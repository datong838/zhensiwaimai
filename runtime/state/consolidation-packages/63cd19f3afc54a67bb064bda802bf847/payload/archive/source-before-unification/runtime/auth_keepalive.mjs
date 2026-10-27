#!/usr/bin/env node
// auth_keepalive.mjs —— 四岗位登录态「真探活 + 保活」（只读+轻量写标记）
//
// v2（2026-10-14）判定核心重写 —— 修 v1 的假阳性盲判
//   v1 判据 = 「页面上下文 fetch SPA 壳路径 + 终 URL 不含登录线索 + HTTP 2xx/3xx」。
//   致命缺陷：SPA 壳在登录态失效时同样返回 200 且不跳转 ⇒ 永远「有效」。
//   实证（2026-10-14）：18:35 保活还报 9231「会话有效」，实则 03:34 起已掉登录，
//   直接导致 4 个 9231 依赖流全天失败（连败 22 轮才发现）。
//   curl 负对照（无 cookie + 忠实请求体）→ {"error":{"code":"UNAUTHORIZED","message":"session 不能为空"}}
//   curl 正对照路径（页面上下文 + 忠实请求体）→ result 正常返回。
//
// v2 判据（按岗位，取「真认证信号」）：
//   9231 open.shop.ele.me（无头）：页面上下文 POST 真认证 API
//     /api/invoke?method=UtilService.isMasterAccount
//     忠实请求体（ncp=2.0.0 / id=HEX32|epochms / metas.ksid 取自 localStorage），
//     头带 Invocation-Protocol: Napos-Communication-Protocol-2。
//     · error.code=UNAUTHORIZED ⇒ 掉登录（负对照实证的签名）
//     · 无 error / result 非空 ⇒ 已登录（该认证调用本身即潜在的服务端会话续期活动）
//     · 其它（ILLEGAL_REQUEST/网络错/非 JSON）⇒ UNKNOWN，退化到渲染文本判据
//   其余岗位：读当前标签渲染文本（业务特征 vs 登录特征）
//     · 命中登录特征 ⇒ 掉登录；命中业务特征 ⇒ 已登录；都不命中 ⇒ UNKNOWN（不猜）
//     · 9233（无头）UNKNOWN 时导航回 imworkbench home 复判一次（无头工位采集器间歇占用，
//       导航同时把标签复位到已知good态，与每日环境复位同向）；9230/9232 有头可见，UNKNOWN 即如实上报
//
// 用法
//   node auth_keepalive.mjs                       # 四岗位逐个探活
//   node auth_keepalive.mjs --ports 9231          # 只探某几个岗位
//   node auth_keepalive.mjs --json                # 结构化输出
//   node auth_keepalive.mjs --notify              # 掉登录时发 macOS 通知（仅状态翻转或>2h 重报，防噪音）
//   node auth_keepalive.mjs --open-login          # 掉登录时有头拉起登录页（v2：会先杀无头实例，带 2h 冷却）
//   node auth_keepalive.mjs --status              # 只看历史摘要
//   node auth_keepalive.mjs --self-test           # 正负对照自检（纯本地，不碰工位）
//
// 退出码：0=无掉登录；3=检出掉登录/端口不可用（needs-attention）；4=跳过（岗位忙）
//
// 边界（严守，不得突破）
//   · 只用现有标签（绝不 newTarget）；不点击、不输入、不提交任何凭证；
//   · 不发任何外发消息、不写游标、不改封印、不触发强制运行；
//   · 9231 必须抢 taobao-svc-post 工位锁，抢不到即跳过（绝不干扰正在跑的采集流）；
//   · 9233 导航复判仅限 UNKNOWN 时一次，不做多余导航。

import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import { spawn, execSync } from 'node:child_process';

const HOME = '/Users/ddt/work/projects/ai_agent/zhensi_waimai_back';
const STATE_DIR = path.join(HOME, 'runtime/state');
const HISTORY = path.join(STATE_DIR, 'auth_keepalive_history.jsonl');
const LAST = path.join(STATE_DIR, 'auth_keepalive_last.json');

// 各岗位目标 URL（权威源=plist）/ 业务特征 / 登录特征
const TARGETS = {
  9230: { role: 'taobao-brand', profile: 'taobao-brand', lease: false,
    url: 'https://melody.shop.ele.me/app/chain/95708808/stats__center#app.chainshop.stats.center',
    host: 'melody.shop.ele.me',
    shell: ['商家首页', '订单管理', '商品管理', '顾客管理', '门店管理', '数据中心', '搜索菜单'],
    login: ['账号登录', '请先选择您的账号类型', '扫码登录', '登录注册', '立即登录'],
    nav: false, minLen: 100 },
  9231: { role: 'taobao-agent-service', profile: 'taobao-agent-service', lease: true,
    url: 'https://open.shop.ele.me/manager/base/home',
    host: 'open.shop.ele.me',
    shell: ['appstore 控制台', '代运营', '客户管理', '意向商户管理', '商家意向列表'],
    login: ['账号登录', '请先选择您的账号类型', '扫码登录', '登录注册', '立即登录'],
    api: { path: '/api/invoke?method=UtilService.isMasterAccount', service: 'UtilService', method: 'isMasterAccount' },
    nav: false, minLen: 100 },
  9232: { role: 'jinsha-business', profile: 'jinsha-business', lease: false,
    url: 'https://data.guoshuyufen.com/#/negativeAnalyse',
    host: 'data.guoshuyufen.com',
    shell: ['数据总览', '实时数据', '门店监控', '店铺列表', '数据中心', '龙虎榜'],
    login: ['账号登录', '密码登录', '扫码登录', '立即登录', '登录/注册'],
    nav: false, minLen: 200 },
  9233: { role: 'meituan-im', profile: 'meituan-merchant', lease: false,
    url: 'https://waimaie.meituan.com/imworkbench/home?appId=4&clientType=140006#/im/page/workbench/reception',
    host: 'waimaie.meituan.com',
    shell: ['顾客消息', '客服管理', '正在接待', '待人工回复', '全部顾客消息', '服务数据'],
    login: ['账号登录', '密码登录', '短信登录', '验证码登录', '请登录', '登录/注册'],
    nav: true, minLen: 200 },
};
const LOGIN_HINTS = ['login', 'passport', 'signin', 'sso', 'oauth'];

// ─── 纯函数：判据可自检（正负对照，不 only-验证「全正常」这一种形状） ───

// 9231 真认证 API 响应判定
export function judgeApiResponse(parsed) {
  if (!parsed || typeof parsed !== 'object') return { state: 'unknown', detail: '响应非 JSON' };
  const code = parsed.error && parsed.error.code;
  if (code === 'UNAUTHORIZED') return { state: 'out', detail: 'API UNAUTHORIZED：' + String(parsed.error.message || '').slice(0, 60) };
  if (parsed.error && (code === 'ILLEGAL_REQUEST' || /TIMEOUT|GATEWAY/i.test(code))) {
    return { state: 'unknown', detail: 'API 请求格式/网关问题：' + String(code) };
  }
  if (parsed.error) return { state: 'unknown', detail: 'API 未预期 error：' + String(code) };
  return { state: 'in', detail: 'API 认证通过（result=' + JSON.stringify(parsed.result).slice(0, 40) + '）' };
}

// 渲染文本判定（URL 登录线索 + 登录特征 + 业务特征）
export function judgeRender(text, url, cfg) {
  const t = String(text || '');
  const lower = String(url || '').toLowerCase();
  const urlLogin = LOGIN_HINTS.some(h => lower.includes(h));
  if (urlLogin) return { state: 'out', detail: 'URL 已跳登录域：' + String(url).slice(0, 70) };
  const loginHit = (cfg.login || []).find(m => t.includes(m));
  if (loginHit) return { state: 'out', detail: '页面命中登录特征：' + loginHit };
  const shellHit = (cfg.shell || []).find(m => t.includes(m));
  if (shellHit) return { state: 'in', detail: '页面命中业务特征：' + shellHit };
  return { state: 'unknown', detail: '业务/登录特征均未命中（len=' + t.length + '）' };
}

export function selfTest() {
  const cfg31 = TARGETS[9231], cfg33 = TARGETS[9233];
  const cases = [
    // ── API 判据（正负对照均来自今天的 curl 实测） ──
    { j: () => judgeApiResponse({ result: true }), want: 'in', name: 'API·正 result=true' },
    { j: () => judgeApiResponse({ result: null }), want: 'in', name: 'API·正 result=null 无 error（isMaster 合法返回）' },
    { j: () => judgeApiResponse({ result: null, error: { code: 'UNAUTHORIZED', message: 'session 不能为空' } }), want: 'out', name: 'API·负 UNAUTHORIZED（curl 无 cookie 实证）' },
    { j: () => judgeApiResponse({ result: null, error: { code: 'ILLEGAL_REQUEST' } }), want: 'unknown', name: 'API·格式错 ⇒ UNKNOWN 不误判' },
    { j: () => judgeApiResponse(null), want: 'unknown', name: 'API·非 JSON ⇒ UNKNOWN' },
    // ── 渲染判据 ──
    { j: () => judgeRender('服务商平台 控制台 代运营 客户管理 全部门店（897家）', 'https://open.shop.ele.me/manager/base/home', cfg31), want: 'in', name: '渲染·正 业务页（今日实测文本）' },
    { j: () => judgeRender('账号登录 请先选择您的账号类型 商家账号 服务商账号', 'https://open.shop.ele.me/login', cfg31), want: 'out', name: '渲染·负 登录页（今日实测文本）' },
    { j: () => judgeRender('顾客消息 客服管理 正在接待 待人工回复', 'https://waimaie.meituan.com/imworkbench/home', cfg33), want: 'in', name: '渲染·正 美团工作台（今日实测文本）' },
    { j: () => judgeRender('账号登录 密码登录 短信登录', 'https://waimaie.meituan.com/login', cfg33), want: 'out', name: '渲染·负 美团登录页' },
    { j: () => judgeRender('白屏加载中', 'https://open.shop.ele.me/manager/base/home', cfg31), want: 'unknown', name: '渲染·都不命中 ⇒ UNKNOWN 不猜' },
  ];
  let pass = 0, fail = 0;
  console.log('self-test v2 判据表（API + 渲染，正负对照）');
  for (const c of cases) {
    const got = c.j().state;
    const hit = got === c.want;
    hit ? pass++ : fail++;
    console.log(`  ${hit ? '✅' : '❌'} ${c.name.padEnd(46)} want=${c.want.padEnd(7)} got=${got}`);
  }
  console.log(`self-test: ${pass} passed, ${fail} failed`);
  return fail;
}

const argv = process.argv.slice(2);
const JSON_OUT = argv.includes('--json');
const NOTIFY = argv.includes('--notify');
const OPEN_LOGIN = argv.includes('--open-login');
const STATUS_ONLY = argv.includes('--status');
const pi = argv.indexOf('--ports');
const PORTS = pi >= 0 && argv[pi + 1]
  ? argv[pi + 1].split(',').map(s => Number(s.trim())).filter(Boolean)
  : Object.keys(TARGETS).map(Number);

const sleep = ms => new Promise(r => setTimeout(r, ms));

function openWs(u, ms = 8000) {
  return new Promise((res, rej) => {
    const w = new WebSocket(String(u).replace('localhost', '127.0.0.1'));
    w.addEventListener('open', () => res(w), { once: true });
    w.addEventListener('error', () => rej(new Error('ws-open-fail')), { once: true });
    setTimeout(() => rej(new Error('ws-open-timeout')), ms);
  });
}
function rpc(w, m, p, ms) {
  const id = Math.floor(Math.random() * 1e9);
  return new Promise((res, rej) => {
    const on = e => { let d; try { d = JSON.parse(e.data); } catch { return; }
      if (d.id === id) { w.removeEventListener('message', on); clearTimeout(t); res(d); } };
    const t = setTimeout(() => { w.removeEventListener('message', on); rej(new Error('timeout:' + m)); }, ms);
    w.addEventListener('message', on);
    w.send(JSON.stringify({ id, method: m, params: p || {} }));
  });
}

function notify(msg) {
  try { spawn('osascript', ['-e', `display notification "${msg}" with title "臻肆看护"`], { stdio: 'ignore' }); } catch {}
}

// v2：杀无头实例再有头重拉（v1 直接调 bg-chrome-up.sh 会被「已在监听」幂等跳过，永远拉不起有头窗口）
// 带 2h 冷却：避免掉登录期间每 20min 反复弹窗。
// v3（2026-10-20）：判无头不再用 `ps -p`（WorkBuddy 沙箱里 ps 返回空 ⇒ 永远判「非无头」⇒ 不杀 ⇒
//   headful 拉起被「已在监听」幂等跳过，openLogin 整链静默失效，#65 同族）。改读 bg-chrome state.json
//   的 mode 字段（权威源：~/Library/Application Support/AOS Background Chrome/<profile>/.aos-background-chrome/）。
function openLogin(cfg, port, cooldownOk) {
  if (!cooldownOk) return;
  try {
    const statePath = `${process.env.HOME}/Library/Application Support/AOS Background Chrome/${cfg.profile}/.aos-background-chrome/state.json`;
    let st = null;
    try { st = JSON.parse(fs.readFileSync(statePath, 'utf8')); } catch {}
    if (st && st.mode === 'headless') {
      // 权威 pid 在 state.json；杀完等端口释放（最长 12s）
      const victims = new Set();
      if (st.pid) victims.add(String(st.pid));
      for (const pid of execSync(`lsof -ti :${port} 2>/dev/null || true`, { encoding: 'utf8' }).trim().split('\n').filter(Boolean)) victims.add(pid);
      for (const pid of victims) { try { spawn('kill', [pid], { stdio: 'ignore' }); } catch {} }
      for (let i = 0; i < 12; i++) {
        try { execSync(`lsof -ti :${port} >/dev/null 2>&1 && exit 1 || exit 0`); break; } catch { execSync('sleep 1'); }
      }
    }
  } catch {}
  try {
    spawn('bash', ['-c',
      `cd ${HOME} && BG_CHROME_LAUNCH=headful bash runtime/bg-chrome-up.sh ${cfg.profile} ${port} '${cfg.url}'`
    ], { stdio: 'ignore', detached: true }).unref();
  } catch {}
}

// 工位互斥：复用 taobao-svc-post 的锁契约（锁存在且未过期且非自己 ⇒ 忙）
const LEASE_TTL_MS = 30 * 60 * 1000;
async function leaseBusy(port) {
  try {
    const cur = JSON.parse(await fs.promises.readFile(`/tmp/zhensi-post-${port}.lock`, 'utf8'));
    if (cur && Date.now() - (cur.acquiredAt || 0) <= LEASE_TTL_MS) return true;
  } catch {}
  return false;
}

async function readTabState(ws) {
  const expr = `(()=>{const t=(document.body?document.body.innerText:'')||'';
    return JSON.stringify({href:location.href,len:t.length,text:t.replace(/\\s+/g,' ').slice(0,600)})})()`;
  const rr = await rpc(ws, 'Runtime.evaluate', { expression: expr, returnByValue: true }, 15000);
  const v = rr.result && rr.result.result && rr.result.result.value;
  if (typeof v !== 'string') return null;
  try { return JSON.parse(v); } catch { return null; }
}

async function probe(port) {
  const cfg = TARGETS[port];
  if (!cfg) return { port, role: 'unconfigured', state: 'unknown', ok: false, detail: '端口未配置' };
  const out = { port, role: cfg.role, cdp: false, state: 'unknown', ok: false, detail: '' };

  // ① 工位被采集流占用 ⇒ 跳过。保活绝不干扰正在跑的业务流。
  if (await leaseBusy(port)) {
    out.detail = 'SKIPPED：工位忙（有采集流占用）'; out.busy = true; return out;
  }

  let ws;
  try {
    const ver = await (await fetch(`http://127.0.0.1:${port}/json/version`, { headers: { Host: 'localhost' } })).json();
    out.cdp = true;
    const list = await (await fetch(`http://127.0.0.1:${port}/json/list`, { headers: { Host: 'localhost' } })).json();
    const pages = list.filter(x => x.type === 'page' && String(x.url || '').includes(cfg.host));
    const tab = pages[0];
    if (!tab) { out.detail = `无目标域(${cfg.host})标签页`; return out; }

    ws = await openWs(tab.webSocketDebuggerUrl);
    await rpc(ws, 'Runtime.enable', {}, 5000).catch(() => {});

    // ② 9231：真认证 API 探活（主判据）
    if (cfg.api) {
      const hex = '0123456789ABCDEF';
      let h32 = '';
      for (let i = 0; i < 32; i++) h32 += hex[Math.floor(Math.random() * 16)];
      const reqId = h32 + '|' + Date.now();
      // ksid 取自 localStorage（SPA 自己就是这么带的；取不到不阻断）
      let ksid = '';
      try {
        const kr = await rpc(ws, 'Runtime.evaluate', { expression: "localStorage.getItem('ksid')||''", returnByValue: true }, 5000);
        ksid = (kr.result && kr.result.result && kr.result.result.value) || '';
      } catch {}
      const metas = { appVersion: '4.4.0', key: '1.0.0', appName: 'Odin' };
      if (ksid) metas.ksid = ksid;
      const body = JSON.stringify({ service: cfg.api.service, method: cfg.api.method, params: {}, id: reqId, metas, ncp: '2.0.0' });
      const expr = `(async()=>{try{
          const r=await fetch(${JSON.stringify(cfg.api.path)},{method:'POST',credentials:'include',
            headers:{'Content-Type':'application/json;charset=UTF-8','Invocation-Protocol':'Napos-Communication-Protocol-2','X-Eleme-RequestID':${JSON.stringify(reqId)}},
            body:${JSON.stringify(body)}});
          const t=await r.text();
          let j=null; try{j=JSON.parse(t)}catch(e){}
          return JSON.stringify({http:r.status, json:j, raw:t.slice(0,120)});
        }catch(e){return JSON.stringify({err:String(e)})}})()`;
      const rr = await rpc(ws, 'Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true }, 30000);
      const v = rr.result && rr.result.result && rr.result.result.value;
      let info = {};
      if (typeof v === 'string') { try { info = JSON.parse(v); } catch {} }
      if (info.err) { out.detail = 'API 调用异常: ' + String(info.err).slice(0, 100); }
      else {
        out.http = info.http;
        const verdict = judgeApiResponse(info.json);
        out.state = verdict.state; out.detail = verdict.detail + '（HTTP ' + info.http + '）';
        if (info.json === null) out.detail += ' raw=' + String(info.raw || '').slice(0, 60);
      }
      // API 判不定 ⇒ 退化渲染文本判据（不导航，免扰采集流）
      if (out.state === 'unknown') {
        const st = await readTabState(ws).catch(() => null);
        if (st) {
          const rv = judgeRender(st.text, st.href, cfg);
          if (rv.state !== 'unknown') { out.state = rv.state; out.detail += ' ⇒ 退化渲染判据：' + rv.detail; }
        }
      }
      if (out.state !== 'unknown') { out.ok = out.state === 'in'; out.url = tab.url.slice(0, 110); return out; }
    }

    // ③ 其余岗位：渲染文本判据
    const st = await readTabState(ws).catch(() => null);
    if (st) {
      const rv = judgeRender(st.text, st.href, cfg);
      out.state = rv.state; out.detail = rv.detail; out.url = st.href.slice(0, 110);
      out.ok = rv.state === 'in';
      if (rv.state !== 'unknown') return out;
    } else {
      out.detail = '读取标签状态失败';
    }

    // ④ UNKNOWN 且岗位允许导航复判（仅 9233 无头）：导航回目标 URL 再来一次
    if (cfg.nav && out.state === 'unknown') {
      await rpc(ws, 'Page.enable', {}, 5000).catch(() => {});
      await rpc(ws, 'Page.navigate', { url: cfg.url }, 15000).catch(() => {});
      await sleep(7000);
      const st2 = await readTabState(ws).catch(() => null);
      if (st2) {
        const rv2 = judgeRender(st2.text, st2.href, cfg);
        out.state = rv2.state; out.detail = '导航复判：' + rv2.detail; out.url = st2.href.slice(0, 110);
        out.ok = rv2.state === 'in';
      }
    }
  } catch (e) {
    out.detail = '保活异常: ' + e.message;
  } finally {
    try { ws && ws.close(); } catch {}
  }
  return out;
}

async function main() {
  if (argv.includes('--self-test')) process.exit(selfTest() ? 1 : 0);
  if (STATUS_ONLY) {
    const lines = fs.existsSync(HISTORY) ? fs.readFileSync(HISTORY, 'utf8').trim().split('\n') : [];
    const rows = lines.slice(-12).map(l => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean);
    for (const r of rows) {
      console.log(`  ${r.at}  ok=${r.ok}  ${r.rows.map(x => `${x.port}:${x.state === 'in' ? 'OK' : (x.busy ? 'BUSY' : String(x.state).toUpperCase())}`).join(' ')}`);
    }
    return;
  }
  const rows = [];
  for (const port of PORTS) rows.push(await probe(port));
  const busy = rows.filter(r => r.busy);
  const bad = rows.filter(r => r.state === 'out');
  const unknown = rows.filter(r => r.state === 'unknown' && !r.busy);
  const at = new Date().toISOString();

  // 通知防噪音：仅状态翻转（上次 ok 本次 out）或距上次告警 >2h
  let prev = null;
  try { prev = JSON.parse(fs.readFileSync(LAST, 'utf8')); } catch {}
  const prevOk = prev && typeof prev.ok === 'boolean' ? prev.ok : true;
  const lastAlertAt = prev && prev.lastAlertAt ? Date.parse(prev.lastAlertAt) : 0;
  const shouldAlert = bad.length > 0 && (!prevOk || Date.now() - lastAlertAt > 2 * 3600 * 1000);

  const rec = { at, ok: bad.length === 0, rows, unknown: unknown.map(r => r.port) };
  if (shouldAlert) rec.lastAlertAt = at;
  else if (prev && prev.lastAlertAt) rec.lastAlertAt = prev.lastAlertAt;
  // 2026-10-21：openLoginAt 冷却记录必须跨轮保留——掉登录后若夹一轮 unknown（如 openLogin 杀实例后的
  // fetch failed），重写 LAST 丢 openLoginAt ⇒ 2h 冷却失效 ⇒ 下轮把刚拉起的 headful 登录窗再杀一次。
  if (prev && prev.openLoginAt) rec.openLoginAt = prev.openLoginAt;
  fs.appendFileSync(HISTORY, JSON.stringify(rec) + '\n');
  fs.writeFileSync(LAST, JSON.stringify(rec, null, 2));

  if (JSON_OUT) console.log(JSON.stringify(rec, null, 2));
  else {
    console.log(`auth-keepalive v2 ${at}`);
    for (const r of rows) {
      const flag = r.busy ? '⏭ 跳过(工位忙)'
        : r.state === 'in' ? '✅ ' + r.detail
        : r.state === 'out' ? '❌ ' + r.detail
        : '⚠️  ' + r.detail;
      console.log(`  :${r.port} ${String(r.role).padEnd(20)} ${flag}${r.url ? '  ' + r.url : ''}`);
    }
  }
  if (shouldAlert && NOTIFY) {
    notify(`登录态告警：${bad.map(r => r.port + '(' + r.role + ')').join('、')} 掉登录，需重新登录`);
  }
  // 掉登录时有头拉起（2h 冷却，防反复弹窗）
  const cooldownOk = !prev || !prev.openLoginAt || Date.now() - Date.parse(prev.openLoginAt) > 2 * 3600 * 1000;
  if (bad.length && OPEN_LOGIN && cooldownOk) {
    // 2026-10-21：先落盘 openLoginAt 再执行拉起（沙箱可能对退出路径投 SIGTERM(143)，
    // 若拉起后再写 LAST，进程被杀则冷却记录丢失 ⇒ 下轮重复弹窗）
    rec.openLoginAt = at;
    fs.writeFileSync(LAST, JSON.stringify(rec, null, 2));
    for (const r of bad) openLogin(TARGETS[r.port], r.port, true);
  }
  process.exit(bad.length ? 3 : (busy.length === rows.length ? 4 : 0));
}
main().catch(e => { console.log(JSON.stringify({ error: e.message })); process.exit(1); });

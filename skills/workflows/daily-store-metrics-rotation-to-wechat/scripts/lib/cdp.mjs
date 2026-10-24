/**
 * CDP 最小工具库（9230 品牌商系统专用）
 *
 * 踩过的坑，全部固化成规则：
 * 1. 外壳 + 跨域 iframe：iframe 不是独立 target，必须取它的 executionContextId
 * 2. 同源会有多个 about:blank context（预渲染/垫片），**只按 origin 取会拿到空壳**
 *    ⇒ 必须 Page.getFrameTree 拿 frame.url，再用 executionContextCreated 的 auxData.frameId 绑定
 * 3. SPA 内导航后 Runtime.enable 不重放 context ⇒ 必须 disable + enable 重放
 * 4. 窗口实际尺寸受 CDP 视口控制，不设 override 会是 800x600
 */

import {guardScreenshot} from './known_overlay.mjs';
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export function connect(wsUrl) {
  return new Promise((res, rej) => {
    const ws = new WebSocket(wsUrl);
    const P = new Map(); const H = new Map(); let seq = 0;
    ws.addEventListener('open', () => res({
      send(method, params = {}, timeout = 90000) {
        const id = ++seq;
        return new Promise((r, j) => {
          const t = setTimeout(() => { P.delete(id); j(new Error('timeout:' + method)); }, timeout);
          P.set(id, { r, j, t });
          ws.send(JSON.stringify({ id, method, params }));
        });
      },
      on(k, f) { H.set(k, (H.get(k) || []).concat([f])); },
      off(k) { H.delete(k); },
      close() { try { ws.close(); } catch {} },
    }));
    ws.addEventListener('message', (e) => {
      let d; try { d = JSON.parse(e.data); } catch { return; }
      if (d.id && P.has(d.id)) {
        const p = P.get(d.id); P.delete(d.id); clearTimeout(p.t);
        if (d.error) p.j(new Error(d.error.message)); else p.r(d.result);
      } else if (d.method && H.has(d.method)) {
        for (const f of H.get(d.method)) { try { f(d.params); } catch {} }
      }
    });
    ws.addEventListener('error', () => rej(new Error('ws error')));
    setTimeout(() => rej(new Error('connect timeout')), 8000);
  });
}

export async function listPages(port) {
  const r = await fetch(`http://127.0.0.1:${port}/json/list`);
  return (await r.json()).filter((t) => t.type === 'page');
}

/**
 * 建立会话：拿 context 收集器 + 常用封装
 */
export async function session({ port = 9230, width = 1440, height = 1500 } = {}) {
  const pages = await listPages(port);
  if (!pages.length) throw new Error('no-page-target');
  // 复用已开页（探针禁止新开标签）
  const candidates=pages.filter(p=>{try{return new URL(p.url).origin==='https://melody.shop.ele.me';}catch{return false;}});
  if(candidates.length!==1)throw Error('brand-page-not-unique');
  const page=candidates[0];
  const cdp = await connect(page.webSocketDebuggerUrl);
  const ctxs = [];
  cdp.on('Runtime.executionContextCreated', (p) => ctxs.push(p.context));
  await cdp.send('Runtime.enable');
  await cdp.send('Page.enable');
  if (width) await cdp.send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false });

  const rearm = async () => {
    ctxs.length = 0;
    await cdp.send('Runtime.disable');
    await cdp.send('Runtime.enable');
    await sleep(1200);
  };

  const mainEval = async (expr, timeout = 60000) =>
    (await cdp.send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true }, timeout)).result?.value;

  /** 按 frame.url 正则绑 contextId（排除 about:blank） */
  const ctxForFrame = async (re, { excludeBlank = true } = {}) => {
    const tree = await cdp.send('Page.getFrameTree');
    const frames = [];
    (function walk(n) { frames.push(n.frame); (n.childFrames || []).forEach(walk); })(tree.frameTree);
    const want = frames.filter((f) => re.test(f.url) && (!excludeBlank || f.url !== 'about:blank'));
    if (!want.length) return { err: 'frame-not-found', frames: frames.map((f) => f.url) };
    // 取最后一个（最新）匹配帧
    const target = want[want.length - 1];
    const ctx = ctxs.filter((x) => x.auxData && x.auxData.frameId === target.id).pop();
    if (!ctx) return { err: 'ctx-not-found', frameId: target.id, url: target.url, known: ctxs.map((x) => ({ id: x.id, frame: x.auxData?.frameId, origin: x.origin })) };
    return { id: ctx.id, url: target.url, frameId: target.id };
  };

  const frameEval = (ctxId) => async (expr, timeout = 60000) =>
    (await cdp.send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true, contextId: ctxId }, timeout)).result?.value;

  const clickAt = async (x, y) => {
    for (const type of ['mousePressed', 'mouseReleased']) {
      await cdp.send('Input.dispatchMouseEvent', { type, x, y, button: 'left', clickCount: 1 });
    }
  };

  /** 轮询直到 fn 返回真值或超时 */
  const waitFor = async (fn, { timeout = 20000, interval = 800, label = 'wait' } = {}) => {
    const t0 = Date.now();
    for (;;) {
      try { const v = await fn(); if (v) return v; } catch {}
      if (Date.now() - t0 > timeout) return null;
      await sleep(interval);
    }
  };

  cdp.send=guardScreenshot(cdp.send.bind(cdp),{mainEval,waitFor});
  const shots = async (clip) => (await cdp.send('Page.captureScreenshot', { format: 'png', clip })).data;

  return { cdp, mainEval, frameEval, ctxForFrame, clickAt, waitFor, rearm, shots, page, sleep };
}

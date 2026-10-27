// 负反馈列表页 · 状态读取与导航门禁
//
// 契约：任何写操作（申诉点击）之前，必须逐项回读并确认下列全部成立，否则 fail-closed。
// 平台分两种模式（jinsha.mjs PLATFORMS.mode）：
//   • status  （美团）：路由/标题/风控/平台tab/时间tab/日期窗口 + 申诉类型(.appeal-filters-box .nav-item active)=全部
//                         + 状态(.status-btn active)=目标状态 + 卡片数<=总数 + 卡片日期落窗内。
//   • category（淘宝）：上述公共门禁 + 分类(.nav_li active)=spec.category（「全部」）。
//                        淘宝**没有**申诉类型/状态 tab，故不校验这两项。
import {
  PLATFORMS, RANGE_DAYS, TIME_RANGE, FEEDBACK, JINSHA_TITLE, clean, parsePassRate, recentRange, sleep,
} from './jinsha.mjs';

/** 采集页面快照（只读，不做任何点击）。 */
const STATE_SCRIPT = `(()=>{
  const T = v => String(v ?? '').replace(/\\s+/g,' ').trim();
  // 卡片容器 = .feedback_list（实测：.feedback_list 命中数与「共 N 条」严格相等。
  // 注意 .feedback 是**整页容器**不是卡片。判据再加一道：必须含 .order_no。
  const cards = [...document.querySelectorAll('.feedback_list')]
    .filter(c => c.offsetParent !== null && c.querySelector('.order_no'))
    .map(c => {
      const btns = [...c.querySelectorAll('.appeal_btn')].filter(b => b.offsetParent !== null);
      return {
        store: T(c.querySelector('.info_name')?.innerText),
        score: Number(T(c.querySelector('.info_score')?.innerText) || 0),
        date: (T(c.innerText).match(/20\\d{2}-\\d{2}-\\d{2}/) || [])[0] || '',
        orderNo: T(c.querySelector('.order_no')?.innerText).replace(/^订单编号[:：]?/, '').trim(),
        channel: T(c.querySelector('.order_type')?.innerText).replace(/^反馈渠道[:：]?/, '').trim(),
        category: T(c.querySelector('.order_problem')?.innerText).replace(/^问题分类[:：]?/, '').trim(),
        preAppeal: T(c.querySelector('.appeal_content')?.innerText).replace(/^申诉内容[:：]?/, '').trim(),
        appealBtnText: T(btns[0]?.innerText),
        hasAppealBtn: btns.length === 1,
      };
    });
  return {
    url: location.href,
    title: document.title,
    risk: /验证码|滑块|账号风险|请重新登录|登录失效/.test(document.body.innerText),
    platform: [...document.querySelectorAll('.optionli')].filter(x => x.offsetParent !== null && x.classList.contains('optionliUp')).map(x => T(x.innerText)).join(','),
    timeTab: [...document.querySelectorAll('.reviewLi')].filter(x => x.offsetParent !== null && x.classList.contains('activate')).map(x => T(x.innerText)).join(','),
    dates: [...document.querySelectorAll('input.el-range-input')].map(x => x.value),
    appealFilter: [...document.querySelectorAll('.appeal-filters-box .nav-item')].filter(x => x.offsetParent !== null && x.classList.contains('active')).map(x => T(x.innerText)).join(','),
    status: [...document.querySelectorAll('.status-btn')].filter(x => x.offsetParent !== null && x.classList.contains('active')).map(x => T(x.innerText).replace(/\\(\\d+\\)\\s*$/, '')).join(','),
    statusCounts: Object.fromEntries([...document.querySelectorAll('.status-btn')].filter(x => x.offsetParent !== null)
      .map(x => { const m = T(x.innerText).match(/^(.+?)\\((\\d+)\\)\\s*$/); return m ? [m[1], Number(m[2])] : null; }).filter(Boolean)),
    // 淘宝视图专用：.nav_li 分类筛选（全部 / 食品安全负反馈率 / 服务负反馈率），active = 当前选中
    category: [...document.querySelectorAll('.nav_li')].filter(x => x.offsetParent !== null && x.classList.contains('active')).map(x => T(x.innerText).replace(/\\(\\d+\\)\\s*$/, '')).join(','),
    categoryCounts: Object.fromEntries([...document.querySelectorAll('.nav_li')].filter(x => x.offsetParent !== null)
      .map(x => { const m = T(x.innerText).match(/^(.+?)\\((\\d+)\\)/); return m ? [m[1], Number(m[2])] : null; }).filter(Boolean)),
    total: T(document.querySelector('.el-pagination__total')?.innerText),
    pageActive: Number(([...document.querySelectorAll('.el-pager li')].find(x => x.classList.contains('active'))?.innerText || '').trim()) || 0,
    cards,
  };
})()`;

export async function readState(cdp) {
  const state = await cdp.eval(STATE_SCRIPT);
  const totalMatch = state.total.match(/共\s*(\d+)\s*条/);
  state.totalNumber = totalMatch ? Number(totalMatch[1]) : state.cards.length;
  state.cards = state.cards.map(card => ({ ...card, passRate: parsePassRate(card.appealBtnText) }));
  return state;
}

/** 门禁断言：任一不符抛错，绝不进入写操作。 */
export function assertState(state, { platformKey, status, window }) {
  const spec = PLATFORMS.find(p => p.key === platformKey);
  if (!spec) throw Error(`platform-key-invalid:${platformKey}`);
  const [start, end] = window;
  if (state.url !== FEEDBACK) throw Error('feedback-route-readback-mismatch');
  if (state.title !== JINSHA_TITLE) throw Error('feedback-title-mismatch');
  if (state.risk) throw Error('feedback-risk-detected');
  // 平台只看顶部 .optionli；左侧渠道保持默认不参与判定（切它会毁掉整页结构）
  if (state.platform !== spec.option) throw Error(`feedback-platform-tab-mismatch:${state.platform}`);
  if (state.timeTab !== TIME_RANGE) throw Error(`feedback-time-tab-mismatch:${state.timeTab}`);
  if (state.dates.length !== 2 || state.dates[0] !== start || state.dates[1] !== end) {
    throw Error(`feedback-date-window-mismatch:${state.dates.join('~')}`);
  }
  // 平台专属维度门禁
  if (spec.mode === 'status') {
    if (state.appealFilter !== '全部') throw Error(`feedback-appeal-filter-mismatch:${state.appealFilter}`);
    if (status && state.status !== status) throw Error(`feedback-status-mismatch:${state.status}`);
  } else if (spec.mode === 'category') {
    if (state.category !== spec.category) throw Error(`feedback-category-mismatch:${state.category}`);
  }
  if (state.cards.some(c => !c.date || c.date < start || c.date > end)) {
    throw Error(`feedback-card-date-out-of-window:${JSON.stringify(state.cards.map(c => c.date))}`);
  }
  if (!Number.isInteger(state.totalNumber) || state.cards.length > state.totalNumber) {
    throw Error(`feedback-card-count-invalid:${state.totalNumber}:${state.cards.length}`);
  }
  if (state.totalNumber > 0 && state.cards.length === 0) throw Error(`feedback-declared-cards-missing:${state.totalNumber}`);
  return true;
}

/** 候选集合签名：只含可申诉条目的稳定键。 */
export const candidateSignature = state =>
  state.cards.filter(c => c.hasAppealBtn).map(c => `${c.store}|${c.date}|${c.orderNo}`).sort().join('#');

/** 连续两次读到同一签名才接受（空集合也必须稳定），防异步渲染误判。 */
export async function readStableState(cdp, gate, { attempts = 16, intervalMs = 700, pause = sleep } = {}) {
  let previous = null, last = null;
  for (let attempt = 0; attempt < attempts; attempt++) {
    last = await readState(cdp);
    assertState(last, gate);
    const signature = candidateSignature(last);
    if (signature === previous) return last;
    previous = signature;
    await pause(intervalMs);
  }
  throw Error(`feedback-candidate-list-not-stable:${previous}`);
}

/** 点击某个元素并轮询等「期望回读」成立（页面异步重排，点完立刻读会拿到旧状态）。 */
async function clickUntil(cdp, { probe, clickBody, expected, errorCode, attempts = 20, intervalMs = 700 }) {
  for (let attempt = 0; attempt < attempts; attempt++) {
    const before = await probe();
    if (before === expected) return true;
    if (before !== null) await cdp.eval(clickBody);
    await sleep(intervalMs);
  }
  const final = await probe();
  if (final === expected) return true;
  throw Error(`${errorCode}-not-applied:${final}`);
}

/**
 * 进入负反馈列表页并锁定平台 / 时间 / 维度筛选。
 *
 * ★ 关键（2026-10-06 实机踩坑，勿改）：全程**不切左侧渠道**（.cutli）。
 *   左侧渠道切到「淘宝」会把整页换成淘宝渠道后台 —— 顶部变成「总览/营业/顾客/智能斗金」，
 *   `.appeal-filters-box` 与 `.status-btn` **双双消失**（count=0），日期默认跳「近1个月」。
 *   平台切换只用顶部 `.optionli`，两个平台共用同一份列表数据。
 *
 * 平台分模式：
 *   • status  （美团）：申诉类型(.appeal-filters-box .nav-item)=全部 + 状态(.status-btn)=未申诉
 *   • category（淘宝）：分类(.nav_li)=spec.category（「全部」）。无申诉类型/状态 tab。
 */
export async function openFilteredPage(cdp, { platformKey, status, window = recentRange() }) {
  const spec = PLATFORMS.find(p => p.key === platformKey);
  if (!spec) throw Error(`platform-key-invalid:${platformKey}`);
  // 美团用「申诉类型全部 + 状态未申诉」；淘宝无状态维度，status 不参与
  const resolvedStatus = spec.mode === 'status' ? (status || spec.appealStatus) : undefined;
  const gate = { platformKey, status: resolvedStatus, window };
  const [start, end] = window;
  const { navigate, entryProbe, assertJinshaEntry, HOME } = await import('./jinsha.mjs');

  // 1) 首页入口门禁 + 进入负反馈列表（渠道上下文保持默认，不切换）。
  //    导航偶发未在 3s 内就绪（上一会话残留弹窗/重定向），门禁失败重试至多 3 次。
  let entryErr = null;
  for (let attempt = 0; attempt < 3; attempt++) {
    await navigate(cdp, HOME, 3000);
    try {
      assertJinshaEntry(await cdp.eval(entryProbe), { home: HOME });
      entryErr = null;
      break;
    } catch (e) {
      entryErr = e;
      await new Promise(r => setTimeout(r, 1500));
    }
  }
  if (entryErr) throw entryErr;
  await navigate(cdp, FEEDBACK, 3500);
  const landed = await cdp.eval(entryProbe);
  assertJinshaEntry(landed, { home: FEEDBACK, errorCode: 'feedback-route-or-login-gate' });

  // 2) 平台 tab（.optionli 全部 / 美团 / 淘宝）
  await clickUntil(cdp, {
    probe: () => cdp.eval(`(()=>[...document.querySelectorAll('.optionli')].filter(x=>x.offsetParent!==null&&x.classList.contains('optionliUp')).map(x=>x.innerText.trim()).join(','))()`),
    clickBody: `(()=>{const t=[...document.querySelectorAll('.optionli')].filter(x=>x.offsetParent!==null&&x.innerText.trim()===${JSON.stringify(spec.option)});if(t.length!==1)throw Error('platform-tab-count:'+t.length);if(!t[0].classList.contains('optionliUp'))t[0].click();return true})()`,
    expected: spec.option,
    errorCode: 'feedback-platform-tab',
  });

  // 3) 时间快捷 tab（近7日）
  await clickUntil(cdp, {
    probe: () => cdp.eval(`(()=>[...document.querySelectorAll('.reviewLi')].filter(x=>x.offsetParent!==null&&x.classList.contains('activate')).map(x=>x.innerText.trim()).join(','))()`),
    clickBody: `(()=>{const t=[...document.querySelectorAll('.reviewLi')].filter(x=>x.offsetParent!==null&&x.innerText.trim()===${JSON.stringify(TIME_RANGE)});if(t.length!==1)throw Error('time-tab-count:'+t.length);if(!t[0].classList.contains('activate'))t[0].click();return true})()`,
    expected: TIME_RANGE,
    errorCode: 'feedback-time-tab',
  });

  // 4) 日期窗口回读（平台「近7日」= 今天-7 至 今天-1，不含今天）
  let dates = [];
  for (let attempt = 0; attempt < 12; attempt++) {
    dates = await cdp.eval(`(()=>[...document.querySelectorAll('input.el-range-input')].map(x=>x.value))()`);
    if (dates.length === 2 && dates[0] === start && dates[1] === end) break;
    await sleep(500);
  }
  if (dates.length !== 2 || dates[0] !== start || dates[1] !== end) {
    throw Error(`feedback-date-window-readback-mismatch:${dates.join('~')}:${start}~${end}`);
  }

  if (spec.mode === 'status') {
    // 5) 申诉类型大 tab（全部 / AI申诉 / 商家申诉）—— 显式点「全部」，不依赖默认值
    await clickUntil(cdp, {
      probe: () => cdp.eval(`(()=>[...document.querySelectorAll('.appeal-filters-box .nav-item')].filter(x=>x.offsetParent!==null&&x.classList.contains('active')).map(x=>x.innerText.trim()).join(','))()`),
      clickBody: `(()=>{const t=[...document.querySelectorAll('.appeal-filters-box .nav-item')].filter(x=>x.offsetParent!==null&&x.innerText.trim()==='全部');if(t.length!==1)throw Error('appeal-type-tab-count:'+t.length);if(!t[0].classList.contains('active'))t[0].click();return true})()`,
      expected: '全部',
      errorCode: 'feedback-appeal-type-tab',
    });
    // 6) 申诉状态 tab（未申诉 / 申诉中 / 申诉成功 / 申诉失败）
    if (resolvedStatus) {
      await clickUntil(cdp, {
        probe: () => cdp.eval(`(()=>[...document.querySelectorAll('.status-btn')].filter(x=>x.offsetParent!==null&&x.classList.contains('active')).map(x=>x.innerText.trim().replace(/\\(\\d+\\)\\s*$/,'')).join(','))()`),
        clickBody: `(()=>{const t=[...document.querySelectorAll('.status-btn')].filter(x=>x.offsetParent!==null&&x.innerText.trim().startsWith(${JSON.stringify(resolvedStatus)}));if(t.length!==1)throw Error('status-tab-count:'+t.length);if(!t[0].classList.contains('active'))t[0].click();return true})()`,
        expected: resolvedStatus,
        errorCode: 'feedback-status-tab',
      });
    }
  } else if (spec.mode === 'category') {
    // 5') 淘宝分类筛选（.nav_li）—— 显式点「全部」（默认激活的是「食品安全负反馈率」）
    await clickUntil(cdp, {
      probe: () => cdp.eval(`(()=>[...document.querySelectorAll('.nav_li')].filter(x=>x.offsetParent!==null&&x.classList.contains('active')).map(x=>x.innerText.trim().replace(/\\(\\d+\\)\\s*$/,'')).join(','))()`),
      clickBody: `(()=>{const t=[...document.querySelectorAll('.nav_li')].filter(x=>x.offsetParent!==null&&x.innerText.trim().startsWith(${JSON.stringify(spec.category)}));if(t.length!==1)throw Error('category-tab-count:'+t.length);if(!t[0].classList.contains('active'))t[0].click();return true})()`,
      expected: spec.category,
      errorCode: 'feedback-category-tab',
    });
  }

  return readStableState(cdp, gate);
}

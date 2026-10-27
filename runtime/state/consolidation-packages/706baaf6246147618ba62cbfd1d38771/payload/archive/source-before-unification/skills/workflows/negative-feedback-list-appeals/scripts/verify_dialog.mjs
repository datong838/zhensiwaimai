// 弹窗交互路径实机验证（写路径预演，但不提交）：
//   点「立即申诉」→ 读弹窗（执行器同款 readStableDialog 契约）→ 点「取消」→ 回读弹窗关闭且卡片仍在。
// 不点「确定」、不写 md、不发消息。每平台只取第一张候选卡。
import { PLATFORMS, recentRange, businessDate, Cdp, navigate, HOME, clean, sleep } from './jinsha.mjs';
import { openFilteredPage, readState } from './page_state.mjs';
import { clickAppeal, readStableDialog } from './appeal_executor.mjs';

const win = recentRange();
const cdp = await Cdp.open();
const out = { ok: false, businessDate: businessDate(), window: win, platforms: {}, runtimeModelDecisions: 0 };

/** 点「取消」—— 必须唯一可见；随后轮询等弹窗真正关闭。 */
async function cancelDialog(cdp) {
  const clicked = await cdp.eval(`(()=>{
    const dlg = [...document.querySelectorAll('.appeal-custom-dialog')].filter(d => d.offsetParent !== null)[0];
    if (!dlg) throw Error('feedback-dialog-missing');
    const btns = [...dlg.querySelectorAll('.dialog-footer button, .dialog-footer .el-button')]
      .filter(b => b.offsetParent !== null && String(b.innerText).replace(/\\s+/g, '') === '取消');
    if (btns.length !== 1) throw Error('feedback-cancel-button-count:' + btns.length);
    btns[0].click();
    return true;
  })()`);
  if (clicked !== true) throw Error('feedback-cancel-click-failed');
  for (let attempt = 0; attempt < 15; attempt++) {
    await sleep(600);
    const open = await cdp.eval(`(()=>[...document.querySelectorAll('.appeal-custom-dialog')].filter(d=>d.offsetParent!==null).length)()`);
    if (open === 0) return true;
  }
  return false;
}

try {
  for (const spec of PLATFORMS) {
    const resolvedStatus = spec.mode === 'status' ? spec.appealStatus : undefined;
    const gate = { platformKey: spec.key, status: resolvedStatus, window: win };
    let state = await openFilteredPage(cdp, { platformKey: spec.key, status: resolvedStatus, window: win });
    const target = state.cards.find(c => c.hasAppealBtn);
    if (!target) {
      out.platforms[spec.key] = { label: spec.label, mode: spec.mode, result: 'no-candidate-on-page', total: state.totalNumber };
      continue;
    }
    const r = { label: spec.label, mode: spec.mode, total: state.totalNumber, target: { store: target.store, date: target.date, orderNo: target.orderNo } };

    // ① 点「立即申诉」（执行器同款定位逻辑）
    await clickAppeal(cdp, target);

    // ② 读弹窗（执行器同款稳定读取契约）
    const dialog = await readStableDialog(cdp);
    r.dialogOpened = !!dialog;
    if (dialog) {
      r.dialogTextLen = dialog.text.length;
      r.dialogTextHead = dialog.text.slice(0, 60);
      r.dialogOrder = dialog.order;
      r.dialogButtons = dialog.buttons;
      r.orderMatch = !dialog.order || clean(dialog.order) === target.orderNo;
    }

    // ③ 点「取消」（绝不点确定）+ 回读弹窗关闭
    if (dialog) {
      r.cancelClicked = await cancelDialog(cdp);
      // ④ 回读：目标卡片仍在当前列表且按钮恢复可见（未发生任何提交）
      for (let attempt = 0; attempt < 12; attempt++) {
        await sleep(700);
        try {
          const after = await readState(cdp);
          const still = after.cards.find(c => c.store === target.store && c.date === target.date && c.orderNo === target.orderNo);
          if (still && still.hasAppealBtn) { r.cardStillAppealable = true; break; }
        } catch { /* 异步重排重试 */ }
      }
      r.cardStillAppealable = r.cardStillAppealable === true;
    }
    r.result = (dialog && r.orderMatch !== false && r.cancelClicked && r.cardStillAppealable) ? 'pass' : 'fail';
    out.platforms[spec.key] = r;
  }
  out.ok = Object.values(out.platforms).every(p => p.result === 'pass' || p.result === 'no-candidate-on-page');
} catch (error) {
  out.error = String(error.message || error);
  out.stack = String(error.stack || '').split('\n').slice(0, 6).join('\n');
} finally {
  try { await navigate(cdp, HOME, 1000); } catch { /* noop */ }
  cdp.close();
}
console.log(JSON.stringify(out, null, 1));

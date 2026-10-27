export function bindReminderAction(info){
 if(!info)return 'none';
 if(info.title!=='绑定手机号提醒'||!info.text.includes('建议绑定手机号')||/验证码|安全验证|滑动验证|拖动滑块|账号存在风险|扫码登录/.test(info.text))throw Error('unknown-modal-blocked');
 if(info.buttons.filter(x=>x.replace(/\s+/g,'')==='跳过').length!==1)throw Error('bind-skip-not-unique');
 return 'skip';
}
export async function dismissBindReminder(s){
 const result=await s.mainEval(`(()=>{
  const visible=e=>{const r=e.getBoundingClientRect(),cs=getComputedStyle(e);return r.width>0&&r.height>0&&cs.display!=='none'&&cs.visibility!=='hidden';};
  const wraps=[...document.querySelectorAll('.ant-modal-wrap,.cook-modal-wrap')].filter(visible);
  if(!wraps.length)return {action:'none'};if(wraps.length!==1)return {error:'multiple-modal-blocked'};
  const w=wraps[0],buttons=[...w.querySelectorAll('button')].filter(visible);
  const info={title:(w.querySelector('.ant-modal-title,.cook-modal-title')?.innerText||'').trim(),text:w.innerText,buttons:buttons.map(b=>b.innerText.trim())};
  try{(${bindReminderAction.toString()})(info);}catch(e){return {error:e.message};}
  buttons.find(b=>b.innerText.replace(/\\s+/g,'')==='跳过').click();return {action:'skipped-bind-reminder'};
 })()`);
 if(!result||result.error)throw Error(result?.error||'modal-check-failed');
 if(result.action!=='none'){
  const gone=await s.waitFor(()=>s.mainEval(`![...document.querySelectorAll('.ant-modal-wrap,.cook-modal-wrap')].some(e=>e.getBoundingClientRect().height>0&&getComputedStyle(e).display!=='none'&&(e.innerText||'').includes('绑定手机号提醒'))`),{timeout:4000,interval:200});
  if(!gone)throw Error('bind-reminder-still-visible');
 }
 return result.action;
}

// All capture paths use this guard; an unknown or unreadable modal fails closed.
export function guardScreenshot(send,session){
 return async (method,params={},timeout)=>{
  if(method==='Page.captureScreenshot')await dismissBindReminder(session);
  return send(method,params,timeout);
 };
}

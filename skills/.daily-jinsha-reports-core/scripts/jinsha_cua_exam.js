import fs from 'node:fs/promises';

const DEFAULT_LEASE_PATH='/tmp/zhensi-jinsha-cua-exam.lock';
const DEFAULT_LEASE_TTL_MS=30*60*1000;

async function acquireJinshaLease(runId, leasePath=DEFAULT_LEASE_PATH, ttlMs=DEFAULT_LEASE_TTL_MS) {
  const now=Date.now();
  const payload={runId,pid:typeof process==='undefined'?null:process.pid,acquiredAt:now};
  for(let attempt=0;attempt<2;attempt++) {
    try {
      const handle=await fs.open(leasePath,'wx',0o600);
      await handle.writeFile(JSON.stringify(payload));
      await handle.close();
      return {...payload,path:leasePath};
    } catch(error) {
      if(error?.code!=='EEXIST')throw error;
      let existing={};
      try {existing=JSON.parse(await fs.readFile(leasePath,'utf8'));} catch {}
      const acquiredAt=Number(existing?.acquiredAt);
      if(attempt===0 && Number.isFinite(acquiredAt) && now-acquiredAt>ttlMs) {
        await fs.unlink(leasePath).catch(unlinkError=>{if(unlinkError?.code!=='ENOENT')throw unlinkError;});
        continue;
      }
      throw Error('jinsha-lease-busy:'+String(existing?.runId||'unknown'));
    }
  }
  throw Error('jinsha-lease-acquire-failed');
}

async function releaseJinshaLease(lease) {
  if(!lease)return false;
  let existing={};
  try {existing=JSON.parse(await fs.readFile(lease.path,'utf8'));} catch(error) {
    if(error?.code==='ENOENT')return false;
    throw error;
  }
  if(existing?.runId!==lease.runId || existing?.acquiredAt!==lease.acquiredAt)
    throw Error('jinsha-lease-owner-mismatch');
  await fs.unlink(lease.path);
  return true;
}

// Load this function into the persistent CUA REPL during untimed preparation.
// API-only desktop adapter; no shell/browser/CDP fallback.
async function runJinshaCuaExam(app, config) {
  const startedAt = Date.now();
  const deadline = startedAt + 180000;
  if(!config?.runId || typeof config.runId!=='string')throw Error('run-id-required');
  const platforms=config.platforms || ['meituan','taobao'];
  if(!Array.isArray(platforms) || platforms.length<1 || new Set(platforms).size!==platforms.length ||
     platforms.some(value=>!['meituan','taobao'].includes(value)))throw Error('platforms-invalid');
  const result = {ok:false, runId:config.runId, startedAt, deadline, clicks:{meituan:0,taobao:0}, files:{...(config.completedFiles || {})}, stage:'start', nodes:[]};
  let lease;
  let nodeStart=startedAt;
  const stage = name => { if(result.stage!=='start')result.nodes.push({name:result.stage,elapsedMs:Date.now()-nodeStart});result.stage=name;nodeStart=Date.now(); };
  const guard = () => {result.efficiencyExceeded=Date.now()>deadline;};
  const state = async () => {guard(); return app.getAXState({emit:false,disableDiffing:true});};
  const index = (text,re) => {
    const matches=text.split('\n').filter(line=>re.test(line));
    if(matches.length!==1)throw Error('element-not-unique:'+re+':'+matches.length);
    return Number(matches[0].match(/^\s*(\d+)/)[1]);
  };
  const click = async (text,re) => {guard();await app.click(index(text,re));return state();};
  const until = async (predicate) => {
    const readyDeadline = Date.now()+8000;
    for(let n=0;n<100 && Date.now()<readyDeadline;n++){const s=await state();if(predicate(s))return s;}
    throw Error('state-not-ready');
  };
  try {
    lease=await acquireJinshaLease(config.runId,config.leasePath,config.leaseTtlMs);
    result.lease={path:lease.path,acquiredAt:lease.acquiredAt,released:false};
    let s=await state();
    if(!s.includes('data.guoshuyufen.com/#/reportDownload'))throw Error('wrong-page');
    await app.performSecondaryAction(0,'Raise');
    s=await state();
    for(const platform of platforms) {
      stage(platform+'.platform');
      await app.performSecondaryAction(0,'Raise');s=await state();
      const label=platform==='meituan'?'美团外卖':'淘宝闪购';
      if(!s.includes(`单选按钮 ${label}, Value: 1`))s=await click(s,new RegExp(`^\\s*\\d+ 单选按钮 ${label}, Value:`));
      if(!s.includes(`单选按钮 ${label}, Value: 1`))s=await until(t=>t.includes(`单选按钮 ${label}, Value: 1`));
      stage(platform+'.date');
      for(const field of ['开始日期','结束日期']) {
        guard();await app.setValue(index(s,new RegExp('^\\s*\\d+ 文本栏.*'+field)),config.businessDate);
        await app.pressKey(field==='开始日期'?'Tab':'Return');s=await state();
      }
      if(!s.includes(`Value: ${config.businessDate}, Placeholder: 开始日期`) ||
         !s.includes(`Value: ${config.businessDate}, Placeholder: 结束日期`))throw Error('date-not-yesterday');
      stage(platform+'.plan');
      const plan=platform==='meituan'?'最终美团最新日报':'饿了么日报数据📊6.18最新最新';
      const optionPattern=platform==='meituan'?/^\s*\d+ 文本 最终美团最新日报$/:/^\s*\d+ 文本 饿了么(?:日报数据📊6\.18|\.\.\.)最新最新$/;
      if(!s.includes('Value: '+plan)) {
        if(!s.split('\n').some(line=>/^\s*\d+ 文本栏.*请选择下载方案/.test(line)))
          s=await until(t=>t.split('\n').some(line=>/^\s*\d+ 文本栏.*请选择下载方案/.test(line)));
        s=await click(s,/^\s*\d+ 文本栏.*(?:请选择下载方案|Placeholder: 请选择下载方案)/);
        if(!s.split('\n').some(line=>optionPattern.test(line)))
          s=await until(t=>t.split('\n').some(line=>optionPattern.test(line)));
        s=await click(s,optionPattern);
        if(!s.includes('Value: '+plan))s=await until(t=>t.includes('Value: '+plan));
      }
      if(!s.includes(`Value: ${config.businessDate}, Placeholder: 开始日期`) ||
         !s.includes(`Value: ${config.businessDate}, Placeholder: 结束日期`))throw Error('date-not-yesterday');
      stage(platform+'.metrics');
      if(platform==='taobao' && s.includes('已选择 (34)')) {
        if(!Array.isArray(config.metrics?.paid) || config.metrics.paid.length!==2 ||
           !Array.isArray(config.metrics?.net) || config.metrics.net.length!==2)
          throw Error('metric-coordinates-required');
        // 本次固定窗口截图校准值；未最大化/缩放/切换窗口尺寸，位置已现场观察。
        guard(); await app.click(config.metrics.paid); s=await state();
        if(!s.includes('已选择 (35)'))s=await until(t=>t.includes('已选择 (35)'));
        guard(); await app.click(config.metrics.net); s=await state();
        if(!s.includes('已选择 (36)'))s=await until(t=>t.includes('已选择 (36)'));
      }
      if(!s.includes('已选择 (36)'))throw Error('metric-count-not-36');
      if(!s.includes(`单选按钮 ${label}, Value: 1`) || !s.includes('Value: '+plan))throw Error('platform-plan-mismatch');
      stage(platform+'.download-save');
      const downloadStartedAt=Date.now();
      result.clicks[platform]++;
      s=await click(s,/^\s*\d+ 按钮 .*下载数据$/);
      if(!s.includes('saveAsNameTextField'))s=await until(t=>t.includes('saveAsNameTextField'));
      guard();await app.setValue(index(s,/^\s*\d+ 文本栏.*ID: saveAsNameTextField/),config.names[platform]);
      s=await state();
      if(!s.includes('Value: '+config.names[platform]))throw Error('save-name-mismatch');
      s=await click(s,/^\s*\d+ 按钮 存储, ID: OKButton$/);
      if(s.includes('saveAsNameTextField'))s=await until(t=>!t.includes('saveAsNameTextField'));
      result.files[platform]={name:config.names[platform],downloadStartedAt,savedAt:Date.now()};
    }
    if(!result.files.meituan?.savedAt || !result.files.taobao?.savedAt)throw Error('download-files-incomplete');
    // From this point onward the desktop resource is released. Do not call app APIs.
    stage('complete');result.ok=true;
    result.jinshaResourceReleased=true;
    result.jinshaReleasedAt=Date.now();
    result.receiptIssuedAt=Date.now();
  } catch(error) {result.reason=String(error.message||error);}
  finally {
    if(lease) {
      try {
        const released=await releaseJinshaLease(lease);
        result.lease={...result.lease,released,releasedAt:Date.now()};
      } catch(error) {
        result.ok=false;result.reason='jinsha-lease-release-failed:'+String(error.message||error);
      }
    }
  }
  if(!result.ok)result.nodes.push({name:result.stage,elapsedMs:Date.now()-nodeStart,failed:true});
  result.elapsedMs=Date.now()-startedAt;
  return result;
}
export { acquireJinshaLease, releaseJinshaLease, runJinshaCuaExam };

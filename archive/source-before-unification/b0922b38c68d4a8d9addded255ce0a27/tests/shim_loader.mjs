// ESM 自定义加载器（zhensi_waimai_back Node 单测专用）。生产代码零改动。
// 职责：
//   1) 拦截 'playwright-core' → 内存假实现（connect.mjs 无需真实浏览器/CDP）。
//   2) 拦截 executor 对 'business_workflow_policy.mjs' 的导入 →
//      - 桩掉 assertProductionConfig / assertFrozenCoreHashes（零副作用、确定性）；
//      - 把 FIXED.runsRoot 重定向到临时目录（allocateRun/loadRun/attemptMarker 全变 hermetic）；
//      - 其余导出（buildProductionConfig/classify*/FIXED.group 等）保持真实。
//   3) 拦截 executor 对 'node:child_process' 的导入 → 指向内存假 execFile 实现，
//      从而离线驱动 download/prepare/send/verify 各 phase 而不拉起真实流水线。
//
// 关键：executor 源码【不做任何改写】——只重定向它导入的模块。这样 c8 对 executor 的
// 插桩/覆盖映射是可靠的（改写源码会让 V8 覆盖行号错位，导致 phantom 未覆盖行）。

const PLAYWRIGHT_SHIM_URL = 'node:playwright-core-shim';
// 假 chromium：默认 contexts()→[{pages:()=>[{fake:'page'}], newPage: async()=>({fake:'page'})}]
// 同时满足简单岗 `context.pages()[0] || await context.newPage()` 与 jinsha 岗页面断言助手。
// 测试可通过 globalThis.__TEST_CONNECT_OVERRIDE__ 注入自定义 browser（覆盖默认），用于触发
// 缺 context 抛错 / 空 pages→newPage 分支；所有 connect 测试经 withConnectLock 串行化，避免并发污染全局。
const PLAYWRIGHT_SHIM = `export const chromium={connectOverCDP: async(cdp)=>{const o=globalThis.__TEST_CONNECT_OVERRIDE__;if(o)return typeof o==='function'?o(cdp):o;return {contexts:()=>[{pages:()=>[{fake:'page'}], newPage: async()=>({fake:'page'})}]};}};`;

// 仅当 executor 导入 node:child_process 时拦截。executor 用 promisify(execFileCb) 包成 execFile；
// 这里 execFileCb 把调用转给 globalThis.__EXEC_EXEC_FILE__（各测试分别注入），并把其结果/错误桥接回 callback。
const EXECFILE_SHIM_URL = 'node:execfile-shim';
const EXECFILE_SHIM = `export const execFile = (cmd, args, opts, cb) => {
  const fn = globalThis.__EXEC_EXEC_FILE__;
  if (typeof fn !== 'function') return cb(new Error('no fake execFile set for executor under test'));
  Promise.resolve().then(() => fn(cmd, args, opts)).then(
    (res) => cb(null, res),
    (err) => cb(err)
  );
};`;

// 仅在 executor 导入 policy 时注入（用 parentURL 区分，测试自身的 policy 直接导入保持真实）
let REAL_POLICY_URL = null;
const POLICY_SHIM_URL = 'node:policy-shim';

export async function resolve(specifier, context, nextResolve) {
  if (specifier === 'playwright-core') return {url: PLAYWRIGHT_SHIM_URL, shortCircuit: true};
  if (specifier === 'node:child_process' && context.parentURL && context.parentURL.includes('business_workflow_executor.mjs')) {
    return {url: EXECFILE_SHIM_URL, shortCircuit: true};
  }
  if (specifier.endsWith('business_workflow_policy.mjs') && context.parentURL && context.parentURL.includes('business_workflow_executor.mjs')) {
    REAL_POLICY_URL = new URL(specifier, context.parentURL).href;
    return {url: POLICY_SHIM_URL, shortCircuit: true};
  }
  return nextResolve(specifier, context);
}

export async function load(url, context, nextLoad) {
  if (url === PLAYWRIGHT_SHIM_URL) return {format: 'module', source: PLAYWRIGHT_SHIM, shortCircuit: true};
  if (url === EXECFILE_SHIM_URL) return {format: 'module', source: EXECFILE_SHIM, shortCircuit: true};
  if (url === POLICY_SHIM_URL) {
    const source = `
import * as __REAL_POLICY__ from ${JSON.stringify(REAL_POLICY_URL)};
export * from ${JSON.stringify(REAL_POLICY_URL)};
export const FIXED = {...__REAL_POLICY__.FIXED, runsRoot: globalThis.__TEST_RUNS_ROOT__ || '/tmp/zhensi-test-runs'};
export function assertProductionConfig(){return {day:'20260930',suffix:'01',runDir:'',outputDir:''};}
export async function assertFrozenCoreHashes(){return {ok:true,count:18};}
`;
    return {format: 'module', source, shortCircuit: true};
  }
  return nextLoad(url, context);
}

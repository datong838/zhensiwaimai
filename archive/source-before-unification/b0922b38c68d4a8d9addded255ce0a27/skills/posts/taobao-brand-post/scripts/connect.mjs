import {chromium} from 'playwright-core';
// 连接本岗位专用工位（端口固定）。登录态/遮罩/业务判定交给调用方（流水线），本文件只负责「连到正确的浏览器」。
const PORT = 9230;
export async function connectToPost() {
  const browser = await chromium.connectOverCDP(`http://127.0.0.1:${PORT}`);
  const context = browser.contexts()[0];
  if (!context) throw Error('post-taobao-brand-post-context-missing');
  const page = context.pages()[0] || await context.newPage();
  return { browser, context, page };
}

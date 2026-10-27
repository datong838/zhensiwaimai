// 9231 裸 CDP 探针：node 原生 WebSocket + 硬超时（禁止任何第三方 ws 模块）
// 用途：验证 9231 后台 Chrome 的 CDP 真实可达（不止端口监听）。
const PORT = process.env.PROBE_PORT || 9231;
const HARD_TIMEOUT = Number(process.env.PROBE_TIMEOUT_MS || 8000);
const HOST = '127.0.0.1';

function httpGet(path) {
  return fetch(`http://${HOST}:${PORT}${path}`).then(r => r.text());
}

async function main() {
  const listTxt = await httpGet('/json/list');
  const list = JSON.parse(listTxt);
  const page = (list.find(t => t.type === 'page' && t.webSocketDebuggerUrl) || list.find(t => t.webSocketDebuggerUrl));
  if (!page || !page.webSocketDebuggerUrl) throw new Error('no page target with webSocketDebuggerUrl');
  const wsUrl = page.webSocketDebuggerUrl;

  const ws = new WebSocket(wsUrl);
  let resolved = false;
  const done = (code, msg) => {
    if (resolved) return;
    resolved = true;
    try { ws.close(); } catch {}
    console.log(`[probe-9231] result=${code} ${msg}`);
    process.exit(code);
  };

  const timer = setTimeout(() => done(1, 'HARD-TIMEOUT'), HARD_TIMEOUT);

  ws.addEventListener('open', () => {
    const id = 1;
    ws.send(JSON.stringify({ id, method: 'Runtime.evaluate', params: { expression: '1+1', returnByValue: true } }));
  });
  ws.addEventListener('message', (ev) => {
    let m;
    try { m = JSON.parse(ev.data.toString()); } catch { return; }
    if (m.id === 1) {
      clearTimeout(timer);
      const ok = m.result && m.result.result && m.result.result.value === 2;
      done(ok ? 0 : 2, ok ? 'CDP-eval 1+1==2 OK' : 'CDP-eval unexpected: ' + JSON.stringify(m.result).slice(0,80));
    }
  });
  ws.addEventListener('error', (e) => { clearTimeout(timer); done(3, 'WS-ERROR ' + (e.message || 'unknown')); });
}

const guard = setTimeout(() => { console.log('[probe-9231] result=1 HARD-TIMEOUT-main'); process.exit(1); }, HARD_TIMEOUT + 2000);
main().catch(e => { clearTimeout(guard); console.log('[probe-9231] result=1 ' + e.message); process.exit(1); });

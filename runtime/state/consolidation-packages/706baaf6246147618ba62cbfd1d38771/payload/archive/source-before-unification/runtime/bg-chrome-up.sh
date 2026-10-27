#!/bin/bash
# bg-chrome-up.sh —— 后台专用 Chrome 岗位保活（幂等）
#
# 用途
#   zhensi 各岗位的"后台专用 Chrome"（headless + CDP）一旦不在，对应采集流必然失败
#   （典型：daily-agent-new-merchants-to-wechat → stage=collection →
#    background-profile-state-mismatch / background-profile-process-not-alive）。
#
# 为什么不用官方 background_chrome.mjs start 直接拉起（2026-10-06 实测）
#   1) 官方 `start` 拉起的 Chrome 在 WorkBuddy 沙箱上下文里**活不过命令结束**；
#   2) 更关键：沙箱里 **Chrome 自身的进程沙箱无法初始化**
#        sandbox initialization failed: Operation not permitted
#        → GPU process exit_code=6 → FATAL: GPU process isn't usable. Goodbye.
#      必须加 `--no-sandbox`（项目自己的 com.zhensi.bg-chrome.*.plist 本就带这个 flag）。
#   3) 官方 `stop` / `probe` 依赖 /bin/ps，而 /bin/ps 在沙箱里被拦
#      （PermissionError: Operation not permitted）⇒ 身份校验会误报
#      managed-process-identity-mismatch。故本脚本用 pgrep + lsof 做等价判定。
#
# 契约
#   bash bg-chrome-up.sh [<profile> <port> <url>]   # 默认 taobao-agent-service 9231 open.shop.ele.me
#   bash bg-chrome-up.sh status [<profile> <port>]
#
# 2026-10-08 大同指示：jinsha-business（金鲨 9232）默认**有头模式**拉起（可见窗口，
#   别用完全无声的 headless）；其余岗位维持 headless（采集器硬校验 mode=headless）。
#   环境变量 BG_CHROME_LAUNCH=headless|headful 可临时覆盖任一岗位（测试用）。
#   state.json 的 mode 字段对金鲨仍写 'headless'：金鲨采集器 fast-path 只认
#   mode='headless' 或完整 visible-handoff 交接仪式字段（本脚本无法诚实产出后者），
#   与 2026-10-08 11:17 轮已验证过的生产状态（有头进程+mode=headless）一致，
#   实际形态记录在 launchNote。
#
# 幂等：已在监听且 state.json 已是 headless/<port> 时只报状态，不做任何改动。
# 边界：只清"可证明陈旧"的 Singleton*（目标 pid 已死 且 无进程占用该 profile 且 端口空闲）。

set -u
PROFILE="${1:-taobao-agent-service}"
PORT="${2:-9231}"
URL="${3:-https://open.shop.ele.me/manager/base/home}"
MODE="${4:-}"           # 传 status 则只查
if [ "${1:-}" = "status" ]; then MODE=status; PROFILE="${2:-taobao-agent-service}"; PORT="${3:-9231}"; fi

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
ROOT="$HOME/Library/Application Support/AOS Background Chrome"
PROF_DIR="$ROOT/$PROFILE"
STATE_DIR="$PROF_DIR/.aos-background-chrome"
STATE="$STATE_DIR/state.json"
PY="/Users/ddt/work/projects/ai_agent/.venvs/harmonyos3-phone-control/bin/python"
LOG="/tmp/bg-chrome-${PROFILE}.log"

listening() { lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; }
prof_pids()  { pgrep -f "user-data-dir=.*/$PROFILE( |\$)" 2>/dev/null || true; }
state_mode() { [ -f "$STATE" ] && /usr/bin/python3 -c "import json;print(json.load(open('$STATE')).get('mode',''))" 2>/dev/null || echo ""; }
state_port() { [ -f "$STATE" ] && /usr/bin/python3 -c "import json;print(json.load(open('$STATE')).get('port') or '')" 2>/dev/null || echo ""; }
state_pid()  { [ -f "$STATE" ] && /usr/bin/python3 -c "import json;print(json.load(open('$STATE')).get('pid') or '')" 2>/dev/null || echo ""; }

if [ "$MODE" = "status" ]; then
  echo "[bg-chrome] profile=$PROFILE port=$PORT"
  echo "  listening = $(listening && echo yes || echo no)"
  echo "  pids      = $(prof_pids | tr '\n' ' ')"
  echo "  state     = mode=$(state_mode) port=$(state_port) pid=$(state_pid)"
  exit 0
fi

if ! listening; then
  echo "[bg-chrome] $PORT 未监听 → 准备拉起"
else
  echo "[bg-chrome] $PORT 已在监听"
fi

# 陈旧 Singleton 清理（仅当可证明陈旧）
OLD_PID="$(state_pid)"
if [ -L "$PROF_DIR/SingletonLock" ] && ! listening && [ -z "$(prof_pids)" ]; then
  echo "[bg-chrome] 清理陈旧 Singleton*（无进程占用且端口空闲）"
  rm -f "$PROF_DIR/SingletonLock" "$PROF_DIR/SingletonSocket" "$PROF_DIR/SingletonCookie"
fi

if ! listening; then
  [ -x "$CHROME" ] || { echo "[bg-chrome] ✗ 未找到 Chrome：$CHROME"; exit 1; }
  env -u PYTHONPATH "$PY" - "$PROFILE" "$PORT" "$URL" "$LOG" <<'PY'
import os,sys
profile,port,url,log=sys.argv[1],sys.argv[2],sys.argv[3],sys.argv[4]
CHROME='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
P=os.path.expanduser('~/Library/Application Support/AOS Background Chrome')+'/'+profile
headful = (os.environ.get('BG_CHROME_LAUNCH') == 'headful'
           or (os.environ.get('BG_CHROME_LAUNCH') != 'headless' and profile == 'jinsha-business'))
# 2026-10-16 大同指示：taobao-brand(9230) 无条件强制无头（回归设计态；其余岗位本就 headless，
# jinsha 仍默认有头）。原因：之前登录临时 headful（兼带 BG_CHROME_FORCE_HEADFUL=1）未切回，
# 导致进程形态与 state.json(mode=headless) 登记不一致、且有头窗口遮挡/占用资源。
# 故此处无条件覆盖，任何环境变量都不允许把 9230 拉成有头；登录场景改由大同手动打开 Chrome
# 完成，不再经本脚本临时有头。
if profile == 'taobao-brand':
    headful = False
args=[CHROME,f'--user-data-dir={P}','--no-sandbox','--no-first-run','--no-default-browser-check',
      '--remote-debugging-address=127.0.0.1',f'--remote-debugging-port={port}']
if headful:
    args += ['--window-size=1280,760', url]   # 2026-10-10：去掉 --window-position=2000,200（窄屏如1312宽会把窗口推到屏外 ⇒ macOS occlusion ⇒ 视口 0×0 ⇒ 元素「outside of viewport」点不到，9232 上 3 条流同日挂）；1280 宽让金鲨表格少横向溢出；不指定位置让 macOS 放到可见区
else:
    args += ['--headless=new','--disable-gpu',url]
if os.fork()==0:
    os.setsid()
    if os.fork()==0:
        os.environ.pop('PYTHONPATH',None)
        fd=os.open(log,os.O_WRONLY|os.O_CREAT|os.O_APPEND)
        os.dup2(fd,1); os.dup2(fd,2)
        os.execv(CHROME,args)
        os._exit(1)
    os._exit(0)
os._exit(0)
PY
  echo "[bg-chrome] 已分离启动，等待 CDP ..."
  for i in $(seq 1 12); do sleep 1; listening && break; done
fi

if ! listening; then
  echo "[bg-chrome] ✗ 启动失败（$PORT 仍无监听）。Chrome stderr 尾部："
  tail -12 "$LOG" 2>/dev/null
  exit 1
fi

# 校正 state.json（采集器硬要求 profile/mode=headless/port/pid 且 pid 存活）
PID="$(lsof -tnP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | head -1)"
env -u PYTHONPATH "$PY" - "$PROFILE" "$PORT" "$PID" "$URL" <<'PY'
import json,os,sys,datetime
profile,port,pid,url=sys.argv[1],int(sys.argv[2]),int(sys.argv[3]),sys.argv[4]
P=os.path.expanduser('~/Library/Application Support/AOS Background Chrome')+'/'+profile
d=os.path.join(P,'.aos-background-chrome');os.makedirs(d,mode=0o700,exist_ok=True)
cur={}
sp=os.path.join(d,'state.json')
if os.path.exists(sp):
    try:cur=json.load(open(sp))
    except Exception:cur={}
if cur.get('mode')=='headless' and cur.get('port')==port and cur.get('pid')==pid:
    print('[bg-chrome] state.json 已正确，无需改写');sys.exit(0)
cur.update(schemaVersion=1,profile=profile,profilePath=P,mode='headless',port=port,pid=pid,
           startedAt=datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00','Z'),
           url=url,disableBackgroundMode=False,restoreLastSession=False,
           processStartedAt=cur.get('processStartedAt',''),
           launchNote=('bg-chrome-up.sh (headful-visible, 2026-10-08 大同指示)' if profile=='jinsha-business'
                       else 'bg-chrome-up.sh (headless + --no-sandbox)'))
tmp=sp+'.tmp';open(tmp,'w').write(json.dumps(cur,ensure_ascii=False,indent=2));os.chmod(tmp,0o600);os.replace(tmp,sp)
print('[bg-chrome] state.json 已校正: mode=headless port=%d pid=%d'%(port,pid))
PY

echo "[bg-chrome] ✅ $PORT 就绪 pid=$PID"
curl -s --noproxy '*' -m 8 "http://127.0.0.1:$PORT/json/list" 2>/dev/null | /usr/bin/python3 -c "
import json,sys
try: d=json.load(sys.stdin)
except Exception: print('  (CDP 无响应)'); raise SystemExit
for t in d:
    if t.get('type')=='page': print('  页面:', (t.get('title') or '')[:40], '|', (t.get('url') or '')[:100])
" 2>/dev/null

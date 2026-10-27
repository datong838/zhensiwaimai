#!/bin/zsh
# ============================================================================
# 9230 淘宝闪购品牌商系统 · 可见登录窗一键脚本（大同双击运行即可）
#
# 为什么需要它：
#   runtime/bg-chrome-up.sh 第 85-91 行对 taobao-brand 硬编码强制无头（2026-10-16 决策），
#   所以 auth_keepalive.mjs --open-login 对 9230 只能拉无头 ⇒ 屏幕上永远看不到登录页。
#   eleme 系令牌有固定 TTL，掉了只能人工扫码/账密重登（内存 #63）。
#   本脚本在「大同自己的终端会话」里启动 Chrome ⇒ 不受 WorkBuddy 沙箱 GUI 权限限制。
#
# 它会做（全自动，登录这一步只需你扫码/输账密）：
#   1) 停掉 9230 无头实例（释放 profile 锁）
#   2) 打开可见 Chrome 登录页
#   3) 每 3 秒轮询，检测到登录成功
#   4) 自动关闭可见窗 → 起回无头实例（采集器要求 mode=headless）
#   5) 自检并打印最终结论
#
# 用法：Finder 里双击本文件；或终端 `zsh runtime/brand-login-visible.command`
# ============================================================================
set -u
PORT=9230
ROLE=taobao-brand
REPO="/Users/ddt/work/projects/ai_agent/zhensi_waimai_back"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PROFILE_DIR="$HOME/Library/Application Support/AOS Background Chrome/taobao-brand"
LOGIN_URL='https://melody.shop.ele.me/app/chain/95708808/dashboard#app.chainshop.dashboard'
TARGET_URL='https://melody.shop.ele.me/app/chain/95708808/stats__center#app.chainshop.stats.center'
PY=/Users/ddt/.workbuddy/binaries/python/envs/default/bin/python
WAIT_MAX=900   # 最长等待登录 15 分钟

say() { print -r -- "[brand-login] $*"; }
port_busy() { [[ -n "$(lsof -ti :$PORT 2>/dev/null)" ]] }
stop_port() {  # 尽力停掉占用端口的进程
  local pids
  pids=($(lsof -ti :$PORT 2>/dev/null))
  (( ${#pids} == 0 )) && return 0
  say "   占用进程：${pids[*]}，发送 TERM"
  kill ${pids[*]} 2>/dev/null
  local i
  for i in {1..15}; do port_busy || break; sleep 1; done
  if port_busy; then
    pids=($(lsof -ti :$PORT 2>/dev/null))
    say "   仍在运行，强制 KILL：${pids[*]}"
    kill -9 ${pids[*]} 2>/dev/null
    sleep 2
  fi
  port_busy && return 1 || return 0
}

say "① 停止 9230 现有实例（释放 profile 锁）"
if port_busy; then
  stop_port || { say "✗ 端口 $PORT 仍被占用，请手动处理后重试"; read -k 1 "?按任意键关闭…"; exit 1; }
else
  say "   端口本就空闲"
fi
say "   ✓ 端口已释放"

say "② 打开可见登录窗（melody.shop.ele.me）"
[ -x "$CHROME" ] || { say "✗ 未找到 Chrome：$CHROME"; read -k 1 "?按任意键关闭…"; exit 1; }
[ -d "$PROFILE_DIR" ] || { say "✗ 未找到 profile：$PROFILE_DIR"; read -k 1 "?按任意键关闭…"; exit 1; }
"$CHROME" --user-data-dir="$PROFILE_DIR" --no-sandbox --no-first-run --no-default-browser-check \
          --remote-debugging-address=127.0.0.1 --remote-debugging-port=$PORT \
          --window-size=1280,860 "$LOGIN_URL" >/tmp/brand-login-visible.log 2>&1 &

say ""
say "=========================================================="
say "  请在弹出的 Chrome 窗口里完成登录（扫码 或 账密）"
say "  登录成功后本脚本自动收尾，无需你操作"
say "  最长等待 15 分钟"
say "=========================================================="
say ""

page_url() {
  curl -s --noproxy '*' --max-time 4 "http://127.0.0.1:$PORT/json/list" 2>/dev/null | "$PY" -c "
import sys, json
try:
    d = json.load(sys.stdin)
except Exception:
    print('NO-CDP'); raise SystemExit
for p in d:
    if p.get('type') == 'page':
        print(p.get('url', ''))
        raise SystemExit
print('NO-PAGE')
" 2>/dev/null
}

ok=0
for i in $(seq 1 $((WAIT_MAX / 3))); do
  sleep 3
  U="$(page_url)"
  if [[ "$U" == *"melody.shop.ele.me"* && "$U" != *"/login"* ]]; then ok=1; break; fi
  (( i % 20 == 0 )) && say "…仍在等待登录（已 $((i * 3)) 秒）当前页：${U:-无}"
done

if (( ok == 0 )); then
  say "✗ 15 分钟内未检测到登录成功。可见窗保留未关闭，请继续登录；"
  say "  登录完成后手动运行：bash $REPO/runtime/bg-chrome-up.sh $ROLE $PORT '$TARGET_URL'"
  read -k 1 "?按任意键关闭…"; exit 3
fi

say "③ 检测到登录成功，关闭可见窗并切回无头"
stop_port || say "   ⚠️ 端口未完全释放，继续尝试"
sleep 2
if ! port_busy; then
  rm -f "$PROFILE_DIR/SingletonLock" "$PROFILE_DIR/SingletonSocket" "$PROFILE_DIR/SingletonCookie" 2>/dev/null
fi

say "④ 拉起无头实例"
cd "$REPO" && env -u PYTHONPATH bash runtime/bg-chrome-up.sh "$ROLE" "$PORT" "$TARGET_URL" 2>&1 | tail -6

say "⑤ 自检"
sleep 4
FINAL="$(page_url)"
say "   当前页面：${FINAL:-无}"
if [[ "$FINAL" == *"/login"* || "$FINAL" == "NO-CDP" || "$FINAL" == "NO-PAGE" || -z "$FINAL" ]]; then
  say "✗ 切回无头后仍异常，请把本窗口输出发给大同排查"
  read -k 1 "?按任意键关闭…"; exit 4
fi
say "✅ 完成：9230 已恢复登录态且运行在无头模式（mode=headless）"
say "   下次 auth_keepalive 探活应返回退出码 0"
read -k 1 "?按任意键关闭…"
exit 0

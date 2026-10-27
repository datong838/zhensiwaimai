#!/usr/bin/env bash
# 幂等启动 localhost 中继（给 launchd daemon 提供绕开 macOS「本地网络」TCC 的入口）。
#
# 背景：launchd 拉起的 daemon 连 LAN 主机被 TCC 拦（Errno 65），只能走
# 127.0.0.1:8732；中继必须跑在**有 Local Network 授权的 GUI 会话**里，
# 由它完成到 Windows 网关的最后一跳。
#
# 用法（在有 GUI 权限的上下文里跑，例如 WorkBuddy / Terminal.app）：
#     bash relay-up.sh          # 已在监听则不动，否则分离式拉起
#     bash relay-up.sh status   # 只看状态
#
# 注意：launchctl bootstrap 在 WorkBuddy 沙箱上下文会报 EIO(5)，故本脚本
# 用「新会话双重 fork + exec」把中继彻底脱离调用方进程组，实现跨命令/跨会话存活。
set -uo pipefail
cd "$(dirname "$0")"

PY_BIN="/Users/ddt/work/projects/ai_agent/.venvs/harmonyos3-phone-control/bin/python3"
PORT="${RELAY_LISTEN_PORT:-8732}"
# ★2026-10-10 网关地址配置化：候选从 gateway.json 读（改 IP 只动那一个文件）；
# env RELAY_TARGET_HOSTS 仍可覆盖；配置不可用回退内置默认。
CFG_DEFAULT="192.168.110.184,192.168.0.3,192.168.0.2,192.168.0.5,172.16.8.157"
TARGETS="${RELAY_TARGET_HOSTS:-$("$PY_BIN" -c "import json;print(','.join(json.load(open('gateway.json'))['candidates']))" 2>/dev/null || echo "$CFG_DEFAULT")}"

listening() { lsof -tnP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; }

if [ "${1:-}" = "status" ]; then
  if listening; then echo "[relay-up] 已在监听 127.0.0.1:$PORT (pid=$(lsof -tnP -iTCP:$PORT -sTCP:LISTEN | head -1))";
  else echo "[relay-up] 未监听 127.0.0.1:$PORT"; fi
  exit 0
fi

if listening; then
  echo "[relay-up] 已在监听 127.0.0.1:${PORT}，跳过"
  exit 0
fi

"$PY_BIN" - <<PY
import os
PY_BIN = "$PY_BIN"
HOME = os.getcwd()
if os.fork() == 0:
    os.setsid()
    if os.fork() == 0:
        os.chdir(HOME)
        os.environ.update(RELAY_LISTEN_HOST="127.0.0.1", RELAY_LISTEN_PORT="$PORT",
                          RELAY_TARGET_HOSTS="$TARGETS",
                          RELAY_TARGET_PORT="$("$PY_BIN" -c "import json;print(json.load(open('gateway.json'))['port'])" 2>/dev/null || echo 8731)")
        fd = os.open("relay.out.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND); os.dup2(fd, 1)
        fd = os.open("relay.err.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND); os.dup2(fd, 2)
        os.execv(PY_BIN, [PY_BIN, "localhost_relay.py"])
        os._exit(1)
    os._exit(0)
os._exit(0)
PY
sleep 2
if listening; then
  echo "[relay-up] 已启动 127.0.0.1:$PORT -> candidates=$TARGETS"
  curl -s --noproxy '*' -m 8 "http://127.0.0.1:$PORT/health" | head -c 200; echo
else
  echo "[relay-up] 启动失败，见 relay.err.log"; tail -5 relay.err.log; exit 1
fi

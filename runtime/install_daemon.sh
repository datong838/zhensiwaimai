#!/bin/sh
# 生成并加载 launchd 常驻守护（P3-1B 会话常驻看护）。
#
# 设计要点（与「独立 / 可重命名」目标一致）：
# - 本脚本不写死任何项目目录名；__PYTHON__ / __RUNTIME__ 按当前绝对路径注入模板。
# - 重命名项目目录后，重跑 `bash runtime/install_daemon.sh` 即用新路径重新生成 plist，无需手工改。
# - 不依赖 codex 或任何特定 agent 运行时；node 经 PATH 解析（见模板 EnvironmentVariables.PATH）。
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUNTIME_DIR="$SCRIPT_DIR"
TEMPLATE="$RUNTIME_DIR/com.zhensi.waimai.careloop.template.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.zhensi.waimai.careloop.plist"
# 优先使用共享 venv（向上两级到 ai_agent 工作区），保证 run_all 自身生成台账
# （openpyxl）与各 skill 脚本用同一解释器，避免 PATH 上 python3 缺 openpyxl
# 导致台账降级为 csv。找不到 venv 时回退到 PATH python3。
AI_AGENT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
VENV_PYTHON="$AI_AGENT_DIR/.venvs/harmonyos3-phone-control/bin/python"
if [ -x "$VENV_PYTHON" ]; then
  PYTHON_BIN="$VENV_PYTHON"
else
  PYTHON_BIN="$(command -v python3)"
fi

# node 解析。**必须与 manifest 保持一致**：manifest 的 interpreter_env_overrides 把
# node 映射到 ZENSI_NODE，即本脚本注入的 ZENSI_NODE 优先级高于 manifest 的
# interpreters.node；若这里取 PATH 上另一个 node（如 WorkBuddy 托管版），就会把 node
# 类技能（其 node_modules 软链与该绝对路径同源）推到错位解释器上。故顺序为：
# manifest 绝对路径 → PATH → 常见安装位置（后两者均为机器级路径，不写死项目目录）。
NODE_BIN=""
MANIFEST="$RUNTIME_DIR/skills_manifest.json"
if [ -f "$MANIFEST" ] && [ -n "$PYTHON_BIN" ]; then
  NODE_BIN="$("$PYTHON_BIN" -c 'import json,sys;v=(json.load(open(sys.argv[1])).get("interpreters") or {}).get("node","");print(v if v.startswith("/") else "")' "$MANIFEST" 2>/dev/null || true)"
fi
if [ -z "$NODE_BIN" ]; then
  NODE_BIN="$(command -v node 2>/dev/null || true)"
fi
if [ -z "$NODE_BIN" ]; then
  for c in /opt/homebrew/bin/node /usr/local/bin/node \
           "$HOME"/.workbuddy/binaries/node/versions/*/bin/node \
           "$HOME"/.nvm/versions/node/*/bin/node; do
    if [ -x "$c" ]; then NODE_BIN="$c"; break; fi
  done
fi
if [ -z "$NODE_BIN" ]; then
  echo "[warn] 未找到 node，daemon 内 node 类 skill 将无法执行（可 brew install node 后重跑本脚本）" >&2
fi

if [ -z "$PYTHON_BIN" ]; then
  echo "[error] 找不到 python3（请在 PATH 中可用）" >&2
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents"
sed -e "s|__PYTHON__|$PYTHON_BIN|g" \
    -e "s|__NODE__|$NODE_BIN|g" \
    -e "s|__RUNTIME__|$RUNTIME_DIR|g" \
    "$TEMPLATE" > "$PLIST_DST"

# ---- 加载：任何一步失败都必须显式报错，禁止静默（"打印成功实则没跑"比报错危险得多）----
LABEL="com.zhensi.waimai.careloop"
DOMAIN="gui/$(id -u)"
HEARTBEAT="$RUNTIME_DIR/state/daemon.json"

# 卸载旧实例（若存在）。bootout 后需短暂停顿避开 launchd 状态竞态。
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
sleep 2

# 必须在 bootstrap **之前** enable：label 一旦进入 launchd 的 disabled 数据库，
# bootstrap 会直接报 "Input/output error (5)"，且任何重试都无法自愈。
# （2026-09-30 实测：正是 disabled 标记导致 Terminal 里也连续 3 次 EIO 失败。）
launchctl enable "$DOMAIN/$LABEL" 2>/dev/null || true

# bootout 与 bootstrap 之间存在 launchd 状态竞态，重试 3 次再判定失败
BOOTED=0
attempt=1
while [ "$attempt" -le 3 ]; do
  if launchctl bootstrap "$DOMAIN" "$PLIST_DST"; then
    BOOTED=1
    break
  fi
  attempt=$((attempt + 1))
  sleep 3
done

if [ "$BOOTED" -ne 1 ]; then
  echo "[error] launchctl bootstrap 连续 3 次失败：服务未注册到 $DOMAIN" >&2
  echo "        常见原因：本脚本必须在「你自己的 Terminal.app」里运行" >&2
  echo "        （ssh / 远程 shell / 其他应用内嵌 shell 会被 launchd 拒绝，报 Input/output error）" >&2
  exit 1
fi

# bootout 后服务可能残留 disabled 状态，显式 enable 再 kickstart 确保立即起一轮
launchctl enable "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl kickstart -k "$DOMAIN/$LABEL" 2>/dev/null || true

# ---- 验收：等心跳落地（最多 25s），没跑起来就报错退出 ----
BEFORE="$( [ -f "$HEARTBEAT" ] && stat -f "%m" "$HEARTBEAT" || echo 0 )"
STARTED=0
i=0
while [ "$i" -lt 25 ]; do
  sleep 1
  i=$((i + 1))
  if [ -f "$HEARTBEAT" ] && [ "$(stat -f "%m" "$HEARTBEAT")" != "$BEFORE" ]; then
    STARTED=1
    break
  fi
done

if [ "$STARTED" -ne 1 ]; then
  echo "[error] daemon 未产生心跳（可能未真正启动）" >&2
  echo "        排查：$RUNTIME_DIR/state/daemon.err.log 与 daemon.out.log 尾部" >&2
  exit 1
fi

echo "careloop daemon 已安装并启动 -> $PLIST_DST"
echo "  runtime = $RUNTIME_DIR"
echo "  python  = $PYTHON_BIN"
echo "  node    = ${NODE_BIN:-（未找到，node 类 skill 不可用）}"
echo "  heartbeat:"
sed 's/^/    /' "$HEARTBEAT"

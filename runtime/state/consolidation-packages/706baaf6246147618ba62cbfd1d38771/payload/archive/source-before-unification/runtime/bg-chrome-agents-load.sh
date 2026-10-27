#!/bin/bash
# bg-chrome-agents-load.sh —— 四岗位后台 Chrome LaunchAgent 的加载/刷新（幂等）。
#
# 为什么需要人工跑一次
#   `launchctl bootstrap` 在 WorkBuddy 沙箱/受限上下文里报 `Bootstrap failed: 5: Input/output error`
#   （EIO(5) 铁律）⇒ 无法脚本化自动 bootstrap。**重启后由 launchd 在登录时自动加载
#   ~/Library/LaunchAgents/*.plist**，无需本条命令；本条只用于「不重启、立即生效」。
#
# 用法（在大同自己的 Terminal 里跑）：
#   bash /Users/ddt/work/projects/ai_agent/zhensi_waimai_back/runtime/bg-chrome-agents-load.sh
#
# 行为：对四岗位 label 先 bootout（清旧实例）再 bootstrap；随后 print 校验 state。
#   plist 由 bg-chrome-up.sh 驱动（幂等 + --headless + 写 state.json），RunAtLoad + StartInterval=300。
set -u
U=$(id -u); DOM="gui/$U"
LA="$HOME/Library/LaunchAgents"
LABELS=(taobao-brand taobao-agent-service jinsha-business meituan-merchant)

for L in "${LABELS[@]}"; do
  P="$LA/com.zhensi.bg-chrome.$L.plist"
  if [ ! -f "$P" ]; then echo "[$L] 缺失 plist: $P"; continue; fi
  launchctl bootout "$DOM/com.zhensi.bg-chrome.$L" >/dev/null 2>&1 && echo "[$L] bootout 旧实例完成"
  if launchctl bootstrap "$DOM" "$P" >/dev/null 2>&1; then
    echo "[$L] bootstrap OK"
  else
    echo "[$L] ✗ bootstrap 失败 rc=$? （请确认在 GUI Terminal 且已登录）"
  fi
done

echo "--- 校验（launchctl print）---"
for L in "${LABELS[@]}"; do
  printf '%-24s ' "$L"
  launchctl print "$DOM/com.zhensi.bg-chrome.$L" 2>&1 | grep -m1 -E "state = |Could not find" || echo "(无输出)"
done

echo "--- 岗位 CDP 复核（等 3s 让 RunAtLoad 幂等空转）---"
sleep 3
for pair in "taobao-brand 9230" "taobao-agent-service 9231" "jinsha-business 9232" "meituan-merchant 9233"; do
  set -- $pair
  code=$(curl -s --noproxy '*' -m 4 -o /dev/null -w '%{http_code}' "http://127.0.0.1:$2/json/version")
  echo "  $1 :$2 CDP=$code"
done

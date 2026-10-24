#!/bin/bash
# open-daily-chrome.sh —— 稳妥打开「日常 Chrome」（默认 profile）
#
# 背景（2026-10-18 大同问诊）：本机 4 个生产 Chrome 实例（9230-9233）共用同一个
# Chrome bundle。当日常 Chrome 未运行时，点 Dock 的「打开」事件可能被路由给某个
# 生产实例（其中 3 个无头，永远不出窗口）→ 表现为「点了没反应」。
#
# 本脚本三步走：
#   1) 已有日常实例（~/Library/Application Support/Google/Chrome 活着）→ 直接激活
#   2) 无日常实例 → 以默认 profile 启动一个（--new-window 保证出窗口）
#   3) 启动后自动跑一次 ASN 守卫（chrome_asn_guard.sh），有幽灵前台就报出来
#
# 判据：日常 Chrome 的特征 = 命令行里不带 --user-data-dir 指向
#       "AOS Background Chrome" 目录（生产实例都带）。
set -u
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
GUARD="/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/runtime/chrome_asn_guard.sh"

# 1) 找日常实例（不带 AOS 后台 profile 参数的 Chrome 主进程）
DAILY_PID=""
for p in $(pgrep -f "Google Chrome" 2>/dev/null); do
  ARGS=$(ps -p "$p" -o command= 2>/dev/null) || continue
  [ -z "$ARGS" ] && continue
  case "$ARGS" in
    *"AOS Background Chrome"*) continue ;;   # 生产实例，跳过
    *"--user-data-dir="*)        continue ;; # 其他自定义 profile，跳过
    *"/Google Chrome"*)          DAILY_PID="$p"; break ;; # 主二进制且无自定义 profile
  esac
done

if [ -n "$DAILY_PID" ]; then
  echo "[daily-chrome] 日常实例已在运行 pid=$DAILY_PID → 仅激活"
  open -a "Google Chrome"
else
  echo "[daily-chrome] 日常实例不在 → 启动默认 profile"
  "$CHROME" --new-window >/dev/null 2>&1 &
  disown
  sleep 4
fi

# 3) 顺手体检：有没有幽灵前台
if [ -x "$GUARD" ]; then
  echo "[daily-chrome] 附带 ASN 体检："
  bash "$GUARD" || true
fi

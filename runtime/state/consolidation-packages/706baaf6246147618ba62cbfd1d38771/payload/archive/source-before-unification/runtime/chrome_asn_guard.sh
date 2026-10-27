#!/bin/bash
# chrome_asn_guard.sh —— 多实例 Chrome「幽灵前台」守卫（监理只读巡检，默认不动手）
#
# 背景（2026-10-18 大同问诊）：4 个生产 Chrome（9230/9231/9232/9233）与日常 Chrome
# 共用同一个 /Applications/Google Chrome.app bundle。headless 实例有时会被 macOS
# LaunchServices 错误注册成 Foreground（"幽灵前台"），抢走点 Dock 图标的「打开」事件，
# 表现为「点开 Chrome 没反应」。当天 9231(pid 1036)/9233(pid 1053) 两次复发，均为
# TERM 旧进程 + launchctl kickstart 重拉后恢复 BackgroundOnly。
#
# 用途
#   巡检 4 个实例的 LaunchServices 注册类型（lsappinfo ASN type 字段）：
#     - 合法有头（金鲨 9232）→ 允许 Foreground
#     - 其余 headless 岗位   → 必须 BackgroundOnly，出现 Foreground 即报警
#
# 契约
#   bash chrome_asn_guard.sh            # 只读巡检，异常时 exit 1 并打印修复指令
#   bash chrome_asn_guard.sh --fix      # 修复模式：TERM 幽灵 pid + kickstart 对应 launchd 服务重拉
#                                       # （登录态在 profile 目录，重启实例不丢）
#
# 判据（2026-10-18 实战沉淀）
#   lsappinfo info -all 输出中每个 Chrome 主进程 ASN 的 type=
#   BackgroundOnly=正常无头 / Foreground=幽灵前台（无窗口但抢 Dock/⌘Tab 激活）。
#   注意 lsappinfo 输出按 ASN 分段，需先切出 pid= 行再回溯最近一条 type= 行。
set -u

# 岗位表：launchd-label|端口|是否允许前台
UNITS=(
  "com.zhensi.bg-chrome.taobao-brand|9230|no"
  "com.zhensi.bg-chrome.taobao-agent-service|9231|no"
  "com.zhensi.bg-chrome.jinsha-business|9232|yes"
  "com.zhensi.bg-chrome.meituan-merchant|9233|no"
)

FIX="${1:-}"

echo "[asn-guard] $(date '+%F %T') 巡检 Chrome ASN 注册类型"
BAD=0
for unit in "${UNITS[@]}"; do
  IFS='|' read -r LABEL PORT ALLOW_FG <<< "$unit"
  PID="$(lsof -tnP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | head -1)"
  if [ -z "$PID" ]; then
    echo "  [$PORT] $LABEL : 端口无监听（实例不在）→ 跳过 ASN 检查"
    continue
  fi
  # lsappinfo 按 ASN 分段输出；取含该 pid 的段内 type 字段
  SEG=$(lsappinfo info -all 2>/dev/null | awk -v pid="$PID" '
    /^"/ {asn=$0; seg=""}
    {seg=seg"\n"$0}
    /pid = '"$PID"' \[|pid='"$PID"' \[/ {found=1}
    END{if(found) print seg}' )
  # 兜底：直接单点查询
  TYPE="$(lsappinfo info "$PID" 2>/dev/null | sed -n 's/.*type="\([A-Za-z]*\)".*/\1/p' | head -1)"
  [ -z "$TYPE" ] && TYPE="(未知/未注册)"
  if [ "$TYPE" = "Foreground" ] && [ "$ALLOW_FG" != "yes" ]; then
    BAD=$((BAD+1))
    echo "  [$PORT] $LABEL pid=$PID type=$TYPE ← 幽灵前台！"
    if [ "$FIX" = "--fix" ]; then
      echo "    → 修复：TERM $PID + kickstart $LABEL"
      kill -TERM "$PID" 2>/dev/null
      sleep 3
      launchctl kickstart -k "gui/$(id -u)/$LABEL" 2>/dev/null || launchctl kickstart "gui/$(id -u)/$LABEL" 2>/dev/null
      sleep 5
      NEW_PID="$(lsof -tnP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | head -1)"
      NEW_TYPE="$(lsappinfo info "$NEW_PID" 2>/dev/null | sed -n 's/.*type="\([A-Za-z]*\)".*/\1/p' | head -1)"
      echo "    → 重拉后 pid=$NEW_PID type=$NEW_TYPE"
    else
      echo "    → 修复指令：kill -TERM $PID && launchctl kickstart -k gui/$(id -u)/$LABEL"
    fi
  else
    echo "  [$PORT] $LABEL pid=$PID type=$TYPE ✓"
  fi
done

if [ "$BAD" -gt 0 ]; then
  echo "[asn-guard] 发现 $BAD 个幽灵前台（$([ "$FIX" = "--fix" ] && echo 已修复 || echo 未修复)）"
  exit 1
fi
echo "[asn-guard] 全部正常：headless 均为 BackgroundOnly，金鲨 9232 为唯一合法前台"

#!/usr/bin/env bash
# 一键基线体检：daemon 心跳 + 中继 + 直连 三条线，只读探活、**不发任何消息**。
#
# 用法：
#   bash baseline-check.sh              # 打印到屏幕
#   bash baseline-check.sh | tee baseline/latest.txt
#
# 说明：本脚本与「每小时看护自动化」用的是同一组命令，故它既是体检工具，
#       也是看护判据的可复核版本（见 RESTART-中继与看护恢复手册.md）。
set -uo pipefail
cd "$(dirname "$0")"

PY="/Users/ddt/work/projects/ai_agent/.venvs/harmonyos3-phone-control/bin/python"
DRIVER_DIR="/Users/ddt/work/projects/ai_agent/wechat-windows-driver"
ZBACK="/Users/ddt/work/projects/ai_agent/zhensi_waimai_back"
# ★2026-10-10 候选配置化：从 gateway.json 读（改 IP 只动那一个文件）；读不到回退内置默认
CAND_DEFAULT="192.168.110.184 192.168.0.3 192.168.0.2 192.168.0.5 172.16.8.157"
read -r -a CAND <<< "$("$PY" -c "import json;print(' '.join(json.load(open('$DRIVER_DIR/gateway.json'))['candidates']))" 2>/dev/null || echo "$CAND_DEFAULT")"

printf '════════ zhensi 通道基线体检  %s ════════\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')"

printf '\n【A】daemon 心跳（车间主任）\n'
HB="$ZBACK/runtime/state/daemon.json"
if [ -f "$HB" ]; then
  m=$(stat -f %m "$HB"); now=$(date +%s)
  printf '  心跳 mtime  = %s （距今 %s 分钟）\n' "$(date -r "$m" '+%Y-%m-%d %H:%M:%S')" "$(( (now-m)/60 ))"
else
  printf '  ⚠ %s 不存在\n' "$HB"
fi
printf '  run_all.py  = %s\n' "$(pgrep -f 'run_all.py' | tr '\n' ' ' | sed 's/ $//')"
# ⚠ 注意：`launchctl list | grep careloop` 在此上下文**恒为空**（0 行，不在同一 domain），
#   会被误当成"服务没注册"。权威来源是 launchctl print gui/501/<label>。
LD="$(launchctl print gui/501/com.zhensi.waimai.careloop 2>/dev/null \
      | grep -E 'state = |pid = |last exit code = |runs = ' \
      | sed 's/^[[:space:]]*//' | paste -sd' ' -)"
printf '  launchd     = %s\n' "${LD:-未注册/不可读（launchctl list 在本上下文无意义）}"
printf '  next_cycle  = %s\n' "$(env -u PYTHONPATH "$PY" -c "import json;print(json.load(open('$ZBACK/runtime/state/daemon.json')).get('next_cycle_at','?'))" 2>/dev/null)"

printf '\n【B】中继 127.0.0.1:8732（给 launchd daemon 绕 TCC 用）\n'
bash "$DRIVER_DIR/relay-up.sh" status | sed 's/^/  /'
printf '  /health     = %s\n' "$(curl -s --noproxy '*' -m 8 http://127.0.0.1:8732/health | head -c 220)"
printf '  上游         = %s\n' "$(grep -a 'upstream target' "$DRIVER_DIR/relay.err.log" 2>/dev/null | tail -1)"

printf '\n【C】直连 192.168.0.x:8731（前台/GUI 正解通道）\n'
for ip in "${CAND[@]}"; do
  r=$(curl -s --noproxy '*' -m 5 "http://$ip:8731/health")
  if [ -z "$r" ]; then
    printf '  %-13s = (无响应)\n' "$ip"
  else
    printf '  %-13s = %s\n' "$ip" "$(printf '%s' "$r" | head -c 200)"
  fi
done
printf '  wxsend --status =\n'
env -u PYTHONPATH "$PY" "$DRIVER_DIR/wxsend.py" --status 2>&1 | head -3 | sed 's/^/    /'
printf '  wxsend --sessions（前 5 条）= \n'
env -u PYTHONPATH "$PY" "$DRIVER_DIR/wxsend.py" --sessions 2>&1 | head -5 | sed 's/^/    /'

printf '\n──────────────── 判读 ────────────────\n'
printf '  · A 正常：心跳 < 90 分钟且 run_all.py 进程在\n'
printf '  · B 正常：8732 在监听 且 /health 回 "agent up"\n'
printf '  · C 正常：192.168.0.2 回驱动签名（msg=agent up 且含 uiautomation/worker）\n'
printf '  · 已知非故障：192.168.0.5（无线网卡）从 Mac 侧不可达属常态\n'

#!/bin/bash
# post-reboot-recover.sh —— Mac 重启后的一键恢复 + 自检（须在**大同自己的 GUI Terminal**跑）。
#
# 背景：大部分服务重启后由 launchd 自动恢复（careloop / 四岗位 Chrome plist 都是 RunAtLoad），
#   但有几件事**做不成自启、必须人工/显式**：
#     ① 四岗位 Chrome LaunchAgent 首次加载（launchd bootstrap，沙箱报 EIO(5)）；
#        —— 注：重启后 launchd 会在登录时自动加载 ~/Library/LaunchAgents/*.plist，
#        本脚本的 bootstrap 只作「确保/刷新」保险。
#     ② Windows 微信中继 relay（TCC 拦 launchd，只能 GUI 会话）。
#     ③ 四岗位页面「可见性」自愈（金鲨有头窗口若被遮挡 ⇒ 视口 0×0 ⇒ 元素点不到；
#        daemon 首轮可能先于 supervisor_drive 跑到，故这里先显式治一次，避免首轮空跑失败）。
#
# 用法：
#   bash /Users/ddt/work/projects/ai_agent/zhensi_waimai_back/runtime/post-reboot-recover.sh
set -u
R=/Users/ddt/work/projects/ai_agent
PY="$R/.venvs/harmonyos3-phone-control/bin/python"
NODE=/Users/ddt/.codex-runtimes/codex-primary-runtime/dependencies/node/bin/node

echo "==================== 1/5 四岗位 Chrome LaunchAgent 加载/刷新 ===================="
bash "$R/zhensi_waimai_back/runtime/bg-chrome-agents-load.sh"

echo
echo "==================== 2/5 Windows 微信中继（TCC：必须 GUI 会话） ===================="
# ★2026-10-10 加固（源自当日真实事故）：relay-up.sh 幂等只看「8732 在听」——若中继
#   「在听但上游坏」（网关 IP 漂移 .2/.5→.3 / 候选钉死旧 IP），它会**静默跳过、绝不修**；
#   launchd 版 com.zhensi.windows-relay（KeepAlive）还会用旧候选反复重拉并抢 8732。
#   故这里：(a) 先确保 launchd 版不被加载（launchd 语境被本地网络 TCC 拦，注定到不了 LAN）；
#           (b) 拉起 GUI 版中继并**显式验 /health**，不通则强制重启（带 .3 优先候选）。
RELAY="$R/wechat-windows-driver/relay-up.sh"
# ★2026-10-10 候选配置化：不再显式传 RELAY_TARGET_HOSTS（传了会覆盖配置），
#   relay-up.sh 自己从 gateway.json 读（单一权威，改 IP 只动那一个文件）。
if launchctl print "gui/$(id -u)/com.zhensi.windows-relay" >/dev/null 2>&1; then
  echo "  移除 launchd 版中继（TCC 下不可用，且会抢 8732）"
  launchctl bootout "gui/$(id -u)/com.zhensi.windows-relay" 2>/dev/null || true
  launchctl disable "gui/$(id -u)/com.zhensi.windows-relay" 2>/dev/null || true
fi
if [ -x "$RELAY" ]; then
  bash "$RELAY" 2>&1 | tail -3
  hc="$(curl -s --noproxy '*' -m 6 http://127.0.0.1:8732/health || true)"
  if printf '%s' "$hc" | grep -q '"agent up"'; then
    echo "  ✓ 中继 /health 正常"
  else
    echo "  ✗ 中继 /health 异常（可能『在听但上游坏』）→ 强制重启中继"
    rpid="$(lsof -tnP -iTCP:8732 -sTCP:LISTEN 2>/dev/null | head -1)"
    if [ -n "$rpid" ] && ps -o command= -p "$rpid" 2>/dev/null | grep -q localhost_relay.py; then
      kill "$rpid" 2>/dev/null; sleep 1; kill -9 "$rpid" 2>/dev/null; sleep 1
    fi
    bash "$RELAY" 2>&1 | tail -3
    hc="$(curl -s --noproxy '*' -m 6 http://127.0.0.1:8732/health || true)"
    if printf '%s' "$hc" | grep -q '"agent up"'; then
      echo "  ✓ 重启后中继正常"
    else
      echo "  ✗ 中继仍不通：先查 Windows 网关主机是否在线 → bash $R/wechat-windows-driver/baseline-check.sh"
    fi
  fi
else
  echo "✗ 未找到 relay-up.sh"
fi

echo
echo "==================== 3/5 四岗位页面活性 + 可见性自愈（只探 + 必要时 bringToFront） ===================="
if [ -x "$NODE" ]; then
  env -u PYTHONPATH -u PYTHONSTARTUP "$NODE" "$R/zhensi_waimai_back/runtime/post_page_probe.mjs" --apply 2>&1 | head -12
  echo "（对卡死页 reload、对失可见流程页 bringToFront；不新开/关 tab、不点击、不发送）"
else
  echo "✗ 未找到 node：$NODE"
fi

echo
echo "==================== 4/5 四岗位登录态自检（只读） ===================="
"$PY" "$R/zhensi_waimai_back/runtime/login_health_check.py" || true
echo "（注意：输出里的『桌面微信未运行』是 2026-09-30 起的历史遗留项，**忽略**；"
echo "  真正要看的是 4 个浏览器项是否 非登录页 / CDP 可达。）"

echo
echo "==================== 5/5 守护进程 careloop ===================="
if launchctl print "gui/$(id -u)/com.zhensi.waimai.careloop" 2>&1 | grep -m1 "state = "; then
  echo "  ✓ careloop 已加载（RunAtLoad 自动）"
else
  echo "  ✗ careloop 未加载 → launchctl bootstrap gui/$(id -u) $HOME/Library/LaunchAgents/com.zhensi.waimai.careloop.plist"
fi

echo
echo "完成。若某岗位 CDP 不可达：bash $R/zhensi_waimai_back/runtime/bg-chrome-up.sh <profile> <port> \"<url>\""

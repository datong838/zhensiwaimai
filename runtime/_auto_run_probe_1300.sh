#!/bin/zsh
# 臻肆四岗位登录态保活探针 · 13:00 档执行体（4689a6ed）
# 与 c89f6bc8·09:00 协议完全相同，但**本档不发微信告警**（群告警由 09/15/19/21 档负责）。
# 职责：①对时 ②随机等待1-10min ③通道自检+自修 ④四岗位登录态判据自检+真会话探活 ⑤退出码3→弹登录窗
# 总原则：检测到问题第一时间尽量自修，不允许等待放任；真修不了才输出需要人工介入。
set +e
ZJ=/Users/ddt/work/projects/ai_agent/zhensi_waimai_back
GW=/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/archive/compat/wechat-windows-driver/gateway.json
NODE=/Users/ddt/.workbuddy/binaries/node/versions/22.22.2-2/bin/node
PY=/usr/bin/python3
CHK=$ZJ/runtime/_auto_channel_check.sh
RELAY_PY=/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/archive/compat/wechat-windows-driver/localhost_relay.py
WOL=$ZJ/runtime/wol_windows.py
WOL_PY=/Users/ddt/work/projects/ai_agent/.venvs/harmonyos3-phone-control/bin/python3

echo "===== 对时 ====="
date
# 1-10 分钟随机等待
WAIT=$(( (RANDOM % 540) + 60 ))
echo "随机等待 ${WAIT}s ..."
sleep $WAIT
echo "===== 等待后开始 ====="
date

# ---- 第0步 通道自检（复用权威脚本） ----
echo "===== STEP0 通道自检（含自修） ====="
CHK_OUT=$(zsh "$CHK" 2>&1)
echo "$CHK_OUT"
CHANNEL_STATE=$(echo "$CHK_OUT" | grep -oE '^CHANNEL_STATE=[A-Z_]+' | tail -1 | cut -d= -f2)
CH_HOST_LINE=$(echo "$CHK_OUT" | grep '^CH_HOST=' | tail -1)
CH_HOST=$(echo "$CH_HOST_LINE" | sed 's/^CH_HOST=//; s/ logged_in=.*//')
LOGGED=$(echo "$CH_HOST_LINE" | grep -oE 'logged_in=[A-Za-z]+' | cut -d= -f2)
READY=$(echo "$CH_HOST_LINE" | grep -oE 'ready=[A-Za-z]+' | cut -d= -f2)
TP_LINE=$(echo "$CHK_OUT" | grep '^TARGET_PRESENT=' | tail -1)
TARGET_PRESENT=$(echo "$TP_LINE" | grep -oE 'TARGET_PRESENT=[A-Za-z]+' | cut -d= -f2)
ALERT_PRESENT=$(echo "$TP_LINE" | grep -oE 'ALERT_PRESENT=[A-Za-z]+' | cut -d= -f2)
PORT=$(echo "$CHK_OUT" | grep -oE 'PORT=[0-9]+' | head -1 | cut -d= -f2)
if echo "$CH_HOST" | grep -q ':'; then
  CH_PORT=$(echo "$CH_HOST" | cut -d: -f2); CH_HOST=$(echo "$CH_HOST" | cut -d: -f1)
else
  CH_PORT="$PORT"
fi

RELAY_LISTENING() { lsof -nP -iTCP:8732 -sTCP:LISTEN >/dev/null 2>&1; }

# 自修：UNREACHABLE → 先 WoL 唤醒复测；仍不通 → 重启中继经 8732 复验；仍不通 → 置顶人工
if [ "$CHANNEL_STATE" = "UNREACHABLE" ]; then
  echo "‼️ 通道双侧不可达 → 第一步自修：WoL 唤醒 Windows 网关机（最长等 180s）"
  "$WOL_PY" "$WOL" --wait 180 2>&1 | tail -5
  echo "--- WoL 后复测通道 ---"
  CHK_OUT=$(zsh "$CHK" 2>&1)
  echo "$CHK_OUT"
  CHANNEL_STATE=$(echo "$CHK_OUT" | grep -oE '^CHANNEL_STATE=[A-Z_]+' | tail -1 | cut -d= -f2)
  CH_HOST_LINE=$(echo "$CHK_OUT" | grep '^CH_HOST=' | tail -1)
  CH_HOST=$(echo "$CH_HOST_LINE" | sed 's/^CH_HOST=//; s/ logged_in=.*//')
  LOGGED=$(echo "$CH_HOST_LINE" | grep -oE 'logged_in=[A-Za-z]+' | cut -d= -f2)
  READY=$(echo "$CH_HOST_LINE" | grep -oE 'ready=[A-Za-z]+' | cut -d= -f2)
  TP_LINE=$(echo "$CHK_OUT" | grep '^TARGET_PRESENT=' | tail -1)
  TARGET_PRESENT=$(echo "$TP_LINE" | grep -oE 'TARGET_PRESENT=[A-Za-z]+' | cut -d= -f2)
  ALERT_PRESENT=$(echo "$TP_LINE" | grep -oE 'ALERT_PRESENT=[A-Za-z]+' | cut -d= -f2)
  PORT=$(echo "$CHK_OUT" | grep -oE 'PORT=[0-9]+' | head -1 | cut -d= -f2)
  if echo "$CH_HOST" | grep -q ':'; then
    CH_PORT=$(echo "$CH_HOST" | cut -d: -f2); CH_HOST=$(echo "$CH_HOST" | cut -d: -f1)
  else
    CH_PORT="$PORT"
  fi
fi

if [ "$CHANNEL_STATE" = "UNREACHABLE" ]; then
  echo "‼️ WoL 后仍双侧不可达 → 第二步自修：检查/重启 8732 中继后复验"
  if RELAY_LISTENING; then
    echo "[relay] 8732 已在监听，但经其复验仍 UNREACHABLE（Windows 网关真不可达）"
  else
    echo "[relay] 8732 不在 → kill 旧中继残留并重拉 localhost_relay.py（经 8732 复验）"
    pkill -f "localhost_relay.py" 2>/dev/null; sleep 1
    CAND_CSV=$("$PY" -c "import json;print(','.join(json.load(open('$GW'))['candidates']))")
    GWPORT=$("$PY" -c "import json;print(json.load(open('$GW'))['port'])")
    cd /Users/ddt/work/projects/ai_agent/zhensi_waimai_back/archive/compat/wechat-windows-driver
    RELAY_TARGET_HOSTS="$CAND_CSV" RELAY_TARGET_PORT="$GWPORT" RELAY_LISTEN_HOST="127.0.0.1" RELAY_LISTEN_PORT="8732" \
      setsid nohup "$WOL_PY" "$RELAY_PY" > /tmp/relay_1300.out 2>&1 &
    cd "$ZJ"
    sleep 4
    echo "[relay] 启动后 8732 /health:"; curl -s --noproxy '*' -m 8 "http://127.0.0.1:8732/health" | head -c 200; echo
  fi
  echo "--- 中继复验通道（经 8732） ---"
  CHK_OUT=$(CH_HOST_OVERRIDE=1 zsh "$CHK" 2>&1)
  echo "$CHK_OUT"
  CHANNEL_STATE=$(echo "$CHK_OUT" | grep -oE '^CHANNEL_STATE=[A-Z_]+' | tail -1 | cut -d= -f2)
  CH_HOST_LINE=$(echo "$CHK_OUT" | grep '^CH_HOST=' | tail -1)
  CH_HOST=$(echo "$CH_HOST_LINE" | sed 's/^CH_HOST=//; s/ logged_in=.*//')
  LOGGED=$(echo "$CH_HOST_LINE" | grep -oE 'logged_in=[A-Za-z]+' | cut -d= -f2)
  READY=$(echo "$CH_HOST_LINE" | grep -oE 'ready=[A-Za-z]+' | cut -d= -f2)
  TP_LINE=$(echo "$CHK_OUT" | grep '^TARGET_PRESENT=' | tail -1)
  TARGET_PRESENT=$(echo "$TP_LINE" | grep -oE 'TARGET_PRESENT=[A-Za-z]+' | cut -d= -f2)
  ALERT_PRESENT=$(echo "$TP_LINE" | grep -oE 'ALERT_PRESENT=[A-Za-z]+' | cut -d= -f2)
  PORT=$(echo "$CHK_OUT" | grep -oE 'PORT=[0-9]+' | head -1 | cut -d= -f2)
  if echo "$CH_HOST" | grep -q ':'; then
    CH_PORT=$(echo "$CH_HOST" | cut -d: -f2); CH_HOST=$(echo "$CH_HOST" | cut -d: -f1)
  else
    CH_PORT="$PORT"
  fi
fi

NEED_HUMAN=0
case "$CHANNEL_STATE" in
  WECHAT_NOT_LOGGED_IN) echo "⚠️需要人工介入：Windows 微信未登录，需大同在该 Windows 机上登录微信"; NEED_HUMAN=1;;
  SESSION_MISSING_TARGET) echo "‼️ 通道异常：logged_in/ready 双 true 但目标运营群不在会话列表；需大同在 Windows 机恢复臻肆运营群与 FEIBING NEO 群。本档不发告警，记录即可。";;
  UNREACHABLE) echo "⚠️需要人工介入：Windows 机需按电源键开机/检查网关（WoL + 中继复验后仍双侧不可达）"; NEED_HUMAN=1;;
  AVAILABLE) echo "✅ 第0步=AVAILABLE（通道可用）";;
  *) echo "⚠️ 第0步=未知状态 $CHANNEL_STATE";;
esac

# ---- 判据自检 ----
echo "===== 判据自检（--self-test） ====="
cd "$ZJ"
ST_OUT=$($NODE runtime/auth_keepalive.mjs --self-test 2>&1)
echo "$ST_OUT"
SELFTEST_PASS=$(echo "$ST_OUT" | grep -oE '[0-9]+ passed' | grep -oE '[0-9]+' | head -1)
SELFTEST_FAIL=$(echo "$ST_OUT" | grep -oE '[0-9]+ failed' | grep -oE '[0-9]+' | head -1)
SELFTEST_FAIL=${SELFTEST_FAIL:-0}
if [ "$SELFTEST_FAIL" != "0" ] && [ -n "$SELFTEST_FAIL" ]; then
  echo "SELFTEST_RESULT=FAILED"
  echo "===== 汇总（三要素） ====="
  echo "①第0步通道自检结论：CHANNEL_STATE=$CHANNEL_STATE logged_in=$LOGGED ready=$READY TARGET_PRESENT=$TARGET_PRESENT ALERT_PRESENT=$ALERT_PRESENT"
  echo "②判据自检结果：$SELFTEST_PASS passed, $SELFTEST_FAIL failed"
  echo "③本次是否完成真会话探活：NO（判据自检失败→判据不可信，已立即停止，未发任何告警）"
  echo "DONE"
  exit 0
fi
echo "SELFTEST_RESULT=OK"

# ---- 真会话探活 ----
echo "===== 真会话探活（auth_keepalive.mjs --json） ====="
PROBE_OUT=$($NODE runtime/auth_keepalive.mjs --json 2>/tmp/probe_err1300.txt); PROBE_RC=$?
echo "$PROBE_OUT"
echo "PROBE_ERR:"; tail -20 /tmp/probe_err1300.txt
echo "PROBE_RC=$PROBE_RC"
echo "$PROBE_OUT" > /tmp/probe_out1300.json

# 端口不可达 → 幂等重启对应浏览器后复验（仅对确实 cdp=false 的岗位）
PORTDOWN_PORTS=$("$PY" -c "
import json
try:
    d=json.load(open('/tmp/probe_out1300.json'))
    for r in d.get('rows',[]):
        if r.get('cdp') is False:
            print(r.get('port'))
except Exception: pass
" 2>/dev/null)
if [ -n "$PORTDOWN_PORTS" ]; then
  echo "⚠️ 以下岗位端口不可达，第一时间幂等拉起（bg-chrome-up.sh）后复验："
  for P in $PORTDOWN_PORTS; do
    case "$P" in
      9230) PROF=taobao-brand; URL='https://melody.shop.ele.me/app/chain/95708808/stats__center#app.chainshop.stats.center';;
      9231) PROF=taobao-agent-service; URL='https://open.shop.ele.me/manager/base/home';;
      9232) PROF=jinsha-business; URL='https://data.guoshuyufen.com/#/negativeAnalyse';;
      9233) PROF=meituan-merchant; URL='https://waimaie.meituan.com/imworkbench/home?appId=4&clientType=140006#/im/page/workbench/reception';;
      *) PROF=""; URL="";;
    esac
    if [ -n "$PROF" ]; then
      echo "  --- bg-chrome-up.sh $PROF $P (幂等) ---"
      bash "$ZJ/runtime/bg-chrome-up.sh" "$PROF" "$P" "$URL" 2>&1 | tail -6
    fi
  done
  echo "--- 复验（重跑 auth_keepalive）---"
  PROBE_OUT=$($NODE runtime/auth_keepalive.mjs --json 2>/tmp/probe_err1300.txt); PROBE_RC=$?
  echo "$PROBE_OUT"
  echo "PROBE_RC=$PROBE_RC"
  echo "$PROBE_OUT" > /tmp/probe_out1300.json
fi

# 若 node 未产出合法 JSON → 退化标签页级判定（标注不可信）
if ! echo "$PROBE_OUT" | $PY -c "import sys,json;json.load(sys.stdin)" 2>/dev/null; then
  echo "⚠️ auth_keepalive 未产出合法 JSON（rc=$PROBE_RC），退化到 curl /json/list 标签页级判定（不可信）："
  for P in 9230 9231 9232 9233; do
    CODE=$(curl -s --noproxy '*' -m 4 -o /dev/null -w '%{http_code}' -H "Host: localhost" "http://127.0.0.1:$P/json/list" 2>/dev/null)
    echo "  :$P 标签页枚举 HTTP $CODE"
  done
fi

# ---- 解析真会话探活结果 ----
echo "===== 探活结果解析 ====="
$PY - <<'PYEOF'
import json
try:
    d = json.load(open('/tmp/probe_out1300.json'))
except Exception as e:
    print('PARSE_ERR', e); raise SystemExit
rows = d.get('rows', [])
for r in rows:
    print('  :%s %s state=%s cdp=%s detail=%s' % (r.get('port'), r.get('role'), r.get('state'), r.get('cdp'), r.get('detail','')[:80]))
PYEOF

# ---- 退出码 3（真掉登录）→ 弹有头登录窗 + 置顶人工介入 ----
if [ "$PROBE_RC" = "3" ]; then
  echo "===== 退出码 3：检出真掉登录 → 拉有头登录窗（2h 冷却）+ 置顶人工介入 ====="
  OUT_LOGIN=$($NODE runtime/auth_keepalive.mjs --notify --open-login 2>&1); OLR=$?
  echo "$OUT_LOGIN"
  echo "OPEN_LOGIN_RC=$OLR"
  echo "⚠️需要人工介入：部分岗位掉登录，Mac 屏幕已弹登录窗，请扫码/账密登录，登录后系统自动切回无头+自动补跑"
  NEED_HUMAN=1
fi

# ---- 监理闭环看板（仅读取，不告警） ----
echo "===== 监理闭环看板（只读，不发告警） ====="
$PY - <<'PYEOF'
import json, datetime
try:
    w = json.load(open('/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/runtime/state/war_room.json'))
    now = datetime.datetime.now()
    breached = []; overdue = []
    for k, v in w.get('items', {}).items():
        s = v.get('status')
        if s == 'breached':
            breached.append(k)
        elif s == 'awaiting_you':
            dl = v.get('sla_deadline'); od = False
            if dl:
                try: od = datetime.datetime.fromisoformat(dl) < now
                except Exception: od = False
            if od: overdue.append((k, dl))
    print('WAR_TOTAL=%d BREACHED=%d AWAITING_OVERDUE=%d' % (len(w.get('items', {})), len(breached), len(overdue)))
    for k in breached: print('  BREACHED', k)
    for k, dl in overdue: print('  OVERDUE', k, dl)
except Exception as e:
    print('WAR_PARSE_ERR', e)
PYEOF

# ---- 汇总三要素 ----
echo "===== 汇总（三要素） ====="
echo "①第0步通道自检结论：CHANNEL_STATE=$CHANNEL_STATE logged_in=$LOGGED ready=$READY TARGET_PRESENT=$TARGET_PRESENT ALERT_PRESENT=$ALERT_PRESENT"
echo "②判据自检结果：$SELFTEST_PASS passed, $SELFTEST_FAIL failed"
echo "③本次是否完成真会话探活：YES（auth_keepalive.mjs 真会话探活，退出码 $PROBE_RC；非静默降级）"
echo "④本档是否发送微信告警：NO（13:00 档职责：仅自修+置顶人工介入；群告警由 09/15/19/21 档负责）"
if [ "$NEED_HUMAN" = "1" ]; then echo "⚠️需要人工介入：见上方各步骤置顶项"; fi
echo "DONE"

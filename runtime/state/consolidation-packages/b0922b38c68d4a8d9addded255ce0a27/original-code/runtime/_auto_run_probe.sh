#!/bin/zsh
# 四岗位登录态保活探针 · 执行体（自动化 c89f6bc8）
# 复用 _auto_channel_check.sh（第0步通道自检，zsh 兼容） + auth_keepalive.mjs（判据自检 + 真会话探活）
# 新增：聚合 LOGOUT/端口不可达/监理超时 → 经 Windows 网关发告警（唯一允许发微信的自动化）
# 严禁：mapfile / 变量名用 MATCH·REPLY·reply·line 等 zsh 保留字；TOKEN 仅运行时读取不外写。
set +e
ZJ=/Users/ddt/work/projects/ai_agent/zhensi_waimai_back
GW=/Users/ddt/work/projects/ai_agent/wechat-windows-driver/gateway.json
TOKFILE=/Users/ddt/work/projects/ai_agent/wechat-windows-driver/接入包/连接信息.txt
NODE=/Users/ddt/.workbuddy/binaries/node/versions/22.22.2-2/bin/node
PY=/usr/bin/python3
CHK=$ZJ/runtime/_auto_channel_check.sh

echo "===== 对时 ====="
date
WAIT=$(( (RANDOM % 421) + 60 ))
echo "随机等待 ${WAIT}s ..."
sleep $WAIT
echo "===== 等待后开始 ====="
date

# ---- 第0步 通道自检（复用权威脚本） ----
echo "===== STEP0 通道自检 ====="
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
  CH_PORT=$(echo "$CH_HOST" | cut -d: -f2)
  CH_HOST=$(echo "$CH_HOST" | cut -d: -f1)
else
  CH_PORT="$PORT"
fi

case "$CHANNEL_STATE" in
  WECHAT_NOT_LOGGED_IN) echo "‼️ 第0步=真故障：Windows 微信未登录（agent 可达但 logged_in/ready 非双 true）。全部发群流将 blocked/windows-wechat-not-ready，需大同在该 Windows 机登录微信。后续闭环告警步骤跳过（发不出去）。";;
  SESSION_MISSING_TARGET) echo "‼️ 第0步=异常：logged_in/ready 双 true 但目标运营群不在会话列表（会话列表缺失臻肆目标群）。需大同在 Windows 机恢复臻肆运营群与 FEIBING NEO 群到会话列表。后续闭环告警步骤跳过。";;
  UNREACHABLE) echo "ℹ️ 第0步=双侧不可达（夜间休眠预期），静默结束微信通道（不告警、不重试）。";;
  AVAILABLE) echo "✅ 第0步=AVAILABLE（通道可用）。";;
  *) echo "⚠️ 第0步=未知状态 $CHANNEL_STATE";;
esac

# ---- 判据自检 ----
echo "===== 判据自检 ====="
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
echo "===== 真会话探活 ====="
PROBE_OUT=$($NODE runtime/auth_keepalive.mjs --json 2>/tmp/probe_err.txt); PROBE_RC=$?
echo "$PROBE_OUT"
echo "PROBE_ERR:"; cat /tmp/probe_err.txt
echo "PROBE_RC=$PROBE_RC"
echo "$PROBE_OUT" > /tmp/probe_out.json
# 若 node 未产出合法 JSON（执行异常）→ 退化标签页级判定，并显著标注不可信
if ! echo "$PROBE_OUT" | $PY -c "import sys,json;json.load(sys.stdin)" 2>/dev/null; then
  echo "⚠️ auth_keepalive 未产出合法 JSON（rc=$PROBE_RC），退化到 curl /json/list 标签页级判定（仅标签页级，未做真会话探活，结论不可信）："
  for P in 9230 9231 9232 9233; do
    CODE=$(curl -s --noproxy '*' -m 4 -o /dev/null -w '%{http_code}' -H "Host: localhost" "http://127.0.0.1:$P/json/list" 2>/dev/null)
    echo "  :$P 标签页枚举 HTTP $CODE"
  done
fi

# ---- TOKEN（仅运行时读取） ----
TOKEN=$(grep -oE 'XFVfZHoKwjHaWsZ7EXt2kNvWLSg4TGSvIpMQnvIkCaY|[A-Za-z0-9]{20,}' "$TOKFILE" | head -1)

# ---- 聚合检测 + 发送告警 ----
echo "===== 聚合与告警发送 ====="
$PY - "$CHANNEL_STATE" "$LOGGED" "$READY" "$TARGET_PRESENT" "$ALERT_PRESENT" "$CH_HOST" "$CH_PORT" "$TOKEN" <<'PYEOF'
import sys, json, subprocess, datetime
ch_state, logged, ready, tp, ap, host, port, token = sys.argv[1:9]
logout = []; portdown = []
try:
    d = json.load(open('/tmp/probe_out.json'))
    for r in d.get('rows', []):
        st = r.get('state'); cdp = r.get('cdp')
        if st == 'out':
            logout.append((r.get('port'), r.get('role'), r.get('detail', '')))
        elif cdp is False:
            portdown.append((r.get('port'), r.get('role'), r.get('detail', '')))
except Exception as e:
    print('PROBE_PARSE_ERR', e)
war = []
try:
    w = json.load(open('/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/runtime/state/war_room.json'))
    now = datetime.datetime.now()
    for k, v in w.get('items', {}).items():
        s = v.get('status')
        if s in ('breached', 'awaiting_you'):
            dl = v.get('sla_deadline'); od = False
            if dl:
                try: od = datetime.datetime.fromisoformat(dl) < now
                except Exception: od = False
            if s == 'breached' or od:
                war.append((k, s, dl, v.get('ask', '')[:240]))
except Exception as e:
    print('WAR_PARSE_ERR', e)
print('LOGOUT_COUNT', len(logout), 'PORTDOWN_COUNT', len(portdown), 'WAR_COUNT', len(war))
for x in logout: print('  LOGOUT', x)
for x in portdown: print('  PORTDOWN', x)
for x in war: print('  WAR', x)

msg = []
if logout:
    msg.append('⚠️ 臻肆岗位登录态异常（真会话探活检出）')
    msg.append('以下岗位掉登录，需大同重登对应工位浏览器：')
    for p, role, det in logout: msg.append('  - :%s %s：%s' % (p, role, det))
    msg.append('')
if portdown:
    msg.append('⚠️ 岗位浏览器端口不可达（可能已挂）')
    for p, role, det in portdown: msg.append('  - :%s %s：%s' % (p, role, det))
    msg.append('建议大同检查/幂等重启对应浏览器（runtime/bg-chrome-up.sh）。')
    msg.append('')
if war:
    msg.append('⚠️ 监理待办超时')
    msg.append('以下事项已超时/待大同拍板，需大同拍板，授权即做：')
    for k, s, dl, ask in war: msg.append('  - %s（%s，%s）：%s' % (k, s, dl, ask))
    msg.append('')
text = '\n'.join(msg)
need = bool(logout or portdown or war)
if need:
    if ch_state == 'AVAILABLE' and ap == 'True':
        who = 'FEIBING NEO AI数字员工'
        payload = json.dumps({"action": "send_message", "params": {"who": who, "text": text}}, ensure_ascii=False)
        try:
            r = subprocess.run(["curl", "-s", "--noproxy", "*", "-m", "15",
                                "-H", "Authorization: Bearer " + token,
                                "-H", "Content-Type: application/json", "-X", "POST",
                                "http://%s:%s/" % (host, port), "-d", payload],
                               capture_output=True, text=True, timeout=20)
            print('ALERT_SEND_RESP', r.stdout[:600])
            print('ALERT_SENT=1')
        except Exception as e:
            print('ALERT_SEND_ERR', e); print('ALERT_SENT=0')
    else:
        print('ALERT_SENT=0 reason=channel_unavailable(ch_state=%s, alert_present=%s)' % (ch_state, ap))
        if ap != 'True':
            print('ALERT_DELIVERY_FAILED=1 (告警出口群 FEIBING NEO AI数字员工 不在会话列表，无法经微信送达；异常已在上方记录，请大同手动处理)')
else:
    print('ALERT_SENT=0 reason=no_issue')
PYEOF

# ---- 汇总三要素 ----
echo "===== 汇总（三要素） ====="
echo "①第0步通道自检结论：CHANNEL_STATE=$CHANNEL_STATE logged_in=$LOGGED ready=$READY TARGET_PRESENT=$TARGET_PRESENT ALERT_PRESENT=$ALERT_PRESENT"
echo "②判据自检结果：$SELFTEST_PASS passed, $SELFTEST_FAIL failed"
echo "③本次是否完成真会话探活：YES（auth_keepalive.mjs 真会话探活，退出码 $PROBE_RC；非静默降级）"
echo "DONE"

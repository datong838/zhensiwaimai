#!/bin/zsh
# 四岗位登录态保活探针（自动化 c89f6bc8 执行体）
set +e
ZJ=/Users/ddt/work/projects/ai_agent/zhensi_waimai_back
GW=/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/archive/compat/wechat-windows-driver/gateway.json
TOKFILE=/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/archive/compat/wechat-windows-driver/接入包/连接信息.txt
NODE=/Users/ddt/.workbuddy/binaries/node/versions/22.22.2-2/bin/node
PY=/usr/bin/python3

echo "===== 对时 ====="
date

# ---- 随机等待 1-15 分钟 ----
WAIT=$(( (RANDOM % 900) + 60 ))
echo "随机等待 ${WAIT}s ..."
sleep $WAIT
echo "===== 等待后开始 ====="
date

# ---- 解析 gateway.json ----
PORT=$($PY -c "import json;print(json.load(open('$GW'))['port'])")
RELAYPORT=$($PY -c "import json;print(json.load(open('$GW')).get('relay_port',8732))")
mapfile -t CAND < <($PY -c "import json;[print(c) for c in json.load(open('$GW'))['candidates']]")
echo "PORT=$PORT RELAYPORT=$RELAYPORT CAND=${CAND[*]}"

# ---- 读取 TOKEN（仅运行时，不外写）----
TOKEN=$(grep -oE 'XFVfZHoKwjHaWsZ7EXt2kNvWLSg4TGSvIpMQnvIkCaY|[A-Za-z0-9]{20,}' "$TOKFILE" | head -1)

CH_STATE="UNREACHABLE"
HEALTH_INFO=""
SESS_INFO=""
TARGET_PRESENT="?"
ALERT_PRESENT="?"

probe_health () {
  local host=$1
  curl -s --noproxy '*' -m 5 "http://${host}:${PORT}/health" 2>/dev/null
}

probe_sessions () {
  local host=$1
  curl -s --noproxy '*' -m 8 -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" \
    -X POST "http://${host}:${PORT}/" -d '{"action":"list_sessions"}' 2>/dev/null
}

# 先试直连候选
for c in "${CAND[@]}"; do
  H=$(probe_health "$c")
  if echo "$H" | grep -q 'agent up'; then
    CH_HOST="$c"
    HEALTH_INFO="$H"
    S=$(probe_sessions "$c")
    SESS_INFO="$S"
    break
  fi
done

# 直连全不可达 → 试中继
if [ -z "$CH_HOST" ]; then
  H=$(probe_health "127.0.0.1")
  if echo "$H" | grep -q 'agent up'; then
    CH_HOST="127.0.0.1"
    HEALTH_INFO="$H"
    S=$(probe_sessions "127.0.0.1")
    SESS_INFO="$S"
  fi
fi

if [ -z "$CH_HOST" ]; then
  CH_STATE="UNREACHABLE"
  echo "CHANNEL_STATE=UNREACHABLE (双侧不可达)"
else
  LI=$(echo "$HEALTH_INFO" | $PY -c "import sys,json;d=json.load(sys.stdin);print(d.get('logged_in'),d.get('ready'))" 2>/dev/null)
  LOGGED=$(echo "$LI" | awk '{print $1}')
  READY=$(echo "$LI" | awk '{print $2}')
  echo "CH_HOST=$CH_HOST logged_in=$LOGGED ready=$READY"
  if [ "$LOGGED" != "True" ] || [ "$READY" != "True" ]; then
    CH_STATE="WECHAT_NOT_LOGGED_IN"
  else
    # 解析 data.sessions
    SESSIONS=$(echo "$SESS_INFO" | $PY -c "import sys,json
try:
  d=json.load(sys.stdin)
  s=d.get('data',{}).get('sessions')
  if s is None: s=d.get('sessions')
  print('\n'.join(s) if isinstance(s,list) else '')
except Exception as e:
  print('')" 2>/dev/null)
    NL=$($PY -c "import re;print(re.sub(r'\s+','',\"\"\"$SESSIONS\"\"\"))")
    if echo "$NL" | grep -q "上海臻肆外卖运营-盯个盯-饭敢当"; then
      TARGET_PRESENT="True"
    else
      TARGET_PRESENT="False"
    fi
    if echo "$NL" | grep -q "FEIBINGNEOAI数字员工"; then
      ALERT_PRESENT="True"
    else
      ALERT_PRESENT="False"
    fi
    if [ "$TARGET_PRESENT" != "True" ]; then
      CH_STATE="SESSION_MISSING_TARGET"
    else
      CH_STATE="AVAILABLE"
    fi
    echo "SESSIONS_COUNT=$(echo "$SESSIONS" | grep -c .)"
  fi
fi
echo "CHANNEL_STATE=$CH_STATE TARGET_PRESENT=$TARGET_PRESENT ALERT_PRESENT=$ALERT_PRESENT"

# ---- 判据自检 ----
echo "===== 判据自检 ====="
cd "$ZJ"
SELFTEST=$($NODE runtime/auth_keepalive.mjs --self-test 2>&1)
echo "$SELFTEST"
ST_PASS=$(echo "$SELFTEST" | grep -oE '[0-9]+ passed' | grep -oE '[0-9]+')
ST_FAIL=$(echo "$SELFTEST" | grep -oE '[0-9]+ failed' | grep -oE '[0-9]+')
echo "SELFTEST_PASS=$ST_PASS SELFTEST_FAIL=$ST_FAIL"
if [ "$ST_FAIL" != "0" ] && [ -n "$ST_FAIL" ]; then
  echo "SELFTEST_RESULT=FAILED"
else
  echo "SELFTEST_RESULT=OK"
fi

# ---- 真会话探活 ----
echo "===== 真会话探活 ====="
PROBE_OUT=$($NODE runtime/auth_keepalive.mjs 2>&1)
PROBE_RC=$?
echo "$PROBE_OUT"
echo "PROBE_RC=$PROBE_RC"

# ---- 监理闭环看板 ----
echo "===== 监理闭环看板 ====="
WAR=$($PY -c "import json,datetime;d=json.load(open('$ZJ/runtime/state/war_room.json'));now=datetime.datetime.now();rows=[]
for k,v in d.get('items',{}).items():
  st=v.get('status')
  if st in ('breached','awaiting_you'):
    dl=v.get('sla_deadline')
    overdue=False
    if dl:
      try:
        overdue=datetime.datetime.fromisoformat(dl)<now
      except: overdue=False
    rows.append((k,st,dl,overdue,v.get('ask','')[:200]))
for r in rows: print(r)
print('WAR_COUNT',len(rows))" 2>&1)
echo "$WAR"

# ===== 汇总判定 =====
echo "===== 汇总 ====="
echo "CHANNEL_STATE=$CH_STATE"
echo "SELFTEST_PASS=$ST_PASS SELFTEST_FAIL=$ST_FAIL"
echo "PROBE_RC=$PROBE_RC"
echo "DONE"

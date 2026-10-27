#!/bin/zsh
# 通道自检修正版（zsh 兼容，中继用 RELAYPORT）
set +e
GW=/Users/ddt/work/projects/ai_agent/wechat-windows-driver/gateway.json
TOKFILE=/Users/ddt/work/projects/ai_agent/wechat-windows-driver/接入包/连接信息.txt
PY=/usr/bin/python3

PORT=$($PY -c "import json;print(json.load(open('$GW'))['port'])")
RELAYPORT=$($PY -c "import json;print(json.load(open('$GW')).get('relay_port',8732))")
# zsh 数组赋值（不用 mapfile）
CAND=($($PY -c "import json;[print(c) for c in json.load(open('$GW'))['candidates']]"))
echo "PORT=$PORT RELAYPORT=$RELAYPORT"
echo "CAND=$CAND"

# TOKEN 仅运行时读取
TOKEN=$(grep -oE 'XFVfZHoKwjHaWsZ7EXt2kNvWLSg4TGSvIpMQnvIkCaY|[A-Za-z0-9]{20,}' "$TOKFILE" | head -1)

CH_HOST=""
HEALTH_INFO=""
SESS_INFO=""

probe_health () { curl -s --noproxy '*' -m 5 "http://${1}:${2}/health" 2>/dev/null; }
probe_sessions () { curl -s --noproxy '*' -m 8 -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" -X POST "http://${1}:${2}/" -d '{"action":"list_sessions"}' 2>/dev/null; }

for c in $CAND; do
  H=$(probe_health "$c" "$PORT")
  if echo "$H" | grep -q 'agent up'; then
    CH_HOST="$c"; HEALTH_INFO="$H"; SESS_INFO=$(probe_sessions "$c" "$PORT"); break
  fi
done

if [ -z "$CH_HOST" ]; then
  H=$(probe_health "127.0.0.1" "$RELAYPORT")
  if echo "$H" | grep -q 'agent up'; then
    CH_HOST="127.0.0.1:$RELAYPORT"; HEALTH_INFO="$H"; SESS_INFO=$(probe_sessions "127.0.0.1" "$RELAYPORT")
  fi
fi

if [ -z "$CH_HOST" ]; then
  echo "CHANNEL_STATE=UNREACHABLE"
  exit 0
fi

LOGGED=$(echo "$HEALTH_INFO" | $PY -c "import sys,json;print(json.load(sys.stdin).get('logged_in'))" 2>/dev/null)
READY=$(echo "$HEALTH_INFO" | $PY -c "import sys,json;print(json.load(sys.stdin).get('ready'))" 2>/dev/null)
echo "CH_HOST=$CH_HOST logged_in=$LOGGED ready=$READY"

if [ "$LOGGED" != "True" ] || [ "$READY" != "True" ]; then
  echo "CHANNEL_STATE=WECHAT_NOT_LOGGED_IN"
  exit 0
fi

SESSIONS=$(echo "$SESS_INFO" | $PY -c "import sys,json
try:
  d=json.load(sys.stdin); s=d.get('data',{}).get('sessions')
  if s is None: s=d.get('sessions')
  print('\n'.join(s)) if isinstance(s,list) else print('')
except Exception: print('')" 2>/dev/null)
NL=$($PY -c "import re;print(re.sub(r'\s+','',open('/dev/stdin').read()))" <<<"$SESSIONS")
echo "SESSIONS_COUNT=$(echo "$SESSIONS" | grep -c .)"
echo "$SESSIONS" | head -20

TARGET_PRESENT=$(echo "$NL" | grep -q "上海臻肆外卖运营-盯个盯-饭敢当" && echo True || echo False)
ALERT_PRESENT=$(echo "$NL" | grep -q "FEIBINGNEOAI数字员工" && echo True || echo False)
echo "TARGET_PRESENT=$TARGET_PRESENT ALERT_PRESENT=$ALERT_PRESENT"

if [ "$TARGET_PRESENT" != "True" ]; then
  echo "CHANNEL_STATE=SESSION_MISSING_TARGET"
else
  echo "CHANNEL_STATE=AVAILABLE"
fi

#!/usr/bin/env bash
# 四岗位登录态保活探针 + 监理闭环看板超时告警
# 用法: bash login_state_probe.sh
set -u
RUNTIME=/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/runtime
GJ=/Users/ddt/work/projects/ai_agent/wechat-windows-driver/gateway.json
CONN=/Users/ddt/work/projects/ai_agent/wechat-windows-driver/接入包/连接信息.txt
GROUP="FEIBING NEO AI数字员工"
JUDGE=$RUNTIME/_probe_judge.py
BGUP=$RUNTIME/bg-chrome-up.sh
PATROL_LOG=$RUNTIME/patrol_log.txt
WAR_ROOM=$RUNTIME/state/war_room.json
TMP=$(mktemp -d)
PORTS=(9230 9231 9232 9233)
TS=$(date '+%Y-%m-%d %H:%M:%S')

# 1) 对时
echo "===== 四岗位登录态保活探针 $TS ====="
date
echo "[对时] 本机: $(date '+%Y-%m-%d %H:%M:%S %Z')"

# 2) 随机等待 1-15 分钟
WAIT=$(( ( RANDOM % 900 ) + 60 ))
echo "[等待] 随机等待 ${WAIT}s 后开始探测..."
sleep $WAIT

# 夜间判定 (20:00-次日08:00)
HOUR=$(date +%H)
IS_NIGHT=0
if [ "$HOUR" -ge 20 ] || [ "$HOUR" -lt 8 ]; then IS_NIGHT=1; fi
echo "[时段] hour=$HOUR IS_NIGHT=$IS_NIGHT"

# ---- 网关候选 + TOKEN (仅本地读取, 不外写) ----
TOKEN=$(/usr/bin/python3 -c "import re,sys;d=open('$CONN',encoding='utf-8').read();m=re.search(r'^TOKEN\s+(\S+)',d,re.M);print(m.group(1) if m else '')")
CAND=$(/usr/bin/python3 -c "import json;print(' '.join(json.load(open('$GJ'))['candidates']))")
PORT=$(/usr/bin/python3 -c "import json;print(json.load(open('$GJ')).get('port',8731))")
echo "[网关] candidates=$CAND port=$PORT"

# ---- 枚举四岗位 (shell curl, 沙箱内可达) ----
enum_one() {
  local port=$1
  local out=$TMP/$port.json
  local code
  code=$(curl -s --noproxy '*' -m 4 -H "Host: localhost" "http://127.0.0.1:$port/json/list" -o "$out" -w "%{http_code}" 2>/dev/null)
  if [ "$code" != "200" ] || [ ! -s "$out" ]; then
    echo "ENUM_FAIL" > "$out"
    echo "[枚举] $port -> HTTP $code (FAIL)"
  else
    local pc
    pc=$(/usr/bin/python3 -c "import json;d=json.load(open('$out'));print(len([t for t in d if isinstance(t,dict) and t.get('type')=='page']) if isinstance(d,list) else 'n/a')" 2>/dev/null)
    echo "[枚举] $port -> HTTP 200 OK ($pc page)"
  fi
}

echo "----- 第一轮枚举 -----"
for p in "${PORTS[@]}"; do enum_one "$p"; done

# 判定 (含 war_room)
JUDGE_JSON=$(/usr/bin/python3 "$JUDGE" "$TMP/9230.json" "$TMP/9231.json" "$TMP/9232.json" "$TMP/9233.json" "$WAR_ROOM")
echo "[判定] $JUDGE_JSON"

BROWSER_DOWN=$(echo "$JUDGE_JSON" | /usr/bin/python3 -c "import json,sys;print(' '.join(json.load(sys.stdin)['browser_down']))")
if [ -n "$BROWSER_DOWN" ]; then
  echo "[动作] 检测到浏览器枚举失败 $BROWSER_DOWN -> 按手册§2.2 幂等拉起 bg-chrome-up.sh"
  bash "$BGUP" >/dev/null 2>&1 || true
  echo "[动作] 等待 25s 让浏览器/页面恢复..."
  sleep 25
  echo "----- 第二轮枚举(仅失败端口) -----"
  for p in $BROWSER_DOWN; do enum_one "$p"; done
  JUDGE_JSON=$(/usr/bin/python3 "$JUDGE" "$TMP/9230.json" "$TMP/9231.json" "$TMP/9232.json" "$TMP/9233.json" "$WAR_ROOM")
  echo "[判定-复探] $JUDGE_JSON"
fi

# ---- 是否需要发告警 ----
LOGIN_RED=$(echo "$JUDGE_JSON" | /usr/bin/python3 -c "import json,sys;print(' '.join(json.load(sys.stdin)['login_red']))")
WAR_BREACHED=$(echo "$JUDGE_JSON" | /usr/bin/python3 -c "import json,sys;d=json.load(sys.stdin);print(len(d['war_breached']))")
WAR_OVERDUE=$(echo "$JUDGE_JSON" | /usr/bin/python3 -c "import json,sys;d=json.load(sys.stdin);print(len(d['war_overdue']))")

NEED_ALERT=0
[ -n "$BROWSER_DOWN" ] && NEED_ALERT=1
[ -n "$LOGIN_RED" ] && NEED_ALERT=1
[ "$WAR_BREACHED" -gt 0 ] && NEED_ALERT=1
[ "$WAR_OVERDUE" -gt 0 ] && NEED_ALERT=1

# ---- 行状态汇总 ----
SUMMARY=$(echo "$JUDGE_JSON" | /usr/bin/python3 -c "import json,sys;print(json.load(sys.stdin)['summary'])")
echo "===== 岗位状态汇总 ====="
echo "$SUMMARY"

if [ "$NEED_ALERT" -eq 0 ]; then
  echo "[结论] 本轮无异常，未发送任何微信告警。"
  echo "$TS | $SUMMARY | 无异常 无告警" >> "$PATROL_LOG"
  rm -rf "$TMP"
  exit 0
fi

# ---- 构造告警正文 ----
ALERT_TITLE=""
ALERT_BODY=$(/usr/bin/python3 - "$JUDGE_JSON" "$GROUP" <<'PY'
import json,sys
d=json.loads(sys.argv[1]); group=sys.argv[2]
lines=[]
login_red=d['login_red']; bdown=d['browser_down']; wb=d['war_breached']; wo=d['war_overdue']
sections=[]
if bdown or login_red:
    sections.append("【四岗位登录态异常】")
    for p in (bdown+login_red):
        s=d['stations'].get(p,{})
        sections.append(f"  · {p}({s.get('name','?')}): {s.get('status','?')} — {s.get('detail','')}")
if wb or wo:
    items=wb+wo
    sections.append("【⚠️ 监理待办超时】以下待办已超 SLA，需大同拍板，授权即做：")
    for it in items:
        sections.append(f"  · [{it.get('key','')}] {it.get('ask','')}")
body="\n".join(sections)
# 标题: 两类都触发则合并
title="⚠️ 四岗位登录态异常"
if (wb or wo) and (bdown or login_red):
    title="⚠️ 四岗位登录态异常 / 监理待办超时"
elif (wb or wo):
    title="⚠️ 监理待办超时"
print(json.dumps({"title":title,"body":body},ensure_ascii=False))
PY
)
TITLE=$(echo "$ALERT_BODY" | /usr/bin/python3 -c "import json,sys;print(json.load(sys.stdin)['title'])")
BODY=$(echo "$ALERT_BODY" | /usr/bin/python3 -c "import json,sys;print(json.load(sys.stdin)['body'])")

# ---- 网关可达性 + 身份校验 ----
GW=""
GW_INFO=""
for h in $CAND; do
  hresp=$(curl -s --noproxy '*' -m 4 -H "Authorization: Bearer $TOKEN" "http://$h:$PORT/health" 2>/dev/null)
  if echo "$hresp" | grep -qi "agent up"; then
    sess=$(curl -s --noproxy '*' -m 6 -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -X POST "http://$h:$PORT/" -d '{"action":"list_sessions","params":{}}' 2>/dev/null)
    if echo "$sess" | grep -q "FEIBING NEO AI数字员工"; then
      GW=$h; GW_INFO="identity verified"; break
    else
      GW_INFO="$h health ok but identity mismatch"
    fi
  else
    GW_INFO="$h health fail"
  fi
done

if [ -z "$GW" ]; then
  if [ "$IS_NIGHT" -eq 1 ]; then
    echo "[网关] 夜间双侧不可达=预期（主机休眠），不告警不重试。"
    echo "$TS | $SUMMARY | 需告警但网关夜间不可达=预期 未发" >> "$PATROL_LOG"
  else
    echo "[网关] 非夜间但网关不可达($GW_INFO)，无法发告警，请检查网关/中继。"
    echo "$TS | $SUMMARY | 需告警但网关不可达($GW_INFO) 未发" >> "$PATROL_LOG"
  fi
  rm -rf "$TMP"
  exit 0
fi

echo "[网关] 命中 $GW ($GW_INFO)"

# ---- 发送告警 ----
FULL="$TITLE
$BODY

（本告警由四岗位登录态保活探针自动发出 / $(date '+%Y-%m-%d %H:%M:%S')）"
BODY_JSON=$(/usr/bin/python3 - "$GROUP" "$FULL" <<'PY'
import json,sys
print(json.dumps({"action":"send_message","params":{"who":sys.argv[1],"text":sys.argv[2]}},ensure_ascii=False))
PY
)
SEND_RESP=$(curl -s --noproxy '*' -m 120 -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -X POST "http://$GW:$PORT/" -d "$BODY_JSON" 2>/dev/null)
echo "[发送] 响应: $SEND_RESP"
if echo "$SEND_RESP" | grep -q '"ok":\s*true\|"ok": true'; then
  echo "[结论] 已发群告警，请大同扫码/处理。"
  echo "$TS | $SUMMARY | 已发群告警($GW) 请大同处理" >> "$PATROL_LOG"
else
  echo "[结论] 发送返回非 ok，请人工确认: $SEND_RESP"
  echo "$TS | $SUMMARY | 发送返回异常: $SEND_RESP" >> "$PATROL_LOG"
fi

rm -rf "$TMP"

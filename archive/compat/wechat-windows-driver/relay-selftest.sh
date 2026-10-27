#!/usr/bin/env bash
# 中继「慢响应」回归自测 —— 防 2026-10-06 那次 P0（中继静默丢弃 >8s 的上游响应）。
#
# 背景：localhost_relay.py 曾是 `create_connection(..., timeout=8)`，8s 超时残留到
# pump 的 dst.recv() 上，超时抛 OSError 被 `except OSError: pass` 吞掉 ⇒ 响应泵线程死
# ⇒ 任何 >8s 的上游响应（= 真实微信发送，UI 自动化必然 >8s）永远回不到调用方，
# 表现为「消息已发出，但调用方挂死到超时」。
#
# 为什么必须单独立这个自测：**纯 /health 探活探不出本缺陷**（快接口永远通）。
#
# 做法：假上游(127.0.0.1:18731) 的 /health 秒回、/slow 睡 12s；用**真中继代码**
# （同一份 localhost_relay.py，只是另起实例、另指上游）转发，对比直连与经中继。
#
# 判据：经中继 /slow 必须等到 HTTP 200 + 完整 body；否则 FAIL（退出码 1）。
# 全程 hermetic：只绑 127.0.0.1，不接触微信、不发任何消息。
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PY="${RELAY_SELFTEST_PYTHON:-/Users/ddt/work/projects/ai_agent/.venvs/harmonyos3-phone-control/bin/python3}"
[ -x "$PY" ] || PY=/usr/bin/python3

UP_PORT=18731
RL_PORT=18732
SLEEP=12

cleanup() {
  [ -n "${UP:-}" ] && kill "$UP" 2>/dev/null
  [ -n "${RL:-}" ] && kill "$RL" 2>/dev/null
  lsof -tnP -iTCP:"$UP_PORT" -sTCP:LISTEN 2>/dev/null | xargs -r kill 2>/dev/null
  lsof -tnP -iTCP:"$RL_PORT" -sTCP:LISTEN 2>/dev/null | xargs -r kill 2>/dev/null
}
trap cleanup EXIT

lsof -tnP -iTCP:"$UP_PORT" -sTCP:LISTEN 2>/dev/null | xargs -r kill 2>/dev/null
lsof -tnP -iTCP:"$RL_PORT" -sTCP:LISTEN 2>/dev/null | xargs -r kill 2>/dev/null
sleep 0.5

"$PY" "$HERE/relay-selftest-upstream.py" "$UP_PORT" "$SLEEP" >/dev/null 2>&1 &
UP=$!
sleep 1.2

RELAY_LISTEN_PORT="$RL_PORT" RELAY_TARGET_HOST=127.0.0.1 RELAY_TARGET_PORT="$UP_PORT" \
RELAY_REPROBE_SECONDS=3600 "$PY" "$HERE/localhost_relay.py" >/dev/null 2>&1 &
RL=$!
sleep 1.5

fail=0

echo "── ① 直连假上游 /slow（对照：应 ~${SLEEP}s 拿到完整响应）"
code=$(curl -s --noproxy '*' --max-time $((SLEEP + 15)) -o /dev/null -w '%{http_code}' \
       "http://127.0.0.1:$UP_PORT/slow" || echo 000)
echo "   直连 /slow -> HTTP $code"
[ "$code" = "200" ] || { echo "   ✗ 对照臂异常（假上游有问题，非中继问题）"; fail=1; }

echo "── ② 经中继 /slow（被测：>8s 响应必须完整返回）"
body=$(curl -s --noproxy '*' --max-time $((SLEEP + 15)) \
       "http://127.0.0.1:$RL_PORT/slow" 2>/dev/null || true)
echo "   经中继 /slow -> [${body}]"
if printf '%s' "$body" | grep -q 'slow-done'; then
  echo "   ✓ PASS：慢响应完整返回"
else
  echo "   ✗ FAIL：慢响应被丢弃/截断 —— localhost_relay.py 的 IO 超时修复可能已回退"
  fail=1
fi

echo "── ③ 经中继 /health（对照：快响应必须通）"
h=$(curl -s --noproxy '*' --max-time 8 "http://127.0.0.1:$RL_PORT/health" 2>/dev/null || true)
printf '%s' "$h" | grep -q 'agent up' && echo "   ✓ 快响应正常" || { echo "   ✗ 快响应也挂了"; fail=1; }

echo
if [ "$fail" = "0" ]; then echo "relay-selftest: ALL PASS"; else echo "relay-selftest: FAILED"; fi
exit "$fail"

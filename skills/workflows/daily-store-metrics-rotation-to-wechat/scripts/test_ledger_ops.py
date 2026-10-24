#!/usr/bin/env python3
"""ledger_ops 离线自测：**只跑在台账副本上**，绝不碰生产台账。

覆盖：dry-run 不落盘 / 幂等 verified 不重复 / unknown 不重发 / blocked 可重试 /
宽表打勾 / 已完成数公式不被破坏 / 缺群名 fail-closed / plan 未登记指标时 fail-closed。
"""
import json
import pathlib
import shutil
import subprocess
import sys

from openpyxl import load_workbook

PY = sys.executable
WF = pathlib.Path(__file__).resolve().parent.parent
OPS = WF / "scripts" / "ledger_ops.py"
SRC = WF / "docs" / "全店铺运营指标商家反馈台账_2026-10.xlsx"
TMP = pathlib.Path("/tmp/ledger_ops_test")
TMP.mkdir(exist_ok=True)
LED = TMP / "台账副本_2026-10.xlsx"

if not SRC.exists():
    sys.exit(f"缺少源台账：{SRC}")
if LED.exists():
    LED.unlink()
shutil.copy2(SRC, LED)

fails = []


def run(*args):
    p = subprocess.run([PY, str(OPS), "--ledger", str(LED), *args],
                       capture_output=True, text=True)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  <- {detail}"))
    if not cond:
        fails.append(name)


def rec_count():
    ws = load_workbook(LED)["当月反馈记录"]
    return sum(1 for r in ws.iter_rows(min_row=2, values_only=True) if r and r[2])


def wide(sid, metric):
    ws = load_workbook(LED)["指标进度"]
    ph = [c.value for c in ws[1]]
    mc = ph.index(metric) + 1
    for r in range(2, ws.max_row + 1):
        if str(ws.cell(row=r, column=1).value).strip() == sid:
            return ws.cell(row=r, column=mc).value, ws.cell(row=r, column=ph.index("已完成数") + 1).value
    return "NOT-FOUND", None


ws_pool = load_workbook(LED)["店铺池"]
SID = str(ws_pool.cell(row=2, column=1).value).strip()
SNAME = str(ws_pool.cell(row=2, column=2).value).strip()
print(f"测试店铺：{SID} {SNAME}")

base = rec_count()
check("初始无反馈记录", base == 0, base)

# 1) dry-run 不落盘
rc, out, _ = run("record", "--store-id", SID, "--metric", "M01",
                 "--result", "verified", "--group", "测试群")
check("dry-run 返回 applied=dry-run", json.loads(out)["decision"] == "dry-run", out)
check("dry-run 未新增行", rec_count() == base, rec_count())

# 2) 缺群名 fail-closed
rc, out, _ = run("record", "--store-id", SID, "--metric", "M01",
                 "--result", "verified", "--require-group", "--apply")
check("缺群名 blocked 且退出码 3", rc == 3 and json.loads(out)["decision"] == "blocked", f"{rc} {out}")
check("缺群名未新增行", rec_count() == base, rec_count())

# 3) 正式写入
rc, out, _ = run("record", "--store-id", SID, "--metric", "M01",
                 "--result", "verified", "--group", "测试群",
                 "--shot", "/tmp/a.png", "--apply")
j = json.loads(out)
check("apply 写入成功", rc == 0 and j["decision"] == "applied", out)
check("新增 1 行", rec_count() == base + 1, rec_count())
check("宽表已打勾", j["wide_marked"] is True, j)
v, f = wide(SID, "M01")
check("宽表 M01 写入日期", isinstance(v, str) and v.startswith("2026-"), v)
check("已完成数为 COUNTA 公式", isinstance(f, str) and f.startswith("=COUNTA"), f)

# 4) 重跑幂等
rc, out, _ = run("record", "--store-id", SID, "--metric", "M01",
                 "--result", "verified", "--group", "测试群", "--apply")
check("重跑返回 already", json.loads(out)["decision"] == "already", out)
check("重跑未新增行", rec_count() == base + 1, rec_count())

# 5) blocked 可重试（换另一店）
SID2 = str(ws_pool.cell(row=3, column=1).value).strip()
rc, out, _ = run("record", "--store-id", SID2, "--metric", "M01",
                 "--result", "blocked", "--group", "测试群", "--note", "switch-timeout", "--apply")
check("blocked 可写入", json.loads(out)["decision"] == "applied", out)
v2, _ = wide(SID2, "M01")
check("blocked 不打勾宽表", not v2, v2)
rc, out, _ = run("record", "--store-id", SID2, "--metric", "M01",
                 "--result", "verified", "--group", "测试群", "--apply")
check("blocked 后补发成功", json.loads(out).get("wide_marked") is True, out)

# 6) unknown 不重发（第三店）
SID3 = str(ws_pool.cell(row=4, column=1).value).strip()
run("record", "--store-id", SID3, "--metric", "M01", "--result", "unknown",
    "--group", "测试群", "--apply")
rc, out, _ = run("record", "--store-id", SID3, "--metric", "M01", "--result", "verified",
                 "--group", "测试群", "--apply")
check("unknown 后重跑判 already", json.loads(out)["decision"] == "already", out)
check("unknown 原因文案正确", "绝不重发" in json.loads(out)["reason"], out)

# 7) 其他表未被破坏
wb = load_workbook(LED)
check("店铺池仍有 486 行数据", wb["店铺池"].max_row == 487, wb["店铺池"].max_row)

# 8) plan：只登记 1 项时，非第 1 个轮次必须 fail-closed
# 第 21 天 slot=0 回到 M01（20 天周期），第 22 天 slot=1 只登记 1 项 ⇒ 必须 fail-closed
rc, out, _ = run("plan", "--date", "2026-10-21")
check("plan 第21天回到 M01（周期正确）", rc == 0 and json.loads(out)["metric"] == "M01", out)
rc, out, _ = run("plan", "--date", "2026-10-22")
j = json.loads(out)
check("plan 未登记指标 fail-closed（退出码 3）", rc == 3, f"{rc} {out}")
check("plan 文案点明缺第几个规则", "补发规则" in j.get("reason", ""), out)
rc, out, _ = run("plan", "--date", "2026-11-01")
j = json.loads(out)
check("plan 第 1 轮正常", rc == 0 and j["metric"] == "M01", out)
check("plan 缺群名计数 = 486-已打勾3 = 483", j["progress"]["no_group"] == 483, j["progress"])

print()
print(f"== 结果：{'全部通过' if not fails else str(len(fails)) + ' 项失败: ' + ', '.join(fails)} ==")
sys.exit(1 if fails else 0)

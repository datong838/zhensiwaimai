import sys,subprocess
from pathlib import Path
sys.path.insert(0,str(Path('skills/workflows/daily-store-metrics-rotation-to-wechat/scripts').resolve()))
from metrics_rotation_daily import brand_lease
node='/Users/ddt/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
with brand_lease():
 p=subprocess.run([node,'skills/workflows/daily-store-metrics-rotation-to-wechat/scripts/switch_shop.mjs','--shop-id','694471','--shop-name','李当家汉派猪蹄饭(一清路店)','--land','stats__center'],capture_output=True,text=True)
 if p.returncode:raise RuntimeError('switch-failed')
 subprocess.run([node,'work/metrics-rotation-development/live-20261021/inspect-goods.mjs'],check=True)

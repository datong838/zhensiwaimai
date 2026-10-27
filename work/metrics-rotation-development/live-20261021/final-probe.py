import sys,subprocess,json
from pathlib import Path
sys.path.insert(0,str(Path('skills/workflows/daily-store-metrics-rotation-to-wechat/scripts').resolve()))
from metrics_rotation_daily import brand_lease
with brand_lease():
 r=subprocess.run(['/Users/ddt/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node','skills/workflows/daily-store-metrics-rotation-to-wechat/scripts/brand_probe.mjs','--expect-chain'],capture_output=True,text=True)
 if r.returncode:raise RuntimeError('final-probe-failed')
 print(r.stdout)

"""Single data-root resolver shared by all video defaults."""
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO_ROOT / 'runtime'))
from business_storage import business_path

def video_root():
    return business_path('video-assets', root=REPO_ROOT)

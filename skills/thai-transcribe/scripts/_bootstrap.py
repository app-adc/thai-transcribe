"""Shared venv bootstrap: every script re-runs itself inside $THAI_TRANSCRIBE_HOME/.venv.

The venv is created on first use and re-synced whenever REQUIREMENTS changes,
so existing installs pick up new dependencies automatically.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

DATA_DIR = Path(os.environ.get("THAI_TRANSCRIBE_HOME") or Path.home() / ".thai-transcribe").expanduser()
VENV_DIR = DATA_DIR / ".venv"
VENV_PYTHON = VENV_DIR / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
REQUIREMENTS = ["faster-whisper>=1.1", "Pillow>=10"]
STAMP = VENV_DIR / "thai-transcribe-requirements.json"


def setup_console():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def in_venv():
    return Path(sys.prefix).resolve() == VENV_DIR.resolve()


def ensure_venv():
    if not VENV_PYTHON.exists():
        print(f"ติดตั้งครั้งแรก: สร้าง venv ที่ {VENV_DIR}…", flush=True)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV_DIR)])
        subprocess.check_call([str(VENV_PYTHON), "-m", "pip", "install", "-q", "--upgrade", "pip"])
    installed = json.loads(STAMP.read_text()) if STAMP.exists() else None
    if installed != REQUIREMENTS:
        print(f"กำลังติดตั้งแพ็กเกจ: {', '.join(REQUIREMENTS)}…", flush=True)
        subprocess.check_call([str(VENV_PYTHON), "-m", "pip", "install", "-q", *REQUIREMENTS])
        STAMP.write_text(json.dumps(REQUIREMENTS))
        print("ติดตั้งเสร็จ", flush=True)


def relaunch_in_venv(script, argv, setup_only=False):
    """Call at the top of main(). Returns only when already running inside the venv."""
    if in_venv():
        return
    ensure_venv()
    if setup_only:
        sys.exit(0)
    sys.exit(subprocess.call([str(VENV_PYTHON), str(Path(script).resolve()), *argv]))


def fmt_hms(seconds):
    seconds = int(seconds)
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def fmt_duration(seconds):
    seconds = int(seconds)
    h, m = seconds // 3600, seconds % 3600 // 60
    return f"{h} ชม. {m} นาที" if h else f"{m} นาที {seconds % 60} วินาที"

"""애플리케이션이 사용하는 경로 모음.

설정과 로그는 사용자 프로필(윈도우: %APPDATA%)에 저장한다. 프로그램 폴더에
쓰지 않으므로 Program Files 아래에 설치해도 권한 문제가 없다.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from . import APP_ID


def _base_data_dir() -> Path:
    if sys.platform == "win32":
        root = os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
        return Path(root) / APP_ID
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_ID
    root = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(root) / APP_ID


DATA_DIR = _base_data_dir()
CONFIG_FILE = DATA_DIR / "settings.json"
SCHEDULE_FILE = DATA_DIR / "schedules.json"
PLAY_LOG_FILE = DATA_DIR / "play_log.jsonl"
APP_LOG_FILE = DATA_DIR / "app.log"


def resource_dir() -> Path:
    """번들된 리소스(기본 차임 등) 폴더. PyInstaller onefile 실행도 지원한다."""
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return Path(bundled) / "assets"
    return Path(__file__).resolve().parent.parent / "assets"


def default_chime_path() -> Path:
    return resource_dir() / "chime.wav"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

"""설정과 예약 목록의 저장/불러오기.

쓰기는 임시 파일에 먼저 기록한 뒤 교체한다. 방송 중 정전이나 강제 종료로
설정 파일이 깨지는 것을 막기 위해서다.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

from .models import ScheduleItem, Settings
from .paths import CONFIG_FILE, SCHEDULE_FILE, ensure_dirs

log = logging.getLogger(__name__)


def _write_json(path: Path, payload) -> None:
    ensure_dirs()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("%s 를 읽지 못해 기본값을 사용합니다: %s", path.name, exc)
        backup = path.with_suffix(path.suffix + ".corrupt")
        try:
            path.replace(backup)
            log.warning("손상된 파일을 %s 로 옮겼습니다.", backup.name)
        except OSError:
            pass
        return default


def load_settings() -> Settings:
    return Settings.from_dict(_read_json(CONFIG_FILE, {}))


def save_settings(settings: Settings) -> None:
    _write_json(CONFIG_FILE, settings.to_dict())


def load_schedules() -> list[ScheduleItem]:
    raw = _read_json(SCHEDULE_FILE, [])
    if isinstance(raw, dict):           # 내보내기 파일 형식도 그대로 읽어준다
        raw = raw.get("schedules", [])
    items: list[ScheduleItem] = []
    for entry in raw or []:
        try:
            items.append(ScheduleItem.from_dict(entry))
        except (TypeError, ValueError) as exc:
            log.warning("예약 항목 하나를 건너뜁니다: %s", exc)
    return items


def save_schedules(items: list[ScheduleItem]) -> None:
    _write_json(SCHEDULE_FILE, [i.to_dict() for i in items])


def export_schedules(items: list[ScheduleItem], path: Path) -> None:
    from . import APP_NAME, APP_VERSION
    from datetime import datetime

    _write_json(
        Path(path),
        {
            "app": APP_NAME,
            "version": APP_VERSION,
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "schedules": [i.to_dict() for i in items],
        },
    )


def import_schedules(path: Path) -> list[ScheduleItem]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = raw.get("schedules", [])
    if not isinstance(raw, list):
        raise ValueError("예약 목록 형식이 아닙니다.")
    return [ScheduleItem.from_dict(entry) for entry in raw]

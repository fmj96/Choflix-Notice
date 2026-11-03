"""방송 재생 기록(JSONL). 한 줄에 한 건씩 append 만 하므로 손상에 강하다."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta

from .paths import PLAY_LOG_FILE, ensure_dirs

log = logging.getLogger(__name__)

RESULT_OK = "성공"
RESULT_FAIL = "실패"
RESULT_SKIP = "건너뜀"
RESULT_STOP = "중지됨"


@dataclass
class PlayRecord:
    time: str
    name: str
    trigger: str        # 예약 / 즉시방송 / 미리듣기
    source: str
    result: str
    detail: str = ""

    @classmethod
    def now(cls, name: str, trigger: str, source: str, result: str, detail: str = "") -> "PlayRecord":
        return cls(datetime.now().isoformat(timespec="seconds"), name, trigger, source, result, detail)


def append(record: PlayRecord) -> None:
    ensure_dirs()
    try:
        with PLAY_LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
    except OSError as exc:
        log.error("재생 로그를 기록하지 못했습니다: %s", exc)


def read_all(limit: int = 2000) -> list[PlayRecord]:
    if not PLAY_LOG_FILE.exists():
        return []
    out: list[PlayRecord] = []
    try:
        with PLAY_LOG_FILE.open("r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError as exc:
        log.error("재생 로그를 읽지 못했습니다: %s", exc)
        return []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(PlayRecord(**json.loads(line)))
        except (json.JSONDecodeError, TypeError):
            continue
    out.reverse()               # 최신이 위로
    return out


def prune(retention_days: int) -> None:
    """보관 기간이 지난 기록을 걷어낸다."""
    if retention_days <= 0 or not PLAY_LOG_FILE.exists():
        return
    cutoff = datetime.now() - timedelta(days=retention_days)
    kept: list[str] = []
    try:
        with PLAY_LOG_FILE.open("r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    stamp = datetime.fromisoformat(json.loads(line)["time"])
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue
                if stamp >= cutoff:
                    kept.append(line)
        PLAY_LOG_FILE.write_text("".join(kept), encoding="utf-8")
    except OSError as exc:
        log.error("재생 로그 정리 실패: %s", exc)


def export_csv(path) -> int:
    import csv
    from pathlib import Path

    records = read_all(limit=100000)
    with Path(path).open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["시각", "이름", "구분", "소스", "결과", "비고"])
        for r in records:
            writer.writerow([r.time.replace("T", " "), r.name, r.trigger, r.source, r.result, r.detail])
    return len(records)

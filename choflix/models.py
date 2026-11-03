"""데이터 모델: 방송 예약 항목과 프로그램 설정.

시각 계산은 모두 로컬 시간(naive datetime) 기준이다. 공지방송은 벽시계
기준으로 동작해야 하므로 UTC 변환 없이 그대로 다룬다.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, time, timedelta

WEEKDAY_NAMES = ["월", "화", "수", "목", "금", "토", "일"]

SOURCE_FILE = "file"

REPEAT_ONCE = "once"
REPEAT_DAILY = "daily"
REPEAT_WEEKLY = "weekly"
REPEAT_INTERVAL = "interval"

REPEAT_LABELS = {
    REPEAT_ONCE: "1회 (지정 날짜)",
    REPEAT_DAILY: "매일",
    REPEAT_WEEKLY: "요일 반복",
    REPEAT_INTERVAL: "주기 반복 (N분마다)",
}

_SEARCH_HORIZON_DAYS = 400


def _parse_time(value: str, fallback: time | None = time(9, 0)) -> time | None:
    """'HH:MM' 을 time 으로. 실패하면 fallback(기본 09:00, None 가능)."""
    try:
        hh, mm = str(value).split(":")[:2]
        hour, minute = int(hh), int(mm)
    except (ValueError, AttributeError):
        return fallback
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return fallback
    return time(hour, minute)


def format_time_kr(value: str) -> str:
    """저장값 '08:50' 을 화면용 '오전 8:50' 으로.

    파일에는 계속 24시간제로 적는다. 정렬·비교·예전 파일 호환이 모두
    그 형식에 기대고 있어서, 12시간제는 보여줄 때만 만든다.
    """
    parsed = _parse_time(value, None)
    if parsed is None:
        return value
    period = "오전" if parsed.hour < 12 else "오후"
    return f"{period} {parsed.hour % 12 or 12}:{parsed.minute:02d}"


def format_datetime_kr(moment: datetime, with_date: bool = True) -> str:
    """datetime 을 '08-24(월) 오전 8:50' 형태로."""
    clock = format_time_kr(f"{moment.hour:02d}:{moment.minute:02d}")
    if not with_date:
        return clock
    return f"{moment:%m-%d}({WEEKDAY_NAMES[moment.weekday()]}) {clock}"


def _parse_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


@dataclass
class ScheduleItem:
    """방송 예약 한 건."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = "새 공지"
    enabled: bool = True

    source_type: str = SOURCE_FILE
    file_path: str = ""

    repeat: str = REPEAT_WEEKLY
    at_time: str = "09:00"
    weekdays: list[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])
    once_date: str = ""
    interval_minutes: int = 60
    interval_start: str = "09:00"
    interval_end: str = "18:00"

    start_date: str = ""
    end_date: str = ""

    volume: float = 1.0
    fade_in_ms: int = 0
    fade_out_ms: int = 300
    play_count: int = 1
    gap_ms: int = 800

    last_fired: str = ""

    def __post_init__(self) -> None:
        # 직접 생성하든 파일에서 읽든 항상 같은 상태가 되도록 여기서 한 번 정리한다.
        self.normalize()

    # ---------------------------------------------------------------- helpers
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ScheduleItem":
        data = dict(data or {})
        # 1.1.0 에서 잠깐 시각을 여러 개(at_times) 저장했다. 그 파일도 읽되
        # 가장 이른 시각 하나만 남긴다.
        if not data.get("at_time") and data.get("at_times"):
            times = [t for t in data["at_times"] if t]
            if times:
                data["at_time"] = sorted(times)[0]
        known = {f for f in cls.__dataclass_fields__}
        clean = {k: v for k, v in data.items() if k in known}
        item = cls(**clean)
        item.normalize()
        return item

    def normalize(self) -> None:
        """외부에서 들어온 값(가져오기 파일 등)을 안전한 범위로 보정한다."""
        if self.source_type != SOURCE_FILE:
            self.source_type = SOURCE_FILE
        if self.repeat not in REPEAT_LABELS:
            self.repeat = REPEAT_WEEKLY
        parsed = _parse_time(self.at_time, None)
        # 잘못된 값은 그대로 두고 is_valid() 가 걸러낸다. 시각을 지어내
        # 엉뚱한 시각에 방송하는 것보다 사용자가 고치게 하는 편이 안전하다.
        if parsed is not None:
            self.at_time = f"{parsed.hour:02d}:{parsed.minute:02d}"
        self.weekdays = sorted({int(d) for d in self.weekdays if 0 <= int(d) <= 6})
        if self.repeat == REPEAT_WEEKLY and not self.weekdays:
            self.weekdays = [0, 1, 2, 3, 4]
        self.volume = min(2.0, max(0.0, float(self.volume)))
        self.interval_minutes = max(1, int(self.interval_minutes))
        self.play_count = min(20, max(1, int(self.play_count)))
        self.gap_ms = max(0, int(self.gap_ms))
        self.fade_in_ms = max(0, int(self.fade_in_ms))
        self.fade_out_ms = max(0, int(self.fade_out_ms))

    @property
    def source_summary(self) -> str:
        if not self.file_path:
            return "파일: (선택 안 됨)"
        return f"파일: {self.file_path.replace(chr(92), '/').rsplit('/', 1)[-1]}"

    @property
    def schedule_summary(self) -> str:
        clock = format_time_kr(self.at_time)
        if self.repeat == REPEAT_ONCE:
            return f"{self.once_date or '날짜 미지정'} {clock}"
        if self.repeat == REPEAT_DAILY:
            return f"매일 {clock}"
        if self.repeat == REPEAT_WEEKLY:
            days = "".join(WEEKDAY_NAMES[d] for d in self.weekdays) or "-"
            return f"{days} {clock}"
        return (f"{format_time_kr(self.interval_start)}~{format_time_kr(self.interval_end)}"
                f" {self.interval_minutes}분마다")

    def is_valid(self) -> tuple[bool, str]:
        if not self.file_path:
            return False, "재생할 음성 파일을 선택하세요."
        if self.repeat == REPEAT_ONCE and not _parse_date(self.once_date):
            return False, "1회 방송은 날짜를 지정해야 합니다."
        if self.repeat != REPEAT_INTERVAL and not self._day_times(date.today()):
            return False, "방송 시각을 올바르게 입력하세요 (예: 09:00)."
        if self.repeat == REPEAT_WEEKLY and not self.weekdays:
            return False, "반복할 요일을 하나 이상 선택하세요."
        if self.repeat == REPEAT_INTERVAL:
            if _parse_time(self.interval_end, time(18, 0)) <= _parse_time(self.interval_start, time(9, 0)):
                return False, "주기 반복의 종료 시각은 시작 시각보다 뒤여야 합니다."
        return True, ""

    # ------------------------------------------------------------- scheduling
    def _day_allowed(self, day: date) -> bool:
        start = _parse_date(self.start_date)
        end = _parse_date(self.end_date)
        if start and day < start:
            return False
        if end and day > end:
            return False
        if self.repeat == REPEAT_ONCE:
            return day == _parse_date(self.once_date)
        if self.repeat == REPEAT_DAILY:
            return True
        return day.weekday() in self.weekdays

    def _day_times(self, day: date) -> list[time]:
        if self.repeat == REPEAT_INTERVAL:
            begin = _parse_time(self.interval_start, time(9, 0))
            finish = _parse_time(self.interval_end, time(18, 0))
            step = timedelta(minutes=self.interval_minutes)
            cursor = datetime.combine(day, begin)
            limit = datetime.combine(day, finish)
            out: list[time] = []
            while cursor <= limit and len(out) < 24 * 60:
                out.append(cursor.time())
                cursor += step
            return out
        slot = _parse_time(self.at_time, None)
        return [slot] if slot else []

    def next_run_at(self, after: datetime) -> datetime | None:
        """`after` 보다 엄격히 뒤에 오는 첫 실행 시각. 없으면 None."""
        if not self.enabled:
            return None
        ok, _ = self.is_valid()
        if not ok:
            return None

        start = _parse_date(self.start_date)
        end = _parse_date(self.end_date)

        if self.repeat == REPEAT_ONCE:
            day = _parse_date(self.once_date)
            if day is None or (start and day < start) or (end and day > end):
                return None
            for slot in self._day_times(day):
                moment = datetime.combine(day, slot)
                if moment > after:
                    return moment
            return None

        for offset in range(_SEARCH_HORIZON_DAYS):
            current = after.date() + timedelta(days=offset)
            if (start and current < start) or (end and current > end):
                # 시작 전이면 계속 탐색하고, 종료일을 넘어섰으면 더 볼 필요가 없다.
                if end and current > end:
                    return None
                continue
            if self.repeat != REPEAT_DAILY and self.weekdays and current.weekday() not in self.weekdays:
                continue
            for slot in self._day_times(current):
                moment = datetime.combine(current, slot)
                if moment > after:
                    return moment
        return None


@dataclass
class Settings:
    """프로그램 전역 설정."""

    output_device: str = ""          # 빈 값이면 시스템 기본 장치
    master_volume: float = 1.0
    chime_path: str = ""             # 빈 값이면 번들 차임 사용
    chime_volume: float = 0.8
    autostart: bool = False
    start_minimized: bool = False
    minimize_to_tray: bool = True
    catchup_seconds: int = 90        # 이 시간 이상 늦은 예약은 건너뛴다
    log_retention_days: int = 90
    duck_on_emergency: bool = True   # 긴급방송 시 진행 중 방송 중단
    column_widths: list[int] = field(default_factory=list)   # 예약 목록 열 폭

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Settings":
        known = {f for f in cls.__dataclass_fields__}
        clean = {k: v for k, v in (data or {}).items() if k in known}
        obj = cls(**clean)
        obj.master_volume = min(2.0, max(0.0, float(obj.master_volume)))
        obj.chime_volume = min(2.0, max(0.0, float(obj.chime_volume)))
        obj.catchup_seconds = max(5, int(obj.catchup_seconds))
        return obj

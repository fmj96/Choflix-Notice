"""예약 감시 스레드와 방송 작업(Job) 조립.

1초마다 벽시계를 확인해 예약 시각이 지난 항목을 재생 큐에 넣는다.
컴퓨터가 절전에서 깨어나 예약 시각이 한참 지나 있으면, 설정한 허용
지연(catchup_seconds)을 넘긴 건은 뒤늦게 틀지 않고 건너뛴다.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta
from typing import Callable

from . import logbook
from .audio import (
    PRIORITY_EMERGENCY,
    PRIORITY_NORMAL,
    AudioError,
    PlaybackEngine,
    PlayJob,
    Segment,
    load_audio,
    silence,
)
from .models import ScheduleItem, Settings
from .paths import default_chime_path

log = logging.getLogger(__name__)

TICK_SECONDS = 1.0
BACKWARD_JUMP = timedelta(minutes=10)       # 시계가 이만큼 뒤로 가면 전체 재계산

TRIGGER_SCHEDULE = "예약"
TRIGGER_MANUAL = "즉시방송"
TRIGGER_PREVIEW = "미리듣기"


# ------------------------------------------------------------------ 세그먼트
def _chime_segments(settings: Settings) -> list[Segment]:
    path = settings.chime_path or str(default_chime_path())
    try:
        data, rate = load_audio(path)
    except AudioError as exc:
        log.warning("차임을 재생하지 못해 건너뜁니다: %s", exc)
        return []
    return [
        Segment(data, rate, settings.chime_volume, 0, 60, "차임"),
        silence(0.25, rate, data.shape[1]),
    ]


def _body_source(item: ScheduleItem) -> str:
    if not item.file_path:
        raise AudioError("재생할 음성 파일이 지정되지 않았습니다.")
    return item.file_path


def build_segments(
    item: ScheduleItem, settings: Settings, with_chime: bool = False
) -> list[Segment]:
    """예약 항목 하나를 재생 세그먼트 목록으로 편다.

    차임은 즉시 방송에서만 쓴다. 예약 방송은 음원만 그대로 내보낸다.
    """
    segments: list[Segment] = []
    if with_chime:
        segments.extend(_chime_segments(settings))

    data, rate = load_audio(_body_source(item))
    channels = data.shape[1]
    for index in range(item.play_count):
        if index > 0 and item.gap_ms > 0:
            segments.append(silence(item.gap_ms / 1000.0, rate, channels))
        segments.append(
            Segment(data, rate, item.volume, item.fade_in_ms, item.fade_out_ms, item.name)
        )
    return segments


def make_job(
    item: ScheduleItem,
    get_settings: Callable[[], Settings],
    trigger: str = TRIGGER_SCHEDULE,
    interrupt: bool = False,
    with_chime: bool = False,
) -> PlayJob:
    """세그먼트 조립을 워커 스레드로 미룬 재생 작업을 만든다.

    파일 디코딩이 큰 음원에서는 수백 ms 걸리므로 UI 스레드에서 하지 않는다.
    """
    snapshot = ScheduleItem.from_dict(item.to_dict())        # 편집 중 변경과 분리
    return PlayJob(
        priority=PRIORITY_EMERGENCY if interrupt else PRIORITY_NORMAL,
        name=snapshot.name,
        trigger=trigger,
        source=snapshot.source_summary,
        prepare=lambda: build_segments(snapshot, get_settings(), with_chime),
        interrupt=interrupt,
    )


# ------------------------------------------------------------------- 서비스
class SchedulerService:
    """예약 감시 스레드."""

    def __init__(
        self,
        get_settings: Callable[[], Settings],
        get_items: Callable[[], list[ScheduleItem]],
        engine: PlaybackEngine,
    ):
        self._get_settings = get_settings
        self._get_items = get_items
        self._engine = engine
        self._next_runs: dict[str, datetime | None] = {}
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._last_tick = datetime.now()
        self._thread = threading.Thread(target=self._run, name="scheduler", daemon=True)

        self.on_fired: Callable[[ScheduleItem, datetime], None] | None = None
        self.on_recalculated: Callable[[], None] | None = None
        self.on_logged: Callable[[], None] | None = None

    # ------------------------------------------------------------ 수명주기
    def start(self) -> None:
        self.reload()
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread.is_alive():
            self._thread.join(timeout=3.0)

    # -------------------------------------------------------------- 재계산
    def reload(self) -> None:
        """예약 목록이 바뀐 뒤 다음 실행 시각을 다시 계산한다."""
        now = datetime.now()
        computed = {item.id: item.next_run_at(now) for item in self._get_items()}
        with self._lock:
            self._next_runs = computed
        self._wake.set()
        if self.on_recalculated:
            try:
                self.on_recalculated()
            except Exception:
                log.exception("재계산 콜백 오류")

    def next_run_of(self, item_id: str) -> datetime | None:
        with self._lock:
            return self._next_runs.get(item_id)

    def upcoming(self) -> tuple[ScheduleItem, datetime] | None:
        """가장 먼저 나갈 예약 한 건."""
        best: tuple[ScheduleItem, datetime] | None = None
        with self._lock:
            snapshot = dict(self._next_runs)
        for item in self._get_items():
            when = snapshot.get(item.id)
            if when and (best is None or when < best[1]):
                best = (item, when)
        return best

    # ---------------------------------------------------------------- 루프
    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(TICK_SECONDS)
            self._wake.clear()
            if self._stop.is_set():
                break
            try:
                self._tick()
            except Exception:                   # 스케줄러가 죽으면 방송이 통째로 멈춘다
                log.exception("스케줄러 tick 오류")

    def _tick(self) -> None:
        now = datetime.now()
        if now < self._last_tick - BACKWARD_JUMP:
            log.info("시스템 시계가 뒤로 조정되어 예약을 재계산합니다.")
            self._last_tick = now
            self.reload()
            return
        self._last_tick = now

        settings = self._get_settings()
        tolerance = timedelta(seconds=settings.catchup_seconds)
        changed = False

        for item in self._get_items():
            with self._lock:
                due = self._next_runs.get(item.id, "missing")
            if due == "missing":                # 새로 추가된 항목
                with self._lock:
                    self._next_runs[item.id] = item.next_run_at(now)
                changed = True
                continue
            if due is None or now < due:
                continue

            late = now - due
            if late <= tolerance:
                self._fire(item, due)
            else:
                log.info("'%s' 예약(%s)이 %s 늦어 건너뜁니다.", item.name, due, late)
                logbook.append(
                    logbook.PlayRecord.now(
                        item.name, TRIGGER_SCHEDULE, item.source_summary, logbook.RESULT_SKIP,
                        f"예약 {due:%Y-%m-%d %H:%M} / {int(late.total_seconds())}초 지연",
                    )
                )
                if self.on_logged:
                    try:
                        self.on_logged()
                    except Exception:
                        log.exception("기록 알림 콜백 오류")
            with self._lock:
                self._next_runs[item.id] = item.next_run_at(now)
            changed = True

        if changed and self.on_recalculated:
            try:
                self.on_recalculated()
            except Exception:
                log.exception("재계산 콜백 오류")

    def _fire(self, item: ScheduleItem, due: datetime) -> None:
        log.info("예약 방송 시작: %s (%s)", item.name, due)
        item.last_fired = due.isoformat(timespec="seconds")
        self._engine.submit(make_job(item, self._get_settings, TRIGGER_SCHEDULE))
        if self.on_fired:
            try:
                self.on_fired(item, due)
            except Exception:
                log.exception("발화 콜백 오류")

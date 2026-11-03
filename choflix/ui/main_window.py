"""메인 창 — 탭들을 묶고, 재생 엔진/스케줄러와 UI 사이를 중계한다."""
from __future__ import annotations

import logging
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox,
    QProgressBar, QPushButton, QSystemTrayIcon, QTabWidget, QVBoxLayout, QWidget,
)

from .. import APP_NAME, APP_VERSION, logbook, store
from ..audio import PlaybackEngine, format_duration
from ..models import ScheduleItem, Settings
from ..scheduler import TRIGGER_MANUAL, SchedulerService, make_job
from .broadcast_tab import BroadcastTab
from .log_tab import LogTab
from .schedule_tab import ScheduleTab, format_next
from .settings_tab import SettingsTab
from .widgets import app_icon

log = logging.getLogger(__name__)

_STOP_BUTTON_WIDTH = 150

# 현재 방송 상태는 중지 버튼과 같은 크기로 읽히게 맞춘다.
_NOW_PLAYING_STYLE = "font-size:15px; font-weight:bold; color:#c0392b;"
_NOW_IDLE_STYLE = "font-size:15px; font-weight:bold; color:#8a8a8a;"

_PROGRESS_STYLE = """
QProgressBar { background: #dcdcdc; border: none; border-radius: 3px; }
QProgressBar::chunk { background: #c0392b; border-radius: 3px; }
"""

STOP_BUTTON_STYLE = """
QPushButton {
    background-color: #c0392b; color: white; font-size: 15px; font-weight: bold;
    padding: 6px 22px; border: none; border-radius: 5px;
}
QPushButton:hover { background-color: #d64435; }
QPushButton:pressed { background-color: #9d2f22; }
"""


class EngineBridge(QObject):
    """워커 스레드의 콜백을 GUI 스레드로 넘기는 신호 묶음."""

    state_changed = Signal(str)
    progress = Signal(float, float)
    job_finished = Signal(str, str, str, str, str)   # 이름, 구분, 소스, 결과, 비고
    schedule_fired = Signal(str)
    logged = Signal()
    recalculated = Signal()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.setWindowIcon(app_icon())
        self.resize(980, 700)

        self.settings: Settings = store.load_settings()
        self.items: list[ScheduleItem] = store.load_schedules()
        logbook.prune(self.settings.log_retention_days)

        self.bridge = EngineBridge()
        self.engine = PlaybackEngine(lambda: self.settings)
        self.scheduler = SchedulerService(lambda: self.settings, lambda: self.items, self.engine)
        self._wire_callbacks()

        self._playing_text = ""
        self._elapsed = ""

        # ScheduleTab 이 만들어지면서 열 폭을 적용하고 저장을 요청하므로
        # 저장 타이머를 UI 보다 먼저 준비해 둔다.
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(lambda: store.save_settings(self.settings))

        self._build_ui()
        self._build_tray()

        self.engine.start()
        self.scheduler.start()

        self._ticker = QTimer(self)
        self._ticker.timeout.connect(self._tick_ui)
        self._ticker.start(1000)


        self._quitting = False
        self._tick_ui()

    # -------------------------------------------------------------- 초기 구성
    def _wire_callbacks(self) -> None:
        self.engine.on_state = self.bridge.state_changed.emit
        self.engine.on_progress = self.bridge.progress.emit
        self.engine.on_finished = lambda job, result, detail: self.bridge.job_finished.emit(
            job.name, job.trigger, job.source, result, detail
        )
        self.scheduler.on_fired = lambda item, due: self.bridge.schedule_fired.emit(item.name)
        self.scheduler.on_recalculated = self.bridge.recalculated.emit
        self.scheduler.on_logged = self.bridge.logged.emit

        self.bridge.state_changed.connect(self._on_state)
        self.bridge.progress.connect(self._on_progress)
        self.bridge.job_finished.connect(self._on_job_finished)
        self.bridge.schedule_fired.connect(self._on_schedule_fired)
        self.bridge.recalculated.connect(self._on_recalculated)
        self.bridge.logged.connect(lambda: self.log_tab.mark_stale())

    def _build_ui(self) -> None:
        # 상단 바: 왼쪽에 중지 버튼, 가운데에 현재 방송 상태.
        # 버튼 폭만큼의 빈 위젯을 오른쪽에 두어야 가운데 글자가 창의 정중앙에 온다.
        top_bar = QWidget()
        top_bar.setStyleSheet("QWidget { background: #f2f2f2; }")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(10, 7, 10, 7)
        top_layout.setSpacing(10)

        # 방송 중지는 급할 때 누르는 버튼이라 어디서든 바로 보이도록 크고 붉게 둔다.
        self.stop_button = QPushButton("■  방송 중지")
        self.stop_button.setToolTip("재생 중인 방송과 대기 중인 방송을 모두 즉시 중지합니다")
        self.stop_button.setStyleSheet(STOP_BUTTON_STYLE)
        self.stop_button.setMinimumHeight(38)
        self.stop_button.setFixedWidth(_STOP_BUTTON_WIDTH)
        self.stop_button.setCursor(Qt.PointingHandCursor)
        self.stop_button.clicked.connect(self.stop_everything)
        top_layout.addWidget(self.stop_button)

        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(3)

        self.now_playing = QLabel()
        self.now_playing.setAlignment(Qt.AlignCenter)
        center_layout.addWidget(self.now_playing)

        # 진행 바는 방송 중에만 보인다. 늘 띄워 두면 시선을 끌기만 한다.
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setStyleSheet(_PROGRESS_STYLE)
        self.progress.setVisible(False)
        center_layout.addWidget(self.progress)

        center.setMinimumHeight(38)
        top_layout.addWidget(center, 1)

        balance = QWidget()                      # 중지 버튼과 같은 폭의 균형추
        balance.setFixedWidth(_STOP_BUTTON_WIDTH)
        top_layout.addWidget(balance)

        self.tabs = QTabWidget()
        self.schedule_tab = ScheduleTab(self)
        self.broadcast_tab = BroadcastTab(self)
        self.log_tab = LogTab(self)
        self.settings_tab = SettingsTab(self)
        self.tabs.addTab(self.schedule_tab, "예약 방송")
        self.tabs.addTab(self.broadcast_tab, "즉시 방송")
        self.tabs.addTab(self.log_tab, "재생 기록")
        self.tabs.addTab(self.settings_tab, "설정")

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(top_bar)
        layout.addWidget(self.tabs, 1)
        self.setCentralWidget(central)

        self.status_next = QLabel()
        self.status_queue = QLabel()
        bar = self.statusBar()
        bar.addWidget(self.status_next, 1)
        bar.addPermanentWidget(self.status_queue)

        self._show_idle()

    def _build_tray(self) -> None:
        self.tray: QSystemTrayIcon | None = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            log.info("시스템 트레이를 사용할 수 없습니다.")
            return

        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip(APP_NAME)

        menu = QMenu()
        menu.addAction("창 열기", self._restore_window)
        menu.addSeparator()
        menu.addAction("방송 중지", self.stop_everything)
        menu.addSeparator()
        menu.addAction("종료", self.quit_app)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    # ---------------------------------------------------- 컨트롤러 인터페이스
    def save_settings(self) -> None:
        store.save_settings(self.settings)
        self.scheduler.reload()

    def save_settings_soon(self) -> None:
        """잠시 뒤 한 번만 저장한다.

        열 폭 드래그처럼 값이 연달아 바뀌는 경우 매번 파일을 쓰면 낭비다.
        """
        self._save_timer.start(800)

    def commit_schedules(self) -> None:
        """예약 목록이 바뀌었을 때: 저장 → 재계산 → 화면 갱신."""
        store.save_schedules(self.items)
        self.scheduler.reload()
        self.schedule_tab.refresh()
        self._tick_ui()

    def play_item(self, item: ScheduleItem, trigger: str = TRIGGER_MANUAL,
                  interrupt: bool = False, with_chime: bool = False) -> None:
        ok, message = item.is_valid()
        if not ok:
            QMessageBox.warning(self, "방송", message)
            return
        force = interrupt and self.settings.duck_on_emergency
        self.engine.submit(
            make_job(item, lambda: self.settings, trigger, interrupt=force,
                     with_chime=with_chime)
        )

    def stop_everything(self) -> None:
        self.engine.stop_all()
        self.toast("방송을 중지했습니다.")

    def toast(self, message: str, seconds: int = 4) -> None:
        self.statusBar().showMessage(message, seconds * 1000)

    # --------------------------------------------------------------- 신호 처리
    def _show_idle(self) -> None:
        self._playing_text = ""
        self._elapsed = ""
        self.progress.setVisible(False)
        self._refresh_now_playing()

    def _on_progress(self, position: float, total: float) -> None:
        if total <= 0:
            self.progress.setVisible(False)
            self._elapsed = ""
            return
        self.progress.setVisible(True)
        self.progress.setValue(int(min(1.0, position / total) * 1000))
        self._elapsed = f"  ({format_duration(position)} / {format_duration(total)})"
        self._refresh_now_playing()

    def _refresh_now_playing(self) -> None:
        if self._playing_text:
            self.now_playing.setText(f"▶  {self._playing_text}{self._elapsed}")
            self.now_playing.setStyleSheet(_NOW_PLAYING_STYLE)
        else:
            self.now_playing.setText("대기 중")
            self.now_playing.setStyleSheet(_NOW_IDLE_STYLE)

    def _on_state(self, text: str) -> None:
        if self.engine.is_playing:
            self._playing_text = text
            self._refresh_now_playing()
        else:
            self._show_idle()
        if self.tray:
            self.tray.setToolTip(f"{APP_NAME} — {text}")

    def _on_job_finished(self, name: str, trigger: str, source: str, result: str, detail: str) -> None:
        logbook.append(logbook.PlayRecord.now(name, trigger, source, result, detail))
        self.log_tab.mark_stale()
        if result == logbook.RESULT_FAIL:
            self.toast(f"방송 실패: {name} — {detail.splitlines()[0]}", 8)
            if self.tray and not self.isVisible():
                self.tray.showMessage(
                    f"{APP_NAME} — 방송 실패", f"{name}\n{detail.splitlines()[0]}",
                    QSystemTrayIcon.Critical, 8000,
                )

    def _on_schedule_fired(self, name: str) -> None:
        self.toast(f"예약 방송 시작: {name}")

    def _on_recalculated(self) -> None:
        self.schedule_tab.refresh_next_column()
        self._update_next_label()

    # ------------------------------------------------------------------- 주기
    def _tick_ui(self) -> None:
        self.schedule_tab.refresh_next_column()
        self._update_next_label()
        pending = self.engine.queue_size()
        self.status_queue.setText(f"대기열 {pending}건" if pending else "")

    def _update_next_label(self) -> None:
        upcoming = self.scheduler.upcoming()
        if not upcoming:
            self.status_next.setText("예정된 방송 없음")
            self.status_next.setStyleSheet("color:#888;")
            return
        item, when = upcoming
        text, color = format_next(when)
        self.status_next.setText(f"다음 방송  {item.name}  ·  {text}")
        self.status_next.setStyleSheet(f"color:{color};")

    # ------------------------------------------------------------- 창 / 트레이
    def _on_tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._restore_window()

    def _restore_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event) -> None:
        if self._quitting or not self.settings.minimize_to_tray or self.tray is None:
            self._shutdown()
            event.accept()
            # 트레이 상주를 위해 setQuitOnLastWindowClosed(False) 로 두었으므로,
            # 실제로 끝낼 때는 직접 종료해야 프로세스가 남지 않는다.
            QApplication.quit()
            return
        event.ignore()
        self.hide()
        self.tray.showMessage(
            APP_NAME,
            "트레이에서 계속 실행 중입니다. 예약 방송은 그대로 나갑니다.",
            QSystemTrayIcon.Information, 4000,
        )

    def quit_app(self) -> None:
        if self.engine.is_playing:
            answer = QMessageBox.question(
                self, "종료", "방송이 진행 중입니다. 그래도 종료할까요?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        self._quitting = True
        self.close()

    def _shutdown(self) -> None:
        self._ticker.stop()
        self._save_timer.stop()
        self.scheduler.stop()
        self.engine.stop_all()
        self.engine.shutdown()
        store.save_schedules(self.items)
        store.save_settings(self.settings)
        if self.tray:
            self.tray.hide()
        log.info("정상 종료")

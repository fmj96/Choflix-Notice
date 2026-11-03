"""설정 탭 — 출력 장치, 차임, 자동 실행 등."""
from __future__ import annotations

import threading

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QSlider, QSpinBox,
    QVBoxLayout, QWidget,
)

import logging

from .. import autostart
from ..audio import AudioError, PlayJob, Segment, list_output_devices, load_audio
from ..paths import DATA_DIR, default_chime_path
from .schedule_dialog import AUDIO_FILTER

log = logging.getLogger(__name__)

_DEFAULT_DEVICE_LABEL = "시스템 기본 장치"


class SettingsTab(QWidget):
    """설정 화면.

    오디오 장치 열거는 1~3초가 걸린다. 기동할 때 하면 그만큼 창이 멈추고,
    부팅 자동 실행에서는 더 두드러진다. 그래서 이 탭을 처음 열 때
    백그라운드 스레드에서 불러온다.
    """

    devices_ready = Signal(list)

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._catalog_loaded = False
        self.devices_ready.connect(self._on_devices_ready)

        root = QVBoxLayout(self)
        root.addWidget(self._build_output_group())
        root.addWidget(self._build_chime_group())
        root.addWidget(self._build_general_group())

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        open_folder = QPushButton("설정 폴더 열기")
        open_folder.clicked.connect(self._open_data_dir)
        save = QPushButton("설정 저장")
        save.setDefault(True)
        save.clicked.connect(self.apply)
        button_row.addWidget(open_folder)
        button_row.addWidget(save)
        root.addLayout(button_row)
        root.addStretch(1)

        self.load()

    # --------------------------------------------------------------- 화면 구성
    def _build_output_group(self) -> QGroupBox:
        group = QGroupBox("출력")
        form = QFormLayout(group)

        device_row = QHBoxLayout()
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(320)
        refresh = QPushButton("목록 새로 고침")
        refresh.clicked.connect(self.refresh_devices)
        test = QPushButton("소리 테스트")
        test.clicked.connect(self._test_device)
        device_row.addWidget(self.device_combo, 1)
        device_row.addWidget(refresh)
        device_row.addWidget(test)
        form.addRow("출력 장치", device_row)

        self.device_hint = QLabel()
        self.device_hint.setStyleSheet("color:#666;")
        self.device_hint.setWordWrap(True)
        form.addRow("", self.device_hint)

        volume_row = QHBoxLayout()
        self.master_volume = QSlider(Qt.Horizontal)
        self.master_volume.setRange(0, 200)
        self.master_label = QLabel()
        self.master_label.setFixedWidth(52)
        self.master_volume.valueChanged.connect(lambda v: self.master_label.setText(f"{v} %"))
        volume_row.addWidget(self.master_volume, 1)
        volume_row.addWidget(self.master_label)
        form.addRow("전체 볼륨", volume_row)
        return group

    def _build_chime_group(self) -> QGroupBox:
        group = QGroupBox("시작 차임 (즉시 방송 전용)")
        form = QFormLayout(group)

        row = QHBoxLayout()
        self.chime_edit = QLineEdit()
        self.chime_edit.setPlaceholderText(f"비워 두면 기본 차임 사용 ({default_chime_path().name})")
        browse = QPushButton("찾아보기…")
        browse.clicked.connect(self._browse_chime)
        reset = QPushButton("기본값")
        reset.clicked.connect(lambda: self.chime_edit.clear())
        listen = QPushButton("들어보기")
        listen.clicked.connect(self._test_chime)
        row.addWidget(self.chime_edit, 1)
        row.addWidget(browse)
        row.addWidget(reset)
        row.addWidget(listen)
        form.addRow("차임 파일", row)

        volume_row = QHBoxLayout()
        self.chime_volume = QSlider(Qt.Horizontal)
        self.chime_volume.setRange(0, 200)
        self.chime_volume_label = QLabel()
        self.chime_volume_label.setFixedWidth(52)
        self.chime_volume.valueChanged.connect(
            lambda v: self.chime_volume_label.setText(f"{v} %")
        )
        volume_row.addWidget(self.chime_volume, 1)
        volume_row.addWidget(self.chime_volume_label)
        form.addRow("차임 볼륨", volume_row)
        return group

    def _build_general_group(self) -> QGroupBox:
        group = QGroupBox("일반")
        form = QFormLayout(group)

        self.autostart_box = QCheckBox("윈도우 시작 시 자동 실행")
        if not autostart.supported():
            self.autostart_box.setEnabled(False)
            self.autostart_box.setToolTip("윈도우에서만 사용할 수 있습니다.")
        self.tray_box = QCheckBox("창을 닫아도 트레이에서 계속 실행")
        self.minimized_box = QCheckBox("프로그램 시작 시 트레이로 최소화")
        form.addRow("", self.autostart_box)
        form.addRow("", self.tray_box)
        form.addRow("", self.minimized_box)

        self.catchup = QSpinBox()
        self.catchup.setRange(5, 3600)
        self.catchup.setSuffix(" 초")
        self.catchup.setToolTip(
            "절전이나 프로그램 재시작으로 예약 시각을 놓쳤을 때, "
            "이 시간 안쪽이면 늦게라도 방송하고 넘으면 건너뜁니다."
        )
        form.addRow("지연 허용", self.catchup)

        self.retention = QSpinBox()
        self.retention.setRange(0, 3650)
        self.retention.setSuffix(" 일 (0이면 계속 보관)")
        form.addRow("기록 보관", self.retention)

        self.duck_box = QCheckBox("긴급 방송이 들어오면 진행 중인 방송을 끊기")
        form.addRow("", self.duck_box)
        return group

    # ------------------------------------------------------------------- 목록
    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._catalog_loaded:
            self._catalog_loaded = True
            self._load_catalog()

    def _load_catalog(self) -> None:
        """출력 장치 목록을 백그라운드에서 읽어 온다."""
        self.device_combo.setEnabled(False)
        self.device_hint.setText("출력 장치를 찾는 중…")
        threading.Thread(target=self._load_worker, daemon=True).start()

    def _load_worker(self) -> None:
        try:
            devices = list_output_devices()
        except AudioError as exc:
            log.warning("장치 목록을 읽지 못했습니다: %s", exc)
            devices = []
        self.devices_ready.emit(devices)

    def refresh_devices(self) -> None:
        self._load_catalog()

    def _on_devices_ready(self, devices: list) -> None:
        saved = self.controller.settings.output_device
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        self.device_combo.addItem(_DEFAULT_DEVICE_LABEL, "")
        for device in devices:
            suffix = "  ★ 기본" if device.is_default else ""
            self.device_combo.addItem(f"{device.label}{suffix}", device.label)

        index = self.device_combo.findData(saved)
        if index < 0 and saved:
            self.device_combo.addItem(f"{saved}  (연결 안 됨)", saved)
            index = self.device_combo.count() - 1
        self.device_combo.setCurrentIndex(max(0, index))
        self.device_combo.blockSignals(False)
        self.device_combo.setEnabled(True)

        if devices:
            self.device_hint.setText(
                f"출력 가능한 장치 {len(devices)}개를 찾았습니다. "
                "방송용 앰프가 USB 사운드카드에 물려 있다면 그 장치를 고르세요."
            )
        else:
            self.device_hint.setText(
                "⚠ 출력 가능한 오디오 장치를 찾지 못했습니다. 사운드카드 연결과 드라이버를 확인하세요."
            )

    def _seed_combos(self) -> None:
        """열거가 끝나기 전에도 저장된 장치가 유지되도록 미리 채워 둔다."""
        saved = self.controller.settings.output_device
        combo = self.device_combo
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(_DEFAULT_DEVICE_LABEL, "")
        if saved:
            combo.addItem(f"{saved}  (확인 중…)", saved)
            combo.setCurrentIndex(1)
        combo.blockSignals(False)

    # ------------------------------------------------------------------- 동작
    def _browse_chime(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "차임 파일 선택", "", AUDIO_FILTER)
        if path:
            self.chime_edit.setText(path)

    def _preview_segments(self, segments: list[Segment], name: str) -> None:
        self.apply(silent=True)
        self.controller.engine.submit(
            PlayJob(name=name, trigger="미리듣기", source=name, prepare=lambda: segments,
                    interrupt=True)
        )

    def _test_device(self) -> None:
        rate = 44100
        t = np.arange(int(rate * 0.7)) / rate
        tone = (np.sin(2 * np.pi * 660 * t) * 0.35).astype(np.float32)[:, None]
        self._preview_segments(
            [Segment(np.repeat(tone, 2, axis=1), rate, 1.0, 30, 150, "테스트음")],
            "출력 장치 테스트",
        )

    def _test_chime(self) -> None:
        path = self.chime_edit.text().strip() or str(default_chime_path())
        try:
            data, rate = load_audio(path)
        except AudioError as exc:
            QMessageBox.warning(self, "차임 미리듣기", str(exc))
            return
        volume = self.chime_volume.value() / 100.0
        self._preview_segments([Segment(data, rate, volume, 0, 60, "차임")], "차임 미리듣기")

    def _open_data_dir(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(DATA_DIR)))

    # ------------------------------------------------------------- 값 읽고 쓰기
    def load(self) -> None:
        settings = self.controller.settings
        self._seed_combos()          # 실제 목록은 탭을 처음 열 때 불러온다

        self.master_volume.setValue(int(settings.master_volume * 100))
        self.chime_edit.setText(settings.chime_path)
        self.chime_volume.setValue(int(settings.chime_volume * 100))
        self.tray_box.setChecked(settings.minimize_to_tray)
        self.minimized_box.setChecked(settings.start_minimized)
        self.catchup.setValue(settings.catchup_seconds)
        self.retention.setValue(settings.log_retention_days)
        self.duck_box.setChecked(settings.duck_on_emergency)
        self.autostart_box.setChecked(
            autostart.is_enabled() if autostart.supported() else settings.autostart
        )

    def apply(self, silent: bool = False) -> None:
        settings = self.controller.settings
        settings.output_device = self.device_combo.currentData() or ""
        settings.master_volume = self.master_volume.value() / 100.0
        settings.chime_path = self.chime_edit.text().strip()
        settings.chime_volume = self.chime_volume.value() / 100.0
        settings.minimize_to_tray = self.tray_box.isChecked()
        settings.start_minimized = self.minimized_box.isChecked()
        settings.catchup_seconds = self.catchup.value()
        settings.log_retention_days = self.retention.value()
        settings.duck_on_emergency = self.duck_box.isChecked()

        message = ""
        wanted = self.autostart_box.isChecked()
        if autostart.supported() and wanted != autostart.is_enabled():
            ok, message = autostart.set_enabled(wanted)
            if not ok:
                self.autostart_box.setChecked(autostart.is_enabled())
        settings.autostart = self.autostart_box.isChecked()

        self.controller.save_settings()
        if not silent:
            self.controller.toast("설정을 저장했습니다." + (f" {message}" if message else ""))

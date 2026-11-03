"""즉시 방송 탭 — 예약과 무관하게 지금 바로 내보내는 화면."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSlider, QVBoxLayout, QWidget,
)

from ..models import ScheduleItem
from ..scheduler import TRIGGER_MANUAL
from .schedule_dialog import AUDIO_FILTER

_EMERGENCY_STYLE = """
QPushButton {
    background-color: #c0392b; color: white; font-size: 16px; font-weight: bold;
    padding: 14px; border: none; border-radius: 6px;
}
QPushButton:hover { background-color: #d64435; }
QPushButton:pressed { background-color: #9d2f22; }
"""

# 스타일시트를 씌우면 네이티브 테두리가 사라지므로 직접 그려 준다.
_STOP_STYLE = """
QPushButton {
    background-color: #f4f4f4; color: #333333; font-size: 14px; font-weight: 600;
    padding: 12px; border: 1px solid #b8b8b8; border-radius: 6px;
}
QPushButton:hover { background-color: #e9e9e9; }
QPushButton:pressed { background-color: #dadada; }
"""


class BroadcastTab(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller

        root = QVBoxLayout(self)

        source_group = QGroupBox("방송할 내용")
        source_layout = QVBoxLayout(source_group)
        row = QHBoxLayout()
        self.file_edit = QLineEdit()
        self.file_edit.setPlaceholderText("재생할 wav / mp3 파일 경로")
        browse = QPushButton("찾아보기…")
        browse.clicked.connect(self._browse)
        row.addWidget(self.file_edit, 1)
        row.addWidget(browse)
        source_layout.addLayout(row)
        root.addWidget(source_group)

        option_group = QGroupBox("옵션")
        option_layout = QVBoxLayout(option_group)

        volume_row = QHBoxLayout()
        volume_row.addWidget(QLabel("볼륨"))
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 200)
        self.volume.setValue(100)
        self.volume.setTickInterval(25)
        self.volume.setTickPosition(QSlider.TicksBelow)
        self.volume_label = QLabel("100 %")
        self.volume_label.setFixedWidth(52)
        self.volume.valueChanged.connect(lambda v: self.volume_label.setText(f"{v} %"))
        volume_row.addWidget(self.volume, 1)
        volume_row.addWidget(self.volume_label)
        option_layout.addLayout(volume_row)

        self.chime_box = QCheckBox("시작 차임 재생")
        self.chime_box.setChecked(True)
        self.interrupt_box = QCheckBox("진행 중인 방송을 끊고 먼저 내보내기 (긴급)")
        self.interrupt_box.setChecked(True)
        option_layout.addWidget(self.chime_box)
        option_layout.addWidget(self.interrupt_box)
        root.addWidget(option_group)

        button_row = QHBoxLayout()
        self.play_button = QPushButton("지금 방송")
        self.play_button.setStyleSheet(_EMERGENCY_STYLE)
        self.play_button.setMinimumHeight(56)
        self.play_button.clicked.connect(self._broadcast)
        self.stop_button = QPushButton("방송 중지")
        self.stop_button.setStyleSheet(_STOP_STYLE)
        self.stop_button.setMinimumHeight(56)
        self.stop_button.setMaximumWidth(160)
        self.stop_button.clicked.connect(self.controller.stop_everything)
        button_row.addWidget(self.play_button, 1)
        button_row.addWidget(self.stop_button)
        root.addLayout(button_row)

        hint = QLabel(
            "예약 목록에 없는 안내를 바로 내보낼 때 사용합니다. "
            "설정 탭에서 고른 출력 장치로 나갑니다."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#666;")
        root.addWidget(hint)
        root.addStretch(1)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "음성 파일 선택", "", AUDIO_FILTER)
        if path:
            self.file_edit.setText(path)

    def _broadcast(self) -> None:
        item = ScheduleItem(
            name="즉시 방송",
            file_path=self.file_edit.text().strip(),
            volume=self.volume.value() / 100.0,
            fade_in_ms=0,
            fade_out_ms=200,
            play_count=1,
        )
        if not item.file_path:
            QMessageBox.warning(self, "즉시 방송", "재생할 음성 파일을 선택하세요.")
            return
        self.controller.play_item(
            item, TRIGGER_MANUAL,
            interrupt=self.interrupt_box.isChecked(),
            with_chime=self.chime_box.isChecked(),
        )

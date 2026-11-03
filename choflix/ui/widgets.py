"""여러 화면에서 함께 쓰는 작은 위젯과 아이콘 생성기."""
from __future__ import annotations

from PySide6.QtCore import QLocale, QRectF, QSize, Qt, QTime, Signal
from PySide6.QtGui import QBrush, QColor, QIcon, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QPushButton, QTimeEdit, QWidget,
)

from ..models import WEEKDAY_NAMES

ACCENT = "#2f6fdb"
DANGER = "#c0392b"


class WeekdaySelector(QWidget):
    """월~일 체크박스 묶음과 빠른 선택 버튼."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._boxes: list[QCheckBox] = []
        for index, name in enumerate(WEEKDAY_NAMES):
            box = QCheckBox(name)
            box.setToolTip(f"{name}요일")
            if index >= 5:
                box.setStyleSheet(f"color: {DANGER};")
            box.toggled.connect(lambda _=False: self.changed.emit())
            layout.addWidget(box)
            self._boxes.append(box)

        layout.addSpacing(10)
        for label, days in (("평일", [0, 1, 2, 3, 4]), ("주말", [5, 6]), ("매일", list(range(7)))):
            button = QPushButton(label)
            button.setFixedWidth(46)
            button.setToolTip(f"{label} 선택")
            button.clicked.connect(lambda _=False, d=days: self.set_days(d))
            layout.addWidget(button)
        layout.addStretch(1)

    def days(self) -> list[int]:
        return [i for i, box in enumerate(self._boxes) if box.isChecked()]

    def set_days(self, days: list[int]) -> None:
        wanted = set(days)
        for index, box in enumerate(self._boxes):
            box.blockSignals(True)
            box.setChecked(index in wanted)
            box.blockSignals(False)
        self.changed.emit()


BIG_TIME_STYLE = """
QTimeEdit {
    font-size: 20px; font-weight: bold; font-family: 'Consolas', 'D2Coding', monospace;
    padding: 4px 8px; min-height: 34px;
}
"""

class BigTimeEdit(QTimeEdit):
    """방송실에서 멀리서도 읽히도록 크게 키운 시각 입력.

    오전/오후 12시간제로 보여준다. 저장은 계속 24시간제라 예전 예약과
    스케줄 계산은 그대로다.

    화살표가 끝에서 막히지 않고 한 바퀴 돈다. 시는 12에서 더 올리면 1,
    1에서 더 내리면 12로 가고, 분은 59와 00 사이를 순환한다. 오전/오후
    칸도 화살표로 뒤집을 수 있다.
    """

    def __init__(self, initial: QTime | None = None, parent: QWidget | None = None):
        super().__init__(initial or QTime(9, 0), parent)
        self.setLocale(QLocale(QLocale.Korean, QLocale.SouthKorea))
        self.setDisplayFormat("AP h:mm")        # 오전/오후 12시간제 표시
        self.setStyleSheet(BIG_TIME_STYLE)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumWidth(150)
        self.setMaximumWidth(200)   # 폼 안에서 폭 전체로 늘어나지 않게
        self.setButtonSymbols(QTimeEdit.UpDownArrows)
        self.setWrapping(True)      # 끝에서 반대쪽으로 순환
        self.setKeyboardTracking(False)


def app_pixmap(size: int = 256) -> QPixmap:
    """앱 아이콘: Choflix 의 'C' 가 스피커 입처럼 열려 음파를 내보내는 모양.

    글자와 방송을 한 형태로 합쳐, 작은 트레이 크기에서도 실루엣이 살아 있도록
    획을 두껍게 두고 음파는 세 겹만 둔다.
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    s = size / 256.0
    gradient = QLinearGradient(0, 0, size, size)
    gradient.setColorAt(0.0, QColor("#3d7ff0"))
    gradient.setColorAt(1.0, QColor("#1f4fa8"))
    painter.setBrush(QBrush(gradient))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(QRectF(0, 0, size, size), 56 * s, 56 * s)

    # 'C' — 오른쪽이 트인 두꺼운 호. 그 틈이 소리가 나가는 입이 된다.
    cx, cy, radius = 104 * s, 128 * s, 62 * s
    pen = QPen(QColor("#ffffff"))
    pen.setWidthF(30 * s)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawArc(
        QRectF(cx - radius, cy - radius, radius * 2, radius * 2),
        48 * 16, 264 * 16,      # 오른쪽으로 96도 트인 C
    )

    # C 의 입에서 퍼져 나가는 음파. 바깥으로 갈수록 옅게.
    # 트레이 아이콘 크기에서 세 겹은 서로 뭉쳐 덩어리로 보이므로 줄인다.
    if size >= 48:
        waves = ((38, 255), (66, 195), (94, 130))
    elif size >= 24:
        waves = ((40, 255), (76, 175))
    else:
        waves = ((46, 255),)
    for wave_radius, alpha in waves:
        wave = QPen(QColor(255, 255, 255, alpha))
        wave.setWidthF(max(1.4, 15 * s))
        wave.setCapStyle(Qt.RoundCap)
        painter.setPen(wave)
        rect = QRectF(
            (150 - wave_radius) * s, (128 - wave_radius) * s,
            wave_radius * 2 * s, wave_radius * 2 * s,
        )
        painter.drawArc(rect, -42 * 16, 84 * 16)

    painter.end()
    return pixmap


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(app_pixmap(size))
    return icon


def status_dot(color: str, size: int = 12) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor(color))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(1, 1, size - 2, size - 2)
    painter.end()
    return QIcon(pixmap)


def icon_size() -> QSize:
    return QSize(18, 18)

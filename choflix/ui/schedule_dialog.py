"""예약 방송 한 건을 만들고 고치는 대화상자."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QDate, QTime
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from ..audio import AudioError, audio_duration
from ..models import (
    REPEAT_DAILY, REPEAT_INTERVAL, REPEAT_LABELS, REPEAT_ONCE, REPEAT_WEEKLY,
    ScheduleItem, format_datetime_kr,
)
from .widgets import BigTimeEdit, WeekdaySelector

AUDIO_FILTER = "오디오 파일 (*.wav *.mp3 *.ogg *.flac *.aiff *.m4a);;모든 파일 (*.*)"
_REPEAT_ORDER = [REPEAT_ONCE, REPEAT_DAILY, REPEAT_WEEKLY, REPEAT_INTERVAL]


class ScheduleDialog(QDialog):
    def __init__(self, item: ScheduleItem | None, parent=None, on_preview=None):
        super().__init__(parent)
        self.setWindowTitle("예약 방송 편집" if item else "예약 방송 추가")
        self.setMinimumWidth(620)
        self._on_preview = on_preview
        self._item = ScheduleItem.from_dict(item.to_dict()) if item else ScheduleItem()

        root = QVBoxLayout(self)
        root.addWidget(self._build_basic_group())
        root.addWidget(self._build_source_group())
        root.addWidget(self._build_timing_group())
        root.addWidget(self._build_playback_group())

        self.preview_label = QLabel()
        self.preview_label.setWordWrap(True)
        self.preview_label.setStyleSheet("color:#2f6fdb; padding:6px 2px;")
        root.addWidget(self.preview_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("저장")
        buttons.button(QDialogButtonBox.Cancel).setText("취소")
        self.preview_button = QPushButton("미리듣기")
        self.preview_button.clicked.connect(self._preview)
        buttons.addButton(self.preview_button, QDialogButtonBox.ActionRole)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._load(self._item)
        self._refresh_preview()

    # --------------------------------------------------------------- 화면 구성
    def _build_basic_group(self) -> QGroupBox:
        group = QGroupBox("기본")
        form = QFormLayout(group)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("예: 점심시간 안내")
        self.enabled_box = QCheckBox("이 예약 사용")
        form.addRow("이름", self.name_edit)
        form.addRow("", self.enabled_box)
        return group

    def _build_source_group(self) -> QGroupBox:
        group = QGroupBox("방송 내용")
        layout = QVBoxLayout(group)

        row = QHBoxLayout()
        self.file_edit = QLineEdit()
        self.file_edit.setPlaceholderText("재생할 wav / mp3 파일 경로")
        self.file_edit.textChanged.connect(self._update_file_info)
        browse = QPushButton("찾아보기…")
        browse.clicked.connect(self._browse)
        row.addWidget(self.file_edit, 1)
        row.addWidget(browse)
        layout.addLayout(row)

        self.file_info = QLabel(" ")
        self.file_info.setStyleSheet("color:#666;")
        layout.addWidget(self.file_info)
        return group

    def _build_timing_group(self) -> QGroupBox:
        group = QGroupBox("방송 시각")
        layout = QVBoxLayout(group)

        top = QHBoxLayout()
        self.repeat_combo = QComboBox()
        for key in _REPEAT_ORDER:
            self.repeat_combo.addItem(REPEAT_LABELS[key], key)
        self.repeat_combo.currentIndexChanged.connect(self._on_repeat_changed)
        top.addWidget(QLabel("반복 방식"))
        top.addWidget(self.repeat_combo)
        top.addStretch(1)
        layout.addLayout(top)

        self.timing_stack = QStackedWidget()

        once_page = QWidget()
        once_form = QFormLayout(once_page)
        once_form.setContentsMargins(0, 4, 0, 4)
        self.once_date = QDateEdit(QDate.currentDate())
        self.once_date.setCalendarPopup(True)
        self.once_date.setDisplayFormat("yyyy-MM-dd")
        self.once_date.setStyleSheet("font-size:15px; padding:4px; min-height:28px;")
        self.once_date.setMaximumWidth(200)
        self.once_date.dateChanged.connect(self._refresh_preview)
        once_form.addRow("날짜", self.once_date)
        self.timing_stack.addWidget(once_page)

        self.timing_stack.addWidget(QWidget())          # 매일: 날짜 입력이 필요 없다
        self.timing_stack.addWidget(QWidget())          # 요일 반복: 아래 요일 선택으로 충분

        interval_page = QWidget()
        interval_form = QFormLayout(interval_page)
        interval_form.setContentsMargins(0, 4, 0, 4)
        self.interval_start = BigTimeEdit(QTime(9, 0))
        self.interval_start.timeChanged.connect(self._refresh_preview)
        self.interval_end = BigTimeEdit(QTime(18, 0))
        self.interval_end.timeChanged.connect(self._refresh_preview)
        self.interval_minutes = QSpinBox()
        self.interval_minutes.setRange(1, 1440)
        self.interval_minutes.setSuffix(" 분마다")
        self.interval_minutes.setStyleSheet("font-size:15px; padding:4px; min-height:28px;")
        self.interval_minutes.setMaximumWidth(170)
        self.interval_minutes.valueChanged.connect(self._refresh_preview)
        interval_form.addRow("시작 시각", self.interval_start)
        interval_form.addRow("종료 시각", self.interval_end)
        interval_form.addRow("반복 주기", self.interval_minutes)
        self.timing_stack.addWidget(interval_page)

        layout.addWidget(self.timing_stack)

        self.times_row = QWidget()
        times_layout = QHBoxLayout(self.times_row)
        times_layout.setContentsMargins(0, 2, 0, 2)
        times_layout.addWidget(QLabel("방송 시각"))
        self.at_time = BigTimeEdit(QTime(9, 0))
        self.at_time.timeChanged.connect(self._refresh_preview)
        times_layout.addWidget(self.at_time)
        times_layout.addStretch(1)
        layout.addWidget(self.times_row)

        self.weekday_row = QWidget()
        weekday_layout = QHBoxLayout(self.weekday_row)
        weekday_layout.setContentsMargins(0, 0, 0, 0)
        weekday_layout.addWidget(QLabel("요일"))
        self.weekdays = WeekdaySelector()
        self.weekdays.changed.connect(self._refresh_preview)
        weekday_layout.addWidget(self.weekdays, 1)
        layout.addWidget(self.weekday_row)

        range_row = QHBoxLayout()
        self.range_box = QCheckBox("기간 제한")
        self.range_box.toggled.connect(self._on_range_toggled)
        self.start_date = QDateEdit(QDate.currentDate())
        self.start_date.setCalendarPopup(True)
        self.start_date.setDisplayFormat("yyyy-MM-dd")
        self.start_date.dateChanged.connect(self._refresh_preview)
        self.end_date = QDateEdit(QDate.currentDate().addMonths(1))
        self.end_date.setCalendarPopup(True)
        self.end_date.setDisplayFormat("yyyy-MM-dd")
        self.end_date.dateChanged.connect(self._refresh_preview)
        range_row.addWidget(self.range_box)
        range_row.addWidget(self.start_date)
        range_row.addWidget(QLabel("~"))
        range_row.addWidget(self.end_date)
        range_row.addStretch(1)
        layout.addLayout(range_row)
        return group

    def _build_playback_group(self) -> QGroupBox:
        group = QGroupBox("재생 옵션")
        form = QFormLayout(group)

        self.volume_spin = QDoubleSpinBox()
        self.volume_spin.setRange(0, 200)
        self.volume_spin.setSingleStep(5)
        self.volume_spin.setDecimals(0)
        self.volume_spin.setSuffix(" %")
        form.addRow("볼륨", self.volume_spin)

        repeat_row = QHBoxLayout()
        self.play_count = QSpinBox()
        self.play_count.setRange(1, 20)
        self.play_count.setSuffix(" 회")
        self.gap_spin = QSpinBox()
        self.gap_spin.setRange(0, 10000)
        self.gap_spin.setSingleStep(100)
        self.gap_spin.setSuffix(" ms 간격")
        repeat_row.addWidget(self.play_count)
        repeat_row.addWidget(self.gap_spin)
        repeat_row.addStretch(1)
        form.addRow("연속 재생", repeat_row)

        fade_row = QHBoxLayout()
        self.fade_in = QSpinBox()
        self.fade_in.setRange(0, 10000)
        self.fade_in.setSingleStep(100)
        self.fade_in.setPrefix("인 ")
        self.fade_in.setSuffix(" ms")
        self.fade_out = QSpinBox()
        self.fade_out.setRange(0, 10000)
        self.fade_out.setSingleStep(100)
        self.fade_out.setPrefix("아웃 ")
        self.fade_out.setSuffix(" ms")
        fade_row.addWidget(self.fade_in)
        fade_row.addWidget(self.fade_out)
        fade_row.addStretch(1)
        form.addRow("페이드", fade_row)

        return group

    # ------------------------------------------------------------------ 동작
    def _on_repeat_changed(self) -> None:
        repeat = self.repeat_combo.currentData()
        self.timing_stack.setCurrentIndex(_REPEAT_ORDER.index(repeat))
        # QStackedWidget 은 가장 큰 페이지 높이를 유지해서 빈 페이지에서도
        # 큰 여백이 남는다. 현재 페이지 높이에 맞춰 접어 준다.
        page = self.timing_stack.currentWidget()
        hint = page.sizeHint().height() if page else 0
        self.timing_stack.setFixedHeight(max(0, hint))   # 빈 페이지는 sizeHint 가 -1 이다
        self.times_row.setVisible(repeat != REPEAT_INTERVAL)
        self.weekday_row.setVisible(repeat in (REPEAT_WEEKLY, REPEAT_INTERVAL))
        if repeat == REPEAT_INTERVAL:
            self.weekdays.setToolTip("비워 두면 매일 반복합니다.")
        self._refresh_preview()

    def _on_range_toggled(self, checked: bool) -> None:
        self.start_date.setEnabled(checked)
        self.end_date.setEnabled(checked)
        self._refresh_preview()

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "음성 파일 선택", "", AUDIO_FILTER)
        if path:
            self.file_edit.setText(path)

    def _update_file_info(self) -> None:
        path = self.file_edit.text().strip()
        if not path:
            self.file_info.setText(" ")
        else:
            try:
                seconds = audio_duration(path)
                self.file_info.setText(f"길이 {int(seconds // 60)}분 {seconds % 60:.1f}초")
                self.file_info.setStyleSheet("color:#2c7a3f;")
            except AudioError as exc:
                self.file_info.setText(str(exc).splitlines()[0])
                self.file_info.setStyleSheet("color:#c0392b;")
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        item = self._collect()
        ok, message = item.is_valid()
        if not ok:
            self.preview_label.setText(f"⚠ {message}")
            self.preview_label.setStyleSheet("color:#c0392b; padding:6px 2px;")
            return
        upcoming: list[str] = []
        cursor = datetime.now()
        for _ in range(3):
            nxt = item.next_run_at(cursor)
            if not nxt:
                break
            upcoming.append(f"{nxt:%Y-%m-%d} {format_datetime_kr(nxt, with_date=False)}")
            cursor = nxt
        self.preview_label.setStyleSheet("color:#2f6fdb; padding:6px 2px;")
        if upcoming:
            self.preview_label.setText("다음 방송 예정: " + "  →  ".join(upcoming))
        else:
            self.preview_label.setStyleSheet("color:#c0392b; padding:6px 2px;")
            self.preview_label.setText("예정된 방송이 없습니다. 날짜나 기간 설정을 확인하세요.")

    def _preview(self) -> None:
        item = self._collect()
        ok, message = item.is_valid()
        if not ok:
            QMessageBox.warning(self, "미리듣기", message)
            return
        if self._on_preview:
            self._on_preview(item)

    # ------------------------------------------------------------ 값 읽고 쓰기
    def _load(self, item: ScheduleItem) -> None:
        self.name_edit.setText(item.name)
        self.enabled_box.setChecked(item.enabled)

        self.file_edit.setText(item.file_path)

        index = _REPEAT_ORDER.index(item.repeat) if item.repeat in _REPEAT_ORDER else 2
        self.repeat_combo.setCurrentIndex(index)

        at = QTime.fromString(item.at_time, "HH:mm")
        self.at_time.setTime(at if at.isValid() else QTime(9, 0))
        if item.once_date:
            date = QDate.fromString(item.once_date, "yyyy-MM-dd")
            if date.isValid():
                self.once_date.setDate(date)

        start = QTime.fromString(item.interval_start, "HH:mm")
        end = QTime.fromString(item.interval_end, "HH:mm")
        self.interval_start.setTime(start if start.isValid() else QTime(9, 0))
        self.interval_end.setTime(end if end.isValid() else QTime(18, 0))
        self.interval_minutes.setValue(item.interval_minutes)
        self.weekdays.set_days(item.weekdays)

        has_range = bool(item.start_date or item.end_date)
        self.range_box.setChecked(has_range)
        if item.start_date:
            date = QDate.fromString(item.start_date, "yyyy-MM-dd")
            if date.isValid():
                self.start_date.setDate(date)
        if item.end_date:
            date = QDate.fromString(item.end_date, "yyyy-MM-dd")
            if date.isValid():
                self.end_date.setDate(date)
        self._on_range_toggled(has_range)

        self.volume_spin.setValue(item.volume * 100)
        self.play_count.setValue(item.play_count)
        self.gap_spin.setValue(item.gap_ms)
        self.fade_in.setValue(item.fade_in_ms)
        self.fade_out.setValue(item.fade_out_ms)
        self._on_repeat_changed()
        self._update_file_info()

    def _collect(self) -> ScheduleItem:
        item = ScheduleItem.from_dict(self._item.to_dict())
        item.name = self.name_edit.text().strip() or "이름 없는 공지"
        item.enabled = self.enabled_box.isChecked()
        item.file_path = self.file_edit.text().strip()

        repeat = self.repeat_combo.currentData()
        item.repeat = repeat
        item.at_time = self.at_time.time().toString("HH:mm")
        if repeat == REPEAT_ONCE:
            item.once_date = self.once_date.date().toString("yyyy-MM-dd")
        if repeat == REPEAT_INTERVAL:
            item.interval_start = self.interval_start.time().toString("HH:mm")
            item.interval_end = self.interval_end.time().toString("HH:mm")
            item.interval_minutes = self.interval_minutes.value()
        item.weekdays = self.weekdays.days()

        if self.range_box.isChecked():
            item.start_date = self.start_date.date().toString("yyyy-MM-dd")
            item.end_date = self.end_date.date().toString("yyyy-MM-dd")
        else:
            item.start_date = item.end_date = ""

        item.volume = self.volume_spin.value() / 100.0
        item.play_count = self.play_count.value()
        item.gap_ms = self.gap_spin.value()
        item.fade_in_ms = self.fade_in.value()
        item.fade_out_ms = self.fade_out.value()
        item.normalize()        # 중복 제거·정렬을 모델 규칙에 맞춘다
        return item

    def _accept(self) -> None:
        item = self._collect()
        ok, message = item.is_valid()
        if not ok:
            QMessageBox.warning(self, "저장할 수 없습니다", message)
            return
        if self.range_box.isChecked() and self.end_date.date() < self.start_date.date():
            QMessageBox.warning(self, "저장할 수 없습니다", "기간의 종료일이 시작일보다 앞설 수 없습니다.")
            return
        self._item = item
        self.accept()

    def result_item(self) -> ScheduleItem:
        return self._item

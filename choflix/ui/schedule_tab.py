"""예약 방송 목록 탭."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QMenu,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .. import store
from ..audio import format_duration, probe_duration
from ..models import ScheduleItem, format_datetime_kr
from ..scheduler import TRIGGER_MANUAL, TRIGGER_PREVIEW
from .schedule_dialog import ScheduleDialog

_COLUMNS = ["사용", "이름", "방송 시각", "내용", "길이", "볼륨", "다음 방송"]
(_COL_ENABLED, _COL_NAME, _COL_WHEN, _COL_SOURCE,
 _COL_LENGTH, _COL_VOLUME, _COL_NEXT) = range(7)
_DEFAULT_WIDTHS = [46, 170, 190, 280, 64, 60, 200]


def format_next(when: datetime | None) -> tuple[str, str]:
    """다음 방송 시각을 '남은 시간'과 함께 사람이 읽기 좋게."""
    if when is None:
        return "—", "#999999"
    delta = when - datetime.now()
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return f"{format_datetime_kr(when, with_date=False)} (곧)", "#c0392b"
    if seconds < 3600:
        remain = f"{seconds // 60}분 {seconds % 60}초 후"
        color = "#c0392b" if seconds < 300 else "#2f6fdb"
    elif seconds < 86400:
        remain = f"{seconds // 3600}시간 {seconds % 3600 // 60}분 후"
        color = "#2f6fdb"
    else:
        remain = f"{seconds // 86400}일 후"
        color = "#666666"
    return f"{format_datetime_kr(when)} · {remain}", color


class ScheduleTab(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._updating = False

        root = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        for label, slot, tip in (
            ("추가", self.add_item, "새 예약 방송을 만듭니다"),
            ("편집", self.edit_item, "선택한 예약을 수정합니다"),
            ("복제", self.duplicate_item, "선택한 예약을 복사합니다"),
            ("삭제", self.delete_item, "선택한 예약을 지웁니다"),
        ):
            button = QPushButton(label)
            button.setToolTip(tip)
            button.clicked.connect(slot)
            toolbar.addWidget(button)

        toolbar.addSpacing(16)
        play_now = QPushButton("지금 재생")
        play_now.setToolTip("선택한 예약을 예약 시각과 무관하게 지금 내보냅니다")
        play_now.clicked.connect(self.play_selected)
        toolbar.addWidget(play_now)
        toolbar.addStretch(1)

        import_button = QPushButton("가져오기")
        import_button.clicked.connect(self.import_items)
        export_button = QPushButton("내보내기")
        export_button.clicked.connect(self.export_items)
        toolbar.addWidget(import_button)
        toolbar.addWidget(export_button)
        root.addLayout(toolbar)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(self.edit_item)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)

        # 모든 열을 사용자가 끌어서 조절할 수 있게 한다. ResizeToContents 나
        # Stretch 로 두면 Qt 가 폭을 붙들고 있어 드래그가 먹히지 않는다.
        header = self.table.horizontalHeader()
        for column in range(len(_COLUMNS)):
            header.setSectionResizeMode(column, QHeaderView.Interactive)
        header.setStretchLastSection(False)
        header.setSectionsMovable(True)          # 열 순서도 바꿀 수 있게
        header.setMinimumSectionSize(40)
        header.sectionResized.connect(self._on_column_resized)
        header.setContextMenuPolicy(Qt.CustomContextMenu)
        header.customContextMenuRequested.connect(self._header_menu)
        self._apply_column_widths()
        root.addWidget(self.table, 1)

        self.empty_hint = QLabel(
            "등록된 예약이 없습니다. [추가] 를 눌러 첫 공지를 만들어 보세요."
        )
        self.empty_hint.setAlignment(Qt.AlignCenter)
        self.empty_hint.setStyleSheet("color:#888; padding:12px;")
        root.addWidget(self.empty_hint)

        self.refresh()

    # ------------------------------------------------------------------ 열 폭
    def _apply_column_widths(self) -> None:
        """저장된 열 폭을 적용한다. 없으면 기본값."""
        saved = list(getattr(self.controller.settings, "column_widths", []) or [])
        if len(saved) != len(_COLUMNS):
            saved = []          # 열 구성이 바뀌었으면 옛 폭은 자리가 어긋나므로 버린다
        for column in range(len(_COLUMNS)):
            width = saved[column] if column < len(saved) and saved[column] > 0 else _DEFAULT_WIDTHS[column]
            self.table.setColumnWidth(column, width)

    def _on_column_resized(self, *_args) -> None:
        if self._updating:
            return
        self.controller.settings.column_widths = [
            self.table.columnWidth(c) for c in range(len(_COLUMNS))
        ]
        self.controller.save_settings_soon()

    def _header_menu(self, position) -> None:
        menu = QMenu(self)
        menu.addAction("열 폭 기본값으로", self.reset_column_widths)
        menu.addAction("내용에 맞춰 자동 조절", self.fit_columns_to_contents)
        menu.exec(self.table.horizontalHeader().mapToGlobal(position))

    def reset_column_widths(self) -> None:
        for column, width in enumerate(_DEFAULT_WIDTHS):
            self.table.setColumnWidth(column, width)

    def fit_columns_to_contents(self) -> None:
        self.table.resizeColumnsToContents()
        for column in range(len(_COLUMNS)):        # 너무 좁아지지 않게 하한
            if self.table.columnWidth(column) < 50:
                self.table.setColumnWidth(column, 50)

    # ------------------------------------------------------------------ 표시
    def refresh(self) -> None:
        items = self.controller.items
        self._updating = True
        try:
            self.table.setRowCount(len(items))
            for row, item in enumerate(items):
                check = QTableWidgetItem()
                check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                check.setCheckState(Qt.Checked if item.enabled else Qt.Unchecked)
                check.setData(Qt.UserRole, item.id)
                self.table.setItem(row, _COL_ENABLED, check)

                name = QTableWidgetItem(item.name)
                if not item.enabled:
                    name.setForeground(QColor("#999999"))
                font = QFont()
                font.setBold(item.enabled)
                name.setFont(font)
                self.table.setItem(row, _COL_NAME, name)

                self.table.setItem(row, _COL_WHEN, QTableWidgetItem(item.schedule_summary))
                source = QTableWidgetItem(item.source_summary)
                source.setToolTip(item.file_path)
                self.table.setItem(row, _COL_SOURCE, source)

                seconds = probe_duration(item.file_path) if item.file_path else None
                length = QTableWidgetItem(format_duration(seconds) or "—")
                length.setTextAlignment(Qt.AlignCenter)
                if seconds is None:
                    length.setForeground(QColor("#c0392b"))
                    length.setToolTip("파일을 읽을 수 없습니다. 경로를 확인하세요.")
                elif item.play_count > 1:
                    total = seconds * item.play_count + item.gap_ms / 1000 * (item.play_count - 1)
                    length.setText(f"{format_duration(seconds)} ×{item.play_count}")
                    length.setToolTip(f"{item.play_count}회 연속 재생, 전체 {format_duration(total)}")
                self.table.setItem(row, _COL_LENGTH, length)
                self.table.setItem(row, _COL_VOLUME, QTableWidgetItem(f"{item.volume * 100:.0f}%"))
                self.table.setItem(row, _COL_NEXT, QTableWidgetItem())
        finally:
            self._updating = False
        self.empty_hint.setVisible(not items)
        self.refresh_next_column()

    def refresh_next_column(self) -> None:
        """1초마다 '다음 방송' 칸만 다시 그린다."""
        items = self.controller.items
        if self.table.rowCount() != len(items):
            return
        self._updating = True
        try:
            for row, item in enumerate(items):
                when = self.controller.scheduler.next_run_of(item.id) if item.enabled else None
                text, color = format_next(when)
                cell = self.table.item(row, _COL_NEXT)
                if cell is None:
                    cell = QTableWidgetItem()
                    self.table.setItem(row, _COL_NEXT, cell)
                if cell.text() != text:
                    cell.setText(text)
                    cell.setForeground(QColor(color))
        finally:
            self._updating = False

    # ------------------------------------------------------------------ 선택
    def selected_index(self) -> int:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if rows:
            return rows[0].row()
        return self.table.currentRow()

    def selected_item(self) -> ScheduleItem | None:
        index = self.selected_index()
        items = self.controller.items
        if 0 <= index < len(items):
            return items[index]
        return None

    def _require_selection(self, action: str) -> ScheduleItem | None:
        item = self.selected_item()
        if item is None:
            QMessageBox.information(self, action, "목록에서 예약을 먼저 선택하세요.")
        return item

    # ------------------------------------------------------------------ 동작
    def _open_dialog(self, item: ScheduleItem | None) -> ScheduleItem | None:
        dialog = ScheduleDialog(
            item, self,
            on_preview=lambda i: self.controller.play_item(i, TRIGGER_PREVIEW, interrupt=True),
        )
        if dialog.exec() == ScheduleDialog.Accepted:
            return dialog.result_item()
        return None

    def add_item(self) -> None:
        created = self._open_dialog(None)
        if created:
            self.controller.items.append(created)
            self.controller.commit_schedules()
            self.table.selectRow(len(self.controller.items) - 1)

    def edit_item(self) -> None:
        item = self._require_selection("편집")
        if item is None:
            return
        index = self.selected_index()
        updated = self._open_dialog(item)
        if updated:
            self.controller.items[index] = updated
            self.controller.commit_schedules()
            self.table.selectRow(index)

    def duplicate_item(self) -> None:
        item = self._require_selection("복제")
        if item is None:
            return
        copy = ScheduleItem.from_dict(item.to_dict())
        copy.id = ScheduleItem().id
        copy.name = f"{item.name} (복사본)"
        copy.last_fired = ""
        self.controller.items.insert(self.selected_index() + 1, copy)
        self.controller.commit_schedules()

    def delete_item(self) -> None:
        item = self._require_selection("삭제")
        if item is None:
            return
        answer = QMessageBox.question(
            self, "예약 삭제", f"'{item.name}' 예약을 지웁니다. 계속할까요?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        del self.controller.items[self.selected_index()]
        self.controller.commit_schedules()

    def play_selected(self) -> None:
        item = self._require_selection("지금 재생")
        if item is not None:
            self.controller.play_item(item, TRIGGER_MANUAL, interrupt=True)

    def toggle_selected(self) -> None:
        item = self.selected_item()
        if item is None:
            return
        item.enabled = not item.enabled
        self.controller.commit_schedules()

    def _on_item_changed(self, cell: QTableWidgetItem) -> None:
        if self._updating or cell.column() != _COL_ENABLED:
            return
        items = self.controller.items
        row = cell.row()
        if not (0 <= row < len(items)):
            return
        items[row].enabled = cell.checkState() == Qt.Checked
        self.controller.commit_schedules()

    def _context_menu(self, position) -> None:
        if self.selected_item() is None:
            return
        menu = QMenu(self)
        menu.addAction("편집", self.edit_item)
        menu.addAction("복제", self.duplicate_item)
        menu.addAction("사용/중지 전환", self.toggle_selected)
        menu.addSeparator()
        menu.addAction("지금 재생", self.play_selected)
        menu.addSeparator()
        menu.addAction("삭제", self.delete_item)
        menu.exec(self.table.viewport().mapToGlobal(position))

    # -------------------------------------------------------- 가져오기/내보내기
    def export_items(self) -> None:
        if not self.controller.items:
            QMessageBox.information(self, "내보내기", "내보낼 예약이 없습니다.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "예약 내보내기", "공지방송_예약.json", "예약 파일 (*.json)"
        )
        if not path:
            return
        try:
            store.export_schedules(self.controller.items, Path(path))
        except OSError as exc:
            QMessageBox.critical(self, "내보내기 실패", str(exc))
            return
        QMessageBox.information(
            self, "내보내기 완료", f"예약 {len(self.controller.items)}건을 저장했습니다.\n{path}"
        )

    def import_items(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "예약 가져오기", "", "예약 파일 (*.json)")
        if not path:
            return
        try:
            imported = store.import_schedules(Path(path))
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "가져오기 실패", f"파일을 읽지 못했습니다.\n{exc}")
            return
        if not imported:
            QMessageBox.information(self, "가져오기", "파일에 예약이 없습니다.")
            return

        answer = QMessageBox.question(
            self, "예약 가져오기",
            f"예약 {len(imported)}건을 읽었습니다.\n\n"
            "[Yes] 현재 목록에 추가\n[No] 현재 목록을 지우고 대체",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel, QMessageBox.Yes,
        )
        if answer == QMessageBox.Cancel:
            return
        if answer == QMessageBox.No:
            self.controller.items.clear()
        else:
            existing = {i.id for i in self.controller.items}
            for entry in imported:            # 같은 id 가 겹치면 새 id 를 준다
                if entry.id in existing:
                    entry.id = ScheduleItem().id
        self.controller.items.extend(imported)
        self.controller.commit_schedules()
        QMessageBox.information(self, "가져오기 완료", f"예약 {len(imported)}건을 반영했습니다.")

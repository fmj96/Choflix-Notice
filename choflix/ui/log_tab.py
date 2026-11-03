"""재생 기록 탭 — 언제 무엇이 나갔는지, 실패했다면 왜인지."""
from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .. import logbook

_RESULT_COLORS = {
    logbook.RESULT_OK: "#2c7a3f",
    logbook.RESULT_FAIL: "#c0392b",
    logbook.RESULT_SKIP: "#b07d20",
    logbook.RESULT_STOP: "#666666",
}
_COLUMNS = ["시각", "이름", "구분", "소스", "결과", "비고"]
_FILTERS = ["전체", logbook.RESULT_OK, logbook.RESULT_FAIL, logbook.RESULT_SKIP, logbook.RESULT_STOP]


class LogTab(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._records: list[logbook.PlayRecord] = []
        self._stale = False

        root = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        refresh = QPushButton("새로 고침")
        refresh.clicked.connect(self.reload)
        toolbar.addWidget(refresh)

        toolbar.addWidget(QLabel("결과"))
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(_FILTERS)
        self.filter_combo.currentIndexChanged.connect(self._render)
        toolbar.addWidget(self.filter_combo)
        toolbar.addStretch(1)

        export = QPushButton("CSV로 내보내기")
        export.clicked.connect(self._export)
        clear = QPushButton("기록 지우기")
        clear.clicked.connect(self._clear)
        toolbar.addWidget(export)
        toolbar.addWidget(clear)
        root.addLayout(toolbar)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        for column in range(len(_COLUMNS)):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(len(_COLUMNS) - 1, QHeaderView.Stretch)
        root.addWidget(self.table, 1)

        self.summary = QLabel()
        self.summary.setStyleSheet("color:#666;")
        root.addWidget(self.summary)

        self.reload()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._stale:
            self.reload()

    def mark_stale(self) -> None:
        """새 방송 기록이 생겼음을 알린다.

        이 탭을 보고 있으면 바로 다시 그리고, 다른 탭에 있으면 표시만 해 두었다가
        탭을 열 때 갱신한다. 안 보이는 화면을 매번 다시 그릴 이유가 없다.
        """
        self._stale = True
        if self.isVisible():
            self.reload()

    def reload(self) -> None:
        self._records = logbook.read_all()
        self._stale = False
        self._render()

    def _render(self) -> None:
        wanted = self.filter_combo.currentText()
        rows = [r for r in self._records if wanted == "전체" or r.result == wanted]

        self.table.setRowCount(len(rows))
        for row, record in enumerate(rows):
            values = [
                record.time.replace("T", " "),
                record.name,
                record.trigger,
                record.source,
                record.result,
                record.detail,
            ]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if column == 4:
                    cell.setForeground(QColor(_RESULT_COLORS.get(record.result, "#333")))
                if column == 5 and value:
                    cell.setToolTip(value)
                self.table.setItem(row, column, cell)

        failures = sum(1 for r in self._records if r.result == logbook.RESULT_FAIL)
        self.summary.setText(
            f"표시 {len(rows)}건 / 전체 {len(self._records)}건"
            + (f"  ·  실패 {failures}건" if failures else "")
        )

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "재생 기록 내보내기", "재생기록.csv", "CSV 파일 (*.csv)"
        )
        if not path:
            return
        try:
            count = logbook.export_csv(path)
        except OSError as exc:
            QMessageBox.critical(self, "내보내기 실패", str(exc))
            return
        QMessageBox.information(self, "내보내기 완료", f"{count}건을 저장했습니다.\n{path}")

    def _clear(self) -> None:
        answer = QMessageBox.question(
            self, "기록 지우기", "재생 기록을 모두 지웁니다. 계속할까요?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        from ..paths import PLAY_LOG_FILE

        PLAY_LOG_FILE.unlink(missing_ok=True)
        self.reload()

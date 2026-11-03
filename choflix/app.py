"""프로그램 진입점.

    python -m choflix            창을 띄우고 시작
    python -m choflix --tray     트레이로 최소화한 채 시작 (자동 실행용)
"""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import sys

from . import APP_ID, APP_NAME, APP_VERSION
from .paths import APP_LOG_FILE, ensure_dirs

log = logging.getLogger(__name__)


def setup_logging(verbose: bool = False) -> None:
    ensure_dirs()
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    handler = logging.handlers.RotatingFileHandler(
        APP_LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(fmt)
    root.addHandler(handler)

    if sys.stderr:                      # pythonw.exe 로 실행하면 stderr 가 없다
        console = logging.StreamHandler()
        console.setFormatter(fmt)
        root.addHandler(console)


def _single_instance_guard(app_key: str):
    """이미 떠 있는 창이 있으면 그쪽을 깨우고 이 프로세스는 종료한다.

    예약 방송이 두 벌 나가는 사고를 막기 위해 반드시 필요하다.
    """
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtNetwork import QLocalServer, QLocalSocket

    socket = QLocalSocket()
    socket.connectToServer(app_key)
    if socket.waitForConnected(300):
        socket.write(b"show")
        socket.flush()
        socket.waitForBytesWritten(300)
        socket.disconnectFromServer()
        return None

    QLocalServer.removeServer(app_key)          # 비정상 종료 후 남은 소켓 정리
    server = QLocalServer()
    if not server.listen(app_key):
        log.warning("단일 실행 감시 소켓을 열지 못했습니다: %s", server.errorString())
    QCoreApplication.instance()                 # 서버 수명을 앱에 묶기 위해 참조 유지
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="choflix-notice", description=f"{APP_NAME} — 오디오 공지방송 스케줄러")
    parser.add_argument("--tray", action="store_true", help="트레이로 최소화한 채 시작합니다")
    parser.add_argument("--verbose", action="store_true", help="자세한 로그를 남깁니다")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
    args = parser.parse_args(argv)

    setup_logging(args.verbose)
    log.info("%s %s 시작", APP_NAME, APP_VERSION)

    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ID)
    app.setQuitOnLastWindowClosed(False)        # 트레이 상주를 위해

    server = _single_instance_guard(f"{APP_ID}-single-instance")
    if server is None:
        log.info("이미 실행 중이라 기존 창을 활성화하고 종료합니다.")
        return 0

    from .ui.widgets import app_icon
    from .ui.main_window import MainWindow

    app.setWindowIcon(app_icon())
    window = MainWindow()
    server.newConnection.connect(lambda: _handle_wakeup(server, window))

    if args.tray or window.settings.start_minimized:
        if window.tray is None:                 # 트레이가 없으면 그냥 창을 띄운다
            window.show()
        else:
            log.info("트레이로 최소화한 채 시작합니다.")
    else:
        window.show()

    return app.exec()


def _handle_wakeup(server, window) -> None:
    socket = server.nextPendingConnection()
    if socket is None:
        return
    socket.readyRead.connect(socket.readAll)
    socket.disconnected.connect(socket.deleteLater)
    window._restore_window()


if __name__ == "__main__":
    sys.exit(main())

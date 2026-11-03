"""윈도우 시작 시 자동 실행 등록/해제 (HKCU Run 키).

관리자 권한이 필요 없는 현재 사용자 범위만 다룬다. 윈도우가 아니면
모든 함수가 조용히 False 를 돌려주므로 다른 OS 에서도 그대로 돌아간다.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from . import APP_NAME

log = logging.getLogger(__name__)

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "ChoflixNotice"


def supported() -> bool:
    return sys.platform == "win32"


def _command() -> str:
    """자동 실행에 등록할 명령줄. 빌드된 exe 와 소스 실행 모두 처리한다."""
    exe = Path(sys.executable).resolve()
    if getattr(sys, "frozen", False):
        return f'"{exe}" --tray'
    script = Path(sys.argv[0]).resolve()
    pythonw = exe.with_name("pythonw.exe")          # 콘솔 창이 뜨지 않도록
    runner = pythonw if pythonw.exists() else exe
    return f'"{runner}" "{script}" --tray'


def is_enabled() -> bool:
    if not supported():
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, _VALUE_NAME)
            return bool(value)
    except FileNotFoundError:
        return False
    except OSError as exc:
        log.warning("자동 실행 등록 상태를 읽지 못했습니다: %s", exc)
        return False


def set_enabled(enabled: bool) -> tuple[bool, str]:
    """등록/해제 결과와 사용자에게 보여줄 메시지를 돌려준다."""
    if not supported():
        return False, f"자동 실행 등록은 윈도우에서만 지원합니다. ({APP_NAME})"
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, _command())
                return True, "윈도우 시작 시 자동 실행하도록 등록했습니다."
            try:
                winreg.DeleteValue(key, _VALUE_NAME)
            except FileNotFoundError:
                pass
            return True, "자동 실행 등록을 해제했습니다."
    except OSError as exc:
        log.error("자동 실행 설정 실패: %s", exc)
        return False, f"자동 실행 설정을 바꾸지 못했습니다: {exc}"

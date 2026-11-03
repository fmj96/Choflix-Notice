"""소스에서 바로 실행하기.

처음 실행할 때 가상환경과 패키지를 자동으로 준비한 뒤 앱을 띄운다.
배치 파일 인코딩 문제를 피하려고 로직을 여기에 둔다.

    python tools/launch.py            앱 실행
    python tools/launch.py --tray     트레이로 최소화한 채 실행
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV_DIR = ROOT / ".venv"
MIN_PYTHON = (3, 10)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build import (  # noqa: E402
    _make_output_safe, describe_offline, ensure_pip, ensure_venv, install_help,
    pip_install_args, run, say, venv_python, wheels_dir,
)


def gui_python(venv_dir: Path) -> Path:
    """콘솔 창이 뜨지 않는 인터프리터를 고른다."""
    console = venv_python(venv_dir)
    if os.name == "nt":
        windowed = console.with_name("pythonw.exe")
        if windowed.exists():
            return windowed
    return console


def packages_ready(python: Path) -> bool:
    check = "import PySide6, numpy, sounddevice, soundfile"
    return subprocess.call([str(python), "-c", check],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0


def main() -> int:
    _make_output_safe()

    if sys.version_info < MIN_PYTHON:
        say(f"파이썬 {MIN_PYTHON[0]}.{MIN_PYTHON[1]} 이상이 필요합니다. 현재 {sys.version.split()[0]} 입니다.")
        return 1

    python = ensure_venv()
    if python is None:
        say("가상환경을 준비하지 못했습니다.")
        return 1

    if not packages_ready(python):
        if not ensure_pip(python):
            say("가상환경에 pip 을 준비하지 못했습니다. 파이썬을 다시 설치해 보세요.")
            return 1
        say("필요한 패키지를 설치합니다. 처음 한 번만 시간이 걸립니다.")
        offline = wheels_dir()
        describe_offline(offline)
        say("")
        extra = pip_install_args(offline)
        if offline is None:
            run([python, "-m", "pip", "install", "--upgrade", "pip", "--quiet"], "pip 업그레이드")
        if not run([python, "-m", "pip", "install", *extra, "-r", "requirements.txt"],
                   "패키지 설치"):
            say(install_help())
            return 1

    say("프로그램을 시작합니다.")
    command = [str(gui_python(VENV_DIR)), str(ROOT / "run.py"), *sys.argv[1:]]
    try:
        if os.name == "nt":
            # 콘솔 창이 닫혀도 앱이 계속 살아 있도록 분리해서 띄운다.
            subprocess.Popen(command, cwd=str(ROOT), close_fds=True,
                             creationflags=0x00000008 | 0x00000200)
            return 0
        return subprocess.call(command, cwd=str(ROOT))
    except OSError as exc:
        say(f"실행에 실패했습니다: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

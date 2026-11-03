"""윈도우 실행 파일 빌드 스크립트.

배치 파일에 로직을 두면 줄바꿈(CRLF)과 한글 인코딩(CP949/UTF-8) 때문에
쉽게 깨진다. 그래서 build_windows.bat 은 이 스크립트를 부르기만 하고,
실제 작업은 전부 여기서 한다. 표준 라이브러리만 쓰므로 아무 파이썬으로나
바로 실행할 수 있다.

    python tools/build.py              폴더 배포 (권장)
    python tools/build.py --onefile    단일 exe
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV_DIR = ROOT / ".venv"
MIN_PYTHON = (3, 10)
TOTAL_STEPS = 5


def _make_output_safe() -> None:
    """콘솔 코드페이지가 한글을 다 못 담아도 죽지 않게 한다."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


def say(message: str = "") -> None:
    print(message, flush=True)


def step(number: int, message: str) -> None:
    say(f"\n[{number}/{TOTAL_STEPS}] {message}")


def fail(message: str) -> int:
    say("")
    say("=" * 60)
    say(f" 빌드 실패: {message}")
    say("=" * 60)
    return 1


def venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def run(command: list, label: str) -> bool:
    say(f"    > {' '.join(str(c) for c in command)}")
    try:
        code = subprocess.call([str(c) for c in command], cwd=str(ROOT))
    except OSError as exc:
        say(f"    실행할 수 없습니다: {exc}")
        return False
    if code != 0:
        say(f"    {label} 실패 (종료 코드 {code})")
        return False
    return True


def ensure_pip(python: Path) -> bool:
    """가상환경에 pip 이 없는 드문 경우까지 복구한다."""
    if subprocess.call([str(python), "-m", "pip", "--version"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
        return True
    say("    pip 이 없어 설치를 시도합니다...")
    subprocess.call([str(python), "-m", "ensurepip", "--upgrade"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return subprocess.call([str(python), "-m", "pip", "--version"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0


def wheels_dir() -> Path | None:
    """오프라인 설치용 wheel 폴더가 있으면 돌려준다."""
    folder = ROOT / "wheels"
    if folder.is_dir() and any(folder.glob("*.whl")):
        return folder
    return None


def pip_install_args(offline: Path | None) -> list[str]:
    """인터넷이 없으면 로컬 wheel 폴더만 보도록 pip 을 묶는다."""
    if offline is None:
        return []
    return ["--no-index", "--find-links", str(offline)]


def describe_offline(offline: Path | None) -> None:
    if offline is None:
        say("    인터넷에서 내려받습니다.")
        say("    PySide6 등 200MB 가량이라 처음 한 번은 5~10분 걸릴 수 있습니다.")
        return
    count = len(list(offline.glob("*.whl")))
    size = sum(f.stat().st_size for f in offline.glob("*.whl")) / 1024 / 1024
    say(f"    오프라인 모드: wheels 폴더에서 설치합니다 ({count}개, {size:.0f}MB)")
    say("    인터넷에 연결하지 않습니다.")


def install_help() -> str:
    return (
        "패키지 설치에 실패했습니다.\n\n"
        "  자주 있는 원인:\n"
        "   - 인터넷이 끊겼거나 사내 방화벽이 pypi.org 를 막고 있음\n"
        "   - 회사 프록시 사용 중 (환경변수 HTTPS_PROXY 설정 필요)\n"
        "   - 디스크 여유 공간 부족 (최소 1GB 필요)\n"
        "   - 백신이 설치를 차단\n\n"
        "  프록시를 쓰는 환경이라면 명령 프롬프트에서 아래를 먼저 실행하세요:\n"
        "   set HTTPS_PROXY=http://프록시주소:포트\n\n"
        "  인터넷이 아예 안 되는 PC 라면, 인터넷 되는 PC 에서 아래를 실행해\n"
        "  wheels 폴더를 만든 뒤 프로젝트 폴더에 함께 복사하세요:\n"
        "   python tools/make_offline_bundle.py --python-version 314"
    )


def ensure_venv() -> Path | None:
    python = venv_python(VENV_DIR)
    if python.exists():
        say("    기존 가상환경을 사용합니다.")
        return python

    say(f"    가상환경을 만듭니다: {VENV_DIR}")
    try:
        venv.EnvBuilder(with_pip=True, clear=False).create(str(VENV_DIR))
    except Exception as exc:               # noqa: BLE001 - 원인을 그대로 보여준다
        say(f"    가상환경 생성 실패: {exc}")
        return None

    if not python.exists():
        say(f"    가상환경은 만들어졌지만 파이썬을 찾을 수 없습니다: {python}")
        return None
    return python


def main() -> int:
    _make_output_safe()

    parser = argparse.ArgumentParser(description="Choflix Notice 빌드")
    parser.add_argument("--onefile", action="store_true", help="단일 exe 로 만듭니다")
    parser.add_argument("--skip-install", action="store_true", help="패키지 설치를 건너뜁니다")
    args = parser.parse_args()

    onefile = args.onefile or os.environ.get("ONEFILE", "").strip() not in ("", "0", "false", "False")

    say("=" * 60)
    say(" Choflix Notice - 실행 파일 빌드")
    say("=" * 60)
    say(f" 파이썬 : {sys.version.split()[0]} ({sys.executable})")
    say(f" 폴더   : {ROOT}")
    say(f" 방식   : {'단일 exe' if onefile else '폴더 배포'}")

    if sys.version_info < MIN_PYTHON:
        return fail(
            f"파이썬 {MIN_PYTHON[0]}.{MIN_PYTHON[1]} 이상이 필요합니다. "
            f"현재 {sys.version.split()[0]} 입니다."
        )

    step(1, "가상환경 준비")
    python = ensure_venv()
    if python is None:
        return fail("가상환경을 준비하지 못했습니다.")

    step(2, "패키지 설치")
    if args.skip_install:
        say("    --skip-install 이 지정되어 건너뜁니다.")
    else:
        if not ensure_pip(python):
            return fail("가상환경에 pip 을 준비하지 못했습니다. 파이썬을 다시 설치해 보세요.")
        offline = wheels_dir()
        describe_offline(offline)
        say("    (이미 설치돼 있으면 즉시 넘어갑니다)")
        say("")
        extra = pip_install_args(offline)
        if offline is None:
            run([python, "-m", "pip", "install", "--upgrade", "pip", "--quiet"], "pip 업그레이드")
        if not run([python, "-m", "pip", "install", *extra, "-r", "requirements-build.txt"],
                   "패키지 설치"):
            return fail(install_help())

    step(3, "기본 차임과 아이콘 생성")
    for script in ("make_chime.py", "make_icon.py"):
        if not run([python, Path("tools") / script], script):
            return fail(f"{script} 실행에 실패했습니다.")

    step(4, "이전 빌드 정리")
    for folder in ("build", "dist"):
        target = ROOT / folder
        if target.exists():
            say(f"    {folder}/ 삭제")
            shutil.rmtree(target, ignore_errors=True)

    step(5, "PyInstaller 빌드 (몇 분 걸립니다)")
    env_note = " (ONEFILE=1)" if onefile else ""
    say(f"    시작합니다{env_note}...")
    os.environ["ONEFILE"] = "1" if onefile else ""
    if not run([python, "-m", "PyInstaller", "--noconfirm", "--clean", "choflix_notice.spec"], "PyInstaller"):
        return fail("PyInstaller 빌드에 실패했습니다. 위 메시지를 확인하세요.")

    exe_name = "ChoflixNotice.exe" if os.name == "nt" else "ChoflixNotice"
    result = ROOT / "dist" / (exe_name if onefile else "ChoflixNotice")
    say("")
    say("=" * 60)
    say(" 빌드 완료")
    say("=" * 60)
    if onefile:
        say(f" 결과물: {result}")
        say(" 이 파일 하나만 옮기면 됩니다.")
    else:
        say(f" 결과물: {result}{os.sep}{exe_name}")
        say(" 이 폴더를 통째로 옮겨서 사용하세요.")
    say("")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""인터넷이 되는 PC 에서 오프라인 설치용 패키지 꾸러미를 만든다.

공지방송 PC 가 인터넷에 연결되지 않은 경우, 여기서 만든 wheels 폴더를
USB 로 옮기면 build_windows.bat 이 인터넷 없이 설치를 끝낸다.

    python tools/make_offline_bundle.py --python-version 314

주의: wheel 은 파이썬 버전(cp314 등)과 아키텍처(win_amd64)에 묶여 있다.
대상 PC 의 `python --version` 을 확인하고 정확히 맞춰야 한다.

pip 의 --platform 옵션은 wheel 태그만 바꿀 뿐 환경 마커(platform_system 등)는
현재 OS 기준으로 평가한다. 그래서 의존성 해석에 맡기지 않고 필요한 패키지를
여기에 직접 나열한 뒤 --no-deps 로 받는다.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 실행에 필요한 패키지와 그 의존성 (윈도우 기준)
RUNTIME = [
    "PySide6-Essentials",   # QtCore/QtGui/QtWidgets/QtNetwork 포함. Addons 는 불필요
    "shiboken6",
    "numpy",
    "sounddevice",
    "soundfile",
    "cffi",                 # sounddevice, soundfile 이 사용
    "pycparser",            # cffi 의존성
    "typing-extensions",    # soundfile 의존성
]

# exe 빌드에만 필요한 패키지
BUILD = [
    "pyinstaller",
    "pyinstaller-hooks-contrib",
    "altgraph",
    "pefile",
    "pywin32-ctypes",
    "packaging",
    "setuptools",
]


def say(message: str = "") -> None:
    print(message, flush=True)


def download(package: str, dest: Path, python_version: str, platform: str) -> str | None:
    result = subprocess.run(
        [sys.executable, "-m", "pip", "download", package,
         "--dest", str(dest), "--only-binary=:all:", "--no-deps",
         "--platform", platform, "--python-version", python_version],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    for line in (result.stdout or "").splitlines():
        line = line.strip()
        if line.startswith("Saved ") and line.endswith(".whl"):
            return Path(line[6:]).name
        if line.startswith("File was already downloaded"):
            return Path(line.split("downloaded", 1)[1].strip()).name
    # 이미 받아둔 경우 파일명을 직접 찾는다
    stem = package.lower().replace("-", "_")
    for path in dest.glob("*.whl"):
        if path.name.lower().startswith(stem):
            return path.name
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="오프라인 설치용 wheel 꾸러미 생성")
    parser.add_argument("--python-version", default="312",
                        help="대상 PC 파이썬 버전 (예: 312, 313, 314)")
    parser.add_argument("--platform", default="win_amd64",
                        help="대상 플랫폼 (기본 win_amd64, ARM 은 win_arm64)")
    parser.add_argument("--dest", default="wheels", help="저장 폴더 (기본 wheels)")
    parser.add_argument("--runtime-only", action="store_true",
                        help="빌드용 패키지(PyInstaller 등)를 제외합니다")
    args = parser.parse_args()

    dest = (ROOT / args.dest) if not Path(args.dest).is_absolute() else Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)

    packages = list(RUNTIME) + ([] if args.runtime_only else list(BUILD))
    pretty = f"{args.python_version[0]}.{args.python_version[1:]}"

    say("=" * 62)
    say(" 오프라인 설치 꾸러미 만들기")
    say("=" * 62)
    say(f" 대상 파이썬 : {pretty}  (cp{args.python_version})")
    say(f" 대상 플랫폼 : {args.platform}")
    say(f" 저장 위치   : {dest}")
    say(f" 패키지 수   : {len(packages)}개"
        + (" (실행용만)" if args.runtime_only else " (실행용 + 빌드용)"))
    say("")

    downloaded: dict[str, str] = {}
    missing: list[str] = []
    for index, package in enumerate(packages, 1):
        name = download(package, dest, args.python_version, args.platform)
        if name:
            downloaded[package] = name
            say(f"  [{index:2}/{len(packages)}] OK   {package:<28} {name}")
        else:
            missing.append(package)
            say(f"  [{index:2}/{len(packages)}] 실패 {package:<28} wheel 을 찾지 못했습니다")

    manifest = {
        "created": datetime.now().isoformat(timespec="seconds"),
        "python_version": args.python_version,
        "platform": args.platform,
        "runtime_only": args.runtime_only,
        "packages": downloaded,
    }
    (dest / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    total = sum(p.stat().st_size for p in dest.glob("*.whl"))
    say("")
    say("=" * 62)
    if missing:
        say(f" 완료 (실패 {len(missing)}개): {', '.join(missing)}")
        say("")
        say(" 실패한 패키지는 해당 파이썬 버전용 wheel 이 아직 없을 수 있습니다.")
        say(" 대상 PC 의 파이썬 버전을 낮추는 편이 안전합니다.")
    else:
        say(" 완료 — 모든 패키지를 받았습니다.")
    say("")
    say(f" wheel {len(list(dest.glob('*.whl')))}개 / {total / 1024 / 1024:.0f} MB")
    say("")
    say(" 다음 단계:")
    say(f"   1. '{dest.name}' 폴더를 프로젝트 폴더 안에 둔 채로 통째로 USB 에 복사")
    say("   2. 오프라인 PC 에서 build_windows.bat 실행")
    say("      (wheels 폴더가 있으면 인터넷 없이 자동으로 여기서 설치합니다)")
    say("=" * 62)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())

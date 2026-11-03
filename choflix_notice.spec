# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 빌드 설정.

    pyinstaller --noconfirm --clean choflix_notice.spec

기본은 폴더 배포(onedir)다. 부팅 자동 실행과 함께 쓸 때 시작이 빠르고
백신 오탐도 적다. 단일 exe 가 필요하면 환경변수를 주고 빌드한다.

    set ONEFILE=1  &&  pyinstaller --noconfirm --clean choflix_notice.spec
"""
import os
from pathlib import Path

APP_NAME = "ChoflixNotice"
ONEFILE = os.environ.get("ONEFILE", "").strip() not in ("", "0", "false", "False")

root = Path(SPECPATH)
icon_file = root / "assets" / "icon.ico"


def _app_version() -> str:
    """choflix/__init__.py 의 APP_VERSION 을 읽는다 (import 없이)."""
    text = (root / "choflix" / "__init__.py").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("APP_VERSION"):
            return line.split("=", 1)[1].strip().strip('"\'')
    return "0.0.0"


def _write_version_resource() -> str | None:
    """윈도우 exe 의 '파일 속성 > 자세히' 에 들어갈 버전 정보를 만든다.

    GUI 로 빌드하면(console=False) exe 에 stdout 이 없어 --version 으로
    버전을 확인할 수 없다. 그래서 PE 리소스에 심어 두고 그걸로 확인한다.
    """
    if os.name != "nt":
        return None
    version = _app_version()
    parts = (version.split(".") + ["0", "0", "0", "0"])[:4]
    nums = ", ".join(str(int(x) if x.isdigit() else 0) for x in parts)
    out_dir = root / "build"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "version_info.txt"
    target.write_text(
        "VSVersionInfo(\n"
        f"  ffi=FixedFileInfo(filevers=({nums}), prodvers=({nums}),\n"
        "    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),\n"
        "  kids=[\n"
        "    StringFileInfo([StringTable('041204B0', [\n"
        "      StringStruct('CompanyName', 'fmj96'),\n"
        "      StringStruct('FileDescription', 'Choflix Notice - audio notice scheduler'),\n"
        f"      StringStruct('FileVersion', '{version}'),\n"
        "      StringStruct('InternalName', 'ChoflixNotice'),\n"
        "      StringStruct('LegalCopyright', '(c) 2026 fmj96'),\n"
        "      StringStruct('OriginalFilename', 'ChoflixNotice.exe'),\n"
        "      StringStruct('ProductName', 'Choflix Notice'),\n"
        f"      StringStruct('ProductVersion', '{version}'),\n"
        "    ])]),\n"
        "    VarFileInfo([VarStruct('Translation', [0x0412, 1200])]),\n"
        "  ],\n"
        ")\n",
        encoding="utf-8",
    )
    return str(target)


version_file = _write_version_resource()

datas = [
    (str(root / "assets" / "chime.wav"), "assets"),
    (str(root / "assets" / "icon.ico"), "assets"),
]

hiddenimports = [
    "soundfile",
    "sounddevice",
]

# 쓰지 않는 Qt 모듈과 무거운 라이브러리를 빼서 배포 크기를 줄인다.
excludes = [
    "tkinter", "matplotlib", "pandas", "scipy", "PIL", "IPython", "pytest",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQml", "PySide6.Qt3DCore",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtBluetooth", "PySide6.QtPositioning",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
]

a = Analysis(
    ["run.py"],
    pathex=[str(root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe_kwargs = dict(
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                  # 콘솔 창 없이 GUI 로만 실행
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_file) if icon_file.exists() else None,
    version=version_file,
)

if ONEFILE:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], upx_exclude=[],
              runtime_tmpdir=None, **exe_kwargs)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **exe_kwargs)
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False,
                   upx_exclude=[], name=APP_NAME)

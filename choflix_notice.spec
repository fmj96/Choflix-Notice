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
)

if ONEFILE:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], upx_exclude=[],
              runtime_tmpdir=None, **exe_kwargs)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **exe_kwargs)
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False,
                   upx_exclude=[], name=APP_NAME)

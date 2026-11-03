"""앱 아이콘(assets/icon.ico) 생성 스크립트.

아이콘 모양은 choflix/ui/widgets.py 의 app_pixmap() 이 코드로 그린다.
여기서는 그 결과를 여러 크기로 렌더링해 윈도우용 .ico 로 묶는다.
    python tools/make_icon.py
"""
from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray            # noqa: E402
from PySide6.QtWidgets import QApplication                # noqa: E402

from choflix.ui.widgets import app_pixmap                  # noqa: E402

SIZES = [16, 24, 32, 48, 64, 128, 256]


def png_bytes(size: int) -> bytes:
    store = QByteArray()                # QBuffer 가 참조하므로 살려 둬야 한다
    buffer = QBuffer(store)
    buffer.open(QBuffer.WriteOnly)
    app_pixmap(size).toImage().save(buffer, "PNG")
    buffer.close()
    return bytes(store)


def build_ico(images: list[tuple[int, bytes]]) -> bytes:
    """PNG 들을 ICO 컨테이너로 묶는다 (Vista 이후 형식)."""
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries, payload = b"", b""
    for size, data in images:
        entries += struct.pack(
            "<BBBBHHII",
            size if size < 256 else 0, size if size < 256 else 0,
            0, 0, 1, 32, len(data), offset,
        )
        payload += data
        offset += len(data)
    return header + entries + payload


def main() -> int:
    QApplication([])
    images = [(size, png_bytes(size)) for size in SIZES]

    assets = Path(__file__).resolve().parent.parent / "assets"
    assets.mkdir(parents=True, exist_ok=True)

    ico = assets / "icon.ico"
    ico.write_bytes(build_ico(images))
    (assets / "icon.png").write_bytes(dict(images)[256])

    print(f"생성 완료: {ico} ({ico.stat().st_size / 1024:.1f} KB, {len(SIZES)}개 크기)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

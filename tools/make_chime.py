"""기본 차임(딩-동) WAV 생성 스크립트.

assets/chime.wav 를 다시 만들고 싶을 때만 실행한다.
    python tools/make_chime.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import soundfile as sf

RATE = 44100
NOTES = [(783.99, 0.0), (523.25, 0.45)]     # G5 → C5, 학교 종소리와 비슷한 음정
DURATION = 1.6


def _make_output_safe() -> None:
    """콘솔 코드페이지가 한글을 못 담아도 죽지 않게 한다.

    영문 윈도우(cp1252)나 CI 러너에서 한글을 그대로 print 하면
    UnicodeEncodeError 로 멈춘다. 깨져 보이더라도 작업은 끝나야 한다.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass

def bell(freq: float, start: float, length: float = 1.1) -> np.ndarray:
    """감쇠하는 배음 몇 개를 겹쳐 종소리 비슷한 음색을 만든다."""
    n = int(RATE * length)
    t = np.arange(n) / RATE
    envelope = np.exp(-t * 3.2) * (1 - np.exp(-t * 260))
    wave = (
        np.sin(2 * np.pi * freq * t)
        + 0.45 * np.sin(2 * np.pi * freq * 2 * t) * np.exp(-t * 5.0)
        + 0.20 * np.sin(2 * np.pi * freq * 3 * t) * np.exp(-t * 7.5)
    )
    tone = wave * envelope
    out = np.zeros(int(RATE * DURATION), dtype=np.float64)
    offset = int(RATE * start)
    end = min(len(out), offset + n)
    out[offset:end] += tone[: end - offset]
    return out


def main() -> int:
    _make_output_safe()
    mix = sum(bell(freq, start) for freq, start in NOTES)
    mix /= np.max(np.abs(mix)) or 1.0
    mix *= 0.85
    mix[-int(RATE * 0.05):] *= np.linspace(1, 0, int(RATE * 0.05))   # 꼬리 페이드
    stereo = np.column_stack([mix, mix]).astype(np.float32)

    target = Path(__file__).resolve().parent.parent / "assets" / "chime.wav"
    target.parent.mkdir(parents=True, exist_ok=True)
    sf.write(target, stereo, RATE, subtype="PCM_16")
    print(f"생성 완료: {target} ({target.stat().st_size / 1024:.1f} KB, {DURATION}초)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

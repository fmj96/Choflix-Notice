"""설치 진단 도구.

방송용 PC 에 설치한 뒤 "소리가 안 나와요" 를 빠르게 좁히기 위한 점검표다.

    python tools/selftest.py            점검만
    python tools/selftest.py --play     선택한 장치로 실제 소리까지 내본다
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OK, WARN, FAIL = "  [정상]", "  [주의]", "  [실패]"
_failures = 0
_warnings = 0


def section(title: str) -> None:
    print(f"\n── {title} " + "─" * max(0, 52 - len(title)))


def ok(message: str) -> None:
    print(f"{OK} {message}")


def warn(message: str) -> None:
    global _warnings
    _warnings += 1
    print(f"{WARN} {message}")


def fail(message: str) -> None:
    global _failures
    _failures += 1
    print(f"{FAIL} {message}")


def check_packages() -> bool:
    section("필수 패키지")
    all_ok = True
    for module, label in (
        ("numpy", "numpy"), ("sounddevice", "sounddevice"), ("soundfile", "soundfile"),
        ("PySide6", "PySide6"),
    ):
        try:
            mod = __import__(module)
            ok(f"{label} {getattr(mod, '__version__', '')}")
        except Exception as exc:
            fail(f"{label} 없음 — pip install -r requirements.txt 를 실행하세요. ({exc})")
            all_ok = False
    return all_ok


def check_devices() -> None:
    section("출력 장치")
    from choflix.audio import AudioError, list_output_devices

    try:
        devices = list_output_devices()
    except AudioError as exc:
        fail(str(exc))
        return
    if not devices:
        fail("출력 가능한 오디오 장치가 없습니다. 사운드카드 연결과 드라이버를 확인하세요.")
        return
    for device in devices:
        mark = " ★ 시스템 기본" if device.is_default else ""
        ok(f"[{device.index}] {device.label} — {device.channels}채널{mark}")


def check_paths() -> None:
    section("저장 폴더")
    from choflix.paths import DATA_DIR, default_chime_path, ensure_dirs

    try:
        ensure_dirs()
        probe = DATA_DIR / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        ok(f"쓰기 가능: {DATA_DIR}")
    except OSError as exc:
        fail(f"설정 폴더에 쓸 수 없습니다: {DATA_DIR} ({exc})")

    chime = default_chime_path()
    if chime.exists():
        ok(f"기본 차임: {chime} ({chime.stat().st_size / 1024:.0f} KB)")
    else:
        warn(f"기본 차임이 없습니다: {chime} — python tools/make_chime.py 로 만드세요.")


def check_decode() -> None:
    section("오디오 디코딩")
    from choflix.audio import AudioError, load_audio
    from choflix.paths import default_chime_path

    chime = default_chime_path()
    if not chime.exists():
        warn("기본 차임이 없어 디코딩 점검을 건너뜁니다.")
        return
    try:
        data, rate = load_audio(chime)
        ok(f"WAV 디코딩 — {len(data) / rate:.2f}초, {rate}Hz, {data.shape[1]}채널")
    except AudioError as exc:
        fail(f"WAV 디코딩 실패: {exc}")

    try:
        import soundfile as sf

        formats = sf.available_formats()
        if "MP3" in formats:
            ok(f"MP3 지원 (libsndfile {sf.__libsndfile_version__})")
        else:
            warn(
                f"libsndfile {sf.__libsndfile_version__} 은 MP3 를 못 읽습니다. "
                "WAV 를 쓰거나 soundfile 을 최신으로 올리세요."
            )
    except Exception as exc:
        warn(f"지원 형식을 확인하지 못했습니다: {exc}")


def check_schedules() -> None:
    section("등록된 예약")
    from choflix import store

    items = store.load_schedules()
    if not items:
        print("       (등록된 예약이 없습니다)")
        return
    now = datetime.now()
    for item in items:
        valid, message = item.is_valid()
        nxt = item.next_run_at(now)
        if not item.enabled:
            print(f"       [중지] {item.name} — {item.schedule_summary}")
        elif not valid:
            fail(f"{item.name} — {message}")
        elif nxt is None:
            warn(f"{item.name} — 예정된 방송이 없습니다 ({item.schedule_summary})")
        else:
            ok(f"{item.name} — 다음 {nxt:%Y-%m-%d %H:%M} ({item.schedule_summary})")


def play_test() -> None:
    section("실제 재생 테스트")
    import time

    from choflix.audio import PlaybackEngine, PlayJob, Segment, load_audio
    from choflix.paths import default_chime_path
    from choflix.store import load_settings

    settings = load_settings()
    print(f"       설정된 출력 장치: {settings.output_device or '시스템 기본 장치'}")
    try:
        data, rate = load_audio(default_chime_path())
    except Exception as exc:
        fail(f"차임을 읽지 못했습니다: {exc}")
        return

    engine = PlaybackEngine(lambda: settings)
    result: list[tuple[str, str]] = []
    engine.on_finished = lambda job, res, detail: result.append((res, detail))
    engine.start()
    engine.submit(PlayJob(name="자가진단", prepare=lambda: [Segment(data, rate, 1.0, 0, 80, "차임")]))
    deadline = time.time() + 20
    while not result and time.time() < deadline:
        time.sleep(0.1)
    engine.shutdown()

    if not result:
        fail("재생이 끝나지 않았습니다 (장치 응답 없음).")
    elif result[0][0] == "성공":
        ok("차임을 재생했습니다. 스피커에서 소리가 났는지 확인하세요.")
    else:
        fail(f"재생 실패: {result[0][1]}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Choflix Notice 설치 진단")
    parser.add_argument("--play", action="store_true", help="실제로 차임을 재생해 봅니다")
    args = parser.parse_args()

    print("=" * 60)
    print(" Choflix Notice 설치 진단")
    print("=" * 60)

    if not check_packages():
        print("\n필수 패키지가 없어 나머지 점검을 건너뜁니다.")
        return 1

    check_paths()
    check_devices()
    check_decode()
    check_schedules()
    if args.play:
        play_test()

    print("\n" + "=" * 60)
    if _failures:
        print(f" 결과: 실패 {_failures}건, 주의 {_warnings}건 — 위 [실패] 항목을 해결하세요.")
    elif _warnings:
        print(f" 결과: 이상 없음 (주의 {_warnings}건)")
    else:
        print(" 결과: 모두 정상")
    print("=" * 60)
    return 1 if _failures else 0


if __name__ == "__main__":
    sys.exit(main())

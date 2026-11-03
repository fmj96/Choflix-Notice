"""오디오 장치 조회, 파일 디코딩, 재생 엔진.

재생은 전용 워커 스레드 한 개가 큐를 소비하는 구조다. 예약 두 건이 같은
시각에 겹쳐도 서로 잘리지 않고 순서대로 나가고, 긴급방송은 진행 중인
방송을 끊고 먼저 나간다.
"""
from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

log = logging.getLogger(__name__)

BLOCK_FRAMES = 1024
STOP_FADE_MS = 120          # 중지 시 딸깍 소리를 막기 위한 짧은 페이드
_PROGRESS_EVERY_BLOCKS = 4  # 약 90ms 마다 진행 상황 보고 (1024프레임/블록)
PRIORITY_NORMAL = 50
PRIORITY_EMERGENCY = 0      # 숫자가 작을수록 먼저

_audio_cache: dict[tuple[str, float], tuple[np.ndarray, int]] = {}
_CACHE_LIMIT = 8
_CACHE_MAX_FRAMES = 60 * 60 * 48000     # 1시간 넘는 파일은 캐시하지 않는다


class AudioError(Exception):
    """재생 계열 오류. 사용자에게 그대로 보여줄 한글 메시지를 담는다."""


# --------------------------------------------------------------------- 장치
@dataclass(frozen=True)
class DeviceInfo:
    index: int
    name: str
    hostapi: str
    channels: int
    is_default: bool

    @property
    def label(self) -> str:
        return f"{self.name} ({self.hostapi})"


def _sd():
    try:
        import sounddevice
    except Exception as exc:                       # pragma: no cover - 설치 문제
        raise AudioError(
            "오디오 모듈(sounddevice)을 불러오지 못했습니다. 설치를 확인하세요.\n" f"{exc}"
        ) from exc
    return sounddevice


def list_output_devices() -> list[DeviceInfo]:
    """출력 채널이 있는 장치만 추려서 돌려준다."""
    sd = _sd()
    try:
        devices = sd.query_devices()
        hostapis = sd.query_hostapis()
        default_out = sd.default.device[1]
    except Exception as exc:
        raise AudioError(f"오디오 장치 목록을 읽지 못했습니다: {exc}") from exc

    out: list[DeviceInfo] = []
    for idx, dev in enumerate(devices):
        if dev.get("max_output_channels", 0) < 1:
            continue
        api = hostapis[dev["hostapi"]]["name"] if dev.get("hostapi") is not None else "?"
        out.append(
            DeviceInfo(idx, dev["name"], api, dev["max_output_channels"], idx == default_out)
        )
    return out


def resolve_device(label: str | None) -> int | None:
    """설정에 저장된 장치 이름을 현재 장치 인덱스로 바꾼다.

    장치를 못 찾으면 None(시스템 기본 장치)을 돌려준다. USB 사운드카드를
    뽑았을 때 프로그램이 죽는 대신 기본 장치로 계속 방송하기 위해서다.
    """
    if not label:
        return None
    try:
        devices = list_output_devices()
    except AudioError:
        return None
    for dev in devices:
        if dev.label == label:
            return dev.index
    for dev in devices:                     # 호스트 API 표기가 바뀐 경우 이름만으로 재시도
        if dev.name == label or label.startswith(dev.name):
            return dev.index
    log.warning("출력 장치 '%s' 를 찾지 못해 시스템 기본 장치를 사용합니다.", label)
    return None


def device_display_name(index: int | None) -> str:
    if index is None:
        return "시스템 기본 장치"
    try:
        for dev in list_output_devices():
            if dev.index == index:
                return dev.label
    except AudioError:
        pass
    return f"장치 #{index}"


# ------------------------------------------------------------------- 디코딩
def load_audio(path: str | Path) -> tuple[np.ndarray, int]:
    """오디오 파일을 (frames, channels) float32 배열과 샘플레이트로 읽는다."""
    p = Path(path)
    if not p.exists():
        raise AudioError(f"파일을 찾을 수 없습니다: {p}")

    key = (str(p.resolve()), p.stat().st_mtime)
    hit = _audio_cache.get(key)
    if hit is not None:
        return hit

    data: np.ndarray | None = None
    samplerate = 0
    first_error = ""
    try:
        import soundfile as sf

        data, samplerate = sf.read(str(p), dtype="float32", always_2d=True)
    except Exception as exc:
        first_error = str(exc)
        try:                                        # libsndfile 이 못 읽는 코덱 대비
            import miniaudio

            decoded = miniaudio.decode_file(str(p), output_format=miniaudio.SampleFormat.FLOAT32)
            samplerate = decoded.sample_rate
            data = np.asarray(decoded.samples, dtype=np.float32).reshape(-1, decoded.nchannels)
        except ImportError:
            data = None
        except Exception as exc2:
            log.debug("miniaudio 디코딩도 실패: %s", exc2)
            data = None

    if data is None or samplerate <= 0:
        raise AudioError(
            f"'{p.name}' 을(를) 재생할 수 없는 형식입니다.\n"
            f"WAV / FLAC / OGG / MP3 파일을 사용하세요.\n(원인: {first_error})"
        )

    if data.ndim == 1:
        data = data[:, None]
    data = np.ascontiguousarray(data, dtype=np.float32)

    if len(data) <= _CACHE_MAX_FRAMES:
        if len(_audio_cache) >= _CACHE_LIMIT:
            _audio_cache.pop(next(iter(_audio_cache)))
        _audio_cache[key] = (data, samplerate)
    return data, samplerate


def audio_duration(path: str | Path) -> float:
    data, sr = load_audio(path)
    return len(data) / float(sr)


_duration_cache: dict[tuple[str, float], float | None] = {}


def probe_duration(path: str | Path) -> float | None:
    """파일 길이(초)만 빠르게 본다. 못 읽으면 None.

    목록을 그릴 때마다 파일마다 불리므로 전체 디코딩은 하지 않는다.
    libsndfile 은 헤더만 읽어 길이를 알려주고, 그마저 안 되는 형식은
    한 번만 디코딩해 보고 결과를 캐시한다.
    """
    p = Path(path)
    try:
        key = (str(p.resolve()), p.stat().st_mtime)
    except OSError:
        return None
    if key in _duration_cache:
        return _duration_cache[key]

    seconds: float | None = None
    try:
        import soundfile as sf

        info = sf.info(str(p))
        if info.samplerate:
            seconds = info.frames / float(info.samplerate)
    except Exception:
        try:
            seconds = audio_duration(p)
        except AudioError:
            seconds = None

    if len(_duration_cache) > 512:
        _duration_cache.clear()
    _duration_cache[key] = seconds
    return seconds


def format_duration(seconds: float | None) -> str:
    """0:08 / 1:23:45 형태로. 값이 없으면 빈 문자열."""
    if seconds is None or seconds < 0:
        return ""
    total = int(round(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _resample(data: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """선형 보간 리샘플. 장치가 원본 샘플레이트를 거부할 때만 쓴다."""
    if src_rate == dst_rate or len(data) == 0:
        return data
    ratio = dst_rate / float(src_rate)
    new_len = max(1, int(round(len(data) * ratio)))
    src_idx = np.linspace(0, len(data) - 1, num=new_len, dtype=np.float64)
    base = np.arange(len(data), dtype=np.float64)
    out = np.empty((new_len, data.shape[1]), dtype=np.float32)
    for ch in range(data.shape[1]):
        out[:, ch] = np.interp(src_idx, base, data[:, ch]).astype(np.float32)
    return out


def _adapt_channels(block: np.ndarray, out_ch: int) -> np.ndarray:
    in_ch = block.shape[1]
    if in_ch == out_ch:
        return block
    if in_ch == 1:
        return np.repeat(block, out_ch, axis=1)
    if out_ch == 1:
        return block.mean(axis=1, keepdims=True)
    if in_ch > out_ch:
        return block[:, :out_ch]
    pad = np.zeros((len(block), out_ch - in_ch), dtype=np.float32)
    return np.hstack([block, pad])


# --------------------------------------------------------------------- 재생
@dataclass
class Segment:
    """연속 재생할 오디오 한 토막."""

    data: np.ndarray
    samplerate: int
    volume: float = 1.0
    fade_in_ms: int = 0
    fade_out_ms: int = 0
    label: str = ""


@dataclass(order=True)
class PlayJob:
    """재생 큐에 들어가는 작업 단위."""

    priority: int = field(default=PRIORITY_NORMAL, compare=True)
    sequence: int = field(default=0, compare=True)
    name: str = field(default="", compare=False)
    trigger: str = field(default="예약", compare=False)
    source: str = field(default="", compare=False)
    prepare: Callable[[], list[Segment]] | None = field(default=None, compare=False)
    interrupt: bool = field(default=False, compare=False)


class PlaybackEngine:
    """재생 큐를 소비하는 워커. 모든 공개 메서드는 스레드 안전하다."""

    def __init__(self, settings_provider: Callable[[], object]):
        self._settings = settings_provider
        self._queue: queue.PriorityQueue[PlayJob | None] = queue.PriorityQueue()
        self._seq = 0
        self._seq_lock = threading.Lock()
        self._stop_current = threading.Event()
        self._shutdown = threading.Event()
        self._current: PlayJob | None = None
        self._thread = threading.Thread(target=self._run, name="playback", daemon=True)

        # UI 가 붙이는 콜백. 워커 스레드에서 호출되므로 시그널로 넘겨야 한다.
        self.on_state: Callable[[str], None] | None = None
        self.on_finished: Callable[[PlayJob, str, str], None] | None = None
        self.on_progress: Callable[[float, float], None] | None = None

    def start(self) -> None:
        self._thread.start()

    def shutdown(self) -> None:
        self._shutdown.set()
        self._stop_current.set()
        self._queue.put(None)
        if self._thread.is_alive():
            self._thread.join(timeout=3.0)

    # ------------------------------------------------------------ 큐 조작
    def submit(self, job: PlayJob) -> None:
        with self._seq_lock:
            self._seq += 1
            job.sequence = self._seq
        if job.interrupt:
            self.clear_queue()
            self.stop_current()
        self._queue.put(job)

    def stop_current(self) -> None:
        self._stop_current.set()

    def clear_queue(self) -> None:
        while True:
            try:
                item = self._queue.get_nowait()
                self._queue.task_done()
                if item is None:
                    self._queue.put(None)
                    break
            except queue.Empty:
                break

    def stop_all(self) -> None:
        self.clear_queue()
        self.stop_current()

    @property
    def is_playing(self) -> bool:
        return self._current is not None

    @property
    def current_name(self) -> str:
        job = self._current
        return job.name if job else ""

    def queue_size(self) -> int:
        return self._queue.qsize()

    # ---------------------------------------------------------------- 내부
    def _emit_state(self, text: str) -> None:
        if self.on_state:
            try:
                self.on_state(text)
            except Exception:                       # UI 오류가 재생을 막지 않게
                log.exception("상태 콜백 오류")

    def _emit_progress(self, position: float, total: float) -> None:
        if self.on_progress:
            try:
                self.on_progress(position, total)
            except Exception:
                log.exception("진행 콜백 오류")

    def _emit_finished(self, job: PlayJob, result: str, detail: str) -> None:
        if self.on_finished:
            try:
                self.on_finished(job, result, detail)
            except Exception:
                log.exception("완료 콜백 오류")

    def _run(self) -> None:
        while not self._shutdown.is_set():
            job = self._queue.get()
            if job is None:
                self._queue.task_done()
                break
            self._current = job
            self._stop_current.clear()
            result, detail = "성공", ""
            try:
                self._emit_state(f"준비 중: {job.name}")
                segments = job.prepare() if job.prepare else []
                if not segments:
                    raise AudioError("재생할 내용이 없습니다.")
                self._emit_state(f"방송 중: {job.name}")
                stopped = self._play_segments(segments)
                if stopped:
                    result, detail = "중지됨", "사용자 중지 또는 긴급방송"
            except AudioError as exc:
                result, detail = "실패", str(exc)
                log.error("방송 실패 [%s]: %s", job.name, exc)
            except Exception as exc:                # noqa: BLE001 - 워커가 죽으면 안 된다
                result, detail = "실패", f"{type(exc).__name__}: {exc}"
                log.exception("방송 중 예상치 못한 오류 [%s]", job.name)
            finally:
                self._current = None
                self._queue.task_done()
                self._emit_progress(0.0, 0.0)
                self._emit_finished(job, result, detail)
                self._emit_state("대기 중")

    def _play_segments(self, segments: list[Segment]) -> bool:
        """작업 하나를 스트림 하나로 이어 재생. 중간에 중지되면 True.

        세그먼트마다 스트림을 열면 장치를 여닫는 데만 수백 ms 가 들어
        차임과 공지 사이가 벌어진다. 그래서 샘플레이트를 한 번 정해 두고
        모든 세그먼트를 거기에 맞춘 뒤 스트림 하나로 흘려보낸다.
        """
        sd = _sd()
        settings = self._settings()
        device = resolve_device(getattr(settings, "output_device", ""))
        master = float(getattr(settings, "master_volume", 1.0))

        try:
            info = sd.query_devices(device if device is not None else sd.default.device[1])
            max_ch = int(info.get("max_output_channels", 2)) or 2
            device_rate = int(info.get("default_samplerate", 44100)) or 44100
        except Exception as exc:
            raise AudioError(f"출력 장치 정보를 읽을 수 없습니다: {exc}") from exc

        out_ch = 2 if max_ch >= 2 else 1
        rate = self._negotiate_rate(sd, segments, device, out_ch, device_rate)
        prepared = [(_resample(seg.data, seg.samplerate, rate), seg) for seg in segments]

        try:
            stream = sd.OutputStream(
                samplerate=rate, channels=out_ch, dtype="float32",
                device=device, blocksize=BLOCK_FRAMES,
            )
        except Exception as exc:
            raise AudioError(
                "출력 장치를 열지 못했습니다. 장치가 연결되어 있는지, 다른 프로그램이 "
                f"독점 사용 중은 아닌지 확인하세요.\n{exc}"
            ) from exc

        stop_fade = max(1, int(rate * STOP_FADE_MS / 1000))
        total_frames = sum(len(data) for data, _ in prepared)
        played = 0
        self._emit_progress(0.0, total_frames / rate if rate else 0.0)
        try:
            with stream:
                for data, seg in prepared:
                    stopped = self._write_segment(
                        stream, data, seg, rate, out_ch, master, stop_fade,
                        played, total_frames,
                    )
                    played += len(data)
                    if stopped:
                        return True
        except AudioError:
            raise
        except Exception as exc:
            raise AudioError(f"재생 중 오류가 발생했습니다: {exc}") from exc
        return self._stop_current.is_set()

    @staticmethod
    def _negotiate_rate(sd, segments: list[Segment], device, out_ch: int, device_rate: int) -> int:
        """작업 전체가 쓸 샘플레이트를 한 번만 정한다.

        본 음원의 원래 레이트를 우선 시도하고, 장치가 거부하면 장치 기본
        레이트로 떨어진다. 확인은 작업당 한 번뿐이라 재생 지연이 없다.
        """
        preferred = next(
            (s.samplerate for s in segments if s.label != "간격" and len(s.data)),
            device_rate,
        )
        for candidate in (preferred, device_rate):
            try:
                sd.check_output_settings(
                    device=device, samplerate=candidate, channels=out_ch, dtype="float32"
                )
                return int(candidate)
            except Exception:
                continue
        return int(device_rate)

    def _write_segment(
        self, stream, data: np.ndarray, seg: Segment,
        rate: int, out_ch: int, master: float, stop_fade: int,
        played_before: int = 0, total_frames: int = 0,
    ) -> bool:
        total = len(data)
        if total == 0:
            return self._stop_current.is_set()

        gain = max(0.0, seg.volume * master)
        fade_in = int(rate * seg.fade_in_ms / 1000)
        fade_out = int(rate * seg.fade_out_ms / 1000)
        stopping_at = -1
        pos = 0
        blocks = 0

        while pos < total:
            if self._stop_current.is_set() and stopping_at < 0:
                stopping_at = pos
            end = min(pos + BLOCK_FRAMES, total)
            block = _adapt_channels(data[pos:end], out_ch) * gain

            idx = np.arange(pos, end, dtype=np.float32)
            if fade_in > 0:
                block *= np.clip(idx / fade_in, 0.0, 1.0)[:, None]
            if fade_out > 0:
                block *= np.clip((total - idx) / fade_out, 0.0, 1.0)[:, None]
            if stopping_at >= 0:
                block *= np.clip(1.0 - (idx - stopping_at) / stop_fade, 0.0, 1.0)[:, None]

            np.clip(block, -1.0, 1.0, out=block)
            stream.write(np.ascontiguousarray(block, dtype=np.float32))
            pos = end

            blocks += 1
            if total_frames and blocks % _PROGRESS_EVERY_BLOCKS == 0:
                self._emit_progress((played_before + pos) / rate, total_frames / rate)

            if stopping_at >= 0 and pos - stopping_at >= stop_fade:
                return True
        if total_frames:
            self._emit_progress((played_before + total) / rate, total_frames / rate)
        return False


def silence(seconds: float, samplerate: int = 44100, channels: int = 1) -> Segment:
    frames = max(0, int(seconds * samplerate))
    return Segment(np.zeros((frames, channels), dtype=np.float32), samplerate, label="간격")

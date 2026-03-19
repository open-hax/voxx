from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "1" if default else "0") or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = str(os.getenv(name, str(default)) or str(default)).strip()
    try:
        value = float(raw)
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = str(os.getenv(name, str(default)) or str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


@dataclass
class Settings:
    host: str = field(default_factory=lambda: str(os.getenv("VOICE_GATEWAY_HOST", "0.0.0.0") or "0.0.0.0"))
    port: int = field(default_factory=lambda: int(str(os.getenv("VOICE_GATEWAY_PORT", "8788") or "8788")))
    api_key: str = field(default_factory=lambda: str(os.getenv("VOICE_GATEWAY_API_KEY", "") or "").strip())
    data_dir: Path = field(default_factory=lambda: Path(str(os.getenv("VOICE_GATEWAY_DATA_DIR", "data") or "data")))
    ffmpeg_bin: str = field(default_factory=lambda: shutil.which("ffmpeg") or "")
    default_audio_format: str = field(default_factory=lambda: str(os.getenv("VOICE_GATEWAY_DEFAULT_AUDIO_FORMAT", "mp3") or "mp3").strip().lower())
    default_language: str = field(default_factory=lambda: str(os.getenv("VOICE_GATEWAY_DEFAULT_LANGUAGE", "en") or "en").strip().lower())
    tts_device: str = field(default_factory=lambda: str(os.getenv("VOICE_GATEWAY_TTS_DEVICE", "auto") or "auto").strip())
    tts_eager_load: bool = field(default_factory=lambda: _env_bool("VOICE_GATEWAY_TTS_EAGER_LOAD", False))
    tts_narrator_unifier_enabled: bool = field(default_factory=lambda: _env_bool("TTS_NARRATOR_UNIFIER_ENABLED", True))
    tts_narrator_target_dbfs: float = field(default_factory=lambda: _env_float("TTS_NARRATOR_TARGET_DBFS", -18.0, -30.0, -8.0))
    tts_narrator_en_pitch: float = field(default_factory=lambda: _env_float("TTS_NARRATOR_EN_PITCH", 1.02, 0.9, 1.1))
    tts_narrator_jp_pitch: float = field(default_factory=lambda: _env_float("TTS_NARRATOR_JP_PITCH", 0.97, 0.9, 1.1))
    tts_narrator_en_variance_depth: float = field(default_factory=lambda: _env_float("TTS_NARRATOR_EN_VARIANCE_DEPTH", 0.02, 0.0, 0.2))
    tts_narrator_variance_freq_hz: float = field(default_factory=lambda: _env_float("TTS_NARRATOR_VARIANCE_FREQ_HZ", 4.5, 0.1, 12.0))
    tts_narrator_switch_fade_out_ms: int = field(default_factory=lambda: _env_int("TTS_NARRATOR_SWITCH_FADE_OUT_MS", 50, 0, 250))
    tts_narrator_switch_fade_in_ms: int = field(default_factory=lambda: _env_int("TTS_NARRATOR_SWITCH_FADE_IN_MS", 50, 0, 250))
    tts_narrator_switch_gap_ms: int = field(default_factory=lambda: _env_int("TTS_NARRATOR_SWITCH_GAP_MS", 100, 0, 400))
    tts_narrator_envelope_window_ms: int = field(default_factory=lambda: _env_int("TTS_NARRATOR_ENVELOPE_WINDOW_MS", 60, 20, 400))
    tts_narrator_envelope_strength: float = field(default_factory=lambda: _env_float("TTS_NARRATOR_ENVELOPE_STRENGTH", 0.12, 0.0, 0.5))
    tts_narrator_envelope_max_gain_db: float = field(default_factory=lambda: _env_float("TTS_NARRATOR_ENVELOPE_MAX_GAIN_DB", 1.2, 0.2, 8.0))
    stt_faster_whisper_model: str = field(default_factory=lambda: str(os.getenv("FASTER_WHISPER_MODEL", "small") or "small").strip())
    stt_faster_whisper_device: str = field(default_factory=lambda: str(os.getenv("FASTER_WHISPER_DEVICE", "auto") or "auto").strip())
    stt_faster_whisper_compute_type: str = field(default_factory=lambda: str(os.getenv("FASTER_WHISPER_COMPUTE_TYPE", "int8") or "int8").strip())
    whisper_cpp_bin: str = field(default_factory=lambda: str(os.getenv("WHISPER_CPP_BIN", "whisper-cli") or "whisper-cli").strip())
    whisper_cpp_model: str = field(default_factory=lambda: str(os.getenv("WHISPER_CPP_MODEL", "") or "").strip())

    cache_dir: Path = field(init=False)
    transcript_dir: Path = field(init=False)

    def __post_init__(self) -> None:
        self.data_dir = self.data_dir.resolve()
        self.cache_dir = (self.data_dir / "tts_cache").resolve()
        self.transcript_dir = (self.data_dir / "transcripts").resolve()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.transcript_dir.mkdir(parents=True, exist_ok=True)


_SETTINGS: Settings | None = None


def get_settings() -> Settings:
    global _SETTINGS
    if _SETTINGS is None:
        _SETTINGS = Settings()
    return _SETTINGS


def reset_settings_for_tests() -> None:
    global _SETTINGS
    _SETTINGS = None

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


def _env_csv(name: str, default: str = "") -> tuple[str, ...]:
    raw = str(os.getenv(name, default) or default).strip()
    if not raw:
        return tuple()
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _normalize_tts_backend_name(name: str) -> str:
    value = name.strip().lower()
    aliases = {
        "requesty": "requesty",
        "openai": "openai",
        "melo": "melo",
        "local": "melo",
        "local_melo": "melo",
        "espeak": "espeak",
        "kokoro": "kokoro",
        "mimo": "xiaomi_mimo",
        "mimo_tts": "xiaomi_mimo",
        "xiaomi": "xiaomi_mimo",
        "xiaomi_mimo": "xiaomi_mimo",
        "xiaomi-mimo": "xiaomi_mimo",
        "xaiomi": "xiaomi_mimo",
        "xaiomi_mimo": "xiaomi_mimo",
        "xaiomi-mimo": "xiaomi_mimo",
    }
    return aliases.get(value, value)


def _env_first(names: tuple[str, ...], default: str = "") -> str:
    for name in names:
        raw = str(os.getenv(name, "") or "").strip()
        if raw:
            return raw
    return default


TTS_POSTPROCESS_PROFILES: dict[str, dict[str, str]] = {
    "sports-commentator-v1": {
        "name": "Sports commentator",
        "description": "High-energy broadcast presence with speech-safe EQ, compression, limiter, and gain.",
    },
    "broadcast-warm-v1": {
        "name": "Broadcast warm",
        "description": "Warmer, less aggressive broadcast polish for conversational narration.",
    },
    "narrator-polish-v1": {
        "name": "Narrator polish",
        "description": "Clean audiobook-style leveling and presence without a hype-voice push.",
    },
    "crisp-radio-v1": {
        "name": "Crisp radio",
        "description": "Tighter radio/dispatch intelligibility with stronger presence and bandwidth control.",
    },
    "soft-studio-v1": {
        "name": "Soft studio",
        "description": "Gentle studio cleanup for softer voices and longer listening sessions.",
    },
}


TTS_PROMPT_AWARE_STYLE = (
    "Prompt-aware performance mode is enabled. Interpret bracketed or XML-like tags such as "
    "[excited], [whisper], [laugh], [pause], [dramatic], or <break time=\"500ms\" /> as voice "
    "performance directions. Do not speak the tags themselves. Preserve the user's words while using "
    "the tags only for timing, energy, emotion, and inflection."
)


def _normalize_tts_postprocess_profile_name(name: str) -> str:
    value = name.strip().lower().replace("_", "-").replace(" ", "-")
    aliases = {
        "": "",
        "off": "",
        "none": "",
        "disabled": "",
        "sports": "sports-commentator-v1",
        "commentator": "sports-commentator-v1",
        "broadcast": "broadcast-warm-v1",
        "warm": "broadcast-warm-v1",
        "broadcast-warm": "broadcast-warm-v1",
        "broadcast-warm-v1": "broadcast-warm-v1",
        "narrator": "narrator-polish-v1",
        "polish": "narrator-polish-v1",
        "narrator-polish": "narrator-polish-v1",
        "narrator-polish-v1": "narrator-polish-v1",
        "radio": "crisp-radio-v1",
        "crisp": "crisp-radio-v1",
        "crisp-radio": "crisp-radio-v1",
        "crisp-radio-v1": "crisp-radio-v1",
        "soft": "soft-studio-v1",
        "studio": "soft-studio-v1",
        "soft-studio": "soft-studio-v1",
        "soft-studio-v1": "soft-studio-v1",
        "sports-commentator": "sports-commentator-v1",
        "sports-commentary": "sports-commentator-v1",
        "broadcast-sports": "sports-commentator-v1",
        "sports-commentator-v1": "sports-commentator-v1",
    }
    return aliases.get(value, value)


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
    tts_backend_order: tuple[str, ...] = field(default_factory=lambda: _env_csv("VOICE_GATEWAY_TTS_BACKEND_ORDER"))
    tts_remote_timeout_seconds: float = field(default_factory=lambda: _env_float("VOICE_GATEWAY_TTS_REMOTE_TIMEOUT_SECONDS", 45.0, 1.0, 300.0))
    requesty_api_token: str = field(default_factory=lambda: str(os.getenv("REQUESTY_API_TOKEN", "") or "").strip())
    requesty_tts_base_url: str = field(default_factory=lambda: str(os.getenv("REQUESTY_TTS_BASE_URL", "https://router.requesty.ai/v1/audio/speech") or "https://router.requesty.ai/v1/audio/speech").strip())
    requesty_tts_model: str = field(default_factory=lambda: str(os.getenv("REQUESTY_TTS_MODEL", "openai/gpt-4o-mini-tts") or "openai/gpt-4o-mini-tts").strip())
    requesty_tts_voice: str = field(default_factory=lambda: str(os.getenv("REQUESTY_TTS_VOICE", "ash") or "ash").strip())
    openai_api_key: str = field(default_factory=lambda: str(os.getenv("OPENAI_API_KEY", "") or "").strip())
    openai_tts_base_url: str = field(default_factory=lambda: str(os.getenv("OPENAI_TTS_BASE_URL", "https://api.openai.com/v1/audio/speech") or "https://api.openai.com/v1/audio/speech").strip())
    openai_tts_model: str = field(default_factory=lambda: str(os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts") or "gpt-4o-mini-tts").strip())
    openai_tts_voice: str = field(default_factory=lambda: str(os.getenv("OPENAI_TTS_VOICE", "ash") or "ash").strip())
    xiaomi_mimo_api_key: str = field(default_factory=lambda: _env_first(("XIAOMI_MIMO_API_KEY", "XAIOMI_MIMO_API_KEY")))
    xiaomi_mimo_api_base_url: str = field(default_factory=lambda: _env_first(("XIAOMI_MIMO_API_BASE_URL", "XAIOMI_MIMO_API_BASE_URL"), "https://api.xiaomimimo.com/v1").rstrip("/"))
    xiaomi_mimo_tts_model: str = field(default_factory=lambda: str(os.getenv("XIAOMI_MIMO_TTS_MODEL", os.getenv("XAIOMI_MIMO_TTS_MODEL", "mimo-v2.5-tts")) or "mimo-v2.5-tts").strip())
    xiaomi_mimo_tts_voice: str = field(default_factory=lambda: str(os.getenv("XIAOMI_MIMO_TTS_VOICE", os.getenv("XAIOMI_MIMO_TTS_VOICE", "mimo_default")) or "mimo_default").strip())
    xiaomi_mimo_tts_style: str = field(default_factory=lambda: str(os.getenv("XIAOMI_MIMO_TTS_STYLE", os.getenv("XAIOMI_MIMO_TTS_STYLE", "Speak naturally and clearly.")) or "Speak naturally and clearly.").strip())
    kokoro_api_key: str = field(default_factory=lambda: str(os.getenv("KOKORO_API_KEY", "") or "").strip())
    kokoro_tts_base_url: str = field(default_factory=lambda: str(os.getenv("KOKORO_TTS_BASE_URL", "http://kokoro:8880/v1/audio/speech") or "http://kokoro:8880/v1/audio/speech").strip().rstrip("/"))
    kokoro_tts_model: str = field(default_factory=lambda: str(os.getenv("KOKORO_TTS_MODEL", "kokoro") or "kokoro").strip())
    kokoro_tts_voice: str = field(default_factory=lambda: str(os.getenv("KOKORO_TTS_VOICE", "af_bella_725_H") or "af_bella_725_H").strip())
    tts_postprocess_enabled: bool = field(default_factory=lambda: _env_bool("TTS_POSTPROCESS_ENABLED", True))
    tts_postprocess_profile: str = field(default_factory=lambda: _normalize_tts_postprocess_profile_name(str(os.getenv("TTS_POSTPROCESS_PROFILE", "sports-commentator-v1") or "sports-commentator-v1")))
    tts_prompt_aware_default: bool = field(default_factory=lambda: _env_bool("TTS_PROMPT_AWARE_DEFAULT", False))
    tts_prompt_aware_style: str = field(default_factory=lambda: str(os.getenv("TTS_PROMPT_AWARE_STYLE", TTS_PROMPT_AWARE_STYLE) or TTS_PROMPT_AWARE_STYLE).strip())
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

    def preferred_tts_backends(self) -> tuple[str, ...]:
        configured = tuple(
            _normalize_tts_backend_name(name) for name in self.tts_backend_order if _normalize_tts_backend_name(name)
        )
        if configured:
            ordered = configured
        else:
            ordered_list: list[str] = []
            if self.kokoro_api_key or self.kokoro_tts_base_url:
                ordered_list.append("kokoro")
            if self.xiaomi_mimo_api_key and self.xiaomi_mimo_api_base_url:
                ordered_list.append("xiaomi_mimo")
            if self.requesty_api_token:
                ordered_list.append("requesty")
            if self.openai_api_key:
                ordered_list.append("openai")
            ordered_list.extend(["melo", "espeak"])
            ordered = tuple(ordered_list)

        deduped: list[str] = []
        for backend in ordered:
            if backend and backend not in deduped:
                deduped.append(backend)
        return tuple(deduped)

    def active_tts_postprocess_profile(self, *, requested_profile: str | None = None, enabled: bool | None = None) -> str:
        if enabled is False or (enabled is None and not self.tts_postprocess_enabled):
            return ""
        profile = self.tts_postprocess_profile if requested_profile is None else requested_profile
        return _normalize_tts_postprocess_profile_name(profile)

    def tts_postprocess_profiles_payload(self) -> dict[str, object]:
        return {
            "default_profile": self.active_tts_postprocess_profile(),
            "profiles": [
                {
                    "id": profile_id,
                    **metadata,
                }
                for profile_id, metadata in TTS_POSTPROCESS_PROFILES.items()
            ],
            "aliases": {
                "off": "",
                "sports": "sports-commentator-v1",
                "commentator": "sports-commentator-v1",
                "broadcast": "broadcast-warm-v1",
                "narrator": "narrator-polish-v1",
                "radio": "crisp-radio-v1",
                "soft": "soft-studio-v1",
            },
        }


_SETTINGS: Settings | None = None


def get_settings() -> Settings:
    global _SETTINGS
    if _SETTINGS is None:
        _SETTINGS = Settings()
    return _SETTINGS


def reset_settings_for_tests() -> None:
    global _SETTINGS
    _SETTINGS = None

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class VoiceProfile:
    id: str
    name: str
    melo_language: str
    category: str = "premade"
    description: str = "OpenHax compatibility voice"
    pitch_multiplier: float = 1.0
    speed_multiplier: float = 1.0
    stability: float = 0.55
    similarity_boost: float = 0.78
    style: float = 0.12
    use_speaker_boost: bool = True
    labels: dict[str, str] = field(default_factory=dict)
    aliases: tuple[str, ...] = tuple()

    def matches(self, voice_id: str) -> bool:
        target = voice_id.strip().lower()
        if target == self.id.lower():
            return True
        return target in {alias.lower() for alias in self.aliases}

    def elevenlabs_settings(self) -> dict[str, Any]:
        return {
            "stability": self.stability,
            "similarity_boost": self.similarity_boost,
            "style": self.style,
            "use_speaker_boost": self.use_speaker_boost,
            "speed": self.speed_multiplier,
        }


VOICE_PROFILES: tuple[VoiceProfile, ...] = (
    VoiceProfile(
        id="alloy",
        name="Alloy",
        melo_language="EN",
        description="Neutral OpenAI-compatible default voice",
        aliases=("rachel", "bella"),
        labels={"accent": "neutral", "provider": "openai+elevenlabs-compatible"},
    ),
    VoiceProfile(
        id="nova",
        name="Nova",
        melo_language="EN",
        pitch_multiplier=1.04,
        speed_multiplier=1.03,
        stability=0.62,
        style=0.18,
        aliases=("aria", "serena"),
        labels={"accent": "bright", "provider": "openai+elevenlabs-compatible"},
    ),
    VoiceProfile(
        id="onyx",
        name="Onyx",
        melo_language="EN",
        pitch_multiplier=0.96,
        speed_multiplier=0.98,
        stability=0.68,
        style=0.08,
        aliases=("adam", "antoni"),
        labels={"accent": "low", "provider": "openai+elevenlabs-compatible"},
    ),
    VoiceProfile(
        id="shimmer",
        name="Shimmer",
        melo_language="EN",
        pitch_multiplier=1.06,
        speed_multiplier=1.01,
        stability=0.58,
        style=0.24,
        aliases=("elli", "dorothy"),
        labels={"accent": "airy", "provider": "openai+elevenlabs-compatible"},
    ),
    VoiceProfile(
        id="echo",
        name="Echo",
        melo_language="EN",
        pitch_multiplier=0.99,
        speed_multiplier=0.97,
        stability=0.7,
        style=0.06,
        aliases=("sam", "josh"),
        labels={"accent": "steady", "provider": "openai+elevenlabs-compatible"},
    ),
    VoiceProfile(
        id="sage",
        name="Sage",
        melo_language="EN",
        pitch_multiplier=1.0,
        speed_multiplier=0.95,
        stability=0.74,
        style=0.05,
        aliases=("george",),
        labels={"accent": "measured", "provider": "openai-compatible"},
    ),
    VoiceProfile(
        id="kaede",
        name="Kaede",
        melo_language="JP",
        pitch_multiplier=1.0,
        speed_multiplier=1.0,
        stability=0.61,
        style=0.16,
        aliases=("ja_default", "sakura"),
        labels={"accent": "jp", "provider": "openhax"},
    ),
)


MODEL_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "id": "gpt-4o-mini-tts",
        "object": "model",
        "created": 0,
        "owned_by": "openhax",
        "modalities": ["text", "audio"],
        "family": "tts",
    },
    {
        "id": "tts-1",
        "object": "model",
        "created": 0,
        "owned_by": "openhax",
        "modalities": ["text", "audio"],
        "family": "tts",
    },
    {
        "id": "tts-1-hd",
        "object": "model",
        "created": 0,
        "owned_by": "openhax",
        "modalities": ["text", "audio"],
        "family": "tts",
    },
    {
        "id": "gpt-4o-transcribe",
        "object": "model",
        "created": 0,
        "owned_by": "openhax",
        "modalities": ["audio", "text"],
        "family": "stt",
    },
    {
        "id": "gpt-4o-mini-transcribe",
        "object": "model",
        "created": 0,
        "owned_by": "openhax",
        "modalities": ["audio", "text"],
        "family": "stt",
    },
    {
        "id": "gpt-4o-transcribe-diarize",
        "object": "model",
        "created": 0,
        "owned_by": "openhax",
        "modalities": ["audio", "text"],
        "family": "stt",
    },
    {
        "id": "whisper-1",
        "object": "model",
        "created": 0,
        "owned_by": "openhax",
        "modalities": ["audio", "text"],
        "family": "stt",
    },
    {
        "id": "eleven_multilingual_v2",
        "object": "model",
        "created": 0,
        "owned_by": "openhax",
        "modalities": ["text", "audio"],
        "family": "tts",
    },
    {
        "id": "scribe_v1",
        "object": "model",
        "created": 0,
        "owned_by": "openhax",
        "modalities": ["audio", "text"],
        "family": "stt",
    },
)


DEFAULT_OPENAI_VOICE = "alloy"
DEFAULT_ELEVENLABS_VOICE = "alloy"


def list_models() -> list[dict[str, Any]]:
    return [dict(model) for model in MODEL_CATALOG]


def list_voices() -> list[VoiceProfile]:
    return list(VOICE_PROFILES)


def resolve_voice(voice_id: str | None, language_hint: str | None = None) -> VoiceProfile:
    if voice_id:
        for profile in VOICE_PROFILES:
            if profile.matches(voice_id):
                return profile

    if language_hint and language_hint.lower().startswith("ja"):
        for profile in VOICE_PROFILES:
            if profile.melo_language == "JP":
                return profile

    for profile in VOICE_PROFILES:
        if profile.id == DEFAULT_OPENAI_VOICE:
            return profile
    return VOICE_PROFILES[0]


def voice_to_elevenlabs_json(profile: VoiceProfile) -> dict[str, Any]:
    return {
        "voice_id": profile.id,
        "name": profile.name,
        "category": profile.category,
        "description": profile.description,
        "labels": dict(profile.labels),
        "preview_url": None,
        "available_for_tiers": ["free", "starter", "creator", "pro"],
        "settings": profile.elevenlabs_settings(),
    }


def voice_to_openai_json(profile: VoiceProfile) -> dict[str, Any]:
    return {
        "id": profile.id,
        "object": "voice",
        "name": profile.name,
        "language": profile.melo_language.lower(),
        "provider": "openhax",
    }

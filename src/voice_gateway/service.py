from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Request

from .auth import is_authorized
from .catalog import (
    DEFAULT_ELEVENLABS_VOICE,
    list_models,
    list_voices,
    resolve_voice,
    voice_to_elevenlabs_json,
    voice_to_openai_json,
)
from .config import Settings, get_settings
from .stt import LocalSttEngine
from .transcripts import TranscriptStore
from .tts import LocalTtsEngine


@dataclass
class VoiceGatewayService:
    settings: Settings
    tts_engine: Any
    stt_engine: Any
    transcript_store: TranscriptStore

    @classmethod
    def create_default(cls) -> "VoiceGatewayService":
        settings = get_settings()
        return cls(
            settings=settings,
            tts_engine=LocalTtsEngine(settings),
            stt_engine=LocalSttEngine(settings),
            transcript_store=TranscriptStore(settings.transcript_dir),
        )

    def authorized(self, request: Request) -> bool:
        return is_authorized(request, self.settings)

    def openai_models_payload(self) -> dict[str, Any]:
        return {
            "object": "list",
            "data": list_models(),
        }

    def voices_payload(self, *, search: str | None = None, voice_ids: list[str] | None = None) -> dict[str, Any]:
        voices = list_voices()
        if voice_ids:
            lowered = {voice_id.strip().lower() for voice_id in voice_ids if voice_id.strip()}
            voices = [voice for voice in voices if voice.id.lower() in lowered or any(alias.lower() in lowered for alias in voice.aliases)]
        if search:
            needle = search.strip().lower()
            voices = [
                voice
                for voice in voices
                if needle in voice.id.lower()
                or needle in voice.name.lower()
                or any(needle in alias.lower() for alias in voice.aliases)
            ]
        payload = [voice_to_elevenlabs_json(voice) for voice in voices]
        return {
            "voices": payload,
            "has_more": False,
            "next_page_token": None,
            "total_count": len(payload),
        }

    def voice_payload(self, voice_id: str) -> dict[str, Any]:
        voice = resolve_voice(voice_id)
        return voice_to_elevenlabs_json(voice)

    def voice_settings_payload(self, voice_id: str) -> dict[str, Any]:
        voice = resolve_voice(voice_id)
        return voice.elevenlabs_settings()

    def synthesize_openai(
        self,
        *,
        text: str,
        voice_id: str | None,
        response_format: str,
        speed: float,
        language: str | None,
    ) -> tuple[bytes, str, dict[str, str]]:
        voice = resolve_voice(voice_id, language)
        audio_bytes, normalized_format = self.tts_engine.synthesize(
            text,
            voice=voice,
            response_format=response_format,
            speed=speed,
            language=language,
        )
        headers = {
            "x-openhax-voice-id": voice.id,
            "x-openhax-audio-format": normalized_format,
        }
        return audio_bytes, normalized_format, headers

    def synthesize_elevenlabs(
        self,
        *,
        text: str,
        voice_id: str | None,
        response_format: str,
        speed: float,
        language: str | None,
    ) -> tuple[bytes, str, dict[str, str]]:
        return self.synthesize_openai(
            text=text,
            voice_id=voice_id or DEFAULT_ELEVENLABS_VOICE,
            response_format=response_format,
            speed=speed,
            language=language,
        )

    def transcribe(
        self,
        *,
        audio_bytes: bytes,
        mime: str,
        language: str | None,
        task: str,
    ) -> Any:
        return self.stt_engine.transcribe(audio_bytes, mime=mime, language=language, task=task)

    def store_transcript(
        self,
        *,
        source_name: str,
        mime_type: str,
        task: str,
        model_id: str,
        result: Any,
    ) -> dict[str, Any]:
        return self.transcript_store.create(
            source_name=source_name,
            mime_type=mime_type,
            task=task,
            model_id=model_id,
            result=result,
        ).to_dict()

    def get_transcript(self, transcription_id: str) -> dict[str, Any] | None:
        return self.transcript_store.get(transcription_id)

    def openai_voice_payload(self) -> dict[str, Any]:
        return {
            "object": "list",
            "data": [voice_to_openai_json(voice) for voice in list_voices()],
        }

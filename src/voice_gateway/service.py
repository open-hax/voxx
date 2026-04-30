from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

from fastapi import Request

from .auth import is_authorized
from .catalog import (
    list_models,
    list_voices,
    resolve_voice,
    voice_to_catalog_json,
    voice_to_openai_json,
)
from .config import Settings, get_settings
from .stt import LocalSttEngine
from .transcripts import TranscriptStore
from .tts import LocalTtsEngine


class TtsQueueFullError(RuntimeError):
    pass


class TtsProcessingQueue:
    def __init__(self, *, max_concurrent: int, max_pending: int, timeout_seconds: float) -> None:
        self.max_concurrent = max(1, max_concurrent)
        self.max_pending = max(0, max_pending)
        self.timeout_seconds = max(0.1, timeout_seconds)
        self._semaphore = threading.BoundedSemaphore(self.max_concurrent)
        self._lock = threading.Lock()
        self._active = 0
        self._waiting = 0

    @contextmanager
    def slot(self) -> Iterator[float]:
        with self._lock:
            if self._active >= self.max_concurrent and self._waiting >= self.max_pending:
                raise TtsQueueFullError(
                    f"TTS queue is full: active={self._active}, waiting={self._waiting}, "
                    f"max_concurrent={self.max_concurrent}, max_pending={self.max_pending}"
                )
            self._waiting += 1

        started = time.monotonic()
        acquired = False
        try:
            acquired = self._semaphore.acquire(timeout=self.timeout_seconds)
            wait_seconds = time.monotonic() - started
            with self._lock:
                self._waiting -= 1
                if acquired:
                    self._active += 1
            if not acquired:
                raise TtsQueueFullError(
                    f"Timed out waiting for TTS queue after {self.timeout_seconds:.1f}s; "
                    f"max_concurrent={self.max_concurrent}, max_pending={self.max_pending}"
                )
            yield wait_seconds
        finally:
            if acquired:
                with self._lock:
                    self._active -= 1
                self._semaphore.release()

    def payload(self) -> dict[str, int | float]:
        with self._lock:
            return {
                "active": self._active,
                "waiting": self._waiting,
                "max_concurrent": self.max_concurrent,
                "max_pending": self.max_pending,
                "timeout_seconds": self.timeout_seconds,
            }


@dataclass
class VoiceGatewayService:
    settings: Settings
    tts_engine: Any
    stt_engine: Any
    transcript_store: TranscriptStore
    tts_queue: TtsProcessingQueue | None = None

    @classmethod
    def create_default(cls) -> "VoiceGatewayService":
        settings = get_settings()
        return cls(
            settings=settings,
            tts_engine=LocalTtsEngine(settings),
            stt_engine=LocalSttEngine(settings),
            transcript_store=TranscriptStore(settings.transcript_dir),
            tts_queue=TtsProcessingQueue(
                max_concurrent=settings.tts_queue_max_concurrent,
                max_pending=settings.tts_queue_max_pending,
                timeout_seconds=settings.tts_queue_timeout_seconds,
            ),
        )

    def __post_init__(self) -> None:
        if self.tts_queue is None:
            self.tts_queue = TtsProcessingQueue(
                max_concurrent=self.settings.tts_queue_max_concurrent,
                max_pending=self.settings.tts_queue_max_pending,
                timeout_seconds=self.settings.tts_queue_timeout_seconds,
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
        payload = [voice_to_catalog_json(voice) for voice in voices]
        return {
            "voices": payload,
            "has_more": False,
            "next_page_token": None,
            "total_count": len(payload),
        }

    def voice_payload(self, voice_id: str) -> dict[str, Any]:
        voice = resolve_voice(voice_id)
        return voice_to_catalog_json(voice)

    def voice_settings_payload(self, voice_id: str) -> dict[str, Any]:
        voice = resolve_voice(voice_id)
        return voice.voice_settings()

    def tts_postprocess_profiles_payload(self) -> dict[str, object]:
        return self.settings.tts_postprocess_profiles_payload()

    def tts_queue_payload(self) -> dict[str, int | float]:
        assert self.tts_queue is not None
        return self.tts_queue.payload()

    def synthesize_openai(
        self,
        *,
        text: str,
        voice_id: str | None,
        response_format: str,
        speed: float,
        language: str | None,
        postprocess_profile: str | None = None,
        postprocess_enabled: bool | None = None,
        prompt_aware: bool | None = None,
        prompt_aware_style: str | None = None,
    ) -> tuple[bytes, str, dict[str, str]]:
        voice = resolve_voice(voice_id, language)
        assert self.tts_queue is not None
        with self.tts_queue.slot() as queue_wait_seconds:
            audio_bytes, normalized_format = self.tts_engine.synthesize(
                text,
                voice=voice,
                response_format=response_format,
                speed=speed,
                language=language,
                requested_voice_id=voice_id,
                postprocess_profile=postprocess_profile,
                postprocess_enabled=postprocess_enabled,
                prompt_aware=prompt_aware,
                prompt_aware_style=prompt_aware_style,
            )
        headers = {
            "x-openhax-voice-id": voice.id,
            "x-openhax-audio-format": normalized_format,
            "x-openhax-tts-queue-wait-ms": str(int(round(queue_wait_seconds * 1000))),
            "x-openhax-tts-queue-max-concurrent": str(self.tts_queue.max_concurrent),
        }
        backend = str(getattr(self.tts_engine, "last_backend", "") or "").strip()
        if backend:
            headers["x-openhax-tts-backend"] = backend
        postprocess = str(getattr(self.tts_engine, "last_postprocess_profile", "") or "").strip()
        headers["x-openhax-tts-postprocess-profile"] = postprocess or "none"
        headers["x-openhax-tts-prompt-aware"] = "1" if bool(getattr(self.tts_engine, "last_prompt_aware", False)) else "0"
        if voice_id:
            headers["x-openhax-requested-voice-id"] = voice_id
        return audio_bytes, normalized_format, headers

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

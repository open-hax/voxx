from __future__ import annotations

import base64
import hashlib
import math
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any

import httpx

from .audio_utils import convert_audio_bytes, normalize_audio_format
from .catalog import VoiceProfile
from .config import Settings, get_settings


_SEGMENT_JP_PATTERN = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]+")
_TTS_MODEL_LOCK = threading.Lock()
_TTS_MODELS: dict[str, Any] | None | bool = None


class LocalTtsEngine:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.device = self._resolve_device()
        self.last_backend = ""
        if self.settings.tts_eager_load:
            self._load_models()

    def _resolve_device(self) -> str:
        requested = self.settings.tts_device.strip().lower()
        if requested and requested != "auto":
            return requested
        try:
            import torch

            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            return "cpu"

    def _load_models(self) -> dict[str, Any] | None:
        global _TTS_MODELS
        with _TTS_MODEL_LOCK:
            if _TTS_MODELS is False:
                return None
            if isinstance(_TTS_MODELS, dict):
                return _TTS_MODELS
            try:
                from melo.api import TTS
            except Exception:
                _TTS_MODELS = False
                return None
            try:
                _TTS_MODELS = {
                    "EN": TTS(language="EN", device=self.device),
                    "JP": TTS(language="JP", device=self.device),
                }
            except Exception:
                _TTS_MODELS = False
                return None
            return _TTS_MODELS

    def _narrator_profile_signature(self, voice: VoiceProfile) -> str:
        return (
            f"voice={voice.id}"
            f";lang={voice.melo_language}"
            f";pitch={voice.pitch_multiplier:.4f}"
            f";speed={voice.speed_multiplier:.4f}"
            f";enabled={int(self.settings.tts_narrator_unifier_enabled)}"
            f";en_pitch={self.settings.tts_narrator_en_pitch:.4f}"
            f";jp_pitch={self.settings.tts_narrator_jp_pitch:.4f}"
            f";en_var={self.settings.tts_narrator_en_variance_depth:.4f}"
            f";var_f={self.settings.tts_narrator_variance_freq_hz:.3f}"
        )

    def _build_filter_chain(self, language: str, voice: VoiceProfile) -> str:
        base_pitch = (
            self.settings.tts_narrator_en_pitch
            if language == "EN"
            else self.settings.tts_narrator_jp_pitch
        )
        pitch = base_pitch * voice.pitch_multiplier
        filters = [f"rubberband=pitch={pitch:.6f}"]
        if language == "EN" and self.settings.tts_narrator_en_variance_depth > 0.0:
            filters.append(
                "vibrato="
                f"f={self.settings.tts_narrator_variance_freq_hz:.3f}"
                f":d={self.settings.tts_narrator_en_variance_depth:.3f}"
            )
        return ",".join(filters)

    def _build_output_postprocess_filter_chain(self) -> str:
        profile = self.settings.active_tts_postprocess_profile()
        if not profile:
            return ""
        if profile == "sports-commentator-v1":
            # Conservative broadcast-style mastering that survives current ffmpeg builds
            # and works across local + remote provider outputs.
            return ",".join(
                [
                    "highpass=f=90",
                    "lowpass=f=13500",
                    "equalizer=f=180:t=q:w=0.8:g=1.5",
                    "equalizer=f=2600:t=q:w=1.1:g=3.8",
                    "equalizer=f=4200:t=q:w=1.0:g=4.2",
                    "equalizer=f=7800:t=q:w=1.2:g=1.2",
                    "acompressor=threshold=0.18:ratio=3.5:attack=5:release=80:makeup=2.0:knee=2.5:link=average:detection=rms",
                    "alimiter=limit=0.93",
                    "volume=1.8dB",
                ]
            )
        return ""

    def _render_with_ffmpeg(self, input_path: Path, output_path: Path, filters: str) -> bool:
        if not self.settings.ffmpeg_bin:
            return False
        command = [
            self.settings.ffmpeg_bin,
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(input_path),
            "-af",
            filters,
            str(output_path),
        ]
        try:
            subprocess.run(command, check=True, timeout=40)
        except (OSError, subprocess.SubprocessError):
            return False
        return output_path.exists() and output_path.stat().st_size > 44

    def _split_text_by_language(self, text: str) -> list[tuple[str, str]]:
        parts: list[tuple[str, str]] = []
        last_end = 0
        for match in _SEGMENT_JP_PATTERN.finditer(text):
            start, end = match.start(), match.end()
            if start > last_end:
                parts.append((text[last_end:start], "EN"))
            parts.append((text[start:end], "JP"))
            last_end = end
        if last_end < len(text):
            parts.append((text[last_end:], "EN"))
        normalized = [(chunk.strip(), language) for chunk, language in parts if chunk.strip()]
        if normalized:
            return normalized
        stripped = text.strip()
        return [(stripped, "EN")] if stripped else []

    def _apply_envelope_shape(self, segment: Any) -> Any:
        if self.settings.tts_narrator_envelope_strength <= 0.0 or len(segment) < self.settings.tts_narrator_envelope_window_ms:
            return segment

        chunk_ms = max(1, self.settings.tts_narrator_envelope_window_ms)
        chunk_count = max(1, math.ceil(len(segment) / chunk_ms))
        chunks = []
        rms_values = []
        for index in range(chunk_count):
            start = index * chunk_ms
            end = min(len(segment), start + chunk_ms)
            chunk = segment[start:end]
            chunks.append(chunk)
            rms_values.append(float(max(chunk.rms, 1)))

        if not rms_values:
            return segment
        mean_rms = sum(rms_values) / len(rms_values)
        if mean_rms <= 0:
            return segment

        shaped = segment[:0]
        for chunk, rms in zip(chunks, rms_values):
            normalized = (rms / mean_rms) - 1.0
            scale = 1.0 + (normalized * self.settings.tts_narrator_envelope_strength)
            scale = max(0.7, min(1.3, scale))
            gain_db = 20.0 * math.log10(scale)
            gain_db = max(
                -self.settings.tts_narrator_envelope_max_gain_db,
                min(self.settings.tts_narrator_envelope_max_gain_db, gain_db),
            )
            shaped += chunk.apply_gain(gain_db)
        return shaped

    def _normalize_segment_level(self, segment: Any) -> Any:
        dbfs = float(getattr(segment, "dBFS", float("-inf")))
        if dbfs == float("-inf"):
            return segment
        gain = self.settings.tts_narrator_target_dbfs - dbfs
        gain = max(-18.0, min(18.0, gain))
        return segment.apply_gain(gain)

    def _apply_language_switch_smoothing(self, combined: Any, segment: Any, switched_language: bool, pydub_module: Any) -> Any:
        if not switched_language:
            return combined + segment

        fade_out_ms = min(self.settings.tts_narrator_switch_fade_out_ms, len(combined))
        if fade_out_ms > 0:
            combined = combined[:-fade_out_ms] + combined[-fade_out_ms:].fade_out(fade_out_ms)

        if self.settings.tts_narrator_switch_gap_ms > 0:
            combined += pydub_module.AudioSegment.silent(duration=self.settings.tts_narrator_switch_gap_ms)

        fade_in_ms = min(self.settings.tts_narrator_switch_fade_in_ms, len(segment))
        if fade_in_ms > 0:
            segment = segment.fade_in(fade_in_ms)

        return combined + segment

    def _model_speaker_id(self, model: Any, language: str) -> int:
        speaker_id = 0
        try:
            speaker_map = {}
            hps = getattr(model, "hps", None)
            data = getattr(hps, "data", None)
            data_speaker_map = getattr(data, "spk2id", None)
            hps_speaker_map = getattr(hps, "spk2id", None)
            if isinstance(data_speaker_map, dict):
                speaker_map = data_speaker_map
            elif isinstance(hps_speaker_map, dict):
                speaker_map = hps_speaker_map
            target_key = f"{language}-Default"
            if target_key in speaker_map:
                speaker_id = int(speaker_map[target_key])
            elif speaker_map:
                speaker_id = int(next(iter(speaker_map.values())))
        except Exception:
            speaker_id = 0
        return speaker_id

    def _cache_key(self, text: str, voice: VoiceProfile, speed: float, language: str | None) -> str:
        spec = (
            f"{text}|{voice.id}|{speed:.4f}|{language or ''}|{self._narrator_profile_signature(voice)}"
        )
        return hashlib.sha1(spec.encode("utf-8")).hexdigest()

    def _synthesize_with_melo(self, text: str, voice: VoiceProfile, *, speed: float, language: str | None) -> bytes | None:
        models = self._load_models()
        if not models:
            return None
        try:
            import pydub
        except Exception:
            return None

        effective_speed = max(0.6, min(1.6, speed * voice.speed_multiplier))
        cache_id = self._cache_key(text, voice, effective_speed, language)
        cache_path = self.settings.cache_dir / f"{cache_id}.wav"
        if cache_path.exists():
            return cache_path.read_bytes()

        segments = self._split_text_by_language(text)
        if not segments:
            return None

        with tempfile.TemporaryDirectory(prefix="voice_gateway_tts_") as temp_dir:
            temp_root = Path(temp_dir)
            rendered_files: list[tuple[Path, str]] = []
            for index, (chunk, chunk_language) in enumerate(segments):
                target_language = chunk_language
                if language and language.lower().startswith("ja"):
                    target_language = "JP"
                model = models.get(target_language) or models.get(voice.melo_language) or models.get("EN")
                if model is None:
                    return None
                source_path = temp_root / f"segment_{index}.wav"
                speaker_id = self._model_speaker_id(model, target_language)
                model.tts_to_file(chunk, speaker_id, str(source_path), speed=effective_speed)
                rendered_path = source_path
                if self.settings.tts_narrator_unifier_enabled:
                    styled_path = temp_root / f"segment_{index}_styled.wav"
                    if self._render_with_ffmpeg(source_path, styled_path, self._build_filter_chain(target_language, voice)):
                        rendered_path = styled_path
                rendered_files.append((rendered_path, target_language))

            combined = pydub.AudioSegment.empty()
            previous_language = ""
            for rendered_path, chunk_language in rendered_files:
                audio = pydub.AudioSegment.from_wav(str(rendered_path))
                if self.settings.tts_narrator_unifier_enabled:
                    audio = self._apply_envelope_shape(audio)
                    audio = self._normalize_segment_level(audio)
                if len(combined) == 0:
                    fade_in_ms = min(self.settings.tts_narrator_switch_fade_in_ms, len(audio))
                    combined += audio.fade_in(fade_in_ms) if fade_in_ms > 0 else audio
                else:
                    combined = self._apply_language_switch_smoothing(
                        combined,
                        audio,
                        switched_language=previous_language != chunk_language,
                        pydub_module=pydub,
                    )
                previous_language = chunk_language

            combined.export(str(cache_path), format="wav")
            return cache_path.read_bytes()

    def _remote_voice_candidates(
        self,
        voice: VoiceProfile,
        *,
        backend: str,
        requested_voice_id: str | None,
        default_voice: str | None,
    ) -> list[str]:
        candidates: list[str] = []
        raw_requested = str(requested_voice_id or "").strip()
        if raw_requested:
            candidates.append(raw_requested)
        mapped = voice.provider_voice(backend)
        if mapped:
            candidates.append(mapped)
        candidates.append(default_voice or "")
        if backend in {"requesty", "openai"}:
            candidates.append(voice.id)

        deduped: list[str] = []
        for candidate in candidates:
            normalized = candidate.strip()
            if normalized and normalized not in deduped:
                deduped.append(normalized)
        return deduped

    def _synthesize_with_openai_compatible(
        self,
        *,
        backend: str,
        api_key: str,
        base_url: str,
        model: str,
        default_voice: str,
        text: str,
        voice: VoiceProfile,
        requested_voice_id: str | None,
        speed: float,
        response_format: str,
    ) -> tuple[bytes, str]:
        if not base_url:
            raise RuntimeError(f"{backend} is not configured")
        if not api_key and backend != "kokoro":
            raise RuntimeError(f"{backend} is not configured")

        request_format = response_format if response_format in {"mp3", "wav", "flac", "opus", "pcm"} else "mp3"
        candidates = self._remote_voice_candidates(
            voice,
            backend=backend,
            requested_voice_id=requested_voice_id,
            default_voice=default_voice,
        )
        if not candidates:
            raise RuntimeError(f"{backend} has no usable voice candidate")

        errors: list[str] = []
        with httpx.Client(timeout=self.settings.tts_remote_timeout_seconds) as client:
            for voice_id in candidates:
                try:
                    headers = {"Content-Type": "application/json"}
                    if api_key:
                        headers["Authorization"] = f"Bearer {api_key}"
                    response = client.post(
                        base_url,
                        headers=headers,
                        json={
                            "model": model,
                            "input": text,
                            "voice": voice_id,
                            "response_format": request_format,
                            "speed": float(speed),
                        },
                    )
                    response.raise_for_status()
                    return response.content, request_format
                except httpx.HTTPStatusError as exc:
                    errors.append(f"voice={voice_id} status={exc.response.status_code}")
                    if exc.response.status_code in {400, 404, 422} and len(candidates) > 1:
                        continue
                    break
                except httpx.HTTPError as exc:
                    errors.append(f"voice={voice_id} error={exc.__class__.__name__}")
                    break
        detail = "; ".join(errors) if errors else "request failed"
        raise RuntimeError(f"{backend} failed ({detail})")

    def _synthesize_with_xiaomi_mimo(
        self,
        *,
        text: str,
        voice: VoiceProfile,
        requested_voice_id: str | None,
        response_format: str,
    ) -> tuple[bytes, str]:
        if not self.settings.xiaomi_mimo_api_key or not self.settings.xiaomi_mimo_api_base_url:
            raise RuntimeError("xiaomi_mimo is not configured")

        request_format = response_format if response_format in {"mp3", "wav"} else "mp3"
        candidates = self._remote_voice_candidates(
            voice,
            backend="xiaomi_mimo",
            requested_voice_id=requested_voice_id,
            default_voice=self.settings.xiaomi_mimo_tts_voice,
        )
        if not candidates:
            raise RuntimeError("xiaomi_mimo has no usable voice candidate")

        base_url = self.settings.xiaomi_mimo_api_base_url.rstrip("/")
        chat_url = f"{base_url}/chat/completions"
        style = self.settings.xiaomi_mimo_tts_style or "Speak naturally and clearly."
        errors: list[str] = []
        with httpx.Client(timeout=self.settings.tts_remote_timeout_seconds) as client:
            for voice_id in candidates:
                try:
                    response = client.post(
                        chat_url,
                        headers={
                            "Authorization": f"Bearer {self.settings.xiaomi_mimo_api_key}",
                            "api-key": self.settings.xiaomi_mimo_api_key,
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": self.settings.xiaomi_mimo_tts_model,
                            "messages": [
                                {"role": "user", "content": style},
                                {"role": "assistant", "content": text},
                            ],
                            "audio": {"voice": voice_id, "format": request_format},
                        },
                    )
                    response.raise_for_status()
                    payload = response.json()
                    message = payload.get("choices", [{}])[0].get("message", {})
                    audio = message.get("audio") or {}
                    audio_data = str(audio.get("data") or "")
                    if not audio_data:
                        raise RuntimeError("missing audio data")
                    return base64.b64decode(audio_data), request_format
                except httpx.HTTPStatusError as exc:
                    errors.append(f"voice={voice_id} status={exc.response.status_code}")
                    if exc.response.status_code in {400, 404, 422} and len(candidates) > 1:
                        continue
                    break
                except (ValueError, RuntimeError) as exc:
                    errors.append(f"voice={voice_id} error={exc}")
                    break
                except httpx.HTTPError as exc:
                    errors.append(f"voice={voice_id} error={exc.__class__.__name__}")
                    break
        detail = "; ".join(errors) if errors else "request failed"
        raise RuntimeError(f"xiaomi_mimo failed ({detail})")

    def _synthesize_with_elevenlabs(
        self,
        text: str,
        voice: VoiceProfile,
        *,
        requested_voice_id: str | None,
        speed: float,
    ) -> tuple[bytes, str]:
        if not self.settings.elevenlabs_api_key:
            raise RuntimeError("elevenlabs is not configured")

        candidates = self._remote_voice_candidates(
            voice,
            backend="elevenlabs",
            requested_voice_id=requested_voice_id,
            default_voice=self.settings.elevenlabs_voice_id,
        )
        if not candidates:
            raise RuntimeError("elevenlabs has no usable voice candidate")

        errors: list[str] = []
        with httpx.Client(timeout=self.settings.tts_remote_timeout_seconds) as client:
            for voice_id in candidates:
                try:
                    response = client.post(
                        f"{self.settings.elevenlabs_tts_base_url}/text-to-speech/{voice_id}",
                        params={"output_format": "mp3_44100_128"},
                        headers={
                            "xi-api-key": self.settings.elevenlabs_api_key,
                            "Content-Type": "application/json",
                        },
                        json={
                            "text": text,
                            "model_id": self.settings.elevenlabs_tts_model,
                            "voice_settings": {
                                "stability": voice.stability,
                                "similarity_boost": voice.similarity_boost,
                                "style": voice.style,
                                "use_speaker_boost": voice.use_speaker_boost,
                                "speed": max(0.6, min(1.2, speed * voice.speed_multiplier)),
                            },
                        },
                    )
                    response.raise_for_status()
                    return response.content, "mp3"
                except httpx.HTTPStatusError as exc:
                    errors.append(f"voice={voice_id} status={exc.response.status_code}")
                    if exc.response.status_code in {400, 404, 422} and len(candidates) > 1:
                        continue
                    break
                except httpx.HTTPError as exc:
                    errors.append(f"voice={voice_id} error={exc.__class__.__name__}")
                    break
        detail = "; ".join(errors) if errors else "request failed"
        raise RuntimeError(f"elevenlabs failed ({detail})")

    def _synthesize_with_espeak(self, text: str, *, speed: float) -> bytes | None:
        command_candidates = (
            ["espeak-ng"],
            ["espeak"],
        )
        words_per_minute = int(round(max(90, min(320, 170 * max(0.6, min(1.6, speed))))))
        with tempfile.TemporaryDirectory(prefix="voice_gateway_espeak_") as temp_dir:
            output_path = Path(temp_dir) / "fallback.wav"
            for prefix in command_candidates:
                command = [*prefix, "-s", str(words_per_minute), "-w", str(output_path), text[:600]]
                try:
                    result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=18)
                except (OSError, subprocess.SubprocessError):
                    continue
                if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 44:
                    return output_path.read_bytes()
        return None

    def synthesize(
        self,
        text: str,
        *,
        voice: VoiceProfile,
        response_format: str = "mp3",
        speed: float = 1.0,
        language: str | None = None,
        requested_voice_id: str | None = None,
    ) -> tuple[bytes, str]:
        normalized_format = normalize_audio_format(response_format or self.settings.default_audio_format)
        failures: list[str] = []
        self.last_backend = ""
        output_postprocess_filters = self._build_output_postprocess_filter_chain()

        for backend in self.settings.preferred_tts_backends():
            try:
                source_bytes: bytes | None = None
                source_format = "wav"
                if backend == "melo":
                    source_bytes = self._synthesize_with_melo(text, voice, speed=speed, language=language)
                elif backend == "kokoro":
                    source_bytes, source_format = self._synthesize_with_openai_compatible(
                        backend="kokoro",
                        api_key=self.settings.kokoro_api_key,
                        base_url=self.settings.kokoro_tts_base_url,
                        model=self.settings.kokoro_tts_model,
                        default_voice=self.settings.kokoro_tts_voice,
                        text=text,
                        voice=voice,
                        requested_voice_id=requested_voice_id,
                        speed=speed,
                        response_format=normalized_format,
                    )
                elif backend == "xiaomi_mimo":
                    source_bytes, source_format = self._synthesize_with_xiaomi_mimo(
                        text=text,
                        voice=voice,
                        requested_voice_id=requested_voice_id,
                        response_format=normalized_format,
                    )
                elif backend == "espeak":
                    source_bytes = self._synthesize_with_espeak(text, speed=speed)
                elif backend == "requesty":
                    source_bytes, source_format = self._synthesize_with_openai_compatible(
                        backend="requesty",
                        api_key=self.settings.requesty_api_token,
                        base_url=self.settings.requesty_tts_base_url,
                        model=self.settings.requesty_tts_model,
                        default_voice=self.settings.requesty_tts_voice,
                        text=text,
                        voice=voice,
                        requested_voice_id=requested_voice_id,
                        speed=speed,
                        response_format=normalized_format,
                    )
                elif backend == "openai":
                    source_bytes, source_format = self._synthesize_with_openai_compatible(
                        backend="openai",
                        api_key=self.settings.openai_api_key,
                        base_url=self.settings.openai_tts_base_url,
                        model=self.settings.openai_tts_model,
                        default_voice=self.settings.openai_tts_voice,
                        text=text,
                        voice=voice,
                        requested_voice_id=requested_voice_id,
                        speed=speed,
                        response_format=normalized_format,
                    )
                elif backend == "elevenlabs":
                    source_bytes, source_format = self._synthesize_with_elevenlabs(
                        text,
                        voice,
                        requested_voice_id=requested_voice_id,
                        speed=speed,
                    )
                else:
                    failures.append(f"{backend}: unsupported backend")
                    continue

                if source_bytes is None:
                    failures.append(f"{backend}: unavailable")
                    continue

                self.last_backend = backend
                output_bytes = convert_audio_bytes(
                    source_bytes,
                    source_format=source_format,
                    target_format=normalized_format,
                    ffmpeg_bin=self.settings.ffmpeg_bin,
                    audio_filters=output_postprocess_filters,
                )
                return output_bytes, normalized_format
            except Exception as exc:
                failures.append(f"{backend}: {exc}")

        raise RuntimeError(
            "No TTS backend available. " + "; ".join(failures)
            if failures
            else "No TTS backend available. Install MeloTTS or espeak-ng."
        )


class StubTtsEngine:
    def __init__(self, audio_bytes: bytes | None = None, *, audio_format: str = "mp3"):
        self.audio_bytes = audio_bytes or b"ID3stub-audio"
        self.audio_format = audio_format
        self.calls: list[dict[str, Any]] = []
        self.last_backend = "stub"

    def synthesize(
        self,
        text: str,
        *,
        voice: VoiceProfile,
        response_format: str = "mp3",
        speed: float = 1.0,
        language: str | None = None,
        requested_voice_id: str | None = None,
    ) -> tuple[bytes, str]:
        self.calls.append(
            {
                "text": text,
                "voice": voice.id,
                "requested_voice_id": requested_voice_id,
                "response_format": response_format,
                "speed": speed,
                "language": language,
            }
        )
        return self.audio_bytes, normalize_audio_format(response_format or self.audio_format)

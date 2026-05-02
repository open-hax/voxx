from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import math
import re
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .audio_utils import convert_audio_bytes, normalize_audio_format
from .catalog import VoiceProfile
from .config import Settings, get_settings


_SEGMENT_JP_PATTERN = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]+")
_PROMPT_AWARE_BREAK_TAG_PATTERN = re.compile(r"<break\b(?P<attrs>[^>]*)/?>", re.IGNORECASE)
_PROMPT_AWARE_TAG_PATTERN = re.compile(
    r"<break\b(?P<break_attrs>[^>]*)/?>|\[(?P<bracket_tag>[a-z][a-z0-9_-]*)(?:\s+[^\]]*)?\]",
    re.IGNORECASE,
)
_PROMPT_AWARE_BRACKET_TAG_PATTERN = re.compile(r"\[(?P<tag>[a-z][a-z0-9_-]*)(?:\s+[^\]]*)?\]", re.IGNORECASE)
_PROMPT_AWARE_TIME_PATTERN = re.compile(r"time\s*=\s*['\"]?(?P<value>[0-9.]+)\s*(?P<unit>ms|s)?", re.IGNORECASE)
_PROMPT_AWARE_PAUSE_TAGS = {"pause", "break", "silence"}
_PROMPT_AWARE_DIRECTION_TAGS = {
    "angry",
    "calm",
    "cheerful",
    "dramatic",
    "excited",
    "laugh",
    "laughing",
    "sad",
    "serious",
    "shout",
    "shouting",
    "sing",
    "singing",
    "soft",
    "stretch",
    "stretched",
    "suture",
    "sutured",
    "autotune",
    "glitch",
    "whisper",
    "whispering",
}
_TTS_MODEL_LOCK = threading.Lock()
_TTS_MODELS: dict[str, Any] | None | bool = None
_PROMPT_AWARE_LOG = logging.getLogger("voice_gateway.tts.prompt_aware")


@dataclass(frozen=True)
class PromptAwareSegment:
    kind: str
    text: str = ""
    style: str = ""
    pause_ms: int = 0


def _prompt_log_preview(text: str, limit: int = 240) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit]}…"


def _prompt_log_json(event: str, payload: dict[str, Any]) -> None:
    # Use warning level intentionally: production uvicorn configs often suppress
    # library INFO logs, and prompt-aware tag leaks need to be visible by default.
    _PROMPT_AWARE_LOG.warning(
        "voxx.%s %s",
        event,
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
    )


def _contains_prompt_markup(text: str) -> bool:
    return bool(_PROMPT_AWARE_TAG_PATTERN.search(text))


def _normalized_prompt_tag(tag: str) -> str:
    return tag.strip().lower().replace("_", "-")


def _clean_prompt_aware_text(text: str) -> str:
    cleaned = re.sub(r"[ \t]+", " ", text)
    cleaned = re.sub(r"\s+([,;:!?])", r"\1", cleaned)
    cleaned = re.sub(r"\s+(\.(?!\.))", r"\1", cleaned)
    return cleaned.strip()


def _break_pause_ms(attrs: str | None) -> int:
    match = _PROMPT_AWARE_TIME_PATTERN.search(str(attrs or ""))
    if not match:
        return 450
    try:
        value = float(match.group("value"))
    except ValueError:
        return 450
    unit = (match.group("unit") or "ms").lower()
    ms = value * 1000.0 if unit == "s" else value
    return int(max(80, min(2500, round(ms))))


def _append_prompt_text_segment(segments: list[PromptAwareSegment], text: str, style: str) -> None:
    cleaned = _clean_prompt_aware_text(text)
    if cleaned and not (cleaned in {".", ",", ";", ":", "!", "?"} and segments and segments[-1].kind in {"pause", "effect"}):
        segments.append(PromptAwareSegment(kind="text", text=cleaned, style=style))


def _parse_prompt_aware_segments(text: str) -> tuple[list[PromptAwareSegment], bool]:
    """Consume performance tags into a Voxx-owned render plan.

    Known bracket tags are never forwarded as spoken text. Direction tags style
    following text segments; pause/break tags become explicit silence segments;
    unknown tags are preserved literally so callers can still intentionally speak
    bracketed non-performance content.
    """

    segments: list[PromptAwareSegment] = []
    current_style = ""
    cursor = 0
    consumed_any = False

    for match in _PROMPT_AWARE_TAG_PATTERN.finditer(text):
        _append_prompt_text_segment(segments, text[cursor:match.start()], current_style)
        cursor = match.end()
        if match.group("break_attrs") is not None:
            segments.append(PromptAwareSegment(kind="pause", pause_ms=_break_pause_ms(match.group("break_attrs"))))
            consumed_any = True
            continue

        tag = _normalized_prompt_tag(match.group("bracket_tag") or "")
        if tag in _PROMPT_AWARE_PAUSE_TAGS:
            segments.append(PromptAwareSegment(kind="pause", pause_ms=350))
            consumed_any = True
        elif tag in {"laugh", "laughing"}:
            segments.append(PromptAwareSegment(kind="effect", style="laugh", pause_ms=180))
            consumed_any = True
        elif tag in _PROMPT_AWARE_DIRECTION_TAGS:
            current_style = tag
            consumed_any = True
        else:
            _append_prompt_text_segment(segments, match.group(0), current_style)

    _append_prompt_text_segment(segments, text[cursor:], current_style)
    return segments, consumed_any


def _flatten_prompt_aware_segments(segments: list[PromptAwareSegment]) -> str:
    parts: list[str] = []
    for segment in segments:
        if segment.kind == "text" and segment.text:
            parts.append(segment.text)
        elif segment.kind in {"pause", "effect"}:
            parts.append("...")
    return _clean_prompt_aware_text(" ".join(parts))


def prompt_aware_render_plan(text: str) -> dict[str, Any]:
    """Return the clean read-aloud prompt plus Voxx-owned inflection points.

    This is the contract boundary for prompt-aware markup: callers can verify
    that known tags have been removed from the text sent to TTS and represented
    as timing/style/effect points for Voxx postprocessing instead.
    """

    segments, consumed = _parse_prompt_aware_segments(text)
    read_parts: list[str] = []
    plan_segments: list[dict[str, Any]] = []
    inflection_points: list[dict[str, Any]] = []
    cursor = 0

    for segment_index, segment in enumerate(segments):
        if segment.kind == "text":
            if not segment.text:
                continue
            prefix = " " if read_parts else ""
            read_start = cursor + len(prefix)
            read_end = read_start + len(segment.text)
            read_parts.append(f"{prefix}{segment.text}")
            cursor = read_end
            plan_segment = {
                "kind": "text",
                "text": segment.text,
                "style": segment.style,
                "read_start": read_start,
                "read_end": read_end,
            }
            plan_segments.append(plan_segment)
            if segment.style:
                inflection_points.append(
                    {
                        "kind": "style",
                        "style": segment.style,
                        "segment_index": segment_index,
                        "read_start": read_start,
                        "read_end": read_end,
                    }
                )
        elif segment.kind == "pause":
            plan_segments.append({"kind": "pause", "pause_ms": segment.pause_ms, "read_position": cursor})
            inflection_points.append(
                {
                    "kind": "pause",
                    "pause_ms": segment.pause_ms,
                    "segment_index": segment_index,
                    "read_position": cursor,
                }
            )
        elif segment.kind == "effect":
            plan_segments.append({"kind": "effect", "style": segment.style, "duration_ms": segment.pause_ms, "read_position": cursor})
            inflection_points.append(
                {
                    "kind": "effect",
                    "style": segment.style,
                    "duration_ms": segment.pause_ms,
                    "segment_index": segment_index,
                    "read_position": cursor,
                }
            )

    updated_prompt = _clean_prompt_aware_text("".join(read_parts))
    return {
        "updated_prompt": updated_prompt,
        "read_aloud_text": updated_prompt,
        "consumed_tags": consumed,
        "segments": plan_segments,
        "inflection_points": inflection_points,
    }


def _sanitize_prompt_aware_text_for_non_prompt_backend(text: str) -> str:
    """Compatibility wrapper: consume tags and return non-marked spoken text."""

    segments, consumed = _parse_prompt_aware_segments(text)
    if consumed:
        return _flatten_prompt_aware_segments(segments)

    def bracket_replacement(match: re.Match[str]) -> str:
        tag = match.group("tag").strip().lower().replace("_", "-")
        if tag in _PROMPT_AWARE_PAUSE_TAGS:
            return " ... "
        if tag in _PROMPT_AWARE_DIRECTION_TAGS:
            return " "
        return match.group(0)

    sanitized = _PROMPT_AWARE_BREAK_TAG_PATTERN.sub(" ... ", text)
    sanitized = _PROMPT_AWARE_BRACKET_TAG_PATTERN.sub(bracket_replacement, sanitized)
    sanitized = re.sub(r"[ \t]+", " ", sanitized)
    sanitized = re.sub(r"\s+([,.;:!?])", r"\1", sanitized)
    sanitized = re.sub(r"([.!?])\s+\.\.\.\s+", r"\1 ... ", sanitized)
    return sanitized.strip()


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

    def _build_output_postprocess_filter_chain(self, *, requested_profile: str | None = None, enabled: bool | None = None) -> str:
        profile = self.settings.active_tts_postprocess_profile(requested_profile=requested_profile, enabled=enabled)
        if not profile:
            return ""
        if profile == "sutured-autotune-v1":
            # Opt-in musical/performance profile recovered from the Sovereign Suture
            # experiments: audible pitch/time character, vibrato, short echo, and
            # broadcast-safe leveling. Keep it profile-gated so normal narration is
            # not accidentally over-processed.
            return ",".join(
                [
                    "highpass=f=85",
                    "lowpass=f=12800",
                    "rubberband=pitch=1.055000",
                    "vibrato=f=5.400:d=0.045",
                    "aecho=0.62:0.36:58:0.20",
                    "equalizer=f=180:t=q:w=0.8:g=1.0",
                    "equalizer=f=2600:t=q:w=1.0:g=3.2",
                    "equalizer=f=5200:t=q:w=1.1:g=2.0",
                    "acompressor=threshold=0.17:ratio=3.2:attack=5:release=90:makeup=1.8:knee=2.5:link=average:detection=rms",
                    "alimiter=limit=0.92",
                    "volume=1.4dB",
                ]
            )
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
        if profile == "broadcast-warm-v1":
            return ",".join(
                [
                    "highpass=f=75",
                    "lowpass=f=14000",
                    "equalizer=f=180:t=q:w=0.9:g=1.2",
                    "equalizer=f=950:t=q:w=1.2:g=0.8",
                    "equalizer=f=3200:t=q:w=1.0:g=2.4",
                    "acompressor=threshold=0.20:ratio=2.6:attack=8:release=120:makeup=1.5:knee=3.0:link=average:detection=rms",
                    "alimiter=limit=0.94",
                    "volume=1.0dB",
                ]
            )
        if profile == "narrator-polish-v1":
            return ",".join(
                [
                    "highpass=f=65",
                    "lowpass=f=15000",
                    "equalizer=f=220:t=q:w=0.9:g=-0.7",
                    "equalizer=f=2800:t=q:w=1.1:g=1.8",
                    "equalizer=f=6500:t=q:w=1.2:g=0.9",
                    "acompressor=threshold=0.24:ratio=2.0:attack=12:release=160:makeup=1.0:knee=4.0:link=average:detection=rms",
                    "alimiter=limit=0.95",
                ]
            )
        if profile == "crisp-radio-v1":
            return ",".join(
                [
                    "highpass=f=120",
                    "lowpass=f=11000",
                    "equalizer=f=300:t=q:w=0.8:g=-1.2",
                    "equalizer=f=2500:t=q:w=1.0:g=3.2",
                    "equalizer=f=5200:t=q:w=1.0:g=3.0",
                    "acompressor=threshold=0.16:ratio=4.0:attack=4:release=70:makeup=2.2:knee=2.0:link=average:detection=rms",
                    "alimiter=limit=0.92",
                    "volume=1.5dB",
                ]
            )
        if profile == "soft-studio-v1":
            return ",".join(
                [
                    "highpass=f=60",
                    "lowpass=f=16000",
                    "equalizer=f=240:t=q:w=1.0:g=0.8",
                    "equalizer=f=3600:t=q:w=1.2:g=1.2",
                    "acompressor=threshold=0.28:ratio=1.8:attack=18:release=180:makeup=0.8:knee=5.0:link=average:detection=rms",
                    "alimiter=limit=0.96",
                    "volume=0.5dB",
                ]
            )
        return ""

    def _prompt_aware_style(self, *, enabled: bool | None = None, style: str | None = None) -> str:
        active = self.settings.tts_prompt_aware_default if enabled is None else enabled
        if not active:
            return ""
        requested_style = str(style or "").strip()
        return requested_style or self.settings.tts_prompt_aware_style

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
        prompt_aware_style: str = "",
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
                    request_payload: dict[str, object] = {
                        "model": model,
                        "input": text,
                        "voice": voice_id,
                        "response_format": request_format,
                        "speed": float(speed),
                    }
                    if prompt_aware_style and backend in {"requesty", "openai"}:
                        request_payload["instructions"] = prompt_aware_style
                    response = client.post(
                        base_url,
                        headers=headers,
                        json=request_payload,
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
        prompt_aware_style: str = "",
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
        style_parts = [self.settings.xiaomi_mimo_tts_style or "Speak naturally and clearly."]
        if prompt_aware_style:
            style_parts.append(prompt_aware_style)
        style = "\n\n".join(part for part in style_parts if part.strip())
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

    def _prompt_aware_performance_directive(self, style: str) -> dict[str, object]:
        normalized = _normalized_prompt_tag(style)
        directives: dict[str, dict[str, object]] = {
            "excited": {"pitch_ratio": 1.122462, "tempo_ratio": 1.08, "contour": "bright_major_second"},
            "cheerful": {"pitch_ratio": 1.090508, "tempo_ratio": 1.06, "contour": "smiling_major_second"},
            "dramatic": {"pitch_ratio": 0.943874, "tempo_ratio": 0.90, "contour": "low_minor_third"},
            "serious": {"pitch_ratio": 0.971532, "tempo_ratio": 0.94, "contour": "low_half_step"},
            "sing": {"pitch_ratio": 1.334840, "tempo_ratio": 0.96, "contour": "perfect_fourth_lift"},
            "singing": {"pitch_ratio": 1.334840, "tempo_ratio": 0.96, "contour": "perfect_fourth_lift"},
            "autotune": {"pitch_ratio": 1.259921, "tempo_ratio": 0.98, "contour": "major_third_lift"},
            "suture": {"pitch_ratio": 1.189207, "tempo_ratio": 0.95, "contour": "minor_third_suture"},
            "sutured": {"pitch_ratio": 1.189207, "tempo_ratio": 0.95, "contour": "minor_third_suture"},
            "stretch": {"pitch_ratio": 0.890899, "tempo_ratio": 0.82, "contour": "stretched_whole_step_down"},
            "stretched": {"pitch_ratio": 0.890899, "tempo_ratio": 0.82, "contour": "stretched_whole_step_down"},
            "glitch": {"pitch_ratio": 1.414214, "tempo_ratio": 1.12, "contour": "tritone_glitch"},
        }
        return directives.get(normalized, {})

    def _prompt_aware_segment_filter_chain(self, style: str) -> str:
        normalized = _normalized_prompt_tag(style)
        performance = self._prompt_aware_performance_directive(normalized)
        filters: list[str] = []
        if performance:
            filters.append(f"rubberband=pitch={float(performance['pitch_ratio']):.6f}")
            filters.append(f"atempo={float(performance['tempo_ratio']):.6f}")
            if normalized in {"sing", "singing", "autotune", "suture", "sutured"}:
                filters.append("vibrato=f=5.600:d=0.055")
            if normalized == "glitch":
                filters.extend(["aecho=0.55:0.32:42:0.24", "acrusher=level_in=1:level_out=0.82:bits=11:mode=log"])
        if normalized == "excited" or normalized == "cheerful":
            filters.extend(
                [
                    "equalizer=f=3200:t=q:w=1.0:g=2.0",
                    "equalizer=f=6200:t=q:w=1.2:g=1.0",
                    "volume=1.8dB",
                ]
            )
            return ",".join(filters)
        if normalized == "dramatic" or normalized == "serious":
            filters.extend(
                [
                    "equalizer=f=180:t=q:w=1.0:g=1.2",
                    "equalizer=f=1800:t=q:w=1.1:g=0.8",
                    "volume=1.1dB",
                ]
            )
            return ",".join(filters)
        if normalized == "whisper" or normalized == "whispering":
            return ",".join(
                [
                    "atempo=0.96",
                    "highpass=f=160",
                    "lowpass=f=6200",
                    "equalizer=f=3600:t=q:w=1.4:g=2.4",
                    "volume=-4.5dB",
                ]
            )
        if normalized == "shout" or normalized == "shouting":
            return ",".join(
                [
                    "atempo=1.03",
                    "equalizer=f=2600:t=q:w=1.0:g=3.0",
                    "acompressor=threshold=0.16:ratio=3.0:attack=4:release=80:makeup=1.5",
                    "volume=2.5dB",
                ]
            )
        if normalized == "calm" or normalized == "soft" or normalized == "sad":
            return ",".join(
                [
                    "atempo=0.96",
                    "equalizer=f=3000:t=q:w=1.2:g=-0.8",
                    "volume=-1.0dB",
                ]
            )
        if normalized == "angry":
            return ",".join(
                [
                    "atempo=1.02",
                    "equalizer=f=900:t=q:w=1.0:g=1.4",
                    "equalizer=f=3000:t=q:w=1.0:g=2.4",
                    "acompressor=threshold=0.15:ratio=3.5:attack=3:release=70:makeup=1.8",
                    "volume=2.0dB",
                ]
            )
        if performance:
            if normalized in {"sing", "singing", "autotune", "suture", "sutured"}:
                filters.extend(
                    [
                        "aecho=0.58:0.34:64:0.18",
                        "equalizer=f=2400:t=q:w=1.0:g=2.6",
                        "acompressor=threshold=0.18:ratio=2.8:attack=6:release=90:makeup=1.6",
                        "volume=1.6dB",
                    ]
                )
            elif normalized in {"stretch", "stretched"}:
                filters.extend(["aecho=0.48:0.28:92:0.18", "lowpass=f=9200", "volume=0.6dB"])
            return ",".join(filters)
        return ""

    def _synthesize_backend_source(
        self,
        backend: str,
        text: str,
        *,
        voice: VoiceProfile,
        normalized_format: str,
        speed: float,
        language: str | None,
        requested_voice_id: str | None,
        prompt_aware_style: str = "",
    ) -> tuple[bytes | None, str]:
        if backend == "melo":
            return self._synthesize_with_melo(text, voice, speed=speed, language=language), "wav"
        if backend == "kokoro":
            return self._synthesize_with_openai_compatible(
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
                prompt_aware_style=prompt_aware_style,
            )
        if backend == "xiaomi_mimo":
            return self._synthesize_with_xiaomi_mimo(
                text=text,
                voice=voice,
                requested_voice_id=requested_voice_id,
                response_format=normalized_format,
                prompt_aware_style=prompt_aware_style,
            )
        if backend == "espeak":
            return self._synthesize_with_espeak(text, speed=speed), "wav"
        if backend == "requesty":
            return self._synthesize_with_openai_compatible(
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
                prompt_aware_style=prompt_aware_style,
            )
        if backend == "openai":
            return self._synthesize_with_openai_compatible(
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
                prompt_aware_style=prompt_aware_style,
            )
        raise RuntimeError(f"{backend}: unsupported backend")

    def _prompt_aware_audio_segment(self, audio_bytes: bytes, source_format: str, style: str, pydub_module: Any) -> Any:
        styled_bytes = convert_audio_bytes(
            audio_bytes,
            source_format=source_format,
            target_format="wav",
            ffmpeg_bin=self.settings.ffmpeg_bin,
            audio_filters=self._prompt_aware_segment_filter_chain(style),
        )
        try:
            return pydub_module.AudioSegment.from_file(io.BytesIO(styled_bytes), format="wav")
        except Exception:
            return pydub_module.AudioSegment.from_file(io.BytesIO(audio_bytes), format=source_format)

    def _prompt_aware_laugh_segment(self, pydub_module: Any, duration_ms: int) -> Any:
        try:
            from pydub.generators import WhiteNoise

            noise = WhiteNoise().to_audio_segment(duration=duration_ms)
            return noise.high_pass_filter(600).low_pass_filter(4200).apply_gain(-30).fade_in(20).fade_out(80)
        except Exception:
            return pydub_module.AudioSegment.silent(duration=duration_ms)

    def _synthesize_prompt_aware_with_backend(
        self,
        backend: str,
        segments: list[PromptAwareSegment],
        *,
        voice: VoiceProfile,
        normalized_format: str,
        speed: float,
        language: str | None,
        requested_voice_id: str | None,
        render_id: str = "",
    ) -> tuple[bytes | None, str]:
        try:
            import pydub
        except Exception:
            flattened_text = _flatten_prompt_aware_segments(segments)
            _prompt_log_json(
                "prompt_aware.pydub_unavailable_flattened_fallback",
                {
                    "render_id": render_id,
                    "backend": backend,
                    "read_aloud_text_preview": _prompt_log_preview(flattened_text),
                    "contains_prompt_markup": _contains_prompt_markup(flattened_text),
                },
            )
            return self._synthesize_backend_source(
                backend,
                flattened_text,
                voice=voice,
                normalized_format=normalized_format,
                speed=speed,
                language=language,
                requested_voice_id=requested_voice_id,
                prompt_aware_style="",
            )

        combined = pydub.AudioSegment.empty()
        for segment_index, segment in enumerate(segments):
            if segment.kind == "pause":
                _prompt_log_json(
                    "prompt_aware.segment_pause",
                    {
                        "render_id": render_id,
                        "backend": backend,
                        "segment_index": segment_index,
                        "pause_ms": segment.pause_ms,
                    },
                )
                combined += pydub.AudioSegment.silent(duration=max(0, segment.pause_ms))
                continue
            if segment.kind == "effect" and segment.style == "laugh":
                _prompt_log_json(
                    "prompt_aware.segment_effect",
                    {
                        "render_id": render_id,
                        "backend": backend,
                        "segment_index": segment_index,
                        "style": segment.style,
                        "duration_ms": max(80, segment.pause_ms),
                    },
                )
                combined += self._prompt_aware_laugh_segment(pydub, max(80, segment.pause_ms))
                continue
            if segment.kind != "text" or not segment.text:
                continue
            performance_directive = self._prompt_aware_performance_directive(segment.style)
            synthesis_payload: dict[str, Any] = {
                "render_id": render_id,
                "backend": backend,
                "segment_index": segment_index,
                "style": segment.style,
                "text_preview": _prompt_log_preview(segment.text),
                "contains_prompt_markup": _contains_prompt_markup(segment.text),
            }
            if performance_directive:
                synthesis_payload["performance_directive"] = performance_directive
            _prompt_log_json("prompt_aware.segment_synthesis", synthesis_payload)
            source_bytes, source_format = self._synthesize_backend_source(
                backend,
                segment.text,
                voice=voice,
                normalized_format=normalized_format,
                speed=speed,
                language=language,
                requested_voice_id=requested_voice_id,
                prompt_aware_style="",
            )
            if source_bytes is None:
                return None, "wav"
            combined += self._prompt_aware_audio_segment(source_bytes, source_format, segment.style, pydub)

        if len(combined) == 0:
            return None, "wav"

        buffer = io.BytesIO()
        combined.export(buffer, format="wav")
        return buffer.getvalue(), "wav"

    def synthesize(
        self,
        text: str,
        *,
        voice: VoiceProfile,
        response_format: str = "mp3",
        speed: float = 1.0,
        language: str | None = None,
        requested_voice_id: str | None = None,
        postprocess_profile: str | None = None,
        postprocess_enabled: bool | None = None,
        prompt_aware: bool | None = None,
        prompt_aware_style: str | None = None,
    ) -> tuple[bytes, str]:
        normalized_format = normalize_audio_format(response_format or self.settings.default_audio_format)
        failures: list[str] = []
        self.last_backend = ""
        self.last_postprocess_profile = self.settings.active_tts_postprocess_profile(
            requested_profile=postprocess_profile,
            enabled=postprocess_enabled,
        )
        self.last_prompt_aware = bool(self._prompt_aware_style(enabled=prompt_aware, style=prompt_aware_style))
        output_postprocess_filters = self._build_output_postprocess_filter_chain(
            requested_profile=postprocess_profile,
            enabled=postprocess_enabled,
        )
        active_prompt_aware_style = self._prompt_aware_style(enabled=prompt_aware, style=prompt_aware_style)
        prompt_aware_segments, prompt_aware_tags_consumed = (
            _parse_prompt_aware_segments(text) if active_prompt_aware_style else ([], False)
        )
        prompt_aware_render_id = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
        if active_prompt_aware_style and prompt_aware_tags_consumed:
            render_plan = prompt_aware_render_plan(text)
            text_segment_count = sum(1 for segment in prompt_aware_segments if segment.kind == "text")
            _prompt_log_json(
                "prompt_aware.render_plan",
                {
                    "render_id": prompt_aware_render_id,
                    "requested_voice_id": requested_voice_id or voice.id,
                    "response_format": normalized_format,
                    "postprocess_profile": self.last_postprocess_profile or "none",
                    "raw_length": len(text),
                    "updated_prompt_preview": _prompt_log_preview(str(render_plan["updated_prompt"])),
                    "updated_prompt_length": len(str(render_plan["updated_prompt"])),
                    "updated_prompt_contains_prompt_markup": _contains_prompt_markup(str(render_plan["updated_prompt"])),
                    "segment_count": len(render_plan["segments"]),
                    "text_segment_count": text_segment_count,
                    "inflection_points": render_plan["inflection_points"],
                },
            )
        elif active_prompt_aware_style:
            _prompt_log_json(
                "prompt_aware.no_known_tags",
                {
                    "render_id": prompt_aware_render_id,
                    "requested_voice_id": requested_voice_id or voice.id,
                    "raw_length": len(text),
                    "text_preview": _prompt_log_preview(text),
                    "contains_prompt_markup": _contains_prompt_markup(text),
                },
            )

        for backend in self.settings.preferred_tts_backends():
            try:
                if prompt_aware_tags_consumed:
                    _prompt_log_json(
                        "prompt_aware.backend_attempt",
                        {"render_id": prompt_aware_render_id, "backend": backend},
                    )
                    source_bytes, source_format = self._synthesize_prompt_aware_with_backend(
                        backend,
                        prompt_aware_segments,
                        voice=voice,
                        normalized_format=normalized_format,
                        speed=speed,
                        language=language,
                        requested_voice_id=requested_voice_id,
                        render_id=prompt_aware_render_id,
                    )
                else:
                    source_bytes, source_format = self._synthesize_backend_source(
                        backend,
                        text,
                        voice=voice,
                        normalized_format=normalized_format,
                        speed=speed,
                        language=language,
                        requested_voice_id=requested_voice_id,
                        prompt_aware_style="",
                    )

                if source_bytes is None:
                    failures.append(f"{backend}: unavailable")
                    if prompt_aware_tags_consumed:
                        _prompt_log_json(
                            "prompt_aware.backend_unavailable",
                            {"render_id": prompt_aware_render_id, "backend": backend},
                        )
                    continue

                self.last_backend = backend
                if prompt_aware_tags_consumed:
                    _prompt_log_json(
                        "prompt_aware.backend_success",
                        {"render_id": prompt_aware_render_id, "backend": backend, "source_format": source_format},
                    )
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
                if prompt_aware_tags_consumed:
                    _prompt_log_json(
                        "prompt_aware.backend_error",
                        {
                            "render_id": prompt_aware_render_id,
                            "backend": backend,
                            "error": str(exc),
                        },
                    )

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
        self.last_postprocess_profile = ""
        self.last_prompt_aware = False

    def synthesize(
        self,
        text: str,
        *,
        voice: VoiceProfile,
        response_format: str = "mp3",
        speed: float = 1.0,
        language: str | None = None,
        requested_voice_id: str | None = None,
        postprocess_profile: str | None = None,
        postprocess_enabled: bool | None = None,
        prompt_aware: bool | None = None,
        prompt_aware_style: str | None = None,
    ) -> tuple[bytes, str]:
        self.last_postprocess_profile = str(postprocess_profile or "")
        self.last_prompt_aware = bool(prompt_aware)
        self.calls.append(
            {
                "text": text,
                "voice": voice.id,
                "requested_voice_id": requested_voice_id,
                "response_format": response_format,
                "speed": speed,
                "language": language,
                "postprocess_profile": postprocess_profile,
                "postprocess_enabled": postprocess_enabled,
                "prompt_aware": prompt_aware,
                "prompt_aware_style": prompt_aware_style,
            }
        )
        return self.audio_bytes, normalize_audio_format(response_format or self.audio_format)

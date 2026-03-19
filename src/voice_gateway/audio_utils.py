from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


AUDIO_FORMAT_CONTENT_TYPES = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "flac": "audio/flac",
    "opus": "audio/opus",
    "aac": "audio/aac",
    "pcm": "application/octet-stream",
}


AUDIO_FORMAT_EXTENSIONS = {
    "mp3": ".mp3",
    "wav": ".wav",
    "flac": ".flac",
    "opus": ".opus",
    "aac": ".aac",
    "pcm": ".pcm",
}


MIME_SUFFIXES = {
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/ogg": ".ogg",
    "audio/webm": ".webm",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/flac": ".flac",
    "audio/aac": ".aac",
}


def audio_suffix_for_mime(mime: str) -> str:
    normalized = mime.lower().split(";", 1)[0].strip()
    return MIME_SUFFIXES.get(normalized, ".webm")


def mime_for_audio_format(fmt: str) -> str:
    normalized = normalize_audio_format(fmt)
    return AUDIO_FORMAT_CONTENT_TYPES[normalized]


def normalize_audio_format(fmt: str | None) -> str:
    normalized = str(fmt or "mp3").strip().lower()
    if normalized in AUDIO_FORMAT_CONTENT_TYPES:
        return normalized
    if normalized.startswith("mp3"):
        return "mp3"
    if normalized.startswith("pcm"):
        return "pcm"
    if normalized.startswith("ulaw"):
        return "pcm"
    if normalized == "s16le":
        return "pcm"
    return "mp3"


def normalize_elevenlabs_output_format(value: str | None) -> str:
    if not value:
        return "mp3"
    normalized = value.strip().lower()
    if normalized.startswith("mp3"):
        return "mp3"
    if normalized.startswith("pcm"):
        return "pcm"
    if normalized.startswith("wav"):
        return "wav"
    if normalized.startswith("flac"):
        return "flac"
    if normalized.startswith("opus"):
        return "opus"
    if normalized.startswith("aac"):
        return "aac"
    return normalize_audio_format(normalized)


def convert_audio_bytes(
    audio_bytes: bytes,
    *,
    source_format: str,
    target_format: str,
    ffmpeg_bin: str,
) -> bytes:
    normalized_source = normalize_audio_format(source_format)
    normalized_target = normalize_audio_format(target_format)
    if normalized_source == normalized_target:
        return audio_bytes
    if not ffmpeg_bin:
        return audio_bytes

    source_suffix = AUDIO_FORMAT_EXTENSIONS[normalized_source]
    target_suffix = AUDIO_FORMAT_EXTENSIONS[normalized_target]

    with tempfile.TemporaryDirectory(prefix="voice_gateway_convert_") as temp_dir:
        temp_path = Path(temp_dir)
        source_path = temp_path / f"input{source_suffix}"
        target_path = temp_path / f"output{target_suffix}"
        source_path.write_bytes(audio_bytes)

        command = [
            ffmpeg_bin,
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(source_path),
        ]

        if normalized_target == "pcm":
            command += ["-f", "s16le", "-acodec", "pcm_s16le", "-ac", "1", "-ar", "24000"]
        command.append(str(target_path))

        try:
            subprocess.run(command, check=True, timeout=40)
        except (OSError, subprocess.SubprocessError):
            return audio_bytes

        if not target_path.exists():
            return audio_bytes
        return target_path.read_bytes()

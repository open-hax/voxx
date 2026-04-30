from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse, PlainTextResponse

from .types import TranscriptResult, TranscriptSegment


def _format_timestamp(seconds: float, *, srt: bool) -> str:
    whole_ms = max(0, int(round(seconds * 1000.0)))
    ms = whole_ms % 1000
    total_seconds = whole_ms // 1000
    sec = total_seconds % 60
    total_minutes = total_seconds // 60
    minute = total_minutes % 60
    hour = total_minutes // 60
    separator = "," if srt else "."
    return f"{hour:02d}:{minute:02d}:{sec:02d}{separator}{ms:03d}"


def _fallback_segments(result: TranscriptResult) -> list[TranscriptSegment]:
    if result.segments:
        return result.segments
    if not result.text.strip():
        return []
    duration = result.duration or 0.0
    return [TranscriptSegment(id=0, start=0.0, end=max(duration, 0.0), text=result.text.strip())]


def to_srt(result: TranscriptResult) -> str:
    lines: list[str] = []
    for index, segment in enumerate(_fallback_segments(result), start=1):
        lines.extend(
            [
                str(index),
                f"{_format_timestamp(segment.start, srt=True)} --> {_format_timestamp(segment.end, srt=True)}",
                segment.text,
                "",
            ]
        )
    return "\n".join(lines).strip() + ("\n" if lines else "")


def to_vtt(result: TranscriptResult) -> str:
    lines = ["WEBVTT", ""]
    for segment in _fallback_segments(result):
        lines.extend(
            [
                f"{_format_timestamp(segment.start, srt=False)} --> {_format_timestamp(segment.end, srt=False)}",
                segment.text,
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def openai_transcription_payload(
    result: TranscriptResult,
    *,
    response_format: str,
    model: str,
) -> JSONResponse | PlainTextResponse:
    normalized = str(response_format or "json").strip().lower()
    if normalized == "text":
        return PlainTextResponse(result.text)
    if normalized == "srt":
        return PlainTextResponse(to_srt(result), media_type="text/plain")
    if normalized == "vtt":
        return PlainTextResponse(to_vtt(result), media_type="text/vtt")
    if normalized == "verbose_json":
        payload: dict[str, Any] = {
            "task": result.task,
            "language": result.language or "",
            "duration": result.duration or 0.0,
            "text": result.text,
            "segments": [segment.to_dict() for segment in _fallback_segments(result)],
            "words": [],
            "model": model,
        }
        return JSONResponse(payload)
    return JSONResponse({"text": result.text})


def voice_transcription_payload(
    result: TranscriptResult,
    *,
    transcription_id: str,
    model_id: str,
) -> JSONResponse:
    return JSONResponse(
        {
            "transcription_id": transcription_id,
            "text": result.text,
            "language_code": result.language or "",
            "model_id": model_id,
            "duration_seconds": result.duration or 0.0,
            "segments": [segment.to_dict() for segment in _fallback_segments(result)],
            "words": [],
        }
    )

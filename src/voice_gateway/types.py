from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TranscriptSegment:
    id: int
    start: float
    end: float
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "start": self.start,
            "end": self.end,
            "text": self.text,
        }


@dataclass
class TranscriptResult:
    ok: bool
    engine: str
    text: str
    error: str | None = None
    language: str | None = None
    task: str = "transcribe"
    duration: float | None = None
    segments: list[TranscriptSegment] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "engine": self.engine,
            "text": self.text,
            "error": self.error,
            "language": self.language,
            "task": self.task,
            "duration": self.duration,
            "segments": [segment.to_dict() for segment in self.segments],
        }

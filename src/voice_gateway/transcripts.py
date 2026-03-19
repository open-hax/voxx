from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .types import TranscriptResult


@dataclass
class TranscriptRecord:
    transcription_id: str
    created_at: str
    source_name: str
    mime_type: str
    task: str
    model_id: str
    result: TranscriptResult

    def to_dict(self) -> dict[str, Any]:
        return {
            "transcription_id": self.transcription_id,
            "created_at": self.created_at,
            "source_name": self.source_name,
            "mime_type": self.mime_type,
            "task": self.task,
            "model_id": self.model_id,
            "result": self.result.to_dict(),
        }


class TranscriptStore:
    def __init__(self, transcript_dir: Path):
        self.transcript_dir = transcript_dir
        self.transcript_dir.mkdir(parents=True, exist_ok=True)

    def create(
        self,
        *,
        source_name: str,
        mime_type: str,
        task: str,
        model_id: str,
        result: TranscriptResult,
    ) -> TranscriptRecord:
        record = TranscriptRecord(
            transcription_id=f"tr_{uuid4().hex}",
            created_at=datetime.now(timezone.utc).isoformat(),
            source_name=source_name,
            mime_type=mime_type,
            task=task,
            model_id=model_id,
            result=result,
        )
        path = self.transcript_dir / f"{record.transcription_id}.json"
        path.write_text(json.dumps(record.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return record

    def get(self, transcription_id: str) -> dict[str, Any] | None:
        path = self.transcript_dir / f"{transcription_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

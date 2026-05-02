from __future__ import annotations

import importlib
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any

from .audio_utils import audio_suffix_for_mime
from .config import Settings, get_settings
from .types import TranscriptResult, TranscriptSegment


_WHISPER_MODEL_LOCK = threading.Lock()
_WHISPER_MODEL: Any = None


class LocalSttEngine:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def _maybe_convert_to_wav(self, path: Path) -> Path:
        if path.suffix.lower() == ".wav":
            return path
        if not self.settings.ffmpeg_bin:
            return path

        wav_path = path.with_suffix(".wav")
        command = [
            self.settings.ffmpeg_bin,
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-ar",
            "16000",
            "-ac",
            "1",
            str(wav_path),
        ]
        try:
            subprocess.run(command, check=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return path
        return wav_path if wav_path.exists() else path

    def _load_faster_whisper_model(self) -> Any:
        global _WHISPER_MODEL
        with _WHISPER_MODEL_LOCK:
            if _WHISPER_MODEL is False:
                return None
            if _WHISPER_MODEL is not None:
                return _WHISPER_MODEL
            try:
                module = importlib.import_module("faster_whisper")
                whisper_model = getattr(module, "WhisperModel")
            except Exception:
                _WHISPER_MODEL = False
                return None

            try:
                _WHISPER_MODEL = whisper_model(
                    self.settings.stt_faster_whisper_model,
                    device=self.settings.stt_faster_whisper_device,
                    compute_type=self.settings.stt_faster_whisper_compute_type,
                )
            except Exception:
                _WHISPER_MODEL = False
                return None
            return _WHISPER_MODEL

    def _transcribe_with_faster_whisper(
        self,
        path: Path,
        *,
        language: str | None,
        task: str,
    ) -> TranscriptResult | None:
        model = self._load_faster_whisper_model()
        if model is None:
            return None
        try:
            segments, info = model.transcribe(
                str(path),
                language=language or None,
                task=task,
                vad_filter=True,
                beam_size=1,
            )
            normalized_segments: list[TranscriptSegment] = []
            text_parts: list[str] = []
            for index, segment in enumerate(segments):
                piece = str(getattr(segment, "text", "") or "").strip()
                if not piece:
                    continue
                text_parts.append(piece)
                normalized_segments.append(
                    TranscriptSegment(
                        id=index,
                        start=float(getattr(segment, "start", 0.0) or 0.0),
                        end=float(getattr(segment, "end", 0.0) or 0.0),
                        text=piece,
                    )
                )
        except Exception as exc:
            return TranscriptResult(
                ok=False,
                engine="faster-whisper",
                text="",
                error=f"error:{exc.__class__.__name__}",
                language=language,
                task=task,
            )

        text = " ".join(text_parts).strip()
        if not text:
            return TranscriptResult(
                ok=False,
                engine="faster-whisper",
                text="",
                error="no-speech",
                language=language,
                task=task,
            )

        detected_language = str(getattr(info, "language", language or "") or language or "")
        duration = float(getattr(info, "duration", normalized_segments[-1].end if normalized_segments else 0.0) or 0.0)
        return TranscriptResult(
            ok=True,
            engine="faster-whisper",
            text=text,
            error=None,
            language=detected_language,
            task=task,
            duration=duration,
            segments=normalized_segments,
        )

    def _transcribe_with_whisper_cpp(
        self,
        path: Path,
        *,
        language: str | None,
        task: str,
    ) -> TranscriptResult | None:
        model_path = self.settings.whisper_cpp_model.strip()
        if not model_path:
            return None

        executable = (
            self.settings.whisper_cpp_bin
            if Path(self.settings.whisper_cpp_bin).exists()
            else shutil.which(self.settings.whisper_cpp_bin)
        )
        if not executable:
            return None

        wav_path = self._maybe_convert_to_wav(path)
        out_base = wav_path.with_suffix("")
        command = [
            str(executable),
            "-m",
            model_path,
            "-f",
            str(wav_path),
            "-otxt",
            "-of",
            str(out_base),
        ]
        if language:
            command += ["-l", language]
        if task == "translate":
            command.append("-tr")

        try:
            subprocess.run(command, check=True, timeout=120)
        except (OSError, subprocess.SubprocessError):
            return TranscriptResult(
                ok=False,
                engine="whisper.cpp",
                text="",
                error="exec-failed",
                language=language,
                task=task,
            )

        text_path = out_base.with_suffix(".txt")
        if not text_path.exists():
            return TranscriptResult(
                ok=False,
                engine="whisper.cpp",
                text="",
                error="no-output",
                language=language,
                task=task,
            )
        text = text_path.read_text(encoding="utf-8", errors="ignore").strip()
        if not text:
            return TranscriptResult(
                ok=False,
                engine="whisper.cpp",
                text="",
                error="no-speech",
                language=language,
                task=task,
            )
        return TranscriptResult(
            ok=True,
            engine="whisper.cpp",
            text=text,
            error=None,
            language=language,
            task=task,
            duration=None,
            segments=[],
        )

    def transcribe(
        self,
        audio_bytes: bytes,
        *,
        mime: str = "audio/webm",
        language: str | None = None,
        task: str = "transcribe",
    ) -> TranscriptResult:
        if not self.settings.stt_enabled:
            return TranscriptResult(
                ok=False,
                engine="disabled",
                text="",
                error="Voxx STT is disabled. Use the external Knoxx NPU STT service or set VOICE_GATEWAY_STT_ENABLED=1 to opt in.",
                language=language,
                task=task,
            )

        if not audio_bytes:
            return TranscriptResult(
                ok=False,
                engine="none",
                text="",
                error="empty audio payload",
                language=language,
                task=task,
            )

        suffix = audio_suffix_for_mime(mime)
        with tempfile.TemporaryDirectory(prefix="voice_gateway_stt_") as temp_dir:
            source_path = Path(temp_dir) / f"input{suffix}"
            source_path.write_bytes(audio_bytes)
            prepared = self._maybe_convert_to_wav(source_path)

            result = self._transcribe_with_faster_whisper(prepared, language=language, task=task)
            if result and result.ok:
                return result
            if result and result.error and result.error != "unavailable":
                return result

            result = self._transcribe_with_whisper_cpp(prepared, language=language, task=task)
            if result and result.ok:
                return result
            if result:
                return result

        return TranscriptResult(
            ok=False,
            engine="none",
            text="",
            error="No STT backend active. Install faster-whisper or set WHISPER_CPP_MODEL.",
            language=language,
            task=task,
        )


class StubSttEngine:
    def __init__(self, text: str = "stub transcript", *, language: str = "en", engine: str = "stub-stt"):
        self.text = text
        self.language = language
        self.engine = engine
        self.calls: list[dict[str, Any]] = []

    def transcribe(
        self,
        audio_bytes: bytes,
        *,
        mime: str = "audio/webm",
        language: str | None = None,
        task: str = "transcribe",
    ) -> TranscriptResult:
        self.calls.append({
            "size": len(audio_bytes),
            "mime": mime,
            "language": language,
            "task": task,
        })
        return TranscriptResult(
            ok=True,
            engine=self.engine,
            text=self.text if task != "translate" else f"translated:{self.text}",
            error=None,
            language=language or self.language,
            task=task,
            duration=1.25,
            segments=[TranscriptSegment(id=0, start=0.0, end=1.25, text=self.text if task != "translate" else f"translated:{self.text}")],
        )

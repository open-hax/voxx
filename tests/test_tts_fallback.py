from __future__ import annotations

from pathlib import Path

from voice_gateway.catalog import resolve_voice
from voice_gateway.config import Settings
from voice_gateway import tts as tts_module
from voice_gateway.tts import LocalTtsEngine


def test_settings_backend_order_prefers_configured_remote_backends(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "runtime",
        requesty_api_token="requesty-token",
        openai_api_key="openai-key",
    )

    assert settings.preferred_tts_backends() == ("requesty", "openai", "melo", "espeak")


def test_settings_backend_order_respects_explicit_override(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "runtime",
        tts_backend_order=("melo", "requesty", "espeak", "melo"),
    )

    assert settings.preferred_tts_backends() == ("melo", "requesty", "espeak")


def test_local_tts_engine_falls_back_after_remote_error(tmp_path: Path, monkeypatch) -> None:
    settings = Settings(
        data_dir=tmp_path / "runtime",
        requesty_api_token="requesty-token",
        tts_backend_order=("requesty", "melo", "espeak"),
        ffmpeg_bin="",
    )
    engine = LocalTtsEngine(settings)
    voice = resolve_voice("nova")

    monkeypatch.setattr(
        engine,
        "_synthesize_with_openai_compatible",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("requesty down")),
    )
    monkeypatch.setattr(engine, "_synthesize_with_melo", lambda *_args, **_kwargs: b"wav-local")
    monkeypatch.setattr(engine, "_synthesize_with_espeak", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tts_module, "convert_audio_bytes", lambda audio_bytes, **_kwargs: audio_bytes)

    audio_bytes, fmt = engine.synthesize(
        "fallback me",
        voice=voice,
        response_format="mp3",
        requested_voice_id="custom-voice",
    )

    assert audio_bytes == b"wav-local"
    assert fmt == "mp3"
    assert engine.last_backend == "melo"


def test_remote_voice_candidates_preserve_requested_id_for_elevenlabs(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "runtime", elevenlabs_voice_id="env-eleven-default")
    engine = LocalTtsEngine(settings)
    voice = resolve_voice("nova")

    candidates = engine._remote_voice_candidates(
        voice,
        backend="elevenlabs",
        requested_voice_id="voice_abc123",
        default_voice=settings.elevenlabs_voice_id,
    )

    assert candidates == ["voice_abc123", "env-eleven-default"]

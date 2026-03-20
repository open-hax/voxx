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


def test_sports_commentator_postprocess_applies_to_remote_outputs(tmp_path: Path, monkeypatch) -> None:
    settings = Settings(
        data_dir=tmp_path / "runtime",
        requesty_api_token="requesty-token",
        tts_backend_order=("requesty",),
        ffmpeg_bin="/usr/bin/ffmpeg",
        tts_postprocess_enabled=True,
        tts_postprocess_profile="sports",
    )
    engine = LocalTtsEngine(settings)
    voice = resolve_voice("nova")

    monkeypatch.setattr(
        engine,
        "_synthesize_with_openai_compatible",
        lambda **_kwargs: (b"remote-mp3", "mp3"),
    )
    captured: dict[str, str] = {}

    def fake_convert(audio_bytes: bytes, **kwargs):
        captured["source_format"] = kwargs["source_format"]
        captured["target_format"] = kwargs["target_format"]
        captured["audio_filters"] = kwargs.get("audio_filters", "")
        return audio_bytes

    monkeypatch.setattr(tts_module, "convert_audio_bytes", fake_convert)

    audio_bytes, fmt = engine.synthesize(
        "goal from downtown",
        voice=voice,
        response_format="mp3",
        requested_voice_id="custom-voice",
    )

    assert audio_bytes == b"remote-mp3"
    assert fmt == "mp3"
    assert captured["source_format"] == "mp3"
    assert captured["target_format"] == "mp3"
    assert "acompressor=" in captured["audio_filters"]
    assert "equalizer=" in captured["audio_filters"]
    assert "alimiter=" in captured["audio_filters"]


def test_postprocess_can_be_disabled(tmp_path: Path, monkeypatch) -> None:
    settings = Settings(
        data_dir=tmp_path / "runtime",
        requesty_api_token="requesty-token",
        tts_backend_order=("requesty",),
        ffmpeg_bin="/usr/bin/ffmpeg",
        tts_postprocess_enabled=False,
    )
    engine = LocalTtsEngine(settings)
    voice = resolve_voice("nova")

    monkeypatch.setattr(
        engine,
        "_synthesize_with_openai_compatible",
        lambda **_kwargs: (b"remote-mp3", "mp3"),
    )
    captured: dict[str, str] = {}

    def fake_convert(audio_bytes: bytes, **kwargs):
        captured["audio_filters"] = kwargs.get("audio_filters", "")
        return audio_bytes

    monkeypatch.setattr(tts_module, "convert_audio_bytes", fake_convert)

    audio_bytes, fmt = engine.synthesize(
        "hold the line",
        voice=voice,
        response_format="mp3",
        requested_voice_id="custom-voice",
    )

    assert audio_bytes == b"remote-mp3"
    assert fmt == "mp3"
    assert captured["audio_filters"] == ""

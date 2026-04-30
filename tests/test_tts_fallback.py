from __future__ import annotations

import base64
from pathlib import Path

import httpx

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

    assert settings.preferred_tts_backends() == ("kokoro", "requesty", "openai", "melo", "espeak")


def test_settings_backend_order_respects_explicit_override(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "runtime",
        tts_backend_order=("melo", "requesty", "espeak", "melo"),
    )

    assert settings.preferred_tts_backends() == ("melo", "requesty", "espeak")


def test_settings_backend_order_prefers_xiaomi_mimo_when_configured(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "runtime",
        xiaomi_mimo_api_key="mimo-token",
        requesty_api_token="requesty-token",
    )

    assert settings.preferred_tts_backends() == ("kokoro", "xiaomi_mimo", "requesty", "melo", "espeak")


def test_kokoro_openai_compatible_backend_does_not_require_api_key(tmp_path: Path, monkeypatch) -> None:
    settings = Settings(
        data_dir=tmp_path / "runtime",
        kokoro_api_key="",
        kokoro_tts_base_url="http://kokoro.test/v1/audio/speech",
        tts_backend_order=("kokoro",),
        ffmpeg_bin="",
    )
    engine = LocalTtsEngine(settings)
    voice = resolve_voice("alloy")
    captured: dict[str, object] = {}

    class FakeResponse:
        content = b"kokoro-mp3"

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, timeout: float):
            captured["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr(tts_module.httpx, "Client", FakeClient)
    monkeypatch.setattr(tts_module, "convert_audio_bytes", lambda audio_bytes, **_kwargs: audio_bytes)

    audio_bytes, fmt = engine.synthesize(
        "kokoro hello",
        voice=voice,
        response_format="mp3",
        requested_voice_id="af_heart",
    )

    assert audio_bytes == b"kokoro-mp3"
    assert fmt == "mp3"
    assert engine.last_backend == "kokoro"
    assert captured["url"] == "http://kokoro.test/v1/audio/speech"
    assert captured["headers"] == {"Content-Type": "application/json"}


def test_xiaomi_mimo_tts_uses_chat_audio_bridge(tmp_path: Path, monkeypatch) -> None:
    settings = Settings(
        data_dir=tmp_path / "runtime",
        xiaomi_mimo_api_key="mimo-token",
        xiaomi_mimo_api_base_url="https://mimo.test/v1",
        xiaomi_mimo_tts_model="mimo-v2.5-tts",
        xiaomi_mimo_tts_voice="mimo_default",
        xiaomi_mimo_tts_style="Speak warmly.",
        tts_backend_order=("xiaomi_mimo",),
        ffmpeg_bin="",
    )
    engine = LocalTtsEngine(settings)
    voice = resolve_voice("alloy")
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "choices": [
                    {
                        "message": {
                            "audio": {"data": base64.b64encode(b"mimo-mp3").decode("ascii")}
                        }
                    }
                ]
            }

    class FakeClient:
        def __init__(self, timeout: float):
            captured["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr(tts_module.httpx, "Client", FakeClient)
    monkeypatch.setattr(tts_module, "convert_audio_bytes", lambda audio_bytes, **_kwargs: audio_bytes)

    audio_bytes, fmt = engine.synthesize(
        "mimo hello",
        voice=voice,
        response_format="mp3",
        requested_voice_id="Mia",
    )

    assert audio_bytes == b"mimo-mp3"
    assert fmt == "mp3"
    assert engine.last_backend == "xiaomi_mimo"
    assert captured["url"] == "https://mimo.test/v1/chat/completions"
    assert captured["headers"] == {
        "Authorization": "Bearer mimo-token",
        "api-key": "mimo-token",
        "Content-Type": "application/json",
    }
    assert captured["json"] == {
        "model": "mimo-v2.5-tts",
        "messages": [
            {"role": "user", "content": "Speak warmly."},
            {"role": "assistant", "content": "mimo hello"},
        ],
        "audio": {"voice": "Mia", "format": "mp3"},
    }


def test_xiaomi_mimo_prompt_aware_appends_performance_style(tmp_path: Path, monkeypatch) -> None:
    settings = Settings(
        data_dir=tmp_path / "runtime",
        xiaomi_mimo_api_key="mimo-token",
        xiaomi_mimo_api_base_url="https://mimo.test/v1",
        xiaomi_mimo_tts_style="Speak warmly.",
        tts_backend_order=("xiaomi_mimo",),
        ffmpeg_bin="",
    )
    engine = LocalTtsEngine(settings)
    voice = resolve_voice("alloy")
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"choices": [{"message": {"audio": {"data": base64.b64encode(b"mimo-mp3").decode("ascii")}}}]}

    class FakeClient:
        def __init__(self, timeout: float):
            captured["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]):
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr(tts_module.httpx, "Client", FakeClient)
    monkeypatch.setattr(tts_module, "convert_audio_bytes", lambda audio_bytes, **_kwargs: audio_bytes)

    audio_bytes, fmt = engine.synthesize(
        "[excited] mimo hello",
        voice=voice,
        response_format="mp3",
        prompt_aware=True,
        prompt_aware_style="Honor bracket tags.",
    )

    assert audio_bytes == b"mimo-mp3"
    assert fmt == "mp3"
    messages = captured["json"]["messages"]  # type: ignore[index]
    assert messages[0]["content"] == "Speak warmly.\n\nHonor bracket tags."


def test_openai_compatible_prompt_aware_sends_instructions_for_remote_provider(tmp_path: Path, monkeypatch) -> None:
    settings = Settings(
        data_dir=tmp_path / "runtime",
        requesty_api_token="requesty-token",
        tts_backend_order=("requesty",),
        ffmpeg_bin="",
    )
    engine = LocalTtsEngine(settings)
    voice = resolve_voice("alloy")
    captured: dict[str, object] = {}

    class FakeResponse:
        content = b"requesty-mp3"

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, timeout: float):
            captured["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]):
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr(tts_module.httpx, "Client", FakeClient)
    monkeypatch.setattr(tts_module, "convert_audio_bytes", lambda audio_bytes, **_kwargs: audio_bytes)

    audio_bytes, fmt = engine.synthesize(
        "[dramatic] hello",
        voice=voice,
        response_format="mp3",
        prompt_aware=True,
        prompt_aware_style="Treat tags as directions.",
    )

    assert audio_bytes == b"requesty-mp3"
    assert fmt == "mp3"
    assert captured["json"]["instructions"] == "Treat tags as directions."  # type: ignore[index]


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


def test_local_tts_engine_falls_back_after_remote_quota_status(tmp_path: Path, monkeypatch) -> None:
    settings = Settings(
        data_dir=tmp_path / "runtime",
        requesty_api_token="requesty-token",
        tts_backend_order=("requesty", "melo", "espeak"),
        ffmpeg_bin="",
    )
    engine = LocalTtsEngine(settings)
    voice = resolve_voice("nova")
    request = httpx.Request("POST", "https://requesty.test/v1/audio/speech")
    response = httpx.Response(429, request=request, text="quota limited")

    class FakeClient:
        def __init__(self, timeout: float):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, *_args, **_kwargs):
            return response

    monkeypatch.setattr(tts_module.httpx, "Client", FakeClient)
    monkeypatch.setattr(engine, "_synthesize_with_melo", lambda *_args, **_kwargs: b"wav-local")
    monkeypatch.setattr(engine, "_synthesize_with_espeak", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tts_module, "convert_audio_bytes", lambda audio_bytes, **_kwargs: audio_bytes)

    audio_bytes, fmt = engine.synthesize(
        "fallback after quota",
        voice=voice,
        response_format="mp3",
        requested_voice_id="custom-voice",
    )

    assert audio_bytes == b"wav-local"
    assert fmt == "mp3"
    assert engine.last_backend == "melo"


def test_remote_voice_candidates_preserve_requested_id_for_requesty(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "runtime", requesty_tts_voice="env-requesty-default")
    engine = LocalTtsEngine(settings)
    voice = resolve_voice("nova")

    candidates = engine._remote_voice_candidates(
        voice,
        backend="requesty",
        requested_voice_id="voice_abc123",
        default_voice=settings.requesty_tts_voice,
    )

    assert candidates == ["voice_abc123", "ash", "env-requesty-default", "nova"]


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


def test_postprocess_profile_can_be_selected_per_request(tmp_path: Path, monkeypatch) -> None:
    settings = Settings(
        data_dir=tmp_path / "runtime",
        requesty_api_token="requesty-token",
        tts_backend_order=("requesty",),
        ffmpeg_bin="/usr/bin/ffmpeg",
        tts_postprocess_profile="sports-commentator-v1",
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
        "read this softly",
        voice=voice,
        response_format="mp3",
        postprocess_profile="soft",
    )

    assert audio_bytes == b"remote-mp3"
    assert fmt == "mp3"
    assert engine.last_postprocess_profile == "soft-studio-v1"
    assert "threshold=0.28" in captured["audio_filters"]


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

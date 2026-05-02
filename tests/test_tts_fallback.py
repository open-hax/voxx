from __future__ import annotations

import base64
import json
import logging
from pathlib import Path

import httpx

from voice_gateway.catalog import resolve_voice
from voice_gateway.config import Settings
from voice_gateway import tts as tts_module
from voice_gateway.tts import (
    LocalTtsEngine,
    _flatten_prompt_aware_segments,
    _parse_prompt_aware_segments,
    prompt_aware_render_plan,
)


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


def test_xiaomi_mimo_prompt_aware_tags_use_voxx_render_plan(tmp_path: Path, monkeypatch) -> None:
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

    def fake_prompt_aware_with_backend(backend: str, segments, **_kwargs):
        captured["backend"] = backend
        captured["segments"] = segments
        return b"mimo-styled-wav", "wav"

    monkeypatch.setattr(engine, "_synthesize_prompt_aware_with_backend", fake_prompt_aware_with_backend)
    monkeypatch.setattr(tts_module, "convert_audio_bytes", lambda audio_bytes, **_kwargs: audio_bytes)

    audio_bytes, fmt = engine.synthesize(
        "[excited] mimo hello",
        voice=voice,
        response_format="mp3",
        prompt_aware=True,
        prompt_aware_style="Honor bracket tags.",
    )

    assert audio_bytes == b"mimo-styled-wav"
    assert fmt == "mp3"
    assert captured["backend"] == "xiaomi_mimo"
    segments = captured["segments"]
    assert [(segment.kind, segment.text, segment.style) for segment in segments] == [("text", "mimo hello", "excited")]


def test_prompt_aware_tags_are_consumed_by_voxx_not_forwarded_to_remote_provider(tmp_path: Path, monkeypatch) -> None:
    settings = Settings(
        data_dir=tmp_path / "runtime",
        requesty_api_token="requesty-token",
        tts_backend_order=("requesty",),
        ffmpeg_bin="",
    )
    engine = LocalTtsEngine(settings)
    voice = resolve_voice("alloy")
    captured: dict[str, object] = {}

    def fake_prompt_aware_with_backend(backend: str, segments, **_kwargs):
        captured["backend"] = backend
        captured["segments"] = segments
        return b"voxx-styled-wav", "wav"

    def fail_if_remote_called(**_kwargs):
        raise AssertionError("prompt-aware tags should not be forwarded as raw remote-provider input")

    monkeypatch.setattr(engine, "_synthesize_prompt_aware_with_backend", fake_prompt_aware_with_backend)
    monkeypatch.setattr(engine, "_synthesize_with_openai_compatible", fail_if_remote_called)
    monkeypatch.setattr(tts_module, "convert_audio_bytes", lambda audio_bytes, **_kwargs: audio_bytes)

    audio_bytes, fmt = engine.synthesize(
        "[dramatic] hello",
        voice=voice,
        response_format="mp3",
        prompt_aware=True,
        prompt_aware_style="Treat tags as directions.",
    )

    assert audio_bytes == b"voxx-styled-wav"
    assert fmt == "mp3"
    assert captured["backend"] == "requesty"
    segments = captured["segments"]
    assert [(segment.kind, segment.text, segment.style) for segment in segments] == [("text", "hello", "dramatic")]


def test_prompt_aware_parser_turns_tags_into_voxx_render_plan() -> None:
    segments, consumed = _parse_prompt_aware_segments(
        "[excited] architect [pause] hello <break time=\"500ms\" /> world [laugh].",
    )

    assert consumed is True
    assert [(segment.kind, segment.text, segment.style, segment.pause_ms) for segment in segments] == [
        ("text", "architect", "excited", 0),
        ("pause", "", "", 350),
        ("text", "hello", "excited", 0),
        ("pause", "", "", 500),
        ("text", "world", "excited", 0),
        ("effect", "", "laugh", 180),
    ]
    assert _flatten_prompt_aware_segments(segments) == "architect ... hello ... world ..."


def test_prompt_aware_render_plan_outputs_clean_prompt_and_inflection_points() -> None:
    plan = prompt_aware_render_plan(
        "[excited] architect [pause] hello <break time=\"500ms\" /> world [laugh].",
    )

    assert plan["consumed_tags"] is True
    assert plan["updated_prompt"] == "architect hello world"
    assert plan["read_aloud_text"] == "architect hello world"
    assert "[excited]" not in plan["updated_prompt"]
    assert "[pause]" not in plan["updated_prompt"]
    assert "[laugh]" not in plan["updated_prompt"]
    assert plan["segments"] == [
        {"kind": "text", "text": "architect", "style": "excited", "read_start": 0, "read_end": 9},
        {"kind": "pause", "pause_ms": 350, "read_position": 9},
        {"kind": "text", "text": "hello", "style": "excited", "read_start": 10, "read_end": 15},
        {"kind": "pause", "pause_ms": 500, "read_position": 15},
        {"kind": "text", "text": "world", "style": "excited", "read_start": 16, "read_end": 21},
        {"kind": "effect", "style": "laugh", "duration_ms": 180, "read_position": 21},
    ]
    assert plan["inflection_points"] == [
        {"kind": "style", "style": "excited", "segment_index": 0, "read_start": 0, "read_end": 9},
        {"kind": "pause", "pause_ms": 350, "segment_index": 1, "read_position": 9},
        {"kind": "style", "style": "excited", "segment_index": 2, "read_start": 10, "read_end": 15},
        {"kind": "pause", "pause_ms": 500, "segment_index": 3, "read_position": 15},
        {"kind": "style", "style": "excited", "segment_index": 4, "read_start": 16, "read_end": 21},
        {"kind": "effect", "style": "laugh", "duration_ms": 180, "segment_index": 5, "read_position": 21},
    ]


def test_prompt_aware_parser_consumes_musical_performance_tags() -> None:
    plan = prompt_aware_render_plan("[sing] absolute [stretch] cinema [glitch] now")

    assert plan["consumed_tags"] is True
    assert plan["updated_prompt"] == "absolute cinema now"
    assert plan["inflection_points"] == [
        {"kind": "style", "style": "sing", "segment_index": 0, "read_start": 0, "read_end": 8},
        {"kind": "style", "style": "stretch", "segment_index": 1, "read_start": 9, "read_end": 15},
        {"kind": "style", "style": "glitch", "segment_index": 2, "read_start": 16, "read_end": 19},
    ]


def test_prompt_aware_synthesis_logs_clean_render_plan(tmp_path: Path, monkeypatch, caplog) -> None:
    settings = Settings(
        data_dir=tmp_path / "runtime",
        requesty_api_token="requesty-token",
        tts_backend_order=("requesty",),
        ffmpeg_bin="",
    )
    engine = LocalTtsEngine(settings)
    voice = resolve_voice("alloy")

    def fake_prompt_aware_with_backend(*_args, **_kwargs):
        return b"voxx-styled-wav", "wav"

    monkeypatch.setattr(engine, "_synthesize_prompt_aware_with_backend", fake_prompt_aware_with_backend)
    monkeypatch.setattr(tts_module, "convert_audio_bytes", lambda audio_bytes, **_kwargs: audio_bytes)
    caplog.set_level(logging.INFO, logger="voice_gateway.tts.prompt_aware")

    audio_bytes, fmt = engine.synthesize(
        "[excited] architect [pause] hello [laugh].",
        voice=voice,
        response_format="mp3",
        prompt_aware=True,
    )

    assert audio_bytes == b"voxx-styled-wav"
    assert fmt == "mp3"
    render_record = next(
        record for record in caplog.records if record.getMessage().startswith("voxx.prompt_aware.render_plan ")
    )
    payload = json.loads(render_record.getMessage().split(" ", 1)[1])
    assert payload["updated_prompt_preview"] == "architect hello"
    assert payload["updated_prompt_contains_prompt_markup"] is False
    assert payload["text_segment_count"] == 2
    assert "[excited]" not in payload["updated_prompt_preview"]
    assert "[pause]" not in payload["updated_prompt_preview"]
    assert "[laugh]" not in payload["updated_prompt_preview"]
    assert payload["inflection_points"] == [
        {"kind": "style", "style": "excited", "segment_index": 0, "read_start": 0, "read_end": 9},
        {"kind": "pause", "pause_ms": 350, "segment_index": 1, "read_position": 9},
        {"kind": "style", "style": "excited", "segment_index": 2, "read_start": 10, "read_end": 15},
        {"kind": "effect", "style": "laugh", "duration_ms": 180, "segment_index": 3, "read_position": 15},
    ]


def test_prompt_aware_disabled_preserves_tags_for_local_backend(tmp_path: Path, monkeypatch) -> None:
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

    def fake_synthesize_with_openai_compatible(**kwargs):
        captured["text"] = kwargs["text"]
        return b"kokoro-mp3", "mp3"

    monkeypatch.setattr(engine, "_synthesize_with_openai_compatible", fake_synthesize_with_openai_compatible)
    monkeypatch.setattr(tts_module, "convert_audio_bytes", lambda audio_bytes, **_kwargs: audio_bytes)

    audio_bytes, fmt = engine.synthesize(
        "[excited] keep tags literal [pause]",
        voice=voice,
        response_format="mp3",
        prompt_aware=False,
    )

    assert audio_bytes == b"kokoro-mp3"
    assert fmt == "mp3"
    assert captured["text"] == "[excited] keep tags literal [pause]"


def test_local_tts_engine_falls_back_after_remote_error(tmp_path: Path, monkeypatch) -> None:
    settings = Settings(
        data_dir=tmp_path / "runtime",
        requesty_api_token="requesty-token",
        tts_backend_order=("requesty", "melo", "espeak"),
        ffmpeg_bin="",
    )
    engine = LocalTtsEngine(settings)
    voice = resolve_voice("nova")
    captured: dict[str, object] = {}

    def fake_prompt_aware_with_backend(backend: str, segments, **_kwargs):
        if backend == "requesty":
            raise RuntimeError("requesty down")
        captured["backend"] = backend
        captured["segments"] = segments
        return b"wav-local", "wav"

    monkeypatch.setattr(engine, "_synthesize_prompt_aware_with_backend", fake_prompt_aware_with_backend)
    monkeypatch.setattr(engine, "_synthesize_with_espeak", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tts_module, "convert_audio_bytes", lambda audio_bytes, **_kwargs: audio_bytes)

    audio_bytes, fmt = engine.synthesize(
        "[dramatic] fallback me [pause]",
        voice=voice,
        response_format="mp3",
        requested_voice_id="custom-voice",
        prompt_aware=True,
    )

    assert audio_bytes == b"wav-local"
    assert fmt == "mp3"
    assert engine.last_backend == "melo"
    assert captured["backend"] == "melo"
    segments = captured["segments"]
    assert [(segment.kind, segment.text, segment.style) for segment in segments] == [
        ("text", "fallback me", "dramatic"),
        ("pause", "", ""),
    ]


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


def test_sutured_autotune_profile_is_labeled_and_selectable(tmp_path: Path, monkeypatch) -> None:
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
        "bop bop be sutured",
        voice=voice,
        response_format="mp3",
        postprocess_profile="sutured",
    )

    assert audio_bytes == b"remote-mp3"
    assert fmt == "mp3"
    assert engine.last_postprocess_profile == "sutured-autotune-v1"
    assert "rubberband=pitch=1.055000" in captured["audio_filters"]
    assert "vibrato=" in captured["audio_filters"]
    assert "aecho=" in captured["audio_filters"]
    payload = settings.tts_postprocess_profiles_payload()
    sutured = next(profile for profile in payload["profiles"] if profile["id"] == "sutured-autotune-v1")
    assert sutured["labels"]["lineage"] == "openplanner-sovereign-suture"
    assert payload["aliases"]["autotune"] == "sutured-autotune-v1"


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

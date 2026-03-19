from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from voice_gateway.app import create_app
from voice_gateway.config import Settings
from voice_gateway.service import VoiceGatewayService
from voice_gateway.stt import StubSttEngine
from voice_gateway.transcripts import TranscriptStore
from voice_gateway.tts import StubTtsEngine


def build_client(tmp_path: Path) -> tuple[TestClient, StubTtsEngine, StubSttEngine]:
    settings = Settings(api_key="secret-token", data_dir=tmp_path / "runtime")
    tts_engine = StubTtsEngine(audio_bytes=b"ID3stub-audio")
    stt_engine = StubSttEngine(text="heard words")
    gateway = VoiceGatewayService(
        settings=settings,
        tts_engine=tts_engine,
        stt_engine=stt_engine,
        transcript_store=TranscriptStore(settings.transcript_dir),
    )
    return TestClient(create_app(gateway)), tts_engine, stt_engine


def test_models_require_auth_and_return_catalog(tmp_path: Path) -> None:
    client, _tts_engine, _stt_engine = build_client(tmp_path)

    unauthorized = client.get("/v1/models")
    assert unauthorized.status_code == 401

    response = client.get("/v1/models", headers={"Authorization": "Bearer secret-token"})
    assert response.status_code == 200
    payload = response.json()
    model_ids = {row["id"] for row in payload["data"]}
    assert "gpt-4o-mini-tts" in model_ids
    assert "whisper-1" in model_ids


def test_openai_speech_endpoint_returns_audio_bytes(tmp_path: Path) -> None:
    client, tts_engine, _stt_engine = build_client(tmp_path)

    response = client.post(
        "/v1/audio/speech",
        headers={"Authorization": "Bearer secret-token"},
        json={
            "model": "gpt-4o-mini-tts",
            "input": "hello from openhax",
            "voice": "nova",
            "response_format": "mp3",
            "speed": 1.1,
        },
    )

    assert response.status_code == 200
    assert response.content == b"ID3stub-audio"
    assert response.headers["content-type"].startswith("audio/mpeg")
    assert response.headers["x-openhax-voice-id"] == "nova"
    assert tts_engine.calls[0]["text"] == "hello from openhax"


def test_openai_transcription_and_translation_routes(tmp_path: Path) -> None:
    client, _tts_engine, stt_engine = build_client(tmp_path)

    transcription = client.post(
        "/v1/audio/transcriptions",
        headers={"Authorization": "Bearer secret-token"},
        files={"file": ("clip.webm", b"audio-data", "audio/webm")},
        data={"model": "gpt-4o-transcribe", "response_format": "verbose_json", "language": "en"},
    )

    assert transcription.status_code == 200
    payload = transcription.json()
    assert payload["text"] == "heard words"
    assert payload["language"] == "en"
    assert transcription.headers["x-openhax-transcription-id"].startswith("tr_")

    translation = client.post(
        "/v1/audio/translations",
        headers={"Authorization": "Bearer secret-token"},
        files={"file": ("clip.webm", b"audio-data", "audio/webm")},
        data={"model": "gpt-4o-transcribe", "response_format": "json", "language": "ja"},
    )

    assert translation.status_code == 200
    assert translation.json()["text"] == "translated:heard words"
    assert stt_engine.calls[1]["task"] == "translate"


def test_elevenlabs_voice_routes_and_tts_route(tmp_path: Path) -> None:
    client, tts_engine, _stt_engine = build_client(tmp_path)

    voices = client.get("/v1/voices", headers={"xi-api-key": "secret-token"})
    assert voices.status_code == 200
    assert any(row["voice_id"] == "alloy" for row in voices.json()["voices"])

    settings_response = client.get("/v1/voices/rachel/settings", headers={"xi-api-key": "secret-token"})
    assert settings_response.status_code == 200
    assert "stability" in settings_response.json()

    tts_response = client.post(
        "/v1/text-to-speech/rachel?output_format=wav",
        headers={"xi-api-key": "secret-token"},
        json={"text": "eleven compatible voice", "voice_settings": {"speed": 0.95}},
    )
    assert tts_response.status_code == 200
    assert tts_response.headers["content-type"].startswith("audio/wav")
    assert tts_engine.calls[-1]["voice"] == "alloy"


def test_elevenlabs_stt_route_persists_transcript(tmp_path: Path) -> None:
    client, _tts_engine, _stt_engine = build_client(tmp_path)

    transcription = client.post(
        "/v1/speech-to-text",
        headers={"xi-api-key": "secret-token"},
        files={"file": ("clip.webm", b"audio-data", "audio/webm")},
        data={"model_id": "scribe_v1", "language_code": "en"},
    )
    assert transcription.status_code == 200
    payload = transcription.json()
    assert payload["text"] == "heard words"
    transcription_id = payload["transcription_id"]

    fetched = client.get(
        f"/v1/speech-to-text/transcripts/{transcription_id}",
        headers={"xi-api-key": "secret-token"},
    )
    assert fetched.status_code == 200
    assert fetched.json()["text"] == "heard words"


def test_realtime_compat_websockets_buffer_and_flush(tmp_path: Path) -> None:
    client, _tts_engine, _stt_engine = build_client(tmp_path)

    with client.websocket_connect(
        "/v1/speech-to-text/realtime",
        headers={"xi-api-key": "secret-token"},
    ) as websocket:
        websocket.send_bytes(b"abc")
        websocket.send_json({"type": "finalize", "language_code": "en"})
        transcript = websocket.receive_json()
        assert transcript["type"] == "transcript"
        assert transcript["text"] == "heard words"

    with client.websocket_connect(
        "/v1/text-to-speech/rachel/stream-input?output_format=mp3",
        headers={"xi-api-key": "secret-token"},
    ) as websocket:
        websocket.send_json({"text": "hello "})
        websocket.send_json({"text": "world"})
        websocket.send_json({"type": "flush"})
        audio = websocket.receive_bytes()
        footer = websocket.receive_json()
        assert audio == b"ID3stub-audio"
        assert footer["type"] == "audio_end"
        assert footer["format"] == "mp3"

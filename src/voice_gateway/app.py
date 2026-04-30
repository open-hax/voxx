from __future__ import annotations

import base64
import json
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from .audio_utils import mime_for_audio_format, normalize_audio_format, normalize_voice_output_format
from .catalog import DEFAULT_OPENAI_VOICE
from .formatters import voice_transcription_payload, openai_transcription_payload
from .service import VoiceGatewayService


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_bool(value: Any, default: bool | None = None) -> bool | None:
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if not normalized:
        return default
    if normalized in {"1", "true", "yes", "on", "enabled", "enable"}:
        return True
    if normalized in {"0", "false", "no", "off", "disabled", "disable", "none"}:
        return False
    return default


def _first_payload_value(payload: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        if name in payload:
            return payload.get(name)
    return None


def _tts_request_options(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    query = request.query_params
    raw_postprocess = query.get("postprocess") or _first_payload_value(payload, ("postprocess",))
    postprocess_enabled = _safe_bool(raw_postprocess, None)
    explicit_postprocess_enabled = query.get("postprocess_enabled") or query.get("postprocessEnabled") or _first_payload_value(
        payload,
        ("postprocess_enabled", "postprocessEnabled"),
    )
    if explicit_postprocess_enabled is not None:
        postprocess_enabled = _safe_bool(explicit_postprocess_enabled, postprocess_enabled)

    postprocess_profile = (
        query.get("postprocess_profile")
        or query.get("postprocessProfile")
        or _first_payload_value(payload, ("postprocess_profile", "postprocessProfile"))
    )
    if postprocess_profile is None and raw_postprocess is not None and _safe_bool(raw_postprocess, None) is None:
        postprocess_profile = raw_postprocess

    raw_prompt_aware = query.get("prompt_aware") or query.get("promptAware") or query.get("prompt-aware") or _first_payload_value(
        payload,
        ("prompt_aware", "promptAware", "prompt-aware"),
    )
    prompt_aware = _safe_bool(raw_prompt_aware, None)
    prompt_aware_style = (
        query.get("prompt_aware_style")
        or query.get("promptAwareStyle")
        or _first_payload_value(payload, ("prompt_aware_style", "promptAwareStyle"))
    )
    return {
        "postprocess_profile": str(postprocess_profile).strip() if postprocess_profile is not None else None,
        "postprocess_enabled": postprocess_enabled,
        "prompt_aware": prompt_aware,
        "prompt_aware_style": str(prompt_aware_style).strip() if prompt_aware_style is not None else None,
    }


def _openai_error(status_code: int, message: str, *, param: str | None = None, code: str = "invalid_request_error") -> JSONResponse:
    response = JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "message": message,
                "type": code,
                "param": param,
                "code": code,
            }
        },
    )
    if status_code == 401:
        response.headers["www-authenticate"] = "Bearer"
    return response


def _compat_error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "detail": {
                "status": "error",
                "message": message,
            }
        },
    )


async def _extract_audio_upload(request: Request) -> dict[str, Any]:
    content_type = str(request.headers.get("content-type", "") or "")
    if "multipart/form-data" in content_type:
        form = await request.form()
        file_field = form.get("file") or form.get("audio")
        if file_field is None:
            return {"error": "missing file"}
        if hasattr(file_field, "read"):
            file_bytes = await file_field.read()
            file_name = str(getattr(file_field, "filename", "audio.bin") or "audio.bin")
            mime = str(getattr(file_field, "content_type", "audio/webm") or "audio/webm")
        else:
            file_bytes = bytes(file_field)
            file_name = "audio.bin"
            mime = "audio/webm"
        return {
            "file_bytes": file_bytes,
            "file_name": file_name,
            "mime": mime,
            "form": form,
        }

    try:
        payload = await request.json()
    except Exception:
        payload = {}
    audio_b64 = str(payload.get("audio_base64") or payload.get("base64") or "").strip()
    if not audio_b64:
        return {"error": "missing file"}
    try:
        audio_bytes = base64.b64decode(audio_b64.encode("utf-8"), validate=False)
    except (ValueError, OSError):
        return {"error": "invalid base64 audio"}
    return {
        "file_bytes": audio_bytes,
        "file_name": str(payload.get("filename") or payload.get("name") or "audio.bin"),
        "mime": str(payload.get("mime") or "audio/webm"),
        "form": payload,
    }


async def _read_json_message(websocket: WebSocket) -> dict[str, Any] | None:
    message = await websocket.receive()
    if message.get("type") == "websocket.disconnect":
        raise WebSocketDisconnect(code=message.get("code", 1000))
    if message.get("bytes") is not None:
        return {"bytes": bytes(message["bytes"])}
    text = message.get("text")
    if text is None:
        return {}
    stripped = str(text).strip()
    if not stripped:
        return {}
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        return {"text": stripped}
    return {"text": stripped}


def create_app(service: VoiceGatewayService | None = None) -> FastAPI:
    gateway = service or VoiceGatewayService.create_default()
    app = FastAPI(
        title="OpenHax Voxx",
        description="Fork Tales voice pipeline extracted into an OpenAI-compatible Voxx service.",
        version="0.1.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.gateway = gateway

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {
            "ok": True,
            "service": "voxx",
            "requires_api_key": bool(gateway.settings.api_key),
            "model_count": len(gateway.openai_models_payload()["data"]),
            "tts_queue": gateway.tts_queue_payload(),
        }

    @app.get("/v1/models")
    @app.get("/models")
    async def models(request: Request) -> Response:
        if not gateway.authorized(request):
            return _openai_error(401, "Invalid API key")
        return JSONResponse(gateway.openai_models_payload())

    @app.get("/v1/voices")
    @app.get("/v1/voices/search")
    async def voice_voices(request: Request) -> Response:
        if not gateway.authorized(request):
            return _compat_error(401, "Invalid API key")
        voice_ids_query = list(request.query_params.getlist("voice_ids"))
        expanded_voice_ids: list[str] = []
        for value in voice_ids_query:
            expanded_voice_ids.extend([part.strip() for part in value.split(",") if part.strip()])
        search = request.query_params.get("search") or request.query_params.get("query")
        return JSONResponse(gateway.voices_payload(search=search, voice_ids=expanded_voice_ids or None))

    @app.get("/v1/voices/openai")
    async def openai_voices(request: Request) -> Response:
        if not gateway.authorized(request):
            return _openai_error(401, "Invalid API key")
        return JSONResponse(gateway.openai_voice_payload())

    @app.get("/v1/voices/{voice_id}")
    async def voice_voice(voice_id: str, request: Request) -> Response:
        if not gateway.authorized(request):
            return _compat_error(401, "Invalid API key")
        return JSONResponse(gateway.voice_payload(voice_id))

    @app.get("/v1/voices/{voice_id}/settings")
    async def voice_voice_settings(voice_id: str, request: Request) -> Response:
        if not gateway.authorized(request):
            return _compat_error(401, "Invalid API key")
        return JSONResponse(gateway.voice_settings_payload(voice_id))

    @app.get("/v1/audio/postprocess-profiles")
    @app.get("/v1/tts/postprocess-profiles")
    async def tts_postprocess_profiles(request: Request) -> Response:
        if not gateway.authorized(request):
            return _openai_error(401, "Invalid API key")
        return JSONResponse(gateway.tts_postprocess_profiles_payload())

    @app.post("/v1/audio/speech")
    async def openai_audio_speech(request: Request) -> Response:
        if not gateway.authorized(request):
            return _openai_error(401, "Invalid API key")
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        text = str(payload.get("input", "") or "").strip()
        if not text:
            return _openai_error(400, "Missing required field: input", param="input")
        voice_id = str(payload.get("voice") or "").strip() or None
        response_format = normalize_audio_format(payload.get("response_format") or gateway.settings.default_audio_format)
        speed = _safe_float(payload.get("speed"), 1.0)
        language = str(payload.get("language") or "").strip() or None
        tts_options = _tts_request_options(request, payload)
        try:
            audio_bytes, normalized_format, headers = await run_in_threadpool(
                gateway.synthesize_openai,
                text=text,
                voice_id=voice_id,
                response_format=response_format,
                speed=speed,
                language=language,
                **tts_options,
            )
        except RuntimeError as exc:
            return _openai_error(503, str(exc), code="service_unavailable")
        headers = {
            **headers,
            "content-disposition": f'inline; filename="speech.{normalized_format}"',
        }
        return Response(audio_bytes, media_type=mime_for_audio_format(normalized_format), headers=headers)

    async def _handle_openai_transcription(request: Request, *, task: str) -> Response:
        if not gateway.authorized(request):
            return _openai_error(401, "Invalid API key")
        upload = await _extract_audio_upload(request)
        if upload.get("error"):
            return _openai_error(400, str(upload["error"]), param="file")
        form = upload["form"]
        model = str(getattr(form, "get", lambda *args: "")("model", "gpt-4o-transcribe") or "gpt-4o-transcribe")
        language = str(getattr(form, "get", lambda *args: "")("language", "") or "").strip() or None
        response_format = str(getattr(form, "get", lambda *args: "json")("response_format", "json") or "json")
        result = gateway.transcribe(
            audio_bytes=upload["file_bytes"],
            mime=str(upload["mime"]),
            language=language,
            task=task,
        )
        if not result.ok:
            status_code = 503 if "backend active" in str(result.error or "").lower() else 400
            return _openai_error(status_code, str(result.error or "transcription failed"), code="audio_processing_error")
        record = gateway.store_transcript(
            source_name=str(upload["file_name"]),
            mime_type=str(upload["mime"]),
            task=task,
            model_id=model,
            result=result,
        )
        response = openai_transcription_payload(result, response_format=response_format, model=model)
        response.headers["x-openhax-transcription-id"] = str(record["transcription_id"])
        return response

    @app.post("/v1/audio/transcriptions")
    async def openai_audio_transcriptions(request: Request) -> Response:
        return await _handle_openai_transcription(request, task="transcribe")

    @app.post("/v1/audio/translations")
    async def openai_audio_translations(request: Request) -> Response:
        return await _handle_openai_transcription(request, task="translate")

    async def _handle_provider_style_tts(request: Request, voice_id: str) -> Response:
        if not gateway.authorized(request):
            return _compat_error(401, "Invalid API key")
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        text = str(payload.get("text") or "").strip()
        if not text:
            return _compat_error(400, "Missing required field: text")
        voice_settings = payload.get("voice_settings") if isinstance(payload.get("voice_settings"), dict) else {}
        speed = _safe_float(voice_settings.get("speed") or payload.get("speed"), 1.0)
        language = str(payload.get("language_code") or payload.get("language") or "").strip() or None
        output_format = normalize_voice_output_format(
            request.query_params.get("output_format") or payload.get("output_format")
        )
        tts_options = _tts_request_options(request, payload)
        try:
            audio_bytes, normalized_format, headers = await run_in_threadpool(
                gateway.synthesize_openai,
                text=text,
                voice_id=voice_id or DEFAULT_OPENAI_VOICE,
                response_format=output_format,
                speed=speed,
                language=language,
                **tts_options,
            )
        except RuntimeError as exc:
            return _compat_error(503, str(exc))
        headers = {
            **headers,
            "content-disposition": f'inline; filename="{voice_id or DEFAULT_OPENAI_VOICE}.{normalized_format}"',
        }
        return Response(audio_bytes, media_type=mime_for_audio_format(normalized_format), headers=headers)

    @app.post("/v1/text-to-speech/{voice_id}")
    async def voice_text_to_speech(voice_id: str, request: Request) -> Response:
        return await _handle_provider_style_tts(request, voice_id)

    @app.post("/v1/text-to-speech/{voice_id}/stream")
    async def voice_text_to_speech_stream(voice_id: str, request: Request) -> Response:
        return await _handle_provider_style_tts(request, voice_id)

    @app.post("/v1/speech-to-text")
    async def voice_speech_to_text(request: Request) -> Response:
        if not gateway.authorized(request):
            return _compat_error(401, "Invalid API key")
        upload = await _extract_audio_upload(request)
        if upload.get("error"):
            return _compat_error(400, str(upload["error"]))
        form = upload["form"]
        model_id = str(getattr(form, "get", lambda *args: "scribe_v1")("model_id", "scribe_v1") or "scribe_v1")
        language = str(
            getattr(form, "get", lambda *args: "")("language_code", getattr(form, "get", lambda *args: "")("language", ""))
            or ""
        ).strip() or None
        result = gateway.transcribe(
            audio_bytes=upload["file_bytes"],
            mime=str(upload["mime"]),
            language=language,
            task="transcribe",
        )
        if not result.ok:
            status_code = 503 if "backend active" in str(result.error or "").lower() else 400
            return _compat_error(status_code, str(result.error or "transcription failed"))
        record = gateway.store_transcript(
            source_name=str(upload["file_name"]),
            mime_type=str(upload["mime"]),
            task="transcribe",
            model_id=model_id,
            result=result,
        )
        response = voice_transcription_payload(
            result,
            transcription_id=str(record["transcription_id"]),
            model_id=model_id,
        )
        response.headers["x-openhax-transcription-id"] = str(record["transcription_id"])
        return response

    @app.get("/v1/speech-to-text/transcripts/{transcription_id}")
    async def voice_get_transcript(transcription_id: str, request: Request) -> Response:
        if not gateway.authorized(request):
            return _compat_error(401, "Invalid API key")
        record = gateway.get_transcript(transcription_id)
        if record is None:
            return _compat_error(404, "Transcript not found")
        result = record.get("result", {})
        return JSONResponse(
            {
                "transcription_id": transcription_id,
                "text": result.get("text", ""),
                "language_code": result.get("language", ""),
                "model_id": record.get("model_id", "scribe_v1"),
                "duration_seconds": result.get("duration") or 0.0,
                "segments": result.get("segments", []),
                "words": [],
                "created_at": record.get("created_at"),
            }
        )

    @app.websocket("/v1/speech-to-text/realtime")
    async def voice_realtime_stt(websocket: WebSocket) -> None:
        if gateway.settings.api_key and not gateway.authorized(websocket):
            await websocket.close(code=4401)
            return
        await websocket.accept()
        audio_buffer = bytearray()
        language: str | None = None
        try:
            while True:
                payload = await _read_json_message(websocket)
                if payload is None:
                    continue
                if "bytes" in payload:
                    audio_buffer.extend(payload["bytes"])
                    continue
                if "audio_base64" in payload:
                    try:
                        audio_buffer.extend(base64.b64decode(str(payload["audio_base64"]), validate=False))
                    except (ValueError, OSError):
                        await websocket.send_json({"type": "error", "message": "invalid audio_base64"})
                    continue
                if "language_code" in payload:
                    language = str(payload.get("language_code") or "").strip() or language
                event_type = str(payload.get("type") or "").strip().lower()
                if event_type in {"flush", "finalize", "transcribe"}:
                    result = gateway.transcribe(
                        audio_bytes=bytes(audio_buffer),
                        mime="audio/webm",
                        language=language,
                        task="transcribe",
                    )
                    if result.ok:
                        await websocket.send_json(
                            {
                                "type": "transcript",
                                "text": result.text,
                                "language_code": result.language or "",
                                "is_final": True,
                            }
                        )
                    else:
                        await websocket.send_json({"type": "error", "message": result.error or "transcription failed"})
                    audio_buffer.clear()
                    continue
                if event_type in {"close", "stop"}:
                    await websocket.close(code=1000)
                    return
                if "text" in payload:
                    language = language or None
        except WebSocketDisconnect:
            return

    @app.websocket("/v1/text-to-speech/{voice_id}/stream-input")
    async def voice_realtime_tts(websocket: WebSocket, voice_id: str) -> None:
        if gateway.settings.api_key and not gateway.authorized(websocket):
            await websocket.close(code=4401)
            return
        await websocket.accept()
        chunks: list[str] = []
        speed = 1.0
        language: str | None = None
        output_format = normalize_voice_output_format(websocket.query_params.get("output_format"))
        postprocess_profile = websocket.query_params.get("postprocess_profile") or websocket.query_params.get("postprocess")
        postprocess_enabled = _safe_bool(websocket.query_params.get("postprocess_enabled"), None)
        if postprocess_enabled is None:
            postprocess_enabled = _safe_bool(websocket.query_params.get("postprocess"), None)
        prompt_aware = _safe_bool(
            websocket.query_params.get("prompt_aware") or websocket.query_params.get("promptAware"),
            None,
        )
        prompt_aware_style = websocket.query_params.get("prompt_aware_style") or websocket.query_params.get("promptAwareStyle")
        try:
            while True:
                payload = await _read_json_message(websocket)
                if payload is None:
                    continue
                if "text" in payload:
                    text_value = str(payload.get("text") or "")
                    if text_value:
                        chunks.append(text_value)
                if "voice_settings" in payload and isinstance(payload["voice_settings"], dict):
                    speed = _safe_float(payload["voice_settings"].get("speed"), speed)
                if "language_code" in payload:
                    language = str(payload.get("language_code") or "").strip() or language
                message_options = _tts_request_options(request=websocket, payload=payload)
                event_type = str(payload.get("type") or "").strip().lower()
                if event_type in {"flush", "generate", "try_trigger_generation"}:
                    text = "".join(chunks).strip()
                    if not text:
                        await websocket.send_json({"type": "error", "message": "empty text buffer"})
                        continue
                    try:
                        audio_bytes, normalized_format, _headers = await run_in_threadpool(
                            gateway.synthesize_openai,
                            text=text,
                            voice_id=voice_id,
                            response_format=output_format,
                            speed=speed,
                            language=language,
                            postprocess_profile=message_options.get("postprocess_profile") or postprocess_profile,
                            postprocess_enabled=message_options.get("postprocess_enabled") if message_options.get("postprocess_enabled") is not None else postprocess_enabled,
                            prompt_aware=message_options.get("prompt_aware") if message_options.get("prompt_aware") is not None else prompt_aware,
                            prompt_aware_style=message_options.get("prompt_aware_style") or prompt_aware_style,
                        )
                    except RuntimeError as exc:
                        await websocket.send_json({"type": "error", "message": str(exc)})
                        continue
                    await websocket.send_bytes(audio_bytes)
                    await websocket.send_json({"type": "audio_end", "format": normalized_format})
                    chunks.clear()
                    continue
                if event_type in {"close", "stop"}:
                    await websocket.close(code=1000)
                    return
        except WebSocketDisconnect:
            return

    return app


app = create_app()

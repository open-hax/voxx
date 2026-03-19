# @openhax/voxx

Fork Tales voice pipeline extracted into the standalone Open Hax service package now aligned with the upstream repo name: `voxx`.

## What it provides
- Local TTS pipeline extracted from `vaults/fork_tales/part64/code/tts_service.py`
- Local STT pipeline extracted from `vaults/fork_tales/part64/code/world_web/ai.py`
- OpenAI-compatible voice endpoints
- ElevenLabs-style compatibility endpoints
- Requesty/OpenAI-client compatibility via `/v1/*` OpenAI audio routes

## Supported endpoint surface
### OpenAI-compatible
- `GET /v1/models`
- `POST /v1/audio/speech`
- `POST /v1/audio/transcriptions`
- `POST /v1/audio/translations`

### ElevenLabs-compatible
- `GET /v1/voices`
- `GET /v1/voices/search`
- `GET /v1/voices/:voice_id`
- `GET /v1/voices/:voice_id/settings`
- `POST /v1/text-to-speech/:voice_id`
- `POST /v1/text-to-speech/:voice_id/stream`
- `POST /v1/speech-to-text`
- `GET /v1/speech-to-text/transcripts/:transcription_id`
- `WS /v1/speech-to-text/realtime`
- `WS /v1/text-to-speech/:voice_id/stream-input`

## Install
Create a Python environment and install runtime dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Optional heavy runtime dependencies for the extracted Fork Tales path:
- `torch`
- `MeloTTS` (install from the upstream repository)
- `ffmpeg`
- `whisper.cpp` binary + model path for fallback STT

## Run
```bash
pnpm start
```

Dev mode:
```bash
pnpm dev
```

Tests:
```bash
pnpm test
```

## Docker Compose
For a self-contained local runtime that does not depend on the pre-published Melo base image:

```bash
docker compose up --build -d
curl http://127.0.0.1:8788/healthz
```

Expected health payload shape:

```json
{"ok":true,"service":"voxx",...}
```

Notes:
- The Compose runtime installs `espeak-ng` + `ffmpeg` so TTS requests can fall back even when MeloTTS is not present.
- `faster-whisper` is installed, but model weights may still download on first transcription use.
- Override the default API token with `VOICE_GATEWAY_API_KEY=... docker compose up --build` if you do not want the dev default.

## Docker + registry reuse
This service reuses the existing registry-backed ML image `localhost:5000/shibboleth/ml-base:cuda12.4-2026-03-18` as the seed ML base for Melo workloads, then publishes a dedicated Melo-capable base into the local registry.

Registry-backed images:
- Reused ML base: `localhost:5000/shibboleth/ml-base:cuda12.4-2026-03-18`
- Melo-capable base: `localhost:5000/openhax/melo-voice-base:2026-03-19`
- Service image target: `localhost:5000/openhax/voxx:latest`

Build/publish the Melo base from the reused registry ML base:
```bash
pnpm docker:publish-melo-base
```

Build the service image from the registry-backed Melo base:
```bash
pnpm docker:build-image
```

Build/publish the service image into the local registry:
```bash
pnpm docker:publish-image
```

Run the published service image:
```bash
docker run --rm -p 8788:8788 \
  -e VOICE_GATEWAY_API_KEY=dev-token \
  localhost:5000/openhax/voxx:latest
```

## Auth
If `VOICE_GATEWAY_API_KEY` is set, the service accepts these auth styles:
- `Authorization: Bearer <token>`
- `x-api-key: <token>`
- `api-key: <token>`
- `xi-api-key: <token>`
- `?token=<token>` for websocket compatibility

## Notes
- Requesty compatibility is handled through the OpenAI-compatible `/v1` audio routes.
- ElevenLabs realtime compatibility here is a buffered shim, not full upstream event parity.
- OpenAI Realtime API parity is intentionally out of scope for this first extraction pass.

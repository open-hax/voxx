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
{"ok":true,"service":"voxx"}
```

Notes:
- The Compose runtime installs `espeak-ng` + `ffmpeg` so TTS requests can fall back even when MeloTTS is not present.
- `faster-whisper` is installed, but model weights may still download on first transcription use.
- Override the default API token with `VOICE_GATEWAY_API_KEY=... docker compose up --build` if you do not want the dev default.
- If port `8788` is already busy, run `VOXX_PORT=8798 docker compose up --build` (or choose another free host port).

## Smart TTS backend order

Voxx now chooses a backend order instead of hard-wiring itself to Melo/espeak only.

Default order when credentials exist:

1. `elevenlabs`
2. `requesty`
3. `openai`
4. `melo`
5. `espeak`

Override the order explicitly with:

```bash
VOICE_GATEWAY_TTS_BACKEND_ORDER=requesty,melo,espeak
```

Useful env knobs:

```bash
# provider order / timeouts
VOICE_GATEWAY_TTS_BACKEND_ORDER=requesty,melo,espeak
VOICE_GATEWAY_TTS_REMOTE_TIMEOUT_SECONDS=45

# Requesty/OpenAI-compatible remote fallback
REQUESTY_API_TOKEN=...
REQUESTY_TTS_BASE_URL=https://router.requesty.ai/v1/audio/speech
REQUESTY_TTS_MODEL=openai/gpt-4o-mini-tts
REQUESTY_TTS_VOICE=ash

# OpenAI direct fallback
OPENAI_API_KEY=...
OPENAI_TTS_BASE_URL=https://api.openai.com/v1/audio/speech
OPENAI_TTS_MODEL=gpt-4o-mini-tts
OPENAI_TTS_VOICE=ash

# ElevenLabs premium target voice
ELEVENLABS_API_KEY=...
ELEVENLABS_TTS_BASE_URL=https://api.elevenlabs.io/v1
ELEVENLABS_TTS_MODEL=eleven_turbo_v2_5
ELEVENLABS_VOICE_ID=<voice-id>
```

Voxx also exposes the backend actually used for a synthesis request through the response header:

- `x-openhax-tts-backend`

That lets Battlebussy keep pointing at Voxx while Voxx quietly upgrades from local Melo/espeak to Requesty or ElevenLabs when those creds are available.

## Provider research snapshot

Quick 2026-03-20 findings from a live crawl of `models.dev` plus provider docs:

- **Cloudflare Workers AI / AI Gateway — MyShell MeloTTS**: models.dev lists `@cf/myshell-ai/melotts` / `workers-ai/@cf/myshell-ai/melotts` at `$0.00` listed token cost, making it the most interesting free-ish hosted fallback candidate to validate next.
- **Requesty**: already compatible with Voxx because it exposes an OpenAI-style `/v1/audio/speech` route; best current near-drop-in option when the token is available.
- **Google Gemini preview TTS** and **Qwen Omni audio models** show up in models.dev, but they are not free and/or are more audio-native than simple drop-in TTS today.
- **ElevenLabs** remains the highest-value final target when a specific sponsored voice is available; Voxx now has a clean env path for that exact voice ID later.

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

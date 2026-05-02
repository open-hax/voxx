# @openhax/voxx

Fork Tales voice pipeline extracted into the standalone Open Hax service package now aligned with the upstream repo name: `voxx`.

## What it provides
- Local TTS pipeline extracted from `orgs/octave-commons/fork_tales/part64/code/tts_service.py`
- Local STT pipeline extracted from `orgs/octave-commons/fork_tales/part64/code/world_web/ai.py`
- OpenAI-compatible voice endpoints
- Voxx voice catalog and provider-style convenience endpoints
- Requesty/OpenAI-client compatibility via `/v1/*` OpenAI audio routes

## Supported endpoint surface
### OpenAI-compatible
- `GET /v1/models`
- `POST /v1/audio/speech`
- `POST /v1/audio/transcriptions`
- `POST /v1/audio/translations`
- `GET /v1/audio/postprocess-profiles`

### Voxx voice catalog and provider-style routes
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
- The Compose runtime installs `espeak-ng`, `ffmpeg`, and MeloTTS dependencies so local `kokoro,melo,espeak` fallback order works without remote providers.
- MeloTTS is installed from GitHub in `Dockerfile.compose` because the PyPI `MeloTTS` sdist is incomplete; the image uses Python 3.11 plus CPU PyTorch/Torchaudio for Melo.
- `faster-whisper` is installed, but model weights may still download on first transcription use.
- Override the default API token with `VOICE_GATEWAY_API_KEY=... docker compose up --build` if you do not want the dev default.
- If port `8788` is already busy, run `VOXX_PORT=8798 docker compose up --build` (or choose another free host port).

## Deploy from pushes to `main`

A GitHub Actions pipeline now lives at:

- `.github/workflows/voxx-main.yml`

Flow:

1. On pull requests and pushes, run pytest and smoke-build `Dockerfile.compose`.
2. On `main`, publish `ghcr.io/<owner>/<repo>:main` and `ghcr.io/<owner>/<repo>:sha-<commit>`.
3. Over SSH, write a remote `.env.deploy` containing the immutable `VOXX_IMAGE=...:sha-<commit>` pin.
4. On the host, source the existing `.env` plus `.env.deploy`, pull the image, restart Voxx without rebuilding, and verify `/healthz`.

Required GitHub configuration:

### Repository variables
- `VOXX_DEPLOY_HOST`
- `VOXX_DEPLOY_USER`
- `VOXX_DEPLOY_PORT` (optional, default `22`)
- `VOXX_DEPLOY_PATH` (optional, default `/home/error/devel/services/voxx`)
- `VOXX_HEALTH_URL` (optional, default `http://127.0.0.1:8788/healthz`)

### Repository secrets
- `VOXX_DEPLOY_SSH_KEY`
- `VOXX_GHCR_USERNAME` (optional if the package is public)
- `VOXX_GHCR_TOKEN` (optional if the package is public)

Remote host expectations:
- `docker` + `docker compose` installed
- runtime lives in `~/devel/services/voxx`
- remote `.env` keeps runtime secrets/tokens
- workflow-owned `.env.deploy` only pins the image tag and should not be edited manually

## Smart TTS backend order

Voxx now chooses a backend order instead of hard-wiring itself to Melo/espeak only.

Default order when credentials exist:

1. `kokoro`
2. `xiaomi_mimo`
3. `requesty`
4. `openai`
5. `melo`
6. `espeak`

The workspace compose default is `kokoro,melo,espeak`. Agents should strongly prefer the local Voxx + Kokoro path and only opt into remote fallbacks when a task explicitly requires them.

Override the order explicitly with local fallbacks at the end. If you opt into a remote/free provider such as Xiaomi MiMo, keep Kokoro/Melo/eSpeak after it so quota, auth, 429, 402/403, or 5xx errors degrade locally instead of requiring prompt edits:

```bash
VOICE_GATEWAY_TTS_BACKEND_ORDER=xiaomi_mimo,kokoro,melo,espeak
# local-only stable default:
VOICE_GATEWAY_TTS_BACKEND_ORDER=kokoro,melo,espeak
```

Useful env knobs:

```bash
# provider order / timeouts / queue safety
VOICE_GATEWAY_TTS_BACKEND_ORDER=xiaomi_mimo,kokoro,melo,espeak
VOICE_GATEWAY_TTS_REMOTE_TIMEOUT_SECONDS=45
TTS_QUEUE_MAX_CONCURRENT=1
TTS_QUEUE_MAX_PENDING=32
TTS_QUEUE_TIMEOUT_SECONDS=120

# Xiaomi MiMo chat/audio bridge
XIAOMI_MIMO_API_BASE_URL=https://api.xiaomimimo.com/v1
XIAOMI_MIMO_API_KEY=...
XIAOMI_MIMO_TTS_MODEL=mimo-v2.5-tts
XIAOMI_MIMO_TTS_VOICE=mimo_default
XIAOMI_MIMO_TTS_STYLE=Speak naturally and clearly.

# Legacy typo-prefixed local env names still work while migrating:
XAIOMI_MIMO_API_BASE_URL=https://api.xiaomimimo.com/v1
XAIOMI_MIMO_API_KEY=...

# Kokoro OpenAI-compatible local sidecar
KOKORO_TTS_BASE_URL=http://kokoro:8880/v1/audio/speech
KOKORO_TTS_MODEL=kokoro
KOKORO_TTS_VOICE=af_bella_725_H

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
```

Voxx also exposes the backend actually used for a synthesis request through the response header:

- `x-openhax-tts-backend`

That lets callers keep pointing at Voxx while Voxx reports whether Kokoro, Xiaomi MiMo, Requesty, OpenAI, Melo, or eSpeak produced the audio.

## TTS postprocess + prompt-aware performance options

Yes: Voxx already had a conservative narrator-unifier lineage from `orgs/octave-commons/fork_tales/part64/code/tts_service.py`.

Voxx has a **final backend-agnostic postprocess stage** so the same mastering profiles can shape audio from any TTS backend, not just local Melo.

Default profile:

```bash
TTS_POSTPROCESS_ENABLED=1
TTS_POSTPROCESS_PROFILE=sports-commentator-v1
TTS_PROMPT_AWARE_DEFAULT=1
```

Available profile IDs and common aliases:

| Profile | Aliases | Use |
|---|---|---|
| `sutured-autotune-v1` | `sutured`, `suture`, `autotune`, `sovereign-suture` | opt-in musical robot speech with pitch lift, vibrato, echo, and tag-driven contours |
| `sports-commentator-v1` | `sports`, `commentator` | high-energy broadcast / sports announcing |
| `broadcast-warm-v1` | `broadcast`, `warm` | warmer conversational broadcast polish |
| `narrator-polish-v1` | `narrator`, `polish` | audiobook-style leveling and presence |
| `crisp-radio-v1` | `radio`, `crisp` | tight radio/dispatch intelligibility |
| `soft-studio-v1` | `soft`, `studio` | gentle cleanup for softer long-form speech |

List the current profile catalog through the API:

```bash
curl -H "Authorization: Bearer $VOICE_GATEWAY_API_KEY" \
  http://127.0.0.1:8787/v1/audio/postprocess-profiles
```

Set a global default with env vars, or override per request with query strings or JSON fields. These are equivalent:

```bash
curl -X POST 'http://127.0.0.1:8787/v1/audio/speech?postprocess_profile=radio&prompt_aware=1' \
  -H "Authorization: Bearer $VOICE_GATEWAY_API_KEY" \
  -H 'Content-Type: application/json' \
  --data '{"model":"kokoro","voice":"alloy","input":"[excited] They are making the comeback!","response_format":"mp3"}' \
  --output out.mp3

curl -X POST http://127.0.0.1:8787/v1/audio/speech \
  -H "Authorization: Bearer $VOICE_GATEWAY_API_KEY" \
  -H 'Content-Type: application/json' \
  --data '{"model":"kokoro","voice":"alloy","input":"[excited] They are making the comeback!","response_format":"mp3","postprocess_profile":"radio","prompt_aware":true}' \
  --output out.mp3
```

Request options:

| Option | Where | Values |
|---|---|---|
| `postprocess_profile` / `postprocessProfile` | query or JSON | profile ID or alias; `off`/`none` disables |
| `postprocess` | query or JSON | `0`/`false`/`off`, `1`/`true`, or a profile alias |
| `postprocess_enabled` / `postprocessEnabled` | query or JSON | explicit boolean override |
| `prompt_aware` / `promptAware` | query or JSON | `1`/`true` to enable tag-aware performance prompting |
| `prompt_aware_style` / `promptAwareStyle` | query or JSON | custom instruction for tag interpretation |

Prompt-aware mode is on by default (`TTS_PROMPT_AWARE_DEFAULT=1`) and can be disabled per request with `prompt_aware=false` or globally with `TTS_PROMPT_AWARE_DEFAULT=0`. When active, Voxx consumes bracketed/XML-like tags itself instead of forwarding them as spoken text. For example: `[excited]`, `[whisper]`, `[laugh]`, `[pause]`, `[dramatic]`, `[sing]`, `[stretch]`, `[glitch]`, `[suture]`, or `<break time="500ms" />`. Use tags sparingly at phrase boundaries: bracket tags select Voxx segment-level inflection filters, `[pause]` and `<break ... />` insert silence, and `[laugh]` inserts a short nonverbal effect. The upstream TTS backend receives clean segment text; Voxx then stitches the rendered segments together and applies the tag-driven postprocessing plus the final mastering profile. Musical tags log a `performance_directive` with pitch/tempo ratios and contour labels under the shared `render_id` so overprocessed or underpowered robot audio can be traced without guessing.

Responses include:

- `x-openhax-tts-postprocess-profile`: active final profile or `none`
- `x-openhax-tts-prompt-aware`: `1` when prompt-aware instructions were active, otherwise `0`
- `x-openhax-tts-queue-wait-ms`: how long this request waited for the bounded TTS processing queue
- `x-openhax-tts-queue-max-concurrent`: active queue concurrency cap

Disable it completely with:

```bash
TTS_POSTPROCESS_ENABLED=0
```

This means `xiaomi_mimo`, `kokoro`, `requesty`, `openai`, `melo`, and even `espeak` fallback outputs can all be pushed toward the same profile texture through Voxx. Use `sports-commentator-v1` for general energetic speech; use `sutured-autotune-v1` only when you intentionally want the recovered OpenPlanner/Sovereign-Suture-style pitch/time performance rather than clean narration.

## MeloTTS local fallback

Melo runs inside the Voxx application container and is selected by including `melo` in `VOICE_GATEWAY_TTS_BACKEND_ORDER`. The compose image installs:

- Python 3.11
- CPU PyTorch/Torchaudio from the PyTorch CPU wheel index
- MeloTTS from `https://github.com/myshell-ai/MeloTTS.git`
- UniDic and NLTK assets needed by `melo.api.TTS`

The PyPI `MeloTTS` package is not used because its source distribution is missing `requirements.txt` and fails to build. Validate Melo with:

```bash
VOICE_GATEWAY_TTS_BACKEND_ORDER=melo docker compose up -d --no-build voxx
curl -X POST 'http://127.0.0.1:8787/v1/audio/speech?postprocess=off' \
  -H "Authorization: Bearer ${VOICE_GATEWAY_API_KEY:-dev-token}" \
  -H 'Content-Type: application/json' \
  --data '{"model":"kokoro","voice":"alloy","input":"Melo local fallback check.","response_format":"mp3"}' \
  --output /tmp/voxx-melo.mp3
```

Restore the stable local chain after one-off validation:

```bash
VOICE_GATEWAY_TTS_BACKEND_ORDER=kokoro,melo,espeak docker compose up -d --no-build voxx
```

Melo is local and queue-protected. If a remote provider returns quota/status errors, keep callers on Voxx and let the backend order degrade to `melo` or `espeak` after Kokoro.

## Processing queue and runtime guardrails

TTS generation is protected by a bounded in-process queue so agent bursts do not fan out into unbounded provider/GPU/CPU work. Defaults are intentionally conservative for a workstation:

```bash
TTS_QUEUE_MAX_CONCURRENT=1
TTS_QUEUE_MAX_PENDING=32
TTS_QUEUE_TIMEOUT_SECONDS=120
```

The compose runtime pins Voxx and Kokoro containers to host CPUs `2-21` by default and requests all NVIDIA GPUs via Docker's GPU device request. Override CPU affinity only when the host has a different topology:

```bash
VOXX_CPUSET=2-21
NVIDIA_VISIBLE_DEVICES=all
NVIDIA_DRIVER_CAPABILITIES=compute,utility
```

`GET /healthz` includes queue state under `tts_queue`.

## Provider research snapshot

Quick 2026-03-20 findings from a live crawl of `models.dev` plus provider docs:

- **Cloudflare Workers AI / AI Gateway — MyShell MeloTTS**: models.dev lists `@cf/myshell-ai/melotts` / `workers-ai/@cf/myshell-ai/melotts` at `$0.00` listed token cost, making it the most interesting free-ish hosted fallback candidate to validate next.
- **Requesty**: already compatible with Voxx because it exposes an OpenAI-style `/v1/audio/speech` route; best current near-drop-in option when the token is available.
- **Google Gemini preview TTS** and **Qwen Omni audio models** show up in models.dev, but they are not free and/or are more audio-native than simple drop-in TTS today.
- **Kokoro** is the preferred local voice path for agents and compose deployments; remote backends remain optional fallbacks behind Voxx.

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
- Provider-style websocket routes are buffered convenience shims, not full upstream event parity.
- OpenAI Realtime API parity is intentionally out of scope for this first extraction pass.

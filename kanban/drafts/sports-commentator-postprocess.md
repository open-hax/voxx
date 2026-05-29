---
uuid: "orgs-open-hax-archived-voxx-kanban-orgs-open-hax-archived-voxx-specs-drafts-sports-commentator-postprocess-md"
title: "Voxx sports commentator postprocess"
status: incoming
priority: P3
labels: ["specs", "migrated-spec"]
created_at: "2026-05-29T04:01:22.562Z"
source: "orgs/open-hax/archived/voxx/specs/drafts/sports-commentator-postprocess.md"
category: "specs"
---

> Source: `orgs/open-hax/archived/voxx/specs/drafts/sports-commentator-postprocess.md`
> Migrated-to-kanban: `orgs/open-hax/archived/voxx/kanban/drafts/sports-commentator-postprocess.md`

# Voxx sports commentator postprocess

## Status
Complete

## Goal
Add a backend-agnostic post-processing pipeline in Voxx so any synthesized voice can be shaped toward a high-energy sports commentator sound, regardless of whether the upstream audio came from Kokoro, Melo, eSpeak, Requesty, OpenAI, or Xiaomi MiMo.

## Background
- Voxx already contains a conservative narrator unifier inherited from `orgs/octave-commons/fork_tales/part64/code/tts_service.py`.
- Today that shaping is applied only inside the local Melo synthesis path.
- Remote-provider voices currently bypass that styling and only get format conversion.
- The user wants a reusable commentator-style postprocess for any voice served through Voxx.

## Open questions
- None blocking for implementation. The safest first version is a conservative FFmpeg mastering chain, not aggressive stadium FX.

## Risks
- Over-aggressive FFmpeg filters can clip or distort speech.
- Applying filters only in one backend path would fail the “any voice” requirement.
- Missing FFmpeg must degrade safely to unprocessed output.

## Phases
1. Add config and helper support for a named postprocess profile.
2. Apply the profile during final audio conversion for all TTS backends.
3. Add tests covering enabled/disabled behavior.
4. Update env examples and docs for deploy/runtime use.

## Affected files
- `orgs/open-hax/voxx/src/voice_gateway/config.py`
- `orgs/open-hax/voxx/src/voice_gateway/audio_utils.py`
- `orgs/open-hax/voxx/src/voice_gateway/tts.py`
- `orgs/open-hax/voxx/tests/test_tts_fallback.py`
- `orgs/open-hax/voxx/.env.example`
- `orgs/open-hax/voxx/README.md`
- `services/voxx/.env.example`
- `services/voxx/compose.yaml`
- `services/voxx/README.md`

## Definition of done
- Voxx has an explicit sports-commentator postprocess profile.
- The profile is applied after any TTS backend, not just local Melo.
- FFmpeg absence fails open to unprocessed audio.
- Tests pass.
- Runtime docs show how to enable/override the profile.

## Implementation notes
- Added `TTS_POSTPROCESS_ENABLED` and `TTS_POSTPROCESS_PROFILE` config knobs.
- Added a final FFmpeg mastering chain for `sports-commentator-v1` and applied it during final conversion for all backends.
- Kept the existing local Melo narrator-unifier path in place; the new stage sits after backend synthesis so remote voices benefit too.
- Updated source + service env examples and runtime docs.

## Verification
- `cd orgs/open-hax/voxx && pnpm test`

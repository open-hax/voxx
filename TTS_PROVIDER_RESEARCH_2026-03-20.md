# Voxx TTS provider research — 2026-03-20

## Goal
Improve Battlebussy commentary voice quality without coupling Battlebussy directly to a single commercial TTS provider.

## Current operational facts
- Battlebussy commentary already talks to Voxx (`COMMENTARY_TTS_PROVIDER=voxx`).
- Deployed Voxx had only local Melo/espeak behavior configured before this pass.
- Local operator environment had `REQUESTY_API_TOKEN` available.
- `ELEVENLABS_API_KEY` was not present in the local shell or deployed commentary/Voxx containers during this pass.

## Immediate recommendation
Use Voxx as the stable API surface and let Voxx choose the best backend.

### Recommended order today
```env
VOICE_GATEWAY_TTS_BACKEND_ORDER=requesty,melo,espeak
```

Why:
- `requesty` gives materially better voice quality than raw local espeak fallback.
- `melo` remains a self-hosted fallback when the remote path fails.
- `espeak` remains the last-resort "never go silent" backend.

### Recommended order later, when the sponsored ElevenLabs voice is ready
```env
VOICE_GATEWAY_TTS_BACKEND_ORDER=elevenlabs,requesty,melo,espeak
ELEVENLABS_VOICE_ID=<exact-voice-id>
```

This preserves Battlebussy's integration point while allowing a premium final voice.

## Official/provider notes
### Requesty
- Best current "make do" path because it already exposes an OpenAI-compatible speech API.
- Voxx can call it as a backend without changing Battlebussy.
- Works with the current `nova` request path in our smoke tests.

### ElevenLabs
- Still the best destination for the final voice-specific product.
- Needs an actual `ELEVENLABS_API_KEY` plus the exact `ELEVENLABS_VOICE_ID` we want to standardize on.
- Voxx should treat it as the premium first-choice backend once the key/voice are available.

### Free / low-cost candidates worth future validation
The live `models.dev` crawl surfaced these noteworthy audio/TTS-adjacent candidates:

1. **Cloudflare Workers AI / AI Gateway — MyShell MeloTTS**
   - `@cf/myshell-ai/melotts`
   - `workers-ai/@cf/myshell-ai/melotts`
   - models.dev currently lists `$0.00` token cost for these rows.
   - Most interesting free-ish hosted fallback candidate to validate next.

2. **OpenCode Zen — MiMo V2 Omni Free**
   - `mimo-v2-omni-free`
   - Free row in models.dev, but omni/audio-native rather than a straightforward drop-in TTS target.

3. **Google Gemini preview TTS / native audio**
   - Present in models.dev, but not free.
   - Useful as a future quality benchmark rather than today's fallback target.

4. **Qwen Omni variants (Alibaba / Novita / SiliconFlow)**
   - Audio-capable and present in models.dev.
   - More exploratory than drop-in today; not as straightforward as Requesty or ElevenLabs for this specific stack.

## Strategic take
- **Now:** `requesty -> melo -> espeak`
- **Later:** `elevenlabs -> requesty -> melo -> espeak`
- **Next research target:** Cloudflare-hosted MyShell MeloTTS because it appears to be the strongest free-ish provider candidate discovered from models.dev during this pass.

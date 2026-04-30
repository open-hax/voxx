# Voxx agent guidance

- Use Voxx as the canonical voice boundary; do not wire direct voice-provider clients into agent code.
- Strongly prefer the local Kokoro backend for TTS: `VOICE_GATEWAY_TTS_BACKEND_ORDER=kokoro,melo,espeak`.
- Keep remote providers optional and behind Voxx only; document any explicit opt-in.

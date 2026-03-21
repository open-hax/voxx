# Voxx Melo postprocess benchmark on big.ussy + ussy2

## Status
Active

## Goal
Verify the current Voxx Melo deployment on `big.ussy.promethean.rest` (`pve.ussy.cloud`), compare Melo latency with and without the sports-commentator postprocess there, then deploy a comparable Voxx Melo runtime on `ussy2.promethean.rest` and run the same benchmark.

## Questions resolved
- **Does `big.ussy.promethean.rest` already have a Voxx instance?** Yes. It currently runs as a systemd service on the host tailnet IP `100.125.215.12:8788` with `VOICE_GATEWAY_TTS_BACKEND_ORDER=melo,espeak` and `TTS_POSTPROCESS_ENABLED=1`.
- **Can `error@big.ussy.promethean.rest` manage the existing systemd unit directly with sudo?** No passwordless sudo is available, but the service process runs as user `error`, so the user can still swap the user-owned `.env` and signal the running process for a managed restart.
- **Does `ussy2.promethean.rest` already have a Voxx runtime?** No. The host has Docker installed, but no Voxx runtime is present yet.
- **What deployment shape is safest for cross-host comparison?** A Python virtualenv + systemd deployment matching the existing big-host runtime keeps the Melo benchmark comparable across both machines.

## Known facts
- Current local source revision: `orgs/open-hax/voxx` @ `7df28c5` on `main`.
- `big.ussy.promethean.rest` resolves to `pve.ussy.cloud` with 4 vCPU / 15 GiB RAM, no Docker, Python 3.11, ffmpeg present, and an active Voxx service.
- `ussy2.promethean.rest` is an Ubuntu host with 2 vCPU / 14 GiB RAM, Docker present, Python 3.12, ffmpeg absent, and passwordless sudo available for `error`.
- The postprocess toggle to compare is `TTS_POSTPROCESS_ENABLED` while keeping the Melo backend itself constant.
- The existing big-host Voxx service is live, so any postprocess-off measurement there must restore the original postprocess-on state after benchmarking.

## Risks observed
- Big host memory is already tight enough that running a second eager-loaded Melo process concurrently is risky; the comparison there should reuse the existing service rather than add a second copy.
- Restart-based benchmarking on big temporarily changes the live service voice profile and introduces short availability gaps while the model warms.
- ussy2 has fewer CPU cores than big, so realtime factor may regress materially even with the same software stack.
- The Melo dependency chain is brittle enough that matching the previously working Python package set matters more than chasing the newest versions.

## Plan
1. Record receipts and verify the local source with `pnpm test`.
2. Add a small reproducible benchmark helper that hits `/v1/audio/speech`, measures latency, derives duration with `ffprobe`, and writes JSON summaries.
3. Benchmark the existing big-host runtime in its current postprocess-on state.
4. Temporarily switch big-host Voxx to `TTS_POSTPROCESS_ENABLED=0`, wait for health, run the same benchmark, then restore the original postprocess-on config.
5. Deploy current Voxx source to `ussy2.promethean.rest` as a systemd-managed Python virtualenv service using the same Melo-first configuration pattern.
6. Run the same on/off benchmark sequence on ussy2, leaving that host in the postprocess-on state afterward.
7. Copy benchmark artifacts back into the repo, update this spec with results, and append verification receipts.

## Benchmark shape
- Endpoint: `POST /v1/audio/speech`
- Voice: `nova`
- Speed: `1.05`
- Response format: `mp3`
- Backend target: `melo`
- Samples: 5 short + 5 medium + 5 long unique announcer-style lines
- Outputs:
  - cold-ish restart readiness + first-request timing for each variant
  - warm unique-request latency, duration, and realtime factor summary per bucket

## Affected files
- `orgs/open-hax/voxx/specs/drafts/big-ussy-ussy2-melo-postprocess-benchmark.md`
- `orgs/open-hax/voxx/scripts/benchmark_openai_speech.py`
- `orgs/open-hax/voxx/receipts.log`
- benchmark result JSON artifacts copied back from remote hosts

## Definition of done
- Big-host Voxx deployment is verified, benchmarked with postprocess on and off, and restored to postprocess on.
- ussy2 has a working Melo-capable Voxx runtime and benchmark results for postprocess on and off.
- Benchmark artifacts are saved in the repo with host + variant labels.
- The spec records the method, results, and operational caveats honestly.

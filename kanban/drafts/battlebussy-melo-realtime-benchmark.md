---
uuid: "orgs-open-hax-archived-voxx-kanban-orgs-open-hax-archived-voxx-specs-drafts-battlebussy-melo-realtime-benchmark-md"
title: "Voxx Melo deployment + Battlebussy realtime benchmark"
status: incoming
priority: P3
labels: ["specs", "migrated-spec"]
created_at: "2026-05-29T04:01:22.559Z"
source: "orgs/open-hax/archived/voxx/specs/drafts/battlebussy-melo-realtime-benchmark.md"
category: "specs"
---

> Source: `orgs/open-hax/archived/voxx/specs/drafts/battlebussy-melo-realtime-benchmark.md`
> Migrated-to-kanban: `orgs/open-hax/archived/voxx/kanban/drafts/battlebussy-melo-realtime-benchmark.md`

# Voxx Melo deployment + Battlebussy realtime benchmark

## Status
Complete

## Goal
Deploy `orgs/open-hax/voxx` with the local `melo` TTS backend on `pve.ussy.cloud`, then benchmark end-to-end synthesis latency to judge whether it is acceptable for Battlebussy realtime announcements.

## Questions resolved
- **Is CPU-only Melo on this host fast enough for short/medium commentary lines?** Yes, when the service is already warm. Warm unique-request realtime factor stayed below `1.0` in every measured bucket.
- **Does the remote host need a permanent service, or is a benchmark-only deployment sufficient for now?** A permanent localhost-bound service is the right shape; cold start is noticeably slower than steady-state.
- **Are Battlebussy announcements short enough that warm performance matters more than cold-start latency?** Yes. The steady-state numbers are acceptable for sequential announcer lines, but a restart or first-hit penalty is still significant.

## Known facts
- Remote host: Debian 12 / Proxmox 8.4, 4 vCPU, 15 GiB RAM, no GPU.
- Docker is not installed on the host, so deployment used a Python virtualenv + `systemd` service rather than compose.
- `battlebussy` already supports `voxx` as a commentary TTS provider and points at an OpenAI-compatible `/v1/audio/speech` endpoint.
- Deployed source revision: `orgs/open-hax/voxx` @ `c682b8f` on `main`.

## Deployment shape
- Remote app dir: `/home/error/devel/services/voxx`
- Remote env file: `/home/error/devel/services/voxx/.env`
- Remote service unit: `/etc/systemd/system/voxx.service`
- Bind address: `127.0.0.1:8788`
- Forced backend order: `melo,espeak`
- TTS device: `cpu`
- Voice used for benchmark: `nova`
- Response format used for benchmark: `mp3`
- Battlebussy-compatible base URL: `http://127.0.0.1:8788/v1/audio/speech`

## Risks observed
- MeloTTS host installation was somewhat brittle: modern `setuptools` dropped `pkg_resources`, so the runtime needed `setuptools<81` for the Melo/librosa path.
- Cold startup is not realtime-friendly. After restart, the service took ~14.45s to become healthy and the first synthesis request still ran slower than realtime.
- This benchmark only covered sequential single-request commentary, not concurrent burst traffic.

## Plan executed
1. Verified `voxx` source locally with `pnpm test`.
2. Prepared the remote host with required Debian packages.
3. Copied the repo into `~/devel/services/voxx` and created a Python virtualenv deployment.
4. Installed MeloTTS dependencies, model assets, and supporting audio/NLP packages.
5. Configured a localhost-bound `systemd` service that forces Melo first.
6. Verified `/healthz` and a real `/v1/audio/speech` request with `x-openhax-tts-backend: melo`.
7. Benchmarked representative Battlebussy-style short/medium/long announcer lines.

## Benchmark results
### Cold-ish startup behavior
Measured after `systemctl restart voxx`:
- Health ready: `14.45s`
- First request latency: `7.03s`
- First request audio duration: `5.17s`
- First request realtime factor: `1.36`
- Backend header: `melo`

### Warm unique-request behavior
All measured requests were unique commentary lines, not cache hits.

| Bucket | Count | Avg latency | P50 latency | Avg audio duration | Avg realtime factor | Best | Worst |
|---|---:|---:|---:|---:|---:|---:|---:|
| short | 5 | 3.20s | 3.06s | 4.24s | 0.755 | 0.666 | 0.826 |
| medium | 5 | 5.54s | 5.53s | 7.17s | 0.773 | 0.677 | 0.852 |
| long | 5 | 10.89s | 11.46s | 12.50s | 0.867 | 0.798 | 0.961 |

Interpretation:
- `rtf < 1.0` means audio was synthesized faster than playback length.
- Warm short and medium Battlebussy-style lines comfortably beat realtime.
- Warm long calls are close to realtime but still stayed under `1.0` in this run.

## Verification
- Local source verification: `cd orgs/open-hax/voxx && pnpm test`
- Remote health check: `GET http://127.0.0.1:8788/healthz`
- Remote speech verification: `POST http://127.0.0.1:8788/v1/audio/speech`
- Verified response header: `x-openhax-tts-backend: melo`
- Benchmark artifact on host: `/home/error/devel/services/voxx/benchmark-results-battlebussy-melo.json`

## Conclusion
**Yes, with caveats:** this host is acceptable for Battlebussy realtime announcements **if Voxx stays running and warm**.

Why:
- Warm single-request Melo synthesis stayed faster than playback for short, medium, and even the tested long announcer lines.
- Battlebussy’s commentary loop sends one line at a time to the Voxx OpenAI-compatible endpoint, which matches the benchmarked path.

Caveats:
- A fresh restart is not realtime-safe; first-hit latency was slower than audio duration.
- I would not rely on this host for heavy concurrent commentary generation without another round of benchmarking.
- If extremely tight latency is required after restarts, a remote provider or pre-generated intro/break scripts would still be safer.

## Affected files
- `orgs/open-hax/voxx/specs/drafts/battlebussy-melo-realtime-benchmark.md`
- `orgs/open-hax/voxx/benchmark-results-battlebussy-melo-pve-ussy-cloud-2026-03-21.json`
- `orgs/open-hax/voxx/receipts.log`

## Definition of done
- Voxx is running on the remote host with the local Melo backend available.
- Health and speech synthesis both succeed on the remote host.
- Benchmark results include cold-start and warm-request latency plus audio duration-derived realtime factor.
- A conclusion is recorded on whether this host is acceptable for Battlebussy realtime announcements.

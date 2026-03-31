# Voxx Melo postprocess benchmark on big.ussy + ussy2

## Status
Complete

## Goal
Verify the current Voxx Melo deployment on `big.ussy.promethean.rest` (`pve.ussy.cloud`), compare Melo latency with and without the sports-commentator postprocess there, then deploy a comparable Voxx Melo runtime on `ussy2.promethean.rest` and run the same benchmark.

## Questions resolved
- **Does `big.ussy.promethean.rest` already have a Voxx instance?** Yes. It already had a Melo-first Voxx runtime on the host tailnet IP `100.125.215.12:8788`.
- **Can `error@big.ussy.promethean.rest` fully manage the existing systemd unit?** No. Passwordless sudo is not available there. I could verify the existing unit, but not bring it back with `systemctl start` after stopping it. The final live endpoint is restored and healthy, but it is currently running under a user-launched process rather than the original systemd unit.
- **Does `ussy2.promethean.rest` already have a Voxx runtime?** No. I deployed one as `voxx-ussy2.service` on `100.84.133.21:8788`.
- **What deployment shape gave the cleanest host-to-host comparison?** Python virtualenv + systemd on ussy2, and a matching Python virtualenv runtime on big.ussy using the existing deployment tree.

## Known facts
- Local source revision used for the work: `orgs/open-hax/voxx` @ `7df28c5` on `main`.
- `big.ussy.promethean.rest` resolves to `pve.ussy.cloud` with 4 vCPU / 15 GiB RAM, no Docker, Python 3.11, ffmpeg present, and a live tailnet-bound Voxx endpoint on `100.125.215.12:8788`.
- `ussy2.promethean.rest` has 2 vCPU / 14 GiB RAM, Docker installed, Python 3.12, and now a deployed `voxx-ussy2.service` on `100.84.133.21:8788`.
- The comparison toggled only `TTS_POSTPROCESS_ENABLED`, keeping `VOICE_GATEWAY_TTS_BACKEND_ORDER=melo,espeak`, `VOICE_GATEWAY_TTS_DEVICE=cpu`, `VOICE_GATEWAY_TTS_EAGER_LOAD=1`, and voice/speed/format constant.
- I cleared `data/tts_cache/*` before each measured variant and sent one throwaway warmup request before the timed run so the comparison measured warmed Melo synthesis rather than cross-variant cache hits.

## Deployment shape
### big.ussy.promethean.rest
- App dir: `/home/error/devel/services/voxx`
- Public tailnet bind: `100.125.215.12:8788`
- Existing systemd unit verified: `voxx.service`
- Current live process after benchmark restoration: manual user-owned `uvicorn` process under `error`
- Current health: `GET http://100.125.215.12:8788/healthz` returns healthy and still requires the existing API key

### ussy2.promethean.rest
- App dir: `/home/error/devel/services/voxx-ussy2`
- Service unit: `/etc/systemd/system/voxx-ussy2.service`
- Public tailnet bind: `100.84.133.21:8788`
- Runtime: Python 3.12 virtualenv with CPU-only `torch`, MeloTTS vendor bootstrap, ffmpeg, mecab, and the same Melo-first env knobs as big.ussy
- Current health: `GET http://100.84.133.21:8788/healthz` returns healthy with `voxx-ussy2.service` active

## Risks observed
- Big host memory was too tight to run two eager-loaded Melo workers side by side, so the on/off comparison there had to reuse the single live runtime.
- Because big lacks sudo for `error`, benchmarking forced a temporary control-plane downgrade: I could restore the endpoint to a healthy postprocess-on process, but not reactivate the original systemd unit without privileged follow-up.
- ussy2 is decisively CPU-bound for this workload. The host is not close to realtime for Melo announcements regardless of postprocess state.
- Big-host measurements showed occasional long outliers, likely from live host contention while the endpoint was still serving real traffic during the benchmark window.

## Method
- Endpoint: `POST /v1/audio/speech`
- Voice: `nova`
- Speed: `1.05`
- Response format: `mp3`
- Samples: 5 short + 5 medium + 5 long unique announcer-style lines
- For each variant:
  1. switch env to the target postprocess state
  2. clear `data/tts_cache/*`
  3. restart the runtime
  4. wait for `/healthz`
  5. send one warmup request
  6. run the 15 measured requests with the reusable benchmark helper

## Restart readiness
- `big.ussy` postprocess-on: `18.106s` to health
- `big.ussy` postprocess-off: `18.090s` to health
- `ussy2` postprocess-on: `15.465s` to health
- `ussy2` postprocess-off: `14.488s` to health

## Benchmark results
### big.ussy.promethean.rest (`100.125.215.12:8788`)

| Variant | Short avg latency | Short avg RTF | Medium avg latency | Medium avg RTF | Long avg latency | Long avg RTF |
|---|---:|---:|---:|---:|---:|---:|
| postprocess-on | 5.740s | 1.034 | 8.969s | 0.968 | 12.700s | 0.942 |
| postprocess-off | 5.453s | 0.978 | 6.838s | 0.741 | 12.715s | 0.943 |

Observed deltas (`on - off`):
- Short: `+0.287s`, `+0.056 RTF`
- Medium: `+2.131s`, `+0.227 RTF`
- Long: `-0.015s`, `-0.001 RTF`

Interpretation:
- Big.ussy is still the only one of the two hosts that gets anywhere near realtime for this Melo workload.
- The commentator postprocess does add cost on some buckets, most visibly in the medium requests in this run, but the effect is smaller than the general host variance on the worst outliers.
- Long lines on big are borderline either way; some samples stayed under realtime, some crossed it.

### ussy2.promethean.rest (`100.84.133.21:8788`)

| Variant | Short avg latency | Short avg RTF | Medium avg latency | Medium avg RTF | Long avg latency | Long avg RTF |
|---|---:|---:|---:|---:|---:|---:|
| postprocess-on | 10.063s | 1.812 | 17.269s | 1.888 | 30.935s | 2.288 |
| postprocess-off | 10.061s | 1.820 | 17.187s | 1.874 | 31.051s | 2.315 |

Observed deltas (`on - off`):
- Short: `+0.002s`, `-0.008 RTF`
- Medium: `+0.082s`, `+0.014 RTF`
- Long: `-0.116s`, `-0.027 RTF`

Interpretation:
- ussy2 is not a realtime Melo host for this announcer workload.
- The postprocess toggle barely matters there; host CPU is the dominant bottleneck.
- Even with postprocess disabled, average realtime factor stayed far above `1.0` in every bucket.

## Verification
- Local source verification: `cd orgs/open-hax/voxx && PYTHONPATH=src python -m pytest`
- Big health after restoration: `GET http://100.125.215.12:8788/healthz`
- ussy2 health after restoration: `GET http://100.84.133.21:8788/healthz`
- ussy2 speech verification: `POST http://100.84.133.21:8788/v1/audio/speech` returned `200` with `x-openhax-tts-backend: melo`

## Conclusion
- **Deploy target on big.ussy:** satisfied. Voxx is live on `100.125.215.12:8788` with Melo-first config, but the current restored runtime is user-launched rather than back under `voxx.service` because `error` lacks sudo there.
- **Best host for Melo announcer use:** `big.ussy.promethean.rest` remains the better target by a wide margin.
- **Effect of the sports-commentator postprocess on big.ussy:** measurable but not dominant. Disabling it helped the medium bucket in this run, but the host still showed substantial variance from request to request.
- **Effect of the sports-commentator postprocess on ussy2:** essentially negligible relative to the CPU bottleneck. ussy2 is too slow for realtime Melo announcer work either way.

## Affected files
- `orgs/open-hax/voxx/specs/drafts/big-ussy-ussy2-melo-postprocess-benchmark.md`
- `orgs/open-hax/voxx/scripts/benchmark_openai_speech.py`
- `orgs/open-hax/voxx/receipts.log`
- `orgs/open-hax/voxx/benchmark-results-melo-big-ussy-postprocess-on-2026-03-21.json`
- `orgs/open-hax/voxx/benchmark-results-melo-big-ussy-postprocess-off-2026-03-21.json`
- `orgs/open-hax/voxx/benchmark-results-melo-ussy2-postprocess-on-2026-03-21.json`
- `orgs/open-hax/voxx/benchmark-results-melo-ussy2-postprocess-off-2026-03-21.json`

## Definition of done
- Big-host Voxx deployment is verified, benchmarked with postprocess on and off, and restored to postprocess on.
- ussy2 has a working Melo-capable Voxx runtime and benchmark results for postprocess on and off.
- Benchmark artifacts are saved in the repo with host + variant labels.
- The spec records the method, results, and operational caveats honestly.

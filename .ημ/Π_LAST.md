# Π handoff

- time: 2026-03-21T21:33:31Z
- branch: main
- pre-Π HEAD: 7df28c5
- Π HEAD: pending at capture time; resolved by the final commit after artifact assembly

## Summary
- Add the source-side benchmark harness scripts/benchmark_openai_speech.py and the big.ussy/ussy2 Melo postprocess benchmark draft for reproducible cross-host comparison work.
- Refresh receipts and .ημ handoff artifacts so the root workspace can carry the exact Voxx benchmark-planning snapshot.

## Notes
- push branch: pi/fork-tax/2026-03-21-211345
- origin remains git@github.com:open-hax/voxx.git; snapshot published on a dedicated Π branch plus tag.

## Verification
- pass: pnpm test (12 passed)
- pass: python3 -m py_compile scripts/benchmark_openai_speech.py

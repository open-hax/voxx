#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Final


PROMPTS: Final[dict[str, tuple[str, ...]]] = {
    "short": (
        "Welcome back to Battlebussy, where the arena is hot and the next clash is seconds away!",
        "Huge knockback to center stage and the crowd knows this round just turned brutal!",
        "That dodge was filthy, that punish was immediate, and momentum just flipped hard!",
        "Blue side steals the pickup, powers the combo, and suddenly the whole bracket is shaking!",
        "One clean confirm, one roaring finish, and the fans are absolutely losing it right now!",
    ),
    "medium": (
        "What a swing in the lane fight: red side looked cornered for a full ten seconds, then snapped back with perfect timing and turned defense into a full-court punish.",
        "You can feel the tension climbing because every pickup matters now, every reposition matters now, and one sloppy engage could hand the whole set to the other side.",
        "That was textbook pressure into chaos: quick spacing, instant conversion, and then a relentless finish that left the rest of the lobby scrambling to recover.",
        "Battlebussy is at its loudest when momentum changes this fast, and right now the winning side is stacking confidence with every clean rotation and every sharp read.",
        "If they keep chaining these short explosive bursts together, the other squad is going to run out of answers before the next checkpoint even appears.",
    ),
    "long": (
        "This is the exact kind of Battlebussy sequence the fans replay all night long: a risky approach at mid, a scramble around the objective, and then a perfectly timed counterburst that turns a messy brawl into a statement play with championship energy.",
        "The pressure is building across the whole map now because every movement has consequences, every missed punish opens a lane, and the squad with the hotter hands is starting to sound like a freight train rolling straight through the bracket.",
        "Listen to the rhythm of this round: quick engage, clean disengage, another explosive re-entry, and then a thunderous finish that makes it obvious one team is reading the flow a full beat faster than everyone else in the arena.",
        "When Battlebussy gets this dramatic, the announcer barely has time to breathe: one side steals space, the other side steals tempo, and then somebody lands a finishing sequence so violent the crowd erupts before the scoreboard can even catch up.",
        "This is turning into a pure endurance test, because the attacks are still sharp, the reactions are still instant, and the team that keeps landing these high-energy conversions is making the whole match feel like a runaway headline.",
    ),
}


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(ratio * len(ordered)) - 1))
    return ordered[index]


class BenchmarkError(RuntimeError):
    pass


def audio_duration_seconds(audio_bytes: bytes, suffix: str) -> float:
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as handle:
        handle.write(audio_bytes)
        handle.flush()
        command = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            handle.name,
        ]
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
    return float((completed.stdout or "0").strip() or "0")


def request_speech(
    *,
    base_url: str,
    text: str,
    model: str,
    voice: str,
    speed: float,
    response_format: str,
    api_key: str,
    timeout_seconds: float,
) -> tuple[bytes, float, str]:
    payload = json.dumps(
        {
            "model": model,
            "input": text,
            "voice": voice,
            "response_format": response_format,
            "speed": speed,
        }
    ).encode("utf-8")
    headers = {
        "content-type": "application/json",
        "accept": "*/*",
    }
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/v1/audio/speech",
        data=payload,
        headers=headers,
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            audio_bytes = response.read()
            backend = str(response.headers.get("x-openhax-tts-backend", "") or "")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise BenchmarkError(f"HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise BenchmarkError(str(exc)) from exc
    latency = time.perf_counter() - started
    return audio_bytes, latency, backend


def build_summary(results: list[dict[str, object]]) -> dict[str, dict[str, float | int]]:
    summary: dict[str, dict[str, float | int]] = {}
    for bucket in PROMPTS:
        bucket_rows = [row for row in results if row["bucket"] == bucket]
        latencies = [float(row["latency_s"]) for row in bucket_rows]
        durations = [float(row["duration_s"]) for row in bucket_rows]
        rtfs = [float(row["rtf"]) for row in bucket_rows]
        summary[bucket] = {
            "count": len(bucket_rows),
            "latency_avg_s": round(statistics.fmean(latencies), 3) if latencies else 0.0,
            "latency_p50_s": round(statistics.median(latencies), 3) if latencies else 0.0,
            "latency_p95_s": round(percentile(latencies, 0.95), 3) if latencies else 0.0,
            "duration_avg_s": round(statistics.fmean(durations), 3) if durations else 0.0,
            "rtf_avg": round(statistics.fmean(rtfs), 3) if rtfs else 0.0,
            "rtf_best": round(min(rtfs), 3) if rtfs else 0.0,
            "rtf_worst": round(max(rtfs), 3) if rtfs else 0.0,
        }
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark Voxx/OpenAI-compatible speech synthesis.")
    parser.add_argument("--base-url", required=True, help="Base URL without the /v1/audio/speech suffix")
    parser.add_argument("--host-label", required=True, help="Human-readable host label for the output JSON")
    parser.add_argument("--variant", required=True, help="Benchmark variant label, e.g. postprocess-on")
    parser.add_argument("--output", required=True, help="Path to the JSON output file")
    parser.add_argument("--voice", default="nova")
    parser.add_argument("--speed", type=float, default=1.05)
    parser.add_argument("--model", default="gpt-4o-mini-tts")
    parser.add_argument("--response-format", default="mp3")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, object]] = []
    for bucket, prompts in PROMPTS.items():
        for index, text in enumerate(prompts, start=1):
            audio_bytes, latency_s, backend = request_speech(
                base_url=args.base_url,
                text=text,
                model=args.model,
                voice=args.voice,
                speed=args.speed,
                response_format=args.response_format,
                api_key=args.api_key,
                timeout_seconds=args.timeout_seconds,
            )
            duration_s = audio_duration_seconds(audio_bytes, f".{args.response_format}")
            rtf = (latency_s / duration_s) if duration_s > 0 else 0.0
            results.append(
                {
                    "bucket": bucket,
                    "index": index,
                    "text": text,
                    "latency_s": latency_s,
                    "duration_s": duration_s,
                    "rtf": rtf,
                    "backend": backend,
                    "bytes": len(audio_bytes),
                }
            )
            print(
                f"{bucket}#{index}: latency={latency_s:.3f}s duration={duration_s:.3f}s rtf={rtf:.3f} backend={backend}",
                file=sys.stderr,
                flush=True,
            )

    payload = {
        "ts": datetime.now(UTC).isoformat(),
        "host": args.host_label,
        "variant": args.variant,
        "base_url": args.base_url,
        "voice": args.voice,
        "speed": args.speed,
        "model": args.model,
        "response_format": args.response_format,
        "results": results,
        "summary": build_summary(results),
    }
    output_path.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BenchmarkError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)

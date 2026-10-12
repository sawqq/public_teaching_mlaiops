"""Lab 4 — the steps of cd.yml, each a thin call through the CloudAdapter seam.

    python scripts/cd_steps.py push   --tag itcs355-serve:<sha>
    python scripts/cd_steps.py deploy --model-ref <repo@sha256:...> --endpoint NAME --instance TYPE
    python scripts/cd_steps.py smoke  --endpoint <resource name> --expect-version <sha>

Nothing here knows which cloud it runs on: it only calls adapter.push_image / deploy / invoke,
so the same workflow survives a provider swap. Each step writes `key=value` to
$GITHUB_OUTPUT (when set) so the next step can use the result.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cloudlayer.factory import get_adapter  # noqa: E402
from src import config  # noqa: E402

# Three known inputs: a machine that should look healthy, the load-test payload, and a worn,
# hot one. The checks are about shape and ordering, not exact numbers, so they stay valid
# when the model is retrained.
HEALTHY = {"temp_c": 66.0, "vibration_mm_s": 1.4, "pressure_kpa": 330.0,
           "hours_since_service": 50.0, "load_pct": 30.0, "ambient_humidity": 50.0}
TYPICAL = {"temp_c": 78.4, "vibration_mm_s": 3.1, "pressure_kpa": 315.2,
           "hours_since_service": 4200.0, "load_pct": 68.0, "ambient_humidity": 55.0}
WORN = {"temp_c": 82.0, "vibration_mm_s": 4.0, "pressure_kpa": 310.0,
        "hours_since_service": 8500.0, "load_pct": 75.0, "ambient_humidity": 60.0}


def set_output(key: str, value: str) -> None:
    print(f"{key}={value}")
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{key}={value}\n")


def push(adapter, tag: str) -> int:
    ref = adapter.push_image(tag)
    if "@sha256:" not in ref:
        print(f"FAIL  push_image returned {ref!r}; expected a digest reference (repo@sha256:...)")
        return 1
    set_output("ref", ref)
    return 0


def deploy(adapter, model_ref: str, endpoint: str, instance: str) -> int:
    resource = adapter.deploy(model_ref, endpoint, instance)
    set_output("endpoint", resource)
    return 0


def smoke(adapter, endpoint: str, expect_version: str) -> int:
    """A deploy that is not smoke-tested is a deploy you have not verified."""
    failures = []
    scores = {}
    for name, payload in (("healthy", HEALTHY), ("typical", TYPICAL), ("worn", WORN)):
        response = adapter.invoke(endpoint, payload)
        prob = response.get("probability")
        version = response.get("model_version")
        scores[name] = prob
        if not isinstance(prob, (int, float)) or not 0.0 <= prob <= 1.0:
            failures.append(f"{name}: probability missing or outside [0, 1]: {prob!r}")
        if version != expect_version:
            failures.append(f"{name}: serving version {version!r}, expected {expect_version!r}")
    if not failures and scores["healthy"] >= scores["worn"]:
        failures.append(f"ordering: healthy scored {scores['healthy']:.3f}, "
                        f"worn {scores['worn']:.3f}; risk should be higher for the worn machine")
    print("scores:", {k: (round(v, 4) if isinstance(v, (int, float)) else v) for k, v in scores.items()})
    if failures:
        for line in failures:
            print("FAIL ", line)
        return 1
    print(f"OK  3/3 payloads scored by version {expect_version}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="step", required=True)

    p = sub.add_parser("push")
    p.add_argument("--tag", required=True)

    d = sub.add_parser("deploy")
    d.add_argument("--model-ref", required=True)
    d.add_argument("--endpoint", required=True)
    d.add_argument("--instance", required=True)

    s = sub.add_parser("smoke")
    s.add_argument("--endpoint", required=True)
    s.add_argument("--expect-version", required=True)

    args = ap.parse_args()
    adapter = get_adapter(config.load())
    if args.step == "push":
        return push(adapter, args.tag)
    if args.step == "deploy":
        return deploy(adapter, args.model_ref, args.endpoint, args.instance)
    return smoke(adapter, args.endpoint, args.expect_version)


if __name__ == "__main__":
    raise SystemExit(main())

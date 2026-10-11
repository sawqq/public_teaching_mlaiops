"""Lab 4 — measure the PSI noise floor, so the drift threshold has a reason.

    python scripts/calibrate_drift_threshold.py

A threshold copied from a tutorial is not a justified threshold. This script gives you the
two numbers a justification needs:

  1. the NOISE FLOOR: how large PSI gets between the reference window and a fresh window
     drawn from the SAME process (different seed, so different machines), for a given
     number of production rows. Anything below this is normal variance.
  2. the SIGNAL: the PSI produced by the drift you actually injected (make inject-drift).

The threshold goes above the first and well below the second. State both in the README.
Window size matters: PSI on few rows is noisy, so the same threshold means different
things for 200 rows and for 5000.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from monitoring.drift import psi  # noqa: E402
from scripts.make_dataset import build  # noqa: E402
from src import data  # noqa: E402

REFERENCE_SEED = 20260101
WINDOW_SIZES = (200, 500, 1000, 2000)
FRESH_DATASETS = 40          # independent draws of the process (new machines each time)
WINDOWS_PER_DATASET = 5
INJECT_FEATURE, INJECT_SHIFT = "temp_c", 6.0   # the default of `make inject-drift`


def max_psi(reference, window) -> float:
    """Worst feature in the window — the detector alerts if ANY feature crosses."""
    return max(
        psi(reference[f].to_numpy(float), window[f].to_numpy(float)) for f in data.FEATURES
    )


def main() -> int:
    rng = np.random.default_rng(0)
    reference = build(REFERENCE_SEED)
    fresh = [build(1000 + i) for i in range(FRESH_DATASETS)]

    print(f"reference rows={len(reference)}  fresh datasets={FRESH_DATASETS}  "
          f"windows per size={FRESH_DATASETS * WINDOWS_PER_DATASET}\n")
    print(f"{'window rows':>12}{'noise p50':>11}{'noise p95':>11}{'noise p99':>11}{'noise max':>11}"
          f"{'injected PSI':>14}")

    for n in WINDOW_SIZES:
        noise = []
        for df in fresh:
            for _ in range(WINDOWS_PER_DATASET):
                noise.append(max_psi(reference, df.sample(n=n, random_state=int(rng.integers(1 << 31)))))
        noise = np.array(noise)

        shifted = []
        for df in fresh[:10]:
            w = df.sample(n=n, random_state=int(rng.integers(1 << 31))).copy()
            w[INJECT_FEATURE] = w[INJECT_FEATURE] + INJECT_SHIFT
            shifted.append(max_psi(reference, w))

        print(f"{n:>12}{np.percentile(noise, 50):>11.3f}{np.percentile(noise, 95):>11.3f}"
              f"{np.percentile(noise, 99):>11.3f}{noise.max():>11.3f}{np.median(shifted):>14.3f}")

    print("\nnoise = worst-feature PSI between the reference and a window with NO real change.")
    print(f"injected = worst-feature PSI after shifting {INJECT_FEATURE} by +{INJECT_SHIFT}.")
    print("Pick a threshold above 'noise p99' for your window size and well below 'injected'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Lab 4 — the scheduled drift run. This is what Cloud Scheduler triggers.

    python scripts/drift_job.py \
        --reference-uri gs://<bucket>/itcs355/drift/reference.csv \
        --current-uri   gs://<bucket>/itcs355/drift/current.csv

Downloads both windows through the adapter, scores PSI per feature with the same code as
`python -m monitoring.drift`, and writes each score as the metric drift.psi.<feature>.

It exits 0 whenever the job itself worked, even when drift was found. The alert comes from
the metric alert policy (monitoring/gcp/setup.sh), which is what sends the email. If this
exited non-zero on drift, the scheduler would record a failed run and nobody would learn
the one thing the job exists to say.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cloudlayer.factory import get_adapter  # noqa: E402
from monitoring.drift import DRIFT_ALERT_PSI, MIN_WINDOW_ROWS, compare  # noqa: E402
from src import config, data  # noqa: E402


def run(adapter, reference_uri: str, current_uri: str) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        ref_path, cur_path = Path(tmp) / "reference.csv", Path(tmp) / "current.csv"
        adapter.download(reference_uri, str(ref_path))
        adapter.download(current_uri, str(cur_path))
        reference, current = pd.read_csv(ref_path), pd.read_csv(cur_path)

    if len(current) < MIN_WINDOW_ROWS:
        print(f"SKIP  {len(current)} rows in the current window; need {MIN_WINDOW_ROWS}+ for PSI "
              f"to be meaningful at threshold {DRIFT_ALERT_PSI}")
        return 0

    results = compare(reference, current, data.FEATURES)
    for r in results:
        adapter.emit_metric(f"drift.psi.{r.feature}", r.psi)
        print(f"{r.feature:<22} psi={r.psi:.5f}  ks={r.ks_statistic:.5f}  {r.verdict}")

    breached = [r.feature for r in results if r.psi >= DRIFT_ALERT_PSI]
    if breached:
        print(f"DRIFT  above {DRIFT_ALERT_PSI}: {', '.join(breached)}  (alert policy sends the email)")
    else:
        print(f"OK  no feature above {DRIFT_ALERT_PSI}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reference-uri", required=True)
    ap.add_argument("--current-uri", required=True)
    args = ap.parse_args()
    return run(get_adapter(config.load()), args.reference_uri, args.current_uri)


if __name__ == "__main__":
    raise SystemExit(main())

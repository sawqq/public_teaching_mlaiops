"""Lab 5 — register a candidate that passed the gate, and record it as the champion.

    python scripts/register.py --model-uri gs://.../model --ref-out /tmp/model_ref

`--model-uri` is a directory holding model.joblib and metrics.json (the pipeline's
train step writes both). The champion record is what scripts/evaluation_gate.py reads
as the incumbent on the next run, so the gate and the registry cannot drift apart:
the record is written only after registration succeeds.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cloudlayer.factory import get_adapter  # noqa: E402
from scripts.evaluation_gate import CHAMPION_KEY  # noqa: E402
from src import config  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-uri", required=True)
    ap.add_argument("--ref-out", type=Path, required=True)
    args = ap.parse_args()

    cfg = config.load()
    adapter = get_adapter(cfg)
    model_uri = args.model_uri.rstrip("/")

    with tempfile.TemporaryDirectory() as tmp:
        metrics_path = Path(tmp) / "metrics.json"
        adapter.download(f"{model_uri}/metrics.json", str(metrics_path))
        metrics = json.loads(metrics_path.read_text())

        model_ref = adapter.register_model(model_uri, cfg.model_registry_name)
        print(f"registered {model_ref}")

        record = {"model_ref": model_ref, "model_uri": model_uri, **metrics}
        champion = Path(tmp) / "champion.json"
        champion.write_text(json.dumps(record, indent=2))
        uri = adapter.upload(str(champion), CHAMPION_KEY.format(name=cfg.model_registry_name))
        print(f"champion record -> {uri}")

    args.ref_out.parent.mkdir(parents=True, exist_ok=True)
    args.ref_out.write_text(model_ref)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Lab 5 — deploy a registered model version.

    python scripts/deploy.py --target staging --model-ref <ref from register.py>

Uses your Lab 3 adapter.deploy(). The endpoint name carries the target so staging and
production never share an endpoint. A staging endpoint bills while it exists: undeploy
it after you have your evidence, and `make teardown` must find it by label.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cloudlayer.factory import get_adapter  # noqa: E402
from src import config  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", choices=["staging", "production"], required=True)
    ap.add_argument("--model-ref", required=True)
    ap.add_argument("--instance", default=os.environ.get("SERVE_INSTANCE", "n1-standard-2"))
    args = ap.parse_args()

    cfg = config.load()
    endpoint = f"itcs355-{args.target}"
    url = get_adapter(cfg).deploy(args.model_ref, endpoint, args.instance)
    print(f"deployed {args.model_ref} -> {endpoint}: {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

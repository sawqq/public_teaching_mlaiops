"""Lab 5 — Vertex AI Pipelines (KFP v2) build of pipeline/pipeline.yaml.

Layer 3: provider SDKs are allowed here. Deliberately has NO `from __future__ import
annotations`: KFP inspects the component type hints at runtime and cannot resolve them
as strings.
"""
import os
from pathlib import Path
from typing import Any


def compile_and_submit(spec: dict[str, Any], spec_dir: Path):
    import json
    import shlex

    from google_cloud_pipeline_components.v1.custom_job import (
        create_custom_training_job_from_component,
    )
    from kfp import compiler, dsl

    from src.config import CAPABILITY_SLOTS

    steps = {s["name"]: s for s in spec["steps"]}
    labels = {k: str(v).lower() for k, v in spec.get("tags", {}).items()}

    image = steps["train"]["image"]
    if "${" in image:
        raise ValueError(
            f"Unexpanded variable in image {image!r}. Set CONTAINER_REGISTRY in cloud.env "
            "and export IMAGE_TAG (or better, the digest) before compiling."
        )
    train_instance = steps["train"].get("instance", "")
    if not train_instance or "${" in train_instance:
        train_instance = "e2-standard-4"

    # The containers do not have cloud.env, so the capability slots travel as env vars.
    env = {k: os.environ[k] for k in CAPABILITY_SLOTS if os.environ.get(k)}

    def cmd(step: str, **subs: str) -> str:
        """The YAML command for a step, with literal path tokens swapped for placeholders."""
        return " ".join(subs.get(tok, shlex.quote(tok)) for tok in steps[step]["command"])

    # Steps that read the dataset copy it to the path src/config.py expects.
    # One command per line: under `sh -e`, a failure inside an `a && b && c` chain does
    # NOT stop the script, so a failed copy would silently test or train on stale data.
    stage_data = 'mkdir -p data/raw\ncp "$0" data/raw/sensors.csv\ntest -s data/raw/sensors.csv'

    @dsl.container_component
    def ingest(raw_data: dsl.Output[dsl.Dataset]):
        return dsl.ContainerSpec(
            image=image, command=["sh", "-ec"],
            args=[f'mkdir -p "$(dirname "$0")"\n{cmd("ingest")} --out "$0"', raw_data.path],
        )

    @dsl.container_component
    def validate(raw_data: dsl.Input[dsl.Dataset]):
        # `test -s` matters: tests/test_data.py SKIPS when the CSV is missing, and a
        # skipped suite exits 0. Without the guard, "validate" passes on no data at all.
        return dsl.ContainerSpec(
            image=image, command=["sh", "-ec"],
            args=[f'{stage_data}\n{cmd("validate")} -rs', raw_data.path],
        )

    @dsl.container_component
    def train(raw_data: dsl.Input[dsl.Dataset], seed: str,
              metrics: dsl.Output[dsl.Artifact], model: dsl.Output[dsl.Model]):
        train_cmd = cmd("train", **{"/outputs/metrics.json": '"$1"'})
        script = "\n".join([
            stage_data,
            'mkdir -p "$(dirname "$1")" "$2"',
            f'{train_cmd} --seed "$3" --model-out "$2/model.joblib"',
            # Metrics travel with the model, so the registered version carries its evidence.
            'cp "$1" "$2/metrics.json"',
        ])
        return dsl.ContainerSpec(
            image=image, command=["sh", "-ec"],
            args=[script, raw_data.path, metrics.path, model.path, seed],
        )

    @dsl.container_component
    def evaluate(metrics: dsl.Input[dsl.Artifact], incumbent_override: str,
                 gate_decision: dsl.OutputPath(str)):
        gate_cmd = cmd("evaluate", **{"/outputs/metrics.json": '"$0"'})
        script = "\n".join([
            'mkdir -p "$(dirname "$1")"',
            # Exit code -> parameter. A crash also lands in "fail": the gate fails closed.
            f'if {gate_cmd} ${{2:+--incumbent "$2"}}; then printf pass > "$1"; '
            'else printf fail > "$1"; fi',
            'echo "gate_decision=$(cat "$1")"',
        ])
        return dsl.ContainerSpec(
            image=image, command=["sh", "-ec"],
            args=[script, metrics.path, gate_decision, incumbent_override],
        )

    @dsl.container_component
    def register(model: dsl.Input[dsl.Model], model_ref: dsl.OutputPath(str)):
        return dsl.ContainerSpec(
            image=image, command=["sh", "-ec"],
            args=[f'mkdir -p "$(dirname "$1")"\n{cmd("register")} --model-uri "$0" --ref-out "$1"',
                  model.uri, model_ref],
        )

    @dsl.container_component
    def deploy_staging(model_ref: str):
        return dsl.ContainerSpec(
            image=image, command=["sh", "-ec"],
            args=[f'{cmd("deploy_staging")} --model-ref "$0"', model_ref],
        )

    # Train runs as a Vertex custom job so it can use spot capacity. Preemption is
    # handled by retrying the step: a RandomForest on this data trains in seconds, so
    # restarting from scratch is cheaper than checkpointing it.
    train_spot = create_custom_training_job_from_component(
        train,
        display_name="train",
        machine_type=train_instance,
        strategy="SPOT",
        service_account=os.environ.get("TRAIN_SERVICE_ACCOUNT", ""),
        labels=labels,
        env=[{"name": k, "value": v} for k, v in env.items()],
    )

    def with_env(task):
        for k, v in env.items():
            task.set_env_variable(k, v)
        return task

    @dsl.pipeline(name=spec["name"])
    def training_pipeline(seed: str = "20260101", incumbent_override: str = ""):
        i = with_env(ingest()).set_display_name("ingest")
        v = with_env(validate(raw_data=i.outputs["raw_data"])).set_display_name("validate")
        t = train_spot(raw_data=i.outputs["raw_data"], seed=seed).after(v).set_retry(num_retries=2)
        e = with_env(evaluate(metrics=t.outputs["metrics"],
                              incumbent_override=incumbent_override)).set_display_name("evaluate")
        with dsl.If(e.outputs["gate_decision"] == "pass", name="gate-passed"):
            r = with_env(register(model=t.outputs["model"])).set_display_name("register")
            with_env(deploy_staging(model_ref=r.outputs["model_ref"])).set_display_name("deploy_staging")

    out = spec_dir / "compiled" / f"{spec['name']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    compiler.Compiler().compile(training_pipeline, package_path=str(out))
    print(f"compiled {out}")

    submit = os.environ.get("PIPELINE_SUBMIT") == "1"
    schedule = os.environ.get("PIPELINE_SCHEDULE") == "1"
    if not (submit or schedule):
        return str(out)

    from google.cloud import aiplatform

    aiplatform.init(project=os.environ["PROJECT_ID"], location=os.environ["REGION"])
    job = aiplatform.PipelineJob(
        display_name=spec["name"],
        template_path=str(out),
        pipeline_root=f"{os.environ['BLOB_URI'].rstrip('/')}/pipeline-root",
        parameter_values=json.loads(os.environ.get("PIPELINE_PARAMS", "{}")),
        labels=labels,
        enable_caching=False,
    )
    # The identity the pipeline itself runs as (Task 2). Empty = Compute Engine default
    # service account, which is exactly the broad identity Task 2 asks you to replace.
    pipeline_sa = os.environ.get("PIPELINE_SERVICE_ACCOUNT") or None
    if schedule:
        sched = job.create_schedule(
            cron=f"TZ=Asia/Bangkok {spec['schedule']}",
            display_name=f"{spec['name']}-schedule",
            service_account=pipeline_sa,
        )
        print(f"schedule created: {sched.resource_name}")
        return sched.resource_name
    job.submit(service_account=pipeline_sa)
    print(f"submitted: {job._dashboard_uri()}")
    return job.resource_name

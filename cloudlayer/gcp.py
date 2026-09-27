"""GCP adapter. Implement upload/download/push_image for Lab 1.

SDK:  pip install google-cloud-storage google-cloud-aiplatform
Docs: storage.Client for GCS; Artifact Registry push goes through `docker push` after
      `gcloud auth configure-docker <region>-docker.pkg.dev`.

Hints for Lab 1:
  * BLOB_URI looks like gs://bucket/prefix — parse it here, never in src/.
  * Artifact Registry paths are region-scoped:
        <region>-docker.pkg.dev/<project>/<repo>/<image>
    A common first failure is pushing to gcr.io out of habit; it is a different service.
  * push_image must return the digest reference, not the tag.
  * GCP calls them labels, not tags, and they must be lowercase with no spaces.
    cfg.tags(1) already satisfies that constraint — do not "improve" the values.
"""
from __future__ import annotations

from typing import Any

from cffi import model
from google.cloud import aiplatform, storage
import subprocess
from urllib.parse import urlparse

from pydantic import json

from cloudlayer.base import CloudAdapter


class GcpAdapter(CloudAdapter):
    
    def __init__(self, cfg):
        super().__init__(cfg)
        self.storage_client = storage.Client(project=self.cfg.project_id)

    def upload(self, local_path: str, key: str) -> str:
        parsed = urlparse(self.cfg.blob_uri)          # e.g. gs://bucket/prefix
        bucket = self.storage_client.bucket(parsed.netloc)
        full_key = f"{parsed.path.lstrip('/')}/{key}" if parsed.path.strip("/") else key
        blob = bucket.blob(full_key)
        blob.upload_from_filename(local_path)
        return f"gs://{parsed.netloc}/{full_key}"

    def download(self, uri: str, local_path: str) -> None:
        from pathlib import Path
        parsed = urlparse(uri)
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        bucket = self.storage_client.bucket(parsed.netloc)
        blob = bucket.blob(parsed.path.lstrip("/"))
        blob.download_to_filename(local_path)

    def push_image(self, local_tag: str) -> str:
        import re
        remote_uri = f"{self.cfg.container_registry}/{local_tag}"
        subprocess.run(["docker", "tag", local_tag, remote_uri], check=True)
        result = subprocess.run(
            ["docker", "push", remote_uri],
            check=True, capture_output=True, text=True,
        )
        match = re.search(r"digest:\s*(sha256:[0-9a-f]{64})", result.stdout)
        digest = match.group(1)
        repo = remote_uri.rsplit(":", 1)[0]
        return f"{repo}@{digest}"
    
    # submit_training / register_model  -> Lab 2 (Vertex custom training + Model Registry)
    def submit_training(self, image_uri: str, args: dict[str, Any], labels: dict[str, str]) -> str:
        aiplatform.init(
            project=self.cfg["project_id"],
            location=self.cfg.get("region", "asia-southeast1"),
            staging_bucket=self.cfg.get("staging_bucket"),
        )
        
        job = aiplatform.CustomContainerTrainingJob(
            display_name=self.cfg["job_name"],
            container_image_uri=image_uri,
        )
        
        cmd_args = [f"--{k}={v}" for k, v in args.items()]
        
        custom_job = job.run(
            args=cmd_args,
            replica_count=1,
            machine_type=self.cfg.get("machine_type", "n1-standard-4"),
            labels=labels,
            sync=False,
        )
        return custom_job.resource_name  # e.g. projects/123/locations/asia-southeast1/customJobs/456
    
    def wait_training(self, job_id: str) -> dict[str, Any]:
        """Block until the Vertex AI job completes and return its status."""
        aiplatform.init(
            project=self.cfg["project_id"],
            location=self.cfg.get("region", "asia-southeast1")
        )
        job = aiplatform.CustomJob.get(resource_name=job_id)
        job.wait()
        return {
            "job_id": job.resource_name,
            "state": job.state.name,
            "error": job.error.message if job.error else None,
        }
    # deploy / invoke                   -> Lab 3 (Vertex Endpoint)
    def deploy(self, model_ref: str, endpoint: str, instance: str) -> str:
        aiplatform.init(project=self.cfg.project_id, location=self.cfg.region)

        model = aiplatform.Model.upload(
            display_name=endpoint,
            serving_container_image_uri=model_ref,
            serving_container_predict_route="/predict",
            serving_container_health_route="/ready",
            serving_container_ports=[8080],
            serving_container_environment_variables={
                "MODEL_PATH": "/app/model.joblib",
                "MODEL_VERSION": "v1-dev",
            },
            labels=self.cfg.tags(3),
        )

        existing = aiplatform.Endpoint.list(filter=f'display_name="{endpoint}"')
        ep = existing[0] if existing else aiplatform.Endpoint.create(
            display_name=endpoint, labels=self.cfg.tags(3)
        )

        model.deploy(
            endpoint=ep,
            deployed_model_display_name=f"{endpoint}-v1",
            machine_type=instance,
            min_replica_count=1,
            max_replica_count=1,
            traffic_percentage=100,
        )
        return ep.resource_name


    def invoke(self, endpoint: str, payload: dict) -> dict:
        import json as _json
        aiplatform.init(project=self.cfg.project_id, location=self.cfg.region)
        ep = aiplatform.Endpoint(endpoint)
        response = ep.raw_predict(
            body=_json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        return _json.loads(response.content)
    # emit_metric                       -> Lab 4 (Cloud Monitoring time series)
    # generate                          -> Lab 5 (managed LLM endpoint; read usageMetadata for tokens)
    # teardown                          -> Lab 5 (filter resources by label)

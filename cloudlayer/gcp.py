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

from google.cloud import aiplatform, storage
import subprocess
from urllib.parse import urlparse

from cloudlayer.base import CloudAdapter


class GcpAdapter(CloudAdapter):
    
    def __init__(self, cfg):
        super().__init__(cfg)
        self.storage_client = storage.Client(project=self.cfg["project_id"])

    def upload(self, local_path: str, key: str) -> str:
        """Upload a local file to GCS bucket under key."""
        bucket_name = self.cfg["blob_bucket"].replace("gs://", "").strip("/")
        bucket = self.storage_client.bucket(bucket_name)
        blob = bucket.blob(key)
        blob.upload_from_filename(local_path)
        return f"gs://{bucket_name}/{key}"

    def download(self, uri: str, local_path: str) -> None:
        """Download a file from GCS uri to local_path."""
        parsed = urlparse(uri)
        bucket = self.storage_client.bucket(parsed.netloc)
        blob = bucket.blob(parsed.path.lstrip("/"))
        blob.download_to_filename(local_path)

    def push_image(self, local_tag: str) -> str:
        """Tag and push the local docker image to Artifact Registry."""
        remote_uri = (
            f"{self.cfg['region']}-docker.pkg.dev/"
            f"{self.cfg['project_id']}/"
            f"{self.cfg['artifact_repo']}/"
            f"{local_tag}"
        )
        subprocess.run(["docker", "tag", local_tag, remote_uri], check=True)
        subprocess.run(["docker", "push", remote_uri], check=True)
        return remote_uri
    
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
    # emit_metric                       -> Lab 4 (Cloud Monitoring time series)
    # generate                          -> Lab 5 (managed LLM endpoint; read usageMetadata for tokens)
    # teardown                          -> Lab 5 (filter resources by label)

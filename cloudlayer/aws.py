"""AWS adapter. Implement upload/download/push_image for Lab 1.

SDK:  pip install boto3
Docs: S3 -> boto3 client("s3"); ECR -> boto3 client("ecr") for the auth token,
      then `docker push` through subprocess.

Hints for Lab 1:
  * BLOB_URI looks like s3://bucket/prefix — parse it here, never in src/.
  * ECR login expires. If a push that worked yesterday fails today, re-authenticate:
        aws ecr get-login-password --region $REGION | docker login --username AWS \
            --password-stdin <account>.dkr.ecr.<region>.amazonaws.com
  * Return the DIGEST reference from push_image, not the tag. `docker inspect` or the
    push output gives you the sha256.
  * Tag the bucket objects and the ECR repository with cfg.tags(1).
"""
from __future__ import annotations

from typing import Any

from cloudlayer.base import CloudAdapter


class AwsAdapter(CloudAdapter):
    @staticmethod
    def _split_s3(uri: str) -> tuple[str, str]:
        """s3://bucket/some/key -> ("bucket", "some/key"). Provider parsing lives here, never in src/."""
        if not uri.startswith("s3://"):
            raise ValueError(
                f"AwsAdapter needs an s3:// URI, got {uri!r}. BLOB_URI is provider-specific, "
                "so switching provider means switching BLOB_URI too."
            )
        bucket, _, key = uri.removeprefix("s3://").partition("/")
        return bucket, key
 
    def upload(self, local_path: str, key: str) -> str:
        import boto3
 
        bucket, prefix = self._split_s3(self.cfg.blob_uri)
        full_key = f"{prefix.rstrip('/')}/{key}".lstrip("/")
        boto3.client("s3", region_name=self.cfg.region).upload_file(local_path, bucket, full_key)
        return f"s3://{bucket}/{full_key}"
 
    def download(self, uri: str, local_path: str) -> None:
        from pathlib import Path
 
        import boto3
 
        bucket, key = self._split_s3(uri)
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        boto3.client("s3", region_name=self.cfg.region).download_file(bucket, key, local_path)
    
    def invoke(self, endpoint: str, payload: dict) -> dict:
        """Call the model service running on AWS (App Runner) and return its JSON body.
 
        `endpoint` may be a full URL, or any other name, in which case the URL is read from
        the AWS_INVOKE_URL environment variable. That indirection is itself a leak: the
        other providers resolve an endpoint NAME to an address for you.
 
        The body is returned as the service sent it. This service answers
        {"probabilities": [...], "model_version": "..."}; a managed Vertex endpoint wraps
        results as {"predictions": [...]}. The caller's parsing differs, and it is not
        hidden here on purpose.
        """
        import json
        import os
        import urllib.request
 
        base = endpoint if endpoint.startswith(("http://", "https://")) else os.environ.get("AWS_INVOKE_URL", "")
        if not base:
            raise RuntimeError("Set AWS_INVOKE_URL to the App Runner service URL, or pass the URL as `endpoint`.")
        if not base.startswith(("http://", "https://")):
            base = "https://" + base
        req = urllib.request.Request(
            f"{base.rstrip('/')}/predict/batch",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
 
    
    def push_image(self, local_tag: str) -> str:
        raise NotImplementedError("Task 4 ports only upload, download and invoke")
    # submit_training / register_model  -> Lab 2 (SageMaker training job + model package group)
    # deploy / invoke                   -> Lab 3 (SageMaker real-time endpoint)
    # emit_metric                       -> Lab 4 (CloudWatch put_metric_data)
    # generate                          -> Lab 5 (managed LLM endpoint; read the usage block for tokens)
    # teardown                          -> Lab 5 (resourcegroupstaggingapi to find by tag)

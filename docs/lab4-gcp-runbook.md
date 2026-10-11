# Lab 4 on GCP — runbook

Everything here is run by you, in order. Steps 1 to 5 need your GCP project; the repo-side
changes (tests, SLO, drift threshold, CD workflow, scripts) are already verified locally.
Nothing in steps 1 to 5 could be run against real GCP while writing this, so expect to fix a
typo or a missing permission; the error message will name the field or the role.

Set these once in your shell (WSL2):

```bash
set -a; source cloud.env; set +a            # PROJECT_ID, REGION, BLOB_URI, CONTAINER_REGISTRY, MODEL_REGISTRY_NAME
export GH_REPO=<github-user>/<repo>
export PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')
gcloud services enable run.googleapis.com cloudscheduler.googleapis.com monitoring.googleapis.com \
  logging.googleapis.com artifactregistry.googleapis.com aiplatform.googleapis.com iamcredentials.googleapis.com \
  --project $PROJECT_ID
```

## 1. Keyless CI identity (workload identity federation)

```bash
gcloud iam service-accounts create itcs355-cd --project $PROJECT_ID
SA=itcs355-cd@$PROJECT_ID.iam.gserviceaccount.com

gcloud iam workload-identity-pools create github --project $PROJECT_ID --location=global
gcloud iam workload-identity-pools providers create-oidc github-actions \
  --project $PROJECT_ID --location=global --workload-identity-pool=github \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository=='$GH_REPO'"

gcloud iam service-accounts add-iam-policy-binding $SA --project $PROJECT_ID \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github/attribute.repository/$GH_REPO"

for ROLE in roles/artifactregistry.writer roles/aiplatform.user roles/monitoring.metricWriter; do
  gcloud projects add-iam-policy-binding $PROJECT_ID --member="serviceAccount:$SA" --role=$ROLE
done
```

If the CD deploy step later says permission denied, that is the "CI can build but not deploy"
failure from the lab handout: grant the role the error names to `$SA`, and write down what broke.

GitHub repository **Secrets** (Settings, Secrets and variables, Actions):

| Secret | Value |
|---|---|
| `GCP_WIF_PROVIDER` | `projects/<PROJECT_NUMBER>/locations/global/workloadIdentityPools/github/providers/github-actions` |
| `GCP_DEPLOY_SA` | `itcs355-cd@<PROJECT_ID>.iam.gserviceaccount.com` |

**Variables** (same page): `PROJECT_ID`, `REGION`, `BLOB_URI`, `CONTAINER_REGISTRY`,
`MODEL_REGISTRY_NAME` (same values as your `cloud.env`), `ENDPOINT_NAME` (e.g. `itcs355-staging`)
and `INSTANCE_TYPE` (e.g. `n1-standard-2`). Create an environment called `staging`
(Settings, Environments).

## 2. First deploy

Merge to `main`. CI runs; when it is green, CD builds the serving image for that exact commit,
pushes it, deploys it and smoke-tests it. The smoke test fails the run unless all three
payloads come back from the commit SHA that was pushed.

## 3. Monitoring: metrics, alert, dashboard

First make sure the service's JSON log lines reach Cloud Logging as `jsonPayload.msg.*` (Logs
Explorer, send one request to the endpoint, open the entry). Then:

```bash
ALERT_EMAIL=<an inbox you read> bash monitoring/gcp/setup.sh
```

This creates four log-based metrics (requests by model version, 4xx, 5xx, latency), an email
channel, the drift alert policy (PSI above 0.15) and the dashboard. Send some traffic (the Lab
3 k6 run) and the panels fill in after a few minutes. Log-based metrics only count requests
made after they exist.

## 4. The scheduled drift run

Add one line to your root `Dockerfile` so the training image can run the detector, then rebuild
and push it (`make image-push`):

```dockerfile
COPY --chown=runner:runner monitoring/ ./monitoring/
```

Upload the reference window and a clean current window (600 rows from a fresh draw):

```bash
python -c "from scripts.make_dataset import build; build(4242).sample(n=600, random_state=1).to_csv('data/current_clean.csv', index=False)"
python -c "from src import config; from cloudlayer.factory import get_adapter; a=get_adapter(config.load()); print(a.upload('data/raw/sensors.csv','drift/reference.csv')); print(a.upload('data/current_clean.csv','drift/current.csv'))"
```

Create the job and the schedule (every 10 minutes while you do the exercise; pause it after):

```bash
IMAGE=<digest reference of the training image you pushed>
DRIFT_SA=itcs355-drift@$PROJECT_ID.iam.gserviceaccount.com
gcloud iam service-accounts create itcs355-drift --project $PROJECT_ID
gcloud projects add-iam-policy-binding $PROJECT_ID --member="serviceAccount:$DRIFT_SA" --role=roles/monitoring.metricWriter
gcloud projects add-iam-policy-binding $PROJECT_ID --member="serviceAccount:$DRIFT_SA" --role=roles/storage.objectViewer

gcloud run jobs create itcs355-drift --project $PROJECT_ID --region $REGION --image "$IMAGE" \
  --service-account $DRIFT_SA --command python \
  --args "scripts/drift_job.py,--reference-uri,$BLOB_URI/drift/reference.csv,--current-uri,$BLOB_URI/drift/current.csv" \
  --set-env-vars "CLOUD_PROVIDER=gcp,PROJECT_ID=$PROJECT_ID,REGION=$REGION,BLOB_URI=$BLOB_URI,CONTAINER_REGISTRY=$CONTAINER_REGISTRY,MLFLOW_TRACKING_URI=sqlite:///mlflow.db,MODEL_REGISTRY_NAME=$MODEL_REGISTRY_NAME,IDENTITY_REF=$DRIFT_SA" \
  --labels course=itcs355,lab=4

gcloud run jobs add-iam-policy-binding itcs355-drift --project $PROJECT_ID --region $REGION \
  --member="serviceAccount:$DRIFT_SA" --role=roles/run.invoker

gcloud scheduler jobs create http itcs355-drift --project $PROJECT_ID --location $REGION \
  --schedule="*/10 * * * *" --http-method=POST \
  --uri="https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT_ID/jobs/itcs355-drift:run" \
  --oauth-service-account-email=$DRIFT_SA
```

Run it once by hand (`gcloud run jobs execute itcs355-drift --region $REGION --wait`), check the
log shows six `psi=` lines, and check `drift.psi.temp_c` appears in Metrics Explorer.

## 5. The injected-drift evidence

```bash
python scripts/inject_drift.py --source data/current_clean.csv --out data/current.csv \
  --feature temp_c --mode shift --magnitude 6
date -u                                    # T0: write this down
python -c "from src import config; from cloudlayer.factory import get_adapter; print(get_adapter(config.load()).upload('data/current.csv','drift/current.csv'))"
```

Wait for the email (T1). Detection time = T1 minus T0; it is bounded by the 10-minute schedule
plus the alert evaluation delay, and you should say so. Capture the email with its timestamp,
the dashboard with the drift panel crossing the red line, and fill the `<FILL>` fields in the
README section. Then restore the clean window and pause the schedule:

```bash
python -c "from src import config; from cloudlayer.factory import get_adapter; get_adapter(config.load()).upload('data/current_clean.csv','drift/current.csv')"
gcloud scheduler jobs pause itcs355-drift --project $PROJECT_ID --location $REGION
```

## 6. The blocked bad commit

```bash
git switch -c bad/fahrenheit
sed -i 's|"temp_c": round(float(temp), 3),|"temp_c": round(float(temp) * 9 / 5 + 32, 3),|' scripts/make_dataset.py
git commit -am "WIP: write temp_c in Fahrenheit (intentionally bad, Lab 4 evidence)"
git push -u origin bad/fahrenheit
```

Open a pull request. CI fails at **Data contract tests** on
`test_features_within_plausible_ranges` (`temp_c above plausible ceiling: 240.215`). Screenshot
the red run and the error, then close the PR without merging and delete the branch.

## 7. Teardown (scheduled jobs are the ones people forget)

```bash
gcloud scheduler jobs delete itcs355-drift --project $PROJECT_ID --location $REGION --quiet
gcloud run jobs delete itcs355-drift --project $PROJECT_ID --region $REGION --quiet
gcloud alpha monitoring policies list --project $PROJECT_ID --format='value(name)'      # delete each itcs355 one
gcloud monitoring dashboards list --project $PROJECT_ID --format='value(name)'          # delete the itcs355 one
for m in requests 4xx 5xx latency_ms; do gcloud logging metrics delete itcs355_predict_$m --project $PROJECT_ID --quiet; done
```

The Vertex endpoint and its deployed models are billed per replica-hour, so they matter most:
undeploy every model from the endpoint, delete the endpoint, then delete the uploaded models and
the images in Artifact Registry. `make teardown` is not implemented in the GCP adapter yet (it
is a Lab 5 method), so do this by hand and verify in the console. Recheck billing after about 24
hours.

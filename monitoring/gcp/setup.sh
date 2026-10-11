#!/usr/bin/env bash
# Lab 4 — create the monitoring pieces for the prediction service on GCP.
#
#   PROJECT_ID=itcs355-<id> ALERT_EMAIL=you@example.com bash monitoring/gcp/setup.sh
#
# Creates, idempotently:
#   1. four log-based metrics read from the service's JSON access log
#      (requests by model version, 4xx, 5xx, latency distribution)
#   2. an email notification channel
#   3. an alert policy: any drift.psi.<feature> metric above 0.15 sends the email
#   4. the dashboard (monitoring/gcp/dashboard.json)
#
# The service already logs one JSON line per request (service/app.py):
#   {"ts": ..., "level": "INFO", "msg": {"request_id": ..., "path": "/predict",
#    "status": 200, "latency_ms": 3.2, "model_version": "<sha>"}}
# Cloud Logging parses that into jsonPayload.msg.*, which is what the filters below read.
# Before running this, confirm those fields exist: Logs Explorer, send one request, open the
# entry. If the Vertex endpoint shows no container logs, enable container logging on deploy.

set -euo pipefail

: "${PROJECT_ID:?set PROJECT_ID}"
: "${ALERT_EMAIL:?set ALERT_EMAIL (where the drift alert should be sent)}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

BASE_FILTER='resource.type="aiplatform.googleapis.com/Endpoint" AND jsonPayload.msg.path="/predict"'

upsert_metric() {   # name, config file
  if gcloud logging metrics describe "$1" --project "$PROJECT_ID" >/dev/null 2>&1; then
    gcloud logging metrics update "$1" --project "$PROJECT_ID" --config-from-file="$2"
  else
    gcloud logging metrics create "$1" --project "$PROJECT_ID" --config-from-file="$2"
  fi
}

cat > "$TMP/requests.yaml" <<EOF
description: "ITCS355 /predict requests, by model version"
filter: '${BASE_FILTER}'
metricDescriptor:
  metricKind: DELTA
  valueType: INT64
  unit: "1"
  labels:
  - key: model_version
    valueType: STRING
labelExtractors:
  model_version: EXTRACT(jsonPayload.msg.model_version)
EOF

cat > "$TMP/4xx.yaml" <<EOF
description: "ITCS355 /predict responses with a 4xx status (caller problems)"
filter: '${BASE_FILTER} AND jsonPayload.msg.status>=400 AND jsonPayload.msg.status<500'
metricDescriptor:
  metricKind: DELTA
  valueType: INT64
  unit: "1"
EOF

cat > "$TMP/5xx.yaml" <<EOF
description: "ITCS355 /predict responses with a 5xx status (our problems)"
filter: '${BASE_FILTER} AND jsonPayload.msg.status>=500'
metricDescriptor:
  metricKind: DELTA
  valueType: INT64
  unit: "1"
EOF

cat > "$TMP/latency.yaml" <<EOF
description: "ITCS355 /predict latency in ms, measured inside the service"
filter: '${BASE_FILTER}'
valueExtractor: EXTRACT(jsonPayload.msg.latency_ms)
metricDescriptor:
  metricKind: DELTA
  valueType: DISTRIBUTION
  unit: ms
bucketOptions:
  exponentialBuckets:
    numFiniteBuckets: 48
    growthFactor: 1.3
    scale: 1
EOF

upsert_metric itcs355_predict_requests "$TMP/requests.yaml"
upsert_metric itcs355_predict_4xx "$TMP/4xx.yaml"
upsert_metric itcs355_predict_5xx "$TMP/5xx.yaml"
upsert_metric itcs355_predict_latency_ms "$TMP/latency.yaml"

# --- the channel the drift alert reaches: a real inbox -------------------------------------
CHANNEL="$(gcloud beta monitoring channels list --project "$PROJECT_ID" \
  --filter="displayName='itcs355 drift email'" --format='value(name)' | head -n1)"
if [ -z "$CHANNEL" ]; then
  CHANNEL="$(gcloud beta monitoring channels create --project "$PROJECT_ID" \
    --display-name='itcs355 drift email' --type=email \
    --channel-labels="email_address=${ALERT_EMAIL}" --format='value(name)')"
fi
echo "notification channel: $CHANNEL"

# --- alert policy: PSI above the threshold justified in README / monitoring/drift.py -------
cat > "$TMP/policy.json" <<'EOF'
{
  "displayName": "itcs355 drift: PSI above 0.15",
  "combiner": "OR",
  "conditions": [
    {
      "displayName": "any drift.psi.<feature> >= 0.15",
      "conditionThreshold": {
        "filter": "metric.type=starts_with(\"custom.googleapis.com/itcs355/drift.psi.\") AND resource.type=\"global\"",
        "comparison": "COMPARISON_GT",
        "thresholdValue": 0.15,
        "duration": "0s",
        "aggregations": [
          {"alignmentPeriod": "300s", "perSeriesAligner": "ALIGN_MAX"}
        ],
        "evaluationMissingData": "EVALUATION_MISSING_DATA_INACTIVE"
      }
    }
  ],
  "alertStrategy": {"autoClose": "1800s"},
  "documentation": {
    "content": "A feature's PSI against the training reference crossed 0.15. Before retraining, check whether the schema or null rate changed (broken upstream: do NOT retrain) and see docs/postmortem-template.md.",
    "mimeType": "text/markdown"
  }
}
EOF
EXISTING="$(gcloud alpha monitoring policies list --project "$PROJECT_ID" \
  --filter="displayName='itcs355 drift: PSI above 0.15'" --format='value(name)' | head -n1)"
if [ -n "$EXISTING" ]; then
  gcloud alpha monitoring policies delete "$EXISTING" --project "$PROJECT_ID" --quiet
fi
gcloud alpha monitoring policies create --project "$PROJECT_ID" \
  --policy-from-file="$TMP/policy.json" --notification-channels="$CHANNEL"

# --- dashboard ---------------------------------------------------------------------------
OLD="$(gcloud monitoring dashboards list --project "$PROJECT_ID" \
  --filter="displayName='ITCS355 - Prediction service'" --format='value(name)' | head -n1)"
if [ -n "$OLD" ]; then
  gcloud monitoring dashboards delete "$OLD" --project "$PROJECT_ID" --quiet
fi
gcloud monitoring dashboards create --project "$PROJECT_ID" --config-from-file="$HERE/dashboard.json"

echo "done. Log-based metrics take a few minutes to start collecting; they only count requests made AFTER they exist."

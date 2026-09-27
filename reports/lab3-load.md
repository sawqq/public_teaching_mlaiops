# Lab 3 — Load Test Results

## Stated target
p95 < 300ms @ concurrency 10 (set before measuring, in loadtest/k6.js)

## Results

| Concurrency | Throughput (req/s) | p50 (ms) | p95 (ms) | p99 (ms) | Error rate |
|-------------|--------------------|----------|----------|----------|------------|
| 1           |    6.315568/s      |-157.06ms-|-239.38ms-| 281.45ms |     0      |
| 10          |    14.528601/s     | 425.6ms  |   1.53s  |   6.51s  |     0       |
| 50          |      13.968284/s   |  3.49s   |   5.67s  |   5.96s  |     0       |

## Breaking point
_The p95 target (<400ms) is met only at VUS=1 (239.38ms). At VUS=10, p95 jumps to
1.53s — already ~4x over target — and throughput only rises modestly (6.3 → 14.5
req/s). At VUS=50, throughput actually plateaus/slightly drops (14.5 → 14.0 req/s)
while p50/p95/p99 all get worse (3.49s / 5.67s / 5.96s), showing the endpoint is
fully saturated: extra concurrent requests just queue rather than get served faster.

The breaking point is therefore between VUS=1 and VUS=10 — the service can sustain
roughly single-digit concurrency before p95 latency blows past target. Error rate
stayed 0% at all levels, so the service degrades gracefully (queues and eventually
serves every request) rather than failing outright, but SLA-wise it is effectively
broken well before VUS=10._

## Observations

_The endpoint was deployed with `min_replica_count=1, max_replica_count=1` (no
autoscaling), so all concurrent requests are served by a single container/replica.
This is the most likely root cause of the saturation — latency scales roughly
linearly with concurrency while throughput stays flat, which is the signature of a
single-worker queue rather than a resource (CPU/memory) ceiling. Enabling
autoscaling (raising `max_replica_count`) would be the direct fix if higher
concurrency needed to be supported._

## Batch vs. singles
100 individual `/predict` calls: **7601.64ms** total (~76ms/request).
One `/predict/batch` call with 100 rows: **2249.04ms** total (~22.5ms/row).
Batching is **~3.4x faster** overall. The difference is almost entirely fixed
per-request overhead (HTTP connection setup, FastAPI routing/validation, JSON
parse) paid once per call — with 100 individual calls that overhead is paid 100
times, while batching pays it once and amortizes it across all 100 rows.

## Payload size
| Rows (n) | Total (ms) | Per-row (ms) |
|----------|-----------|--------------|
| 1        | 87.95     | 87.95        |
| 10       | 75.65     | 7.56         |
| 50       | 82.69     | 1.65         |
| 100      | 75.53     | 0.76         |

Total latency stays roughly flat (~76-88ms) regardless of row count, while
per-row cost keeps dropping as n grows — meaning fixed per-request overhead
(not serialization or model compute) dominates at every tested size. Serialization
never becomes the bottleneck in this range; it would take a much larger batch
(likely thousands of rows) before JSON encode/decode cost grows large enough to
show up against that near-constant ~80ms floor.

## Instance size step-up
_latency change + cost change from n1-standard-2 → next size_

## Task 4 — Canary Deploy and Rollback

1. Deployed a deliberately degraded model (`canary-v1-bad`, DummyClassifier
   always predicting probability=1.0) as a 10% traffic canary alongside the
   existing production model on endpoint `3337530162718703616`, at ~21:09 UTC
   (04:09 local).
2. Probed the live endpoint blind with 100 requests (04:18 local) without
   knowledge of which model served each one; aggregate output distribution
   showed 10/100 responses at exactly probability=1.0 (vs. healthy baseline
   ~0.0099), pulling the average from ~0.01 to 0.109 — a clear bimodal
   anomaly matching the 10% canary split.
3. Detection method: statistical anomaly in prediction output distribution
   (fixed outlier value at 10x-100x the expected magnitude), not manual
   inspection of per-request routing — consistent with a blind
   production-monitoring signal (e.g. an output-drift alert).
4. Rolled back at 21:21 UTC (04:21 local) via
   `gcloud ai endpoints undeploy-model --deployed-model-id=891846866637946880
   --traffic-split=3116413976326438912=100`, removing the canary and
   restoring 100% traffic to the known-good model.
5. Verified rollback: `endpoints describe` confirms only the good deployed
   model remains with 100% traffic split; 10/10 post-rollback probe requests
   returned the healthy baseline probability (0.00985...) with zero anomalies.


## Task 5 — Cost per 1,000 Predictions

**Rate:** n1-standard-2 online prediction, asia-southeast1 = $0.1095/hour
(https://cloud.google.com/vertex-ai/pricing)

**Utilization assumption:** the endpoint runs 24/7 (min_replica_count=1, no
scale-to-zero) and serves a modest, realistic student/testing load of ~500
predictions/day.

- Cost per hour: $0.1095
- Cost per day: $0.1095 × 24 = $2.628
- Cost per 1,000 predictions: ($2.628 / 500) × 1000 = **$5.26**

For comparison, if the same endpoint were driven at its sustained Task 3
VUS=1 throughput (~5.99 req/s ≈ 21,564 predictions/hour) instead of sitting
mostly idle, cost per 1,000 predictions drops to ($0.1095 / 21,564) × 1000
≈ **$0.005** — over 1000x cheaper per prediction.

## Batch vs. warm endpoint
Because Vertex bills for reserved instance-time, not per-prediction, cost
per prediction is dominated entirely by utilization, not compute. For
bursty or low-volume workloads (like this lab), a warm always-on endpoint
wastes most of its cost sitting idle — deploying only to run a batch job
and then tearing the endpoint down (`make teardown`) is far cheaper than
keeping it continuously deployed for sporadic single-prediction traffic.
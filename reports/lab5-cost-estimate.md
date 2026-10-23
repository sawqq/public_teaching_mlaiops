# Lab 5 — Cost estimate (made BEFORE running anything)

Provider: GCP (Vertex AI) · Region: <your REGION from cloud.env> · Currency: THB · FX used: 1 USD = 33.75 THB
Written: 2026-10-23 <HH:MM> · Committed before any Lab 5 resource was created: yes

## 1. What I plan to run

| Item | Plan | Source of price |
|---|---|---|
| Pipeline runs | 4 runs: first full run, forced-fail run (`incumbent_override=0.99`), one scheduled-run check, one spare for a fix | Vertex Pipelines per-run fee ≈ $0.03 (from memory, to verify) |
| Training and step compute | e2-standard-4, ~20 min of container time per run (train ~5 min + 5 small steps ~3 min each), billed on-demand even though training uses spot, so this is an upper bound | Vertex pricing page: e2-standard-4 custom training $0.154/h |
| Staging endpoint | n1-standard-2, up ~3 hours total, then undeployed | Vertex pricing page: n1-standard-2 online prediction $0.1095/h |
| Storage | ~1 GB container image in Artifact Registry + <0.1 GB data and artifacts in GCS, ~1 month | Artifact Registry ≈ $0.10/GB-month, GCS Standard ≈ $0.02/GB-month (from memory, to verify) |
| Logging / monitoring | small volume, inside the free monthly logging allotment | Cloud Logging free allotment |
| Scheduler | 1 schedule, deleted at teardown | no separate charge assumed |
| LLM calls (Part B) | recorded fixtures only → 0 THB | `make llm-eval` is offline |

## 2. Estimate by component

| Component | Calculation | THB |
|---|---|---|
| Training and step compute | 4 runs × 20 min = 1.33 h × $0.154 × 33.75 | 6.9 |
| Pipeline | 4 runs × $0.03 × 33.75 | 4.1 |
| Serving (staging endpoint) | 3 h × $0.1095 × 33.75 | 11.1 |
| Storage | ≈ $0.12 × 33.75 | 4.1 |
| Monitoring | inside free allotment | 0.0 |
| **Subtotal (everything works first time)** | | **26.1** |
| Debugging allowance | ×2: first pipeline runs usually fail once or twice, and failed runs still bill | **≈ 52** |

**Committed estimate: 52 THB.**

## 3. Assumptions I am least sure of
- Endpoint hours. 3 hours assumes I undeploy straight after screenshots. A forgotten overnight deployment adds 3.9 THB/h × 12 h ≈ 47 THB on its own.
- Unit prices for the pipeline fee, GCS and Artifact Registry come from memory, not from the pricing page. The compute and endpoint prices come from the Vertex pricing page, but its table does not label which column is my region.
- No egress or retry charges; spot preemption retries (up to 2 per run) would add training time.
- Step compute is priced as e2-standard-4 on-demand for all steps, which overstates training if spot is applied.

## 4. Budget check
Term budget 800 THB. Spent in Labs 1–4: <__> THB. This estimate: 52 THB. Remaining after Lab 5: <__> THB.

## 5. Tags every resource will carry
`course=itcs355`, `student=<PROJECT_ID>`, `lab=5` — applied at creation, not afterwards.

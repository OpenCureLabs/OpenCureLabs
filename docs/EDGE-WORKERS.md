# Low-Power Edge Workers

OpenCure Labs can run a small always-on worker pool using NVIDIA Jetson boards
and Raspberry Pi compute blades. The goal is not to replace RTX/Vast.ai heavy
compute. The goal is to keep the project active 24x7 with low power draw,
claiming modest jobs, running local inference where practical, and escalating
large jobs to bigger GPUs.

Status: this document describes the target deployment pattern and the current
queue-first way to operate it. The repo already supports local worker threads
through `batch_dispatcher --local-workers`; a dedicated network `edge_worker`
daemon with explicit capability matching is a future hardening step.

---

## Recommended Topology

```
Control plane
  Raspberry Pi compute blade, mini PC, or small server
  PostgreSQL, task queue, dashboard, scheduler, logs, health checks

Edge GPU pool
  Jetson Orin Nano / Orin NX / AGX Orin nodes
  One bounded worker per node by default
  Local inference, embeddings, triage, small scientific jobs

Heavy compute fallback
  Local RTX workstation or Vast.ai
  Docking sweeps, large structure prediction, model training, large LLMs
```

The control plane should be boring and durable. The Jetsons should be treated as
replaceable workers that claim one job, execute it, report the result, and then
sleep or claim another job.

---

## Hardware Roles

| Device | Best role | Notes |
|---|---|---|
| Raspberry Pi compute blade | Control plane | Queue, dashboard, database, scheduler, watchdogs. Prefer NVMe boot and active cooling. |
| Jetson Orin Nano 8GB | One light edge worker | Embeddings, small quantized local models, source triage, light CPU/GPU jobs. |
| Jetson Orin NX 16GB | Primary edge worker tier | Better fit for 7B/8B quantized models and local reviewer drafts. |
| AGX Orin 32GB/64GB | Edge inference anchor | Larger quantized models, more durable local review/inference service. |
| RTX workstation / Vast.ai | Heavy scientific compute | Large docking, structure prediction, training, multi-GPU sweeps. |

If choosing between many 8GB devices and fewer 16GB+ devices, prefer the 16GB+
tier for local LLM work. The 8GB boards are useful, but model memory becomes the
main constraint quickly.

---

## Job Placement

Edge workers should only claim jobs that fit their memory, architecture, and
runtime. A practical capability model is:

| Capability | Good candidates | Avoid |
|---|---|---|
| `edge_cpu` | Variant lookups, source registration, report generation, queue maintenance | Long-running model training |
| `edge_gpu_light` | Embeddings, reranking, classifiers, small inference, small QSAR prediction | Large docking sweeps |
| `edge_gpu_llm` | Reviewer draft, coordinator draft, literature triage, summarization | Long-context final scientific review |
| `heavy_gpu` | Structure prediction, docking sweeps, training, large LLM inference | 8GB Jetson nodes |

Current skill metadata already separates GPU-marked and CPU-friendly skills.
Good first tasks for Jetsons are:

- `variant_pathogenicity`
- `register_source`
- `report_generator`
- `sequencing_qc` on small files
- `qsar` prediction or small training jobs
- local embeddings, summaries, and reviewer drafts once those are wired in

Use RTX/Vast.ai for large `molecular_docking`, heavyweight
`structure_prediction`, bulk QSAR training, or anything that needs x86-only
dependencies.

---

## Current Queue-First Operation

The simplest current deployment is a shared PostgreSQL queue on the control
plane, with each Jetson running one local worker against that queue.

On the control plane, generate or receive work:

```bash
source /root/opencurelabs/.venv/bin/activate
python -m agentiq_labclaw.compute.batch_dispatcher \
  --generate-only \
  --count 200 \
  --config config/research_tasks.yaml
```

On each Jetson, point `POSTGRES_URL` at the control-plane database and drain one
job at a time:

```bash
cd /opt/opencurelabs
source .venv/bin/activate

export POSTGRES_URL="postgresql://control-plane:5433/opencurelabs"
export LABCLAW_COMPUTE=local

python -m agentiq_labclaw.compute.batch_dispatcher \
  --drain-queue \
  --local-workers 1
```

This runs skills locally on the Jetson process. In this context, "local" means
local to the Jetson, not local to the control plane.

For long-running operation, wrap the command in `systemd` with restart enabled.
The process exits when the queue is empty; `systemd` can restart it periodically,
or a timer can run it every few minutes.

---

## Example systemd Service

`/etc/systemd/system/opencurelabs-jetson-worker.service`:

```ini
[Unit]
Description=OpenCure Labs Jetson edge worker
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=opencure
WorkingDirectory=/opt/opencurelabs
Environment=POSTGRES_URL=postgresql://control-plane:5433/opencurelabs
Environment=LABCLAW_COMPUTE=local
ExecStart=/opt/opencurelabs/.venv/bin/python -m agentiq_labclaw.compute.batch_dispatcher --drain-queue --local-workers 1
Restart=always
RestartSec=60

[Install]
WantedBy=multi-user.target
```

Enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now opencurelabs-jetson-worker.service
systemctl status opencurelabs-jetson-worker.service
```

For production, prefer a dedicated database user with limited permissions rather
than a broad local development connection string.

---

## Jetson Software Notes

Jetson nodes are ARM64 and use NVIDIA JetPack/L4T. Treat them as a separate
worker image or install profile from x86_64 machines.

Recommended first pass:

- JetPack 6.x where possible
- Python 3.11/3.12 venv if the dependency set supports it
- PyTorch build matched to JetPack
- `llama.cpp` with CUDA/cuBLAS for small local LLM inference
- TensorRT-LLM later, after the basic worker loop is reliable
- NVMe storage, active cooling, and a small UPS for 24x7 operation

Expect ARM-specific dependency work for packages such as RDKit, PyTorch,
MHCflurry, pyensembl, pysam, gnina, and NeMo/AgentIQ. Keep the worker role small
until the image is proven.

---

## LLM Migration Path

The edge pool should support a gradual move from API-first reasoning to local
inference:

1. Keep Gemini/Grok or another strong API model for coordinator and final
   scientific review while the hardware pool stabilizes.
2. Move embeddings, reranking, source triage, and short summaries onto Jetson
   workers first.
3. Add local reviewer drafts from a quantized model on Jetson NX/AGX.
4. Route final critique to the strongest available provider: local model,
   existing API, or a cheaper OpenAI-compatible model API such as GLM if cost
   and quality are acceptable.
5. Replace hard-coded reviewer providers with a generic reviewer provider layer
   before swapping Grok out completely.

For coordinator models, the existing NeMo/AgentIQ YAML already uses an
OpenAI-compatible shape (`base_url`, `model_name`, `api_key`). Any GLM-style API
that exposes compatible chat completions should be evaluated as a drop-in
candidate. The reviewer path may need more code work if it is currently tied to
xAI/Grok-specific behavior.

Local LLM review should be treated as draft or triage until it is benchmarked on
known scientific outputs. High-stakes novelty/safety review should retain an API
or stronger local fallback until the edge model is proven.

---

## Future Edge Worker Contract

A dedicated edge worker daemon should advertise capabilities and heartbeat to
the control plane:

```yaml
worker_name: jetson-nx-01
arch: arm64
memory_gb: 16
accelerator: jetson_orin
capabilities:
  - edge_cpu
  - edge_gpu_light
  - edge_gpu_llm
concurrency: 1
max_job_seconds: 900
```

The scheduler should match jobs to workers using fields like:

```yaml
runtime_class: edge_gpu_light
arch: arm64
max_memory_gb: 6
timeout_seconds: 600
fallback_runtime_class: heavy_gpu
```

If a Jetson misses heartbeats, the control plane should mark its running job
stale and return it to the queue. If a job exceeds memory or runtime limits, it
should be failed with a clear reason and optionally requeued for `heavy_gpu`.

---

## Operating Rules

- Run one worker per Jetson by default; increase only after measuring memory.
- Keep API keys on the control plane when possible; workers should receive only
  the credentials they need.
- Prefer small, idempotent jobs with bounded runtimes.
- Use RTX/Vast.ai for large or urgent scientific compute.
- Monitor node temperature, disk health, queue age, and worker heartbeat.
- Log every worker run to `logs/` or the central dashboard.
- Treat local LLM review as a draft path until benchmarked against API reviewers.

This gives OpenCure Labs a low-power research fabric: Jetsons provide steady
throughput and local inference, while larger GPUs remain available for peak
scientific workloads.
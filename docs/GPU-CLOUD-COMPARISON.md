# GPU Cloud Comparison: Vast.ai vs RunPod

> Decision reference for OpenCure Labs burst compute layer.
> Last updated: 2026-03-22

---

## TL;DR

| | **Vast.ai** (current) | **RunPod** |
|---|---|---|
| **Best for** | Cheapest spot-market GPUs | Reliable on-demand + serverless |
| **Pricing model** | Peer-to-peer marketplace (bid/ask) | Fixed-rate catalog |
| **Spot pricing** | $0.10–0.40/hr (RTX 4090) | $0.20–0.44/hr (RTX 4090) |
| **On-demand** | "Reserved" tier, limited | First-class, always available |
| **API quality** | Functional but quirky | Clean REST + Python SDK |
| **Serverless** | No | Yes (autoscale to zero) |
| **Docker support** | Yes (custom image + onstart) | Yes (custom image + template) |
| **SSH access** | Yes (root) | Yes (root) |
| **Multi-GPU** | Yes (marketplace dependent) | Yes (up to 8× H100) |
| **Reliability** | Variable (peer network) | Higher (own datacenters + vetted partners) |
| **Instance boot** | 2–8 min (image pull varies) | 30s–3 min (cached templates) |
| **Billing** | Per-second | Per-second |
| **Instance TTL / auto-stop** | Manual (we added our own) | Built-in idle timeout |
| **Budget controls** | API balance check only | Spending limits in dashboard |

---

## Pricing Deep Dive

### Vast.ai (What We Pay Now)

Vast.ai is a peer-to-peer GPU marketplace. Pricing fluctuates based on supply/demand.

| GPU | Spot $/hr (typical) | On-Demand $/hr | VRAM |
|-----|---------------------|----------------|------|
| RTX 4090 | $0.15–0.35 | $0.40–0.55 | 24 GB |
| RTX 5070 Ti | $0.12–0.28 | $0.35–0.45 | 16 GB |
| RTX 5080 | $0.18–0.35 | $0.45–0.55 | 16 GB |
| RTX 5090 | $0.30–0.55 | $0.60–0.85 | 32 GB |
| A100 80GB | $0.80–1.50 | $1.50–2.20 | 80 GB |
| H100 | $2.00–3.50 | $3.50–4.50 | 80 GB |

- Prices are per-GPU, per-hour
- Spot instances can be interrupted (provider reclaims machine)
- Our current filter: `max_cost_hr=0.50`, `reliability2>=0.95`
- Typical spend per Genesis run (20 tasks, 10 instances, ~15 min): **$1–3**

### RunPod

Fixed-rate pricing, less variability. Two tiers: Community Cloud (cheaper, shared infra) and Secure Cloud (dedicated, SOC2).

| GPU | Community $/hr | Secure $/hr | VRAM |
|-----|----------------|-------------|------|
| RTX 4090 | $0.44 | $0.69 | 24 GB |
| RTX A5000 | $0.36 | $0.44 | 24 GB |
| A100 80GB | $1.64 | $2.04 | 80 GB |
| H100 SXM | $3.99 | $4.69 | 80 GB |
| L40S | $0.74 | $0.84 | 48 GB |

- On-demand: always available, no interruption
- Spot: 20–60% cheaper but can be interrupted
- Serverless: pay-per-second only while executing (auto-scales to zero)

### Cost Comparison for Our Workloads

**Scenario: 20-task Genesis run, 10 GPUs, ~15 min wall-clock**

| Provider | GPU | Rate | Cost |
|----------|-----|------|------|
| Vast.ai spot | RTX 4090 | ~$0.25/hr × 10 × 0.25hr | **~$0.63** |
| RunPod community | RTX 4090 | $0.44/hr × 10 × 0.25hr | **~$1.10** |
| RunPod serverless | RTX 4090 | ~$0.00044/s × actual compute | **~$0.50–1.50** |

Vast.ai is **~40–50% cheaper** for batch workloads when spot availability is good.

---

## API & Developer Experience

### Vast.ai API

**Strengths:**
- Offer search is powerful (filter by reliability, GPU RAM, bandwidth, cost)
- Instance creation is a single POST with Docker image + onstart script
- SSH key attachment via API

**Weaknesses:**
- Single-instance GET wraps response as `{"instances": {fields}}` (not a list)
- No official Python SDK (we use raw requests)
- API responses can be inconsistent (fields missing, types changing)
- No webhook/callback for instance state changes — must poll
- Rate limiting is undocumented
- Instance status strings are inconsistent (`"running"`, `"loading"`, `""`, `"exited"`)

### RunPod API

**Strengths:**
- Official Python SDK (`runpod` pip package)
- GraphQL API (flexible queries)
- REST API for pods (create, start, stop, terminate)
- Serverless endpoint API (deploy functions, auto-scale)
- Webhooks for job completion (serverless)
- Well-documented status transitions

**Weaknesses:**
- GraphQL can be verbose for simple operations
- Community Cloud availability varies by region

---

## Reliability & Uptime

### Vast.ai

- Peer-to-peer = variable quality. Even with `reliability2 >= 0.95`:
  - ~30% instance churn rate in our runs (down from ~80% without filtering)
  - Hosts sometimes can't resolve DNS, fail Docker builds, or sit in "loading" forever
  - Provider can reclaim machine at any time (spot)
  - Our health_check + self-healing replaces dead instances automatically

### RunPod

- Secure Cloud: datacenter-grade, very reliable
- Community Cloud: shared hosts, slightly less reliable but still vetted
- Built-in health monitoring + auto-restart
- Instance persistence (volumes survive restarts)
- Network storage for shared data across pods

---

## Architecture Fit for OpenCure Labs

### What We Need

1. **Batch GPU execution** — Run 10–50 short-lived instances (5–30 min each)
2. **SSH access** — Execute Python skills remotely via SSH
3. **Docker** — Custom image with PyTorch + our wheel
4. **Budget controls** — Hard cap on spending
5. **API-driven provisioning** — Pool manager creates/destroys via API
6. **Fast boot** — Minimize time from provision to ready

### Vast.ai Fit

| Requirement | Status |
|------------|--------|
| Batch execution | Works, but requires self-healing for flaky hosts |
| SSH access | Root SSH, key attachment via API |
| Docker | Custom image + onstart script |
| Budget controls | API balance check only — we built our own |
| API provisioning | Works but quirky |
| Fast boot | 2–8 min (highly variable by host) |

### RunPod Fit

| Requirement | Status |
|------------|--------|
| Batch execution | Pods for SSH, or Serverless for function execution |
| SSH access | Root SSH via pods |
| Docker | Custom templates, pre-cached images (faster) |
| Budget controls | Built-in spending limits |
| API provisioning | Clean SDK, GraphQL |
| Fast boot | 30s–3 min (template caching) |

### RunPod Serverless — A Different Model

RunPod Serverless could eliminate most of our pool management complexity:

**Current architecture (Vast.ai):**
```
Task Generator → Queue → Pool Manager → Workers → SSH → Instance
                         (provision)    (threads)   (execute)
```

**With RunPod Serverless:**
```
Task Generator → RunPod Serverless Endpoint → Auto-scaled workers
```

- No pool management code needed
- No SSH, no health checks, no orphan protection
- Pay only for actual compute time (auto-scales to zero)
- But: requires packaging skills as RunPod handler functions instead of SSH scripts

---

## Migration Effort

### Option A: RunPod Pods (Drop-in Replacement)

Swap Vast.ai API calls for RunPod API calls. Keep pool_manager + SSH execution.

**Changes needed:**
- New `runpod_dispatcher.py` replacing `vast_dispatcher.py`
- Update `pool_manager.py` to use RunPod pod lifecycle API
- Update `__init__.py` onstart script for RunPod template format
- Update `cli.py` burst on/off commands
- Keep: worker.py, batch_queue.py, batch_dispatcher.py mostly unchanged
- **Effort: ~2–3 days**

### Option B: RunPod Serverless (Full Rewrite of Compute Layer)

Package each skill as a RunPod serverless handler. Eliminate pool management entirely.

**Changes needed:**
- Create RunPod handler wrapper for each skill
- New serverless dispatcher (replaces pool_manager + worker + SSH)
- Simplify batch_dispatcher — no pool lifecycle
- Build Docker image as RunPod serverless template
- **Effort: ~1–2 weeks**
- **Benefit: Eliminates ~1500 lines of pool management code**

### Option C: Hybrid (Recommended Short-Term)

Keep Vast.ai for cheap batch compute, add RunPod as fallback when Vast.ai spot market is dry.

**Changes needed:**
- Abstract provider interface in pool_manager
- `VastProvider` + `RunPodProvider` behind common API
- Dispatcher picks cheapest available provider per instance
- **Effort: ~3–4 days**

---

## Recommendation

| Timeline | Action |
|----------|--------|
| **Now** | Stay on Vast.ai — it's 40–50% cheaper and working |
| **Short-term** | Fix the `run_batch()` crash protection (done — see below) |
| **Medium-term** | Add RunPod as fallback provider (Option C) |
| **Long-term** | Evaluate RunPod Serverless if pool management becomes a maintenance burden |

### Key Decision Factors

- **If cost is #1 priority** → Stay on Vast.ai
- **If reliability is #1 priority** → Switch to RunPod
- **If simplicity is #1 priority** → RunPod Serverless
- **If budget is tight but uptime matters** → Hybrid (Option C)

---

## Related

- [docs/VAST_AI.md](VAST_AI.md) — Current Vast.ai compute layer documentation
- [scripts/vast_watchdog.sh](../scripts/vast_watchdog.sh) — Orphan instance watchdog
- [packages/agentiq_labclaw/agentiq_labclaw/compute/](../packages/agentiq_labclaw/agentiq_labclaw/compute/) — Compute layer source

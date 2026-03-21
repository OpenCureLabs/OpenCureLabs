"""
Batch dispatcher — orchestrates large-scale research task execution on Vast.ai.

Ties together:
  - task_generator: creates parameterized research tasks
  - batch_queue:    PostgreSQL job queue with atomic claiming
  - pool_manager:   Vast.ai instance fleet management
  - worker:         per-instance SSH job executor

Usage:
    # From Python
    from agentiq_labclaw.compute.batch_dispatcher import run_batch
    results = run_batch(count=100, pool_size=10)

    # From CLI
    python -m agentiq_labclaw.compute.batch_dispatcher --count 100 --pool-size 10
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time

logger = logging.getLogger("labclaw.compute.batch_dispatcher")


def run_batch(
    count: int = 100,
    pool_size: int = 10,
    max_cost_hr: float = 0.50,
    domain: str | None = None,
    config_path: str | None = None,
    seed: int | None = None,
    image: str | None = None,
    progress_callback=None,
) -> dict:
    """Run a full batch dispatch cycle.

    1. Generate tasks
    2. Submit to queue
    3. Provision instance pool
    4. Wait for instances to be ready
    5. Launch workers (one thread per instance)
    6. Monitor progress
    7. Teardown pool
    8. Return summary

    Args:
        count:             Number of tasks to generate and run.
        pool_size:         Number of Vast.ai instances to provision.
        max_cost_hr:       Maximum cost per hour per instance.
        domain:            Optional domain filter ("cancer", "drug_discovery", "rare_disease").
        config_path:       Path to research_tasks.yaml for custom task config.
        seed:              Random seed for task generation reproducibility.
        image:             Docker image for Vast.ai instances (default: labclaw-gpu).
        progress_callback: Optional callable(status_dict) called every 10s for live updates.

    Returns:
        Summary dict with counts, timing, and cost.
    """
    from agentiq_labclaw.compute.batch_queue import BatchQueue
    from agentiq_labclaw.compute.pool_manager import PoolManager
    from agentiq_labclaw.compute.worker import Worker
    from agentiq_labclaw.task_generator import generate_batch

    start_time = time.monotonic()

    # ── 1. Generate tasks ────────────────────────────────────────────────
    _log("Generating %d tasks (domain=%s)...", count, domain or "all")
    tasks = generate_batch(
        count=count,
        domain=domain,
        config_path=config_path,
        seed=seed,
    )
    _log("Generated %d tasks across %d skill types", len(tasks), len(set(t.skill_name for t in tasks)))

    # ── 2. Submit to queue ───────────────────────────────────────────────
    queue = BatchQueue()
    batch_id = queue.submit_batch(tasks)
    _log("Submitted batch %s with %d jobs", batch_id, len(tasks))

    # ── 3. Provision instance pool ───────────────────────────────────────
    _log("Provisioning %d Vast.ai instances (max $%.2f/hr each)...", pool_size, max_cost_hr)
    pool = PoolManager(
        target_size=pool_size,
        gpu_required=True,
        max_cost_hr=max_cost_hr,
        image=image,
    )

    try:
        pool.scale_up()
    except RuntimeError as e:
        _log("Pool provisioning failed: %s — aborting batch", e)
        return _make_summary(batch_id, queue, pool, start_time, error=str(e))

    # ── 4. Wait for at least 1 instance to be ready ──────────────────────
    _log("Waiting for instances to be ready (setup + pip install)...")
    try:
        pool.wait_for_ready(min_ready=1, timeout=1800, progress_fn=_log)
    except TimeoutError as e:
        _log("No instances became ready: %s — aborting", e)
        pool.teardown()
        return _make_summary(batch_id, queue, pool, start_time, error=str(e))

    ready = pool.get_ready_instances()
    _log("%d/%d instances ready — launching workers", len(ready), pool.active_count)

    # ── 5. Launch worker threads ─────────────────────────────────────────
    workers: list[Worker] = []
    threads: list[threading.Thread] = []

    for inst in ready:
        w = Worker(
            instance_id=inst.instance_id,
            ssh_host=inst.ssh_host,
            ssh_port=inst.ssh_port,
            queue=queue,
            pool_manager=pool,
            batch_id=batch_id,
        )
        workers.append(w)
        t = threading.Thread(
            target=w.run,
            name=f"worker-{inst.instance_id}",
            daemon=True,
        )
        threads.append(t)
        t.start()

    _log("Launched %d worker threads", len(threads))

    # ── 6. Monitor progress ──────────────────────────────────────────────
    try:
        _monitor_loop(batch_id, queue, pool, workers, threads, progress_callback)
    except KeyboardInterrupt:
        _log("Interrupted — stopping workers...")
        for w in workers:
            w.stop()

    # Wait for workers to finish
    for t in threads:
        t.join(timeout=30)

    # ── 7. Reclaim any stale jobs ────────────────────────────────────────
    reclaimed = queue.reclaim_stale_jobs(stale_minutes=5)
    if reclaimed:
        _log("Reclaimed %d stale jobs", reclaimed)

    # ── 8. Teardown pool ─────────────────────────────────────────────────
    _log("Tearing down instance pool...")
    pool.teardown()

    # ── 9. Summary ───────────────────────────────────────────────────────
    summary = _make_summary(batch_id, queue, pool, start_time)
    _log("Batch complete: %s", json.dumps(summary, indent=2))
    return summary


def _monitor_loop(batch_id, queue, pool, workers, threads, callback=None):
    """Poll batch status every 10s until all jobs are done or all workers dead."""
    while True:
        alive = [t for t in threads if t.is_alive()]
        status = queue.batch_status(batch_id)
        pending = status.get("pending", 0)
        running = status.get("running", 0)
        done = status.get("done", 0)
        failed = status.get("failed", 0)
        total = status.get("total", 0)

        pool_summary = pool.summary()

        progress = {
            "batch_id": batch_id,
            "pending": pending,
            "running": running,
            "done": done,
            "failed": failed,
            "total": total,
            "workers_alive": len(alive),
            "pool": pool_summary,
        }

        _log(
            "Progress: %d/%d done, %d running, %d pending, %d failed | %d workers alive",
            done, total, running, pending, failed, len(alive),
        )

        if callback:
            callback(progress)

        # Check if done
        if pending == 0 and running == 0:
            _log("All jobs processed")
            break

        # Check if all workers died but jobs remain
        if not alive and (pending > 0 or running > 0):
            _log("All workers stopped but %d jobs remain — attempting recovery", pending + running)
            # Try to spin up new instances for remaining work
            queue.reclaim_stale_jobs(stale_minutes=1)
            break

        # Auto-scale pool based on queue depth
        from agentiq_labclaw.compute.vast_dispatcher import get_account_balance, get_total_spend
        balance = get_account_balance()
        spent = get_total_spend()
        pool.auto_scale(pending, balance - spent)

        # Check for newly ready instances and start workers for them
        new_ready = [
            i for i in pool.get_ready_instances()
            if i.instance_id not in {w.instance_id for w in workers}
        ]
        for inst in new_ready:
            from agentiq_labclaw.compute.worker import Worker
            w = Worker(
                instance_id=inst.instance_id,
                ssh_host=inst.ssh_host,
                ssh_port=inst.ssh_port,
                queue=queue,
                pool_manager=pool,
                batch_id=batch_id,
            )
            workers.append(w)
            t = threading.Thread(
                target=w.run,
                name=f"worker-{inst.instance_id}",
                daemon=True,
            )
            threads.append(t)
            t.start()
            _log("Started new worker for instance %d", inst.instance_id)

        time.sleep(10)


def _make_summary(batch_id, queue, pool, start_time, error=None):
    """Build a summary dict for the batch run."""
    elapsed = time.monotonic() - start_time
    status = queue.batch_status(batch_id)
    pool_info = pool.summary()

    summary = {
        "batch_id": batch_id,
        "jobs": status,
        "pool": pool_info,
        "elapsed_seconds": round(elapsed, 1),
        "elapsed_human": f"{int(elapsed // 60)}m {int(elapsed % 60)}s",
    }
    if error:
        summary["error"] = error
    return summary


def _log(msg, *args):
    """Log to both logger and stdout for terminal visibility."""
    formatted = msg % args if args else msg
    logger.info(formatted)
    print(f"  [batch] {formatted}", flush=True)


# ── CLI entry point ──────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Run batch research tasks on Vast.ai instance pool",
    )
    parser.add_argument("--count", type=int, default=100, help="Number of tasks (default: 100)")
    parser.add_argument("--pool-size", type=int, default=10, help="Instance pool size (default: 10)")
    parser.add_argument("--max-cost", type=float, default=0.50, help="Max $/hr per instance (default: 0.50)")
    parser.add_argument("--domain", choices=["cancer", "drug_discovery", "rare_disease"])
    parser.add_argument("--config", help="Path to research_tasks.yaml")
    parser.add_argument("--image", help="Docker image for Vast.ai instances (default: labclaw-gpu)")
    parser.add_argument("--seed", type=int, help="Random seed for task generation")
    parser.add_argument("--dry-run", action="store_true", help="Generate tasks only, don't dispatch")
    args = parser.parse_args()

    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
    )

    if args.dry_run:
        from agentiq_labclaw.task_generator import generate_batch
        tasks = generate_batch(
            count=args.count, domain=args.domain,
            config_path=args.config, seed=args.seed,
        )
        print(f"\nDry run: {len(tasks)} tasks would be dispatched to {args.pool_size} instances")
        skills = {}
        for t in tasks:
            skills[t.skill_name] = skills.get(t.skill_name, 0) + 1
        for s, c in sorted(skills.items(), key=lambda x: -x[1]):
            print(f"  {s:30s} {c:3d}")
        return

    # Load .env for API keys
    from pathlib import Path
    env_path = Path(__file__).resolve().parents[4] / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))

    result = run_batch(
        count=args.count,
        pool_size=args.pool_size,
        max_cost_hr=args.max_cost,
        domain=args.domain,
        config_path=args.config,
        seed=args.seed,
        image=args.image,
    )

    # Print final summary
    print("\n" + "=" * 50)
    print("  BATCH DISPATCH COMPLETE")
    print("=" * 50)
    jobs = result.get("jobs", {})
    print(f"  Batch ID:  {result['batch_id']}")
    print(f"  Done:      {jobs.get('done', 0)}")
    print(f"  Failed:    {jobs.get('failed', 0)}")
    print(f"  Time:      {result['elapsed_human']}")
    pool = result.get("pool", {})
    print(f"  Instances: {pool.get('active', 0)} used")
    print(f"  Jobs/inst: {pool.get('total_jobs_completed', 0)}")
    if result.get("error"):
        print(f"  Error:     {result['error']}")
    print("=" * 50)


if __name__ == "__main__":
    main()

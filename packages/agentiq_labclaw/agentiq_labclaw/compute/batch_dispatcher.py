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
import signal
import threading
import time

logger = logging.getLogger("labclaw.compute.batch_dispatcher")


def _get_genesis_run_id() -> str:
    """Return a genesis_run_id for the current session.

    Uses GENESIS_START env var (Unix timestamp) to build an ID matching the
    log directory naming convention: ``genesis-YYYYMMDD-HHMMSS``.
    Falls back to the current time if GENESIS_START is not set.
    """
    import datetime as _dt

    ts = os.environ.get("GENESIS_START")
    if ts:
        dt = _dt.datetime.fromtimestamp(float(ts))
    else:
        dt = _dt.datetime.now()
    return dt.strftime("genesis-%Y%m%d-%H%M%S")

# Module-level shutdown event — set by SIGINT/SIGTERM handler
_shutdown = threading.Event()


def _install_signal_handlers():
    """Install SIGINT/SIGTERM handler that sets the _shutdown event."""
    def _handler(signum, frame):
        _log("Shutdown signal received — finishing current cycle...")
        _shutdown.set()

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)


def _launch_workers(pool, queue, batch_id, idle_timeout=0):
    """Launch one worker thread per ready instance. Returns (workers, threads)."""
    from agentiq_labclaw.compute.worker import Worker

    workers: list[Worker] = []
    threads: list[threading.Thread] = []

    for inst in pool.get_ready_instances():
        w = Worker(
            instance_id=inst.instance_id,
            ssh_host=inst.ssh_host,
            ssh_port=inst.ssh_port,
            queue=queue,
            pool_manager=pool,
            batch_id=batch_id,
            idle_timeout=idle_timeout,
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
    return workers, threads


def _record_agent_run(agent_name: str, status: str = "running") -> int:
    """Insert an agent_runs row and return its id."""
    import psycopg2
    conn = psycopg2.connect(os.environ.get("POSTGRES_URL", "dbname=opencurelabs port=5433"))
    try:
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO agent_runs (agent_name, status) VALUES (%s, %s) RETURNING id",
            (agent_name, status),
        )
        run_id = cur.fetchone()[0]
        cur.close()
        return run_id
    finally:
        conn.close()


def _update_agent_run(run_id: int, status: str, result: dict | None = None):
    """Update an agent_runs row with final status."""
    import psycopg2
    conn = psycopg2.connect(os.environ.get("POSTGRES_URL", "dbname=opencurelabs port=5433"))
    try:
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(
            "UPDATE agent_runs SET status = %s, completed_at = NOW(), result_json = %s WHERE id = %s",
            (status, json.dumps(result, default=str) if result else None, run_id),
        )
        cur.close()
    finally:
        conn.close()


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
    from agentiq_labclaw.task_generator import generate_batch

    start_time = time.monotonic()
    run_id = _record_agent_run("batch_dispatch", "running")
    genesis_run_id = _get_genesis_run_id()
    _log("Genesis run ID: %s", genesis_run_id)

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
    batch_id = queue.submit_batch(tasks, genesis_run_id=genesis_run_id)
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
        _update_agent_run(run_id, "failed", {"error": str(e)})
        return _make_summary(batch_id, queue, pool, start_time, error=str(e))

    # ── 4. Wait for at least 1 instance to be ready ──────────────────────
    _log("Waiting for instances to be ready (setup + pip install)...")
    try:
        pool.wait_for_ready(min_ready=1, timeout=1800, progress_fn=_log)
    except TimeoutError as e:
        _log("No instances became ready: %s — aborting", e)
        pool.teardown()
        _update_agent_run(run_id, "failed", {"error": str(e)})
        return _make_summary(batch_id, queue, pool, start_time, error=str(e))

    ready = pool.get_ready_instances()
    _log("%d/%d instances ready — launching workers", len(ready), pool.active_count)

    # ── 5. Launch worker threads ─────────────────────────────────────────
    workers, threads = _launch_workers(pool, queue, batch_id)

    # ── 6–8. Monitor, reclaim, teardown — wrapped in try-finally to
    #         guarantee instance cleanup if the orchestrator crashes ───────
    try:
        try:
            _monitor_loop(batch_id, queue, pool, workers, threads, progress_callback)
        except KeyboardInterrupt:
            _log("Interrupted — stopping workers...")
            for w in workers:
                w.stop()

        # Wait for workers to finish
        for t in threads:
            t.join(timeout=30)

        # ── 7. Reclaim any stale jobs ────────────────────────────────
        reclaimed = queue.reclaim_stale_jobs(stale_minutes=5)
        if reclaimed:
            _log("Reclaimed %d stale jobs", reclaimed)

    finally:
        # ── 8. Teardown pool — always runs even on crash ─────────────
        _log("Tearing down instance pool...")
        pool.teardown()

    # ── 9. Summary ───────────────────────────────────────────────────────
    summary = _make_summary(batch_id, queue, pool, start_time)
    _update_agent_run(run_id, "completed", summary)
    _log("Batch complete: %s", json.dumps(summary, indent=2))
    return summary


def _monitor_loop(batch_id, queue, pool, workers, threads, callback=None, idle_timeout=0):
    """Poll batch status every 10s until all jobs are done or all workers dead."""
    stall_count = 0
    stall_cycles = 0  # how many times health-check fired due to stall
    max_stall_cycles = int(os.environ.get("LABCLAW_MAX_STALL_CYCLES", "3"))
    batch_timeout = int(os.environ.get("LABCLAW_BATCH_TIMEOUT", "1800"))  # 30 min default
    batch_start = time.monotonic()
    last_done = -1
    while not _shutdown.is_set():
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

        # Hard batch timeout — prevent indefinite runs
        elapsed = time.monotonic() - batch_start
        if batch_timeout > 0 and elapsed > batch_timeout:
            _log(
                "BATCH TIMEOUT: %dm%ds elapsed (limit %dm) — stopping",
                int(elapsed // 60), int(elapsed % 60), batch_timeout // 60,
            )
            queue.reclaim_stale_jobs(stale_minutes=1)
            break

        # Check if done
        if pending == 0 and running == 0:
            _log("All jobs processed")
            break

        # Check if all workers died but jobs remain
        if not alive and (pending > 0 or running > 0):
            _log("All workers stopped but %d jobs remain — attempting recovery", pending + running)
            queue.reclaim_stale_jobs(stale_minutes=1)
            # Relaunch workers on still-ready instances instead of giving up
            workers, threads = _launch_workers(pool, queue, batch_id, idle_timeout=idle_timeout)
            if not threads:
                _log("No ready instances — cannot recover")
                break
            _log("Relaunched %d workers — continuing", len(threads))

        # Auto-scale pool based on queue depth + budget floor guard
        from agentiq_labclaw.compute.vast_dispatcher import get_account_balance
        balance = get_account_balance()
        budget_floor = float(os.environ.get("LABCLAW_BUDGET_FLOOR", "5.0"))
        if balance > 0 and balance < budget_floor:
            _log(
                "BUDGET FLOOR: Vast.ai balance $%.2f < $%.2f floor — tearing down pool",
                balance, budget_floor,
            )
            _shutdown.set()
            break
        pool.auto_scale(pending, balance)

        # Poll provisioning/setup instances for readiness transitions
        pool.poll_readiness()

        # Stop workers whose instances have been destroyed
        destroyed_ids = {
            iid for iid, inst in pool.instances.items()
            if inst.status in ("destroyed", "failed")
        }
        for w in workers:
            if w.instance_id in destroyed_ids and not w._stop.is_set():
                _log("Stopping worker for destroyed instance %d", w.instance_id)
                w.stop()

        # Check for newly ready instances and start workers for them
        # Only exclude instances that have a live (non-stopped) worker
        active_instance_ids = {w.instance_id for w in workers if not w._stop.is_set()}
        new_ready = [
            i for i in pool.get_ready_instances()
            if i.instance_id not in active_instance_ids
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
                idle_timeout=idle_timeout,
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

        # Stall detection — if no progress for 2 minutes, run health check
        if done == last_done:
            stall_count += 1
        else:
            stall_count = 0
            stall_cycles = 0  # real progress resets escalation
            last_done = done

        if stall_count >= 12 and (pending > 0 or running > 0):  # 12 × 10s = 2 min
            stall_cycles += 1
            _log(
                "Stall detected (%d iterations no progress, cycle %d/%d) — running health check",
                stall_count, stall_cycles, max_stall_cycles,
            )

            if stall_cycles >= max_stall_cycles:
                _log(
                    "MAX STALL CYCLES reached (%d) — giving up on %d remaining jobs",
                    max_stall_cycles, pending + running,
                )
                queue.reclaim_stale_jobs(stale_minutes=1)
                break

            replaced = pool.health_check(progress_fn=_log)
            if replaced:
                _log("Health check replaced %d instances mid-cycle — restarting workers", replaced)
                for w in workers:
                    w.stop()
                for t in threads:
                    t.join(timeout=10)
                workers, threads = _launch_workers(pool, queue, batch_id, idle_timeout=idle_timeout)
            elif pending > 0 and running == 0:
                # Jobs waiting but nobody running them — relaunch workers on alive instances
                _log("Orphaned jobs detected (pending=%d, running=0) — relaunching workers", pending)
                queue.reclaim_stale_jobs(stale_minutes=1)
                for w in workers:
                    w.stop()
                for t in threads:
                    t.join(timeout=10)
                workers, threads = _launch_workers(pool, queue, batch_id, idle_timeout=idle_timeout)
            else:
                # Reclaim any jobs stuck on dead instances
                queue.reclaim_stale_jobs(stale_minutes=1)
            stall_count = 0

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


# ── Continuous mode ──────────────────────────────────────────────────────────

def run_continuous(
    count: int = 20,
    pool_size: int = 3,
    max_cost_hr: float = 0.50,
    domain: str | None = None,
    config_path: str | None = None,
    seed: int | None = None,
    image: str | None = None,
    budget: float | None = None,
    cycles: int | None = None,
    cooldown: int = 5,
    progress_callback=None,
) -> list[dict]:
    """Run Genesis Mode continuously — batch after batch on a persistent pool.

    Provisions Vast.ai instances once, then loops:
      1. Check budget headroom
      2. Generate + submit a batch
      3. Workers pick up jobs (idle-polling between cycles)
      4. Monitor until batch completes
      5. Log cycle summary
      6. Cooldown pause
      7. Repeat until budget exhausted, cycle limit hit, or Ctrl+C

    Args:
        count:             Tasks per cycle.
        pool_size:         Number of Vast.ai instances.
        max_cost_hr:       Max $/hr per instance.
        domain:            Optional skill domain filter.
        config_path:       Custom task config YAML path.
        seed:              Base seed (incremented per cycle).
        image:             Docker image override.
        budget:            Total $ budget (None = use VAST_AI_BUDGET env).
        cycles:            Max number of cycles (None = unlimited).
        cooldown:          Seconds to pause between cycles.
        progress_callback: Optional callable(status_dict).

    Returns:
        List of per-cycle summary dicts.
    """
    from agentiq_labclaw.compute.batch_queue import BatchQueue
    from agentiq_labclaw.compute.pool_manager import PoolManager
    from agentiq_labclaw.compute.vast_dispatcher import check_budget

    _install_signal_handlers()
    _shutdown.clear()

    if budget is not None:
        os.environ["VAST_AI_BUDGET"] = str(budget)

    start_time = time.monotonic()
    summaries: list[dict] = []
    cycle = 0
    run_id = _record_agent_run("continuous_batch", "running")
    genesis_run_id = _get_genesis_run_id()
    _log("Genesis run ID: %s", genesis_run_id)

    # ── Provision pool once ──────────────────────────────────────────────
    _log("=== CONTINUOUS MODE ===")
    _log("Provisioning %d instances (max $%.2f/hr each)...", pool_size, max_cost_hr)

    pool = PoolManager(
        target_size=pool_size,
        gpu_required=True,
        max_cost_hr=max_cost_hr,
        image=image,
    )

    try:
        pool.scale_up()
    except RuntimeError as e:
        _log("Pool provisioning failed: %s", e)
        return summaries

    _log("Waiting for instances to be ready...")
    try:
        pool.wait_for_ready(min_ready=1, timeout=1800, progress_fn=_log)
    except TimeoutError as e:
        _log("No instances became ready: %s", e)
        pool.teardown()
        return summaries

    ready_count = len(pool.get_ready_instances())
    _log("%d instances ready — entering continuous loop", ready_count)

    queue = BatchQueue()

    # Launch workers with idle_timeout so they persist between cycles
    workers, threads = _launch_workers(pool, queue, batch_id=None, idle_timeout=120)

    try:
        while not _shutdown.is_set():
            cycle += 1

            # ── Cycle limit ──────────────────────────────────────────
            if cycles is not None and cycle > cycles:
                _log("Cycle limit reached (%d cycles)", cycles)
                break

            # ── Budget check ─────────────────────────────────────────
            ok, remaining, total_budget = check_budget()
            if not ok:
                _log("Budget exhausted ($%.2f remaining of $%.2f) — stopping", remaining, total_budget)
                break

            _log("── Cycle %d (budget: $%.2f remaining) ──", cycle, remaining)

            # ── Health check — replace dead instances ────────────
            replaced = pool.health_check(progress_fn=_log)
            if replaced:
                _log("Replaced %d dead instances — pool now has %d ready", replaced, pool.ready_count)
                # Re-launch workers for new instances
                for w in workers:
                    w.stop()
                for t in threads:
                    t.join(timeout=10)
                workers, threads = _launch_workers(pool, queue, batch_id=None, idle_timeout=120)

            # ── Relaunch dead worker threads ─────────────────────
            # Workers exit after idle_timeout expires between cycles.
            # Instances are still running — only the threads are dead.
            dead = [t for t in threads if not t.is_alive()]
            if dead and not replaced:  # skip if health_check already relaunched
                _log("Relaunching %d/%d workers (idle timeout expired)", len(dead), len(threads))
                for w in workers:
                    w.stop()
                for t in threads:
                    t.join(timeout=10)
                workers, threads = _launch_workers(pool, queue, batch_id=None, idle_timeout=120)

            cycle_run_id = _record_agent_run(f"batch_cycle_{cycle}", "running")

            # ── Generate + submit ────────────────────────────────────
            from agentiq_labclaw.task_generator import generate_batch

            cycle_seed = (seed + cycle - 1) if seed is not None else None
            tasks = generate_batch(
                count=count,
                domain=domain,
                config_path=config_path,
                seed=cycle_seed,
            )
            batch_id = queue.submit_batch(tasks, genesis_run_id=genesis_run_id)
            _log("Submitted batch %s with %d jobs", batch_id, len(tasks))

            # Update workers to pick up new batch_id
            for w in workers:
                w.batch_id = batch_id

            # ── Monitor ──────────────────────────────────────────────
            _monitor_loop(batch_id, queue, pool, workers, threads, progress_callback, idle_timeout=120)

            # ── Reclaim stale ────────────────────────────────────────
            reclaimed = queue.reclaim_stale_jobs(stale_minutes=2)
            if reclaimed:
                _log("Reclaimed %d stale jobs", reclaimed)

            # ── Cycle summary ────────────────────────────────────────
            summary = _make_summary(batch_id, queue, pool, start_time)
            summaries.append(summary)
            jobs = summary.get("jobs", {})
            _update_agent_run(cycle_run_id, "completed", {
                "cycle": cycle, "batch_id": batch_id,
                "done": jobs.get("done", 0), "failed": jobs.get("failed", 0),
            })
            _log(
                "Cycle %d complete: %d/%d done, %d failed",
                cycle, jobs.get("done", 0), jobs.get("total", 0), jobs.get("failed", 0),
            )

            # ── Cooldown ─────────────────────────────────────────────
            if not _shutdown.is_set() and (cycles is None or cycle < cycles):
                _log("Cooldown %ds before next cycle...", cooldown)
                _shutdown.wait(cooldown)  # interruptible sleep

    finally:
        # Suppress extra KeyboardInterrupt during cleanup so teardown completes
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)

        _log("Stopping workers...")
        for w in workers:
            w.stop()
        for t in threads:
            t.join(timeout=10)

        _log("Tearing down instance pool...")
        pool.teardown()

        # Mark all running agent_runs from this session as cancelled
        try:
            import psycopg2
            conn = psycopg2.connect("dbname=opencurelabs port=5433")
            cur = conn.cursor()
            cur.execute(
                "UPDATE agent_runs SET status = 'cancelled', completed_at = NOW() "
                "WHERE status = 'running' AND started_at >= %s",
                (summaries[0]["jobs"].get("created_at"),) if summaries else (None,),
            )
            # Fallback: cancel the specific run_id and any cycle runs started after it
            cur.execute(
                "UPDATE agent_runs SET status = 'cancelled', completed_at = NOW() "
                "WHERE status = 'running' AND id >= %s",
                (run_id,),
            )
            conn.commit()
            conn.close()
            _log("Marked stale agent_runs as cancelled")
        except Exception as e:
            _log("Failed to clean up agent_runs: %s", e)

        # Restore default signal handling
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)

    total_elapsed = time.monotonic() - start_time
    total_done = sum(s.get("jobs", {}).get("done", 0) for s in summaries)
    total_failed = sum(s.get("jobs", {}).get("failed", 0) for s in summaries)
    _update_agent_run(run_id, "completed", {
        "cycles": len(summaries), "done": total_done, "failed": total_failed,
        "elapsed_seconds": round(total_elapsed, 1),
    })
    _log(
        "=== CONTINUOUS MODE COMPLETE: %d cycles, %d done, %d failed, %dm%ds ===",
        cycle if cycles is None or cycle <= cycles else cycles,
        total_done,
        total_failed,
        int(total_elapsed // 60),
        int(total_elapsed % 60),
    )

    return summaries


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
    parser.add_argument("--domain", choices=["cancer", "drug_discovery", "rare_disease", "canine", "feline"])
    parser.add_argument("--config", help="Path to research_tasks.yaml")
    parser.add_argument("--image", help="Docker image for Vast.ai instances (default: labclaw-gpu)")
    parser.add_argument("--seed", type=int, help="Random seed for task generation")
    parser.add_argument("--dry-run", action="store_true", help="Generate tasks only, don't dispatch")
    # Continuous mode flags
    parser.add_argument("--continuous", action="store_true", help="Run in continuous mode (loop batches)")
    parser.add_argument("--budget", type=float, help="Total $ budget for continuous mode")
    parser.add_argument("--cycles", type=int, help="Max number of cycles (default: unlimited)")
    parser.add_argument("--cooldown", type=int, default=5, help="Seconds between cycles (default: 5)")
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

    if args.continuous:
        summaries = run_continuous(
            count=args.count,
            pool_size=args.pool_size,
            max_cost_hr=args.max_cost,
            domain=args.domain,
            config_path=args.config,
            seed=args.seed,
            image=args.image,
            budget=args.budget,
            cycles=args.cycles,
            cooldown=args.cooldown,
        )

        # Print final continuous summary
        print("\n" + "=" * 50)
        print("  CONTINUOUS DISPATCH COMPLETE")
        print("=" * 50)
        total_done = sum(s.get("jobs", {}).get("done", 0) for s in summaries)
        total_failed = sum(s.get("jobs", {}).get("failed", 0) for s in summaries)
        print(f"  Cycles:    {len(summaries)}")
        print(f"  Done:      {total_done}")
        print(f"  Failed:    {total_failed}")
        if summaries:
            elapsed = summaries[-1].get("elapsed_seconds", 0)
            print(f"  Time:      {int(elapsed // 60)}m {int(elapsed % 60)}s")
        print("=" * 50)
    else:
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

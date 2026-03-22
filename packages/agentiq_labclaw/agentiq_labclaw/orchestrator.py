"""
Post-execution orchestrator — wires guardrails, reviewers, and publishers.

Called after every skill execution to enforce the full pipeline:
  1. Output validation (schema check)
  2. Novelty filter (DB dedup)
  3. Reviewer critique (Claude Opus + Grok literature review)
  4. Safety check (final gate)
  5. Publishing (PDF, GitHub)
  6. DB logging (experiment_results, critique_log)
"""

import json
import logging
import os
import sys

from pydantic import BaseModel

logger = logging.getLogger("labclaw.orchestrator")

# Default guardrails/publishers — used when not overridden by env or config
GUARDRAILS_DEFAULTS: dict = {
    "output_validation": True,
    "novelty_filter": True,
    "safety_check": True,
}

PUBLISHER_DEFAULTS: dict = {
    "github": {"enabled": True},
    "pdf": {"enabled": True},
    "r2": {"enabled": True},
}


def _load_yaml_config() -> dict:
    """Load LabClaw runtime settings from coordinator YAML (guardrails/publishers sections)."""
    try:
        import yaml

        config_path = os.environ.get(
            "LABCLAW_WORKFLOW_CONFIG",
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "coordinator", "labclaw_workflow.yaml"),
        )
        config_path = os.path.normpath(config_path)
        if os.path.exists(config_path):
            with open(config_path) as f:
                return yaml.safe_load(f) or {}
    except Exception as e:
        logger.debug("Could not load workflow config: %s", e)
    return {}


def _get_config() -> dict:
    """Get cached config."""
    if not hasattr(_get_config, "_cache"):
        _get_config._cache = _load_yaml_config()
    return _get_config._cache


def _guardrails_enabled(name: str) -> bool:
    """Check if a guardrail is enabled in config (falls back to defaults)."""
    config = _get_config()
    guardrails = config.get("guardrails", GUARDRAILS_DEFAULTS)
    return guardrails.get(name, GUARDRAILS_DEFAULTS.get(name, False))


def _publisher_enabled(name: str) -> bool:
    """Check if a publisher is enabled in config (falls back to defaults).

    Solo mode (OPENCURELABS_MODE=solo): only PDF runs locally.
    R2 and GitHub are silenced so personal data never leaves the machine.
    """
    # Solo mode: only PDF (local file). All external publishers are silenced.
    if os.environ.get("OPENCURELABS_MODE") == "solo":
        return name == "pdf"
    config = _get_config()
    publishers = config.get("publishers", PUBLISHER_DEFAULTS)
    pub_config = publishers.get(name, PUBLISHER_DEFAULTS.get(name, {}))
    if isinstance(pub_config, dict):
        return pub_config.get("enabled", False)
    return bool(pub_config)


async def post_execute(
    skill_name: str,
    result: BaseModel,
    run_id: int | None = None,
) -> dict:
    """
    Post-execution orchestration pipeline.

    Runs guardrails, reviewers, and publishers on a skill result.
    Returns enriched result dict with critique and publishing status.

    This function is designed to be resilient — individual step failures
    are logged but don't block the overall flow.
    """
    result_dict = result.model_dump() if isinstance(result, BaseModel) else dict(result)
    enriched = {
        "skill_name": skill_name,
        "result": result_dict,
        "orchestration": {
            "validation": None,
            "novelty": None,
            "critiques": [],
            "safety": None,
            "published": [],
        },
    }
    orch = enriched["orchestration"]

    novel = result_dict.get("novel", False)
    critique_required = result_dict.get("critique_required", False)
    critique_completed = False

    # ── Step 1: Output validation ────────────────────────────────────────
    if _guardrails_enabled("output_validation"):
        try:
            from agentiq_labclaw.guardrails.output_validator import validate_output

            output_schema = type(result) if isinstance(result, BaseModel) else None
            if output_schema:
                is_valid, error = validate_output(result, output_schema)
                orch["validation"] = {"valid": is_valid, "error": error}
                if not is_valid:
                    logger.error("Output validation failed for %s: %s", skill_name, error)
                    return enriched
        except Exception as e:
            logger.warning("Output validation error: %s", e)
            orch["validation"] = {"valid": True, "error": f"skipped: {e}"}

    # ── Step 2: Novelty filter ───────────────────────────────────────────
    if _guardrails_enabled("novelty_filter") and novel:
        try:
            from agentiq_labclaw.guardrails.novelty_filter import check_novelty

            db_novel = check_novelty(skill_name, result_dict)
            orch["novelty"] = {"is_novel": db_novel}
            novel = db_novel  # Use DB-confirmed novelty from here on
        except Exception as e:
            logger.warning("Novelty check error (proceeding with skill-reported novelty): %s", e)
            orch["novelty"] = {"is_novel": novel, "error": str(e)}

    # ── Step 3: Reviewer critique ────────────────────────────────────────
    if critique_required:
        # Claude Opus critique
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
            from reviewer.claude_reviewer import ClaudeReviewer

            reviewer = ClaudeReviewer()
            critique = reviewer.critique(
                pipeline_name=skill_name,
                result_data=result_dict,
            )
            orch["critiques"].append({"reviewer": "claude_opus", "critique": critique})
            critique_completed = True
            logger.info(
                "Claude critique for %s: score=%s, rec=%s",
                skill_name,
                critique.get("overall_score"),
                critique.get("recommendation"),
            )

            # Log to DB
            if run_id is not None:
                try:
                    from agentiq_labclaw.db.critique_log import log_critique

                    log_critique(run_id, "claude_opus", critique)
                except Exception as e:
                    logger.warning("Failed to log Claude critique to DB: %s", e)

        except Exception as e:
            logger.warning("Claude reviewer error: %s", e)
            orch["critiques"].append({"reviewer": "claude_opus", "error": str(e)})

        # Grok literature review (only if result is novel)
        if novel:
            try:
                from reviewer.grok_reviewer import GrokReviewer

                grok = GrokReviewer()
                lit_review = grok.review_literature(
                    pipeline_name=skill_name,
                    result_data=result_dict,
                )
                orch["critiques"].append({"reviewer": "grok_literature", "critique": lit_review})
                logger.info(
                    "Grok literature review for %s: score=%s, confidence=%s",
                    skill_name,
                    lit_review.get("literature_score"),
                    lit_review.get("confidence_in_finding"),
                )

                if run_id is not None:
                    try:
                        from agentiq_labclaw.db.critique_log import log_critique

                        log_critique(run_id, "grok_literature", lit_review)
                    except Exception as e:
                        logger.warning("Failed to log Grok critique to DB: %s", e)

            except Exception as e:
                logger.warning("Grok reviewer error: %s", e)
                orch["critiques"].append({"reviewer": "grok_literature", "error": str(e)})

    # ── Step 4: Safety check ─────────────────────────────────────────────
    if _guardrails_enabled("safety_check"):
        try:
            from agentiq_labclaw.guardrails.safety_check import safety_check

            is_safe, reason = safety_check(
                output=result,
                agent_run_id=run_id,
                critique_completed=critique_completed,
            )
            orch["safety"] = {"safe": is_safe, "reason": reason}
            if not is_safe:
                logger.warning("Safety check blocked publishing for %s: %s", skill_name, reason)
                # Store the blocked result so it's visible in the dashboard
                if run_id is not None:
                    try:
                        from agentiq_labclaw.db.experiment_results import store_result

                        store_result(
                            pipeline_run_id=run_id,
                            result_type=skill_name,
                            result_data=result_dict,
                            novel=novel,
                            status="blocked",
                        )
                    except Exception as e:
                        logger.warning("Failed to store blocked result: %s", e)
                return enriched
        except Exception as e:
            logger.warning("Safety check error (proceeding): %s", e)
            orch["safety"] = {"safe": True, "error": str(e)}

    # ── Step 5: Store result in DB ───────────────────────────────────────
    if run_id is not None:
        try:
            from agentiq_labclaw.db.experiment_results import store_result

            store_result(
                pipeline_run_id=run_id,
                result_type=skill_name,
                result_data=result_dict,
                novel=novel,
            )
        except Exception as e:
            logger.warning("Failed to store result in DB: %s", e)

    # ── Always write reports/last_result.json ────────────────────────────
    # Used by the solo-mode post-run R2 opt-in prompt in run_research.sh
    try:
        import pathlib
        reports_dir = pathlib.Path(os.path.dirname(__file__)).parent.parent.parent / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        last_result_path = reports_dir / "last_result.json"
        with open(last_result_path, "w") as _f:
            json.dump({"skill_name": skill_name, "result": result_dict}, _f, indent=2, default=str)
    except Exception as e:
        logger.debug("Could not write last_result.json: %s", e)

    # ── Step 6: Publishers ───────────────────────────────────────────────
    # PDF report
    pdf_path = None
    if _publisher_enabled("pdf"):
        try:
            from agentiq_labclaw.publishers.pdf_publisher import PDFPublisher

            pdf = PDFPublisher()
            sections = [
                {"heading": "Skill", "content": skill_name},
                {"heading": "Result", "content": json.dumps(result_dict, indent=2, default=str)},
            ]
            critique_data = None
            if orch["critiques"]:
                critique_data = orch["critiques"][0].get("critique")
            pdf_path = pdf.generate_report(
                title=f"{skill_name} Result",
                sections=sections,
                critique=critique_data,
            )
            orch["published"].append(f"pdf:{pdf_path}")
            logger.info("Generated PDF report: %s", pdf_path)
        except Exception as e:
            logger.warning("PDF publish error: %s", e)

    # GitHub commit
    if _publisher_enabled("github") and pdf_path:
        try:
            from agentiq_labclaw.publishers.github_publisher import GitHubPublisher

            github = GitHubPublisher()
            github.commit_result(pdf_path, skill_name)
            orch["published"].append("github")
            logger.info("Committed %s result to GitHub", skill_name)
        except Exception as e:
            logger.warning("GitHub publish error: %s", e)

    # R2 global dataset — writes to OpenCure Labs' central public bucket via ingest Worker
    if _publisher_enabled("r2") and not os.environ.get("PYTEST_CURRENT_TEST"):
        try:
            from agentiq_labclaw.publishers.r2_publisher import R2Publisher

            r2 = R2Publisher()
            if r2.enabled:
                r2_result = r2.publish_result(skill_name, result_dict, novel=novel, status="published")
                if r2_result:
                    orch["published"].append(f"r2:{r2_result.get('url', '')}")
                    logger.info("Published %s result to R2: %s", skill_name, r2_result.get("url"))
        except Exception as e:
            logger.warning("R2 publish error: %s", e)

    return enriched

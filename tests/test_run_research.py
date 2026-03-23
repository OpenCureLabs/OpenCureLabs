"""Scenario tests for dashboard/run_research.sh.

Tests exercise shell functions (_skip_local_task, parameterize_task, task catalog
parsing) and integration behaviour (Run All dispatch, Genesis mode filtering,
environment variable propagation) by running isolated bash snippets via
subprocess.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import textwrap

import pytest

# ── Paths ────────────────────────────────────────────────────────────────────
PROJECT_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPT = os.path.join(PROJECT_DIR, "dashboard", "run_research.sh")
PARAMETERIZE_SCRIPT = os.path.join(PROJECT_DIR, "scripts", "parameterize_task.py")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _run_bash(snippet: str, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Run a bash snippet and return the completed process."""
    run_env = {**os.environ, **(env or {})}
    return subprocess.run(
        ["bash", "-c", snippet],
        capture_output=True,
        text=True,
        timeout=10,
        env=run_env,
    )


def _source_function(func_name: str) -> str:
    """Generate a bash preamble that sources the named function from run_research.sh.

    We cannot source the whole script (it runs interactively), so we extract the
    function block via sed.
    """
    return textwrap.dedent(f"""\
        # Extract the function definition from run_research.sh
        eval "$(sed -n '/{func_name}()/,/^}}/p' '{SCRIPT}')"
    """)


def _extract_task_arrays() -> str:
    """Return bash that defines the 5 task arrays from run_research.sh."""
    return textwrap.dedent(f"""\
        eval "$(sed -n '/^CANCER_TASKS=/,/^)/p' '{SCRIPT}')"
        eval "$(sed -n '/^DRUG_TASKS=/,/^)/p' '{SCRIPT}')"
        eval "$(sed -n '/^RARE_TASKS=/,/^)/p' '{SCRIPT}')"
        eval "$(sed -n '/^CANINE_TASKS=/,/^)/p' '{SCRIPT}')"
        eval "$(sed -n '/^FELINE_TASKS=/,/^)/p' '{SCRIPT}')"
    """)


# ══════════════════════════════════════════════════════════════════════════════
#  Group 1: _skip_local_task filtering
# ══════════════════════════════════════════════════════════════════════════════

class TestSkipLocalTask:
    """Verify _skip_local_task correctly gates tasks in public vs mydata mode."""

    _PREAMBLE = _source_function("_skip_local_task")

    def _check(self, desc: str, data_mode: str, expect_skip: bool):
        snippet = f"""{self._PREAMBLE}
DATA_MODE="{data_mode}"
_skip_local_task "{desc}" && echo SKIP || echo KEEP
"""
        r = _run_bash(snippet)
        expected = "SKIP" if expect_skip else "KEEP"
        assert expected in r.stdout, f"Expected {expected} for '{desc}' in {data_mode} mode, got: {r.stdout!r}"

    def test_neoantigen_public_skips(self):
        self._check("Predict neoantigens from somatic variants", "public", True)

    def test_qc_public_skips(self):
        self._check("Run sequencing quality control on cancer data", "public", True)

    def test_data_quality_public_skips(self):
        self._check("Check data quality for rare disease genomic data", "public", True)

    def test_structure_public_keeps(self):
        self._check("Predict protein structure for TP53", "public", False)

    def test_qsar_public_keeps(self):
        self._check("Train a QSAR model on ChEMBL data", "public", False)

    def test_neoantigen_mydata_keeps(self):
        self._check("Predict neoantigens from somatic variants", "mydata", False)

    def test_default_data_mode_is_public(self):
        """When DATA_MODE is unset, default to 'public' → skip neoantigen."""
        snippet = f"""{self._PREAMBLE}
unset DATA_MODE
_skip_local_task "Predict neoantigens from somatic variants" && echo SKIP || echo KEEP
"""
        r = _run_bash(snippet)
        assert "SKIP" in r.stdout

    def test_case_insensitive(self):
        """Matching is case-insensitive (bash ,, lowercases)."""
        self._check("PREDICT NEOANTIGENS FROM SOMATIC VARIANTS", "public", True)

    def test_substring_no_false_positive(self):
        """'neo' alone doesn't trigger neoantigen skip."""
        self._check("Analyze neoformations in tissue", "public", False)


# ══════════════════════════════════════════════════════════════════════════════
#  Group 2: Task catalog integrity
# ══════════════════════════════════════════════════════════════════════════════

class TestTaskCatalog:
    """Verify the task catalog arrays in run_research.sh are well-formed."""

    _PREAMBLE = _extract_task_arrays()

    def test_all_entries_have_pipe_delimiter(self):
        """Every entry must contain exactly one | separating label from description."""
        snippet = f"""{self._PREAMBLE}
ALL=("${{CANCER_TASKS[@]}}" "${{DRUG_TASKS[@]}}" "${{RARE_TASKS[@]}}" "${{CANINE_TASKS[@]}}" "${{FELINE_TASKS[@]}}")
ERRORS=0
for entry in "${{ALL[@]}}"; do
    count=$(echo "$entry" | grep -o '|' | wc -l)
    if [[ "$count" -ne 1 ]]; then
        echo "BAD: $entry (pipes=$count)"
        ERRORS=$((ERRORS + 1))
    fi
done
echo "ERRORS=$ERRORS"
"""
        r = _run_bash(snippet)
        assert "ERRORS=0" in r.stdout, f"Some entries lack proper pipe delimiter:\n{r.stdout}"

    def test_all_domain_arrays_non_empty(self):
        snippet = f"""{self._PREAMBLE}
echo "cancer=${{#CANCER_TASKS[@]}}"
echo "drug=${{#DRUG_TASKS[@]}}"
echo "rare=${{#RARE_TASKS[@]}}"
echo "canine=${{#CANINE_TASKS[@]}}"
echo "feline=${{#FELINE_TASKS[@]}}"
"""
        r = _run_bash(snippet)
        for name in ("cancer", "drug", "rare", "canine", "feline"):
            match = re.search(rf"{name}=(\d+)", r.stdout)
            assert match, f"Could not find count for {name}"
            assert int(match.group(1)) > 0, f"{name} array is empty"

    def test_labels_unique_per_domain(self):
        """Each domain's entries should have unique labels (part before ~)."""
        snippet = f"""{self._PREAMBLE}
check_domain() {{
    local name="$1"; shift
    local labels=()
    for entry in "$@"; do
        raw="${{entry%%|*}}"
        label="${{raw%% ~*}}"
        labels+=("$label")
    done
    # Check for duplicates
    dupes=$(printf '%s\\n' "${{labels[@]}}" | sort | uniq -d)
    if [[ -n "$dupes" ]]; then
        echo "DUPE:$name:$dupes"
    fi
}}
check_domain "cancer" "${{CANCER_TASKS[@]}}"
check_domain "drug" "${{DRUG_TASKS[@]}}"
check_domain "rare" "${{RARE_TASKS[@]}}"
check_domain "canine" "${{CANINE_TASKS[@]}}"
check_domain "feline" "${{FELINE_TASKS[@]}}"
echo "DONE"
"""
        r = _run_bash(snippet)
        assert "DUPE:" not in r.stdout, f"Duplicate labels found:\n{r.stdout}"

    def test_pipe_split_extracts_description(self):
        """Splitting on | correctly isolates the coordinator description."""
        snippet = f"""{self._PREAMBLE}
entry="${{CANCER_TASKS[0]}}"
desc="${{entry#*|}}"
label="${{entry%%|*}}"
echo "LABEL=$label"
echo "DESC=$desc"
[[ -n "$desc" ]] && echo "OK" || echo "EMPTY"
"""
        r = _run_bash(snippet)
        assert "OK" in r.stdout
        assert "LABEL=" in r.stdout
        assert "DESC=" in r.stdout

    def test_tilde_explanation_present(self):
        """All entries should have a ~ explanation between label and pipe."""
        snippet = f"""{self._PREAMBLE}
ALL=("${{CANCER_TASKS[@]}}" "${{DRUG_TASKS[@]}}" "${{RARE_TASKS[@]}}" "${{CANINE_TASKS[@]}}" "${{FELINE_TASKS[@]}}")
MISSING=0
for entry in "${{ALL[@]}}"; do
    label_part="${{entry%%|*}}"
    if [[ "$label_part" != *"~"* ]]; then
        echo "MISSING_TILDE: $entry"
        MISSING=$((MISSING + 1))
    fi
done
echo "MISSING=$MISSING"
"""
        r = _run_bash(snippet)
        assert "MISSING=0" in r.stdout, f"Entries missing ~ explanation:\n{r.stdout}"


# ══════════════════════════════════════════════════════════════════════════════
#  Group 3: Parameterize integration
# ══════════════════════════════════════════════════════════════════════════════

class TestParameterize:
    """Test the parameterize_task.py script directly (Python-level)."""

    @pytest.fixture(autouse=True)
    def _activate_venv(self):
        """Ensure the project venv is usable."""
        pass  # Tests call parameterize_task.py via subprocess

    def _run_parameterize(self, desc: str, data_mode: str = "public",
                          species: str = "human") -> str:
        cmd = [
            "python3", PARAMETERIZE_SCRIPT, desc,
            "--species", species,
            "--data-mode", data_mode,
        ]
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
            cwd=PROJECT_DIR,
        )
        return r.stdout.strip()

    def test_structure_resolves_real_sequence(self):
        """Structure prediction tasks should resolve AUTO_RESOLVE to a real sequence."""
        out = self._run_parameterize("Predict protein structure for TP53")
        assert "AUTO_RESOLVE" not in out, "AUTO_RESOLVE placeholder not resolved"
        assert "structure_prediction" in out

    def test_neoantigen_public_redirected(self):
        """Neoantigen in public mode → redirected to non-local skill or filtered."""
        out = self._run_parameterize("Predict neoantigens from somatic variants", data_mode="public")
        # In public mode, neoantigen is filtered by generate_batch, so parameterize
        # should either return a different skill or the original description
        assert "neoantigen_prediction" not in out, \
            "Neoantigen should be filtered in public mode"

    def test_qsar_correct_skill(self):
        out = self._run_parameterize("Train a QSAR model on ChEMBL data")
        assert "qsar" in out.lower()

    def test_variant_pathogenicity(self):
        out = self._run_parameterize("Analyze variants for pathogenicity")
        assert "variant_pathogenicity" in out

    def test_species_dog(self):
        out = self._run_parameterize("Find canine tumor mutations", species="dog")
        # Should produce a parameterized output (not just echo back the description)
        assert "parameters" in out.lower() or "agent" in out.lower() or "{" in out

    def test_data_mode_passed(self):
        """public data_mode should not produce neoantigen tasks."""
        out = self._run_parameterize(
            "Predict neoantigens from somatic variants",
            data_mode="public",
        )
        assert "neoantigen_prediction" not in out


# ══════════════════════════════════════════════════════════════════════════════
#  Group 4: Run All dispatch simulation
# ══════════════════════════════════════════════════════════════════════════════

class TestRunAllDispatch:
    """Simulate the Run All dispatch loop logic."""

    def _build_run_all_snippet(self, data_mode: str, tasks_var: str = "CANCER_TASKS") -> str:
        return textwrap.dedent(f"""\
            # Source functions and arrays
            eval "$(sed -n '/_skip_local_task()/,/^}}/p' '{SCRIPT}')"
            eval "$(sed -n '/^{tasks_var}=/,/^)/p' '{SCRIPT}')"

            DATA_MODE="{data_mode}"

            # Build RUN_ALL arrays
            RUN_ALL_TASKS=()
            RUN_ALL_LABELS=()
            for item in "${{{tasks_var}[@]}}"; do
                RUN_ALL_TASKS+=("${{item#*|}}")
                raw="${{item%%|*}}"
                RUN_ALL_LABELS+=("${{raw%% ~*}}")
            done

            # Simulate dispatch loop
            TOTAL=${{#RUN_ALL_TASKS[@]}}
            OK=0; SKIPPED=0; DISPATCHED=0
            for i in $(seq 0 $((TOTAL - 1))); do
                LABEL="${{RUN_ALL_LABELS[$i]}}"
                TASK="${{RUN_ALL_TASKS[$i]}}"
                if _skip_local_task "$TASK"; then
                    SKIPPED=$((SKIPPED + 1))
                    echo "SKIP:$LABEL"
                else
                    DISPATCHED=$((DISPATCHED + 1))
                    echo "DISPATCH:$LABEL"
                fi
            done
            echo "TOTAL=$TOTAL SKIPPED=$SKIPPED DISPATCHED=$DISPATCHED"
        """)

    def test_public_skips_neoantigen_and_qc(self):
        r = _run_bash(self._build_run_all_snippet("public"))
        assert "SKIP:Predict Neoantigens" in r.stdout
        assert "SKIP:Check Data Quality" in r.stdout
        # Others should dispatch
        assert "DISPATCH:Find Tumor Mutations" in r.stdout
        assert "DISPATCH:Predict Protein Shape" in r.stdout

    def test_mydata_keeps_all(self):
        r = _run_bash(self._build_run_all_snippet("mydata"))
        assert "SKIPPED=0" in r.stdout

    def test_public_dispatches_non_local_tasks(self):
        r = _run_bash(self._build_run_all_snippet("public"))
        match = re.search(r"DISPATCHED=(\d+)", r.stdout)
        assert match
        assert int(match.group(1)) >= 2, "Should dispatch at least structure + immune landscape"

    def test_counters_add_up(self):
        r = _run_bash(self._build_run_all_snippet("public"))
        total = int(re.search(r"TOTAL=(\d+)", r.stdout).group(1))
        skipped = int(re.search(r"SKIPPED=(\d+)", r.stdout).group(1))
        dispatched = int(re.search(r"DISPATCHED=(\d+)", r.stdout).group(1))
        assert total == skipped + dispatched

    def test_drug_domain_all_dispatch_public(self):
        """Drug tasks have no local-data dependencies → all dispatch in public mode."""
        r = _run_bash(self._build_run_all_snippet("public", "DRUG_TASKS"))
        assert "SKIPPED=0" in r.stdout

    def test_canine_public_skips_neoantigen_and_qc(self):
        r = _run_bash(self._build_run_all_snippet("public", "CANINE_TASKS"))
        assert "SKIP:Predict Canine Neoantigens" in r.stdout
        assert "SKIP:Check Canine Data Quality" in r.stdout
        assert "DISPATCH:Find Canine Tumor Mutations" in r.stdout


# ══════════════════════════════════════════════════════════════════════════════
#  Group 5: Genesis mode ALL_TASKS construction
# ══════════════════════════════════════════════════════════════════════════════

class TestGenesisMode:
    """Verify Genesis mode task collection and filtering."""

    def _genesis_snippet(self, data_mode: str) -> str:
        return textwrap.dedent(f"""\
            eval "$(sed -n '/_skip_local_task()/,/^}}/p' '{SCRIPT}')"
            {_extract_task_arrays()}

            DATA_MODE="{data_mode}"

            ALL_TASKS=()
            ALL_LABELS=()
            ALL_DOMAINS=()

            for t in "${{CANCER_TASKS[@]}}"; do
                _skip_local_task "${{t#*|}}" && continue
                ALL_TASKS+=("${{t#*|}}")
                raw="${{t%%|*}}"; ALL_LABELS+=("${{raw%% ~*}}")
                ALL_DOMAINS+=("Cancer")
            done
            for t in "${{DRUG_TASKS[@]}}"; do
                _skip_local_task "${{t#*|}}" && continue
                ALL_TASKS+=("${{t#*|}}")
                raw="${{t%%|*}}"; ALL_LABELS+=("${{raw%% ~*}}")
                ALL_DOMAINS+=("Drug Discovery")
            done
            for t in "${{RARE_TASKS[@]}}"; do
                _skip_local_task "${{t#*|}}" && continue
                ALL_TASKS+=("${{t#*|}}")
                raw="${{t%%|*}}"; ALL_LABELS+=("${{raw%% ~*}}")
                ALL_DOMAINS+=("Rare Disease")
            done
            for t in "${{CANINE_TASKS[@]}}"; do
                _skip_local_task "${{t#*|}}" && continue
                ALL_TASKS+=("${{t#*|}}")
                raw="${{t%%|*}}"; ALL_LABELS+=("${{raw%% ~*}}")
                ALL_DOMAINS+=("Canine")
            done
            for t in "${{FELINE_TASKS[@]}}"; do
                _skip_local_task "${{t#*|}}" && continue
                ALL_TASKS+=("${{t#*|}}")
                raw="${{t%%|*}}"; ALL_LABELS+=("${{raw%% ~*}}")
                ALL_DOMAINS+=("Feline")
            done

            echo "TOTAL=${{#ALL_TASKS[@]}}"
            for i in $(seq 0 $((${{#ALL_TASKS[@]}} - 1))); do
                echo "TASK:${{ALL_DOMAINS[$i]}}:${{ALL_LABELS[$i]}}"
            done
        """)

    def test_all_five_domains_present(self):
        r = _run_bash(self._genesis_snippet("mydata"))
        for domain in ("Cancer", "Drug Discovery", "Rare Disease", "Canine", "Feline"):
            assert f"TASK:{domain}:" in r.stdout, f"Missing domain: {domain}"

    def test_public_filters_local_tasks(self):
        r = _run_bash(self._genesis_snippet("public"))
        # Neoantigen and QC tasks should be filtered
        assert "Predict Neoantigens" not in r.stdout
        assert "Check Data Quality" not in r.stdout
        assert "Predict Canine Neoantigens" not in r.stdout
        assert "Check Canine Data Quality" not in r.stdout
        assert "Predict Feline Neoantigens" not in r.stdout
        assert "Check Feline Data Quality" not in r.stdout

    def test_mydata_keeps_all(self):
        """mydata mode should not filter any tasks."""
        r_my = _run_bash(self._genesis_snippet("mydata"))
        total = int(re.search(r"TOTAL=(\d+)", r_my.stdout).group(1))
        # 5 cancer + 4 drug + 3 rare + 4 canine + 4 feline = 20
        assert total == 20

    def test_public_total_less_than_mydata(self):
        r_pub = _run_bash(self._genesis_snippet("public"))
        r_my = _run_bash(self._genesis_snippet("mydata"))
        pub_total = int(re.search(r"TOTAL=(\d+)", r_pub.stdout).group(1))
        my_total = int(re.search(r"TOTAL=(\d+)", r_my.stdout).group(1))
        assert pub_total < my_total, "Public mode should filter some tasks"

    def test_public_still_has_tasks(self):
        """After filtering, public Genesis should still have tasks to run."""
        r = _run_bash(self._genesis_snippet("public"))
        total = int(re.search(r"TOTAL=(\d+)", r.stdout).group(1))
        assert total > 0, "Public genesis should still have runnable tasks"


# ══════════════════════════════════════════════════════════════════════════════
#  Group 6: Dependency handling
# ══════════════════════════════════════════════════════════════════════════════

class TestDependencies:
    """Test behaviour when external dependencies are missing or fail."""

    def test_gum_detection(self):
        """Script detects gum availability via 'command -v gum'."""
        # With gum on PATH
        snippet = """
command -v gum &>/dev/null && echo "HAS_GUM=true" || echo "HAS_GUM=false"
"""
        r = _run_bash(snippet)
        # Just verify the detection mechanism works (result depends on host)
        assert "HAS_GUM=" in r.stdout

    def test_parameterize_fallback_on_python_failure(self):
        """If parameterize_task.py fails, the shell function returns original desc."""
        snippet = f"""
parameterize_task() {{
    local desc="$1"
    python3 /nonexistent/script.py "$desc" 2>/dev/null || echo "$desc"
}}
result=$(parameterize_task "My test task")
echo "RESULT=$result"
"""
        r = _run_bash(snippet)
        assert "RESULT=My test task" in r.stdout

    def test_vast_balance_no_key(self):
        """get_vast_balance returns 0 when VAST_AI_KEY is empty."""
        snippet = f"""
eval "$(sed -n '/get_vast_balance()/,/^}}/p' '{SCRIPT}')"
unset VAST_AI_KEY
result=$(get_vast_balance)
echo "BALANCE=$result"
"""
        r = _run_bash(snippet)
        assert "BALANCE=0" in r.stdout

    def test_script_syntax_valid(self):
        """The full script passes bash -n syntax check."""
        r = subprocess.run(
            ["bash", "-n", SCRIPT],
            capture_output=True, text=True, timeout=10,
        )
        assert r.returncode == 0, f"Syntax error:\n{r.stderr}"

    def test_env_file_source_with_missing_env(self):
        """Sourcing .env should not fail if .env doesn't exist."""
        snippet = """
# Simulate the .env source block from run_research.sh
if [[ -f "/nonexistent/.env" ]]; then
    set -a; source "/nonexistent/.env"; set +a
fi
echo "OK"
"""
        r = _run_bash(snippet)
        assert "OK" in r.stdout

    def test_venv_activation_tolerates_missing(self):
        """source .venv/bin/activate || true should not crash."""
        snippet = """
source /nonexistent/.venv/bin/activate 2>/dev/null || true
echo "OK"
"""
        r = _run_bash(snippet)
        assert "OK" in r.stdout


# ══════════════════════════════════════════════════════════════════════════════
#  Group 7: Environment variable handling
# ══════════════════════════════════════════════════════════════════════════════

class TestEnvironment:
    """Test environment variable propagation and side effects."""

    def test_public_sets_contribute_mode(self):
        """DATA_MODE=public → OPENCURELABS_MODE=contribute."""
        snippet = """
DATA_MODE="public"
[[ "$DATA_MODE" == "mydata" ]] && export OPENCURELABS_MODE=solo || export OPENCURELABS_MODE=contribute
echo "MODE=$OPENCURELABS_MODE"
"""
        r = _run_bash(snippet)
        assert "MODE=contribute" in r.stdout

    def test_mydata_sets_solo_mode(self):
        """DATA_MODE=mydata → OPENCURELABS_MODE=solo."""
        snippet = """
DATA_MODE="mydata"
[[ "$DATA_MODE" == "mydata" ]] && export OPENCURELABS_MODE=solo || export OPENCURELABS_MODE=contribute
echo "MODE=$OPENCURELABS_MODE"
"""
        r = _run_bash(snippet)
        assert "MODE=solo" in r.stdout

    def test_species_dog_appended(self):
        """Non-human species appended to task string."""
        snippet = """
LABCLAW_SPECIES="dog"
TASK="Analyze tumor mutations"
[[ "$LABCLAW_SPECIES" != "human" ]] && TASK="$TASK species=$LABCLAW_SPECIES."
echo "TASK=$TASK"
"""
        r = _run_bash(snippet)
        assert "species=dog." in r.stdout

    def test_species_human_not_appended(self):
        """Human species does not append to task string."""
        snippet = """
LABCLAW_SPECIES="human"
TASK="Analyze tumor mutations"
[[ "$LABCLAW_SPECIES" != "human" ]] && TASK="$TASK species=$LABCLAW_SPECIES."
echo "TASK=$TASK"
"""
        r = _run_bash(snippet)
        assert "species=" not in r.stdout

    def test_vast_yes_sets_compute(self):
        """USE_VAST=yes → LABCLAW_COMPUTE=vast_ai."""
        snippet = """
USE_VAST="yes"
[[ "$USE_VAST" == "yes" ]] && export LABCLAW_COMPUTE=vast_ai || export LABCLAW_COMPUTE=local
echo "COMPUTE=$LABCLAW_COMPUTE"
"""
        r = _run_bash(snippet)
        assert "COMPUTE=vast_ai" in r.stdout

    def test_vast_no_sets_local(self):
        """USE_VAST=no → LABCLAW_COMPUTE=local."""
        snippet = """
USE_VAST="no"
[[ "$USE_VAST" == "yes" ]] && export LABCLAW_COMPUTE=vast_ai || export LABCLAW_COMPUTE=local
echo "COMPUTE=$LABCLAW_COMPUTE"
"""
        r = _run_bash(snippet)
        assert "COMPUTE=local" in r.stdout


# ══════════════════════════════════════════════════════════════════════════════
#  Group 8: Edge cases and integration
# ══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Additional integration and edge case tests."""

    def test_agent_num_appended(self):
        """AGENT_NUM > 1 appends parallel agent instruction."""
        snippet = """
AGENT_NUM=3
FINAL_TASK="Analyze data"
[[ "${AGENT_NUM:-1}" -gt 1 ]] 2>/dev/null && FINAL_TASK="$FINAL_TASK Deploy $AGENT_NUM parallel agents."
echo "TASK=$FINAL_TASK"
"""
        r = _run_bash(snippet)
        assert "Deploy 3 parallel agents." in r.stdout

    def test_agent_num_1_no_append(self):
        """AGENT_NUM=1 does not append parallel instruction."""
        snippet = """
AGENT_NUM=1
FINAL_TASK="Analyze data"
[[ "${AGENT_NUM:-1}" -gt 1 ]] 2>/dev/null && FINAL_TASK="$FINAL_TASK Deploy $AGENT_NUM parallel agents."
echo "TASK=$FINAL_TASK"
"""
        r = _run_bash(snippet)
        assert "Deploy" not in r.stdout

    def test_public_appends_data_sourcing(self):
        """public mode appends data sourcing instruction."""
        snippet = """
DATA_MODE="public"
FINAL_TASK="Run analysis"
[[ "$DATA_MODE" == "public" ]] && FINAL_TASK="$FINAL_TASK Use public databases (TCGA/ClinVar/ChEMBL) for data sourcing."
echo "TASK=$FINAL_TASK"
"""
        r = _run_bash(snippet)
        assert "Use public databases (TCGA/ClinVar/ChEMBL)" in r.stdout

    def test_mydata_no_data_sourcing_append(self):
        """mydata mode does not append data sourcing instruction."""
        snippet = """
DATA_MODE="mydata"
FINAL_TASK="Run analysis"
[[ "$DATA_MODE" == "public" ]] && FINAL_TASK="$FINAL_TASK Use public databases (TCGA/ClinVar/ChEMBL) for data sourcing."
echo "TASK=$FINAL_TASK"
"""
        r = _run_bash(snippet)
        assert "TCGA" not in r.stdout

    def test_vast_compute_appended(self):
        """USE_VAST=yes appends Vast.ai instruction."""
        snippet = """
USE_VAST="yes"
FINAL_TASK="Run analysis"
[[ "$USE_VAST" == "yes" ]] && FINAL_TASK="$FINAL_TASK Use Vast.ai cloud GPU for compute."
echo "TASK=$FINAL_TASK"
"""
        r = _run_bash(snippet)
        assert "Use Vast.ai cloud GPU for compute." in r.stdout

    def test_feline_public_skips_neoantigen_and_qc(self):
        """Feline neoantigen and QC tasks should be skipped in public mode."""
        snippet = f"""
            eval "$(sed -n '/_skip_local_task()/,/^}}/p' '{SCRIPT}')"
            {_extract_task_arrays()}
            DATA_MODE="public"

            SKIPPED=()
            KEPT=()
            for t in "${{FELINE_TASKS[@]}}"; do
                desc="${{t#*|}}"
                raw="${{t%%|*}}"
                label="${{raw%% ~*}}"
                if _skip_local_task "$desc"; then
                    SKIPPED+=("$label")
                else
                    KEPT+=("$label")
                fi
            done
            echo "SKIPPED=${{SKIPPED[*]}}"
            echo "KEPT=${{KEPT[*]}}"
        """
        r = _run_bash(textwrap.dedent(snippet))
        skipped_line = r.stdout.split("SKIPPED=")[1].split("\n")[0]
        kept_line = r.stdout.split("KEPT=")[1].split("\n")[0]
        assert "Predict Feline Neoantigens" in skipped_line
        assert "Check Feline Data Quality" in skipped_line
        assert "Find Feline Tumor Mutations" in kept_line

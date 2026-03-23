# Testing Guide — First Testers

Welcome, and thank you for helping test OpenCure Labs. This guide walks you
through a first session so you can verify the platform works and report any
issues you hit.

---

## Prerequisites

- **OS:** Ubuntu 22.04+ (or Debian 12+). WSL2 works.
- **RAM:** 8 GB minimum, 16 GB recommended.
- **Disk:** ~5 GB free.
- **API keys:** At minimum you need a free **Gemini** key (`GENAI_API_KEY`).
  The Grok reviewer agent needs an **xAI** key (`XAI_API_KEY`) — get it at
  [console.x.ai](https://console.x.ai). `ANTHROPIC_API_KEY` is optional (the
  Claude Opus module is archived and not active in the current pipeline).

---

## Quick Setup

```bash
git clone https://github.com/OpenCureLabs/OpenCureLabs.git
cd OpenCureLabs
sudo bash scripts/setup.sh      # ~15–20 min first time
nano .env                        # paste your API keys
bash dashboard/lab.sh            # opens the Zellij control panel
```

If you want to skip the large model downloads (saves ~10 min), use:

```bash
sudo bash scripts/setup.sh --skip-models
```

Tests use mocks, so `--skip-models` is fine for a quick evaluation.

---

## What to Test

### 1. Setup script (`scripts/setup.sh`)

- [ ] Does it complete without errors?
- [ ] Does the verification summary at the end show all green checks?
- [ ] Are any warnings clear and actionable?

### 2. Run the test suite

```bash
source .venv/bin/activate
pytest -x
```

- [ ] Do all tests pass?
- [ ] Any import errors or missing dependencies?

### 3. Launch the dashboard

```bash
bash dashboard/lab.sh
```

- [ ] Does the Zellij panel open with all panes visible?
- [ ] Can you navigate between panes (Alt+arrow keys)?

### 4. Run a research batch

In the dashboard, the `MAIN` pane runs `run_research.sh`. Select a data source
and pipeline when prompted. For a quick test:

- Data source: **TCGA** or **synthetic**
- Pipeline: **variant_pathogenicity**
- Batch size: **1–3**

- [ ] Does the coordinator start and pick up the task?
- [ ] Do results appear in the database?
  ```bash
  source .venv/bin/activate
  python3 -c "
  import psycopg2
  conn = psycopg2.connect('postgresql://localhost:5433/opencurelabs')
  cur = conn.cursor()
  cur.execute('SELECT COUNT(*) FROM experiment_results')
  print(f'Results in DB: {cur.fetchone()[0]}')
  "
  ```

### 5. Solo mode (your own data)

If you have a VCF, FASTA, PDB, or SDF file:

```bash
bash scripts/solo_run.sh path/to/your/file
```

- [ ] Does it detect the file type correctly?
- [ ] Does it produce a PDF report in `reports/`?

### 6. Reviewer sweep

If you have `XAI_API_KEY` set:

```bash
source .venv/bin/activate
python3 reviewer/sweep.py --once
```

- [ ] Does it find unreviewed results and generate a critique?

---

## How to Report Issues

Open a GitHub issue at
[github.com/OpenCureLabs/OpenCureLabs/issues](https://github.com/OpenCureLabs/OpenCureLabs/issues)
with:

1. **What you tried** — copy the exact command.
2. **What happened** — paste the error output.
3. **Your environment** — OS, Python version, RAM, GPU (if any).
4. **setup.sh output** — if setup failed, paste the last 30 lines.

Use the label `tester-feedback` if available.

---

## Known Limitations

- The coordinator requires a **Gemini API key** (`GENAI_API_KEY`). Without it,
  `nat run` will fail with an auth error.
- Model downloads (pyensembl, MHCflurry) need a stable internet connection and
  ~1.5 GB of disk space. Use `--skip-models` to defer these.
- GPU pipelines (structure prediction, molecular docking) fall back to CPU if no
  CUDA device is available — expect slower results in that case.
- The platform is designed for Ubuntu/Debian. macOS and other distros may work
  but are not tested yet.

---

## After Testing

If everything worked, let us know! A quick "it works on my machine" comment is
incredibly valuable at this stage.

If you're interested in contributing code or pipelines, see
[CONTRIBUTING.md](CONTRIBUTING.md).

---
---

# Developer Test Suite Reference

This section documents the automated test suite for contributors and CI. Use it
to understand what's covered, how tests are organized, and how to add new ones.

---

## Running Tests

```bash
source .venv/bin/activate

# Full suite
pytest

# Quick summary
pytest -q

# Stop on first failure
pytest -x

# Single file
pytest tests/test_skills.py -v

# Single test
pytest tests/test_run_research.py::TestSkipLocalTask::test_neoantigen_public_skips

# With coverage
pytest --cov=packages/agentiq_labclaw --cov-report=term-missing

# Skip GPU-dependent tests
pytest -m "not gpu"
```

**Current status:** 262 tests — 262 passed, 13 skipped, 1 xfailed, 0 failures.

---

## Configuration

| File | Purpose |
|------|---------|
| `pytest.ini` | Test discovery, markers (`gpu`), asyncio mode, default args |
| `pyproject.toml` | Coverage target (`packages/agentiq_labclaw`) |
| `tests/conftest.py` | Shared fixtures — adds `agentiq_labclaw` to `sys.path` |

---

## Test Files Overview

| File | Tests | Category | What It Covers |
|------|-------|----------|----------------|
| `test_cli.py` | 14 | Unit | `.env` key read/write, compute mode, Vast.ai headers, CLI args |
| `test_connectors.py` | 9 | Unit | TCGA, ChEMBL, ClinVar data connectors (mocked HTTP) |
| `test_dashboard.py` | 15 | Integration | FastAPI endpoints, CORS, health check, query helpers |
| `test_db.py` | 12 | Unit | Agent runs, pipeline runs, critique log, experiment results, indexes |
| `test_e2e.py` | 20 | End-to-end | Skill registry, NAT imports, guardrails, publishers, full pipeline |
| `test_guardrails_edge.py` | 17 | Unit | Safety check edge cases, novelty filter, output validator |
| `test_hierarchical.py` | 10 | Unit | Specialist agent config, YAML structure, domain prompts |
| `test_load_connectors.py` | 17 | Unit | HTTP 429 retry, exponential backoff, concurrent requests |
| `test_neoantigen.py` | 38 | Unit | HLA alleles, VCF parsing, peptide windows, codon mutation |
| `test_neoantigen_canine.py` | 11 | Unit | CanFam3.1 species config, DLA/FLA alleles, vet dispatch |
| `test_orchestrator.py` | 6 | Integration | Config loading, post-execute validation/review/safety/publish |
| `test_reviewers.py` | 3 | Unit | Claude and Grok reviewer wrappers |
| `test_run_research.py` | 49 | Scenario | Shell function filtering, task catalog, dispatch loops, env vars |
| `test_security.py` | 21 | Unit | Security scanner grades, findings, reports, baselines |
| `test_skills.py` | 28 | Unit | Structure prediction, docking, QSAR, variant analysis, QC, PDF |
| `test_vast_dispatcher.py` | 10 | Unit | Vast.ai instance lifecycle, offers, dispatch |

---

## Test Patterns

### Python unit tests (most files)

Standard pytest with `monkeypatch`, `tmp_path`, `MagicMock`. External APIs are
mocked. Example pattern:

```python
def test_something(monkeypatch, tmp_path):
    monkeypatch.setattr("module.function", lambda: "mocked")
    result = my_function()
    assert result == expected
```

### Shell scenario tests (`test_run_research.py`)

Tests exercise shell functions from `dashboard/run_research.sh` by extracting
function definitions via `sed` and running them in isolated bash subprocesses.
No interactive TUI — only pure function logic.

```python
def _run_bash(snippet, *, env=None):
    return subprocess.run(["bash", "-c", snippet], capture_output=True, text=True)

def test_example():
    snippet = f'''
        eval "$(sed -n '/_skip_local_task()/,/^}}/p' '{SCRIPT}')"
        DATA_MODE="public"
        _skip_local_task "Predict neoantigens" && echo SKIP || echo KEEP
    '''
    r = _run_bash(snippet)
    assert "SKIP" in r.stdout
```

Key techniques:
- `sed -n '/func_name()/,/^}/p'` extracts a function from the script
- `eval "$(...)"` defines the function in the test shell
- Task arrays are extracted the same way
- No mocking of `gum` or `nat` — tests target pure logic, not TUI

### Integration tests (`test_dashboard.py`, `test_e2e.py`)

Use `fastapi.testclient.TestClient` for API tests. DB connections are mocked
with `MagicMock` patching `psycopg2.connect`.

### Async tests

`pytest-asyncio` with `asyncio_mode = auto` in `pytest.ini`. Async test
functions are detected automatically.

---

## Detailed Test Inventory

### test_cli.py — CLI & Environment

| Class | Tests | What |
|-------|-------|------|
| `TestReadEnvKey` | 6 | Read keys from `.env` — existing, missing, comments, quotes |
| `TestSetEnvKey` | 3 | Write keys — create, update, append |
| `TestReadEnvComputeMode` | 2 | Compute mode detection (local/vast) |
| `TestVastHeaders` | 2 | API header generation, missing key handling |
| `TestInstanceListing` | 2 | Vast.ai instance listing and filtering |

### test_connectors.py — Data Connectors

| Class | Tests | What |
|-------|-------|------|
| `TestTCGAConnector` | 3 | TCGA case queries, GEO metadata, file downloads |
| `TestChEMBLConnector` | 3 | Compound search, bioactivities, target info |
| `TestClinVarConnector` | 3 | Variant lookup, gene search, OMIM lookup |

### test_dashboard.py — Dashboard API

| Class | Tests | What |
|-------|-------|------|
| `TestHealthEndpoint` | 2 | Health check — DB up/down |
| `TestAPIEndpoints` | 7 | Stats, findings, runs, critiques, sources, limit cap |
| `TestDashboardHTML` | 1 | HTML page rendering |
| `TestCORS` | 1 | CORS headers present |
| `TestQueryHelpers` | 3 | Table existence, empty table stats |

### test_db.py — Database Layer

| Class | Tests | What |
|-------|-------|------|
| `TestAgentRuns` | 3 | Start, complete, not-found agent runs |
| `TestPipelineRuns` | 2 | Start, complete pipeline runs |
| `TestCritiqueLog` | 1 | Log and retrieve critiques |
| `TestExperimentResults` | 3 | Store result, novelty detection (new/existing) |
| `TestDiscoveredSources` | 3 | Register, validate, list sources |
| `TestIndexes` | 1 | Verify all performance indexes |

### test_e2e.py — End-to-End Integration

| Class | Tests | What |
|-------|-------|------|
| `TestSkillRegistry` | 2 | All 9 skills registered with schemas |
| `TestNATPluginImports` | 2 | Specialist module and orchestrator imports |
| `TestGuardrailsIntegration` | 4 | Output validation, safety blocks/pass |
| `TestPublishersIntegration` | 1 | PDF publisher generates valid PDF |
| `TestReviewersIntegration` | 3 | Claude/Grok reviewer/researcher init |
| `TestDBInterfaces` | 4 | Critique, agent runs, results, pipeline interfaces |
| `TestFullPipeline` | 1 | Neoantigen skill → orchestrator → publish |

### test_guardrails_edge.py — Guardrail Edge Cases

| Class | Tests | What |
|-------|-------|------|
| `TestSafetyCheck` | 10 | Confidence thresholds (0, negative, at-boundary), critique gates |
| `TestNoveltyFilter` | 3 | Novel, duplicate, empty results |
| `TestOutputValidator` | 4 | Schema pass/fail, optional fields, roundtrip |

### test_load_connectors.py — HTTP Retry & Resilience

| Class | Tests | What |
|-------|-------|------|
| `TestRetryOn429` | 2 | 429 retry then success / exhaustion |
| `TestRetryOnServerErrors` | 4 | 500/502/503/504 handling (parametrized) |
| `TestRetryAfterHeader` | 1 | Respects Retry-After header |
| `TestExponentialBackoff` | 1 | Delay increases exponentially |
| `TestConcurrentRequests` | 2 | Multi-threaded success and retries |
| `TestConnectorIntegration` | 3 | ChEMBL/ClinVar/TCGA retry behavior |

### test_neoantigen.py — Neoantigen Pipeline

| Class | Tests | What |
|-------|-------|------|
| `TestNormalizeAllele` | 7 | HLA prefix, case, underscore, whitespace |
| `TestGeneratePeptideWindows` | 9 | Missense, frameshift, boundaries, lengths |
| `TestGenomicToCodingOffset` | 6 | Forward/reverse strand, edge cases |
| `TestMutateCodon` | 5 | SNV, reverse complement, stop codons |
| `TestNeoantigenOutput` | 4 | Output/input schema validation |
| `TestConstants` | 2 | IC50 thresholds, peptide length tuple |

### test_neoantigen_canine.py — Veterinary Genomics

| Tests | What |
|-------|------|
| 11 | Species registry, canine VCF, DLA/FLA alleles, MHC predictor, QC ref derivation, vet dispatch, canine e2e pipeline |

### test_orchestrator.py — Post-Execute Pipeline

| Class | Tests | What |
|-------|-------|------|
| `TestOrchestratorConfig` | 3 | YAML loading, guardrails, publishers |
| `TestPostExecuteValidation` | 1 | Valid output passes |
| `TestPostExecuteReviewer` | 2 | Grok critique + novelty review |
| `TestPostExecuteSafety` | 1 | Unsafe result blocked |
| `TestPostExecutePublishers` | 1 | PDF generation |

### test_run_research.py — Shell Scenario Tests

| Class | Tests | What |
|-------|-------|------|
| `TestSkipLocalTask` | 9 | `_skip_local_task()` — neoantigen, QC, data quality filtering by data mode |
| `TestTaskCatalog` | 5 | Task array integrity — pipes, tildes, uniqueness, non-empty |
| `TestParameterize` | 6 | `parameterize_task.py` — skill mapping, sequence resolution, data mode |
| `TestRunAllDispatch` | 6 | Run All loop — skip/dispatch counts, domain-specific behavior |
| `TestGenesisMode` | 5 | Genesis ALL_TASKS — 5-domain construction, filtering, totals |
| `TestDependencies` | 6 | Missing gum/python/vast, syntax validation, .env handling |
| `TestEnvironment` | 6 | DATA_MODE → OPENCURELABS_MODE, species, LABCLAW_COMPUTE |
| `TestEdgeCases` | 6 | Agent count, data sourcing, Vast.ai compute, feline filtering |

### test_security.py — Security Scanner

| Class | Tests | What |
|-------|-------|------|
| `TestComputeGrade` | 8 | Grade computation (A+ through F) |
| `TestClassifyFindings` | 5 | Tier classification (ruff/bandit/secrets/deps) |
| `TestReportGeneration` | 3 | Report generation (clean, with findings, JSON) |
| `TestBaselineComparison` | 3 | Baseline save/compare, grade changes, resolved findings |
| `TestAcceptedRisks` | 2 | CVE filtering, empty profile |
| `TestDataClasses` | 4 | Finding/ScanResult defaults and utilities |

### test_skills.py — Scientific Skills

| Class | Tests | What |
|-------|-------|------|
| `TestStructurePrediction` | 3 | ESMFold, AlphaFold lookup, input defaults |
| `TestMolecularDocking` | 3 | Vina output parsing, input/output schemas |
| `TestQSAR` | 4 | RDKit descriptors, invalid SMILES, train/predict |
| `TestVariantPathogenicity` | 7 | Variant parsing, pathogenicity classification, full run |
| `TestSequencingQC` | 2 | fastp QC run, input schema |
| `TestReportGenerator` | 2 | PDF generation, input schema |

### test_vast_dispatcher.py — Cloud Compute

| Class | Tests | What |
|-------|-------|------|
| `TestVastInstance` | 6 | Info, ready check, timeout, destroy |
| `TestFindCheapestOffer` | 3 | Cheapest offer, no offers, GPU filter |
| `TestCreateInstance` | 2 | Create success, failure |
| `TestDispatch` | 1 | Missing API key |

---

## Adding New Tests

1. **Create a file** in `tests/` named `test_<module>.py`.
2. **Group related tests** in classes prefixed with `Test`.
3. **Mock external calls** — never hit real APIs, databases, or GPUs in tests.
4. **Use existing patterns:**
   - Python logic → `monkeypatch` + `MagicMock`
   - Shell logic → `subprocess.run(["bash", "-c", snippet])`
   - API endpoints → `TestClient(app)`
   - Database → mock `psycopg2.connect`
5. **Mark GPU tests** with `@pytest.mark.gpu` so CI can skip them.
6. **Run before committing:** `pytest -x` — the pre-commit hook runs the
   security scanner but not tests, so verify locally.

---

## CI

Tests run in GitHub Actions on every push and PR. The workflow is at
`.github/workflows/ci.yml`. It installs dependencies, runs `pytest`, and fails
the build on any test failure. The security scanner also runs as a pre-commit
hook (see `security/` for details).

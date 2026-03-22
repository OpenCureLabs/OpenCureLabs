# Contributing to OpenCure Labs

## Welcome

OpenCure Labs is an autonomous AI-for-Science platform that runs computational biology pipelines — genomics analysis, neoantigen prediction, molecular docking, QSAR modeling — through multi-agent orchestration. It is open science infrastructure, not a typical software project.

Contributions here have scientific impact. Every pipeline improvement, every new data connector, every bug fix makes personalized medicine tools more accessible to researchers who need them.

This project was inspired by Paul Conyngham's work building a personalized cancer vaccine for his dog Rosie — a remarkable story of one engineer using AI and open data to do something oncology labs hadn't done for his case. OpenCure Labs is building the open, repeatable, automated version of that pipeline so **any researcher, anywhere** can run it. See [README.md](README.md) for the full project context.

---

## Ways to Contribute

There are many entry points, whether you're a biologist, engineer, or someone who wants to help open science move faster:

| Contribution Type | Who It's For | Effort |
|---|---|---|
| **Run a pipeline** | Anyone | Low — clone, run, report |
| **Implement a skill** | Python developers | Medium — build a scientific pipeline module |
| **Add a data connector** | Backend engineers | Medium — integrate a scientific database |
| **Improve scientific accuracy** | Domain experts | Variable — review logic, open issues |
| **Write tests** | Developers | Low–Medium — synthetic data + assertions |
| **Documentation** | Anyone | Low — tutorials, examples, guides |
| **Report bugs** | Anyone | Low — issue with reproduction steps |

### Run a pipeline

The fastest way to contribute is to clone the repo, run the neoantigen pipeline on the synthetic test data, and report what worked and what didn't. Real feedback from real environments is invaluable.

```bash
git clone https://github.com/OpenCureLabs/OpenCureLabs.git
cd OpenCureLabs
python3 -m venv .venv && source .venv/bin/activate
pip install -e packages/agentiq_labclaw
python tests/test_neoantigen.py
```

Open an issue with your output, environment details, and any errors.

### Implement a skill

Pick an unimplemented skill from the [LABCLAW.md](LABCLAW.md) status table (look for "Scaffold (pipeline logic TODO)") and build it. See [How to Implement a New Skill](#how-to-implement-a-new-skill) below.

### Add a data connector

Write a connector for a scientific database we don't cover yet — OpenTargets, PubChem, Ensembl REST API, UniProt, etc. See [How to Add a Data Connector](#how-to-add-a-data-connector) below.

### Improve scientific accuracy

If you're a domain expert — oncologist, geneticist, computational chemist, pharmacologist — review the pipeline logic in `packages/agentiq_labclaw/agentiq_labclaw/skills/` and open issues for anything that is scientifically incorrect, oversimplified, or missing important edge cases. This is one of the most valuable contributions possible.

### Write tests

Add test cases with synthetic data for existing skills. Every skill should have at minimum one positive and one negative control test. See existing tests in `tests/` for the pattern.

### Documentation

Improve setup guides, add worked examples, write tutorials showing how to use OpenCure Labs for specific research questions. Good docs lower the barrier for every contributor after you.

### Report bugs

Open a GitHub issue with:
- What you were trying to do
- What happened instead
- Your environment (OS, Python version, GPU if applicable)
- Steps to reproduce

---

## Development Setup

Assumes Ubuntu 22.04+ or WSL2.

```bash
# Clone
git clone https://github.com/OpenCureLabs/OpenCureLabs.git
cd OpenCureLabs

# Python environment
python3 -m venv .venv
source .venv/bin/activate
pip install -e packages/agentiq_labclaw

# Install scientific dependencies (for neoantigen pipeline)
pip install pysam biopython pyensembl mhcflurry
pyensembl install --release 110 --species human
mhcflurry-downloads fetch models_class1 models_class1_pan models_class1_presentation

# PostgreSQL (optional — needed for full pipeline runs with DB logging)
# Note: OpenCure Labs uses port 5433
sudo apt install postgresql -y
sudo service postgresql start
sudo -u postgres psql -p 5433 -c "CREATE DATABASE opencurelabs;"
sudo -u postgres psql -p 5433 -d opencurelabs -f db/schema.sql

# Environment variables
cp .env.example .env
# Edit .env — minimum required: XAI_API_KEY (ANTHROPIC_API_KEY is optional)

# Verify your setup — run the neoantigen test
python tests/test_neoantigen.py
```

Expected output: 6 strong binders from KRAS G12V, 2 weak binders from TP53 R175H, all tests pass.

---

## How to Implement a New Skill

Skills are the core scientific modules in OpenCure Labs. Each one wraps a computational biology pipeline behind a standard interface so the coordinator can invoke it, guardrails can validate it, and reviewers can critique it.

### Where it goes

```
packages/agentiq_labclaw/agentiq_labclaw/skills/your_skill.py
```

### Required structure

Every skill must:

1. **Inherit from `LabClawSkill`** and use the `@labclaw_skill` decorator
2. **Define Pydantic input/output schemas** — typed, validated, documented
3. **Implement the `run()` method** — the actual pipeline logic
4. **Declare a compute target** — `"local"` (runs on local GPU) or `"vast_ai"` (burst to cloud)
5. **Set `critique_required`** appropriately in the output

### Template

```python
"""Short description of what this skill does."""

import logging
from pydantic import BaseModel
from agentiq_labclaw.base import LabClawSkill, labclaw_skill

logger = logging.getLogger("labclaw.skills.your_skill")


class YourSkillInput(BaseModel):
    """Input schema — all fields must be typed and documented."""
    sample_id: str
    # ... your input fields


class YourSkillOutput(BaseModel):
    """Output schema — guardrails validate against this."""
    sample_id: str
    results: list[dict]
    confidence_score: float
    novel: bool
    critique_required: bool


@labclaw_skill(
    name="your_skill_name",
    description="Human-readable description for the coordinator",
    input_schema=YourSkillInput,
    output_schema=YourSkillOutput,
    compute="local",       # "local" or "vast_ai"
    gpu_required=False,    # True if the pipeline needs GPU
)
class YourSkill(LabClawSkill):
    """Docstring explaining the pipeline steps."""

    def run(self, input_data: YourSkillInput) -> YourSkillOutput:
        # Your pipeline logic here
        ...
```

### Why Pydantic schemas?

Schemas serve three purposes:
- **Guardrails** validate every skill output against its declared schema before publishing
- **The coordinator** uses schemas to understand what data to pass between skills
- **Contributors** can read the schema to understand exactly what a skill expects and returns

### When to set `critique_required=True`

Set it to `True` when the output contains a novel scientific finding that should be reviewed by Grok before publication. If the output is purely informational or replicates known results, set it to `False`.

### Writing a test

Create `tests/test_your_skill.py` with synthetic data:

```python
from agentiq_labclaw.skills.your_skill import YourSkill, YourSkillInput

def test_full_pipeline():
    inp = YourSkillInput(sample_id="TEST_001", ...)
    skill = YourSkill()
    result = skill.run(inp)

    assert result.sample_id == "TEST_001"
    assert isinstance(result.confidence_score, float)
    # Add domain-specific assertions
    print("PASS")

def test_negative_control():
    """Test with input that should produce no results."""
    inp = YourSkillInput(sample_id="NEG_CTRL", ...)
    skill = YourSkill()
    result = skill.run(inp)

    assert len(result.results) == 0
    assert result.novel is False
    print("PASS: negative control")
```

### Register in coordinator YAML

Add your skill to `coordinator/labclaw_workflow.yaml`:

```yaml
functions:
  your_skill_name:
    _type: labclaw_skill
    skill_name: your_skill_name

workflow:
  tool_names:
    - your_skill_name   # add to the list
```

### Reference implementation

See [`packages/agentiq_labclaw/agentiq_labclaw/skills/neoantigen.py`](packages/agentiq_labclaw/agentiq_labclaw/skills/neoantigen.py) — the fully implemented neoantigen prediction pipeline. It demonstrates VCF parsing, transcript lookup, peptide generation, MHC binding prediction, batch optimization, DB logging, and structured output.

---

## How to Add a Data Connector

Connectors provide access to external scientific databases. They live in:

```
packages/agentiq_labclaw/agentiq_labclaw/connectors/your_connector.py
```

### Required interface

Every connector should implement these methods:

```python
class YourConnector:
    """Connector for [Database Name]."""

    BASE_URL = "https://api.example.org"

    def fetch(self, query: str, **kwargs) -> list[dict]:
        """Fetch records matching a query. Returns normalized dicts."""
        ...

    def validate(self, record: dict) -> bool:
        """Validate that a fetched record has required fields."""
        ...

    def normalize(self, raw: dict) -> dict:
        """Normalize raw API response to OpenCure Labs internal format."""
        ...
```

### Guidelines

- **Rate limiting**: Respect API rate limits. Use `time.sleep()` or exponential backoff — do not hammer scientific APIs.
- **Pagination**: Handle paginated responses fully. Don't silently drop results after the first page.
- **Error handling**: Return empty results on transient failures, raise on configuration errors. Log everything.
- **No API keys in code**: Read credentials from environment variables or `.env`.

### Reference implementations

See [`packages/agentiq_labclaw/agentiq_labclaw/connectors/chembl.py`](packages/agentiq_labclaw/agentiq_labclaw/connectors/chembl.py) and [`packages/agentiq_labclaw/agentiq_labclaw/connectors/clinvar.py`](packages/agentiq_labclaw/agentiq_labclaw/connectors/clinvar.py) for the pattern.

---

## Scientific Accuracy Standards

OpenCure Labs produces results that could inform real research decisions. We take this seriously.

- **Cite your methods.** All pipeline logic must reference the underlying algorithm, paper, or tool. If you implement a binding prediction step, cite which predictor and which version.
- **Calibrate confidence scores.** Document what the score means, what range it operates in, and how it was calibrated. A number without context is meaningless.
- **Literature checks on novel results.** Any result marked `novel=True` must have a literature check performed by the Grok reviewer before publication. This is enforced by the guardrails layer.
- **No shortcuts that sacrifice validity.** Do not simplify pipeline steps in ways that produce scientifically misleading results, even if it makes the code easier to write.
- **Ask when uncertain.** If you are unsure about the biology, chemistry, or statistical methodology — open an issue and ask. Do not guess. The community includes domain experts who can help.
- **Negative controls are mandatory.** Every skill test suite must include at minimum one negative control — an input that should produce no results, verifying the pipeline doesn't hallucinate findings.

---

## Commit and PR Guidelines

### Branch naming

```
feat/skill-name          # New skill or feature
fix/issue-description    # Bug fix
docs/section-name        # Documentation
test/test-description    # New tests
```

### Commit messages

We use [Conventional Commits](https://www.conventionalcommits.org/) and enforce them with [commitizen](https://commitizen-tools.github.io/commitizen/). A `commit-msg` hook validates every commit message — non-conforming commits are blocked.

```
feat: add structure prediction skill
fix: correct MHC binding threshold in neoantigen pipeline
docs: add worked example for variant pathogenicity
test: add synthetic VCF test for edge cases
chore: bump dependencies
refactor: extract peptide generation into helper
ci: add coverage threshold to CI
```

Allowed types: `feat`, `fix`, `docs`, `test`, `chore`, `refactor`, `ci`, `style`, `perf`, `build`, `revert`.

To bypass in an emergency: `git commit --no-verify` (use sparingly).

### Branch naming

Use a type prefix matching the commit type:

```
feat/skill-name          # New skill or feature
fix/issue-description    # Bug fix
docs/section-name        # Documentation
test/test-description    # New tests
chore/cleanup-name       # Maintenance
```

Link to issues when applicable: `feat/36-wiki-sync`, `fix/42-binding-threshold`.

### Pull request requirements

Every PR must include:

1. **Description** — what changed and why
2. **Test results** — paste the output of the relevant test suite
3. **LABCLAW.md update** — if you implemented or changed a skill, update the status table
4. **One thing per PR** — one skill, one connector, one fix. Keep PRs focused and reviewable.

---

## Code Style

- **Python 3.11+** — use modern syntax (type unions with `|`, match statements where appropriate)
- **Formatting**: `black packages/` — run before every commit
- **Type hints** required on all public functions and method signatures
- **Docstrings** required on all skill classes — explain the pipeline steps, inputs, and outputs
- **No hardcoded paths** — use configuration, environment variables, or `pathlib.Path` relative to project root
- **No hardcoded API keys** — ever, under any circumstances. Keys go in `.env`, read via `os.environ`

---

## Scientific Data and Privacy

- **Never commit real patient data** or clinical samples — not in code, tests, configs, or documentation
- **Test data must be synthetic** or from public datasets (TCGA accessions, GEO series, ChEMBL IDs)
- **All VCF files in `tests/`** must use synthetic mutations — see `tests/data/synthetic_somatic.vcf` for the pattern
- **Data connectors** may only connect to publicly available databases with open APIs
- **If in doubt**, ask before committing any data — patient privacy is non-negotiable

---

## Community and Communication

- **GitHub Issues** — bugs, feature requests, scientific questions, and discussion
- **Be respectful** — this project sits at the intersection of technology and medicine. Contributors come from very different backgrounds — computational biologists, ML engineers, clinical researchers, open science advocates. Assume good intent and explain context when it might not be obvious.
- **Credit** — all contributors are acknowledged. Significant contributions are listed in CONTRIBUTORS.md.

---

## Roadmap and Priorities

See the [Roadmap section in README.md](README.md#roadmap) for the full phased plan. Here's what is most needed right now:

| Priority | Skill / Component | What's Needed |
|---|---|---|
| **High** | Structure prediction | ESMFold integration — predict protein structures from sequence |
| **High** | Molecular docking | AutoDock Vina or Gnina — score ligand-receptor binding |
| **High** | QSAR | RDKit + scikit-learn — train and evaluate QSAR models |
| **High** | Variant pathogenicity | Real ClinVar/OMIM scoring logic — replace current scaffold |
| **Medium** | TCGA connector | Implement GDC API calls for real cohort data ingestion |
| **Medium** | First published result | End-to-end run on a public TCGA cohort, published as PDF report |
| **Lower** | PDF publisher | Proper report rendering with figures and tables |
| **Lower** | Vast.ai dispatcher | Cloud burst compute for heavy ML jobs |

Pick something from this list and open an issue to claim it — or propose something we haven't thought of.

---

## License

MIT — all contributions are made under the same license.

Note that scientific pipelines may depend on third-party tools with their own licensing requirements. For example, NetMHCpan requires an academic license, certain PDB-derived datasets have usage restrictions, and some ML model weights have non-commercial clauses. Contributors must ensure their implementations use compatible dependencies and document any license constraints in their skill's docstring.

---

## Getting Started — Right Now

If you've read this far and want to contribute but aren't sure where to start:

1. Clone the repo and run `python tests/test_neoantigen.py`
2. Read through [`neoantigen.py`](packages/agentiq_labclaw/agentiq_labclaw/skills/neoantigen.py) to understand how a skill works
3. Pick a scaffold skill from [LABCLAW.md](LABCLAW.md) and start building
4. Open an issue if you get stuck — we'd rather help you contribute than have you give up

### Contributing Results to the Global Dataset

When running in `contribute` mode (the default), your results are signed with an Ed25519 keypair and submitted to the ingest worker:

1. **First run** generates `~/.opencurelabs/signing_key` (Ed25519 keypair) and registers you as a contributor at `~/.opencurelabs/contributor_id`.
2. Each result is serialized as **canonical JSON** (sorted keys, compact separators), signed with your private key, and sent with `X-Signature-Ed25519` and `X-Contributor-Id` headers.
3. The ingest worker verifies your signature against your registered public key — invalid signatures are rejected.
4. Results land with `status: pending` and go through the **two-tier Grok review** before publication.

> **Backup `~/.opencurelabs/signing_key`** — if lost, you must re-register as a new contributor.

The goal is simple: **democratize personalized medicine infrastructure so any researcher, anywhere, can run the pipeline that helped Rosie** — and apply it to human cancer, rare diseases, and drug discovery. Every contribution moves that goal closer.

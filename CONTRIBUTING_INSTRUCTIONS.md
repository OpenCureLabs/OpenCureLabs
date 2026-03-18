# Agent Instructions — Create CONTRIBUTING.md

Read CLAUDE.md, README.md, and LABCLAW.md first.

Create /root/opencurelabs/CONTRIBUTING.md — a guide for researchers, developers,
and scientists who want to contribute to OpenCure Labs. This is the document that
turns GitHub visitors into actual contributors.

---

## Audience

Write for three distinct audiences — the document should serve all three:

1. **Computational biologists** — understand the science, may not know agents or Python packaging
2. **AI/ML engineers** — understand agents and Python, may not know genomics pipelines
3. **Open science enthusiasts** — want to contribute but need clear entry points

---

## CONTRIBUTING.md must include the following sections:

### 1. Welcome
- What OpenCure Labs is in 3 sentences
- Why contributions matter — this is open science infrastructure, not a typical OSS project
- Reference the Rosie story (Paul Conyngham's dog cancer vaccine) as the inspiration
  and explain that OpenCure Labs is building the open, repeatable, automated version of
  that pipeline so any researcher can use it
- Link to README.md for full context

### 2. Ways to Contribute
Cover all entry points clearly:

- **Run a pipeline** — clone the repo, run the neoantigen pipeline on synthetic data,
  report what worked and what didn't
- **Implement a skill** — pick an unimplemented skill from LABCLAW.md status table
  and build it following the LabClawSkill interface
- **Add a data connector** — write a new connector for a scientific database
  (OpenTargets, PubChem, Ensembl, etc.)
- **Improve scientific accuracy** — if you're a domain expert (oncologist, geneticist,
  chemist), review pipeline logic and open issues for scientific correctness
- **Write tests** — add test cases with synthetic data for existing skills
- **Documentation** — improve setup guides, add worked examples, write tutorials
- **Report bugs** — open a GitHub issue with environment details and reproduction steps

### 3. Development Setup
Step by step, assume Ubuntu 22.04+ or WSL2:

```bash
# Clone
git clone https://github.com/OpenCureLabs/XPCLabs.git
cd OpenCureLabs

# Python environment
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e packages/agentiq_labclaw

# PostgreSQL (optional, needed for full pipeline runs)
sudo apt install postgresql -y
sudo service postgresql start
sudo -u postgres psql -c "CREATE DATABASE opencurelabs;"

# Environment variables
cp .env.example .env
# Edit .env — minimum required: ANTHROPIC_API_KEY, XAI_API_KEY

# Run the neoantigen test to verify setup
python tests/test_neoantigen.py
```

### 4. How to Implement a New Skill
Detailed walkthrough of the LabClawSkill interface:
- Where the file goes (packages/agentiq_labclaw/agentiq_labclaw/skills/)
- The required class structure (inherit LabClawSkill, use @labclaw_skill decorator)
- Pydantic input/output schemas — explain why these are required
- The compute target declaration (local vs vast_ai)
- The critique_required flag and when to set it True
- How to write a synthetic data test
- How to register the skill in the coordinator YAML
- Example: point to neoantigen.py as the reference implementation

### 5. How to Add a Data Connector
- Where connectors live (packages/agentiq_labclaw/agentiq_labclaw/connectors/)
- Required interface — fetch, validate, normalize methods
- How to handle rate limiting and pagination
- How to register with the coordinator
- Point to chembl.py or clinvar.py as reference implementations

### 6. Scientific Accuracy Standards
This section is important — OpenCure Labs produces results that could inform
real research decisions. Be direct about the standards:

- All pipeline logic must cite the underlying method (paper, tool, algorithm)
- Confidence scores must be calibrated and documented
- Any result marked novel=True must have a literature check performed
- Do not implement shortcuts that sacrifice scientific validity for speed
- If you are uncertain about the biology, open an issue and ask — do not guess
- All skills must include at minimum one negative control in their test suite

### 7. Commit and PR Guidelines
- Branch naming: feat/skill-name, fix/issue-description, docs/section-name
- Commit messages follow conventional commits:
  feat: add structure prediction skill
  fix: correct MHC binding threshold in neoantigen pipeline
  docs: add worked example for variant pathogenicity
  test: add synthetic VCF test for edge cases
- All PRs must include:
  - Description of what changed and why
  - Test results (paste output of relevant test)
  - LABCLAW.md status table updated if applicable
- Keep PRs focused — one skill, one connector, one fix per PR

### 8. Code Style
- Python 3.11+
- Black for formatting: black packages/
- Type hints required on all public functions
- Docstrings required on all skill classes
- No hardcoded paths — use config or environment variables
- No hardcoded API keys — ever

### 9. Scientific Data and Privacy
- Never commit real patient data or clinical samples
- Test data must be synthetic or from public datasets (TCGA, GEO accessions)
- All example VCF files in tests/ must use synthetic mutations
- If contributing data connectors, only connect to publicly available databases

### 10. Community and Communication
- GitHub Issues for bugs, feature requests, and scientific questions
- Discord: [link to be added] — live agent logs stream here, community discussion
- Be respectful — this project sits at the intersection of technology and medicine,
  contributors come from very different backgrounds
- Credit — all contributors will be listed in CONTRIBUTORS.md

### 11. Roadmap and Priorities
Link to the roadmap section in README.md and highlight what is most needed right now:
- Structure prediction skill (ESMFold integration)
- Molecular docking skill (AutoDock Vina)
- QSAR skill (RDKit + scikit-learn)
- Variant pathogenicity real implementation
- Discord publisher wiring
- First real TCGA cohort run and published result

### 12. License
MIT — all contributions are made under the same license.
Note that scientific pipelines may depend on third-party tools with their own
licenses (NetMHCpan requires academic license, etc.) — contributors must ensure
their implementations are compatible.

---

## Formatting requirements

- Use clear headers and subheaders
- Code blocks for all commands and code examples
- Tables where appropriate (e.g. skill status, contribution types)
- Friendly but professional tone — this is open science, not a corporate OSS project
- End with a motivating closing statement connecting back to the mission:
  democratizing personalized medicine infrastructure so any researcher,
  anywhere, can run the Rosie pipeline

---

## After creating the file:
- Update the Table of Contents in README.md to add a link to CONTRIBUTING.md
- Add a "Contributing" badge or link near the top of README.md if appropriate
- Commit with message: "docs: add CONTRIBUTING.md — guide for researchers and developers"
- Push to GitHub

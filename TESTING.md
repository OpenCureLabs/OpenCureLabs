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

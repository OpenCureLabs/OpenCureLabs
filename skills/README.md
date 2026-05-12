# skills/ — Pointer Directory

> **The actual skill implementations do not live here.**

The scientific skill modules (`neoantigen_prediction`, `variant_pathogenicity`,
`molecular_docking`, `qsar`, `structure_prediction`, `sequencing_qc`,
`report_generator`, `grok_research`, `register_source`, …) are implemented in
the editable `agentiq_labclaw` package:

> [packages/agentiq_labclaw/agentiq_labclaw/skills/](../packages/agentiq_labclaw/agentiq_labclaw/skills/)

This top-level `skills/` directory is preserved only for two reasons:

1. **Architecture diagrams** — `README.md`, `LABCLAW.md`, and
   `docs/ARCHITECTURE.md` refer to a logical "skills layer". The directory name
   is kept so the on-disk layout matches the conceptual layout.
2. **Future extension** — third-party skill packages can be dropped in here and
   loaded via the NeMo plugin registration in
   [`packages/agentiq_labclaw/agentiq_labclaw/nat_plugin.py`](../packages/agentiq_labclaw/agentiq_labclaw/nat_plugin.py).

### To add a new skill

Add it to the package, not to this directory:

```bash
packages/agentiq_labclaw/agentiq_labclaw/skills/your_skill.py
```

Then register it by importing the module in `nat_plugin.py` (eager import — the
`@labclaw_skill` decorator only fires on import). See `CONTRIBUTING.md` →
"Adding a Skill" for the full walk-through.

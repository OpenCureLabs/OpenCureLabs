import importlib as _importlib

__all__ = [
    "MolecularDockingSkill",
    "NeoantigenSkill",
    "QSARSkill",
    "RegisterSourceSkill",
    "ReportGeneratorSkill",
    "SequencingQCSkill",
    "StructurePredictionSkill",
    "VariantPathogenicitySkill",
]

_SKILL_MODULES = {
    "MolecularDockingSkill": "agentiq_labclaw.skills.docking",
    "NeoantigenSkill": "agentiq_labclaw.skills.neoantigen",
    "QSARSkill": "agentiq_labclaw.skills.qsar",
    "RegisterSourceSkill": "agentiq_labclaw.skills.register_source",
    "ReportGeneratorSkill": "agentiq_labclaw.skills.report_generator",
    "SequencingQCSkill": "agentiq_labclaw.skills.sequencing_qc",
    "StructurePredictionSkill": "agentiq_labclaw.skills.structure",
    "VariantPathogenicitySkill": "agentiq_labclaw.skills.variant_pathogenicity",
}


def __getattr__(name: str):
    if name in _SKILL_MODULES:
        mod = _importlib.import_module(_SKILL_MODULES[name])
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

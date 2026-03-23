"""
Species configuration registry for multi-species genomic analysis.

Provides SpeciesConfig dataclass with genome, MHC, and Ensembl parameters
for human, canine, and feline pipelines.  All skill inputs default to
species="human" — no breaking changes to existing human pipelines.

Usage:
    from agentiq_labclaw.species import get_species, HUMAN, DOG, CAT

    cfg = get_species("dog")
    ensembl = EnsemblRelease(cfg.ensembl_release, species=cfg.ensembl_species)
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SpeciesConfig:
    """Immutable configuration for a supported analysis species."""

    # Human-readable name used in API inputs (e.g. "human", "dog", "cat")
    name: str

    # Latin binomial — used in OMIA and Ensembl VEP species routing
    latin: str

    # pyensembl species string — passed to EnsemblRelease(release, species=...)
    ensembl_species: str

    # Ensembl release to use for this species' annotations
    # Human: 110 (GRCh38), Dog/Cat: 112 (CanFam3.1 / felCat9)
    ensembl_release: int

    # Reference genome assembly identifier
    reference_genome: str

    # MHC allele prefix for this species' immune system
    # Human: "HLA", Dog: "DLA", Cat: "FLA"
    mhc_prefix: str

    # Class I MHC gene names for this species
    mhc_class1_genes: tuple[str, ...] = field(default_factory=tuple)

    # Chromosome prefix convention ("" for Ensembl, "chr" for UCSC)
    chromosome_prefix: str = "chr"

    # Preferred MHC binding predictor: "mhcflurry" (human-only) or "netmhcpan" (cross-species)
    supported_mhc_predictor: str = "mhcflurry"

    # NCBI taxonomy ID — used for UniProt organism filtering in structure prediction
    ncbi_taxon_id: int = 9606

    # Ensembl VEP species string (e.g. "homo_sapiens", "canis_lupus_familiaris")
    vep_species: str = ""

    def __post_init__(self) -> None:
        # Default vep_species to ensembl_species if not provided
        if not self.vep_species:
            object.__setattr__(self, "vep_species", self.ensembl_species)


# ---------------------------------------------------------------------------
# Pre-built species configs
# ---------------------------------------------------------------------------

HUMAN = SpeciesConfig(
    name="human",
    latin="Homo sapiens",
    ensembl_species="homo_sapiens",
    ensembl_release=110,
    reference_genome="GRCh38",
    mhc_prefix="HLA",
    mhc_class1_genes=("HLA-A", "HLA-B", "HLA-C"),
    chromosome_prefix="chr",
    supported_mhc_predictor="mhcflurry",
    ncbi_taxon_id=9606,
    vep_species="homo_sapiens",
)

DOG = SpeciesConfig(
    name="dog",
    latin="Canis lupus familiaris",
    ensembl_species="canis_familiaris",
    ensembl_release=111,
    reference_genome="CanFam3.1",
    mhc_prefix="DLA",
    mhc_class1_genes=("DLA-88", "DLA-12", "DLA-64"),
    chromosome_prefix="chr",
    supported_mhc_predictor="netmhcpan",
    ncbi_taxon_id=9615,
    vep_species="canis_lupus_familiaris",
)

CAT = SpeciesConfig(
    name="cat",
    latin="Felis catus",
    ensembl_species="felis_catus",
    ensembl_release=111,
    reference_genome="felCat9",
    mhc_prefix="FLA",
    mhc_class1_genes=("FLA-K", "FLA-1600"),
    chromosome_prefix="chr",
    supported_mhc_predictor="netmhcpan",
    ncbi_taxon_id=9685,
    vep_species="felis_catus",
)


# ---------------------------------------------------------------------------
# Registry and lookup
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, SpeciesConfig] = {
    # Primary names
    "human": HUMAN,
    "dog": DOG,
    "cat": CAT,
    # Common synonyms
    "homo_sapiens": HUMAN,
    "canis_familiaris": DOG,
    "canis_lupus_familiaris": DOG,
    "canine": DOG,
    "felis_catus": CAT,
    "feline": CAT,
}


def get_species(name: str) -> SpeciesConfig:
    """Look up a SpeciesConfig by name or synonym.

    Args:
        name: Case-insensitive species name.  Accepts common names ("dog", "cat",
              "human"), synonyms ("canine", "feline"), or Ensembl species strings.

    Returns:
        SpeciesConfig for the requested species.

    Raises:
        ValueError: If the species is not in the registry.

    Examples:
        >>> get_species("dog")
        SpeciesConfig(name='dog', ...)
        >>> get_species("canine")
        SpeciesConfig(name='dog', ...)
    """
    key = name.strip().lower()
    config = _REGISTRY.get(key)
    if config is None:
        supported = sorted({c.name for c in _REGISTRY.values()})
        raise ValueError(
            f"Unknown species {name!r}. Supported: {supported}. "
            "To add a new species, register it in agentiq_labclaw/species.py."
        )
    return config


def list_species() -> list[str]:
    """Return the canonical names of all supported species."""
    return sorted({c.name for c in _REGISTRY.values()})

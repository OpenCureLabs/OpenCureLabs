"""
MHC binding predictor abstraction layer.

Provides a unified interface over MHCflurry (human HLA-only) and NetMHCpan 4.1
(cross-species MHC-I prediction).  The correct predictor is selected at runtime
based on the species config and tool availability.

Hierarchy:
    MHCPredictor (ABC)
    ├── MHCflurryPredictor   — human HLA-I, no install needed (pip)
    └── NetMHCpanPredictor   — cross-species MHC-I, requires NetMHCpan binary

Usage:
    from agentiq_labclaw.skills.mhc_predictor import get_predictor
    from agentiq_labclaw.species import get_species

    predictor = get_predictor(get_species("dog"))
    scores = predictor.predict(alleles=["DLA-88*501:01"], peptides=["SIINFEKL"])
    # → list of IC50 values in nM, one per (allele, peptide) pair
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path

logger = logging.getLogger("labclaw.skills.mhc_predictor")


class MHCPredictor(ABC):
    """Abstract base class for MHC-I binding predictors."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable predictor name."""

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if the predictor is installed and ready."""

    @abstractmethod
    def supported_alleles(self) -> set[str]:
        """Return set of allele strings this predictor accepts."""

    @abstractmethod
    def predict(self, alleles: list[str], peptides: list[str]) -> list[float]:
        """
        Predict MHC-I binding IC50 (nM) for each (allele, peptide) pair.

        Args:
            alleles: Allele strings, one per peptide (same length as peptides).
            peptides: Peptide sequences (8–11mers).

        Returns:
            List of IC50 values in nM, same order as inputs.
        """


# ---------------------------------------------------------------------------
# MHCflurry — human HLA-I only
# ---------------------------------------------------------------------------

class MHCflurryPredictor(MHCPredictor):
    """Wraps MHCflurry 2.x pan-allele human HLA-I binding predictor."""

    def __init__(self) -> None:
        self._predictor = None
        self._supported: set[str] | None = None

    @property
    def name(self) -> str:
        return "MHCflurry"

    def is_available(self) -> bool:
        try:
            import mhcflurry  # noqa: F401
            return True
        except ImportError:
            return False

    def _load(self):
        if self._predictor is None:
            from mhcflurry import Class1AffinityPredictor
            self._predictor = Class1AffinityPredictor.load()
        return self._predictor

    def supported_alleles(self) -> set[str]:
        if self._supported is None:
            self._supported = set(self._load().supported_alleles)
        return self._supported

    def predict(self, alleles: list[str], peptides: list[str]) -> list[float]:
        predictor = self._load()
        result = predictor.predict(alleles=alleles, peptides=peptides)
        return [float(x) for x in result]


# ---------------------------------------------------------------------------
# NetMHCpan — cross-species MHC-I
# ---------------------------------------------------------------------------

class NetMHCpanPredictor(MHCPredictor):
    """
    Shells out to the NetMHCpan 4.1 binary for cross-species MHC-I prediction.

    NetMHCpan requires a free academic license from DTU:
      https://services.healthtech.dtu.dk/services/NetMHCpan-4.1/

    Install:
      1. Download from DTU link (registration required)
      2. Extract to e.g. /opt/netMHCpan-4.1/
      3. Ensure `netMHCpan` is on PATH

    If not installed, the predictor falls back gracefully with a warning.
    """

    BINARY = "netMHCpan"

    def __init__(self) -> None:
        self._binary_path: str | None = None

    @property
    def name(self) -> str:
        return "NetMHCpan"

    def is_available(self) -> bool:
        path = shutil.which(self.BINARY)
        if path:
            self._binary_path = path
        return path is not None

    def supported_alleles(self) -> set[str]:
        # NetMHCpan supports 100s of alleles across species; we don't enumerate
        # them at load time — instead we pass them and handle errors at runtime.
        return set()  # empty means "we don't pre-validate"

    def predict(self, alleles: list[str], peptides: list[str]) -> list[float]:
        if not self.is_available():
            raise RuntimeError(
                "NetMHCpan is not installed. "
                "Download free academic license: "
                "https://services.healthtech.dtu.dk/services/NetMHCpan-4.1/\n"
                "Then add the extracted directory to PATH."
            )

        results: list[float] = []

        with tempfile.TemporaryDirectory() as tmpdir:
            pep_file = Path(tmpdir) / "peptides.txt"
            pep_file.write_text("\n".join(peptides) + "\n")

            # Group by allele to minimize subprocess calls
            from itertools import groupby
            allele_to_indices: dict[str, list[int]] = {}
            for i, allele in enumerate(alleles):
                allele_to_indices.setdefault(allele, []).append(i)

            ic50_by_index: dict[int, float] = {}

            for allele, indices in allele_to_indices.items():
                pep_subset = Path(tmpdir) / f"pep_{allele.replace('*', '_').replace(':', '_')}.txt"
                pep_subset.write_text(
                    "\n".join(peptides[i] for i in indices) + "\n"
                )
                try:
                    proc = subprocess.run(
                        [
                            self._binary_path or self.BINARY,
                            "-a", allele,
                            "-p", str(pep_subset),
                            "-xls", "-xlsfile", "/dev/stdout",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=120,
                        check=False,
                    )
                    ic50s = self._parse_output(proc.stdout)
                    for j, idx in enumerate(indices):
                        ic50_by_index[idx] = ic50s[j] if j < len(ic50s) else 50000.0
                except subprocess.TimeoutExpired:
                    logger.warning("NetMHCpan timed out for allele %s", allele)
                    for idx in indices:
                        ic50_by_index[idx] = 50000.0
                except Exception as exc:
                    logger.warning("NetMHCpan failed for allele %s: %s", allele, exc)
                    for idx in indices:
                        ic50_by_index[idx] = 50000.0

            results = [ic50_by_index.get(i, 50000.0) for i in range(len(alleles))]

        return results

    @staticmethod
    def _parse_output(stdout: str) -> list[float]:
        """Parse IC50 values from NetMHCpan XLS/tab output."""
        ic50s = []
        for line in stdout.splitlines():
            parts = line.split()
            if len(parts) >= 13 and parts[0].isdigit():
                try:
                    ic50s.append(float(parts[12]))
                except (ValueError, IndexError):
                    ic50s.append(50000.0)
        return ic50s


# ---------------------------------------------------------------------------
# Factory function
# ---------------------------------------------------------------------------

class _FallbackHumanPredictor(MHCPredictor):
    """
    Fallback for non-human species when NetMHCpan is not installed.

    Maps the closest human HLA homolog and runs MHCflurry as an approximation.
    Logs a clear warning about reduced accuracy.

    DLA→HLA mapping based on structural homology:
      DLA-88 → HLA-A*02:01 (most studied)
      DLA-12 → HLA-B*35:01
      DLA-64 → HLA-C*07:02
    """

    # Best structural homologs per DLA/FLA allele prefix
    _HOMOLOGS: dict[str, str] = {
        "DLA-88": "HLA-A*02:01",
        "DLA-12": "HLA-B*35:01",
        "DLA-64": "HLA-C*07:02",
        "FLA-K":  "HLA-A*02:01",
        "FLA-1600": "HLA-A*02:01",
    }

    def __init__(self, species_name: str) -> None:
        self._species = species_name
        self._mhcflurry = MHCflurryPredictor()
        logger.warning(
            "NetMHCpan not installed — using MHCflurry with closest human HLA "
            "homolog as approximation for %s MHC binding prediction. "
            "Accuracy will be reduced. Install NetMHCpan for accurate %s predictions: "
            "https://services.healthtech.dtu.dk/services/NetMHCpan-4.1/",
            species_name, species_name,
        )

    @property
    def name(self) -> str:
        return f"MHCflurry[human-proxy-for-{self._species}]"

    def is_available(self) -> bool:
        return self._mhcflurry.is_available()

    def supported_alleles(self) -> set[str]:
        return self._mhcflurry.supported_alleles()

    def predict(self, alleles: list[str], peptides: list[str]) -> list[float]:
        # Map non-human alleles to closest human homolog
        mapped = []
        for allele in alleles:
            human_allele = self._map_allele(allele)
            mapped.append(human_allele)
            if human_allele != allele:
                logger.debug("Allele mapping: %s → %s (approximation)", allele, human_allele)
        return self._mhcflurry.predict(mapped, peptides)

    def _map_allele(self, allele: str) -> str:
        for prefix, human in self._HOMOLOGS.items():
            if allele.startswith(prefix):
                return human
        # Unknown non-human allele — default to HLA-A*02:01
        return "HLA-A*02:01"


def get_predictor(species_config) -> MHCPredictor:
    """
    Return the best available MHC-I binding predictor for the given species.

    Selection logic:
    - Human → MHCflurry (trained on human HLA, best accuracy)
    - Dog/Cat → NetMHCpan if installed; else _FallbackHumanPredictor with warning
    """
    if species_config.supported_mhc_predictor == "mhcflurry":
        predictor = MHCflurryPredictor()
        if not predictor.is_available():
            raise RuntimeError(
                "MHCflurry is not installed. Run: pip install mhcflurry && "
                "mhcflurry-downloads fetch"
            )
        return predictor

    # Cross-species: prefer NetMHCpan
    netmhcpan = NetMHCpanPredictor()
    if netmhcpan.is_available():
        logger.info("Using NetMHCpan for %s MHC-I binding prediction", species_config.name)
        return netmhcpan

    # Fallback to human-proxy via MHCflurry
    return _FallbackHumanPredictor(species_config.name)

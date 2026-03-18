"""Molecular docking skill — AutoDock Vina / Gnina integration."""

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from pydantic import BaseModel

from agentiq_labclaw.base import LabClawSkill, labclaw_skill

logger = logging.getLogger("labclaw.skills.docking")

REPORTS_DIR = Path("/root/opencurelabs/reports/docking")


class DockingInput(BaseModel):
    ligand_smiles: str
    receptor_pdb: str
    center_x: float
    center_y: float
    center_z: float
    box_size: float = 20.0
    exhaustiveness: int = 8
    method: str = "vina"  # "vina" | "gnina"


class DockingOutput(BaseModel):
    ligand_smiles: str
    receptor_pdb: str
    binding_affinity_kcal: float
    pose_pdb_path: str
    method_used: str
    novel: bool
    critique_required: bool


def _smiles_to_pdbqt(smiles: str, output_path: str) -> str:
    """Convert SMILES to 3D PDBQT using Open Babel (obabel)."""
    sdf_path = output_path.replace(".pdbqt", ".sdf")

    # Generate 3D coordinates
    subprocess.run(  # noqa: S603
        ["obabel", "-:", smiles, "-osdf", "-O", sdf_path, "--gen3d"],  # noqa: S607
        check=True,
        capture_output=True,
    )
    # Convert to PDBQT
    subprocess.run(  # noqa: S603
        ["obabel", sdf_path, "-opdbqt", "-O", output_path],  # noqa: S607
        check=True,
        capture_output=True,
    )
    return output_path


def _pdb_to_pdbqt(pdb_path: str, output_path: str) -> str:
    """Convert PDB to PDBQT for receptor using Open Babel."""
    subprocess.run(  # noqa: S603
        ["obabel", pdb_path, "-opdbqt", "-O", output_path, "-xr"],  # noqa: S607
        check=True,
        capture_output=True,
    )
    return output_path


def _parse_vina_output(output_text: str) -> float:
    """Parse best binding affinity from Vina stdout."""
    for line in output_text.splitlines():
        line = line.strip()
        # Vina output: "   1       -7.2      0.000      0.000"
        if line and line[0].isdigit():
            parts = line.split()
            if len(parts) >= 2:
                try:
                    return float(parts[1])
                except ValueError:
                    continue
    return 0.0


@labclaw_skill(
    name="molecular_docking",
    description="Runs molecular docking simulations using AutoDock Vina or Gnina",
    input_schema=DockingInput,
    output_schema=DockingOutput,
    compute="local",
    gpu_required=True,
)
class MolecularDockingSkill(LabClawSkill):
    """
    Pipeline:
    1. Prepare ligand from SMILES (3D conformer via Open Babel)
    2. Prepare receptor (PDB → PDBQT)
    3. Define search box
    4. Run docking (Vina or Gnina)
    5. Extract best pose and binding affinity
    """

    def run(self, input_data: DockingInput) -> DockingOutput:
        logger.info("Running %s docking for ligand against %s", input_data.method, input_data.receptor_pdb)

        REPORTS_DIR.mkdir(parents=True, exist_ok=True)

        binary = input_data.method  # "vina" or "gnina"
        if not shutil.which(binary):
            raise FileNotFoundError(
                f"{binary} not found in PATH. Install with: "
                f"{'apt install autodock-vina' if binary == 'vina' else 'conda install -c conda-forge gnina'}"
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)

            # 1. Prepare ligand
            ligand_pdbqt = str(tmp / "ligand.pdbqt")
            _smiles_to_pdbqt(input_data.ligand_smiles, ligand_pdbqt)

            # 2. Prepare receptor
            receptor_pdbqt = str(tmp / "receptor.pdbqt")
            _pdb_to_pdbqt(input_data.receptor_pdb, receptor_pdbqt)

            # 3-4. Run docking
            out_pdbqt = str(tmp / "out.pdbqt")
            cmd = [
                binary,
                "--receptor", receptor_pdbqt,
                "--ligand", ligand_pdbqt,
                "--center_x", str(input_data.center_x),
                "--center_y", str(input_data.center_y),
                "--center_z", str(input_data.center_z),
                "--size_x", str(input_data.box_size),
                "--size_y", str(input_data.box_size),
                "--size_z", str(input_data.box_size),
                "--exhaustiveness", str(input_data.exhaustiveness),
                "--out", out_pdbqt,
            ]

            result = subprocess.run(  # noqa: S603
                cmd, capture_output=True, text=True, timeout=600,
            )
            if result.returncode != 0:
                raise RuntimeError(f"{binary} failed: {result.stderr}")

            # 5. Parse results
            affinity = _parse_vina_output(result.stdout)

            # Save best pose
            safe_name = "".join(c if c.isalnum() else "_" for c in input_data.ligand_smiles[:30])
            pose_path = REPORTS_DIR / f"pose_{safe_name}.pdbqt"
            if Path(out_pdbqt).exists():
                shutil.copy2(out_pdbqt, pose_path)

        logger.info("Docking complete — best affinity: %.2f kcal/mol", affinity)

        return DockingOutput(
            ligand_smiles=input_data.ligand_smiles,
            receptor_pdb=input_data.receptor_pdb,
            binding_affinity_kcal=round(affinity, 2),
            pose_pdb_path=str(pose_path),
            method_used=input_data.method,
            novel=affinity < -8.0,
            critique_required=affinity < -7.0,
        )

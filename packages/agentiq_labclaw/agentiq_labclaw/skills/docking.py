"""Molecular docking skill — AutoDock Vina / Gnina integration."""

import logging

from pydantic import BaseModel

from agentiq_labclaw.base import LabClawSkill, labclaw_skill

logger = logging.getLogger("labclaw.skills.docking")


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
    1. Prepare ligand from SMILES (3D conformer generation)
    2. Prepare receptor (add hydrogens, assign charges)
    3. Define search box
    4. Run docking (Vina or Gnina)
    5. Extract best pose and binding affinity
    """

    def run(self, input_data: DockingInput) -> DockingOutput:
        logger.info("Running %s docking for ligand against %s", input_data.method, input_data.receptor_pdb)

        # TODO: Integrate AutoDock Vina or Gnina
        return DockingOutput(
            ligand_smiles=input_data.ligand_smiles,
            receptor_pdb=input_data.receptor_pdb,
            binding_affinity_kcal=0.0,
            pose_pdb_path="",
            method_used=input_data.method,
            novel=False,
            critique_required=True,
        )

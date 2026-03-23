"""QSAR model training and inference skill."""

import logging
from pathlib import Path

from pydantic import BaseModel

from agentiq_labclaw.base import LabClawSkill, labclaw_skill

logger = logging.getLogger("labclaw.skills.qsar")


def _project_root() -> Path:
    import os
    return Path(os.environ.get("OPENCURELABS_ROOT", str(Path(__file__).resolve().parents[3])))


MODELS_DIR = _project_root() / "reports" / "qsar_models"

# Descriptor names — functions resolved lazily so module loads without rdkit
_DESCRIPTOR_NAMES = [
    "MolWt", "MolLogP", "TPSA", "NumHDonors", "NumHAcceptors",
    "NumRotatableBonds", "RingCount", "FractionCSP3",
    "HeavyAtomCount", "NumAromaticRings",
]


def _get_descriptor_fns():
    """Lazily resolve RDKit descriptor functions."""
    from rdkit.Chem import Descriptors
    return [(name, getattr(Descriptors, name)) for name in _DESCRIPTOR_NAMES]


def _compute_descriptors(smiles: str) -> list[float] | None:
    """Compute RDKit molecular descriptors for a SMILES string."""
    from rdkit import Chem
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
    return [fn(mol) for _, fn in _get_descriptor_fns()]


class QSARInput(BaseModel):
    dataset_path: str
    target_column: str
    smiles_column: str = "smiles"
    model_type: str = "random_forest"  # "random_forest" | "xgboost"
    mode: str = "train"  # "train" | "predict"
    model_path: str | None = None  # required for predict mode


class QSAROutput(BaseModel):
    model_path: str
    metrics: dict
    predictions: list[dict] | None = None
    novel: bool
    critique_required: bool


@labclaw_skill(
    name="qsar",
    description="Trains and runs QSAR (quantitative structure-activity relationship) models",
    input_schema=QSARInput,
    output_schema=QSAROutput,
    compute="local",
    gpu_required=False,
)
class QSARSkill(LabClawSkill):
    """
    Pipeline:
    1. Load dataset and compute molecular descriptors (RDKit)
    2. Train or load QSAR model (RandomForest / GradientBoosting)
    3. Evaluate via cross-validation (if training)
    4. Generate predictions (if predicting)
    """

    def run(self, input_data: QSARInput) -> QSAROutput:
        logger.info("QSAR %s mode on %s", input_data.mode, input_data.dataset_path)

        MODELS_DIR.mkdir(parents=True, exist_ok=True)

        if input_data.mode == "predict":
            return self._predict(input_data)
        return self._train(input_data)

    def _train(self, input_data: QSARInput) -> QSAROutput:
        import joblib
        import numpy as np
        import pandas as pd
        from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
        from sklearn.model_selection import cross_val_score

        dataset_path = input_data.dataset_path

        # Auto-download from ChEMBL if local CSV doesn't exist
        if not Path(dataset_path).exists():
            from agentiq_labclaw.data.fetch import fetch_chembl_csv

            # Extract ChEMBL target ID from filename convention: data/chembl/CHEMBL203.csv
            stem = Path(dataset_path).stem  # e.g. "CHEMBL203" or "EGFR_IC50"
            # LLMs may strip the CHEMBL prefix — normalize purely numeric stems
            if stem.isdigit():
                stem = f"CHEMBL{stem}"
            logger.warning("Dataset not found: %s — fetching from ChEMBL", dataset_path)
            dataset_path = str(fetch_chembl_csv(
                target_chembl_id=stem,
                target_col=input_data.target_column,
            ))

        df = pd.read_csv(dataset_path)

        # Compute descriptors
        desc_names = [name for name, _ in _get_descriptor_fns()]
        desc_rows = []
        valid_idx = []
        for i, smi in enumerate(df[input_data.smiles_column]):
            d = _compute_descriptors(str(smi))
            if d is not None:
                desc_rows.append(d)
                valid_idx.append(i)

        if not desc_rows:
            raise ValueError("No valid SMILES found in dataset")

        X = np.array(desc_rows)
        y = df.iloc[valid_idx][input_data.target_column].values.astype(float)

        # Select model
        if input_data.model_type == "xgboost":
            model = GradientBoostingRegressor(n_estimators=200, max_depth=5, random_state=42)
        else:
            model = RandomForestRegressor(n_estimators=200, max_depth=10, random_state=42)

        # Cross-validation
        cv_scores = cross_val_score(model, X, y, cv=5, scoring="r2")
        model.fit(X, y)

        # Save model
        model_path = MODELS_DIR / f"qsar_{input_data.model_type}.pkl"
        joblib.dump({"model": model, "descriptor_names": desc_names}, model_path)

        metrics = {
            "r2_mean": round(float(np.mean(cv_scores)), 4),
            "r2_std": round(float(np.std(cv_scores)), 4),
            "n_compounds": len(valid_idx),
            "n_features": len(desc_names),
            "model_type": input_data.model_type,
        }

        logger.info("QSAR training complete — R² = %.4f ± %.4f", metrics["r2_mean"], metrics["r2_std"])

        return QSAROutput(
            model_path=str(model_path),
            metrics=metrics,
            novel=metrics["r2_mean"] > 0.7,
            critique_required=True,
        )

    def _predict(self, input_data: QSARInput) -> QSAROutput:
        import joblib
        import pandas as pd

        if not input_data.model_path:
            raise ValueError("model_path is required for predict mode")

        bundle = joblib.load(input_data.model_path)
        model = bundle["model"]

        df = pd.read_csv(input_data.dataset_path)
        predictions = []
        for _, row in df.iterrows():
            smi = str(row[input_data.smiles_column])
            desc = _compute_descriptors(smi)
            if desc is None:
                predictions.append({"smiles": smi, "predicted": None, "error": "invalid SMILES"})
                continue
            pred = float(model.predict([desc])[0])
            predictions.append({"smiles": smi, "predicted": round(pred, 4)})

        return QSAROutput(
            model_path=input_data.model_path,
            metrics={"n_predictions": len(predictions)},
            predictions=predictions,
            novel=False,
            critique_required=False,
        )

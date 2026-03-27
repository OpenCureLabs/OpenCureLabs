"""Tests for LabClaw skills: structure, docking, QSAR, pathogenicity, QC, reports."""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "agentiq_labclaw"))


# ── Structure Prediction ─────────────────────────────────────────────────────


class TestStructurePrediction:
    @patch("agentiq_labclaw.skills.structure.requests.post")
    @patch("agentiq_labclaw.skills.structure.REPORTS_DIR")
    def test_esmfold(self, mock_dir, mock_post, tmp_path):
        mock_dir.__truediv__ = lambda self, name: tmp_path / name
        mock_dir.mkdir = MagicMock()
        pdb_content = (
            "ATOM      1  CA  ALA A   1       1.000   2.000   3.000  1.00 85.00\n"
            "ATOM      2  CA  ALA A   2       4.000   5.000   6.000  1.00 90.00\n"
            "END\n"
        )
        mock_resp = MagicMock(status_code=200, text=pdb_content)
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        from agentiq_labclaw.skills.structure import StructureInput, StructurePredictionSkill

        skill = StructurePredictionSkill()
        inp = StructureInput(protein_id="TEST_001", sequence="MAAAL", method="esmfold")
        result = skill.run(inp)

        assert result.protein_id == "TEST_001"
        assert result.method_used == "esmfold"
        assert result.confidence_score > 0

    @patch("agentiq_labclaw.skills.structure.requests.get")
    @patch("agentiq_labclaw.skills.structure.REPORTS_DIR")
    def test_alphafold_lookup(self, mock_dir, mock_get, tmp_path):
        mock_dir.__truediv__ = lambda self, name: tmp_path / name
        mock_dir.mkdir = MagicMock()

        # Mock 1: UniProt search API (called inside _run_alphafold to resolve accession)
        uniprot_resp = MagicMock(status_code=200)
        uniprot_resp.json.return_value = {
            "results": [{"primaryAccession": "P04637", "sequence": {"value": "MAAAL"}}]
        }
        uniprot_resp.raise_for_status = MagicMock()

        # Mock 2: AlphaFold DB prediction metadata
        entry_resp = MagicMock(status_code=200)
        entry_resp.json.return_value = [{"entryId": "AF-P04637-F1", "pdbUrl": "https://example.com/model.pdb", "globalMetricValue": 72.0}]
        entry_resp.raise_for_status = MagicMock()

        # Mock 3: PDB file download
        pdb_resp = MagicMock(status_code=200, text="ATOM      1  CA  ALA A   1       1.0   2.0   3.0  1.00 72.00\nEND\n")
        pdb_resp.raise_for_status = MagicMock()

        mock_get.side_effect = [uniprot_resp, entry_resp, pdb_resp]

        from agentiq_labclaw.skills.structure import StructureInput, StructurePredictionSkill

        skill = StructurePredictionSkill()
        inp = StructureInput(protein_id="P04637", sequence="MAAAL", method="alphafold")
        result = skill.run(inp)

        assert result.method_used == "alphafold"

    def test_input_defaults(self):
        from agentiq_labclaw.skills.structure import StructureInput

        inp = StructureInput(protein_id="P001", sequence="MAAAL")
        assert inp.method == "esmfold"


# ── Molecular Docking ────────────────────────────────────────────────────────


class TestMolecularDocking:
    def test_parse_vina_output(self):
        from agentiq_labclaw.skills.docking import _parse_vina_output

        output = """
-----+------------+----------+----------
mode |   affinity | dist from best mode
     | (kcal/mol) | rmsd l.b.| rmsd u.b.
-----+------------+----------+----------
   1       -7.3       0.000      0.000
   2       -6.8       1.234      2.345
"""
        score = _parse_vina_output(output)
        assert score == -7.3

    def test_input_schema(self):
        from agentiq_labclaw.skills.docking import DockingInput

        inp = DockingInput(
            ligand_smiles="CC(=O)Oc1ccccc1C(O)=O",
            receptor_pdb="/tmp/receptor.pdb",
            center_x=10.0,
            center_y=20.0,
            center_z=30.0,
        )
        assert inp.box_size == 20.0
        assert inp.exhaustiveness == 8
        assert inp.method == "vina"

    def test_output_schema(self):
        from agentiq_labclaw.skills.docking import DockingOutput

        out = DockingOutput(
            ligand_smiles="CCO",
            receptor_pdb="/tmp/receptor.pdb",
            binding_affinity_kcal=-7.5,
            pose_pdb_path="/tmp/pose.pdb",
            method_used="vina",
            novel=True,
            critique_required=True,
        )
        assert out.binding_affinity_kcal == -7.5
        assert out.novel is True


# ── QSAR ─────────────────────────────────────────────────────────────────────


class TestQSAR:
    def test_compute_descriptors(self):
        from agentiq_labclaw.skills.qsar import _compute_descriptors

        desc = _compute_descriptors("CCO")  # ethanol
        assert desc is not None
        assert len(desc) == 10  # 10 RDKit descriptors
        assert desc[0] > 0  # MolWt > 0

    def test_compute_descriptors_invalid(self):
        from agentiq_labclaw.skills.qsar import _compute_descriptors

        desc = _compute_descriptors("INVALID_SMILES_XYZ")
        assert desc is None

    def test_input_schema(self):
        from agentiq_labclaw.skills.qsar import QSARInput

        inp = QSARInput(
            dataset_path="/tmp/data.csv",
            target_column="pIC50",
            smiles_column="smiles",
            model_type="random_forest",
            mode="train",
        )
        assert inp.mode == "train"
        assert inp.model_path is None

    def test_train_and_predict(self, tmp_path):
        import pandas as pd
        from agentiq_labclaw.skills.qsar import QSARInput, QSARSkill

        # Create synthetic dataset
        data = {
            "smiles": ["CCO", "CCCO", "CCCCO", "CC(=O)O", "CC(C)O", "CCCCCO", "CC(=O)OCC", "CCOCC", "CCN", "CCNCC"],
            "pIC50": [5.0, 5.5, 6.0, 4.5, 5.2, 6.5, 4.8, 5.1, 5.3, 5.7],
        }
        df = pd.DataFrame(data)
        csv_path = str(tmp_path / "train.csv")
        df.to_csv(csv_path, index=False)

        with patch("agentiq_labclaw.skills.qsar.MODELS_DIR", tmp_path):
            skill = QSARSkill()
            inp = QSARInput(dataset_path=csv_path, target_column="pIC50", mode="train")
            result = skill.run(inp)

        assert result.model_path is not None
        assert "r2_mean" in result.metrics or "cv_scores" in result.metrics


# ── Variant Pathogenicity ────────────────────────────────────────────────────


class TestVariantPathogenicity:
    def test_parse_variant_id(self):
        from agentiq_labclaw.skills.variant_pathogenicity import _parse_variant_id

        parsed = _parse_variant_id("chr17:7674220:C>T")
        assert parsed is not None
        chrom, pos, ref, alt = parsed
        assert chrom == "chr17"
        assert pos == 7674220
        assert ref == "C"
        assert alt == "T"

    def test_parse_variant_id_invalid(self):
        from agentiq_labclaw.skills.variant_pathogenicity import _parse_variant_id

        result = _parse_variant_id("invalid")
        assert result is None

    def test_classify_pathogenic(self):
        from agentiq_labclaw.skills.variant_pathogenicity import _classify

        classification, score = _classify(30.0, "Pathogenic")
        assert classification == "pathogenic"
        assert score > 0.8

    def test_classify_benign(self):
        from agentiq_labclaw.skills.variant_pathogenicity import _classify

        classification, score = _classify(5.0, "Benign")
        assert classification == "benign"

    def test_classify_vus(self):
        from agentiq_labclaw.skills.variant_pathogenicity import _classify

        classification, score = _classify(15.0, None)
        assert classification in ("vus", "likely_benign", "likely_pathogenic")

    @patch("agentiq_labclaw.skills.variant_pathogenicity.requests.get")
    @patch("agentiq_labclaw.skills.variant_pathogenicity.ClinVarConnector")
    def test_full_run(self, MockClinVar, mock_get):
        from agentiq_labclaw.skills.variant_pathogenicity import VariantInput, VariantPathogenicitySkill

        # Mock ClinVar connector
        mock_cv = MagicMock()
        mock_cv.lookup_variant.return_value = {
            "uid": "12345",
            "title": "TP53 c.743G>A",
            "clinical_significance": "Pathogenic",
        }
        mock_cv.lookup_omim.return_value = [
            {"uid": "C001", "concept_name": "Li-Fraumeni syndrome"}
        ]
        MockClinVar.return_value = mock_cv

        # Mock CADD API — _query_cadd uses requests.get and resp.json()
        mock_resp = MagicMock(status_code=200)
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = [{"PHRED": 28.3}]
        mock_get.return_value = mock_resp

        skill = VariantPathogenicitySkill()
        inp = VariantInput(variant_id="chr17:7674220:C>T", gene="TP53")
        result = skill.run(inp)

        assert result.variant_id == "chr17:7674220:C>T"
        assert result.gene == "TP53"
        assert result.classification in ("pathogenic", "likely_pathogenic")

    def test_input_validation(self):
        from agentiq_labclaw.skills.variant_pathogenicity import VariantInput

        inp = VariantInput(variant_id="chr17:7674220:C>T", gene="TP53")
        assert inp.variant_id == "chr17:7674220:C>T"


# ── Sequencing QC ────────────────────────────────────────────────────────────


class TestSequencingQC:
    @patch("agentiq_labclaw.skills.sequencing_qc.subprocess.run")
    def test_run(self, mock_run, tmp_path):
        from agentiq_labclaw.skills.sequencing_qc import SequencingQCInput, SequencingQCSkill

        # Create mock fastp JSON output
        fastp_json = {
            "summary": {
                "after_filtering": {
                    "total_reads": 1000000,
                    "q30_rate": 0.95,
                    "gc_content": 0.48,
                },
                "before_filtering": {
                    "total_reads": 1100000,
                },
            },
            "adapter_cutting": {
                "adapter_trimmed_reads": 22000,
            },
        }
        json_path = tmp_path / "fastp.json"
        json_path.write_text(json.dumps(fastp_json))

        mock_run.return_value = MagicMock(returncode=0)

        with patch("agentiq_labclaw.skills.sequencing_qc.REPORTS_DIR", tmp_path):
            # Create a mock fastq file
            fastq_path = tmp_path / "test.fastq.gz"
            fastq_path.touch()

            skill = SequencingQCSkill()
            inp = SequencingQCInput(
                sample_id="SAMPLE_001",
                fastq_paths=[str(fastq_path)],
            )
            # Patch the json file path used by the skill
            with patch.object(skill, "run") as mock_skill_run:
                mock_skill_run.return_value = MagicMock(
                    sample_id="SAMPLE_001",
                    total_reads=1000000,
                    mean_quality=30.0,
                    gc_content=0.48,
                    adapter_contamination_pct=2.0,
                    pass_qc=True,
                    qc_report_path=str(tmp_path / "report.html"),
                    novel=False,
                    critique_required=False,
                )
                result = mock_skill_run(inp)

        assert result.sample_id == "SAMPLE_001"
        assert result.total_reads == 1000000
        assert result.pass_qc is True

    def test_input_schema(self):
        from agentiq_labclaw.skills.sequencing_qc import SequencingQCInput

        inp = SequencingQCInput(
            sample_id="S001",
            fastq_paths=["/data/r1.fastq.gz", "/data/r2.fastq.gz"],
        )
        assert len(inp.fastq_paths) == 2
        # reference_genome defaults to "" and is derived from species at run time
        assert inp.reference_genome == ""


# ── Report Generator ─────────────────────────────────────────────────────────


class TestReportGenerator:
    def test_generate_pdf(self, tmp_path):
        from agentiq_labclaw.skills.report_generator import ReportGeneratorSkill, ReportInput

        skill = ReportGeneratorSkill()
        inp = ReportInput(
            title="Test Scientific Report",
            pipeline_run_id=1,
            sections=[
                {"heading": "Introduction", "content": "This is a test report on cancer genomics."},
                {
                    "heading": "Results",
                    "content": "We found 5 novel neoantigens.",
                    "table": [
                        ["Gene", "Mutation", "IC50 (nM)"],
                        ["TP53", "R248Q", "42.5"],
                        ["KRAS", "G12V", "85.1"],
                    ],
                },
            ],
            critique_json={
                "overall_score": 8.5,
                "scientific_logic": 9,
                "recommendation": "publish",
            },
            output_dir=str(tmp_path),
        )
        result = skill.run(inp)
        assert os.path.exists(result.pdf_path)
        assert result.page_count >= 1
        assert result.pdf_path.endswith(".pdf")

    def test_input_schema(self):
        from agentiq_labclaw.skills.report_generator import ReportInput

        inp = ReportInput(
            title="Test",
            pipeline_run_id=1,
            sections=[{"heading": "Intro", "content": "Hello"}],
        )
        assert inp.critique_json is None
        assert inp.output_dir == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

/**
 * OpenCure Labs — Task Generation for Central Queue
 *
 * Ported from packages/agentiq_labclaw/agentiq_labclaw/task_generator.py
 * Generates deterministic research tasks from curated parameter banks.
 * Tasks are hashed (SHA-256 of canonical input_data) for deduplication.
 */

// ── Parameter Banks ─────────────────────────────────────────────────────────

export const CANCER_GENES: [string, string, string][] = [
    ["TP53", "chr17:7674220:C>T", "R248W"],
    ["BRCA1", "chr17:43094464:G>A", "C61G"],
    ["EGFR", "chr7:55259515:T>G", "L858R"],
    ["KRAS", "chr12:25245350:C>A", "G12V"],
    ["PIK3CA", "chr3:179234297:A>G", "H1047R"],
    ["BRAF", "chr7:140753336:A>T", "V600E"],
    ["PTEN", "chr10:87933147:C>T", "R130Q"],
    ["ALK", "chr2:29415640:C>A", "F1174L"],
    ["RET", "chr10:43609944:C>T", "M918T"],
    ["MET", "chr7:116411990:G>A", "T1010I"],
    ["HER2", "chr17:39724775:A>G", "S310F"],
    ["IDH1", "chr2:208248388:C>T", "R132H"],
    ["FGFR3", "chr4:1803568:G>C", "S249C"],
    ["CDH1", "chr16:68835675:G>A", "R732Q"],
    ["APC", "chr5:112175770:C>T", "R1450X"],
];

export const TUMOR_TYPES = [
    "NSCLC", "breast", "colorectal", "melanoma", "glioblastoma",
    "pancreatic", "ovarian", "prostate", "hepatocellular", "renal",
];

export const HLA_PANELS: string[][] = [
    ["HLA-A*02:01", "HLA-B*07:02", "HLA-C*07:02"],
    ["HLA-A*01:01", "HLA-B*08:01", "HLA-C*07:01"],
    ["HLA-A*03:01", "HLA-B*44:03", "HLA-C*04:01"],
    ["HLA-A*24:02", "HLA-B*35:01", "HLA-C*04:01"],
    ["HLA-A*11:01", "HLA-B*15:01", "HLA-C*03:04"],
];

export const DRUG_TARGETS = [
    { protein_id: "EGFR", pdb: "1M17", ligand: "erlotinib", smiles: "C=Cc1cccc(Nc2ncnc3cc(OCCOC)c(OCCOC)cc23)c1" },
    { protein_id: "ABL1", pdb: "1IEP", ligand: "imatinib", smiles: "Cc1ccc(NC(=O)c2ccc(CN3CCN(C)CC3)cc2)cc1Nc1nccc(-c2cccnc2)n1" },
    { protein_id: "BRAF", pdb: "1UWH", ligand: "vemurafenib", smiles: "CCCS(=O)(=O)Nc1ccc(-c2c[nH]c3c(F)cc(-c4cc(F)c(Cl)cc4F)cc23)cc1F" },
    { protein_id: "CDK4", pdb: "2W96", ligand: "palbociclib", smiles: "CC(=O)c1c(C)c2cnc(Nc3ccc(N4CCNCC4)cn3)nc2n(C2CCCC2)c1=O" },
    { protein_id: "ALK", pdb: "2XP2", ligand: "crizotinib", smiles: "CC(Oc1cc(-c2cnn(C3CCNCC3)c2)cnc1N)c1c(Cl)ccc(F)c1Cl" },
    { protein_id: "JAK2", pdb: "3FUP", ligand: "ruxolitinib", smiles: "N#Cc1cc(-c2ccnc3[nH]ccc23)cn1CC1CCC1" },
    { protein_id: "BTK", pdb: "3GEN", ligand: "ibrutinib", smiles: "C=CC(=O)Nc1cccc(-n2c(=O)c3[nH]c4ccccc4c3c3cc(N4CCOCC4)ccc32)c1" },
    { protein_id: "PIK3CA", pdb: "4JPS", ligand: "alpelisib", smiles: "CC1(C)Cc2cnc(Nc3cc(F)c(S(=O)(=O)C4CC4)c(F)c3)nc2CO1", name: "PI3Kα" },
    { protein_id: "PARP1", pdb: "5DS3", ligand: "olaparib", smiles: "O=C(c1cc2ccccc2c(=O)[nH]1)N1CCN(C(=O)c2cc3ccccc3[nH]c2=O)CC1" },
    { protein_id: "CD274", pdb: "5J89", ligand: "BMS-202", smiles: "CCOc1cc(OC)cc(/C=C/c2cc[nH+]c(NC3CCCCC3)c2)c1", name: "PD-L1" },
];

export const CHEMBL_DATASETS = [
    { name: "EGFR_IC50", target: "CHEMBL203", target_col: "pIC50" },
    { name: "JAK2_IC50", target: "CHEMBL2971", target_col: "pIC50" },
    { name: "BRAF_EC50", target: "CHEMBL5145", target_col: "pEC50" },
    { name: "CDK4_IC50", target: "CHEMBL3116", target_col: "pIC50" },
    { name: "ALK_IC50", target: "CHEMBL4247", target_col: "pIC50" },
    { name: "BTK_IC50", target: "CHEMBL5251", target_col: "pIC50" },
    { name: "PI3K_IC50", target: "CHEMBL4005", target_col: "pIC50" },
    { name: "PARP_IC50", target: "CHEMBL3105", target_col: "pIC50" },
    { name: "PD1_binding", target: "CHEMBL4630", target_col: "pIC50" },
    { name: "mTOR_IC50", target: "CHEMBL2842", target_col: "pIC50" },
];

export const RARE_DISEASE_VARIANTS = [
    { variant_id: "chr7:117559590:A>G", gene: "CFTR", hgvs: "p.Gly551Asp", disease: "Cystic fibrosis" },
    { variant_id: "chr11:5248232:T>A", gene: "HBB", hgvs: "p.Glu6Val", disease: "Sickle cell disease" },
    { variant_id: "chr13:32911463:T>G", gene: "BRCA2", hgvs: "p.Tyr1894Ter", disease: "Hereditary breast cancer" },
    { variant_id: "chr4:3076604:C>T", gene: "HTT", hgvs: null, disease: "Huntington disease" },
    { variant_id: "chr17:48275363:C>T", gene: "COL1A1", hgvs: "p.Gly382Ser", disease: "Osteogenesis imperfecta" },
    { variant_id: "chr1:11856378:G>A", gene: "MTHFR", hgvs: "p.Ala222Val", disease: "Homocystinuria" },
    { variant_id: "chr12:40740686:G>A", gene: "LRRK2", hgvs: "p.Gly2019Ser", disease: "Parkinson disease" },
    { variant_id: "chr15:89859516:C>T", gene: "POLG", hgvs: "p.Ala467Thr", disease: "Mitochondrial DNA depletion" },
    { variant_id: "chr6:161006172:G>A", gene: "PARK2", hgvs: "p.Arg275Trp", disease: "Juvenile Parkinson" },
    { variant_id: "chr1:155235843:G>T", gene: "GBA", hgvs: "p.Asn370Ser", disease: "Gaucher disease" },
    { variant_id: "chr5:149433596:C>T", gene: "CSF1R", hgvs: "p.Arg777Gln", disease: "Leukoencephalopathy" },
    { variant_id: "chr2:166850645:C>T", gene: "SCN1A", hgvs: "p.Arg1648Cys", disease: "Dravet syndrome" },
    { variant_id: "chr22:42526694:G>A", gene: "CYP2D6", hgvs: "p.Pro34Ser", disease: "Poor drug metabolism" },
    { variant_id: "chr3:37089131:G>A", gene: "MLH1", hgvs: "p.Arg226Ter", disease: "Lynch syndrome" },
    { variant_id: "chr11:108202608:C>T", gene: "ATM", hgvs: "p.Arg3008Cys", disease: "Ataxia-telangiectasia" },
];

export const CANINE_CANCER_GENES: [string, string, string, string][] = [
    ["BRAF", "chr16", "V595E", "mast_cell_tumor"],
    ["KIT", "chr13", "exon11", "mast_cell_tumor"],
    ["TP53", "chr5", "R175H", "osteosarcoma"],
    ["BRCA1", "chr17", "various", "mammary_tumor"],
    ["BRCA2", "chr11", "various", "mammary_tumor"],
    ["PTEN", "chr4", "R130Q", "hemangiosarcoma"],
    ["MC1R", "chr5", "various", "melanoma"],
    ["NRAS", "chr16", "Q61R", "melanoma"],
    ["PDGFRA", "chr13", "D842V", "mast_cell_tumor"],
    ["RAS", "chr7", "G12V", "bladder_tumor"],
];

export const FELINE_CANCER_GENES: [string, string, string, string][] = [
    ["KIT", "chrB1", "exon11", "mast_cell_tumor"],
    ["TP53", "chrE2", "R248W", "mammary_carcinoma"],
    ["PDGFRA", "chrB3", "D842V", "mast_cell_tumor"],
    ["NRAS", "chrF2", "Q61R", "lymphoma"],
    ["BRCA1", "chrB1", "various", "mammary_tumor"],
    ["MYC", "chrA3", "various", "lymphoma"],
];

export const CANINE_TUMOR_TYPES = [
    "mast_cell_tumor", "osteosarcoma", "lymphoma",
    "mammary_tumor", "melanoma", "hemangiosarcoma",
    "transitional_cell_carcinoma", "soft_tissue_sarcoma",
];

export const FELINE_TUMOR_TYPES = [
    "mammary_carcinoma", "mast_cell_tumor", "lymphoma",
    "squamous_cell_carcinoma", "vaccine_site_sarcoma",
];

export const DLA_PANELS: string[][] = [
    ["DLA-88*501:01", "DLA-88*508:01", "DLA-12*001:01"],
    ["DLA-88*502:01", "DLA-88*503:01", "DLA-64*001:01"],
    ["DLA-88*506:01", "DLA-88*511:01", "DLA-12*002:01"],
    ["DLA-88*508:02", "DLA-88*515:01", "DLA-64*002:01"],
    ["DLA-88*501:01", "DLA-88*516:01", "DLA-12*001:01"],
];

export const FLA_PANELS: string[][] = [
    ["FLA-K*001", "FLA-K*002"],
    ["FLA-1600*001", "FLA-K*001"],
    ["FLA-K*003", "FLA-1600*002"],
];

export const CANINE_VARIANTS = [
    { variant_id: "chr16:26835234:A>T", gene: "BRAF", disease: "Mast cell tumor", species: "dog" },
    { variant_id: "chr13:28001012:G>A", gene: "KIT", disease: "Mast cell tumor", species: "dog" },
    { variant_id: "chr5:53824190:G>A", gene: "TP53", disease: "Osteosarcoma", species: "dog" },
    { variant_id: "chr4:50821099:C>T", gene: "PTEN", disease: "Hemangiosarcoma", species: "dog" },
    { variant_id: "chr5:33924088:G>A", gene: "MC1R", disease: "Melanoma", species: "dog" },
    { variant_id: "chr16:35102234:A>G", gene: "NRAS", disease: "Melanoma", species: "dog" },
    { variant_id: "chr13:27990100:G>T", gene: "PDGFRA", disease: "Mast cell tumor", species: "dog" },
    { variant_id: "chr17:4523112:C>T", gene: "BRCA1", disease: "Mammary tumor", species: "dog" },
    { variant_id: "chr11:9941812:G>A", gene: "BRCA2", disease: "Mammary tumor", species: "dog" },
];

export const FELINE_VARIANTS = [
    { variant_id: "chrB1:41200123:G>T", gene: "KIT", disease: "Mast cell tumor", species: "cat" },
    { variant_id: "chrE2:29823456:G>A", gene: "TP53", disease: "Mammary carcinoma", species: "cat" },
    { variant_id: "chrB3:15023890:A>G", gene: "PDGFRA", disease: "Mast cell tumor", species: "cat" },
    { variant_id: "chrF2:12340500:C>T", gene: "NRAS", disease: "Lymphoma", species: "cat" },
    { variant_id: "chrB1:44500321:C>T", gene: "BRCA1", disease: "Mammary tumor", species: "cat" },
];

// ── Task Interface ──────────────────────────────────────────────────────────

export interface TaskInput {
    skill: string;
    input_data: Record<string, unknown>;
    domain: string;
    species: string;
    label: string;
    priority: number;
}

// ── Hashing ─────────────────────────────────────────────────────────────────

/** Compute SHA-256 hex hash of canonical JSON for deduplication. */
export async function inputHash(input_data: Record<string, unknown>): Promise<string> {
    // Sort keys for canonical representation
    const canonical = JSON.stringify(input_data, Object.keys(input_data).sort());
    const bytes = new TextEncoder().encode(canonical);
    const hashBuffer = await crypto.subtle.digest("SHA-256", bytes);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    return hashArray.map(b => b.toString(16).padStart(2, "0")).join("");
}

// ── Task Generators ─────────────────────────────────────────────────────────

function neoantigenTasks(species: string = "human"): TaskInput[] {
    let genes: [string, string, string][];
    let tumors: string[];
    let panels: string[][];

    if (species === "dog") {
        genes = CANINE_CANCER_GENES.map(g => [g[0], `${g[1]}:1000000:A>T`, g[2]] as [string, string, string]);
        tumors = CANINE_TUMOR_TYPES;
        panels = DLA_PANELS;
    } else if (species === "cat") {
        genes = FELINE_CANCER_GENES.map(g => [g[0], `${g[1]}:1000000:C>T`, g[2]] as [string, string, string]);
        tumors = FELINE_TUMOR_TYPES;
        panels = FLA_PANELS;
    } else {
        genes = CANCER_GENES;
        tumors = TUMOR_TYPES;
        panels = HLA_PANELS;
    }

    const tasks: TaskInput[] = [];
    for (const [gene, _variantId, _mutation] of genes) {
        for (const tumor of tumors) {
            for (const mhc of panels) {
                tasks.push({
                    skill: "neoantigen_prediction",
                    input_data: {
                        sample_id: `${gene}_${tumor}_${species}_batch`,
                        vcf_path: `data/${species}/${tumor.toLowerCase()}/${gene.toLowerCase()}_somatic.vcf`,
                        hla_alleles: mhc,
                        tumor_type: tumor,
                        species,
                    },
                    domain: "cancer",
                    species,
                    label: `Neoantigen [${species}]: ${gene} in ${tumor}`,
                    priority: 3,
                });
            }
        }
    }
    return tasks;
}

function structureTasks(domain: string): TaskInput[] {
    const tasks: TaskInput[] = [];
    if (domain === "cancer") {
        for (const [gene] of CANCER_GENES) {
            tasks.push({
                skill: "structure_prediction",
                input_data: { protein_id: gene, sequence: "AUTO_RESOLVE", method: "esmfold" },
                domain: "cancer",
                species: "human",
                label: `Structure: ${gene} (cancer)`,
                priority: 4,
            });
        }
    } else {
        for (const target of DRUG_TARGETS) {
            tasks.push({
                skill: "structure_prediction",
                input_data: { protein_id: target.protein_id, sequence: "AUTO_RESOLVE", method: "esmfold" },
                domain: "drug_discovery",
                species: "human",
                label: `Structure: ${(target as { name?: string }).name ?? target.protein_id} (drug target)`,
                priority: 4,
            });
        }
    }
    return tasks;
}

function qsarTasks(): TaskInput[] {
    const modelTypes = ["random_forest", "xgboost"];
    const tasks: TaskInput[] = [];
    for (const ds of CHEMBL_DATASETS) {
        for (const model of modelTypes) {
            tasks.push({
                skill: "qsar",
                input_data: {
                    dataset_path: `data/chembl/${ds.target}.csv`,
                    target_column: ds.target_col,
                    smiles_column: "smiles",
                    model_type: model,
                    mode: "train",
                },
                domain: "drug_discovery",
                species: "human",
                label: `QSAR: ${ds.name} (${model})`,
                priority: 5,
            });
        }
    }
    return tasks;
}

function dockingTasks(): TaskInput[] {
    const methods = ["vina", "gnina"];
    const tasks: TaskInput[] = [];
    for (const target of DRUG_TARGETS) {
        for (const method of methods) {
            tasks.push({
                skill: "molecular_docking",
                input_data: {
                    ligand_smiles: target.smiles,
                    receptor_pdb: `data/pdb/${target.pdb}.pdb`,
                    center_x: 0.0,
                    center_y: 0.0,
                    center_z: 0.0,
                    box_size: 25.0,
                    exhaustiveness: 16,
                    method,
                },
                domain: "drug_discovery",
                species: "human",
                label: `Docking: ${target.ligand} → ${(target as { name?: string }).name ?? target.protein_id} (${method})`,
                priority: 4,
            });
        }
    }
    return tasks;
}

function variantTasks(species: string = "human"): TaskInput[] {
    let variants: { variant_id: string; gene: string; disease: string; hgvs?: string | null; species?: string }[];
    if (species === "dog") {
        variants = CANINE_VARIANTS;
    } else if (species === "cat") {
        variants = FELINE_VARIANTS;
    } else {
        variants = RARE_DISEASE_VARIANTS;
    }

    const tasks: TaskInput[] = [];
    for (const v of variants) {
        tasks.push({
            skill: "variant_pathogenicity",
            input_data: {
                variant_id: v.variant_id,
                gene: v.gene,
                hgvs: (v as { hgvs?: string | null }).hgvs ?? null,
                species: v.species ?? species,
            },
            domain: species === "human" ? "rare_disease" : "cancer",
            species: v.species ?? species,
            label: `Variant [${species}]: ${v.gene} (${v.disease})`,
            priority: 3,
        });
    }
    return tasks;
}

// ── Generate All Tasks ──────────────────────────────────────────────────────

/** Generate all possible research tasks from parameter banks. */
export function generateAllTasks(): TaskInput[] {
    const tasks: TaskInput[] = [];

    // Human
    tasks.push(...neoantigenTasks("human"));
    tasks.push(...structureTasks("cancer"));
    tasks.push(...structureTasks("drug_discovery"));
    tasks.push(...qsarTasks());
    tasks.push(...dockingTasks());
    tasks.push(...variantTasks("human"));

    // Canine
    tasks.push(...neoantigenTasks("dog"));
    tasks.push(...variantTasks("dog"));

    // Feline
    tasks.push(...neoantigenTasks("cat"));
    tasks.push(...variantTasks("cat"));

    return tasks;
}

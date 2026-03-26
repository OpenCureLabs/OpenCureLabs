/**
 * OpenCure Labs — Task Generation for Central Queue
 *
 * Ported from packages/agentiq_labclaw/agentiq_labclaw/task_generator.py
 * Generates deterministic research tasks from curated parameter banks.
 * Tasks are hashed (SHA-256 of canonical input_data) for deduplication.
 */

// ── Parameter Banks ─────────────────────────────────────────────────────────

export const CANCER_GENES: [string, string, string][] = [
    // ── Tier 1: Top 15 driver genes (priority 3) ────────────────────────────
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
    // ── Tier 2: COSMIC cancer gene census — additional drivers (priority 5) ─
    ["NRAS", "chr1:115256529:T>C", "Q61R"],
    ["HRAS", "chr11:534242:C>A", "G12V"],
    ["CDKN2A", "chr9:21971120:C>T", "R80X"],
    ["RB1", "chr13:48367556:G>A", "R661W"],
    ["NF1", "chr17:31252184:C>T", "R1513X"],
    ["NF2", "chr22:30032805:G>A", "R341X"],
    ["VHL", "chr3:10149920:G>A", "R167Q"],
    ["WT1", "chr11:32413565:C>T", "R394W"],
    ["SMAD4", "chr18:51065525:C>T", "R361H"],
    ["STK11", "chr19:1219400:G>A", "G163D"],
    ["FBXW7", "chr4:152326159:C>T", "R465C"],
    ["NOTCH1", "chr9:139399360:G>A", "P2514L"],
    ["ARID1A", "chr1:26773594:C>T", "R1989X"],
    ["KMT2D", "chr12:49415854:C>T", "R5432X"],
    ["CTNNB1", "chr3:41224610:T>C", "S45P"],
    ["MAP2K1", "chr15:66727455:G>A", "P124L"],
    ["ERBB3", "chr12:56083807:G>A", "V104M"],
    ["ERBB4", "chr2:212498867:G>A", "E317K"],
    ["FLT3", "chr13:28034105:A>G", "D835Y"],
    ["KIT", "chr4:55593464:A>T", "D816V"],
    ["PDGFRA", "chr4:55141055:A>T", "D842V"],
    ["JAK2", "chr9:5073770:G>T", "V617F"],
    ["JAK1", "chr1:64846780:G>A", "V658F"],
    ["ABL1", "chr9:130862949:C>T", "T315I"],
    ["SRC", "chr20:37399349:G>A", "E527K"],
    ["FGFR1", "chr8:38285863:A>G", "N546K"],
    ["FGFR2", "chr10:121520170:C>T", "S252W"],
    ["FGFR4", "chr5:176520243:G>A", "R388W"],
    ["ROS1", "chr6:117642522:G>A", "G2032R"],
    ["NTRK1", "chr1:156874568:G>A", "G595R"],
    ["NTRK3", "chr15:88524924:C>T", "G623R"],
    ["DDR2", "chr1:162685370:G>A", "L63V"],
    ["MTOR", "chr1:11174395:C>T", "S2215Y"],
    ["TSC1", "chr9:132903976:C>T", "R692X"],
    ["TSC2", "chr16:2126314:G>A", "R905W"],
    ["PTCH1", "chr9:98231058:G>A", "R1344X"],
    ["SMO", "chr7:128846308:G>A", "W535L"],
    ["SUFU", "chr10:102526990:C>T", "R123C"],
    ["CTCF", "chr16:67632413:G>A", "R377C"],
    ["DNMT3A", "chr2:25234374:G>A", "R882H"],
    ["TET2", "chr4:105243553:C>T", "Q1034X"],
    ["EZH2", "chr7:148504856:G>A", "Y641N"],
    ["ASXL1", "chr20:31022292:G>T", "G646fs"],
    ["SF3B1", "chr2:197402110:G>A", "K700E"],
    ["U2AF1", "chr21:44513783:C>T", "S34F"],
    ["SRSF2", "chr17:74733099:G>A", "P95H"],
    ["NPM1", "chr5:170837543:C>T", "W288fs"],
    ["RUNX1", "chr21:34788937:G>A", "R174Q"],
    ["GATA3", "chr10:8098509:C>T", "R330fs"],
    ["FOXA1", "chr14:37590985:G>A", "I176M"],
    ["SPOP", "chr17:47701140:G>A", "F133V"],
    ["AR", "chrX:67711614:G>A", "T878A"],
    ["ESR1", "chr6:151842245:G>A", "D538G"],
    ["CCND1", "chr11:69462910:G>A", "P287S"],
    ["MDM2", "chr12:68817124:G>A", "overexp"],
    ["MYC", "chr8:128748315:G>A", "P57S"],
    ["MYCN", "chr2:16110614:G>A", "P44L"],
    ["BCL2", "chr18:63123685:G>A", "overexp"],
    ["MCL1", "chr1:150578425:G>A", "overexp"],
    ["XPO1", "chr2:61496721:G>A", "E571K"],
    ["BTK", "chrX:101360541:G>A", "C481S"],
    ["CARD11", "chr7:2988470:G>A", "L225LI"],
    ["MYD88", "chr3:38141150:T>C", "L265P"],
    ["CD79B", "chr17:63929526:G>A", "Y196H"],
    ["CREBBP", "chr16:3786745:C>T", "R1446H"],
    ["EP300", "chr22:41150648:C>T", "D1399N"],
    ["KMT2A", "chr11:118392508:C>T", "R3765X"],
    ["KMT2C", "chr7:152134282:C>T", "S3589X"],
    ["SETD2", "chr3:47057898:C>T", "R1625X"],
    ["BAP1", "chr3:52443449:G>A", "splice"],
    ["PBRM1", "chr3:52617589:C>T", "E831X"],
    ["SMARCA4", "chr19:11097274:G>A", "R885C"],
    ["SMARCB1", "chr22:24134560:G>A", "R374X"],
    ["SWI_SNF", "chr1:26679610:G>A", "various"],
    ["KEAP1", "chr19:10507331:G>A", "R413L"],
    ["NFE2L2", "chr2:177234308:G>A", "R34P"],
    ["STK11", "chr19:1219400:G>A", "G163D"],
    ["CASP8", "chr2:201262061:C>T", "R248W"],
    ["FAT1", "chr4:186631800:G>A", "various"],
    ["PPP2R1A", "chr19:52228221:C>T", "R183W"],
    ["MAP3K1", "chr5:56174679:G>A", "various"],
    ["MAP3K4", "chr6:162011236:G>A", "various"],
    ["POLE", "chr12:132624261:C>T", "P286R"],
    ["MSH2", "chr2:47630556:G>A", "various"],
    ["MSH6", "chr2:47783412:G>A", "various"],
    ["PMS2", "chr7:6026871:G>A", "various"],
    ["MLH1", "chr3:37089131:G>A", "R226X"],
    ["ATM", "chr11:108202608:C>T", "R3008C"],
    ["ATR", "chr3:142220823:G>A", "various"],
    ["CHEK2", "chr22:28695868:G>A", "I157T"],
    ["BRCA2", "chr13:32911463:T>G", "Y1894X"],
    ["PALB2", "chr16:23641310:G>A", "Y551X"],
    ["RAD51C", "chr17:58698786:G>A", "various"],
    ["CDK6", "chr7:92462464:G>A", "various"],
    ["CDK12", "chr17:39461871:G>A", "various"],
    ["CCNE1", "chr19:29823652:G>A", "overexp"],
    ["TERT", "chr5:1295228:G>A", "promoter"],
    ["ATRX", "chrX:76950471:G>A", "R781X"],
    ["DAXX", "chr6:33286355:G>A", "various"],
    ["CIC", "chr19:42287874:G>A", "R215W"],
    ["FUBP1", "chr1:77933072:G>A", "various"],
    ["KDM5C", "chrX:53220408:G>A", "various"],
    ["KDM6A", "chrX:44873099:G>A", "various"],
    ["PHF6", "chrX:133547574:G>A", "various"],
    ["BCOR", "chrX:39922359:G>A", "various"],
    ["BCORL1", "chrX:129147612:G>A", "various"],
    ["STAG2", "chrX:123197837:G>A", "various"],
    ["RAD21", "chr8:117867834:G>A", "various"],
    ["SMC1A", "chrX:53428147:G>A", "various"],
    ["ZRSR2", "chrX:15828891:G>A", "various"],
    ["TP63", "chr3:189604747:G>A", "various"],
    ["SOX9", "chr17:72121020:G>A", "various"],
    ["MAX", "chr14:65031219:G>A", "various"],
    ["MGA", "chr15:41818854:G>A", "various"],
    ["RNF43", "chr17:58356667:G>A", "G659fs"],
    ["AXIN1", "chr16:393821:G>A", "various"],
    ["APC2", "chr19:1438768:G>A", "various"],
    ["TCF7L2", "chr10:112998590:G>A", "various"],
    ["GNAS", "chr20:58909365:G>A", "R201H"],
    ["GNA11", "chr19:3094019:C>T", "Q209L"],
    ["GNAQ", "chr9:77794572:C>T", "Q209P"],
    ["RAC1", "chr7:6444172:C>T", "P29S"],
    ["RHOA", "chr3:49396789:G>A", "Y42C"],
    ["CDC42", "chr1:22417990:G>A", "various"],
    ["PIK3R1", "chr5:67589149:G>A", "N564D"],
    ["AKT1", "chr14:104780214:G>A", "E17K"],
    ["AKT2", "chr19:40230317:G>A", "various"],
    ["RICTOR", "chr5:38953653:G>A", "various"],
    ["RPTOR", "chr17:78929298:G>A", "various"],
    ["PTPN11", "chr12:112856531:G>A", "E76K"],
    ["SHP2", "chr12:112926261:G>A", "various"],
    ["CBL", "chr11:119148908:G>A", "various"],
    ["CBLB", "chr3:107272093:G>A", "various"],
    ["NRG1", "chr8:31497272:G>A", "fusion"],
    ["ERBB2", "chr17:39724775:A>G", "S310F"],
    ["IGF1R", "chr15:98717498:G>A", "various"],
    ["VEGFA", "chr6:43770209:G>A", "overexp"],
    ["KDR", "chr4:55095264:G>A", "various"],
    ["FGF19", "chr11:69218308:G>A", "amp"],
    ["FGF3", "chr11:69571337:G>A", "amp"],
    ["FGF4", "chr11:69582822:G>A", "amp"],
    ["CCND3", "chr6:41934973:G>A", "various"],
    ["CDK4", "chr12:57747727:G>A", "R24C"],
    ["RBM10", "chrX:47058498:G>A", "various"],
    ["U2AF2", "chr19:55661636:G>A", "various"],
    ["IDH2", "chr15:90088606:C>T", "R140Q"],
    ["SDH_A", "chr5:218356:G>A", "various"],
    ["SDH_B", "chr1:17371320:G>A", "various"],
    ["SDH_C", "chr1:161309956:G>A", "various"],
    ["SDH_D", "chr11:112086955:G>A", "various"],
    ["FH", "chr1:241660836:G>A", "various"],
    ["DICER1", "chr14:95086222:G>A", "D1709N"],
    ["DROSHA", "chr5:31434916:G>A", "various"],
    ["EPHA3", "chr3:89476283:G>A", "various"],
    ["EPHA5", "chr4:65717620:G>A", "various"],
    ["EPHB1", "chr3:134902301:G>A", "various"],
    ["LATS1", "chr6:150001234:G>A", "various"],
    ["LATS2", "chr13:21553421:G>A", "various"],
    ["YAP1", "chr11:102054722:G>A", "overexp"],
    ["TAZ_WWTR1", "chr3:149756116:G>A", "overexp"],
    ["NKX2_1", "chr14:36516869:G>A", "amp"],
    ["SOX2", "chr3:181429690:G>A", "amp"],
    ["PRDM1", "chr6:106117044:G>A", "various"],
    ["IRF4", "chr6:391739:G>A", "various"],
    ["TNFAIP3", "chr6:138197822:G>A", "various"],
    ["B2M", "chr15:44715432:G>A", "various"],
    ["HLA_A", "chr6:29942470:G>A", "LOH"],
    ["HLA_B", "chr6:31353872:G>A", "LOH"],
    ["JAK3", "chr19:17935696:G>A", "various"],
    ["TYK2", "chr19:10350276:G>A", "various"],
    ["STAT3", "chr17:42322400:G>A", "various"],
    ["STAT5B", "chr17:40372999:G>A", "N642H"],
    ["SOCS1", "chr16:11254730:G>A", "various"],
    ["PTPRD", "chr9:8313487:G>A", "various"],
    ["PTPRT", "chr20:41498866:G>A", "various"],
    ["INPP4B", "chr4:143543070:G>A", "various"],
    ["PIK3C2B", "chr1:204424709:G>A", "various"],
    ["PIK3C3", "chr18:39560368:G>A", "various"],
    ["RASA1", "chr5:86602050:G>A", "various"],
    ["NF1", "chr17:31252184:C>T", "R1513X_tier2"],
    ["LZTR1", "chr22:21343727:G>A", "various"],
    ["PPM1D", "chr17:60665028:G>A", "various"],
    ["MUTYH", "chr1:45332396:G>A", "Y179C"],
    ["NTHL1", "chr16:2041822:G>A", "various"],
    ["SMAD2", "chr18:47841769:G>A", "various"],
    ["SMAD3", "chr15:67063400:G>A", "various"],
    ["TGFBR2", "chr3:30713126:G>A", "various"],
    ["ACVR1", "chr2:158384001:G>A", "R206H"],
    ["BMP5", "chr6:55665800:G>A", "various"],
    ["BMPR1A", "chr10:86756617:G>A", "various"],
    ["AMER1", "chrX:63413252:G>A", "various"],
    ["TRRAP", "chr7:98516649:G>A", "various"],
    ["KANSL1", "chr17:46025783:G>A", "various"],
    ["KAT6A", "chr8:41790268:G>A", "various"],
    ["HDAC", "chr1:32757608:G>A", "various"],
    ["SIRT1", "chr10:67884607:G>A", "various"],
    ["BRD4", "chr19:15349216:G>A", "various"],
    ["DOT1L", "chr19:2165047:G>A", "various"],
    ["PRMT5", "chr14:23356050:G>A", "various"],
    ["WRN", "chr8:30890851:G>A", "various"],
    ["BLM", "chr15:90717388:G>A", "various"],
    ["RECQL4", "chr8:144514543:G>A", "various"],
    ["FANCA", "chr16:89805015:G>A", "various"],
    ["FANCD2", "chr3:10068098:G>A", "various"],
    ["RAD50", "chr5:132556339:G>A", "various"],
    ["MRE11", "chr11:94417771:G>A", "various"],
    ["NBN", "chr8:89971435:G>A", "657del5"],
    ["XRCC1", "chr19:43543580:G>A", "various"],
    ["ERCC2", "chr19:45365065:G>A", "various"],
    ["XPC", "chr3:14165356:G>A", "various"],
    ["DDB2", "chr11:47217741:G>A", "various"],
    ["MGMT", "chr10:129467108:G>A", "promoter_meth"],
];

// Tier 1 gene count for priority assignment
const TIER1_GENE_COUNT = 15;

export const TUMOR_TYPES = [
    // Original 10
    "NSCLC", "breast", "colorectal", "melanoma", "glioblastoma",
    "pancreatic", "ovarian", "prostate", "hepatocellular", "renal",
    // TCGA expansion (25 more)
    "SCLC", "head_neck_SCC", "esophageal", "gastric", "cholangiocarcinoma",
    "bladder_urothelial", "cervical", "endometrial", "thyroid_papillary", "thyroid_anaplastic",
    "adrenocortical", "pheochromocytoma", "mesothelioma", "testicular_germ_cell", "thymoma",
    "AML", "CLL", "DLBCL", "multiple_myeloma", "MDS",
    "uveal_melanoma", "sarcoma_UPS", "Ewing_sarcoma", "neuroblastoma", "medulloblastoma",
];

export const HLA_PANELS: string[][] = [
    // ── Original 5 (European common) ────────────────────────────────────────
    ["HLA-A*02:01", "HLA-B*07:02", "HLA-C*07:02"],
    ["HLA-A*01:01", "HLA-B*08:01", "HLA-C*07:01"],
    ["HLA-A*03:01", "HLA-B*44:03", "HLA-C*04:01"],
    ["HLA-A*24:02", "HLA-B*35:01", "HLA-C*04:01"],
    ["HLA-A*11:01", "HLA-B*15:01", "HLA-C*03:04"],
    // ── European extended ───────────────────────────────────────────────────
    ["HLA-A*02:01", "HLA-B*44:02", "HLA-C*05:01"],
    ["HLA-A*01:01", "HLA-B*57:01", "HLA-C*06:02"],
    ["HLA-A*03:01", "HLA-B*07:02", "HLA-C*07:02"],
    ["HLA-A*29:02", "HLA-B*44:03", "HLA-C*16:01"],
    ["HLA-A*02:01", "HLA-B*15:01", "HLA-C*03:03"],
    // ── East Asian ──────────────────────────────────────────────────────────
    ["HLA-A*24:02", "HLA-B*52:01", "HLA-C*12:02"],
    ["HLA-A*33:03", "HLA-B*58:01", "HLA-C*03:02"],
    ["HLA-A*11:01", "HLA-B*46:01", "HLA-C*01:02"],
    ["HLA-A*02:07", "HLA-B*46:01", "HLA-C*01:02"],
    ["HLA-A*24:02", "HLA-B*07:02", "HLA-C*07:02"],
    ["HLA-A*02:01", "HLA-B*13:01", "HLA-C*03:04"],
    ["HLA-A*33:03", "HLA-B*44:03", "HLA-C*14:03"],
    ["HLA-A*26:01", "HLA-B*40:02", "HLA-C*03:04"],
    ["HLA-A*02:06", "HLA-B*51:01", "HLA-C*14:02"],
    ["HLA-A*31:01", "HLA-B*15:01", "HLA-C*03:03"],
    // ── African ─────────────────────────────────────────────────────────────
    ["HLA-A*30:01", "HLA-B*42:01", "HLA-C*17:01"],
    ["HLA-A*23:01", "HLA-B*07:02", "HLA-C*07:02"],
    ["HLA-A*02:02", "HLA-B*53:01", "HLA-C*04:01"],
    ["HLA-A*68:02", "HLA-B*15:03", "HLA-C*02:10"],
    ["HLA-A*30:02", "HLA-B*18:01", "HLA-C*05:01"],
    ["HLA-A*23:01", "HLA-B*49:01", "HLA-C*07:01"],
    ["HLA-A*74:01", "HLA-B*15:10", "HLA-C*03:04"],
    ["HLA-A*66:01", "HLA-B*58:02", "HLA-C*06:02"],
    ["HLA-A*34:02", "HLA-B*44:03", "HLA-C*04:01"],
    ["HLA-A*02:01", "HLA-B*45:01", "HLA-C*16:01"],
    // ── South Asian ─────────────────────────────────────────────────────────
    ["HLA-A*11:01", "HLA-B*40:06", "HLA-C*15:05"],
    ["HLA-A*01:01", "HLA-B*35:03", "HLA-C*04:01"],
    ["HLA-A*02:11", "HLA-B*40:01", "HLA-C*15:02"],
    ["HLA-A*33:01", "HLA-B*44:03", "HLA-C*07:01"],
    ["HLA-A*24:02", "HLA-B*07:05", "HLA-C*15:05"],
    // ── Americas / Indigenous ───────────────────────────────────────────────
    ["HLA-A*02:01", "HLA-B*39:01", "HLA-C*07:02"],
    ["HLA-A*24:02", "HLA-B*35:12", "HLA-C*04:01"],
    ["HLA-A*02:01", "HLA-B*40:02", "HLA-C*03:05"],
    ["HLA-A*68:01", "HLA-B*39:06", "HLA-C*07:02"],
    ["HLA-A*31:01", "HLA-B*35:01", "HLA-C*04:01"],
    // ── Middle Eastern ──────────────────────────────────────────────────────
    ["HLA-A*02:01", "HLA-B*50:01", "HLA-C*06:02"],
    ["HLA-A*01:01", "HLA-B*51:01", "HLA-C*14:02"],
    ["HLA-A*26:01", "HLA-B*38:01", "HLA-C*12:03"],
    ["HLA-A*03:01", "HLA-B*35:01", "HLA-C*04:01"],
    ["HLA-A*68:01", "HLA-B*18:01", "HLA-C*07:01"],
    // ── Oceanian ────────────────────────────────────────────────────────────
    ["HLA-A*34:01", "HLA-B*56:01", "HLA-C*01:02"],
    ["HLA-A*24:02", "HLA-B*40:01", "HLA-C*04:03"],
    ["HLA-A*11:01", "HLA-B*56:02", "HLA-C*01:02"],
    ["HLA-A*02:01", "HLA-B*15:21", "HLA-C*04:01"],
    ["HLA-A*24:02", "HLA-B*13:01", "HLA-C*03:04"],
];

export const DRUG_TARGETS = [
    // ── Original 10 targets ─────────────────────────────────────────────────
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
    // ── Kinase inhibitor targets ────────────────────────────────────────────
    { protein_id: "FGFR1", pdb: "5A46", ligand: "erdafitinib", smiles: "CC(Oc1cc(Nc2ncc(C#N)c(-c3ccc(N4CCNCC4)cc3)n2)ccc1F)C(F)(F)F" },
    { protein_id: "FGFR2", pdb: "1EV2", ligand: "futibatinib", smiles: "CC(C)(O)c1cc(-c2ccn[nH]2)cc(NC(=O)/C=C/CN(C)C)c1" },
    { protein_id: "FGFR3", pdb: "4K33", ligand: "infigratinib", smiles: "Cc1cc(OC(F)(F)F)ccc1-c1cc(Nc2ncc(Cl)c(Nc3ccccc3S(=O)(=O)C(C)C)n2)ccn1" },
    { protein_id: "RET", pdb: "7JU6", ligand: "selpercatinib", smiles: "CC(C)(O)CNc1ncc(-c2cccc3[nH]c(-c4ccccn4)nc23)c(F)c1F" },
    { protein_id: "MET", pdb: "3LQ8", ligand: "capmatinib", smiles: "CN1CC(Nc2ncc3cc(-c4c(F)cccc4F)c(=O)n3n2)C1" },
    { protein_id: "ROS1", pdb: "3ZBF", ligand: "entrectinib", smiles: "CN(C)C(=O)c1cc(-c2ccc3ncc(-c4cccc(F)c4)n3n2)cc(F)c1F" },
    { protein_id: "NTRK1", pdb: "4YNE", ligand: "larotrectinib", smiles: "OC1CCN(c2cc(-c3cnn4ncccc34)nc3ccsc23)C1" },
    { protein_id: "SRC", pdb: "2SRC", ligand: "dasatinib", smiles: "Cc1nc(Nc2ncc(C(=O)Nc3c(C)cccc3Cl)s2)cc(N2CCN(CCO)CC2)n1" },
    { protein_id: "KIT", pdb: "1T46", ligand: "avapritinib", smiles: "C1=CC=C(CCNC2=NC3=CC=C(F)C=C3N2C2=CC=CC=C2)C=C1" },
    { protein_id: "PDGFRA", pdb: "5K5X", ligand: "ripretinib", smiles: "CC(NC(=O)c1cc(C(F)(F)F)nn1-c1ccc(Cl)cc1Cl)c1cccc(-c2ccn[nH]2)c1" },
    // ── CDK / cell cycle targets ────────────────────────────────────────────
    { protein_id: "CDK6", pdb: "1BI7", ligand: "ribociclib", smiles: "CN(C)C(=O)c1cc2cnc(Nc3ccc(N4CCNCC4)cn3)nc2n1C1CCCC1" },
    { protein_id: "CDK12", pdb: "5ACB", ligand: "THZ531", smiles: "C=CC(=O)Nc1cc(Nc2nc(N3CCN(C)CC3)ncc2C#N)c(OC)cc1OC" },
    { protein_id: "CDK2", pdb: "1PXI", ligand: "dinaciclib", smiles: "CCC(CO)Nc1nc2cc(-c3cnc4ccccc4c3)ccn2c1=O" },
    { protein_id: "CDK9", pdb: "3BLR", ligand: "AZD4573", smiles: "CC(NC(=O)c1ccc2[nH]ncc2c1)c1nc(-c2ccccn2)cs1" },
    { protein_id: "AURKA", pdb: "2J4Z", ligand: "alisertib", smiles: "COc1cc(OC)c(Nc2c3c(nc4ccccc24)C(=O)N(C3=O)c2ccccc2)cc1F" },
    // ── PI3K-AKT-mTOR pathway ───────────────────────────────────────────────
    { protein_id: "PIK3CB", pdb: "4BFR", ligand: "AZD8186", smiles: "CC(C)NC(=O)N1CCC(n2nc(-c3ccc(F)cc3)c3c(N)ncnc32)CC1" },
    { protein_id: "PIK3CD", pdb: "4XE0", ligand: "idelalisib", smiles: "CCC(Nc1ncnc2c1nc(-c1cccc(F)c1)n2C1CC(O)C1)c1nc2ccccc2[nH]1" },
    { protein_id: "AKT1", pdb: "4GV1", ligand: "capivasertib", smiles: "Cl.OC1CCN(C(=O)C2CC(N)C2)C1c1cc(-c2cccc(Cl)c2)nc(N)n1" },
    { protein_id: "MTOR", pdb: "4DRI", ligand: "everolimus", smiles: "COc1cc(CCC=C(/C)CC(OC)C(O)CC(=O)C(/C=C/c2coc(CC)c2C)C.OC(=O)C)ccc1OC" },
    { protein_id: "MTORC1", pdb: "5WBH", ligand: "sapanisertib", smiles: "CC(C)(O)Cc1cc2cccc(NC(=O)c3cc(OC(F)(F)F)ccn3)c2[nH]1" },
    // ── MAPK/RAS pathway ────────────────────────────────────────────────────
    { protein_id: "KRAS_G12C", pdb: "6OIM", ligand: "sotorasib", smiles: "C=CC(=O)N1CCN(c2nc(OCC)nc3c2CC(C)(C)C3=O)CC1c1c(Cl)ccc(F)c1F" },
    { protein_id: "KRAS_G12D", pdb: "7RPZ", ligand: "MRTX1133", smiles: "CC1CC(C)N(c2nc(N)nc3c(F)c(Cl)c(-c4cc(O)c(F)cc4F)cc23)C1" },
    { protein_id: "MEK1", pdb: "3EQI", ligand: "trametinib", smiles: "CC(=O)Nc1cccc(-n2c(=O)c3cc(F)c(I)cc3c(=O)c3cc(NC(=O)C4CC(F)(F)CC4)ccc32)c1" },
    { protein_id: "MEK2", pdb: "1S9J", ligand: "binimetinib", smiles: "CC(=O)Nc1cccc(-n2c(=O)c3cc(F)ccc3c(=O)[nH]c2=O)c1" },
    { protein_id: "ERK2", pdb: "6GDQ", ligand: "ulixertinib", smiles: "CC(Nc1ncc(-c2cccc(Cl)c2F)c(-c2ccnc(NC3CC3)n2)n1)c1ccccc1" },
    { protein_id: "SHP2", pdb: "6MDC", ligand: "TNO155", smiles: "CC(C)(O)c1cc(F)c(-c2ccnc(N3CCC(F)(F)C3)n2)cc1Cl" },
    // ── Epigenetic targets ──────────────────────────────────────────────────
    { protein_id: "EZH2", pdb: "4MI5", ligand: "tazemetostat", smiles: "CCN(c1cc(-c2ccc(CN3CCOCC3)cc2)c(C)nn1)c1c(C)cc(C)nc1C" },
    { protein_id: "BET_BRD4", pdb: "3MXF", ligand: "JQ1", smiles: "CC1=NN(c2ccc(Cl)cc2)C(=O)/C1=C/c1cccs1" },
    { protein_id: "HDAC1", pdb: "5ICN", ligand: "vorinostat", smiles: "ONC(=O)/C=C/c1ccc(CNC(=O)c2ccccc2)cc1" },
    { protein_id: "DOT1L", pdb: "3QOW", ligand: "pinometostat", smiles: "CC(C)(C)NC(=O)c1cc(-c2cccc(NS(C)(=O)=O)c2)c[nH]1" },
    { protein_id: "DNMT3A", pdb: "6F57", ligand: "decitabine", smiles: "Nc1ncn(C2OC(CO)C(O)C2O)c(=O)n1" },
    { protein_id: "IDH1_R132H", pdb: "5TQH", ligand: "ivosidenib", smiles: "CC(NC(=O)c1cccc(C(F)(F)F)c1)C1(c2cccnc2)NC(=O)C(C)(C)N1" },
    { protein_id: "IDH2_R140Q", pdb: "5I96", ligand: "enasidenib", smiles: "CC(C)(O)CNc1nc(NCc2ccc(F)cc2F)c2nncn2n1" },
    // ── Nuclear hormone receptors ───────────────────────────────────────────
    { protein_id: "AR", pdb: "2AXA", ligand: "enzalutamide", smiles: "CNC(=O)c1ccc(-n2c(-c3ccc(C#N)c(C(F)(F)F)c3)nc3cc(F)ccc32)cc1" },
    { protein_id: "ESR1", pdb: "1ERE", ligand: "fulvestrant", smiles: "CC12CCC3c4ccc(O)cc4CCC3C1CCC2O" },
    { protein_id: "ESR1_D538G", pdb: "6PSJ", ligand: "elacestrant", smiles: "CC(C)(O)c1ccc(-c2cc3ccc(O)cc3c(C3CCCCC3)n2)cc1" },
    // ── Immune checkpoint targets ───────────────────────────────────────────
    { protein_id: "PD1", pdb: "5B8C", ligand: "pembrolizumab_epitope", smiles: "PEPTIDE" },
    { protein_id: "CTLA4", pdb: "1I8L", ligand: "ipilimumab_epitope", smiles: "PEPTIDE" },
    { protein_id: "LAG3", pdb: "7TZG", ligand: "relatlimab_epitope", smiles: "PEPTIDE" },
    { protein_id: "TIGIT", pdb: "3UCR", ligand: "tiragolumab_epitope", smiles: "PEPTIDE" },
    { protein_id: "TIM3", pdb: "5F71", ligand: "cobolimab_epitope", smiles: "PEPTIDE" },
    // ── Apoptosis targets ───────────────────────────────────────────────────
    { protein_id: "BCL2", pdb: "6O0K", ligand: "venetoclax", smiles: "CC1(C)CCC(CN2CCN(c3ccc(C(=O)NS(=O)(=O)c4ccc(NCC5CCOCC5)c(S(=O)(=O)C(F)(F)F)c4)cc3)CC2)=C(c2ccc(Cl)cc2)C1" },
    { protein_id: "MCL1", pdb: "6QFI", ligand: "AMG176", smiles: "CC(C)(C)c1c(Cl)cc(CN2C(=O)c3ccccc3C2=O)cc1Cl" },
    { protein_id: "XIAP", pdb: "2JK7", ligand: "ASTX660", smiles: "CC(NC(=O)C1CCCN1C(=O)C(NC(=O)c1cc(Cl)cc(Cl)c1)C(C)C)c1cccc(F)c1" },
    // ── WNT / developmental ─────────────────────────────────────────────────
    { protein_id: "TNKS", pdb: "3KR8", ligand: "XAV939", smiles: "CC(=O)NC1=NN(c2ccc(C(F)(F)F)cc2)C(=O)/C1=C\\c1cccs1" },
    { protein_id: "PORCN", pdb: "MODEL", ligand: "LGK974", smiles: "CC(=O)c1cc(-c2ccc(NC(=O)c3cc(F)cc(F)c3)cn2)ccn1" },
    { protein_id: "SMO", pdb: "4JKV", ligand: "vismodegib", smiles: "CS(=O)(=O)c1ccc(C(Cl)c2cc(Cl)c(Cl)cc2Cl)cc1" },
    // ── DNA damage repair ───────────────────────────────────────────────────
    { protein_id: "PARP2", pdb: "4TVJ", ligand: "niraparib", smiles: "NC(=O)c1cc(-c2ccc3[nH]ncc3c2)c2CCNCC2[nH]1" },
    { protein_id: "ATR", pdb: "5YZ0", ligand: "ceralasertib", smiles: "CC1(C)CNCC(NCc2cc(-c3cnc4cc(OC(F)F)ccc4n3)ccc2OC)O1" },
    { protein_id: "WEE1", pdb: "5V5Y", ligand: "adavosertib", smiles: "CC(=O)Nc1cccc(-n2c(=O)n(-c3ccc(F)cc3F)c3cnc4ccccc4c32)c1" },
    { protein_id: "CHK1", pdb: "2E9P", ligand: "prexasertib", smiles: "O=c1[nH]c2ccccc2c2c(-c3cccc(NS(=O)(=O)C4CC4)c3)n[nH]c12" },
    { protein_id: "POLQ", pdb: "MODEL", ligand: "novobiocin", smiles: "COc1c(O)c2oc(C3CC(O)(C(N)=O)C(OC4OC(C)C(OC(=O)c5cc(-c6ccc(O)cc6)oc5C)C(OC)C4O)CC3C)cc(=O)c2c(O)c1C" },
    // ── Protein degradation (PROTAC / glue) ─────────────────────────────────
    { protein_id: "CRBN", pdb: "4CI1", ligand: "lenalidomide", smiles: "Nc1cccc2c1CN(C1CCC(=O)NC1=O)C2=O" },
    { protein_id: "VHL", pdb: "4W9H", ligand: "VH032", smiles: "CC(C)(C)OC(=O)NC(C(=O)NC1CC(O)CC1O)C(C)(C)C" },
    { protein_id: "DCAF15", pdb: "6SJ7", ligand: "indisulam", smiles: "NS(=O)(=O)c1ccc(N2CCCCC2)c(Cl)c1" },
    // ── Splicing targets ────────────────────────────────────────────────────
    { protein_id: "SF3B1", pdb: "5IFE", ligand: "H3B8800", smiles: "CC(C)C(NC(=O)c1cc(OC)c(OC)c(OC)c1)C(=O)NC1CCCC1O" },
    { protein_id: "CLK2", pdb: "6FYL", ligand: "T025", smiles: "Cc1cc(NC(=O)c2cccc(-c3ccnc4ccccc34)c2)no1" },
    // ── RTK / FLT3 / VEGFR ──────────────────────────────────────────────────
    { protein_id: "FLT3", pdb: "4XUF", ligand: "gilteritinib", smiles: "CC(C)(C)c1nc(-c2ccc(NCc3ccccn3)cc2)c2c(N)ncc(-c3cccnc3NC3CC3)c2n1" },
    { protein_id: "VEGFR2", pdb: "1YWN", ligand: "lenvatinib", smiles: "COc1cc2nccc(Oc3ccc(NC(=O)NC4CC4)c(Cl)c3)c2cc1C(N)=O" },
    { protein_id: "IGF1R", pdb: "1K3A", ligand: "linsitinib", smiles: "Cc1cc(Nc2nccc(-c3c[nH]c4ncccc34)n2)ccc1N1CCNCC1" },
    { protein_id: "AXL", pdb: "5U6B", ligand: "bemcentinib", smiles: "CC(C)Oc1cccc(-c2cc3c(N4CCC(N5CCN(C)CC5)CC4)ncnc3[nH]2)c1" },
    // ── KRAS variants ───────────────────────────────────────────────────────
    { protein_id: "KRAS_G13D", pdb: "6USX", ligand: "MRTX_exp", smiles: "CC1CC(NC(=O)c2cc(F)cnc2N)CN1C(=O)c1cnc2ccccc2c1" },
    { protein_id: "KRAS_G12V", pdb: "7RPZ", ligand: "experimental_1", smiles: "CC(NC(=O)c1cccc(C(F)(F)F)c1)c1c(F)ccc(-c2cnc3ccccc3n2)c1" },
    { protein_id: "HRAS_G12V", pdb: "5P21", ligand: "experimental_2", smiles: "CC(C)(C)NC(=O)c1ccc(-c2c[nH]c(=O)c3ccccc23)cc1" },
    // ── Transcription factor targets ────────────────────────────────────────
    { protein_id: "STAT3", pdb: "6NJS", ligand: "TTI101", smiles: "COc1ccc(S(=O)(=O)N(CC(=O)O)c2ccc(Cl)cc2)cc1OC" },
    { protein_id: "MYC_MAX", pdb: "1NKP", ligand: "MYCi975", smiles: "CC1=CC(=O)c2cc(O)ccc2O1" },
    { protein_id: "FOXM1", pdb: "MODEL", ligand: "FDI6", smiles: "O=C1NC2=CC=CC=C2C1=CC1=CC=C(S(=O)(=O)N2CCOCC2)C=C1" },
    // ── Inflammatory / JAK-STAT ─────────────────────────────────────────────
    { protein_id: "JAK1", pdb: "6N7A", ligand: "upadacitinib", smiles: "CCC(=O)N1CCCC1C(=O)Nc1cnn(-c2cc(C3CCC(F)(F)C3)nc(N)n2)c1" },
    { protein_id: "JAK3", pdb: "3LXK", ligand: "tofacitinib", smiles: "CC1CCN(C(=O)CC#N)CC1N(C)c1ncnc2[nH]ccc12" },
    { protein_id: "TYK2", pdb: "6NZP", ligand: "deucravacitinib", smiles: "CC(C)NC(=O)c1c[nH]c2ncnc(N3CCC(NC(C)(C)C(N)=O)CC3)c12" },
    // ── Metabolic / rare disease targets ────────────────────────────────────
    { protein_id: "PCSK9", pdb: "3BPS", ligand: "inclisiran_target", smiles: "PEPTIDE" },
    { protein_id: "GCase_GBA", pdb: "1OGS", ligand: "miglustat", smiles: "CCCCN1CC(O)C(O)C(O)C1CO" },
    { protein_id: "CFTR_G551D", pdb: "6MSM", ligand: "ivacaftor", smiles: "CC(C)(C)c1cc(NC(=O)c2cnc3[nH]c(=O)ccc3c2O)cc(C(C)(C)C)c1O" },
    { protein_id: "HTT", pdb: "MODEL", ligand: "branaplam", smiles: "C1=CC=C(CN2C=NC3=CC(NC4=CC=C(N5CCCC5=O)C=C4)=CC=C32)C=C1" },
    { protein_id: "SMN2", pdb: "MODEL", ligand: "risdiplam", smiles: "Cn1nc(-c2cccc(-c3cn4c(C5(N)CCC5)cccc4n3)c2F)cc1C" },
    // ── Additional validated targets ────────────────────────────────────────
    { protein_id: "XPO1", pdb: "4GPT", ligand: "selinexor", smiles: "CC(=O)/N=N/C(=O)c1cc(cc(c1)C(F)(F)F)N1CCNCC1" },
    { protein_id: "PRMT5", pdb: "5C9Z", ligand: "GSK3326595", smiles: "CC(NC(=O)c1cc(-c2cccc(Cl)c2)nn1C)C(O)C(F)(F)F" },
    { protein_id: "STING", pdb: "6DXL", ligand: "diABZI", smiles: "CC(C)(C)c1cc(NC(=O)c2n[nH]c3ccccc23)cc(C(C)(C)C)c1O" },
    { protein_id: "CGAS", pdb: "6MJW", ligand: "RU.521", smiles: "O=c1[nH]c2ccccc2c2ccnc(-c3cccc(O)c3O)c12" },
    { protein_id: "HPK1", pdb: "7JWI", ligand: "experimental_hpk1", smiles: "CC1=CC=C(NC(=O)C2=CC=C(C3=CC=NN3C)C=C2)C=C1" },
    { protein_id: "TEAD", pdb: "5EMV", ligand: "K975", smiles: "CC(=O)NC1=CC=C(C(=O)C2=CC=CC(F)=C2)C=C1" },
    { protein_id: "USP7", pdb: "5NGE", ligand: "FT671", smiles: "CC1=C(C#N)C(NC2=CC=CC=C2Cl)=NC(SCC(=O)NC3CCCC3)=N1" },
    { protein_id: "ENPP1", pdb: "6WFJ", ligand: "RBS2418", smiles: "O=C(NC1CCNCC1)c1ccc(Oc2ccc(C(F)(F)F)cc2)cc1" },
    { protein_id: "CD47", pdb: "5TZN", ligand: "magrolimab_epitope", smiles: "PEPTIDE" },
    { protein_id: "SIRPA", pdb: "2WNG", ligand: "TTI621_epitope", smiles: "PEPTIDE" },
];

export const CHEMBL_DATASETS = [
    // ── Original 10 ─────────────────────────────────────────────────────────
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
    // ── Kinase panel ────────────────────────────────────────────────────────
    { name: "FGFR1_IC50", target: "CHEMBL3650", target_col: "pIC50" },
    { name: "FGFR2_IC50", target: "CHEMBL4142", target_col: "pIC50" },
    { name: "FGFR3_IC50", target: "CHEMBL2635", target_col: "pIC50" },
    { name: "RET_IC50", target: "CHEMBL2185", target_col: "pIC50" },
    { name: "MET_IC50", target: "CHEMBL3717", target_col: "pIC50" },
    { name: "ROS1_IC50", target: "CHEMBL5568", target_col: "pIC50" },
    { name: "SRC_IC50", target: "CHEMBL267", target_col: "pIC50" },
    { name: "KIT_IC50", target: "CHEMBL1936", target_col: "pIC50" },
    { name: "PDGFRA_IC50", target: "CHEMBL2007", target_col: "pIC50" },
    { name: "FLT3_IC50", target: "CHEMBL1974", target_col: "pIC50" },
    { name: "VEGFR2_IC50", target: "CHEMBL279", target_col: "pIC50" },
    { name: "AXL_IC50", target: "CHEMBL4722", target_col: "pIC50" },
    { name: "IGF1R_IC50", target: "CHEMBL1957", target_col: "pIC50" },
    // ── CDK/cell cycle ──────────────────────────────────────────────────────
    { name: "CDK6_IC50", target: "CHEMBL2508", target_col: "pIC50" },
    { name: "CDK2_IC50", target: "CHEMBL301", target_col: "pIC50" },
    { name: "CDK9_IC50", target: "CHEMBL3038", target_col: "pIC50" },
    { name: "CDK12_IC50", target: "CHEMBL4523", target_col: "pIC50" },
    { name: "AURKA_IC50", target: "CHEMBL4722", target_col: "pIC50" },
    // ── Epigenetic ──────────────────────────────────────────────────────────
    { name: "EZH2_IC50", target: "CHEMBL3286", target_col: "pIC50" },
    { name: "HDAC1_IC50", target: "CHEMBL325", target_col: "pIC50" },
    { name: "BRD4_IC50", target: "CHEMBL1163125", target_col: "pIC50" },
    { name: "DOT1L_IC50", target: "CHEMBL1795126", target_col: "pIC50" },
    { name: "PRMT5_IC50", target: "CHEMBL6164", target_col: "pIC50" },
    { name: "IDH1_IC50", target: "CHEMBL4523063", target_col: "pIC50" },
    { name: "IDH2_IC50", target: "CHEMBL5655", target_col: "pIC50" },
    // ── PI3K-AKT-mTOR ───────────────────────────────────────────────────────
    { name: "PIK3CB_IC50", target: "CHEMBL3145", target_col: "pIC50" },
    { name: "PIK3CD_IC50", target: "CHEMBL3130", target_col: "pIC50" },
    { name: "AKT1_IC50", target: "CHEMBL4282", target_col: "pIC50" },
    // ── MAPK/ERK ────────────────────────────────────────────────────────────
    { name: "KRAS_binding", target: "CHEMBL6080", target_col: "pIC50" },
    { name: "MEK1_IC50", target: "CHEMBL6162", target_col: "pIC50" },
    { name: "ERK2_IC50", target: "CHEMBL4040", target_col: "pIC50" },
    { name: "SHP2_IC50", target: "CHEMBL3864", target_col: "pIC50" },
    // ── JAK-STAT ────────────────────────────────────────────────────────────
    { name: "JAK1_IC50", target: "CHEMBL2835", target_col: "pIC50" },
    { name: "JAK3_IC50", target: "CHEMBL2148", target_col: "pIC50" },
    { name: "TYK2_IC50", target: "CHEMBL3905", target_col: "pIC50" },
    // ── Apoptosis / BCL2 ────────────────────────────────────────────────────
    { name: "BCL2_IC50", target: "CHEMBL4860", target_col: "pIC50" },
    { name: "MCL1_IC50", target: "CHEMBL4361", target_col: "pIC50" },
    // ── DNA repair ──────────────────────────────────────────────────────────
    { name: "PARP2_IC50", target: "CHEMBL6150", target_col: "pIC50" },
    { name: "ATR_IC50", target: "CHEMBL6166", target_col: "pIC50" },
    { name: "WEE1_IC50", target: "CHEMBL5543", target_col: "pIC50" },
    { name: "CHK1_IC50", target: "CHEMBL4338", target_col: "pIC50" },
    // ── Immune / STING ──────────────────────────────────────────────────────
    { name: "STING_EC50", target: "CHEMBL4523070", target_col: "pEC50" },
    { name: "cGAS_IC50", target: "CHEMBL4630297", target_col: "pIC50" },
    // ── AR / ESR1 ───────────────────────────────────────────────────────────
    { name: "AR_IC50", target: "CHEMBL1871", target_col: "pIC50" },
    { name: "ESR1_IC50", target: "CHEMBL206", target_col: "pIC50" },
];

export const RARE_DISEASE_VARIANTS = [
    // ── Original 15 ─────────────────────────────────────────────────────────
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
    // ── Lysosomal storage disorders ─────────────────────────────────────────
    { variant_id: "chrX:100653428:G>A", gene: "GLA", hgvs: "p.Arg227Gln", disease: "Fabry disease" },
    { variant_id: "chr1:155235870:C>T", gene: "GBA", hgvs: "p.Leu444Pro", disease: "Gaucher disease type 2" },
    { variant_id: "chr14:88443236:G>A", gene: "GALC", hgvs: "p.Thr513Met", disease: "Krabbe disease" },
    { variant_id: "chr5:88907545:G>A", gene: "HEXB", hgvs: "p.Pro417Leu", disease: "Sandhoff disease" },
    { variant_id: "chr15:72638892:G>A", gene: "HEXA", hgvs: "p.Arg178His", disease: "Tay-Sachs disease" },
    { variant_id: "chr17:78082258:G>A", gene: "GAA", hgvs: "p.Asp645Glu", disease: "Pompe disease" },
    { variant_id: "chr3:72940861:G>A", gene: "GNPTAB", hgvs: "p.Arg587Ter", disease: "Mucolipidosis II" },
    { variant_id: "chr4:988143:G>A", gene: "IDUA", hgvs: "p.Trp402Ter", disease: "Hurler syndrome" },
    { variant_id: "chrX:148586130:G>A", gene: "IDS", hgvs: "p.Arg468Trp", disease: "Hunter syndrome" },
    { variant_id: "chr17:78489620:G>A", gene: "NAGLU", hgvs: "p.Arg565Trp", disease: "Sanfilippo B" },
    { variant_id: "chr12:39312230:G>A", gene: "HGSNAT", hgvs: "p.Arg344Cys", disease: "Sanfilippo C" },
    { variant_id: "chr3:33091737:G>A", gene: "GLB1", hgvs: "p.Arg482His", disease: "GM1 gangliosidosis" },
    { variant_id: "chr11:6615910:G>A", gene: "TPP1", hgvs: "p.Arg208Ter", disease: "CLN2 disease" },
    { variant_id: "chr1:40757291:G>A", gene: "PPT1", hgvs: "p.Arg151Ter", disease: "CLN1 disease" },
    { variant_id: "chr16:71489814:G>A", gene: "CLN3", hgvs: null, disease: "CLN3 disease" },
    { variant_id: "chr14:70108698:G>A", gene: "SMPD1", hgvs: "p.Arg496Leu", disease: "Niemann-Pick A" },
    { variant_id: "chr18:23528860:G>A", gene: "NPC1", hgvs: "p.Ile1061Thr", disease: "Niemann-Pick C" },
    { variant_id: "chr10:88635779:G>A", gene: "LIPA", hgvs: "p.Glu8SJter", disease: "Wolman disease" },
    { variant_id: "chr12:109586048:G>A", gene: "GNPTG", hgvs: "p.Arg66Ter", disease: "Mucolipidosis III" },
    // ── Metabolic disorders ─────────────────────────────────────────────────
    { variant_id: "chr12:103234254:G>A", gene: "PAH", hgvs: "p.Arg408Trp", disease: "Phenylketonuria" },
    { variant_id: "chr12:103311124:G>A", gene: "PAH", hgvs: "p.Ile65Thr", disease: "PKU (mild)" },
    { variant_id: "chr15:75046887:G>A", gene: "OTC", hgvs: "p.Arg277Trp", disease: "OTC deficiency" },
    { variant_id: "chr9:34648842:G>A", gene: "ASS1", hgvs: "p.Gly390Arg", disease: "Citrullinemia I" },
    { variant_id: "chr7:117559593:G>A", gene: "CFTR", hgvs: "p.Phe508del", disease: "Cystic fibrosis (ΔF508)" },
    { variant_id: "chr7:117587811:G>A", gene: "CFTR", hgvs: "p.Arg117His", disease: "CF (mild)" },
    { variant_id: "chr17:80084719:G>A", gene: "GALK1", hgvs: "p.Gln188Arg", disease: "Galactosemia" },
    { variant_id: "chr9:104195397:G>A", gene: "GALT", hgvs: "p.Gln188Arg", disease: "Classic galactosemia" },
    { variant_id: "chr19:48580652:G>A", gene: "GPI", hgvs: "p.Arg472Cys", disease: "GPI deficiency" },
    { variant_id: "chr11:67352689:G>A", gene: "PCCA", hgvs: "p.Ala138Thr", disease: "Propionic acidemia" },
    { variant_id: "chr3:135936366:G>A", gene: "PCCB", hgvs: "p.Arg410Trp", disease: "Propionic acidemia B" },
    { variant_id: "chr6:49395689:G>A", gene: "MUT", hgvs: "p.Arg369His", disease: "Methylmalonic acidemia" },
    { variant_id: "chr21:43804048:G>A", gene: "CBS", hgvs: "p.Ile278Thr", disease: "Homocystinuria (CBS)" },
    { variant_id: "chr3:150928104:G>A", gene: "AGXT", hgvs: "p.Gly170Arg", disease: "Primary hyperoxaluria I" },
    { variant_id: "chr9:34082342:G>A", gene: "GRHPR", hgvs: "p.Gly165Asp", disease: "Primary hyperoxaluria II" },
    { variant_id: "chr10:101558034:G>A", gene: "ABCC2", hgvs: "p.Cys1515Tyr", disease: "Dubin-Johnson syndrome" },
    // ── Connective tissue / skeletal ────────────────────────────────────────
    { variant_id: "chr2:189839099:G>A", gene: "COL3A1", hgvs: "p.Gly373Ser", disease: "Ehlers-Danlos vascular" },
    { variant_id: "chr7:94024297:G>A", gene: "COL1A2", hgvs: "p.Gly346Cys", disease: "OI type II" },
    { variant_id: "chr17:48275370:G>A", gene: "COL1A1", hgvs: "p.Gly253Cys", disease: "OI type III" },
    { variant_id: "chr15:48760839:G>A", gene: "FBN1", hgvs: "p.Arg1137Pro", disease: "Marfan syndrome" },
    { variant_id: "chr15:48704217:G>A", gene: "FBN1", hgvs: "p.Cys1039Tyr", disease: "Marfan (neonatal)" },
    { variant_id: "chr2:220285509:G>A", gene: "FBN2", hgvs: "p.Gly1488Asp", disease: "Congenital contractural arachnodactyly" },
    { variant_id: "chr5:149360554:G>A", gene: "SLC26A2", hgvs: "p.Arg279Trp", disease: "Diastrophic dysplasia" },
    { variant_id: "chr4:1804392:G>A", gene: "FGFR3", hgvs: "p.Gly380Arg", disease: "Achondroplasia" },
    { variant_id: "chr4:1804407:G>A", gene: "FGFR3", hgvs: "p.Lys650Met", disease: "Thanatophoric dysplasia II" },
    { variant_id: "chr12:21356599:G>A", gene: "SLCO1B1", hgvs: "p.Val174Ala", disease: "Statin myopathy risk" },
    // ── Hematologic disorders ───────────────────────────────────────────────
    { variant_id: "chr11:5248234:G>A", gene: "HBB", hgvs: "p.Glu6Lys", disease: "Hemoglobin C" },
    { variant_id: "chr11:5225464:G>A", gene: "HBB", hgvs: null, disease: "Beta thalassemia major" },
    { variant_id: "chr16:173245:G>A", gene: "HBA1", hgvs: null, disease: "Alpha thalassemia" },
    { variant_id: "chr1:169549811:G>A", gene: "F5", hgvs: "p.Arg506Gln", disease: "Factor V Leiden" },
    { variant_id: "chr11:46739505:G>A", gene: "F2", hgvs: "p.G20210A", disease: "Prothrombin thrombophilia" },
    { variant_id: "chrX:154064063:G>A", gene: "F8", hgvs: null, disease: "Hemophilia A" },
    { variant_id: "chrX:139530733:G>A", gene: "F9", hgvs: "p.Arg180Gln", disease: "Hemophilia B" },
    { variant_id: "chr12:6018900:G>A", gene: "VWF", hgvs: "p.Arg1306Trp", disease: "Von Willebrand type 2B" },
    { variant_id: "chr1:228097478:G>A", gene: "WAS", hgvs: "p.Arg86Cys", disease: "Wiskott-Aldrich syndrome" },
    { variant_id: "chr17:38471572:G>A", gene: "RARA", hgvs: "t(15;17)", disease: "APL" },
    // ── Neurological / neurodegenerative ────────────────────────────────────
    { variant_id: "chr21:26929620:G>A", gene: "APP", hgvs: "p.Val717Ile", disease: "Early-onset Alzheimer" },
    { variant_id: "chr14:73136402:G>A", gene: "PSEN1", hgvs: "p.Ala431Glu", disease: "Familial Alzheimer" },
    { variant_id: "chr1:227073090:G>A", gene: "PSEN2", hgvs: "p.Asn141Ile", disease: "Familial Alzheimer 4" },
    { variant_id: "chr4:89993420:G>A", gene: "SNCA", hgvs: "p.Ala53Thr", disease: "Familial Parkinson" },
    { variant_id: "chr1:155235843:G>T", gene: "GBA", hgvs: "p.Asn370Ser", disease: "Parkinson risk (GBA)" },
    { variant_id: "chr12:40702911:G>A", gene: "LRRK2", hgvs: "p.Arg1441Gly", disease: "Familial Parkinson (LRRK2)" },
    { variant_id: "chr21:31850318:G>A", gene: "SOD1", hgvs: "p.Ala4Val", disease: "ALS1" },
    { variant_id: "chr9:27573534:G>A", gene: "C9orf72", hgvs: null, disease: "ALS/FTD (repeat expansion)" },
    { variant_id: "chr16:31190952:G>A", gene: "FUS", hgvs: "p.Arg521Cys", disease: "ALS6" },
    { variant_id: "chr1:11082596:G>A", gene: "TARDBP", hgvs: "p.Met337Val", disease: "ALS10" },
    { variant_id: "chr9:135139838:G>A", gene: "TSC1", hgvs: "p.Arg692Ter", disease: "Tuberous sclerosis 1" },
    { variant_id: "chr16:2126314:G>A", gene: "TSC2", hgvs: "p.Arg905Trp", disease: "Tuberous sclerosis 2" },
    { variant_id: "chr3:10183842:G>A", gene: "VHL", hgvs: "p.Arg167Gln", disease: "Von Hippel-Lindau" },
    { variant_id: "chr22:29999545:G>A", gene: "NF2", hgvs: "p.Arg57Ter", disease: "Neurofibromatosis 2" },
    { variant_id: "chr17:31252184:C>T", gene: "NF1", hgvs: "p.Arg1947Ter", disease: "Neurofibromatosis 1" },
    { variant_id: "chr5:112175770:G>A", gene: "APC", hgvs: "p.Arg1450Ter", disease: "Familial adenomatous polyposis" },
    // ── Cardiac / channelopathies ───────────────────────────────────────────
    { variant_id: "chr14:23425370:G>A", gene: "MYH7", hgvs: "p.Arg403Gln", disease: "Hypertrophic cardiomyopathy" },
    { variant_id: "chr11:47354409:G>A", gene: "MYBPC3", hgvs: "p.Arg502Trp", disease: "HCM type 4" },
    { variant_id: "chr15:35086899:G>A", gene: "SCN5A", hgvs: "p.Arg1623Gln", disease: "Brugada syndrome" },
    { variant_id: "chr7:150654119:G>A", gene: "KCNH2", hgvs: "p.Ala561Val", disease: "Long QT syndrome 2" },
    { variant_id: "chr11:2466220:G>A", gene: "KCNQ1", hgvs: "p.Arg190Trp", disease: "Long QT syndrome 1" },
    { variant_id: "chr3:38592923:G>A", gene: "SCN5A", hgvs: "p.Glu1784Lys", disease: "Long QT syndrome 3" },
    { variant_id: "chr1:237890317:G>A", gene: "RYR2", hgvs: "p.Arg4497Cys", disease: "CPVT" },
    { variant_id: "chr14:23854529:G>A", gene: "MYH7", hgvs: "p.Arg719Trp", disease: "Dilated cardiomyopathy" },
    { variant_id: "chr10:121430280:G>A", gene: "LMNA", hgvs: "p.Arg190Trp", disease: "LMNA cardiomyopathy" },
    { variant_id: "chr10:112572778:G>A", gene: "RBM20", hgvs: "p.Arg634Gln", disease: "DCM (RBM20)" },
    { variant_id: "chr1:237781637:G>A", gene: "FLNC", hgvs: "p.Arg1621His", disease: "Restrictive cardiomyopathy" },
    // ── Immunodeficiency / immune ───────────────────────────────────────────
    { variant_id: "chrX:70360952:G>A", gene: "BTK", hgvs: "p.Arg525Gln", disease: "X-linked agamma" },
    { variant_id: "chr20:10626700:G>A", gene: "ADA", hgvs: "p.Arg211His", disease: "ADA-SCID" },
    { variant_id: "chrX:70328852:G>A", gene: "IL2RG", hgvs: null, disease: "X-SCID" },
    { variant_id: "chr11:5320629:G>A", gene: "RAG1", hgvs: "p.Arg474Cys", disease: "Omenn syndrome" },
    { variant_id: "chr11:36597606:G>A", gene: "RAG2", hgvs: "p.Arg229Gln", disease: "SCID (RAG2)" },
    { variant_id: "chr8:90967711:G>A", gene: "NBN", hgvs: "p.657del5", disease: "Nijmegen breakage" },
    { variant_id: "chr10:88635779:G>A", gene: "DCLRE1C", hgvs: null, disease: "Artemis SCID" },
    { variant_id: "chr22:37460859:G>A", gene: "AIRE", hgvs: "p.Arg257Ter", disease: "APECED" },
    { variant_id: "chr2:204738151:G>A", gene: "ICOS", hgvs: null, disease: "ICOS deficiency" },
    { variant_id: "chr1:160564580:G>A", gene: "CD247", hgvs: null, disease: "T-cell deficiency" },
    // ── Endocrine / renal ───────────────────────────────────────────────────
    { variant_id: "chr19:49206674:G>A", gene: "GYS1", hgvs: "p.Arg462Gln", disease: "Glycogen storage 0" },
    { variant_id: "chr17:42418413:G>A", gene: "G6PC", hgvs: "p.Arg83Cys", disease: "GSD Ia" },
    { variant_id: "chr1:155162426:G>A", gene: "GBA", hgvs: "p.Asp409His", disease: "Gaucher type 3" },
    { variant_id: "chr12:48366748:G>A", gene: "AQP2", hgvs: "p.Arg254Leu", disease: "Nephrogenic DI" },
    { variant_id: "chrX:153170408:G>A", gene: "AVPR2", hgvs: "p.Arg181Cys", disease: "X-linked NDI" },
    { variant_id: "chr16:2097370:G>A", gene: "PKD1", hgvs: "p.Arg3277Cys", disease: "ADPKD type 1" },
    { variant_id: "chr4:88024063:G>A", gene: "PKD2", hgvs: "p.Arg803Trp", disease: "ADPKD type 2" },
    { variant_id: "chr6:170165006:G>A", gene: "PKHD1", hgvs: "p.Thr36Met", disease: "ARPKD" },
    { variant_id: "chr2:31750512:G>A", gene: "SLC3A1", hgvs: "p.Met467Thr", disease: "Cystinuria type A" },
    { variant_id: "chr19:32989406:G>A", gene: "SLC7A9", hgvs: "p.Arg333Trp", disease: "Cystinuria type B" },
    // ── Ophthalmologic ──────────────────────────────────────────────────────
    { variant_id: "chrX:38145540:G>A", gene: "RPGR", hgvs: null, disease: "X-linked RP" },
    { variant_id: "chr1:94458994:G>A", gene: "RPE65", hgvs: "p.Arg91Trp", disease: "Leber congenital amaurosis" },
    { variant_id: "chr6:65532765:G>A", gene: "EYS", hgvs: "p.Tyr3156Ter", disease: "RP type 25" },
    { variant_id: "chr14:21756456:G>A", gene: "RPGRIP1", hgvs: "p.Arg827Ter", disease: "Leber congenital amaurosis 6" },
    { variant_id: "chr5:178420825:G>A", gene: "GRK1", hgvs: "p.Met1Ile", disease: "Oguchi disease" },
    { variant_id: "chr4:15989857:G>A", gene: "RD3", hgvs: null, disease: "Leber congenital amaurosis 12" },
    { variant_id: "chr17:7903571:G>A", gene: "GUCY2D", hgvs: "p.Arg838Cys", disease: "Leber congenital amaurosis 1" },
    { variant_id: "chr2:219756339:G>A", gene: "USH2A", hgvs: "p.Cys759Phe", disease: "Usher syndrome 2A" },
    { variant_id: "chr11:17204929:G>A", gene: "MYO7A", hgvs: "p.Arg244Pro", disease: "Usher syndrome 1B" },
    { variant_id: "chr10:71792369:G>A", gene: "CDH23", hgvs: "p.Arg1746Trp", disease: "Usher syndrome 1D" },
    // ── Muscular / neuromuscular ────────────────────────────────────────────
    { variant_id: "chrX:31117274:G>A", gene: "DMD", hgvs: null, disease: "Duchenne muscular dystrophy" },
    { variant_id: "chrX:31174073:G>A", gene: "DMD", hgvs: null, disease: "Becker muscular dystrophy" },
    { variant_id: "chr5:70049543:G>A", gene: "SMN1", hgvs: null, disease: "Spinal muscular atrophy" },
    { variant_id: "chr19:45770205:G>A", gene: "DMPK", hgvs: null, disease: "Myotonic dystrophy 1" },
    { variant_id: "chr3:128891420:G>A", gene: "CNBP", hgvs: null, disease: "Myotonic dystrophy 2" },
    { variant_id: "chr17:80168895:G>A", gene: "SGCA", hgvs: "p.Arg77Cys", disease: "LGMD2D" },
    { variant_id: "chr4:52790665:G>A", gene: "SGCB", hgvs: "p.Ser114Phe", disease: "LGMD2E" },
    { variant_id: "chr13:23345483:G>A", gene: "SGCG", hgvs: null, disease: "LGMD2C" },
    { variant_id: "chr5:155777805:G>A", gene: "SGCD", hgvs: "p.Arg97Gln", disease: "LGMD2F" },
    { variant_id: "chr2:71837756:G>A", gene: "DYSF", hgvs: "p.Arg555Trp", disease: "Miyoshi myopathy" },
    { variant_id: "chr19:50886550:G>A", gene: "RYR1", hgvs: "p.Arg614Cys", disease: "Malignant hyperthermia" },
    { variant_id: "chr9:116226505:G>A", gene: "POMT1", hgvs: "p.Ala200Pro", disease: "Walker-Warburg syndrome" },
    // ── Hearing loss ────────────────────────────────────────────────────────
    { variant_id: "chr13:20133146:G>A", gene: "GJB2", hgvs: "p.35delG", disease: "DFNB1 hearing loss" },
    { variant_id: "chr13:20133116:G>A", gene: "GJB2", hgvs: "p.Met34Thr", disease: "DFNB1 (mild)" },
    { variant_id: "chr13:20761746:G>A", gene: "GJB6", hgvs: null, disease: "DFNB1 (del GJB6)" },
    { variant_id: "chr7:127254587:G>A", gene: "SLC26A4", hgvs: "p.Leu236Pro", disease: "Pendred syndrome" },
    { variant_id: "chr3:136143190:G>A", gene: "STRC", hgvs: null, disease: "DFNB16" },
    // ── Dermatologic ────────────────────────────────────────────────────────
    { variant_id: "chr12:49012400:G>A", gene: "KRT1", hgvs: "p.Asn171Ser", disease: "Epidermolytic hyperkeratosis" },
    { variant_id: "chr17:39721140:G>A", gene: "KRT14", hgvs: "p.Arg125Cys", disease: "EBS Dowling-Meara" },
    { variant_id: "chr3:189618814:G>A", gene: "COL7A1", hgvs: "p.Arg2063Trp", disease: "Dystrophic EB" },
    { variant_id: "chr10:33521750:G>A", gene: "KIF11", hgvs: "p.Arg519Ter", disease: "MCLMR syndrome" },
    { variant_id: "chr1:212480626:G>A", gene: "LAMB3", hgvs: null, disease: "Junctional EB" },
    // ── Mitochondrial / energy ──────────────────────────────────────────────
    { variant_id: "chrM:3243:A>G", gene: "MT-TL1", hgvs: "m.3243A>G", disease: "MELAS" },
    { variant_id: "chrM:8344:A>G", gene: "MT-TK", hgvs: "m.8344A>G", disease: "MERRF" },
    { variant_id: "chrM:11778:G>A", gene: "MT-ND4", hgvs: "m.11778G>A", disease: "Leber optic neuropathy" },
    { variant_id: "chrM:8993:T>G", gene: "MT-ATP6", hgvs: "m.8993T>G", disease: "NARP" },
    { variant_id: "chr15:89859516:G>A", gene: "POLG", hgvs: "p.Trp748Ser", disease: "Alpers syndrome" },
    { variant_id: "chr4:39239942:G>A", gene: "DGUOK", hgvs: "p.Arg47Gln", disease: "Mito DNA depletion (hepatocerebral)" },
    { variant_id: "chr2:74706479:G>A", gene: "TK2", hgvs: "p.Arg183Trp", disease: "Mito DNA depletion (myopathic)" },
    { variant_id: "chr22:41547932:G>A", gene: "TYMP", hgvs: "p.Gly145Arg", disease: "MNGIE" },
    // ── Cancer predisposition syndromes ─────────────────────────────────────
    { variant_id: "chr17:43094464:G>A", gene: "BRCA1", hgvs: "p.185delAG", disease: "Hereditary breast-ovarian" },
    { variant_id: "chr13:32890572:G>A", gene: "BRCA2", hgvs: "p.6174delT", disease: "Hereditary breast-ovarian 2" },
    { variant_id: "chr2:47641560:G>A", gene: "MSH2", hgvs: "p.Arg711Ter", disease: "Lynch syndrome 1" },
    { variant_id: "chr2:47783412:G>A", gene: "MSH6", hgvs: "p.Phe1088fs", disease: "Lynch syndrome 5" },
    { variant_id: "chr7:5997299:G>A", gene: "PMS2", hgvs: "p.Arg134Ter", disease: "Lynch syndrome 4" },
    { variant_id: "chr10:87933147:C>T", gene: "PTEN", hgvs: "p.Arg130Ter", disease: "Cowden syndrome" },
    { variant_id: "chr17:12122965:G>A", gene: "TP53", hgvs: "p.Arg248Trp", disease: "Li-Fraumeni syndrome" },
    { variant_id: "chr13:48367556:G>A", gene: "RB1", hgvs: "p.Arg661Trp", disease: "Retinoblastoma" },
    { variant_id: "chr11:32413565:G>A", gene: "WT1", hgvs: "p.Arg394Trp", disease: "Wilms tumor predisposition" },
    { variant_id: "chr9:21971120:G>A", gene: "CDKN2A", hgvs: "p.Arg80Ter", disease: "Familial melanoma" },
    // ── Pharmacogenomics panels ─────────────────────────────────────────────
    { variant_id: "chr22:42524947:G>A", gene: "CYP2D6", hgvs: "*4", disease: "PM codeine/tamoxifen" },
    { variant_id: "chr10:94781859:G>A", gene: "CYP2C19", hgvs: "*2", disease: "PM clopidogrel" },
    { variant_id: "chr10:94942290:G>A", gene: "CYP2C9", hgvs: "*2", disease: "PM warfarin" },
    { variant_id: "chr16:31107689:G>A", gene: "VKORC1", hgvs: "c.-1639G>A", disease: "Warfarin sensitivity" },
    { variant_id: "chr19:15990431:G>A", gene: "CYP2B6", hgvs: "*6", disease: "PM efavirenz" },
    { variant_id: "chr7:87160618:G>A", gene: "ABCB1", hgvs: "p.Ile1145Ile", disease: "Drug transport polymorphism" },
    { variant_id: "chr10:94761900:G>A", gene: "CYP2C19", hgvs: "*17", disease: "UM clopidogrel" },
    { variant_id: "chr5:75047426:G>A", gene: "DPYD", hgvs: "*2A", disease: "5-FU toxicity" },
    { variant_id: "chr6:18139230:G>A", gene: "TPMT", hgvs: "*3A", disease: "Thiopurine toxicity" },
    { variant_id: "chr1:97915614:G>A", gene: "DPYD", hgvs: "p.Asp949Val", disease: "5-FU intermediate" },
    // ── Additional rare diseases ────────────────────────────────────────────
    { variant_id: "chr16:3293396:G>A", gene: "CREBBP", hgvs: "p.Arg1378Pro", disease: "Rubinstein-Taybi" },
    { variant_id: "chr12:112036730:G>A", gene: "PTPN11", hgvs: "p.Asn308Asp", disease: "Noonan syndrome" },
    { variant_id: "chr3:12625100:G>A", gene: "RAF1", hgvs: "p.Ser257Leu", disease: "Noonan syndrome 5" },
    { variant_id: "chr7:34301950:G>A", gene: "BMPR1A", hgvs: "p.Arg443Cys", disease: "Juvenile polyposis" },
    { variant_id: "chr18:51065525:G>A", gene: "SMAD4", hgvs: "p.Arg361His", disease: "JP-HHT" },
    { variant_id: "chr9:98231058:G>A", gene: "PTCH1", hgvs: "p.Gln852Ter", disease: "Gorlin syndrome" },
    { variant_id: "chr12:103311099:G>A", gene: "PAH", hgvs: "p.Arg252Trp", disease: "Classic PKU" },
    { variant_id: "chr6:152129077:G>A", gene: "ESR1", hgvs: "p.Tyr537Ser", disease: "Estrogen resistance" },
    { variant_id: "chr3:41266113:G>A", gene: "CTNNB1", hgvs: "p.Ser33Cys", disease: "Familial hepatoblastoma" },
    { variant_id: "chr11:64573516:G>A", gene: "MEN1", hgvs: "p.Arg415Ter", disease: "Multiple endocrine neoplasia 1" },
    { variant_id: "chr10:43609944:G>A", gene: "RET", hgvs: "p.Met918Thr", disease: "MEN2B" },
    { variant_id: "chr10:43595968:G>A", gene: "RET", hgvs: "p.Cys634Arg", disease: "MEN2A" },
    { variant_id: "chr3:10191471:G>A", gene: "VHL", hgvs: "p.Tyr98His", disease: "VHL syndrome type 2" },
    { variant_id: "chr22:29091856:G>A", gene: "CHEK2", hgvs: "p.Ile157Thr", disease: "CHEK2 cancer predisposition" },
    { variant_id: "chr16:23646243:G>A", gene: "PALB2", hgvs: "p.1592delT", disease: "PALB2 breast cancer" },
    { variant_id: "chr17:59763347:G>A", gene: "BRIP1", hgvs: "p.Arg798Ter", disease: "Fanconi anemia J" },
    { variant_id: "chr17:56811690:G>A", gene: "RAD51C", hgvs: null, disease: "Fanconi anemia O" },
    { variant_id: "chr16:68771195:G>A", gene: "CDH1", hgvs: "p.Arg598Ter", disease: "Hereditary diffuse gastric cancer" },
    { variant_id: "chr19:1219400:G>A", gene: "STK11", hgvs: "p.Gly163Asp", disease: "Peutz-Jeghers syndrome" },
    { variant_id: "chr2:215674110:G>A", gene: "BARD1", hgvs: "p.Arg658Cys", disease: "Breast cancer risk (BARD1)" },
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
    // Expanded canine panel
    ["PIK3CA", "chr27", "H1047R", "mammary_tumor"],
    ["EGFR", "chr18", "L858R", "nasal_carcinoma"],
    ["KRAS", "chr9", "G12D", "lung_carcinoma"],
    ["APC", "chr3", "R1450X", "colorectal_adenoma"],
    ["SETD2", "chr37", "R1625X", "histiocytic_sarcoma"],
    ["CDKN2A", "chr11", "del", "melanoma"],
    ["MDM2", "chr10", "amp", "osteosarcoma"],
    ["RB1", "chr22", "R661W", "osteosarcoma"],
    ["MYC", "chr13", "amp", "lymphoma"],
    ["BCL2", "chr1", "overexp", "lymphoma"],
];

export const FELINE_CANCER_GENES: [string, string, string, string][] = [
    ["KIT", "chrB1", "exon11", "mast_cell_tumor"],
    ["TP53", "chrE2", "R248W", "mammary_carcinoma"],
    ["PDGFRA", "chrB3", "D842V", "mast_cell_tumor"],
    ["NRAS", "chrF2", "Q61R", "lymphoma"],
    ["BRCA1", "chrB1", "various", "mammary_tumor"],
    ["MYC", "chrA3", "various", "lymphoma"],
    // Expanded feline panel
    ["BRAF", "chrD1", "V595E", "intestinal_lymphoma"],
    ["PIK3CA", "chrA1", "H1047R", "mammary_carcinoma"],
    ["ERBB2", "chrE1", "amp", "mammary_carcinoma"],
    ["KRAS", "chrC2", "G12V", "SCC"],
    ["PTEN", "chrB4", "R130Q", "vaccine_site_sarcoma"],
    ["APC", "chrA2", "R1450X", "intestinal_adenocarcinoma"],
];

export const CANINE_TUMOR_TYPES = [
    "mast_cell_tumor", "osteosarcoma", "lymphoma",
    "mammary_tumor", "melanoma", "hemangiosarcoma",
    "transitional_cell_carcinoma", "soft_tissue_sarcoma",
    // Expanded
    "histiocytic_sarcoma", "nasal_carcinoma", "lung_carcinoma",
    "anal_sac_adenocarcinoma", "thyroid_carcinoma", "hepatocellular_carcinoma",
];

export const FELINE_TUMOR_TYPES = [
    "mammary_carcinoma", "mast_cell_tumor", "lymphoma",
    "squamous_cell_carcinoma", "vaccine_site_sarcoma",
    // Expanded
    "intestinal_lymphoma", "intestinal_adenocarcinoma", "oral_SCC",
    "nasal_lymphoma", "hepatic_lymphoma",
];

export const DLA_PANELS: string[][] = [
    ["DLA-88*501:01", "DLA-88*508:01", "DLA-12*001:01"],
    ["DLA-88*502:01", "DLA-88*503:01", "DLA-64*001:01"],
    ["DLA-88*506:01", "DLA-88*511:01", "DLA-12*002:01"],
    ["DLA-88*508:02", "DLA-88*515:01", "DLA-64*002:01"],
    ["DLA-88*501:01", "DLA-88*516:01", "DLA-12*001:01"],
    // Expanded DLA panels
    ["DLA-88*504:01", "DLA-88*509:01", "DLA-12*003:01"],
    ["DLA-88*507:01", "DLA-88*512:01", "DLA-64*003:01"],
    ["DLA-88*510:01", "DLA-88*513:01", "DLA-12*004:01"],
    ["DLA-88*505:01", "DLA-88*514:01", "DLA-64*004:01"],
    ["DLA-88*517:01", "DLA-88*518:01", "DLA-12*005:01"],
];

export const FLA_PANELS: string[][] = [
    ["FLA-K*001", "FLA-K*002"],
    ["FLA-1600*001", "FLA-K*001"],
    ["FLA-K*003", "FLA-1600*002"],
    // Expanded FLA panels
    ["FLA-K*004", "FLA-1600*003"],
    ["FLA-K*005", "FLA-K*006"],
    ["FLA-1600*004", "FLA-K*007"],
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
    // Expanded canine variants
    { variant_id: "chr27:14500210:G>A", gene: "PIK3CA", disease: "Mammary tumor", species: "dog" },
    { variant_id: "chr18:23100345:G>A", gene: "EGFR", disease: "Nasal carcinoma", species: "dog" },
    { variant_id: "chr9:45200120:G>A", gene: "KRAS", disease: "Lung carcinoma", species: "dog" },
    { variant_id: "chr37:8900234:G>A", gene: "SETD2", disease: "Histiocytic sarcoma", species: "dog" },
    { variant_id: "chr11:12340567:G>A", gene: "CDKN2A", disease: "Melanoma", species: "dog" },
    { variant_id: "chr10:88900123:G>A", gene: "MDM2", disease: "Osteosarcoma", species: "dog" },
    { variant_id: "chr22:33400890:G>A", gene: "RB1", disease: "Osteosarcoma", species: "dog" },
    { variant_id: "chr13:44500120:G>A", gene: "MYC", disease: "Lymphoma", species: "dog" },
    { variant_id: "chr1:55600789:G>A", gene: "BCL2", disease: "Lymphoma", species: "dog" },
];

export const FELINE_VARIANTS = [
    { variant_id: "chrB1:41200123:G>T", gene: "KIT", disease: "Mast cell tumor", species: "cat" },
    { variant_id: "chrE2:29823456:G>A", gene: "TP53", disease: "Mammary carcinoma", species: "cat" },
    { variant_id: "chrB3:15023890:A>G", gene: "PDGFRA", disease: "Mast cell tumor", species: "cat" },
    { variant_id: "chrF2:12340500:C>T", gene: "NRAS", disease: "Lymphoma", species: "cat" },
    { variant_id: "chrB1:44500321:C>T", gene: "BRCA1", disease: "Mammary tumor", species: "cat" },
    // Expanded feline variants
    { variant_id: "chrD1:22300456:G>A", gene: "BRAF", disease: "Intestinal lymphoma", species: "cat" },
    { variant_id: "chrA1:33100789:G>A", gene: "PIK3CA", disease: "Mammary carcinoma", species: "cat" },
    { variant_id: "chrE1:11200345:G>A", gene: "ERBB2", disease: "Mammary carcinoma", species: "cat" },
    { variant_id: "chrC2:44300567:G>A", gene: "KRAS", disease: "SCC", species: "cat" },
    { variant_id: "chrB4:55400123:G>A", gene: "PTEN", disease: "Vaccine-site sarcoma", species: "cat" },
    { variant_id: "chrA2:66500234:G>A", gene: "APC", disease: "Intestinal adenocarcinoma", species: "cat" },
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
    for (let geneIdx = 0; geneIdx < genes.length; geneIdx++) {
        const [gene, _variantId, _mutation] = genes[geneIdx];
        // Tier 1 genes (first 15 in human, first 10 in dog, first 6 in cat) get priority 3
        const isTier1 = species === "human" ? geneIdx < TIER1_GENE_COUNT
            : species === "dog" ? geneIdx < 10
                : geneIdx < 6;
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
                    priority: isTier1 ? 3 : 5,
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
    const modelTypes = ["random_forest", "xgboost", "gnn"];
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
    const methods = ["vina", "gnina", "diffdock"];
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
    // Use concat instead of push(...spread) to avoid stack overflow with 400K+ items
    let tasks: TaskInput[] = [];

    // Human
    tasks = tasks.concat(neoantigenTasks("human"));
    tasks = tasks.concat(structureTasks("cancer"));
    tasks = tasks.concat(structureTasks("drug_discovery"));
    tasks = tasks.concat(qsarTasks());
    tasks = tasks.concat(dockingTasks());
    tasks = tasks.concat(variantTasks("human"));

    // Canine
    tasks = tasks.concat(neoantigenTasks("dog"));
    tasks = tasks.concat(variantTasks("dog"));

    // Feline
    tasks = tasks.concat(neoantigenTasks("cat"));
    tasks = tasks.concat(variantTasks("cat"));

    return tasks;
}

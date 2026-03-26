"""Helper module to generate random test samples for LIMS mock emulator."""

import random
import string
import uuid
from datetime import datetime, timezone

# GIAB NA12878 paired-end FASTQ files (public AWS genomics dataset)
# These are real files that HealthOmics can process.
_GIAB_FASTQ_BASE = "s3://aws-genomics-static-us-east-1/omics-tutorials/data/fastq/NA12878/Sample_U0a"
_GIAB_FASTQ_PAIRS = [
    (f"{_GIAB_FASTQ_BASE}/U0a_CGATGT_L001_R1_001.fastq.gz",
     f"{_GIAB_FASTQ_BASE}/U0a_CGATGT_L001_R2_001.fastq.gz"),
    (f"{_GIAB_FASTQ_BASE}/U0a_CGATGT_L001_R1_002.fastq.gz",
     f"{_GIAB_FASTQ_BASE}/U0a_CGATGT_L001_R2_002.fastq.gz"),
    (f"{_GIAB_FASTQ_BASE}/U0a_CGATGT_L001_R1_003.fastq.gz",
     f"{_GIAB_FASTQ_BASE}/U0a_CGATGT_L001_R2_003.fastq.gz"),
    (f"{_GIAB_FASTQ_BASE}/U0a_CGATGT_L001_R1_004.fastq.gz",
     f"{_GIAB_FASTQ_BASE}/U0a_CGATGT_L001_R2_004.fastq.gz"),
]

# Sample data pools for realistic generation
PROJECT_PREFIXES = ["PROJ", "STUDY", "TRIAL", "EXP", "RES"]
SAMPLE_PREFIXES = ["SAM", "SPL", "BIO", "DNA", "RNA"]
DOMAINS = ["research.org", "biolab.edu", "genomics.com", "hospital.org", "university.edu"]
FIRST_NAMES = ["alice", "bob", "charlie", "diana", "edward", "fiona", "george", "helen"]
LAST_NAMES = ["smith", "jones", "wilson", "brown", "taylor", "anderson", "thomas", "jackson"]


def _random_id(prefix: str, length: int = 6) -> str:
    """Generate a random ID with given prefix."""
    suffix = "".join(random.choices(string.digits, k=length))
    return f"{prefix}-{suffix}"


def _random_email() -> str:
    """Generate a random submitter email."""
    first = random.choice(FIRST_NAMES)
    last = random.choice(LAST_NAMES)
    domain = random.choice(DOMAINS)
    return f"{first}.{last}@{domain}"


def generate_sample(bucket_name: str) -> dict:
    """
    Generate a single random test sample using real GIAB NA12878 FASTQ files.

    Args:
        bucket_name: S3 bucket name (unused - kept for API compatibility).
                     FASTQ paths always point to real GIAB public data.

    Returns:
        dict: Complete LIMS payload ready for submission
    """
    project_id = _random_id(random.choice(PROJECT_PREFIXES))
    sample_id = _random_id(random.choice(SAMPLE_PREFIXES))
    patient_id = f"PAT-{uuid.uuid4().hex[:12].upper()}"
    r1, r2 = random.choice(_GIAB_FASTQ_PAIRS)

    return {
        "source": "ClarityLIMS_Mock",
        "event_type": "analysis.requested",
        "data": {
            "project_id": project_id,
            "sample_id": sample_id,
            "patient_id": patient_id,
            "submitter_email": _random_email(),
            "fastq_paths": {"r1": r1, "r2": r2},
            "reference_genome": "GRCh38",
            "analysis_type": random.choice(["WGS", "WES"])
        }
    }


def generate_batch(count: int, bucket_name: str) -> list:
    """
    Generate a batch of random test samples.

    Args:
        count: Number of samples to generate
        bucket_name: S3 bucket name (unused - kept for API compatibility)

    Returns:
        list: List of LIMS payloads ready for submission
    """
    return [generate_sample(bucket_name) for _ in range(count)]


# ============================================================================
# Organization-specific sample generation (for Register Samples tab)
# ============================================================================

ORG_TEMPLATES = {
    "ORG-ACME": {
        "prefix": "ACME",
        "projects": [
            {
                "id": "Rare-Disease-Dx-2026",
                "code": "RD",
                "type": "WGS",
                "genome": "GRCh38",
                "descriptions": [
                    "Rare disease trio - proband",
                    "Rare disease trio - sibling",
                    "Rare disease trio - mother",
                    "Rare disease trio - father",
                    "Rare disease proband - seizure disorder",
                    "Rare disease proband - developmental delay",
                ],
            },
            {
                "id": "Clinical-WES-Validation",
                "code": "CL",
                "type": "WES",
                "genome": "hg38",
                "descriptions": [
                    "Clinical exome - carrier screening",
                    "Clinical exome - hereditary cardiac panel",
                    "Clinical exome - BRCA validation",
                    "Clinical exome - pharmacogenomics",
                ],
            },
        ],
        "patient_prefix": "PAT-ACME",
    },
    "ORG-BIOCORP": {
        "prefix": "BIO",
        "projects": [
            {
                "id": "Immuno-Oncology-T2026",
                "code": "IO",
                "type": "WES",
                "genome": "GRCh38",
                "descriptions": [
                    "Melanoma tumor biopsy",
                    "NSCLC tumor biopsy",
                    "Melanoma matched normal - blood",
                    "Checkpoint inhibitor response biopsy",
                ],
            },
            {
                "id": "Tumor-Profiling-Panel",
                "code": "TP",
                "type": "PANEL",
                "genome": "hg38",
                "descriptions": [
                    "Colorectal cancer panel",
                    "Breast cancer panel",
                    "Lung adenocarcinoma panel",
                    "Pancreatic cancer panel",
                ],
            },
        ],
        "patient_prefix": "PAT-BIO",
    },
    "ORG-UNIVERSITY": {
        "prefix": "UNI",
        "projects": [
            {
                "id": "PGx-Pharmacogenomics",
                "code": "PG",
                "type": "WES",
                "genome": "GRCh38",
                "descriptions": [
                    "CYP2D6 metabolizer status",
                    "Warfarin dose-response",
                    "CYP2C19 rapid metabolizer",
                    "Statin pharmacogenomics",
                ],
            },
            {
                "id": "Population-WGS-Cohort",
                "code": "POP",
                "type": "WGS",
                "genome": "GRCh38",
                "descriptions": [
                    "Population cohort - East Asian",
                    "Population cohort - European",
                    "Population cohort - African",
                    "Population cohort - South Asian",
                    "Population cohort - Americas",
                ],
            },
        ],
        "patient_prefix": "PAT-UNI",
    },
}

# Generic template for unknown organizations
_GENERIC_TEMPLATE = {
    "prefix": "GEN",
    "projects": [
        {
            "id": "General-Sequencing",
            "code": "GS",
            "type": "WGS",
            "genome": "GRCh38",
            "descriptions": [
                "Whole genome sequencing sample",
                "Genomic analysis sample",
                "Sequencing validation sample",
            ],
        },
    ],
    "patient_prefix": "PAT-GEN",
}


def generate_sample_for_org(org_id: str, submitter_email: str) -> dict:
    """Generate a single sample based on organization-specific templates.

    Args:
        org_id: Organization ID (e.g., 'ORG-ACME')
        submitter_email: Email of the submitter

    Returns:
        dict: Flat sample payload ready for POST /lims/samples
    """
    template = ORG_TEMPLATES.get(org_id, _GENERIC_TEMPLATE)
    project = random.choice(template["projects"])
    description = random.choice(project["descriptions"])
    r1, r2 = random.choice(_GIAB_FASTQ_PAIRS)
    seq_num = random.randint(1, 999)
    sample_id = f"{template['prefix']}-{project['code']}-{seq_num:03d}"
    patient_id = f"{template['patient_prefix']}-{random.randint(100, 999)}"

    return {
        "sample_id": sample_id,
        "project_id": project["id"],
        "description": description,
        "analysis_type": project["type"],
        "reference_genome": project["genome"],
        "patient_id": patient_id,
        "submitter_email": submitter_email,
        "fastq_r1": r1,
        "fastq_r2": r2,
    }


def generate_batch_for_org(count: int, org_id: str, submitter_email: str) -> list:
    """Generate a batch of organization-specific samples.

    Args:
        count: Number of samples to generate
        org_id: Organization ID
        submitter_email: Email of the submitter

    Returns:
        list: List of flat sample payloads
    """
    return [generate_sample_for_org(org_id, submitter_email) for _ in range(count)]

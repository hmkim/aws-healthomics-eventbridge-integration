"""Helper module to generate random test samples for LIMS mock emulator."""

import random
import string
import uuid
from datetime import datetime


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


def _generate_fastq_paths(bucket_name: str, project_id: str, sample_id: str) -> dict:
    """Generate realistic S3 paths for paired-end FASTQ files."""
    date_prefix = datetime.now().strftime("%Y/%m/%d")
    run_id = f"run_{uuid.uuid4().hex[:8]}"

    base_path = f"s3://{bucket_name}/raw_data/{date_prefix}/{project_id}/{run_id}/{sample_id}"

    return {
        "r1": f"{base_path}_R1_001.fastq.gz",
        "r2": f"{base_path}_R2_001.fastq.gz"
    }


def generate_sample(bucket_name: str) -> dict:
    """
    Generate a single random test sample matching the LIMS payload schema.

    Args:
        bucket_name: S3 bucket name for FASTQ file paths

    Returns:
        dict: Complete LIMS payload ready for submission
    """
    project_id = _random_id(random.choice(PROJECT_PREFIXES))
    sample_id = _random_id(random.choice(SAMPLE_PREFIXES))

    patient_id = f"PAT-{uuid.uuid4().hex[:12].upper()}"

    return {
        "source": "ClarityLIMS_Mock",
        "event_type": "StepCompleted",
        "data": {
            "project_id": project_id,
            "sample_id": sample_id,
            "patient_id": patient_id,
            "submitter_email": _random_email(),
            "fastq_paths": _generate_fastq_paths(bucket_name, project_id, sample_id),
            "reference_genome": "GRCh38",
            "analysis_type": random.choice(["WGS", "WES"])
        }
    }


def generate_batch(count: int, bucket_name: str) -> list:
    """
    Generate a batch of random test samples.

    Args:
        count: Number of samples to generate
        bucket_name: S3 bucket name for FASTQ file paths

    Returns:
        list: List of LIMS payloads ready for submission
    """
    return [generate_sample(bucket_name) for _ in range(count)]

#!/usr/bin/env python3
"""Seed LimsSamples DynamoDB table with fake sample data for demo purposes."""

import boto3
from datetime import datetime, timedelta
import random

REGION = "us-east-1"
TABLE_NAME = "LimsSamples"

# Realistic NA12878 family samples from 1000 Genomes / GIAB
SAMPLES = [
    {
        "SampleID": "NA12878-U0a",
        "ProjectID": "PROJ-NA12878",
        "PatientID": "PAT-GIAB-001",
        "SubmitterEmail": "genomics.lab@research.org",
        "ReferenceGenome": "GRCh38",
        "AnalysisType": "WGS",
        "FastqR1": "s3://aws-genomics-static-us-east-1/omics-tutorials/data/fastq/NA12878/Sample_U0a/U0a_CGATGT_L001_R1_001.fastq.gz",
        "FastqR2": "s3://aws-genomics-static-us-east-1/omics-tutorials/data/fastq/NA12878/Sample_U0a/U0a_CGATGT_L001_R2_001.fastq.gz",
        "Description": "GIAB reference sample HG001 (NA12878) - Daughter",
    },
    {
        "SampleID": "NA12891-B0a",
        "ProjectID": "PROJ-NA12878",
        "PatientID": "PAT-GIAB-002",
        "SubmitterEmail": "genomics.lab@research.org",
        "ReferenceGenome": "GRCh38",
        "AnalysisType": "WGS",
        "FastqR1": "s3://aws-genomics-static-us-east-1/omics-tutorials/data/fastq/NA12878/Sample_U0a/U0a_CGATGT_L001_R1_001.fastq.gz",
        "FastqR2": "s3://aws-genomics-static-us-east-1/omics-tutorials/data/fastq/NA12878/Sample_U0a/U0a_CGATGT_L001_R2_001.fastq.gz",
        "Description": "GIAB trio - Father (NA12891)",
    },
    {
        "SampleID": "NA12892-C0a",
        "ProjectID": "PROJ-NA12878",
        "PatientID": "PAT-GIAB-003",
        "SubmitterEmail": "genomics.lab@research.org",
        "ReferenceGenome": "GRCh38",
        "AnalysisType": "WGS",
        "FastqR1": "s3://aws-genomics-static-us-east-1/omics-tutorials/data/fastq/NA12878/Sample_U0a/U0a_CGATGT_L001_R1_001.fastq.gz",
        "FastqR2": "s3://aws-genomics-static-us-east-1/omics-tutorials/data/fastq/NA12878/Sample_U0a/U0a_CGATGT_L001_R2_001.fastq.gz",
        "Description": "GIAB trio - Mother (NA12892)",
    },
    {
        "SampleID": "SAM-ONCO-101",
        "ProjectID": "STUDY-ONCOLOGY-2026",
        "PatientID": "PAT-ONC-A041",
        "SubmitterEmail": "dr.kim@hospital.org",
        "ReferenceGenome": "GRCh38",
        "AnalysisType": "WES",
        "FastqR1": "s3://aws-genomics-static-us-east-1/omics-tutorials/data/fastq/NA12878/Sample_U0a/U0a_CGATGT_L001_R1_001.fastq.gz",
        "FastqR2": "s3://aws-genomics-static-us-east-1/omics-tutorials/data/fastq/NA12878/Sample_U0a/U0a_CGATGT_L001_R2_001.fastq.gz",
        "Description": "Oncology panel - Tumor biopsy sample",
    },
    {
        "SampleID": "SAM-ONCO-102",
        "ProjectID": "STUDY-ONCOLOGY-2026",
        "PatientID": "PAT-ONC-A041",
        "SubmitterEmail": "dr.kim@hospital.org",
        "ReferenceGenome": "GRCh38",
        "AnalysisType": "WES",
        "FastqR1": "s3://aws-genomics-static-us-east-1/omics-tutorials/data/fastq/NA12878/Sample_U0a/U0a_CGATGT_L001_R1_001.fastq.gz",
        "FastqR2": "s3://aws-genomics-static-us-east-1/omics-tutorials/data/fastq/NA12878/Sample_U0a/U0a_CGATGT_L001_R2_001.fastq.gz",
        "Description": "Oncology panel - Matched normal sample",
    },
    {
        "SampleID": "SAM-RARE-201",
        "ProjectID": "TRIAL-RARE-DISEASE",
        "PatientID": "PAT-RD-F012",
        "SubmitterEmail": "research.team@university.edu",
        "ReferenceGenome": "GRCh38",
        "AnalysisType": "WGS",
        "FastqR1": "s3://aws-genomics-static-us-east-1/omics-tutorials/data/fastq/NA12878/Sample_U0a/U0a_CGATGT_L001_R1_001.fastq.gz",
        "FastqR2": "s3://aws-genomics-static-us-east-1/omics-tutorials/data/fastq/NA12878/Sample_U0a/U0a_CGATGT_L001_R2_001.fastq.gz",
        "Description": "Rare disease trio - Proband",
    },
    {
        "SampleID": "SAM-RARE-202",
        "ProjectID": "TRIAL-RARE-DISEASE",
        "PatientID": "PAT-RD-F012-M",
        "SubmitterEmail": "research.team@university.edu",
        "ReferenceGenome": "GRCh38",
        "AnalysisType": "WGS",
        "FastqR1": "s3://aws-genomics-static-us-east-1/omics-tutorials/data/fastq/NA12878/Sample_U0a/U0a_CGATGT_L001_R1_001.fastq.gz",
        "FastqR2": "s3://aws-genomics-static-us-east-1/omics-tutorials/data/fastq/NA12878/Sample_U0a/U0a_CGATGT_L001_R2_001.fastq.gz",
        "Description": "Rare disease trio - Mother",
    },
    {
        "SampleID": "SAM-PHARMA-301",
        "ProjectID": "EXP-PHARMACOGENOMICS",
        "PatientID": "PAT-PGX-V088",
        "SubmitterEmail": "clinical.trial@biolab.edu",
        "ReferenceGenome": "GRCh38",
        "AnalysisType": "WES",
        "FastqR1": "s3://aws-genomics-static-us-east-1/omics-tutorials/data/fastq/NA12878/Sample_U0a/U0a_CGATGT_L001_R1_001.fastq.gz",
        "FastqR2": "s3://aws-genomics-static-us-east-1/omics-tutorials/data/fastq/NA12878/Sample_U0a/U0a_CGATGT_L001_R2_001.fastq.gz",
        "Description": "Pharmacogenomics screening - Drug response panel",
    },
]


def seed():
    dynamodb = boto3.resource('dynamodb', region_name=REGION)
    table = dynamodb.Table(TABLE_NAME)

    base_time = datetime.utcnow() - timedelta(days=3)

    for i, sample in enumerate(SAMPLES):
        registered_at = (base_time + timedelta(hours=i * 6)).isoformat() + "Z"
        item = {
            **sample,
            "RegisteredAt": registered_at,
            "Source": "ClarityLIMS_Mock",
        }
        table.put_item(Item=item)
        print(f"  Seeded: {sample['SampleID']} ({sample['ProjectID']})")

    print(f"\nDone! Seeded {len(SAMPLES)} samples into {TABLE_NAME}")


if __name__ == "__main__":
    seed()

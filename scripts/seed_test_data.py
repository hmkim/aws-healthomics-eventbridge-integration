#!/usr/bin/env python3
"""Seed Cognito users and DynamoDB sample data for development/testing.

Usage:
    python scripts/seed_test_data.py --user-pool-id <id> --region us-east-1

Creates:
    - 3 organizations with users in Cognito (admin, operator, viewer)
    - 5 LIMS samples per organization in DynamoDB
    - A few GenomicWorkflowState records with various statuses

Each user gets a unique random temporary password.
Users must reset via Cognito Hosted UI 'Forgot password' flow.
"""

import argparse
import boto3
import json
import secrets
import string
import sys
from datetime import datetime, timezone, timedelta


def _generate_temp_password(length=16):
    """Generate a random temporary password meeting Cognito requirements."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    # Ensure at least one of each required character type
    password = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice("!@#$%^&*"),
    ]
    password += [secrets.choice(alphabet) for _ in range(length - 4)]
    secrets.SystemRandom().shuffle(password)
    return ''.join(password)

ORGANIZATIONS = [
    {
        "org_id": "ORG-ACME",
        "org_name": "ACME Genomics Lab",
        "users": [
            {"email": "admin@acme.example.com", "name": "Alice Admin", "groups": ["admin"]},
            {"email": "operator@acme.example.com", "name": "Oliver Operator", "groups": ["operator"]},
            {"email": "viewer@acme.example.com", "name": "Vera Viewer", "groups": ["viewer"]},
        ],
    },
    {
        "org_id": "ORG-BIOCORP",
        "org_name": "BioCorp Research",
        "users": [
            {"email": "admin@biocorp.example.com", "name": "Bob Admin", "groups": ["admin"]},
            {"email": "researcher@biocorp.example.com", "name": "Rosa Researcher", "groups": ["operator"]},
        ],
    },
    {
        "org_id": "ORG-UNIVERSITY",
        "org_name": "State University Medical Center",
        "users": [
            {"email": "pi@university.example.com", "name": "Dr. Patricia Investigator", "groups": ["admin", "operator"]},
        ],
    },
]

# Organization-specific sample templates — each org works on different projects
ORG_SAMPLES = {
    "ORG-ACME": [
        {"suffix": "RD-001", "project": "Rare-Disease-Dx-2026", "desc": "Rare disease trio - proband (developmental delay)", "type": "WGS", "genome": "GRCh38", "patient": "PAT-ACME-101"},
        {"suffix": "RD-002", "project": "Rare-Disease-Dx-2026", "desc": "Rare disease trio - mother", "type": "WGS", "genome": "GRCh38", "patient": "PAT-ACME-102"},
        {"suffix": "RD-003", "project": "Rare-Disease-Dx-2026", "desc": "Rare disease trio - father", "type": "WGS", "genome": "GRCh38", "patient": "PAT-ACME-103"},
        {"suffix": "CL-001", "project": "Clinical-WES-Validation", "desc": "Clinical exome validation - BRCA carrier screening", "type": "WES", "genome": "hg38", "patient": "PAT-ACME-201"},
        {"suffix": "CL-002", "project": "Clinical-WES-Validation", "desc": "Clinical exome validation - hereditary cardiac panel", "type": "WES", "genome": "hg38", "patient": "PAT-ACME-202"},
    ],
    "ORG-BIOCORP": [
        {"suffix": "IO-001", "project": "Immuno-Oncology-T2026", "desc": "Melanoma tumor biopsy - pre-treatment baseline", "type": "WES", "genome": "GRCh38", "patient": "PAT-BIO-301"},
        {"suffix": "IO-002", "project": "Immuno-Oncology-T2026", "desc": "Melanoma matched normal - blood", "type": "WES", "genome": "GRCh38", "patient": "PAT-BIO-301"},
        {"suffix": "IO-003", "project": "Immuno-Oncology-T2026", "desc": "NSCLC tumor biopsy - checkpoint inhibitor response", "type": "WES", "genome": "GRCh38", "patient": "PAT-BIO-302"},
        {"suffix": "TP-001", "project": "Tumor-Profiling-Panel", "desc": "Colorectal cancer - 500-gene targeted panel", "type": "PANEL", "genome": "hg38", "patient": "PAT-BIO-401"},
        {"suffix": "TP-002", "project": "Tumor-Profiling-Panel", "desc": "Breast cancer - 500-gene targeted panel", "type": "PANEL", "genome": "hg38", "patient": "PAT-BIO-402"},
    ],
    "ORG-UNIVERSITY": [
        {"suffix": "PG-001", "project": "PGx-Pharmacogenomics", "desc": "Pharmacogenomics - CYP2D6/CYP2C19 metabolizer status", "type": "WES", "genome": "GRCh38", "patient": "PAT-UNI-501"},
        {"suffix": "PG-002", "project": "PGx-Pharmacogenomics", "desc": "Pharmacogenomics - warfarin dose-response panel", "type": "WES", "genome": "GRCh38", "patient": "PAT-UNI-502"},
        {"suffix": "POP-001", "project": "Population-WGS-Cohort", "desc": "Population genetics cohort - East Asian ancestry", "type": "WGS", "genome": "GRCh38", "patient": "PAT-UNI-601"},
        {"suffix": "POP-002", "project": "Population-WGS-Cohort", "desc": "Population genetics cohort - European ancestry", "type": "WGS", "genome": "GRCh38", "patient": "PAT-UNI-602"},
        {"suffix": "POP-003", "project": "Population-WGS-Cohort", "desc": "Population genetics cohort - African ancestry", "type": "WGS", "genome": "GRCh38", "patient": "PAT-UNI-603"},
    ],
}

# Real FASTQ pairs from the AWS public NA12878 tutorial dataset.
# These are rotated across samples so each gets a valid pair for HealthOmics.
_FASTQ_BASE = "s3://aws-genomics-static-us-east-1/omics-tutorials/data/fastq/NA12878/Sample_U0a"
FASTQ_PAIRS = [
    (f"{_FASTQ_BASE}/U0a_CGATGT_L001_R1_001.fastq.gz", f"{_FASTQ_BASE}/U0a_CGATGT_L001_R2_001.fastq.gz"),
    (f"{_FASTQ_BASE}/U0a_CGATGT_L001_R1_002.fastq.gz", f"{_FASTQ_BASE}/U0a_CGATGT_L001_R2_002.fastq.gz"),
    (f"{_FASTQ_BASE}/U0a_CGATGT_L001_R1_003.fastq.gz", f"{_FASTQ_BASE}/U0a_CGATGT_L001_R2_003.fastq.gz"),
    (f"{_FASTQ_BASE}/U0a_CGATGT_L001_R1_004.fastq.gz", f"{_FASTQ_BASE}/U0a_CGATGT_L001_R2_004.fastq.gz"),
]

# Pipeline status lifecycle (for reference only — seed data does NOT create
# fake workflow state records; all samples start as NOT_STARTED and status
# is updated only by actual pipeline executions via Step Functions).
PIPELINE_STATUSES = [
    "NOT_STARTED",
    "INITIALIZED",
    "GATK_RUNNING",
    "GATK_COMPLETED",
    "VEP_RUNNING",
    "VEP_COMPLETED",
    "AWAITING_APPROVAL",
    "COMPLETED_APPROVED",
    "COMPLETED_REJECTED",
]


def create_users(cognito_client, user_pool_id, dry_run=False):
    """Create Cognito users with organization attributes."""
    created = []
    for org in ORGANIZATIONS:
        for user in org["users"]:
            print(f"  Creating user: {user['email']} (org={org['org_id']}, groups={user['groups']})")
            if dry_run:
                created.append(user["email"])
                continue

            temp_password = _generate_temp_password()
            try:
                cognito_client.admin_create_user(
                    UserPoolId=user_pool_id,
                    Username=user["email"],
                    TemporaryPassword=temp_password,
                    UserAttributes=[
                        {"Name": "email", "Value": user["email"]},
                        {"Name": "email_verified", "Value": "true"},
                        {"Name": "custom:organization_id", "Value": org["org_id"]},
                        {"Name": "custom:display_name", "Value": user["name"]},
                    ],
                    MessageAction="SUPPRESS",  # Don't send welcome email
                )
                created.append(user["email"])
            except cognito_client.exceptions.UsernameExistsException:
                print(f"    (already exists, skipping)")
                created.append(user["email"])

            # Add to groups
            for group in user["groups"]:
                try:
                    cognito_client.admin_add_user_to_group(
                        UserPoolId=user_pool_id,
                        Username=user["email"],
                        GroupName=group,
                    )
                except Exception as e:
                    print(f"    Warning: Could not add to group '{group}': {e}")

    return created


def create_samples(dynamodb_resource, dry_run=False):
    """Create LIMS sample records and workflow state records."""
    lims_table = dynamodb_resource.Table("LimsSamples")
    state_table = dynamodb_resource.Table("GenomicWorkflowState")

    now = datetime.now(timezone.utc)
    created_samples = []
    created_states = []

    global_sample_idx = 0
    for org in ORGANIZATIONS:
        org_id = org["org_id"]
        templates = ORG_SAMPLES.get(org_id, [])
        for i, tmpl in enumerate(templates):
            sample_id = f"{org_id.split('-')[1]}-{tmpl['suffix']}"
            registered_at = (now - timedelta(days=30 - i)).isoformat()
            r1, r2 = FASTQ_PAIRS[global_sample_idx % len(FASTQ_PAIRS)]
            global_sample_idx += 1

            sample_item = {
                "SampleID": sample_id,
                "OrganizationID": org_id,
                "ProjectID": tmpl["project"],
                "Description": tmpl["desc"],
                "AnalysisType": tmpl["type"],
                "ReferenceGenome": tmpl["genome"],
                "PatientID": tmpl["patient"],
                "RegisteredAt": registered_at,
                "SubmitterEmail": org["users"][0]["email"],
                "FastqR1": r1,
                "FastqR2": r2,
            }

            print(f"  Creating sample: {sample_id} (org={org_id})")
            if not dry_run:
                lims_table.put_item(Item=sample_item)
            created_samples.append(sample_id)

            # No fake workflow state records — all samples start as NOT_STARTED.
            # Pipeline status is created only by real Step Functions executions.

    return created_samples, []


def main():
    parser = argparse.ArgumentParser(description="Seed test data for LIMS Genomics Dashboard")
    parser.add_argument("--user-pool-id", required=True, help="Cognito User Pool ID")
    parser.add_argument("--region", default="us-east-1", help="AWS region")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be created without making changes")
    args = parser.parse_args()

    print(f"{'[DRY RUN] ' if args.dry_run else ''}Seeding test data...")
    print(f"  Region: {args.region}")
    print(f"  User Pool: {args.user_pool_id}")
    print()

    cognito_client = boto3.client("cognito-idp", region_name=args.region)
    dynamodb = boto3.resource("dynamodb", region_name=args.region)

    print("=== Creating Cognito Users ===")
    users = create_users(cognito_client, args.user_pool_id, dry_run=args.dry_run)
    print(f"\nCreated {len(users)} users")

    print("\n=== Creating DynamoDB Sample Data ===")
    samples, states = create_samples(dynamodb, dry_run=args.dry_run)
    print(f"\nCreated {len(samples)} samples, {len(states)} workflow states")

    print("\n=== Summary ===")
    print("Each user was created with a unique random temporary password.")
    print("Users must reset their password via Cognito Hosted UI 'Forgot password' flow.")
    print()
    for org in ORGANIZATIONS:
        print(f"  {org['org_id']} ({org['org_name']}):")
        for user in org["users"]:
            print(f"    {user['email']} [{', '.join(user['groups'])}]")
    print()
    print("Done!")


if __name__ == "__main__":
    main()

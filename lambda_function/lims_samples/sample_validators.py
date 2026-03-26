"""Validation logic for LIMS sample registration requests."""

import re

VALID_ANALYSIS_TYPES = {'WGS', 'WES', 'PANEL'}
VALID_REFERENCE_GENOMES = {'hg38', 'GRCh38'}
S3_PATH_PATTERN = re.compile(r'^s3://[a-zA-Z0-9.\-_]+/.+')
EMAIL_PATTERN = re.compile(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$')
SAMPLE_ID_PATTERN = re.compile(r'^[A-Za-z0-9\-_]+$')


def validate_sample(sample: dict) -> list:
    """Validate a sample registration payload.

    Returns a list of error messages. Empty list means valid.
    """
    errors = []

    if not sample:
        return ['Sample payload is empty']

    # Required fields
    sample_id = sample.get('sample_id', '')
    if not sample_id:
        errors.append('Missing required field: sample_id')
    elif not SAMPLE_ID_PATTERN.match(sample_id):
        errors.append(f'Invalid sample_id format: {sample_id}. Only alphanumeric, hyphens, and underscores allowed.')

    if not sample.get('project_id'):
        errors.append('Missing required field: project_id')

    # FASTQ paths (flat format: fastq_r1, fastq_r2)
    fastq_r1 = sample.get('fastq_r1', '')
    fastq_r2 = sample.get('fastq_r2', '')

    if not fastq_r1:
        errors.append('Missing required field: fastq_r1')
    elif not S3_PATH_PATTERN.match(fastq_r1):
        errors.append(f'Invalid S3 path format for fastq_r1: {fastq_r1}')

    if not fastq_r2:
        errors.append('Missing required field: fastq_r2')
    elif not S3_PATH_PATTERN.match(fastq_r2):
        errors.append(f'Invalid S3 path format for fastq_r2: {fastq_r2}')

    # Reference genome (required)
    reference_genome = sample.get('reference_genome', '')
    if not reference_genome:
        errors.append('Missing required field: reference_genome')
    elif reference_genome not in VALID_REFERENCE_GENOMES:
        errors.append(
            f'Invalid reference_genome: {reference_genome}. '
            f'Must be one of: {", ".join(sorted(VALID_REFERENCE_GENOMES))}'
        )

    # Analysis type (optional but validated if present)
    analysis_type = sample.get('analysis_type', '')
    if analysis_type and analysis_type not in VALID_ANALYSIS_TYPES:
        errors.append(
            f'Invalid analysis_type: {analysis_type}. '
            f'Must be one of: {", ".join(sorted(VALID_ANALYSIS_TYPES))}'
        )

    # Submitter email (optional but validated if present)
    submitter_email = sample.get('submitter_email', '')
    if submitter_email and not EMAIL_PATTERN.match(submitter_email):
        errors.append(f'Invalid email format: {submitter_email}')

    return errors

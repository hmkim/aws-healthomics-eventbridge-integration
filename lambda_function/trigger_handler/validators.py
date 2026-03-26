import re

VALID_SOURCES = {'ClarityLIMS', 'ClarityLIMS_Mock'}
VALID_ANALYSIS_TYPES = {'WGS', 'WES', 'PANEL'}
VALID_REFERENCE_GENOMES = {'hg38', 'GRCh38'}
S3_PATH_PATTERN = re.compile(r'^s3://[a-zA-Z0-9.\-_]+/.+')
EMAIL_PATTERN = re.compile(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$')


class ValidationError(Exception):
    def __init__(self, errors):
        self.errors = errors if isinstance(errors, list) else [errors]
        super().__init__('; '.join(self.errors))


def validate_lims_payload(payload):
    errors = []

    if not payload:
        raise ValidationError('Request body is empty')

    # Top-level fields
    source = payload.get('source', '')
    if not source:
        errors.append('Missing required field: source')
    elif source not in VALID_SOURCES:
        errors.append(f'Invalid source: {source}. Must be one of: {", ".join(sorted(VALID_SOURCES))}')

    if not payload.get('event_type'):
        errors.append('Missing required field: event_type')

    data = payload.get('data')
    if not data:
        errors.append('Missing required field: data')
        raise ValidationError(errors)

    # Data fields
    if not data.get('project_id'):
        errors.append('Missing required field: data.project_id')

    if not data.get('sample_id'):
        errors.append('Missing required field: data.sample_id')

    if not data.get('patient_id'):
        errors.append('Missing required field: data.patient_id')

    submitter_email = data.get('submitter_email', '')
    if not submitter_email:
        errors.append('Missing required field: data.submitter_email')
    elif not EMAIL_PATTERN.match(submitter_email):
        errors.append(f'Invalid email format: {submitter_email}')

    # FASTQ paths
    fastq_paths = data.get('fastq_paths')
    if not fastq_paths:
        errors.append('Missing required field: data.fastq_paths')
    else:
        r1 = fastq_paths.get('r1', '')
        r2 = fastq_paths.get('r2', '')
        if not r1:
            errors.append('Missing required field: data.fastq_paths.r1')
        elif not S3_PATH_PATTERN.match(r1):
            errors.append(f'Invalid S3 path format for r1: {r1}')
        if not r2:
            errors.append('Missing required field: data.fastq_paths.r2')
        elif not S3_PATH_PATTERN.match(r2):
            errors.append(f'Invalid S3 path format for r2: {r2}')

    # Reference genome
    reference_genome = data.get('reference_genome', '')
    if not reference_genome:
        errors.append('Missing required field: data.reference_genome')
    elif reference_genome not in VALID_REFERENCE_GENOMES:
        errors.append(f'Invalid reference_genome: {reference_genome}. Must be one of: {", ".join(sorted(VALID_REFERENCE_GENOMES))}')

    # Analysis type (optional but validated if present)
    analysis_type = data.get('analysis_type', '')
    if analysis_type and analysis_type not in VALID_ANALYSIS_TYPES:
        errors.append(f'Invalid analysis_type: {analysis_type}. Must be one of: {", ".join(sorted(VALID_ANALYSIS_TYPES))}')

    if errors:
        raise ValidationError(errors)

    return True

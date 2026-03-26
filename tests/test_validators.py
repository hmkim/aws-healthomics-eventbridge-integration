import sys
import os
import pytest

# Add trigger_handler to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lambda_function', 'trigger_handler'))
from validators import validate_lims_payload, ValidationError


def _valid_payload():
    return {
        'source': 'ClarityLIMS',
        'event_type': 'StepCompleted',
        'data': {
            'project_id': 'PROJ-001',
            'sample_id': 'SAM-001',
            'patient_id': 'PAT-HASH-001',
            'submitter_email': 'user@example.com',
            'fastq_paths': {
                'r1': 's3://my-bucket/fastqs/sample_R1.fastq.gz',
                'r2': 's3://my-bucket/fastqs/sample_R2.fastq.gz',
            },
            'reference_genome': 'GRCh38',
            'analysis_type': 'WGS',
        },
    }


def test_valid_payload():
    assert validate_lims_payload(_valid_payload()) is True


def test_empty_payload():
    with pytest.raises(ValidationError) as exc_info:
        validate_lims_payload(None)
    assert 'empty' in str(exc_info.value).lower()


def test_missing_source():
    payload = _valid_payload()
    del payload['source']
    with pytest.raises(ValidationError) as exc_info:
        validate_lims_payload(payload)
    assert 'source' in str(exc_info.value)


def test_missing_data():
    payload = _valid_payload()
    del payload['data']
    with pytest.raises(ValidationError) as exc_info:
        validate_lims_payload(payload)
    assert 'data' in str(exc_info.value)


def test_missing_sample_id():
    payload = _valid_payload()
    del payload['data']['sample_id']
    with pytest.raises(ValidationError) as exc_info:
        validate_lims_payload(payload)
    assert 'sample_id' in str(exc_info.value)


def test_invalid_email():
    payload = _valid_payload()
    payload['data']['submitter_email'] = 'not-an-email'
    with pytest.raises(ValidationError) as exc_info:
        validate_lims_payload(payload)
    assert 'email' in str(exc_info.value).lower()


def test_invalid_s3_path():
    payload = _valid_payload()
    payload['data']['fastq_paths']['r1'] = '/local/path/file.fastq.gz'
    with pytest.raises(ValidationError) as exc_info:
        validate_lims_payload(payload)
    assert 'S3 path' in str(exc_info.value)


def test_missing_r2():
    payload = _valid_payload()
    del payload['data']['fastq_paths']['r2']
    with pytest.raises(ValidationError) as exc_info:
        validate_lims_payload(payload)
    assert 'r2' in str(exc_info.value)


def test_invalid_reference_genome():
    payload = _valid_payload()
    payload['data']['reference_genome'] = 'hg19'
    with pytest.raises(ValidationError) as exc_info:
        validate_lims_payload(payload)
    assert 'reference_genome' in str(exc_info.value)


def test_valid_hg38_genome():
    payload = _valid_payload()
    payload['data']['reference_genome'] = 'hg38'
    assert validate_lims_payload(payload) is True


def test_invalid_analysis_type():
    payload = _valid_payload()
    payload['data']['analysis_type'] = 'RNA-seq'
    with pytest.raises(ValidationError) as exc_info:
        validate_lims_payload(payload)
    assert 'analysis_type' in str(exc_info.value)


def test_no_analysis_type_is_valid():
    payload = _valid_payload()
    del payload['data']['analysis_type']
    assert validate_lims_payload(payload) is True


def test_missing_patient_id():
    payload = _valid_payload()
    del payload['data']['patient_id']
    with pytest.raises(ValidationError) as exc_info:
        validate_lims_payload(payload)
    assert 'patient_id' in str(exc_info.value)


def test_invalid_source():
    payload = _valid_payload()
    payload['source'] = 'UnknownSource'
    with pytest.raises(ValidationError) as exc_info:
        validate_lims_payload(payload)
    assert 'source' in str(exc_info.value).lower()


def test_mock_source_is_valid():
    payload = _valid_payload()
    payload['source'] = 'ClarityLIMS_Mock'
    assert validate_lims_payload(payload) is True


def test_multiple_errors():
    payload = {
        'event_type': 'StepCompleted',
        'data': {
            'project_id': 'PROJ-001',
        },
    }
    with pytest.raises(ValidationError) as exc_info:
        validate_lims_payload(payload)
    # Should contain multiple errors
    assert len(exc_info.value.errors) > 1

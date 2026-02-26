import sys
import os
import json
import pytest
from unittest.mock import patch, MagicMock
from decimal import Decimal

# Set env vars BEFORE import
os.environ['LIMS_SAMPLES_TABLE'] = 'TestLimsSamples'
os.environ['WORKFLOW_STATE_TABLE'] = 'TestWorkflowState'
os.environ['LOG_LEVEL'] = 'DEBUG'
os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'

# Add lims_samples and shared to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lambda_function', 'lims_samples'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lambda_function', 'shared'))

# Patch boto3 resource before importing
with patch('boto3.resource') as mock_resource:
    import lims_samples

ORG_ID = 'ORG-TEST'


def _auth_event(body=None, org_id=ORG_ID, groups='["operator"]', email='test@example.com', method='POST'):
    """Build an event with Cognito auth claims and optional body."""
    event = {
        'httpMethod': method,
        'requestContext': {
            'authorizer': {
                'claims': {
                    'sub': 'test-user-123',
                    'email': email,
                    'organization_id': org_id,
                    'cognito:groups': groups,
                    'custom:display_name': 'Test User',
                }
            }
        }
    }
    if body is not None:
        event['body'] = body if isinstance(body, str) else json.dumps(body)
    return event


def _mock_tables():
    """Return mocked lims_table and state_table."""
    mock_lims = MagicMock()
    mock_state = MagicMock()
    lims_samples.lims_table = mock_lims
    lims_samples.state_table = mock_state
    return mock_lims, mock_state


def _valid_sample(sample_id='TEST-001', **overrides):
    """Build a valid single sample payload."""
    sample = {
        'sample_id': sample_id,
        'project_id': 'Rare-Disease-Dx-2026',
        'description': 'Test sample',
        'analysis_type': 'WGS',
        'reference_genome': 'GRCh38',
        'patient_id': 'PAT-TEST-001',
        'submitter_email': 'operator@acme.example.com',
        'fastq_r1': 's3://aws-genomics-static-us-east-1/omics-tutorials/data/fastq/NA12878/Sample_U0a/U0a_CGATGT_L001_R1_001.fastq.gz',
        'fastq_r2': 's3://aws-genomics-static-us-east-1/omics-tutorials/data/fastq/NA12878/Sample_U0a/U0a_CGATGT_L001_R2_001.fastq.gz',
    }
    sample.update(overrides)
    return sample


# ===========================================================================
# Access Control Tests
# ===========================================================================
class TestAccessControl:

    def test_operator_can_register(self):
        mock_lims, _ = _mock_tables()
        mock_lims.get_item.return_value = {}  # no duplicate
        mock_lims.put_item.return_value = {}

        event = _auth_event(body=_valid_sample(), groups='["operator"]')
        result = lims_samples.handler(event, {})

        assert result['statusCode'] == 201

    def test_viewer_cannot_register(self):
        _mock_tables()

        event = _auth_event(body=_valid_sample(), groups='["viewer"]')
        result = lims_samples.handler(event, {})

        assert result['statusCode'] == 403

    def test_admin_can_register(self):
        mock_lims, _ = _mock_tables()
        mock_lims.get_item.return_value = {}
        mock_lims.put_item.return_value = {}

        event = _auth_event(body=_valid_sample(), groups='["admin"]')
        result = lims_samples.handler(event, {})

        assert result['statusCode'] == 201


# ===========================================================================
# Single Registration Tests
# ===========================================================================
class TestSingleRegistration:

    def test_register_single_success(self):
        mock_lims, _ = _mock_tables()
        mock_lims.get_item.return_value = {}
        mock_lims.put_item.return_value = {}

        event = _auth_event(body=_valid_sample('ACME-RD-010'))
        result = lims_samples.handler(event, {})

        assert result['statusCode'] == 201
        body = json.loads(result['body'])
        assert body['success'] is True
        assert body['sample']['SampleID'] == 'ACME-RD-010'
        assert body['sample']['OrganizationID'] == ORG_ID

        # Verify put_item was called
        mock_lims.put_item.assert_called_once()
        item = mock_lims.put_item.call_args[1]['Item']
        assert item['SampleID'] == 'ACME-RD-010'
        assert item['OrganizationID'] == ORG_ID

    def test_register_duplicate_returns_409(self):
        mock_lims, _ = _mock_tables()
        mock_lims.get_item.return_value = {'Item': {'SampleID': 'DUP-001'}}

        event = _auth_event(body=_valid_sample('DUP-001'))
        result = lims_samples.handler(event, {})

        assert result['statusCode'] == 409
        body = json.loads(result['body'])
        assert 'already exists' in body['error']

    def test_org_id_from_jwt_not_body(self):
        """Body's organization_id should be ignored; JWT org_id is used."""
        mock_lims, _ = _mock_tables()
        mock_lims.get_item.return_value = {}
        mock_lims.put_item.return_value = {}

        sample = _valid_sample()
        sample['organization_id'] = 'ORG-EVIL'  # This should be ignored
        event = _auth_event(body=sample, org_id='ORG-REAL')
        result = lims_samples.handler(event, {})

        assert result['statusCode'] == 201
        body = json.loads(result['body'])
        assert body['sample']['OrganizationID'] == 'ORG-REAL'

    def test_submitter_email_defaults_to_auth_email(self):
        """When submitter_email is not provided, use JWT email."""
        mock_lims, _ = _mock_tables()
        mock_lims.get_item.return_value = {}
        mock_lims.put_item.return_value = {}

        sample = _valid_sample()
        del sample['submitter_email']
        event = _auth_event(body=sample, email='jwt-user@example.com')
        result = lims_samples.handler(event, {})

        assert result['statusCode'] == 201
        body = json.loads(result['body'])
        assert body['sample']['SubmitterEmail'] == 'jwt-user@example.com'


# ===========================================================================
# Batch Registration Tests
# ===========================================================================
class TestBatchRegistration:

    def test_batch_all_success(self):
        mock_lims, _ = _mock_tables()
        mock_lims.get_item.return_value = {}
        mock_lims.put_item.return_value = {}

        samples = [_valid_sample(f'BATCH-{i:03d}') for i in range(3)]
        event = _auth_event(body={'samples': samples})
        result = lims_samples.handler(event, {})

        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['total'] == 3
        assert body['registered'] == 3
        assert body['failed'] == 0

    def test_batch_partial_failure(self):
        """One duplicate in batch should result in 207."""
        mock_lims, _ = _mock_tables()
        # First sample exists (duplicate), second and third do not
        mock_lims.get_item.side_effect = [
            {'Item': {'SampleID': 'BATCH-000'}},  # exists
            {},  # not exists
            {},  # not exists
        ]
        mock_lims.put_item.return_value = {}

        samples = [_valid_sample(f'BATCH-{i:03d}') for i in range(3)]
        event = _auth_event(body={'samples': samples})
        result = lims_samples.handler(event, {})

        assert result['statusCode'] == 207
        body = json.loads(result['body'])
        assert body['total'] == 3
        assert body['registered'] == 2
        assert body['failed'] == 1
        assert body['results'][0]['status'] == 'failed'
        assert body['results'][1]['status'] == 'registered'
        assert body['results'][2]['status'] == 'registered'

    def test_batch_empty_array_returns_400(self):
        _mock_tables()

        event = _auth_event(body={'samples': []})
        result = lims_samples.handler(event, {})

        assert result['statusCode'] == 400
        body = json.loads(result['body'])
        assert 'non-empty' in body['error']


# ===========================================================================
# Validation Tests
# ===========================================================================
class TestValidation:

    def test_missing_sample_id_returns_400(self):
        _mock_tables()

        sample = _valid_sample()
        del sample['sample_id']
        event = _auth_event(body=sample)
        result = lims_samples.handler(event, {})

        assert result['statusCode'] == 400
        body = json.loads(result['body'])
        assert any('sample_id' in e for e in body['details'])

    def test_invalid_s3_path_returns_400(self):
        _mock_tables()

        sample = _valid_sample(fastq_r1='not-an-s3-path')
        event = _auth_event(body=sample)
        result = lims_samples.handler(event, {})

        assert result['statusCode'] == 400
        body = json.loads(result['body'])
        assert any('S3 path' in e for e in body['details'])

    def test_invalid_reference_genome_returns_400(self):
        _mock_tables()

        sample = _valid_sample(reference_genome='hg19')
        event = _auth_event(body=sample)
        result = lims_samples.handler(event, {})

        assert result['statusCode'] == 400
        body = json.loads(result['body'])
        assert any('reference_genome' in e for e in body['details'])

    def test_invalid_json_body_returns_400(self):
        _mock_tables()

        event = _auth_event(body='not-valid-json{{{')
        result = lims_samples.handler(event, {})

        assert result['statusCode'] == 400
        body = json.loads(result['body'])
        assert 'Invalid JSON' in body['error']

    def test_method_not_allowed(self):
        _mock_tables()

        event = _auth_event(method='DELETE')
        result = lims_samples.handler(event, {})

        assert result['statusCode'] == 405


# ===========================================================================
# GET Handler Compatibility Tests
# ===========================================================================
class TestGetHandlerCompatibility:
    """Ensure GET still works after handler refactoring."""

    def test_get_returns_samples(self):
        mock_lims, mock_state = _mock_tables()

        mock_lims.query.return_value = {
            'Items': [
                {'SampleID': 'SAM-001', 'ProjectID': 'PROJ-001', 'RegisteredAt': '2026-01-01T00:00:00Z'},
            ]
        }
        mock_state.query.return_value = {'Items': []}

        event = _auth_event(method='GET', groups='["viewer"]')
        result = lims_samples.handler(event, {})

        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['count'] == 1
        assert body['samples'][0]['PipelineStatus'] == 'NOT_STARTED'

    def test_get_default_method(self):
        """When httpMethod is missing, should default to GET."""
        mock_lims, mock_state = _mock_tables()

        mock_lims.query.return_value = {'Items': []}
        mock_state.query.return_value = {'Items': []}

        event = {
            'requestContext': {
                'authorizer': {
                    'claims': {
                        'sub': 'test-user',
                        'email': 'test@example.com',
                        'organization_id': ORG_ID,
                        'cognito:groups': '["viewer"]',
                    }
                }
            }
        }
        # No httpMethod key
        result = lims_samples.handler(event, {})

        assert result['statusCode'] == 200

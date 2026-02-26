import sys
import os
import json
import pytest
from unittest.mock import patch, MagicMock
from decimal import Decimal

# Set env vars BEFORE import
os.environ['WORKFLOW_STATE_TABLE'] = 'TestWorkflowState'
os.environ['LOG_LEVEL'] = 'DEBUG'
os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'

# Add status_query and shared to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lambda_function', 'status_query'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lambda_function', 'shared'))

# Patch boto3 resource and client before importing
with patch('boto3.resource') as mock_resource, patch('boto3.client') as mock_client:
    import status_query

ORG_ID = 'ORG-TEST'


def _mock_table():
    mock_table = MagicMock()
    status_query.state_table = mock_table
    return mock_table


def _mock_omics(runs=None):
    """Mock HealthOmics client. runs maps run_id -> {'status': ..., 'name': ...}."""
    mock_omics = MagicMock()
    if runs is None:
        runs = {}

    def get_run(id):
        if id in runs:
            return runs[id]
        return {'status': 'COMPLETED', 'name': f'run-{id}'}

    mock_omics.get_run.side_effect = get_run
    status_query.omics = mock_omics
    return mock_omics


def _api_event(sample_id, org_id=ORG_ID, groups='["operator"]'):
    return {
        'pathParameters': {'sample_id': sample_id},
        'requestContext': {
            'authorizer': {
                'claims': {
                    'sub': 'test-user',
                    'email': 'test@example.com',
                    'organization_id': org_id,
                    'cognito:groups': groups,
                    'custom:display_name': 'Test User',
                }
            }
        },
    }


class TestStatusQueryOrdering:
    """Test that status records are sorted by UpdatedAt (most recent first)."""

    def test_records_sorted_by_updated_at(self):
        """Records should be sorted by UpdatedAt descending, not Timestamp."""
        mock_table = _mock_table()
        _mock_omics()

        mock_table.query.return_value = {
            'Items': [
                {
                    'SampleID': 'NA12878-U0a',
                    'Timestamp': '2026-02-19T06:15:30.768Z',
                    'Status': 'INITIALIZED',
                    'UpdatedAt': '2026-02-19T06:15:30.768Z',
                    'OrganizationID': ORG_ID,
                },
                {
                    'SampleID': 'NA12878-U0a',
                    'Timestamp': '2026-02-19T06:15:30.736Z',
                    'Status': 'GATK_RUNNING',
                    'UpdatedAt': '2026-02-19T06:16:45.000Z',
                    'GATKRunId': '9670443',
                    'OrganizationID': ORG_ID,
                },
            ]
        }

        result = status_query.handler(_api_event('NA12878-U0a'), {})
        body = json.loads(result['body'])

        assert result['statusCode'] == 200
        assert body['count'] == 2
        # GATK_RUNNING has later UpdatedAt, so it should be first
        assert body['records'][0]['Status'] == 'GATK_RUNNING'
        assert body['records'][1]['Status'] == 'INITIALIZED'

    def test_full_pipeline_ordering(self):
        """Full pipeline progression: VEP_RUNNING should be first (most recent UpdatedAt)."""
        mock_table = _mock_table()

        mock_table.query.return_value = {
            'Items': [
                {
                    'SampleID': 'SAM-001',
                    'Timestamp': '2026-02-18T10:00:00.100Z',
                    'Status': 'INITIALIZED',
                    'UpdatedAt': '2026-02-18T10:00:00.100Z',
                    'OrganizationID': ORG_ID,
                },
                {
                    'SampleID': 'SAM-001',
                    'Timestamp': '2026-02-18T10:00:00.050Z',
                    'Status': 'GATK_RUNNING',
                    'UpdatedAt': '2026-02-18T10:00:05.000Z',
                    'OrganizationID': ORG_ID,
                },
                {
                    'SampleID': 'SAM-001',
                    'Timestamp': '2026-02-18T10:00:00.050Z',
                    'Status': 'GATK_COMPLETED',
                    'UpdatedAt': '2026-02-18T11:30:00.000Z',
                    'OrganizationID': ORG_ID,
                },
                {
                    'SampleID': 'SAM-001',
                    'Timestamp': '2026-02-18T10:00:00.050Z',
                    'Status': 'VEP_RUNNING',
                    'UpdatedAt': '2026-02-18T11:35:00.000Z',
                    'OrganizationID': ORG_ID,
                },
            ]
        }

        result = status_query.handler(_api_event('SAM-001'), {})
        body = json.loads(result['body'])

        # Should be ordered: VEP_RUNNING, GATK_COMPLETED, GATK_RUNNING, INITIALIZED
        statuses = [r['Status'] for r in body['records']]
        assert statuses == ['VEP_RUNNING', 'GATK_COMPLETED', 'GATK_RUNNING', 'INITIALIZED']

    def test_fallback_to_timestamp_when_no_updated_at(self):
        """When UpdatedAt is missing, fall back to Timestamp."""
        mock_table = _mock_table()

        mock_table.query.return_value = {
            'Items': [
                {
                    'SampleID': 'SAM-OLD',
                    'Timestamp': '2026-01-01T10:00:00.000Z',
                    'Status': 'INITIALIZED',
                    'OrganizationID': ORG_ID,
                },
                {
                    'SampleID': 'SAM-OLD',
                    'Timestamp': '2026-01-01T10:05:00.000Z',
                    'Status': 'GATK_RUNNING',
                    'OrganizationID': ORG_ID,
                },
            ]
        }

        result = status_query.handler(_api_event('SAM-OLD'), {})
        body = json.loads(result['body'])

        # GATK_RUNNING has later Timestamp
        assert body['records'][0]['Status'] == 'GATK_RUNNING'
        assert body['records'][1]['Status'] == 'INITIALIZED'


class TestStatusQueryBasic:
    """Test basic status_query functionality."""

    def test_missing_sample_id_returns_400(self):
        event = _api_event('placeholder')
        event['pathParameters'] = {}
        result = status_query.handler(event, {})
        assert result['statusCode'] == 400

    def test_sample_not_found_returns_404(self):
        mock_table = _mock_table()
        mock_table.query.return_value = {'Items': []}

        result = status_query.handler(_api_event('NONEXISTENT'), {})
        assert result['statusCode'] == 404

    def test_approval_tokens_stripped(self):
        """ApprovalToken should be removed from response for security."""
        mock_table = _mock_table()

        mock_table.query.return_value = {
            'Items': [
                {
                    'SampleID': 'SAM-001',
                    'Timestamp': '2026-01-01T10:00:00Z',
                    'Status': 'PENDING_APPROVAL',
                    'UpdatedAt': '2026-01-01T12:00:00Z',
                    'ApprovalToken': 'secret-token-12345',
                    'OrganizationID': ORG_ID,
                },
            ]
        }

        result = status_query.handler(_api_event('SAM-001'), {})
        body = json.loads(result['body'])

        assert 'ApprovalToken' not in body['records'][0]

    def test_decimal_values_serialized(self):
        """Decimal values from DynamoDB should be serialized to strings."""
        mock_table = _mock_table()

        mock_table.query.return_value = {
            'Items': [
                {
                    'SampleID': 'SAM-001',
                    'Timestamp': '2026-01-01T10:00:00Z',
                    'Status': 'COMPLETED',
                    'UpdatedAt': '2026-01-01T12:00:00Z',
                    'Duration': Decimal('1234.56'),
                    'OrganizationID': ORG_ID,
                },
            ]
        }

        result = status_query.handler(_api_event('SAM-001'), {})
        body = json.loads(result['body'])

        assert body['records'][0]['Duration'] == '1234.56'

    def test_other_org_data_not_visible(self):
        """Items belonging to a different org should be filtered out, returning 404."""
        mock_table = _mock_table()

        mock_table.query.return_value = {
            'Items': [
                {
                    'SampleID': 'SAM-001',
                    'Timestamp': '2026-01-01T10:00:00Z',
                    'Status': 'COMPLETED',
                    'UpdatedAt': '2026-01-01T12:00:00Z',
                    'OrganizationID': 'ORG-OTHER',
                },
            ]
        }

        result = status_query.handler(_api_event('SAM-001'), {})
        assert result['statusCode'] == 404


class TestHealthOmicsRunStatus:
    """Test real-time HealthOmics run status enrichment via omics.get_run()."""

    def test_gatk_run_status_added(self):
        """GATKRunStatus and GATKRunName should be added when GATKRunId is present."""
        mock_table = _mock_table()
        mock_omics = _mock_omics(runs={
            '9670443': {'status': 'RUNNING', 'name': 'SFN_GATK_ACME-RD-001_abc123'},
        })

        mock_table.query.return_value = {
            'Items': [
                {
                    'SampleID': 'SAM-001',
                    'Timestamp': '2026-02-20T10:00:00Z',
                    'Status': 'GATK_RUNNING',
                    'UpdatedAt': '2026-02-20T10:05:00Z',
                    'GATKRunId': '9670443',
                    'OrganizationID': ORG_ID,
                },
            ]
        }

        result = status_query.handler(_api_event('SAM-001'), {})
        body = json.loads(result['body'])

        assert result['statusCode'] == 200
        assert body['records'][0]['GATKRunStatus'] == 'RUNNING'
        assert body['records'][0]['GATKRunName'] == 'SFN_GATK_ACME-RD-001_abc123'
        mock_omics.get_run.assert_called_once_with(id='9670443')

    def test_vep_run_status_added(self):
        """VEPRunStatus and VEPRunName should be added when VEPRunId is present."""
        mock_table = _mock_table()
        mock_omics = _mock_omics(runs={
            '9670500': {'status': 'COMPLETED', 'name': 'SFN_VEP_ACME-RD-001_def456'},
        })

        mock_table.query.return_value = {
            'Items': [
                {
                    'SampleID': 'SAM-001',
                    'Timestamp': '2026-02-20T10:00:00Z',
                    'Status': 'VEP_COMPLETED',
                    'UpdatedAt': '2026-02-20T12:00:00Z',
                    'VEPRunId': '9670500',
                    'OrganizationID': ORG_ID,
                },
            ]
        }

        result = status_query.handler(_api_event('SAM-001'), {})
        body = json.loads(result['body'])

        assert result['statusCode'] == 200
        assert body['records'][0]['VEPRunStatus'] == 'COMPLETED'
        assert body['records'][0]['VEPRunName'] == 'SFN_VEP_ACME-RD-001_def456'
        mock_omics.get_run.assert_called_once_with(id='9670500')

    def test_both_gatk_and_vep_status(self):
        """Both GATK and VEP statuses enriched when both run IDs present."""
        mock_table = _mock_table()
        mock_omics = _mock_omics(runs={
            '9670443': {'status': 'COMPLETED', 'name': 'SFN_GATK_SAM-001'},
            '9670500': {'status': 'RUNNING', 'name': 'SFN_VEP_SAM-001'},
        })

        mock_table.query.return_value = {
            'Items': [
                {
                    'SampleID': 'SAM-001',
                    'Timestamp': '2026-02-20T10:00:00Z',
                    'Status': 'VEP_RUNNING',
                    'UpdatedAt': '2026-02-20T12:00:00Z',
                    'GATKRunId': '9670443',
                    'VEPRunId': '9670500',
                    'OrganizationID': ORG_ID,
                },
            ]
        }

        result = status_query.handler(_api_event('SAM-001'), {})
        body = json.loads(result['body'])

        assert body['records'][0]['GATKRunStatus'] == 'COMPLETED'
        assert body['records'][0]['GATKRunName'] == 'SFN_GATK_SAM-001'
        assert body['records'][0]['VEPRunStatus'] == 'RUNNING'
        assert body['records'][0]['VEPRunName'] == 'SFN_VEP_SAM-001'

    def test_omics_error_returns_unknown(self):
        """When omics.get_run() raises an exception, status should be UNKNOWN."""
        mock_table = _mock_table()
        mock_omics = MagicMock()
        mock_omics.get_run.side_effect = Exception('AccessDenied')
        status_query.omics = mock_omics

        mock_table.query.return_value = {
            'Items': [
                {
                    'SampleID': 'SAM-001',
                    'Timestamp': '2026-02-20T10:00:00Z',
                    'Status': 'GATK_RUNNING',
                    'UpdatedAt': '2026-02-20T10:05:00Z',
                    'GATKRunId': '9670443',
                    'OrganizationID': ORG_ID,
                },
            ]
        }

        result = status_query.handler(_api_event('SAM-001'), {})
        body = json.loads(result['body'])

        assert result['statusCode'] == 200
        assert body['records'][0]['GATKRunStatus'] == 'UNKNOWN'
        assert 'GATKRunName' not in body['records'][0]

    def test_no_run_ids_no_omics_call(self):
        """When no run IDs exist, omics.get_run() should not be called."""
        mock_table = _mock_table()
        mock_omics = _mock_omics()

        mock_table.query.return_value = {
            'Items': [
                {
                    'SampleID': 'SAM-001',
                    'Timestamp': '2026-02-20T10:00:00Z',
                    'Status': 'INITIALIZED',
                    'UpdatedAt': '2026-02-20T10:00:00Z',
                    'OrganizationID': ORG_ID,
                },
            ]
        }

        result = status_query.handler(_api_event('SAM-001'), {})
        body = json.loads(result['body'])

        assert result['statusCode'] == 200
        assert 'GATKRunStatus' not in body['records'][0]
        assert 'VEPRunStatus' not in body['records'][0]
        mock_omics.get_run.assert_not_called()

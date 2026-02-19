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

# Add status_query to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lambda_function', 'status_query'))

# Patch boto3 resource before importing
with patch('boto3.resource') as mock_resource:
    import status_query


def _mock_table():
    mock_table = MagicMock()
    status_query.state_table = mock_table
    return mock_table


def _api_event(sample_id):
    return {
        'pathParameters': {'sample_id': sample_id},
    }


class TestStatusQueryOrdering:
    """Test that status records are sorted by UpdatedAt (most recent first)."""

    def test_records_sorted_by_updated_at(self):
        """Records should be sorted by UpdatedAt descending, not Timestamp."""
        mock_table = _mock_table()

        mock_table.query.return_value = {
            'Items': [
                {
                    'SampleID': 'NA12878-U0a',
                    'Timestamp': '2026-02-19T06:15:30.768Z',
                    'Status': 'INITIALIZED',
                    'UpdatedAt': '2026-02-19T06:15:30.768Z',
                },
                {
                    'SampleID': 'NA12878-U0a',
                    'Timestamp': '2026-02-19T06:15:30.736Z',
                    'Status': 'GATK_RUNNING',
                    'UpdatedAt': '2026-02-19T06:16:45.000Z',
                    'GATKRunId': '9670443',
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
                },
                {
                    'SampleID': 'SAM-001',
                    'Timestamp': '2026-02-18T10:00:00.050Z',
                    'Status': 'GATK_RUNNING',
                    'UpdatedAt': '2026-02-18T10:00:05.000Z',
                },
                {
                    'SampleID': 'SAM-001',
                    'Timestamp': '2026-02-18T10:00:00.050Z',
                    'Status': 'GATK_COMPLETED',
                    'UpdatedAt': '2026-02-18T11:30:00.000Z',
                },
                {
                    'SampleID': 'SAM-001',
                    'Timestamp': '2026-02-18T10:00:00.050Z',
                    'Status': 'VEP_RUNNING',
                    'UpdatedAt': '2026-02-18T11:35:00.000Z',
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
                },
                {
                    'SampleID': 'SAM-OLD',
                    'Timestamp': '2026-01-01T10:05:00.000Z',
                    'Status': 'GATK_RUNNING',
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
        result = status_query.handler({'pathParameters': {}}, {})
        assert result['statusCode'] == 400

    def test_no_path_parameters_returns_400(self):
        result = status_query.handler({}, {})
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
                },
            ]
        }

        result = status_query.handler(_api_event('SAM-001'), {})
        body = json.loads(result['body'])

        assert body['records'][0]['Duration'] == '1234.56'

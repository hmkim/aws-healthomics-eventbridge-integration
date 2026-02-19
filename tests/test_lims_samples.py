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

# Add lims_samples to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lambda_function', 'lims_samples'))

# Patch boto3 resource before importing
with patch('boto3.resource') as mock_resource:
    import lims_samples


def _mock_tables():
    """Return mocked lims_table and state_table."""
    mock_lims = MagicMock()
    mock_state = MagicMock()
    lims_samples.lims_table = mock_lims
    lims_samples.state_table = mock_state
    return mock_lims, mock_state


class TestStatusOrdering:
    """Test that pipeline status is determined by UpdatedAt, not Timestamp sort key."""

    def test_gatk_running_shown_over_initialized(self):
        """NA12878-U0a scenario: INITIALIZED has newer Timestamp but GATK_RUNNING has newer UpdatedAt."""
        mock_lims, mock_state = _mock_tables()

        mock_lims.scan.return_value = {
            'Items': [
                {'SampleID': 'NA12878-U0a', 'ProjectID': 'PROJ-NA12878', 'RegisteredAt': '2026-01-15T10:00:00Z'},
            ]
        }

        # Simulate real DynamoDB data: INITIALIZED has later Timestamp but earlier UpdatedAt
        mock_state.query.return_value = {
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
                    'UpdatedAt': '2026-02-19T06:16:45.000Z',  # Updated LATER
                    'GATKRunId': '9670443',
                },
            ]
        }

        result = lims_samples.handler({}, {})
        body = json.loads(result['body'])

        assert result['statusCode'] == 200
        assert body['count'] == 1
        sample = body['samples'][0]
        assert sample['PipelineStatus'] == 'GATK_RUNNING'
        assert sample['GATKRunId'] == '9670443'

    def test_vep_running_shown_when_gatk_completed(self):
        """VEP_RUNNING should be shown when it has the most recent UpdatedAt."""
        mock_lims, mock_state = _mock_tables()

        mock_lims.scan.return_value = {
            'Items': [
                {'SampleID': 'SAM-001', 'ProjectID': 'PROJ-001', 'RegisteredAt': '2026-01-10T10:00:00Z'},
            ]
        }

        mock_state.query.return_value = {
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
                    'Status': 'GATK_COMPLETED',
                    'UpdatedAt': '2026-02-18T11:30:00.000Z',
                    'GATKRunId': '1234567',
                },
                {
                    'SampleID': 'SAM-001',
                    'Timestamp': '2026-02-18T10:00:00.050Z',
                    'Status': 'VEP_RUNNING',
                    'UpdatedAt': '2026-02-18T11:35:00.000Z',
                    'GATKRunId': '1234567',
                    'VEPRunId': '7654321',
                },
            ]
        }

        result = lims_samples.handler({}, {})
        body = json.loads(result['body'])

        sample = body['samples'][0]
        assert sample['PipelineStatus'] == 'VEP_RUNNING'
        assert sample['VEPRunId'] == '7654321'

    def test_no_pipeline_records_shows_not_started(self):
        """Samples without any pipeline records should show NOT_STARTED."""
        mock_lims, mock_state = _mock_tables()

        mock_lims.scan.return_value = {
            'Items': [
                {'SampleID': 'SAM-NEW', 'ProjectID': 'PROJ-NEW', 'RegisteredAt': '2026-02-19T00:00:00Z'},
            ]
        }
        mock_state.query.return_value = {'Items': []}

        result = lims_samples.handler({}, {})
        body = json.loads(result['body'])

        sample = body['samples'][0]
        assert sample['PipelineStatus'] == 'NOT_STARTED'
        assert sample['PipelineTimestamp'] == ''

    def test_fallback_to_timestamp_when_no_updated_at(self):
        """When UpdatedAt is missing, fall back to Timestamp for ordering."""
        mock_lims, mock_state = _mock_tables()

        mock_lims.scan.return_value = {
            'Items': [
                {'SampleID': 'SAM-OLD', 'ProjectID': 'PROJ-OLD', 'RegisteredAt': '2026-01-01T00:00:00Z'},
            ]
        }

        mock_state.query.return_value = {
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
                    'GATKRunId': '111',
                },
            ]
        }

        result = lims_samples.handler({}, {})
        body = json.loads(result['body'])

        sample = body['samples'][0]
        # GATK_RUNNING has later Timestamp, so it should be picked
        assert sample['PipelineStatus'] == 'GATK_RUNNING'


class TestSampleSorting:
    """Test that samples are sorted correctly: NOT_STARTED first, then INITIALIZED, then others."""

    def test_not_started_samples_listed_first(self):
        mock_lims, mock_state = _mock_tables()

        mock_lims.scan.return_value = {
            'Items': [
                {'SampleID': 'SAM-RUNNING', 'ProjectID': 'PROJ-1', 'RegisteredAt': '2026-01-01T00:00:00Z'},
                {'SampleID': 'SAM-NEW', 'ProjectID': 'PROJ-2', 'RegisteredAt': '2026-01-02T00:00:00Z'},
            ]
        }

        # Return items in scan order: first call for SAM-RUNNING, second for SAM-NEW
        mock_state.query.side_effect = [
            {'Items': [
                {'SampleID': 'SAM-RUNNING', 'Timestamp': '2026-01-05T00:00:00Z',
                 'Status': 'GATK_RUNNING', 'UpdatedAt': '2026-01-06T00:00:00Z', 'GATKRunId': '111'},
            ]},
            {'Items': []},
        ]

        result = lims_samples.handler({}, {})
        body = json.loads(result['body'])

        assert body['count'] == 2
        assert body['samples'][0]['PipelineStatus'] == 'NOT_STARTED'
        assert body['samples'][1]['PipelineStatus'] == 'GATK_RUNNING'


class TestErrorHandling:
    """Test error handling in lims_samples handler."""

    def test_dynamodb_error_returns_500(self):
        mock_lims, _ = _mock_tables()
        mock_lims.scan.side_effect = Exception("DynamoDB connection error")

        result = lims_samples.handler({}, {})

        assert result['statusCode'] == 500
        body = json.loads(result['body'])
        assert 'error' in body

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

# Add Lambda paths
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lambda_function', 'approved_results'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lambda_function', 'shared'))

# Patch boto3 before importing
with patch('boto3.resource') as mock_resource:
    import approved_results

ORG_ID = 'ORG-TEST'
OTHER_ORG = 'ORG-OTHER'


def _auth_event(org_id=ORG_ID, groups='["admin"]'):
    """Build an API Gateway event with Cognito auth claims."""
    return {
        'requestContext': {
            'authorizer': {
                'claims': {
                    'sub': 'admin-user-123',
                    'email': 'admin@test.example.com',
                    'organization_id': org_id,
                    'cognito:groups': groups,
                    'custom:display_name': 'Test Admin',
                }
            }
        },
    }


def _approved_item(sample_id='SAM-001', org_id=ORG_ID, has_outputs=True):
    """Build a DynamoDB item with COMPLETED_APPROVED status."""
    item = {
        'SampleID': sample_id,
        'Timestamp': '2026-02-20T10:00:00.000Z',
        'Status': 'COMPLETED_APPROVED',
        'OrganizationID': org_id,
        'SubmitterEmail': 'submitter@test.example.com',
        'ProjectID': 'PROJ-001',
        'AnalysisType': 'WGS',
        'ApprovedBy': 'admin@test.example.com',
        'ApprovalDecidedAt': '2026-02-20T12:00:00.000Z',
        'ApprovalToken': 'secret-token-should-be-removed',
    }
    if has_outputs:
        item['GATKOutputUri'] = 's3://output-bucket/outputs/12345'
        item['VEPOutputUri'] = 's3://output-bucket/outputs/12346'
    return item


def _mock_table():
    """Set up mocked state_table."""
    mock_table = MagicMock()
    approved_results.state_table = mock_table
    return mock_table


class TestApprovedResultsAccess:
    """Test role-based access control."""

    def test_admin_can_access(self):
        mock_table = _mock_table()
        mock_table.query.return_value = {'Items': [_approved_item()]}

        result = approved_results.handler(_auth_event(groups='["admin"]'), {})
        assert result['statusCode'] == 200

    def test_operator_gets_403(self):
        result = approved_results.handler(_auth_event(groups='["operator"]'), {})
        assert result['statusCode'] == 403

    def test_viewer_gets_403(self):
        result = approved_results.handler(_auth_event(groups='["viewer"]'), {})
        assert result['statusCode'] == 403

    def test_no_auth_gets_401(self):
        result = approved_results.handler({}, {})
        assert result['statusCode'] == 401


class TestApprovedResultsQuery:
    """Test StatusIndex GSI query and org filtering."""

    def test_queries_status_index_for_completed_approved(self):
        mock_table = _mock_table()
        mock_table.query.return_value = {'Items': [_approved_item()]}

        approved_results.handler(_auth_event(), {})

        mock_table.query.assert_called_once()
        call_kwargs = mock_table.query.call_args[1]
        assert call_kwargs['IndexName'] == 'StatusIndex'

    def test_filters_by_organization(self):
        mock_table = _mock_table()
        mock_table.query.return_value = {
            'Items': [
                _approved_item(sample_id='SAM-001', org_id=ORG_ID),
                _approved_item(sample_id='SAM-002', org_id=OTHER_ORG),
                _approved_item(sample_id='SAM-003', org_id=ORG_ID),
            ]
        }

        result = approved_results.handler(_auth_event(org_id=ORG_ID), {})
        body = json.loads(result['body'])

        assert body['count'] == 2
        sample_ids = [item['SampleID'] for item in body['approved_results']]
        assert 'SAM-001' in sample_ids
        assert 'SAM-003' in sample_ids
        assert 'SAM-002' not in sample_ids

    def test_removes_approval_token(self):
        mock_table = _mock_table()
        mock_table.query.return_value = {'Items': [_approved_item()]}

        result = approved_results.handler(_auth_event(), {})
        body = json.loads(result['body'])

        for item in body['approved_results']:
            assert 'ApprovalToken' not in item

    def test_includes_output_uris(self):
        mock_table = _mock_table()
        mock_table.query.return_value = {'Items': [_approved_item(has_outputs=True)]}

        result = approved_results.handler(_auth_event(), {})
        body = json.loads(result['body'])

        item = body['approved_results'][0]
        assert item['GATKOutputUri'] == 's3://output-bucket/outputs/12345'
        assert item['VEPOutputUri'] == 's3://output-bucket/outputs/12346'

    def test_includes_approval_info(self):
        mock_table = _mock_table()
        mock_table.query.return_value = {'Items': [_approved_item()]}

        result = approved_results.handler(_auth_event(), {})
        body = json.loads(result['body'])

        item = body['approved_results'][0]
        assert item['ApprovedBy'] == 'admin@test.example.com'
        assert item['ApprovalDecidedAt'] == '2026-02-20T12:00:00.000Z'

    def test_empty_results(self):
        mock_table = _mock_table()
        mock_table.query.return_value = {'Items': []}

        result = approved_results.handler(_auth_event(), {})
        body = json.loads(result['body'])

        assert body['count'] == 0
        assert body['approved_results'] == []

    def test_handles_decimal_values(self):
        mock_table = _mock_table()
        item = _approved_item()
        item['SomeNumber'] = Decimal('42.5')
        mock_table.query.return_value = {'Items': [item]}

        result = approved_results.handler(_auth_event(), {})
        body = json.loads(result['body'])

        assert body['approved_results'][0]['SomeNumber'] == '42.5'

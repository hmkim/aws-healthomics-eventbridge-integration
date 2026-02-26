import sys
import os
import json
import pytest
from unittest.mock import patch, MagicMock

# Set env vars BEFORE import
os.environ['WORKFLOW_STATE_TABLE'] = 'TestWorkflowState'
os.environ['LOG_LEVEL'] = 'DEBUG'
os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'

# Add status_query and shared to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lambda_function', 'status_query'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lambda_function', 'shared'))

# Patch boto3 resource before importing
with patch('boto3.resource') as mock_resource:
    import status_query

ORG_ACME = 'ORG-ACME'
ORG_BIOCORP = 'ORG-BIOCORP'


def _api_event(sample_id, org_id=ORG_ACME, groups='["viewer"]'):
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


def _mock_table():
    mock_table = MagicMock()
    status_query.state_table = mock_table
    return mock_table


def _state_item(sample_id='SAM-001', org_id=ORG_ACME, status='GATK_RUNNING'):
    return {
        'SampleID': sample_id,
        'Timestamp': '2026-02-19T10:00:00.000Z',
        'Status': status,
        'UpdatedAt': '2026-02-19T10:05:00.000Z',
        'OrganizationID': org_id,
    }


class TestOrgIsolation:
    """Test that status queries enforce organization boundaries."""

    def test_same_org_returns_records(self):
        """User can see status of samples in their own org."""
        mock_table = _mock_table()
        mock_table.query.return_value = {
            'Items': [_state_item(org_id=ORG_ACME)]
        }

        result = status_query.handler(_api_event('SAM-001', org_id=ORG_ACME), {})
        assert result['statusCode'] == 200

        body = json.loads(result['body'])
        assert body['count'] == 1

    def test_cross_org_returns_404(self):
        """User cannot see status of samples in another org."""
        mock_table = _mock_table()
        mock_table.query.return_value = {
            'Items': [_state_item(org_id=ORG_BIOCORP)]
        }

        result = status_query.handler(_api_event('SAM-001', org_id=ORG_ACME), {})
        assert result['statusCode'] == 404

    def test_mixed_org_items_filtered(self):
        """When DynamoDB returns items from multiple orgs, only caller's org items are returned."""
        mock_table = _mock_table()
        mock_table.query.return_value = {
            'Items': [
                _state_item(org_id=ORG_ACME, status='GATK_RUNNING'),
                _state_item(org_id=ORG_BIOCORP, status='VEP_COMPLETED'),
                _state_item(org_id=ORG_ACME, status='INITIALIZED'),
            ]
        }

        result = status_query.handler(_api_event('SAM-001', org_id=ORG_ACME), {})
        body = json.loads(result['body'])

        assert result['statusCode'] == 200
        assert body['count'] == 2
        for record in body['records']:
            assert record['OrganizationID'] == ORG_ACME

    def test_no_org_items_returns_404(self):
        """When no items match the caller's org, return 404 (not empty 200)."""
        mock_table = _mock_table()
        mock_table.query.return_value = {
            'Items': [
                _state_item(org_id=ORG_BIOCORP),
            ]
        }

        result = status_query.handler(_api_event('SAM-001', org_id=ORG_ACME), {})
        assert result['statusCode'] == 404
        body = json.loads(result['body'])
        assert 'error' in body


class TestRoleAccess:
    """Test that different roles can access status queries."""

    def test_viewer_can_query_status(self):
        mock_table = _mock_table()
        mock_table.query.return_value = {'Items': [_state_item()]}

        result = status_query.handler(_api_event('SAM-001', groups='["viewer"]'), {})
        assert result['statusCode'] == 200

    def test_operator_can_query_status(self):
        mock_table = _mock_table()
        mock_table.query.return_value = {'Items': [_state_item()]}

        result = status_query.handler(_api_event('SAM-001', groups='["operator"]'), {})
        assert result['statusCode'] == 200

    def test_admin_can_query_status(self):
        mock_table = _mock_table()
        mock_table.query.return_value = {'Items': [_state_item()]}

        result = status_query.handler(_api_event('SAM-001', groups='["admin"]'), {})
        assert result['statusCode'] == 200

    def test_no_auth_returns_401(self):
        event = {'pathParameters': {'sample_id': 'SAM-001'}}
        result = status_query.handler(event, {})
        assert result['statusCode'] == 401

    def test_no_org_returns_403(self):
        event = {
            'pathParameters': {'sample_id': 'SAM-001'},
            'requestContext': {
                'authorizer': {
                    'claims': {
                        'sub': 'test-user',
                        'email': 'test@example.com',
                        'cognito:groups': '["viewer"]',
                    }
                }
            },
        }
        result = status_query.handler(event, {})
        assert result['statusCode'] == 403

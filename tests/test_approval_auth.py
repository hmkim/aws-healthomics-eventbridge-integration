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

# Add approval_handler and shared to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lambda_function', 'approval_handler'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lambda_function', 'shared'))

# Patch boto3 before importing
with patch('boto3.resource') as mock_resource, \
     patch('boto3.client') as mock_client:
    import approval_handler

ORG_ID = 'ORG-TEST'
OTHER_ORG = 'ORG-OTHER'


def _auth_event(body, org_id=ORG_ID, groups='["admin"]'):
    """Build an API Gateway event with Cognito auth claims."""
    return {
        'body': json.dumps(body) if isinstance(body, dict) else body,
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


def _mock_resources():
    """Set up mocked state_table and sfn client with proper exception classes."""
    mock_table = MagicMock()
    mock_sfn = MagicMock()

    # Create real exception classes so `except sfn.exceptions.X` works
    class TaskTimedOut(Exception):
        pass

    class InvalidToken(Exception):
        pass

    mock_sfn.exceptions = MagicMock()
    mock_sfn.exceptions.TaskTimedOut = TaskTimedOut
    mock_sfn.exceptions.InvalidToken = InvalidToken

    approval_handler.state_table = mock_table
    approval_handler.sfn = mock_sfn
    return mock_table, mock_sfn


def _approval_item(sample_id='SAM-001', org_id=ORG_ID, token='task-token-abc'):
    """Build a DynamoDB item with AWAITING_APPROVAL status."""
    return {
        'SampleID': sample_id,
        'Timestamp': '2026-02-19T10:00:00.000Z',
        'Status': 'AWAITING_APPROVAL',
        'ApprovalToken': token,
        'OrganizationID': org_id,
        'SubmitterEmail': 'submitter@test.example.com',
    }


class TestApprovalRoleAccess:
    """Test that only admin role can access approval handler."""

    def test_admin_can_approve(self):
        mock_table, mock_sfn = _mock_resources()
        mock_table.query.return_value = {'Items': [_approval_item()]}

        event = _auth_event({'sample_id': 'SAM-001', 'decision': 'APPROVED'}, groups='["admin"]')
        result = approval_handler.handler(event, {})

        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['decision'] == 'APPROVED'
        mock_sfn.send_task_success.assert_called_once()

    def test_operator_gets_403(self):
        event = _auth_event(
            {'sample_id': 'SAM-001', 'decision': 'APPROVED'},
            groups='["operator"]',
        )
        result = approval_handler.handler(event, {})

        assert result['statusCode'] == 403

    def test_viewer_gets_403(self):
        event = _auth_event(
            {'sample_id': 'SAM-001', 'decision': 'APPROVED'},
            groups='["viewer"]',
        )
        result = approval_handler.handler(event, {})

        assert result['statusCode'] == 403

    def test_no_auth_context_gets_401(self):
        event = {'body': json.dumps({'sample_id': 'SAM-001', 'decision': 'APPROVED'})}
        result = approval_handler.handler(event, {})

        assert result['statusCode'] == 401


class TestApprovalOrgIsolation:
    """Test that approval handler enforces organization boundaries."""

    def test_cross_org_sample_returns_404(self):
        """Admin from ORG-TEST cannot approve a sample belonging to ORG-OTHER."""
        mock_table, mock_sfn = _mock_resources()
        mock_table.query.return_value = {
            'Items': [_approval_item(org_id=OTHER_ORG)]
        }

        event = _auth_event({'sample_id': 'SAM-001', 'decision': 'APPROVED'}, org_id=ORG_ID)
        result = approval_handler.handler(event, {})

        assert result['statusCode'] == 404
        mock_sfn.send_task_success.assert_not_called()

    def test_same_org_sample_succeeds(self):
        """Admin from ORG-TEST can approve a sample belonging to ORG-TEST."""
        mock_table, mock_sfn = _mock_resources()
        mock_table.query.return_value = {
            'Items': [_approval_item(org_id=ORG_ID)]
        }

        event = _auth_event({'sample_id': 'SAM-001', 'decision': 'APPROVED'}, org_id=ORG_ID)
        result = approval_handler.handler(event, {})

        assert result['statusCode'] == 200

    def test_first_matching_item_wrong_org_returns_404(self):
        """Handler picks the first AWAITING_APPROVAL item; if it belongs to another org, returns 404."""
        mock_table, mock_sfn = _mock_resources()
        # DynamoDB returns other-org item first
        mock_table.query.return_value = {
            'Items': [
                _approval_item(org_id=OTHER_ORG, token='other-token'),
                _approval_item(org_id=ORG_ID, token='my-token'),
            ]
        }

        event = _auth_event({'sample_id': 'SAM-001', 'decision': 'APPROVED'}, org_id=ORG_ID)
        result = approval_handler.handler(event, {})

        # Handler takes the first AWAITING_APPROVAL match, checks org, returns 404
        assert result['statusCode'] == 404
        mock_sfn.send_task_success.assert_not_called()


class TestApprovalDecisions:
    """Test approve and reject decision paths."""

    def test_approve_calls_send_task_success(self):
        mock_table, mock_sfn = _mock_resources()
        mock_table.query.return_value = {'Items': [_approval_item()]}

        event = _auth_event({'sample_id': 'SAM-001', 'decision': 'APPROVED', 'reason': 'Looks good'})
        result = approval_handler.handler(event, {})

        assert result['statusCode'] == 200
        mock_sfn.send_task_success.assert_called_once()
        output = json.loads(mock_sfn.send_task_success.call_args[1]['output'])
        assert output['decision'] == 'APPROVED'
        assert output['approved_by'] == 'Test Admin'

    def test_reject_calls_send_task_failure(self):
        mock_table, mock_sfn = _mock_resources()
        mock_table.query.return_value = {'Items': [_approval_item()]}

        event = _auth_event({'sample_id': 'SAM-001', 'decision': 'REJECTED', 'reason': 'QC failed'})
        result = approval_handler.handler(event, {})

        assert result['statusCode'] == 200
        mock_sfn.send_task_failure.assert_called_once()
        cause = json.loads(mock_sfn.send_task_failure.call_args[1]['cause'])
        assert cause['decision'] == 'REJECTED'
        assert cause['reason'] == 'QC failed'

    def test_updates_dynamodb_after_approval(self):
        mock_table, mock_sfn = _mock_resources()
        mock_table.query.return_value = {'Items': [_approval_item()]}

        event = _auth_event({'sample_id': 'SAM-001', 'decision': 'APPROVED'})
        approval_handler.handler(event, {})

        mock_table.update_item.assert_called_once()
        update_args = mock_table.update_item.call_args[1]
        assert update_args['Key'] == {'SampleID': 'SAM-001', 'Timestamp': '2026-02-19T10:00:00.000Z'}
        assert ':status' in update_args['ExpressionAttributeValues']

    def test_approved_by_defaults_to_auth_display_name(self):
        mock_table, mock_sfn = _mock_resources()
        mock_table.query.return_value = {'Items': [_approval_item()]}

        # Don't send approved_by in body
        event = _auth_event({'sample_id': 'SAM-001', 'decision': 'APPROVED'})
        result = approval_handler.handler(event, {})

        body = json.loads(result['body'])
        assert body['approved_by'] == 'Test Admin'


class TestApprovalValidation:
    """Test input validation."""

    def test_missing_sample_id_returns_400(self):
        mock_table, _ = _mock_resources()

        event = _auth_event({'decision': 'APPROVED'})
        result = approval_handler.handler(event, {})

        assert result['statusCode'] == 400
        assert 'sample_id' in json.loads(result['body'])['error']

    def test_invalid_decision_returns_400(self):
        mock_table, _ = _mock_resources()

        event = _auth_event({'sample_id': 'SAM-001', 'decision': 'MAYBE'})
        result = approval_handler.handler(event, {})

        assert result['statusCode'] == 400

    def test_no_pending_approval_returns_404(self):
        mock_table, _ = _mock_resources()
        # Item exists but is not AWAITING_APPROVAL
        mock_table.query.return_value = {
            'Items': [{
                'SampleID': 'SAM-001',
                'Timestamp': '2026-02-19T10:00:00.000Z',
                'Status': 'GATK_RUNNING',
                'OrganizationID': ORG_ID,
            }]
        }

        event = _auth_event({'sample_id': 'SAM-001', 'decision': 'APPROVED'})
        result = approval_handler.handler(event, {})

        assert result['statusCode'] == 404

    def test_invalid_json_body_returns_400(self):
        mock_table, _ = _mock_resources()

        event = _auth_event('not valid json')
        result = approval_handler.handler(event, {})

        assert result['statusCode'] == 400

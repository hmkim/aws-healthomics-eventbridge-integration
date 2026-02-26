import os
import json
import pytest
from unittest.mock import patch, MagicMock, call

# Set env vars BEFORE import
os.environ['SNS_TOPIC_ARN'] = 'arn:aws:sns:us-east-1:123456789012:test-topic'
os.environ['USER_POOL_ID'] = 'us-east-1_TestPool'
os.environ['DASHBOARD_URL'] = 'https://dashboard.example.com'
os.environ['LOG_LEVEL'] = 'DEBUG'
os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'

# Patch boto3 before importing
with patch('boto3.client') as mock_client:
    mock_sns = MagicMock()
    mock_cognito = MagicMock()

    def _client_factory(service, **kwargs):
        if service == 'sns':
            return mock_sns
        if service == 'cognito-idp':
            return mock_cognito
        return MagicMock()

    mock_client.side_effect = _client_factory
    from lambda_function.failure_notification import failure_notification


def _reset_mocks():
    mock_sns.reset_mock()
    mock_cognito.reset_mock()
    failure_notification.sns = mock_sns
    failure_notification.cognito = mock_cognito


def _base_event(**overrides):
    event = {
        'sample_id': 'ACME-RD-001',
        'project_id': 'Rare-Disease-Dx-2026',
        'submitter_email': 'operator@acme.example.com',
        'organization_id': 'ORG-ACME',
        'failure_type': 'WORKFLOW_FAILED',
        'error': {'Error': 'States.TaskFailed', 'Cause': 'HealthOmics run failed'},
    }
    event.update(overrides)
    return event


class TestFailureNotificationHandler:
    """Test the main handler function."""

    def test_sends_sns_notification(self):
        _reset_mocks()
        mock_cognito.list_users_in_group.return_value = {'Users': []}

        result = failure_notification.handler(_base_event(), {})

        assert result['notification_sent'] is True
        assert result['sample_id'] == 'ACME-RD-001'
        assert result['failure_type'] == 'WORKFLOW_FAILED'
        mock_sns.publish.assert_called_once()
        call_kwargs = mock_sns.publish.call_args[1]
        assert call_kwargs['TopicArn'] == 'arn:aws:sns:us-east-1:123456789012:test-topic'
        assert '[Pipeline Failed]' in call_kwargs['Subject']
        assert 'ACME-RD-001' in call_kwargs['Subject']
        assert 'ACME-RD-001' in call_kwargs['Message']
        assert 'operator@acme.example.com' in call_kwargs['Message']

    def test_includes_dashboard_url(self):
        _reset_mocks()
        mock_cognito.list_users_in_group.return_value = {'Users': []}

        failure_notification.handler(_base_event(), {})

        message = mock_sns.publish.call_args[1]['Message']
        assert 'https://dashboard.example.com/status.html?sample_id=ACME-RD-001' in message

    def test_returns_recipients_list(self):
        _reset_mocks()
        mock_cognito.list_users_in_group.return_value = {'Users': []}

        result = failure_notification.handler(_base_event(), {})

        assert 'operator@acme.example.com' in result['recipients']

    def test_adds_org_admins_to_recipients(self):
        _reset_mocks()
        mock_cognito.list_users_in_group.return_value = {
            'Users': [
                {
                    'Username': 'admin@acme.example.com',
                    'Attributes': [
                        {'Name': 'email', 'Value': 'admin@acme.example.com'},
                        {'Name': 'custom:organization_id', 'Value': 'ORG-ACME'},
                    ],
                },
                {
                    'Username': 'admin@biocorp.example.com',
                    'Attributes': [
                        {'Name': 'email', 'Value': 'admin@biocorp.example.com'},
                        {'Name': 'custom:organization_id', 'Value': 'ORG-BIOCORP'},
                    ],
                },
            ]
        }

        result = failure_notification.handler(_base_event(), {})

        assert 'operator@acme.example.com' in result['recipients']
        assert 'admin@acme.example.com' in result['recipients']
        # BioCorp admin should NOT be included
        assert 'admin@biocorp.example.com' not in result['recipients']

    def test_deduplicates_submitter_if_also_admin(self):
        _reset_mocks()
        mock_cognito.list_users_in_group.return_value = {
            'Users': [
                {
                    'Username': 'operator@acme.example.com',
                    'Attributes': [
                        {'Name': 'email', 'Value': 'operator@acme.example.com'},
                        {'Name': 'custom:organization_id', 'Value': 'ORG-ACME'},
                    ],
                },
            ]
        }

        result = failure_notification.handler(
            _base_event(submitter_email='operator@acme.example.com'), {}
        )

        # Should appear only once
        assert result['recipients'].count('operator@acme.example.com') == 1

    def test_subject_truncated_to_100_chars(self):
        _reset_mocks()
        mock_cognito.list_users_in_group.return_value = {'Users': []}

        long_sample_id = 'A' * 120
        failure_notification.handler(_base_event(sample_id=long_sample_id), {})

        subject = mock_sns.publish.call_args[1]['Subject']
        assert len(subject) <= 100
        assert subject.endswith('...')

    def test_handles_missing_fields_gracefully(self):
        _reset_mocks()
        mock_cognito.list_users_in_group.return_value = {'Users': []}

        result = failure_notification.handler({}, {})

        assert result['sample_id'] == 'Unknown'
        assert result['failure_type'] == 'WORKFLOW_FAILED'
        assert result['notification_sent'] is True

    def test_sns_failure_returns_notification_sent_false(self):
        _reset_mocks()
        mock_cognito.list_users_in_group.return_value = {'Users': []}
        mock_sns.publish.side_effect = Exception('SNS error')

        result = failure_notification.handler(_base_event(), {})

        assert result['notification_sent'] is False

    def test_no_sns_topic_skips_notification(self):
        _reset_mocks()
        mock_cognito.list_users_in_group.return_value = {'Users': []}

        original_arn = failure_notification.SNS_TOPIC_ARN
        try:
            failure_notification.SNS_TOPIC_ARN = ''
            result = failure_notification.handler(_base_event(), {})
            assert result['notification_sent'] is False
            mock_sns.publish.assert_not_called()
        finally:
            failure_notification.SNS_TOPIC_ARN = original_arn


class TestFailureDescriptions:
    """Test failure type description mapping."""

    def test_workflow_failed_description(self):
        _reset_mocks()
        mock_cognito.list_users_in_group.return_value = {'Users': []}

        failure_notification.handler(_base_event(failure_type='WORKFLOW_FAILED'), {})

        message = mock_sns.publish.call_args[1]['Message']
        assert 'HealthOmics workflow execution failed' in message

    def test_workflow_timeout_description(self):
        _reset_mocks()
        mock_cognito.list_users_in_group.return_value = {'Users': []}

        failure_notification.handler(_base_event(failure_type='WORKFLOW_TIMEOUT'), {})

        message = mock_sns.publish.call_args[1]['Message']
        assert 'exceeded the maximum execution time' in message

    def test_approval_timeout_description(self):
        _reset_mocks()
        mock_cognito.list_users_in_group.return_value = {'Users': []}

        failure_notification.handler(_base_event(failure_type='APPROVAL_TIMEOUT'), {})

        message = mock_sns.publish.call_args[1]['Message']
        assert 'approval was not received' in message

    def test_validation_failed_description(self):
        _reset_mocks()
        mock_cognito.list_users_in_group.return_value = {'Users': []}

        failure_notification.handler(_base_event(failure_type='VALIDATION_FAILED'), {})

        message = mock_sns.publish.call_args[1]['Message']
        assert 'Input validation failed' in message

    def test_unknown_failure_type_uses_raw_value(self):
        _reset_mocks()
        mock_cognito.list_users_in_group.return_value = {'Users': []}

        failure_notification.handler(_base_event(failure_type='CUSTOM_ERROR'), {})

        message = mock_sns.publish.call_args[1]['Message']
        assert 'CUSTOM_ERROR' in message


class TestParseErrorDetail:
    """Test the _parse_error_detail helper."""

    def test_dict_with_cause_string(self):
        result = failure_notification._parse_error_detail({
            'Error': 'States.TaskFailed',
            'Cause': 'HealthOmics run failed',
        })
        assert result == 'HealthOmics run failed'

    def test_dict_with_json_cause(self):
        cause = json.dumps({'reason': 'S3 bucket not found', 'code': 'NoSuchBucket'})
        result = failure_notification._parse_error_detail({
            'Error': 'States.TaskFailed',
            'Cause': cause,
        })
        assert result == 'S3 bucket not found'

    def test_dict_with_error_only(self):
        result = failure_notification._parse_error_detail({
            'Error': 'Lambda.ServiceException',
        })
        assert result == 'Lambda.ServiceException'

    def test_empty_dict(self):
        result = failure_notification._parse_error_detail({})
        assert result == 'Unknown error'

    def test_string_input(self):
        result = failure_notification._parse_error_detail('Something went wrong')
        assert result == 'Something went wrong'

    def test_json_string_input(self):
        error_str = json.dumps({'Error': 'X', 'Cause': 'detailed reason'})
        result = failure_notification._parse_error_detail(error_str)
        assert result == 'detailed reason'

    def test_none_input(self):
        result = failure_notification._parse_error_detail(None)
        assert result == 'Unknown error'

    def test_empty_string(self):
        result = failure_notification._parse_error_detail('')
        assert result == 'Unknown error'


class TestGetOrgAdminEmails:
    """Test the _get_org_admin_emails helper."""

    def test_returns_matching_org_admins(self):
        _reset_mocks()
        mock_cognito.list_users_in_group.return_value = {
            'Users': [
                {
                    'Username': 'admin1@acme.example.com',
                    'Attributes': [
                        {'Name': 'email', 'Value': 'admin1@acme.example.com'},
                        {'Name': 'custom:organization_id', 'Value': 'ORG-ACME'},
                    ],
                },
                {
                    'Username': 'admin2@other.example.com',
                    'Attributes': [
                        {'Name': 'email', 'Value': 'admin2@other.example.com'},
                        {'Name': 'custom:organization_id', 'Value': 'ORG-OTHER'},
                    ],
                },
            ]
        }

        result = failure_notification._get_org_admin_emails('ORG-ACME')
        assert result == ['admin1@acme.example.com']

    def test_returns_empty_for_no_pool_id(self):
        _reset_mocks()
        original = failure_notification.USER_POOL_ID
        try:
            failure_notification.USER_POOL_ID = ''
            result = failure_notification._get_org_admin_emails('ORG-ACME')
            assert result == []
            mock_cognito.list_users_in_group.assert_not_called()
        finally:
            failure_notification.USER_POOL_ID = original

    def test_returns_empty_for_no_org_id(self):
        _reset_mocks()
        result = failure_notification._get_org_admin_emails('')
        assert result == []
        mock_cognito.list_users_in_group.assert_not_called()

    def test_handles_cognito_exception(self):
        _reset_mocks()
        mock_cognito.list_users_in_group.side_effect = Exception('Cognito error')

        result = failure_notification._get_org_admin_emails('ORG-ACME')
        assert result == []

    def test_skips_users_without_email(self):
        _reset_mocks()
        mock_cognito.list_users_in_group.return_value = {
            'Users': [
                {
                    'Username': 'no-email-user',
                    'Attributes': [
                        {'Name': 'custom:organization_id', 'Value': 'ORG-ACME'},
                    ],
                },
            ]
        }

        result = failure_notification._get_org_admin_emails('ORG-ACME')
        assert result == []

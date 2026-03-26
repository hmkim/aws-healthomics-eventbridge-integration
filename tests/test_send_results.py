import sys
import os
import json
import pytest
from unittest.mock import patch, MagicMock, call

# Set env vars BEFORE import
os.environ['WORKFLOW_STATE_TABLE'] = 'TestWorkflowState'
os.environ['SES_SENDER_EMAIL'] = 'noreply@test.example.com'
os.environ['LOG_LEVEL'] = 'DEBUG'
os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'

# Add Lambda paths
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lambda_function', 'send_results'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lambda_function', 'shared'))

# Patch boto3 before importing
with patch('boto3.resource') as mock_resource, \
     patch('boto3.client') as mock_client:
    import send_results

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


def _approved_record(sample_id='SAM-001', org_id=ORG_ID, with_uris=True):
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
    }
    if with_uris:
        item['GATKOutputUri'] = 's3://output-bucket/outputs/12345'
        item['VEPOutputUri'] = 's3://output-bucket/outputs/12346'
    return item


def _mock_services():
    """Set up mocked services."""
    mock_table = MagicMock()
    mock_s3 = MagicMock()
    mock_ses = MagicMock()
    # Simulate SES production mode (quota > 200 bypasses recipient filtering)
    mock_ses.get_send_quota.return_value = {'Max24HourSend': 50000.0}

    send_results.state_table = mock_table
    send_results.s3 = mock_s3
    send_results.ses = mock_ses

    return mock_table, mock_s3, mock_ses


def _setup_s3_list(mock_s3, gatk_files=None, vep_files=None):
    """Configure S3 list_objects_v2 paginator to return test files."""
    paginator = MagicMock()
    mock_s3.get_paginator.return_value = paginator

    call_count = [0]

    def paginate_side_effect(**kwargs):
        prefix = kwargs.get('Prefix', '')
        if '12345' in prefix:
            files = gatk_files or [
                'outputs/12345/sample.bam',
                'outputs/12345/sample.vcf.gz',
                'outputs/12345/sample.duplicate_metrics.metrics',
                'outputs/12345/sample.variant_calling.stats',
                'outputs/12345/sample.bam.bai',  # should be excluded
            ]
        elif '12346' in prefix:
            files = vep_files or [
                'outputs/12346/sample.vep.vcf.gz',
                'outputs/12346/sample.vep.html',  # should be excluded
            ]
        else:
            files = []
        return [{'Contents': [{'Key': f} for f in files]}]

    paginator.paginate.side_effect = paginate_side_effect

    mock_s3.generate_presigned_url.side_effect = lambda method, **kw: \
        f"https://presigned-url/{kw['Params']['Key']}"


class TestSendResultsAccess:
    """Test role-based access control."""

    def test_admin_can_access(self):
        mock_table, mock_s3, mock_ses = _mock_services()
        mock_table.query.return_value = {'Items': [_approved_record()]}
        _setup_s3_list(mock_s3)

        result = send_results.handler(
            _auth_event({'sample_id': 'SAM-001'}, groups='["admin"]'), {})
        assert result['statusCode'] == 200

    def test_operator_gets_403(self):
        result = send_results.handler(
            _auth_event({'sample_id': 'SAM-001'}, groups='["operator"]'), {})
        assert result['statusCode'] == 403

    def test_viewer_gets_403(self):
        result = send_results.handler(
            _auth_event({'sample_id': 'SAM-001'}, groups='["viewer"]'), {})
        assert result['statusCode'] == 403


class TestSendResultsValidation:
    """Test input validation."""

    def test_missing_sample_id_returns_400(self):
        _mock_services()
        result = send_results.handler(_auth_event({}), {})
        assert result['statusCode'] == 400
        assert 'sample_id' in json.loads(result['body'])['error']

    def test_invalid_json_returns_400(self):
        _mock_services()
        result = send_results.handler(_auth_event('not json'), {})
        assert result['statusCode'] == 400

    def test_additional_emails_not_list_returns_400(self):
        _mock_services()
        result = send_results.handler(
            _auth_event({'sample_id': 'SAM-001', 'additional_emails': 'not-a-list'}), {})
        assert result['statusCode'] == 400


class TestSendResultsOrgIsolation:
    """Test organization boundary enforcement."""

    def test_cross_org_returns_404(self):
        mock_table, mock_s3, mock_ses = _mock_services()
        mock_table.query.return_value = {
            'Items': [_approved_record(org_id=OTHER_ORG)]
        }

        result = send_results.handler(
            _auth_event({'sample_id': 'SAM-001'}, org_id=ORG_ID), {})

        assert result['statusCode'] == 404
        mock_ses.send_email.assert_not_called()

    def test_no_approved_record_returns_404(self):
        mock_table, mock_s3, mock_ses = _mock_services()
        mock_table.query.return_value = {'Items': []}

        result = send_results.handler(
            _auth_event({'sample_id': 'SAM-001'}), {})
        assert result['statusCode'] == 404


class TestSendResultsNoOutputUris:
    """Test behavior when output URIs are missing."""

    def test_no_output_uris_returns_400(self):
        mock_table, mock_s3, mock_ses = _mock_services()
        mock_table.query.return_value = {
            'Items': [_approved_record(with_uris=False)]
        }

        result = send_results.handler(
            _auth_event({'sample_id': 'SAM-001'}), {})
        assert result['statusCode'] == 400
        assert 'output uri' in json.loads(result['body'])['error'].lower()


class TestSendResultsS3ListAndPresign:
    """Test S3 file listing and presigned URL generation."""

    def test_lists_gatk_and_vep_files(self):
        mock_table, mock_s3, mock_ses = _mock_services()
        mock_table.query.return_value = {'Items': [_approved_record()]}
        _setup_s3_list(mock_s3)

        result = send_results.handler(
            _auth_event({'sample_id': 'SAM-001'}), {})
        body = json.loads(result['body'])

        # GATK: .bam, .vcf.gz, .metrics, .stats (4 files, .bam.bai excluded)
        assert body['gatk_file_count'] == 4
        # VEP: .vcf.gz only (1 file, .html excluded)
        assert body['vep_file_count'] == 1

    def test_generates_presigned_urls_with_24h_expiry(self):
        mock_table, mock_s3, mock_ses = _mock_services()
        mock_table.query.return_value = {'Items': [_approved_record()]}
        _setup_s3_list(mock_s3)

        send_results.handler(_auth_event({'sample_id': 'SAM-001'}), {})

        # Check presigned URL calls
        presign_calls = mock_s3.generate_presigned_url.call_args_list
        assert len(presign_calls) > 0
        for c in presign_calls:
            assert c[1]['ExpiresIn'] == 86400


class TestSendResultsRecipients:
    """Test recipient list construction."""

    def test_submitter_included_by_default(self):
        mock_table, mock_s3, mock_ses = _mock_services()
        mock_table.query.return_value = {'Items': [_approved_record()]}
        _setup_s3_list(mock_s3)

        result = send_results.handler(
            _auth_event({'sample_id': 'SAM-001'}), {})
        body = json.loads(result['body'])

        assert 'submitter@test.example.com' in body['recipients']

    def test_additional_emails_included(self):
        mock_table, mock_s3, mock_ses = _mock_services()
        mock_table.query.return_value = {'Items': [_approved_record()]}
        _setup_s3_list(mock_s3)

        result = send_results.handler(
            _auth_event({
                'sample_id': 'SAM-001',
                'additional_emails': ['extra@test.com', 'another@test.com'],
            }), {})
        body = json.loads(result['body'])

        assert 'extra@test.com' in body['recipients']
        assert 'another@test.com' in body['recipients']
        assert 'submitter@test.example.com' in body['recipients']

    def test_duplicate_emails_deduplicated(self):
        mock_table, mock_s3, mock_ses = _mock_services()
        mock_table.query.return_value = {'Items': [_approved_record()]}
        _setup_s3_list(mock_s3)

        result = send_results.handler(
            _auth_event({
                'sample_id': 'SAM-001',
                'additional_emails': ['submitter@test.example.com', 'extra@test.com'],
            }), {})
        body = json.loads(result['body'])

        # submitter@test.example.com should only appear once
        assert body['recipients'].count('submitter@test.example.com') == 1
        assert len(body['recipients']) == 2


class TestSendResultsSES:
    """Test SES email sending."""

    def test_calls_ses_send_email(self):
        mock_table, mock_s3, mock_ses = _mock_services()
        mock_table.query.return_value = {'Items': [_approved_record()]}
        _setup_s3_list(mock_s3)

        send_results.handler(_auth_event({'sample_id': 'SAM-001'}), {})

        mock_ses.send_email.assert_called_once()
        ses_call = mock_ses.send_email.call_args[1]
        assert ses_call['Source'] == 'noreply@test.example.com'
        assert 'submitter@test.example.com' in ses_call['Destination']['ToAddresses']
        assert '[LIMS]' in ses_call['Message']['Subject']['Data']
        assert 'SAM-001' in ses_call['Message']['Subject']['Data']
        assert 'Html' in ses_call['Message']['Body']

    def test_email_html_contains_sample_info(self):
        mock_table, mock_s3, mock_ses = _mock_services()
        mock_table.query.return_value = {'Items': [_approved_record()]}
        _setup_s3_list(mock_s3)

        send_results.handler(_auth_event({'sample_id': 'SAM-001'}), {})

        html_body = mock_ses.send_email.call_args[1]['Message']['Body']['Html']['Data']
        assert 'SAM-001' in html_body
        assert 'PROJ-001' in html_body
        assert '24 hours' in html_body

    def test_ses_sender_not_configured_returns_500(self):
        mock_table, mock_s3, mock_ses = _mock_services()
        original = send_results.SES_SENDER_EMAIL
        send_results.SES_SENDER_EMAIL = ''
        try:
            result = send_results.handler(
                _auth_event({'sample_id': 'SAM-001'}), {})
            assert result['statusCode'] == 500
            assert 'SES_SENDER_EMAIL' in json.loads(result['body'])['error']
        finally:
            send_results.SES_SENDER_EMAIL = original


class TestSendResultsSelectsLatestApproved:
    """Test that the handler picks the latest COMPLETED_APPROVED record."""

    def test_skips_non_approved_records(self):
        mock_table, mock_s3, mock_ses = _mock_services()
        mock_table.query.return_value = {
            'Items': [
                {
                    'SampleID': 'SAM-001',
                    'Timestamp': '2026-02-21T10:00:00.000Z',
                    'Status': 'GATK_RUNNING',
                    'OrganizationID': ORG_ID,
                },
                _approved_record(),
            ]
        }
        _setup_s3_list(mock_s3)

        result = send_results.handler(
            _auth_event({'sample_id': 'SAM-001'}), {})
        assert result['statusCode'] == 200

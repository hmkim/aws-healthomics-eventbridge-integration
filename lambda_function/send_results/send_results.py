import boto3
import os
import json
import logging
import sys
from decimal import Decimal
from urllib.parse import urlparse
from boto3.dynamodb.conditions import Key

# Add shared layer to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
from auth_middleware import require_auth, cors_headers

WORKFLOW_STATE_TABLE = os.environ.get('WORKFLOW_STATE_TABLE', 'GenomicWorkflowState')
SES_SENDER_EMAIL = os.environ.get('SES_SENDER_EMAIL', '')
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')

dynamodb = boto3.resource('dynamodb')
state_table = dynamodb.Table(WORKFLOW_STATE_TABLE)
s3 = boto3.client('s3')
ses = boto3.client('ses')

logging.basicConfig(level=LOG_LEVEL)
logger = logging.getLogger(__name__)

PRESIGNED_URL_EXPIRY = 86400  # 24 hours

# File extensions to include per pipeline stage
GATK_EXTENSIONS = ('.bam', '.vcf.gz', '.metrics', '.stats')
VEP_EXTENSIONS = ('.vcf.gz',)


def _parse_s3_uri(uri):
    """Parse s3://bucket/key into (bucket, prefix)."""
    parsed = urlparse(uri)
    return parsed.netloc, parsed.path.lstrip('/')


def _list_result_files(bucket, prefix, extensions):
    """List S3 objects matching given extensions under a prefix."""
    files = []
    paginator = s3.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get('Contents', []):
            key = obj['Key']
            if any(key.endswith(ext) for ext in extensions):
                files.append(key)
    return files


def _generate_presigned_urls(bucket, keys):
    """Generate presigned URLs for a list of S3 keys."""
    urls = []
    for key in keys:
        url = s3.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket, 'Key': key},
            ExpiresIn=PRESIGNED_URL_EXPIRY,
        )
        filename = key.split('/')[-1]
        urls.append({'filename': filename, 'url': url, 'key': key})
    return urls


def _build_email_html(sample_id, project_id, analysis_type, approved_by,
                      approval_date, gatk_files, vep_files):
    """Build HTML email body with download links."""
    gatk_section = ''
    if gatk_files:
        gatk_rows = ''.join(
            f'<tr><td style="padding:8px;border-bottom:1px solid #eee;">'
            f'<a href="{f["url"]}">{f["filename"]}</a></td></tr>'
            for f in gatk_files
        )
        gatk_section = f'''
        <h3 style="color:#333;margin-top:24px;">GATK Output Files</h3>
        <table style="width:100%;border-collapse:collapse;">{gatk_rows}</table>
        '''

    vep_section = ''
    if vep_files:
        vep_rows = ''.join(
            f'<tr><td style="padding:8px;border-bottom:1px solid #eee;">'
            f'<a href="{f["url"]}">{f["filename"]}</a></td></tr>'
            for f in vep_files
        )
        vep_section = f'''
        <h3 style="color:#333;margin-top:24px;">VEP Output Files</h3>
        <table style="width:100%;border-collapse:collapse;">{vep_rows}</table>
        '''

    return f'''
    <html>
    <body style="font-family:Arial,sans-serif;color:#333;max-width:600px;margin:0 auto;">
        <h2 style="color:#1a73e8;">Analysis Results Ready</h2>
        <table style="width:100%;border-collapse:collapse;margin-bottom:16px;">
            <tr><td style="padding:6px 12px;font-weight:bold;">Sample ID:</td>
                <td style="padding:6px 12px;">{sample_id}</td></tr>
            <tr><td style="padding:6px 12px;font-weight:bold;">Project:</td>
                <td style="padding:6px 12px;">{project_id}</td></tr>
            <tr><td style="padding:6px 12px;font-weight:bold;">Analysis Type:</td>
                <td style="padding:6px 12px;">{analysis_type}</td></tr>
            <tr><td style="padding:6px 12px;font-weight:bold;">Approved By:</td>
                <td style="padding:6px 12px;">{approved_by}</td></tr>
            <tr><td style="padding:6px 12px;font-weight:bold;">Approval Date:</td>
                <td style="padding:6px 12px;">{approval_date}</td></tr>
        </table>
        {gatk_section}
        {vep_section}
        <p style="color:#666;font-size:12px;margin-top:24px;padding-top:16px;border-top:1px solid #eee;">
            These download links expire in 24 hours. If the links have expired,
            please request a new email from the LIMS dashboard.
        </p>
    </body>
    </html>
    '''


def _is_ses_sandbox():
    """Check if SES is in sandbox mode by inspecting sending quota."""
    try:
        quota = ses.get_send_quota()
        # Sandbox accounts have Max24HourSend of 200
        return quota.get('Max24HourSend', 0) <= 200
    except Exception:
        # If we can't determine, assume sandbox for safety
        return True


def _filter_verified_recipients(recipients):
    """Filter recipients to only SES-verified emails.

    In production mode (SES out of sandbox), all recipients are allowed.
    In sandbox mode, only verified identities can receive email.

    Returns (verified_list, skipped_list).
    """
    if not _is_ses_sandbox():
        return recipients, []

    if not recipients:
        return [], []

    # Check verification status for all recipients in one call
    response = ses.get_identity_verification_attributes(Identities=recipients)
    attrs = response.get('VerificationAttributes', {})

    verified = []
    skipped = []
    for email in recipients:
        status = attrs.get(email, {}).get('VerificationStatus', '')
        if status == 'Success':
            verified.append(email)
        else:
            skipped.append(email)
            logger.warning(f"Skipping unverified SES recipient: {email}")

    return verified, skipped


@require_auth('admin')
def handler(event, context):
    """Generate presigned URLs for approved results and send via SES email."""
    auth = event['auth']
    org_id = auth['organization_id']

    try:
        body = json.loads(event.get('body', '{}'))
    except (json.JSONDecodeError, TypeError):
        return _error_response(400, 'Invalid JSON body')

    sample_id = body.get('sample_id')
    additional_emails = body.get('additional_emails', [])

    if not sample_id:
        return _error_response(400, 'sample_id is required')

    if not SES_SENDER_EMAIL:
        return _error_response(500, 'SES_SENDER_EMAIL not configured')

    # Validate additional_emails is a list of strings
    if not isinstance(additional_emails, list):
        return _error_response(400, 'additional_emails must be a list')

    # Query the latest COMPLETED_APPROVED record for this sample
    response = state_table.query(
        KeyConditionExpression=Key('SampleID').eq(sample_id),
        ScanIndexForward=False,  # newest first
    )
    items = response.get('Items', [])

    # Find the first COMPLETED_APPROVED item
    record = None
    for item in items:
        if item.get('Status') == 'COMPLETED_APPROVED':
            record = item
            break

    if not record:
        return _error_response(404, f'No approved results found for sample {sample_id}')

    # Verify organization
    if record.get('OrganizationID') != org_id:
        return _error_response(404, f'No approved results found for sample {sample_id}')

    gatk_output_uri = record.get('GATKOutputUri')
    vep_output_uri = record.get('VEPOutputUri')

    if not gatk_output_uri and not vep_output_uri:
        return _error_response(400,
            'No output URIs available. This sample may have been processed '
            'before output URI tracking was enabled.')

    # Collect result files and generate presigned URLs
    gatk_files = []
    if gatk_output_uri:
        bucket, prefix = _parse_s3_uri(gatk_output_uri)
        keys = _list_result_files(bucket, prefix, GATK_EXTENSIONS)
        gatk_files = _generate_presigned_urls(bucket, keys)

    vep_files = []
    if vep_output_uri:
        bucket, prefix = _parse_s3_uri(vep_output_uri)
        keys = _list_result_files(bucket, prefix, VEP_EXTENSIONS)
        vep_files = _generate_presigned_urls(bucket, keys)

    if not gatk_files and not vep_files:
        return _error_response(404, 'No matching result files found in S3 outputs')

    # Build recipient list: submitter + additional, deduplicated
    submitter_email = record.get('SubmitterEmail', '')
    all_recipients = list(dict.fromkeys(
        email.strip() for email in [submitter_email] + additional_emails
        if email and email.strip()
    ))

    if not all_recipients:
        return _error_response(400, 'No recipients available')

    # Filter to SES-verified recipients (required in sandbox mode)
    recipients, skipped = _filter_verified_recipients(all_recipients)

    if not recipients:
        return _error_response(400,
            f'No verified recipients. SES sandbox requires all recipients '
            f'to be verified. Unverified: {", ".join(skipped)}')

    # Build and send email
    project_id = record.get('ProjectID', 'Unknown')
    analysis_type = record.get('AnalysisType', 'WGS')
    approved_by = record.get('ApprovedBy', 'Unknown')
    approval_date = record.get('ApprovalDecidedAt', record.get('UpdatedAt', ''))

    html_body = _build_email_html(
        sample_id, project_id, analysis_type, approved_by,
        approval_date, gatk_files, vep_files,
    )

    subject = f'[LIMS] Analysis results ready for {sample_id}'

    try:
        ses.send_email(
            Source=SES_SENDER_EMAIL,
            Destination={'ToAddresses': recipients},
            Message={
                'Subject': {'Data': subject, 'Charset': 'UTF-8'},
                'Body': {
                    'Html': {'Data': html_body, 'Charset': 'UTF-8'},
                },
            },
        )
    except ses.exceptions.MessageRejected as e:
        error_msg = str(e)
        logger.error(f"SES MessageRejected for {sample_id}: {error_msg}")
        return _error_response(502, f'Email delivery failed: {error_msg}')
    except Exception as e:
        logger.error(f"SES send failed for {sample_id}: {e}")
        return _error_response(502, f'Email delivery failed: {str(e)}')

    logger.info(f"Sent results email for {sample_id} to {recipients}")

    skipped_msg = ''
    if skipped:
        skipped_msg = f' (skipped unverified: {", ".join(skipped)})'

    return {
        'statusCode': 200,
        'headers': cors_headers(),
        'body': json.dumps({
            'message': f'Results email sent for {sample_id}{skipped_msg}',
            'recipients': recipients,
            'skipped_recipients': skipped,
            'gatk_file_count': len(gatk_files),
            'vep_file_count': len(vep_files),
        }),
    }


def _error_response(status_code, message):
    return {
        'statusCode': status_code,
        'headers': cors_headers(),
        'body': json.dumps({'error': message}),
    }

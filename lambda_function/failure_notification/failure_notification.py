import boto3
import os
import json
import logging

SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN', '')
USER_POOL_ID = os.environ.get('USER_POOL_ID', '')
DASHBOARD_URL = os.environ.get('DASHBOARD_URL', '')
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')

sns = boto3.client('sns')
cognito = boto3.client('cognito-idp')

logging.basicConfig(level=LOG_LEVEL)
logger = logging.getLogger(__name__)

# Map internal failure types to human-readable descriptions
FAILURE_DESCRIPTIONS = {
    'WORKFLOW_FAILED': 'HealthOmics workflow execution failed',
    'WORKFLOW_TIMEOUT': 'HealthOmics workflow exceeded the maximum execution time',
    'APPROVAL_TIMEOUT': 'Admin approval was not received within the allowed period',
    'VALIDATION_FAILED': 'Input validation failed before pipeline could start',
}


def _get_org_admin_emails(org_id):
    """Look up admin users for the given organization from Cognito."""
    if not USER_POOL_ID or not org_id:
        return []

    try:
        admin_emails = []
        response = cognito.list_users_in_group(
            UserPoolId=USER_POOL_ID,
            GroupName='admin',
            Limit=60,
        )

        for user in response.get('Users', []):
            attrs = {a['Name']: a['Value'] for a in user.get('Attributes', [])}
            if attrs.get('custom:organization_id') == org_id:
                email = attrs.get('email', '')
                if email:
                    admin_emails.append(email)

        return admin_emails
    except Exception as e:
        logger.warning(f"Could not look up org admins for {org_id}: {e}")
        return []


def _parse_error_detail(error_info):
    """Extract a readable error message from the Step Functions error payload."""
    if not error_info:
        return 'Unknown error'

    # error_info may be a dict with 'Error' and 'Cause' from SFN catch
    if isinstance(error_info, dict):
        cause = error_info.get('Cause', '')
        if cause:
            # Cause may be a JSON string (e.g. from workflow_status_handler)
            try:
                parsed = json.loads(cause)
                return parsed.get('reason', cause)
            except (json.JSONDecodeError, TypeError):
                return cause
        return error_info.get('Error', 'Unknown error')

    # error_info may be a JSON string
    if isinstance(error_info, str):
        try:
            parsed = json.loads(error_info)
            return _parse_error_detail(parsed)
        except (json.JSONDecodeError, TypeError):
            return error_info

    return str(error_info)


def handler(event, context):
    """Send failure notification email via SNS.

    Expected event payload from Step Functions:
    {
        "sample_id": "ACME-RD-001",
        "project_id": "Rare-Disease-Dx-2026",
        "submitter_email": "admin@acme.example.com",
        "organization_id": "ORG-ACME",
        "failure_type": "WORKFLOW_FAILED",
        "error": { ... }   # from SFN $.error
    }
    """
    logger.info(f"Failure notification: {json.dumps(event)}")

    sample_id = event.get('sample_id', 'Unknown')
    project_id = event.get('project_id', 'Unknown')
    submitter_email = event.get('submitter_email', 'Unknown')
    org_id = event.get('organization_id', '')
    failure_type = event.get('failure_type', 'WORKFLOW_FAILED')
    error_info = event.get('error', {})

    failure_desc = FAILURE_DESCRIPTIONS.get(failure_type, failure_type)
    error_detail = _parse_error_detail(error_info)

    # Build recipient list
    recipients = [submitter_email]
    org_admins = _get_org_admin_emails(org_id)
    for admin_email in org_admins:
        if admin_email not in recipients:
            recipients.append(admin_email)

    # Format message
    status_url = f"{DASHBOARD_URL}/status.html?sample_id={sample_id}" if DASHBOARD_URL else ''

    message = (
        f"Pipeline Failure Alert\n"
        f"{'=' * 50}\n\n"
        f"Sample ID  : {sample_id}\n"
        f"Project    : {project_id}\n"
        f"Submitter  : {submitter_email}\n"
        f"Organization: {org_id}\n"
        f"Failure Type: {failure_desc}\n\n"
        f"Error Detail:\n"
        f"  {error_detail}\n\n"
        f"Recipients : {', '.join(recipients)}\n"
    )

    if status_url:
        message += f"\nDashboard  : {status_url}\n"

    message += (
        f"\n{'=' * 50}\n"
        f"This is an automated notification from the LIMS Genomics Pipeline.\n"
    )

    subject = f"[Pipeline Failed] {sample_id} - {failure_desc}"
    # SNS subject max is 100 chars
    if len(subject) > 100:
        subject = subject[:97] + '...'

    notification_sent = False
    if SNS_TOPIC_ARN:
        try:
            sns.publish(
                TopicArn=SNS_TOPIC_ARN,
                Subject=subject,
                Message=message,
            )
            notification_sent = True
            logger.info(f"Sent failure notification for {sample_id} to SNS topic")
        except Exception as e:
            logger.error(f"Failed to publish to SNS: {e}", exc_info=True)
    else:
        logger.warning("SNS_TOPIC_ARN not configured, skipping notification")

    return {
        'sample_id': sample_id,
        'failure_type': failure_type,
        'notification_sent': notification_sent,
        'recipients': recipients,
    }

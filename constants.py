import os
import boto3
from aws_cdk import Environment


def _get_account_id():
    """Resolve AWS account ID from environment or STS."""
    acct = os.environ.get("CDK_DEFAULT_ACCOUNT")
    if acct:
        return acct
    try:
        return boto3.client("sts").get_caller_identity()["Account"]
    except Exception:
        return None


# Dev Environment (us-east-1 - HealthOmics Ready2Run workflows are only available here)
DEV_ENV = Environment(
    account=_get_account_id(),
    region="us-east-1",
)
DEV_CONFIG = {
    "AWS_REGION": 'us-east-1',
    "AWS_BUCKET" :  'omics-eventbridge-solution-dev',
    "JOB_TIMEOUT" : 1500,  # seconds

    # Notification Settings
    # Set to True to send email notifications when workflows complete successfully
    "SEND_COMPLETION_NOTIFICATION": False,
    # SES email configuration (requires verified email addresses in SES)
    # Leave empty to disable SES emails (will use SNS only)
    "SES_SENDER_EMAIL": "",  # e.g., "sender@example.com"
    "SES_RECIPIENT_EMAIL": "",  # e.g., "recipient@example.com"

    # LIMS Orchestration Settings
    "ADMIN_EMAIL": "",  # e.g., "admin@example.com" - receives approval requests
    "APPROVAL_TIMEOUT_DAYS": 7,  # days before approval request times out
}

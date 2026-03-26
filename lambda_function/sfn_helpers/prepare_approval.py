import boto3
import os
import json
import logging

SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN', '')
ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', '')
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')

sns = boto3.client('sns')

logging.basicConfig(level=LOG_LEVEL)
logger = logging.getLogger(__name__)


def handler(event, context):
    """Prepare and send approval notification to admin."""
    logger.info(f"Preparing approval: {json.dumps(event)}")

    sample_id = event['sample_id']
    project_id = event['project_id']
    submitter_email = event['submitter_email']
    vep_output = event.get('vep_output', {})
    gatk_run_id = event.get('gatk_run_id', '')
    vep_run_id = event.get('vep_run_id', '')

    message = (
        f"Genomic analysis pipeline completed for sample {sample_id}.\n\n"
        f"Project: {project_id}\n"
        f"Submitter: {submitter_email}\n"
        f"GATK Run ID: {gatk_run_id}\n"
        f"VEP Run ID: {vep_run_id}\n"
        f"VEP Output: {json.dumps(vep_output, indent=2)}\n\n"
        f"Please review and approve/reject the results via the admin dashboard."
    )

    if SNS_TOPIC_ARN:
        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=f"[Action Required] Approve results for sample {sample_id}",
            Message=message,
        )
        logger.info(f"Sent approval notification for sample {sample_id}")

    return {
        'sample_id': sample_id,
        'notification_sent': bool(SNS_TOPIC_ARN),
    }

import boto3
import os
import json
import logging

WORKFLOW_STATE_TABLE = os.environ.get('WORKFLOW_STATE_TABLE', 'GenomicWorkflowState')
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')

dynamodb = boto3.resource('dynamodb')
state_table = dynamodb.Table(WORKFLOW_STATE_TABLE)

logging.basicConfig(level=LOG_LEVEL)
logger = logging.getLogger(__name__)


def handler(event, context):
    """Store approval task token in DynamoDB for admin approval callback.

    Called by Step Functions with waitForTaskToken pattern.
    Does NOT return - the function stores the token and exits.
    Step Functions resumes when ApprovalHandler calls SendTaskSuccess/Failure.
    """
    logger.info(f"Storing approval token: {json.dumps(event)}")

    task_token = event['task_token']
    sample_id = event['sample_id']
    timestamp = event['timestamp']

    state_table.update_item(
        Key={'SampleID': sample_id, 'Timestamp': timestamp},
        UpdateExpression='SET ApprovalToken = :token, #s = :status, UpdatedAt = :updated',
        ExpressionAttributeNames={'#s': 'Status'},
        ExpressionAttributeValues={
            ':token': task_token,
            ':status': 'AWAITING_APPROVAL',
            ':updated': timestamp,
        },
    )

    logger.info(f"Stored approval token for sample {sample_id}")
    # No return - this Lambda is invoked with waitForTaskToken

import boto3
import os
import json
import logging
import time

TASK_TOKENS_TABLE = os.environ.get('TASK_TOKENS_TABLE', 'WorkflowTaskTokens')
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')

dynamodb = boto3.resource('dynamodb')
tokens_table = dynamodb.Table(TASK_TOKENS_TABLE)

logging.basicConfig(level=LOG_LEVEL)
logger = logging.getLogger(__name__)


def handler(event, context):
    """Store task token in DynamoDB for HealthOmics callback.

    Called by Step Functions with waitForTaskToken pattern.
    Does NOT return - the function stores the token and exits.
    Step Functions resumes when WorkflowStatusHandler calls SendTaskSuccess/Failure.
    """
    logger.info(f"Storing task token: {json.dumps(event)}")

    task_token = event['task_token']
    run_id = event['run_id']
    execution_arn = event['execution_arn']
    workflow_type = event['workflow_type']

    tokens_table.put_item(Item={
        'RunId': run_id,
        'TaskToken': task_token,
        'ExecutionArn': execution_arn,
        'WorkflowType': workflow_type,
        'SampleID': event.get('sample_id', ''),
        'CreatedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'TTL': int(time.time()) + 604800,  # 7 days
    })

    logger.info(f"Stored token for run {run_id}, type {workflow_type}")
    # No return - this Lambda is invoked with waitForTaskToken

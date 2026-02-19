import boto3
import os
import json
import logging

LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')
TASK_TOKENS_TABLE = os.environ.get('TASK_TOKENS_TABLE', 'WorkflowTaskTokens')

omics = boto3.client('omics')
sfn = boto3.client('stepfunctions')
dynamodb = boto3.resource('dynamodb')
tokens_table = dynamodb.Table(TASK_TOKENS_TABLE)

logging.basicConfig(level=LOG_LEVEL)
logger = logging.getLogger(__name__)


def handler(event, context):
    """Triggered by EventBridge on HealthOmics COMPLETED/FAILED events.

    Looks up the task token from WorkflowTaskTokens DynamoDB table and
    calls SendTaskSuccess/SendTaskFailure on Step Functions.
    Only processes runs tagged with SOURCE=STEP_FUNCTIONS.
    """
    logger.info(f"Received event: {json.dumps(event)}")

    try:
        run_arn = event['detail']['arn']
        run_id = run_arn.split('/')[-1]
        status = event['detail']['status']

        logger.info(f"Processing run {run_id} with status {status}")

        # Get run details to check tags
        run_info = omics.get_run(id=run_id)
        tags = run_info.get('tags', {})

        # Only process runs managed by Step Functions
        if tags.get('SOURCE') != 'STEP_FUNCTIONS':
            logger.info(f"Run {run_id} not managed by Step Functions (SOURCE={tags.get('SOURCE')}), skipping")
            return {
                'statusCode': 200,
                'message': 'Skipped - not a Step Functions managed run',
            }

        # Look up task token
        token_item = tokens_table.get_item(Key={'RunId': run_id}).get('Item')
        if not token_item:
            logger.warning(f"No task token found for run {run_id}")
            return {
                'statusCode': 200,
                'message': 'No task token found',
            }

        task_token = token_item['TaskToken']
        workflow_type = token_item.get('WorkflowType', 'UNKNOWN')

        logger.info(f"Found task token for run {run_id}, workflow type: {workflow_type}")

        if status == 'COMPLETED':
            output_uri = run_info.get('outputUri', '')
            workflow_id = run_info.get('workflowId', '')

            sfn.send_task_success(
                taskToken=task_token,
                output=json.dumps({
                    'run_id': run_id,
                    'status': 'COMPLETED',
                    'workflow_type': workflow_type,
                    'workflow_id': workflow_id,
                    'output_uri': f"{output_uri}/{run_id}",
                }),
            )
            logger.info(f"Sent task success for run {run_id}")

        elif status == 'FAILED':
            failure_reason = run_info.get('statusMessage', 'Unknown failure')

            sfn.send_task_failure(
                taskToken=task_token,
                error='HealthOmicsWorkflowFailed',
                cause=json.dumps({
                    'run_id': run_id,
                    'status': 'FAILED',
                    'workflow_type': workflow_type,
                    'reason': failure_reason,
                }),
            )
            logger.info(f"Sent task failure for run {run_id}")

        # Clean up token entry
        tokens_table.delete_item(Key={'RunId': run_id})

        return {
            'statusCode': 200,
            'message': f'Processed {status} for run {run_id}',
        }

    except sfn.exceptions.TaskTimedOut:
        logger.warning(f"Task token expired for run {run_id}")
        return {'statusCode': 200, 'message': 'Task token expired'}
    except sfn.exceptions.InvalidToken:
        logger.warning(f"Invalid task token for run {run_id}")
        return {'statusCode': 200, 'message': 'Invalid task token'}
    except Exception as e:
        logger.error(f"Error processing event: {e}", exc_info=True)
        raise

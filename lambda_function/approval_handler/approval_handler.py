import boto3
import os
import json
import logging
from datetime import datetime, timezone

LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')
WORKFLOW_STATE_TABLE = os.environ.get('WORKFLOW_STATE_TABLE', 'GenomicWorkflowState')

sfn = boto3.client('stepfunctions')
dynamodb = boto3.resource('dynamodb')
state_table = dynamodb.Table(WORKFLOW_STATE_TABLE)

logging.basicConfig(level=LOG_LEVEL)
logger = logging.getLogger(__name__)


def handler(event, context):
    """Handles admin approval/rejection decisions for genomic analysis results."""
    logger.info(f"Received event: {json.dumps(event)}")

    try:
        body = event.get('body')
        if isinstance(body, str):
            body = json.loads(body)

        sample_id = body.get('sample_id')
        decision = body.get('decision', '').upper()
        reason = body.get('reason', '')
        approved_by = body.get('approved_by', 'unknown')

        if not sample_id:
            return _error_response(400, 'Missing required field: sample_id')
        if decision not in ('APPROVED', 'REJECTED'):
            return _error_response(400, 'decision must be APPROVED or REJECTED')

        # Find the sample with AWAITING_APPROVAL status
        from boto3.dynamodb.conditions import Key
        response = state_table.query(
            KeyConditionExpression=Key('SampleID').eq(sample_id),
            ScanIndexForward=False,
        )
        items = response.get('Items', [])

        approval_item = None
        for item in items:
            if item.get('Status') == 'AWAITING_APPROVAL' and item.get('ApprovalToken'):
                approval_item = item
                break

        if not approval_item:
            return _error_response(404, f'No pending approval found for sample {sample_id}')

        task_token = approval_item['ApprovalToken']
        timestamp = approval_item['Timestamp']

        # Send task response to Step Functions
        if decision == 'APPROVED':
            sfn.send_task_success(
                taskToken=task_token,
                output=json.dumps({
                    'decision': 'APPROVED',
                    'approved_by': approved_by,
                    'reason': reason,
                    'decided_at': datetime.now(timezone.utc).isoformat(),
                }),
            )
            new_status = 'APPROVED'
        else:
            sfn.send_task_failure(
                taskToken=task_token,
                error='ApprovalRejected',
                cause=json.dumps({
                    'decision': 'REJECTED',
                    'rejected_by': approved_by,
                    'reason': reason,
                    'decided_at': datetime.now(timezone.utc).isoformat(),
                }),
            )
            new_status = 'REJECTED'

        # Update DynamoDB status
        state_table.update_item(
            Key={'SampleID': sample_id, 'Timestamp': timestamp},
            UpdateExpression='SET #s = :status, ApprovedBy = :by, ApprovalReason = :reason, ApprovalDecidedAt = :at, UpdatedAt = :updated',
            ExpressionAttributeNames={'#s': 'Status'},
            ExpressionAttributeValues={
                ':status': new_status,
                ':by': approved_by,
                ':reason': reason,
                ':at': datetime.now(timezone.utc).isoformat(),
                ':updated': datetime.now(timezone.utc).isoformat(),
            },
        )

        logger.info(f"Sample {sample_id} {decision} by {approved_by}")

        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*',
            },
            'body': json.dumps({
                'message': f'Sample {sample_id} {decision.lower()}',
                'sample_id': sample_id,
                'decision': decision,
                'approved_by': approved_by,
            }),
        }

    except sfn.exceptions.TaskTimedOut:
        logger.warning(f"Task token has expired for sample {sample_id}")
        return _error_response(410, 'Approval window has expired')
    except sfn.exceptions.InvalidToken:
        logger.warning(f"Invalid task token for sample {sample_id}")
        return _error_response(400, 'Invalid or already used approval token')
    except json.JSONDecodeError:
        return _error_response(400, 'Invalid JSON in request body')
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return _error_response(500, 'Internal server error')


def _error_response(status_code, message):
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
        },
        'body': json.dumps({'error': message}),
    }

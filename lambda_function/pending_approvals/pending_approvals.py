import boto3
import os
import json
import logging
from decimal import Decimal
from boto3.dynamodb.conditions import Key

WORKFLOW_STATE_TABLE = os.environ.get('WORKFLOW_STATE_TABLE', 'GenomicWorkflowState')
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')

dynamodb = boto3.resource('dynamodb')
state_table = dynamodb.Table(WORKFLOW_STATE_TABLE)

logging.basicConfig(level=LOG_LEVEL)
logger = logging.getLogger(__name__)


class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        return super().default(obj)


def handler(event, context):
    """List all samples awaiting admin approval."""
    logger.info(f"Pending approvals query: {json.dumps(event)}")

    response = state_table.query(
        IndexName='StatusIndex',
        KeyConditionExpression=Key('Status').eq('AWAITING_APPROVAL'),
    )
    items = response.get('Items', [])

    # Remove approval tokens from response for security
    for item in items:
        item.pop('ApprovalToken', None)

    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
        },
        'body': json.dumps({
            'pending_approvals': items,
            'count': len(items),
        }, cls=DecimalEncoder),
    }

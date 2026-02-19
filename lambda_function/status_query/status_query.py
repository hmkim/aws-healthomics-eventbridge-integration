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
    """Query workflow status by sample ID."""
    logger.info(f"Status query event: {json.dumps(event)}")

    # Get sample_id from path parameters
    path_params = event.get('pathParameters') or {}
    sample_id = path_params.get('sample_id')

    if not sample_id:
        return _response(400, {'error': 'Missing sample_id path parameter'})

    response = state_table.query(
        KeyConditionExpression=Key('SampleID').eq(sample_id),
        ScanIndexForward=False,
    )
    items = response.get('Items', [])

    if not items:
        return _response(404, {'error': f'No records found for sample {sample_id}'})

    # Remove approval tokens from response for security
    for item in items:
        item.pop('ApprovalToken', None)

    return _response(200, {
        'sample_id': sample_id,
        'records': items,
        'count': len(items),
    })


def _response(status_code, body):
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
        },
        'body': json.dumps(body, cls=DecimalEncoder),
    }

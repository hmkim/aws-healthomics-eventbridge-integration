import boto3
import os
import json
import logging
import sys
from decimal import Decimal
from boto3.dynamodb.conditions import Key

# Add shared layer to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
from auth_middleware import require_auth, cors_headers

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


@require_auth('admin')
def handler(event, context):
    """List samples awaiting admin approval, filtered by caller's organization."""
    auth = event['auth']
    org_id = auth['organization_id']
    logger.info(f"Pending approvals query for org={org_id}")

    response = state_table.query(
        IndexName='StatusIndex',
        KeyConditionExpression=Key('Status').eq('AWAITING_APPROVAL'),
    )
    items = response.get('Items', [])

    # Filter to caller's organization only
    items = [i for i in items if i.get('OrganizationID') == org_id]

    # Remove approval tokens from response for security
    for item in items:
        item.pop('ApprovalToken', None)

    return {
        'statusCode': 200,
        'headers': cors_headers(),
        'body': json.dumps({
            'pending_approvals': items,
            'count': len(items),
        }, cls=DecimalEncoder),
    }

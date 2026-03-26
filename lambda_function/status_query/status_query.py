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
omics = boto3.client('omics')

logging.basicConfig(level=LOG_LEVEL)
logger = logging.getLogger(__name__)


class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        return super().default(obj)


@require_auth('viewer')
def handler(event, context):
    """Query workflow status by sample ID, filtered by caller's organization."""
    auth = event['auth']
    org_id = auth['organization_id']
    logger.info(f"Status query for org={org_id}")

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

    # Filter to caller's organization only
    items = [i for i in items if i.get('OrganizationID') == org_id]

    if not items:
        return _response(404, {'error': f'No records found for sample {sample_id}'})

    # Remove approval tokens from response for security
    for item in items:
        item.pop('ApprovalToken', None)

    # Sort by most recent activity (UpdatedAt or Timestamp)
    items.sort(key=lambda r: r.get('UpdatedAt') or r.get('Timestamp', ''), reverse=True)

    # Enrich latest record with real-time HealthOmics run status
    latest = items[0]
    gatk_run_id = latest.get('GATKRunId')
    vep_run_id = latest.get('VEPRunId')

    if gatk_run_id:
        try:
            run = omics.get_run(id=gatk_run_id)
            latest['GATKRunStatus'] = run.get('status', 'UNKNOWN')
            latest['GATKRunName'] = run.get('name', '')
        except Exception:
            latest['GATKRunStatus'] = 'UNKNOWN'

    if vep_run_id:
        try:
            run = omics.get_run(id=vep_run_id)
            latest['VEPRunStatus'] = run.get('status', 'UNKNOWN')
            latest['VEPRunName'] = run.get('name', '')
        except Exception:
            latest['VEPRunStatus'] = 'UNKNOWN'

    return _response(200, {
        'sample_id': sample_id,
        'records': items,
        'count': len(items),
    })


def _response(status_code, body):
    return {
        'statusCode': status_code,
        'headers': cors_headers(),
        'body': json.dumps(body, cls=DecimalEncoder),
    }

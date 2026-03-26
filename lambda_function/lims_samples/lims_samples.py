import boto3
import os
import json
import logging
import sys
from datetime import datetime, timezone
from boto3.dynamodb.conditions import Key

# Add shared layer to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
from auth_middleware import require_auth, cors_headers

from sample_validators import validate_sample

LIMS_SAMPLES_TABLE = os.environ.get('LIMS_SAMPLES_TABLE', 'LimsSamples')
WORKFLOW_STATE_TABLE = os.environ.get('WORKFLOW_STATE_TABLE', 'GenomicWorkflowState')
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')

dynamodb = boto3.resource('dynamodb')
lims_table = dynamodb.Table(LIMS_SAMPLES_TABLE)
state_table = dynamodb.Table(WORKFLOW_STATE_TABLE)

logging.basicConfig(level=LOG_LEVEL)
logger = logging.getLogger(__name__)


def handler(event, context):
    """Route requests by HTTP method."""
    method = event.get('httpMethod', 'GET')
    if method == 'GET':
        return get_handler(event, context)
    elif method == 'POST':
        return post_handler(event, context)
    else:
        return {
            'statusCode': 405,
            'headers': cors_headers(),
            'body': json.dumps({'error': f'Method {method} not allowed'}),
        }


@require_auth('viewer')
def get_handler(event, context):
    """List LIMS samples filtered by the caller's organization."""
    auth = event['auth']
    org_id = auth['organization_id']
    logger.info(f"Listing LIMS samples for org={org_id}")

    try:
        # Query by organization using GSI instead of scanning all
        response = lims_table.query(
            IndexName='OrganizationIndex',
            KeyConditionExpression=Key('OrganizationID').eq(org_id),
        )
        samples = response.get('Items', [])

        # For each sample, look up latest pipeline status
        for sample in samples:
            sample_id = sample['SampleID']
            state_response = state_table.query(
                KeyConditionExpression=Key('SampleID').eq(sample_id),
                ScanIndexForward=False,
            )
            records = state_response.get('Items', [])
            if records:
                # Pick the record with the most recent activity (UpdatedAt or Timestamp)
                latest = max(records, key=lambda r: r.get('UpdatedAt') or r.get('Timestamp', ''))
                sample['PipelineStatus'] = latest.get('Status', 'UNKNOWN')
                sample['PipelineTimestamp'] = latest.get('UpdatedAt') or latest.get('Timestamp', '')
                sample['GATKRunId'] = latest.get('GATKRunId', '')
                sample['VEPRunId'] = latest.get('VEPRunId', '')
            else:
                sample['PipelineStatus'] = 'NOT_STARTED'
                sample['PipelineTimestamp'] = ''

        # Sort: NOT_STARTED first, then by RegisteredAt
        status_order = {'NOT_STARTED': 0, 'INITIALIZED': 1}
        samples.sort(key=lambda s: (
            status_order.get(s['PipelineStatus'], 2),
            s.get('RegisteredAt', ''),
        ))

        return {
            'statusCode': 200,
            'headers': cors_headers(),
            'body': json.dumps({
                'samples': samples,
                'count': len(samples),
            }),
        }

    except Exception as e:
        logger.error(f"Error listing samples: {e}", exc_info=True)
        return {
            'statusCode': 500,
            'headers': cors_headers(),
            'body': json.dumps({'error': 'Failed to list samples'}),
        }


@require_auth('operator')
def post_handler(event, context):
    """Register one or more samples into LimsSamples table."""
    auth = event['auth']
    org_id = auth['organization_id']
    user_email = auth['email']

    try:
        body = json.loads(event.get('body') or '{}')
    except (json.JSONDecodeError, TypeError):
        return {
            'statusCode': 400,
            'headers': cors_headers(),
            'body': json.dumps({'error': 'Invalid JSON body'}),
        }

    # Batch vs single detection
    if 'samples' in body:
        samples_list = body['samples']
        if not isinstance(samples_list, list) or len(samples_list) == 0:
            return {
                'statusCode': 400,
                'headers': cors_headers(),
                'body': json.dumps({'error': 'samples must be a non-empty array'}),
            }
        return _register_batch(samples_list, org_id, user_email)
    else:
        return _register_single(body, org_id, user_email)


def _register_single(sample_data, org_id, user_email):
    """Register a single sample. Returns 201 on success, 400/409 on error."""
    errors = validate_sample(sample_data)
    if errors:
        return {
            'statusCode': 400,
            'headers': cors_headers(),
            'body': json.dumps({'error': 'Validation failed', 'details': errors}),
        }

    sample_id = sample_data['sample_id']

    # Check for duplicates
    existing = lims_table.get_item(Key={'SampleID': sample_id})
    if 'Item' in existing:
        return {
            'statusCode': 409,
            'headers': cors_headers(),
            'body': json.dumps({'error': f'Sample already exists: {sample_id}'}),
        }

    now = datetime.now(timezone.utc).isoformat()
    item = {
        'SampleID': sample_id,
        'OrganizationID': org_id,
        'ProjectID': sample_data['project_id'],
        'Description': sample_data.get('description', ''),
        'AnalysisType': sample_data.get('analysis_type', 'WGS'),
        'ReferenceGenome': sample_data['reference_genome'],
        'PatientID': sample_data.get('patient_id', ''),
        'SubmitterEmail': sample_data.get('submitter_email') or user_email,
        'FastqR1': sample_data['fastq_r1'],
        'FastqR2': sample_data['fastq_r2'],
        'RegisteredAt': now,
        'RegisteredBy': user_email,
    }

    lims_table.put_item(Item=item)
    logger.info(f"Registered sample {sample_id} for org={org_id}")

    return {
        'statusCode': 201,
        'headers': cors_headers(),
        'body': json.dumps({'success': True, 'sample': item}),
    }


def _register_batch(samples_list, org_id, user_email):
    """Register multiple samples. Returns 200 (all success) or 207 (partial)."""
    results = []
    registered = 0
    failed = 0

    for sample_data in samples_list:
        sample_id = sample_data.get('sample_id', 'UNKNOWN')

        errors = validate_sample(sample_data)
        if errors:
            results.append({
                'sample_id': sample_id,
                'status': 'failed',
                'error': '; '.join(errors),
            })
            failed += 1
            continue

        # Check for duplicates
        existing = lims_table.get_item(Key={'SampleID': sample_id})
        if 'Item' in existing:
            results.append({
                'sample_id': sample_id,
                'status': 'failed',
                'error': 'Sample already exists',
            })
            failed += 1
            continue

        now = datetime.now(timezone.utc).isoformat()
        item = {
            'SampleID': sample_id,
            'OrganizationID': org_id,
            'ProjectID': sample_data['project_id'],
            'Description': sample_data.get('description', ''),
            'AnalysisType': sample_data.get('analysis_type', 'WGS'),
            'ReferenceGenome': sample_data['reference_genome'],
            'PatientID': sample_data.get('patient_id', ''),
            'SubmitterEmail': sample_data.get('submitter_email') or user_email,
            'FastqR1': sample_data['fastq_r1'],
            'FastqR2': sample_data['fastq_r2'],
            'RegisteredAt': now,
            'RegisteredBy': user_email,
        }

        try:
            lims_table.put_item(Item=item)
            results.append({'sample_id': sample_id, 'status': 'registered'})
            registered += 1
        except Exception as e:
            logger.error(f"Failed to register {sample_id}: {e}")
            results.append({
                'sample_id': sample_id,
                'status': 'failed',
                'error': str(e),
            })
            failed += 1

    status_code = 200 if failed == 0 else 207
    return {
        'statusCode': status_code,
        'headers': cors_headers(),
        'body': json.dumps({
            'total': len(samples_list),
            'registered': registered,
            'failed': failed,
            'results': results,
        }),
    }

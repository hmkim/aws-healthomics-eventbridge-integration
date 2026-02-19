import boto3
import os
import json
import logging
from boto3.dynamodb.conditions import Key

LIMS_SAMPLES_TABLE = os.environ.get('LIMS_SAMPLES_TABLE', 'LimsSamples')
WORKFLOW_STATE_TABLE = os.environ.get('WORKFLOW_STATE_TABLE', 'GenomicWorkflowState')
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')

dynamodb = boto3.resource('dynamodb')
lims_table = dynamodb.Table(LIMS_SAMPLES_TABLE)
state_table = dynamodb.Table(WORKFLOW_STATE_TABLE)

logging.basicConfig(level=LOG_LEVEL)
logger = logging.getLogger(__name__)


def handler(event, context):
    """List all LIMS samples with their pipeline processing status."""
    logger.info(f"Listing LIMS samples")

    try:
        # Scan all samples from LIMS registry
        response = lims_table.scan()
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
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*',
            },
            'body': json.dumps({
                'samples': samples,
                'count': len(samples),
            }),
        }

    except Exception as e:
        logger.error(f"Error listing samples: {e}", exc_info=True)
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*',
            },
            'body': json.dumps({'error': 'Failed to list samples'}),
        }

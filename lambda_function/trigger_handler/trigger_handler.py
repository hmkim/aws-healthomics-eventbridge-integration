import boto3
import os
import json
import logging
import sys
import uuid
from validators import validate_lims_payload, ValidationError

# Add shared layer to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
from auth_middleware import require_auth, cors_headers

STATE_MACHINE_ARN = os.environ['STATE_MACHINE_ARN']
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')

sfn = boto3.client('stepfunctions')

logging.basicConfig(level=LOG_LEVEL)
logger = logging.getLogger(__name__)


@require_auth('operator')
def handler(event, context):
    """Receives LIMS JSON via API Gateway, validates, and starts Step Functions execution."""
    auth = event['auth']
    org_id = auth['organization_id']
    logger.info(f"Trigger handler for org={org_id}")

    try:
        # Parse body from API Gateway
        body = event.get('body')
        if isinstance(body, str):
            body = json.loads(body)

        # Validate payload
        validate_lims_payload(body)

        data = body['data']
        sample_id = data['sample_id']
        project_id = data['project_id']

        # Prepare Step Functions input — include organization_id for data isolation
        sfn_input = {
            'source': body['source'],
            'event_type': body['event_type'],
            'sample_id': sample_id,
            'project_id': project_id,
            'patient_id': data.get('patient_id', ''),
            'submitter_email': data['submitter_email'],
            'fastq_paths': data['fastq_paths'],
            'reference_genome': data['reference_genome'],
            'analysis_type': data.get('analysis_type', 'WGS'),
            'organization_id': org_id,
        }

        unique_suffix = uuid.uuid4().hex[:8]
        execution_name = f"{project_id}-{sample_id}-{unique_suffix}".replace(' ', '_')[:80]

        response = sfn.start_execution(
            stateMachineArn=STATE_MACHINE_ARN,
            name=execution_name,
            input=json.dumps(sfn_input),
        )

        logger.info(f"Started execution: {response['executionArn']}")

        return {
            'statusCode': 202,
            'headers': cors_headers(),
            'body': json.dumps({
                'message': 'Analysis pipeline started',
                'execution_arn': response['executionArn'],
                'sample_id': sample_id,
                'project_id': project_id,
            }),
        }

    except ValidationError as e:
        logger.warning(f"Validation error: {e}")
        return {
            'statusCode': 400,
            'headers': cors_headers(),
            'body': json.dumps({
                'error': 'Validation failed',
                'details': e.errors,
            }),
        }
    except json.JSONDecodeError:
        return {
            'statusCode': 400,
            'headers': cors_headers(),
            'body': json.dumps({
                'error': 'Invalid JSON in request body',
            }),
        }
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return {
            'statusCode': 500,
            'headers': cors_headers(),
            'body': json.dumps({
                'error': 'Internal server error',
            }),
        }

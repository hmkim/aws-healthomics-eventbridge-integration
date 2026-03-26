import boto3
from botocore.config import Config
import os
import json
import logging
import uuid

OMICS_ROLE = os.environ['OMICS_ROLE']
OUTPUT_S3_LOCATION = os.environ['OUTPUT_S3_LOCATION']
GATK_WORKFLOW_ID = os.environ['GATK_WORKFLOW_ID']
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')

# StartRun TPS quota is 1.0 — use adaptive retry with generous backoff
omics = boto3.client('omics', config=Config(
    retries={'mode': 'adaptive', 'max_attempts': 10},
))

logging.basicConfig(level=LOG_LEVEL)
logger = logging.getLogger(__name__)


def handler(event, context):
    """Start GATK-BP workflow for a sample via Step Functions."""
    logger.info(f"Starting GATK workflow: {json.dumps(event)}")

    sample_id = event['sample_id']
    fastq_paths = event['fastq_paths']
    execution_arn = event['execution_arn']

    run_name = f"SFN_GATK_{sample_id}_{uuid.uuid4().hex[:8]}"

    params = {
        'sample_name': sample_id,
        'fastq_pairs': [
            {
                'read_group': 'RG1',
                'fastq_1': fastq_paths['r1'],
                'fastq_2': fastq_paths['r2'],
                'platform': 'illumina',
            }
        ],
    }

    response = omics.start_run(
        workflowType='READY2RUN',
        workflowId=GATK_WORKFLOW_ID,
        name=run_name,
        roleArn=OMICS_ROLE,
        parameters=params,
        outputUri=OUTPUT_S3_LOCATION,
        logLevel='ALL',
        tags={
            'SOURCE': 'STEP_FUNCTIONS',
            'EXECUTION_ARN': execution_arn,
            'SAMPLE_ID': sample_id,
            'WORKFLOW_STEP': 'GATK',
        },
    )

    run_id = response['id']
    run_arn = response['arn']
    logger.info(f"Started GATK run {run_id} for sample {sample_id}")

    return {
        'run_id': run_id,
        'run_arn': run_arn,
    }

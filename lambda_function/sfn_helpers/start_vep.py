import boto3
import os
import json
import logging
import uuid

OMICS_ROLE = os.environ['OMICS_ROLE']
OUTPUT_S3_LOCATION = os.environ['OUTPUT_S3_LOCATION']
VEP_WORKFLOW_ID = os.environ['VEP_WORKFLOW_ID']
VEP_CONTAINER_IMAGE = os.environ['VEP_CONTAINER_IMAGE']
VEP_SPECIES = os.environ.get('VEP_SPECIES', 'homo_sapiens')
VEP_DIR_CACHE = os.environ['VEP_DIR_CACHE']
VEP_CACHE_VERSION = os.environ.get('VEP_CACHE_VERSION', '110')
VEP_GENOME = os.environ.get('VEP_GENOME', 'GRCh38')
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')

omics = boto3.client('omics')
s3 = boto3.client('s3')

logging.basicConfig(level=LOG_LEVEL)
logger = logging.getLogger(__name__)


def split_s3_path(s3_path):
    path_parts = s3_path.replace("s3://", "").split("/")
    bucket = path_parts.pop(0)
    key = "/".join(path_parts)
    return bucket, key


def handler(event, context):
    """Start VEP workflow after GATK completion via Step Functions."""
    logger.info(f"Starting VEP workflow: {json.dumps(event)}")

    sample_id = event['sample_id']
    gatk_output = event['gatk_output']
    execution_arn = event['execution_arn']

    # Find VCF file from GATK output
    output_uri = gatk_output.get('output_uri', '')
    if not output_uri:
        raise Exception("No output_uri from GATK completion")

    s3bucket, s3key = split_s3_path(output_uri)
    paginator = s3.get_paginator('list_objects_v2')
    page_iterator = paginator.paginate(Bucket=s3bucket, Prefix=s3key)

    vcf_file = None
    for page in page_iterator:
        for obj in page.get('Contents', []):
            if obj['Key'].endswith('.vcf.gz'):
                vcf_file = f"s3://{s3bucket}/{obj['Key']}"
                break
        if vcf_file:
            break

    if not vcf_file:
        raise Exception(f"No .vcf.gz file found in {output_uri}")

    run_name = f"SFN_VEP_{sample_id}_{uuid.uuid4().hex[:8]}"

    workflow_params = {
        'id': sample_id,
        'vcf': vcf_file,
        'vep_species': VEP_SPECIES,
        'vep_genome': VEP_GENOME,
        'vep_container': VEP_CONTAINER_IMAGE,
        'vep_cache': VEP_DIR_CACHE,
        'vep_cache_version': VEP_CACHE_VERSION,
    }

    response = omics.start_run(
        workflowType='PRIVATE',
        workflowId=str(VEP_WORKFLOW_ID),
        name=run_name,
        roleArn=OMICS_ROLE,
        parameters=workflow_params,
        outputUri=OUTPUT_S3_LOCATION,
        logLevel='ALL',
        tags={
            'SOURCE': 'STEP_FUNCTIONS',
            'EXECUTION_ARN': execution_arn,
            'SAMPLE_ID': sample_id,
            'WORKFLOW_STEP': 'VEP',
        },
    )

    run_id = response['id']
    run_arn = response['arn']
    logger.info(f"Started VEP run {run_id} for sample {sample_id}")

    return {
        'run_id': run_id,
        'run_arn': run_arn,
    }

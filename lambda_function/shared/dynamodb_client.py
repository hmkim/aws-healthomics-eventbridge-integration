import boto3
import os
import logging
from datetime import datetime, timezone
from boto3.dynamodb.conditions import Key

logger = logging.getLogger(__name__)

WORKFLOW_STATE_TABLE = os.environ.get('WORKFLOW_STATE_TABLE', 'GenomicWorkflowState')
TASK_TOKENS_TABLE = os.environ.get('TASK_TOKENS_TABLE', 'WorkflowTaskTokens')


class WorkflowStateClient:
    def __init__(self, dynamodb_resource=None):
        self.dynamodb = dynamodb_resource or boto3.resource('dynamodb')
        self.state_table = self.dynamodb.Table(WORKFLOW_STATE_TABLE)
        self.tokens_table = self.dynamodb.Table(TASK_TOKENS_TABLE)

    def create_workflow_state(self, sample_id, project_id, submitter_email,
                              fastq_paths, reference_genome, analysis_type,
                              execution_arn, patient_hash=None):
        timestamp = datetime.now(timezone.utc).isoformat()
        item = {
            'SampleID': sample_id,
            'Timestamp': timestamp,
            'ProjectID': project_id,
            'SubmitterEmail': submitter_email,
            'FastqPaths': fastq_paths,
            'ReferenceGenome': reference_genome,
            'AnalysisType': analysis_type,
            'ExecutionArn': execution_arn,
            'Status': 'INITIALIZED',
            'CreatedAt': timestamp,
            'UpdatedAt': timestamp,
        }
        if patient_hash:
            item['PatientHash'] = patient_hash

        self.state_table.put_item(Item=item)
        logger.info(f"Created workflow state for sample {sample_id}")
        return item

    def update_status(self, sample_id, timestamp, status, **extra_attrs):
        update_expr = 'SET #s = :status, UpdatedAt = :updated'
        expr_names = {'#s': 'Status'}
        expr_values = {
            ':status': status,
            ':updated': datetime.now(timezone.utc).isoformat(),
        }

        for key, value in extra_attrs.items():
            safe_key = f'#{key}'
            update_expr += f', {safe_key} = :{key}'
            expr_names[safe_key] = key
            expr_values[f':{key}'] = value

        self.state_table.update_item(
            Key={'SampleID': sample_id, 'Timestamp': timestamp},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values,
        )
        logger.info(f"Updated sample {sample_id} status to {status}")

    def store_approval_token(self, sample_id, timestamp, task_token):
        self.state_table.update_item(
            Key={'SampleID': sample_id, 'Timestamp': timestamp},
            UpdateExpression='SET ApprovalToken = :token, #s = :status, UpdatedAt = :updated',
            ExpressionAttributeNames={'#s': 'Status'},
            ExpressionAttributeValues={
                ':token': task_token,
                ':status': 'AWAITING_APPROVAL',
                ':updated': datetime.now(timezone.utc).isoformat(),
            },
        )
        logger.info(f"Stored approval token for sample {sample_id}")

    def store_task_token(self, run_id, task_token, execution_arn, workflow_type, ttl_seconds=604800):
        import time
        item = {
            'RunId': run_id,
            'TaskToken': task_token,
            'ExecutionArn': execution_arn,
            'WorkflowType': workflow_type,
            'CreatedAt': datetime.now(timezone.utc).isoformat(),
            'TTL': int(time.time()) + ttl_seconds,
        }
        self.tokens_table.put_item(Item=item)
        logger.info(f"Stored task token for run {run_id}")

    def get_task_token(self, run_id):
        response = self.tokens_table.get_item(Key={'RunId': run_id})
        return response.get('Item')

    def get_pending_approvals(self):
        response = self.state_table.query(
            IndexName='StatusIndex',
            KeyConditionExpression=Key('Status').eq('AWAITING_APPROVAL'),
        )
        return response.get('Items', [])

    def get_sample_history(self, sample_id):
        response = self.state_table.query(
            KeyConditionExpression=Key('SampleID').eq(sample_id),
            ScanIndexForward=False,
        )
        return response.get('Items', [])

    def get_sample_by_approval_token(self, task_token):
        """Scan for a sample with a matching approval token.
        Not ideal for large tables; consider GSI if scale demands it."""
        response = self.state_table.scan(
            FilterExpression='ApprovalToken = :token',
            ExpressionAttributeValues={':token': task_token},
        )
        items = response.get('Items', [])
        return items[0] if items else None

    def get_latest_sample_state(self, sample_id):
        response = self.state_table.query(
            KeyConditionExpression=Key('SampleID').eq(sample_id),
            ScanIndexForward=False,
            Limit=1,
        )
        items = response.get('Items', [])
        return items[0] if items else None

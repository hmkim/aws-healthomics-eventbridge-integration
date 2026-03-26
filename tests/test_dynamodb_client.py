import sys
import os
import pytest
from unittest.mock import MagicMock, patch
from decimal import Decimal

# Add shared to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lambda_function', 'shared'))

os.environ['WORKFLOW_STATE_TABLE'] = 'TestWorkflowState'
os.environ['TASK_TOKENS_TABLE'] = 'TestTaskTokens'

from dynamodb_client import WorkflowStateClient


@pytest.fixture
def mock_dynamodb():
    mock_resource = MagicMock()
    mock_state_table = MagicMock()
    mock_tokens_table = MagicMock()
    mock_resource.Table.side_effect = lambda name: {
        'TestWorkflowState': mock_state_table,
        'TestTaskTokens': mock_tokens_table,
    }[name]
    return mock_resource, mock_state_table, mock_tokens_table


def test_create_workflow_state(mock_dynamodb):
    mock_resource, mock_state_table, _ = mock_dynamodb
    client = WorkflowStateClient(dynamodb_resource=mock_resource)

    result = client.create_workflow_state(
        sample_id='SAM-001',
        project_id='PROJ-001',
        submitter_email='user@example.com',
        fastq_paths={'r1': 's3://bucket/r1.fq.gz', 'r2': 's3://bucket/r2.fq.gz'},
        reference_genome='GRCh38',
        analysis_type='WGS',
        execution_arn='arn:aws:states:us-east-1:123:execution:test:exec-1',
    )

    mock_state_table.put_item.assert_called_once()
    assert result['SampleID'] == 'SAM-001'
    assert result['Status'] == 'INITIALIZED'


def test_update_status(mock_dynamodb):
    mock_resource, mock_state_table, _ = mock_dynamodb
    client = WorkflowStateClient(dynamodb_resource=mock_resource)

    client.update_status('SAM-001', '2024-01-01T00:00:00Z', 'GATK_RUNNING',
                         GATKRunId='run-123')

    mock_state_table.update_item.assert_called_once()
    call_kwargs = mock_state_table.update_item.call_args[1]
    assert 'GATKRunId' in call_kwargs['UpdateExpression']


def test_store_task_token(mock_dynamodb):
    mock_resource, _, mock_tokens_table = mock_dynamodb
    client = WorkflowStateClient(dynamodb_resource=mock_resource)

    client.store_task_token('run-123', 'token-abc', 'arn:exec', 'GATK')

    mock_tokens_table.put_item.assert_called_once()
    item = mock_tokens_table.put_item.call_args[1]['Item']
    assert item['RunId'] == 'run-123'
    assert item['TaskToken'] == 'token-abc'
    assert 'TTL' in item


def test_get_task_token(mock_dynamodb):
    mock_resource, _, mock_tokens_table = mock_dynamodb
    mock_tokens_table.get_item.return_value = {
        'Item': {'RunId': 'run-123', 'TaskToken': 'token-abc'}
    }
    client = WorkflowStateClient(dynamodb_resource=mock_resource)

    result = client.get_task_token('run-123')
    assert result['TaskToken'] == 'token-abc'


def test_get_pending_approvals(mock_dynamodb):
    mock_resource, mock_state_table, _ = mock_dynamodb
    mock_state_table.query.return_value = {
        'Items': [
            {'SampleID': 'SAM-001', 'Status': 'AWAITING_APPROVAL'},
            {'SampleID': 'SAM-002', 'Status': 'AWAITING_APPROVAL'},
        ]
    }
    client = WorkflowStateClient(dynamodb_resource=mock_resource)

    result = client.get_pending_approvals()
    assert len(result) == 2


def test_get_sample_history(mock_dynamodb):
    mock_resource, mock_state_table, _ = mock_dynamodb
    mock_state_table.query.return_value = {
        'Items': [
            {'SampleID': 'SAM-001', 'Timestamp': '2024-01-02T00:00:00Z'},
            {'SampleID': 'SAM-001', 'Timestamp': '2024-01-01T00:00:00Z'},
        ]
    }
    client = WorkflowStateClient(dynamodb_resource=mock_resource)

    result = client.get_sample_history('SAM-001')
    assert len(result) == 2

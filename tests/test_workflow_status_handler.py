import sys
import os
import json
import pytest
from unittest.mock import patch, MagicMock

# Set env vars BEFORE import (module-level boto3 client initialization)
os.environ['TASK_TOKENS_TABLE'] = 'TestTaskTokens'
os.environ['LOG_LEVEL'] = 'DEBUG'
os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lambda_function', 'workflow_status_handler'))

# Patch boto3 before importing
with patch('boto3.client') as mock_client, patch('boto3.resource') as mock_resource:
    mock_tokens_table = MagicMock()
    mock_resource.return_value.Table.return_value = mock_tokens_table
    import workflow_status_handler


def _omics_event(status='COMPLETED', run_id='run-123'):
    return {
        'source': 'aws.omics',
        'detail-type': 'Run Status Change',
        'detail': {
            'arn': f'arn:aws:omics:us-east-1:123456789012:run/{run_id}',
            'status': status,
        },
    }


def test_completed_with_sfn_tag():
    mock_omics = MagicMock()
    mock_sfn = MagicMock()
    mock_table = MagicMock()

    mock_omics.get_run.return_value = {
        'tags': {'SOURCE': 'STEP_FUNCTIONS'},
        'outputUri': 's3://bucket/outputs',
        'workflowId': 'wf-123',
    }
    mock_table.get_item.return_value = {
        'Item': {
            'RunId': 'run-123',
            'TaskToken': 'token-abc',
            'WorkflowType': 'GATK',
        }
    }

    workflow_status_handler.omics = mock_omics
    workflow_status_handler.sfn = mock_sfn
    workflow_status_handler.tokens_table = mock_table

    result = workflow_status_handler.handler(_omics_event('COMPLETED'), {})

    assert result['statusCode'] == 200
    mock_sfn.send_task_success.assert_called_once()
    mock_table.delete_item.assert_called_once()


def test_skip_non_sfn_run():
    mock_omics = MagicMock()
    mock_sfn = MagicMock()

    mock_omics.get_run.return_value = {
        'tags': {'SOURCE': 'LAMBDA_INITIAL_WORKFLOW'},
    }

    workflow_status_handler.omics = mock_omics
    workflow_status_handler.sfn = mock_sfn

    result = workflow_status_handler.handler(_omics_event(), {})

    assert 'Skipped' in result['message']
    mock_sfn.send_task_success.assert_not_called()


def test_failed_sends_task_failure():
    mock_omics = MagicMock()
    mock_sfn = MagicMock()
    mock_table = MagicMock()

    mock_omics.get_run.return_value = {
        'tags': {'SOURCE': 'STEP_FUNCTIONS'},
        'statusMessage': 'Out of memory',
    }
    mock_table.get_item.return_value = {
        'Item': {
            'RunId': 'run-123',
            'TaskToken': 'token-abc',
            'WorkflowType': 'GATK',
        }
    }

    workflow_status_handler.omics = mock_omics
    workflow_status_handler.sfn = mock_sfn
    workflow_status_handler.tokens_table = mock_table

    result = workflow_status_handler.handler(_omics_event('FAILED'), {})

    assert result['statusCode'] == 200
    mock_sfn.send_task_failure.assert_called_once()


def test_no_token_found():
    mock_omics = MagicMock()
    mock_sfn = MagicMock()
    mock_table = MagicMock()

    mock_omics.get_run.return_value = {
        'tags': {'SOURCE': 'STEP_FUNCTIONS'},
    }
    mock_table.get_item.return_value = {}

    workflow_status_handler.omics = mock_omics
    workflow_status_handler.sfn = mock_sfn
    workflow_status_handler.tokens_table = mock_table

    result = workflow_status_handler.handler(_omics_event(), {})

    assert 'No task token' in result['message']
    mock_sfn.send_task_success.assert_not_called()

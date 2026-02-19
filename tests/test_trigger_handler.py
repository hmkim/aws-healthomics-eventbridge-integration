import sys
import os
import json
import pytest
from unittest.mock import patch, MagicMock

# Set env vars BEFORE import (module-level boto3 client initialization)
os.environ['STATE_MACHINE_ARN'] = 'arn:aws:states:us-east-1:123456789012:stateMachine:test'
os.environ['LOG_LEVEL'] = 'DEBUG'
os.environ['WORKFLOW_STATE_TABLE'] = 'TestWorkflowState'
os.environ['TASK_TOKENS_TABLE'] = 'TestTaskTokens'
os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'

# Add trigger_handler to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lambda_function', 'trigger_handler'))

# Patch boto3 client before importing trigger_handler
with patch('boto3.client') as mock_boto_client:
    import trigger_handler


def _api_event(body):
    return {
        'body': json.dumps(body) if isinstance(body, dict) else body,
        'httpMethod': 'POST',
        'path': '/analysis/start',
    }


def _valid_body():
    return {
        'source': 'ClarityLIMS',
        'event_type': 'StepCompleted',
        'data': {
            'project_id': 'PROJ-001',
            'sample_id': 'SAM-001',
            'patient_id': 'PAT-HASH-001',
            'submitter_email': 'user@example.com',
            'fastq_paths': {
                'r1': 's3://bucket/sample_R1.fastq.gz',
                'r2': 's3://bucket/sample_R2.fastq.gz',
            },
            'reference_genome': 'GRCh38',
            'analysis_type': 'WGS',
        },
    }


def test_successful_trigger():
    mock_sfn = MagicMock()
    mock_sfn.start_execution.return_value = {
        'executionArn': 'arn:aws:states:us-east-1:123:execution:test:exec-1',
        'startDate': '2024-01-01T00:00:00Z',
    }
    trigger_handler.sfn = mock_sfn

    result = trigger_handler.handler(_api_event(_valid_body()), {})

    assert result['statusCode'] == 202
    body = json.loads(result['body'])
    assert body['sample_id'] == 'SAM-001'
    assert 'execution_arn' in body
    mock_sfn.start_execution.assert_called_once()


def test_validation_error():
    mock_sfn = MagicMock()
    trigger_handler.sfn = mock_sfn

    event = _api_event({'source': 'test'})  # Missing required fields
    result = trigger_handler.handler(event, {})

    assert result['statusCode'] == 400
    body = json.loads(result['body'])
    assert 'error' in body
    mock_sfn.start_execution.assert_not_called()


def test_invalid_json():
    mock_sfn = MagicMock()
    trigger_handler.sfn = mock_sfn

    event = {'body': 'not json'}
    result = trigger_handler.handler(event, {})

    assert result['statusCode'] == 400
    body = json.loads(result['body'])
    assert 'JSON' in body['error']

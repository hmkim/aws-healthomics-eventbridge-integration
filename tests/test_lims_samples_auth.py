import sys
import os
import json
import pytest
from unittest.mock import patch, MagicMock

# Set env vars BEFORE import
os.environ['LIMS_SAMPLES_TABLE'] = 'TestLimsSamples'
os.environ['WORKFLOW_STATE_TABLE'] = 'TestWorkflowState'
os.environ['LOG_LEVEL'] = 'DEBUG'
os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'

# Add lims_samples and shared to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lambda_function', 'lims_samples'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lambda_function', 'shared'))

# Patch boto3 resource before importing
with patch('boto3.resource') as mock_resource:
    import lims_samples

ORG_ACME = 'ORG-ACME'
ORG_BIOCORP = 'ORG-BIOCORP'


def _auth_event(org_id=ORG_ACME, groups='["viewer"]'):
    """Build an event with Cognito auth claims."""
    return {
        'requestContext': {
            'authorizer': {
                'claims': {
                    'sub': 'test-user',
                    'email': 'test@example.com',
                    'organization_id': org_id,
                    'cognito:groups': groups,
                    'custom:display_name': 'Test User',
                }
            }
        }
    }


def _mock_tables():
    """Return mocked lims_table and state_table."""
    mock_lims = MagicMock()
    mock_state = MagicMock()
    lims_samples.lims_table = mock_lims
    lims_samples.state_table = mock_state
    return mock_lims, mock_state


ACME_SAMPLES = [
    {'SampleID': 'ACME-WGS-001', 'OrganizationID': ORG_ACME, 'ProjectID': 'PROJ-A', 'RegisteredAt': '2026-01-15T10:00:00Z'},
    {'SampleID': 'ACME-WGS-002', 'OrganizationID': ORG_ACME, 'ProjectID': 'PROJ-A', 'RegisteredAt': '2026-01-16T10:00:00Z'},
]

BIOCORP_SAMPLES = [
    {'SampleID': 'BIO-WES-001', 'OrganizationID': ORG_BIOCORP, 'ProjectID': 'PROJ-B', 'RegisteredAt': '2026-01-15T10:00:00Z'},
]


class TestOrgIsolation:
    """Test that samples are filtered by organization."""

    def test_queries_organization_index_with_callers_org(self):
        """Handler should query OrganizationIndex GSI with the caller's org ID."""
        mock_lims, mock_state = _mock_tables()
        mock_lims.query.return_value = {'Items': []}

        lims_samples.handler(_auth_event(org_id=ORG_ACME), {})

        mock_lims.query.assert_called_once()
        call_kwargs = mock_lims.query.call_args[1]
        assert call_kwargs['IndexName'] == 'OrganizationIndex'

    def test_acme_user_sees_only_acme_samples(self):
        """ACME user should see ACME samples, not BioCorp."""
        mock_lims, mock_state = _mock_tables()
        mock_lims.query.return_value = {'Items': list(ACME_SAMPLES)}
        mock_state.query.return_value = {'Items': []}

        result = lims_samples.handler(_auth_event(org_id=ORG_ACME), {})
        body = json.loads(result['body'])

        assert result['statusCode'] == 200
        assert body['count'] == 2
        for sample in body['samples']:
            assert sample['OrganizationID'] == ORG_ACME

    def test_biocorp_user_sees_only_biocorp_samples(self):
        """BioCorp user should see BioCorp samples, not ACME."""
        mock_lims, mock_state = _mock_tables()
        mock_lims.query.return_value = {'Items': list(BIOCORP_SAMPLES)}
        mock_state.query.return_value = {'Items': []}

        result = lims_samples.handler(_auth_event(org_id=ORG_BIOCORP), {})
        body = json.loads(result['body'])

        assert result['statusCode'] == 200
        assert body['count'] == 1
        assert body['samples'][0]['SampleID'] == 'BIO-WES-001'

    def test_empty_org_returns_empty_list(self):
        """Org with no samples should return empty list, not error."""
        mock_lims, mock_state = _mock_tables()
        mock_lims.query.return_value = {'Items': []}

        result = lims_samples.handler(_auth_event(org_id='ORG-EMPTY'), {})
        body = json.loads(result['body'])

        assert result['statusCode'] == 200
        assert body['count'] == 0
        assert body['samples'] == []


class TestRoleAccess:
    """Test that different roles can access the samples endpoint."""

    def test_viewer_can_list_samples(self):
        mock_lims, mock_state = _mock_tables()
        mock_lims.query.return_value = {'Items': list(ACME_SAMPLES)}
        mock_state.query.return_value = {'Items': []}

        result = lims_samples.handler(_auth_event(groups='["viewer"]'), {})
        assert result['statusCode'] == 200

    def test_operator_can_list_samples(self):
        mock_lims, mock_state = _mock_tables()
        mock_lims.query.return_value = {'Items': list(ACME_SAMPLES)}
        mock_state.query.return_value = {'Items': []}

        result = lims_samples.handler(_auth_event(groups='["operator"]'), {})
        assert result['statusCode'] == 200

    def test_admin_can_list_samples(self):
        mock_lims, mock_state = _mock_tables()
        mock_lims.query.return_value = {'Items': list(ACME_SAMPLES)}
        mock_state.query.return_value = {'Items': []}

        result = lims_samples.handler(_auth_event(groups='["admin"]'), {})
        assert result['statusCode'] == 200

    def test_no_auth_returns_401(self):
        """Request without auth context returns 401."""
        result = lims_samples.handler({}, {})
        assert result['statusCode'] == 401

    def test_no_org_returns_403(self):
        """User with no organization_id claim returns 403."""
        event = {
            'requestContext': {
                'authorizer': {
                    'claims': {
                        'sub': 'test-user',
                        'email': 'test@example.com',
                        'cognito:groups': '["viewer"]',
                    }
                }
            }
        }
        result = lims_samples.handler(event, {})
        assert result['statusCode'] == 403

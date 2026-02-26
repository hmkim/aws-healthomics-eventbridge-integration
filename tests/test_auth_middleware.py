import unittest
import json
import sys
import os

# Ensure shared module is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lambda_function', 'shared'))
from auth_middleware import (
    parse_groups, has_role, require_auth, ROLE_HIERARCHY,
)


def _make_event(org_id='ORG-TEST', groups='["operator"]', email='test@example.com', **extra):
    """Build an API Gateway event with Cognito authorizer claims."""
    claims = {
        'sub': 'test-user-123',
        'email': email,
        'organization_id': org_id,
        'cognito:groups': groups,
        'custom:display_name': 'Test User',
    }
    claims.update(extra)
    return {
        'requestContext': {
            'authorizer': {
                'claims': claims,
            }
        }
    }


class TestParseGroups(unittest.TestCase):

    def test_json_list_string(self):
        self.assertEqual(parse_groups('["admin", "viewer"]'), ['admin', 'viewer'])

    def test_already_a_list(self):
        self.assertEqual(parse_groups(['admin']), ['admin'])

    def test_comma_separated(self):
        self.assertEqual(parse_groups('admin, operator'), ['admin', 'operator'])

    def test_empty_string(self):
        self.assertEqual(parse_groups(''), [])

    def test_none(self):
        self.assertEqual(parse_groups(None), [])

    def test_single_group(self):
        self.assertEqual(parse_groups('["viewer"]'), ['viewer'])

    def test_invalid_json_falls_back(self):
        self.assertEqual(parse_groups('[invalid'), [])


class TestHasRole(unittest.TestCase):

    def test_admin_has_all_roles(self):
        self.assertTrue(has_role(['admin'], 'admin'))
        self.assertTrue(has_role(['admin'], 'operator'))
        self.assertTrue(has_role(['admin'], 'viewer'))

    def test_operator_has_operator_and_viewer(self):
        self.assertTrue(has_role(['operator'], 'operator'))
        self.assertTrue(has_role(['operator'], 'viewer'))
        self.assertFalse(has_role(['operator'], 'admin'))

    def test_viewer_has_only_viewer(self):
        self.assertTrue(has_role(['viewer'], 'viewer'))
        self.assertFalse(has_role(['viewer'], 'operator'))
        self.assertFalse(has_role(['viewer'], 'admin'))

    def test_empty_groups(self):
        self.assertFalse(has_role([], 'viewer'))

    def test_unknown_group_ignored(self):
        self.assertFalse(has_role(['unknown_role'], 'viewer'))

    def test_multiple_groups_highest_wins(self):
        self.assertTrue(has_role(['viewer', 'admin'], 'admin'))


class TestRequireAuthDecorator(unittest.TestCase):

    def test_valid_viewer_access(self):
        @require_auth('viewer')
        def my_handler(event, context):
            return {'statusCode': 200, 'body': json.dumps(event['auth'])}

        event = _make_event(groups='["viewer"]')
        result = my_handler(event, None)
        self.assertEqual(result['statusCode'], 200)
        body = json.loads(result['body'])
        self.assertEqual(body['organization_id'], 'ORG-TEST')
        self.assertEqual(body['email'], 'test@example.com')

    def test_operator_accessing_viewer_endpoint(self):
        @require_auth('viewer')
        def my_handler(event, context):
            return {'statusCode': 200}

        event = _make_event(groups='["operator"]')
        result = my_handler(event, None)
        self.assertEqual(result['statusCode'], 200)

    def test_admin_accessing_operator_endpoint(self):
        @require_auth('operator')
        def my_handler(event, context):
            return {'statusCode': 200}

        event = _make_event(groups='["admin"]')
        result = my_handler(event, None)
        self.assertEqual(result['statusCode'], 200)

    def test_viewer_cannot_access_admin_endpoint(self):
        @require_auth('admin')
        def my_handler(event, context):
            return {'statusCode': 200}

        event = _make_event(groups='["viewer"]')
        result = my_handler(event, None)
        self.assertEqual(result['statusCode'], 403)
        body = json.loads(result['body'])
        self.assertIn('Required role', body['error'])

    def test_operator_cannot_access_admin_endpoint(self):
        @require_auth('admin')
        def my_handler(event, context):
            return {'statusCode': 200}

        event = _make_event(groups='["operator"]')
        result = my_handler(event, None)
        self.assertEqual(result['statusCode'], 403)

    def test_missing_organization_id_returns_403(self):
        @require_auth('viewer')
        def my_handler(event, context):
            return {'statusCode': 200}

        event = _make_event(org_id='', groups='["admin"]')
        result = my_handler(event, None)
        self.assertEqual(result['statusCode'], 403)
        body = json.loads(result['body'])
        self.assertIn('organization', body['error'].lower())

    def test_missing_auth_context_returns_401(self):
        @require_auth('viewer')
        def my_handler(event, context):
            return {'statusCode': 200}

        event = {}  # No requestContext
        result = my_handler(event, None)
        self.assertEqual(result['statusCode'], 401)

    def test_custom_org_id_claim_fallback(self):
        """When organization_id is missing, fall back to custom:organization_id."""
        @require_auth('viewer')
        def my_handler(event, context):
            return {'statusCode': 200, 'body': json.dumps(event['auth'])}

        claims = {
            'sub': 'u1',
            'email': 'a@b.com',
            'custom:organization_id': 'ORG-FALLBACK',
            'cognito:groups': '["viewer"]',
        }
        event = {'requestContext': {'authorizer': {'claims': claims}}}
        result = my_handler(event, None)
        self.assertEqual(result['statusCode'], 200)
        body = json.loads(result['body'])
        self.assertEqual(body['organization_id'], 'ORG-FALLBACK')

    def test_auth_dict_injected_into_event(self):
        @require_auth('viewer')
        def my_handler(event, context):
            auth = event['auth']
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'sub': auth['sub'],
                    'groups': auth['groups'],
                }),
            }

        event = _make_event(groups='["admin", "operator"]')
        result = my_handler(event, None)
        body = json.loads(result['body'])
        self.assertEqual(body['sub'], 'test-user-123')
        self.assertIn('admin', body['groups'])
        self.assertIn('operator', body['groups'])


if __name__ == '__main__':
    unittest.main()

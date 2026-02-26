import unittest


class TestPreTokenHandler(unittest.TestCase):
    """Tests for the Cognito Pre-Token-Generation trigger Lambda."""

    def _import_handler(self):
        from lambda_function.auth.pre_token_handler import handler
        return handler

    def _make_event(self, attributes=None):
        return {
            'request': {
                'userAttributes': attributes or {},
            },
            'response': {},
        }

    def test_injects_organization_id(self):
        handler = self._import_handler()
        event = self._make_event({
            'sub': 'user-123',
            'custom:organization_id': 'ORG-ACME',
        })
        result = handler(event, None)
        claims = result['response']['claimsOverrideDetails']['claimsToAddOrOverride']
        self.assertEqual(claims['organization_id'], 'ORG-ACME')

    def test_empty_string_when_no_org_attribute(self):
        handler = self._import_handler()
        event = self._make_event({'sub': 'user-456'})
        result = handler(event, None)
        claims = result['response']['claimsOverrideDetails']['claimsToAddOrOverride']
        self.assertEqual(claims['organization_id'], '')

    def test_preserves_existing_response_structure(self):
        handler = self._import_handler()
        event = self._make_event({
            'sub': 'user-789',
            'custom:organization_id': 'ORG-BIOCORP',
        })
        # Add existing response data
        event['response']['someOtherField'] = 'keep-me'

        result = handler(event, None)
        # Should still have the other field
        self.assertEqual(result['response']['someOtherField'], 'keep-me')
        # And the claims override
        claims = result['response']['claimsOverrideDetails']['claimsToAddOrOverride']
        self.assertEqual(claims['organization_id'], 'ORG-BIOCORP')


if __name__ == '__main__':
    unittest.main()

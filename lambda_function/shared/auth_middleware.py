"""Shared authentication middleware for LIMS Genomics Lambda functions.

Provides the ``@require_auth`` decorator that:
1. Extracts Cognito JWT claims from the API Gateway event
2. Validates the user has the required role (admin > operator > viewer)
3. Verifies organization_id is present
4. Injects ``event['auth']`` dict for downstream use
"""

import functools
import json
import logging
import os

logger = logging.getLogger(__name__)

# CORS origin from environment variable; falls back to '*' for local development
ALLOWED_ORIGIN = os.environ.get('ALLOWED_ORIGIN', '*')

# Role hierarchy: admin can do everything operator can, operator can do
# everything viewer can.
ROLE_HIERARCHY = {
    'admin': ['admin', 'operator', 'viewer'],
    'operator': ['operator', 'viewer'],
    'viewer': ['viewer'],
}


def parse_groups(raw_groups):
    """Parse cognito:groups from JWT claims.

    The value may arrive as a JSON-encoded list string (``'["admin"]'``),
    a comma-separated string, or an actual list when the framework has
    already parsed it.
    """
    if not raw_groups:
        return []
    if isinstance(raw_groups, list):
        return raw_groups
    raw = str(raw_groups).strip()
    if raw.startswith('['):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
    # Comma-separated fallback
    return [g.strip() for g in raw.split(',') if g.strip()]


def has_role(groups, required_role):
    """Check if any of the user's groups satisfy *required_role* via hierarchy."""
    for group in groups:
        allowed = ROLE_HIERARCHY.get(group, [])
        if required_role in allowed:
            return True
    return False


def require_auth(required_role='viewer'):
    """Decorator that enforces Cognito authentication and RBAC.

    Usage::

        @require_auth('operator')
        def handler(event, context):
            auth = event['auth']
            org_id = auth['organization_id']
            ...
    """
    def decorator(handler_func):
        @functools.wraps(handler_func)
        def wrapper(event, context):
            claims = _extract_claims(event)
            if claims is None:
                return _error_response(401, 'Missing authentication')

            org_id = (
                claims.get('organization_id')
                or claims.get('custom:organization_id')
                or ''
            )
            groups = parse_groups(claims.get('cognito:groups', ''))

            if not org_id:
                return _error_response(403, 'User has no organization assigned')
            if not has_role(groups, required_role):
                return _error_response(
                    403, f'Insufficient permissions. Required role: {required_role}'
                )

            event['auth'] = {
                'sub': claims.get('sub', ''),
                'email': claims.get('email', ''),
                'organization_id': org_id,
                'groups': groups,
                'display_name': claims.get('custom:display_name', ''),
            }
            return handler_func(event, context)

        return wrapper
    return decorator


def _extract_claims(event):
    """Pull claims dict from API Gateway Cognito authorizer context."""
    try:
        return event['requestContext']['authorizer']['claims']
    except (KeyError, TypeError):
        return None


def cors_headers():
    """Return standard CORS headers using the configured allowed origin."""
    return {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': ALLOWED_ORIGIN,
    }


def _error_response(status_code, message):
    return {
        'statusCode': status_code,
        'headers': cors_headers(),
        'body': json.dumps({'error': message}),
    }

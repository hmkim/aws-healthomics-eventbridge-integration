import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def handler(event, context):
    """Pre-Token-Generation Lambda trigger.

    Copies custom:organization_id from user attributes into the
    id-token claims so that downstream Lambdas can read it directly
    from ``event['requestContext']['authorizer']['claims']`` without
    needing to call Cognito again.
    """
    user_attributes = event['request']['userAttributes']
    org_id = user_attributes.get('custom:organization_id', '')

    logger.info(
        "Pre-token trigger for user %s, org=%s",
        user_attributes.get('sub', 'unknown'),
        org_id,
    )

    event['response']['claimsOverrideDetails'] = {
        'claimsToAddOrOverride': {
            'organization_id': org_id,
        },
    }
    return event

// LIMS Genomics Dashboard Configuration
// This file is populated during CDK deployment with actual values

window.LIMS_CONFIG = {
    // API Gateway endpoint (e.g., https://xxxxx.execute-api.us-east-1.amazonaws.com/prod)
    apiUrl: '',

    // Cognito Hosted UI domain (e.g., https://lims-auth.auth.us-east-1.amazoncognito.com)
    cognitoHostedUiDomain: '',

    // Cognito App Client ID
    cognitoClientId: '',

    // OAuth2 callback URL (e.g., https://xxxxx.cloudfront.net/callback.html)
    callbackUrl: '',

    // Logout redirect URL (e.g., https://xxxxx.cloudfront.net/index.html)
    logoutUrl: '',

    // Cognito User Pool ID (for reference)
    cognitoUserPoolId: '',

    // AWS Region
    region: 'us-east-1'
};

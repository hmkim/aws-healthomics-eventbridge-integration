from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    CfnOutput,
    aws_s3 as s3,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_s3_deployment as s3deploy,
    aws_cognito as cognito,
)
from constructs import Construct


class FrontendStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, api_url: str,
                 cognito_resources=None, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # S3 bucket (private, OAC-only access)
        website_bucket = s3.Bucket(
            self, "frontend-bucket",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )

        # CloudFront distribution with OAC via S3BucketOrigin
        distribution = cloudfront.Distribution(
            self, "frontend-dist",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(website_bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            ),
            default_root_object="index.html",
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=404,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.seconds(0),
                ),
                cloudfront.ErrorResponse(
                    http_status=403,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.seconds(0),
                ),
            ],
        )

        cf_domain = distribution.distribution_domain_name

        # Build config.js content
        config_js_content = f"window.LIMS_CONFIG = {{ apiUrl: '{api_url}' }};\n"

        if cognito_resources:
            user_pool_id = cognito_resources["user_pool_id"]
            domain_prefix = cognito_resources["cognito_domain_prefix"]

            # Use L1 CfnUserPoolClient to avoid cross-stack cyclic dependency.
            # The L2 user_pool.add_client() would create a reference from the
            # Cognito stack back to the Frontend stack (via CloudFront domain),
            # causing a cycle since Frontend already depends on Cognito
            # (through lims-orchestration).
            cfn_client = cognito.CfnUserPoolClient(
                self, "dashboard-client",
                user_pool_id=user_pool_id,
                client_name="lims-dashboard",
                generate_secret=False,
                explicit_auth_flows=["ALLOW_USER_SRP_AUTH", "ALLOW_REFRESH_TOKEN_AUTH", "ALLOW_USER_PASSWORD_AUTH"],
                allowed_o_auth_flows_user_pool_client=True,
                allowed_o_auth_flows=["code"],
                allowed_o_auth_scopes=["openid", "email", "profile"],
                callback_ur_ls=[
                    f"https://{cf_domain}/callback.html",
                    "http://localhost:8080/callback.html",
                ],
                logout_ur_ls=[
                    f"https://{cf_domain}/index.html",
                    "http://localhost:8080/index.html",
                ],
                access_token_validity=1,   # hours
                id_token_validity=1,       # hours
                refresh_token_validity=30,  # days
                token_validity_units=cognito.CfnUserPoolClient.TokenValidityUnitsProperty(
                    access_token="hours",
                    id_token="hours",
                    refresh_token="days",
                ),
                supported_identity_providers=["COGNITO"],
            )

            client_id = cfn_client.ref
            cognito_domain_url = f"https://{domain_prefix}.auth.{self.region}.amazoncognito.com"

            config_js_content = (
                "window.LIMS_CONFIG = {\n"
                f"  apiUrl: '{api_url}',\n"
                f"  cognitoUserPoolId: '{user_pool_id}',\n"
                f"  cognitoClientId: '{client_id}',\n"
                f"  cognitoHostedUiDomain: '{cognito_domain_url}',\n"
                f"  callbackUrl: 'https://{cf_domain}/callback.html',\n"
                f"  logoutUrl: 'https://{cf_domain}/index.html',\n"
                "};\n"
            )

            CfnOutput(self, "CognitoClientId",
                      value=client_id,
                      description="Cognito App Client ID for the dashboard")

        # Deploy frontend files + generated config.js to S3
        s3deploy.BucketDeployment(
            self, "deploy-frontend",
            sources=[
                s3deploy.Source.asset("./frontend"),
                s3deploy.Source.data("config.js", config_js_content),
            ],
            destination_bucket=website_bucket,
            distribution=distribution,  # auto-invalidate on deploy
        )

        CfnOutput(self, "FrontendUrl",
                  value=f"https://{cf_domain}",
                  description="CloudFront Frontend URL")

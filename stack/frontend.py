from aws_cdk import (
    Stack,
    RemovalPolicy,
    CfnOutput,
    aws_s3 as s3,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_s3_deployment as s3deploy,
)
from constructs import Construct


class FrontendStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, api_url: str, api_key_id: str, **kwargs) -> None:
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
        )

        # Deploy frontend files + generated config.js to S3
        s3deploy.BucketDeployment(
            self, "deploy-frontend",
            sources=[
                s3deploy.Source.asset("./frontend"),
                s3deploy.Source.data(
                    "config.js",
                    f"window.LIMS_CONFIG = {{ apiUrl: '{api_url}', apiKeyId: '{api_key_id}' }};",
                ),
            ],
            destination_bucket=website_bucket,
            distribution=distribution,  # auto-invalidate on deploy
        )

        CfnOutput(self, "FrontendUrl",
                  value=f"https://{distribution.distribution_domain_name}",
                  description="CloudFront Frontend URL")

from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    CfnOutput,
    aws_cognito as cognito,
    aws_lambda as lambda_,
    aws_iam as iam,
)
from constructs import Construct


class CognitoAuthStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, config, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        APP_NAME = "lims-genomics"
        cognito_domain_prefix = config.get(
            "COGNITO_DOMAIN_PREFIX", f"lims-genomics-{self.account}"
        )

        # ------------------------------------------------------------------
        # Pre-Token-Generation Lambda
        # ------------------------------------------------------------------
        pre_token_lambda = lambda_.Function(
            self, f"{APP_NAME}-pre-token",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="pre_token_handler.handler",
            code=lambda_.Code.from_asset("lambda_function/auth"),
            timeout=Duration.seconds(10),
            description="Injects organization_id into Cognito ID token claims",
        )

        # ------------------------------------------------------------------
        # Cognito User Pool
        # ------------------------------------------------------------------
        self.user_pool = cognito.UserPool(
            self, f"{APP_NAME}-user-pool",
            user_pool_name=f"{APP_NAME}-users",
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(email=True),
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            password_policy=cognito.PasswordPolicy(
                min_length=12,
                require_lowercase=True,
                require_uppercase=True,
                require_digits=True,
                require_symbols=True,
            ),
            mfa=cognito.Mfa.OPTIONAL,
            mfa_second_factor=cognito.MfaSecondFactor(otp=True, sms=False),
            custom_attributes={
                "organization_id": cognito.StringAttribute(
                    min_len=1, max_len=64, mutable=False,
                ),
                "display_name": cognito.StringAttribute(
                    min_len=1, max_len=128, mutable=True,
                ),
            },
            lambda_triggers=cognito.UserPoolTriggers(
                pre_token_generation=pre_token_lambda,
            ),
            removal_policy=RemovalPolicy.DESTROY,
        )

        # ------------------------------------------------------------------
        # Cognito Domain (Hosted UI)
        # ------------------------------------------------------------------
        self.cognito_domain = self.user_pool.add_domain(
            f"{APP_NAME}-domain",
            cognito_domain=cognito.CognitoDomainOptions(
                domain_prefix=cognito_domain_prefix,
            ),
        )

        # ------------------------------------------------------------------
        # User Pool Groups (role hierarchy: admin > operator > viewer)
        # ------------------------------------------------------------------
        cognito.CfnUserPoolGroup(
            self, f"{APP_NAME}-group-admin",
            user_pool_id=self.user_pool.user_pool_id,
            group_name="admin",
            description="Full access: approve/reject, run pipelines, view all",
            precedence=1,
        )
        cognito.CfnUserPoolGroup(
            self, f"{APP_NAME}-group-operator",
            user_pool_id=self.user_pool.user_pool_id,
            group_name="operator",
            description="Run pipelines and view samples",
            precedence=2,
        )
        cognito.CfnUserPoolGroup(
            self, f"{APP_NAME}-group-viewer",
            user_pool_id=self.user_pool.user_pool_id,
            group_name="viewer",
            description="Read-only access to samples and status",
            precedence=3,
        )

        # ------------------------------------------------------------------
        # Outputs
        # ------------------------------------------------------------------
        self.user_pool_id = self.user_pool.user_pool_id
        self.cognito_domain_prefix = cognito_domain_prefix

        CfnOutput(self, "UserPoolId",
                  value=self.user_pool.user_pool_id,
                  description="Cognito User Pool ID")
        CfnOutput(self, "CognitoDomain",
                  value=f"https://{cognito_domain_prefix}.auth.{self.region}.amazoncognito.com",
                  description="Cognito Hosted UI Domain URL")

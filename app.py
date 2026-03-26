#!/usr/bin/env python3
import aws_cdk as cdk
from stack.compute import OmicsWorkflowStack
from stack.cognito_auth import CognitoAuthStack
from stack.lims_orchestration import LimsOrchestrationStack
from stack.frontend import FrontendStack
import constants

app = cdk.App()

# Existing HealthOmics EventBridge workflow stack
omics_workflow = OmicsWorkflowStack(
    app, "omics-eventbridge-solution",
    env=constants.DEV_ENV,
    config=constants.DEV_CONFIG
)

# Cognito authentication stack (User Pool, Domain, Groups)
cognito_auth = CognitoAuthStack(
    app, "lims-cognito-auth",
    env=constants.DEV_ENV,
    config=constants.DEV_CONFIG,
)
cognito_auth.add_dependency(omics_workflow)

# LIMS orchestration stack (Step Functions, API Gateway, DynamoDB)
lims_orchestration = LimsOrchestrationStack(
    app, "lims-orchestration",
    env=constants.DEV_ENV,
    config=constants.DEV_CONFIG,
    omics_resources={
        "bucket_input": omics_workflow.bucket_input,
        "bucket_output": omics_workflow.bucket_output,
        "omics_role": omics_workflow.omics_role,
        "lambda_role": omics_workflow.lambda_role,
        "sns_topic": omics_workflow.sns_topic,
        "vep_workflow_id": omics_workflow.vep_workflow_id,
        "gatk_workflow_id": omics_workflow.gatk_workflow_id,
        "vep_container_image_uri": omics_workflow.vep_container_image_uri,
    },
    cognito_resources={
        "user_pool": cognito_auth.user_pool,
    },
    frontend_url=constants.DEV_CONFIG.get("FRONTEND_URL"),
)
lims_orchestration.add_dependency(cognito_auth)

# Frontend stack (S3 + CloudFront)
frontend = FrontendStack(
    app, "lims-frontend",
    env=constants.DEV_ENV,
    api_url=f"https://{lims_orchestration.api_id}.execute-api.us-east-1.amazonaws.com/v1",
    cognito_resources={
        "user_pool_id": cognito_auth.user_pool_id,
        "cognito_domain_prefix": cognito_auth.cognito_domain_prefix,
    },
)
frontend.add_dependency(lims_orchestration)

app.synth()

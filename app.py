#!/usr/bin/env python3
import aws_cdk as cdk
from stack.compute import OmicsWorkflowStack
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

# New LIMS orchestration stack (Step Functions, API Gateway, DynamoDB)
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
    }
)
lims_orchestration.add_dependency(omics_workflow)

# Frontend stack (S3 + CloudFront)
frontend = FrontendStack(
    app, "lims-frontend",
    env=constants.DEV_ENV,
    api_url=f"https://{lims_orchestration.api_id}.execute-api.us-east-1.amazonaws.com/v1",
    api_key_id=lims_orchestration.api_key_id,
)
frontend.add_dependency(lims_orchestration)

app.synth()

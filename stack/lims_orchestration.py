from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    CfnOutput,
    aws_dynamodb as dynamodb,
    aws_lambda as lambda_,
    aws_iam as iam,
    aws_stepfunctions as sfn,
    aws_events as events,
    aws_events_targets as events_targets,
    aws_apigateway as apigw,
    aws_logs as logs,
)
from constructs import Construct
import json


class LimsOrchestrationStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, config, omics_resources, cognito_resources=None, frontend_url=None, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        aws_account = self.account
        aws_region = self.region
        APP_NAME = "lims-genomics"

        # CORS allowed origin (CloudFront URL or '*' for local dev)
        allowed_origin = frontend_url or '*'

        # Unpack cross-stack resources
        bucket_input = omics_resources["bucket_input"]
        bucket_output = omics_resources["bucket_output"]
        omics_role = omics_resources["omics_role"]
        sns_topic = omics_resources["sns_topic"]
        vep_workflow_id = omics_resources["vep_workflow_id"]
        gatk_workflow_id = omics_resources["gatk_workflow_id"]
        vep_container_image_uri = omics_resources["vep_container_image_uri"]

        approval_timeout_days = config.get("APPROVAL_TIMEOUT_DAYS", 7)

        ################################################################################################
        #################################### DynamoDB Tables ############################################

        # Workflow state tracking table
        workflow_state_table = dynamodb.Table(
            self, f"{APP_NAME}-workflow-state",
            table_name="GenomicWorkflowState",
            partition_key=dynamodb.Attribute(name="SampleID", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="Timestamp", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # GSI for querying by status
        workflow_state_table.add_global_secondary_index(
            index_name="StatusIndex",
            partition_key=dynamodb.Attribute(name="Status", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="Timestamp", type=dynamodb.AttributeType.STRING),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # LIMS sample registry table
        lims_samples_table = dynamodb.Table(
            self, f"{APP_NAME}-lims-samples",
            table_name="LimsSamples",
            partition_key=dynamodb.Attribute(name="SampleID", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # GSI for querying samples by organization
        lims_samples_table.add_global_secondary_index(
            index_name="OrganizationIndex",
            partition_key=dynamodb.Attribute(name="OrganizationID", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="SampleID", type=dynamodb.AttributeType.STRING),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # Task tokens table for HealthOmics -> Step Functions callback
        task_tokens_table = dynamodb.Table(
            self, f"{APP_NAME}-task-tokens",
            table_name="WorkflowTaskTokens",
            partition_key=dynamodb.Attribute(name="RunId", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
            time_to_live_attribute="TTL",
        )

        ################################################################################################
        #################################### IAM Role for Orchestration Lambdas #########################

        orchestration_lambda_role = iam.Role(
            self, f"{APP_NAME}-orchestration-lambda-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"),
            ],
        )

        # DynamoDB access
        workflow_state_table.grant_read_write_data(orchestration_lambda_role)
        task_tokens_table.grant_read_write_data(orchestration_lambda_role)
        lims_samples_table.grant_read_write_data(orchestration_lambda_role)

        # HealthOmics access (scoped to account)
        orchestration_lambda_role.add_to_policy(iam.PolicyStatement(
            actions=["omics:StartRun", "omics:TagResource", "omics:GetRun"],
            resources=[
                f"arn:aws:omics:{aws_region}:{aws_account}:run/*",
                f"arn:aws:omics:{aws_region}:{aws_account}:workflow/*",
                f"arn:aws:omics:us-east-1::workflow/*",
            ],
        ))

        # PassRole for Omics service role
        orchestration_lambda_role.add_to_policy(iam.PolicyStatement(
            actions=["iam:PassRole"],
            resources=[omics_role.role_arn],
        ))

        # S3 access
        orchestration_lambda_role.add_to_policy(iam.PolicyStatement(
            actions=["s3:ListBucket", "s3:GetObject", "s3:PutObject"],
            resources=[
                bucket_input.bucket_arn,
                bucket_output.bucket_arn,
                bucket_input.bucket_arn + "/*",
                bucket_output.bucket_arn + "/*",
            ],
        ))

        # Step Functions task token callbacks (scoped to state machine ARN after creation)
        sfn_callback_policy = iam.PolicyStatement(
            actions=[
                "states:SendTaskSuccess",
                "states:SendTaskFailure",
                "states:SendTaskHeartbeat",
            ],
            resources=[f"arn:aws:states:{aws_region}:{aws_account}:stateMachine:{APP_NAME}-*"],
        )
        orchestration_lambda_role.add_to_policy(sfn_callback_policy)

        # SNS publish
        sns_topic.grant_publish(orchestration_lambda_role)

        # SES send email (scoped to verified identity)
        ses_sender = config.get("SES_SENDER_EMAIL", "")
        ses_identity_arn = f"arn:aws:ses:{aws_region}:{aws_account}:identity/{ses_sender}" if ses_sender else f"arn:aws:ses:{aws_region}:{aws_account}:identity/*"
        orchestration_lambda_role.add_to_policy(iam.PolicyStatement(
            actions=["ses:SendEmail"],
            resources=[ses_identity_arn],
        ))
        # SES account-level queries (no resource-level scoping available)
        orchestration_lambda_role.add_to_policy(iam.PolicyStatement(
            actions=[
                "ses:GetSendQuota",
                "ses:GetIdentityVerificationAttributes",
            ],
            resources=["*"],
        ))

        ################################################################################################
        #################################### Shared Auth Lambda Layer ##################################

        auth_layer = lambda_.LayerVersion(
            self, f"{APP_NAME}-auth-layer",
            code=lambda_.Code.from_asset("lambda_function/auth_layer"),
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_12],
            description="Shared auth middleware (require_auth decorator)",
        )

        ################################################################################################
        #################################### Lambda Functions ##########################################

        common_env = {
            "WORKFLOW_STATE_TABLE": workflow_state_table.table_name,
            "TASK_TOKENS_TABLE": task_tokens_table.table_name,
            "LOG_LEVEL": "INFO",
            "ALLOWED_ORIGIN": allowed_origin,
        }

        # Start GATK Lambda
        start_gatk_lambda = lambda_.Function(
            self, f"{APP_NAME}-start-gatk",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="start_gatk.handler",
            code=lambda_.Code.from_asset("lambda_function/sfn_helpers"),
            role=orchestration_lambda_role,
            timeout=Duration.seconds(60),
            environment={
                **common_env,
                "OMICS_ROLE": omics_role.role_arn,
                "OUTPUT_S3_LOCATION": f"s3://{bucket_output.bucket_name}/outputs",
                "GATK_WORKFLOW_ID": gatk_workflow_id,
            },
        )

        # Start VEP Lambda
        start_vep_lambda = lambda_.Function(
            self, f"{APP_NAME}-start-vep",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="start_vep.handler",
            code=lambda_.Code.from_asset("lambda_function/sfn_helpers"),
            role=orchestration_lambda_role,
            timeout=Duration.seconds(60),
            environment={
                **common_env,
                "OMICS_ROLE": omics_role.role_arn,
                "OUTPUT_S3_LOCATION": f"s3://{bucket_output.bucket_name}/outputs",
                "VEP_WORKFLOW_ID": vep_workflow_id,
                "VEP_CONTAINER_IMAGE": vep_container_image_uri,
                "VEP_SPECIES": "homo_sapiens",
                "VEP_DIR_CACHE": f"s3://aws-genomics-static-{aws_region}/omics-tutorials/data/databases/vep/",
                "VEP_CACHE_VERSION": "110",
                "VEP_GENOME": "GRCh38",
            },
        )

        # Store Token Lambda (for HealthOmics callback)
        store_token_lambda = lambda_.Function(
            self, f"{APP_NAME}-store-token",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="store_token.handler",
            code=lambda_.Code.from_asset("lambda_function/sfn_helpers"),
            role=orchestration_lambda_role,
            timeout=Duration.seconds(30),
            environment=common_env,
        )

        # Prepare Approval Lambda
        prepare_approval_lambda = lambda_.Function(
            self, f"{APP_NAME}-prepare-approval",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="prepare_approval.handler",
            code=lambda_.Code.from_asset("lambda_function/sfn_helpers"),
            role=orchestration_lambda_role,
            timeout=Duration.seconds(30),
            environment={
                **common_env,
                "SNS_TOPIC_ARN": sns_topic.topic_arn,
                "ADMIN_EMAIL": config.get("ADMIN_EMAIL", ""),
            },
        )

        # Store Approval Token Lambda
        store_approval_token_lambda = lambda_.Function(
            self, f"{APP_NAME}-store-approval-token",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="store_approval_token.handler",
            code=lambda_.Code.from_asset("lambda_function/sfn_helpers"),
            role=orchestration_lambda_role,
            timeout=Duration.seconds(30),
            environment=common_env,
        )

        # Trigger Handler Lambda (API Gateway -> Step Functions)
        trigger_handler_lambda = lambda_.Function(
            self, f"{APP_NAME}-trigger-handler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="trigger_handler.handler",
            code=lambda_.Code.from_asset("lambda_function/trigger_handler"),
            role=orchestration_lambda_role,
            timeout=Duration.seconds(30),
            environment=common_env,  # STATE_MACHINE_ARN added after creation
        )

        # Approval Handler Lambda
        approval_handler_lambda = lambda_.Function(
            self, f"{APP_NAME}-approval-handler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="approval_handler.handler",
            code=lambda_.Code.from_asset("lambda_function/approval_handler"),
            role=orchestration_lambda_role,
            timeout=Duration.seconds(30),
            environment=common_env,
        )

        # Status Query Lambda
        status_query_lambda = lambda_.Function(
            self, f"{APP_NAME}-status-query",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="status_query.handler",
            code=lambda_.Code.from_asset("lambda_function/status_query"),
            role=orchestration_lambda_role,
            timeout=Duration.seconds(30),
            environment=common_env,
        )

        # Pending Approvals Lambda
        pending_approvals_lambda = lambda_.Function(
            self, f"{APP_NAME}-pending-approvals",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="pending_approvals.handler",
            code=lambda_.Code.from_asset("lambda_function/pending_approvals"),
            role=orchestration_lambda_role,
            timeout=Duration.seconds(30),
            environment=common_env,
        )

        # LIMS Samples Lambda
        lims_samples_lambda = lambda_.Function(
            self, f"{APP_NAME}-list-samples",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="lims_samples.handler",
            code=lambda_.Code.from_asset("lambda_function/lims_samples"),
            role=orchestration_lambda_role,
            timeout=Duration.seconds(30),
            environment={
                **common_env,
                "LIMS_SAMPLES_TABLE": lims_samples_table.table_name,
            },
        )

        # Workflow Status Handler Lambda (EventBridge -> Step Functions callback)
        workflow_status_handler_lambda = lambda_.Function(
            self, f"{APP_NAME}-workflow-status-handler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="workflow_status_handler.handler",
            code=lambda_.Code.from_asset("lambda_function/workflow_status_handler"),
            role=orchestration_lambda_role,
            timeout=Duration.seconds(60),
            environment=common_env,
        )

        # Failure Notification Lambda (Step Functions -> SNS email on pipeline failure)
        failure_notification_env = {
            "SNS_TOPIC_ARN": sns_topic.topic_arn,
            "LOG_LEVEL": "INFO",
        }
        if cognito_resources:
            failure_notification_env["USER_POOL_ID"] = cognito_resources["user_pool"].user_pool_id

        failure_notification_lambda = lambda_.Function(
            self, f"{APP_NAME}-failure-notification",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="failure_notification.handler",
            code=lambda_.Code.from_asset("lambda_function/failure_notification"),
            role=orchestration_lambda_role,
            timeout=Duration.seconds(30),
            environment=failure_notification_env,
        )

        # Approved Results Lambda (list approved results)
        approved_results_lambda = lambda_.Function(
            self, f"{APP_NAME}-approved-results",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="approved_results.handler",
            code=lambda_.Code.from_asset("lambda_function/approved_results"),
            role=orchestration_lambda_role,
            timeout=Duration.seconds(30),
            environment=common_env,
        )

        # Send Results Lambda (generate presigned URLs + send email via SES)
        send_results_env = {
            **common_env,
            "SES_SENDER_EMAIL": config.get("SES_SENDER_EMAIL", ""),
        }
        if cognito_resources:
            send_results_env["USER_POOL_ID"] = cognito_resources["user_pool"].user_pool_id

        send_results_lambda = lambda_.Function(
            self, f"{APP_NAME}-send-results",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="send_results.handler",
            code=lambda_.Code.from_asset("lambda_function/send_results"),
            role=orchestration_lambda_role,
            timeout=Duration.seconds(60),
            environment=send_results_env,
        )

        # Grant Cognito ListUsersInGroup for failure notification org admin lookup
        if cognito_resources:
            orchestration_lambda_role.add_to_policy(iam.PolicyStatement(
                actions=["cognito-idp:ListUsersInGroup"],
                resources=[cognito_resources["user_pool"].user_pool_arn],
            ))

        # Attach auth layer to all API-facing Lambda functions
        for fn in [trigger_handler_lambda, status_query_lambda,
                    pending_approvals_lambda, approval_handler_lambda,
                    lims_samples_lambda, approved_results_lambda,
                    send_results_lambda]:
            fn.add_layers(auth_layer)

        ################################################################################################
        #################################### Step Functions State Machine ###############################

        # Load ASL definition and substitute resource ARNs
        with open("state_machine/genomics_pipeline.asl.json") as f:
            asl_definition = f.read()

        asl_definition = asl_definition.replace(
            "${WorkflowStateTable}", workflow_state_table.table_name
        ).replace(
            "${StartGATKFunctionArn}", start_gatk_lambda.function_arn
        ).replace(
            "${StartVEPFunctionArn}", start_vep_lambda.function_arn
        ).replace(
            "${StoreTokenFunctionArn}", store_token_lambda.function_arn
        ).replace(
            "${PrepareApprovalFunctionArn}", prepare_approval_lambda.function_arn
        ).replace(
            "${StoreApprovalTokenFunctionArn}", store_approval_token_lambda.function_arn
        ).replace(
            "${FailureNotificationFunctionArn}", failure_notification_lambda.function_arn
        )

        # Step Functions IAM role
        sfn_role = iam.Role(
            self, f"{APP_NAME}-sfn-role",
            assumed_by=iam.ServicePrincipal("states.amazonaws.com"),
        )

        # Lambda invoke permissions
        for fn in [start_gatk_lambda, start_vep_lambda, store_token_lambda,
                    prepare_approval_lambda, store_approval_token_lambda,
                    failure_notification_lambda]:
            fn.grant_invoke(sfn_role)

        # DynamoDB permissions for direct SDK integrations in ASL
        workflow_state_table.grant_read_write_data(sfn_role)

        # CloudWatch Logs
        sfn_log_group = logs.LogGroup(
            self, f"{APP_NAME}-sfn-logs",
            log_group_name=f"/aws/stepfunctions/{APP_NAME}-pipeline",
            removal_policy=RemovalPolicy.DESTROY,
            retention=logs.RetentionDays.ONE_MONTH,
        )

        state_machine = sfn.CfnStateMachine(
            self, f"{APP_NAME}-state-machine",
            state_machine_name=f"{APP_NAME}-genomics-pipeline",
            definition_string=asl_definition,
            role_arn=sfn_role.role_arn,
            state_machine_type="STANDARD",
            logging_configuration=sfn.CfnStateMachine.LoggingConfigurationProperty(
                destinations=[
                    sfn.CfnStateMachine.LogDestinationProperty(
                        cloud_watch_logs_log_group=sfn.CfnStateMachine.CloudWatchLogsLogGroupProperty(
                            log_group_arn=sfn_log_group.log_group_arn,
                        )
                    )
                ],
                include_execution_data=True,
                level="ALL",
            ),
        )

        # Grant Step Functions permission to deliver logs
        sfn_role.add_to_policy(iam.PolicyStatement(
            actions=[
                "logs:CreateLogDelivery",
                "logs:GetLogDelivery",
                "logs:UpdateLogDelivery",
                "logs:DeleteLogDelivery",
                "logs:ListLogDeliveries",
                "logs:PutLogEvents",
                "logs:PutResourcePolicy",
                "logs:DescribeResourcePolicies",
                "logs:DescribeLogGroups",
            ],
            resources=["*"],
        ))

        # Ensure state machine is created after IAM policy is ready
        state_machine.node.add_dependency(sfn_role)
        state_machine.node.add_dependency(sfn_log_group)

        # Add state machine ARN to trigger handler environment
        trigger_handler_lambda.add_environment(
            "STATE_MACHINE_ARN",
            f"arn:aws:states:{aws_region}:{aws_account}:stateMachine:{APP_NAME}-genomics-pipeline"
        )

        # Grant trigger handler permission to start executions
        orchestration_lambda_role.add_to_policy(iam.PolicyStatement(
            actions=["states:StartExecution"],
            resources=[
                f"arn:aws:states:{aws_region}:{aws_account}:stateMachine:{APP_NAME}-genomics-pipeline"
            ],
        ))

        ################################################################################################
        #################################### EventBridge Rule for HealthOmics -> SFN callback ###########

        # Route HealthOmics COMPLETED/FAILED to WorkflowStatusHandler
        sfn_callback_rule = events.Rule(
            self, f"{APP_NAME}-sfn-callback-rule",
            event_pattern=events.EventPattern(
                source=["aws.omics"],
                detail_type=["Run Status Change"],
                detail={
                    "status": ["COMPLETED", "FAILED"]
                },
            ),
        )
        sfn_callback_rule.add_target(
            events_targets.LambdaFunction(workflow_status_handler_lambda)
        )

        ################################################################################################
        #################################### API Gateway ################################################

        api = apigw.RestApi(
            self, f"{APP_NAME}-api",
            rest_api_name=f"{APP_NAME}-api",
            description="LIMS Genomics Orchestration API",
            default_cors_preflight_options=apigw.CorsOptions(
                allow_origins=[allowed_origin] if allowed_origin != '*' else apigw.Cors.ALL_ORIGINS,
                allow_methods=apigw.Cors.ALL_METHODS,
                allow_headers=["Content-Type", "X-Api-Key", "Authorization"],
            ),
            deploy_options=apigw.StageOptions(
                stage_name="v1",
                throttling_rate_limit=50,
                throttling_burst_limit=100,
            ),
        )

        # Gateway Responses — add CORS headers to error responses generated
        # by API Gateway itself (e.g., Cognito authorizer 401, throttling 429).
        # Without these, the browser blocks error responses as CORS violations.
        api.add_gateway_response(
            "default-4xx",
            type=apigw.ResponseType.DEFAULT_4_XX,
            response_headers={
                "Access-Control-Allow-Origin": f"'{allowed_origin}'",
                "Access-Control-Allow-Headers": "'Content-Type,Authorization'",
            },
        )
        api.add_gateway_response(
            "default-5xx",
            type=apigw.ResponseType.DEFAULT_5_XX,
            response_headers={
                "Access-Control-Allow-Origin": f"'{allowed_origin}'",
                "Access-Control-Allow-Headers": "'Content-Type,Authorization'",
            },
        )

        # Cognito Authorizer (replaces API Key auth)
        cognito_authorizer = None
        if cognito_resources:
            cognito_authorizer = apigw.CognitoUserPoolsAuthorizer(
                self, f"{APP_NAME}-cognito-auth",
                cognito_user_pools=[cognito_resources["user_pool"]],
            )

        method_options = {}
        if cognito_authorizer:
            method_options = {
                "authorizer": cognito_authorizer,
                "authorization_type": apigw.AuthorizationType.COGNITO,
            }

        # /v1/analysis
        analysis_resource = api.root.add_resource("analysis")

        # POST /v1/analysis/start — requires 'operator' role (enforced in Lambda)
        start_resource = analysis_resource.add_resource("start")
        start_resource.add_method(
            "POST",
            apigw.LambdaIntegration(trigger_handler_lambda),
            **method_options,
        )

        # GET /v1/analysis/status/{sample_id} — requires 'viewer' role
        status_resource = analysis_resource.add_resource("status")
        sample_id_resource = status_resource.add_resource("{sample_id}")
        sample_id_resource.add_method(
            "GET",
            apigw.LambdaIntegration(status_query_lambda),
            **method_options,
        )

        # /v1/admin
        admin_resource = api.root.add_resource("admin")

        # POST /v1/admin/approve — requires 'admin' role
        approve_resource = admin_resource.add_resource("approve")
        approve_resource.add_method(
            "POST",
            apigw.LambdaIntegration(approval_handler_lambda),
            **method_options,
        )

        # GET /v1/admin/pending — requires 'admin' role
        pending_resource = admin_resource.add_resource("pending")
        pending_resource.add_method(
            "GET",
            apigw.LambdaIntegration(pending_approvals_lambda),
            **method_options,
        )

        # GET /v1/admin/results — requires 'admin' role
        results_resource = admin_resource.add_resource("results")
        results_resource.add_method(
            "GET",
            apigw.LambdaIntegration(approved_results_lambda),
            **method_options,
        )

        # POST /v1/admin/results/send — requires 'admin' role
        results_send_resource = results_resource.add_resource("send")
        results_send_resource.add_method(
            "POST",
            apigw.LambdaIntegration(send_results_lambda),
            **method_options,
        )

        # /v1/lims
        lims_resource = api.root.add_resource("lims")

        # GET /v1/lims/samples — requires 'viewer' role
        lims_samples_resource = lims_resource.add_resource("samples")
        lims_samples_resource.add_method(
            "GET",
            apigw.LambdaIntegration(lims_samples_lambda),
            **method_options,
        )

        # POST /v1/lims/samples — register samples (operator+ role, checked in Lambda)
        lims_samples_resource.add_method(
            "POST",
            apigw.LambdaIntegration(lims_samples_lambda),
            **method_options,
        )

        ################################################################################################
        #################################### Outputs ####################################################

        # Expose properties for cross-stack references
        self.api_id = api.rest_api_id

        CfnOutput(self, "ApiUrl", value=api.url, description="API Gateway URL")
        CfnOutput(self, "StateMachineArn",
                  value=f"arn:aws:states:{aws_region}:{aws_account}:stateMachine:{APP_NAME}-genomics-pipeline",
                  description="Step Functions State Machine ARN")
        CfnOutput(self, "WorkflowStateTableName",
                  value=workflow_state_table.table_name,
                  description="DynamoDB Workflow State Table")
        CfnOutput(self, "TaskTokensTableName",
                  value=task_tokens_table.table_name,
                  description="DynamoDB Task Tokens Table")

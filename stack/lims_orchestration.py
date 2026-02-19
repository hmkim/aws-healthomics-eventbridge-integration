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

    def __init__(self, scope: Construct, construct_id: str, config, omics_resources, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        aws_account = self.account
        aws_region = self.region
        APP_NAME = "lims-genomics"

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
        lims_samples_table.grant_read_data(orchestration_lambda_role)

        # HealthOmics access
        orchestration_lambda_role.add_to_policy(iam.PolicyStatement(
            actions=["omics:StartRun", "omics:TagResource", "omics:GetRun"],
            resources=["*"],
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

        # Step Functions task token callbacks
        orchestration_lambda_role.add_to_policy(iam.PolicyStatement(
            actions=[
                "states:SendTaskSuccess",
                "states:SendTaskFailure",
                "states:SendTaskHeartbeat",
            ],
            resources=["*"],
        ))

        # SNS publish
        sns_topic.grant_publish(orchestration_lambda_role)

        ################################################################################################
        #################################### Lambda Functions ##########################################

        common_env = {
            "WORKFLOW_STATE_TABLE": workflow_state_table.table_name,
            "TASK_TOKENS_TABLE": task_tokens_table.table_name,
            "LOG_LEVEL": "INFO",
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
        )

        # Step Functions IAM role
        sfn_role = iam.Role(
            self, f"{APP_NAME}-sfn-role",
            assumed_by=iam.ServicePrincipal("states.amazonaws.com"),
        )

        # Lambda invoke permissions
        for fn in [start_gatk_lambda, start_vep_lambda, store_token_lambda,
                    prepare_approval_lambda, store_approval_token_lambda]:
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
                allow_origins=apigw.Cors.ALL_ORIGINS,
                allow_methods=apigw.Cors.ALL_METHODS,
                allow_headers=["Content-Type", "X-Api-Key", "Authorization"],
            ),
            deploy_options=apigw.StageOptions(
                stage_name="v1",
                throttling_rate_limit=50,
                throttling_burst_limit=100,
            ),
        )

        # API Key and Usage Plan
        api_key = api.add_api_key(f"{APP_NAME}-api-key")
        usage_plan = api.add_usage_plan(
            f"{APP_NAME}-usage-plan",
            name=f"{APP_NAME}-usage-plan",
            throttle=apigw.ThrottleSettings(rate_limit=50, burst_limit=100),
        )
        usage_plan.add_api_key(api_key)
        usage_plan.add_api_stage(stage=api.deployment_stage)

        # /v1/analysis
        analysis_resource = api.root.add_resource("analysis")

        # POST /v1/analysis/start
        start_resource = analysis_resource.add_resource("start")
        start_resource.add_method(
            "POST",
            apigw.LambdaIntegration(trigger_handler_lambda),
            api_key_required=True,
        )

        # GET /v1/analysis/status/{sample_id}
        status_resource = analysis_resource.add_resource("status")
        sample_id_resource = status_resource.add_resource("{sample_id}")
        sample_id_resource.add_method(
            "GET",
            apigw.LambdaIntegration(status_query_lambda),
        )

        # /v1/admin
        admin_resource = api.root.add_resource("admin")

        # POST /v1/admin/approve
        approve_resource = admin_resource.add_resource("approve")
        approve_resource.add_method(
            "POST",
            apigw.LambdaIntegration(approval_handler_lambda),
        )

        # GET /v1/admin/pending
        pending_resource = admin_resource.add_resource("pending")
        pending_resource.add_method(
            "GET",
            apigw.LambdaIntegration(pending_approvals_lambda),
        )

        # /v1/lims
        lims_resource = api.root.add_resource("lims")

        # GET /v1/lims/samples
        lims_samples_resource = lims_resource.add_resource("samples")
        lims_samples_resource.add_method(
            "GET",
            apigw.LambdaIntegration(lims_samples_lambda),
        )

        ################################################################################################
        #################################### Outputs ####################################################

        # Expose properties for cross-stack references
        self.api_id = api.rest_api_id
        self.api_key_id = api_key.key_id

        CfnOutput(self, "ApiUrl", value=api.url, description="API Gateway URL")
        CfnOutput(self, "ApiKeyId", value=api_key.key_id, description="API Key ID")
        CfnOutput(self, "StateMachineArn",
                  value=f"arn:aws:states:{aws_region}:{aws_account}:stateMachine:{APP_NAME}-genomics-pipeline",
                  description="Step Functions State Machine ARN")
        CfnOutput(self, "WorkflowStateTableName",
                  value=workflow_state_table.table_name,
                  description="DynamoDB Workflow State Table")
        CfnOutput(self, "TaskTokensTableName",
                  value=task_tokens_table.table_name,
                  description="DynamoDB Task Tokens Table")

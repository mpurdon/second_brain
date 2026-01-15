"""Agents Stack for Second Brain Python agents."""

from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
    aws_ec2 as ec2,
    aws_ecr as ecr,
    aws_ecr_assets as ecr_assets,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_logs as logs,
    aws_location as location,
    aws_secretsmanager as secretsmanager,
)
from constructs import Construct


class AgentsStack(Stack):
    """Stack containing Python agent Lambda and supporting resources."""

    def __init__(
        self,
        scope: Construct,
        id: str,
        vpc: ec2.IVpc,
        security_group: ec2.ISecurityGroup,
        database_secret: secretsmanager.ISecret,
        database_host: str,
        **kwargs,
    ) -> None:
        """Initialize the Agents Stack.

        Args:
            scope: CDK scope.
            id: Stack ID.
            vpc: VPC for Lambda functions.
            security_group: Security group for Lambda functions.
            database_secret: Secret containing database credentials.
            database_host: Database hostname.
            **kwargs: Additional stack properties.
        """
        super().__init__(scope, id, **kwargs)

        # AWS Location Service Place Index for geocoding
        self.place_index = location.CfnPlaceIndex(
            self,
            "PlaceIndex",
            index_name="second-brain-place-index",
            data_source="Esri",
            pricing_plan="RequestBasedUsage",
            description="Place index for geocoding addresses",
        )

        # IAM Role for Agent Lambda
        agent_role = iam.Role(
            self,
            "AgentLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            description="Role for Second Brain agent Lambda",
        )

        # Basic Lambda execution permissions
        agent_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "service-role/AWSLambdaVPCAccessExecutionRole"
            )
        )

        # Bedrock permissions
        agent_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                ],
                resources=["*"],
            )
        )

        # Location Service permissions
        agent_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "geo:SearchPlaceIndexForText",
                    "geo:SearchPlaceIndexForPosition",
                ],
                resources=[
                    f"arn:aws:geo:{self.region}:{self.account}:place-index/{self.place_index.index_name}"
                ],
            )
        )

        # Secrets Manager permissions
        database_secret.grant_read(agent_role)

        # Log group for agent function
        agent_log_group = logs.LogGroup(
            self,
            "AgentFunctionLogs",
            log_group_name="/aws/lambda/second-brain-agents",
            retention=logs.RetentionDays.ONE_WEEK,
        )

        # Agent Lambda function
        self.agent_function = lambda_.Function(
            self,
            "AgentFunction",
            function_name="second-brain-agents",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="agentcore_entry.lambda_handler",
            code=lambda_.Code.from_asset(
                "../agents",
                exclude=[
                    "__pycache__",
                    "*.pyc",
                    ".pytest_cache",
                    ".mypy_cache",
                    ".ruff_cache",
                    "tests",
                    ".venv",
                    "venv",
                ],
            ),
            timeout=Duration.seconds(120),
            memory_size=1024,
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            security_groups=[security_group],
            role=agent_role,
            environment={
                "DB_HOST": database_host,
                "DB_PORT": "5432",
                "DB_NAME": "second_brain",
                "DB_SECRET_ARN": database_secret.secret_arn,
                "BEDROCK_MODEL_ID": "anthropic.claude-3-5-sonnet-20241022-v2:0",
                "EMBEDDING_MODEL_ID": "amazon.titan-embed-text-v2:0",
                "LOCATION_PLACE_INDEX": self.place_index.index_name,
                "LOG_LEVEL": "INFO",
            },
            log_group=agent_log_group,
        )

        # Export function ARN
        self.function_arn = self.agent_function.function_arn

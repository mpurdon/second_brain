# CDK Infrastructure Design

**Version:** 1.0
**Date:** January 2025
**Status:** Draft

---

## Overview

This document defines the AWS CDK infrastructure for the Second Brain application. The infrastructure is organized into modular stacks that can be deployed independently while respecting dependencies.

**CDK Language:** Python (to match the agent codebase)

---

## Project Structure

```
infra/
├── app.py                          # CDK app entry point
├── cdk.json                        # CDK configuration
├── requirements.txt                # Python dependencies
├── pyproject.toml                  # Project metadata
│
├── stacks/
│   ├── __init__.py
│   ├── base.py                     # Base stack with shared config
│   ├── network.py                  # VPC and networking
│   ├── database.py                 # RDS PostgreSQL
│   ├── auth.py                     # Cognito User Pool
│   ├── api.py                      # API Gateway + Rust Lambdas
│   ├── agents.py                   # AgentCore deployment
│   ├── integrations.py             # Discord, Alexa Lambdas
│   ├── scheduling.py               # EventBridge schedules
│   └── monitoring.py               # CloudWatch, alarms
│
├── constructs/
│   ├── __init__.py
│   ├── rust_lambda.py              # Rust Lambda construct
│   ├── postgres_extensions.py      # RDS extension initializer
│   └── api_endpoint.py             # API endpoint construct
│
└── config/
    ├── __init__.py
    └── environments.py             # Environment-specific config
```

---

## Stack Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              CDK App                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────┐                                                         │
│  │   NetworkStack  │ ← VPC, Subnets, Security Groups                        │
│  └────────┬────────┘                                                         │
│           │                                                                  │
│           ▼                                                                  │
│  ┌─────────────────┐     ┌─────────────────┐                                │
│  │  DatabaseStack  │────▶│    AuthStack    │                                │
│  │  (RDS + exts)   │     │   (Cognito)     │                                │
│  └────────┬────────┘     └────────┬────────┘                                │
│           │                       │                                          │
│           ▼                       ▼                                          │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                          ApiStack                                    │    │
│  │                  (API Gateway + Rust Lambdas)                        │    │
│  └────────────────────────────────┬────────────────────────────────────┘    │
│                                   │                                          │
│           ┌───────────────────────┼───────────────────────┐                 │
│           ▼                       ▼                       ▼                 │
│  ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐       │
│  │  AgentsStack    │     │IntegrationsStack│     │SchedulingStack  │       │
│  │  (AgentCore)    │     │(Discord, Alexa) │     │ (EventBridge)   │       │
│  └─────────────────┘     └─────────────────┘     └─────────────────┘       │
│                                                                              │
│                          ┌─────────────────┐                                │
│                          │MonitoringStack  │                                │
│                          │(CloudWatch)     │                                │
│                          └─────────────────┘                                │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Stack Definitions

### 1. NetworkStack

**Purpose:** Creates the VPC and networking infrastructure.

```python
# infra/stacks/network.py

from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    CfnOutput,
)
from constructs import Construct

class NetworkStack(Stack):
    """VPC and networking infrastructure."""

    def __init__(self, scope: Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        # VPC with public and private subnets
        self.vpc = ec2.Vpc(
            self, "SecondBrainVpc",
            vpc_name="second-brain-vpc",
            max_azs=2,  # Cost optimization: 2 AZs sufficient
            nat_gateways=1,  # Cost optimization: single NAT
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="Private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="Isolated",
                    subnet_type=ec2.SubnetType.PRIVATE_ISOLATED,
                    cidr_mask=24,
                ),
            ],
        )

        # Security group for Lambda functions
        self.lambda_security_group = ec2.SecurityGroup(
            self, "LambdaSG",
            vpc=self.vpc,
            description="Security group for Lambda functions",
            allow_all_outbound=True,
        )

        # Security group for RDS
        self.rds_security_group = ec2.SecurityGroup(
            self, "RdsSG",
            vpc=self.vpc,
            description="Security group for RDS PostgreSQL",
            allow_all_outbound=False,
        )

        # Allow Lambda -> RDS
        self.rds_security_group.add_ingress_rule(
            peer=self.lambda_security_group,
            connection=ec2.Port.tcp(5432),
            description="Allow Lambda to RDS",
        )

        # VPC Endpoints for AWS services (cost optimization)
        self.vpc.add_gateway_endpoint(
            "S3Endpoint",
            service=ec2.GatewayVpcEndpointAwsService.S3,
        )

        self.vpc.add_interface_endpoint(
            "SecretsManagerEndpoint",
            service=ec2.InterfaceVpcEndpointAwsService.SECRETS_MANAGER,
            security_groups=[self.lambda_security_group],
        )

        self.vpc.add_interface_endpoint(
            "BedrockEndpoint",
            service=ec2.InterfaceVpcEndpointAwsService.BEDROCK_RUNTIME,
            security_groups=[self.lambda_security_group],
        )

        # Outputs
        CfnOutput(self, "VpcId", value=self.vpc.vpc_id)
```

---

### 2. DatabaseStack

**Purpose:** Creates RDS PostgreSQL with required extensions.

```python
# infra/stacks/database.py

from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    aws_ec2 as ec2,
    aws_rds as rds,
    aws_secretsmanager as secretsmanager,
    aws_lambda as lambda_,
    aws_iam as iam,
    CfnOutput,
    CustomResource,
)
from aws_cdk.custom_resources import Provider
from constructs import Construct

class DatabaseStack(Stack):
    """RDS PostgreSQL with pgvector, PostGIS, btree_gist extensions."""

    def __init__(
        self,
        scope: Construct,
        id: str,
        vpc: ec2.IVpc,
        security_group: ec2.ISecurityGroup,
        **kwargs
    ) -> None:
        super().__init__(scope, id, **kwargs)

        # Database credentials in Secrets Manager
        self.db_secret = secretsmanager.Secret(
            self, "DbSecret",
            secret_name="second-brain/db-credentials",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template='{"username": "sbadmin"}',
                generate_string_key="password",
                exclude_punctuation=True,
                password_length=32,
            ),
        )

        # Parameter group with custom settings
        self.parameter_group = rds.ParameterGroup(
            self, "DbParameterGroup",
            engine=rds.DatabaseInstanceEngine.postgres(
                version=rds.PostgresEngineVersion.VER_16
            ),
            parameters={
                # Enable extensions
                "shared_preload_libraries": "pg_stat_statements,pgvector",
                # Performance tuning for t4g.micro
                "max_connections": "50",
                "shared_buffers": "65536",  # 64MB
                "effective_cache_size": "196608",  # 192MB
                "work_mem": "4096",  # 4MB
                "maintenance_work_mem": "32768",  # 32MB
            },
        )

        # RDS PostgreSQL instance
        self.db_instance = rds.DatabaseInstance(
            self, "DbInstance",
            engine=rds.DatabaseInstanceEngine.postgres(
                version=rds.PostgresEngineVersion.VER_16
            ),
            instance_type=ec2.InstanceType.of(
                ec2.InstanceClass.T4G,
                ec2.InstanceSize.MICRO,
            ),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_ISOLATED,
            ),
            security_groups=[security_group],
            database_name="second_brain",
            credentials=rds.Credentials.from_secret(self.db_secret),
            parameter_group=self.parameter_group,
            allocated_storage=20,
            max_allocated_storage=100,  # Auto-scaling
            storage_encrypted=True,
            backup_retention=Duration.days(7),
            deletion_protection=False,  # Set True for production
            removal_policy=RemovalPolicy.SNAPSHOT,
            publicly_accessible=False,
            multi_az=False,  # Cost optimization
            cloudwatch_logs_exports=["postgresql"],
            enable_performance_insights=False,  # Not available on t4g.micro
        )

        # Lambda to initialize extensions
        self.init_extensions_lambda = self._create_init_extensions_lambda(
            vpc, security_group
        )

        # Custom resource to run initialization
        init_provider = Provider(
            self, "InitExtensionsProvider",
            on_event_handler=self.init_extensions_lambda,
        )

        CustomResource(
            self, "InitExtensions",
            service_token=init_provider.service_token,
            properties={
                "DbHost": self.db_instance.db_instance_endpoint_address,
                "DbName": "second_brain",
                "SecretArn": self.db_secret.secret_arn,
            },
        )

        # Outputs
        CfnOutput(self, "DbEndpoint",
            value=self.db_instance.db_instance_endpoint_address)
        CfnOutput(self, "DbSecretArn", value=self.db_secret.secret_arn)

    def _create_init_extensions_lambda(
        self,
        vpc: ec2.IVpc,
        security_group: ec2.ISecurityGroup,
    ) -> lambda_.Function:
        """Create Lambda to initialize PostgreSQL extensions."""

        init_lambda = lambda_.Function(
            self, "InitExtensionsLambda",
            function_name="second-brain-init-extensions",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="index.handler",
            code=lambda_.Code.from_inline(INIT_EXTENSIONS_CODE),
            timeout=Duration.minutes(5),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
            ),
            security_groups=[security_group],
        )

        # Grant access to secret
        self.db_secret.grant_read(init_lambda)

        return init_lambda


# Inline code for extension initialization
INIT_EXTENSIONS_CODE = '''
import json
import psycopg2
import boto3

def handler(event, context):
    if event["RequestType"] == "Delete":
        return {"Status": "SUCCESS"}

    props = event["ResourceProperties"]

    # Get credentials from Secrets Manager
    secrets = boto3.client("secretsmanager")
    secret = json.loads(
        secrets.get_secret_value(SecretId=props["SecretArn"])["SecretString"]
    )

    conn = psycopg2.connect(
        host=props["DbHost"],
        database=props["DbName"],
        user=secret["username"],
        password=secret["password"],
    )
    conn.autocommit = True
    cur = conn.cursor()

    # Create extensions
    extensions = [
        "uuid-ossp",
        "pgvector",
        "postgis",
        "btree_gist",
        "pg_trgm",
    ]

    for ext in extensions:
        try:
            cur.execute(f'CREATE EXTENSION IF NOT EXISTS "{ext}"')
            print(f"Created extension: {ext}")
        except Exception as e:
            print(f"Error creating {ext}: {e}")

    cur.close()
    conn.close()

    return {"Status": "SUCCESS"}
'''
```

---

### 3. AuthStack

**Purpose:** Creates Cognito User Pool with OAuth2 configuration.

```python
# infra/stacks/auth.py

from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    aws_cognito as cognito,
    aws_lambda as lambda_,
    CfnOutput,
)
from constructs import Construct

class AuthStack(Stack):
    """Cognito User Pool for authentication."""

    def __init__(self, scope: Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        # User Pool
        self.user_pool = cognito.UserPool(
            self, "UserPool",
            user_pool_name="second-brain-users",
            self_sign_up_enabled=True,
            sign_in_aliases=cognito.SignInAliases(
                email=True,
            ),
            auto_verify=cognito.AutoVerifiedAttrs(
                email=True,
            ),
            standard_attributes=cognito.StandardAttributes(
                email=cognito.StandardAttribute(required=True, mutable=True),
                fullname=cognito.StandardAttribute(required=False, mutable=True),
            ),
            custom_attributes={
                "family_id": cognito.StringAttribute(mutable=True),
                "timezone": cognito.StringAttribute(mutable=True),
            },
            password_policy=cognito.PasswordPolicy(
                min_length=8,
                require_lowercase=True,
                require_uppercase=True,
                require_digits=True,
                require_symbols=False,
            ),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            removal_policy=RemovalPolicy.RETAIN,
            mfa=cognito.Mfa.OPTIONAL,
            mfa_second_factor=cognito.MfaSecondFactor(
                sms=False,
                otp=True,
            ),
        )

        # Google Identity Provider
        google_provider = cognito.UserPoolIdentityProviderGoogle(
            self, "GoogleProvider",
            user_pool=self.user_pool,
            client_id="{{resolve:secretsmanager:second-brain/google-oauth:SecretString:client_id}}",
            client_secret="{{resolve:secretsmanager:second-brain/google-oauth:SecretString:client_secret}}",
            scopes=["email", "profile", "openid"],
            attribute_mapping=cognito.AttributeMapping(
                email=cognito.ProviderAttribute.GOOGLE_EMAIL,
                fullname=cognito.ProviderAttribute.GOOGLE_NAME,
            ),
        )

        # Amazon Provider (for Alexa Account Linking)
        amazon_provider = cognito.UserPoolIdentityProviderAmazon(
            self, "AmazonProvider",
            user_pool=self.user_pool,
            client_id="{{resolve:secretsmanager:second-brain/amazon-oauth:SecretString:client_id}}",
            client_secret="{{resolve:secretsmanager:second-brain/amazon-oauth:SecretString:client_secret}}",
            scopes=["profile"],
            attribute_mapping=cognito.AttributeMapping(
                email=cognito.ProviderAttribute.AMAZON_EMAIL,
                fullname=cognito.ProviderAttribute.AMAZON_NAME,
            ),
        )

        # App Client for Web
        self.web_client = self.user_pool.add_client(
            "WebClient",
            user_pool_client_name="second-brain-web",
            generate_secret=False,
            auth_flows=cognito.AuthFlow(
                user_password=True,
                user_srp=True,
            ),
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(
                    authorization_code_grant=True,
                ),
                scopes=[
                    cognito.OAuthScope.EMAIL,
                    cognito.OAuthScope.OPENID,
                    cognito.OAuthScope.PROFILE,
                ],
                callback_urls=[
                    "http://localhost:3000/callback",
                    "https://app.secondbrain.example.com/callback",
                ],
                logout_urls=[
                    "http://localhost:3000",
                    "https://app.secondbrain.example.com",
                ],
            ),
            supported_identity_providers=[
                cognito.UserPoolClientIdentityProvider.GOOGLE,
                cognito.UserPoolClientIdentityProvider.COGNITO,
            ],
            access_token_validity=Duration.hours(1),
            id_token_validity=Duration.hours(1),
            refresh_token_validity=Duration.days(30),
        )

        # App Client for Alexa (with secret for account linking)
        self.alexa_client = self.user_pool.add_client(
            "AlexaClient",
            user_pool_client_name="second-brain-alexa",
            generate_secret=True,
            auth_flows=cognito.AuthFlow(
                user_password=True,
            ),
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(
                    authorization_code_grant=True,
                    implicit_code_grant=True,  # Required for Alexa
                ),
                scopes=[
                    cognito.OAuthScope.EMAIL,
                    cognito.OAuthScope.OPENID,
                    cognito.OAuthScope.PROFILE,
                ],
                callback_urls=[
                    "https://layla.amazon.com/api/skill/link/*",
                    "https://alexa.amazon.co.jp/api/skill/link/*",
                    "https://pitangui.amazon.com/api/skill/link/*",
                ],
            ),
            supported_identity_providers=[
                cognito.UserPoolClientIdentityProvider.AMAZON,
                cognito.UserPoolClientIdentityProvider.COGNITO,
            ],
        )

        # App Client for Discord Bot
        self.discord_client = self.user_pool.add_client(
            "DiscordClient",
            user_pool_client_name="second-brain-discord",
            generate_secret=True,
            auth_flows=cognito.AuthFlow(
                user_password=True,
            ),
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(
                    authorization_code_grant=True,
                ),
                scopes=[
                    cognito.OAuthScope.EMAIL,
                    cognito.OAuthScope.OPENID,
                ],
                callback_urls=[
                    "https://api.secondbrain.example.com/discord/callback",
                ],
            ),
        )

        # Cognito Domain
        self.domain = self.user_pool.add_domain(
            "CognitoDomain",
            cognito_domain=cognito.CognitoDomainOptions(
                domain_prefix="second-brain",
            ),
        )

        # Outputs
        CfnOutput(self, "UserPoolId", value=self.user_pool.user_pool_id)
        CfnOutput(self, "UserPoolArn", value=self.user_pool.user_pool_arn)
        CfnOutput(self, "WebClientId", value=self.web_client.user_pool_client_id)
        CfnOutput(self, "CognitoDomain",
            value=f"{self.domain.domain_name}.auth.{self.region}.amazoncognito.com")
```

---

### 4. ApiStack

**Purpose:** Creates API Gateway and Rust Lambda functions.

```python
# infra/stacks/api.py

from aws_cdk import (
    Stack,
    Duration,
    aws_apigateway as apigw,
    aws_lambda as lambda_,
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_logs as logs,
    aws_cognito as cognito,
    aws_secretsmanager as secretsmanager,
    CfnOutput,
)
from constructs import Construct
from ..constructs.rust_lambda import RustLambda

class ApiStack(Stack):
    """API Gateway with Rust Lambda handlers."""

    def __init__(
        self,
        scope: Construct,
        id: str,
        vpc: ec2.IVpc,
        lambda_security_group: ec2.ISecurityGroup,
        db_secret: secretsmanager.ISecret,
        db_endpoint: str,
        user_pool: cognito.IUserPool,
        user_pool_client: cognito.IUserPoolClient,
        **kwargs
    ) -> None:
        super().__init__(scope, id, **kwargs)

        # Shared Lambda environment
        lambda_env = {
            "DATABASE_URL_SECRET_ARN": db_secret.secret_arn,
            "DATABASE_HOST": db_endpoint,
            "DATABASE_NAME": "second_brain",
            "RUST_LOG": "info",
            "AGENTCORE_ENDPOINT": "",  # Set by AgentsStack
        }

        # Shared Lambda role
        lambda_role = iam.Role(
            self, "LambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaVPCAccessExecutionRole"
                ),
            ],
        )

        # Grant access to secrets
        db_secret.grant_read(lambda_role)

        # Grant Bedrock access
        lambda_role.add_to_policy(iam.PolicyStatement(
            actions=[
                "bedrock:InvokeModel",
                "bedrock:InvokeAgent",
            ],
            resources=["*"],
        ))

        # Create Rust Lambdas
        self.query_lambda = RustLambda(
            self, "QueryLambda",
            function_name="second-brain-query",
            handler_path="lambdas/api-gateway",
            handler_bin="query",
            vpc=vpc,
            security_groups=[lambda_security_group],
            role=lambda_role,
            environment=lambda_env,
            timeout=Duration.seconds(30),
            memory_size=256,
        )

        self.ingest_lambda = RustLambda(
            self, "IngestLambda",
            function_name="second-brain-ingest",
            handler_path="lambdas/api-gateway",
            handler_bin="ingest",
            vpc=vpc,
            security_groups=[lambda_security_group],
            role=lambda_role,
            environment=lambda_env,
            timeout=Duration.seconds(30),
            memory_size=256,
        )

        self.briefing_lambda = RustLambda(
            self, "BriefingLambda",
            function_name="second-brain-briefing",
            handler_path="lambdas/api-gateway",
            handler_bin="briefing",
            vpc=vpc,
            security_groups=[lambda_security_group],
            role=lambda_role,
            environment=lambda_env,
            timeout=Duration.seconds(60),  # Briefings take longer
            memory_size=256,
        )

        self.calendar_lambda = RustLambda(
            self, "CalendarLambda",
            function_name="second-brain-calendar",
            handler_path="lambdas/api-gateway",
            handler_bin="calendar",
            vpc=vpc,
            security_groups=[lambda_security_group],
            role=lambda_role,
            environment=lambda_env,
            timeout=Duration.seconds(30),
            memory_size=256,
        )

        # REST API
        self.api = apigw.RestApi(
            self, "SecondBrainApi",
            rest_api_name="second-brain-api",
            description="Second Brain REST API",
            deploy_options=apigw.StageOptions(
                stage_name="v1",
                throttling_rate_limit=100,
                throttling_burst_limit=50,
                logging_level=apigw.MethodLoggingLevel.INFO,
                data_trace_enabled=True,
                metrics_enabled=True,
            ),
            default_cors_preflight_options=apigw.CorsOptions(
                allow_origins=apigw.Cors.ALL_ORIGINS,
                allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
                allow_headers=["Content-Type", "Authorization"],
            ),
        )

        # Cognito Authorizer
        authorizer = apigw.CognitoUserPoolsAuthorizer(
            self, "CognitoAuthorizer",
            cognito_user_pools=[user_pool],
            identity_source="method.request.header.Authorization",
        )

        # API Resources and Methods
        v1 = self.api.root.add_resource("v1")

        # POST /v1/query
        query = v1.add_resource("query")
        query.add_method(
            "POST",
            apigw.LambdaIntegration(self.query_lambda.function),
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # POST /v1/ingest
        ingest = v1.add_resource("ingest")
        ingest.add_method(
            "POST",
            apigw.LambdaIntegration(self.ingest_lambda.function),
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # GET /v1/briefing
        briefing = v1.add_resource("briefing")
        briefing.add_method(
            "GET",
            apigw.LambdaIntegration(self.briefing_lambda.function),
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # GET /v1/calendar
        calendar = v1.add_resource("calendar")
        calendar.add_method(
            "GET",
            apigw.LambdaIntegration(self.calendar_lambda.function),
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # POST /v1/calendar
        calendar.add_method(
            "POST",
            apigw.LambdaIntegration(self.calendar_lambda.function),
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # /v1/entities/{id}
        entities = v1.add_resource("entities")
        entity = entities.add_resource("{entity_id}")
        entity.add_method(
            "GET",
            apigw.LambdaIntegration(self.query_lambda.function),
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # Outputs
        CfnOutput(self, "ApiUrl", value=self.api.url)
        CfnOutput(self, "ApiId", value=self.api.rest_api_id)
```

---

### 5. AgentsStack

**Purpose:** Deploys Python agents to AgentCore Runtime.

```python
# infra/stacks/agents.py

from aws_cdk import (
    Stack,
    Duration,
    aws_iam as iam,
    aws_ec2 as ec2,
    aws_ecr as ecr,
    aws_ecr_assets as ecr_assets,
    aws_secretsmanager as secretsmanager,
    CfnOutput,
)
from constructs import Construct

class AgentsStack(Stack):
    """AgentCore deployment for Python agents."""

    def __init__(
        self,
        scope: Construct,
        id: str,
        vpc: ec2.IVpc,
        lambda_security_group: ec2.ISecurityGroup,
        db_secret: secretsmanager.ISecret,
        db_endpoint: str,
        **kwargs
    ) -> None:
        super().__init__(scope, id, **kwargs)

        # IAM Role for AgentCore
        self.agent_role = iam.Role(
            self, "AgentCoreRole",
            assumed_by=iam.CompositePrincipal(
                iam.ServicePrincipal("bedrock.amazonaws.com"),
                iam.ServicePrincipal("lambda.amazonaws.com"),
            ),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaVPCAccessExecutionRole"
                ),
            ],
        )

        # Bedrock permissions
        self.agent_role.add_to_policy(iam.PolicyStatement(
            actions=[
                "bedrock:InvokeModel",
                "bedrock:InvokeModelWithResponseStream",
            ],
            resources=[
                f"arn:aws:bedrock:{self.region}::foundation-model/anthropic.claude-sonnet-4-20250514-v1:0",
                f"arn:aws:bedrock:{self.region}::foundation-model/anthropic.claude-haiku-4-20250514-v1:0",
                f"arn:aws:bedrock:{self.region}::foundation-model/amazon.titan-embed-text-v2:0",
            ],
        ))

        # AWS Location Service permissions
        self.agent_role.add_to_policy(iam.PolicyStatement(
            actions=[
                "geo:SearchPlaceIndexForText",
            ],
            resources=[
                f"arn:aws:geo:{self.region}:{self.account}:place-index/second-brain-places",
            ],
        ))

        # Database secret access
        db_secret.grant_read(self.agent_role)

        # ECR Repository for agent container
        self.agent_repository = ecr.Repository(
            self, "AgentRepository",
            repository_name="second-brain-agents",
            image_scan_on_push=True,
        )

        # Build and push agent container
        self.agent_image = ecr_assets.DockerImageAsset(
            self, "AgentImage",
            directory="../agents",
            file="Dockerfile",
            build_args={
                "DB_HOST": db_endpoint,
            },
        )

        # AgentCore Agent definition
        # Note: AgentCore CDK constructs may vary - this is conceptual
        # See AWS documentation for actual AgentCore CDK support

        self.agent_config = {
            "agent_name": "second-brain-swarm",
            "agent_description": "Second Brain multi-agent swarm for knowledge management",
            "foundation_model": "anthropic.claude-sonnet-4-20250514-v1:0",
            "instruction": "You are the Second Brain assistant, helping users manage personal knowledge.",
            "idle_session_ttl_in_seconds": 1800,
            "memory_config": {
                "enabled_memory_types": ["SESSION_SUMMARY"],
                "storage_days": 30,
            },
        }

        # Create AWS Location Place Index
        # Note: This may need to be a custom resource or separate stack

        # Outputs
        CfnOutput(self, "AgentRoleArn", value=self.agent_role.role_arn)
        CfnOutput(self, "AgentRepositoryUri", value=self.agent_repository.repository_uri)
```

---

### 6. IntegrationsStack

**Purpose:** Discord and Alexa integration Lambdas.

```python
# infra/stacks/integrations.py

from aws_cdk import (
    Stack,
    Duration,
    aws_lambda as lambda_,
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_secretsmanager as secretsmanager,
    aws_apigateway as apigw,
    CfnOutput,
)
from constructs import Construct
from ..constructs.rust_lambda import RustLambda

class IntegrationsStack(Stack):
    """Discord and Alexa integration handlers."""

    def __init__(
        self,
        scope: Construct,
        id: str,
        vpc: ec2.IVpc,
        lambda_security_group: ec2.ISecurityGroup,
        db_secret: secretsmanager.ISecret,
        db_endpoint: str,
        api: apigw.IRestApi,
        **kwargs
    ) -> None:
        super().__init__(scope, id, **kwargs)

        # Discord webhook secret
        self.discord_secret = secretsmanager.Secret(
            self, "DiscordSecret",
            secret_name="second-brain/discord",
            description="Discord bot credentials",
        )

        # Alexa skill secret
        self.alexa_secret = secretsmanager.Secret(
            self, "AlexaSecret",
            secret_name="second-brain/alexa",
            description="Alexa skill credentials",
        )

        # Shared environment
        lambda_env = {
            "DATABASE_URL_SECRET_ARN": db_secret.secret_arn,
            "DATABASE_HOST": db_endpoint,
            "DATABASE_NAME": "second_brain",
            "RUST_LOG": "info",
        }

        # Shared Lambda role
        lambda_role = iam.Role(
            self, "IntegrationLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaVPCAccessExecutionRole"
                ),
            ],
        )

        db_secret.grant_read(lambda_role)
        self.discord_secret.grant_read(lambda_role)
        self.alexa_secret.grant_read(lambda_role)

        # Bedrock access for integrations
        lambda_role.add_to_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeAgent"],
            resources=["*"],
        ))

        # Transcribe access for voice
        lambda_role.add_to_policy(iam.PolicyStatement(
            actions=[
                "transcribe:StartStreamTranscription",
                "transcribe:StartTranscriptionJob",
            ],
            resources=["*"],
        ))

        # Polly access for TTS
        lambda_role.add_to_policy(iam.PolicyStatement(
            actions=["polly:SynthesizeSpeech"],
            resources=["*"],
        ))

        # Discord Webhook Lambda
        self.discord_lambda = RustLambda(
            self, "DiscordLambda",
            function_name="second-brain-discord",
            handler_path="lambdas/discord-webhook",
            handler_bin="discord_webhook",
            vpc=vpc,
            security_groups=[lambda_security_group],
            role=lambda_role,
            environment={
                **lambda_env,
                "DISCORD_SECRET_ARN": self.discord_secret.secret_arn,
            },
            timeout=Duration.seconds(30),
            memory_size=256,
        )

        # Alexa Skill Lambda
        self.alexa_lambda = RustLambda(
            self, "AlexaLambda",
            function_name="second-brain-alexa",
            handler_path="lambdas/alexa-skill",
            handler_bin="alexa_skill",
            vpc=vpc,
            security_groups=[lambda_security_group],
            role=lambda_role,
            environment={
                **lambda_env,
                "ALEXA_SECRET_ARN": self.alexa_secret.secret_arn,
            },
            timeout=Duration.seconds(8),  # Alexa has strict timeout
            memory_size=256,
        )

        # Add Alexa trigger permission
        self.alexa_lambda.function.add_permission(
            "AlexaInvoke",
            principal=iam.ServicePrincipal("alexa-appkit.amazon.com"),
            action="lambda:InvokeFunction",
            # Event source token will be the Alexa Skill ID
        )

        # Discord webhook endpoint on API Gateway
        discord = api.root.add_resource("discord")
        webhook = discord.add_resource("webhook")
        webhook.add_method(
            "POST",
            apigw.LambdaIntegration(self.discord_lambda.function),
            # No auth - Discord handles verification
        )

        # Discord OAuth callback
        callback = discord.add_resource("callback")
        callback.add_method(
            "GET",
            apigw.LambdaIntegration(self.discord_lambda.function),
        )

        # Outputs
        CfnOutput(self, "DiscordWebhookUrl",
            value=f"{api.url}discord/webhook")
        CfnOutput(self, "AlexaLambdaArn",
            value=self.alexa_lambda.function.function_arn)
```

---

### 7. SchedulingStack

**Purpose:** EventBridge schedules for proactive features.

```python
# infra/stacks/scheduling.py

from aws_cdk import (
    Stack,
    Duration,
    aws_events as events,
    aws_events_targets as targets,
    aws_lambda as lambda_,
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_secretsmanager as secretsmanager,
    CfnOutput,
)
from constructs import Construct
from ..constructs.rust_lambda import RustLambda

class SchedulingStack(Stack):
    """EventBridge schedules for proactive notifications."""

    def __init__(
        self,
        scope: Construct,
        id: str,
        vpc: ec2.IVpc,
        lambda_security_group: ec2.ISecurityGroup,
        db_secret: secretsmanager.ISecret,
        db_endpoint: str,
        **kwargs
    ) -> None:
        super().__init__(scope, id, **kwargs)

        # Shared environment
        lambda_env = {
            "DATABASE_URL_SECRET_ARN": db_secret.secret_arn,
            "DATABASE_HOST": db_endpoint,
            "DATABASE_NAME": "second_brain",
            "RUST_LOG": "info",
        }

        # Shared Lambda role
        lambda_role = iam.Role(
            self, "SchedulerLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaVPCAccessExecutionRole"
                ),
            ],
        )

        db_secret.grant_read(lambda_role)

        # Bedrock access
        lambda_role.add_to_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeAgent"],
            resources=["*"],
        ))

        # SNS access for notifications
        lambda_role.add_to_policy(iam.PolicyStatement(
            actions=[
                "sns:Publish",
            ],
            resources=["*"],  # Restrict in production
        ))

        # Morning Briefing Dispatcher Lambda
        self.briefing_dispatcher = RustLambda(
            self, "BriefingDispatcher",
            function_name="second-brain-briefing-dispatcher",
            handler_path="lambdas/event-triggers",
            handler_bin="briefing_dispatcher",
            vpc=vpc,
            security_groups=[lambda_security_group],
            role=lambda_role,
            environment=lambda_env,
            timeout=Duration.minutes(5),
            memory_size=256,
        )

        # Reminder Evaluator Lambda
        self.reminder_evaluator = RustLambda(
            self, "ReminderEvaluator",
            function_name="second-brain-reminder-evaluator",
            handler_path="lambdas/event-triggers",
            handler_bin="reminder_evaluator",
            vpc=vpc,
            security_groups=[lambda_security_group],
            role=lambda_role,
            environment=lambda_env,
            timeout=Duration.minutes(5),
            memory_size=256,
        )

        # Calendar Sync Lambda
        self.calendar_sync = RustLambda(
            self, "CalendarSync",
            function_name="second-brain-calendar-sync",
            handler_path="lambdas/event-triggers",
            handler_bin="calendar_sync",
            vpc=vpc,
            security_groups=[lambda_security_group],
            role=lambda_role,
            environment=lambda_env,
            timeout=Duration.minutes(5),
            memory_size=256,
        )

        # Schedule: Morning briefings (runs every hour, filters by user timezone)
        events.Rule(
            self, "BriefingSchedule",
            rule_name="second-brain-briefing-schedule",
            description="Trigger morning briefings based on user timezones",
            schedule=events.Schedule.rate(Duration.hours(1)),
            targets=[
                targets.LambdaFunction(
                    self.briefing_dispatcher.function,
                    retry_attempts=2,
                ),
            ],
        )

        # Schedule: Reminder evaluation (every 15 minutes)
        events.Rule(
            self, "ReminderSchedule",
            rule_name="second-brain-reminder-schedule",
            description="Evaluate pending reminders",
            schedule=events.Schedule.rate(Duration.minutes(15)),
            targets=[
                targets.LambdaFunction(
                    self.reminder_evaluator.function,
                    retry_attempts=2,
                ),
            ],
        )

        # Schedule: Calendar sync (every 15 minutes)
        events.Rule(
            self, "CalendarSyncSchedule",
            rule_name="second-brain-calendar-sync",
            description="Sync external calendars",
            schedule=events.Schedule.rate(Duration.minutes(15)),
            targets=[
                targets.LambdaFunction(
                    self.calendar_sync.function,
                    retry_attempts=2,
                ),
            ],
        )

        # Schedule: Daily cleanup (2 AM UTC)
        events.Rule(
            self, "DailyCleanup",
            rule_name="second-brain-daily-cleanup",
            description="Daily maintenance tasks",
            schedule=events.Schedule.cron(
                minute="0",
                hour="2",
            ),
            targets=[
                # Add cleanup Lambda when implemented
            ],
        )

        # Outputs
        CfnOutput(self, "BriefingDispatcherArn",
            value=self.briefing_dispatcher.function.function_arn)
```

---

### 8. MonitoringStack

**Purpose:** CloudWatch dashboards and alarms.

```python
# infra/stacks/monitoring.py

from aws_cdk import (
    Stack,
    Duration,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
    aws_sns as sns,
    aws_logs as logs,
    CfnOutput,
)
from constructs import Construct

class MonitoringStack(Stack):
    """CloudWatch monitoring and alerting."""

    def __init__(
        self,
        scope: Construct,
        id: str,
        lambda_functions: list,
        db_instance_id: str,
        api_name: str,
        **kwargs
    ) -> None:
        super().__init__(scope, id, **kwargs)

        # SNS Topic for alerts
        self.alert_topic = sns.Topic(
            self, "AlertTopic",
            topic_name="second-brain-alerts",
            display_name="Second Brain Alerts",
        )

        # Dashboard
        self.dashboard = cloudwatch.Dashboard(
            self, "Dashboard",
            dashboard_name="SecondBrain",
        )

        # Lambda metrics widget
        lambda_invocations = cloudwatch.GraphWidget(
            title="Lambda Invocations",
            width=12,
            height=6,
        )

        lambda_errors = cloudwatch.GraphWidget(
            title="Lambda Errors",
            width=12,
            height=6,
        )

        lambda_duration = cloudwatch.GraphWidget(
            title="Lambda Duration",
            width=12,
            height=6,
        )

        for fn in lambda_functions:
            lambda_invocations.add_left_metric(cloudwatch.Metric(
                namespace="AWS/Lambda",
                metric_name="Invocations",
                dimensions_map={"FunctionName": fn.function_name},
                statistic="Sum",
                period=Duration.minutes(5),
            ))

            lambda_errors.add_left_metric(cloudwatch.Metric(
                namespace="AWS/Lambda",
                metric_name="Errors",
                dimensions_map={"FunctionName": fn.function_name},
                statistic="Sum",
                period=Duration.minutes(5),
            ))

            lambda_duration.add_left_metric(cloudwatch.Metric(
                namespace="AWS/Lambda",
                metric_name="Duration",
                dimensions_map={"FunctionName": fn.function_name},
                statistic="Average",
                period=Duration.minutes(5),
            ))

        # RDS metrics widget
        rds_connections = cloudwatch.GraphWidget(
            title="RDS Connections",
            width=12,
            height=6,
            left=[
                cloudwatch.Metric(
                    namespace="AWS/RDS",
                    metric_name="DatabaseConnections",
                    dimensions_map={"DBInstanceIdentifier": db_instance_id},
                    statistic="Average",
                    period=Duration.minutes(5),
                ),
            ],
        )

        rds_cpu = cloudwatch.GraphWidget(
            title="RDS CPU",
            width=12,
            height=6,
            left=[
                cloudwatch.Metric(
                    namespace="AWS/RDS",
                    metric_name="CPUUtilization",
                    dimensions_map={"DBInstanceIdentifier": db_instance_id},
                    statistic="Average",
                    period=Duration.minutes(5),
                ),
            ],
        )

        # API Gateway metrics
        api_requests = cloudwatch.GraphWidget(
            title="API Requests",
            width=12,
            height=6,
            left=[
                cloudwatch.Metric(
                    namespace="AWS/ApiGateway",
                    metric_name="Count",
                    dimensions_map={"ApiName": api_name},
                    statistic="Sum",
                    period=Duration.minutes(5),
                ),
            ],
        )

        api_latency = cloudwatch.GraphWidget(
            title="API Latency",
            width=12,
            height=6,
            left=[
                cloudwatch.Metric(
                    namespace="AWS/ApiGateway",
                    metric_name="Latency",
                    dimensions_map={"ApiName": api_name},
                    statistic="Average",
                    period=Duration.minutes(5),
                ),
            ],
        )

        # Add widgets to dashboard
        self.dashboard.add_widgets(
            lambda_invocations,
            lambda_errors,
        )
        self.dashboard.add_widgets(
            lambda_duration,
            rds_connections,
        )
        self.dashboard.add_widgets(
            rds_cpu,
            api_requests,
        )
        self.dashboard.add_widgets(
            api_latency,
        )

        # Alarms
        # High error rate alarm
        error_alarm = cloudwatch.Alarm(
            self, "HighErrorRate",
            alarm_name="SecondBrain-HighErrorRate",
            alarm_description="High Lambda error rate",
            metric=cloudwatch.Metric(
                namespace="AWS/Lambda",
                metric_name="Errors",
                statistic="Sum",
                period=Duration.minutes(5),
            ),
            threshold=10,
            evaluation_periods=2,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
        )
        error_alarm.add_alarm_action(cw_actions.SnsAction(self.alert_topic))

        # RDS high CPU alarm
        cpu_alarm = cloudwatch.Alarm(
            self, "HighDbCpu",
            alarm_name="SecondBrain-HighDbCpu",
            alarm_description="High RDS CPU utilization",
            metric=cloudwatch.Metric(
                namespace="AWS/RDS",
                metric_name="CPUUtilization",
                dimensions_map={"DBInstanceIdentifier": db_instance_id},
                statistic="Average",
                period=Duration.minutes(5),
            ),
            threshold=80,
            evaluation_periods=3,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
        )
        cpu_alarm.add_alarm_action(cw_actions.SnsAction(self.alert_topic))

        # API high latency alarm
        latency_alarm = cloudwatch.Alarm(
            self, "HighApiLatency",
            alarm_name="SecondBrain-HighApiLatency",
            alarm_description="High API latency",
            metric=cloudwatch.Metric(
                namespace="AWS/ApiGateway",
                metric_name="Latency",
                dimensions_map={"ApiName": api_name},
                statistic="p95",
                period=Duration.minutes(5),
            ),
            threshold=3000,  # 3 seconds
            evaluation_periods=3,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
        )
        latency_alarm.add_alarm_action(cw_actions.SnsAction(self.alert_topic))

        # Outputs
        CfnOutput(self, "DashboardUrl",
            value=f"https://{self.region}.console.aws.amazon.com/cloudwatch/home#dashboards:name=SecondBrain")
        CfnOutput(self, "AlertTopicArn", value=self.alert_topic.topic_arn)
```

---

## Custom Constructs

### RustLambda Construct

```python
# infra/constructs/rust_lambda.py

from aws_cdk import (
    Duration,
    aws_lambda as lambda_,
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_logs as logs,
)
from constructs import Construct
import subprocess
import os

class RustLambda(Construct):
    """Custom construct for building and deploying Rust Lambda functions."""

    def __init__(
        self,
        scope: Construct,
        id: str,
        function_name: str,
        handler_path: str,
        handler_bin: str,
        vpc: ec2.IVpc = None,
        security_groups: list = None,
        role: iam.IRole = None,
        environment: dict = None,
        timeout: Duration = Duration.seconds(30),
        memory_size: int = 256,
    ) -> None:
        super().__init__(scope, id)

        # Build the Rust binary for Lambda
        # This uses cargo-lambda for cross-compilation
        self._build_rust_lambda(handler_path, handler_bin)

        # Log group
        log_group = logs.LogGroup(
            self, f"{id}Logs",
            log_group_name=f"/aws/lambda/{function_name}",
            retention=logs.RetentionDays.TWO_WEEKS,
        )

        # Lambda function
        self.function = lambda_.Function(
            self, f"{id}Function",
            function_name=function_name,
            runtime=lambda_.Runtime.PROVIDED_AL2023,
            handler="bootstrap",
            code=lambda_.Code.from_asset(
                f"../{handler_path}/target/lambda/{handler_bin}"
            ),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
            ) if vpc else None,
            security_groups=security_groups,
            role=role,
            environment=environment or {},
            timeout=timeout,
            memory_size=memory_size,
            architecture=lambda_.Architecture.ARM_64,
            log_group=log_group,
            tracing=lambda_.Tracing.ACTIVE,
        )

    def _build_rust_lambda(self, handler_path: str, handler_bin: str) -> None:
        """Build Rust Lambda using cargo-lambda."""
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        lambda_path = os.path.join(project_root, handler_path)

        # Only build if source is newer than target
        # In production, this should be part of CI/CD
        result = subprocess.run(
            [
                "cargo", "lambda", "build",
                "--release",
                "--arm64",
                "--bin", handler_bin,
            ],
            cwd=lambda_path,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise RuntimeError(f"Failed to build Rust Lambda: {result.stderr}")
```

---

## CDK App Entry Point

```python
# infra/app.py

#!/usr/bin/env python3
import os
from aws_cdk import App, Environment
from stacks.network import NetworkStack
from stacks.database import DatabaseStack
from stacks.auth import AuthStack
from stacks.api import ApiStack
from stacks.agents import AgentsStack
from stacks.integrations import IntegrationsStack
from stacks.scheduling import SchedulingStack
from stacks.monitoring import MonitoringStack

app = App()

# Environment
env = Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=os.environ.get("CDK_DEFAULT_REGION", "us-east-1"),
)

# Network Stack
network = NetworkStack(app, "SecondBrainNetwork", env=env)

# Database Stack
database = DatabaseStack(
    app, "SecondBrainDatabase",
    vpc=network.vpc,
    security_group=network.rds_security_group,
    env=env,
)
database.add_dependency(network)

# Auth Stack
auth = AuthStack(app, "SecondBrainAuth", env=env)

# API Stack
api = ApiStack(
    app, "SecondBrainApi",
    vpc=network.vpc,
    lambda_security_group=network.lambda_security_group,
    db_secret=database.db_secret,
    db_endpoint=database.db_instance.db_instance_endpoint_address,
    user_pool=auth.user_pool,
    user_pool_client=auth.web_client,
    env=env,
)
api.add_dependency(database)
api.add_dependency(auth)

# Agents Stack
agents = AgentsStack(
    app, "SecondBrainAgents",
    vpc=network.vpc,
    lambda_security_group=network.lambda_security_group,
    db_secret=database.db_secret,
    db_endpoint=database.db_instance.db_instance_endpoint_address,
    env=env,
)
agents.add_dependency(database)

# Integrations Stack
integrations = IntegrationsStack(
    app, "SecondBrainIntegrations",
    vpc=network.vpc,
    lambda_security_group=network.lambda_security_group,
    db_secret=database.db_secret,
    db_endpoint=database.db_instance.db_instance_endpoint_address,
    api=api.api,
    env=env,
)
integrations.add_dependency(api)

# Scheduling Stack
scheduling = SchedulingStack(
    app, "SecondBrainScheduling",
    vpc=network.vpc,
    lambda_security_group=network.lambda_security_group,
    db_secret=database.db_secret,
    db_endpoint=database.db_instance.db_instance_endpoint_address,
    env=env,
)
scheduling.add_dependency(database)

# Monitoring Stack
monitoring = MonitoringStack(
    app, "SecondBrainMonitoring",
    lambda_functions=[
        api.query_lambda.function,
        api.ingest_lambda.function,
        api.briefing_lambda.function,
        integrations.discord_lambda.function,
        integrations.alexa_lambda.function,
    ],
    db_instance_id=database.db_instance.instance_identifier,
    api_name="second-brain-api",
    env=env,
)
monitoring.add_dependency(api)
monitoring.add_dependency(integrations)

app.synth()
```

---

## Configuration

### cdk.json

```json
{
  "app": "python3 app.py",
  "watch": {
    "include": ["**"],
    "exclude": [
      "README.md",
      "cdk*.json",
      "requirements*.txt",
      "**/__pycache__",
      "**/*.pyc",
      ".git",
      ".venv"
    ]
  },
  "context": {
    "@aws-cdk/aws-lambda:recognizeLayerVersion": true,
    "@aws-cdk/core:stackRelativeExports": true,
    "@aws-cdk/aws-rds:lowercaseDbIdentifier": true
  }
}
```

### requirements.txt

```
aws-cdk-lib>=2.120.0
constructs>=10.0.0
```

---

## Deployment Commands

```bash
# Initial setup
cd infra
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Build Rust Lambdas (requires cargo-lambda)
cd ../lambdas
cargo lambda build --release --arm64

# Synthesize CloudFormation
cd ../infra
cdk synth

# Deploy all stacks
cdk deploy --all

# Deploy specific stack
cdk deploy SecondBrainDatabase

# Destroy (careful!)
cdk destroy --all
```

---

## Stack Dependencies

```
NetworkStack
    │
    ├──► DatabaseStack ──────────────┐
    │                                │
    └──► AuthStack ──────────────────┼──► ApiStack
                                     │       │
                                     │       ├──► IntegrationsStack
                                     │       │
                                     ├───────┼──► AgentsStack
                                     │       │
                                     └───────┴──► SchedulingStack
                                                      │
                                                      └──► MonitoringStack
```

---

## Cost Optimization Notes

| Decision | Monthly Savings | Notes |
|----------|-----------------|-------|
| Single NAT Gateway | ~$32 | 2 AZs but 1 NAT |
| t4g.micro RDS | ~$80 | vs t3.small |
| VPC Endpoints | ~$7/endpoint | Avoids NAT charges |
| ARM64 Lambdas | ~15% | Lower cost per invocation |
| 2 AZ deployment | ~50% on NAT | vs 3 AZ |

---

*Document Version: 1.0*
*Infrastructure supports: Multi-stack deployment, Rust Lambdas, Python Agents, Full observability*

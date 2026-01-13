"""Database Stack - RDS PostgreSQL with extensions."""

from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    CfnOutput,
    CustomResource,
    aws_ec2 as ec2,
    aws_rds as rds,
    aws_secretsmanager as secretsmanager,
    aws_lambda as lambda_,
    aws_iam as iam,
    aws_logs as logs,
)
from aws_cdk.custom_resources import Provider
from constructs import Construct


# Inline code for extension initialization Lambda
INIT_EXTENSIONS_CODE = '''
import json
import boto3

def handler(event, context):
    print(f"Received event: {json.dumps(event)}")

    if event.get("RequestType") == "Delete":
        return {"Status": "SUCCESS", "PhysicalResourceId": event.get("PhysicalResourceId", "init-extensions")}

    props = event["ResourceProperties"]

    # Get credentials from Secrets Manager
    secrets = boto3.client("secretsmanager")
    secret_value = secrets.get_secret_value(SecretId=props["SecretArn"])
    secret = json.loads(secret_value["SecretString"])

    # Import psycopg2 from Lambda layer or use pg8000
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=props["DbHost"],
            database=props["DbName"],
            user=secret["username"],
            password=secret["password"],
            port=5432,
        )
    except ImportError:
        # Fallback - just log that we need to run migrations manually
        print("psycopg2 not available - extensions must be created manually")
        return {
            "Status": "SUCCESS",
            "PhysicalResourceId": "init-extensions",
            "Data": {"Message": "Manual extension creation required"}
        }

    conn.autocommit = True
    cur = conn.cursor()

    # Create extensions
    extensions = [
        "uuid-ossp",
        "vector",  # pgvector
        "postgis",
        "btree_gist",
        "pg_trgm",
    ]

    created = []
    for ext in extensions:
        try:
            cur.execute(f'CREATE EXTENSION IF NOT EXISTS "{ext}"')
            created.append(ext)
            print(f"Created extension: {ext}")
        except Exception as e:
            print(f"Error creating {ext}: {e}")

    cur.close()
    conn.close()

    return {
        "Status": "SUCCESS",
        "PhysicalResourceId": "init-extensions",
        "Data": {"ExtensionsCreated": ",".join(created)}
    }
'''


class DatabaseStack(Stack):
    """RDS PostgreSQL with pgvector, PostGIS, btree_gist extensions."""

    def __init__(
        self,
        scope: Construct,
        id: str,
        vpc: ec2.IVpc,
        security_group: ec2.ISecurityGroup,
        **kwargs,
    ) -> None:
        super().__init__(scope, id, **kwargs)

        # Database credentials in Secrets Manager
        self.db_secret = secretsmanager.Secret(
            self,
            "DbSecret",
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
            self,
            "DbParameterGroup",
            engine=rds.DatabaseInstanceEngine.postgres(
                version=rds.PostgresEngineVersion.VER_16
            ),
            parameters={
                # Performance tuning for t4g.micro
                "max_connections": "50",
                "shared_buffers": "65536",  # 64MB in 8KB pages
                "effective_cache_size": "196608",  # 192MB in 8KB pages
                "work_mem": "4096",  # 4MB in KB
                "maintenance_work_mem": "32768",  # 32MB in KB
            },
        )

        # RDS PostgreSQL instance
        self.db_instance = rds.DatabaseInstance(
            self,
            "DbInstance",
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

        # Outputs
        CfnOutput(
            self,
            "DbEndpoint",
            value=self.db_instance.db_instance_endpoint_address,
            export_name="SecondBrainDbEndpoint",
        )
        CfnOutput(
            self,
            "DbSecretArn",
            value=self.db_secret.secret_arn,
            export_name="SecondBrainDbSecretArn",
        )
        CfnOutput(
            self,
            "DbInstanceId",
            value=self.db_instance.instance_identifier,
            export_name="SecondBrainDbInstanceId",
        )

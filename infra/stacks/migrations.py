"""Migration Stack - Lambda for running database migrations from CI/CD."""

from pathlib import Path
import shutil

from aws_cdk import (
    Stack,
    Duration,
    CfnOutput,
    ILocalBundling,
    BundlingOptions,
    DockerImage,
    aws_ec2 as ec2,
    aws_lambda as lambda_,
    aws_logs as logs,
    aws_secretsmanager as secretsmanager,
)
from constructs import Construct
from jsii import implements, member


@implements(ILocalBundling)
class LocalPythonBundling:
    """Local bundling for Python Lambda without Docker (code only, no deps)."""

    def __init__(self, project_root: Path):
        self.project_root = project_root

    @member(jsii_name="tryBundle")
    def try_bundle(self, output_dir: str, options) -> bool:
        """Bundle the Lambda code locally (without psycopg2 - comes from layer)."""
        output_path = Path(output_dir)

        # Copy handler
        shutil.copy(
            self.project_root / "lambdas" / "db-migrator" / "handler.py",
            output_path / "handler.py",
        )

        # Copy migrations
        migrations_out = output_path / "migrations"
        migrations_out.mkdir(exist_ok=True)
        for sql_file in (self.project_root / "migrations").glob("*.sql"):
            shutil.copy(sql_file, migrations_out / sql_file.name)

        return True


class MigrationsStack(Stack):
    """Lambda for running database migrations from CI/CD pipelines.

    Usage from CI/CD:
        # Check migration status
        aws lambda invoke --function-name second-brain-db-migrator \\
            --payload '{"action": "status"}' response.json

        # Run all pending migrations
        aws lambda invoke --function-name second-brain-db-migrator \\
            --payload '{"action": "migrate"}' response.json

        # Run specific migration
        aws lambda invoke --function-name second-brain-db-migrator \\
            --payload '{"action": "migrate", "version": "001"}' response.json
    """

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
        super().__init__(scope, id, **kwargs)

        # Project paths
        project_root = Path(__file__).parent.parent.parent

        # Lambda layer with psycopg2 for Amazon Linux 2
        # Using Klayers - community-maintained Lambda layers
        # https://github.com/keithrozario/Klayers
        psycopg2_layer = lambda_.LayerVersion.from_layer_version_arn(
            self,
            "Psycopg2Layer",
            # Klayers psycopg2-binary for Python 3.12 in us-east-1
            layer_version_arn="arn:aws:lambda:us-east-1:770693421928:layer:Klayers-p312-psycopg2-binary:1",
        )

        # Create Lambda with bundled migrations
        self.migration_function = lambda_.Function(
            self,
            "MigrationRunner",
            function_name="second-brain-db-migrator",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=lambda_.Code.from_asset(
                str(project_root),
                bundling=BundlingOptions(
                    image=DockerImage.from_registry("public.ecr.aws/sam/build-python3.12:latest"),
                    local=LocalPythonBundling(project_root),
                    command=[
                        "bash", "-c",
                        "cp lambdas/db-migrator/handler.py /asset-output/ && "
                        "mkdir -p /asset-output/migrations && "
                        "cp migrations/*.sql /asset-output/migrations/"
                    ],
                ),
            ),
            layers=[psycopg2_layer],
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
            ),
            security_groups=[security_group],
            timeout=Duration.minutes(5),
            memory_size=256,
            environment={
                "DB_HOST": database_host,
                "DB_SECRET_ARN": database_secret.secret_arn,
            },
            log_retention=logs.RetentionDays.ONE_WEEK,
        )

        # Grant access to secrets
        database_secret.grant_read(self.migration_function)

        # Outputs
        CfnOutput(
            self,
            "MigrationFunctionName",
            value=self.migration_function.function_name,
            description="Lambda function name for CLI invocation",
        )
        CfnOutput(
            self,
            "MigrationFunctionArn",
            value=self.migration_function.function_arn,
            description="Lambda ARN for CI/CD invocation",
        )

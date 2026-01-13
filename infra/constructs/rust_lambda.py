"""Rust Lambda construct for building and deploying Rust Lambda functions."""

import os
import subprocess
from typing import Optional

from aws_cdk import (
    Duration,
    aws_lambda as lambda_,
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_logs as logs,
)
from constructs import Construct


class RustLambda(Construct):
    """Custom construct for building and deploying Rust Lambda functions.

    Uses cargo-lambda for cross-compilation to ARM64 Lambda runtime.
    """

    def __init__(
        self,
        scope: Construct,
        id: str,
        *,
        function_name: str,
        handler_path: str,
        handler_bin: str,
        vpc: Optional[ec2.IVpc] = None,
        security_groups: Optional[list[ec2.ISecurityGroup]] = None,
        role: Optional[iam.IRole] = None,
        environment: Optional[dict[str, str]] = None,
        timeout: Duration = Duration.seconds(30),
        memory_size: int = 256,
    ) -> None:
        super().__init__(scope, id)

        self.function_name = function_name
        self.handler_path = handler_path
        self.handler_bin = handler_bin

        # Build the Rust binary for Lambda (skip in synth-only mode)
        asset_path = self._get_asset_path()

        # Log group
        log_group = logs.LogGroup(
            self,
            f"{id}Logs",
            log_group_name=f"/aws/lambda/{function_name}",
            retention=logs.RetentionDays.TWO_WEEKS,
        )

        # Lambda function
        self.function = lambda_.Function(
            self,
            f"{id}Function",
            function_name=function_name,
            runtime=lambda_.Runtime.PROVIDED_AL2023,
            handler="bootstrap",
            code=lambda_.Code.from_asset(asset_path),
            vpc=vpc,
            vpc_subnets=(
                ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS)
                if vpc
                else None
            ),
            security_groups=security_groups,
            role=role,
            environment=environment or {},
            timeout=timeout,
            memory_size=memory_size,
            architecture=lambda_.Architecture.ARM_64,
            log_group=log_group,
            tracing=lambda_.Tracing.ACTIVE,
        )

    def _get_asset_path(self) -> str:
        """Get the path to the built Lambda asset.

        Returns the target directory for the built binary. The actual build
        should be done by the CI/CD pipeline or pre-synth script.
        """
        # Get the project root (two levels up from infra/constructs)
        project_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        target_path = os.path.join(
            project_root, self.handler_path, "target", "lambda", self.handler_bin
        )

        # If the target doesn't exist, create a placeholder directory
        # Real builds should use: cargo lambda build --release --arm64
        if not os.path.exists(target_path):
            os.makedirs(target_path, exist_ok=True)
            # Create a placeholder bootstrap file for synth
            bootstrap_path = os.path.join(target_path, "bootstrap")
            if not os.path.exists(bootstrap_path):
                with open(bootstrap_path, "w") as f:
                    f.write("#!/bin/bash\necho 'Placeholder - run cargo lambda build'\n")
                os.chmod(bootstrap_path, 0o755)

        return target_path

    def build(self) -> None:
        """Build the Rust Lambda using cargo-lambda.

        This should be called before deployment, typically by a build script.
        """
        project_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        lambda_path = os.path.join(project_root, self.handler_path)

        result = subprocess.run(
            [
                "cargo",
                "lambda",
                "build",
                "--release",
                "--arm64",
                "--bin",
                self.handler_bin,
            ],
            cwd=lambda_path,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise RuntimeError(f"Failed to build Rust Lambda: {result.stderr}")

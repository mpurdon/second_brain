#!/usr/bin/env python3
"""Second Brain CDK Application entry point."""

import os

from aws_cdk import App, Environment

from stacks.network import NetworkStack
from stacks.database import DatabaseStack
from stacks.auth import AuthStack

app = App()

# Environment
env = Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=os.environ.get("CDK_DEFAULT_REGION", "us-east-1"),
)

# Network Stack - VPC and security groups
network = NetworkStack(app, "SecondBrainNetwork", env=env)

# Database Stack - RDS PostgreSQL
database = DatabaseStack(
    app,
    "SecondBrainDatabase",
    vpc=network.vpc,
    security_group=network.rds_security_group,
    env=env,
)
database.add_dependency(network)

# Auth Stack - Cognito
auth = AuthStack(app, "SecondBrainAuth", env=env)

# TODO: Add remaining stacks as they are implemented
# - ApiStack
# - AgentsStack
# - IntegrationsStack
# - SchedulingStack
# - MonitoringStack

app.synth()

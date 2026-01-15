#!/usr/bin/env python3
"""Second Brain CDK Application entry point."""

import os

from aws_cdk import App, Environment

from stacks.network import NetworkStack
from stacks.database import DatabaseStack
from stacks.auth import AuthStack
from stacks.agents import AgentsStack
from stacks.api import ApiStack
from stacks.integrations import IntegrationsStack
from stacks.scheduling import SchedulingStack
from stacks.monitoring import MonitoringStack

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

# Agents Stack - Python agent Lambda
agents = AgentsStack(
    app,
    "SecondBrainAgents",
    vpc=network.vpc,
    security_group=network.lambda_security_group,
    database_secret=database.db_secret,
    database_host=database.db_instance.db_instance_endpoint_address,
    env=env,
)
agents.add_dependency(network)
agents.add_dependency(database)

# API Stack - REST API Gateway and Rust Lambdas
api = ApiStack(
    app,
    "SecondBrainApi",
    vpc=network.vpc,
    security_group=network.lambda_security_group,
    user_pool=auth.user_pool,
    agent_function_arn=agents.agent_function.function_arn,
    db_secret_arn=database.db_secret.secret_arn,
    db_host=database.db_instance.db_instance_endpoint_address,
    env=env,
)
api.add_dependency(network)
api.add_dependency(auth)
api.add_dependency(agents)
api.add_dependency(database)

# Integrations Stack - Discord, Alexa, etc.
integrations = IntegrationsStack(
    app,
    "SecondBrainIntegrations",
    vpc=network.vpc,
    security_group=network.lambda_security_group,
    agent_function_arn=agents.agent_function.function_arn,
    env=env,
)
integrations.add_dependency(network)
integrations.add_dependency(agents)

# Scheduling Stack - EventBridge rules and scheduled triggers
scheduling = SchedulingStack(
    app,
    "SecondBrainScheduling",
    vpc=network.vpc,
    security_group=network.lambda_security_group,
    database_secret=database.db_secret,
    database_host=database.db_instance.db_instance_endpoint_address,
    agent_function_arn=agents.agent_function.function_arn,
    env=env,
)
scheduling.add_dependency(network)
scheduling.add_dependency(database)
scheduling.add_dependency(agents)

# Monitoring Stack - CloudWatch dashboards and alarms
monitoring = MonitoringStack(
    app,
    "SecondBrainMonitoring",
    api_name="second-brain-api",
    db_instance_id=database.db_instance.instance_identifier,
    alert_email=os.environ.get("ALERT_EMAIL"),  # Optional: set ALERT_EMAIL env var
    env=env,
)
monitoring.add_dependency(api)
monitoring.add_dependency(database)

app.synth()

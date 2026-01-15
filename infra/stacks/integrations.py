"""Integrations Stack for Discord, Alexa, and other external platforms."""

import os
from aws_cdk import (
    Duration,
    Stack,
    aws_apigateway as apigw,
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_logs as logs,
    aws_secretsmanager as secretsmanager,
)
from constructs import Construct


def _get_lambda_asset_path(binary_name: str) -> str:
    """Get the path to a Rust Lambda asset.

    Creates a placeholder if the built binary doesn't exist.
    """
    project_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    target_path = os.path.join(
        project_root, "lambdas", "target", "lambda", binary_name
    )

    # Create placeholder if needed (for synth without build)
    if not os.path.exists(target_path):
        os.makedirs(target_path, exist_ok=True)
        bootstrap_path = os.path.join(target_path, "bootstrap")
        if not os.path.exists(bootstrap_path):
            with open(bootstrap_path, "w") as f:
                f.write("#!/bin/bash\necho 'Placeholder - run cargo lambda build'\n")
            os.chmod(bootstrap_path, 0o755)

    return target_path


class IntegrationsStack(Stack):
    """Stack containing external platform integrations (Discord, Alexa, etc.)."""

    def __init__(
        self,
        scope: Construct,
        id: str,
        vpc: ec2.IVpc,
        security_group: ec2.ISecurityGroup,
        agent_function_arn: str,
        discord_secret_arn: str | None = None,
        **kwargs,
    ) -> None:
        """Initialize the Integrations Stack.

        Args:
            scope: CDK scope.
            id: Stack ID.
            vpc: VPC for Lambda functions.
            security_group: Security group for Lambda functions.
            agent_function_arn: ARN of the agent Lambda function.
            discord_secret_arn: ARN of secret containing Discord credentials.
            **kwargs: Additional stack properties.
        """
        super().__init__(scope, id, **kwargs)

        # Discord Secret (if not provided, create one)
        if discord_secret_arn:
            discord_secret = secretsmanager.Secret.from_secret_complete_arn(
                self, "DiscordSecret", discord_secret_arn
            )
        else:
            discord_secret = secretsmanager.Secret(
                self,
                "DiscordSecret",
                secret_name="second-brain/discord",
                description="Discord bot credentials",
                generate_secret_string=secretsmanager.SecretStringGenerator(
                    secret_string_template='{"bot_token":"","application_id":"","public_key":""}',
                    generate_string_key="placeholder",
                ),
            )

        # Discord Webhook Lambda Log Group
        discord_log_group = logs.LogGroup(
            self,
            "DiscordWebhookLogs",
            log_group_name="/aws/lambda/second-brain-discord-webhook",
            retention=logs.RetentionDays.TWO_WEEKS,
        )

        # Discord Webhook Lambda
        discord_lambda = lambda_.Function(
            self,
            "DiscordWebhookLambda",
            function_name="second-brain-discord-webhook",
            runtime=lambda_.Runtime.PROVIDED_AL2023,
            handler="bootstrap",
            code=lambda_.Code.from_asset(_get_lambda_asset_path("discord_webhook")),
            description="Handles Discord bot interactions",
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            security_groups=[security_group],
            environment={
                "AGENT_FUNCTION_NAME": agent_function_arn,
                "DISCORD_SECRET_ARN": discord_secret.secret_arn,
                "LOG_LEVEL": "INFO",
                # Public key fetched from secret at runtime
                "DISCORD_PUBLIC_KEY": "PLACEHOLDER_REPLACED_AT_RUNTIME",
            },
            timeout=Duration.seconds(30),
            memory_size=256,
            architecture=lambda_.Architecture.ARM_64,
            log_group=discord_log_group,
            tracing=lambda_.Tracing.ACTIVE,
        )

        # Grant permissions
        discord_lambda.add_to_role_policy(
            iam.PolicyStatement(
                actions=["lambda:InvokeFunction"],
                resources=[agent_function_arn],
            )
        )
        discord_secret.grant_read(discord_lambda)

        # Polly permissions for text-to-speech
        discord_lambda.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "polly:SynthesizeSpeech",
                    "polly:DescribeVoices",
                ],
                resources=["*"],
            )
        )

        # Transcribe permissions for speech-to-text (future use)
        discord_lambda.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "transcribe:StartStreamTranscription",
                    "transcribe:StartTranscriptionJob",
                    "transcribe:GetTranscriptionJob",
                ],
                resources=["*"],
            )
        )

        # API Gateway for Discord webhook
        self.discord_api = apigw.RestApi(
            self,
            "DiscordWebhookApi",
            rest_api_name="second-brain-discord-webhook",
            description="Discord interaction webhook endpoint",
            deploy_options=apigw.StageOptions(
                stage_name="prod",
                throttling_rate_limit=50,
                throttling_burst_limit=100,
            ),
        )

        # Discord webhook endpoint
        webhook_resource = self.discord_api.root.add_resource("webhook")
        webhook_resource.add_method(
            "POST",
            apigw.LambdaIntegration(
                discord_lambda,
                # Don't use proxy integration - we need raw body for signature verification
                proxy=False,
                request_templates={
                    "application/json": """{
                        "body": $input.json('$'),
                        "headers": {
                            "x-signature-ed25519": "$input.params('x-signature-ed25519')",
                            "x-signature-timestamp": "$input.params('x-signature-timestamp')"
                        }
                    }"""
                },
                integration_responses=[
                    apigw.IntegrationResponse(
                        status_code="200",
                        response_templates={
                            "application/json": "$input.json('$')"
                        },
                    ),
                    apigw.IntegrationResponse(
                        status_code="401",
                        selection_pattern=".*401.*",
                    ),
                    apigw.IntegrationResponse(
                        status_code="400",
                        selection_pattern=".*400.*",
                    ),
                ],
            ),
            method_responses=[
                apigw.MethodResponse(status_code="200"),
                apigw.MethodResponse(status_code="401"),
                apigw.MethodResponse(status_code="400"),
            ],
        )

        # Export webhook URL
        self.discord_webhook_url = f"{self.discord_api.url}webhook"

        # Store the Lambda function for reference
        self.discord_lambda = discord_lambda

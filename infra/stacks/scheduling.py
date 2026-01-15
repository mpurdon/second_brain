"""Scheduling Stack for EventBridge rules and scheduled Lambda triggers."""

import os
from aws_cdk import (
    Duration,
    Stack,
    aws_ec2 as ec2,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_lambda_event_sources as lambda_event_sources,
    aws_logs as logs,
    aws_secretsmanager as secretsmanager,
    aws_sns as sns,
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


class SchedulingStack(Stack):
    """Stack containing EventBridge rules and scheduled triggers."""

    def __init__(
        self,
        scope: Construct,
        id: str,
        vpc: ec2.IVpc,
        security_group: ec2.ISecurityGroup,
        database_secret: secretsmanager.ISecret,
        database_host: str,
        agent_function_arn: str | None = None,
        google_oauth_secret_arn: str | None = None,
        discord_webhook_secret_arn: str | None = None,
        from_email: str = "noreply@secondbrain.app",
        **kwargs,
    ) -> None:
        """Initialize the Scheduling Stack.

        Args:
            scope: CDK scope.
            id: Stack ID.
            vpc: VPC for Lambda functions.
            security_group: Security group for Lambda functions.
            database_secret: Secret containing database credentials.
            database_host: Database hostname.
            agent_function_arn: ARN of the agent Lambda function.
            google_oauth_secret_arn: ARN of Google OAuth credentials secret.
            discord_webhook_secret_arn: ARN of Discord webhook secret.
            from_email: Email address for sending notifications.
            **kwargs: Additional stack properties.
        """
        super().__init__(scope, id, **kwargs)

        # SNS Topic for notifications
        self.notification_topic = sns.Topic(
            self,
            "NotificationTopic",
            topic_name="second-brain-notifications",
            display_name="Second Brain Notifications",
        )

        # Google OAuth secret
        if google_oauth_secret_arn:
            google_secret = secretsmanager.Secret.from_secret_complete_arn(
                self, "GoogleOAuthSecret", google_oauth_secret_arn
            )
        else:
            google_secret = secretsmanager.Secret(
                self,
                "GoogleOAuthSecret",
                secret_name="second-brain/google-oauth",
                description="Google OAuth credentials",
                generate_secret_string=secretsmanager.SecretStringGenerator(
                    secret_string_template='{"client_id":"","client_secret":""}',
                    generate_string_key="placeholder",
                ),
            )

        # Calendar Sync Lambda
        calendar_sync_log_group = logs.LogGroup(
            self,
            "CalendarSyncLogs",
            log_group_name="/aws/lambda/second-brain-calendar-sync",
            retention=logs.RetentionDays.ONE_WEEK,
        )

        calendar_sync_lambda = lambda_.Function(
            self,
            "CalendarSyncLambda",
            function_name="second-brain-calendar-sync",
            runtime=lambda_.Runtime.PROVIDED_AL2023,
            handler="bootstrap",
            code=lambda_.Code.from_asset(_get_lambda_asset_path("calendar_sync")),
            description="Syncs external calendars (Google, Outlook)",
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            security_groups=[security_group],
            environment={
                "DB_HOST": database_host,
                "DB_PORT": "5432",
                "DB_NAME": "second_brain",
                "DB_SECRET_ARN": database_secret.secret_arn,
                "GOOGLE_OAUTH_SECRET_ARN": google_secret.secret_arn,
                "LOG_LEVEL": "INFO",
            },
            timeout=Duration.minutes(5),
            memory_size=512,
            architecture=lambda_.Architecture.ARM_64,
            log_group=calendar_sync_log_group,
        )

        # Grant permissions
        database_secret.grant_read(calendar_sync_lambda)
        google_secret.grant_read(calendar_sync_lambda)

        # Permission to list and read user calendar secrets
        calendar_sync_lambda.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "secretsmanager:ListSecrets",
                    "secretsmanager:GetSecretValue",
                ],
                resources=["*"],
                conditions={
                    "StringLike": {
                        "secretsmanager:Name": "second-brain/calendar/*"
                    }
                },
            )
        )

        # EventBridge rule for calendar sync (every 15 minutes)
        calendar_sync_rule = events.Rule(
            self,
            "CalendarSyncSchedule",
            rule_name="second-brain-calendar-sync",
            description="Triggers calendar sync every 15 minutes",
            schedule=events.Schedule.rate(Duration.minutes(15)),
        )

        calendar_sync_rule.add_target(
            targets.LambdaFunction(calendar_sync_lambda)
        )

        # Briefing Dispatcher Lambda
        briefing_dispatcher_log_group = logs.LogGroup(
            self,
            "BriefingDispatcherLogs",
            log_group_name="/aws/lambda/second-brain-briefing-dispatcher",
            retention=logs.RetentionDays.ONE_WEEK,
        )

        briefing_env = {
            "DB_HOST": database_host,
            "DB_PORT": "5432",
            "DB_NAME": "second_brain",
            "DB_SECRET_ARN": database_secret.secret_arn,
            "LOG_LEVEL": "INFO",
        }

        if agent_function_arn:
            briefing_env["AGENT_FUNCTION_NAME"] = agent_function_arn

        briefing_dispatcher_lambda = lambda_.Function(
            self,
            "BriefingDispatcherLambda",
            function_name="second-brain-briefing-dispatcher",
            runtime=lambda_.Runtime.PROVIDED_AL2023,
            handler="bootstrap",
            code=lambda_.Code.from_asset(_get_lambda_asset_path("briefing_dispatcher")),
            description="Dispatches morning briefings to users",
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            security_groups=[security_group],
            environment=briefing_env,
            timeout=Duration.minutes(5),
            memory_size=256,
            architecture=lambda_.Architecture.ARM_64,
            log_group=briefing_dispatcher_log_group,
        )

        database_secret.grant_read(briefing_dispatcher_lambda)

        # Permission to invoke agent function
        if agent_function_arn:
            briefing_dispatcher_lambda.add_to_role_policy(
                iam.PolicyStatement(
                    actions=["lambda:InvokeFunction"],
                    resources=[agent_function_arn],
                )
            )

        # EventBridge rule for morning briefings (6 AM ET daily)
        briefing_rule = events.Rule(
            self,
            "MorningBriefingSchedule",
            rule_name="second-brain-morning-briefing",
            description="Triggers morning briefing dispatch at 6 AM ET",
            schedule=events.Schedule.cron(
                minute="0",
                hour="11",  # 11 UTC = 6 AM ET (EST)
                month="*",
                week_day="*",
                year="*",
            ),
        )

        briefing_rule.add_target(
            targets.LambdaFunction(briefing_dispatcher_lambda)
        )

        # Reminder Evaluator Lambda
        reminder_evaluator_log_group = logs.LogGroup(
            self,
            "ReminderEvaluatorLogs",
            log_group_name="/aws/lambda/second-brain-reminder-evaluator",
            retention=logs.RetentionDays.ONE_WEEK,
        )

        reminder_evaluator_lambda = lambda_.Function(
            self,
            "ReminderEvaluatorLambda",
            function_name="second-brain-reminder-evaluator",
            runtime=lambda_.Runtime.PROVIDED_AL2023,
            handler="bootstrap",
            code=lambda_.Code.from_asset(_get_lambda_asset_path("reminder_evaluator")),
            description="Evaluates and sends time-based reminders",
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            security_groups=[security_group],
            environment={
                "DB_HOST": database_host,
                "DB_PORT": "5432",
                "DB_NAME": "second_brain",
                "DB_SECRET_ARN": database_secret.secret_arn,
                "NOTIFICATION_TOPIC_ARN": self.notification_topic.topic_arn,
                "LOG_LEVEL": "INFO",
            },
            timeout=Duration.minutes(2),
            memory_size=256,
            architecture=lambda_.Architecture.ARM_64,
            log_group=reminder_evaluator_log_group,
        )

        database_secret.grant_read(reminder_evaluator_lambda)

        # Grant permission to publish to notification topic
        self.notification_topic.grant_publish(reminder_evaluator_lambda)

        # EventBridge rule for reminder evaluation (every 5 minutes)
        reminder_rule = events.Rule(
            self,
            "ReminderEvaluatorSchedule",
            rule_name="second-brain-reminder-evaluator",
            description="Evaluates reminders every 5 minutes",
            schedule=events.Schedule.rate(Duration.minutes(5)),
        )

        reminder_rule.add_target(
            targets.LambdaFunction(reminder_evaluator_lambda)
        )

        # Notification Sender Lambda
        notification_sender_log_group = logs.LogGroup(
            self,
            "NotificationSenderLogs",
            log_group_name="/aws/lambda/second-brain-notification-sender",
            retention=logs.RetentionDays.ONE_WEEK,
        )

        notification_sender_env = {
            "DB_HOST": database_host,
            "DB_PORT": "5432",
            "DB_NAME": "second_brain",
            "DB_SECRET_ARN": database_secret.secret_arn,
            "FROM_EMAIL": from_email,
            "LOG_LEVEL": "INFO",
        }

        # Add Discord webhook URL if provided
        if discord_webhook_secret_arn:
            discord_secret = secretsmanager.Secret.from_secret_complete_arn(
                self, "DiscordWebhookSecret", discord_webhook_secret_arn
            )

        notification_sender_lambda = lambda_.Function(
            self,
            "NotificationSenderLambda",
            function_name="second-brain-notification-sender",
            runtime=lambda_.Runtime.PROVIDED_AL2023,
            handler="bootstrap",
            code=lambda_.Code.from_asset(_get_lambda_asset_path("notification_sender")),
            description="Sends notifications via email, push, or Discord",
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            security_groups=[security_group],
            environment=notification_sender_env,
            timeout=Duration.minutes(1),
            memory_size=256,
            architecture=lambda_.Architecture.ARM_64,
            log_group=notification_sender_log_group,
        )

        database_secret.grant_read(notification_sender_lambda)

        # SES permissions for sending emails
        notification_sender_lambda.add_to_role_policy(
            iam.PolicyStatement(
                actions=["ses:SendEmail", "ses:SendRawEmail"],
                resources=["*"],
            )
        )

        # Subscribe to notification topic
        notification_sender_lambda.add_event_source(
            lambda_event_sources.SnsEventSource(self.notification_topic)
        )

        # Export Lambda functions
        self.calendar_sync_lambda = calendar_sync_lambda
        self.briefing_dispatcher_lambda = briefing_dispatcher_lambda
        self.reminder_evaluator_lambda = reminder_evaluator_lambda
        self.notification_sender_lambda = notification_sender_lambda

"""Monitoring Stack for Second Brain - CloudWatch dashboards and alarms."""

from aws_cdk import (
    Duration,
    Stack,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
    aws_sns as sns,
    aws_sns_subscriptions as subscriptions,
)
from constructs import Construct


class MonitoringStack(Stack):
    """Stack containing CloudWatch dashboards, metrics, and alarms."""

    def __init__(
        self,
        scope: Construct,
        id: str,
        api_name: str = "second-brain-api",
        lambda_names: list[str] | None = None,
        db_instance_id: str | None = None,
        alert_email: str | None = None,
        **kwargs,
    ) -> None:
        """Initialize the Monitoring Stack.

        Args:
            scope: CDK scope.
            id: Stack ID.
            api_name: Name of the API Gateway REST API.
            lambda_names: List of Lambda function names to monitor.
            db_instance_id: RDS instance identifier for DB metrics.
            alert_email: Email address for alarm notifications.
            **kwargs: Additional stack properties.
        """
        super().__init__(scope, id, **kwargs)

        # Default Lambda names
        if lambda_names is None:
            lambda_names = [
                "second-brain-query",
                "second-brain-ingest",
                "second-brain-briefing",
                "second-brain-calendar",
                "second-brain-families",
                "second-brain-relationships",
                "second-brain-entities",
                "second-brain-locations",
                "second-brain-tags",
                "second-brain-feedback",
            ]

        # SNS Topic for alarms
        self.alarm_topic = sns.Topic(
            self,
            "AlarmTopic",
            topic_name="second-brain-alarms",
            display_name="Second Brain Alerts",
        )

        # Add email subscription if provided
        if alert_email:
            self.alarm_topic.add_subscription(
                subscriptions.EmailSubscription(alert_email)
            )

        # Create main dashboard
        self.dashboard = cloudwatch.Dashboard(
            self,
            "MainDashboard",
            dashboard_name="SecondBrain-Overview",
        )

        # =====================================================
        # API Gateway Metrics
        # =====================================================
        api_request_count = cloudwatch.Metric(
            namespace="AWS/ApiGateway",
            metric_name="Count",
            dimensions_map={"ApiName": api_name},
            statistic="Sum",
            period=Duration.minutes(5),
        )

        api_latency = cloudwatch.Metric(
            namespace="AWS/ApiGateway",
            metric_name="Latency",
            dimensions_map={"ApiName": api_name},
            statistic="Average",
            period=Duration.minutes(5),
        )

        api_4xx_errors = cloudwatch.Metric(
            namespace="AWS/ApiGateway",
            metric_name="4XXError",
            dimensions_map={"ApiName": api_name},
            statistic="Sum",
            period=Duration.minutes(5),
        )

        api_5xx_errors = cloudwatch.Metric(
            namespace="AWS/ApiGateway",
            metric_name="5XXError",
            dimensions_map={"ApiName": api_name},
            statistic="Sum",
            period=Duration.minutes(5),
        )

        # API Gateway widgets
        self.dashboard.add_widgets(
            cloudwatch.TextWidget(
                markdown="# Second Brain API Monitoring\n---",
                width=24,
                height=1,
            ),
            cloudwatch.GraphWidget(
                title="API Request Count",
                left=[api_request_count],
                width=8,
                height=6,
            ),
            cloudwatch.GraphWidget(
                title="API Latency (ms)",
                left=[api_latency],
                width=8,
                height=6,
            ),
            cloudwatch.GraphWidget(
                title="API Errors",
                left=[api_4xx_errors, api_5xx_errors],
                width=8,
                height=6,
            ),
        )

        # =====================================================
        # Lambda Metrics
        # =====================================================
        lambda_invocations = []
        lambda_errors = []
        lambda_durations = []

        for fn_name in lambda_names:
            lambda_invocations.append(
                cloudwatch.Metric(
                    namespace="AWS/Lambda",
                    metric_name="Invocations",
                    dimensions_map={"FunctionName": fn_name},
                    statistic="Sum",
                    period=Duration.minutes(5),
                )
            )
            lambda_errors.append(
                cloudwatch.Metric(
                    namespace="AWS/Lambda",
                    metric_name="Errors",
                    dimensions_map={"FunctionName": fn_name},
                    statistic="Sum",
                    period=Duration.minutes(5),
                )
            )
            lambda_durations.append(
                cloudwatch.Metric(
                    namespace="AWS/Lambda",
                    metric_name="Duration",
                    dimensions_map={"FunctionName": fn_name},
                    statistic="Average",
                    period=Duration.minutes(5),
                )
            )

        # Lambda widgets
        self.dashboard.add_widgets(
            cloudwatch.TextWidget(
                markdown="## Lambda Functions",
                width=24,
                height=1,
            ),
            cloudwatch.GraphWidget(
                title="Lambda Invocations",
                left=lambda_invocations,
                width=8,
                height=6,
            ),
            cloudwatch.GraphWidget(
                title="Lambda Errors",
                left=lambda_errors,
                width=8,
                height=6,
            ),
            cloudwatch.GraphWidget(
                title="Lambda Duration (ms)",
                left=lambda_durations,
                width=8,
                height=6,
            ),
        )

        # =====================================================
        # RDS Metrics (if DB instance provided)
        # =====================================================
        if db_instance_id:
            db_cpu = cloudwatch.Metric(
                namespace="AWS/RDS",
                metric_name="CPUUtilization",
                dimensions_map={"DBInstanceIdentifier": db_instance_id},
                statistic="Average",
                period=Duration.minutes(5),
            )

            db_connections = cloudwatch.Metric(
                namespace="AWS/RDS",
                metric_name="DatabaseConnections",
                dimensions_map={"DBInstanceIdentifier": db_instance_id},
                statistic="Average",
                period=Duration.minutes(5),
            )

            db_read_iops = cloudwatch.Metric(
                namespace="AWS/RDS",
                metric_name="ReadIOPS",
                dimensions_map={"DBInstanceIdentifier": db_instance_id},
                statistic="Average",
                period=Duration.minutes(5),
            )

            db_write_iops = cloudwatch.Metric(
                namespace="AWS/RDS",
                metric_name="WriteIOPS",
                dimensions_map={"DBInstanceIdentifier": db_instance_id},
                statistic="Average",
                period=Duration.minutes(5),
            )

            db_free_storage = cloudwatch.Metric(
                namespace="AWS/RDS",
                metric_name="FreeStorageSpace",
                dimensions_map={"DBInstanceIdentifier": db_instance_id},
                statistic="Average",
                period=Duration.minutes(5),
            )

            # RDS widgets
            self.dashboard.add_widgets(
                cloudwatch.TextWidget(
                    markdown="## Database (RDS)",
                    width=24,
                    height=1,
                ),
                cloudwatch.GraphWidget(
                    title="Database CPU Utilization",
                    left=[db_cpu],
                    width=8,
                    height=6,
                ),
                cloudwatch.GraphWidget(
                    title="Database Connections",
                    left=[db_connections],
                    width=8,
                    height=6,
                ),
                cloudwatch.GraphWidget(
                    title="Database IOPS",
                    left=[db_read_iops, db_write_iops],
                    width=8,
                    height=6,
                ),
            )

            # CPU Alarm
            cpu_alarm = cloudwatch.Alarm(
                self,
                "DbCpuAlarm",
                alarm_name="SecondBrain-DB-HighCPU",
                metric=db_cpu,
                threshold=80,
                evaluation_periods=3,
                comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
                alarm_description="Database CPU utilization is above 80%",
            )
            cpu_alarm.add_alarm_action(cw_actions.SnsAction(self.alarm_topic))

            # Storage Alarm
            storage_alarm = cloudwatch.Alarm(
                self,
                "DbStorageAlarm",
                alarm_name="SecondBrain-DB-LowStorage",
                metric=db_free_storage,
                threshold=5 * 1024 * 1024 * 1024,  # 5 GB in bytes
                evaluation_periods=1,
                comparison_operator=cloudwatch.ComparisonOperator.LESS_THAN_THRESHOLD,
                alarm_description="Database free storage is below 5GB",
            )
            storage_alarm.add_alarm_action(cw_actions.SnsAction(self.alarm_topic))

        # =====================================================
        # Alarms
        # =====================================================

        # API Error Rate Alarm
        error_rate_alarm = cloudwatch.Alarm(
            self,
            "ApiErrorRateAlarm",
            alarm_name="SecondBrain-API-HighErrorRate",
            metric=api_5xx_errors,
            threshold=10,
            evaluation_periods=2,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            alarm_description="API is returning more than 10 5XX errors in 10 minutes",
        )
        error_rate_alarm.add_alarm_action(cw_actions.SnsAction(self.alarm_topic))

        # API Latency Alarm
        latency_alarm = cloudwatch.Alarm(
            self,
            "ApiLatencyAlarm",
            alarm_name="SecondBrain-API-HighLatency",
            metric=api_latency,
            threshold=5000,  # 5 seconds
            evaluation_periods=3,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            alarm_description="API latency is above 5 seconds",
        )
        latency_alarm.add_alarm_action(cw_actions.SnsAction(self.alarm_topic))

        # Lambda Error Alarm (aggregate across all functions)
        for fn_name in lambda_names:
            fn_error_metric = cloudwatch.Metric(
                namespace="AWS/Lambda",
                metric_name="Errors",
                dimensions_map={"FunctionName": fn_name},
                statistic="Sum",
                period=Duration.minutes(5),
            )
            fn_alarm = cloudwatch.Alarm(
                self,
                f"{fn_name.replace('-', '')}ErrorAlarm",
                alarm_name=f"SecondBrain-Lambda-{fn_name}-Errors",
                metric=fn_error_metric,
                threshold=5,
                evaluation_periods=2,
                comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
                alarm_description=f"Lambda {fn_name} is experiencing errors",
            )
            fn_alarm.add_alarm_action(cw_actions.SnsAction(self.alarm_topic))

        # =====================================================
        # Custom Metrics Widget for Business KPIs
        # =====================================================
        self.dashboard.add_widgets(
            cloudwatch.TextWidget(
                markdown="## Business Metrics\n*Custom metrics from application logs*",
                width=24,
                height=1,
            ),
            cloudwatch.SingleValueWidget(
                title="Total API Calls (24h)",
                metrics=[
                    cloudwatch.Metric(
                        namespace="AWS/ApiGateway",
                        metric_name="Count",
                        dimensions_map={"ApiName": api_name},
                        statistic="Sum",
                        period=Duration.hours(24),
                    )
                ],
                width=6,
                height=4,
            ),
            cloudwatch.SingleValueWidget(
                title="Avg Latency (24h)",
                metrics=[
                    cloudwatch.Metric(
                        namespace="AWS/ApiGateway",
                        metric_name="Latency",
                        dimensions_map={"ApiName": api_name},
                        statistic="Average",
                        period=Duration.hours(24),
                    )
                ],
                width=6,
                height=4,
            ),
            cloudwatch.SingleValueWidget(
                title="Total Errors (24h)",
                metrics=[
                    cloudwatch.Metric(
                        namespace="AWS/ApiGateway",
                        metric_name="5XXError",
                        dimensions_map={"ApiName": api_name},
                        statistic="Sum",
                        period=Duration.hours(24),
                    )
                ],
                width=6,
                height=4,
            ),
            cloudwatch.SingleValueWidget(
                title="Error Rate (24h)",
                metrics=[
                    cloudwatch.MathExpression(
                        expression="errors / requests * 100",
                        using_metrics={
                            "errors": cloudwatch.Metric(
                                namespace="AWS/ApiGateway",
                                metric_name="5XXError",
                                dimensions_map={"ApiName": api_name},
                                statistic="Sum",
                                period=Duration.hours(24),
                            ),
                            "requests": cloudwatch.Metric(
                                namespace="AWS/ApiGateway",
                                metric_name="Count",
                                dimensions_map={"ApiName": api_name},
                                statistic="Sum",
                                period=Duration.hours(24),
                            ),
                        },
                        label="Error %",
                    )
                ],
                width=6,
                height=4,
            ),
        )

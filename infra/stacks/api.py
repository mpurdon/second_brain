"""API Gateway Stack for Second Brain REST API."""

import os
from aws_cdk import (
    Duration,
    Stack,
    aws_apigateway as apigw,
    aws_cognito as cognito,
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_logs as logs,
)
from constructs import Construct


def _get_lambda_asset_path(binary_name: str) -> str:
    """Get the path to a Rust Lambda asset.

    Creates a placeholder if the built binary doesn't exist.
    """
    # Get the project root (three levels up from infra/stacks)
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


class ApiStack(Stack):
    """Stack containing REST API Gateway and Lambda integrations."""

    def __init__(
        self,
        scope: Construct,
        id: str,
        vpc: ec2.IVpc,
        security_group: ec2.ISecurityGroup,
        user_pool: cognito.IUserPool,
        agent_function_arn: str,
        db_secret_arn: str,
        db_host: str,
        **kwargs,
    ) -> None:
        """Initialize the API Stack.

        Args:
            scope: CDK scope.
            id: Stack ID.
            vpc: VPC for Lambda functions.
            security_group: Security group for Lambda functions.
            user_pool: Cognito User Pool for authentication.
            agent_function_arn: ARN of the agent Lambda function.
            db_secret_arn: ARN of the database credentials secret.
            db_host: Database host address.
            **kwargs: Additional stack properties.
        """
        super().__init__(scope, id, **kwargs)

        # Common Lambda configuration
        common_env = {
            "AGENT_FUNCTION_NAME": agent_function_arn,
            "LOG_LEVEL": "INFO",
        }

        # Environment for Lambdas that need database access
        db_env = {
            "DB_SECRET_ARN": db_secret_arn,
            "DB_HOST": db_host,
            "DB_NAME": "second_brain",
            "LOG_LEVEL": "INFO",
        }

        # Helper to create Rust Lambda functions
        def create_rust_lambda(
            construct_id: str,
            binary_name: str,
            description: str,
            timeout_seconds: int = 30,
            memory_mb: int = 256,
            env: dict | None = None,
            needs_agent_invoke: bool = True,
            needs_secrets: bool = False,
        ) -> lambda_.Function:
            log_group = logs.LogGroup(
                self,
                f"{construct_id}Logs",
                log_group_name=f"/aws/lambda/second-brain-{binary_name}",
                retention=logs.RetentionDays.TWO_WEEKS,
            )

            fn = lambda_.Function(
                self,
                construct_id,
                function_name=f"second-brain-{binary_name}",
                runtime=lambda_.Runtime.PROVIDED_AL2023,
                handler="bootstrap",
                code=lambda_.Code.from_asset(_get_lambda_asset_path(binary_name)),
                vpc=vpc,
                vpc_subnets=ec2.SubnetSelection(
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
                ),
                security_groups=[security_group],
                environment=env or common_env,
                timeout=Duration.seconds(timeout_seconds),
                memory_size=memory_mb,
                architecture=lambda_.Architecture.ARM_64,
                log_group=log_group,
                tracing=lambda_.Tracing.ACTIVE,
            )

            # Grant invoke permission on agent function
            if needs_agent_invoke:
                fn.add_to_role_policy(
                    iam.PolicyStatement(
                        actions=["lambda:InvokeFunction"],
                        resources=[agent_function_arn],
                    )
                )

            # Grant secrets manager access
            if needs_secrets:
                fn.add_to_role_policy(
                    iam.PolicyStatement(
                        actions=["secretsmanager:GetSecretValue"],
                        resources=[db_secret_arn],
                    )
                )

            return fn

        # Create Lambda functions
        query_lambda = create_rust_lambda(
            "QueryLambda",
            "query",
            "Handles /query requests",
        )

        ingest_lambda = create_rust_lambda(
            "IngestLambda",
            "ingest",
            "Handles /ingest requests",
        )

        briefing_lambda = create_rust_lambda(
            "BriefingLambda",
            "briefing",
            "Handles /briefing requests",
            timeout_seconds=60,
        )

        calendar_lambda = create_rust_lambda(
            "CalendarLambda",
            "calendar",
            "Handles /calendar requests",
        )

        # Families Lambda (database access)
        families_lambda = create_rust_lambda(
            "FamiliesLambda",
            "families",
            "Handles /families requests",
            env=db_env,
            needs_agent_invoke=False,
            needs_secrets=True,
        )

        # Relationships Lambda (database access)
        relationships_lambda = create_rust_lambda(
            "RelationshipsLambda",
            "relationships",
            "Handles /relationships requests",
            env=db_env,
            needs_agent_invoke=False,
            needs_secrets=True,
        )

        # Entities Lambda (database access)
        entities_lambda = create_rust_lambda(
            "EntitiesLambda",
            "entities",
            "Handles /entities requests",
            env=db_env,
            needs_agent_invoke=False,
            needs_secrets=True,
        )

        # Locations Lambda (database access with PostGIS)
        locations_lambda = create_rust_lambda(
            "LocationsLambda",
            "locations",
            "Handles /locations and temporal queries",
            env=db_env,
            needs_agent_invoke=False,
            needs_secrets=True,
        )

        # Tags Lambda (database access)
        tags_lambda = create_rust_lambda(
            "TagsLambda",
            "tags",
            "Handles /tags and fact tagging",
            env=db_env,
            needs_agent_invoke=False,
            needs_secrets=True,
        )

        # Feedback Lambda (database access)
        feedback_lambda = create_rust_lambda(
            "FeedbackLambda",
            "feedback",
            "Handles /feedback user learning loop",
            env=db_env,
            needs_agent_invoke=False,
            needs_secrets=True,
        )

        # Reminders Lambda (database access)
        reminders_lambda = create_rust_lambda(
            "RemindersLambda",
            "reminders",
            "Handles /reminders CRUD operations",
            env=db_env,
            needs_agent_invoke=False,
            needs_secrets=True,
        )

        # REST API Gateway
        self.api = apigw.RestApi(
            self,
            "SecondBrainApi",
            rest_api_name="second-brain-api",
            description="Second Brain REST API",
            deploy_options=apigw.StageOptions(
                stage_name="api",
                logging_level=apigw.MethodLoggingLevel.INFO,
                data_trace_enabled=True,
                metrics_enabled=True,
                throttling_rate_limit=100,
                throttling_burst_limit=200,
            ),
            default_cors_preflight_options=apigw.CorsOptions(
                allow_origins=apigw.Cors.ALL_ORIGINS,
                allow_methods=apigw.Cors.ALL_METHODS,
                allow_headers=[
                    "Content-Type",
                    "Authorization",
                    "X-Amz-Date",
                    "X-Api-Key",
                    "X-Amz-Security-Token",
                ],
            ),
        )

        # Cognito Authorizer
        authorizer = apigw.CognitoUserPoolsAuthorizer(
            self,
            "CognitoAuthorizer",
            cognito_user_pools=[user_pool],
            authorizer_name="cognito-authorizer",
        )

        # API Resources
        root = self.api.root

        # /query endpoint
        query_resource = root.add_resource("query")
        query_resource.add_method(
            "POST",
            apigw.LambdaIntegration(query_lambda),
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # /ingest endpoint
        ingest_resource = root.add_resource("ingest")
        ingest_resource.add_method(
            "POST",
            apigw.LambdaIntegration(ingest_lambda),
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # /briefing endpoint
        briefing_resource = root.add_resource("briefing")
        briefing_resource.add_method(
            "GET",
            apigw.LambdaIntegration(briefing_lambda),
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # /calendar endpoint
        calendar_resource = root.add_resource("calendar")
        calendar_resource.add_method(
            "GET",
            apigw.LambdaIntegration(calendar_lambda),
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # /families endpoints
        families_resource = root.add_resource("families")
        families_integration = apigw.LambdaIntegration(families_lambda)

        # POST /families - Create family
        families_resource.add_method(
            "POST",
            families_integration,
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # GET /families - List user's families
        families_resource.add_method(
            "GET",
            families_integration,
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # /families/{familyId}
        family_resource = families_resource.add_resource("{familyId}")

        # GET /families/{familyId} - Get family details
        family_resource.add_method(
            "GET",
            families_integration,
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # /families/{familyId}/members
        family_members_resource = family_resource.add_resource("members")

        # POST /families/{familyId}/members - Add member
        family_members_resource.add_method(
            "POST",
            families_integration,
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # /families/{familyId}/members/{userId}
        family_member_resource = family_members_resource.add_resource("{userId}")

        # DELETE /families/{familyId}/members/{userId} - Remove member
        family_member_resource.add_method(
            "DELETE",
            families_integration,
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # /relationships endpoints
        relationships_resource = root.add_resource("relationships")
        relationships_integration = apigw.LambdaIntegration(relationships_lambda)

        # POST /relationships - Create relationship
        relationships_resource.add_method(
            "POST",
            relationships_integration,
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # GET /relationships - List relationships
        relationships_resource.add_method(
            "GET",
            relationships_integration,
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # /relationships/{relationshipId}
        relationship_resource = relationships_resource.add_resource("{relationshipId}")

        # PUT /relationships/{relationshipId} - Update access tier
        relationship_resource.add_method(
            "PUT",
            relationships_integration,
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # DELETE /relationships/{relationshipId} - Remove relationship
        relationship_resource.add_method(
            "DELETE",
            relationships_integration,
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # /entities endpoints
        entities_resource = root.add_resource("entities")
        entities_integration = apigw.LambdaIntegration(entities_lambda)

        # POST /entities - Create entity
        entities_resource.add_method(
            "POST",
            entities_integration,
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # GET /entities - Search/list entities
        entities_resource.add_method(
            "GET",
            entities_integration,
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # /entities/{entityId}
        entity_resource = entities_resource.add_resource("{entityId}")

        # GET /entities/{entityId} - Get entity details
        entity_resource.add_method(
            "GET",
            entities_integration,
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # PUT /entities/{entityId} - Update entity
        entity_resource.add_method(
            "PUT",
            entities_integration,
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # DELETE /entities/{entityId} - Delete entity
        entity_resource.add_method(
            "DELETE",
            entities_integration,
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # /entities/{entityId}/facts - Entity timeline
        entity_facts_resource = entity_resource.add_resource("facts")
        entity_facts_resource.add_method(
            "GET",
            entities_integration,
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # /entities/{entityId}/relationships - Entity relationships
        entity_relationships_resource = entity_resource.add_resource("relationships")

        # GET /entities/{entityId}/relationships - List entity relationships
        entity_relationships_resource.add_method(
            "GET",
            entities_integration,
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # POST /entities/{entityId}/relationships - Create entity relationship
        entity_relationships_resource.add_method(
            "POST",
            entities_integration,
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # Entity locations (handled by locations lambda)
        entity_locations_resource = entity_resource.add_resource("locations")
        locations_integration = apigw.LambdaIntegration(locations_lambda)

        # GET /entities/{entityId}/locations - Get entity locations
        entity_locations_resource.add_method(
            "GET",
            locations_integration,
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # POST /entities/{entityId}/locations - Add location to entity
        entity_locations_resource.add_method(
            "POST",
            locations_integration,
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # /locations endpoints
        locations_resource = root.add_resource("locations")

        # GET /locations/nearby - Proximity search
        locations_nearby_resource = locations_resource.add_resource("nearby")
        locations_nearby_resource.add_method(
            "GET",
            locations_integration,
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # GET /locations/distance - Calculate distance
        locations_distance_resource = locations_resource.add_resource("distance")
        locations_distance_resource.add_method(
            "GET",
            locations_integration,
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # /facts/timeline - Temporal query endpoint
        facts_resource = root.add_resource("facts")
        facts_timeline_resource = facts_resource.add_resource("timeline")
        facts_timeline_resource.add_method(
            "GET",
            locations_integration,
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # /tags endpoints
        tags_resource = root.add_resource("tags")
        tags_integration = apigw.LambdaIntegration(tags_lambda)

        # POST /tags - Create tag
        tags_resource.add_method(
            "POST",
            tags_integration,
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # GET /tags - List/search tags (autocomplete)
        tags_resource.add_method(
            "GET",
            tags_integration,
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # GET /tags/stats - Tag statistics
        tags_stats_resource = tags_resource.add_resource("stats")
        tags_stats_resource.add_method(
            "GET",
            tags_integration,
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # POST /tags/suggestions - Get AI tag suggestions
        tags_suggestions_resource = tags_resource.add_resource("suggestions")
        tags_suggestions_resource.add_method(
            "POST",
            tags_integration,
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # /tags/{tagId}
        tag_resource = tags_resource.add_resource("{tagId}")

        # PUT /tags/{tagId} - Update tag
        tag_resource.add_method(
            "PUT",
            tags_integration,
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # DELETE /tags/{tagId} - Delete tag
        tag_resource.add_method(
            "DELETE",
            tags_integration,
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # GET /tags/{tagId}/facts - Facts with this tag
        tag_facts_resource = tag_resource.add_resource("facts")
        tag_facts_resource.add_method(
            "GET",
            tags_integration,
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # /facts/{factId}/tags - Fact tagging
        fact_resource = facts_resource.add_resource("{factId}")
        fact_tags_resource = fact_resource.add_resource("tags")

        # POST /facts/{factId}/tags - Apply tags to fact
        fact_tags_resource.add_method(
            "POST",
            tags_integration,
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # /facts/{factId}/tags/{tagId}
        fact_tag_resource = fact_tags_resource.add_resource("{tagId}")

        # DELETE /facts/{factId}/tags/{tagId} - Remove tag from fact
        fact_tag_resource.add_method(
            "DELETE",
            tags_integration,
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # /feedback endpoints
        feedback_resource = root.add_resource("feedback")
        feedback_integration = apigw.LambdaIntegration(feedback_lambda)

        # POST /feedback - Record feedback
        feedback_resource.add_method(
            "POST",
            feedback_integration,
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # GET /feedback/stats - Get user's feedback stats
        feedback_stats_resource = feedback_resource.add_resource("stats")
        feedback_stats_resource.add_method(
            "GET",
            feedback_integration,
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # GET /feedback/history - Get recent feedback
        feedback_history_resource = feedback_resource.add_resource("history")
        feedback_history_resource.add_method(
            "GET",
            feedback_integration,
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # /queries/{queryId}/feedback - Rate a query
        queries_resource = root.add_resource("queries")
        query_resource = queries_resource.add_resource("{queryId}")
        query_feedback_resource = query_resource.add_resource("feedback")
        query_feedback_resource.add_method(
            "POST",
            feedback_integration,
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # /reminders endpoints
        reminders_resource = root.add_resource("reminders")
        reminders_integration = apigw.LambdaIntegration(reminders_lambda)

        # POST /reminders - Create reminder
        reminders_resource.add_method(
            "POST",
            reminders_integration,
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # GET /reminders - List reminders
        reminders_resource.add_method(
            "GET",
            reminders_integration,
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # /reminders/{reminderId}
        reminder_resource = reminders_resource.add_resource("{reminderId}")

        # GET /reminders/{reminderId} - Get reminder
        reminder_resource.add_method(
            "GET",
            reminders_integration,
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # PUT /reminders/{reminderId} - Update reminder
        reminder_resource.add_method(
            "PUT",
            reminders_integration,
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # DELETE /reminders/{reminderId} - Delete/cancel reminder
        reminder_resource.add_method(
            "DELETE",
            reminders_integration,
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # POST /reminders/{reminderId}/snooze - Snooze reminder
        reminder_snooze_resource = reminder_resource.add_resource("snooze")
        reminder_snooze_resource.add_method(
            "POST",
            reminders_integration,
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # Export API URL
        self.api_url = self.api.url

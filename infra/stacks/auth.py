"""Auth Stack - Cognito User Pool for authentication."""

from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    CfnOutput,
    aws_cognito as cognito,
)
from constructs import Construct


class AuthStack(Stack):
    """Cognito User Pool for authentication."""

    def __init__(self, scope: Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        # User Pool
        self.user_pool = cognito.UserPool(
            self,
            "UserPool",
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

        # App Client for Web (no secret - public client)
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
                cognito.UserPoolClientIdentityProvider.COGNITO,
            ],
        )

        # App Client for Discord Bot (with secret)
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
        CfnOutput(
            self,
            "UserPoolId",
            value=self.user_pool.user_pool_id,
            export_name="SecondBrainUserPoolId",
        )
        CfnOutput(
            self,
            "UserPoolArn",
            value=self.user_pool.user_pool_arn,
            export_name="SecondBrainUserPoolArn",
        )
        CfnOutput(
            self,
            "WebClientId",
            value=self.web_client.user_pool_client_id,
            export_name="SecondBrainWebClientId",
        )
        CfnOutput(
            self,
            "CognitoDomain",
            value=f"{self.domain.domain_name}.auth.{self.region}.amazoncognito.com",
            export_name="SecondBrainCognitoDomain",
        )

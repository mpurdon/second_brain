"""Network Stack - VPC and networking infrastructure."""

from aws_cdk import (
    Stack,
    CfnOutput,
    aws_ec2 as ec2,
)
from constructs import Construct


class NetworkStack(Stack):
    """VPC and networking infrastructure for Second Brain."""

    def __init__(self, scope: Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        # VPC with public and private subnets
        self.vpc = ec2.Vpc(
            self,
            "SecondBrainVpc",
            vpc_name="second-brain-vpc",
            max_azs=2,  # Cost optimization: 2 AZs sufficient
            nat_gateways=1,  # Cost optimization: single NAT
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="Private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="Isolated",
                    subnet_type=ec2.SubnetType.PRIVATE_ISOLATED,
                    cidr_mask=24,
                ),
            ],
        )

        # Security group for Lambda functions
        self.lambda_security_group = ec2.SecurityGroup(
            self,
            "LambdaSG",
            vpc=self.vpc,
            description="Security group for Lambda functions",
            allow_all_outbound=True,
        )

        # Security group for RDS
        self.rds_security_group = ec2.SecurityGroup(
            self,
            "RdsSG",
            vpc=self.vpc,
            description="Security group for RDS PostgreSQL",
            allow_all_outbound=False,
        )

        # Allow Lambda -> RDS
        self.rds_security_group.add_ingress_rule(
            peer=self.lambda_security_group,
            connection=ec2.Port.tcp(5432),
            description="Allow Lambda to RDS",
        )

        # VPC Endpoints for AWS services (cost optimization - avoid NAT charges)
        self.vpc.add_gateway_endpoint(
            "S3Endpoint",
            service=ec2.GatewayVpcEndpointAwsService.S3,
        )

        self.vpc.add_interface_endpoint(
            "SecretsManagerEndpoint",
            service=ec2.InterfaceVpcEndpointAwsService.SECRETS_MANAGER,
            security_groups=[self.lambda_security_group],
        )

        # Bedrock endpoint
        self.vpc.add_interface_endpoint(
            "BedrockEndpoint",
            service=ec2.InterfaceVpcEndpointAwsService.BEDROCK_RUNTIME,
            security_groups=[self.lambda_security_group],
        )

        # Outputs
        CfnOutput(self, "VpcId", value=self.vpc.vpc_id, export_name="SecondBrainVpcId")
        CfnOutput(
            self,
            "LambdaSecurityGroupId",
            value=self.lambda_security_group.security_group_id,
            export_name="SecondBrainLambdaSGId",
        )
        CfnOutput(
            self,
            "RdsSecurityGroupId",
            value=self.rds_security_group.security_group_id,
            export_name="SecondBrainRdsSGId",
        )

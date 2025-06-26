import json

import aws_cdk as cdk

from aws_cdk import (
  Stack,
  aws_ec2,
  aws_logs,
  aws_rds,
  aws_secretsmanager
)
from constructs import Construct


class AuroraPostgresStack(Stack):

  def __init__(self, scope: Construct, id: str, vpc, **kwargs) -> None:
    super().__init__(scope, id, **kwargs)

    self.sg_postgres_client = aws_ec2.SecurityGroup(self, 'PostgresClientSG',
      vpc=vpc,
      allow_all_outbound=True,
      description='security group for postgres client',
      security_group_name='default-postgres-client-sg'
    )
    cdk.Tags.of(self.sg_postgres_client).add('Name', 'default-postgres-client-sg')

    sg_postgres_server = aws_ec2.SecurityGroup(self, 'PostgresServerSG',
      vpc=vpc,
      allow_all_outbound=True,
      description='security group for postgres',
      security_group_name='default-postgres-server-sg'
    )
    sg_postgres_server.add_ingress_rule(peer=self.sg_postgres_client, connection=aws_ec2.Port.tcp(5432),
      description='default-postgres-client-sg')
    sg_postgres_server.add_ingress_rule(peer=sg_postgres_server, connection=aws_ec2.Port.all_tcp(),
      description='default-postgres-server-sg')
    cdk.Tags.of(sg_postgres_server).add('Name', 'default-postgres-server-sg')

    rds_subnet_group = aws_rds.SubnetGroup(self, 'PostgresSubnetGroup',
      description='subnet group for postgres',
      subnet_group_name='aurora-postgres',
      vpc_subnets=aws_ec2.SubnetSelection(subnet_type=aws_ec2.SubnetType.PRIVATE_WITH_EGRESS),
      vpc=vpc
    )

    rds_engine = aws_rds.DatabaseClusterEngine.aurora_postgres(version=aws_rds.AuroraPostgresEngineVersion.VER_13_9)
    # Parameter group for Aurora PostgreSQL
    rds_cluster_param_group = aws_rds.ParameterGroup(self, 'AuroraPostgresClusterParamGroup',
      description='Custom cluster parameter group for aurora-postgres',
      engine=rds_engine,
      parameters={
        'log_statement': 'all'
      }
    )
   
    rds_db_param_group = aws_rds.ParameterGroup(self, 'AuroraPostgresDBParamGroup',
      description='Custom parameter group for aurora-postgres',
      engine=rds_engine,
      parameters={
        'log_statement':'all',
        'work_mem': '65536'
      }
    )

    db_cluster_name = self.node.try_get_context('db_cluster_name')

    # Use aws_secretsmanager.Secret to generate a password without punctuation
    db_secret = aws_secretsmanager.Secret(self, 'DatabaseSecret',
      generate_secret_string=aws_secretsmanager.SecretStringGenerator(
        secret_string_template=json.dumps({"username": "postgres"}),
        generate_string_key="password",
        exclude_punctuation=True,
        password_length=8
      )
    )
    rds_credentials = aws_rds.Credentials.from_secret(db_secret)

    db_cluster = aws_rds.DatabaseCluster(self, 'Database',
      engine=rds_engine,
      credentials=rds_credentials, # A username of 'admin' and SecretsManager-generated password
      writer=aws_rds.ClusterInstance.provisioned("writer",
        instance_type=aws_ec2.InstanceType.of(aws_ec2.InstanceClass.BURSTABLE3, aws_ec2.InstanceSize.MEDIUM),
        parameter_group=rds_db_param_group,
        auto_minor_version_upgrade=False,
      ),
      readers=[
        aws_rds.ClusterInstance.provisioned("reader",
          instance_type=aws_ec2.InstanceType.of(aws_ec2.InstanceClass.BURSTABLE3, aws_ec2.InstanceSize.MEDIUM),
          parameter_group=rds_db_param_group,
          auto_minor_version_upgrade=False
        )
      ],
      parameter_group=rds_cluster_param_group,
      cloudwatch_logs_retention=aws_logs.RetentionDays.THREE_DAYS,
      cluster_identifier=db_cluster_name,
      subnet_group=rds_subnet_group,
      backup=aws_rds.BackupProps(
        retention=cdk.Duration.days(3),
        preferred_window="03:00-04:00"
      ),
      security_groups=[sg_postgres_server],
      vpc=vpc,
      vpc_subnets=aws_ec2.SubnetSelection(subnet_type=aws_ec2.SubnetType.PRIVATE_WITH_EGRESS)
    )

    self.db_hostname = db_cluster.cluster_endpoint.hostname
    self.db_secret = db_cluster.secret

    cdk.CfnOutput(self, 'DBClusterEndpointHostName',
      value=self.db_hostname,
      export_name='DBClusterEndpointHostName')
    cdk.CfnOutput(self, 'DBClusterEndpoint',
      value=db_cluster.cluster_endpoint.socket_address,
      export_name='DBClusterEndpoint')
    cdk.CfnOutput(self, 'DBClusterReadEndpoint',
      value=db_cluster.cluster_read_endpoint.socket_address,
      export_name='DBClusterReadEndpoint')
    cdk.CfnOutput(self, 'DBSecretName',
      value=db_cluster.secret.secret_name,
      export_name='DBSecretName')


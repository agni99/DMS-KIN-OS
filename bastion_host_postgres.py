import os

import aws_cdk as cdk

from aws_cdk import (
  Stack,
  aws_ec2,
  aws_iam,
  aws_s3_assets
)
from constructs import Construct


class BastionHostEC2InstanceStackPostgres(Stack):

  def __init__(self, scope: Construct, construct_id: str, vpc, sg_rds_client, **kwargs) -> None:
    super().__init__(scope, construct_id, **kwargs)

    ec2_key_pair_name = self.node.try_get_context('ec2_key_pair_name')
    ec2_key_pair = aws_ec2.KeyPair.from_key_pair_attributes(self, 'EC2KeyPair',
      key_pair_name=ec2_key_pair_name
    )

    sg_bastion_host = aws_ec2.SecurityGroup(self, 'BastionHostSG',
      vpc=vpc,
      allow_all_outbound=True,
      description='security group for a bastion host',
      security_group_name='bastion-host-sg'
    )
    cdk.Tags.of(sg_bastion_host).add('Name', 'bastion-host-sg')

    # TODO: SHOULD restrict IP range allowed to SSH access
    sg_bastion_host.add_ingress_rule(peer=aws_ec2.Peer.ipv4("0.0.0.0/0"),
      connection=aws_ec2.Port.tcp(22), description='SSH access')

    bastion_host_role = aws_iam.Role(self, 'PostgresClientEC2InstanceRole',
      role_name=f'PostgresClientEC2InstanceRole-{self.stack_name}',
      assumed_by=aws_iam.ServicePrincipal('ec2.amazonaws.com'),
      managed_policies=[
        aws_iam.ManagedPolicy.from_aws_managed_policy_name('AmazonSSMManagedInstanceCore'),
        # EC2 instance should be able to access S3 for user data
        # aws_iam.ManagedPolicy.from_aws_managed_policy_name('AmazonS3ReadOnlyAccess')
      ]
    )

    # Instance type
    ec2_instance_type = aws_ec2.InstanceType.of(aws_ec2.InstanceClass.BURSTABLE3, aws_ec2.InstanceSize.MEDIUM)

    bastion_host = aws_ec2.Instance(self, 'BastionHostEC2Instance',
      instance_type=ec2_instance_type,
      machine_image=aws_ec2.MachineImage.latest_amazon_linux2(),
      instance_name=f'{self.stack_name}/BastionHost',
      role=bastion_host_role,
      security_group=sg_bastion_host,
      key_pair=ec2_key_pair,
      vpc=vpc,
      vpc_subnets=aws_ec2.SubnetSelection(subnet_type=aws_ec2.SubnetType.PUBLIC),
    )
    bastion_host.add_security_group(sg_rds_client)

    # Test data generator script in S3 as Asset
    user_data_asset = aws_s3_assets.Asset(self, 'BastionHostUserData',
      path=os.path.join(os.path.dirname(__file__), '../utils/gen_fake_postgres_data.py'))
    user_data_asset.grant_read(bastion_host.role)

    USER_DATA_LOCAL_PATH = bastion_host.user_data.add_s3_download_command(
      bucket=user_data_asset.bucket,
      bucket_key=user_data_asset.s3_object_key
    )

    # User data commands for PostgreSQL setup
    commands = '''
yum update -y
yum install -y python3.7
yum install -y jq
yum install -y postgresql postgresql-contrib

cd /home/ec2-user
wget https://bootstrap.pypa.io/get-pip.py
su -c "python3.7 get-pip.py --user" -s /bin/sh ec2-user
su -c "/home/ec2-user/.local/bin/pip3 install boto3 --user" -s /bin/sh ec2-user
'''

    commands += f'''
su -c "/home/ec2-user/.local/bin/pip3 install dataset==1.5.2 Faker==13.3.1 psycopg2==2.9.6 --user" -s /bin/sh ec2-user
cp {USER_DATA_LOCAL_PATH} /home/ec2-user/gen_fake_postgres_data.py && chown -R ec2-user /home/ec2-user/gen_fake_postgres_data.py
'''

    bastion_host.user_data.add_commands(commands)

    self.sg_bastion_host = sg_bastion_host

    cdk.CfnOutput(self, f'{self.stack_name}-EC2InstancePublicDNS',
      value=bastion_host.instance_public_dns_name,
      export_name=f'{self.stack_name}-EC2InstancePublicDNS')
    cdk.CfnOutput(self, f'{self.stack_name}-EC2InstanceId',
      value=bastion_host.instance_id,
      export_name=f'{self.stack_name}-EC2InstanceId')
    cdk.CfnOutput(self, f'{self.stack_name}-EC2InstanceAZ',
      value=bastion_host.instance_availability_zone,
      export_name=f'{self.stack_name}-EC2InstanceAZ')


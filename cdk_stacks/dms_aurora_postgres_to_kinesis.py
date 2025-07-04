#!/usr/bin/env python3
# -*- encoding: utf-8 -*-
# vim: tabstop=2 shiftwidth=2 softtabstop=2 expandtab

import json

import aws_cdk as cdk

from aws_cdk import (
  Stack,
  aws_dms,
  aws_ec2,
  aws_iam
)
from constructs import Construct

class DMSAuroraPostgresToKinesisStack(Stack):  # Updated class name for clarity

  def __init__(self, scope: Construct, construct_id: str,
              vpc, db_client_sg, db_secret, source_database_hostname, target_kinesis_stream_arn,
              **kwargs) -> None:

    super().__init__(scope, construct_id, **kwargs)

    db_cluster_name = "database-1"
    dms_data_source = self.node.try_get_context('dms_data_source')
    database_name = "testdb"
    table_name = "retail_trans"

    dms_replication_subnet_group = aws_dms.CfnReplicationSubnetGroup(self, 'DMSReplicationSubnetGroup',
      replication_subnet_group_description='DMS Replication Subnet Group',
      subnet_ids=vpc.select_subnets(subnet_type=aws_ec2.SubnetType.PRIVATE_WITH_EGRESS).subnet_ids
    )

    dms_replication_instance = aws_dms.CfnReplicationInstance(self, 'DMSReplicationInstance',
      replication_instance_class='dms.t3.medium',
      # the properties below are optional
      allocated_storage=50,
      allow_major_version_upgrade=False,
      auto_minor_version_upgrade=False,
      engine_version='3.5.3',
      multi_az=False,
      preferred_maintenance_window='sat:03:17-sat:03:47',
      publicly_accessible=False,
      replication_subnet_group_identifier=dms_replication_subnet_group.ref,
      vpc_security_group_ids=[db_client_sg.security_group_id]
    )

    source_endpoint_id = db_cluster_name
    dms_source_endpoint = aws_dms.CfnEndpoint(self, 'DMSSourceEndpoint',
      endpoint_identifier=source_endpoint_id,
      endpoint_type='source',
      engine_name='postgres',  # Changed from 'mysql' to 'postgres'
      server_name=source_database_hostname,
      port=5432,  # Changed from MySQL's 3306 to PostgreSQL's 5432
      database_name=database_name,
      username="postgres",
      password="password",
      extra_connection_attributes="sslmode=require"  # Added for PostgreSQL-specific settings
    )

    dms_kinesis_access_role_policy_doc = aws_iam.PolicyDocument()
    dms_kinesis_access_role_policy_doc.add_statements(aws_iam.PolicyStatement(**{
      "effect": aws_iam.Effect.ALLOW,
      "resources": ["*"],
      "actions": [
        "kinesis:DescribeStream",
        "kinesis:PutRecord",
        "kinesis:PutRecords"]
    }))

    dms_target_kinesis_access_role = aws_iam.Role(self, 'DMSTargetKinesisAccessRole',
      role_name='DMSTargetKinesisAccessRole',
      assumed_by=aws_iam.ServicePrincipal('dms.amazonaws.com'),
      inline_policies={
        'KinesisAccessRole': dms_kinesis_access_role_policy_doc
      }
    )

    target_endpoint_id = f"{source_endpoint_id}-cdc-to-kinesis"
    dms_target_endpoint = aws_dms.CfnEndpoint(self, 'DMSTargetEndpoint',
      endpoint_identifier=target_endpoint_id,
      endpoint_type='target',
      engine_name='kinesis',
      kinesis_settings=aws_dms.CfnEndpoint.KinesisSettingsProperty(
        # MessageFormat
        #  L json-unformatted: a single line JSON string with new line format
        #  L json: an attribute-value pair in JSON format
        # Link: https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-properties-dms-endpoint-kinesissettings.html
        message_format="json-unformatted",
        service_access_role_arn=dms_target_kinesis_access_role.role_arn,
        stream_arn=target_kinesis_stream_arn
      )
    )

    table_mappings_json = {
      "rules": [
        {
          "rule-type": "selection",
          "rule-id": "1",
          "rule-name": "1",
          "object-locator": {
            "schema-name": "public",
            "table-name": table_name
          },
          "rule-action": "include",
          "filters": []
        },
        {
          "rule-type": "object-mapping",
          "rule-id": "2",
          "rule-name": "DefaultMapToKinesis",
          "rule-action": "map-record-to-record",
          "object-locator": {
            "schema-name": "public",
            "table-name": table_name
          }
        }
      ]
    }

    #XXX: AWS DMS - Using Amazon Kinesis Data Streams as a target for AWS Database Migration Service
    # https://docs.aws.amazon.com/dms/latest/userguide/CHAP_Target.Kinesis.html
    # When using "ParallelApply*" task settings, the "partition-key-type" default is the primary-key of the table, not "schema-name.table-name".
    task_settings_json = {
      # Multithreaded full load task settings
      "FullLoadSettings": {
        "MaxFullLoadSubTasks": 8,
      },
      "TargetMetadata": {
        # Multithreaded full load task settings
        "ParallelLoadQueuesPerThread": 0,
        "ParallelLoadThreads": 0,
        "ParallelLoadBufferSize": 0,

        # Multithreaded CDC load task settings
        "ParallelApplyBufferSize": 1000,
        "ParallelApplyQueuesPerThread": 16,
        "ParallelApplyThreads": 8,
      }
    }

    dms_replication_task = aws_dms.CfnReplicationTask(self, 'DMSReplicationTask',
      replication_task_identifier='CDC-PostgresToKinesisTask',  # Updated task identifier
      replication_instance_arn=dms_replication_instance.ref,
      migration_type='cdc', # [ full-load | cdc | full-load-and-cdc ]
      source_endpoint_arn=dms_source_endpoint.ref,
      target_endpoint_arn=dms_target_endpoint.ref,
      table_mappings=json.dumps(table_mappings_json),
      replication_task_settings=json.dumps(task_settings_json)
    )


    cdk.CfnOutput(self, 'DMSReplicationTaskArn',
      value=dms_replication_task.ref,
      export_name=f'{self.stack_name}-DMSReplicationTaskArn')
    cdk.CfnOutput(self, 'DMSReplicationTaskId',
      value=dms_replication_task.replication_task_identifier,
      export_name=f'{self.stack_name}-ReplicationTaskId')
    cdk.CfnOutput(self, 'DMSSourceEndpointId',
      value=dms_source_endpoint.endpoint_identifier,
      export_name=f'{self.stack_name}-SourceEndpointId')
    cdk.CfnOutput(self, 'DMSTargetEndpointId',
      value=dms_target_endpoint.endpoint_identifier,
      export_name=f'{self.stack_name}-TargetEndpointId')


from aws_cdk import Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_logs
from aws_cdk import aws_stepfunctions as sfn
from aws_cdk import aws_stepfunctions_tasks as tasks
from constructs import Construct


class DbtFargatePocStack(Stack):
    @staticmethod
    def get_env_var_array():
        return [
            tasks.TaskEnvironmentVariable(
                name="DBT_SNOWFLAKE_ACCOUNT",
                value=sfn.JsonPath.string_at("$.DbtSnowflakeAccount"),
            ),
            tasks.TaskEnvironmentVariable(
                name="DBT_USER", value=sfn.JsonPath.string_at("$.DbtUser")
            ),
            tasks.TaskEnvironmentVariable(
                name="DBT_PASSWORD",
                value=sfn.JsonPath.string_at("$.DbtPassword"),
            ),
            tasks.TaskEnvironmentVariable(
                name="DBT_SNOWFLAKE_DATABASE",
                value=sfn.JsonPath.string_at("$.DbtSnowflakeDatabase"),
            ),
            tasks.TaskEnvironmentVariable(
                name="DBT_ROLE", value=sfn.JsonPath.string_at("$.DbtRole")
            ),
            tasks.TaskEnvironmentVariable(
                name="DBT_SCHEMA",
                value=sfn.JsonPath.string_at("$.DbtSchema"),
            ),
            tasks.TaskEnvironmentVariable(
                name="DBT_WAREHOUSE",
                value=sfn.JsonPath.string_at("$.DbtWarehouse"),
            ),
        ]

    def get_ecs_task(self, name, cluster, fargate_task_definition, container):
        return tasks.EcsRunTask(
            self,
            name,
            integration_pattern=sfn.IntegrationPattern.RUN_JOB,
            cluster=cluster,
            task_definition=fargate_task_definition,
            assign_public_ip=False,
            container_overrides=[
                tasks.ContainerOverride(
                    container_definition=container,
                    environment=DbtFargatePocStack.get_env_var_array(),
                )
            ],
            launch_target=tasks.EcsFargateLaunchTarget(
                platform_version=ecs.FargatePlatformVersion.LATEST
            ),
            result_path=sfn.JsonPath.DISCARD,  # will cause the state???s input to become its output
        )

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        container_name = "andrewwlane/dockerized-dbt"  # https://hub.docker.com/r/andrewwlane/dockerized-dbt
        container_tag = "latest"

        dbt_run_fargate_task_definition = ecs.FargateTaskDefinition(
            self,
            "DbtRunExecutionTask",
            memory_limit_mib=512,
            cpu=256,
        )
        dbt_test_fargate_task_definition = ecs.FargateTaskDefinition(
            self,
            "DbtTestExecutionTask",
            memory_limit_mib=512,
            cpu=256,
        )

        dbt_run_container = dbt_run_fargate_task_definition.add_container(
            "DbtRunContainer",
            image=ecs.ContainerImage.from_registry(f"{container_name}:{container_tag}"),
            command=["run"],
            logging=ecs.LogDriver.aws_logs(stream_prefix="FargateDbtRun"),
        )
        dbt_test_container = dbt_test_fargate_task_definition.add_container(
            "DbtTestContainer",
            image=ecs.ContainerImage.from_registry(f"{container_name}:{container_tag}"),
            command=["test"],
            logging=ecs.LogDriver.aws_logs(stream_prefix="FargateDbtTest"),
        )

        vpc = ec2.Vpc(self, "FargateVpc")
        cluster = ecs.Cluster(self, "DbtFargateCluster", vpc=vpc)

        dbt_run_task = self.get_ecs_task(
            "DbtRunViaFargate",
            cluster,
            dbt_run_fargate_task_definition,
            dbt_run_container,
        )
        dbt_test_task = self.get_ecs_task(
            "DbtTestViaFargate",
            cluster,
            dbt_test_fargate_task_definition,
            dbt_test_container,
        )

        log_group = aws_logs.LogGroup(self, "DbtFargatePocLogGroup")

        sfn.StateMachine(
            self,
            "DbtOrchestrationStateMachine",
            definition=dbt_run_task.next(
                dbt_test_task.next(sfn.Succeed(self, "DbtComplete"))
            ),
            logs=sfn.LogOptions(destination=log_group, level=sfn.LogLevel.ALL),
        )

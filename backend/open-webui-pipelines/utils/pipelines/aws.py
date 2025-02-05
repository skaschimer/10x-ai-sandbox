import boto3


def assume_role(role_arn):
    sts_client = boto3.client("sts")
    assumed_role = sts_client.assume_role(
        RoleArn=role_arn, RoleSessionName="BedrockInvokeSession"
    )

    return assumed_role["Credentials"]

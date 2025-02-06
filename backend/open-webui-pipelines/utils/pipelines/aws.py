import datetime
import os
from typing import Optional

import boto3
from botocore.config import Config


def assume_role(role_arn):
    sts_client = boto3.client("sts")
    assumed_role = sts_client.assume_role(
        RoleArn=role_arn, RoleSessionName="BedrockInvokeSession"
    )

    return assumed_role["Credentials"]


def get_bedrock_client(
    assumed_role: Optional[str] = None,
    region: Optional[str] = None,
    runtime: Optional[bool] = True,
    endpoint_url: Optional[str] = None,
):
    if region is None:
        target_region = os.environ.get(
            "AWS_REGION", os.environ.get("AWS_DEFAULT_REGION")
        )
    else:
        target_region = region

    print(f"Create new client\n  Using region: {target_region}")

    aws_session_token = None
    if assumed_role:
        creds = assume_role(assumed_role)
        aws_access_key_id = creds["AccessKeyId"]
        aws_secret_access_key = creds["SecretAccessKey"]
        aws_session_token = creds["SessionToken"]
    else:
        aws_access_key_id = os.environ.get("AWS_ACCESS_KEY_ID")
        aws_secret_access_key = os.environ.get("AWS_SECRET_ACCESS_KEY")

    os.environ.pop("AWS_PROFILE", None)
    os.environ.pop("AWS_DEFAULT_PROFILE", None)

    if assumed_role and not aws_session_token:
        raise ValueError(
            "AWS_SESSION_TOKEN must be set if using an assumed role for AWS credentials"
        )

    if not aws_access_key_id or not aws_secret_access_key:
        raise ValueError("AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY must be set")

    retry_config = Config(
        region_name=target_region,
        retries={
            "max_attempts": 10,
            "mode": "standard",
        },
    )

    if runtime:
        service_name = "bedrock-runtime"
    else:
        service_name = "bedrock"

    print(f"Creating client with region: {target_region}")

    client_params = {
        "service_name": service_name,
        "region_name": target_region,
        "aws_access_key_id": aws_access_key_id,
        "aws_secret_access_key": aws_secret_access_key,
        "config": retry_config,
        "endpoint_url": endpoint_url,
    }

    if aws_session_token:
        client_params["aws_session_token"] = aws_session_token

    bedrock_client = boto3.client(**client_params)

    print("boto3 Bedrock client successfully created!")
    os.environ["BEDROCK_CLIENT_CREATED"] = str(datetime.datetime.now().timestamp())

    return bedrock_client

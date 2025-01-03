import datetime
import os
import json
import requests
from typing import List, Union, Generator, Iterator, Optional
from pydantic import BaseModel

import boto3
from botocore.config import Config


def format_llama_prompt(body):
    messages = body.get("messages", [])
    formatted_prompt = "<|begin_of_text|>"

    for message in messages:
        role = message.get("role", "")
        content = message.get("content", "")
        formatted_prompt += (
            f"<|start_header_id|>{role}<|end_header_id|>\n\n{content}<|eot_id|>"
        )

    formatted_prompt += "<|start_header_id|>assistant<|end_header_id|>"

    return formatted_prompt


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
    """Create a boto3 client for Amazon Bedrock, with optional configuration overrides

    Parameters
    ----------
    assumed_role :
        Optional ARN of an AWS IAM role to assume for calling the Bedrock service. If not
        specified, the current active credentials will be used.
    region :
        Optional name of the AWS Region in which the service should be called (e.g. "us-east-1").
        If not specified, AWS_REGION or AWS_DEFAULT_REGION environment variable will be used.
    runtime :
        Optional choice of getting different client to perform operations with the Amazon Bedrock service.
    endpoint_url :
        Optional URL of the endpoint to use for the client connection. If not specified, the default
        endpoint for the service in the specified region will be used.
    """
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
    # create os env with current time
    os.environ["BEDROCK_CLIENT_CREATED"] = str(datetime.datetime.now().timestamp())

    return bedrock_client


class Pipeline:
    class Valves(BaseModel):
        AWS_ACCESS_KEY_ID: Optional[str]
        AWS_SECRET_ACCESS_KEY: Optional[str]
        AWS_DEFAULT_REGION: Optional[str]
        BEDROCK_ENDPOINT_URL: Optional[str]
        BEDROCK_ASSUME_ROLE: Optional[str]
        BEDROCK_LLAMA3211B_ARN: Optional[str]

    def __init__(self):
        self.name = "Meta LLaMa 3.2 (11B)"
        self.valves = self.Valves(
            **{
                "AWS_ACCESS_KEY_ID": os.getenv(
                    "AWS_ACCESS_KEY_ID", "your-aws-access-key-id-here"
                ),
                "AWS_SECRET_ACCESS_KEY": os.getenv(
                    "AWS_SECRET_ACCESS_KEY", "your-aws-secret-access-key-here"
                ),
                "AWS_DEFAULT_REGION": os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
                "BEDROCK_ENDPOINT_URL": os.getenv(
                    "BEDROCK_ENDPOINT_URL",
                    "https://bedrock.us-east-1.amazonaws.com",  # bedrock-fips.us-east-1.amazonaws.com
                ),
                "BEDROCK_ASSUME_ROLE": os.getenv("BEDROCK_ASSUME_ROLE", None),
                "BEDROCK_LLAMA3211B_ARN": os.getenv("BEDROCK_LLAMA3211B_ARN", None),
            }
        )
        self.bedrock_client = get_bedrock_client(
            assumed_role=os.environ.get("BEDROCK_ASSUME_ROLE", None),
            region=os.environ.get("AWS_DEFAULT_REGION", None),
        )

    async def on_startup(self):
        print(f"on_startup:{__name__}")
        pass

    async def on_shutdown(self):
        print(f"on_shutdown:{__name__}")
        pass

    def pipe(
        self, user_message: str, model_id: str, messages: List[dict], body: dict
    ) -> Union[str, Generator, Iterator]:
        # print(f"pipe:{__name__}")

        # print(f"messages: {messages}")
        # print(f"user_message: {user_message}")
        # print(f"model_id: {model_id}")
        # print(f"body: {body}")

        # Refresh client's temp credentials after 30 minutes
        if (
            "BEDROCK_CLIENT_CREATED" not in os.environ
            or (
                datetime.datetime.now().timestamp()
                - float(os.environ["BEDROCK_CLIENT_CREATED"])
            )
            > 1800
        ):
            print("Recreating Bedrock client")
            self.bedrock_client = get_bedrock_client(
                assumed_role=os.environ.get("BEDROCK_ASSUME_ROLE", None),
                region=os.environ.get("AWS_DEFAULT_REGION", None),
            )

        formatted_prompt = format_llama_prompt(body)

        allowed_params = {"prompt" "temperature" "top_p" "max_gen_len"}

        if "user" in body and not isinstance(body["user"], str):
            body["user"] = (
                body["user"]["id"] if "id" in body["user"] else str(body["user"])
            )

        filtered_body = {k: v for k, v in body.items() if k in allowed_params}

        if len(body) != len(filtered_body):
            print(
                f"Dropped params: {', '.join(set(body.keys()) - set(filtered_body.keys()))}"
            )

        if "max_gen_len" not in filtered_body:
            filtered_body["max_gen_len"] = 2048

        filtered_body["prompt"] = formatted_prompt

        request = json.dumps(filtered_body)

        model_id = self.valves.BEDROCK_LLAMA3211B_ARN

        try:
            r = self.bedrock_client.invoke_model_with_response_stream(
                body=request,
                modelId=model_id,
            )

        except requests.exceptions.HTTPError as e:  # This will catch HTTP errors
            if r.status_code == 400:
                print(f"400 Bad Request received: {r.text}")
            else:
                print(f"HTTP Error: {e} Response: {r.text}")
            return f"Error with r: {e} ({r.text}) for body:\n{body}\nand filtered_body:\n{filtered_body}"
        except requests.exceptions.HTTPError as e:  # This will catch HTTP errors
            if r.status_code == 400:
                print(f"400 Bad Request received: {r.text}")
            else:
                print(f"HTTP Error: {e} Response: {r.text}")
            return f"Error with r: {e} ({r.text}) for body:\n{body}\nand filtered_body:\n{filtered_body}"
        except Exception as e:
            print(
                f"Error without r: {e} for body:\n{body}\nand filtered_body:\n{filtered_body}"
            )
            return f"Error without r: {e} for body:\n{body}\nand filtered_body:\n{filtered_body}"

        try:

            for event in r["body"]:
                chunk = json.loads(event["chunk"]["bytes"])
                if "generation" in chunk:
                    yield chunk["generation"]

        except Exception as e:
            if r:
                print(f"Error iterating r: {e} for r:\n{r}")
            print(f"Error iterating r: {e} for filtered_body:\n{filtered_body}")
            return f"Error iterating r: {e} for filtered_body:\n{filtered_body}"


# import logging

# logger = logging.getLogger(__name__)
# logging.basicConfig(level=logging.INFO)


# async def main():
#     pipeline = Pipeline()

#     await pipeline.on_startup()

#     model_id = "anthropic.claude-3-5-sonnet-20240620-v1:0"
#     prompt = "Describe the purpose of a 'hello world' program in one line."
#     messages = [
#         {
#             "role": "user",
#             "content": [{"type": "text", "text": prompt}],
#         }
#     ]

#     body = {
#         "anthropic_version": "bedrock-2023-05-31",
#         "max_tokens": 512,
#         "temperature": 0.5,
#         "messages": messages,
#     }

#     r = pipeline.pipe(
#         user_message=prompt, model_id=model_id, messages=messages, body=body
#     )

#     for event in r:
#         print(event)

#     await pipeline.on_shutdown()


# # Run the example
# asyncio.run(main())

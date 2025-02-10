import os
import json
import boto3
import httpx
import logging
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
import datetime
import os
from typing import Optional
from dotenv import load_dotenv
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


# Load environment variables from .env file
load_dotenv()

app = FastAPI()

model_id = os.getenv("COHERE_EMBED_MODEL_ID", "You forgot to set COHERE_EMBED_MODEL_ID")

bedrock_client = get_bedrock_client(
    assumed_role=os.environ.get("BEDROCK_ASSUME_ROLE", None),
    region=os.environ.get("AWS_DEFAULT_REGION", None),
)


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@app.post("/embeddings")
async def proxy_embeddings(request: Request):
    """
    Proxies a POST /embeddings?api-version=2023-05-15 call to the Azure OpenAI endpoint.
    """
    logger.info(f"model_id: {model_id}")
    logger.info(f"request: {request}")
    try:
        body = await request.json()
        logger.info(f"body: {body}")

        body_inputs = body.get("input")
        logger.info(f"body_inputs: {body_inputs}")

        # Prepare the request body for the Cohere Embed model
        body = json.dumps(
            {
                "texts": body_inputs,
                "input_type": "search_document",  # You can change this to 'search_query', 'classification', or 'clustering' based on your use case
            }
        )

        response = bedrock_client.invoke_model(
            body=body, modelId=model_id, accept="application/json", contentType="application/json"
        )
        logger.info(f"response: {response}")

        embeddings = response.get("embeddings")
        for e in embeddings:
            logger.info(f"embedding: {e}")

        # Parse the response
        response_body = json.loads(response.get("body").read())
        logger.info(f"response_body: {response_body}")

        # {
        #   "data": [
        #     {
        #       "object": "embedding",
        #       "index": 0,
        #       "embedding": [
        #         0.0023064255, 0.0017623018, ...  // list of floats representing the embedding vector
        #       ]
        #     }
        #     // More embeddings can be listed here if the request had multiple inputs
        #   ],
        #   "model": "text-embedding-ada-002",  // Example model name used
        #   "usage": {
        #     "prompt_tokens": 8,  // Number of tokens in the input
        #     "total_tokens": 8   // Total number of tokens used
        #   }
        # }


        logger.info(f"end of proxy_embeddings")

        # Extract the embeddings
        # embeddings = response_body.get("embeddings")
        # logger.info(f"embeddings: {embeddings}")

        # return Response(
        #     content=response_body,
        #     status_code=200,
        #     headers={"Content-Type": "application/json"},
        # )
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        return JSONResponse(status_code=500, content={"error": "Internal server error"})

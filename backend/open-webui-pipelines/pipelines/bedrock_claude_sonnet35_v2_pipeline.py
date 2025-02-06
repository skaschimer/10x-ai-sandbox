import json
import os
from typing import Generator, Iterator, List, Optional, Union

import requests
from pydantic import BaseModel
from utils.pipelines.aws import get_bedrock_client


class Pipeline:
    class Valves(BaseModel):
        AWS_ACCESS_KEY_ID: Optional[str]
        AWS_SECRET_ACCESS_KEY: Optional[str]
        AWS_DEFAULT_REGION: Optional[str]
        BEDROCK_ENDPOINT_URL: Optional[str]
        BEDROCK_ASSUME_ROLE: Optional[str]
        BEDROCK_LLAMA3211B_ARN: Optional[str]

    def __init__(self):
        self.name = "Claude Sonnet 3.5 v2"
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
                    "https://bedrock.us-east-1.amazonaws.com",
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

        # print(messages)
        # print(user_message)

        # allowed_roles = {"user", "assistant"}

        model_id = "anthropic.claude-3-5-sonnet-20241022-v2:0"

        if "messages" in body:
            # remove messages with system role and insert content into body
            new_msgs = []
            for message in body["messages"]:
                if message["role"] == "system":
                    system_msg = message["content"]
                    body["system"] = system_msg
                else:
                    new_msgs.append(message)
            body["messages"] = new_msgs

        allowed_params = {
            "anthropic_version",
            "messages",
            "temperature",
            "role",
            "content",
            "contentPart",
            "contentPartImage",
            "enhancements",
            "dataSources",
            "n",
            "stop",
            "max_tokens",
            "presence_penalty",
            "frequency_penalty",
            "logit_bias",
            "function_call",
            "functions",
            "tools",
            "tool_choice",
            "top_p",
            "log_probs",
            "top_logprobs",
            "response_format",
            "seed",
            "system",
        }
        if "user" in body and not isinstance(body["user"], str):
            body["user"] = (
                body["user"]["id"] if "id" in body["user"] else str(body["user"])
            )
        filtered_body = {k: v for k, v in body.items() if k in allowed_params}
        if len(body) != len(filtered_body):
            print(
                f"Dropped params: {', '.join(set(body.keys()) - set(filtered_body.keys()))}"
            )

        if "anthropic_version" not in filtered_body:
            filtered_body["anthropic_version"] = "bedrock-2023-05-31"

        if "max_tokens" not in filtered_body:
            filtered_body["max_tokens"] = 4000

        # Claude likes a different format for images than OpenAI
        for message in filtered_body["messages"]:
            if message["role"] == "user":
                if isinstance(message["content"], list):
                    for content in message["content"]:
                        if content["type"] == "image_url":
                            content["type"] = "image"
                            image_type = (
                                content["image_url"]["url"].split(";")[0].split("/")[1]
                            )
                            data = content["image_url"]["url"].split(",")[1]
                            content["source"] = {
                                "type": "base64",  # base64
                                "media_type": f"image/{image_type}",  # i.e. image/jpeg
                                "data": data,
                            }
                            del content["image_url"]

        try:
            r = self.bedrock_client.invoke_model_with_response_stream(
                body=json.dumps(filtered_body), modelId=model_id
            )

            for event in r["body"]:
                chunk = json.loads(event["chunk"]["bytes"])
                if chunk["type"] == "content_block_delta":
                    yield chunk["delta"].get("text", "")

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

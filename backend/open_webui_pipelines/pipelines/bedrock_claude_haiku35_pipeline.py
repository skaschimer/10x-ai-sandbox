# import datetime
import json
import os
from typing import Generator, Iterator, List, Optional, Union
import time

from pydantic import BaseModel
from utils.pipelines.aws import bedrock_client
from botocore.exceptions import BotoCoreError


class Pipeline:
    class Valves(BaseModel):
        AWS_REGION: Optional[str]
        BEDROCK_CLAUDE_HAIKU_ARN: Optional[str]

    def __init__(self):
        self.name = "Claude Haiku 3.5"
        self.valves = self.Valves(
            **{
                "AWS_REGION": os.getenv("AWS_REGION", "us-east-1"),
                "BEDROCK_CLAUDE_HAIKU_ARN": os.getenv(
                    "BEDROCK_CLAUDE_HAIKU_35_ARN", None
                ),
            }
        )
        self.bedrock_client = bedrock_client

    async def on_startup(self):
        print(f"on_startup:{__name__}")
        pass

    async def on_shutdown(self):
        print(f"on_shutdown:{__name__}")
        pass

    def pipe(
        self, user_message: str, model_id: str, messages: List[dict], body: dict
    ) -> Union[str, Generator, Iterator]:

        model_id = self.valves.BEDROCK_CLAUDE_HAIKU_ARN

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

        generic_error_msg = f"## Oops! 🤖💔\n\n ### GSA Chat is having some trouble.\n\nPlease try another model _or_ wait a minute and try again."  # noqa E501
        rate_limit_error_msg = f"## Oops! 🤖💔\n\n ### Looks like GSA Chat has hit a service limit.\n\nPlease try another model _or_ wait a minute and try again."  # noqa E501

        ttft = None
        request_init_time = time.time()

        try:
            r = self.bedrock_client.invoke_model_with_response_stream(
                body=json.dumps(filtered_body), modelId=model_id
            )

            for event in r["body"]:
                chunk = json.loads(event["chunk"]["bytes"])
                if chunk["type"] == "content_block_delta":
                    tokens = chunk["delta"].get("text", "")
                    yield tokens
                    if ttft is None and tokens:
                        ttft = time.time() - request_init_time
                        ttft_log = {
                            "pipeline_ttft": ttft * 1000,
                            "pipeline_model_id": model_id,
                            "pipeline_first_tokens": tokens,
                        }
                        json_ttft_log = json.dumps(ttft_log)
                        print("Haiku 3.5 Pipeline TTFT:", json_ttft_log)

        except self.bedrock_client.exceptions.AccessDeniedException as e:
            print("Access Denied Exception:", e)
            yield generic_error_msg
        except self.bedrock_client.exceptions.ResourceNotFoundException as e:
            print("Resource Not Found Exception:", e)
            yield generic_error_msg
        except self.bedrock_client.exceptions.ThrottlingException as e:
            print("Throttling Exception:", e)
            yield rate_limit_error_msg
        except self.bedrock_client.exceptions.ModelTimeoutException as e:
            print("Model Timeout Exception:", e)
            yield generic_error_msg
        except self.bedrock_client.exceptions.InternalServerException as e:
            print("Internal Server Exception:", e)
            yield generic_error_msg
        except self.bedrock_client.exceptions.ServiceUnavailableException as e:
            print("Service Unavailable Exception:", e)
            yield generic_error_msg
        except self.bedrock_client.exceptions.ModelStreamErrorException as e:
            print("Model Stream Error Exception:", e)
            yield generic_error_msg
        except self.bedrock_client.exceptions.ValidationException as e:
            print("Validation Exception:", e)
            yield generic_error_msg
        except self.bedrock_client.exceptions.ModelNotReadyException as e:
            print("Model Not Ready Exception:", e)
            yield generic_error_msg
        except self.bedrock_client.exceptions.ServiceQuotaExceededException as e:
            print(f"Service Quota Exceeded Exception: {e}")
            yield rate_limit_error_msg
        except self.bedrock_client.exceptions.ModelErrorException as e:
            print("Model Error Exception:", e)
            yield generic_error_msg
        except BotoCoreError as e:
            print(f"AWS BotoCoreError: {e}")
            yield generic_error_msg
        except Exception as e:
            print(f"General Error: {e}")
            yield generic_error_msg

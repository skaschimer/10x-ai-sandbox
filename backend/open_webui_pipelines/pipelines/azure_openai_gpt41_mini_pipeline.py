from typing import List, Union, Generator, Iterator
from pydantic import BaseModel
import requests
import os
import structlog


logger = structlog.get_logger(__name__)


class Pipeline:
    class Valves(BaseModel):
        AZURE_GPT41_MINI_API_KEY: str
        AZURE_GPT41_MINI_URL: str
        AZURE_OPENAI_API_VERSION: str

    def __init__(self):
        """
        Optionally, you can set the id and name of the pipeline.
        Best practice is to not specify the id so that it can be
        automatically inferred from the filename, so that users can
        install multiple versions of the same pipeline. The identifier
        must be unique across all pipelines. The identifier must be an
        alphanumeric string that can include underscores or hyphens.
        It cannot contain spaces, special characters, slashes, or
        backslashes.
        """
        logger.info("Initializing pipeline")

        self.name = "OpenAI ChatGPT 4.1 Mini"
        self.valves = self.Valves(
            **{
                "AZURE_GPT41_MINI_API_KEY": os.getenv(
                    "AZURE_GPT41_MINI_API_KEY", "your-azure-openai-api-key-here"
                ),
                "AZURE_GPT41_MINI_URL": os.getenv(
                    "AZURE_GPT41_MINI_URL", "your-azure-openai-api-key-here"
                ),
                "AZURE_OPENAI_API_VERSION": os.getenv(
                    "AZURE_OPENAI_API_VERSION", "2024-02-01"
                ),
            }
        )
        pass

    async def on_startup(self):
        # This function is called when the server is started.
        logger.info("on_startup")
        pass

    async def on_shutdown(self):
        # This function is called when the server is stopped.
        logger.info("on_shutdown")
        pass

    def pipe(
        self, user_message: str, model_id: str, messages: List[dict], body: dict
    ) -> Union[str, Generator, Iterator]:
        logger.info("pipe")

        headers = {
            "api-key": self.valves.AZURE_GPT41_MINI_API_KEY,
            "Content-Type": "application/json",
        }

        url = (
            f"{self.valves.AZURE_GPT41_MINI_URL}/chat/completions"
            + f"?api-version={self.valves.AZURE_OPENAI_API_VERSION}"
        )

        allowed_params = {
            "messages",
            "temperature",
            "role",
            "content",
            "contentPart",
            "contentPartImage",
            "enhancements",
            "dataSources",
            "n",
            "stream",
            "stop",
            "max_tokens",
            "presence_penalty",
            "frequency_penalty",
            "logit_bias",
            "user",
            "function_call",
            "functions",
            "tools",
            "tool_choice",
            "top_p",
            "log_probs",
            "top_logprobs",
            "response_format",
            "seed",
        }

        # remap user field
        if "user" in body and not isinstance(body["user"], str):
            body["user"] = (
                body["user"]["id"] if "id" in body["user"] else str(body["user"])
            )

        filtered_body = {k: v for k, v in body.items() if k in allowed_params}

        # log fields that were filtered out as a single line
        if len(body) != len(filtered_body):
            logger.info(
                "Dropped params", params=(set(body.keys()) - set(filtered_body.keys()))
            )

        r = None
        try:
            r = requests.post(
                url=url,
                json=filtered_body,
                headers=headers,
                stream=True,
            )

            r.raise_for_status()
            if body["stream"]:
                return r.iter_lines()
            else:
                return r.json()

        except Exception as e:
            text = r.text if r else ""
            raise Exception(f"Error azure gpt4o Mini pipeline: {e} {text}")

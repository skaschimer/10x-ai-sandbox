import os
import json
from typing import Iterator, List, Union
import base64

import structlog
import vertexai
from google.oauth2 import service_account
from pydantic import BaseModel, Field
from vertexai.generative_models import (
    Content,
    GenerationConfig,
    GenerativeModel,
    HarmBlockThreshold,
    HarmCategory,
    Part,
    Image,
)

logger = structlog.get_logger(__name__)


class Pipeline:
    """Google GenAI pipeline"""

    class Valves(BaseModel):
        """Options to change from the WebUI"""

        GOOGLE_PROJECT_ID: str = "You forgot to set GOOGLE_PROJECT_ID"
        GOOGLE_CLOUD_REGION: str = "You forgot to set GOOGLE_CLOUD_REGION"
        USE_PERMISSIVE_SAFETY: bool = Field(default=False)
        VERTEX_API_KEY_JSON: str = ""
        VERTEX_API_KEY_DICT: dict = {}

    def _clean_json_env(self, json_str: str) -> str:
        """Remove surrounding single quotes if present."""
        try:
            return json.loads(json_str)
        except Exception as e:
            logger.exception(
                "Error occured parsing vertex api key json, attempting to recover...",
                exc_info=e,
            )

        json_str = json_str.strip()
        if json_str.startswith("'") and json_str.endswith("'"):
            json_str = json_str[1:-1]
        return json.loads(json_str)

    def __init__(self):
        logger.info("Initializing pipeline")
        self.type = "manifold"
        self.name = "Google "

        raw_json = os.getenv("VERTEX_API_KEY_JSON", "")
        clean_json = self._clean_json_env(raw_json)

        self.valves = self.Valves(
            **{
                "GOOGLE_PROJECT_ID": os.getenv("GOOGLE_PROJECT_ID", ""),
                "GOOGLE_CLOUD_REGION": os.getenv("GOOGLE_CLOUD_REGION", "us-central1"),
                "USE_PERMISSIVE_SAFETY": False,
                "VERTEX_API_KEY_JSON": os.getenv(
                    "VERTEX_API_KEY_JSON",
                    "",
                ),
                "VERTEX_API_KEY_DICT": clean_json if clean_json else {},
            }
        )
        self.pipelines = [
            {"id": "gemini-2.0-flash", "name": "Gemini 2 Flash"},
            # {
            #     "id": "imagen-3.0-generate-002",
            #     "name": "Imagen 3 (image generation)",
            # },
            {"id": "gemini-2.5-pro-preview-03-25", "name": "Gemini 2.5 Pro"},
        ]

    async def on_startup(self) -> None:
        """This function is called when the server is started."""

        logger.info("on_startup")
        credentials = None
        try:
            # key_json = self.valves.VERTEX_API_KEY_JSON
            # key_info = self.valves.VERTEX_API_KEY_DICT
            credentials = service_account.Credentials.from_service_account_info(
                self.valves.VERTEX_API_KEY_DICT,
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
        except KeyError:
            logger.error("Error: VERTEX_API_KEY_JSON environment variable not set.")
            raise
        except json.JSONDecodeError:
            logger.error("Error: VERTEX_API_KEY_JSON contains invalid JSON.")
            raise
        except Exception as e:
            logger.exception(
                "Unexpected error initializing vertex AI client", exc_info=e
            )
            raise

        if credentials:
            vertexai.init(
                project=self.valves.GOOGLE_PROJECT_ID,
                location=self.valves.GOOGLE_CLOUD_REGION,
                credentials=credentials,
            )
            model = GenerativeModel("gemini-2.0-flash")
            try:
                response = model.generate_content(
                    "Please respond with 'hi' and nothing else.", stream=False
                )
                if "hi" in response.text.lower():
                    logger.debug("Vertex AI client initialized successfully.")
            except Exception as e:
                logger.exception("Vertex AI client failed to initialize.", exc_info=e)

    async def on_shutdown(self) -> None:
        """This function is called when the server is stopped."""
        logger.info("on_shutdown")

    async def on_valves_updated(self) -> None:
        """This function is called when the valves are updated."""
        logger.info("on_valves_updated")
        try:
            key_json = self.valves.VERTEX_API_KEY_JSON
            key_info = json.loads(key_json)
            credentials = service_account.Credentials.from_service_account_info(
                key_info,
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
        except KeyError:
            logger.error("Error: VERTEX_API_KEY_JSON environment variable not set.")
            raise
        except json.JSONDecodeError:
            logger.error("Error: VERTEX_API_KEY_JSON contains invalid JSON.")
            raise

        vertexai.init(
            project=self.valves.GOOGLE_PROJECT_ID,
            location=self.valves.GOOGLE_CLOUD_REGION,
            credentials=credentials,
        )

    def pipe(
        self, user_message: str, model_id: str, messages: List[dict], body: dict
    ) -> Union[str, Iterator]:
        try:
            credentials = service_account.Credentials.from_service_account_info(
                self.valves.VERTEX_API_KEY_DICT,
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )

            if credentials.expired:
                logger.warning("Vertex credentials have expired")
                vertexai.init(
                    project=self.valves.GOOGLE_PROJECT_ID,
                    location=self.valves.GOOGLE_CLOUD_REGION,
                    credentials=credentials,
                )

            if not model_id.startswith("gemini-"):
                return f"Error: Invalid model name format: {model_id}"

            logger.info("Pipe function called", model=model_id)

            system_message = next(
                (msg["content"] for msg in messages if msg["role"] == "system"), None
            )

            model = GenerativeModel(
                model_name=model_id,
                system_instruction=system_message,
            )

            if body.get("title", False):  # If chat title generation is requested
                contents = [Content(role="user", parts=[Part.from_text(user_message)])]
            else:
                contents = self.build_conversation_history(messages)

            generation_config = GenerationConfig(
                temperature=body.get("temperature", 0.7),
                top_p=body.get("top_p", 0.9),
                top_k=body.get("top_k", 40),
                max_output_tokens=body.get("max_tokens", 8192),
                stop_sequences=body.get("stop", []),
            )

            if self.valves.USE_PERMISSIVE_SAFETY:
                safety_settings = {
                    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                }
            else:
                safety_settings = body.get("safety_settings")

            response = model.generate_content(
                contents,
                stream=body.get("stream", False),
                generation_config=generation_config,
                safety_settings=safety_settings,
            )

            if body.get("stream", False):
                return self.stream_response(response)
            else:
                return response.text

        except Exception as e:
            logger.exception("Error generating content", exc_info=e)
            return f"An error occurred: {str(e)}"

    def stream_response(self, response):
        for chunk in response:
            if chunk.text:
                logger.debug("chunk", chunk=chunk.text)
                yield chunk.text

    def build_conversation_history(self, messages: List[dict]) -> List[Content]:
        contents = []

        for message in messages:
            if message["role"] == "system":
                continue

            parts = []

            if isinstance(message.get("content"), list):
                for content in message["content"]:
                    if content["type"] == "text":
                        parts.append(Part.from_text(content["text"]))
                    elif content["type"] == "image_url":
                        image_url = content["image_url"]["url"]
                        if image_url.startswith("data:image"):
                            image_data = image_url.split(",")[1]
                            image_bytes = base64.b64decode(image_data)
                            vertex_image = Image.from_bytes(data=image_bytes)
                            parts.append(Part.from_image(vertex_image))
                        else:
                            parts.append(Part.from_uri(image_url))
            else:
                parts = [Part.from_text(message["content"])]

            role = "user" if message["role"] == "user" else "model"
            contents.append(Content(role=role, parts=parts))

        return contents

import os
import json
import logging
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

from open_webui.utils.aws import get_bedrock_client


load_dotenv()

app = FastAPI()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

model_id = os.getenv("COHERE_EMBED_MODEL_ID", "You forgot to set COHERE_EMBED_MODEL_ID")
bedrock_client = get_bedrock_client(
    assumed_role=os.environ.get("BEDROCK_ASSUME_ROLE", None),
    region=os.environ.get("AWS_DEFAULT_REGION", None),
)


@app.post("/embeddings")
async def proxy_embeddings(request: Request):
    try:
        body = await request.json()

        body_input = body.get("input")

        tokens = 0
        for input in body_input:
            words = input.split(" ")
            tokens += len(words) / 0.75  # we can get accurate token count from tiktoken

        body = json.dumps(
            {
                "texts": body_input,
                "input_type": "search_document",  # You can change this to 'search_query', 'classification', or 'clustering' based on your use case  # noqa E501
            }
        )

        response = bedrock_client.invoke_model(
            body=body,
            modelId=model_id,
            accept="application/json",
            contentType="application/json",
        )

        response_body = json.loads(response.get("body").read())
        embeddings = response_body.get("embeddings")

        response_obj = {}
        response_obj["model"] = model_id
        response_obj["usage"] = {}
        response_obj["usage"]["prompt_tokens"] = tokens
        response_obj["usage"]["total_tokens"] = tokens
        response_obj["data"] = []
        for e in embeddings:
            response_obj["data"].append(
                {
                    "object": "embedding",
                    "index": 0,
                    "embedding": e,
                }
            )

        return Response(
            content=json.dumps(response_obj),
            status_code=200,
            headers={"Content-Type": "application/json"},
        )
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        return JSONResponse(status_code=500, content={"error": "Internal server error"})

import os
import httpx
import logging
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = FastAPI()

# Set this to your actual Azure OpenAI endpoint base URL
AZURE_OPENAI_RAG_BASE_URL = os.environ.get(
    "AZURE_OPENAI_RAG_BASE_URL", "You forgot to set AZURE_OPENAI_RAG_BASE_URL"
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@app.post("/embeddings")
async def proxy_embeddings(request: Request):
    """
    Proxies a POST /embeddings?api-version=2023-05-15 call to the Azure OpenAI endpoint.
    """
    try:
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            logger.error("Authorization header is missing")
            return JSONResponse(
                status_code=400, content={"error": "Authorization header is missing"}
            )

        bearer_token = auth_header[len("Bearer ") :]

        # Read the request body
        body = await request.json()

        # Prepare headers to forward (at minimum, Content-Type and api-key).
        forward_headers = {
            "Content-Type": request.headers.get("content-type"),
            "api-key": bearer_token,
        }

        # Build the final Azure endpoint URL
        api_version = "2023-05-15"
        azure_url = f"{AZURE_OPENAI_RAG_BASE_URL}/embeddings?api-version={api_version}"

        async with httpx.AsyncClient() as client:
            # Forward the request to the real Azure endpoint
            azure_response = await client.post(
                azure_url, headers=forward_headers, json=body
            )

        # Return the Azure response directly back to the caller
        return Response(
            content=azure_response.content,
            status_code=azure_response.status_code,
            headers={"Content-Type": "application/json"},
        )
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        return JSONResponse(status_code=500, content={"error": "Internal server error"})

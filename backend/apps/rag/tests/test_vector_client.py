import pytest
import numpy as np
from redis import Redis
from redisvl.index import AsyncSearchIndex
from backend.apps.rag.clients.vector_client import VectorClient, VectorCollection
from backend.apps.rag.utils import get_embedding_function
from backend.config import (
    RAG_OPENAI_API_KEY,
    RAG_OPENAI_API_BASE_URL,
    RAG_EMBEDDING_ENGINE,
    RAG_EMBEDDING_MODEL,
    RAG_EMBEDDING_OPENAI_BATCH_SIZE,
    REDIS_HOST,
    REDIS_PORT,
    REDIS_DB,
    REDIS_VL_SCHEMA,
    VECTOR_STORE,
)


@pytest.fixture(scope="module")
async def initialize_client():
    redis_client = Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        decode_responses=False,
    )

    if VECTOR_STORE == "redis":
        print(f"REDIS_VL_SCHEMA: {REDIS_VL_SCHEMA}")
        async_search_index = await AsyncSearchIndex.from_dict(
            REDIS_VL_SCHEMA
        ).set_client(redis_client)
        await async_search_index.create(overwrite=True)

        client = VectorClient(backend="redis")
        await client.initialize(async_search_index=async_search_index)
        return client
    else:
        raise ValueError(f"Unsupported vector store: {VECTOR_STORE}")


@pytest.fixture(scope="module")
async def vector_client(initialize_client):
    return await initialize_client


@pytest.fixture(scope="module")
def embedding_function():
    print(
        f"Called get_embedding_function with engine={RAG_EMBEDDING_ENGINE}, model={RAG_EMBEDDING_MODEL}"
    )
    return get_embedding_function(
        str(RAG_EMBEDDING_ENGINE),
        str(RAG_EMBEDDING_MODEL),
        None,
        str(RAG_OPENAI_API_KEY),
        str(RAG_OPENAI_API_BASE_URL),
        int(str(RAG_EMBEDDING_OPENAI_BATCH_SIZE)),
    )


# @pytest.mark.asyncio
# async def test_vector_client_creation(vector_client):
#     client = await vector_client
#     assert isinstance(client, VectorClient)
#     assert client.backend == "redis"


# @pytest.mark.asyncio
# async def test_create_collection(vector_client):
#     client = await vector_client
#     collection = client.create_collection("test_collection")
#     assert isinstance(collection, VectorCollection)
#     assert collection.name == "test_collection"


@pytest.mark.asyncio
async def test_add_and_query(vector_client, embedding_function):
    client = await vector_client  # No need to await
    collection = client.create_collection("test_collection")
    paragraphs = [
        "The quick brown fox jumps over the lazy dog.",
        "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
        "To be or not to be, that is the question.",
    ]
    embeddings = await embedding_function(paragraphs)
    # embeddings = [
    #     np.array(embedding, dtype=np.float32).tobytes() for embedding in embeddings
    # ]
    # print(f"~~~~~~~~~~~Paras embedding: {embeddings}")
    ids = [f"paragraph_{i}" for i in range(len(paragraphs))]
    await collection.add(
        texts=paragraphs,
        embeddings=embeddings,
        ids=ids,
        metadatas=[{"source": f"paragraph_{i}"} for i in range(len(paragraphs))],
    )
    docs = await collection.get(ids)
    if docs:
        texts = [doc["text"] for doc in docs]
        ids = [doc["doc_id"] for doc in docs]
        print(f"~~~~~~~~~~~Docs texts: {texts}\n for ids: {ids}")
    query = "What does the fox do?"
    query_embedding = await embedding_function(query)
    # query_embedding = np.array(query_embedding, dtype=np.float32).tobytes()
    # print(f"~~~~~~~~~~~Query embedding: {query_embedding}")
    results = await collection.query(query_embedding=query_embedding, n_results=2)
    print(f"~~~~~~~~~~~Query results: {results}")
    assert len(results) > 0
    assert "document" in results[0]
    assert "distance" in results[0]
    assert len(results[0]["document"]) > 0


if __name__ == "__main__":
    pytest.main([__file__])

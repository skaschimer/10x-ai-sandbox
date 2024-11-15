import pytest
import uuid
from backend.apps.rag.clients.vector_client import PGVectorClient, VectorItem
from backend.apps.rag.utils import get_embedding_function
from backend.config import (
    RAG_OPENAI_API_KEY,
    RAG_OPENAI_API_BASE_URL,
    RAG_EMBEDDING_ENGINE,
    RAG_EMBEDDING_MODEL,
    RAG_EMBEDDING_OPENAI_BATCH_SIZE,
    VECTOR_STORE,
)


@pytest.fixture(scope="module")
async def initialize_client():
    HOST = "localhost"
    DATABASE = "postgres"
    USER = "postgres"
    PASSWORD = "mysecretpassword"  # pragma: allowlist secret
    PORT = 5432
    if VECTOR_STORE == "postgres":
        return PGVectorClient(
            dbname=DATABASE, user=USER, password=PASSWORD, host=HOST, port=PORT
        )
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


@pytest.mark.asyncio
async def test_add_and_query(vector_client, embedding_function):
    collection_name = "test_collection"
    client = await vector_client
    _ = client.delete(collection_name)
    paragraphs = [
        "The quick brown fox jumps over the lazy dog.",
        "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
        "To be or not to be, that is the question.",
    ]
    embeddings = await embedding_function(paragraphs)
    # TODO: save embeddings and mock them
    # embeddings = [
    #     np.array(embedding, dtype=np.float32).tobytes() for embedding in embeddings
    # ]
    # print(f"~~~~~~~~~~~Paras embedding: {embeddings}")
    # ids = [f"paragraph_{i}" for i in range(len(paragraphs))]
    metadatas = [{"id": i} for i in range(len(paragraphs))]
    items_to_upsert = []
    for text, embedding, metadata in zip(paragraphs, embeddings, metadatas):
        vector_item = VectorItem(
            id=str(uuid.uuid4()),
            text=text,
            vector=embedding,
            metadata=metadata,
        )
        items_to_upsert.append(vector_item)
    client.upsert(collection_name, items_to_upsert)

    query = "What does the fox do?"
    query_embedding = await embedding_function(query)
    k = 3
    results = client.search(
        collection_name=collection_name,
        vectors=[query_embedding],
        limit=k - 1,
    )

    print(f"~~~~~~~~~~~Query results: {results}")
    ids = results.ids[0]
    documents = results.documents[0]
    distances = results.distances[0]
    assert len(ids) > 0
    assert "fox" in documents[0]
    assert distances[0] < 0.5


if __name__ == "__main__":
    pytest.main([__file__])

from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel
import numpy as np
import hashlib
import json
from chromadb.utils.batch_utils import create_batches
from redisvl.query import VectorQuery, FilterQuery
from redisvl.index import AsyncSearchIndex
from redisvl.query.filter import Tag
import logging

log = logging.getLogger(__name__)
log.setLevel("DEBUG")


class Metadata(BaseModel):
    key: str
    value: Any  # Be sure `Any` is truly necessary; otherwise, consider a more specific type


class QueryResult(BaseModel):
    ids: Optional[str] = None
    embeddings: Optional[np.ndarray] = None  # Single numpy array
    documents: Optional[str] = None
    uris: Optional[str] = None
    datas: Optional[np.ndarray] = None  # Single numpy array
    metadatas: Optional[Metadata] = None
    distances: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "embedding": (
                self.embedding.tolist() if self.embedding is not None else None
            ),
            "document": self.document,
            "uri": self.uri,
            "data": self.data.tolist() if self.data is not None else None,
            "metadata": self.metadata.dict() if self.metadata is not None else None,
            "distance": self.distance,
        }

    class Config:
        arbitrary_types_allowed = True


class VectorClient:
    """Unified client to manage vector collections in both Chroma and RedisVL."""

    def __init__(self, backend: str, chroma_client: Optional[Any] = None):
        self.backend = backend
        self.chroma_client = chroma_client
        self.async_search_index = None

        if backend not in ["chroma", "redis"]:
            raise ValueError("Backend must be either 'chroma' or 'redis'.")

    async def initialize(self, async_search_index: AsyncSearchIndex):
        """Initialize the VectorClient with the async_search_index."""
        if self.backend == "redis":
            self.async_search_index = async_search_index

    def create_collection(
        self, name: str, metadata: Optional[Dict[str, Any]] = None
    ) -> "VectorCollection":
        """Create a new vector collection."""
        if self.backend == "chroma":
            self.chroma_client.create_collection(name=name, metadata=metadata)
        return VectorCollection(name=name, vector_client=self, metadata=metadata)

    def get_collection(self, name: str) -> "VectorCollection":
        """Retrieve an existing vector collection."""
        # TODO: check if collection exists, meaning entries with collection tag
        if self.backend == "chroma":
            self.chroma_client.get_collection(name=name)
        elif self.backend == "redis":
            return VectorCollection(name=name, vector_client=self)

    def delete_collection(self, name: str):
        """Delete a vector collection. For Redis, handled via collection tag."""
        if self.backend == "chroma":
            self.chroma_client.delete_collection(name=name)
        elif self.backend == "redis":
            # TODO: check for entries with collection tag
            return True

    def _redis_schema(self) -> Dict[str, Any]:
        """Define the shared schema for Redis."""
        return {
            "index": {"name": "global_index", "prefix": "your_prefix"},
            "fields": [
                {"name": "text", "type": "text"},
                {"name": "metadata", "type": "text"},
                {"name": "doc_id", "type": "tag"},
                {"name": "collection", "type": "tag"},
                {
                    "name": "vector",
                    "type": "vector",
                    "attrs": {
                        "dims": 128,
                        "distance_metric": "cosine",
                        "algorithm": "flat",
                        "datatype": "float32",
                    },
                },
            ],
        }


class VectorCollection:
    def __init__(
        self,
        name: str,
        vector_client: VectorClient,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.name = name
        self.vector_client = vector_client
        self.metadata = metadata

        if vector_client.backend == "chroma":
            self.collection = vector_client.chroma_client.get_or_create_collection(
                name=self.name
            )
        elif vector_client.backend == "redis":
            self.collection = vector_client.async_search_index

    async def add(
        self,
        texts: List[str],
        embeddings: List[np.ndarray],
        ids: Optional[List[str]] = None,
        metadatas: Optional[List[Dict[str, Any]]] = None,
    ):
        """Add documents, embeddings, and other metadata to the collection."""
        ids = ids or [
            hashlib.sha256(text.encode("utf-8")).hexdigest() for text in texts
        ]
        ids = [str(id) for id in ids]  # Ensure all IDs are strings
        if self.vector_client.backend == "chroma":
            for batch in create_batches(
                api=self.vector_client.chroma_client,
                ids=ids,
                metadatas=metadatas,
                embeddings=embeddings,
                documents=texts,
            ):
                self.collection.add(*batch)
        elif self.vector_client.backend == "redis":
            data_items = [
                {
                    "text": text,
                    "metadata": json.dumps(metadatas[i]) if metadatas else "",
                    "vector": np.array(embedding, dtype=np.float32).tobytes(),
                    "doc_id": ids[i],
                    "collection": self.name,
                }
                for i, (text, embedding) in enumerate(zip(texts, embeddings))
            ]
            for id in ids:
                result = await self.collection.fetch(id)
                if result:
                    log.debug(f"Document with ID {id}, skipping")
                else:
                    await self.collection.load(data_items, id_field="doc_id")

    async def query(
        self, query_embedding: np.ndarray, n_results: int
    ) -> List[Dict[str, Any]]:
        """Query the collection for similar vectors based on a query embedding."""
        results = []
        if self.vector_client.backend == "chroma":
            raw_results = self.collection.query(
                query_embeddings=[query_embedding], n_results=n_results
            )
            # Assuming Chroma also returns a similar structure (list of dicts)
            for raw_result in raw_results:
                query_result = QueryResult(
                    ids=[doc["id"] for doc in raw_result],
                    embeddings=[np.array(doc["embedding"]) for doc in raw_result],
                    documents=[doc.get("document") for doc in raw_result],
                    distances=[doc.get("distance") for doc in raw_result],
                    # Assuming similar keys, adapt if necessary
                )
                results.append(query_result.to_dict())
        elif self.vector_client.backend == "redis":
            # log.debug(f"\n\nquery_embedding: {query_embedding}\n\n")
            # log.debug(f"\n\nNum_results to return: {n_results}\n\n")
            query = VectorQuery(
                vector=query_embedding,
                vector_field_name="vector",
                num_results=n_results,
                return_fields=["doc_id", "text", "vector", "metadata"],
                filter_expression=Tag("collection") == self.name,
                return_score=True,
            )
            raw_results = await self.collection.query(query)

            for raw_result in raw_results:
                query_result = {
                    "id": raw_result["doc_id"],
                    "embedding": np.array(raw_result["vector"]),
                    "document": raw_result["text"],
                    "metadata": json.loads(raw_result["metadata"]),
                    "distance": raw_result["vector_distance"],
                }
                results.append(query_result)

        return results

    async def get(
        self, ids: Optional[List[str]] = None
    ) -> Union[List[Dict[str, Any]], List[Any]]:
        """Retrieve documents by their IDs."""
        if self.vector_client.backend == "chroma":
            return self.collection.get(ids=ids)
        elif self.vector_client.backend == "redis":
            return (
                [await self.collection.fetch(doc_id) for doc_id in ids] if ids else []
            )

    async def get_one(self) -> List[Dict[str, Any]]:
        """Retrieve documents by their IDs."""
        if self.vector_client.backend == "chroma":
            return NotImplementedError
        elif self.vector_client.backend == "redis":
            collection_tag = Tag("collection") == self.name
            filter_query = FilterQuery(
                filter_expression=collection_tag,
                return_fields=["doc_id"],
                num_results=1,
            )
            collection_entries = await self.collection._query(filter_query)
            if len(collection_entries) > 0:
                return collection_entries
            return None

    async def delete(self, ids: List[str]):
        """Delete documents by their IDs."""
        if self.vector_client.backend == "chroma":
            return self.collection.delete(ids)
        elif self.vector_client.backend == "redis":
            await self.collection.drop_keys(ids)


from pgvector.psycopg import register_vector
import psycopg
import numpy as np
import json
from pydantic import BaseModel
from typing import Optional, List, Any


class VectorItem(BaseModel):
    id: str
    text: str
    vector: List[float | int]
    metadata: Any


class GetResult(BaseModel):
    ids: Optional[List[List[str]]]
    documents: Optional[List[List[str]]]
    metadatas: Optional[List[List[Any]]]


class SearchResult(GetResult):
    distances: Optional[List[List[float | int]]]


HOST = "localhost"
DATABASE = "postgres"
USER = "postgres"
PASSWORD = "mysecretpassword"
PORT = 5432


# NOTE: This client uses pgvector, docs: https://github.com/pgvector/pgvector/blob/master/README.md
class PGVectorClient:
    def __init__(self, dbname: str):
        # self.conn = psycopg.connect(dbname=dbname, autocommit=True)
        self.conn = psycopg.connect(
            dbname=dbname,
            user=USER,
            password=PASSWORD,
            host=HOST,
            port=PORT,
            autocommit=True,
        )
        self.conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        register_vector(self.conn)

    def has_collection(self, collection_name: str) -> bool:
        log.error(f"running check for collection_name: {collection_name}")
        result = self.conn.execute(
            "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = %s);",
            (collection_name,),
        ).fetchone()
        return result and result[0]

    def delete_collection(self, collection_name: str):
        self.conn.execute(f"DROP TABLE IF EXISTS {collection_name}")

    def search(
        self, collection_name: str, vectors: list[list[float]], limit: int
    ) -> Optional[SearchResult]:
        try:
            log.error(f"running search for collection_name: {collection_name}")
            # TODO: need to validate this HNSW index can provide sufficient precision for any params
            # self.conn.execute("SET LOCAL hnsw.ef_search = 64")
            query = f"""
                SELECT id, content, (embedding <=> %s::vector) AS distance, metadata
                FROM {collection_name}
                ORDER BY distance
                LIMIT %s;
            """

            result = self.conn.execute(query, (vectors[0], limit + 1)).fetchall()

            log.error(f"search result is: {result}")

            # Drop first result which is the query string itself
            result = result[1:]

            if result:
                return SearchResult(
                    ids=[[str(row[0]) for row in result]],
                    distances=[[row[2] for row in result]],
                    documents=[[row[1] for row in result]],
                    metadatas=[[row[3] for row in result]],
                )
            return None
        except Exception as e:
            print("Search Error:", e)
            return None

    def query(
        self, collection_name: str, filter: dict, limit: Optional[int] = None
    ) -> Optional[GetResult]:
        try:
            where_clause = " AND ".join([f"{key} = %({key})s" for key in filter.keys()])
            result = self.conn.execute(
                f"SELECT id, content, metadata FROM {collection_name} WHERE {where_clause} LIMIT %(limit)s;",
                {**filter, "limit": limit},
            ).fetchall()

            if result:
                return GetResult(
                    ids=[[str(row[0]) for row in result]],
                    documents=[[row[1] for row in result]],
                    metadatas=[[row[2] for row in result]],
                )
            return None
        except Exception as e:
            print("Query Error:", e)
            return None

    def get(self, collection_name: str) -> Optional[GetResult]:
        try:
            result = self.conn.execute(
                f"SELECT id, content, metadata FROM {collection_name};"
            ).fetchall()

            if result:
                return GetResult(
                    ids=[[row[0] for row in result]],
                    documents=[[row[1] for row in result]],
                    metadatas=[row[2] for row in result],
                )
            return None
        except Exception as e:
            print("Get Error:", e)
            return None

    def insert(self, collection_name: str, items: list[VectorItem]):
        try:
            if not self.has_collection(collection_name):
                self.conn.execute(
                    f"CREATE TABLE {collection_name} "
                    f"(id bigserial PRIMARY KEY, content text, embedding vector(1536), metadata jsonb)"
                )

            for item in items:
                self.conn.execute(
                    f"INSERT INTO {collection_name} (content, embedding, metadata) VALUES (%s, %s, %s)",
                    (item["text"], item["vector"], json.dumps(item["metadata"])),
                )
        except Exception as e:
            print("Insert Error:", e)

    def upsert(self, collection_name: str, items: list[VectorItem]):
        try:
            log.info(f"upsert searching for collection_name: {collection_name}")
            if not self.has_collection(collection_name):
                self.conn.execute(
                    f"CREATE TABLE {collection_name} "
                    f"(id bigserial PRIMARY KEY, content text, embedding vector(1536), metadata jsonb)"
                )

            for item in items:
                # log.info(f"Inserting vector {item['vector'][0:5]}")
                self.conn.execute(
                    f"""
                    INSERT INTO {collection_name} (content, embedding, metadata)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (id)
                    DO UPDATE SET content = EXCLUDED.content, embedding = EXCLUDED.embedding, metadata = EXCLUDED.metadata
                    """,  # noqa: E501
                    (item["text"], item["vector"], json.dumps(item["metadata"])),
                )
            return True
        except Exception as e:
            log.error("Upsert Error:", e)
            return False

    def delete(
        self,
        collection_name: str,
        ids: Optional[list[str]] = None,
        filter: Optional[dict] = None,
    ):
        try:
            if ids:
                self.conn.execute(
                    f"DELETE FROM {collection_name} WHERE id IN %(ids)s;",
                    {"ids": tuple(ids)},
                )
            elif filter:
                where_clause = " AND ".join(
                    [f"{key} = %({key})s" for key in filter.keys()]
                )
                self.conn.execute(
                    f"DELETE FROM {collection_name} WHERE {where_clause};", filter
                )
        except Exception as e:
            print("Delete Error:", e)

    def reset(self):
        try:
            tables = self.conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';"
            ).fetchall()

            for table in tables:
                self.conn.execute(f"DROP TABLE IF EXISTS {table[0]} CASCADE;")
        except Exception as e:
            print("Reset Error:", e)

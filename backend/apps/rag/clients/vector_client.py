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

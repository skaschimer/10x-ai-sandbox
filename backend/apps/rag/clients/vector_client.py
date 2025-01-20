from typing import Optional, List, Any
from pydantic import BaseModel
import json
import logging
from pgvector.psycopg import register_vector
import psycopg

log = logging.getLogger(__name__)
log.setLevel("INFO")


class VectorItem(BaseModel):
    id: str
    text: str
    vector: List[float | int]
    metadata: Any


class GetResult(BaseModel):
    ids: Optional[List[List[str | int]]]
    documents: Optional[List[List[str]]]
    metadatas: Optional[List[List[Any]]]


class SearchResult(GetResult):
    distances: Optional[List[List[float | int]]]


# NOTE: This client uses pgvector, docs: https://github.com/pgvector/pgvector/blob/master/README.md
class PGVectorClient:
    def __init__(self, dbname: str, user: str, password: str, host: str, port: int):
        # self.conn = psycopg.connect(dbname=dbname, autocommit=True)
        self.conn = psycopg.connect(
            dbname=dbname,
            user=user,
            password=password,
            host=host,
            port=port,
            autocommit=True,
        )
        self.conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        log.info("Established connection to the database")
        register_vector(self.conn)

    def has_collection(self, collection_name: str) -> bool:
        result = self.conn.execute(
            "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = %s);",
            (collection_name,),
        ).fetchone()
        return result and result[0]

    def delete_collection(self, collection_name: str):
        self.conn.execute(f'DROP TABLE IF EXISTS "{collection_name}"')

    def search(
        self, collection_name: str, vectors: list[list[float]], limit: int
    ) -> Optional[SearchResult]:
        try:
            # TODO: need to validate this HNSW index can provide sufficient precision for any params
            # self.conn.execute("SET LOCAL hnsw.ef_search = 64")
            query = f"""
                SELECT id, content, (embedding <=> %s::vector) AS distance, metadata
                FROM "{collection_name}"
                ORDER BY distance
                LIMIT %s;
            """

            result = self.conn.execute(query, (vectors[0], limit + 1)).fetchall()

            if result:
                return SearchResult(
                    ids=[[str(row[0]) for row in result]],
                    documents=[[row[1] for row in result]],
                    distances=[[row[2] for row in result]],
                    metadatas=[[row[3] for row in result]],
                )
            return None
        except Exception as e:
            log.error("Search Error:", e)
            return None

    def query(
        self, collection_name: str, filter: dict, limit: Optional[int] = None
    ) -> Optional[GetResult]:
        try:
            where_clause = " AND ".join([f"{key} = %({key})s" for key in filter.keys()])
            result = self.conn.execute(
                f'SELECT id, content, metadata FROM "{collection_name}" WHERE {where_clause} LIMIT %(limit)s;',
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
            log.error("Query Error:", e)
            return None

    def get(self, collection_name: str) -> Optional[GetResult]:
        try:
            result = self.conn.execute(
                f'SELECT id, content, metadata FROM "{collection_name}";'
            ).fetchall()

            if result:
                return GetResult(
                    ids=[[row[0] for row in result]],
                    documents=[[row[1] for row in result]],
                    metadatas=[[row[2] for row in result]],
                )
            return None
        except Exception as e:
            log.error(f"Get Error: {e}")
            return None

    def insert(self, collection_name: str, items: list[VectorItem]):
        try:
            if not self.has_collection(collection_name):
                self.conn.execute(
                    f'CREATE TABLE "{collection_name}" '
                    f"(id bigserial PRIMARY KEY, content text, embedding vector(1536), metadata jsonb)"
                )

            for item in items:
                self.conn.execute(
                    f'INSERT INTO "{collection_name}" (content, embedding, metadata) VALUES (%s, %s, %s)',
                    (item["text"], item["vector"], json.dumps(item["metadata"])),
                )
        except Exception as e:
            log.error("Insert Error:", e)

    def upsert(self, collection_name: str, items: list[VectorItem]):
        try:
            if not self.has_collection(collection_name):
                self.conn.execute(
                    f'CREATE TABLE "{collection_name}" '
                    f"(id bigserial PRIMARY KEY, content text, embedding vector(1536), metadata jsonb)"
                )

            for item in items:
                self.conn.execute(
                    f"""
                    INSERT INTO "{collection_name}" (content, embedding, metadata)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (id)
                    DO UPDATE SET content = EXCLUDED.content, embedding = EXCLUDED.embedding, metadata = EXCLUDED.metadata
                    """,  # noqa: E501
                    (item.text, item.vector, json.dumps(item.metadata)),
                )
            return True
        except Exception as e:
            log.error("Upsert Error:", e)
            raise e

    def delete(
        self,
        collection_name: str,
        ids: Optional[list[str]] = None,
        filter: Optional[dict] = None,
    ):
        try:
            if ids:
                self.conn.execute(
                    f'DELETE FROM "{collection_name}" WHERE id IN %(ids)s;',
                    {"ids": tuple(ids)},
                )
            elif filter:
                where_clause = " AND ".join(
                    [f"{key} = %({key})s" for key in filter.keys()]
                )
                self.conn.execute(
                    f'DELETE FROM "{collection_name}" WHERE {where_clause};', filter
                )
            elif not ids and not filter:  # Check if both are empty
                self.conn.execute(f'DROP TABLE IF EXISTS "{collection_name}";')
            return True

        except Exception as e:
            log.error("Delete Error:", e)
            return False

    def reset(self):
        try:
            tables = self.conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';"
            ).fetchall()

            for table in tables:
                self.conn.execute(f"DROP TABLE IF EXISTS {table[0]} CASCADE;")
        except Exception as e:
            log.error("Reset Error:", e)

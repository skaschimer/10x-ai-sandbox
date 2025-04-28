import contextlib
import logging
from typing import Optional, List, Dict, Any
from sqlalchemy import (
    cast,
    column,
    create_engine,
    Column,
    Integer,
    select,
    text,
    Text,
    values,
)
from sqlalchemy.sql import true

from sqlalchemy.orm import declarative_base, Session, sessionmaker
from sqlalchemy.dialects.postgresql import JSONB, array
from pgvector.sqlalchemy import Vector
from sqlalchemy.ext.mutable import MutableDict

from open_webui.env import SRC_LOG_LEVELS
from open_webui.retrieval.vector.main import VectorItem, SearchResult, GetResult
from open_webui.config import config

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["RAG"])


VECTOR_LENGTH = 1536
Base = declarative_base()


class DocumentChunk(Base):
    __tablename__ = "document_chunk"

    id = Column(Text, primary_key=True)
    vector = Column(Vector(dim=VECTOR_LENGTH), nullable=True)
    collection_name = Column(Text, nullable=False)
    text = Column(Text, nullable=True)
    vmetadata = Column(MutableDict.as_mutable(JSONB), nullable=True)


class PgvectorClient:
    def __init__(self) -> None:

        # if no pgvector uri, use the existing database connection
        if not config.PGVECTOR_DB_URL:
            from open_webui.internal.db import Session as MainLocalSession

            self.session = MainLocalSession
        else:
            engine = create_engine(config.PGVECTOR_DB_URL, pool_pre_ping=True)
            # save the session factory, not the session it generates
            self.SessionLocal = sessionmaker(
                autocommit=False, autoflush=False, bind=engine, expire_on_commit=False
            )

        try:
            with self.get_session() as session:
                # Ensure the pgvector extension is available
                session.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))

                # Create the tables if they do not exist
                Base.metadata.create_all(bind=session.connection())

                # Create an index on the vector column if it doesn't exist
                session.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_document_chunk_vector "
                        "ON document_chunk USING ivfflat (vector vector_cosine_ops) WITH (lists = 100);"
                    )
                )
                session.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_document_chunk_collection_name "
                        "ON document_chunk (collection_name);"
                    )
                )
                log.info("Initialization complete.")
        except Exception as e:
            log.error(e, stack_info=True, exc_info=True)
            raise

    @contextlib.contextmanager
    def get_session(self) -> Session:
        """Manage session in context manager to ensure liefcycle is handled correctly"""
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception as e:
            log.error(e, stack_info=True, exc_info=True)
            session.rollback()
            raise
        finally:
            session.close()

    def adjust_vector_length(self, vector: List[float]) -> List[float]:
        # Adjust vector to have length VECTOR_LENGTH
        current_length = len(vector)
        if current_length < VECTOR_LENGTH:
            # Pad the vector with zeros
            vector += [0.0] * (VECTOR_LENGTH - current_length)
        elif current_length > VECTOR_LENGTH:
            raise Exception(
                f"Vector length {current_length} not supported. Max length must be <= {VECTOR_LENGTH}"
            )
        return vector

    def insert(self, collection_name: str, items: List[VectorItem]) -> None:
        new_items = []
        for item in items:
            vector = self.adjust_vector_length(item["vector"])
            new_chunk = DocumentChunk(
                id=item["id"],
                vector=vector,
                collection_name=collection_name,
                text=item["text"],
                vmetadata=item["metadata"],
            )
            new_items.append(new_chunk)
        with self.get_session() as session:
            session.bulk_save_objects(new_items)

        log.debug(
            f"Inserted {len(new_items)} items into collection '{collection_name}'."
        )

    def upsert(self, collection_name: str, items: List[VectorItem]) -> None:
        with self.get_session() as session:
            for item in items:
                vector = self.adjust_vector_length(item["vector"])
                existing = (
                    session.query(DocumentChunk)
                    .filter(DocumentChunk.id == item["id"])
                    .first()
                )
                if existing:
                    existing.vector = vector
                    existing.text = item["text"]
                    existing.vmetadata = item["metadata"]
                    existing.collection_name = (
                        collection_name  # Update collection_name if necessary
                    )
                else:
                    new_chunk = DocumentChunk(
                        id=item["id"],
                        vector=vector,
                        collection_name=collection_name,
                        text=item["text"],
                        vmetadata=item["metadata"],
                    )
                    session.add(new_chunk)
            log.debug(
                f"Upserted {len(items)} items into collection '{collection_name}'."
            )

    def search(
        self,
        collection_name: str,
        vectors: List[List[float]],
        limit: Optional[int] = None,
    ) -> Optional[SearchResult]:
        if not vectors:
            return None

        # Adjust query vectors to VECTOR_LENGTH
        vectors = [self.adjust_vector_length(vector) for vector in vectors]
        num_queries = len(vectors)

        def vector_expr(vector):
            return cast(array(vector), Vector(VECTOR_LENGTH))

        # Create the values for query vectors
        qid_col = column("qid", Integer)
        q_vector_col = column("q_vector", Vector(VECTOR_LENGTH))
        query_vectors = (
            values(qid_col, q_vector_col)
            .data([(idx, vector_expr(vector)) for idx, vector in enumerate(vectors)])
            .alias("query_vectors")
        )

        # Build the lateral subquery for each query vector
        subq = (
            select(
                DocumentChunk.id,
                DocumentChunk.text,
                DocumentChunk.vmetadata,
                (DocumentChunk.vector.cosine_distance(query_vectors.c.q_vector)).label(
                    "distance"
                ),
            )
            .where(DocumentChunk.collection_name == collection_name)
            .order_by((DocumentChunk.vector.cosine_distance(query_vectors.c.q_vector)))
        )
        if limit is not None:
            subq = subq.limit(limit)
        subq = subq.lateral("result")

        # Build the main query by joining query_vectors and the lateral subquery
        stmt = (
            select(
                query_vectors.c.qid,
                subq.c.id,
                subq.c.text,
                subq.c.vmetadata,
                subq.c.distance,
            )
            .select_from(query_vectors)
            .join(subq, true())
            .order_by(query_vectors.c.qid, subq.c.distance)
        )
        with self.get_session() as session:
            result_proxy = session.execute(stmt)
            results = result_proxy.all()

        ids = [[] for _ in range(num_queries)]
        distances = [[] for _ in range(num_queries)]
        documents = [[] for _ in range(num_queries)]
        metadatas = [[] for _ in range(num_queries)]

        if not results:
            return SearchResult(
                ids=ids,
                distances=distances,
                documents=documents,
                metadatas=metadatas,
            )

        for row in results:
            qid = int(row.qid)
            ids[qid].append(row.id)
            distances[qid].append(row.distance)
            documents[qid].append(row.text)
            metadatas[qid].append(row.vmetadata)

        return SearchResult(
            ids=ids, distances=distances, documents=documents, metadatas=metadatas
        )

    def query(
        self, collection_name: str, filter: Dict[str, Any], limit: Optional[int] = None
    ) -> Optional[GetResult]:
        with self.get_session() as session:
            query = session.query(DocumentChunk).filter(
                DocumentChunk.collection_name == collection_name
            )

            for key, value in filter.items():
                query = query.filter(DocumentChunk.vmetadata[key].astext == str(value))

            if limit is not None:
                query = query.limit(limit)

            results = query.all()

            if not results:
                return None

            ids = [[result.id for result in results]]
            documents = [[result.text for result in results]]
            metadatas = [[result.vmetadata for result in results]]

            return GetResult(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
            )

    def get(
        self, collection_name: str, limit: Optional[int] = None
    ) -> Optional[GetResult]:
        with self.get_session() as session:
            query = session.query(DocumentChunk).filter(
                DocumentChunk.collection_name == collection_name
            )
            if limit is not None:
                query = query.limit(limit)

            results = query.all()

            if not results:
                return None

            ids = [[result.id for result in results]]
            documents = [[result.text for result in results]]
            metadatas = [[result.vmetadata for result in results]]

            return GetResult(ids=ids, documents=documents, metadatas=metadatas)

    def delete(
        self,
        collection_name: str,
        ids: Optional[List[str]] = None,
        filter: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self.get_session() as session:
            query = session.query(DocumentChunk).filter(
                DocumentChunk.collection_name == collection_name
            )
            if ids:
                query = query.filter(DocumentChunk.id.in_(ids))
            if filter:
                for key, value in filter.items():
                    query = query.filter(
                        DocumentChunk.vmetadata[key].astext == str(value)
                    )
            deleted = query.delete(synchronize_session=False)
        log.debug(f"Deleted {deleted} items from collection '{collection_name}'.")

    def reset(self) -> None:
        with self.get_session() as session:
            deleted = session.query(DocumentChunk).delete()
        log.debug(
            f"Reset complete. Deleted {deleted} items from 'document_chunk' table."
        )

    def close(self) -> None:
        pass

    def has_collection(self, collection_name: str) -> bool:
        with self.get_session() as session:
            exists = (
                session.query(DocumentChunk)
                .filter(DocumentChunk.collection_name == collection_name)
                .first()
                is not None
            )
            return exists

    def delete_collection(self, collection_name: str) -> None:
        self.delete(collection_name)
        log.debug(f"Collection '{collection_name}' deleted.")

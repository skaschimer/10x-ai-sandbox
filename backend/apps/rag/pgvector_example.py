# from openai import OpenAI
# from pgvector.psycopg import register_vector
# import psycopg
# from langchain_core.documents import Document
# import os
# import numpy as np
# import json
# from pydantic import BaseModel
# from typing import Optional, List, Any


# class VectorItem(BaseModel):
#     id: str
#     text: str
#     vector: List[float | int]
#     metadata: Any


# class GetResult(BaseModel):
#     ids: Optional[List[List[str]]]
#     documents: Optional[List[List[str]]]
#     metadatas: Optional[List[List[Any]]]


# class SearchResult(GetResult):
#     distances: Optional[List[List[float | int]]]


# # NOTE: This client uses pgvector, docs: https://github.com/pgvector/pgvector/blob/master/README.md
# class PGVectorClient:
#     def __init__(self, dbname: str):
#         # self.conn = psycopg.connect(dbname=dbname, autocommit=True)
#         self.conn = psycopg.connect(
#             dbname=dbname,
#             user=USER,
#             password=PASSWORD,
#             host=HOST,
#             port=PORT,
#             autocommit=True,
#         )
#         self.conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
#         register_vector(self.conn)

#     def has_collection(self, collection_name: str) -> bool:
#         result = self.conn.execute(
#             "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = %s);",
#             (collection_name,),
#         ).fetchone()
#         return result and result[0]

#     def delete_collection(self, collection_name: str):
#         self.conn.execute(f"DROP TABLE IF EXISTS {collection_name}")

#     def search(
#         self, collection_name: str, vectors: list[list[float]], limit: int
#     ) -> Optional[SearchResult]:
#         try:
#             # TODO: need to validate this HNSW index can provide sufficient precision for any params
#             self.conn.execute("SET LOCAL hnsw.ef_search = 64")
#             query = f"""
#                 SELECT id, content, (embedding <=> %s::vector) AS distance, metadata
#                 FROM {collection_name}
#                 ORDER BY distance
#                 LIMIT %s;
#             """

#             result = self.conn.execute(query, (vectors[0], limit + 1)).fetchall()

#             # Drop first result which is the query string itself
#             result = result[1:]

#             if result:
#                 return SearchResult(
#                     ids=[[str(row[0]) for row in result]],
#                     distances=[[row[2] for row in result]],
#                     documents=[[row[1] for row in result]],
#                     metadatas=[[row[3] for row in result]],
#                 )
#             return None
#         except Exception as e:
#             print("Search Error:", e)
#             return None

#     def query(
#         self, collection_name: str, filter: dict, limit: Optional[int] = None
#     ) -> Optional[GetResult]:
#         try:
#             where_clause = " AND ".join([f"{key} = %({key})s" for key in filter.keys()])
#             result = self.conn.execute(
#                 f"SELECT id, content, metadata FROM {collection_name} WHERE {where_clause} LIMIT %(limit)s;",
#                 {**filter, "limit": limit},
#             ).fetchall()

#             if result:
#                 return GetResult(
#                     ids=[[str(row[0]) for row in result]],
#                     documents=[[row[1] for row in result]],
#                     metadatas=[[row[2] for row in result]],
#                 )
#             return None
#         except Exception as e:
#             print("Query Error:", e)
#             return None

#     def get(self, collection_name: str) -> Optional[GetResult]:
#         try:
#             result = self.conn.execute(
#                 f"SELECT id, content, metadata FROM {collection_name};"
#             ).fetchall()

#             if result:
#                 return GetResult(
#                     ids=[[row[0] for row in result]],
#                     documents=[[row[1] for row in result]],
#                     metadatas=[row[2] for row in result],
#                 )
#             return None
#         except Exception as e:
#             print("Get Error:", e)
#             return None

#     def insert(self, collection_name: str, items: list[VectorItem]):
#         try:
#             if not self.has_collection(collection_name):
#                 self.conn.execute(
#                     f"CREATE TABLE {collection_name} "
#                     f"(id bigserial PRIMARY KEY, content text, embedding vector(1536), metadata jsonb)"
#                 )

#             for item in items:
#                 self.conn.execute(
#                     f"INSERT INTO {collection_name} (content, embedding, metadata) VALUES (%s, %s, %s)",
#                     (item["text"], item["vector"], json.dumps(item["metadata"])),
#                 )
#         except Exception as e:
#             print("Insert Error:", e)

#     def upsert(self, collection_name: str, items: list[VectorItem]):
#         try:
#             if not self.has_collection(collection_name):
#                 self.conn.execute(
#                     f"CREATE TABLE {collection_name} "
#                     f"(id bigserial PRIMARY KEY, content text, embedding vector(1536), metadata jsonb)"
#                 )

#             for item in items:
#                 self.conn.execute(
#                     f"""
#                     INSERT INTO {collection_name} (content, embedding, metadata)
#                     VALUES (%s, %s, %s)
#                     ON CONFLICT (id)
#                     DO UPDATE SET content = EXCLUDED.content, embedding = EXCLUDED.embedding, metadata = EXCLUDED.metadata
#                     """,  # noqa: E501
#                     (item["text"], item["vector"], json.dumps(item["metadata"])),
#                 )
#         except Exception as e:
#             print("Upsert Error:", e)

#     def delete(
#         self,
#         collection_name: str,
#         ids: Optional[list[str]] = None,
#         filter: Optional[dict] = None,
#     ):
#         try:
#             if ids:
#                 self.conn.execute(
#                     f"DELETE FROM {collection_name} WHERE id IN %(ids)s;",
#                     {"ids": tuple(ids)},
#                 )
#             elif filter:
#                 where_clause = " AND ".join(
#                     [f"{key} = %({key})s" for key in filter.keys()]
#                 )
#                 self.conn.execute(
#                     f"DELETE FROM {collection_name} WHERE {where_clause};", filter
#                 )
#         except Exception as e:
#             print("Delete Error:", e)

#     def reset(self):
#         try:
#             tables = self.conn.execute(
#                 "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';"
#             ).fetchall()

#             for table in tables:
#                 self.conn.execute(f"DROP TABLE IF EXISTS {table[0]} CASCADE;")
#         except Exception as e:
#             print("Reset Error:", e)


# # # Set your OpenAI API key
# # api_key = os.getenv("OPENAI_API_KEY")  # Make sure your environment variable is set
# # client = OpenAI(api_key=api_key)

# # print("Hi!...")

# # # Database connection details
# # HOST = "localhost"
# # DATABASE = "postgres"
# # USER = "postgres"
# # PASSWORD = "mysecretpassword"
# # PORT = 5432

# # # Connect to Postgres and register the vector extension
# # connection = psycopg.connect(
# #     dbname=DATABASE, user=USER, password=PASSWORD, host=HOST, port=PORT, autocommit=True
# # )
# # register_vector(connection)
# # connection.execute(
# #     "CREATE EXTENSION IF NOT EXISTS vector"
# # )  # might be redundant with above
# # collection_name = "chunks_of_test_doc"
# # connection.execute(f"DROP TABLE IF EXISTS {collection_name}")
# # connection.execute(
# #     f"CREATE TABLE {collection_name} (id bigserial PRIMARY KEY, content text, embedding vector(1536), metadata jsonb)"
# # )


# # connection.execute(
# #     f"CREATE INDEX ON items USING hnsw (embedding vector_l2_ops) WITH (m = 16, ef_construction = 64)"
# # )
# # # NOTE: Has more precision out of the box than IVFFlat, but is slower to build and requires more memory. Need to explore to determine if precision is acceptable. # noqa: E501


# # # # NOTE: creating more than 1 ivfflat partition means only the best-matching partition will be searched, this may be fine in cases that will always have many overlapping acceptable results, but will almost never be good enough for government work # noqa: E501
# # # connection.execute(
# # #     f"CREATE INDEX ON {collection_name} USING ivfflat (embedding vector_cosine_ops) WITH (lists = 1)"
# # # )


# # # Prepare documents
# # docs = [
# #     Document(page_content="there are cats in the pond", metadata={"id": 1}),
# #     Document(page_content="ducks are also found in the pond", metadata={"id": 2}),
# #     Document(
# #         page_content="fresh apples are available at the market", metadata={"id": 3}
# #     ),
# #     Document(page_content="the market also sells fresh oranges", metadata={"id": 4}),
# #     Document(page_content="the new art exhibit is fascinating", metadata={"id": 5}),
# #     Document(
# #         page_content="a sculpture exhibit is also at the museum", metadata={"id": 6}
# #     ),
# #     Document(
# #         page_content="a new coffee shop opened on Main Street", metadata={"id": 7}
# #     ),
# #     Document(page_content="the book club meets at the library", metadata={"id": 8}),
# #     Document(
# #         page_content="the library hosts a weekly story time for kids",
# #         metadata={"id": 9},
# #     ),
# #     Document(
# #         page_content="a cooking class for beginners is offered at the community center",
# #         metadata={"id": 10},
# #     ),
# # ]


# # # Generate embeddings using OpenAI API
# # input_texts = [doc.page_content for doc in docs]
# # response = client.embeddings.create(input=input_texts, model="text-embedding-3-small")
# # embeddings = [np.array(v.embedding) for v in response.data]
# # metadatas = [json.dumps(doc.metadata) for doc in docs]

# # print(f"Embeddings: {embeddings}")
# # # Define the file path where you want to save the embeddings
# # file_path = "./embeddings.txt"  # You can change the file path and name as needed
# # # Open the file in write mode and write the embeddings to it
# # with open(file_path, "w") as file:
# #     # Temporarily change numpy print options to avoid truncation
# #     np.set_printoptions(threshold=np.inf, linewidth=np.inf)
# #     for embedding in embeddings:
# #         # Convert the array to a string with all elements
# #         embedding_str = np.array2string(embedding, separator=",")
# #         file.write(f"{embedding_str}\n")
# #     # Reset print options to default to avoid affecting other parts of the code
# #     np.set_printoptions()
# # print(f"Embeddings have been written to {file_path}")
# # print(f"input_texts: {input_texts}")
# # print(f"metadatas: {metadatas}")

# # # Insert documents with embeddings into the database
# # for content, embedding, metadata in zip(input_texts, embeddings, metadatas):
# #     connection.execute(
# #         f"INSERT INTO {collection_name} (content, embedding, metadata) VALUES (%s, %s, %s)",
# #         (content, embedding, metadata),
# #     )

# # input_texts = ["there are cats in the market"]
# # response = client.embeddings.create(input=input_texts, model="text-embedding-3-small")
# # embeddings = [np.array(v.embedding) for v in response.data]

# # # Define the number of results to grab
# # num_results_to_grab = 5  # You can change this value as needed

# # # Perform a similarity search
# # query_vector = embeddings[0]
# # with connection.cursor() as cursor:  # Create a cursor object
# #     cursor.execute("SET LOCAL hnsw.ef_search = 64")
# #     cursor.execute(
# #         "SELECT content, embedding <=> %s::vector AS distance, metadata "
# #         f"FROM {collection_name} "
# #         "ORDER BY distance LIMIT %s",
# #         (query_vector.tolist(), num_results_to_grab),  # Use the variable here
# #     )
# #     neighbors = cursor.fetchall()  # Fetch all results

# # # Print the input text
# # print(f"Input text:\n~~~> {input_texts[0]}")
# # print("Nearest neighbors:")
# # for neighbor in neighbors:
# #     text_content = neighbor[0]  # Extract content
# #     distance = (2 - neighbor[1]) / 2  # Extract distance
# #     metadata = neighbor[2]["id"]  # Extract metadata
# #     print(f"{text_content}, score: {distance:.3f}, id: {metadata}")


# # # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# # # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# # # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

# # # Initialize the PGVectorClient
# # pgvector_client = PGVectorClient(dbname=DATABASE)

# # # Prepare the vector items for insertion
# # vector_items = [
# #     VectorItem(
# #         id=str(doc.metadata["id"]),
# #         text=doc.page_content,
# #         vector=embedding.tolist(),
# #         metadata=doc.metadata,
# #     ).__dict__
# #     for doc, embedding in zip(docs, embeddings)
# # ]

# # # Insert vector items using the PGVectorClient
# # pgvector_client.insert(collection_name, vector_items)

# # # Perform a similarity search using PGVectorClient's search method
# # search_input_text = ["there are cats in the market"]

# # # Fetch the search results
# # search_results = pgvector_client.search(
# #     collection_name=collection_name,
# #     vectors=[embeddings[0].tolist()],
# #     limit=num_results_to_grab,
# # )

# # # Print the input text
# # print(f"Input text:\n~~~> {search_input_text[0]}")
# # print("Nearest neighbors:")
# # if search_results:
# #     for text_content, distance, metadata in zip(
# #         search_results.documents[0],
# #         search_results.distances[0],
# #         search_results.metadatas[0],
# #     ):
# #         print(f"{text_content}, score: {distance}%, id: {metadata['id']}")
# # else:
# #     print("No neighbors found.")

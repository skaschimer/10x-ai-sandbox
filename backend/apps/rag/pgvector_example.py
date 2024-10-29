# from sentence_transformers import SentenceTransformer
# from langchain_huggingface import HuggingFaceEmbeddings

# from langchain_core.documents import Document
# from langchain_postgres import PGVector
# from langchain_postgres.vectorstores import PGVector

# embedding_model = HuggingFaceEmbeddings(
#     model_name="sentence-transformers/all-MiniLM-L6-v2"
# )

# HOST = "localhost"
# DATABASE = "postgres"
# USER = "postgres"
# PASSWORD = "mysecretpassword"
# PORT = 5432

# connection = f"postgresql+psycopg://{USER}:{PASSWORD}@localhost:5432/{DATABASE}"  # Uses psycopg3!
# collection_name = "my_docs"

# vector_store = PGVector(
#     embeddings=embedding_model,
#     collection_name=collection_name,
#     connection=connection,
#     use_jsonb=True,
# )

# collections = {}

# collections["collection_name"] = vector_store

# docs = [
#     Document(
#         page_content="there are cats in the pond",
#         metadata={"id": 1, "location": "pond", "topic": "animals"},
#     ),
#     Document(
#         page_content="ducks are also found in the pond",
#         metadata={"id": 2, "location": "pond", "topic": "animals"},
#     ),
#     Document(
#         page_content="fresh apples are available at the market",
#         metadata={"id": 3, "location": "market", "topic": "food"},
#     ),
#     Document(
#         page_content="the market also sells fresh oranges",
#         metadata={"id": 4, "location": "market", "topic": "food"},
#     ),
#     Document(
#         page_content="the new art exhibit is fascinating",
#         metadata={"id": 5, "location": "museum", "topic": "art"},
#     ),
#     Document(
#         page_content="a sculpture exhibit is also at the museum",
#         metadata={"id": 6, "location": "museum", "topic": "art"},
#     ),
#     Document(
#         page_content="a new coffee shop opened on Main Street",
#         metadata={"id": 7, "location": "Main Street", "topic": "food"},
#     ),
#     Document(
#         page_content="the book club meets at the library",
#         metadata={"id": 8, "location": "library", "topic": "reading"},
#     ),
#     Document(
#         page_content="the library hosts a weekly story time for kids",
#         metadata={"id": 9, "location": "library", "topic": "reading"},
#     ),
#     Document(
#         page_content="a cooking class for beginners is offered at the community center",
#         metadata={"id": 10, "location": "community center", "topic": "classes"},
#     ),
# ]

# results = vector_store.add_documents(docs, ids=[doc.metadata["id"] for doc in docs])
# print(f"add_documents return value: {results}")

# results = vector_store.delete(ids=["3"])
# print(f"delete return value: {results}")

# results = vector_store.similarity_search(
#     "kitty", k=10, filter={"id": {"$in": [1, 5, 2, 9]}}
# )
# print(
#     "Searching for the top 10 documents related to 'kitty', "
#     + "filtered by IDs [1, 5, 2, 9] "
# )
# for doc in results:
#     print(f"* {doc.page_content} [{doc.metadata}]")
#     # doc.page_content might look like: there are cats in the pond
#     # doc.metadata might look like: [{'id': 1, 'topic': 'animals', 'location': 'pond'}]

# # for filter dicts that don't start with an operator, $and is assumed
# results = vector_store.similarity_search(
#     "ducks",
#     k=10,
#     filter={"id": {"$in": [1, 5, 2, 9]}, "location": {"$in": ["pond", "market"]}},
# )
# print(
#     "Searching for the top 10 documents related to 'ducks', "
#     + "filtered by IDs [1, 5, 2, 9] "
#     + "and locations ['pond', 'market']."
# )
# for doc in results:
#     print(f"* {doc.page_content} [{doc.metadata}]")

# # this should return the same results as the above search
# results = vector_store.similarity_search(
#     "ducks",
#     k=10,
#     filter={
#         "$and": [
#             {"id": {"$in": [1, 5, 2, 9]}},
#             {"location": {"$in": ["pond", "market"]}},
#         ]
#     },
# )
# print(
#     "Searching for the top 10 documents related to 'ducks', "
#     + "filtered by IDs [1, 5, 2, 9] "
#     + "and locations ['pond', 'market']."
# )
# for doc in results:
#     print(f"* {doc.page_content} [{doc.metadata}]")

# query = "there are cats"  # "there are cats in the pond"
# top_n = 10
# results = vector_store.similarity_search_with_score(query=query, k=top_n)
# print(f"printing top {top_n} similarity score against query: {query}")
# for doc, score in results:
#     adjusted_score = max(0, 1 - score) * 100
#     print(f"* [SIM={adjusted_score:.1f}%] {doc.page_content} [{doc.metadata}]")

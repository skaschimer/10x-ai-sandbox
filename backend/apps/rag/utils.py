import asyncio
import os
import logging
import requests
import aiohttp

from typing import List, Union

from apps.ollama.main import (
    generate_ollama_embeddings,
    GenerateEmbeddingsForm,
)

from huggingface_hub import snapshot_download

from langchain_core.documents import Document
from langchain_community.retrievers import BM25Retriever
from langchain.retrievers import (
    ContextualCompressionRetriever,
    EnsembleRetriever,
)

from typing import Optional

from utils.misc import get_last_user_message, add_or_update_system_message
from config import SRC_LOG_LEVELS, CHROMA_CLIENT, VECTOR_CLIENT

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["RAG"])


async def query_doc(
    collection_name: str,
    query: str,
    embedding_function,
    k: int,
):
    try:
        # log.debug(f"Firing query_doc for collection_name {collection_name}")
        # collection = VECTOR_CLIENT.get_collection(
        #     name=collection_name
        # )  # Get the VectorCollection

        query_embeddings = await embedding_function(query)

        log.info(f"Query Embeddings length: {len(query_embeddings)}")

        has_collection = VECTOR_CLIENT.has_collection(collection_name)
        log.info(f"Has collection: {has_collection}")
        if not has_collection:
            log.error("Collection does not exist.")
            return None
        else:
            log.info("Collection exists!")

        return VECTOR_CLIENT.search(
            collection_name=collection_name,
            vectors=[query_embeddings],
            limit=k,
        )
    except Exception as e:
        log.error(f"query_doc: An exception occurred: {str(e)}")
        raise e


def query_doc_with_hybrid_search(
    collection_name: str,
    query: str,
    embedding_function,
    k: int,
    reranking_function,
    r: float,
):
    try:
        collection = CHROMA_CLIENT.get_collection(name=collection_name)
        documents = collection.get()  # get all documents

        bm25_retriever = BM25Retriever.from_texts(
            texts=documents.get("documents"),
            metadatas=documents.get("metadatas"),
        )
        bm25_retriever.k = k

        chroma_retriever = ChromaRetriever(
            collection=collection,
            embedding_function=embedding_function,
            top_n=k,
        )

        ensemble_retriever = EnsembleRetriever(
            retrievers=[bm25_retriever, chroma_retriever], weights=[0.5, 0.5]
        )

        compressor = RerankCompressor(
            embedding_function=embedding_function,
            top_n=k,
            reranking_function=reranking_function,
            r_score=r,
        )

        compression_retriever = ContextualCompressionRetriever(
            base_compressor=compressor, base_retriever=ensemble_retriever
        )

        result = compression_retriever.invoke(query)
        result = {
            "distances": [[d.metadata.get("score") for d in result]],
            "documents": [[d.page_content for d in result]],
            "metadatas": [[d.metadata for d in result]],
        }

        log.info(f"query_doc_with_hybrid_search:result {result}")
        return result
    except Exception as e:
        raise e


async def merge_and_sort_query_results(query_results, k, reverse=False):
    # Initialize lists to store combined data
    combined_distances = []
    combined_documents = []
    combined_metadatas = []

    log.error(f"query_results {query_results}")
    for query_result in query_results:
        combined_distances.extend(query_result["distances"])
        combined_documents.extend(query_result["documents"])
        combined_metadatas.extend(query_result["metadatas"])

    log.error(f"combined_distances {combined_distances}")
    # Create a list of tuples (distance, document, metadata)
    combined = list(zip(combined_distances, combined_documents, combined_metadatas))

    # Sort the list based on distances
    combined.sort(key=lambda x: x[0], reverse=reverse)

    # We don't have anything :-(
    if not combined:
        sorted_distances = []
        sorted_documents = []
        sorted_metadatas = []
    else:
        # Unzip the sorted list
        sorted_distances, sorted_documents, sorted_metadatas = zip(*combined)

        # Slicing the lists to include only k elements
        sorted_distances = list(sorted_distances)[:k]
        sorted_documents = list(sorted_documents)[:k]
        sorted_metadatas = list(sorted_metadatas)[:k]

    # Create the output dictionary
    result = {
        "distances": [sorted_distances],
        "documents": [sorted_documents],
        "metadatas": [sorted_metadatas],
    }

    return result


async def query_collection(
    collection_names: List[str],
    query: str,
    embedding_function,
    k: int,
):
    results = []
    for collection_name in collection_names:
        try:
            log.info(f"Firing query_collection for collection_name {collection_name}")
            result = await query_doc(
                collection_name=collection_name,
                query=query,
                k=k,
                embedding_function=embedding_function,
            )
            results.extend(result)
        except:
            pass
    return await merge_and_sort_query_results(results, k=k)


async def query_collection_with_hybrid_search(
    collection_names: List[str],
    query: str,
    embedding_function,
    k: int,
    reranking_function,
    r: float,
):
    results = []
    for collection_name in collection_names:
        try:
            result = query_doc_with_hybrid_search(
                collection_name=collection_name,
                query=query,
                embedding_function=embedding_function,
                k=k,
                reranking_function=reranking_function,
                r=r,
            )
            results.append(result)
        except:
            pass
    return await merge_and_sort_query_results(results, k=k, reverse=True)


def rag_template(template: str, context: str, query: str):
    template = template.replace("[context]", context)
    template = template.replace("[query]", query)
    return template


async def generate_openai_embeddings_async(
    model: str,
    text: Union[str, list[str]],
    key: str,
    url: str = "https://api.openai.com/v1",
):
    async with aiohttp.ClientSession() as session:
        if isinstance(text, list):
            embeddings = await generate_openai_batch_embeddings_async(
                model, text, key, url, session
            )
        else:
            embeddings = await generate_openai_batch_embeddings_async(
                model, [text], key, url, session
            )
        # log.error(
        #     f"embeddings: {embeddings[0] if isinstance(text, str) else embeddings}"
        # )
    return embeddings[0] if isinstance(text, str) else embeddings


async def generate_openai_batch_embeddings_async(
    model: str, texts: list[str], key: str, url: str, session: aiohttp.ClientSession
) -> Optional[list[list[float]]]:
    try:
        if "azure.com" in url:
            initial_delay = 0.2
            max_retries = 10
            attempt = 0
            retry_delay = initial_delay  # Start with the initial delay

            while attempt <= max_retries:
                log.info(
                    f"Generating async OpenAI embeddings for {texts[0][0:25]}..."
                    + f"(Attempt {attempt + 1}/{max_retries + 1})"
                )
                async with session.post(
                    f"{url}/embeddings?api-version=2023-05-15",
                    headers={
                        "Content-Type": "application/json",
                        "api-key": f"{key}",
                    },
                    json={"input": texts, "model": model},
                ) as response:
                    if response.status == 429:
                        if attempt < max_retries:
                            log.warning(
                                f"Received 429 Too Many Requests. Retrying after {retry_delay:.2f} seconds..."
                            )
                            await asyncio.sleep(retry_delay)
                            attempt += 1
                            retry_delay *= 2
                            continue
                        else:
                            log.error(
                                "Max retries exceeded after receiving 429 Too Many Requests."
                            )
                            raise Exception(
                                "429 Too Many Requests: Maximum retries exceeded."
                            )
                    elif response.status != 200:
                        response.raise_for_status()

                    data = await response.json()
                    if "data" in data:
                        return [elem["embedding"] for elem in data["data"]]
                    else:
                        raise Exception("Something went wrong :/")

            raise Exception("The request failed after several retries.")
        else:
            log.info(
                f"Generating async Azure OpenAI embeddings for {texts[0][0:25]}..."
            )
            async with session.post(
                f"{url}/embeddings",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {key}",
                },
                json={"input": texts, "model": model},
            ) as response:
                response.raise_for_status()
                data = await response.json()
                if "data" in data:
                    return [elem["embedding"] for elem in data["data"]]
                else:
                    raise Exception("Something went wrong :/")

    except Exception as e:
        print(e)
        return None


def get_embedding_function(
    embedding_engine,
    embedding_model,
    embedding_function,
    openai_key,
    openai_url,
    batch_size,
):
    print(f"Getting embedding function for {embedding_engine} & {embedding_model}")
    embedding_engine = str(embedding_engine).strip()
    if embedding_engine == "":
        print(f"No engine for {embedding_engine} & {embedding_model}")
        return lambda query: embedding_function.encode(query).tolist()
    elif embedding_engine in ["ollama", "openai"]:
        print(
            f"found openai getting embedding function for {embedding_engine} & {embedding_model}"
        )
        if embedding_engine == "ollama":
            func = lambda query: generate_ollama_embeddings(
                GenerateEmbeddingsForm(
                    **{
                        "model": embedding_model,
                        "prompt": query,
                    }
                )
            )
        elif embedding_engine == "openai":
            print(
                f"found openai again etting embedding function for {embedding_engine} & {embedding_model}"
            )
            print("OpenAI embeddings are being generated.")
            func = lambda query: generate_openai_embeddings_async(
                model=embedding_model,
                text=query,
                key=openai_key,
                url=openai_url,
            )

        async def generate_multiple(query, f):
            if isinstance(query, list):
                if embedding_engine == "openai":
                    tasks = []
                    for i in range(0, len(query), batch_size):
                        tasks.append(f(query[i : i + batch_size]))
                    embeddings = await asyncio.gather(*tasks)
                    return [item for sublist in embeddings for item in sublist]
                else:
                    tasks = [f(q) for q in query]
                    return await asyncio.gather(*tasks)
            else:
                return await f(query)

        return lambda query: generate_multiple(query, func)

    else:
        raise Exception(f"Unknown embedding engine: {embedding_engine}")


async def get_rag_context(
    docs,
    messages,
    embedding_function,
    k,
    reranking_function,
    r,
    hybrid_search,
):
    log.info(f"Starting get_rag_context with {len(docs)} docs")

    query = get_last_user_message(messages)
    log.info(f"Extracted query: {query}")

    extracted_collections = []
    relevant_contexts = []

    log.info(f"Processing {len(docs)} documents")
    for idx, doc in enumerate(docs):
        log.info(f"Processing document {idx+1}/{len(docs)}")
        context = None

        collection_names = (
            doc["collection_names"]
            if doc["type"] == "collection"
            else [doc["collection_name"]]
        )
        log.info(f"Collection names for current doc: {collection_names}")

        collection_names = set(collection_names).difference(extracted_collections)
        log.debug(
            f"Filtered collection names (removing already extracted): {collection_names}"
        )

        if not collection_names:
            log.info(f"Skipping doc {idx+1} - collections already processed")
            continue

        try:
            if doc["type"] == "text":
                log.info("Processing text type document")
                context = doc["content"]
                log.debug(f"Text content: {context[:100]}...")
            else:
                log.info("Processing collection type document")
                if hybrid_search:
                    log.info("Using hybrid search")
                    context = await query_collection_with_hybrid_search(
                        collection_names=collection_names,
                        query=query,
                        embedding_function=embedding_function,
                        k=k,
                        reranking_function=reranking_function,
                        r=r,
                    )
                else:
                    log.info("Using regular search")
                    context = await query_collection(
                        collection_names=collection_names,
                        query=query,
                        embedding_function=embedding_function,
                        k=k,
                    )
        except Exception as e:
            log.error(f"Error processing document {idx+1}: {str(e)}")
            log.exception(e)
            context = None

        if context:
            log.info(f"Adding context from doc {idx+1} to relevant contexts")
            relevant_contexts.append({**context, "source": doc})
        else:
            log.warning(f"No context found for doc {idx+1}")

        extracted_collections.extend(collection_names)
        log.debug(f"Updated extracted collections: {extracted_collections}")

    log.info(
        f"Processing {len(relevant_contexts)} relevant contexts to build final string"
    )
    context_string = ""
    citations = []

    for idx, context in enumerate(relevant_contexts):
        log.info(f"Processing context {idx+1}/{len(relevant_contexts)}")
        # log.debug(f"Current context: {context}")
        try:
            if "documents" in context:
                # log.debug(f"Context documents: {context['documents']}")
                texts = [text for text in context["documents"][0] if text is not None]
                # log.debug(f"Found texts: {texts}")
                context_string += "\n\n".join(texts)

                if "metadatas" in context:
                    log.info("Adding citation from metadata")
                    log.info(f"Metadata: {context['metadatas']}")
                    citation = {
                        "source": context["source"],
                        "document": context["documents"][0],
                        "metadata": context["metadatas"][0],
                    }
                    citations.append(citation)
                log.info(f"Updated context string: {context_string[:100]}...")
                log.debug(f"Updated citations: {citations}")
            else:
                log.info("No documents in context")
        except Exception as e:
            log.error(f"Error processing context {idx+1}: {str(e)}")
            log.exception(e)

    context_string = context_string.strip()

    return context_string, citations


def get_model_path(model: str, update_model: bool = False):
    # Construct huggingface_hub kwargs with local_files_only to return the snapshot path
    cache_dir = os.getenv("SENTENCE_TRANSFORMERS_HOME")

    local_files_only = not update_model

    snapshot_kwargs = {
        "cache_dir": cache_dir,
        "local_files_only": local_files_only,
    }

    log.debug(f"model: {model}")
    log.debug(f"snapshot_kwargs: {snapshot_kwargs}")

    # Inspiration from upstream sentence_transformers
    if (
        os.path.exists(model)
        or ("\\" in model or model.count("/") > 1)
        and local_files_only
    ):
        # If fully qualified path exists, return input, else set repo_id
        return model
    elif "/" not in model:
        # Set valid repo_id for model short-name
        model = "sentence-transformers" + "/" + model

    snapshot_kwargs["repo_id"] = model
    snapshot_kwargs["local_files_only"] = False

    # Attempt to query the huggingface_hub library to determine the local path and/or to update
    try:
        model_repo_path = snapshot_download(**snapshot_kwargs)
        log.debug(f"model_repo_path: {model_repo_path}")
        return model_repo_path
    except Exception as e:
        log.exception(f"Cannot determine model snapshot path: {e}")
        return model


def generate_openai_embeddings(
    model: str,
    text: Union[str, list[str]],
    key: str,
    url: str = "https://api.openai.com/v1",
):
    if isinstance(text, list):
        embeddings = generate_openai_batch_embeddings(model, text, key, url)
    else:
        embeddings = generate_openai_batch_embeddings(model, [text], key, url)

    return embeddings[0] if isinstance(text, str) else embeddings


def generate_openai_batch_embeddings(
    model: str, texts: list[str], key: str, url: str = "https://api.openai.com/v1"
) -> Optional[list[list[float]]]:
    try:
        log.info(f"Generating OpenAI embeddings for {texts[0][0:25]}...")
        r = requests.post(
            f"{url}/embeddings",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
            },
            json={"input": texts, "model": model},
        )
        r.raise_for_status()
        data = r.json()
        if "data" in data:
            return [elem["embedding"] for elem in data["data"]]
        else:
            raise "Something went wrong :/"
    except Exception as e:
        print(e)
        return None


from typing import Any

from langchain_core.retrievers import BaseRetriever
from langchain_core.callbacks import CallbackManagerForRetrieverRun


class ChromaRetriever(BaseRetriever):
    collection: Any
    embedding_function: Any
    top_n: int

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> List[Document]:
        query_embeddings = self.embedding_function(query)

        results = self.collection.query(
            query_embeddings=[query_embeddings],
            n_results=self.top_n,
        )

        ids = results["ids"][0]
        metadatas = results["metadatas"][0]
        documents = results["documents"][0]

        results = []
        for idx in range(len(ids)):
            results.append(
                Document(
                    metadata=metadatas[idx],
                    page_content=documents[idx],
                )
            )
        return results


import operator

from typing import Optional, Sequence

from langchain_core.documents import BaseDocumentCompressor, Document
from langchain_core.callbacks import Callbacks
from langchain_core.pydantic_v1 import Extra

from sentence_transformers import util


class RerankCompressor(BaseDocumentCompressor):
    embedding_function: Any
    top_n: int
    reranking_function: Any
    r_score: float

    class Config:
        extra = Extra.forbid
        arbitrary_types_allowed = True

    def compress_documents(
        self,
        documents: Sequence[Document],
        query: str,
        callbacks: Optional[Callbacks] = None,
    ) -> Sequence[Document]:
        reranking = self.reranking_function is not None

        if reranking:
            scores = self.reranking_function.predict(
                [(query, doc.page_content) for doc in documents]
            )
        else:
            query_embedding = self.embedding_function(query)
            document_embedding = self.embedding_function(
                [doc.page_content for doc in documents]
            )
            scores = util.cos_sim(query_embedding, document_embedding)[0]

        docs_with_scores = list(zip(documents, scores.tolist()))
        if self.r_score:
            docs_with_scores = [
                (d, s) for d, s in docs_with_scores if s >= self.r_score
            ]

        result = sorted(docs_with_scores, key=operator.itemgetter(1), reverse=True)
        final_results = []
        for doc, doc_score in result[: self.top_n]:
            metadata = doc.metadata
            metadata["score"] = doc_score
            doc = Document(
                page_content=doc.page_content,
                metadata=metadata,
            )
            final_results.append(doc)
        return final_results

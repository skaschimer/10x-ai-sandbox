import time
import structlog
import sys

import asyncio
from aiocache import cached
from typing import Any, Optional
import random
import json
import inspect
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor


from fastapi import Request
from fastapi import BackgroundTasks

from starlette.responses import Response, StreamingResponse


from open_webui.models.chats import Chats
from open_webui.models.users import Users
from open_webui.socket.main import (
    get_event_call,
    get_event_emitter,
    get_active_status_by_user_id,
)
from open_webui.routers.tasks import (
    generate_queries,
    generate_title,
    generate_chat_tags,
)
from open_webui.routers.retrieval import process_web_search, SearchForm
from open_webui.utils.webhook import post_webhook


from open_webui.models.users import UserModel
from open_webui.models.functions import Functions
from open_webui.models.models import Models

from open_webui.retrieval.utils import get_sources_from_files


from open_webui.utils.chat import generate_chat_completion
from open_webui.utils.task import (
    get_task_model_id,
    rag_template,
    tools_function_calling_generation_template,
)
from open_webui.utils.misc import (
    get_message_list,
    add_or_update_system_message,
    get_last_user_message,
    get_last_assistant_message,
    prepend_to_first_user_message_content,
)
from open_webui.utils.tools import get_tools
from open_webui.utils.plugin import load_function_module_by_id


from open_webui.tasks import create_task

from open_webui.config import config
from open_webui.env import (
    SRC_LOG_LEVELS,
    GLOBAL_LOG_LEVEL,
    BYPASS_MODEL_ACCESS_CONTROL,
    ENABLE_REALTIME_CHAT_SAVE,
)
from open_webui.constants import TASKS


log = structlog.get_logger(__name__)


def generate_fall_back_title(messages):
    if not messages:
        return "New Chat"
    user_message = None
    for message in messages:
        if message.get("role") == "user":
            user_message = message.get("content", "").strip()
            break
    if not user_message:
        return "New Chat"

    if len(user_message) > 30:
        return user_message[:27] + "..."
    return user_message


async def chat_completion_filter_functions_handler(request, body, model, extra_params):
    skip_files = None

    def get_filter_function_ids(model):
        def get_priority(function_id):
            function = Functions.get_function_by_id(function_id)
            if function is not None and hasattr(function, "valves"):
                # TODO: Fix FunctionModel
                return (function.valves if function.valves else {}).get("priority", 0)
            return 0

        filter_ids = [
            function.id for function in Functions.get_global_filter_functions()
        ]
        if "info" in model and "meta" in model["info"]:
            filter_ids.extend(model["info"]["meta"].get("filterIds", []))
            filter_ids = list(set(filter_ids))

        enabled_filter_ids = [
            function.id
            for function in Functions.get_functions_by_type("filter", active_only=True)
        ]

        filter_ids = [
            filter_id for filter_id in filter_ids if filter_id in enabled_filter_ids
        ]

        filter_ids.sort(key=get_priority)
        return filter_ids

    filter_ids = get_filter_function_ids(model)
    for filter_id in filter_ids:
        filter = Functions.get_function_by_id(filter_id)
        if not filter:
            continue

        if filter_id in request.app.state.FUNCTIONS:
            function_module = request.app.state.FUNCTIONS[filter_id]
        else:
            function_module, _, _ = load_function_module_by_id(filter_id)
            request.app.state.FUNCTIONS[filter_id] = function_module

        # Check if the function has a file_handler variable
        if hasattr(function_module, "file_handler"):
            skip_files = function_module.file_handler

        # Apply valves to the function
        if hasattr(function_module, "valves") and hasattr(function_module, "Valves"):
            valves = Functions.get_function_valves_by_id(filter_id)
            function_module.valves = function_module.Valves(
                **(valves if valves else {})
            )

        if hasattr(function_module, "inlet"):
            try:
                inlet = function_module.inlet

                # Create a dictionary of parameters to be passed to the function
                params = {"body": body} | {
                    k: v
                    for k, v in {
                        **extra_params,
                        "__model__": model,
                        "__id__": filter_id,
                    }.items()
                    if k in inspect.signature(inlet).parameters
                }

                if "__user__" in params and hasattr(function_module, "UserValves"):
                    try:
                        params["__user__"]["valves"] = function_module.UserValves(
                            **Functions.get_user_valves_by_id_and_user_id(
                                filter_id, params["__user__"]["id"]
                            )
                        )
                    except Exception as e:
                        print(e)

                if inspect.iscoroutinefunction(inlet):
                    body = await inlet(**params)
                else:
                    body = inlet(**params)

            except Exception as e:
                print(f"Error: {e}")
                raise e

    if skip_files and "files" in body.get("metadata", {}):
        del body["metadata"]["files"]

    return body, {}


async def chat_completion_tools_handler(
    request: Request, body: dict, user: UserModel, models, extra_params: dict
) -> tuple[dict, dict]:
    async def get_content_from_response(response) -> Optional[str]:
        content = None
        if hasattr(response, "body_iterator"):
            async for chunk in response.body_iterator:
                data = json.loads(chunk.decode("utf-8"))
                content = data["choices"][0]["message"]["content"]

            # Cleanup any remaining background tasks if necessary
            if response.background is not None:
                await response.background()
        else:
            content = response["choices"][0]["message"]["content"]
        return content

    def get_tools_function_calling_payload(messages, task_model_id, content):
        user_message = get_last_user_message(messages)
        history = "\n".join(
            f"{message['role'].upper()}: \"\"\"{message['content']}\"\"\""
            for message in messages[::-1][:4]
        )

        prompt = f"History:\n{history}\nQuery: {user_message}"

        return {
            "model": task_model_id,
            "messages": [
                {"role": "system", "content": content},
                {"role": "user", "content": f"Query: {prompt}"},
            ],
            "stream": False,
            "metadata": {"task": str(TASKS.FUNCTION_CALLING)},
        }

    # If tool_ids field is present, call the functions
    metadata = body.get("metadata", {})

    tool_ids = metadata.get("tool_ids", None)
    log.debug("chat_completion_tools_handler:tool_ids", tool_ids=tool_ids)
    if not tool_ids:
        return body, {}

    skip_files = False
    sources = []

    task_model_id = get_task_model_id(
        body["model"],
        request.app.state.config.TASK_MODEL,
        request.app.state.config.TASK_MODEL_EXTERNAL,
        models,
    )
    tools = get_tools(
        request,
        tool_ids,
        user,
        {
            **extra_params,
            "__model__": models[task_model_id],
            "__messages__": body["messages"],
            "__files__": metadata.get("files", []),
        },
    )
    log.debug("chat_completion_tools_handler:tools", tools=tools)

    specs = [tool["spec"] for tool in tools.values()]
    tools_specs = json.dumps(specs)

    if request.app.state.config.TOOLS_FUNCTION_CALLING_PROMPT_TEMPLATE != "":
        template = request.app.state.config.TOOLS_FUNCTION_CALLING_PROMPT_TEMPLATE
    else:
        template = config.DEFAULT_TOOLS_FUNCTION_CALLING_PROMPT_TEMPLATE

    tools_function_calling_prompt = tools_function_calling_generation_template(
        template, tools_specs
    )
    log.debug(
        "chat_completion_tools_handler:tools_function_calling_prompt",
        tools_function_calling_prompt=tools_function_calling_prompt,
    )
    payload = get_tools_function_calling_payload(
        body["messages"], task_model_id, tools_function_calling_prompt
    )

    try:
        response = await generate_chat_completion(request, form_data=payload, user=user)
        log.debug(
            "chat_completion_tools_handler:generated_chat_completion", response=response
        )
        content = await get_content_from_response(response)
        log.debug(
            "chat_completion_tools_handler:content_from_response", content=content
        )

        if not content:
            return body, {}

        try:
            content = content[content.find("{") : content.rfind("}") + 1]
            if not content:
                log.error(
                    "chat_completion_tools_handler:bad_content_no_json", content=content
                )
                raise Exception("No JSON object found in the response")

            result = json.loads(content)

            tool_function_name = result.get("name", None)
            if tool_function_name not in tools:
                return body, {}

            tool_function_params = result.get("parameters", {})

            try:
                required_params = (
                    tools[tool_function_name]
                    .get("spec", {})
                    .get("parameters", {})
                    .get("required", [])
                )
                tool_function = tools[tool_function_name]["callable"]
                tool_function_params = {
                    k: v
                    for k, v in tool_function_params.items()
                    if k in required_params
                }
                tool_output = await tool_function(**tool_function_params)

            except Exception as e:
                log.exception(
                    "chat_completion_tools_handler:tools_parsing_error", exc_info=e
                )
                tool_output = str(e)

            if isinstance(tool_output, str):
                if tools[tool_function_name]["citation"]:
                    sources.append(
                        {
                            "source": {
                                "name": f"TOOL:{tools[tool_function_name]['toolkit_id']}/{tool_function_name}"
                            },
                            "document": [tool_output],
                            "metadata": [
                                {
                                    "source": f"TOOL:{tools[tool_function_name]['toolkit_id']}/{tool_function_name}"
                                }
                            ],
                        }
                    )
                else:
                    sources.append(
                        {
                            "source": {},
                            "document": [tool_output],
                            "metadata": [
                                {
                                    "source": f"TOOL:{tools[tool_function_name]['toolkit_id']}/{tool_function_name}"
                                }
                            ],
                        }
                    )

                if tools[tool_function_name]["file_handler"]:
                    skip_files = True

        except Exception as e:
            log.exception(
                "chat_completion_tools_handler:tool_execution_error", exc_info=e
            )
            content = None
    except Exception as e:
        log.exception("chat_completion_tools_handler:error", exc_info=e)
        content = None

    log.debug("chat_completion_tools_handler:tool_sources", sources=sources)

    if skip_files and "files" in body.get("metadata", {}):
        del body["metadata"]["files"]

    return body, {"sources": sources}


async def chat_web_search_handler(
    request: Request, form_data: dict, extra_params: dict, user
):
    log.debug("chat_web_search_handler", form_data=form_data, user=user.email)

    event_emitter = extra_params["__event_emitter__"]
    await event_emitter(
        {
            "type": "status",
            "data": {
                "action": "web_search",
                "description": "Generating search query",
                "done": False,
            },
        }
    )

    messages = form_data["messages"]
    user_message = get_last_user_message(messages)

    log.debug(
        "chat_web_search_handler:check_messages",
        messages=messages,
        user_message=user_message,
    )

    queries = []
    try:
        log.debug("chat_web_search_handler:check_form_data", form_data=form_data)
        res = await generate_queries(
            request,
            {
                "model": form_data["model"],
                "messages": messages,
                "prompt": user_message,
                "type": "web_search",
            },
            user,
        )

        log.debug(
            "chat_web_search_handler:check_generate_queries_response",
            res=res,
        )

        response = res["choices"][0]["message"]["content"]

        try:
            bracket_start = response.find("{")
            bracket_end = response.rfind("}") + 1

            if bracket_start == -1 or bracket_end == -1:
                log.error(
                    "chat_web_search_handler:bad_response_no_json", response=response
                )
                raise Exception("No JSON object found in the response")

            response = response[bracket_start:bracket_end]
            queries = json.loads(response)
            queries = queries.get("queries", [])
            log.debug(
                "chat_web_search_handler:check_queries",
                queries=queries,
            )
        except Exception as e:
            queries = [response]

    except Exception as e:
        log.exception(
            "chat_web_search_handler:exception_generating_queries", exc_info=e
        )
        queries = [user_message]

    if len(queries) == 0:
        log.info("chat_web_search_handler:no_queries_generated")
        await event_emitter(
            {
                "type": "status",
                "data": {
                    "action": "web_search",
                    "description": "No search query generated",
                    "done": True,
                },
            }
        )
        return form_data

    searchQuery = queries[0]

    await event_emitter(
        {
            "type": "status",
            "data": {
                "action": "web_search",
                "description": 'Searching "{{searchQuery}}"',
                "query": searchQuery,
                "done": False,
            },
        }
    )

    try:

        # Offload process_web_search to a separate thread
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor() as executor:
            log.debug("chat_web_search_handler:running_search_query", query=searchQuery)
            results = await loop.run_in_executor(
                executor,
                lambda: process_web_search(
                    request,
                    SearchForm(
                        **{
                            "query": searchQuery,
                        }
                    ),
                    user,
                ),
            )

        if results:
            log.debug("chat_web_search_handler:results_found", results=results)
            await event_emitter(
                {
                    "type": "status",
                    "data": {
                        "action": "web_search",
                        "description": "Searched {{count}} sites",
                        "query": searchQuery,
                        "urls": results["filenames"],
                        "done": True,
                    },
                }
            )

            files = form_data.get("files", [])
            files.append(
                {
                    "collection_name": results["collection_name"],
                    "name": searchQuery,
                    "type": "web_search_results",
                    "urls": results["filenames"],
                }
            )
            form_data["files"] = files
        else:
            log.debug("chat_web_search_handler:no_results_found", results=results)
            await event_emitter(
                {
                    "type": "status",
                    "data": {
                        "action": "web_search",
                        "description": "No search results found",
                        "query": searchQuery,
                        "done": True,
                        "error": True,
                    },
                }
            )
    except Exception as e:
        log.exception("chat_web_search_handler:error", exc_info=e)
        await event_emitter(
            {
                "type": "status",
                "data": {
                    "action": "web_search",
                    "description": 'Error searching "{{searchQuery}}"',
                    "query": searchQuery,
                    "done": True,
                    "error": True,
                },
            }
        )

    log.debug("chat_web_search_handler:form_data_result", form_data=form_data)

    return form_data


async def chat_completion_files_handler(
    request: Request, body: dict, user: UserModel
) -> tuple[dict, dict[str, list]]:
    sources = []

    if files := body.get("metadata", {}).get("files", None):
        log.debug("chat_completion_files_handler:files_found", files=files)
        try:
            queries_response = await generate_queries(
                request,
                {
                    "model": body["model"],
                    "messages": body["messages"],
                    "type": "retrieval",
                },
                user,
            )
            queries_response = queries_response["choices"][0]["message"]["content"]

            try:
                bracket_start = queries_response.find("{")
                bracket_end = queries_response.rfind("}") + 1

                if bracket_start == -1 or bracket_end == -1:
                    raise Exception("No JSON object found in the response")

                queries_response = queries_response[bracket_start:bracket_end]
                queries_response = json.loads(queries_response)
            except Exception as e:
                log.exception(
                    "chat_completion_files_handler:parsing_error",
                    queries_response=queries_response,
                    exc_info=e,
                )
                queries_response = {"queries": [queries_response]}

            queries = queries_response.get("queries", [])
        except Exception as e:
            log.exception("chat_completion_files_handler:error", exc_info=e)
            queries = []

        if len(queries) == 0:
            queries = [get_last_user_message(body["messages"])]

        sources = get_sources_from_files(
            files=files,
            queries=queries,
            embedding_function=request.app.state.EMBEDDING_FUNCTION,
            k=request.app.state.config.RAG_TOP_K,
            reranking_function=request.app.state.rf,
            r=request.app.state.config.RAG_RELEVANCE_THRESHOLD,
            hybrid_search=request.app.state.config.ENABLE_RAG_HYBRID_SEARCH,
        )

        log.debug("chat_completion_files_handler:sources", sources=sources)
    return body, {"sources": sources}


def apply_params_to_form_data(form_data, model):
    log.debug("apply_params_to_form_data", form_data=form_data, model=model)

    params = form_data.pop("params", {})
    if model.get("ollama"):
        form_data["options"] = params

        if "format" in params:
            form_data["format"] = params["format"]

        if "keep_alive" in params:
            form_data["keep_alive"] = params["keep_alive"]
    else:
        if "seed" in params:
            form_data["seed"] = params["seed"]

        if "stop" in params:
            form_data["stop"] = params["stop"]

        if "temperature" in params:
            form_data["temperature"] = params["temperature"]

        if "top_p" in params:
            form_data["top_p"] = params["top_p"]

        if "frequency_penalty" in params:
            form_data["frequency_penalty"] = params["frequency_penalty"]
    return form_data


async def process_chat_payload(request, form_data, metadata, user, model):
    log.debug("process_chat_payload", form_data=form_data, user=user.email, model=model)
    form_data = apply_params_to_form_data(form_data, model)

    event_emitter = get_event_emitter(metadata)
    event_call = get_event_call(metadata)

    extra_params = {
        "__event_emitter__": event_emitter,
        "__event_call__": event_call,
        "__user__": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "role": user.role,
        },
        "__metadata__": metadata,
        "__request__": request,
    }

    # Initialize events to store additional event to be sent to the client
    # Initialize contexts and citation
    models = request.app.state.MODELS

    events = []
    sources = []

    user_message = get_last_user_message(form_data["messages"])
    model_knowledge = model.get("info", {}).get("meta", {}).get("knowledge", False)

    if model_knowledge:
        await event_emitter(
            {
                "type": "status",
                "data": {
                    "action": "knowledge_search",
                    "query": user_message,
                    "done": False,
                },
            }
        )

        knowledge_files = []
        for item in model_knowledge:
            if item.get("collection_name"):
                knowledge_files.append(
                    {
                        "id": item.get("collection_name"),
                        "name": item.get("name"),
                        "legacy": True,
                    }
                )
            elif item.get("collection_names"):
                knowledge_files.append(
                    {
                        "name": item.get("name"),
                        "type": "collection",
                        "collection_names": item.get("collection_names"),
                        "legacy": True,
                    }
                )
            else:
                knowledge_files.append(item)

        files = form_data.get("files", [])
        files.extend(knowledge_files)
        form_data["files"] = files

    features = form_data.pop("features", None)
    if features:
        log.debug("process_chat_payload:found_features", features=features)
        if "web_search" in features and features["web_search"]:
            web_search_result = await chat_web_search_handler(
                request, form_data, extra_params, user
            )
            if web_search_result is not None:
                form_data = web_search_result
            log.debug("process_chat_payload:processed_web_search", form_data=form_data)

    try:
        form_data, flags = await chat_completion_filter_functions_handler(
            request, form_data, model, extra_params
        )
        log.debug(
            "process_chat_payload:from_filter_functions_handler",
            form_data=form_data,
            flags=flags,
        )
    except Exception as e:
        log.exception("process_chat_payload:filter_functions_handler_error", exc_info=e)
        return Exception(f"Error: {e}")

    tool_ids = form_data.pop("tool_ids", None)
    files = form_data.pop("files", None)
    # Remove files duplicates
    if files:
        files = list({json.dumps(f, sort_keys=True): f for f in files}.values())

    metadata = {
        **metadata,
        "tool_ids": tool_ids,
        "files": files,
    }
    form_data["metadata"] = metadata

    try:
        form_data, flags = await chat_completion_tools_handler(
            request, form_data, user, models, extra_params
        )
        sources.extend(flags.get("sources", []))
        log.debug(
            "process_chat_payload:from_tools_handler", form_data=form_data, flags=flags
        )
    except Exception as e:
        log.exception("process_chat_payload:tools_handler_error", exc_info=e)

    try:
        form_data, flags = await chat_completion_files_handler(request, form_data, user)
        sources.extend(flags.get("sources", []))
    except Exception as e:
        log.exception("process_chat_payload:files_handler_error", exc_info=e)

    # If context is not empty, insert it into the messages
    if len(sources) > 0:
        context_string = ""
        for source_idx, source in enumerate(sources):
            source_id = source.get("source", {}).get("name", "")

            if "document" in source:
                for doc_idx, doc_context in enumerate(source["document"]):
                    metadata = source.get("metadata")
                    doc_source_id = None

                    if metadata:
                        doc_source_id = metadata[doc_idx].get("source", source_id)

                    if source_id:
                        context_string += f"<source><source_id>{doc_source_id if doc_source_id is not None else source_id}</source_id><source_context>{doc_context}</source_context></source>\n"
                    else:
                        # If there is no source_id, then do not include the source_id tag
                        context_string += f"<source><source_context>{doc_context}</source_context></source>\n"

        context_string = context_string.strip()
        prompt = get_last_user_message(form_data["messages"])

        if prompt is None:
            log.error("process_chat_payload:no_user_message", form_data=form_data)
            raise Exception("No user message found")
        if (
            request.app.state.config.RAG_RELEVANCE_THRESHOLD == 0
            and context_string.strip() == ""
        ):
            log.debug(
                "With a 0 relevancy threshold for RAG, the context cannot be empty"
            )

        # Workaround for Ollama 2.0+ system prompt issue
        # TODO: replace with add_or_update_system_message
        if model["owned_by"] == "ollama":
            form_data["messages"] = prepend_to_first_user_message_content(
                rag_template(
                    request.app.state.config.RAG_TEMPLATE, context_string, prompt
                ),
                form_data["messages"],
            )
        else:
            form_data["messages"] = add_or_update_system_message(
                rag_template(
                    request.app.state.config.RAG_TEMPLATE, context_string, prompt
                ),
                form_data["messages"],
            )

    # If there are citations, add them to the data_items
    sources = [source for source in sources if source.get("source", {}).get("name", "")]

    if len(sources) > 0:
        events.append({"sources": sources})

    if model_knowledge:
        await event_emitter(
            {
                "type": "status",
                "data": {
                    "action": "knowledge_search",
                    "query": user_message,
                    "done": True,
                    "hidden": True,
                },
            }
        )

    return form_data, events


async def process_chat_response(
    request, response, form_data, user, events, metadata, tasks
):
    log.debug("process_chat_response")

    async def background_tasks_handler():
        message_map = Chats.get_messages_by_chat_id(metadata["chat_id"])
        message = message_map.get(metadata["message_id"]) if message_map else None

        if message:
            messages = get_message_list(message_map, message.get("id"))

            if tasks:
                if TASKS.TITLE_GENERATION in tasks:
                    if tasks[TASKS.TITLE_GENERATION]:
                        res = await generate_title(
                            request,
                            {
                                "model": message["model"],
                                "messages": messages,
                                "chat_id": metadata["chat_id"],
                            },
                            user,
                        )

                        if res and isinstance(res, dict):
                            title = (
                                res.get("choices", [])[0]
                                .get("message", {})
                                .get(
                                    "content",
                                    message.get("content", "New Chat"),
                                )
                            ).strip()

                            # if title using error message
                            if "## Oops!" in title:
                                title = generate_fall_back_title(messages)

                            if not title:
                                title = generate_fall_back_title(messages)

                            Chats.update_chat_title_by_id(metadata["chat_id"], title)

                            await event_emitter(
                                {
                                    "type": "chat:title",
                                    "data": title,
                                }
                            )
                    elif len(messages) == 2:
                        title = generate_fall_back_title(messages)

                        Chats.update_chat_title_by_id(metadata["chat_id"], title)

                        await event_emitter({"type": "chat:title", "data": title})

                if TASKS.TAGS_GENERATION in tasks and tasks[TASKS.TAGS_GENERATION]:
                    res = await generate_chat_tags(
                        request,
                        {
                            "model": message["model"],
                            "messages": messages,
                            "chat_id": metadata["chat_id"],
                        },
                        user,
                    )

                    if res and isinstance(res, dict):
                        tags_string = (
                            res.get("choices", [])[0]
                            .get("message", {})
                            .get("content", "")
                        )

                        tags_string = tags_string[
                            tags_string.find("{") : tags_string.rfind("}") + 1
                        ]

                        try:
                            tags = json.loads(tags_string).get("tags", [])
                            Chats.update_chat_tags_by_id(
                                metadata["chat_id"], tags, user
                            )

                            await event_emitter(
                                {
                                    "type": "chat:tags",
                                    "data": tags,
                                }
                            )
                        except Exception as e:
                            log.exception(
                                "process_chat_response:background_tasks_handler:error",
                                exc_info=e,
                            )

    event_emitter = None
    if (
        "session_id" in metadata
        and metadata["session_id"]
        and "chat_id" in metadata
        and metadata["chat_id"]
        and "message_id" in metadata
        and metadata["message_id"]
    ):
        event_emitter = get_event_emitter(metadata)

    if not isinstance(response, StreamingResponse):
        if event_emitter:

            if "selected_model_id" in response:
                Chats.upsert_message_to_chat_by_id_and_message_id(
                    metadata["chat_id"],
                    metadata["message_id"],
                    {
                        "selectedModelId": response["selected_model_id"],
                    },
                )

            if response.get("choices", [])[0].get("message", {}).get("content"):
                content = response["choices"][0]["message"]["content"]

                if content:

                    await event_emitter(
                        {
                            "type": "chat:completion",
                            "data": response,
                        }
                    )

                    title = Chats.get_chat_title_by_id(metadata["chat_id"])

                    await event_emitter(
                        {
                            "type": "chat:completion",
                            "data": {
                                "done": True,
                                "content": content,
                                "title": title,
                            },
                        }
                    )

                    # Save message in the database
                    Chats.upsert_message_to_chat_by_id_and_message_id(
                        metadata["chat_id"],
                        metadata["message_id"],
                        {
                            "content": content,
                        },
                    )

                    # Send a webhook notification if the user is not active
                    if get_active_status_by_user_id(user.id) is None:
                        webhook_url = Users.get_user_webhook_url_by_id(user.id)
                        if webhook_url:
                            post_webhook(
                                webhook_url,
                                f"{title} - {request.app.state.config.WEBUI_URL}/c/{metadata['chat_id']}\n\n{content}",
                                {
                                    "action": "chat",
                                    "message": content,
                                    "title": title,
                                    "url": f"{request.app.state.config.WEBUI_URL}/c/{metadata['chat_id']}",
                                },
                            )

                    await background_tasks_handler()

            return response
        else:
            return response

    if not any(
        content_type in response.headers["Content-Type"]
        for content_type in ["text/event-stream", "application/x-ndjson"]
    ):
        return response

    if event_emitter:

        task_id = str(uuid4())  # Create a unique task ID.

        # Handle as a background task
        async def post_response_handler(response, events):
            message = Chats.get_message_by_id_and_message_id(
                metadata["chat_id"], metadata["message_id"]
            )
            content = message.get("content", "") if message else ""

            try:
                for event in events:
                    await event_emitter(
                        {
                            "type": "chat:completion",
                            "data": event,
                        }
                    )

                    # Save message in the database
                    Chats.upsert_message_to_chat_by_id_and_message_id(
                        metadata["chat_id"],
                        metadata["message_id"],
                        {
                            **event,
                        },
                    )

                async for line in response.body_iterator:
                    line = line.decode("utf-8") if isinstance(line, bytes) else line
                    data = line

                    # Skip empty lines
                    if not data.strip():
                        continue

                    # "data: " is the prefix for each event
                    if not data.startswith("data: "):
                        continue

                    # Remove the prefix
                    data = data[len("data: ") :]

                    try:
                        data = json.loads(data)

                        if "selected_model_id" in data:
                            Chats.upsert_message_to_chat_by_id_and_message_id(
                                metadata["chat_id"],
                                metadata["message_id"],
                                {
                                    "selectedModelId": data["selected_model_id"],
                                },
                            )

                        else:
                            value = (
                                data.get("choices", [])[0]
                                .get("delta", {})
                                .get("content")
                            )

                            if value:
                                content = f"{content}{value}"

                                if ENABLE_REALTIME_CHAT_SAVE:
                                    # Save message in the database
                                    Chats.upsert_message_to_chat_by_id_and_message_id(
                                        metadata["chat_id"],
                                        metadata["message_id"],
                                        {
                                            "content": content,
                                        },
                                    )
                                else:
                                    data = {
                                        "content": content,
                                    }

                        await event_emitter(
                            {
                                "type": "chat:completion",
                                "data": data,
                            }
                        )

                    except Exception as e:
                        done = "data: [DONE]" in line

                        if done:
                            pass
                        else:
                            continue

                title = Chats.get_chat_title_by_id(metadata["chat_id"])
                data = {"done": True, "content": content, "title": title}

                if not ENABLE_REALTIME_CHAT_SAVE:
                    # Save message in the database
                    Chats.upsert_message_to_chat_by_id_and_message_id(
                        metadata["chat_id"],
                        metadata["message_id"],
                        {
                            "content": content,
                        },
                    )

                # Send a webhook notification if the user is not active
                if get_active_status_by_user_id(user.id) is None:
                    webhook_url = Users.get_user_webhook_url_by_id(user.id)
                    if webhook_url:
                        post_webhook(
                            webhook_url,
                            f"{title} - {request.app.state.config.WEBUI_URL}/c/{metadata['chat_id']}\n\n{content}",
                            {
                                "action": "chat",
                                "message": content,
                                "title": title,
                                "url": f"{request.app.state.config.WEBUI_URL}/c/{metadata['chat_id']}",
                            },
                        )

                await event_emitter(
                    {
                        "type": "chat:completion",
                        "data": data,
                    }
                )

                await background_tasks_handler()
            except asyncio.CancelledError:
                log.info(
                    "process_chat_response:post_response_handler:task_cancelled",
                    task_id=task_id,
                )
                await event_emitter({"type": "task-cancelled"})

                if not ENABLE_REALTIME_CHAT_SAVE:
                    # Save message in the database
                    Chats.upsert_message_to_chat_by_id_and_message_id(
                        metadata["chat_id"],
                        metadata["message_id"],
                        {
                            "content": content,
                        },
                    )

                raise
            finally:
                if response.background is not None:
                    await response.background()

        # background_tasks.add_task(post_response_handler, response, events)
        task_id, _ = create_task(post_response_handler(response, events))
        return {"status": True, "task_id": task_id}

    else:

        # Fallback to the original response
        async def stream_wrapper(original_generator, events):
            def wrap_item(item):
                return f"data: {item}\n\n"

            for event in events:
                yield wrap_item(json.dumps(event))

            async for data in original_generator:
                yield data

        return StreamingResponse(
            stream_wrapper(response.body_iterator, events),
            headers=dict(response.headers),
            background=response.background,
        )

# tasks.py
import asyncio
import structlog
import os
import redis
from typing import Dict
from uuid import uuid4

from open_webui.env import REDIS_URL


# A dictionary to keep track of active tasks
tasks: Dict[str, asyncio.Task] = {}

# Configure logging
log = structlog.get_logger(__name__)

# Unique identifier for this app instance
INSTANCE_NAME = os.environ.get("HOSTNAME", f"instance-{uuid4()}")
CHANNEL_NAME = "tasks"

# Connect to Redis
redis_client = redis.StrictRedis.from_url(
    REDIS_URL,
    socket_timeout=None,
    socket_keepalive=True,
    health_check_interval=10,
    retry_on_timeout=True,
)

if not redis_client:
    log.fatal("Failed to connect to Redis")


def task_channel_listener():
    """
    Listen for task-related messages on the Redis pub/sub channel. This is a
    blocking function, so it should be run in a separate thread.
    """
    pubsub = redis_client.pubsub()
    pubsub.subscribe(CHANNEL_NAME)
    log.info(
        "task_channel_listener:subscribed",
        instance=INSTANCE_NAME,
        channel=CHANNEL_NAME,
    )

    for message in pubsub.listen():
        log.debug("task_channel_listener:message_received", message=message)
        if message["type"] != "message":
            log.debug(
                "task_channel_listener:ignoring_non_message",
                message_type=message["type"],
            )
            continue

        message_data = message["data"].decode("utf-8")
        command, task_id = message_data.split(":", 1)
        log.debug(
            "task_channel_listener:evaluating_command",
            instance=INSTANCE_NAME,
            command=command,
            task_id=task_id,
            local_tasks=tasks.keys(),
        )

        # If this is our task, handle the command.
        if command == "stop" and task_id in tasks:
            cancel_task(task_id)


def cancel_task(task_id: str):
    log.debug("cancel_task", instance=INSTANCE_NAME, task_id=task_id)
    try:
        tasks[task_id].cancel()
    except Exception as e:
        log.exception("cancel_task:error", instance=INSTANCE_NAME, task_id=task_id)


def cleanup_task(task_id: str):
    """
    Remove a completed or canceled task from the global `tasks` dictionary.
    """
    log.info("cleanup_task", instance=INSTANCE_NAME, task_id=task_id)
    tasks.pop(task_id, None)  # Remove the task if it exists


def create_task(coroutine):
    """
    Create a new asyncio task and add it to the local task dictionary.
    """
    task_id = str(uuid4())  # Generate a unique ID for the task
    task = asyncio.create_task(coroutine)  # Create the task
    log.info(
        "create_task",
        instance=INSTANCE_NAME,
        coroutine_name=getattr(coroutine, "__name__", coroutine.__class__.__name__),
        task_id=task_id,
    )

    def on_task_done(task):
        try:
            if task.cancelled():
                log.info(
                    "create_task:on_task_done:cancelled",
                    instance=INSTANCE_NAME,
                    task_id=task_id,
                )
            elif task.exception():
                log.exception(
                    "create_task:on_task_done:exception",
                    instance=INSTANCE_NAME,
                    task_id=task_id,
                    exc_info=task.exception(),
                )
            else:
                log.info(
                    "create_task:on_task_done:completed",
                    instance=INSTANCE_NAME,
                    task_id=task_id,
                )
        finally:
            cleanup_task(task_id)

    # Add a done callback for cleanup
    task.add_done_callback(on_task_done)

    tasks[task_id] = task
    return task_id, task


async def stop_task(task_id: str):
    """
    Handle a request to cancel a running task.
    """
    log.debug("stop_task", instance=INSTANCE_NAME, task_id=task_id)
    if task_id in tasks:
        # It's a local task, stop it locally
        cancel_task(task_id)
        log.debug("stop_task:stopped_locally", instance=INSTANCE_NAME, task_id=task_id)
        return {"status": True, "message": f"Task stopped locally: {task_id}."}
    else:
        # Otherwise, inform other instances of the stop request
        subscriber_count = redis_client.publish(CHANNEL_NAME, f"stop:{task_id}")
        log.debug(
            "stop_task:published_stop_request",
            instance=INSTANCE_NAME,
            task_id=task_id,
            subscribers_notified=subscriber_count,
        )
        return {
            "status": True,
            "message": f"Initiated stop request for task: {task_id}.",
        }

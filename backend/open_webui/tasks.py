# tasks.py
import asyncio
import logging
import os
import sys
import redis
from typing import Dict
from uuid import uuid4

from open_webui.env import GLOBAL_LOG_LEVEL, REDIS_URL, SRC_LOG_LEVELS


# A dictionary to keep track of active tasks
tasks: Dict[str, asyncio.Task] = {}

# Configure logging
logging.basicConfig(stream=sys.stdout, level=GLOBAL_LOG_LEVEL)
log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])

# Unique identifier for this app instance
INSTANCE_NAME = os.environ.get("HOSTNAME", f"instance-{uuid4()}")
CHANNEL_NAME = "tasks"

# Connect to Redis
redis_client = redis.StrictRedis.from_url(REDIS_URL)
if not redis_client:
    log.fatal("Failed to connect to Redis")

pubsub = redis_client.pubsub()
pubsub.subscribe(CHANNEL_NAME)
log.info(f"{INSTANCE_NAME} subscribed to Redis pub/sub channel: {CHANNEL_NAME}")


def task_channel_listener():
    """
    Listen for task-related messages on the Redis pub/sub channel. This is a
    blocking function, so it should be run in a separate thread.
    """
    for message in pubsub.listen():
        if message["type"] != "message":
            continue

        message_data = message["data"].decode("utf-8")
        command, task_id = message_data.split(":", 1)
        log.info(f"Task channel command: {command}, task ID: {task_id}")

        # If this is our task, handle the command.
        task = tasks.get(task_id)
        if task:
            if command == "stop":
                log.info(f"Stopping task {task_id} on instance {INSTANCE_NAME}")
                task.cancel()  # Request task cancellation
                tasks.pop(task_id, None)  # Remove it from the dictionary


def cleanup_task(task_id: str):
    """
    Remove a completed or canceled task from the global `tasks` dictionary.
    """
    tasks.pop(task_id, None)  # Remove the task if it exists


def create_task(coroutine):
    """
    Create a new asyncio task and add it to the global task dictionary.
    """
    task_id = str(uuid4())  # Generate a unique ID for the task
    task = asyncio.create_task(coroutine)  # Create the task

    # Add a done callback for cleanup
    task.add_done_callback(lambda t: cleanup_task(task_id))

    tasks[task_id] = task
    return task_id, task


# def get_task(task_id: str):
#     """
#     Retrieve a task by its task ID.
#     """
#     return tasks.get(task_id)


# def list_tasks():
#     """
#     List all currently active task IDs.
#     """
#     return list(tasks.keys())


async def stop_task(task_id: str):
    """
    Handle a request to cancel a running task.
    """
    redis_client.publish(CHANNEL_NAME, f"stop:{task_id}")
    return {"status": True, "message": f"Initiated stop request for task {task_id}."}

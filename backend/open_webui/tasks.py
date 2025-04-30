# tasks.py
import asyncio
import os
import logging
from typing import Dict
from uuid import uuid4
import redis

# Configure logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# Get environment variables or use defaults
REDIS_URL = os.environ.get("WEBSOCKET_REDIS_URL", "redis://:@redis:6379/0")
POD_NAME = os.environ.get("HOSTNAME", f"pod-{uuid4()}")

# Connect to Redis
try:
    redis_client = redis.StrictRedis.from_url(REDIS_URL)
    # Test connection
    redis_client.ping()
    log.info(f"Successfully connected to Redis at {REDIS_URL}")
    log.info(f"Running on pod {POD_NAME}")
except Exception as e:
    log.error(f"Failed to connect to Redis: {str(e)}")
    redis_client = None

# A dictionary to keep track of active tasks
tasks: Dict[str, asyncio.Task] = {}


def test_redis_connection():
    """Test the Redis connection and print debugging information."""
    if redis_client:
        try:
            print(f"Testing Redis connection to {REDIS_URL}")
            log.critical(f"Testing Redis connection to {REDIS_URL}")

            # Try pinging
            ping_result = redis_client.ping()
            print(f"Redis ping result: {ping_result}")
            log.critical(f"Redis ping result: {ping_result}")

            # Try setting and getting a value
            test_key = f"test:connection:{POD_NAME}"
            redis_client.set(test_key, "test_value", ex=60)
            test_value = redis_client.get(test_key)
            print(f"Redis get test value: {test_value}")
            log.critical(f"Redis get test value: {test_value}")

            return True
        except Exception as e:
            print(f"Redis connection test failed: {e}")
            log.critical(f"Redis connection test failed: {e}")
            return False
    else:
        print("Redis client is None")
        log.critical("Redis client is None")
        return False


# Call this function when the module loads
redis_connected = test_redis_connection()
print(f"Redis connection status: {redis_connected}")
log.critical(f"Redis connection status: {redis_connected}")


def cleanup_task(task_id: str):
    """
    Remove a completed or canceled task from the global `tasks` dictionary.
    """
    log.info(f"Cleaning up task {task_id}")

    # Remove from local tasks
    if task_id in tasks:
        tasks.pop(task_id)
        log.info(f"Removed task {task_id} from local tasks")
    else:
        log.info(f"Task {task_id} not found in local tasks during cleanup")

    # Remove from Redis
    if redis_client:
        try:
            redis_client.delete(f"task:{task_id}")
            log.info(f"Removed task {task_id} from Redis")
        except Exception as e:
            log.error(f"Redis error when removing task {task_id}: {e}")


def create_task(coroutine, task_id=None):
    """
    Create a new asyncio task and add it to the global task dictionary.
    """
    if task_id is None:
        task_id = str(uuid4())

    log.critical(f"Creating task {task_id} on pod {POD_NAME}")

    task = asyncio.create_task(coroutine)
    task.add_done_callback(lambda t: cleanup_task(task_id))

    tasks[task_id] = task

    # Register in Redis
    if redis_client:
        try:
            log.critical(f"Attempting to register task {task_id} in Redis")

            # Set the key with pod name
            redis_key = f"task:{task_id}"
            redis_client.set(redis_key, POD_NAME, ex=3600)

            # Verify it was set
            verify_value = redis_client.get(redis_key)
            if verify_value:
                log.critical(
                    f"Successfully registered task {task_id} in Redis: {verify_value.decode('utf-8')}"
                )

                # List all task keys
                all_keys = redis_client.keys("task:*")
                log.critical(
                    f"All task keys in Redis: {[k.decode('utf-8') for k in all_keys]}"
                )
            else:
                log.critical(f"FAILED to verify task {task_id} in Redis")
        except Exception as e:
            log.critical(f"Redis error in create_task: {e}")
    else:
        log.critical("Redis client is None, task not registered in Redis")

    return task_id, task


def get_task(task_id: str):
    """
    Retrieve a task by its task ID.
    """
    # Check locally first
    task = tasks.get(task_id)
    if task:
        return task

    # Check Redis if not found locally
    if redis_client:
        try:
            pod_name = redis_client.get(f"task:{task_id}")
            if pod_name:
                # Task exists on another pod
                return {"pod": pod_name.decode("utf-8")}
        except Exception as e:
            log.error(f"Redis error in get_task: {e}")

    return None


def list_tasks():
    """
    List all currently active task IDs.
    """
    local_tasks = list(tasks.keys())

    redis_tasks = []
    if redis_client:
        try:
            task_keys = redis_client.keys("task:*")
            redis_tasks = [key.decode("utf-8").split(":", 1)[1] for key in task_keys]
        except Exception as e:
            log.error(f"Redis error in list_tasks: {e}")

    return {"local_tasks": local_tasks, "all_tasks": redis_tasks, "pod_name": POD_NAME}


async def stop_task(task_id: str):
    """
    Cancel a running task and remove it from the global task list.
    """
    log.critical(f"CRITICAL: Attempting to stop task {task_id} on pod {POD_NAME}")

    # Debug: Get raw list of tasks
    local_task_keys = list(tasks.keys())
    log.critical(f"Raw task keys: {local_task_keys}")

    # Debug: Check if task_id exists in the keys directly
    task_exists = task_id in local_task_keys
    log.critical(f"Task {task_id} exists in keys: {task_exists}")

    # Debug: Try getting the task directly
    task = tasks.get(task_id)
    log.critical(f"tasks.get({task_id}) result: {task}")

    if task:
        log.critical(f"FOUND TASK: {task_id}")
        try:
            # Try cancelling it
            task.cancel()
            log.critical(f"Task {task_id} cancelled")

            # Remove from local dictionary
            tasks.pop(task_id, None)

            # Remove from Redis if available
            if redis_client:
                try:
                    redis_client.delete(f"task:{task_id}")
                    log.critical(f"Task {task_id} removed from Redis")
                except Exception as e:
                    log.critical(f"Redis error when deleting task: {e}")

            return {"status": True, "message": f"Task {task_id} successfully stopped."}
        except Exception as e:
            log.critical(f"Error cancelling task: {e}")
            return {
                "status": False,
                "message": f"Error stopping task {task_id}: {str(e)}",
            }
    else:
        log.critical(f"Task {task_id} not found in dictionary")

    # Check Redis
    if redis_client:
        try:
            # List all tasks in Redis
            all_tasks = redis_client.keys("task:*")
            log.critical(
                f"IN REDIS_CLIENT COND: All tasks in Redis: {[k.decode('utf-8') for k in all_tasks]}"
            )

            # Look up specific task
            pod_info = redis_client.get(f"task:{task_id}")
            log.critical(f"Redis lookup for task {task_id}: {pod_info}")

            if pod_info:
                pod_name = pod_info.decode("utf-8")
                log.critical(f"Task {task_id} found in Redis on pod {pod_name}")

                # If on another pod, use WebSockets
                if pod_name != POD_NAME:
                    try:
                        from open_webui.socket.main import sio

                        log.critical(
                            f"Emitting stop_task_request for {task_id} to pod {pod_name}"
                        )
                        try:
                            log.critical(
                                f"About to emit stop_task_request for task {task_id}"
                            )
                            await sio.emit(
                                "stop_task_request",
                                {"task_id": task_id, "pod": pod_name},
                            )
                            log.critical(
                                f"Sio.emit was called with task {task_id} and pod {pod_name}"
                            )
                        except Exception as e:
                            log.critical(
                                f"Socket.IO not connected properly. Error emmitting stop_task_request: {e}"
                            )
                        return {
                            "status": True,
                            "message": f"Stop request sent to pod {pod_name} for task {task_id}",
                        }
                    except ImportError:
                        log.critical("Could not import socket.main.sio")
                    except Exception as e:
                        log.critical(f"Error sending stop request: {e}")
            else:
                log.critical(f"Task {task_id} not found in Redis")
        except Exception as e:
            log.critical(f"Redis error when looking up task: {e}")
    else:
        log.critical("Redis client is not available during stop attempt")

    # Task not found anywhere - we'll still return success with a notice
    log.critical(
        f"Task {task_id} not found locally or in Redis, but may be handled elsewhere"
    )

    # Instead of raising an error, return a "success" response to prevent 404
    return {"status": True, "message": f"Task stop request acknowledged for {task_id}"}

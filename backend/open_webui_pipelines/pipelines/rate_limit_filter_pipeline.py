import os
import time
import json
import sys
from typing import List, Optional
from urllib.parse import urlparse
import asyncio

from pydantic import BaseModel
import redis
import structlog

from utils.pipelines.custom_exceptions import RateLimitException


logger = structlog.get_logger(__name__)


DEFAULT_REQUEST_LIMITS = {
    "bedrock_claude_haiku35_pipeline": {
        "user_limit": 100,
        "global_limit": 2000,
    },
    "bedrock_claude_sonnet35_v2_pipeline": {
        "user_limit": 10,
        "global_limit": 75,
    },
    "bedrock_claude_sonnet37_pipeline": {"user_limit": 10, "global_limit": 75},
    "bedrock_llama32_11b_pipeline": {"user_limit": 40, "global_limit": 400},
    "bedrock_claude_haiku35_pipeline_mock": {
        "user_limit": 2,
        "global_limit": 4,
    },
}


class Pipeline:
    class Valves(BaseModel):
        pipelines: List[str] = []
        priority: int = 0
        request_limits_json: str = ""

    def __init__(self):
        logger.info("Initializing pipeline")
        redis_url = os.getenv(
            "RATE_LIMIT_REDIS_URL",
            os.getenv("REDIS_URL", "you forget to set the REDIS_URL"),
        )
        logger.debug("Using Redis URL", redis_url=redis_url)

        request_limits = None
        request_limits_json_str = os.getenv("REQUEST_LIMITS", None)
        if request_limits_json_str:
            try:
                # Parse JSON string from environment variable
                _ = json.loads(request_limits_json_str)
                request_limits = request_limits_json_str
                logger.info(
                    "Using request limits from environment",
                    request_limits=request_limits,
                )
            except json.JSONDecodeError as e:
                logger.warning(
                    "Failed to parse REQUEST_LIMITS as JSON, falling back to default",
                    exc_info=e,
                )
                request_limits = json.dumps(DEFAULT_REQUEST_LIMITS)

        if not request_limits:
            logger.info("Using default request limits")
            request_limits = json.dumps(DEFAULT_REQUEST_LIMITS)

        self.request_limits_dict = json.loads(request_limits)
        logger.info(
            "Configured request limits dict",
            request_limits_dict=self.request_limits_dict,
        )

        self.models = list(self.request_limits_dict.keys())
        logger.info("Models in request limits dict", models=self.models)

        if redis_url is None:
            self.type = None
            self.name = "Rate Limit Filter (disabled)"
            logger.warning("Rate Limit Filter disabled - No Redis URL provided")
            return

        self.type = "filter"
        self.name = "Rate Limit Filter"
        logger.info("Pipeline values", type=self.type, name=self.name)

        self.valves = self.Valves(
            pipelines=[
                "bedrock_claude_haiku35_pipeline,bedrock_claude_sonnet35_v2_pipeline, bedrock_claude_sonnet37_pipeline,bedrock_claude_haiku35_pipeline_mock,bedrock_llama32_11b_pipeline"  # noqa E501
            ],
            request_limits_json=request_limits,
        )
        logger.debug("Valves configured", pipelines=self.valves.pipelines)

        parsed_url = urlparse(redis_url)

        logger.info(
            "Connecting to Redis",
            redis_host=parsed_url.hostname,
            redis_port=(parsed_url.port if parsed_url.port else 6379),
        )
        if not parsed_url.hostname:
            logger.error("Invalid RATE_LIMIT_REDIS_URL: missing hostname")
            raise ValueError("Invalid RATE_LIMIT_REDIS_URL: missing hostname")
        try:
            verify_ssl = os.getenv("DEV", "false").lower() == "false"
            logger.info("Redis SSL verification", result=verify_ssl)
            self.redis_client = redis.Redis(
                host=parsed_url.hostname,
                port=parsed_url.port if parsed_url.port else 6379,
                db=0,
                password=parsed_url.password,
                decode_responses=True,
                socket_timeout=1.0,  # Add timeout
                socket_connect_timeout=1.0,  # Add connection timeout
                ssl=verify_ssl,  # Enable SSL/TLS
                ssl_cert_reqs=None,  # Skip certificate validation, or use 'required' for validation
            )

            # Test Redis connection with simple get/set operations
            test_key = "connection_test_key"
            test_value = "connection_test_value"

            # Test set operation
            set_result = self.redis_client.set(
                test_key, test_value, ex=60
            )  # Set with 60 second expiration
            if not set_result:
                logger.warning("Redis SET test failed")

            # Test get operation
            get_result = self.redis_client.get(test_key)
            if get_result != test_value:
                logger.warning(
                    "Redis GET test failed", expected=test_value, actual=get_result
                )
            else:
                logger.info(
                    "Redis connection test successful: SET/GET operations working"
                )

            # Clean up test key
            self.redis_client.delete(test_key)

            logger.info("Successfully connected to Redis")
        except redis.exceptions.TimeoutError as e:
            logger.exception(
                "Redis timed out when checking simple get set operation", exc_info=e
            )
            raise ConnectionError(f"Initial Redis connection timed out: {str(e)}")
        except Exception as e:
            logger.exception("Failed to connect to Redis", exc_info=e)
            raise ConnectionError(f"Failed to connect to Redis: {str(e)}")

    async def on_startup(self):
        logger.info("on_startup")
        pass

    async def on_shutdown(self):
        logger.info("on_shutdown")
        pass

    def get_global_redis_key(self, model_id: str):
        """Generate Redis keys for global rate limits."""
        now = int(time.time())
        key = f"global:{model_id}:rate:minute:{now // 60}"
        logger.debug("get_global_redis_key", key=key)
        return key

    def get_user_redis_key(self, user_id: str, model_id: str):
        """Generate Redis keys for user rate limits."""
        now = int(time.time())
        key = f"user:{user_id}:{model_id}:rate:minute:{now // 60}"
        logger.debug("get_user_redis_key", key=key)
        return key

    def get_user_last_blocked_redis_key(self, user_id: str, model_id: str):
        """Generate Redis keys for user rate limits."""
        key = f"user:{user_id}:{model_id}:last_blocked"
        logger.debug("get_user_last_blocked_redis_key", key=key)
        return key

    def get_rate_limit_info(self, user_id: str, model_id: str):
        """Get both the current count and remaining TTL for a rate limit key in one request."""
        user_minute_key = self.get_user_redis_key(user_id, model_id)
        global_minute_key = self.get_global_redis_key(model_id)

        # Using a pipeline to keep redis traffic down
        pipe = self.redis_client.pipeline()
        pipe.get(user_minute_key)
        pipe.ttl(user_minute_key)
        pipe.get(global_minute_key)
        pipe.ttl(global_minute_key)
        user_count, user_ttl, global_count, global_ttl = pipe.execute()

        user_count = int(user_count or 0)
        user_key_expires_at = int(time.time()) + user_ttl if user_ttl else None
        global_count = int(global_count or 0)
        global_key_expires_at = int(time.time()) + global_ttl if global_ttl else None

        return {
            "user_count": user_count,
            "user_key_expires_at": user_key_expires_at,
            "global_count": global_count,
            "global_key_expires_at": global_key_expires_at,
        }

    def set_last_blocked_time(self, user_id: str, model_id: str):

        user_last_blocked_key = self.get_user_last_blocked_redis_key(user_id, model_id)

        rate_limit_info = self.get_rate_limit_info(user_id, model_id)
        logger.debug("Rate limit", info=rate_limit_info)

        global_current_count = rate_limit_info["global_count"]
        user_current_count = rate_limit_info["user_count"]
        user_key_expires_at = rate_limit_info["user_key_expires_at"]

        global_limit = self.request_limits_dict[model_id].get("global_limit", 2000)
        logger.debug(
            "global_limit",
            model=model_id,
            current_count=global_current_count / global_limit,
        )
        safe_free_quota = (global_limit - global_current_count) * 0.25
        logger.debug("safe_free_quota", safe_free_quota=safe_free_quota)

        user_limit = self.request_limits_dict[model_id].get("user_limit", 50)
        logger.debug(
            "user_limit",
            user=user_id,
            model=model_id,
            current_count=user_current_count / user_limit,
        )

        original_user_limit = user_limit
        if user_limit < safe_free_quota:
            user_limit = safe_free_quota
        logger.debug("Adjusted user limit", limit=user_limit)

        if user_current_count >= user_limit:
            logger.warning(
                "User rate limit exceeded",
                user=user_id,
                model=model_id,
                current_count=user_current_count / user_limit,
            )
            current_time = int(time.time())
            self.redis_client.set(user_last_blocked_key, current_time)
            last_period_start_time = user_key_expires_at - 60
            return (
                True,
                f"You've exceeded your limit of {original_user_limit}"
                + f" requests since {last_period_start_time}",
                last_period_start_time,
            )

        return False, None, None

    def is_rate_limited(self, user_id: str, model_id: str) -> bool:
        logger.debug("Checking rate limits", user=user_id, model=model_id)
        if model_id not in self.models:
            logger.warning("Model not found in request limits", model=model_id)
            return False, None

        logger.debug(
            "Model found, checking rate limits for user", model=model_id, user=user_id
        )
        user_last_blocked_key = self.get_user_last_blocked_redis_key(user_id, model_id)

        try:
            user_last_blocked_time = self.redis_client.get(user_last_blocked_key)
            logger.debug(
                "User last blocked time",
                user=user_id,
                last_blocked_time=user_last_blocked_time,
            )
        except redis.exceptions.TimeoutError as e:
            logger.exception(
                "Redis operation timed out when checking last blocked time", exc_info=e
            )
            # Return a default/safe value instead of failing
            return False, None, None
        except Exception as e:
            logger.exception("Redis error when checking last blocked time", exc_info=e)
            return False, None, None

        if (
            user_last_blocked_time
            and int(user_last_blocked_time) > int(time.time()) - 60
        ):
            logger.warning(
                "User was blocked less than 60 seconds ago",
                user=user_id,
                model=model_id,
            )
            return self.set_last_blocked_time(user_id, model_id)

        logger.debug("Proceeding without blocking user", user=user_id, model=model_id)
        return False, None, None

    async def log_request(self, user_id: str, model_id: str):
        logger.debug("Logging request", user=user_id, model=model_id)
        minute_key = self.get_user_redis_key(user_id, model_id)
        new_user_count = self.redis_client.incr(minute_key)
        logger.debug(
            "Incremented user request count",
            new_user_count=new_user_count,
            key=minute_key,
        )

        expiry_result = self.redis_client.expire(minute_key, 60, nx=True)
        logger.debug(
            "Set expiry on user key", minute_key=minute_key, expiry_result=expiry_result
        )

        # Log global request
        global_key = self.get_global_redis_key(model_id)
        new_global_count = self.redis_client.incr(global_key)
        logger.debug(
            "Incremented global request count",
            new_global_count=new_global_count,
            key=global_key,
        )

        expiry_result = self.redis_client.expire(global_key, 60, nx=True)
        logger.debug(
            "Set expiry on global key",
            global_key=global_key,
            expiry_result=expiry_result,
        )
        _, _, _ = self.set_last_blocked_time(user_id, model_id)

    async def inlet(self, body: dict, user: Optional[dict] = None) -> dict:

        logger.debug("Processing inlet request", body=body, user=user)
        user_id = user.get("id", "default_user") if user else "default_user"
        model_id = body["model"]

        logger.debug("Processing inlet request", user_id=user_id, model=model_id)
        limited, msg, last_period_start_time = self.is_rate_limited(user_id, model_id)
        if limited:
            logger.error(f"Rate limit check failed with msg: {msg}")
            raise RateLimitException(
                msg,
                requests_limit=self.request_limits_dict[model_id].get("user_limit", 50),
                requests_period=60,
                last_period_start_time=last_period_start_time,
            )

        logger.debug("Logging request in bg task...")
        asyncio.create_task(self.log_request(user_id, model_id))

        return body

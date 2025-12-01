from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional, Dict

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class CallbackService:
    """Service for sending callback notifications."""

    def __init__(
        self,
        timeout: Optional[int] = None,
        max_retries: Optional[int] = None,
    ):
        self.timeout = timeout or settings.callback_timeout
        self.max_retries = max_retries or settings.callback_max_retries

    async def send_callback_async(
        self,
        callback_url: str,
        payload: Dict[str, Any],
    ) -> bool:
        """
        Send callback notification asynchronously.

        Args:
            callback_url: URL to send callback to
            payload: JSON payload to send

        Returns:
            True if successful, False otherwise
        """
        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        callback_url,
                        json=payload,
                        headers={"Content-Type": "application/json"},
                    )

                    if response.status_code >= 200 and response.status_code < 300:
                        logger.info(f"Callback sent successfully to {callback_url}")
                        return True
                    else:
                        logger.warning(
                            f"Callback failed with status {response.status_code}: {response.text}"
                        )

            except httpx.TimeoutException:
                logger.warning(f"Callback timeout (attempt {attempt + 1}/{self.max_retries})")
            except httpx.RequestError as e:
                logger.warning(f"Callback request error (attempt {attempt + 1}/{self.max_retries}): {e}")
            except Exception as e:
                logger.exception(f"Unexpected callback error: {e}")

            # Wait before retry (exponential backoff: 30s, 60s, 120s)
            if attempt < self.max_retries - 1:
                import asyncio
                wait_time = 30 * (2 ** attempt)
                await asyncio.sleep(wait_time)

        logger.error(f"Callback failed after {self.max_retries} attempts: {callback_url}")
        return False

    def send_callback_sync(
        self,
        callback_url: str,
        payload: Dict[str, Any],
    ) -> bool:
        """
        Send callback notification synchronously (for Celery tasks).

        Args:
            callback_url: URL to send callback to
            payload: JSON payload to send

        Returns:
            True if successful, False otherwise
        """
        import time

        for attempt in range(self.max_retries):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    response = client.post(
                        callback_url,
                        json=payload,
                        headers={"Content-Type": "application/json"},
                    )

                    if response.status_code >= 200 and response.status_code < 300:
                        logger.info(f"Callback sent successfully to {callback_url}")
                        return True
                    else:
                        logger.warning(
                            f"Callback failed with status {response.status_code}: {response.text}"
                        )

            except httpx.TimeoutException:
                logger.warning(f"Callback timeout (attempt {attempt + 1}/{self.max_retries})")
            except httpx.RequestError as e:
                logger.warning(f"Callback request error (attempt {attempt + 1}/{self.max_retries}): {e}")
            except Exception as e:
                logger.exception(f"Unexpected callback error: {e}")

            # Wait before retry
            if attempt < self.max_retries - 1:
                wait_time = 30 * (2 ** attempt)
                time.sleep(wait_time)

        logger.error(f"Callback failed after {self.max_retries} attempts: {callback_url}")
        return False


def build_success_payload(
    task_id: str,
    video_url: str,
    video_info: dict,
    download_url: str,
    file_name: str,
    file_size: int,
) -> dict:
    """Build callback payload for successful download."""
    return {
        "task_id": task_id,
        "status": "completed",
        "video_url": video_url,
        "video_info": video_info,
        "result": {
            "download_url": download_url,
            "file_name": file_name,
            "file_size": file_size,
        },
        "completed_at": datetime.utcnow().isoformat(),
    }


def build_failure_payload(
    task_id: str,
    video_url: str,
    error_code: str,
    error_message: str,
) -> dict:
    """Build callback payload for failed download."""
    return {
        "task_id": task_id,
        "status": "failed",
        "video_url": video_url,
        "error": {
            "code": error_code,
            "message": error_message,
        },
        "failed_at": datetime.utcnow().isoformat(),
    }


# Singleton instance
callback_service = CallbackService()

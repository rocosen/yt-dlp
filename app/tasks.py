from __future__ import annotations

import os
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict

from celery import Task
from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models import Task as TaskModel, TaskStatus
from app.downloader import VideoDownloader, DownloadError
from app.callback import callback_service, build_success_payload, build_failure_payload
from app.storage import upload_to_storage, StorageError
from app.config import settings

logger = logging.getLogger(__name__)


class DatabaseTask(Task):
    """Base task with database session management."""
    _db: Optional[Session] = None

    @property
    def db(self) -> Session:
        if self._db is None:
            self._db = SessionLocal()
        return self._db

    def after_return(self, *args, **kwargs):
        if self._db is not None:
            self._db.close()
            self._db = None


@celery_app.task(
    bind=True,
    base=DatabaseTask,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def download_video_task(
    self,
    task_id: str,
    video_url: str,
    callback_url: Optional[str] = None,
    storage_type: str = "local",
    storage_url: Optional[str] = None,
    options: Optional[Dict] = None,
) -> Dict:
    """
    Celery task to download a video.

    Args:
        task_id: Database task ID
        video_url: URL of video to download
        callback_url: Optional callback URL for notification
        storage_type: Storage type (local, s3, gcs, s3_compatible)
        storage_url: Storage URL for cloud storage
        options: Download options (download_type, video_quality, etc.)

    Returns:
        Result dictionary
    """
    options = options or {}
    db = self.db

    # Extract download options with defaults
    download_type = options.get("download_type", "audio_video")
    video_quality = options.get("video_quality", "720")
    format_spec = options.get("format")
    audio_format = options.get("audio_format", "mp3")

    # Legacy support: extract_audio -> download_type
    if options.get("extract_audio", False) and download_type == "audio_video":
        download_type = "audio"

    # Get task from database
    task = db.query(TaskModel).filter(TaskModel.id == task_id).first()
    if not task:
        logger.error(f"Task {task_id} not found in database")
        return {"error": "Task not found"}

    # Check if task was cancelled
    if task.status == TaskStatus.CANCELLED.value:
        logger.info(f"Task {task_id} was cancelled, skipping")
        return {"status": "cancelled"}

    try:
        # Create downloader
        downloader = VideoDownloader()

        # Get video info first (before downloading)
        try:
            video_info = downloader.get_video_info(video_url)
            task.video_title = video_info.title
            task.video_duration = int(video_info.duration) if video_info.duration else None
            task.video_thumbnail = video_info.thumbnail
            task.video_filesize = video_info.filesize
            logger.info(f"Task {task_id}: Video info - {video_info.title}, size: {video_info.filesize}")
        except Exception as e:
            logger.warning(f"Failed to get video info: {e}")

        # Update status to downloading
        task.status = TaskStatus.DOWNLOADING.value
        task.started_at = datetime.utcnow()
        task.celery_task_id = self.request.id
        db.commit()

        # Progress callback to update database
        def progress_callback(percent: float, message: str):
            try:
                task.progress = percent
                db.commit()
            except Exception as e:
                logger.warning(f"Failed to update progress: {e}")

        # Download video with new parameters
        result = downloader.download(
            url=video_url,
            progress_callback=progress_callback,
            download_type=download_type,
            video_quality=video_quality,
            format_spec=format_spec,
            audio_format=audio_format,
        )

        # Update task with video info
        task.video_title = result.video_info.title
        task.video_duration = result.video_info.duration
        task.video_thumbnail = result.video_info.thumbnail
        task.video_filesize = result.video_info.filesize

        # Store local path
        task.local_path = str(result.file_path)
        task.file_name = result.file_name
        task.file_size = result.file_size

        # Upload to cloud storage if configured
        if storage_type and storage_type != "local":
            task.status = TaskStatus.UPLOADING.value
            db.commit()

            try:
                download_url = upload_to_storage(
                    local_path=result.file_path,
                    storage_type=storage_type,
                    storage_url=storage_url,
                    delete_local=True,  # Delete local file after upload
                )
                task.download_url = download_url
                logger.info(f"Task {task_id}: Uploaded to {storage_type}: {download_url}")
            except StorageError as e:
                logger.error(f"Task {task_id}: Storage upload failed: {e.code} - {e.message}")
                # Keep local file as fallback
                task.download_url = f"file://{result.file_path}"
                task.error_message = f"Storage upload failed: {e.message}"
        else:
            # Local storage
            task.download_url = f"file://{result.file_path}"

        # Update status to completed
        task.status = TaskStatus.COMPLETED.value
        task.progress = 100
        task.completed_at = datetime.utcnow()
        db.commit()

        logger.info(f"Task {task_id} completed successfully: {result.file_name}")

        # Send callback notification
        if callback_url:
            payload = build_success_payload(
                task_id=task_id,
                video_url=video_url,
                video_info={
                    "title": result.video_info.title,
                    "duration": result.video_info.duration,
                    "thumbnail": result.video_info.thumbnail,
                },
                download_url=task.download_url,
                file_name=result.file_name,
                file_size=result.file_size,
            )
            callback_service.send_callback_sync(callback_url, payload)

        return {
            "status": "completed",
            "task_id": task_id,
            "file_path": str(result.file_path),
            "file_size": result.file_size,
        }

    except DownloadError as e:
        logger.error(f"Download error for task {task_id}: {e.code} - {e.message}")

        # Update task with error
        task.status = TaskStatus.FAILED.value
        task.error_code = e.code
        task.error_message = e.message
        db.commit()

        # Send failure callback
        if callback_url:
            payload = build_failure_payload(
                task_id=task_id,
                video_url=video_url,
                error_code=e.code,
                error_message=e.message,
            )
            callback_service.send_callback_sync(callback_url, payload)

        return {
            "status": "failed",
            "task_id": task_id,
            "error_code": e.code,
            "error_message": e.message,
        }

    except Exception as e:
        logger.exception(f"Unexpected error for task {task_id}")

        # Update task with error
        task.status = TaskStatus.FAILED.value
        task.error_code = "UNKNOWN_ERROR"
        task.error_message = str(e)
        db.commit()

        # Send failure callback
        if callback_url:
            payload = build_failure_payload(
                task_id=task_id,
                video_url=video_url,
                error_code="UNKNOWN_ERROR",
                error_message=str(e),
            )
            callback_service.send_callback_sync(callback_url, payload)

        # Re-raise for Celery retry mechanism
        raise


@celery_app.task(bind=True, base=DatabaseTask)
def cleanup_old_files_task(self, max_age_hours: int = 24):
    """
    Periodic task to clean up old downloaded files.

    Args:
        max_age_hours: Delete files older than this many hours
    """
    import time

    download_dir = settings.download_path
    cutoff_time = time.time() - (max_age_hours * 3600)
    deleted_count = 0

    for file_path in download_dir.iterdir():
        if file_path.is_file():
            if file_path.stat().st_mtime < cutoff_time:
                try:
                    file_path.unlink()
                    deleted_count += 1
                    logger.info(f"Deleted old file: {file_path}")
                except Exception as e:
                    logger.warning(f"Failed to delete {file_path}: {e}")

    logger.info(f"Cleanup completed: {deleted_count} files deleted")
    return {"deleted_count": deleted_count}

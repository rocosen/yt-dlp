from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, List, Literal
from pydantic import BaseModel, Field, HttpUrl
from enum import Enum


# ============ Enums ============

class DownloadType(str, Enum):
    """Download type options."""
    AUDIO = "audio"
    VIDEO = "video"
    AUDIO_VIDEO = "audio_video"


class VideoQuality(str, Enum):
    """Video quality options."""
    BEST = "best"
    WORST = "worst"
    Q480 = "480"
    Q720 = "720"
    Q1080 = "1080"
    Q1440 = "1440"
    Q2160 = "2160"


class StorageType(str, Enum):
    """Storage type options."""
    LOCAL = "local"
    S3 = "s3"
    GCS = "gcs"
    S3_COMPATIBLE = "s3_compatible"


# ============ Request Schemas ============

class DownloadOptions(BaseModel):
    """Download options for a task."""
    # New parameters
    download_type: DownloadType = Field(
        DownloadType.AUDIO_VIDEO,
        description="Download type: audio, video, or audio_video"
    )
    video_quality: VideoQuality = Field(
        VideoQuality.Q720,
        description="Video quality: best, worst, or resolution (480, 720, 1080, 1440, 2160)"
    )

    # Legacy parameters (keep for backward compatibility)
    format: Optional[str] = Field(None, description="yt-dlp format specification (overrides video_quality)")
    extract_audio: bool = Field(False, description="[Deprecated] Use download_type='audio' instead")
    audio_format: str = Field("mp3", description="Audio format when download_type is 'audio' (mp3, aac, wav, m4a)")


class CreateTaskRequest(BaseModel):
    """Request to create a new download task."""
    # Required
    video_url: str = Field(..., description="URL of the video to download")

    # Task-level configuration
    callback_url: Optional[str] = Field(None, description="URL for completion callback")
    storage_type: StorageType = Field(
        StorageType.LOCAL,
        description="Storage type: local, s3, gcs, or s3_compatible"
    )
    storage_url: Optional[str] = Field(
        None,
        description="Storage URL (e.g., s3://bucket/folder/ or gs://bucket/folder/)"
    )

    # Download options
    options: Optional[DownloadOptions] = Field(None, description="Download options")

    class Config:
        json_schema_extra = {
            "example": {
                "video_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "callback_url": "https://your-server.com/callback",
                "storage_type": "local",
                "storage_url": None,
                "options": {
                    "download_type": "audio_video",
                    "video_quality": "1080"
                }
            }
        }


class VideoInfoRequest(BaseModel):
    """Request to get video info."""
    video_url: str = Field(..., description="URL of the video")


# ============ Response Schemas ============

class VideoInfo(BaseModel):
    """Video metadata."""
    title: Optional[str] = None
    duration: Optional[float] = None  # seconds, can be float
    thumbnail: Optional[str] = None
    filesize: Optional[int] = None
    uploader: Optional[str] = None
    upload_date: Optional[str] = None


class VideoFormat(BaseModel):
    """Available video format."""
    format_id: Optional[str] = None
    ext: Optional[str] = None
    resolution: Optional[str] = None
    filesize: Optional[int] = None


class VideoInfoResponse(BaseModel):
    """Response for video info request."""
    title: str
    duration: Optional[float] = None  # seconds, can be float
    thumbnail: Optional[str] = None
    uploader: Optional[str] = None
    upload_date: Optional[str] = None
    formats: List[VideoFormat] = []


class TaskResult(BaseModel):
    """Download result."""
    download_url: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None


class TaskError(BaseModel):
    """Task error info."""
    code: Optional[str] = None
    message: Optional[str] = None


class TaskResponse(BaseModel):
    """Response for a single task."""
    task_id: str
    video_url: str
    status: str
    progress: float = 0
    video_info: Optional[VideoInfo] = None
    result: Optional[TaskResult] = None
    error: Optional[TaskError] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CreateTaskResponse(BaseModel):
    """Response for task creation."""
    task_id: str
    status: str
    video_url: str
    created_at: datetime


class TaskListResponse(BaseModel):
    """Response for task list."""
    total: int
    page: int
    page_size: int
    tasks: List[TaskResponse]


class CancelTaskResponse(BaseModel):
    """Response for task cancellation."""
    task_id: str
    status: str
    message: str


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str
    yt_dlp_version: Optional[str] = None
    queue_size: int = 0
    active_downloads: int = 0


class ErrorResponse(BaseModel):
    """Error response."""
    error: str
    detail: Optional[str] = None

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, List
from pydantic import BaseModel, Field, HttpUrl


# ============ Request Schemas ============

class DownloadOptions(BaseModel):
    """Download options for a task."""
    format: Optional[str] = Field(None, description="yt-dlp format specification")
    extract_audio: bool = Field(False, description="Extract audio only")
    audio_format: str = Field("mp3", description="Audio format (mp3, aac, wav)")


class CreateTaskRequest(BaseModel):
    """Request to create a new download task."""
    video_url: str = Field(..., description="URL of the video to download")
    callback_url: Optional[str] = Field(None, description="URL for completion callback")
    options: Optional[DownloadOptions] = Field(None, description="Download options")

    class Config:
        json_schema_extra = {
            "example": {
                "video_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "callback_url": "https://your-server.com/callback",
                "options": {
                    "format": "best[height<=1080]",
                    "extract_audio": False
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

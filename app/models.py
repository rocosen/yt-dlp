import uuid
from datetime import datetime
from enum import Enum
from sqlalchemy import Column, String, Integer, Float, Text, DateTime, JSON
from app.database import Base


class TaskStatus(str, Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Request info
    video_url = Column(String(2048), nullable=False)
    callback_url = Column(String(2048), nullable=True)
    options = Column(JSON, nullable=True)  # format, extract_audio, etc.

    # Status
    status = Column(String(20), default=TaskStatus.PENDING.value, nullable=False)
    progress = Column(Float, default=0.0)  # 0-100
    error_code = Column(String(50), nullable=True)
    error_message = Column(Text, nullable=True)

    # Video info (populated after download starts)
    video_title = Column(String(500), nullable=True)
    video_duration = Column(Integer, nullable=True)  # seconds
    video_thumbnail = Column(String(2048), nullable=True)
    video_filesize = Column(Integer, nullable=True)  # bytes

    # Result (populated after completion)
    download_url = Column(String(2048), nullable=True)
    file_name = Column(String(500), nullable=True)
    file_size = Column(Integer, nullable=True)  # bytes
    local_path = Column(String(1024), nullable=True)  # temp local path

    # Celery task tracking
    celery_task_id = Column(String(50), nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    def to_dict(self) -> dict:
        """Convert to dictionary for API response."""
        result = {
            "task_id": self.id,
            "video_url": self.video_url,
            "status": self.status,
            "progress": self.progress,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

        # Add video info if available
        if self.video_title:
            result["video_info"] = {
                "title": self.video_title,
                "duration": self.video_duration,
                "thumbnail": self.video_thumbnail,
                "filesize": self.video_filesize,
            }

        # Add result if completed
        if self.status == TaskStatus.COMPLETED.value:
            result["result"] = {
                "download_url": self.download_url,
                "file_name": self.file_name,
                "file_size": self.file_size,
            }
            result["completed_at"] = self.completed_at.isoformat() if self.completed_at else None

        # Add error if failed
        if self.status == TaskStatus.FAILED.value:
            result["error"] = {
                "code": self.error_code,
                "message": self.error_message,
            }

        return result

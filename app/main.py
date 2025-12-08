from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db, init_db
from app.models import Task, TaskStatus
from app.schemas import (
    CreateTaskRequest,
    CreateTaskResponse,
    TaskResponse,
    TaskListResponse,
    CancelTaskResponse,
    VideoInfoRequest,
    VideoInfoResponse,
    VideoFormat,
    HealthResponse,
    ErrorResponse,
    VideoInfo,
    TaskResult,
    TaskError,
)
from app.downloader import get_video_info, DownloadError
from app.tasks import download_video_task

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    logger.info("Initializing database...")
    init_db()
    logger.info("Application started")
    yield
    # Shutdown
    logger.info("Application shutdown")


# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Video download service powered by yt-dlp",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files
STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ============ API Routes ============

@app.post(
    "/api/v1/tasks",
    response_model=CreateTaskResponse,
    responses={400: {"model": ErrorResponse}},
    summary="Create download task",
    description="Submit a new video download task",
)
def create_task(
    request: CreateTaskRequest,
    db: Session = Depends(get_db),
):
    """Create a new download task."""
    # Validate URL (basic check)
    if not request.video_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Invalid video URL")

    # Validate storage configuration
    storage_type = request.storage_type.value if request.storage_type else "local"
    if storage_type != "local" and not request.storage_url:
        raise HTTPException(
            status_code=400,
            detail="storage_url is required when storage_type is not 'local'"
        )

    # Create task in database
    task = Task(
        video_url=request.video_url,
        callback_url=request.callback_url,
        options=request.options.model_dump() if request.options else None,
        status=TaskStatus.PENDING.value,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    # Queue Celery task with new parameters
    celery_task = download_video_task.delay(
        task_id=task.id,
        video_url=request.video_url,
        callback_url=request.callback_url,
        storage_type=storage_type,
        storage_url=request.storage_url,
        options=request.options.model_dump() if request.options else None,
    )

    # Update celery task id
    task.celery_task_id = celery_task.id
    db.commit()

    logger.info(f"Created task {task.id} for URL: {request.video_url} (storage: {storage_type})")

    return CreateTaskResponse(
        task_id=task.id,
        status=task.status,
        video_url=task.video_url,
        created_at=task.created_at,
    )


@app.get(
    "/api/v1/tasks/{task_id}",
    response_model=TaskResponse,
    responses={404: {"model": ErrorResponse}},
    summary="Get task status",
    description="Get the status and details of a download task",
)
def get_task(
    task_id: str,
    db: Session = Depends(get_db),
):
    """Get task by ID."""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return _task_to_response(task)


@app.get(
    "/api/v1/tasks",
    response_model=TaskListResponse,
    summary="List tasks",
    description="Get a paginated list of download tasks",
)
def list_tasks(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    status: Optional[str] = Query(None, description="Filter by status"),
    db: Session = Depends(get_db),
):
    """List all tasks with pagination."""
    query = db.query(Task)

    if status:
        query = query.filter(Task.status == status)

    total = query.count()
    tasks = (
        query
        .order_by(Task.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return TaskListResponse(
        total=total,
        page=page,
        page_size=page_size,
        tasks=[_task_to_response(t) for t in tasks],
    )


@app.delete(
    "/api/v1/tasks/{task_id}",
    response_model=CancelTaskResponse,
    responses={404: {"model": ErrorResponse}},
    summary="Cancel task",
    description="Cancel a pending or running download task",
)
def cancel_task(
    task_id: str,
    db: Session = Depends(get_db),
):
    """Cancel a task."""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status in [TaskStatus.COMPLETED.value, TaskStatus.FAILED.value]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel task with status: {task.status}"
        )

    # Cancel Celery task if running
    if task.celery_task_id:
        from app.celery_app import celery_app
        celery_app.control.revoke(task.celery_task_id, terminate=True)

    task.status = TaskStatus.CANCELLED.value
    db.commit()

    logger.info(f"Cancelled task {task_id}")

    return CancelTaskResponse(
        task_id=task_id,
        status=TaskStatus.CANCELLED.value,
        message="Task cancelled successfully",
    )


@app.post(
    "/api/v1/video-info",
    response_model=VideoInfoResponse,
    responses={400: {"model": ErrorResponse}},
    summary="Get video info",
    description="Extract video information without downloading",
)
def get_video_info_endpoint(request: VideoInfoRequest):
    """Get video info without downloading."""
    try:
        info = get_video_info(request.video_url)
        return VideoInfoResponse(
            title=info.title,
            duration=info.duration,
            thumbnail=info.thumbnail,
            uploader=info.uploader,
            upload_date=info.upload_date,
            formats=[
                VideoFormat(
                    format_id=f.get("format_id"),
                    ext=f.get("ext"),
                    resolution=f.get("resolution"),
                    filesize=f.get("filesize"),
                )
                for f in (info.formats or [])
            ],
        )
    except DownloadError as e:
        raise HTTPException(status_code=400, detail=f"{e.code}: {e.message}")
    except Exception as e:
        logger.exception(f"Error getting video info: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.get(
    "/api/v1/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Check service health and status",
)
def health_check(db: Session = Depends(get_db)):
    """Health check endpoint."""
    # Get yt-dlp version
    try:
        import yt_dlp
        yt_dlp_version = yt_dlp.version.__version__
    except Exception:
        yt_dlp_version = None

    # Count active downloads
    active_count = (
        db.query(Task)
        .filter(Task.status == TaskStatus.DOWNLOADING.value)
        .count()
    )

    # Count pending tasks (queue size approximation)
    pending_count = (
        db.query(Task)
        .filter(Task.status == TaskStatus.PENDING.value)
        .count()
    )

    return HealthResponse(
        status="healthy",
        version=settings.app_version,
        yt_dlp_version=yt_dlp_version,
        queue_size=pending_count,
        active_downloads=active_count,
    )


# ============ Helper Functions ============

def _task_to_response(task: Task) -> TaskResponse:
    """Convert Task model to TaskResponse."""
    video_info = None
    if task.video_title:
        video_info = VideoInfo(
            title=task.video_title,
            duration=task.video_duration,
            thumbnail=task.video_thumbnail,
            filesize=task.video_filesize,
        )

    result = None
    if task.status == TaskStatus.COMPLETED.value:
        result = TaskResult(
            download_url=task.download_url,
            file_name=task.file_name,
            file_size=task.file_size,
        )

    error = None
    if task.status == TaskStatus.FAILED.value:
        error = TaskError(
            code=task.error_code,
            message=task.error_message,
        )

    return TaskResponse(
        task_id=task.id,
        video_url=task.video_url,
        status=task.status,
        progress=task.progress or 0,
        video_info=video_info,
        result=result,
        error=error,
        created_at=task.created_at,
        updated_at=task.updated_at,
        completed_at=task.completed_at,
    )


# ============ Root Route ============

@app.get("/", include_in_schema=False)
def root():
    """Serve frontend debug page."""
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/docs")

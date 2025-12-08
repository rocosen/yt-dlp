from __future__ import annotations

import os
import uuid
import logging
from pathlib import Path
from typing import Callable, Any, Optional, List
from dataclasses import dataclass

import yt_dlp

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class VideoInfo:
    """Video metadata extracted from yt-dlp."""
    title: str
    duration: Optional[float]  # seconds, can be float
    thumbnail: Optional[str]
    filesize: Optional[int]  # bytes (estimated)
    uploader: Optional[str]
    upload_date: Optional[str]
    formats: Optional[List[dict]]


@dataclass
class DownloadResult:
    """Result of a successful download."""
    file_path: Path
    file_name: str
    file_size: int
    video_info: VideoInfo


class DownloadError(Exception):
    """Custom exception for download errors."""
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class VideoDownloader:
    """Wrapper around yt-dlp for downloading videos."""

    def __init__(
        self,
        download_dir: Optional[Path] = None,
        format_spec: Optional[str] = None,
        proxy: Optional[str] = None,
    ):
        self.download_dir = download_dir or settings.download_path
        self.format_spec = format_spec or settings.ytdlp_format
        self.proxy = proxy or settings.ytdlp_proxy

    def _get_base_opts(self) -> dict:
        """Get base yt-dlp options."""
        opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
        }
        if self.proxy:
            opts["proxy"] = self.proxy
        return opts

    def get_video_info(self, url: str) -> VideoInfo:
        """
        Extract video information without downloading.

        Args:
            url: Video URL

        Returns:
            VideoInfo object with metadata

        Raises:
            DownloadError: If extraction fails
        """
        opts = self._get_base_opts()
        opts["skip_download"] = True

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)

                if info is None:
                    raise DownloadError("EXTRACTION_ERROR", "Failed to extract video info")

                # Handle playlists - get first video
                if info.get("_type") == "playlist":
                    entries = info.get("entries", [])
                    if not entries:
                        raise DownloadError("EMPTY_PLAYLIST", "Playlist is empty")
                    info = entries[0]

                return VideoInfo(
                    title=info.get("title", "Unknown"),
                    duration=info.get("duration"),
                    thumbnail=info.get("thumbnail"),
                    filesize=info.get("filesize") or info.get("filesize_approx"),
                    uploader=info.get("uploader"),
                    upload_date=info.get("upload_date"),
                    formats=self._extract_formats(info.get("formats", [])),
                )

        except yt_dlp.utils.DownloadError as e:
            error_msg = str(e)
            if "Video unavailable" in error_msg or "Private video" in error_msg:
                raise DownloadError("VIDEO_UNAVAILABLE", "Video is unavailable or private")
            elif "Unsupported URL" in error_msg:
                raise DownloadError("UNSUPPORTED_SITE", f"Unsupported URL: {url}")
            else:
                raise DownloadError("EXTRACTION_ERROR", error_msg)
        except Exception as e:
            logger.exception(f"Unexpected error extracting info from {url}")
            raise DownloadError("UNKNOWN_ERROR", str(e))

    def _extract_formats(self, formats: list) -> List[dict]:
        """Extract relevant format info."""
        result = []
        for f in formats:
            if f.get("vcodec") != "none":  # Has video
                result.append({
                    "format_id": f.get("format_id"),
                    "ext": f.get("ext"),
                    "resolution": f.get("resolution") or f"{f.get('width', '?')}x{f.get('height', '?')}",
                    "filesize": f.get("filesize") or f.get("filesize_approx"),
                    "vcodec": f.get("vcodec"),
                    "acodec": f.get("acodec"),
                })
        return result[:10]  # Limit to 10 formats

    def _build_format_spec(
        self,
        download_type: str = "audio_video",
        video_quality: str = "720",
        format_spec: Optional[str] = None,
    ) -> str:
        """
        Build yt-dlp format specification based on download_type and video_quality.

        Args:
            download_type: audio, video, or audio_video
            video_quality: best, worst, or resolution (480, 720, 1080, 1440, 2160)
            format_spec: Override format spec (if provided, use directly)

        Returns:
            yt-dlp format string

        Format selection priority (with fallback):
        1. Try requested quality
        2. Fallback to best available if requested not found
        """
        # If explicit format_spec provided, use it directly
        if format_spec:
            return format_spec

        # Build format based on download_type and video_quality
        if download_type == "audio":
            # Audio only: best audio, fallback to best overall
            return "bestaudio/best"

        elif download_type == "video":
            # Video only, no audio
            if video_quality == "best":
                return "bestvideo/best"
            elif video_quality == "worst":
                return "worstvideo/worst"
            else:
                # Try requested resolution, fallback to best available
                return (
                    f"bestvideo[height<={video_quality}]/"
                    f"bestvideo/"
                    f"best[height<={video_quality}]/"
                    f"best"
                )

        else:  # audio_video (default)
            if video_quality == "best":
                return "bestvideo+bestaudio/bestvideo*+bestaudio/best"
            elif video_quality == "worst":
                return "worstvideo+worstaudio/worst"
            else:
                # Priority:
                # 1. video<=quality + best audio (separate streams, merged)
                # 2. best video + best audio (if quality not available)
                # 3. single file <=quality
                # 4. best single file
                return (
                    f"bestvideo[height<={video_quality}]+bestaudio/"
                    f"bestvideo+bestaudio/"
                    f"best[height<={video_quality}]/"
                    f"best"
                )

    def download(
        self,
        url: str,
        progress_callback: Optional[Callable[[float, str], None]] = None,
        download_type: str = "audio_video",
        video_quality: str = "720",
        format_spec: Optional[str] = None,
        extract_audio: bool = False,
        audio_format: str = "mp3",
    ) -> DownloadResult:
        """
        Download video from URL.

        Args:
            url: Video URL
            progress_callback: Optional callback(progress_percent, status_message)
            download_type: Download type - audio, video, or audio_video
            video_quality: Video quality - best, worst, or resolution (480, 720, 1080, 1440, 2160)
            format_spec: yt-dlp format specification (overrides download_type/video_quality)
            extract_audio: [Deprecated] Use download_type='audio' instead
            audio_format: Audio format when download_type is 'audio' (mp3, aac, wav, m4a)

        Returns:
            DownloadResult with file path and metadata

        Raises:
            DownloadError: If download fails
        """
        # Handle legacy extract_audio parameter
        if extract_audio and download_type == "audio_video":
            download_type = "audio"

        # Build format specification
        computed_format = self._build_format_spec(download_type, video_quality, format_spec)

        # Generate unique filename to avoid conflicts
        unique_id = str(uuid.uuid4())[:8]
        output_template = str(self.download_dir / f"%(title).100s_{unique_id}.%(ext)s")

        opts = self._get_base_opts()
        opts.update({
            "format": computed_format,
            "outtmpl": output_template,
            "noplaylist": True,  # Download only single video
            "socket_timeout": 30,
            "retries": 3,
            "fragment_retries": 3,
        })

        # Audio extraction post-processing
        if download_type == "audio":
            opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": audio_format,
                "preferredquality": "192",
            }]

        # Progress tracking
        downloaded_file = None
        video_info = None

        def progress_hook(d: dict):
            nonlocal downloaded_file

            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
                downloaded = d.get("downloaded_bytes", 0)

                if total > 0:
                    percent = (downloaded / total) * 100
                    if progress_callback:
                        speed = d.get("speed", 0)
                        speed_str = f"{speed / 1024 / 1024:.1f} MB/s" if speed else "..."
                        progress_callback(percent, f"Downloading: {percent:.1f}% ({speed_str})")

            elif d["status"] == "finished":
                downloaded_file = d.get("filename")
                if progress_callback:
                    progress_callback(100, "Download complete, processing...")

        opts["progress_hooks"] = [progress_hook]

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)

                if info is None:
                    raise DownloadError("DOWNLOAD_ERROR", "Failed to download video")

                # Handle playlist edge case
                if info.get("_type") == "playlist":
                    entries = info.get("entries", [])
                    if entries:
                        info = entries[0]

                video_info = VideoInfo(
                    title=info.get("title", "Unknown"),
                    duration=info.get("duration"),
                    thumbnail=info.get("thumbnail"),
                    filesize=info.get("filesize") or info.get("filesize_approx"),
                    uploader=info.get("uploader"),
                    upload_date=info.get("upload_date"),
                    formats=None,
                )

                # Find the downloaded file
                if downloaded_file and os.path.exists(downloaded_file):
                    file_path = Path(downloaded_file)
                else:
                    # Fallback: find the file by pattern
                    file_path = self._find_downloaded_file(info, unique_id)

                if not file_path or not file_path.exists():
                    raise DownloadError("FILE_NOT_FOUND", "Downloaded file not found")

                file_size = file_path.stat().st_size

                # Check file size limit
                if file_size > settings.max_file_size:
                    file_path.unlink()  # Delete oversized file
                    raise DownloadError(
                        "FILE_TOO_LARGE",
                        f"File size ({file_size / 1024 / 1024:.1f} MB) exceeds limit"
                    )

                return DownloadResult(
                    file_path=file_path,
                    file_name=file_path.name,
                    file_size=file_size,
                    video_info=video_info,
                )

        except yt_dlp.utils.DownloadError as e:
            error_msg = str(e)
            if "Video unavailable" in error_msg:
                raise DownloadError("VIDEO_UNAVAILABLE", "Video is unavailable")
            elif "HTTP Error 429" in error_msg or "rate limit" in error_msg.lower():
                raise DownloadError("RATE_LIMITED", "Rate limited by source site")
            else:
                raise DownloadError("DOWNLOAD_ERROR", error_msg)
        except DownloadError:
            raise
        except Exception as e:
            logger.exception(f"Unexpected error downloading {url}")
            raise DownloadError("UNKNOWN_ERROR", str(e))

    def _find_downloaded_file(self, info: dict, unique_id: str) -> Optional[Path]:
        """Find downloaded file by matching pattern."""
        title = info.get("title", "")[:100]

        # Look for files with our unique_id
        for file in self.download_dir.iterdir():
            if unique_id in file.name:
                return file

        return None


# Convenience functions
def get_video_info(url: str) -> VideoInfo:
    """Get video info without downloading."""
    downloader = VideoDownloader()
    return downloader.get_video_info(url)


def download_video(
    url: str,
    progress_callback: Optional[Callable[[float, str], None]] = None,
    **options
) -> DownloadResult:
    """Download video with optional progress callback."""
    downloader = VideoDownloader()
    return downloader.download(url, progress_callback=progress_callback, **options)

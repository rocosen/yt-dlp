"""
Cloud storage upload module.

Supports:
- Local storage (default)
- AWS S3
- Google Cloud Storage (GCS)
- S3-compatible storage (Alibaba OSS, MinIO, Cloudflare R2, etc.)
"""

from __future__ import annotations

import os
import re
import logging
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger(__name__)


class StorageError(Exception):
    """Custom exception for storage errors."""
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class StorageUploader:
    """
    Cloud storage uploader.

    Supports multiple storage backends:
    - local: Keep file locally (default)
    - s3: Upload to AWS S3
    - gcs: Upload to Google Cloud Storage
    - s3_compatible: Upload to S3-compatible storage (OSS, MinIO, R2, etc.)
    """

    def upload(
        self,
        local_path: Path,
        storage_type: str,
        storage_url: Optional[str] = None,
        delete_local: bool = False,
    ) -> str:
        """
        Upload file to cloud storage.

        Args:
            local_path: Path to local file
            storage_type: Storage type (local, s3, gcs, s3_compatible)
            storage_url: Storage URL (required for cloud storage)
            delete_local: Delete local file after upload

        Returns:
            URL to the uploaded file

        Raises:
            StorageError: If upload fails
        """
        if not local_path.exists():
            raise StorageError("FILE_NOT_FOUND", f"Local file not found: {local_path}")

        if storage_type == "local":
            return f"file://{local_path}"

        if not storage_url:
            raise StorageError("MISSING_STORAGE_URL", "storage_url is required for cloud storage")

        try:
            if storage_type == "s3":
                remote_url = self._upload_s3(local_path, storage_url)
            elif storage_type == "gcs":
                remote_url = self._upload_gcs(local_path, storage_url)
            elif storage_type == "s3_compatible":
                remote_url = self._upload_s3_compatible(local_path, storage_url)
            else:
                raise StorageError("INVALID_STORAGE_TYPE", f"Unknown storage type: {storage_type}")

            # Delete local file if requested
            if delete_local and remote_url:
                try:
                    local_path.unlink()
                    logger.info(f"Deleted local file after upload: {local_path}")
                except Exception as e:
                    logger.warning(f"Failed to delete local file: {e}")

            return remote_url

        except StorageError:
            raise
        except Exception as e:
            logger.exception(f"Failed to upload to {storage_type}")
            raise StorageError("UPLOAD_ERROR", str(e))

    def _parse_s3_url(self, storage_url: str) -> Tuple[str, str]:
        """
        Parse S3 URL to extract bucket and prefix.

        Supports:
        - s3://bucket/prefix/
        - s3://bucket

        Returns:
            Tuple of (bucket_name, prefix)
        """
        # Remove trailing slash
        storage_url = storage_url.rstrip("/")

        if storage_url.startswith("s3://"):
            path = storage_url[5:]  # Remove 's3://'
            parts = path.split("/", 1)
            bucket = parts[0]
            prefix = parts[1] if len(parts) > 1 else ""
            return bucket, prefix

        raise StorageError("INVALID_S3_URL", f"Invalid S3 URL format: {storage_url}")

    def _parse_gcs_url(self, storage_url: str) -> Tuple[str, str]:
        """
        Parse GCS URL to extract bucket and prefix.

        Supports:
        - gs://bucket/prefix/
        - gs://bucket

        Returns:
            Tuple of (bucket_name, prefix)
        """
        storage_url = storage_url.rstrip("/")

        if storage_url.startswith("gs://"):
            path = storage_url[5:]  # Remove 'gs://'
            parts = path.split("/", 1)
            bucket = parts[0]
            prefix = parts[1] if len(parts) > 1 else ""
            return bucket, prefix

        raise StorageError("INVALID_GCS_URL", f"Invalid GCS URL format: {storage_url}")

    def _parse_s3_compatible_url(self, storage_url: str) -> dict:
        """
        Parse S3-compatible storage URL.

        Supports:
        - https://ACCESS_KEY:SECRET@endpoint/bucket/prefix
        - https://endpoint/bucket/prefix (uses env credentials)

        Returns:
            Dict with endpoint_url, bucket, prefix, access_key, secret_key
        """
        parsed = urlparse(storage_url)

        # Extract credentials from URL if present
        access_key = parsed.username
        secret_key = parsed.password

        # Build endpoint URL
        endpoint_url = f"{parsed.scheme}://{parsed.hostname}"
        if parsed.port:
            endpoint_url += f":{parsed.port}"

        # Parse path for bucket and prefix
        path_parts = parsed.path.strip("/").split("/", 1)
        bucket = path_parts[0] if path_parts else ""
        prefix = path_parts[1] if len(path_parts) > 1 else ""

        if not bucket:
            raise StorageError("INVALID_S3_URL", "Bucket name is required in storage_url")

        return {
            "endpoint_url": endpoint_url,
            "bucket": bucket,
            "prefix": prefix,
            "access_key": access_key,
            "secret_key": secret_key,
        }

    def _upload_s3(self, local_path: Path, storage_url: str) -> str:
        """Upload file to AWS S3."""
        try:
            import boto3
            from botocore.exceptions import ClientError
        except ImportError:
            raise StorageError("MISSING_DEPENDENCY", "boto3 is required for S3 upload. Install with: pip install boto3")

        bucket, prefix = self._parse_s3_url(storage_url)

        # Build the S3 key
        key = f"{prefix}/{local_path.name}" if prefix else local_path.name
        key = key.lstrip("/")

        logger.info(f"Uploading to S3: s3://{bucket}/{key}")

        try:
            s3_client = boto3.client("s3")
            s3_client.upload_file(str(local_path), bucket, key)

            # Return the S3 URL
            region = s3_client.get_bucket_location(Bucket=bucket).get("LocationConstraint", "us-east-1")
            if region is None:
                region = "us-east-1"

            return f"https://{bucket}.s3.{region}.amazonaws.com/{key}"

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            raise StorageError(f"S3_ERROR_{error_code}", str(e))

    def _upload_gcs(self, local_path: Path, storage_url: str) -> str:
        """Upload file to Google Cloud Storage."""
        try:
            from google.cloud import storage
        except ImportError:
            raise StorageError(
                "MISSING_DEPENDENCY",
                "google-cloud-storage is required for GCS upload. Install with: pip install google-cloud-storage"
            )

        bucket_name, prefix = self._parse_gcs_url(storage_url)

        # Build the blob name
        blob_name = f"{prefix}/{local_path.name}" if prefix else local_path.name
        blob_name = blob_name.lstrip("/")

        logger.info(f"Uploading to GCS: gs://{bucket_name}/{blob_name}")

        try:
            client = storage.Client()
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(blob_name)
            blob.upload_from_filename(str(local_path))

            return f"https://storage.googleapis.com/{bucket_name}/{blob_name}"

        except Exception as e:
            raise StorageError("GCS_ERROR", str(e))

    def _upload_s3_compatible(self, local_path: Path, storage_url: str) -> str:
        """Upload file to S3-compatible storage (OSS, MinIO, R2, etc.)."""
        try:
            import boto3
            from botocore.exceptions import ClientError
            from botocore.config import Config
        except ImportError:
            raise StorageError("MISSING_DEPENDENCY", "boto3 is required for S3-compatible upload. Install with: pip install boto3")

        config = self._parse_s3_compatible_url(storage_url)

        # Build the key
        key = f"{config['prefix']}/{local_path.name}" if config["prefix"] else local_path.name
        key = key.lstrip("/")

        logger.info(f"Uploading to S3-compatible storage: {config['endpoint_url']}/{config['bucket']}/{key}")

        try:
            # Create S3 client with custom endpoint
            s3_client = boto3.client(
                "s3",
                endpoint_url=config["endpoint_url"],
                aws_access_key_id=config["access_key"] or os.environ.get("AWS_ACCESS_KEY_ID"),
                aws_secret_access_key=config["secret_key"] or os.environ.get("AWS_SECRET_ACCESS_KEY"),
                config=Config(signature_version="s3v4"),
            )

            s3_client.upload_file(str(local_path), config["bucket"], key)

            # Return the URL
            return f"{config['endpoint_url']}/{config['bucket']}/{key}"

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            raise StorageError(f"S3_COMPATIBLE_ERROR_{error_code}", str(e))


# Convenience function
def upload_to_storage(
    local_path: Path,
    storage_type: str = "local",
    storage_url: Optional[str] = None,
    delete_local: bool = False,
) -> str:
    """Upload file to storage and return URL."""
    uploader = StorageUploader()
    return uploader.upload(local_path, storage_type, storage_url, delete_local)

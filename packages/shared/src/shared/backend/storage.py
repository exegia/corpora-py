import logging
from typing import Any, BinaryIO

from shared.backend.client import supabase

logger = logging.getLogger(__name__)


def upload(
    bucket: str,
    path: str,
    file: bytes | bytearray | BinaryIO | str,
    *,
    content_type: str | None = None,
    upsert: bool = False,
) -> Any:
    logger.info("Starting upload to storage bucket '%s' at '%s'", bucket, path)
    storage = supabase.storage.from_(bucket)
    logger.debug("Created storage client for bucket '%s'", bucket)

    try:
        file_options = {"content-type": content_type} if content_type else None
        result = storage.upload(path=path, file=file, file_options=file_options, upsert=upsert)
        logger.info("Upload completed for storage bucket '%s' at '%s'", bucket, path)
        return result
    except Exception:
        logger.exception("Upload failed for storage bucket '%s' at '%s'", bucket, path)
        raise


def download(bucket: str, path: str) -> bytes:
    logger.info("Starting download from storage bucket '%s' at '%s'", bucket, path)
    storage = supabase.storage.from_(bucket)
    logger.debug("Created storage client for bucket '%s'", bucket)

    try:
        result = storage.download(path)
        logger.info("Download completed for storage bucket '%s' at '%s'", bucket, path)
        return result
    except Exception:
        logger.exception("Download failed for storage bucket '%s' at '%s'", bucket, path)
        raise


def remove(bucket: str, path: str) -> Any:
    logger.info("Starting removal from storage bucket '%s' at '%s'", bucket, path)
    storage = supabase.storage.from_(bucket)
    logger.debug("Created storage client for bucket '%s'", bucket)

    try:
        result = storage.remove([path])
        logger.info("Removal completed for storage bucket '%s' at '%s'", bucket, path)
        return result
    except Exception:
        logger.exception("Removal failed for storage bucket '%s' at '%s'", bucket, path)
        raise

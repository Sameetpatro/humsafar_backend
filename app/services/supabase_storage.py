# app/services/supabase_storage.py
# Handles all Supabase Storage interactions for generated videos.
# Uses the official supabase-py client (sync) wrapped in asyncio.to_thread
# so it integrates cleanly with FastAPI's async environment without blocking.

import asyncio
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Environment ───────────────────────────────────────────────────────────────
SUPABASE_URL        = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
SUPABASE_BUCKET     = os.getenv("SUPABASE_BUCKET", "videos")

# Storage path prefix inside the bucket
STORAGE_PREFIX = "generated"


def _get_client():
    """
    Lazily create a Supabase client.
    Raises RuntimeError if env vars are missing.
    """
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in environment"
        )
    from supabase import create_client, Client  # type: ignore
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def _storage_path(video_hash: str) -> str:
    """Returns the object path inside the bucket: generated/{hash}.mp4"""
    return f"{STORAGE_PREFIX}/{video_hash}.mp4"


def _public_url(video_hash: str) -> str:
    """
    Constructs the Supabase public URL for a stored video.
    Pattern: {SUPABASE_URL}/storage/v1/object/public/{bucket}/{path}
    """
    return (
        f"{SUPABASE_URL.rstrip('/')}"
        f"/storage/v1/object/public/{SUPABASE_BUCKET}"
        f"/{_storage_path(video_hash)}"
    )


# ── Public async API ──────────────────────────────────────────────────────────

async def upload_video(local_path: str, video_hash: str) -> str:
    """
    Upload a local MP4 file to Supabase Storage.

    Args:
        local_path:  Absolute or relative path to the .mp4 file on disk.
        video_hash:  Hash string used as the filename inside the bucket.

    Returns:
        Public URL of the uploaded video.

    Raises:
        RuntimeError: On missing env vars, missing file, or upload failure.
    """
    path = Path(local_path)
    if not path.exists():
        raise RuntimeError(f"Local video file not found: {local_path}")

    file_size = path.stat().st_size
    logger.info(
        f"[Supabase] Uploading {file_size:,} bytes → "
        f"bucket={SUPABASE_BUCKET} path={_storage_path(video_hash)}"
    )

    def _sync_upload():
        client = _get_client()
        with open(local_path, "rb") as f:
            data = f.read()

        response = client.storage.from_(SUPABASE_BUCKET).upload(
            path=_storage_path(video_hash),
            file=data,
            file_options={"content-type": "video/mp4", "upsert": "true"},
        )
        return response

    try:
        await asyncio.to_thread(_sync_upload)
    except Exception as exc:
        raise RuntimeError(f"Supabase upload failed for hash={video_hash}: {exc}") from exc

    public_url = _public_url(video_hash)
    logger.info(f"[Supabase] Upload complete ✓ → {public_url}")
    return public_url


async def delete_video(video_hash: str) -> bool:
    """
    Delete a video from Supabase Storage.

    Args:
        video_hash: Hash of the video to delete.

    Returns:
        True if deletion succeeded, False if the file was not found.

    Raises:
        RuntimeError: On missing env vars or unexpected API errors.
    """
    object_path = _storage_path(video_hash)
    logger.info(f"[Supabase] Deleting bucket={SUPABASE_BUCKET} path={object_path}")

    def _sync_delete():
        client = _get_client()
        response = client.storage.from_(SUPABASE_BUCKET).remove([object_path])
        return response

    try:
        response = await asyncio.to_thread(_sync_delete)
    except Exception as exc:
        raise RuntimeError(f"Supabase delete failed for hash={video_hash}: {exc}") from exc

    # supabase-py returns a list of removed objects; empty list = not found
    if not response:
        logger.warning(f"[Supabase] Object not found or already deleted: {object_path}")
        return False

    logger.info(f"[Supabase] Deleted ✓ path={object_path}")
    return True


async def video_exists(video_hash: str) -> str | None:
    """
    Check if a video exists in Supabase Storage.

    Returns:
        Public URL if the video exists, None otherwise.
    """
    object_path = _storage_path(video_hash)

    def _sync_list():
        client = _get_client()
        # List objects under the prefix to check existence
        items = client.storage.from_(SUPABASE_BUCKET).list(
            path=STORAGE_PREFIX,
            options={"search": f"{video_hash}.mp4", "limit": 1},
        )
        return items

    try:
        items = await asyncio.to_thread(_sync_list)
    except Exception as exc:
        logger.warning(f"[Supabase] Existence check failed for hash={video_hash}: {exc}")
        return None

    if items:
        url = _public_url(video_hash)
        logger.info(f"[Supabase] Exists ✓ {url}")
        return url

    return None
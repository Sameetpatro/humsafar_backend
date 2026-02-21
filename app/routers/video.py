# app/routers/video.py
# NEW FILE
#
# Provides:
#   GET  /video-status/{id_or_hash}  — check if video exists / progress
#   POST /generate-video             — trigger on-demand prompt video generation

import asyncio
import hashlib
import logging
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["video"])

# ── Path configuration ────────────────────────────────────────────────────────
STATIC_DIR     = Path("static/videos")
OVERVIEW_DIR   = STATIC_DIR / "overview"
PROMPT_DIR     = STATIC_DIR / "prompt"

# Ensure directories exist on startup
OVERVIEW_DIR.mkdir(parents=True, exist_ok=True)
PROMPT_DIR.mkdir(parents=True, exist_ok=True)

# ── In-memory generation state ────────────────────────────────────────────────
# Maps hash → {"status": "generating"|"ready"|"failed", "progress": int, "message": str}
# For production, swap this for Redis or a DB row.
_generation_state: dict[str, dict] = {}


# ── Request / Response models ─────────────────────────────────────────────────
class GenerateVideoRequest(BaseModel):
    prompt:    str
    bot_text:  str
    site_id:   str
    site_name: str


class GenerateVideoResponse(BaseModel):
    hash:    str
    status:  str   # "generating" | "ready"
    url:     str | None = None


class VideoStatusResponse(BaseModel):
    status:   str   # "ready" | "generating" | "not_started" | "failed"
    url:      str | None = None
    progress: int = 0
    message:  str = ""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_hash(prompt: str, bot_text: str, site_id: str) -> str:
    """Deterministic SHA-256 hash — same prompt+answer always gets same video."""
    raw = f"{site_id}::{prompt.strip().lower()}::{bot_text.strip()[:200]}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _video_url(subpath: str) -> str:
    base = os.getenv("BASE_URL", "https://humsafar-backend-59ic.onrender.com")
    return f"{base}/static/videos/{subpath}"


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/video-status/{id_or_hash}", response_model=VideoStatusResponse)
async def get_video_status(id_or_hash: str):
    """
    Check video availability.

    Priority:
      1. Check prompt video at static/videos/prompt/{hash}.mp4
      2. Check overview video at static/videos/overview/{id}.mp4
      3. Check in-memory generation state
      4. Return not_started
    """
    # 1. Check prompt video first (hash is 24 hex chars)
    prompt_path = PROMPT_DIR / f"{id_or_hash}.mp4"
    if prompt_path.exists():
        return VideoStatusResponse(
            status = "ready",
            url    = _video_url(f"prompt/{id_or_hash}.mp4"),
            progress = 100
        )

    # 2. Check overview video
    overview_path = OVERVIEW_DIR / f"{id_or_hash}.mp4"
    if overview_path.exists():
        return VideoStatusResponse(
            status = "ready",
            url    = _video_url(f"overview/{id_or_hash}.mp4"),
            progress = 100
        )

    # 3. Check in-memory generation state
    state = _generation_state.get(id_or_hash)
    if state:
        return VideoStatusResponse(
            status   = state["status"],
            progress = state.get("progress", 0),
            message  = state.get("message", ""),
            url      = state.get("url")
        )

    return VideoStatusResponse(status="not_started", progress=0)


@router.post("/generate-video", response_model=GenerateVideoResponse)
async def generate_video(
    req: GenerateVideoRequest,
    background_tasks: BackgroundTasks
):
    """
    Trigger on-demand prompt video generation.

    If video already exists → return immediately with status=ready.
    Otherwise → enqueue background task and return hash for polling.
    """
    video_hash = _make_hash(req.prompt, req.bot_text, req.site_id)

    # Already on disk?
    prompt_path = PROMPT_DIR / f"{video_hash}.mp4"
    if prompt_path.exists():
        logger.info(f"[video] Cache hit for hash={video_hash}")
        return GenerateVideoResponse(
            hash   = video_hash,
            status = "ready",
            url    = _video_url(f"prompt/{video_hash}.mp4")
        )

    # Already generating?
    if video_hash in _generation_state:
        state = _generation_state[video_hash]
        return GenerateVideoResponse(
            hash   = video_hash,
            status = state["status"],
            url    = state.get("url")
        )

    # Enqueue background generation
    _generation_state[video_hash] = {"status": "generating", "progress": 0}
    background_tasks.add_task(
        _generate_video_task,
        video_hash = video_hash,
        prompt     = req.prompt,
        bot_text   = req.bot_text,
        site_name  = req.site_name,
        site_id    = req.site_id
    )

    logger.info(f"[video] Generation enqueued — hash={video_hash} site={req.site_name}")
    return GenerateVideoResponse(hash=video_hash, status="generating")


# ── Background task ───────────────────────────────────────────────────────────

async def _generate_video_task(
    video_hash: str,
    prompt: str,
    bot_text: str,
    site_name: str,
    site_id: str
):
    """
    Full async video generation pipeline:
      1. Generate narration audio (TTS)         → progress 10→40
      2. Fetch/select monument images            → progress 40→60
      3. Run FFmpeg: images + audio → MP4        → progress 60→95
      4. Save to PROMPT_DIR                      → progress 100, status ready

    All I/O is async + non-blocking.
    FFmpeg runs in a thread pool executor so it never blocks the event loop.
    """
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    def _update(progress: int, message: str = ""):
        _generation_state[video_hash] = {
            "status":   "generating",
            "progress": progress,
            "message":  message
        }
        logger.info(f"[video/{video_hash}] {progress}% — {message}")

    try:
        _update(5, "Analyzing content…")
        await asyncio.sleep(0.5)

        # Stage 1: TTS narration
        _update(10, "Generating narration…")
        narration_bytes = await _generate_narration(bot_text)
        _update(40, "Narration ready")

        # Stage 2: Images
        _update(45, "Crafting cinematic scenes…")
        image_paths = await _fetch_monument_images(site_id, site_name)
        _update(60, "Scenes composed")

        # Stage 3: FFmpeg (runs in executor — non-blocking)
        _update(65, "Adding narration & visuals…")
        output_path = PROMPT_DIR / f"{video_hash}.mp4"

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            await loop.run_in_executor(
                pool,
                _run_ffmpeg,
                image_paths,
                narration_bytes,
                str(output_path)
            )
        _update(95, "Finalizing…")

        # Confirm file exists
        if not output_path.exists():
            raise RuntimeError("FFmpeg did not produce output file")

        _generation_state[video_hash] = {
            "status":   "ready",
            "progress": 100,
            "url":      _video_url(f"prompt/{video_hash}.mp4")
        }
        logger.info(f"[video/{video_hash}] Generation complete ✓")

    except Exception as exc:
        logger.error(f"[video/{video_hash}] Generation FAILED: {exc}", exc_info=True)
        _generation_state[video_hash] = {
            "status":   "failed",
            "progress": 0,
            "message":  str(exc)
        }


async def _generate_narration(text: str) -> bytes:
    """Call Sarvam TTS to produce WAV narration for the video."""
    from app.services.sarvam_tts import synthesize
    return await synthesize(text, language_code="en-IN")


async def _fetch_monument_images(site_id: str, site_name: str) -> list[str]:
    """
    Return list of image file paths for the monument.
    Strategy: check static/images/{site_id}/ first; fall back to a blank frame.
    """
    images_dir = Path("static/images") / site_id
    if images_dir.exists():
        paths = sorted(images_dir.glob("*.jpg"))[:5]
        if paths:
            return [str(p) for p in paths]

    # Fallback — blank 1920×1080 JPEG created on-the-fly
    fallback = Path("static/images/placeholder.jpg")
    fallback.parent.mkdir(parents=True, exist_ok=True)
    if not fallback.exists():
        _create_placeholder_image(str(fallback))
    return [str(fallback)]


def _create_placeholder_image(path: str):
    """Create a minimal black JPEG placeholder if Pillow is unavailable."""
    try:
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (1920, 1080), color=(5, 13, 26))
        draw = ImageDraw.Draw(img)
        draw.text((860, 520), "🏛️", fill=(255, 213, 79))
        img.save(path, "JPEG")
    except ImportError:
        # Write raw JPEG header bytes for a 1×1 black pixel (minimal valid JPEG)
        minimal_jpeg = bytes([
            0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00, 0x01,
            0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0xFF, 0xDB, 0x00, 0x43,
            0x00, 0x08, 0x06, 0x06, 0x07, 0x06, 0x05, 0x08, 0x07, 0x07, 0x07, 0x09,
            0x09, 0x08, 0x0A, 0x0C, 0x14, 0x0D, 0x0C, 0x0B, 0x0B, 0x0C, 0x19, 0x12,
            0x13, 0x0F, 0x14, 0x1D, 0x1A, 0x1F, 0x1E, 0x1D, 0x1A, 0x1C, 0x1C, 0x20,
            0x24, 0x2E, 0x27, 0x20, 0x22, 0x2C, 0x23, 0x1C, 0x1C, 0x28, 0x37, 0x29,
            0x2C, 0x30, 0x31, 0x34, 0x34, 0x34, 0x1F, 0x27, 0x39, 0x3D, 0x38, 0x32,
            0x3C, 0x2E, 0x33, 0x34, 0x32, 0xFF, 0xC0, 0x00, 0x0B, 0x08, 0x00, 0x01,
            0x00, 0x01, 0x01, 0x01, 0x11, 0x00, 0xFF, 0xC4, 0x00, 0x1F, 0x00, 0x00,
            0x01, 0x05, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
            0x09, 0x0A, 0x0B, 0xFF, 0xC4, 0x00, 0xB5, 0x10, 0x00, 0x02, 0x01, 0x03,
            0x03, 0x02, 0x04, 0x03, 0x05, 0x05, 0x04, 0x04, 0x00, 0x00, 0x01, 0x7D,
            0xFF, 0xDA, 0x00, 0x08, 0x01, 0x01, 0x00, 0x00, 0x3F, 0x00, 0xFB, 0xD7,
            0xFF, 0xD9
        ])
        with open(path, "wb") as f:
            f.write(minimal_jpeg)


def _run_ffmpeg(image_paths: list[str], audio_bytes: bytes, output_path: str):
    """
    Synchronous FFmpeg call — runs in thread pool executor.

    Pipeline:
      • Each image shown for (total_duration / num_images) seconds
      • Audio track from WAV bytes (written to temp file)
      • Output: H.264 video, AAC audio, MP4 container
      • Resolution: 1920×1080, 30fps
    """
    import subprocess
    import tempfile
    import os

    with tempfile.TemporaryDirectory() as tmp:
        # Write audio
        audio_path = os.path.join(tmp, "narration.wav")
        with open(audio_path, "wb") as f:
            f.write(audio_bytes)

        # Write image list for FFmpeg concat demuxer
        # Each image displayed for equal duration
        num_images = len(image_paths)
        # Get audio duration via ffprobe
        try:
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", audio_path],
                capture_output=True, text=True, timeout=10
            )
            total_duration = float(probe.stdout.strip())
        except Exception:
            total_duration = 30.0  # fallback

        duration_per_image = max(total_duration / num_images, 2.0)

        concat_list = os.path.join(tmp, "images.txt")
        with open(concat_list, "w") as f:
            for img_path in image_paths:
                f.write(f"file '{img_path}'\n")
                f.write(f"duration {duration_per_image:.2f}\n")
            # FFmpeg concat requires the last file to be repeated without duration
            f.write(f"file '{image_paths[-1]}'\n")

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", concat_list,
            "-i", audio_path,
            "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-shortest",
            "-r", "30",
            output_path
        ]

        logger.info(f"[ffmpeg] Running: {' '.join(cmd[:6])} ...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg failed:\n{result.stderr[-1000:]}")

        logger.info(f"[ffmpeg] Output: {output_path} ({os.path.getsize(output_path)} bytes)")
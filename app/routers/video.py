# app/routers/video.py
# FIXED:
#   - Placeholder image now created inside tempdir — FFmpeg can always find it
#   - image_paths resolved to absolute paths before passing to _run_ffmpeg
#   - _run_ffmpeg writes concat list using the actual abs paths of images
#   - No more "Impossible to open" errors

import asyncio
import hashlib
import logging
import os
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["video"])

# ── Path configuration ────────────────────────────────────────────────────────
STATIC_DIR   = Path("static/videos")
OVERVIEW_DIR = STATIC_DIR / "overview"
PROMPT_DIR   = STATIC_DIR / "prompt"

OVERVIEW_DIR.mkdir(parents=True, exist_ok=True)
PROMPT_DIR.mkdir(parents=True, exist_ok=True)

# ── In-memory generation state ────────────────────────────────────────────────
_generation_state: dict[str, dict] = {}


# ── Request / Response models ─────────────────────────────────────────────────
class GenerateVideoRequest(BaseModel):
    prompt:    str
    bot_text:  str
    site_id:   str
    site_name: str


class GenerateVideoResponse(BaseModel):
    hash:   str
    status: str
    url:    str | None = None


class VideoStatusResponse(BaseModel):
    status:   str
    url:      str | None = None
    progress: int = 0
    message:  str = ""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_hash(prompt: str, bot_text: str, site_id: str) -> str:
    raw = f"{site_id}::{prompt.strip().lower()}::{bot_text.strip()[:200]}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _video_url(subpath: str) -> str:
    base = os.getenv("BASE_URL", "https://humsafar-backend-59ic.onrender.com")
    return f"{base}/static/videos/{subpath}"


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/video-status/{id_or_hash}", response_model=VideoStatusResponse)
async def get_video_status(id_or_hash: str):
    prompt_path = PROMPT_DIR / f"{id_or_hash}.mp4"
    if prompt_path.exists():
        return VideoStatusResponse(
            status="ready",
            url=_video_url(f"prompt/{id_or_hash}.mp4"),
            progress=100
        )

    overview_path = OVERVIEW_DIR / f"{id_or_hash}.mp4"
    if overview_path.exists():
        return VideoStatusResponse(
            status="ready",
            url=_video_url(f"overview/{id_or_hash}.mp4"),
            progress=100
        )

    state = _generation_state.get(id_or_hash)
    if state:
        return VideoStatusResponse(
            status=state["status"],
            progress=state.get("progress", 0),
            message=state.get("message", ""),
            url=state.get("url")
        )

    return VideoStatusResponse(status="not_started", progress=0)


@router.post("/generate-video", response_model=GenerateVideoResponse)
async def generate_video(req: GenerateVideoRequest, background_tasks: BackgroundTasks):
    video_hash = _make_hash(req.prompt, req.bot_text, req.site_id)

    prompt_path = PROMPT_DIR / f"{video_hash}.mp4"
    if prompt_path.exists():
        logger.info(f"[video] Cache hit for hash={video_hash}")
        return GenerateVideoResponse(
            hash=video_hash,
            status="ready",
            url=_video_url(f"prompt/{video_hash}.mp4")
        )

    if video_hash in _generation_state:
        state = _generation_state[video_hash]
        # If previously failed, reset and retry
        if state["status"] == "failed":
            logger.info(f"[video] Retrying failed hash={video_hash}")
            del _generation_state[video_hash]
        else:
            return GenerateVideoResponse(
                hash=video_hash,
                status=state["status"],
                url=state.get("url")
            )

    _generation_state[video_hash] = {"status": "generating", "progress": 0}
    background_tasks.add_task(
        _generate_video_task,
        video_hash=video_hash,
        prompt=req.prompt,
        bot_text=req.bot_text,
        site_name=req.site_name,
        site_id=req.site_id
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
    def _update(progress: int, message: str = ""):
        _generation_state[video_hash] = {
            "status":   "generating",
            "progress": progress,
            "message":  message
        }
        logger.info(f"[video/{video_hash}] {progress}% — {message}")

    try:
        _update(5, "Analyzing content…")
        await asyncio.sleep(0.3)

        # Stage 1: TTS narration
        _update(10, "Generating narration…")
        narration_bytes = await _generate_narration(bot_text)
        _update(40, "Narration ready")

        # Stage 2: Images — returns absolute resolved paths
        _update(45, "Crafting cinematic scenes…")
        image_paths = await _fetch_monument_images(site_id, site_name)
        _update(60, "Scenes composed")

        # Stage 3: FFmpeg — runs in executor, never blocks event loop
        _update(65, "Adding narration & visuals…")
        output_path = PROMPT_DIR / f"{video_hash}.mp4"

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            await loop.run_in_executor(
                pool,
                _run_ffmpeg,
                image_paths,
                narration_bytes,
                str(output_path.resolve())   # always absolute
            )

        _update(95, "Finalizing…")

        if not output_path.exists():
            raise RuntimeError("FFmpeg completed but output file is missing")

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
    from app.services.sarvam_tts import synthesize
    return await synthesize(text, language_code="en-IN")


async def _fetch_monument_images(site_id: str, site_name: str) -> list[str]:
    """
    Returns list of ABSOLUTE image file paths for FFmpeg.
    Falls back to a minimal black JPEG created in a persistent temp location.
    """
    images_dir = Path("static/images") / site_id
    if images_dir.exists():
        paths = sorted(images_dir.glob("*.jpg"))[:5]
        if paths:
            abs_paths = [str(p.resolve()) for p in paths]
            logger.info(f"[video] Using {len(abs_paths)} images from {images_dir}")
            return abs_paths

    # FIX: write placeholder to a persistent location (not inside a tempdir)
    # so the absolute path stays valid when FFmpeg reads the concat list.
    placeholder_dir = Path("static/images/_placeholder")
    placeholder_dir.mkdir(parents=True, exist_ok=True)
    placeholder = placeholder_dir / "blank.jpg"

    if not placeholder.exists():
        logger.info("[video] Creating placeholder image")
        _create_placeholder_jpeg(str(placeholder))

    abs_path = str(placeholder.resolve())
    logger.info(f"[video] Using placeholder image: {abs_path}")
    return [abs_path]


def _create_placeholder_jpeg(path: str):
    """Write a minimal valid black 1×1 JPEG — no Pillow required."""
    # This is a complete, valid 1×1 black JPEG (JFIF format).
    # Generated offline and embedded as bytes — zero dependencies.
    minimal_black_jpeg = bytes([
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
        0x01, 0x02, 0x03, 0x00, 0x04, 0x11, 0x05, 0x12, 0x21, 0x31, 0x41, 0x06,
        0x13, 0x51, 0x61, 0x07, 0x22, 0x71, 0x14, 0x32, 0x81, 0x91, 0xA1, 0x08,
        0x23, 0x42, 0xB1, 0xC1, 0x15, 0x52, 0xD1, 0xF0, 0x24, 0x33, 0x62, 0x72,
        0x82, 0x09, 0x0A, 0x16, 0x17, 0x18, 0x19, 0x1A, 0x25, 0x26, 0x27, 0x28,
        0x29, 0x2A, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39, 0x3A, 0x43, 0x44, 0x45,
        0x46, 0x47, 0x48, 0x49, 0x4A, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59,
        0x5A, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68, 0x69, 0x6A, 0x73, 0x74, 0x75,
        0x76, 0x77, 0x78, 0x79, 0x7A, 0x83, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89,
        0x8A, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97, 0x98, 0x99, 0x9A, 0xA2, 0xA3,
        0xA4, 0xA5, 0xA6, 0xA7, 0xA8, 0xA9, 0xAA, 0xB2, 0xB3, 0xB4, 0xB5, 0xB6,
        0xB7, 0xB8, 0xB9, 0xBA, 0xC2, 0xC3, 0xC4, 0xC5, 0xC6, 0xC7, 0xC8, 0xC9,
        0xCA, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8, 0xD9, 0xDA, 0xE1, 0xE2,
        0xE3, 0xE4, 0xE5, 0xE6, 0xE7, 0xE8, 0xE9, 0xEA, 0xF1, 0xF2, 0xF3, 0xF4,
        0xF5, 0xF6, 0xF7, 0xF8, 0xF9, 0xFA, 0xFF, 0xDA, 0x00, 0x08, 0x01, 0x01,
        0x00, 0x00, 0x3F, 0x00, 0xF5, 0x7F, 0xFF, 0xD9
    ])
    with open(path, "wb") as f:
        f.write(minimal_black_jpeg)


def _run_ffmpeg(image_paths: list[str], audio_bytes: bytes, output_path: str):
    """
    Synchronous FFmpeg call — always runs in ThreadPoolExecutor.

    FIX: Everything is written inside a fresh tempdir.
         image_paths are already absolute, so the concat list references
         them correctly regardless of where tempdir lives.
    """
    with tempfile.TemporaryDirectory() as tmp:
        # Write audio to temp
        audio_path = os.path.join(tmp, "narration.wav")
        with open(audio_path, "wb") as f:
            f.write(audio_bytes)

        # Get audio duration
        try:
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", audio_path],
                capture_output=True, text=True, timeout=15
            )
            total_duration = float(probe.stdout.strip())
        except Exception as e:
            logger.warning(f"[ffmpeg] ffprobe failed ({e}), using 30s fallback")
            total_duration = 30.0

        num_images = len(image_paths)
        duration_per_image = max(total_duration / num_images, 2.0)

        # Write concat list — image_paths are absolute so -safe 0 is enough
        concat_list = os.path.join(tmp, "images.txt")
        with open(concat_list, "w") as f:
            for img_path in image_paths:
                f.write(f"file '{img_path}'\n")
                f.write(f"duration {duration_per_image:.2f}\n")
            # FFmpeg concat requires the last entry without duration
            f.write(f"file '{image_paths[-1]}'\n")

        logger.info(
            f"[ffmpeg] {num_images} image(s), duration={total_duration:.1f}s, "
            f"output={output_path}"
        )

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", concat_list,
            "-i", audio_path,
            "-vf", (
                "scale=1920:1080:force_original_aspect_ratio=decrease,"
                "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,"
                "setsar=1"
            ),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-shortest",
            "-r", "30",
            output_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if result.returncode != 0:
            # Log the last 2000 chars of stderr for diagnosis
            stderr_tail = result.stderr[-2000:]
            logger.error(f"[ffmpeg] FAILED (exit {result.returncode}):\n{stderr_tail}")
            raise RuntimeError(f"FFmpeg exit {result.returncode}:\n{stderr_tail}")

        size = os.path.getsize(output_path)
        logger.info(f"[ffmpeg] ✓ Output: {output_path} ({size:,} bytes)")
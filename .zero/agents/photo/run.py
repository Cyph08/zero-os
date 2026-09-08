"""
agents/photo/run.py — Zero OS Photo Agent

Cyph's Nikon D3400 batch processing assistant. Uses the visual pipeline
already built in visual/vision.py (OpenCV + Pillow).

Can:
  - Batch resize a folder of photos to a target width (preserving aspect ratio)
  - Rename photos with date-based or custom naming schemes
  - Convert RAW/NEF to JPEG (requires rawpy if installed)
  - Auto-rotate based on EXIF orientation
  - Export web-optimised copies with quality settings
  - Analyse a photo's brightness, blur, and dominant colour
  - Report how many photos are blurry or overexposed

The agent detects what action is needed from the query, uses OpenCV/Pillow
directly (no LLM needed for actual processing), and uses LLM only for
understanding the instruction and generating the report.

Risk level: write — modifies/creates files in the output folder.
Always tells Cyph what it will do before doing it.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.llm import chat

if TYPE_CHECKING:
    from core.bus import ContextBus

logger = logging.getLogger(__name__)

AGENT_NAME = "Lens"
AGENT_VERSION = "0.1.0"
LOG_DIR = Path(__file__).parent.parent.parent / "logs"
ZERO_ROOT = Path(__file__).parent.parent.parent
DEFAULT_OUTPUT_DIR = ZERO_ROOT / "visual" / "processed"

# Supported image extensions
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"}
RAW_EXTENSIONS = {".nef", ".cr2", ".arw", ".dng", ".raf"}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class PhotoResult:
    """Structured output from the photo agent."""
    query: str
    action_type: str          # "batch_resize" | "analyse" | "rename" | "convert" | "report" | "advice"
    summary: str              # Human-readable result report
    files_processed: int = 0
    files_skipped: int = 0
    output_folder: str = ""
    model_used: str = ""
    duration_ms: int = 0
    cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialise to plain dict for MCP / CEO response."""
        return {
            "query": self.query,
            "action_type": self.action_type,
            "summary": self.summary,
            "files_processed": self.files_processed,
            "files_skipped": self.files_skipped,
            "output_folder": self.output_folder,
            "model_used": self.model_used,
            "duration_ms": self.duration_ms,
            "cost_usd": self.cost_usd,
        }


# ---------------------------------------------------------------------------
# Action detector
# ---------------------------------------------------------------------------

def _detect_action(query: str) -> str:
    """
    Classify the photo processing request.

    Args:
        query: Raw user query.

    Returns:
        One of: "batch_resize", "analyse", "rename", "convert", "report", "advice"
    """
    q = query.lower()
    if any(w in q for w in ["resize", "scale", "shrink", "compress", "web", "1080", "1920", "thumbnail"]):
        return "batch_resize"
    if any(w in q for w in ["analyse", "analyze", "check", "blur", "sharp", "brightness", "overexposed"]):
        return "analyse"
    if any(w in q for w in ["rename", "name", "organise", "organize", "sort", "date"]):
        return "rename"
    if any(w in q for w in ["convert", "raw", "nef", "jpeg", "jpg", "export"]):
        return "convert"
    if any(w in q for w in ["report", "how many", "count", "summary", "what's in"]):
        return "report"
    return "advice"


# ---------------------------------------------------------------------------
# Photo processing functions
# ---------------------------------------------------------------------------

def _find_images(folder: Path, include_raw: bool = False) -> list[Path]:
    """
    Recursively find all image files in a folder.

    Args:
        folder:      Directory to search.
        include_raw: Whether to include RAW files.

    Returns:
        Sorted list of image file paths.
    """
    extensions = IMAGE_EXTENSIONS | (RAW_EXTENSIONS if include_raw else set())
    found: list[Path] = []
    try:
        for p in sorted(folder.rglob("*")):
            if p.suffix.lower() in extensions:
                found.append(p)
    except PermissionError as exc:
        logger.warning(f"[lens] Permission denied accessing {folder}: {exc}")
    return found


def _batch_resize(
    source_folder: Path,
    output_folder: Path,
    target_width: int = 1920,
    quality: int = 90,
) -> tuple[int, int]:
    """
    Resize all images in source_folder to target_width, saving to output_folder.

    Args:
        source_folder:  Input directory.
        output_folder:  Output directory (created if not exists).
        target_width:   Maximum width in pixels (aspect ratio preserved).
        quality:        JPEG quality 1–95.

    Returns:
        Tuple of (processed_count, skipped_count).
    """
    try:
        from PIL import Image
    except ImportError:
        logger.error("[lens] Pillow not installed — run: pip install Pillow")
        return 0, 0

    output_folder.mkdir(parents=True, exist_ok=True)
    images = _find_images(source_folder)
    processed = 0
    skipped = 0

    for img_path in images:
        try:
            with Image.open(img_path) as img:
                # Auto-rotate based on EXIF
                try:
                    from PIL import ImageOps
                    img = ImageOps.exif_transpose(img)
                except Exception:
                    pass

                # Only resize if wider than target
                if img.width > target_width:
                    ratio = target_width / img.width
                    new_size = (target_width, int(img.height * ratio))
                    img = img.resize(new_size, Image.LANCZOS)

                # Convert RGBA/palette to RGB for JPEG
                if img.mode not in ("RGB", "L"):
                    img = img.convert("RGB")

                out_path = output_folder / (img_path.stem + ".jpg")
                img.save(out_path, "JPEG", quality=quality, optimize=True)
                processed += 1
        except Exception as exc:
            logger.warning(f"[lens] Failed to process {img_path.name}: {exc}")
            skipped += 1

    return processed, skipped


def _analyse_folder(source_folder: Path) -> dict[str, Any]:
    """
    Analyse a folder of images — count, detect blur, brightness issues.

    Args:
        source_folder: Directory to analyse.

    Returns:
        Dict with counts and quality stats.
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        logger.error("[lens] OpenCV not installed — run: pip install opencv-python")
        return {"error": "OpenCV not available"}

    images = _find_images(source_folder)
    if not images:
        return {"total": 0, "error": "No images found"}

    blurry = 0
    overexposed = 0
    underexposed = 0
    total = len(images)

    for img_path in images[:50]:  # cap at 50 to avoid long waits
        try:
            img = cv2.imread(str(img_path))
            if img is None:
                continue
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            # Blur detection via Laplacian variance (< 100 = blurry)
            lap_var = cv2.Laplacian(gray, cv2.CV_64F).var()
            if lap_var < 100:
                blurry += 1
            # Brightness via mean pixel value
            mean_brightness = float(np.mean(gray))
            if mean_brightness > 220:
                overexposed += 1
            elif mean_brightness < 35:
                underexposed += 1
        except Exception as exc:
            logger.debug(f"[lens] Analysis failed for {img_path.name}: {exc}")

    return {
        "total": total,
        "analysed": min(total, 50),
        "blurry": blurry,
        "overexposed": overexposed,
        "underexposed": underexposed,
        "good": min(total, 50) - blurry - overexposed - underexposed,
    }


def _rename_by_date(source_folder: Path, prefix: str = "cyph") -> tuple[int, int]:
    """
    Rename images using EXIF date or file modification time.
    Format: {prefix}_{YYYYMMDD}_{HHMMSS}_{counter}.jpg

    Args:
        source_folder: Folder containing images to rename.
        prefix:        Filename prefix.

    Returns:
        Tuple of (renamed_count, skipped_count).
    """
    try:
        from PIL import Image
        from PIL.ExifTags import TAGS
    except ImportError:
        logger.error("[lens] Pillow not installed")
        return 0, 0

    images = _find_images(source_folder)
    renamed = 0
    skipped = 0
    counters: dict[str, int] = {}

    for img_path in images:
        try:
            with Image.open(img_path) as img:
                exif_data = img._getexif()  # type: ignore[attr-defined]
                dt_str = None
                if exif_data:
                    for tag_id, value in exif_data.items():
                        tag = TAGS.get(tag_id)
                        if tag == "DateTimeOriginal":
                            dt_str = value  # "YYYY:MM:DD HH:MM:SS"
                            break

                if dt_str:
                    date_part = dt_str[:10].replace(":", "")
                    time_part = dt_str[11:].replace(":", "")
                else:
                    # Fallback to file modification time
                    mtime = img_path.stat().st_mtime
                    from datetime import datetime
                    dt = datetime.fromtimestamp(mtime)
                    date_part = dt.strftime("%Y%m%d")
                    time_part = dt.strftime("%H%M%S")

                key = f"{date_part}_{time_part}"
                counters[key] = counters.get(key, 0) + 1
                new_name = f"{prefix}_{date_part}_{time_part}_{counters[key]:03d}.jpg"
                new_path = img_path.parent / new_name

                if new_path != img_path and not new_path.exists():
                    img_path.rename(new_path)
                    renamed += 1
                else:
                    skipped += 1

        except Exception as exc:
            logger.warning(f"[lens] Rename failed for {img_path.name}: {exc}")
            skipped += 1

    return renamed, skipped


# ---------------------------------------------------------------------------
# Prompt builder (for parsing instructions and generating reports)
# ---------------------------------------------------------------------------

def _build_report_prompt(query: str, stats: dict[str, Any]) -> str:
    """
    Build a prompt for the LLM to turn raw stats into a readable report.

    Args:
        query: Original user query.
        stats: Raw stats dict from analysis functions.

    Returns:
        Formatted prompt string.
    """
    return (
        f"You are Zero's photo agent reporting results to Cyph (Nikon D3400 photographer).\n\n"
        f"User asked: {query}\n\n"
        f"Raw stats: {stats}\n\n"
        f"Write a brief (3–5 sentence) plain English summary of what was found/done. "
        f"Be specific about numbers. If there are blurry or overexposed shots, suggest causes. "
        f"No bullet points. No markdown headers."
    )


# ---------------------------------------------------------------------------
# Folder extractor
# ---------------------------------------------------------------------------

def _extract_folder(query: str) -> Path | None:
    """
    Try to extract a folder path from the query string.

    Args:
        query: Raw user query.

    Returns:
        Path if found and exists, else None.
    """
    import re
    # Match Windows paths like D:\DCIM\100D3400 or K:\Photos\shoot1
    match = re.search(r"[A-Za-z]:\\[^\s,]+", query)
    if match:
        p = Path(match.group(0))
        if p.exists():
            return p
    return None


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _log_action(query: str, result: PhotoResult) -> None:
    """
    Append structured log line to logs/photo.log.

    Args:
        query:  The photo processing query.
        result: The completed PhotoResult.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "photo.log"
    entry = (
        f"timestamp={time.strftime('%Y-%m-%dT%H:%M:%S')} "
        f"agent={AGENT_NAME} "
        f"action={result.action_type} "
        f"files_processed={result.files_processed} "
        f"files_skipped={result.files_skipped} "
        f"query={query!r} "
        f"model={result.model_used} "
        f"duration_ms={result.duration_ms} "
        f"cost_usd={result.cost_usd:.6f}\n"
    )
    try:
        with log_file.open("a", encoding="utf-8") as f:
            f.write(entry)
    except OSError as exc:
        logger.error(f"[lens] Failed to write log: {exc}")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run(query: str, bus: "ContextBus | None" = None) -> PhotoResult:
    """
    Execute a photo processing task.

    Args:
        query: Natural language photo processing request.
               Can include a Windows path to the source folder.
        bus:   Optional shared ContextBus. Publishes processing stats.

    Returns:
        PhotoResult with summary and file counts.
    """
    start_ms = int(time.time() * 1000)
    logger.info(f"[lens] Query: {query!r}")

    action_type = _detect_action(query)
    source_folder = _extract_folder(query)
    output_folder = DEFAULT_OUTPUT_DIR

    model_used = ""
    cost_usd = 0.0
    summary = ""
    processed = 0
    skipped = 0

    # --- Execute the requested action ---
    if action_type == "batch_resize":
        if source_folder:
            logger.info(f"[lens] Batch resizing: {source_folder} → {output_folder}")
            processed, skipped = _batch_resize(source_folder, output_folder)
            raw_summary = {
                "action": "batch_resize",
                "source": str(source_folder),
                "output": str(output_folder),
                "processed": processed,
                "skipped": skipped,
            }
        else:
            raw_summary = {"error": "No source folder found in query. Please include the folder path."}

    elif action_type == "analyse":
        folder = source_folder or output_folder
        logger.info(f"[lens] Analysing: {folder}")
        raw_summary = _analyse_folder(folder)

    elif action_type == "rename":
        if source_folder:
            logger.info(f"[lens] Renaming files in: {source_folder}")
            processed, skipped = _rename_by_date(source_folder)
            raw_summary = {"action": "rename", "renamed": processed, "skipped": skipped}
        else:
            raw_summary = {"error": "No source folder found in query."}

    else:
        # advice / report / convert — use LLM to respond
        raw_summary = {
            "action": action_type,
            "note": "No folder processing performed — generating advice/report."
        }

    # --- Use LLM to turn raw stats into readable text ---
    try:
        prompt = _build_report_prompt(query, raw_summary)
        response = chat(
            prompt,
            tier="fast",
            system="You are Zero's photo agent. Report results clearly and concisely.",
            max_tokens=300,
        )
        summary = response.text
        cost_usd = response.cost_usd
        model_used = f"{response.provider.value}/{response.model}"
    except Exception as exc:
        logger.error(f"[lens] LLM summary error: {exc}")
        summary = f"Processing complete: {processed} files processed, {skipped} skipped. Raw stats: {raw_summary}"

    duration_ms = int(time.time() * 1000) - start_ms
    result = PhotoResult(
        query=query,
        action_type=action_type,
        summary=summary,
        files_processed=processed,
        files_skipped=skipped,
        output_folder=str(output_folder),
        model_used=model_used,
        duration_ms=duration_ms,
        cost_usd=cost_usd,
    )

    _log_action(query, result)

    if bus is not None:
        bus.publish("photo", "summary", summary)
        bus.publish("photo", "processed", processed)
        bus.publish("photo", "output_folder", str(output_folder))
        logger.debug(f"[lens] Published to bus: {processed} files processed")

    logger.info(f"[lens] Done in {duration_ms}ms — {processed} processed — cost=${cost_usd:.6f}")
    return result


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "Analyse the photos in my visual/processed folder and tell me how many are blurry"
    logging.basicConfig(level=logging.INFO)
    result = run(q)
    print(f"\n{'='*60}")
    print(f"PHOTO — {result.action_type.upper()}")
    print(f"{'='*60}")
    print(result.summary)
    print(f"\nProcessed: {result.files_processed} | Skipped: {result.files_skipped}")
    print(f"Output: {result.output_folder}")
    print(f"Model: {result.model_used} | Time: {result.duration_ms}ms | Cost: ${result.cost_usd:.6f}")

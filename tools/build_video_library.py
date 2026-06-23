import argparse
import json
import math
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path


VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv", ".avi"}
THUMB_SUFFIX = ".thumb.jpg"
DELETE_CATEGORY = "其他"
CANONICAL_CATEGORIES = {
    "动画分镜": "动画分镜",
    "分镜": "动画分镜",
    "storyboard": "动画分镜",
    "animatic": "动画分镜",
    "layout": "动画分镜",
    "动画片段": "动画片段",
    "动画": "动画片段",
    "clip": "动画片段",
    "animation": "动画片段",
    "其他": "其他",
    "other": "其他",
    "unclear": "其他",
}


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def to_posix(path):
    return path.as_posix()


def rel_posix(path, root):
    return to_posix(path.relative_to(root))


def load_json(path, default=None):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8", errors="replace") as f:
        return json.load(f)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp_path, path)


def video_id_for(video_path, downloads_root):
    return to_posix(video_path.relative_to(downloads_root).with_suffix(""))


def thumbnail_path_for(video_path):
    return video_path.with_name(f"{video_path.stem}{THUMB_SUFFIX}")


def normalize_tags(value):
    if not value:
        return []
    if isinstance(value, str):
        return [item for item in value.split() if item]
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return []


def normalize_category(value):
    text = str(value or "").strip()
    if not text:
        return "其他"
    return CANONICAL_CATEGORIES.get(text.lower(), text)


def as_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def as_int(value):
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def run_command(command):
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")


def middle_frame_time(record):
    duration = as_float(record.get("duration"))
    if not duration or duration <= 0:
        return None
    return max(0, duration / 2)


def generate_thumbnail(record, project_root, width, force):
    video_path = project_root / record["video_path"]
    thumb_path = project_root / record["thumb_path"]
    if thumb_path.exists() and not force:
        return {"path": str(thumb_path), "status": "exists"}

    thumb_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = thumb_path.with_name(f"{thumb_path.name}.{os.getpid()}.{time.time_ns()}.tmp.jpg")
    seek_seconds = middle_frame_time(record)
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
    ]
    if seek_seconds is not None:
        command.extend(["-ss", f"{seek_seconds:.3f}"])
    command.extend(
        [
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-vf",
        f"scale={width}:-2",
        "-q:v",
        "3",
        str(tmp_path),
        ]
    )
    result = run_command(command)
    if result.returncode != 0:
        if tmp_path.exists():
            tmp_path.unlink()
        return {
            "path": str(thumb_path),
            "status": "error",
            "error": (result.stderr or result.stdout or "").strip(),
        }

    os.replace(tmp_path, thumb_path)
    return {"path": str(thumb_path), "status": "created", "seek_seconds": seek_seconds}


def load_curated_tags(library_root):
    tag_path = library_root / "tagging" / "thumbnail-tags.json"
    data = load_json(tag_path, default={})
    if not isinstance(data, dict):
        return {}
    items = data.get("items") if "items" in data else data
    return items if isinstance(items, dict) else {}


def load_manual_edits(library_root):
    edits = load_json(library_root / "manual-edits.json", default={})
    if not isinstance(edits, dict):
        edits = {}
    excluded = edits.get("excluded")
    overrides = edits.get("category_overrides")
    return {
        "excluded": excluded if isinstance(excluded, dict) else {},
        "category_overrides": overrides if isinstance(overrides, dict) else {},
    }


def apply_manual_edits(records, manual_edits):
    excluded = set(manual_edits.get("excluded", {}).keys())
    overrides = manual_edits.get("category_overrides", {})
    visible_records = []
    other_category_count = 0

    for record in records:
        if record["id"] in excluded:
            continue

        override = overrides.get(record["id"])
        if isinstance(override, dict) and override.get("category"):
            curated = dict(record.get("curated") or {})
            curated.setdefault("tags", [])
            curated["category"] = normalize_category(override.get("category"))
            curated["manual_category"] = True
            curated["manual_updated_at"] = override.get("updated_at")
            record["curated"] = curated

        curated = record.get("curated") or {}
        category = curated.get("category")
        if category and normalize_category(category) == DELETE_CATEGORY:
            other_category_count += 1

        visible_records.append(record)

    return visible_records, len(excluded), other_category_count


def record_category(record):
    curated = record.get("curated") or {}
    if not isinstance(curated, dict):
        return ""
    return normalize_category(curated.get("category"))


def is_publishable_record(record):
    category = record_category(record)
    return bool(category and category != DELETE_CATEGORY)


def duplicate_media_key(record):
    tweet_id = str(record.get("tweet_id") or "").strip()
    media_id = str(record.get("media_id") or "").strip()
    if not tweet_id or not media_id:
        return None
    return (tweet_id, media_id)


def source_relation_rank(record):
    relation = str(record.get("source_relation") or "").strip().lower()
    if relation == "post":
        return 0
    if not relation:
        return 1
    if relation == "quote":
        return 2
    if relation == "repost":
        return 3
    return 4


def source_author_rank(record):
    source = str(record.get("source_screen_name") or "").strip().lower()
    author = str(record.get("author") or "").strip().lower()
    if source and author == source:
        return 0
    if not source:
        return 1
    return 2


def duplicate_candidate_key(record):
    category = record_category(record)
    if category and category != DELETE_CATEGORY:
        category_rank = 0
    elif not category:
        category_rank = 1
    else:
        category_rank = 2

    curated = record.get("curated") or {}
    manual_rank = 0 if isinstance(curated, dict) and curated.get("manual_category") else 1
    area = (as_int(record.get("width")) or 0) * (as_int(record.get("height")) or 0)
    bitrate = as_int(record.get("bitrate")) or as_int(record.get("video_bit_rate")) or 0
    return (
        category_rank,
        manual_rank,
        source_relation_rank(record),
        source_author_rank(record),
        as_int(record.get("media_index")) if as_int(record.get("media_index")) is not None else 9999,
        -area,
        -bitrate,
        record.get("id") or "",
    )


def duplicate_variant_key(record):
    tweet_id = str(record.get("tweet_id") or "").strip()
    width = as_int(record.get("width"))
    height = as_int(record.get("height"))
    duration = as_float(record.get("duration"))
    if not tweet_id or not width or not height or not duration:
        return None
    duration_bucket = int(round(duration * 4))
    return (tweet_id, width, height, duration_bucket)


def duplicate_candidate_snapshot(record):
    curated = record.get("curated") or {}
    return {
        "id": record.get("id"),
        "author": record.get("author"),
        "category": record_category(record),
        "manual_category": bool(isinstance(curated, dict) and curated.get("manual_category")),
        "source_relation": record.get("source_relation"),
        "source_screen_name": record.get("source_screen_name"),
        "timeline_screen_name": record.get("timeline_screen_name"),
        "timeline_tweet_id": record.get("timeline_tweet_id"),
        "tweet_url": record.get("tweet_url"),
        "video_path": record.get("video_path"),
        "media_id": record.get("media_id"),
        "media_index": record.get("media_index"),
        "width": record.get("width"),
        "height": record.get("height"),
        "duration": record.get("duration"),
    }


def dedupe_by_key(records, key_func):
    groups = {}
    for record in records:
        key = key_func(record)
        if not key:
            continue
        groups.setdefault(key, []).append(record)

    duplicate_groups = {}
    removed_ids = set()
    report_groups = []
    publishable_removed = 0

    for key, candidates in groups.items():
        if len(candidates) <= 1:
            continue
        duplicate_groups[key] = candidates
        canonical = sorted(candidates, key=duplicate_candidate_key)[0]
        canonical_id = canonical["id"]
        removed = [record for record in candidates if record["id"] != canonical_id]
        removed_ids.update(record["id"] for record in removed)
        publishable_removed += sum(1 for record in removed if is_publishable_record(record))
        report_groups.append(
            {
                "key": list(key) if isinstance(key, tuple) else key,
                "canonical_id": canonical_id,
                "duplicate_ids": [record["id"] for record in removed],
                "candidates": [duplicate_candidate_snapshot(record) for record in candidates],
            }
        )

    deduped = [record for record in records if record["id"] not in removed_ids]
    summary = {
        "groups": len(duplicate_groups),
        "records_removed": len(removed_ids),
        "publishable_records_removed": publishable_removed,
    }
    return deduped, report_groups, summary


def report_duplicate_candidates_by_key(records, key_func):
    groups = {}
    for record in records:
        key = key_func(record)
        if not key:
            continue
        groups.setdefault(key, []).append(record)

    report_groups = []
    for key, candidates in groups.items():
        if len(candidates) <= 1:
            continue
        canonical = sorted(candidates, key=duplicate_candidate_key)[0]
        canonical_id = canonical["id"]
        report_groups.append(
            {
                "key": list(key) if isinstance(key, tuple) else key,
                "canonical_id": canonical_id,
                "duplicate_ids": [record["id"] for record in candidates if record["id"] != canonical_id],
                "candidates": [duplicate_candidate_snapshot(record) for record in candidates],
            }
        )

    summary = {
        "groups": len(report_groups),
        "records_removed": 0,
        "publishable_records_removed": 0,
    }
    return report_groups, summary


def dedupe_records(records):
    records_after_exact, exact_groups, exact_summary = dedupe_by_key(records, duplicate_media_key)
    records_after_variant, variant_groups, variant_summary = dedupe_by_key(records_after_exact, duplicate_variant_key)
    report = {
        "generated_at": now_iso(),
        "method": "tweet_id_media_id_exact_then_same_tweet_variant_dedupe",
        "exact_duplicate_key": ["tweet_id", "media_id"],
        "variant_duplicate_key": ["tweet_id", "width", "height", "duration_quarter_second_bucket"],
        "groups": exact_groups,
        "variant_groups": variant_groups,
        "summary": {
            "duplicate_media_key_groups": exact_summary["groups"],
            "duplicate_records_removed": exact_summary["records_removed"],
            "duplicate_publishable_records_removed": exact_summary["publishable_records_removed"],
            "duplicate_variant_groups": variant_summary["groups"],
            "duplicate_variant_records_removed": variant_summary["records_removed"],
            "duplicate_variant_publishable_records_removed": variant_summary["publishable_records_removed"],
            "duplicate_records_removed_total": exact_summary["records_removed"] + variant_summary["records_removed"],
            "duplicate_publishable_records_removed_total": (
                exact_summary["publishable_records_removed"] + variant_summary["publishable_records_removed"]
            ),
            "records_before_dedupe": len(records),
            "records_after_exact_dedupe": len(records_after_exact),
            "records_after_dedupe": len(records_after_variant),
        },
    }
    return records_after_variant, report


def count_other_category(records):
    return sum(1 for record in records if record_category(record) == DELETE_CATEGORY)


def build_record(video_path, downloads_root, project_root, curated_tags):
    metadata_path = video_path.with_suffix(".json")
    metadata = load_json(metadata_path, default={}) or {}
    video_id = video_id_for(video_path, downloads_root)
    thumb_path = thumbnail_path_for(video_path)
    stat = video_path.stat()

    author = metadata.get("screen_name") or video_path.parent.name
    tweet_id = str(metadata.get("tweet_id") or "")
    media_id = str(metadata.get("media_id") or "")
    width = as_int(metadata.get("width"))
    height = as_int(metadata.get("height"))
    duration = as_float(metadata.get("duration"))
    created_at = metadata.get("created_at")

    return {
        "id": video_id,
        "author": author,
        "tweet_id": tweet_id,
        "media_id": media_id,
        "media_index": as_int(metadata.get("media_index")),
        "tweet_group_key": f"{author}/{tweet_id}" if tweet_id else f"{author}/{video_id}",
        "created_at": created_at,
        "downloaded_at": metadata.get("downloaded_at"),
        "tweet_url": metadata.get("tweet_url"),
        "tweet_text": metadata.get("tweet_text") or "",
        "source_tags": normalize_tags(metadata.get("tags")),
        "source_relation": metadata.get("source_relation"),
        "source_screen_name": metadata.get("source_screen_name"),
        "timeline_source": metadata.get("timeline_source"),
        "timeline_screen_name": metadata.get("timeline_screen_name"),
        "timeline_tweet_id": metadata.get("timeline_tweet_id"),
        "timeline_tweet_url": metadata.get("timeline_tweet_url"),
        "timeline_author_screen_name": metadata.get("timeline_author_screen_name"),
        "bitrate": as_int(metadata.get("bitrate")),
        "video_bit_rate": as_int(metadata.get("video_bit_rate")),
        "width": width,
        "height": height,
        "duration": duration,
        "aspect": round(width / height, 4) if width and height else None,
        "file_size_bytes": as_int(metadata.get("file_size_bytes")) or stat.st_size,
        "video_path": rel_posix(video_path, project_root),
        "thumb_path": rel_posix(thumb_path, project_root),
        "metadata_path": rel_posix(metadata_path, project_root) if metadata_path.exists() else None,
        "curated": curated_tags.get(video_id),
    }


def scan_videos(downloads_root):
    return sorted(
        path
        for path in downloads_root.rglob("*")
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
    )


def generate_thumbnails(records, project_root, width, workers, force):
    results = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(generate_thumbnail, record, project_root, width, force): record
            for record in records
        }
        for future in as_completed(futures):
            record = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {"path": str(project_root / record["thumb_path"]), "status": "error", "error": str(exc)}
            result["id"] = record["id"]
            result["video"] = str(project_root / record["video_path"])
            results.append(result)
    return results


def load_id_filter(path):
    if not path:
        return None
    id_path = Path(path)
    text = id_path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = [line.strip() for line in text.splitlines()]
    if isinstance(data, dict):
        data = data.get("ids", [])
    return {str(item).strip() for item in data if str(item).strip()}


def make_contact_sheets(records, project_root, library_root, sheet_size, columns):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise RuntimeError("Pillow is required for contact sheets. Install with: pip install Pillow") from exc

    sheet_dir = library_root / "contact_sheets"
    batch_dir = library_root / "tagging" / "batches"
    sheet_dir.mkdir(parents=True, exist_ok=True)
    batch_dir.mkdir(parents=True, exist_ok=True)

    font = ImageFont.load_default()
    title_font = ImageFont.load_default()
    batches = []
    cell_w = 280
    cell_h = 198
    image_box = (256, 144)
    padding = 12

    for batch_index, start in enumerate(range(0, len(records), sheet_size), start=1):
        batch_records = records[start : start + sheet_size]
        rows = math.ceil(len(batch_records) / columns)
        sheet = Image.new("RGB", (columns * cell_w, rows * cell_h), "#171a1f")
        draw = ImageDraw.Draw(sheet)
        batch_id = f"batch_{batch_index:03d}"
        manifest_items = []

        for item_index, record in enumerate(batch_records, start=1):
            col = (item_index - 1) % columns
            row = (item_index - 1) // columns
            x = col * cell_w
            y = row * cell_h
            key = f"B{batch_index:03d}-I{item_index:03d}"
            thumb_path = project_root / record["thumb_path"]

            draw.rectangle([x, y, x + cell_w - 1, y + cell_h - 1], fill="#20252c", outline="#3b434f")
            draw.text((x + padding, y + 8), key, fill="#f4f0e8", font=title_font)
            draw.text(
                (x + 96, y + 8),
                f"@{record['author']} {record.get('duration') or 0:.1f}s",
                fill="#aab3bf",
                font=font,
            )

            if thumb_path.exists():
                with Image.open(thumb_path) as img:
                    img = img.convert("RGB")
                    img.thumbnail(image_box, Image.Resampling.LANCZOS)
                    frame = Image.new("RGB", image_box, "#0c0e12")
                    offset = ((image_box[0] - img.width) // 2, (image_box[1] - img.height) // 2)
                    frame.paste(img, offset)
                    sheet.paste(frame, (x + padding, y + 32))
            else:
                draw.rectangle(
                    [x + padding, y + 32, x + padding + image_box[0], y + 32 + image_box[1]],
                    fill="#0c0e12",
                    outline="#4a5361",
                )
                draw.text((x + padding + 76, y + 92), "missing thumb", fill="#e06c75", font=font)

            created_at = record.get("created_at") or ""
            draw.text((x + padding, y + 180), created_at[:19], fill="#8d98a7", font=font)
            manifest_items.append(
                {
                    "key": key,
                    "id": record["id"],
                    "author": record["author"],
                    "created_at": record.get("created_at"),
                    "duration": record.get("duration"),
                    "source_tags": record.get("source_tags", []),
                    "tweet_text": record.get("tweet_text", ""),
                    "thumb_path": record["thumb_path"],
                    "video_path": record["video_path"],
                    "tweet_url": record.get("tweet_url"),
                }
            )

        sheet_path = sheet_dir / f"{batch_id}.jpg"
        manifest_path = batch_dir / f"{batch_id}.json"
        sheet.save(sheet_path, quality=88, optimize=True)
        write_json(
            manifest_path,
            {
                "schema_version": 1,
                "batch_id": batch_id,
                "contact_sheet": rel_posix(sheet_path, project_root),
                "items": manifest_items,
            },
        )
        batches.append(
            {
                "batch_id": batch_id,
                "contact_sheet": rel_posix(sheet_path, project_root),
                "manifest": rel_posix(manifest_path, project_root),
                "count": len(manifest_items),
            }
        )

    return batches


def write_agent_prompt(library_root, batches):
    prompt_path = library_root / "tagging" / "agent-classification-prompt.md"
    batch_list = "\n".join(
        f"- {batch['batch_id']}: {batch['contact_sheet']} ({batch['count']} items)"
        for batch in batches
    )
    prompt = f"""# Thumbnail Classification Prompt

Classify each middle-frame thumbnail from the assigned contact sheet batch.

Use these primary categories unless a genuinely repeated, useful category appears:
- 动画分镜: rough storyboard, animatic, layout, pencil/line planning, panels, timing boards.
- 动画片段: finished or near-finished animated footage, color animation, rendered anime/game/cinematic clips.
- 其他: delete bucket only. Use for UI screenshots, photos, memes, unclear frames, duplicates, blank/black frames, or anything that should not enter the resource library.

Rules:
- Keep tags sparse. Prefer 1 primary category plus 0-3 useful tags.
- Do not create one-off tags. If the material is not useful enough for the library, mark category=其他; after merge it is excluded from the index and reviewed by the coordinator for deletion.
- Classify only from the thumbnail/contact sheet unless a manifest field gives necessary context.
- Treat reaction/meme footage as 其他 even when it is colorful or animated-looking. Strong signals include overlaid joke captions, social-reply context, cropped TV/movie/live-action clips, image-macro layout, streamer/reaction faces, or a frame whose value is the joke rather than animation, staging, action, FX, camera, or composition reference.
- Do not use color-animation alone as proof of 动画片段. Keep a finished clip only when the visible frame has reusable animation/reference value; if it only reads as a reaction meme, use 其他 with high confidence.
- To avoid false positives, keep as 动画片段 with low confidence when the thumbnail clearly shows reusable action, posing, FX, shot design, or camera movement even if the tweet text is joking.
- If unsure between 动画分镜 and 动画片段, use confidence=low and choose the closer visual state.

Write JSONL to `library/tagging/agent_batches/<batch_id>.jsonl`.
Each line must be:
{{"key":"B001-I001","category":"动画分镜","tags":["rough-layout"],"confidence":"high","notes":""}}

Available batches:
{batch_list}
"""
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(prompt, encoding="utf-8")
    return prompt_path


def summarize(records, thumb_results, batches, excluded_count=0, other_category_count=0, duplicate_report=None):
    categories = {}
    authors = {}
    curated = 0
    for record in records:
        authors[record["author"]] = authors.get(record["author"], 0) + 1
        if record.get("curated"):
            curated += 1
            category = normalize_category(record["curated"].get("category"))
            if category:
                categories[category] = categories.get(category, 0) + 1

    thumb_status = {}
    for result in thumb_results:
        status = result.get("status", "unknown")
        thumb_status[status] = thumb_status.get(status, 0) + 1

    duplicate_summary = {}
    if isinstance(duplicate_report, dict) and isinstance(duplicate_report.get("summary"), dict):
        duplicate_summary = duplicate_report["summary"]

    return {
        "video_count": len(records),
        "author_counts": dict(sorted(authors.items())),
        "thumbnail_status": thumb_status,
        "curated_count": curated,
        "curated_category_counts": dict(sorted(categories.items())),
        "excluded_count": excluded_count,
        "other_category_delete_candidate_count": other_category_count,
        "duplicate_media_key_groups": duplicate_summary.get("duplicate_media_key_groups", 0),
        "duplicate_records_removed": duplicate_summary.get("duplicate_records_removed", 0),
        "duplicate_publishable_records_removed": duplicate_summary.get("duplicate_publishable_records_removed", 0),
        "duplicate_variant_groups": duplicate_summary.get("duplicate_variant_groups", 0),
        "duplicate_variant_records_removed": duplicate_summary.get("duplicate_variant_records_removed", 0),
        "duplicate_variant_publishable_records_removed": duplicate_summary.get("duplicate_variant_publishable_records_removed", 0),
        "duplicate_records_removed_total": duplicate_summary.get("duplicate_records_removed_total", 0),
        "duplicate_publishable_records_removed_total": duplicate_summary.get("duplicate_publishable_records_removed_total", 0),
        "batch_count": len(batches),
    }


def main():
    parser = argparse.ArgumentParser(description="Build local video library thumbnails, index, and tagging batches.")
    parser.add_argument("--downloads", default="Downloads", help="Downloaded media root.")
    parser.add_argument("--library", default="library", help="Generated library data root.")
    parser.add_argument("--thumb-width", type=int, default=640, help="Middle-frame thumbnail width.")
    parser.add_argument("--workers", type=int, default=max(2, min(8, (os.cpu_count() or 4))), help="ffmpeg workers.")
    parser.add_argument("--force-thumbnails", action="store_true", help="Regenerate existing thumbnails.")
    parser.add_argument("--skip-thumbnails", action="store_true", help="Do not generate thumbnails.")
    parser.add_argument("--skip-contact-sheets", action="store_true", help="Do not generate agent contact sheets.")
    parser.add_argument("--only-thumbnails", action="store_true", help="Only generate thumbnails; do not rewrite index or batches.")
    parser.add_argument("--thumbnail-ids-file", default=None, help="Optional JSON/text file of visible record ids to thumbnail.")
    parser.add_argument("--thumbnail-report", default=None, help="Thumbnail report path. Default: <library>/thumbnail-build-report.json.")
    parser.add_argument("--sheet-size", type=int, default=24, help="Items per contact sheet.")
    parser.add_argument("--columns", type=int, default=4, help="Columns per contact sheet.")
    args = parser.parse_args()

    project_root = Path.cwd()
    downloads_root = (project_root / args.downloads).resolve()
    library_root = (project_root / args.library).resolve()

    if not downloads_root.exists():
        print(f"Downloads root not found: {downloads_root}", file=sys.stderr)
        return 1

    video_paths = scan_videos(downloads_root)
    if not video_paths:
        print(f"No videos found under {downloads_root}", file=sys.stderr)
        return 1

    curated_tags = load_curated_tags(library_root)
    manual_edits = load_manual_edits(library_root)
    records = [build_record(path, downloads_root, project_root, curated_tags) for path in video_paths]
    records, excluded_count, _other_category_count = apply_manual_edits(records, manual_edits)
    records.sort(key=lambda item: (item["author"].lower(), item.get("created_at") or "", item["id"]))
    records, duplicate_report = dedupe_records(records)
    records.sort(key=lambda item: (item["author"].lower(), item.get("created_at") or "", item["id"]))
    other_category_count = count_other_category(records)

    id_filter = load_id_filter(args.thumbnail_ids_file)
    thumbnail_records = records
    if id_filter is not None:
        thumbnail_records = [record for record in records if record["id"] in id_filter]

    thumb_results = []
    if args.skip_thumbnails:
        thumb_results = [
            {"id": record["id"], "video": str(project_root / record["video_path"]), "path": str(project_root / record["thumb_path"]), "status": "skipped"}
            for record in thumbnail_records
        ]
    else:
        thumb_results = generate_thumbnails(thumbnail_records, project_root, args.thumb_width, args.workers, args.force_thumbnails)

    report_path = Path(args.thumbnail_report) if args.thumbnail_report else library_root / "thumbnail-build-report.json"
    write_json(report_path, {"generated_at": now_iso(), "results": thumb_results})
    write_json(library_root / "duplicate-media-report.json", duplicate_report)

    if args.only_thumbnails:
        thumb_status = {}
        for result in thumb_results:
            status = result.get("status", "unknown")
            thumb_status[status] = thumb_status.get(status, 0) + 1
        print(f"thumbnail_records={len(thumbnail_records)}")
        print(f"thumbnail_status={thumb_status}")
        print(f"wrote={report_path}")
        return 0

    batches = []
    if not args.skip_contact_sheets:
        batches = make_contact_sheets(records, project_root, library_root, args.sheet_size, args.columns)
        write_agent_prompt(library_root, batches)

    index = {
        "schema_version": 1,
        "generated_at": now_iso(),
        "downloads_root": rel_posix(downloads_root, project_root),
        "thumbnail_suffix": THUMB_SUFFIX,
        "records": records,
        "batches": batches,
        "summary": summarize(records, thumb_results, batches, excluded_count, other_category_count, duplicate_report),
    }
    write_json(library_root / "videos.index.json", index)

    summary = index["summary"]
    print(f"videos={summary['video_count']} batches={summary['batch_count']} curated={summary['curated_count']}")
    print(f"other_category_delete_candidates={summary['other_category_delete_candidate_count']}")
    print(f"duplicate_media_key_groups={summary['duplicate_media_key_groups']}")
    print(f"duplicate_records_removed={summary['duplicate_records_removed']}")
    print(f"duplicate_variant_groups={summary['duplicate_variant_groups']}")
    print(f"duplicate_variant_records_removed={summary['duplicate_variant_records_removed']}")
    print(f"thumbnail_status={summary['thumbnail_status']}")
    print(f"wrote={library_root / 'videos.index.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

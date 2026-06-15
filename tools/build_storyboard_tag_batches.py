import argparse
import json
import math
import os
import time
from datetime import datetime
from pathlib import Path


STORYBOARD_TAGS = [
    "extreme-wide-shot",
    "wide-shot",
    "full-shot",
    "medium-shot",
    "close-up",
    "extreme-close-up",
    "high-angle",
    "low-angle",
    "overhead-view",
    "dutch-angle",
    "over-shoulder",
    "pov-shot",
    "strong-silhouette",
    "center-composition",
    "symmetry",
    "rule-of-thirds",
    "foreground-framing",
    "frame-within-frame",
    "depth-layers",
    "negative-space",
    "two-shot",
    "group-staging",
    "crowd-staging",
    "dialogue-staging",
    "confrontation",
    "chase-staging",
    "fight-staging",
    "clear-line-of-action",
    "dynamic-pose",
    "gesture-acting",
    "facial-acting",
    "motion-blur",
    "speed-lines",
    "impact-moment",
    "fx-emphasis",
    "camera-move-cue",
    "establishing-shot",
    "reaction-shot",
    "insert-shot",
    "transition-shot",
    "unclear-frame",
]


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def rel_posix(path, root):
    return path.relative_to(root).as_posix()


def load_json(path):
    with path.open("r", encoding="utf-8", errors="replace") as f:
        return json.load(f)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp_path, path)


def load_records(index_path):
    data = load_json(index_path)
    records = data.get("records")
    if not isinstance(records, list):
        raise ValueError(f"{index_path} does not contain a records list")
    return records


def make_contact_sheets(records, project_root, output_root, batch_size, columns):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise RuntimeError("Pillow is required. Install with: pip install Pillow") from exc

    sheet_dir = output_root / "contact_sheets"
    batch_dir = output_root / "batches"
    sheet_dir.mkdir(parents=True, exist_ok=True)
    batch_dir.mkdir(parents=True, exist_ok=True)

    font = ImageFont.load_default()
    title_font = ImageFont.load_default()
    batches = []
    cell_w = 320
    cell_h = 226
    image_box = (296, 166)
    padding = 12

    for batch_index, start in enumerate(range(0, len(records), batch_size), start=1):
        batch_records = records[start : start + batch_size]
        rows = math.ceil(len(batch_records) / columns)
        batch_id = f"story_{batch_index:03d}"
        sheet = Image.new("RGB", (columns * cell_w, rows * cell_h), "#15191f")
        draw = ImageDraw.Draw(sheet)
        manifest_items = []

        for item_index, record in enumerate(batch_records, start=1):
            col = (item_index - 1) % columns
            row = (item_index - 1) // columns
            x = col * cell_w
            y = row * cell_h
            key = f"S{batch_index:03d}-I{item_index:03d}"
            thumb_path = project_root / record["thumb_path"]
            curated = record.get("curated") or {}

            draw.rectangle([x, y, x + cell_w - 1, y + cell_h - 1], fill="#20252c", outline="#3b434f")
            draw.text((x + padding, y + 8), key, fill="#f4f0e8", font=title_font)
            draw.text(
                (x + 104, y + 8),
                f"@{record.get('author', '')} {record.get('duration') or 0:.1f}s",
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
                    sheet.paste(frame, (x + padding, y + 34))
            else:
                draw.rectangle(
                    [x + padding, y + 34, x + padding + image_box[0], y + 34 + image_box[1]],
                    fill="#0c0e12",
                    outline="#4a5361",
                )
                draw.text((x + padding + 90, y + 104), "missing thumb", fill="#e06c75", font=font)

            label = f"{curated.get('category') or '未分类'} | {', '.join(curated.get('tags') or [])[:46]}"
            draw.text((x + padding, y + 204), label, fill="#8d98a7", font=font)
            manifest_items.append(
                {
                    "key": key,
                    "id": record["id"],
                    "author": record.get("author"),
                    "category": curated.get("category"),
                    "curated_tags": curated.get("tags") or [],
                    "source_tags": record.get("source_tags", []),
                    "created_at": record.get("created_at"),
                    "duration": record.get("duration"),
                    "tweet_text": record.get("tweet_text", ""),
                    "thumb_path": record["thumb_path"],
                    "video_path": record["video_path"],
                    "tweet_url": record.get("tweet_url"),
                }
            )

        sheet_path = sheet_dir / f"{batch_id}.jpg"
        manifest_path = batch_dir / f"{batch_id}.json"
        sheet.save(sheet_path, quality=90, optimize=True)
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


def write_prompt(output_root, batches, project_root):
    prompt_path = output_root / "storyboard-tagging-prompt.md"
    batch_lines = "\n".join(
        f"- {batch['batch_id']}: {batch['contact_sheet']} ({batch['count']} items)"
        for batch in batches
    )
    tag_lines = "\n".join(f"- `{tag}`" for tag in STORYBOARD_TAGS)
    prompt = f"""# Storyboard Semantic Tagging Prompt

Tag the visible middle-frame thumbnails for storyboard search. This is a semantic visual pass only.

Read the rules in `docs/storyboard-semantic-tagging-rules.md`.

Do not change category, existing curated tags, source_tags, thumbnails, videos, manifests, or the index. Write only JSONL result files under `library/storyboard_tagging/agent_batches/`.

Output one JSON object per line:
{{"key":"S001-I001","storyboard_tags":["wide-shot","depth-layers","establishing-shot"],"storyboard_confidence":"high","storyboard_notes":"space relationship is clear"}}

Rules:
- Use only tags from the allowed list below.
- Pick 2-6 tags per item. If unreadable, use only `unclear-frame`.
- Judge from the single frame. Do not guess plot, identity, or motion that is not visible.
- Keep notes short and factual.
- Do not output `category`, `tags`, or `source_tags`.

Allowed tags:
{tag_lines}

Available batches:
{batch_lines}
"""
    prompt_path.write_text(prompt, encoding="utf-8")
    return rel_posix(prompt_path, project_root)


def main():
    parser = argparse.ArgumentParser(description="Build contact sheets and manifests for storyboard semantic tagging.")
    parser.add_argument("--index", default="library/videos.index.json", help="Visible video index.")
    parser.add_argument("--output", default="library/storyboard_tagging", help="Storyboard tagging output root.")
    parser.add_argument("--batch-size", type=int, default=24, help="Items per contact sheet.")
    parser.add_argument("--columns", type=int, default=4, help="Columns per contact sheet.")
    parser.add_argument("--limit", type=int, default=None, help="Optional first N records for smoke tests.")
    args = parser.parse_args()

    project_root = Path.cwd()
    index_path = (project_root / args.index).resolve()
    output_root = (project_root / args.output).resolve()
    records = load_records(index_path)
    if args.limit is not None:
        records = records[: args.limit]
    if not records:
        raise SystemExit("No visible records found.")

    batches = make_contact_sheets(records, project_root, output_root, args.batch_size, args.columns)
    prompt_path = write_prompt(output_root, batches, project_root)
    summary = {
        "generated_at": now_iso(),
        "index": rel_posix(index_path, project_root),
        "output": rel_posix(output_root, project_root),
        "record_count": len(records),
        "batch_count": len(batches),
        "batch_size": args.batch_size,
        "columns": args.columns,
        "prompt": prompt_path,
        "allowed_tags": STORYBOARD_TAGS,
        "batches": batches,
    }
    write_json(output_root / "summary.json", summary)
    print(f"records={len(records)} batches={len(batches)}")
    print(f"prompt={prompt_path}")
    print(f"summary={rel_posix(output_root / 'summary.json', project_root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

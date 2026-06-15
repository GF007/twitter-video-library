import argparse
import glob
import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path


ALLOWED_TAGS = {
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
}

TAG_ALIASES = {
    "establishing": "establishing-shot",
    "reaction": "reaction-shot",
    "insert": "insert-shot",
    "transition": "transition-shot",
    "extreme-wide": "extreme-wide-shot",
    "wide": "wide-shot",
    "full": "full-shot",
    "medium": "medium-shot",
    "closeup": "close-up",
    "close-up-shot": "close-up",
    "extreme-closeup": "extreme-close-up",
    "ots": "over-shoulder",
    "over-the-shoulder": "over-shoulder",
    "pov": "pov-shot",
    "silhouette": "strong-silhouette",
    "centered": "center-composition",
    "thirds": "rule-of-thirds",
    "depth": "depth-layers",
    "negative-space-composition": "negative-space",
    "two-person": "two-shot",
    "group": "group-staging",
    "crowd": "crowd-staging",
    "dialogue": "dialogue-staging",
    "fight": "fight-staging",
    "chase": "chase-staging",
    "line-of-action": "clear-line-of-action",
    "dynamic": "dynamic-pose",
    "gesture": "gesture-acting",
    "facial": "facial-acting",
    "impact": "impact-moment",
    "fx": "fx-emphasis",
    "camera-move": "camera-move-cue",
    "unclear": "unclear-frame",
}


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def load_json(path, default=None):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8", errors="replace") as f:
        return json.load(f)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp_path, path)


def rel_path(path, root):
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def normalize_tag(value):
    tag = str(value or "").strip().lower().replace("_", "-").replace(" ", "-")
    while "--" in tag:
        tag = tag.replace("--", "-")
    tag = tag.strip("-")
    return TAG_ALIASES.get(tag, tag)


def normalize_tags(value):
    if isinstance(value, str):
        value = [item for item in value.replace(",", " ").split(" ") if item.strip()]
    if not isinstance(value, list):
        return [], ["storyboard_tags must be a list"]

    tags = []
    errors = []
    seen = set()
    for raw in value:
        tag = normalize_tag(raw)
        if not tag or tag in seen:
            continue
        if tag not in ALLOWED_TAGS:
            errors.append(f"unknown storyboard tag {raw!r}")
            continue
        seen.add(tag)
        tags.append(tag)

    if "unclear-frame" in tags and len(tags) > 1:
        tags = ["unclear-frame"]
    if len(tags) > 6:
        tags = tags[:6]
    if not tags:
        errors.append("storyboard_tags is empty")
    return tags, errors


def normalize_confidence(value):
    confidence = str(value or "medium").strip().lower()
    return confidence if confidence in {"high", "medium", "low"} else "medium"


def read_jsonl(path):
    rows = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append((line_number, json.loads(line)))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSONL: {exc}") from exc
    return rows


def load_key_map(batch_root):
    key_to_id = {}
    for manifest_path in sorted(batch_root.glob("story_*.json")):
        manifest = load_json(manifest_path, default={}) or {}
        for item in manifest.get("items", []):
            key_to_id[item["key"]] = item["id"]
    return key_to_id


def load_visible_ids(index_path):
    data = load_json(index_path, default={}) or {}
    records = data.get("records") or []
    return {record["id"] for record in records if record.get("id")}


def merge_storyboard_rows(library_root, input_glob, project_root):
    key_to_id = load_key_map(library_root / "storyboard_tagging" / "batches")
    paths = [Path(path) for path in sorted(glob.glob(str(input_glob)))]
    items = {}
    errors = []

    for path in paths:
        for line_number, row in read_jsonl(path):
            key = row.get("key")
            video_id = row.get("id") or key_to_id.get(key)
            if not video_id:
                errors.append(f"{rel_path(path, project_root)}:{line_number}: unknown key/id {key!r}")
                continue

            if "category" in row or "source_tags" in row:
                errors.append(f"{rel_path(path, project_root)}:{line_number}: category/source_tags must not be output")

            raw_tags = row.get("storyboard_tags", row.get("tags"))
            tags, tag_errors = normalize_tags(raw_tags)
            for tag_error in tag_errors:
                errors.append(f"{rel_path(path, project_root)}:{line_number}: {tag_error}")
            if tag_errors:
                continue

            items[video_id] = {
                "storyboard_tags": tags,
                "storyboard_confidence": normalize_confidence(row.get("storyboard_confidence", row.get("confidence"))),
                "storyboard_notes": str(row.get("storyboard_notes", row.get("notes", "")) or "").strip()[:160],
                "storyboard_source": path.name,
                "storyboard_key": key,
            }

    return paths, items, errors


def main():
    parser = argparse.ArgumentParser(description="Merge storyboard semantic tag JSONL into thumbnail-tags.json.")
    parser.add_argument("--library", default="library", help="Generated library data root.")
    parser.add_argument("--index", default="library/videos.index.json", help="Visible index for full-coverage checks.")
    parser.add_argument(
        "--input-glob",
        default=None,
        help="JSONL glob. Default: <library>/storyboard_tagging/agent_batches/*.jsonl",
    )
    parser.add_argument("--require-all-visible", action="store_true", help="Fail if any visible index record is missing storyboard tags.")
    args = parser.parse_args()

    project_root = Path.cwd()
    library_root = (project_root / args.library).resolve()
    index_path = (project_root / args.index).resolve()
    input_glob = args.input_glob or (library_root / "storyboard_tagging" / "agent_batches" / "*.jsonl")
    paths, storyboard_items, errors = merge_storyboard_rows(library_root, input_glob, project_root)

    tags_path = library_root / "tagging" / "thumbnail-tags.json"
    data = load_json(tags_path, default={}) or {}
    existing_items = data.get("items") if isinstance(data.get("items"), dict) else {}
    merged_items = {key: dict(value) for key, value in existing_items.items()}

    updated_at = now_iso()
    for video_id, storyboard in storyboard_items.items():
        current = dict(merged_items.get(video_id) or {})
        current.update(storyboard)
        current["storyboard_updated_at"] = updated_at
        merged_items[video_id] = current

    visible_ids = load_visible_ids(index_path)
    missing_visible = sorted(visible_ids - set(storyboard_items))
    if args.require_all_visible and missing_visible:
        preview = ", ".join(missing_visible[:10])
        errors.append(f"missing storyboard tags for {len(missing_visible)} visible records: {preview}")

    tag_counts = Counter(tag for item in storyboard_items.values() for tag in item.get("storyboard_tags", []))
    confidence_counts = Counter(item.get("storyboard_confidence") for item in storyboard_items.values())
    source_files = list(data.get("source_files") or [])
    for path in paths:
        source = rel_path(path, project_root)
        if source not in source_files:
            source_files.append(source)

    output = {
        **data,
        "schema_version": data.get("schema_version", 1),
        "updated_at": updated_at,
        "source_files": source_files,
        "items": dict(sorted(merged_items.items())),
    }
    summary = {
        "updated_at": updated_at,
        "source_files": [rel_path(path, project_root) for path in paths],
        "storyboard_classified_count": len(storyboard_items),
        "visible_count": len(visible_ids),
        "missing_visible_count": len(missing_visible),
        "tag_counts": dict(tag_counts.most_common()),
        "confidence_counts": dict(confidence_counts.most_common()),
        "error_count": len(errors),
        "errors": errors,
    }

    if errors:
        write_json(library_root / "storyboard_tagging" / "storyboard-tags.summary.json", summary)
        print(f"files={len(paths)} storyboard={len(storyboard_items)} errors={len(errors)}")
        for error in errors[:30]:
            print(f"ERROR {error}")
        return 1

    write_json(tags_path, output)
    write_json(library_root / "storyboard_tagging" / "storyboard-tags.summary.json", summary)
    print(f"files={len(paths)} storyboard={len(storyboard_items)} errors=0")
    print(f"top_tags={dict(tag_counts.most_common(12))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

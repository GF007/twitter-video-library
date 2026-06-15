import argparse
import glob
import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path


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


def load_json(path):
    with path.open("r", encoding="utf-8", errors="replace") as f:
        return json.load(f)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp_path, path)


def normalize_category(value):
    if not value:
        return "其他"
    key = str(value).strip().lower()
    return CANONICAL_CATEGORIES.get(key, str(value).strip())


def normalize_tags(value):
    if not value:
        return []
    if isinstance(value, str):
        value = [item.strip() for item in value.split(",")]
    tags = []
    seen = set()
    for item in value:
        tag = str(item).strip().lower().replace(" ", "-")
        if not tag or tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)
    return tags[:4]


def read_jsonl(path):
    rows = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSONL: {exc}") from exc
    return rows


def load_key_map(library_root):
    key_to_id = {}
    batch_dir = library_root / "tagging" / "batches"
    for manifest_path in sorted(batch_dir.glob("batch_*.json")):
        manifest = load_json(manifest_path)
        for item in manifest.get("items", []):
            key_to_id[item["key"]] = item["id"]
    return key_to_id


def merge_batches(library_root, input_glob):
    key_to_id = load_key_map(library_root)
    paths = [Path(path) for path in sorted(glob.glob(str(input_glob)))]
    items = {}
    errors = []

    for path in paths:
        for row in read_jsonl(path):
            key = row.get("key")
            video_id = row.get("id") or key_to_id.get(key)
            if not video_id:
                errors.append(f"{path}: unknown key/id {key!r}")
                continue
            category = normalize_category(row.get("category"))
            items[video_id] = {
                "category": category,
                "tags": normalize_tags(row.get("tags")),
                "confidence": str(row.get("confidence") or "medium").strip().lower(),
                "notes": str(row.get("notes") or "").strip(),
                "source": path.name,
                "key": key,
            }

    return paths, items, errors


def main():
    parser = argparse.ArgumentParser(description="Merge agent thumbnail classification JSONL batches.")
    parser.add_argument("--library", default="library", help="Generated library data root.")
    parser.add_argument(
        "--input-glob",
        default=None,
        help="JSONL glob. Default: <library>/tagging/agent_batches/*.jsonl",
    )
    args = parser.parse_args()

    project_root = Path.cwd()
    library_root = (project_root / args.library).resolve()
    input_glob = args.input_glob or (library_root / "tagging" / "agent_batches" / "*.jsonl")
    paths, items, errors = merge_batches(library_root, input_glob)

    category_counts = Counter(item["category"] for item in items.values())
    tag_counts = Counter(tag for item in items.values() for tag in item.get("tags", []))
    data = {
        "schema_version": 1,
        "updated_at": now_iso(),
        "source_files": [str(path.relative_to(project_root)) for path in paths],
        "items": dict(sorted(items.items())),
    }
    summary = {
        "updated_at": data["updated_at"],
        "classified_count": len(items),
        "category_counts": dict(category_counts.most_common()),
        "other_category_delete_candidate_count": category_counts.get("其他", 0),
        "tag_counts": dict(tag_counts.most_common()),
        "error_count": len(errors),
        "errors": errors,
    }

    write_json(library_root / "tagging" / "thumbnail-tags.json", data)
    write_json(library_root / "tagging" / "thumbnail-tags.summary.json", summary)

    print(f"files={len(paths)} classified={len(items)} errors={len(errors)}")
    print(f"category_counts={dict(category_counts.most_common())}")
    print(f"other_category_delete_candidates={category_counts.get('其他', 0)}")
    if errors:
        for error in errors[:20]:
            print(f"ERROR {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

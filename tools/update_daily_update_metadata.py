import argparse
import json
import os
import time
from datetime import date, datetime
from pathlib import Path


DEFAULT_INDEX_FIELD = "daily_update"
DEFAULT_FEED_FIELD = "update_feed"


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def parse_iso_date(value):
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD date, got {value!r}") from exc


def non_negative_int(value):
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected integer, got {value!r}") from exc
    if number < 0:
        raise argparse.ArgumentTypeError("value must be zero or greater")
    return number


def positive_int(value):
    number = non_negative_int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return number


def read_json(path):
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp_path, path)


def default_display_text(update_date, new_count, label=None):
    if label:
        return f"{label}：{update_date.isoformat()} 新增 {new_count} 条"
    noun = "item" if new_count == 1 else "items"
    return f"{new_count} new {noun} on {update_date.isoformat()}"


def build_metadata(args):
    update_date = args.date
    counts = {"new": args.new_count}
    if args.downloaded_count is not None:
        counts["downloaded"] = args.downloaded_count
    if args.visible_new_count is not None:
        counts["visible_new"] = args.visible_new_count
    if args.records_before is not None:
        counts["records_before"] = args.records_before
    if args.records_after is not None:
        counts["records_after"] = args.records_after

    metadata = {
        "schema_version": 1,
        "date": update_date.isoformat(),
        "new_count": args.new_count,
        "counts": counts,
        "count_method": args.count_method,
        "source": args.source,
        "updated_at": args.updated_at or now_iso(),
        "display_text": args.display_text or default_display_text(update_date, args.new_count, args.label),
    }
    if args.kind:
        metadata["kind"] = args.kind
    if args.label:
        metadata["label"] = args.label
    if args.note:
        metadata["note"] = args.note
    return metadata


def build_feed_item(args, metadata):
    item = dict(metadata)
    item["kind"] = args.kind
    if args.label:
        item["label"] = args.label
    return item


def feed_item_key(item):
    if not isinstance(item, dict):
        return ("text", str(item))
    return (
        item.get("kind") or "",
        item.get("label") or "",
        item.get("date") or "",
        item.get("source") or "",
    )


def update_feed_items(index, feed_field, feed_item, max_items, seed_item=None):
    existing = index.get(feed_field)
    if not isinstance(existing, list):
        existing = index.get("daily_updates")
    if not isinstance(existing, list):
        existing = []
    if not existing and seed_item:
        existing = [seed_item]

    key = feed_item_key(feed_item)
    deduped = [item for item in existing if feed_item_key(item) != key]
    return [*deduped, feed_item][-max_items:]


def prepare_index_update(index_path, field_name, metadata, feed_field=None, feed_item=None, max_items=20, mirror_daily_update=True):
    if not index_path.exists():
        return None, "skipped_missing"

    index = read_json(index_path)
    if not isinstance(index, dict):
        raise ValueError(f"{index_path} must contain a JSON object")

    seed_item = index.get(field_name) if isinstance(index.get(field_name), dict) else None
    if mirror_daily_update or field_name not in index:
        index[field_name] = metadata
        seed_item = metadata
    if feed_field and feed_item:
        index[feed_field] = update_feed_items(index, feed_field, feed_item, max_items, seed_item)
    return index, "updated"


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Write the daily update metadata used by the video library and, "
            "when present, mirror it into library/videos.index.json."
        )
    )
    parser.add_argument("--date", required=True, type=parse_iso_date, help="Update date as YYYY-MM-DD.")
    parser.add_argument("--new-count", required=True, type=non_negative_int, help="New item count to show in the app.")
    parser.add_argument("--library", default="library", help="Library data root. Default: library.")
    parser.add_argument("--output", default=None, help="Metadata output path. Default: <library>/daily-update.json.")
    parser.add_argument("--index", default=None, help="Index path to mirror into. Default: <library>/videos.index.json.")
    parser.add_argument("--index-field", default=DEFAULT_INDEX_FIELD, help=f"Index field name. Default: {DEFAULT_INDEX_FIELD}.")
    parser.add_argument("--feed-field", default=DEFAULT_FEED_FIELD, help=f"Feed field name when --append-feed is set. Default: {DEFAULT_FEED_FIELD}.")
    parser.add_argument("--no-index", action="store_true", help="Only write the standalone daily-update JSON.")
    parser.add_argument("--require-index", action="store_true", help="Fail when the index file is missing.")
    parser.add_argument("--append-feed", action="store_true", help="Also append this item to the index update feed.")
    parser.add_argument("--max-items", type=positive_int, default=20, help="Maximum feed items to keep. Default: 20.")
    parser.add_argument("--label", default=None, help="Optional feed label, e.g. 每日更新 or 新增博主 jo_joMT.")
    parser.add_argument("--kind", default="daily", help="Short feed item kind. Default: daily.")
    parser.add_argument("--downloaded-count", type=non_negative_int, default=None, help="Optional raw downloaded count.")
    parser.add_argument("--visible-new-count", type=non_negative_int, default=None, help="Optional visible new record count.")
    parser.add_argument("--records-before", type=non_negative_int, default=None, help="Optional pre-update record count.")
    parser.add_argument("--records-after", type=non_negative_int, default=None, help="Optional post-update record count.")
    parser.add_argument(
        "--count-method",
        default="manual",
        help="Short label for how --new-count was computed. Default: manual.",
    )
    parser.add_argument("--source", default="daily-update", help="Short source label. Default: daily-update.")
    parser.add_argument("--display-text", default=None, help="Optional ready-to-render display text.")
    parser.add_argument("--updated-at", default=None, help="Optional ISO timestamp. Default: current local time.")
    parser.add_argument("--note", default=None, help="Optional non-sensitive note.")
    parser.add_argument("--dry-run", action="store_true", help="Print metadata and planned writes without changing files.")
    return parser.parse_args()


def main():
    args = parse_args()
    library_root = Path(args.library)
    output_path = Path(args.output) if args.output else library_root / "daily-update.json"
    index_path = Path(args.index) if args.index else library_root / "videos.index.json"
    metadata = build_metadata(args)
    feed_item = build_feed_item(args, metadata) if args.append_feed else None

    index_data = None
    index_status = "disabled"
    if not args.no_index:
        mirror_daily_update = not args.append_feed or args.kind == "daily"
        index_data, index_status = prepare_index_update(
            index_path,
            args.index_field,
            metadata,
            args.feed_field if args.append_feed else None,
            feed_item,
            args.max_items,
            mirror_daily_update,
        )
        if index_status == "skipped_missing" and args.require_index:
            raise FileNotFoundError(f"index file not found: {index_path}")

    if args.dry_run:
        preview = {"daily_update": metadata, "feed_item": feed_item} if feed_item else metadata
        print(json.dumps(preview, ensure_ascii=False, indent=2))
    else:
        write_json(output_path, metadata)
        if index_data is not None:
            write_json(index_path, index_data)

    print(f"date={metadata['date']}")
    print(f"new_count={metadata['new_count']}")
    print(f"output={output_path}")
    print(f"index={index_path}")
    print(f"index_status={index_status}")
    if feed_item:
        print(f"feed_field={args.feed_field}")
        print(f"max_items={args.max_items}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

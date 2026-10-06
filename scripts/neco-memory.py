#!/usr/bin/env python3
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "neco"))
from memory.store import MemoryStore


def store_from_args(args):
    path = Path(args.db or os.getenv("NECO_MEMORY_DB", ROOT / ".runtime" / "neco-memory.sqlite3"))
    return MemoryStore(path)


def main():
    parser = argparse.ArgumentParser(description="Inspect and maintain Neco's persistent memory.")
    parser.add_argument("--db", help="override memory database path")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="show recent memories")
    p_list.add_argument("--limit", type=int, default=30)
    p_list.add_argument("--all", action="store_true", help="include archived memories")

    p_show = sub.add_parser("show", help="show one memory")
    p_show.add_argument("id", type=int)

    p_forget = sub.add_parser("forget", help="permanently delete one memory")
    p_forget.add_argument("id", type=int)

    p_archive = sub.add_parser("archive", help="archive one memory without deleting it")
    p_archive.add_argument("id", type=int)

    sub.add_parser("state", help="show evolving state")

    p_search = sub.add_parser("search", help="preview retrieval for a query")
    p_search.add_argument("query")
    p_search.add_argument("--limit", type=int, default=6)

    p_export = sub.add_parser("export", help="export memories and state as JSON")
    p_export.add_argument("path", nargs="?", default="-")

    args = parser.parse_args()
    store = store_from_args(args)

    if args.command == "list":
        rows = store.list_memories(args.limit, status="all" if args.all else "active")
        if not rows:
            print("no memories yet")
            return
        for row in rows:
            mark = "" if row["status"] == "active" else f" ({row['status']})"
            print(f"#{row['id']} [{row['kind']}] imp={row['importance']:.2f} conf={row['confidence']:.2f}{mark}")
            print("  " + row["content"])
    elif args.command == "show":
        row = store.get_memory(args.id)
        if row is None:
            raise SystemExit(f"memory #{args.id} not found")
        print(json.dumps(row, indent=2, ensure_ascii=False))
    elif args.command == "forget":
        if not store.delete_memory(args.id):
            raise SystemExit(f"memory #{args.id} not found")
        print(f"deleted memory #{args.id}")
    elif args.command == "archive":
        if not store.archive_memory(args.id):
            raise SystemExit(f"memory #{args.id} not found")
        print(f"archived memory #{args.id}")
    elif args.command == "state":
        print(json.dumps(store.get_state(), indent=2, ensure_ascii=False))
    elif args.command == "search":
        print(json.dumps(store.retrieve(args.query, args.limit), indent=2, ensure_ascii=False))
    elif args.command == "export":
        rendered = json.dumps(store.export(), indent=2, ensure_ascii=False)
        if args.path == "-":
            print(rendered)
        else:
            Path(args.path).write_text(rendered + "\n")
            print(f"wrote {args.path}")


if __name__ == "__main__":
    main()

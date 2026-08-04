import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


DEFAULT_STATE_FILE = ".notebooklm-obsidian-sync.json"


def run_command(args, check=True):
    result = subprocess.run(
        args,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(args)}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return result


def notebooklm_json(*args):
    result = run_command(["notebooklm", *args])
    return json.loads(result.stdout)


def get_prop(obj, *names):
    for name in names:
        if isinstance(obj, dict) and name in obj:
            return obj[name]
    return None


def load_state(path):
    if not path.exists():
        return {"version": 1, "notes": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_frontmatter(text):
    text = text.lstrip("\ufeff")
    match = re.match(r"(?s)^---\r?\n(.*?)\r?\n---\r?\n(.*)$", text)
    if match:
        return parse_yamlish(match.group(1)), match.group(2)
    return {}, text


def parse_yamlish(block):
    data = {}
    current_key = None
    for raw_line in block.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        item = re.match(r"^\s*-\s+(.*)$", line)
        if item and current_key:
            data.setdefault(current_key, []).append(clean_scalar(item.group(1)))
            continue
        match = re.match(r"^([^:#][^:]*):\s*(.*)$", line)
        if not match:
            continue
        key = match.group(1).strip()
        value = match.group(2).strip()
        current_key = key
        if value == "":
            data[key] = []
        elif value.startswith("[") and value.endswith("]"):
            data[key] = [clean_scalar(part) for part in value[1:-1].split(",") if part.strip()]
        else:
            data[key] = clean_scalar(value)
    return data


def clean_scalar(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def normalize_tags(frontmatter, body):
    tags = set()
    raw_tags = frontmatter.get("tags", [])
    if isinstance(raw_tags, str):
        raw_tags = [raw_tags]
    for tag in raw_tags:
        tag = str(tag).strip().lstrip("#")
        if tag:
            tags.add(tag)
    for tag in re.findall(r"(?<!\w)#([\w\u4e00-\u9fff][\w\-/\u4e00-\u9fff]*)", body):
        tags.add(tag.strip("/"))
    return tags


def file_fingerprint(path):
    stat = path.stat()
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return {
        "sha256": digest.hexdigest(),
        "mtime": int(stat.st_mtime),
        "size": stat.st_size,
    }


def note_key(vault_path, note_path):
    return note_path.relative_to(vault_path).as_posix()


def should_skip_path(vault_path, note_path, include_dirs, exclude_dirs):
    rel = note_path.relative_to(vault_path).as_posix()
    if include_dirs and not any(rel == d or rel.startswith(f"{d}/") for d in include_dirs):
        return True
    return any(rel == d or rel.startswith(f"{d}/") for d in exclude_dirs)


def load_notes(vault_path, include_dirs, exclude_dirs, include_tags, exclude_tags):
    notes = []
    for path in sorted(vault_path.rglob("*.md")):
        if ".obsidian" in path.parts:
            continue
        if should_skip_path(vault_path, path, include_dirs, exclude_dirs):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        frontmatter, body = parse_frontmatter(text)
        tags = normalize_tags(frontmatter, body)
        if include_tags and tags.isdisjoint(include_tags):
            continue
        if exclude_tags and not tags.isdisjoint(exclude_tags):
            continue
        title = str(frontmatter.get("title") or path.stem).strip()
        notes.append(
            {
                "path": path,
                "key": note_key(vault_path, path),
                "title": title,
                "tags": sorted(tags),
                "fingerprint": file_fingerprint(path),
            }
        )
    return notes


def resolve_notebook(notebook_title):
    notebooks = notebooklm_json("list", "--json", "--no-truncate")
    if isinstance(notebooks, dict):
        notebooks = notebooks.get("notebooks") or notebooks.get("items", [])
    for notebook in notebooks:
        if get_prop(notebook, "title", "name") == notebook_title:
            notebook_id = get_prop(notebook, "id", "notebook_id", "notebookId")
            if notebook_id:
                return notebook_id
    raise RuntimeError(f"Notebook '{notebook_title}' not found.")


def source_title(note):
    return f"Obsidian - {note['title']}"


def add_source(notebook_id, note):
    payload = notebooklm_json(
        "source",
        "add",
        "--json",
        "--notebook",
        notebook_id,
        str(note["path"]),
        "--title",
        source_title(note),
    )
    source_id = get_prop(payload, "id", "source_id", "sourceId")
    if source_id:
        run_command(
            [
                "notebooklm",
                "source",
                "wait",
                source_id,
                "--notebook",
                notebook_id,
                "--timeout",
                "120",
                "--interval",
                "2",
            ],
            check=False,
        )
    return source_id


def sync_notes(args):
    vault_path = Path(args.vault).expanduser().resolve()
    if not vault_path.exists():
        raise RuntimeError(f"Obsidian vault not found: {vault_path}")

    include_dirs = {d.replace("\\", "/").strip("/") for d in args.include_dir if d.strip()}
    exclude_dirs = {d.replace("\\", "/").strip("/") for d in args.exclude_dir if d.strip()}
    include_tags = {tag.strip().lstrip("#") for tag in args.include_tag if tag.strip()}
    exclude_tags = {tag.strip().lstrip("#") for tag in args.exclude_tag if tag.strip()}

    state_path = Path(args.state_file).expanduser().resolve()
    state = load_state(state_path)
    notes = load_notes(vault_path, include_dirs, exclude_dirs, include_tags, exclude_tags)

    notebook_id = None if args.dry_run else resolve_notebook(args.notebook_title)
    entries = []
    uploaded = 0
    skipped = 0
    failed = 0

    for note in notes[: args.limit or None]:
        previous = state["notes"].get(note["key"], {})
        changed = previous.get("sha256") != note["fingerprint"]["sha256"]
        if not changed and not args.force:
            skipped += 1
            entries.append({"status": "skipped", "reason": "unchanged", "path": note["key"], "title": note["title"]})
            continue

        if args.dry_run:
            entries.append(
                {
                    "status": "would_upload",
                    "reason": "changed" if previous else "new",
                    "path": note["key"],
                    "title": note["title"],
                    "tags": note["tags"],
                }
            )
            continue

        try:
            source_id = add_source(notebook_id, note)
            state["notes"][note["key"]] = {
                **note["fingerprint"],
                "title": note["title"],
                "source_title": source_title(note),
                "source_id": source_id,
                "notebook_title": args.notebook_title,
                "notebook_id": notebook_id,
                "synced_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            }
            uploaded += 1
            entries.append({"status": "uploaded", "path": note["key"], "title": note["title"], "source_id": source_id})
        except Exception as exc:
            failed += 1
            entries.append({"status": "failed", "path": note["key"], "title": note["title"], "error": str(exc)})

    if not args.dry_run:
        save_state(state_path, state)

    return {
        "status": "completed",
        "mode": "dry-run" if args.dry_run else "execute",
        "vault": str(vault_path),
        "notebook": {"title": args.notebook_title, "id": notebook_id},
        "state_file": str(state_path),
        "counts": {
            "matched": len(notes),
            "uploaded": uploaded,
            "skipped": skipped,
            "failed": failed,
            "would_upload": sum(1 for entry in entries if entry["status"] == "would_upload"),
        },
        "entries": entries,
    }


def main():
    parser = argparse.ArgumentParser(description="Sync selected Obsidian Markdown notes into NotebookLM.")
    parser.add_argument("--vault", required=True, help="Path to an Obsidian vault folder.")
    parser.add_argument("--notebook-title", required=True, help="NotebookLM notebook title to receive notes.")
    parser.add_argument("--state-file", default=str(Path(os.getcwd()) / DEFAULT_STATE_FILE))
    parser.add_argument("--include-dir", action="append", default=[], help="Only sync notes under this vault-relative folder.")
    parser.add_argument("--exclude-dir", action="append", default=[".trash"], help="Skip notes under this vault-relative folder.")
    parser.add_argument("--include-tag", action="append", default=[], help="Only sync notes with this Obsidian tag.")
    parser.add_argument("--exclude-tag", action="append", default=[], help="Skip notes with this Obsidian tag.")
    parser.add_argument("--limit", type=int, default=0, help="Maximum notes to process. 0 means no limit.")
    parser.add_argument("--force", action="store_true", help="Upload even if the note fingerprint is unchanged.")
    parser.add_argument("--dry-run", action="store_true", help="Preview matched notes without uploading.")
    args = parser.parse_args()

    result = sync_notes(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

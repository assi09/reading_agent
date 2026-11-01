"""Reading-list persistence.

`reading_list.json` is the source of truth; `reading_list.md` and `reading_list.bib`
are regenerated on every write so they can be opened directly.
"""

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from server.models import Paper, SavedEntry

_lock = threading.Lock()


def data_dir() -> Path:
    """Directory holding the reading list (override with READING_LIST_DIR)."""
    default = Path(__file__).resolve().parent.parent / "data"
    path = Path(os.environ.get("READING_LIST_DIR", default))
    path.mkdir(parents=True, exist_ok=True)
    return path


def load() -> list[SavedEntry]:
    path = data_dir() / "reading_list.json"
    if not path.exists():
        return []
    return [SavedEntry.model_validate(item) for item in json.loads(path.read_text())]


def add(paper: Paper, note: str | None) -> tuple[bool, int]:
    """Add a paper. Returns (was_added, list_size). Idempotent on arxiv_id."""
    with _lock:
        entries = load()
        if any(e.paper.arxiv_id == paper.arxiv_id for e in entries):
            return False, len(entries)
        entries.append(
            SavedEntry(
                paper=paper,
                note=note,
                saved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )
        )
        _write(entries)
        return True, len(entries)


def remove(arxiv_id: str) -> bool:
    """Remove one paper. Returns False if it was not in the list."""
    with _lock:
        entries = load()
        kept = [e for e in entries if e.paper.arxiv_id != arxiv_id]
        if len(kept) == len(entries):
            return False
        _write(kept)
        return True


def clear() -> int:
    """Remove every paper. Returns how many were removed."""
    with _lock:
        count = len(load())
        _write([])
        return count


def _write(entries: list[SavedEntry]) -> None:
    directory = data_dir()
    tmp = directory / "reading_list.json.tmp"
    tmp.write_text(json.dumps([e.model_dump() for e in entries], indent=2))
    tmp.replace(directory / "reading_list.json")
    (directory / "reading_list.md").write_text(_to_markdown(entries))
    (directory / "reading_list.bib").write_text(_to_bibtex(entries))


def _to_markdown(entries: list[SavedEntry]) -> str:
    lines = ["# Reading List", ""]
    for i, e in enumerate(entries, 1):
        p = e.paper
        authors = ", ".join(p.authors[:3]) + (" et al." if len(p.authors) > 3 else "")
        lines.append(f"{i}. **[{p.title}]({p.url})** ({p.published[:4]}). {authors}")
        if e.note:
            lines.append(f"   - _Note:_ {e.note}")
    return "\n".join(lines) + "\n"


def _to_bibtex(entries: list[SavedEntry]) -> str:
    blocks = []
    for e in entries:
        p = e.paper
        key = (p.authors[0].split()[-1] if p.authors else "anon") + p.published[:4]
        key += p.arxiv_id.replace(".", "").replace("/", "")[-5:]
        blocks.append(
            f"@misc{{{key},\n"
            f"  title = {{{p.title}}},\n"
            f"  author = {{{' and '.join(p.authors)}}},\n"
            f"  year = {{{p.published[:4]}}},\n"
            f"  eprint = {{{p.arxiv_id}}},\n"
            f"  archivePrefix = {{arXiv}},\n"
            f"  url = {{{p.url}}}\n"
            f"}}"
        )
    return "\n\n".join(blocks) + "\n"

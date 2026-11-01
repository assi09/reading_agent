"""Research Paper Scout: a FastMCP server exposing three single-purpose tools.

    Data tool          search_arxiv          read-only lookup on arXiv
    Action tool        save_to_reading_list  writes one paper to the reading list
    Orchestration tool build_reading_list    search_arxiv -> save_to_reading_list (x n)

Plus one resource, `reading-list://current`, a pure read of the saved list.

Run directly (stdio transport):  python -m server.arxiv_server
"""

import json
import sys
from typing import Annotated, Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from server import arxiv_client, storage
from server.models import Paper, ReadingListReport, SaveResult, SearchResult

mcp = FastMCP(
    name="research-paper-scout",
    instructions=(
        "Tools for finding arXiv papers and curating a personal reading list. "
        "Use search_arxiv to look things up, save_to_reading_list to save one paper the "
        "user picked, and build_reading_list when the user wants several papers on a "
        "topic saved in one go."
    ),
)

# Papers seen in search results, keyed by arxiv_id. Lets save_to_reading_list skip
# a second arXiv request for a paper the agent just found (arXiv asks clients to
# keep request rates low).
_seen_papers: dict[str, Paper] = {}


def log(message: str) -> None:
    """Log to stderr; stdout is reserved for the MCP stdio protocol."""
    print(f"[mcp-server] {message}", file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- Data


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
def search_arxiv(
    query: Annotated[
        str, Field(description="Keywords to search for, e.g. 'model context protocol'.")
    ],
    max_results: Annotated[
        int, Field(ge=1, le=20, description="How many papers to return (1-20).")
    ] = 5,
    sort_by: Annotated[
        Literal["relevance", "date"],
        Field(description="'relevance' (best match first) or 'date' (newest first)."),
    ] = "relevance",
) -> SearchResult:
    """Search arXiv for papers matching a keyword query. Read-only: never modifies
    the reading list. Returns each paper's arXiv ID, title, authors, date, abstract,
    and URL."""
    log(f"search_arxiv(query={query!r}, max_results={max_results}, sort_by={sort_by!r})")
    cleaned = query.strip()
    if len(cleaned) < 2:
        raise ToolError("The search query is empty. Provide at least one keyword.")
    if len(cleaned) > 300:
        raise ToolError("The search query is too long (max 300 characters).")

    try:
        total, papers = arxiv_client.search(cleaned, max_results, sort_by)
    except arxiv_client.ArxivError as exc:
        log(f"search_arxiv failed: {exc}")
        raise ToolError(f"Could not search arXiv: {exc} Try again in a moment.") from exc

    _seen_papers.update({p.arxiv_id: p for p in papers})
    message = (
        f"Found {total} matching papers; returning the top {len(papers)}."
        if papers
        else f"No arXiv papers matched '{cleaned}'. Try broader or different keywords."
    )
    log(f"search_arxiv -> {len(papers)} papers")
    return SearchResult(query=cleaned, total_matches=total, papers=papers, message=message)


# --------------------------------------------------------------------------- Action


@mcp.tool(annotations={"readOnlyHint": False, "idempotentHint": True})
def save_to_reading_list(
    arxiv_id: Annotated[
        str,
        Field(description="arXiv ID (e.g. '2507.19570') or arXiv abs/pdf URL of the paper."),
    ],
    note: Annotated[
        str | None, Field(description="Optional short note on why it is worth reading.")
    ] = None,
) -> SaveResult:
    """Save one arXiv paper to the user's reading list. The paper is verified to exist
    on arXiv before saving. Saving a paper that is already in the list does nothing
    and reports status 'already_present'."""
    log(f"save_to_reading_list(arxiv_id={arxiv_id!r}, note={note!r})")
    try:
        paper_id = arxiv_client.normalize_arxiv_id(arxiv_id)
    except arxiv_client.InvalidArxivId as exc:
        raise ToolError(str(exc)) from exc

    paper = _seen_papers.get(paper_id)
    if paper is None:
        try:
            paper = arxiv_client.get_paper(paper_id)
        except arxiv_client.ArxivError as exc:
            raise ToolError(f"Could not verify the paper on arXiv: {exc}") from exc
        if paper is None:
            raise ToolError(
                f"No arXiv paper exists with ID '{paper_id}'. Nothing was saved."
            )

    added, size = storage.add(paper, note.strip() if note else None)
    status = "saved" if added else "already_present"
    message = (
        f"Saved '{paper.title}' to the reading list."
        if added
        else f"'{paper.title}' is already in the reading list; nothing changed."
    )
    log(f"save_to_reading_list -> {status} (list size {size})")
    return SaveResult(
        status=status,
        arxiv_id=paper.arxiv_id,
        title=paper.title,
        reading_list_size=size,
        message=message,
    )


# --------------------------------------------------------------------------- Orchestration


@mcp.tool(annotations={"readOnlyHint": False, "idempotentHint": True, "openWorldHint": True})
def build_reading_list(
    topic: Annotated[str, Field(description="Research topic, e.g. 'LLM tool use'.")],
    n: Annotated[
        int, Field(ge=1, le=10, description="How many new papers to add (1-10).")
    ] = 3,
) -> ReadingListReport:
    """Build a reading list for a topic in one step: runs search_arxiv for the topic,
    then calls save_to_reading_list on the most relevant papers until n new papers
    are saved. Papers already in the list are skipped, not duplicated."""
    log(f"build_reading_list(topic={topic!r}, n={n})")
    # Over-fetch so that papers already in the list don't leave us short.
    search = search_arxiv(topic, max_results=min(20, n * 2 + 2), sort_by="relevance")
    if not search.papers:
        raise ToolError(f"No papers found for '{topic}', so nothing was saved.")

    saved: list[SaveResult] = []
    skipped: list[str] = []
    for paper in search.papers:
        if len(saved) == n:
            break
        result = save_to_reading_list(paper.arxiv_id, note=f"Auto-added for topic: {topic}")
        if result.status == "saved":
            saved.append(result)
        else:
            skipped.append(result.arxiv_id)

    size = len(storage.load())
    message = f"Added {len(saved)} new paper(s) on '{topic}'."
    if len(saved) < n:
        message += f" Only {len(saved)} new relevant papers were available."
    if skipped:
        message += f" Skipped {len(skipped)} already in the list."
    log(f"build_reading_list -> saved {len(saved)}, skipped {len(skipped)}")
    return ReadingListReport(
        topic=topic,
        requested=n,
        saved=saved,
        skipped_already_present=skipped,
        reading_list_size=size,
        message=message,
    )


# --------------------------------------------------------------------------- Resource


@mcp.resource(
    "reading-list://current",
    name="reading_list",
    description="The user's saved reading list (read-only JSON).",
    mime_type="application/json",
)
def reading_list() -> str:
    return json.dumps([e.model_dump() for e in storage.load()], indent=2)


if __name__ == "__main__":
    mcp.run(show_banner=False)

"""Typed data models shared by the arXiv client, storage layer, and MCP tools."""

from pydantic import BaseModel, Field


class Paper(BaseModel):
    """A single arXiv paper, as returned by the arXiv API."""

    arxiv_id: str = Field(description="Version-less arXiv identifier, e.g. '2507.19570'.")
    title: str
    authors: list[str]
    published: str = Field(description="Publication date (YYYY-MM-DD).")
    summary: str = Field(description="Abstract, whitespace-normalized.")
    url: str = Field(description="Link to the arXiv abstract page.")
    primary_category: str | None = None


class SearchResult(BaseModel):
    """Output of the Data tool `search_arxiv`."""

    query: str
    total_matches: int = Field(description="Total number of matches reported by arXiv.")
    papers: list[Paper]
    message: str


class SavedEntry(BaseModel):
    """A paper stored in the reading list, plus the user's note."""

    paper: Paper
    note: str | None = None
    saved_at: str = Field(description="ISO-8601 timestamp of when it was saved.")


class SaveResult(BaseModel):
    """Output of the Action tool `save_to_reading_list`."""

    status: str = Field(description="'saved' or 'already_present'.")
    arxiv_id: str
    title: str
    reading_list_size: int
    message: str


class ReadingListReport(BaseModel):
    """Output of the Orchestration tool `build_reading_list`."""

    topic: str
    requested: int
    saved: list[SaveResult]
    skipped_already_present: list[str] = Field(
        description="arXiv IDs that matched the topic but were already in the list."
    )
    reading_list_size: int
    message: str

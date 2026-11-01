import pytest
from fastmcp import Client

from server import arxiv_client, arxiv_server
from server.models import Paper


def make_paper(arxiv_id: str, title: str) -> Paper:
    return Paper(
        arxiv_id=arxiv_id,
        title=title,
        authors=["Ada Lovelace", "Alan Turing"],
        published="2025-01-15",
        summary=f"Abstract of {title}.",
        url=f"https://arxiv.org/abs/{arxiv_id}",
        primary_category="cs.AI",
    )


FAKE_PAPERS = [
    make_paper("2501.00001", "Tool Use in Language Agents"),
    make_paper("2501.00002", "The Model Context Protocol in Practice"),
    make_paper("2501.00003", "Single-Purpose Tools for Reliable Agents"),
    make_paper("2501.00004", "Orchestrating Agent Workflows"),
    make_paper("2501.00005", "Evaluating Tool-Calling LLMs"),
]


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Each test gets an empty reading list and a fresh search cache."""
    monkeypatch.setenv("READING_LIST_DIR", str(tmp_path))
    arxiv_server._seen_papers.clear()
    yield tmp_path


@pytest.fixture
def fake_arxiv(monkeypatch):
    """Replace network calls with an in-memory fake arXiv."""
    calls = {"search": 0, "get_paper": 0}

    def fake_search(query, max_results, sort_by):
        calls["search"] += 1
        if "nothingmatches" in query:
            return 0, []
        return len(FAKE_PAPERS), FAKE_PAPERS[:max_results]

    def fake_get_paper(arxiv_id):
        calls["get_paper"] += 1
        return next((p for p in FAKE_PAPERS if p.arxiv_id == arxiv_id), None)

    monkeypatch.setattr(arxiv_client, "search", fake_search)
    monkeypatch.setattr(arxiv_client, "get_paper", fake_get_paper)
    return calls


@pytest.fixture
def arxiv_down(monkeypatch):
    """Simulate arXiv being unreachable."""

    def boom(*args, **kwargs):
        raise arxiv_client.ArxivError("arXiv did not respond within 20s.")

    monkeypatch.setattr(arxiv_client, "search", boom)
    monkeypatch.setattr(arxiv_client, "get_paper", boom)


@pytest.fixture
async def client():
    """An MCP client connected in-memory to the server: a real MCP round trip."""
    async with Client(arxiv_server.mcp) as c:
        yield c

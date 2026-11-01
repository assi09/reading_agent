"""Tests for the three MCP tools and the resource, called through an MCP client."""

import json
import os

import pytest

from server import arxiv_client, storage


async def call(client, tool, args):
    return await client.call_tool(tool, args, raise_on_error=False)


# --------------------------------------------------------------------------- discovery


async def test_server_exposes_exactly_three_tools(client):
    tools = {t.name: t for t in await client.list_tools()}
    assert set(tools) == {"search_arxiv", "save_to_reading_list", "build_reading_list"}
    assert tools["search_arxiv"].annotations.read_only_hint is True
    assert tools["save_to_reading_list"].annotations.read_only_hint is False
    for tool in tools.values():
        assert tool.description and tool.output_schema


# --------------------------------------------------------------------------- Data tool


async def test_search_returns_typed_papers(client, fake_arxiv):
    result = await call(client, "search_arxiv", {"query": "tool use", "max_results": 3})
    assert not result.is_error
    data = result.structured_content
    assert [p["arxiv_id"] for p in data["papers"]] == ["2501.00001", "2501.00002", "2501.00003"]
    assert data["total_matches"] == 5


async def test_search_does_not_modify_reading_list(client, fake_arxiv):
    await call(client, "search_arxiv", {"query": "tool use"})
    assert storage.load() == []


async def test_search_no_results_is_explicit(client, fake_arxiv):
    result = await call(client, "search_arxiv", {"query": "nothingmatches"})
    assert not result.is_error
    assert result.structured_content["papers"] == []
    assert "No arXiv papers matched" in result.structured_content["message"]


@pytest.mark.parametrize("query", ["", "   ", "x"])
async def test_search_rejects_empty_query(client, fake_arxiv, query):
    result = await call(client, "search_arxiv", {"query": query})
    assert result.is_error
    assert "empty" in result.content[0].text
    assert fake_arxiv["search"] == 0


async def test_search_rejects_out_of_range_max_results(client, fake_arxiv):
    result = await call(client, "search_arxiv", {"query": "agents", "max_results": 50})
    assert result.is_error
    assert "less than or equal to 20" in result.content[0].text


async def test_search_reports_arxiv_outage(client, arxiv_down):
    result = await call(client, "search_arxiv", {"query": "agents"})
    assert result.is_error
    assert "Could not search arXiv" in result.content[0].text


# --------------------------------------------------------------------------- Action tool


async def test_save_writes_json_markdown_and_bibtex(client, fake_arxiv, isolated_env):
    result = await call(
        client, "save_to_reading_list", {"arxiv_id": "2501.00002", "note": "for C5"}
    )
    assert not result.is_error
    assert result.structured_content["status"] == "saved"
    assert result.structured_content["reading_list_size"] == 1

    entries = storage.load()
    assert entries[0].paper.title == "The Model Context Protocol in Practice"
    assert entries[0].note == "for C5"
    assert "The Model Context Protocol in Practice" in (isolated_env / "reading_list.md").read_text()
    assert "eprint = {2501.00002}" in (isolated_env / "reading_list.bib").read_text()


async def test_save_accepts_urls_and_versions(client, fake_arxiv):
    result = await call(
        client, "save_to_reading_list", {"arxiv_id": "https://arxiv.org/abs/2501.00001v3"}
    )
    assert result.structured_content["arxiv_id"] == "2501.00001"


async def test_save_is_idempotent(client, fake_arxiv):
    await call(client, "save_to_reading_list", {"arxiv_id": "2501.00001"})
    result = await call(client, "save_to_reading_list", {"arxiv_id": "2501.00001"})
    assert result.structured_content["status"] == "already_present"
    assert len(storage.load()) == 1


async def test_save_rejects_malformed_id(client, fake_arxiv):
    result = await call(client, "save_to_reading_list", {"arxiv_id": "not-an-id"})
    assert result.is_error
    assert "not a valid arXiv ID" in result.content[0].text
    assert fake_arxiv["get_paper"] == 0  # rejected before any network call
    assert storage.load() == []


async def test_save_rejects_nonexistent_paper(client, fake_arxiv):
    result = await call(client, "save_to_reading_list", {"arxiv_id": "9999.99999"})
    assert result.is_error
    assert "No arXiv paper exists with ID '9999.99999'" in result.content[0].text
    assert storage.load() == []


async def test_save_reports_arxiv_outage(client, arxiv_down):
    result = await call(client, "save_to_reading_list", {"arxiv_id": "2501.00001"})
    assert result.is_error
    assert "Could not verify the paper on arXiv" in result.content[0].text
    assert storage.load() == []


async def test_save_reuses_papers_from_search(client, fake_arxiv):
    await call(client, "search_arxiv", {"query": "agents"})
    await call(client, "save_to_reading_list", {"arxiv_id": "2501.00001"})
    assert fake_arxiv["get_paper"] == 0


# --------------------------------------------------------------------------- Orchestration tool


async def test_build_reading_list_saves_n_papers(client, fake_arxiv):
    result = await call(client, "build_reading_list", {"topic": "agents", "n": 2})
    assert not result.is_error
    data = result.structured_content
    assert [s["arxiv_id"] for s in data["saved"]] == ["2501.00001", "2501.00002"]
    assert data["reading_list_size"] == 2
    assert fake_arxiv["search"] == 1


async def test_build_reading_list_skips_existing_and_fills_up(client, fake_arxiv):
    await call(client, "save_to_reading_list", {"arxiv_id": "2501.00001"})
    result = await call(client, "build_reading_list", {"topic": "agents", "n": 2})
    data = result.structured_content
    assert data["skipped_already_present"] == ["2501.00001"]
    assert [s["arxiv_id"] for s in data["saved"]] == ["2501.00002", "2501.00003"]
    assert len(storage.load()) == 3


async def test_build_reading_list_with_no_results_saves_nothing(client, fake_arxiv):
    result = await call(client, "build_reading_list", {"topic": "nothingmatches"})
    assert result.is_error
    assert "nothing was saved" in result.content[0].text
    assert storage.load() == []


async def test_build_reading_list_reports_arxiv_outage(client, arxiv_down):
    result = await call(client, "build_reading_list", {"topic": "agents"})
    assert result.is_error
    assert "Could not search arXiv" in result.content[0].text


# --------------------------------------------------------------------------- Resource


async def test_reading_list_resource(client, fake_arxiv):
    await call(client, "save_to_reading_list", {"arxiv_id": "2501.00003"})
    contents = await client.read_resource("reading-list://current")
    entries = json.loads(contents[0].text)
    assert entries[0]["paper"]["arxiv_id"] == "2501.00003"


# --------------------------------------------------------------------------- Helpers


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("2507.19570", "2507.19570"),
        ("2507.19570v2", "2507.19570"),
        ("arxiv.org/pdf/2507.19570v1.pdf", "2507.19570"),
        ("hep-th/9901001", "hep-th/9901001"),
    ],
)
def test_normalize_arxiv_id(raw, expected):
    assert arxiv_client.normalize_arxiv_id(raw) == expected


# --------------------------------------------------------------------------- Live smoke test


@pytest.mark.skipif(not os.environ.get("RUN_LIVE"), reason="set RUN_LIVE=1 to hit arXiv")
async def test_live_search_and_save(client):
    result = await call(client, "search_arxiv", {"query": "model context protocol", "max_results": 2})
    assert result.structured_content["papers"]
    first = result.structured_content["papers"][0]["arxiv_id"]
    saved = await call(client, "save_to_reading_list", {"arxiv_id": first})
    assert saved.structured_content["status"] == "saved"

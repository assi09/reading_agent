"""Tests for reading-list deletion (used by the UI's delete buttons, not an MCP tool)."""

from server import storage
from tests.conftest import FAKE_PAPERS


def test_remove_one_paper_regenerates_files(isolated_env):
    for paper in FAKE_PAPERS[:3]:
        storage.add(paper, None)

    assert storage.remove("2501.00002") is True
    assert [e.paper.arxiv_id for e in storage.load()] == ["2501.00001", "2501.00003"]
    markdown = (isolated_env / "reading_list.md").read_text()
    assert "Model Context Protocol in Practice" not in markdown
    assert "2501.00002" not in (isolated_env / "reading_list.bib").read_text()


def test_remove_missing_paper_is_a_no_op():
    storage.add(FAKE_PAPERS[0], None)
    assert storage.remove("2501.99999") is False
    assert len(storage.load()) == 1


def test_clear_empties_the_list():
    for paper in FAKE_PAPERS:
        storage.add(paper, None)
    assert storage.clear() == len(FAKE_PAPERS)
    assert storage.load() == []


def test_ui_delete_handlers_refresh_panel_and_picker():
    from agent import app

    storage.add(FAKE_PAPERS[0], None)
    storage.add(FAKE_PAPERS[1], None)
    labels = [label for label, _ in app.reading_list_choices().choices]
    assert labels == ["1. Tool Use in Language Agents", "2. The Model Context Protocol in Practice"]

    panel, picker = app.delete_selected("2501.00001")
    assert "Tool Use in Language Agents" not in panel
    assert [value for _, value in picker.choices] == ["2501.00002"]

    panel, picker, _ = app.delete_all()
    assert panel == "_Your reading list is empty._"
    assert picker.choices == []

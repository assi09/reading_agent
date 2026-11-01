# C5 – Agent Tools: Plan

**Theme:** Research Paper Scout — an agent that finds arXiv papers and curates a reading list.
**Stack:** Python 3.13, FastMCP (server), OpenAI Agents SDK (host/client, `gpt-4o-mini`), stdio transport, Gradio UI.

## The three tools

| Category | Tool | Input | Output | Failure case handled |
|---|---|---|---|---|
| **Data** | `search_arxiv` | `query: str`, `max_results: int = 5` (1–20), `sort_by: "relevance" \| "date"` | list of `Paper` (id, title, authors, published, summary, url) | empty/too-long query → clear error; arXiv timeout/HTTP error → `ToolError("arXiv unavailable…")`; no results → empty list + message |
| **Action** | `save_to_reading_list` | `arxiv_id: str`, `note: str \| None` | `SaveResult` (saved / already_present, list size) | malformed arXiv ID → error; unknown ID → error; duplicate → idempotent, no double-write |
| **Orchestration** | `build_reading_list` | `topic: str`, `n: int = 3` (1–10) | `ReadingListReport` (saved papers, skipped duplicates) | propagates Data/Action errors with context; zero results → explicit "nothing saved" |

- Each tool stays single-purpose: search never writes, save never searches, and orchestrate only composes the other two.
- The orchestrator calls the same underlying Python functions as the other two tools, so there is no duplicated logic.
- **Resource:** `reading-list://current` (`@mcp.resource`) is a pure read of the saved list, which satisfies the "pure data lookups as resources" point.
- Persistence: `data/reading_list.json` (source of truth) + auto-generated `reading_list.md` / `.bib` (nice to open during the demo).
- Typed outputs via Pydantic models.

## Project layout

```
c5/
├── server/arxiv_server.py      # FastMCP server: 3 tools + 1 resource
├── server/arxiv_client.py      # thin HTTP + Atom-XML parsing (httpx + feedparser)
├── server/storage.py           # reading-list JSON/MD/BibTeX persistence
├── agent/host.py               # OpenAI Agents SDK Agent + MCPServerStdio
├── agent/app.py                # Gradio chat UI, shows tool calls as collapsible bubbles
├── agent/cli.py                # fallback terminal REPL (handy for debugging)
├── tests/                      # pytest: each tool + failure cases (arXiv mocked) + one live smoke test
├── docs/summary.md             # Part 1 (300–400 words): HF article + Fetch server critique
├── docs/reflection.md          # 1–2 paragraphs
├── docs/demo_script.md         # timed script for the 5–7 min screencast
├── requirements.txt, .env.example, README.md
```

## Steps

1. **Setup:** venv, `requirements.txt` (fastmcp, openai-agents, httpx, feedparser, pydantic, gradio, pytest, pytest-asyncio, python-dotenv), `.env.example`.
2. **Server:** arXiv client → storage → 3 tools + resource. Test standalone with the FastMCP in-memory `Client`.
3. **Tests:** happy path + failure case per tool, using the FastMCP in-memory client (real MCP round trip, no LLM needed).
4. **Agent host:** `MCPServerStdio` launching the server, plus agent instructions for when to use each tool. CLI first.
5. **Gradio UI:** streaming chat; each tool call is shown as a "🔧 search_arxiv(…)" bubble with its result, so the agent → client → server → back round trip is visible.
6. **Docs:** summary (read the HF article + Fetch server source), reflection, README, demo script.
7. **You:** record the screencast, push to GitHub.

## Demo scenarios (for the video)
1. "Find recent papers on the Model Context Protocol" → Data tool only.
2. "Save the second one with note 'read for C5'" → Action tool.
3. "Build me a reading list of 3 papers on LLM tool use" → Orchestration tool.
4. Failure: "Save paper 9999.99999" → clear error, and the agent explains it.
5. Show `reading_list.md` updated on disk.

## Defaults I'll use unless you object
- Plain `venv` + `pip` (uv isn't installed).
- `gpt-4o-mini` (configurable via `OPENAI_MODEL` in `.env`).
- Reading list stored inside the repo's `data/` folder (gitignored).
- You need to put `OPENAI_API_KEY` in `.env` (it isn't set in your shell right now).

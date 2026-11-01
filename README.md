# 📚 Research Paper Scout: an MCP toolkit with FastMCP + OpenAI Agents SDK

EECE 503P/798S, C5 (Agent Tools). An agent that finds arXiv papers and curates a
reading list, using exactly three MCP tools: one **Data**, one **Action**, and one **Orchestration**.

```
┌──────────────── MCP Host ────────────────┐         stdio          ┌──────── MCP Server (FastMCP) ────────┐
│  Gradio UI / CLI                         │   JSON-RPC over pipes  │  search_arxiv          (Data)        │──► arXiv API
│  OpenAI Agents SDK Agent (gpt-4o-mini)   │ ◄────────────────────► │  save_to_reading_list  (Action)      │──► data/reading_list.{json,md,bib}
│  MCPServerStdio  ← the MCP Client        │                        │  build_reading_list    (Orchestration)│
└──────────────────────────────────────────┘                        │  reading-list://current (Resource)   │
                                                                    └──────────────────────────────────────┘
```

## The three tools

| Category | Tool | Arguments | Returns | Failure cases handled |
|---|---|---|---|---|
| **Data** | `search_arxiv` | `query: str`, `max_results: int = 5` (1–20), `sort_by: "relevance" \| "date"` | `SearchResult` (papers with ID, title, authors, date, abstract, URL) | empty/too-long query, `max_results` out of range, arXiv down/timeout, no matches (explicit message) |
| **Action** | `save_to_reading_list` | `arxiv_id: str` (ID or arXiv URL), `note: str \| None` | `SaveResult` (`saved` / `already_present`, list size) | malformed ID, ID that doesn't exist on arXiv, arXiv down; duplicate saves are idempotent |
| **Orchestration** | `build_reading_list` | `topic: str`, `n: int = 3` (1–10) | `ReadingListReport` (saved papers, skipped duplicates) | no results → nothing saved + clear error; errors from the two inner tools pass through unchanged |

There's also one **resource**, `reading-list://current`, a pure read of the saved list.

Design notes:
- **Single-purpose:** search never writes; save writes exactly one paper; the orchestrator holds no
  arXiv or storage logic of its own. It calls `search_arxiv`, then `save_to_reading_list` for each result.
- **Typed I/O:** arguments are validated with Pydantic `Field` constraints, and outputs are Pydantic models,
  so every tool publishes an `outputSchema`.
- **Predictable errors:** expected failures raise `ToolError` with a human-readable message. The client
  receives it as an `isError` result, and the agent explains it to the user.
- **Tool annotations:** `readOnlyHint` / `idempotentHint` / `openWorldHint` tell the host which tools
  are safe to call.

## Setup

Requires Python 3.11+ and an OpenAI API key.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then put your OPENAI_API_KEY in .env
```

## Run

```bash
python -m agent.app           # Gradio web UI → http://127.0.0.1:7860
python -m agent.cli           # same agent in the terminal
python -m server.arxiv_server # just the MCP server over stdio (e.g. for Claude Desktop / MCP Inspector)
```

The host launches the server as a subprocess. Server logs (`[mcp-server] ...`) print in the same
terminal, so you can watch each request reach the server. In the web UI, every tool call appears
as a collapsible 🔧 bubble showing the arguments sent and the server's response. The right-hand
panel shows `data/reading_list.md` updating live. Below it, you can delete one paper (picked by
number and title) or clear the whole list. These buttons edit the file directly; they are not
MCP tools, so the agent's toolkit stays at exactly three tools.

Example prompts:
1. `Find recent papers on the Model Context Protocol` → Data tool
2. `Save the second one with the note "read for C5"` → Action tool
3. `Build me a reading list of 3 papers on LLM tool use` → Orchestration tool
4. `Save paper 9999.99999` → failure case: clear error, nothing saved

## Tests

```bash
pytest                 # 29 tests, arXiv mocked, each runs a real MCP round trip via FastMCP's in-memory Client
RUN_LIVE=1 pytest      # also runs a live smoke test against arXiv
```

The tests cover every tool's happy path and failure cases (invalid input, nonexistent paper, arXiv
outage, no results), idempotency, the orchestrator's skip-duplicates behavior, and the resource.

## Project layout

```
server/
  arxiv_server.py   FastMCP server: the 3 tools + resource
  arxiv_client.py   arXiv HTTP + Atom parsing, ID validation (no MCP code)
  storage.py        reading list persistence (JSON + generated Markdown/BibTeX)
  models.py         Pydantic input/output models
agent/
  host.py           Agents SDK agent + MCPServerStdio client, streamed events
  app.py            Gradio UI
  cli.py            terminal REPL
tests/              pytest suite
docs/
  summary.md        Part 1: article summary + Fetch server critique
  reflection.md     reflection
```

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | (required) | used by the Agents SDK |
| `OPENAI_MODEL` | `gpt-4o-mini` | model the agent runs on |
| `READING_LIST_DIR` | `./data` | where the reading list is stored |

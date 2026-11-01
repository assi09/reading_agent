"""MCP Host: an OpenAI Agents SDK agent wired to the Research Paper Scout server.

The agent is the Host; `MCPServerStdio` is the MCP Client. It launches
`server/arxiv_server.py` as a subprocess and talks MCP over stdin/stdout.

Both the CLI (agent/cli.py) and the Gradio UI (agent/app.py) use `run_turn`,
which streams simplified events so each front end can show the round trip.
"""

import json
import os
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from agents import Agent, Runner, SQLiteSession
from agents.mcp import MCPServerStdio
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

INSTRUCTIONS = """\
You are Research Paper Scout, an assistant that helps the user find arXiv papers \
and keep a reading list. You have three tools:

- search_arxiv (Data): look up papers. Use it for any "find / search / what's new" \
request. It never saves anything.
- save_to_reading_list (Action): save ONE specific paper the user chose, by arXiv ID.
- build_reading_list (Orchestration): when the user wants several papers on a topic \
found AND saved in one go, use this instead of chaining the other two yourself.

Rules:
- When you show search results, number them and always include each arXiv ID, so \
the user can say "save the second one".
- Only pass arXiv IDs that came from a tool result or from the user. Never invent or \
guess IDs. If the user refers to an earlier result ("the second one") and you cannot \
see that list in this conversation, say so and offer to search again instead of \
calling save_to_reading_list.
- When the user types an arXiv ID themselves, always call save_to_reading_list with \
it exactly as given, even if it looks unusual. Do not judge whether it is valid \
yourself: the server checks it against arXiv and reports a clear error if it is wrong. \
When that happens, relay the server's error message to the user.
- If a tool returns an error, tell the user plainly what went wrong and what they \
can do next. Do not retry with made-up arguments.
- Keep answers short: title, first author, year, ID, and one line on why it matters.
"""


def create_server() -> MCPServerStdio:
    """MCP client that spawns the FastMCP server over stdio."""
    return MCPServerStdio(
        name="research-paper-scout",
        params={
            "command": sys.executable,
            "args": ["-m", "server.arxiv_server"],
            "cwd": str(PROJECT_ROOT),
            "env": {**os.environ},
        },
        client_session_timeout_seconds=60,  # arXiv can be slow
    )


def create_agent(server: MCPServerStdio) -> Agent:
    return Agent(
        name="Research Paper Scout",
        instructions=INSTRUCTIONS,
        model=MODEL,
        mcp_servers=[server],
    )


@dataclass
class ToolCall:
    call_id: str
    name: str
    arguments: dict


@dataclass
class ToolOutput:
    call_id: str
    text: str
    is_error: bool


@dataclass
class TextDelta:
    text: str


Event = ToolCall | ToolOutput | TextDelta


def _output_text(output) -> str:
    """Tool outputs arrive as a str, a {'type': 'text', 'text': ...} dict, or a list of those."""
    if isinstance(output, str):
        return output
    if isinstance(output, dict):
        return output.get("text", json.dumps(output))
    if isinstance(output, list):
        return "\n".join(_output_text(o) for o in output)
    return str(output)


def _is_json(text: str) -> bool:
    # Successful calls return JSON (the typed Pydantic output); ToolErrors return plain text.
    try:
        json.loads(text)
        return True
    except ValueError:
        return False


async def run_turn(
    agent: Agent, user_message: str, session: SQLiteSession
) -> AsyncIterator[Event]:
    """Run one user turn and yield tool calls, tool outputs, and text as they happen."""
    result = Runner.run_streamed(agent, user_message, session=session, max_turns=12)
    async for event in result.stream_events():
        if event.type == "raw_response_event":
            if getattr(event.data, "type", "") == "response.output_text.delta":
                yield TextDelta(event.data.delta)
        elif event.type == "run_item_stream_event":
            if event.name == "tool_called":
                raw = event.item.raw_item
                try:
                    args = json.loads(raw.arguments or "{}")
                except ValueError:
                    args = {"raw": raw.arguments}
                yield ToolCall(call_id=raw.call_id, name=raw.name, arguments=args)
            elif event.name == "tool_output":
                raw = event.item.raw_item
                call_id = raw["call_id"] if isinstance(raw, dict) else raw.call_id
                text = _output_text(event.item.output)
                yield ToolOutput(call_id=call_id, text=text, is_error=not _is_json(text))

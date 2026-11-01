"""Terminal chat with the Research Paper Scout agent.

    python -m agent.cli
"""

import asyncio
import json
import uuid

from agents import SQLiteSession

from agent.host import (
    MODEL,
    TextDelta,
    ToolCall,
    ToolOutput,
    create_agent,
    create_server,
    run_turn,
)

DIM, CYAN, RED, RESET = "\033[2m", "\033[36m", "\033[31m", "\033[0m"


async def main() -> None:
    session = SQLiteSession(f"cli-{uuid.uuid4()}")
    async with create_server() as server:
        tools = await server.list_tools()
        print(f"Connected to MCP server '{server.name}' ({MODEL}).")
        print("Tools: " + ", ".join(t.name for t in tools))
        print("Type 'quit' to exit.\n")
        agent = create_agent(server)

        while True:
            try:
                message = input("you> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if message.lower() in {"quit", "exit"}:
                break
            if not message:
                continue

            print("agent> ", end="", flush=True)
            async for event in run_turn_safe(agent, message, session):
                if isinstance(event, ToolCall):
                    print(f"\n{CYAN}  → MCP call {event.name}({json.dumps(event.arguments)}){RESET}")
                elif isinstance(event, ToolOutput):
                    color = RED if event.is_error else DIM
                    preview = event.text if len(event.text) < 300 else event.text[:300] + "…"
                    print(f"{color}  ← {'ERROR: ' if event.is_error else ''}{preview}{RESET}")
                    print("agent> ", end="", flush=True)
                elif isinstance(event, TextDelta):
                    print(event.text, end="", flush=True)
            print("\n")


async def run_turn_safe(agent, message, session):
    try:
        async for event in run_turn(agent, message, session):
            yield event
    except Exception as exc:  # surface API/key problems instead of a traceback
        yield TextDelta(f"[error] {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    asyncio.run(main())

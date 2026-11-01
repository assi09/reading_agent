"""Gradio chat UI for the Research Paper Scout agent.

    python -m agent.app        # then open http://127.0.0.1:7860

Every MCP tool call shows up in the chat as a collapsible bubble with its
arguments and the server's response, so the full round trip is visible:
agent -> MCP client -> FastMCP server -> back. The panel on the right shows
the reading list on disk and refreshes after every turn.
"""

import json
import os
import uuid

import gradio as gr
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
from server import storage

TOOL_KIND = {
    "search_arxiv": "Data",
    "save_to_reading_list": "Action",
    "build_reading_list": "Orchestration",
}

EXAMPLES = [
    "Find recent papers on the Model Context Protocol",
    "Save the second one with the note 'read for C5'",
    "Build me a reading list of 3 papers on LLM tool use",
    "Save paper 9999.99999",
    "What's in my reading list so far?",
]

# One agent memory per browser tab; reset when the chat is cleared.
_sessions: dict[str, SQLiteSession] = {}


def reading_list_markdown() -> str:
    path = storage.data_dir() / "reading_list.md"
    text = path.read_text().replace("# Reading List\n", "", 1).strip() if path.exists() else ""
    return text or "_Your reading list is empty._"


def reading_list_choices() -> gr.Dropdown:
    choices = [(f"{i}. {e.paper.title}", e.paper.arxiv_id) for i, e in enumerate(storage.load(), 1)]
    return gr.Dropdown(choices=choices, value=None)


# Manual controls: these edit the list directly from the UI and are not MCP tools,
# so the agent's toolkit stays at exactly three tools.


def delete_selected(arxiv_id: str | None):
    if arxiv_id:
        storage.remove(arxiv_id)
    return reading_list_markdown(), reading_list_choices()


def delete_all():
    storage.clear()
    return reading_list_markdown(), reading_list_choices(), gr.Button(visible=False)


def _message_text(content) -> str:
    """Gradio history content is a str or a list of {'type': 'text', 'text': ...} blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(_message_text(c) for c in content)
    if isinstance(content, dict):
        return content.get("text", "")
    return ""


async def _session_for(request: gr.Request, history: list) -> SQLiteSession:
    key = request.session_hash or "default"
    if history and key in _sessions:
        return _sessions[key]
    session = SQLiteSession(f"ui-{uuid.uuid4()}")
    # The chat on screen can outlive the agent's memory (e.g. after an app restart).
    # Rebuild it from the visible user/assistant text, skipping tool bubbles, so
    # follow-ups like "save the second one" still see the earlier results.
    items = [
        {"role": m["role"], "content": text}
        for m in history
        if m.get("role") in ("user", "assistant")
        and not (m.get("metadata") or {}).get("title")
        and (text := _message_text(m.get("content")))
    ]
    if items:
        await session.add_items(items)
    _sessions[key] = session
    return session


def _shorten(value):
    """Trim long strings and author lists so the bubble stays readable, valid JSON."""
    if isinstance(value, dict):
        return {
            k: (v[:2] + [f"+{len(v) - 2} more"] if k == "authors" and len(v) > 3 else _shorten(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_shorten(v) for v in value]
    if isinstance(value, str) and len(value) > 140:
        return value[:140] + "…"
    return value


def _format_output(text: str) -> str:
    try:
        pretty = json.dumps(_shorten(json.loads(text)), indent=2, ensure_ascii=False)
    except ValueError:
        return f"**Error from MCP server:**\n\n{text}"
    return f"```json\n{pretty}\n```"


async def respond(message: str, history: list, request: gr.Request):
    if not os.environ.get("OPENAI_API_KEY"):
        yield [gr.ChatMessage("OPENAI_API_KEY is not set. Add it to `.env` and restart.")], reading_list_markdown(), reading_list_choices()
        return

    session = await _session_for(request, history)
    messages: list[gr.ChatMessage] = []
    tool_bubbles: dict[str, gr.ChatMessage] = {}
    answer: gr.ChatMessage | None = None

    try:
        async with create_server() as server:
            agent = create_agent(server)
            async for event in run_turn(agent, message, session):
                if isinstance(event, ToolCall):
                    answer = None  # any text after this call goes in a new bubble
                    kind = TOOL_KIND.get(event.name, "Tool")
                    bubble = gr.ChatMessage(
                        content=f"**Arguments sent to MCP server:**\n```json\n"
                        f"{json.dumps(event.arguments, indent=2)}\n```",
                        metadata={
                            "title": f"🔧 {kind} tool · {event.name}",
                            "status": "pending",
                        },
                    )
                    tool_bubbles[event.call_id] = bubble
                    messages.append(bubble)
                elif isinstance(event, ToolOutput):
                    bubble = tool_bubbles.get(event.call_id)
                    if bubble is not None:
                        bubble.content += "\n\n**Response from MCP server:**\n" + _format_output(event.text)
                        bubble.metadata["status"] = "done"
                        if event.is_error:
                            bubble.metadata["title"] = "⚠️ " + bubble.metadata["title"][2:] + " · error"
                elif isinstance(event, TextDelta):
                    if answer is None:
                        answer = gr.ChatMessage(content="")
                        messages.append(answer)
                    answer.content += event.text
                yield messages, reading_list_markdown(), gr.skip()
    except Exception as exc:
        messages.append(gr.ChatMessage(f"⚠️ {type(exc).__name__}: {exc}"))

    yield messages, reading_list_markdown(), reading_list_choices()


def build_ui() -> gr.Blocks:
    with gr.Blocks(title="Research Paper Scout") as demo:
        gr.Markdown(
            "# 📚 Research Paper Scout\n"
            f"OpenAI Agents SDK (`{MODEL}`) ⇄ MCP over stdio ⇄ FastMCP server · "
            "**Data:** `search_arxiv` · **Action:** `save_to_reading_list` · "
            "**Orchestration:** `build_reading_list`"
        )
        with gr.Row():
            with gr.Column(scale=3):
                reading_list = gr.Markdown(reading_list_markdown(), render=False)
                picker = gr.Dropdown(
                    label="Pick a paper to delete", choices=[], value=None, render=False
                )
                gr.ChatInterface(
                    respond,
                    chatbot=gr.Chatbot(
                        height=620, show_label=False, group_consecutive_messages=False
                    ),
                    additional_outputs=[reading_list, picker],
                    examples=EXAMPLES,
                    run_examples_on_click=False,
                )
            with gr.Column(scale=2):
                gr.Markdown("### 📄 Reading list (`data/reading_list.md`)")
                reading_list.render()
                with gr.Group():
                    picker.render()
                    with gr.Row():
                        delete_one = gr.Button("🗑️ Delete selected", size="sm")
                        ask_clear = gr.Button("Delete all", size="sm", variant="stop")
                    confirm_clear = gr.Button(
                        "⚠️ Yes, delete every paper", size="sm", variant="stop", visible=False
                    )
        delete_one.click(delete_selected, inputs=picker, outputs=[reading_list, picker])
        ask_clear.click(lambda: gr.Button(visible=True), outputs=confirm_clear)
        confirm_clear.click(delete_all, outputs=[reading_list, picker, confirm_clear])
        demo.load(
            lambda: (reading_list_markdown(), reading_list_choices()),
            outputs=[reading_list, picker],
        )
    return demo


if __name__ == "__main__":
    build_ui().launch(theme=gr.themes.Soft())

"""
LangGraph ReAct health agent — 6 core tools.
Streams response chunks for SSE.
"""
from __future__ import annotations
from typing import AsyncGenerator, TypedDict, Annotated
import operator
import json

from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

from config import settings
from agents.tools import get_tools
from prompts.chat import build_system_prompt


class AgentState(TypedDict):
    messages: Annotated[list, operator.add]
    user_id: str
    memories: str
    requires_clinical_review: bool


def _build_graph():
    tools = get_tools()
    model = ChatOpenAI(
        model=settings.PRIMARY_MODEL,
        api_key=settings.OPENAI_API_KEY,
        streaming=True,
    ).bind_tools(tools)

    def call_model(state: AgentState):
        system = build_system_prompt(state["user_id"], state.get("memories", ""))
        response = model.invoke([
            {"role": "system", "content": system},
            *state["messages"]
        ])
        return {"messages": [response]}

    def should_continue(state: AgentState) -> str:
        last = state["messages"][-1]
        if hasattr(last, "tool_calls") and last.tool_calls:
            return "tools"
        return END

    graph = StateGraph(AgentState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", ToolNode(tools))
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue)
    graph.add_edge("tools", "agent")
    return graph.compile()


_graph = None

def get_graph():
    global _graph
    if _graph is None:
        _graph = _build_graph()
    return _graph


async def run_health_agent(
    user_id: str,
    message: str,
    conversation_id: str,
    report_id: str | None,
    memories: str,
    conversation_history: list[dict] | None = None,
) -> AsyncGenerator[str, None]:
    graph = get_graph()
    prior = conversation_history or []
    initial_state: AgentState = {
        "messages": [*prior, {"role": "user", "content": message}],
        "user_id": user_id,
        "memories": memories,
        "requires_clinical_review": False,
    }

    async for event in graph.astream_events(initial_state, version="v2"):
        kind = event.get("event")
        if kind == "on_chat_model_stream":
            chunk = event["data"].get("chunk")
            if chunk and hasattr(chunk, "content") and chunk.content:
                yield chunk.content

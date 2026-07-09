from __future__ import annotations
from functools import lru_cache
from langgraph.graph import END, StateGraph
from app.rag.graph.state import RAGState
from app.rag.graph.nodes import (
    node_route,
    node_load_session,
    node_retrieve,
    node_web_search,
    node_generate,
    node_generate_web,
    node_check_hallucination,
    node_save_to_memory,
)
from app.rag.graph.edges import edge_route_decision

@lru_cache(maxsize=1)
def get_rag_graph():
    graph = StateGraph(RAGState)

    graph.add_node("route",               node_route)
    graph.add_node("load_session",        node_load_session)
    graph.add_node("retrieve",            node_retrieve)
    graph.add_node("web_search",          node_web_search)
    graph.add_node("generate",            node_generate)
    graph.add_node("generate_web",        node_generate_web)
    graph.add_node("check_hallucination", node_check_hallucination)
    graph.add_node("save_to_memory",      node_save_to_memory)

    graph.set_entry_point("load_session")

    graph.add_edge("load_session", "route")

    graph.add_conditional_edges(
        "route",
        edge_route_decision,
        {
            "retrieve":   "retrieve",
            "web_search": "web_search",
        }
    )
    graph.add_edge("retrieve",    "generate")
    graph.add_edge("web_search",  "generate_web")
    graph.add_edge("generate",    "check_hallucination")
    graph.add_edge("generate_web","check_hallucination")
    graph.add_edge("check_hallucination", "save_to_memory")
    graph.add_edge("save_to_memory", END)
    return graph.compile()

async def run_rag_graph(
    question: str,
    conversation_id: str,
    tenant_id: str,
    tenant_slug: str,
    user_id: str,
    collection_id: str | None = None,
    mode: str = "rag",
) -> RAGState:
    graph = get_rag_graph()
    initial_state: RAGState = {
        "question": question,
        "conversation_id": conversation_id,
        "tenant_id": tenant_id,
        "tenant_slug": tenant_slug,
        "user_id": user_id,
        "collection_id": collection_id,
        "mode": mode,
        "route": None,
        "retrieved_chunks": [],
        "session_messages": [],
        "web_results": None,
        "answer": "",
        "sources": [],
        "tokens_in": 0,
        "tokens_out": 0,
        "latency_ms": 0,
        "hallucination_score": None,
        "error": None,
    }
    final_state = await graph.ainvoke(initial_state)
    return final_state


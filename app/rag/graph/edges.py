from __future__ import annotations
from app.rag.graph.state import RAGState

def edge_route_decision(state: RAGState) -> str:
    route = state.get("route", "rag")
    if route == "web":
        return "web_search"
    return "retrieve"


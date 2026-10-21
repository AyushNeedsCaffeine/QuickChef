from __future__ import annotations

from typing import Annotated, Optional, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    session_id: str
    messages: Annotated[list, add_messages]
    dish: Optional[str]
    servings: Optional[int]
    preparsed: bool
    candidates: list[dict]
    needs_clarification: bool
    ingredients: list[dict]
    steps: list[str]
    recipe_source: Optional[str]
    cart: list[dict]
    unmatched: list[str]
    stage: str
    reply: str
    error: Optional[str]
    payment_method: Optional[str]
    address: Optional[str]
    order: Optional[dict]

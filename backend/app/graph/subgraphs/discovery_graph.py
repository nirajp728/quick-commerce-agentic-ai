import json
import logging
from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate

from backend.app.graph.state import AgentState
from backend.app.utils.llm_factory import get_llm, get_structured_llm
from backend.app.tools.db_tools import check_inventory
from backend.app.config import settings

logger = logging.getLogger(settings.APP_NAME)

class RecipeDeconstruction(BaseModel):
    ingredients: list[str] = Field(description="List of core ingredients needed.")
    broadened: bool = Field(default=False, description="True if terms were broadened due to a previous failure.")

def extract_ingredients_node(state: AgentState) -> dict:
    """Uses the LLM's own general knowledge to determine what a dish
    actually needs. This is the source of truth for 'what are the
    ingredients' — the catalog is never used to validate this list,
    only to check what's purchasable from it."""
    logger.info("Discovery Subgraph: Extracting ingredients...")
    last_message = state.get("discovery_original_query") or state["messages"][-1].content
    llm = get_structured_llm(RecipeDeconstruction)

    prompt = ChatPromptTemplate.from_messages([
        ("system", """Deconstruct the user's request into a list of generic grocery search terms.

        - If it's a direct question about whether a SPECIFIC named product is available (e.g. "do you
          have Amul butter", "what about milk", "is X in stock"), the list should contain just that one
          product name itself — do NOT extract ingredients needed to make/produce that product.
        - If it's a request for a recipe or meal (e.g. "ingredients for butter chicken"), extract that
          dish's actual core ingredients using accurate general knowledge.
        - If it's a general browsing request with no specific item or dish, extract 2-3 broad category
          terms instead."""),
        ("human", "{input}")
    ])

    output = (prompt | llm).invoke({"input": last_message})
    return {
        "discovery_items": output.ingredients,
        "discovery_retries": state.get("discovery_retries", 0),
        "discovery_original_query": last_message,
    }

def search_inventory_node(state: AgentState) -> dict:
    """Checks store availability for each real ingredient term. This is a
    pure stock/price lookup — it never redefines what the ingredients are."""
    logger.info("Discovery Subgraph: Checking catalog availability...")
    items = state.get("discovery_items", [])
    found_items = []
    seen_product_ids = set()

    for item in items:
        result = json.loads(check_inventory.invoke({"query": item, "limit": 1}))
        if result.get("status") == "success":
            match = result["items"][0]
            if match["product_id"] not in seen_product_ids:
                found_items.append(match)
                seen_product_ids.add(match["product_id"])

    return {"found_items": found_items}

def route_discovery(state: AgentState) -> str:
    found = state.get("found_items", [])
    items = state.get("discovery_items", [])
    retries = state.get("discovery_retries", 0)

    if len(found) >= (len(items) / 2) or len(items) == 0:
        return "format_recipe"
    if retries >= 2:
        logger.warning("Discovery Subgraph: Max retries hit. Formatting what we have.")
        return "format_recipe"
    logger.info("Discovery Subgraph: Poor match rate. Triggering reflection loop.")
    return "reflect_and_broaden"

def reflect_node(state: AgentState) -> dict:
    retries = state.get("discovery_retries", 0)
    current_items = state.get("discovery_items", [])
    return {
        "messages": [AIMessage(content=f"Failed to find: {current_items}. Broaden the search terms to general categories.")],
        "discovery_retries": retries + 1
    }

def format_recipe_node(state: AgentState) -> dict:
    """Reports store availability as a plain fact — found vs. not found —
    without asserting this list defines the dish. That correctness stays
    with the LLM's own knowledge, applied later in answer_node."""
    logger.info("Discovery Subgraph: Compiling availability facts...")
    found_items = state.get("found_items", [])
    original_query = state.get("discovery_original_query") or ""
    requested_items = state.get("discovery_items", [])

    found_names = {i["name"].lower() for i in found_items}
    missing_terms = [t for t in requested_items if not any(t.lower() in n for n in found_names)]

    if not found_items:
        fact = f"Store availability check for \"{original_query}\": none of the searched terms ({', '.join(requested_items)}) were found in our catalog."
    else:
        lines = "\n".join(f"- {i['name']}: ₹{i['price']}" for i in found_items)
        fact = f"Store availability check for \"{original_query}\":\nIn stock:\n{lines}"
        if missing_terms:
            fact += f"\nNot in stock: {', '.join(missing_terms)}"

    return {
        "gathered_context": [fact],
        "discovery_retries": 0,
        "discovery_original_query": None,
        "last_offered_items": found_items,
    }

# Compile the Subgraph
builder = StateGraph(AgentState)
builder.add_node("extract", extract_ingredients_node)
builder.add_node("search", search_inventory_node)
builder.add_node("reflect", reflect_node)
builder.add_node("format_recipe", format_recipe_node)

builder.add_edge(START, "extract")
builder.add_edge("extract", "search")
builder.add_conditional_edges("search", route_discovery, {"format_recipe": "format_recipe", "reflect_and_broaden": "reflect"})
builder.add_edge("reflect", "extract")
builder.add_edge("format_recipe", END)

discovery_subgraph = builder.compile()
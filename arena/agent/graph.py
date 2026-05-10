"""
Phase 0 commentary agent.
Two-node LangGraph:
  event_detector  (gpt-4o-mini) → detects coding moments worth commenting on
  commentary_gen  (gpt-4o)      → writes the actual commentary line

Note: Originally designed for Kimi K2.5 as detector; falls back to gpt-4o-mini
since Moonshot API key was not valid at time of implementation.
"""
import time
from typing import Optional
from pydantic import BaseModel
from openai import OpenAI
from langgraph.graph import StateGraph, END

from arena.config import settings


# ── Clients ──────────────────────────────────────────────────────────────────

gpt_client = OpenAI(api_key=settings.openai_api_key)

# Detection model: gpt-4o-mini (cheap, structured output)
# Swap to Kimi when a valid Moonshot key is available
DETECT_MODEL = "gpt-4o-mini"
detect_client = gpt_client


# ── State ─────────────────────────────────────────────────────────────────────

class Snapshot(BaseModel):
    player: str          # 'a' | 'b'
    code: str
    ts_ms: int
    prev_code: str = ""  # code from previous snapshot


class DetectedEvent(BaseModel):
    event_type: str      # e.g. "syntax_error_introduced", "algo_approach_changed"
    confidence: float    # 0.0 – 1.0
    evidence: str        # short quote or explanation


class AgentState(BaseModel):
    snapshot: Snapshot
    event: Optional[DetectedEvent] = None
    commentary: Optional[str] = None
    should_comment: bool = False
    latency_detect_ms: int = 0
    latency_comment_ms: int = 0


# ── Prompts ───────────────────────────────────────────────────────────────────

DETECT_SYSTEM = """\
You are an expert competitive programmer watching a live coding match.
Given two snapshots of a player's code (previous and current), identify whether
a notable moment just occurred. Be specific and concise.

Respond with JSON matching this schema exactly:
{
  "event_type": "<one of: syntax_error_introduced | syntax_error_fixed | approach_changed | brute_force_started | optimization_started | test_case_considered | stuck_and_deleting | breakthrough | debugging | idle>",
  "confidence": <float 0.0-1.0>,
  "evidence": "<one sentence quoting or describing the specific change>"
}

Only flag confidence >= 0.6 as noteworthy. Return confidence < 0.6 for idle/no-change."""

COMMENTARY_SYSTEM = """\
You are a witty, insightful sports commentator covering a competitive coding match.
Your style is like a mix of a chess grandmaster analyst and a sports broadcaster —
technically sharp, occasionally humorous, never condescending.

Write ONE punchy commentary line (max 25 words) reacting to the detected coding event.
Be specific to the actual code change. Never be generic like "Player A is writing code."
"""


# ── Nodes ─────────────────────────────────────────────────────────────────────

def event_detector(state: AgentState) -> AgentState:
    snap = state.snapshot
    user_msg = f"""Player {snap.player.upper()} — code change detected.

PREVIOUS CODE:
```python
{snap.prev_code or "(no previous code — match just started)"}
```

CURRENT CODE:
```python
{snap.code}
```

Analyze and respond with JSON."""

    t0 = time.perf_counter()
    resp = detect_client.chat.completions.create(
        model=DETECT_MODEL,
        messages=[
            {"role": "system", "content": DETECT_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
    )
    latency = int((time.perf_counter() - t0) * 1000)

    import json
    raw = json.loads(resp.choices[0].message.content)
    event = DetectedEvent(**raw)
    should_comment = event.confidence >= 0.6 and event.event_type != "idle"

    return state.model_copy(update={
        "event": event,
        "should_comment": should_comment,
        "latency_detect_ms": latency,
    })


def commentary_gen(state: AgentState) -> AgentState:
    if not state.should_comment or not state.event:
        return state

    snap = state.snapshot
    user_msg = f"""Player {snap.player.upper()} just had a "{state.event.event_type}" moment.
Evidence: {state.event.evidence}

Current code:
```python
{snap.code}
```

Write one commentary line."""

    t0 = time.perf_counter()
    resp = gpt_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": COMMENTARY_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=60,
        temperature=0.8,
    )
    latency = int((time.perf_counter() - t0) * 1000)

    return state.model_copy(update={
        "commentary": resp.choices[0].message.content.strip(),
        "latency_comment_ms": latency,
    })


def should_generate(state: AgentState) -> str:
    return "commentary_gen" if state.should_comment else END


# ── Graph ─────────────────────────────────────────────────────────────────────

def build_graph():
    g = StateGraph(AgentState)
    g.add_node("event_detector", event_detector)
    g.add_node("commentary_gen", commentary_gen)
    g.set_entry_point("event_detector")
    g.add_conditional_edges("event_detector", should_generate)
    g.add_edge("commentary_gen", END)
    return g.compile()


commentary_graph = build_graph()


def run_on_snapshot(snapshot: Snapshot) -> AgentState:
    initial = AgentState(snapshot=snapshot)
    result = commentary_graph.invoke(initial)
    return AgentState(**result)

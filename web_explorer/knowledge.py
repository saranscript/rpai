from __future__ import annotations

"""Data structures and utilities that form the *knowledge* backbone of Web-Explorer.

This module is a Python re-implementation of the concepts introduced in Section 3.2 of the
LLM-Explorer paper, generalized for browser-based (Playwright) environments.
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Tuple, Optional
import uuid
import networkx as nx


class ExplorationFlag(str, Enum):
    """Enum mirrors the three exploration flags used by the paper."""

    UNEXPLORED = "unexplored"
    EXPLORED = "explored"
    INEFFECTIVE = "ineffective"


class ActionType(str, Enum):
    """Supported interaction primitives on the Web side."""

    CLICK = "click"
    LONG_CLICK = "long_click"
    SCROLL = "scroll"
    INPUT = "input"


@dataclass
class UIElement:
    """A concrete DOM element.

    For now we store only its unique *Playwright* identifier (DOM path obtained
    from the JS helper). In the future we can attach additional meta information
    such as bounding box, text, aria-label, etc.
    """

    node_id: str  # An id that can be resolved back to the DOM via page_script.js
    description: str


@dataclass
class AbstractAction:
    """Aggregates multiple concrete actions that trigger the same behaviour."""

    action_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    action_type: ActionType = ActionType.CLICK
    # A *representative* set of concrete elements. For clicks we usually store a
    # collection of ids at the same DOM location across dynamic states.
    actual_elements: List[UIElement] = field(default_factory=list)
    exploration_flag: ExplorationFlag = ExplorationFlag.UNEXPLORED
    function_desc: str = ""  # short natural language summary

    # back-pointer to source / destination states set during graph insertion
    source_abs_state: "AbstractState" | None = field(default=None, repr=False)
    target_abs_state: "AbstractState" | None = field(default=None, repr=False)


@dataclass
class AbstractState:
    """A cluster of visually-different but semantically-equivalent DOM trees."""

    state_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    # A random concrete snapshot (DOM skeleton hash) for quick similarity check.
    repr_signature: str = ""
    concrete_states: List[Any] = field(default_factory=list)  # opaque snapshots

    # Mapping (action_id -> AbstractAction) that are available *on* this state
    actions: Dict[str, AbstractAction] = field(default_factory=dict, repr=False)

    # ---- NEW FIELDS (knowledge organisation prompt outputs) -------------
    page_description: str = ""  # short natural-language summary of the page
    element_groups: List[Dict[str, Any]] = field(default_factory=list, repr=False)


class AbstractInteractionGraph:
    """Directed Multi-DiGraph connecting abstract states via abstract actions."""

    def __init__(self) -> None:
        self._g: nx.MultiDiGraph = nx.MultiDiGraph()

    # --- state helpers ----------------------------------------------------
    def add_state(self, state: AbstractState) -> None:
        if state.state_id not in self._g:
            self._g.add_node(state.state_id, obj=state)

    def get_state(self, state_id: str) -> Optional[AbstractState]:
        if state_id in self._g:
            return self._g.nodes[state_id]["obj"]
        return None

    # --- edge helpers -----------------------------------------------------
    def add_edge(self, src: AbstractState, action: AbstractAction, dst: AbstractState) -> None:
        self.add_state(src)
        self.add_state(dst)
        self._g.add_edge(src.state_id, dst.state_id, key=action.action_id, obj=action)
        # Update back-pointers
        action.source_abs_state = src
        action.target_abs_state = dst

    def successors(self, state: AbstractState) -> List[Tuple[AbstractState, AbstractAction]]:
        res: List[Tuple[AbstractState, AbstractAction]] = []
        for _, dst_id, key in self._g.out_edges(state.state_id, keys=True):
            dst = self._g.nodes[dst_id]["obj"]
            action = self._g.edges[state.state_id, dst_id, key]["obj"]
            res.append((dst, action))
        return res

    def shortest_path(self, src: AbstractState, dst: AbstractState) -> List[AbstractAction]:
        """Return a list of AbstractActions along the shortest path."""
        try:
            path_nodes = nx.shortest_path(self._g, src.state_id, dst.state_id)
            # translate node path to action path
            actions: List[AbstractAction] = []
            for i in range(len(path_nodes) - 1):
                # pick *any* action along edge; MultiDiGraph could have several
                edge_data = self._g.get_edge_data(path_nodes[i], path_nodes[i + 1])
                if not edge_data:
                    continue
                # choose first key deterministically
                first_key = list(edge_data.keys())[0]
                actions.append(edge_data[first_key]["obj"])
            return actions
        except nx.NetworkXNoPath:
            return []

    # convenience ----------------------------------------------------------
    def to_networkx(self) -> nx.MultiDiGraph:
        return self._g


@dataclass
class RawTraceItem:
    start_state: Any  # placeholder for concrete browser state snapshot
    action: Any  # placeholder for concrete action object (Playwright)
    end_state: Any


@dataclass
class AppKnowledge:
    """Container that holds the entire exploration knowledge for an app."""

    raw_trace: List[RawTraceItem] = field(default_factory=list)
    abstract_states: Dict[str, AbstractState] = field(default_factory=dict)
    abstract_actions: Dict[str, AbstractAction] = field(default_factory=dict)
    aig: AbstractInteractionGraph = field(default_factory=AbstractInteractionGraph)
    # Maintain a fast index of unexplored actions for quick lookup / termination checks
    unexplored_action_ids: set[str] = field(default_factory=set, repr=False)

    # --- CRUD helpers -----------------------------------------------------
    def get_or_create_state(self, state_signature: str) -> AbstractState:
        # naive method using signature as hash
        for st in self.abstract_states.values():
            if st.repr_signature == state_signature:
                return st
        # create new
        new_state = AbstractState(repr_signature=state_signature)
        self.abstract_states[new_state.state_id] = new_state
        self.aig.add_state(new_state)
        return new_state

    def add_raw_trace_item(self, start_state: Any, action: Any, end_state: Any) -> None:
        self.raw_trace.append(RawTraceItem(start_state, action, end_state))

    # ------------------------------------------------------------------
    # fast-access helpers ------------------------------------------------

    def register_action(self, action: AbstractAction) -> None:
        """Insert new action into global dict and unexplored index."""
        self.abstract_actions[action.action_id] = action
        if action.exploration_flag == ExplorationFlag.UNEXPLORED:
            self.unexplored_action_ids.add(action.action_id)

    def update_action_flag(self, action: AbstractAction, new_flag: ExplorationFlag) -> None:
        prev_flag = action.exploration_flag
        action.exploration_flag = new_flag
        if prev_flag == ExplorationFlag.UNEXPLORED and new_flag != ExplorationFlag.UNEXPLORED:
            self.unexplored_action_ids.discard(action.action_id)
        if prev_flag != ExplorationFlag.UNEXPLORED and new_flag == ExplorationFlag.UNEXPLORED:
            self.unexplored_action_ids.add(action.action_id)

    # ------------------------------------------------------------------
    # persistence -------------------------------------------------------

    def to_json(self) -> Dict[str, Any]:
        """Serialize knowledge into a JSON-serialisable structure."""
        import json, base64
        # For brevity we only store meta – raw_trace is base64-encoded json for size reasons
        return {
            "abstract_states": {
                sid: {
                    "repr_signature": st.repr_signature,
                    "actions": list(st.actions.keys()),
                    "page_desc": st.page_description,
                    "element_groups": st.element_groups,
                }
                for sid, st in self.abstract_states.items()
            },
            "abstract_actions": {
                aid: {
                    "action_type": a.action_type.value,
                    "flag": a.exploration_flag.value,
                    "src": a.source_abs_state.state_id if a.source_abs_state else None,
                    "dst": a.target_abs_state.state_id if a.target_abs_state else None,
                    "elements": [e.node_id for e in a.actual_elements],
                    "function": a.function_desc,
                }
                for aid, a in self.abstract_actions.items()
            },
            "edges": [
                (u, v, k)
                for u, v, k in self.aig.to_networkx().edges(keys=True)
            ],
            "unexplored": list(self.unexplored_action_ids),
            "raw_trace": base64.b64encode(json.dumps([rt.__dict__ for rt in self.raw_trace]).encode()).decode(),
        }

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> "AppKnowledge":
        import json, base64
        K = cls()
        # rebuild states
        for sid, meta in data["abstract_states"].items():
            st = AbstractState(
                state_id=sid,
                repr_signature=meta["repr_signature"],
                page_description=meta.get("page_desc", ""),
                element_groups=meta.get("element_groups", []),
            )
            K.abstract_states[sid] = st
        # rebuild actions
        for aid, meta in data["abstract_actions"].items():
            a = AbstractAction(
                action_id=aid,
                action_type=ActionType(meta["action_type"]),
                exploration_flag=ExplorationFlag(meta["flag"]),
                function_desc=meta["function"],
            )
            a.actual_elements = [UIElement(node_id=eid, description="") for eid in meta["elements"]]
            K.abstract_actions[aid] = a
        # link states & actions, rebuild edges
        for u, v, k in data["edges"]:
            src = K.abstract_states[u]
            dst = K.abstract_states[v]
            act = K.abstract_actions[k]
            src.actions[k] = act
            K.aig.add_edge(src, act, dst)
        # unexplored set
        K.unexplored_action_ids = set(data.get("unexplored", []))
        # raw trace
        rt_bytes = base64.b64decode(data["raw_trace"])
        rt_list = json.loads(rt_bytes.decode())
        from dataclasses import asdict
        for item in rt_list:
            K.raw_trace.append(RawTraceItem(**item))
        return K 
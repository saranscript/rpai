from __future__ import annotations

"""Algorithm 1 – Knowledge Update implementation for Web-Explorer."""

from typing import Any, List
from .knowledge import (
    AppKnowledge,
    AbstractState,
    AbstractAction,
    ExplorationFlag,
    ActionType,
    UIElement,
)
from .state_matcher import StateMatcher
from .element_grouper import ElementGrouper  # will create stub later
import json


class KnowledgeMaintainer:
    """Encapsulates the logic for maintaining exploration knowledge."""

    def __init__(self, state_matcher: StateMatcher | None = None) -> None:
        self._state_matcher = state_matcher or StateMatcher()
        self._grouper = ElementGrouper()

    # ------------------------------------------------------------------
    def update_knowledge(
        self,
        K: AppKnowledge,
        prev_state_snapshot: Any | None,
        prev_action_concrete: Any | None,
        new_state_snapshot: Any,
    ) -> AppKnowledge:
        """Update in-memory knowledge based on new step.

        Mirrors Algorithm 1 in the paper.
        """

        # 1. Append to raw trace -------------------------------------------------
        K.add_raw_trace_item(prev_state_snapshot, prev_action_concrete, new_state_snapshot)

        # 2. Update/merge abstract states ---------------------------------------
        new_state_sig = self._state_matcher.signature(new_state_snapshot)
        new_abs_state: AbstractState = self._state_matcher.match_state(K, new_state_snapshot)
        if new_abs_state is None:
            new_abs_state = K.get_or_create_state(new_state_sig)
            new_abs_state.concrete_states.append(new_state_snapshot)
            # Save LLM-organised knowledge if available
            if isinstance(new_state_snapshot, dict):
                new_abs_state.page_description = new_state_snapshot.get("page_description", "")
                new_abs_state.element_groups = new_state_snapshot.get("element_groups", [])
        else:
            # Add snapshot to cluster for future refinement
            new_abs_state.concrete_states.append(new_state_snapshot)
            # update page description if not set yet and snapshot has it
            if not new_abs_state.page_description and isinstance(new_state_snapshot, dict):
                new_abs_state.page_description = new_state_snapshot.get("page_description", "")
            # merge element groups (union) if any
            if isinstance(new_state_snapshot, dict):
                egroups = new_state_snapshot.get("element_groups", [])
                if egroups:
                    seen_str = {json.dumps(d, sort_keys=True) for d in new_abs_state.element_groups}
                    for g in egroups:
                        if json.dumps(g, sort_keys=True) not in seen_str:
                            new_abs_state.element_groups.append(g)

        # 3. Process new actions observed in the *current* state  --------------
        #    For the web setting we rely on ElementGrouper to group similar
        #    interactive elements together into abstract actions.
        # Use cached grouped actions if available in snapshot
        if isinstance(new_state_snapshot, dict) and "grouped_actions" in new_state_snapshot:
            candidate_ui_actions = new_state_snapshot["grouped_actions"]
        else:
            candidate_ui_actions = self._grouper.extract_actions(new_state_snapshot)
            if isinstance(candidate_ui_actions, tuple):
                candidate_ui_actions = candidate_ui_actions[0]
        for concrete_action in candidate_ui_actions:
            if self._action_matches_existing(K, concrete_action):
                continue
            abs_action = self._create_abstract_action(concrete_action)
            abs_action.source_abs_state = new_abs_state
            K.register_action(abs_action)
            new_abs_state.actions[abs_action.action_id] = abs_action
            abs_action.exploration_flag = ExplorationFlag.UNEXPLORED
            # Debug - log action registration
            elements_str = ','.join([e.node_id for e in abs_action.actual_elements])
            print(f"Registered new action: {abs_action.action_id} ({abs_action.action_type}) with {len(abs_action.actual_elements)} elements: {elements_str[:50]}...")

        # 4. Update prev_action flag + graph ------------------------------------
        if prev_state_snapshot is not None and prev_action_concrete is not None:
            prev_abs_state = self._state_matcher.match_state(K, prev_state_snapshot)
            if prev_abs_state:
                matched_abs_action = self._match_abstract_action(K, prev_action_concrete)
                if matched_abs_action:
                    # Set explored flag
                    K.update_action_flag(matched_abs_action, ExplorationFlag.EXPLORED)
                    # Mark ineffective if state didn't change
                    if prev_abs_state == new_abs_state:
                        K.update_action_flag(matched_abs_action, ExplorationFlag.INEFFECTIVE)
                    # Update graph edge if not ineffective
                    if matched_abs_action.exploration_flag != ExplorationFlag.INEFFECTIVE:
                        K.aig.add_edge(prev_abs_state, matched_abs_action, new_abs_state)
                    else:
                        # ineffective – prune edge if exists
                        try:
                            K.aig.to_networkx().remove_edge(
                                prev_abs_state.state_id,
                                new_abs_state.state_id,
                                key=matched_abs_action.action_id,
                            )
                        except Exception:
                            pass

        return K

    # ------------------------------------------------------------------
    # helper utils ------------------------------------------------------

    def _action_matches_existing(self, K: AppKnowledge, concrete_action: Any) -> bool:
        """Heuristic: compare element identifier & type against existing actions."""
        target_func = concrete_action.get("function", "").strip().lower()
        elem_id = str(concrete_action["element_id"])

        for a in K.abstract_actions.values():
            if a.action_type.value != concrete_action["action_type"]:
                continue

            # 1) Exact element id match
            if any(elem.node_id == elem_id for elem in a.actual_elements):
                return True

            # 2) Same function description (LLM grouping)
            if target_func and a.function_desc.strip().lower() == target_func:
                # merge this concrete element into the existing abstract action
                a.actual_elements.append(UIElement(node_id=elem_id, description=""))
                return True

            # NEW: 1b) XPath match across dynamic ids
            if concrete_action.get("xpath") and any(elem.description == concrete_action.get("xpath") for elem in a.actual_elements):
                # Also merge the new dynamic id for completeness
                a.actual_elements.append(UIElement(node_id=elem_id, description=concrete_action.get("xpath", "")))
                return True
        return False

    def _create_abstract_action(self, concrete_action: Any) -> AbstractAction:
        elem_id = str(concrete_action["element_id"])
        elem = UIElement(node_id=elem_id, description=concrete_action.get("xpath", ""))
        elems: list[UIElement] = [elem]
        for eid in concrete_action.get("elements", [])[1:]:  # skip first as already added
            elems.append(UIElement(node_id=str(eid), description=""))
        aa = AbstractAction(
            action_type=ActionType(concrete_action["action_type"]),
            actual_elements=elems,
            function_desc=concrete_action.get("function", ""),
        )
        return aa

    def _match_abstract_action(self, K: AppKnowledge, concrete_action: Any) -> AbstractAction | None:
        for a in K.abstract_actions.values():
            if a.action_type.value == concrete_action["action_type"]:
                elem_id = str(concrete_action["element_id"])
                if any(elem.node_id == elem_id for elem in a.actual_elements):
                    return a
        return None 
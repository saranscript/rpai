from __future__ import annotations

"""App-wide target action selector (Section 3.3.2)."""

import random
from typing import List
from .knowledge import AppKnowledge, AbstractAction, ExplorationFlag


class ActionSelector:
    """Random but app-wide selector that prefers unexplored actions in the current state."""

    def __init__(self) -> None:
        pass

    def select_action(
        self, K: AppKnowledge, current_state_id: str | None
    ) -> AbstractAction | None:
        """Return an `AbstractAction` to execute next.

        1. If there are unexplored actions in *current_state*, pick one randomly.
        2. Else, consider unexplored actions across *all* states and pick randomly.
        """
        if current_state_id and current_state_id in K.abstract_states:
            st = K.abstract_states[current_state_id]
            candidates: List[AbstractAction] = [
                a for a in st.actions.values() if a.exploration_flag == ExplorationFlag.UNEXPLORED
            ]
            if candidates:
                candidates.sort(key=lambda a: a.action_id)
                return candidates[0]

        # fallback: global unexplored
        global_candidates: List[AbstractAction] = [
            a for a in K.abstract_actions.values() if a.exploration_flag == ExplorationFlag.UNEXPLORED
        ]
        if global_candidates:
            global_candidates.sort(key=lambda a: a.action_id)
            return global_candidates[0]
        return None 
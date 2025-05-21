from __future__ import annotations

"""Fault-tolerant navigation path finder (Section 3.3.3)."""

from typing import List
from .knowledge import AppKnowledge, AbstractAction, AbstractState, ExplorationFlag
import networkx as nx


class PathFinder:
    def __init__(self, max_retry: int = 3) -> None:
        self.max_retry = max_retry

    def find_path(
        self, K: AppKnowledge, current_state: AbstractState, target_action: AbstractAction
    ) -> List[AbstractAction]:
        """Return an ordered list of *navigation* actions leading to state where `target_action` is available.
        If no path exists, returns empty list.
        """
        target_state = target_action.source_abs_state
        if target_state is None:
            return []
        for attempt in range(self.max_retry):
            path = K.aig.shortest_path(current_state, target_state)
            if path:
                return path
            # No path – maybe graph outdated, widen search by removing ineffective edges and retry
            self._prune_ineffective_edges(K)
            # As a fallback, do a BFS ignoring edge directions (undirected) to find any connection
            bfs_path = self._bfs_any_path(K, current_state, target_state)
            if bfs_path:
                return bfs_path
        return []

    def _prune_ineffective_edges(self, K: AppKnowledge) -> None:
        g = K.aig.to_networkx()
        to_remove = []
        for u, v, k, data in g.edges(keys=True, data=True):
            act: AbstractAction = data["obj"]
            if act.exploration_flag == ExplorationFlag.INEFFECTIVE:
                to_remove.append((u, v, k))
        for u, v, k in to_remove:
            g.remove_edge(u, v, key=k)

    # ------------------------------------------------------------------
    def _bfs_any_path(self, K: AppKnowledge, src: AbstractState, dst: AbstractState) -> List[AbstractAction]:
        """Breadth-first search over the *undirected* view of the AIG as last-chance fallback."""
        g_undir = K.aig.to_networkx().to_undirected(as_view=True)
        try:
            nodes_path = nx.shortest_path(g_undir, src.state_id, dst.state_id)
            actions: List[AbstractAction] = []
            for i in range(len(nodes_path) - 1):
                # choose first available action along the multi-edge set (direction disregarded)
                multiedges = K.aig.to_networkx().get_edge_data(nodes_path[i], nodes_path[i + 1])
                if not multiedges:
                    multiedges = K.aig.to_networkx().get_edge_data(nodes_path[i + 1], nodes_path[i])
                if multiedges:
                    first_key = list(multiedges.keys())[0]
                    actions.append(multiedges[first_key]["obj"])
            return actions
        except Exception:
            return []

    def path_to_state(
        self, K: AppKnowledge, src_state: AbstractState, dst_state: AbstractState
    ) -> List[AbstractAction]:
        """Return navigation actions from src_state to dst_state using current AIG."""
        if src_state == dst_state:
            return []
        return K.aig.shortest_path(src_state, dst_state)

    # Additional fault tolerance such as retries / alternative paths can be built
    # on top of this basic shortest path logic. 
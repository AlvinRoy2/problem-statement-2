import networkx as nx
from typing import Optional, Dict
from core.state import state

# Cache the base graph to prevent rebuilding it on every single request
_BASE_GRAPH = None

def get_dynamic_graph() -> nx.Graph:
    global _BASE_GRAPH
    if _BASE_GRAPH is None:
        _BASE_GRAPH = nx.Graph()
        zones = list(state.zones.keys())
        if not zones:
            return nx.Graph()
            
        # Build a "Star" topology connecting everything to a central invisible Concourse
        hub = "Concourse"
        for z in zones:
            if z != hub:
                _BASE_GRAPH.add_edge(hub, z, distance=50, has_stairs=(True if "Stairs" in z else False))
    return _BASE_GRAPH.copy()

# SK-03 & SK-08: Indoor Routing & Accessibility Mode
def compute_route(start: str, end: str, accessible_only: bool, dynamic_densities: Dict[str, float]) -> Optional[list[str]]:
    """
    Computes shortest path based on capacity constraints and accessibility.
    """
    graph = get_dynamic_graph()
    if not graph.nodes:
        return None
        
    # Prune highly congested edges automatically
    for edge in list(graph.edges):
        z1, z2 = edge[0], edge[1]
        if max(dynamic_densities.get(z1, 0.0), dynamic_densities.get(z2, 0.0)) > 0.8:
            if graph.has_edge(*edge):
                graph.remove_edge(*edge)
            
    # Apply delay penalty for inaccessible edges (Accessibility Refactor)
    if accessible_only:
        for u, v, attrs in list(graph.edges(data=True)):
            if attrs.get('has_stairs', False):
                # Apply a significant distance penalty to stairs instead of outright deleting them
                # Allows the pathfinder to still use it as an absolute last resort
                graph[u][v]['distance'] += 9999 
                
    try:
        # Security: Graceful catch for unknown/missing nodes to avoid uncaught crashes
        if not graph.has_node(start) or not graph.has_node(end):
            return None
        return nx.shortest_path(graph, source=start, target=end, weight='distance')
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None

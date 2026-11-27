from collections import Counter
from itertools import combinations, permutations

from scripts.srs_protocol import SlottedProtocol


def test_last_three_pivots_determine_the_full_service_set():
    nodes = tuple(range(5))
    edges = ((0, 1), (1, 2), (2, 3), (3, 4), (0, 4))
    sim = SlottedProtocol(edges, 2, policy="pressure_pre_drop", seed=52,
                          cutoff=3, max_length=4)
    opportunities = Counter()
    for tick, order in enumerate(permutations(nodes)):
        sim.backend.inventory.nodes = order
        # Alternate the edge order and mix requests with idle slots.
        edge_order = edges if tick % 2 else reversed(edges)
        demand = [(0, 2), (1, 3)] if tick % 3 == 0 else []
        consumed = sim.step(tick, {e: True for e in edge_order}, demand)
        live = sim.backend.inventory.pairs.values()
        produced = [item.endpoints for item in live] + [pair for pair, _ in consumed]
        triangle = sorted(combinations(sorted(order[-3:]), 2))
        assert sorted(produced) == triangle
        opportunities.update(triangle)
    # Each demand pair appears in 3 of the 10 possible final triangles.
    assert set(opportunities.values()) == {36}

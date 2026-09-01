#!/usr/bin/env python3
"""Node placement for the scaling benchmark.

Servers from the front of one seeded permutation, clients from the back, so
changing either count never moves the other's nodes. measure_one calls
select_nodes and does the wiring itself.
"""

import random


def select_nodes(local_nodes, num_servers, num_clients, seed):
    """Return (perm[:num_servers], perm[-num_clients:]) from one seeded
    shuffle of the pool.

    local_nodes is a list of distinct items; the function only shuffles
    and slices it, never looks at the items themselves. The same
    (pool, seed) always gives the same placement. The two sets overlap
    once num_servers + num_clients exceeds the pool size, so check
    capacity before calling.
    """
    rng = random.Random(seed)
    perm = rng.sample(local_nodes, len(local_nodes))
    return perm[:num_servers], perm[-num_clients:]

"""Round-robin phase accumulation across weeks.

Every week occupies ``grid_size`` cells in the global round-robin stream,
skipped weeks included. A week's recorded start phase is the sum of the grid
sizes of all preceding weeks, so a skipped week shifts every later week
exactly as if it had been generated.
"""


def recorded_phase(preceding_grid_sizes) -> int:
    """Sum cells consumed by preceding weeks; NULL grid sizes count as zero."""
    return sum(s for s in preceding_grid_sizes if s is not None)

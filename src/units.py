# Time units for the simulator.
#
# The simpy clock has no unit of its own; this project declares it to be
# MILLISECONDS. Every value that enters the clock -- link propagation delays,
# transmission times, arrival draws, session service times, run bounds --
# must therefore be in ms.
#
# Two conventions keep that true:
#   * Engine constants that enter the clock are DEFINED in ms
#     (Graph.default_propagation_delay = 1000, LINKRATE in bits per ms, ...).
#   * Human-interface knobs (CLI/config: until, TAU/arrival mean, session
#     mean, GRAPH_DELAY, prop_delay) declare SECONDS and cross the boundary
#     exactly once through s_to_ms(). Never write a bare *1000.

MS_PER_S = 1000


def s_to_ms(seconds):
    """Convert a seconds-valued human-interface knob to clock milliseconds."""
    return seconds * MS_PER_S

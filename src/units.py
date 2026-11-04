# Time units for the simulator.
#
# The simpy clock has no unit of its own; this project declares it to be
# MILLISECONDS. Every simulation time value is in ms, including engine
# constants, user-facing configuration, CLI/environment overrides, and logs.
# No conversion is needed when a configuration value enters the clock.
#
# External wall-clock APIs such as subprocess timeouts still require seconds.
# Convert exactly once at those boundaries with ms_to_s(). Convert their
# seconds-valued measurements to user-facing ms with s_to_ms().

MS_PER_S = 1000


def s_to_ms(seconds):
    """Convert an external seconds-valued duration to milliseconds."""
    return seconds * MS_PER_S


def ms_to_s(milliseconds):
    """Convert milliseconds to seconds for an external wall-clock API."""
    return milliseconds / MS_PER_S

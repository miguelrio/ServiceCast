# MetricUtility -- step 2 of the utility pipeline:
# map each raw metric of a replica into a metric utility,
# in range 0 (useless) -> 1 (the best it can be).
#
# This module holds the library of mapping techniques and the choice of
# which one is used for each metric.  It knows nothing about how the
# metric utilities are later combined -- see Utility.py.

import math


# Check a utility is in its defined range: 0 (useless) -> 1 (best).
def check_in_range(value, what):
    if value < 0 or value > 1:
        raise ValueError("{} = {} -- not in range 0 -> 1".format(what, value))
    return value


# ---------------------------------------------------------------------------
# The mapping functions.
#
# They all agree at the two ends -- a raw value of 0 gives a metric utility
# of 1, and a raw value of 'scale' gives 0 -- and differ only in the shape
# between.  That shape is the modelling choice: it says how much a change in
# the raw metric is worth.
#
# Add more here as they are needed.
# ---------------------------------------------------------------------------

#  Linear
def linear(value, scale):
    return 1 - value / scale


#   Logarithmic -- written and ready, but not used by any experiment yet.
#    See metric_utility_fn below for the line that switches it on.
def logarithmic(value, scale, k=9.0):
    return 1 - math.log(1 + k * (value / scale)) / math.log(1 + k)


#    Sigmoid -- NOT IMPLEMENTED YET.
def sigmoid(value, scale):
    raise NotImplementedError("MetricUtility.sigmoid: not implemented yet")


class MetricUtility:
    # The following can be reset from the outside
    # to change the behaviour of the algorithms

    # one metric utility function per metric name

    metric_utility_fn = {}
    metric_utility_fn['load'] = linear
    metric_utility_fn['delay'] = linear

    # To use a different metric utility function, point the metric at another function,
    # either here or from an experiment's topology_setup().  For example,
    # to make delay fall off logarithmically rather than in a straight line:
    #
    # metric_utility_fn['delay'] = logarithmic

    # the raw value at which each metric is at its worst
    metric_scale = {}
    metric_scale['load'] = 1.0     # a server with every slot used
    metric_scale['delay'] = None   # no value yet: set to the network diameter
                                   # by Network.calculate_forwarding_tables()

    # Map the raw metrics into metric utilities, each in range 0 -> 1.
    # 'metrics' is a dict of raw values keyed by metric name: a RIB entry at
    # the Router, or a Server's live payload at the Network.  Either way, a
    # key with no metric utility function takes no part in the utility --
    # though it may well be used elsewhere, as 'replica' and 'neighbour' are.
    @classmethod
    def evaluate(cls, metrics):
        """Map each raw metric into a metric utility in range 0 -> 1"""
        return { name: check_in_range(fn(metrics[name], cls.metric_scale[name]),
                                      "MetricUtility: metric utility for '" + name + "'")
                 for name, fn in cls.metric_utility_fn.items() }

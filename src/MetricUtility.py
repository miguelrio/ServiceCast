# MetricUtility -- step 2 of the utility pipeline:
# map each raw metric of a replica into a metric utility,
# in range 0 (useless) -> 1 (the best it can be).
#
# This module holds the library of mapping techniques and the choice of
# which one is used for each metric.  It knows nothing about how the
# metric utilities are later combined -- see Utility.py.


# Check a utility is in its defined range: 0 (useless) -> 1 (best).
def check_in_range(value, what):
    if value < 0 or value > 1:
        raise ValueError("{} = {} -- not in range 0 -> 1".format(what, value))
    return value


# A metric utility function takes the raw value and that metric's 'scale' --
# the raw value at which the metric is at its worst: a server with every
# slot used (load), or the network diameter (delay).
# More mapping techniques can be added here as they are needed.
def lower_is_better(value, scale):
    """The metric utility of a metric that is best at 0 and worst at 'scale'"""
    return 1 - value / scale


class MetricUtility:
    # The following can be reset from the outside
    # to change the behaviour of the algorithms

    # one metric utility function per metric name
    # plain functions, not staticmethods -- a dict lookup is not a descriptor lookup
    metric_utility_fn = {}
    metric_utility_fn['load'] = lower_is_better
    metric_utility_fn['delay'] = lower_is_better

    # the raw value at which each metric is at its worst
    metric_scale = {}
    metric_scale['load'] = 1.0     # a server with every slot used
    metric_scale['delay'] = 1.0    # set to the network diameter by Network

    # Map the raw metrics into metric utilities, each in range 0 -> 1.
    # 'metrics' is a dict of raw values keyed by metric name -- typically a
    # RIB entry; any key without a metric utility function is ignored.
    @classmethod
    def evaluate(cls, metrics):
        """Map each raw metric into a metric utility in range 0 -> 1"""
        return { name: check_in_range(fn(metrics[name], cls.metric_scale[name]),
                                      "MetricUtility: metric utility for '" + name + "'")
                 for name, fn in cls.metric_utility_fn.items() }

# Utility -- the utility of a replica, as a 3 step pipeline
#
#   1. gather the raw metrics of a replica            (load, delay, ...)
#      -- done by Server / Router / Network
#   2. map each raw metric -> a metric utility        0 (useless) -> 1 (best)
#      -- done by MetricUtility
#   3. combine the metric utilities -> user utility   0 (useless) -> 1 (best)
#      -- done here
#
# An experiment can replace the user utility function here, or any metric
# utility function in MetricUtility, without touching the simulator.

from MetricUtility import MetricUtility, check_in_range


# Step 3 -- a user utility function: metric utilities -> the utility for the user
def user_utility1(alpha, metric_utility):
    """The weighted mean of the load and delay metric utilities"""
    return alpha * metric_utility['load'] + (1 - alpha) * metric_utility['delay']


class Utility:
    # The following can be reset from the outside
    # to change the behaviour of the algorithms

    # combine the metric utilities into the utility for the user
    user_utility_fn = staticmethod(user_utility1)


    # The following variables can be reassigned from the outside

    # alpha -- the weight of 'load' against 'delay' in user_utility1
    alpha = 0.5


    # Run the pipeline: raw metrics -> metric utilities -> user utility
    @classmethod
    def eval_forwarding_utility(cls, metrics):
        """The forwarding utility of a replica, in range 0 -> 1"""
        metric_utility = MetricUtility.evaluate(metrics)
        return check_in_range(cls.user_utility_fn(cls.alpha, metric_utility),
                              "Utility: user utility")

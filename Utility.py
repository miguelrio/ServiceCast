

# the first forwarding utility function
# load should be normalised in range 0 -> 1
# delay should be normalised in range 0 -> 1
def forwarding_utility1(alpha, load, delay):
    """ the utility function U=1/(1 + alpha*load + (1-alpha)*delay) """
    # we define the utility function U=1/(1 + alpha*load + (1-alpha)*delay)
    # so that 0 is the worst and 1 is the best, always in range (0, 1]
    return 1 - ( alpha * load + (1-alpha) * delay)
    

class Utility:
    # The following staticmethods can be reset from the outside
    # to change the behaviour of the algorithms

    # forwarding_utility
    forwarding_utility_fn = staticmethod(forwarding_utility1)

    # should we use the normalised delay value
    # or the actual delay value
    use_normalised_delay = True


    # The following variables can be reassigned from the outside

    # alpha
    alpha = 0.5

    # Ensure Utility value is in range 0 -> 1
    @classmethod
    def eval_forwarding_utility(cls, alpha, load, delay, normalised_delay = 0):

        if cls.use_normalised_delay:
            # we will use the normalised_delay value for the forwarding_utility
            
            if (load < 0 or load > 1):
                raise ValueError("Utility: using use_normalised_delay -- load has not been normalised in range 0 -> 1")

            if (normalised_delay < 0 or normalised_delay > 1):
                raise ValueError("Utility: using use_normalised_delay -- delay has not been normalised in range 0 -> 1")

            value = cls.forwarding_utility_fn(alpha, load, normalised_delay)

        else:
            # we will use the delay value for the forwarding_utility
            
            if (load < 0 or load > 1):
                raise ValueError("Utility: using delay -- load has not been normalised in range 0 -> 1")

            if (delay < 0):
                raise ValueError("Utility: using delay -- delay < 0")

            value = cls.forwarding_utility_fn(alpha, load, delay)

            
        # print("eval_forwarding_utility = {} for alpha {} load {} delay_utility {}".format(value, alpha, load, delay))

        # check return value is in range 0 -> 1

        if value < 0:
            return 0
        elif value > 1:
            return 1
        else:
            return value

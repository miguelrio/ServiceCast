

# the first forwarding utility function
def forwarding_utility1(alpha, load, delay):
    """ the utility function U=1/(1 + alpha*load + (1-alpha)*delay) """
    # we define the utility function U=1/(1 + alpha*load + (1-alpha)*delay)
    # so that 0 is the worst and 1 is the best, always in range (0, 1]
    return 1 / (1 + alpha * load + (1-alpha) * delay) 
    

class Utility:
    # The following staticmethods can be reset from the outside
    # to change the behaviour of the algorithms

    # forwarding_utility
    forwarding_utility_fn = staticmethod(forwarding_utility1)

    
    # The following variables can be reassigned from the outside

    # alpha
    alpha = 0.5

    # Ensure Utility value is in range 0 -> 1
    @classmethod
    def eval_forwarding_utility(cls, alpha, load, delay):
        value = cls.forwarding_utility_fn(alpha, load, delay)

        # print("eval_forwarding_utility = {} for alpha {} load {} delay_utility {}".format(value, alpha, load, delay))

        if value < 0:
            return 0
        elif value > 1:
            return 1
        else:
            return value

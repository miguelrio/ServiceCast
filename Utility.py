

# the first forwarding utility function
def forwarding_utility1(alpha, load, delay):
    """ the utility function U=alpha * load + (1-alpha)*delay """
    # we define the utility function U=alpha * load + (1-alpha)*delay
    return alpha * load + (1-alpha) * delay 
    

class Utility:
    # The following staticmethods can be reset from the outside
    # to change the behaviour of the algorithms

    # forwarding_utility
    forwarding_utility_fn = staticmethod(forwarding_utility1)

    
    # The following variables can be reassigned from the outside

    # alpha
    alpha = 0


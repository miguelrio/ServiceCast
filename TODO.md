# Bugs

Fixed issue when there are no more slots in the whole system.


# Issues

#### Client Request Forwarding

Currently we have hop-by-hop forwarding,
so each Router will check which is the best for the service name.

An alternative is to change the service name to an address
at the first Router.

#### Load values

Load values are not in range 0 -> 1.
Currently based on slot.

#### Utility function value DONE

The Utility function has been changed so that:
- 0 is the worst value
- 1 is the best value
- Output is always in range (0, 1]

Changes made:
- `Utility.py`: Changed `forwarding_utility1` to return `1 / (1 + alpha * load + (1-alpha) * delay)`
- `Router.py`: Changed comparison from `<` to `>`, initial `best_utility` from `-inf` to `-1`, and added initialization of `best_neighbour` and `servicename`
- `Network.py`: Added `reverse=True` to sort for maximum utility
- `main_ls_lc.py`, `main_sm_cm.py`, `main.py`: Updated custom utility functions
- `Variables.md`: Updated documentation examples


#### Announcement Radius

Still to be refined.
Draft formula not correct.

####  Server metrics update

Servers should have load_utilty in range 0 -> 1.
We can divide load by total slots 

Adjust load_up_fn and load_down_fn to be slots_up_fn and slots_down_fn

Make load derived from slots.



# TODO


# Experiments


## 2021

1 - Generate demand
  we will have two windows, one for sampling the demand (ground truth) and one for sending the updates
Updates can be sent:
  - synchronously (every fixed interval): interval
  - asynchronously (after a threshold crossing, compared with the last value sent): threshold
  - combination of both
2 - fix hardcoding of individual router2s
  - e.g. some kind of adjacency list
        constructs the routers on the fly
        creates links on the fly
3 - write forwarding algorithm
4 - put metrics in packets

have load generater (LG) of load from a normal distribution
  - configured with a mean and a stddev
have another distribution that can update the mean of LG
  - this can be poisson, always up, always down,
  - from a time-series, or other we device
  - have a knob to adjust stddev in LG so that that range of values will be closer to mean or further away

# Algorithm

1  LOAD TOPOLOGY
2  ALLOCATE REPLICAS
3  ALLOCATE CLIENTS
4  REPLICAS SEND LOAD
5  LOAD GETS PROPAGATED
6  FORWARDING TABLE UPDATED
7  GENERATE DEMANDS - INCLUDING DURATION
8  REQUESTS GET PROPAGATED TOWARDS REPLICA
9  REPLICAS UPDATE INTERNAL LOAD INFO
10 REPLICAS SEND UPDATES
11 LOAD UPDATES GET PROPAGATED
12 ROUTERS UPDATE FORWARDING TABLE


# Network topologies

Potential networks to look at from topology zoo

- abilene
- BICS
- BT Europe
- Cogent
- Colt Telecom
- GEANT

WorldWide
- AboveNet
- Cogent
- Deutsche Telecom *
- EasyNet
- Hibernia Atlantic
- Hostway International
- Hurricane Electric
- Internode
- NTT *
- Tinet *

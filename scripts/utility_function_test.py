from MetricUtility import MetricUtility, linear, logarithmic, sigmoid
from Utility import Utility
import numpy as np
import matplotlib.pyplot as plt

# Use a topology from an adjacency list
def test_utility():

    Utility.alpha = 0.5

    # Define metric scale

    # Load is already normalised in the range 0-1, so setting it to 1 here is not strictly needed. The line can be commented out. But change the value if you want anythihg other than 1.
    MetricUtility.metric_scale['load'] = 1

    # In full simulation runs the default delay scale is set to the network diameter (the maximum of the sum of delays along all network paths). It is determined from the network topology configured for the simulator run. Set it manually to a suitable value here.
    MetricUtility.metric_scale['delay'] = 0.01

    # Define netric utility functions

    # MetricUtility.metric_utility_fn['load'] = lambda load, scale: (1-(0.12*(load/scale))) if (load/scale) < 0.8  else (4.5-(4.5*(load/scale)))
    # MetricUtility.metric_utility_fn['load'] = lambda load, scale: (1-(load/scale))
    # MetricUtility.metric_utility_fn['load'] = lambda value, scale: (logarithmic(value, scale, k=25) if (load / scale) < 0.75 else 0)
    # MetricUtility.metric_utility_fn['load'] = logarithmic
    # MetricUtility.metric_utility_fn['load'] = linear
    MetricUtility.metric_utility_fn['load'] = lambda value, scale: (1 / (1 + (((load/scale) * (1 - 0.75)) / (0.75 * (1.00001 - (load/scale)))) ** 5))

    # MetricUtility.metric_utility_fn['delay'] = lambda delay, scale: (1-(0.1*(delay/scale))) if delay/scale <= 10 else 0
    # MetricUtility.metric_utility_fn['delay'] = lambda delay, scale: (1 if delay/scale <= 3/8 else 0)
    # MetricUtility.metric_utility_fn['delay'] = lambda delay, scale: (1 - delay / scale)
    # MetricUtility.metric_utility_fn['delay'] = linear
    # MetricUtility.metric_utility_fn['delay'] = lambda delay, scale: ((1 - delay/scale) if delay/scale <= 5/8 else 0)
    MetricUtility.metric_utility_fn['delay'] = lambda value, scale: (logarithmic(value, scale, k=25))
    # MetricUtility.metric_utility_fn['delay'] = lambda delay, scale: (1 / (1 + (((delay/scale) * (1 - 0.33)) / (0.33 * (1.00001 - (delay/scale)))) ** 5))
    # MetricUtility.metric_utility_fn['delay'] = lambda value, scale: (1 / (1 + (((value/scale) * (1 - 0.33)) / (0.33 * (1.00001 - (value/scale)))) ** 5))
    # MetricUtility.metric_utility_fn['delay'] = lambda value, scale: (logarithmic(value, scale, k=10) if value/scale < 0.75 else 0)


    # Define the user_utility function here
    # Simple arithmetic mean:
    # Utility.user_utility_fn = staticmethod(lambda alpha, metric_utility: round(metric_utility['load'] * alpha + metric_utility['delay'] * (1 - alpha), 4))
    # Simple geometric mean:
    Utility.user_utility_fn = staticmethod(lambda alpha, metric_utility: round(metric_utility['load'] ** alpha * metric_utility['delay'] ** (1 - alpha), 4))
    # Simple minimum:
    # Utility.user_utility_fn = staticmethod(lambda alpha, metric_utility: np.minimum(metric_utility['load'], metric_utility['delay']))
    # Utility.user_utility_fn = staticmethod(lambda alpha, metric_utility: 0)

    delay_scale = MetricUtility.metric_scale['delay']
    load_scale = MetricUtility.metric_scale['load']
    print("delay scale: " + str(delay_scale) + ", load scale: " + str(load_scale))
    for load_fraction in [0.0, 0.25, 0.5, 0.75, 1.0]:
      for delay_fraction in [0.0, 0.25, 0.5, 0.75, 1.0]:
        load = load_fraction * load_scale
        delay = delay_fraction * delay_scale
        metrics = {'load': load, 'delay': delay}
        metric_utility = MetricUtility.evaluate(metrics)
        user_utility = Utility.eval_forwarding_utility(metrics)
        print(
            f"raw={metrics}  "
            f"metric_utility={metric_utility}  "
            f"user_utility={user_utility}"
        )

    load_fractions = np.linspace(0.0, 1.0, 101)
    delay_fractions = np.linspace(0.0, 1.0, 101)

    load_values = load_fractions * load_scale
    delay_values = delay_fractions * delay_scale

    load_grid, delay_grid = np.meshgrid(load_values, delay_values)
    utility_grid = np.empty_like(load_grid)

    for row, delay in enumerate(delay_values):
        for column, load in enumerate(load_values):
            metrics = {'load': load, 'delay': delay}
            utility_grid[row, column] = Utility.eval_forwarding_utility(metrics)

    figure = plt.figure(figsize=(10, 7))
    axis = figure.add_subplot(111, projection='3d')

    surface = axis.plot_surface(
        load_grid,
        delay_grid,
        utility_grid,
        cmap='viridis',
        edgecolor='none',
    )

    axis.set_xlabel('Load fraction')
    axis.set_ylabel('Delay fraction')
    axis.set_zlabel('User utility')
    axis.set_zlim(0, 1)
    axis.set_xlabel('Load')
    axis.set_ylabel('Delay')
    axis.set_zlabel('User utility')

    figure.colorbar(surface, ax=axis, shrink=0.6, label='User utility')
    figure.tight_layout()
    plt.show()

def main():
    test_utility()

if __name__ == "__main__":
    main()
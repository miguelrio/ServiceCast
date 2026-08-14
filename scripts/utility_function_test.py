"""Interactive utility-function explorer for load and delay metrics.

Run this script to print sample utility values and open a 3D plot of the
user-utility function across the full configured ranges of load and delay.

While the plot window is open, edit and save this file to change metric scales,
utility functions, or the user-utility function. Click the "Re-evaluate" button
to reload the saved changes, recalculate the sample values, and redraw the plot.

The script currently supports load and delay metrics, but may be extended in
the future.
"""

import importlib.util
from pathlib import Path
from MetricUtility import MetricUtility, linear, logarithmic, sigmoid
from Utility import Utility
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.widgets import Button

def configure_utility():
    # Define metric scale

    # Load is already normalised in the range 0-1, so setting it to 1 here is not strictly needed. The line can be commented out. But change the value if you want anythihg other than 1.
    MetricUtility.metric_scale['load'] = 1

    # In full simulation runs the default delay scale is set to the network diameter (the maximum of the sum of delays along all network paths). It is determined from the network topology configured for the simulator run. Set it manually to a suitable value here.
    MetricUtility.metric_scale['delay'] = 0.01

    # Define metric utility functions - some examples are in the comments below. Un-comment the one you want, or write a new one.

    # MetricUtility.metric_utility_fn['load'] = lambda value, scale: (1-(0.12*(value/scale))) if (value/scale) < 0.8  else (4.5-(4.5*(load/scale)))
    # MetricUtility.metric_utility_fn['load'] = lambda value, scale: (1-(value/scale))
    # MetricUtility.metric_utility_fn['load'] = lambda value, scale: (logarithmic(value, scale, k=9) if (value / scale) < 0.75 else 0)
    # MetricUtility.metric_utility_fn['load'] = logarithmic
    # MetricUtility.metric_utility_fn['load'] = linear
    # MetricUtility.metric_utility_fn['load'] = lambda value, scale: (1 / (1 + (((value/scale) * (1 - 0.5)) / (0.5 * (1.00001 - (value/scale)))) ** 2))
    MetricUtility.metric_utility_fn['load'] = lambda value, scale: sigmoid(value, scale, midpoint=0.85, exponent=2)
    # MetricUtility.metric_utility_fn['load'] = lambda value, scale: (sigmoid(value, scale, midpoint=0.85, exponent=2) if (value/scale) < 0.5 else logarithmic(value, scale))

    # MetricUtility.metric_utility_fn['delay'] = lambda value, scale: (1-(value/scale)) if value/scale <= 0.5 else 0
    # MetricUtility.metric_utility_fn['delay'] = lambda value, scale: (1 if value/scale <= 3/8 else 0)
    # MetricUtility.metric_utility_fn['delay'] = lambda value, scale: (1 - value / scale)
    # MetricUtility.metric_utility_fn['delay'] = linear
    # MetricUtility.metric_utility_fn['delay'] = lambda value, scale: ((1 - value/scale) if value/scale <= 5/8 else 0)
    # MetricUtility.metric_utility_fn['delay'] = lambda value, scale: (logarithmic(value, scale, k=25))
    # MetricUtility.metric_utility_fn['delay'] = lambda value, scale: (1 / (1 + (((value/scale) * (1 - 0.33)) / (0.33 * (1.00001 - (value/scale)))) ** 5))
    # MetricUtility.metric_utility_fn['delay'] = lambda value, scale: (logarithmic(value, scale, k=10) if value/scale < 0.75 else 0)
    MetricUtility.metric_utility_fn['delay'] = lambda value, scale: (sigmoid(value, scale, midpoint=0.6, exponent=3) if value/scale <= 0.75 else 0)
    # MetricUtility.metric_utility_fn['delay'] = lambda value, scale: (sigmoid(value, scale, midpoint=0.75, exponent=5))


    # Define the user_utility function here - this is how the metric utilities are combined. The basic methods are weighted arithmetic mean, weighted geometric mean, minimum.

    # Alpha is the weight that is used in weighted arithmetic or geometric mean
    Utility.alpha = 0.5

    # Simple arithmetic mean:
    # Utility.user_utility_fn = staticmethod(lambda alpha, metric_utility: round(metric_utility['load'] * alpha + metric_utility['delay'] * (1 - alpha), 4))
    # Simple geometric mean:
    Utility.user_utility_fn = staticmethod(lambda alpha, metric_utility: round(metric_utility['load'] ** alpha * metric_utility['delay'] ** (1 - alpha), 4))
    # Simple minimum:
    # Utility.user_utility_fn = staticmethod(lambda alpha, metric_utility: np.minimum(metric_utility['load'], metric_utility['delay']))
    # Utility.user_utility_fn = staticmethod(lambda alpha, metric_utility: 0)
    

def reload_configuration():
    script_path = Path(__file__).resolve()
    spec = importlib.util.spec_from_file_location(
        '_utility_function_test_reload',
        script_path,
    )

    if spec is None or spec.loader is None:
        raise ImportError(f'Could not reload {script_path}')

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.configure_utility()


def calculate_utility_grid():
    load_scale = MetricUtility.metric_scale['load']
    delay_scale = MetricUtility.metric_scale['delay']

    load_values = np.linspace(0.0, load_scale, 101)
    delay_values = np.linspace(0.0, delay_scale, 101)
    load_grid, delay_grid = np.meshgrid(load_values, delay_values)
    utility_grid = np.empty_like(load_grid)

    for row, delay in enumerate(delay_values):
        for column, load in enumerate(load_values):
            utility_grid[row, column] = Utility.eval_forwarding_utility({
                'load': load,
                'delay': delay,
            })

    return load_grid, delay_grid, utility_grid

# Use a topology from an adjacency list
def test_utility():
    configure_utility()

    load_grid, delay_grid, utility_grid = calculate_utility_grid()

    figure = plt.figure(figsize=(10, 7))
    figure.canvas.manager.set_window_title("User Utility Function")
    figure.subplots_adjust(
        left=0.03,
        right=0.88,
        bottom=0.12,
        top=0.99,
    )

    axis = figure.add_subplot(111, projection='3d')
    axis.view_init(elev=30, azim=45)
    #axis.set_box_aspect((1.4, 1.1, 0.85))

    surface = axis.plot_surface(
        load_grid,
        delay_grid,
        utility_grid,
        cmap='viridis',
        edgecolor='none',
        vmin=0,
        vmax=1,
    )

    axis.set_xlabel('Load')
    axis.set_ylabel('Delay')
    axis.set_zlabel('User utility')
    axis.set_zlim(0, 1)
    axis.set_xlim(0, MetricUtility.metric_scale['load'])
    axis.set_ylim(0, MetricUtility.metric_scale['delay'])

    colorbar = figure.colorbar(surface, ax=axis, shrink=0.6, label='User utility')

    def print_values():
        delay_scale = MetricUtility.metric_scale['delay']
        load_scale = MetricUtility.metric_scale['load']
        print("delay scale: " + str(delay_scale) + ", load scale: " + str(load_scale))
        print()
        print(
            f"{'Raw load':>10} {'Raw delay':>10} "
            f"{'Load util.':>11} {'Delay util.':>11} {'User util.':>10}"
        )
        print("-" * 59)

        for load_fraction in [0.0, 0.25, 0.5, 0.75, 1.0]:
            for delay_fraction in [0.0, 0.25, 0.5, 0.75, 1.0]:
                load = load_fraction * load_scale
                delay = delay_fraction * delay_scale
                metrics = {'load': load, 'delay': delay}
                metric_utility = MetricUtility.evaluate(metrics)
                user_utility = Utility.eval_forwarding_utility(metrics)
                print(
                    f"{load:10.3g} {delay:10.3g} "
                    f"{metric_utility['load']:11.3g} "
                    f"{metric_utility['delay']:11.3g} "
                    f"{user_utility:10.3g}"
                )

    def redraw(_event):
        nonlocal surface

        try:
            reload_configuration()
            print_values()
            new_load_grid, new_delay_grid, new_utility_grid = calculate_utility_grid()
            new_surface = axis.plot_surface(
                new_load_grid,
                new_delay_grid,
                new_utility_grid,
                cmap='viridis',
                edgecolor='none',
                vmin=0,
                vmax=1,
            )

            surface.remove()
            surface = new_surface
            colorbar.update_normal(surface)
            axis.set_zlim(0, 1)
            axis.set_xlim(0, MetricUtility.metric_scale['load'])
            axis.set_ylim(0, MetricUtility.metric_scale['delay'])
            figure.canvas.draw_idle()
        except Exception as error:
            print(f'Could not re-evaluate formulas: {error}')
    def rotate_view(_event):
        axis.view_init(
            elev=axis.elev,
            azim=axis.azim + 45,
        )
        figure.canvas.draw_idle()

    print_values()
    rotate_button_axis = figure.add_axes([0.47, 0.02, 0.17, 0.03])
    rotate_button = Button(rotate_button_axis, 'Rotate +45 deg')
    rotate_button.on_clicked(rotate_view)

    button_axis = figure.add_axes([0.67, 0.02, 0.17, 0.03])
    button = Button(button_axis, 'Re-evaluate')
    button.on_clicked(redraw)

    plt.show()

def main():
    test_utility()

if __name__ == "__main__":
    main()
from dataclasses import dataclass
import pandas as pd
import numpy as np
import sympy


@dataclass
class Mode:
    name             : str
    access_time      : float  # Tom (hour)
    modal_speed      : float  # Vm  (km/hr)
    fixed_modal_cost : float  # Com ($)
    cost_per_distance: float  # ym  ($/hr)

    def transport_time(self, displacement) -> float:
        return self.access_time + (displacement / self.modal_speed)

    def transport_cost(self, displacement) -> float:
        return self.fixed_modal_cost + (self.cost_per_distance * displacement)

    def generalized_cost(self, value_of_time, displacement) -> float:
        return self.transport_cost(displacement) + (value_of_time * self.transport_time(displacement))

    def generalized_time(self, value_of_time, displacement) -> float:
        return self.transport_time(displacement) + (self.transport_cost(displacement) / value_of_time)

    def generalized_speed(self, value_of_time, displacement) -> float:
        return displacement / self.generalized_time(value_of_time, displacement)


def optimum_mode(modes, value_of_time, displacement) -> (Mode, float):
    max_mode_val = 0
    max_mode = None

    for i in range(len(modes)):
        generalized_speed_i = modes[i].generalized_speed(value_of_time, displacement)
        if generalized_speed_i >= max_mode_val:
            max_mode_val = generalized_speed_i
            max_mode = modes[i]

    return max_mode, max_mode_val

scenario_1 = [
        Mode('Walking', 0, 5, 0, 0),
        Mode('Bicycles', .03, 9, 0, .05),
        Mode('Mopeds', .1, 20, 0, .3),
        Mode('Scooters', .09, 35, 0, .6),
        Mode('Auto-Rickshaws', .15, 40, 0, 2.5),
        Mode('Taxis', .5, 30, 0, 3.5),
        Mode('Buses', .17, 30, 0, .4),
        Mode('Trains', .2, 35, 0, .5),
        Mode('Automobiles', .25, 40, 0, .9)
    ]

scenario_1_1 = [
    Mode('1', 0, 5, 0, 0),
    Mode('2', .03, 9, 0, .05),
    Mode('3', .1, 20, 0, .3),
    Mode('4', .09, 35, 0, .6),
    Mode('5', .15, 40, 0, 2.5),
    Mode('6', .5, 30, 0, 3.5),
    Mode('7', .17, 30, 0, .4),
    Mode('8', .2, 35, 0, .5),
    Mode('9', .25, 40, 0, .9)
]

scenario_2 = [
    Mode('Walking', 0, 5, 0, 0.01),
    Mode('Bicycles', .03, 12, 0, .05),
    Mode('Mopeds', .073, 25, 0, .2),
    Mode('Scooters', .09, 40, 0, .53),
    Mode('Auto-Rickshaws', .15, 40, 0, 3.5),
    Mode('Taxis', .5, 30, 0, 4.5),
    Mode('Buses', .15, 40, 0, .35),
    Mode('Trains', .17, 45, 0, .35),
    Mode('Automobiles', .25, 40, 0, 2)
]

scenario_2_1 = [
    Mode('1', .000,  5, 0, 0.01),
    Mode('2', .030, 12, 0.3, 0.05),
    Mode('3', .073, 25, 1.24, 0.20),
    Mode('4', .090, 40, 1.1, 0.53),
    Mode('5', .150, 40, 0, 3.50),
    Mode('6', .500, 30, 0, 4.50),
    Mode('7', .150, 40, .35, 0.35),
    Mode('8', .170, 45, .48, 0.35),
    Mode('9', .250, 40, 0, 2.00)
]

#     name             : str
#     access_time      : float  # Tom (hour)
#     modal_speed      : float  # Vm  (mi/hr)
#     fixed_modal_cost : float  # Com ($)
#     cost_per_distance: float  # ym  ($/hr)

scenario_new = [
    Mode('Walking',     .00, 3., 0.00, 0.0),
    Mode('Bicycles',    .03, 7., 0.00, .25),
    Mode('Automobiles', .03, 11, 0.00, 0.81),
    Mode('Taxis',       .50, 11, 3.25, 2.25),
    Mode('Buses',       .15, 9., 2.25, 0.0),
    Mode('Subway',      .25, 18, 2.50, 0.5),
    Mode('Train',       .33, 30, 3.75, 1.0),
]

def geometric_sequence_with_step(start, step, num_elements):
    return [start * (step ** i) for i in range(num_elements)]


def create_table(scenario, vot=None, disp=None):

    if vot is None:
        values_of_time = geometric_sequence_with_step(2, 1.15, 25)
    else:
        values_of_time = vot

    if disp is None:
        displacements = geometric_sequence_with_step(.1, 1.5, 17)
    else:
        displacements = disp

    SCENARIO = scenario


    max_mode_names = []
    max_mode_vals = []
    for value_of_time in values_of_time:
        max_mode_name_row = []
        max_mode_val_row = []

        for displacement in displacements:
            max_mode, max_mode_val = optimum_mode(SCENARIO, value_of_time, displacement)
            max_mode_name_row.append(max_mode.name)
            max_mode_val_row.append(max_mode_val)

        max_mode_names.append(max_mode_name_row)
        max_mode_vals.append(max_mode_val_row)
    mode_names_df = pd.DataFrame(max_mode_names, index=values_of_time, columns=displacements)
    mode_vals_df = pd.DataFrame(max_mode_vals, index=values_of_time, columns=displacements)
    print("Mode Names:")
    print(mode_names_df)
    mode_names_df.to_csv('mode_names_scenario_r.csv')
    print("Mode Vals:")
    print(mode_vals_df)
    mode_vals_df.to_csv('mode_vals_scenario_r.csv')


# Press the green button in the gutter to run the script.
if __name__ == '__main__':

    create_table(scenario_new, vot=[1, 5, 7.25, 12, 16.75, 24, 36, 48, 72, 100], disp=[1, 2.5, 5, 7.5, 10, 15, 20, 25, 50, 100])



# See PyCharm help at https://www.jetbrains.com/help/pycharm/

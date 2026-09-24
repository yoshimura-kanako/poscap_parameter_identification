'''
Warning: Changes in this file may not be correctly interpreted later on in the macro engine.

Generated script file.

Name for generated for macro: Pana - Calibration 1: SAOR (no graph) v261

Macro description: Computes the static angle of repose (SAOR).

@author: ESSS
@date: 2022-01

'''

import os
import sys
import pandas as pd
import numpy as np
#import matplotlib.pyplot as plt
import json
from scipy import stats

# ------------------------------
# CONSTANTS
# ------------------------------

TRAY_WIDTH = 0.06 #m
CYLINDER_HEIGHT = 0.05#m

# Controls the bin size, bin_size = N_DIVISIONS_FACTOR * particle average diamenter
N_DIVISIONS_FACTOR = 0.15
# Number of angular samples
N_SAMPLES = 36
# Linear Regression Initial Sample size
LIN_REG_INI = 3


def best_fit(x,y):

    '''
    This function will fit a linear equation for x[:i+LIN_REG_INI],y[:i+LIN_REG_INI]
    and return the best fit it can find. The best fit is assumed where R^2 is max.
    '''

    res = np.array(
        [stats.linregress(x[:i+LIN_REG_INI],y[:i+LIN_REG_INI]).rvalue for i,_ in enumerate(x[LIN_REG_INI:])]
    )

    n = np.argmax(np.abs(res))+LIN_REG_INI
    fit = stats.linregress(x[:n], y[:n])

    return fit, n

def update_array(x,valid, sym = True):
    if valid:
        if sym and valid > 0:
            x = x[valid:-valid]
        else:
            x = x[valid]

    return x

def post_process(project, results_folder):

    # Project Data

    study = project.GetStudy()
    timeset = study.GetTimeSet()

    particles = study.GetParticles()
    collection = project.GetUserProcessCollection()

    # Creates the cylinder user process if it does not exist, otherwise updates info
    # The cylinder user process has a hight of 90% of the container to avoid issues
    # near the inlet

    particle_diameter=0.0021
    #particle_diameter = np.average(particles.GetGridFunction('Particle Size').GetArray(time_step=timeset[-1]))

    if 'cube_process' not in collection.GetCubeProcessNames():
        cube_process = collection.CreateCubeProcess(
            particles,
            name='cube_process',
            #center=(0, 0.5*0.05, 0),
            center=(0, 0.5*CYLINDER_HEIGHT, 0),
            #magnitude=(0.06,0.05,0.0042)
            magnitude=(TRAY_WIDTH,CYLINDER_HEIGHT,2*particle_diameter)
        )
    else:
        cube_process = collection.GetProcess('cube_process')
        #cube_process.SetCenter(0, 0.5*0.05, 0)
        cube_process.SetCenter(0,0.5*CYLINDER_HEIGHT,0)
        #cube_process.SetSize(0.06,0.05,0.0042)
        cube_process.SetSize(TRAY_WIDTH,CYLINDER_HEIGHT,2*particle_diameter)

    # Creates the Eulerian statistics user process if it does not exist, otherwise
    # updates info

    #n_divisions=191
    n_divisions = int(TRAY_WIDTH/particle_diameter/N_DIVISIONS_FACTOR) if int(TRAY_WIDTH/particle_diameter/N_DIVISIONS_FACTOR)%2!=0 else int(TRAY_WIDTH/particle_diameter/N_DIVISIONS_FACTOR) + 1

    if 'eulerian_statistics_process' not in collection.GetEulerianStatisticsNames():
        eulerian = collection.CreateEulerianStatistics(
            cube_process,
            name='eulerian_statistics_process',
            divisions=(n_divisions,1,1)
        )
    else:
        eulerian = collection.GetProcess('eulerian_statistics_process')
        eulerian.SetDivisions((n_divisions,1,1))

    # Tries to read the Max of Particle Y-Coordinate grid function otherwise
    # it will be created

    try:
        max_y_coordinate = eulerian.GetGridFunction('Max of Coordinate : Y')
    except:
        max_y_coordinate = eulerian.CreateEulerianGridFunction(
            'Max',
            'Coordinate : Y'
        )

    #print("check6:", max_y_coordinate.GetArray(time_step=timeset[-1])) #check6

    # Sampling - will get the max y-coordinate for each sampling angle and
    # populate the particle_height array

    particle_height = np.zeros((N_SAMPLES,n_divisions))
    angular_increment = 360/N_SAMPLES

    #print("check5:",particle_height) #check5

    # Retrieving maximum y coordinate for each bin at each time sample
    for i in range(0,N_SAMPLES):
        cube_process.SetRotation(0,angular_increment*i,0)
        particle_height[i] = max_y_coordinate.GetArray(time_step=timeset[-1])

    #print("check4:",particle_height) #check4

    # Masking array to avoid empty bins
    particle_height_masked = np.ma.masked_values(particle_height, 0)

    #print("check3:",particle_height_masked[0]) #check3

    # Calculating min, max and average
    particle_max_y_coordinate = np.amax(particle_height_masked, axis=0)
    particle_min_y_coordinate = np.amin(particle_height_masked, axis=0)
    particle_avg_y_coordinate = np.average(particle_height_masked, axis=0)

    #print("check1:",particle_max_y_coordinate[0]) #check1

    # Mask array
    m = particle_avg_y_coordinate.mask

    # Remove invalid entries
    particle_max_y_coordinate = particle_max_y_coordinate[~m]
    particle_min_y_coordinate = particle_min_y_coordinate[~m]
    particle_avg_y_coordinate = particle_avg_y_coordinate[~m]

    #print("check2:",particle_max_y_coordinate[0]) #check2

    ###############
    # Data fitting
    ###############

    dx = TRAY_WIDTH/n_divisions
    size = len(particle_avg_y_coordinate)
    x_coord = np.arange(-(size-1)*dx/2,(size)*dx/2,dx)

    ### Removing outliers ####

    # Will first consider as valid the points where the minimum particle height
    # is higher than any of the preivous average points

    valid = 0

    for i in range(1,particle_min_y_coordinate.shape[0]):
        if np.where(particle_avg_y_coordinate[:i] <= particle_min_y_coordinate[i]):
            valid = i
            break

    x_coord_fit = update_array(x_coord, valid)
    particle_min_y_coordinate_fit = update_array(particle_min_y_coordinate, valid)
    particle_max_y_coordinate_fit = update_array(particle_max_y_coordinate, valid)
    particle_avg_y_coordinate_fit = update_array(particle_avg_y_coordinate, valid)

    # Also, it will onlly consider the points where the average height
    # is greater than the avarage particle diameter. This will automatically
    # remove particles that are far from the pile

    valid = np.where(particle_avg_y_coordinate_fit > particle_diameter)
    x_coord_fit = update_array(x_coord_fit, valid, sym=False)
    particle_min_y_coordinate_fit = update_array(particle_min_y_coordinate_fit, valid, sym=False)
    particle_max_y_coordinate_fit = update_array(particle_max_y_coordinate_fit, valid, sym=False)
    particle_avg_y_coordinate_fit = update_array(particle_avg_y_coordinate_fit, valid, sym=False)

    # As a last test, points where the minimum y coordinate reduces towards
    # the pile center are removed
    valid = 0
    for j in range(1, int(particle_min_y_coordinate_fit.shape[0]/2)):
        if particle_min_y_coordinate_fit[j] > particle_min_y_coordinate_fit[j-1]:
            valid = j-1
            break
        elif particle_avg_y_coordinate_fit[j] > particle_avg_y_coordinate_fit[j-1]:
            valid = j
            break
        else:
            pass

    x_coord_fit = update_array(x_coord_fit, valid)
    particle_min_y_coordinate_fit = update_array(particle_min_y_coordinate_fit, valid)
    particle_max_y_coordinate_fit = update_array(particle_max_y_coordinate_fit, valid)
    particle_avg_y_coordinate_fit = update_array(particle_avg_y_coordinate_fit, valid)

    # number of available bins
    n = len(particle_avg_y_coordinate_fit)
    # Center
    c = int((n-1)/2)

    # Starting from pile top
    top_start = c + 1

    # Avoiding plateaus at the top of the pile
    for i in range(top_start, n-3):
        if particle_avg_y_coordinate_fit[i] <= particle_avg_y_coordinate_fit[c]:
            top_start = i
            break

    for i in range(top_start, top_start + int(len(particle_avg_y_coordinate_fit[top_start:])/2)):
            test = stats.linregress(x_coord_fit[top_start:i+3], particle_avg_y_coordinate_fit[top_start:i+3])
            if np.abs(test.slope) > np.tan(np.deg2rad(10)):
                top_start = i
                break

    fit_top, size_top = best_fit(x_coord_fit[top_start:], particle_avg_y_coordinate_fit[top_start:])

    # Starting from pile bottom
    fit_bottom, size_bottom = best_fit(x_coord_fit[:c], particle_avg_y_coordinate_fit[:c])

    # Fitted curves
    y_top = fit_top.intercept + fit_top.slope*x_coord
    y_bottom = fit_bottom.intercept + fit_bottom.slope*x_coord
    top_angle = np.degrees(abs(np.arctan(fit_top.slope)))
    bottom_angle = np.degrees(abs(np.arctan(fit_bottom.slope)))
    # ####################
    # # Charting
    # ####################
    # try:
    #     plt.close('all')
    #     fig = plt.figure(figsize=(12,8))
    #     ax = fig.add_subplot(1,1,1)

    #     ax.fill_between(x_coord, 0, particle_max_y_coordinate, facecolor=(160/255, 15/255, 20/255), alpha=0.15, label='Maximum')
    #     ax.fill_between(x_coord, 0, particle_min_y_coordinate, facecolor=(160/255, 15/255, 20/255), alpha=0.45, label='Minimum')
    #     ax.plot(x_coord,particle_avg_y_coordinate, 'ko', label='Average', markersize=3)

    #     # Fitted curves display
    #     x_display_top = np.linspace(x_coord_fit[top_start] - dx*0.5, x_coord_fit[top_start+size_top] + dx*0.5, 10)
    #     y_display_top = fit_top.intercept + fit_top.slope*x_display_top
    #     x_display_bottom = np.linspace(x_coord_fit[0] - dx*0.5, x_coord_fit[size_bottom] + dx*0.5, 10)
    #     y_display_bottom = fit_bottom.intercept + fit_bottom.slope*x_display_bottom

    #     top_angle = np.degrees(abs(np.arctan(fit_top.slope)))
    #     bottom_angle = np.degrees(abs(np.arctan(fit_bottom.slope)))


    #     text = "$\mathrm{AOR}_{\mathrm{\mathit{top}}}$    "  +  u" = {0:3.1f}\u00b0".format(top_angle)
    #     text += "\n$\mathrm{AOR}_{\mathrm{\mathit{bottom}}}$" + u" = {0:3.1f}\u00b0".format(bottom_angle)

    #     ax.plot(x_display_top,y_display_top,color=(160/255, 15/255, 20/255), linestyle='--', linewidth=2, label=u"Fitting from pile top = {0:3.1f}\u00b0".format(np.degrees(abs(np.arctan(fit_top.slope)))))
    #     ax.plot(x_display_bottom,y_display_bottom,color=(64/255, 63/255, 86/255), linestyle='--', linewidth=2, label=u"Fitting from pile bottom = {0:3.1f}\u00b0".format(np.degrees(abs(np.arctan(fit_bottom.slope)))))
    #     t = ax.annotate(text, xy = (0.5,  0.1), xycoords='axes fraction', fontsize=12)
    #     t.set_bbox(dict(boxstyle="square, pad=0.4", facecolor=(194/255, 194/255, 201/255), alpha=1.0))

    #     # Legend
    #     legend = ax.legend(loc='upper left', fontsize=10)
    #     ax.set_xlabel('Pile Radius [m]', fontsize=12)
    #     ax.set_ylabel('Pile Height [m]', fontsize=12)

    #     # Changing x-axis labels
    #     labels = [str(round(abs(item),1)) for item in ax.get_xticks()]
    #     ax.set_xticklabels(labels)

    #     plt.gca().set_aspect('equal')

    #     ax.set_ylim(0,np.max(particle_max_y_coordinate)*1.5)

    #     plt.tight_layout()
    #     file_name = os.path.join(results_folder, "Experiment_saor.png")
    #     plt.savefig(file_name)
    #     plt.draw()

    #     # Check if the plot is too small to fit the legend
    #     if fig.get_size_inches()[0]*fig.dpi * np.max(particle_max_y_coordinate) / np.max(x_coord) / 2 < 2 * legend.get_window_extent().height:
    #         ax.set_ylim(0,np.max(particle_max_y_coordinate)*3)


    #     plt.show()
    #     plt.savefig(file_name)
    # except:
    #     pass

    ##################
    # Wrapping up data
    ##################

    result_data = np.vstack((x_coord, particle_min_y_coordinate, particle_max_y_coordinate, particle_avg_y_coordinate, y_top, y_bottom))
    result_data = np.transpose(result_data)

    #Angles

    return result_data,top_angle,bottom_angle


def dump_to_file(data,top_angle,bottom_angle, results_folder):

    file_path = os.path.join(results_folder, "experiment_data_points.csv")
    header = ['x_coord','min_y_coordinate','max_y_coordinate','avg_y_coordinate', 'fit_top', 'fit_bottom']
    pd.DataFrame(data).to_csv(file_path, mode="w", header=header, line_terminator="\n", index=False)
    # Directly from dictionary
    with open(os.path.join(results_folder, "angles.json"), 'w') as outfile:
        json.dump(
            {
                "SAOR_from_top": top_angle,
                "SAOR_from_bottom": bottom_angle
            }
            , outfile)


def main(project):

    path = os.path.dirname(project.GetProjectFilename())

    # Results folder creation to save the files

    results_folder = os.path.join(path, "Results")
    if not os.path.exists(results_folder):
        os.mkdir(results_folder)

    result_data,top_angle,bottom_angle = post_process(project, results_folder)
    dump_to_file(result_data,top_angle,bottom_angle, results_folder)

# -----------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------


project = app.GetProject()
main(project)
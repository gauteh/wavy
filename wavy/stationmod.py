#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------#
'''
This module encompasses classes and methods to read and process wave
field related data from stations. I try to mostly follow the PEP 
convention for python code style. Constructive comments on style and 
effecient programming are most welcome!
'''
# --- import libraries ------------------------------------------------#
'''
List of libraries needed for this class. Sorted in categories to serve
effortless orientation. May be combined at some point.
'''
# read_altim
import os
import sys
import netCDF4

# all class
import numpy as np
from datetime import datetime, timedelta
import datetime
import argparse
from argparse import RawTextHelpFormatter
import yaml
import os

# get_altim
import urllib
import gzip
import ftplib
from ftplib import FTP

# create_file
import calendar

import sys

# get_remote
from dateutil.relativedelta import relativedelta
from copy import deepcopy

import time

# get d22 files
import pylab as pl
from datetime import datetime
import scipy as sp

# netcdf related
from ncmod import ncdumpMeta, get_varname_for_cf_stdname_in_ncfile

# read yaml config files:
moddir = os.path.abspath(os.path.join(os.path.dirname( __file__ ), 
                        '..', 'config/buoy_specs.yaml'))
with open(moddir,'r') as stream:
    buoy_dict=yaml.safe_load(stream)

moddir = os.path.abspath(os.path.join(os.path.dirname( __file__ ), 
                        '..', 'config/stationlist.yaml'))
with open(moddir,'r') as stream:
    locations=yaml.safe_load(stream)

moddir = os.path.abspath(os.path.join(os.path.dirname( __file__ ), 
                        '..', 'config/station_specs.yaml'))
with open(moddir,'r') as stream:
    station_dict=yaml.safe_load(stream)

moddir = os.path.abspath(os.path.join(os.path.dirname( __file__ ), 
                        '..', 'config/pathfinder.yaml'))
with open(moddir,'r') as stream:
    pathfinder=yaml.safe_load(stream)

moddir = os.path.abspath(os.path.join(os.path.dirname( __file__ ),
                        '..', 'config/d22_var_dicts.yaml'))
with open(moddir, 'r') as stream:
    d22_var_dicts=yaml.safe_load(stream)

moddir = os.path.abspath(os.path.join(os.path.dirname( __file__ ), '..', 'config/variable_info.yaml'))
with open(moddir,'r') as stream:
    variable_info=yaml.safe_load(stream)

stationpath_lustre_om = pathfinder['stationpath_lustre_om']
stationpath_lustre_hi = pathfinder['stationpath_lustre_hi']

# --- global functions ------------------------------------------------#

# define flatten function for lists
''' fct does the following:
flat_list = [item for sublist in TIME for item in sublist]
or:
for sublist in TIME:
for item in sublist:
flat_list.append(item)
'''
flatten = lambda l: [item for sublist in l for item in sublist]

# ---------------------------------------------------------------------#


class station_class():
    '''
    Class to handle platform based time series.
    '''
    basedate = datetime(1970,1,1)
    time_unit = 'seconds since 1970-01-01 00:00:00.0'
    def __init__(self,platform,sensor,sdate,edate,
                mode='d22',deltat=10,varalias='Hs'):
        print ('# ----- ')
        print (" ### Initializing station_class object ###")
        print ('Chosen period: ' + str(sdate) + ' - ' + str(edate))
        print (" Please wait ...")
        stdvarname = variable_info[varalias]['standard_name']
        var, time, timedt = self.get_station(
                                    platform, # change to stdvarname in future
                                    sdate,edate,
                                    mode,deltat,
                                    sensor,
                                    varalias)
        vardict = {
                    stdvarname:var,
                    'time':time,
                    'datetime':timedt,
                    'time_unit':self.time_unit,
                    'longitude':[locations[platform][1]]*len(var),
                    'latitude':[locations[platform][0]]*len(var)
                    }
        # in future coordinates need to be properly 
        # defined with names longitude and latitude 
        # in yaml file not as it is now in stationlist.yaml
        self.vars = vardict
        self.stdvarname = stdvarname
        if mode == 'd22':
            self.varname = varalias
        elif mode == 'nc':
            self.varname = varalias # varalias to be replaced by ncfile varname
        self.varalias = varalias
        self.sdate = sdate
        self.edate = edate
        self.lat = locations[platform][0]
        self.lon = locations[platform][1]
        self.platform = sensor
        self.sensor = platform
        print (" ### station_class object initialized ###")
        print ('# ----- ')

    def get_station(self,platform,sdate,edate,mode,deltat,sensor,varalias):
        stdvarname = variable_info[varalias]['standard_name']
        pathlst = station_dict['path']['platform']['local'][mode]['template']
        strsublst = station_dict['path']['platform']['local'][mode]['strsub']
        if mode == 'nc':
            tmpdate = sdate
            var = []
            time = []
            timedt = []
            while (tmpdate <= edate):
                pathtofile = make_pathtofile(platform,sensor,varalias,
                                             pathlst,strsublst,tmpdate)
                ncdict = ncdumpMeta(pathtofile)
                varname = get_varname_for_cf_stdname_in_ncfile(ncdict,
                                                               stdvarname)
                if len(varname) > 1:
                    # overwrite like for satellite altimetry files
                    varname = station_dict['platform']['misc']\
                                          ['vardef'][stdvarname]
                else:
                    varname = varname[0]
                nc = netCDF4.Dataset(pathtofile,'r')
                var.append(nc.variables[varname][:])
                timeobj = nc.variables['time']
                time.append(nc.variables['time'][:])
                timedt.append(netCDF4.num2date(timeobj[:],timeobj.units))
                nc.close()
                tmpdate = tmpdate + relativedelta(months = +1)
            var = np.array(var).flatten()
            time = np.array(time).flatten()
            timedt = np.array(timedt).flatten()
        elif mode == 'd22':
            sdatetmp = sdate - timedelta(days=1)
            edatetmp = edate + timedelta(days=1)
            sl = parse_d22(platform,sensor,varalias,sdatetmp,edatetmp,
                          pathlst,strsublst,mode)
            var, timedt = extract_d22(sl,varalias,platform,sensor)
            time = np.array(
                    [(t-self.basedate).total_seconds() for t in timedt]
                    )
            ctime, idxtmp = matchtime(sdate,edate,timedt,timewin=1)
        ctime, idxtmp = matchtime(sdate,edate,timedt,timewin=1)
        # convert to list for consistency with other classes
        var = list(np.real(var[idxtmp]))
        time = list(time[idxtmp])
        timedt = list(timedt[idxtmp])
        return var, time, timedt

def make_pathtofile(platform,sensor,varalias,pathlst,strsublst,date):
    i = 0
    pathtofile = date.strftime(pathlst[i])
    for strsub in strsublst:
        pathtofile = pathtofile.replace(strsub,locals()[strsub])
    while os.path.isfile(pathtofile) is False:
        i += 1
        pathtofile = date.strftime(pathlst[i])
        for strsub in strsublst:
            pathtofile = pathtofile.replace(strsub,locals()[strsub])
    return pathtofile

def compute_superobs(st_obj,smoother='running_mean',**kwargs):
    """
    Applies a smoothing filter to create a super-observed ts
    **kwargs includes method specific input for chosen smoother
    Smoother on wish list are:
            block-average
            running mean using convolution
            GP
            GAM
            ...
    Caution:    for some smoothers much more of time series has 
                to be included.
    """
    print('under construction')
    return

def parse_d22(platform,sensor,varalias,sdate,edate,pathlst,strsublst,mode):
    """
    Read all lines in file and append to sl
    """
    sl=[]
    for d in range(int(pl.date2num(sdate)),int(pl.date2num(edate))+1): 
        i = 0
        pathtofile = make_pathtofile(platform,sensor,varalias,\
                                    pathlst,strsublst,pl.num2date(d))
        f = open(pathtofile, "r")
        sl = sl + f.readlines()
        f.close()
    return sl

def floater(s):
    """
    Function that converts 's' to float32 or nan if floater throws exception 
    """
    try:
        x = np.float32(s)
    except:
        x = np.nan
    return x

def find_category_for_variable(varalias):
    lst = [ i for i in d22_var_dicts.keys() \
            if (varalias in d22_var_dicts[i]) ]
    if len(lst) == 1:
        return lst[0]
    else: return None

def get_revised_categories(sl,category):
    """
    finds number of occurences of string (category) to determine
    revised_categories (type: list)
    """
    revised_categories = []
    count = 1
    newsl = sl[1:(sl[1:-1].index('!!!!\n'))]
    for element in newsl: 
        if category in element:
            revised_categories.append(category+str(count))
            count+=1
    return revised_categories

def extract_d22(sl,varalias,platform,sensor):
    """
    Extracting data of choice - reading sl from parse_d22
    CAUTION: 10min data is extracted for entire days only 00:00h - 23:50h
    Returns values of chosen variable (ts) and corresponding datetimes (dt)
    as type: np.array
    """
    category = find_category_for_variable(varalias)
    revised_categories = get_revised_categories(sl,category)
    ts = []
    dt = []
    for i, line in enumerate(sl):
        # get ts for date and time
        if "!!!!" in line:
            datestr = sl[  i
                         + d22_var_dicts['datetime']['date']['idx']
                        ].strip()
            timestr = sl[  i
                         + d22_var_dicts['datetime']['time']['idx']
                        ].strip()
            date_object = datetime.strptime(datestr 
                                            + ' ' 
                                            + timestr,
                                            '%d-%m-%Y %H:%M')
            dt.append(date_object)
        # get ts for variable of interest
        revised_category_for_sensor = revised_categories[
                                        station_dict['platform']\
                                        [platform]['sensor']\
                                        [sensor] ]
        if revised_category_for_sensor in line:
            value = sl[  i
                       + d22_var_dicts[category][varalias]['idx']
                       ].strip()
            ts.append(floater(value))
    #Convert data to arrays
    dt = np.array(dt)
    ts = np.array(ts)
    return ts, dt

def matchtime(sdate,edate,time,time_unit=None,timewin=None,basetime=None):
    '''
    fct to obtain the index of the time step closest to the 
    requested time including the respective time stamp(s). 
    Similarily, indices are chosen for the time and defined region.
    time_win is in [minutes]
    '''
    if timewin is None:
        timewin = 0
    # create list of datetime instances
    timelst=[]
    ctime=[]
    cidx=[]
    idx=0
    if (edate is None or sdate==edate):
        for element in time:
            if time_unit is None:
                tmp = element
            else:
                tmp = netCDF4.num2date(element,time_unit)
            timelst.append(tmp)
            # choose closest match within window of win[minutes]
            if (tmp >= sdate-timedelta(minutes=timewin)
            and tmp <= sdate+timedelta(minutes=timewin)):
                ctime.append(tmp)
                cidx.append(idx)
            del tmp
            idx=idx+1
    if (edate is not None and edate!=sdate):
        for element in time:
            if basetime is None:
                tmp = element
            else:
                tmp = netCDF4.num2date(element,time_unit)
            timelst.append(tmp)
            # choose closest match within window of win[minutes]
            if (tmp >= sdate-timedelta(minutes=timewin)
            and tmp < edate+timedelta(minutes=timewin)):
                ctime.append(tmp)
                cidx.append(idx)
            del tmp
            idx=idx+1
    return ctime, cidx

#def get_loc_idx(init_lats,init_lons,target_lat,target_lon,mask=None):
#    from utils import haversine
#    distM = np.zeros(init_lats.shape)*np.nan
#    for i in range(init_lats.shape[0]):
#        for j in range(init_lats.shape[1]):
#            if mask is None:
#                distM[i,j] = haversine(init_lons[i,j],init_lats[i,j],
#                                    target_lon,target_lat)
#            else:
#                if isinstance(mask[i,j],(np.float32)):
#                    distM[i,j] = haversine(init_lons[i,j],init_lats[i,j],
#                                    target_lon,target_lat)
#    idx,idy = np.where(distM==np.nanmin(distM))
#    return idx, idy, distM, init_lats[idx,idy], init_lons[idx,idy]

# --> get_loc_idx is to be deleted once dependencies are corrected

# --- help ------------------------------------------------------------#
if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="""
This module encompasses classes and methods to read and process wave
field related data from stations.\n
Usage:
from stationmod import station_class as sc
from datetime import datetime, timedelta
sc_obj = sc('ekofiskL',sdate,edate)
    """,
    formatter_class = RawTextHelpFormatter
    )
    args = parser.parse_args()

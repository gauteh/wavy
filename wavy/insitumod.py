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
# standard library imports
import os
import numpy as np
from datetime import datetime, timedelta
import datetime
import time
import argparse
from argparse import RawTextHelpFormatter
import os
from dateutil.relativedelta import relativedelta
from copy import deepcopy
import pylab as pl
from datetime import datetime

# own imports
from wavy.ncmod import ncdumpMeta
from wavy.ncmod import dumptonc_ts_insitu, get_varlst_from_nc_1D
from wavy.ncmod import get_filevarname
from wavy.utils import collocate_times
from wavy.utils import make_pathtofile, get_pathtofile
from wavy.utils import convert_meteorologic_oceanographic
from wavy.utils import finditem, make_subdict
from wavy.utils import parse_date
from wavy.filtermod import filter_main
from wavy.wconfig import load_or_default
# ---------------------------------------------------------------------#

# read yaml config files:
insitu_dict = load_or_default('insitu_specs.yaml')
variable_info = load_or_default('variable_info.yaml')
d22_dict = load_or_default('d22_var_dicts.yaml')
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


class insitu_class():
    '''
    Class to handle insitu based time series.
    '''
    basedate = datetime(1970,1,1)

    def __init__(self,nID,sensor,sdate,edate,varalias='Hs',
    filterData=False,**kwargs):
        # parse and translate date input
        sdate = parse_date(sdate)
        edate = parse_date(edate)
        print('# ----- ')
        print(" ### Initializing insitu_class object ###")
        print(" ")
        print ('Chosen period: ' + str(sdate) + ' - ' + str(edate))
        stdvarname = variable_info[varalias]['standard_name']
        try:
            self.stdvarname = stdvarname
            self.varalias = varalias
            self.units = variable_info[varalias].get('units')
            self.sdate = sdate
            self.edate = edate
            self.nID = nID
            self.sensor = sensor
            self.obstype = 'insitu'
            if ('tags' in insitu_dict[nID].keys() and
            len(insitu_dict[nID]['tags'])>0):
                self.tags = insitu_dict[nID]['tags']
            print(" ")
            print(" ## Read files ...")
            t0=time.time()
            if filterData == False:
                vardict, fifo, pathtofile = \
                    get_insitu_ts(\
                                nID, sensor,sdate,edate,
                                varalias,self.basedate,vars(self),
                                **kwargs)
            elif filterData == True:
                # determine start and end date
                if 'stwin' not in kwargs.keys():
                    kwargs['stwin'] = 3
                if 'etwin' not in kwargs.keys():
                    kwargs['etwin'] = 0
                sdate_new = sdate - timedelta(hours=kwargs['stwin'])
                edate_new = edate + timedelta(hours=kwargs['etwin'])
                tmp_vardict, fifo, pathtofile = \
                    get_insitu_ts(nID,sensor,
                                sdate_new,edate_new,
                                varalias,self.basedate,vars(self),
                                **kwargs)
                vardict = filter_main(tmp_vardict,
                                      varalias=varalias,
                                      **kwargs)
                # cut to original sdate and edate
                time_cut = np.array(vardict['time'])[ \
                                ( (np.array(vardict['datetime'])>=sdate)
                                & (np.array(vardict['datetime'])<=edate)
                                ) ]
                var_cut = np.array(vardict[stdvarname])[ \
                                ( (np.array(vardict['datetime'])>=sdate)
                                & (np.array(vardict['datetime'])<=edate)
                                ) ]
                lon_cut = np.array(vardict['longitude'])[ \
                                ( (np.array(vardict['datetime'])>=sdate)
                                & (np.array(vardict['datetime'])<=edate)
                                ) ]
                lat_cut = np.array(vardict['latitude'])[ \
                                ( (np.array(vardict['datetime'])>=sdate)
                                & (np.array(vardict['datetime'])<=edate)
                                ) ]
                dtime_cut = np.array(vardict['datetime'])[ \
                                ( (np.array(vardict['datetime'])>=sdate)
                                & (np.array(vardict['datetime'])<=edate)) ]
                vardict['time'] = list(time_cut)
                vardict['datetime'] = list(dtime_cut)
                vardict[stdvarname] = list(var_cut)
                vardict['longitude'] = list(lon_cut)
                vardict['latitude'] = list(lat_cut)
                self.filter = True
                self.filterSpecs = kwargs
            self.vars = vardict
            self.lat = np.nanmean(vardict['latitude'])
            self.lon = np.nanmean(vardict['longitude'])
            if fifo == 'nc':
                meta = ncdumpMeta(pathtofile)
                self.vars['meta'] = meta
                varname = get_filevarname(varalias,
                                          variable_info,
                                          insitu_dict[nID],
                                          meta)
                self.varname = varname
            else:
                self.varname = varalias
            t1=time.time()
            print(" ")
            print( '## Summary:')
            print(str(len(self.vars['time'])) + " values retrieved.")
            print("Time used for retrieving insitu data:",\
                   round(t1-t0,2),"seconds")
            print(" ")
            print (" ### insitu_class object initialized ### ")
        except Exception as e:
            print(e)
            self.error = e
            print ("! No insitu_class object initialized !")
        print ('# ----- ')

    def get_item_parent(self,item,attr):
        ncdict = self.vars['meta']
        lst = [i for i in ncdict.keys() \
                if (attr in ncdict[i].keys() \
                and item in ncdict[i][attr]) \
                ]
        if len(lst) >= 1:
            return lst
        else: return None

    def get_item_child(self,item):
        ncdict = self.vars['meta']
        parent = finditem(ncdict,item)
        return parent

    def quicklook(self,ts=True):
        if ts is True:
            import matplotlib.pyplot as plt
            import matplotlib.dates as mdates
            fig = plt.figure(figsize=(9,3.5))
            ax = fig.add_subplot(111)
            colors = ['k']
            ax.plot(self.vars['datetime'],
                    self.vars[self.stdvarname],
                    linestyle='None',color=colors[0],
                    label=self.nID + ' ( ' + self.sensor + ' )',
                    marker='o',alpha=.5,ms=2)
            plt.ylabel(self.varalias + '[' + self.units + ']')
            plt.legend(loc='best')
            plt.tight_layout()
            #ax.set_title()
            plt.show()

    def write_to_nc(self,pathtofile=None,file_date_incr=None):
        # divide time into months by loop over months from sdate to edate
        if 'error' in vars(self):
            print('Erroneous insitu_class file detected')
            print('--> dump to netCDF not possible !')
        else:
            tmpdate = self.sdate
            edate = self.edate
            while tmpdate <= edate:
                if pathtofile is None:
                    path_template = insitu_dict[self.nID]['dst']\
                                               ['path_template'][0]
                    file_template = insitu_dict[self.nID]['dst']\
                                                ['file_template']
                    strsublst = insitu_dict[self.nID]['dst']['strsub']
                    if 'filterData' in vars(self).keys():
                        file_template = 'filtered_' + file_template
                    tmppath = os.path.join(path_template,file_template)
                    pathtofile = make_pathtofile(tmppath,strsublst,
                                                 vars(self),
                                                 date=tmpdate)
                title = ( self.varalias + ' observations from '
                        + self.nID + ' ' + self.sensor )
                dumptonc_ts_insitu(self,pathtofile,title)
                # determine date increment
                if file_date_incr is None:
                    file_date_incr = insitu_dict[self.nID]\
                                    ['src'].get('file_date_incr','m')
                if file_date_incr == 'm':
                    tmpdate += relativedelta(months = +1)
                elif file_date_incr == 'Y':
                    tmpdate += relativedelta(years = +1)
                elif file_date_incr == 'd':
                    tmpdate += timedelta(days = +1)
        return


def get_insitu_ts(nID,sensor,sdate,edate,varalias,basedate,
dict_for_sub,**kwargs):
    stdvarname = variable_info[varalias]['standard_name']
    # determine fifo
    fifo = finditem(insitu_dict[nID],'fifo')[0]
    path_template = insitu_dict[nID]['src']['path_template']
    file_template = insitu_dict[nID]['src']['file_template']
    pathlst = [p + ('/' + file_template) for p in path_template]
    strsublst = insitu_dict[nID]['src']['strsub']
    if 'path_local' in kwargs.keys():
        pathlst = [kwargs['path_local'] + '/' + file_template]
    if fifo == 'nc':
        vardict, pathtofile = \
            get_nc_ts(nID,varalias,sdate,edate,pathlst,\
                      strsublst,dict_for_sub)
    elif fifo == 'd22':
        var, time, timedt = \
            get_d22_ts(sdate,edate,basedate,nID,sensor,varalias,\
                        pathlst,strsublst,dict_for_sub)
        if 'twin' in insitu_dict[nID]:
            idxtmp = collocate_times(unfiltered_t=timedt,\
                                sdate=sdate,edate=edate,
                                twin=insitu_dict[nID]['twin'])
        else:
            # default to allow for a 1 min variation
            idxtmp = collocate_times(unfiltered_t=timedt,\
                                sdate=sdate,edate=edate,
                                twin=1)
        # convert to list for consistency with other classes
        # and make sure that only steps with existing obs are included
        time = [time[i] for i in idxtmp if i < len(var)]
        timedt = [timedt[i] for i in idxtmp if i < len(var)]
        var = [np.real(var[i]) for i in idxtmp if i < len(var)]
        # rm double entries due to 10min spacing
        if ('unique' in kwargs.keys() and kwargs['unique'] is True):
            # delete 10,30,50 min times, keep 00,20,40
            # 1. create artificial time vector for collocation
            tmpdate = deepcopy(sdate)
            tmpdatelst = []
            while tmpdate<edate:
                tmpdatelst.append(tmpdate)
                tmpdate += timedelta(minutes=20)
            # 2. collocate times
            if 'twin' in insitu_dict[nID]:
                idxtmp = collocate_times(\
                            unfiltered_t=timedt,
                            target_t=tmpdatelst,
                            twin=insitu_dict[nID]['twin'])
            else:
                idxtmp = collocate_times(unfiltered_t=timedt,\
                                target_t=tmpdatelst,
                                twin=1)
            time = list(np.array(time)[idxtmp])
            timedt = list(np.array(timedt)[idxtmp])
            var = list(np.array(var)[idxtmp])
        lons = [insitu_dict[nID]['coords'][sensor]['lon']]\
               *len(var)
        lats = [insitu_dict[nID]['coords'][sensor]['lat']]\
               *len(var)
        pathtofile = path_template
        vardict = {
                    stdvarname:var,
                    'time':time,
                    'datetime':timedt,
                    'time_unit':variable_info['time']['units'],
                    'longitude':lons,
                    'latitude':lats
                    }
    return vardict, fifo, pathtofile

def get_d22_ts(sdate,edate,basedate,nID,sensor,varalias,
pathlst,strsublst,dict_for_sub):
    sdatetmp = sdate
    edatetmp = edate
    sl = parse_d22(sdatetmp,edatetmp,pathlst,strsublst,dict_for_sub)
    var, timedt = extract_d22(sl,varalias,nID,sensor)
    time = np.array(
           [(t-basedate).total_seconds() for t in timedt]
           )
    return var, time, timedt

def get_nc_ts(nID,varalias,sdate,edate,pathlst,strsublst,dict_for_sub):
    # loop from sdate to edate with dateincr
    stdvarname = variable_info[varalias]['standard_name']
    tmpdate = deepcopy(sdate)
    varlst = []
    lonlst = []
    latlst = []
    timelst = []
    dtimelst = []
    # make subdict
    subdict = make_subdict(strsublst,class_object_dict=dict_for_sub)
    while datetime(tmpdate.year,tmpdate.month,1)\
    <= datetime(edate.year,edate.month,1):
        # get pathtofile
        pathtofile = get_pathtofile(pathlst,strsublst,\
                                        subdict,tmpdate)
        # get ncdump
        ncdict = ncdumpMeta(pathtofile)
        # retrieve filevarname for varalias
        filevarname = get_filevarname(varalias,
                                      variable_info,
                                      insitu_dict[nID],
                                      ncdict)
        varstrlst = [filevarname,'longitude','latitude','time']
        # query
        vardict = get_varlst_from_nc_1D(pathtofile,
                                        varstrlst,
                                        sdate,edate)
        varlst.append(list(vardict[filevarname]))
        lonlst.append(list(vardict['longitude']))
        latlst.append(list(vardict['latitude']))
        timelst.append(list(vardict['time']))
        dtimelst.append(list(vardict['dtime']))
        # determine date increment
        file_date_incr = insitu_dict[nID]['src'].get('file_date_incr','m')
        if file_date_incr == 'm':
            tmpdate += relativedelta(months = +1)
        elif file_date_incr == 'Y':
            tmpdate += relativedelta(years = +1)
        elif file_date_incr == 'd':
            tmpdate += timedelta(days = +1)
    varlst = flatten(varlst)
    lonlst = flatten(lonlst)
    latlst = flatten(latlst)
    timelst = flatten(timelst)
    dtimelst = flatten(dtimelst)
    vardict = {
                stdvarname:varlst,
                'time':timelst,
                'datetime':dtimelst,
                'time_unit':variable_info['time']['units'],
                'longitude':lonlst,
                'latitude':latlst
                }
    #pathtofile = insitu_dict[nID]['src']['path_template'][0]
    return vardict, pathtofile

def parse_d22(sdate,edate,pathlst,strsublst,dict_for_sub):
    """
    Read all lines in file and append to sl
    """
    subdict = make_subdict(strsublst,class_object_dict=dict_for_sub)
    sl=[]
    for d in range(int(pl.date2num(sdate))-1,int(pl.date2num(edate))+2):
        try:
            pathtofile = get_pathtofile(pathlst,strsublst,
                                        subdict,pl.num2date(d))
            print('Parsing:', pathtofile)
            f = open(pathtofile, "r")
            sl = sl + f.readlines()
            f.close()
        except Exception as e:
            print('Error in parse_d22:')
            print(e)
    return sl

# flatten all lists before returning them
# define flatten function for lists
''' fct does the following:
flat_list = [item for sublist in TIME for item in sublist]
or:
for sublist in TIME:
for item in sublist:
flat_list.append(item)
'''
flatten = lambda l: [item for sublist in l for item in sublist]

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
    lst = [ i for i in d22_dict.keys() \
            if (varalias in d22_dict[i]) ]
    if len(lst) == 1:
        return lst[0]
    else: return None

def get_revised_categories(sl,category):
    """
    finds number of occurences of string (category) to determine
    revised_categories (type: list)
    """
    revised_categories = []
    idxlst = []
    count = 1
    searching = True
    while (searching is True or count<10):
        revised_category = category+str(count)
        if find_category(sl,revised_category) is True:
            revised_categories.append(revised_category)
            idxlst.append(count-1)
            count += 1
        else:
            searching = False
            count += 1
    return revised_categories,idxlst

def find_category(sl,category):
    for element in sl:
        if category in element:
            return True

def check_sensor_availability(idxlst,nID,sensor):
    idxyaml = insitu_dict[nID]['sensor'][sensor]
    if idxyaml in idxlst:
        return idxlst.index(idxyaml)
    else:
        return None

def extract_d22(sl,varalias,nID,sensor):
    """
    Extracting data of choice - reading sl from parse_d22
    CAUTION: 10min data is extracted for entire days only 00:00h - 23:50h
    Returns values of chosen variable (ts) and corresponding datetimes (dt)
    as type: np.array
    """
    print('Extracting data from parsed .d22-files')
    category = find_category_for_variable(varalias)
    revised_categories,idxlst = get_revised_categories(sl,category)
    print( 'Consistency check: \n'
           ' --> compare found #sensors against defined in insitu_specs.yaml')
    sensornr = len(insitu_dict[nID]['sensor'].keys())
    if len(revised_categories) == sensornr:
        print('Consistency check: OK!')
    else:
        print('Consistency check: Failed!')
        print(    '!!! Caution:\n'
                + 'found #sensor ('
                + str(len(revised_categories))
                + ') is not equal to defined ' +
                '#sensors ('
                + str(sensornr)
                + ') in insitu_specs.yaml')
    # check that the defined sensors are actually the ones being found
    check = check_sensor_availability(idxlst,nID,sensor)
    ts = []
    dt = []
    if check is not None:
        print('Sensor is available and defined in insitu_specs.yaml')
        for i, line in enumerate(sl):
            # get ts for date and time
            if "!!!!" in line:
                datestr = sl[  i
                             + d22_dict['datetime']['date']['idx']
                            ].strip()
                timestr = sl[  i
                             + d22_dict['datetime']['time']['idx']
                            ].strip()
                date_object = datetime.strptime(datestr
                                                + ' '
                                                + timestr,
                                                '%d-%m-%Y %H:%M')
                dt.append(date_object)
            # get ts for variable of interest
            revised_category_for_sensor = revised_categories[check]
            #print(revised_category_for_sensor)
            if revised_category_for_sensor in line:
                value = sl[  i
                            + d22_dict[category][varalias]['idx']
                           ].strip()
                ts.append(floater(value))
    else:
        print('Caution: Sensor is not defined or available')
    #Convert data to arrays
    dt = np.array(dt)
    ts = np.array(ts)
    # adjust conventions
    if ('convention' in d22_dict[category][varalias].keys() and
    d22_dict[category][varalias]['convention'] == 'meteorologic'):
        print('Convert from meteorologic to oceanographic convention')
        ts = convert_meteorologic_oceanographic(ts)
    return ts, dt

# --- help ------------------------------------------------------------#
if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="""
This module encompasses classes and methods to read and process wave
field related data from stations.\n
Usage:
from insitumod import insitu_class as sc
from datetime import datetime, timedelta
sc_obj = sc('ekofiskL',sdate,edate)
    """,
    formatter_class = RawTextHelpFormatter
    )
    args = parser.parse_args()

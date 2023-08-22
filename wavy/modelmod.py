#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------#
'''
The main task of this module is to acquire, read, and prepare
geophysical variables from model output files for further use.
'''
# --- import libraries ------------------------------------------------#
# standard library imports
import netCDF4
import numpy as np
from datetime import datetime, timedelta
import time
from functools import lru_cache
from tqdm import tqdm
import importlib.util
import dotenv
import os
import glob

import logging
#logging.basicConfig(level=logging.DEBUG)
logging.basicConfig(level=30)
logger = logging.getLogger(__name__)

# own imports
from wavy.utils import hour_rounder, make_fc_dates
from wavy.utils import finditem, parse_date, NoStdStreams
from wavy.utils import convert_meteorologic_oceanographic
from wavy.utils import date_dispatcher
from wavy.utils import find_direction_convention
from wavy.utils import flatten
from wavy.utils import make_pathtofile, make_subdict

from wavy.ncmod import check_if_ncfile_accessible
from wavy.ncmod import ncdumpMeta, get_filevarname

from wavy.wconfig import load_or_default

from wavy.quicklookmod import quicklook_class_sat as qls

from wavy.init_class_mod import init_class

# ---------------------------------------------------------------------#

def crop_to_period(ds, sd, ed):
    """
    Function to crop the dataset to a given period
    """
    ds_sliced = ds.sel(time=slice(sd, ed))
    return ds_sliced

def check_date(filelst, date):
    '''
    Checks if str in lst according to desired date (sd, ed)

    return: idx for file
    '''
    idx = []
    for i in range(len(filelst)):
        element = filelst[i]
        tmp = element.find(date.strftime('%Y%m%d'))
        if tmp >= 0:
            idx.append(i)
    if len(idx) <= 0:
        idx = [0]
    return idx[0], idx[-1]

def get_model_filedate(model, fc_date, leadtime):
    '''
    get init_date for latest model output file and checks if available

    param:
        model - modelname type(str)
        fc_date - datetime object
        leadtime - integer in hours

    return:
        suitable datetime to create model filename
    '''
    if ('init_times' in model_dict[model].keys()
            and model_dict[model]['init_times'] is not None):
        init_times = \
            np.array(model_dict[model]['init_times']).astype('float')
    else:
        print('init_times for chosen model not specified in config file')
        print('Assuming continuous simulation with hourly values')
        init_times = np.array(range(25)).astype('float')
    date = fc_date - timedelta(hours=leadtime)
    date_hour = hour_rounder(date).hour
    if date_hour in init_times:
        print('Leadtime', leadtime , \
              'available for date', fc_date)
        init_diffs = date_hour - init_times
        init_diffs[init_diffs < 0] = np.nan
        h_idx = np.where(init_diffs == \
                        np.min(init_diffs[~np.isnan(init_diffs)]))
        h = int(init_times[h_idx[0][0]])
        return datetime(date.year, date.month, date.day, h)
    else:
        #print('Leadtime', leadtime , \
        #      'not available for date' ,fc_date, '!')
        return False


def make_model_filename(model, fc_date, leadtime):
    """
    creates/returns filename based on fc_date,leadtime

        param:
        model - modelname type(str)
        fc_date - datetime object
        leadtime - integer in hours

    return:
        filename (consists of path + filename)

    comment:
            - special characters are escaped by adding "\\"
            - the escapes need to be removed for certain libraries
              like xarray and netCDF4
    """
    if model in model_dict:
        if 'xtra_h' in model_dict[model]:
            filedate = get_model_filedate(model, fc_date, leadtime)
            pathdate = filedate + timedelta(hours=leadtime) \
                                * model_dict[model]['lt_switch_p']
            tmpstr = model_dict[model]['file_template']
            for i in range(model_dict[model]['nr_filedates']):
                filedatestr = model_dict[model]['filedate_formats'][i]
                replacestr = (filedate \
                            + timedelta(hours = leadtime \
                                    - (leadtime % \
                                        model_dict[model]['init_step']))
                                    * model_dict[model]['lt_switch_f'][i]
                            + timedelta(hours = \
                                    model_dict[model]['xtra_h'][i])).\
                            strftime(filedatestr)
                tmpstr = tmpstr.replace('filedate', replacestr, 1)
            filename = (
                        pathdate.strftime(\
                            model_dict[model]['path_template'])
                        + tmpstr)
        else:
            filedate = get_model_filedate(model, fc_date, leadtime)
            filename =\
                (filedate.strftime(model_dict[model]\
                                   ['wavy_input']['src_tmplt'])\
                + filedate.strftime(model_dict[model]\
                                    ['wavy_input']['fl_tmplt']))
    else:
        raise ValueError("Chosen model is not specified in model_specs.yaml")
    # replace/escape special characters
    filename = filename.replace(" ", "\\ ")\
                       .replace("?", "\\?")\
                       .replace("&", "\\&")\
                       .replace("(", "\\(")\
                       .replace(")", "\\)")\
                       .replace("*", "\\*")\
                       .replace("<", "\\<")\
                       .replace(">", "\\>")
    return filename


def make_model_filename_wrapper(model, fc_date, leadtime, max_lt=None):
    """
    Wrapper function of make_model_filename. Organizes various cases.

    param:
        model - modelname type(str)
        fc_date - datetime object
        leadtime - integer in hours
        max_lt - maximum lead time allowed

    return:
        filename
    """
    if leadtime is None:
        leadtime = 'best'
    if (isinstance(fc_date, datetime) and leadtime != 'best'):
        filename = make_model_filename(model, fc_date, leadtime)
    elif (isinstance(fc_date, datetime) and leadtime == 'best'):
        switch = False
        leadtime = generate_bestguess_leadtime(model, fc_date)
        while switch is False:
            filename = make_model_filename(model, fc_date, leadtime)
            # check if file is accessible
            switch = check_if_ncfile_accessible(filename)
            if (switch is False):
                print("Desired file:", filename, " not accessible")
                print("Continue to look for date with extended leadtime")
                leadtime = leadtime + model_dict[model]['init_step']
            if max_lt is not None and leadtime > max_lt:
                print("Leadtime:", leadtime,
                      "is greater as maximum allowed leadtime:", max_lt)
                return None
    elif (isinstance(fc_date, list) and isinstance(leadtime, int)):
        filename = [make_model_filename(model, date, leadtime)
                    for date in fc_date]
    elif (isinstance(fc_date, list) and leadtime == 'best'):
        leadtime = generate_bestguess_leadtime(model, fc_date)
        filename = [make_model_filename(model, fc_date[i], leadtime[i])
                    for i in range(len(fc_date))]
    return filename

def make_list_of_model_filenames(model, fc_dates, lt):
    """
    return: flst - list of model files to be opened
            dlst - list of dates to be chosen within each file
    """
    #fn = make_model_filename_wrapper('mwam4',datetime(2021,1,1,1),1)
    flst = []
    for d in fc_dates:
        fn = make_model_filename_wrapper(model, d, lt)
        flst.append(fn)
    return flst

@lru_cache(maxsize=32)
def read_model_nc_output_lru(filestr, lonsname, latsname, timename):
    # remove escape character because netCDF4 handles white spaces
    # but cannot handle escape characters (apparently)
    filestr = filestr.replace('\\', '')
    f = netCDF4.Dataset(filestr, 'r')
    # get coordinates and time
    model_lons = f.variables[lonsname][:]
    model_lats = f.variables[latsname][:]
    model_time = f.variables[timename]
    model_time_dt = list(
        netCDF4.num2date(model_time[:], units=model_time.units))
    f.close()
    return model_lons, model_lats, model_time_dt

def read_model_nc_output(filestr, lonsname, latsname, timename):
    # remove escape character because netCDF4 handles white spaces
    # but cannot handle escape characters (apparently)
    filestr = filestr.replace('\\', '')
    f = netCDF4.Dataset(filestr, 'r')
    # get coordinates and time
    model_lons = f.variables[lonsname][:]
    model_lats = f.variables[latsname][:]
    model_time = f.variables[timename]
    model_time_dt = list(
        netCDF4.num2date(model_time[:], units=model_time.units))
    f.close()
    return model_lons, model_lats, model_time_dt

def read_unstr_model_nc_output(self, **kwargs):
    print('')
    print('Choosing reader..')
    # define reader
    dotenv.load_dotenv()
    WAVY_DIR = os.getenv('WAVY_DIR', None)
    if WAVY_DIR is None:
        print('###########')
        print('Environmental variable for WAVY_DIR needs to be defined!')
        print('###########')
    # read_ww3_unstructured
    reader_str = kwargs.get('reader', self.cfg.reader)
    reader_mod_str = WAVY_DIR + '/wavy/model_readers.py'
    spec = importlib.util.spec_from_file_location(
            'grid_readers.' + reader_str, reader_mod_str)

    # create reader module
    sat_reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sat_reader)

    # pick reader
    #reader = getattr(sat_reader, 'read_local_ncfiles')
    reader = getattr(sat_reader, reader_str)
    self.reader = reader
    print('Chosen reader:', spec.name)
    print('')

    # remove escape character because netCDF4 handles white spaces
    # but cannot handle escape characters (apparently)
    filestr=filestr.replace('\\', '')
    f = netCDF4.Dataset(filestr, 'r')
    # get coordinates and time
    model_lons = f.variables[lonsname][:]
    model_lats = f.variables[latsname][:]
    model_time = f.variables[timename]
    model_time_dt = list(
        netCDF4.num2date(model_time[:], units=model_time.units))
    f.close()
    return model_lons, model_lats, model_time_dt

def get_model_fc_mode(filestr, model, fc_date, varalias=None, **kwargs):
    """
    fct to retrieve model data for correct time
    """
    vardict = {}
    print("Get model data according to selected date(s) ....")
    print(filestr)
    meta = ncdumpMeta(filestr)
    stdvarname = variable_def[varalias]['standard_name']
    lonsname = get_filevarname('lons', variable_def,
                               model_dict[model], meta)
    latsname = get_filevarname('lats', variable_def,
                               model_dict[model], meta)
    timename = get_filevarname('time', variable_def,
                               model_dict[model], meta)
    # get other variables e.g. Hs [time,lat,lon]
    filevarname = get_filevarname(varalias, variable_def,
                                  model_dict[model], meta)
    try:
        model_lons, model_lats, model_time_dt = \
        read_model_nc_output_lru(filestr, lonsname, latsname, timename)
    except Exception as e:
        print(e)
        print('continue with uncached retrieval')
        model_lons, model_lats, model_time_dt = \
        read_model_nc_output(filestr, lonsname, latsname, timename)

    vardict[variable_def['lons']['standard_name']] = model_lons
    vardict[variable_def['lats']['standard_name']] = model_lats

    # remove escape character because netCDF4 handles white spaces
    # but cannot handle escape characters (apparently)
    filestr = filestr.replace('\\', '')
    f = netCDF4.Dataset(filestr, 'r')
    model_time = f.variables[timename]
    l = kwargs.get('vertical_level', 0)
    if (type(filevarname) is dict):
        print(
            'Target variable can be computed from vector \n'
            'components with the following aliases: ', filevarname)
        model_time_dt_valid = model_time_dt[model_time_dt.index(fc_date)]
        model_time_valid = float(model_time[model_time_dt.index(fc_date)])
        model_time_unit = model_time.units
        vardict[variable_def['time']['standard_name']] = model_time_valid
        vardict['datetime'] = model_time_dt_valid
        vardict['time_unit'] = model_time_unit
        for key in filevarname.keys():
            filevarname_dummy = get_filevarname(
                                    filevarname[key][0],
                                    variable_def,
                                    model_dict[model], meta)
            if filevarname_dummy is not None:
                print(filevarname[key][0], 'exists')
                break
        print('Use aliases:', filevarname[key])
        model_var_dummy = f.variables[filevarname_dummy]
        if len(model_var_dummy.dimensions) == 4:
            model_var_dummy = model_var_dummy[:, l, :, :].squeeze()
        if len(model_var_dummy.shape) == 3:  # for multiple time steps
            model_var_valid_tmp = \
                model_var_dummy[model_time_dt.index(fc_date), :, :]\
                .squeeze()**2
            for i in range(1, len(filevarname[key])):
                filevarname_dummy = get_filevarname(
                                        filevarname[key][i],
                                        variable_def,
                                        model_dict[model], meta)
                if len(f.variables[filevarname_dummy].dimensions) == 4:
                    model_var_valid_tmp += \
                        f.variables[filevarname_dummy][
                            model_time_dt.index(fc_date), l, :, :
                            ].squeeze()**2
                elif len(f.variables[filevarname_dummy].dimensions) == 3:
                    model_var_valid_tmp += \
                        f.variables[filevarname_dummy][
                            model_time_dt.index(fc_date), :, :
                            ].squeeze()**2
            model_var_valid = np.sqrt(model_var_valid_tmp)
        elif len(model_var_dummy.dimensions) == 2:
            model_var_valid_tmp = model_var_dummy[:, :]**2
            for i in range(1, len(filevarname[key])):
                filevarname_dummy = get_filevarname(
                                            filevarname[key][i],
                                            variable_def,
                                            model_dict[model],
                                            meta)
                model_var_valid_tmp += \
                    f.variables[filevarname_dummy][:, :]**2
            model_var_valid = np.sqrt(model_var_valid_tmp)
        else:
            print('Dimension mismatch!')
        vardict[stdvarname] = model_var_valid
    else:
        model_time_dt_valid = model_time_dt[model_time_dt.index(fc_date)]
        model_time_valid = float(model_time[model_time_dt.index(fc_date)])
        model_time_unit = model_time.units
        vardict[variable_def['time']['standard_name']] = model_time_valid
        vardict['datetime'] = model_time_dt_valid
        vardict['time_unit'] = model_time_unit
        model_var_link = f.variables[filevarname]
        if len(model_var_link.dimensions) == 4:
            model_var_link = model_var_link[:, l, :, :].squeeze()
        if len(model_var_link.shape) == 3:  # for multiple time steps
            model_var_valid = \
                model_var_link[model_time_dt.index(fc_date), :, :].squeeze()
        elif len(model_var_link.dimensions) == 2:
            model_var_valid = model_var_link[:, :].squeeze()
        else:
            print('Dimension mismatch!')
        vardict[variable_def[varalias]['standard_name']] = \
                                                    model_var_valid
    # transform masked array to numpy array with NaNs
    f.close()
    vardict['longitude'] = vardict['longitude'].filled(np.nan)
    vardict['latitude'] = vardict['latitude'].filled(np.nan)
    vardict[variable_def[varalias]['standard_name']] = \
        vardict[variable_def[varalias]['standard_name']].filled(np.nan)
    vardict['meta'] = meta
    # make lats,lons 2D if only 1D (regular grid)
    if len(vardict['longitude'].shape) == 1:
        LATS, LONS = np.meshgrid(vardict['latitude'],
                                vardict['longitude'])
        vardict['longitude'] = np.transpose(LONS)
        vardict['latitude'] = np.transpose(LATS)
    return vardict, filevarname


def generate_bestguess_leadtime(model, fc_date, lidx=None):
    """
    fct to return leadtimes for bestguess
    """
    if isinstance(fc_date, list):
        leadtime = \
            [generate_bestguess_leadtime(model, date) for date in fc_date]
    else:
        init_times = \
            np.array(model_dict[model]['misc']['init_times']).astype('float')
        diffs = fc_date.hour - np.array(init_times)
        gtz = diffs[diffs >= 0]
        if len(gtz) == 0:
            leadtime = int(np.abs(np.min(np.abs(diffs))
                                - model_dict[model]['misc']['init_step']))
        elif (len(gtz) > 0 and lidx is not None):
            leadtime = int(np.sort(diffs[diffs >= 0])[lidx])
        else:
            leadtime = int(np.min(diffs[diffs >= 0]))
    return leadtime

def get_model(model=None,
              sdate=None,
              edate=None,
              date_incr=None,
              fc_date=None,
              leadtime=None,
              varalias=None,
              st_obj=None,
              transform_lons=None):
    """
    toplevel function to get model data
    """
    if st_obj is not None:
        sdate = st_obj.sdate
        edate = st_obj.edate
        varalias = st_obj.varalias
    if (sdate is not None
        and edate is not None
        and date_incr is not None):
        fc_date = make_fc_dates(sdate, edate, date_incr)
    filestr = make_model_filename_wrapper(model=model,
                                          fc_date=fc_date,
                                          leadtime=leadtime)
    #filestr_lst = make_list_of_model_filenames(model, fc_date, lt)
    if (isinstance(filestr, list) and st_obj is None):
        vardict, \
        filevarname = get_model_fc_mode(filestr=filestr[0], model=model,
                                    fc_date=fc_date[0], varalias=varalias)
        vardict[variable_def[varalias]['standard_name']] = \
                    [vardict[variable_def[varalias]['standard_name']]]
        vardict['time'] = [vardict['time']]
        vardict['datetime'] = [vardict['datetime']]
        vardict['leadtime'] = leadtime
        for i in tqdm(range(1, len(filestr))):
            tmpdict, \
            filevarname = get_model_fc_mode(
                            filestr=filestr[i], model=model,
                            fc_date=fc_date[i], varalias=varalias)
            vardict[variable_def[varalias]['standard_name']].append(
                tmpdict[variable_def[varalias]['standard_name']])
            vardict['time'].append(tmpdict['time'])
            vardict['datetime'].append(tmpdict['datetime'])
        vardict[variable_def[varalias]['standard_name']] =\
            np.array(vardict[variable_def[varalias]['standard_name']])
    else:
        vardict, \
        filevarname = get_model_fc_mode(filestr=filestr, model=model,
                                    fc_date=fc_date, varalias=varalias)
        vardict['time'] = [vardict['time']]
        vardict['datetime'] = [vardict['datetime']]
        vardict['leadtime'] = leadtime
    # transform to datetime
    with NoStdStreams():
        tmpd = [parse_date(str(d)) for d in vardict['datetime']]
    vardict['datetime'] = tmpd
    del tmpd
    if transform_lons==180:
        # transform longitudes from -180 to 180
        vardict['longitude'] = ((vardict['longitude'] - 180) % 360) - 180
    elif transform_lons==360:
        print('not yet implemented !!')
    # adjust conventions
    # check if variable is one with conventions
    if 'convention' in variable_def[varalias].keys():
        convention_set = False
        print('Chosen variable is defined with conventions')
        print('... checking if correct convention is used ...')
        # 1. check if clear from standard_name
        file_stdvarname = find_direction_convention(filevarname,vardict['meta'])
        if "to_direction" in file_stdvarname:
            print('Convert from oceanographic to meteorologic convention')
            vardict[variable_def[varalias]['standard_name']] = \
                    convert_meteorologic_oceanographic(\
                        vardict[variable_def[varalias]['standard_name']])
            convention_set = True
        elif "from_direction" in file_stdvarname:
            print('standard_name indicates meteorologic convention')
            convention_set = True
            pass
        # 2. overwrite convention from config file
        if ('convention' in model_dict[model].keys() and
        model_dict[model]['convention'] == 'oceanographic' and
        convention_set is False):
            print('Convention is set in config file')
            print('This will overwrite conventions from standard_name in file!')
            print('\n')
            print('Convert from oceanographic to meteorologic convention')
            vardict[variable_def[varalias]['standard_name']] = \
                    convert_meteorologic_oceanographic(\
                        vardict[variable_def[varalias]['standard_name']])
            convention_set = True
    return vardict, fc_date, leadtime, filestr, filevarname


# ---------------------------------------------------------------------#

# read yaml config files:
model_dict = load_or_default('model_cfg.yaml')
variable_def = load_or_default('variable_def.yaml')


class model_class(qls):
    '''
    class to read and process model data
    model: e.g. Hs[time,lat,lon], lat[rlat,rlon], lon[rlat,rlon]
    This class should communicate with the satellite, model, and
    station classes.
    '''
    def __init__(self, **kwargs):
        print('# ----- ')
        print(" ### Initializing model_class object ###")
        print(" ")
        print(" Given kwargs:")
        print(kwargs)

        # initializing useful attributes from config file
        dc = init_class('model', kwargs.get('nID'))
        # parse and translate date input
        self.sd = parse_date(kwargs.get('sd'))
        self.ed = parse_date(kwargs.get('ed', self.sd))
        print('Chosen period: ' + str(self.sd) + ' - ' + str(self.ed))

        # add other class object variables
        self.nID = kwargs.get('nID')
        self.varalias = kwargs.get('varalias', 'Hs')
        self.units = variable_def[self.varalias].get('units')
        self.stdvarname = variable_def[self.varalias].get('standard_name')
        self.distlim = kwargs.get('distlim', 6)
        self.filter = kwargs.get('filter', False)
        self.region = kwargs.get('region', 'global')
        self.leadtime = kwargs.get('leadtime', 'best')
        self.cfg = dc

        print(" ")
        print(" ### model_class object initialized ### ")
        print('# ----- ')


    def get_item_parent(self, item, attr):
        """
        Offers possibility to explore netcdf meta info.
        by specifying what you are looking for (item),
        e.g. part of a string, and in which attribute (attr),
        e.g. standard_name, this function returns the
        parent parameter name of the query string.

        param:
            item - (partial) string e.g. [m]
            attr - attribute e.g. units

        return: list of matching parameter strings

        e.g. for satellite_class object sco:

        .. code ::

            sco.get_item_parent('m','units')
        """

        lst = [i for i in self.meta.keys()
               if (attr in self.meta[i].keys()
               and item in self.meta[i][attr])
               ]
        if len(lst) >= 1:
            return lst
        else:
            return None

    def get_item_child(self, item):
        """
        Gets all attributes connected to given parameter name.

        param:
            item - (partial) string e.g. [m]

        return: matching parameter string

        e.g. for satellite_class object sco:

        .. code ::

            sco.get_item_child('time')
        """

        parent = finditem(self.meta, item)
        return parent

    def _get_files(self, dict_for_sub=None, path=None, wavy_path=None):
        """
        Function to retrieve list of files/paths for available
        locally stored data. This list is used for other functions
        to query and parsing.

        param:
            sd - start date (datetime object)
            ed - end date (datetime object)
            nID - nID as of model_cfg.yaml
            dict_for_sub - dictionary for substitution in templates
            path - a path if defined

        return:
            pathlst - list of paths
            filelst - list of files
        """
        filelst = []
        pathlst = []
        tmpdate = self.sd
        if wavy_path is not None:
            pathtotals = [wavy_path]
            filelst = [wavy_path]
        elif path is None:
            print('path is None -> checking config file')
            while (tmpdate <= date_dispatcher(self.ed,
            self.cfg.misc['date_incr_unit'], self.cfg.misc['date_incr'])):
                try:
                    # create local path for each time
                    path_template = \
                            model_dict[self.nID]['wavy_input'].get(
                                                  'src_tmplt')
                    strsublst = \
                        model_dict[self.nID]['wavy_input'].get('strsub')
                    subdict = \
                        make_subdict(strsublst,
                                     class_object_dict=dict_for_sub)
                    path = make_pathtofile(path_template,
                                           strsublst, subdict)
                    path = tmpdate.strftime(path)
                    if os.path.isdir(path):
                        tmplst = np.sort(os.listdir(path))
                        filelst.append(tmplst)
                        pathlst.append([os.path.join(path, e)
                                        for e in tmplst])
                    path = None
                except Exception as e:
                    logger.exception(e)
                tmpdate = date_dispatcher(tmpdate,
                            self.cfg.misc['date_incr_unit'],
                            self.cfg.misc['date_incr'])
            filelst = np.sort(flatten(filelst))
            pathlst = np.sort(flatten(pathlst))
            pathtotals = [pathlst]

            # limit to sd and ed based on file naming, see check_date
            idx_start, tmp = check_date(filelst, self.sd)
            tmp, idx_end = check_date(filelst, self.ed)
            if idx_end == 0:
                idx_end = len(pathlst)-1
            del tmp
            pathtotals = np.unique(pathtotals[idx_start:idx_end+1])
            filelst = np.unique(filelst[idx_start:idx_end+1])

        else:
            if os.path.isdir(path):
                pathlst = glob.glob(path+'/*')
            else:
                pathlst = glob.glob(path+'*')
            #
            # interesting other approach using pathlibs glob
            # https://stackoverflow.com/questions/3348753/\
            #        search-for-a-file-using-a-wildcard
            # from pathlib import Path
            # filelst = [p.name for p in Path(path).glob("*")]
            # pathlst = [str(p.parent) for p in Path(path).glob("*")]
            #
            # separate files from path
            filelst = [p.split('/')[-1] for p in pathlst]
            pathlst = [p[0:-len(f)] for p, f in zip(pathlst, filelst)]
            pathtotals = [os.path.join(p, f) for p, f in zip(pathlst, filelst)]

            # limit to sd and ed based on file naming, see check_date
            idx_start, tmp = check_date(filelst, self.sd)
            tmp, idx_end = check_date(filelst, self.ed)
            if idx_end == 0:
                idx_end = len(pathlst)-1
            del tmp
            pathtotals = np.unique(pathtotals[idx_start:idx_end+1])
            filelst = np.unique(filelst[idx_start:idx_end+1])
        print(str(int(len(pathtotals))) + " valid files found")
        return pathtotals, filelst

    def list_input_files(self, show=False, **kwargs):

        if (kwargs.get('path') is None and kwargs.get('wavy_path') is None):
            fc_dates = make_fc_dates(self.sd, self.ed,
                                     self.cfg.misc['date_incr'])
            pathlst = make_list_of_model_filenames(self.nID,
                        fc_dates, self.leadtime)

        else:
            # if defined path local
            print(" ## Find and list files ...")
            path = kwargs.get('path', None)
            wavy_path = kwargs.get('wavy_path', None)
            pathlst, _ = self._get_files(vars(self),
                                         path=path,
                                         wavy_path=wavy_path)

        if show is True:
            print(" ")
            print(pathlst)
            print(" ")
        return pathlst

    def _get_model(self, **kwargs):
        """
        Main function to obtain data from satellite missions.
        reads files, apply region and temporal filter

        return: adjusted dictionary according to spatial and
                temporal constraints
        """

        # retrieve dataset
        ds = self.reader(fc_dates=kwargs.get('fc_dates'), **(vars(self)))
        self.vars = ds
        self.coords = list(self.vars.coords)
        return self

    @staticmethod
    def _enforce_longitude_format(ds):
        # adjust longitude -180/180
        attrs = ds.lons.attrs
        attrs['valid_min'] = -180
        attrs['valid_max'] = 180
        attrs['comments'] = 'forced to range: -180 to 180'
        ds.lons.values = ((ds.lons.values-180) % 360)-180
        return ds

    def _enforce_meteorologic_convention(self):
        ncvars = list(self.vars.variables)
        for ncvar in ncvars:
            if ('convention' in model_dict[self.nID].keys() and
            model_dict[self.nID]['convention'] == 'oceanographic'):
                print('Convert from oceanographic to meteorologic convention')
                self.vars[ncvar] =\
                    convert_meteorologic_oceanographic(self.vars[ncvar])
            elif 'to_direction' in self.vars[ncvar].attrs['standard_name']:
                print('Convert from oceanographic to meteorologic convention')
                self.vars[ncvar] =\
                    convert_meteorologic_oceanographic(self.vars[ncvar])

        return self

    def _change_varname_to_aliases(self):
        # variables
        ncvar = get_filevarname(self.varalias, variable_def,
                                model_dict[self.nID], self.meta)
        self.vars = self.vars.rename({ncvar: self.varalias})
        # coords
        coords = ['time', 'lons', 'lats']
        for c in coords:
            ncvar = get_filevarname(c, variable_def,
                                    model_dict[self.nID], self.meta)
            self.vars = self.vars.rename({ncvar: c}).set_index(time='time')
        return self

    def _change_stdvarname_to_cfname(self):
        # enforce standard_name for coordinate aliases
        self.vars['lons'].attrs['standard_name'] = \
            variable_def['lons'].get('standard_name')
        self.vars['lats'].attrs['standard_name'] = \
            variable_def['lats'].get('standard_name')
        self.vars['time'].attrs['standard_name'] = \
            variable_def['time'].get('standard_name')
        # enforce standard_name for variable alias
        self.vars[self.varalias].attrs['standard_name'] = \
            self.stdvarname
        return self

    def populate(self, **kwargs):
        print(" ### Read files and populate model_class object")

        fc_dates = make_fc_dates(self.sd, self.ed,
                                 self.cfg.misc['date_incr'])

        self.pathlst = self.list_input_files(**kwargs)

        print('')
        print('Checking variables..')
        self.meta = ncdumpMeta(self.pathlst[0])
        ncvar = get_filevarname(self.varalias, variable_def,
                                model_dict[self.nID], self.meta)
        print('')
        print('Choosing reader..')
        # define reader
        dotenv.load_dotenv()
        WAVY_DIR = os.getenv('WAVY_DIR', None)
        if WAVY_DIR is None:
            print('###########')
            print('Environmental variable for WAVY_DIR needs to be defined!')
            print('###########')
        reader_str = kwargs.get('reader', self.cfg.reader)
        reader_mod_str = WAVY_DIR + '/wavy/model_readers.py'
        spec = importlib.util.spec_from_file_location(
                'model_readers.' + reader_str, reader_mod_str)

        # create reader module
        reader_tmp = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(reader_tmp)

        # pick reader
        reader = getattr(reader_tmp, reader_str)
        self.reader = reader
        print('Chosen reader:', spec.name)
        print('')

        # possible to select list of variables
        self.varname = ncvar

        kwargs['fc_dates'] = fc_dates

        if len(self.pathlst) > 0:
            try:
                t0 = time.time()
                print('Reading..')
                self = self._get_model(**kwargs)

                self = self._change_varname_to_aliases()
                self = self._change_stdvarname_to_cfname()
                self = self._enforce_meteorologic_convention()

                # convert longitude
                ds = self.vars
                ds_new = self._enforce_longitude_format(ds)
                self.vars = ds_new

                # adjust varalias if other return_var
                if kwargs.get('return_var') is not None:
                    newvaralias = kwargs.get('return_var')
                else:
                    newvaralias = self.varalias

                # define more class object variables
                if kwargs.get('return_var') is not None:
                    self.varalias = kwargs.get('return_var')
                    self.stdvarname = \
                        variable_def[newvaralias].get('standard_name')
                    self.units = variable_def[newvaralias].get('units')
                # create label for plotting
                t1 = time.time()
                print(" ")
                print(' ## Summary:')
                print(str(len(self.vars['time'])) + " time steps retrieved.")
                print("Time used for retrieving data:")
                print(round(t1-t0, 2), "seconds")
                print(" ")
                print(" ### model_class object populated ###")
                print('# ----- ')
            except Exception as e:
                logger.exception(e)
                #logger.debug(traceback.format_exc())
                print(e)
                print('Error encountered')
                print('model_class object not populated')
        else:
            print('No data data found')
            print('model_class object not populated')
            print('# ----- ')
        return self

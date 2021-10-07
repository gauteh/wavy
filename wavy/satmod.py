#!/usr/bin/env python
# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------#
'''
This module encompasses classes and methods to read and process wave
field related data from satellites. I try to mostly follow the PEP
convention for python code style. Constructive comments on style and
effecient programming are most welcome!
'''
# --- import libraries ------------------------------------------------#
# standard library imports
import sys
import numpy as np
from datetime import datetime, timedelta
import datetime as dt
import argparse
from argparse import RawTextHelpFormatter
import os
from copy import deepcopy
import yaml
import time
if sys.version_info <= (3, 0):
    from urllib import urlretrieve, urlcleanup # python2
else:
    from urllib.request import urlretrieve, urlcleanup # python3
import ftplib
from ftplib import FTP
import netCDF4 as netCDF4
import calendar
from dateutil.relativedelta import relativedelta
from joblib import Parallel, delayed
import xarray as xa
import pyresample
import pyproj
from dotenv import load_dotenv
import zipfile
import tempfile

# own imports
from wavy.ncmod import ncdumpMeta
from wavy.ncmod import get_varname_for_cf_stdname_in_ncfile
from wavy.ncmod import find_attr_in_nc, dumptonc_ts_sat
from wavy.utils import progress, sort_files, collocate_times
from wavy.utils import make_pathtofile,make_subdict
from wavy.utils import finditem
from wavy.credentials import get_credentials
from wavy.modelmod import get_filevarname
from wavy.modelmod import model_class as mc
from wavy.modelmod import make_model_filename_wrapper
from wavy.wconfig import load_or_default
from wavy.filtermod import filter_main,vardict_unique
from wavy.filtermod import rm_nan_from_vardict
# ---------------------------------------------------------------------#

# read yaml config files:
region_dict = load_or_default('region_specs.yaml')
model_dict = load_or_default('model_specs.yaml')
satellite_dict = load_or_default('satellite_specs.yaml')
variable_info = load_or_default('variable_info.yaml')

# --- global functions ------------------------------------------------#

def tmploop_get_remote_files(i,matching,user,pw,
                            server,remote_path,
                            path_local):
    #for element in matching:
    print("File: ",matching[i])
    dlstr=('ftp://' + user + ':' + pw + '@'
                + server + remote_path + matching[i])
    for attempt in range(10):
        print ("Attempt to download data: ")
        try:
            print ("Downloading file")
            urlretrieve(dlstr, os.path.join(path_local, matching[i]))
            urlcleanup()
        except Exception as e:
            print (e.__doc__)
            print (e.message)
            print ("Waiting for 10 sec and retry")
            time.sleep(10)
        else:
            break
    else:
        print ('An error was raised and I ' +
              'failed to fix problem myself :(')
        print ('Exit program')
        sys.exit()

def get_remote_files_cmems(\
sdate,edate,twin,nproc,sat,level,provider,path_local,dict_for_sub):
    '''
    Download swath files from CMEMS and store them at defined
    location. Time stamps in file name stand for:

    from, to, creation
    '''
    # credentials
    server = satellite_dict[provider][level]['src']['server']
    user, pw = get_credentials(remoteHostName = server)
    tmpdate = deepcopy(sdate)
    filesort = False
    while (tmpdate <= edate):
        # create remote path
        path_template = satellite_dict[provider][level]['src']\
                                      ['path_template']
        strsublst = satellite_dict[provider][level]['src']\
                                  ['strsub']
        subdict = make_subdict(strsublst,class_object_dict=dict_for_sub)
        path_remote = make_pathtofile(path_template,\
                                      strsublst,subdict,\
                                      date=tmpdate)
        if path_local is None:
            # create local path
            path_template = satellite_dict[provider][level]['dst']\
                                          ['path_template']
            strsublst = satellite_dict[provider][level]['dst']\
                                      ['strsub']
            path_local = make_pathtofile(path_template,\
                                     strsublst,subdict,\
                                     date=sdate)
            filesort = True
        print ('# ----- ')
        print ('Chosen source: ')
        print (sat + ' values from ' + provider + ': ' + server)
        print ('# ----- ')
        # get list of accessable files
        ftp = FTP(server)
        ftp.login(user, pw)
        ftp.cwd(path_remote)
        content=FTP.nlst(ftp)
        #choose files according to sdate/edate
        tmplst=[]
        tmpdate_new = tmpdate-timedelta(minutes=twin)
        tmpdate_end = edate+timedelta(minutes=twin)
        while (tmpdate_new <= tmpdate_end):
            matchingtmp = [s for s in content
                            if tmpdate_new.strftime('%Y%m%dT%H')
                            in s ]
            tmplst = tmplst + matchingtmp
            tmpdate_new = tmpdate_new + timedelta(minutes=twin)
        matching = np.unique(tmplst)
        # check if download path exists if not create
        if not os.path.exists(path_local):
            cmd = 'mkdir -p ' + path_local
            os.system(cmd)
        # Download matching files
        print ('Downloading ' + str(len(matching))
                + ' files: .... \n')
        print ("Used number of simultaneous downloads "
                + str(nproc) + "!")
        Parallel(n_jobs=nproc)(
                        delayed(tmploop_get_remote_files)(
                        i,matching,user,pw,server,
                        path_remote,path_local
                        ) for i in range(len(matching))
                        )
        # update time
        tmpdate = datetime((tmpdate + relativedelta(months=+1)).year,
                            (tmpdate + relativedelta(months=+1)).month,1)
    if filesort is True:
        # sort files
        print("Data is being sorted into subdirectories " \
            + "year and month ...")
        filelst = [f for f in os.listdir(path_local)
                    if os.path.isfile(os.path.join(path_local,f))]
        sort_files(path_local,filelst,provider,sat)
    print ('Files downloaded to: \n', path_local)

def get_remote_files_cci(\
sdate,edate,twin,nproc,sat,level,provider,path_local,dict_for_sub):
    '''
    Download swath files from CCI and store them at defined
    location. Time stamps in file name stand for:

    from, to, creation
    '''
    # credentials
    server = satellite_dict[provider][level]['src']['server']
    user, pw = get_credentials(remoteHostName = server)
    tmpdate = deepcopy(sdate)
    filesort = False
    while (tmpdate <= edate):
        print(tmpdate)
        # create remote path
        path_template = satellite_dict[provider][level]['src']\
                                      ['path_template']
        strsublst = satellite_dict[provider][level]['src']\
                                  ['strsub']
        dict_for_sub['mission'] =\
                        satellite_dict[provider][level]['mission'][sat]
        subdict = make_subdict(strsublst,class_object_dict=dict_for_sub)
        path_remote = make_pathtofile(path_template,\
                                      strsublst,subdict,\
                                      date=tmpdate)
        if path_local is None:
            # create local path
            subdict['mission'] = sat
            path_template = satellite_dict[provider][level]['dst']\
                                          ['path_template']
            strsublst = satellite_dict[provider][level]['dst']\
                                      ['strsub']
            path_local = make_pathtofile(path_template,\
                                     strsublst,subdict,\
                                     date=sdate)
            filesort = True
        print ('# ----- ')
        print ('Chosen source: ')
        print (sat + ' values from ' + provider + ': ' + server)
        print ('# ----- ')
        # get list of accessable files
        ftp = FTP(server)
        ftp.login(user, pw)
        ftp.cwd(path_remote)
        content = FTP.nlst(ftp)
        #choose files according to sdate/edate
        tmplst = []
        tmpdate_new = tmpdate-timedelta(minutes=twin)
        tmpdate_end = edate+timedelta(minutes=twin)
        while (tmpdate_new <= tmpdate_end):
            if level == 'L2P':
                matchingtmp = [s for s in content
                            if tmpdate_new.strftime('-%Y%m%dT%H')
                            in s ]
            elif level == 'L3':
                matchingtmp = [s for s in content
                            if tmpdate_new.strftime('-%Y%m%d')
                            in s ]
            tmplst = tmplst + matchingtmp
            tmpdate_new = tmpdate_new + timedelta(minutes=twin)
        matching = np.unique(tmplst)
        # check if download path exists if not create
        if not os.path.exists(path_local):
            cmd = 'mkdir -p ' + path_local
            os.system(cmd)
        # Download matching files
        print ('Downloading ' + str(len(matching))
                + ' files: .... \n')
        print ("Used number of simultaneous downloads "
                + str(nproc) + "!")
        Parallel(n_jobs=nproc)(
                        delayed(tmploop_get_remote_files)(
                        i,matching,user,pw,server,
                        path_remote,path_local
                        ) for i in range(len(matching))
                        )
        # update time
        tmpdate += timedelta(days=1)
    if filesort is True:
        # sort files
        print("Data is being sorted into subdirectories " \
            + "year and month ...")
        print(path_local)
        filelst = [f for f in os.listdir(path_local)
                    if os.path.isfile(os.path.join(path_local,f))]
        sort_files(path_local,filelst,provider,sat)
    print ('Files downloaded to: \n', path_local)

def get_remote_files_eumetsat(\
provider,sdate,edate,api_url,sat,level,path_local,dict_for_sub):
    '''
    Download swath files from EUMETSAT and store them at defined
    location. This fct uses the SentinelAPI for queries.
    '''
    import sentinelsat as ss
    products = None
    dates = (sdate.strftime('%Y-%m-%dT%H:%M:%SZ'),\
             edate.strftime('%Y-%m-%dT%H:%M:%SZ'))
    filessort = False
    if path_local is None:
        # create local path
        path_template = satellite_dict[provider][level]['dst']\
                                      ['path_template']
        strsublst = satellite_dict[provider][level]['dst']\
                                  ['strsub']
        subdict = make_subdict(strsublst,
                               class_object_dict=dict_for_sub)
        path_local = make_pathtofile(path_template,\
                                     strsublst,
                                     subdict,\
                                     date=sdate)
        filesort = True
    kwargs = make_query_dict(provider,sat)
    if api_url is None:
        api_url_lst = \
            satellite_dict[provider][level]['src']['api_url']
        for url in api_url_lst:
            print('Source:',url)
            try:
                user, pw = get_credentials(remoteHostName=url)
                api = ss.SentinelAPI(user, pw, url)
                products = api.query(area=None, date=dates,**kwargs)
                break
            except Exception as e:
                if isinstance(e,ss.exceptions.ServerError):
                    print(e)
    else:
        user, pw = get_credentials(remoteHostName = api_url)
        api = ss.SentinelAPI(user, pw, api_url)
        products = api.query(area=None, date=dates,**kwargs)
    if products is not None:
        # check if download path exists if not create
        if not os.path.exists(path_local):
            cmd = 'mkdir -p ' + path_local
            os.system(cmd)
        api.download_all(products,directory_path=path_local)
        #api.download(product_id)
    else: print('No products found!')
    if filesort is True:
        # sort files
        print("Data is being sorted into subdirectories " \
            + "year and month ...")
        filelst = [f for f in os.listdir(path_local)
                    if os.path.isfile(os.path.join(path_local,f))]
        sort_files(path_local,filelst,provider,sat)
    print ('Files downloaded to: \n', path_local)

def get_remote_files(path_local,sdate,edate,twin,
                    nproc,provider,api_url,sat,level,
                    dict_for_sub):
    '''
    Download swath files and store them at defined location.
    It is currently possible to download L3 altimeter data from
    CMEMS and L2 from EUMETSAT.
    '''
    if provider=='cmems':
        get_remote_files_cmems(sdate,edate,twin,nproc,\
                               sat,level,provider,path_local,\
                               dict_for_sub)
    elif provider=='eumetsat':
        get_remote_files_eumetsat(provider,sdate,edate,\
                                  api_url,sat,level,path_local,\
                                  dict_for_sub)
    elif provider=='cci':
        get_remote_files_cci(sdate,edate,twin,nproc,\
                               sat,level,provider,path_local,\
                               dict_for_sub)

def make_query_dict(provider,sat):
    '''
    fct to setup queries of L2 data using SentinelAPI
    '''
    SAT = satellite_dict[provider][level]['mission'][sat]
    kwargs =  {'platformname': 'Sentinel-3',
               'instrumentshortname': 'SRAL',
               'productlevel': 'L2',
               'filename': SAT + '*WAT*'}
    return kwargs

def get_local_files(sdate,edate,twin,provider,sat,level,
dict_for_sub,path_local=None):
    filelst = []
    pathlst = []
    tmpdate = sdate-timedelta(minutes=twin)
    tmpdate_s = datetime(tmpdate.year,tmpdate.month,1)
    if path_local is None:
        while (tmpdate <= edate + relativedelta(months=+1)):
            try:
                print(tmpdate)
                print('path_local is None -> checking config file')
                # create local path
                path_template = satellite_dict[provider][level]\
                                              ['dst']\
                                              ['path_template']
                strsublst = satellite_dict[provider][level]\
                                          ['dst']\
                                          ['strsub']
                subdict = make_subdict(strsublst,
                                       class_object_dict=dict_for_sub)
                path_local = make_pathtofile(path_template,\
                                             strsublst,subdict)
                path_local = (
                            os.path.join(
                            path_local,
                            tmpdate.strftime('%Y'),
                            tmpdate.strftime('%m'))
                            )
                print(path_local)
                tmplst = np.sort(os.listdir(path_local))
                filelst.append(tmplst)
                pathlst.append([os.path.join(path_local,e) for e in tmplst])
                tmpdate = tmpdate + relativedelta(months=+1)
                path_local = None
            except Exception as e:
                print(e)
                tmpdate = tmpdate + relativedelta(months=+1)
        filelst = np.sort(flatten(filelst))
        pathlst = np.sort(flatten(pathlst))
    else:
        filelst = np.sort(os.listdir(path_local))
        pathlst = [os.path.join(path_local,e) for e in filelst]
    idx_start,tmp = check_date(filelst,sdate-timedelta(minutes=twin))
    tmp,idx_end = check_date(filelst,edate+timedelta(minutes=twin))
    del tmp
    pathlst = np.unique(pathlst[idx_start:idx_end+1])
    filelst = np.unique(filelst[idx_start:idx_end+1])
    print (str(int(len(pathlst))) + " valid files found")
    return pathlst, filelst

def read_local_files_cmems(pathlst,provider,varalias,level):
    '''
    Read and concatenate all data to one timeseries for each variable.
    Fct is tailored to CMEMS files.
    '''
    # --- open file and read variables --- #
    varlst = [varalias] + ['lons','lats','time']
    varlst_cf = []
    for var in varlst:
        varlst_cf.append(variable_info[var]['standard_name'])
    count = 0
    print ("Processing " + str(int(len(pathlst))) + " files")
    print (pathlst[0])
    print (pathlst[-1])
    vardict = {}
    for element in pathlst:
        progress(count,str(int(len(pathlst))),'')
        stdname_lst = []
        try:
            # file includes a 1-D dataset with dimension time
            f = netCDF4.Dataset(element,'r')
            ncvars = [v for v in f.variables]
            for ncvar in ncvars:
                stdname = f.variables[ncvar].getncattr('standard_name')
                if stdname in varlst_cf:
                    if stdname in vardict:
                        if stdname in stdname_lst:
                            print("Caution: variable " +
                                    "standard_name is not unique !!!")
                            if satellite_dict[provider][level] \
                            ['vardef'] is not None:
                                tmp_varalias = varlst[\
                                                varlst_cf.index(stdname)]
                                if tmp_varalias in \
                                satellite_dict\
                                [provider][level]['vardef']:
                                    print( "As defined in "
                                    + "satellite_specs.yaml, "
                                    + "the following "
                                    + "nc-variable name "
                                    + "is chosen:\n", ncvar, "for "
                                    + "stdname: ", stdname )
                            else:
                                print("Only 1. appearance is used.")
                                print("variable " + ncvar + " is neglected")
                        else:
                            tmp = list(f.variables[ncvar][:])
                            vardict[stdname] += tmp
                    else:
                        tmp = list(f.variables[ncvar][:])
                        vardict[stdname] = tmp
                    stdname_lst.append(stdname)
        except (IOError) as e:
            print ("No such file or directory")
            print (e)
        count = count + 1
    print ('\n')
    # remove redundant entries
    time_unique,indices = np.unique(vardict['time'],return_index=True)
    for key in vardict:
        vardict[key]=list(np.array(vardict[key])[indices])
    if (f.variables[variable_info['lons']\
    ['standard_name']].getncattr('valid_min') == 0):
        # transform to -180 to 180 degrees
        tmp = np.array(vardict[variable_info['lons']['standard_name']])
        vardict[variable_info['lons']['standard_name']] \
            = list(((tmp - 180) % 360) - 180)
    # add reference time from netcdf
    vardict['time_unit'] = f.variables['time'].units
    # close nc-file
    f.close()
    return vardict

def read_local_files_cci(pathlst,provider,varalias,level):
    '''
    Read and concatenate all data to one timeseries for each variable.
    Fct is tailored to ESACCI files.
    '''
    # --- open file and read variables --- #
    varlst = [varalias] + ['lons','lats','time']
    varlst_cf = []
    for var in varlst:
        varlst_cf.append(variable_info[var]['standard_name'])
    count = 0
    print ("Processing " + str(int(len(pathlst))) + " files")
    print (pathlst[0])
    print (pathlst[-1])
    vardict = {}
    for f in pathlst:
        ncin = netCDF4.Dataset(f)
        for stdname in varlst_cf:
            tmp_varalias = varlst[varlst_cf.index(stdname)]
            if (satellite_dict[provider][level]['vardef'] is not None \
            and tmp_varalias in satellite_dict[provider][level] \
            ['vardef']):
                ncvar = satellite_dict[provider][level]['vardef']\
                                      [tmp_varalias]
                print( "As defined in "
                     + "satellite_specs.yaml, "
                     + "the following "
                     + "nc-variable name "
                     + "is chosen:\n", ncvar, "for "
                     + "stdname: ", stdname )
                if stdname in vardict.keys():
                    vardict[stdname] += list(ncin[ncvar][:])
                else:
                    vardict[stdname] = list(ncin[ncvar][:])
    # transform to -180 to 180 degrees
    tmp = np.array(vardict['longitude'])
    vardict['longitude'] = list(((tmp - 180) % 360) - 180)
    vardict['time_unit'] = \
        ncin[satellite_dict[provider][level]['vardef']['time']].units
    ncin.close()
    return vardict

def read_local_files_eumetsat(pathlst,provider,varalias,level):
    '''
    Read and concatenate all data to one timeseries for each variable.
    Fct is tailored to EUMETSAT files.
    '''
    # --- create tmpdir --- #
    tmpdir = tempfile.TemporaryDirectory()
    print('tmp directory is established:',tmpdir.name)
    # --- open file and read variables --- #
    varlst = [varalias] + ['lons','lats','time']
    varlst_cf = []
    for var in varlst:
        varlst_cf.append(variable_info[var]['standard_name'])
    count = 0
    print ("Processing " + str(int(len(pathlst))) + " files")
    print (pathlst[0])
    print (pathlst[-1])
    vardict = {}
    for f in pathlst:
        path = f[0:-len(f.split('/')[-1])]
        zipped = zipfile.ZipFile(f)
        enhanced_measurement = zipped.namelist()[-1]
        extracted = zipped.extract(enhanced_measurement, path=tmpdir.name)
        ncin = netCDF4.Dataset(extracted)
        for stdname in varlst_cf:
            tmp_varalias = varlst[varlst_cf.index(stdname)]
            if (satellite_dict[provider][level]['vardef'] is not None \
            and tmp_varalias in \
            satellite_dict[provider][level]['vardef']):
                ncvar = satellite_dict[provider][level]\
                                      ['vardef']\
                                      [tmp_varalias]
                print( "As defined in "
                     + "satellite_specs.yaml, "
                     + "the following "
                     + "nc-variable name "
                     + "is chosen:\n", ncvar, "for "
                     + "stdname: ", stdname )
                if stdname in vardict.keys():
                    vardict[stdname] += list(ncin[ncvar][:])
                else:
                    vardict[stdname] = list(ncin[ncvar][:])
    # transform to -180 to 180 degrees
    tmp = np.array(vardict['longitude'])
    vardict['longitude'] = list(((tmp - 180) % 360) - 180)
    vardict['time_unit'] = \
        ncin[satellite_dict[provider][level]['vardef']['time']].units
    tmpdir.cleanup()
    ncin.close()
    return vardict

def read_local_files(pathlst,provider,varalias,level):
    '''
    main fct to read L2/L3 altimetry files from EUMETSAT/CMEMS,
    respectively. Currently only L3 are possible to read.
    '''
    # read local files depending on provider
    # -> similar to get_remote_files
    if provider == 'cmems':
        vardict = read_local_files_cmems(pathlst,provider,\
                                         varalias,level)
    elif provider == 'cci':
        vardict = read_local_files_cci(pathlst,provider,\
                                       varalias,level)
    elif provider == 'eumetsat':
        vardict = read_local_files_eumetsat(pathlst,provider,\
                                            varalias,level)
    return vardict

def get_sat_ts(sdate,edate,twin,region,provider,sat,level,
    pathlst,varalias):
    #
    vardict = read_local_files(pathlst,provider,varalias,level)
    print('Total: ', len(vardict['time']), ' footprints found')
    # find values for give time constraint
    dtime = list( netCDF4.num2date(vardict['time'],
                                    vardict['time_unit']) )
    cidx = collocate_times(dtime,sdate=sdate,edate=edate,twin=twin)
    cvardict = {}
    for element in vardict:
        if element != 'time_unit':
            cvardict[element] = list(np.array(
                                    vardict[element]
                                    )[cidx])
        else:
            cvardict[element] = vardict[element]
    del vardict
    print('In chosen time period: ', len(cvardict['time']),
        ' footprints found')
    # find values for given region
    ridx = matchregion(cvardict['latitude'],
                       cvardict['longitude'],
                       region=region,grid_date=sdate)
    rvardict = {}
    for element in cvardict:
        if element != 'time_unit':
            rvardict[element] = list(np.array(
                                    cvardict[element]
                                    )[ridx])
        else:
            rvardict[element] = cvardict[element]
    del cvardict
    if len(rvardict['time'])>0:
        rvardict['datetime'] = netCDF4.num2date(
                                    rvardict['time'],
                                    rvardict['time_unit'])
        print('For chosen region and time: ',
                len(rvardict['time']),'footprints found')
        # convert to datetime object
        timedt = rvardict['datetime']
        rvardict['datetime'] = [datetime(t.year,t.month,t.day,
                                         t.hour,t.minute,t.second,\
                                         t.microsecond)\
                                for t in timedt]
    else:
        print('For chosen region and time: 0 footprints found!')
    # find variable name as defined in file
    stdname = variable_info[varalias]['standard_name']
    if provider == 'cmems':
        ncdict = ncdumpMeta(pathlst[0])
    elif provider == 'cci':
        ncdict = ncdumpMeta(pathlst[0])
    elif provider == 'eumetsat':
        tmpdir = tempfile.TemporaryDirectory()
        zipped = zipfile.ZipFile(pathlst[0])
        enhanced_measurement = zipped.namelist()[-1]
        extracted = zipped.extract(enhanced_measurement, path=tmpdir.name)
        ncdict = ncdumpMeta(extracted)
        tmpdir.cleanup()
    filevarname = get_varname_for_cf_stdname_in_ncfile(
                                        ncdict,stdname)
    if (len(filevarname) or filename is None) > 1:
        filevarname = satellite_dict[provider][level]\
                                    ['vardef'][varalias]
    else:
        filevarname = get_varname_for_cf_stdname_in_ncfile(
                                            ncdict,stdname)[0]
    rvardict['meta'] = ncdict
    return rvardict

def crop_vardict_to_period(vardict,sdate,edate,stdvarname):
    for key in vardict:
        if (key != 'time_unit' and key != 'meta' and key != 'datetime'):
            vardict[key] =  list(np.array(vardict[key])[ \
                                ( (np.array(vardict['datetime'])>=sdate)
                                & (np.array(vardict['datetime'])<=edate)
                                ) ])
        else:
            vardict[key] = vardict[key]
    vardict['datetime'] =   list(np.array(vardict['datetime'])[ \
                                ( (np.array(vardict['datetime'])>=sdate)
                                & (np.array(vardict['datetime'])<=edate)
                                ) ])
    return vardict


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

def check_date(filelst,date):
    '''
    returns idx for file
    '''
    # check if str in lst according to desired date (sdate,edate)
    idx = []
    for i in range(len(filelst)):
        element = filelst[i]
        tmp = element.find(date.strftime('%Y%m%d'))
        if tmp>=0:
            #return first index available
            idx.append(i)
    if len(idx)<=0:
        idx=[0]
    return idx[0],idx[-1]

# ---------------------------------------------------------------------#


class satellite_class():
    '''
    Class to handle netcdf files containing satellite data e.g.
    Hs[time], lat[time], lon[time]
    This class offers the following added functionality:
     - get swaths of desired days and read
     - get the closest time stamp(s)
     - get the location (lon, lat) for this time stamp
     - get Hs or 10m wind value for this time
    '''

    def __init__(
        self,sdate,mission='s3a',provider='cmems',
        edate=None,twin=None,download=False,path_local=None,
        remote_ftp_path=None,region='mwam4',nproc=1,varalias='Hs',
        filterData=False,level='L3',**kwargs):

        print ('# ----- ')
        print (" ### Initializing satellite_class object ###")
        # check settings
        if edate is None:
            print ("Requested time: ", str(sdate))
            edate = sdate
        else:
            print ("Requested time frame: " +
                str(sdate) + " - " + str(edate))
        if twin is None:
            twin = int(30)
        stdname = variable_info[varalias]['standard_name']
        # define some class variables
        self.sdate = sdate
        self.edate = edate
        self.varalias = varalias
        self.stdvarname = stdname
        self.twin = twin
        self.region = region
        self.mission = mission
        self.obstype = 'satellite_altimeter'
        self.provider = provider
        self.level = level
        print('Please wait ...')
        print('Chosen time window is:', twin, 'min')
        # make satpaths
        if path_local is None:
            path_template = satellite_dict[provider][level]\
                                          ['dst']\
                                          ['path_template']
            self.path_local = path_template
        else:
            self.path_local = path_local
        # retrieve files
        if download is False:
            print ("No download initialized, checking local files")
        else:
            print ("Downloading necessary files ...")
            get_remote_files(path_local,sdate,edate,twin,
                            nproc,provider,api_url,mission,
                            level,vars(self))
        t0=time.time()
        pathlst, filelst = get_local_files(sdate,edate,twin,
                                        provider,mission,
                                        level,vars(self),
                                        path_local=path_local)
        if len(pathlst) > 0:
            try:
                if filterData == True:
                    # extend time period due to filter
                    if 'stwin' not in kwargs.keys():
                        kwargs['stwin'] = 1 # needs to be changed
                    if 'etwin' not in kwargs.keys():
                        kwargs['etwin'] = 1
                    twin_tmp = twin + kwargs['stwin'] + kwargs['etwin']
                    # retrieve data
                    rvardict = get_sat_ts( sdate,edate,
                                           twin_tmp,region,
                                           provider,mission,
                                           level,pathlst,
                                           varalias )
                    # filter data
                    rvardict = filter_main( rvardict,
                                            varalias = varalias,
                                            **kwargs )
                    # crop to original time period
                    sdate_tmp = sdate - timedelta(minutes=twin)
                    edate_tmp = sdate + timedelta(minutes=twin)
                    rvardict = crop_vardict_to_period(rvardict,
                                                      sdate_tmp,
                                                      edate_tmp,
                                                      stdname)
                    self.filter = True
                    self.filterSpecs = kwargs
                else:
                    rvardict = get_sat_ts(sdate,edate,twin,region,
                                          provider,mission,level,
                                          pathlst,varalias)
                    # make ts in vardict unique
                    rvardict = vardict_unique(rvardict)
                    # rm NaNs
                    rvardict = rm_nan_from_vardict(varalias,rvardict)
                # find variable name as defined in file
                if provider == 'cmems':
                    ncdict = ncdumpMeta(pathlst[0])
                elif provider == 'cci':
                    ncdict = ncdumpMeta(pathlst[0])
                elif provider == 'eumetsat':
                    tmpdir = tempfile.TemporaryDirectory()
                    zipped = zipfile.ZipFile(pathlst[0])
                    enhanced_measurement = zipped.namelist()[-1]
                    extracted = zipped.extract(enhanced_measurement,
                                               path=tmpdir.name)
                    ncdict = ncdumpMeta(extracted)
                    tmpdir.cleanup()
                filevarname = get_varname_for_cf_stdname_in_ncfile(
                                                    ncdict,stdname)
                if (len(filevarname) or filename is None) > 1:
                    filevarname = satellite_dict[provider]\
                                                [level]\
                                                ['vardef']\
                                                [varalias]
                else:
                    filevarname = \
                            get_varname_for_cf_stdname_in_ncfile(
                                                  ncdict,stdname)[0]
                rvardict['meta'] = ncdict
                # define more class variables
                self.vars = rvardict
                self.varname = filevarname
                t1=time.time()
                print("Time used for retrieving satellite data:",\
                        round(t1-t0,2),"seconds")
                print ("Satellite object initialized including "
                    + str(len(self.vars['time'])) + " footprints.")
                #print (" ### satellite_class object initialized ###")
                print ('# ----- ')
            except Exception as e:
                print(e)
                print('Error encountered')
                print('No satellite_class object initialized')
        else:
            print('No satellite data found')
            print('No satellite_class object initialized')
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

    def write_to_nc(self,pathtofile=None,file_date_incr=None):
        if 'error' in vars(self):
            print('Erroneous satellite_class file detected')
            print('--> dump to netCDF not possible !')
        else:
            tmpdate = self.sdate
            edate = self.edate
            while tmpdate <= edate:
                idxtmp = collocate_times(
                            unfiltered_t=self.vars['datetime'],
                            sdate = datetime(tmpdate.year,
                                             tmpdate.month,1),
                            edate = datetime(tmpdate.year,
                                             tmpdate.month,
                                             calendar.monthrange(
                                             tmpdate.year,
                                             tmpdate.month)[1],
                                             23,59) )
                if pathtofile is None:
                    path_template = satellite_dict[self.provider]\
                                                  [self.level]\
                                                  ['dst']\
                                                  ['path_template'][0]
                    file_template = satellite_dict[self.provider]\
                                                  [self.level]\
                                                  ['dst']\
                                                  ['file_template']
                    strsublst = satellite_dict[self.provider]\
                                              [self.level]\
                                              ['dst']['strsub']
                    if 'filterData' in vars(self).keys():
                        file_template = 'filtered_' + file_template
                    tmppath = os.path.join(path_template,file_template)
                    subdict = make_subdict(strsublst,
                                           class_object_dict=vars(self))
                    pathtofile = make_pathtofile(tmppath,strsublst,
                                                 subdict,
                                                 date=tmpdate)
                title = (self.obstype
                       + ' observations from '
                       + self.mission)
                dumptonc_ts_sat(self,pathtofile,title)
                # determine date increment
                if file_date_incr is None:
                    file_date_incr = satellite_dict[self.provider]\
                                    [self.level]\
                                    ['dst'].get('file_date_incr','m')
                if file_date_incr == 'm':
                    tmpdate += relativedelta(months = +1)
                elif file_date_incr == 'Y':
                    tmpdate += relativedelta(years = +1)
                elif file_date_incr == 'd':
                    tmpdate += timedelta(days = +1)
        return

def matchregion(LATS,LONS,region,grid_date):
    # region in region_dict[poly]:
    # find values for given region
    if (region not in region_dict['poly'] and \
    region not in model_dict):
        if region is None:
            region = 'global'
        if ~isinstance(region,str)==True:
            print ("Manually specified region "
                + [llcrnrlat,urcrnrlat,llcrnrlon,urcrnrlon] + ": \n"
                + " --> Bounds: " + str(region))
        else:
            if region not in region_dict['rect']:
                sys.exit("Region is not defined")
            else:
                print("Specified region: " + region + "\n"
                + " --> Bounds: " + str(region_dict['rect'][region]))
        ridx = matchregion_rect(LATS,LONS,region=region)
    else:
        ridx = matchregion_poly(LATS,LONS,region=region,
                                grid_date=grid_date)
    return ridx

def matchregion_rect(LATS,LONS,region):
    if (region is None or region == "global"):
        region = "global"
        ridx = range(len(LATS))
    else:
        if isinstance(region,str)==True:
            if "boundinglat" in region_dict['rect'][region]:
                boundinglat = region_dict['rect'][region]["boundinglat"]
            else:
                llcrnrlat = region_dict['rect'][region]["llcrnrlat"]
                urcrnrlat = region_dict['rect'][region]["urcrnrlat"]
                llcrnrlon = region_dict['rect'][region]["llcrnrlon"]
                urcrnrlon = region_dict['rect'][region]["urcrnrlon"]
        else:
            llcrnrlat = region[0]
            urcrnrlat = region[1]
            llcrnrlon = region[2]
            urcrnrlon = region[3]
        # check if coords in region
        ridx=[]
        for i in range(len(LATS)):
            if (
            "boundinglat" in region_dict['rect'][region]
            and LATS[i] >= boundinglat
                ):
                ridx.append(i)
            elif(
            not "boundinglat" in region_dict['rect'][region]
            and LATS[i] >= llcrnrlat
            and LATS[i] <= urcrnrlat
            and LONS[i] >= llcrnrlon
            and LONS[i] <= urcrnrlon
                ):
                ridx.append(i)
    if not ridx:
        print ("No values for chosen region and time frame!!!")
    else:
        print ("Values found for chosen region and time frame.")
    return ridx

def matchregion_poly(LATS,LONS,region,grid_date):
    from matplotlib.patches import Polygon
    from matplotlib.path import Path
    import numpy as np
    if (region not in region_dict['poly'] \
        and region not in model_dict):
        sys.exit("Region polygone is not defined")
    elif isinstance(region,dict)==True:
        print ("Manuall specified region: \n"
            + " --> Bounds: " + str(region))
        poly = Polygon(list(zip(region['lons'],
            region['lats'])), closed=True)
    elif (isinstance(region,str)==True and region in model_dict):
        try:
            print('Use date for retrieving grid: ', grid_date)
            filestr = make_model_filename_wrapper(\
                                    region,grid_date,'best')
            meta = ncdumpMeta(filestr)
            flon = get_filevarname(region,\
                                'lons',variable_info,\
                                model_dict,meta)
            flat = get_filevarname(region,\
                                'lats',variable_info,\
                                model_dict,meta)
            M = xa.open_dataset(filestr, decode_cf=True)
            model_lons = M[flon].data
            model_lats = M[flat].data
        except (KeyError,IOError,ValueError) as e:
            print(e)
            if 'grid_date' in model_dict[region]:
                grid_date = model_dict[region]['grid_date']
                print('Trying default date ', grid_date)
            else:
                grid_date = datetime(
                                    datetime.now().year,
                                    datetime.now().month,
                                    datetime.now().day
                                    )
            filestr = make_model_filename_wrapper(\
                                    region,grid_date,'best')
            meta = ncdumpMeta(filestr)
            flon = get_filevarname(region,\
                                'lons',variable_info,\
                                model_dict,meta)
            flat = get_filevarname(region,\
                                'lats',variable_info,\
                                model_dict,meta)
            M = xa.open_dataset(filestr, decode_cf=True)
            model_lons = M[flon].data
            model_lats = M[flat].data
        if (len(model_lons.shape)==1):
            model_lons, model_lats = np.meshgrid(
                                    model_lons,
                                    model_lats
                                    )
        print('Check if footprints fall within the chosen domain')
        if (region=='global'):
            rlatlst, rlonlst = LATS, LONS
        else:
            ncdict = ncdumpMeta(filestr)
            try:
                proj4 = find_attr_in_nc('proj',ncdict=ncdict,
                                        subattrstr='proj4')
            except IndexError:
                print('proj4 not defined in netcdf-file')
                print('Using proj4 from model config file')
                proj4 = model_dict[region]['proj4']
            proj_model = pyproj.Proj(proj4)
            Mx, My = proj_model(model_lons,model_lats,inverse=False)
            Vx, Vy = proj_model(LONS,LATS,inverse=False)
            xmax, xmin = np.max(Mx), np.min(Mx)
            ymax, ymin = np.max(My), np.min(My)
            ridx = list(np.where((Vx>xmin) & (Vx<xmax) &
                            (Vy>ymin) & (Vy<ymax))[0]
                        )
    elif isinstance(region,str)==True:
        print ("Specified region: " + region + "\n"
        + " --> Bounded by polygon: \n"
        + "lons: " + str(region_dict['poly'][region]['lons']) + "\n"
        + "lats: " + str(region_dict['poly'][region]['lats']))
        poly = Polygon(list(zip(region_dict['poly'][region]['lons'],
            region_dict['poly'][region]['lats'])), closed=True)
        # check if coords in region
        LATS = list(LATS)
        LONS = list(LONS)
        latlst = LATS
        lonlst = LONS
        lats = np.array(LATS).ravel()
        lons = np.array(LONS).ravel()
        points = np.c_[lons,lats]
        # radius seems to be important to correctly define polygone
        # see discussion here:
        # https://github.com/matplotlib/matplotlib/issues/9704
        hits = Path(poly.xy).contains_points(points,radius=1e-9)
        ridx = list(np.array(range(len(LONS)))[hits])
    if not ridx:
        print ("No values for chosen region and time frame!!!")
    else:
        print ("Values found for chosen region and time frame.")
    return ridx

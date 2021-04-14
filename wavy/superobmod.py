from utils import runmean_conv
from pygam import LinearGAM, l, s, ExpectileGAM
import numpy as np
from copy import deepcopy
import yaml
import os
from datetime import datetime, timedelta
import netCDF4

from utils import find_included_times

moddir = os.path.abspath(os.path.join(os.path.dirname( __file__ ),
                        '..', 'config/variable_info.yaml'))
with open(moddir,'r') as stream:
    variable_info=yaml.safe_load(stream)

def superobbing(varalias,vardict,superob=None,outlier_detection='gam',\
missing_data='marginalize',date_incr=None,**kwargs):
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
    newdict = deepcopy(vardict)
    stdvarname = variable_info[varalias]['standard_name']
    # !if for satellites first a landmask has to be created!
    if outlier_detection is not None:
        ol_dict = detect_outliers(varalias,vardict,method=outlier_detection)
    else: print('Warning: Performing outlier detection is recommended')
    if missing_data == 'marginalize':
        newdict[stdvarname] = ol_dict['ts_clean']
    elif missing_data == 'impute':
        newdict[stdvarname] = ol_dict['ts_clean']
        # create list of time stamps depending on choice
        sd = vardict['datetime'][0]
        ed = vardict['datetime'][-1]
        steps = int((ed-sd).total_seconds()/(date_incr*60*60))+1
        tmpd = sd
        dtlst = [tmpd + timedelta(hours=i) \
            for i in range(0,steps,date_incr) \
            if (tmpd + timedelta(hours=i) <= ed)]
        input_grid = netCDF4.date2num(dtlst,units=vardict['time_unit'])
        del tmpd
        # super observations are computed from cleaned time series
        tmp_vardict = deepcopy(newdict)
        tmpvar = np.array(tmp_vardict[stdvarname])
        tmptime = np.array(tmp_vardict['time'])
        tmpdtime = np.array(tmp_vardict['datetime'])
        tmptime = tmptime[~np.isnan(tmpvar)]
        tmpdtime = tmpdtime[~np.isnan(tmpvar)]
        tmpvar = tmpvar[~np.isnan(tmpvar)]
        tmp_vardict[stdvarname] = tmpvar
        tmp_vardict['time'] = tmptime
        tmp_vardict['datetime'] = tmpdtime
        sobs_ts = compute_superobs(varalias,tmp_vardict,input_grid,dtlst,
                        method=superob,date_incr=date_incr,ol_dict=ol_dict)
        # handle missing data
        newdict[stdvarname] = list(sobs_ts)
        newdict['time'] = list(input_grid)
        newdict['datetime'] = dtlst
        newdict['longitude'] = [vardict['longitude'][0]]*len(dtlst)
        newdict['latitude'] = [vardict['latitude'][0]]*len(dtlst)
    return newdict

def compute_superobs(varalias,vardict,input_grid,dtlst,method='gam',\
date_incr=1,**kwargs):
    stdvarname = variable_info[varalias]['standard_name']
    dt = vardict['datetime']
    x = vardict['time']
    y = vardict[stdvarname]
    X = input_grid
    if method=='gam':
        print('Chosen superobbing method: "gam"')
        sobs_ts = so_linearGAM(x,y,X,varalias,**kwargs)
    if method=='block_mean':
        # blocks are means from date_incr in hours
        # For each grid_input time_stamp compute mean of hour 
        # if at least half of values are valid
        # else attribute NaN
        print('Chosen superobbing method: "block_mean"')
        sobs_ts = block_means(dt,x,y,dtlst,date_incr)
    else: print('Method not defined, please enter valid method')
    return sobs_ts

def block_means(dt,x,y,X,date_incr):
    means = []
    if isinstance(x,list):
        x = np.array(x)
    if isinstance(y,list):
        y = np.array(y)
    for i in range(len(X)):
        # check if more than 50% of values are valid
        # if so compute mean
        idx = find_included_times(dt,\
                                  sdate=X[i]-timedelta(hours=date_incr),\
                                  edate=X[i],twin=0)
        block = y[idx]
        ratio = len(block[np.isnan(block)])/float(len(block))
        if ratio < 0.5:
            means.append(np.nanmean(block))
        else:
            means.append(np.nan)
    means = np.array(means)
    return means

def so_linearGAM(x,y,X,varalias,**kwargs):
    if isinstance(x,list):
        x = np.array(x)
    x = x.reshape(len(x),1)
    if isinstance(y,list):
        y = np.array(y)
    if isinstance(X,list):
        X = np.array(X)
    if X is None:
        X = x.reshape(len(x),1)
    else:
        X = X.reshape(len(X),1)
    if 'n_splines' in kwargs.keys():
        n_splines = kwargs['n_splines']
    else:
        # This is because the automatic approach is too smooth
        n_splines = int(len(y)/6)
    if varalias != 'Mdir':
        gam = LinearGAM(n_splines=n_splines,\
                        terms=s(0,basis='ps')\
                        ).gridsearch(x, y)
    else:
        print('CYCLIC!')
        print(x.shape)
        print(X.shape)
        n_splines = int(len(y)/6)
        gam = LinearGAM(n_splines=n_splines,\
                        terms=s(0,basis='cp',edge_knots=[0,360])\
                        ).gridsearch(x, y)
    # sample on the input grid
    means = gam.predict(X)
    return means

def detect_outliers(varalias,vardict,method='gam',**kwargs):
    print('Detect outliers ...')
    stdvarname = variable_info[varalias]['standard_name']
    ol_dict={}
    dt = vardict['datetime']
    x = vardict['time']
    y = vardict[stdvarname]
    # coars use approximate limits (in future use range from yaml)
    llim = variable_info[varalias]['valid_range'][0]
    ulim = variable_info[varalias]['valid_range'][1]
    # rogorous removal use techniques like: 
    # blockVariance, GP, GAM, (quantile regression) random forest, ...
    if method=='gam':
        idx = ol_linearGAM(x,y,varalias,**kwargs)
        ts_clean = np.array(y)
        ts_clean[idx] = np.nan
    if method=='expectile':
        idx = ol_expectileGAM(x,y,varalias,**kwargs)
        ts_clean = np.array(y)
        ts_clean[idx] = np.nan
    ol_dict['indices']=idx
    ol_dict['ts_clean']=ts_clean
    return ol_dict

def ol_expectileGAM(x,y,varalias,**kwargs):
    if isinstance(x,list):
        x = np.array(x)
    if isinstance(y,list):
        y = np.array(y)
    X = x.reshape(len(x),1)
    if 'n_splines' in kwargs.keys():
        n_splines = kwargs['n_splines']
    else:
        # This is because the automatic approach is too smooth
        n_splines = int(len(y)/6)
    gam50 = ExpectileGAM(expectile=0.50,terms=s(0),\
                        n_splines=n_splines).gridsearch(X, y)
    # This practice of copying makes the models 
    # less likely to cross and much faster
    # https://pygam.readthedocs.io/en/latest/notebooks/tour_of_pygam.html
    # and copy the smoothing to the other models
    lam = gam50.lam
    # now fit a few more models
    gam95 = ExpectileGAM(expectile=0.95, lam=lam, terms=s(0),\
                        n_splines=n_splines).fit(X, y)
    gam05 = ExpectileGAM(expectile=0.05, lam=lam, terms=s(0),\
                        n_splines=n_splines).fit(X, y)
    ulim = gam95.predict(X)
    llim = gam05.predict(X)
    idx = [i for i in range(len(y)) \
            if (y[i]>ulim[i,1] or y[i]<llim[i])]
    return idx

def ol_linearGAM(x,y,varalias,**kwargs):
    if isinstance(x,list):
        x = np.array(x)
    if isinstance(y,list):
        y = np.array(y)
    X = x.reshape(len(x),1)
    if 'n_splines' in kwargs.keys():
        n_splines = kwargs['n_splines']
    else:
        # This is because the automatic approach is too smooth
        n_splines = int(len(y)/6)
    if varalias != 'Mdir':
        gam = LinearGAM(n_splines=n_splines,\
                        terms=s(0,basis='ps')\
                        ).gridsearch(X, y)
    else:
        print('CYCLIC!')
        print(x.shape)
        print(X.shape)
        n_splines = int(len(y)/6)
        gam = LinearGAM(n_splines=n_splines,\
                        terms=s(0,basis='cp',edge_knots=[0,360])\
                        ).gridsearch(X, y)
    #gam = LinearGAM(n_splines=n_splines,terms=s(0)).gridsearch(X, y)
    # sample on the input grid
    means = gam.predict(X)
    bounds = gam.prediction_intervals(X, width=.95)
    idx = [i for i in range(len(y)) \
            if (y[i]>bounds[i,1] or y[i]<bounds[i,0])]
    return idx

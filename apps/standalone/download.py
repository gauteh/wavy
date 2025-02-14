#!/usr/bin/env python3
"""
download satellite data from Copernicus
"""
# --- imports -------------------------------------------------------- #
# standard library imports
import sys
sys.path.append('../../wavy')

import os
import time
from datetime import datetime, timedelta
import yaml
import argparse
from argparse import RawTextHelpFormatter
import numpy as np

# own import
from satmod import get_remote_files
from utils import sort_files
# -------------------------------------------------------------------- #

# read yaml config files:
moddir = os.path.abspath(os.path.join(os.path.dirname( __file__ ), 
                        '../../', 'config/satellite_specs.yaml'))
with open(moddir,'r') as stream:
    satellite_dict=yaml.safe_load(stream)

# parser
parser = argparse.ArgumentParser(
    description="""
Download satellite netcdf from Copernicus DU.

Usage:
./download.py -sat s3a -sd 2020100100 -ed 2020101000
    """,
    formatter_class = RawTextHelpFormatter
    )
parser.add_argument("-sd", metavar='startdate',
    help="start date of time period to be downloaded")
parser.add_argument("-ed", metavar='enddate',
    help="end date of time period to be downloaded")
parser.add_argument("-sat", metavar='satellite',
    help="satellite mission, currently available: \
        \ns3a - Sentinel-3A\
        \ns3b - Sentinel-3B\
        \nj3 - Jason-3 (reference mission)\
        \nc2 - Cryosat-2\
        \nal - SARAL/AltiKa\
        \ncfo - CFOSAT\
        \nh2b - HaiYang-2B\
        \nall - all availabe satellites")
parser.add_argument("-path", metavar='path',
    help="destination for downloaded data")
parser.add_argument("-nproc", metavar='nproc',
    help="number of simultaneous processes",type = int)

args = parser.parse_args()

# settings
instr = 'altimeter'
provider = 'cmems'

now = datetime.now()
if args.sat is None:
    satlst = ['s3a']
elif args.sat == 'all':
    tmp = satellite_dict['altimeter']['cmems']['satellite']
    satlst = tmp.split(',')
    del tmp
else:
    satlst = [args.sat]

if args.sd is None:
    sdate = datetime(now.year,now.month,now.day,now.hour)-timedelta(hours=24)
else:
    sdate = datetime(int(args.sd[0:4]),int(args.sd[4:6]),
                int(args.sd[6:8]),int(args.sd[8:10]))

if args.ed is None:
    edate = datetime(now.year,now.month,now.day,now.hour,now.minute)
else:
    edate = datetime(int(args.ed[0:4]),int(args.ed[4:6]),
                int(args.ed[6:8]),int(args.ed[8:10]))

if args.path is None:
    targetpath = satellite_dict[instr][provider]['local']['path']
else:
    targetpath = args.path

if args.nproc is None:
    nproc = 1
else:
    nproc = args.nproc

for sat in satlst:
    try:
        print("Attempting to download data for:", sat)
        print("Time period:",str(sdate), "to", str(edate))
        satpath = satellite_dict[instr][provider]['remote']['path'] + sat
        destination = targetpath + '/' + sat
        print('destination: ' + destination)
        # check if destination exists
        if os.path.isdir(destination) == False:
            print ( 'Your destination path does not exist')
            print ( destination + ' will now be created')
            cmd = 'mkdir -p ' + destination
            os.system(cmd)
        start_time = time.time()
        sa_obj = get_remote_files(satpath, destination,
                            sdate,edate,twin=30,
                            nproc=nproc,instr=instr,provider=provider)
        time1 = time.time() - start_time
        print("Time used for collecting data: ", time1, " seconds")
        print("Data is being sorted into subdirectories year and month ...")
        filelst = np.sort(os.listdir(destination))
        sort_files(destination,filelst)
    except Exception as e:
        print('Experienced error when downloading data for',sat,
            '\nwith the error:',e,
            '\nSkip and continue ...')

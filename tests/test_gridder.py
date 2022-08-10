import sys
import os
from datetime import datetime
import pytest

from wavy.satmod import satellite_class as sc
from wavy.gridder import gridder_class as gc

def test_gridder(tmpdir,test_data):
    sco = sc(sdate="2020-11-1",edate="2020-11-3",region="NordicSeas",
             path_local=str(test_data)+'/*.nc')
    bb = (-170,170,-75,75)
    res = (2,2)
    print("initialize")
    gco = gc(oco=sco,bb=bb,res=res)
    print("assign obs")
    ovals,Midx = gco.get_obs_grid_idx()
    print("compute metric on grid")
    var_gridded = gco.apply_metric(Midx,ovals,metric="mean")

"""
- Module that should take care of collocation of points or swaths
- Needs input from modules that retrieve from observational platforms
  and models
"""
import sys
import numpy as np
from utils import progress
from region_specs import region_dict
from model_specs import model_dict
from stationmod import matchtime
from utils import haversine

def collocation_loop(
    j,sat_time_dt,model_time_dt_valid,distlim,model,
    sat_rlats,sat_rlons,sat_rHs,
    model_rlats,model_rlons,model_rHs,
    moving_win
    ):
    from utils import haversine
    lat_win = 0.1
    if model in model_dict:
        sat_rlat=sat_rlats[j]
        sat_rlon=sat_rlons[j]
        # constraints to reduce workload
        if model == 'ecwam':
            print("ECWAM not yet implemented, "
                  + "caution ecwam has other dimensions!")
            pass
        else:
            model_rlats_new=model_rlats[
                    (model_rlats>=sat_rlat-lat_win)
                    &
                    (model_rlats<=sat_rlat+lat_win)
                    &
                    (model_rlons>=sat_rlon-moving_win)
                    &
                    (model_rlons<=sat_rlon+moving_win)
                    ]
            model_rlons_new=model_rlons[
                    (model_rlats>=sat_rlat-lat_win)
                    &
                    (model_rlats<=sat_rlat+lat_win)
                    &
                    (model_rlons>=sat_rlon-moving_win)
                    &
                    (model_rlons<=sat_rlon+moving_win)
                    ]
            tmp=range(len(model_rlats))
            tmp_idx=np.array(tmp)[
                    (model_rlats>=sat_rlat-lat_win)
                    &
                    (model_rlats<=sat_rlat+lat_win)
                    &
                    (model_rlons>=sat_rlon-moving_win)
                    &
                    (model_rlons<=sat_rlon+moving_win)
                    ]
            # compute distances
            distlst=map(
                haversine,
                [sat_rlon]*len(model_rlons_new),
                [sat_rlat]*len(model_rlons_new),
                model_rlons_new,model_rlats_new
                )
            tmp_idx2 = distlst.index(np.min(distlst))
            idx_valid = tmp_idx[tmp_idx2]
        if (distlst[tmp_idx2]<=distlim and model_rHs[idx_valid]>=0):
            nearest_all_dist_matches=distlst[tmp_idx2]
            nearest_all_date_matches=sat_time_dt[j]
            nearest_all_model_Hs_matches=\
                           model_rHs[idx_valid]
            nearest_all_sat_Hs_matches=sat_rHs[j]
            nearest_all_sat_lons_matches=sat_rlon
            nearest_all_sat_lats_matches=sat_rlat
            nearest_all_model_lons_matches=\
                            model_rlons[idx_valid]
            nearest_all_model_lats_matches=\
                            model_rlats[idx_valid]
            return nearest_all_date_matches,nearest_all_dist_matches,\
                nearest_all_model_Hs_matches,nearest_all_sat_Hs_matches,\
                nearest_all_sat_lons_matches, nearest_all_sat_lats_matches,\
                nearest_all_model_lons_matches, nearest_all_model_lats_matches
        else:
           return

def collocate(model,model_Hs,model_lats,model_lons,model_time_dt,\
    sa_obj,datein,distlim=None):
    """
    get stellite time steps close to model time step. 
    """
    if distlim is None:
        distlim = int(6)
    timewin = sa_obj.timewin
    ctime, cidx = matchtime(datein,datein,sa_obj.time,
                    sa_obj.basetime,timewin=sa_obj.timewin)
    sat_time_dt=np.array(sa_obj.dtime)[cidx]
    model_time_idx = model_time_dt.index(datein)
    model_time_dt_valid=[model_time_dt[model_time_idx]]
    print ("date matches found:")
    print (model_time_dt_valid)
    # Constrain to region
    if ((model in model_dict)
    and (sa_obj.region=='ecwam'
    and (sa_obj.region=='Global' or sa_obj.region=='ecwam'))):
        model_rlats = model_lats
        model_rlons = model_lons
        model_rHs = model_Hs.squeeze()
    elif ((model in model_dict)
    and (sa_obj.region!='Arctic' and sa_obj.region!='ARCMFC')):
        model_rlats = model_lats[
                    (model_lats
                    >= sa_obj.region_dict[sa_obj.region]["llcrnrlat"])
                  & (model_lats
                    <= sa_obj.region_dict[sa_obj.region]["urcrnrlat"])
                  & (model_lons
                    >= sa_obj.region_dict[sa_obj.region]["llcrnrlon"])
                  & (model_lons
                    <= sa_obj.region_dict[sa_obj.region]["urcrnrlon"])
                            ]
        model_rlons = model_lons[
                    (model_lats
                    >= sa_obj.region_dict[sa_obj.region]["llcrnrlat"])
                  & (model_lats
                    <= sa_obj.region_dict[sa_obj.region]["urcrnrlat"])
                  & (model_lons
                    >= sa_obj.region_dict[sa_obj.region]["llcrnrlon"])
                  & (model_lons
                    <= sa_obj.region_dict[sa_obj.region]["urcrnrlon"])
                            ]
        tmpA=model_Hs.squeeze()
        tmpB = tmpA[
                (model_lats
                >= sa_obj.region_dict[sa_obj.region]["llcrnrlat"])
                & (model_lats
                <= sa_obj.region_dict[sa_obj.region]["urcrnrlat"])
              & (model_lons
                >= sa_obj.region_dict[sa_obj.region]["llcrnrlon"])
              & (model_lons
                <= sa_obj.region_dict[sa_obj.region]["urcrnrlon"])                            ]
        model_rHs=tmpB
        del tmpA, tmpB
    elif ((model in model_dict)
    and (sa_obj.region=='Arctic' or sa_obj.region=='ARCMFC')):
        model_rlats = model_lats[
                    (model_lats
                    >= sa_obj.region_dict[sa_obj.region]["boundinglat"])
                            ]
        model_rlons = model_lons[
                    (model_lats
                    >= sa_obj.region_dict[sa_obj.region]["boundinglat"])
                            ]
        model_rHs=[]
        tmpA = model_Hs[model_time_idx,:]
        tmpB = tmpA[
                (model_lats
                >= sa_obj.region_dict[sa_obj.region]["boundinglat"])
                        ]
        model_rHs = tmpB
        del tmpA, tmpB
    # Compare wave heights of satellite with model with 
    # constraint on distance and time frame
    nearest_all_date_matches=[]
    nearest_all_dist_matches=[]
    nearest_all_model_Hs_matches=[]
    nearest_all_sat_Hs_matches=[]
    nearest_all_sat_lons_matches=[]
    nearest_all_sat_lats_matches=[]
    nearest_all_model_lons_matches=[]
    nearest_all_model_lats_matches=[]
    # create local variables before loop
    sat_rlats=sa_obj.loc[0][cidx]
    sat_rlons=sa_obj.loc[1][cidx]
    sat_rHs=np.array(sa_obj.Hs)[cidx]
    # moving window compensating for increasing latitudes
    try:
        moving_win = round(
                (distlim /
                 haversine(0,
                    np.max(np.abs(sat_rlats)),
                    1,
                    np.max(np.abs(sat_rlats)))
                ),
                2)
    except (ValueError):
        moving_win = .6
    print ("Searching for matches with moving window of degree:",\
            moving_win)
    for j in range(len(sat_time_dt)):
        progress(j,str(int(len(sat_time_dt))),'')
#        for k in range(1):
        try:
            resultlst = collocation_loop(\
                j,sat_time_dt,model_time_dt_valid,distlim,model,\
                sat_rlats,sat_rlons,sat_rHs,\
                model_rlats,model_rlons,model_rHs,moving_win)
            nearest_all_date_matches.append(resultlst[0])
            nearest_all_dist_matches.append(resultlst[1])
            nearest_all_model_Hs_matches.append(resultlst[2])
            nearest_all_sat_Hs_matches.append(resultlst[3])
            nearest_all_sat_lons_matches.append(resultlst[4])
            nearest_all_sat_lats_matches.append(resultlst[5])
            nearest_all_model_lons_matches.append(resultlst[6])
            nearest_all_model_lats_matches.append(resultlst[7])
        except:
#            print "Unexpected error:", sys.exc_info()[0]
            pass
    results_dict = {
        'valid_date':np.array(model_time_dt_valid),
        'date_matches':np.array(nearest_all_date_matches),
        'dist_matches':np.array(nearest_all_dist_matches),
        'model_Hs_matches':np.array(nearest_all_model_Hs_matches),
        'sat_Hs_matches':np.array(nearest_all_sat_Hs_matches),
        'sat_lons_matches':np.array(nearest_all_sat_lons_matches),
        'sat_lats_matches':np.array(nearest_all_sat_lats_matches),
        'model_lons_matches':np.array(nearest_all_model_lons_matches),
        'model_lats_matches':np.array(nearest_all_model_lats_matches)
        }
    return results_dict

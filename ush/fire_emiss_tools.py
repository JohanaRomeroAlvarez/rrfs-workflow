import os
import numpy as np
import xarray as xr
from datetime import datetime
from netCDF4 import Dataset
import interp_tools as i_tools

def averaging_FRP(ebb_dcycle, fcst_dates, cols, rows, intp_dir, rave_to_intp, veg_map, tgt_area, beta, fg_to_ug, to_s):
    base_array = np.zeros((cols * rows))
    frp_daily = base_array.copy()
    ebb_smoke_total = []
    ebb_smoke_hr = []
    frp_avg_hr = []

    ef_map = xr.open_dataset(veg_map)
    emiss_factor = ef_map.emiss_factor.values
    target_area = tgt_area.values

    num_files = 0
    for cycle in fcst_dates:
        file_path = os.path.join(intp_dir, f'{rave_to_intp}{cycle}00_{cycle}59.nc')

        if os.path.exists(file_path):
            with xr.open_dataset(file_path) as nc:
                open_fre = nc.FRE[0, :, :].values
                open_frp = nc.frp_avg_hr[0, :, :].values
                num_files += 1
                if ebb_dcycle == 1:
                    print('Processing emissions for ebb_dcyc 1')
                    frp_avg_hr.append(open_frp)
                    ebb_hourly = (open_fre * emiss_factor * beta * fg_to_ug) / (target_area * to_s)
                    ebb_smoke_total.append(np.where(open_frp > 0, ebb_hourly, 0))
                else:
                    ebb_hourly = open_fre * emiss_factor * beta * fg_to_ug / target_area
                    ebb_smoke_total.append(np.where(open_frp > 0, ebb_hourly, 0).ravel())
                    frp_daily += np.where(open_frp > 0, open_frp, 0).ravel()
        else:
            # Append zeros correctly for missing data
            if ebb_dcycle == 1:
                frp_avg_hr.append(np.zeros((cols, rows)))
                ebb_smoke_total.append(np.zeros((cols, rows)))

    if num_files > 0:
        if ebb_dcycle == 1:
            frp_reshaped = np.stack(frp_avg_hr, axis=0)  # Stack the hourly arrays to match the (24, cols, rows) shape
            ebb_smoke_reshaped = np.stack(ebb_smoke_total, axis=0)
        else:
            summed_array = np.sum(np.array(ebb_smoke_total), axis=0)
            # Count the total number of zeros
            num_zeros = len(ebb_smoke_total) - np.sum([arr == 0 for arr in ebb_smoke_total], axis=0) #Estimate number of observations in 24 hrs
            safe_zero_count = np.where(num_zeros == 0, 1, num_zeros)

            #Estimate ebb rate
            result_array = [summed_array[i]/2 if safe_zero_count[i] == 1 else summed_array[i]/safe_zero_count[i] for i in range(len(safe_zero_count))]
            result_array = np.array(result_array)
            result_array[num_zeros == 0] = summed_array[num_zeros == 0]
            ebb_total =result_array.reshape(cols, rows)
            ebb_smoke_reshaped = ebb_total / 3600

            #Estimate frp avg
            temp_frp=[frp_daily[i]/2 if safe_zero_count[i] == 1 else frp_daily[i]/safe_zero_count[i] for i in range(len(safe_zero_count))]
            temp_frp=np.array(temp_frp)
            temp_frp[num_zeros == 0] = frp_daily[num_zeros == 0]
            frp_reshaped = temp_frp.reshape(cols, rows)
    else:
        if ebb_dcycle == 1:
            frp_reshaped = np.zeros((24, cols, rows))
            ebb_smoke_reshaped = np.zeros((24, cols, rows))
        else:
            frp_reshaped = np.zeros((cols, rows))
            ebb_smoke_reshaped = np.zeros((cols, rows))

    return(frp_reshaped, ebb_smoke_reshaped)

def estimate_fire_duration(intp_avail_hours, intp_dir, fcst_dates, current_day, cols, rows, rave_to_intp):
    # There are two steps here.
    #   1) First day simulation no RAVE from previous 24 hours available (fire age is set to zero)
    #   2) previus files are present (estimate fire age as the difference between the date of the current cycle and the date whe the fire was last observed whiting 24 hours)
    t_fire = np.zeros((cols, rows))

    for date_str in fcst_dates:
        date_file = int(date_str[:10])
        print('Date processing for fire duration',date_file)
        file_path = os.path.join(intp_dir, f'{rave_to_intp}{date_str}00_{date_str}59.nc')
        
        if os.path.exists(file_path):
            with xr.open_dataset(file_path) as open_intp:
                FRP = open_intp.frp_avg_hr[0, :, :].values
                dates_filtered = np.where(FRP > 0, date_file, 0)
                t_fire = np.maximum(t_fire, dates_filtered)

    t_fire_flattened = t_fire.flatten()
    t_fire_flattened = [int(i) if i != 0 else 0 for i in t_fire_flattened]

    try:
        fcst_t = datetime.strptime(current_day, '%Y%m%d%H')
        hr_ends = [datetime.strptime(str(hr), '%Y%m%d%H') if hr != 0 else 0 for hr in t_fire_flattened]
        te = [(fcst_t - i).total_seconds()/3600 if i != 0 else 0 for i in hr_ends]
    except ValueError:
        te = np.zeros((rows, cols))

    return(te)

def save_fire_dur(cols, rows, te):
    fire_dur = np.array(te).reshape(cols, rows)
    return(fire_dur)

def produce_emiss_24hr_file(ebb_dcycle, frp_reshaped, intp_dir, current_day, tgt_latt, tgt_lont, ebb_smoke_reshaped, cols, rows):
    file_path = os.path.join(intp_dir, f'SMOKE_RRFS_data_{current_day}00.nc')
    with Dataset(file_path, 'w') as fout:
        i_tools.create_emiss_file(fout, cols, rows)
        i_tools.Store_latlon_by_Level(fout, 'geolat', tgt_latt, 'cell center latitude', 'degrees_north', '2D', '-9999.f', '1.f')
        i_tools.Store_latlon_by_Level(fout, 'geolon', tgt_lont, 'cell center longitude', 'degrees_east', '2D', '-9999.f', '1.f')

        i_tools.Store_by_Level(fout,'frp_avg_hr','mean Fire Radiative Power','MW','3D','0.f','1.f')
        fout.variables['frp_avg_hr'][:, :, :] = frp_reshaped
        i_tools.Store_by_Level(fout,'ebb_smoke_hr','EBB emissions','ug m-2 s-1','3D','0.f','1.f')
        fout.variables['ebb_smoke_hr'][:, :, :] = ebb_smoke_reshaped

def produce_emiss_file(ebb_dcycle,  xarr_hwp, frp_reshaped, totprcp_ave_arr, xarr_totprcp, intp_dir, current_day, tgt_latt, tgt_lont, ebb_smoke_reshaped, fire_age, cols, rows):
    # Filter HWP
    filtered_hwp = xarr_hwp.where(frp_reshaped > 0, 0)
    filtered_prcp = xarr_totprcp.where(frp_reshaped > 0, 0)

    # Produce emiss file
    file_path = os.path.join(intp_dir, f'SMOKE_RRFS_data_{current_day}00.nc')

    with Dataset(file_path, 'w') as fout:
        i_tools.create_emiss_file(fout, cols, rows)
        i_tools.Store_latlon_by_Level(fout, 'geolat', tgt_latt, 'cell center latitude', 'degrees_north', '2D', '-9999.f', '1.f')
        i_tools.Store_latlon_by_Level(fout, 'geolon', tgt_lont, 'cell center longitude', 'degrees_east', '2D', '-9999.f', '1.f')
 
        print('Storing different variables')
        i_tools.Store_by_Level(fout,'frp_davg','Daily mean Fire Radiative Power','MW','3D','0.f','1.f')
        fout.variables['frp_davg'][0, :, :] = frp_reshaped
        i_tools.Store_by_Level(fout,'ebb_rate','Total EBB emission','ug m-2 s-1','3D','0.f','1.f') 
        fout.variables['ebb_rate'][0, :, :] = ebb_smoke_reshaped
        i_tools.Store_by_Level(fout,'fire_end_hr','Hours since fire was last detected','hrs','3D','0.f','1.f')
        fout.variables['fire_end_hr'][0, :, :] = fire_age
        i_tools.Store_by_Level(fout,'hwp_davg','Daily mean Hourly Wildfire Potential', 'none','3D','0.f','1.f')
        fout.variables['hwp_davg'][0, :, :] = filtered_hwp
        i_tools.Store_by_Level(fout,'totprcp_24hrs','Sum of precipitation', 'm', '3D', '0.f','1.f')
        fout.variables['totprcp_24hrs'][0, :, :] = filtered_prcp  

    return "Emissions file created successfully"



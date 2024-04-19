#!/bin/bash

#
#
#-----------------------------------------------------------------------
#
# Source the variable definitions file and the bash utility functions.
#
#-----------------------------------------------------------------------
#
. ${GLOBAL_VAR_DEFNS_FP}
. $USHdir/source_util_funcs.sh
#
#-----------------------------------------------------------------------
#
# Save current shell options (in a global array).  Then set new options
# for this script/function.
#
#-----------------------------------------------------------------------
#
{ save_shell_opts; set -u -x; } > /dev/null 2>&1
#
#-----------------------------------------------------------------------
#
# Get the full path to the file in which this script/function is located 
# (scrfunc_fp), the name of that file (scrfunc_fn), and the directory in
# which the file is located (scrfunc_dir).
#
#-----------------------------------------------------------------------
#
scrfunc_fp=$( readlink -f "${BASH_SOURCE[0]}" )
scrfunc_fn=$( basename "${scrfunc_fp}" )
scrfunc_dir=$( dirname "${scrfunc_fp}" )
#
#-----------------------------------------------------------------------
#
# Print message indicating entry into script.
#
#-----------------------------------------------------------------------
#
print_info_msg "
========================================================================
Entering script:  \"${scrfunc_fn}\"
In directory:     \"${scrfunc_dir}\"

This is the script for the task that runs smoke emissions preprocessing.
========================================================================"
#
#-----------------------------------------------------------------------
#
# Set the name of and create the directory in which the output from this
# script will be saved for long time (if that directory doesn't already exist).
#
#-----------------------------------------------------------------------
#
export rave_nwges_dir=${NWGES_DIR}/RAVE_INTP
mkdir -p "${rave_nwges_dir}"
export hourly_hwpdir=${NWGES_BASEDIR}/HOURLY_HWP
mkdir -p "${hourly_hwpdir}"
#
#-----------------------------------------------------------------------
#
# Link the the hourly, interpolated RAVE data from $rave_nwges_dir so it
# is reused
#
#-----------------------------------------------------------------------
# Set essential commands
DATE='/bin/date'
LN='/bin/ln'
ECHO='/bin/echo'
SED='/bin/sed'

# Prepare date and time variables
START_DATE=$($ECHO "${CDATE}" | $SED 's/\([[:digit:]]\{2\}\)$/ \1/')
YYYYMMDDHH=$($DATE +%Y%m%d%H -d "${START_DATE}")
YYYYMMDD=${YYYYMMDDHH:0:8}
HH=${YYYYMMDDHH:8:2}

# Define additional date variables
current_day=$($DATE -d "$YYYYMMDD" "+%Y%m%d")
current_hh=$($DATE -d "$HH" +"%H")
prev_hh=$($DATE -d "$current_hh -24 hour" +"%H")
previous_day=$($DATE '+%C%y%m%d' -d "$current_day-1 days")

# Link the hourly, interpolated RAVE data from RAVE_INTP directory
for i in $(seq 0 23); do
    timestr=$($DATE +%Y%m%d%H -d "$previous_day + $i hours")
    intp_fname=${PREDEF_GRID_NAME}_intp_${timestr}00_${timestr}59.nc
    if [ -f "${NWGES_DIR}/RAVE_INTP/${intp_fname}" ]; then
        $LN -sf "${NWGES_DIR}/RAVE_INTP/${intp_fname}" "${workdir}/${intp_fname}"
        echo "${NWGES_DIR}/RAVE_INTP/${intp_fname} interpolated file available to reuse"
    else
        echo "${NWGES_DIR}/RAVE_INTP/${intp_fname} interpolated file not available to reuse"
    fi
done

# Link RAVE data to the work directory as EMC workdir is set up different
previous_2day=`${DATE} '+%C%y%m%d' -d "$current_day-2 days"`
YYYYMMDDm1=${previous_day:0:8}
YYYYMMDDm2=${previous_2day:0:8}
if [ -d "${FIRE_RAVE_DIR}/${YYYYMMDDm1}/rave" ]; then
    fire_rave_dir_work=$workdir
    ln -s "${FIRE_RAVE_DIR}/${YYYYMMDD}/rave/RAVE-HrlyEmiss-3km_*" "${fire_rave_dir_work}/."
    ln -s "${FIRE_RAVE_DIR}/${YYYYMMDDm1}/rave/RAVE-HrlyEmiss-3km_*" "${fire_rave_dir_work}/."
    ln -s "${FIRE_RAVE_DIR}/${YYYYMMDDm2}/rave/RAVE-HrlyEmiss-3km_*" "${fire_rave_dir_work}/."
else
    fire_rave_dir_work=${FIRE_RAVE_DIR}
fi

# Check whether the RAVE files need to be split into hourly files
# Format the current day and hour properly for UTC
ebb_dc=${EBB_DCYCLE}
if [ "$ebb_dc" -eq 1 ]; then
    ddhh_to_use="${current_day}${current_hh}"
    dd_to_use="${current_day}"
else
    ddhh_to_use="${previous_day}${prev_hh}"
    dd_to_use="${previous_day}"
fi

# Construct file names and check their existence
intp_fname="${fire_rave_dir_work}/RAVE-HrlyEmiss-3km_v2r0_blend_s${ddhh_to_use}00000_e${dd_to_use}23*"
intp_fname_beta="${fire_rave_dir_work}/Hourly_Emissions_3km_${ddhh_to_use}00_${dd_to_use}23*"

echo "Checking for files in directory: $fire_rave_dir_work"

# Find files matching the specified patterns
files_found=$(find "$fire_rave_dir_work" -type f \( -name "${intp_fname##*/}" -o -name "${intp_fname_beta##*/}" \))

if [ -z "$files_found" ]; then
    echo "No files found matching patterns."
else
    echo "Files found, proceeding with processing..."
    for file_to_use in $files_found; do
        echo "Using file: $file_to_use"
        for hour in {00..23}; do
            output_file="${fire_rave_dir_work}/Hourly_Emissions_3km_${dd_to_use}${hour}00_${dd_to_use}${hour}00.nc"
            if [ -f "$output_file" ]; then
                echo "Output file for hour $hour already exists: $output_file. Skipping..."
                continue
            fi
            echo "Splitting data for hour $hour..."
            ncks -d time,$hour,$hour "$file_to_use" "$output_file"
        done
        echo "Hourly files processing completed for: $file_to_use"
    done
fi

# Run Python script for generating emissions#
python -u  ${USHdir}/generate_fire_emissions.py \
  "${FIX_SMOKE_DUST}/${PREDEF_GRID_NAME}" \
  "${fire_rave_dir_work}" \
  "${workdir}" \
  "${PREDEF_GRID_NAME}" \
  "${EBB_DCYCLE}" 
export err=$?; err_chk

#Copy the the hourly, interpolated RAVE data to $rave_nwges_dir so it
# is maintained there for future cycles.
for file in ${workdir}/*; do
   filename=$(basename "$file")
   if [ ! -f ${rave_nwges_dir}/${filename} ]; then
      cp ${file} ${rave_nwges_dir}
      echo "Copied missing file: $filename" 
   fi
done

echo "Copy RAVE interpolated files completed"

#
#-----------------------------------------------------------------------
#
# Print exit message.
#
#-----------------------------------------------------------------------
#
print_info_msg "
========================================================================
Exiting script:  \"${scrfunc_fn}\"
In directory:    \"${scrfunc_dir}\"
========================================================================"
#
#-----------------------------------------------------------------------
#
# Restore the shell options saved at the beginning of this script/function.
#
#-----------------------------------------------------------------------
#
{ restore_shell_opts; } > /dev/null 2>&1

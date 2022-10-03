##############################################################################################################
# The script is to login Taiwania1/3 for Lumerical FDTD automatic optimization
#
# Required steps before running optimization:
# 1. Prepare the paired public-private key (ssh-keygen -t ecdsa @ cluster server) and chmod the private key @ local PC for only current PC user to scp
# 2. Create OTP.exe by the command "go build -o OTP.exe main.go" for extraction of time-dependent password.
#       Note that the required "secret" of OTP within main.go can be obtained from the URL by using QR code reader.
# 3. Install AHK and Lumerical software @ local PC; Install Lumerical software @ cluster server by "sh *.sh" with .gz file in the folder "~/LumFile"
# 4. Create <AHK_FILEPATH>\refresh.ahk with the contents of "run <AHK_FILEPATH>\login_for_tasks.ahk" and "return".
#       Note that refresh.ahk should be run before the lumerical optimization. '\\' for python and AHK, '/' for Linux
# 5. Resource configuration in FDTD-solution should be double checked and modified for the desired parameters.
# 6. Note that the "optimization"/"sweep" name should be exactly named as "optimization"/"sweep", respectively.
# 7. Never click on the job for viewing job progress
# 8. Users should renew or re-create the 'FDTD::ports::port *' under linux OS and fetch back to local Win PC for latter optimization, to avoid the issue of compatibility.
#
# Copyright, Ryan(Sheldon) Chung, from IPL (Integrated Photonics Laboratory), EE2-354, NTU (National Taiwan University), Aug, 2021.
##############################################################################################################
# NOTE: The IPL(EE2-354, NTU) members (the ones who reside or work in China are EXCLUDED) are allowed to use this py file for lumerical optimization.
##############################################################################################################
import sys
import subprocess
from time import sleep
from os.path import split, splitext, expanduser, abspath, join, exists
from pathlib import PurePosixPath
import re
import datetime

## Global Variable
USER_NAME = '*********' # usernames can dynamically be assigned with: import getpass; getpass.getuser() 
USER_PSW = '************'       # avoid the char '!' due to the bug of ControlSend over AHK
USER_EMAIL = 'd08941008@ntu.edu.tw'

SCP_KEY = 'H:\\Taiwania\\Connect\\Acc2\\Twnia3\\id_ecdsa'
OTP_EXEPATH = 'H:\\Taiwania\\Connect\\Acc2\\OTP.exe'     # Named with OTP2.exe instead of taiwania.exe to avoid char \t
# TOTPsecret = 'WZNK5ZVUUTKDZN5RCAMUTNECJA6S6KAAPYMX4IAYJNG......'     
# old account: extract from the google authenticator with the use of python script: https://github.com/scito/extract_otp_secret_keys
# new account: extract from the URL by using QR code reader

AHK_EXEPATH = 'G:\\Program Files\\AutoHotkey\\AutoHotkeyU64.exe'

# SSH_LOGIN = f'{USER_NAME}@203.145.216.55'     # @twnia3.nchc.org.tw
SSH_LOGIN = f'{USER_NAME}@203.145.216.51'       # @t3-c1.nchc.org.tw
SCP_LOGIN = f'{USER_NAME}@203.145.216.61'

PATH_TRANSLATION = ('J:\\Taiwania\\Simulation', '/work/********/Work') # use unix-style path deliminters '/'. Use this in the case that there is a shared file system on a windows machine to a linux cluster, or if the host machine has different mount points for the shared directory.

REMOTE_FDTDIMPI_PATH = '/home/********/tools/lumerical/v221/bin/fdtd-engine-impi-lcl'

# QUEUE_LIST = ['ct8k', 'ct2k', 'ctest']
QUEUE_LIST = ['ct560']
# N_NODES_LIST = [41,11, 6]
N_NODES_LIST = [10]
# WALLTIME_LIST = [48, 72, 0.5]     # hrs
WALLTIME_LIST = [48]     # hrs
WALLTIME_MAX = '01:00:00'       # if no need, then comment it

JOBNAME = ''
N_PARTICLES, SWEEP, DIVISION = 10, 10, 1       # set N_PARTICLES = DIVISION for totally parallel computing
                                                                                    # set N_PARTICLES = SWEEP for only sweep without optimization
                                                                                    # set SWEEP = 0 for only optimization without inner sweep
assert(type(DIVISION) == int and DIVISION > 0)

######################################## End of Global Variable ##########################################
def log(msg):
    t = datetime.datetime.now().isoformat()
    print('************************ ' + t + ' ************************\n' + msg + '\n\n')
    sys.stdout.flush()


def posix_path(p):
    return str(PurePosixPath(p))


def remote_path_substitution(local_path):
    filepath, filename = split(local_path)
    remote_path = None
    remote_path = join(filepath.replace(PATH_TRANSLATION[0], PATH_TRANSLATION[1]), filename) # abspath forces unix-style delimiters
    remote_path = posix_path(remote_path).replace('\\', '/')
    log(f'local_path = \n{local_path}\nremote_path = \n{remote_path}')
    return remote_path


def parse_submission_script(submission_script_lines):
# expects a quoted path for a file with extension ['.fsp', '.icp', '.lms', '.ldev']
    local_path = ''
    filename = ''
    basename = ''
    for i in range(len(submission_script_lines)):
        line = submission_script_lines[i]
        # filepath must be a double-quoted string
        quoted_args = re.findall('"([^"]*)"', line)     # find the double-quoted filePath in each line of list
        if (len(quoted_args) > 0):
            for arg in quoted_args:
                if any(arg.endswith(file_extension) for file_extension in ['.fsp', '.icp', '.lms', '.ldev']):
                    local_path = arg
                    filename = split(local_path)[1]
                    basename = splitext(filename)[0]
                    submission_script_lines[i] = line.replace(local_path, remote_path_substitution(local_path.replace('/', '\\')))
                    break
    if not basename:
        raise Exception('A project file (.fsp, .ipc, .lms, .ldev) was not found in the provided arguments: {}'.format(submission_script))
    assert(local_path != '')
    assert(filename != '')
    assert(basename != '')
    return submission_script_lines, local_path.replace('/', '\\'), filename.replace('/', '\\'), basename


def avoid_dos2unix_bug(local_path):
    WINDOWS_LINE_ENDING = b'\r\n'
    UNIX_LINE_ENDING = b'\n'
    with open(local_path, 'rb') as fih:
        content = fih.read()
    content = content.replace(WINDOWS_LINE_ENDING, UNIX_LINE_ENDING)
    with open(local_path, 'wb') as foh:
        foh.write(content)


def qstat(local_log_path):
    line0 = 'test'
    while 1:
        try:    # bug_fix:: to avoid the portion-download issue when readlines() is called
            with open(local_log_path, 'r') as fih:
                lines = fih.readlines()
                for line in reversed(lines):
                    if '100% complete.' in line:
                        return 1
                    elif '% complete. Max time remaining: ' in line:
                        if line0 != line:
                            log(line)
                            sys.stdout.flush()
                            line0 = line
                        break       # to only break for loop
        except FileNotFoundError or OSError:
            pass
        except PermissionError:
            log('PermissionError')      # bug_fix:: to avoid the portion-download issue when readlines() is called
            sys.stdout.flush()
        except Exception as e:
            log('ExceptionError: ' + e)
            sys.stdout.flush()
        sleep(5)


def run_job(submission_script_lines):
    ## writeout sh file
    local_sh_path, remote_filepath, basename = write_sh_files(submission_script_lines)
    local_filepath = split(local_sh_path)[0]        # root path of the local files, i.e. H:/Taiwania/Simulation/date_2021_0516/bentDCslab_48_optimizationg26
    
    ## login_mkdir, logout_upload, and login_submit if it's the first particle of the generation
    if local_sh_path.split('.')[-1] == 'sh':        # if it's the first particle of the generation
        log('Login for tasks (Distributed Computing)......' if DIVISION == 1 else 'Login for tasks (Distributed & Parallel Computing)......')
        login_for_tasks(remote_filepath, local_filepath)
        log(f'All tasks are done and simulation results are downloaded @ \n{local_filepath}')
    
    ## check and update the status of the simulation for each particle
    local_log_path = local_filepath + '\\' + basename + '_p0.log'		# for different particle, different particle with different basename
    log(f'Checking and updating the status @ \n{local_log_path}')
    qstat(local_log_path)
    log(f'{basename} has been 100% completed.')
	
    ## done
    sys.stdout.flush()


def login_for_tasks(remote_filepath, local_filepath):
    n_each_division = N_PARTICLES//DIVISION
    log(f'login_for_tasks::local_filepath = \n{local_filepath}')
    log(f'login_for_tasks::remote_filepath = \n{remote_filepath}')
    
    local_best_path = split(local_filepath)[0] + '\\*best*.fsp'
    local_bestAlign_path = local_filepath + '\\bestAlign.txt'
    remote_best_filepath = split(remote_filepath)[0]
    putbestcmd = ' '.join(  ['scp', '-i', SCP_KEY, local_best_path, SCP_LOGIN + ':' + remote_best_filepath]  )
    local_batputbest_path = local_filepath + '\\putbestcmd.bat'
    
    local_headAlign_path = local_filepath + '\\headAlign.txt'
    headAlignCmd = 'echo Cmd started @ %date%:%time% >> ' + local_headAlign_path
    local_batheadAlign_path = local_filepath + '\\headAlign.bat'
    
    local_uploadAlign_path = local_filepath + '\\allUploaded.txt'
    putfspcmd = ' '.join(  ['scp', '-i', SCP_KEY, local_filepath+'\\*.fsp', SCP_LOGIN + ':' + remote_filepath]  )
    putshcmd = ' '.join(  ['scp', '-i', SCP_KEY, local_filepath+'\\*.sh', SCP_LOGIN + ':' + remote_filepath]  )
    local_batputcmd_path = local_filepath + '\\putcmd.bat'
    
    loopbreak_jobidAlign_str = '    if ('
    for idx, queue in enumerate(QUEUE_LIST):
        for division in range(DIVISION):
            jobidStr = queue + str(division)
            loopbreak_jobidAlign_str = loopbreak_jobidAlign_str + ' and ' + jobidStr + ' != ""' if idx+division != 0 else loopbreak_jobidAlign_str + jobidStr + ' != ""'
    loopbreak_jobidAlign_str = loopbreak_jobidAlign_str + '){'
    
    local_txtAlign_path = local_filepath + '\\zallJobidDownloaded.txt'
    gettxtcmd = ' '.join(  ['scp', '-i', SCP_KEY, SCP_LOGIN + ':' + remote_filepath + '/*.txt', local_filepath]  )
    local_batgettxtcmd_path = local_filepath + '\\gettxtcmd.bat'
    
    if_logAlign_strlist = []
    for division in range(DIVISION):
        path = local_filepath + '\\zallCompleted' + str(division) + '.log'
        if_logAlign_strlist.append('    if (FileExist("' + path + '") and ct' + str(division) + ' = 0){')
        
    if_fspAlign_strlist = []
    for division in range(DIVISION):
        path = local_filepath + '\\zallDownloaded' + str(division) + '.fsp'
        if_fspAlign_strlist.append('    if ((not FileExist("' + path + '")) and ct' + str(division) + ' = 1){')
    
    getlogcmd = ' '.join(  ['scp', '-i', SCP_KEY, SCP_LOGIN + ':' + remote_filepath + '/*.log', local_filepath]  )
    local_batgetlogcmd_path = local_filepath + '\\getlogcmd.bat'
    
    loopbreak_fspAlign_str = '    if ('
    for division in range(DIVISION):
        path = local_filepath + '\\zallDownloaded' + str(division) + '.fsp'
        loopbreak_fspAlign_str = loopbreak_fspAlign_str + ' and FileExist("' + path + '")' if division > 0 else loopbreak_fspAlign_str + 'FileExist("' + path + '")'
    loopbreak_fspAlign_str = loopbreak_fspAlign_str + '){'

    local_batgetfspcmdlist_path = []
    ## to avoid the bug of path in the list for writing in the batch files
    for division in range(DIVISION):
        getallfspcmd = ' '.join(  ['scp', '-i', SCP_KEY, SCP_LOGIN + ':' + remote_filepath + '/d' + str(division) + '/*.fsp', local_filepath]  )
        local_batgetfspcmd_path = local_filepath + '\\getfspcmd' + str(division) + '.bat'
        local_batgetfspcmd_path = write_bat_files(local_batgetfspcmd_path, [getallfspcmd])
        local_batgetfspcmdlist_path.append(  local_batgetfspcmd_path  )
    
    local_endingAlign_path = local_filepath + '\\zallDownloaded.txt'
    endingAlignCmd = 'echo All tasks completed @ %date%:%time% >> ' + local_endingAlign_path
    local_batendingAlign_path = local_filepath + '\\endingAlign.bat'        # to align the progress of AHK and python for closing cmd window
    
    # require upload/download time = 1000ms/5000ms * 2/3 = 2/15 seconds for each fsp file
    t_upload, t_download = 1000, 11000   # unit in ms
    ct_upload, ct_download = 3, 7
    if SWEEP == N_PARTICLES:    # only sweep
        uploadResetCT = ct_upload*SWEEP
        downloadResetCT = ct_download*SWEEP//DIVISION
    else:       # either opt&sweep or only opt
        uploadResetCT = ct_upload*N_PARTICLES*SWEEP if SWEEP != 0 else ct_upload*N_PARTICLES
        downloadResetCT = ct_download*N_PARTICLES//DIVISION*SWEEP if SWEEP != 0 else ct_download*N_PARTICLES//DIVISION
    
    # path for ahk in Win should be joined with '\\'
    ahk_lines = [
    '#NoEnv  ; Recommended for performance and compatibility with future AutoHotkey releases.', 
    '#SingleInstance Force', 
    '; #Warn  ; Enable warnings to assist with detecting common errors.', 
    'SendMode Input  ; Recommended for new scripts due to its superior speed and reliability.', 
    'SetWorkingDir %A_ScriptDir%  ; Ensures a consistent starting directory.', 
    '', 
    'SetKeyDelay, 0, 35',   # to avoid the bug of ControlSend
    'Run, C:\\Windows\\System32\\cmd.exe, , Min, PID', 
    'Winwait, ahk_pid %PID%',   # necessary for ControlSend
    'DoubleCmd(PID, "echo Start cmd @ `%date`%:`%time`% >> ' + local_headAlign_path + '")', 
    'Run, ' + write_bat_files(local_batheadAlign_path, [headAlignCmd]) + ',, Hide', 
    'Sleep 1000', 
    ## mkdir
    'OTP1 := Login(PID)', 
    'DoubleCmd(PID, "rm -r ' + remote_filepath + '")', 
    'DoubleCmd(PID, "rm -r ' + remote_filepath.split('0p')[0]+'*' + '")', 
    'DoubleCmd(PID, "mkdir -p ' + remote_filepath + '")', 
    'DoubleCmd(PID, "cd; cd ' + remote_filepath + '")', 
    ## put files
    'ct := 0', 
    'ctk := 0', 
    'While not FileExist("' + local_uploadAlign_path + '"){', 
    '    DoubleCmd(PID, "echo Uploading all files @ $(date) >> ./' + split(local_uploadAlign_path)[1] + '")', 
    '    Sleep ' + str(t_upload), 
    '    if (ct = 0) {', 
    '        Run, ' + write_bat_files(local_batputcmd_path, [putfspcmd, putshcmd, gettxtcmd]) + ',, Min', 
    '        Sleep 5000', 
    '        ct := 1', 
    '    }', 
    '    if (ct = 1) {', 
    '        ctk += 1', 
    '        ControlSend, , cd; cd ' + remote_filepath + '{Enter}, ahk_pid %PID%', 
    '        if (ctk > ' +  str(uploadResetCT) + ') {',     # bug_fix:: upload failure
    '            ctk := 0', 
    '            ct := 0', 
    '        }', 
    '    }', 
    '}'
    ]
    for idx, queue in enumerate(QUEUE_LIST):
        for division in range(DIVISION):
            ahk_lines.append(queue + str(division) + ' := ""')
    ahk_lines.extend([
    ## submit job
    'Loop {',       # bug_fix:: job submit failure
    loopbreak_jobidAlign_str, 
    '        break', 
    '    }'        # end loopbreak
    ])
    for idx, queue in enumerate(QUEUE_LIST):
        for division in range(DIVISION):
            ahk_lines.extend([
            '    if (' + queue + str(division) + ' = "") {', 
            '        ControlSend, , sbatch *' + queue + str(division) + '.sh >> ' + queue + str(division) + '.txt{Enter}, ahk_pid %PID%', 
            '        Sleep 3600', 
            '    }'
            ])
    ahk_lines.extend([
    '    Run, ' + write_bat_files(local_batgettxtcmd_path, [gettxtcmd]) + ',, Hide', 
    '    Sleep 2500'
    ])
    for idx, queue in enumerate(QUEUE_LIST):
        for division in range(DIVISION):
            ahk_lines.append('    ' + queue + str(division) + ' = ExtractJobID("' + queue + str(division) + '.txt")')
    ## exit and upload
    ahk_lines.extend([
    '}',    # end Loop
    'ControlSend, , exit{Enter}, ahk_pid %PID%', 
    # 'Sleep 1000', 
    # 'ControlSend, , echo Start uploading the best fsp file @ `%date`%:`%time`%  ......{Enter}, ahk_pid %PID%', 
    # 'Run, ' + write_bat_files(local_batputbest_path, [putbestcmd, "echo Finished uploading  the best @ %date%:%time%>> " + local_bestAlign_path]) + ',, Hide', 
    ## get files
    't := ' + str(t_download), 
    'Sleep 1000'
    ])
    for division in range(DIVISION):
        ahk_lines.extend([
        'ct' + str(division) + ' := 0', 
        'ctk' + str(division) + ' := 0'
        ])
    ahk_lines.extend([
    'ControlSend, , echo Start downloading log files @ `%date`%:`%time`%  ......{Enter}, ahk_pid %PID%', 
    'Loop {',       # Start downloading log and fsp files
    loopbreak_fspAlign_str, 
    '        break', 
    '    }',        # end loopbreak_fspAlign_str
    '    Run, ' + write_bat_files(local_batgetlogcmd_path, [getlogcmd]) + ',, Hide', 
    '    Sleep %t%'
    ])
    if len(QUEUE_LIST) > 1:
        ahk_lines.extend([
        '    if (FileExist("' + local_filepath + '\\*.log") and t = ' + str(t_download) + '){',  # QUEUE_LIST[0] is running simulation
        '        t := ' + str(t_download-300), 
        '        OTP2 := Login(PID, OTP1)', 
        '        if FileExist("' + local_filepath + '\\' + QUEUE_LIST[0] + '.log"){'
        ])
        for idx, queue in enumerate(QUEUE_LIST):
            if idx != 0:
                for division in range(DIVISION):
                    ahk_lines.extend([
                    '            ControlSend, , scancel %' + queue + str(division) + '%{Enter}, ahk_pid %PID%', 
                    '            Sleep 1000', 
                    '            ControlSend, , scancel %' + queue + str(division) + '%{Enter}, ahk_pid %PID%', 
                    '            Sleep 1000'
                    ])
        ahk_lines.append('        }')            # end FileExist(QUEUE_LIST[0])
        for i_queue in range(1, len(QUEUE_LIST), 1):
            ahk_lines.append('        else if FileExist("' + local_filepath + '\\' + QUEUE_LIST[i_queue] + '.log"){')   # QUEUE_LIST[the rest] is running simulation
            for idx, queue in enumerate(QUEUE_LIST):
                if idx != i_queue:
                    for division in range(DIVISION):
                        ahk_lines.extend([
                        '            ControlSend, , scancel %' + queue + str(division) + '%{Enter}, ahk_pid %PID%', 
                        '            Sleep 1000', 
                        '            ControlSend, , scancel %' + queue + str(division) + '%{Enter}, ahk_pid %PID%', 
                        '            Sleep 1000'
                        ])
            ahk_lines.append('        }')   # end FileExist(QUEUE_LIST[i_queue])
        ahk_lines.extend([
        '        ControlSend, , exit{Enter}, ahk_pid %PID%', 
        '    }'
        ])       # end FileExist(*.log)
    ## start downloading fsp files if the specific division simulations are completed based on the existance of zallCompleted${division}.log
    for division in range(DIVISION):            # bug_fix:: job running failure @ cluster, download failure; To reduce the download time
        ahk_lines.extend([
        if_logAlign_strlist[division], 
        '        ControlSend, , echo Start downloading fsp files part ' + str(division+1) + ' out of ' + str(DIVISION) + ' @ `%date`%:`%time`% ......{Enter}, ahk_pid %PID%', 
        '        Run, ' + local_batgetfspcmdlist_path[division] + ',, Min', 
        '        ct' + str(division) + ' := 1', 
        '    }',      # end if_logAlign_strlist
        if_fspAlign_strlist[division], 
        '        ctk' + str(division) + ' += 1', 
        '        if (ctk' + str(division) + ' > ' +  str(downloadResetCT) + ') {', 
        '            ctk' + str(division) + ' := 0', 
        '            ct' + str(division) + ' := 0', 
        '        }',        # end if ctk$i = count times while ct = 1
        '    }',      # end if not fileexist(fsp) and ct$i = 1
        ''
        ])
    ahk_lines.extend([
    '}', # end Loop and all log and fsp files are downloaded at this moment
    'Run, ' + write_bat_files(local_batendingAlign_path, [endingAlignCmd]) + ',, Hide', 
    'ControlSend, , exit{Enter}, ahk_pid %PID%',    # exit the cmd terminal
    'return', 
    '', 
    '', 
    '', 
    'DoubleCmd(PID, cmd){', 
    '    ControlSend, , %cmd%{Enter}, ahk_pid %PID%', 
    '    Sleep 800', 
    '    ControlSend, , %cmd%{Enter}, ahk_pid %PID%', 
    '    Sleep 1000', 
    '}', 
    '', 
    'Login(PID, oldOTP := 0){', 
    '    ControlSend, , ssh ' + SSH_LOGIN + '{Enter}, ahk_pid %PID%', 
    '    Sleep 1000', 
    '    ControlSend, , ' + USER_PSW + '{Enter}, ahk_pid %PID%', 
    '    Sleep 1500', 
    '    newOTP:= ExtractOTP()', 
    '    While (newOTP = oldOTP){', 
    '        Sleep 2000', 
    '        newOTP:= ExtractOTP()', 
    '    }', 
    '    ControlSend, , %newOTP%{Enter}, ahk_pid %PID%', 
    '    Sleep 3000', 
    '    return newOTP', 
    '}', 
    '', 
    'ExtractOTP(){', 
    '    return ComObjCreate("WScript.Shell").Exec("' + OTP_EXEPATH + '").StdOut.ReadAll()', 
    '}', 
    '', 
    'ExtractJobID(fname){', 
    '    FileRead, content, %fname%', 
    '    StringSplit, lines, content, `n', 
    '    StringSplit, jobarray, lines1, " "', 
    '    return jobarray4', 
    '}', 
    ''
    ])
    with open(local_filepath + '\\login_twnia3_for_tasks.ahk', 'w') as foh:
        foh.write('\n'.join(ahk_lines))
        foh.write('\n')
    log(f'Finished writing the ahk file @ \n{local_filepath}\\login_twnia3_for_tasks.ahk')
    sys.stdout.flush()
    while not exists(local_headAlign_path):       # to avoid the bug of not executing login_for_tasks.ahk
        log(f'Calling login_twnia3_for_tasks.ahk......')
        subprocess.call([AHK_EXEPATH, local_filepath + '\\login_twnia3_for_tasks.ahk'])
        sleep(20)
    while not exists(local_endingAlign_path):     # to align the progress between AHK and python
        sleep(3)
    sleep(3)        # to have response time to close cmd.exe
    return 1


def write_bat_files(local_path, cmd_lines):
    with open(local_path, 'w') as foh:
        foh.write('\n'.join(cmd_lines))
        foh.write('\n')
    log(f'Finished writing bat file @ \n{local_path}')
    sys.stdout.flush()
    return local_path
    

def write_sh_files(submission_script_lines, Email = USER_EMAIL, mailOption = 'ae', queue = 'ctest', jobname = JOBNAME):
    submission_script_lines, local_path, filename, basename = parse_submission_script(submission_script_lines)
    for line in submission_script_lines:        # note that submission_script_lines represents the lines after replacement action
        if line.split('optimizationg')[-1].split('.fsp')[0].split('sweep')[0].split('_')[-1] == '1' and line.split('_')[-1] == '1.fsp"':        # if it's the first particle
            log(f'Line for the first particle (after replacement): \n{line}')
            g = int(  line.split('optimizationg')[-1].split('_')[0]  )
        elif len(line.split('optimizationg')) == 1 and line.split('_')[-1] == '1.fsp"':
            log(f'Line for the first sweep (after replacement): \n{line}')
            g = 0       # for only sweep without optimization
        elif line.split('.')[-1] == 'fsp"':													# if it's not the first particle
            log(f'Line for the rest particles or sweeps (after replacement): \n{line}')
            return [local_path, filename, basename]
        # Email = line.split('-M ')[-1] if len(line.split('-M ')) > 1 else Email
        # mailOption = line.split('-m ')[-1] if len(line.split('-m ')) > 1 else mailOption
        # jobname = line.split('-N ')[-1] if len(line.split('-N ')) > 1 else jobname
    local_filepath = split(local_path)[0].replace('/', '\\')
    remote_filepath = remote_path_substitution(local_filepath).replace('\\', '/')
    remote_remove_filepath = remote_filepath.replace('optimizationg'+str(g), 'optimizationg'+str(g-1)) if g > 1 else ''
    n_each_division = N_PARTICLES // DIVISION
    forStr = []
    for division in range(DIVISION):
        n_particles_endStr = str((division+1)*n_each_division) if division != DIVISION-1 else str(N_PARTICLES)
        forStr.append('for i in {' + str(1+division*n_each_division) + '..' + n_particles_endStr + '}')
    
    if SWEEP*g > 0:
        rm1st_line = 'rm ${WORKFOLDER}/d0/*_1sweep_1_p0.log'
        exec1st_line = 'mpiexec.hydra $ENGINE ${WORKFOLDER}/d0/*_1sweep_1.fsp; cp ${WORKFOLDER}/d0/*.log $WORKFOLDER'
        logfname = 'optimizationg' + str(g) + '_${i}sweep_${j}_p0.log'
    else:
        rm1st_line = 'rm ${WORKFOLDER}/d0/*_1_p0.log'
        exec1st_line = 'mpiexec.hydra $ENGINE ${WORKFOLDER}/d0/*_1.fsp; cp ${WORKFOLDER}/d0/*.log $WORKFOLDER'
        if SWEEP == 0:  # only opt
            logfname = 'optimizationg' + str(g) + '_${i}_p0.log'
        else:
            logfname = 'sweep_${i}_p0.log'

    for idx, queue in enumerate(QUEUE_LIST):
        for division in range(DIVISION):
            if SWEEP*g > 0:
                cpStr = '        cp ${WORKFOLDER}/*_${i}sweep_${j}.fsp ${WORKFOLDER}/d' + str(division)
                execStr = 'mpiexec.hydra $ENGINE ${WORKFOLDER}/d' + str(division) + '/*_${i}sweep_${j}.fsp'
            else:
                cpStr = '    cp ${WORKFOLDER}/*_${i}.fsp ${WORKFOLDER}/d' + str(division)        # either g = 0 for only sweep or SWEEP = 0 for only opt
                execStr = 'mpiexec.hydra $ENGINE ${WORKFOLDER}/d' + str(division) + '/*_${i}.fsp'
            # ifforStr = '        logfname=./d' + str(division) + '/' + logfname + '\n        for k in {1..12}\n        do\n            if grep -q "FlexNet Licensing error" "$logfname" || grep -q "failure with the license" "$logfname"; then\n                echo license failure @ $(date) >> ./d' + str(division) + '/' + logfname.replace('p0', 'p0failure') + '\n                sleep 5\n                ' + execStr + '\n            fi\n        done'
            ifforStr = '        logfname=./d' + str(division) + '/*' + logfname + '\n        for k in {1..12}\n        do\n            if grep -q "FlexNet Licensing error" $logfname || grep -q "failure with the license" $logfname; then\n                echo license failure @ $(date) >> ./d' + str(division) + '/' + logfname.replace('p0', 'p0failure') + '\n                sleep 5\n                ' + execStr + '\n            fi\n        done'
            sh_script_lines = [
            '#!/bin/bash', 
            '#SBATCH -A MST107345', 											# login and use the command for Taiwania1: get_su_balance
            '#SBATCH -J ' + jobname + 'g' + str(g) + 'd' + str(division+1) + '/' + str(DIVISION), 
            '#SBATCH -p ' + queue, 
            '#SBATCH -n ' + str(56*N_NODES_LIST[idx]), 
            '#SBATCH --time=' + WALLTIME_MAX if 'WALLTIME_MAX' in globals() else ''
            '#SBATCH -c 1', 
            '#SBATCH -N ' + str(N_NODES_LIST[idx]), 
            '#SBATCH --mail-type BEGIN,END', 
            '#SBATCH --mail-user ' + USER_EMAIL, 
            '#SBATCH -o %j.out', 
            '#SBATCH -e %j.err', 
            '', 
            'ENGINE=' + REMOTE_FDTDIMPI_PATH,  
            'WORKFOLDER=' + remote_filepath, 
            '', 
            'echo Simulation g' + str(g) +  'd' + str(division+1) + '/' + str(DIVISION) + ' started @ $(date) >> ${WORKFOLDER}/' + queue + '.log', 
            'rm -r ' + remote_remove_filepath if g > 1 else '', 		# remove all the former-generation files (including the folder)
            'mkdir -p ${WORKFOLDER}/d' + str(division), 
            '', 
            'module load compiler/intel/2020u4 IntelMPI/2020', 
            '', 
            forStr[division], 
            'do', 
            '    for j in {1..' + str(SWEEP) + '}' if SWEEP*g > 0 else '', 
            '    do' if SWEEP*g > 0 else '', 
            cpStr + '; ' + execStr, 
            ifforStr, 
            '        cp ${WORKFOLDER}/d' + str(division) + '/*.log $WORKFOLDER', 
            '    done' if SWEEP*g > 0 else '', 
            'done', 
            rm1st_line + '; ' + exec1st_line if division == 0 and len(QUEUE_LIST) > 1 else '', 
            'echo All simulation are completed @ $(date) >> ${WORKFOLDER}/zallCompleted' + str(division) + '.log', 
            'echo All fsp files are downloaded @ $(date) >> ${WORKFOLDER}/d' + str(division) + '/zallDownloaded' + str(division) + '.fsp'
            ]
            local_sh_path = local_filepath + '\\' + basename.split('_')[0] + '_' + queue + str(division) + '.sh'
            with open(local_sh_path, 'w') as foh:
                foh.write('\n'.join(sh_script_lines))
                foh.write('\n')
            avoid_dos2unix_bug(local_sh_path)
            log(f'Finished writing sh file @ \n{local_sh_path}')
            sys.stdout.flush()
    return [local_sh_path, remote_filepath, basename]


if __name__ == '__main__':
    # submission_script_lines = ['#!/bin/bash', '#PBS -P MST107345', '#PBS -l select=1:ncpus=40:mpiprocs=40', '#PBS -N test', '#PBS -j oe', '#PBS -M d08941008@ntu.edu.tw', '#PBS -m abe', '#PBS -q ctest', '#PBS -p 0', 'module load intel/2018_u1', 'export I_MPI_HYDRA_BRANCH_COUNT=-1', 'mpiexec.hydra /home/d08941008/tools/lumerical/v212/bin/fdtd-engine-impi-lcl "H:/Taiwania/Simulation/y110d0816/bentDCslab_optimizationg5/optimizationg5_1sweep_1.fsp"']
    submission_script_lines = sys.stdin.read().splitlines()       # list
    run_job(submission_script_lines)
    
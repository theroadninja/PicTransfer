# diskutil.py
"""
Utility methods for dealing with disks

TODO: the unit tests for this class create temp files
AND dont even bother to clean them up.
"""
import inspect
import math
import os
import shlex
import subprocess
from subprocess import PIPE

def to_lines(stdout):
    lines = [line.strip() for line in stdout.split("\n")]
    return [line for line in lines if line != ""]


def human_readable(bytecount):
    """
    returns a "human readable" string that should match the output of df.
    
    had to write this because df doesnt seem to have an option to print
    bytes (by default it prints block size

    >>> import math
    >>> human_readable(0)
    '0B'
    >>> human_readable(1023)
    '1023B'
    >>> human_readable(1024)
    '1KB'
    >>> human_readable(1025)
    '1KB'
    >>> human_readable(2047)
    '1KB'
    >>> human_readable(2048)
    '2KB'
    >>> human_readable(2049)
    '2KB'
    >>> human_readable(3071)
    '2KB'
    >>> human_readable(3072)
    '3KB'
    >>> human_readable(1024 * 1024 - 1)
    '1023KB'
    >>> human_readable(1024 * 1024)
    '1MB'
    >>> human_readable(1024 * 1024 * 1024)
    '1GB'
    >>> human_readable(int(math.pow(1024, 4)))
    '1TB'
    >>> human_readable(int(math.pow(1024, 4)) * 2)
    '2TB'
    >>> human_readable(int(math.pow(1024, 5)))
    '1PB'
    >>> human_readable(int(math.pow(1024, 6)))
    '1EB'
    >>> human_readable(int(math.pow(1024, 7)))
    '1024EB'
    """
    if bytecount < 0:
        raise ValueError()

    df_sizes = ["B", "KB", "MB", "GB", "TB", "PB", "EB"]
    prefix = 0
    while bytecount >= 1024 and prefix < len(df_sizes) - 1:
        bytecount //= 1024
        prefix += 1
    return "{}{}".format(bytecount, df_sizes[prefix])
   

hr = human_readable    


def avail_space(path):
    stats = os.statvfs(path)
    # SO:  most of the stuff returned by statvfs is in "frag size"
    # units and NOT in number of blocks, because multiple fragments
    # can be store in a block.
    
    # # not useful: blocksize = stats.f_bsize
    # fragsize = stats.f_frsize
    # # f_blocks is in f_frsize units!
    # total_bytes = stats.f_blocks * fragsize
    # free_bytes = stats.f_bfree * fragsize
    # print(stats)
    # print("block size: {}".format(blocksize))
    # print("total bytes: {}".format(human_readable(total_bytes)))
    # print("total free bytes: {}".format(human_readable(free_bytes)))
    # print("percentage free bytes: {}".format(stats.f_bfree / stats.f_blocks))
    # print("total free bytes available: {}".format(human_readable(stats.f_bavail * fragsize)))
    
    # fragsize * available fragments to user
    return stats.f_frsize * stats.f_bavail


def get_volume_list():
    """:returns: list of removable media"""
    mypath = os.path.dirname(os.path.abspath(inspect.stack()[0][1]))
    cmdpath = os.path.join(mypath, "findflash.macos.sh")
    cmd = shlex.split(cmdpath)
    p = subprocess.Popen(cmd, shell=False, stdout=PIPE, stderr=PIPE, stdin=PIPE, text=True)
    stdout, stderr = p.communicate()
    if p.returncode != 0:
        print(stderr)
        sys.exit(1)
    else:
        return to_lines(stdout)


def alt_folder(simplename, digits=2, start=1):
    """
    Find an alternate folder by incrementing a digit

    TODO:  unit test using temp files

    so for folder1:
        folder1
        folder1_01
        folder1_02
        folder1_03
        ...
        folder1_99
    >>> import tempfile
    >>> import re
    >>> folder = tempfile.mkdtemp(suffix="dtest")
    >>> os.makedirs(os.path.join(folder, "1"))
    >>> alt = alt_folder(folder, digits=1)
    >>> re.sub(r"^.*dtest", "dtest", alt)
    'dtest_1'
    >>> os.makedirs(os.path.join(folder, alt))
    >>> alt = alt_folder(folder, digits=1)
    >>> re.sub(r"^.*dtest", "dtest", alt)
    'dtest_2'
    >>> os.makedirs(os.path.join(folder, alt))
    >>> alt = alt_folder(folder, digits=1)
    >>> re.sub(r"^.*dtest", "dtest", alt)
    'dtest_3'
    >>> re.sub(r"^.*dtest", "dtest", alt_folder(folder, digits=3))
    'dtest_001'
    >>> alt = alt_folder(folder, digits=1, start=9)
    >>> re.sub(r"^.*dtest", "dtest", alt)
    'dtest_9'
    >>> os.makedirs(os.path.join(folder, alt))
    >>> alt = alt_folder(folder, digits=1, start=9)
    ... #doctest: +IGNORE_EXCEPTION_DETAIL
    Traceback (most recent call last):
        ...
    Exception: ...
    """
    if not simplename:
        raise ValueError()
    if digits < 1 or start < 0:
        raise ValueError()
    simplename = simplename.rstrip("/")
    stop = int(math.pow(10, digits))
    for alt in range(start, stop):
        altfolder = "{}_{}".format(simplename, str(alt).zfill(digits))
        if not os.path.isdir(altfolder):
            return altfolder
    raise Exception("cannot find alternate folder for {}".format(simplename))


if __name__ == "__main__":
    import doctest
    doctest.testmod()

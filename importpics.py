#!/usr/bin/env python3
"""
Copies picture files taken by a camera from removable media like
flash, automatically creating new folders based on dates.
"""

import argparse
import collections
import datetime
import inspect
import hashlib
import os
import pathlib
import re
import shlex
import subprocess
from subprocess import PIPE
import sys
import time

import exifread
from dateutil.parser import parse

YYMMDD = "%y%m%d"

try: raw_input = input
except NameError: pass


class Metrics:
    def __init__(self):
        self.started = int(time.time())

    def __str__(self):
        lines = []
        elapsed_sec = int(time.time()) - started
        lines.append("Total time: {} seconds".format(elapsed_sec))
        return "\n".join(lines)

def prompt(msg, default):
    if default is None:
        return raw_input("{}>".format(msg))
    else:
        choice = raw_input("{} [{}]>".format(msg, default))
        return choice or default

def parse_camera_date(datestr):
    """
    Nikon cameras seem to use this restarted format for dates:
        2020:01:02 16:11:06
    and that seems to break both dateutil and dateparser.
    So I have to manually provite a format :(

    :param datestr: date string from EXIF metadata

    >>> parse_camera_date("2020:01:02 16:11:06")
    datetime.datetime(2020, 1, 2, 16, 11, 6)
    """
    if re.match(r"^\s*\d\d+:\d\d:\d\d\s+\d\d:\d\d:\d\d\s*$", datestr):
        # its in the stupid nikon format
        datestr = datestr.replace(":", "-", 2)
    return parse(datestr)
    pass

def get_destpath(cfgfolder, cfgfile):
    cfgfolder = os.path.expanduser(cfgfolder)
    cfgfile = os.path.join(cfgfolder, cfgfile)

    destpath = None
    if os.path.isfile(cfgfile):
        with open(cfgfile, 'r') as f:
            lines = [line.strip() for line in f.readlines()]
        for line in lines:
            if line.startswith("destpath="):
                destpath = os.path.expanduser(line.split("=")[1])
    chosen_path = prompt("Enter path to copy files to", destpath)

    chosen_path = os.path.expanduser(chosen_path)

    # if it doesnt exist but its in their home folder, give them option to auto-create
    if chosen_path.startswith(os.path.expanduser("~/")) and not os.path.exists(chosen_path):
        yn = raw_input("{} does not exist.  Should I create it? y/N>".format(chosen_path)).strip().lower()
        if yn in ["y", "yes"]:
            os.mkdir(chosen_path)
        else:
            print("exiting")
            sys.exit(1)

    # verify chosen path
    if os.path.isdir(chosen_path) and not chosen_path.startswith("/Volumes"):
        pass
    else:
        print("cant copy to {}".format(chosen_path))

    if chosen_path != destpath:
        # TODO - this is blowing away the file
        if not os.path.isdir(cfgfolder):
            os.mkdir(cfgfolder)
        with open(cfgfile, 'w') as f:
            f.write("destpath={}\n".format(chosen_path))
    return chosen_path


def choose_volume(volumes):
    print("select which disk to import from (or ctrl+c to exit)")
    choices = {}
    for i, item in enumerate(volumes):
        choices[i] = item
        print("{}) {}".format(i, item))

    while True:
        try:
            choice = int(raw_input("enter selection>"))
            return choices[choice]
        except KeyboardInterrupt as ex:
            raise ex
        except:
            print("that was not a valid choice -- press ctrl+c if you want to exit")


def to_lines(stdout):
    lines = [line.strip() for line in stdout.split("\n")]
    return [line for line in lines if line != ""]


def ext_match(filename, extensions):
    if filename is None:
        raise ValueError

    for ext in extensions:
        if filename.lower().endswith(ext.lower()):
            return True
    return False


def all_pics(path, extensions = None):
    extensions = extensions or ["jpg", "nef", "png", "gif", "tiff"]
    #print(os.listdir(path))
    pics = []
    for root, dirs, files in os.walk(path, topdown = True):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if ext_match(f, extensions):
                pics.append(os.path.join(root, f))
    return pics


def cam_hash(tags):
    cam_tags = ["Image Make", "Image Model", "MakerNote SerialNumber"]
    cam_values = { tag: str(tags[tag]) for tag in tags.keys() if tag in cam_tags }
    s = ""
    # sort to keep the hash stable even if exif tags in a different order
    for k in sorted(cam_values.keys()):
        s += cam_values[k]
    prefix = ""
    if "nikon" in s.lower():
        prefix = "nik"
    return prefix + hashlib.md5(bytes(s, "utf-8")).digest().hex()[-6:]
    
def exif_date(tags):
    date_tags = ["Image DateTime", "EXIF DateTimeOriginal", "EXIF DateTimeDigitized"]

    dates = { tag: str(tags[tag]) for tag in tags.keys() if tag in date_tags }
    # sort so that we always attempt to read the values in the same order
    # reversed because I comes after E
    for k in reversed(sorted(dates.keys())):
        return parse_camera_date(dates[k])

    raise Exception("unable to read EXIF date of image")



def exif_tags(filename):
    if not filename.lower().endswith("jpg"):
        raise ValueError

    with open(filename, 'rb') as f:
        tags = exifread.process_file(f)
    return tags

    #date_tags = ["Image DateTime", "EXIF DateTimeOriginal", "EXIF DateTimeDigitized"]

    #for tag in tags.keys():
    #    pass
    #    #if tag in cam_tags:
    #    #    print(tag, str(tags[tag]))

    #    #if len(str(tags[tag])) < 1024:
    #    #    print(tag, str(tags[tag]))

    #    #if tag in date_tags:
    #    #    print(tag, str(tags[tag]))

    #    #if not tag.startswith("MakerNote"):
    #    #    if "Date" in tag or "date" in tag or "time" in tag or "Time" in tag:
    #    #        print(tag + " " + str(tags[tag]))


def get_dest_subfolder(tags, dateformat):
    return "{}_{}".format(
        exif_date(tags).strftime(dateformat),
        cam_hash(tags)
    )


class CopyLog:
    def __init__(self, folder):
        self.copied_files = set()
        self.folder = folder
        logfile = "copiedfiles.{}.{}.log".format(
            os.getpid(),
            int(time.time()),
        )
        self.logfile = os.path.join(folder, logfile)
        self.fh = None

    def __enter__(self):
        self.fh = open(self.logfile, 'a')
        return self

    def __exit__(self, extype, exval, trace):
        self.fh.flush()
        self.fh.close()

    def add(self, copied_path):
        if self.fh is None:
            raise Exception("must call __enter__ before calling add")
        self.fh.write(copied_path)
        self.fh.write("\n")
        # TODO: should we update copied_files ? in theory shouldnt need to...

    def already_copied(self, *copied_path):
        if len(copied_path) < 1:
            raise ValueError()

        for path in copied_path:
            if not path in self.copied_files:
                return False
        return True

    @staticmethod
    def load(folder):
        folder = os.path.expanduser(folder)
        if not os.path.exists(folder):
            os.makedirs(folder)

        clog = CopyLog(folder)
        entries = os.listdir(folder)
        for e in entries:
            fn = os.path.join(folder, e)
            if os.path.isfile(fn) and fn.lower().endswith(".log"):
                with open(fn, 'r') as f:
                    lines = [line.strip() for line in f.readlines()]
                    clog.copied_files.update(lines)
        return clog

class FileGroup:
    """A group of files representing a single picture"""
    def __init__(self):
        self.files = []
        self.base_path = None

    def append(self, path):
        self.files.append(path)
        if self.base_path is None:
            self.base_path = self.basepath(path)
        elif self.base_path != self.basepath(path):
            raise Exception("something went wrong")

    def __iter__(self):
        return self.files.__iter__()

    def jpg(self):
        jpgs = [f for f in self.files if f.lower().endswith(".jpg")]
        if len(jpgs) != 1:
            raise Exception("wrong number of jpg files")
        return jpgs[0]
                
    @staticmethod
    def basepath(path):
        return str(pathlib.Path(path).with_suffix(""))


class CopyPlan:
    def __init__(self, lookback_days, started_dt = None):
        if lookback_days < 1:
            raise ValueError()
        self.lookback_days = lookback_days
        self.started_dt = started_dt or datetime.datetime.now()

    def in_lookback(self, dt):
        """
        Returns True if the date is within the lookback period
        >>> CopyPlan(3, datetime.datetime(2010, 6, 20)).in_lookback(datetime.datetime(2010, 6, 20))
        True
        >>> CopyPlan(3, datetime.datetime(2010, 6, 20)).in_lookback(datetime.datetime(2010, 6, 19))
        True
        >>> CopyPlan(3, datetime.datetime(2010, 6, 20)).in_lookback(datetime.datetime(2010, 6, 18))
        True
        >>> CopyPlan(3, datetime.datetime(2010, 6, 20)).in_lookback(datetime.datetime(2010, 6, 17))
        True
        >>> CopyPlan(3, datetime.datetime(2010, 6, 20)).in_lookback(datetime.datetime(2010, 6, 16))
        False
        """
        return (self.started_dt.date() - dt.date()).days <= self.lookback_days

def try_copy(copyplan, copylog, fg):
    """
    Tries to ensure all pictures files in the file group are copied
    :param copylog: the log that tracks if files have already been copied
    :param fg: object representing the group of files to copy
    """
    if copylog.already_copied(*fg):
        print("Already copied: {}".format(fg.base_path))
        return

    tags = exif_tags(fg.jpg())
    d = exif_date(tags)
    if not copyplan.in_lookback(d):
        print("Too old to copy: {}".format(fg.base_path))
        return

    print(d.strftime(YYMMDD))
    print(fg.base_path)
    for f in fg:
        if copylog.already_copied(f):
            print("\t Already copied file: {}".format(f))
        else:
            copylog.add(f)
            print("\t{}".format(f))
            #print(get_dest_subfolder(tags, YYMMDD))


def copy_pictures(logsfolder, picfiles, lookback_days):
    copyplan = CopyPlan(lookback_days)

    def name(path):
        return str(pathlib.Path(path).with_suffix(""))

    #groups = collections.defaultdict(list)
    groups = collections.defaultdict(FileGroup)
    for p in picfiles:
        #groups[name(p)].append(p)
        groups[FileGroup.basepath(p)].append(p)

    with CopyLog.load(logsfolder) as copylog:
        for g in groups.keys():
            try_copy(copyplan, copylog, groups[g])


def show_info():
    pass


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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--test", action="store_true", default=False, help="run unit tests")
    parser.add_argument("--info", action="store_true", default=False, help="dont cp, just show file info")
    parser.add_argument("-d", "--days", type=int, default=7, help="how many days ago to look for pictures")
    args = parser.parse_args()

    started = time.time()
    metrics = Metrics()

    if args.test:
        import doctest
        doctest.testmod()
        sys.exit(0)

    if args.info:
        volume_list = get_volume_list()
        volume_path = choose_volume(volume_list)
        pics = all_pics(volume_path)
        for p in pics:
            if p.lower().endswith(".jpg"):
                tags = exif_tags(p)
                print(get_dest_subfolder(tags, YYMMDD))
                date_tags = ["Image DateTime", "EXIF DateTimeOriginal", "EXIF DateTimeDigitized"]
                dates = { tag: str(tags[tag]) for tag in tags.keys() if tag in date_tags }
                
                print(["{}=={}".format(d, parse(d)) for d in dates.values()])
        print(metrics)
        sys.exit(0)



    cfgfolder = "~/.importpics"
    logsfolder = "~/.importpics/copylogs"

    #mypath = os.path.dirname(os.path.abspath(inspect.stack()[0][1]))
    #cmdpath = os.path.join(mypath, "findflash.macos.sh")
    #cmd = shlex.split(cmdpath)
    #p = subprocess.Popen(cmd, shell=False, stdout=PIPE, stderr=PIPE, stdin=PIPE, text=True)
    #stdout, stderr = p.communicate()
    #if p.returncode != 0:
    #    print(stderr)
    #    sys.exit(1)

    #yymmdd = "%y%m%d"
    #d.strftime("%y%m%d")


    if False:
        testpic = "/Volumes/NIKON D4/DCIM/205NC_D4/DSC_5376.JPG"
        tags = exif_tags(testpic)
        #print(exif_date(tags).strftime(yymmdd))
        #print(cam_hash(tags))
        print(get_dest_subfolder(tags, YYMMDD))
        sys.exit(0)

    volume_list = get_volume_list()
    volume_path = choose_volume(volume_list)
    pics = all_pics(volume_path)
    #for p in pics:
    #    print(p)
    #    #if p.lower().endswith(".jpg"):
    #    #    tags = exif_tags(p)
    #    #    print(get_dest_subfolder(tags, yymmdd))
    #    #else:
    #    #    print(p)

    try:
        destpath = get_destpath(cfgfolder = cfgfolder, cfgfile = "importpicscfg")
        print("chosen path is: " + destpath)
    except KeyboardInterrupt:
        sys.exit(1)

    copy_pictures(logsfolder, pics, args.days)

    elapsed_sec = int(time.time() - started)
    print("Total time: {} seconds".format(elapsed_sec))
    # TODO - print total file paths seen
   





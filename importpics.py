#!/usr/bin/env python3

import argparse
import collections
from dateutil.parser import parse
import inspect
import hashlib
import os
import pathlib
import shlex
import subprocess
from subprocess import PIPE
import sys
import time

import exifread

try: raw_input = input
except NameError: pass


def prompt(msg, default):
    if default is None:
        return raw_input("{}>".format(msg))
    else:
        choice = raw_input("{} [{}]>".format(msg, default))
        return choice or default

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
    for k in sorted(dates.keys()):
        return parse(dates[k])

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
    def __init__(self):
        self.copied_files = []
        self.logfile = "copiedfiles.{}.{}.log".format(
            os.getpid(),
            int(time.time()),
        )
        self.fh = None

    def __enter__(self):
        self.fh = open(self.logfile, 'a')

    def __exit__(self, extype, exval, trace):
        self.fh.flush()
        self.fh.close()

    def add(self, copied_path):
        if self.fh is None:
            raise Exception("must call __enter__ before calling add")
        self.fh.write(copied_path)
        self.fh.write("\n")

    @staticmethod
    def load(folder):
        # TODO
        return CopyLog()


def copy_pictures(logsfolder, picfiles):
    logsfolder = os.path.expanduser(logsfolder)
    if not os.path.exists(logsfolder):
        os.makedirs(logsfolder)

    # TODO - first see if the path is in the log

    # TODO - also need to group them by base filename

    # str(pathlib.Path("/home/dave/a.txt").with_suffix(""))
    def name(path):
        return str(pathlib.Path(path).with_suffix(""))

    groups = collections.defaultdict(list)

    for p in picfiles:
        groups[name(p)].append(p)
        #print(p)

    copylog = CopyLog.load(logsfolder)
    #with CopyLog.load(logsfolder) as copylog:
    with copylog:
        for g in groups.keys():
            print(g)
            for f in groups[g]:
                copylog.add(f)
                print("\t{}".format(f))


if __name__ == "__main__":
    cfgfolder = "~/.importpics"
    logsfolder = "~/.importpics/copylogs"

    mypath = os.path.dirname(os.path.abspath(inspect.stack()[0][1]))
    cmdpath = os.path.join(mypath, "findflash.macos.sh")
    cmd = shlex.split(cmdpath)
    p = subprocess.Popen(cmd, shell=False, stdout=PIPE, stderr=PIPE, stdin=PIPE, text=True)
    stdout, stderr = p.communicate()
    if p.returncode != 0:
        print(stderr)
        sys.exit(1)

    yymmdd = "%y%m%d"
    #d.strftime("%y%m%d")

    started = time.time()

    if False:
        testpic = "/Volumes/NIKON D4/DCIM/205NC_D4/DSC_5376.JPG"
        tags = exif_tags(testpic)
        #print(exif_date(tags).strftime(yymmdd))
        #print(cam_hash(tags))
        print(get_dest_subfolder(tags, yymmdd))
        sys.exit(0)

    volume_path = choose_volume(to_lines(stdout))
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

    copy_pictures(logsfolder, pics)

    elapsed_sec = int(time.time() - started)
    print("Total time: {} seconds".format(elapsed_sec))
   





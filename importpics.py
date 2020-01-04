#!/usr/bin/env python3
"""
Copies picture files taken by a camera from removable media like
flash, automatically creating new folders based on dates.

Warning: this has to read all filenames into memory at once (in
order to match jpg and nef files together, etc)

TODO: not sure how the file size checking code will behave with a network file
system....
"""

# STL
import argparse
import collections
import datetime
import hashlib
import logging
import os
import pathlib
import re
import shlex
import shutil
import sys
import time
import traceback

# LIB
import exifread
from dateutil.parser import parse

# PROJ
import diskutil

YYMMDD = "%y%m%d"

try: raw_input = input
except NameError: pass


class Metrics:
    """
    Tracks metrics like how long it took to run, and how many files were copied.
    """
    def __init__(self):
        self.started = int(time.time())
        self.total_seen = None
        self.already_copied = None
        self.too_old = None
        self.copied = 0
        self.failed = []
        self.file_existed = [] # not in copy log, but existed with correct size

        self.start_disk_avail = None # in bytes
        self.end_disk_avail = None
        self.alt_folders = []

    def inc_already_copied(self, items = None):
        items = items or [1]
        if self.already_copied is None:
            self.already_copied = 0
        self.already_copied += len(items)

    def inc_too_old(self, items = None):
        items = items or [1]
        if self.too_old is None:
            self.too_old = 0
        self.too_old += len(items)

    def inc_copied(self, items = None):
        items = items or [1]
        self.copied = self.copied or 0
        self.copied += len(items)

    def __str__(self):
        lines = []
        elapsed_sec = int(time.time()) - self.started
        lines.append("Total time: {} seconds".format(elapsed_sec))
        def p(msg, count):
            if count is not None:
                lines.append(msg.format(count))
        lines.append("Files copied successfully: {}".format(self.copied))
        lines.append("")
        p("Total picture files found: {}", self.total_seen)
        p("Already copied: {}", self.already_copied)
        p("Skipped because files already existed: {}", len(self.file_existed))
        p("Too old to copy: {}", self.too_old)
        lines.append("Files failed to copy: {}".format(len(self.failed)))
        for f in self.failed:
            lines.append("\t{}".format(f))
        if self.start_disk_avail is not None:
            avail = diskutil.human_readable(self.start_disk_avail)
            lines.append("Disk space available before copy: {}".format(avail))
        if self.end_disk_avail is not None:
            avail = diskutil.human_readable(self.end_disk_avail)
            lines.append("Disk space available after copy: {}".format(avail))
        if self.alt_folders:
            lines.append("Alternate folders created:")
            for f in self.alt_folders:
                lines.append("\t{}".format(f))
        return "\n".join(lines)

def prompt(msg, default):
    """
    Displays a prompt and returns user input.
    :param msg: the message to display to the user
    :param default: the default value to use if they hit enter without entering
        a response (default is displayed in between [])
    :return: the users response
    """
    if default is None:
        return raw_input("{}>".format(msg))
    else:
        choice = raw_input("{} [{}]>".format(msg, default))
        return choice or default

def parse_camera_date(datestr):
    """
    Parses the date string from EXIF metadata into a python datetime.

    Nikon cameras seem to use this retarded format for dates:
        2020:01:02 16:11:06
    and that seems to break both dateutil and dateparser.
    So I have to manually provide a format :(

    :param datestr: date string from EXIF metadata

    >>> parse_camera_date("2020:01:02 16:11:06")
    datetime.datetime(2020, 1, 2, 16, 11, 6)
    """
    if re.match(r"^\s*\d\d+:\d\d:\d\d\s+\d\d:\d\d:\d\d\s*$", datestr):
        # its in the stupid nikon format
        datestr = datestr.replace(":", "-", 2)
    return parse(datestr)
    pass

def confirm(msg, autoyes):
    """
    Displayes a yes/no message and returns the users response
    :param msg: messages to display
    :param autoyes: if true, confirm() returns true without waiting for user
        input (for user with --yes args)
    :returns: user yes/no response, as a boolean
    """
    msg = "{} y/N>".format(msg)
    if autoyes:
        print("{}y".format(msg))
        return True
    else:
        yn = raw_input(msg).strip().lower()
        #yn = raw_input("{} y/N>".format(msg)).strip().lower()
        return yn in ["y", "yes"]

def confirmOrDie(msg, autoyes):
    """
    Displays a confirmation message, existing with status 1 if the user does not
    response with yes.
    """
    if not confirm(msg, autoyes):
        print("Aborting")
        sys.exit(1)

def get_destpath(logger, cfgfolder, cfgfile, autoyes):
    """
    Determine the parent destination path (under with all of the day and camera
    specific subfolders are placed).
    """
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
        confirmOrDie("{} does not exist.  Create it?".format(chosen_path), autoyes)
        os.mkdir(chosen_path)

    # verify chosen path
    if os.path.isdir(chosen_path) and not chosen_path.startswith("/Volumes"):
        pass
    else:
        logger.error("cant copy to {}".format(chosen_path))
        system.exit(1)

    if chosen_path != destpath:
        # TODO - this is blowing away the file
        if not os.path.isdir(cfgfolder):
            os.mkdir(cfgfolder)
        with open(cfgfile, 'w') as f:
            f.write("destpath={}\n".format(chosen_path))
    return chosen_path


def choose_volume(volumes):
    """
    Prompts the user to select with path to import pictures from.
    """
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


def ext_match(filename, extensions):
    """
    Tests a filename extension for case-insensitive match
    """
    if filename is None:
        raise ValueError

    for ext in extensions:
        if filename.lower().endswith(ext.lower()):
            return True
    return False


def all_pics(path, extensions = None):
    """
    Recursively search a path for all files that look like the might be
    pictures.  This is based on the filename extension alone, so misnamed
    files will be missed or be false positives.
    """
    extensions = extensions or ["jpg", "nef", "png", "gif", "tiff"]
    pics = []
    for root, dirs, files in os.walk(path, topdown = True):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if ext_match(f, extensions):
                pics.append(os.path.join(root, f))
    return pics


def cam_hash(tags):
    """
    Creates a string that should uniquely identify the camera.  Since this file
    is being written for someone who primarily uses a nikon camera, a "nik" is
    prepended if the make is nikon.

    The hash is based on the make, model, and serial number, so if all of those
    are present then it should be unique, however the hash is also truncated to
    avoid creating annoyingly large filenames, so collisions could happen.
    :param tags:  dictionary of EXIF tags
    :returns: short string that is _probably_ uniq to the camera that took the
        pic.
    """
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
    """
    Determine the date the picture was taked based on certain exif
    tags.  Different cameras use different tags, so this is a best effort,
    however it is at least deterministic regardless of which order the tags appear
    :param: dictionary of EXIF tags
    :returns: datetime representing the date
    :throws: if it can't find any date tags
    """
    date_tags = ["Image DateTime", "EXIF DateTimeOriginal", "EXIF DateTimeDigitized"]

    dates = { tag: str(tags[tag]) for tag in tags.keys() if tag in date_tags }
    # sort so that we always attempt to read the values in the same order
    # reversed because I comes after E
    for k in reversed(sorted(dates.keys())):
        return parse_camera_date(dates[k])

    raise Exception("unable to read EXIF date of image")


def exif_tags(filename):
    """
    Get the EXIF metadata from a JPG
    :param filename: absolute path of the jpg, as a string
    :returns: dictionary of (exif tag name -> tag object)
    """
    if not filename.lower().endswith("jpg"):
        raise ValueError
    with open(filename, 'rb') as f:
        tags = exifread.process_file(f)
    return tags
    # Convenient way to list them:
    # for tag in tags.keys():
    #     if len(str(tags[tag])) < 1024:
    #         print(tag, str(tags[tag]))



def get_dest_subfolder(tags, dateformat):
    """
    Calculates the subfolder of a pic, based on the date and camera
    hash.  This function does not handle the alternate numbers, like
    _01 or _02; that happens later.
    """
    return "{}_{}".format(
        exif_date(tags).strftime(dateformat),
        cam_hash(tags)
    )


class CopyLog:
    """
    Manages "copy logs" -- records of which files have previously been copied,
    based on the assumption that the absolute path of a picture file written
    to a flash card by a digital camera is always unique.

    A copy log is written every time this program is run, and saved in a
    folder.  All of those logs are read by this classes and the
    previously-copied paths are merged into a single set to make it easy
    to test if a source file has already been copied.
    """
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
    """
    A group of files representing a single picture.
    This is based on my understanding of:
        "Design rule for Camera File system" (DCF)
    It seems that multiple images files might be created for a single image,
    e.g. a jpg and an nef, which will have the same basename and differ only by
    their file extensions.
    """
    def __init__(self):
        self.files = []
        self.base_path = None
        self.total_bytes = None # size in bytes of all files
        self.dest_subfolder = None # the folder with the date and cam hash
        self.dest_subfolderalt = None # alternate folder that did not exist before copying started
        self.exif_date = None # our best guess at the pic date from EXIF metadata

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
    """
    Tracks which files are going to be copied, etc.
    """
    def __init__(self, lookback_days, started_dt = None, force = False, maxpics = None):
        if lookback_days < 1:
            raise ValueError()
        if maxpics and maxpics < 1:
            raise ValueError()
        self.lookback_days = lookback_days
        self.started_dt = started_dt or datetime.datetime.now()
        self.force = force
        self.groups_to_copy = []
        self.bytes_to_copy = 0
        self.start_disk_avail = None # avail. diskspace before copy in bytes 
        self.destpath = None
        self.maxpics = maxpics

    def add(self, filegroup):
        self.groups_to_copy.append(filegroup)
        self.bytes_to_copy += filegroup.total_bytes

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

def schedule_copy(metrics, copyplan, copylog, fg):
    """
    Tries to ensure all pictures files in the file group are copied
    :param copylog: the log that tracks if files have already been copied
    :param fg: object representing the group of files to copy
    """
    if copyplan.maxpics and len(copyplan.groups_to_copy) >= copyplan.maxpics:
        logger.debug("Skipping {} because already at max number".format(fg.base_path))
        return

    if (not copyplan.force) and copylog.already_copied(*fg):
        metrics.inc_already_copied(list(fg))
        logger.debug("Already copied: {}".format(fg.base_path))
        return

    tags = exif_tags(fg.jpg())
    fg.dest_subfolder = get_dest_subfolder(tags, YYMMDD) # TODO dont re-calculate date twice
    fg.dest_subfolderalt = diskutil.alt_folder(fg.dest_subfolder)

    fg.exif_date = exif_date(tags)
    if not copyplan.in_lookback(fg.exif_date):
        metrics.inc_too_old(list(fg))
        logger.debug("Too old to copy: {}".format(fg.base_path))
        return

    fg.total_bytes = 0
    for f in fg:
        fsize = os.path.getsize(f)
        fg.total_bytes += fsize

    copyplan.add(fg)



def try_copy(metrics, copyplan, copylog, fg):
    """
    Copies all files for a picture, ensuring they will end up in the same place.
    """
    destfolder = os.path.join(copyplan.destpath, fg.dest_subfolder)
    if not os.path.isdir(destfolder):
        os.makedirs(destfolder)

    # cases:
    # - all files exist with correct size => use dest folder
    # - all files exist with correct size OR are completely missing => use dest folder and skip
    #   (should be a superset of anything involving the copylog)
    # - anything else? => copy everything to an alternate folder
    use_alt_folder = False
    for f in fg:
        fdest = os.path.join(destfolder, os.path.basename(f))
        if os.path.isdir(fdest):
            use_alt_folder = True # path is a dir somehow
        elif os.path.isfile(fdest):
            if os.path.getsize(f) != os.path.getsize(fdest):
                use_alt_folder = True # file exists with wrong size

    if use_alt_folder:
        destfolder = os.path.join(copyplan.destpath, fg.dest_subfolderalt)
        os.makedirs(destfolder)
        metrics.alt_folders.append(destfolder)
        

    for f in fg:
        fdest = os.path.join(destfolder, os.path.basename(f))
        if os.path.isfile(fdest):
            if os.path.getsize(f) == os.path.getsize(fdest):
                logger.debug("skipping {} b/c it already exists with the correct size".format(fdest))
                metrics.file_existed.append(f)
            else:
                raise Exception("logic error copying files") # this should not happen
        else:
            logger.debug("copying {} to {}".format(f, fdest))
            try:
                shutil.copy(f, fdest)
                copylog.add(f)
                metrics.inc_copied()
            except IOError:
                metrics.failed.append(fdest)
                traceback.print_exc()


def copy_pictures(logger, metrics, copyplan, logsfolder, picfiles, autoyes):
    """
    This is the main method.  Scans the pictures to figure out which ones to
    copy, and copies them.
    """
    metrics.total_seen = len(picfiles)

    def name(path):
        return str(pathlib.Path(path).with_suffix(""))

    groups = collections.defaultdict(FileGroup)
    for p in picfiles:
        groups[FileGroup.basepath(p)].append(p)

    logger.info("Scanning for files to copy...")
    with CopyLog.load(logsfolder) as copylog:
        # see which ones we can copy
        for g in groups.keys():
            schedule_copy(metrics, copyplan, copylog, groups[g])

        # TODO - check against filesystem avail
        msg = "About to copy {} pictures at {}.  Continue?".format(
            len(copyplan.groups_to_copy),
            diskutil.human_readable(copyplan.bytes_to_copy),
        )
        confirmOrDie(msg, autoyes)

        if copyplan.bytes_to_copy > copyplan.start_disk_avail:
            msg = "Warning!  {} is more than the {} available at {}.  Are you sure you want to continue?"
            msg = msg.format(
                diskutil.hr(copyplan.bytes_to_copy),
                diskutil.hr(copyplan.start_disk_avail),
                copyplan.destpath,
            )
            confirmOrDie(msg, autoyes)

        logger.info("Copying {} pictures".format(len(copyplan.groups_to_copy)))
        for group in copyplan.groups_to_copy:
            try_copy(metrics, copyplan, copylog, group)


def show_info():
    pass


def make_logger(verbose):
    logger = logging.getLogger("importpics")
    level = logging.INFO
    if args.verbose:
        level = logging.DEBUG
    logger.setLevel(level)
    logger.handlers = []
    logger.addHandler(logging.StreamHandler())
    return logger


if __name__ == "__main__":
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--test", action="store_true", default=False, help="run unit tests")
    parser.add_argument("--info", action="store_true", default=False, help="dont cp, just show file info")
    parser.add_argument("-d", "--days", type=int, default=7, help="how many days ago to look for pictures")
    parser.add_argument("-f", "--force", action="store_true", default=False, help="copy files even if logs show they were already copied")
    parser.add_argument("-n", "--number", type=int, default=None, help="Number of pictures (not number of files) to import")
    parser.add_argument("-y", "--yes", action="store_true", default=False, help="Automatically answer 'yes' to all confirmation prompts")
    parser.add_argument("-v", "--verbose", action="store_true", default=False, help="verbose logging")
    args = parser.parse_args()

    logger = make_logger(args.verbose)
    metrics = Metrics()

    if args.test:
        import doctest
        doctest.testmod()
        sys.exit(0)

    if args.info:
        volume_list = diskutil.get_volume_list()
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
    logger.info("Using copy logs in {}".format(logsfolder))

    volume_list = diskutil.get_volume_list()
    volume_path = choose_volume(volume_list)
    pics = all_pics(volume_path)

    try:
        destpath = get_destpath(logger, cfgfolder = cfgfolder, cfgfile = "importpicscfg", autoyes=args.yes)
        logger.info("chosen path is: " + destpath)
    except KeyboardInterrupt:
        sys.exit(1)

    diskavail = diskutil.avail_space(destpath)
    metrics.start_disk_avail = diskavail
    copyplan = CopyPlan(lookback_days=args.days, force=args.force, maxpics=args.number)
    copyplan.start_disk_avail = diskavail
    copyplan.destpath = destpath
    copy_pictures(logger, metrics, copyplan, logsfolder, pics, args.yes)

    metrics.end_disk_avail = diskutil.avail_space(destpath)
    print("------------------")
    print("Copy Results:")
    print(metrics)

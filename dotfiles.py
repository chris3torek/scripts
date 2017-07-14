#! /usr/bin/env python

"""
Dotfiles: set up home directory .foorc files.
"""

from __future__ import print_function

import argparse
import errno
import os.path
import shutil
import stat
import sys
# import tarfile -- not yet

# We'll check for a Dotfiles directory where this program lives.
SELF = os.path.abspath(__file__)


class FileInfo(object):
    """
    Each file that is to be manipulated is either a
    regular file, symlink, or directory.  We would like to know
    which.  If it is a directory we can keep a list of all
    its contents as well.

    To keep a list of its contents, pass a list of FileInfo
    objects as the contents entity.  This list is split into
    "regular contents" and "oddball contents"; see
    fileinfo() and get_files_from().  You must pass both!

    The name argument is the full file name (including any
    parent directory that reached this).  The mode
    is the value from getmode(), and can be None if the path
    does not exist.

    The self.filename property automatically extracts the base
    name from the full name.
    """
    def __init__(self, fullname, mode, contents=None, oddballs=None):
        # supply both contents and oddbals, or neither
        if (contents is None) != (oddballs is None):
            raise ValueError('invalid call to FileInfo')
        # only is_dir has contents
        is_dir = mode is not None and stat.S_ISDIR(mode)
        if not is_dir and contents is not None:
            raise ValueError('invalid call to FileInfo')
        self.fullname = fullname
        self.mode = mode
        self._contents = contents
        self._oddballs = oddballs
        self._cached_readlink = None

    def __str__(self):
        # doesn't (currently) annotate symlinks with @ a la "ls -F"
        return '{}{}'.format(self.filename, '/' if self.is_dir() else '')

    def __repr__(self):
        return '{}({!r}, {!r}, {!r}, {!r})'.format(
            self.__class__.__name__, self.fullname, self.mode,
            self._contents, self._oddballs)

    def strmode(self):
        "return 'file', 'directory', 'socket', etc"
        if self.mode is None:
            return 'nonexistent'
        return ftype_string(self.mode)

    def has_contents(self):
        "predicate: did we save dir contents? (false for non-dir)"
        return self._contents is not None

    def has_oddballs(self, recurse):
        "predicate: are there oddballs at this level, or lower if recurse?"
        if not self.has_contents():
            return False
        if len(self._oddballs):
            return True
        if recurse:
            return any(i.has_oddballs(recurse) for i in self._contents)
        return False

    def is_dir(self):
        "true iff this is a directory"
        return self.mode is not None and stat.S_ISDIR(self.mode)

    def is_empty_dir(self):
        "true iff this is an empty directory (no subdirs allowed even if empty)"
        if not self.is_dir():
            return False
        return len(self.contents) == 0 and len(self.oddballs) == 0

    def is_recursively_empty(self):
        "true iff this is a directory that is recursively empty"
        if not self.is_dir() or len(self.oddballs) != 0:
            return False
        for i in self.contents:
            if i.is_dir() and i.is_recursively_empty():
                continue
            return False
        return True

    def is_symlink(self):
        "true iff this is a symlink"
        return self.mode is not None and stat.S_ISLNK(self.mode)

    def read_symlink(self):
        "read target of symlink - do not use on non-symlink"
        if not self.is_symlink():
            raise ValueError('attempt to get target of '
                             '{} {!r}'.format(self.strmode(), self.fullname))
        if self._cached_readlink is None:
            self._cached_readlink = os.readlink(self.fullname)
        return self._cached_readlink

    def strip_prefix(self, prefix):
        """
        Return full name after removing given prefix
        (see general strip_prefix function).
        """
        return strip_prefix(self.fullname, prefix)

    def _dir_contents(self, which):
        "helper for contents/oddballs"
        if not self.is_dir():
            raise ValueError('attempt to get contents of '
                             '{} {!r}'.format(self.strmode(), self.fullname))
        if which is None:
            raise ValueError('attempt to get contents of '
                             'unsaved dir {!r}'.format(self.fullname))
        return which

    @property
    def filename(self):
        "really just os.path.basename(self.fullname)"
        return os.path.basename(self.fullname)

    @property
    def contents(self):
        "get regular files within directory"
        return self._dir_contents(self._contents)

    @property
    def oddballs(self):
        "get oddball files within directory"
        return self._dir_contents(self._oddballs)



def locate_dotfiles(allow_none):
    """
    Locate the Dotfiles directory.
    """
    parent = os.path.dirname(SELF)
    dotfilesdir = os.path.join(parent, 'Dotfiles')
    if os.path.isdir(dotfilesdir):
        return dotfilesdir
    if allow_none:
        return None
    print('I found myself at {}'.format(SELF), file=sys.stderr)
    print('I could not find a Dotfiles directory at {}'.format(dotfilesdir),
          file=sys.stderr)
    sys.exit(1)


def compute_relpath(within, to):
    """
    We want to link <within>/foo to <to>/foo, using a
    relative path with .. if needed and then leading
    path components elided from <to>, so that if, e.g.,
    dfdir is /home/user/x/y/z/Dotfiles and homedir is
    /home/user, we link .bashrc (in /home/user) to
    x/y/z/Dotfiles/bashrc.  This may need to climb up,
    e.g., if dfdir is /src/x/y/z/Dotfiles we must link
    to ../../src/x/y/z/Dotfiles.
    """
    # note, assumes paths are normalized and absolute
    pcf = within.split(os.path.sep) # from here...
    pct = to.split(os.path.sep)     # to here
    # first one is always empty
    while pcf and pct and pcf[0] == pct[0]:
        pcf.pop(0)
        pct.pop(0)
    # now if pcf still has components, that's how many
    # we have to climb.
    relpath = os.path.sep.join((['..'] * len(pcf)) + pct)
    return relpath


def strip_prefix(path, prefix):
    """
    Return path name after removing given prefix, if path
    name starts with said prefix (we remove the os.path.sep
    as well).

    (Note that prefix should not end with os.path.sep.)

    If the full name exactly matches the prefix, this
    still returns the full name, not the empty string.
    """
    pl = len(prefix)
    fl = len(path)
    if fl > pl and path.startswith(prefix):
        part = path[pl:]
        if part.startswith(os.path.sep):
            return part[len(os.path.sep):]
    return path


def ftype_string(mode):
    """
    Format stat.st_mode field as file-type string
    (file, directory, symlink, etc).
    """
    if stat.S_ISREG(mode):
        return 'file'
    if stat.S_ISDIR(mode):
        return 'directory'
    if stat.S_ISLNK(mode):
        return 'symlink'
    if stat.S_ISBLK(mode) or stat.S_ISCHR(mode):
        return 'device'
    if stat.S_ISFIFO(mode):
        return 'fifo'
    if stat.S_ISSOCK(mode):
        return 'socket'
    # bsd only whiteout is not supported
    return 'mystery-file-mode={:07o}' % mode


def getmode(path, use_stat=False):
    """
    Get the st_mode from os.lstat(path), but return None
    harmlessly if and only if the file does not exist.

    If use_stat is True, use os.stat instead of os.lstat,
    to allow top level Dotfiles to be existing symlinks.
    """
    try:
        statresult = (os.stat if use_stat else os.lstat)(path)
    except OSError as err:
        # OSX raises EBADF on some /dev/fdfiles instead of ENOENT
        if err.errno in [errno.ENOENT, errno.EBADF]:
            return None
        raise
    return statresult.st_mode


def allow_dir_or_file_or_symlink(mode):
    """
    Default "allow" function: allow directories, regular files,
    and symlinks.
    """
    return stat.S_ISDIR(mode) or stat.S_ISREG(mode) or stat.S_ISLNK(mode)


def _get_files_from(path, recurse, allowfn=None):
    """
    Return tuple: list of all "allowed" files in path,
    list of remaining "oddball" files.

    allowfn is the function to test for oddball-ness:
    allowed files are good, others are oddballs.

    If recurse, we get the contents of any sub-directories.

    Note that this fails (w/ OSError) if path is not a directory!
    """
    contents = []
    oddballs = []
    for name in os.listdir(path):
        fullpath = os.path.join(path, name)
        mode = getmode(fullpath)
        if mode is None:        # can't happen unless racing
            continue

        # obtain sub-directory content pair recursively if appropriate
        if stat.S_ISDIR(mode) and recurse:
            pair = _get_files_from(fullpath, recurse, allowfn)
        else:
            pair = (None, None)

        info = FileInfo(fullpath, mode, pair[0], pair[1])
        if allowfn(mode):
            contents.append(info)
        else:
            oddballs.append(info)

    return contents, oddballs


def finfo(path, recurse, allowfn=None, always=False):
    """
    Get FileInfo on path.  If it is a directory, we scan it --
    optionally recursively.  If allowfn is provided, that
    determines which files are "good" (allowed) and which
    are considered "oddball" (e.g., sockets).

    If the path represents a nonexistent file, return None,
    unless always=True, in which case, return an object with
    a None mode.

    The resulting FileInfo object saves the mode of the file,
    so the caller can tell if it's an allowed file, existing
    file, etc.
    """
    mode = getmode(path)
    if mode is None:
        if always:
            return FileInfo(path, None, None, None)
        return None
    pair = (None, None)
    if stat.S_ISDIR(mode):
        if allowfn is None:
            allowfn = allow_dir_or_file_or_symlink
        pair = _get_files_from(path, recurse, allowfn)
    return FileInfo(path, mode, pair[0], pair[1])


def blank_finfo(info):
    """
    Given an existing FileInfo for a file we intend to rename,
    unlink, rmdir, or otherwise get out of the way, make a new
    fileinfo representing a nonexistent file with the same paths.
    """
    return FileInfo(info.fullname, None, None, None)


def flatten_contents(info, postorder=False):
    """
    Given a directory FileInfo, yield all its contents.  If
    it was scanned recursively, this is includes its
    sub-directories' contents after each subdirectory.

    If you pass postorder=True, you get a post-order walk
    (yield i after contents).  The default is a pre-order
    walk.
    """
    preorder = not postorder
    for i in info.contents:
        if preorder:
            yield i
        if i.has_contents():
            # py3k: yield from flatten_contents(i)
            for j in flatten_contents(i, preorder):
                yield j
        if postorder:
            yield i


def flatten_oddballs(info):
    """
    Given a directory FileInfo, yield all its oddball files,
    and (recursively) all its normal subdirectories' oddball files.
    """
    for i in info.oddballs:
        yield i
    for i in info.contents:
        if i.is_dir():
            # py3k: yield from flatten_oddballs(i)
            for j in flatten_oddballs(i):
                yield j


def rmtree(tgtinfo, rmdirs, rmfiles):
    """
    Remove all files and directories, recursively.

    We don't actually do it here, just add it to our
    instruction-set.
    """
    if tgtinfo.is_dir():
        for subfile in flatten_contents(tgtinfo):
            if subfile.is_dir():
                rmdirs.append(subfile)
            else:
                rmfiles.append(subfile)
        rmdirs.append(tgtinfo)
    else:
        rmfiles.append(tgtinfo)

def transliterate(toppath, subfile, newtop):
    """
    Turn a sub-file of the given top path into a "new subfile"
    of the new top path.
    """
    subpath = subfile.strip_prefix(toppath.fullname)
    newpath = os.path.join(newtop.fullname, subpath)
    return FileInfo(newpath, None)


def clean_copy(srcinfo, tgtinfo, mkdirs, cpfiles):
    """
    tgtinfo represents a non-existent directory, which
    we must make to make directory srcinfo.  We then
    copy, recursively, all files and sub-directories
    from srcinfo into tgtinfo.

    Note that tgtinfo fullname may be, e.g., .vim while
    srcinfo.fullname is just vim - we mkdir the dot version.
    Subfile names do not get treated this way.

    We don't actually do it here, just add it to our
    instruction-set.
    """
    if srcinfo.is_dir():
        mkdirs.append(tgtinfo)
        for subfile in flatten_contents(srcinfo):
            # Strip srcinfo path prefix off, and replace with
            # a prefix made from tgtinfo instead.
            newtgt = transliterate(srcinfo, subfile, tgtinfo)
            if subfile.is_dir():
                mkdirs.append(newtgt)
            else:
                cpfiles.append((subfile, newtgt))
    else:
        cpfiles.append((srcinfo, tgtinfo))


def match_dirs(srcinfo, tgtinfo, mkdirs, rmdirs, rmfiles):
    """
    rmdir any target dir where it does not have a corresponding
    src dir.  mkdir any target dir where src dir exists but does
    not have a corresponding tgt dir.

    Note: tgtinfo may even be a file, and may contain files;
    if it has files, we remove all of them.

    Note: srcinfo may be an ordinary file, in which case we
    remove the top level tgt dir too.

    We don't actually do it here, just add it to our
    instruction-set.
    """
    if tgtinfo.is_dir():
        tgt_dirs = []
        # use postorder walk, in case we want to remove everything
        for info in flatten_contents(tgtinfo, postorder=True):
            if info.is_dir():
                # if src is dir, accumulate target dirs;
                # otherwise remove all target dirs
                if srcinfo.is_dir():
                    tgt_dirs.append(info)
                else:
                    rmdirs.append(info)
            else:
                # always remove all existing target files
                # (to get them out of the way)
                rmfiles.append(info)
    else:
        rmfiles.append(tgtinfo)

    # if source is not a dir, we're done
    if not srcinfo.is_dir():
        return

    # sort dirs by full path name
    tgt_dirs = sorted(tgt_dirs, key = lambda e: e.fullname)
    src_dirs = sorted((i for i in flatten_contents(srcinfo)
                           if i.is_dir()), key = lambda e: e.fullname)
    # run the list backwards so that we remove x/top after x/top/sub
    # (forward sort always lists subdirs after their containing dir)
    while src_dirs and tgt_dirs:
        sdir = src_dirs[-1]
        tdir = tgt_dirs[-1]
        if sdir == tdir:
            # both exist, so we are OK
            src_dirs.pop()
            tgt_dirs.pop()
            continue
        # example: if src=['a', 'b', 'c'] and tgt=['a', 'b', 'd'],
        # we will have sdir='c', tdir='d'
        if sdir < tdir:
            # tdir is extra, so rmdir it
            rmdirs.append(tdir)
            tgt_dirs.pop()
        else:
            # sdir is missing, so mkdir it
            mkdirs.append(transliterate(srcinfo, sdir, tgtinfo))
            src_dirs.pop()
    # any remaining src dirs are missing
    for sdir in src_dirs:
        mkdirs.append(transliterate(srcinfo, sdir, tgtinfo))
    # any remaining tgt dirs are extra
    for tdir in tgt_dirs:
        rmdirs.append(tdir)


def copy_files(srcinfo, tgtinfo, cpfiles):
    """
    Copy any src file (directories are already matched up).

    We don't actually do it here, just add it to our
    instruction-set.
    """
    if srcinfo.is_dir():
        for subfile in flatten_contents(srcinfo):
            if not subfile.is_dir():
                cpfiles.append((subfile, subfile))
    else:
        cpfiles.append((srcinfo, tgtinfo))


def make_rename_name(path):
    """
    Given a file path (e.g., /path/to/foo) that does exist, find
    another name (/path/to/foo.<suffix>) that does not exist.
    """
    dirname = os.path.dirname(path)
    basename = os.path.basename(path)
    i = 0
    while True:
        i += 1
        tpath = os.path.join(dirname, '{}.{}'.format(basename, i))
        if getmode(tpath) is None:
            return tpath
        # todo, perhaps: if i > 10; try reading dir?


def install(relpath, dfdir, homedir, dryrun, force):
    """
    Install (or print about installing) dot-files in home directory.
    Home directory names are '.file' which become symlinks to
    os.path.join(relpath, 'file'), e.g., $HOME/.vimrc -> $dfdir/vimrc

    The dfdir argument is where the to-be-installed dotfiles
    come from.  We simply read its contents, so that if it
    contains a file named vimrc, we will create a '.vimrc'.

    If relpath is None, we copy files into place
    (instead of making symlinks).

    If force is set, we can rename or even blow away existing
    incorrect files (including removing directories recursively!).
    (If the dry run option is set we'll just say that we
    would do this.)  Force is actually a counter: set it
    twice, and we don't bother keeping the originals.

    Note: if there is a long path in some name <name>, we may
    need to make directories in homedir, e.g., <name> may be
    'vim/after/ftplugin/c.vim' in which case we need to create
    create <homedir>/.vim/after/ftplugin.  It's OK if this exists
    now, as long as it is a directory.

    In any case we, make two passes, one to see what to do,
    and one to actually install.
    """
    # Get file info about dfdir.  If there are any problematic
    # files in there, complain about them and stop.
    # (If relpath is None, get file list recursively.)
    recurse = relpath is None
    info = finfo(dfdir, recurse)
    if info is None:
        print('cannot install from {!r}: no such directory'.format(dfdir),
              file=sys.stderr)
        return 1
    if not info.is_dir():
        print('cannot install from {} {!r}: not a '
              'directory'.format(info.strmode(), dfdir),
              file=sys.stderr)
        return 1
    # can always check for this recursively, even if we didn't recurse
    if info.has_oddballs(recurse=True):
        print('cannot install from {} due to:'.format(dfdir), file=sys.stderr)
        bad = sorted(flatten_oddballs(info), key=lambda e: e.fullname)
        for i in bad[:9]:
            print('  {!r}: {}'.format(i.strip_prefix(dfdir), i.strmode()),
                  file=sys.stderr)
        if len(bad) > 9:
            print('... and {} more'.format(len(bad) - 9), file=sys.stderr)
        return 1

    # OK, info is a directory and there are no oddball files.  If
    # relpath is not None, info.contents may have sub-directories with
    # unknown contents (e.g., '.vim'); if relpath is None, it may have
    # such dirs, but with known contents.
    #
    # Make lists of all the work we want to do.
    renames = []
    rmdirs = []
    rmfiles = []
    mkdirs = []
    cpfiles = []
    symlinks = []
    errors = 0

    for srcinfo in info.contents:
        tgtname = '.' + srcinfo.filename
        tgtpath = os.path.join(homedir, tgtname)
        # gather recursive scan of everything at the target path
        tgtinfo = finfo(tgtpath, recurse=True,
                        allowfn=lambda mode: True, always=True)

        if tgtinfo.mode is None:
            # Target doesn't exist; all we do is copy or symlink,
            # and that will take care of everything.
            if relpath is None:
                clean_copy(srcinfo, tgtinfo, mkdirs, cpfiles)
            else:
                symlinks.append((srcinfo, tgtinfo))
            continue

        # Target exists.  Now what?
        if tgtinfo.is_symlink():
            # It's a symlink.  Do we want a symlink?
            if relpath is None:
                # We don't want a symlink.  If force, schedule rm
                # and pretend it's gone, so we can do a clean copy
                # into place.
                if force:
                    rmfiles.append(tgtinfo)
                    tgtinfo = blank_finfo(tgtinfo)
                    clean_copy(srcinfo, tgtinfo, mkdirs, cpfiles)
                    continue
                # Fall through to other tests below, to complain
                # about the symlink in the way.
            else:
                # We do want a symlink.  If it's good, leave it alone.
                # If it's wrong, schedule to replace it with the
                # right one.  Either one will finish the work.
                dstlink = os.path.join(relpath, srcinfo.filename)
                if tgtinfo.read_symlink() != dstlink:
                    rmfiles.append(tgtinfo)
                    symlinks.append((srcinfo, tgtinfo))
                continue

        # Target exists and is not symlink (is dir, file,
        # device, whatever).
        if force:
            if relpath is not None:
                # We're symlinking top level files.
                # Just rename any non-empty directory or ordinary file;
                # or remove empty tree, or rm -r if --force --force.
                if tgtinfo.is_recursively_empty() or force > 1:
                    rmtree(tgtinfo, rmdirs, rmfiles)
                else:
                    renames.append(tgtinfo)
                # can just re-use tgtinfo here now, that's safe
                symlinks.append((srcinfo, tgtinfo))
                continue

            # We're copying all the files.  If the target
            # dir is recursively empty, remove any unwanted
            # subdirs (that are in the way of any wanted files)
            # and leave or create any subdirs needed (for
            # wanted files).
            if tgtinfo.is_recursively_empty() or force > 1:
                # remove any unwanted dirs and files;
                # add any missing empty dirs
                match_dirs(srcinfo, tgtinfo, mkdirs, rmdirs, rmfiles)
                # and copy all regular files
                copy_files(srcinfo, tgtinfo, cpfiles)
            else:
                # tgt has files - rename it to get it out of the way
                renames.append(tgtinfo)
                tgtinfo = blank_finfo(tgtinfo)
                # now, cleanly mkdir directories and copy files
                clean_copy(srcinfo, tgtinfo, mkdirs, cpfiles)
            continue

        # Target exists, and force not set.
        if errors == 0:
            print('error: cannot install to {}:'.format(homedir),
                  file=sys.stderr)
        print('  {} {!r} is in the way'.format(tgtinfo.strmode(),
                                               tgtinfo.strip_prefix(homedir)),
              file=sys.stderr)
        errors += 1

    if errors:
        return 1

    # Now do, or just show (dryrun), all the file manipulations.
    dryrun = True # XXX
    if dryrun:
        print('cd {}'.format(homedir))

    for info in renames:
        # pick a new name from the existing name
        path = os.path.join(homedir, info.fullname)
        newpath = make_rename_name(path)
        if dryrun:
            print('mv {!r} {!r}'.format(strip_prefix(path, homedir),
                                        strip_prefix(newpath, homedir)))
        else:
            os.rename(path, newpath)

    for info in rmfiles:
        path = os.path.join(homedir, info.fullname)
        if dryrun:
            print('rm {!r}'.format(strip_prefix(path, homedir)))
        else:
            os.unlink(path)

    for info in rmdirs:
        path = os.path.join(homedir, info.fullname)
        if dryrun:
            print('rmdir {!r}'.format(strip_prefix(path, homedir)))
        else:
            os.rmdir(path)

    for info in mkdirs:
        path = os.path.join(homedir, info.fullname)
        if dryrun:
            print('mkdir {!r}'.format(strip_prefix(path, homedir)))
        else:
            os.mkdir(path, 0o777)

    for pair in cpfiles:
        spath = os.path.join(dfdir, pair[0].fullname)
        dpath = os.path.join(homedir, pair[1].fullname)
        if dryrun:
            print('cp {!r} {!r}'.format(strip_prefix(spath, homedir),
                                        strip_prefix(dpath, homedir)))
        else:
            shutil.copyfile(spath, dpath)

    for pair in symlinks:
        # these are also src <- tgt, which is how
        # we call os.symlink
        print('relpath = {}'.format(relpath))
        spath = os.path.join(relpath, pair[0].strip_prefix(dfdir))
        dpath = os.path.join(homedir, pair[1].fullname)
        if dryrun:
            print('ln -s {!r} {!r}'.format(spath, strip_prefix(dpath, homedir)))
        else:
            os.symlink(spath, dpath)

    return 0


def main():
    """
    The usual main
    """
    parser = argparse.ArgumentParser(description='set up dot-files')

    dfdir = locate_dotfiles(allow_none=True)
    homedir = os.environ['HOME']

    # NB: if dfdir is None, --dotfiles is actually required
    parser.add_argument('--dotfiles', default=dfdir,
        help='set path to dot-files directory (default {})'.format(dfdir))
    parser.add_argument('--install-to', default=homedir,
        help='set path for installation (default {})'.format(homedir))
    parser.add_argument('-c', '--copy', action='store_true',
        help='make copies (instead of symlinks)')
    parser.add_argument('-f', '--force', action='count',
        help='rename/overwrite existing files/symlinks if needed')
    parser.add_argument('-n', '--dry-run', action='store_true',
        help='show links that would be made, without making them')

    args = parser.parse_args()
    dfdir = args.dotfiles
    if dfdir is None:
        dfdir = locate_dotfiles(allow_none=False)
    dfdir = dfdir

    homedir = os.path.abspath(args.install_to)
    if not os.path.isdir(homedir):
        print('error: {} is not a directory'.format(homedir), file=sys.stderr)
        return 1

    if args.copy:
        relpath = None
    else:
        relpath = compute_relpath(homedir, dfdir)
        if not relpath:
            print('error: cannot install {} at {}'.format(dfdir, homedir),
                  file=sys.stderr)
            return 1

    # args.dry_run -- not yet, for testing
    return install(relpath, dfdir, homedir,
                   dryrun=args.dry_run, force=args.force)

if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit('\nInterrupted')

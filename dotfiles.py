#! /usr/bin/env python3

"""
Dotfiles: set up home directory .foorc files.
"""

import argparse
import errno
import itertools
import os.path
import shutil
import stat
import subprocess
import sys
import tarfile

# We'll check for a Dotfiles directory where this program lives.
SELF = os.path.abspath(__file__)


class FileInfo:
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
        return f"{self.fullname}{'/' if self.is_dir() else ''}"

    def __repr__(self):
        return (f"{self.__class__.__name__}({repr(self.fullname)}, "
            f"{repr(self.mode)}, "
            f"{repr(self._contents)}, {repr(self._oddballs)})")

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
                             f'{self.strmode()} {repr(self.fullname)}')
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
                             f'{self.strmode()} {repr(self.fullname)}')
        if which is None:
            raise ValueError('attempt to get contents of unsaved dir'
                             f'{self.strmode()} {repr(self.fullname)}')
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


class WorkList:
    """
    WorkList collects up a list of operations to be done on a
    set of files (the files themselves are represented by
    FileInfo objects, or occasionally pairs of FileInfo objects,
    or by path names - we keep just the path name).

    The operations are:
     - rename a file or directory (pair: oldname, newname)
     - remove a file
     - remove a directory (which must be empty by this point)
     - create a directory
     - copy a file (pair: original, copy-dest)
     - symlink a file (pair: existing, where-link-goes)

    The operations are then done in that order, when you commit
    them.  Note that we must, in general, do the renames and file
    removes first so that the directories are empty and can be
    removed.

    If a name is relative (does not start with /) we need to know
    "relative to what".  For now all paths should be absolute.
    """
    def __init__(self):
        self.to_rename = []
        self.to_remove = []
        self.to_rmdir = []
        self.to_mkdir = []
        self.to_copy = []
        self.to_symlink = []

    # Optionally, we could set a default top level, and _pathfrom
    # would use self.rootpath to construct the absolute path....
    @staticmethod
    def _abspathfrom(arg):
        path = getattr(arg, 'fullname', arg)
        if not os.path.isabs(path):
            raise ValueError(f'path {path} is not absolute')
        return path

    @staticmethod
    def _pathfrom(arg):
        return getattr(arg, 'fullname', arg)

    def rename(self, old, new):
        """
        Schedule file rename.

        As a special case, you can provided None for the new
        name, which means "generate a name that does not exist
        that is otherwise the same as the old name but with
        a suffix added."
        """
        old = self._abspathfrom(old)
        new = _get_rename_path(old) if new is None else self._abspathfrom(new)
        self.to_rename.append((old, new))

    def remove(self, path):
        """
        Schedule file removal.

        As a special case, if path has an 'is_dir' attribute,
        we'll schedule a rmdir instead.
        """
        if hasattr(path, 'is_dir') and path.is_dir():
            self.to_rmdir.append(self._abspathfrom(path))
        else:
            self.to_remove.append(self._abspathfrom(path))

    def rmdir(self, path):
        "Schedule directory removal."
        self.to_rmdir.append(self._abspathfrom(path))

    def mkdir(self, path):
        "Schedule directory creation."
        self.to_mkdir.append(self._abspathfrom(path))

    def copyfile(self, old, new):
        "Schedule file copy."
        old = self._abspathfrom(old)
        new = self._abspathfrom(new)
        self.to_copy.append((old, new))

    def symlink(self, old, new):
        "Schedule symlink of new -> old."
        old = self._pathfrom(old)
        new = self._abspathfrom(new)
        self.to_symlink.append((old, new))

    def execute(self, dryrun, location=None):
        """
        Execute all of the operations, but as if we did a
        "cd location" first if location is not None.
        (For now this affects only the printed results.)

        If dryrun is set, just *print* the operations instead.

        This operation is fundamentally destructive (unless
        doing a dry run) so if any OSError is raised, there is
        no simple reversal.
        """
        # pylint: disable=too-many-branches
        if (len(self.to_rename) +
                len(self.to_remove) +
                len(self.to_rmdir) +
                len(self.to_mkdir) +
                len(self.to_copy) +
                len(self.to_symlink)) == 0:
            # nothing to do - avoid printing location when doing dry-run
            return
        if dryrun:
            # pylint: disable=unnecessary-lambda-assignment
            if location is not None:
                print(f'cd {repr(location)}')
                fmt = lambda path: strip_prefix(path, location)
            else:
                fmt = lambda path: path

        for old, new in self.to_rename:
            if dryrun:
                print(f'mv {repr(fmt(old))} {repr(fmt(new))}')
            else:
                os.rename(old, new)
        for old in self.to_remove:
            if dryrun:
                print(f'rm {repr(fmt(old))}')
            else:
                os.unlink(old)
        for old in self.to_rmdir:
            if dryrun:
                print(f'rmdir {repr(fmt(old))}')
            else:
                os.rmdir(old)
        for new in self.to_mkdir:
            if dryrun:
                print(f'mkdir {repr(fmt(new))}')
            else:
                os.mkdir(new, 0o777)
        for old, new in self.to_copy:
            if dryrun:
                print(f'cp {repr(fmt(old))} {repr(fmt(new))}')
            else:
                shutil.copyfile(old, new)
        for old, new in self.to_symlink:
            # Although "ls -l" displays these as new -> old, the
            # ln -s and symlink calls take them in the old, new order.
            if dryrun:
                print(f'ln -s {repr(fmt(old))} {repr(fmt(new))}')
            else:
                os.symlink(old, new)


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
    print(f'I found myself at {SELF}', file=sys.stderr)
    print(f'I could not find a Dotfiles directory at {dotfilesdir}',
          file=sys.stderr)
    sys.exit(1)


def compute_relpath(within, to): # pylint: disable=invalid-name
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
    path_len = len(prefix)
    file_len = len(path)
    if file_len > path_len and path.startswith(prefix):
        part = path[path_len:]
        if part.startswith(os.path.sep):
            return part[len(os.path.sep):]
    return path


def ftype_string(mode): # pylint: disable=too-many-return-statements
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
    return f'mystery-file-mode={mode:07o}'


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


def allow_std(mode):
    """
    Default "allow" function: allow directories, regular files,
    and symlinks.
    """
    return stat.S_ISDIR(mode) or stat.S_ISREG(mode) or stat.S_ISLNK(mode)


def allow_plus_fifo(mode):
    """
    Same as above, but also alow fifo files (mkfifo).
    """
    if allow_std(mode):
        return True
    return stat.S_ISFIFO(mode)


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
            allowfn = allow_std
        pair = _get_files_from(path, recurse, allowfn)
    return FileInfo(path, mode, pair[0], pair[1])


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


def rmtree(worklist, tgtinfo):
    """
    Remove all files and directories, recursively.
    """
    if tgtinfo.is_dir():
        for subfile in flatten_contents(tgtinfo):
            worklist.remove(subfile)
    worklist.remove(tgtinfo)


def transliterate(toppath, subfile, newtop):
    """
    Turn a sub-file of the given top path (eg, vim/foo) into a
    subfile of the new top path (e.g., .vim/foo).  Result is just
    a path string.
    """
    subpath = subfile.strip_prefix(toppath.fullname)
    return os.path.join(newtop, subpath)


def clean_copy(worklist, srcinfo, newtop):
    """
    tgtinfo represents a non-existent directory, which
    we must make to make directory srcinfo.  We then
    copy, recursively, all files and sub-directories
    from srcinfo into newtop.

    Note that newtop may be, e.g., .vim while
    srcinfo.fullname is just vim - we mkdir the dot version.
    Subfile names do not get more dots added.

    We don't actually do it here, just add it to our
    instruction-set.
    """
    if srcinfo.is_dir():
        worklist.mkdir(newtop)
        for subfile in flatten_contents(srcinfo):
            # Strip srcinfo path prefix off, and replace with
            # a prefix made from newtop instead.
            newtgt = transliterate(srcinfo, subfile, newtop)
            if subfile.is_dir():
                worklist.mkdir(newtgt)
            else:
                worklist.copyfile(subfile, newtgt)
    else:
        worklist.copyfile(srcinfo, newtop)


def match_dirs(worklist, srcinfo, tgtinfo): # pylint: disable=too-many-branches
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
                # if src is dir, remember that there is an existing
                # target dir; otherwise remove the target dir
                if srcinfo.is_dir():
                    tgt_dirs.append(info)
                else:
                    worklist.rmdir(info)
            else:
                # always remove all existing target files
                # (to get them out of the way)
                worklist.remove(info)
    else:
        worklist.remove(tgtinfo)

    # if source is not a dir, we're done
    if not srcinfo.is_dir():
        return

    # sort all dirs by full path name
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
            worklist.rmdir(tdir)
            tgt_dirs.pop()
        else:
            # sdir is missing, so mkdir it
            worklist.mkdir(transliterate(srcinfo, sdir, tgtinfo.fullname))
            src_dirs.pop()
    # any remaining src dirs are missing
    for sdir in src_dirs:
        worklist.mkdir(transliterate(srcinfo, sdir, tgtinfo.fullname))
    # any remaining tgt dirs are extra
    for tdir in tgt_dirs:
        worklist.rmdir(tdir)


def copy_files(worklist, srcinfo, newtop):
    """
    Copy any src file (directories are already matched up),
    to path starting with (if tree) or consisting of (if file)
    newtop.

    We don't actually do it here, just add it to our
    instruction-set.
    """
    if srcinfo.is_dir():
        for subfile in flatten_contents(srcinfo):
            if not subfile.is_dir():
                worklist.copyfile(subfile,
                                  transliterate(srcinfo, subfile, newtop))
    else:
        worklist.copyfile(srcinfo, newtop)


def _get_rename_path(path):
    """
    Given a file path (e.g., /path/to/foo) that does exist, find
    another name (/path/to/foo.<suffix>) that does not exist.
    """
    dirname = os.path.dirname(path)
    basename = os.path.basename(path)
    i = 0
    while True:
        i += 1
        tpath = os.path.join(dirname, f'{basename}.{i}')
        if getmode(tpath) is None:
            return tpath
        # todo, perhaps: if i > 10; try reading dir?


def install(relpath, dfdir, homedir, dryrun, force, mktar, tarmode):
    # pylint: disable=too-many-arguments,too-many-locals
    # pylint: disable=too-many-branches,too-many-statements
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

    If mktar is not None, it's a tarfile where we should store
    the originals, instead of renaming and before blowing
    away.  In this case, one level of --force suffices to
    remove the files, since we save them first.

    Note: if there is a long path in some name <name>, we may
    need to make directories in homedir, e.g., <name> may be
    'vim/after/ftplugin/c.vim' in which case we need to create
    create <homedir>/.vim/after/ftplugin.  It's OK if this exists
    now, as long as it is a directory.

    In any case we, make two passes, one to see what to do,
    and one to actually install.
    """
    def print_error_header():
        if errors == 0:
            print(f'error: cannot install to {homedir}:',
                  file=sys.stderr)

    def print_oddballs(info):
        bad = sorted(flatten_oddballs(info), key=lambda e: e.fullname)
        for i in bad[:9]:
            print(f'  {repr(i.strip_prefix(dfdir))}: {i.strmode()}',
                  file=sys.stderr)
        if len(bad) > 9:
            print(f'... and {len(bad) - 9} more', file=sys.stderr)

    # Get file info about dfdir.  If there are any problematic
    # files in there, complain about them and stop.
    # (If relpath is None, get file list recursively.)
    recurse = relpath is None
    info = finfo(dfdir, recurse)
    if info is None:
        print(f'cannot install from {repr(dfdir)}: no such directory',
              file=sys.stderr)
        return 1
    if not info.is_dir():
        print(f'cannot install from {info.strmode()} {repr(dfdir)}: '
              'not a directory',
              file=sys.stderr)
        return 1
    # can always check for this recursively, even if we didn't recurse
    if info.has_oddballs(recurse=True):
        print(f'cannot install from {dfdir} due to:', file=sys.stderr)
        print_oddballs(info)
        return 1

    # OK, info is a directory and there are no oddball files.  If
    # relpath is not None, info.contents may have sub-directories with
    # unknown contents (e.g., '.vim'); if relpath is None, it may have
    # such dirs, but with known contents.
    worklist = WorkList()
    errors = 0

    for srcinfo in info.contents:
        tgtname = '.' + srcinfo.filename
        tgtpath = os.path.join(homedir, tgtname)
        # gather recursive scan of everything at the target path
        tgtinfo = finfo(tgtpath, recurse=True,
            allowfn=allow_plus_fifo, always=True)

        if tgtinfo.mode is None:
            # Target doesn't exist; all we do is copy or symlink,
            # and that will take care of everything.
            if relpath is None:
                clean_copy(worklist, srcinfo, tgtinfo.fullname)
            else:
                rellink = os.path.join(relpath, srcinfo.filename)
                worklist.symlink(rellink, tgtinfo)
            continue

        # Refuse to install over top of weird files.
        if not allow_plus_fifo(tgtinfo.mode):
            print_error_header()
            print(f'error: {tgtinfo.strmode()} '
                  f'{repr(tgtinfo.strip_prefix(homedir))}: '
                  'not a regular file, symlink, or directory',
                  file=sys.stderr)
            errors += 1
            continue
        if tgtinfo.has_oddballs(recurse=True):
            print_error_header()
            print(f'error: {tgtinfo} contains special files:',
                  file=sys.stderr)
            print_oddballs(tgtinfo)
            errors += 1
            continue

        # Target exists.  Now what?
        if tgtinfo.is_symlink():
            # It's a symlink.  Do we want a symlink?
            if relpath is None:
                # We don't want a symlink.  If force, schedule rm
                # and pretend it's gone, so we can do a clean copy
                # into place.
                if force:
                    worklist.remove(tgtinfo)
                    clean_copy(worklist, srcinfo, tgtinfo.fullname)
                    continue
                # Fall through to other tests below, to complain
                # about the symlink in the way.
            else:
                # We do want a symlink.  If it's good, leave it alone.
                # If it's wrong, schedule to replace it with the
                # right one.  Either one will finish the work.
                #
                # Note that scheduling it to be removed gets it
                # added to the tar file, if there is one.
                rellink = os.path.join(relpath, srcinfo.filename)
                if tgtinfo.read_symlink() != rellink:
                    worklist.remove(tgtinfo)
                    worklist.symlink(rellink, tgtinfo)
                continue

        # Target exists and is not symlink (is dir, file,
        # device, whatever).
        if force or mktar:
            if relpath is not None:
                # We're symlinking top level files.
                # Just rename any non-empty directory or ordinary file;
                # or remove empty tree, or rm -r as appropriate.
                if tgtinfo.is_recursively_empty() or force > 1 or mktar:
                    rmtree(worklist, tgtinfo)
                else:
                    worklist.rename(tgtinfo, None)
                # don't need a fake tgtinfo, worklist saves only the name
                rellink = os.path.join(relpath, srcinfo.filename)
                worklist.symlink(rellink, tgtinfo)
                continue

            # We're copying all the files.  If the target
            # dir is recursively empty, remove any unwanted
            # subdirs (that are in the way of any wanted files)
            # and leave or create any subdirs needed (for
            # wanted files).
            if tgtinfo.is_recursively_empty() or force > 1 or mktar:
                # remove any unwanted dirs and files;
                # add any missing empty dirs
                match_dirs(worklist, srcinfo, tgtinfo)
                # and copy all regular files
                copy_files(worklist, srcinfo, tgtinfo.fullname)
            else:
                # tgt has files - rename it to get it out of the way
                worklist.rename(tgtinfo, None)
                clean_copy(worklist, srcinfo, tgtinfo.fullname)
            continue

        # Target exists, and force not set.
        if errors == 0:
            print(f'error: cannot install to {homedir}:',
                  file=sys.stderr)
        print(f'  {tgtinfo.strmode()} {repr(tgtinfo.strip_prefix(homedir))} '
              'is in the way',
              file=sys.stderr)
        errors += 1

    if errors:
        return 1

    # If making tar file, do that now (even in dry-run mode).
    if mktar:
        if worklist.to_rename:
            raise ValueError('internal error: mktar but renames found')
        with tarfile.open(mktar, tarmode) as tar:
            for path in itertools.chain(worklist.to_rmdir, worklist.to_remove):
                tar.add(path, arcname=strip_prefix(path, homedir),
                        recursive=False)

    worklist.execute(dryrun, location=homedir)
    postinstall = f'{homedir}/.postinstall'
    if dryrun:
        print(f'if [ -f {postinstall} ]; then {postinstall}; fi')
    else:
        if os.path.exists(postinstall):
            status = subprocess.call(postinstall)
            if status != 0:
                print(f'{postinstall}: exit code {status}')

    return 0


def main(): # pylint: disable=too-many-branches
    """
    The usual main
    """
    parser = argparse.ArgumentParser(description='set up dot-files')

    dfdir = locate_dotfiles(allow_none=True)
    homedir = os.environ['HOME']

    # NB: if dfdir is None, --dotfiles is actually required
    parser.add_argument('--dotfiles', default=dfdir,
        help=f'set path to dot-files directory (default {dfdir})')
    parser.add_argument('--homedir', default=homedir,
        help=f'set path for installation (default {homedir})')
    parser.add_argument('-c', '--copy', action='store_true',
        help='make copies (instead of symlinks)')
    parser.add_argument('-f', '--force', action='count',
        help='rename/overwrite existing files/symlinks if needed')
    parser.add_argument('-n', '--dry-run', action='store_true',
        help='show links that would be made, without making them')
    parser.add_argument('-t', '--tar',
        help='set name of tar file to hold original dot-files')
    parser.add_argument('-C', '--compress', choices=['gz', 'bz2'],
        help='set compression mode for tar file (default = intuit)')

    args = parser.parse_args()
    dfdir = args.dotfiles
    if dfdir is None:
        dfdir = locate_dotfiles(allow_none=False)
    dfdir = os.path.abspath(dfdir)

    homedir = os.path.abspath(args.homedir)
    if not os.path.isdir(homedir):
        print(f'error: {homedir} is not a directory', file=sys.stderr)
        return 1

    if args.copy:
        relpath = None
    else:
        relpath = compute_relpath(homedir, dfdir)
        if not relpath:
            print(f'error: cannot install {dfdir} at {homedir}',
                  file=sys.stderr)
            return 1

    # should we make a tar file?
    if args.tar is not None:
        tarname = args.tar
        tarmode = args.compress
        if tarmode is None:
            if tarname.endswith('.gz'):
                tarmode = 'gz'
            elif tarname.endswith('.bz2'):
                tarmode = 'bz2'
            else:
                tarmode = ''
            tarmode = 'w:' + tarmode
        if getmode(tarname) is not None:
            print(f'error: {tarname} already exists', file=sys.stderr)
            return 1
    else:
        if args.compress:
            print(f'warning: compression mode {args.compress} ignored',
                  file=sys.stderr)
        tarname = None
        tarmode = None

    return install(relpath, dfdir, homedir,
                   dryrun=args.dry_run, force=args.force,
                   mktar=tarname, tarmode=tarmode)

if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit('\nInterrupted')

#! /usr/bin/env python

"""
post-checkout hook to re-smudge files
"""

from __future__ import print_function

import collections
import os
import subprocess
import sys

def run(cmd):
    """
    Run command and collect its stdout.  If it produces any stderr
    or exits nonzero, die a la subprocess.check_call().
    """
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    stdout, _ = proc.communicate()
    status = proc.wait()
    if status != 0:
        raise subprocess.CalledProcessError(status, cmd)
    return stdout

def git_ls_files(*args):
    """
    Run git ls-files with given arguments, plus -z; break up
    returned byte string into list of files.  Note, in Py3k this
    will be a list of byte-strings!
    """
    output = run(['git', 'ls-files', '-z'] + list(args))
    # -z produces NUL termination, not NUL separation: discard last entry
    return output.split(b'\0')[:-1]

def recheckout(files):
    """
    Force Git to re-extract the given files from the index.
    Since Git insists on doing nothing when the files exist
    in the work-tree, we first *remove* them.

    To avoid blowing up on very long argument lists, do these
    1000 files at a time or up to 10k bytes of argument at a
    time, whichever occurs first.  Note that we may go over
    the 10k limit by the length of whatever file is long, so
    it's a sloppy limit and we don't need to be very accurate.
    """
    files = collections.deque(files)
    while files:
        todo = [b'git', b'checkout', b'--']
        # should add 1 to account for b'\0' between arguments in os exec:
        # argbytes = reduce(lambda x, y: x + len(y) + 1, todo, 0)
        # but let's just be very sloppy here
        argbytes = 0
        while files and len(todo) < 1000 and argbytes < 10000:
            path = files.popleft()
            todo.append(path)
            argbytes += len(path) + 1
            os.remove(path)
        # files is now empty, or todo has reached its limit:
        # run the git checkout command
        run(todo)

def warn_about(files):
    """
    Make a note to the user that some file(s) have not been
    re-checked-out as they are modified in the work-tree.
    """
    if len(files) == 0:
        return
    print("Note: the following files have been carried over and may")
    print("not match what you would expect for a clean checkout:")
    # If this is py3k, each path is a bytes and we need a string.
    if type(b'') == type(''):
        printable = lambda path: path
    else:
        printable = lambda path: path.decode('unicode_escape')
    for path in files:
        print('\t{}\n'.format(printable(path)))

def main():
    """
    Run, as called by git post-checkout hook.  We get three arguments
    that are very simple, so no need for argparse.

    We only want to do something when:
     - the flag argument, arg 3, is 1
     - the two other arguments differ

    What we do is re-checkout the *unmodified* files, to
    force them to re-run through any defined .gitattributes
    filter.
    """
    argv = sys.argv[1:]
    if len(argv) != 3:
        return 'error: hook must be called with three arguments'
    if argv[2] != '1':
        return 0
    if argv[0] == argv[1]:
        return 0
    allfiles = git_ls_files()
    modfiles = git_ls_files('-m')
    unmodified = set(allfiles) - set(modfiles)
    recheckout(unmodified)
    warn_about(modfiles)
    return 0

if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit('\nInterrupted')

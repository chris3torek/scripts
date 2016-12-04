#! /usr/bin/env python

from __future__ import print_function

"""
find "system ioctls" (_IOR, _IOW, _IOWR).
"""

import argparse
import os
import re
import subprocess
import sys

# input lines are expected to have the form
#   path/too/foo:123:#define ...
# as produced by:
#   git grep -P -n "..._IO...("
# or:
#   egrep -R -n "..._IO...("
grepfor = r'\b_IO(|R|WR|W)' '[ \t]' r'*\('   # passed to git grep or egrep

lineparts = re.compile(r'([^:]+):(\d+):(.*\n)')

# Most ioctl groups are defined by a character constant.
# However, some are defined through another #define, so
# we need to accept names as well as character constants.
# For completeness we accept raw numbers as well, converting
# those *to* character constants.
#
# The same applies to ioctl ID numbers.  There's little we can
# do with symbolic numbers though.
#
# There are even a few cases where the ID number is an expression
# (in the VESA code).  For now we just ignore them entirely.
sysioc_define = re.compile(r'#\s*define\s*_IO(R|WR|W|)\(')
grp_regexp = r"(?P<grp>(?:'.'|\d+|0x[0-9a-fA-F]+|[a-zA-Z_]\w*))"
id_regexp = r"(?P<id>(?:\d+|0x[0-9a-fA-F]+|[a-zA-Z_]\w*|'.'))"
sysioc_noarg = re.compile(
    r"(?P<type>_IO)\s*\(\s*" + grp_regexp + r"\s*,\s*" + id_regexp + "\s*\)")
sysioc_arg = re.compile(
    r"(?P<type>_IO(R|WR|W))\s*\(\s*" + grp_regexp + r"\s*,\s*" +
    id_regexp + r"\s*,\s*(?P<arg>[^)]+?)\s*\)")

def format_group(group):
    """
    If the group is a numeric value and makes a suitable printable character,
    turn it into a C style character constant.
    """
    if isinstance(group, int):
        if group > 0 and group < 128:
            as_char = chr(group)
            if as_char.isalnum():
                return "'{0}'".format(as_char)
        return '{0}'.format(group)
    return group

def is_C_number(string):
    """
    Test whether string is a valid C number.

    (Note that caller must use int(string, 0) to convert it.)
    """
    if string.isdigit():
        return True
    if string.startswith('0x'):
        return len(string) > 2 and string[2:].isdigit()
    return False

class SysIoc(object):
    def __init__(self, iotype, group, number, arg):
        self.iotype = iotype
        self.group = group
        self.number = number
        self.arg = arg
        self.sources = []

    def __repr__(self):
        return '%s(%r, %r, %r, %r)' % (self.__class__.__name__,
            self.iotype, self.group, self.number, self.arg)

    def __str__(self):
        grp = format_group(self.group)
        if self.iotype == '_IO':
            return "%s(%s, %s)" % (self.iotype, grp, self.number)
        arg = '???' if self.arg is None else self.arg
        return "%s(%s, %s, %s)" % (self.iotype, grp, self.number, arg)

    def addsource(self, path, lineno, alt):
        """
        Add a source that defines this ioctl.  Alt is the specific
        ioctl, which may be different from self if this is a duplicate.
        """
        self.sources.append((path, lineno, alt))

def full_line(srcdir, srcpath, lineno, text):
    """
    Mainly used for lines that end in backslash: open the original
    file and read more lines.  We expect the first line to match
    the given text.

    Also used, however, for lines that may be in the middle of, or
    at the end of, a continuation.

    Passing None for text => no checking
    """
    allreplaced = False
    if srcdir is None:
        path = srcpath
    else:
        path = os.path.join(srcdir, srcpath)
    saved = []
    replacement = None
    with open(path, 'r') as stream:
        for lno, line in enumerate(stream, start=1):
            is_continued = line.endswith('\\\n')
            if lno < lineno:
                if is_continued:
                    saved.append(line)
                else:
                    saved = []
                continue
            if lno == lineno and line != text and text is not None:
                raise ValueError("file text {0!r} "
                                 "doesn't match grepped result "
                                 "{1!r}".format(text, line))
            # Note that saved is empty unless we have some
            # saved lines that come before the target line.
            if lno == lineno:
                replacement = saved
            replacement.append(line)
            if not is_continued:
                allreplaced = True
                break
    if replacement:
        if not allreplaced:
            print("warning: final line of {0!r} ended with "
                 "backslash".format(srcpath))
        # Ditch backslash-newlines (from all but last line).
        # Note that last line probably ends with just \n, but
        # if not allreplaced, it ends with \ and \n; but in
        # that case, we want to keep the \ anyway.
        replacement[0:-1] = [i[:-2] for i in replacement[0:-1]]
        return ''.join(replacement)
    raise ValueError("can't find line {0} in {1!r}".format(lineno, srcpath))

def readstream(args, stream):
    """
    Read lines from the given stream, finding their ioctl definitions.

    We'll look for files based on pathnames, if needed, too.

    The return value is a dictionary of ioctls by group,
    with each group being a dictionary of ioctls by number,
    with each number mapping to all its ioctls and their source
    lines.

    Warning: not all numbers are actually numbers.
    """
    ret = {}
    for line in stream:
        parts = lineparts.match(line)
        if not parts:
            srcpath = None
            lineno = None
            text = line
        else:
            srcpath = parts.group(1)
            lineno = int(parts.group(2))
            text = parts.group(3)
            if text.endswith('\\\n') or '#' not in text:
                try:
                    text = full_line(args.source, srcpath, lineno, text)
                except (ValueError, IOError) as err:
                    # suppress unless args.warns?
                    print("warning: unable to complete line {0} from "
                          "{1!r}:".format(lineno, srcpath), file=sys.stderr)
                    print(err, file=sys.stderr)

        # If the line is `#define _IO...(` then we want to skip it!
        if sysioc_define.search(text):
            if args.debug:
                print('ignoring definition {0}'.format(line.rstrip('\n')),
                      file=sys.stderr)
            continue
        # _IOR, _IOW, _IOWR are more common so check them first
        m = sysioc_arg.search(text)
        if m is None:
            m = sysioc_noarg.search(text)
        if m:
            iotype = m.group('type')
            iogrp = m.group('grp')
            ioid = m.group('id')
            ioarg = None if iotype == '_IO' else m.group('arg')
            if len(iogrp) == 3 and iogrp[0] == "'" and iogrp[2] == "'":
                iogrp = ord(iogrp[1])
            elif is_C_number(iogrp):
                iogrp = int(iogrp, 0)
            # else it's something arbitrary
            if is_C_number(ioid):
                ioid = int(ioid, 0)
            elif len(ioid) == 3 and ioid[0] == "'" and ioid[2] == "'":
                ioid = ord(ioid[1])
            # else it's something arbitrary
            ioc = SysIoc(iotype, iogrp, ioid, ioarg)
            if args.debug:
                print('{0}: src={1!r}'.format(ioc, srcpath), file=sys.stderr)
            mainioc = ret.setdefault(iogrp, {}).setdefault(ioid, ioc)
            mainioc.addsource(srcpath, lineno, ioc)
        elif args.warns:
            print('warning: line did not match; line was: '
                  '{0!r}'.format(line.rstrip('\n')),
                  file=sys.stderr)
            print('\t text was: {0!r}'.format(text.rstrip('\n')),
                  file=sys.stderr)
    return ret

def rungit(path):
    """
    Run git grep -n in the given path, or in current dir if path is None
    """
    cwdarg = {}
    if path:
        cwdarg['cwd'] = path
    proc = subprocess.Popen(['git', 'grep', '-n', '-P', '-e', grepfor],
                            stdout=subprocess.PIPE, **cwdarg)
    return proc

def rungrep(path):
    """
    Run egrep -n -R in the given path, or in current dir if path is None
    """
    cwdarg = {}
    if path:
        cwdarg['cwd'] = path
    proc = subprocess.Popen(['egrep', '-n', '-R', '-e', grepfor],
                            stdout=subprocess.PIPE, **cwdarg)
    return proc

def main():
    "the usual"
    parser = argparse.ArgumentParser("find kernel ioctl number usage")
    parser.add_argument('--debug', default=False, action='store_true',
        help='enable debugging')
    parser.add_argument('-W', '--warns', default=False, action='store_true',
        help='enable warnings (mainly mismatch failures)')
    parser.add_argument('-s', '--source',
        help='path to the kernel source tree (optional with --file)')
    parser.add_argument('-f', '--file',
        help='read _IO calls from a file rather than grepping (overrides -g)')
    parser.add_argument('-g', '--git', default=False, action='store_true',
        help='run "git grep" to find _IO calls (else use grep -R)')

    args = parser.parse_args()
    if args.debug:
        args.warns = True

    if args.file:
        proc = None
        try:
            stream = open(args.file, 'r')
        except (OSError, IOError) as err:
            sys.exit(err)
    else:
        try:
            proc = (rungit if args.git else rungrep)(args.source)
        except OSError as err:
            sys.exit(err)
        stream = proc.stdout

    allioc = readstream(args, stream)

    if args.file:
        stream.close()
    else:
        stream = None
        proc.wait() # and ignore return code

    print('system ioctls')
    for group in sorted(allioc.keys()):
        thisgroup = allioc[group]
        print()
        print("group {0}:".format(format_group(group)))
        for ioid in sorted(thisgroup.keys()):
            main = thisgroup[ioid]
            if isinstance(ioid, int):
                print('{0:3d}: '.format(ioid), end='')
                firstline = True
            else:
                print('{0}:'.format(ioid))
                firstline = False
            for (path, lineno, subioc) in main.sources:
                text = '{0:38} {1}:{2}'.format(subioc, path, lineno)
                if subioc == main and firstline:
                    print(text)
                else:
                    print('     {0}'.format(text))
    return 0

if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit('\nInterrupted')

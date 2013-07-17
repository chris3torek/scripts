#! /usr/bin/env python

#
# Read e-mail messages from an MH mail directory in my preferred style.
#

import argparse
import email.charset
import email.header
import email.message
import email.parser
import errno
import os
import subprocess
import sys
import tempfile

# Global variables.
# ?? probably should just use the name of the program, and let
# os.Popen search $PATH for it
default_pager = '/usr/bin/more'
lynx_path = '/usr/local/bin/lynx'
mhpath_path = '/usr/local/bin/mhpath'
show_path = '/usr/local/bin/show'
default_images = False

def extract_mh_files(arguments):
    '''Run MH commands to parse the argument string and return a list
       of paths to MH message files.'''

    # Mhpath differs from show when provided no arguments --
    # we want the same behavior as show, so we supply a default argument.
    if not arguments:
	arguments = ['.']

    # Run mhpath to retrive the pathnames of the messages.
    try:
        mhpath_command = subprocess.Popen(
          [mhpath_path] + arguments,
          stdout = subprocess.PIPE)
    except OSError as err:
        if err.errno == errno.ENOENT:
            sys.exit('%s: command not found' % mhpath_path)
        raise
    so, _ = mhpath_command.communicate()
    message_paths = so.split()

    nullfd = os.open(os.devnull, os.O_WRONLY)
    # Run the MH show command and discard the output (!).
    # We need to produce the side effects from running show.
    show_args = [show_path, '-noshowproc'] + arguments
    show_command = subprocess.Popen(
      show_args,
      stdout = nullfd,
      stderr = nullfd)
    show_command.wait()
    os.close(nullfd)

    return message_paths

def sanitize_substrings(substring_pairs):
    '''Given a list of pairs of strings and encodings, produce a single
       concatenated UTF-8 result.'''

    out = []
    for substring, mime_charset in substring_pairs:
	if not mime_charset:
	    mime_charset = 'us-ascii'
	if type(substring) == unicode:
	    s = substring.encode('utf-8', 'ignore')
	else:
	    codec_name = email.charset.Charset(mime_charset).input_codec
	    if not codec_name:
		codec_name = 'ascii'
	    try:
		u = substring.decode(codec_name, 'strict')
	    except (UnicodeError, LookupError):
		u = substring.decode('iso-8859-1')
	    s = u.encode('utf-8', 'ignore')
	out.append(s)

    return ''.join(out)

def sanitize(s, mime_charset):
    return sanitize_substrings([(s, mime_charset)])

displayable_types = set((
  'text/plain',
  'text/html',
  'message/rfc822',
  'text/enriched',
  'text/richtext',
))

def displayable(tree):
    '''Return True if this MIME part is displayable as text.'''

    return tree.get_content_type() in displayable_types

def is_image(tree):
    '''Return Tue if this MIME part represents an image.'''
    return tree.get_content_type().startswith('image/')

score_type = {
  'text/plain': 9,
  'message/rfc822': 8,
  'text/html': 7,
  'text/enriched': 6,
  'text/richtext': 6,
}

def get_score(part):
    '''Score this MIME part from 1 to 10 based on desirability
       for printing text.'''

    part_type = part.get_content_type()
    return score_type.get(part_type, 1)

def select_parts(tree, parts, images):
    '''Given a tree of email MIME messages (Message objects), choose
       the parts that we're interested in and append them to
       the 'parts' list.'''

    if not tree.is_multipart():
	if displayable(tree):
	    parts.append(tree)
        if images and is_image(tree):
            parts.append(tree)
	return

    # Loop over alternatives and choose the best one.
    if tree.get_content_type() == 'multipart/alternative':
	best_part = None
	best_score = 0
	for part in tree.get_payload():
	    score = get_score(part);
	    if score > best_score:
		best_score = score
		best_part = part
	if best_part:
	    select_parts(best_part, parts, images)
	return

    # Loop over multiple parts.
    for part in tree.get_payload():
	select_parts(part, parts, images)

interesting_headers = set((
  'cc',
  'date',
  'from',
  'subject',
  'to',
))

def format_headers(buffer, tree):
    '''Queue the headers that we're interested in from this tree.'''

    if is_image(tree):
        return
    for header, value in tree.items():
	if header.lower() in interesting_headers:
	    substring_pairs = email.header.decode_header(value)
	    buffer.append("%s: %s\n" %
	      (header, sanitize_substrings(substring_pairs)))
    buffer.append('\n')

def format_parts(buffer, parts):
    '''Queue the MIME parts that we want to print.'''

    for part in parts:
	part_type = part.get_content_type()
	part_charset = part.get_content_charset()
	part_payload = part.get_payload(decode = True)
        if is_image(part):
            display_image(part_payload)
	elif part_type == 'text/html':
	    lynx_command = subprocess.Popen(
	      [lynx_path, '-stdin', '-dump', '-force_html',
		'-hiddenlinks=ignore', '-nolist', '-width=80'],
	      stdin = subprocess.PIPE,
	      stdout = subprocess.PIPE,
	      stderr = subprocess.PIPE)
	    so, se = lynx_command.communicate(part_payload)
	    if se:
		buffer.append(se)
	    if so:
		# Lynx appears to produce Latin-1 output.
		buffer.append(sanitize(so, 'latin_1'))
	else:
	    buffer.append(sanitize(part_payload, part_charset))
    buffer.append('\n')

def display_image(bits):
    '''Display image.  We use xv, so you'll have to have that installed.'''

    # If there's something pending, push it out now so that we don't
    # duplicate it in our subprocess.
    sys.stdout.flush()
    sys.stderr.flush()

    # Fire up a pre-backgrounded (as it were) xv.
    try:
        pid = os.fork()
    except OSError as err:
        print >> sys.stderr, str(err)
        return
    if pid:
        return

    # Child: run xv.  When it finishes, exit immediately so
    # that we don't go on and display more image parts.
    tmp = tempfile.NamedTemporaryFile()
    tmp.write(bits)
    tmp.flush()
    status = subprocess.call(['xv', tmp.name])
    if status:
        print >> sys.stderr, 'xv exited with status', status
    os._exit(1)

def main():
    p = argparse.ArgumentParser(
      description = 'Print the given MH messages from the current folder '
	'using MIME headers to pick the best text representation.')
    p.add_argument('-H', '--html', action = 'store_true',
      help = 'Score HTML higher than plain text.  Useful when a message '
	'with alternative parts contains different information in the plain '
	'text and html alternatives.')
    group = p.add_mutually_exclusive_group()
    group.add_argument('-i', '--images',
      action = 'store_true', dest = 'images',
      help = 'display multipart pieces of type image/*')
    group.add_argument('-n', '--no-images',
      action = 'store_true', dest = 'noimages',
      help = 'suppress display of multipart pieces of type image/*')
    p.add_argument('arguments', metavar = 'msg', nargs = '*',
        help = 'messages to show')

    args = p.parse_args()

    if args.html:
	score_type['text/html'] = 10
    if not args.images and not args.noimages:
        args.images = default_images

    status = 0
    files = extract_mh_files(args.arguments)

    buffer = []
    for filename in files:
	try:
	    with open(filename, 'r') as f:
		tree = email.message_from_file(f)
		parts = []
		select_parts(tree, parts, args.images)
		format_headers(buffer, tree)
		format_parts(buffer, parts)
	except email.errors.MessageError as err:
	    print >>sys.stderr, str(err)
	    status = 1
	except EnvironmentError as err:
	    print >>sys.stderr, '%s: %s' % (err.filename, err.strerror)
	    status = 1

    if buffer:
	s = ''.join(buffer)
	if os.isatty(sys.stdout.fileno()):
	    pager = os.environ.get('PAGER', default_pager)
	    pager_command = subprocess.Popen(
	      [pager],
	      stdin = subprocess.PIPE)
	    try:
		pager_command.communicate(s)
                pager_command.wait()
	    except IOError as err:
		pass
	else:
	    try:
		sys.stdout.write(s)
	    except IOError as err:
		pass

    return status

if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(1)

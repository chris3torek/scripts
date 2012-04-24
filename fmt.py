#!/usr/bin/env python

'''A replacement for the fmt utility.'''

import optparse
import re
import sys
import textwrap

PREFIX_RE = re.compile(r'''[ >]+| *\* +|# +''')

CONVERSIONS = {
  ord(u'\N{no-break space}') : u' ',
  ord(u'\N{inverted exclamation mark}') : u'!',
  ord(u'\N{pound sign}') : u'#',
  ord(u'\N{broken bar}') : u'|',
  ord(u'\N{section sign}') : u'S',
  ord(u'\N{copyright sign}') : u'(c)',
  ord(u'\N{left-pointing double angle quotation mark}') : u'"',
  ord(u'\N{not sign}') : u'!',
  ord(u'\N{soft hyphen}') : u'-',
  ord(u'\N{registered sign}') : u'(R)',
  ord(u'\N{degree sign}') : u'(deg)',
  ord(u'\N{plus-minus sign}') : u'+/-',
  ord(u'\N{superscript two}') : u'2',
  ord(u'\N{superscript three}') : u'3',
  ord(u'\N{acute accent}') : u"'",
  ord(u'\N{middle dot}') : u'.',
  ord(u'\N{superscript one}') : u'1',
  ord(u'\N{right-pointing double angle quotation mark}') : u'"',
  ord(u'\N{vulgar fraction one quarter}') : u'1/4',
  ord(u'\N{vulgar fraction one half}') : u'1/2',
  ord(u'\N{vulgar fraction three quarters}') : u'3/4',
  ord(u'\N{inverted question mark}') : u'?',
  ord(u'\N{latin capital letter a with grave}') : u'A',
  ord(u'\N{latin capital letter a with acute}') : u'A',
  ord(u'\N{latin capital letter a with circumflex}') : u'A',
  ord(u'\N{latin capital letter a with tilde}') : u'A',
  ord(u'\N{latin capital letter a with diaeresis}') : u'AE',
  ord(u'\N{latin capital letter a with ring above}') : u'A',
  ord(u'\N{latin capital letter ae}') : u'AE',
  ord(u'\N{latin capital letter c with cedilla}') : u'C',
  ord(u'\N{latin capital letter e with grave}') : u'E',
  ord(u'\N{latin capital letter e with acute}') : u'E',
  ord(u'\N{latin capital letter e with circumflex}') : u'E',
  ord(u'\N{latin capital letter e with diaeresis}') : u'E',
  ord(u'\N{latin capital letter i with grave}') : u'I',
  ord(u'\N{latin capital letter i with acute}') : u'I',
  ord(u'\N{latin capital letter i with circumflex}') : u'I',
  ord(u'\N{latin capital letter i with diaeresis}') : u'I',
  ord(u'\N{latin capital letter eth}') : u'TH',
  ord(u'\N{latin capital letter n with tilde}') : u'NY',
  ord(u'\N{latin capital letter o with grave}') : u'O',
  ord(u'\N{latin capital letter o with acute}') : u'O',
  ord(u'\N{latin capital letter o with circumflex}') : u'O',
  ord(u'\N{latin capital letter o with tilde}') : u'O',
  ord(u'\N{latin capital letter o with diaeresis}') : u'OE',
  ord(u'\N{multiplication sign}') : u'x',
  ord(u'\N{latin capital letter o with stroke}') : u'OE',
  ord(u'\N{latin capital letter u with grave}') : u'U',
  ord(u'\N{latin capital letter u with acute}') : u'U',
  ord(u'\N{latin capital letter u with circumflex}') : u'U',
  ord(u'\N{latin capital letter u with diaeresis}') : u'U',
  ord(u'\N{latin capital letter y with acute}') : u'Y',
  ord(u'\N{latin small letter sharp s}') : u'ss',
  ord(u'\N{latin small letter a with grave}') : u'a',
  ord(u'\N{latin small letter a with acute}') : u'a',
  ord(u'\N{latin small letter a with circumflex}') : u'a',
  ord(u'\N{latin small letter a with tilde}') : u'a',
  ord(u'\N{latin small letter a with diaeresis}') : u'ae',
  ord(u'\N{latin small letter a with ring above}') : u'a',
  ord(u'\N{latin small letter ae}') : u'ae',
  ord(u'\N{latin small letter c with cedilla}') : u'c',
  ord(u'\N{latin small letter e with grave}') : u'e',
  ord(u'\N{latin small letter e with acute}') : u'e',
  ord(u'\N{latin small letter e with circumflex}') : u'e',
  ord(u'\N{latin small letter e with diaeresis}') : u'e',
  ord(u'\N{latin small letter i with grave}') : u'i',
  ord(u'\N{latin small letter i with acute}') : u'i',
  ord(u'\N{latin small letter i with circumflex}') : u'i',
  ord(u'\N{latin small letter i with diaeresis}') : u'i',
  ord(u'\N{latin small letter eth}') : u'th',
  ord(u'\N{latin small letter n with tilde}') : u'ny',
  ord(u'\N{latin small letter o with grave}') : u'o',
  ord(u'\N{latin small letter o with acute}') : u'o',
  ord(u'\N{latin small letter o with circumflex}') : u'o',
  ord(u'\N{latin small letter o with tilde}') : u'o',
  ord(u'\N{latin small letter o with diaeresis}') : u'oe',
  ord(u'\N{division sign}') : u'/',
  ord(u'\N{latin small letter o with stroke}') : u'oe',
  ord(u'\N{latin small letter u with grave}') : u'u',
  ord(u'\N{latin small letter u with acute}') : u'u',
  ord(u'\N{latin small letter u with circumflex}') : u'u',
  ord(u'\N{latin small letter u with diaeresis}') : u'u',
  ord(u'\N{latin small letter y with acute}') : u'u',
  ord(u'\N{latin small letter thorn}') : u'th',
  ord(u'\N{latin small letter y with diaeresis}') : u'y',
  ord(u'\N{latin capital letter a with macron}') : u'AA',
  ord(u'\N{latin small letter a with macron}') : u'aa',
  ord(u'\N{latin capital letter e with macron}') : u'EE',
  ord(u'\N{latin small letter e with macron}') : u'ee',
  ord(u'\N{latin capital letter i with macron}') : u'II',
  ord(u'\N{latin small letter i with macron}') : u'ii',
  ord(u'\N{latin capital letter i with dot above}') : u'I',
  ord(u'\N{latin small letter dotless i}') : u'i',
  ord(u'\N{latin capital ligature ij}') : u'IJ',
  ord(u'\N{latin capital letter eng}') : u'NG',
  ord(u'\N{latin small letter eng}') : u'ng',
  ord(u'\N{latin capital letter o with macron}') : u'OO',
  ord(u'\N{latin small letter o with macron}') : u'oo',
  ord(u'\N{latin capital ligature oe}') : u'OE',
  ord(u'\N{latin small ligature oe}') : u'oe',
  ord(u'\N{latin capital letter s with acute}') : u'SH',
  ord(u'\N{latin small letter s with acute}') : u'sh',
  ord(u'\N{latin capital letter s with caron}') : u'SH',
  ord(u'\N{latin small letter s with caron}') : u'sh',
  ord(u'\N{latin capital letter u with macron}') : u'UU',
  ord(u'\N{latin small letter u with macron}') : u'uu',
  ord(u'\N{latin capital letter z with caron}') : u'ZH',
  ord(u'\N{latin small letter z with caron}') : u'zh',
  ord(u'\N{latin small letter long s}') : u's',
  ord(u'\N{latin capital letter open o}') : u'o',
  ord(u'\N{double acute accent}') : u'"',
  ord(u'\N{modifier letter double apostrophe}') : u'"',
  ord(u'\N{en quad}') : u' ',
  ord(u'\N{em quad}') : u' ',
  ord(u'\N{en space}') : u' ',
  ord(u'\N{em space}') : u' ',
  ord(u'\N{three-per-em space}') : u' ',
  ord(u'\N{four-per-em space}') : u' ',
  ord(u'\N{six-per-em space}') : u' ',
  ord(u'\N{figure space}') : u' ',
  ord(u'\N{punctuation space}') : u' ',
  ord(u'\N{thin space}') : u' ',
  ord(u'\N{hair space}') : u' ',
  ord(u'\N{hyphen}') : u'-',
  ord(u'\N{non-breaking hyphen}') : u'-',
  ord(u'\N{figure dash}') : u'-',
  ord(u'\N{en dash}') : u'-',
  ord(u'\N{em dash}') : u'-',
  ord(u'\N{horizontal bar}') : u'-',
  ord(u'\N{left single quotation mark}') : u"'",
  ord(u'\N{right single quotation mark}') : u"'",
  ord(u'\N{single low-9 quotation mark}') : u"'",
  ord(u'\N{single high-reversed-9 quotation mark}') : u"'",
  ord(u'\N{left double quotation mark}') : u'"',
  ord(u'\N{right double quotation mark}') : u'"',
  ord(u'\N{double low-9 quotation mark}') : u'"',
  ord(u'\N{double high-reversed-9 quotation mark}') : u'"',
  ord(u'\N{bullet}') : u'+',
  ord(u'\N{horizontal ellipsis}') : u'...',
  ord(u'\N{single left-pointing angle quotation mark}') : u"'",
  ord(u'\N{single right-pointing angle quotation mark}') : u"'",
  ord(u'\N{fraction slash}') : u'/',
  ord(u'\N{euro sign}') : u'#',
}

class line_data(object):
    '''A convenience object that stores the representation of a
       formattable line of text.  It converts all non-ASCII input
       characters into reasonable substitutes, and it splits off
       any initial prefix containing ">" characters (an e-mail
       blockquoting convention).'''

    def __init__(self, s):
        try:
            s = s.decode('utf_8')
        except UnicodeError:
            s = s.decode('iso-8859-1')
        s = s.rstrip()
        s = s.expandtabs()
	if not options.utf8:
	    s = s.translate(CONVERSIONS)
	    s = s.encode('ascii', 'xmlcharrefreplace')
        m = PREFIX_RE.match(s)
        if m:
            self.prefix = s[m.start():m.end()]
            self.text = s[m.end():]
        else:
            self.prefix = ''
            self.text = s

def main():
    '''Process lines from files or from standard input, reflowing
       text where it's reasonable to do so.  Non-ASCII characters
       are converted to safe ASCII equivalents.  E-mail blockquotes
       are reflowed, preserving any prefix.'''

    global options

    p = optparse.OptionParser(usage = 'Usage: %prog [options] [files ...]',
      description = 'Format text from standard input or files, converting '
        'UTF-8 characters into semi-equivalent ASCII where possible, '
        'and preserving decorations and indentation (but expanding tabs).')

    p.add_option('--utf8', '-u', action = 'store_true',
      help = 'preserve UTF-8 character encodings in the input')
    p.add_option('--width', '-w', type = 'int', default = 72,
      help = 'limit the length of filled lines to the given value '
      '(default 72)')

    result = 0

    options, files = p.parse_args()

    input_lines = []

    if files:
        for filename in files:
            try:
                f = open(filename, 'r')
            except IOError as err:
                print >> sys.stderr, str(err)
                result = 1
                continue

            for s in f:
                input_lines.append(line_data(s))
    else:
        for s in sys.stdin:
            input_lines.append(line_data(s))

    merged_lines = []

    while input_lines:
        line = input_lines.pop(0)
	if line.text:
	    while input_lines and input_lines[0].text and \
	      input_lines[0].prefix == line.prefix:
		line.text = '%s %s' % (line.text, input_lines.pop(0).text)
        merged_lines.append(line)

    wrapper = textwrap.TextWrapper()
    wrapper.width = options.width
    wrapper.fix_sentence_endings = True
    # wrapper.drop_whitespace = False

    for line in merged_lines:
	if line.text:
	    # print '[%s#%s]' % (line.prefix, line.text)
	    wrapper.initial_indent = line.prefix
	    wrapper.subsequent_indent = line.prefix
	    s = wrapper.fill(line.text)
	else:
	    s = line.prefix.rstrip()
	if options.utf8:
	    s = s.encode('utf_8')
	print s

    return result

if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(1)

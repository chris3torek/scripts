" adjustments for C code, with explanatory comments
" Note that you can type :help <keyword> (the : to enter ex style
" command as usual).

" automagic indentation of C code.  See "help c-indent"; this
" one is really complicated.  Note: this does annoying things with
" '#' characters in #define, #include, etc (they get de-indented
" to start of line) - see "help smartindent" as well.
setlocal cindent

" tab key will indent 4 spaces; control-D will de-indent 4 spaces
" (can be abbreviated as sts=4)
"setlocal softtabstop=4

" << (deindent) and >> (indent) commands will shift 4 spaces
" (can be abbreviated as sw=4)
"setlocal shiftwidth=4

" vim will not use hardware tabs (\t) and will replace them
" with spaces when you shift a block of code with << or >>
" (can be abbreviated as et)
"setlocal expandtab

" partly redundant with softtabstop: tab key will insert
" 'shiftwidth' spaces and backspace will remove 'shiftwidth'
" spaces, when you're at the start of the line
" (can be abbreviated as sta)
setlocal smarttab

" smartindent, autoindent (abbreviate as si, ai) - optional
" when using smartindent, set autoindent too.  Note that if
" you have set cindent, these don't matter (so we have them
" commented out here).
" set smartindent autoindent

" highlight trailing whitespace
" let c_space_errors = 1

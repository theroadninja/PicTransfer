#!/bin/bash

# mount | grep -v -e "on \(/\|/home\|/dev\|/net\) "

# this works:
# mount | grep -v -e "on \(/\|/home\|/dev\|/net\) " | sed 's!\(^/dev[^ ]*\).*!\1!'

list_devs () {
    mount | grep -v -e "on \(/\|/home\|/dev\|/net\) " | sed 's!\(^/dev[^ ]*\).*!\1!'
}




get_mount () {
  while IFS= read -r line; do
    # useful for bash but not python, because python will handle the backslash wrong:
    #diskutil info $line | grep -e "^.*Mount Point:" | sed 's!.*Mount Point:[^/]*\(.*\)!\1!' | sed 's/ /\\ /'
    diskutil info $line | grep -e "^.*Mount Point:" | sed 's!.*Mount Point:[^/]*\(.*\)!\1!'
  done
}

list_devs | get_mount

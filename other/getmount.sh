#!/bin/bash

while IFS= read -r line; do
    #diskutil info $line 
    #diskutil info $line | grep "Mount Point"
    diskutil info $line | grep -e "^.*Mount Point:" | sed 's!.*Mount Point:[^/]*\(.*\)!\1!' | sed 's/ /\\ /'
done

#!/bin/bash

[ "$1" == "-h" -o "$1" == "--help"  ] && { 
    echo "Usage: $0 "; 
    exit 1; } 

scriptdir=`dirname $0`

set -x
export AWS_PROFILE=concurrent_root
$scriptdir/build-and-push.sh

# ~ >  echo 
#
# 

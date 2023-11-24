#!/bin/bash

scriptdir=`dirname $0`

set -x
# need to execute update-cft-based-stack.sh in the directory with template.yaml
cd $scriptdir/..

export AWS_PROFILE=isstage2_root

#   echo "Usage: $0 <concurrent_rest_dns_name> <service_name> <scratch_bucketname> [region; default=us-east-1]"
scripts/update-cft-based-stack.sh concurrent ml1.concurrent-ai.org scratch-bucket-xyzzy-8

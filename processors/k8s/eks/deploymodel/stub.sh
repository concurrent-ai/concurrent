#!/bin/bash

mkdir -p /root
curl -o /root/bootstrap.sh https://concurrentdist.s3.amazonaws.com/scripts/bootstrap.sh
chmod 755 /root/bootstrap.sh
bash /root/bootstrap.sh
exit $?

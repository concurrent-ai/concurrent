#!/bin/bash

if [ x"$1" == "x" ] ; then
  echo "Usage: $0 namespace_to_cleanup"
  exit 255
fi

JOBS=`kubectl -n $1 get jobs|grep -v NAME| awk '{ print $1 }'`
for j in $JOBS
do
  kubectl -n $1 delete job $j
done

PODS=`kubectl -n $1 get pods|grep -v NAME | grep -v docker-dind|awk '{ print $1 }'`
for p in $PODS
do
  kubectl -n $1 delete pod $p
done

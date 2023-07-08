#!/bin/bash

if [ x"$1" == "x" ] ; then
  echo "Usage: $0 namespace_to_cleanup"
  exit 255
fi

SERVICES=`kubectl -n $1 get services |grep mlflow-deploy-endpoint|awk '{ print $1 }'`
for s in $SERVICES
do
  kubectl -n $1 delete service $s
done

DEPLOYMENTS=`kubectl -n $1 get deployments|grep -v NAME| grep -v docker-dind | awk '{ print $1 }'`
for d in $DEPLOYMENTS
do
  kubectl -n $1 delete deployment $d
done

JOBS=`kubectl -n $1 get jobs|grep -v NAME| awk '{ print $1 }'`
for j in $JOBS
do
  kubectl -n $1 delete job $j
done

#PODS=`kubectl -n $1 get pods|grep -v NAME | grep -v docker-dind|awk '{ print $1 }'`

PODS=`kubectl -n $1 get pods|grep Completed | awk '{ print $1 }'`
for p in $PODS
do
  kubectl -n $1 delete pod $p
done

PODS=`kubectl -n $1 get pods|grep Error | awk '{ print $1 }'`
for p in $PODS
do
  kubectl -n $1 delete pod $p
done

PODS=`kubectl -n $1 get pods|grep ImagePullBackOff | awk '{ print $1 }'`
for p in $PODS
do
  kubectl -n $1 delete pod $p
done

PODS=`kubectl -n $1 get pods|grep ErrImagePull | awk '{ print $1 }'`
for p in $PODS
do
  kubectl -n $1 delete pod $p
done

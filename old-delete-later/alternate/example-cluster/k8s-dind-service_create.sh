#!/bin/bash

[ -z "$NAMESPACE" ] && export NAMESPACE='nsforraj'
PV_SIZE=50Gi

envsubst < k8s-dind-service.yaml

# ~ >  echo 
#
# 

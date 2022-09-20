#!/bin/bash

if [ x"$1" == "x" ] ; then
  echo "Usage: $0 Role_ARN"
  echo " Example: ./patch-aws-auth.sh arn:aws:iam::574123455659:role/ab284a40-fbcb-11ec-944c-0aeb57ffb633-RoleForAccessingEksAndEcr"
  echo " Notes: This script must be run with the aws credentials setup as the account with the eks cluster"
  echo " Notes: kubectl must work for the cluster"
  exit 255
fi

ROLE="    - groups:\n      - system:masters\n      rolearn: $1\n      username: $1"
kubectl get -n kube-system configmap/aws-auth -o yaml | awk "/mapRoles: \|/{print;print \"$ROLE\";next}1" > /tmp/aws-auth-patch.yml
kubectl patch configmap/aws-auth -n kube-system --patch "$(cat /tmp/aws-auth-patch.yml)"

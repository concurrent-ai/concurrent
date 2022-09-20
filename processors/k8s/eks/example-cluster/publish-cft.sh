#!/bin/bash
set -e

if [ x"$1" == "x" ] ; then
  echo "Usage: $0 cft_version"
  exit 255
fi

for i in `/bin/ls *.yaml`
do
  aws s3 cp "$i" s3://docs.mlflow-parallels.org/cft/version/$1/
done

sed -e "s/REP_MLFLOW_PARALLELS_STACK_VER/$1/" freeservice/create-eks-for-parallels.yaml.template > /tmp/create-eks-for-parallels.yaml
aws s3 cp /tmp/create-eks-for-parallels.yaml s3://docs.mlflow-parallels.org/cft/version/$1/freeservice/

sed -e "s/REP_MLFLOW_PARALLELS_STACK_VER/$1/" install/create-eks-for-parallels.yaml.template > /tmp/create-eks-for-parallels.yaml
aws s3 cp /tmp/create-eks-for-parallels.yaml s3://docs.mlflow-parallels.org/cft/version/$1/install/

sed -e "s/REP_MLFLOW_PARALLELS_STACK_VER/$1/" create-k8s-role-wrapper.yaml.template > /tmp/create-k8s-role-wrapper.yaml
aws s3 cp /tmp/create-k8s-role-wrapper.yaml s3://docs.mlflow-parallels.org/cft/version/$1/

exit 0

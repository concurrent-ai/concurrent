#!/bin/bash
set -x
#/bin/rm -rf ~/.cache/pip
#docker rmi -f public.ecr.aws/k7c5t9s7/parallels-eks-bootstrap
set -e
git describe --tags --always > bootstrap-version.txt

aws ecr-public get-login-password --region us-east-1 | docker login --username AWS --password-stdin public.ecr.aws/k7c5t9s7
docker build -t parallels-eks-bootstrap -f Dockerfile --build-arg IGNORECACHE=$(date +%s) .

if [ x"$1" == "x" ] ; then
  docker tag parallels-eks-bootstrap public.ecr.aws/k7c5t9s7/parallels-eks-bootstrap:latest
  docker push public.ecr.aws/k7c5t9s7/parallels-eks-bootstrap:latest
else
  echo "Pushing to eks-bootstrap-test repo"
  docker tag parallels-eks-bootstrap public.ecr.aws/k7c5t9s7/parallels-eks-bootstrap-test:latest
  docker push public.ecr.aws/k7c5t9s7/parallels-eks-bootstrap-test:latest
fi

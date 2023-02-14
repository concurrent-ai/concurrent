#!/bin/bash
set -x
#/bin/rm -rf ~/.cache/pip
#docker rmi -f public.ecr.aws/k7c5t9s7/parallels-eks-bootstrap
set -e

# first check if the right aws credentials are active
aws s3 ls s3://docs.mlflow-parallels.org || { echo "Error: unable to access S3://docs.mlflow-parallels.org.  Ensure the right AWS credentials are setup and run again"; exit 1; } 

git describe --tags --always > bootstrap-version.txt

aws ecr-public get-login-password --region us-east-1 | docker login --username AWS --password-stdin public.ecr.aws/k7c5t9s7

[ -n "$2" ] && concurrent_plugin="--build-arg CONCURRENT_PLUGIN=$2"
docker build -t parallels-eks-bootstrap -f Dockerfile --build-arg IGNORECACHE=$(date +%s) $concurrent_plugin .

docker_repo="parallels-eks-bootstrap-test"
[ x"$1" == "x" ] && docker_repo="parallels-eks-bootstrap"

# tag with both 'latest' and 'timestamp'.  will allow referring to an older image using the timestamp tag if needed.
for image_tag in latest $(date +'%Y%m%d_%H%M%S' ) ; do
  echo "Pushing tag $image_tag to repo $docker_repo"
  docker tag parallels-eks-bootstrap public.ecr.aws/k7c5t9s7/${docker_repo}:${image_tag}
  docker push public.ecr.aws/k7c5t9s7/${docker_repo}:${image_tag}
done;

#!/bin/bash
set -x
#/bin/rm -rf ~/.cache/pip
#docker rmi -f public.ecr.aws/u5q3r5r0/concurrent-bootstrap
set -e

# first check if the right aws credentials are active
aws s3 ls s3://docs.concurrent-ai.org || { echo "Error: unable to access S3://docs.concurrent-ai.org.  Ensure the right AWS credentials are setup and run again"; exit 1; } 

echo "Recording version information for bootstrap code: $(git describe --tags --dirty --long --always) as bootstrap-version.txt"
git describe --tags --dirty --long --always > bootstrap-version.txt

aws ecr-public get-login-password --region us-east-1 | docker login --username AWS --password-stdin public.ecr.aws/k7c5t9s7

[ -n "$2" ] && concurrent_plugin="--build-arg CONCURRENT_PLUGIN=$2"
docker build -t concurrent-bootstrap -f Dockerfile --build-arg IGNORECACHE=$(date +%s) $concurrent_plugin .

docker_repo="concurrent-bootstrap-test"
[ x"$1" == "x" ] && docker_repo="concurrent-bootstrap"

# tag with both 'latest' and 'timestamp'.  will allow referring to an older image using the timestamp tag if needed.
for image_tag in latest $(date +'%Y%m%d_%H%M%S' ) ; do
  echo "Pushing image with tag '$image_tag' to docker repo '$docker_repo'"
  docker tag concurrent-bootstrap public.ecr.aws/u5q3r5r0/${docker_repo}:${image_tag}
  docker push public.ecr.aws/u5q3r5r0/${docker_repo}:${image_tag}
done;

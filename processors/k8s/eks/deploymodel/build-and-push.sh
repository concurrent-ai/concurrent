#!/bin/bash
set -x
set -e

# first check if the right aws credentials are active
aws s3 ls s3://docs.concurrent-ai.org || { echo "Error: unable to access S3://docs.concurrent-ai.org.  Ensure the right AWS credentials are setup and run again"; exit 1; } 

MINICONDA='Miniconda3-py310_23.3.1-0-Linux-x86_64.sh'
MINICONDA_MD5='e65ad52d60452ce818869c3309d7964e'
if [ ! -f "./${MINICONDA}" ] ; then
    aws s3 cp s3://concurrentdist/misc/${MINICONDA} .
fi
THIS_MD5=`md5sum Miniconda3-py310_23.3.1-0-Linux-x86_64.sh |awk '{ print $1 }'`
if [ ${THIS_MD5} != ${MINICONDA_MD5} ] ; then
    echo "Error downloading miniconda"
    exit 255
fi

git describe --tags --always > bootstrap-version.txt

aws ecr-public get-login-password --region us-east-1 | docker login --username AWS --password-stdin public.ecr.aws/u5q3r5r0

#docker build -t deploy-model -f Dockerfile --no-cache .
docker build -t deploy-model -f Dockerfile .

docker_repo="deploy-model-test"
[ x"$1" == "x" ] && docker_repo="deploy-model"

# tag with both 'latest' and 'timestamp'.  will allow referring to an older image using the timestamp tag if needed.
for image_tag in latest $(date +'%Y%m%d_%H%M%S' ) ; do
  echo "Pushing image with tag '$image_tag' to docker repo '$docker_repo'"
  docker tag deploy-model public.ecr.aws/u5q3r5r0/${docker_repo}:${image_tag}
  docker push public.ecr.aws/u5q3r5r0/${docker_repo}:${image_tag}
done;

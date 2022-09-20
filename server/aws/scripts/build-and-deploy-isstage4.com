#!/bin/bash

VERS=`git describe --tags --always`
/bin/rm -f lambdas/parallels_version.py
echo "def get_version():" > lambdas/parallels_version.py
echo "    return '"${VERS}"'" >> lambdas/parallels_version.py
echo "" >> lambdas/parallels_version.py

sam build

sam deploy --template template.yaml --stack-name mlflow-parallels-server \
  --s3-bucket scratch-bucket-xyzzy --s3-prefix mlflow-parallels-server \
  --region us-east-1 --capabilities CAPABILITY_IAM \
  --parameter-overrides ParameterKey=PoolIdParameter,ParameterValue=us-east-1_k4gJRVFFQ \
    ParameterKey=MlflowParallelsCertArnParameter,ParameterValue=arn:aws:acm:us-east-1:673036865242:certificate/1791643c-e121-4173-be63-7d9028fe4b58 \
    ParameterKey=UseBoundaryPolicy,ParameterValue=false \
    ParameterKey=BoundaryPolicyARN,ParameterValue=unused \
    ParameterKey=SubscribersTable,ParameterValue=infinstor-Subscribers \
    ParameterKey=PeriodicRunsTable,ParameterValue=infinstor-PeriodicRuns \
    ParameterKey=CustomTokensTable,ParameterValue=infinstor-queue-message-tokens \
    ParameterKey=CustomDomainParameter,ParameterValue=parallels.ai.isstage4.com || exit 1;

## sam deploy --template template.yaml --stack-name mlflow-parallels-server \
##   --s3-bucket scratch-bucket-xyzzy1 --s3-prefix mlflow-parallels-server \
##   --region us-east-1 --capabilities CAPABILITY_IAM \
##   --parameter-overrides ParameterKey=PoolIdParameter,ParameterValue=us-east-1_JR1exWFtX \
##     ParameterKey=MlflowParallelsCertArnParameter,ParameterValue=arn:aws:acm:us-east-1:549374093768:certificate/b62efdcb-13a1-4830-afd5-e1426963ecec \
##     ParameterKey=UseBoundaryPolicy,ParameterValue=false \
##     ParameterKey=BoundaryPolicyARN,ParameterValue=unused \
##     ParameterKey=CustomTokensTable,ParameterValue=infinstor-queue-message-tokens \
##     ParameterKey=CustomDomainParameter,ParameterValue=parallels.isstage6.net || exit 1;

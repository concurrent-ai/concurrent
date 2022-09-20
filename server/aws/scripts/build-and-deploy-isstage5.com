#!/bin/bash

VERS=`git describe --tags --always`
/bin/rm -f lambdas/parallels_version.py
echo "def get_version():" > lambdas/parallels_version.py
echo "    return '"${VERS}"'" >> lambdas/parallels_version.py
echo "" >> lambdas/parallels_version.py

sam build

sam deploy --template template.yaml --stack-name mlflow-parallels-server \
  --s3-bucket scratch-bucket-xyzzy-1 --s3-prefix mlflow-parallels-server \
  --region us-east-1 --capabilities CAPABILITY_IAM \
  --parameter-overrides ParameterKey=PoolIdParameter,ParameterValue=us-east-1_gTwynKi1a \
    ParameterKey=MlflowParallelsCertArnParameter,ParameterValue=arn:aws:acm:us-east-1:117250000326:certificate/c9aff02a-36cb-422c-98fe-a39697970c53 \
    ParameterKey=UseBoundaryPolicy,ParameterValue=false \
    ParameterKey=BoundaryPolicyARN,ParameterValue=unused \
    ParameterKey=SubscribersTable,ParameterValue=infinstor-Subscribers \
    ParameterKey=PeriodicRunsTable,ParameterValue=infinstor-PeriodicRuns \
    ParameterKey=CustomTokensTable,ParameterValue=infinstor-queue-message-tokens \
    ParameterKey=CustomDomainParameter,ParameterValue=parallels.ai.isstage5.com || exit 1;

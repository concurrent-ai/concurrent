#!/bin/bash

# needs to run in the directory where template.yaml is located (and directory lambdas exist): mlflow-parallels/server/aws
[ ! -f "template.yaml" ] && { echo "Error: needs to run in the directory mlflow-parallels/server/aws where template.yaml is located (and where directory lambdas exists): change directory and try again"; exit 1; }

VERS=`git describe --tags --always`
/bin/rm -f lambdas/parallels_version.py
echo "def get_version():" > lambdas/parallels_version.py
echo "    return '"${VERS}"'" >> lambdas/parallels_version.py
echo "" >> lambdas/parallels_version.py

sam build

sam deploy --template template.yaml --stack-name mlflow-parallels-server \
  --s3-bucket scratch-bucket-xyzzy-2 --s3-prefix mlflow-parallels-server \
  --region us-east-1 --capabilities CAPABILITY_IAM \
  --parameter-overrides ParameterKey=PoolIdParameter,ParameterValue=us-east-1_Cxu5bUMxH \
    ParameterKey=MlflowParallelsCertArnParameter,ParameterValue=arn:aws:acm:us-east-1:483528551273:certificate/4ae80ff8-f263-426b-85eb-c8cc2b5d6a45 \
    ParameterKey=UseBoundaryPolicy,ParameterValue=false \
    ParameterKey=BoundaryPolicyARN,ParameterValue=unused \
    ParameterKey=SubscribersTable,ParameterValue=infinstor-Subscribers \
    ParameterKey=PeriodicRunsTable,ParameterValue=infinstor-PeriodicRuns \
    ParameterKey=CustomTokensTable,ParameterValue=infinstor-queue-message-tokens \
    ParameterKey=CustomDomainParameter,ParameterValue=parallels-build-script.isstage10.com || exit 1;

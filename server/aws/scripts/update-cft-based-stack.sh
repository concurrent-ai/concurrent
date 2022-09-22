#!/bin/bash

if [ x"$2" == "x" ] ; then
  echo "Usage: $0 <concurrent_rest_dns_name> <service_name> <scratch_bucketname> [region; default=us-east-1]"
  echo "  This script updates the mlflow lambdas deployed using CFT.  It reads the name of the currently deployed mlflow lambda stack (deployed by cft) and uses the same name to run 'aws sam deploy' to update the stack"
  echo "  Example: $0 concurrent concurrent-ai.org scratch-bucket-xyzzy-3"
  exit 255
fi

[ -f "template.yaml" ] || { echo "Unable to find template.yaml.  This script must be executed from infinstor-mlflow.git/server directory.  cd to this directory and try again.. "; exit 1; }

echo "Trying to access scratch bucket s3://$3"
aws s3 ls s3://$3/ >& /dev/null || { echo "Unable to access scratch bucket s3://$3. Fix ~/.aws/credentials and try again" ; exit 1; }
echo "Successfully accessed scratch bucket s3://$3"

# set the region if specified.  Default is us-east-1
REGION="us-east-1"
[ -n "$4" ] && REGION=$4

VERS=`git describe --tags --always`
/bin/rm -f lambdas/parallels_version.py
echo "def get_version():" > lambdas/parallels_version.py
echo "    return '"${VERS}"'" >> lambdas/parallels_version.py
echo "" >> lambdas/parallels_version.py

DNS_HOST=$1
SRVC=$2

c=`cat <<EOF
import boto3
import sys

client = boto3.client('acm', region_name='$REGION')
result = client.list_certificates()
if ('CertificateSummaryList' in result):
    certs = result['CertificateSummaryList']
    for cert in certs:
        if (cert['DomainName'] == "$DNS_HOST.$SRVC" or cert['DomainName'] == "*.$SRVC"):
            print(cert['CertificateArn'])
            sys.exit(0)
sys.exit(255)
EOF`
CERT_ARN=`python3 -c "$c"`
if [ $? != 0 ] ; then
  echo "Error getting the ARN of certificate for $DNS_HOST.$SRVC"
  exit 255
fi

c=`cat <<EOF
import boto3
import sys

# if 'region_name' is not specified, defaults to us-east-1, even if ~/.aws/config is configured for ap-south-1.  So pass 'region' explicitly
client = boto3.client('cloudformation', region_name='$REGION')
stacks = client.list_stacks()
ssum = stacks['StackSummaries']

for os in ssum: 
    if os['StackStatus'] == 'CREATE_COMPLETE' or os['StackStatus'] == 'UPDATE_COMPLETE' or os['StackStatus'] == 'UPDATE_ROLLBACK_COMPLETE':
      if 'MLflowParallelsService' in os['StackName']:
        print(os['StackName'])
        sys.exit(0)
sys.exit(255)
EOF`
STACK_NAME=`python3 -c "$c"`

c=`cat <<EOF
import boto3
import sys

client = boto3.client('cognito-idp', region_name='$REGION')
up = client.list_user_pools(MaxResults=60)
ups = up['UserPools']
for oneu in ups:
    if (oneu['Name'] == 'infinstor-service-subscribers'):
        print(oneu['Id'])
        sys.exit(0)
sys.exit(255)
EOF`
USER_POOL_ID=`python3 -c "$c"`
if [ x"$USER_POOL_ID" == "x" ] ; then
  USER_POOL_ID=Unused
fi

echo "Certificate ARN="$CERT_ARN
echo "Stack Name="$STACK_NAME
echo "User Pool Id="$USER_POOL_ID

[ -z "$CERT_ARN" -o -z "$STACK_NAME" -o -z "$USER_POOL_ID" ] && { echo "One or more values is empty.. see above.. fix and retry.."; exit 1;  }

sam build

sam deploy --template template.yaml --stack-name ${STACK_NAME} \
  --s3-bucket "$3" --s3-prefix concurrent-server \
  --region "$REGION" --capabilities CAPABILITY_IAM \
  --parameter-overrides ParameterKey=PoolIdParameter,ParameterValue=${USER_POOL_ID}\
    ParameterKey=MlflowParallelsCertArnParameter,ParameterValue=${CERT_ARN} \
    ParameterKey=UseBoundaryPolicy,ParameterValue=false \
    ParameterKey=BoundaryPolicyARN,ParameterValue=unused \
    ParameterKey=SubscribersTable,ParameterValue=infinstor-Subscribers \
    ParameterKey=PeriodicRunsTable,ParameterValue=parallels-PeriodicRuns \
    ParameterKey=CustomTokensTable,ParameterValue=infinstor-queue-message-tokens \
    ParameterKey=CustomDomainParameter,ParameterValue=${DNS_HOST}.${SRVC} || exit 1;

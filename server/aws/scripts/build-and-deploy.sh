#!/bin/bash

$SET_X

if [ x"$1" == "x" ] ; then
  echo "Usage: $0 service_name"
  echo " Example: $0 service.isstage6.net"
  exit 255
fi

VERS=`git describe --tags --always`
/bin/rm -f lambdas/infinstor_version.py
echo "def get_version():" > lambdas/infinstor_version.py
echo "    return '"${VERS}"'" >> lambdas/infinstor_version.py
echo "" >> lambdas/infinstor_version.py

JS=`aws cognito-idp list-user-pools --max-results 10`
RV=$?
if [ $RV != 0 ] ; then
  echo 'Error listing user pools'
  exit $RV
fi
NLJS=`echo $JS | tr -d '\n' | sed -e 's/ //g'`
GI=/tmp/get-id.$$.py
/bin/rm -f $GI
echo "#!/bin/python3" >> $GI
echo "import sys" >> $GI
echo "import json" >> $GI
echo "jsin = json.loads(sys.argv[1])" >> $GI
echo "user_pools = jsin['UserPools']" >> $GI
echo "for user_pool in user_pools:" >> $GI
echo "     if (user_pool['Name'] == 'infinstor-service-subscribers'):" >> $GI
echo "         print(str(user_pool['Id']))" >> $GI
echo "         sys.exit(0)" >> $GI
echo "sys.exit(255)" >> $GI
USER_POOL_ID=`python3 $GI "$NLJS"`
if [ $? != 0 ] ; then
  echo 'Error extracting user pool id'
  exit $?
fi

AWS_REGION=us-east-1 # This should not be hardcoded
AWS_ACCOUNT_ID=`aws sts get-caller-identity|grep Account|awk '{ print $2 }'|sed -e 's/\"//g' | sed -e 's/,//'`
USER_POOL_ARN="arn:aws:cognito-idp:${AWS_REGION}:${AWS_ACCOUNT_ID}:userpool\/${USER_POOL_ID}"

echo "AWS Account ID= $AWS_ACCOUNT_ID , User Pool ID= $USER_POOL_ID , User Pool ARN= $USER_POOL_ARN"

# Get the ARN of the certificate for mlflow.X.com and pass it to sam
# Do this in the base conda env because the infinstorlambda conda env cannot contain boto3
SRVC=`echo $1 | sed -e 's/service\.\(.*\)$/\1/'`
c=`cat <<EOF
import boto3
import sys

client = boto3.client('acm')
result = client.list_certificates()
if ('CertificateSummaryList' in result):
    certs = result['CertificateSummaryList']
    for cert in certs:
        if (cert['DomainName'] == "mlflow.$SRVC"):
            print(cert['CertificateArn'])
            sys.exit(0)
sys.exit(255)
EOF`
CERT_ARN=`python3 -c "$c"`
if [ $? != 0 ] ; then
  echo "Error getting the ARN of certificate for mlflow.$SRVC"
  exit 255
fi
echo "Using ARN $CERT_ARN for the cert for mlflow.$SRVC"

conda --version >& /dev/null
if [ $? == 0 ] ; then
  echo 'Found conda in the PATH. Attempting to activate infinstorlambda conda env for sam'
  CONDABINARY=`which conda`
  CONDABINDIR=`dirname $CONDABINARY`
  # if "activate command" exists
  if [ -f "$CONDABINDIR/activate" ]; then
    source $CONDABINDIR/activate infinstorlambda || exit 1;   # exit with error if can't source the specified file.. earlier we continued even if the sourcing files
  else
    # if "activate" command does not exist (happens inside the build docker container with sam where /opt/conda/condabin/activate does not exist), then following error is seen.  
    #
    # + echo 'Found conda in the PATH. Attempting to activate infinstorlambda conda env for sam'
    # Found conda in the PATH. Attempting to activate infinstorlambda conda env for sam
    # ++ which conda
    # + CONDABINARY=/opt/conda/condabin/conda
    # ++ dirname /opt/conda/condabin/conda
    # + CONDABINDIR=/opt/conda/condabin
    # + source /opt/conda/condabin/activate infinstorlambda
    # ./scripts/build-and-deploy.sh: line 59: /opt/conda/condabin/activate: No such file or directory  
    # 
    # fix is the code below..  calling source ~/.bashrc to make 'conda' command available doesn't work since .bashrc will exit if the shell is not interactive
    #   code below copied from ~/.bashrc
    
    # >>> conda initialize >>>
    # !! Contents within this block are managed by 'conda init' !!
    __conda_setup="$('conda' 'shell.bash' 'hook' 2> /dev/null)"
    if [ $? -eq 0 ]; then
        eval "$__conda_setup" || exit 1
        conda activate infinstorlambda  || exit 1
        conda env list      # to check if infinstorlambda has been activated correctly..
    else
        echo "Unable to find 'conda' command"; exit 1;
    fi           
  fi
else
  echo 'conda not found in PATH. sam needs to be available and functional in the PATH' && exit 1;
fi

sam build
sam deploy --template template.yaml --stack-name infinstor-mlflow-server \
  --s3-bucket infinstor-service-jars-$1 --s3-prefix mlflow-server \
  --region ${AWS_REGION} --capabilities CAPABILITY_IAM \
  --parameter-overrides ParameterKey=PoolIdParameter,ParameterValue=${USER_POOL_ID} \
    ParameterKey=MlflowCertArnParameter,ParameterValue=${CERT_ARN} \
    ParameterKey=UseBoundaryPolicy,ParameterValue=false \
    ParameterKey=BoundaryPolicyARN,ParameterValue=unused \
    ParameterKey=CustomDomainParameter,ParameterValue=mlflow.${SRVC} || exit 1;

PERIOD_RUN_ARN=`aws lambda  list-functions|grep periodrun|grep FunctionArn |sed -e 's/",$//' | sed -e 's/.*FunctionArn.*\(arn.*\)/\1/'`
echo "periodrun lambda ARN is " $PERIOD_RUN_ARN
set +e # grep will fail if perm does not exist. we don't want the script to quit if that happens
aws lambda get-policy --function-name "${PERIOD_RUN_ARN}" | grep TrustCWEToInvokeMyLambdaFunction >& /dev/null
if [ $? == 0 ] ; then
  echo "Resource policy TrustCWEToInvokeMyLambdaFunction exists. Not creating."
else
  echo "Resource policy TrustCWEToInvokeMyLambdaFunction does not exist. Creating."
  echo 'Adding permission for AWS Events to call the periodrun lambda'
  aws lambda add-permission --statement-id "TrustCWEToInvokeMyLambdaFunction" \
    --action "lambda:InvokeFunction" \
    --principal "events.amazonaws.com" \
    --function-name "$PERIOD_RUN_ARN" \
    --source-arn "arn:aws:events:${AWS_REGION}:${AWS_ACCOUNT_ID}:rule/*"

  if [ $? != 0 ] ; then
    echo "WARNING: Adding permission for AWS Events to call periodrun lambda failed"
  fi
fi

RUN_PROJECT_ARN=`aws lambda  list-functions|grep runproject|grep FunctionArn |sed -e 's/",$//' | sed -e 's/.*FunctionArn.*\(arn.*\)/\1/'`
CREATE_RUN_ARN=`aws lambda  list-functions|grep createrun|grep FunctionArn |sed -e 's/",$//' | sed -e 's/.*FunctionArn.*\(arn.*\)/\1/'`

# get the mlflowApiId
# This could be done more elegantly in python, but we don't want to depend on
# python in our build and deploy script
NXT=""
MLFLOW_API_ID=""
for (( ; ; ))
do
  if [ -z $NXT ] ; then
    aws apigateway get-rest-apis --max-items 1 | grep infinstor-mlflow-server >& /dev/null
    if [ $? == 0 ] ; then
      MLFLOW_API_ID=`aws apigateway get-rest-apis --max-items 1 | grep "\"id\"" | sed -e 's/.*"id": "\(.*\)"/\1/' | sed -e 's/,$//'`
      break
    else
      NXTLINE=`aws apigateway get-rest-apis --max-items 1 | grep NextToken`
      if [ $? == 0 ] ; then
        NXT=`echo ${NXTLINE} | sed -e 's/ *"NextToken": "\(.*\)"/\1/'`
      else
        break
      fi
    fi
  else
    aws apigateway get-rest-apis --max-items 1 --starting-token "$NXT" | grep infinstor-mlflow-server >& /dev/null
    if [ $? == 0 ] ; then
      MLFLOW_API_ID=`aws apigateway get-rest-apis --max-items 1 --starting-token "$NXT" | grep "\"id\"" | sed -e 's/.*"id": "\(.*\)"/\1/' | sed -e 's/,$//'`
      break
    else
      NXTLINE=`aws apigateway get-rest-apis --max-items 1 --starting-token "$NXT" | grep NextToken`
      if [ $? == 0 ] ; then
        NXT=`echo ${NXTLINE} | sed -e 's/ *"NextToken": "\(.*\)"/\1/'`
      else
        break
      fi
    fi
  fi
done
if [ -z $MLFLOW_API_ID ] ; then
  echo "WARNING: Could not determine MLFLOW API ID"
else
  echo mlflowApiId is ${MLFLOW_API_ID}
fi

echo "Updating service conf with the following values:"
echo "    createRunLambda is " $CREATE_RUN_ARN
echo "    runProjectLambda is " $RUN_PROJECT_ARN
echo "    periodRunLambdaArn is " $PERIOD_RUN_ARN
echo "    mlflowApiId is " $MLFLOW_API_ID

UPDATE_EXPRESSION="SET #C = :c, #R = :r, #P = :p, #M = :m"

/bin/rm -f /tmp/key.json.$$
echo "{" >> /tmp/key.json.$$
echo "  \"configVersion\": {\"N\": \"1\" }" >> /tmp/key.json.$$
echo "}" >> /tmp/key.json.$$

/bin/rm -f /tmp/ean.json.$$
echo "{" >> /tmp/ean.json.$$
echo "  \"#C\": \"createRunLambda\"," >> /tmp/ean.json.$$
echo "  \"#R\": \"runProjectLambda\"," >> /tmp/ean.json.$$
echo "  \"#P\": \"periodRunLambdaArn\"," >> /tmp/ean.json.$$
echo "  \"#M\": \"mlflowApiId\"" >> /tmp/ean.json.$$
echo "}" >> /tmp/ean.json.$$

/bin/rm -f /tmp/eav.json.$$
echo "{" >> /tmp/eav.json.$$
echo "  \":c\": {\"S\": \"$CREATE_RUN_ARN\" }," >> /tmp/eav.json.$$
echo "  \":r\": {\"S\": \"$RUN_PROJECT_ARN\" }," >> /tmp/eav.json.$$
echo "  \":p\": {\"S\": \"$PERIOD_RUN_ARN\" }," >> /tmp/eav.json.$$
echo "  \":m\": {\"S\": \"$MLFLOW_API_ID\" }" >> /tmp/eav.json.$$
echo "}" >> /tmp/eav.json.$$

aws dynamodb update-item \
  --table-name infinstor-ServiceConf \
  --key file:///tmp/key.json.$$ \
  --update-expression "$UPDATE_EXPRESSION" \
  --expression-attribute-names file:///tmp/ean.json.$$ \
  --expression-attribute-values file:///tmp/eav.json.$$ \
  --return-values ALL_NEW \
  --return-consumed-capacity TOTAL \
  --return-item-collection-metrics SIZE >& /dev/null

if [ $? == 0 ] ; then
  echo "Update of ServiceConf table succeeded"
  /bin/rm -f /tmp/key.json.$$ /tmp/ean.json.$$ /tmp/eav.json.$$
else
  echo "WARNING: Update of ServiceConf table did not go well. Not removing json files /tmp/key.json.$$ /tmp/ean.json.$$ /tmp/eav.json.$$"
fi

exit 0

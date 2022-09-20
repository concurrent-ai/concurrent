#! /bin/bash
set -e
if [ x"$3" == "x" ] ; then
  echo "Usage: $0 cft_version_number parallels_lambda_version parallels_ui_version "
  echo "Example: $0 1.1.1 2.2.2 3.3.3"
  echo "Do not prefix version with v, i.e. 2.1.1 and not v2.1.1"
  exit 255
fi

echo "Trying to access bucket parallelsdist.."
aws s3 ls s3://parallelsdist/ >& /dev/null
echo "Successfully accessed bucket parallelsdist.."

echo "#####################################################################################" > mlflow-parallels-cft.yaml
echo "# This is an auto generated file.  Do not edit it.  Any changes will be overwritten #" >> mlflow-parallels-cft.yaml
echo "#####################################################################################" >> mlflow-parallels-cft.yaml
{ sed -e "s/REP_VER_PARALLELS_CFT/$1/" mlflow-parallels-cft-template.yaml  | sed -e "s/REP_VER_PARALLELS_LAMBDA/$2/"  | sed -e "s/REP_VER_PARALLELS_UI/$3/" ; } >> mlflow-parallels-cft.yaml

for file in certs-cft.json mlflow-parallels-cft-template.yaml mlflow-parallels-cft.yaml mlflow-parallels-cognito-user-pool-cft.json mlflow-parallels-lambdas-cft.json serviceconf-cft-lambda.py serviceconf-cft.yaml single-tenant-cft-lambda.py single-tenant-cft.yaml  staticfiles-cft-lambda.py staticfiles-cft.yaml; do
    aws s3 cp $file s3://parallelsdist/cft/parallels-cft/"$1"/$file
done;

# don't do the tagging here since the generated mlflow-parallels-cft.yaml is not checked in yet.
# if [ "$4" != "with_notag" ]; then
#   git tag "parallels-cft-$1"
#   git push origin "parallels-cft-$1"
# else
#   echo "Not tagging since '$2' was passed"
# fi;


exit 0
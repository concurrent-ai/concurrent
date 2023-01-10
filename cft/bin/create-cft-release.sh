#!/bin/bash
#set -x

get_concurrent_appid() {
  LA=`aws --region $1 serverlessrepo list-applications`
  if [ $? != 0 ] ; then
    echo 'Error listing serverless applications'
    exit 255
  fi
  export LA
  python3 << ENDPY
import json
import os

apps = json.loads(os.getenv('LA'))
for app in apps['Applications']:
    if app['ApplicationId'].endswith('concurrent-lambda'):
        print(app['ApplicationId'], flush=True)
        os._exit(0)
ENDPY
}

get_software_versions() {
  VFILE_CONTENTS=`python3 << ENDPY
import json
import os
import boto3

try:
  client = boto3.client('s3')
  data = client.get_object(Bucket='concurrentdist', Key='cft/parallels-cft/latest-software-versions.json')
  contents = data['Body'].read()
  print(contents.decode('utf-8'), flush=True)
except Exception as e1:
  print('Caught ' + str(e1) + ' while reading latest-software-versions.json')
  os._exit(255)
ENDPY`
export VFILE_CONTENTS
  export CFT_VERSION=`python3 << ENDPY
import json
import os

try:
  rjson = json.loads(os.getenv('VFILE_CONTENTS'))
  print(rjson['cft_version'], flush=True)
  os._exit(0)
except Exception as e1:
  print('Caught ' + str(e1) + ' while reading latest-software-versions.json')
  os._exit(255)
ENDPY`
  export CONCURRENT_LAMBDAS_VERSION=`python3 << ENDPY
import json
import os

try:
  rjson = json.loads(os.getenv('VFILE_CONTENTS'))
  print(rjson['concurrent_lambdas'], flush=True)
  os._exit(0)
except Exception as e1:
  print('Caught ' + str(e1) + ' while reading latest-software-versions.json')
  os._exit(255)
ENDPY`
  export CONCURRENT_UI_VERSION=`python3 << ENDPY
import json
import os

try:
  rjson = json.loads(os.getenv('VFILE_CONTENTS'))
  print(rjson['concurrent_ui'], flush=True)
  os._exit(0)
except Exception as e1:
  print('Caught ' + str(e1) + ' while reading latest-software-versions.json')
  os._exit(255)
ENDPY`
}

aws s3 ls s3://concurrentdist/ >& /dev/null
if [ $? != 0 ] ; then
  echo "Error accessing S3 bucket concurrentdist. Configure aws credentials for concurrent and try again"
  exit 255
fi

get_software_versions
echo 'Current CFT Version:' $CFT_VERSION
echo 'Current Concurrent Lambdas: ' $CONCURRENT_LAMBDAS_VERSION
echo 'Current Concurrent UI: ' $CONCURRENT_UI_VERSION

for var in "$@"
do
    if [[ $var == new_cft_version* ]] ; then
      NEW_CFT_VERSION=`echo $var | awk -F= '{ print $2 }'`
      echo "NEW_CFT_VERSION=$NEW_CFT_VERSION"
    elif [[ $var == concurrent_lambdas* ]] ; then
      CONCURRENT_LAMBDAS=`echo $var | awk -F= '{ print $2 }'`
      EON_CONCURRENT_LAMBDAS=`echo $CONCURRENT_LAMBDAS | awk -F: '{ print $1 }'`
      if [ $EON_CONCURRENT_LAMBDAS == "new" ] ; then
        NEW_CONCURRENT_LAMBDAS=`echo $CONCURRENT_LAMBDAS | awk -F: '{ print $2 }'`
      elif [ $EON_CONCURRENT_LAMBDAS == "existing" ] ; then
        EXISTING_CONCURRENT_LAMBDAS=`echo $CONCURRENT_LAMBDAS | awk -F: '{ print $2 }'`
      else
        echo "Error. Incorrect specification of concurrent_lambdas"
        exit 255
      fi
    elif [[ $var == concurrent_ui* ]] ; then
      CONCURRENT_UI=`echo $var | awk -F= '{ print $2 }'`
      EON_CONCURRENT_UI=`echo $CONCURRENT_UI | awk -F: '{ print $1 }'`
      if [ $EON_CONCURRENT_UI == "new" ] ; then
        NEW_CONCURRENT_UI=`echo $CONCURRENT_UI | awk -F: '{ print $2 }'`
      elif [ $EON_CONCURRENT_UI == "existing" ] ; then
        EXISTING_CONCURRENT_UI=`echo $CONCURRENT_UI | awk -F: '{ print $2 }'`
      else
        echo "Error. Incorrect specification of concurrent_ui"
        exit 255
      fi
    elif [[ $var == overwrite_cft ]] ; then
      OVERWRITE_CFT=true
      echo "Overwriting CFT version if it is present"
    elif [[ $var == update_version_json ]] ; then
      UPDATE_VERSION_JSON=true
      echo "Updating latest-software-versions.json"
    else
      echo "Error. Unknown parameter $var"
      printf "Usage: $0 new_cft_version=a.b.c\n\t[overwrite_cft]\n\t[update_version_json]\n\t[concurrent_lambdas=new:a.b.c|existing:x.y.z]\n\t[concurrent_ui=new:a.b.c|existing:x.y.z]\n"
      exit 255
    fi
done

if [ x$NEW_CFT_VERSION == "x" ] ; then
  echo "Error. new_cft_version must be specified"
  printf "Usage: $0 new_cft_version=a.b.c\n\t[overwrite_cft]\n\t[update_version_json]\n\t[concurrent_lambdas=new:a.b.c|existing:x.y.z]\n\t[concurrent_ui=new:a.b.c|existing:x.y.z]\n"
  exit 255
fi

aws s3 ls s3://concurrentdist/cft/parallels-cft/$NEW_CFT_VERSION/ >& /dev/null
if [ $? == 0 ] ; then
  if [ x$OVERWRITE_CFT == "x" ] ; then
    echo "Error. New CFT Version $NEW_CFT_VERSION already exists in s3://concurrentdist/cft/parallels-cft/$NEW_CFT_VERSION/. Use overwrite_cft if you want to overwrite"
    exit 255
  fi
fi

/bin/rm -f workdir/*.template

if [ ! -d workdir ] ; then
  /bin/mkdir workdir
fi

if [ x$NEW_CONCURRENT_LAMBDAS != "x" ] ; then
  echo "Building and publishing new Concurrent Lambdas version $NEW_CONCURRENT_LAMBDAS"
  CONCURRENT_US_EAST_1_APPID=`get_concurrent_appid us-east-1`
  CONCURRENT_AP_SOUTH_1_APPID=`get_concurrent_appid ap-south-1`
  echo "Concurrent Serverless Application Appid in us-east-1 is $CONCURRENT_US_EAST_1_APPID"
  echo "Concurrent Serverless Application Appid in ap-south-1 is $CONCURRENT_AP_SOUTH_1_APPID"
  if [ -d workdir/concurrent ] ; then
    echo "Cleaning up existing concurrent source tree"
    (cd workdir/concurrent; /bin/rm -f server/aws/lambdas/parallels_version.py)
    (cd workdir/concurrent; git reset --hard)
    (cd workdir/concurrent; git checkout main)
  else
    echo "Checking out concurrent source tree"
    (cd workdir; git clone https://github.com/concurrent-ai/concurrent.git)
    if [ $? != 0 ] ; then
      echo "Error cloning concurrent"
      exit $?
    fi
  fi
  echo "Fetching all tags for the concurrent source tree"
  (cd workdir/concurrent; git fetch --all --tags)
  if [ $? != 0 ] ; then
    echo "Error fetching all tags in source tree concurrent"
    exit $?
  fi
  echo "Checkout out tag $NEW_CONCURRENT_LAMBDAS in the concurrent source tree"
  (cd workdir/concurrent; git -c advice.detachedHead=false checkout tags/$NEW_CONCURRENT_LAMBDAS)
  if [ $? != 0 ] ; then
    echo "Error checking out tag $NEW_CONCURRENT_LAMBDAS in source tree concurrent. Perhaps tag $NEW_CONCURRENT_LAMBDAS does not exist?"
    exit $?
  fi
  echo "Running create_layer.sh to create the dependent layer for Concurrent lambdas"
  (cd workdir/concurrent/server/aws; ./scripts/create-layer.sh)
  if [ $? != 0 ] ; then
    echo "Error creating layer using create-leyer.sh for version $NEW_CONCURRENT_LAMBDAS in source tree concurrent"
    exit $?
  fi
  echo "Running update-cft-based-stack.sh to deploy lambdas to concurrent aws account"
  (cd workdir/concurrent/server/aws; ./scripts/update-cft-based-stack.sh concurrent concurrent-ai.org scratch-bucket-xyzzy-3) >& /tmp/concurrent-build.log.$$
  UPLINER=`grep 'Uploading to concurrent-server/.*\.template .*100.00\%' /tmp/concurrent-build.log.$$`
  if [ $? != 0 ] ; then
    grep 'Error: No changes to deploy. Stack concurrent-server is up to date' /tmp/concurrent-build.log.$$
    if [ $? == 0 ] ; then
      echo "Error. No changes in Concurrent Lambda"
      exit 255
    fi
    echo "Error determining the name of the generated template.yaml file. Details in file /tmp/concurrent-build.log.$$"
    exit $?
  fi
  UPLINE=`echo $UPLINER| tr -d '\n' | tr -d '\r'`
  CONCURRENT_TEMPLATE_FILE=`echo $UPLINE | sed -e 's/Uploading to \(concurrent-server\/.*template\).*/\1/'`
  echo "Concurrent Lambdas generated template file name is $CONCURRENT_TEMPLATE_FILE"
  aws s3 cp s3://scratch-bucket-xyzzy-3/$CONCURRENT_TEMPLATE_FILE ./workdir
  if [ $? != 0 ] ; then
    echo "Error downloading the generated template.yaml file $CONCURRENT_TEMPLATE_FILE"
    exit $?
  fi
  echo "Using AWS CLI to create new application version $NEW_CONCURRENT_LAMBDAS for application $CONCURRENT_US_EAST_1_APPID"
  CONCURRENT_TEMPLATE_FILE_LAST=`echo $CONCURRENT_TEMPLATE_FILE | sed -e 's/concurrent-server\/\(.*\)/\1/'`
  TEMPL=`cat workdir/$CONCURRENT_TEMPLATE_FILE_LAST`
  aws --region us-east-1 serverlessrepo create-application-version --application-id $CONCURRENT_US_EAST_1_APPID --semantic-version $NEW_CONCURRENT_LAMBDAS --source-code-url https://gituhub.com/concurrent-ai/concurrent.git --template-body "$TEMPL" > /dev/null
  if [ $? != 0 ] ; then
    echo "Error creating new application version $NEW_CONCURRENT_LAMBDAS for application $CONCURRENT_US_EAST_1_APPID"
    exit $?
  fi
  aws --region ap-south-1 serverlessrepo create-application-version --application-id $CONCURRENT_AP_SOUTH_1_APPID --semantic-version $NEW_CONCURRENT_LAMBDAS --source-code-url https://gituhub.com/concurrent-ai/concurrent.git --template-body "$TEMPL" > /dev/null
  if [ $? != 0 ] ; then
    echo "Error creating new application version $NEW_CONCURRENT_LAMBDAS for application $CONCURRENT_AP_SOUTH_1_APPID"
    exit $?
  fi
elif [ x$EXISTING_CONCURRENT_LAMBDAS != "x" ] ; then
  echo "Using existing Concurrent Lambdas $EXISTING_CONCURRENT_LAMBDAS"
  NEW_CONCURRENT_LAMBDAS=$EXISTING_CONCURRENT_LAMBDAS
else
  echo "Concurrent Lambdas version not specified. Using latest version of Concurrent Lambdas from s3://infinstorcft/latest-software-versions.json: $CONCURRENT_LAMBDAS_VERSION"
  NEW_CONCURRENT_LAMBDAS=$CONCURRENT_LAMBDAS_VERSION
fi

if [ x$NEW_CONCURRENT_UI != "x" ] ; then
  echo "Building and Updating Concurrent UI version=$NEW_CONCURRENT_UI"
  if [ -d workdir/mlflow-noproxy ] ; then
    echo "Cleaning up existing mlflow-noproxy source tree"
    (cd workdir/mlflow-noproxy; git reset --hard)
    (cd workdir/mlflow-noproxy; git checkout master)
  else
    echo "Checking out mlflow-noproxy source tree"
    (cd workdir; git clone https://git-codecommit.us-east-1.amazonaws.com/v1/repos/mlflow-noproxy)
    if [ $? != 0 ] ; then
      echo "Error cloning mlflow-noproxy"
      exit $?
    fi
  fi
  echo "Fetching all tags for the mlflow-noproxy source tree"
  (cd workdir/mlflow-noproxy; git fetch --all --tags)
  if [ $? != 0 ] ; then
    echo "Error fetching all tags in source tree mlflow-noproxy"
    exit $?
  fi
  echo "Checkout out tag $NEW_CONCURRENT_UI in the mlflow-noproxy source tree"
  (cd workdir/mlflow-noproxy; git -c advice.detachedHead=false checkout tags/$NEW_CONCURRENT_UI)
  if [ $? != 0 ] ; then
    echo "Error checking out tag $NEW_CONCURRENT_UI in source tree mlflow-noproxy. Perhaps tag $NEW_CONCURRENT_UI does not exist?"
    exit $?
  fi
  (cd workdir/mlflow-noproxy; ./scripts/build-and-copy-mlflow-noproxy-parallels.sh $NEW_CONCURRENT_UI)
  if [ $? != 0 ] ; then
    echo "Error building and copying $NEW_CONCURRENT_UI version of Concurrent UI"
    exit $?
  fi
elif [ x$EXISTING_CONCURRENT_UI != "x" ] ; then
  echo "Using existing Concurrent UI $EXISTING_CONCURRENT_UI"
  NEW_CONCURRENT_UI=$EXISTING_CONCURRENT_UI
else
  echo "Concurrent UI Version not specified. Using latest version of Concurrent UI from s3://infinstorcft/latest-software-versions.json: $CONCURRENT_UI_VERSION"
  NEW_CONCURRENT_UI=$CONCURRENT_UI_VERSION
fi

# Create new CFT version

echo "#####################################################################################" > mlflow-parallels-cft.yaml
echo "# This is an auto generated file.  Do not edit it.  Any changes will be overwritten #" >> mlflow-parallels-cft.yaml
echo "#####################################################################################" >> mlflow-parallels-cft.yaml
{ sed -e "s/REP_VER_PARALLELS_CFT/$NEW_CFT_VERSION/" mlflow-parallels-cft-template.yaml  | sed -e "s/REP_VER_PARALLELS_LAMBDA/$NEW_CONCURRENT_LAMBDAS/"  | sed -e "s/REP_VER_PARALLELS_UI/$NEW_CONCURRENT_UI/" ; } >> mlflow-parallels-cft.yaml

for file in certs-cft.json mlflow-parallels-cft-template.yaml mlflow-parallels-cft.yaml mlflow-parallels-cognito-user-pool-cft.json mlflow-parallels-lambdas-cft.json serviceconf-cft-lambda.py serviceconf-cft.yaml single-tenant-cft-lambda.py single-tenant-cft.yaml  staticfiles-cft-lambda.py staticfiles-cft.yaml; do
    aws s3 cp $file s3://concurrentdist/cft/parallels-cft/"$NEW_CFT_VERSION"/$file
done;

if [ "$UPDATE_VERSION_JSON" == "true" ] ; then
  echo "Updating s3://concurrentdist/cft/parallels-cft/latest-software-versions.json"
  echo "{" > /tmp/latest-software-versions.json.$$
  echo "  \"cft_version\": \"$NEW_CFT_VERSION\"," >> /tmp/latest-software-versions.json.$$
  echo "  \"concurrent_lambdas\": \"$NEW_CONCURRENT_LAMBDAS\"," >> /tmp/latest-software-versions.json.$$
  echo "  \"concurrent_ui\": \"$NEW_CONCURRENT_UI\"" >> /tmp/latest-software-versions.json.$$
  echo "}" >> /tmp/latest-software-versions.json.$$
  aws s3 cp /tmp/latest-software-versions.json.$$ s3://concurrentdist/cft/parallels-cft/latest-software-versions.json
else
  echo "Not updating s3://concurrentdist/cft/parallels-cft/latest-software-versions.json"
fi


# remove temporary file, after copying it above, to keep git workspace clean
/bin/rm -f mlflow-parallels-cft.yaml

exit 0

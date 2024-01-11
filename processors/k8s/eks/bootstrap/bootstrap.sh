#!/bin/bash

# if there is an error, abort
set -e
set -x

logit() {
    echo "`date` - $$ - INFO - bootstrap.sh - ${*}" # >> ${LOG_FILE}
    # [ -n "$LOG_FILE" ] && echo "`date` - $$ - INFO - bootstrap.sh - ${*}"  >> "${LOG_FILE}"
}

BOOTSTRAP_LOG_FILE="/tmp/bootstrap-log-${ORIGINAL_NODE_ID}.txt"

if [ x"${PARENT_RUN_ID}" == "x" ] ; then
    PARENT_RUN_ID=$MLFLOW_RUN_ID
    export PARENT_RUN_ID
fi

update_mlflow_run() {
  export MLFLOW_RUN_ID=$1
  export UPD_STATUS=$2
  python3 << ENDPY
import sys
import os
import mlflow
from mlflow.tracking import MlflowClient
${ADDITIONAL_IMPORTS}

client = MlflowClient()
print(f"Attempting to set mlflow run_id={os.getenv('MLFLOW_RUN_ID')} with status={os.getenv('UPD_STATUS')}")
client.set_terminated(os.getenv('MLFLOW_RUN_ID'), os.getenv('UPD_STATUS'))
ENDPY
}

log_mlflow_artifact() {
  export MLFLOW_RUN_ID=$1
  export ARTIFACT=$2
  export DESTINATION_PREFIX=$3
  python3 << ENDPY
import sys
import os
import mlflow
from mlflow.tracking import MlflowClient
${ADDITIONAL_IMPORTS}

client = MlflowClient()
artifact = os.getenv('ARTIFACT')
if os.path.isdir(artifact):
    client.log_artifacts(os.getenv('MLFLOW_RUN_ID'), artifact, os.getenv('DESTINATION_PREFIX'))
else:
    client.log_artifact(os.getenv('MLFLOW_RUN_ID'), artifact, os.getenv('DESTINATION_PREFIX'))
ENDPY
}

num_of_images() {
  export ECR_OP=$1
  python3 << ENDPY
import os
import json
try:
  js = json.loads(open(os.getenv('ECR_OP'), "r").read().encode('utf-8'))
  id = js['imageDetails']
  if len(id) > 0:
    print(f"{len(id)}", flush=True)
    os._exit(0)
  else:
    print("0", flush=True)
    os._exit(0)
except Exception as ex:
  print("-1", flush=True)
  os._exit(0)
ENDPY
  return $?
}

fail_exit() {
  logit "script exited: logging bootstrap output to mlflow"
  update_mlflow_run ${PARENT_RUN_ID} "FAILED" 
  kubectl logs "${MY_POD_NAME}" > ${BOOTSTRAP_LOG_FILE}
  log_mlflow_artifact ${PARENT_RUN_ID} ${BOOTSTRAP_LOG_FILE} '.concurrent/logs'
  exit 255
}

# trap: trap [-lp] [[arg] signal_spec ...]
#
# If a SIGNAL_SPEC is EXIT (0) ARG is executed on exit from the shell.  
# If a SIGNAL_SPEC is DEBUG, ARG is executed before every simple command.  
# If a SIGNAL_SPEC is RETURN, ARG is executed each time a shell function or a  script run by the . or source builtins finishes executing.  
# A SIGNAL_SPEC of ERR means to execute ARG each time a command's failure would cause the shell to exit when the -e option is enabled.
trap fail_exit EXIT

scriptdir=`dirname $0`
[ -f "$scriptdir/bootstrap-version.txt" ] && logit "Bootstrap version: $(cat $scriptdir/bootstrap-version.txt)"


logit "Environment: "
typeset -p

setup_docker_secret() {
  DOCKER_CONFIG_JSON=`cat /root/.docker/config.json | base64 -w0`
  /bin/rm -f $1
  echo "apiVersion: v1" > $1
  echo "kind: Secret" >> $1
  echo "metadata:" >> $1
  echo "  name: ecr-private-key" >> $1
  echo "  namespace: $2" >> $1
  echo "data:" >> $1
  echo "  .dockerconfigjson: $DOCKER_CONFIG_JSON" >> $1
  echo "type: kubernetes.io/dockerconfigjson" >> $1
}

get_repository_uri() {
  /bin/rm -f /tmp/reps
  if ! aws --profile ecr --region $2 $1 describe-repositories > /tmp/reps ; then
    logit "Error listing repositories $1"
    return 255
  fi
  export REP_NAME=$3
  python3 << ENDPY
import sys
import os
import json

reps = json.loads(open('/tmp/reps', "r").read().encode('utf-8'))
rp = os.getenv('REP_NAME')
for one in reps['repositories']:
  if one['repositoryName'] == rp:
    print(one['repositoryUri'])
    sys.exit(0)
sys.exit(255)
ENDPY
  return $?
}

download_project_files() {
  export MLFLOW_RUN_ID
  python3 << ENDPY
import sys
import os
import mlflow
from mlflow.tracking import MlflowClient

run_id = os.getenv('MLFLOW_RUN_ID')
spath = '.concurrent/project_files'

client = MlflowClient()
client.download_artifacts(run_id, spath, '/tmp/workdir')
sys.exit(0)
ENDPY
}

get_xform() {
  
  if (cd /tmp/workdir; git clone "$XFORMNAME" >& /tmp/git.log.$$) ; then
    # CINTO is a lin similar to "Cloning into 'cwsearch'  xxxxx"
    if CINTO=`grep 'Cloning into' /tmp/git.log.$$` ; then
      # from CINTO, extract the subdirectory into which the clone was done: first sed replaces everything from beginning until "'" with an empty string; 2nd sed replaces everything from a "'" till the end of the string with an empty string.
      export USE_SUBDIR=`echo $CINTO | sed -e "s/^Cloning into '//"|sed -e "s/'.*$//"`/
      if [ x"$XFORM_PATH" != "x" ] ; then
          export USE_SUBDIR=${USE_SUBDIR}${XFORM_PATH}/
      fi
      logit "USE_SUBDIR=$USE_SUBDIR"
      
      # write the output of git describe to store version details of the Mlproject being executed.
      ( cd /tmp/workdir/$USE_SUBDIR; echo "Creating version.txt: Version information of MLproject: $XFORMNAME:$(git describe --all --long --always)"; echo "Version information of MLproject: $XFORMNAME:$(git describe --all --long --always)" > version.txt )
      
      # get the 'git commit id' of the tip of the branch.  the docker image created later is tagged using this 'git commit id'
      CMT=`(cd /tmp/workdir/$USE_SUBDIR; git log -n 1 | grep '^commit '|sed -e 's/commit \(.*\)$/\1/')`
      if [ $? == 0 ] ; then
        if [ x$CMT != "x" ] ; then
          export GIT_COMMIT=$CMT
          logit "GIT_COMMIT=$GIT_COMMIT"
        else
          unset GIT_COMMIT
        fi
      else
        unset GIT_COMMIT
      fi
      (cd /tmp/workdir/$USE_SUBDIR; /bin/rm -rf .git)
    else
      logit "Error cloning git tree $XFORMNAME"
      cat /tmp/git.log.$$
      fail_exit
    fi
  else
    logit "Error checking out git tree $XFORMNAME"
    fail_exit
  fi
}

docker_img_from_mlproject() {
  export USE_SUBDIR
  python3 << ENDPY
import sys
import os
from mlflow.projects.utils import load_project

try:
    project = load_project("/tmp/workdir/" + os.getenv('USE_SUBDIR'))
except:
    sys.exit(255)
docker_image = project.docker_env.get("image")
if not docker_image:
  sys.exit(255)
else:
  print(docker_image)
  sys.exit(0)
ENDPY
}

get_python_package_version() {
  export PACKAGE_NAME=$1
  python3 << ENDPY
import os
from importlib.metadata import version
package_name = os.environ['PACKAGE_NAME']
print(version(package_name))
ENDPY
}

logit "MLFLOW_TRACKING_URI = " $MLFLOW_TRACKING_URI
# if tracking uri is not set, then error
[ -z "$MLFLOW_TRACKING_URI" ] && logit "Error: MLFLOW_TRACKING_URI is not set.  " && fail_exit

if [ x"$ADDITIONAL_PACKAGES" != "x" ] ; then
  for i in $(echo ${ADDITIONAL_PACKAGES} | tr "," "\n")
  do
    logit "Installing additional package $i"
    pip install --no-cache-dir --upgrade $i
  done
fi

DEFAULT_CONCURRENT_PLUGIN_PIP_INSTALL_CMD="pip install --no-cache-dir --upgrade concurrent-plugin"
# pass the full concurrent pip install command into bootstrap.sh instead of just the plugin version.  this will allow installation of the package from other sources such as http://xyz.com:9876/packages/concurrent-plugin/concurrent_plugin-0.3.27-py3-none-any.whl
if [ -n "$CONCURRENT_PLUGIN_PIP_INSTALL_CMD" ]; then
    echo "Executing $CONCURRENT_PLUGIN_PIP_INSTALL_CMD"
    $CONCURRENT_PLUGIN_PIP_INSTALL_CMD
else
    echo "Executing $DEFAULT_CONCURRENT_PLUGIN_PIP_INSTALL_CMD"
    $DEFAULT_CONCURRENT_PLUGIN_PIP_INSTALL_CMD
    # CONCURRENT_PLUGIN_VERSION is mandatory: without this the mlflow project container image will not be rebuilt when a new version of the plugin is published 
    CONCURRENT_PLUGIN_VERSION=`get_python_package_version concurrent-plugin`
fi    

mkdir -p /tmp/workdir/.concurrent/project_files

if [ x"$XFORMNAME" != "x" ] ; then
  logit "Running xform"
  
  if echo "$XFORMNAME" | grep ':' >& /dev/null ; then
    logit "xform is in git repo"
    get_xform
    logit "USE_SUBDIR is $USE_SUBDIR"
    /bin/ls /tmp/workdir/"$USE_SUBDIR"
  else
    logit "Error. xformname should be a git URL"
    fail_exit
  fi
else
  logit "Using project files from mlflow artifacts"
  USE_SUBDIR=".concurrent/project_files/"
  if ! download_project_files ; then
    logit "Error downloading project files"
    fail_exit
  fi
fi

#HPE_CONTAINER_REGISTRY_URI="registry-service:5000"
/bin/rm -f /root/.docker/config.json
if [ ${BACKEND_TYPE} == "gke" ] ; then
  gcloud auth activate-service-account ${GCE_ACCOUNT} --key-file=/root/.gce/key.json
  gcloud auth configure-docker
  export USE_DOCKER_BUILD=yes
elif [ ${BACKEND_TYPE} == "HPE" ]; then
  logit "HPE: Using docker registry for images being built: $HPE_CONTAINER_REGISTRY_URI"
  export USE_DOCKER_BUILD=yes
else # if BACKEND_TYPE is not specified, assume it is EKS
  export USE_DOCKER_BUILD=no
  # prepare for ECR access using aws credentials in call
  if [ "${ECR_TYPE}" == "public" ] ; then
    logit "Using public ECR repository"
    ECR_SERVICE=ecr-public
    ECR_LOGIN_ENDPOINT=public.ecr.aws
  else
    logit "Using private ECR repository"
    ECR_SERVICE=ecr
    ECR_LOGIN_ENDPOINT=${ECR_AWS_ACCOUNT_ID}.dkr.ecr.${ECR_REGION}.amazonaws.com
  fi
  P1=$(aws --profile ecr ${ECR_SERVICE} get-login-password --region ${ECR_REGION})
  /bin/mkdir -p /root/.docker
  export REGISTRY_AUTH_FILE=/root/.docker/config.json
  echo "${P1}" | buildah login --username AWS --password-stdin ${ECR_LOGIN_ENDPOINT}
  # Make docker login info available to k8s
  logit "NAMESPACE=" $NAMESPACE
  if [ "${ECR_TYPE}" == "private" ] ; then
    setup_docker_secret "/tmp/docker-secret.yaml" ${NAMESPACE}
    kubectl apply -f /tmp/docker-secret.yaml
  fi
fi

# First, MLproject environment image

if ! DOCKER_IMAGE=`docker_img_from_mlproject` ; then
  logit "Error parsing MLproject to determine docker image"
  fail_exit
fi
export DOCKER_IMAGE
logit "DOCKER_IMAGE for MLproject is ${DOCKER_IMAGE}"
logit "Add additional dependencies to Dockerfile"
(cd /tmp/workdir/${USE_SUBDIR}; echo " " >> Dockerfile)
(cd /tmp/workdir/${USE_SUBDIR}; echo "RUN if [ -f '/usr/bin/apt' ] ; then apt update ; fi" >> Dockerfile)
#(cd /tmp/workdir/${USE_SUBDIR}; echo "RUN if [ -f '/usr/bin/apt' ] ; then apt install -y libfuse-dev curl; else yum install -y fuse-libs curl; fi" >> Dockerfile)
(cd /tmp/workdir/${USE_SUBDIR}; echo "RUN pip install --ignore-installed PyYAML" >> Dockerfile)
(cd /tmp/workdir/${USE_SUBDIR}; echo "RUN pip uninstall -y concurrent-plugin" >> Dockerfile)
if [ -n "$CONCURRENT_PLUGIN_PIP_INSTALL_CMD" ]; then
(cd /tmp/workdir/${USE_SUBDIR}; echo "RUN $CONCURRENT_PLUGIN_PIP_INSTALL_CMD" >> Dockerfile)
else
(cd /tmp/workdir/${USE_SUBDIR}; echo "RUN $DEFAULT_CONCURRENT_PLUGIN_PIP_INSTALL_CMD==$CONCURRENT_PLUGIN_VERSION" >> Dockerfile)
fi
(cd /tmp/workdir/${USE_SUBDIR}; echo "RUN pip install boto3" >> Dockerfile)
(cd /tmp/workdir/${USE_SUBDIR}; echo "RUN pip install psutil" >> Dockerfile)
# install the aws_signing_helper needed for AWS IAM roles anywhere
(cd /tmp/workdir/${USE_SUBDIR}; echo "RUN curl --output /root/aws_signing_helper  https://rolesanywhere.amazonaws.com/releases/1.0.4/X86_64/Linux/aws_signing_helper && chmod a+x /root/aws_signing_helper" >> Dockerfile)
if [ x"$ADDITIONAL_PACKAGES" != "x" ] ; then
  for i in $(echo ${ADDITIONAL_PACKAGES} | tr "," "\n")
  do
    logit "Adding additional package $i to env image"
    (cd /tmp/workdir/${USE_SUBDIR}; echo "RUN pip install $i" >> Dockerfile)
  done
fi

logit "Updated Dockerfile /tmp/workdir/${USE_SUBDIR}/Dockerfile ========="
cat /tmp/workdir/${USE_SUBDIR}/Dockerfile
logit "============================"

CREATE_ENV_IMAGE="yes"
ENV_SHA=`sha256sum /tmp/workdir/${USE_SUBDIR}Dockerfile |awk -F' ' '{ print $1 }'`
USER_NAME_MUNGED=`echo ${COGNITO_USERNAME}|sed -e 's/@/-/g'`
ENV_REPO_NAME=mlflow/${USER_NAME_MUNGED}-env_images/${ENV_SHA}

if [ "${BACKEND_TYPE}" == "gke" ] ; then
  ENV_REPO_URI="gcr.io/${PROJECT_ID}/${ENV_REPO_NAME}"
  logit "Checking if env image exists in repo URI ${ENV_REPO_URI}"
  if docker pull ${ENV_REPO_URI}:latest ; then
    # tag the image pulled from the remote docker regsitry with the docker_image name specified in MLProject
    if docker tag ${ENV_REPO_URI}:latest ${DOCKER_IMAGE}:latest ; then
      logit "Found latest MLproject docker env image from existing repo $ENV_REPO_URI"
      docker images
      CREATE_ENV_IMAGE="no"
    fi
  fi
elif  [ "${BACKEND_TYPE}" == "HPE" ]; then
  ENV_REPO_URI="${HPE_CONTAINER_REGISTRY_URI}/${ENV_REPO_NAME}"
  logit "Checking if env image exists in repo URI ${ENV_REPO_URI}"  
  if docker pull ${ENV_REPO_URI}:latest ; then
    # tag the image pulled from the remote docker regsitry with the docker_image name specified in MLProject
    if docker tag ${ENV_REPO_URI}:latest ${DOCKER_IMAGE}:latest ; then
      logit "Found latest MLproject docker env image from existing repo $ENV_REPO_URI"
      docker images
      CREATE_ENV_IMAGE="no"
    fi
  fi
else # default BACKEND_TYPE is eks  
  if ENV_REPO_URI=`get_repository_uri $ECR_SERVICE $ECR_REGION $ENV_REPO_NAME` ; then
    logit "Looking for latest MLproject docker env image, using aws ecr describe-images, from existing repo $ENV_REPO_URI"    
    aws --region ${ECR_REGION} ecr describe-images --repository-name ${ENV_REPO_NAME} > /tmp/di-output.json
    if [ $? != 0 ] ; then
      logit "aws ecr describe-images failed for env image. ${ENV_REPO_NAME}. Creating env image"
      CREATE_ENV_IMAGE="yes"
    else
      NUM_IMAGES=`num_of_images /tmp/di-output.json`
      echo "Number of images in repo ${ENV_REPO_NAME}=$NUM_IMAGES"
      if [ $NUM_IMAGES -le 0 ] ; then
        logit "env image not found from existing repo $ENV_REPO_URI. Building new env image"
        CREATE_ENV_IMAGE="yes"
      else
        logit "env image found from existing repo $ENV_REPO_URI. Not building new env image"
        CREATE_ENV_IMAGE="no"
      fi
    fi
  else
    logit "Creating new MLproject docker env image repo $ENV_REPO_NAME"
    /bin/rm -f /tmp/cr-out.txt
    aws --profile ecr --region ${ECR_REGION} ${ECR_SERVICE} create-repository --repository-name ${ENV_REPO_NAME} > /tmp/cr-out.txt
    logit "Proceed if repository created"    
    if ! ENV_REPO_URI=`get_repository_uri $ECR_SERVICE $ECR_REGION $ENV_REPO_NAME` ; then
      logit "Error creating docker repository ${ENV_REPO_NAME}: "
      cat /tmp/cr-out.txt
      fail_exit
    fi
  fi
fi
export ENV_REPO_URI

export INFINSTOR_TOKEN=`grep '^Token=' /root/.concurrent/token | awk -F= '{ print $2 }' | sed -e 's/^Custom //'`
# if the env docker image wasn't found, build it now.
if [ $CREATE_ENV_IMAGE == "yes" ] ; then
  logit "Environment image creation starting for $ENV_REPO_URI"
  if [ $USE_DOCKER_BUILD == "yes" ] ; then
    logit "Building env image using docker for pushing to $ENV_REPO_URI"
    if  [ "${BACKEND_TYPE}" == "HPE" ]; then
      # tag the built docker image with the 'image' specified in MLProject
      (cd /tmp/workdir/${USE_SUBDIR}; /usr/bin/docker build -t ${DOCKER_IMAGE} --build-arg MLFLOW_TRACKING_URI=$MLFLOW_TRACKING_URI --build-arg INFINSTOR_TOKEN=$INFINSTOR_TOKEN -f Dockerfile --network host . )
    else
      # tag the built docker image with the 'image' specified in MLProject
      (cd /tmp/workdir/${USE_SUBDIR}; /usr/bin/docker build -t ${DOCKER_IMAGE} --build-arg MLFLOW_TRACKING_URI=$MLFLOW_TRACKING_URI --build-arg INFINSTOR_TOKEN=$INFINSTOR_TOKEN -f Dockerfile . )
    fi
    docker images  
    # tag the built image with the remote docker registry hostname, so that it can be pushed.
    if ! /usr/bin/docker tag ${DOCKER_IMAGE}:latest ${ENV_REPO_URI}:latest ; then
      logit "Error tagging env image before pushing"
      fail_exit
    fi
    logit "Pushing env image using docker for pushing to $ENV_REPO_URI"
    /usr/bin/docker push ${ENV_REPO_URI}:latest
  else
    logit "Building env image using buildah with repo URI $ENV_REPO_URI"
    (cd /tmp/workdir/${USE_SUBDIR}; /usr/bin/buildah bud --isolation chroot --build-arg MLFLOW_TRACKING_URI=${MLFLOW_TRACKING_URI} --build-arg INFINSTOR_TOKEN=${INFINSTOR_TOKEN} -t ${DOCKER_IMAGE} -f Dockerfile .)
    /usr/bin/buildah images  
    # tag the built image with the remote docker registry hostname, so that it can be pushed.
    if ! /usr/bin/buildah tag ${DOCKER_IMAGE}:latest ${ENV_REPO_URI}:latest ; then
      logit "Error tagging env image before pushing"
      fail_exit
    fi
    logit "Pushing env image using buildah to $ENV_REPO_URI"
    /usr/bin/buildah push ${ENV_REPO_URI}:latest
  fi
  logit "Environment image creation complete for $ENV_REPO_URI"
else
  logit "Not creating env image since it exists"
fi

MLFLOW_PROJECT_DIR=/tmp/workdir/${USE_SUBDIR}

# Note: we are uploading the modified Dockerfile here.  If this script runs again, with the same artificat location (with this same mlflow run id), it will force a rebuild of the MLproject environment image due to this modified docker file
log_mlflow_artifact ${PARENT_RUN_ID} ${MLFLOW_PROJECT_DIR} ".concurrent/${ORIGINAL_NODE_ID}/project_files"

# Next, repository for full image, i.e. MLproject env base plus project code/data
REPO_NAME_MUNGED=`find ${MLFLOW_PROJECT_DIR} -type f|sort|xargs sha256sum|awk -F ' ' '{ print $1 }'|sha256sum|awk -F ' ' '{ print $1 }'`
REPOSITORY_FULL_NAME=mlflow/${USER_NAME_MUNGED}/${REPO_NAME_MUNGED}
logit "Name of docker repository for full image is $REPOSITORY_FULL_NAME"
if [ ${BACKEND_TYPE} == "gke" ] ; then
  REPOSITORY_URI="gcr.io/${PROJECT_ID}/${REPOSITORY_FULL_NAME}"
elif [ ${BACKEND_TYPE} == "HPE" ] ; then
  REPOSITORY_URI="${HPE_CONTAINER_REGISTRY_URI}/${REPOSITORY_FULL_NAME}"
else # default backend is eks  
  if REPOSITORY_URI=`get_repository_uri $ECR_SERVICE $ECR_REGION $REPOSITORY_FULL_NAME` ; then
    logit "Using existing Docker repo $REPOSITORY_FULL_NAME"
  else
    logit "Docker repo ${REPOSITORY_FULL_NAME} does not exist. Creating"
    /bin/rm -f /tmp/cr-out.txt
    aws --profile ecr --region ${ECR_REGION} ${ECR_SERVICE} create-repository --repository-name ${REPOSITORY_FULL_NAME} > /tmp/cr-out.txt
    logit "Proceed if repository created"    
    if ! REPOSITORY_URI=`get_repository_uri $ECR_SERVICE $ECR_REGION $REPOSITORY_FULL_NAME` ; then
      logit "Error creating docker repository:"
      cat /tmp/cr-out.txt
      fail_exit
    fi
    REPOSITORY_URI=`get_repository_uri $ECR_SERVICE $ECR_REGION $REPOSITORY_FULL_NAME`
  fi
  export ECR_REGION
fi
export REPOSITORY_URI

export MLFLOW_PROJECT_DIR
export BOOTSTRAP_LOG_FILE
export PERIODIC_RUN_FREQUENCY
export PERIODIC_RUN_START_TIME
export PERIODIC_RUN_END_TIME
# previous_run_status == first_run | running | failed | success
export PERIODIC_RUN_LAST_STATUS
export ORIGINAL_NODE_ID
export USE_FARGATE
export CONCURRENT_DISABLE_NODE_PINNING

logit "MLFLOW_CONCURRENT_URI is " $MLFLOW_CONCURRENT_URI
logit "MLFLOW_TRACKING_URI is " $MLFLOW_TRACKING_URI
logit "MLFLOW_RUN_ID is " $MLFLOW_RUN_ID
logit "ENV_REPO_URI is " $ENV_REPO_URI
logit "REPOSITORY_URI is " $REPOSITORY_URI
logit "DAGID is " $DAGID
logit "DAG_EXECUTION_ID is " $DAG_EXECUTION_ID
logit "PERIODIC_RUN_NAME is " $PERIODIC_RUN_NAME
logit "PARENT_RUN_ID is " $PARENT_RUN_ID
logit "REPOSITORY_URI is " $REPOSITORY_URI
logit "MLFLOW_PROJECT_DIR is " $MLFLOW_PROJECT_DIR
logit "PERIODIC_RUN_FREQUENCY is " $PERIODIC_RUN_FREQUENCY
logit "PERIODIC_RUN_START_TIME is " $PERIODIC_RUN_START_TIME
logit "PERIODIC_RUN_END_TIME is " $PERIODIC_RUN_END_TIME
logit "ORIGINAL_NODE_ID is " $ORIGINAL_NODE_ID
logit "USE_FARGATE is " $USE_FARGATE
logit "CONCURRENT_DISABLE_NODE_PINNING is " $CONCURRENT_DISABLE_NODE_PINNING
logit "Full environment: "
typeset -p

# ARG is a command to be read and executed when the shell receives the signal(s) SIGNAL_SPEC.  If ARG is absent (and a single SIGNAL_SPEC
# is supplied) or `-', each specified signal is reset to its original value.
# 
# task_launcher has its own 'trap' to hook into 'EXIT' and upload logs.  So disable this script's exit hook
trap - EXIT

##Launch task containers
TASK_LAUNCHER_CMD="python3 /usr/local/bin/task_launcher.py"

logit "Starting task launcher: " $TASK_LAUNCHER_CMD
if ! $TASK_LAUNCHER_CMD ; then
    logit "Task Launcher Failed"
    exit 255
else
    logit "Task Launcher Succeeded"
    exit 0
fi

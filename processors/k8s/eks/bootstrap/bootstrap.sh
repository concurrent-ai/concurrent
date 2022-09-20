#!/bin/bash

export DOCKER_HOST="tcp://docker-dind:2375"

if [ x"$DOCKER_HOST" == "x" ] ; then
    ##
    ## Begin Code lifted from stackexchange that provides docker-in-docker functionality
    ##
    # Ensure that all nodes in /dev/mapper correspond to mapped devices currently loaded by the device-mapper kernel driver
    dmsetup mknodes

    # First, make sure that cgroups are mounted correctly.
    CGROUP=/sys/fs/cgroup
    : {LOG:=stdio}

    [ -d $CGROUP ] ||
        mkdir $CGROUP

    mountpoint -q $CGROUP ||
        mount -n -t tmpfs -o uid=0,gid=0,mode=0755 cgroup $CGROUP || {
            echo "Could not make a tmpfs mount. Did you use --privileged?"
            exit 1
        }

    if [ -d /sys/kernel/security ] && ! mountpoint -q /sys/kernel/security
    then
        mount -t securityfs none /sys/kernel/security || {
            echo "Could not mount /sys/kernel/security."
            echo "AppArmor detection and --privileged mode might break."
        }
    fi

    # Mount the cgroup hierarchies exactly as they are in the parent system.
    for SUBSYS in $(cut -d: -f2 /proc/1/cgroup)
    do
        [ -d $CGROUP/$SUBSYS ] || mkdir $CGROUP/$SUBSYS
        mountpoint -q $CGROUP/$SUBSYS ||
                mount -n -t cgroup -o $SUBSYS cgroup $CGROUP/$SUBSYS

        # The two following sections address a bug which manifests itself
        # by a cryptic "lxc-start: no ns_cgroup option specified" when
        # trying to start containers withina container.
        # The bug seems to appear when the cgroup hierarchies are not
        # mounted on the exact same directories in the host, and in the
        # container.

        # Named, control-less cgroups are mounted with "-o name=foo"
        # (and appear as such under /proc/<pid>/cgroup) but are usually
        # mounted on a directory named "foo" (without the "name=" prefix).
        # Systemd and OpenRC (and possibly others) both create such a
        # cgroup. To avoid the aforementioned bug, we symlink "foo" to
        # "name=foo". This shouldn't have any adverse effect.
        echo $SUBSYS | grep -q ^name= && {
                NAME=$(echo $SUBSYS | sed s/^name=//)
                ln -s $SUBSYS $CGROUP/$NAME
        }

        # Likewise, on at least one system, it has been reported that
        # systemd would mount the CPU and CPU accounting controllers
        # (respectively "cpu" and "cpuacct") with "-o cpuacct,cpu"
        # but on a directory called "cpu,cpuacct" (note the inversion
        # in the order of the groups). This tries to work around it.
        [ $SUBSYS = cpuacct,cpu ] && ln -s $SUBSYS $CGROUP/cpu,cpuacct
    done

    # Note: as I write those lines, the LXC userland tools cannot setup
    # a "sub-container" properly if the "devices" cgroup is not in its
    # own hierarchy. Let's detect this and issue a warning.
    grep -q :devices: /proc/1/cgroup ||
        echo "WARNING: the 'devices' cgroup should be in its own hierarchy."
    grep -qw devices /proc/1/cgroup ||
        echo "WARNING: it looks like the 'devices' cgroup is not mounted."

    # Now, close extraneous file descriptors.
    pushd /proc/self/fd >/dev/null
    for FD in *
    do
        case "$FD" in
        # Keep stdin/stdout/stderr
        [012])
            ;;
        # Nuke everything else
        *)
            eval exec "$FD>&-"
            ;;
        esac
    done
    popd >/dev/null


    # If a pidfile is still around (for example after a container restart),
    # delete it so that docker can start.
    rm -rf /var/run/docker.pid

    if [ "$LOG" == "file" ]
    then
      dockerd $DOCKER_DAEMON_ARGS &>/var/log/docker.log &
    else
      dockerd $DOCKER_DAEMON_ARGS &
    fi
    (( timeout = 60 + SECONDS ))
    until docker info >/dev/null 2>&1
    do
      if (( SECONDS >= timeout )); then
        echo 'Timed out trying to connect to internal docker host.' >&2
        break
      fi
      sleep 1
    done
    ##
    ## End Code lifted from stackexchange that provides docker-in-docker functionality
    ##
fi

echo "Bootstrap Container Pip Packages="
pip list
echo "End bootstrap Container Pip Packages="

##
## Begin mlflow-parallels code
##

BOOTSTRAP_LOG_FILE="/tmp/bootstrap-log-${ORIGINAL_NODE_ID}.txt"

if [ x"${PARENT_RUN_ID}" == "x" ] ; then
    PARENT_RUN_ID=$MLFLOW_RUN_ID
    export PARENT_RUN_ID
fi

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

generate_kubernetes_job_template() {
  /bin/rm -f $1
  echo "apiVersion: batch/v1" > $1
  echo "kind: Job" >> $1
  echo "metadata:" >> $1
  echo "  name: \"{replaced with MLflow Project name}\"" >> $1
  echo "  namespace: $2" >> $1
  echo "spec:" >> $1
  echo "  ttlSecondsAfterFinished: 600" >> $1
  echo "  backoffLimit: 0" >> $1
  echo "  template:" >> $1
  echo "    spec:" >> $1
  echo "      containers:" >> $1
  echo "      - name: \"{replaced with MLflow Project name}\"" >> $1
  echo "        image: \"{replaced with URI of Docker image created during Project execution}\"" >> $1
  echo "        command: [\"{replaced with MLflow Project entry point command}\"]" >> $1
  echo "        imagePullPolicy: IfNotPresent" >> $1
  echo "        securityContext:" >> $1
  echo "          privileged: true" >> $1
  echo "          capabilities:" >> $1
  echo "            add:" >> $1
  echo "              - SYS_ADMIN" >> $1
  echo "        resources:" >> $1
  echo "          limits:" >> $1
  if [ x"${RESOURCES_LIMITS_CPU}" != "x" ] ; then
    echo "            cpu: \"${RESOURCES_LIMITS_CPU}\"" >> $1
  fi
  if [ x"${RESOURCES_LIMITS_MEMORY}" != "x" ] ; then
    echo "            memory: \"${RESOURCES_LIMITS_MEMORY}\"" >> $1
  fi
  if [ x"${RESOURCES_LIMITS_HUGEPAGES}" != "x" ] ; then
    HP_SIZE=`echo ${RESOURCES_LIMITS_HUGEPAGES} | awk -F/ '{ print $1 }'`
    HP_VALUE=`echo ${RESOURCES_LIMITS_HUGEPAGES} | awk -F/ '{ print $2 }'`
    echo "            hugepages-${HP_SIZE}: \"${HP_VALUE}\"" >> $1
  fi
  if [ x"${RESOURCES_LIMITS_NVIDIA_COM_GPU}" != "x" ] ; then
    echo "            nvidia.com/gpu: ${RESOURCES_LIMITS_NVIDIA_COM_GPU}" >> $1
  fi
  echo "          requests:" >> $1
  if [ x"${RESOURCES_REQUESTS_CPU}" != "x" ] ; then
    echo "            cpu: \"${RESOURCES_REQUESTS_CPU}\"" >> $1
  fi
  if [ x"${RESOURCES_REQUESTS_MEMORY}" != "x" ] ; then
    echo "            memory: \"${RESOURCES_REQUESTS_MEMORY}\"" >> $1
  fi
  if [ x"${RESOURCES_REQUESTS_HUGEPAGES}" != "x" ] ; then
    HP_SIZE=`echo ${RESOURCES_REQUESTS_HUGEPAGES} | awk -F/ '{ print $1 }'`
    HP_VALUE=`echo ${RESOURCES_REQUESTS_HUGEPAGES} | awk -F/ '{ print $2 }'`
    echo "            hugepages-${HP_SIZE}: \"${HP_VALUE}\"" >> $1
  fi
  if [ x"${RESOURCES_REQUESTS_NVIDIA_COM_GPU}" != "x" ] ; then
    echo "            nvidia.com/gpu: ${RESOURCES_REQUESTS_NVIDIA_COM_GPU}" >> $1
  fi
  if [ ${ECR_TYPE} == "private" ] ; then
    echo "      imagePullSecrets:" >> $1
    echo "      - name: ecr-private-key" >> $1
  fi
  echo "      restartPolicy: Never" >> $1
}

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


get_repository_uri() {
  /bin/rm -f /tmp/reps
  aws --profile ecr --region $2 $1 describe-repositories > /tmp/reps
  if [ $? != 0 ] ; then
    echo "Error listing repositories $1"
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

get_mlflow_param() {
  export MLFLOW_RUN_ID
  export PNAME=$1
  python3 << ENDPY
import sys
import os
import mlflow
from mlflow.tracking import MlflowClient
${ADDITIONAL_IMPORTS}

client = MlflowClient()
run = client.get_run(os.getenv('MLFLOW_RUN_ID'))
param = os.getenv('PNAME')
if param in run.data.params:
  print(run.data.params[param])
  sys.exit(0)
else:
  sys.exit(255)
ENDPY
}

download_project_files() {
  export MLFLOW_RUN_ID
  python3 << ENDPY
import sys
import os
import mlflow
from mlflow.tracking import MlflowClient

run_id = os.getenv('MLFLOW_RUN_ID')
spath = '.mlflow-parallels/project_files'

client = MlflowClient()
client.download_artifacts(run_id, spath, '/tmp/workdir')
sys.exit(0)
ENDPY
}

get_xform() {
  (cd /tmp/workdir; git clone "$XFORMNAME" >& /tmp/git.log.$$)
  if [ $? == 0 ] ; then
    CINTO=`grep 'Cloning into' /tmp/git.log.$$`
    if [ $? == 0 ] ; then
      export USE_SUBDIR=`echo $CINTO | sed -e "s/^Cloning into '//"|sed -e "s/'.*$//"`/
      if [ x"$XFORM_PATH" != "x" ] ; then
          export USE_SUBDIR=${USE_SUBDIR}${XFORM_PATH}/
      fi
      echo "USE_SUBDIR=$USE_SUBDIR"
      (cd /tmp/workdir/$USE_SUBDIR; /bin/rm -rf .git)
    else
      echo "Error cloning git tree $XFORMNAME"
      cat /tmp/git.log.$$
      fail_exit
    fi
  else
    echo "Error checking out git tree $XFORMNAME"
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

fail_exit() {
  update_mlflow_run ${PARENT_RUN_ID} "FAILED" 
  kubectl logs "${MY_POD_NAME}" > ${BOOTSTRAP_LOG_FILE}
  log_mlflow_artifact ${PARENT_RUN_ID} ${BOOTSTRAP_LOG_FILE} '.mlflow-parallels/logs'
  exit 255
}

if [ x"$ADDITIONAL_PACKAGES" != "x" ] ; then
  for i in $(echo ${ADDITIONAL_PACKAGES} | tr "," "\n")
  do
    echo "Installing additional package $i"
    pip install --no-cache-dir --upgrade $i
  done
fi

mkdir -p /tmp/workdir/.mlflow-parallels/project_files

if [ x"$XFORMNAME" != "x" ] ; then
  echo "Running xform"
  echo "$XFORMNAME" | grep ':' >& /dev/null
  if [ $? == 0 ] ; then
    echo "xform is in git repo"
    get_xform
    echo "USE_SUBDIR is $USE_SUBDIR"
    /bin/ls /tmp/workdir/"$USE_SUBDIR"
  else
    echo "Error. xformname should be a git URL"
    fail_exit
  fi
else
  echo "Using project files from mlflow artifacts"
  USE_SUBDIR=".mlflow-parallels/project_files/"
  download_project_files
  if [ $? != 0 ] ; then
    echo "Error downloading project files"
    fail_exit
  fi
fi

echo "MLFLOW_TRACKING_URI = " $MLFLOW_TRACKING_URI
# if tracking uri is not set, then error
[ -z "$MLFLOW_TRACKING_URI" ] && echo "Error: MLFLOW_TRACKING_URI is not set.  " && fail_exit

/bin/rm -f /root/.docker/config.json
if [ ${BACKEND_TYPE} == "gke" ] ; then
  gcloud auth activate-service-account ${GCE_ACCOUNT} --key-file=/root/.gce/key.json
  gcloud auth configure-docker
else # if BACKEND_TYPE is not specified, assume it is EKS
  # prepare for ECR access using aws credentials in call
  if [ ${ECR_TYPE} == "public" ] ; then
    echo "Using public ECR repository"
    ECR_SERVICE=ecr-public
    ECR_LOGIN_ENDPOINT=public.ecr.aws
  else
    echo "Using private ECR repository"
    ECR_SERVICE=ecr
    ECR_LOGIN_ENDPOINT=${ECR_AWS_ACCOUNT_ID}.dkr.ecr.${ECR_REGION}.amazonaws.com
  fi
  P1=$(aws --profile ecr ${ECR_SERVICE} get-login-password --region ${ECR_REGION})
  echo "${P1}" | docker login --username AWS --password-stdin ${ECR_LOGIN_ENDPOINT}

  # Make docker login info available to k8s
  echo "NAMESPACE=" $NAMESPACE
  if [ ${ECR_TYPE} == "private" ] ; then
    setup_docker_secret "/tmp/docker-secret.yaml" ${NAMESPACE}
    kubectl apply -f /tmp/docker-secret.yaml
  fi
fi

# First, MLproject environment image
DOCKER_IMAGE=`docker_img_from_mlproject`
if [ $? != 0 ] ; then
  echo "Error parsing MLproject to determine docker image"
  fail_exit
fi
echo "DOCKER_IMAGE is ${DOCKER_IMAGE}"
CREATE_ENV_IMAGE="yes"
ENV_SHA=`sha256sum /tmp/workdir/${USE_SUBDIR}Dockerfile |awk -F' ' '{ print $1 }'`
ENV_REPO_NAME=mlflow/shared_env_images/${ENV_SHA}

if [ ${BACKEND_TYPE} == "gke" ] ; then
  ENV_REPO_URI="gcr.io/${PROJECT_ID}/${ENV_REPO_NAME}"
  echo "Checking if env image exists in repo URI ${ENV_REPO_URI}"
  docker pull ${ENV_REPO_URI}:latest
  if [ $? == 0 ] ; then
    docker tag ${ENV_REPO_URI}:latest ${DOCKER_IMAGE}:latest
    if [ $? == 0 ] ; then
      echo "Found latest MLproject docker env image from existing repo $ENV_REPO_URI"
      docker images
      CREATE_ENV_IMAGE="no"
    fi
  fi
else # default BACKEND_TYPE is eks
  ENV_REPO_URI=`get_repository_uri $ECR_SERVICE $ECR_REGION $ENV_REPO_NAME`
  if [ $? == 0 ] ; then
    echo "Looking for latest MLproject docker env image from existing repo $ENV_REPO_URI"
    docker pull ${ENV_REPO_URI}:latest
    if [ $? == 0 ] ; then
      docker tag ${ENV_REPO_URI}:latest ${DOCKER_IMAGE}:latest
      if [ $? == 0 ] ; then
        echo "Found latest MLproject docker env image from existing repo $ENV_REPO_URI"
        docker images
        CREATE_ENV_IMAGE="no"
      fi
    fi
  else
    echo "Creating new MLproject docker env image repo $ENV_REPO_NAME"
    /bin/rm -f /tmp/cr-out.txt
    aws --profile ecr --region ${ECR_REGION} ${ECR_SERVICE} create-repository --repository-name ${ENV_REPO_NAME} > /tmp/cr-out.txt
    echo "Proceed if repository created"
    ENV_REPO_URI=`get_repository_uri $ECR_SERVICE $ECR_REGION $ENV_REPO_NAME`
    if [ $? != 0 ] ; then
      echo "Error creating docker repository ${ENV_REPO_NAME}: "
      cat /tmp/cr-out.txt
      fail_exit
    fi
  fi
fi

if [ $CREATE_ENV_IMAGE == "yes" ] ; then
  echo "Building env image for pushing to $ENV_REPO_URI"
  (cd /tmp/workdir/${USE_SUBDIR}; echo " " >> Dockerfile)
  (cd /tmp/workdir/${USE_SUBDIR}; echo "RUN apt update" >> Dockerfile)
  (cd /tmp/workdir/${USE_SUBDIR}; echo "RUN apt install -y libfuse-dev" >> Dockerfile)
  (cd /tmp/workdir/${USE_SUBDIR}; echo "RUN pip install --ignore-installed PyYAML" >> Dockerfile)
  (cd /tmp/workdir/${USE_SUBDIR}; echo "RUN pip install parallels_plugin" >> Dockerfile)
  (cd /tmp/workdir/${USE_SUBDIR}; echo "RUN pip install boto3" >> Dockerfile)
  if [ x"$ADDITIONAL_PACKAGES" != "x" ] ; then
    for i in $(echo ${ADDITIONAL_PACKAGES} | tr "," "\n")
    do
      echo "Adding additional package $i to env image"
      (cd /tmp/workdir/${USE_SUBDIR}; echo "RUN pip install $i" >> Dockerfile)
    done
  fi
  (cd /tmp/workdir/${USE_SUBDIR}; /usr/bin/docker build -t ${DOCKER_IMAGE} -f Dockerfile .)
  docker images
  /usr/bin/docker tag ${DOCKER_IMAGE}:latest ${ENV_REPO_URI}:latest
  if [ $? != 0 ] ; then
    echo "Error tagging env image before pushing"
    fail_exit
  fi
  /usr/bin/docker push ${ENV_REPO_URI}:latest
fi

MLFLOW_PROJECT_DIR=/tmp/workdir/${USE_SUBDIR}

log_mlflow_artifact ${PARENT_RUN_ID} ${MLFLOW_PROJECT_DIR} '.mlflow-parallels/project_files'

# Next, repository for full image, i.e. MLproject env base plus project code/data
USER_NAME_MUNGED=`echo ${COGNITO_USERNAME}|sed -e 's/@/-/g'`
REPO_NAME_MUNGED=`find ${MLFLOW_PROJECT_DIR} -type f|sort|xargs sha256sum|awk -F ' ' '{ print $1 }'|sha256sum|awk -F ' ' '{ print $1 }'`
REPOSITORY_FULL_NAME=mlflow/${USER_NAME_MUNGED}/${REPO_NAME_MUNGED}
echo "Name of docker repository for full image is $REPOSITORY_FULL_NAME"
if [ ${BACKEND_TYPE} == "gke" ] ; then
  REPOSITORY_URI="gcr.io/${PROJECT_ID}/${REPOSITORY_FULL_NAME}"
else # default backend is eks
  REPOSITORY_URI=`get_repository_uri $ECR_SERVICE $ECR_REGION $REPOSITORY_FULL_NAME`
  if [ $? == 0 ] ; then
    echo "Using existing Docker repo $REPOSITORY_FULL_NAME"
  else
    echo "Docker repo ${REPOSITORY_FULL_NAME} does not exist. Creating"
    /bin/rm -f /tmp/cr-out.txt
    aws --profile ecr --region ${ECR_REGION} ${ECR_SERVICE} create-repository --repository-name ${REPOSITORY_FULL_NAME} > /tmp/cr-out.txt
    echo "Proceed if repository created"
    REPOSITORY_URI=`get_repository_uri $ECR_SERVICE $ECR_REGION $REPOSITORY_FULL_NAME`
    if [ $? != 0 ] ; then
      echo "Error creating docker repository:"
      cat /tmp/cr-out.txt
      fail_exit
    fi
    REPOSITORY_URI=`get_repository_uri $ECR_SERVICE $ECR_REGION $REPOSITORY_FULL_NAME`
  fi
fi
export REPOSITORY_URI

export MLFLOW_PROJECT_DIR
export BOOTSTRAP_LOG_FILE

echo "MLFLOW_PARALLELS_URI is " $MLFLOW_PARALLELS_URI
echo "MLFLOW_TRACKING_URI is " $MLFLOW_TRACKING_URI
echo "MLFLOW_RUN_ID is " $MLFLOW_RUN_ID
echo "ENV_REPO_URI is " $ENV_REPO_URI
echo "REPOSITORY_URI is " $REPOSITORY_URI
echo "DAGID is " $DAGID
echo "DAG_EXECUTION_ID is " $DAG_EXECUTION_ID
echo "PERIODIC_RUN_NAME is " $PERIODIC_RUN_NAME
echo "PARENT_RUN_ID is " $PARENT_RUN_ID
echo "REPOSITORY_URI is " $REPOSITORY_URI
echo "MLFLOW_PROJECT_DIR is " $MLFLOW_PROJECT_DIR

##Launch task containers
TASK_LAUNCHER_CMD="python3 /usr/local/bin/task_launcher.py"

echo "Starting task launcher: " $TASK_LAUNCHER_CMD
$TASK_LAUNCHER_CMD
if [ $? != 0 ] ; then
    echo "Task Launcher Failed"
    exit 255
else
    echo "Task Launcher Succeeded"
    exit 0
fi

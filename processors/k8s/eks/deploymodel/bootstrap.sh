#!/bin/bash

export DOCKER_HOST="tcp://docker-dind:2375"

logit() {
    echo "`date` - $$ - INFO - deploymodel.sh - ${*}" # >> ${LOG_FILE}
    # [ -n "$LOG_FILE" ] && echo "`date` - $$ - INFO - deploymodel.sh - ${*}"  >> "${LOG_FILE}"
}

logit "deploymodel Container Pip Packages="
pip list
logit "End deploymodel Container Pip Packages="

##
## Begin concurrent code
##

DEPLOYMODEL_LOG_FILE="/tmp/deploymodel-log.txt"

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

upon_exit() {
  exit_code=$?
  logit "script exited with code $exit_code. logging bootstrap output to mlflow"
  if [ $exit_code -eq 0 ] ; then
    update_mlflow_run ${MLFLOW_RUN_ID} "FINISHED" 
  else
    update_mlflow_run ${MLFLOW_RUN_ID} "FAILED" 
  fi
  kubectl logs "${MY_POD_NAME}" > ${DEPLOYMODEL_LOG_FILE}
  log_mlflow_artifact ${MLFLOW_RUN_ID} ${DEPLOYMODEL_LOG_FILE} '.concurrent/logs'
  exit $exit_code
}

# trap: trap [-lp] [[arg] signal_spec ...]
#
# If a SIGNAL_SPEC is EXIT (0) ARG is executed on exit from the shell.  
# If a SIGNAL_SPEC is DEBUG, ARG is executed before every simple command.  
# If a SIGNAL_SPEC is RETURN, ARG is executed each time a shell function or a  script run by the . or source builtins finishes executing.  
# A SIGNAL_SPEC of ERR means to execute ARG each time a command's failure would cause the shell to exit when the -e option is enabled.
trap upon_exit EXIT

logit "Environment: "
typeset -p

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
            logit "Could not make a tmpfs mount. Did you use --privileged?"
            exit 1
        }

    if [ -d /sys/kernel/security ] && ! mountpoint -q /sys/kernel/security
    then
        mount -t securityfs none /sys/kernel/security || {
            logit "Could not mount /sys/kernel/security."
            logit "AppArmor detection and --privileged mode might break."
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
        logit "WARNING: the 'devices' cgroup should be in its own hierarchy."
    grep -qw devices /proc/1/cgroup ||
        logit "WARNING: it looks like the 'devices' cgroup is not mounted."

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
        logit 'Timed out trying to connect to internal docker host.' >&2
        break
      fi
      sleep 1
    done
    ##
    ## End Code lifted from stackexchange that provides docker-in-docker functionality
    ##
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
spath = '.concurrent/project_files'

client = MlflowClient()
client.download_artifacts(run_id, spath, '/tmp/workdir')
sys.exit(0)
ENDPY
}

get_xform() {
  
  if (cd /tmp/workdir; git clone "$XFORMNAME" >& /tmp/git.log.$$) ; then
    # CINTO is similar to Cloning into 'xxxxxxx'  abcdef
    if CINTO=`grep 'Cloning into' /tmp/git.log.$$` ; then
      # extract the subdirectory into which the clone was done
      export USE_SUBDIR=`echo $CINTO | sed -e "s/^Cloning into '//"|sed -e "s/'.*$//"`/
      if [ x"$XFORM_PATH" != "x" ] ; then
          export USE_SUBDIR=${USE_SUBDIR}${XFORM_PATH}/
      fi
      logit "USE_SUBDIR=$USE_SUBDIR"
      (cd /tmp/workdir/$USE_SUBDIR; /bin/rm -rf .git)
    else
      logit "Error cloning git tree $XFORMNAME"
      cat /tmp/git.log.$$
      exit 255
    fi
  else
    logit "Error checking out git tree $XFORMNAME"
    exit 255
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

download_model() {
  export MODEL_URI=$1
  export DEST_DIR=$2
  python3 << ENDPY
import sys
import os
import mlflow

try:
    mlflow.artifacts.download_artifacts(os.environ['MODEL_URI'], None, None, os.environ['DEST_DIR'], None)
except:
    import traceback
    traceback.print_exc()
    sys.exit(255)
sys.exit(0)
ENDPY
}

logit "MLFLOW_TRACKING_URI = " $MLFLOW_TRACKING_URI
# if tracking uri is not set, then error
[ -z "$MLFLOW_TRACKING_URI" ] && logit "Error: MLFLOW_TRACKING_URI is not set.  " && exit 255

TASKINFO=`cat /root/.taskinfo/taskinfo`
logit "TASKINFO="$TASKINFO

logit "MODEL_URI="$MODEL_URI
IMG_HASH=`echo $MODEL_URI | sha256sum | awk -F' ' '{ print $1 }'`
IMG_NAME="mlflow-deploy-${IMG_HASH}"
logit "IMG_NAME="$IMG_NAME

#HPE_CONTAINER_REGISTRY_URI="registry-service:5000"
/bin/rm -f /root/.docker/config.json
if [ ${BACKEND_TYPE} == "gke" ] ; then
  gcloud auth activate-service-account ${GCE_ACCOUNT} --key-file=/root/.gce/key.json
  gcloud auth configure-docker
elif [ ${BACKEND_TYPE} == "HPE" ]; then
  logit "HPE: Using docker registry for images being built: $HPE_CONTAINER_REGISTRY_URI"
else # if BACKEND_TYPE is not specified, assume it is EKS
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
  echo "${P1}" | docker login --username AWS --password-stdin ${ECR_LOGIN_ENDPOINT}

  # Make docker login info available to k8s
  logit "NAMESPACE=" $NAMESPACE
  if [ "${ECR_TYPE}" == "private" ] ; then
    setup_docker_secret "/tmp/docker-secret.yaml" ${NAMESPACE}
    kubectl apply -f /tmp/docker-secret.yaml
  fi
fi

CREATE_IMAGE="yes"
REPO_NAME=mlflow/deployment_images/${IMG_NAME}

if [ "${BACKEND_TYPE}" == "gke" ] ; then
  REPO_URI="gcr.io/${PROJECT_ID}/${REPO_NAME}"
  logit "Checking if env image exists in repo URI ${REPO_URI}"
  docker manifest inspect ${REPO_URI}:latest
  if [ $? == 0 ] ; then
    logit "Found existing image ${REPO_URI}. Not creating a new image"
    CREATE_IMAGE="no"
  fi
elif  [ "${BACKEND_TYPE}" == "HPE" ]; then
  REPO_URI="${HPE_CONTAINER_REGISTRY_URI}/${REPO_NAME}"
  logit "Checking if env image exists in repo URI ${REPO_URI}"  
  docker manifest inspect ${REPO_URI}:latest
  if [ $? == 0 ] ; then
    logit "Found existing image ${REPO_URI}. Not creating a new image"
    CREATE_IMAGE="no"
  fi
else # default BACKEND_TYPE is eks  
  if REPO_URI=`get_repository_uri $ECR_SERVICE $ECR_REGION $REPO_NAME` ; then
    logit "Looking for latest MLproject docker env image from existing repo $REPO_URI"    
    docker manifest inspect ${REPO_URI}:latest
    if [ $? == 0 ] ; then
      logit "Found existing image ${REPO_URI}. Not creating a new image"
      CREATE_IMAGE="no"
    fi
  else
    logit "Creating new MLproject docker env image repo $REPO_NAME"
    /bin/rm -f /tmp/cr-out.txt
    aws --profile ecr --region ${ECR_REGION} ${ECR_SERVICE} create-repository --repository-name ${REPO_NAME} > /tmp/cr-out.txt
    logit "Proceed if repository created"    
    if ! REPO_URI=`get_repository_uri $ECR_SERVICE $ECR_REGION $REPO_NAME` ; then
      logit "Error creating docker repository ${REPO_NAME}: "
      cat /tmp/cr-out.txt
      exit 255
    fi
  fi
fi

# if the env docker image wasn't found, build it now.
if [ $CREATE_IMAGE == "no" ] ; then
  logit "Building env image for pushing to $REPO_URI"
  mkdir -p /root/workdir/container/model
  download_model $MODEL_URI /root/workdir/container/model
  if [ $? != 0 ] ; then
      logit "Error downloading model"
      exit 255
  fi
  echo "Model download complete. Model dir listing.."
  /bin/ls -lR /root/workdir/container/model
  echo "Model download complete. End model dir listing"

  echo "FROM condaforge/miniforge3" > /root/workdir/container/Dockerfile
  echo "RUN /opt/conda/bin/conda update -n base -c conda-forge conda" >> /root/workdir/container/Dockerfile
  echo "RUN /opt/conda/bin/conda init bash" >> /root/workdir/container/Dockerfile
  echo "WORKDIR /root" >> /root/workdir/container/Dockerfile
  echo "COPY . ./" >> /root/workdir/container/Dockerfile
  echo "RUN /opt/conda/bin/conda env create -f /root/model/conda.yaml" >> /root/workdir/container/Dockerfile
  echo "RUN echo '#!/bin/bash' > /root/start.sh" >> /root/workdir/container/Dockerfile
  echo "RUN echo 'set -x' > /root/start.sh" >> /root/workdir/container/Dockerfile
  echo "RUN echo 'cat /root/.bashrc' >> /root/start.sh" >> /root/workdir/container/Dockerfile
  echo "RUN echo '. /opt/conda/etc/profile.d/conda.sh' >> /root/start.sh" >> /root/workdir/container/Dockerfile
  echo "RUN echo 'conda init bash' >> /root/start.sh" >> /root/workdir/container/Dockerfile
  echo "RUN echo 'bash /root/start1.sh' >> /root/start.sh" >> /root/workdir/container/Dockerfile

  echo "RUN echo '#!/bin/bash' > /root/start1.sh" >> /root/workdir/container/Dockerfile
  echo "RUN echo 'set -x' > /root/start1.sh" >> /root/workdir/container/Dockerfile
  echo "RUN echo '. /opt/conda/etc/profile.d/conda.sh' >> /root/start1.sh" >> /root/workdir/container/Dockerfile
  echo "RUN echo 'conda activate mlflow-env' >> /root/start1.sh" >> /root/workdir/container/Dockerfile
  echo "RUN echo 'mlflow models serve -m /root/model' >> /root/start1.sh" >> /root/workdir/container/Dockerfile

  echo "RUN chmod 755 /root/start.sh" >> /root/workdir/container/Dockerfile
  echo "RUN chmod 755 /root/start1.sh" >> /root/workdir/container/Dockerfile
  echo "CMD /usr/bin/bash /root/start.sh" >> /root/workdir/container/Dockerfile
  if  [ "${BACKEND_TYPE}" == "HPE" ]; then
    # tag the built docker image with the 'image' specified in MLProject
    (cd /root/workdir/container; docker build -t ${IMG_NAME} --network host .)
  else
    # tag the built docker image with the 'image' specified in MLProject
    (cd /root/workdir/container; docker build -t ${IMG_NAME} .)
  fi
  docker images  
  # tag the built image with the remote docker registry hostname, so that it can be pushed.
  if ! /usr/bin/docker tag ${IMG_NAME}:latest ${REPO_URI}:latest ; then
    logit "Error tagging env image before pushing"
    exit 255
  fi
  /usr/bin/docker push ${REPO_URI}:latest
fi

if [ x${RESOURCES_LIMITS_CPU} == "x" ] ; then
  RESOURCES_LIMITS_CPU=$RESOURCES_REQUESTS_CPU
fi
if [ x${RESOURCES_LIMITS_MEMORY} == "x" ] ; then
  RESOURCES_LIMITS_MEMORY=$RESOURCES_REQUESTS_MEMORY
fi
if [ x${RESOURCES_LIMITS_NVIDIA_COM_GPU} == "x" ] ; then
  RESOURCES_LIMITS_NVIDIA_COM_GPU=$RESOURCES_REQUESTS_NVIDIA_COM_GPU
fi

cat > /tmp/deployment.$$.yaml << EOYAML
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mlflow-deploy-deployment-${MLFLOW_RUN_ID}
  labels:
    app: mlflow-deploy
spec:
  replicas: 1
  selector:
    matchLabels:
      app: mlflow-deploy
  template:
    metadata:
      labels:
        app: mlflow-deploy
    spec:
      containers:
      - name: mlflow-deploy
        image: ${REPO_URI}:latest
        resources:
          requests:
            memory: ${RESOURCES_REQUESTS_MEMORY}
            cpu: ${RESOURCES_REQUESTS_CPU}
            nvidia.com/gpu: ${RESOURCES_REQUESTS_NVIDIA_COM_GPU}
          limits:
            memory: ${RESOURCES_LIMITS_MEMORY}
            cpu: ${RESOURCES_LIMITS_CPU}
            nvidia.com/gpu: ${RESOURCES_LIMITS_NVIDIA_COM_GPU}
        ports:
        - containerPort: 8080
EOYAML

logit "Creating deployment using the following yaml"
logit `cat /tmp/deployment.$$.yaml`

/usr/local/bin/kubectl create -n ${NAMESPACE} -f /tmp/deployment.$$.yaml
exit $?

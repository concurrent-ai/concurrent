#!/bin/bash

export DOCKER_HOST="tcp://docker-dind:2375"

logit() {
    echo "`date` - $$ - INFO - deploymodel.sh - ${*}" # >> ${LOG_FILE}
    # [ -n "$LOG_FILE" ] && echo "`date` - $$ - INFO - deploymodel.sh - ${*}"  >> "${LOG_FILE}"
}

logit "deploymodel Container Pip Packages="
pip list
logit "End deploymodel Container Pip Packages="

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

trap upon_exit EXIT

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
  echo "RUN echo '. /opt/conda/etc/profile.d/conda.sh' >> /root/start.sh" >> /root/workdir/container/Dockerfile
  echo "RUN echo 'conda init bash' >> /root/start.sh" >> /root/workdir/container/Dockerfile
  echo "RUN echo 'bash /root/start1.sh' >> /root/start.sh" >> /root/workdir/container/Dockerfile

  echo "RUN echo '#!/bin/bash' > /root/start1.sh" >> /root/workdir/container/Dockerfile
  echo "RUN echo 'set -x' > /root/start1.sh" >> /root/workdir/container/Dockerfile
  echo "RUN echo '. /opt/conda/etc/profile.d/conda.sh' >> /root/start1.sh" >> /root/workdir/container/Dockerfile
  echo "RUN echo 'conda activate mlflow-env' >> /root/start1.sh" >> /root/workdir/container/Dockerfile
  echo "RUN echo 'pip install -U pyopenssl cryptography' >> /root/start1.sh" >> /root/workdir/container/Dockerfile
  echo "RUN echo 'echo serve_model.py=====' >> /root/start1.sh" >> /root/workdir/container/Dockerfile
  echo "RUN echo 'cat /root/serve_model.py' >> /root/start1.sh" >> /root/workdir/container/Dockerfile
  echo "RUN echo 'python /root/serve_model.py' >> /root/start1.sh" >> /root/workdir/container/Dockerfile

  echo "RUN echo 'import mlflow' > /root/serve_model.py" >> /root/workdir/container/Dockerfile
  echo "RUN echo 'model_uri=\"/root/model\"' >> /root/serve_model.py" >> /root/workdir/container/Dockerfile
  echo "RUN echo 'pipeline = mlflow.transformers.load_model(model_uri, None, return_type=\"pipeline\", device=\"cuda\")' >> /root/serve_model.py" >> /root/workdir/container/Dockerfile
  echo "RUN echo 'print(pipeline)' >> /root/serve_model.py" >> /root/workdir/container/Dockerfile
  echo "RUN echo 'output = pipeline([\"Paris is the\"])' >> /root/serve_model.py" >> /root/workdir/container/Dockerfile
  echo "RUN echo 'print(f\"output={output}\")' >> /root/serve_model.py" >> /root/workdir/container/Dockerfile

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

# Test Free Service using the CLI (optional)

## CLI Environment variables

The following environment variables need to be set for using Concurrent for MLflow Free Service using the CLI (e.g. bash shell)
Here are the commands for setting up the environment variables in the bash shell.

```
export MLFLOW_TRACKING_URI=infinstor://mlflow.concurrent-ai.org/
export MLFLOW_EXPERIMENT_ID=<Experiment ID Created right after signup>
export MLFLOW_CONCURRENT_URI=https://concurrent.concurrent-ai.org/
```

## Install required pip packages

The concurrent_plugin is required for Concurrent for MLflow and infinstor_mlflow_plugin is required for the InfinStor MLflow service, which is included as part of the Concurrent for MLflow Free Service

```
pip install concurrent_plugin
pip install infinstor_mlflow_plugin
```

## Login to the service

```
python -m concurrent_plugin.login
Unable to read token file /home/jagane/.concurrent/token when MLFLOW_CONCURRENT_URI=https://concurrent.concurrent-ai.org/.  run login_concurrent cli command to login or place a valid token file as /home/jagane/.concurrent/token
Username: test1
Password: 
Login completed
```

Now, a quick test.

```
mlflow experiments list
  Experiment Id  Name        Artifact Location
---------------  ----------  -----------------------------------------------------------------------------
              5  test1-exp1  s3://infinstor-mlflow-artifacts-concurrent-ai.org/mlflow-artifacts/test1/5

```

## Run a MLflow Project

Here's an example of running an MLflow Project using the Concurrent for MLflow Free service

```
mlflow run -b concurrent-backend --backend-config '{"backend-type": "gke", "kube-context": "parallels-free", "kube-namespace": "parallelsns", "resources.requests.memory": "1024Mi", "kube-client-location": "backend"}' https://github.com/jagane-infinstor/mlflow-example-docker.git -Palpha=0.62 -Pl1_ratio=0.02
```

Here are some noteworthy items. The backend-config contains useful options:

- **backend-type**: **gke** in this example; other K8s implementations are supported
- **kube-context**: The name of the cluster, **parallels-free** in this example
- **kube-namespace**: The name of the namespace in the cluster, **parallelsns** in this example
- **resources.requests.memory**: Memory requested for this container. **1024Mi** in this example
- **kube-client-location**: **backend** indicates that the dockerfile creation will be taken care of by the Concurrent for MLflow backend

Now, you can browse over to the MLflow UI, available at **https://mlflowui.concurrent-ai.org/**. [Click here](https://mlflowui.concurrent-ai.org/ "MLflow UI"){:target="\_blank"} and see the results of the run. Here's an example screenshot:

[![](https://docs.concurrent-ai.org/images/free-3.png?raw=true)](https://docs.concurrent-ai.org/images/free-3.png?raw=true)

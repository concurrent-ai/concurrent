# Test Free Service using the CLI (optional)

## CLI Environment variables

The following environment variables need to be set for using MLflow Parallels Free Service using the CLI (e.g. bash shell)
Here are the commands for setting up the environment variables in the bash shell.

```
export MLFLOW_TRACKING_URI=infinstor://mlflow.mlflow-parallels.org/
export MLFLOW_EXPERIMENT_ID=<Experiment ID Created right after signup>
export MLFLOW_PARALLELS_URI=https://parallels.mlflow-parallels.org/
```

## Install required pip packages

The parallels_plugin is required for MLflow Parallels and infinstor_mlflow_plugin is required for the InfinStor MLflow service, which is included as part of the MLflow Parallels Free Service

```
pip install parallels_plugin
pip install infinstor_mlflow_plugin
```

## Login to the service

```
python -m parallels_plugin.login
Unable to read token file /home/jagane/.mlflow-parallels/token when MLFLOW_PARALLELS_URI=https://parallels.mlflow-parallels.org/.  run login_parallels cli command to login or place a valid token file as /home/jagane/.mlflow-parallels/token
Username: test1
Password: 
Login completed
```

Now, a quick test.

```
mlflow experiments list
  Experiment Id  Name        Artifact Location
---------------  ----------  -----------------------------------------------------------------------------
              5  test1-exp1  s3://infinstor-mlflow-artifacts-mlflow-parallels.org/mlflow-artifacts/test1/5

```

## Run a MLflow Project

Here's an example of running an MLflow Project using the MLflow Parallels Free service

```
mlflow run -b parallels-backend --backend-config '{"backend-type": "gke", "kube-context": "parallels-free", "kube-namespace": "parallelsns", "resources.requests.memory": "1024Mi", "kube-client-location": "backend"}' https://github.com/jagane-infinstor/mlflow-example-docker.git -Palpha=0.62 -Pl1_ratio=0.02
```

Here are some noteworthy items. The backend-config contains useful options:

- **backend-type**: **gke** in this example; other K8s implementations are supported
- **kube-context**: The name of the cluster, **parallels-free** in this example
- **kube-namespace**: The name of the namespace in the cluster, **parallelsns** in this example
- **resources.requests.memory**: Memory requested for this container. **1024Mi** in this example
- **kube-client-location**: **backend** indicates that the dockerfile creation will be taken care of by the MLflow Parallels backend

Now, you can browse over to the MLflow UI, available at **https://mlflowui.mlflow-parallels.org/**. [Click here](https://mlflowui.mlflow-parallels.org/ "MLflow UI"){:target="\_blank"} and see the results of the run. Here's an example screenshot:

[![](https://docs.mlflow-parallels.org/images/free-3.png?raw=true)](https://docs.mlflow-parallels.org/images/free-3.png?raw=true)

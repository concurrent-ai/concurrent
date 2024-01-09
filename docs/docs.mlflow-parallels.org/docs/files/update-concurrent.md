# 1. Add the EKS Cluster Configuration to Concurrent

In this step, we will configure Concurrent with the details of the EKS cluster and namespace

## 1.1. Update Concurrent Configuration with EKS cluster details

- Login to the Concurrent MLflow ui and click on the gear icon in the top right. The `Use Setting` page is displayed
- Choose the `Cluster Configuration` tab in `User Setting`
- Click `Add Cluster` and fill out the details. Note that EKS Role and EKS External ID are from the output of the CFT in Step 1
- Example screenshot below.

[![](https://docs.concurrent-ai.org/images/configure-cluster.png?raw=true)](https://docs.concurrent-ai.org/images/configure-cluster.png?raw=true)

## 1.2. Run a test pipeline in Concurrent

Finally, test the system by running a MLflow Project. For example,

- Login to the MLFlow UI and create an experiment: *https://mlflowui.infinstor.yourcompany.com*.  
    - Replace *mlflowui* (the default) in the URL above with the name you specified, if it was [overridden during Infinstor MLflow installation](https://docs.infinstor.com/files/install-service/).
    - Replace *infinstor.yourcompany.com* in the URL above,with the subdomain you specified, when [installing Infinstor MLflow](https://docs.infinstor.com/files/install-service/)
- Create a new *mlflow experiment* and note down the *experiment ID*.

Then execute the following commands in a shell to run a test pipeline in *Concurrent*:

```shell
# install the concurrent-plugin, if you haven't already done so.
python3 -m pip install concurrent-plugin

# replace YOUR_EXPERIMENT_ID with the ID of the experiment you created above. 
# repalce infinstor.yourcompany.com in the URLs below with the domain name you specified, when installing Infinstor MLflow.
# replace 'mlflow' and 'concurrent' in the URLs below, if they were overridden when installing Infinstor MLflow.
export MLFLOW_TRACKING_URI=infinstor://mlflow.infinstor.yourcompany.com 
export MLFLOW_CONCURRENT_URI=https://concurrent.infinstor.yourcompany.com 
export MLFLOW_EXPERIMENT_ID=YOUR_EXPERIMENT_ID;

# login to concurrent using your username and password. This generates a temporary token for invoking the REST API.
login_concurrent

# replace kube-context below with the name of your EKS cluster, say infinlogs-k8s-cluster
# replace kube-namespace below with the k8s namespace created for concurrent, say infinlogs-ns
mlflow run -b concurrent-backend --backend-config '{"backend-type": "eks", "kube-context": "concurrent-free", "kube-namespace": "parallelsns", "resources.requests.memory": "1024Mi", "kube-client-location": "backend"}' https://github.com/jagane-infinstor/mlflow-example-docker.git -Palpha=0.62 -Pl1_ratio=0.02
```

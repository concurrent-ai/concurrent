# Add the EKS Cluster Configuration to Concurrent

In this step, we will configure Concurrent with the details of the EKS cluster and namespace

## Step 6: Update Concurrent Configuration

- Login to the Concurrent MLflow ui and click on the gear icon in the top right. The `Use Setting` page is displayed
- Choose the `Cluster Configuration` tab in `User Setting`
- Click `Add Cluster` and fill out the details. Note that EKS Role and EKS External ID are from the output of the CFT in Step 1
- Example screenshot below.

[![](https://docs.concurrent-ai.org/images/configure-cluster.png?raw=true)](https://docs.concurrent-ai.org/images/configure-cluster.png?raw=true)

## Test system

Finally, test the system by running a MLflow Project. For example,

```
mlflow run -b concurrent-backend --backend-config '{"backend-type": "eks", "kube-context": "concurrent-free", "kube-namespace": "parallelsns", "resources.requests.memory": "1024Mi", "kube-client-location": "backend"}' https://github.com/jagane-infinstor/mlflow-example-docker.git -Palpha=0.62 -Pl1_ratio=0.02
```

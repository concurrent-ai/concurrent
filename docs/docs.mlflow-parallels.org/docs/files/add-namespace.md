# Add namespace to Kubernetes Cluster for Concurrent

This page describes the process for creating a new namespace called **newnsforconcurrent** for use by Concurrent.

## Create namespace

Download the following policy template:

```
wget https://docs.concurrent-ai.org/scripts/k8s-service-role.yaml
```

Modify the role to reflect the new name. In the following example, we are creating a new namespace called **newnsforconcurrent**:
```
sed -e 's/parallelsns/newnsforconcurrent/g' k8s-service-role.yaml > k8s-service-role-new.yaml
```

Create a namespace called **newnsforconcurrent**

```
kubectl create namespace newnsforconcurrent
```

## Create Privileged Role for System Components

Next, create a priveleged role for system components in this new namespace

```
kubectl apply -f k8s-service-role-new.yaml
```

## Create Low Privelege Role for User Code

```
wget https://docs.concurrent-ai.org/scripts/user-role.yaml
```

Next, edit the user-role.yaml file to change the namespace from parallelsns to the new namespace being created 

```
sed -e 's/parallelsns/newnsforconcurrent/g' user-role.yaml > user-role-new.yaml
```

Finally, apply to the k8s cluster

```
kubectl apply -f user-role-new.yaml 
```

Here's an example output:

```
clusterrole.rbac.authorization.k8s.io/k8s-role-for-users-newnsforconcurrent created
serviceaccount/k8s-serviceaccount-for-users-newnsforconcurrent created
rolebinding.rbac.authorization.k8s.io/k8s-serviceaccount-for-users-newnsforconcurrent-binding created
```

## Create DinD service

In this step, we create a Docker in Docker service for this namespace. [Instructions are available here](/files/create-dind/)

## Test new namespace

Finally, test that cluster setup worked by running a test MLflow Project as follows:

```
mlflow run -b concurrent-backend --backend-config '{"backend-type": "gke", "kube-context": "<your_cluster_name_here>", "kube-namespace": "newnsforconcurrent", "resources.requests.memory": "1024Mi", "kube-client-location": "backend"}' https://github.com/jagane-infinstor/mlflow-example-docker.git -Palpha=0.62 -Pl1_ratio=0.02
```

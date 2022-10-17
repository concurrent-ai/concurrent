# Add a Kubernetes Role for Pods/Jobs started by Concurrent for MLflow

Concurrent utilizes two roles in each namespace:

- A role with high privileges for system components to run
- A low privilege role for user code to run in

This page describes how these two roles can be created. The example namespace used here is parallelsns.

## Privileged Role

Create a privileged k8s role for system components and bind this role to a k8s ServiceAccount

### Cluster wide k8s role for system components

This cluster wide role needs to be created only once per cluster, at the time of creation of the first namespace.

Download the yaml file k8s-role-for-parallels.yaml from [here](https://docs.concurrent-ai.org/scripts/k8s-role-for-parallels.yaml "Download k8s-role-for-parallels.yaml"). Apply this yaml file to your cluster

Here's an example for a Regional cluster:

```
gcloud container clusters get-credentials <your_regional_cluster_name_here> --zone=us-central1
Fetching cluster endpoint and auth data.
kubeconfig entry generated for <your_regional_cluster_name_here>
kubectl apply -f k8s-role-for-parallels.yaml
clusterrole.rbac.authorization.k8s.io/k8s-role-for-parallels-lambda created
clusterrolebinding.rbac.authorization.k8s.io/k8s-role-for-parallels-lambda-binding created

```

and this is an example for a Zonal cluster:

```
gcloud container clusters get-credentials <your_zonal_cluster_name_here> --zone=us-central1-c
Fetching cluster endpoint and auth data.
kubeconfig entry generated for <your_zonal_cluster_name_here>
kubectl apply -f k8s-role-for-parallels.yaml
clusterrole.rbac.authorization.k8s.io/k8s-role-for-parallels-lambda created
clusterrolebinding.rbac.authorization.k8s.io/k8s-role-for-parallels-lambda-binding created
```

### Create a namespace called parallelsns

Create a namespace called parallelsns, and a ServiceAccount called k8s-serviceaccount-for-parallels-parallelsns

In this example, we create a namespace called parallelsns in k8s and configure it for use with Concurrent for MLflow

```
kubectl create namespace parallelsns
namespace/parallelsns created
```

### Create a ServiceAccount called k8s-serviceaccount-for-parallels-parallelsns

Download the yaml file k8s-service-role.yaml from [here](https://docs.concurrent-ai.org/scripts/k8s-service-role.yaml "Download k8s-service-role.yaml"). Apply this yaml file to your cluster

```
kubectl apply -f k8s-service-role.yaml 
serviceaccount/k8s-serviceaccount-for-parallels-parallelsns created
rolebinding.rbac.authorization.k8s.io/k8s-service-account-binding-parallelsns created
```

## Low Privilege Role for user code

Download the yaml file user-role.yaml from [here](https://docs.concurrent-ai.org/scripts/user-role.yaml "Download user-role.yaml"). Apply this yaml file to your cluster

```
kubectl apply -f user-role.yaml 
clusterrole.rbac.authorization.k8s.io/k8s-role-for-users-parallelsns created
serviceaccount/k8s-serviceaccount-for-users-parallelsns created
rolebinding.rbac.authorization.k8s.io/k8s-serviceaccount-for-users-parallelsns-binding created
```

Finally, test that cluster setup worked by running a test MLflow Project as follows:
```
mlflow run -b concurrent-backend --backend-config '{"backend-type": "gke", "kube-context": "<your_cluster_name_here>", "kube-namespace": "parallelsns", "resources.requests.memory": "1024Mi", "kube-client-location": "backend"}' https://github.com/jagane-infinstor/mlflow-example-docker.git -Palpha=0.62 -Pl1_ratio=0.02
```

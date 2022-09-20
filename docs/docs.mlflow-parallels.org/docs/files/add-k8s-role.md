# Add a Kubernetes Role for Pods/Jobs started by MLflow Parallels

## Create a k8s role for running jobs and bind this role to a k8s ServiceAccount

**Create a k8s role for running jobs**

Download the yaml file k8s-role-for-parallels.yaml from [here](https://docs.mlflow-parallels.org/scripts/k8s-role-for-parallels.yaml "Download k8s-role-for-parallels.yaml"). Apply this yaml file to your cluster

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

**Create a namespace called parallelsns, and a ServiceAccount called k8s-serviceaccount-for-parallels-parallelsns**

In this example, we create a namespace called parallelsns in k8s and configure it for use with MLflow Parallels

```
kubectl create namespace parallelsns
namespace/parallelsns created
```

Download the yaml file k8s-service-role.yaml from [here](https://docs.mlflow-parallels.org/scripts/k8s-service-role.yaml "Download k8s-service-role.yaml"). Apply this yaml file to your cluster

```
kubectl apply -f k8s-service-role.yaml 
serviceaccount/k8s-serviceaccount-for-parallels-parallelsns created
rolebinding.rbac.authorization.k8s.io/k8s-service-account-binding-parallelsns created
```

Finally, test that cluster setup worked by running a test MLflow Project as follows:
```
mlflow run -b parallels-backend --backend-config '{"backend-type": "gke", "kube-context": "<your_cluster_name_here>", "kube-namespace": "parallelsns", "resources.requests.memory": "1024Mi", "kube-client-location": "backend"}' https://github.com/jagane-infinstor/mlflow-example-docker.git -Palpha=0.62 -Pl1_ratio=0.02
```

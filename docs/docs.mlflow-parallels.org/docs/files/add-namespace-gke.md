# Add namespace to Kubernetes Cluster for Concurrent

This page describes the process for creating a new namespace called **newnsforconcurrent** for use by Concurrent.

## Create namespace

```
kubectl create namespace newnsforconcurrent
```

## k8s Roles/ServiceAccounts

Next, we will configure two Kubernetes ServiceAccounts **k8s-serviceaccount-for-parallels-NAMESPACE** and **k8s-serviceaccount-for-users-NAMESPACE**. The first ServiceAccount is for the Concurrent bootstrap job, which creates the Docker container required for the MLproject and the second is for the Concurrent worker code. We will also associate each ServiceAccount with a Role that provides it the required permissions.

### ServiceAccounts

- k8s-serviceaccount-for-parallels-NAMESPACE
- k8s-serviceaccount-for-users-NAMESPACE

### Roles

- k8s-role-for-concurrent-bootstrap: This role is for the ServiceAccount **k8s-serviceaccount-for-parallels-NAMESPACE** and is used by Concurrent bootstrap to create the Docker container if necessary
- k8s-role-for-users-<namespace>: This role is for the ServiceAccount **k8s-serviceaccount-for-users-NAMESPACE** and is used by user code from the MLproject

Download the following policy template:

```
wget https://docs.concurrent-ai.org/scripts/new-namespace-template.yaml
```

Modify the role to reflect the new name. In the following example, we are creating a new namespace called **newnsforconcurrent**:
```
sed -e 's/REPLACE_WITH_NEW_NAMESPACE_NAME/newnsforconcurrent/g' new-namespace-template.yaml > new-namespace.yaml
```

Apply to the kubernetes cluster

```
kubectl apply -f new-namespace.yaml
```

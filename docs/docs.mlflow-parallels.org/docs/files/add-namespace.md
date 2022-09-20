# Add namespace to Kubernetes Cluster for Concurrent

This page describes the process for creating a new namespace called **newnsforconcurrent** for use by Concurrent.

## Create namespace

Download the following policy template:

```
wget https://docs.concurrent-ai.org/scripts/k8s-service-role.yaml
```

Modify the role to reflect the new name. In the following example, we are creating a new namespace called **newnsforconcurrent**:
```
sed -e 's/parallelsns/newnsforconcurrent/gc' k8s-service-role.yaml > k8s-service-role-new.yaml
```

Create a namespace called **newnsforconcurrent**

```
kubectl create namespace newnsforconcurrent
```

Finally, create a service role for this new namespace

```
kubectl apply -f k8s-service-role-new.yaml
```

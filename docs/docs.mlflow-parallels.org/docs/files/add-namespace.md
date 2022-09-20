# Add namespace to Kubernetes Cluster for Parallels

This page describes the process for creating a new namespace called **newnsforparallels** for use by Parallels.

## Create namespace

Download the following policy template:

```
wget https://docs.mlflow-parallels.org/scripts/k8s-service-role.yaml
```

Modify the role to reflect the new name. In the following example, we are creating a new namespace called **newnsforparallels**:
```
sed -e 's/parallelsns/newnsforparallels/gc' k8s-service-role.yaml > k8s-service-role-new.yaml
```

Create a namespace called **newnsforparallels**

```
kubectl create namespace newnsforparallels
```

Finally, create a service role for this new namespace

```
kubectl apply -f k8s-service-role-new.yaml
```

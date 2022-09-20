# Create a Docker-In-Docker Service for MLflow Parallels

MLflow Parallels takes over the job of creating Docker containers for running workloads on Kubernetes. It uses a Docker In Docker service for this purpose. This service is per namespace.

Use the following command to download k8s-dind-service.yaml
```
wget https://docs.mlflow-parallels.org/cft/version/0.6/k8s-dind-service.yaml
```

Apply it to your kubernetes cluster using kubectl as follows:

```
kubectl apply -f k8s-dind-service.yaml
```

Note that this docker in docker service for the *default* namespace. If you want to create this service for another namespace, say *parallelsns*, then use the following two commands:

```
cat k8s-dind-service.yaml | sed -e 's/default/parallelsns/g' > /tmp/k8s-dind-service.yaml
kubectl apply -f /tmp/k8s-dind-service.yaml
```

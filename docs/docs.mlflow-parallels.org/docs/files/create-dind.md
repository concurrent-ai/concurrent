# Create a Docker-In-Docker Service for Concurrent for MLflow

Concurrent for MLflow takes over the job of creating Docker containers for running workloads on Kubernetes. It uses a Docker In Docker service for this purpose. This service is per namespace.

Use the following command to download k8s-dind-service.yaml
```
wget https://docs.concurrent-ai.org/cft/version/0.4/k8s-dind-service.yaml
```

The downloaded file creates a **dind** service in the **default** namespace. If you want to create the **dind** service in a different namespace, for example **newnsforconcurrent**, then edit the file to reflect this namespace. For example:

```
sed -e 's/default/newnsforconcurrent/g' k8s-dind-service.yaml > k8s-dind-service-new.yaml
```

Apply it to your kubernetes cluster using kubectl as follows:

```
kubectl apply -f k8s-dind-service-new.yaml
```

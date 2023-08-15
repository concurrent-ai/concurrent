# Test a new k8s cluster by running a project


Finally, test that cluster setup worked by running a test MLflow Project as follows:

```
mlflow run -b concurrent-backend --backend-config '{"backend-type": "gke", "kube-context": "<your_cluster_name_here>", "kube-namespace": "parallelsns", "resources.requests.memory": "1024Mi", "kube-client-location": "backend"}' https://github.com/jagane-infinstor/mlflow-example-docker.git -Palpha=0.62 -Pl1_ratio=0.02
```

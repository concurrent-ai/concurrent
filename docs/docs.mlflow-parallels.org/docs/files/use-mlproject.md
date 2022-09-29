# MLflow Project

The MLflow project defines a format for packaging AI/ML code - [MLflow Project](https://www.mlflow.org/docs/latest/projects.html "Go to MLflow docs for MLflow Project"){:target="\_blank"}. **Concurrent for MLflow** uses this format for code that runs in nodes in the DAG.

Here are the conditions for using **MLflow Projects** in **Concurrent for MLflow**

- The MLflow Project must be stored in git and accessible to the k8s cluster(s)
- The MLflow Project must use a Docker environment and the Dockerfile for the environment must be included in the git tree

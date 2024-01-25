# MLflow Project

The MLflow project defines a format for packaging AI/ML code - [MLflow Project](https://www.mlflow.org/docs/latest/projects.html "Go to MLflow docs for MLflow Project"){:target="\_blank"}. **Concurrent for MLflow** uses this format for code that runs in nodes in the DAG.

Here are the conditions for using **MLflow Projects** in **Concurrent for MLflow**

- The MLflow Project must be stored in git and accessible to the k8s cluster(s)
- The MLflow Project must use a Docker environment and the Dockerfile for the environment must be included in the git tree

## Adding kubernetes labels to DAG Nodes

If you add the parameter **k8s-labels** while defining the DAG node, then concurrent will add the specified kubernetes labels to the kubernetes pod when it creates the pod. The value of the parameter **k8s-labels** must be a comma separated list.

For example, if you set the value to the following, then three labels will be created:

**mlops.project-name,bugpinpointer,mlops.pipeline-name,githubwatcher,mlops.owner,jagane**

- A label named *mlops.project-name* with the value *bugpinpointer*
- A label named *mlops.pipeline-name* with the value *githubwatcher*
- A label named *mlops.owner* with the value *jagane*

Note: There cannot be any spaces or = in the value. Also, kubernetes automatically adds some labels to a pod, for example job-name. Hence, you cannot specify a job-name label using this method.


# MLflow Parallels Architecture

The components of MLflow Parallels are:

- External MLflow Service
- MLflow Parallels Control Plane
- MLflow Parallels Web UI
- Kubernetes Cluster(s) for compute
- Git Repostiory for storing MLflow Projects

## Architecture

[![](https://docs.mlflow-parallels.org/images/mlflow-parallels-arch.png?raw=true)](https://docs.mlflow-parallels.org/images/mlflow-parallels-arch.png?raw=true)

## External MLflow Service

MLflow Parallels is tightly integrated with MLflow. All runs are logged to MLflow. Output of each stage of processing is stored as MLflow artifacts and subsequent stages can partition these artifacts and use them as input. Finally, MLflow models can be loaded in MLflow Parallels and used for inference. Hence, MLflow Parallels requires a robust hosted MLflow service. Examples include Databricks MLflow, Azure ML MLflow and InfinStor MLflow. 

## MLflow Parallels Control Plane

MLflow Parallels Control Plane is responsible for all aspects of the operation of MLflow Parallels. This includes:

- Storing DAG templates
- Starting and Managing DAG runs. This includes partitioning data and scheduling work on one or more Kubernetes clusters
- Providing REST APIs for the MLflow Parallels UI

Currently, MLflow Parallels includes an implementation of the MLflow Parallels Control Plane using AWS Lambdas and AWS DynamoDB. Installation of the MLflow Parallels Control Plane is by means of Cloud Formation Templates.

The critical workflows in the MLflow Parallels Control Plane include the following:

- Run MLflow Projects in Kubernetes
    * Receives *mlflow run* requests from the mlflow CLI
    * Creates a **bootstrap pod** in the specified k8s cluster and send it the *mlflow run* request
- Design and store Directed Acyclic Graphs
    * MLflow Parallels Control Plane provides the **REST api** that **MLflow Parallels Web GUI** uses to create and store DAGs
- Run DAGs
    * Kicks off k8s pods for running the various steps in the DAG
    * Monitors pods for progress and pushes the work through the containers created

The MLflow Parallels Control plane is implemented using serverless functions (lambdas) in the cloud. It persists information in a serverless cloud key-value store.

## MLflow Parallels Web UI

The MLflow Parallels Web UI is integrated with MLflow Web UI and shows up as another tab in the MLflow User Inteface, right next to the Experiments and Models tabs.

## Kubernetes Cluster(s) for compute
MLflow Parallels needs a kubernetes cluster to run its MLflow Projects and DAGs. For this purpose, you must provide a Kubernetes Cluster of type supported by MLflow Parallels. The Kubernetes Cluster can be located in the cloud or on-premise. Currently, MLflow Parallels supports Amazon EKS and Google GKE kubernetes. Support for HPE Ezmeral, Openshift and VMware Tanzu are in the roadmap.

## Git

**MLflow Parallels** uses **MLflow Projects** stored in git as the code for computation.

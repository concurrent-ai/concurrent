# Prepare Kubernetes Cluster for Concurrent for MLflow

Specific actions need to be taken on your Kubernetes cluster in order to prepare it for use by **Concurrent for MLflow**.

These instructions differ from Kubernetes implementation to implementation. Currently, Concurrent for MLflow supports EKS and GKE. Choose your flavor of Kubernetes below and follow the instructions.

## EKS

The easiest way to prepare an EKS cluster for use by Concurrent for MLflow is to create a dedicated cluster. The IAM roles, the cluster itself, k8s roles in the cluster and service components in the cluster are all created by a single CFT. If you wish to create a brand new EKS Kubernetes cluster for use with Concurrent for MLflow, [Click here](/files/install-create "Create a new EKS Cluster for Concurrent for MLflow").


Alternatively, you can also follow a series of steps and configure an existing EKS cluster for use with Concurrent for MLflow. [Click here](connect-to-eks.md) for instructions on adding configuration items to your existing EKS Kubernetes cluster.

## GKE

There are three steps in enabling a GKE cluster for use by Concurrent for MLflow:

- Step 1: Create Service Account - [Click here](/files/create-service-account/ "Create Google Cloud Service Account") for details
- Step 2: Add Kubernetes Role for Concurrent for MLflow Pods - [Click here](/files/add-k8s-role/ "Create Kubernetes Role for Concurrent for MLflow") for details
- Step 3: Create a Docker-In-Docker service in your kubernetes for Concurrent for MLflow - [Click here](/files/create-dind/ "Create Docker-In-Docker Service for Concurrent for MLflow") for details

## Add Namespace to existing cluster

[Here](/files/add-namespace "Add k8s namespace for Concurrent for MLflow") are instructions for creating a new namespace and configuring it for use with Concurrent for MLflow

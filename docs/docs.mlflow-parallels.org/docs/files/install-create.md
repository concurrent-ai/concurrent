# Create New EKS Cluster for use with Concurrent for MLflow

This guide describes a simple CloudFormation Template method for creating an EKS cluster that is configued for use with the Concurrent for MLflow Service that you installed in the previous step.

Note - you will incur AWS charges for this EKS cluster.

- Create a new EKS cluster with the default services suggested by AWS including coredns
- Next, delete all node groups and nodes
- Finally add a new nodegroup with a single t3.micro instance. This is for coredns
- Now, follow [these](/files/install-existing/ "Configure Existing Kubernetes Cluster") steps to setup the required permissions and node groups

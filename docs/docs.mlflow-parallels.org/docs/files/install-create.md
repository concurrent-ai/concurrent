# Create New EKS Cluster for use with Concurrent for MLflow

Follow these instructions if you want to create a brand new EKS cluster for use with Concurrent. You will incur AWS charges for this new EKS cluster. Note that if you already have an EKS cluster, you can simply use a new namespace in that cluster for Concurrent and avoid the charges for a new EKS cluster.


- Create a new EKS cluster with the default services suggested by AWS including coredns
- Next, delete all node groups and nodes
- Add a new nodegroup with a single t3.micro instance. This is for coredns
- Now, follow [these](/files/install-existing/ "Configure Existing Kubernetes Cluster") steps to setup the required permissions and node groups

# Configure an existing EKS Cluster for use with Concurrent for MLflow

There are five steps that need to be performed in order for an existing cluster to be configured for use with Concurrent for MLflow.

- Create an AWS IAM role for the Concurrent for MLflow Service to access your EKS cluster with admin privileges
- Create a mapping in your Kubernetes cluster's aws-auth ConfigMap from the IAM role created above to the 'system-manager' 
- Create a k8s role for concurrent system components
- Create a namespace for running Concurrent DAGs and configure k8s roles for it
- Update Concurrent configuration with information about this k8s cluster

## Step 1: Create IAM Role

Browse to AWS CloudFormation console in the region where your EKS cluster is deployed, then click on ``Create stack -> With new resources (standard)``.

[![](https://docs.concurrent-ai.org/images/install-existing-1.png?raw=true)](https://docs.concurrent-ai.org/images/install-existing-1.png?raw=true)

Use the following S3 URL in the specify URL section:

```
https://s3.amazonaws.com/docs.concurrent-ai.org/cft/version/0.7/iam-role-for-parallels.yaml
```

Next, choose a name for the stack and specify the AWS account number where the Concurrent for MLflow service is running. The following screenshot shows the stack name role-for-parallels and the Concurrent for MLflow Service.


[![](https://docs.concurrent-ai.org/images/install-existing-2.png?raw=true)](https://docs.concurrent-ai.org/images/install-existing-2.png?raw=true)


Click on *Next* and add tags if necessary, then click on *Next* again. Be sure to check the **I acknowledge that AWS CloudFormation might create IAM resources with custom names.** box as shown below and create the stack

[![](https://docs.concurrent-ai.org/images/install-existing-3.png?raw=true)](https://docs.concurrent-ai.org/images/install-existing-3.png?raw=true)

Once the stack reaches the **CREATE_COMPLETE** state, click on the stack and click on the *Outputs* tab. There are two entries of interest here:

- RoleForConcurrentService
- RoleForConcurrentServiceExtId

Here's a screen capture:

[![](https://docs.concurrent-ai.org/images/install-existing-4.png?raw=true)](https://docs.concurrent-ai.org/images/install-existing-4.png?raw=true)

## Step 2: Create a mapping in your Kubernetes cluster's aws-auth ConfigMap from the IAM role created above to the 'system-manager' 

The next two steps needs to be performed on a machine with the bash shell and a functional kubectl for the cluster. Download the script path-aws-auth.sh from [here](https://docs.concurrent-ai.org/scripts/patch-aws-auth.sh "Download patch-aws-auth.sh"). This script takes one parameter, the RoleForInfinstorService output from the previous step. Here is a screen capture of a successful run of this script

First, update kubeconfig so that the cluster is accessible from your workstation. In the example below, the cluster is named kubetest32. After calling the aws cli to update the kubeconfig, call ``kubectl get nodes`` to verify that access to the cluster is working.

```
aws eks --region us-east-2 update-kubeconfig --name kubetest32
Added new context arn:aws:eks:us-east-2:678901234557:cluster/kubetest32 to /home/some_user/.kube/config
kubectl get nodes
NAME                                           STATUS   ROLES    AGE   VERSION
ip-192-168-32-210.us-east-2.compute.internal   Ready    <none>   32h   v1.22.12-eks-ba74326
```

Now, patch the aws-auth map for the cluster by making the IAM role created in the previous step an administrator for this cluster

```
bash ./patch-aws-auth.sh arn:aws:iam::678901234557:role/72253740-21cc-11ed-838a-024da6da7570-RoleForAccessingEksAndEcr
configmap/aws-auth patched

```

## Step 3: Create a k8s role for concurrent system components

This cluster wide role needs to be created only once per cluster

Download the yaml file k8s-role-for-parallels.yaml from [here](https://docs.concurrent-ai.org/scripts/k8s-role-for-parallels.yaml "Download k8s-role-for-parallels.yaml"). Apply this yaml file to your cluster

```
kubectl apply -f k8s-role-for-parallels.yaml
```

## Step 4: Create a namespace for running Concurrent DAGs and configure k8s roles for it

Directions for creating a new namespace and configuring it for use with Concurrent are described in detail [here](https://docs.concurrent-ai.org/files/add-namespace/ "Add namespace")


## Step 5: Update Concurrent Configuration

- Login to the Concurrent MLflow ui and click on the gear icon in the top right. The `Use Setting` page is displayed
- Choose the `Cluster Configuration` tab in `User Setting`
- Click `Add Cluster` and fill out the details. Note that EKS Role and EKS External ID are from the output of the CFT in Step 1
- Example screenshot below.

[![](https://docs.concurrent-ai.org/images/configure-cluster.png?raw=true)](https://docs.concurrent-ai.org/images/configure-cluster.png?raw=true)

## Test system

Finally, test the system by running a MLflow Project. For example,

```
mlflow run -b concurrent-backend --backend-config '{"backend-type": "eks", "kube-context": "concurrent-free", "kube-namespace": "parallelsns", "resources.requests.memory": "1024Mi", "kube-client-location": "backend"}' https://github.com/jagane-infinstor/mlflow-example-docker.git -Palpha=0.62 -Pl1_ratio=0.02
```

# Configure an existing EKS Cluster for use with Concurrent for MLflow

Here are the steps that need to be performed in order for an EKS cluster to be configured for use with Concurrent for MLflow.

- Create an AWS IAM role for the Concurrent for MLflow Service to access your EKS cluster with admin privileges
- Create a mapping in your Kubernetes cluster's aws-auth ConfigMap from the IAM role created above to the 'system-manager' 
- Create nodegroups or Fargate Profiles for running Concurrent system, worker and optionally deployment pods
- Create and configure one or more namespaces for Concurrent
- Update Concurrent configuration with information about this k8s cluster/namespace

## Step 1: Create AWS IAM Role

The AWS IAM role must be created in the AWS account where the EKS cluster is running. We provide a convenient CloudFormation template for creating this role. Otherwise, you can create an IAM role manually and provide it the following permissions

### Option 1: Manual

#### IAM Role Permissions

```
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Action": [
                "ecr:*"
            ],
            "Resource": "*",
            "Effect": "Allow"
        },
        {
            "Action": [
                "eks:*"
            ],
            "Resource": "arn:aws:eks:<REGION>:<AWS_ACCOUNT_NUMBER_WHERE_EKS_IS_RUNNING>:cluster/<EKS_CLUSTER_NAME>",
            "Effect": "Allow"
        },
        {
            "Action": [
                "sts:GetServiceBearerToken"
            ],
            "Resource": "*",
            "Effect": "Allow"
        },
        {
            "Effect": "Allow",
            "Action": [
                "ses:SendEmail",
                "ses:SendRawEmail"
            ],
            "Resource": "*"
        }
    ]
}
```

#### Notes

- Replace **REGION**, **AWS_ACCOUNT_NUMBER_WHERE_EKS_IS_RUNNING**, and **EKS_CLUSTER_NAME**
- ECR permissions allows Concurrent to create containers required for running MLflow projects as part of the pipeline
- SES permission allows Concurrent pipelines to send email using SES, for example, InfinLogs utilizes this permission to send alerts to users
- Be sure to configure an external ID for this manually created IAM Role and take note of the IAM Role ARN and the external ID. This will be used while configuring Concurrent to use this EKS cluster

### Option 2: Using CloudFormation

For convenience, we provide a CloudFormation template that you can use to create the IAM Role. Browse to AWS CloudFormation console in the region where your EKS cluster is deployed, then click on ``Create stack -> With new resources (standard)``.

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

## Step 2: Map AWS IAM Role to K8s system-manager

In this step, you will create a mapping in your Kubernetes cluster's aws-auth ConfigMap from the IAM role created above to the 'system-manager' 

The next two steps needs to be performed on a machine with the bash shell and a functional kubectl for the cluster. Download the script patch-aws-auth.sh from [here](https://docs.concurrent-ai.org/scripts/patch-aws-auth.sh "Download patch-aws-auth.sh"). This script takes one parameter, the RoleForInfinstorService output from the previous step. Here is a screen capture of a successful run of this script

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

## Step 3: Prepare Compute

### Option 1: Create node groups

Concurrent uses the following node groups:

#### system

This node group is used for running the bootstrap container. Bootstrap is a system component that builds the worker container image and kicks of the kubernetes job for the worker node.

It is acceptable to use spot instances for the *system* node group. Here's a suggested list of instance types for this node group

```
    t3.medium
    c5.large
    c5a.large
    c6a.large
```

It is also required to set the disk size to 200GB for this nodegroup instances

The node group size is set to:

```
Desired size: 1 node
Minimum size: 0 nodes
Maximum size: 1 node
```

The following taint must be set.

```
Key: concurrent-node-type
Value: system
Effect: NoSchedule
```

#### worker

This node group is used for running the pipeline(DAG) nodes.

It is acceptable to use spot instances for the *worker* node group. Here's a suggested list of instance types for this node group

```
    c4.2xlarge
    c5.2xlarge
    c5a.2xlarge
    m4.2xlarge
```

It is also required to set the disk size to 200GB for this nodegroup instances

The node group size is set to:

```
Desired size: 1 node
Minimum size: 0 nodes
Maximum size: 1 node
```

The following taint must be set.

```
Key: concurrent-node-type
Value: worker
Effect: NoSchedule
```

#### deployment

This node group is optional and only used for deployment.

It is acceptable to use spot instances for the *deployment* node group. Here's a suggested list of instance types for this node group

```
    c3.2xlarge
    c4.2xlarge
    c5a.2xlarge
    c6a.2xlarge
```

It is also required to set the disk size to 200GB for this nodegroup instances

The node group size is set to:

```
Desired size: 1 node
Minimum size: 0 nodes
Maximum size: 1 node
```

The following taint must be set.

```
Key: concurrent-node-type
Value: deployment
Effect: NoSchedule
```

### Option 2: Use Fargate Profiles

Concurrent can be configured to use EKS Fargate Profiles for compute instead of node pools. In order to do this, you must first prepare your VPC for EKS Fargate use. Next, you must create two Fargate Profiles for your EKS cluster.

#### Prepare VPC

EKS Fargate Profiles can only run in private subnets of the VPC. Additionally, the private subnets must have Internet access through a NAT Gateway or a NAT Instance. Here are the requirements:

- Three Private Subnets in the VPC
- NAT Internet access through a NAT Gateway or NAT instance, or a DIY NAT Instance

We include a convenient CFT that creates the above requirements, i.e. three private subnets with Internet access through a DIY NAT Instance. In your AWS console, go to CloudFormation and click on *Create Stack*, pick *With new resources (standard)* and specify the template using the following Amazon S3 URL:

```
https://s3.amazonaws.com/docs.concurrent-ai.org/scripts/fargate-subnets.yml
```

The following screen capture shows this step:

[![](https://docs.concurrent-ai.org/images/fargate-subnets-cft.png?raw=true)](https://docs.concurrent-ai.org/images/fargate-subnets-cft.png?raw=true)

Fill out the parameters for this CloudFormation template. Here is an example:

[![](https://docs.concurrent-ai.org/images/fargate-subnets-cft-filled.png?raw=true)](https://docs.concurrent-ai.org/images/fargate-subnets-cft-filled.png?raw=true)

Noteable parameters in the above CloudFormation template are:

- **VpcId** This is the ID of the VPC that you are adding these subnets to
- **VpcPublicSubnetId** The t2.micro DIY NAT instance that will be created by the CFT needs a public IP address to forward network packets to. This subnet is the public subnet for this purpose.
- **VpcCidr** This is the IP address range of the entire VPC
- **Subnet1Cidr**, **Subnet2Cidr**, **Subnet3Cidr**: These are the subset IP address ranges that will be assigned to the new private subnets

Once this CloudFormation template has run to completion, it will have created three new private subnets for the EKS Fargate profiles to use. Configuration of the EKS fargate profiles is described next.

#### Configure EKS

Two Fargate Profiles are required for Concurrent - they are named *concurrent-worker* and *concurrent-system* in the following screen captures.

In the following screencapture, the name of the fargate profile is *concurrent-system* and the subnets chosen are the ones created by the CFT above

[![](https://docs.concurrent-ai.org/images/conf-fargate-system-1.png?raw=true)](https://docs.concurrent-ai.org/images/conf-fargate-system-1.png?raw=true)

In the following screencapture, the pod selectors are configured as follows:

- Two namespaces *unpriv-ns-jagane* and *unpriv-ns-raj*
- Each namespace has a label *concurrent-node-type* set to the value *system*

[![](https://docs.concurrent-ai.org/images/conf-fargate-system-2.png?raw=true)](https://docs.concurrent-ai.org/images/conf-fargate-system-2.png?raw=true)

Here is the summary of the fargate profile called *concurrent-worker*

[![](https://docs.concurrent-ai.org/images/conf-fargate-system-3.png?raw=true)](https://docs.concurrent-ai.org/images/conf-fargate-system-3.png?raw=true)

The next three screen capture images are for creating the *concurrent-worker* fargate profile

[![](https://docs.concurrent-ai.org/images/conf-fargate-worker-1.png?raw=true)](https://docs.concurrent-ai.org/images/conf-fargate-worker-1.png?raw=true)
[![](https://docs.concurrent-ai.org/images/conf-fargate-worker-2.png?raw=true)](https://docs.concurrent-ai.org/images/conf-fargate-worker-2.png?raw=true)
[![](https://docs.concurrent-ai.org/images/conf-fargate-worker-3.png?raw=true)](https://docs.concurrent-ai.org/images/conf-fargate-worker-3.png?raw=true)

That's it. Now Concurrent pipelines can be run on these two fargate profiles

## Step 5: Create namespace(s)

In this step, we create one or more namespaces for running Concurrent DAGs and configure the required k8s SystemAccount and roles for each namespace

Directions for creating a new namespace and configuring it for use with Concurrent are described in detail [here](/files/add-namespace/ "Add namespace")


## Step 6: Update Concurrent Configuration

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

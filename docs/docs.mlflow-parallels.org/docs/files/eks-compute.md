# Add compute resources to your EKS Cluster for Concurrent

Compute resources need to be added to your EKS cluster. This can be accomplished using **node groups** or **Fargate Profiles**

## Option 1: Create node groups

Concurrent uses the following node groups:

### system

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

### worker

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

### deployment

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

## Option 2: Use Fargate Profiles

Concurrent can be configured to use EKS Fargate Profiles for compute instead of node pools. In order to do this, you must first prepare your VPC for EKS Fargate use. Next, you must create two Fargate Profiles for your EKS cluster.

### Prepare VPC

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

### Configure EKS

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

# Create New EKS Cluster for use with Concurrent for MLflow

This guide describes a simple CloudFormation Template method for creating an EKS cluster that is configued for use with the Concurrent for MLflow Service that you installed in the previous step.

Note - you will incur AWS charges for this EKS cluster.

## Prequisites

We provide a CFT for creating and configuring an EKS cluster for use with Concurrent for MLflow. This CFT is based on Amazon Web Services Quickstart Template. In order to use this CFT you must first you must **activate** the Quick Start CloudFormation Public Extension **AWSQS::Kubernetes::Resource**. In order to activate this extension, you must first creae an IAM Role for the Extension. Step by step instructions to perform these two steps follow:

### Step 1: Create Role for the Quick Start extension

Run the following CFT by [clicking here](https://us-east-1.console.aws.amazon.com/cloudformation/home?region=us-east-1#/stacks/create/review/?stackName=role-for-cft-qs-extension&templateURL=https://s3.amazonaws.com/docs.concurrent-ai.org/cft/pre-requisites/role-for-cft-qs-extension.yaml){:target="\_blank"}

When you press the link above, you will be taken to the AWS Console CloudFormation page as shown below.

[![](https://docs.concurrent-ai.org/images/cft/create-role-for-extension/image1.png?raw=true)](https://docs.concurrent-ai.org/images/cft/create-role-for-extension/image1.png?raw=true)

When you CFT creation is completed, check the output of the CFT and copy the ExecutionRoleArn as shown below:

[![](https://docs.concurrent-ai.org/images/cft/create-role-for-extension/image2.png?raw=true)](https://docs.concurrent-ai.org/images/cft/create-role-for-extension/image2.png?raw=true)

### Step 2: Use Role and Activate the AWSQS::Kubernetes::Resource extension

Next, go to CloudFormation console, click on the **Registry** tab in the left navbar and then the **Public extensions**. Choose **Third Party** and enter. In the search bar choose **Extension name prefix** and enter the text **AWSQS::Kubernetes::Resource**. The following screen should show up:

[![](https://docs.concurrent-ai.org/images/cft/create-role-for-extension/image3.png?raw=true)](https://docs.concurrent-ai.org/images/cft/create-role-for-extension/image3.png?raw=true)

Choose this extension and activate it. You will need to enter the ARN of the role created in the first step when you do this. Screencapture below:

[![](https://docs.concurrent-ai.org/images/cft/create-role-for-extension/image4.png?raw=true)](https://docs.concurrent-ai.org/images/cft/create-role-for-extension/image4.png?raw=true)

## Create EKS Cluster

To create a fresh EKS cluster for use with Concurrent for MLflow in us-east-2, [click here](https://us-east-2.console.aws.amazon.com/cloudformation/home?region=us-east-2#/stacks/create/review/?stackName=eks-for-concurrent&templateURL=https://s3.amazonaws.com/docs.concurrent-ai.org/cft/example-cluster/create-eks-for-parallels.yaml&param_Region=us-east-2){:target="\_blank"}

To create a fresh EKS cluster for use with Concurrent for MLflow in us-west-2, [click here](https://us-west-2.console.aws.amazon.com/cloudformation/home?region=us-west-2#/stacks/create/review/?stackName=eks-for-concurrent&templateURL=https://s3.amazonaws.com/docs.concurrent-ai.org/cft/example-cluster/create-eks-for-parallels.yaml&param_Region=us-west-2){:target="\_blank"}

### CloudFormation Console - Start

[![](https://docs.concurrent-ai.org/images/install-create-1.png?raw=true)](https://docs.concurrent-ai.org/images/install-create-1.png?raw=true)

### CloudFormation Console - After Pressing Next

[![](https://docs.concurrent-ai.org/images/install-create-1.png?raw=true)](https://docs.concurrent-ai.org/images/install-create-2.png?raw=true)

Note that the name suggested for the stack is **eks-for-concurrent**. You can change this if you want. Note also that the CFT creates **three t3.medium** nodes for compute. You can change this as well.

### CloudFormation Console - After Pressing Next

[![](https://docs.concurrent-ai.org/images/install-create-3.png?raw=true)](https://docs.concurrent-ai.org/images/install-create-3.png?raw=true)

The next screen offers CloudFormation options. It is perfectly fine to leave all options in their default settings.

### CloudFormation Console - After Pressing Next

[![](https://docs.concurrent-ai.org/images/install-create-4.png?raw=true)](https://docs.concurrent-ai.org/images/install-create-4.png?raw=true)

The next screen has two important settings - the IAM custom names warning and the CAPABILITY_AUTO_EXPAND warning. Please check both of these boxes and click next.

### CloudFormation Console - CFT Creation Complete

Once the CFT reaches the **CREATE_COMPLETE** state, identify the substack named **eks-for-concurrent-iamrole-<something>** and click on the outputs of that stack. The following screen capture is illustrative

[![](https://docs.concurrent-ai.org/images/install-create-5.png?raw=true)](https://docs.concurrent-ai.org/images/install-create-5.png?raw=true)

### Concurrent UI - Configure Cluster

You will need the entries **RoleForParallelsService** and **RoleForParallelsServiceExtId** for configuring Concurrent. Browse to the concurrent web ui and login. Click on the gear icon in the top right of the page and choose the **Cluster Configuration** tab. Click on **Add Cluster** and use the following entries

- **Cluster name** eks-for-concurrent
- **Namespace** default
- **Cluster type** EKS
- **Cluster Region** us-east-2 or us-west-2
- **EKS Role** The role that the eks-for-concurrent-iamrole-<something> substack output
- **EKS External ID** The external ID that the eks-for-concurrent-iamrole-<something> substack output
- **ECR Type** Usually private. Use public if you want the ECR repository to be public

[![](https://docs.concurrent-ai.org/images/install-create-6.png?raw=true)](https://docs.concurrent-ai.org/images/install-create-6.png?raw=true)

Finally, test the system by running a MLflow Project. For example,

```
mlflow run -b concurrent-backend --backend-config '{"backend-type": "eks", "kube-context": "eks-for-concurrnet", "kube-namespace": "default", "resources.requests.memory": "1024Mi", "kube-client-location": "backend"}' https://github.com/jagane-infinstor/mlflow-example-docker.git -Palpha=0.62 -Pl1_ratio=0.02
```

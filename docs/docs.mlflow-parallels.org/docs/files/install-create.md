# Create New EKS Cluster for use with MLflow Parallels

This guide describes a simple CloudFormation Template method for creating an EKS cluster that is configued for use with the MLflow Parallels Service that you installed in the previous step.

Note - you will incur AWS charges for this EKS cluster.

# Create EKS Cluster

To create a fresh EKS cluster for use with MLflow Parallels, [click here](https://console.aws.amazon.com/cloudformation/home?region=us-east-2#/stacks/new?stackName=EKS-for-Parallels&templateURL=https://s3.amazonaws.com/docs.mlflow-parallels.org/cft/version/0.3/install/create-eks-for-parallels.yaml "Create EKS Cluster using CFT"){:target="\_blank"}. It will take you to your AWS Console's CloudFormation page with a pre-loaded CFT. Screenshots and instructions below.

**CloudFormation Console - Start**

[![](https://docs.mlflow-parallels.org/images/install-create-1.png?raw=true)](https://docs.mlflow-parallels.org/images/install-create-1.png?raw=true)

**CloudFormation Console - After Pressing Next**

[![](https://docs.mlflow-parallels.org/images/install-create-1.png?raw=true)](https://docs.mlflow-parallels.org/images/install-create-2.png?raw=true)

Note that the name suggested for the stack is **EKS-For-Parallels**. You can change this if you want. Note also that the CFT creates **three t3.medium** nodes for compute. You can change this as well.

**CloudFormation Console - After Pressing Next**

[![](https://docs.mlflow-parallels.org/images/install-create-3.png?raw=true)](https://docs.mlflow-parallels.org/images/install-create-3.png?raw=true)

The next screen offers CloudFormation options. It is perfectly fine to leave all options in their default settings.

**CloudFormation Console - After Pressing Next**

[![](https://docs.mlflow-parallels.org/images/install-create-4.png?raw=true)](https://docs.mlflow-parallels.org/images/install-create-4.png?raw=true)

The next screen has two important settings - the IAM custom names warning and the CAPABILITY_AUTO_EXPAND warning. Please check both of these boxes and click next.

XXX: Document how the role ARN and the ext are taken from the CloudFormation template and used to configure the free service

Finally, test the system by running a MLflow Project. For example,

```
mlflow run -b parallels-backend --backend-config '{"backend-type": "eks", "kube-context": "mlflow-parallels", "kube-namespace": "default", "resources.requests.memory": "1024Mi", "kube-client-location": "backend"}' https://github.com/jagane-infinstor/mlflow-example-docker.git -Palpha=0.62 -Pl1_ratio=0.02
```

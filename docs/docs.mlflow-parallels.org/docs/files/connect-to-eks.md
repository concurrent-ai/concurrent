# Connect Concurrent to EKS Cluster

Here are the steps that need to be performed in order to connect Concurrent to an EKS cluster

- Create an AWS IAM role for Concurrent to access your EKS cluster
- Map the IAM role created above to the EKS cluster's 'system-manager' 

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

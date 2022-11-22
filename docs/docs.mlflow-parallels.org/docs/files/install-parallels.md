# Install Concurrent for MLflow Control Plane

Concurrent for MLflow Control Plane is built as AWS Lambda Serverless functions that store persistent data in AWS DynamoDB. There are no VMs running 24x7 running up the cloud bill. Your AWS bill will be proportional to your usage of the MLflow parallels service.

## CloudFormation Template based install

Ensure that you are logged into your AWS console and then [click here](https://console.aws.amazon.com/cloudformation/home?region=us-east-1#/stacks/new?stackName=ConcurrentForMLflow&templateURL=https://s3.amazonaws.com/concurrentdist/cft/parallels-cft/1.0.23/mlflow-parallels-cft.yaml "Create Concurrent for MLflow Control Plane"){:target="\_blank"}. It will take you to your AWS Console's CloudFormation page with a pre-loaded CFT for creating a CloudFormation stack using CFTs published by the Concurrent for MLflow Project. Screenshots and instructions below.

Here is the CFT that the above link refers to:
```
https://s3.amazonaws.com/concurrentdist/cft/parallels-cft/1.0.23/mlflow-parallels-cft.yaml
```

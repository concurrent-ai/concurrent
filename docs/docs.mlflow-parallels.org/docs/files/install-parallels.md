# Install MLflow Parallels Control Plane

MLflow Parallels Control Plane is built as AWS Lambda Serverless functions that store persistent data in AWS DynamoDB. There are no VMs running 24x7 running up the cloud bill. Your AWS bill will be proportional to your usage of the MLflow parallels service.

## CloudFormation Template based install

Ensure that you are logged into your AWS console and then [click here](https://console.aws.amazon.com/cloudformation/home?region=us-east-2#/stacks/new?stackName=MLflow-Parallels&templateURL=https://s3.amazonaws.com/parallelsdist/cft/parallels-cft/1.0.0/mlflow-parallels-cft.yaml "Create MLflow Parallels Control Plane"){:target="\_blank"}. It will take you to your AWS Console's CloudFormation page with a pre-loaded CFT for creating a CloudFormation stack using CFTs published by the MLflow Parallels Project. Screenshots and instructions below.

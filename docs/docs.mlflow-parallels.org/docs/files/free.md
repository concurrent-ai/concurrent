# The Free Concurrent for MLflow Service

The Concurrent for MLflow Project offers a free hosted service. This service includes everything required to try Concurrent for MLflow:

- **Free hosted MLflow Service**
- **Free hosted Concurrent for MLflow Service**
- **Kubernetes cluster** (no GPU, sorry) to run MLprojects and DAGs.

Click [here](https://docs.concurrent-ai.org/register "Register for a Concurrent for MLflow Free Service Account"){:target="\_blank"} to sign up for a free account to try out Concurrent for MLflow. (This will open the sign up page in a new browser tab)

## Verify Email and Activate Account

When you sign up for an account, you will receive a confirmation email. Follow the link in the confirmation email to activate your new account and to change the initial password.

## Login to MLflow UI and Create an Experiment

After activating the account, you will be taken to the main page of the UI. Click on the plus icon on the left navbar to create an experiment as shown in the screen capture below.

For your reference the **MLflow UI** is always available at **https://mlflowui.concurrent-ai.org/**. [Click here to access the UI](https://mlflowui.concurrent-ai.org/ "MLflow UI"){:target="\_blank"} Note that this will open the MLflow UI in a new browser tab.

[![](https://docs.concurrent-ai.org/images/free-1.png?raw=true)](https://docs.concurrent-ai.org/images/free-1.png?raw=true)

In the **Create Experiment** flyout, leave the **Artifact Location** empty. After the experiment is created, note down the experiment ID as shown below. In this example, the experiment id is 5. You will need to set this as an environment variable **MLFLOW_EXPERIMENT_ID** for command line use.

[![](https://docs.concurrent-ai.org/images/free-2.png?raw=true)](https://docs.concurrent-ai.org/images/free-2.png?raw=true)

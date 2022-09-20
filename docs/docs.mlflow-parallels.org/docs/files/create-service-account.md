# Create Google Cloud Service Account for MLflow Parallels

This section describes the process of creating a Google Cloud Service Account for MLflow Parallels. Google Cloud Service Accounts are created in the context of a project.


## Step 1: Create Service Account

[Browse](https://console.cloud.google.com "Google Cloud Console") to the specific project in the google cloud console, and click on **Create Service Account** as shown below


[![](https://docs.mlflow-parallels.org/images/create-service-account-1.png?raw=true)](https://docs.mlflow-parallels.org/images/create-service-account-1.png?raw=true)

Add the following three **Roles** to this **Service Account**

- **Cloud Build Service Account**
- **Container Registry Service Agent**
- **Kubernetes Engine Service Agent**

When you click on the **IAM And Permissions** page and choose the **IAM** item in the left navbar, the table displayed should have an entry such as the following:

[![](https://docs.mlflow-parallels.org/images/create-service-account-2.png?raw=true)](https://docs.mlflow-parallels.org/images/create-service-account-2.png?raw=true)

## Step 2: Create Key For Service Account

[Browse](https://console.cloud.google.com "Google Cloud Console") to the specific project in the google cloud console, and click on the **IAM And Permissions** page and choose the **Service Accounts** item in the left navbar. Click on the three vertical dots in the **Actions** column of the table in the row for your service account. Click on **Manage Keys** and create a key. Download the **json** key. You will use this key to configure your GKE cluster.

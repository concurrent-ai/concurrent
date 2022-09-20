# MLfow Parallels Free Service - Hello World

Get started with MLflow Parallels using this simple Hello World DAG

Here is a screen capture video:

<iframe width="560" height="315" src="https://www.youtube.com/embed/eykHtBg8bNo" title="YouTube video player" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe>


## Try it

### Login to the UI

MLflow Parallels Free Service UI is available at **https://mlflowui.mlflow-parallels.org/**: [click here](https://mlflowui.mlflow-parallels.org/ "MLflow Parallels Free Service UI"){:target="\_blank"} (This will open a new tab). Perform the steps described below to create and run a simple Parallel.

### Click Parallels tab

[![](https://docs.mlflow-parallels.org/images/helloworld/hw1.png?raw=true)](https://docs.mlflow-parallels.org/images/helloworld/hw1.png?raw=true)

### Click 'Create Parallel' button

[![](https://docs.mlflow-parallels.org/images/helloworld/hw2.png?raw=true)](https://docs.mlflow-parallels.org/images/helloworld/hw2.png?raw=true)

Give the parallel a name, **helloworld-test1** in this example. Note that the Parallel name has to be unique among all users in the Enterprise. This is necessary in order to allow for sharing of Parallels. It is useful to attach your username to the Parallel's name. After successful creation of the Parallel, you will be taken to a page with a list of Parallels that you have created or have access to. Click on the newly created Parallel (helloworld-test1 in this example) and you will be taken to the page for the specific Parallel. In this page, click on the **Create Template** button as shown below

[![](https://docs.mlflow-parallels.org/images/helloworld/hw3.png?raw=true)](https://docs.mlflow-parallels.org/images/helloworld/hw3.png?raw=true)

### Add Node to DAG

As you might already know, each step in the processing of a **DAG (Directed Acyclic Graph)** is termed a **Node**. In this example, we add a single node and configure it to be the helloworld MLproject in the MLflow Parallels git tree. Click on the **Add Node** button as shown below

[![](https://docs.mlflow-parallels.org/images/helloworld/hw4.png?raw=true)](https://docs.mlflow-parallels.org/images/helloworld/hw4.png?raw=true)

### Fill Node details

Here are the node details:

[![](https://docs.mlflow-parallels.org/images/helloworld/node.png?raw=true)](https://docs.mlflow-parallels.org/images/helloworld/node.png?raw=true)

We have chosen a container with 256 Megabytes of RAM and 250 milli CPUs, i.e. one quarter of a virtual CPU

These are some details that you will need while trying this out:

- Kubernetes Cluster: **parallels-free**
- Cluster's Namespace: **parallelsns**
- GIT Url: **https://github.com/MLflowParallels/mlflow-parallels-examples.git**
- Project Path: **helloworld**

Click Add and then save the template. For this simple example, we will not be using any inputs or parameters. There are more sophisticated examples that will demonstrate these features.

### Run DAG

Once you have saved the template using the **Save Template** button, you are ready to run the Parallel. From the detail page for the Parallel, press the **Run Template** button. You are presented with an opportunity to modify any of the parameters stored in the template. For this example, you do not need to modify anything - just press the **Run Template** button. Once the template run starts up, you will be taken to the MLflow experiments tab where you can follow the progress of the run.

[![](https://docs.mlflow-parallels.org/images/helloworld/hw5.png?raw=true)](https://docs.mlflow-parallels.org/images/helloworld/hw5.png?raw=true)

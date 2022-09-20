# Frequently Asked Questions

## Suitable Use Cases

### **FAQ 1: Is MLflow Parallels a good tool for live inference, i.e. spinning up an ensemble of containers with a Load Balancer in front?**
No. MLflow Parallels is best suited for **pre-processing data** and for **batch or micro-batch inferencing**. MLflow Parallels will spin up any number of **short lived containers** in one or more Kubernetes clusters, run multi-step pre-processing of data, then perform batch or micro-batch inferencing. Containers will be terminated after each stage of work is complete. **Extraordinary savings** can be accomplished by replacing live inference systems with MLflow Parallels based batch/micro-batch inference systems.

### **FAQ 2: Is MLflow Parallels suitable for distributed training?**
No. Distributed training is best accomplished using features built into Pytorch or Tensorflow.

## Run MLproject in k8s

### **FAQ 3: Doesn't MLflow itself include the ability to run MLprojects in Kubernetes? Why do I need MLflow Parallels to run an MLflow Project in Kubernetes?**

Yes, MLflow itself includes capabilities to run MLflow Projects in Kubernetes. However, it is a complex task that requires specialized Docker and Kubernetes knowledge. [Click here](https://medium.com/p/b0906e04c273 "Run MLflow Project in EKS"){:target="\_blank"} to read a medium article describing the set of steps for running an MLflow Project in Kubernetes.

For instance, much of the work in running MLflow projects in Kubernetes is docker related. One must create an 'environment' docker image, then create a 'full' docker image from the 'environment' docker image, and then publish this 'full' image to a docker repository . Only then, Kubernetes can run the MLflow Project. Clearly, this requires extensive knowledge of docker and also requires a machine with docker cli and a docker repository.

**MLflow Parallels** automates these steps and eliminates the need for Docker and Kubernetes knowledge. Hence it is easy for Data Scientists and MLops staff to run MLflow Projects in Kubernetes - all without becoming Docker or Kubernetes experts.

**MLflow Parallels** uses the kubernetes environment itself to create the requisite docker images. Hence, MLflow Parallels can kick off MLflow Projects and DAGs from resource starved environments such as javascript in the browser and serverless functions.

## Comparison

### **FAQ 4: How does MLflow Parallels compare to MLflow Pipelines?**

**MLflow Pipelines** provides a higher level abstraction than MLflow Parallels. MLflow Pipelines is architected around pre-built templates, e.g. regression template. As such, it is an inflexible framework that works really well if your problem fits the model that the authors of MLflow Pipelines had envisioned. For example, you could provide your own code for *ingest*, *split*, *transform*, *train*, *evaluate* and *register* steps. No other processing is supported. Further, there is no mention of parallelizing the processing or running it in Kubernetes.

**MLflow Parallels**, on the other hand, does not prescribe a specific set of steps - you provide MLprojects and design the graph using a simple GUI with drag and drop. MLflow Parallels excels at taking this graph of MLprojects and running them, in parallel, on **Kubernetes**.

### **FAQ 5: How does MLflow Parallels compare to Kubeflow Pipelines?**

**Kubeflow Pipelines** is similar to **MLflow Parallels** in that both projects compose a Machine Learning Project into multiple steps that are then run in Kubernetes. However, that is where the similariy ends. Here are the advantages of **MLflow Parallels**

- **MLflow Parallels** is tightly integrated with **MLflow**. These are the resulting benefits:
    * Runs are tracked using standard **MLflow Experiment Tracking** and its concept of parent/child runs; Kubeflow Pipelines does not address run tracking
    * **MLflow Parallels** uses the well established **MLflow Project** definition as the unit of compute, whereas Kubeflow Pipelines reinvents the wheel by defining a new *component*
    * **MLflow Parallels** uses **MLflow Artifacts** for passing data between steps in the processing, whereas Kubeflow Pipelines does not provide a clean mechanism to pass data between steps
- *Docker* and *Kubernetes* expertise is essential for using Kubeflow Pipelines. **MLflow Parallels** automates all Docker and Kubernetes operations - users merely store their MLprojects in git and use a drag and drop GUI to build and run graphs.
- **MLflow Parallels** parallelizes computation, for example, if you have 10,000 images that need to be pre-processed before batch inference, and if you have the Kubernetes capacity to run 10 containers, MLflow Parallels will create 10 containers and run them in parallel for pre-processing the 10,000 images
- The **MLflow Parallels** control plane runs in the cloud, independent of Kubernetes. The advantage of this architecture is that **MLflow Parallels** automatically supports multiple kubernetes clusters - for example a single Parallels DAG can be executed partially in an EKS cluster in the cloud and partially in a GPU enabled HPE Ezmeral cluster on-premise. This is true hybrid cloud.

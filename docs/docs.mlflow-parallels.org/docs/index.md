**MLflow Parallels** is an **Apache Licensed** open source project for running MLflow projects, in parallel, in **Kubernetes**. It enhances MLflow with two important capabilities:

- Effortlessly run MLflow Projects in Kubernetes, without the hassle of dealing with docker
- Design a DAG of MLflow Projects and then execute the DAG in Kubernetes

MLflow Parallels is ideal for **complex pre-processing of AI data** and for **batch/micro-batch inferencing**. It is not suitable for distributed training or real time inferencing.

## Simple MLflow Project Use Case
- Wrap your AI code in [MLflow projects](https://mlflow.org/docs/latest/projects.html "MLflow Projects") and store in git
- Run MLflow Project in Kubernetes

[![](https://docs.mlflow-parallels.org/images/docs-front-page-image2.png?raw=true)](https://docs.mlflow-parallels.org/images/docs-front-page-image2.png?raw=true)

## Sophisticated Parallelized DAG Use Case
- Wrap your AI code in [MLflow projects](https://mlflow.org/docs/latest/projects.html "MLflow Projects") and store in git
- Define a DAG of MLflow projects in MLflow parallels using the Parallels Web UI
- Run the DAG in Kubernetes

[![](https://docs.mlflow-parallels.org/images/docs-front-page-image1.png?raw=true)](https://docs.mlflow-parallels.org/images/docs-front-page-image1.png?raw=true)

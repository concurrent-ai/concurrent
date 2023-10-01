# Deploy llama-cpp model registered as an MLflow Model

Llama2-cpp models registered as MLflow Models can be deployed in a suitable container in a configured Kubernetes cluster using **Concurrent for MLflow**

### llama-cpp Models
Concurrent for MLflow Deployment includes support for optimzation using llama.cpp. The following is an example of using llama.cpp optimization as part of the deployment

## Prereq: Obtain Llama2 model

Start by going to the following Meta website and signing up for access to the Llama2 models: [here](https://ai.meta.com/resources/models-and-libraries/llama-downloads/ "Apply for Free Llama2 License")

Once you have the license, download the GGML version of the Llama2 models from: [here](https://huggingface.co/TheBloke "Choose a Llama2 GGML model")

You can also take the pytorch version of Llama2 and convert it yourself using the tools provided by llama.cpp
## Step 1: Log Huggingface Model

In this step, we turn the GGML version of the Llama2 model *llama-2-7b-chat.ggmlv3.q2_K.bin* by TheBloke into an MLflow model

```
git clone https://github.com/jagane-infinstor/logmodel.git
cd logmodel/llama2-7b-chat-ggml
python log.py models/llama-2-7b-chat.ggmlv3.q2_K.bin

```

## Step 2: Registered MLflow Model
In this step, we register the artifact logged in step 1 as a Registered MLflow Model

Use the MLflow GUI to register the model artifact from the run in step 1, as a MLflow Registered Model. In this example, we use the name *llama2-7b-chat-ggml* and the version is *1*

## Step 3: Deploy model
We now deploy the model using the concurrent-deployment target

In the following example, the cluster name is *parallels-free* and the namespace is *nsforconcurrent*

```
mlflow deployments create --target concurrent-deployment -C kube-context=parallels-free -C kube-namespace=nsforconcurrent -C resources.requests.cpu=3000m -C resources.requests.memory=6000Mi -C resources.requests.nvidia.com/gpu=1 -C backend_type=gke -C optimizer-technology=llama.cpp --name llama.cpp-1 --model-uri models:/llama2-7b-chat-ggml/1
```

Note the following:

- Kubernetes Cluster is *parallels-free*
- Kubernetes Namespace is *nsforconcurrent*
- Requested CPU: *3000m*
- Requested Memory: *6000Mi*
- Requested Nvidia GPU: *1*
- Backend Type: *gke* or *eks*
- Optimizer Technology: llama.cpp

## Step 4: List Deployments
We can now list the newly deployed model

```
mlflow deployments list --target concurrent-deployment
```

The output is likely to be something such as
```
List of all deployments:
['docker-dind', 'mlflow-deploy-deployment-79-16903256617600000000132']
```

## Step 5: Create Endpoint
Create an endpoint for the newly created deployment
```
mlflow deployments update-endpoint -t concurrent-deployment --endpoint mlflow-deploy-deployment-79-16903256617600000000132
PluginConcurrentDeploymentClient.create_endpoint: posting {'name': 'mlflow-deploy-deployment-79-16903256617600000000132'} to https://concurrent.cws.infinstor.com/api/2.0/mlflow/parallels/create-endpoint
Endpoint mlflow-deploy-deployment-79-16903256617600000000132 is updated
```

## Step 6: Test Endpoint
Now use kubectl to list the service and its availability state:
```
kubectl -n nsforconcurrent get services
NAME                                                TYPE           CLUSTER-IP    EXTERNAL-IP     PORT(S)          AGE
docker-dind                                         ClusterIP      10.16.3.133   <none>          2375/TCP         162d
mlflow-deploy-endpoint-79-16903256617600000000132   LoadBalancer   10.16.8.3     35.222.26.238   8080:30627/TCP   41s
```
As you can see above, the mlflow deployment *mlflow-deploy-endpoint-79-16903256617600000000132* is listening on public IP *35.222.26.238* port *8080*

You can invoke it as follows:
```
curl -X POST -H "Content-Type:application/json; format=pandas-split" --data '{"columns":["role", "message"],"data":[["system", "user"], ["You are a helpful, respectful and honest assistant. Always answer as helpfully as possible, while being safe.  Your answers should not include any harmful, unethical, racist, sexist, toxic, dangerous, or illegal content. Please ensure that your responses are socially unbiased and positive in nature.", "What is python?"]]}' http://35.222.26.238:8080/invocations

```

You can expect something similar to the following:

```
{"id": "cmpl-2c513aa9-4e74-4cf2-a9de-b1b5cd75bc03", "object": "text_completion", "created": 1696132804, "model": "/root/model/data/ggml-model-q8_0.gguf", "choices": [{"text": "  Thank you for asking! Python is a high-level programming language that is widely used for various purposes, including web development, scientific computing, data analysis, artificial intelligence, and more. It is known for its simplicity, readability, and ease of use, making it a great language for beginners and experienced programmers alike.\nPython has a vast number of libraries and frameworks that enable developers to build complex applications with ease. Some popular ones include NumPy, pandas, and scikit-learn for data analysis, Django and Flask for web development, and TensorFlow and Keras for machine learning.\nWhether you're just starting out or looking to expand your skillset, Python is definitely worth checking out! \ud83d\ude0a", "index": 0, "logprobs": null, "finish_reason": "stop"}], "usage": {"prompt_tokens": 91, "completion_tokens": 154, "total_tokens": 245}}
```


# Deploy MLflow Model

MLflow Models can be deployed in a suitable container in a configured Kubernetes cluster using **Concurrent for MLflow**

## Step 1: Log Huggingface Model

In this step, we log a Huggingface sequence to sequence model as an MLflow artifact

```
from transformers import AutoTokenizer, AutoModelForCausalLM
import transformers
import torch
import mlflow

#model = "tiiuae/falcon-7b-instruct"
model = "gpt2-large"
#model = 'hf-tiny-model-private/tiny-random-BartForCausalLM'

print(f'Logging model {model}')

tokenizer = AutoTokenizer.from_pretrained(model)
pipeline = transformers.pipeline(
    "text-generation",
    model=model,
    tokenizer=tokenizer,
    torch_dtype=torch.bfloat16,
    trust_remote_code=True,
    device_map="auto",
)

with mlflow.start_run():
    mlflow.transformers.log_model(transformers_model=pipeline, artifact_path="my_pipeline")
```

## Step 2: Registered MLflow Model
In this step, we register the artifact logged in step 1 as a Registered MLflow Model

Use the MLflow GUI to register the model artifact from the run in step 1, as a MLflow Registered Model. In this example, we use the name *GPT2-Large-2* and the version is *1*

## Step 3: Deploy model
We now deploy the model using the concurrent-deployment target

In the following example, the cluster name is *parallels-free* and the namespace is *nsforconcurrent*
```
#!/bin/bash
#MODEL="models:/BartForCausalLM/1"
MODEL="models:/GPT2-Large-2/1"
mlflow deployments create --target concurrent-deployment -C kube-context=parallels-free -C kube-namespace=nsforconcurrent -C resources.requests.cpu=3000m -C resources.requests.memory=6000Mi -C resources.requests.nvidia.com/gpu=1 -C backend_type=gke --name test1 --model-uri "$MODEL"
```

## Step 4: List Deployments
We can now list the newly deployed model

```
mlflow deployments list -t concurrent-deployment
```

The output is likely to be something such as
```
$ mlflow deployments list -t concurrent-deployment
2023-07-07 22:16:39,122 - 86142 - numexpr.utils - INFO - Note: NumExpr detected 16 cores but "NUMEXPR_MAX_THREADS" not set, so enforcing safe limit of 8.
2023-07-07 22:16:39,122 - 86142 - numexpr.utils - INFO - NumExpr defaulting to 8 threads.
Forcing renewal of concurrent token
PluginConcurrentDeploymentClient.list_deployments: Calling GET url https://concurrent.cws.infinstor.com/api/2.0/mlflow/parallels/list-deployments
List of all deployments:
['docker-dind', 'mlflow-deploy-deployment-79-16887889569750000000112']
```

## Step 5: Create Endpoint
Create an endpoint for the newly created deployment
```
mlflow deployments update-endpoint -t concurrent-deployment --endpoint mlflow-deploy-deployment-79-16887889569750000000112
```

## Step 6: Test Endpoint
Now use kubectl to list the service and its availability state:
```
$ kubectl -n nsforconcurrent get services
NAME                                                TYPE           CLUSTER-IP    EXTERNAL-IP    PORT(S)          AGE
docker-dind                                         ClusterIP      10.16.3.133   <none>         2375/TCP         145d
mlflow-deploy-endpoint-79-16887889569750000000112   LoadBalancer   10.16.9.97    34.29.158.90   8080:31735/TCP   56s
```
As you can see above, the mlflow deployment *mlflow-deploy-endpoint-79-16887889569750000000112* is listening on public IP *34.29.158.90* port *8080*

You can invoke it as follows:
```
$ curl -X POST -H "Content-Type:application/json; format=pandas-split" --data '{"columns":["text", "junk"],"data":[["This is lousy weather", "j1"], ["This is great weather", "j2"]]}' http://34.29.158.90:8080/invocations
[[{"generated_text": "This is lousy weather. You've almost got to do without the sun,\" Paul told his backers in the Republican field.\n\nPaul's rivals have been touting plans to build a wall on the US border with Mexico to keep out illegal immigrants.\n"}], [{"generated_text": "This is great weather for the day-to-day operations of our store.\"\n\nSara Anderson of the American Farm Bureau says she has been stocking the market with fresh vegetables as the area recovers from its record-setting heat. This year's"}]]
```

### DeepSpeed Models
Concurrent for MLflow Deployment includes optimzation using DeepSpeed. The following is an example of using DeepSpeed optimization as part of the deployment

## Step 1: Log Huggingface Model

In this step, we turn the *google/t5-v1_1-small* Huggingface model for a *text2text-generation* pipeline into an MLflow model

```
from transformers import AutoTokenizer, AutoModelForCausalLM
import transformers
import torch
import mlflow

model = 'google/t5-v1_1-small'

print(f'Logging model {model}')

tokenizer = AutoTokenizer.from_pretrained(model)
pipeline = transformers.pipeline(
    "text2text-generation",
    model=model,
    tokenizer=tokenizer,
    torch_dtype=torch.bfloat16,
    trust_remote_code=True,
    device_map="auto",
)

with mlflow.start_run():
    mlflow.transformers.log_model(transformers_model=pipeline, artifact_path="my_pipeline")
```

## Step 2: Registered MLflow Model
In this step, we register the artifact logged in step 1 as a Registered MLflow Model

Use the MLflow GUI to register the model artifact from the run in step 1, as a MLflow Registered Model. In this example, we use the name *deepspeed-test-1* and the version is *1*

## Step 3: Deploy model
We now deploy the model using the concurrent-deployment target

In the following example, the cluster name is *parallels-free* and the namespace is *nsforconcurrent*
```
mlflow deployments create --target concurrent-deployment -C kube-context=parallels-free -C kube-namespace=nsforconcurrent -C resources.requests.cpu=3000m -C resources.requests.memory=6000Mi -C resources.requests.nvidia.com/gpu=1 -C backend_type=gke -C optimizer-technology=deepspeed --name deepspeed-test-3 --model-uri models:/deepspeed-test-1/1
```
Note the following:

- Kubernetes Cluster is *parallels-free*
- Kubernetes Namespace is *nsforconcurrent*
- Requested CPU: *3000m*
- Requested Memory: *6000Mi*
- Requested Nvidia GPU: *1*
- Backend Type: *GKE*
- Optimizer Technology: DeepSpeed

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
$ mlflow deployments update-endpoint -t concurrent-deployment --endpoint mlflow-deploy-deployment-79-16903256617600000000132
PluginConcurrentDeploymentClient.create_endpoint: posting {'name': 'mlflow-deploy-deployment-79-16903256617600000000132'} to https://concurrent.cws.infinstor.com/api/2.0/mlflow/parallels/create-endpoint
Endpoint mlflow-deploy-deployment-79-16903256617600000000132 is updated
```

## Step 6: Test Endpoint
Now use kubectl to list the service and its availability state:
```
$ kubectl -n nsforconcurrent get services
NAME                                                TYPE           CLUSTER-IP    EXTERNAL-IP     PORT(S)          AGE
docker-dind                                         ClusterIP      10.16.3.133   <none>          2375/TCP         162d
mlflow-deploy-endpoint-79-16903256617600000000132   LoadBalancer   10.16.8.3     35.222.26.238   8080:30627/TCP   41s
```
As you can see above, the mlflow deployment *mlflow-deploy-endpoint-79-16903256617600000000132* is listening on public IP *35.222.26.238* port *8080*

You can invoke it as follows:
```
$ curl -X POST -H "Content-Type:application/json; format=pandas-split" --data '{"columns":["text", "junk"],"data":[["This is lousy weather", "j1"], ["This is great weather", "j2"]]}' http://35.222.26.238:8080/invocations
[{"generated_text": "cial, and this post has acial about this this story is about"}, {"generated_text": "."}]
```



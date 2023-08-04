# Deploy MLflow Model

MLflow Models can be deployed in a suitable container in a configured Kubernetes cluster using **Concurrent for MLflow**

### DeepSpeed Models
Concurrent for MLflow Deployment includes optimzation using DeepSpeed. The following is an example of using DeepSpeed optimization as part of the deployment

## Step 1: Log Huggingface Model

In this step, we turn the *google/t5-v1_1-small* Huggingface model for a *text2text-generation* pipeline into an MLflow model

```
git clone https://github.com/jagane-infinstor/logmodel.git
cd logmodel/llama2-7b-chat-hf
python log.py

```

## Step 2: Registered MLflow Model
In this step, we register the artifact logged in step 1 as a Registered MLflow Model

Use the MLflow GUI to register the model artifact from the run in step 1, as a MLflow Registered Model. In this example, we use the name *llama2-7b-chat-hf* and the version is *1*

## Step 3: Deploy model
We now deploy the model using the concurrent-deployment target

In the following example, the cluster name is *parallels-free* and the namespace is *nsforconcurrent*
```
mlflow deployments create --target concurrent-deployment -C kube-context=parallels-free -C kube-namespace=nsforconcurrent -C resources.requests.cpu=3000m -C resources.requests.memory=6000Mi -C resources.requests.nvidia.com/gpu=1 -C backend_type=gke -C optimizer-technology=deepspeed --name deepspeed-test-5 --model-uri models:/llama2-7b-chat-hf/1
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



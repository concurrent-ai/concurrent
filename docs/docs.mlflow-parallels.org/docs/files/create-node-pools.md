# Create Node Pools

Concurrent for MLflow uses three node pools

- System Pool
- Non GPU Worker Pool
- GPU Worker Pool

## System Pool

``` 
gcloud container node-pools create concurrent-system-pods \
    --cluster concurrent-devel --disk-size 500 --num-nodes 1 \
    --machine-type e2-standard-2 \
    --node-taints=concurrent-node-type=system:NoSchedule
```

## Non GPU Worker Pool

```
gcloud container node-pools create concurrent-cpu-worker-pool \
    --cluster=concurrent-devel --disk-size=500 --num-nodes=1 \
    --enable-autoscaling --min-nodes=0 --max-nodes=1 --spot \
    --machine-type=e2-standard-4 \
    --node-taints=concurrent-node-type=worker:NoSchedule
```

## GPU Worker Pool

Before starting the GPU Worker Pool, please run the following kubectl command. This ensures that the correct nvidia driver is loaded in the nodes

```
kubectl apply -f https://raw.githubusercontent.com/GoogleCloudPlatform/container-engine-accelerators/master/nvidia-driver-installer/cos/daemonset-preloaded-latest.yaml
```
Note that the above is required for the use of CUDA 12.

```
#!/bin/bash
gcloud container node-pools create concurrent-gpu-worker \
    --cluster=concurrent-devel --disk-size=500 --num-nodes=1 \
    --enable-autoscaling --min-nodes=0 --max-nodes=1 \
    --accelerator=type=nvidia-tesla-t4,count=1 \
    --machine-type=n1-standard-4 \
    --node-taints=concurrent-node-type=worker:NoSchedule
```

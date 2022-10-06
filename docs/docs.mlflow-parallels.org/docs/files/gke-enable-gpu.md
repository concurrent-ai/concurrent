# Enable GPU

To enable GPU support in gke, run the following command from the CLI

```
kubectl apply -f https://raw.githubusercontent.com/GoogleCloudPlatform/container-engine-accelerators/master/nvidia-driver-installer/cos/daemonset-preloaded.yaml
```

Note that you must have cluster wide admin privileges when running this command

Next, using the GKE console, add a node group with nodes that include GPUs.

Finally, while designing the DAG using the *Concurrent* GUI, select a number greater than 0 for the GPU field in the node that needs a GPU. Now, this particular node will automatically be scheduled on containers that have the requisite number of GPUs.

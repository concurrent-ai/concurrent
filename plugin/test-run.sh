#!/bin/bash
#MODEL="models:/GPT2-Large/1"
MODEL="models:/BartForCausalLM/1"
mlflow deployments create --target concurrent-deployment -C kube-context=parallels-free -C kube-namespace=nsforconcurrent -C resources.requests.cpu=3000m -C resources.requests.memory=6000Mi -C resources.requests.nvidia.com/gpu=1 -C backend_type=gke --name test1 --model-uri "$MODEL"

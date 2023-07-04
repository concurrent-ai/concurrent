#!/bin/bash
#MODEL="models:/BartForCausalLM/1"
MODEL="models:/GPT2-Large-2/1"
mlflow deployments create --target concurrent-deployment -C kube-context=parallels-free -C kube-namespace=nsforconcurrent -C resources.requests.cpu=3000m -C resources.requests.memory=6000Mi -C resources.requests.nvidia.com/gpu=1 -C backend_type=gke --name test1 --model-uri "$MODEL"

# curl -X POST -H "Content-Type:application/json; format=pandas-split" --data '{"columns":["text", "junk"],"data":[["This is lousy weather", "j1"], ["This is great weather", "j2"]]}' http://127.0.0.1:8080/invocations

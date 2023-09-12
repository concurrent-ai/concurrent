# llama.cpp in a node

## Register Model

Instructions for registering a gguf format Llama2 model as an MLflow model are provided [here](https://docs.infinstor.com/files/mlflow-models-usage/ "Registering Llama2 Model as llama.cpp"){:target="\_blank"}

Register the model using the name *Llama-2-7b-chat-hf-gguf/1*

## DAG Node

### Dockerfile:

```
FROM python:3.9
# FROM nvcr.io/nvidia/pytorch:23.07-py3

RUN pip install 'transformers[torch]' \
    && python -m pip install mlflow>=2.6.0 \
    && python -m pip install azure-storage-blob \
    && python -m pip install numpy \
    && python -m pip install scipy \
    && python -m pip install pandas \
    && python -m pip install scikit-learn \
    && python -m pip install cloudpickle \
    && python -m pip install tzlocal \
    && python -m pip install infinstor_mlflow_plugin \
    && python -m pip install infinstor \
    && python -m pip install pynvml \
    && python -m pip install arnparse \
    && python -m pip install cwsearch_utils

ARG CACHEBUST=37
ARG CMAKE_ARGS=-DLLAMA_CLBLAST=ON
#ARG CMAKE_ARGS=-DLLAMA_CUBLAS=ON
ENV CMAKE_ARGS "${CMAKE_ARGS}"
ENV FORCE_CMAKE 1
ENV CUDAFLAGS "-arch=all -lcublas"
RUN python -m pip install llama-cpp-python

ARG INFINSTOR_TOKEN
ENV INFINSTOR_TOKEN $INFINSTOR_TOKEN
RUN mkdir -p /root/.infinstor
RUN echo "Token=Custom $INFINSTOR_TOKEN" > /root/.infinstor/token
ARG MLFLOW_TRACKING_URI
ENV MLFLOW_TRACKING_URI $MLFLOW_TRACKING_URI
RUN mkdir -p /root/model
RUN python -c "import mlflow; pfmodel = mlflow.pyfunc.load_model('models:/Llama-2-7b-chat-hf-gguf/1', suppress_warnings=False, dst_path='/root/model');"
```

### Node code

```

pfmodel = mlflow.pyfunc.load_model('/root/model', suppress_warnings=False)
sentence_model = pfmodel.unwrap_python_model()

pred = sentence_model.predict(df, {'n_gpu_layers': '32'})
for row in pred:
    embeddings.append(row['embedding'])

```

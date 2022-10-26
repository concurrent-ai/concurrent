# helloworld

**Concurrent for MLflow** uses code checked into git for each node in the DAG. Here are the contents of the the helloworld subdirectory of the github repo *https://github.com/concurrent-ai/concurrent-examples.git*. Here's the listing of the directory:

```
-rw-rw-r-- 1 jagane jagane  56 Oct 19 21:11 Dockerfile
-rw-rw-r-- 1 jagane jagane  33 Oct 19 21:11 helloworld.py
-rw-rw-r-- 1 jagane jagane 139 Oct 19 21:11 MLproject

```

The Dockerfile included with helloworld is a good starting point for very simple projects. helloworld.py is a single line which prints out hello world. Finally, the MLproject contains the following

```
name: docker-example

docker_env:
  image:  mlflow-parallels-example-helloworld

entry_points:
  main:
    command: "python helloworld.py"
```

Note the entry point named main - this is the command that is executed when the DAG node runs

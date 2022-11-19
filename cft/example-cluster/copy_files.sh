#!/bin/bash
aws s3 cp create-eks-for-parallels.yaml s3://docs.concurrent-ai.org/cft/example-cluster/
aws s3 cp create-k8s-role-wrapper.yaml s3://docs.concurrent-ai.org/cft/example-cluster/
aws s3 cp create-user-role-wrapper.yaml s3://docs.concurrent-ai.org/cft/example-cluster/
aws s3 cp iam-role-for-parallels.yaml s3://docs.concurrent-ai.org/cft/example-cluster/
aws s3 cp k8s-dind-service.yaml s3://docs.concurrent-ai.org/cft/example-cluster/
aws s3 cp k8s-service-role-for-parallels.yaml s3://docs.concurrent-ai.org/cft/example-cluster/
aws s3 cp quickstart-wrapper.yaml s3://docs.concurrent-ai.org/cft/example-cluster/
aws s3 cp user-role.yaml s3://docs.concurrent-ai.org/cft/example-cluster/
aws s3 cp pre-requisites/role-for-cft-qs-extension.yaml s3://docs.concurrent-ai.org/cft/pre-requisites/

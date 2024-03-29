FROM ubuntu:22.04

LABEL version="0.1"
LABEL maintainer="docker@infinstor.com"
LABEL description="Image for creating a docker image from a git tree that has a Dockerfile"

RUN apt update && DEBIAN_FRONTEND=noninteractive TZ=Etc/UTC apt-get -y install tzdata && apt install -y bash \
                   build-essential \
                   git \
                   curl \
                   ca-certificates \
                   docker.io \
                   git \
                   lxc \
                   iptables \
                   unzip \
                   buildah \
                   python3 \
                   python3-pip && \
    rm -rf /var/lib/apt/lists

RUN curl -O https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-cli-399.0.0-linux-x86_64.tar.gz && tar -xf google-cloud-cli-399.0.0-linux-x86_64.tar.gz && ./google-cloud-sdk/install.sh
ENV PATH="${PATH}:/google-cloud-sdk/bin"
RUN gcloud components install docker-credential-gcr

RUN curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip" && unzip awscliv2.zip && ./aws/install && python3 -m pip install --no-cache-dir --upgrade pip && python3 -m pip -V &&  python3 -m pip install --no-cache-dir docker mlflow boto3 kubernetes && curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" && install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl && curl --output /root/aws_signing_helper  https://rolesanywhere.amazonaws.com/releases/1.0.4/X86_64/Linux/aws_signing_helper && chmod a+x /root/aws_signing_helper

RUN python3 -m pip install --no-cache-dir --upgrade infinstor_mlflow_plugin
RUN python3 -m pip install --no-cache-dir --upgrade transformers

ADD ./kubectl /usr/local/bin/kubectl
RUN chmod +x /usr/local/bin/kubectl
ADD ./bootstrap.sh /usr/local/bin/bootstrap.sh
ADD ./Dockerfile.inference-container /usr/local/bin/Dockerfile.inference-container
ADD ./model-Dockerfile-epilogue /usr/local/bin/model-Dockerfile-epilogue
ADD ./serve_model.py /usr/local/bin/serve_model.py
ADD ./Miniconda3-py310_23.3.1-0-Linux-x86_64.sh /usr/local/bin/Miniconda3-py310_23.3.1-0-Linux-x86_64.sh
RUN chmod +x /usr/local/bin/bootstrap.sh
CMD /usr/local/bin/bootstrap.sh

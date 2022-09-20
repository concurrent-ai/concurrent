FROM ubuntu:20.04

LABEL version="0.1"
LABEL maintainer="docker@infinstor.com"
LABEL description="Image for creating a docker image from a git tree that has a Dockerfile"

RUN apt update
RUN DEBIAN_FRONTEND=noninteractive TZ=Etc/UTC apt-get -y install tzdata
RUN apt install -y bash \
                   build-essential \
                   git \
                   curl \
                   ca-certificates \
                   docker.io \
                   git \
                   lxc \
                   iptables \
                   unzip \
                   python3 \
                   python3-pip && \
    rm -rf /var/lib/apt/lists

RUN curl -O https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-cli-399.0.0-linux-x86_64.tar.gz
RUN tar -xf google-cloud-cli-399.0.0-linux-x86_64.tar.gz
RUN ./google-cloud-sdk/install.sh
ENV PATH="${PATH}:/google-cloud-sdk/bin"
RUN gcloud components install docker-credential-gcr

RUN curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
RUN unzip awscliv2.zip
RUN ./aws/install

RUN python3 -m pip install --no-cache-dir --upgrade pip
RUN python3 -m pip -V
RUN python3 -m pip install --no-cache-dir docker mlflow boto3 kubernetes

ADD ./bootstrap.sh /usr/local/bin/bootstrap.sh
RUN chmod +x /usr/local/bin/bootstrap.sh
ADD ./bootstrap-version.txt /usr/local/bin/bootstrap-version.txt
ADD ./task_launcher.py /usr/local/bin/task_launcher.py

RUN curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
RUN install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl

ARG IGNORECACHE=1
RUN echo "$IGNORECACHE"
RUN python3 -m pip install --no-cache-dir parallels_plugin

#### RUN python3 -m pip install --no-cache-dir infinstor_mlflow_plugin
# To test with a modified infinstor_mlflow_plugin without pushing to pypi,
# copy the infinstor-mlflow/plugin directory here, modify it, then
# comment out the line above and uncomment the two lines below
## ADD ./plugin /tmp/plugin
## RUN cd /tmp/plugin && python3 ./setup.py sdist bdist_wheel && pip3 install dist/infinstor_mlflow_plugin-[0-9].[0-9].[0-9]*-py3-none-any.whl

#### RUN python3 -m pip install --no-cache-dir --upgrade infinstor

RUN pip list
VOLUME /var/lib/docker
CMD /usr/local/bin/bootstrap.sh

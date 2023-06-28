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
                   python3 \
                   python3-pip && \
    rm -rf /var/lib/apt/lists

RUN curl -O https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-cli-399.0.0-linux-x86_64.tar.gz && tar -xf google-cloud-cli-399.0.0-linux-x86_64.tar.gz && ./google-cloud-sdk/install.sh
ENV PATH="${PATH}:/google-cloud-sdk/bin"
RUN gcloud components install docker-credential-gcr

RUN curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip" && unzip awscliv2.zip && ./aws/install && python3 -m pip install --no-cache-dir --upgrade pip && python3 -m pip -V &&  python3 -m pip install --no-cache-dir docker mlflow boto3 kubernetes && curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" && install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl && curl --output /root/aws_signing_helper  https://rolesanywhere.amazonaws.com/releases/1.0.4/X86_64/Linux/aws_signing_helper && chmod a+x /root/aws_signing_helper

ADD ./stub.sh /usr/local/bin/stub.sh
RUN chmod +x /usr/local/bin/stub.sh
CMD /usr/local/bin/stub.sh

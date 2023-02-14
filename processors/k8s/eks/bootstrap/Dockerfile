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

ADD ./bootstrap.sh /usr/local/bin/bootstrap.sh
RUN chmod +x /usr/local/bin/bootstrap.sh
ADD ./bootstrap-version.txt /usr/local/bin/bootstrap-version.txt
ADD ./task_launcher.py /usr/local/bin/task_launcher.py

#ARG IGNORECACHE=1

# Note: concurrent-plugin is installed by bootstrap.sh and not in this Dockerfile anymore.  So installing concurrent-plugin here is of no use.

RUN echo $(pip list)
VOLUME /var/lib/docker

# The CMD instruction has three forms:
# CMD ["executable","param1","param2"] (exec form, this is the preferred form)
# CMD ["param1","param2"] (as default parameters to ENTRYPOINT; ENTRYPOINT must be specified)
# CMD command param1 param2 (shell form)
#
# Provide defaults for an executing container. If an executable is not specified, then ENTRYPOINT must be specified as well. There can only be one CMD instruction in a Dockerfile.
# CMD [ "/bin/ls", "-l" ]
CMD /usr/local/bin/bootstrap.sh

# ENTRYPOINT has two forms: 
# The exec form, which is the preferred form: 
# ENTRYPOINT ["executable", "param1", "param2"]
# The shell form: 
# ENTRYPOINT command param1 param2
# An ENTRYPOINT allows you to configure a container that will run as an executable.
#
# Configures the container to be run as an executable;  
# ENTRYPOINT [ "/opt/app/run.sh", "--port", "8080" ]
# ENTRYPOINT [ "executable" ]
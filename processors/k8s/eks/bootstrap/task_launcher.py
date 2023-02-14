import logging
import os
import json
import base64
from typing import Dict, List, Tuple
import zlib
import subprocess
import time
from mlflow.tracking import MlflowClient
from mlflow.projects.utils import load_project, MLFLOW_DOCKER_WORKDIR_PATH
from mlflow.projects import kubernetes as kb

import docker
import docker.models.images
# Use lazy % or % formatting in logging functionspylint(logging-fstring-interpolation)
# Use lazy % or % formatting in logging functionspylint(logging-format-interpolation)
# Catching too general exception Exceptionpylint(broad-except)
#pylint: disable=logging-not-lazy, logging-fstring-interpolation, logging-format-interpolation, broad-except

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def generate_kubernetes_job_template(job_tmplate_file, namespace, run_id, image_tag,
                                     image_digest, side_car_name):
    image_uri = image_tag + "@" + image_digest
    mlflow_tracking_uri = os.environ['MLFLOW_TRACKING_URI']
    concurrent_uri = os.environ['MLFLOW_CONCURRENT_URI']
    dag_execution_id = os.getenv('DAG_EXECUTION_ID')
    periodic_run_name = os.environ.get('PERIODIC_RUN_NAME')
    periodic_run_frequency = os.getenv('PERIODIC_RUN_FREQUENCY')
    periodic_run_start_time = os.getenv('PERIODIC_RUN_START_TIME')
    periodic_run_end_time = os.getenv('PERIODIC_RUN_END_TIME')
    dag_id = os.getenv('DAGID')
    with open(job_tmplate_file, "w") as fh:
        fh.write("apiVersion: batch/v1\n")
        fh.write("kind: Job\n")
        fh.write("metadata:\n")
        fh.write("  name: \"{replaced with MLflow Project name}\"\n")
        fh.write("  namespace: {}\n".format(namespace))
        fh.write("spec:\n")
        #fh.write("  ttlSecondsAfterFinished: 600\n")
        fh.write("  backoffLimit: 0\n")
        fh.write("  template:\n")
        fh.write("    spec:\n")
        fh.write("      shareProcessNamespace: true\n")
        fh.write("      containers:\n")
        fh.write("      - name: \"{replaced with MLflow Project name}\"\n")
        fh.write("        image: \"{replaced with URI of Docker image created during Project execution}\"\n")
        fh.write("        command: [\"{replaced with MLflow Project entry point command}\"]\n")
        fh.write("        imagePullPolicy: IfNotPresent\n")
        fh.write("        resources:\n")
        fh.write("          limits:\n")
        if 'RESOURCES_LIMITS_CPU' in os.environ:
            fh.write("            cpu: \"{}\"\n".format(os.environ['RESOURCES_LIMITS_CPU']))
        if 'RESOURCES_LIMITS_MEMORY' in os.environ:
            fh.write("            memory: \"{}\"\n".format(os.environ['RESOURCES_LIMITS_MEMORY']))
        if "RESOURCES_LIMITS_HUGEPAGES" in os.environ:
            HP_SIZE, HP_VALUE = os.environ['RESOURCES_LIMITS_HUGEPAGES'].split('/')[:2]
            fh.write("            hugepages-{}: \"{}\"\n".format(HP_SIZE, HP_VALUE))
        if "RESOURCES_LIMITS_NVIDIA_COM_GPU" in os.environ:
            fh.write("            nvidia.com/gpu: {}\n".format(os.environ['RESOURCES_LIMITS_NVIDIA_COM_GPU']))
            fh.write("          requests:\n")
        if "RESOURCES_REQUESTS_CPU" in os.environ:
            fh.write("            cpu: \"{}\"\n".format(os.environ['RESOURCES_REQUESTS_CPU']))
        if "RESOURCES_REQUESTS_MEMORY" in os.environ:
            fh.write("            memory: \"{}\"\n".format(os.environ['RESOURCES_REQUESTS_MEMORY']))
        if "RESOURCES_REQUESTS_HUGEPAGES" in os.environ:
            HP_SIZE, HP_VALUE = os.environ['RESOURCES_REQUESTS_HUGEPAGES'].split('/')[:2]
            fh.write("            hugepages-{}: \"{}\"\n".format(HP_SIZE, HP_VALUE))
        if "RESOURCES_REQUESTS_NVIDIA_COM_GPU" in os.environ:
            fh.write("            nvidia.com/gpu: {}\n".format(os.environ['RESOURCES_REQUESTS_NVIDIA_COM_GPU']))
        if os.environ.get('ECR_TYPE') == "private":
            fh.write("      imagePullSecrets:\n")
            fh.write("      - name: ecr-private-key\n")

        ##Add sidecar container
        fh.write("      - name: \"{}\"\n".format(side_car_name))
        fh.write("        image: \"{}\"\n".format(image_uri))
        fh.write("        lifecycle:\n")
        fh.write("          type: Sidecar\n")
        fh.write("        command: [\"python\"]\n")
        fh.write("        args: [\"-m\", \"concurrent_plugin.infinfs.mount_service\"]\n")
        fh.write("        imagePullPolicy: IfNotPresent\n")
        fh.write("        env:\n")
        fh.write("        - name: MLFLOW_TRACKING_URI\n")
        fh.write("          value: \"{}\"\n".format(mlflow_tracking_uri))
        fh.write("        - name: MLFLOW_RUN_ID\n")
        fh.write("          value: \"{}\"\n".format(run_id))
        fh.write("        - name: MLFLOW_CONCURRENT_URI\n")
        fh.write("          value: \"{}\"\n".format(concurrent_uri))
        fh.write("        - name: DAG_EXECUTION_ID\n")
        fh.write("          value: \"{}\"\n".format(dag_execution_id))
        fh.write("        - name: DAGID\n")
        fh.write("          value: \"{}\"\n".format(dag_id))
        if periodic_run_name:
            fh.write("        - name: PERIODIC_RUN_NAME\n")
            fh.write("          value: \"{}\"\n".format(periodic_run_name))
        if periodic_run_frequency:
            fh.write("        - name: PERIODIC_RUN_FREQUENCY\n")
            fh.write("          value: \"{}\"\n".format(periodic_run_frequency))
        if periodic_run_start_time:
            fh.write("        - name: PERIODIC_RUN_START_TIME\n")
            fh.write("          value: \"{}\"\n".format(periodic_run_start_time))
        if periodic_run_end_time:
            fh.write("        - name: PERIODIC_RUN_END_TIME\n")
            fh.write("          value: \"{}\"\n".format(periodic_run_end_time))
        fh.write("        - name: MY_POD_NAME\n")
        fh.write("          valueFrom:\n")
        fh.write("            fieldRef:\n")
        fh.write("              fieldPath: metadata.name\n")
        fh.write("        - name: MY_POD_NAMESPACE\n")
        fh.write("          valueFrom:\n")
        fh.write("            fieldRef:\n")
        fh.write("              fieldPath: metadata.namespace\n")
        fh.write("        securityContext:\n")
        fh.write("          privileged: true\n")
        fh.write("          capabilities:\n")
        fh.write("            add:\n")
        fh.write("              - SYS_ADMIN\n")
        fh.write("        resources:\n")
        fh.write("          limits:\n")
        fh.write("            cpu: \"250m\"\n")
        fh.write("            memory: \"1024Mi\"\n")
        if os.environ.get('ECR_TYPE') == "private":
            fh.write("      imagePullSecrets:\n")
            fh.write("      - name: ecr-private-key\n")
        ## Sidecar config ends
        fh.write("      priorityClassName: concurrent-high-non-preempt-prio\n")
        fh.write("      restartPolicy: Never\n")


def get_side_car_container_name(run_id):
    return 'sidecar-' + run_id

def generate_backend_config_json(backend_conf_file:str, input_spec, run_id, k8s_job_template_file,
                                image_tag, image_digest):
    """
    writes the backend config json to 'backend_conf_file'.
    {backend-type: <backend_type>, repository-uri: <uri>, git-commit: <git>, run-id:<runid>, INPUT_DATA_SPEC:<spec>, IMAGE_TAG:<tag>, IMAGE_DIGEST:<digest>, kube-job-template-path:<path> }

    Args:
        backend_conf_file (str): file to write the backend config json to
        input_spec (_type_): _description_
        run_id (_type_): _description_
        k8s_job_template_file (_type_): _description_
        image_tag (_type_): _description_
        image_digest (_type_): _description_
    """
    input_spec_encoded = base64.b64encode(json.dumps(input_spec).encode('utf-8'), altchars=None).decode('utf-8')
    with open(backend_conf_file, "w") as fh:
        fh.write("{\n")
        if os.environ["BACKEND_TYPE"] == "gke":
            fh.write("  \"backend-type\": \"gke\",\n")
        elif os.environ["BACKEND_TYPE"] == "HPE":
            fh.write("  \"backend-type\": \"HPE\",\n")
        else:
            fh.write("  \"backend-type\": \"eks\",\n")

        fh.write("  \"repository-uri\": \"{}\",\n".format(os.environ['REPOSITORY_URI']))
        if "GIT_COMMIT" in os.environ:
            fh.write("  \"git-commit\": \"{}\",\n".format(os.environ['GIT_COMMIT']))
        fh.write("  \"run-id\": \"{}\",\n".format(run_id))
        fh.write("  \"INPUT_DATA_SPEC\": \"{}\",\n".format(input_spec_encoded))
        if image_tag:
            fh.write("  \"IMAGE_TAG\": \"{}\",\n".format(image_tag))
        if image_digest:
            fh.write("  \"IMAGE_DIGEST\": \"{}\",\n".format(image_digest))
        fh.write("  \"kube-job-template-path\": \"{}\"\n".format(k8s_job_template_file))
        fh.write("}\n")


def upload_logs_for_pod(run_id, pod_name, tmp_log_file, container_name=None):
    if container_name:
        get_log_cmd = ['kubectl', 'logs', pod_name, '-c', container_name]
    else:
        get_log_cmd = ['kubectl', 'logs', pod_name]
    try:
        log_content = subprocess.check_output(get_log_cmd)
        with open(tmp_log_file, "w") as fh:
            fh.write(log_content.decode('utf-8'))
    except Exception as ex:
        logger.warning("Failed to fetch logs for {}, {}: {}".format(run_id, pod_name, ex))
        return

    try:
        client = MlflowClient()
        client.log_artifact(run_id, tmp_log_file, artifact_path='.concurrent/logs')
    except Exception as ex:
        logger.warning("Failed upload logs for {}, {}: {}".format(run_id, pod_name, ex))


def fail_exit(parent_run_id):
    upload_logs_for_pod(parent_run_id, os.environ['MY_POD_NAME'], os.environ['BOOTSTRAP_LOG_FILE'])
    exit(-1)


def log_pip_requirements(base_image, run_id, build_logs):
    try:
        start_looking = False
        for l1 in list(list(build_logs)):
            line = None
            if 'stream' in l1:
                line = l1['stream']
            elif 'aux' in l1:
                line = l1['aux']
            if not line:
                continue
            if start_looking:
                pl = None
                try:
                    pl = json.loads(line)
                except Exception :
                    pl = None
                if pl:
                    reqs = ''
                    for one_entry in pl:
                        if 'name' in one_entry and 'version' in one_entry:
                            logger.info('Package=' + str(one_entry['name']) + ', version=' + str(one_entry['version']))
                            reqs = reqs + one_entry['name'] + '==' + one_entry['version'] + '\n'
                    if reqs:
                        fpath = '/tmp/requirements-' + base_image + '.txt'
                        with open(fpath, 'w') as fp:
                            fp.write(reqs)
                        client = MlflowClient()
                        client.log_artifact(run_id, fpath, artifact_path='.concurrent/logs')
                        logger.info('build_log: successfully wrote requirements.txt')
                        break
            if 'Running pip list' in line:
                start_looking = True
    except Exception as ex2:
        logger.info("Caught exception while trying to extract pip package list. Not fatal" + str(ex2))


def build_docker_image(parent_run_id, work_dir, repository_uri, base_image, git_commit):
    """
    Build a docker image containing the project in `work_dir`, using the base image.
    """
    from mlflow.projects.docker import (
        _create_docker_build_ctx,
        _PROJECT_TAR_ARCHIVE_NAME,
        _GENERATED_DOCKERFILE_NAME
    )
    # image tag for the image
    version_string = ":" + git_commit[:7] if git_commit else ""
    image_uri = repository_uri + version_string
    dockerfile = (
        "FROM {imagename}\n COPY {build_context_path}/ {workdir}\n WORKDIR {workdir}\n RUN echo 'Running pip list'\n RUN echo $(pip list --format json)"
    ).format(
        imagename=base_image,
        build_context_path=_PROJECT_TAR_ARCHIVE_NAME,
        workdir=MLFLOW_DOCKER_WORKDIR_PATH,
    )
    logger.info("Docker file:\n {}".format(dockerfile))
    build_ctx_path = _create_docker_build_ctx(work_dir, dockerfile)
    logger.info("build_ctx_path = {}".format(build_ctx_path))
    logger.info("_PROJECT_TAR_ARCHIVE_NAME = {}, _GENERATED_DOCKERFILE_NAME = {}".format(_PROJECT_TAR_ARCHIVE_NAME, _GENERATED_DOCKERFILE_NAME))
    with open(build_ctx_path, "rb") as docker_build_ctx:
        logger.info("=== Building docker image %s ===", image_uri)
        client:docker.DockerClient = docker.from_env()
        image, build_logs = client.images.build(
            tag=image_uri,
            forcerm=True,
            dockerfile=os.path.join(_PROJECT_TAR_ARCHIVE_NAME, _GENERATED_DOCKERFILE_NAME),
            fileobj=docker_build_ctx,
            custom_context=True,
            encoding="gzip"
        )
        log_pip_requirements(base_image, parent_run_id, build_logs)
    try:
        os.remove(build_ctx_path)
    except Exception:
        logger.info("Temporary docker context file %s was not deleted.", build_ctx_path)
    # tracking.MlflowClient().set_tag(run_id, MLFLOW_DOCKER_IMAGE_URI, image_uri)
    # tracking.MlflowClient().set_tag(run_id, MLFLOW_DOCKER_IMAGE_ID, image.id)
    return image


def get_docker_image(parent_run_id:str) -> Tuple[docker.models.images.Image, str]:
    """
    get the docker image that corresponds to os.environ['REPOSITORY_URI']:latest.  
    Either build the image if it doesn't exist, using Dockerfile in os.environ['MLFLOW_PROJECT_DIR'] or pull an existing image.

    Args:
        parent_run_id (str): pip requirements.txt is logged to this parent_run_id.  requirements.txt is created by parsing 'docker build' output

    Returns:
        Tuple[docker.models.images.Image, str]: returns (image, image_digest)
    """
    git_commit = os.environ.get('GIT_COMMIT')
    repository_uri = os.environ['REPOSITORY_URI']
    do_build = True
    if git_commit:
        lookup_tag = git_commit[:7]
    else:
        lookup_tag = 'latest'
    docker_client:docker.DockerClient = docker.from_env()
    try:
        image:docker.models.images.Image = docker_client.images.pull(repository_uri, tag=lookup_tag)
    except docker.errors.ImageNotFound :
        logger.info("task_launcher.get_docker_image: Docker img "
                     + repository_uri + ", tag=" + lookup_tag + " not found. Building...")
    except docker.errors.APIError as apie:
        logger.info("task_launcher.get_docker_image: Error " + str(apie)
                     + " while pulling " + repository_uri + ", tag=" + lookup_tag)
    else:
        logger.info("task_launcher.get_docker_image: image=" + str(image))
        logger.info("task_launcher.get_docker_image: Docker img found "
                     + repository_uri + ", tag=" + lookup_tag + ". Reusing...")
        image_digest = docker_client.images.get_registry_data(image.tags[0]).id
        logger.info("task_launcher.get_docker_image: image_digest=" + image_digest)
        do_build = False

    if do_build:
        logger.info("Task launcher: Building "
                     + repository_uri)
        work_dir = os.environ['MLFLOW_PROJECT_DIR']
        project = load_project(work_dir)
        logger.info('Task launcher, base image = ' + str(project.docker_env.get("image")))
        image = build_docker_image(
            parent_run_id=parent_run_id,
            work_dir=work_dir,
            repository_uri=repository_uri,
            base_image=project.docker_env.get("image"),
            git_commit=git_commit
        )
        image_digest = kb.push_image_to_registry(image.tags[0])

    return image, image_digest


def launch_mlflow_commands(cmd_list:List[Tuple[str, List[str]]]) -> Dict[str, Tuple[str, None]]:
    """
    launch the specified mlflow commands; 

    Args:
        cmd_list (List[Tuple[str, List[str]]]): List of tuples.  Each tuple is (run_id, [mlflow_command args as list])

    Returns:
        Dict[str, Tuple[str, None]]: returns a dict of run_id --> (k8s_job_name, None)
    """
    batch_size = 10
    run_job_dict = {}
    remaining = cmd_list
    while remaining:
        procs_dict = {}
        cmds_to_run = remaining[:batch_size]
        for run_id, cmd in cmds_to_run:
            # If 'env' kwarg to Popen() is not None, it must be a mapping that defines the environment variables for the new process; these are used instead of the default behavior of inheriting the current process’ environment
            proc:subprocess.Popen = subprocess.Popen(cmd, cwd=os.environ['MLFLOW_PROJECT_DIR'],
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            logger.info("Launched mlflow cmd: " + str(cmd))
            procs_dict[run_id] = (proc, None, None)
        for run_id, _ in cmds_to_run:
            proc, _, _ = procs_dict[run_id]
            stdout, stderr = proc.communicate()
            logger.info(f"launch logs for run_id {run_id}")
            if stdout:
                logger.info('STDOUT:\n{}'.format(stdout.decode('utf-8')))
            else:
                logger.info('STDOUT: None')
            if stderr:
                logger.info('STDERR:\n{}'.format(stderr.decode('utf-8')))
            else:
                logger.info('STDERR: None')
        remaining = remaining[batch_size:]
    return


def main(run_id_list, input_data_specs, parent_run_id):
    image:docker.models.images.Image; image_digest:str; 
    image, image_digest = get_docker_image(parent_run_id)

    mlflow_cmd_list = []
    for run_id, input_spec in zip(run_id_list, input_data_specs):
        k8s_job_template_file = "/tmp/kubernetes_job_template-" + run_id + ".yaml"
        if os.path.exists(k8s_job_template_file):
            os.remove(k8s_job_template_file)

        side_car_name = get_side_car_container_name(run_id)
        if 'KUBE_JOB_TEMPLATE_CONTENTS' in os.environ:
            logger.info("Using Kubernetes Job Template from environment")
            with open(k8s_job_template_file, "w") as fh:
                base64.decode(os.environ['KUBE_JOB_TEMPLATE_CONTENTS'], fh)
        else:
            logger.info("Generating Kubernetes Job Template from params")
            generate_kubernetes_job_template(k8s_job_template_file, os.environ['NAMESPACE'],
                                             run_id, image.tags[0], image_digest, side_car_name)

        k8s_backend_config_file = "/tmp/k8s-backend-config-" + run_id + ".json"
        if os.path.exists(k8s_backend_config_file):
            os.remove(k8s_backend_config_file)
        generate_backend_config_json(k8s_backend_config_file, input_spec, run_id,
                                     k8s_job_template_file, image.tags[0], image_digest)



        mlflow_cmd = ['mlflow', 'run', '--backend', 'concurrent-backend', '--backend-config', k8s_backend_config_file,
                      '.']
        if 'PROJECT_PARAMS' in os.environ:
            params = json.loads(base64.b64decode(os.getenv('PROJECT_PARAMS')).decode('utf-8'))
            for k, v in params.items():
                mlflow_cmd.append('-P')
                mlflow_cmd.append(k + '=' + v)
        mlflow_cmd_list.append((run_id, mlflow_cmd))

    launch_mlflow_commands(mlflow_cmd_list)

    time.sleep(5)
    upload_logs_for_pod(parent_run_id, os.environ['MY_POD_NAME'], os.environ['BOOTSTRAP_LOG_FILE'])


##Main
if __name__ == '__main__':
    logger.info(f"THE TASK LAUNCHER ENV: {os.environ}")
    parent_run_id = os.environ['PARENT_RUN_ID']
    ##read input specs
    with open('/root/.taskinfo/taskinfo', 'rb') as infh:
        input_spec_content = infh.read()
        run_input_spec_map = json.loads(zlib.decompress(input_spec_content).decode('utf-8'))

    run_id_list = list(run_input_spec_map.keys())
    input_data_specs = list(run_input_spec_map.values())

    logger.info("Input data specs: " + str(input_data_specs))
    logger.info("Run id list: " + str(run_id_list))
    main(run_id_list, input_data_specs, parent_run_id)
    logger.info("End")
    exit(0)

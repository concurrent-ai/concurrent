import logging
import os
import sys
import json
import base64
import subprocess
import time
import requests
from mlflow.tracking import MlflowClient
from mlflow.projects.utils import load_project, MLFLOW_DOCKER_WORKDIR_PATH
from mlflow.projects import kubernetes as kb

import docker

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def generate_kubernetes_job_template(job_tmplate_file, namespace):
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
        fh.write("      containers:\n")
        fh.write("      - name: \"{replaced with MLflow Project name}\"\n")
        fh.write("        image: \"{replaced with URI of Docker image created during Project execution}\"\n")
        fh.write("        command: [\"{replaced with MLflow Project entry point command}\"]\n")
        fh.write("        imagePullPolicy: IfNotPresent\n")
        fh.write("        securityContext:\n")
        fh.write("          privileged: true\n")
        fh.write("          capabilities:\n")
        fh.write("            add:\n")
        fh.write("              - SYS_ADMIN\n")
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
        fh.write("      restartPolicy: Never\n")


def generate_backend_config_json(backend_conf_file, input_spec, run_id, k8s_job_template_file,
                                image_tag, image_digest):
    input_spec_encoded = base64.b64encode(json.dumps(input_spec).encode('utf-8'), altchars=None).decode('utf-8')
    with open(backend_conf_file, "w") as fh:
        fh.write("{\n")
        if os.environ["BACKEND_TYPE"] == "gke":
            fh.write("  \"backend-type\": \"gke\",\n")
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


def get_mlflow_param(run_id, pname):
    client = MlflowClient()
    run = client.get_run(run_id)
    if pname in run.data.params:
        return run.data.params[pname]
    else:
        return None


def upload_logs_for_pod(run_id, pod_name, tmp_log_file):
    get_log_cmd = ['kubectl', 'logs', pod_name]
    try:
        log_content = subprocess.check_output(get_log_cmd)
        with open(tmp_log_file, "w") as fh:
            fh.write(log_content.decode('utf-8'))
    except Exception as ex:
        logger.warning("Failed to fetch logs for {}, {}: {}".format(run_id, pod_name, ex))
        return
    client = MlflowClient()
    client.log_artifact(run_id, tmp_log_file, artifact_path='.mlflow-parallels/logs')


def update_mlflow_run(run_id, status):
    client = MlflowClient()
    client.set_terminated(run_id, status)


def fail_exit(parent_run_id):
    upload_logs_for_pod(parent_run_id, os.environ['MY_POD_NAME'], os.environ['BOOTSTRAP_LOG_FILE'])
    exit(-1)

def log_describe_pod(pod_name, run_id):
    describe_file = "/tmp/describe-" + pod_name + ".txt"
    describe_cmd = ['kubectl', 'describe', 'pod', pod_name]
    try:
        desc_content = subprocess.check_output(describe_cmd)
        with open(describe_file, "w") as fh:
            fh.write(desc_content.decode('utf-8'))
    except Exception as ex:
        return
    else:
        client = MlflowClient()
        client.log_artifact(run_id, describe_file, artifact_path='.mlflow-parallels/logs')

def fetch_upload_pod_status_logs(pods_run_dict, completed_pods, success_pods):
    pods_status_cmd = ['kubectl', 'get', 'pod',
                       "-o=jsonpath={range .items[*]}{.metadata.name}{\"\\t\"}{.status.phase}{\"\\n\"}{end}"]
    try:
        pods_status = subprocess.check_output(pods_status_cmd)
    except Exception as ex:
        logger.warning("Failed to get pods status: " + str(ex))
        return

    pods_status = pods_status.decode('utf-8')
    for pod_record in pods_status.splitlines():
        pod_name, pod_phase = pod_record.split()
        if pod_name in pods_run_dict:
            pod_run_id = pods_run_dict[pod_name]
            if pod_phase == 'Pending':
                logger.info("{} is in Pending phase. Waiting".format(pod_name))
                log_describe_pod(pod_name, pod_run_id)
                upload_logs_for_pod(pod_run_id, pod_name, "/tmp/run-logs.txt")
            elif pod_phase == 'Running':
                logger.info("{} is in Running phase. Waiting".format(pod_name))
                upload_logs_for_pod(pod_run_id, pod_name, "/tmp/run-logs.txt")
            elif pod_phase == 'Succeeded':
                if pod_name not in completed_pods:
                    logger.info("{} is in Succeeded phase".format(pod_name))
                    log_describe_pod(pod_name, pod_run_id)
                    upload_logs_for_pod(pod_run_id, pod_name, "/tmp/run-logs.txt")
                    update_mlflow_run(pod_run_id, "FINISHED")
                    completed_pods.add(pod_name)
                    success_pods.add(pod_name)
            elif pod_phase == 'Failed':
                if pod_name not in completed_pods:
                    logger.info("{} is in Failed phase".format(pod_name))
                    log_describe_pod(pod_name, pod_run_id)
                    upload_logs_for_pod(pod_run_id, pod_name, "/tmp/run-logs.txt")
                    update_mlflow_run(pod_run_id, "FAILED")
                    completed_pods.add(pod_name)
            elif pod_phase == 'Unknown':
                logger.warning("{} is in Unknown phase".format(pod_name))
                log_describe_pod(pod_name, pod_run_id)
                completed_pods.add(pod_name)
    return


def get_pod_run_mapping(run_job_pod_dict):
    return {x[1]: run_id for run_id, x in run_job_pod_dict.items() if x[1] is not None}


def read_token(token_file):
    with open(token_file, 'r') as tfh:
        token_file_content = tfh.read()
        for token_line in token_file_content.splitlines():
            if token_line.startswith('Token='):
                return token_line[6:]
    return None


def launch_dag_controller():
    if 'DAG_EXECUTION_ID' not in os.environ:
        logger.info('Not a dag execution, skip dag controller')
        return
    infinstor_token = read_token('/root/.mlflow-parallels/token')
    mlflow_parallels_uri = os.environ['MLFLOW_PARALLELS_URI']
    dag_execution_id = os.environ['DAG_EXECUTION_ID']
    dagid = os.environ['DAGID']
    periodic_run_name = os.environ.get('PERIODIC_RUN_NAME')

    execute_dag_url = mlflow_parallels_uri.rstrip('/') + '/api/2.0/mlflow/parallels/execdag'
    print(execute_dag_url)
    headers = {'Content-Type': 'application/json', 'Authorization': infinstor_token}
    body = {'dagid': dagid, 'dag_execution_id': dag_execution_id, "periodic_run_name": periodic_run_name}
    response = requests.post(execute_dag_url, json=body, headers = headers)
    print("DAG Controller response: ", response)


def build_docker_image(work_dir, repository_uri, base_image, git_commit):
        """
        Build a docker image containing the project in `work_dir`, using the base image.
        """
        from mlflow.projects.docker import (
            _create_docker_build_ctx,
            _PROJECT_TAR_ARCHIVE_NAME,
            _GENERATED_DOCKERFILE_NAME
        )
        version_string = ":" + git_commit[:7] if git_commit else ""
        image_uri = repository_uri + version_string
        dockerfile = (
            "FROM {imagename}\n COPY {build_context_path}/ {workdir}\n WORKDIR {workdir}\n"
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
            client = docker.from_env()
            image, _ = client.images.build(
                tag=image_uri,
                forcerm=True,
                dockerfile=os.path.join(_PROJECT_TAR_ARCHIVE_NAME, _GENERATED_DOCKERFILE_NAME),
                fileobj=docker_build_ctx,
                custom_context=True,
                encoding="gzip",
            )
        try:
            os.remove(build_ctx_path)
        except Exception:
            logger.info("Temporary docker context file %s was not deleted.", build_ctx_path)
        # tracking.MlflowClient().set_tag(run_id, MLFLOW_DOCKER_IMAGE_URI, image_uri)
        # tracking.MlflowClient().set_tag(run_id, MLFLOW_DOCKER_IMAGE_ID, image.id)
        return image


def get_docker_image():
    git_commit = os.environ.get('GIT_COMMIT')
    repository_uri = os.environ['REPOSITORY_URI']
    do_build = True
    if git_commit:
        lookup_tag = git_commit[:7]
    else:
        lookup_tag = 'latest'
    docker_client = docker.from_env()
    try:
        image = docker_client.images.pull(repository_uri, tag=lookup_tag)
    except docker.errors.ImageNotFound as inf:
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
            work_dir=work_dir,
            repository_uri=repository_uri,
            base_image=project.docker_env.get("image"),
            git_commit=git_commit
        )
        image_digest = kb.push_image_to_registry(image.tags[0])

    return image, image_digest


def launch_mlflow_commands(cmd_list):
    batch_size = 10
    run_job_dict = {}
    remaining = cmd_list
    while remaining:
        procs_dict = {}
        cmds_to_run = remaining[:batch_size]
        for run_id, cmd in cmds_to_run:
            proc = subprocess.Popen(cmd, cwd=os.environ['MLFLOW_PROJECT_DIR'],
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
            job_name = get_mlflow_param(run_id, 'kubernetes.job_name')
            if not job_name:
                logger.error("Could not obtain job name")
                fail_exit(parent_run_id)
            logger.info("Job name for run_id {} is {}".format(run_id, job_name))
            run_job_dict[run_id] = (job_name, None)
        remaining = remaining[batch_size:]
    return run_job_dict


def main(run_id_list, input_data_specs, parent_run_id):

    image, image_digest = get_docker_image()

    mlflow_cmd_list = []
    for run_id, input_spec in zip(run_id_list, input_data_specs):
        k8s_job_template_file = "/tmp/kubernetes_job_template-" + run_id + ".yaml"
        if os.path.exists(k8s_job_template_file):
            os.remove(k8s_job_template_file)

        if 'KUBE_JOB_TEMPLATE_CONTENTS' in os.environ:
            logger.info("Using Kubernetes Job Template from environment")
            with open(k8s_job_template_file, "w") as fh:
                base64.decode(os.environ['KUBE_JOB_TEMPLATE_CONTENTS'], fh)
        else:
            logger.info("Generating Kubernetes Job Template from params")
            generate_kubernetes_job_template(k8s_job_template_file, os.environ['NAMESPACE'])

        k8s_backend_config_file = "/tmp/k8s-backend-config-" + run_id + ".json"
        if os.path.exists(k8s_backend_config_file):
            os.remove(k8s_backend_config_file)
        generate_backend_config_json(k8s_backend_config_file, input_spec, run_id,
                                     k8s_job_template_file, image.tags[0], image_digest)



        mlflow_cmd = ['mlflow', 'run', '--backend', 'parallels-backend', '--backend-config', k8s_backend_config_file,
                      '.']
        if 'PROJECT_PARAMS' in os.environ:
            params = json.loads(base64.b64decode(os.getenv('PROJECT_PARAMS')).decode('utf-8'))
            for k, v in params.items():
                mlflow_cmd.append('-P')
                mlflow_cmd.append(k + '=' + v)
        mlflow_cmd_list.append((run_id, mlflow_cmd))

    procs_dict = launch_mlflow_commands(mlflow_cmd_list)

    time.sleep(30)
    #get the pod name from the jobs
    completed_pods = set()
    success_pods = set()
    for i in range(100):
        for run_id in run_id_list:
            job_name, pod_name = procs_dict[run_id]
            if not pod_name:
                get_pod_name_cmd = ['kubectl', 'get', 'pods', '--selector=job-name=' + job_name,
                                    "--output=jsonpath={.items[*].metadata.name}"]
                try:
                    pod_name = subprocess.check_output(get_pod_name_cmd)
                    pod_name = pod_name.decode('utf-8')
                    procs_dict[run_id] = (job_name, pod_name)
                    logger.info("run_id, job name, pod name = {}, {}, {}".format(run_id, job_name, pod_name))
                except Exception as ex:
                    logger.warning("Waiting to get pod name..")
        pods_run_dict = get_pod_run_mapping(procs_dict)
        fetch_upload_pod_status_logs(pods_run_dict, completed_pods, success_pods)
        if len(completed_pods) == len(run_id_list):
            logger.info("All pods completed, exiting bootstrap")
            break
        upload_logs_for_pod(parent_run_id, os.environ['MY_POD_NAME'], os.environ['BOOTSTRAP_LOG_FILE'])
        time.sleep(10)
        launch_dag_controller()

    pods_run_dict = get_pod_run_mapping(procs_dict)
    prev_complete = len(completed_pods)
    if len(completed_pods) < len(run_id_list):
        while True:
            fetch_upload_pod_status_logs(pods_run_dict, completed_pods, success_pods)
            upload_logs_for_pod(parent_run_id, os.environ['MY_POD_NAME'], os.environ['BOOTSTRAP_LOG_FILE'])
            if len(completed_pods) > prev_complete:
                launch_dag_controller()
                prev_complete = len(completed_pods)
            if len(completed_pods) == len(run_id_list):
                logger.info("All pods completed, exiting bootstrap")
                break
            time.sleep(30)

    if len(success_pods) == len(run_id_list):
        logger.info("All tasks succeeded")
    else:
        logger.info("Some tasks failed")

    upload_logs_for_pod(parent_run_id, os.environ['MY_POD_NAME'], os.environ['BOOTSTRAP_LOG_FILE'])


##Main
if __name__ == '__main__':
    print("THE TASK LAUNCHER ENV: ", os.environ)
    parent_run_id = os.environ['PARENT_RUN_ID']
    ##read input specs
    with open('/root/.taskinfo/taskinfo') as infh:
        run_input_spec_map = json.loads(infh.read())

    run_id_list = list(run_input_spec_map.keys())
    input_data_specs = list(run_input_spec_map.values())

    logger.info("Input data specs: " + str(input_data_specs))
    logger.info("Run id list: " + str(run_id_list))
    main(run_id_list, input_data_specs, parent_run_id)
    launch_dag_controller()
    logger.info("End")
    exit(0)

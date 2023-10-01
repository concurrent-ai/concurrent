import os
from mlflow.deployments import BaseDeploymentClient, PredictionsResponse
from mlflow.exceptions import MlflowException
from concurrent_plugin.login import get_conf, get_token, get_token_file_obj, get_env_var
import requests
from requests.exceptions import HTTPError
import logging
import json
from mlflow.tracking import fluent
from mlflow import tracking

_logger = logging.getLogger(__name__)

f_endpoint_name = "concurrent_deployment"

def run_local(target, name, model_uri, flavor=None, config=None):  # pylint: disable=unused-argument
    """
    .. Note::
        This function is kept here only for documentation purpose and not implementing the
        actual feature. It should be implemented in the plugin's top level namescope and should
        be callable with ``plugin_module.run_local``

    Deploys the specified model locally, for testing. This function should be defined
    within the plugin module. Also note that this function has a signature which is very
    similar to :py:meth:`BaseDeploymentClient.create_deployment` since both does logically
    similar operation.

    :param target: Which target to use. This information is used to call the appropriate plugin
    :param name:  Unique name to use for deployment. If another deployment exists with the same
                     name, create_deployment will raise a
                     :py:class:`mlflow.exceptions.MlflowException`
    :param model_uri: URI of model to deploy
    :param flavor: (optional) Model flavor to deploy. If unspecified, default flavor is chosen.
    :param config: (optional) Dict containing updated target-specific config for the deployment
    :return: None
    """
    raise NotImplementedError(
        "This function should be implemented in the deployment plugin. It is "
        "kept here only for documentation purpose and shouldn't be used in "
        "your application"
    )


def target_help():
    """
    .. Note::
        This function is kept here only for documentation purpose and not implementing the
        actual feature. It should be implemented in the plugin's top level namescope and should
        be callable with ``plugin_module.target_help``

    Return a string containing detailed documentation on the current deployment target, to be
    displayed when users invoke the ``mlflow deployments help -t <target-name>`` CLI. This
    method should be defined within the module specified by the plugin author.
    The string should contain:

    * An explanation of target-specific fields in the ``config`` passed to ``create_deployment``,
      ``update_deployment``
    * How to specify a ``target_uri`` (e.g. for AWS SageMaker, ``target_uri`` have a scheme of
      "sagemaker:/<aws-cli-profile-name>", where aws-cli-profile-name is the name of an AWS
      CLI profile https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-profiles.html)
    * Any other target-specific details.

    """
    raise NotImplementedError(
        "This function should be implemented in the deployment plugin. It is "
        "kept here only for documentation purpose and shouldn't be used in "
        "your application"
    )

class PluginConcurrentDeploymentClient(BaseDeploymentClient):
    def create_deployment(self, name, model_uri, flavor=None, config=None, endpoint=None):
        print(f"PluginConcurrentDeploymentClient.create_deployment: name={name}, model_uri={model_uri}, flavor={flavor}, config={config}, endpoint={endpoint}")
        if not config:
            raise RuntimeError("Config must be provided")
        if not os.environ.get('MLFLOW_EXPERIMENT_ID'):
            raise RuntimeError("Please sent environment variable MLFLOW_EXPERIMENT_ID and run again")

        existing_run = fluent.active_run()
        if existing_run:
            run_id = existing_run.info.run_id
            print(f"PluginConcurrentDeploymentClient.create_deployment: using currently active run_id {run_id}")
        else:
            active_run = tracking.MlflowClient().create_run(experiment_id=os.environ['MLFLOW_EXPERIMENT_ID'])
            run_id = active_run.info.run_id
            print(f"PluginConcurrentDeploymentClient.create_deployment: created new run_id {run_id}")

        body = {}
        body['model_uri'] = model_uri
        body['run_id'] = run_id
        body['MLFLOW_TRACKING_URI'] = os.environ['MLFLOW_TRACKING_URI']
        body['experiment_id'] = os.environ['MLFLOW_EXPERIMENT_ID']
        body['MLFLOW_CONCURRENT_URI'] = os.environ['MLFLOW_CONCURRENT_URI']
        body['backend_type'] = config['backend_type']
        if 'kube-job-template-path' in config:
            _logger.info('Using kubernetes job template file ' + config['kube-job-template-path'])
            body['kube_job_template_contents'] = base64.b64encode(
                    open(config.get('kube-job-template-path'), "r").read().encode('utf-8')).decode('utf-8')
            with open(config.get('kube-job-template-path'), "r") as yf:
                yml = yaml.safe_load(yf)
            _logger.info(f"contents of {config.get('kube-job-template-path')} = {yml}")
            if 'metadata' in yml and 'namespace' in yml['metadata']:
                body['namespace'] = yml['metadata']['namespace']
                _logger.info('namespace obtained from job template: ' + body['namespace'])
                if 'kube-namespace' in config:
                    if body['namespace'] != config['kube-namespace']:
                        _logger.info('Error. mismatch between namespace in backend configuration and job template')
                        raise RuntimeError('Error. mismatch between namespace in backend configuration and job template')
            else:
                if 'kube-namespace' in config:
                    body['namespace'] = config['kube-namespace']
                    _logger.info('namespace obtained from backend configuration: ' + body['namespace'])
                else:
                    body['namespace'] = 'default'
        else:
            _logger.info('Using parameters provided in backend configuration to generate a kubernetes job template')
            if "resources.limits.cpu" in config:
                body['resources.limits.cpu'] = config['resources.limits.cpu']
            if "resources.limits.memory" in config:
                body['resources.limits.memory'] = config['resources.limits.memory']
            if "resources.limits.hugepages" in config:
                body['resources.limits.hugepages'] = config['resources.limits.hugepages']
            if "resources.limits.nvidia.com/gpu" in config:
                body['resources.limits.nvidia.com/gpu'] = config['resources.limits.nvidia.com/gpu']
            if "resources.requests.cpu" in config:
                body['resources.requests.cpu'] = config['resources.requests.cpu']
            if "resources.requests.memory" in config:
                body['resources.requests.memory'] = config['resources.requests.memory']
            if "resources.requests.hugepages" in config:
                body['resources.requests.hugepages'] = config['resources.requests.hugepages']
            if "resources.requests.nvidia.com/gpu" in config:
                body['resources.requests.nvidia.com/gpu'] = config['resources.requests.nvidia.com/gpu']
            if 'kube-namespace' in config:
                body['namespace'] = config['kube-namespace']
            else:
                body['namespace'] = 'default'
            if "optimizer-technology" in config:
                body['optimizer-technology'] = config['optimizer-technology']
        kube_context = config.get('kube-context')
        if kube_context:
            body['kube_context'] = kube_context

        cognito_client_id, _, _, _, region = get_conf()
        token = get_token(cognito_client_id, region, True)

        headers = {
                'Content-Type': 'application/x-amz-json-1.1',
                'Authorization' : 'Bearer ' + token
                }
        url = get_env_var().rstrip('/') + '/api/2.0/mlflow/parallels/deploy-model'
        print(f"PluginConcurrentDeploymentClient.create_deployment: posting {body} to {url}")
        try:
            response = requests.post(url, data=json.dumps(body), headers=headers)
            response.raise_for_status()
        except HTTPError as http_err:
            _logger.info(f'HTTP error occurred: {http_err}')
            raise
        except Exception as err:
            _logger.info(f'Other error occurred: {err}')
            raise
        return {"name": f"concurrent-deployment-{run_id}", "flavor": "transformers"}

    def delete_deployment(self, name, config=None, endpoint=None):
        print(f"PluginConcurrentDeploymentClient.delete_deployment: name={name}, config={config}, endpoint={endpoint}")
        if config and config.get("raiseError") == "True":
            raise RuntimeError("Error requested")
        return None

    def update_deployment(self, name, model_uri=None, flavor=None, config=None, endpoint=None):
        print(f"PluginConcurrentDeploymentClient.update_deployment: name={name}, model_uri={model_uri}, config={config}, endpoint={endpoint}")
        return {"flavor": flavor}

    def list_deployments(self, endpoint=None):
        if os.environ.get("raiseError") == "True":
            raise RuntimeError("Error requested")
        cognito_client_id, _, _, _, region = get_conf()
        token = get_token(cognito_client_id, region, True)

        headers = {
                'Content-Type': 'application/x-amz-json-1.1',
                'Authorization' : 'Bearer ' + token
                }
        url = get_env_var().rstrip('/') + '/api/2.0/mlflow/parallels/list-deployments'
        print(f"PluginConcurrentDeploymentClient.list_deployments: Calling GET url {url}")
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            jr = json.loads(response.text)
            #print(jr)
        except HTTPError as http_err:
            _logger.info(f'HTTP error occurred: {http_err}')
            raise
        except Exception as err:
            _logger.info(f'Other error occurred: {err}')
            raise
        rv = []
        for one in jr['deployments']:
            rv.append(one['name'])
        return rv

    def get_deployment(self, name, endpoint=None):
        print(f"PluginConcurrentDeploymentClient.get_deployment: name={name}, endpoint={endpoint}")
        return {"key1": "val1", "key2": "val2"}

    def predict(self, deployment_name=None, inputs=None, endpoint=None):
        print(f"PluginConcurrentDeploymentClient.predict: deployment_name={deployment_name}, inputs={inputs}, endpoint={endpoint}")
        return PredictionsResponse.from_json('{"predictions": [1,2,3]}')

    def explain(self, deployment_name=None, df=None, endpoint=None):
        print(f"PluginConcurrentDeploymentClient.explain: deployment_name={deployment_name}, df={df}, endpoint={endpoint}")
        return "1"

    def create_endpoint(self, name, config=None):
        print(f"PluginConcurrentDeploymentClient.create_endpoint: name={name}, config={config}")
        if not name.startswith('mlflow-deploy-deployment-'):
            raise RuntimeError(f"Error: incorrect endpont. should be of format mlflow-deploy-deployment-<run-id>")
        run_id = name[len('mlflow-deploy-deployment-'):]
        if config and config.get("raiseError") == "True":
            raise RuntimeError("Error requested")
        cognito_client_id, _, _, _, region = get_conf()
        token = get_token(cognito_client_id, region, True)

        body = {'name': name}
        headers = {
                'Content-Type': 'application/x-amz-json-1.1',
                'Authorization' : 'Bearer ' + token
                }
        url = get_env_var().rstrip('/') + '/api/2.0/mlflow/parallels/create-endpoint'
        print(f"PluginConcurrentDeploymentClient.create_endpoint: posting {body} to {url}")
        try:
            response = requests.post(url, data=json.dumps(body), headers=headers)
            response.raise_for_status()
        except HTTPError as http_err:
            _logger.info(f'HTTP error occurred: {http_err}')
            raise
        except Exception as err:
            _logger.info(f'Other error occurred: {err}')
            raise
        return {"name": f"concurrent-endpoint-{run_id}", "flavor": "transformers"}

    def update_endpoint(self, endpoint, config=None):
        print(f"PluginConcurrentDeploymentClient.update_endpoint: endpoint={endpoint}, config={config}")
        if not endpoint.startswith('mlflow-deploy-deployment-'):
            raise RuntimeError(f"Error: incorrect endpont. should be of format mlflow-deploy-deployment-<run-id>")
        run_id = endpoint[len('mlflow-deploy-deployment-'):]
        if config and config.get("raiseError") == "True":
            raise RuntimeError("Error requested")
        cognito_client_id, _, _, _, region = get_conf()
        token = get_token(cognito_client_id, region, True)

        body = {'name': endpoint}
        headers = {
                'Content-Type': 'application/x-amz-json-1.1',
                'Authorization' : 'Bearer ' + token
                }
        url = get_env_var().rstrip('/') + '/api/2.0/mlflow/parallels/create-endpoint'
        print(f"PluginConcurrentDeploymentClient.create_endpoint: posting {body} to {url}")
        try:
            response = requests.post(url, data=json.dumps(body), headers=headers)
            response.raise_for_status()
        except HTTPError as http_err:
            _logger.info(f'HTTP error occurred: {http_err}')
            raise
        except Exception as err:
            _logger.info(f'Other error occurred: {err}')
            raise
        return {"name": f"concurrent-endpoint-{run_id}", "flavor": "transformers"}
        return None

    def delete_endpoint(self, endpoint):
        print(f"PluginConcurrentDeploymentClient.delete_endpoint: endpoint={endpoint}")
        return None

    def list_endpoints(self):
        print(f"PluginConcurrentDeploymentClient.list_endpoints")
        return [{"name": f_endpoint_name}]

    def get_endpoint(self, endpoint):
        print(f"PluginConcurrentDeploymentClient.get_endpoint: endpoint={endpoint}")
        return {"name": f_endpoint_name}

    def run_local(target, name, model_uri, flavor=None, config=None):  # pylint: disable=unused-argument
        print(f"PluginConcurrentDeploymentClient.run_local: name={name}, model_uri={model_uri}, flavor={flavor}, config={config}")
        return

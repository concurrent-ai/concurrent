from setuptools import setup, find_packages


setup(
    name="concurrent-plugin",
    version="0.5.20",
    description="Plugin for Concurrent for MLFlow",
    packages=find_packages(),
    # Require MLflow as a dependency of the plugin, so that plugin users can simply install
    # the plugin & then immediately use it with MLflow
    install_requires=["mlflow >= 1.21.0 ", "jsons", "kubernetes", "dpath", "traceback-with-variables"],
    entry_points={
        # Define a MLflow Project Backend plugin called 'concurrent-backend'
        "mlflow.project_backend":
            "concurrent-backend=concurrent_plugin.concurrent_backend:PluginConcurrentProjectBackend",
        "mlflow.deployments": "concurrent-deployment=concurrent_plugin.concurrent_deployment",
        # entry point for concurrent login command
        'console_scripts': [
            'login_concurrent = concurrent_plugin.login:login',
        ],                
    },
)

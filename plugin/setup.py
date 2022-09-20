from setuptools import setup, find_packages


setup(
    name="parallels-plugin",
    version="0.3.6",
    description="Plugin for MLflow Parallels",
    packages=find_packages(),
    # Require MLflow as a dependency of the plugin, so that plugin users can simply install
    # the plugin & then immediately use it with MLflow
    install_requires=["mlflow >= 1.21.0 ", "jsons", "kubernetes"],
    entry_points={
        # Define a MLflow Project Backend plugin called 'parallels-backend'
        "mlflow.project_backend":
            "parallels-backend=parallels_plugin.parallels_backend:PluginParallelsProjectBackend",
        # entry point for infinstor login command
        'console_scripts': [
            'login_mlflow_parallels = parallels_plugin.login:login',
        ],                
    },
)

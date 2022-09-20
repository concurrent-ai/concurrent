#!/usr/bin/env python3

##################
# https://sites.google.com/infinstor.com/engineering/mlops-platform/publishing-to-infinstordist
####################

# https://amoffat.github.io/sh/sections/faq.html#how-do-i-see-the-commands-sh-is-running
#
# if _fg=True is used in 'sh', logging for 'sh' does not work
import logging
from typing import Tuple
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(process)d - %(name)s - %(levelname)s - %(message)s", )

import os
import sh
import yaml
import argparse

# pylint: disable=logging-fstring-interpolation

argparser:argparse.ArgumentParser=argparse.ArgumentParser()

argparser.add_argument("--parallels-lambda-version")
argparser.add_argument("--parallels-ui-version")
argparser.add_argument("--parallels-cft-version")

#args_cmdline = ["--mlflow_lambda_version", "2.1.32"]
#args_cmdline = ["--dashboard_lambda_version", "2.0.20"]
# mlflowui 2.0.7, 2.0.8
# root stack 2.3.75
args:argparse.Namespace = argparser.parse_args() #args_cmdline)

# check if correct directories exist
def check_if_source_dirs_exist(component_enabled:str, component_dirname):
    """
    check if the source directory exists for the component to be built.  If not, exit..
    """
    if component_enabled and not os.path.isdir(component_dirname): 
        logging.info(f"can't find directory {component_dirname} to build component {component_dirname} with version {component_enabled}.  Setup the directory and try again..")
        exit(1)

check_if_source_dirs_exist(args.parallels_lambda_version, "./mlflow-parallels" )
check_if_source_dirs_exist(args.parallels_ui_version, "./mlflow-noproxy")
check_if_source_dirs_exist(args.parallels_cft_version, "./mlflow-parallels")

def _get_versions_from_parallels_yaml(parallels_yaml_template_fname:str) -> Tuple[str,str,str]:
    """returns the versions of the components specified in mlflow-parallels-cft.yaml. see below
    
    Args:
        infin_yaml_template_fname (str): template filename

    Returns:
        [tuple]: returns the tuple (l_parallels_yaml_parallels_cft_version, l_parallels_yaml_parallels_lambda_version, l_parallels_yaml_parallels_ui_version) from mlflow-parallels-cft.yaml
    """

    with open(parallels_yaml_template_fname, "r") as infin_yaml_template:
        # ConstructorError: could not determine a constructor for the tag '!Equals'; fix: https://github.com/yaml/pyyaml/issues/266
        parallels_yaml_template_dict:dict = yaml.load(infin_yaml_template, Loader=yaml.BaseLoader)
        l_parallels_yaml_cft_version:str = parallels_yaml_template_dict['Parameters']['ParallelsCftVersion']['Default']; logging.info(f"{parallels_yaml_template_fname}: current parallels_cft_version = {l_parallels_yaml_cft_version}")
        l_parallels_yaml_parallels_lambda_version:str    = parallels_yaml_template_dict['Parameters']['MlflowParallelsLambdaVersion']['Default']; logging.info(f"{parallels_yaml_template_fname}: current parallels_lambda_version = {l_parallels_yaml_parallels_lambda_version}")
        l_parallels_yaml_parallels_ui_version:str = parallels_yaml_template_dict['Parameters']['MlflowParallelsUiVersion']['Default']; logging.info(f"{parallels_yaml_template_fname}: current parallels_ui_version = {l_parallels_yaml_parallels_ui_version}")
        
    return (l_parallels_yaml_cft_version, l_parallels_yaml_parallels_lambda_version, l_parallels_yaml_parallels_ui_version)

parallels_yaml_cft_version, parallels_yaml_parallels_lambda_version, parallels_yaml_parallels_ui_version = _get_versions_from_parallels_yaml('mlflow-parallels/cft/mlflow-parallels-cft.yaml')
logging.info(f"Current versions in mlflow-parallels-cft.yaml before building: parallels_yaml_cft_version={parallels_yaml_cft_version}, parallels_yaml_parallels_lambda_version={parallels_yaml_parallels_lambda_version}, parallels_yaml_parallels_ui_version={parallels_yaml_parallels_ui_version}")

# https://amoffat.github.io/sh/sections/default_arguments.html: Many times, you want to override the default arguments of all commands launched through sh.
#
# setup 'sh' to unbuffered mode to see stdout and stderr well: https://amoffat.github.io/sh/sections/faq.html#how-do-i-run-a-command-and-connect-it-to-sys-stdout-and-sys-stdin
# this didn't work: https://amoffat.github.io/sh/sections/special_arguments.html#out-bufsize 
#
# if _fg=True is used, logging of commands that 'sh' is running does not work: https://amoffat.github.io/sh/sections/faq.html#how-do-i-see-the-commands-sh-is-running
sh2 = sh(_fg=True)   # pylint: disable=not-callable
def shcmd(*cmdarg, **kwarg):
    logging.info(f"Running command: {cmdarg} with kwarg={kwarg}")
    cmd = sh2.Command(cmdarg[0])
    cmd(*cmdarg[1:], _fg=True, **kwarg)

parallels_aws_credentials_check:bool = None
def check_parallels_aws_credentials():
    global parallels_aws_credentials_check
    if not parallels_aws_credentials_check:
        try:
            shcmd("aws", "s3", "ls", "s3://parallelsdist/")
        except Exception as e:
            logging.error("Unable to access bucket s3://parallelsdist.  setup ~/.aws/credenitals's default profile to point to mlflow-parallels AWS account and try again..",exc_info=e)
            exit(1)
    
    parallels_aws_credentials_check = True

def _check_and_tag_git_code(repo_name:str, version_tag:str):
    """
    check with user and tag the specified git_repo with the specified version tag

    Args:
        repo_name (str): _description_
        version_tag (str): _description_
    """    
    shcmd("git", "status")
    
    l_choice:str = ""
    while not ( l_choice == "no" or l_choice == "with_tag" or l_choice == "without_tag"):
        l_choice = input(f"""
**** About to do a 'git tag' with version {version_tag}:  Check if the right branch is setup for {repo_name}.git. Enter
    'no' (exits this build) or 
    'with_tag' (do a 'git tag' and continue building.  Before responding, ensure that all changes in this git repo are committed and pushed) or 
    'without_tag' (continue building without doing a 'git tag') ? """)
    if l_choice == "no" or not l_choice in ('with_tag', 'without_tag'): exit(1)
        
    # git tag 2.1.2 (Don't use v2.1.2, use plain 2.1.2)    # 
    # git push origin 2.1.2
    if l_choice == "with_tag": 
        shcmd("git", "tag", version_tag)
        shcmd("git", "push", "origin", version_tag)

def _show_git_log_check_if_build(git_repo_dir:str, sub_path:str, last_version:str) -> str:
    """
        returns if the specified component must be built or not built, based on user response.  returns the "version" to use for building this component or None if not to build
    """
    
    with sh2.pushd(git_repo_dir):
        shcmd("git", "status")
        shcmd("git", "--no-pager", "log", "--graph", "-15",  "--decorate", "--source", "--date=local", '--format=format:"%h %d %an  %ai %s"')
        
        l_choice:str = input(f"""
**** build component {git_repo_dir}/{sub_path} (last_version from mlflow-parallels-cft.yaml={last_version})? enter
    Enter version_number to build or 'no' to skip building this component: """)
        return l_choice if not l_choice == "no" else None

# get the version specified in the command line
parallels_lambda_version = args.parallels_lambda_version
# if not specified in the command line, get from the user
if not parallels_lambda_version: parallels_lambda_version = _show_git_log_check_if_build("mlflow-parallels", "server/aws (parallels lambda)", parallels_yaml_parallels_lambda_version)
# if we need to publish mlflow lambda
if parallels_lambda_version:
    # pushd cd infinstor-mlflow/server
    with sh2.pushd("mlflow-parallels"):
        logging.info(f'****** building {os.getcwd()}')
        
        # Setup ~/.aws/credentials with credentials for infinstordist
        check_parallels_aws_credentials()
        
        # only for the first time: to setup the conda environment
        choice:str = input("\n**** Do you want to build python layer for parallels lambdas? yes/no ?")
        if choice == "yes": 
            shcmd("bash", "-c", "(cd server/aws; ./scripts/create-layer.sh)")
        #else:
            ## delete stale 'package' directory from earlier run, if it exists, since we have decided not to update the lambda layer
            # shcmd("bash", "-c", "(cd server; [ -d './package' ] && rm -rf ./package)")

        # (cd infinstor-mlflow/server; ./scripts/build-and-deploy.sh service.infinstordist.com)
        shcmd("bash", "-c", "(cd server/aws; export AWS_PROFILE=isstage10_root; scripts/build-and-deploy-isstage10.com; unset AWS_PROFILE; )")

        # You will see a message such as:
        # Initiating deployment
        # =====================
        # Uploading to mlflow-server/5a1f90e5626e259b5bc74cb66a9b0a87  119076 / 119076.0  (100.00%)
        # Uploading to mlflow-server/2fe1d0fb29bfdb9bbc59657ce6049b04.template  7850 / 7850.0  (100.00%)
        # Ignore the warning 'WARNING: Update of ServiceConf table did not go well' at the end of the build
        # Copy the template file, e.g.
        # aws s3 cp s3://infinstor-service-jars-service.infinstordist.com/mlflow-server/2fe1d0fb29bfdb9bbc59657ce6049b04.template  /tmp
        # Rename this file to /tmp/template.yaml
        s3_template_yaml:str = input("\n**** Enter s3 path fragment, from output above, for SAM template.yaml similar to mlflow-parallels-server/2fe1d0fb29bfdb9bbc59657ce6049b04.template: ")
        shcmd("aws", "s3", "cp",  f"s3://scratch-bucket-xyzzy-2/{s3_template_yaml}",  "/tmp/template.yaml")       
        input(f"copied {s3_template_yaml} to /tmp/template.yaml..: press any key to continue..")

        _check_and_tag_git_code('mlflow-parallels', parallels_lambda_version)
        
        choice:str = input(f"""
**** Sign into the aws console (https://console.aws.amazon.com) as mlflow-parallels@infinstor.com and browse to 'Serverless Application Repository'
**** Choose mlflow-parallels-lambda and click on 'Publish new version'
**** Enter {parallels_lambda_version} for the 'Semantic Version'.  
**** Specify 'https://mlflow-parallels.org' for the source code URL.
**** Upload /tmp/template.yaml for SAM template, then hit 'Publish Version'
**** 
**** publish this application in multiple AWS regions if needed (us-east-1 and ap-south-1 say)
**** 
**** After publishing, enter yes to continue or no to abort: yes/no? """)
        if not choice == "yes": exit(1)

        # don't need to edit the version manually.  we generate it further below.
        # choice:str = input(f"""
# **** edit parallels CFT (mlflow-parallels/cft/mlflow-parallels-cft.yaml) to specify MLflow lamba version as {parallels_lambda_version}.  
# **** Look for the entry 'Parameters/MlflowParallelsLambdaVersion/Default' and 'Parameters/MlflowParallelsLambdaVersion/AllowedValues' update it to {parallels_lambda_version}
# **** 
# **** continue: yes/no? """)  
        # if not choice == "yes": exit(1)
else:
    # use the last version specified in mlflow-parallels-cft.yaml since we did not build a new version above
    parallels_lambda_version = parallels_yaml_parallels_lambda_version
    logging.info(f'Using last known version of parallels lambda from mlflow-parallels-cft.yaml: {parallels_lambda_version}')
    
# get the version specified in the command line
parallels_ui_version = args.parallels_ui_version
# if not specified in the command line, get from the user
if not parallels_ui_version: parallels_ui_version = _show_git_log_check_if_build("mlflow-noproxy", "  (mlflow-noproxy-parallels-ui)", parallels_yaml_parallels_ui_version)
if parallels_ui_version:
    check_parallels_aws_credentials()

    with sh2.pushd("mlflow-noproxy"):
        logging.info(f'****** building {os.getcwd()}')

        shcmd("bash", "-c", f"./scripts/build-and-copy-mlflow-noproxy-parallels.sh {parallels_ui_version}")

        _check_and_tag_git_code("mlflow-noproxy", f'mlflow-noproxy-parallels-ui-{parallels_ui_version}')        

    # seeing error: could not determine a constructor for the tag '!Equals' when using pyyaml.unsafe_load('mlflow-parallels-cft.yaml'). so edit manually for now.
    # could be solved using below, but need to do both 'Loader' and 'Dumper' to handle these cloudformation tags with '!'
    # see https://death.andgravity.com/any-yaml.  
    # see https://death.andgravity.com/yaml-unknown-tag
    #
    # don't need to edit the version manually.  we generate it further below.
    # choice:str = input(f"""**** Edit mlflow-parallels/cft/mlflow-parallels-cft.yaml and update Parameters/MlflowParallelsUiVersion/Default and Parameters/MlflowParallelsUiVersion/AllowedValues to the new version {parallels_ui_version}.. After editing, enter yes to continue..  continue: yes/no? """)  
    # if not choice == "yes": exit(1)
else:
    # use the last version specified in mlflow-parallels-cft.yaml since we did not build a new version above
    parallels_ui_version = parallels_yaml_parallels_ui_version
    logging.info(f'Using last known version of parallels UI from mlflow-parallels-cft.yaml: {parallels_ui_version}')

# get the version specified in the command line
parallels_cft_version = args.parallels_cft_version
# if not specified in the command line, get from the user
if not parallels_cft_version: parallels_cft_version = _show_git_log_check_if_build("mlflow-parallels", "cft (parallels-cft)", parallels_yaml_cft_version)
if parallels_cft_version:
    # Finally, update the root stack CFT version (the root stack version must be updated for updates to any of the nested stacks)
    # This is accomplished by running './create-new-root-stack-version.sh 2.1.12'
    # Note that the root stack version is different from the nested stack versions, which were set above..
    with sh2.pushd("mlflow-parallels"):
        logging.info(f'****** buildling {os.getcwd()}')
        
        check_parallels_aws_credentials()
        
        # Run mlflow-parallels/cft/create-new-root-stack-version.sh from the cft dir e.g.
        # ./create-new-root-stack-version.sh 2.2.13
        # This will generate a infinstor.yaml from mlflow-parallels-cft.yaml, create a git tag 2.2.13, and copy the yaml/json up to the s3 bucket
        # Now, you can create a stack from 2.2.13 and the correct json/yaml files will be pulled down from the s3 bucket.
        shcmd("bash", "-c", f"(cd cft; ./create-new-parallels-cft-version.sh {parallels_cft_version} {parallels_lambda_version} {parallels_ui_version}; )")

        # committing and tagging needs to happen after the new CFT version is created since we also need to check the generated mlflow-parallels-cft.yaml file.
        choice:str = input(f"""
**** do a 'git commit' of needed files in mlflow-parallels.git.  This is to commit the modified mlflow-parallels/cft/mlflow-parallels-cft.yaml and other files. 
**** use this git commit message: parallels cft={parallels_cft_version} parallels lambda={parallels_lambda_version} mlflow-noproxy-parallels-ui={parallels_ui_version}.  
**** Press any key after doing this 'git commit': """)  
        
        # Edit any of the json/yaml files for the root or substacks
        # Check it in (unfortunately, this is not testable without checking in)
        _check_and_tag_git_code("mlflow-parallels", parallels_cft_version)
        


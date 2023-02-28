
from contextlib import redirect_stdout
import io
import os
import logging
import sys
import subprocess

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def respond(err, res=None):
    return {
        'statusCode': '400' if err else '200',
        'body': str(err) if err else res,
        'headers': {
            'Content-Type': 'text/html',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': '*',
            'Access-Control-Allow-Methods': '*',
            'Access-Control-Allow-Credentials': '*'
        },
    }


def get_lambda_configuration(event, context):
    logger.info('## ENVIRONMENT VARIABLES')
    logger.info(os.environ)
    logger.info('## EVENT')
    logger.info(event)
    # logger.info("Received event: " + json.dumps(event, indent=2))

    operation = event['httpMethod']
    if (operation != 'GET'):
        return respond(ValueError('Unsupported method ' + str(operation)))

    res:str = ""
    res += f"""<p><pre>
sys.version={sys.version}
sys.path={sys.path}
sys.argv={sys.argv}
sys.executable={sys.executable}
</pre>
"""
    
    # return requirements.txt; /var/task/ has lambda code; /opt/python has python lambda layer content
    with open('/opt/python/requirements.txt', 'r') as f:
        res += f"""
<h1> requirements.txt </h1>
<p> <pre> {f.read()} </pre>"""
    
    opt_python_paths:list = [pythonpath for pythonpath in sys.path if pythonpath.startswith("/opt/python")]
    for opt_python_path in opt_python_paths:
        res += log_directory_listing(opt_python_path)
        res += log_directory_listing(f"{opt_python_path}/pipdeptree")

    # (infinstor) dev@vmi504080:c_r: ~/dev/infinstor/infinstor-mlflow/server $ ll package/python/pipdeptree/
    # total 56
    # drwxrwxr-x   2 dev dev  4096 Oct 13 18:57 ./
    # drwxrwxr-x 155 dev dev 12288 Oct 13 18:57 ../
    # -rw-rw-r--   1 dev dev 30651 Oct 13 18:57 __init__.py
    # -rw-rw-r--   1 dev dev    89 Oct 13 18:57 __main__.py
    # -rw-rw-r--   1 dev dev   176 Oct 13 18:57 version.py
    #
    c_proc:subprocess.CompletedProcess = subprocess.run([sys.executable, "-c", "import sys; sys.path.append('/opt/python'); print('sys.path=' + str(sys.path) ); import pipdeptree; pipdeptree.main(); "], capture_output=True)
    res += f"""<h1> output of pipdeptree </h1>
stdout: <pre>{c_proc.stdout.decode('utf-8')}</pre>
stderr: <pre>{c_proc.stderr.decode('utf-8')}</pre>
"""

    # https://stackoverflow.com/questions/5136611/capture-stdout-from-a-script
    f:io.StringIO = io.StringIO()
    with redirect_stdout(f):
        import pipdeptree
        pipdeptree.main()
    res += f"""<h1> output of pipdeptree </h1>
stdout: <pre>{f.getvalue()}</pre>
"""

    return respond(None, res)

def log_directory_listing(rootdir_path:str) -> str:
    # get contents of /opt/python directory
    curr_dirpath:str = ""; dirnames_list:list; filenames_list:list; dirnames:str = ""; filenames:str=""
    for (curr_dirpath, dirnames_list, filenames_list) in os.walk(rootdir_path):
        filenames = "\n".join(filenames_list)
        dirnames = "\n".join(dirnames_list)
        # only walk the root directory
        break
    
    # f-string expression part cannot include a backslash.  So need to do "\n".join() above
    return f"""<h1> files in {rootdir_path} </h1>
<p>Files <pre> {filenames} </pre>
<p>Directories <pre> {dirnames} </pre>
"""

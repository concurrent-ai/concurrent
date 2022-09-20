import os
import io
import sys
import getpass
import json
from urllib.parse import urlparse
import urllib
import requests
from requests.exceptions import HTTPError
import time

g_tokfile_contents:str=""
def write_token_file(token_time, token, refresh_token, idToken, client_id):
    with get_token_file_obj('w') as wfile:
        wfile.write("Token=" + token + "\n")
        wfile.write("RefreshToken=" + refresh_token + "\n")
        wfile.write("TokenTimeEpochSeconds=" + str(token_time) + "\n")
        wfile.write("IdToken=" + idToken + "\n")
        wfile.write("ClientId=" + client_id + "\n")
        global g_tokfile_contents
        # if we are writing to an in-memory file (StringIO), then extract the contents before closing
        if isinstance(wfile, io.StringIO): g_tokfile_contents = wfile.getvalue()
        wfile.close()

def get_creds():
    if sys.stdin.isatty():
        username = input("Username: ")
        password = getpass.getpass("Password: ")
    else:
        username = sys.stdin.readline().rstrip()
        password = sys.stdin.readline().rstrip()
    return username, password

def login_and_update_token_file(cognito_client_id, cognito_callback_url,
        cognito_domain, region, is_external_auth):
    if is_external_auth:
        oauth2_authorize_url = f"https://{cognito_domain}.auth.{region}.amazoncognito.com/oauth2/authorize?redirect_uri={urllib.parse.quote_plus(cognito_callback_url)}&response_type=code&state=uxZCvnJk33cDTIoFhT2yxo846Rdj7Q&access_type=offline&prompt=select_account&client_id={cognito_client_id}"

        auth_code = input(f"Enter this URL in a browser and obtain a code: {oauth2_authorize_url}\n  Enter the obtained code here: ")
        
        # get the auth2 access token url based on the service dasshboard url
        oauth2_token_url = f"https://{cognito_domain}.auth.{region}.amazoncognito.com/oauth2/token"
        # do not urlencode the redirect_uri using urllib.parse.quote_plus():  the post call automatically does this..
        response:requests.Response = requests.post(oauth2_token_url, data={"grant_type":"authorization_code", "client_id":cognito_client_id, "code":auth_code, 'redirect_uri': cognito_callback_url})
        
        authres = response.json()
        idToken = authres['id_token']
        accessToken = authres['access_token']
        refresh_token = authres['refresh_token']
        
        # refresh the token.
        response:requests.Response = requests.post(oauth2_token_url, data={"grant_type":"refresh_token", "client_id":cognito_client_id, "refresh_token":refresh_token})
        accessToken = authres['access_token']
        refresh_token = authres['refresh_token']
    else:
        username, password = get_creds()
        postdata = dict()
        auth_parameters = dict()
        auth_parameters['USERNAME'] = username
        auth_parameters['PASSWORD'] = password
        postdata['AuthParameters'] = auth_parameters
        postdata['AuthFlow'] = "USER_PASSWORD_AUTH"
        postdata['ClientId'] = cognito_client_id
        payload = json.dumps(postdata)
        url = 'https://cognito-idp.' +region +'.amazonaws.com:443/'
        headers = {
                'Content-Type': 'application/x-amz-json-1.1',
                'X-Amz-Target' : 'AWSCognitoIdentityProviderService.InitiateAuth'
                }

        try:
            response:requests.Response = requests.post(url, data=payload, headers=headers)
            response.raise_for_status()
        except HTTPError as http_err:
            print(f'HTTP error occurred: {http_err}')
            raise
        except Exception as err:
            print(f'Other error occurred: {err}')
            raise
        
        authres = response.json()['AuthenticationResult']
        idToken = authres['IdToken']
        accessToken = authres['AccessToken']
        refresh_token = authres['RefreshToken']
        
        ##Refresh token once############################
        postdata = dict()
        auth_parameters = dict()
        auth_parameters['REFRESH_TOKEN'] = refresh_token
        postdata['AuthParameters'] = auth_parameters
        postdata['AuthFlow'] = "REFRESH_TOKEN_AUTH"
        postdata['ClientId'] = cognito_client_id

        payload = json.dumps(postdata)

        url = 'https://cognito-idp.' +region +'.amazonaws.com:443/'
        headers = {
                'Content-Type': 'application/x-amz-json-1.1',
                'X-Amz-Target' : 'AWSCognitoIdentityProviderService.InitiateAuth'
                }

        try:
            response = requests.post(url, data=payload, headers=headers)
            response.raise_for_status()
        except HTTPError as http_err:
            print(f'HTTP error occurred: {http_err}')
            raise
        except Exception as err:
            print(f'Other error occurred: {err}')
            raise

        authres = response.json()['AuthenticationResult']
        idToken = authres['IdToken']
        accessToken = authres['AccessToken']

    token_time = int(time.time())
    write_token_file(token_time, accessToken, refresh_token, idToken, cognito_client_id)

# in memory token file contents as a str.  Used when PARALLELS_REFRESH_TOKEN environment variable is in use.
def get_token_file_obj(mode:str, exit_on_error=True):
    """
    if PARALLELS_REFRESH_TOKEN is set
        return in memory token file object
    else if PARALLELS_TOKEN_FILE_DIR is set
        return $PARALLELS_TOKEN_FILE_DIR/token file object
    else 
         return ~/.mlflow-parallels/token file object or ~/.mlflow-parallels/token 

    _extended_summary_
    
    Args:
        mode[str]: must be 'r' or 'w'
        exit_on_error(bool):  Default True.  If True, when an error is encountered, prints an error and exit()s.  If False, prints an error and returns None

    Returns:
        io.TextIOWrapper: file object for the token file. file object is opened for read only ('r').  Need to call close() on this file object when done with it.  May return 'None' if an error is encountered and exit_on_error=False
    """
    
    if mode != 'r' and mode != 'w': raise ValueError(f"Invalid value for mode: must be 'r' or 'w' only: {mode}")
        
    global g_tokfile_contents
    fh:io.TextIOWrapper = None
    if 'PARALLELS_REFRESH_TOKEN' in os.environ:
        # if 'reading' the file, use the in memory file contents to create the file object
        # if writing the file, clear the current in memory file contents and return the file object
        if (mode == 'w'): g_tokfile_contents = ""
        fh = io.StringIO(g_tokfile_contents) 
    elif 'PARALLELS_TOKEN_FILE_DIR' in os.environ:
        tokfile = os.path.join(os.environ['PARALLELS_TOKEN_FILE_DIR'], "token")
        if mode == 'w': os.makedirs(os.path.dirname(tokfile), exist_ok=True)
        # if we are attempting to read the token file, ensure that the token file exists
        if mode == 'r' and not os.path.exists(tokfile):
            print(f"Unable to read token file {tokfile} when PARALLELS_TOKEN_FILE_DIR={os.environ['PARALLELS_TOKEN_FILE_DIR']}.  run login_parallels cli command to login or place a valid token file as {tokfile}")
        else: 
            fh = open(tokfile, mode)
    else:
        if 'MLFLOW_PARALLELS_URI' in os.environ:
            tokfile = os.path.join(os.path.expanduser("~"), ".mlflow-parallels", "token")
            if mode == 'w': os.makedirs(os.path.dirname(tokfile), exist_ok=True)
            # if we are attempting to read the token file, ensure that the token file exists
            if mode == 'r' and not os.path.exists(tokfile):
                print(f"Unable to read token file {tokfile} when MLFLOW_PARALLELS_URI={os.environ['MLFLOW_PARALLELS_URI']}.  run login_parallels cli command to login or place a valid token file as {tokfile}")
            else: 
                fh = open(tokfile, mode)
        else:
            tokfile = os.path.join(os.path.expanduser("~"), ".mlflow-parallels", "token")
            if mode == 'w': os.makedirs(os.path.dirname(tokfile), exist_ok=True)
            # if we are attempting to read the token file, ensure that the token file exists
            if mode == 'r' and not os.path.exists(tokfile):
                print(f"Unable to read token file {tokfile}.  run login_parallels cli command to login or place a valid token file as {tokfile}")
            else:
                fh = open(tokfile, mode)
    
    if not fh and exit_on_error:
        # exit() so that we print an user friendly message instead of the exception that will be thrown if open() is called with a file that doesn't exist
        exit()

    return fh

def read_token_file(region, exit_on_error=False):
    """reads and returns the following from the tokenfile: access_token, refresh_token, token_time, client_id, service, token_type, id_token
    The file from which these are read from can be a file in the filesystem or an in memory file: see get_token_file_obj() for details.

    Args:
        exit_on_error(bool): Default is True.  if an error is encountered during reading token file.  print an error message and call exit(), if True.  If False, returned values may be None.
    Returns:
        [tuple]: returns the tuple (access_token, refresh_token, token_time, client_id, service, token_type, id_token)
    """
    with get_token_file_obj( 'r', exit_on_error ) as fp:
        # check if this is an in-memory token file (PARALLELS_REFRESH_TOKEN is set) and if this file is empty.  If so, create the in-memory tokenfile.  
        # Note that this is needed, since when PARALLELS_REFRESH_TOKEN is used, performing a cli login to create filesystem tokenfile or placing the 'token' file in the filesystem will not work.  
        # Instead the in-memory token file needs to be created whenever anyone attempts to read the token file.
        #
        # if in memory token file is in use and it is empty
        if fp and isinstance(fp, io.StringIO) and not fp.getvalue():
            # renew the token, which creates the in-memory token file
            renew_token(region, os.getenv('PARALLELS_REFRESH_TOKEN','PARALLELS_REFRESH_TOKEN not set'), os.getenv('PARALLELS_COGNITO_CLIENTID','PARALLELS_COGNITO_CLIENTID not set'))

    fclient_id = None
    ftoken = None
    frefresh_token = None
    ftoken_time = None
    token_type = None
    id_token = None
    with get_token_file_obj( 'r', exit_on_error) as fp:
        if fp:
            for count, line in enumerate(fp):
                if (line.startswith('ClientId=')):
                    fclient_id = line[len('ClientId='):].rstrip()
                if (line.startswith('Token=')):
                    ftoken = line[len('Token='):].rstrip()
                if (line.startswith('RefreshToken=')):
                    frefresh_token = line[len('RefreshToken='):].rstrip()
                if (line.startswith('TokenTimeEpochSeconds=')):
                    ftoken_time = int(line[len('TokenTimeEpochSeconds='):].rstrip())
                if (line.startswith('TokenType=')):
                    token_type = line[len('TokenType='):].rstrip()
                if (line.strip().lower().startswith('idtoken=')):
                    # read the content after '='
                    id_token = line.split('=')[1].strip()
    if (token_type == None):
        if ftoken != None: token_type = 'Custom' if ftoken.startswith('Custom ') else 'Bearer'
        
    return ftoken, frefresh_token, ftoken_time, fclient_id, token_type, id_token

def renew_token(region, refresh_token, client_id):
    payload = "{\n"
    payload += "    \"AuthParameters\" : {\n"
    payload += "        \"REFRESH_TOKEN\" : \"" + refresh_token + "\"\n"
    payload += "    },\n"
    payload += "    \"AuthFlow\" : \"REFRESH_TOKEN_AUTH\",\n"
    payload += "    \"ClientId\" : \"" + client_id + "\"\n"
    payload += "}\n"

    url = 'https://cognito-idp.' +region +'.amazonaws.com:443/'

    headers = {
            'Content-Type': 'application/x-amz-json-1.1',
            'X-Amz-Target' : 'AWSCognitoIdentityProviderService.InitiateAuth'
            }

    try:
        response = requests.post(url, data=payload, headers=headers)
        response.raise_for_status()
    except HTTPError as http_err:
        print(f'HTTP error occurred while trying to renew token: {http_err}')
        raise
    except Exception as err:
        print(f'Other non http error occurred while trying to renew token: {err}')
        raise
    else:
        authres = response.json()['AuthenticationResult']
        token = authres['AccessToken']
        idToken = authres['IdToken']        
        token_time = int(time.time())
        write_token_file(token_time, token, refresh_token, idToken, client_id)

def get_token(client_id, region, force_renew):
    token = None
    refresh_token = None
    token_time = None

    token, refresh_token, token_time, client_id, token_type, id_token = read_token_file(region)
    if (token_type == "Custom"):
        return token

    if (force_renew == True):
        print("Forcing renewal of parallels token")
        renew_token(region, refresh_token, client_id)
        token, refresh_token, token_time, client_id, token_type, id_token = read_token_file(region)
        return token

    time_now = int(time.time())
    if ((token_time + (30 * 60)) < time_now):
        print('Parallels token has expired. Calling renew')
        renew_token(region, refresh_token, client_id)
        token, refresh_token, token_time, client_id, token_type, id_token = read_token_file(region)
        return token
    else:
        return token

def get_env_var():
    muri = os.getenv('MLFLOW_PARALLELS_URI')
    if not muri:
        raise Exception('Please set environment variable MLFLOW_PARALLELS_URI and try again')
    pmuri = urlparse(muri)
    if (pmuri.scheme.lower() != 'https'):
        raise Exception("Error: MLFLOW_PARALLELS_URI must be set to https://<mlflow_parallels_server>:<mlflow_parallels_port>/")
    return muri

def get_conf():
    cognito_client_id = None
    is_external_auth = None
    cognito_callback_url = None
    cognito_domain = None
    region = None

    muri = get_env_var()
    url = muri.rstrip('/') + '/api/2.0/mlflow/parallels/getversion'
    headers = { 'Authorization': 'None' }
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        resp = response.json()
        cognito_client_id = resp['cognitoClientId']
        is_external_auth = resp['isExternalAuth']
        cognito_callback_url = resp['cognitoCallbackUrl']
        cognito_domain =  resp['cognitoDomain']
        region = resp['region']
    except HTTPError as http_err:
        print('Caught ' + str(http_err) + ' getting cognito client id')
        raise Exception('Caught ' + str(http_err) + ' getting cognito client id')
    except Exception as err:
        print('Caught ' + str(err) + ' getting cognito client id')
        raise Exception('Caught ' + str(err) + ' getting cognito client id')
    return cognito_client_id, is_external_auth, cognito_callback_url, cognito_domain, region

def login():
    cognito_client_id, is_external_auth, cognito_callback_url, cognito_domain, region = get_conf()
    login_completed = False
    try:
        token = get_token(cognito_client_id, region, True)
        print('Login completed')
        login_completed = True
    except Exception as err:
        pass

    if not login_completed:
        login_and_update_token_file(cognito_client_id,
                cognito_callback_url, cognito_domain, region, is_external_auth)
        try:
            token = get_token(cognito_client_id, region, False)
            print('Login completed')
            login_completed = True
        except Exception as err:
            raise
    return 0

if __name__ == "__main__":
    exit(login())

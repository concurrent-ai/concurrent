import mimetypes
import os
import zipfile
import boto3
from typing import TYPE_CHECKING, List
if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client
else:
    S3Client = object
import cfnresponse
import urllib3
from six.moves.urllib.parse import quote
import time

# pylint: disable=bad-indentation,broad-except
def handler(event, context):
    print(f'event={event}')
    print(f'context={context}')
    response_data = {}
    try:
      # Init ...
      the_event = event['RequestType']
      print('The event is: ' + str(the_event))
      s3_client:S3Client = boto3.client('s3')
      # Retrieve parameters
      the_bucket = event['ResourceProperties']['the_bucket']
      staticfilesBucketPrefix:str = event['ResourceProperties']['StaticfilesBucketPrefix']
      user_pool_id = event['ResourceProperties']['user_pool_id']
      cli_client_id = event['ResourceProperties']['cli_client_id']
      mlflowui_client_id = event['ResourceProperties']['mlflowui_client_id']
      service = event['ResourceProperties']['service']
      mlflow_parallels_dns_name = event['ResourceProperties']['mlflow_parallels_dns_name']
      mlflowparallelsui_dns_name = event['ResourceProperties']['mlflowparallelsui_dns_name']
      mlflow_parallels_ui_build_location = event['ResourceProperties']['mlflow_parallels_ui_build_location']
      mlflow_parallels_ui_version = event['ResourceProperties']['mlflow_parallels_ui_version']
      mlflowServerType = event['ResourceProperties']['mlflowServerType']

      if the_event == 'Create':
        create_all(s3_client, mlflowServerType, the_bucket, staticfilesBucketPrefix, user_pool_id, cli_client_id, mlflowui_client_id,
                  service, mlflow_parallels_dns_name, mlflowparallelsui_dns_name, mlflow_parallels_ui_build_location, mlflow_parallels_ui_version)
        # Everything OK... send the signal back
        print('Operation successful!')
        cfnresponse.send(event, context, cfnresponse.SUCCESS, response_data, physicalResourceId=the_bucket)
      elif the_event == 'Update':
        OldStaticfilesBucketPrefix:str = event['OldResourceProperties']['StaticfilesBucketPrefix']
        delete_all(s3_client, mlflowServerType, the_bucket, OldStaticfilesBucketPrefix)
        create_all(s3_client, mlflowServerType, the_bucket, staticfilesBucketPrefix, user_pool_id, cli_client_id, mlflowui_client_id,
                  service, mlflow_parallels_dns_name, mlflowparallelsui_dns_name, mlflow_parallels_ui_build_location, mlflow_parallels_ui_version)
        # Everything OK... send the signal back
        print('Operation successful!')
        cfnresponse.send(event, context, cfnresponse.SUCCESS, response_data, physicalResourceId=the_bucket)
      elif the_event == 'Delete':
        # TODO: if installing on top of mlflow-noproxy, when we uninstall mlflow-noproxy-parallels-ui build, we need to retore the old mlflow-noproxy build that it overwrote.
        delete_all(s3_client, mlflowServerType, the_bucket, staticfilesBucketPrefix)
        # Everything OK... send the signal back
        print('Operation successful!')
        cfnresponse.send(event, context, cfnresponse.SUCCESS, response_data, physicalResourceId=the_bucket)
    except Exception as e:
      print('Operation failed...')
      print(str(e))
      response_data['Data'] = str(e)
      cfnresponse.send(event, context, cfnresponse.FAILED, response_data, physicalResourceId=the_bucket)

def create_all(s3_client:S3Client, mlflowServerType:str, the_bucket, staticfilesBucketPrefix:str, user_pool_id, cli_client_id, mlflowui_client_id,
                service, mlflow_parallels_dns_name, mlflowparallelsui_dns_name, mlflow_parallels_ui_build_location:str, mlflow_parallels_ui_version:str):
    create_or_update_sc_js(s3_client, mlflowServerType, the_bucket, staticfilesBucketPrefix, user_pool_id, cli_client_id,
                            mlflowui_client_id, service, mlflow_parallels_dns_name, mlflowparallelsui_dns_name)
    http:urllib3.PoolManager = urllib3.PoolManager()
    # copy mlflow noproxy files from mlflow-parallelsdist to this service bucket
    copy_parallels_ui(mlflow_parallels_ui_build_location, mlflow_parallels_ui_version, http, s3_client, the_bucket, staticfilesBucketPrefix)

def create_or_update_sc_js(s3_client:S3Client, mlflowServerType:str, the_bucket:str, staticfilesBucketPrefix:str, user_pool_id:str, cli_client_id:str,
                              mlflowui_client_id:str, service:str, mlflow_parallels_dns_name:str, mlflowparallelsui_dns_name:str):
    s3_prefix:str = staticfilesBucketPrefix + '/static-files/serviceconfig.js'
    tmp_serviceconfig_js = '/tmp/serviceconfig.js'
    
    # when installing on top of infinstor mlflow server, first download the existing file
    if mlflowServerType == 'infinstor':
      print(f'Downloading file s3://{the_bucket}/{s3_prefix} to {tmp_serviceconfig_js}')
      # we could get this error if 'serviceconfig.js' doesn't exist in the bucket: An error occurred (403) when calling the HeadObject operation: Forbidden.  Handle it.
      try:
        s3_client.download_file(the_bucket, s3_prefix, tmp_serviceconfig_js)
      except Exception as e:
        print(f's3_client.download_file() failed for s3://{the_bucket}/{s3_prefix}: {str(e)}.  Ignoring error (non fatal) and continuing..')
      
    create_or_update_sc_js_file(user_pool_id, cli_client_id, mlflowui_client_id, service, mlflow_parallels_dns_name, mlflowparallelsui_dns_name, tmp_serviceconfig_js)
        
    print(f'Creating s3://{the_bucket}/{s3_prefix} from {tmp_serviceconfig_js}')
    s3_client.upload_file(tmp_serviceconfig_js, the_bucket, s3_prefix)

def create_or_update_sc_js_file(user_pool_id:str, cli_client_id:str, mlflowui_client_id:str, service:str, mlflow_parallels_dns_name:str, mlflowparallelsui_dns_name:str, tmp_serviceconfig_js:str):
    # we can perform update many times, so need to merge and simply cannot append lines to the end    
    file_lines:dict = {}
    # if file exists, read it into the dict.
    if os.path.isfile(tmp_serviceconfig_js):
      with open(tmp_serviceconfig_js, 'r') as file:
        # window.InfinStorUserPoolId = "us-east-1_YwLsbrqSp";
        # window.InfinStorClientId = "6ueuk0h1gba1o19pnfdt6s33qj";
        for line in file:
          line_split:List[str] = line.split("=")
          file_lines[line_split[0].strip()] = line_split[1].strip()   # strip() also removes trailing new lines

    # make the needed updates in the dict
    file_lines['window.ParallelsUserPoolId'] = f'"{user_pool_id}"'
    file_lines['window.ParallelsCliClientId'] = f'"{cli_client_id}"'
    file_lines['window.ParallelsUiClientId'] = f'"{mlflowui_client_id}"'
    file_lines['window.ParallelsService'] = f'"{service}"'
    file_lines['window.ParallelsServer'] = f'"{mlflow_parallels_dns_name}.{service}"'
    file_lines['window.ParallelsUiServer'] = f'"{mlflowparallelsui_dns_name}.{service}"'
      
    # write the dict out as a file
    with open(tmp_serviceconfig_js, 'w') as file:
      for item in file_lines.items():
        file.write(f'{item[0]}={item[1]};\n')

def copy_parallels_ui(mlflow_parallels_ui_build_location:str, mlflow_parallels_ui_version:str, http:urllib3.PoolManager, s3_client:S3Client, the_bucket:str, staticfilesBucketPrefix:str):
    build_loc_with_ver:str = f'{mlflow_parallels_ui_build_location}/{mlflow_parallels_ui_version}'
    build_zip:str = 'build.zip'
    r:urllib3.response.HTTPResponse = http.request('GET', f'https://parallelsdist.s3.amazonaws.com/{build_loc_with_ver}/{build_zip}')
    if (r.status != 200):
      estr = f'Download of https://parallelsdist.s3.amazonaws.com/{build_loc_with_ver}/{build_zip} failed. http status={r.status};headers={r.getheaders()};body={r.data}'
      print(estr)
      raise ValueError(estr)
    
    # copy build.zip to target s3 bucket
    s3_client.put_object(Body=r.data, Bucket=the_bucket, Key=f'{staticfilesBucketPrefix}/{build_zip}', ContentType=r.headers['Content-Type'])
    
    # download build.zip to /tmp directory
    build_zip_fpath = '/tmp/'+ build_zip
    with open(build_zip_fpath, "wb") as fh:
      fh.write(r.data)
      
    # read the .zip file and copy to s3 bucket
    zipf:zipfile.ZipFile
    with zipfile.ZipFile(build_zip_fpath) as zipf:
        filelist:List[zipfile.ZipInfo] = zipf.filelist;  file_zipinfo:zipfile.ZipInfo
        for file_zipinfo in filelist:
            print(f"file_zipinfo={file_zipinfo}")
            # if archive member is a file
            if not file_zipinfo.is_dir(): 
                # read the file
                file_bytes:bytes = zipf.read(file_zipinfo)
                # determine its mime type.  without this, file content type is set to binary/octet-stream, even for .html files, when http served from s3 bucket
                content_type, encoding = mimetypes.guess_type(file_zipinfo.filename, strict=False)
                s3_prefix:str=f'{staticfilesBucketPrefix}/{file_zipinfo.filename}'
                print(f"writing {file_zipinfo.filename} to s3://{the_bucket}/{s3_prefix} with content_type={content_type}")
                if content_type:
                  s3_client.put_object(Body=file_bytes, Bucket=the_bucket, Key=s3_prefix, ContentType=content_type)
                else:
                  s3_client.put_object(Body=file_bytes, Bucket=the_bucket, Key=s3_prefix) #, ContentType=r1.headers['Content-Type'])

def delete_all(s_3:S3Client, mlflowServerType:str, the_bucket:str, staticfilesBucketPrefix:str):
    # if mlflowservertype is not infinstor and ('delete' during 'update' or 'delete' during 'delete')
    if not mlflowServerType == 'infinstor':
      print(f'deleting static-files in s3://{the_bucket}/{staticfilesBucketPrefix} since mlflowservertype is infinstor')
      delete_s_3:S3Client = boto3.client('s3')
      paginator = s_3.get_paginator('list_object_versions')
      page_iterator = paginator.paginate(Bucket=the_bucket, Prefix=staticfilesBucketPrefix)
      for page in page_iterator:
        if ('Versions' in page):
          aob = page['Versions']
          oa = []
          for obj in aob:
            oe = {}
            oe['Key'] = obj['Key']
            if 'VersionId' in obj and obj['VersionId'] and obj['VersionId'] != 'null':
              oe['VersionId'] = obj['VersionId']
              print('Adding key=' + str(oe['Key']) + ' vers=' + str(oe['VersionId']) + ' to del list')
            else:
              print('Adding key=' + str(oe['Key']) + ' to del list')
            oa.append(oe)

          dobjs = {}
          dobjs['Objects'] = oa
          dobjs['Quiet'] = True
          print('deleting ' + str(len(oa)) + ' object versions')
          delete_s_3.delete_objects(Bucket=the_bucket, Delete=dobjs)
          print('deleted ' + str(len(oa)) + ' object versions')

        if ('DeleteMarkers' in page):
          aob = page['DeleteMarkers']
          oa = []
          for obj in aob:
            oe = {}
            oe['Key'] = obj['Key']
            if 'VersionId' in obj and obj['VersionId'] and obj['VersionId'] != 'null':
              oe['VersionId'] = obj['VersionId']
              print('Adding delmarker=' + str(oe['Key']) + ' vers=' + str(oe['VersionId']) + ' to del list')
            else:
              print('Adding delmarker=' + str(oe['Key']) + ' to del list')
            oa.append(oe)

          dobjs = {}
          dobjs['Objects'] = oa
          dobjs['Quiet'] = True
          print('deleting ' + str(len(oa)) + ' delete markers')
          delete_s_3.delete_objects(Bucket=the_bucket, Delete=dobjs)
          print('deleted ' + str(len(oa)) + ' delete markers')
    else:  # if mlflowservertype is infinstor and (delete during update or delete during delete): 
      # don't delete when mlflowservertype is infinstor and delete during update, since want to preserve serviceconfig.js part from root stack.
      # don't delete when mlflowservertype is infinstor and delete during delete, since want to preserve mlflow-noproxy from root stack. TODO: ui will show parallels tab but it won't work. fix this
      print(f'Not deleting static-files in s3://{the_bucket}/{staticfilesBucketPrefix} since mlflowservertype is infinstor')
      


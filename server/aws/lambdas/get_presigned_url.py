
import json
import jsons
import os
import logging
import uuid
from urllib.parse import urlparse, quote, unquote, unquote_plus

from utils import get_cognito_user
import boto3
from storage_credentials import query_storage_credentials
import botocore
import botocore.client
import dataclasses

from typing import TYPE_CHECKING, List, Any
if TYPE_CHECKING:
    from mypy_boto3_s3.type_defs import ListObjectsOutputTypeDef, PutObjectRequestRequestTypeDef, PutObjectOutputTypeDef, CreateMultipartUploadRequestRequestTypeDef, CreateMultipartUploadOutputTypeDef, CompleteMultipartUploadRequestRequestTypeDef, CompleteMultipartUploadOutputTypeDef, AbortMultipartUploadOutputTypeDef, CompletedMultipartUploadTypeDef, CompletedPartTypeDef
else:
    ListObjectsOutputTypeDef = object; PutObjectRequestRequestTypeDef = object; PutObjectOutputTypeDef = object; CreateMultipartUploadOutputTypeDef = object; CreateMultipartUploadOutputTypeDef = object; CompleteMultipartUploadRequestRequestTypeDef = object;  CompleteMultipartUploadOutputTypeDef = object; AbortMultipartUploadOutputTypeDef = object; CompletedMultipartUploadTypeDef = object; CompletedPartTypeDef = object

logger = logging.getLogger()
logger.setLevel(logging.INFO)
#pylint: disable=logging-fstring-interpolation, logging-not-lazy

def respond(err:Any, res:Any=None) -> dict:
    """
    if err is not none, returns {statusCode: 400, body: str(err), headers:{} }
    else returns {statusCode:200, body:json.dumps(res), headers:{} }

    

    Args:
        err (Any): _description_
        res (Any, optional): _description_. Defaults to None.

    Returns:
        dict: see description above
    """
    return {
        'statusCode': '400' if err else '200',
        'body': str(err) if err else json.dumps(res),
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': '*',
            'Access-Control-Allow-Methods': '*',
            'Access-Control-Allow-Credentials': '*'
        },
    }

@dataclasses.dataclass
class CreateMultiPartUploadPresignedUrlInfo:        
    chunk_num:int
    """chunk number for this multipart upload"""
    ps_url:str
    """presigned url for above chunk number"""
    
@dataclasses.dataclass
class CreateMultiPartUploadResp:
    upload_id: str 
    ps_url_infos_for_mult_part:List[CreateMultiPartUploadPresignedUrlInfo] = dataclasses.field(default_factory=list)

@dataclasses.dataclass
class CompleteMultiPartUploadComplatedPartInfo:
    PartNumber:int
    ETag:str

@dataclasses.dataclass
class CompleteMultiPartUploadReq:
    upload_id:str
    Parts:List[CompleteMultiPartUploadComplatedPartInfo] = dataclasses.field(default_factory=list)


def get_presigned_url(event, context):    
    logger.info('## ENVIRONMENT VARIABLES')
    logger.info(os.environ)
    logger.info('## EVENT')
    logger.info(event)

    try:
        operation = event['httpMethod']
        if (operation != 'GET'):
            return respond(ValueError('Unsupported method ' + str(operation)))

        cognito_username, _ = get_cognito_user(event)

        qs = event['queryStringParameters']
        logger.info(qs)

        bucket = None
        path = None
        if 'bucket' in qs:
            bucket = qs['bucket']
        if 'path' in qs:
            path = qs['path']

        if not path or not bucket:
            logger.info('bucket and path are required')
            return respond(ValueError('bucket and path are required'))
        # method = 'get_object' | 'put_object' | 'list_objects_v2' | 'list_objects' | 'head_object' 
        if ('method' in qs):
            method = qs['method']
        else:
            method = 'get_object'

        creds = query_storage_credentials(cognito_username, bucket)

        if not creds:
            msg = "No credentials available for bucket {} for user {}".format(bucket, cognito_username)
            logger.warning(msg)
            return respond(msg)

        sts_client = boto3.client('sts')
        if 'external_id' in creds:
            assumed_role_object = sts_client.assume_role(
                RoleArn=creds['iam_role'],
                ExternalId=creds['external_id'],
                RoleSessionName=str(uuid.uuid4()))
        else:
            assumed_role_object = sts_client.assume_role(
                RoleArn=creds['iam_role'],
                RoleSessionName=str(uuid.uuid4()))

        credentials = assumed_role_object['Credentials']
        # https://stackoverflow.com/questions/57950613/boto3-generate-presigned-url-signaturedoesnotmatch-error; 
        # to avoid this error from generate_presigned_url('list_objects_v2'): <Error><Code>SignatureDoesNotMatch</Code><Message>The request signature we calculated does not match the signature you provided. Check your key and signing method.</Message>    
        client_args = {
            "aws_access_key_id": credentials['AccessKeyId'],
            "aws_secret_access_key": credentials['SecretAccessKey'],
            "aws_session_token": credentials['SessionToken'],
            "config": botocore.client.Config(signature_version='s3v4')
        }
    
        if 'region_name' in creds and creds['region_name'] != '':
            client_args['region_name'] = creds['region_name']
        
        if 'endpoint_url' in creds and creds['endpoint_url'] != '':
            client_args['endpoint_url'] = creds['endpoint_url']
      
        client = boto3.client("s3",**client_args)

        if method == 'create_multipart_upload':
            # number of chunks for generating presigned URLs for create_multipart_upload()
            num_of_chunks:int = int(qs['num_of_chunks']) if ('num_of_chunks' in qs) else None

            params = {'Bucket': bucket, 'Key': path}
            # invoke create_multipart_upload()
            multi_upload_resp:CreateMultipartUploadOutputTypeDef = client.create_multipart_upload(**params)
            logger.info(f"multi_upload_resp={multi_upload_resp}")
            
            multipart_upload_resp:CreateMultiPartUploadResp = CreateMultiPartUploadResp(multi_upload_resp['UploadId'])
            # generate presigned URLs for each chunk: 1 to num_of_chunks
            for chunk_num in range(1, num_of_chunks+1):
                # https://www.altostra.com/blog/multipart-uploads-with-s3-presigned-url
                # https://docs.aws.amazon.com/AmazonS3/latest/API/API_UploadPart.html
                # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3/client/upload_part.html#
                # PartNumber: Part number of part being uploaded. This is a positive integer between 1 and 10,000.
                logger.info("\n##############\nStarting s3_client.generate_presigned_url()\n########################")
                ps_url_resp:str = client.generate_presigned_url("upload_part", {"Bucket":params['Bucket'], "Key":params["Key"], "UploadId":multi_upload_resp["UploadId"], "PartNumber":chunk_num})
                logger.info(f"chunk_num={chunk_num} ps_url={ps_url_resp}")
                multipart_upload_resp.ps_url_infos_for_mult_part.append(CreateMultiPartUploadPresignedUrlInfo(chunk_num, ps_url_resp))
            ps_url_resp = multipart_upload_resp
            
        elif method == 'complete_multipart_upload':
            # urlencode.parse.quote_plus() encoded json for complete_multipart_upload()
            # this is a json serialization of artifact_utils.py::CompleteMultiPartUploadReq
            comp_multi_upload_json_str:str = qs['complete_multipart_upload_json_str'] if ( 'complete_multipart_upload_json_str' in qs ) else None
            if comp_multi_upload_json_str: comp_multi_upload_json_str = unquote_plus(comp_multi_upload_json_str)

            comp_multi_upload_req:CompleteMultiPartUploadReq = jsons.loads(comp_multi_upload_json_str, CompleteMultiPartUploadReq)
            logger.info(f"comp_multi_upload_req={comp_multi_upload_req}")
            
            # MultipartUpload={ "Parts": [ {"PartNumber":xxxx, ETag:yyyy }, ... ] }
            comp_mp_upload_resp:CompleteMultipartUploadOutputTypeDef = client.complete_multipart_upload(Bucket=bucket, Key=path, UploadId=comp_multi_upload_req.upload_id, MultipartUpload={ "Parts": jsons.loads(jsons.dumps(comp_multi_upload_req.Parts)) } )
            logger.info(f"comp_mp_upload_resp={comp_mp_upload_resp}")
            # return the ETag
            ps_url_resp = comp_mp_upload_resp['ETag']
            
        elif method == 'abort_multipart_upload':
            upload_id:str = qs['upload_id'] if ( 'upload_id' in qs ) else None
            
            abort_mp_upload_resp:AbortMultipartUploadOutputTypeDef = client.abort_multipart_upload(Bucket=bucket, Key=path, UploadId=upload_id )
            logger.info(f"abort_mp_upload_resp={abort_mp_upload_resp}")
            # return the http status code
            ps_url_resp = str(abort_mp_upload_resp['ResponseMetadata']['HTTPStatusCode'])
            
        else:  # get_object(), put_object(), head_object(), list_objects(), list_objects_v2
            if method == 'list_objects_v2' or method == 'list_objects':
                params = {'Bucket': bucket, 'Prefix': path, 'Delimiter': '/'}
                # https://docs.aws.amazon.com/AmazonS3/latest/API/API_ListObjectsV2.html#API_ListObjectsV2_RequestParameters
                # for list_objects_v2: ContinuationToken indicates Amazon S3 that the list is being continued on this bucket with a token. ContinuationToken is obfuscated and is not a real key.
                if 'ContinuationToken' in qs:
                    params['ContinuationToken'] = unquote(qs['ContinuationToken'])
            # method = 'get_object' | 'put_object' | 'head_object' 
            else:         
                params = {'Bucket': bucket, 'Key': path}
                # https://docs.aws.amazon.com/AmazonS3/latest/API/API_ListObjects.html#API_ListObjects_RequestParameters
                # for list_objects: Marker is where you want Amazon S3 to start listing from. Amazon S3 starts listing after this specified key. Marker can be any key in the bucket.
                if 'Marker' in qs:
                    params['Marker'] = qs['Marker']

            # https://docs.aws.amazon.com/AmazonS3/latest/API/API_ListObjectsV2.html#API_ListObjectsV2_RequestParameters
            # for list_objects_v2: StartAfter is where you want Amazon S3 to start listing from. Amazon S3 starts listing after this specified key. StartAfter can be any key in the bucket.
            if 'StartAfter' in qs:
                params['StartAfter'] = qs['StartAfter']
            # https://docs.aws.amazon.com/AmazonS3/latest/API/API_ListObjectsV2.html#API_ListObjectsV2_RequestParameters
            # for list_objects_v2: Sets the maximum number of keys returned in the response. By default the action returns up to 1,000 key names. The response might contain fewer keys but will never contain more.
            if 'MaxKeys' in qs:
                params['MaxKeys'] = qs['MaxKeys']

            ps_url_resp = client.generate_presigned_url(method, Params=params, ExpiresIn = (24*60*60))

            logger.info('Presigned URL is ' + str(ps_url_resp))
            # Handle url quoting of continuation-token
            if 'ContinuationToken' in params:
                url_comps = urlparse(ps_url_resp)
                query_comps = url_comps.query.split('&')
                for i in range(len(query_comps)):
                    if query_comps[i].startswith('continuation-token='):
                        ct_quoted = quote(params['ContinuationToken'])
                        query_comps[i] = 'continuation-token=' + ct_quoted
                query = '&'.join(query_comps)
                url_comps._replace(query=query)
                ps_url_resp = url_comps.geturl()
                logger.info('Updated Presigned URL is ' + str(ps_url_resp))

            # Handle url quoting of Marker
            if 'Marker' in params:
                url_comps = urlparse(ps_url_resp)
                query_comps = url_comps.query.split('&')
                for i in range(len(query_comps)):
                    if query_comps[i].startswith('marker='):
                        ct_quoted = quote(params['Marker'])
                        query_comps[i] = 'marker=' + ct_quoted
                query = '&'.join(query_comps)
                url_comps._replace(query=query)
                ps_url_resp = url_comps.geturl()
                logger.info('Updated Presigned URL is ' + str(ps_url_resp))

        if (ps_url_resp == None):
            return respond(ValueError('Failed to create presigned URL'))
        else:
            # ps_url_resp can be the presigned_url or CreateMultipartUploadResp instance (method == create_multipart_upload) or ETag (method == complete_multipart_upload) or http_status_code (method == abort_multipart_upload) 
            if method == 'create_multipart_upload':
                rv = jsons.loads(jsons.dumps(ps_url_resp))
            else:
                rv = {"presigned_url": ps_url_resp}
            logger.info(json.dumps(rv))
            return respond(None, rv)
    except Exception as e:
        logger.error(f"Caught Exception {e}", exc_info=e)
        return respond(f"Caught Exception {e}")
        
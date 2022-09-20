import os
import sys
import base64
from datetime import datetime, timedelta
import boto3
import uuid
import json

def _retrieve_cluster_name(params, context, **kwargs):
    if 'ClusterName' in params:
        context['eks_cluster'] = params.pop('ClusterName')

def _inject_cluster_name_header(request, **kwargs):
    if 'eks_cluster' in request.context:
        request.headers[
            'x-k8s-aws-id'] = request.context['eks_cluster']

def _register_cluster_name_handlers(sts_client):
    sts_client.meta.events.register(
        'provide-client-params.sts.GetCallerIdentity',
        _retrieve_cluster_name
    )
    sts_client.meta.events.register(
        'before-sign.sts.GetCallerIdentity',
        _inject_cluster_name_header
    )

def uni_print(statement, out_file=None):
    """
    This function is used to properly write unicode to a file, usually
    stdout or stdderr.  It ensures that the proper encoding is used if the
    statement is not a string type.
    """
    if out_file is None:
        out_file = sys.stdout
    try:
        # Otherwise we assume that out_file is a
        # text writer type that accepts str/unicode instead
        # of bytes.
        out_file.write(statement)
    except UnicodeEncodeError:
        # Some file like objects like cStringIO will
        # try to decode as ascii on python2.
        #
        # This can also fail if our encoding associated
        # with the text writer cannot encode the unicode
        # ``statement`` we've been given.  This commonly
        # happens on windows where we have some S3 key
        # previously encoded with utf-8 that can't be
        # encoded using whatever codepage the user has
        # configured in their console.
        #
        # At this point we've already failed to do what's
        # been requested.  We now try to make a best effort
        # attempt at printing the statement to the outfile.
        # We're using 'ascii' as the default because if the
        # stream doesn't give us any encoding information
        # we want to pick an encoding that has the highest
        # chance of printing successfully.
        new_encoding = getattr(out_file, 'encoding', 'ascii')
        # When the output of the aws command is being piped,
        # ``sys.stdout.encoding`` is ``None``.
        if new_encoding is None:
            new_encoding = 'ascii'
        new_statement = statement.encode(
            new_encoding, 'replace').decode(new_encoding)
        out_file.write(new_statement)
    out_file.flush()

def get_token(access_key_id, secret_access_key, session_token, kube_cluster_name):
    client_kwargs = {}
    client_kwargs['region_name'] = 'us-east-1'
    client_kwargs['aws_access_key_id'] = access_key_id
    client_kwargs['aws_secret_access_key'] = secret_access_key
    client_kwargs['aws_session_token'] = session_token
    sts_client_1 = boto3.client('sts', **client_kwargs)
    _register_cluster_name_handlers(sts_client_1)
    url = sts_client_1.generate_presigned_url('get_caller_identity',
            Params={'ClusterName': kube_cluster_name},
            ExpiresIn=60, HttpMethod='Get')
    token = 'k8s-aws-v1.' +base64.urlsafe_b64encode(url.encode('utf-8')).decode('utf-8').rstrip('=')
    expr = datetime.utcnow() + timedelta(minutes=14)
    token_expiration = expr.strftime('%Y-%m-%dT%H:%M:%SZ')

    full_object = {
            "kind": "ExecCredential",
            "apiVersion": "client.authentication.k8s.io/v1alpha1",
            "spec": {},
            "status": {
                "expirationTimestamp": token_expiration,
                "token": token
            }
        }
    uni_print(json.dumps(full_object))
    uni_print('\n')
    return 0

if __name__ == "__main__":
    token = get_token(
                os.getenv('AWS_ACCESS_KEY_ID'),
                os.getenv('AWS_SECRET_ACCESS_KEY'),
                os.getenv('AWS_SESSION_TOKEN'),
                os.getenv('EKS_CLUSTER_NAME')
            )
    os._exit(0)

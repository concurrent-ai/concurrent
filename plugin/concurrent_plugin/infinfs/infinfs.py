from __future__ import print_function
import os
import builtins
import json
import mlflow
from fuse import Operations
from urllib.parse import urlparse
import sys
from concurrent_plugin.infinfs import infin_download
import boto3
import hashlib
import shutil
import tempfile

##This import is required
from infinstor import infin_boto3


def get_cache_key(mount_spec):
   return hashlib.md5(json.dumps(mount_spec).encode('utf-8')).hexdigest()


class InfinFS(Operations):
    def __init__(self, mount_specs, shadow_path=None, use_cache=True):
        self.mountpoint = mount_specs['mountpoint']
        self.infinstor_time_spec = mount_specs.get('infinstor_time_spec')
        self.prefix = mount_specs.get('prefix')
        self.bucket = mount_specs['bucket']

        ##Create shadow location
        mountdir = os.path.dirname(self.mountpoint)
        mountbasename = os.path.basename(self.mountpoint)
        shadowbasename = "infin-" + mountbasename + "-shadow"
        cache_key = get_cache_key(mount_specs)
        if shadow_path:
            self.shadow_location = os.path.join(shadow_path, '.concurrent', cache_key, shadowbasename)
        else:
            tmpdir = tempfile.mkdtemp()
            self.shadow_location = os.path.join(tmpdir, '.concurrent', cache_key, shadowbasename)
        if not os.path.exists(self.shadow_location):
            os.makedirs(self.shadow_location)
        elif not use_cache:
            shutil.rmtree(self.shadow_location)
            os.mkdir(self.shadow_location)
        self.s3_client = self.get_s3_client()
        print(self.prefix, self.mountpoint, self.shadow_location, self.bucket, self.s3_client)

    def get_mountpoint(self):
        return self.mountpoint

    def get_s3_client(self):
        if self.infinstor_time_spec:
            return boto3.client('s3', infinstor_time_spec=self.infinstor_time_spec)
        else:
            return boto3.client('s3')


    def get_bucket_prefix(self, s3path):
        m = urlparse(s3path)
        return m.netloc, m.path.lstrip('/').rstrip('/')

    def get_mount_relative_path(self, absolute_path):
        if self.mountpoint not in absolute_path:
            raise Exception("Invalid mounted path")
        rel_path = absolute_path[len(self.mountpoint):]
        return rel_path.lstrip('/')

    def get_remote_path(self, full_path):
        if not full_path.startswith(self.mountpoint):
            raise Exception("Invalid mounted path " + full_path)
        rel_path = self.get_mount_relative_path(full_path)
        if self.prefix and rel_path:
            return self.prefix + "/" + rel_path
        elif self.prefix:
            return self.prefix
        else:
            return rel_path

    def get_shadow_path(self, path):
        spath = self.shadow_location + path[len(self.mountpoint):]
        return spath


    def _full_path(self, partial):
        if partial.startswith("/"):
            partial = partial[1:]
        path = os.path.join(self.mountpoint, partial)
        return path

    def get_file_type(self, s3_list_response):
        if s3_list_response.get('CommonPrefixes', None):
            return 'directory'
        elif 'Contents' in s3_list_response:
            if len(s3_list_response['Contents']) > 1 \
                    or s3_list_response['Contents'][0]['Key'].endswith('/') \
                    or s3_list_response['Contents'][0]['Size'] == 0:
                return 'directory'
            else:
                return 'file'
        else:
            return None

    ##File Methods

    def readdir(self, path, fh):
        ##List operation
        print("Inside readdir ## ", path)
        full_path = self._full_path(path)
        prefix = self.get_remote_path(full_path)
        prefix = prefix + '/'
        obj_list_response = self.get_remote_ls(prefix)
        print(obj_list_response)
        dirents = ['.', '..']
        if 'Contents' in obj_list_response:
            for key in obj_list_response['Contents']:
                remote_path = key['Key']
                rel_path = remote_path[len(prefix):].lstrip('/')
                if not rel_path or rel_path == '.infinstor':
                    continue
                local_shadow_path = self.get_shadow_path(os.path.join(full_path, rel_path))
                self.create_tmp_file(local_shadow_path, int(key['Size']))
                dirents.append(rel_path)
        if 'CommonPrefixes' in obj_list_response:
            for key in obj_list_response['CommonPrefixes']:
                remote_path = key['Prefix'].rstrip('/')
                rel_path = remote_path[len(prefix):].lstrip('/')
                if not rel_path or rel_path == '.infinstor':
                    continue
                folder_path = os.path.join(full_path, rel_path)
                local_shadow_folder = self.get_shadow_path(folder_path)
                st = self.create_folder(local_shadow_folder)
                dirents.append(rel_path)
        print(dirents)
        for r in dirents:
            yield r

    def read(self, path, length, offset, fh):
        os.lseek(fh, offset, os.SEEK_SET)
        return os.read(fh, length)

    def open(self, path, flags):
        full_path = self._full_path(path)
        local_shadow_path = self.get_shadow_path(full_path)
        if not os.path.exists(local_shadow_path):
            remote_path = self.get_remote_path(full_path)
            tmp_shadow_file = self.get_temporary_shadow_file(local_shadow_path, ".tmp")
            infin_download.download_objects(local_shadow_path, tmp_shadow_file, self.bucket,
                                        remote_path, self.infinstor_time_spec, self.s3_client)
        return os.open(local_shadow_path, flags)

    def get_remote_ls(self, prefix):
        print("#get_remote_ls#  Bucket = " + self.bucket + ", prefix = " + prefix)
        client = self.get_s3_client()
        paginator = client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=self.bucket, Prefix=prefix, Delimiter='/')

        contents = []
        common_prefixes = []
        for page in pages:
            if 'Contents' in page:
                contents.extend(page['Contents'])
            if 'CommonPrefixes' in page:
                common_prefixes.extend(page['CommonPrefixes'])
        obj_list_response = {'Contents': contents, 'CommonPrefixes': common_prefixes}
        print(obj_list_response)
        return obj_list_response


    def release(self, path, fh):
        return os.close(fh)

    def statfs(self, path):
        stv = os.statvfs(self.shadow_location)
        stat = dict((key, getattr(stv, key)) for key in ('f_bavail', 'f_bfree',
                                                         'f_blocks', 'f_bsize', 'f_favail', 'f_ffree', 'f_files',
                                                         'f_flag',
                                                         'f_frsize', 'f_namemax'))
        print('statfs #', stat)
        return stat

    def getattr(self, path, fh=None):
        print("Inside getattr path = " + path)
        if path == "/":
            st = os.lstat(self.shadow_location)
            return self.get_attr_from_lstat(st)
        full_path = self._full_path(path)
        local_shadow_path = self.get_shadow_path(full_path)
        temp_shadow_file = self.get_temporary_shadow_file(local_shadow_path, ".tmp")
        print(full_path, local_shadow_path, temp_shadow_file)
        if os.path.exists(local_shadow_path):
            st = os.lstat(local_shadow_path)
        elif os.path.exists(temp_shadow_file):
            st = os.lstat(temp_shadow_file)
        else:
            remote_prefix = self.get_remote_path(full_path)
            list_response = self.get_remote_ls(remote_prefix)
            ftype = self.get_file_type(list_response)
            if ftype == "directory":
                st = self.create_folder(local_shadow_path)
            elif ftype == 'file':
                st, tmp_shadow_file = self.create_tmp_file(local_shadow_path, int(list_response['Contents'][0]['Size']))
            else:
                return dict()
        attr = self.get_attr_from_lstat(st)
        return attr

    def get_attr_from_lstat(self, st):
        stat = dict((key, getattr(st, key)) for key in ('st_atime', 'st_ctime',
                                                        'st_gid', 'st_mode', 'st_mtime', 'st_nlink', 'st_size',
                                                        'st_uid'))
        print('get_attr_from_lstat #', stat)
        return stat

    def create_folder(self, shadow_path):
        if not os.path.exists(shadow_path):
            os.makedirs(shadow_path, exist_ok=True)
        return os.lstat(shadow_path)

    def get_temporary_shadow_file(self, local_shadow_path, suffix):
        basename = os.path.basename(local_shadow_path)
        dirname = os.path.dirname(local_shadow_path)
        tmp_shadow_file = dirname + "/.infin-" + basename + suffix
        return tmp_shadow_file

    def create_tmp_file(self, local_shadow_path, size=0):
        tmp_shadow_file = self.get_temporary_shadow_file(local_shadow_path, ".tmp")
        if not os.path.exists(tmp_shadow_file):
            with open(tmp_shadow_file, "w") as fh:
                fh.close()
            #Truncate to actual filesize
            #Note: when the download starts, the file size will be reset
            os.truncate(tmp_shadow_file, size)
        return os.lstat(tmp_shadow_file), tmp_shadow_file
    ## Following methods will do nothing,
    ## but, will not throw exception

    def flush(self, path, fh):
        ##Do Nothing
        pass

    def fsync(self, path, fdatasync, fh):
        ##Do Nothing
        pass

    ##Following methods are not supported
    ##Will throw exception

    def access(self, path, mode):
        ##Access is checked at S3
        return 0

    def chmod(self, path, mode):
        raise ('Not Supported')

    def chown(self, path, uid, gid):
        raise ('Not Supported')

    def readlink(self, path):
        raise('Not Supported')

    def mknod(self, path, mode, dev):
        raise('Not Supported')

    def rmdir(self, path):
        raise('Not Supported')

    def mkdir(self, path, mode):
        raise('Not Supported')

    def unlink(self, path):
        raise ('Not Supported')

    def symlink(self, name, target):
        raise ('Not Supported')

    def rename(self, old, new):
        raise ('Not Supported')

    def link(self, target, name):
        raise ('Not Supported')

    def utimens(self, path, times=None):
        raise ('Not Supported')

    def create(self, path, mode, fi=None):
        raise ('Not Supported')

    def write(self, path, buf, offset, fh):
        raise ('Not Supported')

    def truncate(self, path, length, fh=None):
        raise ('Not Supported')


import sys
import os
import json
import subprocess

from fuse import FUSE, fuse_exit
from concurrent_plugin.infinfs.infinfs import InfinFS

VERBOSE = True

def launch_fuse_infinfs(ifs):
    mountpath = ifs.get_mountpoint()
    if os.path.ismount(mountpath):
        umountp = subprocess.Popen(['umount', '-lf', mountpath], stdout=sys.stdout, stderr=subprocess.STDOUT)
        umountp.wait()
    if VERBOSE:
        FUSE(ifs, mountpath, nothreads=True, foreground=True)
    else:
        FUSE(ifs, mountpath, nothreads=True, foreground=False)
    print("exiting")


if __name__ == '__main__':
    mount_spec_str = sys.argv[1]
    mount_specs = json.loads(mount_spec_str)
    use_cache_str = sys.argv[2]

    if use_cache_str.lower() == 'true':
        use_cache = True
    else:
        use_cache = False

    if len(sys.argv) > 3:
        shadow_base_path = sys.argv[3]
    else:
        shadow_base_path = None

    if mount_specs == None:
        print('Error no input spec found, skipping mount')
        exit(-1)

    ifs = InfinFS(mount_specs, shadow_path=shadow_base_path, use_cache=use_cache)
    launch_fuse_infinfs(ifs)
    exit(0)
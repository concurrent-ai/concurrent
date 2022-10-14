##WARNING: This module globally overrides the stdout
import sys

fuse_debug_handle = None
fuse_debug_file = "/tmp/fuse_debug.log"
fuse_debug_handle = open(fuse_debug_file, "a")

sys.stdout = fuse_debug_handle
sys.stderr = fuse_debug_handle
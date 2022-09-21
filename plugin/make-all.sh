#!/bin/bash
set -e
$SET_X

if [ x"$1" == "x" ] ; then
  echo "Usage: $0 install|dontinstall"
  exit 255
fi

/bin/rm -rf build dist concurrent_plugin.egg-info
python3 ./setup.py sdist bdist_wheel
/bin/rm -rf build concurrent_plugin.egg-info

if [ "$1" == "install" ] ; then
  pip uninstall -y concurrent_plugin
  pip install dist/concurrent_plugin-[0-9].[0-9].[0-9]*-py3-none-any.whl
fi

exit 0

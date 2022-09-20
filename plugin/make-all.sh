#!/bin/bash
set -e
$SET_X

if [ x"$1" == "x" ] ; then
  echo "Usage: $0 install|dontinstall"
  exit 255
fi

/bin/rm -rf build dist parallels_plugin.egg-info
python3 ./setup.py sdist bdist_wheel
/bin/rm -rf build parallels_plugin.egg-info

if [ "$1" == "install" ] ; then
  pip uninstall -y parallels_plugin
  pip install dist/parallels_plugin-[0-9].[0-9].[0-9]*-py3-none-any.whl
fi

exit 0

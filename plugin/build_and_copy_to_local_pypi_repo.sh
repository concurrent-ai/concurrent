#!/bin/bash

set -ex

[ ! -f "./setup.py" ] && { echo "Unable to find ./setup.py.  Change to the right directory and try again.."; exit 1; }

scriptdir=`dirname $0`

# remove any earlier built wheels
ls dist/*.whl && rm -iv dist/*.whl

# build the wheel
python3 setup.py sdist bdist_wheel; 

# delete the 'build' directory created by above command, since it has a copy of the source code.  Interferes with IDE's list of source files
[ -d "$scriptdir/build" ] && rm -R $scriptdir/build

# remove any earlier wheels in the private pypi server's package repository
ls ~/packages/concurrent-plugin/*.whl && rm -iv ~/packages/concurrent-plugin/*.whl

# copy the wheel to the private pypi server
wheel_name=concurrent_plugin-$(python3 setup.py --version)-py3-none-any.whl
cp -ivp dist/$wheel_name ~/packages/concurrent-plugin/

echo "Use the URL: http://cvat.infinstor.com:9876/packages/concurrent-plugin/$wheel_name"

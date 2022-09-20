#!/bin/bash

BUCKET=docs.mlflow-parallels.org

echo "Trying to access bucket s3://${BUCKET}"
aws s3 ls s3://${BUCKET}/ >& /dev/null || { echo "Unable to access bucket s3://${BUCKET}. Fix ~/.aws/credentials and try again" ; exit 1; }
echo "Successfully accessed bucket s3://${BUCKET}. Copying site files. Note: This script does not copy images"

aws s3 rm --recursive s3://${BUCKET}/files/
aws s3 rm --recursive s3://${BUCKET}/search/
aws s3 rm --recursive s3://${BUCKET}/assets/

(cd site; [ -d "files/" ] && aws s3 cp --recursive files/ s3://${BUCKET}/files/)
(cd site; [ -d "search/" ] && aws s3 cp --recursive search/ s3://${BUCKET}/search/)
(cd site; [ -d "assets/" ] && aws s3 cp --recursive assets/ s3://${BUCKET}/assets/ ; )

aws s3 rm --recursive s3://${BUCKET}/404.html
aws s3 rm --recursive s3://${BUCKET}/index.html
aws s3 rm --recursive s3://${BUCKET}/sitemap.xml
aws s3 rm --recursive s3://${BUCKET}/sitemap.xml.gz

(cd site; aws s3 cp 404.html s3://${BUCKET}/404.html)
(cd site; aws s3 cp index.html s3://${BUCKET}/index.html)
(cd site; aws s3 cp sitemap.xml s3://${BUCKET}/sitemap.xml)
(cd site; aws s3 cp sitemap.xml.gz s3://${BUCKET}/sitemap.xml.gz)

if [ x"$MLFLOW_PARALLELS_DOCS_DISTID" != "x" ] ; then
  echo Flushing CloudFront distro $MLFLOW_PARALLELS_DOCS_DISTID
  aws cloudfront create-invalidation --distribution-id ${MLFLOW_PARALLELS_DOCS_DISTID} --paths "/*"
else
  echo MLFLOW_PARALLELS_DOCS_DISTID is not set. CloudFront distro not flushed
fi
exit 0

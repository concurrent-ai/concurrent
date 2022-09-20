#!/bin/bash

BUCKET=mlflow-parallels.org

echo "Trying to access bucket s3://${BUCKET}"
aws s3 ls s3://${BUCKET}/ >& /dev/null || { echo "Unable to access bucket s3://${BUCKET}. Fix ~/.aws/credentials and try again" ; exit 1; }
echo "Successfully accessed bucket s3://${BUCKET}. Copying site files"

aws s3 rm --recursive s3://${BUCKET}/css/
aws s3 rm --recursive s3://${BUCKET}/images/
aws s3 rm --recursive s3://${BUCKET}/js/

(cd site; [ -d "css/" ] && aws s3 cp --recursive css/ s3://${BUCKET}/css/)
(cd site; [ -d "images/" ] && aws s3 cp --recursive images/ s3://${BUCKET}/images/)
(cd site; [ -d "js/" ] && aws s3 cp --recursive js/ s3://${BUCKET}/js/ ; )

aws s3 rm s3://${BUCKET}/401.html
aws s3 rm s3://${BUCKET}/404.html
aws s3 rm s3://${BUCKET}/detail_blog.html
aws s3 rm s3://${BUCKET}/index.html
aws s3 rm s3://${BUCKET}/style-guide.html

(cd site; aws s3 cp 401.html s3://${BUCKET}/401.html)
(cd site; aws s3 cp 404.html s3://${BUCKET}/404.html)
(cd site; aws s3 cp detail_blog.html s3://${BUCKET}/detail_blog.html)
(cd site; aws s3 cp index.html s3://${BUCKET}/index.html)
(cd site; aws s3 cp style-guide.html s3://${BUCKET}/style-guide.html)

if [ x"$MLFLOW_PARALLELS_DISTID" != "x" ] ; then
  echo Flushing CloudFront distro $MLFLOW_PARALLELS_DISTID
  aws cloudfront create-invalidation --distribution-id ${MLFLOW_PARALLELS_DISTID} --paths "/*"
else
  echo MLFLOW_PARALLELS_DISTID is not set. CloudFront distro not flushed
fi
exit 0

"""สร้าง/ลบ S3 bucket ด้วย boto3 (ใช้แทน aws cli ใน terraform local-exec)

ใช้: python s3_bucket.py create <bucket> <region>
     python s3_bucket.py delete <bucket> <region>
อ่าน credentials จาก environment (AWS_ACCESS_KEY_ID / SECRET / SESSION_TOKEN) ที่โหลดไว้ใน terminal
"""
import sys

import boto3
from botocore.exceptions import ClientError


def create(s3, bucket, region):
    kwargs = {"Bucket": bucket}
    if region != "us-east-1":
        kwargs["CreateBucketConfiguration"] = {"LocationConstraint": region}
    try:
        s3.create_bucket(**kwargs)
        print(f"created bucket {bucket}")
    except ClientError as e:
        if e.response["Error"]["Code"] == "BucketAlreadyOwnedByYou":
            print(f"bucket {bucket} already exists (owned by you)")
        else:
            raise


def delete(s3, bucket, region):
    try:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket):
            objs = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            if objs:
                s3.delete_objects(Bucket=bucket, Delete={"Objects": objs})
        s3.delete_bucket(Bucket=bucket)
        print(f"deleted bucket {bucket}")
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchBucket":
            print(f"bucket {bucket} not found, skip")
        else:
            raise


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] not in ("create", "delete"):
        sys.exit(__doc__)
    action, bucket, region = sys.argv[1:]
    client = boto3.client("s3", region_name=region)
    {"create": create, "delete": delete}[action](client, bucket, region)

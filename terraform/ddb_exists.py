"""external data source: เช็คว่าตาราง DynamoDB มีอยู่จริงไหม
อ่าน JSON จาก stdin {"region": "...", "tables": "a,b,c"}
พิมพ์ JSON {"a": "true", "b": "false", ...} (ค่าต้องเป็น string)
"""
import json
import sys

import boto3
from botocore.exceptions import ClientError

q = json.load(sys.stdin)
ddb = boto3.client("dynamodb", region_name=q["region"])
out = {}
for name in filter(None, q["tables"].split(",")):
    try:
        ddb.describe_table(TableName=name)
        out[name] = "true"
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            out[name] = "false"
        else:  # credentials หมดอายุ / ไม่มีสิทธิ์ -> ให้ Terraform แสดง error
            sys.exit(f"describe_table {name}: {e}")
print(json.dumps(out))

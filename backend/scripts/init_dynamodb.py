#!/usr/bin/env python3
"""
init_dynamodb.py
----------------
สคริปต์สำหรับสร้าง DynamoDB Tables สำหรับ NetLab:
1. netlab_users:
   - Primary Key: user_id (S)
   - GSI: UsernameIndex (username - S)
   - GSI: StudentIdIndex (student_id - S)
2. netlab_instances:
   - Primary Key: instance_id (S)
   - GSI: UserIdIndex (user_id - S)
   - GSI: StudentIdIndex (student_id - S)

ใช้ BillingMode = PAY_PER_REQUEST (On-Demand) เพื่อประหยัดค่าใช้จ่ายและรองรับ Learner Lab
"""

import sys
import os
import time

# Ensure backend root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from botocore.exceptions import ClientError
from app.config import get_settings
from app.dynamodb_service import get_dynamodb_client


def create_users_table(client, table_name: str):
    print(f"[*] Checking table: {table_name}...")
    try:
        resp = client.describe_table(TableName=table_name)
        status = resp["Table"]["TableStatus"]
        print(f"[+] Table '{table_name}' already exists (Status: {status}).")
        return
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            print(f"[-] Error describing table '{table_name}': {e}")
            raise

    print(f"[*] Creating table '{table_name}'...")
    client.create_table(
        TableName=table_name,
        KeySchema=[
            {"AttributeName": "user_id", "KeyType": "HASH"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "user_id", "AttributeType": "S"},
            {"AttributeName": "username", "AttributeType": "S"},
            {"AttributeName": "student_id", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "UsernameIndex",
                "KeySchema": [
                    {"AttributeName": "username", "KeyType": "HASH"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                "IndexName": "StudentIdIndex",
                "KeySchema": [
                    {"AttributeName": "student_id", "KeyType": "HASH"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    print(f"[+] Table '{table_name}' creation initiated.")


def create_instances_table(client, table_name: str):
    print(f"[*] Checking table: {table_name}...")
    try:
        resp = client.describe_table(TableName=table_name)
        status = resp["Table"]["TableStatus"]
        print(f"[+] Table '{table_name}' already exists (Status: {status}).")
        return
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            print(f"[-] Error describing table '{table_name}': {e}")
            raise

    print(f"[*] Creating table '{table_name}'...")
    client.create_table(
        TableName=table_name,
        KeySchema=[
            {"AttributeName": "instance_id", "KeyType": "HASH"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "instance_id", "AttributeType": "S"},
            {"AttributeName": "user_id", "AttributeType": "S"},
            {"AttributeName": "student_id", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "UserIdIndex",
                "KeySchema": [
                    {"AttributeName": "user_id", "KeyType": "HASH"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                "IndexName": "StudentIdIndex",
                "KeySchema": [
                    {"AttributeName": "student_id", "KeyType": "HASH"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    print(f"[+] Table '{table_name}' creation initiated.")


def wait_for_table_active(client, table_name: str, timeout: int = 60):
    print(f"[*] Waiting for table '{table_name}' to become ACTIVE...")
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = client.describe_table(TableName=table_name)
            status = resp["Table"]["TableStatus"]
            if status == "ACTIVE":
                print(f"[+] Table '{table_name}' is ACTIVE.")
                return
        except ClientError:
            pass
        time.sleep(2)
    print(f"[!] Warning: Table '{table_name}' did not become ACTIVE within {timeout}s.")


def main():
    settings = get_settings()
    client = get_dynamodb_client()

    print("========================================")
    print("NetLab DynamoDB Initializer")
    print(f"Region: {settings.aws_region}")
    print(f"Users Table: {settings.users_table_name}")
    print(f"Instances Table: {settings.instances_table_name}")
    print("========================================")

    create_users_table(client, settings.users_table_name)
    create_instances_table(client, settings.instances_table_name)

    wait_for_table_active(client, settings.users_table_name)
    wait_for_table_active(client, settings.instances_table_name)

    print("\n[✔] DynamoDB tables initialization complete!")


if __name__ == "__main__":
    main()

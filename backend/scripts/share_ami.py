#!/usr/bin/env python3
"""
share_ami.py
------------
แชร์ GNS3 AMI (และ snapshot ของมัน) ให้ AWS account ของเพื่อน

วิธีใช้:
    python scripts/share_ami.py ami-0123456789abcdef0 111122223333 444455556666

เพื่อนแต่ละคนจะเห็น AMI ใน account ตัวเอง แล้วควร copy เข้า account ตัวเอง
(เพื่อไม่ต้องพึ่ง account ของคุณ ถ้า Learner Lab ถูกรีเซ็ต AMI ต้นทางจะหาย):
    python scripts/bootstrap_aws.py --copy-ami ami-0123456789abcdef0

หมายเหตุ: AMI ที่เข้ารหัสด้วย KMS key ของคุณ แชร์ข้าม account แบบนี้ไม่ได้
"""

import argparse
import sys

import boto3
from botocore.exceptions import ClientError


def main():
    parser = argparse.ArgumentParser(description="Share an AMI with other AWS accounts")
    parser.add_argument("ami_id")
    parser.add_argument("account_ids", nargs="+", help="AWS account ID 12 หลักของเพื่อน")
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args()

    for acc in args.account_ids:
        if not (acc.isdigit() and len(acc) == 12):
            raise SystemExit(f"[-] account id ไม่ถูกต้อง: {acc} (ต้องเป็นตัวเลข 12 หลัก)")

    ec2 = boto3.Session(region_name=args.region).client("ec2")
    try:
        image = ec2.describe_images(ImageIds=[args.ami_id])["Images"][0]
    except (ClientError, IndexError) as e:
        raise SystemExit(f"[-] ไม่พบ AMI {args.ami_id} ใน account นี้: {e}")

    try:
        ec2.modify_image_attribute(
            ImageId=args.ami_id,
            LaunchPermission={"Add": [{"UserId": a} for a in args.account_ids]},
        )
        print(f"[+] AMI {args.ami_id} shared with {', '.join(args.account_ids)}")

        snapshots = [
            m["Ebs"]["SnapshotId"]
            for m in image.get("BlockDeviceMappings", [])
            if "Ebs" in m and m["Ebs"].get("SnapshotId")
        ]
        for snap in snapshots:
            ec2.modify_snapshot_attribute(
                SnapshotId=snap,
                Attribute="createVolumePermission",
                OperationType="add",
                UserIds=args.account_ids,
            )
            print(f"[+] Snapshot {snap} shared")
    except ClientError as e:
        print(f"[-] แชร์ไม่สำเร็จ: {e}")
        sys.exit(1)

    print("\nบอกเพื่อนให้รัน:")
    print(f"    python scripts/bootstrap_aws.py --copy-ami {args.ami_id} --write-credentials --init-db")


if __name__ == "__main__":
    main()

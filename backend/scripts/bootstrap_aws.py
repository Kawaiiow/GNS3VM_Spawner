#!/usr/bin/env python3
"""
bootstrap_aws.py
----------------
ตั้งค่า AWS สำหรับ NetLab ให้พร้อมใช้ด้วยคำสั่งเดียว (รันซ้ำได้ปลอดภัย)

ทำอะไรบ้าง:
  1. หา default VPC (Learner Lab มีให้อยู่แล้ว ไม่ต้องสร้าง VPC / IGW เอง)
  2. สร้าง Security Group สำหรับ GNS3 VM (3080, 5900-5999, และ SSH เฉพาะ IP ของคุณ)
  3. สร้าง Key Pair gns3-cloud-keypair (บันทึก .pem ไว้ในโฟลเดอร์ backend)
  4. หา Instance Profile ของ Learner Lab (LabInstanceProfile)
  5. หา GNS3 Base AMI ในบัญชีนี้ (หรือ copy จาก AMI ที่เพื่อนแชร์ให้ด้วย --copy-ami)
  6. เขียนค่าทั้งหมดลงไฟล์ .env (และสุ่ม JWT_SECRET_KEY ให้ถ้ายังเป็นค่าตัวอย่าง)
  7. (ตัวเลือก) --write-credentials  ก็อป AWS credentials ปัจจุบันลง .env
  8. (ตัวเลือก) --init-db            สร้างตาราง DynamoDB + บัญชีทดสอบ

วิธีใช้ (รันจากโฟลเดอร์ backend, หลังใส่ Learner Lab credentials ใน ~/.aws/credentials):
    python scripts/bootstrap_aws.py --write-credentials --init-db
"""

import argparse
import os
import secrets
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

BACKEND_DIR = Path(__file__).resolve().parent.parent

SG_NAME = "netlab-gns3-vm-sg"
KEY_NAME = "gns3-cloud-keypair"
PREFERRED_PROFILE = "LabInstanceProfile"
AMI_NAME_PREFIX = "netlab-gns3-base"
PROJECT_TAG = "gns3-cloud"


# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------

def update_env(env_path: Path, updates: dict) -> None:
    """อัปเดต/เพิ่ม KEY=VALUE ในไฟล์ .env โดยไม่แตะบรรทัดอื่น"""
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    seen = set()
    out = []
    for line in lines:
        stripped = line.strip()
        key = None
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
        if key in updates:
            out.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            out.append(line)
    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={value}")
    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")


def read_env(env_path: Path) -> dict:
    values = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                values[k.strip()] = v.strip()
    return values


def detect_public_cidr():
    try:
        with urllib.request.urlopen("https://checkip.amazonaws.com", timeout=5) as r:
            return r.read().decode().strip() + "/32"
    except Exception:
        return None


# ------------------------------------------------------------------
# AWS steps
# ------------------------------------------------------------------

def get_default_vpc(ec2) -> str:
    vpcs = ec2.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])["Vpcs"]
    if not vpcs:
        raise SystemExit(
            "[-] ไม่พบ default VPC ในบัญชีนี้ (ต้องสร้าง VPC เอง หรือใช้ "
            "`aws ec2 create-default-vpc`)"
        )
    return vpcs[0]["VpcId"]


def ensure_security_group(ec2, vpc_id: str, ssh_cidr) -> str:
    found = ec2.describe_security_groups(
        Filters=[
            {"Name": "group-name", "Values": [SG_NAME]},
            {"Name": "vpc-id", "Values": [vpc_id]},
        ]
    )["SecurityGroups"]
    if found:
        sg_id = found[0]["GroupId"]
        print(f"[+] Security Group exists: {sg_id}")
    else:
        sg_id = ec2.create_security_group(
            GroupName=SG_NAME,
            Description="NetLab GNS3 VM - 3080, 5900-5999, ssh admin",
            VpcId=vpc_id,
            TagSpecifications=[
                {
                    "ResourceType": "security-group",
                    "Tags": [{"Key": "Project", "Value": PROJECT_TAG}],
                }
            ],
        )["GroupId"]
        print(f"[+] Security Group created: {sg_id}")

    rules = [
        (3080, 3080, "0.0.0.0/0", "GNS3 server"),
        (5900, 5999, "0.0.0.0/0", "GNS3 consoles"),
    ]
    if ssh_cidr:
        rules.append((22, 22, ssh_cidr, "SSH admin"))
    for lo, hi, cidr, desc in rules:
        try:
            ec2.authorize_security_group_ingress(
                GroupId=sg_id,
                IpPermissions=[
                    {
                        "IpProtocol": "tcp",
                        "FromPort": lo,
                        "ToPort": hi,
                        "IpRanges": [{"CidrIp": cidr, "Description": desc}],
                    }
                ],
            )
            print(f"    + allow tcp {lo}-{hi} from {cidr}")
        except ClientError as e:
            if e.response["Error"]["Code"] != "InvalidPermission.Duplicate":
                raise
    return sg_id


def ensure_key_pair(ec2, name: str, pem_path: Path) -> None:
    try:
        ec2.describe_key_pairs(KeyNames=[name])
        exists = True
    except ClientError as e:
        if e.response["Error"]["Code"] != "InvalidKeyPair.NotFound":
            raise
        exists = False

    if exists:
        print(f"[+] Key pair exists: {name}")
        if not pem_path.exists():
            print(f"    [!] ไม่พบไฟล์ {pem_path.name} ในเครื่องนี้ (AWS ให้ private key ครั้งเดียวตอนสร้าง)")
        return

    material = ec2.create_key_pair(KeyName=name)["KeyMaterial"]
    with open(pem_path, "w", encoding="ascii", newline="\n") as f:
        f.write(material)
    try:
        os.chmod(pem_path, 0o600)
    except OSError:
        pass
    print(f"[+] Key pair created: {name} -> {pem_path}")
    if os.name == "nt":
        print(
            f'    Windows: ก่อน ssh ให้รัน  icacls .\\{pem_path.name} /inheritance:r  แล้ว  '
            f'icacls .\\{pem_path.name} /grant:r "$($env:USERNAME):R"'
        )


def find_instance_profile(session):
    try:
        iam = session.client("iam")
        profiles = []
        for page in iam.get_paginator("list_instance_profiles").paginate():
            profiles.extend(page["InstanceProfiles"])
    except ClientError as e:
        print(f"[!] อ่านรายการ Instance Profile ไม่ได้ ({e.response['Error']['Code']}) ใช้ค่า {PREFERRED_PROFILE}")
        return PREFERRED_PROFILE

    names = [p["InstanceProfileName"] for p in profiles]
    if PREFERRED_PROFILE in names:
        return PREFERRED_PROFILE
    for p in profiles:
        if any(r["RoleName"] == "LabRole" for r in p.get("Roles", [])):
            return p["InstanceProfileName"]
    return None


def find_base_ami(ec2):
    images = ec2.describe_images(
        Owners=["self"],
        Filters=[
            {"Name": "name", "Values": [f"{AMI_NAME_PREFIX}*"]},
            {"Name": "state", "Values": ["available"]},
        ],
    )["Images"]
    if not images:
        return None
    return sorted(images, key=lambda i: i["CreationDate"])[-1]["ImageId"]


def copy_shared_ami(ec2, source_id: str, region: str) -> str:
    name = f"{AMI_NAME_PREFIX}-copy-{time.strftime('%Y%m%d-%H%M%S')}"
    print(f"[*] Copying shared AMI {source_id} into this account...")
    new_id = ec2.copy_image(
        SourceImageId=source_id, SourceRegion=region, Name=name,
        Description="NetLab GNS3 base image (copy)",
    )["ImageId"]
    ec2.create_tags(
        Resources=[new_id],
        Tags=[{"Key": "Project", "Value": PROJECT_TAG}, {"Key": "Name", "Value": name}],
    )
    ec2.get_waiter("image_available").wait(
        ImageIds=[new_id], WaiterConfig={"Delay": 15, "MaxAttempts": 80}
    )
    print(f"[+] AMI copied: {new_id}")
    return new_id


# ------------------------------------------------------------------
# main
# ------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Bootstrap AWS resources + .env for NetLab")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--env-file", default=str(BACKEND_DIR / ".env"))
    parser.add_argument("--ssh-cidr", help="CIDR ที่อนุญาต SSH เช่น 1.2.3.4/32 (ค่าเริ่มต้น: IP ปัจจุบันของคุณ)")
    parser.add_argument("--no-ssh", action="store_true", help="ไม่เปิด port 22")
    parser.add_argument("--ami-id", help="ใช้ AMI นี้ (ที่อยู่ในบัญชีของคุณแล้ว)")
    parser.add_argument("--copy-ami", help="copy AMI ที่เพื่อนแชร์ให้ (ami-xxxx) เข้าบัญชีตัวเอง")
    parser.add_argument("--instance-type", help="ตั้ง DEFAULT_INSTANCE_TYPE ใน .env (เช่น t3.medium)")
    parser.add_argument("--write-credentials", action="store_true",
                        help="ก็อป AWS credentials ปัจจุบัน (รวม session token) ลง .env")
    parser.add_argument("--init-db", action="store_true",
                        help="รัน init_dynamodb.py --seed หลังตั้งค่าเสร็จ")
    args = parser.parse_args()

    session = boto3.Session(region_name=args.region)
    creds = session.get_credentials()
    if creds is None:
        raise SystemExit(
            "[-] ไม่พบ AWS credentials ใส่ค่าจาก Learner Lab (AWS Details) ใน ~/.aws/credentials ก่อน"
        )
    ec2 = session.client("ec2")

    try:
        ident = session.client("sts").get_caller_identity()
    except (ClientError, NoCredentialsError) as e:
        raise SystemExit(f"[-] credentials ใช้ไม่ได้ (หมดอายุ?): {e}")
    print(f"[*] Account {ident['Account']} | Region {args.region}")

    env_path = Path(args.env_file)
    if not env_path.exists():
        example = BACKEND_DIR / ".env.example"
        if example.exists():
            env_path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"[+] Created {env_path.name} from .env.example")
        else:
            env_path.write_text("", encoding="utf-8")
            print(f"[+] Created empty {env_path.name}")

    vpc_id = get_default_vpc(ec2)
    print(f"[+] Default VPC: {vpc_id}")

    ssh_cidr = None
    if not args.no_ssh:
        ssh_cidr = args.ssh_cidr or detect_public_cidr()
        if not ssh_cidr:
            print("[!] หา IP ของคุณไม่ได้ จึงไม่เปิด port 22 (ระบุเองได้ด้วย --ssh-cidr)")

    sg_id = ensure_security_group(ec2, vpc_id, ssh_cidr)
    ensure_key_pair(ec2, KEY_NAME, BACKEND_DIR / f"{KEY_NAME}.pem")

    profile = find_instance_profile(session)
    if profile:
        print(f"[+] Instance profile: {profile}")
    else:
        print("[!] ไม่พบ Instance Profile (VM จะถูกสร้างโดยไม่มี profile)")

    if args.copy_ami:
        ami_id = copy_shared_ami(ec2, args.copy_ami, args.region)
    elif args.ami_id:
        ami_id = args.ami_id
    else:
        ami_id = find_base_ami(ec2)
    if ami_id:
        print(f"[+] GNS3 AMI: {ami_id}")
    else:
        print(
            "[!] ยังไม่มี GNS3 AMI ในบัญชีนี้ ให้รันอย่างใดอย่างหนึ่ง:\n"
            "      python scripts/build_gns3_ami.py --write-env      (สร้างเองจากศูนย์)\n"
            "      python scripts/bootstrap_aws.py --copy-ami ami-xxxx (copy จากที่เพื่อนแชร์)"
        )

    updates = {
        "AWS_REGION": args.region,
        "DEFAULT_KEY_NAME": KEY_NAME,
        "DEFAULT_SECURITY_GROUP_ID": sg_id,
        "INSTANCE_PROFILE_NAME": profile or "",
    }
    if ami_id:
        updates["DEFAULT_AMI_ID"] = ami_id
    if args.instance_type:
        updates["DEFAULT_INSTANCE_TYPE"] = args.instance_type
    if args.write_credentials:
        frozen = creds.get_frozen_credentials()
        updates["AWS_ACCESS_KEY_ID"] = frozen.access_key
        updates["AWS_SECRET_ACCESS_KEY"] = frozen.secret_key
        updates["AWS_SESSION_TOKEN"] = frozen.token or ""

    current = read_env(env_path)
    jwt = current.get("JWT_SECRET_KEY", "")
    if not jwt or "change" in jwt.lower() or "secret-key" in jwt.lower():
        updates["JWT_SECRET_KEY"] = secrets.token_urlsafe(48)
        print("[+] Generated a random JWT_SECRET_KEY")

    update_env(env_path, updates)
    print(f"[+] Updated {env_path}")

    if args.init_db:
        print("[*] Initializing DynamoDB tables + test users...")
        subprocess.run(
            [sys.executable, str(BACKEND_DIR / "scripts" / "init_dynamodb.py"), "--seed"],
            cwd=str(BACKEND_DIR), check=True,
        )

    print("\n[✔] Bootstrap complete. Next:")
    if not args.write_credentials:
        print("    - ใส่ AWS_ACCESS_KEY_ID / SECRET / SESSION_TOKEN ใน .env (หรือรันซ้ำพร้อม --write-credentials)")
    if not args.init_db:
        print("    - python scripts/init_dynamodb.py --seed")
    if not ami_id:
        print("    - สร้าง/copy GNS3 AMI (ดูข้อความด้านบน)")
    print("    - uvicorn app.main:app --reload --host 0.0.0.0 --port 8000")


if __name__ == "__main__":
    main()
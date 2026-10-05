#!/usr/bin/env python3
"""
build_gns3_ami.py
-----------------
สร้าง GNS3 Base AMI จากศูนย์ ด้วยคำสั่งเดียว (ไม่ต้องตั้งค่า VM ด้วยมือ)

ขั้นตอน:
  1. หา Ubuntu 24.04 AMI ล่าสุดของ Canonical
  2. เปิด builder VM ชั่วคราว พร้อม UserData ที่ติดตั้ง GNS3 จาก PPA ทางการ
     (gns3-server + docker.io + qemu/dynamips/ubridge/vpcs ที่มากับแพ็กเกจ),
     ตั้ง gns3_server.conf (auth เปิด, port 3080, console 5900-5999),
     ติดตั้ง systemd service แล้วทดสอบเรียก /v2/version
  3. ถ้าผ่าน builder จะพิมพ์ NETLAB_BUILD_OK ลง console แล้วปิดเครื่องตัวเอง
  4. สคริปต์นี้อ่าน console output, สร้าง AMI จาก builder, แล้ว terminate builder
  5. (ตัวเลือก) --write-env  เขียน DEFAULT_AMI_ID ลง .env

วิธีใช้ (รันจากโฟลเดอร์ backend):
    python scripts/bootstrap_aws.py            # สร้าง Security Group ก่อน
    python scripts/build_gns3_ami.py --write-env

ใช้เวลาประมาณ 10-20 นาที และใช้เครดิตเล็กน้อย (builder ถูก terminate ตอนจบ)
หมายเหตุ: รหัสผ่าน GNS3 ใน AMI เป็นค่าสุ่มชั่วคราว VM แต่ละเครื่องจะถูกตั้งรหัสผ่านใหม่
ตอน launch (ดู ec2_service.py)
"""

import argparse
import secrets
import string
import sys
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bootstrap_aws import (  # noqa: E402
    AMI_NAME_PREFIX,
    BACKEND_DIR,
    PROJECT_TAG,
    SG_NAME,
    update_env,
)

UBUNTU_OWNER = "099720109477"  # Canonical
UBUNTU_NAME = "ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"

USER_DATA_TEMPLATE = r"""#!/bin/bash
# NetLab: build GNS3 base image (runs once on the temporary builder VM)
export DEBIAN_FRONTEND=noninteractive
LOG=/var/log/netlab-build.log
fail() { echo "NETLAB_BUILD_FAILED: $1" > /dev/console; sync; poweroff; exit 1; }

apt-get update -y >>$LOG 2>&1 || fail "apt update"
apt-get install -y software-properties-common curl >>$LOG 2>&1 || fail "base packages"
add-apt-repository -y ppa:gns3/ppa >>$LOG 2>&1 || fail "add gns3 ppa"
echo "ubridge ubridge/install-setuid boolean true" | debconf-set-selections
echo "wireshark-common wireshark-common/install-setuid boolean true" | debconf-set-selections
apt-get update -y >>$LOG 2>&1 || fail "apt update (ppa)"
apt-get install -y gns3-server docker.io >>$LOG 2>&1 || fail "install gns3-server"

# user ubuntu ต้องอยู่ในกลุ่มที่ GNS3 ใช้ (ข้ามกลุ่มที่ไม่มีอยู่จริง)
for g in kvm libvirt ubridge wireshark docker; do
  getent group "$g" >/dev/null && usermod -aG "$g" ubuntu
done

mkdir -p /home/ubuntu/.config/GNS3/2.2
cat > /home/ubuntu/.config/GNS3/2.2/gns3_server.conf <<'NETLAB_CONF'
[Server]
host = 0.0.0.0
port = 3080
auth = True
user = gns3
password = __BUILD_PASSWORD__
console_start_port_range = 5900
console_end_port_range = 5999
NETLAB_CONF
chown -R ubuntu:ubuntu /home/ubuntu/.config
chmod 600 /home/ubuntu/.config/GNS3/2.2/gns3_server.conf

cat > /etc/systemd/system/gns3-server.service <<'NETLAB_UNIT'
[Unit]
Description=GNS3 server
After=network.target

[Service]
Type=simple
User=ubuntu
ExecStart=/usr/bin/gns3server
Restart=on-failure

[Install]
WantedBy=multi-user.target
NETLAB_UNIT
systemctl daemon-reload
systemctl enable --now gns3-server >>$LOG 2>&1 || fail "start gns3-server"

# ทดสอบว่า GNS3 ตอบที่ port 3080 และ auth ทำงาน
ok=0
for i in $(seq 1 40); do
  code=$(curl -s -o /dev/null -w "%{http_code}" -u "gns3:__BUILD_PASSWORD__" http://localhost:3080/v2/version)
  if [ "$code" = "200" ]; then ok=1; break; fi
  sleep 3
done
[ "$ok" = "1" ] || fail "gns3 did not answer 200 on :3080"
noauth=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:3080/v2/version)
[ "$noauth" = "401" ] || fail "auth is not enforced (got $noauth)"
VER=$(curl -s -u "gns3:__BUILD_PASSWORD__" http://localhost:3080/v2/version | tr -d ' \n')

# เก็บกวาดก่อนทำ AMI (ไม่ให้ log / UserData ที่มีรหัสชั่วคราวติดไปกับ image)
apt-get clean
rm -rf /var/lib/apt/lists/*
rm -f /home/ubuntu/.ssh/authorized_keys /root/.ssh/authorized_keys
rm -f "$LOG"
rm -rf /var/lib/cloud/instances/*/scripts /var/lib/cloud/instances/*/user-data.txt*

echo "NETLAB_BUILD_OK gns3=$VER" > /dev/console
sync
poweroff
"""


def build_user_data() -> str:
    alphabet = string.ascii_letters + string.digits
    password = "".join(secrets.choice(alphabet) for _ in range(24))
    return USER_DATA_TEMPLATE.replace("__BUILD_PASSWORD__", password)


# ------------------------------------------------------------------
# AWS helpers (แยกเป็นฟังก์ชันเล็กๆ เพื่อให้ทดสอบ/แทนที่ได้ง่าย)
# ------------------------------------------------------------------

def find_ubuntu_ami(ec2) -> str:
    images = ec2.describe_images(
        Owners=[UBUNTU_OWNER],
        Filters=[
            {"Name": "name", "Values": [UBUNTU_NAME]},
            {"Name": "state", "Values": ["available"]},
        ],
    )["Images"]
    if not images:
        raise SystemExit("[-] ไม่พบ Ubuntu 24.04 AMI (ระบุเองด้วย --base-ami)")
    return sorted(images, key=lambda i: i["CreationDate"])[-1]["ImageId"]


def find_security_group(ec2, name: str):
    found = ec2.describe_security_groups(
        Filters=[{"Name": "group-name", "Values": [name]}]
    )["SecurityGroups"]
    return found[0]["GroupId"] if found else None


def wait_stopped(ec2, instance_id: str, minutes: int = 40) -> None:
    """รอจน builder ปิดเครื่องเอง (stopped)

    ไม่ใช้ waiter "instance_stopped" ของ boto3 เพราะมันถือว่าสถานะ "pending"
    เป็น failure ทำให้พังทันทีที่เครื่องเพิ่งเปิด จึง poll เองแทน
    """
    deadline = time.time() + minutes * 60
    last = None
    while time.time() < deadline:
        try:
            resp = ec2.describe_instances(InstanceIds=[instance_id])
            state = resp["Reservations"][0]["Instances"][0]["State"]["Name"]
        except (ClientError, IndexError, KeyError):
            time.sleep(5)  # instance เพิ่งสร้าง AWS อาจยังไม่เห็น ลองใหม่
            continue
        if state != last:
            print(f"    builder state: {state}")
            last = state
        if state == "stopped":
            return
        if state in ("shutting-down", "terminated"):
            raise SystemExit(f"[-] builder ถูก terminate ระหว่าง build (state={state})")
        time.sleep(15)
    raise SystemExit(f"[-] รอ builder ปิดเครื่องเกิน {minutes} นาที (ยังเป็น {last})")


def read_console(ec2, instance_id: str, attempts: int = 36) -> str:
    """อ่าน console output จนกว่าจะเจอ marker (console อาจมาช้ากว่า instance stop หลายนาที)"""
    out = ""
    for i in range(attempts):
        try:
            out = ec2.get_console_output(InstanceId=instance_id, Latest=True).get("Output", "") or ""
        except ClientError:
            try:
                out = ec2.get_console_output(InstanceId=instance_id).get("Output", "") or ""
            except ClientError:
                out = ""
        if "NETLAB_BUILD_OK" in out or "NETLAB_BUILD_FAILED" in out:
            return out
        if i == 0:
            print("    รอ console output จาก AWS (อาจใช้เวลาหลายนาที)...")
        time.sleep(10)
    return out


def wait_image(ec2, image_id: str) -> None:
    ec2.get_waiter("image_available").wait(
        ImageIds=[image_id], WaiterConfig={"Delay": 15, "MaxAttempts": 120}
    )


def main():
    parser = argparse.ArgumentParser(description="Build the NetLab GNS3 base AMI")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--instance-type", default="t3.medium", help="ชนิดเครื่อง builder")
    parser.add_argument("--volume-gb", type=int, default=16, help="ขนาด root disk (GB)")
    parser.add_argument("--base-ami", help="ใช้ AMI นี้เป็นฐานแทน Ubuntu 24.04 ล่าสุด")
    parser.add_argument("--security-group", help="Security Group ID (ค่าเริ่มต้น: netlab-gns3-vm-sg)")
    parser.add_argument("--name", help="ชื่อ AMI (ค่าเริ่มต้น netlab-gns3-base-<เวลา>)")
    parser.add_argument("--write-env", action="store_true", help="เขียน DEFAULT_AMI_ID ลง .env")
    parser.add_argument("--keep-builder", action="store_true",
                        help="ไม่ terminate builder เมื่อ build ล้มเหลว (ไว้ดีบั๊ก)")
    parser.add_argument("--print-userdata", action="store_true",
                        help="พิมพ์สคริปต์ติดตั้งแล้วจบ (ไม่เรียก AWS)")
    args = parser.parse_args()

    if args.print_userdata:
        print(build_user_data())
        return

    session = boto3.Session(region_name=args.region)
    if session.get_credentials() is None:
        raise SystemExit("[-] ไม่พบ AWS credentials (ใส่ใน ~/.aws/credentials ก่อน)")
    ec2 = session.client("ec2")

    base_ami = args.base_ami or find_ubuntu_ami(ec2)
    sg_id = args.security_group or find_security_group(ec2, SG_NAME)
    if not sg_id:
        print(f"[!] ไม่พบ Security Group {SG_NAME} (รัน bootstrap_aws.py ก่อน) ใช้ default SG ของ VPC")

    print(f"[*] Base image: {base_ami}")
    run_kwargs = dict(
        ImageId=base_ami,
        InstanceType=args.instance_type,
        MinCount=1,
        MaxCount=1,
        UserData=build_user_data(),
        BlockDeviceMappings=[
            {
                "DeviceName": "/dev/sda1",
                "Ebs": {"VolumeSize": args.volume_gb, "VolumeType": "gp3", "DeleteOnTermination": True},
            }
        ],
        TagSpecifications=[
            {
                "ResourceType": "instance",
                "Tags": [
                    {"Key": "Name", "Value": "netlab-gns3-ami-builder"},
                    {"Key": "Project", "Value": PROJECT_TAG},
                ],
            }
        ],
    )
    if sg_id:
        run_kwargs["SecurityGroupIds"] = [sg_id]

    instance_id = ec2.run_instances(**run_kwargs)["Instances"][0]["InstanceId"]
    print(f"[*] Builder launched: {instance_id} (ติดตั้ง GNS3 ประมาณ 10-20 นาที)")

    success = False
    try:
        wait_stopped(ec2, instance_id)
        console = read_console(ec2, instance_id)
        if "NETLAB_BUILD_OK" not in console:
            reason = next((l for l in console.splitlines() if "NETLAB_BUILD_FAILED" in l), None)
            print(f"[-] Build ล้มเหลว: {reason or 'ไม่พบ marker ใน console output'}")
            tail = "\n".join(console.splitlines()[-40:]) if console else "(console output ว่างเปล่า)"
            print("---------- console output (40 บรรทัดสุดท้าย) ----------")
            print(tail)
            print("-------------------------------------------------------")
            print("    ดู log ได้ด้วย: aws ec2 get-console-output --instance-id "
                  f"{instance_id} --latest --output text --region {args.region}  (พิมพ์ --region ติดกันเป็นคำเดียว)")
            sys.exit(1)
        ver = next((l for l in console.splitlines() if "NETLAB_BUILD_OK" in l), "").strip()
        print(f"[+] Builder reports: {ver[ver.index('NETLAB_BUILD_OK'):]}")

        name = args.name or f"{AMI_NAME_PREFIX}-{time.strftime('%Y%m%d-%H%M%S')}"
        tags = [{"Key": "Project", "Value": PROJECT_TAG}, {"Key": "Name", "Value": name}]
        image_id = ec2.create_image(
            InstanceId=instance_id,
            Name=name,
            Description="NetLab GNS3 base image (Ubuntu 24.04 + GNS3 2.2 PPA)",
            TagSpecifications=[
                {"ResourceType": "image", "Tags": tags},
                {"ResourceType": "snapshot", "Tags": tags},
            ],
        )["ImageId"]
        print(f"[*] Creating AMI {image_id} ...")
        wait_image(ec2, image_id)
        print(f"[✔] AMI ready: {image_id}  ({name})")
        success = True
    finally:
        if success or not args.keep_builder:
            try:
                ec2.terminate_instances(InstanceIds=[instance_id])
                print(f"[*] Builder {instance_id} terminated")
            except ClientError as e:
                print(f"[!] terminate builder ไม่สำเร็จ ({e}) กรุณาลบเองใน EC2 console")
        else:
            print(f"[!] Builder {instance_id} ยังอยู่ (--keep-builder) อย่าลืม terminate")

    if args.write_env:
        update_env(BACKEND_DIR / ".env", {"DEFAULT_AMI_ID": image_id})
        print(f"[+] .env: DEFAULT_AMI_ID={image_id}")
    else:
        print(f"    ใส่ใน .env:  DEFAULT_AMI_ID={image_id}")
    print("    แชร์ให้เพื่อน:  python scripts/share_ami.py "
          f"{image_id} <ACCOUNT_ID_ของเพื่อน>")


if __name__ == "__main__":
    main()
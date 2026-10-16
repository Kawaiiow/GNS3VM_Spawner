#!/bin/bash
# Backend (FastAPI :8000) - รันบนเครื่องใน ASG หลาย AZ ข้างหลัง internal ALB
set -euxo pipefail

dnf install -y docker git
systemctl enable --now docker

# ปิด xtrace ตอน clone เพื่อไม่ให้ token โผล่ใน /var/log/cloud-init-output.log
set +x
git clone --branch ${repo_branch} "${clone_url}" /opt/app
# เปลี่ยน remote กลับเป็น URL ที่ไม่มี token (ไม่ให้ค้างใน /opt/app/.git/config)
git -C /opt/app remote set-url origin "${repo_url}"
set -x
cd /opt/app

# ไม่ใส่ AWS_ACCESS_KEY_ID / SECRET / SESSION_TOKEN: boto3 จะใช้ LabInstanceProfile
# ของเครื่องนี้เอง (credentials หมุนเวียนอัตโนมัติ ไม่หมดอายุตาม session)
# JWT_SECRET_KEY ต้องเป็นค่าเดียวกันทุกเครื่อง backend (มาจาก Terraform random_password)
set +x
cat > backend/.env <<ENV
AWS_REGION=${region}
DEFAULT_AMI_ID=${ami_id}
DEFAULT_INSTANCE_TYPE=${lab_instance_type}
DEFAULT_KEY_NAME=${key_name}
DEFAULT_SECURITY_GROUP_ID=${lab_sg_id}
INSTANCE_PROFILE_NAME=${instance_profile}
MAX_CONCURRENT_INSTANCES=${max_instances}
USERS_TABLE_NAME=${users_table}
INSTANCES_TABLE_NAME=${instances_table}
EXERCISES_TABLE_NAME=${exercises_table}
SNAPSHOTS_BUCKET=${snapshots_bucket}
SNAPSHOTS_PREFIX=exercises
JWT_SECRET_KEY=${jwt_secret}
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=1440
ENV
chmod 600 backend/.env
set -x

docker build -t netlab-backend ./backend
docker run -d --name backend --restart unless-stopped \
  --env-file /opt/app/backend/.env -p 8000:8000 netlab-backend

# --- สร้าง admin คนแรก ---
# ทำเฉพาะเครื่องที่อยู่ AZ ${admin_az} เครื่องเดียว กัน 2 เครื่องสร้างพร้อมกันจนได้ user ซ้ำ
# (create_user.py เช็คแล้วค่อยเขียน ไม่ใช่ conditional write) ถ้าเครื่องถูกสร้างใหม่ทีหลัง
# จะเจอ "already exists" แล้วข้ามเอง
IMDS_TOKEN=$(curl -s -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 300")
MY_AZ=$(curl -s -H "X-aws-ec2-metadata-token: $IMDS_TOKEN" http://169.254.169.254/latest/meta-data/placement/availability-zone)
echo "this instance AZ: $MY_AZ (admin AZ: ${admin_az})"

if [ "$MY_AZ" = "${admin_az}" ]; then
  # ปิด xtrace กันรหัสผ่านโผล่ใน /var/log/cloud-init-output.log
  set +x
  ADMIN_PW=$(echo '${admin_password_b64}' | base64 -d)
  ADMIN_CREATED=no
  for i in $(seq 1 20); do
    if out=$(docker run --rm --env-file /opt/app/backend/.env \
          -v /opt/app/backend/scripts:/app/scripts netlab-backend \
          python scripts/create_user.py \
            -u '${admin_username}' -m '${admin_member_id}' \
            -p "$ADMIN_PW" -r admin 2>&1); then
      echo "$out"
      ADMIN_CREATED=yes
      break
    else
      echo "$out"
      # create_user.py exit 1 พร้อม "already exists" เมื่อมี user อยู่แล้ว -> ไม่ต้อง retry
      if grep -q "already exists" <<<"$out"; then
        ADMIN_CREATED=exists
        break
      fi
      echo "create admin failed (DynamoDB ยังไม่พร้อม?) retry $i/20 ..."
      sleep 15
    fi
  done
  unset ADMIN_PW out
  set -x
  echo "admin status: $ADMIN_CREATED"
fi

# ลบสำเนา user-data บนดิสก์ (มี token / รหัสผ่าน admin / JWT secret)
# ยังเหลือใน instance metadata จึงควร revoke token และเปลี่ยนรหัส admin หลัง deploy
rm -f /var/lib/cloud/instances/*/user-data.txt* /var/lib/cloud/instances/*/scripts/* || true

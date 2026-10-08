#!/bin/bash
set -euxo pipefail

dnf install -y docker git
systemctl enable --now docker

mkdir -p /usr/local/lib/docker/cli-plugins
curl -SL https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-x86_64 \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# ปิด xtrace ตอน clone เพื่อไม่ให้ token โผล่ใน /var/log/cloud-init-output.log
set +x
git clone --branch ${repo_branch} "${clone_url}" /opt/app
# เปลี่ยน remote กลับเป็น URL ที่ไม่มี token (ไม่ให้ค้างใน /opt/app/.git/config)
git -C /opt/app remote set-url origin "${repo_url}"
set -x
cd /opt/app

JWT=$(head -c 48 /dev/urandom | base64 | tr -d '\n=+/')

# ไม่ใส่ AWS_ACCESS_KEY_ID / SECRET / SESSION_TOKEN: boto3 จะใช้ LabInstanceProfile
# ของเครื่องนี้เอง (credentials หมุนเวียนอัตโนมัติ ไม่หมดอายุตาม session)
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
JWT_SECRET_KEY=$JWT
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=1440
ENV
chmod 600 backend/.env

docker compose up -d --build

# --- สร้าง admin คนแรก ---
# ปิด xtrace กันรหัสผ่านโผล่ใน /var/log/cloud-init-output.log
set +x
ADMIN_PW=$(echo '${admin_password_b64}' | base64 -d)
ADMIN_CREATED=no
for i in $(seq 1 20); do
  if out=$(docker compose run --rm -T \
        -v /opt/app/backend/scripts:/app/scripts backend \
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
    echo "create admin failed (backend/DynamoDB ยังไม่พร้อม?) retry $i/20 ..."
    sleep 15
  fi
done
unset ADMIN_PW out
set -x
echo "admin status: $ADMIN_CREATED"

# ลบสำเนา user-data บนดิสก์ (มี token และ/หรือรหัสผ่าน admin)
# ยังเหลือใน instance metadata จึงควร revoke token และเปลี่ยนรหัส admin หลัง deploy
rm -f /var/lib/cloud/instances/*/user-data.txt* /var/lib/cloud/instances/*/scripts/* || true

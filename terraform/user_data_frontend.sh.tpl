#!/bin/bash
# Frontend (FastAPI + Jinja :8080) - รันบนเครื่องใน ASG หลาย AZ ข้างหลัง ALB สาธารณะ
# เรียก backend ผ่าน internal ALB (BACKEND_URL) ไม่มี AWS credentials บนเครื่องนี้
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

docker build -t netlab-frontend ./frontend
docker run -d --name frontend --restart unless-stopped \
  -e BACKEND_URL=${backend_url} \
  -e PROTOCOL_HEADER=x-forwarded-proto \
  -e HOST_HEADER=x-forwarded-host \
  -p 8080:8080 netlab-frontend

rm -f /var/lib/cloud/instances/*/user-data.txt* /var/lib/cloud/instances/*/scripts/* || true

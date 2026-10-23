# Terraform: Deploy NetLab บน AWS Learner Lab

Terraform ชุดนี้สร้างโครงสร้างสำหรับรันเว็บ NetLab แบบ **แยก Frontend / Backend และกระจายหลาย AZ (High Availability)**
อยู่หลัง Application Load Balancer พร้อมทรัพยากรที่ backend ต้องใช้ (DynamoDB, S3, Security Group)

```
                      Internet
                         │ HTTPS :443 / HTTP :80 (redirect)
                ┌────────▼─────────┐
                │ ALB สาธารณะ      │  (2 AZ, SSL/TLS)
                └────────┬─────────┘
                         │ :8080
        ┌────────────────▼────────────────┐
        │ Frontend ASG   AZ-a  │  AZ-b    │  FastAPI + Jinja (server-rendered)
        └────────────────┬────────────────┘
                         │ BACKEND_URL (เรียกจากฝั่ง server ไม่ใช่เบราว์เซอร์)
                ┌────────▼─────────┐
                │ ALB ภายใน (8000) │  เข้าได้เฉพาะใน VPC
                └────────┬─────────┘
        ┌────────────────▼────────────────┐
        │ Backend ASG    AZ-a  │  AZ-b    │  FastAPI (stateless, JWT)
        └────────────────┬────────────────┘
                         │ boto3 (LabInstanceProfile)
          ┌──────────────┼───────────────┬───────────────────────┐
          ▼              ▼               ▼                       ▼
     DynamoDB        S3 (private)     EC2 API  ──สร้าง──►  GNS3 VM นักศึกษา
   (multi-AZ ในตัว)  (multi-AZ ในตัว)                      (AZ ไหนก็ได้ ไม่มีสำรอง)
```

- Frontend/Backend แต่ละฝั่งมี **2 เครื่อง คนละ AZ** ถ้า AZ หนึ่งล่ม ALB จะส่งต่อไปอีก AZ และ ASG สร้างเครื่องใหม่ทดแทน
- **GNS3 VM ที่ API สร้างไม่ได้สำรองและไม่ผูก AZ**: backend ไม่ระบุ subnet AWS เลือก AZ ให้เอง ถ้า AZ นั้นล่ม VM ในนั้นหายไป ให้ผู้ใช้ลบแล้วสร้างใหม่ (ข้อมูลที่สำคัญอยู่ใน S3/DynamoDB)
- ข้อมูลทั้งหมดอยู่ใน DynamoDB/S3 ตัว backend จึง stateless (login ใช้ JWT, secret ชุดเดียวกันทุกเครื่อง)

## สิ่งที่ Terraform สร้าง

| ไฟล์ | ทรัพยากร |
|---|---|
| `data.tf` | อ้างอิง default VPC, `LabInstanceProfile`, Amazon Linux 2023, และ GNS3 AMI ล่าสุด (`netlab-gns3-base*`) |
| `security.tf` | `netlab-tf-alb-sg` (80, 443 เปิดทุกที่, 8000 สำหรับ backend), `netlab-tf-frontend-sg` (8080 จาก ALB เท่านั้น), `netlab-tf-backend-alb-sg` (8000 จาก frontend), `netlab-tf-backend-sg` (8000 จาก internal ALB) ทุกตัว SSH 22 เฉพาะ admin และ `netlab-tf-gns3-vm-sg` (3080, 5900-5999, 22 admin) สำหรับ VM นักศึกษา |
| `alb.tf` | ALB สาธารณะ (HTTPS :443 → frontend :8080, HTTP :80 redirect → 443, และ backend :8000) พร้อมรองรับ SSL/TLS (ACM certificate หรือ self-signed cert อัตโนมัติ), target group / health check (`/` และ `/health`) |
| `dynamodb.tf` | ตาราง `netlab_users`, `netlab_instances`, `netlab_exercises` พร้อม GSI (ตรงกับ `init_dynamodb.py`) |
| `s3.tf` | bucket private สำหรับเก็บ snapshot แบบฝึกหัด (`netlab-snapshots-<random>`) |
| `ec2.tf` | Launch Template + Auto Scaling Group ของ Frontend และ Backend (กระจาย AZ, health check แบบ ELB, rolling refresh), `random_password` สำหรับ JWT secret, และตัว cleanup VM ตอน destroy |
| `user_data_backend.sh.tpl`, `user_data_frontend.sh.tpl` | ติดตั้ง Docker, `git clone` repo ตาม `repo_branch`, `docker build` แล้ว `docker run` (backend เขียน `backend/.env` และสร้าง admin คนแรกจากเครื่องใน AZ แรกเท่านั้น) |

หมายเหตุ: Terraform สร้าง VPC `10.0.0.0/16` + IGW + public route table เอง (`vpc.tf`)
- เครื่อง Frontend/Backend/ALB อยู่ `public1` (10.0.0.0/24) และ `public2` (10.0.1.0/24) ใน 2 AZ แรก (ไม่รวม `lab_az`)
- VM นักศึกษาที่ API สร้างถูกบังคับให้อยู่ subnet `public-lab` (10.0.2.0/24) ใน `lab_az` (default `us-east-1c`) ผ่าน `DEFAULT_SUBNET_ID` ที่ Terraform ส่งให้ backend
- ทุก subnet เป็น public (auto-assign public IP) จึง **ไม่ต้องใช้ NAT Gateway** (ประหยัด credit) โดยล็อก Security Group ให้รับเฉพาะจาก ALB

## สิ่งที่ต้องมีก่อนเริ่ม

1. **Terraform >= 1.5**
   - Windows: `winget install Hashicorp.Terraform`
   - macOS: `brew install terraform`
2. **Learner Lab ที่ Start Lab แล้ว** (สถานะจุดเขียว)
3. **โค้ดล่าสุดถูก push ขึ้น GitHub** เพราะเครื่อง EC2 จะ `git clone` โค้ดจาก repo นี้ ถ้า repo เป็น private ต้องมี GitHub token (ดูหัวข้อ [Repo แบบ private](#repo-แบบ-private-github-token))
   - ต้อง apply การแก้ backend แล้ว (`config.py` ให้ `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` เป็น optional, มี `gns3_service.py` และ `s3_service.py`)
4. **GNS3 base AMI ในบัญชีนี้** สร้างด้วย `backend/scripts/build_gns3_ami.py` (ใช้เวลา ~10-20 นาที)
5. **IP ของคุณ** สำหรับ SSH (ดูได้ที่ https://checkip.amazonaws.com)

## ขั้นตอน

### 1) สร้าง GNS3 AMI (ทำครั้งเดียวต่อบัญชี Lab) <ถ้ามีแล้วข้ามไปได้เลย>

รันจากโฟลเดอร์ `backend` (ต้องตั้ง credentials ตามข้อ 2 ก่อน):

```bash
cd backend
python scripts/bootstrap_aws.py          # สร้าง SG/key pair สำหรับ builder
python scripts/build_gns3_ami.py         # พิมพ์ AMI ID ตอนจบ
```

ถ้ามี AMI ที่เพื่อนแชร์ให้แล้ว ให้ copy เข้าบัญชีตัวเองแทน: `python scripts/bootstrap_aws.py --copy-ami ami-xxxx`

### 2) ตั้งค่า AWS credentials 

credentials ของ Learner Lab (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`) เก็บอยู่ใน **`backend/.env`** อยู่แล้ว
(ใส่เองจาก AWS Details หรือรัน `python scripts/bootstrap_aws.py --write-credentials` ในโฟลเดอร์ `backend`)
แต่ Terraform **ไม่อ่านไฟล์ `.env` เอง** ต้องโหลดค่าเหล่านี้เข้า environment ของ terminal ก่อน รันจากโฟลเดอร์ `terraform`:

Windows PowerShell:
> ต้องอยู่ที่ \GNS3VM_Spawner
```powershell
Get-Content .\backend\.env |
  Where-Object { $_ -match '^(AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY|AWS_SESSION_TOKEN|AWS_REGION)=' } |
  ForEach-Object {
    $k, $v = $_ -split '=', 2
    Set-Item -Path "env:$($k.Trim())" -Value $v.Trim()
  }
```

macOS / Linux:

```bash
export $(grep -E '^(AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY|AWS_SESSION_TOKEN|AWS_REGION)=' ../backend/.env | tr -d '\r' | xargs)
```

ตรวจว่าใช้ได้: `aws sts get-caller-identity` (ต้องเห็น Account ID ของ Lab) ### ไม่มี aws cli ข้ามไปเลย

> credentials หมดอายุเมื่อ session จบ (~4 ชม.) ต้องอัปเดตค่าใน `backend/.env` ใหม่ทุกครั้งที่เปิด Lab
> แล้วรันคำสั่งโหลดด้านบนซ้ำ (ตัวแปรที่โหลดไว้อยู่แค่ใน terminal ที่เปิดอยู่ ปิดแล้วหาย)
>
> ห้าม commit `backend/.env` และห้ามคัดลอกไปวางบน EC2: เครื่อง EC2 ใช้ Instance Profile แทน
> (ดูหัวข้อ "backend/.env บนเครื่อง EC2")

### 3) ตั้งค่าตัวแปร

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars   # Windows: copy terraform.tfvars.example terraform.tfvars
```

แก้ `terraform.tfvars` ตาม example:

ถ้า repo เป็น **private** (repo นี้เป็น public จึงข้ามได้) ให้ตั้ง `TF_VAR_github_token` ก่อน apply (ดูหัวข้อ [Repo แบบ private](#repo-แบบ-private-github-token))

### 4) รัน Terraform

```bash
terraform init
terraform validate
terraform plan
terraform apply
```

ตอบ `yes` เมื่อถาม เมื่อเสร็จจะแสดง outputs:

| Output | ความหมาย |
|---|---|
| `web_url` | URL เปิดเว็บ (`http://<ชื่อ DNS ของ ALB>`) port 80 |
| `alb_dns_name` | ชื่อ DNS ของ ALB สาธารณะ |
| `backend_internal_url` | `BACKEND_URL` ที่ frontend ใช้ (internal ALB เข้าได้เฉพาะใน VPC) |
| `availability_zones_used` | AZ ที่ ALB / Frontend / Backend กระจายอยู่ |
| `frontend_asg_name`, `backend_asg_name` | ชื่อ Auto Scaling Group (ใช้กับคำสั่ง `aws autoscaling`) |
| `gns3_ami_used` | AMI ที่ backend ใช้สร้าง VM |
| `gns3_vm_sg_id` | Security Group ของ VM นักศึกษา |
| `snapshots_bucket` | ชื่อ S3 bucket |

### 5) รอให้เครื่อง build เสร็จ

หลัง apply เครื่องแต่ละตัวยังต้องติดตั้ง Docker, clone repo และ build image อีก **ประมาณ 3-5 นาที** ตลอดช่วงนี้ ALB จะแสดง 503 จนกว่าเครื่องจะผ่าน health check
ตรวจสถานะได้ที่ EC2 Console → Target Groups (`netlab-tf-frontend-tg`, `netlab-tf-backend-tg` ต้องเป็น healthy ครบ 2 ตัว) หรือ SSH เข้าเครื่องแล้วรัน `docker ps -a` และ `docker logs backend` / `docker logs frontend`
(`/var/log/cloud-init-output.log` สำหรับดู log ของ user_data)

### 6) เปิดใช้งาน

เปิด `web_url` ในเบราว์เซอร์ แล้ว login ด้วย admin ที่สร้างไว้ (ถ้า login ไม่ได้ในช่วงแรก รอให้ backend ทั้ง 2 ตัว healthy ก่อน)

## Repo แบบ private (GitHub token)

เครื่อง EC2 เริ่มต้นเปล่า ต้อง `git clone` โค้ดจาก GitHub เอง ถ้า repo เป็น private ต้องมี token ที่อ่าน repo ได้

### สร้าง token (ไม่จำเป็นต้องเป็นเจ้าของ repo)

| วิธี | เงื่อนไข |
|---|---|
| **Fine-grained token** (Repository access: เฉพาะ repo นี้, Contents: **Read-only**) | ปลอดภัยที่สุด แต่ repo ต้องเป็นของคุณหรือ organization ที่อนุญาต ถ้าเป็น repo ส่วนตัวของคนอื่นต้องให้เจ้าของ/admin สร้างให้ |
| **Classic token** (scope `repo`) | ใช้กับ repo ที่คุณเข้าถึงได้ แต่ token อ่าน/เขียนได้ **ทุก private repo ที่คุณเข้าถึง** ถ้า repo อยู่ใน organization ที่เปิด SSO ต้องกด Authorize token กับ organization นั้นด้วย |

ตั้งวันหมดอายุสั้น (เช่น 7 วัน) และ **revoke หลัง deploy เสร็จ**

### ใช้กับ Terraform

ตั้งผ่าน environment variable (ไม่ต้องเขียนลงไฟล์ `terraform.tfvars`):

```powershell
# Windows PowerShell
$env:TF_VAR_github_token="github_pat_xxxxxxxx"
```

```bash
# macOS / Linux
export TF_VAR_github_token="github_pat_xxxxxxxx"
```

แล้ว `terraform apply` ตามปกติ โดย `repo_url` ยังเป็น URL ธรรมดา (`https://github.com/<owner>/<repo>.git`) และต้องเป็น `https://` เท่านั้น
ถ้าใส่ token ลงใน `repo_url` ตรงๆ Terraform จะแจ้ง error ให้ใช้ `github_token` แทน

### Terraform ทำอะไรกับ token

- ตัวแปร `github_token` เป็น `sensitive` จึงไม่ถูกพิมพ์ใน `plan`/`apply`
- ฝัง token ลงใน URL เฉพาะคำสั่ง `git clone` ตอน boot และ **ปิด `set -x` ระหว่าง clone** เพื่อไม่ให้ token โผล่ใน `/var/log/cloud-init-output.log`
- หลัง clone เสร็จ **เปลี่ยน `origin` กลับเป็น URL ไม่มี token** (`/opt/app/.git/config` สะอาด)
- ลบสำเนา user-data บนดิสก์ของเครื่อง (`/var/lib/cloud/instances/*/user-data.txt*` และ `scripts/*`)

### สิ่งที่ยังเหลืออยู่ (ลดความเสี่ยงได้ ไม่ได้หายไปหมด)

- **`terraform.tfstate`** เก็บ token เป็นข้อความธรรมดา
- **user_data ใน instance metadata** ผู้ที่มีสิทธิ์ดู attribute ของเครื่องหรือเข้าเครื่องได้ จะอ่านได้
- ดังนั้นควรใช้ token สิทธิ์ read-only วันหมดอายุสั้น และ revoke เมื่อ deploy เสร็จ ห้ามแชร์ไฟล์ state

### อัปเดตโค้ด (repo private)

ในโครงสร้างที่มีหลายเครื่อง ไม่แนะนำให้ `git pull` ทีละเครื่อง ให้ใช้ instance refresh ตามหัวข้อ [อัปเดตโค้ด / ทดสอบ branch อื่น](#อัปเดตโค้ด--ทดสอบ-branch-อื่น)
โดยตั้ง `TF_VAR_github_token` ให้ใช้ได้ตอน `terraform apply` (เครื่องใหม่จะ clone ด้วย token ที่ฝังใน user_data)

## backend/.env บนเครื่อง EC2

`user_data` สร้างไฟล์ `/opt/app/backend/.env` ให้เองตอน boot ครั้งแรก
ไฟล์นี้ **ไม่ได้มาจาก Git** (`.env` ถูก ignore) ดังนั้นไม่ต้องคัดลอก `backend/.env.example` ไปวางบนเครื่อง
`.env.example` ใช้เป็นแม่แบบสำหรับรันบนเครื่องตัวเองเท่านั้น

| ตัวแปรใน `.env` | ค่ามาจาก |
|---|---|
| `AWS_REGION` | `region` |
| `DEFAULT_AMI_ID` | `base_ami_id` (ว่าง = AMI `netlab-gns3-base*` ล่าสุด) |
| `DEFAULT_INSTANCE_TYPE` | `lab_instance_type` |
| `DEFAULT_KEY_NAME` | `key_name` |
| `DEFAULT_SECURITY_GROUP_ID` | `netlab-tf-gns3-vm-sg` ที่ Terraform สร้าง |
| `INSTANCE_PROFILE_NAME` | `LabInstanceProfile` |
| `MAX_CONCURRENT_INSTANCES` | `max_concurrent_instances` |
| `USERS_TABLE_NAME`, `INSTANCES_TABLE_NAME`, `EXERCISES_TABLE_NAME` | ชื่อตาราง DynamoDB ที่ Terraform สร้าง |
| `SNAPSHOTS_BUCKET`, `SNAPSHOTS_PREFIX` | bucket ใน `s3.tf` และ `exercises` |
| `JWT_SECRET_KEY` | `random_password` ของ Terraform (ค่าเดียวกันทุกเครื่อง backend จึง login ข้ามเครื่องได้) เก็บอยู่ใน `terraform.tfstate` ห้ามแชร์ไฟล์ state |

ข้อสำคัญ:

- **ไม่ใส่** `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` เพราะ boto3 ใช้ `LabInstanceProfile` ของเครื่อง
  (ถ้าก๊อป `.env` จากเครื่องตัวเองที่มี key หมดอายุไปวาง backend จะใช้ key นั้นแล้วล้ม `ExpiredToken`)
- ตัวแปรที่ไม่ได้อยู่ในตาราง (`SNAPSHOT_URL_EXPIRES`, `GNS3_API_PORT`, `GNS3_PREFER_PRIVATE_IP`, `GNS3_EXPORT_TIMEOUT`) ใช้ค่าเริ่มต้นจาก `config.py`
- `.env` ของเครื่องตัวเอง (dev) กับบน EC2 เป็นคนละไฟล์ อย่าใช้ปนกัน: dev ใช้ `bootstrap_aws.py` สร้าง SG/key pair ชุดของตัวเอง
  ส่วนบน EC2 ใช้ชุดที่ Terraform สร้าง

แก้ค่าหลัง deploy แบบชั่วคราว (ต้องทำ **ทุกเครื่อง backend** ไม่งั้นแต่ละเครื่องจะใช้ค่าไม่ตรงกัน):

```bash
ssh -i <labsuser.pem> ec2-user@<public-ip-ของเครื่อง-backend>
nano /opt/app/backend/.env
docker rm -f backend
docker run -d --name backend --restart unless-stopped --env-file /opt/app/backend/.env -p 8000:8000 netlab-backend
```

> วิธีที่ถูกต้องคือแก้ผ่าน Terraform (`terraform.tfvars`) แล้ว `terraform apply` user_data เปลี่ยน -> ASG ทำ rolling refresh
> เปลี่ยนเครื่องให้ทีละตัว ข้อมูลใน DynamoDB/S3 ไม่หาย ทุกเครื่องได้ค่าตรงกัน

## ตัวแปรที่ปรับได้ (`variables.tf`)

| ตัวแปร | ค่าเริ่มต้น | หมายเหตุ |
|---|---|---|
| `admin_cidr` | (ต้องกรอก) | IP สำหรับ SSH เช่น `1.2.3.4/32` |
| `repo_url` | (ต้องกรอก) | HTTPS URL ของ repo (ห้ามฝัง token) |
| `github_token` | `""` | token อ่าน repo private (sensitive) ตั้งผ่าน `TF_VAR_github_token` |
| `repo_branch` | `main` | |
| `region` | `us-east-1` | Learner Lab ใช้ได้เฉพาะบาง region |
| `project` | `netlab` | prefix ของชื่อ resource |
| `base_ami_id` | `""` | ว่าง = ใช้ `netlab-gns3-base*` ล่าสุดในบัญชี |
| `key_name` | `vockey` | key pair ที่มีอยู่แล้ว ใช้ทั้งเครื่อง frontend/backend และ VM นักศึกษา (ถ้าใช้ `gns3-cloud-keypair` จาก `bootstrap_aws.py` ให้ตั้งค่านี้ และเก็บไฟล์ `.pem` ไว้ ห้าม commit) |
| `frontend_instance_type`, `backend_instance_type` | `t3.small` | ชนิดเครื่อง frontend / backend (ต่อ 1 เครื่อง) |
| `frontend_count`, `backend_count` | `2` | จำนวนเครื่องในแต่ละ ASG (ขนาดคงที่ กระจายตาม AZ) ตั้งน้อยกว่า 2 จะไม่ทน AZ ล่ม |
| `az_count` | `2` | จำนวน AZ ที่ใช้ (2-4) เลือก AZ แรกๆ ตามตัวอักษรของ default VPC |
| `health_check_grace_period` | `600` | วินาทีที่ ASG รอก่อนเริ่มนับ health check ของเครื่องใหม่ ต้องนานกว่าเวลา build |
| `alb_idle_timeout` | `600` | idle timeout ของ ALB (ค่าเริ่มต้นของ AWS คือ 60 ซึ่งสั้นกว่าตอน start VM ~150 วินาที) |
| `lab_instance_type` | `t3.medium` | ชนิด VM นักศึกษา (`DEFAULT_INSTANCE_TYPE`) `.env.example` ตั้งเป็น `t2.micro` เพื่อประหยัด credit แต่ RAM 1 GB มักไม่พอรัน GNS3 หลาย node |
| `max_concurrent_instances` | `3` | จำกัดจำนวน VM พร้อมกัน (กัน credit หมด) |
| `expose_backend_port` | `false` | เปิด 8000 บน ALB สาธารณะเฉพาะ `admin_cidr` ให้ `terraform destroy` เรียก API ลบ VM/AMI (ถ้าปิดจะใช้ aws CLI fallback) เบราว์เซอร์ไม่ต้องเข้า backend เพราะ frontend เรียกจากฝั่ง server |
| `certificate_arn` | `""` | ARN ของ SSL/TLS Certificate ใน ACM (ถ้าเว้นว่างไว้ ระบบจะสร้าง self-signed cert และ import เข้า ACM ให้อัตโนมัติ) |
| `ssl_policy` | `ELBSecurityPolicy-TLS13-1-2-2021-06` | SSL Policy สำหรับ HTTPS Listener บน ALB |
| `redirect_http_to_https` | `true` | เปลี่ยนเส้นทาง HTTP (พอร์ต 80) ไปยัง HTTPS (พอร์ต 443) อัตโนมัติ |
| `users_table`, `instances_table`, `exercises_table` | `netlab_*` | ชื่อตาราง DynamoDB |

## การใช้งานหลัง deploy

### อัปเดตโค้ด / ทดสอบ branch อื่น

user_data รันแค่ตอนเครื่อง boot ครั้งแรก มี 2 วิธีทำให้ทุกเครื่องได้โค้ดใหม่:

1. **เปลี่ยน `repo_branch` แล้ว `terraform apply`** (เช่นทดสอบ branch `feature-x` ก่อนกลับมา `main`)
   user_data เปลี่ยน -> Launch Template version ใหม่ -> ASG ทำ **Rolling instance refresh** ทยอยเปลี่ยนเครื่องทีละตัว เว็บไม่หยุด (ใช้เวลาหลายนาทีต่อเครื่อง)
   ```powershell
   terraform apply -var "repo_branch=feature-x"   # ทดสอบ
   terraform apply -var "repo_branch=main"         # กลับมา main
   ```
2. **push โค้ดใหม่ใน branch เดิม** Terraform มองไม่เห็นว่าเปลี่ยน ให้สั่ง refresh เอง:
   ```bash
   aws autoscaling start-instance-refresh --auto-scaling-group-name netlab-tf-backend-asg \
     --preferences '{"MinHealthyPercentage":50,"InstanceWarmup":300}'
   aws autoscaling start-instance-refresh --auto-scaling-group-name netlab-tf-frontend-asg \
     --preferences '{"MinHealthyPercentage":50,"InstanceWarmup":300}'
   ```
   (ชื่อ ASG ดูได้จาก output `backend_asg_name` / `frontend_asg_name`)

ดู log (SSH เข้าเครื่องหนึ่งตัว ดู IP ได้ใน EC2 Console):

```bash
ssh -i <labsuser.pem> ec2-user@<public-ip-ของเครื่อง>
docker logs -f backend      # เครื่อง backend
docker logs -f frontend     # เครื่อง frontend
```

เมื่อ Learner Lab หยุด EC2 จะถูก stop และเมื่อ Start Lab ใหม่ container จะกลับมาเอง (`--restart unless-stopped`)
ทางเข้าเว็บคือ DNS ของ ALB ซึ่งคงเดิมตราบที่ ALB ไม่ถูกลบ

## ทดสอบว่า HA ทำงานจริง

1. เปิด `web_url` แล้ว login ให้เรียบร้อย
2. EC2 Console → Instances เลือกเครื่อง `netlab-frontend` ตัวหนึ่ง (หรือ `netlab-backend`) → **Terminate**
3. รีเฟรชหน้าเว็บต่อเนื่อง: ต้องยังใช้งานได้ (ALB ส่งไปเครื่องอีก AZ) และอยู่ในระบบอยู่ไม่หลุด (JWT ใช้ secret เดียวกัน)
4. ใน Target Groups จะเห็นเครื่องเก่า unhealthy/หายไป แล้ว ASG สร้างเครื่องใหม่ทดแทนภายในไม่กี่นาที
5. ทดสอบระดับ AZ: Terminate ทั้ง 2 เครื่องของฝั่งเดียวกันที่อยู่ AZ เดียวกัน เว็บต้องยังตอบจากอีก AZ

ข้อจำกัดที่ควรเขียนในรายงาน:
- GNS3 VM ที่ API สร้างไม่ได้สำรอง ถ้า AZ ล่ม VM ใน AZ นั้นหาย (ตั้งใจให้เป็นแบบนี้)
- มีการเข้ารหัส SSL/TLS บนพอร์ต 443 ผ่าน ALB (หากไม่มี custom domain บน ACM สามารถปล่อยว่าง `certificate_arn` เพื่อให้ Terraform สร้าง self-signed certificate และ import เข้า ACM ให้อัตโนมัติ โดยเบราว์เซอร์จะแสดงคำเตือน Self-signed certificate)
- ALB 2 ตัว (สาธารณะ + ภายใน) คิดค่าบริการรายชั่วโมงตลอดเวลาที่เปิดอยู่ ควร `terraform destroy` เมื่อไม่ใช้

## ลบทั้งหมด (`terraform destroy`)

1. **Terminate VM นักศึกษาและอาจารย์ทั้งหมดก่อน** (ผ่านหน้าเว็บหรือ EC2 Console)
   VM เหล่านี้ backend สร้างผ่าน boto3 ไม่อยู่ใน Terraform state ถ้ายังเหลืออยู่ Security Group จะลบไม่ได้ (`DependencyViolation`)
   (ตอน destroy Terraform พยายามลบให้เอง: ถ้าตั้ง `expose_backend_port = true` จะเรียก API ผ่าน ALB สาธารณะ port 8000 ถ้าไม่ตั้งจะใช้ aws CLI ลบตาม Security Group ซึ่งต้องมี `aws` ใน PATH)
2. รัน:

```bash
terraform destroy
```

bucket S3 ตั้ง `force_destroy = true` จึงลบพร้อมไฟล์ snapshot ทั้งหมดด้วย
ส่วน GNS3 AMI ที่สร้างด้วยสคริปต์ **ไม่ถูกลบ** ต้อง deregister เองหากไม่ต้องการ

## แก้ปัญหาเบื้องต้น

| อาการ | สาเหตุ / วิธีแก้ |
|---|---|
| `ExpiredToken` / `InvalidClientTokenId` | credentials หมดอายุ ตั้งค่าใหม่จาก AWS Details (ข้อ 2) |
| `ไม่พบ GNS3 AMI` (precondition) | ยังไม่มี AMI ชื่อ `netlab-gns3-base*` รัน `build_gns3_ami.py` หรือตั้ง `base_ami_id` |
| `InvalidKeyPair.NotFound` | `key_name` ไม่มีในบัญชี ใช้ `vockey` หรือสร้าง key pair ก่อน |
| `UnauthorizedOperation` ตอน apply | Learner Lab จำกัดสิทธิ์บางอย่าง (เช่น IAM) Terraform ชุดนี้ใช้แค่ role ที่มีอยู่แล้ว ตรวจว่าไม่ได้แก้ไฟล์ให้สร้าง IAM |
| `terraform apply` ผ่าน แต่ `/opt/app` ไม่มีโค้ด / log ขึ้น `Repository not found` หรือ `Authentication failed` | repo เป็น private แต่ไม่ได้ตั้ง `TF_VAR_github_token`, token หมดอายุ, ไม่มีสิทธิ์ที่ repo นี้ หรือ organization ต้อง Authorize token (SSO) แก้แล้ว `terraform apply` ใหม่ (user_data เปลี่ยน เครื่องจะถูกสร้างใหม่) |
| เปิด `web_url` แล้วขึ้น 503 | ยังไม่มีเครื่อง healthy ใน target group (build ยังไม่เสร็จ ~3-5 นาที) ดู Target Groups และ `/var/log/cloud-init-output.log` หรือ Lab ถูก stop อยู่ |
| เครื่องถูก ASG ฆ่าแล้วสร้างใหม่วนซ้ำ | health check ไม่ผ่าน: ดู log `docker logs backend`; ตรวจว่า branch มี `/health` และ image build ผ่าน หรือเพิ่ม `health_check_grace_period` |
| login แล้วหลุดสลับไปมา | JWT secret ไม่เหมือนกันทุกเครื่อง ตรวจว่า `JWT_SECRET_KEY` ใน `/opt/app/backend/.env` ของ backend ทุกตัวตรงกัน (ชุดนี้ใช้ค่าเดียวจาก Terraform) |
| กด start VM แล้วหน้าเว็บ error 504 | ALB idle timeout สั้นกว่าเวลา start VM ตรวจว่า `alb_idle_timeout` >= 300 |
| `docker build` ล้มตอน boot | ดู `/var/log/cloud-init-output.log`; ตรวจว่า repo clone ได้และมี `backend/Dockerfile`, `frontend/Dockerfile` |
| backend เริ่มไม่ขึ้น (validation error) | ตรวจว่าแก้ `config.py` ให้ AWS key เป็น optional แล้ว และ `/opt/app/backend/.env` มีค่าครบ (`docker logs backend`) |
| `Invalid IAM Instance Profile name` ตอน launch VM | `INSTANCE_PROFILE_NAME` ต้องเป็นชื่อ Instance Profile (`LabInstanceProfile`) ไม่ใช่ชื่อ Role (`LabRole`) |
| backend ขึ้น `ExpiredToken` บน EC2 | มี `AWS_ACCESS_KEY_ID`/`SECRET`/`SESSION_TOKEN` ค้างใน `/opt/app/backend/.env` ลบทิ้งแล้ว `docker rm -f backend` และ `docker run` ใหม่ (หรือสั่ง instance refresh) |
| ตารางมีอยู่แล้ว (`ResourceInUseException`) | เคยรัน `init_dynamodb.py` ไว้ ลบตารางเดิมก่อน หรือเปลี่ยนชื่อผ่าน `users_table` ฯลฯ |
| `SecurityGroup ... already exists` | ชื่อซ้ำกับของเดิมใน default VPC ลบอันเก่าหรือเปลี่ยน `project` |

## ย้ายจากโครงสร้างเดิม (EC2 เครื่องเดียว + Elastic IP)

ถ้าเคย `terraform apply` ด้วยเวอร์ชันเดิมไว้ ควร **`terraform destroy` ด้วยโค้ดเวอร์ชันเดิมก่อน** แล้วค่อย apply ชุดนี้ เพราะ Security Group และ resource cleanup เปลี่ยนชื่อ/โครงสร้างทั้งหมด
(ตาราง DynamoDB ที่มีอยู่แล้วจะถูก import กลับมาเอง ผ่าน `ddb_exists.py` ข้อมูลผู้ใช้ไม่หาย ถ้าไม่ได้ลบตาราง)

## ข้อควรระวัง

- **ห้าม commit** `terraform.tfvars`, `*.tfstate`, `.terraform/` ให้เพิ่มใน `.gitignore`:

  ```
  terraform/.terraform/
  terraform/*.tfstate*
  terraform/terraform.tfvars
  backend/.env
  *.pem
  ```

- **State เก็บในเครื่อง (local)** หาย = Terraform จำ resource ไม่ได้ ควรสำรองไฟล์ `terraform.tfstate`
- **ค่าใช้จ่าย** หักจาก credit ของ Lab: เครื่อง frontend + backend อย่างละ 2 เครื่อง, ALB 2 ตัว (คิดรายชั่วโมงตลอดที่เปิด) และ VM นักศึกษา ปรับ `frontend_count`/`backend_count`, `max_concurrent_instances` และ `lab_instance_type` ให้เหมาะกับงบ และ `terraform destroy` เมื่อไม่ใช้
- `JWT_SECRET_KEY` มาจาก `random_password` ใน Terraform (ค่าเดียวกันทุกเครื่อง backend) จึงอยู่ใน `terraform.tfstate` เหมือน `admin_password`
- ค่า `INSTANCE_PROFILE_NAME` ใช้ `LabInstanceProfile` ซึ่งต้องมีสิทธิ์ `iam:PassRole` เพื่อแนบให้ VM นักศึกษา (ปกติ Learner Lab อนุญาต)

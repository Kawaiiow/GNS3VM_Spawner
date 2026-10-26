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
python scripts/build_gns3_ami.py         # พิมพ์ AMI ID ตอนจบ
```
และนำค่า AMI ID ที่ได้ไปใส่ใน .env
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

### 3) ตั้งค่าตัวแปร

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars   # Windows: copy terraform.tfvars.example terraform.tfvars
```

แก้ `terraform.tfvars` ตาม example:
โดยใส่
```bash
> admin_cidr = "เลขอะไรก็ได้"
> repo_url = "https://github.com/Kawaiiow/GNS3VM_Spawner.git"
> repo_branch  = "main"
> expose_backend_port = true/false # เปิดหรือปิดให้คนเข้า backend
> admin_password      = "xxxxx"  #รหัสสำหรับ username admin
> redirect_http_to_https = true # redirect HTTP (80) -> HTTPS (443) อัตโนมัติ
> max_concurrent_instances = "มากสุดตามต้องการ" #แต่ Leaner Lab Max ที่ 9
```

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


เมื่อ Learner Lab หยุด EC2 จะถูก stop และเมื่อ Start Lab ใหม่ container จะกลับมาเอง (`--restart unless-stopped`)
ทางเข้าเว็บคือ DNS ของ ALB ซึ่งคงเดิมตราบที่ ALB ไม่ถูกลบ

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


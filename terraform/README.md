# Terraform: Deploy NetLab บน AWS Learner Lab

Terraform ชุดนี้สร้างโครงสร้างสำหรับรันเว็บ NetLab (frontend + backend) บน **EC2 เครื่องเดียวด้วย Docker Compose**
และเตรียมทรัพยากรที่ backend ต้องใช้ (DynamoDB, S3, Security Group)

```
นักศึกษา / อาจารย์ ──► EC2 web (Elastic IP)
                         ├─ frontend :8080
                         └─ backend  :8000 (ใน Docker network)
                                │  boto3 (LabInstanceProfile)
                ┌───────────────┼────────────────┐
                ▼               ▼                ▼
           EC2 API         DynamoDB            S3 (private)
     (สร้าง VM นักศึกษา)   users/instances/    เก็บ .gns3project
                           exercises
```

## สิ่งที่ Terraform สร้าง

| ไฟล์ | ทรัพยากร |
|---|---|
| `data.tf` | อ้างอิง default VPC, `LabInstanceProfile`, Amazon Linux 2023, และ GNS3 AMI ล่าสุด (`netlab-gns3-base*`) |
| `security.tf` | `netlab-tf-web-sg` (8080 เปิดทุกที่, 22 เฉพาะ admin) และ `netlab-tf-gns3-vm-sg` (3080, 5900-5999, 22 admin) สำหรับ VM นักศึกษา |
| `dynamodb.tf` | ตาราง `netlab_users`, `netlab_instances`, `netlab_exercises` พร้อม GSI (ตรงกับ `init_dynamodb.py`) |
| `s3.tf` | bucket private สำหรับเก็บ snapshot แบบฝึกหัด (`netlab-snapshots-<random>`) |
| `ec2.tf` | EC2 web (`t3.small`) + Elastic IP; `user_data` ติดตั้ง Docker, clone repo, เขียน `backend/.env`, รัน `docker compose up` |

หมายเหตุ: ทุกอย่างอยู่ใน **default VPC** เพราะ backend เรียก `run_instances` โดยไม่ระบุ subnet
VM นักศึกษาจะไปอยู่ใน default VPC เสมอ จึงต้องใช้ Security Group ใน VPC เดียวกัน

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

แก้ `terraform.tfvars` อย่างน้อย 2 ค่า:

```hcl
admin_cidr = "1.2.3.4/32"                                  # ไม่ต้องใส่ SSH ในเว็บได้
repo_url   = "https://github.com/<owner>/GNS3VM_Spawner.git"   # ห้ามใส่ token ในบรรทัดนี้
repo_branch = "branch"
# expose_backend_port = true   # เปิด 8000 ถ้า JS ในหน้าเว็บเรียก backend ตรงๆ จากเบราว์เซอร์
PowerShell: $env:TF_VAR_github_token="..."   |   bash: export TF_VAR_github_token=...
```

ถ้า repo เป็น **private** ให้ตั้ง `TF_VAR_github_token` ก่อน apply (ดูหัวข้อ [Repo แบบ private](#repo-แบบ-private-github-token))

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
| `web_url` | URL เปิดเว็บ (`http://<Elastic IP>:8080`) |
| `web_public_ip` | IP ของเครื่อง web (ใช้ SSH) |
| `gns3_ami_used` | AMI ที่ backend ใช้สร้าง VM |
| `gns3_vm_sg_id` | Security Group ของ VM นักศึกษา |
| `snapshots_bucket` | ชื่อ S3 bucket |

### 5) รอให้เครื่อง build เสร็จ

หลัง apply เครื่องยังต้องติดตั้ง Docker และ build image อีก **ประมาณ 3-5 นาที** ตรวจสถานะ:

```bash
ssh -i <labsuser.pem> ec2-user@<web_public_ip>
sudo tail -f /var/log/cloud-init-output.log     # ดูจนเห็นว่า docker compose up จบ
cd /opt/app && docker compose ps                 # backend ต้อง healthy
```
> เข้าผ่านเว็บไปเช็คได้

> `key_name` เริ่มต้นเป็น `vockey` ให้ดาวน์โหลดไฟล์ `.pem` จากหน้า AWS Details

### 6) สร้างบัญชี admin คนแรก

บนเครื่อง EC2:
# SSH เข้าไปใน Webstie Console

```bash
cd /opt/app
docker compose run --rm -v $(pwd)/backend/scripts:/app/scripts backend \
  python scripts/create_user.py -u admin -m ADMIN01 -p '<รหัสผ่านที่ต้องการ>' -r admin
```

ไม่ต้องรัน `init_dynamodb.py` เพราะ Terraform สร้างตารางให้แล้ว (รันซ้ำจะชื่อชนกัน)

### 7) เปิดใช้งาน

เปิด `web_url` ในเบราว์เซอร์ แล้ว login ด้วย admin ที่สร้างไว้

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

### อัปเดตโค้ดบนเครื่อง (repo private)

เพราะ remote ไม่มี token แล้ว ให้ส่ง token ตอน pull ครั้งนั้นๆ (ไม่บันทึกลงเครื่อง):

```bash
cd /opt/app
git pull "https://x-access-token:<token>@github.com/<owner>/<repo>.git" <branch>
docker compose up -d --build
```

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
| `JWT_SECRET_KEY` | สุ่มบนเครื่อง ไม่อยู่ใน Terraform state |

ข้อสำคัญ:

- **ไม่ใส่** `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` เพราะ boto3 ใช้ `LabInstanceProfile` ของเครื่อง
  (ถ้าก๊อป `.env` จากเครื่องตัวเองที่มี key หมดอายุไปวาง backend จะใช้ key นั้นแล้วล้ม `ExpiredToken`)
- ตัวแปรที่ไม่ได้อยู่ในตาราง (`SNAPSHOT_URL_EXPIRES`, `GNS3_API_PORT`, `GNS3_PREFER_PRIVATE_IP`, `GNS3_EXPORT_TIMEOUT`) ใช้ค่าเริ่มต้นจาก `config.py`
- `.env` ของเครื่องตัวเอง (dev) กับบน EC2 เป็นคนละไฟล์ อย่าใช้ปนกัน: dev ใช้ `bootstrap_aws.py` สร้าง SG/key pair ชุดของตัวเอง
  ส่วนบน EC2 ใช้ชุดที่ Terraform สร้าง

แก้ค่าหลัง deploy (เช่นเปลี่ยนชนิด VM โดยไม่ apply ใหม่):

```bash
ssh -i <labsuser.pem> ec2-user@<web_public_ip>
nano /opt/app/backend/.env
cd /opt/app && docker compose up -d --force-recreate backend
```

> ถ้าแก้ผ่าน Terraform (`terraform.tfvars`) แล้ว apply ใหม่ เครื่อง web จะถูกสร้างใหม่ (`user_data_replace_on_change`)
> ข้อมูลใน DynamoDB/S3 ยังอยู่ แต่ Elastic IP จะถูกผูกกับเครื่องใหม่

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
| `key_name` | `vockey` | key pair ที่มีอยู่แล้ว ใช้ทั้งเครื่อง web และ VM นักศึกษา (ถ้าใช้ `gns3-cloud-keypair` จาก `bootstrap_aws.py` ให้ตั้งค่านี้ และเก็บไฟล์ `.pem` ไว้ ห้าม commit) |
| `web_instance_type` | `t3.small` | ชนิดเครื่อง web |
| `lab_instance_type` | `t3.medium` | ชนิด VM นักศึกษา (`DEFAULT_INSTANCE_TYPE`) `.env.example` ตั้งเป็น `t2.micro` เพื่อประหยัด credit แต่ RAM 1 GB มักไม่พอรัน GNS3 หลาย node |
| `max_concurrent_instances` | `3` | จำกัดจำนวน VM พร้อมกัน (กัน credit หมด) |
| `expose_backend_port` | `false` | เปิด 8000 ให้เบราว์เซอร์ถ้า JavaScript เรียก backend ตรงๆ |
| `users_table`, `instances_table`, `exercises_table` | `netlab_*` | ชื่อตาราง DynamoDB |

## การใช้งานหลัง deploy

อัปเดตโค้ด (user_data รันแค่ครั้งแรกตอน boot):

```bash
ssh -i <labsuser.pem> ec2-user@<web_public_ip>
cd /opt/app && git pull && docker compose up -d --build   # repo public
```

repo private ดูวิธีส่ง token ตอน pull ในหัวข้อ [Repo แบบ private](#repo-แบบ-private-github-token)

ดู log:

```bash
docker compose logs -f backend
docker compose logs -f frontend
```

เมื่อ Learner Lab หยุด EC2 จะถูก stop และเมื่อ Start Lab ใหม่ container จะกลับมาเอง (`restart: unless-stopped`)
Elastic IP ยังเป็นตัวเดิมตราบที่ resource ไม่ถูกลบ

## ลบทั้งหมด (`terraform destroy`)

1. **Terminate VM นักศึกษาและอาจารย์ทั้งหมดก่อน** (ผ่านหน้าเว็บหรือ EC2 Console)
   VM เหล่านี้ backend สร้างผ่าน boto3 ไม่อยู่ใน Terraform state ถ้ายังเหลืออยู่ Security Group จะลบไม่ได้ (`DependencyViolation`)
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
| เปิด `web_url` ไม่ได้ | เครื่องยัง build ไม่เสร็จ (ดู `cloud-init-output.log`) หรือ Lab ถูก stop อยู่ |
| `docker compose` ล้มตอน build | ดู `/var/log/cloud-init-output.log`; ตรวจว่า repo clone ได้และมี `backend/Dockerfile`, `frontend/Dockerfile` |
| backend เริ่มไม่ขึ้น (validation error) | ตรวจว่าแก้ `config.py` ให้ AWS key เป็น optional แล้ว และ `/opt/app/backend/.env` มีค่าครบ |
| `Invalid IAM Instance Profile name` ตอน launch VM | `INSTANCE_PROFILE_NAME` ต้องเป็นชื่อ Instance Profile (`LabInstanceProfile`) ไม่ใช่ชื่อ Role (`LabRole`) |
| backend ขึ้น `ExpiredToken` บน EC2 | มี `AWS_ACCESS_KEY_ID`/`SECRET`/`SESSION_TOKEN` ค้างใน `/opt/app/backend/.env` ลบทิ้งแล้ว `docker compose up -d --force-recreate backend` |
| ตารางมีอยู่แล้ว (`ResourceInUseException`) | เคยรัน `init_dynamodb.py` ไว้ ลบตารางเดิมก่อน หรือเปลี่ยนชื่อผ่าน `users_table` ฯลฯ |
| `SecurityGroup ... already exists` | ชื่อซ้ำกับของเดิมใน default VPC ลบอันเก่าหรือเปลี่ยน `project` |

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
- **ค่าใช้จ่าย** หักจาก credit ของ Lab: เครื่อง web + VM นักศึกษา (ตามจำนวนและชนิดเครื่อง) ปรับ `max_concurrent_instances` และ `lab_instance_type` ให้เหมาะกับงบ
- `JWT_SECRET_KEY` ถูกสุ่มบนเครื่อง EC2 ตอน boot ครั้งแรก ไม่อยู่ใน Terraform state
- ค่า `INSTANCE_PROFILE_NAME` ใช้ `LabInstanceProfile` ซึ่งต้องมีสิทธิ์ `iam:PassRole` เพื่อแนบให้ VM นักศึกษา (ปกติ Learner Lab อนุญาต)

# GNS3 Cloud - NetLab Backend API

FastAPI backend สำหรับระบบ **NetLab** ให้นักศึกษาแขนง Infrastructure ขอสร้างและควบคุม GNS3 VM บน AWS EC2 ผ่านเว็บไซต์ พร้อมระบบจัดการผู้ใช้, อินสแตนซ์ และแบบฝึกหัด Lab ด้วย **Amazon DynamoDB (Reduced Schema)**, ระบบความปลอดภัย **JWT Authentication**, สิทธิ์ตามบทบาท (`student` / `instructor` / `admin`) และโควตา VM แบบ Atomic

---

## 📑 สารบัญ

- [ฟีเจอร์หลัก](#-ฟีเจอร์หลักของระบบ)
- [โครงสร้างฐานข้อมูล](#️-โครงสร้างฐานข้อมูล-dynamodb-reduced-schema)
- [คำแนะนำสำหรับ AWS Academy Learner Lab](#️-คำแนะนำสำหรับ-aws-academy-learner-lab)
- [ส่วนที่ 0: Quick Start ด้วย Bootstrap Scripts (แนะนำ)](#ส่วนที่-0-quick-start-ด้วย-bootstrap-scripts-แนะนำ)
- [ส่วนที่ 1: ติดตั้งและรัน Local Backend (ตั้งค่าเอง)](#ส่วนที่-1-การติดตั้งและรัน-local-backend-ตั้งค่าเอง)
- [การทดสอบระบบ](#-การทดสอบระบบ-automated-tests)
- [ส่วนที่ 2: ตัวอย่างการเรียกใช้ API](#ส่วนที่-2-สรุปและตัวอย่างการเรียกใช้-api)
- [ส่วนที่ 3: Deploy ไปยัง Amazon ECR และ AWS ECS (Fargate)](#ส่วนที่-3-การ-deploy-ไปยัง-amazon-ecr-และ-aws-ecs-fargate)
- [มาตรการความปลอดภัย](#-มาตรการความปลอดภัยและคำแนะนำ)

---

## 🚀 ฟีเจอร์หลักของระบบ

1. **Authentication & User Management (DynamoDB)**
   - ลงชื่อเข้าใช้ด้วย Username หรือ Member ID พร้อมรหัสผ่านที่เข้ารหัสด้วย `bcrypt`
   - ออก **JWT (HS256)** รองรับทั้ง `Authorization: Bearer <token>` และ `HttpOnly Cookie` (ออกจากระบบด้วย `POST /auth/logout`)
   - แบ่งสิทธิ์: `student`, `instructor`, `admin`
   - Admin จัดการผู้ใช้ผ่าน API ได้ครบ (สร้าง / ดูรายชื่อ / แก้ไข / ลบ) และมี Dashboard ภาพรวม
   - มีสคริปต์ CLI สำหรับสร้างบัญชี (`scripts/create_user.py`)
2. **EC2 & VM Lifecycle with DynamoDB Persistence**
   - **โควตา VM ตามบทบาท** (ป้องกัน Race Condition ด้วย DynamoDB Conditional Write):
     | บทบาท | สิทธิ์สร้าง VM |
     |---|---|
     | `student` | **Sandbox 1 เครื่อง + Exercise 1 เครื่อง** (ล็อกแยกกัน) |
     | `instructor` | ไม่จำกัดจำนวน |
     | `admin` | สร้าง VM ไม่ได้ (ดู Dashboard / จัดการผู้ใช้เท่านั้น) |
   - จำกัดจำนวน VM ของทั้งโปรเจกต์ด้วย `MAX_CONCURRENT_INSTANCES`
   - **รหัสผ่าน GNS3 แยกต่อ VM**: ตอน launch ระบบสุ่มรหัสผ่านใหม่ใส่ผ่าน EC2 UserData แล้วเก็บใน DynamoDB ส่งให้เจ้าของ VM เท่านั้น (Admin ไม่เห็น)
   - Real-time sync สถานะและ Public IP จาก EC2 เข้า DynamoDB (Start แล้วรอ `running` เพื่อได้ IP ใหม่, Stop แล้วเคลียร์ IP)
   - Ownership Protection: Start / Stop / Terminate ได้เฉพาะ VM ของตัวเอง (Admin ทำได้ทุกเครื่อง)
   - คืนโควตาทันทีเมื่อ Terminate
3. **Lab Exercises Management**
   - Instructor สร้างแบบฝึกหัดได้ 2 แบบ: **Snapshot จาก VM ของตัวเอง** (ระบบสั่งสร้าง AMI ให้, สถานะ `pending` → `available`) หรือระบุ `ami_id` ที่มีอยู่แล้ว
   - นักศึกษาเลือก `exercise_id` ตอนขอสร้าง VM เพื่อเริ่มจากโจทย์/Topology นั้นทันที (VM จะถูกสร้างได้เมื่อ Snapshot เป็น `available`)
   - ลบแบบฝึกหัดแล้วระบบ De-register AMI ของแบบฝึกหัดนั้นให้ ⚠️ จึง **อย่าสร้างแบบฝึกหัดโดยใส่ `ami_id` ของ GNS3 Base AMI** ไม่งั้นการลบแบบฝึกหัดจะลบ Base AMI ไปด้วย (ให้ใช้วิธี Snapshot จาก VM แทน)
4. **Automated Provisioning & Verification**
   - `scripts/bootstrap_aws.py` ตั้งค่า AWS + `.env` ให้ครบในคำสั่งเดียว
   - `scripts/build_gns3_ami.py` สร้าง GNS3 Base AMI จากศูนย์แบบอัตโนมัติ
   - `scripts/share_ami.py` แชร์ AMI ให้เพื่อนร่วมทีม
   - `scripts/init_dynamodb.py` สร้างตาราง DynamoDB (On-Demand)
   - `scripts/test_flow.py` ชุดทดสอบ 26 เคส (ไม่ต้องใช้ AWS จริง)
   - เอกสาร API ทุก Route ใน [`api_doc.md`](api_doc.md)

---

## 🗄️ โครงสร้างฐานข้อมูล DynamoDB (Reduced Schema)

ใช้ 3 ตารางแบบ On-Demand (`PAY_PER_REQUEST`):

```mermaid
erDiagram
    USERS {
        string user_id PK "UUID"
        string username UK "GSI: UsernameIndex"
        string member_id UK "GSI: MemberIdIndex"
        string password_hash "Bcrypt hash"
        string full_name
        string role "student | instructor | admin"
        string active_instance_id "Nullable - ล็อก Sandbox VM"
        string active_exercise_instance_id "Nullable - ล็อก Exercise VM"
        string created_at "ISO-8601"
        string updated_at "ISO-8601"
    }

    VM_INSTANCES {
        string instance_id PK "EC2 Instance ID (i-xxx)"
        string user_id FK "GSI: UserIdIndex"
        string exercise_id FK "Nullable - references EXERCISES"
        string name "Instance friendly name"
        string instance_type
        string ami_id
        string state "pending | running | stopped | terminated"
        string public_ip "Nullable"
        string private_ip "Nullable"
        string gns3_user "รหัสเข้า GNS3 ของ VM นี้"
        string gns3_password "สุ่มใหม่ทุก VM"
        string launch_time "ISO-8601"
        string terminated_at "Nullable"
    }

    EXERCISES {
        string exercise_id PK "UUID"
        string instructor_id FK "GSI: InstructorIdIndex"
        string ami_id "AMI ของ Snapshot"
        string title
        string description
        string status "pending | available | failed"
        boolean is_active
        string created_at "ISO-8601"
    }

    USERS ||--o{ VM_INSTANCES : "owns (student: max 1 sandbox + 1 exercise)"
    USERS ||--o{ EXERCISES : "creates (instructor)"
    EXERCISES ||--o{ VM_INSTANCES : "spawns"
```

---

## ⚠️ คำแนะนำสำหรับ AWS Academy Learner Lab

โปรเจกต์นี้รองรับทั้ง **AWS Academy Learner Lab** และ **AWS Account จริงทั่วไป**:

- **AWS Learner Lab**
  - ล็อก Region `us-east-1` (N. Virginia)
  - Credentials มีอายุ ~3-4 ชั่วโมง (มี `aws_session_token`)
  - **สร้าง IAM Role / IAM User เองไม่ได้** ต้องใช้ `LabRole` / `LabInstanceProfile` ที่ Lab เตรียมไว้
  - มี **default VPC + Internet Gateway + public subnet** ให้อยู่แล้ว ไม่ต้องสร้างเอง
  - ต้องคัดลอกค่าจาก **AWS Details** ทุกครั้งที่เปิด Session ใหม่ (ถ้าใช้ `bootstrap_aws.py --write-credentials` สคริปต์จะเขียนลง `.env` ให้)
  - Budget จำกัด **ควร Stop / Terminate VM ทุกครั้งที่เลิกใช้งาน**
- **AWS Account จริง**
  - ลบบรรทัด `AWS_SESSION_TOKEN` ใน `.env` ได้
  - เลือก Region ได้อิสระ เช่น `ap-southeast-1` และสร้าง IAM Role เองตาม least-privilege

ในโค้ดจุดที่ต่างกันระหว่าง Lab กับ Account จริงจะมีคอมเมนต์ `>>> LEARNER LAB ONLY <<<` กำกับใน `app/config.py`

---

## ส่วนที่ 0: Quick Start ด้วย Bootstrap Scripts (แนะนำ)

ถ้าไม่อยากสร้าง Security Group, Key Pair, GNS3 AMI และไฟล์ `.env` ด้วยมือ ให้ใช้ 3 สคริปต์ในโฟลเดอร์ `scripts/` (เขียนด้วย `boto3` รันซ้ำได้ปลอดภัย):

| สคริปต์ | หน้าที่ | ใครรัน |
|---|---|---|
| `bootstrap_aws.py` | หา default VPC, สร้าง Security Group + Key Pair, หา Instance Profile, หา/copy AMI, เขียน `.env`, (ตัวเลือก) สร้างตาราง + ผู้ใช้ Admin | **ทุกคน** |
| `build_gns3_ami.py` | สร้าง GNS3 Base AMI จากศูนย์ (เปิด builder VM ชั่วคราว → ติดตั้ง GNS3 → ทดสอบ → สร้าง AMI → terminate builder) | คนที่ยังไม่มี AMI |
| `share_ami.py` | แชร์ AMI (และ Snapshot) ให้ AWS Account ของเพื่อน | เจ้าของ AMI |

### สิ่งที่ต้องมีก่อน
- Python 3.11+ และติดตั้ง dependencies แล้ว (`pip install -r requirements.txt`)
- Start Lab แล้วก็อป credentials จาก **AWS Details** ไปวางที่ `~/.aws/credentials` (Windows: `C:\Users\<ชื่อ>\.aws\credentials`):
  ```ini
  [default]
  aws_access_key_id=ASIA...
  aws_secret_access_key=...
  aws_session_token=IQoJ...
  ```
- รันทุกคำสั่งจากโฟลเดอร์ `backend/`

### ขั้นตอนสำหรับเพื่อนร่วมทีม (ทางลัด: เจ้าของโปรเจกต์แชร์ AMI ให้)

1. หา Account ID ของตัวเองแล้วส่งให้เจ้าของโปรเจกต์:
   ```bash
   aws sts get-caller-identity --query Account --output text
   ```
2. เจ้าของรัน `python scripts/share_ami.py <AMI_ID> <ACCOUNT_ID_เพื่อน>` (ดูหัวข้อ "สำหรับเจ้าของ AMI" ด้านล่าง)
3. เพื่อนรันคำสั่งเดียว (copy AMI เข้า Account ตัวเอง + ตั้งค่าทุกอย่าง + สร้างตาราง):
   ```bash
   python scripts/bootstrap_aws.py --copy-ami <AMI_ID> --write-credentials --init-db
   ```
4. รันเซิร์ฟเวอร์:
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

> ⚠️ `--copy-ami` สร้าง AMI สำเนาใหม่ **ทุกครั้งที่รัน** ให้ใช้แค่ครั้งแรก ครั้งต่อไปรัน `python scripts/bootstrap_aws.py --write-credentials` เฉยๆ สคริปต์จะหา AMI ชื่อ `netlab-gns3-base*` ใน Account ให้เอง

### ขั้นตอนสำหรับคนที่ยังไม่มี AMI (สร้างเองจากศูนย์ ไม่พึ่ง Account ใคร)

```bash
python scripts/bootstrap_aws.py --write-credentials --init-db   # สร้าง SG, Key Pair, .env, ตาราง
python scripts/build_gns3_ami.py --write-env                    # สร้าง AMI (~10-20 นาที) แล้วเขียน DEFAULT_AMI_ID ลง .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

`build_gns3_ami.py` ทำสิ่งเหล่านี้ให้:
1. หา Ubuntu 24.04 AMI ล่าสุดของ Canonical
2. เปิด builder VM (`t3.medium`, disk 16 GB) พร้อม UserData ที่ติดตั้ง `gns3-server` จาก PPA ทางการ (`ppa:gns3/ppa`) + `docker.io` (มี QEMU / Dynamips / uBridge / VPCS มากับแพ็กเกจ), ตั้ง `gns3_server.conf` (เปิด auth, port 3080, console 5900-5999) และติดตั้ง systemd service `gns3-server`
3. builder ทดสอบเรียก `/v2/version` (ต้องได้ `200` เมื่อใส่รหัส และ `401` เมื่อไม่ใส่) ผ่านแล้วพิมพ์ `NETLAB_BUILD_OK` ลง console แล้วปิดเครื่อง
4. สคริปต์อ่าน console → สร้าง AMI → **terminate builder** ทิ้ง (ไม่เสียเครดิตต่อ)
5. ล้างไฟล์ log / UserData / SSH keys ก่อนทำ AMI รหัสผ่าน GNS3 ใน AMI เป็นค่าสุ่มชั่วคราว และถูกแทนที่ด้วยรหัสใหม่ของแต่ละ VM ตอน launch

ตัวเลือกที่มีประโยชน์:
```bash
python scripts/build_gns3_ami.py --print-userdata     # ดูสคริปต์ติดตั้งโดยไม่เรียก AWS
python scripts/build_gns3_ami.py --keep-builder       # ถ้า build พัง ไม่ terminate builder ไว้ดีบั๊ก
python scripts/build_gns3_ami.py --instance-type t3.large --volume-gb 24 --name my-gns3-ami
```

### สำหรับเจ้าของ AMI: แชร์ให้เพื่อน
```bash
python scripts/share_ami.py ami-0123456789abcdef0 111122223333 444455556666
```
สคริปต์เพิ่ม Launch Permission ให้ AMI และ Snapshot ของมัน (ใช้ได้เมื่อ AMI ไม่ถูกเข้ารหัสด้วย KMS key ส่วนตัว) เพื่อนต้อง **copy เข้า Account ตัวเอง** (ผ่าน `--copy-ami`) เพราะถ้า Learner Lab ของเจ้าของถูกรีเซ็ต AMI ต้นทางจะหายไป

### ตัวเลือกของ `bootstrap_aws.py`

| Option | ความหมาย |
|---|---|
| `--write-credentials` | ก็อป credentials ปัจจุบัน (รวม session token) ลง `.env` ใช้ทุกครั้งที่เปิด Lab session ใหม่ |
| `--init-db` | รัน `init_dynamodb.py --seed` (สร้างตาราง + บัญชี Admin) |
| `--copy-ami ami-xxx` | copy AMI ที่เพื่อนแชร์มาเข้า Account ตัวเอง |
| `--ami-id ami-xxx` | ใช้ AMI ที่อยู่ใน Account ตัวเองอยู่แล้ว |
| `--ssh-cidr 1.2.3.4/32` / `--no-ssh` | กำหนด IP ที่ SSH ได้ / ไม่เปิด port 22 (ค่าเริ่มต้น: IP ปัจจุบันของคุณ) |
| `--instance-type t3.medium` | ตั้ง `DEFAULT_INSTANCE_TYPE` ใน `.env` |
| `--region`, `--env-file` | เปลี่ยน Region (ค่าเริ่มต้น `us-east-1`) / path ของ `.env` |

สิ่งที่ `bootstrap_aws.py` ทำให้:
- สร้าง Security Group `netlab-gns3-vm-sg` (เปิด `3080`, `5900-5999` และ `22` เฉพาะ IP คุณ)
- สร้าง Key Pair `gns3-cloud-keypair` และบันทึก `gns3-cloud-keypair.pem` ไว้ในโฟลเดอร์ `backend/` (AWS ให้ private key ครั้งเดียวตอนสร้าง)
- หา Instance Profile (`LabInstanceProfile`) แล้วใส่ `INSTANCE_PROFILE_NAME`
- สุ่ม `JWT_SECRET_KEY` ให้ถ้ายังเป็นค่าตัวอย่าง
- อัปเดตเฉพาะ key ที่เกี่ยวข้องใน `.env` ไม่แตะบรรทัดอื่น

> หลังรัน `--init-db` จะได้บัญชี Admin ทดสอบ: **username `admin` / Member ID `ADMIN01` / password `test1234`** (เปลี่ยนรหัสด้วยตัวแปร `SEED_PASSWORD` ก่อนรัน) แล้วใช้ Admin สร้าง Instructor / Student ผ่าน `POST /admin/users` หรือ `scripts/create_user.py`

---

## ส่วนที่ 1: การติดตั้งและรัน Local Backend (ตั้งค่าเอง)

> ข้ามส่วนนี้ได้ถ้าใช้ [ส่วนที่ 0](#ส่วนที่-0-quick-start-ด้วย-bootstrap-scripts-แนะนำ) แล้ว

### 1. ติดตั้ง Dependencies
```bash
cd backend
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. ตั้งค่าไฟล์ Environment (.env)
```bash
cp .env.example .env
```
ค่าสำคัญใน `.env`:
```ini
AWS_ACCESS_KEY_ID=ASIA...
AWS_SECRET_ACCESS_KEY=...
AWS_SESSION_TOKEN=IQoJ...       # (เฉพาะ Learner Lab)
AWS_REGION=us-east-1

DEFAULT_AMI_ID=ami-xxxxxxxxxxxxxxxxx
DEFAULT_INSTANCE_TYPE=t2.micro
DEFAULT_KEY_NAME=gns3-cloud-keypair
DEFAULT_SECURITY_GROUP_ID=sg-xxxxxxxxxxxxxxxxx
INSTANCE_PROFILE_NAME=LabInstanceProfile   # หรือ LabRole ตามที่ Account ของคุณใช้
MAX_CONCURRENT_INSTANCES=3

# DynamoDB
USERS_TABLE_NAME=netlab_users
INSTANCES_TABLE_NAME=netlab_instances
EXERCISES_TABLE_NAME=netlab_exercises

# JWT
JWT_SECRET_KEY=<สุ่มค่ายาวๆ ห้ามใช้ค่าตัวอย่าง>
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=1440
```

ตัวแปรเสริม (มีค่า default ใน `app/config.py` ไม่ต้องใส่ก็ได้): `GNS3_SET_VM_PASSWORD` (`true`), `GNS3_VM_USER` (`gns3`), `GNS3_CONFIG_PATH`, `GNS3_SERVICE_NAME`, `DYNAMODB_ENDPOINT_URL`

> ⚠️ ตัวอย่างขนาดเครื่อง `t2.micro` เหมาะกับทดสอบเท่านั้น ถ้า GNS3 ช้าหรือรัน node ไม่ไหว ให้เพิ่มเป็น `t3.medium` ขึ้นไป (`--instance-type t3.medium` ของ `bootstrap_aws.py`)

### 3. สร้างตาราง DynamoDB (ครั้งแรกครั้งเดียว รันซ้ำได้ปลอดภัย)
```bash
python scripts/init_dynamodb.py           # สร้างเฉพาะตาราง (เพิ่ม GSI ที่ขาดให้ถ้าตารางมีอยู่แล้ว)
python scripts/init_dynamodb.py --seed    # + สร้างบัญชี Admin ทดสอบ (admin / ADMIN01 / test1234)
```

### 4. สร้างบัญชีผู้ใช้ (Admin / Instructor / Student)
```bash
python scripts/create_user.py -u admin -m 0000000 -p AdminPass123! -r admin -n "System Admin"
python scripts/create_user.py -u instructor01 -m INST01 -p InstPass123! -r instructor -n "Ajarn Somchai"
python scripts/create_user.py -u student01 -m 6410001 -p StudentPass123! -r student -n "Somchai Student"
```
หรือ Login เป็น Admin แล้วสร้างผ่าน `POST /admin/users`

### 5. รันเซิร์ฟเวอร์
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
เปิด Swagger UI ที่ 👉 **`http://localhost:8000/docs`**

---

## 🧪 การทดสอบระบบ (Automated Tests)

### 1) Unit / API tests (ไม่ต้องใช้ AWS จริง)
```bash
python scripts/test_flow.py
```
ทดสอบ **26 เคส** ด้วย mock: bcrypt, JWT, Pydantic models, ล็อกโควตา VM (Sandbox/Exercise), Login / สิทธิ์ตามบทบาท, Ownership, การสร้าง/ลบ Exercise (รวม Snapshot)

### 2) ทดสอบ Bootstrap Scripts (ใช้ AWS Lab จริง)

| ลำดับ | คำสั่ง | ผลที่ควรเห็น |
|---|---|---|
| 1 | `python scripts/build_gns3_ami.py --print-userdata` | พิมพ์สคริปต์ติดตั้ง (ไม่เรียก AWS ใช้ตรวจดูได้ทุกเมื่อ) |
| 2 | `python scripts/bootstrap_aws.py --write-credentials --init-db` | `[✔] Bootstrap complete` และ `.env` มีค่า `DEFAULT_SECURITY_GROUP_ID`, `DEFAULT_KEY_NAME`, `INSTANCE_PROFILE_NAME`, `JWT_SECRET_KEY` ครบ |
| 3 | รันคำสั่งที่ 2 ซ้ำอีกครั้ง | ขึ้น `Security Group exists`, `Key pair exists` ไม่สร้างซ้ำ (ยืนยันว่ารันซ้ำได้) |
| 4 | `python scripts/build_gns3_ami.py --write-env` | `[+] Builder reports: NETLAB_BUILD_OK gns3=...` → `[✔] AMI ready: ami-...` → builder ถูก terminate และ `.env` มี `DEFAULT_AMI_ID` |
| 5 | `uvicorn ...` แล้ว Login → `POST /instances` → รอ `running` → เปิด `http://<public_ip>:3080` | ถูกถามรหัส (auth ทำงาน) ใช้ `gns3_user` / `gns3_password` จาก `GET /instances` เข้าได้ |
| 6 | `DELETE /instances/<id>` | state เป็น `terminated` และสร้าง VM ใหม่ได้ |

ตรวจ AMI และ builder ที่ค้างอยู่:
```bash
aws ec2 describe-images --owners self --filters "Name=name,Values=netlab-gns3-base*" --query "Images[].[ImageId,Name,State]" --output table
aws ec2 describe-instances --filters "Name=tag:Name,Values=netlab-gns3-ami-builder" "Name=instance-state-name,Values=pending,running,stopped" --query "Reservations[].Instances[].InstanceId"
```

### 3) ทดสอบ `share_ami.py` กับเพื่อน
เจ้าของรัน `share_ami.py` → เพื่อนรัน `bootstrap_aws.py --copy-ami <AMI_ID> ...` → ถ้าสำเร็จเพื่อนจะเห็น AMI ใน `aws ec2 describe-images --owners self`

---

## ส่วนที่ 2: สรุปและตัวอย่างการเรียกใช้ API

> รายละเอียดทุก Endpoint และ Response Model อยู่ที่ [`api_doc.md`](api_doc.md)

| กลุ่ม | Endpoint | สิทธิ์ |
|---|---|---|
| System | `GET /`, `GET /health` | Public |
| Auth | `POST /auth/login`, `POST /auth/logout`, `GET /auth/me` | Public / Public / User |
| Exercises | `GET /exercises`, `GET /exercises/{id}` | Public |
| | `POST /exercises` | Instructor |
| | `DELETE /exercises/{id}` | เจ้าของ (Instructor) / Admin |
| Instances | `POST /instances`, `GET /instances` | User (Admin สร้างไม่ได้) |
| | `POST /instances/{id}/start`, `/stop`, `DELETE /instances/{id}` | เจ้าของ / Admin |
| Admin | `POST/GET /admin/users`, `PATCH/DELETE /admin/users/{id}`, `GET /admin/dashboard` | Admin |

### 1. เข้าสู่ระบบ (Username หรือ Member ID)
```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"identifier": "6410001", "password": "StudentPass123!"}' \
  -c cookies.txt
```
ระบบเก็บคุกกี้ `access_token` ลง `cookies.txt` และส่ง JWT กลับมาใน Response

### 2. ดูข้อมูลโปรไฟล์และสถานะ VM
```bash
curl http://localhost:8000/auth/me -b cookies.txt
# หรือ
curl http://localhost:8000/auth/me -H "Authorization: Bearer <TOKEN_HERE>"
```

### 2.1 ออกจากระบบ
```bash
curl -X POST http://localhost:8000/auth/logout -b cookies.txt -c cookies.txt
```
ระบบลบคุกกี้ `access_token` ให้ (ถ้าใช้ Bearer Token ให้ลบ Token ทิ้งฝั่ง Client เอง เพราะ Token ยังใช้ได้จนหมดอายุ)

### 3. ดูรายการแบบฝึกหัด Lab
```bash
curl http://localhost:8000/exercises
```

### 4. สร้างแบบฝึกหัด (Instructor)
```bash
# Snapshot จาก VM ของอาจารย์ (ระบุ instance_id ถ้ามีหลายเครื่อง)
curl -X POST http://localhost:8000/exercises -b cookies.txt \
  -H "Content-Type: application/json" \
  -d '{"title": "OSPF Lab 1", "description": "ตั้งค่า OSPF 2 Area", "instance_id": "i-0123456789abcdef0"}'

# หรือใช้ AMI ที่มีอยู่แล้ว
curl -X POST http://localhost:8000/exercises -b cookies.txt \
  -H "Content-Type: application/json" \
  -d '{"title": "OSPF Lab 1", "description": "ตั้งค่า OSPF 2 Area", "ami_id": "ami-xxxxxxxx"}'
```

### 5. ขอสร้าง GNS3 VM
```bash
# Sandbox (VM ว่าง)
curl -X POST http://localhost:8000/instances -b cookies.txt \
  -H "Content-Type: application/json" \
  -d '{"instance_name": "gns3-student01-sandbox"}'

# จากแบบฝึกหัด
curl -X POST http://localhost:8000/instances -b cookies.txt \
  -H "Content-Type: application/json" \
  -d '{"instance_name": "gns3-lab1-vm", "exercise_id": "<EXERCISE_ID>"}'
```
*นักศึกษาที่มี VM ในช่องนั้นอยู่แล้ว (Sandbox หรือ Exercise) จะได้ `400 Bad Request` ส่วนถ้า VM ทั้งโปรเจกต์ถึง `MAX_CONCURRENT_INSTANCES` จะได้ `429`*

### 6. ดูรายการ VM (พร้อมรหัสเข้า GNS3 ของเครื่องตัวเอง)
```bash
curl http://localhost:8000/instances -b cookies.txt
```
ผลลัพธ์มี `public_ip`, `gns3_user`, `gns3_password` เปิด GNS3 ได้ที่ `http://<public_ip>:3080`

### 7. เปิด / ปิด / ลบ VM
```bash
curl -X POST   http://localhost:8000/instances/i-0123456789abcdef0/start -b cookies.txt
curl -X POST   http://localhost:8000/instances/i-0123456789abcdef0/stop  -b cookies.txt
curl -X DELETE http://localhost:8000/instances/i-0123456789abcdef0       -b cookies.txt
```
*Terminate แล้วสถานะใน DynamoDB เป็น `terminated` และโควตาถูกคืนทันที (Stop แล้ว Public IP จะหาย Start ใหม่จะได้ IP ใหม่)*

---

## ส่วนที่ 3: การ Deploy ไปยัง Amazon ECR และ AWS ECS (Fargate)

รองรับทั้ง **AWS Academy Learner Lab** และ **AWS Account จริงทั่วไป**

> 📦 ไฟล์ที่ใช้ใน Deploy คือ `backend/Dockerfile`, `backend/.dockerignore` และ `backend/scripts/push_to_ecr.sh` ซึ่งอยู่ในสาขา `main` ของ repo ถ้าโฟลเดอร์ `backend/` ของคุณยังไม่มี ให้คัดลอกมาจาก repo ก่อน

> ✅ ควรรัน `init_dynamodb.py` (ตารางอยู่ใน AWS Account เดียวกับที่ ECS ใช้) ก่อน Deploy เพราะ Container ไม่ได้สร้างตารางให้เอง

### ขั้นตอนที่ 1: Push Docker Image ไปยัง Amazon ECR

#### วิธีที่ 1: ใช้สคริปต์อัตโนมัติ (แนะนำ)
[`scripts/push_to_ecr.sh`](scripts/push_to_ecr.sh) อ่าน credentials (รวม `AWS_SESSION_TOKEN`) จาก `.env`, หา Account ID, สร้าง ECR repository `gns3-backend` (ถ้ายังไม่มี), build image แบบ `--platform linux/amd64` และ push ให้ในคำสั่งเดียว:

```bash
cd backend
chmod +x scripts/push_to_ecr.sh
./scripts/push_to_ecr.sh            # tag = latest (หรือ ./scripts/push_to_ecr.sh v1)
```
> สำเร็จแล้วสคริปต์แสดง **ECR Image URI** เช่น `<AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/gns3-backend:latest` ให้คัดลอกไว้ใช้ในขั้นตอนถัดไป
>
> ใช้บน Windows ให้รันผ่าน **Git Bash** หรือ **WSL** และต้องเปิด Docker Desktop ไว้

#### วิธีที่ 2: รันคำสั่งเองทีละขั้น
```bash
cd backend

# 1. โหลด credentials จาก .env
export $(grep -v '^#' .env | xargs)
export AWS_DEFAULT_REGION="us-east-1"

# 2. ดึง AWS Account ID
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# 3. Login Docker เข้า ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin "${AWS_ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com"

# 4. สร้าง ECR Repository (ครั้งแรกครั้งเดียว)
aws ecr create-repository --repository-name gns3-backend --region us-east-1

# 5. Build (linux/amd64 เพื่อให้รันบน Fargate ได้ทุกเครื่อง)
docker build --platform linux/amd64 -t gns3-backend:latest .

# 6. Tag และ Push
docker tag gns3-backend:latest "${AWS_ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/gns3-backend:latest"
docker push "${AWS_ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/gns3-backend:latest"
```

> `.dockerignore` กัน `.env` และ `*.pem` ไม่ให้ถูกใส่ลง image (ค่า Secret ต้องส่งผ่าน Environment Variables ของ ECS เท่านั้น)

---

### ขั้นตอนที่ 2: สร้าง ECS Cluster
1. AWS Console → **Elastic Container Service (ECS)** (ตรวจว่าอยู่ `us-east-1`)
2. **Clusters** → **Create cluster**
3. **Cluster name**: `gns3-cluster` / **Infrastructure**: **AWS Fargate (serverless)**
4. กด **Create** (รอ ~10-20 วินาทีจนเป็น Active)

---

### ขั้นตอนที่ 3: สร้าง Task Definition
1. **Task definitions** → **Create new task definition**
2. ตั้งค่า:
   - **Family**: `gns3-backend-task`
   - **Launch type**: `AWS Fargate` / **OS-Architecture**: `Linux/X86_64`
   - **Task size**: CPU `.5 vCPU`, Memory `1 GB`
   - **Task role** และ **Task execution role**: `LabRole` (ให้ ECS ดึง image จาก ECR และส่ง log เข้า CloudWatch ได้)
3. **Container - 1**:
   - **Name**: `backend`
   - **Image URI**: Image URI จากขั้นตอนที่ 1
   - **Port mappings**: Container port `8000`, Protocol `TCP`
   - **Health check**: **ปล่อยว่าง** (ใช้ `HEALTHCHECK` ใน `Dockerfile` ซึ่งเรียก `/health`)
   - **Environment variables**:

   | Key | Value (นำจาก `.env`) |
   |---|---|
   | `AWS_ACCESS_KEY_ID` | `ASIA...` |
   | `AWS_SECRET_ACCESS_KEY` | `...` |
   | `AWS_SESSION_TOKEN` | `IQoJ...` (เฉพาะ Learner Lab) |
   | `AWS_REGION` | `us-east-1` |
   | `DEFAULT_AMI_ID` | `ami-xxxxxxxxxxxxxxxxx` |
   | `DEFAULT_KEY_NAME` | `gns3-cloud-keypair` |
   | `DEFAULT_SECURITY_GROUP_ID` | `sg-xxxxxxxxxxxxxxxxx` (SG ของ **GNS3 VM** ไม่ใช่ SG ของ ECS) |
   | `DEFAULT_INSTANCE_TYPE` | `t2.micro` (หรือ `t3.medium`) |
   | `INSTANCE_PROFILE_NAME` | `LabInstanceProfile` / `LabRole` ตามค่าใน `.env` |
   | `MAX_CONCURRENT_INSTANCES` | `3` |
   | `USERS_TABLE_NAME` | `netlab_users` |
   | `INSTANCES_TABLE_NAME` | `netlab_instances` |
   | `EXERCISES_TABLE_NAME` | `netlab_exercises` |
   | `JWT_SECRET_KEY` | ค่าเดียวกับใน `.env` (**ห้ามใช้ค่าตัวอย่าง**) |
   | `JWT_ALGORITHM` | `HS256` |
   | `JWT_EXPIRE_MINUTES` | `1440` |

4. กด **Create**

---

### ขั้นตอนที่ 4: สร้าง Security Group สำหรับ ECS (เปิด Port 8000)
1. **EC2 Console** → **Security Groups** (us-east-1) → **Create security group**
2. **Name**: `ecs-backend-sg` / **Description**: `Allow port 8000 for ECS FastAPI backend` / **VPC**: Default VPC
3. **Inbound rules**: Custom TCP, port `8000`, Source `0.0.0.0/0`
4. **Create security group**

---

### ขั้นตอนที่ 5: สั่งรัน Container ผ่าน ECS Service
1. **ECS** → **Clusters** → `gns3-cluster` → แท็บ **Services** → **Create**
2. ตั้งค่า:
   - **Compute options**: Launch type → `FARGATE`
   - **Application type**: `Service` / **Family**: `gns3-backend-task` / **Revision**: LATEST
   - **Service name**: `gns3-backend-service` / **Desired tasks**: `1`
   - **Networking**: VPC = Default VPC, Subnets = public subnet, Security group = `ecs-backend-sg`
   - ⚠️ **Public IP**: **Turned on (ENABLED)** *(สำคัญมาก ไม่งั้น task ดึง image จาก ECR ไม่ได้ และเข้าจากภายนอกไม่ได้)*
3. **Create** แล้วรอ ~30-60 วินาทีจน Task เป็น **`RUNNING`** และ Health เป็น **`HEALTHY`**

---

### ขั้นตอนที่ 6: ทดสอบ API บน ECS
1. **Services** → แท็บ **Tasks** → คลิก Task ID → คัดลอก **Public IP**
2. ทดสอบ:
   ```bash
   # Health check
   curl http://<TASK_PUBLIC_IP>:8000/health
   # ผลลัพธ์: {"status":"ok","service":"netlab-backend"}

   # Login แล้วสร้าง VM (ต้อง login ก่อน)
   curl -X POST http://<TASK_PUBLIC_IP>:8000/auth/login \
     -H "Content-Type: application/json" \
     -d '{"identifier": "student01", "password": "StudentPass123!"}' -c cookies.txt

   curl -X POST http://<TASK_PUBLIC_IP>:8000/instances -b cookies.txt \
     -H "Content-Type: application/json" \
     -d '{"instance_name": "gns3-ecs-vm1"}'
   ```
   เปิด Swagger UI: `http://<TASK_PUBLIC_IP>:8000/docs`

---

### 🛠️ Troubleshooting

| ปัญหา / Error | สาเหตุ | วิธีแก้ |
|---|---|---|
| `ResourceInitializationError: dial tcp ...:443: i/o timeout` | Fargate ไม่มีอินเทอร์เน็ตดึง image จาก ECR | ตอนสร้าง Service ต้องเปิด **Public IP: ENABLED** และใช้ Default VPC |
| `Task failed health checks and stopped` | ตั้ง health check ผิดรูปแบบ หรือแอปสตาร์ทไม่ผ่าน | ปล่อยช่อง Health Check ใน Task Definition ว่าง และดู CloudWatch Log ว่า Uvicorn สตาร์ทสำเร็จหรือไม่ (ถ้าขาด Environment Variable ที่จำเป็น เช่น `DEFAULT_AMI_ID` แอปจะ crash ตอนเริ่ม) |
| `curl` ค้าง / `Operation timed out` | Security Group บล็อก port 8000 | เพิ่ม Inbound `8000` จาก `0.0.0.0/0` ให้ `ecs-backend-sg` |
| `Connection refused` | ไม่ใส่ port หรือใช้ IP ผิด | ใช้ `http://<PUBLIC_IP>:8000/...` และต้องเป็น **Public IP** ไม่ใช่ Private IP (172.31.x.x) |
| `ExpiredToken` / `InvalidClientTokenId` | Session Token ของ Learner Lab หมดอายุ (3-4 ชม.) | Start Lab ใหม่ → ก็อป AWS Details → อัปเดตค่าใน `.env` (ใช้ `bootstrap_aws.py --write-credentials`) และใน Environment Variables ของ Task Definition (สร้าง Revision ใหม่) แล้ว Update Service ให้ใช้ Revision ล่าสุด |
| `LabRole` / `InvalidParameterValue: Value (...) for parameter iamInstanceProfile.name is invalid` ตอนสร้าง VM | ชื่อ Instance Profile ใน `INSTANCE_PROFILE_NAME` ไม่ตรงกับที่มีใน Account | ใช้ `LabInstanceProfile` (หรือรัน `bootstrap_aws.py` ให้หาชื่อที่ถูกต้อง) |
| `InvalidAMIID.NotFound` ตอนสร้าง VM | AMI ไม่อยู่ใน Account/Region นี้ (เช่น Lab ถูกรีเซ็ต) | สร้างใหม่ด้วย `build_gns3_ami.py` หรือ `--copy-ami` จากเพื่อน |
| `build_gns3_ami.py` ขึ้น "ไม่พบ marker ใน console output" | Console output ของ builder มาช้า หรือ build ล้มเหลว | ดู log ด้วย `aws ec2 get-console-output --instance-id <ID> --latest --output text` และรันใหม่ด้วย `--keep-builder` เพื่อดีบั๊ก |

---

## 🔒 มาตรการความปลอดภัยและคำแนะนำ

1. **ห้าม commit / แชร์ `.env` และ `*.pem`**: มี AWS credentials, `JWT_SECRET_KEY` และ private key ของ EC2 (ตรวจว่า `.gitignore` ของโปรเจกต์ครอบคลุมทั้งสองไฟล์) ถ้าบีบไฟล์ `backend` ส่งให้คนอื่น ให้ลบ 2 ไฟล์นี้ออกก่อน
2. **เปลี่ยนรหัส Admin ทดสอบ** (`test1234`) และ `JWT_SECRET_KEY` ก่อนใช้งานจริง
3. **Bcrypt Password Security**: รหัสผ่านผู้ใช้ไม่ถูกเก็บเป็น Plain text
4. **Atomic State Locks**: กัน Race Condition ในการขอสร้าง VM ด้วย DynamoDB Conditional Expressions
5. **Ownership & Role Verification**: ทุก Endpoint ตรวจ Identity และบทบาท ผู้ใช้สั่งควบคุม/ลบเครื่องคนอื่นไม่ได้
6. **รหัส GNS3 แยกต่อ VM**: GNS3 เปิด auth เสมอ และแต่ละ VM ได้รหัสสุ่มของตัวเอง ใครเห็นได้เฉพาะเจ้าของ VM
7. **Security Group**: `3080` และ `5900-5999` เปิด `0.0.0.0/0` (เพื่อให้นักศึกษาเชื่อมต่อได้จากทุกที่) ส่วน `22` เปิดเฉพาะ IP ผู้ดูแล ถ้าต้องการเข้มงวดขึ้น ให้จำกัด Source ตามเครือข่ายของมหาวิทยาลัย
8. **Tag `Project=gns3-cloud`**: ทุก Resource ที่ระบบสร้างถูกติด Tag นี้เพื่อแยกจาก Resource อื่นในบัญชีเดียวกัน และ API ใช้นับโควตา `MAX_CONCURRENT_INSTANCES`
9. **ปิด VM ที่ไม่ใช้**: Learner Lab มี Budget จำกัด ควร Stop / Terminate VM ทุกครั้งที่เลิกใช้งาน

**.gitignore แนะนำ**
```
venv/
.env
.env.*
!.env.example
__pycache__/
*.pem
```
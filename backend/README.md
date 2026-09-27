# GNS3 Cloud - NetLab Backend API

FastAPI backend สำหรับระบบ **NetLab** ให้นักศึกษาแขนง Infrastructure ขอสร้างและควบคุม GNS3 VM บน AWS EC2 ผ่านเว็บไซต์ พร้อมระบบจัดการฐานข้อมูลผู้ใช้, อินสแตนซ์, และแบบฝึกหัด Lab ด้วย **Amazon DynamoDB (Reduced Schema)**, ระบบความปลอดภัย **JWT Authentication**, และการจำกัดสิทธิ์ **1 VM ต่อ 1 ผู้ใช้** แบบ Atomic

---

## 🚀 ฟีเจอร์หลักของระบบ

1. **Authentication & User Management (DynamoDB)**
   - ระบบลงชื่อเข้าใช้ด้วย Username หรือ Member ID พร้อมรหัสผ่านที่เข้ารหัสด้วย `bcrypt`
   - ออกบัตรประจำตัวแบบ **JWT (HS256)** รองรับทั้ง `Authorization: Bearer <token>` และ `HttpOnly Cookie`
   - แบ่งระดับสิทธิ์ผู้ใช้: `student`, `instructor`, และ `admin`
   - สคริปต์ CLI สำหรับสร้างบัญชี Admin, ผู้สอน, และนักศึกษา (`scripts/create_user.py`)
2. **EC2 & VM Lifecycle with DynamoDB Persistence (Reduced Schema)**
   - **Atomic 1-VM Limit**: ผู้ใช้แต่ละคนมีสิทธิ์เปิดใช้งาน VM ได้สูงสุด **1 เครื่องพร้อมกันเท่านั้น** (ป้องกันด้วย DynamoDB Conditional Write ไม่ให้เกิด Race Condition)
   - **Reduced Schema**: อินสแตนซ์ผูกกับ `user_id` เพียงตัวเดียว ตัด `student_id` และ `StudentIdIndex` GSI ออกเพื่อประหยัดค่าใช้จ่ายการเขียน Index ใน DynamoDB ถึง 50%
   - Real-time Sync สถานะจาก EC2 (Pending, Running, Stopped, Terminated) เข้าตาราง DynamoDB อัตโนมัติ
   - Ownership Protection: นักศึกษาไม่สามารถ Start, Stop หรือ Terminate VM ของผู้อื่นได้
   - คืนโควตา 1 VM ทันทีเมื่อผู้ใช้สั่ง Terminate VM ตัวเดิม
3. **Lab Exercises Management**
   - รองรับการสร้างแบบฝึกหัด Lab (`netlab_exercises`) จาก Template / Snapshot AMI
   - นักศึกษาสามารถเลือก `exercise_id` ตอนขอสร้าง VM เพื่อโหลดโจทย์และ Topology มาเริ่มต้นใช้งานได้ทันที
4. **Automated Provisioning & Verification**
   - สคริปต์สร้างตาราง DynamoDB อัตโนมัติ (`scripts/init_dynamodb.py`) แบบ On-Demand (`PAY_PER_REQUEST`)
   - ชุดทดสอบความถูกต้องของระบบแบบครอบคลุม 100% (`scripts/test_flow.py`)
   - เอกสารสรุป API ทุก Route ฉบับเต็มใน [`api_doc.md`](api_doc.md)

---

## 🗄️ โครงสร้างฐานข้อมูล DynamoDB (Reduced Schema)

ระบบใช้ตาราง DynamoDB จำนวน 3 ตารางแบบ On-Demand (`PAY_PER_REQUEST`):

```mermaid
erDiagram
    USERS {
        string user_id PK "UUID"
        string username GSI "UsernameIndex"
        string member_id GSI "MemberIdIndex"
        string password_hash "Bcrypt hash"
        string full_name
        string role "student | instructor | admin"
        string active_instance_id "Nullable - 1-VM lock"
        string created_at "ISO-8601"
        string updated_at "ISO-8601"
    }

    VM_INSTANCES {
        string instance_id PK "EC2 Instance ID (i-xxx)"
        string user_id GSI "UserIdIndex (single user reference)"
        string exercise_id "Nullable - references EXERCISES"
        string name "Instance friendly name"
        string instance_type
        string ami_id
        string state "pending | running | stopped | terminated"
        string public_ip "Nullable"
        string private_ip "Nullable"
        string launch_time "ISO-8601"
        string terminated_at "Nullable"
    }

    EXERCISES {
        string exercise_id PK "UUID"
        string instructor_id GSI "InstructorIdIndex"
        string ami_id "AWS EC2 AMI ID"
        string title
        string description
        string status "pending | available | failed"
        boolean is_active
        string created_at "ISO-8601"
    }

    USERS ||--o| VM_INSTANCES : "owns at most 1 active"
    USERS ||--o{ EXERCISES : "creates"
    EXERCISES ||--o{ VM_INSTANCES : "spawns"
```

---

## ⚠️ คำแนะนำสำหรับ AWS Academy Learner Lab

โปรเจกต์นี้รองรับทั้ง **AWS Academy Learner Lab** และ **AWS Account จริงทั่วไป**:
- **AWS Learner Lab**:
  - ล็อกให้ใช้งาน Region `us-east-1` (N. Virginia)
  - Credentials มีอายุ ~3-4 ชั่วโมง (มี `aws_session_token`)
  - ใช้ IAM Role ชื่อ `LabRole` ที่ระบบเตรียมไว้ให้สำหรับ EC2 instance profile
  - ให้คัดลอกค่าจากปุ่ม **AWS Details** ในหน้า Lab มาใส่ในไฟล์ `.env` ทุกครั้งที่เปิด Session ใหม่
- **AWS Account จริง**:
  - ลบบรรทัด `AWS_SESSION_TOKEN` ใน `.env` ทิ้งได้
  - เลือก Region ที่ต้องการได้อิสระ เช่น `ap-southeast-1`

---

## ส่วนที่ 1: การติดตั้งและรัน Local Backend

### 1. ติดตั้ง Dependencies
```bash
cd backend
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. ตั้งค่าไฟล์ Environment (.env)
คัดลอกไฟล์ตัวอย่างและใส่ค่า Credentials ให้ครบ:
```bash
cp .env.example .env
```
กำหนดค่าสำคัญใน `.env`:
```ini
AWS_ACCESS_KEY_ID=ASIA...
AWS_SECRET_ACCESS_KEY=...
AWS_SESSION_TOKEN=IQoJ...       # (เฉพาะ Learner Lab)
AWS_REGION=us-east-1

DEFAULT_AMI_ID=ami-xxxxxxxxxxxxxxxxx
DEFAULT_INSTANCE_TYPE=t2.micro
DEFAULT_KEY_NAME=gns3-cloud-keypair
DEFAULT_SECURITY_GROUP_ID=sg-xxxxxxxxxxxxxxxxx
INSTANCE_PROFILE_NAME=LabRole
MAX_CONCURRENT_INSTANCES=3

# DynamoDB Configuration
USERS_TABLE_NAME=netlab_users
INSTANCES_TABLE_NAME=netlab_instances
EXERCISES_TABLE_NAME=netlab_exercises

# JWT Configuration
JWT_SECRET_KEY=netlab-super-secret-key-change-in-production
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=1440
```

### 3. สร้างตารางใน DynamoDB (ทำครั้งแรกครั้งเดียว)
รันสคริปต์เพื่อสร้างตาราง `netlab_users`, `netlab_instances`, และ `netlab_exercises`:
```bash
python scripts/init_dynamodb.py
```

### 4. สร้างบัญชีผู้ใช้เริ่มต้น (Admin / Instructor / Student)
ใช้สคริปต์ CLI เพื่อสร้างบัญชี (ใช้ `-m` / `--member-id`):
```bash
# สร้างบัญชี Admin
python scripts/create_user.py -u admin -m 0000000 -p AdminPass123! -r admin -n "System Admin"

# สร้างบัญชีผู้สอน
python scripts/create_user.py -u instructor01 -m INST01 -p InstPass123! -r instructor -n "Ajarn Somchai"

# สร้างบัญชีนักศึกษา
python scripts/create_user.py -u student01 -m 6410001 -p StudentPass123! -r student -n "Somchai Student"
```

### 5. รันเซิร์ฟเวอร์ Backend
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
เปิดดู Interactive Swagger UI เพื่อทดสอบ API ได้ทันทีที่:  
👉 **`http://localhost:8000/docs`**

---

## 🧪 การทดสอบระบบ (Automated Tests)

รันชุดทดสอบเพื่อยืนยันว่าระบบ Authentication, Member ID, Single Index Instances, Exercises, และ 1-VM Limit ทำงานได้ถูกต้องสมบูรณ์ 100%:

```bash
python scripts/test_flow.py
```
*จะทำการทดสอบ 17 Test Cases และรายงานผลทันทีโดยไม่ต้องเปิด AWS Lab*

---

## ส่วนที่ 2: สรุปและตัวอย่างการเรียกใช้ API

> ดูคู่มือ API ฉบับละเอียดและ Response Model ทั้งหมดได้ที่ [`api_doc.md`](api_doc.md)

### 1. เข้าสู่ระบบ (Login ด้วย Username หรือ Member ID)
```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"identifier": "6410001", "password": "StudentPass123!"}' \
  -c cookies.txt
```
*ระบบจะบันทึกคุกกี้ `access_token` ลงใน `cookies.txt` และส่งค่า JWT Token กลับมาใน Response*

### 2. ดูข้อมูลโปรไฟล์ตนเองและสถานะ VM
```bash
# เรียกโดยใช้คุกกี้
curl -X GET http://localhost:8000/auth/me -b cookies.txt

# หรือเรียกโดยใช้ Authorization Header
curl -X GET http://localhost:8000/auth/me \
  -H "Authorization: Bearer <TOKEN_HERE>"
```

### 3. ดูรายการแบบฝึกหัด Lab (Exercises)
```bash
curl -X GET http://localhost:8000/exercises
```

### 4. ขอสร้าง GNS3 VM ใหม่ (ผูกกับผู้ใช้และจำกัด 1 VM)
```bash
# สั่งสร้าง VM ว่างเปล่าทั่วไป
curl -X POST http://localhost:8000/instances \
  -b cookies.txt \
  -H "Content-Type: application/json" \
  -d '{"instance_name": "gns3-student01-vm1"}'

# หรือสั่งสร้าง VM จากแบบฝึกหัด Lab
curl -X POST http://localhost:8000/instances \
  -b cookies.txt \
  -H "Content-Type: application/json" \
  -d '{"instance_name": "gns3-lab1-vm", "exercise_id": "<EXERCISE_ID>"}'
```
*หากผู้ใช้มี VM ที่ยังไม่ถูก Terminate อยู่แล้ว API จะตอบกลับด้วย `400 Bad Request` ทันที*

### 5. ดูรายการ VM ทั้งหมดของตนเอง
```bash
curl -X GET http://localhost:8000/instances -b cookies.txt
```

### 6. เปิดเครื่อง / ปิดเครื่อง VM
```bash
# เปิดเครื่อง (Start)
curl -X POST http://localhost:8000/instances/i-0123456789abcdef0/start -b cookies.txt

# ปิดเครื่องชั่วคราว (Stop)
curl -X POST http://localhost:8000/instances/i-0123456789abcdef0/stop -b cookies.txt
```

### 7. ลบ VM (Terminate) และคืนโควตา 1 VM
```bash
curl -X DELETE http://localhost:8000/instances/i-0123456789abcdef0 -b cookies.txt
```
*เมื่อคำสั่งสำเร็จ สถานะ VM ใน DynamoDB จะเปลี่ยนเป็น `terminated` และผู้ใช้จะสามารถขอสร้าง VM ตัวใหม่ได้ทันที*

---

## ส่วนที่ 3: การ Deploy ไปยัง Amazon ECR และ AWS ECS (Fargate)

### ขั้นตอนที่ 1: Build & Push Image ไปยัง Amazon ECR
ใช้สคริปต์อัตโนมัติเพื่ออ่านค่าจาก `.env` และ push image:
```bash
chmod +x scripts/push_to_ecr.sh
./scripts/push_to_ecr.sh
```

### ขั้นตอนที่ 2: ตั้งค่า ECS Task Definition
1. ในหน้า **Task definitions** เลือก Task Role และ Task Execution Role เป็น `LabRole`
2. กำหนด Container port: `8000` (TCP)
3. ใส่ **Environment Variables** ให้ครบตามไฟล์ `.env`:
   - `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, `AWS_REGION`
   - `DEFAULT_AMI_ID`, `DEFAULT_KEY_NAME`, `DEFAULT_SECURITY_GROUP_ID`, `DEFAULT_INSTANCE_TYPE`
   - `USERS_TABLE_NAME` (`netlab_users`), `INSTANCES_TABLE_NAME` (`netlab_instances`), `EXERCISES_TABLE_NAME` (`netlab_exercises`)
   - `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `JWT_EXPIRE_MINUTES`

### ขั้นตอนที่ 3: รัน ECS Service (Fargate)
1. เลือก Subnet และ Security Group ที่เปิด Inbound port `8000` (`0.0.0.0/0`)
2. **สำคัญมาก**: ตรวจสอบว่าเปิด **Public IP: ENABLED**
3. เมื่อ Task สถานะเป็น `RUNNING` นำ Public IP ของ Task ไปเปิดใช้งานผ่านเบราว์เซอร์:
   `http://<TASK_PUBLIC_IP>:8000/docs`

---

## 🔒 มาตรการความปลอดภัยและคำแนะนำ

1. **ห้าม Commit `.env` ขึ้น Git**: ไฟล์ `.env` เก็บข้อมูล Secret Key และ AWS Token ซึ่งจะถูกละเว้นโดย `.gitignore`
2. **Bcrypt Password Security**: รหัสผ่านของผู้ใช้ไม่เคยถูกจัดเก็บในรูป Plain text
3. **Atomic State Locks**: ระบบป้องกัน Race condition ในการขอสร้าง VM ของนักศึกษาด้วย DynamoDB Conditional Expressions
4. **Ownership Verification**: Endpoint ทุกจุดมีการตรวจสอบ Identity เพื่อป้องกันไม่ให้ผู้ใช้แอบสั่งควบคุมหรือลบเครื่องของคนอื่น

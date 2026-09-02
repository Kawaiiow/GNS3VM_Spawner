# GNS3 Cloud - EC2 API

FastAPI backend สำหรับให้นักศึกษาแขนง Infrastructure ขอสร้าง/ควบคุม GNS3 VM
บน AWS EC2 ผ่านเว็บไซต์ โดยไม่ต้องติดตั้ง GNS3 ลงเครื่องเอง

รองรับ:
- `POST   /instances`              - สร้าง (launch) EC2 instance ใหม่
- `GET    /instances`              - list instance ทั้งหมด / filter ตาม student_id
- `POST   /instances/{id}/start`   - เปิดเครื่อง
- `POST   /instances/{id}/stop`    - ปิดเครื่องชั่วคราว
- `DELETE /instances/{id}`         - terminate (ลบถาวร)

---

## ⚠️ ใช้ AWS Academy Learner Lab อยู่หรือเปล่า?

โค้ดชุดนี้รองรับทั้ง 2 แบบอยู่แล้ว (สลับได้แค่แก้ `.env`) แต่ขั้นตอนเตรียม AWS
**ไม่เหมือนส่วนที่ 1 ด้านล่าง** ให้ข้ามไปทำตาม **ส่วนที่ 1B** แทน แล้วค่อยกลับมา
ทำส่วนที่ 2 (รัน API) ตามปกติ

ทุกจุดในโค้ดที่ต่างกันระหว่าง Learner Lab กับ AWS account จริง จะมีคอมเมนต์
`>>> LEARNER LAB ONLY <<<` กำกับไว้ในไฟล์ `app/config.py` และ `app/ec2_service.py`
อ่านตรงนั้นได้เลยถ้าจะย้ายจาก Lab ไปใช้ account จริงทีหลัง

---

## ส่วนที่ 1: เตรียม AWS ตั้งแต่ศูนย์ (สำหรับ AWS account จริงทั่วไป)

### 1. สมัคร AWS Account
ไปที่ https://aws.amazon.com/ กด "Create an AWS Account" แล้วกรอกอีเมล/บัตรเครดิต
(AWS จะยึด 1 USD ชั่วคราวเพื่อยืนยันบัตร) เลือก Free Tier ได้เพื่อลดค่าใช้จ่ายช่วงทดสอบ

### 2. สร้าง IAM User สำหรับให้ API ใช้ (ห้ามใช้ root account key)
1. เข้า AWS Console -> ค้นหา **IAM** -> **Users** -> **Create user**
2. ตั้งชื่อ เช่น `gns3-cloud-api`
3. เลือก **Attach policies directly** แล้วแนบ policy `AmazonEC2FullAccess`
   (โปรเจคจริงควรจำกัดสิทธิ์ให้แคบกว่านี้ แต่สำหรับโปรเจควิชาใช้ตัวนี้ก่อนได้)
4. สร้างเสร็จแล้วเข้าไปที่ user -> แท็บ **Security credentials** -> **Create access key**
   -> เลือก use case เป็น **Application running outside AWS**
5. จะได้ `Access Key ID` และ `Secret Access Key` มา **เก็บไว้ให้ดี เห็นครั้งเดียว**
   -> เอาไปใส่ในไฟล์ `.env` (ดูส่วนที่ 2)

### 3. สร้าง EC2 Key Pair (ไว้ SSH เข้า instance)
IAM Console -> **EC2** -> **Key Pairs** -> **Create key pair**
- ตั้งชื่อ เช่น `gns3-cloud-keypair`
- Format: `.pem` (Linux/Mac) หรือ `.ppk` (ถ้าใช้ PuTTY บน Windows)
- ดาวน์โหลดไฟล์เก็บไว้ (ใช้ตอนต้องการ SSH/RDP เข้า VM โดยตรง)

### 4. สร้าง Security Group (เปิด port ที่ GNS3 ต้องใช้)
EC2 Console -> **Security Groups** -> **Create security group**
เพิ่ม Inbound rules อย่างน้อย:
| Type       | Port range   | Source              | หมายเหตุ |
|------------|-------------|---------------------|----------|
| SSH        | 22          | My IP หรือ 0.0.0.0/0 | เข้าเครื่องผ่าน terminal |
| Custom TCP | 3080        | 0.0.0.0/0           | GNS3 server web UI |
| Custom TCP | 5900-5999   | 0.0.0.0/0           | VNC console ของ QEMU/IOS node |
| RDP        | 3389        | 0.0.0.0/0 (ถ้าใช้ Windows GUI) | ถ้าทำ GUI ผ่าน RDP |

คัดลอก **Security Group ID** (ขึ้นต้น `sg-...`) ไว้ใส่ `.env`

### 5. เตรียม AMI ที่มี GNS3 ลงไว้แล้ว (สำคัญที่สุด)
มี 2 ทางเลือก:
- **ทางลัด**: ค้นหา "GNS3" ใน AWS Marketplace (มี community AMI ที่ลง GNS3 server ไว้แล้ว)
- **ทำเอง**: launch EC2 instance ธรรมดา (Ubuntu 22.04) -> ติดตั้ง GNS3 server +
  IOU/QEMU support ตามคู่มือ https://docs.gns3.com/ -> จากนั้นไปที่
  EC2 Console -> เลือก instance นั้น -> Actions -> Image -> **Create image**
  จะได้ **AMI ID** ของตัวเองมาใช้เป็น `DEFAULT_AMI_ID`

---

## ส่วนที่ 1B: เตรียม AWS ผ่าน AWS Academy Learner Lab (ทำทุกครั้งที่เปิด lab session ใหม่)

Learner Lab **ไม่ให้เข้า IAM Console สร้าง user/key เอง** และ credentials เป็น
แบบชั่วคราว หมดอายุทุก ~3-4 ชม. ต้องทำตามนี้ทุกครั้งที่เริ่ม session ใหม่:

### 1. Start Lab
เข้า AWS Academy -> เลือกคอร์ส -> **Learner Lab** -> กด **Start Lab**
รอจนวงกลมข้าง AWS เปลี่ยนเป็นสีเขียว (ใช้เวลาประมาณ 1-3 นาที)

### 2. ก็อป Credentials
คลิก **AWS Details** (อยู่ข้างปุ่ม Start Lab) -> จะเห็นกล่อง **AWS CLI** ที่มี
```
[default]
aws_access_key_id=...
aws_secret_access_key=...
aws_session_token=...
```
ก็อปทั้ง 3 ค่าไปใส่ใน `.env` ที่ `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
`AWS_SESSION_TOKEN` ตามลำดับ (ดู `.env.example` มี field พวกนี้เตรียมไว้แล้ว)

### 3. เปิด AWS Console จาก Lab (ไม่ใช่ login ปกติ)
คลิกปุ่ม **AWS** สีส้มด้านบน จะพาเข้า AWS Console โดยอัตโนมัติ (ไม่ต้อง login
ด้วยอีเมล/รหัสผ่านเอง) จากตรงนี้ทำตาม **ข้อ 3-5 ของส่วนที่ 1 ได้ตามปกติ**
(สร้าง Key Pair, Security Group, AMI ที่ลง GNS3) ต่างกันแค่ข้อ 2 (สร้าง IAM
user) ที่ **ข้ามไปเลย ไม่ต้องทำ** เพราะ Lab ให้ credentials มาแล้ว

### 4. ใช้ Role "LabRole" แทนการสร้าง IAM Role เอง
ถ้า instance ต้องเรียก AWS service อื่น (เช่น S3) ให้ใช้ role ชื่อ `LabRole`
ที่ Lab เตรียมไว้ให้ (ตั้งค่าไว้แล้วใน `.env.example` -> `INSTANCE_PROFILE_NAME`)
ห้ามพยายามสร้าง IAM Role ใหม่เอง เพราะ Learner Lab บล็อกสิทธิ์ตรงนี้ไว้

### 5. Region ต้องเป็น us-east-1
Learner Lab ส่วนใหญ่ล็อกให้ใช้ได้แค่ N. Virginia (`us-east-1`) เท่านั้น
ตรวจดูมุมขวาบนของ AWS Console ว่าเป็น region นี้อยู่ก่อนสร้าง Key Pair/SG/AMI

### 6. ระวังเรื่อง budget และเวลา
Lab แต่ละครั้งมี budget จำกัด (มักไม่กี่สิบ USD) และ session จะถูกตัดอัตโนมัติ
หลังจากไม่ได้ใช้งานสักพัก **ควร stop/terminate instance ทุกครั้งที่เลิกใช้งาน**
ไม่งั้นเงินใน lab จะหมดเร็วโดยไม่ได้ตั้งใจ

### ทุกครั้งที่ credentials หมดอายุ (เจอ error `ExpiredToken` หรือ `InvalidClientTokenId`)
กลับไปทำข้อ 1-2 ใหม่ (Start Lab -> ก็อป AWS Details -> แปะใส่ `.env`) แล้ว
restart `uvicorn` ใหม่ ไม่ต้องแก้โค้ดอะไรเพิ่ม

---

## ส่วนที่ 2: ติดตั้งและรัน API

```bash
cd gns3-ec2-api
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# แก้ .env ใส่ค่าที่ได้จากส่วนที่ 1 ให้ครบทุกช่อง

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

เปิดดู interactive docs (ทดสอบ endpoint ได้เลยจากหน้าเว็บ) ที่:
`http://localhost:8000/docs`

---

## ส่วนที่ 3: ตัวอย่างการเรียกใช้ API

**สร้าง instance ใหม่**
```bash
curl -X POST http://localhost:8000/instances \
  -H "Content-Type: application/json" \
  -d '{"student_id": "6410000", "instance_name": "gns3-6410000-vm1"}'
```

**ดู instance ทั้งหมดของนักศึกษาคนหนึ่ง**
```bash
curl "http://localhost:8000/instances?student_id=6410000"
```

**Start / Stop**
```bash
curl -X POST http://localhost:8000/instances/i-0123456789abcdef0/start
curl -X POST http://localhost:8000/instances/i-0123456789abcdef0/stop
```

**ลบ instance (terminate)**
```bash
curl -X DELETE http://localhost:8000/instances/i-0123456789abcdef0
```

---

## หมายเหตุด้านความปลอดภัย / ข้อควรระวังสำหรับส่งอาจารย์
- **ห้าม commit ไฟล์ `.env`** ขึ้น GitHub (มี `.gitignore` ตัวอย่างด้านล่าง) เพราะมี AWS
  secret key อยู่ข้างใน ถ้าหลุดจะโดนคนอื่นเอาไปใช้ยิง EC2 จนบิลบาน
- `max_concurrent_instances` ใน `.env` ช่วยกันไม่ให้ระบบสร้าง VM เกินจำนวนที่ควบคุมได้
- ทุก instance ที่สร้างผ่าน API จะถูกติด Tag `Project=gns3-cloud` เพื่อแยกจาก
  resource อื่นในบัญชี AWS เดียวกัน และ endpoint start/stop/terminate จะเช็ค tag
  นี้ก่อนเสมอ กัน error กดลบ instance อื่นที่ไม่เกี่ยวข้อง
- โปรเจคจริงควรเพิ่มระบบ authentication (เช่น JWT ของนักศึกษาที่ login ผ่านเว็บ)
  ก่อนอนุญาตให้เรียก endpoint พวกนี้ - เวอร์ชันนี้ยังไม่มี auth เพื่อให้ทดสอบง่ายก่อน

**.gitignore แนะนำ**
```
venv/
.env
__pycache__/
*.pem
```

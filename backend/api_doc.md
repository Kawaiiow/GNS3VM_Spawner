# NetLab Backend - API Documentation (`api_doc.md`)

สรุป API Endpoints ของ NetLab Backend พร้อมตัวอย่าง Request / Response JSON
ลองยิงแบบ Interactive ได้ที่ Swagger UI: `http://localhost:8000/docs`

---

## 📋 ตารางสรุป (Quick Reference)

| Method | Endpoint | สิทธิ์ | คำอธิบาย |
| :--- | :--- | :---: | :--- |
| `GET` | `/` , `/health` | Public | ตรวจสอบสถานะระบบ |
| `POST` | `/auth/login` | Public | เข้าสู่ระบบ |
| `POST` | `/auth/logout` | Public | ออกจากระบบ (ลบคุกกี้ `access_token`) |
| `GET` | `/auth/me` | User | ดูโปรไฟล์และ VM ของตัวเอง |
| `GET` | `/exercises` | Public | ดูรายการแบบฝึกหัด |
| `GET` | `/exercises/{id}` | Public | ดูรายละเอียดแบบฝึกหัด |
| `POST` | `/exercises` | Instructor | สร้างแบบฝึกหัด |
| `DELETE` | `/exercises/{id}` | เจ้าของ / Admin | ลบแบบฝึกหัด |
| `POST` | `/instances` | Student / Instructor | สร้าง GNS3 VM |
| `GET` | `/instances` | User | ดูรายการ VM |
| `POST` | `/instances/{id}/start` | เจ้าของ / Admin | เปิดเครื่อง |
| `POST` | `/instances/{id}/stop` | เจ้าของ / Admin | ปิดเครื่องชั่วคราว |
| `DELETE` | `/instances/{id}` | เจ้าของ / Admin | ลบ (Terminate) VM ถาวร |
| `POST` | `/admin/users` | Admin | สร้างผู้ใช้ |
| `GET` | `/admin/users` | Admin | ดูรายชื่อผู้ใช้ทั้งหมด |
| `PATCH` | `/admin/users/{id}` | Admin | แก้ไขผู้ใช้ / รีเซ็ตรหัสผ่าน |
| `DELETE` | `/admin/users/{id}` | Admin | ลบผู้ใช้ |
| `GET` | `/admin/dashboard` | Admin | ดูผู้ใช้ทุกคนพร้อม VM |

---

## 🔐 การยืนยันตัวตน

หลัง Login ส่ง Token ได้ 2 แบบ:
1. Header: `Authorization: Bearer <access_token>`
2. Cookie: `access_token` (HttpOnly ตั้งให้อัตโนมัติตอน Login)

Token เป็น JWT (HS256) อายุ 24 ชั่วโมง ส่ง Token ผิดหรือหมดอายุได้ `401`

**บทบาทและโควตา VM**
- `student`: Sandbox 1 เครื่อง + Exercise 1 เครื่อง
- `instructor`: ไม่จำกัด
- `admin`: สร้าง VM ไม่ได้

---

## ⚠️ รูปแบบ Error

```json
{ "detail": "ข้อความอธิบายข้อผิดพลาด" }
```

| Status | ความหมาย |
| :---: | :--- |
| `400` | Request ไม่ถูกต้อง / ผิดเงื่อนไข (เช่น มี VM ในช่องนั้นแล้ว) |
| `401` | ไม่ได้ล็อกอิน / Token ผิด / หมดอายุ |
| `403` | ไม่มีสิทธิ์ |
| `404` | ไม่พบข้อมูล |
| `409` | ข้อมูลซ้ำ / ลบไม่ได้ |
| `422` | Body ไม่ครบหรือรูปแบบผิด |
| `429` | VM ทั้งระบบถึงขีดจำกัด (`MAX_CONCURRENT_INSTANCES`) |

---

## 📦 Object ที่ใช้ซ้ำ

**User**
```json
{
  "user_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "username": "student01",
  "member_id": "6410001",
  "full_name": "Somchai Student",
  "role": "student",
  "active_instance_id": null,
  "active_exercise_instance_id": null,
  "created_at": "2026-09-20T14:00:00.000000+00:00",
  "updated_at": "2026-09-20T14:00:00.000000+00:00"
}
```
`role` = `student` | `instructor` | `admin` ส่วน `active_instance_id` / `active_exercise_instance_id` คือ Sandbox / Exercise VM ที่ถืออยู่ (`null` ถ้าไม่มี)

**Instance**
```json
{
  "instance_id": "i-0123456789abcdef0",
  "user_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "exercise_id": null,
  "name": "gns3-student01-sandbox",
  "state": "running",
  "instance_type": "t3.medium",
  "public_ip": "54.200.12.34",
  "private_ip": "172.31.10.5",
  "launch_time": "2026-09-27T14:10:00.000000+00:00",
  "created_at": "2026-09-27T14:10:00.000000+00:00",
  "terminated_at": null,
  "gns3_user": "gns3",
  "gns3_password": "k3Jx9QmZpA7vTn2R"
}
```
- `state` = `pending` | `running` | `stopping` | `stopped` | `shutting-down` | `terminated`
- `exercise_id` เป็น `null` = Sandbox, มีค่า = Exercise VM
- `public_ip` เป็น `null` เมื่อเครื่องยังไม่ `running` หรือถูก Stop
- `gns3_user` / `gns3_password` คือรหัสเข้า GNS3 (`http://<public_ip>:3080`) ส่งให้เจ้าของ VM เท่านั้น (Admin ได้ `null`)

**Exercise**
```json
{
  "exercise_id": "7b1e0c3a-92f4-4d51-8a1c-0f6d3b2a9e11",
  "instructor_id": "c1d2e3f4-0000-4a5b-9c8d-111122223333",
  "title": "Lab 1: Basic OSPF Routing",
  "description": "ตั้งค่า OSPF single-area บน Router 3 ตัว",
  "ami_id": "ami-0123456789abcdef0",
  "is_active": true,
  "status": "available",
  "created_at": "2026-09-27T10:00:00.000000+00:00"
}
```
`status` = `pending` (กำลังสร้าง Snapshot) | `available` (พร้อมใช้) | `failed`

---

## 🛠️ รายละเอียดแต่ละ Endpoint

### 1. System

#### `GET /health`
**Response `200`**
```json
{ "status": "ok", "service": "netlab-backend" }
```

---

### 2. Auth

#### `POST /auth/login`
เข้าสู่ระบบด้วย Username หรือ Member ID
**Request**
```json
{ "identifier": "student01", "password": "StudentPass123!" }
```
**Response `200`**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "user": { "...": "User object" }
}
```
**Error:** `401` ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง

#### `POST /auth/logout`
ออกจากระบบ ลบคุกกี้ `access_token` ฝั่ง Server (ไม่ต้องส่ง Body และไม่ต้องล็อกอิน เรียกซ้ำได้)
**Response `200`**
```json
{ "message": "Logged out successfully." }
```
> ⚠️ JWT เป็นแบบ Stateless Logout ลบได้แค่คุกกี้ ส่วน Token ที่ถูกเก็บไว้ที่อื่น (เช่น ที่ใช้ผ่าน `Authorization: Bearer`) ยังใช้ได้จนหมดอายุ ฝั่ง Client ต้องลบ Token ทิ้งเองด้วย

#### `GET /auth/me`
**Response `200`**: User object (`active_instance_id` และ `active_exercise_instance_id` เป็นค่าล่าสุด)

---

### 3. Exercises

#### `GET /exercises`
Query: `only_active` (ค่าเริ่มต้น `true`, ใส่ `false` เพื่อดูทั้งหมด)
**Response `200`**
```json
{
  "count": 1,
  "exercises": [ { "...": "Exercise object" } ]
}
```

#### `GET /exercises/{id}`
ถ้า `status` ยังเป็น `pending` ระบบเช็ค Snapshot บน AWS แล้วอัปเดตให้อัตโนมัติ
**Response `200`**: Exercise object
**Error:** `404`

#### `POST /exercises`
สิทธิ์: **Instructor เท่านั้น** (Admin / Student ได้ `403`)
**Request**
```json
{
  "title": "Lab 2: BGP Configuration",
  "description": "ตั้งค่า eBGP peering ระหว่าง 2 AS",
  "instance_id": "i-0123456789abcdef0",
  "ami_id": null
}
```
| ฟิลด์ | จำเป็น | คำอธิบาย |
| :--- | :---: | :--- |
| `title`, `description` | ✅ | ชื่อและโจทย์ |
| `instance_id` | ❌ | VM ที่จะทำ Snapshot (ไม่ส่ง = ใช้ VM ปัจจุบันของอาจารย์) |
| `ami_id` | ❌ | ใช้ AMI ที่มีอยู่แล้ว (ไม่ทำ Snapshot, สถานะ `available` ทันที) |

ถ้าไม่ส่ง `ami_id` ระบบสร้าง Snapshot จาก VM และตั้งสถานะ `pending`
**Response `201`**: Exercise object (`"status": "pending"`)
**Error:** `400` ไม่มี VM / มีหลาย VM แต่ไม่ระบุ `instance_id` | `403` ไม่ใช่ Instructor หรือ VM ไม่ใช่ของตัวเอง

#### `DELETE /exercises/{id}`
สิทธิ์: เจ้าของแบบฝึกหัด (Instructor) หรือ Admin ลบแล้วระบบ De-register AMI ให้
**Response `200`**
```json
{ "message": "Exercise '7b1e0c3a-...' deleted successfully." }
```
**Error:** `403` | `404`

---

### 4. Instances (VM)

#### `POST /instances`
สร้าง GNS3 VM ผูกกับผู้ใช้ที่ล็อกอิน (Admin สร้างไม่ได้ ได้ `403`)
**Request**
```json
{
  "instance_name": "gns3-lab1-student01",
  "exercise_id": "7b1e0c3a-92f4-4d51-8a1c-0f6d3b2a9e11",
  "instance_type": "t3.medium",
  "ami_id": null
}
```
| ฟิลด์ | จำเป็น | คำอธิบาย |
| :--- | :---: | :--- |
| `instance_name` | ✅ | ชื่อ VM |
| `exercise_id` | ❌ | ไม่ส่ง = Sandbox, ส่ง = Exercise VM (แบบฝึกหัดต้อง `available`) |
| `instance_type` | ❌ | ไม่ส่งใช้ค่า Default จาก `.env` |
| `ami_id` | ❌ | ไม่ส่งใช้ AMI ของ exercise หรือ Default |

**Response `201`**: Instance object (`state` เป็น `pending`, `public_ip` เป็น `null` ให้เรียก `GET /instances` ซ้ำจนเป็น `running`)
**Error:** `400` มี VM ในช่องนั้นแล้ว / แบบฝึกหัดไม่พร้อม | `403` Admin | `429` VM ทั้งระบบเต็ม

#### `GET /instances`
Sync สถานะและ IP จาก EC2 ทุกครั้งที่เรียก (ไม่รวม VM ที่ `terminated`)
- Student / Instructor: เห็นเฉพาะ VM ของตัวเอง (พร้อม `gns3_user`, `gns3_password`)
- Admin: เห็น VM ทุกคน (`gns3_user`, `gns3_password` เป็น `null`)

**Response `200`**
```json
{
  "count": 1,
  "instances": [ { "...": "Instance object" } ]
}
```

#### `POST /instances/{id}/start`
เปิดเครื่องที่ Stop ไว้ รอจนเครื่อง `running` (สูงสุดประมาณ 2 นาที) เพื่อให้ได้ Public IP ใหม่
**Response `200`**
```json
{
  "instance_id": "i-0123456789abcdef0",
  "state": "running",
  "message": "instance เริ่มทำงานแล้ว",
  "public_ip": "3.91.45.120"
}
```
ถ้ายังไม่พร้อมเมื่อหมดเวลา จะได้ `"state": "pending"` และ `"public_ip": null`

#### `POST /instances/{id}/stop`
ปิดเครื่องชั่วคราว (ยังนับเป็นโควตา, Public IP จะหาย)
**Response `200`**
```json
{
  "instance_id": "i-0123456789abcdef0",
  "state": "stopping",
  "message": "instance กำลังปิดเครื่อง",
  "public_ip": null
}
```

#### `DELETE /instances/{id}`
Terminate ถาวรและคืนโควตาให้เจ้าของ
**Response `200`**
```json
{
  "instance_id": "i-0123456789abcdef0",
  "state": "shutting-down",
  "message": "instance กำลังถูกลบ (terminate) และปล่อยโควตา VM เรียบร้อยแล้ว",
  "public_ip": null
}
```

**Error ของ start / stop / delete:** `403` ไม่ใช่ VM ของตัวเอง | `404` ไม่พบ instance

---

### 5. Admin (เฉพาะ Admin)

#### `POST /admin/users`
**Request**
```json
{
  "username": "student02",
  "member_id": "6410002",
  "password": "SecurePass123!",
  "full_name": "Somying Student",
  "role": "student"
}
```
| ฟิลด์ | จำเป็น | คำอธิบาย |
| :--- | :---: | :--- |
| `username`, `member_id` | ✅ | ต้องไม่ซ้ำ |
| `password` | ✅ | อย่างน้อย 6 ตัวอักษร |
| `full_name` | ❌ | ชื่อ-นามสกุล |
| `role` | ❌ | `student` (ค่าเริ่มต้น) / `instructor` / `admin` |

**Response `201`**: User object
**Error:** `400` Username หรือ Member ID ซ้ำ | `422`

#### `GET /admin/users`
**Response `200`**: อาร์เรย์ของ User object
```json
[ { "...": "User object" }, { "...": "User object" } ]
```

#### `PATCH /admin/users/{id}`
ส่งเฉพาะฟิลด์ที่ต้องการแก้ (ใส่ `password` เพื่อรีเซ็ตรหัสผ่าน)
**Request**
```json
{ "role": "instructor", "password": "NewPass456!" }
```
ฟิลด์ที่ใช้ได้: `username`, `member_id`, `full_name`, `role`, `password` (ไม่จำเป็นทั้งหมด)
**Response `200`**: User object หลังแก้ไข
**Error:** `400` ไม่มีข้อมูลแก้ไข / ลดสิทธิ์ admin ของตัวเอง | `404` | `409` Username หรือ Member ID ซ้ำ

#### `DELETE /admin/users/{id}`
**Response `200`**
```json
{ "message": "User 'student02' deleted successfully." }
```
**Error:** `400` ลบบัญชีตัวเอง | `404` | `409` ผู้ใช้ยังมี VM ใช้งานอยู่ (ต้อง Terminate ก่อน)

#### `GET /admin/dashboard`
ผู้ใช้ทุกคนพร้อม VM ที่ยังไม่ถูกลบ (sync กับ EC2 ก่อนแสดง)
**Response `200`**
```json
[
  {
    "user_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "username": "student01",
    "member_id": "6410001",
    "full_name": "Somchai Student",
    "role": "student",
    "instances": [
      {
        "instance_id": "i-0123456789abcdef0",
        "name": "gns3-student01-sandbox",
        "kind": "sandbox",
        "exercise_id": null,
        "state": "running",
        "public_ip": "54.200.12.34"
      }
    ]
  }
]
```
`kind` = `sandbox` | `exercise`
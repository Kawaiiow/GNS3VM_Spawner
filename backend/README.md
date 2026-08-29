# EC2 Provisioning API (FastAPI + Boto3)

A REST API wrapper built with **FastAPI** and **Boto3** to automate the provisioning, lifecycle management, and nested virtualization configuration of Amazon EC2 instances (such as GNS3 VM lab nodes).

---

## 1. Prerequisites

Ensure you have the following installed on your machine:

* **Python 3.10+**
* **AWS CLI (v2)** configured with appropriate IAM permissions


* **Git**

---

## 2. Local Setup & Installation

### Step 1: Clone the Repository

```bash
git clone <repository-url>
cd <repository-folder>/backend

```

### Step 2: Create and Activate a Virtual Environment

* **Linux / macOS:**
```bash
python3 -m venv .venv
source .venv/bin/activate

```


* **Windows (PowerShell):**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1

```



### Step 3: Install Dependencies

```bash
pip install -r requirements.txt

```

*(If you are initializing dependencies from scratch, use:)*

```text
boto3==1.43.83
fastapi==0.141.1
pydantic==2.13.5
pydantic-settings==2.15.0
python-dotenv==1.2.3
uvicorn==0.52.4

```

---

## 3. Environment & AWS Configuration

### Configure Local AWS Credentials

If you haven't configured your AWS credentials locally, run:

```bash
aws configure

```

You will be prompted for:

* `AWS Access Key ID`

* `AWS Secret Access Key`

* `Default region name` (e.g., `us-east-1`)


* `Default output format` (`json`)



### Create `.env` Configuration File

Create a `.env` file in the root directory:

```env
AWS_REGION=us-east-1
DEFAULT_AMI_ID=ami-xxxxxxxxxxxxxxxxx
DEFAULT_INSTANCE_TYPE=c7i-flex.xlarge
DEFAULT_KEY_NAME=your-key-name
DEFAULT_SECURITY_GROUP_ID=sg-xxxxxxxxxxxxxxxxx
DEFAULT_SUBNET_ID=subnet-xxxxxxxxxxxxxxxxx

```

> **Note:** For running nested hypervisors (e.g., GNS3/QEMU/KVM nodes), instances require Nitro-based Intel architectures (such as `c7i-flex.xlarge`) with `NestedVirtualization` enabled in the launch parameters.
> 
> 

---

## 4. Running the Application

Start the local ASGI development server with auto-reload:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

```

---

## 5. API Documentation & Endpoints

Once the application is running, access the interactive API docs:

* **Swagger UI:** [http://127.0.0.1:8000/docs](https://www.google.com/search?q=http://127.0.0.1:8000/docs)
* **ReDoc:** [http://127.0.0.1:8000/redoc](https://www.google.com/search?q=http://127.0.0.1:8000/redoc)

### Key Endpoints

| Method | Endpoint | Description |
| --- | --- | --- |
| `POST` | `/api/v1/instances` | Launches an EC2 instance (supports nested virtualization flags).

 |
| `GET` | `/api/v1/instances` | Lists running instances filtered by tag/status. |
| `GET` | `/api/v1/instances/{id}` | Retrieves status and IP metadata for a specific instance. |
| `DELETE` | `/api/v1/instances/{id}` | Terminates an instance. |

---

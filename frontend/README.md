# Frontend

## Getting Started

### 1. Go to the frontend directory

```bash
cd frontend
```

### 2. Create a virtual environment

```bash
python -m venv .venv
```

Activate it:

```bash
# macOS / Linux
source .venv/bin/activate

# Windows
.venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Go to the app directory

```bash
cd app
```

### 5. Run the frontend

```bash
uvicorn main:app --host 0.0.0.0 --port 8080
```

### 6. Open in browser

```
http://localhost:8080
```

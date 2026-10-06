from fastapi import FastAPI, Request, Form, status
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from router import admin
import uvicorn, httpx

BACKEND_URL = "http://localhost:8000"

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
template = Jinja2Templates(directory="template")

@app.get("/")
def render_home(request: Request):
    return template.TemplateResponse(request=request, name="home.html")

@app.get("/signin")
def render_signin(request: Request):
    return template.TemplateResponse(request=request, name="signin.html")

@app.post("/signin")
def handle_signin(identifier: str = Form(...), password: str = Form(...)):
    try:
        with httpx.Client as client:
            response = client.post(f"{BACKEND_URL}/auth/login", json={"identifier": identifier, "password": password},)
    except httpx.RequestError:
        return "503 Service Unavailable"
    if response.status_code == 401:
        return "401 Unauthorized"
    data = response.json()
    role = data["user"]["role"]
    if role == "admin":
        redirect_to = "/admin/dashboard"
    elif role == "Instructor":
        redirect_to = "/Instructor/dashboard"
    else:
        redirect_to = "/dashboard"
    redirect = RedirectResponse(url=redirect_to)
    redirect.set_cookie(key="access_token", value=data["access_token"], httponly=True, max_age=1440 * 60, samesite="lax")
    print(response.status_code)
    return redirect

app.include_router(admin.router, prefix="/admin")

@app.api_route("/{path:path}", methods=["GET", "POST"])
def catch_all(request: Request):
    return template.TemplateResponse(request=request, name="404.html")

if __name__ == "__main__":
    uvicorn.run("main:app", host="localhost", port=8080, reload=True)

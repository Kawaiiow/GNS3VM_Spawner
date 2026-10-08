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
    if request.cookies.get("access_token"):
        return template.TemplateResponse(request=request, name="404.html", status_code=status.HTTP_404_NOT_FOUND)
    return template.TemplateResponse(request=request, name="home.html")

@app.get("/signin")
def render_signin(request: Request):
    if request.cookies.get("access_token"):
        return template.TemplateResponse(request=request, name="404.html", status_code=status.HTTP_404_NOT_FOUND)
    return template.TemplateResponse(request=request, name="signin.html")

@app.post("/signin")
def handle_signin(request: Request, identifier: str = Form(...), password: str = Form(...)):
    if request.cookies.get("access_token"):
        return template.TemplateResponse(request=request, name="404.html", status_code=status.HTTP_404_NOT_FOUND)
    try:
        response = httpx.post(f"{BACKEND_URL}/auth/login", json={"identifier": identifier, "password": password}, timeout=10.0)
    except:
        return template.TemplateResponse(request=request, name="503.html", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    if response.status_code in (401, 403):
        return "ไม่พบบัญชีนี้"
    data = response.json()
    target = f"/{data['user']['role']}/dashboard" if data["user"]["role"] in ("admin", "instructor") else "/dashboard"
    redirect = RedirectResponse(url=target, status_code=status.HTTP_303_SEE_OTHER)
    redirect.set_cookie(key="access_token", value=data["access_token"], httponly=True, max_age=1440 * 60, samesite="lax")
    redirect.set_cookie(key="username", value=data["user"]["username"], httponly=True, max_age=1440 * 60, samesite="lax")
    return redirect

@app.post("/signout")
def handle_signout(request: Request):
    if not request.cookies.get("access_token"):
        return template.TemplateResponse(request=request, name="404.html", status_code=status.HTTP_404_NOT_FOUND)
    try:
        httpx.post(f"{BACKEND_URL}/auth/logout", cookies={"access_token": request.cookies.get("access_token")}, timeout=10.0)
    except:
        return template.TemplateResponse(request=request, name="503.html", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    redirect = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    redirect.delete_cookie("access_token")
    redirect.delete_cookie("username")
    return redirect

app.include_router(admin.router, prefix="/admin")

@app.api_route("/{path:path}", methods=["GET", "POST"])
def catch_all(request: Request):
    return template.TemplateResponse(request=request, name="404.html", status_code=status.HTTP_404_NOT_FOUND)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)

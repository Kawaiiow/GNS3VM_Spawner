from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
template = Jinja2Templates(directory="template")

@app.get("/")
def render_home(request: Request):
    return template.TemplateResponse(
        request=request,
        name="home.html"
    )

@app.get("/signin")
def render_signin(request: Request):
    return template.TemplateResponse(
        request=request,
        name="signin.html"
    )

@app.get("/admin/dashboard")
def render_admin_dashboard(request: Request):
    return template.TemplateResponse(
        request=request,
        name="admin/dashboard.html"
    )

@app.get("/admin/create")
def render_admin_create(request: Request):
    return template.TemplateResponse(
        request=request,
        name="admin/create.html"
    )

@app.get("/admin/update")
def render_admin_edit(request: Request):
    return template.TemplateResponse(
        request=request,
        name="admin/update.html"
    )

@app.get("/{path:path}")
def catch_all(request: Request):
    return template.TemplateResponse(
        request=request,
        name="404.html"
    )

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")

@app.get("/")
def redirect_to_home():
    return RedirectResponse(url="/home")

@app.get("/home")
def render_home(request: Request):
    return templates.TemplateResponse(
        request=request, 
        name="home.html"
    )
    
@app.get("/signin")
def render_signin(request: Request):
    return templates.TemplateResponse(
        request=request, 
        name="signin.html"
    )

@app.get("/{full_path:path}")
def catch_all(request: Request):
    return templates.TemplateResponse(
        request=request, 
        name="notfound.html"
    )

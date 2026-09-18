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

@app.get("/{path:path}")
def catch_all(request: Request):
    return template.TemplateResponse(
        request=request, 
        name="notfound.html"
    )

# start frontend
# uvicorn main:app --reload
# localhost:8000

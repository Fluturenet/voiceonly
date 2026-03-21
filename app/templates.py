# app/templates.py
from fastapi.templating import Jinja2Templates

# Create templates instance that can be imported anywhere
templates = Jinja2Templates(directory="app/templates")

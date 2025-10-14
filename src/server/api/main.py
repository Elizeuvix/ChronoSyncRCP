import sys
import os
# Ensure parent (src/server) is importable so 'ws' and 'common' resolve
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from fastapi import FastAPI
import auth
from ws.ws_server import router as ws_router
from apikeys import router as apikeys_router
from common.db import init_db

app = FastAPI()

@app.get("/")
def read_root():
    return {"message": "ChronoSyncRCP API online"}

app.add_api_route("/register", auth.register_player, methods=["POST"])
app.add_api_route("/login", auth.login_player, methods=["POST"])
app.include_router(ws_router)
app.include_router(apikeys_router)

@app.on_event("startup")
def _startup():
    init_db()

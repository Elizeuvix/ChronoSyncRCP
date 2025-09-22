import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from fastapi import FastAPI
import auth
from ws.ws_server import router as ws_router

app = FastAPI()

@app.get("/")
def read_root():
    return {"message": "ChronoSyncRCP API online"}

app.add_api_route("/register", auth.register_player, methods=["POST"])
app.add_api_route("/login", auth.login_player, methods=["POST"])
app.include_router(ws_router)

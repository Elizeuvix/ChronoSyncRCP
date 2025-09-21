
from fastapi import FastAPI
from src.server.api.auth import register_player, login_player
from fastapi import APIRouter
from src.server.ws.ws_server import router as ws_router

app = FastAPI()

router = APIRouter()

@app.get("/")
def read_root():
    return {"message": "ChronoSyncRCP API online"}

app.add_api_route("/register", register_player, methods=["POST"])
app.add_api_route("/login", login_player, methods=["POST"])
app.include_router(ws_router)

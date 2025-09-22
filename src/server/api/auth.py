from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

class PlayerRegister(BaseModel):
    username: str
    password: str

class PlayerLogin(BaseModel):
    username: str
    password: str

fake_db = {}

@app.post("/register")
def register_player(data: PlayerRegister):
    if data.username in fake_db:
        raise HTTPException(status_code=400, detail="Username already exists")
    fake_db[data.username] = data.password
    return {"message": "Player registered successfully"}

@app.post("/login")
def login_player(data: PlayerLogin):
    if fake_db.get(data.username) != data.password:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"message": "Login successful"}

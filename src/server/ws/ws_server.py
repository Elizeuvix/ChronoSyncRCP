import asyncio
from fastapi import WebSocket, WebSocketDisconnect
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


connected_players = set()
import datetime
lobbies = {}  # lobby_name: [player_id]
chat_history = {}  # lobby_name: [ {"player_id": str, "message": str, "timestamp": str} ]
websockets = set()

# Modelo de payload para sincronização
class StatePayload(BaseModel):
    player_id: str
    position: dict  # {"x": float, "y": float, "z": float}
    rotation: dict  # {"x": float, "y": float, "z": float}
    velocity: dict  # {"x": float, "y": float, "z": float}
    animation: str
    sound: str
    objects: list   # [{"id": str, "state": dict}]


@router.websocket("/ws/game")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    player_id = None
    websockets.add(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            event = data.get("event")
            if event == "player_connected":
                player_id = data.get("player_id")
                connected_players.add(player_id)
                await websocket.send_json({"event": "player_connected", "player_id": player_id})
                await broadcast_lobby_list()
            elif event == "player_disconnected":
                if player_id:
                    connected_players.discard(player_id)
                    remove_player_from_lobbies(player_id)
                await websocket.send_json({"event": "player_disconnected", "player_id": player_id})
                await broadcast_lobby_list()
            elif event == "state_update":
                try:
                    state = StatePayload(**data.get("state"))
                    await websocket.send_json({"event": "state_update", "state": state.dict()})
                except Exception as e:
                    await websocket.send_json({"event": "error", "detail": str(e)})
            elif event == "score_update":
                await websocket.send_json({"event": "score_update", "score": data.get("score")})
            elif event == "match_start":
                lobby_name = data.get("lobby")
                if lobby_name:
                    lobbies.setdefault(lobby_name, []).append(player_id)
                    chat_history.setdefault(lobby_name, [])
                    await websocket.send_json({"event": "match_start", "lobby": lobby_name})
                    await broadcast_lobby_list()
            elif event == "join_lobby":
                lobby_name = data.get("lobby")
                if lobby_name and lobby_name in lobbies:
                    lobbies[lobby_name].append(player_id)
                    await websocket.send_json({"event": "join_lobby", "lobby": lobby_name})
                    await broadcast_lobby_list()
                    # Envia histórico do chat ao entrar
                    await websocket.send_json({"event": "chat_history", "lobby": lobby_name, "messages": chat_history.get(lobby_name, [])})
            elif event == "chat_message":
                lobby_name = data.get("lobby")
                message = data.get("message")
                if lobby_name and lobby_name in lobbies and message:
                    msg_obj = {"player_id": player_id, "message": message, "timestamp": datetime.datetime.utcnow().isoformat()}
                    chat_history.setdefault(lobby_name, []).append(msg_obj)
                    await broadcast_chat_message(lobby_name, msg_obj)
            elif event == "match_end":
                await websocket.send_json({"event": "match_end"})
    except WebSocketDisconnect:
        if player_id:
            connected_players.discard(player_id)
            remove_player_from_lobbies(player_id)
        websockets.discard(websocket)
        await broadcast_lobby_list()

def remove_player_from_lobbies(player_id):
    to_remove = []
    for lobby, players in lobbies.items():
        if player_id in players:
            players.remove(player_id)
        if not players:
            to_remove.append(lobby)
    for lobby in to_remove:
        del lobbies[lobby]

async def broadcast_lobby_list():
    lobby_names = list(lobbies.keys())
    payload = {"eventName": "lobby_list", "lobbies": lobby_names}
    for ws in list(websockets):
        try:
            await ws.send_json(payload)
        except:
            pass
async def broadcast_chat_message(lobby_name, msg_obj):
    payload = {"event": "chat_message", "lobby": lobby_name, "message": msg_obj}
    for ws in list(websockets):
        try:
            await ws.send_json(payload)
        except:
            pass

async def broadcast_lobby_list():
    lobby_names = list(lobbies.keys())
    payload = {"eventName": "lobby_list", "lobbies": lobby_names}
    for ws in list(websockets):
        try:
            await ws.send_json(payload)
        except:
            pass

# Exemplo de integração Unity (C#):
#
# using NativeWebSocket;
# ...
# WebSocket websocket = new WebSocket("ws://localhost:8000/ws/game");
# await websocket.Connect();
# await websocket.SendText(JsonUtility.ToJson(new {
#     event = "state_update",
#     state = new {
#         player_id = "player1",
#         position = new { x = 1.0, y = 2.0, z = 3.0 },
#         rotation = new { x = 0.0, y = 90.0, z = 0.0 },
#         velocity = new { x = 0.0, y = 0.0, z = 0.0 },
#         animation = "run",
#         sound = "footstep",
#         objects = new [] { new { id = "obj1", state = new { active = true } } }
#     }
# }));

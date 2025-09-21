import asyncio
from fastapi import WebSocket, WebSocketDisconnect
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

connected_players = set()

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
    try:
        while True:
            data = await websocket.receive_json()
            event = data.get("event")
            if event == "player_connected":
                player_id = data.get("player_id")
                connected_players.add(player_id)
                await websocket.send_json({"event": "player_connected", "player_id": player_id})
            elif event == "player_disconnected":
                if player_id:
                    connected_players.discard(player_id)
                await websocket.send_json({"event": "player_disconnected", "player_id": player_id})
            elif event == "state_update":
                # Validação do payload
                try:
                    state = StatePayload(**data.get("state"))
                    # Aqui pode-se propagar o estado para outros jogadores
                    await websocket.send_json({"event": "state_update", "state": state.dict()})
                except Exception as e:
                    await websocket.send_json({"event": "error", "detail": str(e)})
            elif event == "score_update":
                await websocket.send_json({"event": "score_update", "score": data.get("score")})
            elif event == "match_start":
                await websocket.send_json({"event": "match_start"})
            elif event == "match_end":
                await websocket.send_json({"event": "match_end"})
    except WebSocketDisconnect:
        if player_id:
            connected_players.discard(player_id)

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

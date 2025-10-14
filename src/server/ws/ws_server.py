import asyncio
import uuid
import os
from fastapi import WebSocket, WebSocketDisconnect
from fastapi import APIRouter
from pydantic import BaseModel
import datetime
from common.db import SessionLocal
from common.models import ApiKey

router = APIRouter()
API_KEY = os.environ.get("API_KEY", "CHRONOSYNC_DEV_KEY")
DEFAULT_MAX_PLAYERS = int(os.environ.get("MAX_PLAYERS_PER_LOBBY", "100"))
DEFAULT_MAX_PLAYERS = max(2, min(500, DEFAULT_MAX_PLAYERS))


connected_players = set()
lobbies = {}  # lobby_name: [player_id]
lobby_caps = {}  # lobby_name: max_players
lobby_owners = {}  # lobby_name: owner player_id
chat_history = {}  # lobby_name: [ {"player_id": str, "message": str, "timestamp": str} ]
websockets = set()
# Map players to their active websockets
player_sockets = {}
player_display_names = {}
player_caps = {}  # player_id -> max_players allowed by API key

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
    # Require API key in query string (?key=...)
    key = websocket.query_params.get("key")
    # Validate against DB first, fallback to env var
    valid = False
    max_players_cap = DEFAULT_MAX_PLAYERS
    if key:
        db = SessionLocal()
        try:
            ak = db.query(ApiKey).filter(ApiKey.key == key).first()
            if ak and not ak.is_revoked and (not ak.expires_at or ak.expires_at >= datetime.datetime.utcnow()) and ak.owner and ak.owner.is_active:
                valid = True
                # Clamp cap to [2,500]
                try:
                    max_players_cap = max(2, min(500, int(ak.max_players or DEFAULT_MAX_PLAYERS)))
                except Exception:
                    max_players_cap = DEFAULT_MAX_PLAYERS
        finally:
            db.close()
    if not valid and (not key or key != API_KEY):
        await websocket.close()
        return
    await websocket.accept()
    # Generate a unique server-side player id for this connection
    player_id = f"p-{uuid.uuid4().hex[:8]}"
    websockets.add(websocket)
    try:
        # Register this socket under the new player id
        connected_players.add(player_id)
        player_sockets.setdefault(player_id, set()).add(websocket)
        player_caps[player_id] = max_players_cap
        # Inform client of assigned id
        await websocket.send_json({"event": "player_connected", "player_id": player_id})
        await broadcast_lobby_list()
        while True:
            data = await websocket.receive_json()
            event = data.get("event")
            if event == "player_connected":
                # Legacy no-op: server assigns id; ignore client-provided id
                await websocket.send_json({"event": "player_connected", "player_id": player_id})
                await broadcast_lobby_list()
            elif event == "set_display_name":
                display_name = data.get("display_name")
                if isinstance(display_name, str) and display_name.strip():
                    player_display_names[player_id] = display_name.strip()
                    # Optionally, refresh members for lobbies this player is in
                    for lobby_name, members in list(lobbies.items()):
                        if player_id in members:
                            await send_lobby_members(lobby_name)
            elif event == "player_disconnected":
                if player_id:
                    connected_players.discard(player_id)
                    remove_player_from_lobbies(player_id)
                await websocket.send_json({"event": "player_disconnected", "player_id": player_id})
                await broadcast_lobby_list()
            elif event == "state_update":
                try:
                    # Accept reduced state from client and fill required fields
                    state_in = data.get("state") or {}
                    if not isinstance(state_in, dict):
                        state_in = {}
                    # Ensure the state carries the authoritative player id
                    state_in.setdefault("player_id", player_id)
                    # Fill optional fields with safe defaults
                    state_in.setdefault("animation", "")
                    state_in.setdefault("sound", "")
                    state_in.setdefault("objects", [])
                    # Prepare transform block: prefer client-provided 'transform' (may contain quaternion w)
                    transform_in = data.get("transform") or {}
                    if not isinstance(transform_in, dict):
                        transform_in = {}
                    # Validate/normalize state (may drop 'w' in rotation but kept in 'transform')
                    state = StatePayload(**state_in)
                    # Ensure field order: put 'transform' before 'state' to help naive parsers
                    payload = {"event": "state_update", "player_id": player_id, "entity_id": player_id, "transform": transform_in, "state": state.dict()}
                    # Broadcast to all members of lobbies this player is in (including sender for echo)
                    for lobby_name, members in list(lobbies.items()):
                        if player_id in members:
                            await broadcast_to_lobby(lobby_name, payload)
                except Exception as e:
                    await websocket.send_json({"event": "error", "detail": str(e)})
            elif event == "score_update":
                await websocket.send_json({"event": "score_update", "score": data.get("score")})
            elif event == "match_start":
                lobby_name = data.get("lobby")
                # Requested cap from client
                max_players_req = int(str(data.get("max_players") or DEFAULT_MAX_PLAYERS))
                max_players_req = max(2, min(500, max_players_req))
                # Enforce per-player cap from API key
                max_players = min(max_players_req, player_caps.get(player_id, DEFAULT_MAX_PLAYERS))
                if lobby_name:
                    current = lobbies.setdefault(lobby_name, [])
                    if player_id not in current:
                        current.append(player_id)
                    chat_history.setdefault(lobby_name, [])
                    # Set cap only when creating or if not set yet
                    if lobby_name not in lobby_caps:
                        lobby_caps[lobby_name] = max_players
                    # Set owner when creating the lobby if not present
                    if lobby_name not in lobby_owners:
                        lobby_owners[lobby_name] = player_id
                    await websocket.send_json({"event": "match_start", "lobby": lobby_name, "max_players": max_players, "owner_id": lobby_owners.get(lobby_name)})
                    await broadcast_lobby_list()
                    await send_lobby_members(lobby_name)
            elif event == "request_lobby_list":
                # Respond only to the requester with the current lobby list
                await websocket.send_json({"event": "lobby_list", "lobbies": build_lobby_list_payload()})
            elif event == "request_lobby_members":
                lobby_name = data.get("lobby")
                member_ids = list(lobbies.get(lobby_name, [])) if lobby_name else []
                members = [{"player_id": pid, "display_name": player_display_names.get(pid, pid)} for pid in member_ids]
                await websocket.send_json({"event": "lobby_members", "lobby": lobby_name, "members": members, "owner_id": lobby_owners.get(lobby_name), "max_players": lobby_caps.get(lobby_name, DEFAULT_MAX_PLAYERS)})
            elif event == "join_lobby":
                lobby_name = data.get("lobby")
                # Determine max players for this lobby from stored caps or default
                max_players = lobby_caps.get(lobby_name, DEFAULT_MAX_PLAYERS)
                if lobby_name and lobby_name in lobbies:
                    if len(lobbies[lobby_name]) >= max_players:
                        await websocket.send_json({"event": "error", "detail": f"Lobby full (max {max_players})"})
                    else:
                        if player_id not in lobbies[lobby_name]:
                            lobbies[lobby_name].append(player_id)
                        # Ensure owner mapping exists
                        if lobby_name not in lobby_owners and lobbies[lobby_name]:
                            lobby_owners[lobby_name] = lobbies[lobby_name][0]
                        await websocket.send_json({"event": "join_lobby", "lobby": lobby_name})
                        await broadcast_lobby_list()
                        # Notify members of this lobby that a player joined
                        await broadcast_to_lobby(lobby_name, {"event": "player_joined_lobby", "lobby": lobby_name, "player_id": player_id, "player_name": player_display_names.get(player_id, player_id)})
                        await send_lobby_members(lobby_name)
                        # Envia histórico do chat ao entrar
                        await websocket.send_json({"event": "chat_history", "lobby": lobby_name, "messages": chat_history.get(lobby_name, [])})
            elif event == "leave_lobby":
                lobby_name = data.get("lobby")
                if lobby_name and lobby_name in lobbies:
                    await remove_player_from_lobby(lobby_name, player_id, notify_target=False)
            elif event == "remove_from_lobby":
                lobby_name = data.get("lobby")
                target_pid = data.get("player_id")
                if lobby_name and lobby_name in lobbies and target_pid:
                    # Permission: only owner can remove others; anyone can remove themselves
                    is_host = (lobby_owners.get(lobby_name) == player_id)
                    if target_pid == player_id or is_host:
                        await remove_player_from_lobby(lobby_name, target_pid, notify_target=True, reason="kicked_by_host" if target_pid != player_id else "left")
                    else:
                        await websocket.send_json({"event": "error", "detail": "Only host can remove other players."})
            elif event == "start_match":
                # Host (ou qualquer membro) solicita iniciar a partida de um lobby já existente
                lobby_name = data.get("lobby")
                if lobby_name and lobby_name in lobbies:
                    members = lobbies.get(lobby_name, [])
                    if len(members) >= 2:
                        payload = {"event": "game_start", "lobby": lobby_name}
                        scene = data.get("scene")
                        if isinstance(scene, str) and scene.strip():
                            payload["scene"] = scene.strip()
                        await broadcast_to_lobby(lobby_name, payload)
            elif event == "lobby_cancel":
                lobby_name = data.get("lobby")
                if lobby_name and lobby_name in lobbies:
                    # Only owner can cancel the lobby
                    if lobby_owners.get(lobby_name) != player_id:
                        await websocket.send_json({"event": "error", "detail": "Only host can cancel the lobby."})
                        continue
                    members = list(lobbies.get(lobby_name, []))
                    # Notify members that lobby is closing
                    await broadcast_to_list_of_players(members, {"event": "lobby_closed", "lobby": lobby_name})
                    # Remove lobby
                    if lobby_name in lobbies:
                        del lobbies[lobby_name]
                    if lobby_name in lobby_caps:
                        del lobby_caps[lobby_name]
                    if lobby_name in lobby_owners:
                        del lobby_owners[lobby_name]
                    await broadcast_lobby_list()
            elif event == "chat_message":
                lobby_name = data.get("lobby")
                message = data.get("message")
                if lobby_name and lobby_name in lobbies and message:
                    msg_obj = {"player_id": player_id, "name": player_display_names.get(player_id, player_id), "message": message, "timestamp": datetime.datetime.utcnow().isoformat()}
                    chat_history.setdefault(lobby_name, []).append(msg_obj)
                    await broadcast_chat_message(lobby_name, msg_obj)
            elif event == "chat_message_global":
                message = data.get("message")
                if message:
                    msg_obj = {"player_id": player_id, "name": player_display_names.get(player_id, player_id), "message": message, "timestamp": datetime.datetime.utcnow().isoformat()}
                    await broadcast_to_all({"event": "chat_message_global", "message": msg_obj})
            elif event == "custom_event":
                # Photon-like RaiseEvent support
                code = data.get("code")
                content = data.get("content")
                entity_id = data.get("entity_id") or player_id
                payload = {"event": "custom_event", "code": code, "content": content, "entity_id": entity_id, "from": player_id, "from_name": player_display_names.get(player_id, player_id)}
                # Broadcast to all lobbies this player is currently in
                for lobby_name, members in list(lobbies.items()):
                    if player_id in members:
                        await broadcast_to_lobby(lobby_name, payload)
            elif event == "private_message":
                to_player = data.get("to")
                message = data.get("message")
                if to_player and message:
                    msg_obj = {"player_id": player_id, "name": player_display_names.get(player_id, player_id), "message": message, "timestamp": datetime.datetime.utcnow().isoformat()}
                    payload = {"event": "private_message", "from": player_id, "from_name": player_display_names.get(player_id, player_id), "to": to_player, "message": msg_obj}
                    # send to recipient
                    await broadcast_to_list_of_players([to_player], payload)
                    # echo to sender (so they also see it)
                    await broadcast_to_list_of_players([player_id], payload)
            elif event == "match_end":
                await websocket.send_json({"event": "match_end"})
    except WebSocketDisconnect:
        if player_id:
            connected_players.discard(player_id)
            remove_player_from_lobbies(player_id)
        websockets.discard(websocket)
        # Remove from player_sockets mapping
        if player_id:
            sockets = player_sockets.get(player_id, set())
            if websocket in sockets:
                sockets.discard(websocket)
                if not sockets:
                    player_sockets.pop(player_id, None)
            # Clean up cap map
            player_caps.pop(player_id, None)
        await broadcast_lobby_list()

def remove_player_from_lobbies(player_id):
    to_remove = []
    for lobby, players in lobbies.items():
        if player_id in players:
            players.remove(player_id)
            # Inform remaining members
            import asyncio as _asyncio
            _asyncio.create_task(broadcast_to_lobby(lobby, {"event": "player_left_lobby", "lobby": lobby, "player_id": player_id}))
            _asyncio.create_task(send_lobby_members(lobby))
        if not players:
            to_remove.append(lobby)
    for lobby in to_remove:
        del lobbies[lobby]

async def broadcast_lobby_list():
    payload = {"event": "lobby_list", "lobbies": build_lobby_list_payload()}
    for ws in list(websockets):
        try:
            await ws.send_json(payload)
        except:
            pass

async def remove_player_from_lobby(lobby_name: str, pid: str, notify_target: bool = True, reason: str | None = None):
    if not lobby_name or lobby_name not in lobbies:
        return
    players = lobbies.get(lobby_name, [])
    if pid in players:
        players.remove(pid)
        # Inform lobby
        await broadcast_to_lobby(lobby_name, {"event": "player_left_lobby", "lobby": lobby_name, "player_id": pid})
        await send_lobby_members(lobby_name)
        # Inform target (optional)
        if notify_target:
            payload = {"event": "kicked_from_lobby", "lobby": lobby_name}
            if reason:
                payload["reason"] = reason
            await broadcast_to_list_of_players([pid], payload)
        # Remove empty lobby
        if not players:
            if lobby_name in lobbies:
                del lobbies[lobby_name]
            if lobby_name in lobby_caps:
                del lobby_caps[lobby_name]
            if lobby_name in lobby_owners:
                del lobby_owners[lobby_name]
        else:
            # Ensure owner is valid; if current owner left, promote first member
            if lobby_owners.get(lobby_name) not in players:
                lobby_owners[lobby_name] = players[0]
        await broadcast_lobby_list()
async def broadcast_chat_message(lobby_name, msg_obj):
    payload = {"event": "chat_message", "lobby": lobby_name, "message": msg_obj}
    for ws in list(websockets):
        try:
            await ws.send_json(payload)
        except:
            pass

async def broadcast_to_lobby(lobby_name, payload):
    players = lobbies.get(lobby_name, [])
    for pid in list(players):
        for ws in list(player_sockets.get(pid, set())):
            try:
                await ws.send_json(payload)
            except:
                pass

async def broadcast_to_list_of_players(players, payload):
    for pid in list(players):
        for ws in list(player_sockets.get(pid, set())):
            try:
                await ws.send_json(payload)
            except:
                pass

async def send_lobby_members(lobby_name):
    member_ids = list(lobbies.get(lobby_name, []))
    members = [{"player_id": pid, "display_name": player_display_names.get(pid, pid)} for pid in member_ids]
    await broadcast_to_lobby(lobby_name, {"event": "lobby_members", "lobby": lobby_name, "members": members, "owner_id": lobby_owners.get(lobby_name), "max_players": lobby_caps.get(lobby_name, DEFAULT_MAX_PLAYERS)})

async def broadcast_to_all(payload):
    for ws in list(websockets):
        try:
            await ws.send_json(payload)
        except:
            pass

def build_lobby_list_payload():
    result = []
    for name, members in lobbies.items():
        try:
            result.append({
                "name": name,
                "max_players": lobby_caps.get(name, DEFAULT_MAX_PLAYERS),
                "count": len(members),
                "owner_id": lobby_owners.get(name)
            })
        except Exception:
            # Fallback to simple name if something goes wrong
            result.append(name)
    return result

# Duplicate function removed; standardized 'event' key is used above.

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

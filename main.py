from enum import Enum
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, List
from pydantic import BaseModel
import uuid
import uvicorn
from datetime import datetime
import logging
import sys
import websockets

# Configure logging with detailed timestamp
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s.%(msecs)03d %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler('game_server.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

app = FastAPI()

# CORS configuration
origins = [
    "http://localhost:3000",     # Next.js dev server
    "https://localhost:3000",
    "ws://localhost:3000",       # WebSocket connections
    "wss://localhost:3000",
    "http://localhost:8000",     # FastAPI dev server
    "https://localhost:8000",
    "ws://localhost:8000",
    "wss://localhost:8000",
    "https://your-production-domain.com",
    "wss://your-production-domain.com"
]

# Add CORS middleware with specific configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Define player count types
class PlayerCountType(str, Enum):
    SOLO = "solo"
    REPRESENTATIVE = "representative"
    TEAM = "team"

# Define the settings model
class GameSettings(BaseModel):
    version: str
    draftMode: str
    matchFormat: str
    playerCount: PlayerCountType  # Updated to use enum
    timeLimit: str

# Define the game result model
class GameResult(BaseModel):
    winner: str  # "team1" or "team2"
    score: dict  # {"team1": int, "team2": int}

# Define the lobby user model
class LobbyUser(BaseModel):
    id: str
    nickname: str
    team: str  # "BLUE" | "RED" | "SPECTATOR"
    position: int
    isReady: bool
    isHost: bool

# Define the lobby status model
class LobbyStatus(BaseModel):
    """Lobby status response model"""
    gameCode: str
    settings: GameSettings
    users: List[LobbyUser]  # '<' 를 '[' 로 수정
    status: str  # "waiting" | "ready" | "in_progress" | "completed"
    currentSet: int
    allReady: bool

# Participant limits per mode
PARTICIPANT_LIMITS = {
    PlayerCountType.SOLO: 1,
    PlayerCountType.REPRESENTATIVE: 2,
    PlayerCountType.TEAM: 10
}

# Updated room storage with settings
rooms: Dict[str, Dict[str, any]] = {}

# 브로드캐스트를 위한 WebSocket 연결 저장소 추가
connected_clients: Dict[str, Dict[str, WebSocket]] = {}

async def broadcast_room_status(game_code: str):
    """Broadcast room status to all connected clients"""
    if game_code not in rooms or game_code not in connected_clients:
        return
    
    room = rooms[game_code]
    all_ready = all(user["isReady"] or user["isHost"] for user in room["users"] if user["team"] != "SPECTATOR")
    
    status_update = {
        "type": "status_update",
        "data": LobbyStatus(
            gameCode=game_code,
            settings=GameSettings(**room["settings"]),
            users=room["users"],
            status=room["status"],
            currentSet=room["currentSet"],
            allReady=all_ready
        ).model_dump()
    }
    
    # 모든 연결된 클라이언트에게 상태 업데이트 전송
    for websocket in connected_clients[game_code].values():
        try:
            await websocket.send_json(status_update)
        except:
            logger.warning(f"Failed to send status update to a client in room {game_code}")

@app.post("/create-room")
async def create_room(request: Request):
    """Create a new room with game settings"""
    settings_data = await request.json()
    
    try:
        settings = GameSettings(**settings_data)
    except Exception as e:
        logger.error(f"Invalid settings data: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    
    room_id = str(uuid.uuid4())[:8]
    rooms[room_id] = {
        "bans": [],
        "picks": [],
        "settings": settings.model_dump(),  # Updated from dict()
        "status": "waiting",
        "participants": {},  # Active game participants
        "spectators": {},    # Spectators
        "currentSet": 1,     # 현재 세트 번호
        "results": [],       # 각 세트의 게임 결과
        "users": [],         # 로비 사용자 목록
    }
    logger.info(f"New room created - ID: {room_id}, Settings: {settings.model_dump()}")  # Updated from dict()
    return {"room_id": room_id}

@app.get("/game/{game_code}")
async def get_game(game_code: str):
    """Get game information for a specific room"""
    if game_code not in rooms:
        logger.warning(f"Room not found - ID: {game_code}")
        raise HTTPException(status_code=404, detail="Room not found")
    
    logger.info(f"Room info requested - ID: {game_code}")
    return rooms[game_code]

@app.get("/game/{game_code}/status", response_model=LobbyStatus)
async def get_lobby_status(game_code: str):
    """Get detailed lobby status information"""
    if game_code not in rooms:
        logger.warning(f"Room not found - ID: {game_code}")
        raise HTTPException(status_code=404, detail="Room not found")
    
    room = rooms[game_code]
    all_ready = all(user["isReady"] or user["isHost"] for user in room["users"] if user["team"] != "SPECTATOR")
    
    status_response = LobbyStatus(
        gameCode=game_code,
        settings=GameSettings(**room["settings"]),
        users=room["users"],
        status=room["status"],
        currentSet=room["currentSet"],
        allReady=all_ready
    )
    
    logger.info(f"Lobby status requested - Room: {game_code}, All ready: {all_ready}")
    return status_response

@app.post("/game/{game_code}/result")
async def submit_game_result(game_code: str, result: GameResult):
    """Submit the result for the current game set"""
    if game_code not in rooms:
        raise HTTPException(status_code=404, detail="Room not found")
    
    room = rooms[game_code]
    room["results"].append(result.model_dump())
    room["currentSet"] += 1  # 다음 세트로 이동
    room["bans"] = []       # 밴 목록 초기화
    room["picks"] = []      # 픽 목록 초기화
    
    logger.info(f"Game result submitted - Room: {game_code}, Set: {room['currentSet']-1}, Result: {result.model_dump()}")
    return {"status": "success", "currentSet": room["currentSet"]}

@app.post("/game/{game_code}/join")
async def join_lobby(game_code: str, user_data: dict):
    """Join lobby with nickname"""
    if game_code not in rooms:
        raise HTTPException(status_code=404, detail="Room not found")
    
    room = rooms[game_code]
    user_id = str(uuid.uuid4())[:6]
    
    new_user = LobbyUser(
        id=user_id,
        nickname=user_data["nickname"],
        team="SPECTATOR",
        position=-1,
        isReady=False,
        isHost=len(room["users"]) == 0  # 첫 번째 참가자를 호스트로 지정
    )
    
    room["users"].append(new_user.model_dump())
    logger.info(f"User '{new_user.nickname}' joined room {game_code}")
    
    # 모든 클라이언트에게 상태 업데이트 전송
    await broadcast_room_status(game_code)
    return new_user.model_dump()

@app.patch("/game/{game_code}/user/{user_id}/team")
async def update_team(game_code: str, user_id: str, team_data: dict):
    """Update user's team and position"""
    if game_code not in rooms:
        raise HTTPException(status_code=404, detail="Room not found")
    
    room = rooms[game_code]
    user = next((u for u in room["users"] if u["id"] == user_id), None)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user["team"] = team_data["team"]
    user["position"] = team_data["position"]
    logger.info(f"User '{user['nickname']}' moved to team {team_data['team']} at position {team_data['position']} in room {game_code}")
    
    # 모든 클라이언트에게 상태 업데이트 전송
    await broadcast_room_status(game_code)
    return user

@app.patch("/game/{game_code}/user/{user_id}/ready")
async def update_ready_status(game_code: str, user_id: str, ready_data: dict):
    """Update user's ready status"""
    if game_code not in rooms:
        raise HTTPException(status_code=404, detail="Room not found")
    
    room = rooms[game_code]
    user = next((u for u in room["users"] if u["id"] == user_id), None)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user["isReady"] = ready_data["isReady"]
    ready_status = "ready" if ready_data["isReady"] else "not ready"
    logger.info(f"User '{user['nickname']}' is now {ready_status} in room {game_code}")
    
    # 모든 클라이언트에게 상태 업데이트 전송
    await broadcast_room_status(game_code)
    return user

@app.websocket("/ws/draft")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    query_params = websocket.query_params
    room_id = query_params.get("id")
    is_spectator = query_params.get("spectator", "false").lower() == "true"
    client_id = str(uuid.uuid4())[:6]  # Generate unique client ID

    if not room_id or room_id not in rooms:
        logger.warning(f"Invalid room connection attempt - Client: {client_id}")
        await websocket.close()
        return

    room = rooms[room_id]
    player_count_type = room["settings"]["playerCount"]

    # Solo mode doesn't use WebSocket
    if player_count_type == PlayerCountType.SOLO:
        logger.warning(f"Solo mode doesn't support WebSocket connections")
        await websocket.close()
        return

    # Check participant limit if not spectator
    if not is_spectator:
        participant_limit = PARTICIPANT_LIMITS[player_count_type]
        if len(room["participants"]) >= participant_limit:
            logger.warning(f"Room {room_id} participant limit reached")
            await websocket.close()
            return
        room["participants"][client_id] = {
            "connected_at": datetime.now().isoformat(),
            "client_id": client_id
        }
    else:
        room["spectators"][client_id] = {
            "connected_at": datetime.now().isoformat(),
            "client_id": client_id
        }

    # WebSocket 연결 저장
    if room_id not in connected_clients:
        connected_clients[room_id] = {}
    connected_clients[room_id][client_id] = websocket

    # 사용자 닉네임 가져오기
    user = next((u for u in room["users"] if u["id"] == client_id), None)
    nickname = user["nickname"] if user else "Unknown"

    logger.info(f"User '{nickname}' connected to room {room_id} as {'spectator' if is_spectator else 'participant'}")

    try:
        while True:
            data = await websocket.receive_json()
            # Only participants can perform actions
            if not is_spectator:
                action = data.get("action")
                champion = data.get("champion")

                if action == "ban":
                    room["bans"].append(champion)
                    logger.info(f"Room {room_id}: Champion {champion} banned by '{nickname}'")
                elif action == "pick":
                    room["picks"].append(champion)
                    logger.info(f"Room {room_id}: Champion {champion} picked by '{nickname}'")
                elif action == "submit_result":
                    result = GameResult(**data.get("result", {}))
                    room["results"].append(result.model_dump())
                    room["currentSet"] += 1
                    room["bans"] = []
                    room["picks"] = []
                    logger.info(f"Room {room_id}: Game result submitted by '{nickname}' for set {room['currentSet']-1}")
                elif action == "update_team":
                    user_id = data.get("userId")
                    team_data = data.get("teamData")
                    target_user = next((u for u in room["users"] if u["id"] == user_id), None)
                    if target_user:
                        target_user["team"] = team_data["team"]
                        target_user["position"] = team_data["position"]
                        logger.info(f"User '{target_user['nickname']}' team updated by '{nickname}' in room {room_id}")
                elif action == "update_ready":
                    user_id = data.get("userId")
                    ready_status = data.get("isReady")
                    target_user = next((u for u in room["users"] if u["id"] == user_id), None)
                    if target_user:
                        target_user["isReady"] = ready_status
                        status_text = "ready" if ready_status else "not ready"
                        logger.info(f"User '{target_user['nickname']}' is now {status_text} in room {room_id}")

            await websocket.send_json(room)
            await broadcast_room_status(room_id)  # 상태 변경 시마다 브로드캐스트

    except WebSocketDisconnect:
        # WebSocket 연결 제거
        if room_id in connected_clients and client_id in connected_clients[room_id]:
            del connected_clients[room_id][client_id]
            if not connected_clients[room_id]:  # 방에 더 이상 연결된 클라이언트가 없으면
                del connected_clients[room_id]
        
        # 기존 participants/spectators 삭제
        if is_spectator:
            del room["spectators"][client_id]
        else:
            del room["participants"][client_id]
        
        # 로비 사용자 목록에서도 삭제
        room["users"] = [user for user in room["users"] if user["id"] != client_id]
        
        # 종료 로그에 닉네임 포함
        logger.info(f"User '{nickname}' disconnected from room {room_id}")
        
        # 남아있는 모든 클라이언트에게 업데이트된 방 정보 브로드캐스트
        await broadcast_room_status(room_id)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

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

# 로깅 설정: 모든 이벤트에 타임스탬프 포함
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

# FastAPI 애플리케이션 초기화
app = FastAPI()

# CORS 설정
# 개발 환경과 프로덕션 환경 모두에서 웹소켓 연결을 허용하기 위해
# http, https, ws, wss 프로토콜을 모두 허용
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

# PlayerCountType: 게임 모드별 참가자 수를 정의하는 열거형
# - SOLO: 혼자서 연습하는 모드
# - REPRESENTATIVE: 팀당 1명의 대표가 참여하는 모드
# - TEAM: 팀 전체가 참여하는 모드
class PlayerCountType(str, Enum):
    SOLO = "solo"
    REPRESENTATIVE = "representative"
    TEAM = "team"

# GameSettings: 게임 방 생성 시 필요한 설정
# - version: 게임 버전 (예: "13.10")
# - draftMode: 드래프트 모드 (예: "Tournament" 등)
# - matchFormat: 경기 포맷 (예: "Bo1", "Bo3", "Bo5")
# - playerCount: 참가자 수 타입
# - timeLimit: 선택 제한 시간
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

# 전역 상태 저장소
# rooms: 게임 방들의 상태를 저장
# - key: 방 ID (8자리 UUID)
# - value: 방 상태 정보 (설정, 참가자, 현재 상태 등)
rooms: Dict[str, Dict[str, any]] = {}

# WebSocket 연결 저장소
# - key: 방 ID
# - value: Dictionary of client_id to WebSocket connection
connected_clients: Dict[str, Dict[str, WebSocket]] = {}

async def broadcast_room_status(game_code: str):
    """
    방의 상태가 변경될 때마다 해당 방의 모든 연결된 클라이언트에게 업데이트를 전송
    
    브로드캐스트되는 상황:
    1. 새로운 사용자 입장/퇴장
    2. 팀 변경
    3. 준비 상태 변경
    4. 게임 결과 제출
    """
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
    """
    새로운 게임 방을 생성
    
    1. 클라이언트로부터 받은 설정을 검증
    2. 고유한 방 ID 생성 (8자리 UUID)
    3. 초기 상태의 방 생성 (대기 상태)
    4. 방 정보를 전역 저장소에 저장
    """
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
    """
    WebSocket 연결을 처리하는 메인 엔드포인트
    
    연결 과정:
    1. 연결 수락 및 클라이언트 정보 확인
    2. 방 존재 여부 확인
    3. 연결 정보 저장
    4. 상태 변경 처리 및 브로드캐스트
    """
    await websocket.accept()
    query_params = websocket.query_params
    room_id = query_params.get("id")
    user_id = query_params.get("userId")  # userId를 쿼리 파라미터로 받음
    is_spectator = query_params.get("spectator", "false").lower() == "true"

    if not room_id or not user_id or room_id not in rooms:
        logger.warning(f"Invalid connection attempt - Room: {room_id}, User: {user_id}")
        await websocket.close()
        return

    room = rooms[room_id]
    
    # Solo mode check
    if room["settings"]["playerCount"] == PlayerCountType.SOLO:
        logger.warning(f"Solo mode doesn't support WebSocket connections")
        await websocket.close()
        return

    # Find user in room
    user = next((u for u in room["users"] if u["id"] == user_id), None)
    if not user:
        logger.warning(f"User {user_id} not found in room {room_id}")
        await websocket.close()
        return

    nickname = user["nickname"]

    # Register connection info
    if not is_spectator:
        room["participants"][user_id] = {
            "connected_at": datetime.now().isoformat(),
            "client_id": user_id
        }
    else:
        room["spectators"][user_id] = {
            "connected_at": datetime.now().isoformat(),
            "client_id": user_id
        }

    # Store WebSocket connection
    if room_id not in connected_clients:
        connected_clients[room_id] = {}
    connected_clients[room_id][user_id] = websocket

    logger.info(f"User '{nickname}' connected to room {room_id} as {'spectator' if is_spectator else 'participant'}")

    try:
        while True:
            data = await websocket.receive_json()
            if not is_spectator:
                action = data.get("action")
                
                if action == "update_team":
                    target_id = data.get("userId")
                    team_data = data.get("teamData")
                    target_user = next((u for u in room["users"] if u["id"] == target_id), None)
                    if target_user:
                        # Update user's team and position
                        target_user["team"] = team_data["team"]
                        target_user["position"] = team_data["position"]
                        logger.info(f"User '{target_user['nickname']}' team updated to {team_data['team']} at position {team_data['position']} in room {room_id}")
                        await broadcast_room_status(room_id)

                elif action == "update_ready":
                    target_id = data.get("userId")
                    ready_status = data.get("isReady")
                    target_user = next((u for u in room["users"] if u["id"] == target_id), None)
                    if target_user:
                        # Update user's ready status
                        target_user["isReady"] = ready_status
                        status_text = "ready" if ready_status else "not ready"
                        logger.info(f"User '{target_user['nickname']}' is now {status_text} in room {room_id}")
                        await broadcast_room_status(room_id)

                elif action in ["ban", "pick"]:
                    # ...existing ban/pick handling code...
                    pass

            # Send safe copy of room data
            room_data = {k: v for k, v in room.items() if k not in ["spectators", "participants"]}
            await websocket.send_json(room_data)

    except WebSocketDisconnect:
        # Cleanup connections
        if room_id in connected_clients and user_id in connected_clients[room_id]:
            del connected_clients[room_id][user_id]
            if not connected_clients[room_id]:
                del connected_clients[room_id]

        # Remove from participants/spectators
        if is_spectator:
            room["spectators"].pop(user_id, None)
        else:
            room["participants"].pop(user_id, None)

        logger.info(f"User '{nickname}' disconnected from room {room_id}")
        await broadcast_room_status(room_id)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

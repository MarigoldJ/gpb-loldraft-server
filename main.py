from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from typing import Dict, List
import uvicorn

app = FastAPI()

# 방 목록 (방 ID별 밴픽 상태 저장)
rooms: Dict[str, Dict[str, List[str]]] = {}

@app.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str):
    await websocket.accept()
    
    if room_id not in rooms:
        rooms[room_id] = {"bans": [], "picks": []}

    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action")
            champion = data.get("champion")

            if action == "ban":
                rooms[room_id]["bans"].append(champion)
            elif action == "pick":
                rooms[room_id]["picks"].append(champion)

            # 모든 클라이언트에게 업데이트 전송
            await websocket.send_json(rooms[room_id])

    except WebSocketDisconnect:
        print(f"Client disconnected from room {room_id}")

@app.get("/room/{room_id}")
async def get_room_state(room_id: str):
    return rooms.get(room_id, {"bans": [], "picks": []})

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

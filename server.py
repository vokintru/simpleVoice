import random
import string
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import socketio
from typing import Dict

app = FastAPI()

sio = socketio.AsyncServer(
    cors_allowed_origins="*",
    async_mode='asgi'
)
socket_app = socketio.ASGIApp(sio, app)

rooms: Dict[str, Dict[str, dict]] = {}
users: Dict[str, str] = {}


def generate_room_code(length: int = 6) -> str:
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))
        if code not in rooms:
            return code


@app.get("/", response_class=HTMLResponse)
async def get_index():
    with open("templates/index.html", "r", encoding="utf-8") as f:
        return f.read()


@app.get("/room/{room_code}", response_class=HTMLResponse)
async def get_room(room_code: str):
    room_code = room_code.upper()
    print(f"Запрос страницы комнаты: {room_code}, существует: {room_code in rooms}")
    with open("templates/room.html", "r", encoding="utf-8") as f:
        content = f.read().replace("{{ROOM_CODE}}", room_code)
        return content


@app.get("/api/rooms/{room_code}/exists")
async def check_room_exists(room_code: str):
    room_code = room_code.upper()
    exists = room_code in rooms
    user_count = len(rooms[room_code]) if exists else 0
    print(f"Проверка комнаты {room_code}: существует={exists}, пользователей={user_count}")
    return {"exists": exists, "user_count": user_count}


@sio.event
async def connect(sid, environ):
    print(f"Клиент подключен: {sid}")


@sio.event
async def disconnect(sid):
    print(f"Клиент отключен: {sid}")

    if sid in users:
        room_code = users[sid]
        if room_code in rooms and sid in rooms[room_code]:
            del rooms[room_code][sid]
            
            print(f"Пользователь {sid} удален из комнаты {room_code}. Осталось пользователей: {len(rooms[room_code])}")

            await sio.emit('user-left', {'sid': sid}, room=room_code, skip_sid=sid)

            print(f"Комната {room_code} сохранена. Всего пользователей в ней: {len(rooms[room_code])}")
        
        del users[sid]


@sio.event
async def create_room(sid, data):
    try:
        print(f"Получен запрос на создание комнаты от {sid}, данные: {data}")
        room_code = generate_room_code()
        rooms[room_code] = {}
        users[sid] = room_code

        await sio.enter_room(sid, room_code)

        username = data.get('username', 'User')
        rooms[room_code][sid] = {
            'socket_id': sid,
            'username': username
        }
        
        print(f"Создана комната {room_code} пользователем {sid} ({username})")
        print(f"Всего комнат в системе: {len(rooms)}, комната {room_code} содержит {len(rooms[room_code])} пользователей")
        await sio.emit('room-created', {'room_code': room_code}, room=sid)
        print(f"Отправлено событие room-created в комнату {sid}")
    except Exception as e:
        print(f"Ошибка при создании комнаты: {e}")
        import traceback
        traceback.print_exc()


@sio.event
async def join_room(sid, data):
    try:
        room_code = data.get('room_code', '').upper().strip()
        username = data.get('username', 'User')
        
        print(f"Запрос на присоединение к комнате: код={room_code}, пользователь={username}, socket_id={sid}")
        print(f"Доступные комнаты: {list(rooms.keys())}")
        
        if not room_code:
            await sio.emit('join-error', {'message': 'Код комнаты не указан'}, room=sid)
            print(f"Ошибка: код комнаты не указан для {sid}")
            return
        
        if room_code not in rooms:
            await sio.emit('join-error', {'message': f'Комната {room_code} не найдена'}, room=sid)
            print(f"Ошибка: комната {room_code} не найдена. Доступные: {list(rooms.keys())}")
            return

        if sid in users and users[sid] != room_code:
            old_room = users[sid]
            if old_room in rooms and sid in rooms[old_room]:
                del rooms[old_room][sid]
                await sio.leave_room(sid, old_room)

        await sio.enter_room(sid, room_code)
        users[sid] = room_code

        rooms[room_code][sid] = {
            'socket_id': sid,
            'username': username
        }

        users_in_room = [
            {'socket_id': u['socket_id'], 'username': u['username']}
            for u in rooms[room_code].values()
        ]
        
        print(f"Отправка room-joined для {sid}, пользователей в комнате: {len(users_in_room)}")
        await sio.emit('room-joined', {
            'room_code': room_code,
            'users': users_in_room
        }, room=sid)

        if len(rooms[room_code]) > 1:
            await sio.emit('user-joined', {
                'socket_id': sid,
                'username': username
            }, room=room_code, skip_sid=sid)
        
        print(f"Пользователь {sid} ({username}) присоединился к комнате {room_code}. Всего в комнате: {len(rooms[room_code])}")
    except Exception as e:
        print(f"Ошибка при присоединении к комнате: {e}")
        import traceback
        traceback.print_exc()
        await sio.emit('join-error', {'message': f'Ошибка сервера: {str(e)}'}, room=sid)


@sio.event
async def offer(sid, data):
    target_sid = data.get('target')
    offer = data.get('offer')
    
    await sio.emit('offer', {
        'offer': offer,
        'from': sid
    }, room=target_sid)
    print(f"Offer от {sid} к {target_sid}")


@sio.event
async def answer(sid, data):
    target_sid = data.get('target')
    answer = data.get('answer')
    
    await sio.emit('answer', {
        'answer': answer,
        'from': sid
    }, room=target_sid)
    print(f"Answer от {sid} к {target_sid}")


@sio.event
async def ice_candidate(sid, data):
    target_sid = data.get('target')
    candidate = data.get('candidate')
    
    await sio.emit('ice-candidate', {
        'candidate': candidate,
        'from': sid
    }, room=target_sid)


@sio.event
async def mic_muted(sid, data):
    room_code = users.get(sid)
    if room_code:
        await sio.emit('user-mic-muted', {
            'socket_id': sid,
            'muted': True
        }, room=room_code, skip_sid=sid)
        print(f"Пользователь {sid} выключил микрофон в комнате {room_code}")


@sio.event
async def mic_unmuted(sid, data):
    room_code = users.get(sid)
    if room_code:
        await sio.emit('user-mic-unmuted', {
            'socket_id': sid,
            'muted': False
        }, room=room_code, skip_sid=sid)
        print(f"Пользователь {sid} включил микрофон в комнате {room_code}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(socket_app, host="0.0.0.0", port=8088)


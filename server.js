const express = require('express');
const http = require('http');
const { Server } = require('socket.io');
const { v4: uuidv4 } = require('uuid');
const path = require('path');

const app = express();
const server = http.createServer(app);
const io = new Server(server, {
  cors: { origin: "*" }
});

app.use(express.static(path.join(__dirname, 'public')));

// ==================== КОНФИГУРАЦИЯ ДОСКИ ====================
const BOARD_SIZE = 15;
const COLORS = ['yellow', 'blue', 'red', 'green'];
const COLOR_CODES = {
  yellow: '#FFC107',
  blue: '#03A9F4',
  red: '#FF5252',
  green: '#8BC34A'
};

// Путь для каждого цвета (координаты [row, col])
const PATHS = {
  yellow: [
    [6,1],[6,2],[6,3],[6,4],[6,5],
    [5,6],[4,6],[3,6],[2,6],[1,6],[0,6],
    [0,7],[0,8],
    [1,8],[2,8],[3,8],[4,8],[5,8],
    [6,9],[6,10],[6,11],[6,12],[6,13],[6,14],
    [7,14],[8,14],
    [8,13],[8,12],[8,11],[8,10],[8,9],
    [9,8],[10,8],[11,8],[12,8],[13,8],[14,8],
    [14,7],[14,6],
    [13,6],[12,6],[11,6],[10,6],[9,6],
    [8,5],[8,4],[8,3],[8,2],[8,1],[8,0],
    [7,0],[7,1],[7,2],[7,3],[7,4],[7,5],[7,6]
  ],
  blue: [
    [1,8],[2,8],[3,8],[4,8],[5,8],
    [6,9],[6,10],[6,11],[6,12],[6,13],[6,14],
    [7,14],[8,14],
    [8,13],[8,12],[8,11],[8,10],[8,9],
    [9,8],[10,8],[11,8],[12,8],[13,8],[14,8],
    [14,7],[14,6],
    [13,6],[12,6],[11,6],[10,6],[9,6],
    [8,5],[8,4],[8,3],[8,2],[8,1],[8,0],
    [7,0],[6,0],
    [6,1],[6,2],[6,3],[6,4],[6,5],
    [5,6],[4,6],[3,6],[2,6],[1,6],[0,6],
    [0,7],[1,7],[2,7],[3,7],[4,7],[5,7],[6,7]
  ],
  red: [
    [8,13],[8,12],[8,11],[8,10],[8,9],
    [9,8],[10,8],[11,8],[12,8],[13,8],[14,8],
    [14,7],[14,6],
    [13,6],[12,6],[11,6],[10,6],[9,6],
    [8,5],[8,4],[8,3],[8,2],[8,1],[8,0],
    [7,0],[6,0],
    [6,1],[6,2],[6,3],[6,4],[6,5],
    [5,6],[4,6],[3,6],[2,6],[1,6],[0,6],
    [0,7],[0,8],
    [1,8],[2,8],[3,8],[4,8],[5,8],
    [6,9],[6,10],[6,11],[6,12],[6,13],[6,14],
    [7,14],[7,13],[7,12],[7,11],[7,10],[7,9],[7,8]
  ],
  green: [
    [13,6],[12,6],[11,6],[10,6],[9,6],
    [8,5],[8,4],[8,3],[8,2],[8,1],[8,0],
    [7,0],[6,0],
    [6,1],[6,2],[6,3],[6,4],[6,5],
    [5,6],[4,6],[3,6],[2,6],[1,6],[0,6],
    [0,7],[0,8],
    [1,8],[2,8],[3,8],[4,8],[5,8],
    [6,9],[6,10],[6,11],[6,12],[6,13],[6,14],
    [7,14],[8,14],
    [8,13],[8,12],[8,11],[8,10],[8,9],
    [9,8],[10,8],[11,8],[12,8],[13,8],[14,8],
    [14,7],[13,7],[12,7],[11,7],[10,7],[9,7],[8,7]
  ]
};

// Базовые позиции (где фишки стартуют)
const BASE_POSITIONS = {
  yellow: [[1,1],[1,4],[4,1],[4,4]],
  blue: [[1,10],[1,13],[4,10],[4,13]],
  red: [[10,1],[10,4],[13,1],[13,4]],
  green: [[10,10],[10,13],[13,10],[13,13]]
};

// Safe-зоны (звёздочки)
const SAFE_ZONES = [
  [2,6],[6,2],[10,6],[6,10],  // стартовые звёзды
  [6,6],[6,8],[8,6],[8,8]     // центральные
];

// ==================== КЛАСС КОМНАТЫ ====================
class Room {
  constructor(id, hostId, hostName) {
    this.id = id;
    this.players = [{ id: hostId, name: hostName, color: null, ready: false }];
    this.hostId = hostId;
    this.status = 'waiting'; // waiting, playing, finished
    this.currentTurn = 0;
    this.dice = 1;
    this.board = this.initBoard();
    this.winner = null;
    this.moveHistory = [];
    this.createdAt = Date.now();
  }

  initBoard() {
    const board = {};
    COLORS.forEach(color => {
      board[color] = {
        pieces: [0, 0, 0, 0], // 0 = в базе, 1-56 = на пути, 57 = финиш
        base: BASE_POSITIONS[color].map((pos, i) => ({ id: i, pos, onBoard: false, pathIndex: -1 }))
      };
    });
    return board;
  }

  addPlayer(playerId, playerName) {
    if (this.players.length >= 4) return false;
    if (this.status !== 'waiting') return false;
    this.players.push({ id: playerId, name: playerName, color: null, ready: false });
    return true;
  }

  removePlayer(playerId) {
    this.players = this.players.filter(p => p.id !== playerId);
    if (this.players.length === 0) return true; // комната пуста
    if (this.hostId === playerId && this.players.length > 0) {
      this.hostId = this.players[0].id;
    }
    return false;
  }

  assignColors() {
    const available = COLORS.slice(0, this.players.length);
    this.players.forEach((p, i) => {
      p.color = available[i];
    });
  }

  startGame() {
    if (this.players.length < 2) return false;
    this.assignColors();
    this.status = 'playing';
    this.currentTurn = 0;
    return true;
  }

  getCurrentPlayer() {
    return this.players[this.currentTurn % this.players.length];
  }

  rollDice() {
    this.dice = Math.floor(Math.random() * 6) + 1;
    return this.dice;
  }

  canMove(pieceIndex, playerColor) {
    const piece = this.board[playerColor].base[pieceIndex];

    // Если в базе — нужна 6 чтобы выйти
    if (!piece.onBoard) {
      return this.dice === 6;
    }

    // Если на пути — проверяем не вышли ли за пределы
    if (piece.pathIndex + this.dice > 56) {
      return false;
    }

    return true;
  }

  movePiece(pieceIndex, playerColor) {
    const piece = this.board[playerColor].base[pieceIndex];
    const path = PATHS[playerColor];

    if (!piece.onBoard) {
      // Выход из базы
      if (this.dice !== 6) return false;
      piece.onBoard = true;
      piece.pathIndex = 0;
    } else {
      // Движение по пути
      piece.pathIndex += this.dice;
    }

    // Проверяем "убийство"
    if (piece.pathIndex < 51) { // Не на домашней дорожке
      const newPos = path[piece.pathIndex];
      this.checkKill(newPos, playerColor);
    }

    // Проверяем победу
    if (piece.pathIndex >= 56) {
      piece.pathIndex = 57; // Финиш
      this.checkWin(playerColor);
    }

    // Записываем ход
    this.moveHistory.push({
      player: playerColor,
      piece: pieceIndex,
      dice: this.dice,
      from: piece.onBoard ? piece.pathIndex - this.dice : -1,
      to: piece.pathIndex,
      time: Date.now()
    });

    return true;
  }

  checkKill(pos, killerColor) {
    COLORS.forEach(color => {
      if (color === killerColor) return;
      this.board[color].base.forEach(piece => {
        if (!piece.onBoard || piece.pathIndex >= 51) return;
        const piecePos = PATHS[color][piece.pathIndex];
        if (piecePos[0] === pos[0] && piecePos[1] === pos[1]) {
          // Проверяем safe-зону
          const isSafe = SAFE_ZONES.some(sz => sz[0] === pos[0] && sz[1] === pos[1]);
          if (!isSafe) {
            // Убиваем!
            piece.onBoard = false;
            piece.pathIndex = -1;
          }
        }
      });
    });
  }

  checkWin(color) {
    const allFinished = this.board[color].base.every(p => p.pathIndex >= 56);
    if (allFinished) {
      this.winner = color;
      this.status = 'finished';
    }
  }

  nextTurn() {
    if (this.dice === 6) {
      // Если выпала 6 — ход тот же игрок (но не более 3 раз подряд)
      return;
    }
    this.currentTurn++;
  }

  getState() {
    return {
      id: this.id,
      status: this.status,
      players: this.players.map(p => ({
        id: p.id,
        name: p.name,
        color: p.color,
        ready: p.ready
      })),
      currentTurn: this.currentTurn,
      currentPlayer: this.getCurrentPlayer()?.color || null,
      dice: this.dice,
      board: this.board,
      winner: this.winner,
      moveHistory: this.moveHistory.slice(-10)
    };
  }
}

// ==================== ХРАНИЛИЩЕ ====================
const rooms = new Map();
const playerRooms = new Map(); // socket.id -> roomId

function generateRoomCode() {
  return Math.random().toString(36).substring(2, 7).toUpperCase();
}

// ==================== SOCKET.IO ====================
io.on('connection', (socket) => {
  console.log('Player connected:', socket.id);

  // Создание комнаты
  socket.on('create-room', (data, callback) => {
    const roomId = generateRoomCode();
    const room = new Room(roomId, socket.id, data.name || 'Player 1');
    rooms.set(roomId, room);
    playerRooms.set(socket.id, roomId);
    socket.join(roomId);

    callback({ success: true, roomId, state: room.getState() });
    console.log('Room created:', roomId);
  });

  // Присоединение к комнате
  socket.on('join-room', (data, callback) => {
    const roomId = data.roomId.toUpperCase();
    const room = rooms.get(roomId);

    if (!room) {
      callback({ success: false, error: 'Комната не найдена' });
      return;
    }

    if (room.status !== 'waiting') {
      callback({ success: false, error: 'Игра уже началась' });
      return;
    }

    if (!room.addPlayer(socket.id, data.name || `Player ${room.players.length + 1}`)) {
      callback({ success: false, error: 'Комната заполнена' });
      return;
    }

    playerRooms.set(socket.id, roomId);
    socket.join(roomId);

    io.to(roomId).emit('room-update', room.getState());
    callback({ success: true, state: room.getState() });
    console.log('Player joined:', roomId, socket.id);
  });

  // Готовность
  socket.on('ready', () => {
    const roomId = playerRooms.get(socket.id);
    if (!roomId) return;

    const room = rooms.get(roomId);
    const player = room.players.find(p => p.id === socket.id);
    if (player) {
      player.ready = !player.ready;
      io.to(roomId).emit('room-update', room.getState());
    }
  });

  // Старт игры
  socket.on('start-game', () => {
    const roomId = playerRooms.get(socket.id);
    if (!roomId) return;

    const room = rooms.get(roomId);
    if (room.hostId !== socket.id) return;

    const allReady = room.players.every(p => p.ready);
    if (!allReady) {
      socket.emit('error', 'Не все игроки готовы');
      return;
    }

    if (room.startGame()) {
      io.to(roomId).emit('game-started', room.getState());
    }
  });

  // Бросок кубика
  socket.on('roll-dice', () => {
    const roomId = playerRooms.get(socket.id);
    if (!roomId) return;

    const room = rooms.get(roomId);
    const currentPlayer = room.getCurrentPlayer();

    if (currentPlayer.id !== socket.id) return;
    if (room.status !== 'playing') return;

    const dice = room.rollDice();
    io.to(roomId).emit('dice-rolled', { 
      player: currentPlayer.color, 
      dice,
      state: room.getState()
    });
  });

  // Ход фишкой
  socket.on('move-piece', (data) => {
    const roomId = playerRooms.get(socket.id);
    if (!roomId) return;

    const room = rooms.get(roomId);
    const currentPlayer = room.getCurrentPlayer();

    if (currentPlayer.id !== socket.id) return;
    if (room.status !== 'playing') return;

    const pieceIndex = data.pieceIndex;
    if (!room.canMove(pieceIndex, currentPlayer.color)) {
      socket.emit('error', 'Нельзя так ходить');
      return;
    }

    room.movePiece(pieceIndex, currentPlayer.color);
    room.nextTurn();

    io.to(roomId).emit('piece-moved', room.getState());

    if (room.winner) {
      io.to(roomId).emit('game-over', { winner: room.winner, state: room.getState() });
    }
  });

  // Отключение
  socket.on('disconnect', () => {
    const roomId = playerRooms.get(socket.id);
    if (roomId) {
      const room = rooms.get(roomId);
      if (room) {
        const isEmpty = room.removePlayer(socket.id);
        if (isEmpty) {
          rooms.delete(roomId);
        } else {
          io.to(roomId).emit('player-left', room.getState());
        }
      }
      playerRooms.delete(socket.id);
    }
    console.log('Player disconnected:', socket.id);
  });
});

// ==================== ЗАПУСК ====================
const PORT = process.env.PORT || 3000;
server.listen(PORT, () => {
  console.log(`🎲 Ludo Server running on port ${PORT}`);
});

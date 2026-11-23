/**
 * Cloudflare Worker Entrypoint — Workspace Battle Royale Realtime Backend
 *
 * Routes:
 *   GET  /health       -> Health check JSON
 *   POST /api/rooms    -> Generates a fresh unambiguous 5-char room code
 *   GET  /room/:code   -> WebSocket upgrade routed deterministically to GameRoom DO
 */

import { generateRoomCode, isValidRoomCode, normalizeRoomCode } from '../../src/net/protocol';
import { GameRoom } from './gameRoom';

export { GameRoom };

export interface Env {
  GAME_ROOM: DurableObjectNamespace<GameRoom>;
}

const CORS_HEADERS: Record<string, string> = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      ...CORS_HEADERS,
    },
  });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: CORS_HEADERS });
    }

    const url = new URL(request.url);
    const pathname = url.pathname;

    if (request.method === 'GET' && pathname === '/health') {
      return jsonResponse({
        ok: true,
        service: 'workspace-battle-royale-rt',
      });
    }

    if (request.method === 'POST' && pathname === '/api/rooms') {
      return jsonResponse({
        ok: true,
        roomCode: generateRoomCode(),
      });
    }

    const roomMatch = /^\/room\/([^/]+)\/?$/i.exec(pathname);
    if (roomMatch) {
      let rawCode = roomMatch[1];
      try {
        rawCode = decodeURIComponent(rawCode);
      } catch {
        return jsonResponse({ ok: false, error: 'Malformed room code' }, 400);
      }
      const code = normalizeRoomCode(rawCode);
      if (!isValidRoomCode(code)) {
        return jsonResponse(
          { ok: false, error: 'Room code must be 4-6 alphanumeric characters' },
          400
        );
      }

      const upgradeHeader = request.headers.get('Upgrade');
      if (!upgradeHeader || upgradeHeader.toLowerCase() !== 'websocket') {
        return jsonResponse(
          { ok: false, error: 'Expected Upgrade: websocket header' },
          426
        );
      }

      const stub = env.GAME_ROOM.getByName(code);
      return stub.fetch(request);
    }

    return jsonResponse({ ok: false, error: 'Not found' }, 404);
  },
} satisfies ExportedHandler<Env>;

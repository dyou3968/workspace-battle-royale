/// <reference types="vite/client" />

/**
 * Browser Multiplayer WebSocket Client
 *
 * Manages connection lifecycle, URL resolution (`?server=`, `VITE_MP_SERVER_URL`,
 * localhost dev fallback, and prod fallback), 3-second RTT pings, and typed
 * `ClientMessage` / `ServerMessage` transport against the Cloudflare Worker
 * `GameRoom` Durable Object.
 */

import {
  ClientMessage,
  MpHeroId,
  ServerMessage,
  TeamId,
  isValidRoomCode,
  normalizeRoomCode,
} from './protocol';

/**
 * Production Cloudflare Workers realtime backend URL fallback.
 *
 * Can still be overridden at build time via `VITE_MP_SERVER_URL` (Cloudflare Pages
 * environment variable), at runtime via `?server=wss://...`, or automatically via
 * `ws://127.0.0.1:8787` when served on `localhost` / `127.0.0.1`.
 */
export const DEFAULT_PROD_MP_URL = 'wss://workspace-battle-royale.dyou3968.workers.dev';

export const MP_NOT_CONFIGURED_MESSAGE = 'Multiplayer server URL not configured yet';

const PING_INTERVAL_MS = 3000;

export type MpConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'error';

export interface MpStatusSnapshot {
  status: MpConnectionStatus;
  rttMs: number | null;
  roomCode: string | null;
  memberId: string | null;
  serverUrl: string | null;
  errorMessage: string | null;
}

export interface MpJoinProfile {
  name: string;
  heroId: MpHeroId;
  teamId?: TeamId;
}

export type MpMessageListener = (msg: ServerMessage) => void;
export type MpStatusListener = (info: MpStatusSnapshot) => void;

/**
 * Resolve the multiplayer server base URL with strict priority:
 *  1. Query string `?server=...` (handy for staging / local tunnel testing)
 *  2. Build-time Vite env `import.meta.env.VITE_MP_SERVER_URL`
 *  3. Local development default `ws://127.0.0.1:8787` when served on localhost / 127.0.0.1
 *  4. `DEFAULT_PROD_MP_URL` fallback constant
 *
 * Returns `null` when running in production with no server URL configured yet.
 */
export function resolveMpServerUrl(): string | null {
  if (typeof window !== 'undefined') {
    try {
      const params = new URLSearchParams(window.location.search);
      const fromQuery = params.get('server')?.trim();
      if (fromQuery) return fromQuery;
    } catch {
      // Ignore malformed location.search
    }
  }

  const fromEnv =
    typeof import.meta !== 'undefined' && import.meta.env
      ? (import.meta.env.VITE_MP_SERVER_URL ?? '').trim()
      : '';
  if (fromEnv) return fromEnv;

  if (typeof window !== 'undefined') {
    const host = window.location.hostname;
    if (host === 'localhost' || host === '127.0.0.1') {
      return 'ws://127.0.0.1:8787';
    }
  }

  const fallback = DEFAULT_PROD_MP_URL.trim();
  return fallback.length > 0 ? fallback : null;
}

/**
 * Normalize an http/https/ws/wss server base URL into a clean `ws://` or `wss://`
 * base URL with no trailing slash.
 */
export function toWebSocketBaseUrl(rawUrl: string): string {
  let url = rawUrl.trim().replace(/\/+$/, '');
  if (/^https:\/\//i.test(url)) {
    url = 'wss://' + url.slice('https://'.length);
  } else if (/^http:\/\//i.test(url)) {
    url = 'ws://' + url.slice('http://'.length);
  } else if (!/^wss?:\/\//i.test(url)) {
    const isLocal = /^(localhost|127\.0\.0\.1)(:|\/|$)/i.test(url);
    url = `${isLocal ? 'ws' : 'wss'}://${url}`;
  }
  return url;
}

/**
 * Normalize an http/https/ws/wss server base URL into an `http://` or `https://`
 * base URL with no trailing slash (for REST endpoints like `/api/rooms` & `/health`).
 */
export function toHttpBaseUrl(rawUrl: string): string {
  let url = rawUrl.trim().replace(/\/+$/, '');
  if (/^wss:\/\//i.test(url)) {
    url = 'https://' + url.slice('wss://'.length);
  } else if (/^ws:\/\//i.test(url)) {
    url = 'http://' + url.slice('ws://'.length);
  } else if (!/^https?:\/\//i.test(url)) {
    const isLocal = /^(localhost|127\.0\.0\.1)(:|\/|$)/i.test(url);
    url = `${isLocal ? 'http' : 'https'}://${url}`;
  }
  return url;
}

/**
 * Read an optional `?room=CODE` query parameter from the current browser URL.
 */
export function readRoomCodeFromUrl(): string | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = new URLSearchParams(window.location.search).get('room');
    if (!raw) return null;
    const normalized = normalizeRoomCode(raw);
    return isValidRoomCode(normalized) ? normalized : null;
  } catch {
    return null;
  }
}

/**
 * Build a shareable invite link containing `?room=CODE` (preserving `?server=` if set).
 */
export function buildRoomInviteUrl(roomCode: string): string {
  const code = normalizeRoomCode(roomCode);
  if (typeof window === 'undefined') return `?room=${code}`;
  const url = new URL(window.location.href);
  url.searchParams.set('room', code);
  return url.toString();
}

export class MultiplayerClient {
  private ws: WebSocket | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private intentionalClose = false;

  private _status: MpConnectionStatus = 'disconnected';
  private _rttMs: number | null = null;
  private _roomCode: string | null = null;
  private _memberId: string | null = null;
  private _serverUrl: string | null = null;
  private _errorMessage: string | null = null;

  private messageListeners = new Set<MpMessageListener>();
  private statusListeners = new Set<MpStatusListener>();

  public get status(): MpConnectionStatus {
    return this._status;
  }

  public get rttMs(): number | null {
    return this._rttMs;
  }

  public get roomCode(): string | null {
    return this._roomCode;
  }

  public get memberId(): string | null {
    return this._memberId;
  }

  public get serverUrl(): string | null {
    return this._serverUrl;
  }

  public get errorMessage(): string | null {
    return this._errorMessage;
  }

  public get isConnected(): boolean {
    return this._status === 'connected' && this.ws !== null && this.ws.readyState === WebSocket.OPEN;
  }

  public getStatusSnapshot(): MpStatusSnapshot {
    return {
      status: this._status,
      rttMs: this._rttMs,
      roomCode: this._roomCode,
      memberId: this._memberId,
      serverUrl: this._serverUrl,
      errorMessage: this._errorMessage,
    };
  }

  /**
   * Request a freshly generated room code from the Worker (`POST /api/rooms`).
   */
  public async createRoom(explicitServerUrl?: string): Promise<string> {
    const resolved = explicitServerUrl?.trim() || resolveMpServerUrl();
    if (!resolved) {
      this.setStatus('error', MP_NOT_CONFIGURED_MESSAGE);
      throw new Error(MP_NOT_CONFIGURED_MESSAGE);
    }

    const httpBase = toHttpBaseUrl(resolved);
    const res = await fetch(`${httpBase}/api/rooms`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    if (!res.ok) {
      const msg = `Failed to create room (HTTP ${res.status})`;
      this.setStatus('error', msg);
      throw new Error(msg);
    }
    const data = (await res.json()) as { roomCode?: string };
    const code = normalizeRoomCode(data.roomCode ?? '');
    if (!isValidRoomCode(code)) {
      const msg = 'Server returned an invalid room code';
      this.setStatus('error', msg);
      throw new Error(msg);
    }
    return code;
  }

  /**
   * Connect to `${wsBaseUrl}/room/${roomCode}` and immediately send `join_room`.
   */
  public connect(
    roomCode: string,
    profile: MpJoinProfile,
    explicitServerUrl?: string
  ): boolean {
    const normalizedCode = normalizeRoomCode(roomCode);
    if (!isValidRoomCode(normalizedCode)) {
      this.setStatus('error', 'Room code must be 4–6 letters or numbers');
      return false;
    }

    const resolved = explicitServerUrl?.trim() || resolveMpServerUrl();
    if (!resolved) {
      this.teardownSocket(true);
      this._roomCode = normalizedCode;
      this._serverUrl = null;
      this.setStatus('error', MP_NOT_CONFIGURED_MESSAGE);
      return false;
    }

    const wsBase = toWebSocketBaseUrl(resolved);
    const wsUrl = `${wsBase}/room/${encodeURIComponent(normalizedCode)}`;

    this.teardownSocket(true);
    this.intentionalClose = false;
    this._roomCode = normalizedCode;
    this._memberId = null;
    this._rttMs = null;
    this._serverUrl = wsBase;
    this.setStatus('connecting', null);

    let socket: WebSocket;
    try {
      socket = new WebSocket(wsUrl);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unable to open WebSocket connection';
      this.setStatus('error', msg);
      return false;
    }

    this.ws = socket;

    socket.addEventListener('open', () => {
      if (this.ws !== socket) return;
      this.setStatus('connected', null);
      this.send({
        type: 'join_room',
        name: profile.name,
        heroId: profile.heroId,
        teamId: profile.teamId,
      });
      this.startPingLoop();
    });

    socket.addEventListener('message', (ev) => {
      if (this.ws !== socket) return;
      if (typeof ev.data !== 'string') return;
      let parsed: ServerMessage;
      try {
        parsed = JSON.parse(ev.data) as ServerMessage;
      } catch {
        return;
      }
      if (!parsed || typeof parsed.type !== 'string') return;

      if (parsed.type === 'pong') {
        if (typeof parsed.t === 'number' && Number.isFinite(parsed.t)) {
          const rtt = Math.max(0, Math.round(Date.now() - parsed.t));
          if (this._rttMs !== rtt) {
            this._rttMs = rtt;
            this.emitStatus();
          }
        }
      } else if (parsed.type === 'welcome') {
        this._memberId = parsed.memberId;
        this._roomCode = parsed.room.roomCode;
        this.emitStatus();
      } else if (parsed.type === 'error') {
        this._errorMessage = parsed.message;
        this.emitStatus();
      }

      for (const listener of this.messageListeners) {
        try {
          listener(parsed);
        } catch (err) {
          console.error('[MultiplayerClient] message listener error:', err);
        }
      }
    });

    socket.addEventListener('error', () => {
      if (this.ws !== socket) return;
      if (this.intentionalClose) return;
      this.setStatus('error', 'Connection error talking to multiplayer server');
    });

    socket.addEventListener('close', (ev) => {
      if (this.ws !== socket) return;
      this.stopPingLoop();
      this.ws = null;
      if (this.intentionalClose) {
        this.setStatus('disconnected', null);
        return;
      }
      const reason = ev.reason?.trim() || (ev.code === 1000 ? null : `Disconnected (code ${ev.code})`);
      if (this._status !== 'error') {
        this.setStatus(reason ? 'error' : 'disconnected', reason);
      }
    });

    return true;
  }

  /**
   * Send a typed `ClientMessage` over the open WebSocket. Returns `false` if not connected.
   */
  public send(msg: ClientMessage): boolean {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      return false;
    }
    try {
      this.ws.send(JSON.stringify(msg));
      return true;
    } catch {
      return false;
    }
  }

  /**
   * Register a typed listener for incoming `ServerMessage` payloads.
   * Returns an unsubscribe function.
   */
  public onMessage(listener: MpMessageListener): () => void {
    this.messageListeners.add(listener);
    return () => {
      this.messageListeners.delete(listener);
    };
  }

  /**
   * Register a listener for connection status and live `rttMs` updates.
   * Returns an unsubscribe function.
   */
  public onStatusChange(listener: MpStatusListener): () => void {
    this.statusListeners.add(listener);
    return () => {
      this.statusListeners.delete(listener);
    };
  }

  /**
   * Cleanly disconnect from the current room and release timers/socket handles.
   */
  public disconnect(reason = 'Client disconnected'): void {
    this.teardownSocket(true, reason);
    this._roomCode = null;
    this._memberId = null;
    this._rttMs = null;
    this.setStatus('disconnected', null);
  }

  /**
   * Alias for full cleanup when tearing down the page or controller.
   */
  public dispose(): void {
    this.disconnect('Disposed');
    this.messageListeners.clear();
    this.statusListeners.clear();
  }

  private startPingLoop(): void {
    this.stopPingLoop();
    this.send({ type: 'ping', t: Date.now() });
    this.pingTimer = setInterval(() => {
      if (!this.isConnected) {
        this.stopPingLoop();
        return;
      }
      this.send({ type: 'ping', t: Date.now() });
    }, PING_INTERVAL_MS);
  }

  private stopPingLoop(): void {
    if (this.pingTimer !== null) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
  }

  private teardownSocket(intentional: boolean, reason = 'Closed'): void {
    this.intentionalClose = intentional;
    this.stopPingLoop();
    const existing = this.ws;
    this.ws = null;
    if (existing) {
      try {
        if (
          existing.readyState === WebSocket.OPEN ||
          existing.readyState === WebSocket.CONNECTING
        ) {
          existing.close(1000, reason.slice(0, 120));
        }
      } catch {
        // Ignore close errors during teardown
      }
    }
  }

  private setStatus(status: MpConnectionStatus, errorMessage: string | null): void {
    this._status = status;
    this._errorMessage = errorMessage;
    this.emitStatus();
  }

  private emitStatus(): void {
    const snap = this.getStatusSnapshot();
    for (const listener of this.statusListeners) {
      try {
        listener(snap);
      } catch (err) {
        console.error('[MultiplayerClient] status listener error:', err);
      }
    }
  }
}

/**
 * GameRoom SQLite Durable Object — Authoritative Lobby & Match State Coordinator
 *
 * Uses Cloudflare Durable Objects SQLite storage + WebSocket Hibernation API
 * (`acceptWebSocket`, `webSocketMessage`, `webSocketClose`, `webSocketError`,
 * `alarm`) so private rooms stay free-tier compatible, cost zero CPU while idle,
 * and provide low-latency authoritative combat/world-claim resolution.
 */

import { DurableObject } from 'cloudflare:workers';
import {
  ClientMessage,
  DEFAULT_ROOM_SETTINGS,
  DamageEvent,
  ElimEvent,
  MP_BOT_CALLSIGNS,
  MP_DROP_RING_COUNT,
  MP_HERO_IDS,
  MP_MAX_PLAYERS,
  MP_STORM_ANCHOR_COUNT,
  MP_TEAM_IDS,
  MatchCombatantSpec,
  MatchEndPayload,
  MatchRankingEntry,
  MatchStartPayload,
  MpGameModeId,
  MpHeroId,
  RoomLobbySnapshot,
  RoomMember,
  RoomPhase,
  RoomSettings,
  ServerMessage,
  SyncedGroundLoot,
  TEAM_CONFIG,
  TeamId,
  assignSeededBotTiers,
  createSeededRng,
  isValidBotDifficulty,
  isValidGameModeId,
  isValidHeroId,
  isValidRarity,
  isValidRoomCode,
  isValidRoomFormat,
  isValidTeamId,
  isValidWeaponId,
  normalizeRoomCode,
  sanitizeDisplayName,
} from '../../src/net/protocol';
import type { Env } from './index';

interface SocketAttachment {
  memberId: string;
  roomCode: string;
}

interface RoomMetaRow {
  [key: string]: SqlStorageValue;
  room_code: string;
  phase: string;
  countdown_sec: number;
  host_id: string;
  settings_json: string;
}

interface RoomMemberRow {
  [key: string]: SqlStorageValue;
  id: string;
  name: string;
  hero_id: string;
  team_id: string;
  ready: number;
  is_host: number;
  joined_at: number;
}

interface AuthoritativeCombatant {
  id: string;
  name: string;
  isHuman: boolean;
  heroId: MpHeroId;
  teamId: TeamId | null;
  alive: boolean;
  health: number;
  shield: number;
  mana: number;
  eliminations: number;
  headshots: number;
  damageDealt: number;
  placement: number;
  eliminatedAtMs: number | null;
}

interface ActiveMatchState {
  matchId: string;
  seed: number;
  serverStartTimeMs: number;
  combatants: Map<string, AuthoritativeCombatant>;
  openedChests: Set<string>;
  claimedLoot: Set<string>;
  openedDrops: Set<string>;
  bikeOwners: Map<string, string>;
}

const MAX_SINGLE_HIT_DAMAGE = 220;
const MAX_STORM_TICK_DAMAGE = 60;
const IN_FLIGHT_TRADE_WINDOW_MS = 2000;
const COUNTDOWN_SECONDS = 3;

function getStartManaForMode(mode: MpGameModeId): number {
  switch (mode) {
    case 'blitz':
      return 60;
    case 'sniper_showdown':
      return 50;
    case 'campus_practice':
      return 100;
    case 'battle_royale':
    default:
      return 40;
  }
}

function clampFinite(value: unknown, min: number, max: number, fallback = 0): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) return fallback;
  return Math.min(max, Math.max(min, value));
}

function finiteOrZero(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function sanitizeSyncedLoot(rawList: unknown): SyncedGroundLoot[] {
  if (!Array.isArray(rawList)) return [];
  const result: SyncedGroundLoot[] = [];
  const cap = Math.min(rawList.length, 16);
  for (let i = 0; i < cap; i++) {
    const item = rawList[i] as Partial<SyncedGroundLoot> | null;
    if (!item || typeof item !== 'object') continue;
    if (typeof item.id !== 'string' || item.id.length === 0 || item.id.length > 64) continue;
    if (item.kind !== 'weapon' && item.kind !== 'item') continue;
    if (typeof item.itemId !== 'string' || item.itemId.length === 0 || item.itemId.length > 48) continue;
    if (!isValidRarity(item.rarity)) continue;
    result.push({
      id: item.id,
      kind: item.kind,
      itemId: item.itemId,
      rarity: item.rarity,
      count: typeof item.count === 'number' && Number.isFinite(item.count) ? Math.max(1, Math.min(99, Math.round(item.count))) : undefined,
      ammo: typeof item.ammo === 'number' && Number.isFinite(item.ammo) ? Math.max(0, Math.min(999, Math.round(item.ammo))) : undefined,
      x: finiteOrZero(item.x),
      y: finiteOrZero(item.y),
      z: finiteOrZero(item.z),
    });
  }
  return result;
}

export class GameRoom extends DurableObject<Env> {
  private roomCode = '';
  private phase: RoomPhase = 'lobby';
  private countdownSec = 0;
  private hostId = '';
  private settings: RoomSettings = { ...DEFAULT_ROOM_SETTINGS };
  private members = new Map<string, RoomMember>();
  private joinOrder = new Map<string, number>();
  private nextJoinSeq = 1;
  private match: ActiveMatchState | null = null;
  private closedSockets = new WeakSet<WebSocket>();

  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);

    ctx.blockConcurrencyWhile(async () => {
      this.initSchema();
      this.loadPersistedState();
    });
  }

  private initSchema(): void {
    this.ctx.storage.sql.exec(`
      CREATE TABLE IF NOT EXISTS room_meta (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        room_code TEXT NOT NULL,
        phase TEXT NOT NULL,
        countdown_sec INTEGER NOT NULL DEFAULT 0,
        host_id TEXT NOT NULL,
        settings_json TEXT NOT NULL,
        updated_at INTEGER NOT NULL
      );

      CREATE TABLE IF NOT EXISTS room_members (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        hero_id TEXT NOT NULL,
        team_id TEXT NOT NULL,
        ready INTEGER NOT NULL DEFAULT 0,
        is_host INTEGER NOT NULL DEFAULT 0,
        joined_at INTEGER NOT NULL
      );
    `);
  }

  private loadPersistedState(): void {
    const metaRows = this.ctx.storage.sql
      .exec<RoomMetaRow>(
        'SELECT room_code, phase, countdown_sec, host_id, settings_json FROM room_meta WHERE id = 1'
      )
      .toArray();

    if (metaRows.length > 0) {
      const row = metaRows[0];
      this.roomCode = row.room_code || '';
      const validPhase: RoomPhase =
        row.phase === 'lobby' ||
        row.phase === 'countdown' ||
        row.phase === 'playing' ||
        row.phase === 'ended'
          ? row.phase
          : 'lobby';
      this.phase = validPhase;
      this.countdownSec = Number(row.countdown_sec) || 0;
      this.hostId = row.host_id || '';
      try {
        const parsed = JSON.parse(row.settings_json) as Partial<RoomSettings>;
        this.settings = {
          mode: isValidGameModeId(parsed.mode) ? parsed.mode : DEFAULT_ROOM_SETTINGS.mode,
          format: isValidRoomFormat(parsed.format) ? parsed.format : DEFAULT_ROOM_SETTINGS.format,
          fillBots: typeof parsed.fillBots === 'boolean' ? parsed.fillBots : DEFAULT_ROOM_SETTINGS.fillBots,
          botDifficulty: isValidBotDifficulty(parsed.botDifficulty)
            ? parsed.botDifficulty
            : DEFAULT_ROOM_SETTINGS.botDifficulty,
          maxPlayers: Math.round(
            clampFinite(parsed.maxPlayers, 2, MP_MAX_PLAYERS, DEFAULT_ROOM_SETTINGS.maxPlayers)
          ),
        };
      } catch {
        this.settings = { ...DEFAULT_ROOM_SETTINGS };
      }
    }

    const activeMemberIds = new Set<string>();
    for (const ws of this.ctx.getWebSockets()) {
      const att = this.getAttachment(ws);
      if (att?.memberId) {
        activeMemberIds.add(att.memberId);
      }
    }

    const memberRows = this.ctx.storage.sql
      .exec<RoomMemberRow>(
        'SELECT id, name, hero_id, team_id, ready, is_host, joined_at FROM room_members ORDER BY joined_at ASC'
      )
      .toArray();

    for (const row of memberRows) {
      const connected = activeMemberIds.has(row.id);
      if (!connected && this.phase !== 'playing') {
        this.ctx.storage.sql.exec('DELETE FROM room_members WHERE id = ?', row.id);
        continue;
      }
      const member: RoomMember = {
        id: row.id,
        name: sanitizeDisplayName(row.name),
        heroId: isValidHeroId(row.hero_id) ? row.hero_id : 'gmail',
        teamId: isValidTeamId(row.team_id) ? row.team_id : 'blue',
        ready: row.ready === 1,
        isHost: row.id === this.hostId,
        connected,
      };
      this.members.set(member.id, member);
      this.joinOrder.set(member.id, this.nextJoinSeq++);
    }

    // If DO woke up with zero live sockets, ensure clean idle lobby state
    if (activeMemberIds.size === 0 && (this.phase === 'playing' || this.phase === 'countdown')) {
      this.phase = 'lobby';
      this.countdownSec = 0;
      this.hostId = '';
      this.match = null;
      this.members.clear();
      this.joinOrder.clear();
      this.ctx.storage.sql.exec('DELETE FROM room_members');
      this.persistMeta();
    }
  }

  private persistMeta(): void {
    this.ctx.storage.sql.exec(
      `INSERT INTO room_meta (id, room_code, phase, countdown_sec, host_id, settings_json, updated_at)
       VALUES (1, ?, ?, ?, ?, ?, ?)
       ON CONFLICT(id) DO UPDATE SET
         room_code = excluded.room_code,
         phase = excluded.phase,
         countdown_sec = excluded.countdown_sec,
         host_id = excluded.host_id,
         settings_json = excluded.settings_json,
         updated_at = excluded.updated_at`,
      this.roomCode,
      this.phase,
      this.countdownSec,
      this.hostId,
      JSON.stringify(this.settings),
      Date.now()
    );
  }

  private persistMember(member: RoomMember): void {
    const seq = this.joinOrder.get(member.id) ?? this.nextJoinSeq++;
    this.joinOrder.set(member.id, seq);
    this.ctx.storage.sql.exec(
      `INSERT INTO room_members (id, name, hero_id, team_id, ready, is_host, joined_at)
       VALUES (?, ?, ?, ?, ?, ?, ?)
       ON CONFLICT(id) DO UPDATE SET
         name = excluded.name,
         hero_id = excluded.hero_id,
         team_id = excluded.team_id,
         ready = excluded.ready,
         is_host = excluded.is_host`,
      member.id,
      member.name,
      member.heroId,
      member.teamId,
      member.ready ? 1 : 0,
      member.isHost ? 1 : 0,
      seq
    );
  }

  private deletePersistedMember(memberId: string): void {
    this.ctx.storage.sql.exec('DELETE FROM room_members WHERE id = ?', memberId);
  }

  private syncHostFlags(): void {
    for (const member of this.members.values()) {
      const shouldBeHost = member.id === this.hostId;
      if (member.isHost !== shouldBeHost) {
        member.isHost = shouldBeHost;
        this.persistMember(member);
      }
    }
  }

  private getAttachment(ws: WebSocket): SocketAttachment | null {
    try {
      const att = ws.deserializeAttachment() as SocketAttachment | null;
      if (att && typeof att.memberId === 'string') return att;
    } catch {
      // Ignore attachment read failure
    }
    return null;
  }

  private getOpenWebSockets(excludeWs?: WebSocket): WebSocket[] {
    const sockets: WebSocket[] = [];
    for (const ws of this.ctx.getWebSockets()) {
      if (ws === excludeWs) continue;
      if (this.closedSockets.has(ws)) continue;
      sockets.push(ws);
    }
    return sockets;
  }

  private sendTo(ws: WebSocket, msg: ServerMessage): void {
    if (this.closedSockets.has(ws)) return;
    try {
      ws.send(JSON.stringify(msg));
    } catch {
      // Ignore send failure on closing socket
    }
  }

  private broadcast(msg: ServerMessage, excludeWs?: WebSocket): void {
    const payload = JSON.stringify(msg);
    for (const ws of this.getOpenWebSockets(excludeWs)) {
      try {
        ws.send(payload);
      } catch {
        // Ignore individual broken socket
      }
    }
  }

  private getConnectedMembers(): RoomMember[] {
    return Array.from(this.members.values())
      .filter((m) => m.connected)
      .sort((a, b) => (this.joinOrder.get(a.id) ?? 0) - (this.joinOrder.get(b.id) ?? 0));
  }

  private getLobbySnapshot(): RoomLobbySnapshot {
    const sorted = Array.from(this.members.values()).sort(
      (a, b) => (this.joinOrder.get(a.id) ?? 0) - (this.joinOrder.get(b.id) ?? 0)
    );
    return {
      roomCode: this.roomCode,
      phase: this.phase,
      countdownSec: this.countdownSec,
      hostId: this.hostId,
      settings: { ...this.settings },
      members: sorted.map((m) => ({ ...m })),
    };
  }

  private pickAutoTeamId(): TeamId {
    let blueCount = 0;
    let redCount = 0;
    for (const m of this.members.values()) {
      if (!m.connected) continue;
      if (m.teamId === 'blue') blueCount += 1;
      else if (m.teamId === 'red') redCount += 1;
    }
    return blueCount <= redCount ? 'blue' : 'red';
  }

  /**
   * Resolve an actor ID for a gameplay message:
   * - Defaults to `senderId`.
   * - Allows `requestedId` ONLY if it matches `senderId`, OR `senderId === this.hostId`
   *   and `requestedId` is a known non-human AI bot in the active match.
   */
  private resolveAuthorizedActorId(senderId: string, requestedId?: string): string | null {
    if (!requestedId || requestedId === senderId) return senderId;
    if (senderId !== this.hostId || !this.match) return null;
    const combatant = this.match.combatants.get(requestedId);
    if (!combatant || combatant.isHuman) return null;
    return combatant.id;
  }

  // -------------------------------------------------------------------------
  // Durable Object HTTP -> WebSocket Upgrade Entry
  // -------------------------------------------------------------------------

  async fetch(request: Request): Promise<Response> {
    const upgradeHeader = request.headers.get('Upgrade');
    if (!upgradeHeader || upgradeHeader.toLowerCase() !== 'websocket') {
      return new Response('Expected WebSocket upgrade', { status: 426 });
    }

    const url = new URL(request.url);
    const match = /^\/room\/([^/]+)\/?$/i.exec(url.pathname);
    if (match) {
      let decoded = match[1];
      try {
        decoded = decodeURIComponent(decoded);
      } catch {
        // Keep raw
      }
      const code = normalizeRoomCode(decoded);
      if (isValidRoomCode(code) && this.roomCode !== code) {
        this.roomCode = code;
        this.persistMeta();
      }
    }

    const pair = new WebSocketPair();
    const [client, server] = Object.values(pair);

    const memberId = `p_${crypto.randomUUID().replace(/-/g, '').slice(0, 8)}`;
    this.ctx.acceptWebSocket(server);
    server.serializeAttachment({
      memberId,
      roomCode: this.roomCode,
    } satisfies SocketAttachment);

    return new Response(null, { status: 101, webSocket: client });
  }

  // -------------------------------------------------------------------------
  // WebSocket Hibernation Handlers
  // -------------------------------------------------------------------------

  async webSocketMessage(ws: WebSocket, message: string | ArrayBuffer): Promise<void> {
    if (typeof message !== 'string') return;
    let msg: ClientMessage;
    try {
      msg = JSON.parse(message) as ClientMessage;
    } catch {
      this.sendTo(ws, { type: 'error', code: 'BAD_JSON', message: 'Invalid JSON payload' });
      return;
    }
    if (!msg || typeof msg.type !== 'string') return;

    if (msg.type === 'ping') {
      this.sendTo(ws, {
        type: 'pong',
        t: typeof msg.t === 'number' && Number.isFinite(msg.t) ? msg.t : Date.now(),
        serverTimeMs: Date.now(),
      });
      return;
    }

    const att = this.getAttachment(ws);
    if (!att) return;
    const senderId = att.memberId;

    if (msg.type === 'join_room') {
      this.handleJoinRoom(ws, senderId, msg);
      return;
    }

    const member = this.members.get(senderId);
    if (!member || !member.connected) {
      this.sendTo(ws, { type: 'error', code: 'NOT_JOINED', message: 'Send join_room first' });
      return;
    }

    switch (msg.type) {
      case 'update_profile':
        this.handleUpdateProfile(member, msg);
        break;
      case 'update_settings':
        this.handleUpdateSettings(ws, senderId, msg.settings);
        break;
      case 'start_match':
        await this.handleStartMatch(ws, senderId);
        break;
      case 'return_lobby':
        await this.handleReturnLobby(ws, senderId);
        break;
      case 'player_state':
        this.handlePlayerState(ws, senderId, msg.state);
        break;
      case 'bot_batch':
        this.handleBotBatch(ws, senderId, msg.bots);
        break;
      case 'fire_fx':
        this.handleFireFx(ws, senderId, msg.event);
        break;
      case 'hit_report':
        this.handleHitReport(senderId, msg);
        break;
      case 'vitals_sync':
        this.handleVitalsSync(senderId, msg);
        break;
      case 'storm_damage':
        this.handleStormDamage(senderId, msg);
        break;
      case 'ult_cast':
        this.handleUltCast(ws, senderId, msg.event);
        break;
      case 'chest_open':
        this.handleChestOpen(senderId, msg);
        break;
      case 'loot_claim':
        this.handleLootClaim(senderId, msg);
        break;
      case 'loot_spawn':
        this.handleLootSpawn(ws, msg.items);
        break;
      case 'supply_drop_open':
        this.handleSupplyDropOpen(senderId, msg);
        break;
      case 'bike_claim':
        this.handleBikeClaim(senderId, msg);
        break;
      case 'bike_release':
        this.handleBikeRelease(senderId, msg);
        break;
      case 'bike_bell':
        this.handleBikeBell(ws, senderId, msg);
        break;
      case 'techstop_upgrade':
        this.handleTechStopUpgrade(ws, senderId, msg);
        break;
      default:
        break;
    }
  }

  async webSocketClose(
    ws: WebSocket,
    code: number,
    reason: string,
    _wasClean: boolean
  ): Promise<void> {
    await this.handleSocketDisconnect(ws);
    try {
      ws.close(code || 1000, reason || 'Closed');
    } catch {
      // Already closed
    }
  }

  async webSocketError(ws: WebSocket, _error: unknown): Promise<void> {
    await this.handleSocketDisconnect(ws);
    try {
      ws.close(1011, 'Socket error');
    } catch {
      // Already closed
    }
  }

  // -------------------------------------------------------------------------
  // Durable Object Alarm — 3-Second Synced Match Countdown
  // -------------------------------------------------------------------------

  async alarm(): Promise<void> {
    if (this.phase !== 'countdown') return;

    const connected = this.getConnectedMembers();
    if (connected.length === 0) {
      this.phase = 'lobby';
      this.countdownSec = 0;
      this.persistMeta();
      return;
    }

    this.countdownSec -= 1;

    if (this.countdownSec > 0) {
      this.persistMeta();
      this.broadcast({ type: 'countdown', seconds: this.countdownSec });
      this.broadcast({ type: 'room_state', room: this.getLobbySnapshot() });
      await this.ctx.storage.setAlarm(Date.now() + 1000);
      return;
    }

    this.launchMatch();
  }

  // -------------------------------------------------------------------------
  // Lobby Handlers
  // -------------------------------------------------------------------------

  private handleJoinRoom(
    ws: WebSocket,
    memberId: string,
    msg: Extract<ClientMessage, { type: 'join_room' }>
  ): void {
    // Auto-reset an empty ended room back into a clean lobby for new players
    if (this.phase === 'ended' && this.getConnectedMembers().length === 0) {
      this.phase = 'lobby';
      this.countdownSec = 0;
      this.match = null;
      this.members.clear();
      this.joinOrder.clear();
      this.ctx.storage.sql.exec('DELETE FROM room_members');
      this.hostId = '';
      this.persistMeta();
    }

    if (this.phase === 'playing' || this.phase === 'countdown') {
      this.sendTo(ws, {
        type: 'error',
        code: 'MATCH_IN_PROGRESS',
        message: 'A match is already in progress in this room.',
      });
      this.closedSockets.add(ws);
      try {
        ws.close(4002, 'Match in progress');
      } catch {
        // Ignore
      }
      return;
    }

    const connectedCount = this.getConnectedMembers().filter((m) => m.id !== memberId).length;
    if (connectedCount >= MP_MAX_PLAYERS) {
      this.sendTo(ws, {
        type: 'error',
        code: 'ROOM_FULL',
        message: `Room is full (${MP_MAX_PLAYERS}/${MP_MAX_PLAYERS} players).`,
      });
      this.closedSockets.add(ws);
      try {
        ws.close(4001, 'Room full');
      } catch {
        // Ignore
      }
      return;
    }

    const existing = this.members.get(memberId);
    const defaultName = `Player ${connectedCount + 1}`;
    const name = sanitizeDisplayName(msg.name, existing?.name ?? defaultName);
    const heroId: MpHeroId = isValidHeroId(msg.heroId) ? msg.heroId : existing?.heroId ?? 'gmail';
    const teamId: TeamId = isValidTeamId(msg.teamId)
      ? msg.teamId
      : existing?.teamId ?? this.pickAutoTeamId();

    const currentHost = this.hostId ? this.members.get(this.hostId) : null;
    if (!currentHost || !currentHost.connected) {
      this.hostId = memberId;
    }

    const member: RoomMember = {
      id: memberId,
      name,
      heroId,
      teamId,
      ready: existing?.ready ?? false,
      isHost: memberId === this.hostId,
      connected: true,
    };

    this.members.set(memberId, member);
    this.syncHostFlags();
    this.persistMember(member);
    this.persistMeta();

    const snapshot = this.getLobbySnapshot();
    this.sendTo(ws, { type: 'welcome', memberId, room: snapshot });
    this.broadcast({ type: 'room_state', room: snapshot }, ws);
  }

  private handleUpdateProfile(
    member: RoomMember,
    msg: Extract<ClientMessage, { type: 'update_profile' }>
  ): void {
    if (this.phase === 'playing') return;

    let changed = false;
    if (typeof msg.name === 'string') {
      const sanitized = sanitizeDisplayName(msg.name, member.name);
      if (sanitized !== member.name) {
        member.name = sanitized;
        changed = true;
      }
    }
    if (msg.heroId !== undefined && isValidHeroId(msg.heroId) && msg.heroId !== member.heroId) {
      member.heroId = msg.heroId;
      changed = true;
    }
    if (msg.teamId !== undefined && isValidTeamId(msg.teamId) && msg.teamId !== member.teamId) {
      member.teamId = msg.teamId;
      changed = true;
    }
    if (typeof msg.ready === 'boolean' && msg.ready !== member.ready) {
      member.ready = msg.ready;
      changed = true;
    }

    if (changed) {
      this.persistMember(member);
      this.broadcast({ type: 'room_state', room: this.getLobbySnapshot() });
    }
  }

  private handleUpdateSettings(
    ws: WebSocket,
    senderId: string,
    patch: Partial<RoomSettings>
  ): void {
    if (senderId !== this.hostId) {
      this.sendTo(ws, {
        type: 'error',
        code: 'NOT_HOST',
        message: 'Only the room host can update match settings.',
      });
      return;
    }
    if (this.phase !== 'lobby') {
      this.sendTo(ws, {
        type: 'error',
        code: 'INVALID_PHASE',
        message: 'Settings can only be changed in the lobby.',
      });
      return;
    }
    if (!patch || typeof patch !== 'object') return;

    if (patch.mode !== undefined && isValidGameModeId(patch.mode)) {
      this.settings.mode = patch.mode;
    }
    if (patch.format !== undefined && isValidRoomFormat(patch.format)) {
      this.settings.format = patch.format;
    }
    if (typeof patch.fillBots === 'boolean') {
      this.settings.fillBots = patch.fillBots;
    }
    if (patch.botDifficulty !== undefined && isValidBotDifficulty(patch.botDifficulty)) {
      this.settings.botDifficulty = patch.botDifficulty;
    }
    if (patch.maxPlayers !== undefined) {
      this.settings.maxPlayers = Math.round(
        clampFinite(patch.maxPlayers, 2, MP_MAX_PLAYERS, this.settings.maxPlayers)
      );
    }

    this.persistMeta();
    this.broadcast({ type: 'room_state', room: this.getLobbySnapshot() });
  }

  private async handleStartMatch(ws: WebSocket, senderId: string): Promise<void> {
    if (senderId !== this.hostId) {
      this.sendTo(ws, {
        type: 'error',
        code: 'NOT_HOST',
        message: 'Only the room host can start the match.',
      });
      return;
    }
    if (this.phase !== 'lobby') {
      this.sendTo(ws, {
        type: 'error',
        code: 'INVALID_PHASE',
        message: 'Match can only be started from the lobby.',
      });
      return;
    }

    const connected = this.getConnectedMembers();
    if (connected.length === 0) return;

    if (!this.settings.fillBots && connected.length < 2) {
      this.sendTo(ws, {
        type: 'error',
        code: 'MIN_PLAYERS',
        message: 'Need at least 2 players to start without AI bots (or enable Fill with AI Bots).',
      });
      return;
    }

    if (!this.settings.fillBots && this.settings.format === 'teams') {
      const distinctTeams = new Set(connected.map((m) => m.teamId));
      if (distinctTeams.size < 2) {
        this.sendTo(ws, {
          type: 'error',
          code: 'MIN_TEAMS',
          message: 'Assign players to at least 2 teams (or enable AI bots) to start a Teams match.',
        });
        return;
      }
    }

    this.phase = 'countdown';
    this.countdownSec = COUNTDOWN_SECONDS;
    this.persistMeta();

    this.broadcast({ type: 'room_state', room: this.getLobbySnapshot() });
    this.broadcast({ type: 'countdown', seconds: this.countdownSec });
    await this.ctx.storage.setAlarm(Date.now() + 1000);
  }

  private async handleReturnLobby(ws: WebSocket, senderId: string): Promise<void> {
    if (this.phase === 'lobby') {
      this.sendTo(ws, { type: 'room_state', room: this.getLobbySnapshot() });
      return;
    }

    if ((this.phase === 'playing' || this.phase === 'countdown') && senderId !== this.hostId) {
      this.sendTo(ws, {
        type: 'error',
        code: 'NOT_HOST',
        message: 'Only the host can cancel an active match back to the lobby.',
      });
      return;
    }

    await this.ctx.storage.deleteAlarm();
    this.phase = 'lobby';
    this.countdownSec = 0;
    this.match = null;

    // Prune disconnected members and reset ready state for instant rematch
    for (const [id, member] of this.members.entries()) {
      if (!member.connected) {
        this.members.delete(id);
        this.joinOrder.delete(id);
        this.deletePersistedMember(id);
      } else {
        member.ready = false;
        this.persistMember(member);
      }
    }

    // Ensure host is still valid
    const connected = this.getConnectedMembers();
    if (connected.length > 0 && (!this.hostId || !this.members.get(this.hostId)?.connected)) {
      this.hostId = connected[0].id;
    }
    this.syncHostFlags();
    this.persistMeta();

    this.broadcast({ type: 'room_state', room: this.getLobbySnapshot() });
  }

  // -------------------------------------------------------------------------
  // Match Launch & Roster Synthesis
  // -------------------------------------------------------------------------

  private launchMatch(): void {
    const connectedHumans = this.getConnectedMembers();
    if (connectedHumans.length === 0) {
      this.phase = 'lobby';
      this.countdownSec = 0;
      this.persistMeta();
      return;
    }

    const seed =
      ((Math.floor(Math.random() * 0x7fffffff) ^ (Date.now() & 0x7fffffff)) >>> 0) || 1;
    const rng = createSeededRng(seed);

    const stormAnchorIndex = Math.floor(rng() * MP_STORM_ANCHOR_COUNT);
    const stormOffsetX = Number(((rng() - 0.5) * 24).toFixed(2));
    const stormOffsetZ = Number(((rng() - 0.5) * 24).toFixed(2));

    // Deterministic Fisher-Yates shuffle over the 20 glider drop ring slots
    const dropIndices = Array.from({ length: MP_DROP_RING_COUNT }, (_, i) => i);
    for (let i = dropIndices.length - 1; i > 0; i--) {
      const j = Math.floor(rng() * (i + 1));
      [dropIndices[i], dropIndices[j]] = [dropIndices[j], dropIndices[i]];
    }

    const isTeams = this.settings.format === 'teams';
    const combatants: MatchCombatantSpec[] = [];

    for (let i = 0; i < connectedHumans.length; i++) {
      const m = connectedHumans[i];
      combatants.push({
        id: m.id,
        name: m.name,
        isHuman: true,
        heroId: m.heroId,
        teamId: isTeams ? m.teamId : null,
        dropIndex: dropIndices[i % dropIndices.length],
      });
    }

    if (this.settings.fillBots) {
      const targetTotal = Math.max(
        connectedHumans.length,
        Math.min(MP_MAX_PLAYERS, this.settings.maxPlayers)
      );
      const botCount = Math.max(0, targetTotal - connectedHumans.length);
      const botTiers = assignSeededBotTiers(this.settings.botDifficulty, botCount, rng);

      // Build balanced active team list when in Teams mode
      const activeTeams: TeamId[] = [];
      const teamCounts = new Map<TeamId, number>();
      if (isTeams) {
        for (const t of MP_TEAM_IDS) {
          if (connectedHumans.some((h) => h.teamId === t)) {
            activeTeams.push(t);
            teamCounts.set(t, connectedHumans.filter((h) => h.teamId === t).length);
          }
        }
        // Guarantee at least 2 opposing teams so a squad of friends on Blue faces Red bots
        while (activeTeams.length < 2) {
          const nextTeam = MP_TEAM_IDS.find((t) => !activeTeams.includes(t));
          if (!nextTeam) break;
          activeTeams.push(nextTeam);
          teamCounts.set(nextTeam, 0);
        }
      }

      const nameCounters: Record<MpHeroId, number> = {
        gmail: 0,
        drive: 0,
        calendar: 0,
        chat: 0,
        slides: 0,
        docs: 0,
      };

      for (let i = 0; i < botCount; i++) {
        const heroId = MP_HERO_IDS[i % MP_HERO_IDS.length];
        const callsigns = MP_BOT_CALLSIGNS[heroId];
        const nIdx = nameCounters[heroId]++;
        const botName =
          callsigns[nIdx % callsigns.length] + (nIdx >= callsigns.length ? ` ${nIdx + 1}` : '');

        let assignedTeam: TeamId | null = null;
        if (isTeams && activeTeams.length > 0) {
          let bestTeam = activeTeams[0];
          let lowestCount = teamCounts.get(bestTeam) ?? 0;
          for (let tIdx = 1; tIdx < activeTeams.length; tIdx++) {
            const candidate = activeTeams[tIdx];
            const c = teamCounts.get(candidate) ?? 0;
            if (c < lowestCount) {
              bestTeam = candidate;
              lowestCount = c;
            }
          }
          assignedTeam = bestTeam;
          teamCounts.set(bestTeam, lowestCount + 1);
        }

        const slotIdx = connectedHumans.length + i;
        combatants.push({
          id: `bot_${i + 1}`,
          name: botName,
          isHuman: false,
          heroId,
          teamId: assignedTeam,
          dropIndex: dropIndices[slotIdx % dropIndices.length],
          botTier: botTiers[i],
        });
      }
    }

    const startMana = getStartManaForMode(this.settings.mode);
    const authMap = new Map<string, AuthoritativeCombatant>();
    for (const c of combatants) {
      authMap.set(c.id, {
        id: c.id,
        name: c.name,
        isHuman: c.isHuman,
        heroId: c.heroId,
        teamId: c.teamId,
        alive: true,
        health: 100,
        shield: 0,
        mana: startMana,
        eliminations: 0,
        headshots: 0,
        damageDealt: 0,
        placement: 0,
        eliminatedAtMs: null,
      });
    }

    const matchId = `m_${crypto.randomUUID().replace(/-/g, '').slice(0, 10)}`;
    const serverStartTimeMs = Date.now();

    this.match = {
      matchId,
      seed,
      serverStartTimeMs,
      combatants: authMap,
      openedChests: new Set(),
      claimedLoot: new Set(),
      openedDrops: new Set(),
      bikeOwners: new Map(),
    };

    this.phase = 'playing';
    this.countdownSec = 0;
    this.persistMeta();

    const payload: MatchStartPayload = {
      matchId,
      seed,
      settings: { ...this.settings },
      hostId: this.hostId,
      combatants,
      stormAnchorIndex,
      stormOffsetX,
      stormOffsetZ,
      serverStartTimeMs,
    };

    this.broadcast({ type: 'room_state', room: this.getLobbySnapshot() });
    this.broadcast({ type: 'match_start', match: payload });
  }

  // -------------------------------------------------------------------------
  // Real-Time Match Relay & Authoritative Combat Handlers
  // -------------------------------------------------------------------------

  private handlePlayerState(
    ws: WebSocket,
    senderId: string,
    state: Extract<ClientMessage, { type: 'player_state' }>['state']
  ): void {
    if (this.phase !== 'playing' || !this.match || !state || typeof state !== 'object') return;
    const combatant = this.match.combatants.get(senderId);
    if (!combatant || !combatant.alive) return;

    this.broadcast(
      {
        type: 'peer_state',
        state: {
          id: senderId,
          x: finiteOrZero(state.x),
          y: finiteOrZero(state.y),
          z: finiteOrZero(state.z),
          vx: finiteOrZero(state.vx),
          vy: finiteOrZero(state.vy),
          vz: finiteOrZero(state.vz),
          yaw: finiteOrZero(state.yaw),
          pitch: finiteOrZero(state.pitch),
          flags: typeof state.flags === 'number' ? state.flags | 0 : 0,
          weaponId: state.weaponId && isValidWeaponId(state.weaponId) ? state.weaponId : null,
          weaponRarity: state.weaponRarity && isValidRarity(state.weaponRarity) ? state.weaponRarity : null,
          bikeId: typeof state.bikeId === 'string' ? state.bikeId.slice(0, 48) : null,
          bikeSteer: typeof state.bikeSteer === 'number' && Number.isFinite(state.bikeSteer) ? state.bikeSteer : undefined,
          bikeLean: typeof state.bikeLean === 'number' && Number.isFinite(state.bikeLean) ? state.bikeLean : undefined,
          bikeSpeed: typeof state.bikeSpeed === 'number' && Number.isFinite(state.bikeSpeed) ? state.bikeSpeed : undefined,
        },
      },
      ws
    );
  }

  private handleBotBatch(
    ws: WebSocket,
    senderId: string,
    bots: Extract<ClientMessage, { type: 'bot_batch' }>['bots']
  ): void {
    if (this.phase !== 'playing' || !this.match) return;
    if (senderId !== this.hostId) return;
    if (!Array.isArray(bots) || bots.length === 0) return;

    const sanitized = [];
    const cap = Math.min(bots.length, MP_MAX_PLAYERS);
    for (let i = 0; i < cap; i++) {
      const b = bots[i];
      if (!b || typeof b.id !== 'string') continue;
      const auth = this.match.combatants.get(b.id);
      if (!auth || auth.isHuman) continue;
      sanitized.push({
        id: b.id,
        x: finiteOrZero(b.x),
        y: finiteOrZero(b.y),
        z: finiteOrZero(b.z),
        vx: finiteOrZero(b.vx),
        vz: finiteOrZero(b.vz),
        yaw: finiteOrZero(b.yaw),
        pitch: finiteOrZero(b.pitch),
        flags: typeof b.flags === 'number' ? b.flags | 0 : 0,
        // Stamp server-authoritative vitals so peers never diverge from damage_event
        hp: auth.health,
        sh: auth.shield,
        alive: auth.alive,
        weaponId: b.weaponId && isValidWeaponId(b.weaponId) ? b.weaponId : null,
        weaponRarity: b.weaponRarity && isValidRarity(b.weaponRarity) ? b.weaponRarity : null,
      });
    }

    if (sanitized.length > 0) {
      this.broadcast({ type: 'bot_batch', bots: sanitized }, ws);
    }
  }

  private handleFireFx(
    ws: WebSocket,
    senderId: string,
    event: Extract<ClientMessage, { type: 'fire_fx' }>['event']
  ): void {
    if (this.phase !== 'playing' || !this.match || !event || typeof event !== 'object') return;
    const shooterId = this.resolveAuthorizedActorId(senderId, event.shooterId);
    if (!shooterId || !isValidWeaponId(event.weaponId)) return;

    this.broadcast(
      {
        type: 'fire_fx',
        event: {
          shooterId,
          weaponId: event.weaponId,
          ox: finiteOrZero(event.ox),
          oy: finiteOrZero(event.oy),
          oz: finiteOrZero(event.oz),
          endX: finiteOrZero(event.endX),
          endY: finiteOrZero(event.endY),
          endZ: finiteOrZero(event.endZ),
          isExplosive: Boolean(event.isExplosive),
          explosionRadius:
            typeof event.explosionRadius === 'number' && Number.isFinite(event.explosionRadius)
              ? clampFinite(event.explosionRadius, 0, 25, 0)
              : undefined,
        },
      },
      ws
    );
  }

  private handleUltCast(
    ws: WebSocket,
    senderId: string,
    event: Extract<ClientMessage, { type: 'ult_cast' }>['event']
  ): void {
    if (this.phase !== 'playing' || !this.match || !event || typeof event !== 'object') return;
    const casterId = this.resolveAuthorizedActorId(senderId, event.casterId);
    if (!casterId || !isValidHeroId(event.heroId)) return;

    this.broadcast(
      {
        type: 'ult_cast',
        event: {
          casterId,
          heroId: event.heroId,
          x: finiteOrZero(event.x),
          y: finiteOrZero(event.y),
          z: finiteOrZero(event.z),
          yaw: finiteOrZero(event.yaw),
          pitch: finiteOrZero(event.pitch),
          targetX:
            typeof event.targetX === 'number' && Number.isFinite(event.targetX)
              ? event.targetX
              : undefined,
          targetY:
            typeof event.targetY === 'number' && Number.isFinite(event.targetY)
              ? event.targetY
              : undefined,
          targetZ:
            typeof event.targetZ === 'number' && Number.isFinite(event.targetZ)
              ? event.targetZ
              : undefined,
        },
      },
      ws
    );
  }

  private handleHitReport(
    senderId: string,
    msg: Extract<ClientMessage, { type: 'hit_report' }>
  ): void {
    if (this.phase !== 'playing' || !this.match) return;
    if (typeof msg.targetId !== 'string' || !msg.targetId) return;

    const attackerId = this.resolveAuthorizedActorId(senderId, msg.attackerId);
    if (!attackerId) return;

    const victim = this.match.combatants.get(msg.targetId);
    const attacker = this.match.combatants.get(attackerId);
    if (!victim || !victim.alive || !attacker) return;

    // Validate attacker is alive or died within the brief in-flight projectile trade window
    if (!attacker.alive) {
      const diedAgo = attacker.eliminatedAtMs ? Date.now() - attacker.eliminatedAtMs : Infinity;
      if (diedAgo > IN_FLIGHT_TRADE_WINDOW_MS) return;
    }

    // Sanity-clamp single hit damage <= 220
    const amount = Math.round(clampFinite(msg.amount, 0, MAX_SINGLE_HIT_DAMAGE, 0));
    if (amount <= 0) return;

    // AUTHORITATIVE FRIENDLY-FIRE GUARD: block same-team damage in Teams mode
    if (
      this.settings.format === 'teams' &&
      attacker.teamId !== null &&
      victim.teamId !== null &&
      attacker.teamId === victim.teamId &&
      attacker.id !== victim.id
    ) {
      return;
    }

    // Shield absorbs damage before Health
    const hadShield = victim.shield > 0;
    const shieldAbsorb = Math.min(victim.shield, amount);
    const healthDmg = amount - shieldAbsorb;
    victim.shield = Math.max(0, victim.shield - shieldAbsorb);
    victim.health = Math.max(0, victim.health - healthDmg);
    const shieldBroken = hadShield && victim.shield <= 0;

    const headshot = Boolean(msg.headshot);
    const isUltimate = Boolean(msg.isUltimate);
    const weaponName =
      typeof msg.weaponName === 'string' && msg.weaponName.trim().length > 0
        ? msg.weaponName.trim().slice(0, 40)
        : 'Weapon';

    if (attacker.id !== victim.id) {
      attacker.damageDealt += amount;
      if (headshot) {
        attacker.headshots += 1;
      }
    }

    const damageEvent: DamageEvent = {
      targetId: victim.id,
      attackerId: attacker.id,
      amount,
      newHealth: victim.health,
      newShield: victim.shield,
      shieldBroken,
      headshot,
      weaponName,
      isUltimate,
      isStorm: false,
      hitX: finiteOrZero(msg.hitX),
      hitY: finiteOrZero(msg.hitY),
      hitZ: finiteOrZero(msg.hitZ),
    };

    this.broadcast({ type: 'damage_event', event: damageEvent });

    if (victim.health <= 0) {
      this.eliminateCombatant(
        victim,
        attacker.id !== victim.id ? attacker : null,
        weaponName,
        headshot,
        isUltimate,
        false
      );
    }
  }

  private handleVitalsSync(
    senderId: string,
    msg: Extract<ClientMessage, { type: 'vitals_sync' }>
  ): void {
    if (this.phase !== 'playing' || !this.match) return;
    const combatantId = this.resolveAuthorizedActorId(senderId, msg.combatantId);
    if (!combatantId) return;

    const combatant = this.match.combatants.get(combatantId);
    if (!combatant || !combatant.alive) return;

    // Clamp healed/synced vitals; alive combatants keep health in [1, 100], shield in [0, 100]
    combatant.health = Math.round(clampFinite(msg.health, 1, 100, combatant.health));
    combatant.shield = Math.round(clampFinite(msg.shield, 0, 100, combatant.shield));
    if (msg.mana !== undefined) {
      combatant.mana = Math.round(clampFinite(msg.mana, 0, 100, combatant.mana));
    }

    this.broadcast({
      type: 'vitals_update',
      combatantId: combatant.id,
      health: combatant.health,
      shield: combatant.shield,
      mana: msg.mana !== undefined ? combatant.mana : undefined,
    });
  }

  private handleStormDamage(
    senderId: string,
    msg: Extract<ClientMessage, { type: 'storm_damage' }>
  ): void {
    if (this.phase !== 'playing' || !this.match) return;
    const targetId = this.resolveAuthorizedActorId(senderId, msg.targetId);
    if (!targetId) return;

    const victim = this.match.combatants.get(targetId);
    if (!victim || !victim.alive) return;

    const amount = Math.round(clampFinite(msg.amount, 0, MAX_STORM_TICK_DAMAGE, 0));
    if (amount <= 0) return;

    // Storm bypasses shields directly onto health
    victim.health = Math.max(0, victim.health - amount);

    this.broadcast({
      type: 'damage_event',
      event: {
        targetId: victim.id,
        attackerId: null,
        amount,
        newHealth: victim.health,
        newShield: victim.shield,
        shieldBroken: false,
        headshot: false,
        weaponName: 'The Storm',
        isUltimate: false,
        isStorm: true,
        hitX: 0,
        hitY: 0,
        hitZ: 0,
      },
    });

    if (victim.health <= 0) {
      this.eliminateCombatant(victim, null, 'The Storm', false, false, true);
    }
  }

  private eliminateCombatant(
    victim: AuthoritativeCombatant,
    killer: AuthoritativeCombatant | null,
    weaponName: string,
    headshot: boolean,
    isUltimate: boolean,
    isStorm: boolean
  ): void {
    if (!this.match || !victim.alive) return;

    let aliveBefore = 0;
    for (const c of this.match.combatants.values()) {
      if (c.alive) aliveBefore += 1;
    }

    victim.alive = false;
    victim.health = 0;
    victim.shield = 0;
    victim.placement = aliveBefore;
    victim.eliminatedAtMs = Date.now();

    // Release any GBike owned by the eliminated combatant
    this.releaseBikesOwnedBy(victim.id);

    if (killer && killer.id !== victim.id) {
      killer.eliminations += 1;
    }

    const aliveCombatants: AuthoritativeCombatant[] = [];
    const aliveTeamIds = new Set<TeamId>();
    for (const c of this.match.combatants.values()) {
      if (c.alive) {
        aliveCombatants.push(c);
        if (c.teamId) aliveTeamIds.add(c.teamId);
      }
    }

    const aliveCount = aliveCombatants.length;
    const aliveTeams = this.settings.format === 'teams' ? aliveTeamIds.size : aliveCount;

    const elimEvent: ElimEvent = {
      victimId: victim.id,
      killerId: killer && killer.id !== victim.id ? killer.id : null,
      weaponName,
      headshot,
      isUltimate,
      isStorm,
      placement: victim.placement,
      aliveCount,
      aliveTeams,
    };

    this.broadcast({ type: 'elim_event', event: elimEvent });

    const matchFinished =
      this.settings.format === 'teams' ? aliveTeams <= 1 : aliveCount <= 1;

    if (matchFinished) {
      this.finalizeMatch(aliveCombatants);
    }
  }

  private finalizeMatch(survivors: AuthoritativeCombatant[]): void {
    if (!this.match) return;

    for (const s of survivors) {
      s.placement = 1;
    }

    const isTeams = this.settings.format === 'teams';
    let winnerId: string | null = null;
    let winnerTeamId: TeamId | null = null;
    let winnerName = 'No Winner';

    if (isTeams) {
      winnerTeamId = survivors[0]?.teamId ?? null;
      if (winnerTeamId) {
        // Assign placement = 1 to all members of the winning team (including eliminated teammates)
        for (const c of this.match.combatants.values()) {
          if (c.teamId === winnerTeamId) {
            c.placement = 1;
          }
        }
        const mvp = [...survivors].sort(
          (a, b) => b.eliminations - a.eliminations || b.damageDealt - a.damageDealt
        )[0];
        winnerId = mvp?.id ?? null;
        winnerName = `Team ${TEAM_CONFIG[winnerTeamId].label}`;
      }
    } else {
      const winner = survivors[0] ?? null;
      winnerId = winner?.id ?? null;
      winnerName = winner?.name ?? 'No Winner';
    }

    const rankings: MatchRankingEntry[] = Array.from(this.match.combatants.values())
      .map((c) => ({
        id: c.id,
        name: c.name,
        teamId: c.teamId,
        placement: c.placement > 0 ? c.placement : this.match!.combatants.size,
        eliminations: c.eliminations,
        headshots: c.headshots,
        damageDealt: c.damageDealt,
        isHuman: c.isHuman,
      }))
      .sort(
        (a, b) =>
          a.placement - b.placement ||
          b.eliminations - a.eliminations ||
          b.damageDealt - a.damageDealt
      );

    const survivedSeconds = Math.max(
      0,
      Math.round((Date.now() - this.match.serverStartTimeMs) / 1000)
    );

    const result: MatchEndPayload = {
      winnerId,
      winnerTeamId,
      winnerName,
      totalPlayers: this.match.combatants.size,
      survivedSeconds,
      rankings,
    };

    this.phase = 'ended';
    this.persistMeta();

    this.broadcast({ type: 'match_end', result });
    this.broadcast({ type: 'room_state', room: this.getLobbySnapshot() });
  }

  // -------------------------------------------------------------------------
  // Authoritative World Claims (First-Come-First-Served)
  // -------------------------------------------------------------------------

  private handleChestOpen(
    senderId: string,
    msg: Extract<ClientMessage, { type: 'chest_open' }>
  ): void {
    if (this.phase !== 'playing' || !this.match) return;
    if (typeof msg.chestId !== 'string' || msg.chestId.length === 0 || msg.chestId.length > 64) {
      return;
    }

    const openerId = this.resolveAuthorizedActorId(senderId, msg.openerId);
    if (!openerId) return;

    // First-come-first-served guard
    if (this.match.openedChests.has(msg.chestId)) return;
    this.match.openedChests.add(msg.chestId);

    const loot = sanitizeSyncedLoot(msg.loot);
    this.broadcast({
      type: 'chest_opened',
      chestId: msg.chestId,
      openerId,
      loot,
    });
  }

  private handleLootClaim(
    senderId: string,
    msg: Extract<ClientMessage, { type: 'loot_claim' }>
  ): void {
    if (this.phase !== 'playing' || !this.match) return;
    if (typeof msg.lootId !== 'string' || msg.lootId.length === 0 || msg.lootId.length > 64) {
      return;
    }

    const claimerId = this.resolveAuthorizedActorId(senderId, msg.claimerId);
    if (!claimerId) return;

    // First-come-first-served guard
    if (this.match.claimedLoot.has(msg.lootId)) return;
    this.match.claimedLoot.add(msg.lootId);

    this.broadcast({
      type: 'loot_claimed',
      lootId: msg.lootId,
      claimerId,
    });
  }

  private handleLootSpawn(ws: WebSocket, items: SyncedGroundLoot[]): void {
    if (this.phase !== 'playing' || !this.match) return;
    const sanitized = sanitizeSyncedLoot(items);
    if (sanitized.length === 0) return;

    this.broadcast({ type: 'loot_spawned', items: sanitized }, ws);
  }

  private handleSupplyDropOpen(
    senderId: string,
    msg: Extract<ClientMessage, { type: 'supply_drop_open' }>
  ): void {
    if (this.phase !== 'playing' || !this.match) return;
    if (typeof msg.dropId !== 'string' || msg.dropId.length === 0 || msg.dropId.length > 64) {
      return;
    }

    const openerId = this.resolveAuthorizedActorId(senderId, msg.openerId);
    if (!openerId) return;

    // First-come-first-served guard
    if (this.match.openedDrops.has(msg.dropId)) return;
    this.match.openedDrops.add(msg.dropId);

    const loot = sanitizeSyncedLoot(msg.loot);
    this.broadcast({
      type: 'supply_drop_opened',
      dropId: msg.dropId,
      openerId,
      loot,
    });
  }

  private handleBikeClaim(
    senderId: string,
    msg: Extract<ClientMessage, { type: 'bike_claim' }>
  ): void {
    if (this.phase !== 'playing' || !this.match) return;
    if (typeof msg.bikeId !== 'string' || msg.bikeId.length === 0 || msg.bikeId.length > 64) {
      return;
    }

    const riderId = this.resolveAuthorizedActorId(senderId, msg.riderId);
    if (!riderId) return;

    const rider = this.match.combatants.get(riderId);
    if (!rider || !rider.alive) return;

    // First-come-first-served guard: reject if another rider already owns this bike
    const existingOwner = this.match.bikeOwners.get(msg.bikeId);
    if (existingOwner && existingOwner !== riderId) return;
    if (existingOwner === riderId) return;

    // Release any previous bike this rider owned
    this.releaseBikesOwnedBy(riderId);

    this.match.bikeOwners.set(msg.bikeId, riderId);
    this.broadcast({
      type: 'bike_state',
      bikeId: msg.bikeId,
      riderId,
    });
  }

  private handleBikeRelease(
    senderId: string,
    msg: Extract<ClientMessage, { type: 'bike_release' }>
  ): void {
    if (this.phase !== 'playing' || !this.match) return;
    if (typeof msg.bikeId !== 'string' || msg.bikeId.length === 0 || msg.bikeId.length > 64) {
      return;
    }

    const riderId = this.resolveAuthorizedActorId(senderId, msg.riderId);
    if (!riderId) return;

    const existingOwner = this.match.bikeOwners.get(msg.bikeId);
    if (existingOwner !== riderId) return;

    this.match.bikeOwners.delete(msg.bikeId);
    this.broadcast({
      type: 'bike_state',
      bikeId: msg.bikeId,
      riderId: null,
      x: finiteOrZero(msg.x),
      y: finiteOrZero(msg.y),
      z: finiteOrZero(msg.z),
      yaw: finiteOrZero(msg.yaw),
      speed: clampFinite(msg.speed, -10, 30, 0),
    });
  }

  private releaseBikesOwnedBy(riderId: string): void {
    if (!this.match) return;
    for (const [bikeId, ownerId] of this.match.bikeOwners.entries()) {
      if (ownerId === riderId) {
        this.match.bikeOwners.delete(bikeId);
        this.broadcast({
          type: 'bike_state',
          bikeId,
          riderId: null,
        });
      }
    }
  }

  private handleBikeBell(
    ws: WebSocket,
    senderId: string,
    msg: Extract<ClientMessage, { type: 'bike_bell' }>
  ): void {
    if (this.phase !== 'playing' || !this.match) return;
    if (typeof msg.bikeId !== 'string' || !msg.bikeId) return;

    this.broadcast(
      {
        type: 'bike_bell',
        bikeId: msg.bikeId.slice(0, 64),
        riderId: senderId,
        x: finiteOrZero(msg.x),
        y: finiteOrZero(msg.y),
        z: finiteOrZero(msg.z),
      },
      ws
    );
  }

  private handleTechStopUpgrade(
    ws: WebSocket,
    senderId: string,
    msg: Extract<ClientMessage, { type: 'techstop_upgrade' }>
  ): void {
    if (this.phase !== 'playing' || !this.match) return;
    if (typeof msg.techStopId !== 'string' || !msg.techStopId) return;
    if (!isValidWeaponId(msg.weaponId) || !isValidRarity(msg.newRarity)) return;

    this.broadcast(
      {
        type: 'techstop_upgrade',
        playerId: senderId,
        techStopId: msg.techStopId.slice(0, 64),
        weaponId: msg.weaponId,
        newRarity: msg.newRarity,
        x: finiteOrZero(msg.x),
        y: finiteOrZero(msg.y),
        z: finiteOrZero(msg.z),
      },
      ws
    );
  }

  // -------------------------------------------------------------------------
  // Disconnect Cleanup & Instant Host Failover
  // -------------------------------------------------------------------------

  private async handleSocketDisconnect(ws: WebSocket): Promise<void> {
    if (this.closedSockets.has(ws)) return;
    this.closedSockets.add(ws);

    const att = this.getAttachment(ws);
    if (!att) return;
    const memberId = att.memberId;

    const member = this.members.get(memberId);
    if (!member) return;

    const wasHost = this.hostId === memberId;

    // Release any bike owned by the disconnecting player
    if (this.phase === 'playing' && this.match) {
      this.releaseBikesOwnedBy(memberId);
    }

    if (this.phase === 'playing') {
      member.connected = false;
    } else {
      this.members.delete(memberId);
      this.joinOrder.delete(memberId);
      this.deletePersistedMember(memberId);
    }

    const remainingConnected = this.getConnectedMembers();

    // Room completely empty -> cancel countdown and reset cleanly to idle lobby
    if (remainingConnected.length === 0) {
      await this.ctx.storage.deleteAlarm();
      this.phase = 'lobby';
      this.countdownSec = 0;
      this.hostId = '';
      this.match = null;
      this.members.clear();
      this.joinOrder.clear();
      this.ctx.storage.sql.exec('DELETE FROM room_members');
      this.persistMeta();
      return;
    }

    // Immediate Host Failover (both in lobby AND mid-match so bot simulation never freezes!)
    if (wasHost) {
      this.hostId = remainingConnected[0].id;
      this.syncHostFlags();
      this.persistMeta();
      this.broadcast(
        {
          type: 'host_changed',
          hostId: this.hostId,
          reason: 'Previous host disconnected',
        },
        ws
      );
    }

    // Abort countdown if PvP-only room drops below 2 players
    if (
      this.phase === 'countdown' &&
      !this.settings.fillBots &&
      remainingConnected.length < 2
    ) {
      await this.ctx.storage.deleteAlarm();
      this.phase = 'lobby';
      this.countdownSec = 0;
      this.persistMeta();
      this.broadcast(
        {
          type: 'error',
          code: 'COUNTDOWN_CANCELLED',
          message: 'Countdown cancelled — a player disconnected.',
        },
        ws
      );
    }

    // Mid-match disconnect eliminates the departed player so matches never deadlock
    if (this.phase === 'playing' && this.match) {
      const combatant = this.match.combatants.get(memberId);
      if (combatant && combatant.alive) {
        this.eliminateCombatant(combatant, null, 'Disconnected', false, false, false);
      }
    }

    this.broadcast({ type: 'room_state', room: this.getLobbySnapshot() }, ws);
  }
}

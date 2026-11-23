/**
 * Shared Multiplayer Protocol & Deterministic PRNG
 *
 * Pure TypeScript with ZERO Three.js / DOM imports so both the Vite browser
 * client (`src/`) and the Cloudflare Worker + Durable Object (`worker/`)
 * import it directly.
 */

// ---------------------------------------------------------------------------
// Core Game Domain Literal Unions (mirroring src/types.ts without DOM deps)
// ---------------------------------------------------------------------------

export type MpHeroId = 'gmail' | 'drive' | 'calendar' | 'chat' | 'slides' | 'docs';

export type MpBotTier = 'casual' | 'tactical' | 'pro';
export type MpBotDifficulty = MpBotTier | 'mixed';

export type MpGameModeId = 'battle_royale' | 'blitz' | 'sniper_showdown' | 'campus_practice';

export type MpWeaponId =
  | 'vanguard_m4'
  | 'breaker_12g'
  | 'vector_9'
  | 'longbow_308'
  | 'nova_gl40';

export type MpUtilityItemId =
  | 'shield_cell'
  | 'shield_jug'
  | 'medkit'
  | 'mana_elixir'
  | 'hardlight_cover'
  | 'impulse_booster';

export type MpRarity = 'common' | 'rare' | 'epic';
export type MpChestTier = 1 | 2 | 3;

export const MP_HERO_IDS: readonly MpHeroId[] = [
  'gmail',
  'drive',
  'calendar',
  'chat',
  'slides',
  'docs',
];

export const MP_GAME_MODES: readonly MpGameModeId[] = [
  'battle_royale',
  'blitz',
  'sniper_showdown',
  'campus_practice',
];

export const MP_BOT_DIFFICULTIES: readonly MpBotDifficulty[] = [
  'casual',
  'tactical',
  'pro',
  'mixed',
];

export const MP_WEAPON_IDS: readonly MpWeaponId[] = [
  'vanguard_m4',
  'breaker_12g',
  'vector_9',
  'longbow_308',
  'nova_gl40',
];

export const MP_RARITIES: readonly MpRarity[] = ['common', 'rare', 'epic'];

export const MP_MAX_PLAYERS = 20;
export const MP_DROP_RING_COUNT = 20;
export const MP_STORM_ANCHOR_COUNT = 12;

export const MP_BOT_CALLSIGNS: Record<MpHeroId, readonly string[]> = {
  gmail: ['Gmail-AI·01', 'Inbox-AI·04', 'Priority-AI·13', 'Mail-AI·19'],
  drive: ['Drive-AI·02', 'Vault-AI·05', 'Cloud-AI·14', 'Share-AI·20'],
  calendar: ['Calendar-AI·03', 'Chrono-AI·06', 'Block-AI·15', 'Event-AI·21'],
  chat: ['Chat-AI·07', 'Ping-AI·08', 'Thread-AI·16', 'Space-AI·22'],
  slides: ['Slides-AI·09', 'Deck-AI·10', 'Laser-AI·17', 'Stage-AI·23'],
  docs: ['Docs-AI·11', 'Draft-AI·12', 'Version-AI·18', 'Edit-AI·24'],
};

// ---------------------------------------------------------------------------
// Room, Teams & Lobby State
// ---------------------------------------------------------------------------

export type RoomFormat = 'ffa' | 'teams';
export type TeamId = 'blue' | 'red' | 'yellow' | 'green';
export type RoomPhase = 'lobby' | 'countdown' | 'playing' | 'ended';

export const MP_ROOM_FORMATS: readonly RoomFormat[] = ['ffa', 'teams'];
export const MP_TEAM_IDS: readonly TeamId[] = ['blue', 'red', 'yellow', 'green'];

export interface TeamConfig {
  id: TeamId;
  label: string;
  colorCss: string;
  hex: number;
}

export const TEAM_CONFIG: Record<TeamId, TeamConfig> = {
  blue: { id: 'blue', label: 'Blue', colorCss: '#1A73E8', hex: 0x1a73e8 },
  red: { id: 'red', label: 'Red', colorCss: '#EA4335', hex: 0xea4335 },
  yellow: { id: 'yellow', label: 'Yellow', colorCss: '#FBBC04', hex: 0xfbbc04 },
  green: { id: 'green', label: 'Green', colorCss: '#34A853', hex: 0x34a853 },
};

export interface RoomSettings {
  mode: MpGameModeId;
  format: RoomFormat;
  fillBots: boolean;
  botDifficulty: MpBotDifficulty;
  maxPlayers: number;
}

export const DEFAULT_ROOM_SETTINGS: RoomSettings = {
  mode: 'battle_royale',
  format: 'ffa',
  fillBots: true,
  botDifficulty: 'tactical',
  maxPlayers: 20,
};

export interface RoomMember {
  id: string;
  name: string;
  heroId: MpHeroId;
  teamId: TeamId;
  ready: boolean;
  isHost: boolean;
  connected: boolean;
}

export interface RoomLobbySnapshot {
  roomCode: string;
  phase: RoomPhase;
  countdownSec: number;
  hostId: string;
  settings: RoomSettings;
  members: RoomMember[];
}

export interface MatchCombatantSpec {
  id: string;
  name: string;
  isHuman: boolean;
  heroId: MpHeroId;
  teamId: TeamId | null;
  dropIndex: number;
  botTier?: MpBotTier;
}

export interface MatchStartPayload {
  matchId: string;
  seed: number;
  settings: RoomSettings;
  hostId: string;
  combatants: MatchCombatantSpec[];
  stormAnchorIndex: number;
  stormOffsetX: number;
  stormOffsetZ: number;
  serverStartTimeMs: number;
}

// ---------------------------------------------------------------------------
// Compact Movement State Flag Bitmask
// ---------------------------------------------------------------------------

export const FLAG_GROUNDED = 1 << 0;
export const FLAG_CROUCHING = 1 << 1;
export const FLAG_SPRINTING = 1 << 2;
export const FLAG_SLIDING = 1 << 3;
export const FLAG_ADS = 1 << 4;
export const FLAG_RELOADING = 1 << 5;
export const FLAG_SKYDROPPING = 1 << 6;
export const FLAG_REWINDING = 1 << 7;
export const FLAG_CHANNELING = 1 << 8;
export const FLAG_IN_BUS = 1 << 9;

// ---------------------------------------------------------------------------
// Compact Real-Time Match Payloads
// ---------------------------------------------------------------------------

export interface PeerStateUpdate {
  id: string;
  x: number;
  y: number;
  z: number;
  vx: number;
  vy: number;
  vz: number;
  yaw: number;
  pitch: number;
  flags: number;
  weaponId?: MpWeaponId | null;
  weaponRarity?: MpRarity | null;
  bikeId?: string | null;
  bikeSteer?: number;
  bikeLean?: number;
  bikeSpeed?: number;
}

export type PlayerStateInput = Omit<PeerStateUpdate, 'id'>;

export interface BotStateSample {
  id: string;
  x: number;
  y: number;
  z: number;
  vx: number;
  vz: number;
  yaw: number;
  pitch: number;
  flags: number;
  hp: number;
  sh: number;
  alive: boolean;
  weaponId?: MpWeaponId | null;
  weaponRarity?: MpRarity | null;
}

export interface SyncedGroundLoot {
  id: string;
  kind: 'weapon' | 'item';
  itemId: string;
  rarity: MpRarity;
  count?: number;
  ammo?: number;
  x: number;
  y: number;
  z: number;
}

export interface FireFxEvent {
  shooterId: string;
  weaponId: MpWeaponId;
  ox: number;
  oy: number;
  oz: number;
  endX: number;
  endY: number;
  endZ: number;
  isExplosive?: boolean;
  explosionRadius?: number;
}

export interface UltCastEvent {
  casterId: string;
  heroId: MpHeroId;
  x: number;
  y: number;
  z: number;
  yaw: number;
  pitch: number;
  targetX?: number;
  targetY?: number;
  targetZ?: number;
}

export interface DamageEvent {
  targetId: string;
  attackerId: string | null;
  amount: number;
  newHealth: number;
  newShield: number;
  shieldBroken: boolean;
  headshot: boolean;
  weaponName: string;
  isUltimate: boolean;
  isStorm?: boolean;
  hitX: number;
  hitY: number;
  hitZ: number;
}

export interface ElimEvent {
  victimId: string;
  killerId: string | null;
  weaponName: string;
  headshot: boolean;
  isUltimate: boolean;
  isStorm: boolean;
  placement: number;
  aliveCount: number;
  aliveTeams: number;
}

export interface MatchRankingEntry {
  id: string;
  name: string;
  teamId: TeamId | null;
  placement: number;
  eliminations: number;
  headshots: number;
  damageDealt: number;
  isHuman: boolean;
}

export interface MatchEndPayload {
  winnerId: string | null;
  winnerTeamId: TeamId | null;
  winnerName: string;
  totalPlayers: number;
  survivedSeconds: number;
  rankings: MatchRankingEntry[];
}

// ---------------------------------------------------------------------------
// Client -> Server Discriminated Union (`ClientMessage`)
// ---------------------------------------------------------------------------

export type ClientMessage =
  // Lobby
  | {
      type: 'join_room';
      name: string;
      heroId: MpHeroId;
      teamId?: TeamId;
    }
  | {
      type: 'update_profile';
      name?: string;
      heroId?: MpHeroId;
      teamId?: TeamId;
      ready?: boolean;
    }
  | {
      type: 'update_settings';
      settings: Partial<RoomSettings>;
    }
  | {
      type: 'start_match';
    }
  | {
      type: 'return_lobby';
    }
  | {
      type: 'ping';
      t: number;
    }
  // Live Match
  | {
      type: 'player_state';
      state: PlayerStateInput;
    }
  | {
      type: 'bot_batch';
      bots: BotStateSample[];
    }
  | {
      type: 'fire_fx';
      event: FireFxEvent;
    }
  | {
      type: 'hit_report';
      targetId: string;
      /** Optional override allowed ONLY when host reports damage dealt by an AI bot. */
      attackerId?: string;
      amount: number;
      headshot: boolean;
      weaponName: string;
      isUltimate: boolean;
      hitX: number;
      hitY: number;
      hitZ: number;
    }
  | {
      type: 'vitals_sync';
      /** Optional override allowed ONLY when host syncs vitals for an AI bot. */
      combatantId?: string;
      health: number;
      shield: number;
      mana?: number;
    }
  | {
      type: 'storm_damage';
      /** Optional override allowed ONLY when host reports storm damage on an AI bot. */
      targetId?: string;
      amount: number;
    }
  | {
      type: 'ult_cast';
      event: UltCastEvent;
    }
  | {
      type: 'chest_open';
      chestId: string;
      /** Optional override allowed ONLY when host opens a chest on behalf of an AI bot. */
      openerId?: string;
      loot?: SyncedGroundLoot[];
    }
  | {
      type: 'loot_claim';
      lootId: string;
      /** Optional override allowed ONLY when host claims loot on behalf of an AI bot. */
      claimerId?: string;
    }
  | {
      type: 'loot_spawn';
      items: SyncedGroundLoot[];
    }
  | {
      type: 'supply_drop_open';
      dropId: string;
      /** Optional override allowed ONLY when host opens a supply drop on behalf of an AI bot. */
      openerId?: string;
      loot?: SyncedGroundLoot[];
    }
  | {
      type: 'bike_claim';
      bikeId: string;
      /** Optional override allowed ONLY when host mounts a bike on behalf of an AI bot. */
      riderId?: string;
    }
  | {
      type: 'bike_release';
      bikeId: string;
      /** Optional override allowed ONLY when host dismounts a bike on behalf of an AI bot. */
      riderId?: string;
      x: number;
      y: number;
      z: number;
      yaw: number;
      speed: number;
    }
  | {
      type: 'bike_bell';
      bikeId: string;
      x: number;
      y: number;
      z: number;
    }
  | {
      type: 'techstop_upgrade';
      techStopId: string;
      weaponId: MpWeaponId;
      newRarity: MpRarity;
      x: number;
      y: number;
      z: number;
    };

// ---------------------------------------------------------------------------
// Server -> Client Discriminated Union (`ServerMessage`)
// ---------------------------------------------------------------------------

export type ServerMessage =
  // Lobby
  | {
      type: 'welcome';
      memberId: string;
      room: RoomLobbySnapshot;
    }
  | {
      type: 'room_state';
      room: RoomLobbySnapshot;
    }
  | {
      type: 'countdown';
      seconds: number;
    }
  | {
      type: 'match_start';
      match: MatchStartPayload;
    }
  | {
      type: 'host_changed';
      hostId: string;
      reason?: string;
    }
  | {
      type: 'error';
      code: string;
      message: string;
    }
  | {
      type: 'pong';
      t: number;
      serverTimeMs: number;
    }
  // Live Match
  | {
      type: 'peer_state';
      state: PeerStateUpdate;
    }
  | {
      type: 'bot_batch';
      bots: BotStateSample[];
    }
  | {
      type: 'fire_fx';
      event: FireFxEvent;
    }
  | {
      type: 'damage_event';
      event: DamageEvent;
    }
  | {
      type: 'elim_event';
      event: ElimEvent;
    }
  | {
      type: 'vitals_update';
      combatantId: string;
      health: number;
      shield: number;
      mana?: number;
    }
  | {
      type: 'ult_cast';
      event: UltCastEvent;
    }
  | {
      type: 'chest_opened';
      chestId: string;
      openerId: string;
      loot: SyncedGroundLoot[];
    }
  | {
      type: 'loot_claimed';
      lootId: string;
      claimerId: string;
    }
  | {
      type: 'loot_spawned';
      items: SyncedGroundLoot[];
    }
  | {
      type: 'supply_drop_opened';
      dropId: string;
      openerId: string;
      loot: SyncedGroundLoot[];
    }
  | {
      type: 'bike_state';
      bikeId: string;
      riderId: string | null;
      x?: number;
      y?: number;
      z?: number;
      yaw?: number;
      speed?: number;
    }
  | {
      type: 'bike_bell';
      bikeId: string;
      riderId: string;
      x: number;
      y: number;
      z: number;
    }
  | {
      type: 'techstop_upgrade';
      playerId: string;
      techStopId: string;
      weaponId: MpWeaponId;
      newRarity: MpRarity;
      x: number;
      y: number;
      z: number;
    }
  | {
      type: 'match_end';
      result: MatchEndPayload;
    };

// ---------------------------------------------------------------------------
// Deterministic PRNG & Room Code Helpers
// ---------------------------------------------------------------------------

/**
 * Mulberry32 deterministic 32-bit PRNG returning uniform floats in [0, 1).
 * Used identically across clients & server so chests, drops, and bot specs
 * roll deterministically from `MatchStartPayload.seed`.
 */
export function createSeededRng(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * Deterministic bot tier assignment mirroring `assignBotTiers` in botProfiles.ts,
 * driven by a seeded PRNG so worker and clients stay completely synchronized.
 */
export function assignSeededBotTiers(
  difficulty: MpBotDifficulty,
  botCount: number,
  rng: () => number
): MpBotTier[] {
  if (botCount <= 0) return [];
  if (difficulty !== 'mixed') {
    return Array.from({ length: botCount }, () => difficulty);
  }
  const casualCount = Math.max(1, Math.round(botCount * 0.3));
  const proCount = Math.max(1, Math.round(botCount * 0.25));
  const tacticalCount = Math.max(0, botCount - casualCount - proCount);
  const tiers: MpBotTier[] = [
    ...Array.from({ length: casualCount }, (): MpBotTier => 'casual'),
    ...Array.from({ length: tacticalCount }, (): MpBotTier => 'tactical'),
    ...Array.from({ length: proCount }, (): MpBotTier => 'pro'),
  ];
  for (let i = tiers.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [tiers[i], tiers[j]] = [tiers[j], tiers[i]];
  }
  return tiers.slice(0, botCount);
}

/**
 * Unambiguous room code alphabet excluding visually confusing `O`, `0`, `I`, `1`.
 */
const ROOM_CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';

/**
 * Normalize raw user input to uppercase A-Z0-9, clamped to at most 6 chars.
 */
export function normalizeRoomCode(raw: string): string {
  return String(raw ?? '')
    .toUpperCase()
    .replace(/[^A-Z0-9]/g, '')
    .slice(0, 6);
}

/**
 * Check whether a normalized room code satisfies the 4-6 alphanumeric length contract.
 */
export function isValidRoomCode(code: string): boolean {
  const normalized = normalizeRoomCode(code);
  return normalized.length >= 4 && normalized.length <= 6 && normalized === code;
}

/**
 * Generate a 5-character (or 4-5 char) unambiguous uppercase alphanumeric room code.
 */
export function generateRoomCode(length = 5): string {
  const clampedLen = Math.max(4, Math.min(5, Math.floor(length)));
  const bytes = new Uint8Array(clampedLen);
  const cryptoObj = (
    globalThis as unknown as {
      crypto?: { getRandomValues?: (arr: Uint8Array) => Uint8Array };
    }
  ).crypto;
  if (cryptoObj && typeof cryptoObj.getRandomValues === 'function') {
    cryptoObj.getRandomValues(bytes);
  } else {
    for (let i = 0; i < clampedLen; i++) {
      bytes[i] = Math.floor(Math.random() * 256);
    }
  }
  let code = '';
  for (let i = 0; i < clampedLen; i++) {
    code += ROOM_CODE_ALPHABET[bytes[i] % ROOM_CODE_ALPHABET.length];
  }
  return code;
}

/**
 * Sanitize a player display name (trimmed, stripped of control chars, <= 18 chars).
 */
export function sanitizeDisplayName(raw: string, fallback = 'Googler'): string {
  const cleaned = String(raw ?? '')
    .replace(/[\u0000-\u001f\u007f]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 18);
  return cleaned.length > 0 ? cleaned : fallback;
}

export function isValidHeroId(value: unknown): value is MpHeroId {
  return typeof value === 'string' && (MP_HERO_IDS as readonly string[]).includes(value);
}

export function isValidGameModeId(value: unknown): value is MpGameModeId {
  return typeof value === 'string' && (MP_GAME_MODES as readonly string[]).includes(value);
}

export function isValidBotDifficulty(value: unknown): value is MpBotDifficulty {
  return typeof value === 'string' && (MP_BOT_DIFFICULTIES as readonly string[]).includes(value);
}

export function isValidTeamId(value: unknown): value is TeamId {
  return typeof value === 'string' && (MP_TEAM_IDS as readonly string[]).includes(value);
}

export function isValidRoomFormat(value: unknown): value is RoomFormat {
  return typeof value === 'string' && (MP_ROOM_FORMATS as readonly string[]).includes(value);
}

export function isValidWeaponId(value: unknown): value is MpWeaponId {
  return typeof value === 'string' && (MP_WEAPON_IDS as readonly string[]).includes(value);
}

export function isValidRarity(value: unknown): value is MpRarity {
  return typeof value === 'string' && (MP_RARITIES as readonly string[]).includes(value);
}

export type Rarity = 'common' | 'rare' | 'epic' | 'mythic';

export type ChestTier = 1 | 2 | 3;

export type ProductHeroId = 'gmail' | 'drive' | 'calendar' | 'chat' | 'slides' | 'docs';

export type AnimName =
  | 'Idle'
  | 'Run'
  | 'Sprint'
  | 'Crouch'
  | 'Aim'
  | 'Reload'
  | 'Glide'
  | 'Jump'
  | 'IdleArmed'
  | 'RunArmed'
  | 'SprintArmed'
  | 'JumpArmed'
  | 'LobbyShowcase';

export type BotTier = 'casual' | 'tactical' | 'pro';
export type BotDifficulty = BotTier | 'mixed';

export type WeaponId =
  | 'vanguard_m4'
  | 'breaker_12g'
  | 'vector_9'
  | 'longbow_308'
  | 'nova_gl40';

export type UtilityItemId =
  | 'shield_cell'
  | 'shield_jug'
  | 'medkit'
  | 'mana_elixir'
  | 'hardlight_cover'
  | 'impulse_booster'
  | 'frag_grenade'
  | 'flashbang'
  | 'shield_drop'
  | 'regen_pod';

export type SpectateMode = 'follow' | 'free';

export type PropAssetId =
  | 'supply_drop'
  | 'glider'
  | 'loot_chest'
  | 'gbike_rideable'
  | 'techstop_kiosk'
  | 'google_gbus';

export type MapAssetKey =
  | 'terrain'
  | 'stan_trex'
  | 'b40_partnerplex'
  | 'b41'
  | 'b42'
  | 'b43'
  | 'skybridge'
  | 'volleyball_court'
  | 'gradient_canopy'
  | 'orb_plaza'
  | 'shoreline_amphitheatre'
  | 'athletic_field'
  | 'google_2000_1950'
  | 'charleston_campus'
  | 'alta_complex'
  | 'shoreline_east_office'
  | 'umbrella_bistro'
  | 'gbike_rack'
  | 'oak_tree'
  | 'redwood_tree'
  | 'desk_pod'
  | 'conference_pod'
  | 'microkitchen_bar'
  | 'lounge_nook'
  | 'whiteboard_wall'
  | 'park_outdoor_gym'
  | 'park_art_garden'
  | 'park_google_pergola'
  | 'garden_planter_wall'
  | 'sculpture_plinth';

export interface RarityConfig {
  id: Rarity;
  label: string;
  colorCss: string;
  hex: number;
  emissiveHex: number;
  emissiveIntensity: number;
  mult: number;
  reloadMult: number;
  standardWeight: number;
  highTierWeight: number;
}

export interface ChestTierConfig {
  tier: ChestTier;
  name: string;
  shortLabel: string;
  colorCss: string;
  hex: number;
  emissiveHex: number;
  emissiveIntensity: number;
  minItems: number;
  maxItems: number;
}

export interface ProductHeroUltimateDef {
  name: string;
  subtitle: string;
  description: string;
  manaCost: number;
  cooldown: number;
}

export interface ProductHeroDef {
  id: ProductHeroId;
  personaName: string;
  productName: string;
  /** Short display title (e.g. "Maya · Gmail") */
  displayName: string;
  /** Product label (e.g. "Gmail") */
  name: string;
  shortBadge: string;
  role: string;
  tagline: string;
  primaryColor: string;
  accentColor: string;
  hexPrimary: number;
  hexAccent: number;
  assetPath: string;
  lobbyAnimLabel: string;
  lobbyWeaponId: WeaponId | null;
  ultimate: ProductHeroUltimateDef;
}

export interface WeaponDef {
  id: WeaponId;
  name: string;
  shortName: string;
  weaponClass: string;
  skinName: string;
  skinPaletteCss: string;
  icon: string;
  category: 'weapon';
  damage: number;
  headshotMult: number;
  fireRate: number; // shots per second
  magSize: number;
  reloadTime: number;
  range: number;
  pellets: number;
  spread: number; // radians base bloom
  adsSpreadMult: number;
  projectileSpeed: number;
  automatic: boolean;
  hasScope?: boolean;
  splashRadius?: number;
  gravityScale?: number;
  coverDamageMult?: number;
  manaPerShot?: number;
  color: number;
  assetPath: string;
}

export interface UtilityItemDef {
  id: UtilityItemId;
  name: string;
  shortName: string;
  utilityCategory: 'shield' | 'health' | 'mana' | 'tactical' | 'mobility';
  icon: string;
  category: 'item';
  description: string;
  baseAmount: number;
  amountsByRarity: Record<Rarity, number>;
  channelTime: number; // seconds (0 = instant)
  maxStack: number;
  manaCost?: number;
  color: number;
  assetPath: string;
}

export interface InventorySlot {
  kind: 'weapon' | 'item';
  id: WeaponId | UtilityItemId;
  rarity: Rarity;
  ammo?: number;
  count?: number;
}

export interface BotDifficultyProfile {
  tier: BotTier;
  label: string;
  shortLabel: string;
  description: string;
  /** Angular aim scatter in radians */
  aimErrorRad: number;
  /** Reference scatter in meters at medium range (spec §6) */
  aimScatterMeters: number;
  /** 0..1 linear velocity lead prediction factor */
  leadFactor: number;
  /** 0..1 probability of aiming for head hitbox */
  headshotBias: number;
  /** Reaction delay in seconds before firing on newly acquired target */
  reactionTime: number;
  /** Maximum engagement distance in meters */
  engagementRange: number;
  /** Fire cadence throttle multiplier (0..1) */
  fireCadenceMult: number;
  /** Lateral combat strafe speed/aggressiveness (0..1) */
  strafeIntensity: number;
  /** Likelihood to crouch when peeking or shooting at range */
  crouchPeekChance: number;
  /** Likelihood to seek architectural cover in combat */
  useCoverChance: number;
  /** Likelihood to deploy Hard-Light Cover when taking sudden fire */
  deployHardlightChance: number;
  /** Likelihood to use Impulse Booster for high ground or escape */
  useImpulseChance: number;
  /** Total vitals ratio (0..1) below which bot retreats/heals */
  healThresholdRatio: number;
  /** Whether bot moves behind cover before channeling heals */
  healInCover: boolean;
  /** Whether bot actively contests mid-match Supply Drops */
  contestSupplyDrop: boolean;
  /** Priority weight for contesting Supply Drops (0..1) */
  supplyDropPriority: number;
  /** Desire to seek Rare/Epic loot upgrades (0..1) */
  lootUpgradeDesire: number;
  /** Bias toward hot-drop landmarks (Stan Plaza / Gradient Canopy / Roofs) */
  hotDropBias: number;
  /** Tendency to third-party nearby active fights (0..1) */
  thirdPartyAggression: number;
  /** Seconds before storm shrink that bot begins rotating inward */
  stormRotateLeadSec: number;
  /** Whether bot pre-rotates into the next dashed safe zone early */
  preRotateNextZone: boolean;
  /** Ultimate decision quality tier */
  ultimateSmartness: 'basic' | 'contextual' | 'optimal';
}

export interface BoxCollider {
  id?: string;
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
  minZ: number;
  maxZ: number;
  /** Optional Y-axis rotation in radians around the box's XZ center (OBB) */
  rotationY?: number;
  /** Walkable ramp/stair slope */
  isRamp?: boolean;
  /** Local axis along which ramp rises ('x' or 'z') */
  rampAxis?: 'x' | 'z';
  /** +1 rises toward +axis, -1 rises toward -axis */
  rampDir?: 1 | -1;
  /** Elevated thin walkable platform (allows walking underneath when minY > head) */
  isPlatform?: boolean;
  destructible?: boolean;
  hp?: number;
  maxHp?: number;
  ownerId?: string;
  meshId?: string;
  /** Whether projectiles/LOS are blocked (defaults to true) */
  blocksBullets?: boolean;
  tag?: string;
}

export interface HitboxCheckResult {
  hit: boolean;
  headshot: boolean;
  /** Normalized ray/segment parameter in [0, 1] */
  t: number;
  point?: { x: number; y: number; z: number };
}

export interface LandmarkInfo {
  id: string;
  name: string;
  x: number;
  z: number;
  radius: number;
  color: string;
  highTier?: boolean;
}

export interface LootSpot {
  x: number;
  y: number;
  z: number;
  highTier: boolean;
  landmark: string;
}

export interface GliderDropPoint {
  x: number;
  y: number;
  z: number;
  heading: number;
}

export interface SupplyDropSpot {
  x: number;
  y: number;
  z: number;
  landmark: string;
}

export interface StormPhaseDef {
  phase: number;
  waitDuration: number;
  shrinkDuration: number;
  targetRadius: number;
  dps: number;
  isMoving?: boolean;
  moveShiftMin?: number;
  moveShiftMax?: number;
}

export interface LoadingProgress {
  loaded: number;
  total: number;
  ratio: number;
  label: string;
}

export interface ChannelState {
  active: boolean;
  label: string;
  progress: number; // 0..1
  remainingSec: number;
  totalSec: number;
  kind?: 'consumable' | 'supply_drop' | 'chest' | 'techstop';
  chestTier?: ChestTier;
}

export interface StatusEffectsState {
  crouching: boolean;
  sliding: boolean;
  ridingGBike?: boolean;
  gbikeSpeedKmh?: number;
  inBus?: boolean;
  canDropFromBus?: boolean;
  busProgress?: number; // 0..1
  silencedSec: number;
  hastedSec: number;
  slowedSec: number;
  revealedSec: number;
  rewinding: boolean;
  inStorm: boolean;
  skyDropping: boolean;
  altitude: number;
}

export type QualityPreset = 'performance' | 'balanced' | 'high';

export type GameModeId = 'battle_royale' | 'blitz' | 'sniper_showdown' | 'campus_practice';

export interface GameModeDef {
  id: GameModeId;
  name: string;
  badge: string;
  tagline: string;
  description: string;
  accentCss: string;
  totalCombatants: number;
  startMana: number;
  manaRegenMult: number;
  moveSpeedMult: number;
  stormEnabled: boolean;
  stormPaceMult: number;
  initialStormRadius: number;
  forceWeaponId?: WeaponId;
  minChestTier?: ChestTier;
  forceBotDifficulty?: BotDifficulty;
  highlights: string[];
}

export interface GameSettings {
  botDifficulty: BotDifficulty;
  qualityPreset: QualityPreset;
  showPerfHud: boolean;
  masterVolume: number;       // 0..1 (default 1.0)
  muted: boolean;             // default false
  mouseSensitivity: number;   // 0.4..2.2 (default 1.0)
  adsSensitivity: number;     // 0.4..2.0 (default 1.0)
  invertY: boolean;           // default false
  visualSoundCompass?: boolean; // default true
}

export interface PerfStats {
  fps: number;
  drawCalls: number;
  triangles: number;
  visibleChests: number;
  visibleBots: number;
}

export interface MapWaypoint {
  x: number;
  z: number;
}

export interface SupplyDropBearing {
  angleRad: number;
  dist: number;
  landed: boolean;
  opened: boolean;
}

export type SoundCueKind = 'footstep' | 'gunfire' | 'chest' | 'gbike' | 'supply_drop';

export interface SoundCompassCue {
  kind: SoundCueKind;
  /** Relative bearing in radians from player forward: 0 = ahead, +PI/2 = right, -PI/2 = left, ±PI = behind */
  bearingRad: number;
  /** Normalized prominence 0..1 */
  intensity: number;
}

export interface HudSnapshot {
  health: number;
  maxHealth: number;
  shield: number;
  maxShield: number;
  mana: number;
  maxMana: number;
  aliveCount: number;
  totalPlayers: number;
  eliminations: number;
  headshots: number;
  damageDealt: number;
  heroId: ProductHeroId;
  heroName: string;
  heroPersona: string;
  botDifficulty: BotDifficulty;
  gameMode: GameModeId;
  slots: (InventorySlot | null)[];
  activeSlot: number;
  isReloading: boolean;
  reloadProgress: number;
  isAds: boolean;
  sniperScope: boolean;
  spreadPx: number;
  ultName: string;
  ultManaCost: number;
  ultCooldown: number;
  ultMaxCooldown: number;
  ultReady: boolean;
  stormPhase: number;
  stormStateLabel: string;
  stormTimer: number;
  inStorm: boolean;
  stormDps: number;
  stormIsMoving?: boolean;
  zoneName: string;
  headingRad: number;
  interactPrompt: string | null;
  channel: ChannelState;
  status: StatusEffectsState;
  supplyDropBearings: SupplyDropBearing[];
  soundCues?: SoundCompassCue[];
  waypointBearingRad?: number | null;
  waypointDist?: number | null;
  pointerLocked: boolean;
  matchPhase: 'lobby' | 'skydrop' | 'playing' | 'ended';
  flashBlindAlpha?: number;
  multiplayer?: {
    active: boolean;
    roomCode: string;
    format: 'ffa' | 'teams';
    teamId: 'blue' | 'red' | 'yellow' | 'green' | null;
    aliveTeams: number;
    rttMs: number;
  } | null;
  spectating?: {
    active: boolean;
    targetId: string;
    targetName: string;
    targetHeroId: ProductHeroId;
    health: number;
    shield: number;
    teamId: 'blue' | 'red' | 'yellow' | 'green' | null;
    mode?: SpectateMode;
    altitude?: number;
    zoneName?: string;
  } | null;
}

export interface MinimapEntity {
  x: number;
  z: number;
  color?: string;
  revealed?: boolean;
  isBot?: boolean;
  isTeammate?: boolean;
  name?: string;
  teamColor?: string;
}

export interface MinimapLootPip {
  x: number;
  z: number;
  rarity: Rarity;
}

export interface MinimapChestPip {
  x: number;
  z: number;
  tier: ChestTier;
}

export interface MinimapSupplyDrop {
  x: number;
  z: number;
  landed: boolean;
  opened: boolean;
}

export interface MinimapGBike {
  x: number;
  z: number;
  occupied: boolean;
}

export interface MinimapTechStop {
  x: number;
  z: number;
  name: string;
}

export interface MinimapGBusState {
  active: boolean;
  x: number;
  z: number;
  yaw: number;
  startX: number;
  startZ: number;
  endX: number;
  endZ: number;
  progress: number; // 0..1
}

export interface MinimapState {
  playerX: number;
  playerZ: number;
  playerYaw: number;
  stormCenterX: number;
  stormCenterZ: number;
  stormRadius: number;
  nextStormCenterX: number;
  nextStormCenterZ: number;
  nextStormRadius: number;
  enemies: MinimapEntity[];
  loot: MinimapLootPip[];
  chests: MinimapChestPip[];
  supplyDrops: MinimapSupplyDrop[];
  gbikes?: MinimapGBike[];
  techStops?: MinimapTechStop[];
  gbus?: MinimapGBusState | null;
  stormMoving?: boolean;
  landmarks: LandmarkInfo[];
  revealedAll: boolean;
  waypoint?: MapWaypoint | null;
}

export interface KillFeedEntry {
  id: number;
  killer: string;
  killerHero: ProductHeroId;
  victim: string;
  victimHero: ProductHeroId;
  weapon: string;
  headshot: boolean;
  isUltimate?: boolean;
  isMythic?: boolean;
  isStorm?: boolean;
  timestamp: number;
}

export interface FloatingDamageEvent {
  screenX: number;
  screenY: number;
  amount: number;
  kind: 'health' | 'shield' | 'headshot' | 'heal';
  worldX?: number;
  worldY?: number;
  worldZ?: number;
}

export interface DirectionalDamageEvent {
  /** Relative bearing in radians from player forward (0=front, +PI/2=right, PI=behind, -PI/2=left) */
  bearingRad: number;
  amount: number;
  isStorm?: boolean;
}

export interface MatchSummary {
  won: boolean;
  placement: number;
  totalPlayers: number;
  heroId: ProductHeroId;
  heroName: string;
  heroPersona: string;
  eliminations: number;
  headshots: number;
  damageDealt: number;
  survivedSeconds: number;
  botDifficulty: BotDifficulty;
  gameMode: GameModeId;
  isMultiplayer?: boolean;
  matchOngoing?: boolean;
  teamId?: 'blue' | 'red' | 'yellow' | 'green' | null;
  winnerTeamId?: 'blue' | 'red' | 'yellow' | 'green' | null;
  winnerName?: string;
}

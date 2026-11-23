import * as THREE from 'three';
import {
  AnimName,
  BotDifficulty,
  BotTier,
  ChannelState,
  ChestTier,
  DirectionalDamageEvent,
  FloatingDamageEvent,
  GameModeId,
  GameSettings,
  HudSnapshot,
  InventorySlot,
  KillFeedEntry,
  LoadingProgress,
  MapWaypoint,
  MatchSummary,
  MinimapChestPip,
  MinimapEntity,
  MinimapGBike,
  MinimapLootPip,
  MinimapState,
  MinimapSupplyDrop,
  MinimapTechStop,
  PerfStats,
  ProductHeroId,
  QualityPreset,
  Rarity,
  SoundCompassCue,
  SoundCueKind,
  SpectateMode,
  SupplyDropBearing,
  UtilityItemId,
  WeaponId,
} from '../types';
import {
  CHEST_TIER_CONFIG,
  createStarterLoadout,
  GAME_CONSTANTS,
  GAME_MODES,
  getUtilityAmount,
  getWeaponDamage,
  getWeaponReloadTime,
  HERO_MAP,
  RARITY_CONFIG,
  rollChestLoot,
  rollChestTier,
  rollSupplyDropWeapon,
  STORM_PHASES,
  UTILITY_ITEMS,
  WEAPONS,
} from '../data/catalog';
import { assignBotTiers, getBotProfile } from '../data/botProfiles';
import {
  alignWeaponTwoHanded,
  AssetManager,
  GoogleGBusVisual,
  HeroInstance,
  LootChestVisual,
  LootDropVisual,
  ReloadLowerMode,
  RideableGBikeVisual,
  sharedAssetManager,
  WeaponInstance,
} from '../core/assetManager';
import { sharedAudio, SoundEngine } from '../core/audio';
import { PhysicsWorld } from '../core/physics';
import { GoogleplexWorld, TechStopPlacement } from '../world/googleplex';
import { ThirdPersonCamera } from './camera';
import {
  DEFAULT_LOBBY_FOV,
  SPLASH_SCENES_META,
  SplashAttractDirector,
  SplashAttractState,
  SplashSceneMeta,
} from './splashAttract';
import { PersistentZoneVisual, VfxSystem } from './vfx';

export type { SplashAttractState, SplashSceneMeta };
import {
  BOT_DROP_IGNORE_SEC,
  BOT_UTILITY_SWAP_HYSTERESIS,
  BotBrain,
  BotChestSnapshot,
  BotCombatantSnapshot,
  BotDecision,
  BotLootSnapshot,
  BotSupplyDropSnapshot,
  BotWorldContext,
  getBotUtilityValue,
} from '../ai/botBrain';
import { MultiplayerClient } from '../net/mpClient';
import {
  BotStateSample,
  createSeededRng,
  DamageEvent,
  ElimEvent,
  FireFxEvent,
  FLAG_ADS,
  FLAG_CHANNELING,
  FLAG_CROUCHING,
  FLAG_GROUNDED,
  FLAG_IN_BUS,
  FLAG_RELOADING,
  FLAG_REWINDING,
  FLAG_SKYDROPPING,
  FLAG_SLIDING,
  FLAG_SPRINTING,
  MatchEndPayload,
  MatchStartPayload,
  PeerStateUpdate,
  RoomFormat,
  ServerMessage,
  SyncedGroundLoot,
  TEAM_CONFIG,
  TeamId,
  UtilityThrowEvent,
  UltCastEvent,
} from '../net/protocol';

export interface HudCallbacks {
  onHudUpdate: (snapshot: HudSnapshot) => void;
  onKillFeed: (entry: KillFeedEntry) => void;
  onHitMarker: (isHeadshot: boolean, isKill: boolean, shieldBroken?: boolean) => void;
  onPlayerShieldBreak?: () => void;
  onFloatingDamage: (event: FloatingDamageEvent) => void;
  onDirectionalDamage: (event: DirectionalDamageEvent) => void;
  onAnnouncement: (title: string, subtitle?: string) => void;
  onMatchEnd: (summary: MatchSummary) => void;
  onPointerLockChange: (locked: boolean) => void;
}

interface DocsHistorySample {
  pos: THREE.Vector3;
  health: number;
  shield: number;
  timestamp: number;
}

interface ActiveChannel {
  kind: 'consumable' | 'supply_drop' | 'chest' | 'techstop';
  label: string;
  slotIndex: number;
  itemId?: UtilityItemId;
  rarity?: Rarity;
  supplyDropId?: string;
  chestId?: string;
  chestTier?: ChestTier;
  techStopId?: string;
  targetRarity?: Rarity;
  manaCost?: number;
  elapsed: number;
  duration: number;
}

interface RewindState {
  active: boolean;
  elapsed: number;
  duration: number;
  path: THREE.Vector3[];
  targetHealth: number;
  targetShield: number;
  ghostTimer: number;
}

interface PendingSlidesBeam {
  ownerId: string;
  origin: THREE.Vector3;
  dir: THREE.Vector3;
  remaining: number;
  visualOnly?: boolean;
}

interface RemoteNetTarget {
  x: number;
  y: number;
  z: number;
  vx: number;
  vy: number;
  vz: number;
  yaw: number;
  pitch: number;
  flags: number;
  weaponId: WeaponId | null;
  weaponRarity: Rarity | null;
  bikeId: string | null;
  bikeSteer: number;
  bikeLean: number;
  bikeSpeed: number;
  receivedAt: number;
}

interface Combatant {
  id: string;
  name: string;
  isPlayer: boolean;
  isRemoteHuman: boolean;
  teamId: TeamId | null;
  heroId: ProductHeroId;
  botTier?: BotTier;
  brain?: BotBrain;
  netTarget?: RemoteNetTarget;
  remoteRewindGhostTimer: number;

  hero: HeroInstance;
  gliderMesh: THREE.Group;
  weaponInstance: WeaponInstance | null;
  equippedKey: string;

  pos: THREE.Vector3;
  vel: THREE.Vector3;
  yaw: number;
  pitch: number;

  alive: boolean;
  inBus: boolean;
  busDropProgress: number;
  skyDropping: boolean;
  grounded: boolean;
  crouching: boolean;
  sliding: boolean;
  slideTimer: number;
  slideElapsed: number;
  slideCooldown: number;
  slideDirX: number;
  slideDirZ: number;
  slideSpeed: number;
  slidePoseBlend: number;
  slideVfxTimer: number;
  slideInitiatedByCtrl: boolean;
  sprinting: boolean;
  isAds: boolean;
  ridingGBikeId: string | null;
  surface: 'grass' | 'stone' | 'sand' | 'metal';

  health: number;
  shield: number;
  mana: number;
  eliminations: number;
  headshots: number;
  damageDealt: number;

  slots: (InventorySlot | null)[];
  activeSlot: number;
  fireCooldown: number;
  isReloading: boolean;
  reloadTimer: number;
  reloadDuration: number;
  lastShotAt: number;
  semiAutoLatch: boolean;

  ultCooldown: number;
  silencedSec: number;
  blindedSec: number;
  flashBlindPeak: number;
  hastedSec: number;
  slowedSec: number;
  revealedSec: number;
  revealedAllSec: number;

  channel: ActiveChannel | null;
  hitFlashTimer: number;
  footstepTimer: number;
  stormTickAccum: number;
  lastDamagedAt: number;
  lastAttackerId: string | null;
  recentDamageTaken: number;
  gliderTrailTimer: number;

  // Google Docs 4.0s ring buffer (40 entries sampled every 0.1s)
  history: DocsHistorySample[];
  historySampleTimer: number;
  rewind: RewindState;

  // Dynamic locomotion & glider visual polish state
  prevYaw: number;
  prevVelX: number;
  prevVelZ: number;
  leanPitch: number;
  leanBank: number;
  airborneTime: number;
  peakFallSpeed: number;
  squashTimer: number;
  squashDuration: number;
  squashIntensity: number;
  takeoffTimer: number;
  glideBank: number;
  glidePitch: number;
  smoothAimPitch: number;
  twoHandBlend: number;

  // Cached exact inverse-delta quaternions to undo post-mixer procedural bone offsets cleanly before each mixer.update()
  hasProcBoneUndo: boolean;
  procBoneUndo: {
    spine: THREE.Quaternion;
    chest: THREE.Quaternion;
    thighL: THREE.Quaternion;
    shinL: THREE.Quaternion;
    footL: THREE.Quaternion;
    thighR: THREE.Quaternion;
    shinR: THREE.Quaternion;
    footR: THREE.Quaternion;
    upperArmL: THREE.Quaternion;
    lowerArmL: THREE.Quaternion;
    upperArmR: THREE.Quaternion;
    lowerArmR: THREE.Quaternion;
  };

  // Performance: 10 Hz staggered Bot AI & Animation LOD state
  aiThinkTimer: number;
  aiThinkAccumDt: number;
  cachedDecision: BotDecision | null;
  animAccumDt: number;
  animFrameSkip: number;
  castingShadow: boolean;
}

interface Projectile {
  id: number;
  ownerId: string;
  weaponId?: WeaponId;
  weaponName: string;
  isUltimate: boolean;
  kind: 'bullet' | 'grenade' | 'envelope';
  pos: THREE.Vector3;
  prevPos: THREE.Vector3;
  vel: THREE.Vector3;
  damage: number;
  headshotMult: number;
  coverDamageMult: number;
  splashRadius: number;
  gravity: number;
  age: number;
  maxAge: number;
  color: number;
  targetId?: string;
  mesh?: THREE.Object3D;
  visualOnly?: boolean;
}

interface GroundLoot {
  id: string;
  x: number;
  y: number;
  z: number;
  kind: 'weapon' | 'item';
  itemId: WeaponId | UtilityItemId;
  rarity: Rarity;
  count: number;
  visual: LootDropVisual;
  bobPhase: number;
  popStartX?: number;
  popStartY?: number;
  popStartZ?: number;
  popProgress?: number;
  droppedById?: string;
  droppedAt?: number;
}

interface LootChestEntity {
  id: string;
  x: number;
  y: number;
  z: number;
  yaw: number;
  tier: ChestTier;
  landmark: string;
  opened: boolean;
  lidProgress: number;
  visual: LootChestVisual;
  pulsePhase: number;
}

interface HardLightBarrier {
  colliderId: string;
  ownerId: string;
  mesh: THREE.Group;
  pos: THREE.Vector3;
  hp: number;
  maxHp: number;
  flashTimer: number;
}

interface GuardrailZone {
  ownerId: string;
  center: THREE.Vector3;
  radius: number;
  elapsed: number;
  duration: number;
  visual: PersistentZoneVisual;
}

interface ChronoZone {
  ownerId: string;
  center: THREE.Vector3;
  radius: number;
  elapsed: number;
  duration: number;
  visual: PersistentZoneVisual;
}

interface ThrownUtilityEntity {
  id: string;
  ownerId: string;
  itemId: 'frag_grenade' | 'flashbang';
  rarity: Rarity;
  pos: THREE.Vector3;
  vel: THREE.Vector3;
  fuseRemaining: number;
  maxFuse: number;
  mesh: THREE.Group;
  fuseGlow: THREE.Mesh | null;
  visualOnly: boolean;
  bounceCount: number;
}

interface DeployableFieldEntity {
  id: string;
  ownerId: string;
  itemId: 'shield_drop' | 'regen_pod';
  rarity: Rarity;
  center: THREE.Vector3;
  radius: number;
  ratePerSec: number;
  elapsed: number;
  duration: number;
  visual: PersistentZoneVisual;
  propMesh: THREE.Group;
  vitalsSyncAccum: number;
}

interface SupplyDropEntity {
  id: string;
  x: number;
  y: number;
  targetY: number;
  z: number;
  landmark: string;
  landed: boolean;
  opened: boolean;
  root: THREE.Group;
  parachuteNode: THREE.Object3D | null;
  beacon: THREE.Group;
}

interface WorldGBike {
  id: string;
  x: number;
  y: number;
  z: number;
  yaw: number;
  speed: number;
  velY: number;
  grounded: boolean;
  steerAngle: number;
  leanAngle: number;
  parkTilt: number;
  wheelSpin: number;
  pedalSpin: number;
  rollTickTimer: number;
  bellCooldown: number;
  hopCooldown: number;
  soundCueTimer: number;
  riderId: string | null;
  visual: RideableGBikeVisual;
}

interface SoundEventRecord {
  kind: SoundCueKind;
  x: number;
  z: number;
  maxRange: number;
  age: number;
  ttl: number;
  weight: number;
}

const BOT_CALLSIGNS: Record<ProductHeroId, string[]> = {
  gmail: ['Gmail-AI·01', 'Inbox-AI·04', 'Priority-AI·13', 'Mail-AI·19'],
  drive: ['Drive-AI·02', 'Vault-AI·05', 'Cloud-AI·14', 'Share-AI·20'],
  calendar: ['Calendar-AI·03', 'Chrono-AI·06', 'Block-AI·15', 'Event-AI·21'],
  chat: ['Chat-AI·07', 'Ping-AI·08', 'Thread-AI·16', 'Space-AI·22'],
  slides: ['Slides-AI·09', 'Deck-AI·10', 'Laser-AI·17', 'Stage-AI·23'],
  docs: ['Docs-AI·11', 'Draft-AI·12', 'Version-AI·18', 'Edit-AI·24'],
};

const ALL_HERO_IDS: ProductHeroId[] = ['gmail', 'drive', 'calendar', 'chat', 'slides', 'docs'];

const CENTRAL_STORM_ANCHORS: readonly [number, number][] = [
  [-51, 4],     // Stan Plaza (Core Quad)
  [26, -6],     // Charleston Park
  [-70, 2],     // Quad Skybridge
  [62, 2],      // Joaquin Corridor
  [113, 4],     // Gradient Canopy
  [-35, -12],   // B40 / Partner Plex
  [58, -122],   // Shoreline Amphitheatre Concourse
  [-62, -144],  // Bay Point Shoreline Overlook
  [-185, 2],    // Google 2000 / 1950 Creek Plaza
  [-92, 110],   // 1098 Alta / Huff Corridor
  [28, 114],    // Charleston Campus Courtyard
  [196, -16],   // N Shoreline Blvd / Google 2015
];

/**
 * Calibrated glider hand-grip offset in `hero.model` local space (measured by @anim-blender across all 6 heroes):
 * - Hand_L / Hand_R bone origins (wrists) during Glide: (±0.2350, 1.8290, -0.1243)
 * - Exact curled palm-grip handlebar centers:           (±0.2350, 1.9050, -0.1800)
 * - Adding (0.000, +0.076, -0.056) to live midpoint(Hand_L, Hand_R) locks prop_glider.glb's (0,0,0)
 *   control trapeze bar dead-center inside both palms with 0.00mm drift at any bank angle or dive!
 */
const GLIDE_MOUNT_LOCAL_OFFSET = new THREE.Vector3(0.0, 0.076, -0.056);

/**
 * Calibrated Loot Chest hinge & front-ejection constants for `prop_loot_chest.glb`
 * (verified by @chest-blender in #60):
 * - Front clasps/LED bar face `-Z` in Three.js (`CHEST_FRONT_Z_SIGN = -1`).
 * - `ChestLid` pivots at rear hinge `(0, +0.42, +0.31)` and opens UPWARD & BACKWARD
 *   with POSITIVE X rotation `+1.745` rad (`+100°`).
 */
const CHEST_LID_OPEN_ANGLE_RAD = 1.745;
const CHEST_FRONT_Z_SIGN = -1;

interface QualityConfig {
  maxDpr: number;
  shadowMapSize: number;
  chestCullDist: number;
  chestBeamDist: number;
  lootCullDist: number;
  botCullDist: number;
  botFullAnimDist: number;
}

const QUALITY_PRESETS: Record<QualityPreset, QualityConfig> = {
  performance: {
    maxDpr: 1.0,
    shadowMapSize: 1024,
    chestCullDist: 105,
    chestBeamDist: 75,
    lootCullDist: 95,
    botCullDist: 120,
    botFullAnimDist: 56,
  },
  balanced: {
    maxDpr: 1.25,
    shadowMapSize: 1536,
    chestCullDist: 145,
    chestBeamDist: 95,
    lootCullDist: 120,
    botCullDist: 165,
    botFullAnimDist: 68,
  },
  high: {
    maxDpr: 1.75,
    shadowMapSize: 2048,
    chestCullDist: 210,
    chestBeamDist: 135,
    lootCullDist: 160,
    botCullDist: 240,
    botFullAnimDist: 88,
  },
};

interface GoogleGBusState {
  active: boolean;
  visual: GoogleGBusVisual;
  startX: number;
  startZ: number;
  endX: number;
  endZ: number;
  x: number;
  y: number;
  z: number;
  yaw: number;
  elapsed: number;
  duration: number;
  progress: number;
  hornPlayed: boolean;
  trailTimer: number;
}

export class WorkspaceRoyaleEngine {
  public readonly assetManager: AssetManager;

  private readonly container: HTMLElement;
  private readonly callbacks: HudCallbacks;
  private readonly audio: SoundEngine;
  private readonly renderer: THREE.WebGLRenderer;
  private readonly scene: THREE.Scene;
  private readonly physics: PhysicsWorld;
  private readonly vfx: VfxSystem;
  private readonly camController: ThirdPersonCamera;

  private world: GoogleplexWorld | null = null;
  private splashAttract: SplashAttractDirector | null = null;
  private wantsSplashAttract = false;
  private pendingSplashSceneIndex: number | null = null;
  private ready = false;
  private disposed = false;

  private matchPhase: 'lobby' | 'skydrop' | 'playing' | 'ended' = 'lobby';
  private activeBotDifficulty: BotDifficulty = 'tactical';
  private activeGameMode: GameModeId = 'battle_royale';
  private mouseSensitivity = 1.0;
  private adsSensitivity = 1.0;
  private invertY = false;
  private matchElapsed = 0;
  private lobbyOrbitAngle = 0.6;
  private rafId = 0;
  private lastFrameMs = 0;
  private hudEmitAccum = 0;

  private combatants: Combatant[] = [];
  private player: Combatant | null = null;
  private projectiles: Projectile[] = [];
  private lootDrops: GroundLoot[] = [];
  private lootChests: LootChestEntity[] = [];
  private barriers: HardLightBarrier[] = [];
  private guardrailZones: GuardrailZone[] = [];
  private chronoZones: ChronoZone[] = [];
  private thrownUtilities: ThrownUtilityEntity[] = [];
  private deployableFields: DeployableFieldEntity[] = [];
  private pendingBeams: PendingSlidesBeam[] = [];
  private supplyDrops: SupplyDropEntity[] = [];
  private worldGBikes: WorldGBike[] = [];
  private gbus: GoogleGBusState | null = null;
  private soundEvents: SoundEventRecord[] = [];
  private supplyDropsSpawned = 0;
  private worldVisualTime = 0;

  private nextProjectileSeq = 1;
  private nextLootSeq = 1;
  private nextChestSeq = 1;
  private nextKillFeedSeq = 1;
  private nextBarrierSeq = 1;
  private nextGBikeSeq = 1;
  private nextUtilitySeq = 1;
  private unarmedHintCooldown = 0;

  // 5-Phase Storm State (3× Mountain View Campus: 365m -> 245m -> 155m -> 88m -> 42m -> 14m)
  private stormPhaseIndex = 0; // 0..4 corresponding to STORM_PHASES[0..4]
  private stormMode: 'wait' | 'shrink' = 'wait';
  private stormPhaseTimer = STORM_PHASES[0].waitDuration;
  private stormCenterX = 0;
  private stormCenterZ = 0;
  private stormRadius = 365;
  private stormStartCenterX = 0;
  private stormStartCenterZ = 0;
  private stormStartRadius = 365;
  private nextStormCenterX = -20;
  private nextStormCenterZ = 0;
  private nextStormRadius = STORM_PHASES[0].targetRadius;

  // Input State
  private keys = new Set<string>();
  private mouseLeftDown = false;
  private mouseRightDown = false;
  private crouchToggled = false;
  private sprintLatchedOnReload = false;
  private sprintLatchedOnChannel = false;
  private sprintLatchedOnSlide = false;
  private ctrlSlideConsumed = false;
  private pointerLocked = false;

  // Graphics Quality, Telemetry, Full Tactical Map & Waypoint State
  private qualityPreset: QualityPreset = 'balanced';
  private smoothedFps = 60;
  private lastRenderCalls = 0;
  private lastRenderTriangles = 0;
  private visibleChestCount = 0;
  private visibleBotCount = 0;
  private mapOpen = false;
  private waypoint: MapWaypoint | null = null;

  // Multiplayer Session State (completely inactive in Offline Solo mode)
  private mpActive = false;
  private mpClient: MultiplayerClient | null = null;
  private mpUnsubMessage: (() => void) | null = null;
  private mpRoomCode = '';
  private mpMatchId = '';
  private mpSelfId = '';
  private mpHostId = '';
  private mpFormat: RoomFormat = 'ffa';
  private mpTeamId: TeamId | null = null;
  private mpAliveTeams = 0;
  private mpRng: (() => number) | null = null;
  private mpStateSendAccum = 0;
  private mpBotBatchAccum = 0;
  private mpPendingBikeClaimId: string | null = null;
  private mpPendingBikeClaimAt = 0;
  private mpPendingLootClaims = new Map<string, number>();
  private mpPendingChestOpens = new Set<string>();
  private mpPendingDropOpens = new Set<string>();

  // Live Spectate Mode State (Follow Cam & 6-DOF Free-Form Drone in both Solo & Multiplayer)
  private spectateActive = false;
  private spectateTargetId: string | null = null;
  private spectateMode: SpectateMode = 'follow';
  private freeCamPos = new THREE.Vector3(0, 28, 0);
  private freeCamYaw = 0;
  private freeCamPitch = -0.35;
  private freeCamDragging = false;
  private freeCamLastMouseX = 0;
  private freeCamLastMouseY = 0;

  // Reusable scratch math objects
  private readonly tmpVecA = new THREE.Vector3();
  private readonly tmpVecB = new THREE.Vector3();
  private readonly tmpVecC = new THREE.Vector3();
  private readonly tmpIkA = new THREE.Vector3();
  private readonly tmpIkB = new THREE.Vector3();
  private readonly tmpIkC = new THREE.Vector3();
  private readonly tmpIkD = new THREE.Vector3();
  private readonly tmpIkE = new THREE.Vector3();
  private readonly tmpIkTarget = new THREE.Vector3();
  private readonly tmpIkPole = new THREE.Vector3();
  private readonly tmpSlideCurFoot = new THREE.Vector3();
  private readonly tmpSlideCurKnee = new THREE.Vector3();
  private readonly tmpSlidePrePole = new THREE.Vector3();
  private readonly tmpSlideRootQuat = new THREE.Quaternion();
  private readonly tmpSlideFootQuat = new THREE.Quaternion();
  private readonly tmpSlideEuler = new THREE.Euler(0, 0, 0, 'YXZ');
  private readonly tmpQuatA = new THREE.Quaternion();
  private readonly tmpQuatB = new THREE.Quaternion();
  private readonly tmpQuatC = new THREE.Quaternion();
  private readonly tmpPreBoneQuats = {
    spine: new THREE.Quaternion(),
    chest: new THREE.Quaternion(),
    thighL: new THREE.Quaternion(),
    shinL: new THREE.Quaternion(),
    footL: new THREE.Quaternion(),
    thighR: new THREE.Quaternion(),
    shinR: new THREE.Quaternion(),
    footR: new THREE.Quaternion(),
    upperArmL: new THREE.Quaternion(),
    lowerArmL: new THREE.Quaternion(),
    upperArmR: new THREE.Quaternion(),
    lowerArmR: new THREE.Quaternion(),
  };
  private readonly tmpProj = new THREE.Vector3();

  // Bound event listeners for clean disposal
  private readonly onResizeBound: () => void;
  private readonly onKeyDownBound: (e: KeyboardEvent) => void;
  private readonly onKeyUpBound: (e: KeyboardEvent) => void;
  private readonly onMouseDownBound: (e: MouseEvent) => void;
  private readonly onMouseUpBound: (e: MouseEvent) => void;
  private readonly onMouseMoveBound: (e: MouseEvent) => void;
  private readonly onWheelBound: (e: WheelEvent) => void;
  private readonly onContextMenuBound: (e: MouseEvent) => void;
  private readonly onPointerLockChangeBound: () => void;
  private readonly onBlurBound: () => void;

  constructor(container: HTMLElement, callbacks: HudCallbacks, assetManager?: AssetManager) {
    this.container = container;
    this.callbacks = callbacks;
    this.assetManager = assetManager ?? sharedAssetManager;
    this.audio = sharedAudio;

    this.scene = new THREE.Scene();
    this.physics = new PhysicsWorld();
    this.vfx = new VfxSystem(this.scene);

    const w = Math.max(container.clientWidth || window.innerWidth, 1);
    const h = Math.max(container.clientHeight || window.innerHeight, 1);
    this.camController = new ThirdPersonCamera(w / h);
    // Extend far clip plane for the 3× Mountain View campus (600m × 380m) and 920m California sky dome
    this.camController.camera.far = 1150;
    this.camController.camera.updateProjectionMatrix();

    this.renderer = new THREE.WebGLRenderer({
      antialias: true,
      powerPreference: 'high-performance',
    });
    const qCfg = QUALITY_PRESETS[this.qualityPreset];
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, qCfg.maxDpr));
    this.renderer.setSize(w, h);
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.08;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFShadowMap;
    this.renderer.domElement.style.display = 'block';
    this.renderer.domElement.style.width = '100%';
    this.renderer.domElement.style.height = '100%';
    this.container.appendChild(this.renderer.domElement);

    this.onResizeBound = this.handleResize.bind(this);
    this.onKeyDownBound = this.handleKeyDown.bind(this);
    this.onKeyUpBound = this.handleKeyUp.bind(this);
    this.onMouseDownBound = this.handleMouseDown.bind(this);
    this.onMouseUpBound = this.handleMouseUp.bind(this);
    this.onMouseMoveBound = this.handleMouseMove.bind(this);
    this.onWheelBound = this.handleWheel.bind(this);
    this.onContextMenuBound = (e: MouseEvent) => e.preventDefault();
    this.onPointerLockChangeBound = this.handlePointerLockChange.bind(this);
    this.onBlurBound = this.handleBlur.bind(this);

    window.addEventListener('resize', this.onResizeBound);
    window.addEventListener('keydown', this.onKeyDownBound);
    window.addEventListener('keyup', this.onKeyUpBound);
    window.addEventListener('mouseup', this.onMouseUpBound);
    window.addEventListener('mousemove', this.onMouseMoveBound);
    window.addEventListener('wheel', this.onWheelBound, { passive: true });
    window.addEventListener('blur', this.onBlurBound);
    this.renderer.domElement.addEventListener('mousedown', this.onMouseDownBound);
    this.renderer.domElement.addEventListener('contextmenu', this.onContextMenuBound);
    document.addEventListener('pointerlockchange', this.onPointerLockChangeBound);

    this.lastFrameMs = performance.now();
    this.loop(this.lastFrameMs);
  }

  public isReady(): boolean {
    return this.ready;
  }

  public async preloadAssets(onProgress?: (progress: LoadingProgress) => void): Promise<void> {
    await this.assetManager.preloadAll(onProgress);
    if (!this.world && !this.disposed) {
      this.world = new GoogleplexWorld(this.scene, this.renderer, this.assetManager, this.physics);
      this.world.setShadowMapSize(QUALITY_PRESETS[this.qualityPreset].shadowMapSize);
    }
    this.ready = true;
    if (this.wantsSplashAttract && this.matchPhase === 'lobby' && !this.disposed) {
      this.startSplashAttract();
    }
  }

  public startSplashAttract(): void {
    if (this.disposed) return;
    this.wantsSplashAttract = true;
    if (this.matchPhase !== 'lobby' || !this.world) {
      return;
    }
    if (this.splashAttract && this.splashAttract.isActive()) {
      return;
    }
    if (!this.splashAttract) {
      this.splashAttract = new SplashAttractDirector({
        scene: this.scene,
        assetManager: this.assetManager,
        physics: this.physics,
        vfx: this.vfx,
      });
    }
    const startIdx = this.pendingSplashSceneIndex ?? 0;
    this.pendingSplashSceneIndex = null;
    this.splashAttract.start(startIdx, this.camController.camera, this.world);
  }

  public stopSplashAttract(): void {
    this.wantsSplashAttract = false;
    this.pendingSplashSceneIndex = null;
    if (this.splashAttract) {
      this.splashAttract.stop(this.camController.camera);
      this.splashAttract = null;
    }
    const cam = this.camController.camera;
    if (Math.abs(cam.fov - DEFAULT_LOBBY_FOV) > 0.01) {
      cam.fov = DEFAULT_LOBBY_FOV;
      cam.updateProjectionMatrix();
    }
    if (this.matchPhase === 'lobby') {
      this.updateLobbyCamera(0);
    }
  }

  public setSplashScene(index: number): void {
    const count = SPLASH_SCENES_META.length;
    const safeIdx = Number.isFinite(index) ? ((Math.floor(index) % count) + count) % count : 0;
    if (this.splashAttract && this.splashAttract.isActive()) {
      this.splashAttract.setScene(safeIdx, this.camController.camera, this.world ?? undefined);
    } else {
      this.pendingSplashSceneIndex = safeIdx;
    }
  }

  public getSplashAttractState(): SplashAttractState {
    if (this.splashAttract) {
      return this.splashAttract.getState();
    }
    return {
      active: false,
      sceneIndex: this.pendingSplashSceneIndex ?? 0,
      sceneProgress: 0,
      scenes: SPLASH_SCENES_META.map((s) => ({ ...s })),
    };
  }

  public setQualityPreset(preset: QualityPreset): void {
    if (!(preset in QUALITY_PRESETS)) return;
    this.qualityPreset = preset;
    const cfg = QUALITY_PRESETS[preset];
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, cfg.maxDpr));
    const w = Math.max(this.container.clientWidth || window.innerWidth, 1);
    const h = Math.max(this.container.clientHeight || window.innerHeight, 1);
    this.renderer.setSize(w, h);
    if (this.world) {
      this.world.setShadowMapSize(cfg.shadowMapSize);
    }
  }

  public getQualityPreset(): QualityPreset {
    return this.qualityPreset;
  }

  public getActiveGameMode(): GameModeId {
    return this.activeGameMode;
  }

  public applySettings(settings: Partial<GameSettings>): void {
    if (settings.qualityPreset !== undefined) {
      this.setQualityPreset(settings.qualityPreset);
    }
    if (settings.masterVolume !== undefined) {
      this.audio.setMasterVolume(settings.masterVolume);
    }
    if (settings.muted !== undefined) {
      this.audio.setMuted(settings.muted);
    }
    if (settings.mouseSensitivity !== undefined && Number.isFinite(settings.mouseSensitivity)) {
      this.mouseSensitivity = THREE.MathUtils.clamp(settings.mouseSensitivity, 0.4, 2.2);
    }
    if (settings.adsSensitivity !== undefined && Number.isFinite(settings.adsSensitivity)) {
      this.adsSensitivity = THREE.MathUtils.clamp(settings.adsSensitivity, 0.4, 2.0);
    }
    if (settings.invertY !== undefined) {
      this.invertY = Boolean(settings.invertY);
    }
  }

  public playTestSound(): void {
    this.audio.unlock();
    this.audio.playPickup('rare');
  }

  public getPerfStats(): PerfStats {
    return {
      fps: Math.round(this.smoothedFps),
      drawCalls: this.lastRenderCalls,
      triangles: this.lastRenderTriangles,
      visibleChests: this.visibleChestCount,
      visibleBots: this.visibleBotCount,
    };
  }

  public setMapOpen(open: boolean): void {
    this.mapOpen = open;
    if (open) {
      this.mouseLeftDown = false;
      this.mouseRightDown = false;
      this.keys.clear();
      this.sprintLatchedOnReload = false;
      this.sprintLatchedOnChannel = false;
      this.sprintLatchedOnSlide = false;
      this.ctrlSlideConsumed = false;
      if (document.pointerLockElement === this.renderer.domElement) {
        document.exitPointerLock();
      }
    } else if (!this.spectateActive && (this.matchPhase === 'skydrop' || this.matchPhase === 'playing')) {
      this.requestPointerLock();
    }
    if (this.matchPhase === 'skydrop' || this.matchPhase === 'playing') {
      this.emitHudSnapshot();
    }
  }

  public isMapOpen(): boolean {
    return this.mapOpen;
  }

  public setWaypoint(x: number, z: number): void {
    const cx = THREE.MathUtils.clamp(x, GAME_CONSTANTS.ARENA_MIN_X, GAME_CONSTANTS.ARENA_MAX_X);
    const cz = THREE.MathUtils.clamp(z, GAME_CONSTANTS.ARENA_MIN_Z, GAME_CONSTANTS.ARENA_MAX_Z);
    this.waypoint = { x: cx, z: cz };
    if (this.matchPhase === 'skydrop' || this.matchPhase === 'playing') {
      this.emitHudSnapshot();
    }
  }

  public clearWaypoint(): void {
    if (!this.waypoint) return;
    this.waypoint = null;
    if (this.matchPhase === 'skydrop' || this.matchPhase === 'playing') {
      this.emitHudSnapshot();
    }
  }

  public requestPointerLock(): void {
    this.audio.unlock();
    if (document.pointerLockElement !== this.renderer.domElement) {
      try {
        const result = this.renderer.domElement.requestPointerLock() as unknown as Promise<void> | undefined;
        if (result && typeof result.catch === 'function') {
          result.catch(() => {
            // Ignore Chrome async pointer lock rejection (e.g. ESC cooldown or non-gesture call)
          });
        }
      } catch {
        // Ignore synchronous browser pointer lock rejection when triggered outside gesture
      }
    }
  }

  public pauseToLobby(): void {
    this.detachMpSessionState();
    this.spectateActive = false;
    this.spectateTargetId = null;
    this.spectateMode = 'follow';
    this.freeCamDragging = false;
    this.matchPhase = 'lobby';
    this.mapOpen = false;
    this.waypoint = null;
    this.mouseLeftDown = false;
    this.mouseRightDown = false;
    this.sprintLatchedOnReload = false;
    this.sprintLatchedOnChannel = false;
    this.sprintLatchedOnSlide = false;
    this.ctrlSlideConsumed = false;
    this.keys.clear();
    this.audio.setGliderWind(false);
    if (document.pointerLockElement === this.renderer.domElement) {
      document.exitPointerLock();
    }
    this.emitHudSnapshot();
  }

  public isInMultiplayerMatch(): boolean {
    return this.mpActive;
  }

  public isSpectating(): boolean {
    return this.spectateActive;
  }

  private get isMpHost(): boolean {
    return this.mpActive && this.mpSelfId.length > 0 && this.mpSelfId === this.mpHostId;
  }

  private isFriendly(a: Combatant | null | undefined, b: Combatant | null | undefined): boolean {
    if (!this.mpActive || this.mpFormat !== 'teams') return false;
    if (!a || !b || a.id === b.id) return false;
    return a.teamId !== null && a.teamId === b.teamId;
  }

  private isFriendlyId(a: Combatant | null | undefined, otherId: string | null | undefined): boolean {
    if (!this.mpActive || this.mpFormat !== 'teams' || !a || !a.teamId || !otherId || a.id === otherId) {
      return false;
    }
    const other = this.combatants.find((c) => c.id === otherId);
    return Boolean(other && other.teamId === a.teamId);
  }

  private detachMpSessionState(): void {
    if (this.mpUnsubMessage) {
      this.mpUnsubMessage();
      this.mpUnsubMessage = null;
    }
    this.mpActive = false;
    this.mpClient = null;
    this.mpRoomCode = '';
    this.mpMatchId = '';
    this.mpSelfId = '';
    this.mpHostId = '';
    this.mpFormat = 'ffa';
    this.mpTeamId = null;
    this.mpAliveTeams = 0;
    this.mpRng = null;
    this.mpStateSendAccum = 0;
    this.mpBotBatchAccum = 0;
    this.mpPendingBikeClaimId = null;
    this.mpPendingBikeClaimAt = 0;
    this.mpPendingLootClaims.clear();
    this.mpPendingChestOpens.clear();
    this.mpPendingDropOpens.clear();
  }

  public leaveMultiplayerMatch(): void {
    this.detachMpSessionState();
    this.spectateActive = false;
    this.spectateTargetId = null;
    this.spectateMode = 'follow';
    this.freeCamDragging = false;
    this.matchPhase = 'lobby';
    this.mapOpen = false;
    this.waypoint = null;
    this.mouseLeftDown = false;
    this.mouseRightDown = false;
    this.sprintLatchedOnReload = false;
    this.sprintLatchedOnChannel = false;
    this.sprintLatchedOnSlide = false;
    this.ctrlSlideConsumed = false;
    this.keys.clear();
    this.audio.setGliderWind(false);
    if (document.pointerLockElement === this.renderer.domElement) {
      document.exitPointerLock();
    }
    this.clearMatchEntities();
    this.emitHudSnapshot();
  }

  private getSpectateCandidates(): Combatant[] {
    const excludeId = this.mpActive ? this.mpSelfId : this.player?.id ?? '';
    const alive = this.combatants.filter((c) => c.alive && c.id !== excludeId);
    if (alive.length === 0) return [];
    const score = (c: Combatant): number => {
      const mate = this.mpFormat === 'teams' && this.mpTeamId !== null && c.teamId === this.mpTeamId;
      if (mate && c.isRemoteHuman) return 0;
      if (mate) return 1;
      if (c.isRemoteHuman) return 2;
      return 3;
    };
    return alive.sort((a, b) => score(a) - score(b) || a.id.localeCompare(b.id));
  }

  private pickBestSpectateTarget(preferKillerId?: string | null): Combatant | null {
    const candidates = this.getSpectateCandidates();
    if (candidates.length === 0) {
      this.spectateTargetId = null;
      return null;
    }
    // In Teams mode, prioritize alive teammates first; in FFA, prefer the player who eliminated us
    if (this.mpFormat === 'teams' && this.mpTeamId) {
      const mate = candidates.find((c) => c.teamId === this.mpTeamId);
      if (mate) {
        this.spectateTargetId = mate.id;
        return mate;
      }
    }
    if (preferKillerId) {
      const killer = candidates.find((c) => c.id === preferKillerId);
      if (killer) {
        this.spectateTargetId = killer.id;
        return killer;
      }
    }
    this.spectateTargetId = candidates[0].id;
    return candidates[0];
  }

  public getSpectateMode(): SpectateMode {
    return this.spectateMode;
  }

  public setSpectateMode(mode: SpectateMode): void {
    if (!this.spectateActive || this.spectateMode === mode) return;
    if (mode === 'free') {
      // Seamless handoff from current camera position & orientation with zero jump
      this.freeCamPos.copy(this.camController.camera.position);
      const minY = this.physics.getTerrainHeight(this.freeCamPos.x, this.freeCamPos.z) + 1.2;
      this.freeCamPos.x = THREE.MathUtils.clamp(this.freeCamPos.x, -310, 310);
      this.freeCamPos.z = THREE.MathUtils.clamp(this.freeCamPos.z, -200, 200);
      this.freeCamPos.y = THREE.MathUtils.clamp(this.freeCamPos.y, minY, 185);
      const dir = this.tmpVecA;
      this.camController.camera.getWorldDirection(dir);
      dir.normalize();
      this.freeCamPitch = THREE.MathUtils.clamp(Math.asin(THREE.MathUtils.clamp(dir.y, -1, 1)), -1.48, 1.48);
      this.freeCamYaw = Math.atan2(-dir.x, -dir.z);
      this.spectateMode = 'free';
      this.freeCamDragging = false;
      this.keys.clear();
    } else {
      this.spectateMode = 'follow';
      this.freeCamDragging = false;
      this.keys.clear();
      if (document.pointerLockElement === this.renderer.domElement) {
        document.exitPointerLock();
      }
      let target = this.spectateTargetId
        ? this.combatants.find((c) => c.id === this.spectateTargetId && c.alive) ?? null
        : null;
      if (!target) {
        target = this.pickBestSpectateTarget(null);
      }
      if (target) {
        this.camController.reset(target.pos, target.yaw);
      }
    }
    this.emitHudSnapshot();
  }

  public toggleSpectateMode(): void {
    if (!this.spectateActive) return;
    this.setSpectateMode(this.spectateMode === 'free' ? 'follow' : 'free');
  }

  public startSpectating(): boolean {
    if (this.matchPhase === 'ended' || this.matchPhase === 'lobby') {
      return false;
    }
    const target = this.pickBestSpectateTarget(this.player?.lastAttackerId ?? null);
    if (!target) {
      this.spectateActive = false;
      return false;
    }
    this.spectateActive = true;
    this.spectateMode = 'follow';
    this.freeCamDragging = false;
    this.mapOpen = false;
    this.mouseLeftDown = false;
    this.mouseRightDown = false;
    this.keys.clear();
    if (document.pointerLockElement === this.renderer.domElement) {
      document.exitPointerLock();
    }
    this.camController.reset(target.pos, target.yaw);
    this.emitHudSnapshot();
    return true;
  }

  public cycleSpectateTarget(delta: number): void {
    if (!this.spectateActive || this.spectateMode === 'free') return;
    const candidates = this.getSpectateCandidates();
    if (candidates.length === 0) {
      this.spectateTargetId = null;
      this.setSpectateMode('free');
      return;
    }
    const curIdx = candidates.findIndex((c) => c.id === this.spectateTargetId);
    const step = delta >= 0 ? 1 : -1;
    const nextIdx =
      curIdx < 0 ? 0 : (curIdx + step + candidates.length) % candidates.length;
    const nextTarget = candidates[nextIdx];
    this.spectateTargetId = nextTarget.id;
    this.camController.reset(nextTarget.pos, nextTarget.yaw);
    this.emitHudSnapshot();
  }

  private getCameraFocusCombatant(): Combatant | null {
    if (this.spectateActive && this.spectateTargetId) {
      const target = this.combatants.find((c) => c.id === this.spectateTargetId && c.alive);
      if (target) return target;
    }
    return this.player;
  }

  private getCameraFocusPos(): THREE.Vector3 {
    if (this.spectateActive && this.spectateMode === 'free') {
      return this.freeCamPos;
    }
    const focus = this.getCameraFocusCombatant();
    return focus ? focus.pos : this.camController.camera.position;
  }

  private computeAliveTeamsCount(): number {
    if (!this.mpActive || this.mpFormat !== 'teams') {
      return this.combatants.filter((c) => c.alive).length;
    }
    const teams = new Set<TeamId>();
    for (const c of this.combatants) {
      if (c.alive && c.teamId) {
        teams.add(c.teamId);
      }
    }
    return teams.size;
  }

  public startMultiplayerMatch(
    client: MultiplayerClient,
    payload: MatchStartPayload,
    selfId: string
  ): void {
    this.stopSplashAttract();
    this.detachMpSessionState();
    this.spectateActive = false;
    this.spectateTargetId = null;

    if (!this.world) {
      this.world = new GoogleplexWorld(this.scene, this.renderer, this.assetManager, this.physics);
      this.world.setShadowMapSize(QUALITY_PRESETS[this.qualityPreset].shadowMapSize);
    }
    this.audio.unlock();
    this.clearMatchEntities();

    this.mpActive = true;
    this.mpClient = client;
    this.mpRoomCode = client.roomCode ?? '';
    this.mpMatchId = payload.matchId;
    this.mpSelfId = selfId;
    this.mpHostId = payload.hostId;
    this.mpFormat = payload.settings.format;
    this.mpRng = createSeededRng(payload.seed);

    const mode = GAME_MODES[payload.settings.mode] ?? GAME_MODES.battle_royale;
    this.activeGameMode = mode.id;
    this.activeBotDifficulty = mode.forceBotDifficulty ?? payload.settings.botDifficulty;
    this.matchPhase = 'skydrop';
    this.matchElapsed = 0;
    this.supplyDropsSpawned = 0;
    this.unarmedHintCooldown = 0;
    this.crouchToggled = false;
    this.sprintLatchedOnReload = false;
    this.sprintLatchedOnChannel = false;
    this.sprintLatchedOnSlide = false;
    this.ctrlSlideConsumed = false;
    this.mapOpen = false;
    this.waypoint = null;
    this.visibleChestCount = 0;
    this.visibleBotCount = 0;
    this.mouseLeftDown = false;
    this.mouseRightDown = false;
    this.keys.clear();

    // Deterministic Storm Anchor matching server payload across every peer
    const anchorIdx =
      ((payload.stormAnchorIndex % CENTRAL_STORM_ANCHORS.length) + CENTRAL_STORM_ANCHORS.length) %
      CENTRAL_STORM_ANCHORS.length;
    const [anchorX, anchorZ] = CENTRAL_STORM_ANCHORS[anchorIdx];
    this.stormPhaseIndex = 0;
    this.stormMode = 'wait';
    this.stormCenterX = 0;
    this.stormCenterZ = 0;
    this.stormRadius = mode.initialStormRadius;
    this.stormStartCenterX = 0;
    this.stormStartCenterZ = 0;
    this.stormStartRadius = mode.initialStormRadius;

    if (mode.stormEnabled) {
      this.stormPhaseTimer = STORM_PHASES[0].waitDuration * mode.stormPaceMult;
      this.nextStormCenterX = anchorX + payload.stormOffsetX;
      this.nextStormCenterZ = anchorZ + payload.stormOffsetZ;
      this.nextStormRadius = Math.min(mode.initialStormRadius, STORM_PHASES[0].targetRadius);
    } else {
      this.stormPhaseTimer = 0;
      this.nextStormCenterX = 0;
      this.nextStormCenterZ = 0;
      this.nextStormRadius = mode.initialStormRadius;
    }
    this.world.updateStormVisual(this.stormCenterX, this.stormCenterZ, this.stormRadius, 0);

    // Deterministic shared campus chests (identical chest_1..N IDs and Tier 1-3 rolls!) & 18 GBikes
    this.spawnInitialCampusChests(this.mpRng);
    this.spawnInitialCampusGBikes();

    // Deterministic edge-to-edge Flying Google GBus route shared identically across all MP peers
    const gbus = this.spawnGBus(this.mpRng);

    const selfSpec = payload.combatants.find((s) => s.id === selfId) ?? null;
    this.mpTeamId = this.mpFormat === 'teams' ? (selfSpec?.teamId ?? null) : null;

    let botIndex = 0;
    const totalBots = Math.max(1, payload.combatants.filter((s) => !s.isHuman).length);

    for (let i = 0; i < payload.combatants.length; i++) {
      const spec = payload.combatants[i];
      const isSelf = spec.id === selfId;
      const isRemoteHuman = spec.isHuman && !isSelf;
      const teamId: TeamId | null = this.mpFormat === 'teams' ? spec.teamId : null;
      const botTier: BotTier | undefined = !spec.isHuman ? (spec.botTier ?? 'tactical') : undefined;
      const brain =
        !spec.isHuman && this.isMpHost
          ? new BotBrain(getBotProfile(botTier ?? 'tactical'), this.world.landmarks)
          : undefined;
      const busDropProgress = !spec.isHuman ? 0.1 + this.mpRng() * 0.76 : 0.94;

      const combatant = this.spawnCombatant({
        id: spec.id,
        name: spec.name,
        isPlayer: isSelf,
        isRemoteHuman,
        teamId,
        heroId: spec.heroId,
        botTier,
        brain,
        botIndex: !spec.isHuman ? botIndex++ : undefined,
        totalBots,
        x: gbus.startX,
        y: gbus.y - 1.2,
        z: gbus.startZ,
        yaw: gbus.yaw,
        inBus: true,
        busDropProgress,
      });

      if (isSelf) {
        this.player = combatant;
      } else {
        const isMate = this.mpFormat === 'teams' && teamId !== null && teamId === this.mpTeamId;
        const teamColorCss = teamId ? TEAM_CONFIG[teamId].colorCss : null;
        if (isRemoteHuman || isMate) {
          combatant.hero.setNameplate(spec.name, teamColorCss);
        }
        if (isMate && teamId) {
          const hpMat = combatant.hero.hpBarFill.material as THREE.MeshBasicMaterial;
          hpMat.color.setHex(TEAM_CONFIG[teamId].hex);
        }
      }
    }

    this.mpAliveTeams = this.computeAliveTeamsCount();

    // Subscribe to live GameRoom server broadcasts
    this.mpUnsubMessage = client.onMessage((msg) => this.handleMpMessage(msg));

    if (this.player) {
      this.camController.reset(this.player.pos, this.player.yaw);
    }
    this.audio.setGliderWind(false, false);
    this.requestPointerLock();

    if (this.mpFormat === 'teams' && this.mpTeamId) {
      const tLabel = TEAM_CONFIG[this.mpTeamId].label.toUpperCase();
      this.callbacks.onAnnouncement(
        `TEAM ${tLabel} — GOOGLE GBUS DEPARTING`,
        `Room ${this.mpRoomCode} · Press SPACE to jump & survey the campus`
      );
    } else {
      this.callbacks.onAnnouncement(
        'GOOGLE GBUS DEPARTING',
        `Private Room ${this.mpRoomCode} · ${payload.combatants.length} Combatants · Press SPACE to Jump`
      );
    }
    this.emitHudSnapshot();
  }

  public startMatch(
    heroId: ProductHeroId,
    botDifficulty: BotDifficulty,
    modeId: GameModeId = 'battle_royale'
  ): void {
    this.detachMpSessionState();
    this.spectateActive = false;
    this.spectateTargetId = null;
    this.stopSplashAttract();
    if (!this.world) {
      this.world = new GoogleplexWorld(this.scene, this.renderer, this.assetManager, this.physics);
      this.world.setShadowMapSize(QUALITY_PRESETS[this.qualityPreset].shadowMapSize);
    }
    this.audio.unlock();
    this.clearMatchEntities();

    const mode = GAME_MODES[modeId] ?? GAME_MODES.battle_royale;
    this.activeGameMode = mode.id;
    const effectiveDiff = mode.forceBotDifficulty ?? botDifficulty;
    this.activeBotDifficulty = effectiveDiff;
    this.matchPhase = 'skydrop';
    this.matchElapsed = 0;
    this.supplyDropsSpawned = 0;
    this.unarmedHintCooldown = 0;
    this.crouchToggled = false;
    this.sprintLatchedOnReload = false;
    this.sprintLatchedOnChannel = false;
    this.sprintLatchedOnSlide = false;
    this.ctrlSlideConsumed = false;
    this.mapOpen = false;
    this.waypoint = null;
    this.visibleChestCount = 0;
    this.visibleBotCount = 0;
    this.mouseLeftDown = false;
    this.mouseRightDown = false;
    this.keys.clear();

    // Initialize Storm per Play Mode (disabled & parked outside arena in Campus Free Roam)
    const [anchorX, anchorZ] =
      CENTRAL_STORM_ANCHORS[Math.floor(Math.random() * CENTRAL_STORM_ANCHORS.length)];
    this.stormPhaseIndex = 0;
    this.stormMode = 'wait';
    this.stormCenterX = 0;
    this.stormCenterZ = 0;
    this.stormRadius = mode.initialStormRadius;
    this.stormStartCenterX = 0;
    this.stormStartCenterZ = 0;
    this.stormStartRadius = mode.initialStormRadius;

    if (mode.stormEnabled) {
      this.stormPhaseTimer = STORM_PHASES[0].waitDuration * mode.stormPaceMult;
      this.nextStormCenterX = anchorX + (Math.random() - 0.5) * 24;
      this.nextStormCenterZ = anchorZ + (Math.random() - 0.5) * 24;
      this.nextStormRadius = Math.min(mode.initialStormRadius, STORM_PHASES[0].targetRadius);
    } else {
      this.stormPhaseTimer = 0;
      this.nextStormCenterX = 0;
      this.nextStormCenterZ = 0;
      this.nextStormRadius = mode.initialStormRadius;
    }
    this.world.updateStormVisual(this.stormCenterX, this.stormCenterZ, this.stormRadius, 0);

    // Populate closed Tier 1–3 Blender Loot Chests across all authentic Googleplex loot spots (ZERO pre-existing bare ground loot!)
    this.spawnInitialCampusChests();
    // Spawn all 18 rideable Google GBikes across campus corrals & iconic hubs
    this.spawnInitialCampusGBikes();

    // Launch the winged Flying Google GBus on a fresh edge-to-edge flight path across the Googleplex
    const gbus = this.spawnGBus(Math.random);

    // Spawn local player aboard the GBus
    const heroDef = HERO_MAP[heroId];
    this.player = this.spawnCombatant({
      id: 'player',
      name: heroDef.personaName,
      isPlayer: true,
      heroId,
      x: gbus.startX,
      y: gbus.y - 1.2,
      z: gbus.startZ,
      yaw: gbus.yaw,
      inBus: true,
      busDropProgress: GAME_CONSTANTS.GBUS_AUTO_EJECT_PROGRESS,
    });

    // Spawn mode-configured AI Workspace Bots aboard the GBus with staggered drop timing
    const desiredBots = Math.max(0, mode.totalCombatants - 1);
    const botCount = desiredBots;
    const botTiers = assignBotTiers(effectiveDiff, botCount);
    const nameCounters: Record<ProductHeroId, number> = {
      gmail: 0,
      drive: 0,
      calendar: 0,
      chat: 0,
      slides: 0,
      docs: 0,
    };

    for (let i = 0; i < botCount; i++) {
      const bHeroId = ALL_HERO_IDS[i % ALL_HERO_IDS.length];
      const names = BOT_CALLSIGNS[bHeroId];
      const nIdx = nameCounters[bHeroId]++;
      const botName = names[nIdx % names.length] + (nIdx >= names.length ? ` ${nIdx + 1}` : '');
      const tier = botTiers[i];
      const profile = getBotProfile(tier);
      this.spawnCombatant({
        id: `bot_${i + 1}`,
        name: botName,
        isPlayer: false,
        heroId: bHeroId,
        botTier: tier,
        brain: new BotBrain(profile, this.world.landmarks),
        botIndex: i,
        totalBots: botCount,
        x: gbus.startX,
        y: gbus.y - 1.2,
        z: gbus.startZ,
        yaw: gbus.yaw,
        inBus: true,
        busDropProgress: 0.1 + Math.random() * 0.76,
      });
    }

    this.camController.reset(this.player.pos, this.player.yaw);
    this.audio.setGliderWind(false, false);
    this.requestPointerLock();

    if (mode.id === 'blitz') {
      this.callbacks.onAnnouncement(
        'BLITZ ROYALE — GBUS DEPARTING',
        'Press SPACE to Jump · 1.8× Faster Storm · Tier 2–3 Chests'
      );
    } else if (mode.id === 'sniper_showdown') {
      this.callbacks.onAnnouncement(
        'SNIPER SHOWDOWN — GBUS DEPARTING',
        'Press SPACE to Jump · Longbow .308 Exclusive · Claim Rooftops'
      );
    } else if (mode.id === 'campus_practice') {
      this.callbacks.onAnnouncement(
        'CAMPUS FREE ROAM — GBUS TOUR',
        'Press SPACE to Jump · No Storm · Explore the 3× Googleplex'
      );
    } else {
      this.callbacks.onAnnouncement(
        'GOOGLE GBUS DEPARTING',
        'Press SPACE to Jump · [M] Tactical Map · Land & Open Chests [E]'
      );
    }
    this.emitHudSnapshot();
  }

  private spawnCombatant(opts: {
    id: string;
    name: string;
    isPlayer: boolean;
    isRemoteHuman?: boolean;
    teamId?: TeamId | null;
    heroId: ProductHeroId;
    botTier?: BotTier;
    brain?: BotBrain;
    botIndex?: number;
    totalBots?: number;
    x: number;
    y: number;
    z: number;
    yaw: number;
    inBus?: boolean;
    busDropProgress?: number;
  }): Combatant {
    const mode = GAME_MODES[this.activeGameMode] ?? GAME_MODES.battle_royale;
    const inBus = Boolean(opts.inBus);
    const hero = this.assetManager.instantiateHero(opts.heroId, {
      includeOverhead: !opts.isPlayer,
    });
    hero.root.position.set(opts.x, opts.y, opts.z);
    hero.root.rotation.y = opts.yaw;
    hero.root.visible = !inBus;
    hero.crossFade('Glide', 0.05);
    this.scene.add(hero.root);

    const gliderMesh = this.assetManager.instantiateProp('glider');
    gliderMesh.position.set(0, 0, 0);
    hero.gliderMount.add(gliderMesh);
    gliderMesh.visible = !inBus;

    const slots = createStarterLoadout();
    const startMana = Math.min(GAME_CONSTANTS.MAX_MANA, mode.startMana);
    const totalBots = Math.max(1, opts.totalBots ?? Math.max(1, mode.totalCombatants - 1));
    const combatant: Combatant = {
      id: opts.id,
      name: opts.name,
      isPlayer: opts.isPlayer,
      isRemoteHuman: Boolean(opts.isRemoteHuman),
      teamId: opts.teamId ?? null,
      heroId: opts.heroId,
      botTier: opts.botTier,
      brain: opts.brain,
      netTarget: undefined,
      remoteRewindGhostTimer: 0,
      hero,
      gliderMesh,
      weaponInstance: null,
      equippedKey: '',
      pos: new THREE.Vector3(opts.x, opts.y, opts.z),
      vel: new THREE.Vector3(0, -8, 0),
      yaw: opts.yaw,
      pitch: opts.isPlayer ? -0.42 : 0,
      alive: true,
      inBus,
      busDropProgress: opts.busDropProgress ?? 0.5,
      skyDropping: true,
      grounded: false,
      crouching: false,
      sliding: false,
      slideTimer: 0,
      slideElapsed: 0,
      slideCooldown: 0,
      slideDirX: 0,
      slideDirZ: -1,
      slideSpeed: 0,
      slidePoseBlend: 0,
      slideVfxTimer: 0,
      slideInitiatedByCtrl: false,
      sprinting: false,
      isAds: false,
      ridingGBikeId: null,
      surface: 'stone',
      health: GAME_CONSTANTS.START_HEALTH,
      shield: GAME_CONSTANTS.START_SHIELD,
      mana: startMana,
      eliminations: 0,
      headshots: 0,
      damageDealt: 0,
      slots,
      activeSlot: 0,
      fireCooldown: 0,
      isReloading: false,
      reloadTimer: 0,
      reloadDuration: 1,
      lastShotAt: -10,
      semiAutoLatch: false,
      ultCooldown: 0,
      silencedSec: 0,
      blindedSec: 0,
      flashBlindPeak: 0,
      hastedSec: 0,
      slowedSec: 0,
      revealedSec: 0,
      revealedAllSec: 0,
      channel: null,
      hitFlashTimer: 0,
      footstepTimer: 0,
      stormTickAccum: 0,
      lastDamagedAt: -10,
      lastAttackerId: null,
      recentDamageTaken: 0,
      gliderTrailTimer: Math.random() * 0.2,
      history: [
        {
          pos: new THREE.Vector3(opts.x, opts.y, opts.z),
          health: GAME_CONSTANTS.START_HEALTH,
          shield: GAME_CONSTANTS.START_SHIELD,
          timestamp: 0,
        },
      ],
      historySampleTimer: 0,
      rewind: {
        active: false,
        elapsed: 0,
        duration: 0.45,
        path: [],
        targetHealth: GAME_CONSTANTS.START_HEALTH,
        targetShield: GAME_CONSTANTS.START_SHIELD,
        ghostTimer: 0,
      },
      prevYaw: opts.yaw,
      prevVelX: 0,
      prevVelZ: 0,
      leanPitch: 0,
      leanBank: 0,
      airborneTime: 0,
      peakFallSpeed: 0,
      squashTimer: 0,
      squashDuration: 0.18,
      squashIntensity: 0,
      takeoffTimer: 0,
      glideBank: 0,
      glidePitch: -0.08,
      smoothAimPitch: 0,
      twoHandBlend: 1,
      hasProcBoneUndo: false,
      procBoneUndo: {
        spine: new THREE.Quaternion(),
        chest: new THREE.Quaternion(),
        thighL: new THREE.Quaternion(),
        shinL: new THREE.Quaternion(),
        footL: new THREE.Quaternion(),
        thighR: new THREE.Quaternion(),
        shinR: new THREE.Quaternion(),
        footR: new THREE.Quaternion(),
        upperArmL: new THREE.Quaternion(),
        lowerArmL: new THREE.Quaternion(),
        upperArmR: new THREE.Quaternion(),
        lowerArmR: new THREE.Quaternion(),
      },
      // Evenly stagger 10 Hz bot thinking across [0.00, 0.10)s so ~2-3 bots think per 60fps frame
      aiThinkTimer: opts.isPlayer ? 0 : ((opts.botIndex ?? 0) / totalBots) * 0.1,
      aiThinkAccumDt: 0.016,
      cachedDecision: null,
      animAccumDt: 0,
      animFrameSkip: (opts.botIndex ?? 0) % 3,
      castingShadow: true,
    };

    // Advance mixer 1 tiny step on spawn and lock gliderMount immediately to live palm midpoint
    hero.mixer.update(0.001);
    this.syncGliderMountToHands(combatant);

    this.syncEquippedWeaponVisual(combatant);
    if (combatant.weaponInstance) {
      combatant.weaponInstance.root.visible = false; // Hidden while gliding
    }

    this.combatants.push(combatant);
    return combatant;
  }

  private clearMatchEntities(): void {
    for (const c of this.combatants) {
      this.scene.remove(c.hero.root);
    }
    this.combatants.length = 0;
    this.player = null;

    for (const p of this.projectiles) {
      if (p.mesh) this.scene.remove(p.mesh);
    }
    this.projectiles.length = 0;

    for (const l of this.lootDrops) {
      this.scene.remove(l.visual.root);
    }
    this.lootDrops.length = 0;

    for (const ch of this.lootChests) {
      this.scene.remove(ch.visual.root);
    }
    this.lootChests.length = 0;

    for (const b of this.barriers) {
      this.scene.remove(b.mesh);
      this.physics.removeCollider(b.colliderId);
    }
    this.barriers.length = 0;

    for (const z of this.guardrailZones) {
      z.visual.dispose();
    }
    this.guardrailZones.length = 0;

    for (const z of this.chronoZones) {
      z.visual.dispose();
    }
    this.chronoZones.length = 0;

    for (const u of this.thrownUtilities) {
      this.scene.remove(u.mesh);
    }
    this.thrownUtilities.length = 0;

    for (const f of this.deployableFields) {
      f.visual.dispose();
      this.scene.remove(f.propMesh);
    }
    this.deployableFields.length = 0;

    for (const s of this.supplyDrops) {
      this.scene.remove(s.root);
      this.scene.remove(s.beacon);
    }
    this.supplyDrops.length = 0;

    for (const bike of this.worldGBikes) {
      this.scene.remove(bike.visual.root);
    }
    this.worldGBikes.length = 0;

    if (this.gbus) {
      this.scene.remove(this.gbus.visual.root);
      this.gbus = null;
    }

    this.soundEvents.length = 0;
    this.pendingBeams.length = 0;
    this.vfx.clear();

    // Reset deterministic entity ID counters so chest_1..N and gbike_1..18 match 1:1 across all MP peers
    this.nextProjectileSeq = 1;
    this.nextLootSeq = 1;
    this.nextChestSeq = 1;
    this.nextBarrierSeq = 1;
    this.nextGBikeSeq = 1;
    this.nextUtilitySeq = 1;
  }

  private computeChestYaw(x: number, y: number, z: number): number {
    // Orient chest front cleanly toward nearest open plaza/courtyard/room center (and away from Stan's pedestal)
    let lookX = x < 55 ? -51 : 113;
    let lookZ = 4;
    if (Math.hypot(x + 51, z - 4) < 12) {
      // Around Stan Plaza: face radially outward from Stan pedestal
      lookX = x + (x + 51);
      lookZ = z + (z - 4);
    } else if (x < -160 || x > 165 || z < -95 || z > 90) {
      // Outer 3× Mountain View campus zones: face toward each landmark's central courtyard/stage/field
      const outerCenters: [number, number][] = [
        [58, -148],    // Shoreline Amphitheatre
        [-220, -134],  // Athletic Field
        [-225, 2],     // Google 2000 / 1950
        [-108, 126],   // 1098 Alta Complex
        [28, 134],     // Charleston Campus
        [234, -22],    // Google 2015 / Stierlin Ct
        [236, -140],   // Google CL2 Crittenden
        [234, 122],    // Google 1395 Charleston
        [-62, -144],   // Bay Point Shoreline Overlook
      ];
      let bestDist = Infinity;
      for (const [cx, cz] of outerCenters) {
        const d = Math.hypot(x - cx, z - cz);
        if (d < bestDist) {
          bestDist = d;
          lookX = cx;
          lookZ = cz;
        }
      }
    } else if (y < 0.25 && x < 10) {
      // Ground-floor offices (B40/B41/B42/B43): face toward the room's central aisle
      const officeCenters: [number, number][] = [
        [-41, -21],
        [-112, -31],
        [-117, 23],
        [-58, 33],
      ];
      let bestDist = Infinity;
      for (const [cx, cz] of officeCenters) {
        const d = Math.hypot(x - cx, z - cz);
        if (d < bestDist && d < 46) {
          bestDist = d;
          lookX = cx;
          lookZ = cz;
        }
      }
    }
    const dx = lookX - x;
    const dz = lookZ - z;
    if (Math.hypot(dx, dz) < 0.5) return 0;
    // If CHEST_FRONT_Z_SIGN === 1 (+Z local front), world front is (sin(yaw), cos(yaw)) -> atan2(dx, dz)
    // If CHEST_FRONT_Z_SIGN === -1 (-Z local front), world front is (-sin(yaw), -cos(yaw)) -> atan2(-dx, -dz)
    return CHEST_FRONT_Z_SIGN >= 0 ? Math.atan2(dx, dz) : Math.atan2(-dx, -dz);
  }

  private rollChestTierSeeded(highTier: boolean, rng?: () => number): ChestTier {
    if (!rng) return rollChestTier(highTier);
    const r = rng();
    if (highTier) {
      return r < 0.55 ? 2 : 3;
    }
    if (r < 0.50) return 1;
    if (r < 0.85) return 2;
    return 3;
  }

  private spawnInitialCampusChests(rng?: () => number): void {
    if (!this.world) return;
    const mode = GAME_MODES[this.activeGameMode] ?? GAME_MODES.battle_royale;
    for (const spot of this.world.lootSpots) {
      let tier = this.rollChestTierSeeded(spot.highTier, rng);
      if (mode.minChestTier && tier < mode.minChestTier) {
        tier = mode.minChestTier;
      }
      const yaw = this.computeChestYaw(spot.x, spot.y, spot.z);
      const visual = this.assetManager.instantiateLootChest(tier);
      visual.root.position.set(spot.x, spot.y, spot.z);
      visual.root.rotation.y = yaw;
      this.scene.add(visual.root);

      this.lootChests.push({
        id: `chest_${this.nextChestSeq++}`,
        x: spot.x,
        y: spot.y,
        z: spot.z,
        yaw,
        tier,
        landmark: spot.landmark,
        opened: false,
        lidProgress: 0,
        visual,
        pulsePhase: (rng ? rng() : Math.random()) * Math.PI * 2,
      });
    }
  }

  private spawnInitialCampusGBikes(): void {
    if (!this.world) return;
    for (const spawn of this.world.gbikeSpawns) {
      const visual = this.assetManager.instantiateRideableGBike(spawn.variant);
      const parkTilt = 0.14;
      visual.root.position.set(spawn.x, spawn.y, spawn.z);
      visual.root.rotation.order = 'YXZ';
      visual.root.rotation.set(0, spawn.rotY, parkTilt);
      if (visual.frontAssembly) {
        visual.frontAssembly.rotation.y = 0.16;
      }
      this.scene.add(visual.root);

      this.worldGBikes.push({
        id: `gbike_${this.nextGBikeSeq++}`,
        x: spawn.x,
        y: spawn.y,
        z: spawn.z,
        yaw: spawn.rotY,
        speed: 0,
        velY: 0,
        grounded: true,
        steerAngle: 0.16,
        leanAngle: 0,
        parkTilt,
        wheelSpin: 0,
        pedalSpin: 0,
        rollTickTimer: 0,
        bellCooldown: 0,
        hopCooldown: 0,
        soundCueTimer: 0,
        riderId: null,
        visual,
      });
    }
  }

  private spawnLootDrop(
    x: number,
    y: number,
    z: number,
    kind: 'weapon' | 'item',
    itemId: WeaponId | UtilityItemId,
    rarity: Rarity,
    count = 1,
    popFrom?: { x: number; y: number; z: number },
    explicitId?: string
  ): GroundLoot {
    const id = explicitId ?? `loot_${this.nextLootSeq++}`;
    const existing = this.lootDrops.find((l) => l.id === id);
    if (existing) return existing;
    const visual = this.assetManager.createLootDropVisual(kind, itemId, rarity);
    if (popFrom) {
      visual.root.position.set(popFrom.x, popFrom.y, popFrom.z);
    } else {
      visual.root.position.set(x, y, z);
    }
    this.scene.add(visual.root);
    const entry: GroundLoot = {
      id,
      x,
      y,
      z,
      kind,
      itemId,
      rarity,
      count,
      visual,
      bobPhase: Math.random() * Math.PI * 2,
      popStartX: popFrom?.x,
      popStartY: popFrom?.y,
      popStartZ: popFrom?.z,
      popProgress: popFrom ? 0 : 1,
    };
    this.lootDrops.push(entry);
    return entry;
  }

  private computeChestEjectedLoot(chest: LootChestEntity, opener: Combatant): SyncedGroundLoot[] {
    const drops = rollChestLoot(chest.tier, this.activeGameMode);
    const frontYaw =
      CHEST_FRONT_Z_SIGN >= 0
        ? Math.atan2(Math.sin(chest.yaw), Math.cos(chest.yaw))
        : Math.atan2(-Math.sin(chest.yaw), -Math.cos(chest.yaw));
    const openerDx = opener.pos.x - chest.x;
    const openerDz = opener.pos.z - chest.z;
    const openerYaw =
      Math.hypot(openerDx, openerDz) > 0.25 ? Math.atan2(openerDx, openerDz) : frontYaw;

    const probeOrigin = new THREE.Vector3(chest.x, chest.y + 0.75, chest.z);
    const frontProbe = new THREE.Vector3(
      chest.x + Math.sin(frontYaw) * 1.9,
      chest.y + 0.75,
      chest.z + Math.cos(frontYaw) * 1.9
    );
    const frontSupportY = this.physics.getSupportHeight(frontProbe.x, frontProbe.z, chest.y + 1.2, 0.3, 0.5);
    const frontClear =
      this.physics.hasLineOfSight(probeOrigin, frontProbe) && Math.abs(frontSupportY - chest.y) <= 1.25;
    const baseArcYaw = frontClear ? frontYaw : openerYaw;

    const arcSpan = drops.length === 1 ? 0 : drops.length === 2 ? 0.92 : 1.56;
    const result: SyncedGroundLoot[] = [];

    drops.forEach((item, idx) => {
      const frac = drops.length === 1 ? 0 : idx / (drops.length - 1) - 0.5;
      const ang = baseArcYaw + frac * arcSpan;
      let ejectDist = drops.length === 1 ? 1.55 : 1.75;
      let lx = THREE.MathUtils.clamp(
        chest.x + Math.sin(ang) * ejectDist,
        GAME_CONSTANTS.ARENA_MIN_X + 3,
        GAME_CONSTANTS.ARENA_MAX_X - 3
      );
      let lz = THREE.MathUtils.clamp(
        chest.z + Math.cos(ang) * ejectDist,
        GAME_CONSTANTS.ARENA_MIN_Z + 3,
        GAME_CONSTANTS.ARENA_MAX_Z - 3
      );

      const itemProbe = new THREE.Vector3(lx, chest.y + 0.75, lz);
      let ly = this.physics.getSupportHeight(lx, lz, chest.y + 1.2, 0.3, 0.5);
      if (!this.physics.hasLineOfSight(probeOrigin, itemProbe) || Math.abs(ly - chest.y) > 1.25) {
        ejectDist = 1.1;
        lx = chest.x + Math.sin(openerYaw + frac * 0.65) * ejectDist;
        lz = chest.z + Math.cos(openerYaw + frac * 0.65) * ejectDist;
        ly = this.physics.getSupportHeight(lx, lz, chest.y + 1.2, 0.3, 0.5);
        if (Math.abs(ly - chest.y) > 1.35) {
          lx = chest.x + Math.sin(openerYaw) * 0.75;
          lz = chest.z + Math.cos(openerYaw) * 0.75;
          ly = chest.y;
        }
      }

      result.push({
        id: `${chest.id}_item_${idx}`,
        kind: item.kind,
        itemId: item.id,
        rarity: item.rarity,
        count: item.count,
        x: Number(lx.toFixed(2)),
        y: Number(ly.toFixed(2)),
        z: Number(lz.toFixed(2)),
      });
    });

    return result;
  }

  private applyOpenedLootChest(
    chest: LootChestEntity,
    openerIsLocalPlayer: boolean,
    syncedLoot: SyncedGroundLoot[]
  ): void {
    if (chest.opened) return;
    chest.opened = true;
    chest.lidProgress = 0;

    // Cancel any other combatant channeling this same chest
    for (const c of this.combatants) {
      if (c.channel?.kind === 'chest' && c.channel.chestId === chest.id) {
        this.cancelChannel(c);
      }
    }

    chest.visual.beam.visible = false;
    chest.visual.markOpened?.();

    const tierCfg = CHEST_TIER_CONFIG[chest.tier];
    const burstPos = new THREE.Vector3(chest.x, chest.y + 0.65, chest.z);
    this.vfx.spawnStatusBurst(burstPos, tierCfg.hex);
    this.vfx.spawnExpandingRing(
      new THREE.Vector3(chest.x, chest.y, chest.z),
      chest.tier === 3 ? 3.8 : chest.tier === 2 ? 3.0 : 2.3,
      tierCfg.hex,
      0.46
    );
    this.vfx.spawnHitImpact(burstPos, {
      isHeadshot: chest.tier === 3,
      isShield: chest.tier === 2,
    });

    const listenerPos = this.getCameraFocusPos();
    const distToListener = Math.hypot(chest.x - listenerPos.x, chest.z - listenerPos.z);
    this.audio.playChestOpenComplete(
      chest.tier,
      openerIsLocalPlayer ? 0 : distToListener,
      openerIsLocalPlayer ? 0 : this.computeSpatialPan(burstPos)
    );

    const ejectOrigin = { x: chest.x, y: chest.y + 0.38, z: chest.z };
    for (const item of syncedLoot) {
      this.spawnLootDrop(
        item.x,
        item.y,
        item.z,
        item.kind,
        item.itemId as WeaponId | UtilityItemId,
        item.rarity,
        item.count ?? 1,
        ejectOrigin,
        item.id
      );
    }
  }

  private openLootChest(chest: LootChestEntity, opener: Combatant): void {
    if (chest.opened) return;
    if (this.mpActive) {
      if (!opener.isPlayer && !(this.isMpHost && !opener.isRemoteHuman)) return;
      if (this.mpPendingChestOpens.has(chest.id)) return;
      this.mpPendingChestOpens.add(chest.id);
      const loot = this.computeChestEjectedLoot(chest, opener);
      this.mpClient?.send({
        type: 'chest_open',
        chestId: chest.id,
        ...(opener.isPlayer ? {} : { openerId: opener.id }),
        loot,
      });
      return;
    }

    const drops = this.computeChestEjectedLoot(chest, opener);
    this.applyOpenedLootChest(chest, opener.isPlayer, drops);
  }

  // =========================================================================
  // MAIN SIMULATION LOOP
  // =========================================================================

  private loop = (nowMs: number): void => {
    if (this.disposed) return;
    this.rafId = requestAnimationFrame(this.loop);

    const rawDeltaMs = nowMs - this.lastFrameMs;
    const dt = Math.min(0.05, Math.max(0.001, rawDeltaMs / 1000));
    this.lastFrameMs = nowMs;
    if (rawDeltaMs > 0 && rawDeltaMs < 2000) {
      const instantFps = 1000 / Math.max(1, rawDeltaMs);
      this.smoothedFps += (instantFps - this.smoothedFps) * 0.12;
    }

    this.worldVisualTime += dt;
    this.updateTechStopVisuals(dt);

    if (this.matchPhase === 'lobby') {
      if (this.splashAttract && this.splashAttract.isActive() && this.world) {
        this.splashAttract.update(dt, this.camController.camera, this.world);
      } else {
        this.updateLobbyCamera(dt);
        this.world?.updatePerformanceFocus(0, 6, -6);
      }
      this.vfx.update(dt);
      this.renderer.render(this.scene, this.camController.camera);
      this.lastRenderCalls = this.renderer.info.render.calls;
      this.lastRenderTriangles = this.renderer.info.render.triangles;
      return;
    }

    this.matchElapsed += dt;
    this.unarmedHintCooldown = Math.max(0, this.unarmedHintCooldown - dt);
    this.updateSoundEvents(dt);
    this.updateGBus(dt);
    this.updateStorm(dt);
    this.updateSupplyDrops(dt);
    this.updateActiveZones(dt);
    this.updatePendingSlidesBeams(dt);
    this.updateCombatants(dt);
    if (this.mpActive) {
      this.updateMultiplayerSync(dt);
    }
    this.updateWorldGBikes(dt);
    this.updateProjectiles(dt);
    this.updateThrownUtilities(dt);
    this.updateLootChests(dt);
    this.updateLootVisuals(dt);
    this.updateBarriers(dt);
    this.vfx.update(dt);
    this.updateCamera(dt);

    if (this.world) {
      const focus = this.getCameraFocusPos();
      this.world.updatePerformanceFocus(focus.x, focus.y, focus.z);
    }

    this.renderer.render(this.scene, this.camController.camera);
    this.lastRenderCalls = this.renderer.info.render.calls;
    this.lastRenderTriangles = this.renderer.info.render.triangles;

    this.hudEmitAccum += dt;
    if (this.hudEmitAccum >= 0.05) {
      this.hudEmitAccum = 0;
      this.emitHudSnapshot();
    }
  };

  private updateLobbyCamera(dt: number): void {
    this.lobbyOrbitAngle += dt * 0.068;
    const cam = this.camController.camera;
    const cx = 0;
    const cz = -6;
    const rx = 252;
    const rz = 166;
    cam.position.set(
      cx + Math.cos(this.lobbyOrbitAngle) * rx,
      84 + Math.sin(this.lobbyOrbitAngle * 1.4) * 10,
      cz + Math.sin(this.lobbyOrbitAngle) * rz
    );
    cam.lookAt(0, 6, -6);
  }

  // =========================================================================
  // FLYING GOOGLE GBUS WITH WINGS (DROP-IN BATTLE BUS)
  // =========================================================================

  private spawnGBus(rngFn: () => number): GoogleGBusState {
    if (this.gbus) {
      this.scene.remove(this.gbus.visual.root);
      this.gbus = null;
    }

    const theta = rngFn() * Math.PI * 2;
    const rx = 335;
    const rz = 225;
    const perpOffset = (rngFn() - 0.5) * 110; // ±55m off-center variety across Googleplex landmarks
    const cosT = Math.cos(theta);
    const sinT = Math.sin(theta);
    const perpX = -sinT * perpOffset;
    const perpZ = cosT * perpOffset;

    const startX = cosT * rx + perpX;
    const startZ = sinT * rz + perpZ;
    const endX = -cosT * rx + perpX;
    const endZ = -sinT * rz + perpZ;
    const y = GAME_CONSTANTS.GBUS_ALTITUDE;
    // Nose is at -Z in local GLB space -> forward vector is (-sin(yaw), 0, -cos(yaw))
    const yaw = Math.atan2(-(endX - startX), -(endZ - startZ));

    const visual = this.assetManager.instantiateGoogleGBus();
    visual.root.position.set(startX, y, startZ);
    visual.root.rotation.order = 'YXZ';
    visual.root.rotation.set(0, yaw, 0);
    this.scene.add(visual.root);

    this.gbus = {
      active: true,
      visual,
      startX,
      startZ,
      endX,
      endZ,
      x: startX,
      y,
      z: startZ,
      yaw,
      elapsed: 0,
      duration: GAME_CONSTANTS.GBUS_FLIGHT_DURATION,
      progress: 0,
      hornPlayed: false,
      trailTimer: 0.04,
    };

    return this.gbus;
  }

  private updateGBus(dt: number): void {
    const gbus = this.gbus;
    if (!gbus || !gbus.active) return;

    gbus.elapsed += dt;
    gbus.progress = gbus.elapsed / Math.max(1, gbus.duration);

    gbus.x = gbus.startX + (gbus.endX - gbus.startX) * gbus.progress;
    gbus.z = gbus.startZ + (gbus.endZ - gbus.startZ) * gbus.progress;
    gbus.y = GAME_CONSTANTS.GBUS_ALTITUDE + Math.sin(gbus.elapsed * 2.2) * 0.45;
    const roll = Math.sin(gbus.elapsed * 1.1) * 0.03;

    gbus.visual.root.position.set(gbus.x, gbus.y, gbus.z);
    gbus.visual.root.rotation.order = 'YXZ';
    gbus.visual.root.rotation.set(0, gbus.yaw, roll);

    if (gbus.visual.rotorL) {
      gbus.visual.rotorL.rotation.z += dt * 26;
    }
    if (gbus.visual.rotorR) {
      gbus.visual.rotorR.rotation.z -= dt * 26;
    }

    // Dual jet thruster contrails every 0.06s
    gbus.trailTimer -= dt;
    if (gbus.trailTimer <= 0) {
      gbus.trailTimer = 0.06;
      gbus.visual.root.updateMatrixWorld(true);
      if (gbus.visual.thrusterL) {
        gbus.visual.thrusterL.getWorldPosition(this.tmpVecA);
        this.vfx.spawnGliderTrail(this.tmpVecA);
      }
      if (gbus.visual.thrusterR) {
        gbus.visual.thrusterR.getWorldPosition(this.tmpVecB);
        this.vfx.spawnGliderTrail(this.tmpVecB);
      }
    }

    // Iconic Google GBus departure horn once campus drop zone unlocks
    if (!gbus.hornPlayed && gbus.progress >= 0.05) {
      gbus.hornPlayed = true;
      this.audio.playGBusHorn();
    }

    // Keep passengers synchronized inside the GBus & trigger staggered bot drops + player auto-eject
    for (const c of this.combatants) {
      if (!c.alive || !c.inBus) continue;
      c.pos.set(gbus.x, gbus.y - 1.2, gbus.z);
      c.hero.root.visible = false;
      c.gliderMesh.visible = false;

      if (c.isPlayer) {
        if (gbus.progress >= GAME_CONSTANTS.GBUS_AUTO_EJECT_PROGRESS) {
          this.ejectFromGBus(c);
        }
      } else if (!c.isRemoteHuman && (!this.mpActive || this.isMpHost)) {
        if (gbus.progress >= c.busDropProgress) {
          this.ejectFromGBus(c);
        }
      }
    }

    // Despawn GBus cleanly once it clears the far perimeter (0 extra draw calls during ground combat!)
    if (gbus.progress >= 1.18) {
      for (const c of this.combatants) {
        if (c.alive && c.inBus && (c.isPlayer || (!c.isRemoteHuman && (!this.mpActive || this.isMpHost)))) {
          this.ejectFromGBus(c);
        }
      }
      gbus.active = false;
      this.scene.remove(gbus.visual.root);
    }
  }

  private ejectFromGBus(c: Combatant): void {
    if (!c.inBus) return;
    c.inBus = false;
    c.skyDropping = true;
    c.hero.root.visible = true;
    c.gliderMesh.visible = true;

    const gbus = this.gbus;
    const baseX = gbus ? gbus.x : c.pos.x;
    const baseY = (gbus ? gbus.y : c.pos.y) - 2.6;
    const baseZ = gbus ? gbus.z : c.pos.z;

    let spawnX = baseX;
    let spawnZ = baseZ;
    if (!c.isPlayer) {
      const spreadAng = Math.random() * Math.PI * 2;
      const spreadDist = 1.6 + Math.random() * 2.8;
      spawnX += Math.cos(spreadAng) * spreadDist;
      spawnZ += Math.sin(spreadAng) * spreadDist;
      // Steer bots toward campus interior on drop
      const toCenterYaw = Math.atan2(spawnX, spawnZ);
      c.yaw = toCenterYaw + (Math.random() - 0.5) * 1.1;
    }

    spawnX = THREE.MathUtils.clamp(spawnX, GAME_CONSTANTS.ARENA_MIN_X + 6, GAME_CONSTANTS.ARENA_MAX_X - 6);
    spawnZ = THREE.MathUtils.clamp(spawnZ, GAME_CONSTANTS.ARENA_MIN_Z + 6, GAME_CONSTANTS.ARENA_MAX_Z - 6);

    c.pos.set(spawnX, baseY, spawnZ);
    const launchSpeed = c.isPlayer ? 20 : 22;
    c.vel.set(-Math.sin(c.yaw) * launchSpeed, -10.5, -Math.cos(c.yaw) * launchSpeed);

    c.hero.root.position.copy(c.pos);
    c.hero.root.rotation.order = 'YXZ';
    c.hero.root.rotation.set(0, c.yaw, 0);
    c.hero.crossFade('Glide', 0.05);

    if (c.isPlayer) {
      this.audio.playGBusJump();
      this.audio.setGliderWind(true, false);
      this.emitHudSnapshot();
    }
  }

  // =========================================================================
  // 8-PHASE STORM (PHASES 6–8 MOVING FINAL CIRCLES) & MID-MATCH SUPPLY DROPS
  // =========================================================================

  private updateStorm(dt: number): void {
    if (!this.world) return;
    const mode = GAME_MODES[this.activeGameMode] ?? GAME_MODES.battle_royale;

    if (!mode.stormEnabled) {
      // Free Roam mode: keep storm parked far outside campus & schedule Supply Drops on elapsed timers
      if (this.supplyDropsSpawned === 0 && this.matchElapsed >= 16) {
        this.spawnSupplyDrop();
      } else if (this.supplyDropsSpawned === 1 && this.matchElapsed >= 65) {
        this.spawnSupplyDrop();
      } else if (this.supplyDropsSpawned === 2 && this.matchElapsed >= 120) {
        this.spawnSupplyDrop();
      }
      this.stormCenterX = 0;
      this.stormCenterZ = 0;
      this.stormRadius = mode.initialStormRadius;
      this.nextStormCenterX = 0;
      this.nextStormCenterZ = 0;
      this.nextStormRadius = mode.initialStormRadius;
      this.stormPhaseTimer = 0;
      this.world.updateStormVisual(this.stormCenterX, this.stormCenterZ, this.stormRadius, this.matchElapsed);
      return;
    }

    const phaseDef = STORM_PHASES[this.stormPhaseIndex] ?? STORM_PHASES[STORM_PHASES.length - 1];
    const firstDropTime = 16 * mode.stormPaceMult;

    // Spawn 3 aerial Supply Drops across the 3× campus: Phases 1, 2, and 3!
    if (this.supplyDropsSpawned === 0 && this.matchElapsed >= firstDropTime) {
      this.spawnSupplyDrop();
    } else if (this.supplyDropsSpawned === 1 && this.stormPhaseIndex >= 1) {
      this.spawnSupplyDrop();
    } else if (this.supplyDropsSpawned === 2 && this.stormPhaseIndex >= 2) {
      this.spawnSupplyDrop();
    }

    this.stormPhaseTimer -= dt;
    const scaledShrinkDuration = Math.max(1.0, phaseDef.shrinkDuration * mode.stormPaceMult);

    if (this.stormMode === 'wait') {
      if (this.stormPhaseTimer <= 0) {
        this.stormMode = 'shrink';
        this.stormPhaseTimer = scaledShrinkDuration;
        this.stormStartCenterX = this.stormCenterX;
        this.stormStartCenterZ = this.stormCenterZ;
        this.stormStartRadius = this.stormRadius;
        if (phaseDef.isMoving) {
          this.callbacks.onAnnouncement(
            `MOVING ZONE ${phaseDef.phase}`,
            `Safe zone shifting across campus (${phaseDef.dps} HP/s outside)`
          );
        } else {
          this.callbacks.onAnnouncement(
            `STORM PHASE ${phaseDef.phase} CLOSING`,
            `Safe zone shrinking (${phaseDef.dps} HP/s outside)`
          );
        }
      }
    } else {
      const progress = 1 - Math.max(0, this.stormPhaseTimer) / scaledShrinkDuration;
      this.stormCenterX = this.stormStartCenterX + (this.nextStormCenterX - this.stormStartCenterX) * progress;
      this.stormCenterZ = this.stormStartCenterZ + (this.nextStormCenterZ - this.stormStartCenterZ) * progress;
      this.stormRadius = this.stormStartRadius + (this.nextStormRadius - this.stormStartRadius) * progress;

      if (this.stormPhaseTimer <= 0) {
        this.stormCenterX = this.nextStormCenterX;
        this.stormCenterZ = this.nextStormCenterZ;
        this.stormRadius = this.nextStormRadius;

        if (this.stormPhaseIndex < STORM_PHASES.length - 1) {
          this.stormPhaseIndex++;
          const nextDef = STORM_PHASES[this.stormPhaseIndex];
          this.stormMode = 'wait';
          this.stormPhaseTimer = nextDef.waitDuration * mode.stormPaceMult;

          const rngFn = this.mpActive && this.mpRng ? this.mpRng : Math.random;
          if (nextDef.isMoving) {
            // Moving Final Circle (Phases 6, 7, 8): shift target center outside current circle across playable campus
            const minShift = nextDef.moveShiftMin ?? 48;
            const maxShift = nextDef.moveShiftMax ?? 78;
            const shift = minShift + rngFn() * (maxShift - minShift);
            const minX = GAME_CONSTANTS.ARENA_MIN_X + 36;
            const maxX = GAME_CONSTANTS.ARENA_MAX_X - 36;
            const minZ = GAME_CONSTANTS.ARENA_MIN_Z + 36;
            const maxZ = GAME_CONSTANTS.ARENA_MAX_Z - 36;

            let chosenX: number | null = null;
            let chosenZ: number | null = null;
            const baseAng = rngFn() * Math.PI * 2;
            for (let attempt = 0; attempt < 6; attempt++) {
              const ang = baseAng + (attempt * Math.PI * 2) / 6;
              const candX = this.stormCenterX + Math.cos(ang) * shift;
              const candZ = this.stormCenterZ + Math.sin(ang) * shift;
              if (candX >= minX && candX <= maxX && candZ >= minZ && candZ <= maxZ) {
                chosenX = candX;
                chosenZ = candZ;
                break;
              }
            }
            if (chosenX === null || chosenZ === null) {
              const towardCenterAng = Math.atan2(-this.stormCenterZ, -this.stormCenterX);
              chosenX = THREE.MathUtils.clamp(
                this.stormCenterX + Math.cos(towardCenterAng) * shift,
                minX,
                maxX
              );
              chosenZ = THREE.MathUtils.clamp(
                this.stormCenterZ + Math.sin(towardCenterAng) * shift,
                minZ,
                maxZ
              );
            }
            this.nextStormCenterX = chosenX;
            this.nextStormCenterZ = chosenZ;
            this.nextStormRadius = nextDef.targetRadius;
            this.callbacks.onAnnouncement(
              'MOVING FINAL CIRCLE',
              `Moving Zone ${nextDef.phase} shifts in ${Math.ceil(this.stormPhaseTimer)}s (${nextDef.dps} HP/s)`
            );
          } else {
            // Standard Phases 1–5: drift next safe zone subtly within current circle (deterministic in MP via mpRng)
            const maxShift = Math.max(0, this.stormRadius - nextDef.targetRadius) * 0.45;
            const ang = rngFn() * Math.PI * 2;
            const shift = rngFn() * maxShift;
            this.nextStormCenterX = THREE.MathUtils.clamp(
              this.stormCenterX + Math.cos(ang) * shift,
              GAME_CONSTANTS.ARENA_MIN_X + 24,
              GAME_CONSTANTS.ARENA_MAX_X - 24
            );
            this.nextStormCenterZ = THREE.MathUtils.clamp(
              this.stormCenterZ + Math.sin(ang) * shift,
              GAME_CONSTANTS.ARENA_MIN_Z + 24,
              GAME_CONSTANTS.ARENA_MAX_Z - 24
            );
            this.nextStormRadius = nextDef.targetRadius;
          }
        } else {
          this.stormPhaseTimer = 0;
        }
      }
    }

    this.world.updateStormVisual(this.stormCenterX, this.stormCenterZ, this.stormRadius, this.matchElapsed);
  }

  private spawnSupplyDrop(): void {
    if (!this.world) return;
    this.supplyDropsSpawned++;

    // Choose a Supply Drop coordinate inside the next safe zone (or closest spot clamped inside)
    const candidates = this.world.supplyDropSpots.filter((s) => {
      const alreadyUsed = this.supplyDrops.some((d) => Math.hypot(d.x - s.x, d.z - s.z) < 8);
      const inNext =
        Math.hypot(s.x - this.nextStormCenterX, s.z - this.nextStormCenterZ) <=
        Math.max(18, this.nextStormRadius - 8);
      return !alreadyUsed && inNext;
    });

    let sx: number;
    let sz: number;
    let landmark: string;
    const rngFn = this.mpActive && this.mpRng ? this.mpRng : Math.random;
    if (candidates.length > 0) {
      const picked = candidates[Math.floor(rngFn() * candidates.length)];
      sx = picked.x;
      sz = picked.z;
      landmark = picked.landmark;
    } else {
      const a = rngFn() * Math.PI * 2;
      const r = Math.min(48, Math.max(8, this.nextStormRadius * 0.45));
      sx = THREE.MathUtils.clamp(
        this.nextStormCenterX + Math.cos(a) * r,
        GAME_CONSTANTS.ARENA_MIN_X + 36,
        GAME_CONSTANTS.ARENA_MAX_X - 36
      );
      sz = THREE.MathUtils.clamp(
        this.nextStormCenterZ + Math.sin(a) * r,
        GAME_CONSTANTS.ARENA_MIN_Z + 28,
        GAME_CONSTANTS.ARENA_MAX_Z - 28
      );
      landmark = this.world.getZoneName(sx, sz);
    }

    const targetY = this.physics.getSupportHeight(sx, sz, 10, 0.7, 0.5);
    const root = this.assetManager.instantiateProp('supply_drop');
    root.position.set(sx, 125, sz);
    this.scene.add(root);

    const parachuteNode = root.getObjectByName('ParachuteCanopy') ?? null;
    const beacon = this.vfx.createSupplyDropBeacon();
    beacon.position.set(sx, targetY, sz);
    this.scene.add(beacon);

    this.supplyDrops.push({
      id: `supply_${this.supplyDropsSpawned}`,
      x: sx,
      y: 125,
      targetY,
      z: sz,
      landmark,
      landed: false,
      opened: false,
      root,
      parachuteNode,
      beacon,
    });

    this.audio.playSupplyDropHorn();
    this.callbacks.onAnnouncement(
      'EPIC SUPPLY DROP INCOMING',
      `Descending near ${landmark} · Look for the Gold Sky-Beacon!`
    );
  }

  private updateSupplyDrops(dt: number): void {
    for (const drop of this.supplyDrops) {
      if (!drop.landed) {
        drop.y = Math.max(drop.targetY, drop.y - 14.0 * dt);
        drop.root.position.set(drop.x, drop.y, drop.z);
        drop.root.rotation.y += dt * 0.35;
        // Gentle parachute sway while descending
        drop.root.rotation.z = Math.sin(this.matchElapsed * 2.2) * 0.06;

        if (drop.y <= drop.targetY + 0.02) {
          drop.y = drop.targetY;
          drop.landed = true;
          drop.root.position.set(drop.x, drop.y, drop.z);
          drop.root.rotation.z = 0;
          if (drop.parachuteNode) {
            drop.parachuteNode.visible = false;
          }
          // Hide shroud cables cleanly if named
          drop.root.traverse((obj) => {
            const n = obj.name.toLowerCase();
            if (n.includes('parachute') || n.includes('canopy') || n.includes('shroud') || n.includes('cable')) {
              obj.visible = false;
            }
          });
          this.vfx.spawnExpandingRing(new THREE.Vector3(drop.x, drop.y, drop.z), 5.5, 0xfbbf24, 0.7);
          this.audio.playLanding(true);
        }
      } else if (!drop.opened) {
        drop.beacon.rotation.y += dt * 0.6;
        // Subtle pulsing beacon
        const pulse = 0.85 + Math.sin(this.matchElapsed * 4.5) * 0.15;
        drop.beacon.scale.set(pulse, 1, pulse);
      }
    }
  }

  private computeSupplyDropLoot(drop: SupplyDropEntity): SyncedGroundLoot[] {
    const weaponId = rollSupplyDropWeapon(this.activeGameMode);
    const healId: UtilityItemId = Math.random() < 0.55 ? 'shield_jug' : 'medkit';

    const dropItems: { kind: 'weapon' | 'item'; id: WeaponId | UtilityItemId; count: number }[] = [
      { kind: 'weapon', id: weaponId, count: 1 },
      { kind: 'item', id: healId, count: 1 },
      { kind: 'item', id: 'mana_elixir', count: 1 },
    ];

    return dropItems.map((item, idx) => {
      const ang = (idx / dropItems.length) * Math.PI * 2 + Math.random() * 0.5;
      const lx = drop.x + Math.cos(ang) * 2.1;
      const lz = drop.z + Math.sin(ang) * 2.1;
      const ly = this.physics.getSupportHeight(lx, lz, drop.y + 1.5, 0.3, 0.5);
      return {
        id: `${drop.id}_item_${idx}`,
        kind: item.kind,
        itemId: item.id,
        rarity: 'epic',
        count: item.count,
        x: Number(lx.toFixed(2)),
        y: Number(ly.toFixed(2)),
        z: Number(lz.toFixed(2)),
      };
    });
  }

  private applyOpenedSupplyDrop(
    drop: SupplyDropEntity,
    openerIsLocalPlayer: boolean,
    syncedLoot: SyncedGroundLoot[]
  ): void {
    if (drop.opened) return;
    drop.opened = true;
    for (const c of this.combatants) {
      if (c.channel?.kind === 'supply_drop' && c.channel.supplyDropId === drop.id) {
        this.cancelChannel(c);
      }
    }
    this.scene.remove(drop.beacon);
    const lid = drop.root.getObjectByName('CrateUpperLid');
    if (lid) {
      lid.position.y += 0.25;
      lid.rotation.x = -0.65;
    }

    const burstPos = new THREE.Vector3(drop.x, drop.y + 0.8, drop.z);
    this.vfx.spawnExplosion(burstPos, 4.5, 0xfbbf24);
    this.audio.playSupplyDropOpen();

    for (const item of syncedLoot) {
      this.spawnLootDrop(
        item.x,
        item.y,
        item.z,
        item.kind,
        item.itemId as WeaponId | UtilityItemId,
        item.rarity,
        item.count ?? 1,
        undefined,
        item.id
      );
    }

    if (openerIsLocalPlayer) {
      const mode = GAME_MODES[this.activeGameMode] ?? GAME_MODES.battle_royale;
      const weaponLabel = mode.forceWeaponId ? WEAPONS[mode.forceWeaponId].name : 'Weapon';
      this.callbacks.onAnnouncement(
        'SUPPLY DROP OPENED',
        `Epic ${weaponLabel} + Epic Shield/Medkit + Epic Mana Elixir!`
      );
    }
  }

  private openSupplyDrop(drop: SupplyDropEntity, opener: Combatant): void {
    if (drop.opened) return;
    if (this.mpActive) {
      if (!opener.isPlayer && !(this.isMpHost && !opener.isRemoteHuman)) return;
      if (this.mpPendingDropOpens.has(drop.id)) return;
      this.mpPendingDropOpens.add(drop.id);
      const loot = this.computeSupplyDropLoot(drop);
      this.mpClient?.send({
        type: 'supply_drop_open',
        dropId: drop.id,
        ...(opener.isPlayer ? {} : { openerId: opener.id }),
        loot,
      });
      return;
    }

    const loot = this.computeSupplyDropLoot(drop);
    this.applyOpenedSupplyDrop(drop, opener.isPlayer, loot);
  }

  // =========================================================================
  // COMBATANTS, INPUT, BOT AI, MOVEMENT, CHANNELING & ANIMATIONS
  // =========================================================================

  private updateCombatants(dt: number): void {
    const mode = GAME_MODES[this.activeGameMode] ?? GAME_MODES.battle_royale;
    const phaseDef = STORM_PHASES[this.stormPhaseIndex] ?? STORM_PHASES[STORM_PHASES.length - 1];
    this.visibleBotCount = 0;

    // Staggered 10 Hz Bot AI thinking: only rebuild BotWorldContext snapshots when >=1 bot thinks this frame!
    let anyBotNeedsThink = false;
    for (const c of this.combatants) {
      if (!c.alive || c.isPlayer || c.isRemoteHuman || !c.brain || c.rewind.active) continue;
      if (this.mpActive && !this.isMpHost) continue;
      c.aiThinkTimer -= dt;
      c.aiThinkAccumDt += dt;
      if (!c.cachedDecision || c.aiThinkTimer <= 0) {
        anyBotNeedsThink = true;
      }
    }

    let botWorld: BotWorldContext | null = null;
    let botSnapMap: Map<string, BotCombatantSnapshot> | null = null;
    if (anyBotNeedsThink) {
      botWorld = this.buildBotWorldContext(dt);
      botSnapMap = new Map();
      for (const s of botWorld.combatants) {
        botSnapMap.set(s.id, s);
      }
    }

    for (const c of this.combatants) {
      if (!c.alive) continue;

      // Cooldowns & status timers
      c.fireCooldown = Math.max(0, c.fireCooldown - dt);
      c.ultCooldown = Math.max(0, c.ultCooldown - dt);
      c.slideCooldown = Math.max(0, c.slideCooldown - dt);
      c.silencedSec = Math.max(0, c.silencedSec - dt);
      if (c.blindedSec > 0) {
        c.blindedSec = Math.max(0, c.blindedSec - dt);
        if (c.blindedSec <= 0) c.flashBlindPeak = 0;
      }
      c.hastedSec = Math.max(0, c.hastedSec - dt);
      c.slowedSec = Math.max(0, c.slowedSec - dt);
      c.revealedSec = Math.max(0, c.revealedSec - dt);
      c.revealedAllSec = Math.max(0, c.revealedAllSec - dt);

      if (this.matchElapsed - c.lastDamagedAt > 2.2) {
        c.recentDamageTaken = Math.max(0, c.recentDamageTaken - 25 * dt);
      }

      // Passive Mana regeneration (+4.5/s × mode.manaRegenMult up to 100)
      if (!c.skyDropping) {
        c.mana = Math.min(
          GAME_CONSTANTS.MAX_MANA,
          c.mana + GAME_CONSTANTS.MANA_REGEN_PER_SEC * mode.manaRegenMult * dt
        );
      }

      // Hit flash decay
      if (c.hitFlashTimer > 0) {
        c.hitFlashTimer -= dt;
        if (c.hitFlashTimer <= 0) {
          c.hero.clearFlash();
        }
      }

      // Check Chrono-Field buffs/debuffs (Google Calendar Hard Stop) + Mode movement speed multiplier
      let chronoSpeedMult = 1.0;
      let fireRateMult = 1.0;
      let inOwnChrono = false;
      let inEnemyChrono = false;
      for (const cz of this.chronoZones) {
        const d = Math.hypot(c.pos.x - cz.center.x, c.pos.z - cz.center.z);
        if (d <= cz.radius) {
          const rem = Math.max(0.1, cz.duration - cz.elapsed);
          if (c.id === cz.ownerId) {
            chronoSpeedMult = Math.max(chronoSpeedMult, 1.4);
            fireRateMult = Math.max(fireRateMult, 1.45);
            c.hastedSec = Math.max(c.hastedSec, rem);
            inOwnChrono = true;
          } else if (!this.isFriendlyId(c, cz.ownerId)) {
            chronoSpeedMult = Math.min(chronoSpeedMult, 0.35);
            fireRateMult = Math.min(fireRateMult, 0.45);
            c.slowedSec = Math.max(c.slowedSec, rem);
            inEnemyChrono = true;
          }
        }
      }
      const speedMult = mode.moveSpeedMult * chronoSpeedMult;
      if (!inOwnChrono && c.hastedSec > 0.15) c.hastedSec = 0.15;
      if (!inEnemyChrono && c.slowedSec > 0.15) c.slowedSec = 0.15;

      // Google Drive Guardrail Dome perimeter enforcement for unauthorized enemies
      const isRemoteSimulated = c.isRemoteHuman || (this.mpActive && !this.isMpHost && !c.isPlayer);
      if (!isRemoteSimulated) {
        for (const gz of this.guardrailZones) {
          if (c.id === gz.ownerId || this.isFriendlyId(c, gz.ownerId) || c.skyDropping) continue;
          const dx = c.pos.x - gz.center.x;
          const dz = c.pos.z - gz.center.z;
          const dist = Math.hypot(dx, dz);
          if (dist < gz.radius && dist > 0.01) {
            const push = (gz.radius - dist) + 0.25;
            const step = Math.min(push, 18 * dt);
            const ox = (dx / dist) * step;
            const oz = (dz / dist) * step;
            c.pos.x += ox;
            c.pos.z += oz;
            if (c.ridingGBikeId) {
              const bike = this.worldGBikes.find((b) => b.id === c.ridingGBikeId);
              if (bike) {
                bike.x += ox;
                bike.z += oz;
                bike.speed *= 0.82;
              }
            }
          }
        }
      }

      // Google Docs Version History Rewind Interpolation (0.45s smooth rollback!)
      if (c.rewind.active && !isRemoteSimulated) {
        this.updateDocsRewind(c, dt);
        this.syncCombatantVisuals(c, dt);
        continue;
      }

      // Record 4.0s Version History ring buffer (40 samples @ 0.1s intervals)
      if (!c.skyDropping && !isRemoteSimulated) {
        c.historySampleTimer += dt;
        if (c.historySampleTimer >= 0.1) {
          c.historySampleTimer -= 0.1;
          c.history.push({
            pos: c.pos.clone(),
            health: c.health,
            shield: c.shield,
            timestamp: this.matchElapsed,
          });
          if (c.history.length > 40) {
            c.history.shift();
          }
        }
      }

      // Reload timer progression
      if (c.isReloading && !isRemoteSimulated) {
        c.reloadTimer -= dt;
        if (c.reloadTimer <= 0) {
          c.isReloading = false;
          c.reloadTimer = 0;
          c.reloadDuration = 0;
          if (c.isPlayer) {
            this.sprintLatchedOnReload = false;
          }
          const slot = c.slots[c.activeSlot];
          if (slot && slot.kind === 'weapon') {
            slot.ammo = WEAPONS[slot.id as WeaponId].magSize;
          }
        }
      }

      // Active channel progression (consumables + Supply Drop opening)
      if (c.channel && !isRemoteSimulated) {
        if (c.silencedSec > 0) {
          this.cancelChannel(c, c.isPlayer ? 'Channel interrupted (Access Revoked!)' : undefined);
        } else {
          c.channel.elapsed += dt;
          if (c.channel.elapsed >= c.channel.duration) {
            this.completeChannel(c);
          }
        }
      }

      // Drive input (Local Player vs Remote Network Interpolation vs Multi-Tier Bot Brain)
      if (c.isPlayer) {
        this.updatePlayerController(c, dt, speedMult, fireRateMult);
      } else if (isRemoteSimulated) {
        this.updateRemoteInterpolatedCombatant(c, dt);
      } else {
        this.updateBotController(c, dt, speedMult, fireRateMult, botWorld, botSnapMap);
      }

      // Storm out-of-zone damage (bypasses Shield directly into Health; disabled in Free Roam)
      const ownsStormTick = !this.mpActive || c.isPlayer || (this.isMpHost && !c.isRemoteHuman);
      if (mode.stormEnabled && !c.skyDropping && ownsStormTick) {
        const distFromStorm = Math.hypot(c.pos.x - this.stormCenterX, c.pos.z - this.stormCenterZ);
        if (distFromStorm > this.stormRadius) {
          c.stormTickAccum += dt;
          if (c.stormTickAccum >= 1.0) {
            c.stormTickAccum -= 1.0;
            this.applyStormDamage(c, phaseDef.dps);
          }
        } else {
          c.stormTickAccum = 0;
        }
      } else {
        c.stormTickAccum = 0;
      }

      this.syncCombatantVisuals(c, dt);
    }
  }

  private getCombatantSpeedMult(c: Combatant): number {
    const mode = GAME_MODES[this.activeGameMode] ?? GAME_MODES.battle_royale;
    let chronoSpeedMult = 1.0;
    for (const cz of this.chronoZones) {
      const d = Math.hypot(c.pos.x - cz.center.x, c.pos.z - cz.center.z);
      if (d <= cz.radius) {
        if (c.id === cz.ownerId) {
          chronoSpeedMult = Math.max(chronoSpeedMult, 1.4);
        } else if (!this.isFriendlyId(c, cz.ownerId)) {
          chronoSpeedMult = Math.min(chronoSpeedMult, 0.35);
        }
      }
    }
    return mode.moveSpeedMult * chronoSpeedMult;
  }

  private startSlideFromVelocity(
    p: Combatant,
    dirX: number,
    dirZ: number,
    launchSpeed: number,
    initiatedByCtrl = false
  ): boolean {
    if (!p.alive || p.skyDropping || p.rewind.active || p.channel || p.sliding) {
      return false;
    }
    const len = Math.hypot(dirX, dirZ);
    if (len < 0.01) return false;
    p.slideDirX = dirX / len;
    p.slideDirZ = dirZ / len;
    p.slideSpeed = Math.max(GAME_CONSTANTS.SLIDE_RUN_SPEED, launchSpeed);

    p.sliding = true;
    p.crouching = true;
    p.sprinting = false;
    p.slideTimer = GAME_CONSTANTS.SLIDE_DURATION;
    p.slideElapsed = 0;
    p.slideCooldown = 0;
    p.slideInitiatedByCtrl = initiatedByCtrl;
    p.slideVfxTimer = 0.045;
    p.vel.x = p.slideDirX * p.slideSpeed;
    p.vel.z = p.slideDirZ * p.slideSpeed;

    if (p.isPlayer) {
      if (this.keys.has('ShiftLeft') || this.keys.has('ShiftRight')) {
        this.sprintLatchedOnSlide = true;
      }
      this.audio.playSlideStart(p.surface);
    }

    this.tmpVecA.set(p.pos.x + p.slideDirX * 0.42, p.pos.y + 0.01, p.pos.z + p.slideDirZ * 0.42);
    this.vfx.spawnSlideDust(this.tmpVecA, p.slideDirX, p.slideDirZ, p.surface, true);
    return true;
  }

  private tryStartSlide(p: Combatant, initiatedByCtrl: boolean): boolean {
    if (
      !p.alive ||
      !p.grounded ||
      p.skyDropping ||
      p.rewind.active ||
      p.ridingGBikeId !== null ||
      p.channel ||
      p.sliding ||
      p.slideCooldown > 0
    ) {
      return false;
    }

    const horizSpeed = Math.hypot(p.vel.x, p.vel.z);
    if (horizSpeed < GAME_CONSTANTS.SLIDE_MIN_ENTRY_SPEED) {
      return false;
    }

    const speedMult = this.getCombatantSpeedMult(p);
    const launchBase =
      horizSpeed >= 10.2 ? GAME_CONSTANTS.SLIDE_SPRINT_SPEED : GAME_CONSTANTS.SLIDE_RUN_SPEED;
    return this.startSlideFromVelocity(
      p,
      p.vel.x / horizSpeed,
      p.vel.z / horizSpeed,
      launchBase * speedMult,
      initiatedByCtrl
    );
  }

  // =========================================================================
  // RIDEABLE GOOGLE GBIKES & TECHSTOP WORLD VISUALS
  // =========================================================================

  private findNearestUnoccupiedGBike(
    c: Combatant,
    maxDist: number = GAME_CONSTANTS.GBIKE_MOUNT_RADIUS
  ): WorldGBike | null {
    let best: WorldGBike | null = null;
    let bestDist = maxDist;
    for (const bike of this.worldGBikes) {
      if (bike.riderId !== null) continue;
      const d = Math.hypot(bike.x - c.pos.x, bike.z - c.pos.z);
      if (d <= bestDist && Math.abs(bike.y - c.pos.y) <= 2.4) {
        bestDist = d;
        best = bike;
      }
    }
    return best;
  }

  private mountGBike(p: Combatant, bike: WorldGBike): boolean {
    if (!p.alive || p.skyDropping || p.rewind.active || p.ridingGBikeId !== null || bike.riderId !== null) {
      return false;
    }
    if (p.channel) this.cancelChannel(p);
    if (p.isReloading) this.cancelReload(p);
    if (p.sliding) this.endSlide(p, false);
    if (p.isPlayer) {
      this.crouchToggled = false;
      this.ctrlSlideConsumed = false;
    }
    p.crouching = false;
    p.sprinting = false;
    p.isAds = false;
    p.ridingGBikeId = bike.id;
    bike.riderId = p.id;
    bike.parkTilt = 0;

    if (p.weaponInstance) {
      p.weaponInstance.root.visible = false;
    }

    p.pos.set(bike.x, bike.y, bike.z);
    p.vel.set(-Math.sin(bike.yaw) * bike.speed, bike.velY, -Math.cos(bike.yaw) * bike.speed);
    p.yaw = bike.yaw;
    p.grounded = bike.grounded;

    if (p.isPlayer) {
      this.audio.playGBikeMount(true);
    }
    return true;
  }

  private dismountGBike(c: Combatant, allowBailSlide = true, broadcastRelease = true): void {
    if (!c.ridingGBikeId) return;
    const bike = this.worldGBikes.find((b) => b.id === c.ridingGBikeId) ?? null;
    c.ridingGBikeId = null;

    if (c.weaponInstance && !c.skyDropping) {
      c.weaponInstance.root.visible = true;
    }
    c.hero.root.rotation.set(0, c.yaw, 0);
    c.hero.model.position.set(0, 0, 0);
    c.hero.model.rotation.set(0, 0, 0);

    if (!bike) return;
    bike.riderId = null;

    const bikeSpeed = bike.speed;
    const absSpeed = Math.abs(bikeSpeed);
    const fx = -Math.sin(bike.yaw);
    const fz = -Math.cos(bike.yaw);
    const rx = Math.cos(bike.yaw);
    const rz = -Math.sin(bike.yaw);

    // Choose a clear dismount position to the left/right of the bike so rider never clips walls
    const originProbe = new THREE.Vector3(bike.x, bike.y + 0.9, bike.z);
    const candidateOffsets: [number, number][] = [
      [-rx * 1.05, -rz * 1.05], // Left side
      [rx * 1.05, rz * 1.05],   // Right side
      [fx * 0.9, fz * 0.9],     // Slightly forward
      [0, 0],                   // Fallback at bike
    ];
    let dropX = bike.x;
    let dropY = bike.y;
    let dropZ = bike.z;
    for (const [ox, oz] of candidateOffsets) {
      const tx = THREE.MathUtils.clamp(
        bike.x + ox,
        GAME_CONSTANTS.ARENA_MIN_X + 3,
        GAME_CONSTANTS.ARENA_MAX_X - 3
      );
      const tz = THREE.MathUtils.clamp(
        bike.z + oz,
        GAME_CONSTANTS.ARENA_MIN_Z + 3,
        GAME_CONSTANTS.ARENA_MAX_Z - 3
      );
      const probe = new THREE.Vector3(tx, bike.y + 0.9, tz);
      const supportY = this.physics.getSupportHeight(tx, tz, bike.y + 1.2, 0.42, 0.65);
      if ((ox === 0 && oz === 0) || (this.physics.hasLineOfSight(originProbe, probe) && Math.abs(supportY - bike.y) <= 1.2)) {
        dropX = tx;
        dropY = Math.max(supportY, bike.grounded ? supportY : bike.y);
        dropZ = tz;
        break;
      }
    }

    c.pos.set(dropX, dropY, dropZ);
    const supportAtDrop = this.physics.getSupportHeight(dropX, dropZ, dropY + 0.8, 0.42, 0.65);
    c.grounded = Math.abs(dropY - supportAtDrop) <= 0.45;
    if (c.grounded) {
      c.pos.y = supportAtDrop;
    }

    if (c.isPlayer && c.alive) {
      this.audio.playGBikeMount(false);
    }

    // Bail-Out Into Slide when dismounting at speed (>= 8.5 m/s)!
    if (
      allowBailSlide &&
      c.alive &&
      !c.rewind.active &&
      absSpeed >= GAME_CONSTANTS.GBIKE_BAIL_SLIDE_MIN_SPEED
    ) {
      const dirSign = bikeSpeed >= 0 ? 1 : -1;
      const slideDirX = fx * dirSign;
      const slideDirZ = fz * dirSign;
      const launchSpeed = Math.min(
        GAME_CONSTANTS.GBIKE_BOOST_SPEED,
        Math.max(GAME_CONSTANTS.SLIDE_SPRINT_SPEED, absSpeed * 1.04)
      );
      c.vel.y = 0;
      this.startSlideFromVelocity(c, slideDirX, slideDirZ, launchSpeed, false);
      // Let unoccupied GBike coast forward ~1.2s smoothly before settling on kickstand
      bike.speed = bikeSpeed * 0.88;
      if (this.mpActive && broadcastRelease && c.isPlayer) {
        this.mpClient?.send({
          type: 'bike_release',
          bikeId: bike.id,
          x: Number(bike.x.toFixed(2)),
          y: Number(bike.y.toFixed(2)),
          z: Number(bike.z.toFixed(2)),
          yaw: Number(bike.yaw.toFixed(3)),
          speed: Number(bike.speed.toFixed(2)),
        });
      }
      return;
    }

    // Standard low-speed / elimination / rewind dismount
    c.vel.set(fx * bikeSpeed * 0.35, Math.max(0, bike.velY * 0.5), fz * bikeSpeed * 0.35);
    bike.speed = bikeSpeed * 0.72;
    if (this.mpActive && broadcastRelease && c.isPlayer) {
      this.mpClient?.send({
        type: 'bike_release',
        bikeId: bike.id,
        x: Number(bike.x.toFixed(2)),
        y: Number(bike.y.toFixed(2)),
        z: Number(bike.z.toFixed(2)),
        yaw: Number(bike.yaw.toFixed(3)),
        speed: Number(bike.speed.toFixed(2)),
      });
    }
  }

  private updatePlayerOnGBike(p: Combatant, bike: WorldGBike, dt: number, speedMult: number): void {
    const fInput = (this.keys.has('KeyW') ? 1 : 0) - (this.keys.has('KeyS') ? 1 : 0);
    const steerInput = (this.keys.has('KeyA') ? 1 : 0) - (this.keys.has('KeyD') ? 1 : 0);
    const boostHeld = this.keys.has('ShiftLeft') || this.keys.has('ShiftRight');

    p.isAds = false;
    p.crouching = false;
    p.sliding = false;
    p.sprinting = boostHeld && fInput > 0 && bike.speed > 2.5;

    const maxFwd = (boostHeld ? GAME_CONSTANTS.GBIKE_BOOST_SPEED : GAME_CONSTANTS.GBIKE_MAX_SPEED) * speedMult;
    const maxRev = GAME_CONSTANTS.GBIKE_REVERSE_SPEED * speedMult;

    if (fInput > 0) {
      if (bike.speed < 0) {
        bike.speed = Math.min(0, bike.speed + 26.0 * dt);
      } else if (bike.speed < maxFwd) {
        const accel = boostHeld ? 16.5 : 13.5;
        bike.speed = Math.min(maxFwd, bike.speed + accel * dt);
      } else {
        // Released Shift boost: coast gently back to cruise speed
        bike.speed = Math.max(maxFwd, bike.speed - 6.8 * dt);
      }
    } else if (fInput < 0) {
      if (bike.speed > 0.1) {
        bike.speed = Math.max(0, bike.speed - 24.0 * dt);
      } else {
        bike.speed = Math.max(-maxRev, bike.speed - 9.5 * dt);
      }
    } else {
      // Natural rolling coasting drag
      const drag = bike.grounded ? 5.2 : 1.4;
      if (Math.abs(bike.speed) <= drag * dt) {
        bike.speed = 0;
      } else {
        bike.speed -= Math.sign(bike.speed) * drag * dt;
      }
    }

    // Steering & lean
    const targetSteer = steerInput * 0.44;
    bike.steerAngle += (targetSteer - bike.steerAngle) * Math.min(1, dt * 13);

    const absSpd = Math.abs(bike.speed);
    const turnScale =
      absSpd < 0.8
        ? 0.68
        : THREE.MathUtils.clamp(0.76 + (absSpd / GAME_CONSTANTS.GBIKE_MAX_SPEED) * 0.4, 0.76, 1.16);
    const reverseSign = bike.speed < -0.4 ? -1 : 1;
    const yawDelta = steerInput * 2.1 * turnScale * reverseSign * dt;
    bike.yaw += yawDelta;
    // Gently nudge camera yaw with steering while preserving free 360° mouse orbit
    p.yaw += yawDelta;

    const leanFactor = THREE.MathUtils.clamp(absSpd / 11.0, 0, 1);
    const targetLean = steerInput * reverseSign * 0.34 * leanFactor;
    bike.leanAngle += (targetLean - bike.leanAngle) * Math.min(1, dt * 10);
    bike.parkTilt += (0 - bike.parkTilt) * Math.min(1, dt * 12);

    // Quick Bunny Hop on Space
    bike.hopCooldown = Math.max(0, bike.hopCooldown - dt);
    if (this.keys.has('Space') && bike.grounded && bike.hopCooldown <= 0) {
      bike.velY = GAME_CONSTANTS.GBIKE_HOP_IMPULSE;
      bike.grounded = false;
      bike.hopCooldown = 0.55;
    }

    // Resolve movement & terrain following via PhysicsWorld
    const fx = -Math.sin(bike.yaw);
    const fz = -Math.cos(bike.yaw);
    const prevX = bike.x;
    const prevZ = bike.z;
    const wasGrounded = bike.grounded;
    const prevVelY = bike.velY;

    const bikePos = this.tmpVecA.set(bike.x, bike.y, bike.z);
    const bikeVel = this.tmpVecB.set(fx * bike.speed, bike.velY, fz * bike.speed);
    const moveRes = this.physics.resolveCombatantMovement(
      bikePos,
      bikeVel,
      0.52,
      GAME_CONSTANTS.STANDING_HEIGHT,
      dt
    );
    bike.x = bikePos.x;
    bike.y = bikePos.y;
    bike.z = bikePos.z;
    bike.velY = bikeVel.y;
    bike.grounded = moveRes.grounded;

    // Damp speed cleanly on head-on wall or tree impact
    const dispFwd = (bike.x - prevX) * fx + (bike.z - prevZ) * fz;
    const actualFwdSpeed = dispFwd / Math.max(dt, 0.001);
    if (Math.abs(bike.speed) > 1.5 && Math.abs(actualFwdSpeed) < Math.abs(bike.speed) * 0.35) {
      bike.speed *= 0.25;
    }

    if (!wasGrounded && bike.grounded && -prevVelY > 5.5) {
      this.audio.playLanding(-prevVelY > 12.0);
    }

    // Wheel & crank pedal spin (negative X rotation rolls forward along -Z)
    bike.wheelSpin -= (bike.speed * dt) / 0.34;
    if (fInput > 0 && bike.speed > 0.3) {
      bike.pedalSpin -= (bike.speed * dt) / 0.22;
    } else if (fInput < 0 && bike.speed < -0.2) {
      bike.pedalSpin -= (bike.speed * dt) / 0.28;
    }

    // Subtle tire & freewheel cadence when rolling > 4 m/s
    if (bike.grounded && Math.abs(bike.speed) > 4.0) {
      bike.rollTickTimer -= dt;
      if (bike.rollTickTimer <= 0) {
        const speedRatio = THREE.MathUtils.clamp(Math.abs(bike.speed) / GAME_CONSTANTS.GBIKE_MAX_SPEED, 0.25, 1.35);
        bike.rollTickTimer = THREE.MathUtils.clamp(0.32 / Math.max(speedRatio, 0.5), 0.16, 0.34);
        this.audio.playGBikeRollTick(speedRatio);
      }
    }

    // Handlebar Bell on Left Click
    bike.bellCooldown = Math.max(0, bike.bellCooldown - dt);
    if (this.mouseLeftDown && this.pointerLocked && !this.mapOpen && !p.semiAutoLatch) {
      this.tryRingGBikeBell(p);
    }

    // Sync player combatant kinematics to bike
    p.pos.set(bike.x, bike.y, bike.z);
    p.vel.set(fx * bike.speed, bike.velY, fz * bike.speed);
    p.grounded = bike.grounded;
    p.surface = moveRes.surface;
    p.airborneTime = bike.grounded ? 0 : p.airborneTime + dt;

    // Auto-clear pinned tactical waypoint when arriving on GBike within 14m
    if (this.waypoint) {
      const wdx = this.waypoint.x - p.pos.x;
      const wdz = this.waypoint.z - p.pos.z;
      if (wdx * wdx + wdz * wdz <= 14 * 14) {
        this.waypoint = null;
      }
    }
  }

  private tryRingGBikeBell(p: Combatant): boolean {
    if (!p.alive || p.ridingGBikeId === null) return false;
    const bike = this.worldGBikes.find((b) => b.id === p.ridingGBikeId);
    if (!bike || bike.bellCooldown > 0) return false;
    p.semiAutoLatch = true;
    bike.bellCooldown = 0.45;
    const fx = -Math.sin(bike.yaw);
    const fz = -Math.cos(bike.yaw);
    this.audio.playGBikeBell(0, 0);
    this.pushSoundEvent('gbike', bike.x + fx * 0.65, bike.z + fz * 0.65, 55, 0.55, 0.9);
    if (this.mpActive && p.isPlayer) {
      this.mpClient?.send({
        type: 'bike_bell',
        bikeId: bike.id,
        x: Number(bike.x.toFixed(2)),
        y: Number(bike.y.toFixed(2)),
        z: Number(bike.z.toFixed(2)),
      });
    }
    return true;
  }

  private updateWorldGBikes(dt: number): void {
    for (const bike of this.worldGBikes) {
      if (bike.riderId === null) {
        bike.bellCooldown = Math.max(0, bike.bellCooldown - dt);
        bike.hopCooldown = Math.max(0, bike.hopCooldown - dt);

        if (Math.abs(bike.speed) > 0.06 || !bike.grounded) {
          const decel = bike.grounded ? 9.5 : 1.5;
          if (Math.abs(bike.speed) <= decel * dt) {
            bike.speed = 0;
          } else {
            bike.speed -= Math.sign(bike.speed) * decel * dt;
          }

          const fx = -Math.sin(bike.yaw);
          const fz = -Math.cos(bike.yaw);
          const prevX = bike.x;
          const prevZ = bike.z;
          const bikePos = this.tmpVecA.set(bike.x, bike.y, bike.z);
          const bikeVel = this.tmpVecB.set(fx * bike.speed, bike.velY, fz * bike.speed);
          const moveRes = this.physics.resolveCombatantMovement(bikePos, bikeVel, 0.52, 1.25, dt);
          bike.x = bikePos.x;
          bike.y = bikePos.y;
          bike.z = bikePos.z;
          bike.velY = bikeVel.y;
          bike.grounded = moveRes.grounded;

          const dispFwd = (bike.x - prevX) * fx + (bike.z - prevZ) * fz;
          const actualFwdSpeed = dispFwd / Math.max(dt, 0.001);
          if (Math.abs(bike.speed) > 1.2 && Math.abs(actualFwdSpeed) < Math.abs(bike.speed) * 0.35) {
            bike.speed *= 0.2;
          }

          bike.wheelSpin -= (bike.speed * dt) / 0.34;
          bike.steerAngle += (0 - bike.steerAngle) * Math.min(1, dt * 8);
          bike.leanAngle += (0 - bike.leanAngle) * Math.min(1, dt * 8);
          bike.parkTilt += (0 - bike.parkTilt) * Math.min(1, dt * 8);

          // Emit 'gbike' Visual Sound Compass cue while coasting bike moves nearby
          if (Math.abs(bike.speed) > 2.2) {
            bike.soundCueTimer -= dt;
            if (bike.soundCueTimer <= 0) {
              bike.soundCueTimer = 0.28;
              this.pushSoundEvent('gbike', bike.x, bike.z, 55, 0.55, 0.9);
            }
          }
        } else {
          bike.speed = 0;
          bike.leanAngle += (0 - bike.leanAngle) * Math.min(1, dt * 8);
          bike.parkTilt += (0.14 - bike.parkTilt) * Math.min(1, dt * 5);
          bike.steerAngle += (0.16 - bike.steerAngle) * Math.min(1, dt * 5);
        }
      } else if (bike.riderId !== this.player?.id && Math.abs(bike.speed) > 2.0) {
        bike.soundCueTimer -= dt;
        if (bike.soundCueTimer <= 0) {
          bike.soundCueTimer = 0.28;
          this.pushSoundEvent('gbike', bike.x, bike.z, 55, 0.55, 0.9);
        }
      }

      // Apply live transforms to 3D GBike rig
      this.syncGBikeVisualTransform(bike);
    }
  }

  private syncGBikeVisualTransform(bike: WorldGBike): void {
    bike.visual.root.position.set(bike.x, bike.y, bike.z);
    bike.visual.root.rotation.order = 'YXZ';
    bike.visual.root.rotation.set(0, bike.yaw, bike.leanAngle + bike.parkTilt);
    if (bike.visual.frontAssembly) {
      bike.visual.frontAssembly.rotation.y = bike.steerAngle;
    }
    if (bike.visual.wheelFront) {
      bike.visual.wheelFront.rotation.x = bike.wheelSpin;
    }
    if (bike.visual.wheelRear) {
      bike.visual.wheelRear.rotation.x = bike.wheelSpin;
    }
    if (bike.visual.crankPedals) {
      bike.visual.crankPedals.rotation.x = bike.pedalSpin;
    }
  }

  private updateTechStopVisuals(dt: number): void {
    if (!this.world) return;
    const stops = this.world.techStops;
    for (let i = 0; i < stops.length; i++) {
      const icon = stops[i].visual?.holoIcon;
      if (!icon) continue;
      icon.rotation.y += dt * 1.4;
      icon.position.y = 1.29 + Math.sin(this.worldVisualTime * 2.4 + i * 1.15) * 0.05;
    }
  }

  private endSlide(c: Combatant, keepCrouchIfCtrl: boolean): void {
    if (!c.sliding) return;
    c.sliding = false;
    c.slideTimer = 0;
    c.slideElapsed = 0;
    c.slideInitiatedByCtrl = false;
    c.slideCooldown = GAME_CONSTANTS.SLIDE_COOLDOWN;

    if (c.isPlayer) {
      this.sprintLatchedOnSlide = false;
      const ctrlHeld = this.keys.has('ControlLeft');
      if (keepCrouchIfCtrl && ctrlHeld) {
        c.crouching = true;
      } else {
        this.crouchToggled = false;
        if (!this.isHealOrShieldChannel(c.channel)) {
          c.crouching = false;
        }
      }
    }
  }

  private updatePlayerController(
    p: Combatant,
    dt: number,
    speedMult: number,
    fireRateMult: number
  ): void {
    // Riding inside the Flying Google GBus (mouse-look orbits freely; Space/E jumps out!)
    if (p.inBus) {
      p.vel.set(0, 0, 0);
      p.sprinting = false;
      this.audio.setGliderWind(false, false);
      return;
    }

    // Sky / Glider Drop-In Controls (§3.2)
    if (p.skyDropping) {
      const fInput = (this.keys.has('KeyW') ? 1 : 0) - (this.keys.has('KeyS') ? 1 : 0);
      const rInput = (this.keys.has('KeyD') ? 1 : 0) - (this.keys.has('KeyA') ? 1 : 0);
      const diving = this.keys.has('ShiftLeft') || this.keys.has('ShiftRight');
      p.sprinting = diving;

      const sinY = Math.sin(p.yaw);
      const cosY = Math.cos(p.yaw);
      // Forward = (-sinY, -cosY), Right = (cosY, -sinY)
      let dirX = -sinY * fInput + cosY * rInput;
      let dirZ = -cosY * fInput - sinY * rInput;
      const len = Math.hypot(dirX, dirZ);

      const glideSpeed = diving ? 38 : 28;
      if (len > 0.01) {
        dirX /= len;
        dirZ /= len;
        p.vel.x += (dirX * glideSpeed - p.vel.x) * Math.min(1, dt * 4.5);
        p.vel.z += (dirZ * glideSpeed - p.vel.z) * Math.min(1, dt * 4.5);
      } else {
        // Gentle forward airspeed drift even with hands off WASD
        p.vel.x += (-sinY * 14 - p.vel.x) * Math.min(1, dt * 2.5);
        p.vel.z += (-cosY * 14 - p.vel.z) * Math.min(1, dt * 2.5);
      }
      p.vel.y = diving ? -24.5 : -9.8;

      p.pos.addScaledVector(p.vel, dt);
      p.pos.x = THREE.MathUtils.clamp(p.pos.x, GAME_CONSTANTS.ARENA_MIN_X + 3, GAME_CONSTANTS.ARENA_MAX_X - 3);
      p.pos.z = THREE.MathUtils.clamp(p.pos.z, GAME_CONSTANTS.ARENA_MIN_Z + 3, GAME_CONSTANTS.ARENA_MAX_Z - 3);

      // Smooth bank & pitch tilt on hero.model (gliderMount is parented to model -> 1:1 lockstep!)
      let yawDelta = p.yaw - p.prevYaw;
      yawDelta = ((yawDelta + Math.PI * 3) % (Math.PI * 2)) - Math.PI;
      const yawRate = THREE.MathUtils.clamp(yawDelta / Math.max(dt, 0.004), -5.0, 5.0);
      const targetBank = THREE.MathUtils.clamp(-rInput * 0.28 + yawRate * 0.045, -0.34, 0.34);
      const targetPitchTilt = diving ? -0.34 : fInput > 0 ? -0.14 : fInput < 0 ? 0.06 : -0.09;
      p.glideBank += (targetBank - p.glideBank) * Math.min(1, dt * 6.5);
      p.glidePitch += (targetPitchTilt - p.glidePitch) * Math.min(1, dt * 6.5);
      p.hero.model.rotation.z = p.glideBank;
      p.hero.model.rotation.x = p.glidePitch;

      this.audio.setGliderWind(true, diving);

      p.gliderTrailTimer -= dt;
      if (p.gliderTrailTimer <= 0) {
        p.gliderTrailTimer = diving ? 0.05 : 0.1;
        this.vfx.spawnGliderTrail(new THREE.Vector3(p.pos.x, p.pos.y + 2.4, p.pos.z));
      }

      const groundY = this.physics.getSupportHeight(p.pos.x, p.pos.z, p.pos.y, 0.42, 0.65);
      if (p.pos.y - groundY <= GAME_CONSTANTS.GLIDER_STOW_CLEARANCE) {
        this.completeSkyDropTouchdown(p, groundY);
      }
      return;
    }

    // Rideable Google GBike Physics & Controls
    if (p.ridingGBikeId !== null) {
      const bike = this.worldGBikes.find((b) => b.id === p.ridingGBikeId);
      if (bike) {
        this.updatePlayerOnGBike(p, bike, dt, speedMult);
        return;
      }
      p.ridingGBikeId = null;
      if (p.weaponInstance) p.weaponInstance.root.visible = true;
    }

    // Ground / Combat Movement
    const fInput = (this.keys.has('KeyW') ? 1 : 0) - (this.keys.has('KeyS') ? 1 : 0);
    const rInput = (this.keys.has('KeyD') ? 1 : 0) - (this.keys.has('KeyA') ? 1 : 0);
    const shiftHeld = this.keys.has('ShiftLeft') || this.keys.has('ShiftRight');
    const ctrlHeld = this.keys.has('ControlLeft');

    const activeSlotObj = p.slots[p.activeSlot];
    const activeWeapon =
      activeSlotObj && activeSlotObj.kind === 'weapon'
        ? WEAPONS[activeSlotObj.id as WeaponId]
        : null;

    // ADS: Right-Click while wielding weapon and not reloading/channeling (allowed during slide!)
    p.isAds = this.mouseRightDown && activeWeapon !== null && !p.isReloading && !p.channel;

    // Edge-trigger ControlLeft slide cleanly (e.g. pressed just before landing or while moving fast)
    if (!ctrlHeld) {
      this.ctrlSlideConsumed = false;
    } else if (
      !this.ctrlSlideConsumed &&
      p.grounded &&
      !p.sliding &&
      !p.rewind.active &&
      !this.isHealOrShieldChannel(p.channel)
    ) {
      this.ctrlSlideConsumed = true;
      this.tryStartSlide(p, true);
    }

    // Sprint cancels crouch, active channel & reload (unless Shift was already held when reload/channel/slide began, or holding Ctrl)
    const canTriggerSprint =
      shiftHeld &&
      fInput > 0 &&
      !p.isAds &&
      !p.sliding &&
      !ctrlHeld &&
      !this.sprintLatchedOnReload &&
      !this.sprintLatchedOnChannel &&
      !this.sprintLatchedOnSlide;
    if (canTriggerSprint) {
      this.crouchToggled = false;
      if (p.channel) this.cancelChannel(p);
      if (p.isReloading) this.cancelReload(p);
    }
    if (!p.isReloading && !shiftHeld) {
      this.sprintLatchedOnReload = false;
    }
    if (!p.channel && !shiftHeld) {
      this.sprintLatchedOnChannel = false;
    }
    if (!p.sliding && !shiftHeld) {
      this.sprintLatchedOnSlide = false;
    }

    // Tactical Slide movement & steering vs. standard locomotion
    let didSlideJump = false;
    if (p.sliding) {
      p.slideElapsed += dt;
      p.slideTimer -= dt;
      p.crouching = true;
      p.sprinting = false;

      // Hold-Ctrl release exits slide smoothly once past initial commit window
      if (p.slideInitiatedByCtrl && !ctrlHeld && p.slideElapsed >= 0.18) {
        this.endSlide(p, false);
      } else if (this.keys.has('Space') && p.grounded) {
        // Slide-Jump: cancel slide, boost jump slightly, and preserve ~85% horizontal slide velocity
        const preserveVx = p.vel.x * 0.85;
        const preserveVz = p.vel.z * 0.85;
        this.endSlide(p, false);
        if (p.channel) this.cancelChannel(p);
        this.crouchToggled = false;
        p.crouching = false;
        p.vel.x = preserveVx;
        p.vel.z = preserveVz;
        p.vel.y = GAME_CONSTANTS.JUMP_IMPULSE * 1.04;
        p.grounded = false;
        p.airborneTime = 0.09;
        p.peakFallSpeed = 0;
        p.takeoffTimer = 0.14;
        p.squashTimer = 0;
        didSlideJump = true;
      } else {
        // Subtle lateral carving around corners/cover via A/D (~1.35 rad/s)
        if (rInput !== 0) {
          const steerAngle = rInput * 1.35 * dt;
          const cs = Math.cos(steerAngle);
          const sn = Math.sin(steerAngle);
          const nx = p.slideDirX * cs - p.slideDirZ * sn;
          const nz = p.slideDirX * sn + p.slideDirZ * cs;
          const nLen = Math.hypot(nx, nz) || 1;
          p.slideDirX = nx / nLen;
          p.slideDirZ = nz / nLen;
        }
        p.vel.x = p.slideDirX * p.slideSpeed;
        p.vel.z = p.slideDirZ * p.slideSpeed;
      }
    }

    if (!p.sliding && !didSlideJump) {
      const healCrouching = this.isHealOrShieldChannel(p.channel);
      p.crouching = healCrouching || (!canTriggerSprint && (this.crouchToggled || ctrlHeld));
      p.sprinting = canTriggerSprint && !p.crouching && !p.isReloading && !p.channel;

      // Movement speed
      let baseSpeed: number = GAME_CONSTANTS.WALK_SPEED;
      if (p.channel) {
        baseSpeed = 3.2;
      } else if (p.crouching) {
        baseSpeed = GAME_CONSTANTS.CROUCH_SPEED;
      } else if (p.isReloading) {
        baseSpeed = 5.2;
      } else if (p.isAds) {
        baseSpeed = 5.4;
      } else if (p.sprinting) {
        baseSpeed = GAME_CONSTANTS.SPRINT_SPEED;
      }
      const moveSpeed = baseSpeed * speedMult;

      const sinY = Math.sin(p.yaw);
      const cosY = Math.cos(p.yaw);
      let moveX = -sinY * fInput + cosY * rInput;
      let moveZ = -cosY * fInput - sinY * rInput;
      const len = Math.hypot(moveX, moveZ);
      if (len > 0.01) {
        moveX /= len;
        moveZ /= len;
      }

      const accel = p.grounded ? 16 : 5.5;
      p.vel.x += (moveX * moveSpeed - p.vel.x) * Math.min(1, dt * accel);
      p.vel.z += (moveZ * moveSpeed - p.vel.z) * Math.min(1, dt * accel);

      // Jump
      if (this.keys.has('Space') && p.grounded) {
        if (p.channel) this.cancelChannel(p);
        this.crouchToggled = false;
        p.crouching = false;
        p.vel.y = GAME_CONSTANTS.JUMP_IMPULSE;
        p.grounded = false;
        p.airborneTime = 0.09;
        p.peakFallSpeed = 0;
        p.takeoffTimer = 0.14;
        p.squashTimer = 0;
      }
    }

    const wasGrounded = p.grounded;
    const prevX = p.pos.x;
    const prevY = p.pos.y;
    const prevZ = p.pos.z;
    const prevVelY = p.vel.y;
    const colHeight = p.crouching ? GAME_CONSTANTS.CROUCH_HEIGHT : GAME_CONSTANTS.STANDING_HEIGHT;
    const moveRes = this.physics.resolveCombatantMovement(p.pos, p.vel, 0.42, colHeight, dt);
    p.grounded = moveRes.grounded;
    p.surface = moveRes.surface;

    if (!p.grounded) {
      p.airborneTime += dt;
      if (p.vel.y < 0) {
        p.peakFallSpeed = Math.max(p.peakFallSpeed, -p.vel.y);
      }
    } else {
      if (!wasGrounded) {
        const impactSpeed = Math.max(p.peakFallSpeed, -prevVelY);
        if (impactSpeed > 3.5) {
          p.squashDuration = 0.18;
          p.squashTimer = 0.18;
          p.squashIntensity = THREE.MathUtils.clamp((impactSpeed - 3.0) / 14.0, 0.38, 1.0);
          p.takeoffTimer = 0;
        }
        if (impactSpeed > 6.0) {
          this.audio.playLanding(impactSpeed > 14.0);
        }
      }
      p.airborneTime = 0;
      p.peakFallSpeed = 0;
    }

    // Post-movement slide slope physics, dust trail, wall-impact & ledge termination
    if (p.sliding) {
      const dispHoriz = Math.hypot(p.pos.x - prevX, p.pos.z - prevZ);
      const actualHorizSpeed = dispHoriz / Math.max(dt, 0.001);
      const deltaY = p.pos.y - prevY;
      const slopeGrad = dispHoriz > 0.01 ? deltaY / dispHoriz : 0;

      if (p.grounded) {
        if (slopeGrad < -0.06) {
          // Downhill ramp/hill: boost momentum & extend duration up to SLIDE_MAX_DURATION
          const downhillBoost = Math.min(9.5, (-slopeGrad - 0.06) * 26.0);
          const maxDownhillSpeed = GAME_CONSTANTS.SLIDE_SPRINT_SPEED * 1.18 * speedMult;
          p.slideSpeed = Math.min(maxDownhillSpeed, p.slideSpeed + downhillBoost * dt);
          const maxRemaining = Math.max(0, GAME_CONSTANTS.SLIDE_MAX_DURATION - p.slideElapsed);
          p.slideTimer = Math.min(maxRemaining, p.slideTimer + dt * 1.35);
        } else if (slopeGrad > 0.08) {
          // Uphill slope: stronger friction
          p.slideSpeed = Math.max(0, p.slideSpeed - 18.0 * dt);
        } else {
          // Flat ground friction
          p.slideSpeed = Math.max(0, p.slideSpeed - 11.8 * dt);
        }
        p.vel.x = p.slideDirX * p.slideSpeed;
        p.vel.z = p.slideDirZ * p.slideSpeed;

        p.slideVfxTimer -= dt;
        if (p.slideVfxTimer <= 0) {
          p.slideVfxTimer = 0.045;
          this.tmpVecA.set(
            p.pos.x + p.slideDirX * 0.42,
            p.pos.y + 0.01,
            p.pos.z + p.slideDirZ * 0.42
          );
          this.vfx.spawnSlideDust(this.tmpVecA, p.slideDirX, p.slideDirZ, p.surface);
        }
      }

      const hitWall = p.slideElapsed > 0.12 && actualHorizSpeed < 3.8;
      const leftLedge = !p.grounded && p.airborneTime > 0.14;
      if (
        hitWall ||
        leftLedge ||
        p.slideSpeed < GAME_CONSTANTS.SLIDE_MIN_END_SPEED ||
        p.slideTimer <= 0
      ) {
        if (hitWall) {
          p.vel.x *= 0.25;
          p.vel.z *= 0.25;
        } else if (leftLedge) {
          p.vel.x = p.slideDirX * p.slideSpeed;
          p.vel.z = p.slideDirZ * p.slideSpeed;
        }
        this.endSlide(p, !leftLedge);
      }
    }

    // Footstep audio (suppressed while sliding)
    const horizSpeed = Math.hypot(p.vel.x, p.vel.z);
    if (p.grounded && !p.sliding && horizSpeed > 1.2) {
      p.footstepTimer -= dt;
      if (p.footstepTimer <= 0) {
        p.footstepTimer = p.sprinting ? 0.29 : p.crouching ? 0.54 : 0.4;
        this.audio.playFootstep(p.sprinting, p.crouching, p.surface);
      }
    }

    // Supply Drop, Loot Chest & TechStop channel proximity checks (cancel if player walks too far or already opened)
    if (p.channel?.kind === 'supply_drop' && p.channel.supplyDropId) {
      const sd = this.supplyDrops.find((d) => d.id === p.channel?.supplyDropId);
      if (!sd || sd.opened || Math.hypot(sd.x - p.pos.x, sd.z - p.pos.z) > 4.4) {
        this.cancelChannel(p);
      }
    } else if (p.channel?.kind === 'chest' && p.channel.chestId) {
      const ch = this.lootChests.find((c) => c.id === p.channel?.chestId);
      if (!ch || ch.opened || Math.hypot(ch.x - p.pos.x, ch.z - p.pos.z) > 4.0) {
        this.cancelChannel(p);
      }
    } else if (p.channel?.kind === 'techstop' && p.channel.techStopId) {
      const ts = this.world?.techStops.find((t) => t.id === p.channel?.techStopId);
      if (!ts || Math.hypot(ts.x - p.pos.x, ts.z - p.pos.z) > 4.0) {
        this.cancelChannel(p);
      }
    }

    // Auto-clear pinned tactical waypoint when player arrives within 14m horizontally
    if (this.waypoint) {
      const wdx = this.waypoint.x - p.pos.x;
      const wdz = this.waypoint.z - p.pos.z;
      if (wdx * wdx + wdz * wdz <= 14 * 14) {
        this.waypoint = null;
      }
    }

    // Firing / Utility activation on Left Click (graceful unarmed hint when holding empty slot)
    if (this.mouseLeftDown && this.pointerLocked && !this.mapOpen) {
      if (activeSlotObj?.kind === 'weapon') {
        const wDef = WEAPONS[activeSlotObj.id as WeaponId];
        if (wDef.automatic || !p.semiAutoLatch) {
          if (p.channel) this.cancelChannel(p);
          const fired = this.tryFireWeapon(p, fireRateMult, null);
          if (fired && !wDef.automatic) {
            p.semiAutoLatch = true;
          }
        }
      } else if (activeSlotObj?.kind === 'item' && !p.semiAutoLatch) {
        p.semiAutoLatch = true;
        this.tryUseActiveItem(p);
      } else if (!activeSlotObj && !p.semiAutoLatch && !p.channel) {
        p.semiAutoLatch = true;
        if (this.unarmedHintCooldown <= 0) {
          this.unarmedHintCooldown = 2.6;
          this.audio.playDryFire();
          const hasAnyWeapon = p.slots.some((s) => s?.kind === 'weapon');
          if (!hasAnyWeapon) {
            this.callbacks.onAnnouncement('UNARMED', 'Open a Chest [E] to loot weapons & gear');
          } else {
            this.callbacks.onAnnouncement('EMPTY SLOT', 'Switch slots [1–5] or open a Chest [E]');
          }
        }
      }
    }
  }

  private updateBotController(
    b: Combatant,
    dt: number,
    speedMult: number,
    fireRateMult: number,
    worldCtx: BotWorldContext | null,
    snapMap: Map<string, BotCombatantSnapshot> | null
  ): void {
    if (!b.brain) return;
    if ((!b.cachedDecision || b.aiThinkTimer <= 0) && worldCtx && snapMap) {
      const selfSnap = snapMap.get(b.id);
      if (selfSnap) {
        // Advance BotBrain internal timers using real accumulated dt since this bot's last 10 Hz think
        worldCtx.dt = Math.min(0.25, Math.max(dt, b.aiThinkAccumDt));
        // In Teams mode, filter teammates out of BotWorldContext so bots NEVER target or fire at allies!
        const effectiveWorld: BotWorldContext =
          this.mpActive && this.mpFormat === 'teams' && b.teamId !== null
            ? {
                ...worldCtx,
                combatants: worldCtx.combatants.filter(
                  (s) => s.id === b.id || !this.isFriendlyId(b, s.id)
                ),
              }
            : worldCtx;
        b.cachedDecision = b.brain.update(selfSnap, effectiveWorld);
        b.aiThinkTimer = 0.1;
        b.aiThinkAccumDt = 0;
      }
    }
    const decision = b.cachedDecision;
    if (!decision) return;

    // Bots waiting aboard the Flying Google GBus eject via updateGBus() at their staggered busDropProgress
    if (b.inBus) {
      b.vel.set(0, 0, 0);
      return;
    }

    // Sky Drop gliding for AI bots
    if (b.skyDropping) {
      b.sprinting = decision.dive;
      const glideSpeed = decision.dive ? 35 : 26;
      b.vel.x += (decision.moveX * glideSpeed - b.vel.x) * Math.min(1, dt * 4);
      b.vel.z += (decision.moveZ * glideSpeed - b.vel.z) * Math.min(1, dt * 4);
      b.vel.y = decision.dive ? -23.5 : -10.2;
      const prevBotYaw = b.yaw;
      b.yaw = this.lerpAngle(b.yaw, decision.aimYaw, Math.min(1, dt * 5));

      let yawDelta = b.yaw - prevBotYaw;
      yawDelta = ((yawDelta + Math.PI * 3) % (Math.PI * 2)) - Math.PI;
      const yawRate = THREE.MathUtils.clamp(yawDelta / Math.max(dt, 0.004), -4.5, 4.5);
      const targetBank = THREE.MathUtils.clamp(yawRate * 0.12, -0.28, 0.28);
      const targetPitch = decision.dive ? -0.30 : -0.10;
      b.glideBank += (targetBank - b.glideBank) * Math.min(1, dt * 6);
      b.glidePitch += (targetPitch - b.glidePitch) * Math.min(1, dt * 6);
      b.hero.model.rotation.z = b.glideBank;
      b.hero.model.rotation.x = b.glidePitch;

      b.pos.addScaledVector(b.vel, dt);
      b.pos.x = THREE.MathUtils.clamp(b.pos.x, GAME_CONSTANTS.ARENA_MIN_X + 4, GAME_CONSTANTS.ARENA_MAX_X - 4);
      b.pos.z = THREE.MathUtils.clamp(b.pos.z, GAME_CONSTANTS.ARENA_MIN_Z + 4, GAME_CONSTANTS.ARENA_MAX_Z - 4);

      const groundY = this.physics.getSupportHeight(b.pos.x, b.pos.z, b.pos.y, 0.42, 0.65);
      if (b.pos.y - groundY <= GAME_CONSTANTS.GLIDER_STOW_CLEARANCE) {
        this.completeSkyDropTouchdown(b, groundY);
      }
      return;
    }

    // Slot switch
    if (decision.desiredSlot !== b.activeSlot && decision.desiredSlot >= 0 && decision.desiredSlot < 5) {
      if (!b.channel || b.channel.slotIndex !== decision.desiredSlot) {
        this.switchSlot(b, decision.desiredSlot);
      }
    }

    // Smooth yaw turning toward aim target
    b.yaw = this.lerpAngle(b.yaw, decision.aimYaw, Math.min(1, dt * 11));
    const botHealCrouching = this.isHealOrShieldChannel(b.channel);
    b.crouching = botHealCrouching || (decision.crouch && (!decision.sprint || b.isReloading));
    b.sprinting = decision.sprint && !b.crouching && !b.channel && !b.isReloading;
    const botActiveSlot = b.slots[b.activeSlot];
    b.isAds =
      decision.fire &&
      decision.aimTargetPoint !== null &&
      botActiveSlot?.kind === 'weapon' &&
      !b.isReloading &&
      !b.channel;
    if (decision.aimTargetPoint && botActiveSlot?.kind === 'weapon') {
      const eyeY = b.pos.y + (b.crouching ? GAME_CONSTANTS.EYE_HEIGHT_CROUCHING : GAME_CONSTANTS.EYE_HEIGHT_STANDING);
      const horizDist = Math.max(
        0.5,
        Math.hypot(decision.aimTargetPoint.x - b.pos.x, decision.aimTargetPoint.z - b.pos.z)
      );
      const desiredPitch = THREE.MathUtils.clamp(
        Math.atan2(decision.aimTargetPoint.y - eyeY, horizDist),
        -0.65,
        0.65
      );
      b.pitch += (desiredPitch - b.pitch) * Math.min(1, dt * 10);
    } else {
      b.pitch += (0 - b.pitch) * Math.min(1, dt * 8);
    }

    let baseSpeed: number = GAME_CONSTANTS.WALK_SPEED;
    if (b.channel) baseSpeed = 1.6;
    else if (b.crouching) baseSpeed = GAME_CONSTANTS.CROUCH_SPEED;
    else if (b.isReloading) baseSpeed = 5.2;
    else if (b.sprinting) baseSpeed = GAME_CONSTANTS.SPRINT_SPEED;

    const moveSpeed = baseSpeed * speedMult;
    const accel = b.grounded ? 14 : 4.5;
    b.vel.x += (decision.moveX * moveSpeed - b.vel.x) * Math.min(1, dt * accel);
    b.vel.z += (decision.moveZ * moveSpeed - b.vel.z) * Math.min(1, dt * accel);

    if (decision.jump && b.grounded) {
      decision.jump = false;
      b.vel.y = GAME_CONSTANTS.JUMP_IMPULSE;
      b.grounded = false;
      b.airborneTime = 0.09;
      b.peakFallSpeed = 0;
      b.takeoffTimer = 0.14;
      b.squashTimer = 0;
    } else if (decision.jump) {
      decision.jump = false;
    }

    const wasGrounded = b.grounded;
    const prevVelY = b.vel.y;
    const colHeight = b.crouching ? GAME_CONSTANTS.CROUCH_HEIGHT : GAME_CONSTANTS.STANDING_HEIGHT;
    const moveRes = this.physics.resolveCombatantMovement(b.pos, b.vel, 0.42, colHeight, dt);
    b.grounded = moveRes.grounded;
    b.surface = moveRes.surface;

    if (!b.grounded) {
      b.airborneTime += dt;
      if (b.vel.y < 0) {
        b.peakFallSpeed = Math.max(b.peakFallSpeed, -b.vel.y);
      }
    } else {
      if (!wasGrounded) {
        const impactSpeed = Math.max(b.peakFallSpeed, -prevVelY);
        if (impactSpeed > 3.5) {
          b.squashDuration = 0.18;
          b.squashTimer = 0.18;
          b.squashIntensity = THREE.MathUtils.clamp((impactSpeed - 3.0) / 14.0, 0.38, 1.0);
          b.takeoffTimer = 0;
        }
      }
      b.airborneTime = 0;
      b.peakFallSpeed = 0;
    }

    // Enemy bot footstep visual-compass events + spatialized stereo footsteps (crouching stays stealthy!)
    const botHorizSpeed = Math.hypot(b.vel.x, b.vel.z);
    if (b.grounded && !b.crouching && botHorizSpeed > 1.5) {
      b.footstepTimer -= dt;
      if (b.footstepTimer <= 0) {
        b.footstepTimer = b.sprinting ? 0.30 : 0.42;
        this.pushSoundEvent(
          'footstep',
          b.pos.x,
          b.pos.z,
          b.sprinting ? 40 : 28,
          0.45,
          b.sprinting ? 0.95 : 0.72
        );
        if (this.player) {
          const dist = b.pos.distanceTo(this.player.pos);
          if (dist <= 32) {
            this.audio.playFootstep(b.sprinting, false, b.surface, dist, this.computeSpatialPan(b.pos));
          }
        }
      }
    }

    // Cancel bot's chest/supply-drop channel if target was already opened or bot drifted too far
    if (b.channel?.kind === 'chest' && b.channel.chestId) {
      const ch = this.lootChests.find((c) => c.id === b.channel?.chestId);
      if (!ch || ch.opened || Math.hypot(ch.x - b.pos.x, ch.z - b.pos.z) > 4.2) {
        this.cancelChannel(b);
      }
    } else if (b.channel?.kind === 'supply_drop' && b.channel.supplyDropId) {
      const sd = this.supplyDrops.find((d) => d.id === b.channel?.supplyDropId);
      if (!sd || sd.opened || Math.hypot(sd.x - b.pos.x, sd.z - b.pos.z) > 4.6) {
        this.cancelChannel(b);
      }
    }

    // Loot pickup (requires matching floor elevation so ground-floor bots don't grab rooftop loot!)
    if (decision.pickupLootId) {
      const loot = this.lootDrops.find((l) => l.id === decision.pickupLootId);
      if (loot && Math.hypot(loot.x - b.pos.x, loot.z - b.pos.z) <= 3.6 && Math.abs(loot.y - b.pos.y) <= 2.6) {
        this.pickupLoot(b, loot);
        decision.pickupLootId = null;
      }
    }

    // Loot Chest interact (0.75s channel)
    if (decision.interactChestId && !b.channel) {
      const ch = this.lootChests.find((c) => c.id === decision.interactChestId);
      if (
        ch &&
        !ch.opened &&
        Math.hypot(ch.x - b.pos.x, ch.z - b.pos.z) <= 3.6 &&
        Math.abs(ch.y - b.pos.y) <= 2.5
      ) {
        this.startChestChannel(b, ch);
        decision.interactChestId = null;
      }
    }

    // Supply Drop interact
    if (decision.interactSupplyDropId && !b.channel) {
      const sd = this.supplyDrops.find((d) => d.id === decision.interactSupplyDropId);
      if (sd && sd.landed && !sd.opened && Math.hypot(sd.x - b.pos.x, sd.z - b.pos.z) <= 4.0) {
        if (b.isReloading) this.cancelReload(b);
        b.isAds = false;
        b.sprinting = false;
        b.channel = {
          kind: 'supply_drop',
          label: 'Opening Supply Drop...',
          slotIndex: b.activeSlot,
          supplyDropId: sd.id,
          elapsed: 0,
          duration: GAME_CONSTANTS.SUPPLY_DROP_CHANNEL_TIME,
        };
        decision.interactSupplyDropId = null;
      }
    }

    // Cast Ultimate (one-shot trigger cleared after firing once between 10 Hz think ticks)
    if (decision.useUltimate) {
      decision.useUltimate = false;
      this.tryCastUltimate(b, decision.aimTargetPoint);
      return;
    }

    // Use active utility / consumable (one-shot trigger cleared after firing once)
    if (decision.useItem && !b.channel) {
      decision.useItem = false;
      this.tryUseActiveItem(b);
      return;
    }

    // Fire weapon
    if (decision.fire && decision.aimTargetPoint && !b.channel) {
      this.tryFireWeapon(b, fireRateMult, decision.aimTargetPoint);
    }
  }

  private completeSkyDropTouchdown(c: Combatant, groundY: number): void {
    c.skyDropping = false;
    c.sprinting = false;
    c.sliding = false;
    c.slideTimer = 0;
    c.slideElapsed = 0;
    c.slideCooldown = 0;
    c.slidePoseBlend = 0;
    c.slideInitiatedByCtrl = false;
    c.pos.y = groundY;
    c.vel.set(0, 0, 0);
    c.grounded = true;
    c.gliderMesh.visible = false;
    c.glideBank = 0;
    c.glidePitch = 0;
    c.leanPitch = 0;
    c.leanBank = 0;
    c.smoothAimPitch = 0;
    c.twoHandBlend = 1;
    c.airborneTime = 0;
    c.peakFallSpeed = 0;
    c.takeoffTimer = 0;
    // Crisp touchdown landing impulse squash
    c.squashDuration = 0.20;
    c.squashTimer = 0.20;
    c.squashIntensity = 0.88;
    c.hero.model.rotation.x = 0;
    c.hero.model.rotation.z = 0;
    c.hero.gliderMount.rotation.set(0, 0, 0);
    if (c.weaponInstance) {
      c.weaponInstance.root.visible = true;
    }
    c.hero.crossFade(c.weaponInstance ? 'IdleArmed' : 'Idle', 0.16);
    // Immediately re-think on next tick when a bot finishes sky-dropping
    c.aiThinkTimer = 0;
    c.cachedDecision = null;

    // Seed clean grounded Docs history sample
    c.history = [
      {
        pos: c.pos.clone(),
        health: c.health,
        shield: c.shield,
        timestamp: this.matchElapsed,
      },
    ];

    if (c.isPlayer) {
      this.matchPhase = 'playing';
      this.audio.setGliderWind(false);
      this.audio.playLanding(true);
      const mode = GAME_MODES[this.activeGameMode] ?? GAME_MODES.battle_royale;
      const zone = this.world?.getZoneName(c.pos.x, c.pos.z) ?? 'Googleplex';
      const lootHint = mode.forceWeaponId
        ? `Open Chests [E] for ${WEAPONS[mode.forceWeaponId].name} & Mobility Gear`
        : mode.minChestTier && mode.minChestTier >= 2
          ? 'Open Tier 2–3 Upgraded Chests [E] for Gear'
          : 'Open Tier 1–3 Chests [E] for Weapons & Gear';
      this.callbacks.onAnnouncement('TOUCHDOWN — LOOT UP!', `Zone: ${zone} · ${lootHint}`);
    }
  }

  private buildBotWorldContext(dt: number): BotWorldContext {
    const snapshots: BotCombatantSnapshot[] = this.combatants.map((c) => {
      const oldest = c.history[0];
      return {
        id: c.id,
        alive: c.alive,
        skyDropping: c.skyDropping,
        heroId: c.heroId,
        pos: c.pos,
        vel: c.vel,
        yaw: c.yaw,
        health: c.health,
        shield: c.shield,
        mana: c.mana,
        crouching: c.crouching,
        channeling: c.channel !== null,
        silencedSec: c.silencedSec,
        blindedSec: c.blindedSec,
        ultCooldown: c.ultCooldown,
        slots: c.slots,
        activeSlot: c.activeSlot,
        isReloading: c.isReloading,
        lastDamagedAt: c.lastDamagedAt,
        lastAttackerId: c.lastAttackerId,
        recentDamageTaken: c.recentDamageTaken,
        docsHistoryHealth: oldest ? oldest.health : c.health,
        docsHistoryShield: oldest ? oldest.shield : c.shield,
        revealedAllSec: c.revealedAllSec,
      };
    });

    const lootSnaps: BotLootSnapshot[] = this.lootDrops.map((l) => ({
      id: l.id,
      x: l.x,
      y: l.y,
      z: l.z,
      kind: l.kind,
      itemId: l.itemId,
      rarity: l.rarity,
      droppedById: l.droppedById,
      droppedAt: l.droppedAt,
    }));

    const chestSnaps: BotChestSnapshot[] = this.lootChests
      .filter((ch) => !ch.opened)
      .map((ch) => ({
        id: ch.id,
        x: ch.x,
        y: ch.y,
        z: ch.z,
        tier: ch.tier,
        opened: ch.opened,
      }));

    const supplySnaps: BotSupplyDropSnapshot[] = this.supplyDrops.map((s) => ({
      id: s.id,
      x: s.x,
      y: s.y,
      z: s.z,
      landed: s.landed,
      opened: s.opened,
    }));

    const mode = GAME_MODES[this.activeGameMode] ?? GAME_MODES.battle_royale;
    return {
      time: this.matchElapsed,
      dt,
      combatants: snapshots,
      lootDrops: lootSnaps,
      chests: chestSnaps,
      supplyDrops: supplySnaps,
      landmarks: this.world?.landmarks ?? [],
      stormCenterX: this.stormCenterX,
      stormCenterZ: this.stormCenterZ,
      stormRadius: this.stormRadius,
      nextStormCenterX: this.nextStormCenterX,
      nextStormCenterZ: this.nextStormCenterZ,
      nextStormRadius: this.nextStormRadius,
      stormShrinkInSec: mode.stormEnabled ? (this.stormMode === 'wait' ? this.stormPhaseTimer : 0) : 9999,
      hasLineOfSight: (a, b) => this.physics.hasLineOfSight(a, b),
    };
  }

  // =========================================================================
  // WEAPON FIRING, PARALLAX-FREE AIMING & BALLISTICS
  // =========================================================================

  private tryFireWeapon(
    shooter: Combatant,
    fireRateMult: number,
    botAimPoint: THREE.Vector3 | null
  ): boolean {
    if (shooter.skyDropping || shooter.isReloading || shooter.fireCooldown > 0) return false;
    const slot = shooter.slots[shooter.activeSlot];
    if (!slot || slot.kind !== 'weapon') return false;

    const weaponId = slot.id as WeaponId;
    const weapon = WEAPONS[weaponId];

    // Check magazine
    if ((slot.ammo ?? 0) <= 0) {
      if (shooter.isPlayer) this.audio.playDryFire();
      this.startReload(shooter);
      return false;
    }

    // Check Mana cost (Nova GL-40 costs 8 Mana/shot)
    if (weapon.manaPerShot && shooter.mana < weapon.manaPerShot) {
      if (shooter.isPlayer) {
        this.audio.playDryFire();
        this.callbacks.onAnnouncement('LOW MANA', `${weapon.name} requires ${weapon.manaPerShot} Mana per shot`);
      }
      return false;
    }

    if (weapon.manaPerShot) {
      shooter.mana = Math.max(0, shooter.mana - weapon.manaPerShot);
    }

    slot.ammo = (slot.ammo ?? weapon.magSize) - 1;
    shooter.fireCooldown = 1 / Math.max(0.2, weapon.fireRate * fireRateMult);
    shooter.lastShotAt = this.matchElapsed;

    // Resolve exact world muzzle position from Blender MuzzlePoint socket
    const muzzlePos = this.getMuzzleWorldPosition(shooter);

    // Resolve parallax-free target world aim point
    const aimPoint = this.tmpVecC;
    if (shooter.isPlayer) {
      this.resolvePlayerAimPoint(weapon.range, aimPoint);
    } else if (botAimPoint) {
      aimPoint.copy(botAimPoint);
    } else {
      aimPoint.set(
        muzzlePos.x - Math.sin(shooter.yaw) * 40,
        muzzlePos.y,
        muzzlePos.z - Math.cos(shooter.yaw) * 40
      );
    }

    const baseDir = aimPoint.clone().sub(muzzlePos);
    if (baseDir.lengthSq() < 0.04) {
      baseDir.set(-Math.sin(shooter.yaw), 0, -Math.cos(shooter.yaw));
    } else {
      baseDir.normalize();
    }

    // Spread with ADS and Crouch (-45% spread) modifiers
    let spread = weapon.spread;
    if (shooter.isAds) spread *= weapon.adsSpreadMult;
    if (shooter.crouching) spread *= GAME_CONSTANTS.CROUCH_SPREAD_MULT;

    const dmg = getWeaponDamage(weaponId, slot.rarity);

    for (let i = 0; i < weapon.pellets; i++) {
      const shotDir = baseDir.clone();
      if (spread > 0) {
        shotDir.x += (Math.random() - 0.5) * 2 * spread;
        shotDir.y += (Math.random() - 0.5) * 2 * spread;
        shotDir.z += (Math.random() - 0.5) * 2 * spread;
        shotDir.normalize();
      }

      if (weaponId === 'nova_gl40') {
        // Arcing ordnance grenade
        const vel = shotDir.multiplyScalar(weapon.projectileSpeed);
        vel.y += 4.2;
        const mesh = this.vfx.createGrenadeProjectile();
        mesh.position.copy(muzzlePos);
        this.scene.add(mesh);

        this.projectiles.push({
          id: this.nextProjectileSeq++,
          ownerId: shooter.id,
          weaponId,
          weaponName: weapon.shortName,
          isUltimate: false,
          kind: 'grenade',
          pos: muzzlePos.clone(),
          prevPos: muzzlePos.clone(),
          vel,
          damage: dmg,
          headshotMult: 1.0,
          coverDamageMult: weapon.coverDamageMult ?? 2.4,
          splashRadius: weapon.splashRadius ?? 6.5,
          gravity: GAME_CONSTANTS.GRAVITY * (weapon.gravityScale ?? 0.65),
          age: 0,
          maxAge: 3.5,
          color: weapon.color,
          mesh,
        });
      } else {
        const vel = shotDir.multiplyScalar(weapon.projectileSpeed);
        const maxAge = Math.min(2.2, weapon.range / Math.max(weapon.projectileSpeed, 30));
        this.projectiles.push({
          id: this.nextProjectileSeq++,
          ownerId: shooter.id,
          weaponId,
          weaponName: weapon.shortName,
          isUltimate: false,
          kind: 'bullet',
          pos: muzzlePos.clone(),
          prevPos: muzzlePos.clone(),
          vel,
          damage: dmg,
          headshotMult: weapon.headshotMult,
          coverDamageMult: weapon.coverDamageMult ?? 1.0,
          splashRadius: 0,
          gravity: weaponId === 'longbow_308' ? 2.2 : 0,
          age: 0,
          maxAge,
          color: weaponId === 'longbow_308' ? 0xfef08a : RARITY_CONFIG[slot.rarity].hex,
        });
      }
    }

    // Muzzle flash, audio, and subtle camera recoil
    this.vfx.spawnMuzzleFlash(
      muzzlePos,
      baseDir,
      weaponId === 'nova_gl40' ? 0xc084fc : 0xffd166,
      weaponId === 'breaker_12g' || weaponId === 'longbow_308' ? 1.4 : 0.95
    );

    if (this.mpActive && (shooter.isPlayer || (this.isMpHost && !shooter.isRemoteHuman))) {
      this.mpClient?.send({
        type: 'fire_fx',
        event: {
          shooterId: shooter.id,
          weaponId,
          ox: Number(muzzlePos.x.toFixed(2)),
          oy: Number(muzzlePos.y.toFixed(2)),
          oz: Number(muzzlePos.z.toFixed(2)),
          endX: Number(aimPoint.x.toFixed(2)),
          endY: Number(aimPoint.y.toFixed(2)),
          endZ: Number(aimPoint.z.toFixed(2)),
          isExplosive: false,
        },
      });
    }

    const listenerPos = this.getCameraFocusPos();
    const distToPlayer = shooter.pos.distanceTo(listenerPos);
    this.audio.playShot(
      weaponId,
      shooter.isPlayer ? 0 : distToPlayer,
      shooter.isPlayer ? 0 : this.computeSpatialPan(shooter.pos)
    );
    if (!shooter.isPlayer && !this.isFriendly(this.player, shooter)) {
      this.pushSoundEvent(
        'gunfire',
        shooter.pos.x,
        shooter.pos.z,
        weaponId === 'longbow_308' ? 120 : 95,
        0.65,
        1.0
      );
    }

    if (shooter.isPlayer) {
      const recoil =
        weaponId === 'longbow_308'
          ? 0.048
          : weaponId === 'breaker_12g'
            ? 0.042
            : weaponId === 'nova_gl40'
              ? 0.036
              : weaponId === 'vanguard_m4'
                ? 0.013
                : 0.008;
      this.camController.addRecoil(shooter.isAds ? recoil * 0.65 : recoil);
      this.camController.addShake(weaponId === 'longbow_308' || weaponId === 'breaker_12g' ? 0.09 : 0.025);
    }

    // Auto-reload when magazine hits 0
    if ((slot.ammo ?? 0) <= 0) {
      this.startReload(shooter);
    }

    return true;
  }

  private resolvePlayerAimPoint(maxRange: number, outPoint: THREE.Vector3): void {
    const rayOrigin = this.tmpVecA;
    const rayDir = this.tmpVecB;
    this.camController.getAimRay(rayOrigin, rayDir);

    let bestDist = maxRange;
    const worldHit = this.physics.raycastWorld(rayOrigin, rayDir, maxRange);
    if (worldHit && worldHit.distance < bestDist) {
      bestDist = worldHit.distance;
    }

    // Also test living enemy hitboxes along center crosshair ray so close-range parallax is zero!
    const segEnd = rayOrigin.clone().addScaledVector(rayDir, bestDist);
    for (const c of this.combatants) {
      if (!c.alive || c.isPlayer || c.skyDropping || this.isFriendly(this.player, c)) continue;
      const hit = this.physics.testCombatantHitbox(rayOrigin, segEnd, c.pos, c.crouching);
      if (hit.hit) {
        const d = hit.t * bestDist;
        if (d > 1.2 && d < bestDist) {
          bestDist = d;
        }
      }
    }

    outPoint.copy(rayOrigin).addScaledVector(rayDir, Math.max(2.5, bestDist));
  }

  private getMuzzleWorldPosition(c: Combatant): THREE.Vector3 {
    const out = new THREE.Vector3();
    if (c.weaponInstance && c.weaponInstance.root.visible && c.hero.root.visible) {
      c.hero.root.updateMatrixWorld(true);
      c.weaponInstance.muzzleNode.getWorldPosition(out);
      if (out.distanceToSquared(c.pos) < 9) {
        return out;
      }
    }
    const eyeY = c.crouching ? 0.92 : 1.38;
    return out.set(
      c.pos.x - Math.sin(c.yaw) * 0.65,
      c.pos.y + eyeY,
      c.pos.z - Math.cos(c.yaw) * 0.65
    );
  }

  private updateProjectiles(dt: number): void {
    for (let i = this.projectiles.length - 1; i >= 0; i--) {
      const p = this.projectiles[i];
      p.age += dt;
      if (p.age >= p.maxAge) {
        if (p.splashRadius > 0) {
          this.detonateSplash(p.pos, p);
        }
        if (p.mesh) this.scene.remove(p.mesh);
        this.projectiles.splice(i, 1);
        continue;
      }

      p.prevPos.copy(p.pos);

      // Gmail Homing Envelope steering
      if (p.kind === 'envelope' && p.targetId) {
        const target = this.combatants.find((c) => c.id === p.targetId && c.alive);
        if (target) {
          const desired = this.tmpVecA
            .set(target.pos.x, target.pos.y + (target.crouching ? 0.7 : 1.15), target.pos.z)
            .sub(p.pos);
          const dist = desired.length();
          if (dist > 0.1) {
            desired.divideScalar(dist);
            const speed = p.vel.length();
            // After initial upward launch arc (0.28s), steer tightly onto enemy
            const turnRate = p.age < 0.28 ? 3.2 : 10.5;
            p.vel.normalize().lerp(desired, Math.min(1, dt * turnRate)).normalize().multiplyScalar(speed);
          }
        }
      }

      if (p.gravity !== 0) {
        p.vel.y -= p.gravity * dt;
      }

      p.pos.addScaledVector(p.vel, dt);

      if (p.mesh) {
        p.mesh.position.copy(p.pos);
        p.mesh.lookAt(p.pos.x + p.vel.x, p.pos.y + p.vel.y, p.pos.z + p.vel.z);
      }

      // 1. Check Google Drive Access Revoked Guardrail Dome interception!
      const projOwner = this.combatants.find((c) => c.id === p.ownerId) ?? null;
      let interceptedByDrive = false;
      for (const gz of this.guardrailZones) {
        if (p.ownerId === gz.ownerId || this.isFriendlyId(projOwner, gz.ownerId)) continue;
        const prevDist = p.prevPos.distanceTo(gz.center);
        const currDist = p.pos.distanceTo(gz.center);
        // Intercept any enemy projectile crossing from outside to inside (or traveling inside boundary)
        if ((prevDist >= gz.radius - 0.5 && currDist <= gz.radius + 0.35) || currDist <= gz.radius) {
          const hitPoint = p.pos.clone();
          this.vfx.spawnGuardrailIntercept(hitPoint, gz.center);
          if (p.kind === 'bullet') {
            this.vfx.spawnTracer(p.prevPos, hitPoint, p.color, 0.032, 0.085);
          }
          interceptedByDrive = true;
          break;
        }
      }
      if (!interceptedByDrive) {
        // Also check deployed Shield Drop protective domes!
        for (const field of this.deployableFields) {
          if (field.itemId !== 'shield_drop') continue;
          if (p.ownerId === field.ownerId || this.isFriendlyId(projOwner, field.ownerId)) continue;
          const prevDist = p.prevPos.distanceTo(field.center);
          const currDist = p.pos.distanceTo(field.center);
          const withinY =
            p.pos.y >= field.center.y - 0.5 && p.pos.y <= field.center.y + field.radius + 0.5;
          if (
            withinY &&
            ((prevDist >= field.radius - 0.45 && currDist <= field.radius + 0.35) ||
              currDist <= field.radius)
          ) {
            const hitPoint = p.pos.clone();
            this.vfx.spawnGuardrailIntercept(hitPoint, field.center);
            if (p.kind === 'bullet') {
              this.vfx.spawnTracer(p.prevPos, hitPoint, p.color, 0.032, 0.085);
            }
            interceptedByDrive = true;
            break;
          }
        }
      }
      if (interceptedByDrive) {
        if (p.mesh) this.scene.remove(p.mesh);
        this.projectiles.splice(i, 1);
        continue;
      }

      // 2. Raycast segment against world geometry & Hard-Light Covers
      const segVec = this.tmpVecA.subVectors(p.pos, p.prevPos);
      const segLen = segVec.length();
      if (segLen < 0.0001) continue;
      const segDir = this.tmpVecB.copy(segVec).divideScalar(segLen);

      const worldHit = this.physics.raycastWorld(p.prevPos, segDir, segLen);
      let maxT = worldHit ? worldHit.distance / segLen : 1.0;

      // 3. Test segment against living combatants' dual-zone Head/Torso hitboxes
      let hitTarget: Combatant | null = null;
      let hitHeadshot = false;
      let hitPoint = worldHit ? worldHit.point : p.pos.clone();

      for (const target of this.combatants) {
        if (!target.alive || target.id === p.ownerId || target.rewind.active) continue;
        if (this.isFriendly(projOwner, target)) continue;
        const res = this.physics.testCombatantHitbox(p.prevPos, p.pos, target.pos, target.crouching);
        if (res.hit && res.t <= maxT) {
          maxT = res.t;
          hitTarget = target;
          hitHeadshot = res.headshot && p.headshotMult > 1.0;
          hitPoint = res.point
            ? new THREE.Vector3(res.point.x, res.point.y, res.point.z)
            : p.prevPos.clone().lerp(p.pos, res.t);
        }
      }

      // Render crisp tracer segment for ballistic bullets
      if (p.kind === 'bullet') {
        const isSniper = p.weaponId === 'longbow_308';
        this.vfx.spawnTracer(
          p.prevPos,
          hitPoint,
          p.color,
          isSniper ? 0.055 : 0.028,
          isSniper ? 0.28 : 0.095
        );
      }

      if (hitTarget) {
        if (p.splashRadius > 0) {
          this.detonateSplash(hitPoint, p);
        } else if (!p.visualOnly) {
          const finalDmg = Math.round(p.damage * (hitHeadshot ? p.headshotMult : 1.0));
          this.applyCombatDamage(hitTarget, projOwner, finalDmg, {
            headshot: hitHeadshot,
            weaponName: p.weaponName,
            isUltimate: p.isUltimate,
            hitPoint,
          });
        }
        if (p.mesh) this.scene.remove(p.mesh);
        this.projectiles.splice(i, 1);
      } else if (worldHit) {
        if (p.splashRadius > 0) {
          this.detonateSplash(worldHit.point, p);
        } else {
          this.vfx.spawnHitImpact(worldHit.point, { isWorld: true });
          if (!p.visualOnly && worldHit.destructible && worldHit.colliderId) {
            this.damageHardLightBarrier(worldHit.colliderId, p.damage * p.coverDamageMult, worldHit.point);
          }
        }
        if (p.mesh) this.scene.remove(p.mesh);
        this.projectiles.splice(i, 1);
      }
    }
  }

  private detonateSplash(center: THREE.Vector3, proj: Projectile): void {
    const color = proj.kind === 'envelope' ? 0xea4335 : 0xc084fc;
    this.vfx.spawnExplosion(center, proj.splashRadius, color);

    const listenerPos = this.getCameraFocusPos();
    const distToPlayer = center.distanceTo(listenerPos);
    this.audio.playExplosion(distToPlayer, this.computeSpatialPan(center));
    const attacker = this.combatants.find((c) => c.id === proj.ownerId) ?? null;
    if (proj.ownerId !== this.player?.id && !this.isFriendly(this.player, attacker)) {
      this.pushSoundEvent('gunfire', center.x, center.z, 105, 0.85, 1.0);
    }
    if (this.player && this.player.alive && distToPlayer < 24) {
      this.camController.addShake(Math.max(0.05, (1 - distToPlayer / 24) * 0.28));
    }

    if (proj.visualOnly) return;

    // Broadcast grenade explosion VFX to remote peers in MP
    if (
      this.mpActive &&
      proj.kind === 'grenade' &&
      proj.weaponId &&
      attacker &&
      (attacker.isPlayer || (this.isMpHost && !attacker.isRemoteHuman))
    ) {
      this.mpClient?.send({
        type: 'fire_fx',
        event: {
          shooterId: attacker.id,
          weaponId: proj.weaponId,
          ox: Number(center.x.toFixed(2)),
          oy: Number(center.y.toFixed(2)),
          oz: Number(center.z.toFixed(2)),
          endX: Number(center.x.toFixed(2)),
          endY: Number(center.y.toFixed(2)),
          endZ: Number(center.z.toFixed(2)),
          isExplosive: true,
          explosionRadius: proj.splashRadius,
        },
      });
    }

    // Damage combatants inside blast radius with smooth radial falloff
    for (const target of this.combatants) {
      if (!target.alive || target.rewind.active) continue;
      // Avoid self-damage on Gmail Ultimate; allow reduced self-splash on Nova GL-40
      if (target.id === proj.ownerId && proj.kind === 'envelope') continue;
      if (this.isFriendly(attacker, target)) continue;
      const bodyCenter = this.tmpVecA.set(target.pos.x, target.pos.y + 0.95, target.pos.z);
      const dist = bodyCenter.distanceTo(center);
      if (dist <= proj.splashRadius) {
        const falloff = 1 - (dist / proj.splashRadius) * 0.45;
        const mult = target.id === proj.ownerId ? 0.5 : 1.0;
        const dmg = Math.max(8, Math.round(proj.damage * falloff * mult));
        this.applyCombatDamage(target, attacker, dmg, {
          headshot: false,
          weaponName: proj.weaponName,
          isUltimate: proj.isUltimate,
          hitPoint: bodyCenter.clone(),
        });
      }
    }

    // Blast Hard-Light Cover barriers inside splash radius (Nova GL-40 excels at breaking barriers!)
    for (let i = this.barriers.length - 1; i >= 0; i--) {
      const b = this.barriers[i];
      if (b.pos.distanceTo(center) <= proj.splashRadius + 2.0) {
        this.damageHardLightBarrier(b.colliderId, proj.damage * proj.coverDamageMult, b.pos);
      }
    }
  }

  // =========================================================================
  // DAMAGE, HEADSHOT CRITS, DIRECTIONAL ARCS & ELIMINATIONS
  // =========================================================================

  private applyCombatDamage(
    victim: Combatant,
    attacker: Combatant | null,
    amount: number,
    meta: {
      headshot: boolean;
      weaponName: string;
      isUltimate: boolean;
      hitPoint: THREE.Vector3;
    }
  ): void {
    if (!victim.alive || amount <= 0) return;
    if (this.isFriendly(attacker, victim)) return;

    // Server-authoritative combat routing in Multiplayer
    if (this.mpActive) {
      const authorized =
        Boolean(attacker?.isPlayer) ||
        (attacker === null && victim.isPlayer) ||
        Boolean(this.isMpHost && attacker && !attacker.isRemoteHuman && !attacker.isPlayer);
      if (!authorized) return;

      this.mpClient?.send({
        type: 'hit_report',
        targetId: victim.id,
        ...(attacker && !attacker.isPlayer ? { attackerId: attacker.id } : {}),
        amount: Math.round(amount),
        headshot: meta.headshot,
        weaponName: meta.weaponName,
        isUltimate: meta.isUltimate,
        hitX: Number(meta.hitPoint.x.toFixed(2)),
        hitY: Number(meta.hitPoint.y.toFixed(2)),
        hitZ: Number(meta.hitPoint.z.toFixed(2)),
      });
      return;
    }

    const hadShield = victim.shield > 0;
    const shieldAbsorbed = Math.min(victim.shield, amount);
    victim.shield = Math.max(0, victim.shield - shieldAbsorbed);
    const hpDamage = amount - shieldAbsorbed;
    victim.health = Math.max(0, victim.health - hpDamage);

    victim.lastDamagedAt = this.matchElapsed;
    victim.recentDamageTaken += amount;
    if (attacker && attacker.id !== victim.id) {
      victim.lastAttackerId = attacker.id;
    }

    // Visual hit flash & sparks
    victim.hero.flashHit(meta.headshot ? 0xfbbf24 : hadShield ? 0x38bdf8 : 0xef4444, 0.72);
    victim.hitFlashTimer = 0.11;

    this.vfx.spawnHitImpact(meta.hitPoint, {
      isShield: hadShield && shieldAbsorbed > 0,
      isHeadshot: meta.headshot,
    });

    const shieldBroken = hadShield && victim.shield <= 0;
    if (shieldBroken) {
      this.vfx.spawnShieldBreak(victim.pos);
      const isDirect = Boolean(attacker?.isPlayer || victim.isPlayer);
      const dist = this.player ? victim.pos.distanceTo(this.player.pos) : 0;
      this.audio.playShieldCrack(dist, isDirect, isDirect ? 0 : this.computeSpatialPan(victim.pos));
      if (victim.isPlayer) {
        this.callbacks.onPlayerShieldBreak?.();
        this.camController.addShake(0.18);
      }
    }

    const killed = victim.health <= 0;

    // Feedback when LOCAL PLAYER deals damage
    if (attacker?.isPlayer && !victim.isPlayer) {
      attacker.damageDealt += amount;
      if (meta.headshot) attacker.headshots++;
      this.audio.playHitmarker(meta.headshot, shieldAbsorbed > 0 && hpDamage === 0);
      this.callbacks.onHitMarker(meta.headshot, killed, shieldBroken);

      const screen = this.projectWorldToScreen(meta.hitPoint);
      if (screen) {
        this.callbacks.onFloatingDamage({
          screenX: screen.x,
          screenY: screen.y,
          amount,
          kind: meta.headshot ? 'headshot' : shieldAbsorbed > hpDamage ? 'shield' : 'health',
          worldX: meta.hitPoint.x,
          worldY: meta.hitPoint.y,
          worldZ: meta.hitPoint.z,
        });
      }
    }

    // Feedback when LOCAL PLAYER takes damage (Directional Damage Indicator!)
    if (victim.isPlayer && attacker && attacker.id !== victim.id) {
      const dx = attacker.pos.x - victim.pos.x;
      const dz = attacker.pos.z - victim.pos.z;
      const fx = -Math.sin(victim.yaw);
      const fz = -Math.cos(victim.yaw);
      const rx = Math.cos(victim.yaw);
      const rz = -Math.sin(victim.yaw);
      const bearingRad = Math.atan2(dx * rx + dz * rz, dx * fx + dz * fz);
      this.callbacks.onDirectionalDamage({ bearingRad, amount, isStorm: false });
      this.camController.addShake(Math.min(0.24, 0.06 + amount * 0.003));
    }

    if (killed) {
      this.handleElimination(victim, attacker, meta.weaponName, meta.headshot, meta.isUltimate, false);
    }
  }

  private applyStormDamage(victim: Combatant, dps: number): void {
    if (!victim.alive) return;
    if (this.mpActive) {
      if (victim.isPlayer) {
        this.mpClient?.send({ type: 'storm_damage', amount: Math.round(dps) });
      } else if (this.isMpHost && !victim.isRemoteHuman) {
        this.mpClient?.send({ type: 'storm_damage', targetId: victim.id, amount: Math.round(dps) });
      }
      return;
    }
    victim.health = Math.max(0, victim.health - dps);
    if (victim.isPlayer) {
      this.audio.playStormTick();
      this.callbacks.onDirectionalDamage({ bearingRad: Math.PI, amount: dps, isStorm: true });
    }
    if (victim.health <= 0) {
      this.handleElimination(victim, null, 'The Storm', false, false, true);
    }
  }

  private handleElimination(
    victim: Combatant,
    killer: Combatant | null,
    weaponName: string,
    headshot: boolean,
    isUltimate: boolean,
    isStorm: boolean
  ): void {
    if (!victim.alive) return;
    const aliveBefore = this.combatants.filter((c) => c.alive).length;
    if (victim.ridingGBikeId) {
      this.dismountGBike(victim, false);
    }
    if (victim.sliding) {
      this.endSlide(victim, false);
    }
    victim.alive = false;
    victim.channel = null;
    if (victim.isPlayer) {
      this.sprintLatchedOnChannel = false;
      this.sprintLatchedOnSlide = false;
      this.ctrlSlideConsumed = false;
    }
    victim.sprinting = false;
    this.cancelReload(victim);
    victim.hero.root.visible = false;

    this.vfx.spawnExplosion(
      new THREE.Vector3(victim.pos.x, victim.pos.y + 1.0, victim.pos.z),
      2.6,
      HERO_MAP[victim.heroId].hexPrimary
    );

    // Drop victim's actual looted gear on death (highest-rarity weapon + carried utility items)
    let bestWeapon: InventorySlot | null = null;
    const carriedItems: InventorySlot[] = [];
    const rarityRank: Record<Rarity, number> = { common: 1, rare: 2, epic: 3 };
    for (const s of victim.slots) {
      if (!s) continue;
      if (s.kind === 'weapon') {
        if (!bestWeapon || rarityRank[s.rarity] > rarityRank[bestWeapon.rarity]) {
          bestWeapon = s;
        }
      } else if ((s.count ?? 0) > 0) {
        carriedItems.push(s);
      }
    }
    carriedItems.sort((a, b) => rarityRank[b.rarity] - rarityRank[a.rarity]);

    const deathDrops: { kind: 'weapon' | 'item'; id: WeaponId | UtilityItemId; rarity: Rarity; count: number }[] = [];
    if (bestWeapon) {
      deathDrops.push({ kind: 'weapon', id: bestWeapon.id, rarity: bestWeapon.rarity, count: 1 });
    }
    for (const it of carriedItems.slice(0, 2)) {
      deathDrops.push({ kind: 'item', id: it.id, rarity: it.rarity, count: it.count ?? 1 });
    }

    const groundY = this.physics.getSupportHeight(victim.pos.x, victim.pos.z, victim.pos.y + 1, 0.3, 0.5);
    deathDrops.forEach((d, idx) => {
      const ang = (idx / Math.max(1, deathDrops.length)) * Math.PI * 2 + 0.4;
      const dist = deathDrops.length === 1 ? 0.5 : 0.95;
      const dx = victim.pos.x + Math.cos(ang) * dist;
      const dz = victim.pos.z + Math.sin(ang) * dist;
      const dy = this.physics.getSupportHeight(dx, dz, victim.pos.y + 1, 0.3, 0.5);
      this.spawnLootDrop(dx, Math.abs(dy - groundY) <= 1.2 ? dy : groundY, dz, d.kind, d.id, d.rarity, d.count);
    });

    if (killer && killer.id !== victim.id) {
      killer.eliminations++;
      killer.mana = Math.min(GAME_CONSTANTS.MAX_MANA, killer.mana + GAME_CONSTANTS.ELIM_MANA_BONUS);
      this.audio.playElimination(killer.isPlayer);
    } else {
      this.audio.playElimination(false);
    }

    this.callbacks.onKillFeed({
      id: this.nextKillFeedSeq++,
      killer: isStorm ? 'Googleplex Storm' : killer ? killer.name : 'Campus Hazard',
      killerHero: killer ? killer.heroId : victim.heroId,
      victim: victim.name,
      victimHero: victim.heroId,
      weapon: weaponName,
      headshot,
      isUltimate,
      isStorm,
      timestamp: this.matchElapsed,
    });

    const remainingAlive = this.combatants.filter((c) => c.alive);
    if (victim.isPlayer) {
      this.finishMatch(false, aliveBefore);
    } else if (remainingAlive.length === 1 && remainingAlive[0].isPlayer) {
      this.finishMatch(true, 1);
    }
  }

  private finishMatch(won: boolean, placement: number): void {
    if (this.matchPhase === 'ended' || !this.player) return;
    const aliveRemaining = this.combatants.filter((c) => c.alive).length;
    const matchOngoing = !won && aliveRemaining >= 1;
    if (!matchOngoing) {
      this.matchPhase = 'ended';
    }
    this.mapOpen = false;
    this.mouseLeftDown = false;
    this.mouseRightDown = false;
    this.sprintLatchedOnReload = false;
    this.sprintLatchedOnChannel = false;
    this.sprintLatchedOnSlide = false;
    this.ctrlSlideConsumed = false;
    this.keys.clear();
    this.audio.setGliderWind(false);
    if (document.pointerLockElement === this.renderer.domElement) {
      document.exitPointerLock();
    }

    if (won) {
      this.audio.playVictory();
    } else {
      this.audio.playDefeat();
    }

    const heroDef = HERO_MAP[this.player.heroId];
    const summary: MatchSummary = {
      won,
      placement,
      totalPlayers: this.combatants.length,
      heroId: this.player.heroId,
      heroName: heroDef.productName,
      heroPersona: heroDef.personaName,
      eliminations: this.player.eliminations,
      headshots: this.player.headshots,
      damageDealt: Math.round(this.player.damageDealt),
      survivedSeconds: Math.round(this.matchElapsed),
      botDifficulty: this.activeBotDifficulty,
      gameMode: this.activeGameMode,
      isMultiplayer: false,
      matchOngoing,
    };
    this.emitHudSnapshot();
    this.callbacks.onMatchEnd(summary);
  }

  // =========================================================================
  // ALL 6 WORKSPACE PRODUCT ULTIMATES (§2 & §15)
  // =========================================================================

  private tryCastUltimate(caster: Combatant, botAimPoint: THREE.Vector3 | null = null): void {
    if (!caster.alive || caster.skyDropping || caster.rewind.active) return;

    if (caster.silencedSec > 0) {
      if (caster.isPlayer) {
        this.audio.playSilenced();
        this.callbacks.onAnnouncement('ACCESS REVOKED', `Ultimate silenced (${caster.silencedSec.toFixed(1)}s)`);
      }
      return;
    }

    const heroDef = HERO_MAP[caster.heroId];
    const ult = heroDef.ultimate;
    if (caster.ultCooldown > 0 || caster.mana < ult.manaCost) {
      if (caster.isPlayer) this.audio.playDryFire();
      return;
    }

    if (caster.ridingGBikeId) this.dismountGBike(caster, false);
    if (caster.channel) this.cancelChannel(caster);
    if (caster.isReloading) this.cancelReload(caster);
    caster.mana = Math.max(0, caster.mana - ult.manaCost);
    caster.ultCooldown = ult.cooldown;

    const distToPlayer = this.player ? caster.pos.distanceTo(this.player.pos) : 0;
    this.audio.playUltimate(
      caster.heroId,
      caster.isPlayer ? 0 : distToPlayer,
      caster.isPlayer ? 0 : this.computeSpatialPan(caster.pos)
    );
    if (!caster.isPlayer) {
      this.pushSoundEvent('gunfire', caster.pos.x, caster.pos.z, 105, 0.85, 1.0);
    }

    if (caster.isPlayer) {
      this.callbacks.onAnnouncement(ult.name.toUpperCase(), ult.subtitle);
    }

    // Broadcast Ultimate cast to all peers in Multiplayer (including Slides aim target)
    if (this.mpActive && (caster.isPlayer || (this.isMpHost && !caster.isRemoteHuman))) {
      let targetX: number | undefined;
      let targetY: number | undefined;
      let targetZ: number | undefined;
      if (caster.heroId === 'slides') {
        const aimPt = new THREE.Vector3();
        if (caster.isPlayer) {
          this.resolvePlayerAimPoint(85, aimPt);
        } else if (botAimPoint) {
          aimPt.copy(botAimPoint);
        } else {
          aimPt.set(
            caster.pos.x - Math.sin(caster.yaw) * 85,
            caster.pos.y + 1.4,
            caster.pos.z - Math.cos(caster.yaw) * 85
          );
        }
        targetX = Number(aimPt.x.toFixed(2));
        targetY = Number(aimPt.y.toFixed(2));
        targetZ = Number(aimPt.z.toFixed(2));
      }
      this.mpClient?.send({
        type: 'ult_cast',
        event: {
          casterId: caster.id,
          heroId: caster.heroId,
          x: Number(caster.pos.x.toFixed(2)),
          y: Number(caster.pos.y.toFixed(2)),
          z: Number(caster.pos.z.toFixed(2)),
          yaw: Number(caster.yaw.toFixed(3)),
          pitch: Number(caster.pitch.toFixed(3)),
          targetX,
          targetY,
          targetZ,
        },
      });
    }

    switch (caster.heroId) {
      case 'gmail':
        this.castGmailReplyAll(caster);
        break;
      case 'drive':
        this.castDriveAccessRevoked(caster);
        break;
      case 'calendar':
        this.castCalendarHardStop(caster);
        break;
      case 'chat':
        this.castChatPingOverload(caster);
        break;
      case 'slides':
        this.castSlidesExecutiveSpotlight(caster, botAimPoint);
        break;
      case 'docs':
        this.castDocsVersionHistory(caster);
        break;
    }
  }

  /** 1. GMAIL — Reply-All Barrage: 6 homing explosive envelopes targeting up to 3 nearest enemies (34 splash, 5m). */
  private castGmailReplyAll(caster: Combatant, visualOnly = false): void {
    const enemies = this.combatants
      .filter((c) => c.alive && !c.skyDropping && c.id !== caster.id && !this.isFriendly(caster, c))
      .map((c) => ({ c, dist: c.pos.distanceTo(caster.pos) }))
      .filter((e) => e.dist <= 95)
      .sort((a, b) => a.dist - b.dist)
      .slice(0, 3);

    const origin = new THREE.Vector3(caster.pos.x, caster.pos.y + 1.85, caster.pos.z);

    for (let i = 0; i < 6; i++) {
      const assignedTarget = enemies.length > 0 ? enemies[i % enemies.length].c : null;
      const fanYaw = caster.yaw + (i - 2.5) * 0.24;
      const launchDir = new THREE.Vector3(
        -Math.sin(fanYaw) * 0.85,
        0.58 + (i % 2) * 0.16,
        -Math.cos(fanYaw) * 0.85
      ).normalize();

      const mesh = this.vfx.createGmailEnvelopeMissile();
      mesh.position.copy(origin);
      this.scene.add(mesh);

      this.projectiles.push({
        id: this.nextProjectileSeq++,
        ownerId: caster.id,
        weaponName: 'Reply-All Barrage',
        isUltimate: true,
        kind: 'envelope',
        pos: origin.clone().addScaledVector(launchDir, 0.5),
        prevPos: origin.clone(),
        vel: launchDir.multiplyScalar(34),
        damage: 34,
        headshotMult: 1.0,
        coverDamageMult: 1.8,
        splashRadius: 5.0,
        gravity: 3.5,
        age: 0,
        maxAge: 3.8,
        color: 0xea4335,
        targetId: assignedTarget?.id,
        mesh,
        visualOnly,
      });
    }
  }

  /**
   * 2. GOOGLE DRIVE — Access Revoked (Permission Guardrail):
   * - Deploys 12m Guardrail Dome for 6s blocking enemy projectiles
   * - Revokes enemies within 16m: 22 dmg, knockback outward, 3.0s Silence (blocks Ults & cancels channels!)
   * - Grants +40 Shield to caster!
   */
  private castDriveAccessRevoked(caster: Combatant, visualOnly = false): void {
    if (!visualOnly) {
      const prevShield = caster.shield;
      caster.shield = Math.min(GAME_CONSTANTS.MAX_SHIELD, caster.shield + 40);
      const gained = Math.round(caster.shield - prevShield);
      if (caster.isPlayer && gained > 0) {
        const scr = this.projectWorldToScreen(caster.pos.clone().add(new THREE.Vector3(0, 1.8, 0)));
        if (scr) {
          this.callbacks.onFloatingDamage({ screenX: scr.x, screenY: scr.y, amount: gained, kind: 'heal' });
        }
      }
      if (this.mpActive && (caster.isPlayer || (this.isMpHost && !caster.isRemoteHuman))) {
        this.mpClient?.send({
          type: 'vitals_sync',
          ...(caster.isPlayer ? {} : { combatantId: caster.id }),
          health: Math.round(caster.health),
          shield: Math.round(caster.shield),
          mana: Math.round(caster.mana),
        });
      }
    }
    this.vfx.spawnStatusBurst(caster.pos, 0x34a853);

    const center = caster.pos.clone();
    const visual = this.vfx.createDriveGuardrailDome(center, 12.0);
    this.guardrailZones.push({
      ownerId: caster.id,
      center,
      radius: 12.0,
      elapsed: 0,
      duration: 6.0,
      visual,
    });

    // Revoke sharing permissions within 16m
    for (const enemy of this.combatants) {
      if (!enemy.alive || enemy.skyDropping || enemy.id === caster.id || this.isFriendly(caster, enemy)) continue;
      const dx = enemy.pos.x - center.x;
      const dz = enemy.pos.z - center.z;
      const dist = Math.hypot(dx, dz);
      if (dist <= 16.0) {
        enemy.silencedSec = Math.max(enemy.silencedSec, 3.0);
        if (enemy.channel) {
          this.cancelChannel(enemy, enemy.isPlayer ? 'Access Revoked — Channel Canceled!' : undefined);
        }
        const nx = dist > 0.01 ? dx / dist : 1;
        const nz = dist > 0.01 ? dz / dist : 0;
        enemy.vel.x = nx * 16.5;
        enemy.vel.z = nz * 16.5;
        enemy.vel.y = Math.max(enemy.vel.y, 4.8);
        enemy.grounded = false;

        if (!visualOnly) {
          this.applyCombatDamage(enemy, caster, 22, {
            headshot: false,
            weaponName: 'Access Revoked',
            isUltimate: true,
            hitPoint: new THREE.Vector3(enemy.pos.x, enemy.pos.y + 1.1, enemy.pos.z),
          });
        }

        if (enemy.isPlayer) {
          this.audio.playSilenced();
          this.callbacks.onAnnouncement('ACCESS REVOKED', 'Silenced for 3.0s — Ultimates & Channels Blocked!');
        }
      }
    }
  }

  /** 3. GOOGLE CALENDAR — Hard Stop: 20m chrono-field (6s), -65% enemy speed / -55% fire rate, +40% caster speed / +45% fire rate. */
  private castCalendarHardStop(caster: Combatant): void {
    const center = caster.pos.clone();
    const visual = this.vfx.createCalendarChronoField(center, 20.0);
    this.chronoZones.push({
      ownerId: caster.id,
      center,
      radius: 20.0,
      elapsed: 0,
      duration: 6.0,
      visual,
    });
  }

  /** 4. GOOGLE CHAT — @all Ping Overload: 28m shockwave (45 dmg, -35 Mana, reveals ALL living enemies for 8s!). */
  private castChatPingOverload(caster: Combatant, visualOnly = false): void {
    const center = caster.pos.clone();
    this.vfx.spawnChatPingWave(center, 28.0);
    caster.revealedAllSec = 8.0;
    // In Teams mode, teammates of a Chat caster also share the 8s recon reveal!
    if (this.mpActive && this.mpFormat === 'teams' && this.player && this.isFriendly(caster, this.player)) {
      this.player.revealedAllSec = Math.max(this.player.revealedAllSec, 8.0);
    }

    for (const enemy of this.combatants) {
      if (!enemy.alive || enemy.id === caster.id || this.isFriendly(caster, enemy)) continue;
      enemy.revealedSec = Math.max(enemy.revealedSec, 8.0);
      const dist = enemy.pos.distanceTo(center);
      if (dist <= 28.0 && !enemy.skyDropping) {
        enemy.mana = Math.max(0, enemy.mana - 35);
        if (!visualOnly) {
          this.applyCombatDamage(enemy, caster, 45, {
            headshot: false,
            weaponName: '@all Ping Overload',
            isUltimate: true,
            hitPoint: new THREE.Vector3(enemy.pos.x, enemy.pos.y + 1.15, enemy.pos.z),
          });
        }
      }
    }
  }

  /** 5. GOOGLE SLIDES — Executive Spotlight: 0.3s charge + piercing 85m × 2.4m golden orbital beam (85 dmg + knockback). */
  private castSlidesExecutiveSpotlight(caster: Combatant, botAimPoint: THREE.Vector3 | null): void {
    const origin = new THREE.Vector3(
      caster.pos.x,
      caster.pos.y + (caster.crouching ? 0.95 : 1.42),
      caster.pos.z
    );
    const dir = new THREE.Vector3();

    if (caster.isPlayer) {
      const aimPt = new THREE.Vector3();
      this.resolvePlayerAimPoint(85, aimPt);
      dir.subVectors(aimPt, origin).normalize();
    } else if (botAimPoint) {
      dir.subVectors(botAimPoint, origin).normalize();
    } else {
      dir.set(-Math.sin(caster.yaw), 0, -Math.cos(caster.yaw)).normalize();
    }

    this.vfx.spawnSlidesChargeBeam(origin, dir, 85, 0.3);
    this.pendingBeams.push({
      ownerId: caster.id,
      origin,
      dir,
      remaining: 0.3,
    });
  }

  private updatePendingSlidesBeams(dt: number): void {
    for (let i = this.pendingBeams.length - 1; i >= 0; i--) {
      const pb = this.pendingBeams[i];
      pb.remaining -= dt;
      if (pb.remaining > 0) continue;

      this.pendingBeams.splice(i, 1);
      const caster = this.combatants.find((c) => c.id === pb.ownerId);
      if (!caster || !caster.alive) continue;

      // Refresh origin/direction at exact fire moment for crisp responsiveness
      const origin = new THREE.Vector3(
        caster.pos.x,
        caster.pos.y + (caster.crouching ? 0.95 : 1.42),
        caster.pos.z
      );
      const dir = pb.dir.clone();
      if (caster.isPlayer) {
        const aimPt = new THREE.Vector3();
        this.resolvePlayerAimPoint(85, aimPt);
        dir.subVectors(aimPt, origin).normalize();
      }

      const beamLen = 85;
      const beamHalfWidth = 1.2; // 2.4m total beam width
      this.vfx.spawnSlidesOrbitalBeam(origin, dir, beamLen, 2.4);
      if (caster.isPlayer) {
        this.camController.addShake(0.24);
      }

      const segEnd = origin.clone().addScaledVector(dir, beamLen);
      const segLine = new THREE.Line3(origin, segEnd);
      const closest = new THREE.Vector3();

      if (!pb.visualOnly) {
        for (const enemy of this.combatants) {
          if (
            !enemy.alive ||
            enemy.skyDropping ||
            enemy.id === caster.id ||
            enemy.rewind.active ||
            this.isFriendly(caster, enemy)
          ) {
            continue;
          }
          const bodyCenter = new THREE.Vector3(enemy.pos.x, enemy.pos.y + 1.0, enemy.pos.z);
          segLine.closestPointToPoint(bodyCenter, true, closest);
          if (closest.distanceTo(bodyCenter) <= beamHalfWidth + 0.5) {
            enemy.vel.addScaledVector(dir, 18.5);
            enemy.vel.y = Math.max(enemy.vel.y, 6.2);
            enemy.grounded = false;
            this.applyCombatDamage(enemy, caster, 85, {
              headshot: false,
              weaponName: 'Executive Spotlight',
              isUltimate: true,
              hitPoint: bodyCenter,
            });
          }
        }
      }

      // Pierces & shatters Hard-Light Covers in beam path
      for (let k = this.barriers.length - 1; k >= 0; k--) {
        const b = this.barriers[k];
        segLine.closestPointToPoint(b.pos, true, closest);
        if (closest.distanceTo(b.pos) <= beamHalfWidth + 1.5) {
          this.damageHardLightBarrier(b.colliderId, 400, b.pos);
        }
      }
    }
  }

  /**
   * 6. GOOGLE DOCS — Version History (Rollback):
   * - 12m Redline Pulse (35 dmg) at departure point
   * - Smooth 0.45s rewind along 4.0s ring-buffer with glowing blue Doc-cursor ghost trails
   * - Restores max(current, saved) Health & Shield, cleanses slows, auto-reloads active weapon!
   */
  private castDocsVersionHistory(caster: Combatant): void {
    const departurePos = caster.pos.clone();
    this.vfx.spawnDocsRedlinePulse(departurePos, 12.0);

    // 12m Redline Pulse at departure point (35 dmg)
    for (const enemy of this.combatants) {
      if (!enemy.alive || enemy.skyDropping || enemy.id === caster.id || this.isFriendly(caster, enemy)) continue;
      if (enemy.pos.distanceTo(departurePos) <= 12.0) {
        this.applyCombatDamage(enemy, caster, 35, {
          headshot: false,
          weaponName: 'Version History (Redline)',
          isUltimate: true,
          hitPoint: new THREE.Vector3(enemy.pos.x, enemy.pos.y + 1.0, enemy.pos.z),
        });
      }
    }

    const oldest = caster.history[0] ?? {
      pos: departurePos.clone(),
      health: caster.health,
      shield: caster.shield,
      timestamp: this.matchElapsed,
    };

    // Build reverse path from current -> oldest snapshot
    const path: THREE.Vector3[] = [];
    for (let i = caster.history.length - 1; i >= 0; i--) {
      path.push(caster.history[i].pos.clone());
    }
    if (path.length < 2) {
      path.unshift(departurePos.clone());
      path.push(oldest.pos.clone());
    }

    // Cleanse slows & auto-reload active weapon immediately
    if (caster.ridingGBikeId) {
      this.dismountGBike(caster, false);
    }
    if (caster.sliding) {
      this.endSlide(caster, false);
    }
    caster.slowedSec = 0;
    this.cancelReload(caster);
    caster.sprinting = false;
    const slot = caster.slots[caster.activeSlot];
    if (slot && slot.kind === 'weapon') {
      slot.ammo = WEAPONS[slot.id as WeaponId].magSize;
    }

    caster.rewind = {
      active: true,
      elapsed: 0,
      duration: 0.45,
      path,
      targetHealth: Math.max(caster.health, oldest.health),
      targetShield: Math.max(caster.shield, oldest.shield),
      ghostTimer: 0,
    };
  }

  private updateDocsRewind(c: Combatant, dt: number): void {
    const rw = c.rewind;
    rw.elapsed += dt;
    rw.ghostTimer -= dt;

    const progress = Math.min(1, rw.elapsed / Math.max(rw.duration, 0.05));
    const maxIdx = rw.path.length - 1;
    const fIdx = progress * maxIdx;
    const i0 = Math.floor(fIdx);
    const i1 = Math.min(maxIdx, i0 + 1);
    const localT = fIdx - i0;

    c.pos.lerpVectors(rw.path[i0], rw.path[i1], localT);
    c.vel.set(0, 0, 0);

    if (rw.ghostTimer <= 0) {
      rw.ghostTimer = 0.055;
      this.vfx.spawnDocsGhostTrail(c.pos, c.yaw);
    }

    if (progress >= 1) {
      rw.active = false;
      const hpGain = Math.round(Math.max(0, rw.targetHealth - c.health));
      const shGain = Math.round(Math.max(0, rw.targetShield - c.shield));
      c.health = rw.targetHealth;
      c.shield = rw.targetShield;
      c.slowedSec = 0;
      c.history = [
        {
          pos: c.pos.clone(),
          health: c.health,
          shield: c.shield,
          timestamp: this.matchElapsed,
        },
      ];
      this.vfx.spawnStatusBurst(c.pos, 0x4285f4);

      if (this.mpActive && (c.isPlayer || (this.isMpHost && !c.isRemoteHuman))) {
        this.mpClient?.send({
          type: 'vitals_sync',
          ...(c.isPlayer ? {} : { combatantId: c.id }),
          health: Math.round(c.health),
          shield: Math.round(c.shield),
          mana: Math.round(c.mana),
        });
      }

      if (c.isPlayer && hpGain + shGain > 0) {
        const scr = this.projectWorldToScreen(c.pos.clone().add(new THREE.Vector3(0, 1.85, 0)));
        if (scr) {
          this.callbacks.onFloatingDamage({
            screenX: scr.x,
            screenY: scr.y,
            amount: hpGain + shGain,
            kind: 'heal',
          });
        }
      }
    }
  }

  private updateActiveZones(dt: number): void {
    for (let i = this.guardrailZones.length - 1; i >= 0; i--) {
      const z = this.guardrailZones[i];
      z.elapsed += dt;
      const rem = z.duration - z.elapsed;
      z.visual.update(dt, z.elapsed, rem);
      if (rem <= 0) {
        z.visual.dispose();
        this.guardrailZones.splice(i, 1);
      }
    }

    for (let i = this.chronoZones.length - 1; i >= 0; i--) {
      const z = this.chronoZones[i];
      z.elapsed += dt;
      const rem = z.duration - z.elapsed;
      z.visual.update(dt, z.elapsed, rem);
      if (rem <= 0) {
        z.visual.dispose();
        this.chronoZones.splice(i, 1);
      }
    }

    for (let i = this.deployableFields.length - 1; i >= 0; i--) {
      const f = this.deployableFields[i];
      f.elapsed += dt;
      const rem = f.duration - f.elapsed;
      f.visual.update(dt, f.elapsed, rem);
      if (rem <= 0) {
        f.visual.dispose();
        this.scene.remove(f.propMesh);
        this.deployableFields.splice(i, 1);
        continue;
      }

      // Gentle spin on the central ground beacon prop
      f.propMesh.rotation.y += dt * (f.itemId === 'shield_drop' ? 0.85 : 1.15);

      f.vitalsSyncAccum += dt;
      const shouldSyncVitals = f.vitalsSyncAccum >= 0.5;
      if (shouldSyncVitals) f.vitalsSyncAccum = 0;

      for (const c of this.combatants) {
        if (!c.alive || c.skyDropping) continue;
        if (c.id !== f.ownerId && !this.isFriendlyId(c, f.ownerId)) continue;
        const horizDist = Math.hypot(c.pos.x - f.center.x, c.pos.z - f.center.z);
        const vertDiff = Math.abs(c.pos.y - f.center.y);
        if (horizDist > f.radius || vertDiff > f.radius + 1.5) continue;

        // In MP, only authoritatively mutate local player or host-owned bots
        const canMutate = !this.mpActive || c.isPlayer || (this.isMpHost && !c.isRemoteHuman);
        if (!canMutate) continue;

        let changed = false;
        if (f.itemId === 'shield_drop') {
          if (c.shield < GAME_CONSTANTS.MAX_SHIELD) {
            c.shield = Math.min(GAME_CONSTANTS.MAX_SHIELD, c.shield + f.ratePerSec * dt);
            changed = true;
          }
        } else {
          if (c.health < GAME_CONSTANTS.MAX_HEALTH) {
            c.health = Math.min(GAME_CONSTANTS.MAX_HEALTH, c.health + f.ratePerSec * dt);
            changed = true;
          }
          if (c.mana < GAME_CONSTANTS.MAX_MANA) {
            c.mana = Math.min(GAME_CONSTANTS.MAX_MANA, c.mana + 5.0 * dt);
            changed = true;
          }
        }

        if (changed && this.mpActive && shouldSyncVitals) {
          this.mpClient?.send({
            type: 'vitals_sync',
            combatantId: c.isPlayer ? undefined : c.id,
            health: Math.round(c.health),
            shield: Math.round(c.shield),
            mana: Math.round(c.mana),
          });
        }
      }
    }
  }

  // =========================================================================
  // UTILITIES, CONSUMABLE CHANNELING, HARD-LIGHT COVER & LOOT
  // =========================================================================

  private isHealOrShieldItem(itemId: UtilityItemId | undefined): boolean {
    return itemId === 'shield_cell' || itemId === 'shield_jug' || itemId === 'medkit';
  }

  private isHealOrShieldChannel(channel: ActiveChannel | null): boolean {
    return Boolean(
      channel && channel.kind === 'consumable' && this.isHealOrShieldItem(channel.itemId)
    );
  }

  private tryUseActiveItem(c: Combatant): void {
    if (!c.alive || c.skyDropping || c.channel) return;
    const slot = c.slots[c.activeSlot];
    if (!slot || slot.kind !== 'item' || (slot.count ?? 0) <= 0) return;

    const itemId = slot.id as UtilityItemId;
    const def = UTILITY_ITEMS[itemId];

    // Check Silence for channeled consumables
    if (def.channelTime > 0 && c.silencedSec > 0) {
      if (c.isPlayer) {
        this.audio.playSilenced();
        this.callbacks.onAnnouncement('ACCESS REVOKED', 'Consumables blocked while silenced!');
      }
      return;
    }

    // Don't waste full-stat heals
    if ((itemId === 'shield_cell' || itemId === 'shield_jug') && c.shield >= GAME_CONSTANTS.MAX_SHIELD) {
      if (c.isPlayer) this.callbacks.onAnnouncement('SHIELD FULL', 'Your Shield is already at 100');
      return;
    }
    if (itemId === 'medkit' && c.health >= GAME_CONSTANTS.MAX_HEALTH) {
      if (c.isPlayer) this.callbacks.onAnnouncement('HEALTH FULL', 'Your Health is already at 100');
      return;
    }
    if (itemId === 'mana_elixir' && c.mana >= GAME_CONSTANTS.MAX_MANA) {
      if (c.isPlayer) this.callbacks.onAnnouncement('MANA FULL', 'Your Mana is already at 100');
      return;
    }

    // Instant tactical utilities (Hard-Light Cover, Impulse Booster, Frag, Flashbang, Shield Drop, Regen Pod)
    if (def.channelTime <= 0) {
      if (def.manaCost && c.mana < def.manaCost) {
        if (c.isPlayer) {
          this.audio.playDryFire();
          this.callbacks.onAnnouncement('LOW MANA', `${def.name} requires ${def.manaCost} Mana`);
        }
        return;
      }
      if (def.manaCost) c.mana -= def.manaCost;

      if (itemId === 'hardlight_cover') {
        this.deployHardLightCover(c, slot.rarity);
        if (c.isPlayer) this.audio.playChannelStart(itemId);
      } else if (itemId === 'impulse_booster') {
        this.activateImpulseBooster(c, slot.rarity);
        if (c.isPlayer) this.audio.playChannelStart(itemId);
      } else if (
        itemId === 'frag_grenade' ||
        itemId === 'flashbang' ||
        itemId === 'shield_drop' ||
        itemId === 'regen_pod'
      ) {
        this.throwTacticalUtility(c, itemId, slot.rarity);
      }

      this.consumeSlotItem(c, c.activeSlot);
      return;
    }

    // Start timed consumable channel (1.4s - 3.0s)
    if (c.sliding) {
      this.endSlide(c, false);
    }
    this.cancelReload(c);
    c.sprinting = false;
    c.isAds = false;
    if (this.isHealOrShieldItem(itemId)) {
      c.crouching = true;
    }
    if (c.isPlayer && (this.keys.has('ShiftLeft') || this.keys.has('ShiftRight'))) {
      this.sprintLatchedOnChannel = true;
    }
    c.channel = {
      kind: 'consumable',
      label: `Using ${def.name}...`,
      slotIndex: c.activeSlot,
      itemId,
      rarity: slot.rarity,
      elapsed: 0,
      duration: def.channelTime,
    };
    if (c.isPlayer) {
      this.audio.playChannelStart(itemId);
    }
  }

  private cancelChannel(c: Combatant, notice?: string): void {
    if (!c.channel) return;
    c.channel = null;
    if (c.isPlayer) {
      this.sprintLatchedOnChannel = false;
    }
    if (notice && c.isPlayer) {
      this.callbacks.onAnnouncement('CHANNEL CANCELED', notice);
    }
  }

  private completeChannel(c: Combatant): void {
    const ch = c.channel;
    if (!ch) return;
    c.channel = null;
    if (c.isPlayer) {
      this.sprintLatchedOnChannel = false;
    }

    if (ch.kind === 'supply_drop' && ch.supplyDropId) {
      const sd = this.supplyDrops.find((d) => d.id === ch.supplyDropId);
      if (sd && sd.landed && !sd.opened) {
        this.openSupplyDrop(sd, c);
      }
      return;
    }

    if (ch.kind === 'chest' && ch.chestId) {
      const chest = this.lootChests.find((item) => item.id === ch.chestId);
      if (chest && !chest.opened) {
        this.openLootChest(chest, c);
      }
      return;
    }

    if (ch.kind === 'techstop' && ch.techStopId && ch.targetRarity && ch.manaCost !== undefined) {
      const slot = c.slots[ch.slotIndex];
      if (
        slot &&
        slot.kind === 'weapon' &&
        slot.rarity !== 'epic' &&
        c.mana >= ch.manaCost
      ) {
        const wDef = WEAPONS[slot.id as WeaponId];
        c.mana = Math.max(0, c.mana - ch.manaCost);
        slot.rarity = ch.targetRarity;
        slot.ammo = wDef.magSize;
        this.syncEquippedWeaponVisual(c);

        const ts = this.world?.techStops.find((t) => t.id === ch.techStopId);
        const fxPos = ts ? new THREE.Vector3(ts.x, ts.y, ts.z) : c.pos.clone();
        this.vfx.spawnTechStopUpgrade(fxPos, ch.targetRarity);
        this.audio.playTechStopUpgrade(ch.targetRarity);
        if (this.mpActive && c.isPlayer) {
          this.mpClient?.send({
            type: 'techstop_upgrade',
            techStopId: ch.techStopId,
            weaponId: slot.id as WeaponId,
            newRarity: ch.targetRarity,
            x: Number(fxPos.x.toFixed(2)),
            y: Number(fxPos.y.toFixed(2)),
            z: Number(fxPos.z.toFixed(2)),
          });
        }
        if (c.isPlayer) {
          this.callbacks.onAnnouncement(
            'TECHSTOP UPGRADE',
            `Upgraded to ${RARITY_CONFIG[ch.targetRarity].label} ${wDef.name}`
          );
        }
      }
      return;
    }

    if (ch.kind === 'consumable' && ch.itemId && ch.rarity) {
      const amount = getUtilityAmount(ch.itemId, ch.rarity);
      let color = 0x38bdf8;
      if (ch.itemId === 'shield_cell' || ch.itemId === 'shield_jug') {
        c.shield = Math.min(GAME_CONSTANTS.MAX_SHIELD, c.shield + amount);
        color = 0x38bdf8;
      } else if (ch.itemId === 'medkit') {
        c.health = Math.min(GAME_CONSTANTS.MAX_HEALTH, c.health + amount);
        color = 0x22c55e;
      } else if (ch.itemId === 'mana_elixir') {
        c.mana = Math.min(GAME_CONSTANTS.MAX_MANA, c.mana + amount);
        color = 0xa855f7;
      }

      this.consumeSlotItem(c, ch.slotIndex);
      this.vfx.spawnStatusBurst(c.pos, color);

      if (this.mpActive && (c.isPlayer || (this.isMpHost && !c.isRemoteHuman))) {
        this.mpClient?.send({
          type: 'vitals_sync',
          ...(c.isPlayer ? {} : { combatantId: c.id }),
          health: Math.round(c.health),
          shield: Math.round(c.shield),
          mana: Math.round(c.mana),
        });
      }

      if (c.isPlayer) {
        this.audio.playChannelComplete(ch.itemId);
        const scr = this.projectWorldToScreen(c.pos.clone().add(new THREE.Vector3(0, 1.8, 0)));
        if (scr) {
          this.callbacks.onFloatingDamage({ screenX: scr.x, screenY: scr.y, amount, kind: 'heal' });
        }
      }
    }
  }

  private consumeSlotItem(c: Combatant, slotIdx: number): void {
    const slot = c.slots[slotIdx];
    if (!slot || slot.kind !== 'item') return;
    slot.count = (slot.count ?? 1) - 1;
    if (slot.count <= 0) {
      c.slots[slotIdx] = null;
      // Auto-select first weapon slot if active item just ran out
      if (c.activeSlot === slotIdx) {
        const wIdx = c.slots.findIndex((s) => s?.kind === 'weapon');
        if (wIdx >= 0) {
          c.activeSlot = wIdx;
          this.syncEquippedWeaponVisual(c);
        }
      }
    }
  }

  private deployHardLightCover(c: Combatant, rarity: Rarity): void {
    const width = 4.0;
    const height = 2.25;
    const thickness = 0.42;
    const hp = getUtilityAmount('hardlight_cover', rarity);

    const dist = 3.2;
    const cx = THREE.MathUtils.clamp(
      c.pos.x - Math.sin(c.yaw) * dist,
      GAME_CONSTANTS.ARENA_MIN_X + 4,
      GAME_CONSTANTS.ARENA_MAX_X - 4
    );
    const cz = THREE.MathUtils.clamp(
      c.pos.z - Math.cos(c.yaw) * dist,
      GAME_CONSTANTS.ARENA_MIN_Z + 4,
      GAME_CONSTANTS.ARENA_MAX_Z - 4
    );
    const baseY = this.physics.getSupportHeight(cx, cz, c.pos.y + 1.0, 0.5, 0.8);

    const colliderId = `hlc_${this.nextBarrierSeq++}`;
    this.physics.addDestructibleCover(cx, baseY, cz, width, height, thickness, c.yaw, hp, c.id, colliderId);

    const mesh = this.vfx.createHardLightCoverMesh(width, height, RARITY_CONFIG[rarity].hex);
    mesh.position.set(cx, baseY, cz);
    mesh.rotation.y = c.yaw;
    this.scene.add(mesh);

    this.barriers.push({
      colliderId,
      ownerId: c.id,
      mesh,
      pos: new THREE.Vector3(cx, baseY + height * 0.5, cz),
      hp,
      maxHp: hp,
      flashTimer: 0,
    });
    this.vfx.spawnExpandingRing(new THREE.Vector3(cx, baseY, cz), 2.8, RARITY_CONFIG[rarity].hex, 0.35);
  }

  private throwTacticalUtility(
    c: Combatant,
    itemId: 'frag_grenade' | 'flashbang' | 'shield_drop' | 'regen_pod',
    rarity: Rarity
  ): void {
    const sinY = Math.sin(c.yaw);
    const cosY = Math.cos(c.yaw);
    const cosP = Math.cos(c.pitch);
    const sinP = Math.sin(c.pitch);
    const fwdX = -sinY * cosP;
    const fwdY = sinP;
    const fwdZ = -cosY * cosP;

    const shouldBroadcast =
      this.mpActive && (c.isPlayer || (this.isMpHost && !c.isRemoteHuman));

    if (itemId === 'frag_grenade' || itemId === 'flashbang') {
      const eyeY = c.crouching ? 1.05 : 1.48;
      const origin = new THREE.Vector3(
        c.pos.x + fwdX * 0.52,
        c.pos.y + eyeY,
        c.pos.z + fwdZ * 0.52
      );
      const launchSpeed = itemId === 'frag_grenade' ? 22 : 24;
      const upBoost = itemId === 'frag_grenade' ? 5.5 : 5.0;
      const vel = new THREE.Vector3(
        fwdX * launchSpeed,
        fwdY * launchSpeed + upBoost,
        fwdZ * launchSpeed
      );
      if (c.isPlayer) {
        this.audio.playGrenadeThrow();
      }
      this.spawnThrownUtility(c.id, itemId, rarity, origin, vel, false);

      if (shouldBroadcast) {
        this.mpClient?.send({
          type: 'utility_throw',
          event: {
            ownerId: c.id,
            itemId,
            rarity,
            x: Number(origin.x.toFixed(2)),
            y: Number(origin.y.toFixed(2)),
            z: Number(origin.z.toFixed(2)),
            vx: Number(vel.x.toFixed(2)),
            vy: Number(vel.y.toFixed(2)),
            vz: Number(vel.z.toFixed(2)),
          },
        });
      }
      return;
    }

    // Deployable ground fields: shield_drop (3.2m forward) & regen_pod (1.6m forward)
    const deployDist = itemId === 'shield_drop' ? 3.2 : 1.6;
    const startOrigin = new THREE.Vector3(c.pos.x, c.pos.y + 1.15, c.pos.z);
    const horizDir = new THREE.Vector3(-sinY, 0, -cosY).normalize();
    const wallHit = this.physics.raycastWorld(startOrigin, horizDir, deployDist);
    const actualDist = wallHit ? Math.max(0.6, wallHit.distance - 0.5) : deployDist;

    const dx = THREE.MathUtils.clamp(
      c.pos.x - sinY * actualDist,
      GAME_CONSTANTS.ARENA_MIN_X + 4,
      GAME_CONSTANTS.ARENA_MAX_X - 4
    );
    const dz = THREE.MathUtils.clamp(
      c.pos.z - cosY * actualDist,
      GAME_CONSTANTS.ARENA_MIN_Z + 4,
      GAME_CONSTANTS.ARENA_MAX_Z - 4
    );
    const baseY = this.physics.getSupportHeight(dx, dz, c.pos.y + 1.2, 0.45, 0.9);
    const deployPos = new THREE.Vector3(dx, baseY, dz);

    this.deployTacticalField(c.id, itemId, rarity, deployPos);

    if (shouldBroadcast) {
      this.mpClient?.send({
        type: 'utility_throw',
        event: {
          ownerId: c.id,
          itemId,
          rarity,
          x: Number(deployPos.x.toFixed(2)),
          y: Number(deployPos.y.toFixed(2)),
          z: Number(deployPos.z.toFixed(2)),
          vx: 0,
          vy: 0,
          vz: 0,
        },
      });
    }
  }

  private spawnThrownUtility(
    ownerId: string,
    itemId: 'frag_grenade' | 'flashbang',
    rarity: Rarity,
    origin: THREE.Vector3,
    vel: THREE.Vector3,
    visualOnly: boolean
  ): void {
    const mesh = this.assetManager.instantiateUtility(itemId);
    mesh.scale.setScalar(1.35);
    mesh.position.copy(origin);

    let fuseGlow: THREE.Mesh | null = null;
    if (itemId === 'frag_grenade') {
      fuseGlow = new THREE.Mesh(
        new THREE.SphereGeometry(0.11, 10, 8),
        new THREE.MeshBasicMaterial({
          color: 0xff3b30,
          transparent: true,
          opacity: 0.9,
          blending: THREE.AdditiveBlending,
          depthWrite: false,
        })
      );
      fuseGlow.position.set(0, 0.24, 0);
      mesh.add(fuseGlow);
    }
    this.scene.add(mesh);

    const maxFuse = itemId === 'frag_grenade' ? 1.8 : 1.25;
    this.thrownUtilities.push({
      id: `util_${this.nextUtilitySeq++}`,
      ownerId,
      itemId,
      rarity,
      pos: origin.clone(),
      vel: vel.clone(),
      fuseRemaining: maxFuse,
      maxFuse,
      mesh,
      fuseGlow,
      visualOnly,
      bounceCount: 0,
    });
  }

  private deployTacticalField(
    ownerId: string,
    itemId: 'shield_drop' | 'regen_pod',
    rarity: Rarity,
    pos: THREE.Vector3
  ): void {
    const owner = this.combatants.find((c) => c.id === ownerId) ?? null;
    const radius = itemId === 'shield_drop' ? 4.6 : 5.2;
    const duration = 10.0;
    const ratePerSec = getUtilityAmount(itemId, rarity);

    let teamColor = 0x38bdf8;
    if (itemId === 'shield_drop' && owner?.teamId) {
      teamColor = TEAM_CONFIG[owner.teamId].hex;
    }

    const visual =
      itemId === 'shield_drop'
        ? this.vfx.createShieldDropDome(pos, radius, teamColor)
        : this.vfx.createRegenPodAura(pos, radius);

    const propMesh = this.assetManager.instantiateUtility(itemId);
    propMesh.scale.setScalar(1.35);
    propMesh.position.copy(pos);
    this.scene.add(propMesh);

    const distToCam = pos.distanceTo(this.getCameraFocusPos());
    const pan = this.computeSpatialPan(pos);
    if (itemId === 'shield_drop') {
      this.audio.playShieldDropDeploy(distToCam, pan);
    } else {
      this.audio.playRegenPodDeploy(distToCam, pan);
    }

    this.deployableFields.push({
      id: `field_${this.nextUtilitySeq++}`,
      ownerId,
      itemId,
      rarity,
      center: pos.clone(),
      radius,
      ratePerSec,
      elapsed: 0,
      duration,
      visual,
      propMesh,
      vitalsSyncAccum: 0,
    });
  }

  private updateThrownUtilities(dt: number): void {
    const gravity = 22.0;

    for (let i = this.thrownUtilities.length - 1; i >= 0; i--) {
      const u = this.thrownUtilities[i];
      u.fuseRemaining -= dt;

      // Integrate ballistic arc + bounce off walls & terrain
      u.vel.y -= gravity * dt;
      const nextPos = this.tmpVecA.copy(u.pos).addScaledVector(u.vel, dt);
      const segVec = this.tmpVecB.subVectors(nextPos, u.pos);
      const segLen = segVec.length();
      const restitution = u.itemId === 'frag_grenade' ? 0.42 : 0.45;

      let bounced = false;
      let bounceSpeed = 0;

      if (segLen > 0.0005) {
        const segDir = this.tmpVecC.copy(segVec).divideScalar(segLen);
        const hit = this.physics.raycastWorld(u.pos, segDir, segLen + 0.14);
        if (hit) {
          bounceSpeed = u.vel.length();
          u.pos.copy(hit.point).addScaledVector(hit.normal, 0.14);
          const vn = u.vel.dot(hit.normal);
          if (vn < 0) {
            u.vel.addScaledVector(hit.normal, -(1 + restitution) * vn);
          }
          if (hit.normal.y > 0.5) {
            u.vel.x *= 0.78;
            u.vel.z *= 0.78;
            if (Math.abs(u.vel.y) < 1.1) u.vel.y = 0;
          } else {
            u.vel.multiplyScalar(0.84);
          }
          bounced = true;
        } else {
          u.pos.copy(nextPos);
        }
      }

      // Clamp cleanly above terrain floor
      const floorY = this.physics.getTerrainHeight(u.pos.x, u.pos.z) + 0.14;
      if (u.pos.y < floorY) {
        bounceSpeed = Math.max(bounceSpeed, Math.abs(u.vel.y));
        u.pos.y = floorY;
        if (u.vel.y < -1.1) {
          u.vel.y = Math.abs(u.vel.y) * restitution;
          bounced = true;
        } else {
          u.vel.y = 0;
        }
        u.vel.x *= 0.78;
        u.vel.z *= 0.78;
      }

      if (bounced && bounceSpeed > 1.8 && u.bounceCount < 5) {
        u.bounceCount += 1;
        const dist = u.pos.distanceTo(this.getCameraFocusPos());
        this.audio.playGrenadeBounce(dist, this.computeSpatialPan(u.pos));
      }

      // Spin mesh proportional to velocity + blink red fuse glow on Frag Grenade
      u.mesh.position.copy(u.pos);
      const speed = u.vel.length();
      if (speed > 0.4) {
        u.mesh.rotation.x += dt * Math.min(14, speed * 0.75);
        u.mesh.rotation.z += dt * Math.min(10, speed * 0.5);
      }
      if (u.fuseGlow) {
        const blinkFreq = u.fuseRemaining < 0.55 ? 24 : 11;
        const blinkOn = Math.sin(this.matchElapsed * blinkFreq) > 0;
        u.fuseGlow.visible = blinkOn;
        u.fuseGlow.scale.setScalar(u.fuseRemaining < 0.55 ? 1.45 : 1.0);
      }

      if (u.fuseRemaining <= 0) {
        this.scene.remove(u.mesh);
        this.thrownUtilities.splice(i, 1);
        if (u.itemId === 'frag_grenade') {
          this.detonateFragGrenade(u);
        } else {
          this.detonateFlashbang(u);
        }
      }
    }
  }

  private detonateFragGrenade(u: ThrownUtilityEntity): void {
    const blastRadius = 7.5;
    this.vfx.spawnExplosion(u.pos, blastRadius, 0xea4335);

    const listenerPos = this.getCameraFocusPos();
    const distToCam = u.pos.distanceTo(listenerPos);
    this.audio.playExplosion(distToCam, this.computeSpatialPan(u.pos));

    const attacker = this.combatants.find((c) => c.id === u.ownerId) ?? null;
    if (u.ownerId !== this.player?.id && !this.isFriendly(this.player, attacker)) {
      this.pushSoundEvent('gunfire', u.pos.x, u.pos.z, 110, 0.9, 1.1);
    }
    if (this.player && this.player.alive && distToCam < 24) {
      this.camController.addShake(Math.max(0.06, (1 - distToCam / 24) * 0.34));
    }

    if (u.visualOnly) return;

    const maxDamage = getUtilityAmount('frag_grenade', u.rarity);
    for (const target of this.combatants) {
      if (!target.alive || target.rewind.active) continue;
      if (target.id !== u.ownerId && this.isFriendly(attacker, target)) continue;
      const bodyCenter = this.tmpVecA.set(target.pos.x, target.pos.y + 0.95, target.pos.z);
      const dist = bodyCenter.distanceTo(u.pos);
      if (dist <= blastRadius) {
        const falloff = 1 - (dist / blastRadius) * 0.55;
        const mult = target.id === u.ownerId ? 0.45 : 1.0;
        const dmg = Math.max(10, Math.round(maxDamage * falloff * mult));
        this.applyCombatDamage(target, attacker, dmg, {
          headshot: false,
          weaponName: 'Frag Grenade',
          isUltimate: false,
          hitPoint: bodyCenter.clone(),
        });
      }
    }
  }

  private detonateFlashbang(u: ThrownUtilityEntity): void {
    const flashRadius = 13.0;
    this.vfx.spawnFlashbangBurst(u.pos);

    const attacker = this.combatants.find((c) => c.id === u.ownerId) ?? null;
    const baseDuration = getUtilityAmount('flashbang', u.rarity);
    let playerBlinded = false;

    for (const target of this.combatants) {
      if (!target.alive || target.rewind.active) continue;
      if (target.id !== u.ownerId && this.isFriendly(attacker, target)) continue;

      const eyePos = this.tmpVecA.set(
        target.pos.x,
        target.pos.y + (target.crouching ? 1.0 : 1.48),
        target.pos.z
      );
      const toFlash = this.tmpVecB.subVectors(u.pos, eyePos);
      const dist = toFlash.length();
      if (dist > flashRadius) continue;

      toFlash.divideScalar(Math.max(dist, 0.001));
      const cosP = Math.cos(target.pitch);
      const lookDir = this.tmpVecC
        .set(-Math.sin(target.yaw) * cosP, Math.sin(target.pitch), -Math.cos(target.yaw) * cosP)
        .normalize();

      const facing01 = THREE.MathUtils.clamp((lookDir.dot(toFlash) + 1) * 0.5, 0, 1);
      const lookFactor = 0.35 + 0.65 * Math.pow(facing01, 0.85);
      const distFactor = Math.max(0.22, 1 - (dist / flashRadius) * 0.72);
      const selfMult = target.id === u.ownerId ? 0.5 : 1.0;
      const factor = distFactor * lookFactor * selfMult;
      const blindDur = baseDuration * factor;

      target.blindedSec = Math.max(target.blindedSec, blindDur);
      target.flashBlindPeak = Math.max(target.flashBlindPeak, Math.min(1.0, factor * 1.15));

      if (target.isPlayer) {
        playerBlinded = true;
        this.audio.playFlashbang(Math.min(1, factor), dist, this.computeSpatialPan(u.pos));
        this.camController.addShake(Math.max(0.05, factor * 0.18));
        this.emitHudSnapshot();
      }
    }

    if (!playerBlinded) {
      const distToCam = u.pos.distanceTo(this.getCameraFocusPos());
      if (distToCam < 60) {
        this.audio.playFlashbang(0, distToCam, this.computeSpatialPan(u.pos));
      }
    }
  }

  private handleMpUtilityThrow(event: UtilityThrowEvent): void {
    const pos = new THREE.Vector3(event.x, event.y, event.z);
    if (event.itemId === 'frag_grenade' || event.itemId === 'flashbang') {
      const vel = new THREE.Vector3(event.vx, event.vy, event.vz);
      this.spawnThrownUtility(event.ownerId, event.itemId, event.rarity, pos, vel, true);
    } else if (event.itemId === 'shield_drop' || event.itemId === 'regen_pod') {
      this.deployTacticalField(event.ownerId, event.itemId, event.rarity, pos);
    }
  }

  private damageHardLightBarrier(colliderId: string, damage: number, hitPos: THREE.Vector3): void {
    const res = this.physics.damageCollider(colliderId, damage);
    const idx = this.barriers.findIndex((b) => b.colliderId === colliderId);
    if (idx < 0) return;

    const barrier = this.barriers[idx];
    barrier.hp = res.remainingHp;
    barrier.flashTimer = 0.12;
    this.vfx.spawnHitImpact(hitPos, { isShield: true });

    if (res.destroyed) {
      this.scene.remove(barrier.mesh);
      this.barriers.splice(idx, 1);
      this.vfx.spawnExplosion(barrier.pos, 3.0, 0x38bdf8);
      const dist = this.player ? barrier.pos.distanceTo(this.player.pos) : 0;
      this.audio.playShieldCrack(dist, false, this.computeSpatialPan(barrier.pos));
    }
  }

  private updateBarriers(dt: number): void {
    for (const b of this.barriers) {
      if (b.flashTimer > 0) {
        b.flashTimer = Math.max(0, b.flashTimer - dt);
        const panel = b.mesh.getObjectByName('HardLightWallPanel') as THREE.Mesh | undefined;
        if (panel && panel.material instanceof THREE.MeshPhysicalMaterial) {
          panel.material.emissiveIntensity = b.flashTimer > 0 ? 1.8 : 0.45;
        }
      }
    }
  }

  private activateImpulseBooster(c: Combatant, rarity: Rarity): void {
    if (c.sliding) {
      this.endSlide(c, false);
    }
    const power = getUtilityAmount('impulse_booster', rarity); // 22 / 26 / 30
    const fx = -Math.sin(c.yaw);
    const fz = -Math.cos(c.yaw);
    c.vel.x = fx * (power * 0.72);
    c.vel.z = fz * (power * 0.72);
    c.vel.y = power * 0.68;
    c.grounded = false;
    c.crouching = false;
    c.airborneTime = 0.12;
    c.peakFallSpeed = 0;
    c.takeoffTimer = 0.16;
    c.squashTimer = 0;
    this.vfx.spawnImpulseBurst(c.pos);
  }

  private startChestChannel(c: Combatant, chest: LootChestEntity): boolean {
    if (!c.alive || c.skyDropping || c.channel || chest.opened) return false;
    if (c.silencedSec > 0) {
      if (c.isPlayer) {
        this.audio.playSilenced();
        this.callbacks.onAnnouncement('ACCESS REVOKED', 'Chest opening blocked while silenced!');
      }
      return false;
    }
    if (c.sliding) {
      this.endSlide(c, false);
    }
    this.cancelReload(c);
    c.sprinting = false;
    c.isAds = false;
    c.channel = {
      kind: 'chest',
      label: `Opening Tier ${chest.tier} Chest...`,
      slotIndex: c.activeSlot,
      chestId: chest.id,
      chestTier: chest.tier,
      elapsed: 0,
      duration: GAME_CONSTANTS.CHEST_OPEN_CHANNEL_TIME,
    };
    const dist = this.player ? Math.hypot(chest.x - this.player.pos.x, chest.z - this.player.pos.z) : 0;
    this.audio.playChestOpenStart(
      c.isPlayer ? 0 : dist,
      c.isPlayer ? 0 : this.computeSpatialPan(this.tmpVecA.set(chest.x, chest.y, chest.z))
    );
    return true;
  }

  private findNearestUnopenedChest(
    c: Combatant,
    maxDist: number = GAME_CONSTANTS.CHEST_INTERACT_RADIUS
  ): LootChestEntity | null {
    let best: LootChestEntity | null = null;
    let bestDist = maxDist;
    for (const ch of this.lootChests) {
      if (ch.opened) continue;
      const d = Math.hypot(ch.x - c.pos.x, ch.z - c.pos.z);
      if (d <= bestDist && Math.abs(ch.y - c.pos.y) <= 2.4) {
        bestDist = d;
        best = ch;
      }
    }
    return best;
  }

  private getChestPromptText(tier: ChestTier): string {
    if (tier === 3) return '[E] Open Tier 3 Epic Vault Chest';
    if (tier === 2) return '[E] Open Tier 2 Rare Chest';
    return '[E] Open Tier 1 Chest';
  }

  private findNearestTechStop(
    c: Combatant,
    maxDist: number = GAME_CONSTANTS.TECHSTOP_INTERACT_RADIUS
  ): TechStopPlacement | null {
    if (!this.world) return null;
    let best: TechStopPlacement | null = null;
    let bestDist = maxDist;
    for (const ts of this.world.techStops) {
      const d = Math.hypot(ts.x - c.pos.x, ts.z - c.pos.z);
      if (d <= bestDist && Math.abs(ts.y - c.pos.y) <= 2.5) {
        bestDist = d;
        best = ts;
      }
    }
    return best;
  }

  private getTechStopPromptAndSpec(p: Combatant): {
    prompt: string;
    canUpgrade: boolean;
    weaponName?: string;
    targetRarity?: Rarity;
    manaCost?: number;
    duration?: number;
    reason?: 'unarmed' | 'max_tier' | 'low_mana';
  } {
    const slot = p.slots[p.activeSlot];
    if (!slot || slot.kind !== 'weapon') {
      return {
        prompt: 'TechStop: Equip a Common or Rare weapon',
        canUpgrade: false,
        reason: 'unarmed',
      };
    }
    const wDef = WEAPONS[slot.id as WeaponId];
    if (slot.rarity === 'common') {
      const cost = GAME_CONSTANTS.TECHSTOP_RARE_MANA_COST;
      const enough = p.mana >= cost;
      return {
        prompt: enough
          ? `[E] TechStop Upgrade: ${wDef.name} → Rare (${cost} MP)`
          : `[E] TechStop Upgrade → Rare (Need ${cost} MP)`,
        canUpgrade: enough,
        weaponName: wDef.name,
        targetRarity: 'rare',
        manaCost: cost,
        duration: GAME_CONSTANTS.TECHSTOP_RARE_CHANNEL_TIME,
        reason: enough ? undefined : 'low_mana',
      };
    }
    if (slot.rarity === 'rare') {
      const cost = GAME_CONSTANTS.TECHSTOP_EPIC_MANA_COST;
      const enough = p.mana >= cost;
      return {
        prompt: enough
          ? `[E] TechStop Upgrade: ${wDef.name} → Epic (${cost} MP)`
          : `[E] TechStop Upgrade → Epic (Need ${cost} MP)`,
        canUpgrade: enough,
        weaponName: wDef.name,
        targetRarity: 'epic',
        manaCost: cost,
        duration: GAME_CONSTANTS.TECHSTOP_EPIC_CHANNEL_TIME,
        reason: enough ? undefined : 'low_mana',
      };
    }
    return {
      prompt: `TechStop: ${wDef.name} is Max Tier (Epic)`,
      canUpgrade: false,
      weaponName: wDef.name,
      reason: 'max_tier',
    };
  }

  private resolveNearestInteractable(p: Combatant):
    | { kind: 'supply_drop'; supplyDrop: SupplyDropEntity; prompt: string }
    | { kind: 'chest'; chest: LootChestEntity; prompt: string }
    | { kind: 'loot'; loot: GroundLoot; prompt: string }
    | { kind: 'techstop'; techStop: TechStopPlacement; prompt: string }
    | { kind: 'gbike'; bike: WorldGBike; prompt: string }
    | null {
    // 1. Landed unopened Supply Drop takes top priority
    const sd = this.supplyDrops.find(
      (d) =>
        d.landed &&
        !d.opened &&
        Math.hypot(d.x - p.pos.x, d.z - p.pos.z) <= 3.8 &&
        Math.abs(d.y - p.pos.y) <= 2.5
    );
    if (sd) {
      return { kind: 'supply_drop', supplyDrop: sd, prompt: '[E] Open Epic Supply Drop (1.5s)' };
    }

    const formatLootPrompt = (loot: GroundLoot): string => {
      const rLabel = RARITY_CONFIG[loot.rarity].label;
      const itemName =
        loot.kind === 'weapon'
          ? WEAPONS[loot.itemId as WeaponId].name
          : UTILITY_ITEMS[loot.itemId as UtilityItemId].name;
      return `[E] Pick up ${rLabel} ${itemName}`;
    };

    const nearChest = this.findNearestUnopenedChest(p, GAME_CONSTANTS.CHEST_INTERACT_RADIUS);
    const nearLoot = this.findNearestLoot(p, 3.4);
    const nearTechStop = this.findNearestTechStop(p, GAME_CONSTANTS.TECHSTOP_INTERACT_RADIUS);
    const nearBike = this.findNearestUnoccupiedGBike(p, GAME_CONSTANTS.GBIKE_MOUNT_RADIUS);

    type Candidate = {
      score: number;
      result:
        | { kind: 'chest'; chest: LootChestEntity; prompt: string }
        | { kind: 'loot'; loot: GroundLoot; prompt: string }
        | { kind: 'techstop'; techStop: TechStopPlacement; prompt: string }
        | { kind: 'gbike'; bike: WorldGBike; prompt: string };
    };
    const candidates: Candidate[] = [];
    if (nearChest) {
      candidates.push({
        score: Math.hypot(nearChest.x - p.pos.x, nearChest.z - p.pos.z),
        result: { kind: 'chest', chest: nearChest, prompt: this.getChestPromptText(nearChest.tier) },
      });
    }
    if (nearLoot) {
      // Slight tie-break preference for dropped ground loot right underfoot vs. nearby chest
      candidates.push({
        score: Math.hypot(nearLoot.x - p.pos.x, nearLoot.z - p.pos.z) - 0.35,
        result: { kind: 'loot', loot: nearLoot, prompt: formatLootPrompt(nearLoot) },
      });
    }
    if (nearTechStop) {
      candidates.push({
        score: Math.hypot(nearTechStop.x - p.pos.x, nearTechStop.z - p.pos.z),
        result: {
          kind: 'techstop',
          techStop: nearTechStop,
          prompt: this.getTechStopPromptAndSpec(p).prompt,
        },
      });
    }
    if (nearBike) {
      // Slightly lower priority than Chest/TechStop/Loot when standing right on top of one
      candidates.push({
        score: Math.hypot(nearBike.x - p.pos.x, nearBike.z - p.pos.z) + 0.45,
        result: { kind: 'gbike', bike: nearBike, prompt: '[E] Ride GBike' },
      });
    }

    if (candidates.length === 0) return null;
    candidates.sort((a, b) => a.score - b.score);
    return candidates[0].result;
  }

  private tryStartTechStopUpgrade(p: Combatant, ts: TechStopPlacement): void {
    if (p.silencedSec > 0) {
      this.audio.playSilenced();
      this.callbacks.onAnnouncement('ACCESS REVOKED', 'TechStop upgrade blocked while silenced!');
      return;
    }

    const spec = this.getTechStopPromptAndSpec(p);
    if (!spec.canUpgrade || !spec.targetRarity || spec.manaCost === undefined || !spec.duration) {
      this.audio.playDryFire();
      if (spec.reason === 'low_mana' && spec.manaCost !== undefined) {
        this.callbacks.onAnnouncement('LOW MANA', `TechStop upgrade requires ${spec.manaCost} Mana`);
      } else if (spec.reason === 'max_tier' && spec.weaponName) {
        this.callbacks.onAnnouncement('TECHSTOP', `${spec.weaponName} is already Max Tier (Epic)`);
      } else {
        this.callbacks.onAnnouncement('TECHSTOP', 'Equip a Common or Rare weapon to upgrade');
      }
      return;
    }

    if (p.sliding) {
      this.endSlide(p, false);
    }
    this.cancelReload(p);
    p.sprinting = false;
    p.isAds = false;
    if (this.keys.has('ShiftLeft') || this.keys.has('ShiftRight')) {
      this.sprintLatchedOnChannel = true;
    }
    p.channel = {
      kind: 'techstop',
      label: `Upgrading ${spec.weaponName}...`,
      slotIndex: p.activeSlot,
      techStopId: ts.id,
      targetRarity: spec.targetRarity,
      manaCost: spec.manaCost,
      elapsed: 0,
      duration: spec.duration,
    };
  }

  private tryPlayerInteract(): void {
    const p = this.player;
    if (!p || !p.alive || p.skyDropping) return;

    // Dismount GBike immediately on [E] (triggers Bail-Out Slide if moving >= 8.5 m/s!)
    if (p.ridingGBikeId !== null) {
      this.dismountGBike(p, true);
      return;
    }

    if (p.channel) return;

    const target = this.resolveNearestInteractable(p);
    if (!target) return;

    if (target.kind === 'supply_drop') {
      const sd = target.supplyDrop;
      if (p.silencedSec > 0) {
        this.audio.playSilenced();
        return;
      }
      if (p.sliding) {
        this.endSlide(p, false);
      }
      this.cancelReload(p);
      p.sprinting = false;
      p.isAds = false;
      p.channel = {
        kind: 'supply_drop',
        label: 'Opening Supply Drop...',
        slotIndex: p.activeSlot,
        supplyDropId: sd.id,
        elapsed: 0,
        duration: GAME_CONSTANTS.SUPPLY_DROP_CHANNEL_TIME,
      };
      return;
    }

    if (target.kind === 'chest') {
      this.startChestChannel(p, target.chest);
      return;
    }

    if (target.kind === 'loot') {
      this.pickupLoot(p, target.loot);
      return;
    }

    if (target.kind === 'techstop') {
      this.tryStartTechStopUpgrade(p, target.techStop);
      return;
    }

    if (target.kind === 'gbike') {
      if (this.mpActive) {
        if (target.bike.riderId !== null) {
          this.callbacks.onAnnouncement('GBIKE TAKEN', 'Another player is already riding this GBike');
          return;
        }
        const nowMs = performance.now();
        if (this.mpPendingBikeClaimId === target.bike.id && nowMs - this.mpPendingBikeClaimAt < 1200) {
          return;
        }
        this.mpPendingBikeClaimId = target.bike.id;
        this.mpPendingBikeClaimAt = nowMs;
        this.mpClient?.send({
          type: 'bike_claim',
          bikeId: target.bike.id,
        });
        return;
      }
      this.mountGBike(p, target.bike);
    }
  }

  private findNearestLoot(c: Combatant, maxDist: number): GroundLoot | null {
    let best: GroundLoot | null = null;
    let bestDist = maxDist;
    for (const l of this.lootDrops) {
      const d = Math.hypot(l.x - c.pos.x, l.z - c.pos.z);
      if (d < bestDist && Math.abs(l.y - c.pos.y) < 2.6) {
        bestDist = d;
        best = l;
      }
    }
    return best;
  }

  private canBotTakeLoot(c: Combatant, loot: GroundLoot): boolean {
    if (
      loot.droppedById === c.id &&
      loot.droppedAt !== undefined &&
      this.matchElapsed - loot.droppedAt < BOT_DROP_IGNORE_SEC
    ) {
      return false;
    }

    const rarityRank: Record<Rarity, number> = { common: 1, rare: 2, epic: 3 };

    if (loot.kind === 'item') {
      const uDef = UTILITY_ITEMS[loot.itemId as UtilityItemId];
      for (const s of c.slots) {
        if (
          s &&
          s.kind === 'item' &&
          s.id === loot.itemId &&
          ((s.count ?? 0) < uDef.maxStack || rarityRank[loot.rarity] > rarityRank[s.rarity])
        ) {
          return true;
        }
      }
    } else {
      for (const s of c.slots) {
        if (s && s.kind === 'weapon' && s.id === loot.itemId && rarityRank[loot.rarity] > rarityRank[s.rarity]) {
          return true;
        }
      }
    }

    if (c.slots.some((s) => s === null)) {
      return true;
    }

    // Full inventory: strict monotonic upgrade only
    if (loot.kind === 'weapon') {
      let weaponCount = 0;
      let lowestWeaponRank = 99;
      let hasUtilitySlot = false;
      for (const s of c.slots) {
        if (!s) continue;
        if (s.kind === 'weapon') {
          weaponCount++;
          lowestWeaponRank = Math.min(lowestWeaponRank, rarityRank[s.rarity]);
        } else {
          hasUtilitySlot = true;
        }
      }
      if (weaponCount === 0) return hasUtilitySlot;
      return lowestWeaponRank < rarityRank[loot.rarity];
    }

    // Full inventory utility item: never replace a weapon, never duplicate a full stack, require strict hysteresis upgrade
    if (c.slots.some((s) => s !== null && s.kind === 'item' && s.id === loot.itemId)) {
      return false;
    }
    let worstVal = Infinity;
    for (const s of c.slots) {
      if (s && s.kind === 'item') {
        worstVal = Math.min(worstVal, getBotUtilityValue(s.id as UtilityItemId, s.rarity));
      }
    }
    if (worstVal === Infinity) return false;
    const newVal = getBotUtilityValue(loot.itemId as UtilityItemId, loot.rarity);
    return newVal >= worstVal + BOT_UTILITY_SWAP_HYSTERESIS;
  }

  private pickupLoot(c: Combatant, loot: GroundLoot): void {
    const idx = this.lootDrops.indexOf(loot);
    if (idx < 0) return;

    // For bots, verify the item can actually be placed/upgraded/swapped cleanly before claiming
    if (!c.isPlayer && !this.canBotTakeLoot(c, loot)) {
      return;
    }

    if (this.mpActive) {
      if (!c.isPlayer && !(this.isMpHost && !c.isRemoteHuman)) return;
      const nowMs = performance.now();
      const pendingAt = this.mpPendingLootClaims.get(loot.id);
      if (pendingAt && nowMs - pendingAt < 1500) return;
      this.mpPendingLootClaims.set(loot.id, nowMs);
      this.mpClient?.send({
        type: 'loot_claim',
        lootId: loot.id,
        ...(c.isPlayer ? {} : { claimerId: c.id }),
      });
      return;
    }

    this.applyClaimedLootToCombatant(c, loot);
  }

  private applyClaimedLootToCombatant(c: Combatant, loot: GroundLoot): void {
    const idx = this.lootDrops.indexOf(loot);
    if (idx < 0) return;

    // Track unarmed / empty-slot state BEFORE pickup for seamless Auto-Equip convenience
    const hadAnyWeapon = c.slots.some((s) => s !== null && s.kind === 'weapon');
    const activeWasEmpty = c.slots[c.activeSlot] === null;

    const rarityRank: Record<Rarity, number> = { common: 1, rare: 2, epic: 3 };
    let placed = false;
    let placedSlotIdx = -1;

    if (loot.kind === 'item') {
      const uDef = UTILITY_ITEMS[loot.itemId as UtilityItemId];
      // Try stacking into existing matching item slot (or upgrading its rarity in place) first
      for (let i = 0; i < c.slots.length; i++) {
        const s = c.slots[i];
        if (
          s &&
          s.kind === 'item' &&
          s.id === loot.itemId &&
          ((s.count ?? 0) < uDef.maxStack || rarityRank[loot.rarity] > rarityRank[s.rarity])
        ) {
          s.count = Math.min(uDef.maxStack, (s.count ?? 0) + loot.count);
          if (rarityRank[loot.rarity] > rarityRank[s.rarity]) {
            s.rarity = loot.rarity;
          }
          placed = true;
          placedSlotIdx = i;
          break;
        }
      }
    } else {
      // If carrying same weapon at lower rarity, directly upgrade it in place
      for (let i = 0; i < c.slots.length; i++) {
        const s = c.slots[i];
        if (s && s.kind === 'weapon' && s.id === loot.itemId && rarityRank[loot.rarity] > rarityRank[s.rarity]) {
          s.rarity = loot.rarity;
          s.ammo = WEAPONS[loot.itemId as WeaponId].magSize;
          placed = true;
          placedSlotIdx = i;
          break;
        }
      }
    }

    // Try placing into first empty slot
    if (!placed) {
      const emptyIdx = c.slots.findIndex((s) => s === null);
      if (emptyIdx >= 0) {
        c.slots[emptyIdx] =
          loot.kind === 'weapon'
            ? {
                kind: 'weapon',
                id: loot.itemId,
                rarity: loot.rarity,
                ammo: WEAPONS[loot.itemId as WeaponId].magSize,
              }
            : {
                kind: 'item',
                id: loot.itemId,
                rarity: loot.rarity,
                count: loot.count,
              };
        placed = true;
        placedSlotIdx = emptyIdx;
      }
    }

    // Otherwise swap with active slot (for human player) or strictly worse matching slot (for bots)
    if (!placed) {
      let replaceIdx = c.activeSlot;
      if (!c.isPlayer) {
        if (loot.kind === 'weapon') {
          let lowestScore = 99;
          let lowestWeaponIdx = -1;
          let weaponCount = 0;
          let worstUtilVal = Infinity;
          let worstUtilIdx = -1;
          for (let i = 0; i < c.slots.length; i++) {
            const s = c.slots[i];
            if (!s) continue;
            if (s.kind === 'weapon') {
              weaponCount++;
              if (rarityRank[s.rarity] < lowestScore) {
                lowestScore = rarityRank[s.rarity];
                lowestWeaponIdx = i;
              }
            } else {
              const uVal = getBotUtilityValue(s.id as UtilityItemId, s.rarity);
              if (uVal < worstUtilVal) {
                worstUtilVal = uVal;
                worstUtilIdx = i;
              }
            }
          }
          if (weaponCount > 0) {
            if (lowestWeaponIdx < 0 || lowestScore >= rarityRank[loot.rarity]) {
              // No strictly worse weapon to replace: abort cleanly and leave loot untouched
              return;
            }
            replaceIdx = lowestWeaponIdx;
          } else if (worstUtilIdx >= 0) {
            replaceIdx = worstUtilIdx;
          } else {
            return;
          }
        } else {
          // Bot utility swap: NEVER replace a weapon slot, never duplicate a full stack, require strict hysteresis upgrade
          if (c.slots.some((s) => s !== null && s.kind === 'item' && s.id === loot.itemId)) {
            return;
          }
          let worstUtilVal = Infinity;
          let worstUtilIdx = -1;
          for (let i = 0; i < c.slots.length; i++) {
            const s = c.slots[i];
            if (s && s.kind === 'item') {
              const uVal = getBotUtilityValue(s.id as UtilityItemId, s.rarity);
              if (uVal < worstUtilVal) {
                worstUtilVal = uVal;
                worstUtilIdx = i;
              }
            }
          }
          if (worstUtilIdx < 0) return;
          const newVal = getBotUtilityValue(loot.itemId as UtilityItemId, loot.rarity);
          if (newVal < worstUtilVal + BOT_UTILITY_SWAP_HYSTERESIS) {
            return;
          }
          replaceIdx = worstUtilIdx;
        }
      }
      const prev = c.slots[replaceIdx];
      c.slots[replaceIdx] =
        loot.kind === 'weapon'
          ? {
              kind: 'weapon',
              id: loot.itemId,
              rarity: loot.rarity,
              ammo: WEAPONS[loot.itemId as WeaponId].magSize,
            }
          : {
              kind: 'item',
              id: loot.itemId,
              rarity: loot.rarity,
              count: loot.count,
            };

      if (prev) {
        const dropX = Number((loot.x + (Math.random() - 0.5) * 0.7).toFixed(2));
        const dropY = Number(loot.y.toFixed(2));
        const dropZ = Number((loot.z + (Math.random() - 0.5) * 0.7).toFixed(2));
        const explicitDropId = this.mpActive
          ? `drop_${c.id}_${this.nextLootSeq++}`
          : undefined;
        const spawned = this.spawnLootDrop(
          dropX,
          dropY,
          dropZ,
          prev.kind,
          prev.id,
          prev.rarity,
          prev.count ?? 1,
          undefined,
          explicitDropId
        );
        spawned.droppedById = c.id;
        spawned.droppedAt = this.matchElapsed;
        if (this.mpActive) {
          this.mpClient?.send({
            type: 'loot_spawn',
            items: [
              {
                id: spawned.id,
                kind: spawned.kind,
                itemId: spawned.itemId,
                rarity: spawned.rarity,
                count: spawned.count,
                x: dropX,
                y: dropY,
                z: dropZ,
              },
            ],
          });
        }
      }
      placed = true;
      placedSlotIdx = replaceIdx;
    }

    if (placed) {
      this.scene.remove(loot.visual.root);
      this.lootDrops.splice(idx, 1);

      // Auto-Equip Convenience: switch immediately to first picked-up weapon when unarmed or holding an empty slot
      if (loot.kind === 'weapon' && (!hadAnyWeapon || activeWasEmpty) && placedSlotIdx >= 0) {
        c.activeSlot = placedSlotIdx;
        this.cancelReload(c);
      } else if (placedSlotIdx === c.activeSlot && c.isReloading) {
        // Active slot was upgraded/refilled or swapped while reloading
        this.cancelReload(c);
      }

      this.syncEquippedWeaponVisual(c);
      if (c.isPlayer) {
        this.audio.playPickup(loot.rarity);
      }
    }
  }

  private switchSlot(c: Combatant, index: number): void {
    if (index < 0 || index >= c.slots.length || c.activeSlot === index) return;
    if (c.channel) this.cancelChannel(c);
    this.cancelReload(c);
    c.activeSlot = index;
    this.syncEquippedWeaponVisual(c);
  }

  private cancelReload(c: Combatant): void {
    c.isReloading = false;
    c.reloadTimer = 0;
    c.reloadDuration = 0;
    if (c.isPlayer) {
      this.sprintLatchedOnReload = false;
    }
  }

  private startReload(c: Combatant): void {
    if (!c.alive || c.skyDropping || c.isReloading || c.rewind.active || c.ridingGBikeId !== null) return;
    const slot = c.slots[c.activeSlot];
    if (!slot || slot.kind !== 'weapon') return;
    const wDef = WEAPONS[slot.id as WeaponId];
    if ((slot.ammo ?? 0) >= wDef.magSize) return;
    if (c.channel) this.cancelChannel(c);
    // Direction A: immediately drop out of sprint and latch Shift so holding Shift+W doesn't cancel reload on next frame
    c.sprinting = false;
    if (c.isPlayer && (this.keys.has('ShiftLeft') || this.keys.has('ShiftRight'))) {
      this.sprintLatchedOnReload = true;
    }
    // Guard same-frame cancel + immediate re-reload so ReloadUpper restarts cleanly from t=0
    if (c.hero.currentAnim === 'Reload') {
      c.hero.crossFade(c.weaponInstance ? 'IdleArmed' : 'Idle', 0.02);
    }
    c.isAds = false;
    c.isReloading = true;
    c.reloadDuration = getWeaponReloadTime(wDef.id, slot.rarity);
    c.reloadTimer = c.reloadDuration;
    if (c.isPlayer) {
      this.audio.playReload(wDef.id);
    }
  }

  // =========================================================================
  // VISUALS, BLENDER ANIMATIONS, WEAPON SOCKET ALIGNMENT & CAMERA
  // =========================================================================

  private syncEquippedWeaponVisual(c: Combatant): void {
    const slot = c.slots[c.activeSlot];
    const desiredKey = slot && slot.kind === 'weapon' ? `${slot.id}:${slot.rarity}` : 'none';
    if (c.equippedKey === desiredKey) return;
    c.equippedKey = desiredKey;

    if (c.weaponInstance) {
      c.hero.weaponSocket.remove(c.weaponInstance.root);
      c.weaponInstance = null;
    }

    if (slot && slot.kind === 'weapon') {
      const inst = this.assetManager.instantiateWeapon(slot.id as WeaponId, slot.rarity);
      inst.root.visible = !c.skyDropping && c.ridingGBikeId === null;
      if (!c.castingShadow) {
        inst.root.traverse((obj) => {
          if (obj instanceof THREE.Mesh) obj.castShadow = false;
        });
      }
      c.hero.weaponSocket.add(inst.root);
      c.weaponInstance = inst;
      c.twoHandBlend = 1;
      if (!c.skyDropping && c.ridingGBikeId === null && c.hero.root.visible) {
        alignWeaponTwoHanded(inst.root, c.hero, { weaponId: inst.weaponId });
      }
    }
  }

  private setCombatantShadowCasting(c: Combatant, enabled: boolean): void {
    this.assetManager.setHeroCastShadow(c.hero, enabled);
    if (c.weaponInstance) {
      c.weaponInstance.root.traverse((obj) => {
        if (obj instanceof THREE.Mesh) {
          obj.castShadow = enabled;
        }
      });
    }
  }

  private updateBotOverheadAndReveal(c: Combatant, dSq: number, revealedByPlayer: boolean): void {
    const isTeammate = this.isFriendly(this.player, c);
    const isSpectatedTarget = this.spectateActive && c.id === this.spectateTargetId;
    const maxDist = isTeammate ? 120 : c.isRemoteHuman ? 72 : 56;
    const showOverhead =
      c.alive && !c.skyDropping && !isSpectatedTarget && (dSq < maxDist * maxDist || revealedByPlayer);
    c.hero.overheadGroup.visible = showOverhead;
    if (showOverhead) {
      c.hero.overheadGroup.position.y = c.crouching ? 1.55 : 2.18;
      c.hero.overheadGroup.quaternion
        .copy(c.hero.root.quaternion)
        .invert()
        .multiply(this.camController.camera.quaternion);
      const hpRatio = Math.max(0.001, c.health / GAME_CONSTANTS.MAX_HEALTH);
      c.hero.hpBarFill.scale.x = hpRatio;
      c.hero.hpBarFill.position.x = -(1 - hpRatio) * 0.56;
      const hasShield = c.shield > 0.5;
      const shRatio = Math.max(0.001, c.shield / GAME_CONSTANTS.MAX_SHIELD);
      c.hero.shieldBarBg.visible = hasShield;
      c.hero.shieldBarFill.visible = hasShield;
      if (hasShield) {
        c.hero.shieldBarFill.scale.x = shRatio;
        c.hero.shieldBarFill.position.x = -(1 - shRatio) * 0.56;
      }
    }

    // Google Chat @all Ping Overload glowing wallhack ring (depthTest: false; enemies only)
    c.hero.revealRing.visible = c.alive && revealedByPlayer && !isTeammate;
    if (c.hero.revealRing.visible) {
      const pulse = 1.0 + Math.sin(this.matchElapsed * 7.5) * 0.16;
      c.hero.revealRing.scale.setScalar(pulse);
    }
  }

  private getCrossFadeDuration(prevAnim: AnimName, nextAnim: AnimName): number {
    if (nextAnim === 'Jump' || nextAnim === 'JumpArmed') return 0.10;
    if (prevAnim === 'Jump' || prevAnim === 'JumpArmed') return 0.12;
    if (nextAnim === 'Aim') return 0.10;
    if (prevAnim === 'Reload') {
      if (nextAnim === 'Sprint' || nextAnim === 'SprintArmed') return 0.10;
      return 0.12;
    }
    if (nextAnim === 'Reload') return 0.12;
    if (nextAnim === 'Crouch' || prevAnim === 'Crouch') return 0.13;
    if (
      (prevAnim === 'Run' && nextAnim === 'Sprint') ||
      (prevAnim === 'Sprint' && nextAnim === 'Run') ||
      (prevAnim === 'RunArmed' && nextAnim === 'SprintArmed') ||
      (prevAnim === 'SprintArmed' && nextAnim === 'RunArmed')
    ) {
      return 0.14;
    }
    if (nextAnim === 'Glide') return 0.12;
    if (nextAnim === 'Idle' || nextAnim === 'IdleArmed') return 0.16;
    return 0.15;
  }

  /**
   * Applies additive vertical aim pitch across `Spine` (35%) and `Chest` (65%) around the hero's
   * world right axis after `mixer.update(dt)` so torso, head, both arms, and the two-handed rifle
   * pitch together seamlessly toward rooftops or courtyard targets while keeping both hands locked.
   */
  private applyUpperBodyAimPitch(c: Combatant, pitchRad: number): void {
    const { spineNode, chestNode, model, root } = c.hero;
    if (!spineNode && !chestNode) return;

    root.updateMatrixWorld(true);
    model.getWorldQuaternion(this.tmpQuatC);
    this.tmpVecA.set(1, 0, 0).applyQuaternion(this.tmpQuatC).normalize();

    if (spineNode && spineNode.parent) {
      spineNode.parent.getWorldQuaternion(this.tmpQuatA).invert();
      this.tmpVecB.copy(this.tmpVecA).applyQuaternion(this.tmpQuatA).normalize();
      this.tmpQuatB.setFromAxisAngle(this.tmpVecB, pitchRad * 0.35);
      spineNode.quaternion.premultiply(this.tmpQuatB);
      spineNode.updateMatrixWorld(true);
    }

    if (chestNode && chestNode.parent) {
      chestNode.parent.getWorldQuaternion(this.tmpQuatA).invert();
      this.tmpVecB.copy(this.tmpVecA).applyQuaternion(this.tmpQuatA).normalize();
      this.tmpQuatB.setFromAxisAngle(this.tmpVecB, pitchRad * 0.65);
      chestNode.quaternion.premultiply(this.tmpQuatB);
    }
  }

  /**
   * Reverses the exact procedural bone offsets applied on the previous frame right BEFORE
   * `mixer.update(animDt)` so Three.js `PropertyMixer.apply()` (which skips `setValue` whenever
   * interleaved clip buffers match at low `timeScale`!) NEVER accumulates procedural rotations.
   */
  private undoProceduralBoneOffsets(c: Combatant): void {
    if (!c.hasProcBoneUndo) return;
    const {
      spineNode,
      chestNode,
      thighLNode,
      shinLNode,
      footLNode,
      thighRNode,
      shinRNode,
      footRNode,
      upperArmLNode,
      lowerArmLNode,
      upperArmRNode,
      lowerArmRNode,
    } = c.hero;
    const u = c.procBoneUndo;
    if (spineNode) spineNode.quaternion.premultiply(u.spine).normalize();
    if (chestNode) chestNode.quaternion.premultiply(u.chest).normalize();
    if (thighLNode) thighLNode.quaternion.premultiply(u.thighL).normalize();
    if (shinLNode) shinLNode.quaternion.premultiply(u.shinL).normalize();
    if (footLNode) footLNode.quaternion.premultiply(u.footL).normalize();
    if (thighRNode) thighRNode.quaternion.premultiply(u.thighR).normalize();
    if (shinRNode) shinRNode.quaternion.premultiply(u.shinR).normalize();
    if (footRNode) footRNode.quaternion.premultiply(u.footR).normalize();
    if (upperArmLNode) upperArmLNode.quaternion.premultiply(u.upperArmL).normalize();
    if (lowerArmLNode) lowerArmLNode.quaternion.premultiply(u.lowerArmL).normalize();
    if (upperArmRNode) upperArmRNode.quaternion.premultiply(u.upperArmR).normalize();
    if (lowerArmRNode) lowerArmRNode.quaternion.premultiply(u.lowerArmR).normalize();
    c.hasProcBoneUndo = false;
  }

  /**
   * Applies procedural athletic feet-first tactical slide pose (after `mixer.update` and before
   * `alignWeaponTwoHanded`) using zero-allocation analytical 2-bone leg IK + boot heel-first pitch
   * + exact ground-surface floor-clearance clamping:
   * - Counter-pitches `Spine` & `Chest` upright so torso, head, and two-handed weapon aim dead-level forward
   * - Solves both legs (`Thigh/Shin/Foot_L` lead & `Thigh/Shin/Foot_R` trail) forward along `-Z` strictly ON TOP of the map
   * - Tilts both boots slightly toes-up (heel-first) so neither heel nor toe ever dips below floor
   * - Verifies live world-space ankle, boot-sole (heel/toe/edges), knee, and hip clearance on flat & sloped ground
   */
  private applySlideBonePose(c: Combatant, blend: number): void {
    const {
      spineNode,
      chestNode,
      thighLNode,
      shinLNode,
      footLNode,
      thighRNode,
      shinRNode,
      footRNode,
      model,
      root,
    } = c.hero;
    if (blend <= 0.001) return;

    root.updateMatrixWorld(true);
    root.getWorldQuaternion(this.tmpSlideRootQuat);

    // 1. Counter-pitch upper body upright around model +X so torso, head & rifle aim dead-level forward
    model.getWorldQuaternion(this.tmpQuatC);
    this.tmpVecA.set(1, 0, 0).applyQuaternion(this.tmpQuatC).normalize();

    const applyAxisRot = (node: THREE.Object3D | null, angleRad: number): void => {
      if (!node || !node.parent || Math.abs(angleRad) < 0.0005) return;
      node.parent.getWorldQuaternion(this.tmpQuatA).invert();
      this.tmpVecB.copy(this.tmpVecA).applyQuaternion(this.tmpQuatA).normalize();
      this.tmpQuatB.setFromAxisAngle(this.tmpVecB, angleRad);
      node.quaternion.premultiply(this.tmpQuatB).normalize();
      node.updateMatrixWorld(true);
    };

    applyAxisRot(spineNode, -0.24 * blend);
    applyAxisRot(chestNode, -0.32 * blend);

    // Terrain/surface floor height helper (never drops below c.pos.y; climbs smoothly on uphill slopes/ramps)
    const getFloorY = (wx: number, wz: number): number => {
      if (!c.grounded) return c.pos.y;
      const supportY = this.physics.getSupportHeight(wx, wz, c.pos.y, 0.10, 0.42);
      return Math.max(c.pos.y, Math.min(supportY, c.pos.y + 0.36));
    };

    // 2. Smoothly blended 2-bone leg IK toward forward (-Z) above-ground foot targets
    const solveSlideLeg = (
      thigh: THREE.Object3D | null,
      shin: THREE.Object3D | null,
      foot: THREE.Object3D | null,
      targetLocalX: number,
      targetLocalY: number,
      targetLocalZ: number,
      poleLocalX: number,
      poleLocalY: number,
      poleLocalZ: number
    ): void => {
      if (!thigh || !shin || !foot) return;

      thigh.getWorldPosition(this.tmpIkA);
      shin.getWorldPosition(this.tmpSlideCurKnee);
      foot.getWorldPosition(this.tmpSlideCurFoot);

      // Desired full-slide pole vector in world space
      this.tmpIkPole.set(poleLocalX, poleLocalY, poleLocalZ).applyQuaternion(this.tmpSlideRootQuat).normalize();

      // Current pre-IK knee bend plane (ensures 100% pop-free blend from blend=0..1)
      this.tmpIkD.copy(this.tmpSlideCurFoot).sub(this.tmpIkA);
      const curDist = this.tmpIkD.length();
      if (curDist > 1e-4) {
        this.tmpIkD.divideScalar(curDist);
        this.tmpSlidePrePole.copy(this.tmpSlideCurKnee).sub(this.tmpIkA);
        this.tmpSlidePrePole.addScaledVector(this.tmpIkD, -this.tmpSlidePrePole.dot(this.tmpIkD));
        if (this.tmpSlidePrePole.lengthSq() > 1e-6) {
          this.tmpSlidePrePole.normalize();
          this.tmpIkPole.lerpVectors(this.tmpSlidePrePole, this.tmpIkPole, blend);
          if (this.tmpIkPole.lengthSq() > 1e-6) {
            this.tmpIkPole.normalize();
          } else {
            this.tmpIkPole.set(poleLocalX, poleLocalY, poleLocalZ).applyQuaternion(this.tmpSlideRootQuat).normalize();
          }
        }
      }

      // Compute full-slide world target & lift cleanly above local terrain/ramp height
      this.tmpIkTarget.set(targetLocalX, targetLocalY, targetLocalZ);
      root.localToWorld(this.tmpIkTarget);
      const targetFloorY = getFloorY(this.tmpIkTarget.x, this.tmpIkTarget.z);
      this.tmpIkTarget.y = Math.max(this.tmpIkTarget.y, targetFloorY + targetLocalY);

      // Blend from live pre-IK ankle position to forward slide target, keeping above ground mid-transition
      this.tmpIkTarget.lerpVectors(this.tmpSlideCurFoot, this.tmpIkTarget, blend);
      if (blend > 0.08) {
        const curFloorY = getFloorY(this.tmpIkTarget.x, this.tmpIkTarget.z);
        this.tmpIkTarget.y = Math.max(this.tmpIkTarget.y, curFloorY + 0.115 * blend);
      }

      this.solveTwoBoneIK(thigh, shin, foot, this.tmpIkTarget, this.tmpIkPole);
    };

    // Lead Left Foot: stretches long & low forward along -Z, skimming flush heel-first on top of the map
    solveSlideLeg(thighLNode, shinLNode, footLNode, -0.15, 0.118, -0.68, -0.24, 0.94, -0.22);
    // Trail Right Foot: moves forward in front of pelvis with low outward-flared athletic baseball-slide knee
    solveSlideLeg(thighRNode, shinRNode, footRNode, +0.22, 0.114, -0.44, +0.92, 0.34, -0.18);

    // 3. Orient both boots heel-first (toes tilted slightly up) so neither heel nor toe clips below ground
    // Exact flat-sole Foot bone pitch in hero root space from build_characters.py: -PI/2 - atan2(0.068, 0.142) = -2.0174 rad
    const BOOT_FLAT_PITCH_X = -2.0174;
    const orientSlideBoot = (
      foot: THREE.Object3D | null,
      toeUpRad: number,
      yawFlareRad: number
    ): void => {
      if (!foot || !foot.parent) return;
      this.tmpSlideEuler.set(BOOT_FLAT_PITCH_X + toeUpRad, yawFlareRad, 0, 'YXZ');
      this.tmpSlideFootQuat.setFromEuler(this.tmpSlideEuler);
      this.tmpSlideFootQuat.premultiply(this.tmpSlideRootQuat);
      foot.parent.getWorldQuaternion(this.tmpQuatA).invert();
      this.tmpSlideFootQuat.premultiply(this.tmpQuatA).normalize();
      foot.quaternion.slerp(this.tmpSlideFootQuat, blend).normalize();
      foot.updateMatrixWorld(true);
    };

    orientSlideBoot(footLNode, 0.36, +0.08);
    orientSlideBoot(footRNode, 0.20, -0.26);

    // 4. Mathematical floor-clearance clamp (0 mm underground guarantee on flat & sloped terrain!)
    root.updateMatrixWorld(true);
    let maxDeficit = 0;

    const checkNodeClearance = (node: THREE.Object3D | null, minClearance: number): void => {
      if (!node) return;
      node.getWorldPosition(this.tmpVecA);
      const floorY = getFloorY(this.tmpVecA.x, this.tmpVecA.z);
      const deficit = floorY + minClearance - this.tmpVecA.y;
      if (deficit > maxDeficit) maxDeficit = deficit;
    };

    const checkBootSoleProbes = (foot: THREE.Object3D | null): void => {
      if (!foot) return;
      // Exact sneaker-boot sole extreme points transformed into Foot bone-local space:
      // Heel bottom (0, -0.021, -0.114), Toe bottom (0, +0.208, -0.005), Outer/Inner sole edges (±0.056, +0.032, -0.089)
      const checkProbe = (lx: number, ly: number, lz: number): void => {
        this.tmpVecA.set(lx, ly, lz);
        foot.localToWorld(this.tmpVecA);
        const floorY = getFloorY(this.tmpVecA.x, this.tmpVecA.z);
        const deficit = floorY + 0.005 - this.tmpVecA.y;
        if (deficit > maxDeficit) maxDeficit = deficit;
      };
      checkProbe(0, -0.021, -0.114);
      checkProbe(0, +0.208, -0.005);
      checkProbe(-0.056, +0.032, -0.089);
      checkProbe(+0.056, +0.032, -0.089);
    };

    checkNodeClearance(footLNode, 0.105);
    checkNodeClearance(footRNode, 0.105);
    checkBootSoleProbes(footLNode);
    checkBootSoleProbes(footRNode);
    checkNodeClearance(shinLNode, 0.13);
    checkNodeClearance(shinRNode, 0.13);
    checkNodeClearance(thighLNode, 0.24);
    checkNodeClearance(thighRNode, 0.24);

    if (maxDeficit > 0.0005) {
      model.position.y += maxDeficit;
      root.updateMatrixWorld(true);
    }
  }

  /**
   * Applies calm seated bicycle rider bone offsets (recorded into procBoneUndo so dismounting
   * restores 100% clean Blender clips with zero residual twist):
   * - Slight forward cycling torso tuck on Spine/Chest
   * - Alternating knee/thigh crank cadence synced to `bike.pedalSpin`
   */
  private solveTwoBoneIK(
    upper: THREE.Object3D | null,
    lower: THREE.Object3D | null,
    end: THREE.Object3D | null,
    targetWorld: THREE.Vector3,
    poleDirWorld: THREE.Vector3
  ): void {
    if (!upper || !lower || !end || !upper.parent || !lower.parent) return;

    upper.getWorldPosition(this.tmpIkA);
    lower.getWorldPosition(this.tmpIkB);
    end.getWorldPosition(this.tmpIkC);

    const len1 = this.tmpIkA.distanceTo(this.tmpIkB);
    const len2 = this.tmpIkB.distanceTo(this.tmpIkC);
    if (len1 < 1e-4 || len2 < 1e-4) return;

    this.tmpIkD.copy(targetWorld).sub(this.tmpIkA);
    const rawDist = this.tmpIkD.length();
    if (rawDist < 1e-4) return;
    this.tmpIkD.divideScalar(rawDist);

    const minReach = Math.abs(len1 - len2) + 0.015;
    const maxReach = len1 + len2 - 0.006;
    const d = THREE.MathUtils.clamp(rawDist, minReach, maxReach);
    const cosAlpha = THREE.MathUtils.clamp((len1 * len1 + d * d - len2 * len2) / (2 * len1 * d), -1, 1);
    const sinAlpha = Math.sqrt(Math.max(0, 1 - cosAlpha * cosAlpha));

    // Orthogonalize pole direction against A->T
    this.tmpIkE.copy(poleDirWorld).addScaledVector(this.tmpIkD, -poleDirWorld.dot(this.tmpIkD));
    if (this.tmpIkE.lengthSq() < 1e-6) {
      this.tmpIkE.set(0, 1, 0).addScaledVector(this.tmpIkD, -this.tmpIkD.y);
      if (this.tmpIkE.lengthSq() < 1e-6) this.tmpIkE.set(1, 0, 0);
    }
    this.tmpIkE.normalize();

    // Desired upper-segment unit direction & current upper-segment unit direction
    this.tmpVecA
      .copy(this.tmpIkD)
      .multiplyScalar(cosAlpha)
      .addScaledVector(this.tmpIkE, sinAlpha)
      .normalize();
    this.tmpVecB.copy(this.tmpIkB).sub(this.tmpIkA).normalize();

    this.tmpQuatB.setFromUnitVectors(this.tmpVecB, this.tmpVecA);
    upper.parent.getWorldQuaternion(this.tmpQuatA);
    this.tmpQuatC.copy(this.tmpQuatA).invert().multiply(this.tmpQuatB).multiply(this.tmpQuatA);
    upper.quaternion.premultiply(this.tmpQuatC).normalize();
    upper.updateMatrixWorld(true);

    // Aim lower segment directly from updated mid-joint to targetWorld
    lower.getWorldPosition(this.tmpIkB);
    end.getWorldPosition(this.tmpIkC);
    this.tmpVecB.copy(this.tmpIkC).sub(this.tmpIkB).normalize();
    this.tmpVecA.copy(targetWorld).sub(this.tmpIkB);
    if (this.tmpVecA.lengthSq() < 1e-6) return;
    this.tmpVecA.normalize();

    this.tmpQuatB.setFromUnitVectors(this.tmpVecB, this.tmpVecA);
    lower.parent.getWorldQuaternion(this.tmpQuatA);
    this.tmpQuatC.copy(this.tmpQuatA).invert().multiply(this.tmpQuatB).multiply(this.tmpQuatA);
    lower.quaternion.premultiply(this.tmpQuatC).normalize();
    lower.updateMatrixWorld(true);
  }

  private applyGBikeRiderPose(c: Combatant, bike: WorldGBike): void {
    const {
      spineNode,
      chestNode,
      thighLNode,
      shinLNode,
      footLNode,
      thighRNode,
      shinRNode,
      footRNode,
      upperArmLNode,
      lowerArmLNode,
      leftHandNode,
      upperArmRNode,
      lowerArmRNode,
      rightHandNode,
      model,
      root,
    } = c.hero;

    // Sync live GBike transforms first so handlebar & crank targets have zero 1-frame lag
    this.syncGBikeVisualTransform(bike);
    bike.visual.root.updateMatrixWorld(true);
    root.updateMatrixWorld(true);

    model.getWorldQuaternion(this.tmpQuatC);
    this.tmpVecA.set(1, 0, 0).applyQuaternion(this.tmpQuatC).normalize();

    const applyAxisRot = (node: THREE.Object3D | null, angleRad: number): void => {
      if (!node || !node.parent || Math.abs(angleRad) < 0.0005) return;
      node.parent.getWorldQuaternion(this.tmpQuatA).invert();
      this.tmpVecB.copy(this.tmpVecA).applyQuaternion(this.tmpQuatA).normalize();
      this.tmpQuatB.setFromAxisAngle(this.tmpVecB, angleRad);
      node.quaternion.premultiply(this.tmpQuatB);
      node.updateMatrixWorld(true);
    };

    // Lean torso comfortably forward toward handlebars while keeping head level forward
    applyAxisRot(spineNode, -0.24);
    applyAxisRot(chestNode, 0.12);

    // Bike world orientation for pole vectors & vertical foot offset
    bike.visual.root.getWorldQuaternion(this.tmpQuatC);
    const bikeUpWorld = this.tmpVecC.set(0, 1, 0).applyQuaternion(this.tmpQuatC).normalize();

    // 1. Lock BOTH hands onto the live steering handlebar rubber grips (GBike_FrontAssembly local (±0.292, 0.285, 0.137))
    const frontNode = bike.visual.frontAssembly ?? bike.visual.root;
    const isFrontChild = Boolean(bike.visual.frontAssembly);
    const gripY = isFrontChild ? 0.285 : 1.025;
    const gripZ = isFrontChild ? 0.137 : -0.223;

    this.tmpIkTarget.set(-0.292, gripY, gripZ);
    frontNode.localToWorld(this.tmpIkTarget);
    this.tmpIkPole.set(-0.58, -0.45, 0.68).applyQuaternion(this.tmpQuatC).normalize();
    this.solveTwoBoneIK(upperArmLNode, lowerArmLNode, leftHandNode, this.tmpIkTarget, this.tmpIkPole);

    this.tmpIkTarget.set(+0.292, gripY, gripZ);
    frontNode.localToWorld(this.tmpIkTarget);
    this.tmpIkPole.set(+0.58, -0.45, 0.68).applyQuaternion(this.tmpQuatC).normalize();
    this.solveTwoBoneIK(upperArmRNode, lowerArmRNode, rightHandNode, this.tmpIkTarget, this.tmpIkPole);

    // 2. Lock BOTH feet onto the live rotating crank pedals (GBike_CrankPedals local (±0.114, ∓0.145, 0.0) + sole clearance)
    if (bike.visual.crankPedals && footLNode && footRNode) {
      this.tmpIkTarget.set(-0.114, -0.145, 0.0);
      bike.visual.crankPedals.localToWorld(this.tmpIkTarget);
      this.tmpIkTarget.addScaledVector(bikeUpWorld, 0.065);
      this.tmpIkPole.set(-0.08, 0.14, -0.985).applyQuaternion(this.tmpQuatC).normalize();
      this.solveTwoBoneIK(thighLNode, shinLNode, footLNode, this.tmpIkTarget, this.tmpIkPole);

      this.tmpIkTarget.set(+0.114, +0.145, 0.0);
      bike.visual.crankPedals.localToWorld(this.tmpIkTarget);
      this.tmpIkTarget.addScaledVector(bikeUpWorld, 0.065);
      this.tmpIkPole.set(+0.08, 0.14, -0.985).applyQuaternion(this.tmpQuatC).normalize();
      this.solveTwoBoneIK(thighRNode, shinRNode, footRNode, this.tmpIkTarget, this.tmpIkPole);
    } else {
      const pedalWave = Math.sin(bike.pedalSpin);
      const pedalingAmp = THREE.MathUtils.clamp(Math.abs(bike.speed) / 8.0, 0, 1);
      applyAxisRot(thighLNode, 0.24 + pedalWave * 0.28 * pedalingAmp);
      applyAxisRot(shinLNode, -0.22 - pedalWave * 0.22 * pedalingAmp);
      applyAxisRot(thighRNode, 0.24 - pedalWave * 0.28 * pedalingAmp);
      applyAxisRot(shinRNode, -0.22 + pedalWave * 0.22 * pedalingAmp);
    }
  }

  /**
   * Pins `c.hero.gliderMount` directly to the live midpoint of `leftHandNode` & `rightHandNode`
   * in `c.hero.model` local space (after `mixer.update` + `updateMatrixWorld`) + calibrated
   * wrist-to-palm offset `(0.000, +0.076, -0.056)` so hands stay strictly locked onto the twin
   * glider handlebars at any bank angle, strafe, or dive.
   */
  private syncGliderMountToHands(c: Combatant): void {
    const { leftHandNode, rightHandNode, gliderMount, model, root } = c.hero;
    if (!leftHandNode || !rightHandNode) return;

    root.updateMatrixWorld(true);

    // Measure live Hand_L / Hand_R wrist positions in `model` local space
    leftHandNode.getWorldPosition(this.tmpVecA);
    model.worldToLocal(this.tmpVecA);

    rightHandNode.getWorldPosition(this.tmpVecB);
    model.worldToLocal(this.tmpVecB);

    // Pin gliderMount directly to live midpoint + exact wrist-to-palm grip offset
    this.tmpVecC
      .addVectors(this.tmpVecA, this.tmpVecB)
      .multiplyScalar(0.5)
      .add(GLIDE_MOUNT_LOCAL_OFFSET);
    gliderMount.position.copy(this.tmpVecC);

    // Micro-align trapeze bar axis with Left->Right hand line so subtle body sway never drifts palms off grips
    const dx = this.tmpVecB.x - this.tmpVecA.x;
    const dy = this.tmpVecB.y - this.tmpVecA.y;
    const dz = this.tmpVecB.z - this.tmpVecA.z;
    if (dx > 0.12) {
      const microRoll = THREE.MathUtils.clamp(Math.atan2(dy, dx), -0.22, 0.22);
      const microYaw = THREE.MathUtils.clamp(Math.atan2(-dz, dx), -0.22, 0.22);
      gliderMount.rotation.set(0, microYaw, microRoll, 'YXZ');
    } else {
      gliderMount.rotation.set(0, 0, 0);
    }
  }

  private syncCombatantVisuals(c: Combatant, dt: number): void {
    if (c.inBus) {
      if (c.hero.root.visible) c.hero.root.visible = false;
      if (c.gliderMesh.visible) c.gliderMesh.visible = false;
      c.hero.overheadGroup.visible = false;
      c.hero.revealRing.visible = false;
      c.prevYaw = c.yaw;
      c.prevVelX = c.vel.x;
      c.prevVelZ = c.vel.z;
      return;
    }

    const qCfg = QUALITY_PRESETS[this.qualityPreset];
    const revealedByPlayer = Boolean(this.player && this.player.revealedAllSec > 0);
    let isMidLod = false;
    let justBecameVisible = false;
    let botDistSq = 0;

    // Smart Bot Distance Culling & 3-Tier Animation/Shadow LOD (keep teammates & remote humans crisp at range!)
    if (!c.isPlayer) {
      const refPos = this.getCameraFocusPos();
      const dx = c.pos.x - refPos.x;
      const dz = c.pos.z - refPos.z;
      botDistSq = dx * dx + dz * dz;
      const isTeammate = this.isFriendly(this.player, c);
      const isSpectated = this.spectateActive && c.id === this.spectateTargetId;

      if (!c.skyDropping) {
        const effectiveCullDist = isTeammate || c.isRemoteHuman ? Math.max(qCfg.botCullDist, 145) : qCfg.botCullDist;
        const botCullDistSq = effectiveCullDist * effectiveCullDist;
        if (botDistSq > botCullDistSq && !revealedByPlayer && !isSpectated) {
          if (c.hero.root.visible) c.hero.root.visible = false;
          if (c.castingShadow) {
            c.castingShadow = false;
            this.setCombatantShadowCasting(c, false);
          }
          c.prevYaw = c.yaw;
          c.prevVelX = c.vel.x;
          c.prevVelZ = c.vel.z;
          return;
        }

        justBecameVisible = !c.hero.root.visible;
        if (justBecameVisible) {
          c.hero.root.visible = true;
        }
        this.visibleBotCount++;

        const fullAnimDistSq = qCfg.botFullAnimDist * qCfg.botFullAnimDist;
        if (botDistSq > fullAnimDistSq && !isSpectated) {
          isMidLod = true;
          if (c.castingShadow) {
            c.castingShadow = false;
            this.setCombatantShadowCasting(c, false);
          }
        } else if (!c.castingShadow) {
          c.castingShadow = true;
          this.setCombatantShadowCasting(c, true);
        }
      } else {
        // Sky-dropping bots stay visible across the sky, without casting shadows from altitude
        justBecameVisible = !c.hero.root.visible;
        if (justBecameVisible) c.hero.root.visible = true;
        this.visibleBotCount++;
        if (c.castingShadow) {
          c.castingShadow = false;
          this.setCombatantShadowCasting(c, false);
        }
      }
    }

    const riddenBike = c.ridingGBikeId
      ? this.worldGBikes.find((b) => b.id === c.ridingGBikeId) ?? null
      : null;

    if (riddenBike) {
      c.hero.root.position.set(riddenBike.x, riddenBike.y, riddenBike.z);
      c.hero.root.rotation.order = 'YXZ';
      c.hero.root.rotation.set(0, riddenBike.yaw, riddenBike.leanAngle);
    } else {
      c.hero.root.position.copy(c.pos);
      c.hero.root.rotation.order = 'YXZ';
      c.hero.root.rotation.set(0, c.yaw, 0);
    }

    // Mid-distance bots (> 68m balanced): smooth 60 Hz transform movement, 20 Hz (every 3rd frame) skeleton + weapon IK
    if (isMidLod && !justBecameVisible) {
      c.animAccumDt += dt;
      c.animFrameSkip++;
      if (c.animFrameSkip < 3) {
        c.prevYaw = c.yaw;
        c.prevVelX = c.vel.x;
        c.prevVelZ = c.vel.z;
        this.updateBotOverheadAndReveal(c, botDistSq, revealedByPlayer);
        return;
      }
    }
    const animDt = isMidLod ? c.animAccumDt + (justBecameVisible ? dt : 0) : dt + c.animAccumDt;
    c.animAccumDt = 0;
    c.animFrameSkip = 0;

    // 1. Smart armed vs. unarmed clip selection across all 12 baked Blender NLA clips
    const horizSpeed = Math.hypot(c.vel.x, c.vel.z);
    const hasWeapon = Boolean(c.weaponInstance && c.slots[c.activeSlot]?.kind === 'weapon');
    const aimingNow = hasWeapon && (c.isAds || this.matchElapsed - c.lastShotAt < 0.45);
    const isAirborneJump =
      !c.grounded && !c.skyDropping && !c.rewind.active && (c.vel.y > 2.2 || c.airborneTime > 0.08);

    let nextAnim: AnimName = hasWeapon ? 'IdleArmed' : 'Idle';
    if (c.skyDropping) {
      nextAnim = 'Glide';
    } else if (riddenBike) {
      // Symmetric unarmed Idle base prevents combat rifle crouch torso twist before 2-bone handlebar/pedal IK
      nextAnim = 'Idle';
    } else if (c.isReloading && hasWeapon) {
      nextAnim = 'Reload';
    } else if (isAirborneJump) {
      nextAnim = aimingNow ? 'Aim' : hasWeapon ? 'JumpArmed' : 'Jump';
    } else if (c.crouching) {
      nextAnim = 'Crouch';
    } else if (aimingNow) {
      nextAnim = 'Aim';
    } else if (c.sprinting && horizSpeed > 5.0) {
      nextAnim = hasWeapon ? 'SprintArmed' : 'Sprint';
    } else if (horizSpeed > 0.9) {
      nextAnim = hasWeapon ? 'RunArmed' : 'Run';
    } else {
      nextAnim = hasWeapon ? 'IdleArmed' : 'Idle';
    }

    // 2. Dynamic speed-matched stride (timeScale) across both unarmed & armed locomotion clips
    const runScale = THREE.MathUtils.clamp(horizSpeed / GAME_CONSTANTS.WALK_SPEED, 0.55, 1.45);
    const sprintScale = THREE.MathUtils.clamp(horizSpeed / GAME_CONSTANTS.SPRINT_SPEED, 0.55, 1.45);
    const crouchScale = riddenBike
      ? 0.04
      : c.sliding
        ? 0.08
        : horizSpeed < 0.25
          ? 0.25
          : THREE.MathUtils.clamp(horizSpeed / GAME_CONSTANTS.CROUCH_SPEED, 0.55, 1.45);
    c.hero.actions.Run.timeScale = runScale;
    c.hero.actions.RunArmed.timeScale = runScale;
    c.hero.actions.Sprint.timeScale = sprintScale;
    c.hero.actions.SprintArmed.timeScale = sprintScale;
    c.hero.actions.Crouch.timeScale = crouchScale;
    c.hero.actions.Idle.timeScale = 1.0;
    c.hero.actions.IdleArmed.timeScale = 1.0;
    c.hero.actions.Aim.timeScale =
      horizSpeed > 0.5
        ? THREE.MathUtils.clamp(0.9 + (horizSpeed / GAME_CONSTANTS.WALK_SPEED) * 0.25, 0.9, 1.2)
        : 1.0;
    const reloadClipDur = c.hero.actions.Reload.getClip()?.duration || 2.0;
    const reloadTimeScale =
      c.isReloading && c.reloadDuration > 0.1
        ? THREE.MathUtils.clamp(reloadClipDur / c.reloadDuration, 0.65, 1.65)
        : 1.0;
    c.hero.actions.Reload.timeScale = reloadTimeScale;
    c.hero.actions.Glide.timeScale = 1.0;
    c.hero.actions.Jump.timeScale = 1.0;
    c.hero.actions.JumpArmed.timeScale = 1.0;

    // 3. Crisp per-transition cross-fade (with upper/lower-body split locomotion during Reload)
    const fadeDur = this.getCrossFadeDuration(c.hero.currentAnim, nextAnim);
    if (nextAnim === 'Reload') {
      let lowerMode: ReloadLowerMode = 'stand';
      if (isAirborneJump) {
        lowerMode = 'jump';
      } else if (c.crouching) {
        lowerMode = 'crouch';
      } else if (horizSpeed > 0.6) {
        lowerMode = 'walk';
      }
      const lowerTimeScale =
        lowerMode === 'walk' ? runScale : lowerMode === 'crouch' ? crouchScale : 1.0;
      c.hero.setReloadPose(lowerMode, reloadTimeScale, lowerTimeScale, fadeDur);
    } else {
      c.hero.crossFade(nextAnim, fadeDur);
    }

    // 4. Dynamic strafe/turn body lean, tactical slide posture & landing/takeoff squash on hero.model
    const targetSlideBlend = c.sliding && !c.skyDropping ? 1 : 0;
    c.slidePoseBlend += (targetSlideBlend - c.slidePoseBlend) * Math.min(1, animDt * 14);
    if (!c.sliding && c.slidePoseBlend < 0.004) {
      c.slidePoseBlend = 0;
    }

    if (c.skyDropping) {
      c.slidePoseBlend = 0;
      c.hero.model.scale.set(1, 1, 1);
      c.hero.model.position.set(0, 0, 0);
      c.hero.model.rotation.x = c.glidePitch;
      c.hero.model.rotation.z = c.glideBank;
    } else if (riddenBike) {
      c.slidePoseBlend = 0;
      c.leanPitch = 0;
      c.leanBank = 0;
      c.hero.model.scale.set(1, 1, 1);
      // Anchor symmetric Idle pelvis (~0.92m in model space) squarely onto GBike_SeatMount (0, 0.95, 0.20)
      const seatZ = riddenBike.visual.seatMount ? riddenBike.visual.seatMount.position.z : 0.2;
      const seatY = riddenBike.visual.seatMount ? riddenBike.visual.seatMount.position.y - 0.90 : 0.05;
      c.hero.model.position.set(0, seatY, seatZ);
      c.hero.model.rotation.set(0, 0, 0);
    } else {
      const safeDt = Math.max(dt, 0.004);
      const fx = -Math.sin(c.yaw);
      const fz = -Math.cos(c.yaw);
      const rx = Math.cos(c.yaw);
      const rz = -Math.sin(c.yaw);

      const localFwd = c.vel.x * fx + c.vel.z * fz;
      const localRight = c.vel.x * rx + c.vel.z * rz;
      const accX = (c.vel.x - c.prevVelX) / safeDt;
      const accZ = (c.vel.z - c.prevVelZ) / safeDt;
      const localFwdAcc = THREE.MathUtils.clamp(accX * fx + accZ * fz, -28, 28);
      const localRightAcc = THREE.MathUtils.clamp(accX * rx + accZ * rz, -28, 28);

      let yawDelta = c.yaw - c.prevYaw;
      yawDelta = ((yawDelta + Math.PI * 3) % (Math.PI * 2)) - Math.PI;
      const yawRate = THREE.MathUtils.clamp(yawDelta / safeDt, -6.5, 6.5);

      // Keep aim/ADS/reload/channel rock-solid by zeroing dynamic lean cleanly
      const lockAimPosture =
        c.isAds ||
        c.isReloading ||
        c.channel !== null ||
        c.rewind.active ||
        this.matchElapsed - c.lastShotAt < 0.35;

      let targetLeanPitch = 0;
      let targetLeanBank = 0;
      if (!lockAimPosture && !c.sliding) {
        targetLeanPitch = THREE.MathUtils.clamp(
          -(localFwd / GAME_CONSTANTS.SPRINT_SPEED) * 0.068 - localFwdAcc * 0.0022,
          -0.11,
          0.06
        );
        if (!c.grounded) {
          targetLeanPitch = THREE.MathUtils.clamp(
            targetLeanPitch + c.vel.y * 0.0035,
            -0.12,
            0.08
          );
        }
        const carveFactor = Math.min(1, Math.max(0, localFwd / 9.5));
        targetLeanBank = THREE.MathUtils.clamp(
          -(localRight / GAME_CONSTANTS.WALK_SPEED) * 0.085 -
            localRightAcc * 0.0018 +
            yawRate * carveFactor * 0.032,
          -0.13,
          0.13
        );
      }

      const leanRate = lockAimPosture ? 16 : 10;
      const leanAlpha = Math.min(1, animDt * leanRate);
      c.leanPitch += (targetLeanPitch - c.leanPitch) * leanAlpha;
      c.leanBank += (targetLeanBank - c.leanBank) * leanAlpha;

      const b = c.slidePoseBlend;
      // Positive rotation.x leans hero BACK (feet-first forward toward -Z) in Three.js model space
      const slideBackLean = 0.56 * b;
      const slideHipBank = -0.14 * b * (c.isAds ? 0.15 : 1.0);
      c.hero.model.rotation.x = THREE.MathUtils.lerp(c.leanPitch, slideBackLean, b);
      c.hero.model.rotation.z = THREE.MathUtils.lerp(c.leanBank, slideHipBank, b);

      // Landing impulse squash (0.18s damped spring) & responsive takeoff bounce (0.14s)
      let scaleY = 1.0;
      let scaleXZ = 1.0;
      if (c.squashTimer > 0 && !c.rewind.active) {
        c.squashTimer = Math.max(0, c.squashTimer - animDt);
        const u = 1 - c.squashTimer / Math.max(c.squashDuration, 0.01);
        const dip = Math.sin(u * Math.PI) * Math.exp(-u * 1.15);
        scaleY = 1 - dip * 0.15 * c.squashIntensity;
        scaleXZ = 1 + dip * 0.075 * c.squashIntensity;
      } else if (c.takeoffTimer > 0 && !c.rewind.active) {
        c.takeoffTimer = Math.max(0, c.takeoffTimer - animDt);
        const u = 1 - c.takeoffTimer / 0.14;
        const stretch = Math.sin(u * Math.PI);
        scaleY = 1 + stretch * 0.055;
        scaleXZ = 1 - stretch * 0.025;
      }
      c.hero.model.scale.set(scaleXZ, scaleY, scaleXZ);
      // Lower pelvis smoothly to sleek athletic slide height (~0.36-0.38m) while 2-bone leg IK + floor clamp keep boots 100% on top of ground
      c.hero.model.position.set(0, -0.10 * b, -0.28 * b);
    }

    // 5. Restore clean clip quaternions before advancing Blender skeletal animation mixer
    this.undoProceduralBoneOffsets(c);
    c.hero.mixer.update(animDt);

    // 5a/5b. Apply procedural GBike seated pose, athletic slide pose & upper-body vertical aim pitch, recording exact undo deltas
    const hasGBikePose = Boolean(riddenBike) && !c.skyDropping;
    const hasSlideBonePose = !hasGBikePose && c.slidePoseBlend > 0.001 && !c.skyDropping;
    const trackAimPitch = !hasGBikePose && hasWeapon && (aimingNow || c.crouching) && !c.skyDropping && !c.isReloading;
    const targetAimPitch = trackAimPitch ? THREE.MathUtils.clamp(c.pitch, -0.65, 0.65) : 0;
    c.smoothAimPitch += (targetAimPitch - c.smoothAimPitch) * Math.min(1, animDt * 14);
    const hasAimPitchPose = !hasGBikePose && Math.abs(c.smoothAimPitch) > 0.001;

    if (hasGBikePose || hasSlideBonePose || hasAimPitchPose) {
      const {
        spineNode,
        chestNode,
        thighLNode,
        shinLNode,
        footLNode,
        thighRNode,
        shinRNode,
        footRNode,
        upperArmLNode,
        lowerArmLNode,
        upperArmRNode,
        lowerArmRNode,
      } = c.hero;
      const pre = this.tmpPreBoneQuats;
      if (spineNode) pre.spine.copy(spineNode.quaternion);
      if (chestNode) pre.chest.copy(chestNode.quaternion);
      if (thighLNode) pre.thighL.copy(thighLNode.quaternion);
      if (shinLNode) pre.shinL.copy(shinLNode.quaternion);
      if (footLNode) pre.footL.copy(footLNode.quaternion);
      if (thighRNode) pre.thighR.copy(thighRNode.quaternion);
      if (shinRNode) pre.shinR.copy(shinRNode.quaternion);
      if (footRNode) pre.footR.copy(footRNode.quaternion);
      if (upperArmLNode) pre.upperArmL.copy(upperArmLNode.quaternion);
      if (lowerArmLNode) pre.lowerArmL.copy(lowerArmLNode.quaternion);
      if (upperArmRNode) pre.upperArmR.copy(upperArmRNode.quaternion);
      if (lowerArmRNode) pre.lowerArmR.copy(lowerArmRNode.quaternion);

      if (hasGBikePose && riddenBike) {
        this.applyGBikeRiderPose(c, riddenBike);
      } else {
        if (hasSlideBonePose) {
          this.applySlideBonePose(c, c.slidePoseBlend);
        }
        if (hasAimPitchPose) {
          this.applyUpperBodyAimPitch(c, c.smoothAimPitch);
        }
      }

      // Compute exact undo delta R = Q_pre * inv(Q_post) so R * Q_post === Q_pre before next mixer.update()
      const u = c.procBoneUndo;
      const storeUndo = (node: THREE.Object3D | null, preQ: THREE.Quaternion, outUndo: THREE.Quaternion): void => {
        if (!node) {
          outUndo.identity();
          return;
        }
        outUndo.copy(node.quaternion).invert().premultiply(preQ).normalize();
      };
      storeUndo(spineNode, pre.spine, u.spine);
      storeUndo(chestNode, pre.chest, u.chest);
      storeUndo(thighLNode, pre.thighL, u.thighL);
      storeUndo(shinLNode, pre.shinL, u.shinL);
      storeUndo(footLNode, pre.footL, u.footL);
      storeUndo(thighRNode, pre.thighR, u.thighR);
      storeUndo(shinRNode, pre.shinR, u.shinR);
      storeUndo(footRNode, pre.footR, u.footR);
      storeUndo(upperArmLNode, pre.upperArmL, u.upperArmL);
      storeUndo(lowerArmLNode, pre.lowerArmL, u.lowerArmL);
      storeUndo(upperArmRNode, pre.upperArmR, u.upperArmR);
      storeUndo(lowerArmRNode, pre.lowerArmR, u.lowerArmR);
      c.hasProcBoneUndo = true;
    }

    // 6. Lock gliderMount directly to live Hand_L / Hand_R midpoint during Sky-Drop
    if (c.skyDropping) {
      this.syncGliderMountToHands(c);
    }

    // 7. Two-handed Hand_R (WeaponSocket_R) -> Hand_L barrel alignment with smooth Reload mag-swap handoff
    if (c.weaponInstance && !c.skyDropping && !riddenBike) {
      if (nextAnim === 'Reload') {
        // Exact Reload beat handoff matching build_characters.py 48f Reload:
        //   t ∈ [0.00, 0.04]: Beat 0 (two-handed Aim grip, weight = 1)
        //   t ∈ [0.04, 0.14]: smoothstep 1 -> 0 as Hand_L drops to waist mag pouch
        //   t ∈ [0.14, 0.84]: weight = 0 (WeaponSocket_R identity holds rifle cleanly canted in Hand_R)
        //   t ∈ [0.84, 0.96]: smoothstep 0 -> 1 as Hand_L returns to handguard
        //   t ∈ [0.96, 1.00]: Beat 5 (two-handed Aim grip, weight = 1)
        const t = c.hero.getReloadProgress01();
        let targetTwoHandWeight = 1.0;
        if (t <= 0.04 || t >= 0.96) {
          targetTwoHandWeight = 1.0;
        } else if (t < 0.14) {
          const u = (t - 0.04) / 0.10;
          targetTwoHandWeight = 1.0 - u * u * (3 - 2 * u);
        } else if (t <= 0.84) {
          targetTwoHandWeight = 0.0;
        } else {
          const u = (t - 0.84) / 0.12;
          targetTwoHandWeight = u * u * (3 - 2 * u);
        }
        c.twoHandBlend += (targetTwoHandWeight - c.twoHandBlend) * Math.min(1, animDt * 24);
      } else {
        c.twoHandBlend += (1.0 - c.twoHandBlend) * Math.min(1, animDt * 16);
      }

      alignWeaponTwoHanded(c.weaponInstance.root, c.hero, {
        weaponId: c.weaponInstance.weaponId,
        twoHandWeight: c.twoHandBlend,
      });
    }

    // Track previous kinematics for next frame's acceleration & turn-carve derivatives
    c.prevYaw = c.yaw;
    c.prevVelX = c.vel.x;
    c.prevVelZ = c.vel.z;

    // Hide local player model while zoomed into 16° Sniper Scope overlay to avoid self-clipping
    if (c.isPlayer) {
      const scoped = this.isPlayerSniperScoped();
      c.hero.root.visible = c.alive && !scoped;
    } else {
      this.updateBotOverheadAndReveal(c, botDistSq, revealedByPlayer);
    }
  }

  private updateLootChests(dt: number): void {
    const focusC = this.getCameraFocusCombatant();
    const refPos = focusC ? focusC.pos : this.camController.camera.position;
    const isSkyDropping = Boolean(focusC?.skyDropping);
    const qCfg = QUALITY_PRESETS[this.qualityPreset];
    const cullDist = isSkyDropping ? 320 : qCfg.chestCullDist;
    const cullDistSq = cullDist * cullDist;
    const beamDist = isSkyDropping ? 320 : qCfg.chestBeamDist;
    const beamDistSq = beamDist * beamDist;

    let visibleCount = 0;
    for (const ch of this.lootChests) {
      // Smoothly finish lid open swing even if player moves away
      if (ch.opened && ch.lidProgress < 1) {
        ch.lidProgress = Math.min(1, ch.lidProgress + dt * 3.8);
        const t = ch.lidProgress;
        const eased = 1 - Math.pow(1 - t, 3);
        if (ch.visual.lidNode) {
          ch.visual.lidNode.rotation.x = CHEST_LID_OPEN_ANGLE_RAD * eased;
        }
      }

      const dx = ch.x - refPos.x;
      const dz = ch.z - refPos.z;
      const dSq = dx * dx + dz * dz;

      if (dSq > cullDistSq) {
        if (ch.visual.root.visible) ch.visual.root.visible = false;
        continue;
      }

      if (!ch.visual.root.visible) ch.visual.root.visible = true;
      visibleCount++;

      const showBeam = !ch.opened && dSq <= beamDistSq;
      if (ch.visual.beam.visible !== showBeam) {
        ch.visual.beam.visible = showBeam;
      }

      if (!ch.opened) {
        ch.pulsePhase += dt * 2.6;
        const pulse = 0.88 + Math.sin(ch.pulsePhase) * 0.12;
        if (showBeam) {
          ch.visual.beam.scale.x = pulse;
          ch.visual.beam.scale.z = pulse;
        }
        ch.visual.ring.scale.setScalar(0.95 + Math.sin(ch.pulsePhase) * 0.06);
      }
    }
    this.visibleChestCount = visibleCount;
  }

  private updateLootVisuals(dt: number): void {
    const refPos = this.getCameraFocusPos();
    const lootCullDist = QUALITY_PRESETS[this.qualityPreset].lootCullDist;
    const lootCullDistSq = lootCullDist * lootCullDist;

    for (const l of this.lootDrops) {
      const dx = l.x - refPos.x;
      const dz = l.z - refPos.z;
      const dSq = dx * dx + dz * dz;
      const culled = dSq > lootCullDistSq;

      if (l.popProgress !== undefined && l.popProgress < 1) {
        l.popProgress = Math.min(1, l.popProgress + dt * 2.85);
        if (!culled) {
          const u = 1 - Math.pow(1 - l.popProgress, 2);
          const sx = l.popStartX ?? l.x;
          const sy = l.popStartY ?? l.y;
          const sz = l.popStartZ ?? l.z;
          const cx = sx + (l.x - sx) * u;
          const cz = sz + (l.z - sz) * u;
          const arcLift = Math.sin(l.popProgress * Math.PI) * 1.05;
          const cy = sy + (l.y - sy) * l.popProgress + arcLift;
          l.visual.root.position.set(cx, cy, cz);
        }
        if (l.popProgress >= 1) {
          l.visual.root.position.set(l.x, l.y, l.z);
        }
      }

      if (culled) {
        if (l.visual.root.visible) l.visual.root.visible = false;
        continue;
      }

      if (!l.visual.root.visible) l.visual.root.visible = true;
      l.bobPhase += dt * 2.2;
      l.visual.itemHolder.rotation.y += dt * 1.35;
      l.visual.itemHolder.position.y = 0.58 + Math.sin(l.bobPhase) * 0.12;
      l.visual.ring.rotation.z += dt * 0.8;
    }
  }

  private isPlayerSniperScoped(): boolean {
    if (!this.player || !this.player.alive || !this.player.isAds || this.player.skyDropping) {
      return false;
    }
    const slot = this.player.slots[this.player.activeSlot];
    return Boolean(slot && slot.kind === 'weapon' && WEAPONS[slot.id as WeaponId].hasScope);
  }

  private updateCamera(dt: number): void {
    if (this.spectateActive) {
      if (this.spectateMode === 'free') {
        const shiftHeld = this.keys.has('ShiftLeft') || this.keys.has('ShiftRight');
        const speed = shiftHeld ? 38 : 16;
        const cosP = Math.cos(this.freeCamPitch);
        const sinP = Math.sin(this.freeCamPitch);
        const sinY = Math.sin(this.freeCamYaw);
        const cosY = Math.cos(this.freeCamYaw);

        const fwd = this.tmpVecA.set(-sinY * cosP, sinP, -cosY * cosP).normalize();
        const right = this.tmpVecB.set(cosY, 0, -sinY).normalize();
        const move = this.tmpVecC.set(0, 0, 0);

        if (this.keys.has('KeyW') || this.keys.has('ArrowUp')) move.add(fwd);
        if (this.keys.has('KeyS') || this.keys.has('ArrowDown')) move.sub(fwd);
        if (this.keys.has('KeyD') || this.keys.has('ArrowRight')) move.add(right);
        if (this.keys.has('KeyA') || this.keys.has('ArrowLeft')) move.sub(right);
        if (this.keys.has('Space')) move.y += 1;
        if (this.keys.has('KeyC') || this.keys.has('ControlLeft')) move.y -= 1;

        if (move.lengthSq() > 0.0001) {
          move.normalize();
          this.freeCamPos.addScaledVector(move, speed * dt);
        }

        this.freeCamPos.x = THREE.MathUtils.clamp(this.freeCamPos.x, -310, 310);
        this.freeCamPos.z = THREE.MathUtils.clamp(this.freeCamPos.z, -200, 200);
        const minTerrainY =
          this.physics.getTerrainHeight(this.freeCamPos.x, this.freeCamPos.z) + 1.2;
        this.freeCamPos.y = THREE.MathUtils.clamp(this.freeCamPos.y, minTerrainY, 185);

        this.camController.updateFreeCam(
          dt,
          this.freeCamPos,
          this.freeCamYaw,
          this.freeCamPitch,
          shiftHeld
        );
        return;
      }

      let target = this.spectateTargetId
        ? this.combatants.find((c) => c.id === this.spectateTargetId && c.alive) ?? null
        : null;
      if (!target) {
        target = this.pickBestSpectateTarget(null);
      }
      if (!target) {
        this.setSpectateMode('free');
        return;
      }
      if (target) {
        const riddenBike = target.ridingGBikeId
          ? this.worldGBikes.find((b) => b.id === target?.ridingGBikeId) ?? null
          : null;
        this.camController.update({
          dt,
          playerPos: target.pos,
          yaw: target.yaw,
          pitch: target.pitch,
          crouching: target.crouching,
          sliding: target.sliding,
          ridingGBike: Boolean(riddenBike),
          gbikeLean: riddenBike ? riddenBike.leanAngle : 0,
          sprinting: target.sprinting,
          isAds: false,
          sniperScope: false,
          skyDropping: target.skyDropping,
          inBus: target.inBus,
          dead: false,
          raycastDist: (origin, dir, maxDist) => {
            const hit = this.physics.raycastWorld(origin, dir, maxDist);
            return hit ? hit.distance : maxDist;
          },
        });
        return;
      }
    }
    if (!this.player) return;
    const riddenBike = this.player.ridingGBikeId
      ? this.worldGBikes.find((b) => b.id === this.player?.ridingGBikeId) ?? null
      : null;
    this.camController.update({
      dt,
      playerPos: this.player.pos,
      yaw: this.player.yaw,
      pitch: this.player.pitch,
      crouching: this.player.crouching,
      sliding: this.player.sliding,
      ridingGBike: Boolean(riddenBike),
      gbikeLean: riddenBike ? riddenBike.leanAngle : 0,
      sprinting: this.player.sprinting,
      isAds: this.player.isAds,
      sniperScope: this.isPlayerSniperScoped(),
      skyDropping: this.player.skyDropping,
      inBus: this.player.inBus,
      dead: !this.player.alive,
      raycastDist: (origin, dir, maxDist) => {
        const hit = this.physics.raycastWorld(origin, dir, maxDist);
        return hit ? hit.distance : maxDist;
      },
    });
  }

  // =========================================================================
  // SPATIAL STEREO PANNING & VISUAL SOUND COMPASS CUE TRACKER
  // =========================================================================

  private computeSpatialPan(sourcePos: THREE.Vector3): number {
    const p = this.getCameraFocusCombatant();
    if (!p) return 0;
    const dx = sourcePos.x - p.pos.x;
    const dz = sourcePos.z - p.pos.z;
    const dist = Math.hypot(dx, dz);
    if (dist < 1.0) return 0;
    const rx = Math.cos(p.yaw);
    const rz = -Math.sin(p.yaw);
    return THREE.MathUtils.clamp((dx * rx + dz * rz) / Math.max(dist, 0.5), -0.92, 0.92);
  }

  private pushSoundEvent(
    kind: SoundCueKind,
    x: number,
    z: number,
    maxRange: number,
    ttl: number,
    weight: number
  ): void {
    if (this.soundEvents.length >= 64) {
      this.soundEvents.shift();
    }
    this.soundEvents.push({ kind, x, z, maxRange, age: 0, ttl, weight });
  }

  private updateSoundEvents(dt: number): void {
    for (let i = this.soundEvents.length - 1; i >= 0; i--) {
      const ev = this.soundEvents[i];
      ev.age += dt;
      if (ev.age >= ev.ttl) {
        this.soundEvents.splice(i, 1);
      }
    }
  }

  private computeSoundCompassCues(p: Combatant | null): SoundCompassCue[] {
    if (!p || !p.alive || p.skyDropping || this.matchPhase !== 'playing') {
      return [];
    }

    const fx = -Math.sin(p.yaw);
    const fz = -Math.cos(p.yaw);
    const rx = Math.cos(p.yaw);
    const rz = -Math.sin(p.yaw);

    const raw: SoundCompassCue[] = [];

    // 1. Transient combat, footstep & GBike sound events
    for (let i = 0; i < this.soundEvents.length; i++) {
      const ev = this.soundEvents[i];
      const dx = ev.x - p.pos.x;
      const dz = ev.z - p.pos.z;
      const dist = Math.hypot(dx, dz);
      if (dist > ev.maxRange || dist < 0.25) continue;
      const fade = Math.max(0, 1 - ev.age / Math.max(ev.ttl, 0.05));
      const intensity = THREE.MathUtils.clamp((1 - dist / ev.maxRange) * ev.weight * fade, 0.12, 1.0);
      const bearingRad = Math.atan2(dx * rx + dz * rz, dx * fx + dz * fz);
      raw.push({ kind: ev.kind, bearingRad, intensity });
    }

    // 2. Live proximity cues for unopened Tier 3 Epic Vault Chests within 34m (top 2 closest keep ring ultra-clean)
    const nearbyChests: { dist: number; bearingRad: number; intensity: number }[] = [];
    for (let i = 0; i < this.lootChests.length; i++) {
      const ch = this.lootChests[i];
      if (ch.opened || ch.tier !== 3) continue;
      const dx = ch.x - p.pos.x;
      const dy = ch.y - p.pos.y;
      const dz = ch.z - p.pos.z;
      const dist = Math.hypot(dx, dy, dz);
      if (dist > 34 || dist < 0.4) continue;
      const intensity = THREE.MathUtils.clamp((1 - dist / 34) * 0.68, 0.14, 0.72);
      const bearingRad = Math.atan2(dx * rx + dz * rz, dx * fx + dz * fz);
      nearbyChests.push({ dist, bearingRad, intensity });
    }
    nearbyChests.sort((a, b) => a.dist - b.dist);
    for (let i = 0; i < Math.min(2, nearbyChests.length); i++) {
      const c = nearbyChests[i];
      raw.push({ kind: 'chest', bearingRad: c.bearingRad, intensity: c.intensity });
    }

    // 3. Live proximity cues for landed unopened Epic Supply Drops within 65m
    for (let i = 0; i < this.supplyDrops.length; i++) {
      const sd = this.supplyDrops[i];
      if (!sd.landed || sd.opened) continue;
      const dx = sd.x - p.pos.x;
      const dz = sd.z - p.pos.z;
      const dist = Math.hypot(dx, dz);
      if (dist > 65 || dist < 0.4) continue;
      const intensity = THREE.MathUtils.clamp((1 - dist / 65) * 0.85, 0.12, 1.0);
      const bearingRad = Math.atan2(dx * rx + dz * rz, dx * fx + dz * fz);
      raw.push({ kind: 'supply_drop', bearingRad, intensity });
    }

    if (raw.length === 0) return [];

    // Sort strongest first, deduplicate/cluster cues of same kind within 0.28 rad (~16°), cap top 10
    raw.sort((a, b) => b.intensity - a.intensity);
    const clustered: SoundCompassCue[] = [];
    for (let i = 0; i < raw.length; i++) {
      const cand = raw[i];
      let merged = false;
      for (let j = 0; j < clustered.length; j++) {
        const existing = clustered[j];
        if (existing.kind !== cand.kind) continue;
        let diff = Math.abs(existing.bearingRad - cand.bearingRad);
        if (diff > Math.PI) diff = Math.PI * 2 - diff;
        if (diff < 0.28) {
          merged = true;
          break;
        }
      }
      if (!merged) {
        clustered.push(cand);
        if (clustered.length >= 10) break;
      }
    }

    return clustered;
  }

  private projectWorldToScreen(worldPos: THREE.Vector3): { x: number; y: number } | null {
    this.tmpProj.copy(worldPos).project(this.camController.camera);
    if (this.tmpProj.z > 1) return null;
    const rect = this.renderer.domElement.getBoundingClientRect();
    return {
      x: (this.tmpProj.x * 0.5 + 0.5) * rect.width,
      y: (-this.tmpProj.y * 0.5 + 0.5) * rect.height,
    };
  }

  // =========================================================================
  // HUD SNAPSHOT & MINIMAP STATE
  // =========================================================================

  private emitHudSnapshot(): void {
    const p = this.player;
    const focusC = this.getCameraFocusCombatant();
    const spectateTarget =
      this.spectateActive && this.spectateTargetId
        ? this.combatants.find((c) => c.id === this.spectateTargetId && c.alive) ?? null
        : null;
    const heroId: ProductHeroId = p?.heroId ?? 'gmail';
    const heroDef = HERO_MAP[heroId];
    const mode = GAME_MODES[this.activeGameMode] ?? GAME_MODES.battle_royale;
    const phaseDef = STORM_PHASES[this.stormPhaseIndex] ?? STORM_PHASES[STORM_PHASES.length - 1];

    const aliveCount = this.combatants.filter((c) => c.alive).length;
    const inStorm =
      mode.stormEnabled && focusC
        ? Math.hypot(focusC.pos.x - this.stormCenterX, focusC.pos.z - this.stormCenterZ) > this.stormRadius
        : false;

    const groundY = p ? this.physics.getSupportHeight(p.pos.x, p.pos.z, p.pos.y, 0.42, 0.65) : 0;
    const altitude = p ? Math.max(0, Math.round(p.pos.y - groundY)) : 0;

    // Context interact prompt ([E]) — Supply Drops, Unopened Loot Chests, Popped Loot, TechStops, & Rideable GBikes
    let interactPrompt: string | null = null;
    if (p && p.alive && !p.skyDropping && !p.channel && p.ridingGBikeId === null) {
      const target = this.resolveNearestInteractable(p);
      interactPrompt = target ? target.prompt : null;
    }

    const riddenBike =
      p && p.ridingGBikeId
        ? this.worldGBikes.find((b) => b.id === p.ridingGBikeId) ?? null
        : null;

    // Dynamic crosshair spread in screen pixels
    const activeSlotObj = p ? p.slots[p.activeSlot] : null;
    let spreadPx = 10;
    if (activeSlotObj?.kind === 'weapon') {
      const w = WEAPONS[activeSlotObj.id as WeaponId];
      let sp = w.spread;
      if (p?.isAds) sp *= w.adsSpreadMult;
      if (p?.crouching) sp *= GAME_CONSTANTS.CROUCH_SPREAD_MULT;
      if (p && Math.hypot(p.vel.x, p.vel.z) > 2) sp *= 1.25;
      spreadPx = Math.max(4, Math.min(48, Math.round(sp * 580)));
    }

    const channelState: ChannelState = p?.channel
      ? {
          active: true,
          label: p.channel.label,
          progress: Math.min(1, p.channel.elapsed / Math.max(p.channel.duration, 0.01)),
          remainingSec: Math.max(0, p.channel.duration - p.channel.elapsed),
          totalSec: p.channel.duration,
          kind: p.channel.kind,
          chestTier: p.channel.chestTier,
        }
      : {
          active: false,
          label: '',
          progress: 0,
          remainingSec: 0,
          totalSec: 0,
        };

    const supplyDropBearings: SupplyDropBearing[] = this.supplyDrops
      .filter((d) => !d.opened)
      .map((d) => {
        const px = focusC?.pos.x ?? 0;
        const pz = focusC?.pos.z ?? 0;
        const yaw = focusC?.yaw ?? 0;
        const dx = d.x - px;
        const dz = d.z - pz;
        const fx = -Math.sin(yaw);
        const fz = -Math.cos(yaw);
        const rx = Math.cos(yaw);
        const rz = -Math.sin(yaw);
        return {
          // Relative angle from player forward in radians (+right, -left) matching TacticalMinimap.renderCompass
          angleRad: Math.atan2(dx * rx + dz * rz, dx * fx + dz * fz),
          dist: Math.round(Math.hypot(dx, dz)),
          landed: d.landed,
          opened: d.opened,
        };
      });

    let waypointBearingRad: number | null = null;
    let waypointDist: number | null = null;
    if (this.waypoint && focusC) {
      const dx = this.waypoint.x - focusC.pos.x;
      const dz = this.waypoint.z - focusC.pos.z;
      const fx = -Math.sin(focusC.yaw);
      const fz = -Math.cos(focusC.yaw);
      const rx = Math.cos(focusC.yaw);
      const rz = -Math.sin(focusC.yaw);
      waypointBearingRad = Math.atan2(dx * rx + dz * rz, dx * fx + dz * fz);
      waypointDist = Math.round(Math.hypot(dx, dz));
    }

    const snapshot: HudSnapshot = {
      health: Math.ceil(p?.health ?? 100),
      maxHealth: GAME_CONSTANTS.MAX_HEALTH,
      shield: Math.ceil(p?.shield ?? GAME_CONSTANTS.START_SHIELD),
      maxShield: GAME_CONSTANTS.MAX_SHIELD,
      mana: Math.floor(p?.mana ?? mode.startMana),
      maxMana: GAME_CONSTANTS.MAX_MANA,
      aliveCount,
      totalPlayers: this.combatants.length || mode.totalCombatants,
      eliminations: p?.eliminations ?? 0,
      headshots: p?.headshots ?? 0,
      damageDealt: Math.round(p?.damageDealt ?? 0),
      heroId,
      heroName: heroDef.productName,
      heroPersona: heroDef.personaName,
      botDifficulty: this.activeBotDifficulty,
      gameMode: this.activeGameMode,
      slots: p ? p.slots.map((s) => (s ? { ...s } : null)) : [null, null, null, null, null],
      activeSlot: p?.activeSlot ?? 0,
      isReloading: p?.isReloading ?? false,
      reloadProgress:
        p && p.isReloading && p.reloadDuration > 0
          ? 1 - Math.max(0, p.reloadTimer) / p.reloadDuration
          : 0,
      isAds: p?.isAds ?? false,
      sniperScope: this.isPlayerSniperScoped(),
      spreadPx,
      ultName: heroDef.ultimate.name,
      ultManaCost: heroDef.ultimate.manaCost,
      ultCooldown: p?.ultCooldown ?? 0,
      ultMaxCooldown: heroDef.ultimate.cooldown,
      ultReady: Boolean(
        p &&
          p.alive &&
          !p.skyDropping &&
          p.ultCooldown <= 0 &&
          p.mana >= heroDef.ultimate.manaCost &&
          p.silencedSec <= 0
      ),
      stormPhase: mode.stormEnabled ? phaseDef.phase : 0,
      stormStateLabel: mode.stormEnabled
        ? phaseDef.isMoving
          ? this.stormMode === 'wait'
            ? `Moving Zone ${phaseDef.phase}`
            : `Zone ${phaseDef.phase} Moving`
          : this.stormMode === 'wait'
            ? `Phase ${phaseDef.phase} Wait`
            : `Phase ${phaseDef.phase} Shrinking`
        : 'FREE ROAM · NO STORM',
      stormTimer: mode.stormEnabled ? Math.max(0, Math.ceil(this.stormPhaseTimer)) : 0,
      inStorm,
      stormDps: mode.stormEnabled ? phaseDef.dps : 0,
      stormIsMoving: mode.stormEnabled ? Boolean(phaseDef.isMoving) : false,
      zoneName:
        this.spectateActive && this.spectateMode === 'free'
          ? this.world
            ? this.world.getZoneName(this.freeCamPos.x, this.freeCamPos.z)
            : 'Googleplex Campus'
          : focusC && this.world
            ? this.world.getZoneName(focusC.pos.x, focusC.pos.z)
            : 'Googleplex Campus',
      headingRad:
        this.spectateActive && this.spectateMode === 'free'
          ? this.freeCamYaw
          : focusC
            ? focusC.yaw
            : 0, // Standard Three.js yaw (0 = North -Z, turning right decreases yaw)
      interactPrompt,
      channel: channelState,
      status: {
        crouching: p?.crouching ?? false,
        sliding: p?.sliding ?? false,
        ridingGBike: Boolean(riddenBike),
        gbikeSpeedKmh: riddenBike ? Math.abs(riddenBike.speed) * 3.6 : 0,
        inBus: p?.inBus ?? false,
        canDropFromBus: Boolean(
          p?.inBus &&
            this.gbus &&
            this.gbus.active &&
            this.gbus.progress >= GAME_CONSTANTS.GBUS_DROP_UNLOCK_PROGRESS
        ),
        busProgress:
          this.gbus && this.gbus.active ? THREE.MathUtils.clamp(this.gbus.progress, 0, 1) : 0,
        silencedSec: p?.silencedSec ?? 0,
        hastedSec: p?.hastedSec ?? 0,
        slowedSec: p?.slowedSec ?? 0,
        revealedSec: p?.revealedSec ?? 0,
        rewinding: p?.rewind.active ?? false,
        inStorm,
        skyDropping: p?.skyDropping ?? false,
        altitude,
      },
      supplyDropBearings,
      soundCues: this.spectateActive ? [] : this.computeSoundCompassCues(p),
      waypointBearingRad,
      waypointDist,
      pointerLocked: this.pointerLocked,
      matchPhase: this.matchPhase,
      flashBlindAlpha:
        p && p.alive && p.blindedSec > 0
          ? Number(
              THREE.MathUtils.clamp(
                Math.pow(Math.min(1, p.blindedSec / 1.4), 0.72) * Math.max(0.75, p.flashBlindPeak),
                0,
                0.98
              ).toFixed(3)
            )
          : 0,
      multiplayer: this.mpActive
        ? {
            active: true,
            roomCode: this.mpRoomCode,
            format: this.mpFormat,
            teamId: this.mpTeamId,
            aliveTeams: this.mpAliveTeams || this.computeAliveTeamsCount(),
            rttMs: this.mpClient?.rttMs ?? 0,
          }
        : null,
      spectating: this.spectateActive
        ? this.spectateMode === 'free'
          ? (() => {
              const freeZone = this.world
                ? this.world.getZoneName(this.freeCamPos.x, this.freeCamPos.z)
                : 'Googleplex Campus';
              return {
                active: true,
                mode: 'free' as const,
                targetId: '',
                targetName: freeZone,
                targetHeroId: 'gmail' as const,
                health: 0,
                shield: 0,
                teamId: null,
                altitude: Math.round(this.freeCamPos.y),
                zoneName: freeZone,
              };
            })()
          : spectateTarget
            ? {
                active: true,
                mode: 'follow' as const,
                targetId: spectateTarget.id,
                targetName: spectateTarget.name,
                targetHeroId: spectateTarget.heroId,
                health: Math.ceil(spectateTarget.health),
                shield: Math.ceil(spectateTarget.shield),
                teamId: spectateTarget.teamId,
              }
            : null
        : null,
    };

    this.callbacks.onHudUpdate(snapshot);
  }

  public getMinimapState(): MinimapState {
    const p = this.getCameraFocusCombatant();
    const revealedAll = Boolean(this.player && this.player.revealedAllSec > 0);

    const enemies: MinimapEntity[] = [];
    for (const c of this.combatants) {
      if (!c.alive) continue;
      if (p && c.id === p.id) continue;
      if (this.mpActive && this.mpFormat === 'teams' && this.isFriendly(this.player, c)) {
        const teamColor = c.teamId ? TEAM_CONFIG[c.teamId].colorCss : '#1A73E8';
        enemies.push({
          x: c.pos.x,
          z: c.pos.z,
          isTeammate: true,
          name: c.name,
          teamColor,
          color: teamColor,
          isBot: !c.isRemoteHuman,
        });
        continue;
      }
      if (c.isPlayer) continue;
      if (c.inBus) continue;
      const dist = p ? c.pos.distanceTo(p.pos) : 999;
      const recentlyFired = this.matchElapsed - c.lastShotAt < 2.2 && dist < 115;
      if (revealedAll || dist < 48 || recentlyFired) {
        enemies.push({
          x: c.pos.x,
          z: c.pos.z,
          color: revealedAll ? '#10b981' : HERO_MAP[c.heroId].primaryColor,
          revealed: revealedAll,
          isBot: !c.isRemoteHuman,
        });
      }
    }

    const loot: MinimapLootPip[] = this.lootDrops
      .filter((l) => l.rarity !== 'common')
      .map((l) => ({ x: l.x, z: l.z, rarity: l.rarity }));

    // Unopened Loot Chests on radar: show all chests during Sky-Drop gliding or Full Tactical Map;
    // on ground corner minimap, show all Tier 3 vaults, Tier 2 within 175m, and Tier 1 within 95m.
    const chests: MinimapChestPip[] = [];
    const px = p?.pos.x ?? -51;
    const pz = p?.pos.z ?? 4;
    const isGliding = Boolean(p?.skyDropping);
    for (const ch of this.lootChests) {
      if (ch.opened) continue;
      if (!isGliding && !this.mapOpen && ch.tier < 3) {
        const d = Math.hypot(ch.x - px, ch.z - pz);
        if (ch.tier === 1 && d > 95) continue;
        if (ch.tier === 2 && d > 175) continue;
      }
      chests.push({ x: ch.x, z: ch.z, tier: ch.tier });
    }

    const supplyDrops: MinimapSupplyDrop[] = this.supplyDrops.map((s) => ({
      x: s.x,
      z: s.z,
      landed: s.landed,
      opened: s.opened,
    }));

    const gbikes: MinimapGBike[] = this.worldGBikes.map((b) => ({
      x: b.x,
      z: b.z,
      occupied: b.riderId !== null,
    }));

    const techStops: MinimapTechStop[] = (this.world?.techStops ?? []).map((ts) => ({
      x: ts.x,
      z: ts.z,
      name: ts.name,
    }));

    const mode = GAME_MODES[this.activeGameMode] ?? GAME_MODES.battle_royale;
    const phaseDef = STORM_PHASES[this.stormPhaseIndex] ?? STORM_PHASES[STORM_PHASES.length - 1];

    const isFreeCam = this.spectateActive && this.spectateMode === 'free';
    return {
      playerX: isFreeCam ? this.freeCamPos.x : px,
      playerZ: isFreeCam ? this.freeCamPos.z : pz,
      playerYaw: isFreeCam ? this.freeCamYaw : p?.yaw ?? 0,
      stormCenterX: this.stormCenterX,
      stormCenterZ: this.stormCenterZ,
      stormRadius: this.stormRadius,
      nextStormCenterX: this.nextStormCenterX,
      nextStormCenterZ: this.nextStormCenterZ,
      nextStormRadius: this.nextStormRadius,
      enemies,
      loot,
      chests,
      supplyDrops,
      gbikes,
      techStops,
      gbus:
        this.gbus && this.gbus.active
          ? {
              active: true,
              x: this.gbus.x,
              z: this.gbus.z,
              yaw: this.gbus.yaw,
              startX: this.gbus.startX,
              startZ: this.gbus.startZ,
              endX: this.gbus.endX,
              endZ: this.gbus.endZ,
              progress: THREE.MathUtils.clamp(this.gbus.progress, 0, 1),
            }
          : null,
      stormMoving: mode.stormEnabled ? Boolean(phaseDef.isMoving) : false,
      landmarks: this.world?.landmarks ?? [],
      revealedAll,
      waypoint: this.waypoint ? { x: this.waypoint.x, z: this.waypoint.z } : null,
    };
  }

  // =========================================================================
  // INPUT HANDLERS & LIFECYCLE
  // =========================================================================

  private handleResize(): void {
    const w = Math.max(this.container.clientWidth || window.innerWidth, 1);
    const h = Math.max(this.container.clientHeight || window.innerHeight, 1);
    const maxDpr = QUALITY_PRESETS[this.qualityPreset].maxDpr;
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, maxDpr));
    this.renderer.setSize(w, h);
    this.camController.resize(w, h);
  }

  private handleKeyDown(e: KeyboardEvent): void {
    if (this.matchPhase !== 'skydrop' && this.matchPhase !== 'playing') return;

    // Live Spectate Mode controls (Follow Cam cycling + Free-Form Drone flight + KeyF toggle; works with or without pointer lock!)
    if (this.spectateActive && !this.mapOpen) {
      const targetEl = e.target as HTMLElement | null;
      const isInput =
        targetEl instanceof HTMLInputElement ||
        targetEl instanceof HTMLTextAreaElement ||
        targetEl instanceof HTMLSelectElement;
      if (!isInput) {
        if (e.code === 'KeyF' && !e.repeat) {
          e.preventDefault();
          this.toggleSpectateMode();
          return;
        }
        if (this.spectateMode === 'free') {
          if (['Space', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.code)) {
            e.preventDefault();
          }
          this.keys.add(e.code);
          return;
        }
        if (!e.repeat) {
          if (e.code === 'KeyA' || e.code === 'ArrowLeft') {
            e.preventDefault();
            this.cycleSpectateTarget(-1);
            return;
          }
          if (e.code === 'KeyD' || e.code === 'ArrowRight') {
            e.preventDefault();
            this.cycleSpectateTarget(1);
            return;
          }
        }
      }
      return;
    }

    // Allow jumping from the Flying Google GBus via Space or E (even before pointer lock re-engages)
    if (
      !this.mapOpen &&
      this.player &&
      this.player.alive &&
      this.player.inBus &&
      !e.repeat &&
      (e.code === 'Space' || e.code === 'KeyE')
    ) {
      const targetEl = e.target as HTMLElement | null;
      const isInput =
        targetEl instanceof HTMLInputElement ||
        targetEl instanceof HTMLTextAreaElement ||
        targetEl instanceof HTMLSelectElement;
      if (!isInput) {
        const canDrop = Boolean(
          this.gbus &&
            this.gbus.active &&
            this.gbus.progress >= GAME_CONSTANTS.GBUS_DROP_UNLOCK_PROGRESS
        );
        if (canDrop) {
          e.preventDefault();
          this.ejectFromGBus(this.player);
        }
        return;
      }
    }

    if (this.mapOpen || !this.pointerLocked) return;
    if (['Space', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.code)) {
      e.preventDefault();
    }
    const alreadyDown = this.keys.has(e.code);
    this.keys.add(e.code);

    const p = this.player;
    if (!p || !p.alive || alreadyDown) return;

    if (e.code === 'Digit1') this.switchSlot(p, 0);
    else if (e.code === 'Digit2') this.switchSlot(p, 1);
    else if (e.code === 'Digit3') this.switchSlot(p, 2);
    else if (e.code === 'Digit4') this.switchSlot(p, 3);
    else if (e.code === 'Digit5') this.switchSlot(p, 4);
    else if (e.code === 'KeyR') this.startReload(p);
    else if (e.code === 'KeyE') this.tryPlayerInteract();
    else if (e.code === 'KeyQ') this.tryCastUltimate(p);
    else if (e.code === 'KeyC' && !p.skyDropping && !p.rewind.active) {
      if (p.ridingGBikeId !== null) {
        const bike = this.worldGBikes.find((b) => b.id === p.ridingGBikeId);
        if (bike && Math.abs(bike.speed) >= GAME_CONSTANTS.GBIKE_BAIL_SLIDE_MIN_SPEED) {
          this.dismountGBike(p, true);
        }
      } else if (p.sliding) {
        if (p.slideElapsed >= 0.15) {
          this.endSlide(p, false);
        }
      } else if (!this.isHealOrShieldChannel(p.channel)) {
        if (!this.tryStartSlide(p, false)) {
          this.crouchToggled = !this.crouchToggled;
        }
      }
    } else if (e.code === 'ControlLeft' && !p.skyDropping && !p.rewind.active && p.ridingGBikeId === null) {
      if (!p.sliding && !this.isHealOrShieldChannel(p.channel) && p.grounded) {
        this.ctrlSlideConsumed = true;
        this.tryStartSlide(p, true);
      }
    }
  }

  private handleKeyUp(e: KeyboardEvent): void {
    this.keys.delete(e.code);
    if (e.code === 'ControlLeft') {
      this.ctrlSlideConsumed = false;
    }
    if (!this.keys.has('ShiftLeft') && !this.keys.has('ShiftRight')) {
      this.sprintLatchedOnReload = false;
      this.sprintLatchedOnChannel = false;
      this.sprintLatchedOnSlide = false;
    }
  }

  private handleBlur(): void {
    this.keys.clear();
    this.mouseLeftDown = false;
    this.mouseRightDown = false;
    this.freeCamDragging = false;
    this.sprintLatchedOnReload = false;
    this.sprintLatchedOnChannel = false;
    this.sprintLatchedOnSlide = false;
    this.ctrlSlideConsumed = false;
  }

  private handleMouseDown(e: MouseEvent): void {
    if (this.matchPhase !== 'skydrop' && this.matchPhase !== 'playing') return;
    if (this.mapOpen) return;
    if (this.spectateActive) {
      if (this.spectateMode === 'free' && e.target === this.renderer.domElement) {
        this.audio.unlock();
        if (e.button === 0) {
          this.freeCamDragging = true;
          this.freeCamLastMouseX = e.clientX;
          this.freeCamLastMouseY = e.clientY;
          if (e.detail >= 2 && !this.pointerLocked) {
            this.requestPointerLock();
          }
        } else if (e.button === 2 && !this.pointerLocked) {
          this.requestPointerLock();
        }
      }
      return;
    }
    this.audio.unlock();
    if (!this.pointerLocked) {
      this.requestPointerLock();
      return;
    }
    if (e.button === 0) {
      this.mouseLeftDown = true;
      this.ifPlayerExists((p) => {
        p.semiAutoLatch = false;
        if (p.ridingGBikeId !== null) {
          this.tryRingGBikeBell(p);
        }
      });
    } else if (e.button === 2) {
      this.mouseRightDown = true;
    }
  }

  private handleMouseUp(e: MouseEvent): void {
    if (e.button === 0) {
      this.mouseLeftDown = false;
      this.freeCamDragging = false;
      this.ifPlayerExists((p) => {
        p.semiAutoLatch = false;
      });
    } else if (e.button === 2) {
      this.mouseRightDown = false;
    }
  }

  private handleMouseMove(e: MouseEvent): void {
    if (this.mapOpen) return;
    if (this.matchPhase !== 'skydrop' && this.matchPhase !== 'playing') return;

    // 6-DOF Free-Form Spectator Drone look (Pointer Lock OR click-and-drag)
    if (this.spectateActive && this.spectateMode === 'free') {
      let dx = 0;
      let dy = 0;
      if (this.pointerLocked) {
        dx = e.movementX;
        dy = e.movementY;
      } else if (this.freeCamDragging) {
        dx = e.clientX - this.freeCamLastMouseX;
        dy = e.clientY - this.freeCamLastMouseY;
        this.freeCamLastMouseX = e.clientX;
        this.freeCamLastMouseY = e.clientY;
      } else {
        return;
      }
      const sens = 0.0024 * this.mouseSensitivity;
      const pitchSign = this.invertY ? 1 : -1;
      this.freeCamYaw -= dx * sens;
      this.freeCamPitch = THREE.MathUtils.clamp(
        this.freeCamPitch + pitchSign * dy * sens,
        -1.48,
        1.48
      );
      return;
    }

    if (!this.pointerLocked || !this.player || !this.player.alive) return;

    const scoped = this.isPlayerSniperScoped();
    // Scaled smoothly for tighter 31° Ground ADS and 16° Longbow .308 Sniper Scope FOV + user sensitivity settings
    const sens = scoped
      ? 0.00056 * this.mouseSensitivity * this.adsSensitivity
      : this.player.isAds
        ? 0.00112 * this.mouseSensitivity * this.adsSensitivity
        : 0.00235 * this.mouseSensitivity;
    this.player.yaw -= e.movementX * sens;
    const pitchSign = this.invertY ? 1 : -1;
    this.player.pitch = THREE.MathUtils.clamp(
      this.player.pitch + pitchSign * e.movementY * sens,
      -1.15,
      1.15
    );
  }

  private handleWheel(e: WheelEvent): void {
    if (this.mapOpen || !this.pointerLocked || !this.player || !this.player.alive || this.player.skyDropping) return;
    const delta = Math.sign(e.deltaY);
    if (delta === 0) return;
    const next = (this.player.activeSlot + delta + 5) % 5;
    this.switchSlot(this.player, next);
  }

  private handlePointerLockChange(): void {
    const wasLocked = this.pointerLocked;
    this.pointerLocked = document.pointerLockElement === this.renderer.domElement;
    if (!this.pointerLocked) {
      this.keys.clear();
      this.mouseLeftDown = false;
      this.mouseRightDown = false;
      this.sprintLatchedOnReload = false;
      this.sprintLatchedOnChannel = false;
      this.sprintLatchedOnSlide = false;
      this.ctrlSlideConsumed = false;
    }
    if (!this.pointerLocked && (this.mapOpen || !wasLocked)) {
      return;
    }
    if (!this.pointerLocked && this.mpActive && this.matchElapsed < 0.75) {
      return;
    }
    this.callbacks.onPointerLockChange(this.pointerLocked);
  }

  private ifPlayerExists(fn: (p: Combatant) => void): void {
    if (this.player && this.player.alive) fn(this.player);
  }

  private lerpAngle(a: number, b: number, t: number): number {
    let diff = ((b - a + Math.PI * 3) % (Math.PI * 2)) - Math.PI;
    return a + diff * t;
  }

  // =========================================================================
  // MULTIPLAYER REAL-TIME SYNC, REMOTE INTERPOLATION & SERVER MESSAGE HANDLER
  // =========================================================================

  private packCombatantFlags(c: Combatant): number {
    let flags = 0;
    if (c.grounded) flags |= FLAG_GROUNDED;
    if (c.crouching) flags |= FLAG_CROUCHING;
    if (c.sprinting) flags |= FLAG_SPRINTING;
    if (c.sliding) flags |= FLAG_SLIDING;
    if (c.isAds) flags |= FLAG_ADS;
    if (c.isReloading) flags |= FLAG_RELOADING;
    if (c.skyDropping) flags |= FLAG_SKYDROPPING;
    if (c.rewind.active) flags |= FLAG_REWINDING;
    if (c.channel !== null) flags |= FLAG_CHANNELING;
    if (c.inBus) flags |= FLAG_IN_BUS;
    return flags;
  }

  private updateMultiplayerSync(dt: number): void {
    const client = this.mpClient;
    if (!client || !client.isConnected) return;
    if (this.matchPhase !== 'skydrop' && this.matchPhase !== 'playing') return;

    const nowMs = performance.now();
    // Expire any stale pending claims (> 2.5s) so failed/raced claims never lock out future retries
    if (this.mpPendingBikeClaimId && nowMs - this.mpPendingBikeClaimAt > 2500) {
      this.mpPendingBikeClaimId = null;
    }
    if (this.mpPendingLootClaims.size > 0) {
      for (const [id, ts] of this.mpPendingLootClaims.entries()) {
        if (nowMs - ts > 2500) {
          this.mpPendingLootClaims.delete(id);
        }
      }
    }

    // 1. Outbound Local Player State at 20 Hz (50ms)
    this.mpStateSendAccum += dt;
    if (this.mpStateSendAccum >= 0.05 && this.player && this.player.alive) {
      this.mpStateSendAccum = 0;
      const p = this.player;
      const slot = p.slots[p.activeSlot];
      const weaponId = slot && slot.kind === 'weapon' ? (slot.id as WeaponId) : null;
      const weaponRarity = slot && slot.kind === 'weapon' ? slot.rarity : null;
      const bike =
        p.ridingGBikeId !== null
          ? this.worldGBikes.find((b) => b.id === p.ridingGBikeId) ?? null
          : null;

      client.send({
        type: 'player_state',
        state: {
          x: Number(p.pos.x.toFixed(2)),
          y: Number(p.pos.y.toFixed(2)),
          z: Number(p.pos.z.toFixed(2)),
          vx: Number(p.vel.x.toFixed(2)),
          vy: Number(p.vel.y.toFixed(2)),
          vz: Number(p.vel.z.toFixed(2)),
          yaw: Number((bike ? bike.yaw : p.yaw).toFixed(3)),
          pitch: Number(p.pitch.toFixed(3)),
          flags: this.packCombatantFlags(p),
          weaponId,
          weaponRarity,
          bikeId: bike ? bike.id : null,
          bikeSteer: bike ? Number(bike.steerAngle.toFixed(3)) : undefined,
          bikeLean: bike ? Number(bike.leanAngle.toFixed(3)) : undefined,
          bikeSpeed: bike ? Number(bike.speed.toFixed(2)) : undefined,
        },
      });
    }

    // 2. Host Outbound AI Bot Batch at 10 Hz (100ms)
    if (this.isMpHost) {
      this.mpBotBatchAccum += dt;
      if (this.mpBotBatchAccum >= 0.1) {
        this.mpBotBatchAccum = 0;
        const bots: BotStateSample[] = [];
        for (const c of this.combatants) {
          if (c.isPlayer || c.isRemoteHuman || !c.alive) continue;
          const slot = c.slots[c.activeSlot];
          bots.push({
            id: c.id,
            x: Number(c.pos.x.toFixed(2)),
            y: Number(c.pos.y.toFixed(2)),
            z: Number(c.pos.z.toFixed(2)),
            vx: Number(c.vel.x.toFixed(2)),
            vz: Number(c.vel.z.toFixed(2)),
            yaw: Number(c.yaw.toFixed(3)),
            pitch: Number(c.pitch.toFixed(3)),
            flags: this.packCombatantFlags(c),
            hp: Math.round(c.health),
            sh: Math.round(c.shield),
            alive: c.alive,
            weaponId: slot && slot.kind === 'weapon' ? (slot.id as WeaponId) : null,
            weaponRarity: slot && slot.kind === 'weapon' ? slot.rarity : null,
          });
        }
        if (bots.length > 0) {
          client.send({ type: 'bot_batch', bots });
        }
      }
    }
  }

  private updateRemoteInterpolatedCombatant(c: Combatant, dt: number): void {
    const t = c.netTarget;
    if (!t) return;

    // Position interpolation (snap if > 8m teleport/rewind)
    const dx = t.x - c.pos.x;
    const dy = t.y - c.pos.y;
    const dz = t.z - c.pos.z;
    const distSq = dx * dx + dy * dy + dz * dz;
    if (distSq > 64) {
      c.pos.set(t.x, t.y, t.z);
    } else {
      const alpha = Math.min(1, dt * 16);
      c.pos.x += dx * alpha;
      c.pos.y += dy * alpha;
      c.pos.z += dz * alpha;
    }

    c.vel.set(t.vx, t.vy, t.vz);
    const prevYaw = c.yaw;
    c.yaw = this.lerpAngle(c.yaw, t.yaw, Math.min(1, dt * 16));
    c.pitch += (t.pitch - c.pitch) * Math.min(1, dt * 16);

    // Unpack stance & action bitmask flags
    const wasSkyDropping = c.skyDropping;
    const wasReloading = c.isReloading;
    const wasInBus = c.inBus;
    c.grounded = (t.flags & FLAG_GROUNDED) !== 0;
    c.crouching = (t.flags & FLAG_CROUCHING) !== 0;
    c.sprinting = (t.flags & FLAG_SPRINTING) !== 0;
    c.sliding = (t.flags & FLAG_SLIDING) !== 0;
    c.isAds = (t.flags & FLAG_ADS) !== 0;
    c.isReloading = (t.flags & FLAG_RELOADING) !== 0;
    c.skyDropping = (t.flags & FLAG_SKYDROPPING) !== 0;
    c.rewind.active = (t.flags & FLAG_REWINDING) !== 0;
    c.inBus = (t.flags & FLAG_IN_BUS) !== 0;

    if (c.inBus) {
      c.hero.root.visible = false;
      c.gliderMesh.visible = false;
      return;
    } else if (wasInBus && !c.inBus) {
      c.hero.root.visible = true;
      c.gliderMesh.visible = c.skyDropping;
    }

    if (!c.grounded && !c.skyDropping) {
      c.airborneTime += dt;
    } else {
      c.airborneTime = 0;
    }

    // Glider stow / bank / trail sync
    if (wasSkyDropping && !c.skyDropping) {
      c.gliderMesh.visible = false;
      c.glideBank = 0;
      c.glidePitch = 0;
      c.hero.model.rotation.x = 0;
      c.hero.model.rotation.z = 0;
      c.hero.gliderMount.rotation.set(0, 0, 0);
      if (c.weaponInstance) {
        c.weaponInstance.root.visible = c.ridingGBikeId === null;
      }
    } else if (c.skyDropping) {
      c.gliderMesh.visible = true;
      let yawDelta = c.yaw - prevYaw;
      yawDelta = ((yawDelta + Math.PI * 3) % (Math.PI * 2)) - Math.PI;
      const yawRate = THREE.MathUtils.clamp(yawDelta / Math.max(dt, 0.004), -4.5, 4.5);
      const targetBank = THREE.MathUtils.clamp(yawRate * 0.12, -0.28, 0.28);
      const targetPitch = c.sprinting ? -0.32 : -0.10;
      c.glideBank += (targetBank - c.glideBank) * Math.min(1, dt * 6);
      c.glidePitch += (targetPitch - c.glidePitch) * Math.min(1, dt * 6);
      c.gliderTrailTimer -= dt;
      if (c.gliderTrailTimer <= 0) {
        c.gliderTrailTimer = c.sprinting ? 0.06 : 0.12;
        this.vfx.spawnGliderTrail(new THREE.Vector3(c.pos.x, c.pos.y + 2.4, c.pos.z));
      }
    }

    // Reload animation timing sync
    if (!wasReloading && c.isReloading && t.weaponId) {
      c.reloadDuration = getWeaponReloadTime(t.weaponId, t.weaponRarity ?? 'common');
      c.reloadTimer = c.reloadDuration;
    } else if (c.isReloading) {
      c.reloadTimer = Math.max(0.05, c.reloadTimer - dt);
    }

    // Slide dust VFX for remote sliding friends
    if (c.sliding && c.grounded && !c.skyDropping) {
      c.slideVfxTimer -= dt;
      if (c.slideVfxTimer <= 0) {
        c.slideVfxTimer = 0.065;
        const speed = Math.hypot(c.vel.x, c.vel.z);
        const sdx = speed > 0.2 ? c.vel.x / speed : -Math.sin(c.yaw);
        const sdz = speed > 0.2 ? c.vel.z / speed : -Math.cos(c.yaw);
        this.tmpVecA.set(c.pos.x + sdx * 0.42, c.pos.y + 0.01, c.pos.z + sdz * 0.42);
        this.vfx.spawnSlideDust(this.tmpVecA, sdx, sdz, c.surface);
      }
    }

    // Docs Version History ghost trail VFX for remote rewinding friends
    if (c.rewind.active) {
      c.remoteRewindGhostTimer -= dt;
      if (c.remoteRewindGhostTimer <= 0) {
        c.remoteRewindGhostTimer = 0.06;
        this.vfx.spawnDocsGhostTrail(c.pos, c.yaw);
      }
    }

    // Equipped weapon visual sync
    if (t.weaponId) {
      const rarity = t.weaponRarity ?? 'common';
      const curSlot = c.slots[0];
      if (!curSlot || curSlot.kind !== 'weapon' || curSlot.id !== t.weaponId || curSlot.rarity !== rarity) {
        c.slots[0] = {
          kind: 'weapon',
          id: t.weaponId,
          rarity,
          ammo: WEAPONS[t.weaponId].magSize,
        };
      }
      c.activeSlot = 0;
    } else {
      c.slots[0] = null;
      c.activeSlot = 0;
    }
    this.syncEquippedWeaponVisual(c);

    // Sync Rideable GBike kinematics so remote friends pedal GBikes with full 2-bone IK!
    if (t.bikeId) {
      const bike = this.worldGBikes.find((b) => b.id === t.bikeId) ?? null;
      if (bike) {
        if (c.ridingGBikeId !== bike.id) {
          if (c.ridingGBikeId) {
            const oldBike = this.worldGBikes.find((b) => b.id === c.ridingGBikeId);
            if (oldBike && oldBike.riderId === c.id) oldBike.riderId = null;
          }
          c.ridingGBikeId = bike.id;
          bike.riderId = c.id;
          bike.parkTilt = 0;
          if (c.weaponInstance) {
            c.weaponInstance.root.visible = false;
          }
        }
        bike.x = c.pos.x;
        bike.y = c.pos.y;
        bike.z = c.pos.z;
        bike.yaw = c.yaw;
        bike.parkTilt = 0;
        bike.steerAngle += (t.bikeSteer - bike.steerAngle) * Math.min(1, dt * 14);
        bike.leanAngle += (t.bikeLean - bike.leanAngle) * Math.min(1, dt * 14);
        bike.speed += (t.bikeSpeed - bike.speed) * Math.min(1, dt * 14);
        bike.wheelSpin -= (bike.speed * dt) / 0.34;
        if (Math.abs(bike.speed) > 0.3) {
          bike.pedalSpin -= (bike.speed * dt) / 0.22;
        }
      }
    } else if (c.ridingGBikeId !== null) {
      const oldBike = this.worldGBikes.find((b) => b.id === c.ridingGBikeId);
      if (oldBike && oldBike.riderId === c.id) {
        oldBike.riderId = null;
      }
      c.ridingGBikeId = null;
      c.hero.root.rotation.set(0, c.yaw, 0);
      c.hero.model.position.set(0, 0, 0);
      c.hero.model.rotation.set(0, 0, 0);
      if (c.weaponInstance && !c.skyDropping) {
        c.weaponInstance.root.visible = true;
      }
    }

    // Enemy remote footsteps & Visual Sound Compass (crouching & teammates stay silent!)
    const horizSpeed = Math.hypot(c.vel.x, c.vel.z);
    if (
      c.grounded &&
      !c.skyDropping &&
      !c.crouching &&
      !c.sliding &&
      c.ridingGBikeId === null &&
      horizSpeed > 1.5 &&
      !this.isFriendly(this.player, c)
    ) {
      c.footstepTimer -= dt;
      if (c.footstepTimer <= 0) {
        c.footstepTimer = c.sprinting ? 0.30 : 0.42;
        this.pushSoundEvent(
          'footstep',
          c.pos.x,
          c.pos.z,
          c.sprinting ? 40 : 28,
          0.45,
          c.sprinting ? 0.95 : 0.72
        );
        const listenerPos = this.getCameraFocusPos();
        const dist = c.pos.distanceTo(listenerPos);
        if (dist <= 32) {
          this.audio.playFootstep(c.sprinting, false, c.surface, dist, this.computeSpatialPan(c.pos));
        }
      }
    }
  }

  private handleMpMessage(msg: ServerMessage): void {
    if (!this.mpActive) return;

    switch (msg.type) {
      case 'host_changed': {
        const wasHost = this.isMpHost;
        this.mpHostId = msg.hostId;
        if (!wasHost && this.isMpHost && this.world) {
          for (const c of this.combatants) {
            if (!c.isPlayer && !c.isRemoteHuman && c.alive) {
              if (!c.brain) {
                const profile = getBotProfile(c.botTier ?? 'tactical');
                c.brain = new BotBrain(profile, this.world.landmarks);
              }
              c.netTarget = undefined;
              c.aiThinkTimer = Math.random() * 0.1;
              c.cachedDecision = null;
            }
          }
          this.callbacks.onAnnouncement('HOST MIGRATED', 'You are now hosting match simulation');
        }
        break;
      }

      case 'peer_state':
        this.applyMpPeerState(msg.state);
        break;

      case 'bot_batch':
        if (!this.isMpHost) {
          this.applyMpBotBatch(msg.bots);
        }
        break;

      case 'fire_fx':
        this.handleMpFireFx(msg.event);
        break;

      case 'damage_event':
        this.handleMpDamageEvent(msg.event);
        break;

      case 'elim_event':
        this.handleMpElimEvent(msg.event);
        break;

      case 'vitals_update': {
        const c = this.combatants.find((item) => item.id === msg.combatantId);
        if (c && c.alive) {
          const gainedShield = msg.shield > c.shield + 1;
          const gainedHealth = msg.health > c.health + 1;
          c.health = msg.health;
          c.shield = msg.shield;
          if (msg.mana !== undefined && !c.isPlayer) {
            c.mana = msg.mana;
          }
          if (!c.isPlayer && (gainedShield || gainedHealth)) {
            this.vfx.spawnStatusBurst(c.pos, gainedShield ? 0x38bdf8 : 0x22c55e);
          }
        }
        break;
      }

      case 'ult_cast':
        this.handleMpUltCast(msg.event);
        break;

      case 'utility_throw':
        this.handleMpUtilityThrow(msg.event);
        break;

      case 'chest_opened': {
        this.mpPendingChestOpens.delete(msg.chestId);
        const chest = this.lootChests.find((ch) => ch.id === msg.chestId);
        if (chest && !chest.opened) {
          this.applyOpenedLootChest(chest, msg.openerId === this.mpSelfId, msg.loot);
        }
        break;
      }

      case 'supply_drop_opened': {
        this.mpPendingDropOpens.delete(msg.dropId);
        const drop = this.supplyDrops.find((sd) => sd.id === msg.dropId);
        if (drop && !drop.opened) {
          this.applyOpenedSupplyDrop(drop, msg.openerId === this.mpSelfId, msg.loot);
        }
        break;
      }

      case 'loot_claimed':
        this.handleMpLootClaimed(msg.lootId, msg.claimerId);
        break;

      case 'loot_spawned':
        for (const item of msg.items) {
          this.spawnLootDrop(
            item.x,
            item.y,
            item.z,
            item.kind,
            item.itemId as WeaponId | UtilityItemId,
            item.rarity,
            item.count ?? 1,
            undefined,
            item.id
          );
        }
        break;

      case 'bike_state':
        this.handleMpBikeState(msg);
        break;

      case 'bike_bell': {
        const bellPos = new THREE.Vector3(msg.x, msg.y, msg.z);
        const dist = bellPos.distanceTo(this.getCameraFocusPos());
        this.audio.playGBikeBell(dist, this.computeSpatialPan(bellPos));
        this.pushSoundEvent('gbike', msg.x, msg.z, 55, 0.55, 0.9);
        break;
      }

      case 'techstop_upgrade': {
        const fxPos = new THREE.Vector3(msg.x, msg.y, msg.z);
        this.vfx.spawnTechStopUpgrade(fxPos, msg.newRarity);
        const dist = fxPos.distanceTo(this.getCameraFocusPos());
        if (dist <= 45) {
          this.audio.playTechStopUpgrade(msg.newRarity);
        }
        break;
      }

      case 'match_end':
        this.handleMpMatchEnd(msg.result);
        break;

      default:
        break;
    }
  }

  private applyMpPeerState(state: PeerStateUpdate): void {
    const c = this.combatants.find((item) => item.id === state.id);
    if (!c || c.isPlayer || !c.alive) return;
    c.netTarget = {
      x: state.x,
      y: state.y,
      z: state.z,
      vx: state.vx,
      vy: state.vy,
      vz: state.vz,
      yaw: state.yaw,
      pitch: state.pitch,
      flags: state.flags,
      weaponId: state.weaponId ?? null,
      weaponRarity: state.weaponRarity ?? null,
      bikeId: state.bikeId ?? null,
      bikeSteer: state.bikeSteer ?? 0,
      bikeLean: state.bikeLean ?? 0,
      bikeSpeed: state.bikeSpeed ?? 0,
      receivedAt: performance.now(),
    };
  }

  private applyMpBotBatch(bots: BotStateSample[]): void {
    const now = performance.now();
    for (const sample of bots) {
      const c = this.combatants.find((item) => item.id === sample.id);
      if (!c || c.isPlayer || c.isRemoteHuman) continue;
      if (!sample.alive) {
        if (c.alive) {
          c.alive = false;
          c.health = 0;
          c.shield = 0;
          c.hero.root.visible = false;
        }
        continue;
      }
      c.health = sample.hp;
      c.shield = sample.sh;
      c.netTarget = {
        x: sample.x,
        y: sample.y,
        z: sample.z,
        vx: sample.vx,
        vy: 0,
        vz: sample.vz,
        yaw: sample.yaw,
        pitch: sample.pitch,
        flags: sample.flags,
        weaponId: sample.weaponId ?? null,
        weaponRarity: sample.weaponRarity ?? null,
        bikeId: null,
        bikeSteer: 0,
        bikeLean: 0,
        bikeSpeed: 0,
        receivedAt: now,
      };
    }
  }

  private handleMpFireFx(ev: FireFxEvent): void {
    const shooter = this.combatants.find((c) => c.id === ev.shooterId) ?? null;
    const origin = new THREE.Vector3(ev.ox, ev.oy, ev.oz);
    const end = new THREE.Vector3(ev.endX, ev.endY, ev.endZ);
    const listenerPos = this.getCameraFocusPos();

    if (ev.isExplosive) {
      const radius = ev.explosionRadius ?? 6.5;
      this.vfx.spawnExplosion(end, radius, 0xc084fc);
      const dist = end.distanceTo(listenerPos);
      this.audio.playExplosion(dist, this.computeSpatialPan(end));
      if (!this.isFriendly(this.player, shooter)) {
        this.pushSoundEvent('gunfire', end.x, end.z, 105, 0.85, 1.0);
      }
      if (this.player && this.player.alive && dist < 24) {
        this.camController.addShake(Math.max(0.05, (1 - dist / 24) * 0.28));
      }
      return;
    }

    if (shooter) {
      shooter.lastShotAt = this.matchElapsed;
    }

    const dir = end.clone().sub(origin);
    const len = dir.length();
    if (len > 0.01) {
      dir.divideScalar(len);
    } else {
      dir.set(0, 0, -1);
    }

    this.vfx.spawnMuzzleFlash(
      origin,
      dir,
      ev.weaponId === 'nova_gl40' ? 0xc084fc : 0xffd166,
      ev.weaponId === 'breaker_12g' || ev.weaponId === 'longbow_308' ? 1.4 : 0.95
    );

    const isSniper = ev.weaponId === 'longbow_308';
    const tracerColor =
      ev.weaponId === 'longbow_308'
        ? 0xfef08a
        : ev.weaponId === 'nova_gl40'
          ? 0xc084fc
          : WEAPONS[ev.weaponId]?.color ?? 0x60a5fa;
    this.vfx.spawnTracer(origin, end, tracerColor, isSniper ? 0.055 : 0.028, isSniper ? 0.28 : 0.095);

    const dist = origin.distanceTo(listenerPos);
    this.audio.playShot(ev.weaponId, dist, this.computeSpatialPan(origin));
    if (!this.isFriendly(this.player, shooter)) {
      this.pushSoundEvent(
        'gunfire',
        origin.x,
        origin.z,
        ev.weaponId === 'longbow_308' ? 120 : 95,
        0.65,
        1.0
      );
    }
  }

  private handleMpDamageEvent(ev: DamageEvent): void {
    const victim = this.combatants.find((c) => c.id === ev.targetId);
    if (!victim) return;
    const attacker = ev.attackerId ? this.combatants.find((c) => c.id === ev.attackerId) ?? null : null;

    const prevHealth = victim.health;
    const prevShield = victim.shield;
    victim.health = ev.newHealth;
    victim.shield = ev.newShield;
    victim.lastDamagedAt = this.matchElapsed;
    victim.recentDamageTaken += ev.amount;
    if (attacker && attacker.id !== victim.id) {
      victim.lastAttackerId = attacker.id;
    }

    if (ev.isStorm) {
      if (victim.isPlayer) {
        this.audio.playStormTick();
        this.callbacks.onDirectionalDamage({ bearingRad: Math.PI, amount: ev.amount, isStorm: true });
      }
      return;
    }

    const hitPoint =
      ev.hitX === 0 && ev.hitY === 0 && ev.hitZ === 0
        ? new THREE.Vector3(victim.pos.x, victim.pos.y + 1.1, victim.pos.z)
        : new THREE.Vector3(ev.hitX, ev.hitY, ev.hitZ);

    const shieldAbsorbed = Math.max(0, prevShield - ev.newShield);
    const hpLoss = Math.max(0, prevHealth - ev.newHealth);
    const shieldHit = shieldAbsorbed > 0 || ev.shieldBroken;

    victim.hero.flashHit(ev.headshot ? 0xfbbf24 : shieldHit ? 0x38bdf8 : 0xef4444, 0.72);
    victim.hitFlashTimer = 0.11;
    this.vfx.spawnHitImpact(hitPoint, {
      isShield: shieldHit,
      isHeadshot: ev.headshot,
    });

    if (ev.shieldBroken) {
      this.vfx.spawnShieldBreak(victim.pos);
      const isDirect = Boolean(ev.attackerId === this.mpSelfId || victim.isPlayer);
      const dist = victim.pos.distanceTo(this.getCameraFocusPos());
      this.audio.playShieldCrack(dist, isDirect, isDirect ? 0 : this.computeSpatialPan(victim.pos));
      if (victim.isPlayer) {
        this.callbacks.onPlayerShieldBreak?.();
        this.camController.addShake(0.18);
      }
    }

    // Attacker feedback for local player
    if (ev.attackerId === this.mpSelfId && ev.targetId !== this.mpSelfId && this.player) {
      this.player.damageDealt += ev.amount;
      if (ev.headshot) this.player.headshots++;
      const killed = ev.newHealth <= 0;
      this.audio.playHitmarker(ev.headshot, shieldAbsorbed > 0 && hpLoss === 0);
      this.callbacks.onHitMarker(ev.headshot, killed, ev.shieldBroken);

      const screen = this.projectWorldToScreen(hitPoint);
      if (screen) {
        this.callbacks.onFloatingDamage({
          screenX: screen.x,
          screenY: screen.y,
          amount: ev.amount,
          kind: ev.headshot ? 'headshot' : shieldAbsorbed > hpLoss ? 'shield' : 'health',
          worldX: hitPoint.x,
          worldY: hitPoint.y,
          worldZ: hitPoint.z,
        });
      }
    }

    // Victim directional damage arc & shake for local player
    if (victim.isPlayer && attacker && attacker.id !== victim.id) {
      const dx = attacker.pos.x - victim.pos.x;
      const dz = attacker.pos.z - victim.pos.z;
      const fx = -Math.sin(victim.yaw);
      const fz = -Math.cos(victim.yaw);
      const rx = Math.cos(victim.yaw);
      const rz = -Math.sin(victim.yaw);
      const bearingRad = Math.atan2(dx * rx + dz * rz, dx * fx + dz * fz);
      this.callbacks.onDirectionalDamage({ bearingRad, amount: ev.amount, isStorm: false });
      this.camController.addShake(Math.min(0.24, 0.06 + ev.amount * 0.003));
    }
  }

  private handleMpElimEvent(ev: ElimEvent): void {
    this.mpAliveTeams = ev.aliveTeams;
    const victim = this.combatants.find((c) => c.id === ev.victimId);
    const killer = ev.killerId ? this.combatants.find((c) => c.id === ev.killerId) ?? null : null;

    if (victim && victim.alive) {
      if (victim.ridingGBikeId) {
        this.dismountGBike(victim, false, false);
      }
      if (victim.sliding) {
        this.endSlide(victim, false);
      }
      victim.alive = false;
      victim.health = 0;
      victim.shield = 0;
      victim.channel = null;
      if (victim.isPlayer) {
        this.sprintLatchedOnChannel = false;
        this.sprintLatchedOnSlide = false;
        this.ctrlSlideConsumed = false;
      }
      victim.sprinting = false;
      this.cancelReload(victim);
      victim.hero.root.visible = false;

      this.vfx.spawnExplosion(
        new THREE.Vector3(victim.pos.x, victim.pos.y + 1.0, victim.pos.z),
        2.6,
        HERO_MAP[victim.heroId].hexPrimary
      );

      // Authoritative death loot broadcast: local victim drops their own gear; Host drops AI bot gear
      const ownsDeathDrop =
        victim.isPlayer || (this.isMpHost && !victim.isRemoteHuman);
      if (ownsDeathDrop) {
        let bestWeapon: InventorySlot | null = null;
        const carriedItems: InventorySlot[] = [];
        const rarityRank: Record<Rarity, number> = { common: 1, rare: 2, epic: 3 };
        for (const s of victim.slots) {
          if (!s) continue;
          if (s.kind === 'weapon') {
            if (!bestWeapon || rarityRank[s.rarity] > rarityRank[bestWeapon.rarity]) {
              bestWeapon = s;
            }
          } else if ((s.count ?? 0) > 0) {
            carriedItems.push(s);
          }
        }
        carriedItems.sort((a, b) => rarityRank[b.rarity] - rarityRank[a.rarity]);

        const deathDrops: { kind: 'weapon' | 'item'; id: WeaponId | UtilityItemId; rarity: Rarity; count: number }[] = [];
        if (bestWeapon) {
          deathDrops.push({ kind: 'weapon', id: bestWeapon.id, rarity: bestWeapon.rarity, count: 1 });
        }
        for (const it of carriedItems.slice(0, 2)) {
          deathDrops.push({ kind: 'item', id: it.id, rarity: it.rarity, count: it.count ?? 1 });
        }

        if (deathDrops.length > 0) {
          const groundY = this.physics.getSupportHeight(victim.pos.x, victim.pos.z, victim.pos.y + 1, 0.3, 0.5);
          const syncedItems: SyncedGroundLoot[] = [];
          deathDrops.forEach((d, idx) => {
            const ang = (idx / Math.max(1, deathDrops.length)) * Math.PI * 2 + 0.4;
            const dist = deathDrops.length === 1 ? 0.5 : 0.95;
            const dx = Number((victim.pos.x + Math.cos(ang) * dist).toFixed(2));
            const dz = Number((victim.pos.z + Math.sin(ang) * dist).toFixed(2));
            const rawDy = this.physics.getSupportHeight(dx, dz, victim.pos.y + 1, 0.3, 0.5);
            const dy = Number((Math.abs(rawDy - groundY) <= 1.2 ? rawDy : groundY).toFixed(2));
            const lootId = `death_${victim.id}_${idx}`;
            this.spawnLootDrop(dx, dy, dz, d.kind, d.id, d.rarity, d.count, undefined, lootId);
            syncedItems.push({
              id: lootId,
              kind: d.kind,
              itemId: d.id,
              rarity: d.rarity,
              count: d.count,
              x: dx,
              y: dy,
              z: dz,
            });
          });
          this.mpClient?.send({ type: 'loot_spawn', items: syncedItems });
        }
      }
    }

    if (killer && victim && killer.id !== victim.id) {
      killer.eliminations++;
      killer.mana = Math.min(GAME_CONSTANTS.MAX_MANA, killer.mana + GAME_CONSTANTS.ELIM_MANA_BONUS);
      this.audio.playElimination(killer.isPlayer);
    } else {
      this.audio.playElimination(false);
    }

    if (victim) {
      this.callbacks.onKillFeed({
        id: this.nextKillFeedSeq++,
        killer: ev.isStorm ? 'Googleplex Storm' : killer ? killer.name : 'Campus Hazard',
        killerHero: killer ? killer.heroId : victim.heroId,
        victim: victim.name,
        victimHero: victim.heroId,
        weapon: ev.weaponName,
        headshot: ev.headshot,
        isUltimate: ev.isUltimate,
        isStorm: ev.isStorm,
        timestamp: this.matchElapsed,
      });
    }

    // If we were spectating the eliminated combatant, auto-advance to next alive target
    if (this.spectateActive && this.spectateTargetId === ev.victimId) {
      const next = this.pickBestSpectateTarget(ev.killerId);
      if (next) {
        this.camController.reset(next.pos, next.yaw);
      }
    }

    // Local player eliminated while match is still ongoing -> show Eliminated modal with "Spectate Match"
    const matchOngoing =
      this.mpFormat === 'teams' ? ev.aliveTeams > 1 : ev.aliveCount > 1;
    if (victim?.isPlayer && matchOngoing && this.player) {
      this.mapOpen = false;
      this.mouseLeftDown = false;
      this.mouseRightDown = false;
      this.keys.clear();
      this.audio.setGliderWind(false);
      if (document.pointerLockElement === this.renderer.domElement) {
        document.exitPointerLock();
      }
      this.audio.playDefeat();
      const heroDef = HERO_MAP[this.player.heroId];
      const summary: MatchSummary = {
        won: false,
        placement: ev.placement,
        totalPlayers: this.combatants.length,
        heroId: this.player.heroId,
        heroName: heroDef.productName,
        heroPersona: heroDef.personaName,
        eliminations: this.player.eliminations,
        headshots: this.player.headshots,
        damageDealt: Math.round(this.player.damageDealt),
        survivedSeconds: Math.round(this.matchElapsed),
        botDifficulty: this.activeBotDifficulty,
        gameMode: this.activeGameMode,
        isMultiplayer: true,
        matchOngoing: true,
        teamId: this.mpTeamId,
      };
      this.emitHudSnapshot();
      this.callbacks.onMatchEnd(summary);
    }
  }

  private handleMpUltCast(ev: UltCastEvent): void {
    const caster = this.combatants.find((c) => c.id === ev.casterId) ?? null;
    const castPos = new THREE.Vector3(ev.x, ev.y, ev.z);
    const dist = castPos.distanceTo(this.getCameraFocusPos());
    this.audio.playUltimate(ev.heroId, dist, this.computeSpatialPan(castPos));
    if (!this.isFriendly(this.player, caster)) {
      this.pushSoundEvent('gunfire', ev.x, ev.z, 105, 0.85, 1.0);
    }

    switch (ev.heroId) {
      case 'gmail':
        if (caster) {
          this.castGmailReplyAll(caster, true);
        }
        break;
      case 'drive':
        if (caster) {
          this.castDriveAccessRevoked(caster, true);
        } else {
          const visual = this.vfx.createDriveGuardrailDome(castPos, 12.0);
          this.guardrailZones.push({
            ownerId: ev.casterId,
            center: castPos,
            radius: 12.0,
            elapsed: 0,
            duration: 6.0,
            visual,
          });
        }
        break;
      case 'calendar':
        if (caster) {
          this.castCalendarHardStop(caster);
        } else {
          const visual = this.vfx.createCalendarChronoField(castPos, 20.0);
          this.chronoZones.push({
            ownerId: ev.casterId,
            center: castPos,
            radius: 20.0,
            elapsed: 0,
            duration: 6.0,
            visual,
          });
        }
        break;
      case 'chat':
        if (caster) {
          this.castChatPingOverload(caster, true);
        } else {
          this.vfx.spawnChatPingWave(castPos, 28.0);
        }
        break;
      case 'slides': {
        const origin = new THREE.Vector3(ev.x, ev.y + 1.4, ev.z);
        const dir =
          ev.targetX !== undefined && ev.targetY !== undefined && ev.targetZ !== undefined
            ? new THREE.Vector3(ev.targetX - origin.x, ev.targetY - origin.y, ev.targetZ - origin.z)
            : new THREE.Vector3(-Math.sin(ev.yaw), 0, -Math.cos(ev.yaw));
        if (dir.lengthSq() < 0.001) {
          dir.set(-Math.sin(ev.yaw), 0, -Math.cos(ev.yaw));
        } else {
          dir.normalize();
        }
        this.vfx.spawnSlidesChargeBeam(origin, dir, 85, 0.3);
        this.pendingBeams.push({
          ownerId: ev.casterId,
          origin,
          dir,
          remaining: 0.3,
          visualOnly: true,
        });
        break;
      }
      case 'docs':
        this.vfx.spawnDocsRedlinePulse(castPos, 12.0);
        break;
    }
  }

  private handleMpLootClaimed(lootId: string, claimerId: string): void {
    this.mpPendingLootClaims.delete(lootId);
    const idx = this.lootDrops.findIndex((l) => l.id === lootId);
    if (idx < 0) return;
    const loot = this.lootDrops[idx];

    const claimer = this.combatants.find((c) => c.id === claimerId) ?? null;
    if (claimer && (claimer.isPlayer || (this.isMpHost && !claimer.isRemoteHuman))) {
      this.applyClaimedLootToCombatant(claimer, loot);
    } else {
      this.scene.remove(loot.visual.root);
      this.lootDrops.splice(idx, 1);
    }
  }

  private handleMpBikeState(
    msg: Extract<ServerMessage, { type: 'bike_state' }>
  ): void {
    const bike = this.worldGBikes.find((b) => b.id === msg.bikeId);
    if (!bike) return;

    if (msg.riderId !== null) {
      if (this.mpPendingBikeClaimId === msg.bikeId) {
        this.mpPendingBikeClaimId = null;
        if (msg.riderId !== this.mpSelfId) {
          this.callbacks.onAnnouncement('GBIKE TAKEN', 'Another player claimed this GBike');
        }
      }
      if (msg.riderId === this.mpSelfId && this.player && this.player.alive) {
        if (this.player.ridingGBikeId !== bike.id) {
          bike.riderId = null;
          this.mountGBike(this.player, bike);
        }
      } else {
        const rider = this.combatants.find((c) => c.id === msg.riderId) ?? null;
        bike.riderId = msg.riderId;
        bike.parkTilt = 0;
        if (rider) {
          rider.ridingGBikeId = bike.id;
          if (rider.weaponInstance) {
            rider.weaponInstance.root.visible = false;
          }
        }
      }
    } else {
      if (bike.riderId) {
        const oldRider = this.combatants.find((c) => c.id === bike.riderId) ?? null;
        if (oldRider && !oldRider.isPlayer && oldRider.ridingGBikeId === bike.id) {
          oldRider.ridingGBikeId = null;
          oldRider.hero.root.rotation.set(0, oldRider.yaw, 0);
          oldRider.hero.model.position.set(0, 0, 0);
          oldRider.hero.model.rotation.set(0, 0, 0);
          if (oldRider.weaponInstance && !oldRider.skyDropping) {
            oldRider.weaponInstance.root.visible = true;
          }
        }
      }
      bike.riderId = null;
      if (msg.x !== undefined && msg.y !== undefined && msg.z !== undefined) {
        bike.x = msg.x;
        bike.y = msg.y;
        bike.z = msg.z;
      }
      if (msg.yaw !== undefined) {
        bike.yaw = msg.yaw;
      }
      if (msg.speed !== undefined) {
        bike.speed = msg.speed;
      }
    }
  }

  private handleMpMatchEnd(result: MatchEndPayload): void {
    this.spectateActive = false;
    this.spectateTargetId = null;
    this.matchPhase = 'ended';
    this.mapOpen = false;
    this.mouseLeftDown = false;
    this.mouseRightDown = false;
    this.sprintLatchedOnReload = false;
    this.sprintLatchedOnChannel = false;
    this.sprintLatchedOnSlide = false;
    this.ctrlSlideConsumed = false;
    this.keys.clear();
    this.audio.setGliderWind(false);
    if (document.pointerLockElement === this.renderer.domElement) {
      document.exitPointerLock();
    }

    const selfRank = result.rankings.find((r) => r.id === this.mpSelfId) ?? null;
    const won =
      this.mpFormat === 'teams'
        ? Boolean(this.mpTeamId && result.winnerTeamId && result.winnerTeamId === this.mpTeamId)
        : result.winnerId === this.mpSelfId;

    if (won) {
      this.audio.playVictory();
    } else {
      this.audio.playDefeat();
    }

    const heroId = this.player?.heroId ?? 'gmail';
    const heroDef = HERO_MAP[heroId];
    const summary: MatchSummary = {
      won,
      placement: selfRank?.placement ?? (won ? 1 : result.totalPlayers),
      totalPlayers: result.totalPlayers || this.combatants.length,
      heroId,
      heroName: heroDef.productName,
      heroPersona: heroDef.personaName,
      eliminations: selfRank?.eliminations ?? this.player?.eliminations ?? 0,
      headshots: selfRank?.headshots ?? this.player?.headshots ?? 0,
      damageDealt: Math.round(selfRank?.damageDealt ?? this.player?.damageDealt ?? 0),
      survivedSeconds: result.survivedSeconds || Math.round(this.matchElapsed),
      botDifficulty: this.activeBotDifficulty,
      gameMode: this.activeGameMode,
      isMultiplayer: true,
      matchOngoing: false,
      teamId: this.mpTeamId,
      winnerTeamId: result.winnerTeamId,
      winnerName: result.winnerName,
    };

    this.emitHudSnapshot();
    this.callbacks.onMatchEnd(summary);
  }

  public dispose(): void {
    this.disposed = true;
    this.detachMpSessionState();
    this.sprintLatchedOnReload = false;
    this.sprintLatchedOnChannel = false;
    this.sprintLatchedOnSlide = false;
    this.ctrlSlideConsumed = false;
    cancelAnimationFrame(this.rafId);
    this.stopSplashAttract();
    window.removeEventListener('resize', this.onResizeBound);
    window.removeEventListener('keydown', this.onKeyDownBound);
    window.removeEventListener('keyup', this.onKeyUpBound);
    window.removeEventListener('mouseup', this.onMouseUpBound);
    window.removeEventListener('mousemove', this.onMouseMoveBound);
    window.removeEventListener('wheel', this.onWheelBound);
    window.removeEventListener('blur', this.onBlurBound);
    this.renderer.domElement.removeEventListener('mousedown', this.onMouseDownBound);
    this.renderer.domElement.removeEventListener('contextmenu', this.onContextMenuBound);
    document.removeEventListener('pointerlockchange', this.onPointerLockChangeBound);

    this.clearMatchEntities();
    this.world?.dispose();
    this.audio.dispose();
    this.renderer.dispose();
    if (this.renderer.domElement.parentElement === this.container) {
      this.container.removeChild(this.renderer.domElement);
    }
  }
}

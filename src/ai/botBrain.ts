import * as THREE from 'three';
import {
  BotDifficultyProfile,
  ChestTier,
  InventorySlot,
  LandmarkInfo,
  ProductHeroId,
  Rarity,
  UtilityItemId,
  WeaponId,
} from '../types';
import { GAME_CONSTANTS, HERO_MAP, RARITY_CONFIG, UTILITY_ITEMS, WEAPONS } from '../data/catalog';

export type BotStateName =
  | 'SKY_DROP'
  | 'HUNT_CHEST'
  | 'LOOT_UPGRADE'
  | 'ROTATE_SAFE_ZONE'
  | 'CONTEST_SUPPLY_DROP'
  | 'COMBAT_ENGAGE'
  | 'RETREAT_AND_HEAL';

export interface BotCombatantSnapshot {
  id: string;
  alive: boolean;
  skyDropping: boolean;
  heroId: ProductHeroId;
  pos: THREE.Vector3;
  vel: THREE.Vector3;
  yaw: number;
  health: number;
  shield: number;
  mana: number;
  crouching: boolean;
  channeling: boolean;
  silencedSec: number;
  blindedSec: number;
  ultCooldown: number;
  slots: (InventorySlot | null)[];
  activeSlot: number;
  isReloading: boolean;
  lastDamagedAt: number;
  lastAttackerId: string | null;
  recentDamageTaken: number;
  docsHistoryHealth: number;
  docsHistoryShield: number;
  revealedAllSec: number;
}

export interface BotLootSnapshot {
  id: string;
  x: number;
  y: number;
  z: number;
  kind: 'weapon' | 'item';
  itemId: WeaponId | UtilityItemId;
  rarity: Rarity;
  droppedById?: string;
  droppedAt?: number;
}

export interface BotChestSnapshot {
  id: string;
  x: number;
  y: number;
  z: number;
  tier: ChestTier;
  opened: boolean;
}

export interface BotSupplyDropSnapshot {
  id: string;
  x: number;
  y: number;
  z: number;
  landed: boolean;
  opened: boolean;
}

export interface BotWorldContext {
  time: number;
  dt: number;
  combatants: BotCombatantSnapshot[];
  lootDrops: BotLootSnapshot[];
  chests: BotChestSnapshot[];
  supplyDrops: BotSupplyDropSnapshot[];
  landmarks: LandmarkInfo[];
  stormCenterX: number;
  stormCenterZ: number;
  stormRadius: number;
  nextStormCenterX: number;
  nextStormCenterZ: number;
  nextStormRadius: number;
  stormShrinkInSec: number;
  hasLineOfSight: (from: THREE.Vector3, to: THREE.Vector3) => boolean;
}

export interface BotDecision {
  state: BotStateName;
  moveX: number; // world-space desired horizontal direction X (-1..1)
  moveZ: number; // world-space desired horizontal direction Z (-1..1)
  sprint: boolean;
  crouch: boolean;
  jump: boolean;
  dive: boolean; // glider fast dive during SKY_DROP
  aimYaw: number;
  aimTargetPoint: THREE.Vector3 | null;
  desiredSlot: number;
  fire: boolean;
  useItem: boolean;
  useUltimate: boolean;
  interactSupplyDropId: string | null;
  interactChestId: string | null;
  pickupLootId: string | null;
}

const RARITY_SCORE: Record<Rarity, number> = {
  common: 1,
  rare: 2.1,
  epic: 3.4,
};

export const BOT_DROP_IGNORE_SEC = 12.0;
export const BOT_UTILITY_SWAP_HYSTERESIS = 8;

const BOT_UTILITY_BASE_VALUE: Record<UtilityItemId, number> = {
  shield_jug: 38,
  medkit: 36,
  shield_drop: 34,
  regen_pod: 34,
  shield_cell: 30,
  frag_grenade: 28,
  flashbang: 24,
  hardlight_cover: 22,
  impulse_booster: 18,
  mana_elixir: 16,
};

export function getBotUtilityValue(itemId: UtilityItemId, rarity: Rarity): number {
  return (BOT_UTILITY_BASE_VALUE[itemId] ?? 15) + RARITY_SCORE[rarity] * 10;
}

function gaussianApprox(): number {
  return (Math.random() + Math.random() + Math.random() - 1.5) * 0.9;
}

function clamp(v: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, v));
}

function yawToward(fromX: number, fromZ: number, toX: number, toZ: number): number {
  // Yaw=0 faces -Z; forward vector is (-sin(yaw), 0, -cos(yaw))
  return Math.atan2(-(toX - fromX), -(toZ - fromZ));
}

function pointInPolyXZ(x: number, z: number, poly: readonly [number, number][]): boolean {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const xi = poly[i][0];
    const zi = poly[i][1];
    const xj = poly[j][0];
    const zj = poly[j][1];
    const intersect = zi > z !== zj > z && x < ((xj - xi) * (z - zi)) / (zj - zi + 1e-9) + xi;
    if (intersect) inside = !inside;
  }
  return inside;
}

interface OfficeInteriorZone {
  id: string;
  centerX: number;
  centerZ: number;
  poly: readonly [number, number][];
  /** Ground-floor open lobby/portal centers (Three.js XZ) that bots can route freely through */
  doorways: readonly [number, number][];
}

function makeShorelineEastInterior(
  id: string,
  cx: number,
  cz: number,
  rotY: number
): OfficeInteriorZone {
  const cos = Math.cos(rotY);
  const sin = Math.sin(rotY);
  const toW = (lx: number, lz: number): [number, number] => [
    cx + lx * cos + lz * sin,
    cz - lx * sin + lz * cos,
  ];
  const localPoly: [number, number][] = [
    [-27, 22],
    [27, 22],
    [33, 16],
    [33, -16],
    [27, -22],
    [-27, -22],
    [-33, -16],
    [-33, 16],
  ];
  const localDoors: [number, number][] = [
    [0, 22],
    [33, 0],
    [0, -22],
    [-33, 0],
  ];
  return {
    id,
    centerX: cx,
    centerZ: cz,
    poly: localPoly.map(([lx, lz]) => toW(lx, lz)),
    doorways: localDoors.map(([lx, lz]) => toW(lx, lz)),
  };
}

// Playable hollow office ground floors across the full 3× Mountain View campus:
// Core Quad (B40–B43, Gradient Canopy) + Outer Ring (Google 2000/1950, Charleston Campus, 1098 Alta, Shoreline East).
// Exact doorway portal midpoints matching build_map.py, build_expanded_landmarks.py & googleplex.ts!
const OFFICE_INTERIOR_ZONES: OfficeInteriorZone[] = [
  {
    id: 'b40',
    centerX: -41,
    centerZ: -21,
    poly: [
      [-85.14, -17.9],
      [-61.69, -10.31],
      [-26.52, -4.1],
      [-1.0, -7.55],
      [3.14, -19.28],
      [-18.24, -28.93],
      [-49.97, -37.9],
      [-83.07, -34.45],
    ],
    doorways: [
      [-79.33, -16.02], // edge[0]: West Courtyard lobby (6.2m)
      [-34.02, -5.43],  // edge[1]: Charlie's Café South Lobby facing Stan Plaza (7.2m)
      [1.03, -13.30],   // edge[3]: East Partner Plex facing Charleston Park (6.0m)
      [-66.58, -36.17], // edge[6]: North Amphitheatre Pkwy lobby (7.0m)
    ],
  },
  {
    id: 'b41',
    centerX: -112,
    centerZ: -31,
    poly: [
      [-128.55, -26.52],
      [-118.21, -12.72],
      [-102.34, -16.86],
      [-92.69, -38.93],
      [-111.31, -49.28],
      [-129.93, -41.69],
    ],
    doorways: [
      [-110.28, -14.80], // edge[1]: South Courtyard overhang (6.6m)
      [-102.00, -44.10], // edge[3]: NE Amphitheatre Pkwy lobby (6.5m)
      [-129.24, -34.12], // edge[5]: West Permanente Creek lobby (6.0m)
    ],
  },
  {
    id: 'b42',
    centerX: -117,
    centerZ: 23,
    poly: [
      [-132.52, 24.38],
      [-129.76, 43.0],
      [-108.38, 43.69],
      [-100.79, 23.0],
      [-106.31, 3.0],
      [-131.14, 4.38],
    ],
    doorways: [
      [-103.56, 12.98], // edge[3]: East Volleyball overhang (7.0m)
      [-119.12, 43.35], // edge[1]: South Charleston Rd lobby (6.5m)
      [-131.83, 14.36], // edge[5]: West Permanente Creek lobby (6.0m)
    ],
  },
  {
    id: 'b43',
    centerX: -58,
    centerZ: 33,
    poly: [
      [-99.38, 41.62],
      [-51.1, 48.52],
      [-16.62, 47.83],
      [-24.9, 25.76],
      [-64.9, 17.48],
      [-98.0, 20.93],
    ],
    doorways: [
      [-86.78, 19.76], // edge[4]: NW Volleyball overhang, west of Skybridge (7.0m)
      [-52.81, 19.99], // edge[3]: NE Courtyard facing Stan Plaza (7.0m)
      [-20.75, 36.83], // edge[2]: East SE Parking / Charleston Park (6.5m)
      [-75.13, 45.09], // edge[0]: South Charleston Rd lobby (7.0m)
    ],
  },
  {
    id: 'gradient_canopy',
    centerX: 113,
    centerZ: 4,
    poly: [
      [78, -32],
      [148, -32],
      [148, 40],
      [78, 40],
    ],
    doorways: [
      [78.8, 4.0],     // West Joaquin / Huddle portal (13.6m)
      [147.2, 4.0],    // East Shoreline portal (13.6m)
      [113.0, -32.2],  // North Amphitheatre portal (13.6m)
      [113.0, 40.2],   // South Visitor Plaza portal (13.6m)
    ],
  },
  // --- Expanded 3× Mountain View Campus Hollow Offices ---
  {
    id: 'google_2000_north',
    centerX: -225,
    centerZ: -26,
    poly: [
      [-264, -15],
      [-235, -11],
      [-189, -13],
      [-185, -37],
      [-229, -42],
      [-265, -36],
    ],
    doorways: [
      [-217.52, -11.76], // South Courtyard lobby
      [-186.99, -25.08], // East Creek lobby
      [-247.25, -38.96], // North Amphitheatre lobby
    ],
  },
  {
    id: 'google_1950_south',
    centerX: -224,
    centerZ: 30,
    poly: [
      [-256, 34],
      [-213, 45],
      [-185, 42],
      [-187, 17],
      [-237, 15],
      [-264, 20],
    ],
    doorways: [
      [-199.58, 43.56], // South Charleston Rd lobby
      [-185.98, 29.79], // East Creek lobby
      [-208.48, 16.14], // North Courtyard lobby
    ],
  },
  {
    id: 'charleston_west',
    centerX: -16.5,
    centerZ: 134,
    poly: [
      [-27, 161],
      [-6, 161],
      [-6, 107],
      [-27, 107],
    ],
    doorways: [
      [-16.5, 161],
      [-6, 134.4],
      [-16.5, 107],
    ],
  },
  {
    id: 'charleston_north',
    centerX: 37.5,
    centerZ: 112,
    poly: [
      [9, 121],
      [66, 121],
      [66, 103],
      [9, 103],
    ],
    doorways: [
      [30.5, 121],
      [40.5, 103],
      [9, 112],
    ],
  },
  {
    id: 'charleston_south',
    centerX: 37.5,
    centerZ: 156,
    poly: [
      [9, 165],
      [66, 165],
      [66, 147],
      [9, 147],
    ],
    doorways: [
      [34.5, 165],
      [24.5, 147],
      [9, 156],
    ],
  },
  {
    id: 'charleston_east_spine',
    centerX: 57.5,
    centerZ: 134,
    poly: [
      [49, 145],
      [66, 145],
      [66, 123],
      [49, 123],
    ],
    doorways: [
      [57.5, 145],
      [57.5, 123],
      [49, 134],
    ],
  },
  {
    id: 'alta_nw',
    centerX: -125.5,
    centerZ: 108.5,
    poly: [
      [-146, 118],
      [-105, 118],
      [-105, 99],
      [-146, 99],
    ],
    doorways: [
      [-126.5, 118],
      [-105, 108.5],
      [-124.5, 99],
    ],
  },
  {
    id: 'alta_sw',
    centerX: -125.5,
    centerZ: 143.5,
    poly: [
      [-146, 153],
      [-105, 153],
      [-105, 134],
      [-146, 134],
    ],
    doorways: [
      [-126.5, 153],
      [-105, 143.5],
      [-127.5, 134],
    ],
  },
  {
    id: 'alta_east',
    centerX: -79.5,
    centerZ: 126,
    poly: [
      [-89, 151],
      [-70, 151],
      [-70, 101],
      [-89, 101],
    ],
    doorways: [
      [-79.5, 151],
      [-79.5, 101],
      [-89, 126],
    ],
  },
  makeShorelineEastInterior('google_2015', 234, -22, 0),
  makeShorelineEastInterior('google_cl2', 236, -140, Math.PI),
  makeShorelineEastInterior('google_1395', 234, 122, 0.06),
];

/**
 * Multi-tier data-driven Bot AI Finite State Machine (Spec §6 & §16).
 * States: SKY_DROP | LOOT_UPGRADE | ROTATE_SAFE_ZONE | CONTEST_SUPPLY_DROP | COMBAT_ENGAGE | RETREAT_AND_HEAL
 */
export class BotBrain {
  public readonly profile: BotDifficultyProfile;
  public state: BotStateName = 'SKY_DROP';

  private dropTarget = new THREE.Vector3(-51, 0, 4);
  private roamTarget = new THREE.Vector3(0, 0, 0);
  private roamTimer = 0;

  private currentTargetId: string | null = null;
  private targetAcquiredAt = 0;
  private strafeDir = Math.random() < 0.5 ? 1 : -1;
  private strafeFlipTimer = 1.2 + Math.random() * 1.4;
  private crouchDecision = false;
  private crouchFlipTimer = 1.4 + Math.random() * 1.6;
  private coverPoint: THREE.Vector3 | null = null;
  private coverTimer = 0;
  private lastPos = new THREE.Vector3();
  private lastWantedMove = false;
  private stuckTimer = 0;
  private unstuckAngle = 0;
  private unstuckDir = Math.random() < 0.5 ? 1 : -1;
  private unstuckHoldTimer = 0;
  private navProbeTimer = 0;
  private doorwaySteerAngle = 0;
  private doorwaySteerTimer = 0;
  private doorwaySteerSign = Math.random() < 0.5 ? 1 : -1;
  private burstCooldown = 0;
  private burstActiveTimer = 0.8;
  private hardlightCooldown = 0;
  private impulseCooldown = 0;
  private grenadeCooldown = 0;
  private deployableCooldown = 0;

  private readonly tmpFrom = new THREE.Vector3();
  private readonly tmpTo = new THREE.Vector3();
  private readonly tmpAim = new THREE.Vector3();
  private readonly tmpProbeA = new THREE.Vector3();
  private readonly tmpProbeB = new THREE.Vector3();

  constructor(profile: BotDifficultyProfile, landmarks: LandmarkInfo[]) {
    this.profile = profile;
    this.pickDropTarget(landmarks);
  }

  private pickDropTarget(landmarks: LandmarkInfo[]): void {
    if (landmarks.length === 0) {
      this.dropTarget.set(-51, 0, 4);
      return;
    }
    const highTier = landmarks.filter((l) => l.highTier);
    const pool =
      highTier.length > 0 && Math.random() < this.profile.hotDropBias ? highTier : landmarks;
    const chosen = pool[Math.floor(Math.random() * pool.length)];
    const jitterAngle = Math.random() * Math.PI * 2;
    const jitterR = 4 + Math.random() * Math.max(8, chosen.radius * 0.55);
    this.dropTarget.set(
      clamp(chosen.x + Math.cos(jitterAngle) * jitterR, GAME_CONSTANTS.ARENA_MIN_X + 14, GAME_CONSTANTS.ARENA_MAX_X - 14),
      0,
      clamp(chosen.z + Math.sin(jitterAngle) * jitterR, GAME_CONSTANTS.ARENA_MIN_Z + 14, GAME_CONSTANTS.ARENA_MAX_Z - 14)
    );
  }

  public update(self: BotCombatantSnapshot, world: BotWorldContext): BotDecision {
    const dt = world.dt;
    this.strafeFlipTimer -= dt;
    this.crouchFlipTimer -= dt;
    this.roamTimer -= dt;
    this.coverTimer = Math.max(0, this.coverTimer - dt);
    this.hardlightCooldown = Math.max(0, this.hardlightCooldown - dt);
    this.impulseCooldown = Math.max(0, this.impulseCooldown - dt);
    this.grenadeCooldown = Math.max(0, this.grenadeCooldown - dt);
    this.deployableCooldown = Math.max(0, this.deployableCooldown - dt);
    this.burstCooldown = Math.max(0, this.burstCooldown - dt);
    this.burstActiveTimer -= dt;
    this.unstuckHoldTimer = Math.max(0, this.unstuckHoldTimer - dt);
    this.navProbeTimer = Math.max(0, this.navProbeTimer - dt);
    this.doorwaySteerTimer = Math.max(0, this.doorwaySteerTimer - dt);

    if (this.strafeFlipTimer <= 0) {
      this.strafeDir = Math.random() < 0.5 ? -1 : 1;
      this.strafeFlipTimer =
        this.profile.tier === 'pro'
          ? 0.45 + Math.random() * 0.65
          : 1.0 + Math.random() * 1.4;
    }
    if (this.crouchFlipTimer <= 0) {
      this.crouchDecision = Math.random() < this.profile.crouchPeekChance;
      this.crouchFlipTimer = 1.1 + Math.random() * 1.6;
    }

    // Track stuck detection by effective horizontal progress speed when attempting to move
    const movedDist = Math.hypot(self.pos.x - this.lastPos.x, self.pos.z - this.lastPos.z);
    const actualSpeed = movedDist / Math.max(dt, 0.004);
    if (!self.channeling && !self.skyDropping && this.lastWantedMove && actualSpeed < 1.65) {
      this.stuckTimer += dt;
    } else {
      this.stuckTimer = Math.max(0, this.stuckTimer - dt * 2.6);
    }
    this.lastPos.copy(self.pos);

    const decision: BotDecision = {
      state: this.state,
      moveX: 0,
      moveZ: 0,
      sprint: false,
      crouch: false,
      jump: false,
      dive: false,
      aimYaw: self.yaw,
      aimTargetPoint: null,
      desiredSlot: self.activeSlot,
      fire: false,
      useItem: false,
      useUltimate: false,
      interactSupplyDropId: null,
      interactChestId: null,
      pickupLootId: null,
    };

    // 1. SKY_DROP STATE
    if (self.skyDropping) {
      this.state = 'SKY_DROP';
      decision.state = 'SKY_DROP';
      const dx = this.dropTarget.x - self.pos.x;
      const dz = this.dropTarget.z - self.pos.z;
      const dist = Math.hypot(dx, dz);
      if (dist > 3) {
        decision.moveX = dx / dist;
        decision.moveZ = dz / dist;
        decision.aimYaw = yawToward(self.pos.x, self.pos.z, this.dropTarget.x, this.dropTarget.z);
      }
      // Dive faster once nearing drop point (Pro dives aggressively early to hot-drop first!)
      decision.dive = dist < (this.profile.tier === 'pro' ? 54 : 36) || self.pos.y < 32;
      return decision;
    }

    // Check active channeling — let consumable/supply drop finish unless imminent lethal danger
    const vitalsRatio = (self.health + self.shield) / 200;
    const distToStormCenter = Math.hypot(
      self.pos.x - world.stormCenterX,
      self.pos.z - world.stormCenterZ
    );
    const outsideActiveStorm = distToStormCenter > world.stormRadius - 3;
    const distToNextCenter = Math.hypot(
      self.pos.x - world.nextStormCenterX,
      self.pos.z - world.nextStormCenterZ
    );
    const outsideNextZone = distToNextCenter > Math.max(6, world.nextStormRadius - 8);

    // Perceive visible / threatening enemies
    const targetInfo = this.selectEnemyTarget(self, world);
    const target = targetInfo?.enemy ?? null;
    const targetDist = targetInfo?.dist ?? Infinity;
    const targetHasLos = targetInfo?.hasLos ?? false;

    if (target) {
      if (this.currentTargetId !== target.id) {
        this.currentTargetId = target.id;
        this.targetAcquiredAt = world.time;
      }
    } else {
      this.currentTargetId = null;
    }

    // Check whether this bot has armed itself with at least one weapon yet
    const isArmed = this.hasWeapon(self);
    const threatArmed = target ? this.hasWeapon(target) : false;

    if (self.channeling) {
      this.state = isArmed ? 'RETREAT_AND_HEAL' : 'HUNT_CHEST';
      decision.state = this.state;
      decision.crouch = this.profile.healInCover;
      // Let 0.75s chest opening finish when unarmed unless fatally cornered;
      // when armed, only break heal/drop channel if an enemy walks right on top of us with LOS (< 9.5m)
      const keepChannel = !isArmed
        ? !(threatArmed && target && targetHasLos && targetDist < 5.5 && self.health < 30)
        : !target || !targetHasLos || targetDist > 9.5;
      if (keepChannel) {
        if (target) {
          decision.aimYaw = yawToward(self.pos.x, self.pos.z, target.pos.x, target.pos.z);
        }
        return decision;
      }
    }

    // Evaluate healing slot availability
    const healSlot = this.findBestHealSlot(self);
    const needsHeal =
      healSlot !== -1 &&
      ((this.profile.tier === 'casual' && self.health < 35) ||
        (this.profile.tier !== 'casual' && vitalsRatio < this.profile.healThresholdRatio) ||
        (self.mana < 65 && this.findItemSlot(self, 'mana_elixir') !== -1 && !target));

    // Evaluate Supply Drop contesting opportunity (only once armed)
    const supplyDrop = isArmed ? this.findContestSupplyDrop(self, world) : null;

    // Evaluate nearby popped ground loot & unopened Loot Chests
    const lootTarget = this.findBestLootTarget(self, world, isArmed && target !== null, !isArmed);
    const chestTarget = this.findBestChestTarget(
      self,
      world,
      !isArmed,
      threatArmed ? target : null
    );

    // Evaluate storm rotation urgency
    const mustRotateStorm =
      outsideActiveStorm ||
      (outsideNextZone &&
        (this.profile.preRotateNextZone ||
          world.stormShrinkInSec <= this.profile.stormRotateLeadSec));

    // Check instant opportunistic pickup when passing within 3.2m of reachable same-floor loot
    if (lootTarget && lootTarget.dist <= 3.2 && Math.abs(lootTarget.loot.y - self.pos.y) <= 2.6) {
      decision.pickupLootId = lootTarget.loot.id;
    }

    // ------------------------------------------------------------------
    // FSM STATE SELECTION PRIORITY
    // ------------------------------------------------------------------
    let unarmedEvadeThreat = false;
    if (!isArmed) {
      // Unarmed priority: grab popped weapon -> hunt & open nearest/highest-tier chest -> evade armed foes
      const hasImmediatePoppedWeapon =
        lootTarget !== null &&
        lootTarget.loot.kind === 'weapon' &&
        (lootTarget.dist <= 16 || !chestTarget || lootTarget.dist < chestTarget.dist * 0.78);

      const armedThreatClose =
        target !== null && threatArmed && (targetHasLos || targetDist < 16) && targetDist < 24;

      if (hasImmediatePoppedWeapon) {
        this.state = 'LOOT_UPGRADE';
      } else if (
        armedThreatClose &&
        (!chestTarget || chestTarget.dist > 5.2) &&
        (!lootTarget || lootTarget.dist > 4.2)
      ) {
        // Evade/flee armed rival while steering toward a safer unopened chest if one is away from them
        const safeChest =
          chestTarget &&
          target &&
          Math.hypot(chestTarget.chest.x - target.pos.x, chestTarget.chest.z - target.pos.z) >
            targetDist + 5;
        if (safeChest) {
          this.state = 'HUNT_CHEST';
        } else {
          this.state = 'RETREAT_AND_HEAL';
          unarmedEvadeThreat = true;
        }
      } else if (chestTarget) {
        this.state = 'HUNT_CHEST';
      } else if (lootTarget) {
        this.state = 'LOOT_UPGRADE';
      } else {
        this.state = 'ROTATE_SAFE_ZONE';
      }
    } else if (outsideActiveStorm && (!target || targetDist > 30)) {
      this.state = 'ROTATE_SAFE_ZONE';
    } else if (needsHeal && (!target || !targetHasLos || targetDist > 12 || vitalsRatio < 0.35)) {
      this.state = 'RETREAT_AND_HEAL';
    } else if (target && (targetHasLos || targetDist < 28 || world.time - self.lastDamagedAt < 2.2)) {
      this.state = 'COMBAT_ENGAGE';
    } else if (mustRotateStorm) {
      this.state = 'ROTATE_SAFE_ZONE';
    } else if (supplyDrop) {
      this.state = 'CONTEST_SUPPLY_DROP';
    } else if (lootTarget) {
      this.state = 'LOOT_UPGRADE';
    } else if (chestTarget) {
      this.state = 'HUNT_CHEST';
    } else {
      this.state = 'ROTATE_SAFE_ZONE';
    }

    decision.state = this.state;

    // ------------------------------------------------------------------
    // STATE EXECUTION
    // ------------------------------------------------------------------
    switch (this.state) {
      case 'HUNT_CHEST': {
        if (chestTarget) {
          this.executeHuntChest(self, world, chestTarget, decision);
        }
        break;
      }
      case 'RETREAT_AND_HEAL': {
        if (unarmedEvadeThreat && target) {
          this.executeUnarmedEvade(self, world, target, decision);
        } else {
          this.executeRetreatAndHeal(self, world, target, targetHasLos, healSlot, decision);
        }
        break;
      }
      case 'COMBAT_ENGAGE': {
        if (target) {
          this.executeCombat(self, world, target, targetDist, targetHasLos, decision);
        }
        break;
      }
      case 'CONTEST_SUPPLY_DROP': {
        if (supplyDrop) {
          this.executeSupplyDrop(self, world, supplyDrop, decision);
        }
        break;
      }
      case 'LOOT_UPGRADE': {
        if (lootTarget) {
          this.steerToward(self, lootTarget.loot.x, lootTarget.loot.z, decision, true, world);
          if (lootTarget.dist <= 3.2 && Math.abs(lootTarget.loot.y - self.pos.y) <= 2.6) {
            decision.pickupLootId = lootTarget.loot.id;
          }
        }
        break;
      }
      case 'ROTATE_SAFE_ZONE':
      default: {
        this.executeRotateSafeZone(self, world, outsideActiveStorm, outsideNextZone, decision);
        break;
      }
    }

    // Proactive doorway/wall-edge avoidance + stuck recovery (works smoothly indoors & around desk pods!)
    const moveMag = Math.hypot(decision.moveX, decision.moveZ);
    this.lastWantedMove = moveMag > 0.12 && !self.channeling;
    if (this.lastWantedMove) {
      this.applyDoorwayAndObstacleSteering(self, world, decision);
    }

    // Never request sprint while reloading so bot intent strictly matches engine state
    if (self.isReloading) {
      decision.sprint = false;
    }

    return decision;
  }

  private executeRetreatAndHeal(
    self: BotCombatantSnapshot,
    world: BotWorldContext,
    threat: BotCombatantSnapshot | null,
    threatHasLos: boolean,
    healSlot: number,
    decision: BotDecision
  ): void {
    // Check Docs Version History clutch reset before even running!
    if (
      self.heroId === 'docs' &&
      this.shouldCastUltimate(self, world, threat, threat ? self.pos.distanceTo(threat.pos) : 999, threatHasLos)
    ) {
      decision.useUltimate = true;
      return;
    }

    // Deploy Shield Drop or Regen Pod when hurt behind cover (or no LOS)
    if (this.deployableCooldown <= 0 && self.silencedSec <= 0 && (!threat || !threatHasLos)) {
      const shieldDropSlot = self.shield < 72 ? this.findItemSlot(self, 'shield_drop') : -1;
      const regenPodSlot = self.health < 78 ? this.findItemSlot(self, 'regen_pod') : -1;
      const chosenDeploy = shieldDropSlot !== -1 ? shieldDropSlot : regenPodSlot;
      if (chosenDeploy !== -1) {
        decision.desiredSlot = chosenDeploy;
        decision.useItem = true;
        this.deployableCooldown = 10.5;
        return;
      }
    }

    // Casual heals right in place without seeking cover
    if (!this.profile.healInCover || !threat || !threatHasLos) {
      if (healSlot !== -1 && self.silencedSec <= 0) {
        decision.desiredSlot = healSlot;
        decision.useItem = true;
        decision.crouch = this.profile.healInCover;
      }
      return;
    }

    // Tactical & Pro: deploy Hard-Light Cover or duck behind architectural cover first!
    const coverSlot = this.findItemSlot(self, 'hardlight_cover');
    if (
      coverSlot !== -1 &&
      self.mana >= (UTILITY_ITEMS.hardlight_cover.manaCost ?? 12) &&
      this.hardlightCooldown <= 0 &&
      Math.random() < this.profile.deployHardlightChance
    ) {
      decision.desiredSlot = coverSlot;
      decision.aimYaw = yawToward(self.pos.x, self.pos.z, threat.pos.x, threat.pos.z);
      decision.useItem = true;
      this.hardlightCooldown = 4.5;
      return;
    }

    // Impulse Booster escape for Pro bots when critically low
    const impulseSlot = this.findItemSlot(self, 'impulse_booster');
    if (
      impulseSlot !== -1 &&
      self.health < 45 &&
      self.mana >= (UTILITY_ITEMS.impulse_booster.manaCost ?? 10) &&
      this.impulseCooldown <= 0 &&
      Math.random() < this.profile.useImpulseChance
    ) {
      decision.desiredSlot = impulseSlot;
      decision.aimYaw = yawToward(threat.pos.x, threat.pos.z, self.pos.x, self.pos.z);
      decision.useItem = true;
      this.impulseCooldown = 5.0;
      return;
    }

    // Cast radial cover rays to locate nearest out-of-LOS cover point
    if (!this.coverPoint || this.coverTimer <= 0) {
      this.coverPoint = this.findCoverPoint(self, threat, world);
      this.coverTimer = 2.4;
    }

    if (this.coverPoint) {
      const distCover = Math.hypot(
        this.coverPoint.x - self.pos.x,
        this.coverPoint.z - self.pos.z
      );
      if (distCover > 2.2) {
        this.steerToward(self, this.coverPoint.x, this.coverPoint.z, decision, true, world);
      } else if (healSlot !== -1 && self.silencedSec <= 0) {
        decision.desiredSlot = healSlot;
        decision.useItem = true;
        decision.crouch = true;
      }
    } else {
      // Retreat away from threat toward safe zone center
      const rx = self.pos.x - threat.pos.x;
      const rz = self.pos.z - threat.pos.z;
      const len = Math.max(0.01, Math.hypot(rx, rz));
      this.steerToward(
        self,
        self.pos.x + (rx / len) * 14,
        self.pos.z + (rz / len) * 14,
        decision,
        true,
        world
      );
    }
  }

  private executeCombat(
    self: BotCombatantSnapshot,
    world: BotWorldContext,
    target: BotCombatantSnapshot,
    dist: number,
    hasLos: boolean,
    decision: BotDecision
  ): void {
    // Choose optimal weapon slot for engagement range; if unarmed, evade instead of dry-firing
    const bestWeaponSlot = this.selectBestWeaponSlot(self, dist);
    if (bestWeaponSlot === -1) {
      this.executeUnarmedEvade(self, world, target, decision);
      return;
    }
    decision.desiredSlot = bestWeaponSlot;

    // Flashbang blindness reaction: suppress accurate aiming & firing, back up/weave blindly
    if (self.blindedSec > 0.1) {
      const rx = self.pos.x - target.pos.x;
      const rz = self.pos.z - target.pos.z;
      const rLen = Math.max(0.01, Math.hypot(rx, rz));
      const awayX = rx / rLen;
      const awayZ = rz / rLen;
      const perpX = -awayZ * this.strafeDir * 0.7;
      const perpZ = awayX * this.strafeDir * 0.7;
      const bLen = Math.max(0.01, Math.hypot(awayX + perpX, awayZ + perpZ));
      decision.moveX = (awayX + perpX) / bLen;
      decision.moveZ = (awayZ + perpZ) / bLen;
      decision.sprint = false;
      decision.crouch = false;
      const blindYaw = self.yaw + gaussianApprox() * 1.15;
      decision.aimYaw = blindYaw;
      this.tmpAim.set(
        self.pos.x - Math.sin(blindYaw) * 14,
        self.pos.y + 1.1 + gaussianApprox() * 2.8,
        self.pos.z - Math.cos(blindYaw) * 14
      );
      decision.aimTargetPoint = this.tmpAim.clone();
      // Occasional panicked inaccurate spray only when very close
      decision.fire = dist < 14 && Math.random() < 0.16;
      return;
    }

    // Tactical grenade throw (Frag Grenade or Flashbang) at mid-range enemies (10-26m)
    if (
      this.grenadeCooldown <= 0 &&
      self.silencedSec <= 0 &&
      dist >= 10 &&
      dist <= 26 &&
      Math.random() < world.dt * (this.profile.tier === 'pro' ? 0.55 : this.profile.tier === 'tactical' ? 0.35 : 0.18)
    ) {
      const fragSlot = this.findItemSlot(self, 'frag_grenade');
      const flashSlot = this.findItemSlot(self, 'flashbang');
      const throwSlot =
        fragSlot !== -1 && flashSlot !== -1
          ? Math.random() < 0.55
            ? fragSlot
            : flashSlot
          : fragSlot !== -1
            ? fragSlot
            : flashSlot;
      if (throwSlot !== -1) {
        decision.desiredSlot = throwSlot;
        decision.aimYaw = yawToward(self.pos.x, self.pos.z, target.pos.x, target.pos.z);
        this.tmpAim.set(target.pos.x, target.pos.y + 1.0, target.pos.z);
        decision.aimTargetPoint = this.tmpAim.clone();
        decision.useItem = true;
        this.grenadeCooldown = 5.5;
        return;
      }
    }

    // Sudden-fire Shield Drop or Hard-Light Cover reaction for Tactical/Pro bots
    const shieldDropCombatSlot = this.findItemSlot(self, 'shield_drop');
    if (
      shieldDropCombatSlot !== -1 &&
      this.deployableCooldown <= 0 &&
      self.silencedSec <= 0 &&
      self.shield < 55 &&
      world.time - self.lastDamagedAt < 1.2 &&
      Math.random() < this.profile.deployHardlightChance * 0.5
    ) {
      decision.desiredSlot = shieldDropCombatSlot;
      decision.aimYaw = yawToward(self.pos.x, self.pos.z, target.pos.x, target.pos.z);
      decision.useItem = true;
      this.deployableCooldown = 11.0;
      return;
    }

    // Sudden-fire Hard-Light Cover reaction for Tactical/Pro bots
    const coverSlot = this.findItemSlot(self, 'hardlight_cover');
    if (
      coverSlot !== -1 &&
      world.time - self.lastDamagedAt < 0.7 &&
      self.recentDamageTaken >= 28 &&
      self.mana >= 12 &&
      this.hardlightCooldown <= 0 &&
      hasLos &&
      dist > 10 &&
      Math.random() < this.profile.deployHardlightChance * 0.45
    ) {
      decision.desiredSlot = coverSlot;
      decision.aimYaw = yawToward(self.pos.x, self.pos.z, target.pos.x, target.pos.z);
      decision.useItem = true;
      this.hardlightCooldown = 6.0;
      return;
    }

    // Check Hero-Specific Ultimate Heuristics
    if (this.shouldCastUltimate(self, world, target, dist, hasLos)) {
      decision.aimYaw = yawToward(self.pos.x, self.pos.z, target.pos.x, target.pos.z);
      this.tmpAim.copy(target.pos);
      this.tmpAim.y += target.crouching ? 0.75 : 1.15;
      decision.aimTargetPoint = this.tmpAim.clone();
      decision.useUltimate = true;
      return;
    }

    // Compute predictive velocity-lead aim point + headshot bias + Gaussian scatter
    const activeSlotObj = self.slots[decision.desiredSlot];
    const weaponDef =
      activeSlotObj && activeSlotObj.kind === 'weapon'
        ? WEAPONS[activeSlotObj.id as WeaponId]
        : WEAPONS.vanguard_m4;

    const travelTime = dist / Math.max(weaponDef.projectileSpeed, 20);
    const leadT = travelTime * this.profile.leadFactor;

    const aimForHead =
      weaponDef.headshotMult > 1.0 && Math.random() < this.profile.headshotBias;
    const targetY =
      target.pos.y +
      (aimForHead
        ? target.crouching
          ? GAME_CONSTANTS.HEAD_OFFSET_CROUCHING
          : GAME_CONSTANTS.HEAD_OFFSET_STANDING
        : target.crouching
          ? 0.62
          : 1.05);

    const leadX = target.pos.x + target.vel.x * leadT;
    const leadZ = target.pos.z + target.vel.z * leadT;
    const leadY = targetY + target.vel.y * leadT * 0.35;

    // Angular Gaussian error scaled by distance
    const errScale = Math.tan(this.profile.aimErrorRad) * Math.max(6, dist);
    this.tmpAim.set(
      leadX + gaussianApprox() * errScale,
      leadY + gaussianApprox() * errScale * 0.45,
      leadZ + gaussianApprox() * errScale
    );
    decision.aimTargetPoint = this.tmpAim.clone();
    decision.aimYaw = yawToward(self.pos.x, self.pos.z, this.tmpAim.x, this.tmpAim.z);

    // Movement: approach if no LOS or out of preferred weapon range, else tactical strafe-weave
    const idealMin = weaponDef.id === 'breaker_12g' ? 5 : weaponDef.id === 'longbow_308' ? 32 : 16;
    const idealMax =
      weaponDef.id === 'breaker_12g'
        ? 14
        : weaponDef.id === 'vector_9'
          ? 24
          : weaponDef.id === 'longbow_308'
            ? 85
            : 40;

    const toX = (target.pos.x - self.pos.x) / Math.max(dist, 0.01);
    const toZ = (target.pos.z - self.pos.z) / Math.max(dist, 0.01);
    const perpX = -toZ * this.strafeDir;
    const perpZ = toX * this.strafeDir;

    if (!hasLos) {
      // Push through doorways or flank around office walls toward enemy
      const wp = this.resolveDoorwayWaypoint(self, target.pos.x, target.pos.z, world);
      if (wp) {
        const wdx = wp[0] - self.pos.x;
        const wdz = wp[1] - self.pos.z;
        const wLen = Math.max(0.01, Math.hypot(wdx, wdz));
        decision.moveX = wdx / wLen;
        decision.moveZ = wdz / wLen;
      } else {
        const flankWeight = this.profile.useCoverChance * 0.55;
        decision.moveX = toX + perpX * flankWeight;
        decision.moveZ = toZ + perpZ * flankWeight;
      }
      decision.sprint = dist > 18;
    } else {
      let fwdFactor = 0;
      if (dist > idealMax) fwdFactor = 0.72;
      else if (dist < idealMin) fwdFactor = -0.58;

      decision.moveX = toX * fwdFactor + perpX * this.profile.strafeIntensity;
      decision.moveZ = toZ * fwdFactor + perpZ * this.profile.strafeIntensity;

      // Crouch peeking at medium/long range for tighter accuracy
      if (dist > 15 && this.crouchDecision && !decision.sprint) {
        decision.crouch = true;
      }

      // Occasional Pro combat jump when close
      if (
        this.profile.tier === 'pro' &&
        dist < 16 &&
        !decision.crouch &&
        Math.random() < world.dt * 0.9
      ) {
        decision.jump = true;
      }
    }

    // Normalize move vector
    const mLen = Math.hypot(decision.moveX, decision.moveZ);
    if (mLen > 0.001) {
      decision.moveX /= mLen;
      decision.moveZ /= mLen;
    }

    // Firing gate: requires LOS, reaction time elapsed, within weapon range, and cadence throttle
    const reacted = world.time - this.targetAcquiredAt >= this.profile.reactionTime;
    if (hasLos && reacted && dist <= Math.min(weaponDef.range, this.profile.engagementRange)) {
      if (this.burstCooldown <= 0) {
        decision.fire = true;
        if (this.burstActiveTimer <= 0) {
          this.burstActiveTimer = 0.55 + Math.random() * 0.9;
          // Casual pauses briefly between bursts; Pro stays relentless
          this.burstCooldown = (1 - this.profile.fireCadenceMult) * (0.45 + Math.random() * 0.45);
        }
      }
    }
  }

  private executeHuntChest(
    self: BotCombatantSnapshot,
    world: BotWorldContext,
    target: { chest: BotChestSnapshot; dist: number },
    decision: BotDecision
  ): void {
    const ch = target.chest;
    const dist = Math.hypot(ch.x - self.pos.x, ch.z - self.pos.z);
    if (dist <= GAME_CONSTANTS.CHEST_INTERACT_RADIUS && Math.abs(ch.y - self.pos.y) <= 2.4 && !ch.opened) {
      decision.interactChestId = ch.id;
      decision.moveX = 0;
      decision.moveZ = 0;
      decision.sprint = false;
      decision.crouch = this.profile.tier !== 'casual';
      decision.aimYaw = yawToward(self.pos.x, self.pos.z, ch.x, ch.z);
      return;
    }
    this.steerToward(self, ch.x, ch.z, decision, true, world);
  }

  private executeUnarmedEvade(
    self: BotCombatantSnapshot,
    world: BotWorldContext,
    threat: BotCombatantSnapshot,
    decision: BotDecision
  ): void {
    // Sprint evasively away from armed opponent with slight lateral weave toward safe zone
    const rx = self.pos.x - threat.pos.x;
    const rz = self.pos.z - threat.pos.z;
    const len = Math.max(0.01, Math.hypot(rx, rz));
    const awayX = rx / len;
    const awayZ = rz / len;
    const perpX = -awayZ * this.strafeDir * 0.42;
    const perpZ = awayX * this.strafeDir * 0.42;
    const targetX = clamp(
      self.pos.x + (awayX + perpX) * 18,
      GAME_CONSTANTS.ARENA_MIN_X + 10,
      GAME_CONSTANTS.ARENA_MAX_X - 10
    );
    const targetZ = clamp(
      self.pos.z + (awayZ + perpZ) * 18,
      GAME_CONSTANTS.ARENA_MIN_Z + 10,
      GAME_CONSTANTS.ARENA_MAX_Z - 10
    );
    this.steerToward(self, targetX, targetZ, decision, true, world);
  }

  private executeSupplyDrop(
    self: BotCombatantSnapshot,
    world: BotWorldContext,
    drop: BotSupplyDropSnapshot,
    decision: BotDecision
  ): void {
    const dist = Math.hypot(drop.x - self.pos.x, drop.z - self.pos.z);
    if (dist <= 3.6 && drop.landed && !drop.opened) {
      decision.interactSupplyDropId = drop.id;
      decision.crouch = true;
    } else if (dist > 3.2) {
      this.steerToward(self, drop.x, drop.z, decision, true, world);
    } else {
      // Wait nearby while crate finishes descending
      decision.crouch = this.profile.tier !== 'casual';
      decision.aimYaw = yawToward(self.pos.x, self.pos.z, drop.x, drop.z);
    }
  }

  private executeRotateSafeZone(
    self: BotCombatantSnapshot,
    world: BotWorldContext,
    outsideActiveStorm: boolean,
    outsideNextZone: boolean,
    decision: BotDecision
  ): void {
    if (outsideActiveStorm || outsideNextZone) {
      // Run cleanly toward interior of next safe zone with organic angular spread across 3× campus
      const angle = Math.atan2(self.pos.z - world.nextStormCenterZ, self.pos.x - world.nextStormCenterX);
      const safeR = Math.max(6, Math.min(world.nextStormRadius * 0.55, world.nextStormRadius - 12));
      const tx = world.nextStormCenterX + Math.cos(angle) * safeR;
      const tz = world.nextStormCenterZ + Math.sin(angle) * safeR;
      this.steerToward(self, tx, tz, decision, true, world);
      return;
    }

    // Patrol between landmarks & playable office interiors (B40, B41, B42, B43, Gradient Canopy) inside safe zone
    const distRoam = Math.hypot(this.roamTarget.x - self.pos.x, this.roamTarget.z - self.pos.z);
    if (this.roamTimer <= 0 || distRoam < 5) {
      const safeOffices = OFFICE_INTERIOR_ZONES.filter((oz) => {
        const d = Math.hypot(oz.centerX - world.nextStormCenterX, oz.centerZ - world.nextStormCenterZ);
        return d < Math.max(22, world.nextStormRadius - 6);
      });
      const safeLandmarks = world.landmarks.filter((lm) => {
        const d = Math.hypot(lm.x - world.nextStormCenterX, lm.z - world.nextStormCenterZ);
        return d < Math.max(18, world.nextStormRadius - 8);
      });

      if (safeOffices.length > 0 && Math.random() < 0.34) {
        // Actively enter & patrol hollow ground-floor office interiors for loot & indoor skirmishes!
        const office = safeOffices[Math.floor(Math.random() * safeOffices.length)];
        const a = Math.random() * Math.PI * 2;
        const r = Math.random() * 11;
        this.roamTarget.set(
          clamp(office.centerX + Math.cos(a) * r, GAME_CONSTANTS.ARENA_MIN_X + 12, GAME_CONSTANTS.ARENA_MAX_X - 12),
          0,
          clamp(office.centerZ + Math.sin(a) * r, GAME_CONSTANTS.ARENA_MIN_Z + 12, GAME_CONSTANTS.ARENA_MAX_Z - 12)
        );
      } else if (safeLandmarks.length > 0 && Math.random() < 0.75) {
        const lm = safeLandmarks[Math.floor(Math.random() * safeLandmarks.length)];
        const a = Math.random() * Math.PI * 2;
        const r = Math.random() * Math.max(6, lm.radius * 0.6);
        this.roamTarget.set(
          clamp(lm.x + Math.cos(a) * r, GAME_CONSTANTS.ARENA_MIN_X + 12, GAME_CONSTANTS.ARENA_MAX_X - 12),
          0,
          clamp(lm.z + Math.sin(a) * r, GAME_CONSTANTS.ARENA_MIN_Z + 12, GAME_CONSTANTS.ARENA_MAX_Z - 12)
        );
      } else {
        const a = Math.random() * Math.PI * 2;
        const r = Math.random() * Math.max(8, world.nextStormRadius * 0.72);
        this.roamTarget.set(
          clamp(world.nextStormCenterX + Math.cos(a) * r, GAME_CONSTANTS.ARENA_MIN_X + 12, GAME_CONSTANTS.ARENA_MAX_X - 12),
          0,
          clamp(world.nextStormCenterZ + Math.sin(a) * r, GAME_CONSTANTS.ARENA_MIN_Z + 12, GAME_CONSTANTS.ARENA_MAX_Z - 12)
        );
      }
      this.roamTimer = 7 + Math.random() * 7;
    }

    this.steerToward(self, this.roamTarget.x, this.roamTarget.z, decision, distRoam > 18, world);
  }

  private steerToward(
    self: BotCombatantSnapshot,
    tx: number,
    tz: number,
    decision: BotDecision,
    sprint: boolean,
    world?: BotWorldContext
  ): void {
    let navX = tx;
    let navZ = tz;
    if (world) {
      const wp = this.resolveDoorwayWaypoint(self, tx, tz, world);
      if (wp) {
        navX = wp[0];
        navZ = wp[1];
      }
    }

    const dx = navX - self.pos.x;
    const dz = navZ - self.pos.z;
    const dist = Math.hypot(dx, dz);
    if (dist > 0.2) {
      decision.moveX = dx / dist;
      decision.moveZ = dz / dist;
      decision.sprint = sprint;
      decision.aimYaw = yawToward(self.pos.x, self.pos.z, navX, navZ);
    }
  }

  /**
   * When entering or exiting B40, B41, B42, B43, or Gradient Canopy ground floors and direct
   * line-of-sight is blocked by an exterior wall, routes cleanly through the nearest open doorway!
   */
  private resolveDoorwayWaypoint(
    self: BotCombatantSnapshot,
    tx: number,
    tz: number,
    world: BotWorldContext
  ): [number, number] | null {
    // Only route ground-floor doorways when bot is on ground level (not on +6.4m rooftops)
    if (self.pos.y > 3.2) return null;

    const totalDist = Math.hypot(tx - self.pos.x, tz - self.pos.z);
    if (totalDist < 4.5) return null;

    // If direct path at chest height is already open, walk straight in/out without detouring!
    this.tmpProbeA.set(self.pos.x, self.pos.y + 1.32, self.pos.z);
    this.tmpProbeB.set(tx, self.pos.y + 1.32, tz);
    if (world.hasLineOfSight(this.tmpProbeA, this.tmpProbeB)) {
      return null;
    }

    for (const office of OFFICE_INTERIOR_ZONES) {
      const selfIn = pointInPolyXZ(self.pos.x, self.pos.z, office.poly);
      const targetIn = pointInPolyXZ(tx, tz, office.poly);
      if (!selfIn && !targetIn) continue;

      let bestDoor: [number, number] | null = null;
      let bestCost = Infinity;
      for (const door of office.doorways) {
        const dToDoor = Math.hypot(door[0] - self.pos.x, door[1] - self.pos.z);
        const dDoorToTarget = Math.hypot(tx - door[0], tz - door[1]);
        // Skip doorways we're already standing right inside so we push cleanly through into the room
        if (dToDoor < 2.0) continue;
        let cost = dToDoor + dDoorToTarget;
        this.tmpProbeB.set(door[0], self.pos.y + 1.32, door[1]);
        if (world.hasLineOfSight(this.tmpProbeA, this.tmpProbeB)) {
          cost -= 8.0; // Prefer unobstructed doorway approach
        }
        if (cost < bestCost) {
          bestCost = cost;
          bestDoor = door;
        }
      }
      if (bestDoor) {
        return bestDoor;
      }
    }

    return null;
  }

  /**
   * Proactive wall-edge & doorway fan-probing + committed stuck recovery so bots smoothly
   * slide around doorway jambs, interior walls, columns, and office furniture without jittering.
   */
  private applyDoorwayAndObstacleSteering(
    self: BotCombatantSnapshot,
    world: BotWorldContext,
    decision: BotDecision
  ): void {
    const baseLen = Math.hypot(decision.moveX, decision.moveZ);
    if (baseLen < 0.05) return;
    const dirX = decision.moveX / baseLen;
    const dirZ = decision.moveZ / baseLen;

    const chestY = self.pos.y + 1.32;
    const waistY = self.pos.y + 0.72;

    // 1. Committed stuck-recovery doorway steering (when progress stalls against a wall corner or furniture)
    if (this.stuckTimer > 0.48) {
      this.tmpProbeA.set(self.pos.x, waistY, self.pos.z);
      this.tmpProbeB.set(self.pos.x + dirX * 2.1, waistY, self.pos.z + dirZ * 2.1);
      const waistBlocked = !world.hasLineOfSight(this.tmpProbeA, this.tmpProbeB);

      this.tmpProbeA.set(self.pos.x, chestY, self.pos.z);
      this.tmpProbeB.set(self.pos.x + dirX * 2.3, chestY, self.pos.z + dirZ * 2.3);
      const chestBlocked = !world.hasLineOfSight(this.tmpProbeA, this.tmpProbeB);

      // Low cover ahead (desk pod / sofa / planter) -> hop cleanly over it!
      if (waistBlocked && !chestBlocked && this.stuckTimer > 0.55) {
        decision.jump = true;
      }

      if (this.unstuckHoldTimer <= 0) {
        // Probe left vs right to choose the side leading toward an open doorway / corridor
        let chosenAngle = this.unstuckDir * (Math.PI * 0.46);
        let foundClear = false;
        const testAngles = [
          this.unstuckDir * 0.95,
          -this.unstuckDir * 0.95,
          this.unstuckDir * 1.48,
          -this.unstuckDir * 1.48,
          this.unstuckDir * 2.1,
          -this.unstuckDir * 2.1,
        ];
        this.tmpProbeA.set(self.pos.x, chestY, self.pos.z);
        for (const ang of testAngles) {
          const c = Math.cos(ang);
          const s = Math.sin(ang);
          const rx = dirX * c - dirZ * s;
          const rz = dirX * s + dirZ * c;
          this.tmpProbeB.set(self.pos.x + rx * 3.8, chestY, self.pos.z + rz * 3.8);
          if (world.hasLineOfSight(this.tmpProbeA, this.tmpProbeB)) {
            chosenAngle = ang;
            this.unstuckDir = ang >= 0 ? 1 : -1;
            foundClear = true;
            break;
          }
        }
        if (!foundClear) {
          this.unstuckDir = -this.unstuckDir;
          chosenAngle = this.unstuckDir * (Math.PI * 0.62);
        }
        this.unstuckAngle = chosenAngle;
        this.unstuckHoldTimer = 0.95;
      }

      const cosA = Math.cos(this.unstuckAngle);
      const sinA = Math.sin(this.unstuckAngle);
      decision.moveX = dirX * cosA - dirZ * sinA;
      decision.moveZ = dirX * sinA + dirZ * cosA;
      if (this.stuckTimer > 1.5 && this.state === 'ROTATE_SAFE_ZONE') {
        this.roamTimer = 0; // Refresh patrol target if wedged
      }
      return;
    }

    // 2. Proactive short-range wall-edge & doorway funnel steering (throttled to ~8 Hz per bot)
    if (this.navProbeTimer <= 0) {
      this.navProbeTimer = 0.12;
      this.tmpProbeA.set(self.pos.x, chestY, self.pos.z);
      this.tmpProbeB.set(self.pos.x + dirX * 2.6, chestY, self.pos.z + dirZ * 2.6);

      if (!world.hasLineOfSight(this.tmpProbeA, this.tmpProbeB)) {
        // Wall edge or interior partition ahead -> fan-probe to glide smoothly into adjacent doorway!
        const candidates = [0.48, -0.48, 0.96, -0.96, 1.44, -1.44, 1.92, -1.92];
        let bestAng = 0;
        let bestScore = -Infinity;

        for (const ang of candidates) {
          const c = Math.cos(ang);
          const s = Math.sin(ang);
          const rx = dirX * c - dirZ * s;
          const rz = dirX * s + dirZ * c;
          this.tmpProbeB.set(self.pos.x + rx * 4.2, chestY, self.pos.z + rz * 4.2);
          if (!world.hasLineOfSight(this.tmpProbeA, this.tmpProbeB)) continue;

          let score = 2.5 - Math.abs(ang);
          if (Math.sign(ang) === this.doorwaySteerSign) score += 0.45; // Anti-oscillation hysteresis

          // Bonus for deeper open clearance (pulls bots cleanly into wide office doorways!)
          this.tmpProbeB.set(self.pos.x + rx * 7.2, chestY, self.pos.z + rz * 7.2);
          if (world.hasLineOfSight(this.tmpProbeA, this.tmpProbeB)) {
            score += 0.9;
          }

          if (score > bestScore) {
            bestScore = score;
            bestAng = ang;
          }
        }

        if (bestScore > -Infinity) {
          this.doorwaySteerAngle = bestAng;
          this.doorwaySteerSign = bestAng >= 0 ? 1 : -1;
          this.doorwaySteerTimer = 0.42;
        }
      } else if (this.doorwaySteerTimer > 0) {
        // Path ahead opened up (e.g. aligned with doorway!) -> release detour smoothly
        this.doorwaySteerTimer = Math.min(this.doorwaySteerTimer, 0.08);
      }
    }

    if (this.doorwaySteerTimer > 0 && Math.abs(this.doorwaySteerAngle) > 0.05) {
      const cosA = Math.cos(this.doorwaySteerAngle);
      const sinA = Math.sin(this.doorwaySteerAngle);
      decision.moveX = dirX * cosA - dirZ * sinA;
      decision.moveZ = dirX * sinA + dirZ * cosA;
    }
  }

  private selectEnemyTarget(
    self: BotCombatantSnapshot,
    world: BotWorldContext
  ): { enemy: BotCombatantSnapshot; dist: number; hasLos: boolean } | null {
    let best: { enemy: BotCombatantSnapshot; dist: number; hasLos: boolean; score: number } | null = null;
    const maxSense = this.profile.engagementRange * 1.25;

    this.tmpFrom.set(self.pos.x, self.pos.y + 1.45, self.pos.z);

    for (const other of world.combatants) {
      if (other.id === self.id || !other.alive || other.skyDropping) continue;
      const dist = self.pos.distanceTo(other.pos);
      if (dist > maxSense && self.revealedAllSec <= 0 && other.id !== self.lastAttackerId) {
        continue;
      }

      this.tmpTo.set(other.pos.x, other.pos.y + (other.crouching ? 0.85 : 1.3), other.pos.z);
      const hasLos = dist <= this.profile.engagementRange && world.hasLineOfSight(this.tmpFrom, this.tmpTo);

      // Ignore distant enemies without LOS unless revealed or retaliating
      if (!hasLos && dist > 32 && other.id !== self.lastAttackerId && self.revealedAllSec <= 0) {
        continue;
      }

      // Avoid ground-floor indoor bots locking onto rooftop enemies directly overhead without LOS
      const vertDiff = Math.abs(other.pos.y - self.pos.y);
      if (!hasLos && vertDiff > 3.5 && other.id !== self.lastAttackerId && self.revealedAllSec <= 0) {
        continue;
      }

      let score = 165 - dist;
      if (hasLos) score += 55;
      if (!hasLos && vertDiff > 3.5) score -= 50;
      if (other.id === self.lastAttackerId && world.time - self.lastDamagedAt < 5.0) {
        score += 75;
      }
      // Pro & Tactical bots third-party weakened/fighting targets
      const targetVitals = other.health + other.shield;
      if (targetVitals < 120) {
        score += ((120 - targetVitals) / 120) * 55 * this.profile.thirdPartyAggression;
      }
      if (other.id === this.currentTargetId) {
        score += 18; // Target stickiness prevents jittery target-flicking
      }

      if (!best || score > best.score) {
        best = { enemy: other, dist, hasLos, score };
      }
    }

    return best ? { enemy: best.enemy, dist: best.dist, hasLos: best.hasLos } : null;
  }

  private selectBestWeaponSlot(self: BotCombatantSnapshot, dist: number): number {
    let bestSlot = -1;
    let bestScore = -1;
    for (let i = 0; i < self.slots.length; i++) {
      const slot = self.slots[i];
      if (!slot || slot.kind !== 'weapon') continue;
      const wId = slot.id as WeaponId;
      const wDef = WEAPONS[wId];
      if (wDef.manaPerShot && self.mana < wDef.manaPerShot) continue;

      let rangeFit = 1.0;
      if (wId === 'breaker_12g') rangeFit = dist < 14 ? 1.85 : dist < 24 ? 0.9 : 0.25;
      else if (wId === 'vector_9') rangeFit = dist < 25 ? 1.55 : dist < 45 ? 1.0 : 0.45;
      else if (wId === 'vanguard_m4') rangeFit = dist < 85 ? 1.45 : 1.0;
      else if (wId === 'longbow_308') rangeFit = dist > 38 ? 1.95 : dist > 20 ? 1.15 : 0.55;
      else if (wId === 'nova_gl40') rangeFit = dist > 12 && dist < 55 ? 1.4 : 0.5;

      const score = rangeFit * RARITY_CONFIG[slot.rarity].mult + ((slot.ammo ?? 0) > 0 ? 0.25 : 0);
      if (score > bestScore) {
        bestScore = score;
        bestSlot = i;
      }
    }
    return bestSlot;
  }

  private findItemSlot(self: BotCombatantSnapshot, id: UtilityItemId): number {
    for (let i = 0; i < self.slots.length; i++) {
      const s = self.slots[i];
      if (s && s.kind === 'item' && s.id === id && (s.count ?? 0) > 0) return i;
    }
    return -1;
  }

  private findBestHealSlot(self: BotCombatantSnapshot): number {
    // Priority: Medkit / Regen Pod if HP low -> Shield Jug / Shield Drop if Shield low -> Shield Cell -> Mana Elixir
    if (self.health < 68) {
      const mk = this.findItemSlot(self, 'medkit');
      if (mk !== -1) return mk;
      const rp = this.findItemSlot(self, 'regen_pod');
      if (rp !== -1) return rp;
    }
    if (self.shield < 45) {
      const jug = this.findItemSlot(self, 'shield_jug');
      if (jug !== -1) return jug;
      const sd = this.findItemSlot(self, 'shield_drop');
      if (sd !== -1) return sd;
    }
    if (self.shield < 82) {
      const cell = this.findItemSlot(self, 'shield_cell');
      if (cell !== -1) return cell;
    }
    if (self.health < 88) {
      const mk = this.findItemSlot(self, 'medkit');
      if (mk !== -1) return mk;
      const rp = this.findItemSlot(self, 'regen_pod');
      if (rp !== -1) return rp;
    }
    if (self.mana < 65) {
      const mana = this.findItemSlot(self, 'mana_elixir');
      if (mana !== -1) return mana;
    }
    return -1;
  }

  private findCoverPoint(
    self: BotCombatantSnapshot,
    threat: BotCombatantSnapshot,
    world: BotWorldContext
  ): THREE.Vector3 | null {
    const selfEye = new THREE.Vector3(self.pos.x, self.pos.y + 1.25, self.pos.z);
    const threatEye = new THREE.Vector3(threat.pos.x, threat.pos.y + 1.45, threat.pos.z);
    const probe = new THREE.Vector3();
    let best: THREE.Vector3 | null = null;
    let bestScore = -Infinity;

    for (let i = 0; i < 12; i++) {
      const ang = (i / 12) * Math.PI * 2;
      const dist = 5.5 + (i % 2) * 5.0;
      const px = clamp(self.pos.x + Math.cos(ang) * dist, GAME_CONSTANTS.ARENA_MIN_X + 8, GAME_CONSTANTS.ARENA_MAX_X - 8);
      const pz = clamp(self.pos.z + Math.sin(ang) * dist, GAME_CONSTANTS.ARENA_MIN_Z + 8, GAME_CONSTANTS.ARENA_MAX_Z - 8);
      probe.set(px, self.pos.y + 1.05, pz);

      // Good cover blocks LOS from threat! Prefer spots directly reachable on the same side of walls
      if (!world.hasLineOfSight(threatEye, probe)) {
        const reachable = world.hasLineOfSight(selfEye, probe);
        const distFromThreat = Math.hypot(px - threat.pos.x, pz - threat.pos.z);
        const distToSafe = Math.hypot(px - world.nextStormCenterX, pz - world.nextStormCenterZ);
        const score = distFromThreat * 0.6 - distToSafe * 0.15 + (reachable ? 18 : -8);
        if (score > bestScore) {
          bestScore = score;
          best = new THREE.Vector3(px, self.pos.y, pz);
        }
      }
    }
    return best;
  }

  private findContestSupplyDrop(
    self: BotCombatantSnapshot,
    world: BotWorldContext
  ): BotSupplyDropSnapshot | null {
    if (!this.profile.contestSupplyDrop) return null;
    const maxDist = this.profile.tier === 'pro' ? 235 : 130;
    let best: BotSupplyDropSnapshot | null = null;
    let bestDist = maxDist;
    for (const drop of world.supplyDrops) {
      if (drop.opened) continue;
      const dStorm = Math.hypot(drop.x - world.stormCenterX, drop.z - world.stormCenterZ);
      if (dStorm > world.stormRadius - 4) continue;
      const d = Math.hypot(drop.x - self.pos.x, drop.z - self.pos.z);
      if (d < bestDist) {
        bestDist = d;
        best = drop;
      }
    }
    return best;
  }

  private hasWeapon(c: BotCombatantSnapshot): boolean {
    for (const s of c.slots) {
      if (s && s.kind === 'weapon') return true;
    }
    return false;
  }

  private findBestChestTarget(
    self: BotCombatantSnapshot,
    world: BotWorldContext,
    unarmed: boolean,
    armedThreat: BotCombatantSnapshot | null
  ): { chest: BotChestSnapshot; dist: number } | null {
    if (world.chests.length === 0) return null;

    // Armed bots skip chest-hunting if already well-equipped unless a high-tier chest is very close
    let bestWeaponScore = 0;
    let hasEmptySlot = false;
    for (const slot of self.slots) {
      if (!slot) {
        hasEmptySlot = true;
      } else if (slot.kind === 'weapon') {
        bestWeaponScore = Math.max(bestWeaponScore, RARITY_SCORE[slot.rarity]);
      }
    }

    const needsGear = unarmed || bestWeaponScore < 2.0 || self.shield < 55 || hasEmptySlot;
    const searchRadius = unarmed
      ? 340
      : this.profile.tier === 'casual'
        ? needsGear
          ? 36
          : 20
        : this.profile.tier === 'tactical'
          ? needsGear
            ? 66
            : 38
          : needsGear
            ? 96
            : 56;

    // Tier preference: Tactical & Pro bots prioritize Tier 2/3 chests over distant/common Tier 1
    const tierWeight =
      this.profile.tier === 'pro' ? 22 : this.profile.tier === 'tactical' ? 14 : 4.0;

    let best: { chest: BotChestSnapshot; dist: number; score: number } | null = null;
    for (const ch of world.chests) {
      if (ch.opened) continue;
      const vertDiff = Math.abs(ch.y - self.pos.y);
      // Prefer chests on the same elevation/floor; allow fallback only when completely unarmed
      if (vertDiff > 2.8) continue;

      const d = Math.hypot(ch.x - self.pos.x, ch.z - self.pos.z);
      if (d > searchRadius) continue;

      // Avoid running deep outside active storm unless unarmed and chest is right next to us
      const dStorm = Math.hypot(ch.x - world.stormCenterX, ch.z - world.stormCenterZ);
      if (dStorm > world.stormRadius - 2 && (!unarmed || d > 22)) continue;

      // Armed bots with Rare/Epic weapon + decent shield ignore Tier 1 chests unless almost touching
      if (!unarmed && ch.tier === 1 && bestWeaponScore >= 2.0 && self.shield >= 50 && !hasEmptySlot) {
        continue;
      }

      let score = (unarmed ? 120 : needsGear ? 44 : 26) + ch.tier * tierWeight - d * (unarmed ? 0.95 : 0.72);
      if (!unarmed && ch.tier === 3) {
        score += 18 * this.profile.lootUpgradeDesire;
      }

      // Unarmed bots avoid chests camped right next to an armed enemy
      if (unarmed && armedThreat) {
        const dThreat = Math.hypot(ch.x - armedThreat.pos.x, ch.z - armedThreat.pos.z);
        if (dThreat < 16) {
          score -= (16 - dThreat) * 3.2;
        }
      }

      if (!unarmed && score <= 4) continue;
      if (!best || score > best.score) {
        best = { chest: ch, dist: d, score };
      }
    }

    // Fallback when completely unarmed on an already-looted rooftop/elevated deck: drop down toward nearest chest on any floor
    if (unarmed && !best) {
      let fallbackDist = Infinity;
      for (const ch of world.chests) {
        if (ch.opened) continue;
        const d = Math.hypot(ch.x - self.pos.x, ch.z - self.pos.z);
        if (d < fallbackDist) {
          fallbackDist = d;
          best = { chest: ch, dist: d, score: 100 - d };
        }
      }
    }

    return best ? { chest: best.chest, dist: best.dist } : null;
  }

  private findBestLootTarget(
    self: BotCombatantSnapshot,
    world: BotWorldContext,
    inFight: boolean,
    unarmed = false
  ): { loot: BotLootSnapshot; dist: number } | null {
    if (inFight && !unarmed && this.profile.tier !== 'pro') return null;
    const searchRadius = unarmed
      ? 54
      : this.profile.tier === 'casual'
        ? 24
        : this.profile.tier === 'tactical'
          ? 52
          : 78;

    // Current weapon & utility inventory quality snapshot
    let bestWeaponScore = 0;
    let worstWeaponScore = Infinity;
    let weaponCount = 0;
    let hasEmptySlot = false;
    let worstUtilityValue = Infinity;
    for (const slot of self.slots) {
      if (!slot) {
        hasEmptySlot = true;
      } else if (slot.kind === 'weapon') {
        weaponCount++;
        const wScore = RARITY_SCORE[slot.rarity];
        bestWeaponScore = Math.max(bestWeaponScore, wScore);
        worstWeaponScore = Math.min(worstWeaponScore, wScore);
      } else if (slot.kind === 'item') {
        const uVal = getBotUtilityValue(slot.id as UtilityItemId, slot.rarity);
        worstUtilityValue = Math.min(worstUtilityValue, uVal);
      }
    }
    if (weaponCount === 0) worstWeaponScore = 0;

    let best: { loot: BotLootSnapshot; dist: number; value: number } | null = null;
    for (const loot of world.lootDrops) {
      // Never re-pick loot this bot just dropped (prevents any residual drop/pickup loop)
      if (
        loot.droppedById === self.id &&
        loot.droppedAt !== undefined &&
        world.time - loot.droppedAt < BOT_DROP_IGNORE_SEC
      ) {
        continue;
      }
      // Skip loot on a different floor (e.g. rooftop loot when bot is looting inside ground-floor office)
      if (Math.abs(loot.y - self.pos.y) > 2.8) continue;
      const d = Math.hypot(loot.x - self.pos.x, loot.z - self.pos.z);
      if (d > searchRadius) continue;

      let value = 0;
      if (loot.kind === 'weapon') {
        const rScore = RARITY_SCORE[loot.rarity];
        const sameWeaponUpgrade = self.slots.some(
          (s) => s !== null && s.kind === 'weapon' && s.id === loot.itemId && rScore > RARITY_SCORE[s.rarity]
        );
        if (unarmed) {
          // Immediately grab ANY weapon dropped from an opened chest!
          value = 110 + rScore * 16 + (d < 6 ? 45 : 0);
        } else if (hasEmptySlot) {
          if (rScore > bestWeaponScore || weaponCount < 2 || rScore >= 2) {
            value = rScore * 22 * this.profile.lootUpgradeDesire + (d < 5.5 ? 16 : 0);
          }
        } else if (sameWeaponUpgrade || (weaponCount > 0 && rScore > worstWeaponScore)) {
          // Full inventory: only upgrade an existing weapon in-place or strictly upgrade worst carried weapon
          value = rScore * 22 * this.profile.lootUpgradeDesire + (d < 5.5 ? 16 : 0);
        }
      } else {
        const uId = loot.itemId as UtilityItemId;
        const existingIdx = this.findItemSlot(self, uId);
        const existingSlot = existingIdx !== -1 ? self.slots[existingIdx] : null;
        const isShield = uId === 'shield_cell' || uId === 'shield_jug';
        if (unarmed) {
          // Only grab adjacent utility if right at feet (< 4.5m) and it can fit/stack; weapons remain top priority
          if (d < 4.5) {
            const canTakeUnarmed = existingSlot
              ? (existingSlot.count ?? 0) < UTILITY_ITEMS[uId].maxStack ||
                RARITY_SCORE[loot.rarity] > RARITY_SCORE[existingSlot.rarity]
              : hasEmptySlot;
            if (canTakeUnarmed) {
              value = isShield ? 26 : 16;
            }
          }
        } else if (existingSlot) {
          const canStack = (existingSlot.count ?? 0) < UTILITY_ITEMS[uId].maxStack;
          const canUpgradeRarityInPlace = RARITY_SCORE[loot.rarity] > RARITY_SCORE[existingSlot.rarity];
          if (canStack || canUpgradeRarityInPlace) {
            value =
              (8 + (canUpgradeRarityInPlace ? 10 : 0) + (isShield && self.shield < 50 ? 10 : 0)) *
              this.profile.lootUpgradeDesire;
          }
        } else if (hasEmptySlot) {
          const shieldBonus = isShield && self.shield < 60 ? 18 : 0;
          value =
            (14 + RARITY_SCORE[loot.rarity] * 6 + shieldBonus) * this.profile.lootUpgradeDesire +
            (d < 5.5 ? 18 : 0);
        } else if (
          worstUtilityValue < Infinity &&
          getBotUtilityValue(uId, loot.rarity) >= worstUtilityValue + BOT_UTILITY_SWAP_HYSTERESIS
        ) {
          // Full inventory: strictly higher monotonic utility value with hysteresis margin (ping-pong impossible)
          const shieldBonus = isShield && self.shield < 60 ? 18 : 0;
          value =
            (14 + RARITY_SCORE[loot.rarity] * 6 + shieldBonus) * this.profile.lootUpgradeDesire +
            (d < 5.5 ? 18 : 0);
        }
      }

      if (value <= 0) continue;
      const score = value - d * 0.45;
      if (score > 4 && (!best || score > best.value)) {
        best = { loot, dist: d, value: score };
      }
    }
    return best ? { loot: best.loot, dist: best.dist } : null;
  }

  /**
   * Hero-specific Product Ultimate decision heuristics across all 6 Workspace heroes (Spec §6 & §16).
   */
  private shouldCastUltimate(
    self: BotCombatantSnapshot,
    world: BotWorldContext,
    target: BotCombatantSnapshot | null,
    targetDist: number,
    targetHasLos: boolean
  ): boolean {
    if (self.ultCooldown > 0 || self.silencedSec > 0) return false;

    const ultCost = HERO_MAP[self.heroId].ultimate.manaCost;
    if (self.mana < ultCost) return false;

    // Tier 1 (Casual): simple proximity cast
    if (this.profile.ultimateSmartness === 'basic') {
      return target !== null && targetDist < 25;
    }

    const isOptimal = this.profile.ultimateSmartness === 'optimal';
    const vitals = self.health + self.shield;

    switch (self.heroId) {
      case 'gmail': {
        // Reply-All Barrage: strong multi-target or mid-range flush-out
        if (!target) return false;
        let nearbyEnemies = 0;
        for (const c of world.combatants) {
          if (c.id !== self.id && c.alive && !c.skyDropping && self.pos.distanceTo(c.pos) < 42) {
            nearbyEnemies++;
          }
        }
        return nearbyEnemies >= 2 || (targetDist > 8 && targetDist < 38 && (targetHasLos || isOptimal));
      }
      case 'drive': {
        // Access Revoked: anti-rush guardrail + cancel enemy channels + shield emergency
        if (!target) return false;
        if (isOptimal && target.channeling && targetDist < 15.5) return true;
        return targetDist < 15 || (targetDist < 28 && vitals < 115 && targetHasLos);
      }
      case 'calendar': {
        // Hard Stop: 20m chrono-field to dominate 1v1 duels
        return target !== null && targetDist < 18.5 && (targetHasLos || isOptimal);
      }
      case 'chat': {
        // @all Ping Overload: 28m disruptor wave + global recon reveal
        if (!target) {
          return isOptimal && world.combatants.filter((c) => c.alive && c.id !== self.id).length >= 2 && Math.random() < 0.02;
        }
        return targetDist < 26;
      }
      case 'slides': {
        // Executive Spotlight: piercing 85m orbital beam along clear line of sight
        return target !== null && targetHasLos && targetDist >= 10 && targetDist <= 78;
      }
      case 'docs': {
        // Version History: clutch 4s rollback when hurt or burst-damaged while saved snapshot is healthier
        const savedVitals = self.docsHistoryHealth + self.docsHistoryShield;
        const gainsVitals = savedVitals >= vitals + (isOptimal ? 28 : 35);
        const underBurst = self.recentDamageTaken >= 32 && world.time - self.lastDamagedAt < 1.8;
        return (self.health < 50 && gainsVitals) || (isOptimal && underBurst && gainsVitals);
      }
    }
  }
}

import * as THREE from 'three';
import {
  alignWeaponTwoHanded,
  AssetManager,
  HeroInstance,
  LootChestVisual,
  WeaponInstance,
} from '../core/assetManager';
import { PhysicsWorld } from '../core/physics';
import { AnimName, ProductHeroId, Rarity, WeaponId } from '../types';
import { GoogleplexWorld } from '../world/googleplex';
import { PersistentZoneVisual, VfxSystem } from './vfx';

export interface SplashSceneMeta {
  index: number;
  title: string;
  subtitle: string;
  location: string;
  durationSec: number;
}

export interface SplashAttractState {
  active: boolean;
  sceneIndex: number;
  sceneProgress: number; // 0..1 within active scene
  scenes: SplashSceneMeta[];
}

export const SPLASH_SCENES_META: readonly SplashSceneMeta[] = [
  {
    index: 0,
    title: 'Sky-Drop Formation',
    subtitle: 'Unarmed glider drop over Mountain View Googleplex',
    location: 'Stan Plaza & B40 Core',
    durationSec: 5.5,
  },
  {
    index: 1,
    title: 'Art Garden & Gym Skirmish',
    subtitle: 'Tactical cover firefights & Guardrail Dome defense',
    location: 'Charleston Art Garden & Outdoor Gym',
    durationSec: 6.0,
  },
  {
    index: 2,
    title: 'Skybridge Ultimate Clash',
    subtitle: 'Chrono-fields, Orbital Beams & Tier 3 Vault Chests',
    location: 'Stan Plaza & Central Glass Skybridge',
    durationSec: 6.0,
  },
  {
    index: 3,
    title: '3× Mountain View Campus',
    subtitle: '600m × 380m open arena — 31 landmarks & 165 chests',
    location: 'Gradient Canopy · Shoreline · Bay Point',
    durationSec: 5.5,
  },
];

export const DEFAULT_LOBBY_FOV = 76;

/** Exact calibrated wrist-to-palm glider control bar offset (matches engine.ts 1:1). */
const GLIDE_MOUNT_LOCAL_OFFSET = new THREE.Vector3(0.0, 0.076, -0.056);

/** Exact calibrated Loot Chest lid open angle (+100° upward/backward on rear hinge). */
const CHEST_LID_OPEN_ANGLE_RAD = 1.745;

interface AttractHeroLoadout {
  heroId: ProductHeroId;
  weaponId: WeaponId;
  rarity: Rarity;
}

const ATTRACT_CAST: readonly AttractHeroLoadout[] = [
  { heroId: 'gmail', weaponId: 'vanguard_m4', rarity: 'rare' },
  { heroId: 'drive', weaponId: 'breaker_12g', rarity: 'epic' },
  { heroId: 'calendar', weaponId: 'vanguard_m4', rarity: 'common' },
  { heroId: 'chat', weaponId: 'vector_9', rarity: 'rare' },
  { heroId: 'slides', weaponId: 'longbow_308', rarity: 'epic' },
  { heroId: 'docs', weaponId: 'nova_gl40', rarity: 'epic' },
];

interface AttractActor {
  heroId: ProductHeroId;
  hero: HeroInstance;
  weapon: WeaponInstance;
  glider: THREE.Group;
  gliding: boolean;
}

interface ActiveAttractZone {
  visual: PersistentZoneVisual;
  center: THREE.Vector3;
  radius: number;
  elapsed: number;
  duration: number;
  kind: 'guardrail' | 'chrono';
}

export interface SplashAttractDeps {
  scene: THREE.Scene;
  assetManager: AssetManager;
  physics: PhysicsWorld;
  vfx: VfxSystem;
}

function clamp01(v: number): number {
  return v < 0 ? 0 : v > 1 ? 1 : v;
}

function smoothstep01(t: number): number {
  const u = clamp01(t);
  return u * u * (3 - 2 * u);
}

function easeOutCubic(t: number): number {
  const u = clamp01(t);
  return 1 - Math.pow(1 - u, 3);
}

/**
 * Computes Three.js hero Y-rotation yaw so a hero facing local `-Z` looks from `(x, z)` toward `(tx, tz)`.
 */
function yawToward(x: number, z: number, tx: number, tz: number): number {
  const dx = tx - x;
  const dz = tz - z;
  if (dx * dx + dz * dz < 1e-6) return 0;
  return Math.atan2(-dx, -dz);
}

/**
 * Evaluates a cubic Bézier curve into `out`.
 */
function evalCubicBezier(
  p0: THREE.Vector3,
  p1: THREE.Vector3,
  p2: THREE.Vector3,
  p3: THREE.Vector3,
  t: number,
  out: THREE.Vector3
): THREE.Vector3 {
  const u = clamp01(t);
  const inv = 1 - u;
  const b0 = inv * inv * inv;
  const b1 = 3 * inv * inv * u;
  const b2 = 3 * inv * u * u;
  const b3 = u * u * u;
  return out.set(
    b0 * p0.x + b1 * p1.x + b2 * p2.x + b3 * p3.x,
    b0 * p0.y + b1 * p1.y + b2 * p2.y + b3 * p3.y,
    b0 * p0.z + b1 * p1.z + b2 * p2.z + b3 * p3.z
  );
}

// Scene 3 golden-hour helicopter flyover splines (Gradient Canopy -> Shoreline -> Bay Point -> Googleplex Quad)
const S3_CAM_P0 = new THREE.Vector3(166, 52, 48);
const S3_CAM_P1 = new THREE.Vector3(136, 66, -88);
const S3_CAM_P2 = new THREE.Vector3(18, 72, -184);
const S3_CAM_P3 = new THREE.Vector3(-92, 56, -86);

const S3_LOOK_P0 = new THREE.Vector3(106, 8, -2);
const S3_LOOK_P1 = new THREE.Vector3(58, 12, -136);
const S3_LOOK_P2 = new THREE.Vector3(-48, 8, -118);
const S3_LOOK_P3 = new THREE.Vector3(-46, 8, 4);

/**
 * Live 3D Gameplay Attract Reel Director for the Splash Screen.
 * Runs 4 choreographed real-engine scenes across the 3× Mountain View Googleplex campus
 * with all 6 rigged Product Icon AIs, bespoke skinned weapons, hand-locked gliders,
 * live Ultimates, and a real Tier 3 Vault Loot Chest.
 */
export class SplashAttractDirector {
  private readonly scene: THREE.Scene;
  private readonly assetManager: AssetManager;
  private readonly physics: PhysicsWorld;
  private readonly vfx: VfxSystem;

  private attractGroup: THREE.Group | null = null;
  private actors = new Map<ProductHeroId, AttractActor>();
  private lootChest: LootChestVisual | null = null;
  private supplyDropCrate: THREE.Group | null = null;
  private supplyDropBeacon: THREE.Group | null = null;
  private activeZones: ActiveAttractZone[] = [];

  private active = false;
  private sceneIndex = 0;
  private sceneElapsed = 0;
  private gliderTrailAccum = 0;
  private docsGhostAccum = 0;
  private firedCues = new Set<string>();
  private chestPopDone = false;

  // Scratch math objects (zero per-frame heap churn)
  private readonly tmpA = new THREE.Vector3();
  private readonly tmpB = new THREE.Vector3();
  private readonly tmpC = new THREE.Vector3();
  private readonly tmpCamPos = new THREE.Vector3();
  private readonly tmpLookAt = new THREE.Vector3();
  private readonly tmpFocus = new THREE.Vector3();
  private readonly tmpMuzzle = new THREE.Vector3();
  private readonly tmpTarget = new THREE.Vector3();
  private readonly tmpDir = new THREE.Vector3();
  private readonly tmpHit = new THREE.Vector3();
  private readonly tmpDomeCenter = new THREE.Vector3();

  constructor(deps: SplashAttractDeps) {
    this.scene = deps.scene;
    this.assetManager = deps.assetManager;
    this.physics = deps.physics;
    this.vfx = deps.vfx;
  }

  public isActive(): boolean {
    return this.active;
  }

  public getState(): SplashAttractState {
    const meta = SPLASH_SCENES_META[this.sceneIndex] ?? SPLASH_SCENES_META[0];
    const progress =
      this.active && meta.durationSec > 0 ? clamp01(this.sceneElapsed / meta.durationSec) : 0;
    return {
      active: this.active,
      sceneIndex: this.sceneIndex,
      sceneProgress: progress,
      scenes: SPLASH_SCENES_META.map((s) => ({ ...s })),
    };
  }

  /**
   * Spawns attract actors once inside `SplashAttractGroup` and launches live attract playback.
   */
  public start(
    initialSceneIndex = 0,
    camera?: THREE.PerspectiveCamera,
    world?: GoogleplexWorld
  ): void {
    if (this.active) {
      if (initialSceneIndex !== this.sceneIndex) {
        this.setScene(initialSceneIndex, camera, world);
      }
      return;
    }

    this.buildAttractRig();
    this.active = true;
    const safeIdx = this.normalizeSceneIndex(initialSceneIndex);
    this.enterScene(safeIdx, camera, world);
  }

  /**
   * Immediately jumps to scene `index` (0..3), clearing transient VFX & persistent zones cleanly.
   */
  public setScene(
    index: number,
    camera?: THREE.PerspectiveCamera,
    world?: GoogleplexWorld
  ): void {
    const safeIdx = this.normalizeSceneIndex(index);
    if (!this.active) {
      this.sceneIndex = safeIdx;
      this.sceneElapsed = 0;
      return;
    }
    this.enterScene(safeIdx, camera, world);
  }

  /**
   * Cleanly tears down all attract meshes, mixers, persistent zones, and transient VFX,
   * and restores the default lobby camera FOV (`76°`).
   */
  public stop(camera?: THREE.PerspectiveCamera): void {
    this.disposeActiveZones();
    this.vfx.clear();

    // Stop and uncache every hero mixer cleanly so no animation state lingers
    for (const actor of this.actors.values()) {
      actor.hero.revealRing.visible = false;
      actor.hero.clearFlash();
      actor.hero.mixer.stopAllAction();
      actor.hero.mixer.uncacheRoot(actor.hero.model);
    }
    this.actors.clear();

    // Dispose locally constructed Supply Drop beacon geometries & materials (skipping shared RingGeometry)
    if (this.supplyDropBeacon) {
      this.supplyDropBeacon.traverse((obj) => {
        if ((obj as THREE.Mesh).isMesh) {
          const mesh = obj as THREE.Mesh;
          if (mesh.geometry instanceof THREE.CylinderGeometry) {
            mesh.geometry.dispose();
          }
          if (Array.isArray(mesh.material)) {
            mesh.material.forEach((m) => m.dispose());
          } else if (mesh.material) {
            mesh.material.dispose();
          }
        }
      });
      this.supplyDropBeacon = null;
    }

    this.supplyDropCrate = null;
    this.lootChest = null;

    if (this.attractGroup) {
      this.scene.remove(this.attractGroup);
      this.attractGroup = null;
    }

    this.firedCues.clear();
    this.gliderTrailAccum = 0;
    this.docsGhostAccum = 0;
    this.chestPopDone = false;
    this.sceneElapsed = 0;
    this.active = false;

    if (camera) {
      camera.up.set(0, 1, 0);
      if (Math.abs(camera.fov - DEFAULT_LOBBY_FOV) > 0.01) {
        camera.fov = DEFAULT_LOBBY_FOV;
        camera.updateProjectionMatrix();
      }
    }
  }

  /**
   * Advances the active choreographed scene, hero animations, two-handed weapon & glider locks,
   * timed VFX cues, persistent zones, camera trajectory, and shadow focus.
   */
  public update(dt: number, camera: THREE.PerspectiveCamera, world: GoogleplexWorld): void {
    if (!this.active || !this.attractGroup) return;

    const safeDt = Math.min(0.05, Math.max(0.0005, Number.isFinite(dt) ? dt : 0.016));
    const meta = SPLASH_SCENES_META[this.sceneIndex] ?? SPLASH_SCENES_META[0];
    this.sceneElapsed += safeDt;

    if (this.sceneElapsed >= meta.durationSec) {
      const nextIndex = (this.sceneIndex + 1) % SPLASH_SCENES_META.length;
      this.enterScene(nextIndex, camera, world);
      return;
    }

    this.evaluateCurrentScene(safeDt, camera, world, false);
  }

  // =========================================================================
  // RIG CONSTRUCTION & SCENE LIFECYCLE
  // =========================================================================

  private normalizeSceneIndex(index: number): number {
    const count = SPLASH_SCENES_META.length;
    if (!Number.isFinite(index)) return 0;
    return ((Math.floor(index) % count) + count) % count;
  }

  private buildAttractRig(): void {
    if (this.attractGroup) {
      this.scene.remove(this.attractGroup);
    }

    const group = new THREE.Group();
    group.name = 'SplashAttractGroup';
    this.scene.add(group);
    this.attractGroup = group;

    this.actors.clear();
    for (const cast of ATTRACT_CAST) {
      const hero = this.assetManager.instantiateHero(cast.heroId, { includeOverhead: false });
      hero.overheadGroup.visible = false;
      hero.revealRing.visible = false;
      group.add(hero.root);

      const weapon = this.assetManager.instantiateWeapon(cast.weaponId, cast.rarity);
      hero.weaponSocket.add(weapon.root);
      weapon.root.visible = false;

      const glider = this.assetManager.instantiateProp('glider');
      glider.position.set(0, 0, 0);
      hero.gliderMount.add(glider);
      glider.visible = false;

      this.actors.set(cast.heroId, {
        heroId: cast.heroId,
        hero,
        weapon,
        glider,
        gliding: false,
      });
    }

    // Real Tier 3 Vault Loot Chest for Scene 2 ("Skybridge Ultimate Clash")
    const chest = this.assetManager.instantiateLootChest(3);
    chest.root.visible = false;
    group.add(chest.root);
    this.lootChest = chest;

    // Real Supply Drop crate & sky beacon for Scene 3 ("3× Mountain View Campus")
    const crate = this.assetManager.instantiateProp('supply_drop');
    crate.visible = false;
    group.add(crate);
    this.supplyDropCrate = crate;

    const beacon = this.vfx.createSupplyDropBeacon();
    beacon.visible = false;
    group.add(beacon);
    this.supplyDropBeacon = beacon;
  }

  private disposeActiveZones(): void {
    for (const z of this.activeZones) {
      z.visual.dispose();
    }
    this.activeZones.length = 0;
  }

  private enterScene(
    index: number,
    camera?: THREE.PerspectiveCamera,
    world?: GoogleplexWorld
  ): void {
    this.disposeActiveZones();
    this.vfx.clear();

    this.sceneIndex = index;
    this.sceneElapsed = 0;
    this.gliderTrailAccum = 0;
    this.docsGhostAccum = 0;
    this.firedCues.clear();
    this.chestPopDone = false;

    // Reset all actors cleanly before staging the newly selected scene
    for (const actor of this.actors.values()) {
      actor.hero.root.visible = false;
      actor.hero.model.rotation.set(0, 0, 0);
      actor.hero.model.position.set(0, 0, 0);
      actor.hero.model.scale.set(1, 1, 1);
      actor.hero.revealRing.visible = false;
      actor.hero.clearFlash();
      actor.glider.visible = false;
      actor.weapon.root.visible = false;
      actor.gliding = false;
    }

    if (this.lootChest) {
      this.lootChest.root.visible = false;
      this.lootChest.beam.visible = true;
      this.lootChest.ring.scale.setScalar(1);
      if (this.lootChest.lidNode) {
        this.lootChest.lidNode.rotation.x = 0;
      }
    }
    if (this.supplyDropCrate) {
      this.supplyDropCrate.visible = false;
    }
    if (this.supplyDropBeacon) {
      this.supplyDropBeacon.visible = false;
    }

    // Pre-pose the initial frame immediately so scene cuts have zero 1-frame T-pose or jump
    if (camera && world) {
      this.evaluateCurrentScene(0.001, camera, world, true);
    }
  }

  private evaluateCurrentScene(
    dt: number,
    camera: THREE.PerspectiveCamera,
    world: GoogleplexWorld,
    snapAnims: boolean
  ): void {
    // Tick active persistent zones (Drive Guardrail Dome, Calendar Chrono-Field)
    for (let i = this.activeZones.length - 1; i >= 0; i--) {
      const zone = this.activeZones[i];
      zone.elapsed += dt;
      const remaining = Math.max(0, zone.duration - zone.elapsed);
      zone.visual.update(dt, zone.elapsed, remaining);
      if (zone.elapsed >= zone.duration) {
        zone.visual.dispose();
        this.activeZones.splice(i, 1);
      }
    }

    let targetFov = DEFAULT_LOBBY_FOV;
    switch (this.sceneIndex) {
      case 0:
        targetFov = this.updateScene0SkyDrop(dt, snapAnims);
        break;
      case 1:
        targetFov = this.updateScene1ArtGardenSkirmish(dt, snapAnims);
        break;
      case 2:
        targetFov = this.updateScene2SkybridgeUltimates(dt, snapAnims);
        break;
      case 3:
      default:
        targetFov = this.updateScene3CampusFlyover(dt, snapAnims);
        break;
    }

    // Advance mixers & lock gliders / two-handed weapons for every visible actor
    for (const actor of this.actors.values()) {
      if (!actor.hero.root.visible) continue;
      actor.hero.mixer.update(dt);
      if (actor.gliding) {
        this.syncGliderMountToHands(actor.hero);
      } else if (actor.weapon.root.visible) {
        alignWeaponTwoHanded(actor.weapon.root, actor.hero, {
          weaponId: actor.weapon.weaponId,
        });
      }
    }

    // Apply camera FOV, position, look target, and update world shadow/lighting focus
    this.applyCameraSafe(camera, targetFov, this.tmpCamPos, this.tmpLookAt);
    world.updatePerformanceFocus(this.tmpFocus.x, this.tmpFocus.y, this.tmpFocus.z);
  }

  // =========================================================================
  // SCENE 0: "Sky-Drop Formation" (5.5s) — Stan Plaza & B40 Core
  // =========================================================================

  private updateScene0SkyDrop(dt: number, snapAnims: boolean): number {
    const dur = SPLASH_SCENES_META[0].durationSec;
    const t = this.sceneElapsed;
    const p = clamp01(t / dur);

    // Lead Gmail glides diagonally NW -> SE directly over Glass Skybridge, Stan Plaza (-51, 4), and B40 Core
    // Heading SE faces directly into late-afternoon California sunlight (+115, +138, +82) for crisp front lighting!
    const leadX = THREE.MathUtils.lerp(-84, -22, p);
    const leadY = THREE.MathUtils.lerp(47.5, 22.0, p) + Math.sin(p * Math.PI * 1.5) * 0.7;
    const leadZ = THREE.MathUtils.lerp(-20, 15, p);

    const vx = -22 - -84; // +62
    const vz = 15 - -20; // +35
    const vLen = Math.hypot(vx, vz) || 1;
    const fwdX = vx / vLen;
    const fwdZ = vz / vLen;
    // Right vector in XZ plane: cross(fwd, up) = (-fwdZ, 0, fwdX)
    const rightX = -fwdZ;
    const rightZ = fwdX;
    const baseYaw = yawToward(0, 0, fwdX, fwdZ);

    const formation: {
      id: ProductHeroId;
      fwd: number;
      right: number;
      up: number;
      phase: number;
      weaveAmp: number;
    }[] = [
      { id: 'gmail', fwd: 0.0, right: 0.0, up: 0.0, phase: 0.0, weaveAmp: 0.65 },
      { id: 'drive', fwd: -3.2, right: 3.4, up: 0.85, phase: 1.1, weaveAmp: 0.8 },
      { id: 'calendar', fwd: -3.4, right: -3.4, up: 0.7, phase: 2.3, weaveAmp: 0.75 },
      { id: 'chat', fwd: -6.7, right: 6.8, up: 1.9, phase: 3.4, weaveAmp: 0.9 },
      { id: 'slides', fwd: -6.9, right: -6.8, up: 1.75, phase: 4.5, weaveAmp: 0.85 },
      { id: 'docs', fwd: -9.4, right: 1.1, up: 2.9, phase: 5.2, weaveAmp: 0.7 },
    ];

    this.gliderTrailAccum += dt;
    const emitTrail = this.gliderTrailAccum >= 0.09;
    if (emitTrail) {
      this.gliderTrailAccum = 0;
    }

    for (const slot of formation) {
      const actor = this.actors.get(slot.id);
      if (!actor) continue;

      const sway = Math.sin(t * 1.45 + slot.phase) * slot.weaveAmp;
      const swayVel = Math.cos(t * 1.45 + slot.phase) * slot.weaveAmp * 1.45;
      const bob = Math.sin(t * 1.85 + slot.phase * 0.8) * 0.42;

      const x = leadX + fwdX * slot.fwd + rightX * (slot.right + sway);
      const y = leadY + slot.up + bob;
      const z = leadZ + fwdZ * slot.fwd + rightZ * (slot.right + sway);

      actor.hero.root.visible = true;
      actor.hero.root.position.set(x, y, z);
      actor.hero.root.rotation.set(0, baseYaw - swayVel * 0.06, 0);
      actor.hero.model.rotation.set(-0.14 + Math.cos(t * 1.6 + slot.phase) * 0.035, 0, -swayVel * 0.22);

      actor.gliding = true;
      actor.glider.visible = true;
      actor.weapon.root.visible = false;
      this.setActorClip(actor, 'Glide', snapAnims ? 0 : 0.12);

      if (emitTrail) {
        actor.hero.root.updateMatrixWorld(true);
        this.emitGliderWingtipTrails(actor.hero);
      }
    }

    // Sweeping aerial tracking camera gliding ahead & alongside lead Gmail & Drive,
    // arcing cleanly from heroic front-right 3/4 to sweeping wing-flank framing Stan Plaza & B40 below
    const camS = smoothstep01(p);
    const camFwdOff = THREE.MathUtils.lerp(11.2, 5.2, camS);
    const camRightOff = THREE.MathUtils.lerp(6.8, 12.6, camS);
    const camUpOff = THREE.MathUtils.lerp(3.2, 6.2, camS);

    this.tmpCamPos.set(
      leadX + fwdX * camFwdOff + rightX * camRightOff,
      leadY + camUpOff,
      leadZ + fwdZ * camFwdOff + rightZ * camRightOff
    );
    this.tmpLookAt.set(
      leadX - fwdX * 3.8,
      leadY - 2.4,
      leadZ - fwdZ * 3.8
    );
    // Keep shadow frustum anchored over Stan Plaza & the gliding formation below
    this.tmpFocus.set(leadX, 4, leadZ);

    return 64;
  }

  // =========================================================================
  // SCENE 1: "Art Garden & Gym Skirmish" (6.0s) — Charleston Art Garden (30, -8)
  // =========================================================================

  private updateScene1ArtGardenSkirmish(_dt: number, snapAnims: boolean): number {
    const dur = SPLASH_SCENES_META[1].durationSec;
    const t = this.sceneElapsed;
    const p = clamp01(t / dur);

    // Every path verified >= 0.85m clear of Charleston Art Garden monolith (30±1.2, -8±1.2),
    // 4 staggered limestone walls, 4 raised planters, and surrounding live oak / redwood trunks!

    // 1. Gmail AI (vanguard_m4 'rare'): sprints onto SW travertine plaza -> plants in Aim firing at Drive
    const gmail = this.actors.get('gmail');
    const gmailMove = smoothstep01(t / 1.35);
    const gmailX = THREE.MathUtils.lerp(22.6, 26.4, gmailMove);
    const gmailZ = THREE.MathUtils.lerp(-1.2, -2.2, gmailMove);
    const gmailY = this.getGroundHeight(gmailX, gmailZ);

    // 2. Drive AI (breaker_12g 'epic'): advances in East travertine lane -> aims SW & pops Guardrail Dome at t=1.6s
    const drive = this.actors.get('drive');
    const driveMove = smoothstep01(t / 1.3);
    const driveX = THREE.MathUtils.lerp(34.4, 34.2, driveMove);
    const driveZ = THREE.MathUtils.lerp(-9.6, -8.4, driveMove);
    const driveY = this.getGroundHeight(driveX, driveZ);

    // 3. Chat AI (vector_9 'rare'): flanks along open SE edge -> Crouch peek -> rises & emits ChatPingWave at t=3.6s
    const chat = this.actors.get('chat');
    let chatX = 37.4;
    let chatZ = 0.6;
    let chatAnim: AnimName = 'Crouch';
    let chatYaw = yawToward(chatX, chatZ, driveX, driveZ);
    if (t < 1.55) {
      const cm = smoothstep01(t / 1.55);
      chatX = THREE.MathUtils.lerp(39.4, 37.4, cm);
      chatZ = THREE.MathUtils.lerp(5.2, 0.6, cm);
      chatAnim = 'SprintArmed';
      chatYaw = yawToward(39.4, 5.2, 37.4, 0.6);
    } else if (t < 3.35) {
      chatX = 37.4;
      chatZ = 0.6;
      chatAnim = 'Crouch';
      chatYaw = yawToward(chatX, chatZ, driveX, driveZ);
    } else {
      const rise = smoothstep01((t - 3.35) / 1.1);
      chatX = THREE.MathUtils.lerp(37.4, 36.2, rise);
      chatZ = THREE.MathUtils.lerp(0.6, 0.2, rise);
      chatAnim = 'Aim';
      chatYaw = yawToward(chatX, chatZ, driveX, driveZ);
    }
    const chatY = this.getGroundHeight(chatX, chatZ);

    // 4. Slides AI (longbow_308 'epic'): perched cleanly on North-East garden rim (clear of North wall & NE planter)
    const slides = this.actors.get('slides');
    const slidesX = 32.0;
    const slidesZ = -12.5;
    const slidesY = this.getGroundHeight(slidesX, slidesZ);

    if (gmail) {
      const gmailAiming = t >= 1.35;
      const gYaw = gmailAiming
        ? yawToward(gmailX, gmailZ, driveX, driveZ)
        : yawToward(22.6, -1.2, 26.4, -2.2);
      this.placeGroundArmedActor(
        gmail,
        gmailX,
        gmailY,
        gmailZ,
        gYaw,
        gmailAiming ? 'Aim' : 'SprintArmed',
        snapAnims
      );
    }

    if (drive) {
      const driveAiming = t >= 1.3;
      const dYaw = driveAiming
        ? yawToward(driveX, driveZ, gmailX, gmailZ)
        : yawToward(34.4, -9.6, 34.2, -8.4);
      this.placeGroundArmedActor(
        drive,
        driveX,
        driveY,
        driveZ,
        dYaw,
        driveAiming ? 'Aim' : 'RunArmed',
        snapAnims
      );
      drive.hero.revealRing.visible = t >= 3.7 && t <= 5.5;
    }

    if (chat) {
      this.placeGroundArmedActor(chat, chatX, chatY, chatZ, chatYaw, chatAnim, snapAnims);
    }

    if (slides) {
      const sYaw = yawToward(slidesX, slidesZ, chatX, chatZ);
      this.placeGroundArmedActor(slides, slidesX, slidesY, slidesZ, sYaw, 'Aim', snapAnims);
      slides.hero.revealRing.visible = t >= 3.75 && t <= 5.5;
    }

    // --- Timed Live Combat & Ultimate VFX Beats ---
    const domeCenter = this.tmpDomeCenter.set(34.2, driveY, -8.4);
    const domeRadius = 8.5;

    // Pre-dome opening crossfire
    if (this.consumeCue('s1_shot_slides_1', t >= 0.75) && slides) {
      this.fireWeaponTracer(slides, chatX, chatY + 1.2, chatZ, 0xfef08a, 0.042, 0.14, { isShield: true });
    }
    if (this.consumeCue('s1_shot_drive_1', t >= 1.15) && drive) {
      this.fireShotgunSpread(drive, gmailX, gmailY + 1.15, gmailZ, { isShield: true });
    }
    if (this.consumeCue('s1_shot_gmail_1', t >= 1.42) && gmail) {
      this.fireWeaponTracer(gmail, driveX, driveY + 1.25, driveZ, 0xffe49c, 0.036, 0.12, { isShield: true });
    }

    // t = 1.6s: Drive AI deploys shimmering Guardrail Dome (radius = 8.5m)
    if (this.consumeCue('s1_drive_dome', t >= 1.6)) {
      const centerClone = new THREE.Vector3(34.2, driveY, -8.4);
      const visual = this.vfx.createDriveGuardrailDome(centerClone, domeRadius);
      this.activeZones.push({
        visual,
        center: centerClone,
        radius: domeRadius,
        elapsed: 0,
        duration: 4.35,
        kind: 'guardrail',
      });
    }

    // Guardrail Dome intercept bursts from Gmail (9.96m away) & Chat (9.55m away)
    const gmailInterceptTimes = [1.88, 2.18, 2.52, 3.05, 4.10, 4.62, 5.20];
    for (let i = 0; i < gmailInterceptTimes.length; i++) {
      if (this.consumeCue(`s1_gmail_dome_${i}`, t >= gmailInterceptTimes[i]) && gmail) {
        this.fireAtGuardrailDome(gmail, domeCenter, domeRadius, 0xffe49c, 1.25 + (i % 3) * 0.25);
      }
    }

    const chatInterceptTimes = [2.02, 2.34, 2.74, 3.22, 4.32, 4.88, 5.42];
    for (let i = 0; i < chatInterceptTimes.length; i++) {
      if (this.consumeCue(`s1_chat_dome_${i}`, t >= chatInterceptTimes[i]) && chat) {
        this.fireAtGuardrailDome(chat, domeCenter, domeRadius, 0x6ee7b7, 1.15 + (i % 2) * 0.35);
      }
    }

    // Counterfire from Drive & Slides across the garden
    if (this.consumeCue('s1_slides_2', t >= 2.45) && slides) {
      this.fireWeaponTracer(slides, chatX, chatY + 1.1, chatZ, 0xfef08a, 0.044, 0.14, { isHeadshot: true });
    }
    if (this.consumeCue('s1_drive_2', t >= 2.95) && drive) {
      this.fireShotgunSpread(drive, gmailX, gmailY + 1.2, gmailZ, { isWorld: true });
    }

    // t = 3.6s: Chat AI emits expanding emerald sonar Ping Wave across Charleston Park
    if (this.consumeCue('s1_chat_ping', t >= 3.6)) {
      this.vfx.spawnChatPingWave(new THREE.Vector3(chatX, chatY, chatZ), 24);
    }

    if (this.consumeCue('s1_slides_3', t >= 4.45) && slides) {
      this.fireWeaponTracer(slides, gmailX, gmailY + 1.35, gmailZ, 0xfef08a, 0.044, 0.14, { isShield: true });
    }
    if (this.consumeCue('s1_drive_3', t >= 5.05) && drive) {
      this.fireShotgunSpread(drive, chatX, chatY + 1.2, chatZ, { isShield: true });
    }

    // Smooth low-angle heroic dolly orbiting the north rim of Charleston Art Garden (clear of all trees!)
    // Frames Slides sniper foreground, 4-color kinetic monolith (30, -8), Drive Guardrail Dome,
    // advancing Gmail & Chat firefights, AND Charleston Outdoor Gym (32, 30) in the sunlit park vista beyond!
    const orbitS = smoothstep01(p);
    this.tmpCamPos.set(
      THREE.MathUtils.lerp(24.5, 36.2, orbitS),
      6.4 + Math.sin(p * Math.PI) * 1.4,
      THREE.MathUtils.lerp(-21.2, -20.4, orbitS)
    );
    this.tmpLookAt.set(
      THREE.MathUtils.lerp(30.8, 31.4, orbitS),
      1.95,
      THREE.MathUtils.lerp(-6.2, -5.2, orbitS)
    );
    this.tmpFocus.set(30.8, 1.5, -6.5);

    return 56;
  }

  // =========================================================================
  // SCENE 2: "Skybridge Ultimate Clash" (6.0s) — Stan Plaza & Glass Skybridge
  // =========================================================================

  private updateScene2SkybridgeUltimates(dt: number, snapAnims: boolean): number {
    const dur = SPLASH_SCENES_META[2].durationSec;
    const t = this.sceneElapsed;
    const p = clamp01(t / dur);

    // Every actor & chest path verified clear of Stan pedestal (-51, 4, r=3.9m apron),
    // all Stan Plaza umbrella tables (-44, 11.5), (-58.5, 10.0), (-41.5, -1.5), (-39, 5.5),
    // Charlie's espresso bar (-43, -6.5), B40/B43 walls, and Skybridge piers!

    // 1. Calendar AI (vanguard_m4 'common'): dashes across Stan Plaza -> pops Chrono-Field at t=0.8s
    const calendar = this.actors.get('calendar');
    const calSprint = smoothstep01(t / 2.2);
    const calX = THREE.MathUtils.lerp(-45.5, -55.5, calSprint);
    const calZ = THREE.MathUtils.lerp(9.2, 12.4, calSprint);
    const calY = this.getGroundHeight(calX, calZ);

    // 2. Docs AI (nova_gl40 'epic' · Hypernova Prism): sprints from under Skybridge -> Impulse JumpArmed arc!
    const docs = this.actors.get('docs');
    let docsX = -59.5;
    let docsZ = 5.2;
    let docsY = this.getGroundHeight(docsX, docsZ);
    let docsAnim: AnimName = 'SprintArmed';
    let docsYaw = yawToward(-63.0, 4.2, -45.0, 5.0);

    if (t < 1.0) {
      const dm = smoothstep01(t / 1.0);
      docsX = THREE.MathUtils.lerp(-63.0, -59.5, dm);
      docsZ = THREE.MathUtils.lerp(4.2, 5.2, dm);
      docsY = this.getGroundHeight(docsX, docsZ);
      docsAnim = 'SprintArmed';
      docsYaw = yawToward(-63.0, 4.2, -54.8, 8.2);
    } else if (t < 2.35) {
      const airU = clamp01((t - 1.0) / 1.35);
      docsX = THREE.MathUtils.lerp(-59.5, -54.8, airU);
      docsZ = THREE.MathUtils.lerp(5.2, 8.2, airU);
      const baseG = this.getGroundHeight(docsX, docsZ);
      const arcHeight = 4.2 * 4 * airU * (1 - airU);
      docsY = baseG + arcHeight;
      docsAnim = 'JumpArmed';
      docsYaw = yawToward(docsX, docsZ, -44.0, 4.0);
    } else {
      docsX = -54.8;
      docsZ = 8.2;
      docsY = this.getGroundHeight(docsX, docsZ);
      docsAnim = 'Aim';
      docsYaw = yawToward(docsX, docsZ, -41.0, 0.5);
    }

    // 3. Slides AI (longbow_308 'epic' · Shoreline Viper): holds steady Aim on B40 Charlie's patio
    const slides = this.actors.get('slides');
    const slidesX = -39.6;
    const slidesZ = -3.5;
    const slidesY = this.getGroundHeight(slidesX, slidesZ);
    const slidesAimTargetX = -65.0;
    const slidesAimTargetZ = 5.5;
    const slidesYaw = yawToward(slidesX, slidesZ, slidesAimTargetX, slidesAimTargetZ);

    // 4. Supporting Gmail AI across north edge of Stan Plaza for authentic courtyard crossfire
    const gmail = this.actors.get('gmail');
    const gmailX = -48.5;
    const gmailZ = -2.4;
    const gmailY = this.getGroundHeight(gmailX, gmailZ);
    const gmailYaw = yawToward(gmailX, gmailZ, docsX, docsZ);

    if (calendar) {
      const calAiming = t >= 2.2;
      const cYaw = calAiming
        ? yawToward(calX, calZ, slidesX, slidesZ)
        : yawToward(-45.5, 9.2, -55.5, 12.4);
      this.placeGroundArmedActor(
        calendar,
        calX,
        calY,
        calZ,
        cYaw,
        calAiming ? 'Aim' : 'SprintArmed',
        snapAnims
      );
    }

    if (docs) {
      this.placeGroundArmedActor(docs, docsX, docsY, docsZ, docsYaw, docsAnim, snapAnims);
      // Slight athletic pitch while soaring through impulse jump
      if (docsAnim === 'JumpArmed') {
        const airU = clamp01((t - 1.0) / 1.35);
        docs.hero.model.rotation.x = THREE.MathUtils.lerp(-0.14, 0.1, airU);
      }
    }

    if (slides) {
      this.placeGroundArmedActor(slides, slidesX, slidesY, slidesZ, slidesYaw, 'Aim', snapAnims);
    }

    if (gmail) {
      this.placeGroundArmedActor(gmail, gmailX, gmailY, gmailZ, gmailYaw, 'Aim', snapAnims);
    }

    // 5. Real Tier 3 Vault Loot Chest beside Stan Plaza (-46.8, gy, 6.8)
    const chestX = -46.8;
    const chestZ = 6.8;
    const chestY = this.getGroundHeight(chestX, chestZ);
    if (this.lootChest) {
      this.lootChest.root.visible = true;
      this.lootChest.root.position.set(chestX, chestY, chestZ);
      // Front clasps (-Z) face SE toward the sweeping camera so the vault lid swings cleanly upward & backward!
      this.lootChest.root.rotation.set(0, yawToward(chestX, chestZ, -34, 16), 0);

      if (t < 1.2) {
        if (this.lootChest.lidNode) this.lootChest.lidNode.rotation.x = 0;
        this.lootChest.beam.visible = true;
        const pulse = 0.88 + Math.sin(t * 5.2) * 0.12;
        this.lootChest.beam.scale.x = pulse;
        this.lootChest.beam.scale.z = pulse;
        this.lootChest.ring.scale.setScalar(0.95 + Math.sin(t * 5.2) * 0.08);
      } else {
        const lidU = clamp01((t - 1.2) / 0.48);
        if (this.lootChest.lidNode) {
          this.lootChest.lidNode.rotation.x = CHEST_LID_OPEN_ANGLE_RAD * easeOutCubic(lidU);
        }
        this.lootChest.beam.visible = t < 1.65;
      }
    }

    // --- Timed Ultimate & Chest VFX Beats ---

    // t = 0.8s: Calendar deploys shimmering cobalt Chrono-Field across Stan Plaza
    if (this.consumeCue('s2_calendar_chrono', t >= 0.8)) {
      const chronoCenter = new THREE.Vector3(calX, calY, calZ);
      const visual = this.vfx.createCalendarChronoField(chronoCenter, 10.5);
      this.activeZones.push({
        visual,
        center: chronoCenter,
        radius: 10.5,
        elapsed: 0,
        duration: 5.1,
        kind: 'chrono',
      });
    }

    // t = 1.0s: Docs launches with Impulse Burst + Redline Pulse
    if (this.consumeCue('s2_docs_impulse', t >= 1.0)) {
      const launchPos = new THREE.Vector3(docsX, docsY, docsZ);
      this.vfx.spawnImpulseBurst(launchPos);
      this.vfx.spawnDocsRedlinePulse(launchPos, 11);
    }

    // Continuous luminous blue Docs Ghost Trail silhouettes during Docs' airborne arc
    if (t >= 1.06 && t <= 2.32) {
      this.docsGhostAccum += dt;
      if (this.docsGhostAccum >= 0.14) {
        this.docsGhostAccum = 0;
        this.vfx.spawnDocsGhostTrail(new THREE.Vector3(docsX, docsY, docsZ), docsYaw);
      }
    }

    // t = 1.2s: Tier 3 Vault Loot Chest pop burst + expanding golden/epic rings
    if (!this.chestPopDone && t >= 1.2) {
      this.chestPopDone = true;
      const chestPos = new THREE.Vector3(chestX, chestY + 0.35, chestZ);
      this.vfx.spawnStatusBurst(chestPos, 0xfbbc04);
      this.vfx.spawnExpandingRing(chestPos, 4.6, 0xf59e0b, 0.58);
      this.vfx.spawnExpandingRing(chestPos, 2.9, 0xa855f7, 0.46);
    }

    // t = 1.72s: Airborne Docs fires Nova GL-40 plasma grenade -> orange-violet explosion at t = 1.96s
    if (this.consumeCue('s2_docs_shot', t >= 1.72) && docs) {
      const impactY = this.getGroundHeight(-44.0, 4.0) + 0.4;
      this.fireWeaponTracer(docs, -44.0, impactY, 4.0, 0xfb923c, 0.08, 0.24);
    }
    if (this.consumeCue('s2_docs_explosion', t >= 1.96)) {
      const expY = this.getGroundHeight(-44.0, 4.0) + 0.35;
      const expPos = new THREE.Vector3(-44.0, expY, 4.0);
      this.vfx.spawnExplosion(expPos, 5.2, 0xff6b35);
      this.vfx.spawnExpandingRing(expPos, 6.2, 0xa855f7, 0.52);
    }

    // t = 2.0s: Slides windup golden Charge Beam slashing across Stan Plaza
    if (this.consumeCue('s2_slides_charge', t >= 2.0) && slides) {
      this.getActorMuzzleWorld(slides, this.tmpMuzzle);
      const targetY = this.getGroundHeight(slidesAimTargetX, slidesAimTargetZ) + 1.6;
      this.tmpDir
        .set(
          slidesAimTargetX - this.tmpMuzzle.x,
          targetY - this.tmpMuzzle.y,
          slidesAimTargetZ - this.tmpMuzzle.z
        )
        .normalize();
      this.vfx.spawnSlidesChargeBeam(this.tmpMuzzle.clone(), this.tmpDir.clone(), 56, 0.4);
    }

    // t = 2.4s: Slides blazing golden Orbital Beam ("Executive Spotlight") across Stan Plaza!
    if (this.consumeCue('s2_slides_orbital', t >= 2.4) && slides) {
      this.getActorMuzzleWorld(slides, this.tmpMuzzle);
      const targetY = this.getGroundHeight(slidesAimTargetX, slidesAimTargetZ) + 1.6;
      this.tmpDir
        .set(
          slidesAimTargetX - this.tmpMuzzle.x,
          targetY - this.tmpMuzzle.y,
          slidesAimTargetZ - this.tmpMuzzle.z
        )
        .normalize();
      this.vfx.spawnSlidesOrbitalBeam(this.tmpMuzzle.clone(), this.tmpDir.clone(), 56, 2.2);
      const beamBurst = new THREE.Vector3(-56.5, this.getGroundHeight(-56.5, 2.5) + 1.1, 2.5);
      this.vfx.spawnHitImpact(beamBurst, { isHeadshot: true });
    }

    // Follow-up courtyard firefight beats (t = 2.8..5.4s)
    if (this.consumeCue('s2_gmail_1', t >= 1.45) && gmail) {
      this.fireWeaponTracer(gmail, docsX, docsY + 1.2, docsZ, 0xffe49c, 0.036, 0.12, { isShield: true });
    }
    if (this.consumeCue('s2_cal_1', t >= 2.85) && calendar) {
      this.fireWeaponTracer(calendar, slidesX, slidesY + 1.3, slidesZ, 0x93c5fd, 0.038, 0.13, { isShield: true });
    }
    if (this.consumeCue('s2_gmail_2', t >= 3.45) && gmail) {
      this.fireWeaponTracer(gmail, calX, calY + 1.2, calZ, 0xffe49c, 0.036, 0.12, { isShield: true });
    }
    if (this.consumeCue('s2_docs_exp_2', t >= 4.25) && docs) {
      const exp2Y = this.getGroundHeight(-45.2, 1.5) + 0.35;
      this.fireWeaponTracer(docs, -45.2, exp2Y, 1.5, 0xfb923c, 0.075, 0.18);
      const exp2Pos = new THREE.Vector3(-45.2, exp2Y, 1.5);
      this.vfx.spawnExplosion(exp2Pos, 4.4, 0xff6b35);
      this.vfx.spawnExpandingRing(exp2Pos, 5.2, 0xa855f7, 0.45);
    }
    if (this.consumeCue('s2_slides_followup', t >= 4.95) && slides) {
      this.fireWeaponTracer(slides, calX, calY + 1.35, calZ, 0xfef08a, 0.044, 0.15, { isHeadshot: true });
    }

    // Low sweeping cinematic dolly past Stan T-Rex framing Tier 3 Chest, Chrono-Field,
    // Docs' jump arc, Slides' golden Orbital Beam, and the Central Glass Skybridge behind!
    const dollyS = smoothstep01(p);
    this.tmpCamPos.set(
      THREE.MathUtils.lerp(-28.5, -36.5, dollyS),
      THREE.MathUtils.lerp(5.8, 7.8, dollyS),
      THREE.MathUtils.lerp(14.2, 17.2, dollyS)
    );
    this.tmpLookAt.set(
      THREE.MathUtils.lerp(-50.5, -53.2, dollyS),
      THREE.MathUtils.lerp(2.4, 2.8, dollyS),
      THREE.MathUtils.lerp(4.2, 3.8, dollyS)
    );
    this.tmpFocus.set(-51, 2.5, 4);

    return 58;
  }

  // =========================================================================
  // SCENE 3: "3× Mountain View Campus" (5.5s) — Gradient Canopy -> Shoreline -> Bay Point
  // =========================================================================

  private updateScene3CampusFlyover(dt: number, snapAnims: boolean): number {
    const dur = SPLASH_SCENES_META[3].durationSec;
    const t = this.sceneElapsed;
    const p = clamp01(t / dur);
    const s = smoothstep01(p);

    // Sweeping golden-hour helicopter flyover spline across the 600m × 380m Mountain View campus
    evalCubicBezier(S3_CAM_P0, S3_CAM_P1, S3_CAM_P2, S3_CAM_P3, s, this.tmpCamPos);
    evalCubicBezier(S3_LOOK_P0, S3_LOOK_P1, S3_LOOK_P2, S3_LOOK_P3, s, this.tmpLookAt);

    // Glowing Supply Drop sky-beacon rising from open Shoreline/Charleston concourse (42, -94)
    const dropX = 42;
    const dropZ = -94;
    const dropGroundY = this.getGroundHeight(dropX, dropZ);
    if (this.supplyDropBeacon) {
      this.supplyDropBeacon.visible = true;
      this.supplyDropBeacon.position.set(dropX, dropGroundY, dropZ);
      this.supplyDropBeacon.rotation.y = t * 0.65;
    }
    if (this.supplyDropCrate) {
      this.supplyDropCrate.visible = true;
      const crateY = THREE.MathUtils.lerp(dropGroundY + 26, dropGroundY + 4.5, p);
      this.supplyDropCrate.position.set(dropX, crateY, dropZ);
      this.supplyDropCrate.rotation.y = t * 0.5;
    }

    // 3 heroes gliding high across the golden horizon (Gmail, Drive, Slides) with contrails
    const gStartX = 96;
    const gStartZ = -48;
    const gEndX = -32;
    const gEndZ = -92;
    const gDx = gEndX - gStartX;
    const gDz = gEndZ - gStartZ;
    const gLen = Math.hypot(gDx, gDz) || 1;
    const gFwdX = gDx / gLen;
    const gFwdZ = gDz / gLen;
    const gRightX = -gFwdZ;
    const gRightZ = gFwdX;
    const gYaw = yawToward(0, 0, gFwdX, gFwdZ);

    const leadX = THREE.MathUtils.lerp(gStartX, gEndX, p);
    const leadY = THREE.MathUtils.lerp(48, 38, p);
    const leadZ = THREE.MathUtils.lerp(gStartZ, gEndZ, p);

    this.gliderTrailAccum += dt;
    const emitTrail = this.gliderTrailAccum >= 0.09;
    if (emitTrail) {
      this.gliderTrailAccum = 0;
    }

    const trio: { id: ProductHeroId; fwd: number; right: number; up: number; phase: number }[] = [
      { id: 'gmail', fwd: 0, right: 0, up: 0, phase: 0 },
      { id: 'drive', fwd: -5.5, right: 6.2, up: 1.8, phase: 1.4 },
      { id: 'slides', fwd: -6.0, right: -6.2, up: 1.5, phase: 2.8 },
    ];

    for (const slot of trio) {
      const actor = this.actors.get(slot.id);
      if (!actor) continue;

      const bankWave = Math.sin(t * 1.2 + slot.phase);
      const x = leadX + gFwdX * slot.fwd + gRightX * slot.right;
      const y = leadY + slot.up + bankWave * 0.6;
      const z = leadZ + gFwdZ * slot.fwd + gRightZ * slot.right;

      actor.hero.root.visible = true;
      actor.hero.root.position.set(x, y, z);
      actor.hero.root.rotation.set(0, gYaw, 0);
      actor.hero.model.rotation.set(-0.1, 0, bankWave * 0.14);

      actor.gliding = true;
      actor.glider.visible = true;
      actor.weapon.root.visible = false;
      this.setActorClip(actor, 'Glide', snapAnims ? 0 : 0.12);

      if (emitTrail) {
        actor.hero.root.updateMatrixWorld(true);
        this.emitGliderWingtipTrails(actor.hero);
      }
    }

    // Track shadow frustum across the active landmark being flown over
    this.tmpFocus.copy(this.tmpLookAt);

    return 64;
  }

  // =========================================================================
  // SHARED ACTOR, WEAPON, GLIDER & VFX HELPERS
  // =========================================================================

  private getGroundHeight(x: number, z: number): number {
    return this.physics.getSupportHeight(x, z, 3.0, 0.35, 0.5);
  }

  private setActorClip(actor: AttractActor, clip: AnimName, fadeDur: number): void {
    if (actor.hero.currentAnim !== clip) {
      actor.hero.crossFade(clip, fadeDur);
    }
  }

  private placeGroundArmedActor(
    actor: AttractActor,
    x: number,
    y: number,
    z: number,
    yaw: number,
    clip: AnimName,
    snapAnims: boolean
  ): void {
    actor.hero.root.visible = true;
    actor.hero.root.position.set(x, y, z);
    actor.hero.root.rotation.set(0, yaw, 0);
    actor.hero.model.rotation.set(0, 0, 0);
    actor.hero.model.scale.set(1, 1, 1);
    actor.gliding = false;
    actor.glider.visible = false;
    actor.weapon.root.visible = true;
    this.setActorClip(actor, clip, snapAnims ? 0 : 0.14);
  }

  /**
   * Exact live Hand_L / Hand_R midpoint tracking so gliders stay glued to both palms (matches engine.ts 1:1).
   */
  private syncGliderMountToHands(hero: HeroInstance): void {
    const { leftHandNode, rightHandNode, gliderMount, model, root } = hero;
    if (!leftHandNode || !rightHandNode) return;

    root.updateMatrixWorld(true);

    leftHandNode.getWorldPosition(this.tmpA);
    model.worldToLocal(this.tmpA);

    rightHandNode.getWorldPosition(this.tmpB);
    model.worldToLocal(this.tmpB);

    this.tmpC
      .addVectors(this.tmpA, this.tmpB)
      .multiplyScalar(0.5)
      .add(GLIDE_MOUNT_LOCAL_OFFSET);
    gliderMount.position.copy(this.tmpC);

    const dx = this.tmpB.x - this.tmpA.x;
    const dy = this.tmpB.y - this.tmpA.y;
    const dz = this.tmpB.z - this.tmpA.z;
    if (dx > 0.12) {
      const microRoll = THREE.MathUtils.clamp(Math.atan2(dy, dx), -0.22, 0.22);
      const microYaw = THREE.MathUtils.clamp(Math.atan2(-dz, dx), -0.22, 0.22);
      gliderMount.rotation.set(0, microYaw, microRoll, 'YXZ');
    } else {
      gliderMount.rotation.set(0, 0, 0);
    }
  }

  private emitGliderWingtipTrails(hero: HeroInstance): void {
    this.tmpA.set(-1.45, 0.55, 0.25);
    hero.gliderMount.localToWorld(this.tmpA);
    this.vfx.spawnGliderTrail(this.tmpA);

    this.tmpB.set(1.45, 0.55, 0.25);
    hero.gliderMount.localToWorld(this.tmpB);
    this.vfx.spawnGliderTrail(this.tmpB);
  }

  private getActorMuzzleWorld(actor: AttractActor, out: THREE.Vector3): THREE.Vector3 {
    actor.hero.root.updateMatrixWorld(true);
    alignWeaponTwoHanded(actor.weapon.root, actor.hero, {
      weaponId: actor.weapon.weaponId,
      skipMatrixUpdate: true,
    });
    actor.weapon.root.updateMatrixWorld(true);
    return actor.weapon.muzzleNode.getWorldPosition(out);
  }

  private consumeCue(id: string, ready: boolean): boolean {
    if (!ready || this.firedCues.has(id)) return false;
    this.firedCues.add(id);
    return true;
  }

  private fireWeaponTracer(
    shooter: AttractActor,
    tx: number,
    ty: number,
    tz: number,
    color: number,
    thickness = 0.038,
    ttl = 0.12,
    impact?: { isShield?: boolean; isHeadshot?: boolean; isWorld?: boolean }
  ): void {
    this.getActorMuzzleWorld(shooter, this.tmpMuzzle);
    this.tmpTarget.set(tx, ty, tz);
    this.tmpDir.subVectors(this.tmpTarget, this.tmpMuzzle);
    if (this.tmpDir.lengthSq() < 1e-4) return;
    this.tmpDir.normalize();

    this.vfx.spawnMuzzleFlash(this.tmpMuzzle, this.tmpDir, color, 1.05);
    this.vfx.spawnTracer(this.tmpMuzzle, this.tmpTarget, color, thickness, ttl);
    if (impact) {
      this.vfx.spawnHitImpact(this.tmpTarget, impact);
    }
  }

  private fireShotgunSpread(
    shooter: AttractActor,
    tx: number,
    ty: number,
    tz: number,
    impact?: { isShield?: boolean; isHeadshot?: boolean; isWorld?: boolean }
  ): void {
    this.getActorMuzzleWorld(shooter, this.tmpMuzzle);
    this.tmpTarget.set(tx, ty, tz);
    this.tmpDir.subVectors(this.tmpTarget, this.tmpMuzzle);
    if (this.tmpDir.lengthSq() < 1e-4) return;
    this.tmpDir.normalize();

    this.vfx.spawnMuzzleFlash(this.tmpMuzzle, this.tmpDir, 0xffb74d, 1.25);
    const offsets: [number, number, number][] = [
      [0, 0, 0],
      [0.32, 0.16, -0.22],
      [-0.28, -0.14, 0.24],
    ];
    for (let i = 0; i < offsets.length; i++) {
      const [ox, oy, oz] = offsets[i];
      this.tmpHit.set(tx + ox, ty + oy, tz + oz);
      this.vfx.spawnTracer(this.tmpMuzzle, this.tmpHit, 0xffd54f, 0.034, 0.11);
    }
    if (impact) {
      this.vfx.spawnHitImpact(this.tmpTarget, impact);
    }
  }

  /**
   * Fires a tracer from `shooter` toward `domeCenter` and sparks right on the outer sphere shell
   * of Drive's Guardrail Dome via `vfx.spawnGuardrailIntercept`.
   */
  private fireAtGuardrailDome(
    shooter: AttractActor,
    domeCenter: THREE.Vector3,
    domeRadius: number,
    color: number,
    aimHeightOffset: number
  ): void {
    this.getActorMuzzleWorld(shooter, this.tmpMuzzle);
    this.tmpTarget.set(domeCenter.x, domeCenter.y + aimHeightOffset, domeCenter.z);
    this.tmpDir.subVectors(this.tmpTarget, this.tmpMuzzle);
    const dist = this.tmpDir.length();
    if (dist < 0.2) return;
    this.tmpDir.divideScalar(dist);

    // Compute exact entry intersection on the Guardrail Dome sphere
    const ocX = this.tmpMuzzle.x - domeCenter.x;
    const ocY = this.tmpMuzzle.y - domeCenter.y;
    const ocZ = this.tmpMuzzle.z - domeCenter.z;
    const b = ocX * this.tmpDir.x + ocY * this.tmpDir.y + ocZ * this.tmpDir.z;
    const c = ocX * ocX + ocY * ocY + ocZ * ocZ - domeRadius * domeRadius;
    const disc = b * b - c;

    let hitDist = Math.max(0.5, dist - domeRadius);
    if (disc >= 0) {
      const root = -b - Math.sqrt(disc);
      if (root > 0.2 && root < dist) {
        hitDist = root;
      }
    }

    this.tmpHit.copy(this.tmpMuzzle).addScaledVector(this.tmpDir, hitDist);
    this.vfx.spawnMuzzleFlash(this.tmpMuzzle, this.tmpDir, color, 1.0);
    this.vfx.spawnTracer(this.tmpMuzzle, this.tmpHit, color, 0.038, 0.13);
    this.vfx.spawnGuardrailIntercept(this.tmpHit, domeCenter);
  }

  private applyCameraSafe(
    camera: THREE.PerspectiveCamera,
    targetFov: number,
    pos: THREE.Vector3,
    lookAt: THREE.Vector3
  ): void {
    if (
      !Number.isFinite(pos.x) ||
      !Number.isFinite(pos.y) ||
      !Number.isFinite(pos.z) ||
      !Number.isFinite(lookAt.x) ||
      !Number.isFinite(lookAt.y) ||
      !Number.isFinite(lookAt.z)
    ) {
      return;
    }

    if (Number.isFinite(targetFov) && Math.abs(camera.fov - targetFov) > 0.01) {
      camera.fov = targetFov;
      camera.updateProjectionMatrix();
    }

    camera.up.set(0, 1, 0);
    camera.position.copy(pos);
    camera.lookAt(lookAt);
  }
}

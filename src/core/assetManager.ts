import * as THREE from 'three';
import { GLTFLoader, type GLTF } from 'three/examples/jsm/loaders/GLTFLoader.js';
import * as SkeletonUtils from 'three/examples/jsm/utils/SkeletonUtils.js';
import { CHEST_TIER_CONFIG, HERO_MAP, RARITY_CONFIG, UTILITY_ITEMS, WEAPONS } from '../data/catalog';
import {
  AnimName,
  ChestTier,
  LoadingProgress,
  MapAssetKey,
  ProductHeroId,
  PropAssetId,
  Rarity,
  UtilityItemId,
  WeaponId,
} from '../types';

export type ReloadLowerMode = 'stand' | 'walk' | 'crouch' | 'jump';

export interface HeroInstance {
  heroId: ProductHeroId;
  root: THREE.Group;
  model: THREE.Object3D;
  mixer: THREE.AnimationMixer;
  actions: Record<AnimName, THREE.AnimationAction>;
  weaponSocket: THREE.Object3D;
  spineNode: THREE.Object3D | null;
  chestNode: THREE.Object3D | null;
  headNode: THREE.Object3D | null;
  leftHandNode: THREE.Object3D | null;
  rightHandNode: THREE.Object3D | null;
  upperArmLNode: THREE.Object3D | null;
  lowerArmLNode: THREE.Object3D | null;
  upperArmRNode: THREE.Object3D | null;
  lowerArmRNode: THREE.Object3D | null;
  thighLNode: THREE.Object3D | null;
  shinLNode: THREE.Object3D | null;
  footLNode: THREE.Object3D | null;
  thighRNode: THREE.Object3D | null;
  shinRNode: THREE.Object3D | null;
  footRNode: THREE.Object3D | null;
  gliderMount: THREE.Group;
  overheadGroup: THREE.Group;
  hpBarFill: THREE.Mesh;
  shieldBarBg: THREE.Mesh;
  shieldBarFill: THREE.Mesh;
  revealRing: THREE.Mesh;
  /** Cached hero meshes toggled by AssetManager.setHeroCastShadow() without per-frame traversal */
  shadowMeshes: THREE.Mesh[];
  castShadowEnabled: boolean;
  currentAnim: AnimName;
  /** Smoothly cross-fade between the 13 baked Blender NLA clips (12 combat + LobbyShowcase, reload-split-aware) */
  crossFade: (next: AnimName, duration?: number) => void;
  /** Enter or update upper/lower-body split reload pose (upper Reload uninterrupted; lower matches stand/walk/crouch/jump) */
  setReloadPose: (
    lowerMode: ReloadLowerMode,
    reloadTimeScale: number,
    lowerTimeScale: number,
    fadeDur?: number
  ) => void;
  /** Normalized [0, 1] playback progress of the active Reload upper-body clip */
  getReloadProgress01: () => number;
  /** Brief emissive hit flash on hero materials */
  flashHit: (colorHex?: number, intensity?: number) => void;
  /** Reset emissive tint back to resting values */
  clearFlash: () => void;
  /** Lazily create or update a crisp compact overhead player nameplate billboard above HP/Shield bars */
  setNameplate: (name: string, teamColorCss?: string | null) => void;
}

export interface WeaponInstance {
  weaponId: WeaponId;
  rarity: Rarity;
  root: THREE.Group;
  muzzleNode: THREE.Object3D;
}

export interface LootDropVisual {
  root: THREE.Group;
  itemHolder: THREE.Group;
  beam: THREE.Mesh;
  ring: THREE.Mesh;
  rarity: Rarity;
}

export interface LootChestVisual {
  root: THREE.Group;
  chestModel: THREE.Object3D;
  lidNode: THREE.Object3D | null;
  beam: THREE.Mesh;
  beamMat: THREE.MeshBasicMaterial;
  ring: THREE.Mesh;
  ringMat: THREE.MeshBasicMaterial;
  accentMaterials: THREE.MeshStandardMaterial[];
  tier: ChestTier;
  /** Swaps this chest's ring & accent slots to shared dimmed "opened" materials without mutating unopened chests */
  markOpened?: () => void;
}

export interface RideableGBikeVisual {
  root: THREE.Group;
  frontAssembly: THREE.Object3D | null;
  wheelFront: THREE.Object3D | null;
  wheelRear: THREE.Object3D | null;
  crankPedals: THREE.Object3D | null;
  seatMount: THREE.Object3D | null;
  frameMat: THREE.MeshStandardMaterial | null;
  fenderMat: THREE.MeshStandardMaterial | null;
}

export interface TechStopVisual {
  root: THREE.Group;
  holoIcon: THREE.Object3D | null;
}

export interface GoogleGBusVisual {
  root: THREE.Group;
  rotorL: THREE.Object3D | null;
  rotorR: THREE.Object3D | null;
  thrusterL: THREE.Object3D | null;
  thrusterR: THREE.Object3D | null;
}

const GBIKE_LIVERY_PAIRS: readonly { frameHex: number; fenderHex: number }[] = [
  { frameHex: 0x4285f4, fenderHex: 0xfbbc04 }, // 0: Google Blue + Google Yellow
  { frameHex: 0xea4335, fenderHex: 0x4285f4 }, // 1: Google Red + Google Blue
  { frameHex: 0x34a853, fenderHex: 0xfbbc04 }, // 2: Google Green + Google Yellow
  { frameHex: 0xfbbc04, fenderHex: 0xea4335 }, // 3: Google Yellow + Google Red
];

const ANIM_NAMES: AnimName[] = [
  'Idle',
  'Run',
  'Sprint',
  'Crouch',
  'Aim',
  'Reload',
  'Glide',
  'Jump',
  'IdleArmed',
  'RunArmed',
  'SprintArmed',
  'JumpArmed',
  'LobbyShowcase',
];

const ARMED_CLIP_FALLBACKS: Partial<Record<AnimName, AnimName>> = {
  IdleArmed: 'Idle',
  RunArmed: 'Run',
  SprintArmed: 'Sprint',
  JumpArmed: 'Jump',
  LobbyShowcase: 'IdleArmed',
};

const RELOAD_LOWER_MODES: readonly ReloadLowerMode[] = ['stand', 'walk', 'crouch', 'jump'];

// Disjoint 18-bone partition matching all 6 Blender hero GLB armatures (8 lower + 10 upper = 18, intersection = ∅)
const LOWER_BODY_BONES: ReadonlySet<string> = new Set([
  'Root',
  'Pelvis',
  'Thigh_L',
  'Shin_L',
  'Foot_L',
  'Thigh_R',
  'Shin_R',
  'Foot_R',
]);

const UPPER_BODY_BONES: ReadonlySet<string> = new Set([
  'Spine',
  'Chest',
  'Neck',
  'Head',
  'UpperArm_L',
  'LowerArm_L',
  'Hand_L',
  'UpperArm_R',
  'LowerArm_R',
  'Hand_R',
]);

interface HeroReloadSplitClips {
  reloadUpper: THREE.AnimationClip;
  lower: Record<ReloadLowerMode, THREE.AnimationClip>;
}

function getTrackBoneName(trackName: string): string {
  const nodePath = trackName.split('.')[0];
  const parts = nodePath.split('/');
  return parts[parts.length - 1] ?? nodePath;
}

function filterClipTracksByBones(
  source: THREE.AnimationClip | undefined,
  clipName: string,
  allowedBones: ReadonlySet<string>
): THREE.AnimationClip | null {
  if (!source || source.tracks.length === 0) return null;
  const filtered = source.tracks.filter((track) => allowedBones.has(getTrackBoneName(track.name)));
  if (filtered.length === 0) return null;
  // Shares source KeyframeTrack instances with zero extra typed-array allocations
  return new THREE.AnimationClip(clipName, source.duration, filtered);
}

/**
 * Calibrated two-handed rifle grip constants (measured 1:1 in `build_characters.py` across all 6 heroes):
 * - `LEFT_HAND_PALM_OFFSET_LOCAL`: left palm cradle center in `Hand_L` bone-local space (exact within ±1.2mm).
 * - `RIFLE_FOREGRIP_DIST` / `RIFLE_FOREGRIP_UP`: pistol grip (0,0,0) -> handguard underside (0,+0.064,-0.290).
 * - `RIFLE_FOREGRIP_ALPHA`: exact pitch compensation `atan2(0.064, 0.290) = 0.21721 rad (12.445°)` so `Aim`
 *   barrel points dead-level along `(0, 0, -1)` while both palms lock onto grip & handguard with 0.00mm gap.
 */
export const LEFT_HAND_PALM_OFFSET_LOCAL = new THREE.Vector3(0.03, 0.092, 0.006);
export const RIFLE_FOREGRIP_DIST = 0.29;
export const RIFLE_FOREGRIP_UP = 0.064;
export const RIFLE_FOREGRIP_ALPHA = Math.atan2(RIFLE_FOREGRIP_UP, RIFLE_FOREGRIP_DIST);

const _COS_FOREGRIP_ALPHA = Math.cos(RIFLE_FOREGRIP_ALPHA);
const _SIN_FOREGRIP_ALPHA = Math.sin(RIFLE_FOREGRIP_ALPHA);

interface WeaponGripTune {
  /** Subtle local shift in weapon axes (+X right, +Y up, -Z forward toward muzzle) */
  posOffset: THREE.Vector3;
}

const DEFAULT_WEAPON_GRIP_TUNE: WeaponGripTune = {
  posOffset: new THREE.Vector3(0, 0, 0),
};

const WEAPON_GRIP_TUNE: Record<WeaponId, WeaponGripTune> = {
  vanguard_m4: {
    posOffset: new THREE.Vector3(0, 0, 0),
  },
  breaker_12g: {
    posOffset: new THREE.Vector3(0, 0.006, 0),
  },
  vector_9: {
    posOffset: new THREE.Vector3(0, 0.008, -0.014),
  },
  longbow_308: {
    posOffset: new THREE.Vector3(0, 0, -0.01),
  },
  nova_gl40: {
    posOffset: new THREE.Vector3(0, 0, -0.006),
  },
};

export interface TwoHandWeaponAlignOptions {
  /** Weapon ID for subtle per-weapon pistol-grip / buttstock clearance fine-tuning */
  weaponId?: WeaponId;
  /**
   * Blend weight in [0, 1] between `fallbackWorldQuat` (0, defaults to `WeaponSocket_R`
   * identity for mid-Reload single-hand canted hold) and exact `WeaponSocket_R -> Hand_L`
   * two-handed barrel lock (1). Default: `1`.
   */
  twoHandWeight?: number;
  /** Optional custom world-space fallback orientation when `twoHandWeight < 1` or `Hand_L` is missing */
  fallbackWorldQuat?: THREE.Quaternion;
  /** Optional override for `Hand_L` local palm-cup offset */
  leftPalmOffsetLocal?: THREE.Vector3;
  /** Optional override for pitch-compensation angle `ALPHA` (rad) between grip and handguard underside */
  foregripAlpha?: number;
  /** Set true when caller just ran `updateMatrixWorld(true)` on `hero.root` (or its parent) */
  skipMatrixUpdate?: boolean;
}

// Module-level scratch objects for zero-allocation per-frame weapon alignment
const _alignGripWorld = new THREE.Vector3();
const _alignForegripWorld = new THREE.Vector3();
const _alignGHat = new THREE.Vector3();
const _alignRefUp = new THREE.Vector3();
const _alignRHat = new THREE.Vector3();
const _alignGUp = new THREE.Vector3();
const _alignBHat = new THREE.Vector3();
const _alignUHat = new THREE.Vector3();
const _alignZAxis = new THREE.Vector3();
const _alignRotMat = new THREE.Matrix4();
const _alignTwoHandWorldQuat = new THREE.Quaternion();
const _alignFinalWorldQuat = new THREE.Quaternion();
const _alignParentWorldQuat = new THREE.Quaternion();
const _alignParentWorldQuatInv = new THREE.Quaternion();
const _alignModelWorldQuat = new THREE.Quaternion();
const _alignLocalPosOffset = new THREE.Vector3();
const _ALIGN_WORLD_UP = new THREE.Vector3(0, 1, 0);

/**
 * Orients `weaponRoot` (parented to `hero.weaponSocket`, with barrel along local `-Z`
 * and top rail along local `+Y`) using the exact pitch-compensated `WeaponSocket_R -> Hand_L`
 * basis matching `build_characters.py` 1:1 (`ALPHA = atan2(0.064, 0.290) = 0.21721 rad`),
 * with upright roll aligned to the hero's model up vector.
 *
 * Shared by both live combat (`engine.ts`) and the 3D Lobby Showcase (`main.ts`) so both hands
 * stay mathematically glued to the pistol grip and handguard across all armed animations and
 * crossfades, and blend smoothly via `twoHandWeight` to `WeaponSocket_R` identity during Reload.
 */
export function alignWeaponTwoHanded(
  weaponRoot: THREE.Object3D,
  hero: HeroInstance,
  options?: TwoHandWeaponAlignOptions
): void {
  if (!options?.skipMatrixUpdate) {
    hero.root.updateMatrixWorld(true);
  }

  hero.weaponSocket.getWorldQuaternion(_alignParentWorldQuat);
  _alignParentWorldQuatInv.copy(_alignParentWorldQuat).invert();

  const weight = THREE.MathUtils.clamp(options?.twoHandWeight ?? 1, 0, 1);
  const tune = options?.weaponId ? WEAPON_GRIP_TUNE[options.weaponId] : DEFAULT_WEAPON_GRIP_TUNE;

  let hasTwoHandOrientation = false;
  if (hero.leftHandNode && weight > 0.001) {
    hero.weaponSocket.getWorldPosition(_alignGripWorld);
    _alignForegripWorld.copy(options?.leftPalmOffsetLocal ?? LEFT_HAND_PALM_OFFSET_LOCAL);
    hero.leftHandNode.localToWorld(_alignForegripWorld);

    _alignGHat.subVectors(_alignForegripWorld, _alignGripWorld);
    const handDist = _alignGHat.length();
    if (handDist > 0.05) {
      _alignGHat.divideScalar(handDist);

      // Upright reference vector: (0, 1, 0) rotated by hero.model world quat (matches Blender IK 1:1)
      hero.model.getWorldQuaternion(_alignModelWorldQuat);
      _alignRefUp.set(0, 1, 0).applyQuaternion(_alignModelWorldQuat).normalize();
      if (Math.abs(_alignGHat.dot(_alignRefUp)) > 0.94) {
        _alignRefUp.copy(_ALIGN_WORLD_UP);
        if (Math.abs(_alignGHat.dot(_alignRefUp)) > 0.94) {
          _alignRefUp.set(0, 0, 1).applyQuaternion(_alignModelWorldQuat).normalize();
        }
      }

      // Exact pitch-compensated basis:
      //   rHat  = normalize(cross(gHat, upRef))
      //   gUp   = normalize(cross(rHat, gHat))
      //   bHat  = normalize(gHat * cos(ALPHA) - gUp * sin(ALPHA))  // barrel axis (-Z_weapon)
      //   uHat  = normalize(gHat * sin(ALPHA) + gUp * cos(ALPHA))  // optics up   (+Y_weapon)
      //   zAxis = -bHat                                            // stock axis  (+Z_weapon)
      _alignRHat.crossVectors(_alignGHat, _alignRefUp).normalize();
      _alignGUp.crossVectors(_alignRHat, _alignGHat).normalize();

      const cosA =
        options?.foregripAlpha !== undefined ? Math.cos(options.foregripAlpha) : _COS_FOREGRIP_ALPHA;
      const sinA =
        options?.foregripAlpha !== undefined ? Math.sin(options.foregripAlpha) : _SIN_FOREGRIP_ALPHA;

      _alignBHat
        .copy(_alignGHat)
        .multiplyScalar(cosA)
        .addScaledVector(_alignGUp, -sinA)
        .normalize();
      _alignUHat
        .copy(_alignGHat)
        .multiplyScalar(sinA)
        .addScaledVector(_alignGUp, cosA)
        .normalize();
      _alignZAxis.copy(_alignBHat).negate();

      _alignRotMat.makeBasis(_alignRHat, _alignUHat, _alignZAxis);
      _alignTwoHandWorldQuat.setFromRotationMatrix(_alignRotMat);
      hasTwoHandOrientation = true;
    }
  }

  // Fallback defaults to WeaponSocket_R world quaternion (= identity in socket local space),
  // pre-oriented +90° X in build_characters.py so Hand_R naturally cants the rifle during Reload.
  const fallbackQuat = options?.fallbackWorldQuat ?? _alignParentWorldQuat;

  if (hasTwoHandOrientation) {
    if (weight < 0.999) {
      _alignFinalWorldQuat.copy(fallbackQuat).slerp(_alignTwoHandWorldQuat, weight);
    } else {
      _alignFinalWorldQuat.copy(_alignTwoHandWorldQuat);
    }
  } else {
    _alignFinalWorldQuat.copy(fallbackQuat);
  }

  weaponRoot.quaternion.copy(_alignParentWorldQuatInv).multiply(_alignFinalWorldQuat);

  // Subtle per-weapon shift expressed in weapon's own local axes (invariant to WeaponSocket_R rest roll)
  if (tune.posOffset.lengthSq() > 1e-8) {
    _alignLocalPosOffset.copy(tune.posOffset).applyQuaternion(weaponRoot.quaternion);
    weaponRoot.position.copy(_alignLocalPosOffset);
  } else {
    weaponRoot.position.set(0, 0, 0);
  }
}

export const HERO_ASSET_PATHS: Record<ProductHeroId, string> = {
  gmail: '/assets/characters/hero_gmail.glb',
  drive: '/assets/characters/hero_drive.glb',
  calendar: '/assets/characters/hero_calendar.glb',
  chat: '/assets/characters/hero_chat.glb',
  slides: '/assets/characters/hero_slides.glb',
  docs: '/assets/characters/hero_docs.glb',
};

export const WEAPON_ASSET_PATHS: Record<WeaponId, string> = {
  vanguard_m4: '/assets/weapons/weapon_vanguard_m4.glb',
  breaker_12g: '/assets/weapons/weapon_breaker_12g.glb',
  vector_9: '/assets/weapons/weapon_vector_9.glb',
  longbow_308: '/assets/weapons/weapon_longbow_308.glb',
  nova_gl40: '/assets/weapons/weapon_nova_gl40.glb',
};

export const UTILITY_ASSET_PATHS: Record<UtilityItemId, string> = {
  shield_cell: '/assets/utilities/item_shield_cell.glb',
  shield_jug: '/assets/utilities/item_shield_jug.glb',
  medkit: '/assets/utilities/item_medkit.glb',
  mana_elixir: '/assets/utilities/item_mana_elixir.glb',
  hardlight_cover: '/assets/utilities/item_hardlight_cover.glb',
  impulse_booster: '/assets/utilities/item_impulse_booster.glb',
};

export const PROP_ASSET_PATHS: Record<PropAssetId, string> = {
  supply_drop: '/assets/utilities/prop_supply_drop.glb',
  glider: '/assets/utilities/prop_glider.glb',
  loot_chest: '/assets/utilities/prop_loot_chest.glb',
  gbike_rideable: '/assets/map/prop_gbike_rideable.glb',
  techstop_kiosk: '/assets/map/prop_techstop_kiosk.glb',
  google_gbus: '/assets/map/prop_google_gbus.glb',
};

export const MAP_ASSET_PATHS: Record<MapAssetKey, string> = {
  terrain: '/assets/map/googleplex_terrain.glb',
  stan_trex: '/assets/map/landmark_stan_trex.glb',
  b40_partnerplex: '/assets/map/landmark_b40_partnerplex.glb',
  b41: '/assets/map/landmark_b41.glb',
  b42: '/assets/map/landmark_b42.glb',
  b43: '/assets/map/landmark_b43.glb',
  skybridge: '/assets/map/landmark_skybridge.glb',
  volleyball_court: '/assets/map/landmark_volleyball_court.glb',
  gradient_canopy: '/assets/map/landmark_gradient_canopy.glb',
  orb_plaza: '/assets/map/landmark_orb_plaza.glb',
  shoreline_amphitheatre: '/assets/map/landmark_shoreline_amphitheatre.glb',
  athletic_field: '/assets/map/landmark_athletic_field.glb',
  google_2000_1950: '/assets/map/landmark_google_2000_1950.glb',
  charleston_campus: '/assets/map/landmark_charleston_campus.glb',
  alta_complex: '/assets/map/landmark_alta_complex.glb',
  shoreline_east_office: '/assets/map/landmark_shoreline_east_office.glb',
  umbrella_bistro: '/assets/map/prop_umbrella_bistro.glb',
  gbike_rack: '/assets/map/prop_gbike_rack.glb',
  oak_tree: '/assets/map/prop_oak_tree.glb',
  redwood_tree: '/assets/map/prop_redwood_tree.glb',
  desk_pod: '/assets/map/prop_desk_pod.glb',
  conference_pod: '/assets/map/prop_conference_pod.glb',
  microkitchen_bar: '/assets/map/prop_microkitchen_bar.glb',
  lounge_nook: '/assets/map/prop_lounge_nook.glb',
  whiteboard_wall: '/assets/map/prop_whiteboard_wall.glb',
  park_outdoor_gym: '/assets/map/park_outdoor_gym.glb',
  park_art_garden: '/assets/map/park_art_garden.glb',
  park_google_pergola: '/assets/map/park_google_pergola.glb',
  garden_planter_wall: '/assets/map/prop_garden_planter_wall.glb',
  sculpture_plinth: '/assets/map/prop_sculpture_plinth.glb',
};

const OPTIONAL_MAP_KEYS = new Set<string>([
  'terrain',
  'desk_pod',
  'conference_pod',
  'microkitchen_bar',
  'lounge_nook',
  'whiteboard_wall',
]);

// Small indoor furniture props, modular park cover props, terrain, and loot chests never cast shadows so only heroes & major architecture/trees/park plazas enter the shadow pass
const NO_CAST_SHADOW_KEYS = new Set<string>([
  'map:terrain',
  'map:desk_pod',
  'map:conference_pod',
  'map:microkitchen_bar',
  'map:lounge_nook',
  'map:whiteboard_wall',
  'map:garden_planter_wall',
  'map:sculpture_plinth',
  'prop:loot_chest',
]);

interface ManifestEntry {
  cacheKey: string;
  url: string;
  label: string;
  optional?: boolean;
}

export class AssetManager {
  private loader = new GLTFLoader();
  private cache = new Map<string, GLTF>();
  private loadPromise: Promise<void> | null = null;
  private loaded = false;

  // Shared lightweight geometries for loot beams, chest beacons & overhead bars
  private lootRingGeo = new THREE.RingGeometry(0.42, 0.56, 24);
  private lootBeamGeo = new THREE.CylinderGeometry(0.14, 0.44, 1.0, 14, 1, true);
  private chestRingGeo = new THREE.RingGeometry(0.62, 0.82, 28);
  private chestBeamGeo = new THREE.CylinderGeometry(0.22, 0.58, 1.0, 16, 1, true);
  private barBgGeo = new THREE.PlaneGeometry(1.16, 0.14);
  private barFillGeo = new THREE.PlaneGeometry(1.12, 0.09);
  private revealRingGeo = new THREE.RingGeometry(0.68, 0.88, 28);

  // Cached shared materials across all 150 loot chests (3 per tier) & ground loot drops (3 per rarity)
  private chestAccentMats = new Map<ChestTier, THREE.MeshStandardMaterial>();
  private chestOpenedAccentMats = new Map<ChestTier, THREE.MeshStandardMaterial>();
  private chestRingMats = new Map<ChestTier, THREE.MeshBasicMaterial>();
  private chestOpenedRingMats = new Map<ChestTier, THREE.MeshBasicMaterial>();
  private chestBeamMats = new Map<ChestTier, THREE.MeshBasicMaterial>();
  private chestFallbackBaseMat: THREE.MeshStandardMaterial | null = null;
  private lootRingMats = new Map<Rarity, THREE.MeshBasicMaterial>();
  private lootBeamMats = new Map<Rarity, THREE.MeshBasicMaterial>();
  private weaponAccentMats = new Map<string, THREE.MeshStandardMaterial>();
  // Cached upper/lower-body split reload clips per heroId (shared across all 20 hero instances)
  private heroReloadSplitClips = new Map<ProductHeroId, HeroReloadSplitClips | null>();

  constructor() {
    this.lootRingGeo.rotateX(-Math.PI / 2);
    this.lootBeamGeo.translate(0, 0.5, 0);
    this.chestRingGeo.rotateX(-Math.PI / 2);
    this.chestBeamGeo.translate(0, 0.5, 0);
    this.revealRingGeo.rotateX(-Math.PI / 2);
  }

  public get isLoaded(): boolean {
    return this.loaded;
  }

  public isHeroReady(heroId: ProductHeroId): boolean {
    return this.cache.has(`hero:${heroId}`);
  }

  public isWeaponReady(weaponId: WeaponId): boolean {
    return this.cache.has(`weapon:${weaponId}`);
  }

  public hasTerrainAsset(): boolean {
    return this.cache.has('map:terrain');
  }

  /**
   * Preloads all 52 Blender .glb assets (heroes, weapons, utilities, props, rideable GBike, TechStop kiosk, 3x Mountain View Googleplex landmarks & outdoor park defenses).
   * Safe to call multiple times; deduplicates concurrent invocations.
   */
  public preloadAll(onProgress?: (progress: LoadingProgress) => void): Promise<void> {
    if (this.loaded) {
      onProgress?.({ loaded: 1, total: 1, ratio: 1, label: 'All Googleplex 3D assets ready' });
      return Promise.resolve();
    }
    if (this.loadPromise) {
      return this.loadPromise.then(() => {
        onProgress?.({ loaded: 1, total: 1, ratio: 1, label: 'All Googleplex 3D assets ready' });
      });
    }

    const manifest: ManifestEntry[] = [];
    for (const [id, url] of Object.entries(HERO_ASSET_PATHS)) {
      const hero = HERO_MAP[id as ProductHeroId];
      manifest.push({
        cacheKey: `hero:${id}`,
        url,
        label: `Hero · ${hero.displayName}`,
      });
    }
    for (const [id, url] of Object.entries(WEAPON_ASSET_PATHS)) {
      manifest.push({
        cacheKey: `weapon:${id}`,
        url,
        label: `Weapon · ${WEAPONS[id as WeaponId].name}`,
      });
    }
    for (const [id, url] of Object.entries(UTILITY_ASSET_PATHS)) {
      manifest.push({
        cacheKey: `utility:${id}`,
        url,
        label: `Utility · ${UTILITY_ITEMS[id as UtilityItemId].name}`,
      });
    }
    for (const [id, url] of Object.entries(PROP_ASSET_PATHS)) {
      manifest.push({
        cacheKey: `prop:${id}`,
        url,
        label:
          id === 'glider'
            ? 'Prop · Tactical Glider'
            : id === 'loot_chest'
              ? 'Prop · Loot Chest'
              : id === 'gbike_rideable'
                ? 'Prop · Rideable GBike'
                : id === 'techstop_kiosk'
                  ? 'Prop · TechStop Kiosk'
                  : id === 'google_gbus'
                    ? 'Prop · Flying Google GBus'
                    : 'Prop · Supply Drop',
      });
    }
    for (const [key, url] of Object.entries(MAP_ASSET_PATHS)) {
      manifest.push({
        cacheKey: `map:${key}`,
        url,
        label: `Campus · ${key.replace(/_/g, ' ')}`,
        optional: OPTIONAL_MAP_KEYS.has(key),
      });
    }

    const total = manifest.length;
    let completed = 0;

    onProgress?.({ loaded: 0, total, ratio: 0, label: 'Initializing Googleplex assets...' });

    const loadOne = async (entry: ManifestEntry): Promise<void> => {
      try {
        const gltf = await this.loader.loadAsync(entry.url);
        this.prepareLoadedScene(
          gltf.scene,
          entry.cacheKey.startsWith('map:'),
          NO_CAST_SHADOW_KEYS.has(entry.cacheKey)
        );
        this.cache.set(entry.cacheKey, gltf);
      } catch (err) {
        if (entry.optional) {
          console.info(`[AssetManager] Optional asset ${entry.url} unavailable; skipping.`);
        } else {
          console.warn(`[AssetManager] Failed to load ${entry.url}:`, err);
        }
      } finally {
        completed++;
        onProgress?.({
          loaded: completed,
          total,
          ratio: completed / total,
          label: entry.label,
        });
      }
    };

    // Load in balanced concurrent batches of 6 to avoid saturating browser connections
    const runBatched = async (): Promise<void> => {
      const batchSize = 6;
      for (let i = 0; i < manifest.length; i += batchSize) {
        const slice = manifest.slice(i, i + batchSize);
        await Promise.all(slice.map(loadOne));
      }
      this.loaded = true;
      onProgress?.({
        loaded: total,
        total,
        ratio: 1,
        label: 'Googleplex Campus Ready',
      });
    };

    this.loadPromise = runBatched();
    return this.loadPromise;
  }

  private prepareLoadedScene(scene: THREE.Object3D, isMapAsset: boolean, disableCastShadow = false): void {
    scene.traverse((obj) => {
      if ((obj as THREE.Mesh).isMesh) {
        const mesh = obj as THREE.Mesh;
        mesh.castShadow = !disableCastShadow;
        mesh.receiveShadow = true;
        if ((mesh as THREE.SkinnedMesh).isSkinnedMesh) {
          mesh.frustumCulled = false; // Prevent skinned animation culling glitches
        }
        const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
        for (const m of mats) {
          if (!m) continue;
          const std = m as THREE.MeshStandardMaterial;
          if (std.map) {
            std.map.colorSpace = THREE.SRGBColorSpace;
            std.map.anisotropy = 2;
          }
          if (isMapAsset && std.transparent && std.opacity < 0.99) {
            // Keep architectural curtain glass crisp without dark self-shadow artifacts
            mesh.castShadow = false;
          }
        }
      }
    });
  }

  private getHeroReloadSplitClips(
    heroId: ProductHeroId,
    clips: THREE.AnimationClip[]
  ): HeroReloadSplitClips | null {
    if (clips.length === 0) return null;
    if (this.heroReloadSplitClips.has(heroId)) {
      return this.heroReloadSplitClips.get(heroId) ?? null;
    }

    const findClipByName = (name: string): THREE.AnimationClip | undefined =>
      clips.find((c) => c.name === name) ??
      clips.find((c) => c.name.toLowerCase() === name.toLowerCase());

    const reloadClip = findClipByName('Reload');
    const runClip = findClipByName('RunArmed') ?? findClipByName('Run');
    const crouchClip = findClipByName('Crouch');
    const jumpClip = findClipByName('JumpArmed') ?? findClipByName('Jump');

    const reloadUpper = filterClipTracksByBones(reloadClip, 'ReloadUpper', UPPER_BODY_BONES);
    const reloadLower = filterClipTracksByBones(reloadClip, 'ReloadLower', LOWER_BODY_BONES);
    const runLower = filterClipTracksByBones(runClip, 'RunLower', LOWER_BODY_BONES) ?? reloadLower;
    const crouchLower =
      filterClipTracksByBones(crouchClip, 'CrouchLower', LOWER_BODY_BONES) ?? reloadLower;
    const jumpLower = filterClipTracksByBones(jumpClip, 'JumpLower', LOWER_BODY_BONES) ?? reloadLower;

    if (!reloadUpper || !reloadLower || !runLower || !crouchLower || !jumpLower) {
      this.heroReloadSplitClips.set(heroId, null);
      return null;
    }

    const split: HeroReloadSplitClips = {
      reloadUpper,
      lower: {
        stand: reloadLower,
        walk: runLower,
        crouch: crouchLower,
        jump: jumpLower,
      },
    };
    this.heroReloadSplitClips.set(heroId, split);
    return split;
  }

  /**
   * Instantiates a rigged & animated Google Workspace human hero using SkeletonUtils.clone.
   * Note: Exported Blender heroes face -Z in local Three.js space (+X right, +Y up, feet at Y=0).
   */
  public instantiateHero(
    heroId: ProductHeroId,
    options?: { includeOverhead?: boolean }
  ): HeroInstance {
    const gltf = this.cache.get(`hero:${heroId}`);
    const root = new THREE.Group();
    root.name = `HeroRoot_${heroId}`;

    let model: THREE.Object3D;
    const shadowMeshes: THREE.Mesh[] = [];
    const clonedMaterials: THREE.MeshStandardMaterial[] = [];
    const baseEmissives: THREE.Color[] = [];
    const baseEmissiveIntensities: number[] = [];

    if (gltf) {
      model = SkeletonUtils.clone(gltf.scene);
      model.traverse((obj) => {
        if ((obj as THREE.Mesh).isMesh) {
          const mesh = obj as THREE.Mesh;
          mesh.castShadow = true;
          mesh.receiveShadow = true;
          shadowMeshes.push(mesh);
          if ((mesh as THREE.SkinnedMesh).isSkinnedMesh) {
            mesh.frustumCulled = false;
          }
          if (Array.isArray(mesh.material)) {
            mesh.material = mesh.material.map((m) => this.cloneHeroMat(m, clonedMaterials, baseEmissives, baseEmissiveIntensities));
          } else if (mesh.material) {
            mesh.material = this.cloneHeroMat(mesh.material, clonedMaterials, baseEmissives, baseEmissiveIntensities);
          }
        }
      });
    } else {
      // Emergency procedural fallback only if GLB failed to load
      const fallback = new THREE.Mesh(
        new THREE.CapsuleGeometry(0.32, 1.1, 8, 12),
        new THREE.MeshStandardMaterial({ color: HERO_MAP[heroId].hexPrimary, roughness: 0.6 })
      );
      fallback.position.y = 0.9;
      fallback.castShadow = true;
      shadowMeshes.push(fallback);
      model = fallback;
    }

    root.add(model);

    // Find Spine, Chest, Head, arms/hands, Thigh/Shin/Foot legs, and WeaponSocket_R reliably inside cloned armature hierarchy
    const spineNode = model.getObjectByName('Spine') ?? null;
    const chestNode = model.getObjectByName('Chest') ?? null;
    const leftHandNode = model.getObjectByName('Hand_L') ?? null;
    const rightHandNode = model.getObjectByName('Hand_R') ?? null;
    const upperArmLNode = model.getObjectByName('UpperArm_L') ?? null;
    const lowerArmLNode = model.getObjectByName('LowerArm_L') ?? null;
    const upperArmRNode = model.getObjectByName('UpperArm_R') ?? null;
    const lowerArmRNode = model.getObjectByName('LowerArm_R') ?? null;
    const thighLNode = model.getObjectByName('Thigh_L') ?? null;
    const shinLNode = model.getObjectByName('Shin_L') ?? null;
    const footLNode = model.getObjectByName('Foot_L') ?? null;
    const thighRNode = model.getObjectByName('Thigh_R') ?? null;
    const shinRNode = model.getObjectByName('Shin_R') ?? null;
    const footRNode = model.getObjectByName('Foot_R') ?? null;

    let weaponSocket = model.getObjectByName('WeaponSocket_R') ?? null;
    if (!weaponSocket) {
      weaponSocket = new THREE.Object3D();
      weaponSocket.name = 'WeaponSocket_R';
      if (rightHandNode) {
        rightHandNode.add(weaponSocket);
      } else {
        weaponSocket.position.set(0.24, 1.05, -0.22);
        model.add(weaponSocket);
      }
    }

    const headNode = model.getObjectByName('Head') ?? null;

    // Glider mount parented to `model` (NOT `root`!) so banking/pitching tilts glider 1:1 with hero hands.
    // Exact Glide palm-grip midpoint in model local space from build_characters.py: (0.000, 1.905, -0.180).
    const gliderMount = new THREE.Group();
    gliderMount.name = 'GliderMount';
    gliderMount.position.set(0, 1.905, -0.18);
    model.add(gliderMount);

    // AnimationMixer + all 13 baked Blender NLA animation clips (12 combat + LobbyShowcase, with graceful fallback)
    const mixer = new THREE.AnimationMixer(model);
    const clips = gltf?.animations ?? [];
    const actions = {} as Record<AnimName, THREE.AnimationAction>;
    const emptyClip = new THREE.AnimationClip('Empty', 0.5, []);

    const findClipByName = (name: string): THREE.AnimationClip | undefined =>
      clips.find((c) => c.name === name) ??
      clips.find((c) => c.name.toLowerCase() === name.toLowerCase());

    for (const animName of ANIM_NAMES) {
      const fallbackBase = ARMED_CLIP_FALLBACKS[animName];
      const clip =
        findClipByName(animName) ??
        (fallbackBase ? findClipByName(fallbackBase) : undefined) ??
        clips.find((c) => c.name.toLowerCase().startsWith(animName.toLowerCase())) ??
        clips[0] ??
        emptyClip;
      const action = mixer.clipAction(clip);
      action.setLoop(THREE.LoopRepeat, Infinity);
      action.enabled = true;
      actions[animName] = action;
    }

    actions.Idle.play();
    actions.Idle.setEffectiveWeight(1);

    // Pre-wire cached upper/lower split reload actions (upper: Spine..Hand_R; lower: Root..Foot_R)
    const splitClips = gltf ? this.getHeroReloadSplitClips(heroId, clips) : null;
    let reloadUpperAction: THREE.AnimationAction | null = null;
    let reloadLowerActions: Record<ReloadLowerMode, THREE.AnimationAction> | null = null;
    if (splitClips) {
      reloadUpperAction = mixer.clipAction(splitClips.reloadUpper);
      reloadUpperAction.setLoop(THREE.LoopOnce, 1);
      reloadUpperAction.clampWhenFinished = true;

      reloadLowerActions = {
        stand: mixer.clipAction(splitClips.lower.stand),
        walk: mixer.clipAction(splitClips.lower.walk),
        crouch: mixer.clipAction(splitClips.lower.crouch),
        jump: mixer.clipAction(splitClips.lower.jump),
      };
      for (const mode of RELOAD_LOWER_MODES) {
        reloadLowerActions[mode].setLoop(THREE.LoopRepeat, Infinity);
      }
    }

    let inReloadSplit = false;
    let activeReloadLower: ReloadLowerMode | null = null;

    const fadeOutSafely = (action: THREE.AnimationAction, duration: number): void => {
      if (!action.enabled) return;
      const curWeight = action.getEffectiveWeight();
      if (curWeight <= 0.001 || duration <= 0.001) {
        action.stop();
        return;
      }
      // Re-anchor weight to live effective weight so rapid back-and-forth transitions never pop
      action.weight = curWeight;
      action.fadeOut(duration);
    };

    // Overhead tactical vitals bars (hidden for local player, shown for AI rivals)
    const overheadGroup = new THREE.Group();
    overheadGroup.name = 'OverheadBars';
    overheadGroup.position.set(0, 2.18, 0);
    overheadGroup.visible = Boolean(options?.includeOverhead);

    const bgMat = new THREE.MeshBasicMaterial({
      color: 0x0f172a,
      transparent: true,
      opacity: 0.78,
      side: THREE.DoubleSide,
      depthTest: false,
    });
    const hpBg = new THREE.Mesh(this.barBgGeo, bgMat);
    hpBg.renderOrder = 50;
    overheadGroup.add(hpBg);

    const hpFillMat = new THREE.MeshBasicMaterial({
      color: 0x22c55e,
      side: THREE.DoubleSide,
      depthTest: false,
    });
    const hpBarFill = new THREE.Mesh(this.barFillGeo, hpFillMat);
    hpBarFill.position.z = 0.005;
    hpBarFill.renderOrder = 51;
    overheadGroup.add(hpBarFill);

    const shieldBg = new THREE.Mesh(this.barBgGeo, bgMat);
    shieldBg.position.y = 0.16;
    shieldBg.renderOrder = 50;
    overheadGroup.add(shieldBg);

    const shieldFillMat = new THREE.MeshBasicMaterial({
      color: 0x38bdf8,
      side: THREE.DoubleSide,
      depthTest: false,
    });
    const shieldBarFill = new THREE.Mesh(this.barFillGeo, shieldFillMat);
    shieldBarFill.position.set(0, 0.16, 0.005);
    shieldBarFill.renderOrder = 51;
    overheadGroup.add(shieldBarFill);
    root.add(overheadGroup);

    // Lazy overhead player nameplate billboard (allocated only when setNameplate() is called)
    let nameplateSprite: THREE.Sprite | null = null;
    let nameplateCanvas: HTMLCanvasElement | null = null;
    let nameplateTexture: THREE.CanvasTexture | null = null;
    let nameplateKey = '';

    // Glowing emerald Chat-reveal wallhack beacon ring (depthTest: false!)
    const revealMat = new THREE.MeshBasicMaterial({
      color: 0x10b981,
      transparent: true,
      opacity: 0.85,
      side: THREE.DoubleSide,
      depthTest: false,
      depthWrite: false,
    });
    const revealRing = new THREE.Mesh(this.revealRingGeo, revealMat);
    revealRing.position.y = 0.12;
    revealRing.renderOrder = 999;
    revealRing.visible = false;
    root.add(revealRing);

    const instance: HeroInstance = {
      heroId,
      root,
      model,
      mixer,
      actions,
      weaponSocket,
      spineNode,
      chestNode,
      headNode,
      leftHandNode,
      rightHandNode,
      upperArmLNode,
      lowerArmLNode,
      upperArmRNode,
      lowerArmRNode,
      thighLNode,
      shinLNode,
      footLNode,
      thighRNode,
      shinRNode,
      footRNode,
      gliderMount,
      overheadGroup,
      hpBarFill,
      shieldBarBg: shieldBg,
      shieldBarFill,
      revealRing,
      shadowMeshes,
      castShadowEnabled: true,
      currentAnim: 'Idle',
      crossFade(next: AnimName, duration = 0.16) {
        const nextAction = actions[next];
        if (!nextAction) return;

        if (inReloadSplit) {
          if (next === 'Reload') return;

          // Optionally preserve stride phase when exiting split reload back into locomotion
          let seedNextTime: number | null = null;
          if (reloadLowerActions && activeReloadLower) {
            const nextClipDur = nextAction.getClip().duration;
            if (nextClipDur > 0.001) {
              if (activeReloadLower === 'walk' && (next === 'RunArmed' || next === 'Run')) {
                const t = reloadLowerActions.walk.time;
                seedNextTime = ((t % nextClipDur) + nextClipDur) % nextClipDur;
              } else if (activeReloadLower === 'walk' && (next === 'SprintArmed' || next === 'Sprint')) {
                const walkDur = reloadLowerActions.walk.getClip().duration;
                if (walkDur > 0.001) {
                  const phase = (((reloadLowerActions.walk.time % walkDur) + walkDur) % walkDur) / walkDur;
                  seedNextTime = phase * nextClipDur;
                }
              } else if (activeReloadLower === 'crouch' && next === 'Crouch') {
                const t = reloadLowerActions.crouch.time;
                seedNextTime = ((t % nextClipDur) + nextClipDur) % nextClipDur;
              } else if (activeReloadLower === 'jump' && (next === 'JumpArmed' || next === 'Jump')) {
                const t = reloadLowerActions.jump.time;
                seedNextTime = ((t % nextClipDur) + nextClipDur) % nextClipDur;
              }
            }
          }

          if (reloadUpperAction) {
            fadeOutSafely(reloadUpperAction, duration);
          }
          if (reloadLowerActions) {
            for (const mode of RELOAD_LOWER_MODES) {
              fadeOutSafely(reloadLowerActions[mode], duration);
            }
          }
          for (const animName of ANIM_NAMES) {
            if (animName !== next) {
              fadeOutSafely(actions[animName], duration);
            }
          }

          nextAction.reset();
          if (seedNextTime !== null) {
            nextAction.time = seedNextTime;
          }
          nextAction.enabled = true;
          nextAction.setEffectiveWeight(1);
          nextAction.fadeIn(duration);
          nextAction.play();

          inReloadSplit = false;
          activeReloadLower = null;
          instance.currentAnim = next;
          return;
        }

        if (instance.currentAnim === next) return;
        const prevAction = actions[instance.currentAnim];
        nextAction.reset();
        nextAction.enabled = true;
        nextAction.setEffectiveWeight(1);
        nextAction.play();
        if (prevAction && prevAction !== nextAction) {
          const prevWeight = prevAction.getEffectiveWeight();
          if (prevWeight > 0.001 && duration > 0.001) {
            prevAction.weight = prevWeight;
            prevAction.crossFadeTo(nextAction, duration, false);
          } else {
            prevAction.stop();
            if (duration > 0.001) {
              nextAction.fadeIn(duration);
            }
          }
        }
        instance.currentAnim = next;
      },
      setReloadPose(
        lowerMode: ReloadLowerMode,
        reloadTimeScale: number,
        lowerTimeScale: number,
        fadeDur = 0.12
      ) {
        // Fallback safety for procedural capsule or GLBs lacking split bone tracks
        if (!reloadUpperAction || !reloadLowerActions) {
          actions.Reload.timeScale = reloadTimeScale;
          if (instance.currentAnim !== 'Reload') {
            actions.Reload.setLoop(THREE.LoopOnce, 1);
            actions.Reload.clampWhenFinished = true;
            instance.crossFade('Reload', fadeDur);
          }
          return;
        }

        if (!inReloadSplit) {
          const prevAnim = instance.currentAnim;
          const prevAction = actions[prevAnim];

          // Preserve seamless stride phase when entering reload from matching locomotion clip
          let seedLowerTime: number | null = null;
          const targetLower = reloadLowerActions[lowerMode];
          const lowerDur = targetLower.getClip().duration;
          if (prevAction && lowerDur > 0.001) {
            if (lowerMode === 'walk' && (prevAnim === 'RunArmed' || prevAnim === 'Run')) {
              seedLowerTime = ((prevAction.time % lowerDur) + lowerDur) % lowerDur;
            } else if (lowerMode === 'crouch' && prevAnim === 'Crouch') {
              seedLowerTime = ((prevAction.time % lowerDur) + lowerDur) % lowerDur;
            } else if (lowerMode === 'jump' && (prevAnim === 'JumpArmed' || prevAnim === 'Jump')) {
              seedLowerTime = ((prevAction.time % lowerDur) + lowerDur) % lowerDur;
            }
          }

          // Fade out active full-body clip (and any lingering cross-fading full-body clips)
          for (const animName of ANIM_NAMES) {
            fadeOutSafely(actions[animName], fadeDur);
          }
          // Ensure no stale lower-body actions linger from a very recent reload cancel
          for (const mode of RELOAD_LOWER_MODES) {
            if (mode !== lowerMode) {
              fadeOutSafely(reloadLowerActions[mode], fadeDur);
            }
          }

          reloadUpperAction.reset();
          reloadUpperAction.setLoop(THREE.LoopOnce, 1);
          reloadUpperAction.clampWhenFinished = true;
          reloadUpperAction.timeScale = reloadTimeScale;
          reloadUpperAction.enabled = true;
          reloadUpperAction.setEffectiveWeight(1);
          reloadUpperAction.fadeIn(fadeDur);
          reloadUpperAction.play();

          targetLower.reset();
          if (seedLowerTime !== null) {
            targetLower.time = seedLowerTime;
          }
          targetLower.setLoop(THREE.LoopRepeat, Infinity);
          targetLower.timeScale = lowerTimeScale;
          targetLower.enabled = true;
          targetLower.setEffectiveWeight(1);
          targetLower.fadeIn(fadeDur);
          targetLower.play();

          inReloadSplit = true;
          activeReloadLower = lowerMode;
          instance.currentAnim = 'Reload';
          return;
        }

        // Already in split reload: keep upper-body Reload running completely uninterrupted!
        reloadUpperAction.timeScale = reloadTimeScale;

        if (lowerMode === activeReloadLower) {
          reloadLowerActions[lowerMode].timeScale = lowerTimeScale;
          return;
        }

        // Cross-fade ONLY between lower-body actions while upper-body reload continues uninterrupted
        const lowerFade = 0.12;
        const prevLower = activeReloadLower ? reloadLowerActions[activeReloadLower] : null;
        const nextLower = reloadLowerActions[lowerMode];

        for (const mode of RELOAD_LOWER_MODES) {
          if (mode !== lowerMode) {
            const other = reloadLowerActions[mode];
            if (other !== prevLower) {
              fadeOutSafely(other, lowerFade);
            }
          }
        }

        nextLower.reset();
        nextLower.setLoop(THREE.LoopRepeat, Infinity);
        nextLower.timeScale = lowerTimeScale;
        nextLower.enabled = true;
        nextLower.setEffectiveWeight(1);
        nextLower.play();

        if (prevLower && prevLower !== nextLower && prevLower.enabled) {
          const prevWeight = prevLower.getEffectiveWeight();
          if (prevWeight > 0.001) {
            prevLower.weight = prevWeight;
            prevLower.crossFadeTo(nextLower, lowerFade, false);
          } else {
            prevLower.stop();
            nextLower.fadeIn(lowerFade);
          }
        } else {
          nextLower.fadeIn(lowerFade);
        }

        activeReloadLower = lowerMode;
      },
      getReloadProgress01(): number {
        const action = inReloadSplit && reloadUpperAction ? reloadUpperAction : actions.Reload;
        const dur = Math.max(action.getClip()?.duration || 2.0, 0.01);
        return THREE.MathUtils.clamp(action.time / dur, 0, 1);
      },
      flashHit(colorHex = 0xff4444, intensity = 0.65) {
        for (const m of clonedMaterials) {
          m.emissive.setHex(colorHex);
          m.emissiveIntensity = intensity;
        }
      },
      clearFlash() {
        for (let i = 0; i < clonedMaterials.length; i++) {
          clonedMaterials[i].emissive.copy(baseEmissives[i]);
          clonedMaterials[i].emissiveIntensity = baseEmissiveIntensities[i];
        }
      },
      setNameplate(name: string, teamColorCss?: string | null) {
        const cleanName = String(name ?? '').trim().slice(0, 18);
        if (!cleanName) {
          if (nameplateSprite) nameplateSprite.visible = false;
          return;
        }
        const colorKey = teamColorCss?.trim() || '';
        const nextKey = `${cleanName}|${colorKey}`;
        if (nextKey === nameplateKey && nameplateSprite) {
          nameplateSprite.visible = true;
          return;
        }
        nameplateKey = nextKey;

        if (!nameplateCanvas) {
          nameplateCanvas = document.createElement('canvas');
          nameplateCanvas.width = 256;
          nameplateCanvas.height = 64;
        }
        const ctx = nameplateCanvas.getContext('2d');
        if (!ctx) return;

        const W = 256;
        const H = 64;
        ctx.clearRect(0, 0, W, H);

        const hasDot = colorKey.length > 0;
        const dotRadius = 6.5;
        const dotGap = 9;
        const padX = 16;
        let fontSize = 22;
        const fontFamily = '-apple-system, BlinkMacSystemFont, "Google Sans", "Inter", sans-serif';
        ctx.font = `700 ${fontSize}px ${fontFamily}`;

        const maxContentW = W - 16 - padX * 2 - (hasDot ? dotRadius * 2 + dotGap : 0);
        let textW = ctx.measureText(cleanName).width;
        while (textW > maxContentW && fontSize > 14) {
          fontSize -= 1;
          ctx.font = `700 ${fontSize}px ${fontFamily}`;
          textW = ctx.measureText(cleanName).width;
        }

        const contentW = textW + (hasDot ? dotRadius * 2 + dotGap : 0);
        const pillW = Math.min(W - 8, Math.max(76, Math.ceil(contentW + padX * 2)));
        const pillH = 42;
        const pillX = Math.round((W - pillW) * 0.5);
        const pillY = Math.round((H - pillH) * 0.5);
        const radius = pillH * 0.5;

        // Sleek dark frosted pill background
        ctx.beginPath();
        ctx.moveTo(pillX + radius, pillY);
        ctx.lineTo(pillX + pillW - radius, pillY);
        ctx.quadraticCurveTo(pillX + pillW, pillY, pillX + pillW, pillY + radius);
        ctx.lineTo(pillX + pillW, pillY + pillH - radius);
        ctx.quadraticCurveTo(pillX + pillW, pillY + pillH, pillX + pillW - radius, pillY + pillH);
        ctx.lineTo(pillX + radius, pillY + pillH);
        ctx.quadraticCurveTo(pillX, pillY + pillH, pillX, pillY + pillH - radius);
        ctx.lineTo(pillX, pillY + radius);
        ctx.quadraticCurveTo(pillX, pillY, pillX + radius, pillY);
        ctx.closePath();

        ctx.fillStyle = 'rgba(15, 23, 42, 0.88)';
        ctx.fill();
        ctx.lineWidth = 2.4;
        ctx.strokeStyle = hasDot ? colorKey : 'rgba(255, 255, 255, 0.34)';
        ctx.stroke();

        const centerY = pillY + pillH * 0.5;
        let cursorX = Math.round((W - contentW) * 0.5);

        if (hasDot) {
          ctx.beginPath();
          ctx.arc(cursorX + dotRadius, centerY, dotRadius, 0, Math.PI * 2);
          ctx.fillStyle = colorKey;
          ctx.fill();
          ctx.lineWidth = 1.6;
          ctx.strokeStyle = '#ffffff';
          ctx.stroke();
          cursorX += dotRadius * 2 + dotGap;
        }

        ctx.fillStyle = '#ffffff';
        ctx.textAlign = 'left';
        ctx.textBaseline = 'middle';
        ctx.shadowColor = 'rgba(0, 0, 0, 0.65)';
        ctx.shadowBlur = 3;
        ctx.fillText(cleanName, cursorX, centerY + 1);
        ctx.shadowColor = 'transparent';
        ctx.shadowBlur = 0;

        if (!nameplateTexture) {
          nameplateTexture = new THREE.CanvasTexture(nameplateCanvas);
          nameplateTexture.colorSpace = THREE.SRGBColorSpace;
          nameplateTexture.minFilter = THREE.LinearFilter;
          nameplateTexture.magFilter = THREE.LinearFilter;
          nameplateTexture.generateMipmaps = false;
        } else {
          nameplateTexture.needsUpdate = true;
        }

        if (!nameplateSprite) {
          const spriteMat = new THREE.SpriteMaterial({
            map: nameplateTexture,
            transparent: true,
            depthTest: false,
            depthWrite: false,
          });
          nameplateSprite = new THREE.Sprite(spriteMat);
          nameplateSprite.name = 'PlayerNameplate';
          nameplateSprite.position.set(0, 0.36, 0.01);
          nameplateSprite.scale.set(1.24, 0.31, 1);
          nameplateSprite.renderOrder = 52;
          overheadGroup.add(nameplateSprite);
        }
        nameplateSprite.visible = true;
      },
    };

    return instance;
  }

  /**
   * Toggles shadow casting on a hero instance using its cached mesh list (O(1) no-op when unchanged)
   * so distant bots can skip the shadow pass without per-frame scene-graph traversals.
   */
  public setHeroCastShadow(hero: HeroInstance, enabled: boolean): void {
    if (hero.castShadowEnabled === enabled) return;
    hero.castShadowEnabled = enabled;
    const meshes = hero.shadowMeshes;
    for (let i = 0; i < meshes.length; i++) {
      meshes[i].castShadow = enabled;
    }
    if (hero.weaponSocket.children.length > 0) {
      hero.weaponSocket.traverse((obj) => {
        if ((obj as THREE.Mesh).isMesh) {
          (obj as THREE.Mesh).castShadow = enabled;
        }
      });
    }
  }

  private cloneHeroMat(
    mat: THREE.Material,
    outList: THREE.MeshStandardMaterial[],
    baseEmissives: THREE.Color[],
    baseIntensities: number[]
  ): THREE.Material {
    const cloned = mat.clone();
    if ((cloned as THREE.MeshStandardMaterial).isMeshStandardMaterial) {
      const std = cloned as THREE.MeshStandardMaterial;
      outList.push(std);
      baseEmissives.push(std.emissive.clone());
      baseIntensities.push(std.emissiveIntensity ?? 0);
    }
    return cloned;
  }

  private getWeaponAccentMaterial(sourceMat: THREE.Material, rarity: Rarity): THREE.MeshStandardMaterial {
    const key = `${sourceMat.uuid}:${rarity}`;
    const existing = this.weaponAccentMats.get(key);
    if (existing) return existing;
    const rarityCfg = RARITY_CONFIG[rarity];
    const cloned = sourceMat.clone() as THREE.MeshStandardMaterial;
    cloned.color.setHex(rarityCfg.hex);
    if (cloned.emissive) {
      cloned.emissive.setHex(rarityCfg.emissiveHex);
      cloned.emissiveIntensity = rarityCfg.emissiveIntensity;
    }
    this.weaponAccentMats.set(key, cloned);
    return cloned;
  }

  /**
   * Clones the Blender weapon .glb, dynamically tints the `RarityAccent` material slot
   * to Common/Rare/Epic (via shared cached materials), and locates the exact barrel-tip `MuzzlePoint`.
   */
  public instantiateWeapon(weaponId: WeaponId, rarity: Rarity): WeaponInstance {
    const gltf = this.cache.get(`weapon:${weaponId}`);
    const root = new THREE.Group();
    root.name = `Weapon_${weaponId}_${rarity}`;

    const rarityCfg = RARITY_CONFIG[rarity];
    let muzzleNode: THREE.Object3D | null = null;

    if (gltf) {
      const cloned = gltf.scene.clone(true);
      cloned.traverse((obj) => {
        if ((obj as THREE.Mesh).isMesh) {
          const mesh = obj as THREE.Mesh;
          mesh.castShadow = true;
          mesh.receiveShadow = true;
          const tintOne = (mat: THREE.Material): THREE.Material => {
            if (mat.name && mat.name.toLowerCase().includes('rarityaccent')) {
              return this.getWeaponAccentMaterial(mat, rarity);
            }
            return mat;
          };
          if (Array.isArray(mesh.material)) {
            mesh.material = mesh.material.map(tintOne);
          } else if (mesh.material) {
            mesh.material = tintOne(mesh.material);
          }
        }
      });
      root.add(cloned);
      muzzleNode = cloned.getObjectByName('MuzzlePoint') ?? null;
    } else {
      const fallback = new THREE.Mesh(
        new THREE.BoxGeometry(0.08, 0.14, 0.65),
        new THREE.MeshStandardMaterial({ color: rarityCfg.hex, metalness: 0.7, roughness: 0.3 })
      );
      fallback.position.set(0, 0.06, -0.22);
      root.add(fallback);
    }

    if (!muzzleNode) {
      muzzleNode = new THREE.Object3D();
      muzzleNode.name = 'MuzzlePoint';
      muzzleNode.position.set(0, 0.088, -0.55);
      root.add(muzzleNode);
    }

    return {
      weaponId,
      rarity,
      root,
      muzzleNode,
    };
  }

  public instantiateUtility(utilityId: UtilityItemId): THREE.Group {
    const gltf = this.cache.get(`utility:${utilityId}`);
    const root = new THREE.Group();
    root.name = `Utility_${utilityId}`;
    if (gltf) {
      root.add(gltf.scene.clone(true));
    } else {
      const fallback = new THREE.Mesh(
        new THREE.CylinderGeometry(0.12, 0.12, 0.36, 12),
        new THREE.MeshStandardMaterial({ color: UTILITY_ITEMS[utilityId].color, roughness: 0.3 })
      );
      fallback.position.y = 0.18;
      root.add(fallback);
    }
    return root;
  }

  public instantiateProp(propId: PropAssetId): THREE.Group {
    const gltf = this.cache.get(`prop:${propId}`);
    const root = new THREE.Group();
    root.name = `Prop_${propId}`;
    if (gltf) {
      root.add(gltf.scene.clone(true));
    } else if (propId === 'glider') {
      const wing = new THREE.Mesh(
        new THREE.BoxGeometry(3.2, 0.1, 1.2),
        new THREE.MeshStandardMaterial({ color: 0x4285f4, roughness: 0.4 })
      );
      wing.position.y = 0.8;
      root.add(wing);
    } else {
      const crate = new THREE.Mesh(
        new THREE.BoxGeometry(1.4, 1.4, 1.4),
        new THREE.MeshStandardMaterial({ color: 0xfbbc04, metalness: 0.4, roughness: 0.5 })
      );
      crate.position.y = 0.7;
      root.add(crate);
    }
    return root;
  }

  public instantiateMapAsset(key: MapAssetKey): THREE.Group | null {
    const gltf = this.cache.get(`map:${key}`);
    if (!gltf) return null;
    const root = new THREE.Group();
    root.name = `Map_${key}`;
    root.add(gltf.scene.clone(true));
    return root;
  }

  public getMapAssetTemplate(key: MapAssetKey): THREE.Group | null {
    const gltf = this.cache.get(`map:${key}`);
    return gltf ? gltf.scene : null;
  }

  private getLootRingMaterial(rarity: Rarity): THREE.MeshBasicMaterial {
    const cached = this.lootRingMats.get(rarity);
    if (cached) return cached;
    const rarityCfg = RARITY_CONFIG[rarity];
    const mat = new THREE.MeshBasicMaterial({
      color: rarityCfg.hex,
      transparent: true,
      opacity: rarity === 'epic' ? 0.92 : rarity === 'rare' ? 0.8 : 0.65,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    this.lootRingMats.set(rarity, mat);
    return mat;
  }

  private getLootBeamMaterial(rarity: Rarity): THREE.MeshBasicMaterial {
    const cached = this.lootBeamMats.get(rarity);
    if (cached) return cached;
    const rarityCfg = RARITY_CONFIG[rarity];
    const mat = new THREE.MeshBasicMaterial({
      color: rarityCfg.hex,
      transparent: true,
      opacity: rarity === 'epic' ? 0.24 : rarity === 'rare' ? 0.17 : 0.11,
      side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    this.lootBeamMats.set(rarity, mat);
    return mat;
  }

  private getChestAccentMaterial(
    tier: ChestTier,
    sourceMat?: THREE.Material
  ): THREE.MeshStandardMaterial {
    const cached = this.chestAccentMats.get(tier);
    if (cached) return cached;
    const tierCfg = CHEST_TIER_CONFIG[tier];
    const mat =
      sourceMat && (sourceMat as THREE.MeshStandardMaterial).isMeshStandardMaterial
        ? (sourceMat.clone() as THREE.MeshStandardMaterial)
        : new THREE.MeshStandardMaterial({
            metalness: 0.4,
            roughness: 0.3,
          });
    mat.color.setHex(tierCfg.hex);
    if (mat.emissive) {
      mat.emissive.setHex(tierCfg.emissiveHex);
      mat.emissiveIntensity = tierCfg.emissiveIntensity;
    }
    this.chestAccentMats.set(tier, mat);
    return mat;
  }

  private getChestOpenedAccentMaterial(
    tier: ChestTier,
    unopenedMat: THREE.MeshStandardMaterial
  ): THREE.MeshStandardMaterial {
    const cached = this.chestOpenedAccentMats.get(tier);
    if (cached) return cached;
    const mat = unopenedMat.clone();
    mat.emissiveIntensity = 0.16;
    this.chestOpenedAccentMats.set(tier, mat);
    return mat;
  }

  private getChestRingMaterial(tier: ChestTier): THREE.MeshBasicMaterial {
    const cached = this.chestRingMats.get(tier);
    if (cached) return cached;
    const tierCfg = CHEST_TIER_CONFIG[tier];
    const mat = new THREE.MeshBasicMaterial({
      color: tierCfg.hex,
      transparent: true,
      opacity: tier === 3 ? 0.88 : tier === 2 ? 0.76 : 0.62,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    this.chestRingMats.set(tier, mat);
    return mat;
  }

  private getChestOpenedRingMaterial(tier: ChestTier): THREE.MeshBasicMaterial {
    const cached = this.chestOpenedRingMats.get(tier);
    if (cached) return cached;
    const tierCfg = CHEST_TIER_CONFIG[tier];
    const mat = new THREE.MeshBasicMaterial({
      color: tierCfg.hex,
      transparent: true,
      opacity: 0.16,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    this.chestOpenedRingMats.set(tier, mat);
    return mat;
  }

  private getChestBeamMaterial(tier: ChestTier): THREE.MeshBasicMaterial {
    const cached = this.chestBeamMats.get(tier);
    if (cached) return cached;
    const tierCfg = CHEST_TIER_CONFIG[tier];
    const mat = new THREE.MeshBasicMaterial({
      color: tierCfg.hex,
      transparent: true,
      opacity: tier === 3 ? 0.24 : tier === 2 ? 0.16 : 0.11,
      side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    this.chestBeamMats.set(tier, mat);
    return mat;
  }

  /**
   * Wraps the real Blender weapon or utility .glb inside a glowing rotating
   * rarity beacon with ground ring & vertical translucent beam (no shadow casting).
   */
  public createLootDropVisual(
    kind: 'weapon' | 'item',
    id: WeaponId | UtilityItemId,
    rarity: Rarity
  ): LootDropVisual {
    const root = new THREE.Group();
    root.name = `Loot_${kind}_${id}_${rarity}`;

    const itemHolder = new THREE.Group();
    itemHolder.position.y = 0.56;

    if (kind === 'weapon') {
      const weapon = this.instantiateWeapon(id as WeaponId, rarity);
      weapon.root.scale.setScalar(1.38);
      // Slight heroic tilt so silhouette reads cleanly from third-person camera
      weapon.root.rotation.set(0.14, 0, 0.12);
      itemHolder.add(weapon.root);
    } else {
      const util = this.instantiateUtility(id as UtilityItemId);
      util.scale.setScalar(1.45);
      itemHolder.add(util);
    }

    // Ground loot drops never cast shadows into the directional shadow pass
    itemHolder.traverse((obj) => {
      if ((obj as THREE.Mesh).isMesh) {
        const mesh = obj as THREE.Mesh;
        mesh.castShadow = false;
        mesh.receiveShadow = true;
      }
    });
    root.add(itemHolder);

    const ringMat = this.getLootRingMaterial(rarity);
    const ring = new THREE.Mesh(this.lootRingGeo, ringMat);
    ring.position.y = 0.05;
    ring.castShadow = false;
    ring.receiveShadow = false;
    root.add(ring);

    const beamHeight = rarity === 'epic' ? 5.6 : rarity === 'rare' ? 4.2 : 2.9;
    const beamMat = this.getLootBeamMaterial(rarity);
    const beam = new THREE.Mesh(this.lootBeamGeo, beamMat);
    beam.scale.set(1, beamHeight, 1);
    beam.position.y = 0.04;
    beam.castShadow = false;
    beam.receiveShadow = false;
    root.add(beam);

    return {
      root,
      itemHolder,
      beam,
      ring,
      rarity,
    };
  }

  /**
   * Clones the Blender 3D Loot Chest (`prop_loot_chest.glb`), applies shared cached per-tier
   * `RarityAccent`, ring, and beam materials (3 per tier across all 150 chests), disables shadow
   * casting on chests/beams/rings while preserving `receiveShadow = true` on chest base/lid,
   * and locates the hinged `ChestLid` node.
   */
  public instantiateLootChest(tier: ChestTier): LootChestVisual {
    const gltf = this.cache.get('prop:loot_chest');
    const root = new THREE.Group();
    root.name = `LootChest_T${tier}`;

    const accentSlots: { mesh: THREE.Mesh; index: number }[] = [];
    let sharedAccentMat: THREE.MeshStandardMaterial | null = null;
    let chestModel: THREE.Object3D;
    let lidNode: THREE.Object3D | null = null;

    if (gltf) {
      const cloned = gltf.scene.clone(true);
      cloned.traverse((obj) => {
        if ((obj as THREE.Mesh).isMesh) {
          const mesh = obj as THREE.Mesh;
          mesh.castShadow = false;
          mesh.receiveShadow = true;
          if (Array.isArray(mesh.material)) {
            mesh.material = mesh.material.map((mat, idx) => {
              if (mat && mat.name && mat.name.toLowerCase().includes('rarityaccent')) {
                const shared = this.getChestAccentMaterial(tier, mat);
                sharedAccentMat = shared;
                accentSlots.push({ mesh, index: idx });
                return shared;
              }
              return mat;
            });
          } else if (mesh.material) {
            const mat = mesh.material;
            if (mat.name && mat.name.toLowerCase().includes('rarityaccent')) {
              const shared = this.getChestAccentMaterial(tier, mat);
              sharedAccentMat = shared;
              accentSlots.push({ mesh, index: -1 });
              mesh.material = shared;
            }
          }
        }
      });
      chestModel = cloned;
      lidNode = cloned.getObjectByName('ChestLid') ?? null;
    } else {
      // Fallback chest only if GLB failed to load
      const fallback = new THREE.Group();
      if (!this.chestFallbackBaseMat) {
        this.chestFallbackBaseMat = new THREE.MeshStandardMaterial({
          color: 0x334155,
          metalness: 0.55,
          roughness: 0.42,
        });
      }
      const baseMat = this.chestFallbackBaseMat;
      const accentMat = this.getChestAccentMaterial(tier);
      sharedAccentMat = accentMat;

      const base = new THREE.Mesh(new THREE.BoxGeometry(1.12, 0.48, 0.68), baseMat);
      base.position.y = 0.24;
      base.castShadow = false;
      base.receiveShadow = true;
      fallback.add(base);

      const trim = new THREE.Mesh(new THREE.BoxGeometry(1.16, 0.08, 0.72), accentMat);
      trim.position.y = 0.44;
      trim.castShadow = false;
      trim.receiveShadow = true;
      accentSlots.push({ mesh: trim, index: -1 });
      fallback.add(trim);

      const lidPivot = new THREE.Group();
      lidPivot.name = 'ChestLid';
      lidPivot.position.set(0, 0.42, 0.31);
      const lidMesh = new THREE.Mesh(new THREE.BoxGeometry(1.08, 0.22, 0.64), baseMat);
      lidMesh.position.set(0, 0.11, -0.31);
      lidMesh.castShadow = false;
      lidMesh.receiveShadow = true;
      lidPivot.add(lidMesh);
      fallback.add(lidPivot);

      chestModel = fallback;
      lidNode = lidPivot;
    }

    root.add(chestModel);

    // Shared unopened ground beacon ring + subtle vertical light column (zero shadow casting)
    const ringMat = this.getChestRingMaterial(tier);
    const ring = new THREE.Mesh(this.chestRingGeo, ringMat);
    ring.position.y = 0.04;
    ring.castShadow = false;
    ring.receiveShadow = false;
    root.add(ring);

    const beamHeight = tier === 3 ? 5.6 : tier === 2 ? 4.0 : 2.6;
    const beamMat = this.getChestBeamMaterial(tier);
    const beam = new THREE.Mesh(this.chestBeamGeo, beamMat);
    beam.scale.set(1, beamHeight, 1);
    beam.position.y = 0.04;
    beam.castShadow = false;
    beam.receiveShadow = false;
    root.add(beam);

    const accentMaterials = sharedAccentMat ? [sharedAccentMat] : [];

    const visual: LootChestVisual = {
      root,
      chestModel,
      lidNode,
      beam,
      beamMat,
      ring,
      ringMat,
      accentMaterials,
      tier,
      markOpened: () => {
        const openedRingMat = this.getChestOpenedRingMaterial(tier);
        visual.beam.visible = false;
        visual.ring.material = openedRingMat;
        visual.ringMat = openedRingMat;
        if (sharedAccentMat) {
          const openedAccentMat = this.getChestOpenedAccentMaterial(tier, sharedAccentMat);
          for (let i = 0; i < accentSlots.length; i++) {
            const slot = accentSlots[i];
            if (slot.index >= 0 && Array.isArray(slot.mesh.material)) {
              slot.mesh.material[slot.index] = openedAccentMat;
            } else {
              slot.mesh.material = openedAccentMat;
            }
          }
          visual.accentMaterials = [openedAccentMat];
        }
      },
    };

    return visual;
  }

  public setLootChestOpened(visual: LootChestVisual): void {
    visual.markOpened?.();
  }

  /**
   * Instantiates a rideable Google GBike (`prop_gbike_rideable.glb`), cloning ONLY the
   * `GBike_FramePrimary` and `GBike_FenderAccent` materials per instance so authentic
   * 4-variant Google liveries never mutate shared cached materials.
   */
  public instantiateRideableGBike(colorVariantIndex: number): RideableGBikeVisual {
    const safeIdx = ((Math.floor(colorVariantIndex) % GBIKE_LIVERY_PAIRS.length) + GBIKE_LIVERY_PAIRS.length) % GBIKE_LIVERY_PAIRS.length;
    const livery = GBIKE_LIVERY_PAIRS[safeIdx];
    const gltf = this.cache.get('prop:gbike_rideable');
    const root = new THREE.Group();
    root.name = `RideableGBike_v${safeIdx}`;

    let frontAssembly: THREE.Object3D | null = null;
    let wheelFront: THREE.Object3D | null = null;
    let wheelRear: THREE.Object3D | null = null;
    let crankPedals: THREE.Object3D | null = null;
    let seatMount: THREE.Object3D | null = null;
    let frameMat: THREE.MeshStandardMaterial | null = null;
    let fenderMat: THREE.MeshStandardMaterial | null = null;

    if (gltf) {
      const cloned = gltf.scene.clone(true);
      const tintMaterial = (mat: THREE.Material): THREE.Material => {
        if (!mat || !mat.name) return mat;
        const lower = mat.name.toLowerCase();
        if (lower.includes('gbike_frameprimary')) {
          if (!frameMat) {
            frameMat = mat.clone() as THREE.MeshStandardMaterial;
            if (frameMat.color) frameMat.color.setHex(livery.frameHex);
          }
          return frameMat;
        }
        if (lower.includes('gbike_fenderaccent')) {
          if (!fenderMat) {
            fenderMat = mat.clone() as THREE.MeshStandardMaterial;
            if (fenderMat.color) fenderMat.color.setHex(livery.fenderHex);
          }
          return fenderMat;
        }
        return mat;
      };

      cloned.traverse((obj) => {
        if ((obj as THREE.Mesh).isMesh) {
          const mesh = obj as THREE.Mesh;
          mesh.castShadow = true;
          mesh.receiveShadow = true;
          if (Array.isArray(mesh.material)) {
            mesh.material = mesh.material.map(tintMaterial);
          } else if (mesh.material) {
            mesh.material = tintMaterial(mesh.material);
          }
        }
      });

      root.add(cloned);
      frontAssembly = cloned.getObjectByName('GBike_FrontAssembly') ?? null;
      wheelFront = cloned.getObjectByName('GBike_WheelFront') ?? null;
      wheelRear = cloned.getObjectByName('GBike_WheelRear') ?? null;
      crankPedals = cloned.getObjectByName('GBike_CrankPedals') ?? null;
      seatMount = cloned.getObjectByName('GBike_SeatMount') ?? null;
    } else {
      // Minimal procedural fallback only if GLB failed to load
      frameMat = new THREE.MeshStandardMaterial({
        color: livery.frameHex,
        metalness: 0.32,
        roughness: 0.26,
      });
      fenderMat = new THREE.MeshStandardMaterial({
        color: livery.fenderHex,
        metalness: 0.2,
        roughness: 0.35,
      });
      const frame = new THREE.Mesh(new THREE.BoxGeometry(0.24, 0.56, 1.35), frameMat);
      frame.position.set(0, 0.52, 0);
      frame.castShadow = true;
      frame.receiveShadow = true;
      root.add(frame);

      const tireMat = new THREE.MeshStandardMaterial({ color: 0x1f2937, roughness: 0.85 });
      const wheelGeo = new THREE.TorusGeometry(0.32, 0.045, 8, 20);
      wheelGeo.rotateY(Math.PI / 2);

      const frontPivot = new THREE.Group();
      frontPivot.name = 'GBike_FrontAssembly';
      frontPivot.position.set(0, 0.74, -0.36);
      const wf = new THREE.Mesh(wheelGeo, tireMat);
      wf.name = 'GBike_WheelFront';
      wf.position.set(0, -0.4, -0.2);
      wf.castShadow = true;
      frontPivot.add(wf);
      root.add(frontPivot);

      const wr = new THREE.Mesh(wheelGeo, tireMat);
      wr.name = 'GBike_WheelRear';
      wr.position.set(0, 0.34, 0.52);
      wr.castShadow = true;
      root.add(wr);

      const crank = new THREE.Group();
      crank.name = 'GBike_CrankPedals';
      crank.position.set(0, 0.3, 0.06);
      root.add(crank);

      const seat = new THREE.Object3D();
      seat.name = 'GBike_SeatMount';
      seat.position.set(0, 0.95, 0.2);
      root.add(seat);

      frontAssembly = frontPivot;
      wheelFront = wf;
      wheelRear = wr;
      crankPedals = crank;
      seatMount = seat;
    }

    return {
      root,
      frontAssembly,
      wheelFront,
      wheelRear,
      crankPedals,
      seatMount,
      frameMat,
      fenderMat,
    };
  }

  /**
   * Instantiates a Google TechStop Weapon Upgrade Center (`prop_techstop_kiosk.glb`),
   * capturing the floating `TechStop_HoloIcon` node (`local (0, 1.29, -0.08)`) for live bob/spin
   * and enabling clean shadows on opaque kiosk geometry.
   */
  public instantiateTechStop(): TechStopVisual {
    const gltf = this.cache.get('prop:techstop_kiosk');
    const root = new THREE.Group();
    root.name = 'TechStopKiosk';

    let holoIcon: THREE.Object3D | null = null;

    if (gltf) {
      const cloned = gltf.scene.clone(true);
      cloned.traverse((obj) => {
        if ((obj as THREE.Mesh).isMesh) {
          const mesh = obj as THREE.Mesh;
          const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
          const isTranslucentHolo = mats.some((m) => {
            if (!m) return false;
            const std = m as THREE.MeshStandardMaterial;
            const n = (m.name || '').toLowerCase();
            return (std.transparent && std.opacity < 0.95) || n.includes('holobeam') || n.includes('holoicon');
          });
          mesh.castShadow = !isTranslucentHolo;
          mesh.receiveShadow = !isTranslucentHolo;
        }
      });
      root.add(cloned);
      holoIcon = cloned.getObjectByName('TechStop_HoloIcon') ?? null;
    } else {
      // Minimal fallback kiosk only if GLB failed to load
      const desk = new THREE.Mesh(
        new THREE.BoxGeometry(2.5, 1.0, 1.1),
        new THREE.MeshStandardMaterial({ color: 0xf1f5f9, roughness: 0.45 })
      );
      desk.position.y = 0.5;
      desk.castShadow = true;
      desk.receiveShadow = true;
      root.add(desk);

      const canopy = new THREE.Mesh(
        new THREE.BoxGeometry(2.52, 0.25, 1.12),
        new THREE.MeshStandardMaterial({ color: 0x4285f4, roughness: 0.35 })
      );
      canopy.position.y = 2.3;
      canopy.castShadow = true;
      root.add(canopy);

      const icon = new THREE.Mesh(
        new THREE.OctahedronGeometry(0.18, 0),
        new THREE.MeshBasicMaterial({ color: 0x38bdf8, transparent: true, opacity: 0.9 })
      );
      icon.name = 'TechStop_HoloIcon';
      icon.position.set(0, 1.29, -0.08);
      root.add(icon);
      holoIcon = icon;
    }

    return {
      root,
      holoIcon,
    };
  }

  /**
   * Instantiates the flying winged Google GBus (`prop_google_gbus.glb`),
   * capturing `GBus_RotorL`, `GBus_RotorR`, `GBus_ThrusterL`, and `GBus_ThrusterR`
   * for live propeller spin and dual jet contrail emission.
   */
  public instantiateGoogleGBus(): GoogleGBusVisual {
    const gltf = this.cache.get('prop:google_gbus');
    const root = new THREE.Group();
    root.name = 'GoogleGBus';

    let rotorL: THREE.Object3D | null = null;
    let rotorR: THREE.Object3D | null = null;
    let thrusterL: THREE.Object3D | null = null;
    let thrusterR: THREE.Object3D | null = null;

    if (gltf) {
      const cloned = gltf.scene.clone(true);
      cloned.traverse((obj) => {
        if ((obj as THREE.Mesh).isMesh) {
          const mesh = obj as THREE.Mesh;
          mesh.castShadow = false;
          mesh.receiveShadow = false;
        }
      });
      root.add(cloned);
      rotorL = cloned.getObjectByName('GBus_RotorL') ?? null;
      rotorR = cloned.getObjectByName('GBus_RotorR') ?? null;
      thrusterL = cloned.getObjectByName('GBus_ThrusterL') ?? null;
      thrusterR = cloned.getObjectByName('GBus_ThrusterR') ?? null;
    } else {
      // Minimal procedural fallback only if GLB failed to load
      const body = new THREE.Mesh(
        new THREE.BoxGeometry(2.6, 3.2, 11.8),
        new THREE.MeshStandardMaterial({ color: 0xf8fafc, roughness: 0.3 })
      );
      root.add(body);
      const wing = new THREE.Mesh(
        new THREE.BoxGeometry(13.4, 0.28, 2.2),
        new THREE.MeshStandardMaterial({ color: 0x4285f4, roughness: 0.35 })
      );
      wing.position.set(0, 0.42, -0.2);
      root.add(wing);

      const tL = new THREE.Object3D();
      tL.name = 'GBus_ThrusterL';
      tL.position.set(-3.85, 0.42, 1.55);
      root.add(tL);
      const tR = new THREE.Object3D();
      tR.name = 'GBus_ThrusterR';
      tR.position.set(3.85, 0.42, 1.55);
      root.add(tR);
      thrusterL = tL;
      thrusterR = tR;
    }

    return {
      root,
      rotorL,
      rotorR,
      thrusterL,
      thrusterR,
    };
  }
}

export const sharedAssetManager = new AssetManager();

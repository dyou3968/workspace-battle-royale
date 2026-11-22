import {
  ChestTier,
  ChestTierConfig,
  GameModeDef,
  GameModeId,
  GameSettings,
  InventorySlot,
  ProductHeroDef,
  ProductHeroId,
  Rarity,
  RarityConfig,
  StormPhaseDef,
  UtilityItemDef,
  UtilityItemId,
  WeaponDef,
  WeaponId,
} from '../types';

export const GAME_CONSTANTS = {
  MAX_HEALTH: 100,
  START_HEALTH: 100,
  MAX_SHIELD: 100,
  START_SHIELD: 0, // Unarmed start: players & bots must open Loot Chests to gear up
  MAX_MANA: 100,
  START_MANA: 40, // Intentional v2 pacing: no instant Ult on landing
  MANA_REGEN_PER_SEC: 5.0,
  ELIM_MANA_BONUS: 30,

  WALK_SPEED: 8.5,
  SPRINT_SPEED: 12.8,
  CROUCH_SPEED: 4.8,
  JUMP_IMPULSE: 12.2,
  GRAVITY: 28.0,

  SLIDE_MIN_ENTRY_SPEED: 6.8,
  SLIDE_RUN_SPEED: 13.6,
  SLIDE_SPRINT_SPEED: 15.6,
  SLIDE_MIN_END_SPEED: 4.8,
  SLIDE_DURATION: 0.90,
  SLIDE_MAX_DURATION: 1.55,
  SLIDE_COOLDOWN: 0.45,

  STANDING_HEIGHT: 1.82,
  CROUCH_HEIGHT: 1.15,
  EYE_HEIGHT_STANDING: 1.62,
  EYE_HEIGHT_CROUCHING: 1.02,
  EYE_HEIGHT_SLIDING: 0.78,
  CROUCH_SPREAD_MULT: 0.55, // Tightens spread by 45%

  HEAD_RADIUS: 0.25,
  HEAD_OFFSET_STANDING: 1.60,
  HEAD_OFFSET_CROUCHING: 1.00,
  TORSO_RADIUS: 0.42,
  TORSO_MIN_Y: 0.15,
  TORSO_MAX_STANDING: 1.42,
  TORSO_MAX_CROUCHING: 0.85,

  SKY_DROP_ALTITUDE: 135,
  GLIDER_STOW_CLEARANCE: 3.0,
  CHEST_OPEN_CHANNEL_TIME: 0.75,
  CHEST_INTERACT_RADIUS: 3.2,
  SUPPLY_DROP_CHANNEL_TIME: 1.5,
  TOTAL_COMBATANTS: 20, // 1 player + 19 AI bots

  GBIKE_MAX_SPEED: 15.6,
  GBIKE_BOOST_SPEED: 19.4,
  GBIKE_REVERSE_SPEED: 4.4,
  GBIKE_MOUNT_RADIUS: 3.4,
  GBIKE_BAIL_SLIDE_MIN_SPEED: 8.5,
  GBIKE_HOP_IMPULSE: 8.2,

  TECHSTOP_INTERACT_RADIUS: 3.4,
  TECHSTOP_RARE_MANA_COST: 45,
  TECHSTOP_EPIC_MANA_COST: 75,
  TECHSTOP_RARE_CHANNEL_TIME: 1.2,
  TECHSTOP_EPIC_CHANNEL_TIME: 1.5,

  ARENA_MIN_X: -300,
  ARENA_MAX_X: 300,
  ARENA_MIN_Z: -190,
  ARENA_MAX_Z: 190,
  ARENA_WIDTH: 600,
  ARENA_DEPTH: 380,
} as const;

export const RARITY_CONFIG: Record<Rarity, RarityConfig> = {
  common: {
    id: 'common',
    label: 'Common',
    colorCss: '#9aa0a6',
    hex: 0x9aa0a6,
    emissiveHex: 0x4b5563,
    emissiveIntensity: 0.12,
    mult: 1.0,
    reloadMult: 1.0,
    standardWeight: 55,
    highTierWeight: 15,
  },
  rare: {
    id: 'rare',
    label: 'Rare',
    colorCss: '#4285f4',
    hex: 0x4285f4,
    emissiveHex: 0x2563eb,
    emissiveIntensity: 0.55,
    mult: 1.25,
    reloadMult: 0.88,
    standardWeight: 31,
    highTierWeight: 45,
  },
  epic: {
    id: 'epic',
    label: 'Epic',
    colorCss: '#a855f7',
    hex: 0xa855f7,
    emissiveHex: 0x9333ea,
    emissiveIntensity: 0.85,
    mult: 1.55,
    reloadMult: 0.76,
    standardWeight: 14,
    highTierWeight: 40,
  },
};

export const CHEST_TIER_CONFIG: Record<ChestTier, ChestTierConfig> = {
  1: {
    tier: 1,
    name: 'Tier 1 Chest',
    shortLabel: 'Common Supply Chest',
    colorCss: '#f59e0b',
    hex: 0xf59e0b,
    emissiveHex: 0xd97706,
    emissiveIntensity: 0.65,
    minItems: 1,
    maxItems: 2,
  },
  2: {
    tier: 2,
    name: 'Tier 2 Rare Chest',
    shortLabel: 'Rare Tech Chest',
    colorCss: '#4285f4',
    hex: 0x4285f4,
    emissiveHex: 0x2563eb,
    emissiveIntensity: 0.88,
    minItems: 2,
    maxItems: 3,
  },
  3: {
    tier: 3,
    name: 'Tier 3 Epic Vault Chest',
    shortLabel: 'Epic Vault Chest',
    colorCss: '#a855f7',
    hex: 0xa855f7,
    emissiveHex: 0x9333ea,
    emissiveIntensity: 1.15,
    minItems: 3,
    maxItems: 3,
  },
};

export const PRODUCT_HEROES: ProductHeroDef[] = [
  {
    id: 'gmail',
    personaName: 'Gmail AI',
    productName: 'Gmail',
    displayName: 'Gmail AI',
    name: 'Gmail AI',
    shortBadge: 'M',
    role: 'Autonomous Inbox Striker AI',
    tagline: 'Embodied 3D Gmail icon AI engineered for relentless multi-target inbox pressure.',
    primaryColor: '#ea4335',
    accentColor: '#ffffff',
    hexPrimary: 0xea4335,
    hexAccent: 0xffffff,
    assetPath: '/assets/characters/hero_gmail.glb',
    lobbyAnimLabel: 'Tactical Sweep',
    lobbyWeaponId: 'vanguard_m4',
    ultimate: {
      name: 'Reply-All Barrage',
      subtitle: 'Homing Priority Volley',
      description:
        'Launches 6 homing explosive priority projectiles in an arcing volley targeting up to 3 nearby enemies (34 splash dmg each, 5m blast radius).',
      manaCost: 100,
      cooldown: 16,
    },
  },
  {
    id: 'drive',
    personaName: 'Drive AI',
    productName: 'Google Drive',
    displayName: 'Drive AI',
    name: 'Google Drive AI',
    shortBadge: '▲',
    role: 'Autonomous Cloud Security AI',
    tagline: 'Embodied 3D Google Drive icon AI that revokes enemy permissions and fortifies ground.',
    primaryColor: '#34a853',
    accentColor: '#fbbc04',
    hexPrimary: 0x34a853,
    hexAccent: 0xfbbc04,
    assetPath: '/assets/characters/hero_drive.glb',
    lobbyAnimLabel: 'Warden Guard',
    lobbyWeaponId: 'breaker_12g',
    ultimate: {
      name: 'Access Revoked',
      subtitle: 'Permission Guardrail Dome',
      description:
        'Deploys a 12m Restricted Access Guardrail Dome for 6s: blocks enemy projectiles, knocks unauthorized foes within 16m outward for 22 dmg, silences Ultimates & consumable channels for 3.0s, and grants +40 Shield.',
      manaCost: 100,
      cooldown: 18,
    },
  },
  {
    id: 'calendar',
    personaName: 'Calendar AI',
    productName: 'Google Calendar',
    displayName: 'Calendar AI',
    name: 'Google Calendar AI',
    shortBadge: '31',
    role: 'Autonomous Chrono-Tempo AI',
    tagline: 'Embodied 3D Google Calendar icon AI that bends time blocks across the Googleplex.',
    primaryColor: '#4285f4',
    accentColor: '#ffffff',
    hexPrimary: 0x4285f4,
    hexAccent: 0xffffff,
    assetPath: '/assets/characters/hero_calendar.glb',
    lobbyAnimLabel: 'Chrono Check',
    lobbyWeaponId: null,
    ultimate: {
      name: 'Hard Stop',
      subtitle: 'Time Block Chrono-Field',
      description:
        'Projects a 20m chrono-field for 6s that slows enemy movement (-65%) and fire rate (-55%) inside while granting you +40% move speed and +45% fire rate.',
      manaCost: 100,
      cooldown: 17,
    },
  },
  {
    id: 'chat',
    personaName: 'Chat AI',
    productName: 'Google Chat',
    displayName: 'Chat AI',
    name: 'Google Chat AI',
    shortBadge: '💬',
    role: 'Autonomous Comms Recon AI',
    tagline: 'Embodied 3D Google Chat icon AI that disrupts enemy Mana and exposes every rival.',
    primaryColor: '#00ac47',
    accentColor: '#a7f3d0',
    hexPrimary: 0x00ac47,
    hexAccent: 0xa7f3d0,
    assetPath: '/assets/characters/hero_chat.glb',
    lobbyAnimLabel: 'Recon Peek',
    lobbyWeaponId: 'vector_9',
    ultimate: {
      name: '@all Ping Overload',
      subtitle: 'Disruptor Recon Shockwave',
      description:
        'Emits an expanding 28m emerald shockwave dealing 45 instant damage, draining 35 enemy Mana, and revealing all living opponents through cover and on the minimap for 8s.',
      manaCost: 100,
      cooldown: 15,
    },
  },
  {
    id: 'slides',
    personaName: 'Slides AI',
    productName: 'Google Slides',
    displayName: 'Slides AI',
    name: 'Google Slides AI',
    shortBadge: '▣',
    role: 'Autonomous Spotlight Precision AI',
    tagline: 'Embodied 3D Google Slides icon AI armed with a devastating orbital projection beam.',
    primaryColor: '#fbbc04',
    accentColor: '#fff7ed',
    hexPrimary: 0xfbbc04,
    hexAccent: 0xfff7ed,
    assetPath: '/assets/characters/hero_slides.glb',
    lobbyAnimLabel: 'Spotlight Sightline',
    lobbyWeaponId: 'longbow_308',
    ultimate: {
      name: 'Executive Spotlight',
      subtitle: 'Orbital Projection Beam',
      description:
        'After a crisp 0.3s charge, fires a piercing golden orbital projection beam (85m range, 2.4m width) down your crosshair dealing 85 damage + heavy knockback to every rival in line.',
      manaCost: 100,
      cooldown: 16,
    },
  },
  {
    id: 'docs',
    personaName: 'Docs AI',
    productName: 'Google Docs',
    displayName: 'Docs AI',
    name: 'Google Docs AI',
    shortBadge: '≡',
    role: 'Autonomous Version-Control Skirmisher AI',
    tagline: 'Embodied 3D Google Docs icon AI that rewinds bad trades back to peak condition.',
    primaryColor: '#2563eb',
    accentColor: '#dbeafe',
    hexPrimary: 0x2563eb,
    hexAccent: 0xdbeafe,
    assetPath: '/assets/characters/hero_docs.glb',
    lobbyAnimLabel: 'Version Hover',
    lobbyWeaponId: 'nova_gl40',
    ultimate: {
      name: 'Version History',
      subtitle: '4s Rollback & Redline Pulse',
      description:
        'Rewinds smoothly (0.45s) back to your 4.0s-ago position, restoring max(current, saved) Health & Shield, cleansing slows, auto-reloading your weapon, and emitting a 12m Redline Pulse (35 dmg) at departure.',
      manaCost: 100,
      cooldown: 17,
    },
  },
];

export const HERO_MAP: Record<ProductHeroId, ProductHeroDef> = Object.fromEntries(
  PRODUCT_HEROES.map((h) => [h.id, h])
) as Record<ProductHeroId, ProductHeroDef>;

export const WEAPONS: Record<WeaponId, WeaponDef> = {
  vanguard_m4: {
    id: 'vanguard_m4',
    name: 'Vanguard M4',
    shortName: 'Vanguard M4',
    weaponClass: 'Assault Rifle',
    skinName: 'Arctic Apex',
    skinPaletteCss: '#60a5fa',
    icon: 'AR',
    category: 'weapon',
    damage: 20,
    headshotMult: 1.75,
    fireRate: 6.4,
    magSize: 30,
    reloadTime: 1.8,
    range: 125,
    pellets: 1,
    spread: 0.016,
    adsSpreadMult: 0.42,
    projectileSpeed: 165,
    automatic: true,
    color: 0x60a5fa,
    assetPath: '/assets/weapons/weapon_vanguard_m4.glb',
  },
  breaker_12g: {
    id: 'breaker_12g',
    name: 'Breaker 12G',
    shortName: 'Breaker 12G',
    weaponClass: 'Tactical Shotgun',
    skinName: 'Hazard Forge',
    skinPaletteCss: '#f97316',
    icon: 'SG',
    category: 'weapon',
    damage: 12,
    headshotMult: 1.6,
    fireRate: 1.2,
    magSize: 6,
    reloadTime: 2.1,
    range: 38,
    pellets: 8,
    spread: 0.068,
    adsSpreadMult: 0.72,
    projectileSpeed: 125,
    automatic: false,
    color: 0xf97316,
    assetPath: '/assets/weapons/weapon_breaker_12g.glb',
  },
  vector_9: {
    id: 'vector_9',
    name: 'Vector-9',
    shortName: 'Vector-9',
    weaponClass: 'SMG / PDW',
    skinName: 'Cyber Pulse',
    skinPaletteCss: '#22d3ee',
    icon: 'SMG',
    category: 'weapon',
    damage: 13,
    headshotMult: 1.75,
    fireRate: 11.0,
    magSize: 36,
    reloadTime: 1.45,
    range: 70,
    pellets: 1,
    spread: 0.028,
    adsSpreadMult: 0.48,
    projectileSpeed: 145,
    automatic: true,
    color: 0x38bdf8,
    assetPath: '/assets/weapons/weapon_vector_9.glb',
  },
  longbow_308: {
    id: 'longbow_308',
    name: 'Longbow .308',
    shortName: 'Longbow .308',
    weaponClass: 'Marksman Sniper',
    skinName: 'Shoreline Viper',
    skinPaletteCss: '#d4af37',
    icon: 'SR',
    category: 'weapon',
    damage: 68,
    headshotMult: 2.0,
    fireRate: 0.75,
    magSize: 5,
    reloadTime: 2.4,
    range: 220,
    pellets: 1,
    spread: 0.002,
    adsSpreadMult: 0.12,
    projectileSpeed: 265,
    automatic: false,
    hasScope: true,
    color: 0xfef08a,
    assetPath: '/assets/weapons/weapon_longbow_308.glb',
  },
  nova_gl40: {
    id: 'nova_gl40',
    name: 'Nova GL-40',
    shortName: 'Nova GL-40',
    weaponClass: 'Ordnance Launcher',
    skinName: 'Hypernova Prism',
    skinPaletteCss: '#c084fc',
    icon: 'GL',
    category: 'weapon',
    damage: 56,
    headshotMult: 1.0,
    fireRate: 0.85,
    magSize: 4,
    reloadTime: 2.5,
    range: 95,
    pellets: 1,
    spread: 0.012,
    adsSpreadMult: 0.6,
    projectileSpeed: 60,
    automatic: false,
    splashRadius: 6.5,
    gravityScale: 0.65,
    coverDamageMult: 2.4,
    manaPerShot: 8,
    color: 0xc084fc,
    assetPath: '/assets/weapons/weapon_nova_gl40.glb',
  },
};

export const WEAPON_LIST: WeaponDef[] = Object.values(WEAPONS);

export const UTILITY_ITEMS: Record<UtilityItemId, UtilityItemDef> = {
  shield_cell: {
    id: 'shield_cell',
    name: 'Shield Cell',
    shortName: 'Shield Cell',
    utilityCategory: 'shield',
    icon: 'SC',
    category: 'item',
    description: 'Fast mid-fight Shield energy top-up (1.5s channel).',
    baseAmount: 25,
    amountsByRarity: { common: 25, rare: 32, epic: 40 },
    channelTime: 1.5,
    maxStack: 4,
    color: 0x38bdf8,
    assetPath: '/assets/utilities/item_shield_cell.glb',
  },
  shield_jug: {
    id: 'shield_jug',
    name: 'Aegis Shield Jug',
    shortName: 'Shield Jug',
    utilityCategory: 'shield',
    icon: 'SJ',
    category: 'item',
    description: 'Full Shield reset behind cover (3.0s channel).',
    baseAmount: 60,
    amountsByRarity: { common: 60, rare: 75, epic: 100 },
    channelTime: 3.0,
    maxStack: 2,
    color: 0x06b6d4,
    assetPath: '/assets/utilities/item_shield_jug.glb',
  },
  medkit: {
    id: 'medkit',
    name: 'Field Medkit',
    shortName: 'Medkit',
    utilityCategory: 'health',
    icon: 'MK',
    category: 'item',
    description: 'Primary Health recovery trauma kit (2.8s channel).',
    baseAmount: 45,
    amountsByRarity: { common: 45, rare: 65, epic: 100 },
    channelTime: 2.8,
    maxStack: 3,
    color: 0x22c55e,
    assetPath: '/assets/utilities/item_medkit.glb',
  },
  mana_elixir: {
    id: 'mana_elixir',
    name: 'Mana Elixir',
    shortName: 'Mana Elixir',
    utilityCategory: 'mana',
    icon: 'ME',
    category: 'item',
    description: 'Accelerates Ultimate readiness (1.4s channel).',
    baseAmount: 45,
    amountsByRarity: { common: 45, rare: 65, epic: 100 },
    channelTime: 1.4,
    maxStack: 3,
    color: 0xa855f7,
    assetPath: '/assets/utilities/item_mana_elixir.glb',
  },
  hardlight_cover: {
    id: 'hardlight_cover',
    name: 'Hard-Light Cover',
    shortName: 'HL Cover',
    utilityCategory: 'tactical',
    icon: 'HC',
    category: 'item',
    description: 'Deploys a curved ballistic energy barrier anywhere (12 Mana, instant).',
    baseAmount: 240,
    amountsByRarity: { common: 240, rare: 300, epic: 380 },
    channelTime: 0,
    maxStack: 3,
    manaCost: 12,
    color: 0x60a5fa,
    assetPath: '/assets/utilities/item_hardlight_cover.glb',
  },
  impulse_booster: {
    id: 'impulse_booster',
    name: 'Impulse Booster',
    shortName: 'Impulse',
    utilityCategory: 'mobility',
    icon: 'IB',
    category: 'item',
    description: 'Directional high-arc vertical/forward launch to scale roofs or disengage (10 Mana, instant).',
    baseAmount: 22,
    amountsByRarity: { common: 22, rare: 26, epic: 30 },
    channelTime: 0,
    maxStack: 3,
    manaCost: 10,
    color: 0xfacc15,
    assetPath: '/assets/utilities/item_impulse_booster.glb',
  },
};

export const UTILITY_LIST: UtilityItemDef[] = Object.values(UTILITY_ITEMS);

export const STORM_PHASES: StormPhaseDef[] = [
  { phase: 1, waitDuration: 42, shrinkDuration: 44, targetRadius: 245, dps: 2 },
  { phase: 2, waitDuration: 36, shrinkDuration: 38, targetRadius: 155, dps: 4 },
  { phase: 3, waitDuration: 30, shrinkDuration: 34, targetRadius: 88, dps: 7 },
  { phase: 4, waitDuration: 24, shrinkDuration: 30, targetRadius: 42, dps: 10 },
  { phase: 5, waitDuration: 20, shrinkDuration: 26, targetRadius: 14, dps: 15 },
];

export const DEFAULT_GAME_SETTINGS: GameSettings = {
  botDifficulty: 'tactical',
  qualityPreset: 'balanced',
  showPerfHud: true,
  masterVolume: 1.0,
  muted: false,
  mouseSensitivity: 1.0,
  adsSensitivity: 1.0,
  invertY: false,
  visualSoundCompass: true,
};

export const GAME_MODES: Record<GameModeId, GameModeDef> = {
  battle_royale: {
    id: 'battle_royale',
    name: 'Battle Royale',
    badge: 'CLASSIC 20',
    tagline: 'The signature Mountain View Googleplex survival showdown.',
    description:
      'Drop unarmed from 135m across the full 3× Mountain View Googleplex, loot Tier 1–3 chests and 3 aerial Supply Drops, and outlast 19 AI opponents across 5 closing storm phases.',
    accentCss: '#4285f4',
    totalCombatants: 20,
    startMana: 40,
    manaRegenMult: 1.0,
    moveSpeedMult: 1.0,
    stormEnabled: true,
    stormPaceMult: 1.0,
    initialStormRadius: 365,
    highlights: ['20 Characters', 'Standard 5-Phase Storm', 'Tier 1–3 Loot Chests', '3 Supply Drops'],
  },
  blitz: {
    id: 'blitz',
    name: 'Blitz Royale',
    badge: 'FAST PACED',
    tagline: 'Turbocharged storm cycles, upgraded loot chests, and hyper Mana regen.',
    description:
      'High-tempo survival inside a tighter starting perimeter with 1.8× faster storm collapses, boosted ground movement (+12%), upgraded Tier 2–3 chests everywhere, and supercharged Mana for relentless Ultimates.',
    accentCss: '#f97316',
    totalCombatants: 16,
    startMana: 60,
    manaRegenMult: 1.65,
    moveSpeedMult: 1.12,
    stormEnabled: true,
    stormPaceMult: 0.55,
    initialStormRadius: 270,
    minChestTier: 2,
    highlights: ['16 Characters', '1.8× Faster Storm', 'Tier 2–3 Upgraded Chests', '+65% Mana Regen'],
  },
  sniper_showdown: {
    id: 'sniper_showdown',
    name: 'Sniper Showdown',
    badge: 'LONGBOW ONLY',
    tagline: 'Long-range rooftop duels with Shoreline Viper Longbow .308 sniper rifles.',
    description:
      'Every loot chest and Supply Drop arms combatants exclusively with Longbow .308 marksman rifles alongside Impulse Boosters, Hard-Light Cover, and high-grade Shields for lethal 2.0× headshot duels.',
    accentCss: '#d4af37',
    totalCombatants: 16,
    startMana: 50,
    manaRegenMult: 1.15,
    moveSpeedMult: 1.04,
    stormEnabled: true,
    stormPaceMult: 0.82,
    initialStormRadius: 330,
    forceWeaponId: 'longbow_308',
    highlights: ['Longbow .308 Exclusive', '16 Characters', 'Impulse & Shield Loot', '2.0× Headshot Crits'],
  },
  campus_practice: {
    id: 'campus_practice',
    name: 'Campus Free Roam',
    badge: 'NO STORM',
    tagline: 'Explore the 3× Mountain View Googleplex with no storm pressure and light sparring bots.',
    description:
      'Tour every Mountain View landmark, rooftop, and office floor with zero storm pressure, full 100 starting Mana, 2.2× Mana regen, upgraded Tier 2–3 loot chests, and 6 Intern sparring bots.',
    accentCss: '#34a853',
    totalCombatants: 7,
    startMana: 100,
    manaRegenMult: 2.2,
    moveSpeedMult: 1.08,
    stormEnabled: false,
    stormPaceMult: 1.0,
    initialStormRadius: 420,
    minChestTier: 2,
    forceBotDifficulty: 'casual',
    highlights: ['No Storm Closing', '6 Intern Sparring Bots', '100 Start Mana · 2.2× Regen', 'All 5 Skinned Weapons'],
  },
};

export const GAME_MODE_LIST: GameModeDef[] = [
  GAME_MODES.battle_royale,
  GAME_MODES.blitz,
  GAME_MODES.sniper_showdown,
  GAME_MODES.campus_practice,
];

export function createStarterLoadout(): (InventorySlot | null)[] {
  // Both players and all 19 AI bots drop in completely unarmed and must open Loot Chests
  return [null, null, null, null, null];
}

export function getWeaponDamage(weaponId: WeaponId, rarity: Rarity): number {
  return Math.round(WEAPONS[weaponId].damage * RARITY_CONFIG[rarity].mult);
}

export function getWeaponReloadTime(weaponId: WeaponId, rarity: Rarity): number {
  return Number((WEAPONS[weaponId].reloadTime * RARITY_CONFIG[rarity].reloadMult).toFixed(2));
}

export function getUtilityAmount(utilityId: UtilityItemId, rarity: Rarity): number {
  return UTILITY_ITEMS[utilityId].amountsByRarity[rarity];
}

export function rollRarity(highTier = false): Rarity {
  const r = Math.random() * 100;
  if (highTier) {
    if (r < RARITY_CONFIG.epic.highTierWeight) return 'epic';
    if (r < RARITY_CONFIG.epic.highTierWeight + RARITY_CONFIG.rare.highTierWeight) return 'rare';
    return 'common';
  }
  if (r < RARITY_CONFIG.epic.standardWeight) return 'epic';
  if (r < RARITY_CONFIG.epic.standardWeight + RARITY_CONFIG.rare.standardWeight) return 'rare';
  return 'common';
}

export function rollChestTier(highTier = false): ChestTier {
  const r = Math.random();
  if (highTier) {
    // High-tier spots: ~55% Tier 2 Rare Tech Chest, ~45% Tier 3 Epic Vault Chest
    return r < 0.55 ? 2 : 3;
  }
  // Standard spots: ~50% Tier 1 Common Supply, ~35% Tier 2 Rare Tech, ~15% Tier 3 Epic Vault
  if (r < 0.50) return 1;
  if (r < 0.85) return 2;
  return 3;
}

function rollChestRarity(tier: ChestTier): Rarity {
  const r = Math.random();
  if (tier === 1) {
    // Common 75% / Rare 22% / Epic 3%
    if (r < 0.75) return 'common';
    if (r < 0.97) return 'rare';
    return 'epic';
  }
  if (tier === 2) {
    // Common 25% / Rare 58% / Epic 17%
    if (r < 0.25) return 'common';
    if (r < 0.83) return 'rare';
    return 'epic';
  }
  // Tier 3: Rare 40% / Epic 60%
  return r < 0.40 ? 'rare' : 'epic';
}

function rollWeaponForTier(tier: ChestTier, excludeId?: WeaponId): WeaponId {
  const pool: [WeaponId, number][] =
    tier === 1
      ? [
          ['vanguard_m4', 32],
          ['breaker_12g', 26],
          ['vector_9', 26],
          ['longbow_308', 11],
          ['nova_gl40', 5],
        ]
      : tier === 2
        ? [
            ['vanguard_m4', 26],
            ['breaker_12g', 22],
            ['vector_9', 22],
            ['longbow_308', 18],
            ['nova_gl40', 12],
          ]
        : [
            ['vanguard_m4', 22],
            ['breaker_12g', 18],
            ['vector_9', 20],
            ['longbow_308', 22],
            ['nova_gl40', 18],
          ];

  const filtered = excludeId ? pool.filter(([id]) => id !== excludeId) : pool;
  const total = filtered.reduce((sum, [, w]) => sum + w, 0);
  let r = Math.random() * total;
  for (const [id, w] of filtered) {
    r -= w;
    if (r <= 0) return id;
  }
  return filtered[0][0];
}

function rollShieldItem(tier: ChestTier): UtilityItemId {
  const jugChance = tier === 3 ? 0.62 : tier === 2 ? 0.38 : 0.16;
  return Math.random() < jugChance ? 'shield_jug' : 'shield_cell';
}

function rollSupportUtility(tier: ChestTier, excludeShield = false): UtilityItemId {
  if (excludeShield) {
    const r = Math.random();
    if (r < (tier === 3 ? 0.40 : 0.32)) return 'mana_elixir';
    if (r < 0.64) return 'medkit';
    if (r < 0.83) return 'hardlight_cover';
    return 'impulse_booster';
  }
  const r = Math.random();
  if (r < 0.30) return 'shield_cell';
  if (r < 0.44) return 'shield_jug';
  if (r < 0.62) return 'medkit';
  if (r < 0.77) return 'mana_elixir';
  if (r < 0.90) return 'hardlight_cover';
  return 'impulse_booster';
}

function rollSniperSupportUtility(tier: ChestTier, excludeShield = false): UtilityItemId {
  const r = Math.random();
  if (excludeShield) {
    if (r < 0.36) return 'impulse_booster';
    if (r < 0.64) return 'hardlight_cover';
    if (r < 0.90) return 'medkit';
    return 'mana_elixir';
  }
  const jugCut = tier === 3 ? 0.64 : tier === 2 ? 0.60 : 0.56;
  if (r < 0.26) return 'impulse_booster';
  if (r < 0.44) return 'shield_cell';
  if (r < jugCut) return 'shield_jug';
  if (r < 0.80) return 'medkit';
  return 'hardlight_cover';
}

export interface ChestDropRoll {
  kind: 'weapon' | 'item';
  id: WeaponId | UtilityItemId;
  rarity: Rarity;
  count: number;
}

export function rollSupplyDropWeapon(modeId: GameModeId = 'battle_royale'): WeaponId {
  const mode = GAME_MODES[modeId] ?? GAME_MODES.battle_royale;
  if (mode.forceWeaponId) return mode.forceWeaponId;
  const epicWeapons: WeaponId[] = ['vanguard_m4', 'breaker_12g', 'vector_9', 'longbow_308', 'nova_gl40'];
  return epicWeapons[Math.floor(Math.random() * epicWeapons.length)];
}

export function rollChestLoot(tier: ChestTier, modeId: GameModeId = 'battle_royale'): ChestDropRoll[] {
  const mode = GAME_MODES[modeId] ?? GAME_MODES.battle_royale;
  const effectiveTier = (mode.minChestTier ? Math.max(tier, mode.minChestTier) : tier) as ChestTier;
  const isForcedWeapon = Boolean(mode.forceWeaponId);
  const pickWeapon = (t: ChestTier, excludeId?: WeaponId): WeaponId =>
    mode.forceWeaponId ?? rollWeaponForTier(t, excludeId);
  const pickUtility = (t: ChestTier, excludeShield = false): UtilityItemId =>
    isForcedWeapon ? rollSniperSupportUtility(t, excludeShield) : rollSupportUtility(t, excludeShield);

  const drops: ChestDropRoll[] = [];
  const itemCountFor = (id: UtilityItemId): number => (id === 'shield_cell' ? 2 : 1);

  if (effectiveTier === 1) {
    // Tier 1: 1–2 items (1 item ~45%, 2 items ~55%), guaranteed >= 1 Weapon
    const count = Math.random() < 0.45 ? 1 : 2;
    const weaponId = pickWeapon(1);
    drops.push({ kind: 'weapon', id: weaponId, rarity: rollChestRarity(1), count: 1 });
    if (count >= 2) {
      const utilId = pickUtility(1, false);
      drops.push({
        kind: 'item',
        id: utilId,
        rarity: rollChestRarity(1),
        count: itemCountFor(utilId),
      });
    }
    return drops;
  }

  if (effectiveTier === 2) {
    // Tier 2: 2–3 items (2 items ~60%, 3 items ~40%), guaranteed >= 1 Weapon + 1 Shield/Utility
    const count = Math.random() < 0.60 ? 2 : 3;
    const weaponId = pickWeapon(2);
    drops.push({ kind: 'weapon', id: weaponId, rarity: rollChestRarity(2), count: 1 });
    const secondId = Math.random() < 0.62 ? rollShieldItem(2) : pickUtility(2, true);
    drops.push({
      kind: 'item',
      id: secondId,
      rarity: rollChestRarity(2),
      count: itemCountFor(secondId),
    });
    if (count >= 3) {
      if (!isForcedWeapon && Math.random() < 0.35) {
        const extraWeapon = pickWeapon(2, weaponId);
        drops.push({ kind: 'weapon', id: extraWeapon, rarity: rollChestRarity(2), count: 1 });
      } else {
        const extraUtil = pickUtility(2, secondId === 'shield_cell' || secondId === 'shield_jug');
        drops.push({
          kind: 'item',
          id: extraUtil,
          rarity: rollChestRarity(2),
          count: itemCountFor(extraUtil),
        });
      }
    }
    return drops;
  }

  // Tier 3 (Epic Vault Chest): Always 3 items — guaranteed Rare/Epic Weapon + Shield + Utility/Mobility
  const weaponId = pickWeapon(3);
  const shieldId = rollShieldItem(3);
  const utilityId = pickUtility(3, true);
  drops.push({ kind: 'weapon', id: weaponId, rarity: rollChestRarity(3), count: 1 });
  drops.push({
    kind: 'item',
    id: shieldId,
    rarity: rollChestRarity(3),
    count: itemCountFor(shieldId),
  });
  drops.push({
    kind: 'item',
    id: utilityId,
    rarity: rollChestRarity(3),
    count: itemCountFor(utilityId),
  });
  return drops;
}

export function rollRandomLoot(highTier = false, modeId: GameModeId = 'battle_royale'): {
  kind: 'weapon' | 'item';
  id: WeaponId | UtilityItemId;
  rarity: Rarity;
} {
  const mode = GAME_MODES[modeId] ?? GAME_MODES.battle_royale;
  const rarity = rollRarity(highTier);
  const isWeapon = Math.random() < (highTier ? 0.56 : 0.48);
  if (isWeapon) {
    if (mode.forceWeaponId) {
      return { kind: 'weapon', id: mode.forceWeaponId, rarity };
    }
    const weaponRoll = Math.random();
    let id: WeaponId = 'vanguard_m4';
    if (weaponRoll < 0.28) id = 'vanguard_m4';
    else if (weaponRoll < 0.50) id = 'breaker_12g';
    else if (weaponRoll < 0.72) id = 'vector_9';
    else if (weaponRoll < 0.88) id = 'longbow_308';
    else id = 'nova_gl40';
    return { kind: 'weapon', id, rarity };
  }

  if (mode.forceWeaponId) {
    return { kind: 'item', id: rollSniperSupportUtility(highTier ? 3 : 2, false), rarity };
  }

  const itemRoll = Math.random();
  let id: UtilityItemId = 'shield_cell';
  if (itemRoll < 0.25) id = 'shield_cell';
  else if (itemRoll < 0.40) id = 'shield_jug';
  else if (itemRoll < 0.58) id = 'medkit';
  else if (itemRoll < 0.75) id = 'mana_elixir';
  else if (itemRoll < 0.89) id = 'hardlight_cover';
  else id = 'impulse_booster';
  return { kind: 'item', id, rarity };
}

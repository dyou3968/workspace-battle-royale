import * as THREE from 'three';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import './style.css';
import {
  alignWeaponTwoHanded,
  AssetManager,
  HeroInstance,
  WeaponInstance,
  sharedAssetManager,
} from './core/assetManager';
import { BOT_DIFFICULTY_OPTIONS, BOT_PROFILES } from './data/botProfiles';
import {
  DEFAULT_GAME_SETTINGS,
  GAME_CONSTANTS,
  GAME_MODES,
  GAME_MODE_LIST,
  HERO_MAP,
  PRODUCT_HEROES,
  RARITY_CONFIG,
  UTILITY_ITEMS,
  WEAPONS,
} from './data/catalog';
import { HudCallbacks, WorkspaceRoyaleEngine } from './gameplay/engine';
import { TacticalMinimap } from './ui/minimap';
import {
  BotDifficulty,
  DirectionalDamageEvent,
  FloatingDamageEvent,
  GameModeId,
  GameSettings,
  HudSnapshot,
  KillFeedEntry,
  LoadingProgress,
  MatchSummary,
  MinimapState,
  ProductHeroId,
  QualityPreset,
  UtilityItemId,
  WeaponId,
} from './types';

type MenuPage = 'home' | 'modes' | 'characters' | 'settings';
type SettingsTab = 'gameplay' | 'video' | 'audio' | 'controls';

const SETTINGS_STORAGE_KEY = 'workspace_royale_settings_v1';

// ==================== AUTHENTIC MULTI-COLOR GOOGLE WORKSPACE PRODUCT SVGs ====================
const HERO_PRODUCT_SVGS: Record<ProductHeroId, string> = {
  gmail: `<svg viewBox="0 0 32 32" fill="none" aria-hidden="true">
    <path d="M4 10.4V24a2 2 0 0 0 2 2h4.5V15.1L4 10.4Z" fill="#4285F4"/>
    <path d="M28 10.4V24a2 2 0 0 1-2 2h-4.5V15.1L28 10.4Z" fill="#34A853"/>
    <path d="M21.5 8.7l3.7-2.7A1.8 1.8 0 0 1 28 7.5v3l-6.5 4.7V8.7Z" fill="#FBBC04"/>
    <path d="M4 7.5A1.8 1.8 0 0 1 6.8 6l3.7 2.7v6.5L4 10.5v-3Z" fill="#C5221F"/>
    <path d="M10.5 8.7L16 12.8l5.5-4.1v6.5L16 19.3l-5.5-4.1V8.7Z" fill="#EA4335"/>
  </svg>`,
  drive: `<svg viewBox="0 0 32 32" fill="none" aria-hidden="true">
    <path d="M11.8 5L3.5 20.5h7.9L16 12.2 11.8 5Z" fill="#00AC47"/>
    <path d="M11.8 5h8.4L16 12.2 11.8 5Z" fill="#00832D"/>
    <path d="M20.2 5L28.5 20.5h-7.9L16 12.2 20.2 5Z" fill="#FFBA00"/>
    <path d="M28.5 20.5l-3.7 6-4.2-6h7.9Z" fill="#EA4335"/>
    <path d="M11.4 20.5h9.2l4.2 6H7.2l4.2-6Z" fill="#2684FC"/>
    <path d="M3.5 20.5h7.9l-4.2 6-3.7-6Z" fill="#0066DA"/>
  </svg>`,
  calendar: `<svg viewBox="0 0 32 32" fill="none" aria-hidden="true">
    <rect x="8.5" y="8.5" width="15" height="15" fill="#FFFFFF"/>
    <path d="M8.5 4h15v4.5h-15V4Z" fill="#4285F4"/>
    <path d="M4 8.5h4.5v15H4v-15Z" fill="#4285F4"/>
    <path d="M4 8.5V6a2 2 0 0 1 2-2h2.5v4.5H4Z" fill="#1967D2"/>
    <path d="M23.5 4H26a2 2 0 0 1 2 2v2.5h-4.5V4Z" fill="#1967D2"/>
    <path d="M4 23.5h4.5V28H6a2 2 0 0 1-2-2v-2.5Z" fill="#1967D2"/>
    <path d="M23.5 8.5H28v15h-4.5v-15Z" fill="#34A853"/>
    <path d="M8.5 23.5h15V28h-15v-4.5Z" fill="#FBBC04"/>
    <path d="M23.5 23.5H28L23.5 28v-4.5Z" fill="#EA4335"/>
    <text x="16" y="20.1" text-anchor="middle" fill="#1A73E8" font-family="Google Sans, Roboto, Arial, sans-serif" font-size="11.5" font-weight="700">31</text>
  </svg>`,
  chat: `<svg viewBox="0 0 32 32" fill="none" aria-hidden="true">
    <path d="M11.5 11.5H25a2.5 2.5 0 0 1 2.5 2.5v8.5A2.5 2.5 0 0 1 25 25h-9.2l-3.8 3.2V25h-.5A2.5 2.5 0 0 1 9 22.5V14a2.5 2.5 0 0 1 2.5-2.5Z" fill="#00832D"/>
    <path d="M7 5.5h13.5A2.5 2.5 0 0 1 23 8v8.5a2.5 2.5 0 0 1-2.5 2.5H10.5L6 22.6V19a2.5 2.5 0 0 1-1.5-2.3V8A2.5 2.5 0 0 1 7 5.5Z" fill="#00AC47"/>
    <path d="M9 11.5h11.5A2.5 2.5 0 0 1 23 14v2.5a2.5 2.5 0 0 1-2.5 2.5H9v-7.5Z" fill="#5BB974" fill-opacity="0.45"/>
    <rect x="8.5" y="10.2" width="10.2" height="2" rx="1" fill="#FFFFFF"/>
    <rect x="8.5" y="13.8" width="6.8" height="2" rx="1" fill="#FFFFFF"/>
  </svg>`,
  slides: `<svg viewBox="0 0 32 32" fill="none" aria-hidden="true">
    <path d="M8 3.5h11.5L26 10v16.5a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2v-21a2 2 0 0 1 2-2Z" fill="#FBBC04"/>
    <path d="M19.5 3.5V8a2 2 0 0 0 2 2H26l-6.5-6.5Z" fill="#F29900"/>
    <rect x="9.5" y="13.5" width="13" height="9" rx="1.2" fill="none" stroke="#FFFFFF" stroke-width="2"/>
  </svg>`,
  docs: `<svg viewBox="0 0 32 32" fill="none" aria-hidden="true">
    <path d="M8 3.5h11.5L26 10v16.5a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2v-21a2 2 0 0 1 2-2Z" fill="#4285F4"/>
    <path d="M19.5 3.5V8a2 2 0 0 0 2 2H26l-6.5-6.5Z" fill="#1967D2"/>
    <rect x="9.5" y="14" width="13" height="1.9" rx="0.95" fill="#FFFFFF"/>
    <rect x="9.5" y="17.8" width="13" height="1.9" rx="0.95" fill="#FFFFFF"/>
    <rect x="9.5" y="21.6" width="8.5" height="1.9" rx="0.95" fill="#FFFFFF"/>
  </svg>`,
};

// ==================== DOM REFERENCES ====================
const gameViewport = document.getElementById('game-viewport') as HTMLElement;
const minimapCanvas = document.getElementById('minimap-canvas') as HTMLCanvasElement;
const compassCanvas = document.getElementById('compass-canvas') as HTMLCanvasElement;
const compassDegEl = document.getElementById('compass-deg')!;
const previewStage = document.getElementById('preview-stage')!;
const previewCanvas = document.getElementById('hero-preview-canvas') as HTMLCanvasElement;
const previewLoadingPill = document.getElementById('preview-loading-pill')!;

// Live 3D Splash Screen DOM
const splashOverlay = document.getElementById('splash-overlay')!;
const splashPreloadVeil = document.getElementById('splash-preload-veil')!;
const splashPreloadProgressbar = document.getElementById('splash-preload-progressbar')!;
const splashPreloadFill = document.getElementById('splash-preload-fill')!;
const splashPreloadCaption = document.getElementById('splash-preload-caption')!;
const splashPreloadPct = document.getElementById('splash-preload-pct')!;
const splashAssetBadge = document.getElementById('splash-asset-badge')!;
const btnSplashMute = document.getElementById('btn-splash-mute') as HTMLButtonElement;
const splashSceneBars = document.getElementById('splash-scene-bars')!;
const btnSplashStart = document.getElementById('btn-splash-start') as HTMLButtonElement;
const btnSplashQuickplay = document.getElementById('btn-splash-quickplay') as HTMLButtonElement;

const lobbyOverlay = document.getElementById('lobby-overlay')!;
const hudEl = document.getElementById('hud')!;
const fullmapOverlay = document.getElementById('fullmap-overlay')!;
const fullmapCanvas = document.getElementById('fullmap-canvas') as HTMLCanvasElement;
const fullmapZoneEl = document.getElementById('fullmap-zone')!;
const fullmapStormEl = document.getElementById('fullmap-storm')!;
const fullmapWaypointPill = document.getElementById('fullmap-waypoint-pill')!;
const fullmapWaypointDist = document.getElementById('fullmap-waypoint-dist')!;
const btnClearWaypoint = document.getElementById('btn-clear-waypoint') as HTMLButtonElement;
const btnCloseFullmap = document.getElementById('btn-close-fullmap') as HTMLButtonElement;
const pauseOverlay = document.getElementById('pause-overlay')!;
const pauseMatchPill = document.getElementById('pause-match-pill')!;
const gameoverOverlay = document.getElementById('gameover-overlay')!;

// Multi-Page Menu Shell DOM
const navBrandHome = document.getElementById('nav-brand-home') as HTMLButtonElement;
const menuNavTabs = document.getElementById('menu-nav-tabs')!;
const menuPageViewport = document.querySelector('.menu-page-viewport') as HTMLElement;
const inmatchSettingsBanner = document.getElementById('inmatch-settings-banner')!;
const btnInmatchBack = document.getElementById('btn-inmatch-back') as HTMLButtonElement;
const btnTopbarSplash = document.getElementById('btn-topbar-splash') as HTMLButtonElement;
const btnTopbarSettings = document.getElementById('btn-topbar-settings') as HTMLButtonElement;
const assetStatusChip = document.getElementById('asset-status-chip')!;
const assetChipText = document.getElementById('asset-chip-text')!;
const chipMiniFill = document.getElementById('chip-mini-fill')!;
const assetPreloadBar = document.getElementById('asset-preload-bar')!;
const preloadLabel = document.getElementById('preload-label')!;
const preloadPct = document.getElementById('preload-pct')!;
const preloadFill = document.getElementById('preload-fill')!;

// Showcase Reparenting Slots
const homeShowcaseSlot = document.getElementById('home-showcase-slot')!;
const charactersShowcaseSlot = document.getElementById('characters-showcase-slot')!;

// Page 1: Home DOM
const btnHomePlay = document.getElementById('btn-home-play') as HTMLButtonElement;
const homeCardMode = document.getElementById('home-card-mode') as HTMLButtonElement;
const homeCardHero = document.getElementById('home-card-hero') as HTMLButtonElement;
const homeCardSettings = document.getElementById('home-card-settings') as HTMLButtonElement;
const homeBtnControls = document.getElementById('home-btn-controls') as HTMLButtonElement;
const homeModeAccent = document.getElementById('home-mode-accent')!;
const homeModeBadge = document.getElementById('home-mode-badge')!;
const homeModeName = document.getElementById('home-mode-name')!;
const homeModeTagline = document.getElementById('home-mode-tagline')!;
const homeHeroBadge = document.getElementById('home-hero-badge')!;
const homeHeroName = document.getElementById('home-hero-name')!;
const homeHeroMeta = document.getElementById('home-hero-meta')!;
const homeStripHeroName = document.getElementById('home-strip-hero-name')!;
const homeStripUltName = document.getElementById('home-strip-ult-name')!;
const btnHomeCustomize = document.getElementById('btn-home-customize') as HTMLButtonElement;

// Page 2: Play Modes DOM
const modesBody = document.getElementById('modes-body')!;
const modeGrid = document.getElementById('mode-grid')!;
const btnModesBack = document.getElementById('btn-modes-back') as HTMLButtonElement;
const btnModesPlay = document.getElementById('btn-modes-play') as HTMLButtonElement;

// Page 3: Characters DOM
const heroGrid = document.getElementById('hero-grid')!;
const detailHeroIcon = document.getElementById('detail-hero-icon')!;
const detailHeroName = document.getElementById('detail-hero-name')!;
const detailHeroTagline = document.getElementById('detail-hero-tagline')!;
const detailUltName = document.getElementById('detail-ult-name')!;
const detailUltDesc = document.getElementById('detail-ult-desc')!;
const detailUltCost = document.getElementById('detail-ult-cost')!;
const previewTag = document.getElementById('preview-tag')!;
const previewRole = document.getElementById('preview-role')!;
const previewShowcasePill = document.getElementById('preview-showcase-pill')!;
const btnFlipPreview = document.getElementById('btn-flip-preview') as HTMLButtonElement;
const btnCharsBack = document.getElementById('btn-chars-back') as HTMLButtonElement;
const btnCharsPlay = document.getElementById('btn-chars-play') as HTMLButtonElement;

// Page 4: Categorized Settings DOM
const settingsContent = document.getElementById('settings-content')!;
const difficultyGrid = document.getElementById('bot-difficulty-grid')!;
const difficultySummary = document.getElementById('bot-difficulty-summary')!;
const settingsPracticeNote = document.getElementById('settings-practice-note')!;
const settingsQualitySub = document.getElementById('settings-quality-sub')!;
const settingShowPerfHud = document.getElementById('setting-show-perf-hud') as HTMLInputElement;
const settingMouseSens = document.getElementById('setting-mouse-sens') as HTMLInputElement;
const valMouseSens = document.getElementById('val-mouse-sens')!;
const settingAdsSens = document.getElementById('setting-ads-sens') as HTMLInputElement;
const valAdsSens = document.getElementById('val-ads-sens')!;
const settingInvertY = document.getElementById('setting-invert-y') as HTMLInputElement;
const settingVolumeRow = document.getElementById('setting-volume-row')!;
const settingMasterVolume = document.getElementById('setting-master-volume') as HTMLInputElement;
const valMasterVolume = document.getElementById('val-master-volume')!;
const btnTestAudio = document.getElementById('btn-test-audio') as HTMLButtonElement;
const settingMuted = document.getElementById('setting-muted') as HTMLInputElement;
const btnSettingsReset = document.getElementById('btn-settings-reset') as HTMLButtonElement;
const settingsSavedNote = document.getElementById('settings-saved-note')!;
const btnSettingsDone = document.getElementById('btn-settings-done') as HTMLButtonElement;

// In-Game HUD DOM
const sniperScopeOverlay = document.getElementById('sniper-scope-overlay')!;
const stormVignette = document.getElementById('storm-vignette')!;
const lowHpVignette = document.getElementById('low-hp-vignette')!;
const zoneNameEl = document.getElementById('zone-name')!;
const stormPill = document.getElementById('storm-pill')!;
const stormPhaseBadge = document.getElementById('storm-phase-badge')!;
const stormStatus = document.getElementById('storm-status')!;
const perfPill = document.getElementById('perf-pill')!;
const perfFpsEl = document.getElementById('perf-fps')!;
const perfDrawsEl = document.getElementById('perf-draws')!;

const hudModeLabel = document.getElementById('hud-mode-label')!;
const hudAlive = document.getElementById('hud-alive')!;
const hudElims = document.getElementById('hud-elims')!;
const hudHeadshots = document.getElementById('hud-headshots')!;
const hudBotTier = document.getElementById('hud-bot-tier')!;
const skydropPrompt = document.getElementById('skydrop-prompt')!;
const skydropAlt = document.getElementById('skydrop-alt')!;
const skydropBar = document.getElementById('skydrop-bar')!;
const bannerToast = document.getElementById('banner-toast')!;
const killFeedEl = document.getElementById('kill-feed')!;

const damageArcLayer = document.getElementById('damage-arc-layer')!;
const crosshairEl = document.getElementById('crosshair')!;
const hitmarkerEl = document.getElementById('hitmarker')!;
const critFlashEl = document.getElementById('crit-flash')!;
const channelRing = document.getElementById('channel-ring')!;
const channelArc = document.getElementById('channel-arc') as unknown as SVGCircleElement;
const channelTime = document.getElementById('channel-time')!;
const channelLabel = document.getElementById('channel-label')!;
const interactPrompt = document.getElementById('interact-prompt')!;
const interactText = document.getElementById('interact-text')!;
const damageLayer = document.getElementById('damage-layer')!;

const statusBadgesEl = document.getElementById('status-badges')!;
const heroStatusCard = document.getElementById('hero-status-card')!;
const hudHeroAvatar = document.getElementById('hud-hero-avatar')!;
const hudHeroName = document.getElementById('hud-hero-name')!;
const hudUltPill = document.getElementById('hud-ult-pill')!;
const hudManaRow = document.getElementById('hud-mana-row')!;
const hudUltCallout = document.getElementById('hud-ult-callout')!;
const hudUltCalloutText = document.getElementById('hud-ult-callout-text')!;
const barShield = document.getElementById('bar-shield')!;
const barHealth = document.getElementById('bar-health')!;
const barMana = document.getElementById('bar-mana')!;
const numShield = document.getElementById('num-shield')!;
const numHealth = document.getElementById('num-health')!;
const numMana = document.getElementById('num-mana')!;

const activeItemName = document.getElementById('active-item-name')!;
const activeItemAmmo = document.getElementById('active-item-ammo')!;
const reloadBarWrap = document.getElementById('reload-bar-wrap')!;
const reloadBarFill = document.getElementById('reload-bar-fill')!;
const hotbarEl = document.getElementById('hotbar')!;

// ==================== SETTINGS PERSISTENCE ====================
function clampNum(val: number, min: number, max: number, fallback: number): number {
  if (typeof val !== 'number' || !Number.isFinite(val)) return fallback;
  return Math.max(min, Math.min(max, val));
}

function isBotDifficulty(v: unknown): v is BotDifficulty {
  return v === 'casual' || v === 'tactical' || v === 'pro' || v === 'mixed';
}

function isQualityPreset(v: unknown): v is QualityPreset {
  return v === 'performance' || v === 'balanced' || v === 'high';
}

function loadSettings(): GameSettings {
  try {
    const raw = window.localStorage.getItem(SETTINGS_STORAGE_KEY);
    if (!raw) return { ...DEFAULT_GAME_SETTINGS };
    const parsed = JSON.parse(raw) as Partial<GameSettings>;
    return {
      botDifficulty: isBotDifficulty(parsed.botDifficulty)
        ? parsed.botDifficulty
        : DEFAULT_GAME_SETTINGS.botDifficulty,
      qualityPreset: isQualityPreset(parsed.qualityPreset)
        ? parsed.qualityPreset
        : DEFAULT_GAME_SETTINGS.qualityPreset,
      showPerfHud:
        typeof parsed.showPerfHud === 'boolean' ? parsed.showPerfHud : DEFAULT_GAME_SETTINGS.showPerfHud,
      masterVolume: clampNum(
        parsed.masterVolume ?? DEFAULT_GAME_SETTINGS.masterVolume,
        0,
        1,
        DEFAULT_GAME_SETTINGS.masterVolume
      ),
      muted: typeof parsed.muted === 'boolean' ? parsed.muted : DEFAULT_GAME_SETTINGS.muted,
      mouseSensitivity: clampNum(
        parsed.mouseSensitivity ?? DEFAULT_GAME_SETTINGS.mouseSensitivity,
        0.4,
        2.2,
        DEFAULT_GAME_SETTINGS.mouseSensitivity
      ),
      adsSensitivity: clampNum(
        parsed.adsSensitivity ?? DEFAULT_GAME_SETTINGS.adsSensitivity,
        0.4,
        2.0,
        DEFAULT_GAME_SETTINGS.adsSensitivity
      ),
      invertY: typeof parsed.invertY === 'boolean' ? parsed.invertY : DEFAULT_GAME_SETTINGS.invertY,
    };
  } catch {
    return { ...DEFAULT_GAME_SETTINGS };
  }
}

function saveSettings(settings: GameSettings): void {
  try {
    window.localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(settings));
  } catch {
    // Graceful fallback when storage is unavailable or private browsing blocks writes
  }
}

// ==================== STATE ====================
let splashActive = true;
let splashTickerRafId = 0;
let splashSceneBarButtons: HTMLButtonElement[] = [];
let splashSceneBarFills: HTMLElement[] = [];
let activeMenuPage: MenuPage = 'home';
let activeSettingsTab: SettingsTab = 'gameplay';
let settingsReturnTarget: 'menu' | 'pause' = 'menu';
let selectedModeId: GameModeId = 'battle_royale';
let selectedHeroId: ProductHeroId = 'gmail';
let currentSettings: GameSettings = loadSettings();
let assetsReady = false;
let lastLoadPct = 0;
let lastPreloadTotal = 0;
let isFullMapOpen = false;
let currentMatchPhase: HudSnapshot['matchPhase'] = 'lobby';
let bannerTimer: number | undefined;
let hitmarkerTimer: number | undefined;
let critFlashTimer: number | undefined;
let savedNoteTimer: number | undefined;
let testSoundTimer: number | undefined;
let lastHotbarSig = '';
let lastStatusSig = '';
let lastPerfSig = '';
let lastMinimapRenderMs = 0;
let lastFullMapRenderMs = 0;
let lastPerfUpdateMs = 0;
let lastHeroHudId: ProductHeroId | null = null;
let lastHudModeId: GameModeId | null = null;
let lastActiveNameColor = '';
let lastCrosshairGap = '';

const textCache = new WeakMap<HTMLElement, string>();
const widthCache = new WeakMap<HTMLElement, string>();

function setTextCached(el: HTMLElement, text: string): void {
  if (textCache.get(el) === text) return;
  textCache.set(el, text);
  el.textContent = text;
}

function setWidthCached(el: HTMLElement, widthStr: string): void {
  if (widthCache.get(el) === widthStr) return;
  widthCache.set(el, widthStr);
  el.style.width = widthStr;
}

function formatModeBadge(raw: string): string {
  return raw
    .toLowerCase()
    .split(/\s+/)
    .map((word) => (word.length > 0 ? word[0].toUpperCase() + word.slice(1) : ''))
    .join(' ');
}

const QUALITY_DESCRIPTIONS: Record<QualityPreset, string> = {
  performance: 'Performance · 1.0× DPR · 1024 Shadows · Max FPS',
  balanced: 'Balanced · 1.25× DPR · 1536 Shadows',
  high: 'High · 1.75× DPR · 2048 Shadows · Max Detail',
};

const MODE_SHORT_LABELS: Record<GameModeId, string> = {
  battle_royale: 'ROYALE',
  blitz: 'BLITZ',
  sniper_showdown: 'SNIPER',
  campus_practice: 'FREE ROAM',
};

const CHANNEL_RING_CIRCUMFERENCE = 2 * Math.PI * 36; // r = 36 -> 226.195

// ==================== TACTICAL SVG ICONS FOR 5-SLOT HOTBAR ====================
const WEAPON_SVGS: Record<WeaponId, string> = {
  vanguard_m4: `<svg viewBox="0 0 48 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h11l3-3h14v3h10"/><path d="M18 12l2 6h4l-1-6"/><path d="M27 12l2 7h3l-1-7"/><path d="M5 9v7l4-2"/><path d="M22 7h6"/></svg>`,
  breaker_12g: `<svg viewBox="0 0 48 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><path d="M4 14l6-4h33"/><path d="M16 13h19"/><path d="M11 10l-2 7h4l2-5"/><path d="M22 13v3h8v-3"/></svg>`,
  vector_9: `<svg viewBox="0 0 48 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 10h25v4H18l-4 3H9z"/><path d="M34 11h7"/><path d="M22 14l-1 7h4l1-7"/><path d="M16 14l-2 5"/></svg>`,
  longbow_308: `<svg viewBox="0 0 48 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M3 14l7-3h35"/><path d="M16 7h12v3H16z"/><path d="M12 11l-1 6h4l1-6"/><path d="M23 11v5h4v-5"/></svg>`,
  nova_gl40: `<svg viewBox="0 0 48 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="19" y="8" width="11" height="9" rx="2"/><path d="M6 12h13"/><path d="M30 11h12v3H30"/><path d="M13 12l-2 7h4l1-7"/></svg>`,
};

const UTILITY_SVGS: Record<UtilityItemId, string> = {
  shield_cell: `<svg viewBox="0 0 32 24" fill="none" stroke="#669DF6" stroke-width="2" stroke-linejoin="round"><rect x="10" y="5" width="12" height="15" rx="3"/><path d="M13 5V3h6v2"/><path d="M13 13h6M16 10v6"/></svg>`,
  shield_jug: `<svg viewBox="0 0 32 24" fill="none" stroke="#4285F4" stroke-width="2" stroke-linejoin="round"><path d="M11 6h10l3 5v8a2 2 0 0 1-2 2H10a2 2 0 0 1-2-2v-8l3-5z"/><path d="M13 3h6v3h-6z"/><path d="M12 14h8"/></svg>`,
  medkit: `<svg viewBox="0 0 32 24" fill="none" stroke="#34A853" stroke-width="2" stroke-linejoin="round"><rect x="6" y="6" width="20" height="14" rx="3"/><path d="M12 6V4h8v2"/><path d="M16 9.5v7M12.5 13h7"/></svg>`,
  mana_elixir: `<svg viewBox="0 0 32 24" fill="none" stroke="#C58AF9" stroke-width="2" stroke-linejoin="round"><path d="M13 3h6v4l5 9a3 3 0 0 1-2.6 4.5H10.6A3 3 0 0 1 8 16l5-9V3z"/><path d="M10.5 15h11"/></svg>`,
  hardlight_cover: `<svg viewBox="0 0 32 24" fill="none" stroke="#8AB4F8" stroke-width="2" stroke-linecap="round"><path d="M6 17c3-8 17-8 20 0"/><path d="M9 19c2.5-5 11.5-5 14 0"/><path d="M16 7v4"/></svg>`,
  impulse_booster: `<svg viewBox="0 0 32 24" fill="none" stroke="#FBBC04" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 4l6 8h-4v8h-4v-8h-4l6-8z"/></svg>`,
};

// ==================== BRIGHT GOOGLE STUDIO 3D HERO SHOWCASE (SINGLE WEBGL CONTEXT) ====================
class LobbyHeroShowcase {
  private renderer: THREE.WebGLRenderer;
  private scene: THREE.Scene;
  private camera: THREE.PerspectiveCamera;
  private turntable: THREE.Group;
  private pedestalRingMat: THREE.MeshStandardMaterial;
  private accentLight: THREE.PointLight;
  private pmrem: THREE.PMREMGenerator;
  private envTex: THREE.Texture;
  private stageEl: HTMLElement;

  private currentHero: HeroInstance | null = null;
  private currentWeapon: WeaponInstance | null = null;
  private currentHeroId: ProductHeroId | null = null;
  private assets: AssetManager;

  // Blender exported heroes face -Z; yaw = Math.PI faces +Z (straight at camera)
  private yaw = Math.PI + 0.16;
  private targetSnapYaw: number | null = null;
  private dragVelocity = 0;
  private isDragging = false;
  private lastPointerX = 0;
  private idleDelaySec = 0;
  private lastFrameTime = performance.now();
  private rafId = 0;
  private active = false;

  constructor(canvas: HTMLCanvasElement, stageEl: HTMLElement, assets: AssetManager) {
    this.stageEl = stageEl;
    this.assets = assets;

    this.renderer = new THREE.WebGLRenderer({
      canvas,
      alpha: true,
      antialias: true,
      powerPreference: 'high-performance',
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.08;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;

    this.scene = new THREE.Scene();

    // Real-time bright studio RoomEnvironment reflections for PBR glass, ceramic & metal
    this.pmrem = new THREE.PMREMGenerator(this.renderer);
    this.envTex = this.pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    this.scene.environment = this.envTex;

    this.camera = new THREE.PerspectiveCamera(34, 600 / 440, 0.1, 30);
    this.camera.position.set(0, 1.22, 3.45);
    this.camera.lookAt(0, 1.0, 0);

    // Bright Google Workspace Studio Lighting Rig (Clean Daylight Hemisphere, Soft Warm-White Key, Sky Fill)
    const hemi = new THREE.HemisphereLight(0xffffff, 0xdbeafe, 1.05);
    this.scene.add(hemi);

    const keyLight = new THREE.DirectionalLight(0xfffaf0, 2.35);
    keyLight.position.set(2.4, 4.0, 3.4);
    keyLight.castShadow = true;
    keyLight.shadow.mapSize.set(1024, 1024);
    keyLight.shadow.camera.near = 0.5;
    keyLight.shadow.camera.far = 12;
    keyLight.shadow.camera.left = -2;
    keyLight.shadow.camera.right = 2;
    keyLight.shadow.camera.top = 2.5;
    keyLight.shadow.camera.bottom = -1;
    keyLight.shadow.bias = -0.0005;
    this.scene.add(keyLight);

    const fillLight = new THREE.DirectionalLight(0xdbeafe, 1.15);
    fillLight.position.set(-2.8, 2.4, 2.2);
    this.scene.add(fillLight);

    const rimLight = new THREE.DirectionalLight(0xffffff, 1.2);
    rimLight.position.set(-0.6, 2.8, -3.4);
    this.scene.add(rimLight);

    this.accentLight = new THREE.PointLight(0xea4335, 0.85, 5.0);
    this.accentLight.position.set(0, 0.45, 1.35);
    this.scene.add(this.accentLight);

    // Turntable & Architectural Pearl-White Studio Pedestal
    this.turntable = new THREE.Group();
    this.turntable.rotation.y = this.yaw;
    this.scene.add(this.turntable);

    const pedestalGeo = new THREE.CylinderGeometry(0.76, 0.86, 0.14, 48);
    const pedestalMat = new THREE.MeshStandardMaterial({
      color: 0xf4f7fb,
      roughness: 0.45,
      metalness: 0.12,
    });
    const pedestal = new THREE.Mesh(pedestalGeo, pedestalMat);
    pedestal.position.y = -0.07;
    pedestal.receiveShadow = true;
    this.scene.add(pedestal);

    this.pedestalRingMat = new THREE.MeshStandardMaterial({
      color: 0xea4335,
      emissive: 0xea4335,
      emissiveIntensity: 0.35,
      roughness: 0.3,
      metalness: 0.25,
    });
    const trimRing = new THREE.Mesh(new THREE.TorusGeometry(0.765, 0.016, 12, 64), this.pedestalRingMat);
    trimRing.rotation.x = Math.PI / 2;
    trimRing.position.y = 0.002;
    this.scene.add(trimRing);

    this.bindPointerDrag(stageEl);
    this.observeResize(stageEl);
    this.syncSize();
    this.startLoop();
  }

  private bindPointerDrag(stageEl: HTMLElement): void {
    stageEl.addEventListener('pointerdown', (e) => {
      if ((e.target as HTMLElement).closest('button')) return;
      this.isDragging = true;
      this.targetSnapYaw = null;
      this.lastPointerX = e.clientX;
      this.dragVelocity = 0;
      stageEl.classList.add('dragging');
      stageEl.setPointerCapture(e.pointerId);
    });

    stageEl.addEventListener('pointermove', (e) => {
      if (!this.isDragging) return;
      const dx = e.clientX - this.lastPointerX;
      this.lastPointerX = e.clientX;
      const deltaYaw = dx * 0.012;
      this.yaw += deltaYaw;
      this.dragVelocity = deltaYaw * 48;
      this.idleDelaySec = 2.4;
      this.updateFlipButtonLabel();
    });

    const endDrag = (e: PointerEvent): void => {
      if (!this.isDragging) return;
      this.isDragging = false;
      stageEl.classList.remove('dragging');
      if (stageEl.hasPointerCapture(e.pointerId)) {
        stageEl.releasePointerCapture(e.pointerId);
      }
    };

    stageEl.addEventListener('pointerup', endDrag);
    stageEl.addEventListener('pointercancel', endDrag);
  }

  private observeResize(stageEl: HTMLElement): void {
    const ro = new ResizeObserver(() => this.syncSize());
    ro.observe(stageEl);
  }

  public syncSize(stageEl: HTMLElement = this.stageEl): void {
    const rect = stageEl.getBoundingClientRect();
    if (rect.width < 10 || rect.height < 10) return;
    const w = Math.max(240, Math.round(rect.width));
    const h = Math.max(200, Math.round(rect.height));
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  public setActive(active: boolean): void {
    const resuming = active && !this.active;
    this.active = active;
    if (resuming) {
      this.lastFrameTime = performance.now();
      this.syncSize();
    }
  }

  private clearCurrentHero(): void {
    if (!this.currentHero) return;
    this.currentHero.mixer.stopAllAction();
    if (this.currentWeapon) {
      this.currentHero.weaponSocket.remove(this.currentWeapon.root);
      this.currentWeapon = null;
    }
    this.turntable.remove(this.currentHero.root);
    this.currentHero = null;
    this.currentHeroId = null;
  }

  public setHero(heroId: ProductHeroId): void {
    const heroDef = HERO_MAP[heroId];
    this.pedestalRingMat.color.setHex(heroDef.hexPrimary);
    this.pedestalRingMat.emissive.setHex(heroDef.hexPrimary);
    this.accentLight.color.setHex(heroDef.hexPrimary);

    const weaponId = heroDef.lobbyWeaponId;
    const heroShowcaseReady =
      this.assets.isHeroReady(heroId) && (!weaponId || this.assets.isWeaponReady(weaponId));

    if (!heroShowcaseReady && !this.assets.isLoaded) {
      if (this.currentHeroId !== heroId) {
        this.clearCurrentHero();
      }
      previewLoadingPill.textContent = `Loading ${heroDef.personaName}...`;
      previewLoadingPill.classList.remove('hidden');
      return;
    }

    if (this.currentHeroId === heroId && this.currentHero) {
      previewLoadingPill.classList.add('hidden');
      return;
    }

    this.clearCurrentHero();

    const inst = this.assets.instantiateHero(heroId, { includeOverhead: false });
    let showcaseWeapon: WeaponInstance | null = null;
    if (weaponId) {
      showcaseWeapon = this.assets.instantiateWeapon(weaponId, 'common');
      inst.weaponSocket.add(showcaseWeapon.root);
    }
    inst.mixer.stopAllAction();
    inst.actions.LobbyShowcase.reset();
    inst.actions.LobbyShowcase.setLoop(THREE.LoopRepeat, Infinity);
    inst.actions.LobbyShowcase.setEffectiveWeight(1);
    inst.actions.LobbyShowcase.play();
    inst.currentAnim = 'LobbyShowcase';

    this.turntable.add(inst.root);
    inst.mixer.update(0.001);
    this.turntable.updateMatrixWorld(true);
    if (showcaseWeapon) {
      alignWeaponTwoHanded(showcaseWeapon.root, inst, {
        weaponId: showcaseWeapon.weaponId,
        skipMatrixUpdate: true,
      });
    }

    this.currentHero = inst;
    this.currentWeapon = showcaseWeapon;
    this.currentHeroId = heroId;

    this.targetSnapYaw = Math.PI + 0.16;
    this.idleDelaySec = 1.8;
    previewLoadingPill.classList.add('hidden');
    this.updateFlipButtonLabel();
  }

  public flipFrontBack(): void {
    const norm = ((this.yaw % (Math.PI * 2)) + Math.PI * 2) % (Math.PI * 2);
    const showingFront = Math.abs(norm - Math.PI) < Math.PI * 0.5;
    const baseTurns = Math.round((this.yaw - Math.PI) / (Math.PI * 2)) * Math.PI * 2;
    this.targetSnapYaw = showingFront ? baseTurns : baseTurns + Math.PI;
    this.dragVelocity = 0;
    this.idleDelaySec = 3.2;
    btnFlipPreview.textContent = showingFront ? 'Inspect Front' : 'Inspect Back';
  }

  private updateFlipButtonLabel(): void {
    const norm = ((this.yaw % (Math.PI * 2)) + Math.PI * 2) % (Math.PI * 2);
    const showingFront = Math.abs(norm - Math.PI) < Math.PI * 0.5;
    btnFlipPreview.textContent = showingFront ? 'Inspect Back' : 'Inspect Front';
  }

  private startLoop(): void {
    const tick = (now: number): void => {
      this.rafId = requestAnimationFrame(tick);
      const dt = Math.min(0.05, Math.max(0.001, (now - this.lastFrameTime) * 0.001));
      this.lastFrameTime = now;

      // Pause 3D turntable completely when Splash is active, menu is hidden, OR on Modes/Settings pages
      if (!this.active || splashActive || lobbyOverlay.classList.contains('hidden')) return;

      if (this.currentHero) {
        this.currentHero.mixer.update(dt);
      }

      if (this.targetSnapYaw !== null) {
        const diff = this.targetSnapYaw - this.yaw;
        if (Math.abs(diff) < 0.005) {
          this.yaw = this.targetSnapYaw;
          this.targetSnapYaw = null;
        } else {
          this.yaw += diff * Math.min(1, dt * 8.5);
        }
      } else if (!this.isDragging) {
        if (Math.abs(this.dragVelocity) > 0.02) {
          this.yaw += this.dragVelocity * dt;
          this.dragVelocity *= Math.pow(0.08, dt);
        } else if (this.idleDelaySec > 0) {
          this.idleDelaySec = Math.max(0, this.idleDelaySec - dt);
        } else {
          this.yaw += 0.24 * dt;
        }
      }

      this.turntable.rotation.y = this.yaw;

      if (this.currentHero && this.currentWeapon) {
        this.turntable.updateMatrixWorld(true);
        alignWeaponTwoHanded(this.currentWeapon.root, this.currentHero, {
          weaponId: this.currentWeapon.weaponId,
          skipMatrixUpdate: true,
        });
      }

      this.renderer.render(this.scene, this.camera);
    };

    this.rafId = requestAnimationFrame(tick);
  }

  public getLoadedHeroId(): ProductHeroId | null {
    return this.currentHeroId;
  }

  public dispose(): void {
    cancelAnimationFrame(this.rafId);
    this.envTex.dispose();
    this.pmrem.dispose();
    this.renderer.dispose();
  }
}

// ==================== MINIMAP & COMPASS INSTANCE ====================
const minimap = new TacticalMinimap(minimapCanvas, compassCanvas, compassDegEl);

// ==================== MENU PAGE NAVIGATION & SHOWCASE REPARENTING ====================
function formatDifficultyLabel(diff: BotDifficulty): string {
  const opt = BOT_DIFFICULTY_OPTIONS.find((o) => o.id === diff);
  return opt ? opt.label : 'Tactical (Staff)';
}

function formatDifficultyShort(diff: BotDifficulty): string {
  if (diff === 'casual') return 'INTERN';
  if (diff === 'pro') return 'PRO';
  if (diff === 'mixed') return 'MIXED';
  return 'STAFF';
}

function syncShowcasePlacement(): void {
  if (splashActive || lobbyOverlay.classList.contains('hidden')) {
    showcase.setActive(false);
    return;
  }

  if (activeMenuPage === 'home') {
    if (previewStage.parentElement !== homeShowcaseSlot) {
      homeShowcaseSlot.appendChild(previewStage);
    }
    showcase.setActive(true);
    showcase.syncSize();
    requestAnimationFrame(() => showcase.syncSize());
  } else if (activeMenuPage === 'characters') {
    if (previewStage.parentElement !== charactersShowcaseSlot) {
      charactersShowcaseSlot.appendChild(previewStage);
    }
    showcase.setActive(true);
    showcase.syncSize();
    requestAnimationFrame(() => showcase.syncSize());
  } else {
    // Pause showcase GPU rendering on Play Modes & Settings pages
    showcase.setActive(false);
  }
}

function setActiveSettingsTab(tab: SettingsTab): void {
  activeSettingsTab = tab;

  document.querySelectorAll<HTMLButtonElement>('.settings-nav-btn').forEach((btn) => {
    const isTarget = btn.dataset.settingsTab === tab;
    btn.classList.toggle('active', isTarget);
    btn.setAttribute('aria-selected', isTarget ? 'true' : 'false');
  });

  document.querySelectorAll<HTMLElement>('.settings-panel').forEach((panel) => {
    const isTarget = panel.dataset.settingsPanel === tab;
    panel.classList.toggle('hidden', !isTarget);
    panel.classList.toggle('active', isTarget);
  });

  settingsContent.scrollTop = 0;
}

function setInMatchSettingsMode(inMatch: boolean): void {
  settingsReturnTarget = inMatch ? 'pause' : 'menu';
  menuNavTabs.classList.toggle('hidden', inMatch);
  btnTopbarSplash.classList.toggle('hidden', inMatch);
  btnTopbarSettings.classList.toggle('hidden', inMatch);
  inmatchSettingsBanner.classList.toggle('hidden', !inMatch);
  navBrandHome.disabled = inMatch;
  btnSettingsDone.textContent = inMatch ? '← Back to Pause' : 'Done';
}

function navigateMenu(page: MenuPage, settingsTab?: SettingsTab): void {
  if (settingsReturnTarget === 'pause' && page !== 'settings') return;

  activeMenuPage = page;

  document.querySelectorAll<HTMLElement>('.menu-page').forEach((section) => {
    const isTarget = section.dataset.pageView === page;
    section.classList.toggle('hidden', !isTarget);
    section.classList.toggle('active', isTarget);
    if (isTarget) {
      section.scrollTop = 0;
    }
  });

  document.querySelectorAll<HTMLButtonElement>('.menu-tab').forEach((tab) => {
    tab.classList.toggle('active', tab.dataset.page === page);
  });
  btnTopbarSettings.classList.toggle('active', page === 'settings');

  menuPageViewport.scrollTop = 0;

  if (page === 'modes') {
    modesBody.scrollTop = 0;
  } else if (page === 'settings') {
    setActiveSettingsTab(settingsTab ?? activeSettingsTab);
    syncSettingsUi();
  }
  syncShowcasePlacement();
}

function openSettingsFromPause(initialTab: SettingsTab = 'gameplay'): void {
  pauseOverlay.classList.add('hidden');
  lobbyOverlay.classList.remove('hidden');
  setInMatchSettingsMode(true);
  setActiveSettingsTab(initialTab);
  navigateMenu('settings', initialTab);
}

function closeSettingsToPause(): void {
  setInMatchSettingsMode(false);
  lobbyOverlay.classList.add('hidden');
  showcase.setActive(false);
  pauseOverlay.classList.remove('hidden');
}

// ==================== HOME, PLAY MODES & CHARACTER UI RENDERING ====================
function updatePlayButtons(): void {
  const mode = GAME_MODES[selectedModeId] ?? GAME_MODES.battle_royale;
  const hero = HERO_MAP[selectedHeroId];

  if (!assetsReady) {
    const loadingText = `Loading 3D assets (${lastLoadPct}%)...`;
    btnHomePlay.disabled = true;
    btnModesPlay.disabled = true;
    btnCharsPlay.disabled = true;
    btnHomePlay.textContent = loadingText;
    btnModesPlay.textContent = loadingText;
    btnCharsPlay.textContent = loadingText;

    btnSplashStart.disabled = true;
    btnSplashQuickplay.disabled = true;
    setTextCached(btnSplashStart, `Loading 3D Campus (${lastLoadPct}%)...`);
    setTextCached(btnSplashQuickplay, 'Quick Play');
    return;
  }

  btnHomePlay.disabled = false;
  btnModesPlay.disabled = false;
  btnCharsPlay.disabled = false;
  btnHomePlay.textContent = `Play ${mode.name}`;
  btnModesPlay.textContent = `Play ${mode.name}`;
  btnCharsPlay.textContent = `Play as ${hero.personaName}`;

  btnSplashStart.disabled = false;
  btnSplashQuickplay.disabled = false;
  setTextCached(btnSplashStart, 'Start Game →');
  setTextCached(btnSplashQuickplay, 'Quick Play');
}

function updateHomeSummary(): void {
  const mode = GAME_MODES[selectedModeId] ?? GAME_MODES.battle_royale;
  const hero = HERO_MAP[selectedHeroId];
  const lobbyWeapon = hero.lobbyWeaponId ? WEAPONS[hero.lobbyWeaponId] : null;

  homeModeAccent.style.background = mode.accentCss;
  homeCardMode.style.setProperty('--mode-accent', mode.accentCss);
  homeModeBadge.textContent = formatModeBadge(mode.badge);
  homeModeName.textContent = mode.name;
  homeModeTagline.textContent = mode.tagline;

  homeHeroBadge.innerHTML = HERO_PRODUCT_SVGS[hero.id];
  homeHeroName.textContent = hero.personaName;
  homeHeroMeta.textContent = lobbyWeapon
    ? `${hero.ultimate.name} · ${hero.lobbyAnimLabel} (${lobbyWeapon.skinName})`
    : `${hero.ultimate.name} · ${hero.lobbyAnimLabel}`;

  homeStripHeroName.textContent = hero.personaName;
  homeStripUltName.textContent = `Ultimate [Q]: ${hero.ultimate.name}`;
  pauseMatchPill.textContent = `${mode.name} · ${hero.personaName}`;

  updatePlayButtons();
}

function renderModeSelector(): void {
  modeGrid.innerHTML = '';
  for (const mode of GAME_MODE_LIST) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = `mode-card${mode.id === selectedModeId ? ' selected' : ''}`;
    btn.style.setProperty('--mode-accent', mode.accentCss);
    btn.dataset.modeId = mode.id;

    const highlightsHtml = mode.highlights
      .map((item) => `<span class="mode-highlight-chip">${escapeHtml(item)}</span>`)
      .join('');

    btn.innerHTML = `
      <div class="mode-card-top">
        <span class="mode-badge-pill">${escapeHtml(formatModeBadge(mode.badge))}</span>
        <span class="mode-selected-pill">✓ Selected</span>
      </div>
      <h3 class="mode-card-name">${escapeHtml(mode.name)}</h3>
      <p class="mode-card-tagline">${escapeHtml(mode.tagline)}</p>
      <p class="mode-card-desc">${escapeHtml(mode.description)}</p>
      <div class="mode-highlights">${highlightsHtml}</div>
    `;

    btn.addEventListener('click', () => {
      selectedModeId = mode.id;
      renderModeSelector();
      updateHomeSummary();
      syncPracticeNote();
    });

    modeGrid.appendChild(btn);
  }
}

function renderHeroSelector(): void {
  heroGrid.innerHTML = '';
  for (const h of PRODUCT_HEROES) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = `hero-card${h.id === selectedHeroId ? ' selected' : ''}`;
    btn.style.setProperty('--hero-color', h.primaryColor);
    btn.innerHTML = `
      <div class="ws-product-tile hero-card-icon">${HERO_PRODUCT_SVGS[h.id]}</div>
      <div class="hero-card-text">
        <div class="hero-card-title">${escapeHtml(h.personaName)}</div>
        <div class="hero-card-ult">${escapeHtml(h.ultimate.name)}</div>
        <div class="hero-card-meta">${h.ultimate.manaCost} Mana · ${h.ultimate.cooldown}s CD</div>
      </div>
    `;
    btn.addEventListener('click', () => {
      selectedHeroId = h.id;
      renderHeroSelector();
      updateHeroDetails();
    });
    heroGrid.appendChild(btn);
  }
}

function updateHeroDetails(): void {
  const h = HERO_MAP[selectedHeroId];
  const lobbyWeapon = h.lobbyWeaponId ? WEAPONS[h.lobbyWeaponId] : null;
  detailHeroIcon.innerHTML = HERO_PRODUCT_SVGS[h.id];
  detailHeroName.textContent = h.personaName;
  detailHeroTagline.textContent = h.tagline;
  detailUltName.textContent = `${h.ultimate.name} (${h.ultimate.subtitle})`;
  detailUltDesc.textContent = h.ultimate.description;
  detailUltCost.textContent = `${h.ultimate.manaCost} Mana · ${h.ultimate.cooldown}s CD`;
  previewTag.textContent = `${h.personaName} · Workspace Character`;
  previewRole.textContent = h.role;
  previewShowcasePill.textContent = lobbyWeapon
    ? `✦ ${h.lobbyAnimLabel} · ${lobbyWeapon.skinName} (${lobbyWeapon.name})`
    : `✦ ${h.lobbyAnimLabel} · Unarmed`;
  showcase.setHero(selectedHeroId);
  updateHomeSummary();
}

// ==================== CATEGORIZED SETTINGS LOGIC ====================
function syncPracticeNote(): void {
  settingsPracticeNote.classList.toggle('hidden', selectedModeId !== 'campus_practice');
}

function syncPerfHudVisibility(): void {
  perfPill.classList.toggle('hidden', !currentSettings.showPerfHud);
  if (currentSettings.showPerfHud) {
    lastPerfUpdateMs = 0;
    lastPerfSig = '';
  }
}

function setSliderFill(input: HTMLInputElement, value: number, min: number, max: number): void {
  const pct = Math.max(0, Math.min(100, ((value - min) / Math.max(0.0001, max - min)) * 100));
  input.style.setProperty('--slider-pct', `${pct.toFixed(1)}%`);
}

function flashSavedNote(message: string): void {
  settingsSavedNote.textContent = message;
  settingsSavedNote.classList.add('flash');
  clearTimeout(savedNoteTimer);
  savedNoteTimer = window.setTimeout(() => {
    settingsSavedNote.textContent = 'Changes save automatically';
    settingsSavedNote.classList.remove('flash');
  }, 1500);
}

function syncSettingsUi(): void {
  // Gameplay: Bot Intelligence
  difficultyGrid.querySelectorAll<HTMLButtonElement>('.diff-btn').forEach((btn) => {
    const diff = btn.dataset.diff as BotDifficulty;
    btn.classList.toggle('selected', diff === currentSettings.botDifficulty);
  });
  const opt = BOT_DIFFICULTY_OPTIONS.find((o) => o.id === currentSettings.botDifficulty);
  if (opt) {
    difficultySummary.textContent = `${opt.label}: ${opt.summary}`;
  } else if (currentSettings.botDifficulty !== 'mixed') {
    difficultySummary.textContent = BOT_PROFILES[currentSettings.botDifficulty].description;
  }
  syncPracticeNote();

  // Video: Graphics Quality & Perf HUD
  document.querySelectorAll<HTMLButtonElement>('.quality-btn').forEach((btn) => {
    btn.classList.toggle('selected', btn.dataset.quality === currentSettings.qualityPreset);
  });
  setTextCached(settingsQualitySub, QUALITY_DESCRIPTIONS[currentSettings.qualityPreset]);
  settingShowPerfHud.checked = currentSettings.showPerfHud;

  // Controls: Sensitivity & Invert Y
  settingMouseSens.value = currentSettings.mouseSensitivity.toFixed(2);
  setSliderFill(settingMouseSens, currentSettings.mouseSensitivity, 0.4, 2.2);
  setTextCached(valMouseSens, `${currentSettings.mouseSensitivity.toFixed(2)}×`);
  settingAdsSens.value = currentSettings.adsSensitivity.toFixed(2);
  setSliderFill(settingAdsSens, currentSettings.adsSensitivity, 0.4, 2.0);
  setTextCached(valAdsSens, `${currentSettings.adsSensitivity.toFixed(2)}×`);
  settingInvertY.checked = currentSettings.invertY;

  // Audio: Master Volume & Mute
  const volPct = Math.round(currentSettings.masterVolume * 100);
  settingMasterVolume.value = String(volPct);
  setSliderFill(settingMasterVolume, volPct, 0, 100);
  setTextCached(valMasterVolume, currentSettings.muted ? 'Muted' : `${volPct}%`);
  settingVolumeRow.classList.toggle('is-muted', currentSettings.muted);
  settingMuted.checked = currentSettings.muted;

  // Splash Screen Quick Mute Button Sync
  btnSplashMute.classList.toggle('is-muted', currentSettings.muted);
  btnSplashMute.setAttribute('aria-pressed', currentSettings.muted ? 'true' : 'false');
  btnSplashMute.title = currentSettings.muted ? 'Unmute Audio' : 'Mute Audio';
}

function applyAndSaveSettings(patch: Partial<GameSettings>, savedMessage = 'Saved automatically'): void {
  currentSettings = {
    ...currentSettings,
    ...patch,
    masterVolume: clampNum(
      patch.masterVolume ?? currentSettings.masterVolume,
      0,
      1,
      currentSettings.masterVolume
    ),
    mouseSensitivity: clampNum(
      patch.mouseSensitivity ?? currentSettings.mouseSensitivity,
      0.4,
      2.2,
      currentSettings.mouseSensitivity
    ),
    adsSensitivity: clampNum(
      patch.adsSensitivity ?? currentSettings.adsSensitivity,
      0.4,
      2.0,
      currentSettings.adsSensitivity
    ),
  };

  saveSettings(currentSettings);
  engine.applySettings(currentSettings);
  syncSettingsUi();
  syncPerfHudVisibility();
  flashSavedNote(savedMessage);
}

function bindSettingsControls(): void {
  // Left Sidebar Category Tabs
  document.querySelectorAll<HTMLButtonElement>('.settings-nav-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      const tab = btn.dataset.settingsTab as SettingsTab | undefined;
      if (!tab) return;
      setActiveSettingsTab(tab);
    });
  });

  difficultyGrid.querySelectorAll<HTMLButtonElement>('.diff-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      const diff = btn.dataset.diff as BotDifficulty | undefined;
      if (!diff) return;
      applyAndSaveSettings({ botDifficulty: diff });
    });
  });

  document.querySelectorAll<HTMLButtonElement>('.quality-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      const preset = btn.dataset.quality as QualityPreset | undefined;
      if (!preset) return;
      applyAndSaveSettings({ qualityPreset: preset });
    });
  });

  settingShowPerfHud.addEventListener('change', () => {
    applyAndSaveSettings({ showPerfHud: settingShowPerfHud.checked });
  });

  settingMouseSens.addEventListener('input', () => {
    const val = Number(settingMouseSens.value);
    if (Number.isFinite(val)) {
      applyAndSaveSettings({ mouseSensitivity: val });
    }
  });

  settingAdsSens.addEventListener('input', () => {
    const val = Number(settingAdsSens.value);
    if (Number.isFinite(val)) {
      applyAndSaveSettings({ adsSensitivity: val });
    }
  });

  settingInvertY.addEventListener('change', () => {
    applyAndSaveSettings({ invertY: settingInvertY.checked });
  });

  settingMasterVolume.addEventListener('input', () => {
    const pct = Number(settingMasterVolume.value);
    if (Number.isFinite(pct)) {
      applyAndSaveSettings({
        masterVolume: pct / 100,
        ...(pct > 0 && currentSettings.muted ? { muted: false } : {}),
      });
    }
  });

  btnTestAudio.addEventListener('click', () => {
    engine.playTestSound();
    const labelSpan = btnTestAudio.querySelector('span');
    if (labelSpan) {
      labelSpan.textContent = currentSettings.muted ? 'Audio Muted' : 'Playing...';
      clearTimeout(testSoundTimer);
      testSoundTimer = window.setTimeout(() => {
        labelSpan.textContent = 'Test Sound';
      }, 650);
    }
  });

  settingMuted.addEventListener('change', () => {
    applyAndSaveSettings({ muted: settingMuted.checked });
  });

  btnSettingsReset.addEventListener('click', () => {
    applyAndSaveSettings({ ...DEFAULT_GAME_SETTINGS }, 'Defaults restored');
  });

  btnSettingsDone.addEventListener('click', () => {
    if (settingsReturnTarget === 'pause') {
      closeSettingsToPause();
    } else {
      navigateMenu('home');
    }
  });

  btnInmatchBack.addEventListener('click', closeSettingsToPause);
}

// ==================== FULL TACTICAL MAP OVERLAY [M] ====================
function updateFullMapWaypointPill(state: MinimapState): void {
  if (state.waypoint) {
    const dist = Math.round(
      Math.hypot(state.waypoint.x - state.playerX, state.waypoint.z - state.playerZ)
    );
    fullmapWaypointPill.classList.remove('hidden');
    setTextCached(fullmapWaypointDist, `Ping ${dist}m`);
  } else {
    fullmapWaypointPill.classList.add('hidden');
  }
}

function renderFullMapImmediate(): void {
  const now = performance.now();
  lastFullMapRenderMs = now;
  const mmState = engine.getMinimapState();
  minimap.renderFullMap(fullmapCanvas, mmState, now * 0.001);
  updateFullMapWaypointPill(mmState);
}

function openFullMap(): void {
  if (splashActive) return;
  if (isFullMapOpen) return;
  if (currentMatchPhase !== 'skydrop' && currentMatchPhase !== 'playing') return;
  if (!lobbyOverlay.classList.contains('hidden')) return;
  if (!gameoverOverlay.classList.contains('hidden')) return;
  if (!pauseOverlay.classList.contains('hidden')) return;

  isFullMapOpen = true;
  lastFullMapRenderMs = 0;
  pauseOverlay.classList.add('hidden');
  fullmapOverlay.classList.remove('hidden');
  engine.setMapOpen(true);
  if (lastFullMapRenderMs === 0) {
    renderFullMapImmediate();
  }
}

function closeFullMap(resumeLock = true): void {
  if (!isFullMapOpen && fullmapOverlay.classList.contains('hidden')) return;
  isFullMapOpen = false;
  fullmapOverlay.classList.add('hidden');
  pauseOverlay.classList.add('hidden');
  lastMinimapRenderMs = 0;
  if (resumeLock) {
    engine.setMapOpen(false);
  }
}

// ==================== HUD RENDERING ====================
function showBanner(title: string, subtitle?: string): void {
  let cleanSubtitle = subtitle;
  if (cleanSubtitle) {
    if (title === 'DROP INTO GOOGLEPLEX') {
      cleanSubtitle = undefined;
    } else if (title.startsWith('TOUCHDOWN') && cleanSubtitle.includes(' · ')) {
      cleanSubtitle = cleanSubtitle.split(' · ')[0];
    } else if (/\[(?:E|1–5|Q|R|M)\]|WASD|SHIFT/i.test(cleanSubtitle)) {
      cleanSubtitle = undefined;
    }
  }
  bannerToast.textContent = cleanSubtitle ? `${title} — ${cleanSubtitle}` : title;
  bannerToast.classList.remove('hidden');
  clearTimeout(bannerTimer);
  bannerTimer = window.setTimeout(() => bannerToast.classList.add('hidden'), 3200);
}

function spawnDirectionalDamageArc(event: DirectionalDamageEvent): void {
  if (event.isStorm) return;
  const arc = document.createElement('div');
  arc.className = 'damage-arc';
  const deg = (event.bearingRad * 180) / Math.PI;
  arc.style.transform = `rotate(${deg.toFixed(1)}deg)`;
  const strokeW = Math.min(13, Math.max(6, 5 + event.amount * 0.14));
  arc.innerHTML = `
    <svg viewBox="0 0 240 240">
      <path
        d="M 76 26 A 104 104 0 0 1 164 26"
        fill="none"
        stroke="rgba(234, 67, 53, 0.94)"
        stroke-width="${strokeW.toFixed(1)}"
        stroke-linecap="round"
        style="filter: drop-shadow(0 0 10px rgba(234, 67, 53, 0.95));"
      />
    </svg>
  `;
  damageArcLayer.appendChild(arc);
  window.setTimeout(() => arc.remove(), 1120);
}

function spawnFloatingDamage(event: FloatingDamageEvent): void {
  const el = document.createElement('div');
  const isCrit = event.kind === 'headshot';
  el.className = `dmg-float${isCrit ? ' crit' : ''}`;
  el.textContent =
    event.kind === 'heal'
      ? `+${Math.round(event.amount)}`
      : `${Math.round(event.amount)}${isCrit ? '!' : ''}`;
  el.style.left = `${event.screenX + (Math.random() - 0.5) * 18}px`;
  el.style.top = `${event.screenY}px`;
  if (event.kind === 'shield') {
    el.style.color = '#669DF6';
  } else if (event.kind === 'heal') {
    el.style.color = '#81C995';
  } else if (isCrit) {
    el.style.color = '#FBBC04';
  } else {
    el.style.color = '#FFFFFF';
  }
  damageLayer.appendChild(el);
  window.setTimeout(() => el.remove(), isCrit ? 940 : 800);
}

function pushKillFeed(entry: KillFeedEntry): void {
  const el = document.createElement('div');
  el.className = `kill-entry${entry.headshot ? ' headshot' : ''}`;

  const badges: string[] = [];
  if (entry.headshot) badges.push('<span class="kill-hs-tag">HEADSHOT</span>');
  if (entry.isUltimate) badges.push('<span class="kill-ult-tag">ULT</span>');

  if (entry.isStorm) {
    el.innerHTML = `<span>${escapeHtml(entry.victim)} eliminated by <b>Storm</b></span>`;
  } else {
    el.innerHTML = `
      <span><b>${escapeHtml(entry.killer)}</b> [${escapeHtml(entry.weapon)}] <b>${escapeHtml(entry.victim)}</b></span>
      ${badges.join('')}
    `;
  }

  killFeedEl.prepend(el);
  while (killFeedEl.children.length > 5) {
    killFeedEl.removeChild(killFeedEl.lastChild!);
  }
  window.setTimeout(() => el.remove(), 7000);
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function renderStatusBadges(state: HudSnapshot): void {
  const badges: { cls: string; text: string }[] = [];
  if (state.status.sliding) {
    badges.push({ cls: 'slide', text: 'SLIDING • -45% SPREAD' });
  } else if (state.status.crouching) {
    let crouchLabel = 'CROUCH • -45% SPREAD';
    if (state.channel.active && state.channel.kind === 'consumable') {
      const lower = state.channel.label.toLowerCase();
      if (lower.includes('shield')) {
        crouchLabel = 'CROUCHING • SHIELDING';
      } else if (lower.includes('medkit')) {
        crouchLabel = 'CROUCHING • HEALING';
      }
    }
    badges.push({ cls: 'crouch', text: crouchLabel });
  }
  if (state.status.silencedSec > 0.05) {
    badges.push({ cls: 'silenced', text: `SILENCED ${state.status.silencedSec.toFixed(1)}s` });
  }
  if (state.status.hastedSec > 0.05) {
    badges.push({ cls: 'hasted', text: `HARD STOP HASTE ${state.status.hastedSec.toFixed(1)}s` });
  }
  if (state.status.slowedSec > 0.05) {
    badges.push({ cls: 'slowed', text: `TIME SLOWED ${state.status.slowedSec.toFixed(1)}s` });
  }
  if (state.status.rewinding) {
    badges.push({ cls: 'version-history', text: 'VERSION HISTORY ROLLBACK' });
  } else if (state.heroId === 'docs' && state.matchPhase === 'playing') {
    badges.push({ cls: 'version-history', text: 'VERSION HISTORY 4s SNAPSHOT' });
  }
  if (state.status.revealedSec > 0.05) {
    badges.push({ cls: 'revealed', text: `PING REVEALED ${state.status.revealedSec.toFixed(1)}s` });
  }

  const sig = badges.map((b) => `${b.cls}:${b.text}`).join('|');
  if (sig === lastStatusSig) return;
  lastStatusSig = sig;

  statusBadgesEl.innerHTML = badges
    .map((b) => `<span class="status-badge ${b.cls}">${b.text}</span>`)
    .join('');
}

function renderHud(state: HudSnapshot): void {
  const nowMs = performance.now();
  const hero = HERO_MAP[state.heroId];
  const mode = GAME_MODES[state.gameMode] ?? GAME_MODES.battle_royale;
  currentMatchPhase = state.matchPhase;

  // Throttled 2D Minimap (~15 Hz when closed) vs Full Tactical Map (~20 Hz when open)
  if (isFullMapOpen) {
    if (nowMs - lastFullMapRenderMs >= 50) {
      lastFullMapRenderMs = nowMs;
      const mmState = engine.getMinimapState();
      minimap.renderFullMap(fullmapCanvas, mmState, nowMs * 0.001);
      updateFullMapWaypointPill(mmState);
    }
  } else if (nowMs - lastMinimapRenderMs >= 65) {
    lastMinimapRenderMs = nowMs;
    minimap.render(engine.getMinimapState(), nowMs * 0.001);
  }

  // Top-Center Compass Strip (Supply Drops + Active Waypoint Diamond)
  const compassWaypoint =
    state.waypointBearingRad != null && state.waypointDist != null
      ? { bearingRad: state.waypointBearingRad, dist: state.waypointDist }
      : null;
  minimap.renderCompass(state.headingRad, state.supplyDropBearings, compassWaypoint);

  // Live Performance Telemetry Badge (2 Hz = >= 500ms, gated by Settings showPerfHud)
  if (currentSettings.showPerfHud && nowMs - lastPerfUpdateMs >= 500) {
    lastPerfUpdateMs = nowMs;
    const perf = engine.getPerfStats();
    const fps = Math.max(0, Math.round(perf.fps));
    const draws = Math.max(0, Math.round(perf.drawCalls));
    const tier = fps >= 50 ? 'good' : fps >= 35 ? 'warn' : 'bad';
    const perfSig = `${fps}|${draws}|${tier}`;
    if (perfSig !== lastPerfSig) {
      lastPerfSig = perfSig;
      setTextCached(perfFpsEl, `${fps} FPS`);
      setTextCached(perfDrawsEl, `${draws} draws`);
      perfPill.classList.toggle('perf-good', tier === 'good');
      perfPill.classList.toggle('perf-warn', tier === 'warn');
      perfPill.classList.toggle('perf-bad', tier === 'bad');
    }
  }

  // Hero Authentic Multi-Color Product SVG, Mode Label & Counters (cached)
  if (lastHeroHudId !== state.heroId) {
    lastHeroHudId = state.heroId;
    hudHeroAvatar.innerHTML = HERO_PRODUCT_SVGS[state.heroId];
    hudHeroAvatar.style.borderColor = hero.primaryColor;
    setTextCached(hudHeroName, hero.displayName);
  }
  if (lastHudModeId !== mode.id) {
    lastHudModeId = mode.id;
    setTextCached(hudModeLabel, MODE_SHORT_LABELS[mode.id] ?? 'ROYALE');
    hudModeLabel.style.color = mode.accentCss;
  }
  setTextCached(hudAlive, String(state.aliveCount));
  setTextCached(hudElims, String(state.eliminations));
  setTextCached(hudHeadshots, String(state.headshots));
  setTextCached(hudBotTier, formatDifficultyShort(state.botDifficulty));

  // Vitals Bars (Shield Blue, Health Green->Yellow->Red, Mana Violet)
  const shieldPct = Math.max(0, Math.min(100, (state.shield / Math.max(1, state.maxShield)) * 100));
  const healthPct = Math.max(0, Math.min(100, (state.health / Math.max(1, state.maxHealth)) * 100));
  const manaPct = Math.max(0, Math.min(100, (state.mana / Math.max(1, state.maxMana)) * 100));

  setWidthCached(barShield, `${shieldPct.toFixed(1)}%`);
  setWidthCached(barHealth, `${healthPct.toFixed(1)}%`);
  setWidthCached(barMana, `${manaPct.toFixed(1)}%`);
  barHealth.classList.toggle('mid', healthPct <= 55 && healthPct > 25);
  barHealth.classList.toggle('low', healthPct <= 25);

  setTextCached(numShield, String(Math.ceil(state.shield)));
  setTextCached(numHealth, String(Math.ceil(state.health)));
  setTextCached(numMana, String(Math.floor(state.mana)));

  // Screen Vignettes
  const showStormAlarm = mode.stormEnabled && state.inStorm;
  stormVignette.classList.toggle('hidden', !showStormAlarm);
  lowHpVignette.classList.toggle('hidden', state.health <= 0 || state.health > 30);

  // Zone & Storm Status (calm indicator when storm is disabled in Campus Free Roam)
  const upperZone = state.zoneName.toUpperCase();
  setTextCached(zoneNameEl, upperZone);

  if (!mode.stormEnabled) {
    stormPill.classList.remove('in-storm');
    stormPill.classList.add('no-storm');
    setTextCached(stormPhaseBadge, 'SAFE');
    setTextCached(stormStatus, 'FREE ROAM · NO STORM');
    if (isFullMapOpen) {
      setTextCached(fullmapZoneEl, state.zoneName);
      fullmapStormEl.classList.add('no-storm');
      setTextCached(fullmapStormEl, 'Free Roam · No Storm');
    }
  } else {
    stormPill.classList.remove('no-storm');
    setTextCached(stormPhaseBadge, `P${state.stormPhase}`);
    const timerStr = `${Math.max(0, Math.ceil(state.stormTimer))}s`;
    const cleanStormLabel = state.stormStateLabel.replace(/^Phase\s+\d+\s+/i, '');
    const stormAction =
      cleanStormLabel.toLowerCase() === 'wait'
        ? `Shrinking in ${timerStr}`
        : `${cleanStormLabel} · ${timerStr}`;
    setTextCached(
      stormStatus,
      state.inStorm ? `IN STORM (-${state.stormDps} HP/s) · ${stormAction}` : stormAction
    );
    stormPill.classList.toggle('in-storm', state.inStorm);

    if (isFullMapOpen) {
      setTextCached(fullmapZoneEl, state.zoneName);
      fullmapStormEl.classList.remove('no-storm');
      setTextCached(fullmapStormEl, `P${state.stormPhase} · ${stormAction}`);
    }
  }

  // Sky-Drop Glider HUD Prompt
  const isSkyDrop = state.status.skyDropping || state.matchPhase === 'skydrop';
  skydropPrompt.classList.toggle('hidden', !isSkyDrop);
  if (isSkyDrop) {
    const alt = Math.max(0, Math.round(state.status.altitude));
    setTextCached(skydropAlt, `${alt}m`);
    const altPct = Math.max(0, Math.min(100, (state.status.altitude / GAME_CONSTANTS.SKY_DROP_ALTITUDE) * 100));
    setWidthCached(skydropBar, `${altPct.toFixed(1)}%`);
  }

  // Sniper Scope Overlay & Dynamic Crosshair
  const active = state.slots[state.activeSlot];
  const hasAnyWeapon = state.slots.some((s) => s?.kind === 'weapon');
  const isUnarmed = !active && !hasAnyWeapon;

  sniperScopeOverlay.classList.toggle('hidden', !state.sniperScope || isFullMapOpen);
  crosshairEl.classList.toggle('hidden', state.sniperScope || isSkyDrop || isFullMapOpen);
  crosshairEl.classList.toggle('ads', state.isAds);
  crosshairEl.classList.toggle('crouching', state.status.crouching);
  crosshairEl.classList.toggle('unarmed', !active || active.kind !== 'weapon');
  const dynamicGap = `${Math.max(2, Math.min(26, state.spreadPx)).toFixed(1)}px`;
  if (dynamicGap !== lastCrosshairGap) {
    lastCrosshairGap = dynamicGap;
    crosshairEl.style.setProperty('--ch-gap', dynamicGap);
  }

  // Circular Consumable / Chest / Supply Drop Channeling Progress Ring
  if (state.channel.active) {
    channelRing.classList.remove('hidden');
    const prog = Math.max(0, Math.min(1, state.channel.progress));
    channelArc.style.strokeDashoffset = String(CHANNEL_RING_CIRCUMFERENCE * (1 - prog));
    const remTxt = `${Math.max(0, state.channel.remainingSec).toFixed(1)}s`;
    setTextCached(channelTime, remTxt);
    const baseLabel = state.channel.label.endsWith('...') ? state.channel.label : `${state.channel.label}...`;
    setTextCached(channelLabel, `${baseLabel} ${remTxt}`);

    const lower = state.channel.label.toLowerCase();
    channelRing.classList.toggle('supply', state.channel.kind === 'supply_drop' || lower.includes('supply'));
    channelRing.classList.toggle('chest-t1', state.channel.kind === 'chest' && state.channel.chestTier === 1);
    channelRing.classList.toggle('chest-t2', state.channel.kind === 'chest' && state.channel.chestTier === 2);
    channelRing.classList.toggle('chest-t3', state.channel.kind === 'chest' && state.channel.chestTier === 3);
    channelRing.classList.toggle('health', lower.includes('medkit'));
    channelRing.classList.toggle('mana', lower.includes('mana'));
  } else {
    channelRing.classList.add('hidden');
  }

  // Proximity Interact Prompt
  if (state.interactPrompt) {
    interactPrompt.classList.remove('hidden');
    setTextCached(interactText, state.interactPrompt.replace(/^\[E\]\s*/i, ''));
    const pLower = state.interactPrompt.toLowerCase();
    interactPrompt.classList.toggle('supply', pLower.includes('supply drop'));
    interactPrompt.classList.toggle('chest-t1', pLower.includes('tier 1'));
    interactPrompt.classList.toggle('chest-t2', pLower.includes('tier 2'));
    interactPrompt.classList.toggle('chest-t3', pLower.includes('tier 3'));
  } else {
    interactPrompt.classList.add('hidden');
  }

  // Status Badges
  renderStatusBadges(state);

  // Bottom-Left Mana & Ultimate Readiness (100-Mana threshold + glowing outline)
  const manaInt = Math.floor(state.mana);
  const isSilenced = state.status.silencedSec > 0.05;
  const isOnCooldown = !isSilenced && state.ultCooldown > 0.05;
  const isUltReady =
    !isSilenced && !isOnCooldown && (state.ultReady || manaInt >= state.ultManaCost);

  heroStatusCard.classList.toggle('ult-ready', isUltReady);
  hudManaRow.classList.toggle('ult-ready', isUltReady);

  hudUltPill.classList.toggle('silenced', isSilenced);
  hudUltPill.classList.toggle('ready', isUltReady);
  hudUltPill.classList.toggle('ult-ready', isUltReady);

  hudUltCallout.classList.toggle('silenced', isSilenced);
  hudUltCallout.classList.toggle('ready', isUltReady);
  hudUltCallout.classList.toggle('ult-ready', isUltReady);

  if (isSilenced) {
    setTextCached(hudUltPill, 'Q · SILENCED');
    setTextCached(hudUltCalloutText, `Access Revoked (${state.status.silencedSec.toFixed(1)}s)`);
  } else if (isOnCooldown) {
    const cdSec = Math.ceil(state.ultCooldown);
    setTextCached(hudUltPill, `Q · ${cdSec}s`);
    setTextCached(hudUltCalloutText, `[Q] ${state.ultName} · Cooldown ${cdSec}s`);
  } else if (isUltReady) {
    setTextCached(hudUltPill, 'Q · READY');
    setTextCached(hudUltCalloutText, `ULTIMATE READY [Q] · ${state.ultName}`);
  } else {
    setTextCached(hudUltPill, `Q · ${manaInt}/${state.ultManaCost}`);
    setTextCached(hudUltCalloutText, `[Q] ${state.ultName} · Charge to ${state.ultManaCost} MP`);
  }

  // Active Item Readout & Reload Progress Bar (Bottom-Right — weapons & equipment only)
  const setActiveColor = (color: string): void => {
    if (lastActiveNameColor !== color) {
      lastActiveNameColor = color;
      activeItemName.style.color = color;
    }
  };
  if (!active) {
    if (isUnarmed) {
      setTextCached(activeItemName, 'Unarmed');
      setActiveColor('#FBBC04');
      setTextCached(activeItemAmmo, 'NO WEAPON');
    } else {
      setTextCached(activeItemName, 'Empty Slot');
      setActiveColor('#9AA0A6');
      setTextCached(activeItemAmmo, '—');
    }
    reloadBarWrap.classList.add('hidden');
  } else if (active.kind === 'weapon') {
    const w = WEAPONS[active.id as WeaponId];
    setTextCached(activeItemName, `${RARITY_CONFIG[active.rarity].label} ${w.name} · ${w.skinName}`);
    setActiveColor(RARITY_CONFIG[active.rarity].colorCss);
    if (state.isReloading) {
      setTextCached(activeItemAmmo, 'RELOADING...');
      reloadBarWrap.classList.remove('hidden');
      setWidthCached(reloadBarFill, `${Math.max(0, Math.min(100, state.reloadProgress * 100)).toFixed(1)}%`);
    } else {
      setTextCached(activeItemAmmo, `${active.ammo ?? 0} / ${w.magSize}`);
      reloadBarWrap.classList.add('hidden');
    }
  } else {
    const it = UTILITY_ITEMS[active.id as UtilityItemId];
    setTextCached(activeItemName, `${RARITY_CONFIG[active.rarity].label} ${it.name}`);
    setActiveColor(RARITY_CONFIG[active.rarity].colorCss);
    const channelTxt = it.channelTime > 0 ? ` · ${it.channelTime}s` : '';
    setTextCached(activeItemAmmo, `x${active.count ?? 1}${channelTxt}`);
    reloadBarWrap.classList.add('hidden');
  }

  // 5-Slot Rarity-Bordered Hotbar (Bottom-Right)
  const hotbarSig =
    `${state.activeSlot}|` +
    state.slots.map((s) => (s ? `${s.kind}:${s.id}:${s.rarity}:${s.ammo ?? ''}:${s.count ?? ''}` : '_')).join('|');

  if (hotbarSig !== lastHotbarSig) {
    lastHotbarSig = hotbarSig;
    hotbarEl.innerHTML = '';
    state.slots.forEach((slot, idx) => {
      const div = document.createElement('div');
      const rarityClass = slot ? `rarity-${slot.rarity}` : '';
      div.className = `hotbar-slot ${rarityClass} ${idx === state.activeSlot ? 'active' : ''}`;

      if (!slot) {
        div.innerHTML = `
          <span class="slot-num">${idx + 1}</span>
          <span class="slot-name" style="opacity:0.4">Empty</span>
        `;
      } else if (slot.kind === 'weapon') {
        const w = WEAPONS[slot.id as WeaponId];
        div.innerHTML = `
          <span class="slot-num">${idx + 1}</span>
          <span class="slot-icon">${WEAPON_SVGS[w.id]}</span>
          <span class="slot-name">${w.shortName}</span>
          <span class="slot-count">${slot.ammo ?? 0}</span>
        `;
      } else {
        const it = UTILITY_ITEMS[slot.id as UtilityItemId];
        div.innerHTML = `
          <span class="slot-num">${idx + 1}</span>
          <span class="slot-icon">${UTILITY_SVGS[it.id]}</span>
          <span class="slot-name">${it.shortName}</span>
          <span class="slot-count">x${slot.count ?? 1}</span>
        `;
      }

      hotbarEl.appendChild(div);
    });
  }
}

// ==================== ENGINE INITIALIZATION ====================
const hudCallbacks: HudCallbacks = {
  onHudUpdate: renderHud,
  onKillFeed: pushKillFeed,
  onHitMarker: (isHeadshot, isKill) => {
    hitmarkerEl.classList.add('show');
    hitmarkerEl.classList.toggle('crit', isHeadshot);
    clearTimeout(hitmarkerTimer);
    hitmarkerTimer = window.setTimeout(() => {
      hitmarkerEl.classList.remove('show', 'crit');
    }, isHeadshot ? 190 : 120);

    if (isHeadshot || isKill) {
      critFlashEl.textContent = isHeadshot && isKill ? 'HEADSHOT ELIM!' : isHeadshot ? 'HEADSHOT' : 'ELIMINATED';
      critFlashEl.classList.add('show');
      clearTimeout(critFlashTimer);
      critFlashTimer = window.setTimeout(() => critFlashEl.classList.remove('show'), 460);
    }
  },
  onFloatingDamage: spawnFloatingDamage,
  onDirectionalDamage: spawnDirectionalDamageArc,
  onAnnouncement: showBanner,
  onPointerLockChange: (locked) => {
    if (splashActive) return;
    if (!lobbyOverlay.classList.contains('hidden')) return;
    if (!gameoverOverlay.classList.contains('hidden')) return;
    if (isFullMapOpen || engine.isMapOpen()) {
      pauseOverlay.classList.add('hidden');
      return;
    }
    pauseOverlay.classList.toggle('hidden', locked);
  },
  onMatchEnd: (summary: MatchSummary) => {
    currentMatchPhase = 'ended';
    splashActive = false;
    stopSplashUiTicker();
    splashOverlay.classList.remove('active');
    splashOverlay.classList.add('hidden');
    setInMatchSettingsMode(false);
    closeFullMap(false);
    engine.setMapOpen(false);
    lobbyOverlay.classList.add('hidden');
    pauseOverlay.classList.add('hidden');
    sniperScopeOverlay.classList.add('hidden');
    gameoverOverlay.classList.remove('hidden');

    const mode = GAME_MODES[summary.gameMode] ?? GAME_MODES.battle_royale;
    const goModeEl = document.getElementById('go-mode')!;
    goModeEl.textContent = mode.name;
    goModeEl.style.color = `color-mix(in srgb, ${mode.accentCss} 50%, #1F1F1F)`;

    const goPlacement = document.getElementById('go-placement')!;
    goPlacement.textContent = `#${summary.placement} / ${summary.totalPlayers}`;
    goPlacement.classList.toggle('is-victory', summary.won);
    goPlacement.classList.toggle('is-eliminated', !summary.won);

    document.getElementById('go-title')!.textContent = summary.won ? 'Victory Royale!' : 'Eliminated';
    document.getElementById('go-subtitle')!.textContent = summary.won
      ? `${summary.heroPersona} conquered ${mode.name} at the Mountain View Googleplex.`
      : `Finished #${summary.placement} of ${summary.totalPlayers} in ${mode.name}.`;
    document.getElementById('go-hero')!.textContent = summary.heroPersona;
    document.getElementById('go-elims')!.textContent = String(summary.eliminations);
    document.getElementById('go-headshots')!.textContent = String(summary.headshots);
    document.getElementById('go-damage')!.textContent = String(Math.round(summary.damageDealt));

    const totalSec = Math.max(0, Math.floor(summary.survivedSeconds));
    const mins = Math.floor(totalSec / 60);
    const secs = String(totalSec % 60).padStart(2, '0');
    document.getElementById('go-time')!.textContent = `${mins}:${secs}`;
    document.getElementById('go-difficulty')!.textContent = formatDifficultyLabel(summary.botDifficulty);
  },
};

const engine = new WorkspaceRoyaleEngine(gameViewport, hudCallbacks, sharedAssetManager);
const showcase = new LobbyHeroShowcase(previewCanvas, previewStage, engine.assetManager);

// ==================== LIVE 3D SPLASH SCREEN FLOW & SCENE TICKER ====================
function bindSplashSceneBarElements(): void {
  splashSceneBarButtons = Array.from(
    splashSceneBars.querySelectorAll<HTMLButtonElement>('.splash-scene-bar')
  );
  splashSceneBarFills = splashSceneBarButtons.map(
    (btn) => btn.querySelector<HTMLElement>('.splash-scene-bar-fill')!
  );
  splashSceneBarButtons.forEach((btn, idx) => {
    btn.onclick = () => {
      engine.setSplashScene(idx);
      updateSplashSceneUi();
      btn.blur();
    };
  });
}

function rebuildSplashSceneBars(count: number): void {
  splashSceneBars.innerHTML = '';
  for (let i = 0; i < count; i++) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'splash-scene-bar';
    btn.dataset.sceneIndex = String(i);
    btn.setAttribute('aria-label', `Preview segment ${i + 1}`);
    btn.setAttribute('aria-current', 'false');
    btn.innerHTML =
      '<span class="splash-scene-bar-track"><span class="splash-scene-bar-fill"></span></span>';
    splashSceneBars.appendChild(btn);
  }
  bindSplashSceneBarElements();
}

function updateSplashSceneUi(): void {
  const state = engine.getSplashAttractState();
  if (!state.scenes || state.scenes.length === 0) return;
  const totalScenes = state.scenes.length;
  const clampedIdx = Math.max(0, Math.min(totalScenes - 1, state.sceneIndex));
  const progressClamped = Math.max(0, Math.min(1, state.sceneProgress));

  if (splashSceneBarButtons.length !== totalScenes) {
    rebuildSplashSceneBars(totalScenes);
  }

  for (let i = 0; i < splashSceneBarButtons.length; i++) {
    const btn = splashSceneBarButtons[i];
    const fill = splashSceneBarFills[i];
    const isCurrent = i === clampedIdx;
    const isPast = i < clampedIdx;
    btn.classList.toggle('is-active', isCurrent);
    btn.classList.toggle('is-complete', isPast);
    btn.setAttribute('aria-current', isCurrent ? 'true' : 'false');

    const fillPct = isPast ? 100 : isCurrent ? progressClamped * 100 : 0;
    setWidthCached(fill, `${fillPct.toFixed(1)}%`);
  }
}

function stopSplashUiTicker(): void {
  if (splashTickerRafId !== 0) {
    cancelAnimationFrame(splashTickerRafId);
    splashTickerRafId = 0;
  }
}

function startSplashUiTicker(): void {
  if (splashTickerRafId !== 0) return;
  const tick = (): void => {
    if (!splashActive) {
      splashTickerRafId = 0;
      return;
    }
    updateSplashSceneUi();
    splashTickerRafId = requestAnimationFrame(tick);
  };
  splashTickerRafId = requestAnimationFrame(tick);
}

function enterHomeFromSplash(): void {
  if (!assetsReady) return;
  splashActive = false;
  stopSplashUiTicker();
  engine.stopSplashAttract();
  splashOverlay.classList.remove('active');
  splashOverlay.classList.add('hidden');
  lobbyOverlay.classList.remove('hidden');
  lobbyOverlay.classList.add('active');
  navigateMenu('home');
  if (showcase.getLoadedHeroId() !== selectedHeroId) {
    showcase.setHero(selectedHeroId);
  }
  showcase.setActive(true);
  showcase.syncSize();
  requestAnimationFrame(() => showcase.syncSize());
}

function quickPlayFromSplash(): void {
  if (!assetsReady) return;
  splashActive = false;
  stopSplashUiTicker();
  engine.stopSplashAttract();
  splashOverlay.classList.remove('active');
  splashOverlay.classList.add('hidden');
  launchMatch();
}

function openSplashFromMenu(): void {
  if (settingsReturnTarget === 'pause') return;
  if (currentMatchPhase !== 'lobby') return;
  splashActive = true;
  lobbyOverlay.classList.add('hidden');
  lobbyOverlay.classList.remove('active');
  showcase.setActive(false);
  splashOverlay.classList.remove('hidden');
  splashOverlay.classList.add('active');
  if (assetsReady) {
    splashPreloadVeil.classList.add('is-ready');
  }
  engine.startSplashAttract();
  updateSplashSceneUi();
  startSplashUiTicker();
}

// ==================== BOOTSTRAP MENU, SETTINGS & ASSET PRELOAD ====================
bindSplashSceneBarElements();
renderModeSelector();
renderHeroSelector();
bindSettingsControls();
setActiveSettingsTab('gameplay');
engine.applySettings(currentSettings);
syncSettingsUi();
syncPerfHudVisibility();
updateHeroDetails();
navigateMenu('home');

// Initial landing view = Live 3D Splash Screen (keep LobbyHeroShowcase paused while Splash is visible)
splashActive = true;
showcase.setActive(false);
lobbyOverlay.classList.add('hidden');
lobbyOverlay.classList.remove('active');
splashOverlay.classList.remove('hidden');
splashOverlay.classList.add('active');
engine.startSplashAttract();
updateSplashSceneUi();
startSplashUiTicker();

function handleLoadProgress(p: LoadingProgress): void {
  if (p.total > 0) {
    lastPreloadTotal = p.total;
  }
  const pct = Math.round(Math.max(0, Math.min(1, p.ratio)) * 100);
  lastLoadPct = pct;

  preloadPct.textContent = `${pct}%`;
  preloadFill.style.width = `${pct}%`;
  preloadLabel.textContent =
    pct >= 100
      ? `All ${p.total} 3D Mountain View campus assets loaded`
      : `Loading ${p.label} (${p.loaded}/${p.total})`;

  setWidthCached(splashPreloadFill, `${pct}%`);
  splashPreloadProgressbar.setAttribute('aria-valuenow', String(pct));
  setTextCached(splashPreloadPct, `${pct}%`);
  setTextCached(
    splashPreloadCaption,
    pct >= 100
      ? `Mountain View Campus Ready · ${p.total}/${p.total}`
      : `Loading Mountain View Campus · ${p.loaded}/${p.total}`
  );

  if (!assetsReady) {
    assetChipText.textContent = `Loading 3D assets ${pct}%`;
    chipMiniFill.style.width = `${pct}%`;
    setTextCached(splashAssetBadge, `Loading 3D ${pct}%`);
    updatePlayButtons();
  }

  // Hero-first showcase preview: prepare hero turntable silently without rendering during Splash
  if (showcase.getLoadedHeroId() !== selectedHeroId) {
    const heroDef = HERO_MAP[selectedHeroId];
    const ready =
      engine.assetManager.isHeroReady(selectedHeroId) &&
      (!heroDef.lobbyWeaponId || engine.assetManager.isWeaponReady(heroDef.lobbyWeaponId));
    if (ready) {
      showcase.setHero(selectedHeroId);
    }
  }
}

engine
  .preloadAssets(handleLoadProgress)
  .then(() => {
    assetsReady = true;
    lastLoadPct = 100;
    assetPreloadBar.classList.add('ready');
    preloadPct.textContent = '100%';
    preloadFill.style.width = '100%';
    const totalCount = lastPreloadTotal || 50;
    preloadLabel.textContent = `All ${totalCount} 3D Mountain View campus assets loaded`;
    assetStatusChip.classList.add('ready');
    assetChipText.textContent = `Ready · ${totalCount} assets`;
    chipMiniFill.style.width = '100%';

    setWidthCached(splashPreloadFill, '100%');
    splashPreloadProgressbar.setAttribute('aria-valuenow', '100');
    setTextCached(splashPreloadPct, '100%');
    setTextCached(splashPreloadCaption, `Mountain View Campus Ready · ${totalCount}/${totalCount}`);
    splashPreloadVeil.classList.add('is-ready');
    splashAssetBadge.classList.add('ready');
    setTextCached(splashAssetBadge, `${totalCount} 3D Assets Ready`);

    updatePlayButtons();
    if (splashActive) {
      updateSplashSceneUi();
    }
    if (showcase.getLoadedHeroId() !== selectedHeroId) {
      showcase.setHero(selectedHeroId);
    }
  })
  .catch((err) => {
    console.error('[WorkspaceRoyale] Asset preload error:', err);
    assetsReady = true;
    lastLoadPct = 100;
    assetPreloadBar.classList.add('ready');
    assetStatusChip.classList.add('ready');
    assetChipText.textContent = 'Ready · Fallback assets';
    splashPreloadVeil.classList.add('is-ready');
    splashAssetBadge.classList.add('ready');
    setTextCached(splashAssetBadge, 'Campus Ready');
    updatePlayButtons();
    if (splashActive) {
      updateSplashSceneUi();
    }
    if (showcase.getLoadedHeroId() !== selectedHeroId) {
      showcase.setHero(selectedHeroId);
    }
  });

// ==================== MATCH FLOW CONTROLS ====================
function launchMatch(): void {
  if (!assetsReady) return;
  const mode = GAME_MODES[selectedModeId] ?? GAME_MODES.battle_royale;
  const hero = HERO_MAP[selectedHeroId];
  pauseMatchPill.textContent = `${mode.name} · ${hero.personaName}`;

  splashActive = false;
  stopSplashUiTicker();
  if (engine.getSplashAttractState().active) {
    engine.stopSplashAttract();
  }
  splashOverlay.classList.remove('active');
  splashOverlay.classList.add('hidden');
  setInMatchSettingsMode(false);
  closeFullMap(false);
  lobbyOverlay.classList.add('hidden');
  lobbyOverlay.classList.remove('active');
  gameoverOverlay.classList.add('hidden');
  pauseOverlay.classList.add('hidden');
  sniperScopeOverlay.classList.add('hidden');
  showcase.setActive(false);
  hudEl.classList.remove('hidden');
  killFeedEl.innerHTML = '';
  damageArcLayer.innerHTML = '';
  lastHotbarSig = '';
  lastStatusSig = '';
  lastPerfSig = '';
  lastHeroHudId = null;
  lastHudModeId = null;
  lastMinimapRenderMs = 0;
  lastFullMapRenderMs = 0;
  lastPerfUpdateMs = 0;
  currentMatchPhase = 'skydrop';
  syncPerfHudVisibility();
  engine.applySettings(currentSettings);
  engine.startMatch(selectedHeroId, currentSettings.botDifficulty, selectedModeId);
}

function returnToLobby(targetPage: MenuPage = 'home'): void {
  currentMatchPhase = 'lobby';
  splashActive = false;
  stopSplashUiTicker();
  splashOverlay.classList.remove('active');
  splashOverlay.classList.add('hidden');
  setInMatchSettingsMode(false);
  closeFullMap(false);
  engine.pauseToLobby();
  engine.setMapOpen(false);
  hudEl.classList.add('hidden');
  pauseOverlay.classList.add('hidden');
  gameoverOverlay.classList.add('hidden');
  sniperScopeOverlay.classList.add('hidden');
  lobbyOverlay.classList.remove('hidden');
  lobbyOverlay.classList.add('active');
  navigateMenu(targetPage);
  if (showcase.getLoadedHeroId() !== selectedHeroId) {
    showcase.setHero(selectedHeroId);
  }
}

// ==================== MENU NAVIGATION & BUTTON BINDINGS ====================
btnSplashStart.addEventListener('click', enterHomeFromSplash);
btnSplashQuickplay.addEventListener('click', quickPlayFromSplash);
btnSplashMute.addEventListener('click', () => {
  applyAndSaveSettings({ muted: !currentSettings.muted });
  btnSplashMute.blur();
});

navBrandHome.addEventListener('click', () => {
  if (settingsReturnTarget === 'pause') return;
  navigateMenu('home');
});

document.querySelectorAll<HTMLButtonElement>('.menu-tab').forEach((tab) => {
  tab.addEventListener('click', () => {
    const page = tab.dataset.page as MenuPage | undefined;
    if (!page) return;
    navigateMenu(page);
  });
});

btnTopbarSplash.addEventListener('click', openSplashFromMenu);

btnTopbarSettings.addEventListener('click', () => {
  if (settingsReturnTarget === 'pause') return;
  navigateMenu('settings');
});

homeCardMode.addEventListener('click', () => navigateMenu('modes'));
homeCardHero.addEventListener('click', () => navigateMenu('characters'));
homeCardSettings.addEventListener('click', () => navigateMenu('settings', 'gameplay'));
homeBtnControls.addEventListener('click', () => navigateMenu('settings', 'controls'));
btnHomeCustomize.addEventListener('click', () => navigateMenu('characters'));

btnModesBack.addEventListener('click', () => navigateMenu('home'));
btnCharsBack.addEventListener('click', () => navigateMenu('home'));

btnHomePlay.addEventListener('click', launchMatch);
btnModesPlay.addEventListener('click', launchMatch);
btnCharsPlay.addEventListener('click', launchMatch);
btnFlipPreview.addEventListener('click', () => showcase.flipFrontBack());

// Pause & Game Over Actions
document.getElementById('btn-resume')!.addEventListener('click', () => {
  pauseOverlay.classList.add('hidden');
  engine.requestPointerLock();
});
document.getElementById('btn-pause-settings')!.addEventListener('click', () => {
  openSettingsFromPause('gameplay');
});
document.getElementById('btn-pause-controls')!.addEventListener('click', () => {
  openSettingsFromPause('controls');
});
document.getElementById('btn-back-lobby')!.addEventListener('click', () => returnToLobby('home'));

document.getElementById('btn-play-again')!.addEventListener('click', launchMatch);
document.getElementById('btn-change-hero')!.addEventListener('click', () => returnToLobby('characters'));
document.getElementById('btn-gameover-home')!.addEventListener('click', () => returnToLobby('home'));

// Full Tactical Map [M] Click-to-Ping Waypoint & Close Controls
fullmapCanvas.addEventListener('mousedown', (e) => {
  if (!isFullMapOpen) return;
  if (e.button === 0) {
    e.preventDefault();
    const { x, z } = TacticalMinimap.canvasToWorld(fullmapCanvas, e.clientX, e.clientY);
    engine.setWaypoint(x, z);
    renderFullMapImmediate();
  }
});

fullmapCanvas.addEventListener('contextmenu', (e) => {
  e.preventDefault();
  if (!isFullMapOpen) return;
  engine.clearWaypoint();
  renderFullMapImmediate();
});

btnClearWaypoint.addEventListener('click', (e) => {
  e.stopPropagation();
  engine.clearWaypoint();
  renderFullMapImmediate();
});

btnCloseFullmap.addEventListener('click', () => {
  closeFullMap(true);
});

fullmapOverlay.addEventListener('click', (e) => {
  if (e.target === fullmapOverlay && isFullMapOpen) {
    closeFullMap(true);
  }
});

// ==================== GLOBAL KEYBOARD HANDLING ====================
window.addEventListener('keydown', (e) => {
  // 0. Live 3D Splash Screen Keyboard Navigation (blocks menu & match hotkeys cleanly)
  if (splashActive) {
    if (e.ctrlKey || e.metaKey || e.altKey) return;

    if (e.key === 'Enter' || e.code === 'Space' || e.key === ' ') {
      const activeEl = document.activeElement;
      if (activeEl === btnSplashQuickplay || activeEl === btnSplashMute) {
        return;
      }
      if (assetsReady) {
        e.preventDefault();
        enterHomeFromSplash();
      }
      return;
    }

    if (e.key >= '1' && e.key <= '4') {
      const state = engine.getSplashAttractState();
      const idx = Number(e.key) - 1;
      if (state.scenes.length > 0 && idx >= 0 && idx < state.scenes.length) {
        e.preventDefault();
        engine.setSplashScene(idx);
        updateSplashSceneUi();
      }
      return;
    }

    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
      const state = engine.getSplashAttractState();
      const count = state.scenes.length;
      if (count > 0) {
        const delta = e.key === 'ArrowRight' ? 1 : -1;
        const nextIdx = (state.sceneIndex + delta + count) % count;
        e.preventDefault();
        engine.setSplashScene(nextIdx);
        updateSplashSceneUi();
      }
      return;
    }

    return;
  }

  // 1. Multi-Page Menu Shell Keyboard Navigation
  if (!lobbyOverlay.classList.contains('hidden')) {
    if (e.key === 'Escape') {
      e.preventDefault();
      if (settingsReturnTarget === 'pause') {
        closeSettingsToPause();
      } else if (activeMenuPage !== 'home') {
        navigateMenu('home');
      }
      return;
    }

    const targetEl = e.target as HTMLElement | null;
    const isFormInput =
      targetEl instanceof HTMLInputElement ||
      targetEl instanceof HTMLTextAreaElement ||
      targetEl instanceof HTMLSelectElement;
    if (isFormInput) return;

    // Keys 1-6 preview Characters on the Characters page
    if (activeMenuPage === 'characters') {
      const idx = Number(e.key) - 1;
      if (idx >= 0 && idx < PRODUCT_HEROES.length) {
        selectedHeroId = PRODUCT_HEROES[idx].id;
        renderHeroSelector();
        updateHeroDetails();
        return;
      }
    }

    // Enter launches match from Home / Modes / Characters (NEVER on Settings or when activating a focused button)
    if (e.key === 'Enter' && assetsReady && activeMenuPage !== 'settings' && settingsReturnTarget !== 'pause') {
      const activeEl = document.activeElement;
      const isInteractiveFocus =
        activeEl instanceof HTMLButtonElement ||
        activeEl instanceof HTMLInputElement ||
        activeEl instanceof HTMLAnchorElement ||
        activeEl instanceof HTMLSelectElement;
      if (!isInteractiveFocus) {
        launchMatch();
      }
    }
    return;
  }

  // 2. Game Over active -> ignore map hotkeys
  if (!gameoverOverlay.classList.contains('hidden')) return;

  // 3. ESC closes Full Tactical Map cleanly and resumes pointer lock
  if (e.key === 'Escape' && isFullMapOpen) {
    e.preventDefault();
    e.stopPropagation();
    closeFullMap(true);
    return;
  }

  // 4. Press M during Sky-Drop or active gameplay to toggle Full Tactical Map Overlay
  if (e.code === 'KeyM' && !e.repeat && !e.ctrlKey && !e.metaKey && !e.altKey) {
    if (isFullMapOpen) {
      e.preventDefault();
      closeFullMap(true);
    } else if (
      pauseOverlay.classList.contains('hidden') &&
      (currentMatchPhase === 'skydrop' || currentMatchPhase === 'playing')
    ) {
      e.preventDefault();
      openFullMap();
    }
  }
});

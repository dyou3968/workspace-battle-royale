import { BotDifficulty, BotDifficultyProfile, BotTier } from '../types';

export const BOT_PROFILES: Record<BotTier, BotDifficultyProfile> = {
  casual: {
    tier: 'casual',
    label: 'Casual (Intern)',
    shortLabel: 'Casual',
    description: 'Relaxed aim scatter (±2.4m), slower 550ms reaction, fights in the open, late storm rotation.',
    aimErrorRad: 0.082,
    aimScatterMeters: 2.4,
    leadFactor: 0.15,
    headshotBias: 0.03,
    reactionTime: 0.55,
    engagementRange: 68,
    fireCadenceMult: 0.62,
    strafeIntensity: 0.35,
    crouchPeekChance: 0.05,
    useCoverChance: 0.1,
    deployHardlightChance: 0.0,
    useImpulseChance: 0.0,
    healThresholdRatio: 0.35,
    healInCover: false,
    contestSupplyDrop: false,
    supplyDropPriority: 0.08,
    lootUpgradeDesire: 0.32,
    hotDropBias: 0.15,
    thirdPartyAggression: 0.1,
    stormRotateLeadSec: 0,
    preRotateNextZone: false,
    ultimateSmartness: 'basic',
  },
  tactical: {
    tier: 'tactical',
    label: 'Tactical (Staff)',
    shortLabel: 'Tactical',
    description: 'Accurate lead aim (±1.1m, 300ms reaction), cover peeking, smart healing, contextual Ultimates.',
    aimErrorRad: 0.037,
    aimScatterMeters: 1.1,
    leadFactor: 0.72,
    headshotBias: 0.1,
    reactionTime: 0.3,
    engagementRange: 98,
    fireCadenceMult: 0.86,
    strafeIntensity: 0.78,
    crouchPeekChance: 0.42,
    useCoverChance: 0.68,
    deployHardlightChance: 0.38,
    useImpulseChance: 0.25,
    healThresholdRatio: 0.6,
    healInCover: true,
    contestSupplyDrop: true,
    supplyDropPriority: 0.55,
    lootUpgradeDesire: 0.76,
    hotDropBias: 0.48,
    thirdPartyAggression: 0.45,
    stormRotateLeadSec: 12,
    preRotateNextZone: false,
    ultimateSmartness: 'contextual',
  },
  pro: {
    tier: 'pro',
    label: 'Pro (Distinguished)',
    shortLabel: 'Pro',
    description: 'Tight aim (±0.45m, 140ms reaction, 22% headshots), Supply Drop contesting, Hard-Light Cover & combo Ultimates.',
    aimErrorRad: 0.015,
    aimScatterMeters: 0.45,
    leadFactor: 1.0,
    headshotBias: 0.22,
    reactionTime: 0.14,
    engagementRange: 138,
    fireCadenceMult: 1.0,
    strafeIntensity: 1.0,
    crouchPeekChance: 0.74,
    useCoverChance: 0.95,
    deployHardlightChance: 0.85,
    useImpulseChance: 0.75,
    healThresholdRatio: 0.68,
    healInCover: true,
    contestSupplyDrop: true,
    supplyDropPriority: 0.95,
    lootUpgradeDesire: 0.98,
    hotDropBias: 0.82,
    thirdPartyAggression: 0.9,
    stormRotateLeadSec: 24,
    preRotateNextZone: true,
    ultimateSmartness: 'optimal',
  },
};

export interface BotDifficultyOption {
  id: BotDifficulty;
  label: string;
  badge: string;
  summary: string;
}

export const BOT_DIFFICULTY_OPTIONS: BotDifficultyOption[] = [
  {
    id: 'casual',
    label: 'Casual (Intern)',
    badge: 'L3',
    summary: 'Wide scatter (±2.4m), 550ms reaction, open-field duels, casual looting.',
  },
  {
    id: 'tactical',
    label: 'Tactical (Staff)',
    badge: 'L6',
    summary: 'Velocity-lead aim (±1.1m), cover peeking & heals, contextual Ultimates.',
  },
  {
    id: 'pro',
    label: 'Pro (Distinguished)',
    badge: 'L9',
    summary: '22% headshot crits, 140ms reaction, Supply Drop contests, Hard-Light Cover & combos.',
  },
  {
    id: 'mixed',
    label: 'Mixed Lobby',
    badge: 'MIX',
    summary: 'Balanced lobby distribution: 30% Casual · 45% Tactical · 25% Pro.',
  },
];

/**
 * Assign concrete BotTier values across `botCount` AI combatants.
 * For 'mixed', deterministically distributes 30% Casual / 45% Tactical / 25% Pro and shuffles.
 */
export function assignBotTiers(difficulty: BotDifficulty, botCount: number): BotTier[] {
  if (difficulty !== 'mixed') {
    return Array.from({ length: botCount }, () => difficulty);
  }
  const casualCount = Math.max(1, Math.round(botCount * 0.3));
  const proCount = Math.max(1, Math.round(botCount * 0.25));
  const tacticalCount = Math.max(0, botCount - casualCount - proCount);
  const tiers: BotTier[] = [
    ...Array.from({ length: casualCount }, (): BotTier => 'casual'),
    ...Array.from({ length: tacticalCount }, (): BotTier => 'tactical'),
    ...Array.from({ length: proCount }, (): BotTier => 'pro'),
  ];
  // Fisher-Yates shuffle
  for (let i = tiers.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [tiers[i], tiers[j]] = [tiers[j], tiers[i]];
  }
  return tiers.slice(0, botCount);
}

export function getBotProfile(tier: BotTier): BotDifficultyProfile {
  return BOT_PROFILES[tier];
}

import { ChestTier, ProductHeroId, Rarity, UtilityItemId, WeaponId } from '../types';

export class SoundEngine {
  private ctx: AudioContext | null = null;
  private masterGain: GainNode | null = null;
  private noiseBuffer: AudioBuffer | null = null;
  private gliderWindGain: GainNode | null = null;
  private gliderWindFilter: BiquadFilterNode | null = null;
  private gliderWindActive = false;
  private masterVolume = 1.0;
  public muted = false;

  private ensureContext(): AudioContext | null {
    if (this.muted) return null;
    if (!this.ctx) {
      const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      if (!AudioCtx) return null;
      this.ctx = new AudioCtx();

      const compressor = this.ctx.createDynamicsCompressor();
      compressor.threshold.setValueAtTime(-14, this.ctx.currentTime);
      compressor.knee.setValueAtTime(18, this.ctx.currentTime);
      compressor.ratio.setValueAtTime(6, this.ctx.currentTime);
      compressor.attack.setValueAtTime(0.004, this.ctx.currentTime);
      compressor.release.setValueAtTime(0.14, this.ctx.currentTime);

      this.masterGain = this.ctx.createGain();
      this.masterGain.gain.setValueAtTime(0.42 * this.masterVolume, this.ctx.currentTime);
      this.masterGain.connect(compressor);
      compressor.connect(this.ctx.destination);

      this.noiseBuffer = this.createNoiseBuffer(this.ctx, 2.0);
    }
    if (this.ctx.state === 'suspended') {
      this.ctx.resume().catch(() => {});
    }
    return this.ctx;
  }

  public unlock(): void {
    this.ensureContext();
  }

  public setMasterVolume(vol: number): void {
    const clamped = Number.isFinite(vol) ? Math.max(0, Math.min(1, vol)) : 1.0;
    this.masterVolume = clamped;
    if (this.ctx && this.masterGain) {
      const target = this.muted ? 0 : 0.42 * this.masterVolume;
      this.masterGain.gain.setTargetAtTime(target, this.ctx.currentTime, 0.02);
    }
  }

  public getMasterVolume(): number {
    return this.masterVolume;
  }

  public setMuted(muted: boolean): void {
    this.muted = muted;
    if (muted) {
      this.setGliderWind(false);
      if (this.ctx && this.masterGain) {
        const now = this.ctx.currentTime;
        this.masterGain.gain.cancelScheduledValues(now);
        this.masterGain.gain.setValueAtTime(0, now);
      }
    } else if (this.ctx && this.masterGain) {
      const now = this.ctx.currentTime;
      this.masterGain.gain.cancelScheduledValues(now);
      this.masterGain.gain.setTargetAtTime(0.42 * this.masterVolume, now, 0.02);
    }
  }

  private createNoiseBuffer(ctx: AudioContext, seconds: number): AudioBuffer {
    const length = Math.floor(ctx.sampleRate * seconds);
    const buffer = ctx.createBuffer(1, length, ctx.sampleRate);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < length; i++) {
      data[i] = Math.random() * 2 - 1;
    }
    return buffer;
  }

  private spatialGain(distance = 0, maxDistance = 120): number {
    if (distance <= 3) return 1.0;
    if (distance >= maxDistance) return 0.0;
    const t = 1 - distance / maxDistance;
    return t * t;
  }

  private createPanDestination(ctx: AudioContext, pan: number, startTime: number): AudioNode | null {
    if (!this.masterGain) return null;
    if (!Number.isFinite(pan) || pan === 0 || typeof ctx.createStereoPanner !== 'function') {
      return this.masterGain;
    }
    const clamped = Math.max(-0.92, Math.min(0.92, pan));
    if (Math.abs(clamped) < 0.005) {
      return this.masterGain;
    }
    const panner = ctx.createStereoPanner();
    panner.pan.setValueAtTime(clamped, Math.max(ctx.currentTime, startTime));
    panner.connect(this.masterGain);
    return panner;
  }

  private playTone(
    type: OscillatorType,
    startFreq: number,
    endFreq: number,
    duration: number,
    gainPeak: number,
    delay = 0,
    pan = 0
  ): void {
    const ctx = this.ensureContext();
    if (!ctx || !this.masterGain || gainPeak <= 0.001) return;
    const now = ctx.currentTime + delay;
    const dest = this.createPanDestination(ctx, pan, now);
    if (!dest) return;
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(Math.max(20, startFreq), now);
    osc.frequency.exponentialRampToValueAtTime(Math.max(20, endFreq), now + duration);
    g.gain.setValueAtTime(0.0001, now);
    g.gain.linearRampToValueAtTime(gainPeak, now + Math.min(0.012, duration * 0.25));
    g.gain.exponentialRampToValueAtTime(0.0001, now + duration);
    osc.connect(g);
    g.connect(dest);
    if (dest !== this.masterGain) {
      osc.onended = () => {
        try {
          dest.disconnect();
        } catch {
          // ignore disconnect race
        }
      };
    }
    osc.start(now);
    osc.stop(now + duration + 0.02);
  }

  private playNoise(
    filterType: BiquadFilterType,
    freqStart: number,
    freqEnd: number,
    q: number,
    duration: number,
    gainPeak: number,
    delay = 0,
    pan = 0
  ): void {
    const ctx = this.ensureContext();
    if (!ctx || !this.masterGain || !this.noiseBuffer || gainPeak <= 0.001) return;
    const now = ctx.currentTime + delay;
    const dest = this.createPanDestination(ctx, pan, now);
    if (!dest) return;
    const src = ctx.createBufferSource();
    src.buffer = this.noiseBuffer;

    const filter = ctx.createBiquadFilter();
    filter.type = filterType;
    filter.Q.setValueAtTime(q, now);
    filter.frequency.setValueAtTime(Math.max(40, freqStart), now);
    filter.frequency.exponentialRampToValueAtTime(Math.max(40, freqEnd), now + duration);

    const g = ctx.createGain();
    g.gain.setValueAtTime(0.0001, now);
    g.gain.linearRampToValueAtTime(gainPeak, now + Math.min(0.008, duration * 0.2));
    g.gain.exponentialRampToValueAtTime(0.0001, now + duration);

    src.connect(filter);
    filter.connect(g);
    g.connect(dest);
    if (dest !== this.masterGain) {
      src.onended = () => {
        try {
          dest.disconnect();
        } catch {
          // ignore disconnect race
        }
      };
    }
    src.start(now, Math.random() * 0.8);
    src.stop(now + duration + 0.03);
  }

  public playShot(weaponId: WeaponId, distance = 0, pan = 0): void {
    const atten = this.spatialGain(distance, weaponId === 'longbow_308' ? 190 : 125);
    if (atten <= 0.015) return;

    switch (weaponId) {
      case 'vanguard_m4':
        // Crisp 5.56mm carbine snap + tight low punch
        this.playNoise('bandpass', 2400, 680, 1.1, 0.11, 0.42 * atten, 0, pan);
        this.playTone('triangle', 210, 58, 0.09, 0.34 * atten, 0, pan);
        this.playTone('sawtooth', 980, 260, 0.04, 0.12 * atten, 0, pan);
        break;
      case 'breaker_12g':
        // Thunderous 12-gauge blast + mechanical forend tail
        this.playNoise('lowpass', 1900, 240, 0.7, 0.24, 0.68 * atten, 0, pan);
        this.playTone('sine', 135, 34, 0.22, 0.62 * atten, 0, pan);
        this.playNoise('highpass', 1800, 900, 1.5, 0.06, 0.16 * atten, 0.12, pan);
        break;
      case 'vector_9':
        // Ultra-fast high-RPM PDW crack
        this.playNoise('bandpass', 3200, 1100, 1.4, 0.065, 0.3 * atten, 0, pan);
        this.playTone('square', 360, 120, 0.05, 0.18 * atten, 0, pan);
        break;
      case 'longbow_308':
        // Supersonic .308 sniper crack + deep atmospheric tail
        this.playNoise('highpass', 3600, 820, 0.9, 0.09, 0.56 * atten, 0, pan);
        this.playNoise('lowpass', 1400, 180, 0.6, 0.46, 0.48 * atten, 0.02, pan);
        this.playTone('sawtooth', 260, 42, 0.28, 0.5 * atten, 0, pan);
        this.playTone('triangle', 1450, 920, 0.06, 0.1 * atten, 0.34, pan);
        break;
      case 'nova_gl40':
        // Hollow pneumatic grenade launch "thoomp" + Mana plasma whine
        this.playTone('sine', 155, 48, 0.22, 0.56 * atten, 0, pan);
        this.playNoise('bandpass', 800, 260, 1.8, 0.18, 0.36 * atten, 0, pan);
        this.playTone('sine', 620, 1180, 0.16, 0.16 * atten, 0, pan);
        break;
    }
  }

  public playReload(weaponId?: WeaponId): void {
    const pitch = weaponId === 'longbow_308' ? 0.85 : weaponId === 'vector_9' ? 1.25 : 1.0;
    this.playNoise('bandpass', 2400 * pitch, 1400 * pitch, 3.0, 0.06, 0.16, 0);
    this.playTone('square', 420 * pitch, 260 * pitch, 0.05, 0.09, 0.02);
    this.playNoise('highpass', 3000 * pitch, 1800 * pitch, 2.2, 0.07, 0.18, 0.22);
    this.playTone('triangle', 580 * pitch, 820 * pitch, 0.06, 0.11, 0.25);
  }

  public playDryFire(): void {
    this.playNoise('highpass', 3200, 2200, 4.0, 0.025, 0.15);
    this.playTone('square', 720, 480, 0.02, 0.08);
  }

  /**
   * Crisp body tick, shield ping, or unmistakable metallic headshot "DINK!"
   */
  public playHitmarker(headshot: boolean, shieldHit: boolean): void {
    if (headshot) {
      // Iconic double metallic headshot dink
      this.playTone('sine', 1880, 2120, 0.11, 0.34, 0);
      this.playTone('triangle', 2820, 2450, 0.14, 0.24, 0.012);
      this.playNoise('highpass', 4200, 2800, 2.5, 0.045, 0.18, 0);
      return;
    }
    if (shieldHit) {
      this.playTone('sine', 1120, 1480, 0.075, 0.22);
      this.playNoise('bandpass', 3400, 2200, 3.0, 0.04, 0.12);
    } else {
      this.playNoise('bandpass', 2200, 1400, 2.0, 0.035, 0.2);
      this.playTone('triangle', 740, 480, 0.04, 0.14);
    }
  }

  /**
   * Unmistakable 4-layer crystalline shield shatter SFX.
   * When isDirect === true (player broke an enemy's shield or player's own shield shattered),
   * plays at full punchy gain regardless of distance.
   */
  public playShieldCrack(distance = 0, isDirect = false, pan = 0): void {
    const atten = isDirect ? 1.0 : this.spatialGain(distance, 85);
    if (atten <= 0.015) return;

    // 1. Crisp high-frequency glass shatter bursts (staggered micro-crackles at 0ms, 26ms, 58ms)
    this.playNoise('highpass', 5200, 1600, 1.35, 0.24, 0.44 * atten, 0, pan);
    this.playNoise('highpass', 4800, 1850, 1.8, 0.14, 0.34 * atten, 0.026, pan);
    this.playNoise('highpass', 5400, 2100, 2.1, 0.12, 0.26 * atten, 0.058, pan);

    // 2. Electric shield power-down sweep
    this.playTone('triangle', 2650, 700, 0.24, 0.3 * atten, 0.006, pan);
    this.playTone('sine', 1820, 420, 0.28, 0.28 * atten, 0.014, pan);

    // 3. Punchy low-end pop so cracking a shield hits hard
    this.playTone('sine', 195, 52, 0.18, 0.48 * atten, 0, pan);

    // 4. Sparkling glass-shard tinkle chimes (staggered 20–85ms)
    this.playTone('sine', 3400, 3240, 0.11, 0.16 * atten, 0.02, pan);
    this.playTone('sine', 4180, 3960, 0.12, 0.14 * atten, 0.052, pan);
    this.playTone('sine', 4920, 4680, 0.13, 0.12 * atten, 0.085, pan);
  }

  public playElimination(isPlayerKill = true): void {
    if (isPlayerKill) {
      this.playTone('triangle', 523.25, 523.25, 0.11, 0.22, 0);
      this.playTone('triangle', 659.25, 659.25, 0.12, 0.24, 0.07);
      this.playTone('sine', 1046.5, 1060, 0.24, 0.26, 0.14);
    } else {
      this.playTone('sine', 340, 180, 0.16, 0.12);
    }
  }

  public playExplosion(distance = 0, pan = 0): void {
    const atten = this.spatialGain(distance, 150);
    if (atten <= 0.015) return;
    this.playTone('sine', 110, 24, 0.52, 0.72 * atten, 0, pan);
    this.playNoise('lowpass', 1250, 140, 0.65, 0.62, 0.64 * atten, 0, pan);
    this.playNoise('bandpass', 2400, 420, 1.0, 0.22, 0.28 * atten, 0.02, pan);
  }

  public playPickup(rarity: Rarity = 'common'): void {
    const base = rarity === 'epic' ? 660 : rarity === 'rare' ? 540 : 440;
    this.playTone('sine', base, base * 1.25, 0.09, 0.18, 0);
    this.playTone('triangle', base * 1.25, base * 1.5, 0.12, 0.2, 0.06);
    if (rarity === 'epic') {
      this.playTone('sine', base * 2.0, base * 2.05, 0.2, 0.18, 0.12);
    }
  }

  public playChannelStart(itemId: UtilityItemId): void {
    if (itemId === 'hardlight_cover') {
      this.playTone('sawtooth', 260, 620, 0.18, 0.24);
      this.playTone('sine', 520, 1040, 0.22, 0.2, 0.04);
      return;
    }
    if (itemId === 'impulse_booster') {
      this.playNoise('bandpass', 600, 2600, 1.2, 0.34, 0.38);
      this.playTone('sawtooth', 180, 740, 0.28, 0.3);
      return;
    }
    this.playNoise('bandpass', 1800, 2600, 2.0, 0.12, 0.14);
    this.playTone('sine', 380, 520, 0.12, 0.12);
  }

  public playChannelComplete(itemId: UtilityItemId): void {
    if (itemId === 'shield_cell' || itemId === 'shield_jug') {
      this.playTone('sine', 520, 1040, 0.22, 0.26, 0);
      this.playTone('triangle', 780, 1560, 0.26, 0.2, 0.08);
    } else if (itemId === 'medkit') {
      this.playTone('sine', 440, 554.37, 0.15, 0.22, 0);
      this.playTone('sine', 554.37, 659.25, 0.2, 0.22, 0.1);
      this.playTone('sine', 659.25, 880, 0.26, 0.2, 0.2);
    } else if (itemId === 'mana_elixir') {
      this.playTone('sine', 420, 840, 0.22, 0.24, 0);
      this.playTone('triangle', 630, 1260, 0.28, 0.2, 0.07);
    }
  }

  public playFootstep(
    sprinting: boolean,
    crouching: boolean,
    surface: 'grass' | 'stone' | 'sand' | 'metal' = 'stone',
    distance = 0,
    pan = 0
  ): void {
    const atten = distance > 0 ? this.spatialGain(distance, 34) : 1.0;
    if (atten <= 0.015) return;
    const vol = (crouching ? 0.04 : sprinting ? 0.13 : 0.08) * atten;
    const freq =
      surface === 'metal'
        ? 1600
        : surface === 'stone'
          ? 950
          : surface === 'sand'
            ? 650
            : 520;
    this.playNoise('bandpass', freq, freq * 0.45, 1.4, 0.055, vol, 0, pan);
    this.playTone('sine', 110, 55, 0.045, vol * 0.7, 0, pan);
  }

  /** Iconic bright cheerful double metallic GBike bell: "BRING-BRING!" */
  public playGBikeBell(distance = 0, pan = 0): void {
    const atten = this.spatialGain(distance, 72);
    if (atten <= 0.015) return;

    const ring = (delay: number, durScale: number, gainScale: number): void => {
      // Twin inharmonic metallic brass-bell partials (2480 Hz + 3760 Hz + 5120 Hz)
      this.playTone('sine', 2480, 2472, 0.24 * durScale, 0.28 * gainScale * atten, delay, pan);
      this.playTone('sine', 3760, 3748, 0.19 * durScale, 0.17 * gainScale * atten, delay, pan);
      this.playTone('sine', 5120, 5100, 0.14 * durScale, 0.11 * gainScale * atten, delay, pan);
      // Crisp striker click on thumb flick
      this.playNoise('highpass', 5600, 3200, 3.0, 0.018, 0.11 * gainScale * atten, delay, pan);
    };

    ring(0, 0.92, 0.94);
    ring(0.115, 1.38, 1.08);
  }

  /** Crisp mechanical spring clack + brief chain click when mounting or dismounting a GBike. */
  public playGBikeMount(mounting: boolean): void {
    if (mounting) {
      this.playTone('triangle', 340, 560, 0.085, 0.22, 0);
      this.playNoise('bandpass', 2400, 1500, 2.8, 0.045, 0.15, 0.01);
      this.playTone('square', 1120, 860, 0.032, 0.09, 0.055);
      this.playNoise('highpass', 3600, 2200, 3.2, 0.03, 0.1, 0.055);
    } else {
      this.playTone('triangle', 480, 280, 0.09, 0.2, 0);
      this.playNoise('bandpass', 1900, 980, 2.4, 0.05, 0.14, 0.01);
      this.playTone('square', 840, 580, 0.035, 0.08, 0.06);
      this.playNoise('highpass', 3000, 1700, 3.0, 0.03, 0.09, 0.06);
    }
  }

  /** Subtle soft bicycle tire hum + delicate freewheel/pedal tick while riding a GBike. */
  public playGBikeRollTick(speedRatio: number): void {
    const r = Math.max(0.08, Math.min(1.5, Number.isFinite(speedRatio) ? speedRatio : 0));
    this.playNoise('bandpass', 340 + r * 280, 260 + r * 210, 1.6, 0.085, 0.042 + r * 0.034, 0);
    this.playTone('triangle', 1280 + r * 360, 920 + r * 240, 0.022, 0.03 + r * 0.022, 0);
    this.playNoise('highpass', 3800 + r * 600, 2400, 3.5, 0.016, 0.024 + r * 0.018, 0.008);
  }

  /** Futuristic ascending Google-chime arpeggio when upgrading a weapon at a TechStop. */
  public playTechStopUpgrade(newRarity: Rarity): void {
    if (newRarity === 'epic') {
      // Triumphant 4-note shimmering chord: D5 - F#5 - A5 - D6 + sparkling high-pass chime sweep
      this.playNoise('highpass', 1600, 5400, 1.8, 0.36, 0.17, 0.03);
      this.playTone('triangle', 587.33, 591, 0.2, 0.24, 0);
      this.playTone('sine', 1174.66, 1180, 0.18, 0.1, 0);
      this.playTone('triangle', 739.99, 744, 0.22, 0.25, 0.08);
      this.playTone('sine', 1479.98, 1488, 0.2, 0.11, 0.08);
      this.playTone('triangle', 880.0, 886, 0.26, 0.26, 0.16);
      this.playTone('sine', 1760.0, 1772, 0.24, 0.12, 0.16);
      this.playTone('sine', 1174.66, 1186, 0.44, 0.3, 0.24);
      this.playTone('triangle', 2349.32, 2368, 0.36, 0.15, 0.24);
      this.playTone('sine', 2959.96, 2980, 0.24, 0.09, 0.31);
      return;
    }

    if (newRarity === 'rare') {
      // Bright 3-note electric-blue synth chord: C5 - E5 - G5
      this.playNoise('bandpass', 1200, 3400, 2.2, 0.16, 0.13, 0);
      this.playTone('triangle', 523.25, 526, 0.18, 0.23, 0.02);
      this.playTone('sine', 1046.5, 1052, 0.16, 0.1, 0.02);
      this.playTone('triangle', 659.25, 663, 0.2, 0.24, 0.1);
      this.playTone('sine', 1318.5, 1325, 0.18, 0.11, 0.1);
      this.playTone('sine', 783.99, 790, 0.34, 0.27, 0.18);
      this.playTone('triangle', 1567.98, 1580, 0.28, 0.13, 0.18);
      return;
    }

    // Fallback chime for common
    this.playTone('triangle', 440, 444, 0.16, 0.2, 0);
    this.playTone('sine', 554.37, 560, 0.22, 0.22, 0.08);
  }

  public playLanding(hard = false): void {
    this.playTone('sine', 120, 42, 0.16, hard ? 0.36 : 0.22);
    this.playNoise('lowpass', 720, 200, 0.9, 0.14, hard ? 0.3 : 0.16);
  }

  public playSlideStart(surface: 'grass' | 'stone' | 'sand' | 'metal' = 'stone'): void {
    const startFreq =
      surface === 'metal'
        ? 2800
        : surface === 'stone'
          ? 1950
          : surface === 'sand'
            ? 1400
            : 1150;
    const endFreq =
      surface === 'metal'
        ? 760
        : surface === 'stone'
          ? 420
          : surface === 'sand'
            ? 360
            : 280;
    // Crisp downward-sweeping bandpass noise whoosh + surface skid + subtle bass thump
    this.playNoise('bandpass', startFreq, endFreq, 1.3, 0.38, 0.28, 0);
    this.playNoise('highpass', startFreq * 0.85, endFreq * 1.1, 1.6, 0.26, 0.12, 0.04);
    this.playTone('sine', 128, 46, 0.14, 0.24, 0);
    if (surface === 'metal') {
      this.playTone('triangle', 1480, 620, 0.18, 0.08, 0.02);
    }
  }

  public setGliderWind(active: boolean, diving = false): void {
    if (!active) {
      if (this.gliderWindGain && this.ctx) {
        this.gliderWindGain.gain.setTargetAtTime(0.0001, this.ctx.currentTime, 0.12);
      }
      this.gliderWindActive = false;
      return;
    }

    const ctx = this.ensureContext();
    if (!ctx || !this.masterGain || !this.noiseBuffer) return;

    if (!this.gliderWindGain || !this.gliderWindFilter) {
      const src = ctx.createBufferSource();
      src.buffer = this.noiseBuffer;
      src.loop = true;

      const filter = ctx.createBiquadFilter();
      filter.type = 'bandpass';
      filter.frequency.setValueAtTime(520, ctx.currentTime);
      filter.Q.setValueAtTime(0.9, ctx.currentTime);

      const gain = ctx.createGain();
      gain.gain.setValueAtTime(0.0001, ctx.currentTime);

      src.connect(filter);
      filter.connect(gain);
      gain.connect(this.masterGain);
      src.start();

      this.gliderWindFilter = filter;
      this.gliderWindGain = gain;
    }

    const targetGain = diving ? 0.22 : 0.11;
    const targetFreq = diving ? 920 : 480;
    this.gliderWindGain.gain.setTargetAtTime(targetGain, ctx.currentTime, 0.15);
    this.gliderWindFilter.frequency.setTargetAtTime(targetFreq, ctx.currentTime, 0.15);
    this.gliderWindActive = true;
  }

  public playSupplyDropHorn(): void {
    // Deep aerospace two-tone supply drop horn
    this.playTone('sawtooth', 220, 220, 0.45, 0.2, 0);
    this.playTone('triangle', 330, 330, 0.55, 0.18, 0.05);
    this.playTone('sawtooth', 293.66, 293.66, 0.65, 0.22, 0.48);
    this.playTone('triangle', 440, 440, 0.72, 0.18, 0.5);
  }

  public playSupplyDropOpen(): void {
    this.playNoise('bandpass', 1400, 420, 1.5, 0.22, 0.25, 0);
    this.playTone('triangle', 523.25, 659.25, 0.14, 0.24, 0.08);
    this.playTone('triangle', 659.25, 783.99, 0.16, 0.24, 0.18);
    this.playTone('sine', 1046.5, 1318.5, 0.35, 0.26, 0.28);
  }

  public playChestOpenStart(distance = 0, pan = 0): void {
    const atten = this.spatialGain(distance, 38);
    if (atten <= 0.02) return;
    // Crisp metallic latch unclip + ascending pneumatic unlock whine
    this.playNoise('bandpass', 2600, 1400, 2.8, 0.06, 0.18 * atten, 0, pan);
    this.playTone('square', 380, 520, 0.05, 0.09 * atten, 0, pan);
    this.playTone('sine', 310, 620, 0.34, 0.14 * atten, 0.05, pan);
    this.playNoise('bandpass', 900, 2100, 1.8, 0.28, 0.09 * atten, 0.08, pan);
  }

  public playChestOpenComplete(tier: ChestTier, distance = 0, pan = 0): void {
    const atten = this.spatialGain(distance, 50);
    if (atten <= 0.02) return;
    // Hydraulic lid pop + tier-escalating triumphant chime
    this.playNoise('bandpass', 1700, 520, 1.4, 0.18, 0.24 * atten, 0, pan);
    this.playTone('sine', 180, 95, 0.11, 0.2 * atten, 0, pan);

    if (tier === 1) {
      this.playTone('triangle', 440, 445, 0.14, 0.2 * atten, 0.04, pan);
      this.playTone('triangle', 554.37, 560, 0.22, 0.22 * atten, 0.11, pan);
    } else if (tier === 2) {
      this.playTone('triangle', 523.25, 528, 0.14, 0.22 * atten, 0.04, pan);
      this.playTone('triangle', 659.25, 664, 0.16, 0.22 * atten, 0.1, pan);
      this.playTone('sine', 783.99, 792, 0.28, 0.24 * atten, 0.17, pan);
    } else {
      // Tier 3 Epic Vault: shimmering major-9th arpeggio + crystalline sparkle
      this.playTone('triangle', 523.25, 526, 0.14, 0.22 * atten, 0.03, pan);
      this.playTone('triangle', 659.25, 663, 0.16, 0.23 * atten, 0.09, pan);
      this.playTone('sine', 783.99, 789, 0.18, 0.24 * atten, 0.15, pan);
      this.playTone('sine', 1046.5, 1060, 0.34, 0.26 * atten, 0.21, pan);
      this.playTone('sine', 1174.66, 1190, 0.36, 0.18 * atten, 0.26, pan);
    }
  }

  public playUltimate(heroId: ProductHeroId, distance = 0, pan = 0): void {
    const atten = this.spatialGain(distance, 140);
    if (atten <= 0.02) return;

    switch (heroId) {
      case 'gmail':
        // Reply-All Barrage: rapid 6-pip notification burst + rocket launch whoosh
        for (let i = 0; i < 6; i++) {
          this.playTone('triangle', 620 + i * 85, 860 + i * 95, 0.075, 0.2 * atten, i * 0.045, pan);
        }
        this.playNoise('bandpass', 1600, 520, 1.1, 0.42, 0.32 * atten, 0.05, pan);
        break;
      case 'drive':
        // Access Revoked: authoritative guardrail lockdown bass + barrier resonance
        this.playTone('sawtooth', 165, 92, 0.38, 0.36 * atten, 0, pan);
        this.playTone('square', 330, 220, 0.16, 0.2 * atten, 0.06, pan);
        this.playTone('sine', 740, 1180, 0.45, 0.26 * atten, 0.12, pan);
        this.playNoise('highpass', 2200, 760, 1.8, 0.34, 0.24 * atten, 0.08, pan);
        break;
      case 'calendar':
        // Hard Stop: heavy chrono time-warp drop + crystalline chime
        this.playTone('sine', 420, 72, 0.62, 0.46 * atten, 0, pan);
        this.playTone('triangle', 1046, 523, 0.35, 0.22 * atten, 0.05, pan);
        this.playTone('sine', 1568, 1568, 0.12, 0.15 * atten, 0.24, pan);
        break;
      case 'chat':
        // @all Ping Overload: iconic dual emerald ping + sweeping sonar shockwave
        this.playTone('sine', 880, 1320, 0.12, 0.3 * atten, 0, pan);
        this.playTone('sine', 1320, 1760, 0.18, 0.28 * atten, 0.09, pan);
        this.playNoise('bandpass', 2400, 320, 1.4, 0.5, 0.32 * atten, 0.1, pan);
        this.playTone('triangle', 260, 68, 0.42, 0.34 * atten, 0.1, pan);
        break;
      case 'slides':
        // Executive Spotlight: 0.3s charge shimmer + blazing golden orbital beam!
        this.playTone('sine', 340, 1420, 0.3, 0.26 * atten, 0, pan);
        this.playTone('sawtooth', 180, 68, 0.65, 0.48 * atten, 0.29, pan);
        this.playNoise('bandpass', 3200, 620, 0.8, 0.58, 0.44 * atten, 0.29, pan);
        this.playTone('triangle', 980, 420, 0.5, 0.28 * atten, 0.3, pan);
        break;
      case 'docs':
        // Version History: slick reverse rewind sweep + crisp Doc snap + Redline Pulse
        this.playTone('sine', 320, 1180, 0.38, 0.28 * atten, 0, pan);
        this.playNoise('bandpass', 480, 2900, 1.8, 0.38, 0.28 * atten, 0, pan);
        this.playTone('triangle', 1240, 620, 0.16, 0.26 * atten, 0.36, pan);
        this.playTone('sine', 140, 45, 0.28, 0.42 * atten, 0.04, pan);
        break;
    }
  }

  public playSilenced(): void {
    this.playTone('sawtooth', 240, 150, 0.11, 0.2);
    this.playTone('sawtooth', 180, 120, 0.12, 0.18, 0.09);
  }

  public playStormTick(): void {
    this.playTone('sine', 160, 110, 0.14, 0.16);
    this.playNoise('bandpass', 900, 420, 2.2, 0.12, 0.12);
  }

  public playVictory(): void {
    const notes = [523.25, 659.25, 783.99, 1046.5];
    notes.forEach((f, idx) => {
      this.playTone('triangle', f, f * 1.005, 0.38, 0.24, idx * 0.11);
    });
  }

  public playDefeat(): void {
    const notes = [392.0, 349.23, 311.13, 261.63];
    notes.forEach((f, idx) => {
      this.playTone('sine', f, f * 0.98, 0.34, 0.2, idx * 0.13);
    });
  }

  public dispose(): void {
    this.setGliderWind(false);
    if (this.gliderWindActive) {
      this.gliderWindActive = false;
    }
  }
}

export const sharedAudio = new SoundEngine();

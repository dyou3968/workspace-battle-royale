import * as THREE from 'three';
import { Rarity } from '../types';

interface TransientEffect {
  object: THREE.Object3D;
  age: number;
  ttl: number;
  update: (dt: number, progress: number) => void;
  disposeMaterials?: boolean;
}

interface Particle {
  mesh: THREE.Mesh;
  vel: THREE.Vector3;
  gravity: number;
  age: number;
  ttl: number;
  startScale: number;
  endScale: number;
  baseOpacity?: number;
  rotVel?: THREE.Vector3;
}

interface FlashLight {
  light: THREE.PointLight;
  age: number;
  ttl: number;
  peakIntensity: number;
  seq: number;
}

export interface PersistentZoneVisual {
  group: THREE.Group;
  update: (dt: number, elapsed: number, remaining: number) => void;
  dispose: () => void;
}

/**
 * High-performance Three.js 3D VFX system for Workspace Royale.
 * Handles muzzle flashes, ballistic tracers, shield/headshot impacts, explosions,
 * Hard-Light Cover shields, Supply Drop sky beacons, and all 6 Product Ultimates.
 */
export class VfxSystem {
  private readonly scene: THREE.Scene;
  private readonly effects: TransientEffect[] = [];
  private readonly particles: Particle[] = [];
  private readonly lights: FlashLight[] = [];
  private nextLightSeq = 1;

  // Shared unit geometries (never disposed per-effect)
  private readonly unitSphereGeo = new THREE.SphereGeometry(1, 14, 10);
  private readonly lowSphereGeo = new THREE.SphereGeometry(1, 8, 6);
  private readonly unitCylinderGeo = new THREE.CylinderGeometry(1, 1, 1, 10, 1, true);
  private readonly closedCylinderGeo = new THREE.CylinderGeometry(1, 1, 1, 14, 1, false);
  private readonly unitRingGeo = new THREE.RingGeometry(0.78, 1.0, 32);
  private readonly unitTorusGeo = new THREE.TorusGeometry(1, 0.045, 8, 36);
  private readonly unitBoxGeo = new THREE.BoxGeometry(1, 1, 1);
  private readonly unitConeGeo = new THREE.ConeGeometry(0.5, 1, 8);
  private readonly sparkGeo = new THREE.OctahedronGeometry(0.12, 0);
  private readonly unitShardGeo = new THREE.OctahedronGeometry(0.16, 0);

  private readonly tmpVecA = new THREE.Vector3();
  private readonly tmpVecB = new THREE.Vector3();
  private readonly upAxis = new THREE.Vector3(0, 1, 0);

  constructor(scene: THREE.Scene) {
    this.scene = scene;
    // Rotate unit ring so it lies flat on XZ plane by default
    this.unitRingGeo.rotateX(-Math.PI / 2);
    // Faceted crystalline diamond shard profile for shield-shatter debris
    this.unitShardGeo.scale(0.62, 1.65, 0.3);

    // Pre-allocate a tight pool of ONLY 2 dynamic point lights (recycles oldest light if >2 bursts overlap)
    // Combined with the world's 1 dynamic interior light, total scene PointLights stays <= 3 across WebGL shaders.
    for (let i = 0; i < 2; i++) {
      const light = new THREE.PointLight(0xffffff, 0, 14, 2);
      light.visible = false;
      this.scene.add(light);
      this.lights.push({ light, age: 1, ttl: 1, peakIntensity: 0, seq: 0 });
    }
  }

  private triggerFlashLight(
    pos: THREE.Vector3,
    color: number,
    intensity: number,
    distance: number,
    ttl: number
  ): void {
    // Reuse inactive slot first, otherwise recycle oldest active light
    let slot = this.lights[0];
    let bestScore = -1;
    for (const candidate of this.lights) {
      if (!candidate.light.visible) {
        slot = candidate;
        break;
      }
      const ratio = candidate.age / Math.max(candidate.ttl, 0.001);
      if (ratio > bestScore || (ratio === bestScore && candidate.seq < slot.seq)) {
        bestScore = ratio;
        slot = candidate;
      }
    }
    slot.light.position.copy(pos);
    slot.light.color.setHex(color);
    slot.light.distance = distance;
    slot.light.intensity = intensity;
    slot.light.visible = true;
    slot.age = 0;
    slot.ttl = ttl;
    slot.peakIntensity = intensity;
    slot.seq = this.nextLightSeq++;
  }

  private addEffect(
    object: THREE.Object3D,
    ttl: number,
    update: (dt: number, progress: number) => void,
    disposeMaterials = true
  ): void {
    this.scene.add(object);
    this.effects.push({ object, age: 0, ttl, update, disposeMaterials });
  }

  private spawnSpark(
    pos: THREE.Vector3,
    vel: THREE.Vector3,
    color: number,
    ttl: number,
    startScale = 1,
    endScale = 0.05,
    gravity = 16
  ): void {
    if (this.particles.length > 260) return;
    const mat = new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      opacity: 0.95,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const mesh = new THREE.Mesh(this.sparkGeo, mat);
    mesh.position.copy(pos);
    mesh.scale.setScalar(startScale);
    this.scene.add(mesh);
    this.particles.push({
      mesh,
      vel: vel.clone(),
      gravity,
      age: 0,
      ttl,
      startScale,
      endScale,
    });
  }

  private spawnCrystalShard(
    pos: THREE.Vector3,
    vel: THREE.Vector3,
    color: number,
    ttl = 0.48,
    startScale = 1.2,
    endScale = 0.22,
    gravity = 13
  ): void {
    if (this.particles.length > 280) return;
    const mat = new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      opacity: 0.88,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const mesh = new THREE.Mesh(this.unitShardGeo, mat);
    mesh.position.copy(pos);
    mesh.rotation.set(
      Math.random() * Math.PI * 2,
      Math.random() * Math.PI * 2,
      Math.random() * Math.PI * 2
    );
    mesh.scale.setScalar(startScale);
    this.scene.add(mesh);
    this.particles.push({
      mesh,
      vel: vel.clone(),
      gravity,
      age: 0,
      ttl,
      startScale,
      endScale,
      baseOpacity: 0.88,
      rotVel: new THREE.Vector3(
        (Math.random() - 0.5) * 26,
        (Math.random() - 0.5) * 26,
        (Math.random() - 0.5) * 22
      ),
    });
  }

  /** Crisp muzzle flash burst aligned to barrel direction. */
  public spawnMuzzleFlash(
    pos: THREE.Vector3,
    dir: THREE.Vector3,
    color = 0xffcf6b,
    scale = 1.0
  ): void {
    const group = new THREE.Group();
    group.position.copy(pos);
    const lookTarget = this.tmpVecA.copy(pos).add(dir);
    group.lookAt(lookTarget);

    const coreMat = new THREE.MeshBasicMaterial({
      color: 0xffffff,
      transparent: true,
      opacity: 0.95,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const core = new THREE.Mesh(this.lowSphereGeo, coreMat);
    core.scale.set(0.08 * scale, 0.08 * scale, 0.22 * scale);
    core.position.z = 0.08 * scale;
    group.add(core);

    const outerMat = new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      opacity: 0.85,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const cone = new THREE.Mesh(this.unitConeGeo, outerMat);
    cone.rotation.x = Math.PI / 2;
    cone.scale.set(0.22 * scale, 0.42 * scale, 0.22 * scale);
    cone.position.z = 0.22 * scale;
    group.add(cone);

    this.triggerFlashLight(pos, color, 4.0 * scale, 8, 0.06);

    this.addEffect(group, 0.065, (_dt, p) => {
      const s = 1 - p * 0.65;
      group.scale.setScalar(s);
      coreMat.opacity = 1 - p;
      outerMat.opacity = 0.85 * (1 - p);
    });
  }

  /** Ballistic glowing bullet tracer from muzzle to hit point. */
  public spawnTracer(
    start: THREE.Vector3,
    end: THREE.Vector3,
    color = 0xffe49c,
    thickness = 0.032,
    ttl = 0.095
  ): void {
    const diff = this.tmpVecA.subVectors(end, start);
    const len = diff.length();
    if (len < 0.05) return;

    const mat = new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      opacity: 0.9,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const mesh = new THREE.Mesh(this.unitCylinderGeo, mat);
    mesh.position.copy(start).addScaledVector(diff, 0.5);
    mesh.scale.set(thickness, len, thickness);
    mesh.quaternion.setFromUnitVectors(this.upAxis, diff.normalize());

    this.addEffect(mesh, ttl, (_dt, p) => {
      mat.opacity = 0.9 * (1 - p);
      const shrink = 1 - p * 0.5;
      mesh.scale.set(thickness * shrink, len, thickness * shrink);
    });
  }

  /** Hit sparks for world geometry, body shots, shield impacts, and golden headshot crits. */
  public spawnHitImpact(
    pos: THREE.Vector3,
    options: { isShield?: boolean; isHeadshot?: boolean; isWorld?: boolean } = {}
  ): void {
    const { isShield = false, isHeadshot = false, isWorld = false } = options;
    const primaryColor = isHeadshot
      ? 0xfbbf24
      : isShield
        ? 0x38bdf8
        : isWorld
          ? 0xe2e8f0
          : 0xf87171;
    const count = isHeadshot ? 14 : isShield ? 10 : 7;

    for (let i = 0; i < count; i++) {
      const speed = (isHeadshot ? 7.5 : 5.0) * (0.45 + Math.random() * 0.85);
      const theta = Math.random() * Math.PI * 2;
      const phi = (Math.random() - 0.25) * Math.PI;
      const vel = new THREE.Vector3(
        Math.cos(theta) * Math.cos(phi) * speed,
        Math.abs(Math.sin(phi)) * speed + 1.5,
        Math.sin(theta) * Math.cos(phi) * speed
      );
      this.spawnSpark(
        pos,
        vel,
        i % 3 === 0 && isHeadshot ? 0xffffff : primaryColor,
        isHeadshot ? 0.34 : 0.24,
        isHeadshot ? 1.45 : 0.95,
        0.05,
        15
      );
    }

    if (isHeadshot || isShield) {
      const ringMat = new THREE.MeshBasicMaterial({
        color: primaryColor,
        transparent: true,
        opacity: 0.95,
        side: THREE.DoubleSide,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      });
      const ring = new THREE.Mesh(this.unitTorusGeo, ringMat);
      ring.position.copy(pos);
      ring.rotation.set(Math.random() * Math.PI, Math.random() * Math.PI, 0);
      ring.scale.setScalar(0.15);
      const maxR = isHeadshot ? 1.15 : 0.72;
      this.addEffect(ring, isHeadshot ? 0.28 : 0.2, (_dt, p) => {
        ring.scale.setScalar(0.15 + p * maxR);
        ringMat.opacity = 0.95 * (1 - p);
      });
      if (isHeadshot) {
        this.triggerFlashLight(pos, 0xfbbf24, 5.5, 9, 0.14);
      }
    }
  }

  /** Shield shatter burst when a combatant's shield drops from >0 to 0. */
  public spawnShieldBreak(pos: THREE.Vector3): void {
    const center = pos.clone().add(new THREE.Vector3(0, 1.1, 0));

    // 1. Bright electric cyan-white core flash sphere (0.18s)
    const coreMat = new THREE.MeshBasicMaterial({
      color: 0xe0f2fe,
      transparent: true,
      opacity: 0.96,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const coreFlash = new THREE.Mesh(this.unitSphereGeo, coreMat);
    coreFlash.position.copy(center);
    coreFlash.scale.setScalar(0.38);
    this.addEffect(coreFlash, 0.18, (_dt, p) => {
      const ease = 1 - Math.pow(1 - p, 2.5);
      coreFlash.scale.setScalar(0.38 + ease * 0.92);
      coreMat.opacity = 0.96 * Math.pow(1 - p, 1.6);
    });

    // 2. Dual expanding electric cyan shockwave rings (horizontal + tilted 35°)
    const horizRingMat = new THREE.MeshBasicMaterial({
      color: 0x38bdf8,
      transparent: true,
      opacity: 0.95,
      side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const horizRing = new THREE.Mesh(this.unitRingGeo, horizRingMat);
    horizRing.position.copy(center);
    horizRing.scale.setScalar(0.42);
    this.addEffect(horizRing, 0.34, (_dt, p) => {
      const ease = 1 - Math.pow(1 - p, 2.6);
      horizRing.scale.setScalar(0.42 + ease * 2.45);
      horizRingMat.opacity = 0.95 * (1 - p);
    });

    const tiltedRingMat = new THREE.MeshBasicMaterial({
      color: 0x7dd3fc,
      transparent: true,
      opacity: 0.92,
      side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const tiltedRing = new THREE.Mesh(this.unitTorusGeo, tiltedRingMat);
    tiltedRing.position.copy(center);
    tiltedRing.rotation.order = 'YXZ';
    tiltedRing.rotation.set(Math.PI / 2 + (35 * Math.PI) / 180, Math.random() * Math.PI * 2, 0);
    tiltedRing.scale.setScalar(0.36);
    this.addEffect(tiltedRing, 0.36, (dt, p) => {
      const ease = 1 - Math.pow(1 - p, 2.4);
      tiltedRing.scale.setScalar(0.36 + ease * 2.15);
      tiltedRing.rotation.z += dt * 4.2;
      tiltedRingMat.opacity = 0.92 * (1 - p);
    });

    // 3. Rapid-expanding shattering wireframe hex shell
    const shellMat = new THREE.MeshBasicMaterial({
      color: 0x38bdf8,
      wireframe: true,
      transparent: true,
      opacity: 0.94,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const shell = new THREE.Mesh(this.unitSphereGeo, shellMat);
    shell.position.copy(center);
    shell.scale.setScalar(0.55);
    this.addEffect(shell, 0.34, (dt, p) => {
      const ease = 1 - Math.pow(1 - p, 2.2);
      shell.scale.setScalar(0.55 + ease * 1.85);
      shell.rotation.y += dt * 5.2;
      shell.rotation.z += dt * 2.4;
      shellMat.opacity = 0.94 * (1 - p);
    });

    // 4. 28 high-velocity electric multi-tone sparks bursting radially + arcing upward
    const sparkPalette = [0x38bdf8, 0x7dd3fc, 0xe0f2fe, 0x4285f4];
    for (let i = 0; i < 28; i++) {
      const a = (i / 28) * Math.PI * 2 + (Math.random() - 0.5) * 0.22;
      const radialSpeed = 6.2 + Math.random() * 6.4;
      const vel = new THREE.Vector3(
        Math.cos(a) * radialSpeed,
        2.6 + Math.random() * 5.2,
        Math.sin(a) * radialSpeed
      );
      this.spawnSpark(
        center,
        vel,
        sparkPalette[i % sparkPalette.length],
        0.36 + Math.random() * 0.2,
        1.25 + Math.random() * 0.5,
        0.05,
        16
      );
    }

    // 5. 10 spinning translucent crystalline glass shards flying outward & tumbling for 0.48s
    for (let i = 0; i < 10; i++) {
      const a = (i / 10) * Math.PI * 2 + (Math.random() - 0.5) * 0.32;
      const radialSpeed = 4.6 + Math.random() * 4.4;
      const startOffset = new THREE.Vector3(
        Math.cos(a) * 0.32,
        (Math.random() - 0.35) * 0.45,
        Math.sin(a) * 0.32
      );
      const vel = new THREE.Vector3(
        Math.cos(a) * radialSpeed,
        2.4 + Math.random() * 3.6,
        Math.sin(a) * radialSpeed
      );
      this.spawnCrystalShard(
        center.clone().add(startOffset),
        vel,
        i % 2 === 0 ? 0xbae6fd : 0x38bdf8,
        0.48,
        1.05 + Math.random() * 0.45,
        0.22,
        13
      );
    }

    // 6. Brighter cyan flash light
    this.triggerFlashLight(center, 0x38bdf8, 9.5, 14, 0.24);
  }

  /** Holographic scan burst when upgrading a weapon at a TechStop kiosk. */
  public spawnTechStopUpgrade(pos: THREE.Vector3, rarity: Rarity): void {
    const isEpic = rarity === 'epic';
    const primaryColor = isEpic ? 0xa855f7 : 0x4285f4;
    const accentColor = isEpic ? 0xe9d5ff : 0x7dd3fc;

    const group = new THREE.Group();
    group.position.copy(pos);

    // Vertical holographic scan beam cylinder (outer + bright inner core)
    const outerBeamMat = new THREE.MeshBasicMaterial({
      color: primaryColor,
      transparent: true,
      opacity: 0.42,
      side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const outerBeam = new THREE.Mesh(this.unitCylinderGeo, outerBeamMat);
    outerBeam.position.y = 2.3;
    outerBeam.scale.set(0.88, 4.6, 0.88);
    group.add(outerBeam);

    const innerBeamMat = new THREE.MeshBasicMaterial({
      color: accentColor,
      transparent: true,
      opacity: 0.68,
      side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const innerBeam = new THREE.Mesh(this.unitCylinderGeo, innerBeamMat);
    innerBeam.position.y = 2.5;
    innerBeam.scale.set(0.28, 5.0, 0.28);
    group.add(innerBeam);

    // Rising twin concentric holographic scan rings
    const lowerRingMat = new THREE.MeshBasicMaterial({
      color: primaryColor,
      transparent: true,
      opacity: 0.95,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const lowerRing = new THREE.Mesh(this.unitTorusGeo, lowerRingMat);
    lowerRing.rotation.x = Math.PI / 2;
    lowerRing.position.y = 0.2;
    lowerRing.scale.setScalar(0.75);
    group.add(lowerRing);

    const upperRingMat = new THREE.MeshBasicMaterial({
      color: accentColor,
      transparent: true,
      opacity: 0.92,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const upperRing = new THREE.Mesh(this.unitTorusGeo, upperRingMat);
    upperRing.rotation.x = Math.PI / 2;
    upperRing.position.y = 0.55;
    upperRing.scale.setScalar(0.5);
    group.add(upperRing);

    // Ground halo ring
    const groundRingMat = new THREE.MeshBasicMaterial({
      color: primaryColor,
      transparent: true,
      opacity: 0.82,
      side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const groundRing = new THREE.Mesh(this.unitRingGeo, groundRingMat);
    groundRing.position.y = 0.12;
    groundRing.scale.setScalar(0.6);
    group.add(groundRing);

    this.addEffect(group, 0.76, (dt, p) => {
      const ease = 1 - Math.pow(1 - p, 2.3);
      const fade = Math.max(0, 1 - p);

      const outerR = 0.88 + ease * 0.42;
      outerBeam.scale.set(outerR, 4.6 + ease * 0.8, outerR);
      outerBeamMat.opacity = 0.42 * fade;

      const innerR = Math.max(0.05, 0.28 * (1 - p * 0.65));
      innerBeam.scale.set(innerR, 5.0 + ease * 0.9, innerR);
      innerBeamMat.opacity = 0.68 * fade;

      lowerRing.position.y = 0.2 + ease * 3.1;
      lowerRing.scale.setScalar(0.75 + ease * 0.95);
      lowerRing.rotation.z += dt * 3.6;
      lowerRingMat.opacity = 0.95 * fade;

      upperRing.position.y = 0.55 + ease * 3.55;
      upperRing.scale.setScalar(0.5 + ease * 0.78);
      upperRing.rotation.z -= dt * 4.8;
      upperRingMat.opacity = 0.92 * fade;

      groundRing.scale.setScalar(0.6 + ease * 2.1);
      groundRingMat.opacity = 0.82 * fade;
    });

    // 22 ascending sparkle particles tinted Electric Blue (rare) or Royal Epic Purple (epic)
    for (let i = 0; i < 22; i++) {
      const a = (i / 22) * Math.PI * 2 + (Math.random() - 0.5) * 0.3;
      const r = 0.35 + Math.random() * 0.85;
      const start = new THREE.Vector3(
        pos.x + Math.cos(a) * r,
        pos.y + 0.18 + Math.random() * 1.15,
        pos.z + Math.sin(a) * r
      );
      const swirlX = -Math.sin(a) * 0.9 + Math.cos(a) * (0.4 + Math.random() * 0.7);
      const swirlZ = Math.cos(a) * 0.9 + Math.sin(a) * (0.4 + Math.random() * 0.7);
      this.spawnSpark(
        start,
        new THREE.Vector3(swirlX, 3.4 + Math.random() * 3.4, swirlZ),
        i % 2 === 0 ? primaryColor : accentColor,
        0.56 + Math.random() * 0.28,
        0.95 + Math.random() * 0.45,
        0.05,
        -1.8
      );
    }

    this.triggerFlashLight(
      pos.clone().add(new THREE.Vector3(0, 1.5, 0)),
      primaryColor,
      isEpic ? 9.0 : 7.5,
      14,
      0.34
    );
  }

  /** Explosive shockwave + fire core + sparks (Nova GL-40, Gmail Reply-All, eliminations). */
  public spawnExplosion(pos: THREE.Vector3, radius: number, color = 0xff6b35): void {
    const group = new THREE.Group();
    group.position.copy(pos);

    const flashMat = new THREE.MeshBasicMaterial({
      color: 0xfff3c4,
      transparent: true,
      opacity: 0.95,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const flash = new THREE.Mesh(this.unitSphereGeo, flashMat);
    group.add(flash);

    const blastMat = new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      opacity: 0.65,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const blast = new THREE.Mesh(this.unitSphereGeo, blastMat);
    group.add(blast);

    const ringMat = new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      opacity: 0.9,
      side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const ring = new THREE.Mesh(this.unitRingGeo, ringMat);
    ring.position.y = 0.12;
    group.add(ring);

    this.triggerFlashLight(pos, color, 9.5, radius * 3.2, 0.28);

    this.addEffect(group, 0.52, (_dt, p) => {
      const easeOut = 1 - Math.pow(1 - p, 3);
      flash.scale.setScalar(radius * 0.45 * (1 - p * 0.5));
      flashMat.opacity = Math.max(0, 1 - p * 2.2);
      blast.scale.setScalar(radius * 0.78 * easeOut);
      blastMat.opacity = 0.65 * (1 - p);
      ring.scale.setScalar(Math.max(0.2, radius * 1.08 * easeOut));
      ringMat.opacity = 0.9 * (1 - p);
    });

    const sparkCount = Math.min(26, Math.max(12, Math.round(radius * 3.5)));
    for (let i = 0; i < sparkCount; i++) {
      const angle = Math.random() * Math.PI * 2;
      const spd = radius * (1.2 + Math.random() * 1.9);
      const vel = new THREE.Vector3(
        Math.cos(angle) * spd,
        3.5 + Math.random() * (radius * 1.6),
        Math.sin(angle) * spd
      );
      this.spawnSpark(
        pos,
        vel,
        i % 3 === 0 ? 0xffe082 : color,
        0.45 + Math.random() * 0.25,
        1.5,
        0.1,
        18
      );
    }
  }

  /** Blinding flashbang detonation: bright white flash sphere, shockwave ring, 22 sparks & flash light. */
  public spawnFlashbangBurst(pos: THREE.Vector3): void {
    const group = new THREE.Group();
    group.position.copy(pos);

    const flashMat = new THREE.MeshBasicMaterial({
      color: 0xffffff,
      transparent: true,
      opacity: 0.98,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const flashSphere = new THREE.Mesh(this.unitSphereGeo, flashMat);
    flashSphere.scale.setScalar(0.45);
    group.add(flashSphere);

    const ringMat = new THREE.MeshBasicMaterial({
      color: 0xfef08a,
      transparent: true,
      opacity: 0.95,
      side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const ring = new THREE.Mesh(this.unitRingGeo, ringMat);
    ring.position.y = 0.14;
    ring.scale.setScalar(0.4);
    group.add(ring);

    this.triggerFlashLight(pos, 0xffffff, 14, 24, 0.28);

    this.addEffect(group, 0.34, (_dt, p) => {
      const easeOut = 1 - Math.pow(1 - p, 2.6);
      flashSphere.scale.setScalar(0.45 + easeOut * 3.2);
      flashMat.opacity = 0.98 * Math.pow(1 - p, 1.5);
      ring.scale.setScalar(0.4 + easeOut * 8.6);
      ringMat.opacity = 0.95 * (1 - p);
    });

    const sparkPalette = [0xffffff, 0xfef08a, 0xfde047];
    for (let i = 0; i < 22; i++) {
      const theta = (i / 22) * Math.PI * 2 + (Math.random() - 0.5) * 0.25;
      const spd = 6.5 + Math.random() * 7.5;
      const vel = new THREE.Vector3(
        Math.cos(theta) * spd,
        2.5 + Math.random() * 6.5,
        Math.sin(theta) * spd
      );
      this.spawnSpark(
        pos,
        vel,
        sparkPalette[i % sparkPalette.length],
        0.34 + Math.random() * 0.2,
        1.35 + Math.random() * 0.45,
        0.06,
        14
      );
    }
  }

  /**
   * Shield Drop — translucent Google-Blue/Cyan protective energy hemisphere
   * with wireframe hex shimmer, glowing ground perimeter ring & rotating shield beacon pulse.
   */
  public createShieldDropDome(
    pos: THREE.Vector3,
    radius: number,
    colorHex = 0x38bdf8
  ): PersistentZoneVisual {
    const group = new THREE.Group();
    group.position.copy(pos);

    // Protective energy hemisphere
    const domeGeo = new THREE.SphereGeometry(radius, 28, 16, 0, Math.PI * 2, 0, Math.PI * 0.52);
    const domeMat = new THREE.MeshBasicMaterial({
      color: colorHex,
      transparent: true,
      opacity: 0.24,
      side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const dome = new THREE.Mesh(domeGeo, domeMat);
    group.add(dome);

    // Subtle wireframe hex shimmer
    const wireMat = new THREE.MeshBasicMaterial({
      color: 0xbae6fd,
      wireframe: true,
      transparent: true,
      opacity: 0.26,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const wire = new THREE.Mesh(domeGeo, wireMat);
    wire.scale.setScalar(1.004);
    group.add(wire);

    // Glowing ground perimeter ring
    const groundMat = new THREE.MeshBasicMaterial({
      color: colorHex,
      transparent: true,
      opacity: 0.8,
      side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const groundRing = new THREE.Mesh(this.unitRingGeo, groundMat);
    groundRing.scale.setScalar(radius);
    groundRing.position.y = 0.09;
    group.add(groundRing);

    // Rotating shield beacon pulse band
    const bandGeo = new THREE.TorusGeometry(radius * 0.84, 0.06, 8, 48);
    const bandMat = new THREE.MeshBasicMaterial({
      color: 0x7dd3fc,
      transparent: true,
      opacity: 0.78,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const beaconBand = new THREE.Mesh(bandGeo, bandMat);
    beaconBand.rotation.x = Math.PI / 2;
    beaconBand.position.y = radius * 0.42;
    group.add(beaconBand);

    // Central ground emitter glow
    const coreMat = new THREE.MeshBasicMaterial({
      color: 0xe0f2fe,
      transparent: true,
      opacity: 0.85,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const core = new THREE.Mesh(this.lowSphereGeo, coreMat);
    core.position.y = 0.24;
    core.scale.setScalar(0.32);
    group.add(core);

    this.scene.add(group);
    this.triggerFlashLight(pos.clone().add(new THREE.Vector3(0, 1.8, 0)), colorHex, 8, radius * 2.6, 0.36);

    return {
      group,
      update: (dt, elapsed, remaining) => {
        const fade = remaining < 0.65 ? Math.max(0, remaining / 0.65) : 1;
        const shimmer = 0.86 + Math.sin(elapsed * 4.8) * 0.14;
        domeMat.opacity = 0.24 * shimmer * fade;
        wireMat.opacity = (0.22 + Math.sin(elapsed * 6.2) * 0.06) * fade;
        groundMat.opacity = 0.8 * fade;

        wire.rotation.y += dt * 0.24;
        beaconBand.rotation.z += dt * 1.1;
        const pulsePhase = (elapsed * 0.65) % 1;
        const bandH = 0.2 + pulsePhase * (radius * 0.78);
        const bandR = Math.sqrt(Math.max(0.25, radius * radius - bandH * bandH)) / (radius * 0.84);
        beaconBand.position.y = bandH;
        beaconBand.scale.setScalar(Math.max(0.2, bandR));
        bandMat.opacity = 0.78 * Math.sin(pulsePhase * Math.PI) * fade;

        core.scale.setScalar(0.28 + Math.sin(elapsed * 7.5) * 0.06);
        coreMat.opacity = 0.85 * fade;
      },
      dispose: () => {
        this.scene.remove(group);
        domeGeo.dispose();
        domeMat.dispose();
        wireMat.dispose();
        groundMat.dispose();
        bandGeo.dispose();
        bandMat.dispose();
        coreMat.dispose();
      },
    };
  }

  /**
   * Regeneration Pod — warm luminous Google-Green healing pulse ring,
   * soft vertical emerald aura cylinder & gently rising healing motes.
   */
  public createRegenPodAura(pos: THREE.Vector3, radius: number): PersistentZoneVisual {
    const group = new THREE.Group();
    group.position.copy(pos);

    // Outer luminous Google-Green ground ring
    const outerRingMat = new THREE.MeshBasicMaterial({
      color: 0x34a853,
      transparent: true,
      opacity: 0.82,
      side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const outerRing = new THREE.Mesh(this.unitRingGeo, outerRingMat);
    outerRing.scale.setScalar(radius);
    outerRing.position.y = 0.09;
    group.add(outerRing);

    // Pulsing inner emerald wave ring
    const pulseRingMat = new THREE.MeshBasicMaterial({
      color: 0x6ee7b7,
      transparent: true,
      opacity: 0.72,
      side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const pulseRing = new THREE.Mesh(this.unitRingGeo, pulseRingMat);
    pulseRing.scale.setScalar(0.4);
    pulseRing.position.y = 0.12;
    group.add(pulseRing);

    // Soft vertical emerald aura cylinder
    const auraHeight = 2.8;
    const auraGeo = new THREE.CylinderGeometry(radius * 0.96, radius, auraHeight, 28, 1, true);
    const auraMat = new THREE.MeshBasicMaterial({
      color: 0x34a853,
      transparent: true,
      opacity: 0.14,
      side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const auraCylinder = new THREE.Mesh(auraGeo, auraMat);
    auraCylinder.position.y = auraHeight * 0.5;
    group.add(auraCylinder);

    // Gently rising healing motes
    const moteMat = new THREE.MeshBasicMaterial({
      color: 0x86efac,
      transparent: true,
      opacity: 0.85,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const motes: { mesh: THREE.Mesh; angle: number; dist: number; phase: number; speed: number }[] = [];
    const moteCount = 14;
    for (let i = 0; i < moteCount; i++) {
      const angle = (i / moteCount) * Math.PI * 2 + (Math.random() - 0.5) * 0.35;
      const dist = radius * (0.2 + Math.random() * 0.72);
      const phase = Math.random();
      const speed = 0.38 + Math.random() * 0.28;
      const mote = new THREE.Mesh(this.sparkGeo, moteMat);
      mote.position.set(Math.cos(angle) * dist, 0.2 + phase * 2.4, Math.sin(angle) * dist);
      mote.scale.setScalar(0.85);
      group.add(mote);
      motes.push({ mesh: mote, angle, dist, phase, speed });
    }

    this.scene.add(group);
    this.triggerFlashLight(pos.clone().add(new THREE.Vector3(0, 1.4, 0)), 0x34a853, 7, radius * 2.4, 0.38);

    return {
      group,
      update: (dt, elapsed, remaining) => {
        const fade = remaining < 0.65 ? Math.max(0, remaining / 0.65) : 1;
        const breathe = 0.84 + Math.sin(elapsed * 4.2) * 0.16;
        outerRingMat.opacity = 0.82 * breathe * fade;
        auraMat.opacity = 0.14 * breathe * fade;
        auraCylinder.rotation.y += dt * 0.3;

        const wave = (elapsed * 0.85) % 1;
        pulseRing.scale.setScalar(Math.max(0.25, radius * (0.15 + wave * 0.88)));
        pulseRingMat.opacity = 0.72 * (1 - wave) * fade;

        moteMat.opacity = 0.85 * fade;
        for (const m of motes) {
          m.phase = (m.phase + dt * m.speed) % 1;
          m.angle += dt * 0.32;
          const y = 0.18 + m.phase * 2.65;
          m.mesh.position.set(Math.cos(m.angle) * m.dist, y, Math.sin(m.angle) * m.dist);
          m.mesh.rotation.y += dt * 3.0;
          const scale = Math.sin(m.phase * Math.PI) * 1.1;
          m.mesh.scale.setScalar(Math.max(0.05, scale));
        }
      },
      dispose: () => {
        this.scene.remove(group);
        outerRingMat.dispose();
        pulseRingMat.dispose();
        auraGeo.dispose();
        auraMat.dispose();
        moteMat.dispose();
      },
    };
  }

  /** Gmail Ultimate homing explosive envelope missile visual. */
  public createGmailEnvelopeMissile(): THREE.Group {
    const group = new THREE.Group();
    const bodyMat = new THREE.MeshStandardMaterial({
      color: 0xffffff,
      emissive: 0xea4335,
      emissiveIntensity: 0.55,
      roughness: 0.35,
    });
    const body = new THREE.Mesh(this.unitBoxGeo, bodyMat);
    body.scale.set(0.42, 0.08, 0.28);
    group.add(body);

    const trimMat = new THREE.MeshBasicMaterial({
      color: 0xea4335,
    });
    const leftStripe = new THREE.Mesh(this.unitBoxGeo, trimMat);
    leftStripe.scale.set(0.06, 0.095, 0.29);
    leftStripe.position.x = -0.18;
    group.add(leftStripe);

    const rightStripe = new THREE.Mesh(this.unitBoxGeo, trimMat);
    rightStripe.scale.set(0.06, 0.095, 0.29);
    rightStripe.position.x = 0.18;
    group.add(rightStripe);

    const trailMat = new THREE.MeshBasicMaterial({
      color: 0xff6b57,
      transparent: true,
      opacity: 0.75,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const trail = new THREE.Mesh(this.unitConeGeo, trailMat);
    trail.rotation.x = Math.PI / 2;
    trail.scale.set(0.24, 0.85, 0.24);
    trail.position.z = 0.45;
    group.add(trail);

    return group;
  }

  /** Nova GL-40 glowing explosive grenade orb. */
  public createGrenadeProjectile(): THREE.Group {
    const group = new THREE.Group();
    const core = new THREE.Mesh(
      this.lowSphereGeo,
      new THREE.MeshStandardMaterial({
        color: 0x1e293b,
        emissive: 0xff7043,
        emissiveIntensity: 1.4,
        roughness: 0.3,
        metalness: 0.6,
      })
    );
    core.scale.setScalar(0.16);
    group.add(core);

    const halo = new THREE.Mesh(
      this.lowSphereGeo,
      new THREE.MeshBasicMaterial({
        color: 0xffa726,
        transparent: true,
        opacity: 0.45,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      })
    );
    halo.scale.setScalar(0.26);
    group.add(halo);
    return group;
  }

  /**
   * Google Drive Ultimate — "Access Revoked (Permission Guardrail)"
   * 12m translucent emerald/gold guardrail dome with rotating security bands + ground ring.
   */
  public createDriveGuardrailDome(center: THREE.Vector3, radius: number): PersistentZoneVisual {
    const group = new THREE.Group();
    group.position.copy(center);

    // Translucent dome shell
    const domeGeo = new THREE.SphereGeometry(radius, 28, 18, 0, Math.PI * 2, 0, Math.PI * 0.56);
    const domeMat = new THREE.MeshBasicMaterial({
      color: 0x34a853,
      transparent: true,
      opacity: 0.14,
      side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const dome = new THREE.Mesh(domeGeo, domeMat);
    group.add(dome);

    // Geodesic wireframe barrier lattice
    const latticeMat = new THREE.MeshBasicMaterial({
      color: 0x6ee7b7,
      wireframe: true,
      transparent: true,
      opacity: 0.28,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const lattice = new THREE.Mesh(domeGeo, latticeMat);
    lattice.scale.setScalar(1.003);
    group.add(lattice);

    // Three Drive tri-color rotating guardrail security bands (Green / Blue / Gold)
    const bandColors = [0x34a853, 0x4285f4, 0xfbbc04];
    const bands: THREE.Mesh[] = [];
    const bandMats: THREE.MeshBasicMaterial[] = [];
    for (let i = 0; i < 3; i++) {
      const h = 1.1 + i * 2.2;
      const rAtH = Math.sqrt(Math.max(1, radius * radius - h * h));
      const bGeo = new THREE.TorusGeometry(rAtH, 0.085, 8, 56);
      const bMat = new THREE.MeshBasicMaterial({
        color: bandColors[i],
        transparent: true,
        opacity: 0.85,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      });
      const band = new THREE.Mesh(bGeo, bMat);
      band.rotation.x = Math.PI / 2;
      band.position.y = h;
      group.add(band);
      bands.push(band);
      bandMats.push(bMat);
    }

    // Crisp ground perimeter ring
    const groundMat = new THREE.MeshBasicMaterial({
      color: 0x34a853,
      transparent: true,
      opacity: 0.72,
      side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const groundRing = new THREE.Mesh(this.unitRingGeo, groundMat);
    groundRing.scale.setScalar(radius);
    groundRing.position.y = 0.09;
    group.add(groundRing);

    this.scene.add(group);
    this.triggerFlashLight(center.clone().add(new THREE.Vector3(0, 2.5, 0)), 0x34a853, 7.5, 22, 0.45);

    // Expanding 16m silence revocation shockwave on activation
    this.spawnExpandingRing(center, 16, 0x34a853, 0.55);
    this.spawnExpandingRing(center, 16, 0xfbbc04, 0.42);

    return {
      group,
      update: (dt, elapsed, remaining) => {
        const fade = remaining < 0.7 ? Math.max(0, remaining / 0.7) : 1;
        const pulse = 0.85 + Math.sin(elapsed * 5.2) * 0.15;
        domeMat.opacity = 0.14 * pulse * fade;
        latticeMat.opacity = 0.28 * fade;
        groundMat.opacity = 0.72 * fade;
        lattice.rotation.y += dt * 0.18;
        bands.forEach((b, idx) => {
          b.rotation.z += dt * (idx % 2 === 0 ? 0.55 : -0.45);
          bandMats[idx].opacity = 0.85 * fade;
        });
      },
      dispose: () => {
        this.scene.remove(group);
        domeGeo.dispose();
        domeMat.dispose();
        latticeMat.dispose();
        groundMat.dispose();
        bands.forEach((b) => b.geometry.dispose());
        bandMats.forEach((m) => m.dispose());
      },
    };
  }

  /** Crisp shield ripple flash where Drive's Guardrail intercepts an enemy bullet. */
  public spawnGuardrailIntercept(pos: THREE.Vector3, domeCenter: THREE.Vector3): void {
    const mat = new THREE.MeshBasicMaterial({
      color: 0x6ee7b7,
      transparent: true,
      opacity: 0.95,
      side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const ring = new THREE.Mesh(this.unitTorusGeo, mat);
    ring.position.copy(pos);
    ring.lookAt(domeCenter);
    ring.scale.setScalar(0.25);

    this.addEffect(ring, 0.28, (_dt, p) => {
      ring.scale.setScalar(0.25 + p * 1.4);
      mat.opacity = 0.95 * (1 - p);
    });
    for (let i = 0; i < 6; i++) {
      const vel = new THREE.Vector3(
        (Math.random() - 0.5) * 6,
        1 + Math.random() * 4,
        (Math.random() - 0.5) * 6
      );
      this.spawnSpark(pos, vel, 0x34a853, 0.24, 0.9, 0.05, 10);
    }
  }

  /**
   * Google Calendar Ultimate — "Hard Stop (Time Block)"
   * 20m cobalt chrono-field with rotating clock hands, tick perimeter, and chrono pillars.
   */
  public createCalendarChronoField(center: THREE.Vector3, radius: number): PersistentZoneVisual {
    const group = new THREE.Group();
    group.position.copy(center);

    const discGeo = new THREE.CircleGeometry(radius, 48);
    discGeo.rotateX(-Math.PI / 2);
    const discMat = new THREE.MeshBasicMaterial({
      color: 0x4285f4,
      transparent: true,
      opacity: 0.16,
      side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const disc = new THREE.Mesh(discGeo, discMat);
    disc.position.y = 0.08;
    group.add(disc);

    const outerRingMat = new THREE.MeshBasicMaterial({
      color: 0x60a5fa,
      transparent: true,
      opacity: 0.85,
      side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const outerRing = new THREE.Mesh(this.unitRingGeo, outerRingMat);
    outerRing.scale.setScalar(radius);
    outerRing.position.y = 0.12;
    group.add(outerRing);

    // Sweeping minute & hour hands
    const handMat = new THREE.MeshBasicMaterial({
      color: 0xbfdbfe,
      transparent: true,
      opacity: 0.78,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const minuteHand = new THREE.Mesh(this.unitBoxGeo, handMat);
    minuteHand.scale.set(0.26, 0.06, radius * 0.88);
    minuteHand.position.set(0, 0.16, -radius * 0.44);
    const minutePivot = new THREE.Group();
    minutePivot.add(minuteHand);
    group.add(minutePivot);

    const hourHand = new THREE.Mesh(this.unitBoxGeo, handMat);
    hourHand.scale.set(0.38, 0.06, radius * 0.56);
    hourHand.position.set(0, 0.17, -radius * 0.28);
    const hourPivot = new THREE.Group();
    hourPivot.add(hourHand);
    group.add(hourPivot);

    // 12 vertical holographic clock-hour pillars around the rim
    const pillarMat = new THREE.MeshBasicMaterial({
      color: 0x3b82f6,
      transparent: true,
      opacity: 0.42,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const pillars: THREE.Mesh[] = [];
    for (let i = 0; i < 12; i++) {
      const ang = (i / 12) * Math.PI * 2;
      const p = new THREE.Mesh(this.unitCylinderGeo, pillarMat);
      p.scale.set(0.16, 4.4, 0.16);
      p.position.set(Math.cos(ang) * radius, 2.2, Math.sin(ang) * radius);
      group.add(p);
      pillars.push(p);
    }

    this.scene.add(group);
    this.triggerFlashLight(center.clone().add(new THREE.Vector3(0, 3, 0)), 0x4285f4, 8, 28, 0.5);

    return {
      group,
      update: (dt, elapsed, remaining) => {
        const fade = remaining < 0.75 ? Math.max(0, remaining / 0.75) : 1;
        minutePivot.rotation.y -= dt * 1.9;
        hourPivot.rotation.y -= dt * 0.45;
        const pulse = 0.82 + Math.sin(elapsed * 4.5) * 0.18;
        discMat.opacity = 0.16 * pulse * fade;
        outerRingMat.opacity = 0.85 * fade;
        handMat.opacity = 0.78 * fade;
        pillarMat.opacity = 0.42 * pulse * fade;
      },
      dispose: () => {
        this.scene.remove(group);
        discGeo.dispose();
        discMat.dispose();
        outerRingMat.dispose();
        handMat.dispose();
        pillarMat.dispose();
      },
    };
  }

  /**
   * Google Chat Ultimate — "@all Ping Overload"
   * Expanding 28m emerald sonar dome + double shockwave rings.
   */
  public spawnChatPingWave(center: THREE.Vector3, maxRadius = 28): void {
    const domeMat = new THREE.MeshBasicMaterial({
      color: 0x10b981,
      transparent: true,
      opacity: 0.34,
      side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const dome = new THREE.Mesh(this.unitSphereGeo, domeMat);
    dome.position.copy(center).add(new THREE.Vector3(0, 0.8, 0));
    dome.scale.setScalar(0.5);

    this.addEffect(dome, 0.75, (_dt, p) => {
      const ease = 1 - Math.pow(1 - p, 2.2);
      dome.scale.setScalar(0.5 + ease * maxRadius);
      domeMat.opacity = 0.36 * (1 - p);
    });

    this.spawnExpandingRing(center, maxRadius, 0x34d399, 0.75);
    this.spawnExpandingRing(center, maxRadius * 0.78, 0x6ee7b7, 0.55);
    this.triggerFlashLight(center.clone().add(new THREE.Vector3(0, 2, 0)), 0x10b981, 10, 32, 0.45);
  }

  /**
   * Google Slides Ultimate — "Executive Spotlight"
   * Step 1: 0.3s crisp golden windup laser sightline.
   */
  public spawnSlidesChargeBeam(
    origin: THREE.Vector3,
    dir: THREE.Vector3,
    length = 85,
    duration = 0.3
  ): void {
    const normDir = dir.clone().normalize();
    const mat = new THREE.MeshBasicMaterial({
      color: 0xfbbc04,
      transparent: true,
      opacity: 0.75,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const beam = new THREE.Mesh(this.unitCylinderGeo, mat);
    beam.position.copy(origin).addScaledVector(normDir, length * 0.5);
    beam.quaternion.setFromUnitVectors(this.upAxis, normDir);
    beam.scale.set(0.11, length, 0.11);

    this.addEffect(beam, duration, (_dt, p) => {
      const w = 0.08 + p * 0.22;
      beam.scale.set(w, length, w);
      mat.opacity = 0.45 + p * 0.5;
    });
    this.triggerFlashLight(origin, 0xfbbc04, 6.5, 16, duration);
  }

  /**
   * Google Slides Ultimate — "Executive Spotlight"
   * Step 2: Piercing 85m × 2.4m golden orbital projection beam.
   */
  public spawnSlidesOrbitalBeam(
    origin: THREE.Vector3,
    dir: THREE.Vector3,
    length = 85,
    width = 2.4
  ): void {
    const normDir = dir.clone().normalize();
    const group = new THREE.Group();
    group.position.copy(origin).addScaledVector(normDir, length * 0.5);
    group.quaternion.setFromUnitVectors(this.upAxis, normDir);

    const coreMat = new THREE.MeshBasicMaterial({
      color: 0xfffbeb,
      transparent: true,
      opacity: 0.98,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const core = new THREE.Mesh(this.closedCylinderGeo, coreMat);
    core.scale.set(width * 0.24, length, width * 0.24);
    group.add(core);

    const outerMat = new THREE.MeshBasicMaterial({
      color: 0xfbbc04,
      transparent: true,
      opacity: 0.62,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const outer = new THREE.Mesh(this.unitCylinderGeo, outerMat);
    outer.scale.set(width * 0.54, length, width * 0.54);
    group.add(outer);

    // 5 golden projection aperture rings spaced along beam
    const ringMat = new THREE.MeshBasicMaterial({
      color: 0xfef08a,
      transparent: true,
      opacity: 0.85,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const rings: THREE.Mesh[] = [];
    for (let i = 0; i < 5; i++) {
      const r = new THREE.Mesh(this.unitTorusGeo, ringMat);
      r.rotation.x = Math.PI / 2;
      r.position.y = -length * 0.5 + 3 + i * (length / 5.5);
      r.scale.setScalar(width * 0.65);
      group.add(r);
      rings.push(r);
    }

    this.triggerFlashLight(origin, 0xfbbc04, 12, 34, 0.4);

    this.addEffect(group, 0.58, (_dt, p) => {
      const fade = Math.max(0, 1 - p);
      const radiusFactor = 1.15 - p * 0.65;
      core.scale.set(width * 0.24 * radiusFactor, length, width * 0.24 * radiusFactor);
      outer.scale.set(width * 0.58 * (1 + p * 0.2), length, width * 0.58 * (1 + p * 0.2));
      coreMat.opacity = 0.98 * fade;
      outerMat.opacity = 0.62 * fade;
      ringMat.opacity = 0.85 * fade;
      rings.forEach((r) => r.scale.setScalar(width * (0.65 + p * 0.6)));
    });
  }

  /**
   * Google Docs Ultimate — "Version History (Rollback)"
   * Spawns a luminous blue Doc-cursor silhouette ghost along the 0.45s rewind trail.
   */
  public spawnDocsGhostTrail(pos: THREE.Vector3, yaw: number): void {
    const group = new THREE.Group();
    group.position.copy(pos);
    group.rotation.y = yaw;

    const bodyMat = new THREE.MeshBasicMaterial({
      color: 0x4285f4,
      transparent: true,
      opacity: 0.58,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const body = new THREE.Mesh(this.closedCylinderGeo, bodyMat);
    body.scale.set(0.28, 1.35, 0.22);
    body.position.y = 0.88;
    group.add(body);

    const head = new THREE.Mesh(this.lowSphereGeo, bodyMat);
    head.scale.setScalar(0.19);
    head.position.y = 1.66;
    group.add(head);

    // Tall bright blue Google Docs cursor bar beside ghost
    const cursorMat = new THREE.MeshBasicMaterial({
      color: 0x93c5fd,
      transparent: true,
      opacity: 0.9,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const cursorBar = new THREE.Mesh(this.unitBoxGeo, cursorMat);
    cursorBar.scale.set(0.05, 1.95, 0.05);
    cursorBar.position.set(0.36, 1.0, 0);
    group.add(cursorBar);

    this.addEffect(group, 0.48, (_dt, p) => {
      bodyMat.opacity = 0.58 * (1 - p);
      cursorMat.opacity = 0.9 * (1 - p);
      group.position.y += 0.008;
    });
  }

  /** Google Docs Ultimate — 12m Redline Pulse at departure point. */
  public spawnDocsRedlinePulse(center: THREE.Vector3, radius = 12): void {
    this.spawnExpandingRing(center, radius, 0xea4335, 0.52);
    this.spawnExpandingRing(center, radius * 0.82, 0x4285f4, 0.46);
    this.triggerFlashLight(center.clone().add(new THREE.Vector3(0, 1.4, 0)), 0x4285f4, 8, 22, 0.35);

    for (let i = 0; i < 18; i++) {
      const a = (i / 18) * Math.PI * 2;
      const spd = 7 + Math.random() * 6;
      this.spawnSpark(
        center.clone().add(new THREE.Vector3(0, 1.0, 0)),
        new THREE.Vector3(Math.cos(a) * spd, 2 + Math.random() * 4, Math.sin(a) * spd),
        i % 2 === 0 ? 0x60a5fa : 0xf87171,
        0.4,
        1.3,
        0.08,
        11
      );
    }
  }

  /** Expanding luminous ground ring utility. */
  public spawnExpandingRing(
    center: THREE.Vector3,
    maxRadius: number,
    color: number,
    ttl = 0.5
  ): void {
    const mat = new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      opacity: 0.9,
      side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const ring = new THREE.Mesh(this.unitRingGeo, mat);
    ring.position.set(center.x, center.y + 0.14, center.z);
    ring.scale.setScalar(0.4);

    this.addEffect(ring, ttl, (_dt, p) => {
      const ease = 1 - Math.pow(1 - p, 2.4);
      ring.scale.setScalar(0.4 + ease * maxRadius);
      mat.opacity = 0.9 * (1 - p);
    });
  }

  /** Healing / Shield / Mana completion burst around a combatant. */
  public spawnStatusBurst(pos: THREE.Vector3, color: number): void {
    this.spawnExpandingRing(pos, 2.2, color, 0.42);
    for (let i = 0; i < 14; i++) {
      const a = (i / 14) * Math.PI * 2;
      const r = 0.45 + Math.random() * 0.35;
      const start = new THREE.Vector3(
        pos.x + Math.cos(a) * r,
        pos.y + 0.3 + Math.random() * 0.6,
        pos.z + Math.sin(a) * r
      );
      this.spawnSpark(
        start,
        new THREE.Vector3(Math.cos(a) * 0.8, 3.2 + Math.random() * 2.4, Math.sin(a) * 0.8),
        color,
        0.55,
        1.1,
        0.1,
        -2.5
      );
    }
  }

  /** Impulse Booster turbine blast underneath combatant. */
  public spawnImpulseBurst(pos: THREE.Vector3): void {
    this.spawnExpandingRing(pos, 3.6, 0xf59e0b, 0.38);
    this.triggerFlashLight(pos, 0xf59e0b, 7, 14, 0.22);
    for (let i = 0; i < 16; i++) {
      const a = Math.random() * Math.PI * 2;
      const spd = 2.5 + Math.random() * 4.5;
      this.spawnSpark(
        pos,
        new THREE.Vector3(Math.cos(a) * spd, -2 + Math.random() * 3.5, Math.sin(a) * spd),
        i % 2 === 0 ? 0xfbbf24 : 0x38bdf8,
        0.38,
        1.3,
        0.08,
        6
      );
    }
  }

  /** Subtle glider contrail spark while sky-dropping. */
  public spawnGliderTrail(pos: THREE.Vector3): void {
    this.spawnSpark(
      pos,
      new THREE.Vector3((Math.random() - 0.5) * 0.4, 0.3, (Math.random() - 0.5) * 0.4),
      0xe0f2fe,
      0.32,
      0.55,
      0.02,
      -0.5
    );
  }

  /**
   * Surface-tinted dust puffs & friction debris kicking back-and-up behind a sliding hero's heels.
   */
  public spawnSlideDust(
    pos: THREE.Vector3,
    dirX: number,
    dirZ: number,
    surface: 'grass' | 'stone' | 'sand' | 'metal',
    initialBurst = false
  ): void {
    const count = initialBurst ? 4 : Math.random() < 0.5 ? 2 : 3;
    const palette: [number, number] =
      surface === 'grass'
        ? [0xd4e2b6, 0xa8c284]
        : surface === 'sand'
          ? [0xf0d6a4, 0xdfb974]
          : surface === 'metal'
            ? [0xdbe4ee, 0x94a3b8]
            : [0xe8edf3, 0xcbd5e1];

    const perpX = -dirZ;
    const perpZ = dirX;

    for (let i = 0; i < count; i++) {
      if (this.particles.length > 180) break;
      const lat = (Math.random() - 0.5) * 0.44;
      const back = 0.08 + Math.random() * 0.30;
      const startPos = new THREE.Vector3(
        pos.x - dirX * back + perpX * lat,
        pos.y + 0.05 + Math.random() * 0.08,
        pos.z - dirZ * back + perpZ * lat
      );
      const backSpeed = 2.4 + Math.random() * 2.2;
      const latSpeed = (Math.random() - 0.5) * 1.9;
      const vel = new THREE.Vector3(
        -dirX * backSpeed + perpX * latSpeed,
        0.55 + Math.random() * 0.75,
        -dirZ * backSpeed + perpZ * latSpeed
      );
      const baseOpacity = initialBurst ? 0.46 : 0.36;
      const mat = new THREE.MeshBasicMaterial({
        color: palette[i % 2],
        transparent: true,
        opacity: baseOpacity,
        depthWrite: false,
      });
      const mesh = new THREE.Mesh(this.unitSphereGeo, mat);
      const startScale = (initialBurst ? 0.11 : 0.085) + Math.random() * 0.035;
      const endScale = startScale * (2.2 + Math.random() * 0.55);
      mesh.position.copy(startPos);
      mesh.scale.setScalar(startScale);
      this.scene.add(mesh);
      this.particles.push({
        mesh,
        vel,
        gravity: 1.6,
        age: 0,
        ttl: 0.28 + Math.random() * 0.14,
        startScale,
        endScale,
        baseOpacity,
      });
    }

    // Crisp surface flecks / sparks kicking up from sliding heel
    if (this.particles.length <= 180) {
      const sparkPos = new THREE.Vector3(
        pos.x - dirX * 0.18 + perpX * (Math.random() - 0.5) * 0.28,
        pos.y + 0.06,
        pos.z - dirZ * 0.18 + perpZ * (Math.random() - 0.5) * 0.28
      );
      const sparkVel = new THREE.Vector3(
        -dirX * (3.6 + Math.random() * 2.4) + perpX * (Math.random() - 0.5) * 2.4,
        1.4 + Math.random() * 1.6,
        -dirZ * (3.6 + Math.random() * 2.4) + perpZ * (Math.random() - 0.5) * 2.4
      );
      const sparkColor =
        surface === 'metal'
          ? Math.random() < 0.5
            ? 0xfde68a
            : 0x7dd3fc
          : surface === 'grass'
            ? 0xbef264
            : surface === 'sand'
              ? 0xfde08d
              : 0xe2e8f0;
      this.spawnSpark(
        sparkPos,
        sparkVel,
        sparkColor,
        0.24,
        surface === 'metal' ? 0.72 : 0.42,
        0.03,
        14
      );
    }
  }

  /**
   * Builds a sleek curved translucent Hard-Light Cover energy barrier mesh.
   * Width ~3.8m, Height ~2.15m, grounded at local Y=0.
   */
  public createHardLightCoverMesh(width: number, height: number, rarityColor: number): THREE.Group {
    const group = new THREE.Group();

    // Base metallic emitter rail
    const baseGeo = new THREE.BoxGeometry(width * 0.94, 0.22, 0.34);
    const baseMat = new THREE.MeshStandardMaterial({
      color: 0x1e293b,
      metalness: 0.78,
      roughness: 0.28,
    });
    const base = new THREE.Mesh(baseGeo, baseMat);
    base.position.y = 0.11;
    base.castShadow = false;
    base.receiveShadow = true;
    group.add(base);

    // Subtle curved energy wall using a wide cylinder segment
    const arcRadius = width * 1.45;
    const arcAngle = width / arcRadius;
    const wallGeo = new THREE.CylinderGeometry(
      arcRadius,
      arcRadius,
      height - 0.2,
      18,
      4,
      true,
      -arcAngle * 0.5,
      arcAngle
    );
    // Shift so center of curved arc sits at local Z=0
    wallGeo.translate(0, (height - 0.2) * 0.5 + 0.18, -arcRadius);

    const wallMat = new THREE.MeshPhysicalMaterial({
      color: 0x38bdf8,
      emissive: rarityColor,
      emissiveIntensity: 0.45,
      transparent: true,
      opacity: 0.42,
      roughness: 0.15,
      metalness: 0.1,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    const wall = new THREE.Mesh(wallGeo, wallMat);
    wall.name = 'HardLightWallPanel';
    wall.castShadow = false;
    group.add(wall);

    // Crisp hex-grid wireframe overlay
    const wireMat = new THREE.MeshBasicMaterial({
      color: rarityColor,
      wireframe: true,
      transparent: true,
      opacity: 0.55,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const wire = new THREE.Mesh(wallGeo, wireMat);
    wire.castShadow = false;
    group.add(wire);

    // Top glowing edge rail
    const topGeo = new THREE.BoxGeometry(width * 0.96, 0.08, 0.08);
    const topMat = new THREE.MeshBasicMaterial({
      color: 0xe0f2fe,
      transparent: true,
      opacity: 0.9,
    });
    const topRail = new THREE.Mesh(topGeo, topMat);
    topRail.position.y = height - 0.02;
    topRail.castShadow = false;
    group.add(topRail);

    return group;
  }

  /** Golden vertical Supply Drop sky-beacon + pulsing flare ring. */
  public createSupplyDropBeacon(): THREE.Group {
    const group = new THREE.Group();
    const beamGeo = new THREE.CylinderGeometry(0.45, 1.35, 130, 14, 1, true);
    const beamMat = new THREE.MeshBasicMaterial({
      color: 0xfbbf24,
      transparent: true,
      opacity: 0.22,
      side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const beam = new THREE.Mesh(beamGeo, beamMat);
    beam.position.y = 65;
    group.add(beam);

    const innerGeo = new THREE.CylinderGeometry(0.14, 0.32, 130, 10, 1, true);
    const innerMat = new THREE.MeshBasicMaterial({
      color: 0xfef3c7,
      transparent: true,
      opacity: 0.42,
      side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const inner = new THREE.Mesh(innerGeo, innerMat);
    inner.position.y = 65;
    group.add(inner);

    const groundRing = new THREE.Mesh(
      this.unitRingGeo,
      new THREE.MeshBasicMaterial({
        color: 0xf59e0b,
        transparent: true,
        opacity: 0.72,
        side: THREE.DoubleSide,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      })
    );
    groundRing.scale.setScalar(3.2);
    groundRing.position.y = 0.14;
    group.add(groundRing);

    return group;
  }

  public update(dt: number): void {
    // Update transient effects
    for (let i = this.effects.length - 1; i >= 0; i--) {
      const fx = this.effects[i];
      fx.age += dt;
      const progress = Math.min(1, fx.age / Math.max(fx.ttl, 0.001));
      fx.update(dt, progress);
      if (fx.age >= fx.ttl) {
        this.scene.remove(fx.object);
        if (fx.disposeMaterials) {
          fx.object.traverse((child) => {
            if (child instanceof THREE.Mesh) {
              if (Array.isArray(child.material)) {
                child.material.forEach((m) => m.dispose());
              } else {
                child.material.dispose();
              }
            }
          });
        }
        this.effects.splice(i, 1);
      }
    }

    // Update spark particles
    for (let i = this.particles.length - 1; i >= 0; i--) {
      const pt = this.particles[i];
      pt.age += dt;
      if (pt.age >= pt.ttl) {
        this.scene.remove(pt.mesh);
        (pt.mesh.material as THREE.Material).dispose();
        this.particles.splice(i, 1);
        continue;
      }
      const p = pt.age / pt.ttl;
      pt.vel.y -= pt.gravity * dt;
      pt.mesh.position.addScaledVector(pt.vel, dt);
      if (pt.rotVel) {
        pt.mesh.rotation.x += pt.rotVel.x * dt;
        pt.mesh.rotation.y += pt.rotVel.y * dt;
        pt.mesh.rotation.z += pt.rotVel.z * dt;
      } else {
        pt.mesh.rotation.x += dt * 7;
        pt.mesh.rotation.y += dt * 5;
      }
      const scale = pt.startScale + (pt.endScale - pt.startScale) * p;
      pt.mesh.scale.setScalar(Math.max(0.01, scale));
      (pt.mesh.material as THREE.MeshBasicMaterial).opacity = (pt.baseOpacity ?? 0.95) * (1 - p);
    }

    // Update pooled flash lights
    for (const fl of this.lights) {
      if (!fl.light.visible) continue;
      fl.age += dt;
      if (fl.age >= fl.ttl) {
        fl.light.visible = false;
        fl.light.intensity = 0;
      } else {
        fl.light.intensity = fl.peakIntensity * (1 - fl.age / fl.ttl);
      }
    }
  }

  public clear(): void {
    for (const fx of this.effects) {
      this.scene.remove(fx.object);
      if (fx.disposeMaterials) {
        fx.object.traverse((child) => {
          if (child instanceof THREE.Mesh) {
            if (Array.isArray(child.material)) {
              child.material.forEach((m) => m.dispose());
            } else {
              child.material.dispose();
            }
          }
        });
      }
    }
    this.effects.length = 0;

    for (const pt of this.particles) {
      this.scene.remove(pt.mesh);
      (pt.mesh.material as THREE.Material).dispose();
    }
    this.particles.length = 0;

    for (const fl of this.lights) {
      fl.light.visible = false;
      fl.light.intensity = 0;
    }
  }
}

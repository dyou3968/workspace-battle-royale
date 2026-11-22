import * as THREE from 'three';
import { GAME_CONSTANTS } from '../data/catalog';

export type CameraRaycastFn = (
  origin: THREE.Vector3,
  dir: THREE.Vector3,
  maxDist: number
) => number;

export interface CameraUpdateInput {
  dt: number;
  playerPos: THREE.Vector3;
  yaw: number;
  pitch: number;
  crouching: boolean;
  sliding?: boolean;
  sprinting: boolean;
  isAds: boolean;
  sniperScope: boolean;
  skyDropping: boolean;
  dead: boolean;
  raycastDist: CameraRaycastFn;
}

/**
 * Third-person over-the-right-shoulder spring-arm camera controller.
 * - Normal FOV: 68° | Ground ADS FOV: 31° | Longbow .308 Sniper Scope FOV: 16°
 * - Ceiling-aware & wall-whiskered spring-arm avoidance (smooth indoors & zero wall clipping)
 * - Smooth crouch eye-height drop, sky-drop panoramic view, and recoil/impact shake
 */
export class ThirdPersonCamera {
  public readonly camera: THREE.PerspectiveCamera;

  private currentFov = 68;
  private currentEyeHeight: number = GAME_CONSTANTS.EYE_HEIGHT_STANDING;
  private currentBackDist = 3.8;
  private currentRightOffset = 0.72;
  private currentUpOffset = 0.24;
  private currentRoll = 0;
  private smoothArmDist = 3.8;
  private smoothShoulderScale = 1.0;

  private shakeIntensity = 0;
  private shakeDecay = 8.5;
  private recoilPitch = 0;
  private spectatorAngle = 0;

  private readonly pivot = new THREE.Vector3();
  private readonly shoulderPos = new THREE.Vector3();
  private readonly desiredPos = new THREE.Vector3();
  private readonly forward = new THREE.Vector3();
  private readonly right = new THREE.Vector3();
  private readonly up = new THREE.Vector3(0, 1, 0);
  private readonly armDir = new THREE.Vector3();
  private readonly probeDir = new THREE.Vector3();
  private readonly probeTarget = new THREE.Vector3();
  private readonly lookTarget = new THREE.Vector3();
  private readonly aimRayDir = new THREE.Vector3();

  constructor(aspect: number) {
    this.camera = new THREE.PerspectiveCamera(68, aspect, 0.12, 620);
  }

  public resize(width: number, height: number): void {
    this.camera.aspect = Math.max(width, 1) / Math.max(height, 1);
    this.camera.updateProjectionMatrix();
  }

  public addShake(amount: number): void {
    this.shakeIntensity = Math.min(0.45, this.shakeIntensity + amount);
  }

  public addRecoil(pitchKickRad: number): void {
    this.recoilPitch = Math.min(0.14, this.recoilPitch + pitchKickRad);
  }

  public reset(playerPos: THREE.Vector3, yaw: number): void {
    this.currentFov = 78;
    this.currentEyeHeight = GAME_CONSTANTS.EYE_HEIGHT_STANDING;
    this.currentBackDist = 6.2;
    this.currentRightOffset = 0;
    this.currentUpOffset = 1.4;
    this.currentRoll = 0;
    this.smoothArmDist = 6.2;
    this.smoothShoulderScale = 1.0;
    this.shakeIntensity = 0;
    this.recoilPitch = 0;
    this.spectatorAngle = yaw;
    this.camera.fov = this.currentFov;
    this.camera.updateProjectionMatrix();
    this.camera.position.set(
      playerPos.x + Math.sin(yaw) * 6.2,
      playerPos.y + 3.0,
      playerPos.z + Math.cos(yaw) * 6.2
    );
    this.camera.lookAt(playerPos.x, playerPos.y + 1.5, playerPos.z);
  }

  public update(input: CameraUpdateInput): void {
    const {
      dt,
      playerPos,
      yaw,
      pitch,
      crouching,
      sliding = false,
      sprinting,
      isAds,
      sniperScope,
      skyDropping,
      dead,
      raycastDist,
    } = input;

    // Decay recoil kick and screen shake smoothly
    const recoilLerp = Math.min(1, dt * 14);
    this.recoilPitch *= Math.max(0, 1 - recoilLerp);
    if (this.shakeIntensity > 0) {
      this.shakeIntensity = Math.max(0, this.shakeIntensity - this.shakeDecay * dt);
    }

    if (dead) {
      this.spectatorAngle += dt * 0.28;
      const orbitDist = 11.5;
      const targetFov = 68;
      this.currentFov += (targetFov - this.currentFov) * Math.min(1, dt * 6);
      this.camera.fov = this.currentFov;
      this.camera.updateProjectionMatrix();
      this.camera.position.set(
        playerPos.x + Math.sin(this.spectatorAngle) * orbitDist,
        playerPos.y + 6.4,
        playerPos.z + Math.cos(this.spectatorAngle) * orbitDist
      );
      this.camera.lookAt(playerPos.x, playerPos.y + 1.1, playerPos.z);
      return;
    }

    const effectivePitch = Math.max(-1.22, Math.min(1.18, pitch + this.recoilPitch));

    // Target camera profile per stance/mode
    // Standing/Crouch Normal: FOV 68°, backDist 3.8m, rightOffset 0.72m
    let targetFov = 68;
    let targetBack = 3.8;
    let targetRight = 0.72;
    let targetUp = crouching ? 0.2 : 0.24;

    if (skyDropping) {
      targetFov = sprinting ? 84 : 76;
      targetBack = sprinting ? 5.6 : 6.4;
      targetRight = 0.0;
      targetUp = 1.45;
    } else if (sniperScope) {
      // Longbow .308 Sniper Scope ADS: razor-sharp 16° FOV at 0.85m backDist
      targetFov = 16;
      targetBack = 0.85;
      targetRight = 0.0;
      targetUp = 0.06;
    } else if (isAds) {
      // Tight tactical Ground ADS (AR / SMG / Shotgun / Launcher): 31° FOV, hero cleanly left of crosshair
      targetFov = 31;
      targetBack = 1.82;
      targetRight = 0.58;
      targetUp = 0.16;
    } else if (sliding) {
      targetFov = 76;
      targetBack = 4.05;
      targetRight = 0.74;
      targetUp = 0.16;
    } else if (sprinting) {
      targetFov = 73;
      targetBack = 4.15;
      targetRight = 0.74;
      targetUp = 0.26;
    }

    const targetEye =
      sliding && !isAds && !sniperScope
        ? GAME_CONSTANTS.EYE_HEIGHT_SLIDING
        : crouching
          ? GAME_CONSTANTS.EYE_HEIGHT_CROUCHING
          : GAME_CONSTANTS.EYE_HEIGHT_STANDING;

    // Fast, responsive zoom-in lerp (14/s for ground ADS, 18/s for Sniper Scope)
    const blendRate = sniperScope ? 18 : isAds ? 14 : 11;
    const blend = Math.min(1, dt * blendRate);
    this.currentFov += (targetFov - this.currentFov) * blend;
    this.currentEyeHeight += (targetEye - this.currentEyeHeight) * Math.min(1, dt * 13);
    this.currentBackDist += (targetBack - this.currentBackDist) * blend;
    this.currentRightOffset += (targetRight - this.currentRightOffset) * blend;
    this.currentUpOffset += (targetUp - this.currentUpOffset) * blend;

    const targetRoll = sliding && !isAds && !sniperScope && !skyDropping ? -0.026 : 0;
    this.currentRoll += (targetRoll - this.currentRoll) * Math.min(1, dt * 11);

    if (Math.abs(this.camera.fov - this.currentFov) > 0.01) {
      this.camera.fov = this.currentFov;
      this.camera.updateProjectionMatrix();
    }

    // Forward look vector from (yaw, pitch): yaw=0 faces -Z (North)
    const cosPitch = Math.cos(effectivePitch);
    const sinPitch = Math.sin(effectivePitch);
    const sinYaw = Math.sin(yaw);
    const cosYaw = Math.cos(yaw);

    this.forward.set(-sinYaw * cosPitch, sinPitch, -cosYaw * cosPitch).normalize();
    // Right vector in XZ plane: cross(forward, worldUp)
    this.right.set(cosYaw, 0, -sinYaw).normalize();

    // Shoulder/eye pivot on the combatant
    this.pivot.set(
      playerPos.x,
      playerPos.y + this.currentEyeHeight,
      playerPos.z
    );

    // 1. Check horizontal shoulder clearance so standing beside an interior office wall
    //    or doorway jamb smoothly tucks the right-shoulder offset instead of clipping/snapping
    let targetShoulderScale = 1.0;
    if (!skyDropping && Math.abs(this.currentRightOffset) > 0.05) {
      const shLen = Math.hypot(this.currentRightOffset, this.currentUpOffset);
      this.probeDir
        .copy(this.right)
        .multiplyScalar(this.currentRightOffset)
        .addScaledVector(this.up, this.currentUpOffset)
        .divideScalar(shLen);
      const shHit = raycastDist(this.pivot, this.probeDir, shLen + 0.24);
      if (shHit < shLen + 0.24) {
        targetShoulderScale = Math.max(0.18, Math.min(1.0, (shHit - 0.24) / shLen));
      }
    }
    const shRate = targetShoulderScale < this.smoothShoulderScale ? 22 : 9;
    this.smoothShoulderScale += (targetShoulderScale - this.smoothShoulderScale) * Math.min(1, dt * shRate);

    this.shoulderPos
      .copy(this.pivot)
      .addScaledVector(this.right, this.currentRightOffset * this.smoothShoulderScale)
      .addScaledVector(this.up, this.currentUpOffset * this.smoothShoulderScale);

    // 2. Compute desired over-the-shoulder camera position
    this.desiredPos
      .copy(this.shoulderPos)
      .addScaledVector(this.forward, -this.currentBackDist);

    // 3. Indoor ceiling clearance probe (smoothly glides beneath Y=5.75m office ceilings
    //    instead of snapping the camera inward when looking downward or jumping indoors)
    if (!skyDropping && this.desiredPos.y > this.pivot.y + 0.15) {
      const maxCeilProbe = Math.min(5.6, (this.desiredPos.y - this.pivot.y) + 0.55);
      const ceilHit = raycastDist(this.pivot, this.up, maxCeilProbe);
      if (ceilHit < maxCeilProbe) {
        const maxCamY = this.pivot.y + ceilHit - 0.30;
        if (this.desiredPos.y > maxCamY) {
          this.desiredPos.y = Math.max(this.pivot.y - 0.1, maxCamY);
        }
      }
    }

    // 4. Multi-probe spring-arm raycast from pivot to desiredPos (center + subtle side/up whiskers)
    this.armDir.subVectors(this.desiredPos, this.pivot);
    const maxArmDist = this.armDir.length();
    if (maxArmDist > 0.05) {
      this.armDir.divideScalar(maxArmDist);
      let minHitDist = raycastDist(this.pivot, this.armDir, maxArmDist);

      // Subtle lateral & vertical clearance whiskers when grounded indoors to catch thin
      // interior wall edges, doorway frames, and ceiling lips before the near plane clips
      if (!skyDropping && maxArmDist > 0.65) {
        const whiskerSpan = 0.14;
        const probes: [number, number][] = [
          [whiskerSpan, 0],
          [-whiskerSpan, 0],
          [0, whiskerSpan],
        ];
        for (let i = 0; i < probes.length; i++) {
          const [wr, wu] = probes[i];
          this.probeTarget
            .copy(this.desiredPos)
            .addScaledVector(this.right, wr)
            .addScaledVector(this.up, wu);
          this.probeDir.subVectors(this.probeTarget, this.pivot);
          const pLen = this.probeDir.length();
          if (pLen > 0.05) {
            this.probeDir.divideScalar(pLen);
            const pHit = raycastDist(this.pivot, this.probeDir, pLen);
            if (pHit < pLen) {
              // Scale back into main arm length proportionally
              const equivDist = (pHit / pLen) * maxArmDist;
              if (equivDist < minHitDist) {
                minHitDist = equivDist;
              }
            }
          }
        }
      }

      const minDist = sniperScope ? 0.28 : 0.42;
      const hardLimit = Math.max(minDist, Math.min(maxArmDist, minHitDist - 0.16));
      const paddedSafe = Math.max(minDist, Math.min(maxArmDist, minHitDist - 0.30));

      // Smooth rapid pull-in (never crossing hard wall limit) + graceful ease-out
      if (paddedSafe < this.smoothArmDist) {
        const pulled = this.smoothArmDist + (paddedSafe - this.smoothArmDist) * Math.min(1, dt * 26);
        this.smoothArmDist = Math.min(hardLimit, pulled);
      } else {
        this.smoothArmDist += (paddedSafe - this.smoothArmDist) * Math.min(1, dt * 8.5);
      }
      this.camera.position.copy(this.pivot).addScaledVector(this.armDir, this.smoothArmDist);
    } else {
      this.camera.position.copy(this.desiredPos);
    }

    // Apply subtle camera shake
    if (this.shakeIntensity > 0.001) {
      const s = this.shakeIntensity;
      this.camera.position.x += (Math.random() - 0.5) * s;
      this.camera.position.y += (Math.random() - 0.5) * s;
      this.camera.position.z += (Math.random() - 0.5) * s;
    }

    // Look down exact center-screen sightline from camera position
    this.lookTarget.copy(this.camera.position).addScaledVector(this.forward, 120);
    this.camera.lookAt(this.lookTarget);

    // Subtle kinetic Dutch roll during tactical slide (around camera local Z, preserves aim ray!)
    if (Math.abs(this.currentRoll) > 0.0002) {
      this.camera.rotateZ(this.currentRoll);
    }
  }

  /**
   * Returns exact world-space camera origin and normalized center-crosshair ray direction
   * for parallax-free third-person aiming.
   */
  public getAimRay(outOrigin: THREE.Vector3, outDir: THREE.Vector3): void {
    outOrigin.copy(this.camera.position);
    this.camera.getWorldDirection(this.aimRayDir);
    outDir.copy(this.aimRayDir).normalize();
  }
}

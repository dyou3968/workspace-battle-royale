import * as THREE from 'three';
import { GAME_CONSTANTS } from '../data/catalog';
import { BoxCollider, HitboxCheckResult } from '../types';

export interface PolygonCollider {
  id: string;
  /** 2D world XZ vertices */
  points: [number, number][];
  minY: number;
  maxY: number;
  minX: number;
  maxX: number;
  minZ: number;
  maxZ: number;
  blocksBullets?: boolean;
  tag?: string;
  /** Internal spatial-grid query deduplication stamp */
  _stamp?: number;
  /** Internal spatial-grid cell bounds */
  _c0?: number;
  _c1?: number;
  _r0?: number;
  _r1?: number;
}

export interface PolygonDoorwaySpec {
  /** Index of polygon edge i -> (i + 1) % points.length */
  edgeIndex: number;
  /** Normalized start/end fraction along the edge in [0, 1] */
  tStart?: number;
  tEnd?: number;
  /** Center fraction along the edge [0, 1] paired with opening width in meters */
  centerT?: number;
  width?: number;
  /** Distance in meters along the edge from vertex i */
  distStart?: number;
  distEnd?: number;
  /** Optional world-space XZ endpoints projected onto the edge */
  worldStart?: [number, number];
  worldEnd?: [number, number];
  /** Clear walkthrough height above minY before the overhead wall lintel begins (default 3.6m) */
  clearHeight?: number;
}

export interface CylinderCollider {
  id: string;
  x: number;
  z: number;
  radius: number;
  minY: number;
  maxY: number;
  blocksBullets?: boolean;
  tag?: string;
  /** Internal spatial-grid query deduplication stamp */
  _stamp?: number;
  /** Internal spatial-grid cell bounds */
  _c0?: number;
  _c1?: number;
  _r0?: number;
  _r1?: number;
}

type IndexedBoxCollider = BoxCollider & {
  _stamp: number;
  _cx: number;
  _cz: number;
  _hx: number;
  _hz: number;
  _cos: number;
  _sin: number;
  _wMinX: number;
  _wMaxX: number;
  _wMinZ: number;
  _wMaxZ: number;
  _c0: number;
  _c1: number;
  _r0: number;
  _r1: number;
};

export interface WorldRaycastHit {
  distance: number;
  point: THREE.Vector3;
  normal: THREE.Vector3;
  colliderId?: string;
  destructible?: boolean;
  tag?: string;
}

export interface MovementResult {
  grounded: boolean;
  groundY: number;
  hitCeiling: boolean;
  surface: 'grass' | 'stone' | 'sand' | 'metal';
}

const MIN_X = GAME_CONSTANTS.ARENA_MIN_X;
const MAX_X = GAME_CONSTANTS.ARENA_MAX_X;
const MIN_Z = GAME_CONSTANTS.ARENA_MIN_Z;
const MAX_Z = GAME_CONSTANTS.ARENA_MAX_Z;

// 2D Uniform Spatial Hash Grid covering [-312..+312] × [-204..+204] with 24m cells (26 × 17 = 442 cells)
const CELL_SIZE = 24;
const INV_CELL_SIZE = 1 / CELL_SIZE;
const SPATIAL_COLS = 26;
const SPATIAL_ROWS = 17;
const SPATIAL_MIN_X = -312;
const SPATIAL_MIN_Z = -204;
const SPATIAL_MAX_X = SPATIAL_MIN_X + SPATIAL_COLS * CELL_SIZE; // +312
const SPATIAL_MAX_Z = SPATIAL_MIN_Z + SPATIAL_ROWS * CELL_SIZE; // +204
const SPATIAL_CELL_COUNT = SPATIAL_COLS * SPATIAL_ROWS; // 442
const SPATIAL_INDEX_EPS = 0.05;

function smoothstep(edge0: number, edge1: number, x: number): number {
  const t = Math.max(0, Math.min(1, (x - edge0) / (edge1 - edge0)));
  return t * t * (3 - 2 * t);
}

/**
 * Spatial collision & ballistics registry for the Mountain View Googleplex arena.
 * Supports:
 *  - Auto-baked heightfield from Blender googleplex_terrain.glb (with analytical fallback)
 *  - 2D Uniform Spatial Hash Grid (24m cells, 26×17) with integer stamp dedup & 2D DDA ray traversal
 *  - Exact 2D polygon prism colliders for angled SGI buildings (B40, B41, B42, B43)
 *  - Axis-aligned & rotated OBB BoxColliders, walkable RampColliders, elevated Platforms
 *  - Destructible Hard-Light Cover barriers & CylinderColliders (trees, pedestals, columns)
 *  - Dual-zone Head Sphere + Torso Capsule segment intersection for crisp headshot crits
 */
export class PhysicsWorld {
  public readonly boxes: BoxCollider[] = [];
  public readonly polygons: PolygonCollider[] = [];
  public readonly cylinders: CylinderCollider[] = [];

  // 2D Spatial Hash Grid cell buckets (zero per-call Set/array allocations)
  private readonly boxCells: IndexedBoxCollider[][] = Array.from({ length: SPATIAL_CELL_COUNT }, () => []);
  private readonly polyCells: PolygonCollider[][] = Array.from({ length: SPATIAL_CELL_COUNT }, () => []);
  private readonly cylCells: CylinderCollider[][] = Array.from({ length: SPATIAL_CELL_COUNT }, () => []);
  private queryStamp = 0;

  // Reusable scratch hit record for zero-allocation primitive raycast tests
  private readonly rayHitScratch = { dist: 0, nx: 0, ny: 0, nz: 0 };

  // Optional baked heightfield from googleplex_terrain.glb (2.5m grid covering [-300..300]x[-190..190])
  private bakedHeights: Float32Array | null = null;
  private readonly gridCols = 241; // 240 steps of 2.5m across 600m
  private readonly gridRows = 153; // 152 steps of 2.5m across 380m
  private readonly gridStep = 2.5;

  private nextColliderSeq = 1;

  private cellCol(x: number): number {
    const c = Math.floor((x - SPATIAL_MIN_X) * INV_CELL_SIZE);
    return c < 0 ? 0 : c >= SPATIAL_COLS ? SPATIAL_COLS - 1 : c;
  }

  private cellRow(z: number): number {
    const r = Math.floor((z - SPATIAL_MIN_Z) * INV_CELL_SIZE);
    return r < 0 ? 0 : r >= SPATIAL_ROWS ? SPATIAL_ROWS - 1 : r;
  }

  private unindexBox(box: IndexedBoxCollider): void {
    for (let r = box._r0; r <= box._r1; r++) {
      const rowOff = r * SPATIAL_COLS;
      for (let c = box._c0; c <= box._c1; c++) {
        const cell = this.boxCells[rowOff + c];
        const idx = cell.indexOf(box);
        if (idx >= 0) {
          const last = cell.length - 1;
          if (idx !== last) cell[idx] = cell[last];
          cell.pop();
        }
      }
    }
  }

  private unindexPolygon(poly: PolygonCollider): void {
    const r0 = poly._r0;
    const r1 = poly._r1;
    const c0 = poly._c0;
    const c1 = poly._c1;
    if (r0 === undefined || r1 === undefined || c0 === undefined || c1 === undefined) return;
    for (let r = r0; r <= r1; r++) {
      const rowOff = r * SPATIAL_COLS;
      for (let c = c0; c <= c1; c++) {
        const cell = this.polyCells[rowOff + c];
        const idx = cell.indexOf(poly);
        if (idx >= 0) {
          const last = cell.length - 1;
          if (idx !== last) cell[idx] = cell[last];
          cell.pop();
        }
      }
    }
  }

  private unindexCylinder(cyl: CylinderCollider): void {
    const r0 = cyl._r0;
    const r1 = cyl._r1;
    const c0 = cyl._c0;
    const c1 = cyl._c1;
    if (r0 === undefined || r1 === undefined || c0 === undefined || c1 === undefined) return;
    for (let r = r0; r <= r1; r++) {
      const rowOff = r * SPATIAL_COLS;
      for (let c = c0; c <= c1; c++) {
        const cell = this.cylCells[rowOff + c];
        const idx = cell.indexOf(cyl);
        if (idx >= 0) {
          const last = cell.length - 1;
          if (idx !== last) cell[idx] = cell[last];
          cell.pop();
        }
      }
    }
  }

  public clear(): void {
    this.boxes.length = 0;
    this.polygons.length = 0;
    this.cylinders.length = 0;
    this.bakedHeights = null;
    this.queryStamp = 0;
    for (let i = 0; i < SPATIAL_CELL_COUNT; i++) {
      this.boxCells[i].length = 0;
      this.polyCells[i].length = 0;
      this.cylCells[i].length = 0;
    }
  }

  public addBox(box: BoxCollider): BoxCollider {
    if (!box.id) {
      box.id = `box_${this.nextColliderSeq++}`;
    }
    const cx = (box.minX + box.maxX) * 0.5;
    const cz = (box.minZ + box.maxZ) * 0.5;
    const hx = (box.maxX - box.minX) * 0.5;
    const hz = (box.maxZ - box.minZ) * 0.5;
    const ry = box.rotationY ?? 0;
    const cos = ry ? Math.cos(ry) : 1;
    const sin = ry ? Math.sin(ry) : 0;
    const aabbHx = ry ? hx * Math.abs(cos) + hz * Math.abs(sin) : hx;
    const aabbHz = ry ? hx * Math.abs(sin) + hz * Math.abs(cos) : hz;
    const wMinX = cx - aabbHx;
    const wMaxX = cx + aabbHx;
    const wMinZ = cz - aabbHz;
    const wMaxZ = cz + aabbHz;

    const c0 = this.cellCol(wMinX - SPATIAL_INDEX_EPS);
    const c1 = this.cellCol(wMaxX + SPATIAL_INDEX_EPS);
    const r0 = this.cellRow(wMinZ - SPATIAL_INDEX_EPS);
    const r1 = this.cellRow(wMaxZ + SPATIAL_INDEX_EPS);

    const indexed = box as IndexedBoxCollider;
    indexed._stamp = 0;
    indexed._cx = cx;
    indexed._cz = cz;
    indexed._hx = hx;
    indexed._hz = hz;
    indexed._cos = cos;
    indexed._sin = sin;
    indexed._wMinX = wMinX;
    indexed._wMaxX = wMaxX;
    indexed._wMinZ = wMinZ;
    indexed._wMaxZ = wMaxZ;
    indexed._c0 = c0;
    indexed._c1 = c1;
    indexed._r0 = r0;
    indexed._r1 = r1;

    this.boxes.push(indexed);
    for (let r = r0; r <= r1; r++) {
      const rowOff = r * SPATIAL_COLS;
      for (let c = c0; c <= c1; c++) {
        this.boxCells[rowOff + c].push(indexed);
      }
    }
    return indexed;
  }

  public addCenteredBox(
    cx: number,
    cy: number,
    cz: number,
    sizeX: number,
    sizeY: number,
    sizeZ: number,
    extra?: Partial<BoxCollider>
  ): BoxCollider {
    return this.addBox({
      minX: cx - sizeX * 0.5,
      maxX: cx + sizeX * 0.5,
      minY: cy - sizeY * 0.5,
      maxY: cy + sizeY * 0.5,
      minZ: cz - sizeZ * 0.5,
      maxZ: cz + sizeZ * 0.5,
      ...extra,
    });
  }

  public addPolygon(
    points: [number, number][],
    minY: number,
    maxY: number,
    tag?: string,
    id?: string
  ): PolygonCollider {
    let minX = Infinity;
    let maxX = -Infinity;
    let minZ = Infinity;
    let maxZ = -Infinity;
    for (const [x, z] of points) {
      if (x < minX) minX = x;
      if (x > maxX) maxX = x;
      if (z < minZ) minZ = z;
      if (z > maxZ) maxZ = z;
    }
    const c0 = this.cellCol(minX - SPATIAL_INDEX_EPS);
    const c1 = this.cellCol(maxX + SPATIAL_INDEX_EPS);
    const r0 = this.cellRow(minZ - SPATIAL_INDEX_EPS);
    const r1 = this.cellRow(maxZ + SPATIAL_INDEX_EPS);

    const poly: PolygonCollider = {
      id: id ?? `poly_${this.nextColliderSeq++}`,
      points,
      minY,
      maxY,
      minX,
      maxX,
      minZ,
      maxZ,
      blocksBullets: true,
      tag,
      _stamp: 0,
      _c0: c0,
      _c1: c1,
      _r0: r0,
      _r1: r1,
    };
    this.polygons.push(poly);
    for (let r = r0; r <= r1; r++) {
      const rowOff = r * SPATIAL_COLS;
      for (let c = c0; c <= c1; c++) {
        this.polyCells[rowOff + c].push(poly);
      }
    }
    return poly;
  }

  /**
   * Builds hollow perimeter wall OBB colliders along every edge of a 2D XZ polygon while
   * carving exact open walkthrough doorway gaps (and optional overhead doorway lintels).
   * Designed to pair with an elevated roof slab polygon (e.g. minY=5.75, maxY=6.40) so
   * combatants can walk, loot, and fight both inside the ground floor and on the rooftop.
   */
  public addHollowPolygonWalls(
    points: [number, number][],
    minY: number,
    maxY: number,
    wallThickness = 0.45,
    doorways: PolygonDoorwaySpec[] = [],
    tag?: string,
    options?: { insetInward?: boolean; addDoorLintels?: boolean; cornerOverlap?: number }
  ): BoxCollider[] {
    const n = points.length;
    if (n < 3) return [];

    const insetInward = options?.insetInward !== false;
    const addDoorLintels = options?.addDoorLintels !== false;
    const cornerOverlap = options?.cornerOverlap ?? 0.12;

    // Signed 2D area in XZ plane determines polygon winding so inward normal works for CW & CCW
    let area2 = 0;
    for (let i = 0; i < n; i++) {
      const [x0, z0] = points[i];
      const [x1, z1] = points[(i + 1) % n];
      area2 += x0 * z1 - x1 * z0;
    }
    const inwardSign = area2 >= 0 ? 1 : -1;

    const created: BoxCollider[] = [];

    for (let edgeIdx = 0; edgeIdx < n; edgeIdx++) {
      const [ax, az] = points[edgeIdx];
      const [bx, bz] = points[(edgeIdx + 1) % n];
      const ex = bx - ax;
      const ez = bz - az;
      const edgeLen = Math.hypot(ex, ez);
      if (edgeLen < 0.05) continue;

      const tx = ex / edgeLen;
      const tz = ez / edgeLen;
      const inX = -tz * inwardSign;
      const inZ = tx * inwardSign;
      const rotY = Math.atan2(-tz, tx);
      const insetDist = insetInward ? wallThickness * 0.5 : 0;

      // Resolve all doorway openings assigned to this edge into [d0, d1] meter intervals
      const edgeDoors: { d0: number; d1: number; clearHeight: number }[] = [];
      for (const d of doorways) {
        if (d.edgeIndex !== edgeIdx) continue;
        let d0 = 0;
        let d1 = 0;
        if (d.distStart !== undefined && d.distEnd !== undefined) {
          d0 = Math.min(d.distStart, d.distEnd);
          d1 = Math.max(d.distStart, d.distEnd);
        } else if (d.tStart !== undefined && d.tEnd !== undefined) {
          d0 = Math.min(d.tStart, d.tEnd) * edgeLen;
          d1 = Math.max(d.tStart, d.tEnd) * edgeLen;
        } else if (d.centerT !== undefined && d.width !== undefined) {
          const center = d.centerT * edgeLen;
          d0 = center - d.width * 0.5;
          d1 = center + d.width * 0.5;
        } else if (d.worldStart && d.worldEnd) {
          const p0 = (d.worldStart[0] - ax) * tx + (d.worldStart[1] - az) * tz;
          const p1 = (d.worldEnd[0] - ax) * tx + (d.worldEnd[1] - az) * tz;
          d0 = Math.min(p0, p1);
          d1 = Math.max(p0, p1);
        } else {
          continue;
        }
        d0 = Math.max(0, Math.min(edgeLen, d0));
        d1 = Math.max(0, Math.min(edgeLen, d1));
        if (d1 - d0 >= 0.2) {
          edgeDoors.push({ d0, d1, clearHeight: d.clearHeight ?? 3.6 });
        }
      }

      edgeDoors.sort((a, b) => a.d0 - b.d0);

      const emitSpan = (
        s0: number,
        s1: number,
        y0: number,
        y1: number,
        isLintel: boolean,
        extendStart: boolean,
        extendEnd: boolean
      ) => {
        const a0 = extendStart ? s0 - cornerOverlap : s0;
        const a1 = extendEnd ? s1 + cornerOverlap : s1;
        const spanLen = a1 - a0;
        if (spanLen < 0.12 || y1 - y0 < 0.05) return;
        const mid = 0.5 * (a0 + a1);
        const cx = ax + tx * mid + inX * insetDist;
        const cz = az + tz * mid + inZ * insetDist;
        created.push(
          this.addCenteredBox(cx, 0.5 * (y0 + y1), cz, spanLen, y1 - y0, wallThickness, {
            rotationY: rotY,
            isPlatform: isLintel,
            blocksBullets: true,
            tag: tag ? (isLintel ? `${tag}_lintel` : `${tag}_wall`) : undefined,
          })
        );
      };

      let cursor = 0;
      for (const door of edgeDoors) {
        if (door.d0 - cursor > 0.15) {
          emitSpan(cursor, door.d0, minY, maxY, false, cursor === 0, false);
        }
        if (addDoorLintels && minY + door.clearHeight < maxY - 0.12) {
          emitSpan(door.d0, door.d1, minY + door.clearHeight, maxY, true, false, false);
        }
        cursor = Math.max(cursor, door.d1);
      }

      if (edgeLen - cursor > 0.15) {
        emitSpan(cursor, edgeLen, minY, maxY, false, cursor === 0, true);
      }
    }

    return created;
  }

  public addCylinder(
    x: number,
    z: number,
    radius: number,
    minY: number,
    maxY: number,
    tag?: string,
    blocksBullets = true
  ): CylinderCollider {
    const c0 = this.cellCol(x - radius - SPATIAL_INDEX_EPS);
    const c1 = this.cellCol(x + radius + SPATIAL_INDEX_EPS);
    const r0 = this.cellRow(z - radius - SPATIAL_INDEX_EPS);
    const r1 = this.cellRow(z + radius + SPATIAL_INDEX_EPS);

    const cyl: CylinderCollider = {
      id: `cyl_${this.nextColliderSeq++}`,
      x,
      z,
      radius,
      minY,
      maxY,
      blocksBullets,
      tag,
      _stamp: 0,
      _c0: c0,
      _c1: c1,
      _r0: r0,
      _r1: r1,
    };
    this.cylinders.push(cyl);
    for (let r = r0; r <= r1; r++) {
      const rowOff = r * SPATIAL_COLS;
      for (let c = c0; c <= c1; c++) {
        this.cylCells[rowOff + c].push(cyl);
      }
    }
    return cyl;
  }

  public addDestructibleCover(
    cx: number,
    baseY: number,
    cz: number,
    width: number,
    height: number,
    thickness: number,
    rotationY: number,
    hp: number,
    ownerId?: string,
    meshId?: string
  ): BoxCollider {
    return this.addBox({
      id: meshId ?? `hlc_${this.nextColliderSeq++}`,
      minX: cx - width * 0.5,
      maxX: cx + width * 0.5,
      minY: baseY,
      maxY: baseY + height,
      minZ: cz - thickness * 0.5,
      maxZ: cz + thickness * 0.5,
      rotationY,
      destructible: true,
      hp,
      maxHp: hp,
      ownerId,
      meshId,
      blocksBullets: true,
      tag: 'hardlight_cover',
    });
  }

  public damageCollider(colliderId: string, damage: number): { destroyed: boolean; remainingHp: number; collider?: BoxCollider } {
    const idx = this.boxes.findIndex((b) => b.id === colliderId || b.meshId === colliderId);
    if (idx < 0) return { destroyed: false, remainingHp: 0 };
    const col = this.boxes[idx];
    if (!col.destructible || col.hp === undefined) {
      return { destroyed: false, remainingHp: Infinity, collider: col };
    }
    col.hp -= damage;
    if (col.hp <= 0) {
      this.boxes.splice(idx, 1);
      this.unindexBox(col as IndexedBoxCollider);
      return { destroyed: true, remainingHp: 0, collider: col };
    }
    return { destroyed: false, remainingHp: col.hp, collider: col };
  }

  public removeCollider(colliderId: string): boolean {
    const idx = this.boxes.findIndex((b) => b.id === colliderId || b.meshId === colliderId);
    if (idx >= 0) {
      const removed = this.boxes[idx] as IndexedBoxCollider;
      this.boxes.splice(idx, 1);
      this.unindexBox(removed);
      return true;
    }
    const pIdx = this.polygons.findIndex((p) => p.id === colliderId);
    if (pIdx >= 0) {
      const removed = this.polygons[pIdx];
      this.polygons.splice(pIdx, 1);
      this.unindexPolygon(removed);
      return true;
    }
    const cIdx = this.cylinders.findIndex((c) => c.id === colliderId);
    if (cIdx >= 0) {
      const removed = this.cylinders[cIdx];
      this.cylinders.splice(cIdx, 1);
      this.unindexCylinder(removed);
      return true;
    }
    return false;
  }

  /**
   * Rasterizes triangles of a loaded terrain mesh (googleplex_terrain.glb) onto a fast
   * 2.5m-cell heightfield (241×153 across 600m×380m) so character grounding matches the Blender terrain 1:1.
   */
  public bakeTerrainHeightfield(terrainRoot: THREE.Object3D): void {
    terrainRoot.updateMatrixWorld(true);
    const cols = this.gridCols;
    const rows = this.gridRows;
    const step = this.gridStep;
    const heights = new Float32Array(cols * rows);
    heights.fill(-9999);

    const vA = new THREE.Vector3();
    const vB = new THREE.Vector3();
    const vC = new THREE.Vector3();
    const e1 = new THREE.Vector3();
    const e2 = new THREE.Vector3();
    const triNormal = new THREE.Vector3();

    terrainRoot.traverse((obj) => {
      if (!(obj as THREE.Mesh).isMesh) return;
      const mesh = obj as THREE.Mesh;
      const geo = mesh.geometry;
      const posAttr = geo.attributes.position;
      if (!posAttr) return;
      const index = geo.index;
      const matWorld = mesh.matrixWorld;
      const triCount = index ? index.count / 3 : posAttr.count / 3;

      for (let t = 0; t < triCount; t++) {
        const i0 = index ? index.getX(t * 3) : t * 3;
        const i1 = index ? index.getX(t * 3 + 1) : t * 3 + 1;
        const i2 = index ? index.getX(t * 3 + 2) : t * 3 + 2;

        vA.fromBufferAttribute(posAttr, i0).applyMatrix4(matWorld);
        vB.fromBufferAttribute(posAttr, i1).applyMatrix4(matWorld);
        vC.fromBufferAttribute(posAttr, i2).applyMatrix4(matWorld);

        // Only bake upward-facing walkable surfaces (ignore steep vertical curb/railing sides)
        e1.subVectors(vB, vA);
        e2.subVectors(vC, vA);
        triNormal.crossVectors(e1, e2);
        const nLen = triNormal.length();
        if (nLen < 1e-6) continue;
        if (Math.abs(triNormal.y) / nLen < 0.45) continue;

        const avgY = (vA.y + vB.y + vC.y) / 3;
        const avgX = (vA.x + vB.x + vC.x) / 3;
        // Skip thin creek bridge guardrails above deck level near Permanente Creek (X=-156)
        if (Math.abs(avgX + 156) < 7.5 && avgY > 0.35) continue;
        // North Bay Point Shoreline Overlook hills reach up to ~8m; ignore abnormally tall structures
        if (avgY > 9.5) continue;

        const triMinX = Math.min(vA.x, vB.x, vC.x);
        const triMaxX = Math.max(vA.x, vB.x, vC.x);
        const triMinZ = Math.min(vA.z, vB.z, vC.z);
        const triMaxZ = Math.max(vA.z, vB.z, vC.z);

        const c0 = Math.max(0, Math.floor((triMinX - MIN_X) / step));
        const c1 = Math.min(cols - 1, Math.ceil((triMaxX - MIN_X) / step));
        const r0 = Math.max(0, Math.floor((triMinZ - MIN_Z) / step));
        const r1 = Math.min(rows - 1, Math.ceil((triMaxZ - MIN_Z) / step));

        const denom = (vB.z - vC.z) * (vA.x - vC.x) + (vC.x - vB.x) * (vA.z - vC.z);
        if (Math.abs(denom) < 1e-6) continue;
        const invDenom = 1 / denom;

        for (let r = r0; r <= r1; r++) {
          const pz = MIN_Z + r * step;
          for (let c = c0; c <= c1; c++) {
            const px = MIN_X + c * step;
            const w0 = ((vB.z - vC.z) * (px - vC.x) + (vC.x - vB.x) * (pz - vC.z)) * invDenom;
            if (w0 < -0.02) continue;
            const w1 = ((vC.z - vA.z) * (px - vC.x) + (vA.x - vC.x) * (pz - vC.z)) * invDenom;
            if (w1 < -0.02) continue;
            const w2 = 1 - w0 - w1;
            if (w2 < -0.02) continue;

            const y = w0 * vA.y + w1 * vB.y + w2 * vC.y;
            const cellIdx = r * cols + c;
            if (y > heights[cellIdx]) {
              heights[cellIdx] = y;
            }
          }
        }
      }
    });

    // Fill any uncovered cells cleanly from analytical fallback and clamp creek depth safely
    let validCount = 0;
    for (let r = 0; r < rows; r++) {
      const pz = MIN_Z + r * step;
      for (let c = 0; c < cols; c++) {
        const px = MIN_X + c * step;
        const idx = r * cols + c;
        if (heights[idx] < -100) {
          heights[idx] = this.getAnalyticalTerrainHeight(px, pz);
        } else {
          heights[idx] = Math.max(-0.65, Math.min(8.8, heights[idx]));
          validCount++;
        }
      }
    }

    if (validCount > cols * rows * 0.4) {
      this.bakedHeights = heights;
    }
  }

  /**
   * Analytical 3× Mountain View Googleplex heightfield (600m × 380m, X∈[-300,+300], Z∈[-190,+190]):
   * - Flat 0.0m across all building pads (B40–B43, Gradient Canopy, Orb Plaza, Shoreline Amphitheatre,
   *   Athletic Field, Google 2000/1950, 1098 Alta, Charleston Campus, Shoreline East offices), plazas & roads
   * - Recessed Permanente Creek channel along X = -156m across full Z∈[-190,+190] (with bridges)
   * - Contoured 0.0–1.35m California Live Oak berms in Charleston Park (+10..+52, -52..+48)
   * - Rolling Bay Point Regional Shoreline Overlook hills north of Amphitheatre Pkwy (Z < -72m, X∈[-140,+20])
   */
  public getAnalyticalTerrainHeight(x: number, z: number): number {
    // Permanente Creek recessed channel at X = -156m across full Z ∈ [-190, +190]
    // Flat bridges at Amphitheatre Pkwy (Z≈-65), Charleston Rd (Z≈+65), & footbridges at Z=-2 and Z=-126
    const creekDist = Math.abs(x + 156);
    if (creekDist < 6.2) {
      const nearNorthRoadBridge = Math.abs(z + 65) < 8.5;
      const nearSouthRoadBridge = Math.abs(z - 65) < 8.5;
      const nearCentralFootbridge = Math.abs(z + 2) < 5.0;
      const nearNorthFootbridge = Math.abs(z + 126) < 5.0;
      if (!nearNorthRoadBridge && !nearSouthRoadBridge && !nearCentralFootbridge && !nearNorthFootbridge) {
        const bank = 1 - smoothstep(2.4, 6.2, creekDist);
        return -0.55 * bank;
      }
    }

    // Keep major boulevards & outer Mountain View arteries cleanly flat
    if (Math.abs(z + 65) < 7.0 || Math.abs(z - 65) < 7.0) return 0; // Amphitheatre Pkwy / Stierlin Ct / Charleston Rd
    if (Math.abs(x - 168) < 8.0) return 0; // N Shoreline Blvd
    if (x > 160 && (Math.abs(z + 108) < 6.5 || Math.abs(z - 160) < 6.5)) return 0; // Crittenden Ln / Shorebird Way
    if (z > 172 && x > -158 && x < 176) return 0; // Plymouth St

    // Keep all 6 expanded outer landmark pads & Parking Lot C cleanly flat (Y = 0)
    if (Math.abs(x - 58) < 38 && Math.abs(z + 148) < 32) return 0;   // Shoreline Amphitheatre
    if (Math.abs(x + 220) < 38 && Math.abs(z + 134) < 26) return 0;  // Athletic Field
    if (Math.abs(x + 225) < 46 && Math.abs(z - 2) < 52) return 0;    // Google 2000 / 1950
    if (Math.abs(x + 108) < 44 && Math.abs(z - 126) < 32) return 0;  // 1098 Alta Complex
    if (Math.abs(x - 28) < 60 && Math.abs(z - 134) < 36) return 0;   // Charleston Campus
    if (Math.abs(x - 234) < 40 && Math.abs(z + 22) < 28) return 0;   // Google 2015 / Stierlin Ct
    if (Math.abs(x - 236) < 40 && Math.abs(z + 140) < 28) return 0;  // Google CL2 Crittenden
    if (Math.abs(x - 234) < 40 && Math.abs(z - 122) < 28) return 0;  // Google 1395 Charleston
    if (Math.abs(x - 118) < 30 && Math.abs(z + 112) < 22) return 0;  // Parking Lot C

    // Gentle Charleston Park grassy berms (east of Quad, west of Joaquin Rd)
    const parkMaskX = smoothstep(5, 16, x) * (1 - smoothstep(46, 56, x));
    const parkMaskZ = smoothstep(-56, -42, z) * (1 - smoothstep(42, 56, z));
    const parkMask = parkMaskX * parkMaskZ;
    let h = 0;
    if (parkMask > 0.001) {
      const mound1 = Math.exp(-(((x - 24) ** 2) / 190 + ((z + 24) ** 2) / 210)) * 1.25;
      const mound2 = Math.exp(-(((x - 36) ** 2) / 220 + ((z - 16) ** 2) / 240)) * 1.15;
      const undul = (Math.sin(x * 0.11) * Math.cos(z * 0.09) * 0.5 + 0.5) * 0.35;
      h += parkMask * (mound1 + mound2 + undul);
    }

    // North Shoreline & Bay Point Regional Shoreline Overlook rolling hills (crest at (-62, -144) up to ~6.8m)
    if (z < -72 && x > -148 && x < 28) {
      const northMask = smoothstep(-72, -88, z);
      const westFade = smoothstep(-148, -134, x);
      const eastFade = 1 - smoothstep(4, 24, x);
      const ampClear = smoothstep(32, 48, Math.hypot(x - 58, z + 148));
      const mask = northMask * westFade * eastFade * ampClear;
      if (mask > 0.001) {
        const rolling = (Math.sin(x * 0.045 + 0.6) * Math.cos(z * 0.06) * 0.5 + 0.5) * 1.45;
        const overlookCrest = Math.exp(-(((x + 62) ** 2) / 2400 + ((z + 144) ** 2) / 950)) * 5.2;
        const knollEast = Math.exp(-(((x + 14) ** 2) / 900 + ((z + 132) ** 2) / 700)) * 2.1;
        h += mask * (rolling + overlookCrest + knollEast);
      }
    }

    return h;
  }

  public getTerrainHeight(x: number, z: number): number {
    if (!this.bakedHeights) {
      return this.getAnalyticalTerrainHeight(x, z);
    }
    const fx = Math.max(0, Math.min(this.gridCols - 1.001, (x - MIN_X) / this.gridStep));
    const fz = Math.max(0, Math.min(this.gridRows - 1.001, (z - MIN_Z) / this.gridStep));
    const c0 = Math.floor(fx);
    const r0 = Math.floor(fz);
    const c1 = Math.min(this.gridCols - 1, c0 + 1);
    const r1 = Math.min(this.gridRows - 1, r0 + 1);
    const tx = fx - c0;
    const tz = fz - r0;

    const cols = this.gridCols;
    const h00 = this.bakedHeights[r0 * cols + c0];
    const h10 = this.bakedHeights[r0 * cols + c1];
    const h01 = this.bakedHeights[r1 * cols + c0];
    const h11 = this.bakedHeights[r1 * cols + c1];

    const hx0 = h00 + (h10 - h00) * tx;
    const hx1 = h01 + (h11 - h01) * tx;
    return hx0 + (hx1 - hx0) * tz;
  }

  /**
   * Computes highest walkable surface directly below (or within stepHeight above) currentY.
   * Handles terrain, building rooftops, elevated Skybridge deck (while permitting walking underneath!),
   * exterior staircases/ramps, and low curbs/plazas using the 2D spatial hash grid.
   */
  public getSupportHeight(
    x: number,
    z: number,
    currentY = 100,
    radius = 0.35,
    stepHeight = 0.65
  ): number {
    let supportY = this.getTerrainHeight(x, z);
    const maxReachY = currentY + stepHeight;
    const rampReachY = currentY + Math.max(stepHeight, 1.35);

    const c0 = this.cellCol(x - radius);
    const c1 = this.cellCol(x + radius);
    const r0 = this.cellRow(z - radius);
    const r1 = this.cellRow(z + radius);
    const stamp = ++this.queryStamp;

    for (let r = r0; r <= r1; r++) {
      const rowOff = r * SPATIAL_COLS;
      for (let c = c0; c <= c1; c++) {
        const cellIdx = rowOff + c;

        // 1. Polygon building rooftops (B40, B41, B42, B43, expanded hollow offices)
        const pCell = this.polyCells[cellIdx];
        for (let i = 0; i < pCell.length; i++) {
          const p = pCell[i];
          if (p._stamp === stamp) continue;
          p._stamp = stamp;
          if (p.maxY > maxReachY || p.maxY <= supportY) continue;
          if (x < p.minX - radius || x > p.maxX + radius || z < p.minZ - radius || z > p.maxZ + radius) {
            continue;
          }
          if (this.pointInOrNearPolygon(x, z, p.points, radius * 0.7)) {
            supportY = p.maxY;
          }
        }

        // 2. Box / OBB / Ramp / Platform colliders
        const bCell = this.boxCells[cellIdx];
        for (let i = 0; i < bCell.length; i++) {
          const b = bCell[i];
          if (b._stamp === stamp) continue;
          b._stamp = stamp;

          if (x < b._wMinX - radius || x > b._wMaxX + radius || z < b._wMinZ - radius || z > b._wMaxZ + radius) {
            continue;
          }

          let lx = x - b._cx;
          let lz = z - b._cz;
          if (b.rotationY) {
            const rx = lx * b._cos - lz * b._sin;
            const rz = lx * b._sin + lz * b._cos;
            lx = rx;
            lz = rz;
          }

          if (Math.abs(lx) > b._hx + radius || Math.abs(lz) > b._hz + radius) continue;

          if (b.isRamp && b.rampAxis) {
            const halfAxis = b.rampAxis === 'x' ? b._hx : b._hz;
            const coord = b.rampAxis === 'x' ? lx : lz;
            const dir = b.rampDir ?? 1;
            let t = halfAxis > 1e-4 ? (coord * dir + halfAxis) / (2 * halfAxis) : 0;
            t = Math.max(0, Math.min(1, t));
            const rampY = b.minY + t * (b.maxY - b.minY);
            // Generous climb window on stairs/ramps so walking onto steps never snags
            if (rampY <= rampReachY && rampY > supportY) {
              supportY = rampY;
            }
          } else {
            if (b.maxY <= maxReachY && b.maxY > supportY) {
              supportY = b.maxY;
            }
          }
        }

        // 3. Walkable pedestal/cylinder tops (e.g. Stan pedestal, Orb base)
        const cCell = this.cylCells[cellIdx];
        for (let i = 0; i < cCell.length; i++) {
          const cyl = cCell[i];
          if (cyl._stamp === stamp) continue;
          cyl._stamp = stamp;
          if (cyl.maxY > maxReachY || cyl.maxY <= supportY) continue;
          const dx = x - cyl.x;
          const dz = z - cyl.z;
          const rSum = cyl.radius + radius * 0.6;
          if (dx * dx + dz * dz <= rSum * rSum) {
            supportY = cyl.maxY;
          }
        }
      }
    }

    return supportY;
  }

  /**
   * Resolves horizontal movement, solid wall pushout, ramp climbing, elevated platform
   * walkthrough/landing, gravity, and arena boundary clamping for any combatant.
   */
  public resolveCombatantMovement(
    pos: THREE.Vector3,
    vel: THREE.Vector3,
    radius: number,
    height: number,
    dt: number,
    options?: { stepHeight?: number; applyGravity?: boolean }
  ): MovementResult {
    const stepHeight = options?.stepHeight ?? 0.65;
    const applyGravity = options?.applyGravity !== false;

    const clampedDt = Math.min(dt, 0.05);
    const horizDist = Math.hypot(vel.x * clampedDt, vel.z * clampedDt);
    const subSteps = Math.max(1, Math.min(4, Math.ceil(horizDist / Math.max(0.35, radius * 0.8))));
    const subDt = clampedDt / subSteps;
    const queryPad = radius + 0.6;

    for (let s = 0; s < subSteps; s++) {
      pos.x += vel.x * subDt;
      pos.z += vel.z * subDt;

      // Push out from solid colliders overlapping combatant vertical body [pos.y + stepHeight, pos.y + height]
      const bodyMinY = pos.y + stepHeight;
      const bodyMaxY = pos.y + height;

      const c0 = this.cellCol(pos.x - queryPad);
      const c1 = this.cellCol(pos.x + queryPad);
      const r0 = this.cellRow(pos.z - queryPad);
      const r1 = this.cellRow(pos.z + queryPad);
      const stamp = ++this.queryStamp;

      // 1. Polygon buildings & elevated roof slabs (e.g. B40-B43 hollow roofs at minY=5.75..6.40)
      for (let r = r0; r <= r1; r++) {
        const rowOff = r * SPATIAL_COLS;
        for (let c = c0; c <= c1; c++) {
          const pCell = this.polyCells[rowOff + c];
          for (let i = 0; i < pCell.length; i++) {
            const p = pCell[i];
            if (p._stamp === stamp) continue;
            p._stamp = stamp;
            if (p.maxY <= bodyMinY || p.minY >= bodyMaxY) continue;
            if (pos.x < p.minX - radius || pos.x > p.maxX + radius || pos.z < p.minZ - radius || pos.z > p.maxZ + radius) {
              continue;
            }
            // If already inside an elevated roof slab's footprint and below its underside (e.g. uncrouching
            // near an interior ceiling), clamp headroom vertically instead of ejecting sideways through walls.
            if (p.minY > 0.5 && pos.y < p.minY - 0.25 && this.pointInPolygon2D(pos.x, pos.z, p.points)) {
              pos.y = Math.min(pos.y, p.minY - height - 0.01);
              if (vel.y > 0) vel.y = 0;
              continue;
            }
            this.resolveCircleVsPolygon(pos, radius, p.points);
          }
        }
      }

      // 2. Boxes / OBBs / Platforms / Hard-Light Covers (skip walkable ramps!)
      for (let r = r0; r <= r1; r++) {
        const rowOff = r * SPATIAL_COLS;
        for (let c = c0; c <= c1; c++) {
          const bCell = this.boxCells[rowOff + c];
          for (let i = 0; i < bCell.length; i++) {
            const b = bCell[i];
            if (b._stamp === stamp) continue;
            b._stamp = stamp;
            if (b.isRamp) continue;
            if (b.maxY <= bodyMinY || b.minY >= bodyMaxY) continue;
            if (pos.x < b._wMinX - radius || pos.x > b._wMaxX + radius || pos.z < b._wMinZ - radius || pos.z > b._wMaxZ + radius) {
              continue;
            }
            if (b.isPlatform && b.minY > 0.5 && pos.y < b.minY - 0.25 && this.pointInBoxXZ(pos.x, pos.z, b, 0)) {
              pos.y = Math.min(pos.y, b.minY - height - 0.01);
              if (vel.y > 0) vel.y = 0;
              continue;
            }
            this.resolveCircleVsBox(pos, radius, b);
          }
        }
      }

      // 3. Cylinders (tree trunks, pedestals, columns)
      for (let r = r0; r <= r1; r++) {
        const rowOff = r * SPATIAL_COLS;
        for (let c = c0; c <= c1; c++) {
          const cCell = this.cylCells[rowOff + c];
          for (let i = 0; i < cCell.length; i++) {
            const cyl = cCell[i];
            if (cyl._stamp === stamp) continue;
            cyl._stamp = stamp;
            if (cyl.maxY <= bodyMinY || cyl.minY >= bodyMaxY) continue;
            const dx = pos.x - cyl.x;
            const dz = pos.z - cyl.z;
            const minDist = cyl.radius + radius;
            const dSq = dx * dx + dz * dz;
            if (dSq < minDist * minDist) {
              const dist = Math.sqrt(dSq);
              if (dist > 1e-5) {
                const push = minDist - dist;
                pos.x += (dx / dist) * push;
                pos.z += (dz / dist) * push;
              } else {
                pos.x += minDist;
              }
            }
          }
        }
      }
    }

    // Clamp to Googleplex arena bounds with slight margin
    const boundMargin = 1.6;
    if (pos.x < MIN_X + boundMargin) {
      pos.x = MIN_X + boundMargin;
      if (vel.x < 0) vel.x = 0;
    } else if (pos.x > MAX_X - boundMargin) {
      pos.x = MAX_X - boundMargin;
      if (vel.x > 0) vel.x = 0;
    }
    if (pos.z < MIN_Z + boundMargin) {
      pos.z = MIN_Z + boundMargin;
      if (vel.z < 0) vel.z = 0;
    } else if (pos.z > MAX_Z - boundMargin) {
      pos.z = MAX_Z - boundMargin;
      if (vel.z > 0) vel.z = 0;
    }

    // Vertical gravity & ceiling/ground resolution
    const prevY = pos.y;
    if (applyGravity) {
      vel.y -= GAME_CONSTANTS.GRAVITY * clampedDt;
    }
    pos.y += vel.y * clampedDt;

    // Ceiling headroom clamp when jumping underneath elevated platforms (Skybridge, doorway lintels)
    // OR hollow building roof slabs (B40, B41, B42, B43 ceilings at Y=5.75m)
    let hitCeiling = false;
    if (vel.y > 0) {
      const headY = pos.y + height;
      const prevHeadY = prevY + height;
      let lowestCeilingY = Infinity;

      const c0 = this.cellCol(pos.x - radius);
      const c1 = this.cellCol(pos.x + radius);
      const r0 = this.cellRow(pos.z - radius);
      const r1 = this.cellRow(pos.z + radius);
      const stamp = ++this.queryStamp;

      for (let r = r0; r <= r1; r++) {
        const rowOff = r * SPATIAL_COLS;
        for (let c = c0; c <= c1; c++) {
          const cellIdx = rowOff + c;

          const bCell = this.boxCells[cellIdx];
          for (let i = 0; i < bCell.length; i++) {
            const b = bCell[i];
            if (b._stamp === stamp) continue;
            b._stamp = stamp;
            if (!b.isPlatform || b.isRamp || b.minY <= 0.5) continue;
            if (prevHeadY <= b.minY + 0.25 && headY > b.minY && b.minY < lowestCeilingY) {
              if (
                pos.x >= b._wMinX - radius &&
                pos.x <= b._wMaxX + radius &&
                pos.z >= b._wMinZ - radius &&
                pos.z <= b._wMaxZ + radius &&
                this.pointInBoxXZ(pos.x, pos.z, b, radius * 0.65)
              ) {
                lowestCeilingY = b.minY;
              }
            }
          }

          const pCell = this.polyCells[cellIdx];
          for (let i = 0; i < pCell.length; i++) {
            const p = pCell[i];
            if (p._stamp === stamp) continue;
            p._stamp = stamp;
            if (p.minY <= 0.5) continue;
            if (prevHeadY <= p.minY + 0.25 && headY > p.minY && p.minY < lowestCeilingY) {
              if (
                pos.x >= p.minX - radius &&
                pos.x <= p.maxX + radius &&
                pos.z >= p.minZ - radius &&
                pos.z <= p.maxZ + radius &&
                this.pointInOrNearPolygon(pos.x, pos.z, p.points, radius * 0.55)
              ) {
                lowestCeilingY = p.minY;
              }
            }
          }
        }
      }

      if (lowestCeilingY < Infinity) {
        pos.y = lowestCeilingY - height - 0.01;
        vel.y = 0;
        hitCeiling = true;
      }
    }

    const groundY = this.getSupportHeight(pos.x, pos.z, Math.max(prevY, pos.y), radius, stepHeight);
    let grounded = false;
    if (pos.y <= groundY + 0.02 && vel.y <= 0.1) {
      pos.y = groundY;
      vel.y = 0;
      grounded = true;
    } else if (prevY <= groundY + 0.12 && pos.y <= groundY + 0.25 && vel.y <= 0) {
      // Smoothly glue to downward stairs/slopes while walking down
      pos.y = groundY;
      vel.y = 0;
      grounded = true;
    }

    const surface = this.classifySurface(pos.x, pos.z, pos.y);
    return { grounded, groundY, hitCeiling, surface };
  }

  private classifySurface(x: number, z: number, y: number): 'grass' | 'stone' | 'sand' | 'metal' {
    if (y > 3.5) return 'metal'; // Rooftops & Skybridge deck
    if (Math.abs(x + 91) < 9.5 && Math.abs(z - 4) < 5.5) return 'sand'; // Sand Volleyball Court
    if (Math.abs(x + 220) < 34 && Math.abs(z + 134) < 22) return 'grass'; // Google Athletic Field turf
    if (x > 6 && x < 58 && z > -55 && z < 55) return 'grass'; // Charleston Park
    if (z < -72 && x > -148 && x < 24) return 'grass'; // Bay Point Shoreline Overlook
    if (Math.abs(x - 58) < 30 && Math.abs(z + 148) < 24) return 'stone'; // Shoreline Amphitheatre concourse/stage
    if (Math.abs(x + 225) < 42 && Math.abs(z - 2) < 48) return 'stone'; // Google 2000/1950
    if (Math.abs(x + 108) < 40 && Math.abs(z - 126) < 28) return 'stone'; // 1098 Alta
    if (Math.abs(x - 28) < 56 && Math.abs(z - 134) < 32) return 'stone'; // Charleston Campus
    if (x > 195 && (Math.abs(z + 22) < 25 || Math.abs(z + 140) < 25 || Math.abs(z - 122) < 25)) return 'stone'; // Shoreline East offices
    if (z < -72 || z > 72) return 'grass';
    return 'stone';
  }

  /**
   * Raycast against terrain, buildings, rotated OBBs, destructible Hard-Light Covers, and cylinders
   * using zero-allocation 2D DDA grid traversal with early termination and integer query stamps.
   */
  public raycastWorld(
    origin: THREE.Vector3,
    dir: THREE.Vector3,
    maxDist: number,
    options?: { ignoreDestructible?: boolean; ignoreTag?: string }
  ): WorldRaycastHit | null {
    const dLen = dir.length();
    if (dLen < 1e-6) return null;
    const ox = origin.x;
    const oy = origin.y;
    const oz = origin.z;
    const dx = dir.x / dLen;
    const dy = dir.y / dLen;
    const dz = dir.z / dLen;

    const ignoreDestructible = Boolean(options?.ignoreDestructible);
    const ignoreTag = options?.ignoreTag;

    let bestDist = maxDist;
    let bestNx = 0;
    let bestNy = 1;
    let bestNz = 0;
    let bestId: string | undefined;
    let bestDestructible = false;
    let bestTag: string | undefined;
    let hitAny = false;

    // 1–3. 2D DDA traversal across overlapped spatial grid cells (polygons, boxes, cylinders)
    let tStart = 0;
    let tEnd = maxDist;
    let intersectsGrid = true;

    if (Math.abs(dx) < 1e-9) {
      if (ox < SPATIAL_MIN_X || ox > SPATIAL_MAX_X) intersectsGrid = false;
    } else {
      const invX = 1 / dx;
      let tx1 = (SPATIAL_MIN_X - ox) * invX;
      let tx2 = (SPATIAL_MAX_X - ox) * invX;
      if (tx1 > tx2) {
        const tmp = tx1;
        tx1 = tx2;
        tx2 = tmp;
      }
      if (tx1 > tStart) tStart = tx1;
      if (tx2 < tEnd) tEnd = tx2;
      if (tStart > tEnd) intersectsGrid = false;
    }

    if (intersectsGrid) {
      if (Math.abs(dz) < 1e-9) {
        if (oz < SPATIAL_MIN_Z || oz > SPATIAL_MAX_Z) intersectsGrid = false;
      } else {
        const invZ = 1 / dz;
        let tz1 = (SPATIAL_MIN_Z - oz) * invZ;
        let tz2 = (SPATIAL_MAX_Z - oz) * invZ;
        if (tz1 > tz2) {
          const tmp = tz1;
          tz1 = tz2;
          tz2 = tmp;
        }
        if (tz1 > tStart) tStart = tz1;
        if (tz2 < tEnd) tEnd = tz2;
        if (tStart > tEnd) intersectsGrid = false;
      }
    }

    if (intersectsGrid) {
      const sx = ox + dx * tStart;
      const sz = oz + dz * tStart;
      let col = this.cellCol(sx);
      let row = this.cellRow(sz);

      let stepX = 0;
      let tMaxX = Infinity;
      let tDeltaX = Infinity;
      if (dx > 1e-9) {
        stepX = 1;
        tMaxX = (SPATIAL_MIN_X + (col + 1) * CELL_SIZE - ox) / dx;
        tDeltaX = CELL_SIZE / dx;
      } else if (dx < -1e-9) {
        stepX = -1;
        tMaxX = (SPATIAL_MIN_X + col * CELL_SIZE - ox) / dx;
        tDeltaX = -CELL_SIZE / dx;
      }

      let stepZ = 0;
      let tMaxZ = Infinity;
      let tDeltaZ = Infinity;
      if (dz > 1e-9) {
        stepZ = 1;
        tMaxZ = (SPATIAL_MIN_Z + (row + 1) * CELL_SIZE - oz) / dz;
        tDeltaZ = CELL_SIZE / dz;
      } else if (dz < -1e-9) {
        stepZ = -1;
        tMaxZ = (SPATIAL_MIN_Z + row * CELL_SIZE - oz) / dz;
        tDeltaZ = -CELL_SIZE / dz;
      }

      const stamp = ++this.queryStamp;
      let cellT = tStart;

      while (
        col >= 0 &&
        col < SPATIAL_COLS &&
        row >= 0 &&
        row < SPATIAL_ROWS &&
        cellT <= bestDist &&
        cellT <= tEnd
      ) {
        const cellIdx = row * SPATIAL_COLS + col;

        // Polygons in cell
        const pCell = this.polyCells[cellIdx];
        for (let i = 0; i < pCell.length; i++) {
          const p = pCell[i];
          if (p._stamp === stamp) continue;
          p._stamp = stamp;
          if (p.blocksBullets === false) continue;
          if (ignoreTag && p.tag === ignoreTag) continue;
          const res = this.rayIntersectPolygonPrism(ox, oy, oz, dx, dy, dz, bestDist, p);
          if (res && res.dist < bestDist) {
            bestDist = res.dist;
            bestNx = res.nx;
            bestNy = res.ny;
            bestNz = res.nz;
            bestId = p.id;
            bestDestructible = false;
            bestTag = p.tag;
            hitAny = true;
          }
        }

        // Boxes / OBBs / Destructible covers in cell
        const bCell = this.boxCells[cellIdx];
        for (let i = 0; i < bCell.length; i++) {
          const b = bCell[i];
          if (b._stamp === stamp) continue;
          b._stamp = stamp;
          if (b.blocksBullets === false) continue;
          if (ignoreDestructible && b.destructible) continue;
          if (ignoreTag && b.tag === ignoreTag) continue;
          const res = this.rayIntersectBox(ox, oy, oz, dx, dy, dz, bestDist, b);
          if (res && res.dist < bestDist) {
            bestDist = res.dist;
            bestNx = res.nx;
            bestNy = res.ny;
            bestNz = res.nz;
            bestId = b.id;
            bestDestructible = Boolean(b.destructible);
            bestTag = b.tag;
            hitAny = true;
          }
        }

        // Cylinders in cell
        const cCell = this.cylCells[cellIdx];
        for (let i = 0; i < cCell.length; i++) {
          const cyl = cCell[i];
          if (cyl._stamp === stamp) continue;
          cyl._stamp = stamp;
          if (cyl.blocksBullets === false) continue;
          if (ignoreTag && cyl.tag === ignoreTag) continue;
          const res = this.rayIntersectCylinder(ox, oy, oz, dx, dy, dz, bestDist, cyl);
          if (res && res.dist < bestDist) {
            bestDist = res.dist;
            bestNx = res.nx;
            bestNy = res.ny;
            bestNz = res.nz;
            bestId = cyl.id;
            bestDestructible = false;
            bestTag = cyl.tag;
            hitAny = true;
          }
        }

        if (tMaxX < tMaxZ) {
          cellT = tMaxX;
          tMaxX += tDeltaX;
          col += stepX;
        } else {
          cellT = tMaxZ;
          tMaxZ += tDeltaZ;
          row += stepZ;
        }
      }
    }

    // 4. Terrain heightfield march (fast coarse step + binary refinement)
    if (dy < 0.25) {
      const step = 2.0;
      let prevT = 0;
      let prevDiff = oy - this.getTerrainHeight(ox, oz);
      for (let t = step; t <= bestDist + step; t += step) {
        const ct = Math.min(t, bestDist);
        const px = ox + dx * ct;
        const py = oy + dy * ct;
        const pz = oz + dz * ct;
        const diff = py - this.getTerrainHeight(px, pz);
        if (diff <= 0 && prevDiff > 0) {
          // Refine intersection with 5 binary iterations
          let lo = prevT;
          let hi = ct;
          for (let k = 0; k < 5; k++) {
            const mid = 0.5 * (lo + hi);
            const mx = ox + dx * mid;
            const my = oy + dy * mid;
            const mz = oz + dz * mid;
            if (my - this.getTerrainHeight(mx, mz) <= 0) {
              hi = mid;
            } else {
              lo = mid;
            }
          }
          if (hi < bestDist) {
            bestDist = hi;
            bestNx = 0;
            bestNy = 1;
            bestNz = 0;
            bestId = 'terrain';
            bestDestructible = false;
            bestTag = 'terrain';
            hitAny = true;
          }
          break;
        }
        prevT = ct;
        prevDiff = diff;
        if (ct >= bestDist) break;
      }
    }

    if (!hitAny) return null;

    return {
      distance: bestDist,
      point: new THREE.Vector3(ox + dx * bestDist, oy + dy * bestDist, oz + dz * bestDist),
      normal: new THREE.Vector3(bestNx, bestNy, bestNz),
      colliderId: bestId,
      destructible: bestDestructible,
      tag: bestTag,
    };
  }

  /**
   * Zero-allocation early-exit 2D DDA line-of-sight query (returns false on first solid or terrain hit).
   */
  public hasLineOfSight(a: THREE.Vector3, b: THREE.Vector3): boolean {
    const vx = b.x - a.x;
    const vy = b.y - a.y;
    const vz = b.z - a.z;
    const dist = Math.hypot(vx, vy, vz);
    if (dist < 0.05) return true;
    const maxDist = dist - 0.15;
    if (maxDist <= 0.001) return true;

    const ox = a.x;
    const oy = a.y;
    const oz = a.z;
    const invDist = 1 / dist;
    const dx = vx * invDist;
    const dy = vy * invDist;
    const dz = vz * invDist;

    let tStart = 0;
    let tEnd = maxDist;
    let intersectsGrid = true;

    if (Math.abs(dx) < 1e-9) {
      if (ox < SPATIAL_MIN_X || ox > SPATIAL_MAX_X) intersectsGrid = false;
    } else {
      const invX = 1 / dx;
      let tx1 = (SPATIAL_MIN_X - ox) * invX;
      let tx2 = (SPATIAL_MAX_X - ox) * invX;
      if (tx1 > tx2) {
        const tmp = tx1;
        tx1 = tx2;
        tx2 = tmp;
      }
      if (tx1 > tStart) tStart = tx1;
      if (tx2 < tEnd) tEnd = tx2;
      if (tStart > tEnd) intersectsGrid = false;
    }

    if (intersectsGrid) {
      if (Math.abs(dz) < 1e-9) {
        if (oz < SPATIAL_MIN_Z || oz > SPATIAL_MAX_Z) intersectsGrid = false;
      } else {
        const invZ = 1 / dz;
        let tz1 = (SPATIAL_MIN_Z - oz) * invZ;
        let tz2 = (SPATIAL_MAX_Z - oz) * invZ;
        if (tz1 > tz2) {
          const tmp = tz1;
          tz1 = tz2;
          tz2 = tmp;
        }
        if (tz1 > tStart) tStart = tz1;
        if (tz2 < tEnd) tEnd = tz2;
        if (tStart > tEnd) intersectsGrid = false;
      }
    }

    if (intersectsGrid) {
      const sx = ox + dx * tStart;
      const sz = oz + dz * tStart;
      let col = this.cellCol(sx);
      let row = this.cellRow(sz);

      let stepX = 0;
      let tMaxX = Infinity;
      let tDeltaX = Infinity;
      if (dx > 1e-9) {
        stepX = 1;
        tMaxX = (SPATIAL_MIN_X + (col + 1) * CELL_SIZE - ox) / dx;
        tDeltaX = CELL_SIZE / dx;
      } else if (dx < -1e-9) {
        stepX = -1;
        tMaxX = (SPATIAL_MIN_X + col * CELL_SIZE - ox) / dx;
        tDeltaX = -CELL_SIZE / dx;
      }

      let stepZ = 0;
      let tMaxZ = Infinity;
      let tDeltaZ = Infinity;
      if (dz > 1e-9) {
        stepZ = 1;
        tMaxZ = (SPATIAL_MIN_Z + (row + 1) * CELL_SIZE - oz) / dz;
        tDeltaZ = CELL_SIZE / dz;
      } else if (dz < -1e-9) {
        stepZ = -1;
        tMaxZ = (SPATIAL_MIN_Z + row * CELL_SIZE - oz) / dz;
        tDeltaZ = -CELL_SIZE / dz;
      }

      const stamp = ++this.queryStamp;
      let cellT = tStart;

      while (
        col >= 0 &&
        col < SPATIAL_COLS &&
        row >= 0 &&
        row < SPATIAL_ROWS &&
        cellT <= tEnd
      ) {
        const cellIdx = row * SPATIAL_COLS + col;

        const pCell = this.polyCells[cellIdx];
        for (let i = 0; i < pCell.length; i++) {
          const p = pCell[i];
          if (p._stamp === stamp) continue;
          p._stamp = stamp;
          if (p.blocksBullets === false) continue;
          const res = this.rayIntersectPolygonPrism(ox, oy, oz, dx, dy, dz, maxDist, p);
          if (res && res.dist < maxDist) return false;
        }

        const bCell = this.boxCells[cellIdx];
        for (let i = 0; i < bCell.length; i++) {
          const box = bCell[i];
          if (box._stamp === stamp) continue;
          box._stamp = stamp;
          if (box.blocksBullets === false) continue;
          const res = this.rayIntersectBox(ox, oy, oz, dx, dy, dz, maxDist, box);
          if (res && res.dist < maxDist) return false;
        }

        const cCell = this.cylCells[cellIdx];
        for (let i = 0; i < cCell.length; i++) {
          const cyl = cCell[i];
          if (cyl._stamp === stamp) continue;
          cyl._stamp = stamp;
          if (cyl.blocksBullets === false) continue;
          const res = this.rayIntersectCylinder(ox, oy, oz, dx, dy, dz, maxDist, cyl);
          if (res && res.dist < maxDist) return false;
        }

        if (tMaxX < tMaxZ) {
          cellT = tMaxX;
          tMaxX += tDeltaX;
          col += stepX;
        } else {
          cellT = tMaxZ;
          tMaxZ += tDeltaZ;
          row += stepZ;
        }
      }
    }

    // Terrain occlusion check
    if (dy < 0.25) {
      const step = 2.0;
      let prevT = 0;
      let prevDiff = oy - this.getTerrainHeight(ox, oz);
      for (let t = step; t <= maxDist + step; t += step) {
        const ct = Math.min(t, maxDist);
        const px = ox + dx * ct;
        const py = oy + dy * ct;
        const pz = oz + dz * ct;
        const diff = py - this.getTerrainHeight(px, pz);
        if (diff <= 0 && prevDiff > 0) {
          let lo = prevT;
          let hi = ct;
          for (let k = 0; k < 5; k++) {
            const mid = 0.5 * (lo + hi);
            const mx = ox + dx * mid;
            const my = oy + dy * mid;
            const mz = oz + dz * mid;
            if (my - this.getTerrainHeight(mx, mz) <= 0) {
              hi = mid;
            } else {
              lo = mid;
            }
          }
          if (hi < maxDist) return false;
          break;
        }
        prevT = ct;
        prevDiff = diff;
        if (ct >= maxDist) break;
      }
    }

    return true;
  }

  /**
   * Dual-zone competitive combatant hitbox segment test (§4 & §15):
   * - Head Sphere: center (x, y + (crouching ? 1.00 : 1.60), z), radius 0.25m
   * - Torso Capsule: (x, y + 0.15, z) -> (x, y + (crouching ? 0.85 : 1.42), z), radius 0.42m
   */
  public testCombatantHitbox(
    p0: THREE.Vector3,
    p1: THREE.Vector3,
    targetPos: THREE.Vector3,
    crouching: boolean
  ): HitboxCheckResult {
    const headCenterY = targetPos.y + (crouching ? GAME_CONSTANTS.HEAD_OFFSET_CROUCHING : GAME_CONSTANTS.HEAD_OFFSET_STANDING);
    const headRadius = GAME_CONSTANTS.HEAD_RADIUS;

    const headT = this.segmentSphereIntersect(
      p0.x,
      p0.y,
      p0.z,
      p1.x,
      p1.y,
      p1.z,
      targetPos.x,
      headCenterY,
      targetPos.z,
      headRadius
    );

    const torsoMinY = targetPos.y + GAME_CONSTANTS.TORSO_MIN_Y;
    const torsoMaxY = targetPos.y + (crouching ? GAME_CONSTANTS.TORSO_MAX_CROUCHING : GAME_CONSTANTS.TORSO_MAX_STANDING);
    const torsoRadius = GAME_CONSTANTS.TORSO_RADIUS;

    const torsoT = this.segmentVerticalCapsuleIntersect(
      p0.x,
      p0.y,
      p0.z,
      p1.x,
      p1.y,
      p1.z,
      targetPos.x,
      targetPos.z,
      torsoMinY,
      torsoMaxY,
      torsoRadius
    );

    if (headT === null && torsoT === null) {
      return { hit: false, headshot: false, t: 1 };
    }

    // Favor clean headshots when the ray grazes head nearly simultaneously with upper shoulder
    let headshot = false;
    let t = 1;
    if (headT !== null && (torsoT === null || headT <= torsoT + 0.035)) {
      headshot = true;
      t = headT;
    } else if (torsoT !== null) {
      headshot = false;
      t = torsoT;
    }

    return {
      hit: true,
      headshot,
      t,
      point: {
        x: p0.x + (p1.x - p0.x) * t,
        y: p0.y + (p1.y - p0.y) * t,
        z: p0.z + (p1.z - p0.z) * t,
      },
    };
  }

  // -------------------------------------------------------------------------
  // Internal Geometry Primitives
  // -------------------------------------------------------------------------

  private pointInBoxXZ(x: number, z: number, b: IndexedBoxCollider, pad = 0): boolean {
    const hx = b._hx + pad;
    const hz = b._hz + pad;
    let lx = x - b._cx;
    let lz = z - b._cz;
    if (b.rotationY) {
      const rx = lx * b._cos - lz * b._sin;
      const rz = lx * b._sin + lz * b._cos;
      lx = rx;
      lz = rz;
    }
    return Math.abs(lx) <= hx && Math.abs(lz) <= hz;
  }

  private resolveCircleVsBox(pos: THREE.Vector3, radius: number, b: IndexedBoxCollider): void {
    if (!b.rotationY) {
      const closestX = Math.max(b.minX, Math.min(pos.x, b.maxX));
      const closestZ = Math.max(b.minZ, Math.min(pos.z, b.maxZ));
      const dx = pos.x - closestX;
      const dz = pos.z - closestZ;
      const dSq = dx * dx + dz * dz;
      if (dSq >= radius * radius) return;

      if (dSq > 1e-6) {
        const dist = Math.sqrt(dSq);
        const push = radius - dist;
        pos.x += (dx / dist) * push;
        pos.z += (dz / dist) * push;
      } else {
        // Inside AABB: push out along shallowest axis
        const penLeft = pos.x - b.minX;
        const penRight = b.maxX - pos.x;
        const penTop = pos.z - b.minZ;
        const penBot = b.maxZ - pos.z;
        const minPen = Math.min(penLeft, penRight, penTop, penBot);
        if (minPen === penLeft) pos.x = b.minX - radius;
        else if (minPen === penRight) pos.x = b.maxX + radius;
        else if (minPen === penTop) pos.z = b.minZ - radius;
        else pos.z = b.maxZ + radius;
      }
      return;
    }

    // Rotated OBB: transform into local box space using cached cos/sin, push out, rotate delta back to world
    const hx = b._hx;
    const hz = b._hz;
    const cos = b._cos;
    const sin = b._sin;
    const dxW = pos.x - b._cx;
    const dzW = pos.z - b._cz;
    const lx = dxW * cos - dzW * sin;
    const lz = dxW * sin + dzW * cos;

    const clx = Math.max(-hx, Math.min(lx, hx));
    const clz = Math.max(-hz, Math.min(lz, hz));
    const dlx = lx - clx;
    const dlz = lz - clz;
    const dSq = dlx * dlx + dlz * dlz;
    if (dSq >= radius * radius) return;

    let pushLX = 0;
    let pushLZ = 0;
    if (dSq > 1e-6) {
      const dist = Math.sqrt(dSq);
      const push = radius - dist;
      pushLX = (dlx / dist) * push;
      pushLZ = (dlz / dist) * push;
    } else {
      const ox = hx - Math.abs(lx) + radius;
      const oz = hz - Math.abs(lz) + radius;
      if (ox < oz) {
        pushLX = lx >= 0 ? ox : -ox;
      } else {
        pushLZ = lz >= 0 ? oz : -oz;
      }
    }

    pos.x += pushLX * cos + pushLZ * sin;
    pos.z += -pushLX * sin + pushLZ * cos;
  }

  private pointInPolygon2D(x: number, z: number, pts: [number, number][]): boolean {
    let inside = false;
    const n = pts.length;
    for (let i = 0, j = n - 1; i < n; j = i++) {
      const [xi, zi] = pts[i];
      const [xj, zj] = pts[j];
      if (zi > z !== zj > z && x < ((xj - xi) * (z - zi)) / (zj - zi + 1e-12) + xi) {
        inside = !inside;
      }
    }
    return inside;
  }

  private pointInOrNearPolygon(x: number, z: number, pts: [number, number][], pad: number): boolean {
    if (this.pointInPolygon2D(x, z, pts)) return true;
    const padSq = pad * pad;
    const n = pts.length;
    for (let i = 0; i < n; i++) {
      const [ax, az] = pts[i];
      const [bx, bz] = pts[(i + 1) % n];
      const ex = bx - ax;
      const ez = bz - az;
      const lenSq = ex * ex + ez * ez;
      let t = lenSq > 1e-6 ? ((x - ax) * ex + (z - az) * ez) / lenSq : 0;
      t = Math.max(0, Math.min(1, t));
      const dx = x - (ax + t * ex);
      const dz = z - (az + t * ez);
      if (dx * dx + dz * dz <= padSq) return true;
    }
    return false;
  }

  private resolveCircleVsPolygon(pos: THREE.Vector3, radius: number, pts: [number, number][]): void {
    const inside = this.pointInPolygon2D(pos.x, pos.z, pts);
    let bestDistSq = Infinity;
    let bestClosestX = pos.x;
    let bestClosestZ = pos.z;

    const n = pts.length;
    for (let i = 0; i < n; i++) {
      const [ax, az] = pts[i];
      const [bx, bz] = pts[(i + 1) % n];
      const ex = bx - ax;
      const ez = bz - az;
      const lenSq = ex * ex + ez * ez;
      let t = lenSq > 1e-6 ? ((pos.x - ax) * ex + (pos.z - az) * ez) / lenSq : 0;
      t = Math.max(0, Math.min(1, t));
      const cx = ax + t * ex;
      const cz = az + t * ez;
      const dx = pos.x - cx;
      const dz = pos.z - cz;
      const dSq = dx * dx + dz * dz;
      if (dSq < bestDistSq) {
        bestDistSq = dSq;
        bestClosestX = cx;
        bestClosestZ = cz;
      }
    }

    if (!inside && bestDistSq >= radius * radius) return;

    const dist = Math.sqrt(bestDistSq);
    if (inside) {
      // Push outward past nearest edge + radius
      const nx = dist > 1e-5 ? (bestClosestX - pos.x) / dist : 1;
      const nz = dist > 1e-5 ? (bestClosestZ - pos.z) / dist : 0;
      pos.x = bestClosestX + nx * radius;
      pos.z = bestClosestZ + nz * radius;
    } else if (dist > 1e-5) {
      const push = radius - dist;
      pos.x += ((pos.x - bestClosestX) / dist) * push;
      pos.z += ((pos.z - bestClosestZ) / dist) * push;
    }
  }

  private rayIntersectBox(
    ox: number,
    oy: number,
    oz: number,
    dx: number,
    dy: number,
    dz: number,
    maxDist: number,
    b: IndexedBoxCollider
  ): { dist: number; nx: number; ny: number; nz: number } | null {
    const hx = b._hx;
    const hz = b._hz;
    const cos = b._cos;
    const sin = b._sin;

    let lox = ox - b._cx;
    let loz = oz - b._cz;
    let ldx = dx;
    let ldz = dz;
    const ry = b.rotationY ?? 0;

    if (ry) {
      const rOx = lox * cos - loz * sin;
      const rOz = lox * sin + loz * cos;
      const rDx = ldx * cos - ldz * sin;
      const rDz = ldx * sin + ldz * cos;
      lox = rOx;
      loz = rOz;
      ldx = rDx;
      ldz = rDz;
    }

    let tmin = 0;
    let tmax = maxDist;
    let hitAxis = -1;
    let hitSign = 1;

    // X slab
    if (Math.abs(ldx) < 1e-8) {
      if (lox < -hx || lox > hx) return null;
    } else {
      const inv = 1 / ldx;
      let t1 = (-hx - lox) * inv;
      let t2 = (hx - lox) * inv;
      let s = -1;
      if (t1 > t2) {
        const tmp = t1;
        t1 = t2;
        t2 = tmp;
        s = 1;
      }
      if (t1 > tmin) {
        tmin = t1;
        hitAxis = 0;
        hitSign = s;
      }
      if (t2 < tmax) tmax = t2;
      if (tmin > tmax) return null;
    }

    // Y slab
    if (Math.abs(dy) < 1e-8) {
      if (oy < b.minY || oy > b.maxY) return null;
    } else {
      const inv = 1 / dy;
      let t1 = (b.minY - oy) * inv;
      let t2 = (b.maxY - oy) * inv;
      let s = -1;
      if (t1 > t2) {
        const tmp = t1;
        t1 = t2;
        t2 = tmp;
        s = 1;
      }
      if (t1 > tmin) {
        tmin = t1;
        hitAxis = 1;
        hitSign = s;
      }
      if (t2 < tmax) tmax = t2;
      if (tmin > tmax) return null;
    }

    // Z slab
    if (Math.abs(ldz) < 1e-8) {
      if (loz < -hz || loz > hz) return null;
    } else {
      const inv = 1 / ldz;
      let t1 = (-hz - loz) * inv;
      let t2 = (hz - loz) * inv;
      let s = -1;
      if (t1 > t2) {
        const tmp = t1;
        t1 = t2;
        t2 = tmp;
        s = 1;
      }
      if (t1 > tmin) {
        tmin = t1;
        hitAxis = 2;
        hitSign = s;
      }
      if (t2 < tmax) tmax = t2;
      if (tmin > tmax) return null;
    }

    if (tmin <= 0.001 || tmin > maxDist) return null;

    let nx = hitAxis === 0 ? hitSign : 0;
    const ny = hitAxis === 1 ? hitSign : 0;
    let nz = hitAxis === 2 ? hitSign : 0;
    if (ry && hitAxis !== 1) {
      const wNx = nx * cos + nz * sin;
      const wNz = -nx * sin + nz * cos;
      nx = wNx;
      nz = wNz;
    }
    const out = this.rayHitScratch;
    out.dist = tmin;
    out.nx = nx;
    out.ny = ny;
    out.nz = nz;
    return out;
  }

  private rayIntersectPolygonPrism(
    ox: number,
    oy: number,
    oz: number,
    dx: number,
    dy: number,
    dz: number,
    maxDist: number,
    p: PolygonCollider
  ): { dist: number; nx: number; ny: number; nz: number } | null {
    // Fast allocation-free 3-axis AABB reject first
    let tmin = 0;
    let tmax = maxDist;

    if (Math.abs(dx) < 1e-8) {
      if (ox < p.minX || ox > p.maxX) return null;
    } else {
      const inv = 1 / dx;
      let t1 = (p.minX - ox) * inv;
      let t2 = (p.maxX - ox) * inv;
      if (t1 > t2) {
        const tmp = t1;
        t1 = t2;
        t2 = tmp;
      }
      if (t1 > tmin) tmin = t1;
      if (t2 < tmax) tmax = t2;
      if (tmin > tmax) return null;
    }

    if (Math.abs(dy) < 1e-8) {
      if (oy < p.minY || oy > p.maxY) return null;
    } else {
      const inv = 1 / dy;
      let t1 = (p.minY - oy) * inv;
      let t2 = (p.maxY - oy) * inv;
      if (t1 > t2) {
        const tmp = t1;
        t1 = t2;
        t2 = tmp;
      }
      if (t1 > tmin) tmin = t1;
      if (t2 < tmax) tmax = t2;
      if (tmin > tmax) return null;
    }

    if (Math.abs(dz) < 1e-8) {
      if (oz < p.minZ || oz > p.maxZ) return null;
    } else {
      const inv = 1 / dz;
      let t1 = (p.minZ - oz) * inv;
      let t2 = (p.maxZ - oz) * inv;
      if (t1 > t2) {
        const tmp = t1;
        t1 = t2;
        t2 = tmp;
      }
      if (t1 > tmin) tmin = t1;
      if (t2 < tmax) tmax = t2;
      if (tmin > tmax) return null;
    }

    let bestDist = maxDist;
    let bestNx = 0;
    let bestNy = 1;
    let bestNz = 0;
    let hit = false;

    // 1. Check horizontal caps (top roof maxY and bottom minY) without temporary tuple allocations
    if (Math.abs(dy) > 1e-6) {
      const invDy = 1 / dy;
      const tTop = (p.maxY - oy) * invDy;
      if (tTop > 0.001 && tTop < bestDist) {
        if (this.pointInPolygon2D(ox + dx * tTop, oz + dz * tTop, p.points)) {
          bestDist = tTop;
          bestNx = 0;
          bestNy = 1;
          bestNz = 0;
          hit = true;
        }
      }
      const tBot = (p.minY - oy) * invDy;
      if (tBot > 0.001 && tBot < bestDist) {
        if (this.pointInPolygon2D(ox + dx * tBot, oz + dz * tBot, p.points)) {
          bestDist = tBot;
          bestNx = 0;
          bestNy = -1;
          bestNz = 0;
          hit = true;
        }
      }
    }

    // 2. Check each vertical polygon wall quad
    const pts = p.points;
    const n = pts.length;
    for (let i = 0; i < n; i++) {
      const [ax, az] = pts[i];
      const [bx, bz] = pts[(i + 1) % n];
      const ex = bx - ax;
      const ez = bz - az;
      // Solve ox + t*dx = ax + u*ex, oz + t*dz = az + u*ez
      const det = dx * ez - dz * ex;
      if (Math.abs(det) < 1e-8) continue;
      const rx = ax - ox;
      const rz = az - oz;
      const t = (rx * ez - rz * ex) / det;
      if (t <= 0.001 || t >= bestDist) continue;
      const u = (rx * dz - rz * dx) / det;
      if (u < 0 || u > 1) continue;
      const hy = oy + dy * t;
      if (hy < p.minY || hy > p.maxY) continue;

      const eLen = Math.hypot(ex, ez);
      let nx = ez / eLen;
      let nz = -ex / eLen;
      if (nx * dx + nz * dz > 0) {
        nx = -nx;
        nz = -nz;
      }
      bestDist = t;
      bestNx = nx;
      bestNy = 0;
      bestNz = nz;
      hit = true;
    }

    if (!hit) return null;
    const out = this.rayHitScratch;
    out.dist = bestDist;
    out.nx = bestNx;
    out.ny = bestNy;
    out.nz = bestNz;
    return out;
  }

  private rayIntersectCylinder(
    ox: number,
    oy: number,
    oz: number,
    dx: number,
    dy: number,
    dz: number,
    maxDist: number,
    c: CylinderCollider
  ): { dist: number; nx: number; ny: number; nz: number } | null {
    const rx = ox - c.x;
    const rz = oz - c.z;
    const a = dx * dx + dz * dz;
    if (a < 1e-8) return null;
    const b = 2 * (rx * dx + rz * dz);
    const k = rx * rx + rz * rz - c.radius * c.radius;
    const disc = b * b - 4 * a * k;
    if (disc < 0) return null;
    const sqrtD = Math.sqrt(disc);
    const t = (-b - sqrtD) / (2 * a);
    if (t <= 0.001 || t > maxDist) return null;
    const hy = oy + dy * t;
    if (hy < c.minY || hy > c.maxY) return null;
    const out = this.rayHitScratch;
    out.dist = t;
    out.nx = (ox + dx * t - c.x) / c.radius;
    out.ny = 0;
    out.nz = (oz + dz * t - c.z) / c.radius;
    return out;
  }

  private segmentSphereIntersect(
    x0: number,
    y0: number,
    z0: number,
    x1: number,
    y1: number,
    z1: number,
    cx: number,
    cy: number,
    cz: number,
    r: number
  ): number | null {
    const dx = x1 - x0;
    const dy = y1 - y0;
    const dz = z1 - z0;
    const fx = x0 - cx;
    const fy = y0 - cy;
    const fz = z0 - cz;

    const a = dx * dx + dy * dy + dz * dz;
    if (a < 1e-9) {
      return fx * fx + fy * fy + fz * fz <= r * r ? 0 : null;
    }
    const b = 2 * (fx * dx + fy * dy + fz * dz);
    const c = fx * fx + fy * fy + fz * fz - r * r;
    const disc = b * b - 4 * a * c;
    if (disc < 0) return null;
    const sqrtD = Math.sqrt(disc);
    const t0 = (-b - sqrtD) / (2 * a);
    if (t0 >= 0 && t0 <= 1) return t0;
    const t1 = (-b + sqrtD) / (2 * a);
    if (t1 >= 0 && t1 <= 1) return 0; // Started inside sphere
    return null;
  }

  private segmentVerticalCapsuleIntersect(
    x0: number,
    y0: number,
    z0: number,
    x1: number,
    y1: number,
    z1: number,
    cx: number,
    cz: number,
    minY: number,
    maxY: number,
    r: number
  ): number | null {
    let bestT: number | null = null;

    // 1. Cylindrical body wall
    const dx = x1 - x0;
    const dy = y1 - y0;
    const dz = z1 - z0;
    const fx = x0 - cx;
    const fz = z0 - cz;
    const a = dx * dx + dz * dz;
    if (a > 1e-9) {
      const b = 2 * (fx * dx + fz * dz);
      const c = fx * fx + fz * fz - r * r;
      const disc = b * b - 4 * a * c;
      if (disc >= 0) {
        const sqrtD = Math.sqrt(disc);
        const t = (-b - sqrtD) / (2 * a);
        if (t >= 0 && t <= 1) {
          const hy = y0 + dy * t;
          if (hy >= minY && hy <= maxY) {
            bestT = t;
          }
        } else if ((-b + sqrtD) / (2 * a) >= 0 && t < 0) {
          if (y0 >= minY && y0 <= maxY) {
            bestT = 0;
          }
        }
      }
    }

    // 2. Endcap spheres
    const tBot = this.segmentSphereIntersect(x0, y0, z0, x1, y1, z1, cx, minY, cz, r);
    if (tBot !== null && (bestT === null || tBot < bestT)) bestT = tBot;

    const tTop = this.segmentSphereIntersect(x0, y0, z0, x1, y1, z1, cx, maxY, cz, r);
    if (tTop !== null && (bestT === null || tTop < bestT)) bestT = tTop;

    return bestT;
  }
}

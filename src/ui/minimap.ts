import { GAME_CONSTANTS } from '../data/catalog';
import { MinimapState, SupplyDropBearing } from '../types';

// Expanded 3x Mountain View Googleplex Arena Bounds (600m x 380m)
// Driven dynamically from GAME_CONSTANTS (MIN_X=-300, MAX_X=+300, MIN_Z=-190, MAX_Z=+190)
const ARENA_MIN_X = GAME_CONSTANTS.ARENA_MIN_X;
const ARENA_MAX_X = GAME_CONSTANTS.ARENA_MAX_X;
const ARENA_MIN_Z = GAME_CONSTANTS.ARENA_MIN_Z;
const ARENA_MAX_Z = GAME_CONSTANTS.ARENA_MAX_Z;
const ARENA_W = GAME_CONSTANTS.ARENA_WIDTH;
const ARENA_D = GAME_CONSTANTS.ARENA_DEPTH;

// Exact Core Googleplex Quad world XZ polygons (matching src/world/googleplex.ts & docs/googleplex-map-topdown.svg)
const B41_WORLD_POLY: [number, number][] = [
  [-128.55, -26.52],
  [-118.21, -12.72],
  [-102.34, -16.86],
  [-92.69, -38.93],
  [-111.31, -49.28],
  [-129.93, -41.69],
];

const B42_WORLD_POLY: [number, number][] = [
  [-132.52, 24.38],
  [-129.76, 43.0],
  [-108.38, 43.69],
  [-100.79, 23.0],
  [-106.31, 3.0],
  [-131.14, 4.38],
];

const B40_WORLD_POLY: [number, number][] = [
  [-85.14, -17.9],
  [-61.69, -10.31],
  [-26.52, -4.1],
  [-1.0, -7.55],
  [3.14, -19.28],
  [-18.24, -28.93],
  [-49.97, -37.9],
  [-83.07, -34.45],
];

const B43_WORLD_POLY: [number, number][] = [
  [-99.38, 41.62],
  [-51.1, 48.52],
  [-16.62, 47.83],
  [-24.9, 25.76],
  [-64.9, 17.48],
  [-98.0, 20.93],
];

const CARDINALS: { deg: number; label: string; major: boolean }[] = [
  { deg: 0, label: 'N', major: true },
  { deg: 45, label: 'NE', major: false },
  { deg: 90, label: 'E', major: true },
  { deg: 135, label: 'SE', major: false },
  { deg: 180, label: 'S', major: true },
  { deg: 225, label: 'SW', major: false },
  { deg: 270, label: 'W', major: true },
  { deg: 315, label: 'NW', major: false },
];

interface MapProjection {
  cssW: number;
  cssH: number;
  scale: number; // cssW / 240 (1.0 on minimap, 3.75 on 900x570 full map)
  wx: (worldX: number) => number;
  wz: (worldZ: number) => number;
  wr: (worldDist: number) => number;
  wrZ: (worldDist: number) => number;
}

export interface CompassWaypointMarker {
  bearingRad: number;
  dist: number;
}

interface FullMapLandmarkPill {
  label: string;
  x: number;
  z: number;
  color: string;
  highTier?: boolean;
}

const FULL_MAP_LANDMARK_PILLS: FullMapLandmarkPill[] = [
  // Core Quad & Central Campus
  { label: 'STAN PLAZA', x: -51, z: 4, color: '#fbbc04', highTier: true },
  { label: "B40 CHARLIE'S", x: -41, z: -24, color: '#f87171', highTier: true },
  { label: 'B41', x: -112, z: -31, color: '#60a5fa' },
  { label: 'B42', x: -117, z: 24, color: '#2dd4bf' },
  { label: 'B43', x: -58, z: 35, color: '#fbbf24', highTier: true },
  { label: 'CHARLESTON ART GARDEN', x: 24, z: -12, color: '#4ade80', highTier: true },
  { label: 'CHARLESTON GYM', x: 16, z: 33, color: '#60a5fa' },
  { label: 'GRADIENT CANOPY', x: 113, z: 4, color: '#38bdf8', highTier: true },
  { label: 'THE ORB', x: 152, z: 60, color: '#c084fc', highTier: true },
  // North Ring
  { label: 'ATHLETIC GYM', x: -220, z: -168, color: '#60a5fa' },
  { label: 'ATHLETIC FIELD', x: -220, z: -134, color: '#4ade80' },
  { label: 'BAY POINT GARDEN', x: -62, z: -138, color: '#a3e635', highTier: true },
  { label: 'SHORELINE AMPHITHEATRE', x: 58, z: -148, color: '#38bdf8', highTier: true },
  { label: 'LOT C', x: 124, z: -112, color: '#94a3b8' },
  // West Ring
  { label: 'GOOGLE 2000 / 1950', x: -225, z: 2, color: '#60a5fa', highTier: true },
  { label: 'CREEKSIDE GARDEN', x: -226, z: 124, color: '#4ade80', highTier: true },
  // South Ring
  { label: '1098 ALTA', x: -108, z: 126, color: '#38bdf8' },
  { label: 'CHARLESTON CAMPUS', x: 28, z: 134, color: '#fbbf24', highTier: true },
  { label: 'EASTSIDE GYM', x: 126, z: 126, color: '#60a5fa' },
  // East Ring (East of N Shoreline Blvd)
  { label: 'GOOGLE CL2', x: 236, z: -140, color: '#2dd4bf' },
  { label: 'GOOGLE 2015', x: 234, z: -22, color: '#818cf8', highTier: true },
  { label: 'GOOGLE 1395', x: 234, z: 122, color: '#f472b6' },
];

interface RoadLabelSpec {
  label: string;
  x: number;
  z: number;
  angleDeg: number;
}

const FULL_MAP_ROAD_LABELS: RoadLabelSpec[] = [
  { label: 'AMPHITHEATRE PKWY', x: -90, z: -61, angleDeg: 7 },
  { label: 'AMPHITHEATRE PKWY', x: 76, z: -61, angleDeg: -5 },
  { label: 'CHARLESTON RD', x: -102, z: 59, angleDeg: 3.5 },
  { label: 'CHARLESTON RD', x: 112, z: 73, angleDeg: 3.5 },
  { label: 'N SHORELINE BLVD', x: 168, z: -24, angleDeg: -90 },
  { label: 'PERMANENTE CREEK TRAIL', x: -150, z: -90, angleDeg: -90 },
  { label: 'JOAQUIN RD', x: 60, z: 19, angleDeg: -82 },
  { label: 'ALTA / HUFF', x: -50, z: 112, angleDeg: -90 },
  { label: 'PLYMOUTH ST', x: -4, z: 179, angleDeg: 0 },
  { label: 'CRITTENDEN LN', x: 234, z: -108, angleDeg: 0 },
  { label: 'STIERLIN CT', x: 234, z: -65, angleDeg: 0 },
  { label: 'SHOREBIRD WAY', x: 234, z: 160, angleDeg: 0 },
];

function createProjection(cssW: number, cssH: number): MapProjection {
  return {
    cssW,
    cssH,
    scale: cssW / 240,
    wx: (worldX: number) => ((worldX - ARENA_MIN_X) / ARENA_W) * cssW,
    wz: (worldZ: number) => ((worldZ - ARENA_MIN_Z) / ARENA_D) * cssH,
    wr: (worldDist: number) => (worldDist / ARENA_W) * cssW,
    wrZ: (worldDist: number) => (worldDist / ARENA_D) * cssH,
  };
}

function wrapDeg(deg: number): number {
  return ((deg % 360) + 360) % 360;
}

function degToCardinal(deg: number): string {
  const idx = Math.round(wrapDeg(deg) / 45) % 8;
  return CARDINALS[idx].label;
}

function drawRoundedRectPath(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number
): void {
  const radius = Math.min(r, w * 0.5, h * 0.5);
  ctx.beginPath();
  ctx.moveTo(x + radius, y);
  ctx.lineTo(x + w - radius, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + radius);
  ctx.lineTo(x + w, y + h - radius);
  ctx.quadraticCurveTo(x + w, y + h, x + w - radius, y + h);
  ctx.lineTo(x + radius, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - radius);
  ctx.lineTo(x, y + radius);
  ctx.quadraticCurveTo(x, y, x + radius, y);
  ctx.closePath();
}

export class TacticalMinimap {
  private canvas: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;
  private compassCanvas: HTMLCanvasElement | null;
  private compassCtx: CanvasRenderingContext2D | null;
  private compassDegEl: HTMLElement | null;

  private cssW = 240;
  private cssH = 152;
  private dpr = 1;
  private proj: MapProjection;
  private staticLayer: HTMLCanvasElement;

  private fullStaticLayer: HTMLCanvasElement | null = null;
  private fullCssW = 900;
  private fullCssH = 570;
  private fullDpr = 1;
  private fullProj: MapProjection;
  private fullCanvasRef: HTMLCanvasElement | null = null;

  private compassW = 340;
  private compassH = 30;
  private compassDpr = 1;
  private lastCompassSig = '';
  private lastCompassText = '';

  constructor(
    minimapCanvas: HTMLCanvasElement,
    compassCanvas?: HTMLCanvasElement | null,
    compassDegEl?: HTMLElement | null
  ) {
    this.canvas = minimapCanvas;
    const ctx = minimapCanvas.getContext('2d');
    if (!ctx) throw new Error('Failed to acquire 2D context for minimap canvas');
    this.ctx = ctx;

    this.dpr = Math.min(window.devicePixelRatio || 1, 2);
    this.cssW = minimapCanvas.width || 240;
    this.cssH = minimapCanvas.height || 152;
    this.canvas.width = Math.round(this.cssW * this.dpr);
    this.canvas.height = Math.round(this.cssH * this.dpr);
    this.proj = createProjection(this.cssW, this.cssH);

    this.staticLayer = document.createElement('canvas');
    this.staticLayer.width = this.canvas.width;
    this.staticLayer.height = this.canvas.height;
    this.bakeStaticGoogleplexMap(this.staticLayer, this.proj, this.dpr, false);

    this.fullProj = createProjection(this.fullCssW, this.fullCssH);

    this.compassCanvas = compassCanvas ?? null;
    this.compassDegEl = compassDegEl ?? null;
    if (this.compassCanvas) {
      this.compassCtx = this.compassCanvas.getContext('2d');
      this.compassDpr = Math.min(window.devicePixelRatio || 1, 2);
      this.compassW = this.compassCanvas.width || 340;
      this.compassH = this.compassCanvas.height || 30;
      this.compassCanvas.width = Math.round(this.compassW * this.compassDpr);
      this.compassCanvas.height = Math.round(this.compassH * this.compassDpr);
    } else {
      this.compassCtx = null;
    }
  }

  /**
   * Converts a pointer event position on the tactical map canvas directly into exact
   * Mountain View campus world coordinates (X ∈ [-300, +300], Z ∈ [-190, +190]).
   */
  public static canvasToWorld(
    canvas: HTMLCanvasElement,
    clientX: number,
    clientY: number
  ): { x: number; z: number } {
    const rect = canvas.getBoundingClientRect();
    const u = Math.max(0, Math.min(1, (clientX - rect.left) / Math.max(1, rect.width)));
    const v = Math.max(0, Math.min(1, (clientY - rect.top) / Math.max(1, rect.height)));
    return {
      x: ARENA_MIN_X + u * ARENA_W,
      z: ARENA_MIN_Z + v * ARENA_D,
    };
  }

  private polyWorld(ctx: CanvasRenderingContext2D, proj: MapProjection, pts: [number, number][]): void {
    ctx.beginPath();
    pts.forEach(([x, z], i) => {
      if (i === 0) ctx.moveTo(proj.wx(x), proj.wz(z));
      else ctx.lineTo(proj.wx(x), proj.wz(z));
    });
    ctx.closePath();
  }

  private drawEastOfficeComplex(
    ctx: CanvasRenderingContext2D,
    proj: MapProjection,
    cx: number,
    cz: number,
    fill: string,
    stroke: string,
    notchSouth: boolean,
    detailed: boolean
  ): void {
    const hw = 34; // 68m wide
    const hd = 23; // 46m deep
    const nw = 10.5;
    const nd = 10;

    // Subtle paved apron pad
    ctx.fillStyle = 'rgba(203, 213, 225, 0.16)';
    ctx.fillRect(
      proj.wx(cx - hw - 3),
      proj.wz(cz - hd - 3),
      proj.wr((hw + 3) * 2),
      proj.wrZ((hd + 3) * 2)
    );

    const pts: [number, number][] = notchSouth
      ? [
          [cx - hw, cz - hd],
          [cx + hw, cz - hd],
          [cx + hw, cz + hd],
          [cx + nw, cz + hd],
          [cx + nw, cz + hd - nd],
          [cx - nw, cz + hd - nd],
          [cx - nw, cz + hd],
          [cx - hw, cz + hd],
        ]
      : [
          [cx - hw, cz - hd],
          [cx - nw, cz - hd],
          [cx - nw, cz - hd + nd],
          [cx + nw, cz - hd + nd],
          [cx + nw, cz - hd],
          [cx + hw, cz - hd],
          [cx + hw, cz + hd],
          [cx - hw, cz + hd],
        ];

    this.polyWorld(ctx, proj, pts);
    ctx.fillStyle = fill;
    ctx.fill();
    ctx.strokeStyle = stroke;
    ctx.lineWidth = detailed ? 1.7 : 0.9;
    ctx.stroke();
  }

  /**
   * Pre-renders the expanded 3x Mountain View Googleplex campus (600m x 380m)
   * directly matching SPEC §10 & docs/googleplex-map-topdown.svg in world meters.
   * Shared identically between the 240x152 corner minimap and 900x570 Full Tactical Map.
   */
  private bakeStaticGoogleplexMap(
    targetCanvas: HTMLCanvasElement,
    proj: MapProjection,
    dpr: number,
    detailed: boolean
  ): void {
    const ctx = targetCanvas.getContext('2d');
    if (!ctx) return;

    const sw = detailed ? 1.8 : 1.0;

    ctx.save();
    ctx.scale(dpr, dpr);

    // 1. Base Mountain View Campus Lawn
    ctx.fillStyle = '#1f4429';
    ctx.fillRect(0, 0, proj.cssW, proj.cssH);

    // 2. Bay Point Regional Shoreline Overlook Golden-Green Bluffs (North of Amphitheatre Pkwy)
    const hillsGrad = ctx.createLinearGradient(0, proj.wz(ARENA_MIN_Z), 0, proj.wz(-52));
    hillsGrad.addColorStop(0, '#787148');
    hillsGrad.addColorStop(0.65, '#5a6b3d');
    hillsGrad.addColorStop(1, '#3b5a30');
    ctx.fillStyle = hillsGrad;
    ctx.beginPath();
    ctx.moveTo(proj.wx(-152), proj.wz(ARENA_MIN_Z));
    ctx.lineTo(proj.wx(168), proj.wz(ARENA_MIN_Z));
    ctx.lineTo(proj.wx(168), proj.wz(-67.2));
    ctx.quadraticCurveTo(proj.wx(62.1), proj.wz(-57.6), proj.wx(-13.8), proj.wz(-52.8));
    ctx.quadraticCurveTo(proj.wx(-93.1), proj.wz(-58.3), proj.wx(-152), proj.wz(-69));
    ctx.closePath();
    ctx.fill();

    // Bay Point Overlook subtle bluff rings & dashed dirt trails
    ctx.save();
    ctx.strokeStyle = detailed ? 'rgba(226, 223, 201, 0.3)' : 'rgba(226, 223, 201, 0.25)';
    ctx.lineWidth = detailed ? 1.2 : 0.7;
    ctx.beginPath();
    ctx.ellipse(proj.wx(-62), proj.wz(-144), proj.wr(56), proj.wrZ(26), 0, 0, Math.PI * 2);
    ctx.stroke();
    ctx.beginPath();
    ctx.ellipse(proj.wx(-62), proj.wz(-144), proj.wr(32), proj.wrZ(15), 0, 0, Math.PI * 2);
    ctx.stroke();

    ctx.strokeStyle = detailed ? 'rgba(226, 223, 201, 0.48)' : 'rgba(226, 223, 201, 0.42)';
    ctx.lineWidth = detailed ? 1.6 : 0.85;
    ctx.setLineDash(detailed ? [6, 5] : [2.5, 2.2]);
    ctx.beginPath();
    ctx.moveTo(proj.wx(-142), proj.wz(-108));
    ctx.quadraticCurveTo(proj.wx(-100), proj.wz(-126), proj.wx(-62), proj.wz(-135));
    ctx.quadraticCurveTo(proj.wx(-10), proj.wz(-128), proj.wx(26), proj.wz(-118));
    ctx.stroke();
    ctx.restore();

    // Subtle 60m tactical coordinate grid aligned to (0, 0)
    ctx.strokeStyle = detailed ? 'rgba(255, 255, 255, 0.07)' : 'rgba(255, 255, 255, 0.05)';
    ctx.lineWidth = detailed ? 1.0 : 0.6;
    for (let x = -240; x <= 240; x += 60) {
      if (x <= ARENA_MIN_X || x >= ARENA_MAX_X) continue;
      const px = proj.wx(x);
      ctx.beginPath();
      ctx.moveTo(px, 0);
      ctx.lineTo(px, proj.cssH);
      ctx.stroke();
    }
    for (let z = -120; z <= 120; z += 60) {
      if (z <= ARENA_MIN_Z || z >= ARENA_MAX_Z) continue;
      const py = proj.wz(z);
      ctx.beginPath();
      ctx.moveTo(0, py);
      ctx.lineTo(proj.cssW, py);
      ctx.stroke();
    }

    // 3. Permanente Creek (Full N-S at X = -156m) & Paved Bike/Foot Trail (X = -150m)
    const creekW = Math.max(2.1, proj.wr(4.2));
    const creekX0 = proj.wx(-156) - creekW * 0.5;
    const creekGrad = ctx.createLinearGradient(creekX0, 0, creekX0 + creekW, 0);
    creekGrad.addColorStop(0, '#0369a1');
    creekGrad.addColorStop(0.5, '#38bdf8');
    creekGrad.addColorStop(1, '#0369a1');
    ctx.fillStyle = creekGrad;
    ctx.fillRect(creekX0, 0, creekW, proj.cssH);

    ctx.strokeStyle = 'rgba(226, 232, 240, 0.72)';
    ctx.lineWidth = Math.max(0.95, proj.wr(2.0));
    ctx.beginPath();
    ctx.moveTo(proj.wx(-150), 0);
    ctx.lineTo(proj.wx(-150), proj.cssH);
    ctx.stroke();

    // 4. All Mountain View Campus Roads & Arteries
    ctx.lineCap = 'butt';
    ctx.lineJoin = 'round';

    const drawRoad = (drawPath: () => void, metersWidth: number, dashed = true): void => {
      if (detailed) {
        // Subtle dark asphalt curb edge for crisp contrast on full map
        ctx.strokeStyle = 'rgba(15, 23, 42, 0.68)';
        ctx.lineWidth = Math.max(3.2, proj.wr(metersWidth) + 2.4);
        drawPath();
        ctx.stroke();
      }

      ctx.strokeStyle = '#334155';
      ctx.lineWidth = Math.max(1.8, proj.wr(metersWidth));
      drawPath();
      ctx.stroke();

      if (dashed) {
        ctx.save();
        ctx.strokeStyle = detailed ? 'rgba(226, 232, 240, 0.44)' : 'rgba(203, 213, 225, 0.38)';
        ctx.lineWidth = detailed ? 1.1 : 0.55;
        ctx.setLineDash(detailed ? [7, 7] : [2.5, 2.5]);
        drawPath();
        ctx.stroke();
        ctx.restore();
      }
    };

    // Amphitheatre Parkway (NW Edge -> Core Curve -> N Shoreline Blvd)
    drawRoad(() => {
      ctx.beginPath();
      ctx.moveTo(proj.wx(ARENA_MIN_X), proj.wz(-109));
      ctx.lineTo(proj.wx(-282), proj.wz(-104));
      ctx.quadraticCurveTo(proj.wx(-228), proj.wz(-88), proj.wx(-170), proj.wz(-72.4));
      ctx.quadraticCurveTo(proj.wx(-93.1), proj.wz(-58.3), proj.wx(-13.8), proj.wz(-52.8));
      ctx.quadraticCurveTo(proj.wx(62.1), proj.wz(-57.6), proj.wx(168), proj.wz(-67.2));
    }, 9.0);

    // Sweeping Western Charleston Rd Curve (-282,-104 -> -210,+53 -> -170,+55.5) + Inner & East Charleston Rd
    drawRoad(() => {
      ctx.beginPath();
      ctx.moveTo(proj.wx(-282), proj.wz(-104));
      ctx.bezierCurveTo(
        proj.wx(-293),
        proj.wz(-50),
        proj.wx(-292),
        proj.wz(16),
        proj.wx(-268),
        proj.wz(42)
      );
      ctx.quadraticCurveTo(proj.wx(-246), proj.wz(52), proj.wx(-210), proj.wz(53));
      ctx.lineTo(proj.wx(-170), proj.wz(55.5));
      ctx.lineTo(proj.wx(168), proj.wz(76.8));
      ctx.lineTo(proj.wx(ARENA_MAX_X), proj.wz(85));
    }, 8.6);

    // N Shoreline Blvd (Full N-S at X = +168m)
    drawRoad(() => {
      ctx.beginPath();
      ctx.moveTo(proj.wx(168), proj.wz(ARENA_MIN_Z));
      ctx.lineTo(proj.wx(168), proj.wz(ARENA_MAX_Z));
    }, 9.4);

    // East Ring Arteries: Crittenden Ln (-108), Stierlin Ct (-65), Shorebird Way (+160)
    drawRoad(() => {
      ctx.beginPath();
      ctx.moveTo(proj.wx(168), proj.wz(-108));
      ctx.lineTo(proj.wx(ARENA_MAX_X), proj.wz(-108));
      ctx.moveTo(proj.wx(168), proj.wz(-65));
      ctx.lineTo(proj.wx(ARENA_MAX_X), proj.wz(-65));
      ctx.moveTo(proj.wx(168), proj.wz(160));
      ctx.lineTo(proj.wx(ARENA_MAX_X), proj.wz(160));
    }, 6.8, false);

    // Plymouth St (South Border Z = +180m, X in [-150, +168])
    drawRoad(() => {
      ctx.beginPath();
      ctx.moveTo(proj.wx(-150), proj.wz(180));
      ctx.lineTo(proj.wx(168), proj.wz(180));
    }, 6.8, false);

    // Bill Graham Pkwy -> Curved Joaquin Rd (Core + South flank of Charleston Campus)
    drawRoad(() => {
      ctx.beginPath();
      ctx.moveTo(proj.wx(76), proj.wz(-116));
      ctx.lineTo(proj.wx(73.8), proj.wz(-59.1));
      ctx.quadraticCurveTo(proj.wx(53.8), proj.wz(-38.5), proj.wx(56.6), proj.wz(-3.8));
      ctx.quadraticCurveTo(proj.wx(58.6), proj.wz(30.5), proj.wx(77.2), proj.wz(71.1));
      ctx.quadraticCurveTo(proj.wx(91.7), proj.wz(113.3), proj.wx(92.2), proj.wz(180));
    }, 6.6);

    // Alta Ave (X = -64m), Huff Ave (X = -36m), and Parking Lot C Spur
    drawRoad(() => {
      ctx.beginPath();
      ctx.moveTo(proj.wx(-64), proj.wz(62));
      ctx.lineTo(proj.wx(-64), proj.wz(180));
      ctx.moveTo(proj.wx(-36), proj.wz(64));
      ctx.lineTo(proj.wx(-36), proj.wz(180));
      ctx.moveTo(proj.wx(75), proj.wz(-108));
      ctx.lineTo(proj.wx(98), proj.wz(-108));
    }, 5.8, false);

    // Pedestrian Footbridge over Permanente Creek (Google 2000/1950 <-> Core Quad)
    ctx.fillStyle = '#e2e8f0';
    ctx.fillRect(proj.wx(-163), proj.wz(-5), proj.wr(17), proj.wrZ(6));
    ctx.strokeStyle = '#0f172a';
    ctx.lineWidth = 0.6 * sw;
    ctx.strokeRect(proj.wx(-163), proj.wz(-5), proj.wr(17), proj.wrZ(6));

    // ==================== NORTH RING LANDMARKS ====================

    // 5. Google Athletic Recreation Field (-220, -134; 66m x 42m)
    const afX = proj.wx(-253);
    const afY = proj.wz(-155);
    const afW = proj.wr(66);
    const afH = proj.wrZ(42);
    ctx.fillStyle = '#238636';
    ctx.fillRect(afX, afY, afW, afH);
    // Subtle mowing bands
    ctx.fillStyle = '#2b9a43';
    const bandW = afW / 6;
    for (let b = 0; b < 6; b += 2) {
      ctx.fillRect(afX + b * bandW, afY, bandW, afH);
    }
    ctx.strokeStyle = '#86efac';
    ctx.lineWidth = 0.85 * sw;
    ctx.strokeRect(afX, afY, afW, afH);
    // White pitch outline, halfway line & center circle
    const pad = detailed ? 4 : 1.5;
    ctx.strokeStyle = 'rgba(248, 250, 252, 0.88)';
    ctx.lineWidth = 0.6 * sw;
    ctx.strokeRect(afX + pad, afY + pad, afW - pad * 2, afH - pad * 2);
    ctx.beginPath();
    ctx.moveTo(afX + afW * 0.5, afY + pad);
    ctx.lineTo(afX + afW * 0.5, afY + afH - pad);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(afX + afW * 0.5, afY + afH * 0.5, Math.max(2.2, proj.wr(6.5)), 0, Math.PI * 2);
    ctx.stroke();

    // 6. Shoreline Amphitheatre (+58, -148; 64m x 56m)
    const ampX = proj.wx(58);
    const ampY = proj.wz(-148);
    ctx.save();
    ctx.translate(ampX, ampY);
    // Terraced seating bowl
    ctx.beginPath();
    ctx.ellipse(0, proj.wrZ(4), proj.wr(31), proj.wrZ(25), 0, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(63, 98, 18, 0.78)';
    ctx.fill();
    ctx.strokeStyle = 'rgba(132, 204, 22, 0.65)';
    ctx.lineWidth = 0.7 * sw;
    ctx.stroke();
    // Iconic twin-peak white concert tent
    ctx.beginPath();
    ctx.moveTo(proj.wr(-29), proj.wrZ(-8));
    ctx.quadraticCurveTo(proj.wr(-13), proj.wrZ(-26), 0, proj.wrZ(-17));
    ctx.quadraticCurveTo(proj.wr(14), proj.wrZ(-26), proj.wr(29), proj.wrZ(-8));
    ctx.quadraticCurveTo(proj.wr(26), proj.wrZ(10), 0, proj.wrZ(13));
    ctx.quadraticCurveTo(proj.wr(-26), proj.wrZ(10), proj.wr(-29), proj.wrZ(-8));
    ctx.closePath();
    ctx.fillStyle = '#f8fafc';
    ctx.fill();
    ctx.strokeStyle = '#38bdf8';
    ctx.lineWidth = 1.05 * sw;
    ctx.stroke();
    // Twin steel mast dots
    ctx.fillStyle = '#0284c7';
    ctx.beginPath();
    ctx.arc(proj.wr(-12), proj.wrZ(-6), detailed ? 3.2 : 1.3, 0, Math.PI * 2);
    ctx.arc(proj.wr(12), proj.wrZ(-6), detailed ? 3.2 : 1.3, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();

    // 7. Parking Lot C (+118, -112)
    const lotX = proj.wx(97);
    const lotY = proj.wz(-129);
    const lotW = proj.wr(58);
    const lotH = proj.wrZ(40);
    ctx.fillStyle = 'rgba(51, 65, 85, 0.88)';
    ctx.fillRect(lotX, lotY, lotW, lotH);
    ctx.strokeStyle = '#64748b';
    ctx.lineWidth = 0.75 * sw;
    ctx.strokeRect(lotX, lotY, lotW, lotH);
    ctx.strokeStyle = 'rgba(203, 213, 225, 0.35)';
    ctx.lineWidth = 0.5 * sw;
    for (let r = 1; r <= 3; r++) {
      const ly = lotY + (lotH * r) / 4;
      ctx.beginPath();
      ctx.moveTo(lotX + (detailed ? 5 : 2), ly);
      ctx.lineTo(lotX + lotW - (detailed ? 5 : 2), ly);
      ctx.stroke();
    }

    // ==================== WEST RING LANDMARK ====================

    // 8. Google 2000 & 1950 Complex (-225, +2; 82m x 92m)
    ctx.fillStyle = 'rgba(203, 213, 225, 0.18)';
    ctx.fillRect(proj.wx(-267), proj.wz(-44), proj.wr(86), proj.wrZ(92));
    // Central green courtyard
    ctx.fillStyle = '#2f6d3b';
    ctx.fillRect(proj.wx(-258), proj.wz(-7), proj.wr(70), proj.wrZ(15));
    // Google 2000 (North curving wing)
    ctx.beginPath();
    ctx.moveTo(proj.wx(-264), proj.wz(-36));
    ctx.quadraticCurveTo(proj.wx(-225), proj.wz(-46), proj.wx(-186), proj.wz(-36));
    ctx.lineTo(proj.wx(-188), proj.wz(-10));
    ctx.quadraticCurveTo(proj.wx(-225), proj.wz(-17), proj.wx(-262), proj.wz(-10));
    ctx.closePath();
    ctx.fillStyle = '#2563eb';
    ctx.fill();
    ctx.strokeStyle = '#93c5fd';
    ctx.lineWidth = 0.9 * sw;
    ctx.stroke();
    // Google 1950 (South curving wing)
    ctx.beginPath();
    ctx.moveTo(proj.wx(-262), proj.wz(12));
    ctx.quadraticCurveTo(proj.wx(-225), proj.wz(19), proj.wx(-188), proj.wz(12));
    ctx.lineTo(proj.wx(-186), proj.wz(40));
    ctx.quadraticCurveTo(proj.wx(-225), proj.wz(47), proj.wx(-263), proj.wz(39));
    ctx.closePath();
    ctx.fillStyle = '#0d9488';
    ctx.fill();
    ctx.strokeStyle = '#5eead4';
    ctx.lineWidth = 0.9 * sw;
    ctx.stroke();

    // ==================== CORE GOOGLEPLEX CENTER ====================

    // 9. Googleplex Central Quad Apron & Courtyard Lawn
    this.polyWorld(ctx, proj, [
      [-143, -55],
      [-14, -44],
      [4, -6],
      [-3, 52],
      [-143, 47],
    ]);
    ctx.fillStyle = 'rgba(203, 213, 225, 0.2)';
    ctx.fill();
    ctx.strokeStyle = 'rgba(148, 163, 184, 0.38)';
    ctx.lineWidth = 0.65 * sw;
    ctx.stroke();

    // West Parking Strip beside Permanente Creek
    ctx.fillStyle = 'rgba(51, 65, 85, 0.74)';
    ctx.fillRect(proj.wx(-141), proj.wz(-48), proj.wr(8.5), proj.wrZ(90));

    // Central Courtyard Lawn
    this.polyWorld(ctx, proj, [
      [-105, -16],
      [-29, -11],
      [-31, 20],
      [-106, 17],
    ]);
    ctx.fillStyle = '#336b3c';
    ctx.fill();

    // Charleston Park (+28, -10)
    ctx.beginPath();
    ctx.moveTo(proj.wx(-2), proj.wz(-45));
    ctx.quadraticCurveTo(proj.wx(29), proj.wz(-48), proj.wx(54), proj.wz(-49));
    ctx.quadraticCurveTo(proj.wx(52), proj.wz(-6), proj.wx(62), proj.wz(51));
    ctx.lineTo(proj.wx(8), proj.wz(50));
    ctx.lineTo(proj.wx(7), proj.wz(21));
    ctx.lineTo(proj.wx(3), proj.wz(-8));
    ctx.closePath();
    ctx.fillStyle = '#1b5e2e';
    ctx.fill();
    ctx.strokeStyle = 'rgba(74, 222, 128, 0.45)';
    ctx.lineWidth = 0.8 * sw;
    ctx.stroke();

    // Charleston Park oak clusters (framing Art Garden & Outdoor Gym)
    const parkTrees: [number, number, number][] = [
      [15, -32, 5.5],
      [35, -35, 6.2],
      [47, -24, 5.2],
      [14, -1, 5.2],
      [45, 4, 5.4],
      [49, 14, 5.0],
      [16, 32, 5.4],
      [47, 34, 5.4],
    ];
    for (const [tx, tz, tr] of parkTrees) {
      ctx.beginPath();
      ctx.arc(proj.wx(tx), proj.wz(tz), Math.max(1.5, proj.wr(tr)), 0, Math.PI * 2);
      ctx.fillStyle = '#15803d';
      ctx.fill();
      if (detailed) {
        ctx.strokeStyle = 'rgba(134, 239, 172, 0.25)';
        ctx.lineWidth = 1;
        ctx.stroke();
      }
    }

    // SE Quad Parking Pad
    ctx.fillStyle = 'rgba(51, 65, 85, 0.82)';
    ctx.fillRect(proj.wx(-14), proj.wz(26), proj.wr(15), proj.wrZ(22));

    // Quad Buildings (Exact B41, B42, B40, B43 World Polygons)
    const drawQuadBuilding = (poly: [number, number][], fill: string, stroke: string): void => {
      this.polyWorld(ctx, proj, poly);
      ctx.fillStyle = fill;
      ctx.fill();
      ctx.strokeStyle = stroke;
      ctx.lineWidth = 0.85 * sw;
      ctx.stroke();
    };
    drawQuadBuilding(B41_WORLD_POLY, '#2563eb', '#93c5fd');
    drawQuadBuilding(B42_WORLD_POLY, '#0f766e', '#5eead4');
    drawQuadBuilding(B40_WORLD_POLY, '#b91c1c', '#fca5a5');
    drawQuadBuilding(B43_WORLD_POLY, '#d97706', '#fde68a');

    // Elevated Diagonal Glass Skybridge (-73, +2)
    this.polyWorld(ctx, proj, [
      [-79, -16],
      [-71.5, -15],
      [-66, 20],
      [-73.5, 21],
    ]);
    ctx.fillStyle = 'rgba(186, 230, 253, 0.92)';
    ctx.fill();
    ctx.strokeStyle = '#0284c7';
    ctx.lineWidth = 0.75 * sw;
    ctx.stroke();

    // Sand Volleyball Court (-91, +4)
    ctx.save();
    ctx.translate(proj.wx(-91), proj.wz(4));
    ctx.rotate((-10 * Math.PI) / 180);
    const vw = proj.wr(18);
    const vh = proj.wrZ(10);
    ctx.fillStyle = '#f3d69b';
    ctx.fillRect(-vw * 0.5, -vh * 0.5, vw, vh);
    ctx.strokeStyle = '#b45309';
    ctx.lineWidth = 0.6 * sw;
    ctx.strokeRect(-vw * 0.5, -vh * 0.5, vw, vh);
    ctx.restore();

    // Stan the T-Rex Plaza (-51, +4) + Google Umbrellas
    const stanX = proj.wx(-51);
    const stanY = proj.wz(4);
    ctx.beginPath();
    ctx.arc(stanX, stanY, Math.max(2.6, proj.wr(8)), 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(226, 232, 240, 0.9)';
    ctx.fill();
    ctx.strokeStyle = '#fbbc04';
    ctx.lineWidth = 0.85 * sw;
    ctx.stroke();

    const umbrellas: [number, number, string][] = [
      [-61, -3, '#4285f4'],
      [-60, 12, '#ea4335'],
      [-41, -3, '#fbbc04'],
      [-41, 12, '#34a853'],
    ];
    for (const [ux, uz, col] of umbrellas) {
      ctx.beginPath();
      ctx.arc(proj.wx(ux), proj.wz(uz), detailed ? 3.5 : 1.35, 0, Math.PI * 2);
      ctx.fillStyle = col;
      ctx.fill();
      if (detailed) {
        ctx.strokeStyle = 'rgba(15, 23, 42, 0.75)';
        ctx.lineWidth = 0.9;
        ctx.stroke();
      }
    }

    // 10. Gradient Canopy (+113, +4; Diamond-Quilted White Dragonscale Roof)
    ctx.save();
    ctx.translate(proj.wx(113), proj.wz(4));
    const traceCanopyOutline = (): void => {
      ctx.beginPath();
      ctx.moveTo(proj.wr(-39), proj.wrZ(-41));
      ctx.quadraticCurveTo(0, proj.wrZ(-49), proj.wr(37), proj.wrZ(-44));
      ctx.quadraticCurveTo(proj.wr(47), 0, proj.wr(43), proj.wrZ(42));
      ctx.quadraticCurveTo(proj.wr(4), proj.wrZ(52), proj.wr(-33), proj.wrZ(48));
      ctx.quadraticCurveTo(proj.wr(-48), proj.wrZ(3), proj.wr(-39), proj.wrZ(-41));
      ctx.closePath();
    };
    traceCanopyOutline();
    ctx.fillStyle = 'rgba(241, 245, 249, 0.93)';
    ctx.fill();

    // Clipped diamond dragonscale hatch scaled properly to canvas resolution
    ctx.save();
    ctx.clip();
    ctx.strokeStyle = 'rgba(100, 116, 139, 0.36)';
    ctx.lineWidth = detailed ? 0.9 : 0.55;
    const hatchSpan = proj.wr(76);
    const hatchStep = proj.wr(13.5);
    for (let i = -hatchSpan; i <= hatchSpan; i += hatchStep) {
      ctx.beginPath();
      ctx.moveTo(i - hatchSpan, -hatchSpan);
      ctx.lineTo(i + hatchSpan, hatchSpan);
      ctx.moveTo(i + hatchSpan, -hatchSpan);
      ctx.lineTo(i - hatchSpan, hatchSpan);
      ctx.stroke();
    }
    ctx.restore();

    // Re-trace the Gradient Canopy outline before stroking (ctx.restore does not restore paths)
    traceCanopyOutline();
    ctx.strokeStyle = '#3b82f6';
    ctx.lineWidth = 1.0 * sw;
    ctx.stroke();
    ctx.restore();

    // 11. The Orb Plaza (+152, +60)
    const orbX = proj.wx(152);
    const orbY = proj.wz(60);
    ctx.beginPath();
    ctx.arc(orbX, orbY, Math.max(2.1, proj.wr(5.2)), 0, Math.PI * 2);
    ctx.fillStyle = '#e2e8f0';
    ctx.fill();
    ctx.strokeStyle = '#38bdf8';
    ctx.lineWidth = 0.8 * sw;
    ctx.stroke();

    // ==================== SOUTH RING LANDMARKS ====================

    // 12. 1098 Alta / Huff Complex (-108, +126; 76m x 54m twin white-roofed wings)
    ctx.fillStyle = 'rgba(203, 213, 225, 0.18)';
    ctx.fillRect(proj.wx(-146), proj.wz(99), proj.wr(76), proj.wrZ(54));
    ctx.fillStyle = '#e2e8f0';
    ctx.strokeStyle = '#60a5fa';
    ctx.lineWidth = 0.85 * sw;
    ctx.fillRect(proj.wx(-143), proj.wz(102), proj.wr(30), proj.wrZ(48));
    ctx.strokeRect(proj.wx(-143), proj.wz(102), proj.wr(30), proj.wrZ(48));
    ctx.fillRect(proj.wx(-103), proj.wz(102), proj.wr(30), proj.wrZ(48));
    ctx.strokeRect(proj.wx(-103), proj.wz(102), proj.wr(30), proj.wrZ(48));
    // Central garden walkway
    ctx.fillStyle = '#2f6e3d';
    ctx.fillRect(proj.wx(-113), proj.wz(104), proj.wr(10), proj.wrZ(44));

    // 13. Charleston Campus (+28, +134; 110m x 62m multi-wing courtyard campus)
    ctx.fillStyle = 'rgba(203, 213, 225, 0.18)';
    ctx.fillRect(proj.wx(-27), proj.wz(103), proj.wr(110), proj.wrZ(62));
    this.polyWorld(ctx, proj, [
      [-23, 107],
      [79, 107],
      [79, 161],
      [53, 161],
      [53, 127],
      [2, 127],
      [2, 161],
      [-23, 161],
    ]);
    ctx.fillStyle = '#0369a1';
    ctx.fill();
    ctx.strokeStyle = '#7dd3fc';
    ctx.lineWidth = 0.9 * sw;
    ctx.stroke();
    // Sunlit courtyard plaza inside Charleston Campus
    ctx.fillStyle = '#367542';
    ctx.fillRect(proj.wx(4), proj.wz(129), proj.wr(47), proj.wrZ(30));

    // ==================== EAST RING LANDMARKS (East of N Shoreline Blvd) ====================

    // 14. Google CL2 Crittenden (+236, -140)
    this.drawEastOfficeComplex(ctx, proj, 236, -140, '#0f766e', '#5eead4', true, detailed);
    // 15. Google 2015 / Stierlin Ct (+234, -22)
    this.drawEastOfficeComplex(ctx, proj, 234, -22, '#1d4ed8', '#93c5fd', false, detailed);
    // 16. Google 1395 Charleston / SB10 (+234, +122)
    this.drawEastOfficeComplex(ctx, proj, 234, 122, '#4338ca', '#a5b4fc', true, detailed);

    // ==================== OUTDOOR PARK DEFENSES, ART GARDENS & GYMS ====================

    // 16b-1. 3 Googleplex Outdoor Calisthenics Gyms (14.0m × 11.0m Google-blue athletic pads)
    const outdoorGyms: [number, number, number][] = [
      [32, 30, 0],
      [-220, -168, 0],
      [126, 126, Math.PI / 2],
    ];
    for (const [gx, gz, rotY] of outdoorGyms) {
      ctx.save();
      ctx.translate(proj.wx(gx), proj.wz(gz));
      ctx.rotate(-rotY);
      const gw = proj.wr(14.0);
      const gh = proj.wrZ(11.0);
      // Google-blue rubberized athletic turf pad
      ctx.fillStyle = '#2563eb';
      ctx.fillRect(-gw * 0.5, -gh * 0.5, gw, gh);
      // Crisp white athletic border
      ctx.strokeStyle = 'rgba(248, 250, 252, 0.9)';
      ctx.lineWidth = detailed ? 1.15 : 0.65;
      ctx.strokeRect(-gw * 0.5, -gh * 0.5, gw, gh);
      // Fitness lane center tick & opposing L-wall accents
      ctx.strokeStyle = 'rgba(248, 250, 252, 0.65)';
      ctx.lineWidth = detailed ? 0.9 : 0.5;
      ctx.beginPath();
      ctx.moveTo(0, -gh * 0.36);
      ctx.lineTo(0, gh * 0.36);
      if (detailed) {
        ctx.moveTo(-gw * 0.34, 0);
        ctx.lineTo(gw * 0.34, 0);
      }
      ctx.stroke();
      if (detailed) {
        // Subtle architectural concrete L-wall corner ticks (NW & SE)
        ctx.strokeStyle = '#fbbf24';
        ctx.lineWidth = 1.4;
        ctx.beginPath();
        ctx.moveTo(-gw * 0.44, -gh * 0.12);
        ctx.lineTo(-gw * 0.44, -gh * 0.44);
        ctx.lineTo(-gw * 0.06, -gh * 0.44);
        ctx.moveTo(gw * 0.44, gh * 0.12);
        ctx.lineTo(gw * 0.44, gh * 0.44);
        ctx.lineTo(gw * 0.06, gh * 0.44);
        ctx.stroke();
      }
      ctx.restore();
    }

    // 16b-2. 3 Google Sculpture & Art Gardens (16.0m × 14.0m warm limestone octagons + 4-color center marker)
    const artGardens: [number, number, number][] = [
      [30, -8, 0],
      [-62, -138, 0.25],
      [-226, 124, -0.2],
    ];
    for (const [ax, az, rotY] of artGardens) {
      ctx.save();
      ctx.translate(proj.wx(ax), proj.wz(az));
      ctx.rotate(-rotY);
      const hw = proj.wr(8.0);
      const hh = proj.wrZ(7.0);
      const cxCut = hw * 0.46;
      const czCut = hh * 0.46;
      // Warm travertine/limestone octagon plaza
      ctx.beginPath();
      ctx.moveTo(-cxCut, -hh);
      ctx.lineTo(cxCut, -hh);
      ctx.lineTo(hw, -czCut);
      ctx.lineTo(hw, czCut);
      ctx.lineTo(cxCut, hh);
      ctx.lineTo(-cxCut, hh);
      ctx.lineTo(-hw, czCut);
      ctx.lineTo(-hw, -czCut);
      ctx.closePath();
      ctx.fillStyle = '#e7e2d4';
      ctx.fill();
      ctx.strokeStyle = '#4ade80';
      ctx.lineWidth = detailed ? 1.25 : 0.7;
      ctx.stroke();

      // Subtle 4-color Google kinetic sculpture center marker
      const dotR = detailed ? 1.85 : 0.85;
      const dotOff = detailed ? 2.1 : 0.95;
      const gDots: [number, number, string][] = [
        [-dotOff, -dotOff, '#4285f4'],
        [dotOff, -dotOff, '#ea4335'],
        [-dotOff, dotOff, '#fbbc04'],
        [dotOff, dotOff, '#34a853'],
      ];
      for (const [dx, dy, col] of gDots) {
        ctx.beginPath();
        ctx.arc(dx, dy, dotR, 0, Math.PI * 2);
        ctx.fillStyle = col;
        ctx.fill();
      }
      ctx.restore();
    }

    // 16b-3. 6 Google Outdoor Collaboration Pergolas (9.5m × 6.5m warm cedar slatted rectangles)
    const pergolas: [number, number, number][] = [
      [-46, -86, 0],
      [28, -44, Math.PI],
      [-106, -130, 0.35],
      [-248, 92, -0.3],
      [228, -82, 0],
      [232, 42, Math.PI],
    ];
    for (const [px, pz, rotY] of pergolas) {
      ctx.save();
      ctx.translate(proj.wx(px), proj.wz(pz));
      ctx.rotate(-rotY);
      const pw = proj.wr(9.5);
      const ph = proj.wrZ(6.5);
      ctx.fillStyle = '#b45309';
      ctx.fillRect(-pw * 0.5, -ph * 0.5, pw, ph);
      if (detailed) {
        // Warm slatted cedar roof louvers
        ctx.strokeStyle = 'rgba(254, 243, 199, 0.55)';
        ctx.lineWidth = 0.75;
        const slatCount = 5;
        for (let s = 1; s < slatCount; s++) {
          const sx = -pw * 0.5 + (pw * s) / slatCount;
          ctx.beginPath();
          ctx.moveTo(sx, -ph * 0.44);
          ctx.lineTo(sx, ph * 0.44);
          ctx.stroke();
        }
      }
      ctx.strokeStyle = '#fde68a';
      ctx.lineWidth = detailed ? 0.95 : 0.55;
      ctx.strokeRect(-pw * 0.5, -ph * 0.5, pw, ph);
      ctx.restore();
    }

    // 17. Labels: Crisp Micro-Labels on Corner Minimap OR High-Res Road Names + Pill Labels on Full Map
    if (!detailed) {
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      const label = (txt: string, worldX: number, worldZ: number, color: string, size = 5.4): void => {
        const px = proj.wx(worldX);
        const py = proj.wz(worldZ);
        ctx.font = `800 ${size}px -apple-system, BlinkMacSystemFont, sans-serif`;
        ctx.fillStyle = 'rgba(6, 10, 20, 0.78)';
        ctx.fillText(txt, px + 0.55, py + 0.55);
        ctx.fillStyle = color;
        ctx.fillText(txt, px, py);
      };

      // North Ring
      label('FIELD', -220, -134, '#f0fdf4', 5.4);
      label('BAY PT', -62, -144, '#fef9c3', 5.2);
      label('AMP', 58, -148, '#0f172a', 5.6);
      label('LOT C', 124, -109, '#cbd5e1', 4.8);
      // West Ring
      label('2000', -225, -24, '#ffffff', 5.4);
      label('1950', -225, 28, '#ffffff', 5.4);
      // Core Quad & East Core
      label('B41', -112, -31, '#ffffff', 5.2);
      label('B42', -117, 24, '#ffffff', 5.2);
      label('B40', -51, -24, '#ffffff', 5.3);
      label('B43', -58, 35, '#ffffff', 5.3);
      label('PARK', 28, -10, '#dcfce7', 5.2);
      label('CANOPY', 113, 4, '#0f172a', 5.6);
      // South Ring
      label('ALTA', -108, 126, '#0f172a', 5.3);
      label('CHARLESTON', 28, 117, '#ffffff', 5.0);
      // East Ring
      label('CL2', 236, -140, '#ffffff', 5.6);
      label('2015', 234, -22, '#ffffff', 5.6);
      label('1395', 234, 122, '#ffffff', 5.6);
    } else {
      // Crisp Mountain View Road Artery Labels
      ctx.save();
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.font = '800 8.5px ui-monospace, SFMono-Regular, Menlo, monospace';
      for (const road of FULL_MAP_ROAD_LABELS) {
        ctx.save();
        ctx.translate(proj.wx(road.x), proj.wz(road.z));
        ctx.rotate((road.angleDeg * Math.PI) / 180);
        ctx.lineWidth = 3;
        ctx.strokeStyle = 'rgba(7, 12, 24, 0.85)';
        ctx.strokeText(road.label, 0, 0);
        ctx.fillStyle = 'rgba(203, 213, 225, 0.9)';
        ctx.fillText(road.label, 0, 0);
        ctx.restore();
      }
      ctx.restore();

      // North Compass Badge (top-left)
      ctx.save();
      drawRoundedRectPath(ctx, 12, 12, 28, 28, 8);
      ctx.fillStyle = 'rgba(7, 12, 24, 0.84)';
      ctx.fill();
      ctx.strokeStyle = 'rgba(96, 165, 250, 0.55)';
      ctx.lineWidth = 1.2;
      ctx.stroke();
      ctx.fillStyle = '#60a5fa';
      ctx.font = '900 13px -apple-system, BlinkMacSystemFont, sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText('N', 26, 26.5);
      ctx.restore();

      // 100m Scale Bar (bottom-left)
      ctx.save();
      const barPx = proj.wr(100);
      const bx = 14;
      const by = proj.cssH - 16;
      drawRoundedRectPath(ctx, bx - 6, by - 16, barPx + 12, 24, 6);
      ctx.fillStyle = 'rgba(7, 12, 24, 0.78)';
      ctx.fill();
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.16)';
      ctx.lineWidth = 1;
      ctx.stroke();

      ctx.strokeStyle = '#e2e8f0';
      ctx.lineWidth = 1.8;
      ctx.beginPath();
      ctx.moveTo(bx, by - 4);
      ctx.lineTo(bx, by);
      ctx.lineTo(bx + barPx, by);
      ctx.lineTo(bx + barPx, by - 4);
      ctx.stroke();

      ctx.fillStyle = '#cbd5e1';
      ctx.font = '800 9px ui-monospace, SFMono-Regular, Menlo, monospace';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText('100m', bx + barPx * 0.5, by - 8);
      ctx.restore();
    }

    ctx.restore();
  }

  /**
   * Draws the 22 crisp named landmark pills on the Full Tactical Map dynamically
   * after Loot Chests & Supply Drops so chest icons never overlap landmark names,
   * and before Enemies, Waypoint, and the Player Marker so active tactical icons sit on top.
   */
  private drawFullMapLandmarkPills(ctx: CanvasRenderingContext2D, proj: MapProjection): void {
    ctx.save();
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.font = '800 9.5px -apple-system, BlinkMacSystemFont, "Inter", sans-serif';
    for (const lm of FULL_MAP_LANDMARK_PILLS) {
      const cx = proj.wx(lm.x);
      const cy = proj.wz(lm.z);
      const textW = ctx.measureText(lm.label).width;
      const dotSpace = 8;
      const padX = 7;
      const pillW = textW + padX * 2 + dotSpace;
      const pillH = 16;
      const x0 = Math.max(6, Math.min(proj.cssW - pillW - 6, cx - pillW * 0.5));
      const y0 = Math.max(6, Math.min(proj.cssH - pillH - 6, cy - pillH * 0.5));

      drawRoundedRectPath(ctx, x0, y0, pillW, pillH, 8);
      ctx.fillStyle = 'rgba(7, 12, 24, 0.86)';
      ctx.fill();
      ctx.strokeStyle = lm.highTier ? lm.color : 'rgba(226, 232, 240, 0.34)';
      ctx.lineWidth = lm.highTier ? 1.15 : 0.85;
      ctx.stroke();

      // Landmark accent dot
      ctx.beginPath();
      ctx.arc(x0 + padX + 2.5, y0 + pillH * 0.5, 2.4, 0, Math.PI * 2);
      ctx.fillStyle = lm.color;
      ctx.fill();

      // Crisp pill label text
      ctx.fillStyle = lm.highTier ? '#f8fafc' : '#e2e8f0';
      ctx.fillText(lm.label, x0 + padX + dotSpace + textW * 0.5, y0 + pillH * 0.5 + 0.4);
    }
    ctx.restore();
  }

  /**
   * Renders all live dynamic tactical layers onto either the corner minimap or full tactical map:
   * - Active purple storm curtain + glowing perimeter border
   * - White dashed next safe zone preview ring
   * - Unopened Tier 1-3 Loot Chests & Rare/Epic popped loot pips
   * - Golden Supply Drop beacons
   * - Nearby / Chat-revealed enemy markers
   * - Pulsing cyan/gold Waypoint Pin + dashed route line (+ distance pill on full map)
   * - Player heading vision cone & directional arrow
   */
  private renderDynamicOverlays(
    ctx: CanvasRenderingContext2D,
    proj: MapProjection,
    state: MinimapState,
    timeSec: number,
    detailed: boolean
  ): void {
    const pulse = (Math.sin(timeSec * 5.2) + 1) * 0.5;

    // 1. Active Purple Storm Curtain (everything outside active circle)
    const stormCX = proj.wx(state.stormCenterX);
    const stormCY = proj.wz(state.stormCenterZ);
    const stormR = Math.max(0, proj.wr(state.stormRadius));

    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 0, proj.cssW, proj.cssH);
    if (stormR > 0.5) {
      ctx.arc(stormCX, stormCY, stormR, 0, Math.PI * 2, true);
    }
    ctx.fillStyle = 'rgba(139, 34, 212, 0.34)';
    ctx.fill('evenodd');
    ctx.restore();

    if (stormR > 0.5) {
      ctx.save();
      ctx.beginPath();
      ctx.arc(stormCX, stormCY, stormR, 0, Math.PI * 2);
      ctx.strokeStyle = '#c084fc';
      ctx.lineWidth = detailed ? 2.6 : 2;
      ctx.shadowColor = '#a855f7';
      ctx.shadowBlur = detailed ? 10 : 6;
      ctx.stroke();
      ctx.restore();
    }

    // 2. White Dashed Next Safe Zone Preview Ring
    const nextR = proj.wr(state.nextStormRadius);
    if (nextR > 0.5) {
      const nextCX = proj.wx(state.nextStormCenterX);
      const nextCY = proj.wz(state.nextStormCenterZ);
      ctx.save();
      ctx.beginPath();
      ctx.arc(nextCX, nextCY, nextR, 0, Math.PI * 2);
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.9)';
      ctx.lineWidth = detailed ? 2.0 : 1.35;
      ctx.setLineDash(detailed ? [8, 6] : [4, 3.5]);
      ctx.stroke();
      ctx.restore();
    }

    // 3. Unopened Loot Chests (Tier 1 Amber / Tier 2 Blue / Tier 3 Purple+Gold)
    if (state.chests && state.chests.length > 0) {
      for (const ch of state.chests) {
        const cx = proj.wx(ch.x);
        const cy = proj.wz(ch.z);
        if (ch.tier === 3) {
          // Tier 3 Epic Vault Chest: crisp royal-purple diamond with gold border
          const r = detailed ? 5.2 : 2.6;
          ctx.beginPath();
          ctx.moveTo(cx, cy - r);
          ctx.lineTo(cx + r, cy);
          ctx.lineTo(cx, cy + r);
          ctx.lineTo(cx - r, cy);
          ctx.closePath();
          ctx.fillStyle = '#a855f7';
          ctx.fill();
          ctx.strokeStyle = '#fde047';
          ctx.lineWidth = detailed ? 1.45 : 0.85;
          ctx.stroke();
        } else if (ch.tier === 2) {
          // Tier 2 Rare Tech Chest: crisp cobalt square with bright rim
          const half = detailed ? 3.5 : 1.65;
          ctx.fillStyle = '#3b82f6';
          ctx.fillRect(cx - half, cy - half, half * 2, half * 2);
          ctx.strokeStyle = '#dbeafe';
          ctx.lineWidth = detailed ? 1.0 : 0.6;
          ctx.strokeRect(cx - half, cy - half, half * 2, half * 2);
        } else {
          // Tier 1 Common Supply Chest: crisp bronze/amber square
          const half = detailed ? 2.8 : 1.3;
          ctx.fillStyle = '#f59e0b';
          ctx.fillRect(cx - half, cy - half, half * 2, half * 2);
          ctx.strokeStyle = 'rgba(15, 23, 42, 0.88)';
          ctx.lineWidth = detailed ? 0.95 : 0.55;
          ctx.strokeRect(cx - half, cy - half, half * 2, half * 2);
        }
      }
    }

    // 3b. Rare & Epic Popped Ground Loot Pips
    for (const pip of state.loot) {
      if (pip.rarity === 'common') continue;
      const lx = proj.wx(pip.x);
      const ly = proj.wz(pip.z);
      const sz = detailed ? (pip.rarity === 'epic' ? 3.8 : 3.0) : pip.rarity === 'epic' ? 2.1 : 1.65;
      ctx.fillStyle = pip.rarity === 'epic' ? '#d8b4fe' : '#60a5fa';
      ctx.beginPath();
      ctx.moveTo(lx, ly - sz);
      ctx.lineTo(lx + sz, ly);
      ctx.lineTo(lx, ly + sz);
      ctx.lineTo(lx - sz, ly);
      ctx.closePath();
      ctx.fill();
    }

    // 3c. Rideable GBikes (Google Green circular pip + crisp white ring; handlebar/wheel glyph on Full Map)
    if (state.gbikes && state.gbikes.length > 0) {
      for (const bike of state.gbikes) {
        if (bike.occupied) continue;
        const bx = proj.wx(bike.x);
        const by = proj.wz(bike.z);
        const r = detailed ? 4.2 : 2.6;

        ctx.save();
        if (detailed) {
          ctx.beginPath();
          ctx.arc(bx, by, r + 1.4, 0, Math.PI * 2);
          ctx.fillStyle = 'rgba(15, 23, 42, 0.72)';
          ctx.fill();
        }

        ctx.beginPath();
        ctx.arc(bx, by, r, 0, Math.PI * 2);
        ctx.fillStyle = '#34A853';
        ctx.fill();
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = detailed ? 1.35 : 0.9;
        ctx.stroke();

        if (detailed) {
          ctx.strokeStyle = '#ffffff';
          ctx.lineWidth = 0.85;
          ctx.lineCap = 'round';
          ctx.lineJoin = 'round';
          // Tiny twin wheels
          ctx.beginPath();
          ctx.arc(bx - 1.55, by + 0.95, 0.9, 0, Math.PI * 2);
          ctx.stroke();
          ctx.beginPath();
          ctx.arc(bx + 1.55, by + 0.95, 0.9, 0, Math.PI * 2);
          ctx.stroke();
          // Tiny cruiser handlebar / frame glyph
          ctx.beginPath();
          ctx.moveTo(bx - 1.35, by + 0.7);
          ctx.lineTo(bx - 0.1, by - 1.25);
          ctx.lineTo(bx + 1.35, by - 1.25);
          ctx.lineTo(bx + 1.45, by + 0.7);
          ctx.stroke();
        }
        ctx.restore();
      }
    }

    // 3d. TechStop Weapon Upgrade Centers (Google Blue diamond badge + white border + crisp upgrade bolt)
    if (state.techStops && state.techStops.length > 0) {
      for (const stop of state.techStops) {
        const tx = proj.wx(stop.x);
        const ty = proj.wz(stop.z);
        const r = detailed ? 6.5 : 4.2;

        ctx.save();
        // Subtle dark contrast halo so white border pops over light campus roofs
        ctx.beginPath();
        ctx.moveTo(tx, ty - r - 1.3);
        ctx.lineTo(tx + r + 1.3, ty);
        ctx.lineTo(tx, ty + r + 1.3);
        ctx.lineTo(tx - r - 1.3, ty);
        ctx.closePath();
        ctx.fillStyle = 'rgba(15, 23, 42, 0.74)';
        ctx.fill();

        // Crisp Google Blue diamond badge with 1.4px white border
        ctx.beginPath();
        ctx.moveTo(tx, ty - r);
        ctx.lineTo(tx + r, ty);
        ctx.lineTo(tx, ty + r);
        ctx.lineTo(tx - r, ty);
        ctx.closePath();
        ctx.fillStyle = '#1A73E8';
        ctx.fill();
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = detailed ? 1.4 : 1.1;
        ctx.stroke();

        // Crisp vector lightning / upgrade bolt inside diamond
        const s = r * 0.56;
        ctx.beginPath();
        ctx.moveTo(tx + 0.18 * s, ty - 1.0 * s);
        ctx.lineTo(tx - 0.62 * s, ty + 0.08 * s);
        ctx.lineTo(tx - 0.02 * s, ty + 0.08 * s);
        ctx.lineTo(tx - 0.22 * s, ty + 1.0 * s);
        ctx.lineTo(tx + 0.62 * s, ty - 0.08 * s);
        ctx.lineTo(tx + 0.02 * s, ty - 0.08 * s);
        ctx.closePath();
        ctx.fillStyle = '#FEF08A';
        ctx.fill();
        ctx.restore();
      }
    }

    // 4. Golden Supply Drop Beacons / Triangles
    for (const drop of state.supplyDrops) {
      const dx = proj.wx(drop.x);
      const dy = proj.wz(drop.z);
      if (drop.opened) {
        ctx.fillStyle = 'rgba(148, 163, 184, 0.5)';
        ctx.beginPath();
        ctx.arc(dx, dy, detailed ? 3.6 : 2.0, 0, Math.PI * 2);
        ctx.fill();
        continue;
      }

      // Pulsing outer gold/cyan beacon ring
      ctx.save();
      ctx.beginPath();
      ctx.arc(dx, dy, (detailed ? 8.5 : 4.2) + pulse * (detailed ? 8.5 : 4.2), 0, Math.PI * 2);
      ctx.strokeStyle = drop.landed
        ? `rgba(250, 204, 21, ${0.78 - pulse * 0.55})`
        : `rgba(56, 189, 248, ${0.88 - pulse * 0.6})`;
      ctx.lineWidth = detailed ? 2.0 : 1.25;
      ctx.stroke();

      // Solid golden triangle icon
      const topOff = detailed ? 7.8 : 4.4;
      const sideOff = detailed ? 7.0 : 4.0;
      const botOff = detailed ? 5.6 : 3.1;
      ctx.beginPath();
      ctx.moveTo(dx, dy - topOff);
      ctx.lineTo(dx + sideOff, dy + botOff);
      ctx.lineTo(dx - sideOff, dy + botOff);
      ctx.closePath();
      ctx.fillStyle = '#facc15';
      ctx.fill();
      ctx.strokeStyle = '#0f172a';
      ctx.lineWidth = detailed ? 1.6 : 1.0;
      ctx.stroke();

      if (detailed) {
        ctx.font = '900 8.5px ui-monospace, SFMono-Regular, Menlo, monospace';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        ctx.lineWidth = 2.6;
        ctx.strokeStyle = 'rgba(7, 12, 24, 0.9)';
        const tag = drop.landed ? 'DROP' : 'INCOMING';
        ctx.strokeText(tag, dx, dy + botOff + 3);
        ctx.fillStyle = '#fde047';
        ctx.fillText(tag, dx, dy + botOff + 3);
      }
      ctx.restore();
    }

    // 4b. Full Tactical Map Named Landmark Pills (drawn above chests/drops, below enemies/waypoint/player)
    if (detailed) {
      this.drawFullMapLandmarkPills(ctx, proj);
    }

    // 5. Nearby / Chat-Revealed Enemies (drawn beneath teammates & local player)
    for (const enemy of state.enemies) {
      const ext = enemy as MinimapState['enemies'][number] & {
        isTeammate?: boolean;
        name?: string;
        teamColor?: string;
      };
      if (ext.isTeammate) continue;

      const ex = proj.wx(enemy.x);
      const ey = proj.wz(enemy.z);
      const isRevealed = Boolean(enemy.revealed || state.revealedAll);

      if (isRevealed) {
        ctx.beginPath();
        ctx.arc(ex, ey, (detailed ? 6.5 : 3.5) + pulse * (detailed ? 5.5 : 3.1), 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(52, 211, 153, ${0.85 - pulse * 0.55})`;
        ctx.lineWidth = detailed ? 1.8 : 1.15;
        ctx.stroke();
      }

      ctx.beginPath();
      ctx.arc(ex, ey, detailed ? (isRevealed ? 4.8 : 4.0) : isRevealed ? 2.7 : 2.2, 0, Math.PI * 2);
      ctx.fillStyle = isRevealed ? '#fb7185' : '#ef4444';
      ctx.fill();
      ctx.strokeStyle = '#0f172a';
      ctx.lineWidth = detailed ? 1.4 : 0.85;
      ctx.stroke();
    }

    // 5a. Always-Visible Teammate Markers + Full Tactical Map Nameplates (draw human squadmates on top of AI bots)
    const teammates = state.enemies
      .filter((entity) => Boolean(entity.isTeammate))
      .sort((a, b) => (a.isBot === b.isBot ? 0 : a.isBot ? -1 : 1));

    for (const mate of teammates) {
      const tx = proj.wx(mate.x);
      const ty = proj.wz(mate.z);
      const teamCol = mate.teamColor || mate.color || '#1A73E8';
      const dotR = detailed ? 5.4 : 3.2;

      ctx.save();
      // Subtle outer dark halo so teammates pop over blue roofs & green lawns
      ctx.beginPath();
      ctx.arc(tx, ty, dotR + (detailed ? 2.6 : 1.8), 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(15, 23, 42, 0.78)';
      ctx.fill();

      // Crisp team-colored circular marker with bold pure white border
      ctx.beginPath();
      ctx.arc(tx, ty, dotR, 0, Math.PI * 2);
      ctx.fillStyle = teamCol;
      ctx.fill();
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = detailed ? 2.0 : 1.8;
      ctx.stroke();

      // Compact crisp nameplate right above dot on Full Tactical Map (truncated to 10 chars)
      if (detailed && mate.name) {
        const trimmed = mate.name.trim();
        if (trimmed.length > 0) {
          const label = trimmed.length > 10 ? trimmed.slice(0, 10) : trimmed;
          ctx.font = '700 9.5px -apple-system, BlinkMacSystemFont, "Inter", sans-serif';
          const tw = ctx.measureText(label).width;
          const pw = Math.ceil(tw + 10);
          const ph = 15;
          const lx = Math.max(6, Math.min(proj.cssW - pw - 6, tx - pw * 0.5));
          const rawLy = ty < 26 ? ty + dotR + 5 : ty - dotR - 4 - ph;
          const ly = Math.max(4, Math.min(proj.cssH - ph - 4, rawLy));

          drawRoundedRectPath(ctx, lx, ly, pw, ph, 7.5);
          ctx.fillStyle = 'rgba(15, 23, 42, 0.88)';
          ctx.fill();
          ctx.strokeStyle = teamCol;
          ctx.lineWidth = 1.25;
          ctx.stroke();

          ctx.fillStyle = '#ffffff';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillText(label, lx + pw * 0.5, ly + ph * 0.5 + 0.5);
        }
      }
      ctx.restore();
    }

    const px = proj.wx(state.playerX);
    const py = proj.wz(state.playerZ);

    // 5b. Active Click-to-Ping Waypoint Pin + Tactical Dashed Route Line + Distance Tag
    if (state.waypoint) {
      const wpx = proj.wx(state.waypoint.x);
      const wpy = proj.wz(state.waypoint.z);
      const distMeters = Math.round(
        Math.hypot(state.waypoint.x - state.playerX, state.waypoint.z - state.playerZ)
      );

      // Dashed cyan/gold route line from player to waypoint
      ctx.save();
      ctx.beginPath();
      ctx.moveTo(px, py);
      ctx.lineTo(wpx, wpy);
      ctx.strokeStyle = detailed ? 'rgba(34, 211, 238, 0.82)' : 'rgba(34, 211, 238, 0.7)';
      ctx.lineWidth = detailed ? 2.0 : 1.15;
      ctx.setLineDash(detailed ? [7, 5] : [3, 3]);
      ctx.stroke();
      ctx.restore();

      // Pulsing outer cyan/gold beacon ring
      ctx.save();
      ctx.beginPath();
      ctx.arc(
        wpx,
        wpy,
        (detailed ? 8.5 : 4.2) + pulse * (detailed ? 10.5 : 4.5),
        0,
        Math.PI * 2
      );
      ctx.strokeStyle = `rgba(34, 211, 238, ${0.9 - pulse * 0.65})`;
      ctx.lineWidth = detailed ? 2.2 : 1.3;
      ctx.stroke();

      // Inner subtle gold ring
      if (detailed) {
        ctx.beginPath();
        ctx.arc(wpx, wpy, 10.5 + (1 - pulse) * 4.5, 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(250, 204, 21, ${0.55 * pulse + 0.15})`;
        ctx.lineWidth = 1.4;
        ctx.stroke();
      }

      // Crisp cyan diamond waypoint pin with gold core
      const dr = detailed ? 7.8 : 4.0;
      ctx.beginPath();
      ctx.moveTo(wpx, wpy - dr);
      ctx.lineTo(wpx + dr, wpy);
      ctx.lineTo(wpx, wpy + dr);
      ctx.lineTo(wpx - dr, wpy);
      ctx.closePath();
      ctx.fillStyle = '#22d3ee';
      ctx.fill();
      ctx.strokeStyle = '#0f172a';
      ctx.lineWidth = detailed ? 1.8 : 1.05;
      ctx.stroke();

      ctx.beginPath();
      ctx.arc(wpx, wpy, detailed ? 2.6 : 1.35, 0, Math.PI * 2);
      ctx.fillStyle = '#fde047';
      ctx.fill();

      // Distance tag pill beside waypoint pin on full tactical map
      if (detailed) {
        const tag = `${distMeters}m`;
        ctx.font = '900 11px ui-monospace, SFMono-Regular, Menlo, monospace';
        const tw = ctx.measureText(tag).width;
        const pw = tw + 14;
        const ph = 20;
        let tx = wpx + 13;
        let ty = wpy - ph * 0.5;
        if (tx + pw > proj.cssW - 8) tx = wpx - 13 - pw;
        if (ty < 8) ty = 8;
        if (ty + ph > proj.cssH - 8) ty = proj.cssH - ph - 8;

        drawRoundedRectPath(ctx, tx, ty, pw, ph, 10);
        ctx.fillStyle = 'rgba(6, 15, 30, 0.92)';
        ctx.fill();
        ctx.strokeStyle = '#22d3ee';
        ctx.lineWidth = 1.35;
        ctx.stroke();

        ctx.fillStyle = '#fde047';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(tag, tx + pw * 0.5, ty + ph * 0.5 + 0.5);
      }
      ctx.restore();
    }

    // 6. High-Contrast Prominent Player Marker (Vision Cone, Pulsing Rings, Contrast Halo, Chevron & "YOU" Pill)
    // Standard Three.js yaw convention:
    // forward = (-sin(yaw), -cos(yaw)) in (X, Z) => on canvas (+X right, +Z down),
    // atan2(fwdZ, fwdX) = atan2(-cos(yaw), -sin(yaw)) = -PI/2 - yaw.
    const fwdCanvasAngle = -Math.PI / 2 - state.playerYaw;
    const coneHalf = 0.46;
    const coneLen = detailed ? 56 : 24;

    // 6a. Warm bright gold-white Vision Cone with crisp fading edge rays (high-contrast over lawns, roads & blue roofs)
    ctx.save();
    const coneGrad = ctx.createRadialGradient(px, py, detailed ? 3 : 1.5, px, py, coneLen);
    coneGrad.addColorStop(0, 'rgba(255, 241, 168, 0.58)');
    coneGrad.addColorStop(0.55, 'rgba(251, 188, 4, 0.14)');
    coneGrad.addColorStop(1, 'rgba(251, 188, 4, 0)');
    ctx.beginPath();
    ctx.moveTo(px, py);
    ctx.arc(px, py, coneLen, fwdCanvasAngle - coneHalf, fwdCanvasAngle + coneHalf);
    ctx.closePath();
    ctx.fillStyle = coneGrad;
    ctx.fill();

    const edgeGrad = ctx.createRadialGradient(px, py, detailed ? 4 : 2, px, py, coneLen);
    edgeGrad.addColorStop(0, 'rgba(255, 248, 204, 0.65)');
    edgeGrad.addColorStop(0.65, 'rgba(251, 188, 4, 0.28)');
    edgeGrad.addColorStop(1, 'rgba(251, 188, 4, 0)');
    ctx.strokeStyle = edgeGrad;
    ctx.lineWidth = detailed ? 1.3 : 0.85;
    ctx.beginPath();
    ctx.moveTo(px, py);
    ctx.lineTo(
      px + Math.cos(fwdCanvasAngle - coneHalf) * coneLen,
      py + Math.sin(fwdCanvasAngle - coneHalf) * coneLen
    );
    ctx.moveTo(px, py);
    ctx.lineTo(
      px + Math.cos(fwdCanvasAngle + coneHalf) * coneLen,
      py + Math.sin(fwdCanvasAngle + coneHalf) * coneLen
    );
    ctx.stroke();
    ctx.restore();

    // 6b. Animated Double Pulsing Radar Locator Rings (Google Yellow + staggered white beacon on full map)
    const radarPulse1 = (((timeSec * 0.9) % 1) + 1) % 1;
    const minRingR = detailed ? 11 : 5;
    const maxRingR = detailed ? 30 : 14;
    const ring1R = minRingR + radarPulse1 * (maxRingR - minRingR);
    const ring1Alpha = 0.95 * (1 - radarPulse1);

    ctx.save();
    ctx.beginPath();
    ctx.arc(px, py, ring1R, 0, Math.PI * 2);
    ctx.strokeStyle = `rgba(251, 188, 4, ${ring1Alpha.toFixed(3)})`;
    ctx.lineWidth = detailed ? 2.6 : 1.5;
    ctx.stroke();

    if (detailed) {
      const radarPulse2 = (radarPulse1 + 0.5) % 1;
      const ring2R = minRingR + radarPulse2 * (maxRingR - minRingR);
      const ring2Alpha = 0.72 * (1 - radarPulse2);
      ctx.beginPath();
      ctx.arc(px, py, ring2R, 0, Math.PI * 2);
      ctx.strokeStyle = `rgba(255, 255, 255, ${ring2Alpha.toFixed(3)})`;
      ctx.lineWidth = 1.8;
      ctx.stroke();
    }
    ctx.restore();

    // 6c. Solid Dark Contrast Disk Halo + Crisp Google Yellow Border Ring right behind the player chevron
    ctx.save();
    const haloR = detailed ? 11.5 : 5.8;
    ctx.beginPath();
    ctx.arc(px, py, haloR, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(15, 23, 42, 0.85)';
    ctx.shadowColor = 'rgba(251, 188, 4, 0.52)';
    ctx.shadowBlur = detailed ? 10 : 5;
    ctx.fill();
    ctx.shadowBlur = 0;
    ctx.strokeStyle = '#FBBC04';
    ctx.lineWidth = detailed ? 2.2 : 1.3;
    ctx.stroke();
    ctx.restore();

    // 6d. Bold High-Contrast Directional Player Chevron
    ctx.save();
    ctx.translate(px, py);
    ctx.rotate(fwdCanvasAngle + Math.PI / 2);
    const arrowScale = detailed ? 2.35 : 1.35;
    ctx.beginPath();
    ctx.moveTo(0, -4.8 * arrowScale);
    ctx.lineTo(3.5 * arrowScale, 3.7 * arrowScale);
    ctx.lineTo(0, 1.8 * arrowScale);
    ctx.lineTo(-3.5 * arrowScale, 3.7 * arrowScale);
    ctx.closePath();
    ctx.fillStyle = '#ffffff';
    ctx.fill();
    ctx.lineJoin = 'round';
    ctx.strokeStyle = '#0f172a';
    ctx.lineWidth = detailed ? 2.2 : 1.3;
    ctx.stroke();
    ctx.restore();

    // 6e. Floating "YOU" Pill Badge (drawn LAST on Full Tactical Map so nothing ever covers it)
    if (detailed) {
      ctx.save();
      ctx.font = '900 10.5px -apple-system, BlinkMacSystemFont, "Inter", sans-serif';
      const youLabel = 'YOU';
      const tw = ctx.measureText(youLabel).width;
      const pw = Math.ceil(tw + 14);
      const ph = 17;
      const pillX = Math.max(8, Math.min(proj.cssW - pw - 8, px - pw * 0.5));
      const rawPillY = py < 36 ? py + 17 : py - 17 - ph;
      const pillY = Math.max(6, Math.min(proj.cssH - ph - 6, rawPillY));

      drawRoundedRectPath(ctx, pillX, pillY, pw, ph, 8.5);
      ctx.shadowColor = 'rgba(15, 23, 42, 0.72)';
      ctx.shadowBlur = 6;
      ctx.shadowOffsetY = 2;
      ctx.fillStyle = '#FBBC04';
      ctx.fill();
      ctx.shadowColor = 'transparent';
      ctx.shadowBlur = 0;
      ctx.shadowOffsetY = 0;
      ctx.strokeStyle = '#0f172a';
      ctx.lineWidth = 1.6;
      ctx.stroke();

      ctx.fillStyle = '#0f172a';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(youLabel, pillX + pw * 0.5, pillY + ph * 0.5 + 0.5);
      ctx.restore();
    }
  }

  /**
   * Renders the corner 2D tactical minimap frame.
   */
  public render(state: MinimapState, timeSec = performance.now() * 0.001): void {
    const ctx = this.ctx;
    ctx.save();
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);

    // Draw cached expanded 3x Mountain View Googleplex campus layer
    ctx.drawImage(this.staticLayer, 0, 0, this.cssW, this.cssH);

    // Draw dynamic tactical layers (storm, chests, supply drops, enemies, waypoint, player)
    this.renderDynamicOverlays(ctx, this.proj, state, timeSec, false);

    ctx.restore();
  }

  /**
   * Renders the High-Res 900x570 (dpr-aware) Full Tactical Campus Map (`[M]`)
   * sharing the exact 600m x 380m Mountain View vector geometry, roads, 22 landmark pills,
   * live storm, chests, supply drops, enemies, player vision cone, and click-to-ping Waypoint!
   */
  public renderFullMap(
    canvas: HTMLCanvasElement,
    state: MinimapState,
    timeSec = performance.now() * 0.001
  ): void {
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const targetDpr = Math.min(window.devicePixelRatio || 1, 2);
    if (!this.fullStaticLayer || this.fullCanvasRef !== canvas || this.fullDpr !== targetDpr) {
      this.fullCanvasRef = canvas;
      this.fullDpr = targetDpr;
      this.fullCssW = 900;
      this.fullCssH = 570;
      canvas.width = Math.round(this.fullCssW * this.fullDpr);
      canvas.height = Math.round(this.fullCssH * this.fullDpr);
      this.fullProj = createProjection(this.fullCssW, this.fullCssH);

      this.fullStaticLayer = document.createElement('canvas');
      this.fullStaticLayer.width = canvas.width;
      this.fullStaticLayer.height = canvas.height;
      this.bakeStaticGoogleplexMap(this.fullStaticLayer, this.fullProj, this.fullDpr, true);
    }

    ctx.save();
    ctx.setTransform(this.fullDpr, 0, 0, this.fullDpr, 0, 0);
    ctx.drawImage(this.fullStaticLayer, 0, 0, this.fullCssW, this.fullCssH);
    this.renderDynamicOverlays(ctx, this.fullProj, state, timeSec, true);
    ctx.restore();
  }

  /**
   * Renders the top-center Compass Bearing Strip (N/NE/E/SE/S/SW/W/NW + Supply Drop + Waypoint markers).
   * `headingRad`: Three.js player yaw where 0 faces North (-Z), turning right decreases yaw (so compass bearing = -headingRad).
   */
  public renderCompass(
    headingRad: number,
    supplyDrops: SupplyDropBearing[] = [],
    waypoint?: CompassWaypointMarker | null
  ): void {
    const ctx = this.compassCtx;
    if (!ctx) return;

    // Bearing in degrees clockwise from North (0=N, 90=E, 180=S, 270=W)
    const bearingDeg = wrapDeg((-headingRad * 180) / Math.PI);

    // Lightweight signature check to skip identical compass canvas draws when stationary
    const degKey = Math.round(bearingDeg * 5);
    const dropKey = supplyDrops
      .filter((d) => !d.opened)
      .map((d) => `${Math.round(d.angleRad * 200)}:${Math.round(d.dist)}`)
      .join(',');
    const wpKey = waypoint ? `${Math.round(waypoint.bearingRad * 200)}:${Math.round(waypoint.dist)}` : '';
    const sig = `${degKey}|${dropKey}|${wpKey}`;
    if (sig === this.lastCompassSig) return;
    this.lastCompassSig = sig;

    if (this.compassDegEl) {
      const padded = String(Math.round(bearingDeg) % 360).padStart(3, '0');
      const nextText = `${padded}° ${degToCardinal(bearingDeg)}`;
      if (nextText !== this.lastCompassText) {
        this.lastCompassText = nextText;
        this.compassDegEl.textContent = nextText;
      }
    }

    ctx.save();
    ctx.setTransform(this.compassDpr, 0, 0, this.compassDpr, 0, 0);
    ctx.clearRect(0, 0, this.compassW, this.compassH);

    const cx = this.compassW * 0.5;
    const pxPerDeg = 2.4; // ~140° visible strip
    const halfSpanDeg = Math.ceil(cx / pxPerDeg) + 10;

    // Draw tick marks every 5°
    const startDeg = Math.floor((bearingDeg - halfSpanDeg) / 5) * 5;
    const endDeg = Math.ceil((bearingDeg + halfSpanDeg) / 5) * 5;

    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';

    for (let d = startDeg; d <= endDeg; d += 5) {
      const x = cx + (d - bearingDeg) * pxPerDeg;
      if (x < 6 || x > this.compassW - 6) continue;

      const norm = wrapDeg(d);
      const cardinal = CARDINALS.find((c) => c.deg === norm);

      // Edge fade alpha
      const edgeFade = Math.min(1, Math.min(x, this.compassW - x) / 36);

      if (cardinal) {
        ctx.fillStyle =
          cardinal.label === 'N'
            ? `rgba(96, 165, 250, ${edgeFade})`
            : cardinal.major
              ? `rgba(248, 250, 252, ${edgeFade * 0.95})`
              : `rgba(148, 163, 184, ${edgeFade * 0.85})`;
        ctx.font = `${cardinal.major ? '900 11px' : '800 9.5px'} -apple-system, BlinkMacSystemFont, sans-serif`;
        ctx.fillText(cardinal.label, x, 17);

        ctx.strokeStyle = `rgba(255, 255, 255, ${edgeFade * 0.45})`;
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        ctx.moveTo(x, 3);
        ctx.lineTo(x, 8);
        ctx.stroke();
      } else if (norm % 15 === 0) {
        ctx.strokeStyle = `rgba(148, 163, 184, ${edgeFade * 0.55})`;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(x, 4);
        ctx.lineTo(x, 10);
        ctx.stroke();
      } else {
        ctx.strokeStyle = `rgba(148, 163, 184, ${edgeFade * 0.28})`;
        ctx.lineWidth = 0.8;
        ctx.beginPath();
        ctx.moveTo(x, 5);
        ctx.lineTo(x, 8);
        ctx.stroke();
      }
    }

    // Golden Supply Drop markers along compass strip
    for (const drop of supplyDrops) {
      if (drop.opened) continue;
      // drop.angleRad is relative angle from player forward in radians (+right, -left)
      let relDeg = (drop.angleRad * 180) / Math.PI;
      while (relDeg > 180) relDeg -= 360;
      while (relDeg < -180) relDeg += 360;

      const rawX = cx + relDeg * pxPerDeg;
      const clampedX = Math.max(14, Math.min(this.compassW - 58, rawX));

      ctx.save();
      ctx.fillStyle = '#facc15';
      ctx.strokeStyle = '#0f172a';
      ctx.lineWidth = 1.2;
      ctx.beginPath();
      ctx.moveTo(clampedX, 7);
      ctx.lineTo(clampedX + 5, 16);
      ctx.lineTo(clampedX - 5, 16);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();

      ctx.fillStyle = '#fef08a';
      ctx.font = '800 8px ui-monospace, Menlo, monospace';
      ctx.fillText(`${Math.round(drop.dist)}m`, clampedX, 24);
      ctx.restore();
    }

    // Active Cyan/Gold Diamond Waypoint Marker along compass strip
    if (waypoint) {
      let relDeg = (waypoint.bearingRad * 180) / Math.PI;
      while (relDeg > 180) relDeg -= 360;
      while (relDeg < -180) relDeg += 360;

      const rawX = cx + relDeg * pxPerDeg;
      const minX = 14;
      const maxX = this.compassW - 58;
      const clampedX = Math.max(minX, Math.min(maxX, rawX));

      ctx.save();
      // Subtle cyan halo
      ctx.beginPath();
      ctx.arc(clampedX, 11.5, 6.5, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(34, 211, 238, 0.22)';
      ctx.fill();

      // Crisp cyan diamond
      ctx.beginPath();
      ctx.moveTo(clampedX, 6.2);
      ctx.lineTo(clampedX + 5.2, 11.5);
      ctx.lineTo(clampedX, 16.8);
      ctx.lineTo(clampedX - 5.2, 11.5);
      ctx.closePath();
      ctx.fillStyle = '#22d3ee';
      ctx.fill();
      ctx.strokeStyle = '#0f172a';
      ctx.lineWidth = 1.2;
      ctx.stroke();

      // Gold center dot
      ctx.beginPath();
      ctx.arc(clampedX, 11.5, 1.6, 0, Math.PI * 2);
      ctx.fillStyle = '#fde047';
      ctx.fill();

      // Distance tag
      ctx.fillStyle = '#67e8f9';
      ctx.font = '900 8px ui-monospace, Menlo, monospace';
      const distLabel = `${Math.round(waypoint.dist)}m`;
      const arrowPrefix = rawX < minX ? '‹' : '';
      const arrowSuffix = rawX > maxX ? '›' : '';
      ctx.fillText(`${arrowPrefix}${distLabel}${arrowSuffix}`, clampedX, 24.5);
      ctx.restore();
    }

    ctx.restore();
  }
}

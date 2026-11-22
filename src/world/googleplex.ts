import * as THREE from 'three';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import { GAME_CONSTANTS } from '../data/catalog';
import { BoxCollider, GliderDropPoint, LandmarkInfo, LootSpot, MapAssetKey, SupplyDropSpot } from '../types';
import { AssetManager } from '../core/assetManager';
import { PhysicsWorld, PolygonDoorwaySpec } from '../core/physics';

// Exact Three.js XZ polygons matching scripts/blender/build_map.py (SVG -> local -> §10.2 centers)
const B40_POLY: [number, number][] = [
  [-85.14, -17.9],
  [-61.69, -10.31],
  [-26.52, -4.1],
  [-1.0, -7.55],
  [3.14, -19.28],
  [-18.24, -28.93],
  [-49.97, -37.9],
  [-83.07, -34.45],
];

const B41_POLY: [number, number][] = [
  [-128.55, -26.52],
  [-118.21, -12.72],
  [-102.34, -16.86],
  [-92.69, -38.93],
  [-111.31, -49.28],
  [-129.93, -41.69],
];

const B42_POLY: [number, number][] = [
  [-132.52, 24.38],
  [-129.76, 43.0],
  [-108.38, 43.69],
  [-100.79, 23.0],
  [-106.31, 3.0],
  [-131.14, 4.38],
];

const B43_POLY: [number, number][] = [
  [-99.38, 41.62],
  [-51.1, 48.52],
  [-16.62, 47.83],
  [-24.9, 25.76],
  [-64.9, 17.48],
  [-98.0, 20.93],
];

interface InstancePlacement {
  x: number;
  y?: number;
  z: number;
  rotY: number;
  scale: number;
}

interface IndoorLightZone {
  x: number;
  y: number;
  z: number;
  intensity: number;
  distance: number;
  colorHex: number;
}

export class GoogleplexWorld {
  public readonly worldGroup = new THREE.Group();
  public readonly landmarks: LandmarkInfo[] = [];
  public readonly lootSpots: LootSpot[] = [];
  public readonly gliderDropPoints: GliderDropPoint[] = [];
  public readonly supplyDropSpots: SupplyDropSpot[] = [];

  private sunLight!: THREE.DirectionalLight;
  private activeIndoorLight!: THREE.PointLight;
  private readonly indoorLightZones: IndoorLightZone[] = [];
  private readonly parkPlazaLootSpots: LootSpot[] = [];
  private lastSunSnapX = NaN;
  private lastSunSnapZ = NaN;
  private readonly indoorTargetPos = new THREE.Vector3();
  private readonly indoorTargetColor = new THREE.Color(0xfff4e0);

  private stormWall: THREE.Mesh;
  private stormWallMat: THREE.ShaderMaterial;
  private stormRing: THREE.Mesh;
  private pmremTarget: THREE.WebGLRenderTarget | null = null;
  private disposables: { dispose: () => void }[] = [];

  constructor(
    private readonly scene: THREE.Scene,
    private readonly renderer: THREE.WebGLRenderer,
    private readonly assets: AssetManager,
    private readonly physics: PhysicsWorld
  ) {
    this.worldGroup.name = 'GoogleplexCampus';
    this.scene.add(this.worldGroup);

    this.setupLightingAndEnvironment();
    this.setupInteriorLighting();
    this.setupCaliforniaSkyDome();
    this.setupTerrain();
    this.placeLandmarksAndColliders();
    this.placeInstancedCampusProps();
    this.placeParkDefensesAndGardens();
    this.placeOfficeInteriors();
    this.buildLandmarksMetadata();
    this.buildLootAndDropPoints();

    const storm = this.buildStormVisuals();
    this.stormWall = storm.wall;
    this.stormWallMat = storm.wallMat;
    this.stormRing = storm.ring;

    this.freezeStaticWorldMatrices();
  }

  private setupLightingAndEnvironment(): void {
    // Realistic PBR glass & brushed gunmetal reflections without external HDRI downloads
    const pmrem = new THREE.PMREMGenerator(this.renderer);
    const roomEnv = new RoomEnvironment();
    this.pmremTarget = pmrem.fromScene(roomEnv, 0.04);
    this.scene.environment = this.pmremTarget.texture;
    if ('environmentIntensity' in this.scene) {
      (this.scene as THREE.Scene & { environmentIntensity: number }).environmentIntensity = 0.68;
    }
    roomEnv.dispose();
    pmrem.dispose();

    // Subtle sunlit Mountain View coastal haze scaled for the 3× (600m × 380m) campus
    this.scene.fog = new THREE.Fog(0xdbe8f5, 250, 780);

    // Golden-hour California ambient sky/lawn bounce (raised slightly so distant lobbies stay warm with 1 dynamic PointLight)
    const hemi = new THREE.HemisphereLight(0x8ec5ff, 0x97ad78, 1.12);
    hemi.position.set(0, 160, 0);
    this.worldGroup.add(hemi);

    // Late-afternoon 4:30 PM warm directional sun with player-centered tight ±92m shadow frustum
    const sun = new THREE.DirectionalLight(0xfff1d6, 2.35);
    sun.position.set(115, 138, 82);
    sun.castShadow = true;
    sun.shadow.mapSize.set(1536, 1536);
    sun.shadow.camera.near = 20;
    sun.shadow.camera.far = 420;
    sun.shadow.camera.left = -92;
    sun.shadow.camera.right = 92;
    sun.shadow.camera.top = 92;
    sun.shadow.camera.bottom = -92;
    sun.shadow.bias = -0.0004;
    sun.shadow.normalBias = 0.04;
    this.worldGroup.add(sun);
    this.worldGroup.add(sun.target);
    this.sunLight = sun;

    // Subtle cool sky fill light from opposite azimuth
    const fill = new THREE.DirectionalLight(0x93c5fd, 0.36);
    fill.position.set(-180, 95, -135);
    this.worldGroup.add(fill);
  }

  /**
   * Registers lightweight indoor LED lighting zones across all playable office ground floors,
   * Gradient Canopy atrium, and the under-Skybridge breezeway, powered by a SINGLE reusable
   * non-shadow PointLight repositioned dynamically around the active player in updatePerformanceFocus().
   */
  private setupInteriorLighting(): void {
    const indoorLights: [number, number, number, number, number, number?][] = [
      // (x, y, z, intensity, distance, optional colorHex)
      // B40 — Charlie's Café West, Center Commons, East Partner Plex
      [-68, 5.15, -24, 9.5, 36],
      [-42, 5.15, -20, 10.0, 38],
      [-15, 5.15, -18, 9.0, 34],
      // B41 — SWE Engineering Hub
      [-112, 5.15, -31, 9.5, 36],
      // B42 — Design Studio & Lounge
      [-117, 5.15, 23, 9.5, 36],
      // B43 — Sweeping Open Office Floor (West & East wings)
      [-78, 5.15, 32, 10.0, 38],
      [-38, 5.15, 35, 10.0, 38],
      // Gradient Canopy Atrium (West & East halls)
      [101, 6.8, 4, 11.0, 44, 0xfff8ec],
      [125, 6.8, 4, 11.0, 44, 0xfff8ec],
      // Under-Skybridge Breezeway
      [-73, 3.25, 2, 5.5, 22],
      // Outer 3× Mountain View Campus Offices & Concert Stage
      [-225, 5.15, -26, 9.5, 42], // Google 2000 North Interior
      [-224, 5.15, 30, 9.5, 42],  // Google 1950 South Interior
      [-125, 5.15, 126, 9.0, 40], // 1098 Alta West Wings
      [-79, 5.15, 126, 8.5, 36],  // 1098 Alta East Wing
      [34, 5.15, 112, 9.5, 40],   // Charleston Campus North Wing
      [34, 5.15, 156, 9.5, 40],   // Charleston Campus South Wing
      [234, 5.15, -22, 9.5, 42],  // Google 2015 Interior
      [236, 5.15, -140, 9.5, 42], // Google CL2 Interior
      [234, 5.15, 122, 9.5, 42],  // Google 1395 Interior
      [50.6, 5.8, -159.9, 10.5, 36, 0xfff7e6], // Shoreline Amphitheatre Acoustic Stage
    ];

    this.indoorLightZones.length = 0;
    for (const [x, y, z, intensity, distance, colorHex] of indoorLights) {
      this.indoorLightZones.push({
        x,
        y,
        z,
        intensity,
        distance,
        colorHex: colorHex ?? 0xfff4e0,
      });
    }

    // Single reusable indoor PointLight (eliminates 20 permanent PointLights from every PBR fragment shader)
    const light = new THREE.PointLight(0xfff4e0, 0, 38, 1.35);
    light.position.set(0, 5.15, 0);
    light.castShadow = false;
    light.name = 'ActiveIndoorLight';
    this.worldGroup.add(light);
    this.activeIndoorLight = light;
  }

  private setupCaliforniaSkyDome(): void {
    const sunDir = new THREE.Vector3(175, 195, 125).normalize();
    const skyGeo = new THREE.SphereGeometry(920, 32, 20);
    const skyMat = new THREE.ShaderMaterial({
      side: THREE.BackSide,
      depthWrite: false,
      uniforms: {
        uZenith: { value: new THREE.Color('#2d72d9') },
        uMidSky: { value: new THREE.Color('#7cc4fa') },
        uHorizon: { value: new THREE.Color('#fde68a') },
        uGround: { value: new THREE.Color('#c8d9be') },
        uSunDir: { value: sunDir },
      },
      vertexShader: /* glsl */ `
        varying vec3 vWorldDir;
        void main() {
          vec4 wp = modelMatrix * vec4(position, 1.0);
          vWorldDir = normalize(wp.xyz);
          gl_Position = projectionMatrix * viewMatrix * wp;
        }
      `,
      fragmentShader: /* glsl */ `
        uniform vec3 uZenith;
        uniform vec3 uMidSky;
        uniform vec3 uHorizon;
        uniform vec3 uGround;
        uniform vec3 uSunDir;
        varying vec3 vWorldDir;
        void main() {
          vec3 d = normalize(vWorldDir);
          float h = d.y;
          vec3 col;
          if (h >= 0.0) {
            float t1 = smoothstep(0.0, 0.24, h);
            float t2 = smoothstep(0.18, 0.78, h);
            col = mix(uHorizon, uMidSky, t1);
            col = mix(col, uZenith, t2);
          } else {
            col = mix(uHorizon, uGround, smoothstep(0.0, -0.18, h));
          }
          float sunDot = max(dot(d, normalize(uSunDir)), 0.0);
          float corona = pow(sunDot, 12.0) * 0.26;
          float disc = smoothstep(0.9982, 0.9994, sunDot) * 1.1;
          col += vec3(1.0, 0.92, 0.72) * (corona + disc);
          gl_FragColor = vec4(col, 1.0);
        }
      `,
    });
    const skyMesh = new THREE.Mesh(skyGeo, skyMat);
    skyMesh.name = 'CaliforniaSkyDome';
    this.worldGroup.add(skyMesh);
    this.disposables.push(skyGeo, skyMat);
  }

  private setupTerrain(): void {
    const terrainGlb = this.assets.instantiateMapAsset('terrain');
    if (terrainGlb) {
      terrainGlb.traverse((obj) => {
        if ((obj as THREE.Mesh).isMesh) {
          const mesh = obj as THREE.Mesh;
          mesh.castShadow = false;
          mesh.receiveShadow = true;
        }
      });
      this.worldGroup.add(terrainGlb);
      this.physics.bakeTerrainHeightfield(terrainGlb);
      return;
    }

    // Graceful procedural Mountain View terrain matching §10.2 if googleplex_terrain.glb is absent
    this.buildProceduralFallbackTerrain();
  }

  private buildProceduralFallbackTerrain(): void {
    const width = GAME_CONSTANTS.ARENA_WIDTH + 80;
    const depth = GAME_CONSTANTS.ARENA_DEPTH + 80;
    const geo = new THREE.PlaneGeometry(width, depth, 180, 120);
    geo.rotateX(-Math.PI / 2);

    const pos = geo.attributes.position;
    const colors = new Float32Array(pos.count * 3);
    const colLawn = new THREE.Color('#6ea44e');
    const colPark = new THREE.Color('#5a9244');
    const colHill = new THREE.Color('#80a856');
    const colCreekBank = new THREE.Color('#7b725b');
    const colTmp = new THREE.Color();

    for (let i = 0; i < pos.count; i++) {
      const x = pos.getX(i);
      const z = pos.getZ(i);
      const y = this.physics.getAnalyticalTerrainHeight(x, z);
      pos.setY(i, y);

      if (Math.abs(x + 156) < 6.2) {
        colTmp.copy(colCreekBank);
      } else if (z < -70) {
        colTmp.copy(colHill);
      } else if (x > 6 && x < 58 && z > -55 && z < 55) {
        colTmp.copy(colPark).lerp(colLawn, Math.min(1, y * 0.55));
      } else {
        colTmp.copy(colLawn);
      }
      colors[i * 3] = colTmp.r;
      colors[i * 3 + 1] = colTmp.g;
      colors[i * 3 + 2] = colTmp.b;
    }
    geo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    geo.computeVertexNormals();

    const groundMat = new THREE.MeshStandardMaterial({
      vertexColors: true,
      roughness: 0.92,
      metalness: 0.0,
    });
    const groundMesh = new THREE.Mesh(geo, groundMat);
    groundMesh.receiveShadow = true;
    this.worldGroup.add(groundMesh);
    this.disposables.push(geo, groundMat);

    // Permanente Creek glossy water ribbon at X = -156m across full Z ∈ [-190, +190]
    const waterGeo = new THREE.PlaneGeometry(7.2, 390);
    waterGeo.rotateX(-Math.PI / 2);
    const waterMat = new THREE.MeshStandardMaterial({
      color: 0x2b7cb3,
      roughness: 0.12,
      metalness: 0.18,
    });
    const water = new THREE.Mesh(waterGeo, waterMat);
    water.position.set(-156, -0.32, 0);
    water.receiveShadow = true;
    this.worldGroup.add(water);
    this.disposables.push(waterGeo, waterMat);

    // Asphalt boulevards: Amphitheatre Pkwy, Charleston Rd, N Shoreline Blvd, Stierlin/Crittenden/Shorebird/Plymouth
    const asphaltMat = new THREE.MeshStandardMaterial({ color: 0x3b424c, roughness: 0.86, metalness: 0.04 });
    const concreteMat = new THREE.MeshStandardMaterial({ color: 0xd6cfc2, roughness: 0.82, metalness: 0.0 });
    this.disposables.push(asphaltMat, concreteMat);

    const addFlatSlab = (x: number, y: number, z: number, w: number, d: number, rotY: number, mat: THREE.Material) => {
      const g = new THREE.PlaneGeometry(w, d);
      g.rotateX(-Math.PI / 2);
      const m = new THREE.Mesh(g, mat);
      m.position.set(x, y, z);
      m.rotation.y = rotY;
      m.receiveShadow = true;
      this.worldGroup.add(m);
      this.disposables.push(g);
    };

    // Amphitheatre Pkwy (North) & Charleston Rd (South) spanning full 600m width
    addFlatSlab(0, 0.03, -65, 600, 10.5, 0, asphaltMat);
    addFlatSlab(0, 0.03, 65, 600, 10.5, 0, asphaltMat);
    // N Shoreline Blvd (full N–S eastern arterial at X = +168m)
    addFlatSlab(168, 0.03, 0, 12.0, 380, 0, asphaltMat);
    // Eastern E–W arteries (Stierlin Ct, Crittenden Ln, Shorebird Way) & southern Plymouth St
    addFlatSlab(234, 0.03, -108, 132, 9.0, 0, asphaltMat);
    addFlatSlab(234, 0.03, 160, 132, 9.0, 0, asphaltMat);
    addFlatSlab(9, 0.03, 180, 318, 9.0, 0, asphaltMat);
    // Permanente Creek Trail (full N–S paved path at X = -148.5m)
    addFlatSlab(-148.5, 0.04, 0, 3.6, 380, 0, concreteMat);
    // Curved Joaquin Rd approximation between Charleston Park & Gradient Canopy
    addFlatSlab(65, 0.03, -34, 7.2, 62, 0.28, asphaltMat);
    addFlatSlab(65, 0.03, 34, 7.2, 66, -0.31, asphaltMat);
    // Quad Courtyard concrete apron & Stan plaza paved ground
    addFlatSlab(-68, 0.02, 2, 132, 104, 0, concreteMat);
    // SE B43 parking pad & Parking Lot C
    addFlatSlab(-4, 0.03, 38, 22, 20, 0, asphaltMat);
    addFlatSlab(118, 0.03, -112, 54, 38, 0, asphaltMat);
  }

  private placeLandmarksAndColliders(): void {
    // 1. Building 40 (Charlie's Café & Partner Plex) at (-41, 0, -21) — Hollow Playable Ground Floor + Walkable Roof!
    this.placeLandmarkMesh('b40_partnerplex', -41, 0, -21, 0);
    const b40Doorways: PolygonDoorwaySpec[] = [
      { edgeIndex: 0, distStart: 3.0, distEnd: 9.2, clearHeight: 3.6 },   // West Courtyard portal
      { edgeIndex: 1, distStart: 24.5, distEnd: 31.7, clearHeight: 3.6 }, // Charlie's Café South Lobby
      { edgeIndex: 3, distStart: 3.1, distEnd: 9.1, clearHeight: 3.6 },   // East Partner Plex portal
      { edgeIndex: 6, distStart: 13.2, distEnd: 20.2, clearHeight: 3.6 }, // North Amphitheatre Pkwy portal
    ];
    this.physics.addPolygon(B40_POLY, -0.25, 0.056, 'b40_floor', 'b40_floor');
    this.physics.addPolygon(B40_POLY, 5.75, 6.4, 'b40_roof', 'b40_main');
    this.physics.addHollowPolygonWalls(B40_POLY, 0, 6.4, 0.45, b40Doorways, 'b40');
    for (const [cx, cz] of [
      [-69, -25],
      [-52, -23],
      [-36, -17.5],
      [-20, -15.5],
    ] as const) {
      this.physics.addCylinder(cx, cz, 0.32, 0.056, 5.75, 'b40_col');
    }
    this.physics.addCenteredBox(-59.5, 1.486, -24, 4.6, 2.86, 0.22, { rotationY: 1.35, tag: 'b40_partition' });
    this.physics.addCenteredBox(-28, 1.486, -16.5, 4.6, 2.86, 0.22, { rotationY: 1.25, tag: 'b40_partition' });
    // B40 exterior SE staircase ramp (exact match to build_map.py: base (-20.74,-3.63) -> top (-10.63,-4.99))
    this.physics.addCenteredBox(-15.68, 3.2, -4.31, 10.4, 6.4, 2.5, {
      rotationY: 0.1343,
      isRamp: true,
      rampAxis: 'x',
      rampDir: 1,
      blocksBullets: false,
      tag: 'b40_stair',
    });
    this.physics.addCenteredBox(-9.49, 6.26, -5.15, 2.6, 0.28, 2.7, {
      rotationY: 0.1343,
      isPlatform: true,
      tag: 'b40_landing',
    });
    // Charlie's Café courtyard espresso counter cover
    this.physics.addCenteredBox(-43, 0.62, -6.5, 7.6, 1.24, 1.4, { rotationY: 0.18, tag: 'charlies_bar' });
    // Rooftop HVAC cover units on B40
    this.physics.addCenteredBox(-41, 7.12, -21, 3.8, 1.44, 2.5, { rotationY: -0.22, tag: 'b40_hvac' });
    this.physics.addCenteredBox(-52, 7.12, -22, 3.8, 1.44, 2.5, { rotationY: -0.22, tag: 'b40_hvac2' });

    // 2. Building 41 at (-112, 0, -31) — Hollow Playable SWE Ground Floor + Walkable Roof!
    this.placeLandmarkMesh('b41', -112, 0, -31, 0);
    const b41Doorways: PolygonDoorwaySpec[] = [
      { edgeIndex: 1, distStart: 4.9, distEnd: 11.5, clearHeight: 3.6 },  // South Courtyard overhang
      { edgeIndex: 3, distStart: 7.4, distEnd: 13.9, clearHeight: 3.6 },  // NE Amphitheatre Pkwy
      { edgeIndex: 5, distStart: 4.6, distEnd: 10.6, clearHeight: 3.6 },  // West Permanente Creek
    ];
    this.physics.addPolygon(B41_POLY, -0.25, 0.056, 'b41_floor', 'b41_floor');
    this.physics.addPolygon(B41_POLY, 5.75, 6.4, 'b41_roof', 'b41_main');
    this.physics.addHollowPolygonWalls(B41_POLY, 0, 6.4, 0.45, b41Doorways, 'b41');
    for (const [cx, cz] of [
      [-117, -35],
      [-106.5, -33.5],
      [-112, -24],
    ] as const) {
      this.physics.addCylinder(cx, cz, 0.32, 0.056, 5.75, 'b41_col');
    }
    this.physics.addCenteredBox(-113.5, 1.486, -37.5, 4.0, 2.86, 0.22, { rotationY: 0.2, tag: 'b41_partition' });
    // B41 exterior SE staircase ramp (exact match: base (-99.75,-19.67) -> top (-95.66,-29.02))
    this.physics.addCenteredBox(-97.71, 3.2, -24.34, 10.4, 6.4, 2.5, {
      rotationY: 1.1584,
      isRamp: true,
      rampAxis: 'x',
      rampDir: 1,
      blocksBullets: false,
      tag: 'b41_stair',
    });
    this.physics.addCenteredBox(-95.2, 6.26, -30.07, 2.6, 0.28, 2.7, {
      rotationY: 1.1584,
      isPlatform: true,
      tag: 'b41_landing',
    });
    this.physics.addCenteredBox(-112, 7.12, -31, 3.8, 1.44, 2.5, { rotationY: 0.18, tag: 'b41_hvac' });

    // 3. Building 42 at (-117, 0, +23) — Hollow Playable Design Studio Floor + Walkable Roof!
    this.placeLandmarkMesh('b42', -117, 0, 23, 0);
    const b42Doorways: PolygonDoorwaySpec[] = [
      { edgeIndex: 1, distStart: 7.4, distEnd: 13.9, clearHeight: 3.6 },  // South Charleston Rd
      { edgeIndex: 3, distStart: 6.9, distEnd: 13.9, clearHeight: 3.6 },  // East Volleyball overhang
      { edgeIndex: 5, distStart: 7.0, distEnd: 13.0, clearHeight: 3.6 },  // West Permanente Creek
    ];
    this.physics.addPolygon(B42_POLY, -0.25, 0.056, 'b42_floor', 'b42_floor');
    this.physics.addPolygon(B42_POLY, 5.75, 6.4, 'b42_roof', 'b42_main');
    this.physics.addHollowPolygonWalls(B42_POLY, 0, 6.4, 0.45, b42Doorways, 'b42');
    for (const [cx, cz] of [
      [-121.5, 16],
      [-112.5, 17],
      [-118.5, 31],
    ] as const) {
      this.physics.addCylinder(cx, cz, 0.32, 0.056, 5.75, 'b42_col');
    }
    this.physics.addCenteredBox(-116.5, 1.486, 24, 4.0, 2.86, 0.22, { rotationY: 1.5, tag: 'b42_partition' });
    this.physics.addCenteredBox(-117, 7.12, 23, 3.8, 1.44, 2.5, { rotationY: -0.1, tag: 'b42_hvac' });

    // 4. Building 43 (Solar Roof) at (-58, 0, +33) — Hollow Sweeping Open Office Floor + Walkable Solar Roof!
    this.placeLandmarkMesh('b43', -58, 0, 33, 0);
    const b43Doorways: PolygonDoorwaySpec[] = [
      { edgeIndex: 0, distStart: 21.0, distEnd: 28.0, clearHeight: 3.6 }, // South Charleston Rd
      { edgeIndex: 2, distStart: 8.5, distEnd: 15.0, clearHeight: 3.6 },  // East SE Parking / Charleston Park
      { edgeIndex: 3, distStart: 25.0, distEnd: 32.0, clearHeight: 3.6 }, // NE Courtyard facing Stan Plaza
      { edgeIndex: 4, distStart: 18.5, distEnd: 25.5, clearHeight: 3.6 }, // NW Volleyball overhang
    ];
    this.physics.addPolygon(B43_POLY, -0.25, 0.056, 'b43_floor', 'b43_floor');
    this.physics.addPolygon(B43_POLY, 5.75, 6.4, 'b43_roof', 'b43_main');
    this.physics.addHollowPolygonWalls(B43_POLY, 0, 6.4, 0.45, b43Doorways, 'b43');
    for (const [cx, cz] of [
      [-82, 30.5],
      [-65, 32],
      [-48, 35.5],
      [-34, 37.5],
    ] as const) {
      this.physics.addCylinder(cx, cz, 0.32, 0.056, 5.75, 'b43_col');
    }
    this.physics.addCenteredBox(-73.5, 1.486, 31.5, 4.6, 2.86, 0.22, { rotationY: 1.45, tag: 'b43_partition' });
    this.physics.addCenteredBox(-40.5, 1.486, 36.5, 4.6, 2.86, 0.22, { rotationY: 1.35, tag: 'b43_partition' });
    // B43 exterior NE staircase ramp (exact match: base (-29.44,23.54) -> top (-39.43,21.48))
    this.physics.addCenteredBox(-34.44, 3.2, 22.51, 10.4, 6.4, 2.5, {
      rotationY: 2.9376,
      isRamp: true,
      rampAxis: 'x',
      rampDir: 1,
      blocksBullets: false,
      tag: 'b43_stair',
    });
    this.physics.addCenteredBox(-40.56, 6.26, 21.24, 2.6, 0.28, 2.7, {
      rotationY: 2.9376,
      isPlatform: true,
      tag: 'b43_landing',
    });
    this.physics.addCenteredBox(-58, 7.12, 33, 3.8, 1.44, 2.5, { rotationY: -0.16, tag: 'b43_hvac' });
    this.physics.addCenteredBox(-46, 7.12, 35, 3.8, 1.44, 2.5, { rotationY: -0.16, tag: 'b43_hvac2' });

    // 5. Elevated Diagonal Glass Skybridge at (-73, 0, +2) — +4.2m deck, open walkthrough underneath!
    this.placeLandmarkMesh('skybridge', -73, 0, 2, 0);
    const skyYaw = (-8.6 * Math.PI) / 180;
    // Elevated walkable deck (minY 3.65 allows unobstructed 3.65m headroom walking underneath!)
    this.physics.addCenteredBox(-73, 3.925, 2, 7.6, 0.55, 36.2, {
      rotationY: skyYaw,
      isPlatform: true,
      tag: 'skybridge_deck',
    });
    // Skybridge curved roof top (walkable if player lands on roof during Sky Drop)
    this.physics.addCenteredBox(-73, 7.85, 2, 7.8, 0.5, 36.4, {
      rotationY: skyYaw,
      isPlatform: true,
      tag: 'skybridge_roof',
    });
    // Glass side curtain walls on elevated deck level (+4.2..+7.35m)
    const cosSky = Math.cos(skyYaw);
    const sinSky = Math.sin(skyYaw);
    for (const sgn of [-1, 1]) {
      const sideX = sgn * 3.82;
      this.physics.addCenteredBox(-73 + sideX * cosSky, 5.75, 2 - sideX * sinSky, 0.24, 3.1, 35.8, {
        rotationY: skyYaw,
        isPlatform: true,
        tag: 'skybridge_wall',
      });
    }
    // 4 ground V-pier footings at local Z = ±12.2, X = ±3.05
    for (const lz of [-12.2, 12.2]) {
      for (const lx of [-3.05, 3.05]) {
        const wx = -73 + lx * cosSky + lz * sinSky;
        const wz = 2 - lx * sinSky + lz * cosSky;
        this.physics.addCylinder(wx, wz, 0.65, 0, 3.8, 'skybridge_pier');
      }
    }

    // 6. Sand Volleyball Court at (-91, 0, +4), +10° CCW matching SVG -10° & full-campus Blender master
    const vballYaw = (10 * Math.PI) / 180;
    this.placeLandmarkMesh('volleyball_court', -91, 0, 4, vballYaw);
    // Volleyball net posts rotated cleanly with court
    const vbSin = Math.sin(vballYaw);
    const vbCos = Math.cos(vballYaw);
    this.physics.addCylinder(-91 - 4.45 * vbSin, 4 - 4.45 * vbCos, 0.16, 0, 2.6, 'vball_post');
    this.physics.addCylinder(-91 + 4.45 * vbSin, 4 + 4.45 * vbCos, 0.16, 0, 2.6, 'vball_post');

    // 7. Stan the T-Rex Plaza at (-51, 0, +4)
    this.placeLandmarkMesh('stan_trex', -51, 0, 4, 0);
    // Low walkable stone apron (0..0.22m) + solid tiered pedestal (0.22..1.85m)
    this.physics.addCylinder(-51, 4, 3.9, 0, 0.22, 'stan_apron', false);
    this.physics.addCylinder(-51, 4, 2.85, 0.22, 1.88, 'stan_pedestal', true);

    // 8. Gradient Canopy (Google Visitor Experience & Huddle) at (+113, 0, +4)
    this.placeLandmarkMesh('gradient_canopy', 113, 0, 4, 0);
    // Walkable travertine podium (+0.40m)
    this.physics.addCenteredBox(113, 0.2, 4, 82, 0.4, 86, { isPlatform: true, blocksBullets: false, tag: 'gc_podium' });
    // Atrium glass walls along the 4 rounded corners — leaving all 4 wide ~13.6m N/S/E/W entrance portals OPEN!
    const gcWallArcs: [number, number, number, number, number][] = [
      // (localX, localZ, len, thickness, rotY)
      [-23.5, -26.5, 25, 0.45, -0.58], // NW glass arc
      [23.5, -26.5, 25, 0.45, 0.58],   // NE glass arc
      [-23.5, 26.5, 25, 0.45, 0.58],   // SW glass arc
      [23.5, 26.5, 25, 0.45, -0.58],   // SE glass arc
      [-34.2, -16.5, 16.5, 0.45, Math.PI / 2], // West-North wing
      [-34.2, 16.5, 16.5, 0.45, Math.PI / 2],  // West-South wing
      [34.2, -16.5, 16.5, 0.45, Math.PI / 2],  // East-North wing
      [34.2, 16.5, 16.5, 0.45, Math.PI / 2],   // East-South wing
      [-16.5, -36.2, 16.0, 0.45, 0],           // North-West wing
      [16.5, -36.2, 16.0, 0.45, 0],            // North-East wing
      [-16.5, 36.2, 16.0, 0.45, 0],            // South-West wing
      [16.5, 36.2, 16.0, 0.45, 0],             // South-East wing
    ];
    for (const [lx, lz, len, thk, rot] of gcWallArcs) {
      this.physics.addCenteredBox(113 + lx, 3.4, 4 + lz, len, 6.0, thk, {
        rotationY: rot,
        tag: 'gc_glass_wall',
      });
    }
    // Huddle Café espresso bar counter inside SW atrium (Blender local (-5.5,-10.5) -> Three.js (-5.5, +10.5))
    this.physics.addCenteredBox(113 - 5.5, 0.96, 4 + 10.5, 12.0, 1.15, 2.5, { tag: 'huddle_bar' });
    this.physics.addCenteredBox(113 - 10.7, 0.96, 4 + 6.7, 2.5, 1.15, 6.6, { tag: 'huddle_bar_wing' });
    // 3 Visitor Experience exhibition kiosk pods inside atrium
    const gcPods: [number, number, number][] = [
      [10.5, -9.5, 0.25],
      [-11.0, -11.5, -0.35],
      [12.5, 7.5, 0.45],
    ];
    for (const [px, pz, rot] of gcPods) {
      this.physics.addCenteredBox(113 + px, 1.4, 4 + pz, 6.4, 2.0, 2.4, {
        rotationY: rot,
        tag: 'gc_kiosk',
      });
    }
    // 8 interior tree-columns inside atrium
    const gcCols: [number, number][] = [
      [-16, -16], [0, -18], [16, -16],
      [-18, 0],             [18, 0],
      [-16, 16],  [0, 18],  [16, 16],
    ];
    for (const [cx, cz] of gcCols) {
      this.physics.addCylinder(113 + cx, 4 + cz, 0.42, 0.4, 8.2, 'gc_col');
    }
    // Enriched Gradient Canopy Interior Features (matched to build_map.py §5C–§5F):
    // NW Acoustic Pavilion (walk-in open front, back timber slat wall + banquette bench + rib roof)
    this.physics.addCenteredBox(92.21, 2.41, -19.23, 8.2, 3.8, 0.35, { rotationY: -0.78, tag: 'gc_nw_pav_wall' });
    this.physics.addCenteredBox(91.56, 0.8, -18.57, 6.8, 0.8, 1.32, { rotationY: -0.78, tag: 'gc_nw_pav_bench' });
    this.physics.addCenteredBox(90.5, 4.3, -17.5, 8.4, 0.28, 5.4, {
      rotationY: -0.78,
      isPlatform: true,
      tag: 'gc_nw_pav_roof',
    });
    // NE Showcase Pavilion (walk-in open front, back slat wall + glowing Workspace showcase wall + rib roof)
    this.physics.addCenteredBox(133.79, 2.41, -19.23, 8.2, 3.8, 0.35, { rotationY: 0.78, tag: 'gc_ne_pav_wall' });
    this.physics.addCenteredBox(134.28, 1.95, -18.73, 5.6, 2.8, 0.36, { rotationY: 0.78, tag: 'gc_ne_showcase' });
    this.physics.addCenteredBox(135.5, 4.3, -17.5, 8.4, 0.28, 5.4, {
      rotationY: 0.78,
      isPlatform: true,
      tag: 'gc_ne_pav_roof',
    });
    // SE Stepped Timber Amphitheater (4 walkable ascending 0.42m tiers Y=0.40..2.08m + 2 flanking planter cheek walls)
    const ampRot = (135 * Math.PI) / 180;
    const ampTiers: [number, number, number][] = [
      [135.77, 23.23, 0.42],
      [134.96, 24.04, 0.84],
      [134.15, 24.85, 1.26],
      [133.33, 25.67, 1.68],
    ];
    for (let ti = 0; ti < ampTiers.length; ti++) {
      const [tx, tz, th] = ampTiers[ti];
      this.physics.addCenteredBox(tx, 0.4 + th * 0.5, tz, 8.8, th, 1.2, {
        rotationY: ampRot,
        tag: `gc_amp_tier_${ti}`,
      });
    }
    this.physics.addCenteredBox(137.89, 1.2, 28.11, 1.1, 1.6, 4.9, { rotationY: ampRot, tag: 'gc_amp_cheek' });
    this.physics.addCenteredBox(130.89, 1.2, 21.11, 1.1, 1.6, 4.9, { rotationY: ampRot, tag: 'gc_amp_cheek' });
    // SW Gallery Glowing Google Workspace Showcase Feature Wall
    this.physics.addCenteredBox(89.5, 1.84, 24.0, 6.4, 2.88, 0.5, { rotationY: -Math.PI / 4, tag: 'gc_sw_showcase' });
    // 8 Biophilic Portal Flanking Planter Beds (waist-high tactical cover Y=0.40..1.05m, portals wide open!)
    const gcPlanters: [number, number, number][] = [
      [103.2, -25.2, 0],
      [122.8, -25.2, 0],
      [103.2, 33.2, 0],
      [122.8, 33.2, 0],
      [85.0, -5.8, Math.PI * 0.5],
      [85.0, 13.8, Math.PI * 0.5],
      [141.0, -5.8, Math.PI * 0.5],
      [141.0, 13.8, Math.PI * 0.5],
    ];
    for (const [px, pz, rot] of gcPlanters) {
      this.physics.addCenteredBox(px, 0.725, pz, 3.6, 0.65, 1.44, {
        rotationY: rot,
        tag: 'gc_portal_planter',
      });
    }
    // High dragonscale roof canopy platform (+8.2m) so players gliding onto roof can stand on top
    this.physics.addCenteredBox(113, 8.0, 4, 80, 0.6, 84, { isPlatform: true, tag: 'gc_canopy_roof' });

    // 9. The Orb Plaza at (+152, 0, +60)
    this.placeLandmarkMesh('orb_plaza', 152, 0, 60, 0);
    this.physics.addCylinder(152, 60, 10.0, 0, 0.2, 'orb_apron', false);
    this.physics.addCylinder(152, 60, 2.75, 0.2, 5.2, 'orb_sculpture', true);

    // 10–15. Expanded 3× Mountain View Campus Ring Landmarks (600m × 380m)
    this.placeExpandedLandmarksAndColliders();
  }

  /**
   * Mounts all 6 new 3× Mountain View architectural landmarks (8 total placements) with
   * exact 1:1 colliders, walkable roofs, exterior staircases, open hollow lobbies,
   * concert seating bowl tiers, dugouts, bleachers, and cover matching build_expanded_landmarks.py.
   */
  private placeExpandedLandmarksAndColliders(): void {
    // -----------------------------------------------------------------------
    // 10. Shoreline Amphitheatre at (+58, 0, -148) — SE +32° orientation baked in GLB!
    // -----------------------------------------------------------------------
    this.placeLandmarkMesh('shoreline_amphitheatre', 58, 0, -148, 0);
    const amphX = 58;
    const amphZ = -148;
    const amphYaw = (32 * Math.PI) / 180; // 0.5585 rad
    const cosAmph = Math.cos(amphYaw);
    const sinAmph = Math.sin(amphYaw);
    // Exact Blender local (bx, by) -> Three.js world (wx, wz) after +32° CCW Blender Z-rotation
    const amphWorld = (bx: number, by: number): [number, number] => {
      const rx = bx * cosAmph - by * sinAmph;
      const ry = bx * sinAmph + by * cosAmph;
      return [amphX + rx, amphZ - ry];
    };

    // Walkable fan concourse apron (0..0.16m)
    this.physics.addCylinder(amphX, amphZ, 30.2, -0.2, 0.16, 'shoreline_apron', false);

    // Open Acoustic Performance Stage polygon (Y = 0.16..1.22m)
    const stagePoly: [number, number][] = [
      amphWorld(-11.5, 19.5),
      amphWorld(-13.5, 11.5),
      amphWorld(-8.0, 8.2),
      amphWorld(8.0, 8.2),
      amphWorld(13.5, 11.5),
      amphWorld(11.5, 19.5),
    ];
    this.physics.addPolygon(stagePoly, 0.16, 1.22, 'shoreline_stage', 'shoreline_stage');

    // Twin walkable side stage ramps (rising 0.16m -> 1.22m inward onto stage flanks)
    for (const sgn of [-1, 1] as const) {
      const [rx, rz] = amphWorld(sgn * 14.7, 13.8);
      this.physics.addCenteredBox(rx, 0.69, rz, 4.1, 1.06, 3.3, {
        rotationY: amphYaw,
        isRamp: true,
        rampAxis: 'x',
        rampDir: sgn === -1 ? 1 : -1,
        blocksBullets: false,
        tag: 'shoreline_stage_ramp',
      });
    }

    // Backstage Acoustic Shell & Green-Room Cover Wall
    this.physics.addCenteredBox(46.61, 3.4, -166.23, 26.0, 6.6, 1.4, {
      rotationY: amphYaw,
      tag: 'shoreline_backstage',
    });

    // Twin Iconic Steel Primary Mast Towers (r = 0.85m, Y = 0..20.2m)
    this.physics.addCylinder(46.01, -142.28, 0.85, 0, 20.2, 'shoreline_mast_w', true);
    this.physics.addCylinder(68.4, -156.27, 0.85, 0, 20.2, 'shoreline_mast_e', true);

    // Twin SE Entry Concourse Ticket & Concession Kiosks (solid cover + walkable canopy top!)
    this.physics.addCenteredBox(61.23, 1.75, -121.13, 6.4, 3.5, 3.2, {
      rotationY: amphYaw,
      tag: 'shoreline_kiosk_w',
    });
    this.physics.addCenteredBox(80.74, 1.75, -133.32, 6.4, 3.5, 3.2, {
      rotationY: amphYaw,
      tag: 'shoreline_kiosk_e',
    });

    // Walkable Curved Terraced Amphitheatre Seating Bowl (7 gentle 0.34m tiers up to Y=2.58m + outer grassy rim Y=2.72m)
    const bowlFocalY = 11.5;
    const bowlAngMin = (-152 * Math.PI) / 180;
    const bowlAngMax = (-28 * Math.PI) / 180;
    const bowlSegs = 6;
    for (let ti = 0; ti < 7; ti++) {
      const rIn = 10.5 + ti * 2.55;
      const rOut = rIn + 2.58;
      const rMid = 0.5 * (rIn + rOut);
      const zTier = 0.2 + (ti + 1) * 0.34;
      for (let ai = 0; ai < bowlSegs; ai++) {
        const a0 = bowlAngMin + ((bowlAngMax - bowlAngMin) * ai) / bowlSegs;
        const a1 = bowlAngMin + ((bowlAngMax - bowlAngMin) * (ai + 1)) / bowlSegs;
        const am = 0.5 * (a0 + a1);
        const segW = rMid * (a1 - a0) * 1.04;
        const [wx, wz] = amphWorld(rMid * Math.cos(am), bowlFocalY + rMid * Math.sin(am));
        this.physics.addCenteredBox(wx, 0.16 + (zTier - 0.16) * 0.5, wz, segW, zTier - 0.16, 2.62, {
          rotationY: am + Math.PI * 0.5 + amphYaw,
          blocksBullets: ti >= 2,
          tag: `shoreline_bowl_t${ti}`,
        });
      }
    }
    // Outer grassy picnic rim behind bowl (leaving central SE concourse entry wide open!)
    for (let ai = 0; ai < bowlSegs; ai++) {
      const a0 = bowlAngMin + ((bowlAngMax - bowlAngMin) * ai) / bowlSegs;
      const a1 = bowlAngMin + ((bowlAngMax - bowlAngMin) * (ai + 1)) / bowlSegs;
      const am = 0.5 * (a0 + a1);
      if (Math.abs((am * 180) / Math.PI + 90) < 15) continue;
      const rMid = 31.0;
      const segW = rMid * (a1 - a0) * 1.04;
      const [wx, wz] = amphWorld(rMid * Math.cos(am), bowlFocalY + rMid * Math.sin(am));
      this.physics.addCenteredBox(wx, 1.44, wz, segW, 2.56, 4.8, {
        rotationY: am + Math.PI * 0.5 + amphYaw,
        tag: 'shoreline_lawn_rim',
      });
    }

    // -----------------------------------------------------------------------
    // 11. Google Athletic Recreation Field at (-220, 0, -134)
    // -----------------------------------------------------------------------
    this.placeLandmarkMesh('athletic_field', -220, 0, -134, 0);
    // Ground apron & lush turf pitch floor (0..0.062m)
    this.physics.addCenteredBox(-220, 0.031, -134, 66.0, 0.062, 42.0, {
      isPlatform: true,
      blocksBullets: false,
      tag: 'athletic_pitch',
    });
    // North Aluminum Spectator Bleachers (walkable 3-tier climbable stands + solid back guard!)
    for (const bx of [-234, -206]) {
      this.physics.addCenteredBox(bx, 0.34, -152.45, 14.0, 0.68, 0.95, { tag: 'athletic_bleacher_s1' });
      this.physics.addCenteredBox(bx, 0.68, -153.45, 14.0, 1.36, 1.0, { tag: 'athletic_bleacher_s2' });
      this.physics.addCenteredBox(bx, 1.02, -154.45, 14.0, 2.04, 1.05, { tag: 'athletic_bleacher_s3' });
      this.physics.addCenteredBox(bx, 1.55, -154.9, 14.0, 3.1, 0.25, { tag: 'athletic_bleacher_back' });
    }
    // South Shaded Team Dugouts (open North front facing pitch -> enterable cover + walkable roof!)
    for (const dx of [-232, -208]) {
      this.physics.addCenteredBox(dx, 1.25, -113.62, 7.2, 2.45, 0.22, { tag: 'athletic_dugout_back' });
      this.physics.addCenteredBox(dx - 3.5, 1.25, -114.6, 0.22, 2.45, 2.1, { tag: 'athletic_dugout_side' });
      this.physics.addCenteredBox(dx + 3.5, 1.25, -114.6, 0.22, 2.45, 2.1, { tag: 'athletic_dugout_side' });
      this.physics.addCenteredBox(dx, 2.52, -114.6, 7.4, 0.22, 2.25, { isPlatform: true, tag: 'athletic_dugout_roof' });
    }
    // Twin Soccer Goals (open front mouth, solid posts + rear/side net frames)
    for (const sgn of [-1, 1] as const) {
      const gxFront = -220 + sgn * 27.0;
      const gxBack = -220 + sgn * 29.2;
      const gxMid = 0.5 * (gxFront + gxBack);
      this.physics.addCylinder(gxFront, -134 - 3.66, 0.12, 0, 2.44, 'athletic_goal_post');
      this.physics.addCylinder(gxFront, -134 + 3.66, 0.12, 0, 2.44, 'athletic_goal_post');
      this.physics.addCenteredBox(gxBack, 1.15, -134, 0.24, 2.3, 7.32, { blocksBullets: false, tag: 'athletic_goal_net' });
      this.physics.addCenteredBox(gxMid, 1.15, -134 - 3.66, 2.2, 2.3, 0.2, { blocksBullets: false, tag: 'athletic_goal_net' });
      this.physics.addCenteredBox(gxMid, 1.15, -134 + 3.66, 2.2, 2.3, 0.2, { blocksBullets: false, tag: 'athletic_goal_net' });
    }
    // Six Stadium Floodlight Poles
    for (const [px, pz] of [
      [-246, -153.6],
      [-220, -153.8],
      [-194, -153.6],
      [-246, -114.4],
      [-220, -114.2],
      [-194, -114.4],
    ] as const) {
      this.physics.addCylinder(px, pz, 0.34, 0, 12.6, 'athletic_light_pole', true);
    }

    // -----------------------------------------------------------------------
    // 12. Google 2000 (North) & Google 1950 (South) at (-225, 0, +2)
    // -----------------------------------------------------------------------
    this.placeLandmarkMesh('google_2000_1950', -225, 0, 2, 0);
    const g2000Poly: [number, number][] = [
      [-264, -15],
      [-235, -11],
      [-189, -13],
      [-185, -37],
      [-229, -42],
      [-265, -36],
    ];
    this.physics.addPolygon(g2000Poly, -0.25, 0.056, 'g2000_floor', 'g2000_floor');
    this.physics.addPolygon(g2000Poly, 5.75, 6.4, 'g2000_roof', 'g2000_roof');
    this.physics.addHollowPolygonWalls(
      g2000Poly,
      0,
      6.4,
      0.45,
      [
        { edgeIndex: 1, distStart: 14.0, distEnd: 21.0, clearHeight: 3.6 },
        { edgeIndex: 2, distStart: 9.0, distEnd: 15.5, clearHeight: 3.6 },
        { edgeIndex: 4, distStart: 15.0, distEnd: 22.0, clearHeight: 3.6 },
      ],
      'g2000'
    );
    for (const [cx, cz] of [
      [-249, -25],
      [-231, -26],
      [-211, -26],
      [-197, -25],
    ] as const) {
      this.physics.addCylinder(cx, cz, 0.32, 0.056, 5.75, 'g2000_col');
    }
    this.physics.addCenteredBox(-252.74, 3.2, -12.19, 10.4, 6.4, 2.5, {
      rotationY: -0.1371,
      isRamp: true,
      rampAxis: 'x',
      rampDir: 1,
      blocksBullets: false,
      tag: 'g2000_stair',
    });
    this.physics.addCenteredBox(-246.55, 6.26, -11.33, 2.6, 0.28, 2.7, {
      rotationY: -0.1371,
      isPlatform: true,
      tag: 'g2000_landing',
    });
    this.physics.addCenteredBox(-235, 7.1, -26, 3.8, 1.4, 2.4, { rotationY: 0.05, tag: 'g2000_hvac' });
    this.physics.addCenteredBox(-215, 7.1, -26, 3.8, 1.4, 2.4, { rotationY: 0.05, tag: 'g2000_hvac' });

    const g1950Poly: [number, number][] = [
      [-256, 34],
      [-213, 45],
      [-185, 42],
      [-187, 17],
      [-237, 15],
      [-264, 20],
    ];
    this.physics.addPolygon(g1950Poly, -0.25, 0.056, 'g1950_floor', 'g1950_floor');
    this.physics.addPolygon(g1950Poly, 5.75, 6.4, 'g1950_roof', 'g1950_roof');
    this.physics.addHollowPolygonWalls(
      g1950Poly,
      0,
      6.4,
      0.45,
      [
        { edgeIndex: 1, distStart: 10.0, distEnd: 17.0, clearHeight: 3.6 },
        { edgeIndex: 2, distStart: 9.0, distEnd: 15.5, clearHeight: 3.6 },
        { edgeIndex: 3, distStart: 18.0, distEnd: 25.0, clearHeight: 3.6 },
      ],
      'g1950'
    );
    for (const [cx, cz] of [
      [-247, 26],
      [-229, 29],
      [-211, 30],
      [-197, 29],
    ] as const) {
      this.physics.addCylinder(cx, cz, 0.32, 0.056, 5.75, 'g1950_col');
    }
    this.physics.addCenteredBox(-248.18, 3.2, 15.8, 10.4, 6.4, 2.5, {
      rotationY: -2.9585,
      isRamp: true,
      rampAxis: 'x',
      rampDir: 1,
      blocksBullets: false,
      tag: 'g1950_stair',
    });
    this.physics.addCenteredBox(-254.33, 6.26, 16.94, 2.6, 0.28, 2.7, {
      rotationY: -2.9585,
      isPlatform: true,
      tag: 'g1950_landing',
    });
    this.physics.addCenteredBox(-235, 7.1, 30, 3.8, 1.4, 2.4, { rotationY: -0.1, tag: 'g1950_hvac' });
    this.physics.addCenteredBox(-215, 7.1, 30, 3.8, 1.4, 2.4, { rotationY: -0.1, tag: 'g1950_hvac' });

    // Central Courtyard planters & shade pergola
    this.physics.addCenteredBox(-241, 0.45, 2, 11.5, 0.9, 5.6, { tag: 'g2000_planter' });
    this.physics.addCenteredBox(-211, 0.45, 2, 11.5, 0.9, 5.6, { tag: 'g2000_planter' });
    for (const [px, pz] of [
      [-229.2, -1.2],
      [-220.8, -1.2],
      [-229.2, 5.2],
      [-220.8, 5.2],
    ] as const) {
      this.physics.addCylinder(px, pz, 0.16, 0, 3.7, 'g2000_pergola_post');
    }
    this.physics.addCenteredBox(-225, 3.84, 2, 8.8, 0.24, 6.8, { isPlatform: true, tag: 'g2000_pergola_roof' });

    // -----------------------------------------------------------------------
    // 13. Charleston Campus at (+28, 0, +134) — 4 Convex Hollow Wings + Parking Deck
    // -----------------------------------------------------------------------
    this.placeLandmarkMesh('charleston_campus', 28, 0, 134, 0);
    const charlWest: [number, number][] = [
      [-27, 161],
      [-6, 161],
      [-6, 107],
      [-27, 107],
    ];
    this.physics.addPolygon(charlWest, -0.25, 0.056, 'charl_w_floor', 'charl_w_floor');
    this.physics.addPolygon(charlWest, 5.75, 6.4, 'charl_w_roof', 'charl_w_roof');
    this.physics.addHollowPolygonWalls(
      charlWest,
      0,
      6.4,
      0.45,
      [
        { edgeIndex: 0, distStart: 7.2, distEnd: 13.8, clearHeight: 3.6 },
        { edgeIndex: 1, distStart: 23.0, distEnd: 30.2, clearHeight: 3.6 },
        { edgeIndex: 2, distStart: 7.2, distEnd: 13.8, clearHeight: 3.6 },
      ],
      'charl_w'
    );
    for (const cz of [120, 134, 148]) {
      this.physics.addCylinder(-16.5, cz, 0.32, 0.056, 5.75, 'charl_w_col');
    }
    this.physics.addCenteredBox(-4.75, 3.2, 152.66, 10.4, 6.4, 2.5, {
      rotationY: Math.PI / 2,
      isRamp: true,
      rampAxis: 'x',
      rampDir: 1,
      blocksBullets: false,
      tag: 'charl_w_stair',
    });
    this.physics.addCenteredBox(-4.75, 6.26, 146.41, 2.6, 0.28, 2.7, {
      rotationY: Math.PI / 2,
      isPlatform: true,
      tag: 'charl_w_landing',
    });

    const charlNorth: [number, number][] = [
      [9, 121],
      [66, 121],
      [66, 103],
      [9, 103],
    ];
    this.physics.addPolygon(charlNorth, -0.25, 0.056, 'charl_n_floor', 'charl_n_floor');
    this.physics.addPolygon(charlNorth, 5.75, 6.4, 'charl_n_roof', 'charl_n_roof');
    this.physics.addHollowPolygonWalls(
      charlNorth,
      0,
      6.4,
      0.45,
      [
        { edgeIndex: 0, distStart: 18.0, distEnd: 25.0, clearHeight: 3.6 },
        { edgeIndex: 2, distStart: 22.0, distEnd: 29.0, clearHeight: 3.6 },
        { edgeIndex: 3, distStart: 5.5, distEnd: 12.5, clearHeight: 3.6 },
      ],
      'charl_n'
    );
    for (const cx of [24, 42, 57]) {
      this.physics.addCylinder(cx, 112, 0.32, 0.056, 5.75, 'charl_n_col');
    }
    this.physics.addCenteredBox(16.95, 3.2, 122.25, 10.4, 6.4, 2.5, {
      rotationY: 0,
      isRamp: true,
      rampAxis: 'x',
      rampDir: 1,
      blocksBullets: false,
      tag: 'charl_n_stair',
    });
    this.physics.addCenteredBox(23.2, 6.26, 122.25, 2.6, 0.28, 2.7, {
      rotationY: 0,
      isPlatform: true,
      tag: 'charl_n_landing',
    });
    this.physics.addCenteredBox(27.5, 7.1, 112, 3.8, 1.4, 2.4, { tag: 'charl_n_hvac' });
    this.physics.addCenteredBox(47.5, 7.1, 112, 3.8, 1.4, 2.4, { tag: 'charl_n_hvac' });

    const charlSouth: [number, number][] = [
      [9, 165],
      [66, 165],
      [66, 147],
      [9, 147],
    ];
    this.physics.addPolygon(charlSouth, -0.25, 0.056, 'charl_s_floor', 'charl_s_floor');
    this.physics.addPolygon(charlSouth, 5.75, 6.4, 'charl_s_roof', 'charl_s_roof');
    this.physics.addHollowPolygonWalls(
      charlSouth,
      0,
      6.4,
      0.45,
      [
        { edgeIndex: 0, distStart: 22.0, distEnd: 29.0, clearHeight: 3.6 },
        { edgeIndex: 2, distStart: 38.0, distEnd: 45.0, clearHeight: 3.6 },
        { edgeIndex: 3, distStart: 5.5, distEnd: 12.5, clearHeight: 3.6 },
      ],
      'charl_s'
    );
    for (const cx of [24, 42, 57]) {
      this.physics.addCylinder(cx, 156, 0.32, 0.056, 5.75, 'charl_s_col');
    }
    this.physics.addCenteredBox(39.24, 3.2, 145.75, 10.4, 6.4, 2.5, {
      rotationY: Math.PI,
      isRamp: true,
      rampAxis: 'x',
      rampDir: 1,
      blocksBullets: false,
      tag: 'charl_s_stair',
    });
    this.physics.addCenteredBox(32.99, 6.26, 145.75, 2.6, 0.28, 2.7, {
      rotationY: Math.PI,
      isPlatform: true,
      tag: 'charl_s_landing',
    });
    this.physics.addCenteredBox(27.5, 7.1, 156, 3.8, 1.4, 2.4, { tag: 'charl_s_hvac' });
    this.physics.addCenteredBox(47.5, 7.1, 156, 3.8, 1.4, 2.4, { tag: 'charl_s_hvac' });

    const charlEastSpine: [number, number][] = [
      [49, 145],
      [66, 145],
      [66, 123],
      [49, 123],
    ];
    this.physics.addPolygon(charlEastSpine, -0.25, 0.056, 'charl_e_floor', 'charl_e_floor');
    this.physics.addPolygon(charlEastSpine, 5.75, 6.4, 'charl_e_roof', 'charl_e_roof');
    this.physics.addHollowPolygonWalls(
      charlEastSpine,
      0,
      6.4,
      0.45,
      [
        { edgeIndex: 0, distStart: 5.2, distEnd: 11.8, clearHeight: 3.6 },
        { edgeIndex: 2, distStart: 5.2, distEnd: 11.8, clearHeight: 3.6 },
        { edgeIndex: 3, distStart: 7.5, distEnd: 14.5, clearHeight: 3.6 },
      ],
      'charl_e'
    );
    this.physics.addCylinder(57.5, 134, 0.32, 0.056, 5.75, 'charl_e_col');

    // Adjacent East Modern Louvered Parking Deck (walkable +6.4m top deck)
    this.physics.addCenteredBox(76.0, 3.2, 134.0, 14.0, 6.4, 56.0, { tag: 'charl_parking_deck' });
    // Sunlit courtyard reflecting pool & flanking planter islands
    this.physics.addCenteredBox(28.0, 0.18, 134.0, 12.0, 0.36, 6.2, { blocksBullets: false, tag: 'charl_pool' });
    this.physics.addCenteredBox(16.5, 0.45, 134.0, 5.2, 0.9, 7.6, { tag: 'charl_planter' });
    this.physics.addCenteredBox(39.5, 0.45, 134.0, 5.2, 0.9, 7.6, { tag: 'charl_planter' });

    // -----------------------------------------------------------------------
    // 14. 1098 Alta / Huff Complex at (-108, 0, +126) — 3 Arched Hollow Wings
    // -----------------------------------------------------------------------
    this.placeLandmarkMesh('alta_complex', -108, 0, 126, 0);
    const altaNW: [number, number][] = [
      [-146, 118],
      [-105, 118],
      [-105, 99],
      [-146, 99],
    ];
    this.physics.addPolygon(altaNW, -0.25, 0.056, 'alta_nw_floor', 'alta_nw_floor');
    this.physics.addPolygon(altaNW, 5.75, 6.4, 'alta_nw_roof', 'alta_nw_roof');
    this.physics.addHollowPolygonWalls(
      altaNW,
      0,
      6.4,
      0.45,
      [
        { edgeIndex: 0, distStart: 16.0, distEnd: 23.0, clearHeight: 3.6 },
        { edgeIndex: 1, distStart: 5.5, distEnd: 13.5, clearHeight: 3.6 },
        { edgeIndex: 2, distStart: 16.0, distEnd: 23.0, clearHeight: 3.6 },
      ],
      'alta_nw'
    );
    this.physics.addCylinder(-134, 108.5, 0.32, 0.056, 5.75, 'alta_nw_col');
    this.physics.addCylinder(-116, 108.5, 0.32, 0.056, 5.75, 'alta_nw_col');

    const altaSW: [number, number][] = [
      [-146, 153],
      [-105, 153],
      [-105, 134],
      [-146, 134],
    ];
    this.physics.addPolygon(altaSW, -0.25, 0.056, 'alta_sw_floor', 'alta_sw_floor');
    this.physics.addPolygon(altaSW, 5.75, 6.4, 'alta_sw_roof', 'alta_sw_roof');
    this.physics.addHollowPolygonWalls(
      altaSW,
      0,
      6.4,
      0.45,
      [
        { edgeIndex: 0, distStart: 16.0, distEnd: 23.0, clearHeight: 3.6 },
        { edgeIndex: 1, distStart: 5.5, distEnd: 13.5, clearHeight: 3.6 },
        { edgeIndex: 2, distStart: 19.0, distEnd: 26.0, clearHeight: 3.6 },
      ],
      'alta_sw'
    );
    this.physics.addCylinder(-134, 143.5, 0.32, 0.056, 5.75, 'alta_sw_col');
    this.physics.addCylinder(-116, 143.5, 0.32, 0.056, 5.75, 'alta_sw_col');
    this.physics.addCenteredBox(-111.74, 3.2, 132.75, 10.4, 6.4, 2.5, {
      rotationY: Math.PI,
      isRamp: true,
      rampAxis: 'x',
      rampDir: 1,
      blocksBullets: false,
      tag: 'alta_sw_stair',
    });
    this.physics.addCenteredBox(-117.99, 6.26, 132.75, 2.6, 0.28, 2.7, {
      rotationY: Math.PI,
      isPlatform: true,
      tag: 'alta_sw_landing',
    });

    const altaEast: [number, number][] = [
      [-89, 151],
      [-70, 151],
      [-70, 101],
      [-89, 101],
    ];
    this.physics.addPolygon(altaEast, -0.25, 0.056, 'alta_e_floor', 'alta_e_floor');
    this.physics.addPolygon(altaEast, 5.75, 6.4, 'alta_e_roof', 'alta_e_roof');
    this.physics.addHollowPolygonWalls(
      altaEast,
      0,
      6.4,
      0.45,
      [
        { edgeIndex: 0, distStart: 6.2, distEnd: 12.8, clearHeight: 3.6 },
        { edgeIndex: 2, distStart: 6.2, distEnd: 12.8, clearHeight: 3.6 },
        { edgeIndex: 3, distStart: 21.0, distEnd: 29.0, clearHeight: 3.6 },
      ],
      'alta_e'
    );
    for (const cz of [113, 126, 139]) {
      this.physics.addCylinder(-79.5, cz, 0.32, 0.056, 5.75, 'alta_e_col');
    }
    this.physics.addCenteredBox(-90.25, 3.2, 109.1, 10.4, 6.4, 2.5, {
      rotationY: -Math.PI / 2,
      isRamp: true,
      rampAxis: 'x',
      rampDir: 1,
      blocksBullets: false,
      tag: 'alta_e_stair',
    });
    this.physics.addCenteredBox(-90.25, 6.26, 115.35, 2.6, 0.28, 2.7, {
      rotationY: -Math.PI / 2,
      isPlatform: true,
      tag: 'alta_e_landing',
    });
    // Garden court & Alta Ave planters
    this.physics.addCenteredBox(-125.5, 0.45, 126.0, 11.0, 0.9, 4.6, { tag: 'alta_planter' });
    for (const [px, pz] of [
      [-103.4, 108.5],
      [-103.4, 143.5],
      [-90.4, 108.5],
      [-90.4, 143.5],
    ] as const) {
      this.physics.addCenteredBox(px, 0.45, pz, 2.2, 0.9, 6.5, { tag: 'alta_planter' });
    }

    // -----------------------------------------------------------------------
    // 15. Shoreline East Offices (3 placements: Google 2015, CL2 Crittenden, 1395 Charleston)
    // -----------------------------------------------------------------------
    const shoreEastLocalPoly: [number, number][] = [
      [-27, 22],
      [27, 22],
      [33, 16],
      [33, -16],
      [27, -22],
      [-27, -22],
      [-33, -16],
      [-33, 16],
    ];
    const shoreEastDoors: PolygonDoorwaySpec[] = [
      { edgeIndex: 0, distStart: 23.0, distEnd: 31.0, clearHeight: 3.6 },
      { edgeIndex: 2, distStart: 12.5, distEnd: 19.5, clearHeight: 3.6 },
      { edgeIndex: 4, distStart: 23.0, distEnd: 31.0, clearHeight: 3.6 },
      { edgeIndex: 6, distStart: 12.5, distEnd: 19.5, clearHeight: 3.6 },
    ];
    const shoreEastCols: [number, number][] = [
      [-18, -9],
      [0, -9],
      [18, -9],
      [-18, 9],
      [0, 9],
      [18, 9],
    ];

    const placeShorelineEast = (tag: string, cx: number, cz: number, rotY: number): void => {
      this.placeLandmarkMesh('shoreline_east_office', cx, 0, cz, rotY);
      const cos = Math.cos(rotY);
      const sin = Math.sin(rotY);
      const toW = (lx: number, lz: number): [number, number] => [
        cx + lx * cos + lz * sin,
        cz - lx * sin + lz * cos,
      ];

      const worldPoly = shoreEastLocalPoly.map(([lx, lz]) => toW(lx, lz));
      this.physics.addPolygon(worldPoly, -0.25, 0.056, `${tag}_floor`, `${tag}_floor`);
      this.physics.addPolygon(worldPoly, 5.75, 6.4, `${tag}_roof`, `${tag}_roof`);
      this.physics.addHollowPolygonWalls(worldPoly, 0, 6.4, 0.45, shoreEastDoors, tag);

      for (const [lx, lz] of shoreEastCols) {
        const [wx, wz] = toW(lx, lz);
        this.physics.addCylinder(wx, wz, 0.32, 0.056, 5.75, `${tag}_col`);
      }

      const [rx, rz] = toW(15.42, -23.25);
      const [lx, lz] = toW(9.17, -23.25);
      const stairYaw = Math.PI + rotY;
      this.physics.addCenteredBox(rx, 3.2, rz, 10.4, 6.4, 2.5, {
        rotationY: stairYaw,
        isRamp: true,
        rampAxis: 'x',
        rampDir: 1,
        blocksBullets: false,
        tag: `${tag}_stair`,
      });
      this.physics.addCenteredBox(lx, 6.26, lz, 2.6, 0.28, 2.7, {
        rotationY: stairYaw,
        isPlatform: true,
        tag: `${tag}_landing`,
      });

      // Rooftop HVAC cover units
      for (const hx of [-10, 10]) {
        const [wx, wz] = toW(hx, 0);
        this.physics.addCenteredBox(wx, 7.1, wz, 3.8, 1.4, 2.4, { rotationY: rotY, tag: `${tag}_hvac` });
      }
    };

    placeShorelineEast('g2015', 234, -22, 0);
    placeShorelineEast('gcl2', 236, -140, Math.PI);
    placeShorelineEast('g1395', 234, 122, 0.06);
  }

  private placeLandmarkMesh(
    key:
      | 'b40_partnerplex'
      | 'b41'
      | 'b42'
      | 'b43'
      | 'skybridge'
      | 'volleyball_court'
      | 'stan_trex'
      | 'gradient_canopy'
      | 'orb_plaza'
      | 'shoreline_amphitheatre'
      | 'athletic_field'
      | 'google_2000_1950'
      | 'charleston_campus'
      | 'alta_complex'
      | 'shoreline_east_office',
    x: number,
    y: number,
    z: number,
    rotY: number
  ): void {
    const mesh = this.assets.instantiateMapAsset(key);
    if (!mesh) return;
    mesh.position.set(x, y, z);
    mesh.rotation.y = rotY;
    this.worldGroup.add(mesh);
  }

  /**
   * Batches repeated Blender props (Google Umbrellas, GBike racks, California Live Oaks,
   * Coastal Redwoods) into THREE.InstancedMesh objects to keep runtime draw calls <= 180!
   */
  private placeInstancedCampusProps(): void {
    // 1. Google Umbrella Bistro clusters around Stan Plaza, Charlie's Patio, Courtyard, and Gradient Canopy
    const umbrellas: InstancePlacement[] = [
      // Stan the T-Rex Plaza clusters
      { x: -41.5, z: -1.5, rotY: 0.4, scale: 1.0 },
      { x: -39.0, z: 5.5, rotY: 1.3, scale: 1.0 },
      { x: -44.0, z: 11.5, rotY: 2.2, scale: 1.0 },
      { x: -58.5, z: 10.0, rotY: 0.9, scale: 1.0 },
      { x: -60.5, z: -0.5, rotY: 2.7, scale: 1.0 },
      // Charlie's Café South Patio terrace
      { x: -52.0, z: -6.0, rotY: 0.2, scale: 1.0 },
      { x: -34.0, z: -1.5, rotY: 1.1, scale: 1.0 },
      { x: -24.5, z: 2.5, rotY: 1.9, scale: 1.0 },
      // West Courtyard / Volleyball overlook
      { x: -92.0, z: -6.5, rotY: 0.6, scale: 1.0 },
      { x: -90.0, z: 14.0, rotY: 2.4, scale: 1.0 },
      { x: -102.5, z: -3.5, rotY: 1.5, scale: 1.0 },
      // Partner Plex / Charleston Park terrace
      { x: 4.5, z: -6.0, rotY: 0.8, scale: 1.0 },
      { x: 4.0, z: 4.5, rotY: 2.1, scale: 1.0 },
      // Gradient Canopy West Patio / Huddle Entrance
      { x: 67.5, z: -5.5, rotY: 0.3, scale: 1.0 },
      { x: 68.0, z: 13.5, rotY: 1.7, scale: 1.0 },
      { x: 113.0, z: 52.0, rotY: 2.8, scale: 1.0 },
      // Outer 3× Campus Entry Plazas & Terraces (Shoreline Amphitheatre, Athletic Field, 2000/1950, Alta, Charleston, 2015)
      { x: 98.0, z: -144.0, rotY: 0.5, scale: 1.0 },
      { x: 96.0, z: -124.0, rotY: 1.6, scale: 1.0 },
      { x: 32.0, z: -112.0, rotY: 2.3, scale: 1.0 },
      { x: -202.0, z: -104.0, rotY: 0.4, scale: 1.0 },
      { x: -238.0, z: -104.0, rotY: 1.9, scale: 1.0 },
      { x: -174.0, z: -8.0, rotY: 0.9, scale: 1.0 },
      { x: -174.0, z: 14.0, rotY: 2.6, scale: 1.0 },
      { x: -126.0, z: 88.0, rotY: 0.3, scale: 1.0 },
      { x: -82.0, z: 88.0, rotY: 1.8, scale: 1.0 },
      { x: 28.0, z: 94.0, rotY: 1.1, scale: 1.0 },
      { x: 96.0, z: 126.0, rotY: 2.4, scale: 1.0 },
      { x: 96.0, z: 144.0, rotY: 0.7, scale: 1.0 },
      { x: 188.0, z: -14.0, rotY: 1.4, scale: 1.0 },
      { x: 188.0, z: -32.0, rotY: 2.9, scale: 1.0 },
    ];
    this.instantiateBatch('umbrella_bistro', umbrellas);
    for (const u of umbrellas) {
      const gy = this.physics.getTerrainHeight(u.x, u.z);
      this.physics.addCylinder(u.x, u.z, 0.72, gy, gy + 0.82, 'umbrella_table', true);
    }

    // 2. GBike Corrals across authentic campus entry plazas
    const gbikes: InstancePlacement[] = [
      { x: -124, z: -52, rotY: 0.15, scale: 1.05 },
      { x: -138, z: 6, rotY: Math.PI / 2, scale: 1.05 },
      { x: 6, z: -24, rotY: -0.4, scale: 1.05 },
      { x: -4, z: 44, rotY: Math.PI, scale: 1.05 },
      { x: 65, z: 3, rotY: Math.PI / 2, scale: 1.05 },
      { x: -58, z: 56, rotY: 0, scale: 1.05 },
      { x: 116, z: 55, rotY: 0.1, scale: 1.05 },
      // Outer 3× Campus GBike Hubs
      { x: 64, z: -108, rotY: 0.25, scale: 1.05 },
      { x: -178, z: -134, rotY: Math.PI / 2, scale: 1.05 },
      { x: -174, z: 6, rotY: Math.PI / 2, scale: 1.05 },
      { x: -62, z: 122, rotY: Math.PI / 2, scale: 1.05 },
      { x: 14, z: 92, rotY: 0, scale: 1.05 },
      { x: 188, z: -22, rotY: Math.PI / 2, scale: 1.05 },
      { x: 188, z: -140, rotY: Math.PI / 2, scale: 1.05 },
      { x: 188, z: 122, rotY: Math.PI / 2, scale: 1.05 },
    ];
    this.instantiateBatch('gbike_rack', gbikes);
    for (const g of gbikes) {
      const gy = this.physics.getTerrainHeight(g.x, g.z);
      this.physics.addCenteredBox(g.x, gy + 0.55, g.z, 3.6, 1.1, 1.5, {
        rotationY: g.rotY,
        tag: 'gbike_rack',
      });
    }

    // 3. Lush California Live Oak Groves (Charleston Park + North Shoreline + Perimeter)
    const oaks: InstancePlacement[] = [
      // Charleston Park core groves (+10..+52, -52..+50 — framing Art Garden, Outdoor Gym & Pergola!)
      { x: 14, z: -42, rotY: 0.5, scale: 1.05 },
      { x: 18, z: -46, rotY: 1.8, scale: 0.95 },
      { x: 40, z: -44, rotY: 2.9, scale: 1.12 },
      { x: 52, z: -46, rotY: 0.9, scale: 0.92 },
      { x: 16, z: -28, rotY: 2.1, scale: 1.08 },
      { x: 30, z: -30, rotY: 0.3, scale: 1.18 },
      { x: 44, z: -26, rotY: 1.4, scale: 0.98 },
      { x: 14, z: -14, rotY: 3.6, scale: 1.14 },
      { x: 44, z: -18, rotY: 4.2, scale: 1.02 },
      { x: 48, z: -12, rotY: 5.1, scale: 0.96 },
      { x: 14, z: 6, rotY: 1.2, scale: 1.05 },
      { x: 18, z: 12, rotY: 2.6, scale: 1.16 },
      { x: 42, z: 10, rotY: 0.7, scale: 1.04 },
      { x: 16, z: 24, rotY: 3.1, scale: 0.94 },
      { x: 46, z: 18, rotY: 4.8, scale: 1.12 },
      { x: 50, z: 26, rotY: 1.9, scale: 1.0 },
      { x: 22, z: 42, rotY: 0.4, scale: 1.08 },
      { x: 38, z: 44, rotY: 2.3, scale: 0.96 },
      { x: 52, z: 46, rotY: 3.9, scale: 1.05 },
      // North Shoreline Parkland (north of Amphitheatre Pkwy)
      { x: -115, z: -84, rotY: 0.6, scale: 1.15 },
      { x: -82, z: -90, rotY: 1.7, scale: 1.05 },
      { x: -34, z: -88, rotY: 2.8, scale: 1.2 },
      { x: -8, z: -88, rotY: 3.9, scale: 1.08 },
      { x: 32, z: -84, rotY: 5.0, scale: 1.12 },
      { x: 86, z: -86, rotY: 1.2, scale: 1.05 },
      { x: 135, z: -84, rotY: 2.5, scale: 1.15 },
      // South Charleston Rd Corridor & Alta/Huff Ave medians
      { x: -124, z: 86, rotY: 1.1, scale: 1.05 },
      { x: -86, z: 84, rotY: 2.4, scale: 1.12 },
      { x: -38, z: 88, rotY: 3.7, scale: 1.04 },
      { x: 12, z: 84, rotY: 0.8, scale: 1.16 },
      { x: 64, z: 86, rotY: 2.0, scale: 1.02 },
      { x: 112, z: 88, rotY: 4.5, scale: 1.08 },
      // Framing Gradient Canopy East/NE lawn (clear of Shoreline Blvd X=165.5 & canopy overhang)
      { x: 158, z: -48, rotY: 0.9, scale: 1.05 },
      { x: 146, z: -53, rotY: 2.2, scale: 1.1 },
      { x: 158, z: 38, rotY: 3.4, scale: 0.98 },
      // Subtle courtyard shade oak near B40/B43 east apron
      { x: -16, z: 12, rotY: 1.5, scale: 0.92 },
      // Bay Point Regional Shoreline Overlook hills (North outer ring)
      { x: -132, z: -124, rotY: 0.6, scale: 1.12 },
      { x: -112, z: -144, rotY: 1.7, scale: 1.16 },
      { x: -88, z: -122, rotY: 2.8, scale: 1.08 },
      { x: -66, z: -156, rotY: 3.9, scale: 1.2 },
      { x: -44, z: -128, rotY: 5.0, scale: 1.06 },
      { x: -22, z: -162, rotY: 0.9, scale: 1.14 },
      { x: -4, z: -122, rotY: 2.1, scale: 1.04 },
      { x: 12, z: -152, rotY: 3.4, scale: 1.1 },
      { x: -124, z: -168, rotY: 4.6, scale: 1.12 },
      { x: -82, z: -174, rotY: 1.3, scale: 1.15 },
      // NW Athletic Field & Western Charleston Rd outer parkland
      { x: -274, z: -158, rotY: 0.5, scale: 1.12 },
      { x: -266, z: -126, rotY: 2.0, scale: 1.04 },
      { x: -192, z: -168, rotY: 3.2, scale: 1.14 },
      { x: -236, z: -172, rotY: 4.5, scale: 1.08 },
      { x: -284, z: -46, rotY: 1.2, scale: 1.1 },
      { x: -284, z: 18, rotY: 2.7, scale: 1.06 },
      { x: -276, z: 96, rotY: 4.0, scale: 1.15 },
      { x: -252, z: 124, rotY: 5.2, scale: 1.08 },
      { x: -196, z: 104, rotY: 0.8, scale: 1.05 },
      { x: -184, z: 148, rotY: 2.4, scale: 1.12 },
      // South Campus Corridors (Alta / Charleston Campus / SE buffer)
      { x: -142, z: 164, rotY: 1.5, scale: 1.08 },
      { x: -54, z: 144, rotY: 3.1, scale: 1.04 },
      { x: -48, z: 106, rotY: 4.3, scale: 1.02 },
      { x: 102, z: 112, rotY: 0.7, scale: 1.1 },
      { x: 148, z: 148, rotY: 2.3, scale: 1.08 },
      { x: 144, z: 108, rotY: 3.8, scale: 1.05 },
      // East N Shoreline Blvd Office Park green buffers (clear of Stierlin/Crittenden/Shorebird)
      { x: 186, z: -84, rotY: 0.4, scale: 1.06 },
      { x: 212, z: -86, rotY: 1.9, scale: 1.12 },
      { x: 278, z: -84, rotY: 3.3, scale: 1.08 },
      { x: 284, z: -22, rotY: 4.8, scale: 1.1 },
      { x: 212, z: 42, rotY: 1.1, scale: 1.14 },
      { x: 280, z: 42, rotY: 2.6, scale: 1.06 },
    ];
    this.instantiateBatch('oak_tree', oaks);
    for (const o of oaks) {
      const gy = this.physics.getTerrainHeight(o.x, o.z);
      this.physics.addCylinder(o.x, o.z, 0.52 * o.scale, gy, gy + 4.2, 'oak_trunk', true);
    }

    // 4. Towering California Coastal Redwoods (Permanente Creek Trail + Perimeter Backdrop)
    const redwoods: InstancePlacement[] = [
      // West bank & trail along Permanente Creek (X ≈ -164 & -143, clear of Amphitheatre & Charleston bridges)
      { x: -164, z: -96, rotY: 0.4, scale: 1.05 },
      { x: -164, z: -85, rotY: 1.6, scale: 0.96 },
      { x: -164, z: -48, rotY: 2.8, scale: 1.12 },
      { x: -164, z: -22, rotY: 3.9, scale: 1.02 },
      { x: -164, z: 4, rotY: 5.1, scale: 1.15 },
      { x: -164, z: 24, rotY: 0.7, scale: 0.98 },
      { x: -164, z: 42, rotY: 2.1, scale: 1.08 },
      { x: -164, z: 84, rotY: 3.5, scale: 1.04 },
      { x: -143, z: -44, rotY: 1.1, scale: 0.94 },
      { x: -143, z: -10, rotY: 2.5, scale: 1.02 },
      { x: -143, z: 22, rotY: 4.0, scale: 0.96 },
      { x: -143, z: 50, rotY: 5.3, scale: 1.06 },
      // North Shoreline Redwood Grove
      { x: -136, z: -98, rotY: 0.9, scale: 1.14 },
      { x: -98, z: -100, rotY: 2.0, scale: 1.08 },
      { x: -62, z: -98, rotY: 3.2, scale: 1.16 },
      { x: -24, z: -100, rotY: 4.4, scale: 1.04 },
      { x: 16, z: -98, rotY: 5.6, scale: 1.12 },
      { x: 56, z: -96, rotY: 1.3, scale: 1.02 },
      { x: 112, z: -84, rotY: 2.7, scale: 1.14 },
      { x: 152, z: -94, rotY: 3.8, scale: 1.08 },
      // Charleston Park majestic anchor redwoods (framing Art Garden & Outdoor Gym perimeter)
      { x: 16, z: -22, rotY: 0.6, scale: 0.95 },
      { x: 46, z: 6, rotY: 2.4, scale: 0.98 },
      { x: 16, z: 40, rotY: 4.1, scale: 0.92 },
      // South perimeter redwoods
      { x: -104, z: 90, rotY: 1.4, scale: 1.08 },
      { x: -14, z: 98, rotY: 3.0, scale: 1.12 },
      { x: 146, z: 94, rotY: 4.7, scale: 1.06 },
      // Extended Permanente Creek N & S outer trail redwoods
      { x: -166, z: -174, rotY: 0.8, scale: 1.14 },
      { x: -166, z: -144, rotY: 2.1, scale: 1.08 },
      { x: -166, z: -116, rotY: 3.4, scale: 1.12 },
      { x: -142, z: -168, rotY: 4.6, scale: 1.1 },
      { x: -142, z: -132, rotY: 1.2, scale: 1.06 },
      { x: -166, z: 118, rotY: 2.5, scale: 1.12 },
      { x: -166, z: 152, rotY: 3.9, scale: 1.08 },
      { x: -166, z: 178, rotY: 5.1, scale: 1.14 },
      { x: -142, z: 114, rotY: 0.7, scale: 1.04 },
      { x: -142, z: 158, rotY: 2.2, scale: 1.1 },
      // Bay Point Overlook North Ridge & Shoreline Amphitheatre backdrop
      { x: -96, z: -180, rotY: 1.5, scale: 1.18 },
      { x: -36, z: -180, rotY: 3.0, scale: 1.16 },
      { x: 14, z: -178, rotY: 4.4, scale: 1.12 },
      { x: 112, z: -174, rotY: 0.6, scale: 1.14 },
      { x: 148, z: -162, rotY: 2.3, scale: 1.1 },
      // Far West & Far East Mountain View perimeter backdrop
      { x: -288, z: -140, rotY: 1.1, scale: 1.15 },
      { x: -286, z: 68, rotY: 2.8, scale: 1.12 },
      { x: -248, z: 166, rotY: 4.2, scale: 1.16 },
      { x: 284, z: -162, rotY: 0.9, scale: 1.14 },
      { x: 284, z: 14, rotY: 2.4, scale: 1.12 },
      { x: 284, z: 118, rotY: 3.8, scale: 1.1 },
      { x: 284, z: 176, rotY: 5.2, scale: 1.15 },
    ];
    this.instantiateBatch('redwood_tree', redwoods);
    for (const r of redwoods) {
      const gy = this.physics.getTerrainHeight(r.x, r.z);
      this.physics.addCylinder(r.x, r.z, 0.62 * r.scale, gy, gy + 6.5, 'redwood_trunk', true);
    }
  }

  /**
   * Places the 5 Google-themed outdoor park & defensive cover assets across the 3× campus:
   * - 3 Googleplex Outdoor Calisthenics Gyms (`park_outdoor_gym`, 14.0m × 11.0m)
   * - 3 Google Sculpture & Art Gardens (`park_art_garden`, 16.0m × 14.0m)
   * - 6 Google Outdoor Collaboration Pergolas (`park_google_pergola`, 9.5m × 6.5m)
   * - 28 Modular Garden Planter Walls (`garden_planter_wall`) & 14 Kinetic Sculpture Plinths (`sculpture_plinth`)
   * Every structure uses InstancedMesh batching and exact 1:1 rotated OBB/cylinder colliders.
   */
  private placeParkDefensesAndGardens(): void {
    this.parkPlazaLootSpots.length = 0;

    // Three.js Object3D.rotation.y (+rotY around +Y) maps local (lx, ly, lz) ->
    // world (cx + lx*cos(rotY) + lz*sin(rotY), gy + ly, cz - lx*sin(rotY) + lz*cos(rotY)),
    // matching PhysicsWorld.addCenteredBox(rotationY) 1:1.
    const toWorldXZ = (cx: number, cz: number, rotY: number, lx: number, lz: number): [number, number] => {
      const cos = Math.cos(rotY);
      const sin = Math.sin(rotY);
      return [cx + lx * cos + lz * sin, cz - lx * sin + lz * cos];
    };

    const addLocalBox = (
      cx: number,
      gy: number,
      cz: number,
      rotY: number,
      lx: number,
      ly: number,
      lz: number,
      sx: number,
      sy: number,
      sz: number,
      extra?: Partial<BoxCollider>
    ): void => {
      const [wx, wz] = toWorldXZ(cx, cz, rotY, lx, lz);
      this.physics.addCenteredBox(wx, gy + ly, wz, sx, sy, sz, {
        ...extra,
        rotationY: rotY + (extra?.rotationY ?? 0),
      });
    };

    const addLocalCylinder = (
      cx: number,
      gy: number,
      cz: number,
      rotY: number,
      lx: number,
      lz: number,
      radius: number,
      minY: number,
      maxY: number,
      tag: string,
      blocksBullets = true
    ): void => {
      const [wx, wz] = toWorldXZ(cx, cz, rotY, lx, lz);
      this.physics.addCylinder(wx, wz, radius, gy + minY, gy + maxY, tag, blocksBullets);
    };

    // Sample terrain height across a plaza footprint so sloped hillsides (Bay Point Overlook,
    // North Shoreline Grove, Charleston Park berms) neither poke grass through the walkable pad
    // nor float above the terrain (every GLB carries a -1.4m..-1.6m foundation skirt).
    const samplePlazaBaseY = (
      cx: number,
      cz: number,
      sx: number,
      sz: number,
      rotY: number,
      padHeight: number,
      isOctagon = false
    ): number => {
      const centerY = this.physics.getTerrainHeight(cx, cz);
      const octLimit = (sx + sz) * 0.5 - 2.75; // Exact match to park_art_garden.glb chamfer ch=2.75m
      let minY = centerY;
      let maxY = centerY;
      for (let ix = -3; ix <= 3; ix++) {
        const lx = (ix / 6) * sx;
        for (let iz = -3; iz <= 3; iz++) {
          const lz = (iz / 6) * sz;
          if (isOctagon && Math.abs(lx) + Math.abs(lz) > octLimit + 0.15) continue;
          const [wx, wz] = toWorldXZ(cx, cz, rotY, lx, lz);
          const h = this.physics.getTerrainHeight(wx, wz);
          if (h < minY) minY = h;
          if (h > maxY) maxY = h;
        }
      }
      // Guarantee padTop = baseY + padHeight clears the highest terrain triangle by >= 6cm,
      // while capping rise <= minY + 1.05m so -1.40m..-1.60m skirts stay deeply anchored underground.
      const desiredY = Math.max(centerY, maxY - padHeight + 0.06);
      const stepCapY = minY + 1.05;
      return Math.min(desiredY, stepCapY);
    };

    // -----------------------------------------------------------------------
    // A. 3 Googleplex Outdoor Calisthenics Gyms (14.0m × 11.0m, pad top +0.14m)
    // -----------------------------------------------------------------------
    const outdoorGyms: { name: string; x: number; z: number; rotY: number }[] = [
      { name: 'Charleston Outdoor Gym', x: 32, z: 30, rotY: 0 },
      // Placed cleanly north of Google Athletic Field bleachers (clear of curved Amphitheatre Pkwy & parking driveway!)
      { name: 'Athletic Outdoor Gym', x: -220, z: -168, rotY: 0 },
      { name: 'Eastside Outdoor Gym', x: 126, z: 126, rotY: Math.PI / 2 },
    ];
    const gymInstances: InstancePlacement[] = [];
    for (const g of outdoorGyms) {
      const gy = samplePlazaBaseY(g.x, g.z, 14.0, 11.0, g.rotY, 0.14, false);
      gymInstances.push({ x: g.x, y: gy, z: g.z, rotY: g.rotY, scale: 1.0 });

      // Solid foundation turf pad (maxY = gy + 0.14, buried skirt avoids hill ceiling-clamp edge cases)
      addLocalBox(g.x, gy, g.z, g.rotY, 0, -0.53, 0, 14.0, 1.34, 11.0, {
        blocksBullets: false,
        tag: 'gym_pad',
      });
      // Opposing NW & SE L-Shaped Defensive Retaining Walls (y = 0.14..1.29m)
      addLocalBox(g.x, gy, g.z, g.rotY, -3.8, 0.72, -5.05, 5.8, 1.15, 0.72, { tag: 'gym_wall' });
      addLocalBox(g.x, gy, g.z, g.rotY, -6.55, 0.72, -2.55, 0.72, 1.15, 4.6, { tag: 'gym_wall' });
      addLocalBox(g.x, gy, g.z, g.rotY, 3.8, 0.72, 5.05, 5.8, 1.15, 0.72, { tag: 'gym_wall' });
      addLocalBox(g.x, gy, g.z, g.rotY, 6.55, 0.72, 2.55, 0.72, 1.15, 4.6, { tag: 'gym_wall' });
      // 3-Tier Jumpable Plyo-Box Deck (both cover and climbable high-ground juke!)
      addLocalBox(g.x, gy, g.z, g.rotY, 3.4, 0.44, -2.2, 1.4, 0.6, 1.4, { tag: 'gym_plyo' });
      addLocalBox(g.x, gy, g.z, g.rotY, 3.4, 0.64, -0.6, 1.4, 1.0, 1.4, { tag: 'gym_plyo' });
      addLocalBox(g.x, gy, g.z, g.rotY, 3.4, 0.84, 1.0, 1.4, 1.4, 1.4, { tag: 'gym_plyo' });
      // Kettlebell/Dumbbell Rack & Weighted Sled/Bench cover
      addLocalBox(g.x, gy, g.z, g.rotY, -2.4, 0.68, 3.4, 3.4, 1.08, 0.85, { tag: 'gym_rack' });
      addLocalBox(g.x, gy, g.z, g.rotY, 1.2, 0.56, 3.2, 2.2, 0.84, 1.1, { tag: 'gym_bench' });
      // Calisthenics Rig 4 corner upright posts (open weave underneath/through the rig!)
      for (const lx of [-4.4, 0.0]) {
        for (const lz of [-1.5, 0.7]) {
          addLocalCylinder(g.x, gy, g.z, g.rotY, lx, lz, 0.14, 0.14, 3.09, 'gym_rig_post', true);
        }
      }

      // Tactical high-tier loot chest spot on open NE athletic turf under the shade sail
      const [lx, lz] = toWorldXZ(g.x, g.z, g.rotY, 1.2, -3.2);
      this.parkPlazaLootSpots.push({ x: lx, y: gy + 0.14, z: lz, highTier: true, landmark: g.name });
    }
    this.instantiateBatch('park_outdoor_gym', gymInstances);

    // -----------------------------------------------------------------------
    // B. 3 Google Sculpture & Art Gardens (16.0m × 14.0m, pad top +0.12m)
    // -----------------------------------------------------------------------
    const artGardens: { name: string; x: number; z: number; rotY: number }[] = [
      { name: 'Charleston Art Garden', x: 30, z: -8, rotY: 0 },
      { name: 'Bay Point Art Garden', x: -62, z: -138, rotY: 0.25 },
      { name: 'Creekside Art Garden', x: -226, z: 124, rotY: -0.2 },
    ];
    const gardenInstances: InstancePlacement[] = [];
    for (const ag of artGardens) {
      const gy = samplePlazaBaseY(ag.x, ag.z, 16.0, 14.0, ag.rotY, 0.12, true);
      gardenInstances.push({ x: ag.x, y: gy, z: ag.z, rotY: ag.rotY, scale: 1.0 });

      // Solid travertine octagonal plaza pad (maxY = gy + 0.12)
      addLocalBox(ag.x, gy, ag.z, ag.rotY, 0, -0.54, 0, 16.0, 1.32, 14.0, {
        blocksBullets: false,
        tag: 'garden_pad',
      });
      // Centerpiece Google 4-Color Sculpture Plinth (full standing cover!)
      addLocalBox(ag.x, gy, ag.z, ag.rotY, 0, 1.5, 0, 2.4, 3.0, 2.4, { tag: 'garden_monolith' });
      // 4 Pinwheel Staggered Limestone Cover Walls (1.22m tall)
      addLocalBox(ag.x, gy, ag.z, ag.rotY, -1.6, 0.73, -5.8, 5.4, 1.22, 0.76, { tag: 'garden_wall' });
      addLocalBox(ag.x, gy, ag.z, ag.rotY, 1.6, 0.73, 5.8, 5.4, 1.22, 0.76, { tag: 'garden_wall' });
      addLocalBox(ag.x, gy, ag.z, ag.rotY, -6.6, 0.73, 1.4, 0.76, 1.22, 4.8, { tag: 'garden_wall' });
      addLocalBox(ag.x, gy, ag.z, ag.rotY, 6.6, 0.73, -1.4, 0.76, 1.22, 4.8, { tag: 'garden_wall' });
      // 4 Raised Native-California Succulent & Lavender Planter Beds (0.95m tall)
      addLocalBox(ag.x, gy, ag.z, ag.rotY, -4.4, 0.6, -3.4, 2.6, 0.95, 1.5, { tag: 'garden_planter' });
      addLocalBox(ag.x, gy, ag.z, ag.rotY, 4.4, 0.6, -3.6, 2.6, 0.95, 1.5, { tag: 'garden_planter' });
      addLocalBox(ag.x, gy, ag.z, ag.rotY, -4.4, 0.6, 3.6, 2.6, 0.95, 1.5, { tag: 'garden_planter' });
      addLocalBox(ag.x, gy, ag.z, ag.rotY, 4.4, 0.6, 3.4, 2.6, 0.95, 1.5, { tag: 'garden_planter' });

      // 2 High-tier loot chests on opposite open travertine flanking lanes (clear of monolith & planters!)
      for (const [cxOff, czOff] of [
        [-3.2, 0.8],
        [3.2, -0.8],
      ] as const) {
        const [lx, lz] = toWorldXZ(ag.x, ag.z, ag.rotY, cxOff, czOff);
        this.parkPlazaLootSpots.push({ x: lx, y: gy + 0.12, z: lz, highTier: true, landmark: ag.name });
      }
    }
    this.instantiateBatch('park_art_garden', gardenInstances);

    // -----------------------------------------------------------------------
    // C. 6 Google Outdoor Collaboration Pergolas (9.5m × 6.5m, deck top +0.12m)
    // -----------------------------------------------------------------------
    const pergolas: { name: string; x: number; z: number; rotY: number }[] = [
      { name: 'North Shoreline Grove Pergola', x: -46, z: -86, rotY: 0 },
      { name: 'North Charleston Park Pergola', x: 28, z: -44, rotY: Math.PI },
      { name: 'West Bay Point Grove Pergola', x: -106, z: -130, rotY: 0.35 },
      { name: 'SW Creekside Lawn Pergola', x: -248, z: 92, rotY: -0.3 },
      { name: 'East Shoreline North Pergola', x: 228, z: -82, rotY: 0 },
      // Nudged cleanly south of Google 2015 surface parking bay (z=15.8..32.2)
      { name: 'East Shoreline South Pergola', x: 232, z: 42, rotY: Math.PI },
    ];
    const pergolaInstances: InstancePlacement[] = [];
    for (const pg of pergolas) {
      const gy = samplePlazaBaseY(pg.x, pg.z, 9.5, 6.5, pg.rotY, 0.12, false);
      pergolaInstances.push({ x: pg.x, y: gy, z: pg.z, rotY: pg.rotY, scale: 1.0 });

      // Timber-edged travertine deck pad (maxY = gy + 0.12)
      addLocalBox(pg.x, gy, pg.z, pg.rotY, 0, -0.54, 0, 9.5, 1.32, 6.5, {
        blocksBullets: false,
        tag: 'pergola_pad',
      });
      // Rear Full-Height Acoustic Privacy Screen Wall (standing hard cover!)
      addLocalBox(pg.x, gy, pg.z, pg.rotY, 0, 1.24, -2.85, 7.6, 2.24, 0.36, { tag: 'pergola_wall' });
      // West & East Built-In Bench Planters (waist cover)
      addLocalBox(pg.x, gy, pg.z, pg.rotY, -4.15, 0.66, 0.4, 0.95, 1.08, 3.6, { tag: 'pergola_planter' });
      addLocalBox(pg.x, gy, pg.z, pg.rotY, 4.15, 0.66, 0.4, 0.95, 1.08, 3.6, { tag: 'pergola_planter' });
      // Central Cedar Collaboration Table
      addLocalBox(pg.x, gy, pg.z, pg.rotY, 0, 0.54, 0.5, 3.8, 0.84, 1.35, { tag: 'pergola_table' });

      // Loot chest on the open +Z front deck right in front of the cedar table
      const [lx, lz] = toWorldXZ(pg.x, pg.z, pg.rotY, 0.0, 2.25);
      this.parkPlazaLootSpots.push({ x: lx, y: gy + 0.12, z: lz, highTier: false, landmark: pg.name });
    }
    this.instantiateBatch('park_google_pergola', pergolaInstances);

    // -----------------------------------------------------------------------
    // D. Modular Tree-Grove Cover Network (28 Planter Walls + 14 Sculpture Plinths)
    //    Verified >= 3.0m clear of every tree trunk and 100% clear of all roads/buildings!
    // -----------------------------------------------------------------------
    const planterWalls: InstancePlacement[] = [
      // Charleston Park flanks (4)
      { x: 11, z: -34, rotY: 0.35, scale: 1.0 },
      { x: 49, z: -34, rotY: -0.4, scale: 1.0 },
      { x: 13, z: 18, rotY: 1.35, scale: 1.0 },
      { x: 49, z: 13, rotY: -1.25, scale: 1.0 },
      // North Shoreline Parkland (5)
      { x: -104, z: -84, rotY: 0.2, scale: 1.0 },
      { x: -72, z: -88, rotY: -0.15, scale: 1.0 },
      { x: -18, z: -86, rotY: 0.1, scale: 1.0 },
      { x: 12, z: -84, rotY: -0.2, scale: 1.0 },
      { x: 96, z: -84, rotY: 0.15, scale: 1.0 },
      // Bay Point Overlook trails (4)
      { x: -122, z: -152, rotY: 0.4, scale: 1.0 },
      { x: -84, z: -156, rotY: -0.2, scale: 1.0 },
      { x: -36, z: -152, rotY: 0.3, scale: 1.0 },
      { x: -14, z: -124, rotY: -0.45, scale: 1.0 },
      // Permanente Creek Trail cover pockets (4)
      { x: -172, z: -32, rotY: 1.48, scale: 1.0 },
      { x: -174, z: 34, rotY: 1.62, scale: 1.0 },
      { x: -174, z: 118, rotY: 1.5, scale: 1.0 },
      { x: -180, z: -98, rotY: 0.3, scale: 1.0 },
      // South Charleston Corridor & SE/SW Park (5)
      { x: -110, z: 84, rotY: 0.1, scale: 1.0 },
      { x: -44, z: 84, rotY: -0.1, scale: 1.0 },
      { x: 20, z: 84, rotY: 0.15, scale: 1.0 },
      { x: 122, z: 88, rotY: -0.15, scale: 1.0 },
      { x: -266, z: 134, rotY: 0.45, scale: 1.0 },
      // NW Athletic Field Lawn & East Shoreline buffers (6)
      { x: -264, z: -142, rotY: 1.45, scale: 1.0 },
      { x: -178, z: -146, rotY: 1.6, scale: 1.0 },
      { x: 194, z: -84, rotY: 0.1, scale: 1.0 },
      { x: 264, z: -84, rotY: -0.1, scale: 1.0 },
      { x: 196, z: 44, rotY: 0.2, scale: 1.0 },
      { x: 266, z: 44, rotY: -0.2, scale: 1.0 },
    ];
    this.instantiateBatch('garden_planter_wall', planterWalls);
    for (const pw of planterWalls) {
      const gy = this.physics.getTerrainHeight(pw.x, pw.z);
      this.physics.addCenteredBox(pw.x, gy + 0.61, pw.z, 5.2, 1.22, 1.55, {
        rotationY: pw.rotY,
        tag: 'park_planter_wall',
      });
    }

    const sculpturePlinths: InstancePlacement[] = [
      // Charleston Park (2)
      { x: 16, z: 48, rotY: 0.4, scale: 1.0 },
      { x: 36, z: -24, rotY: 0.8, scale: 1.0 },
      // North Shoreline & Bay Point (4)
      { x: 128, z: -86, rotY: 0.25, scale: 1.0 },
      { x: 8, z: -142, rotY: 0.6, scale: 1.0 },
      { x: -64, z: -112, rotY: -0.3, scale: 1.0 },
      { x: -134, z: -86, rotY: 0.5, scale: 1.0 },
      // Permanente Creek & SW Park (4)
      { x: -174, z: -82, rotY: 0.2, scale: 1.0 },
      { x: -174, z: 86, rotY: -0.4, scale: 1.0 },
      { x: -192, z: 132, rotY: 0.35, scale: 1.0 },
      { x: -214, z: 92, rotY: 0.7, scale: 1.0 },
      // SE Campus Park & South Corridor (2)
      { x: 144, z: 102, rotY: -0.25, scale: 1.0 },
      { x: 112, z: 152, rotY: 0.5, scale: 1.0 },
      // NW Athletic & East Shoreline (2)
      { x: -252, z: -168, rotY: 0.3, scale: 1.0 },
      { x: 256, z: -94, rotY: -0.5, scale: 1.0 },
    ];
    this.instantiateBatch('sculpture_plinth', sculpturePlinths);
    for (const sp of sculpturePlinths) {
      const gy = this.physics.getTerrainHeight(sp.x, sp.z);
      this.physics.addCenteredBox(sp.x, gy + 1.1, sp.z, 1.85, 2.2, 1.85, {
        rotationY: sp.rotY,
        tag: 'park_sculpture_plinth',
      });
    }
  }

  /**
   * Furnishes all hollow ground-floor office interiors (B40 Charlie's Café & Partner Plex,
   * B41 SWE Hub, B42 Design Studio, B43 Open Office Floor, enriched Gradient Canopy atrium,
   * and under-Skybridge breezeway) using InstancedMesh batching + tactical cover colliders.
   */
  private placeOfficeInteriors(): void {
    const FLOOR_Y = 0.056;
    const GC_Y = 0.4;
    const SKY_Y = 0.03;

    const deskPods: InstancePlacement[] = [
      // B40 — Charlie's Coworking & Partner Plex SWE pods
      { x: -51.5, y: FLOOR_Y, z: -16.0, rotY: 0.18, scale: 1.0 },
      { x: -39.5, y: FLOOR_Y, z: -25.5, rotY: 0.2, scale: 1.0 },
      { x: -11.5, y: FLOOR_Y, z: -12.5, rotY: -0.15, scale: 1.0 },
      // B41 — SWE Engineering Hub
      { x: -121.0, y: FLOOR_Y, z: -24.5, rotY: 0.65, scale: 1.0 },
      { x: -102.5, y: FLOOR_Y, z: -26.5, rotY: -0.4, scale: 1.0 },
      // B42 — Design Studio & SWE workstations
      { x: -123.5, y: FLOOR_Y, z: 9.5, rotY: 0.05, scale: 1.0 },
      { x: -108.5, y: FLOOR_Y, z: 25.5, rotY: 1.45, scale: 1.0 },
      // B43 — Sweeping Open Office Floor
      { x: -90.5, y: FLOOR_Y, z: 35.5, rotY: 0.14, scale: 1.0 },
      { x: -80.5, y: FLOOR_Y, z: 37.5, rotY: 0.14, scale: 1.0 },
      { x: -66.5, y: FLOOR_Y, z: 25.5, rotY: -0.15, scale: 1.0 },
      { x: -29.5, y: FLOOR_Y, z: 42.5, rotY: 0.05, scale: 1.0 },
      // Gradient Canopy Coworking Atrium
      { x: 102.5, y: GC_Y, z: -18.0, rotY: 0.15, scale: 1.0 },
      { x: 123.5, y: GC_Y, z: -18.0, rotY: -0.15, scale: 1.0 },
    ];

    const conferencePods: InstancePlacement[] = [
      // B40 Partner Plex executive conference pod
      { x: -15.5, y: FLOOR_Y, z: -21.0, rotY: 0.35, scale: 1.0 },
      // B41 Glass Conference Room
      { x: -112.5, y: FLOOR_Y, z: -42.5, rotY: -0.25, scale: 1.0 },
      // B42 Design Review Conference Room
      { x: -111.5, y: FLOOR_Y, z: 36.5, rotY: 2.95, scale: 1.0 },
      // B43 Central & East Meet Conference Pods
      { x: -66.5, y: FLOOR_Y, z: 40.5, rotY: 0.14, scale: 1.0 },
      { x: -31.5, y: FLOOR_Y, z: 29.5, rotY: -0.22, scale: 1.0 },
      // Gradient Canopy Showcase Conference Pods
      { x: 135.0, y: GC_Y, z: -6.5, rotY: 1.57, scale: 1.0 },
      { x: 102.5, y: GC_Y, z: 25.5, rotY: 0.12, scale: 1.0 },
    ];

    const microkitchenBars: InstancePlacement[] = [
      // B40 — Charlie's Café West Espresso Counter & North Serving Bar
      { x: -75.0, y: FLOOR_Y, z: -27.0, rotY: 0.12, scale: 1.0 },
      { x: -47.5, y: FLOOR_Y, z: -31.0, rotY: 0.18, scale: 1.0 },
      // B41 — SWE Coffee Bar
      { x: -122.5, y: FLOOR_Y, z: -38.5, rotY: 0.4, scale: 1.0 },
      // B42 — Studio Microkitchen
      { x: -114.5, y: FLOOR_Y, z: 9.0, rotY: 0.05, scale: 1.0 },
      // B43 — Central Microkitchen
      { x: -56.5, y: FLOOR_Y, z: 41.5, rotY: 3.14, scale: 1.0 },
      // Gradient Canopy North Hospitality Bar
      { x: 113.0, y: GC_Y, z: -20.5, rotY: 0.0, scale: 1.0 },
    ];

    const loungeNooks: InstancePlacement[] = [
      // B40 — Charlie's Café Dining Lounges & Partner Plex Waiting Lounge
      { x: -66.0, y: FLOOR_Y, z: -18.0, rotY: -0.25, scale: 1.0 },
      { x: -43.5, y: FLOOR_Y, z: -13.5, rotY: 2.95, scale: 1.0 },
      { x: -23.0, y: FLOOR_Y, z: -22.0, rotY: 0.4, scale: 1.0 },
      // B42 — Sunny Workspace Lounge
      { x: -124.5, y: FLOOR_Y, z: 34.5, rotY: -0.3, scale: 1.0 },
      // B43 — Entry & Central Breakout Lounges
      { x: -90.0, y: FLOOR_Y, z: 26.5, rotY: 0.25, scale: 1.0 },
      { x: -55.5, y: FLOOR_Y, z: 30.5, rotY: -0.2, scale: 1.0 },
      // Gradient Canopy Huddle & South Atrium Lounges
      { x: 92.5, y: GC_Y, z: 15.5, rotY: 0.55, scale: 1.0 },
      { x: 121.0, y: GC_Y, z: 26.5, rotY: -2.45, scale: 1.0 },
      // Under-Skybridge Breezeway Seating Nooks
      { x: -73.5, y: SKY_Y, z: -5.0, rotY: 1.42, scale: 1.0 },
      { x: -72.5, y: SKY_Y, z: 9.0, rotY: -1.72, scale: 1.0 },
    ];

    const whiteboardWalls: InstancePlacement[] = [
      // B40 — Café & Partner Plex flanking cover dividers
      { x: -72.5, y: FLOOR_Y, z: -20.5, rotY: 0.4, scale: 1.0 },
      { x: -44.5, y: FLOOR_Y, z: -22.0, rotY: 1.4, scale: 1.0 },
      { x: -19.5, y: FLOOR_Y, z: -10.5, rotY: 0.12, scale: 1.0 },
      // B41 — Entry sightline cover
      { x: -109.5, y: FLOOR_Y, z: -20.5, rotY: 1.2, scale: 1.0 },
      // B42 — West studio flanking cover
      { x: -124.0, y: FLOOR_Y, z: 23.0, rotY: 0.25, scale: 1.0 },
      // B43 — Lobby & East aisle flanking cover
      { x: -60.5, y: FLOOR_Y, z: 25.0, rotY: 0.15, scale: 1.0 },
      { x: -45.0, y: FLOOR_Y, z: 28.0, rotY: 1.5, scale: 1.0 },
      // Gradient Canopy Central Exhibition Dividers
      { x: 106.5, y: GC_Y, z: 1.5, rotY: 0.65, scale: 1.0 },
      { x: 119.5, y: GC_Y, z: 2.0, rotY: -0.65, scale: 1.0 },
      // Under-Skybridge Breezeway Planter/Whiteboard Flanking Cover
      { x: -76.8, y: SKY_Y, z: 2.2, rotY: 1.42, scale: 1.0 },
      { x: -69.2, y: SKY_Y, z: 1.8, rotY: 1.42, scale: 1.0 },
    ];

    this.placeInstancedGroup('desk_pod', deskPods);
    this.placeInstancedGroup('conference_pod', conferencePods);
    this.placeInstancedGroup('microkitchen_bar', microkitchenBars);
    this.placeInstancedGroup('lounge_nook', loungeNooks);
    this.placeInstancedGroup('whiteboard_wall', whiteboardWalls);

    // Waist-high tactical cover (~1.05m) on SWE desk pods for crisp crouch-peeking over monitors
    for (const p of deskPods) {
      const baseY = p.y ?? FLOOR_Y;
      this.physics.addCenteredBox(p.x, baseY + 0.525, p.z, 3.35 * p.scale, 1.05, 2.05 * p.scale, {
        rotationY: p.rotY,
        tag: 'office_desk_pod',
      });
    }

    // Two-part colliders on conference pods: waist-high oval birch table + full-height Meet accent wall (-X)
    for (const p of conferencePods) {
      const baseY = p.y ?? FLOOR_Y;
      const cos = Math.cos(p.rotY);
      const sin = Math.sin(p.rotY);
      const tableLx = 0.56 * p.scale;
      this.physics.addCenteredBox(
        p.x + tableLx * cos,
        baseY + 0.41,
        p.z - tableLx * sin,
        3.4 * p.scale,
        0.82,
        1.75 * p.scale,
        { rotationY: p.rotY, tag: 'office_conf_table' }
      );
      const wallLx = -2.35 * p.scale;
      this.physics.addCenteredBox(
        p.x + wallLx * cos,
        baseY + 1.25,
        p.z - wallLx * sin,
        0.52 * p.scale,
        2.5,
        3.06 * p.scale,
        { rotationY: p.rotY, tag: 'office_conf_wall' }
      );
    }

    // Two-part colliders on microkitchen bars: waist-high marble espresso bar (-X) + tall cooler fridge (+X)
    for (const p of microkitchenBars) {
      const baseY = p.y ?? FLOOR_Y;
      const cos = Math.cos(p.rotY);
      const sin = Math.sin(p.rotY);
      const barLx = -0.52 * p.scale;
      this.physics.addCenteredBox(
        p.x + barLx * cos,
        baseY + 0.525,
        p.z - barLx * sin,
        3.95 * p.scale,
        1.05,
        1.25 * p.scale,
        { rotationY: p.rotY, tag: 'office_microkitchen_bar' }
      );
      const fridgeLx = 1.94 * p.scale;
      const fridgeLz = 0.16 * p.scale;
      this.physics.addCenteredBox(
        p.x + fridgeLx * cos + fridgeLz * sin,
        baseY + 1.04,
        p.z - fridgeLx * sin + fridgeLz * cos,
        0.98 * p.scale,
        2.08,
        0.84 * p.scale,
        { rotationY: p.rotY, tag: 'office_microkitchen_cooler' }
      );
    }

    // Waist-high crouch cover (~0.90m) on modular lounge sofas & coffee tables
    for (const p of loungeNooks) {
      const baseY = p.y ?? FLOOR_Y;
      this.physics.addCenteredBox(p.x, baseY + 0.45, p.z, 3.65 * p.scale, 0.9, 2.6 * p.scale, {
        rotationY: p.rotY,
        tag: 'office_lounge_nook',
      });
    }

    // Full standing height (1.85m) tactical flanking cover on mobile whiteboards & indoor planters
    for (const p of whiteboardWalls) {
      const baseY = p.y ?? FLOOR_Y;
      this.physics.addCenteredBox(p.x, baseY + 0.925, p.z, 2.6 * p.scale, 1.85, 0.7 * p.scale, {
        rotationY: p.rotY,
        tag: 'office_whiteboard_wall',
      });
    }
  }

  private placeInstancedGroup(assetKey: MapAssetKey, placements: InstancePlacement[]): void {
    this.instantiateBatch(assetKey, placements);
  }

  private instantiateBatch(
    assetKey: MapAssetKey,
    placements: InstancePlacement[]
  ): void {
    const template = this.assets.getMapAssetTemplate(assetKey);
    if (!template || placements.length === 0) return;

    template.updateMatrixWorld(true);
    const meshes: THREE.Mesh[] = [];
    template.traverse((obj) => {
      if ((obj as THREE.Mesh).isMesh) {
        meshes.push(obj as THREE.Mesh);
      }
    });

    const dummy = new THREE.Object3D();
    const instanceMatrix = new THREE.Matrix4();

    for (const srcMesh of meshes) {
      const inst = new THREE.InstancedMesh(srcMesh.geometry, srcMesh.material, placements.length);
      inst.castShadow = srcMesh.castShadow;
      inst.receiveShadow = srcMesh.receiveShadow;
      inst.name = `Instanced_${assetKey}_${srcMesh.name}`;

      for (let i = 0; i < placements.length; i++) {
        const p = placements[i];
        const groundY = p.y ?? this.physics.getTerrainHeight(p.x, p.z);
        dummy.position.set(p.x, groundY, p.z);
        dummy.rotation.set(0, p.rotY, 0);
        dummy.scale.setScalar(p.scale);
        dummy.updateMatrix();
        instanceMatrix.multiplyMatrices(dummy.matrix, srcMesh.matrixWorld);
        inst.setMatrixAt(i, instanceMatrix);
      }
      inst.instanceMatrix.needsUpdate = true;
      inst.computeBoundingSphere();
      this.worldGroup.add(inst);
    }
  }

  private buildLandmarksMetadata(): void {
    this.landmarks.push(
      // Core Inner Googleplex (B40–B43 Quad, Charleston Park, Gradient Canopy, The Orb)
      { id: 'stan_plaza', name: 'Stan the T-Rex Plaza', x: -51, z: 4, radius: 18, color: '#fbbc04', highTier: true },
      { id: 'b40', name: "B40 · Charlie's & Partner Plex", x: -41, z: -21, radius: 34, color: '#ea4335', highTier: true },
      { id: 'b41', name: 'Building 41', x: -112, z: -31, radius: 22, color: '#4285f4' },
      { id: 'b42', name: 'Building 42', x: -117, z: 23, radius: 22, color: '#0f766e' },
      { id: 'b43', name: 'Building 43 · Solar Roof', x: -58, z: 33, radius: 32, color: '#f59e0b', highTier: true },
      { id: 'skybridge', name: 'Central Glass Skybridge', x: -73, z: 2, radius: 18, color: '#60a5fa', highTier: true },
      { id: 'volleyball', name: 'Sand Volleyball Court', x: -91, z: 4, radius: 14, color: '#f59e0b' },
      { id: 'charleston_park', name: 'Charleston Park', x: 28, z: -4, radius: 38, color: '#34a853' },
      { id: 'joaquin_rd', name: 'Joaquin Road', x: 64, z: 0, radius: 18, color: '#94a3b8' },
      { id: 'gradient_canopy', name: 'Gradient Canopy · Huddle', x: 113, z: 4, radius: 46, color: '#38bdf8', highTier: true },
      { id: 'orb_plaza', name: 'The Orb Plaza', x: 152, z: 60, radius: 14, color: '#a855f7', highTier: true },
      { id: 'permanente_creek', name: 'Permanente Creek Trail', x: -152, z: 0, radius: 20, color: '#22c55e' },
      { id: 'amphitheatre_pkwy', name: 'Amphitheatre Pkwy', x: -20, z: -72, radius: 30, color: '#64748b' },
      { id: 'charleston_rd', name: 'Charleston Rd Corridor', x: -10, z: 72, radius: 30, color: '#64748b' },
      // Expanded 3× Mountain View Campus Ring (600m × 380m)
      { id: 'shoreline_amphitheatre', name: 'Shoreline Amphitheatre', x: 58, z: -148, radius: 38, color: '#f8fafc', highTier: true },
      { id: 'athletic_field', name: 'Google Athletic Field', x: -220, z: -134, radius: 36, color: '#22c55e' },
      { id: 'bay_point_overlook', name: 'Bay Point Shoreline Overlook', x: -62, z: -144, radius: 42, color: '#84cc16' },
      { id: 'parking_lot_c', name: 'Shoreline Parking Lot C', x: 118, z: -112, radius: 26, color: '#64748b' },
      { id: 'google_2000_1950', name: 'Google 2000 · 1950', x: -225, z: 2, radius: 46, color: '#3b82f6', highTier: true },
      { id: 'alta_complex', name: '1098 Alta · Huff Complex', x: -108, z: 126, radius: 38, color: '#0ea5e9' },
      { id: 'charleston_campus', name: 'Charleston Campus', x: 28, z: 134, radius: 52, color: '#f59e0b', highTier: true },
      { id: 'google_2015', name: 'Google 2015 · Stierlin Ct', x: 234, z: -22, radius: 36, color: '#6366f1', highTier: true },
      { id: 'google_cl2', name: 'Google CL2 · Crittenden', x: 236, z: -140, radius: 36, color: '#14b8a6' },
      { id: 'google_1395', name: 'Google 1395 · Charleston', x: 234, z: 122, radius: 36, color: '#ec4899' },
      { id: 'shoreline_blvd', name: 'N Shoreline Blvd', x: 168, z: 0, radius: 24, color: '#94a3b8' },
      // Signature Googleplex Outdoor Art Gardens & Calisthenics Gyms
      { id: 'charleston_art_garden', name: 'Charleston Art Garden', x: 30, z: -8, radius: 18, color: '#34a853', highTier: true },
      { id: 'charleston_gym', name: 'Charleston Outdoor Gym', x: 32, z: 30, radius: 16, color: '#4285f4' },
      { id: 'athletic_gym', name: 'Athletic Outdoor Gym', x: -220, z: -168, radius: 16, color: '#4285f4' },
      { id: 'bay_point_garden', name: 'Bay Point Art Garden', x: -62, z: -138, radius: 18, color: '#84cc16', highTier: true },
      { id: 'creekside_garden', name: 'Creekside Art Garden', x: -226, z: 124, radius: 18, color: '#34a853', highTier: true },
      { id: 'eastside_gym', name: 'Eastside Outdoor Gym', x: 126, z: 126, radius: 16, color: '#4285f4' }
    );
  }

  private buildLootAndDropPoints(): void {
    const addSpot = (x: number, z: number, highTier: boolean, landmark: string, forcedY?: number) => {
      // currentY=3.2 + step=0.5 reaches up to 3.7m (handles Shoreline Amphitheatre bowl tiers up to 2.72m
      // while staying cleanly below +4.2m Skybridge deck and +6.4m building rooftops!)
      const y = forcedY ?? this.physics.getSupportHeight(x, z, 3.2, 0.25, 0.5);
      this.lootSpots.push({ x, y, z, highTier, landmark });
    };

    // Stan the T-Rex Plaza (High-tier hot drop!)
    addSpot(-51, -2.5, true, 'Stan the T-Rex Plaza');
    addSpot(-51, 10.5, true, 'Stan the T-Rex Plaza');
    addSpot(-44, 4, true, 'Stan the T-Rex Plaza');
    addSpot(-58, 4, true, 'Stan the T-Rex Plaza');

    // Charlie's Café Patio & B40 Indoor Office Floor + Rooftop (+6.4m)
    addSpot(-48, -7, true, "B40 · Charlie's Café");
    addSpot(-35, -3.5, true, "B40 · Charlie's Café");
    addSpot(-18, -1, false, "B40 · Partner Plex");
    addSpot(-75.5, -21.5, true, "B40 · Charlie's Café West", 0.056);
    addSpot(-63.5, -28.0, false, "B40 · Charlie's Café", 0.056);
    addSpot(-53.5, -28.0, true, "B40 · Charlie's Café", 0.056);
    addSpot(-47.5, -22.0, false, "B40 · Charlie's Commons", 0.056);
    addSpot(-34.0, -13.0, true, "B40 · Charlie's Lobby", 0.056);
    addSpot(-23.5, -14.5, false, "B40 · Partner Plex", 0.056);
    addSpot(-8.0, -17.5, true, "B40 · Partner Plex Suite", 0.056);
    addSpot(-68, -22, true, 'B40 Rooftop', 6.4);
    addSpot(-42, -16, true, 'B40 Rooftop', 6.4);
    addSpot(-22, -20, true, 'B40 Rooftop', 6.4);
    addSpot(-6, -15, true, 'B40 Rooftop', 6.4);

    // Building 41 Ground + Indoor SWE Hub + Rooftop (+6.4m)
    addSpot(-106, -10, false, 'Building 41');
    addSpot(-132, -32, false, 'Building 41');
    addSpot(-112, -52, false, 'Building 41');
    addSpot(-116.5, -29.0, true, 'B41 · SWE Floor', 0.056);
    addSpot(-107.0, -28.5, false, 'B41 · SWE Floor', 0.056);
    addSpot(-117.5, -42.0, true, 'B41 · Coffee Bar', 0.056);
    addSpot(-104.5, -39.5, false, 'B41 · Conference Wing', 0.056);
    addSpot(-116, -26, true, 'B41 Rooftop', 6.4);
    addSpot(-106, -37, true, 'B41 Rooftop', 6.4);

    // Building 42 Ground + Indoor Design Studio + Rooftop (+6.4m)
    addSpot(-100, 14, false, 'Building 42');
    addSpot(-118, 47, false, 'Building 42');
    addSpot(-136, 20, false, 'Building 42');
    addSpot(-118.0, 14.5, false, 'B42 · North Studio', 0.056);
    addSpot(-113.5, 22.5, true, 'B42 · Design Floor', 0.056);
    addSpot(-121.0, 29.0, false, 'B42 · Lounge', 0.056);
    addSpot(-117.5, 38.0, true, 'B42 · South Studio', 0.056);
    addSpot(-116, 16, true, 'B42 Rooftop', 6.4);
    addSpot(-119, 32, true, 'B42 Rooftop', 6.4);

    // Building 43 Ground + Sweeping Open Office Floor + Solar Rooftop (+6.4m)
    addSpot(-58, 15, false, 'Building 43');
    addSpot(-24, 21, false, 'Building 43');
    addSpot(-5, 38, false, 'B43 SE Parking');
    addSpot(-87.5, 31.0, false, 'B43 · West Open Floor', 0.056);
    addSpot(-76.5, 26.5, true, 'B43 · NW Lobby', 0.056);
    addSpot(-69.5, 34.5, false, 'B43 · Central Floor', 0.056);
    addSpot(-53.0, 25.0, true, 'B43 · NE Atrium', 0.056);
    addSpot(-43.5, 39.5, true, 'B43 · East Suite', 0.056);
    addSpot(-27.5, 36.0, false, 'B43 · East Lobby', 0.056);
    addSpot(-80, 32, true, 'B43 Solar Roof', 6.4);
    addSpot(-55, 29, true, 'B43 Solar Roof', 6.4);
    addSpot(-34, 38, true, 'B43 Solar Roof', 6.4);

    // Central Glass Skybridge (Elevated +4.2m deck & under-bridge courtyard)
    addSpot(-73, 2, true, 'Central Glass Skybridge', 4.2);
    addSpot(-72, -8, true, 'Central Glass Skybridge', 4.2);
    addSpot(-74, 12, true, 'Central Glass Skybridge', 4.2);
    addSpot(-74, 2, false, 'Under Skybridge');

    // Sand Volleyball Court
    addSpot(-95, 4, false, 'Sand Volleyball Court');
    addSpot(-86, 4, true, 'Sand Volleyball Court');
    addSpot(-91, -4, false, 'Sand Volleyball Court');

    // Charleston Park Oak Groves & Winding Paths
    addSpot(12, -32, false, 'Charleston Park');
    addSpot(26, -36, false, 'Charleston Park');
    addSpot(38, -18, true, 'Charleston Park');
    addSpot(18, -4, false, 'Charleston Park');
    addSpot(32, 16, true, 'Charleston Park');
    addSpot(18, 32, false, 'Charleston Park');
    addSpot(46, 36, false, 'Charleston Park');
    addSpot(48, -2, false, 'Charleston Park');

    // Gradient Canopy (Google Visitor Experience & Huddle Café — High-Tier!)
    addSpot(113, 4, true, 'Gradient Canopy Atrium', 0.4);
    addSpot(108, 18, true, 'Huddle Café', 0.4);
    addSpot(98, 4, true, 'Gradient Canopy West', 0.4);
    addSpot(128, 4, true, 'Gradient Canopy East', 0.4);
    addSpot(113, -16, true, 'Gradient Canopy North', 0.4);
    addSpot(113, 24, false, 'Gradient Canopy South', 0.4);
    addSpot(94.0, -13.5, true, 'Gradient Canopy · NW Pavilion', 0.4);
    addSpot(132.0, -13.5, true, 'Gradient Canopy · NE Showcase', 0.4);
    addSpot(128.0, 19.0, true, 'Gradient Canopy · Amphitheater', 0.4);
    addSpot(76, 4, false, 'Gradient Canopy Patio');
    addSpot(113, 50, false, 'Visitor Experience Plaza');

    // The Orb Plaza
    addSpot(147, 56, true, 'The Orb Plaza', 0.2);
    addSpot(156, 63, true, 'The Orb Plaza', 0.2);

    // Permanente Creek Trail, Amphitheatre Pkwy, & Charleston Rd Corridor
    addSpot(-148, -42, false, 'Permanente Creek Trail');
    addSpot(-148, 2, false, 'Permanente Creek Trail');
    addSpot(-148, 44, false, 'Permanente Creek Trail');
    addSpot(-75, -62, false, 'Amphitheatre Pkwy');
    addSpot(28, -62, false, 'Amphitheatre Pkwy');
    addSpot(-68, 60, false, 'Charleston Rd');
    addSpot(34, 62, false, 'Charleston Rd');

    // --- EXPANDED 3× MOUNTAIN VIEW CAMPUS LOOT CHEST SPOTS (+67 spots -> 150 total!) ---

    // Shoreline Amphitheatre (+58, -148) & Parking Lot C (+118, -112)
    addSpot(50.6, -159.9, true, 'Shoreline Amphitheatre · Stage', 1.22);
    addSpot(43.2, -156.8, true, 'Shoreline Amphitheatre · Stage West', 1.22);
    addSpot(57.8, -163.0, true, 'Shoreline Amphitheatre · Stage East', 1.22);
    addSpot(55.0, -152.5, false, 'Shoreline Amphitheatre · Orchestra Pit', 0.16);
    addSpot(63.0, -140.0, true, 'Shoreline Amphitheatre · Seating Bowl');
    addSpot(49.5, -133.0, false, 'Shoreline Amphitheatre · West Bowl');
    addSpot(73.0, -147.0, false, 'Shoreline Amphitheatre · East Bowl');
    addSpot(70.5, -127.0, true, 'Shoreline Amphitheatre · Concourse', 0.16);
    addSpot(118.0, -112.0, false, 'Shoreline Parking Lot C');

    // Bay Point Regional Shoreline Overlook (-62, -144) & North Creek Trail
    addSpot(-62.0, -149.5, true, 'Bay Point Shoreline Overlook');
    addSpot(-102.0, -142.0, false, 'Bay Point Overlook · West Ridge');
    addSpot(-24.0, -138.0, false, 'Bay Point Overlook · East Trail');
    addSpot(-64.0, -170.0, true, 'Bay Point Overlook · North Bluff');
    addSpot(-146.0, -126.0, false, 'Permanente Creek · North Footbridge');

    // Google Athletic Recreation Field (-220, -134)
    addSpot(-220.0, -134.0, true, 'Google Athletic Field · Center Pitch', 0.062);
    addSpot(-245.0, -134.0, false, 'Google Athletic Field · West Goal', 0.062);
    addSpot(-195.0, -134.0, false, 'Google Athletic Field · East Goal', 0.062);
    addSpot(-232.0, -115.1, true, 'Google Athletic Field · West Dugout', 0.14);
    addSpot(-208.0, -115.1, true, 'Google Athletic Field · East Dugout', 0.14);
    addSpot(-234.0, -150.5, false, 'Google Athletic Field · NW Bleachers', 0.062);
    addSpot(-206.0, -150.5, false, 'Google Athletic Field · NE Bleachers', 0.062);

    // Google 2000 (North) & Google 1950 (South) Complex (-225, +2)
    addSpot(-225.0, 2.0, true, 'Google 2000 · 1950 Courtyard', 0.036);
    addSpot(-178.0, 2.0, false, 'Google 2000 · Creek Bridge Plaza');
    addSpot(-254.0, -25.0, false, 'Google 2000 · West Floor', 0.056);
    addSpot(-220.0, -20.0, true, 'Google 2000 · Central Lobby', 0.056);
    addSpot(-194.0, -26.0, false, 'Google 2000 · East Floor', 0.056);
    addSpot(-244.0, -29.0, true, 'Google 2000 · Solar Rooftop', 6.4);
    addSpot(-206.0, -28.0, true, 'Google 2000 · East Rooftop', 6.4);
    addSpot(-245.0, 29.0, false, 'Google 1950 · West Floor', 0.056);
    addSpot(-218.0, 27.0, true, 'Google 1950 · Central Lobby', 0.056);
    addSpot(-195.0, 31.0, false, 'Google 1950 · East Floor', 0.056);
    addSpot(-244.0, 30.0, true, 'Google 1950 · Solar Rooftop', 6.4);
    addSpot(-206.0, 30.0, true, 'Google 1950 · East Rooftop', 6.4);

    // 1098 Alta / Huff Complex (-108, +126)
    addSpot(-114.0, 126.0, true, '1098 Alta · Garden Courtyard', 0.036);
    addSpot(-125.0, 108.5, false, '1098 Alta · NW Floor', 0.056);
    addSpot(-125.0, 143.5, true, '1098 Alta · SW Floor', 0.056);
    addSpot(-130.0, 147.5, true, '1098 Alta · SW White Roof', 6.4);
    addSpot(-79.5, 118.0, false, '1098 Alta · East Wing North', 0.056);
    addSpot(-79.5, 134.0, false, '1098 Alta · East Wing South', 0.056);
    addSpot(-79.5, 118.0, true, '1098 Alta · East Rooftop', 6.4);
    addSpot(-97.0, 126.0, false, 'Alta Ave Promenade');

    // Charleston Campus (+28, +134)
    addSpot(28.0, 127.0, true, 'Charleston Campus · Courtyard North', 0.036);
    addSpot(28.0, 141.0, false, 'Charleston Campus · Courtyard South', 0.036);
    addSpot(-16.5, 125.0, false, 'Charleston Campus · West Wing North', 0.056);
    addSpot(-16.5, 142.0, true, 'Charleston Campus · West Wing South', 0.056);
    addSpot(-16.5, 126.0, true, 'Charleston Campus · West Rooftop', 6.4);
    addSpot(33.0, 112.0, true, 'Charleston Campus · North Wing Floor', 0.056);
    addSpot(36.0, 116.5, true, 'Charleston Campus · North Rooftop', 6.4);
    addSpot(33.0, 156.0, false, 'Charleston Campus · South Wing Floor', 0.056);
    addSpot(36.0, 151.5, true, 'Charleston Campus · South Rooftop', 6.4);
    addSpot(57.5, 128.0, true, 'Charleston Campus · East Spine Lobby', 0.056);
    addSpot(76.0, 134.0, true, 'Charleston Campus · Parking Deck Roof', 6.4);

    // Google 2015 / Stierlin Ct (+234, -22)
    addSpot(216.0, -22.0, false, 'Google 2015 · West Floor', 0.056);
    addSpot(234.0, -22.0, true, 'Google 2015 · Central Atrium', 0.056);
    addSpot(252.0, -22.0, false, 'Google 2015 · East Floor', 0.056);
    addSpot(234.0, 2.5, false, 'Google 2015 · South Arcade', 0.036);
    addSpot(234.0, -30.0, true, 'Google 2015 · Solar Rooftop', 6.4);

    // Google CL2 Crittenden (+236, -140)
    addSpot(218.0, -140.0, false, 'Google CL2 · West Floor', 0.056);
    addSpot(236.0, -140.0, true, 'Google CL2 · Central Atrium', 0.056);
    addSpot(254.0, -140.0, false, 'Google CL2 · East Floor', 0.056);
    addSpot(236.0, -164.5, false, 'Google CL2 · North Arcade', 0.036);
    addSpot(236.0, -132.0, true, 'Google CL2 · Solar Rooftop', 6.4);

    // Google 1395 Charleston / SB10 (+234, +122)
    addSpot(216.0, 123.0, false, 'Google 1395 · West Floor', 0.056);
    addSpot(234.0, 122.0, true, 'Google 1395 · Central Atrium', 0.056);
    addSpot(252.0, 121.0, false, 'Google 1395 · East Floor', 0.056);
    addSpot(235.5, 146.5, false, 'Google 1395 · South Arcade', 0.036);
    addSpot(234.0, 114.0, true, 'Google 1395 · Solar Rooftop', 6.4);

    // Outdoor Art Gardens, Calisthenics Gyms & Collaboration Pergolas (+15 tactical spots -> 165 total!)
    for (const spot of this.parkPlazaLootSpots) {
      addSpot(spot.x, spot.z, spot.highTier, spot.landmark, spot.y);
    }

    // 20 Perimeter Glider Drop-In Points (y = 135m, evenly spaced around the 600m × 380m campus ring facing inward)
    const dropCount = 20;
    for (let i = 0; i < dropCount; i++) {
      const ang = (i / dropCount) * Math.PI * 2;
      const rx = 262;
      const rz = 162;
      const x = Math.cos(ang) * rx;
      const z = Math.sin(ang) * rz;
      // Yaw = 0 faces -Z; forward = (-sin(yaw), 0, -cos(yaw)) -> point toward campus center (0, 0)
      const heading = Math.atan2(x, z);
      this.gliderDropPoints.push({
        x,
        y: GAME_CONSTANTS.SKY_DROP_ALTITUDE,
        z,
        heading,
      });
    }

    // Prime Supply Drop landing coordinates across open inner & outer 3× Mountain View campus zones
    const supplyCoords: [number, number, string][] = [
      // Core Googleplex zones
      [30, 12, 'Charleston Park Lawn'],
      [-51, 14, 'Stan Plaza South'],
      [-86, -4, 'Quad West Courtyard'],
      [64, -18, 'Joaquin Road Overlook'],
      [96, -34, 'Gradient Canopy North Lawn'],
      // 6 Outer 3× Mountain View campus Supply Drop zones
      [58, -114, 'Shoreline Amphitheatre Concourse'],
      [-220, -134, 'Google Athletic Field Pitch'],
      [-62, -153, 'Bay Point Shoreline Overlook'],
      [-225, 9, 'Google 2000 · 1950 Courtyard'],
      [28, 127, 'Charleston Campus Plaza'],
      [194, -22, 'Google 2015 · Shoreline Plaza'],
    ];
    for (const [sx, sz, lm] of supplyCoords) {
      this.supplyDropSpots.push({
        x: sx,
        y: this.physics.getSupportHeight(sx, sz, 2.0, 0.5, 0.5),
        z: sz,
        landmark: lm,
      });
    }
  }

  private buildStormVisuals(): {
    wall: THREE.Mesh;
    wallMat: THREE.ShaderMaterial;
    ring: THREE.Mesh;
  } {
    // Translucent shimmering purple Storm Cylinder scaled for 135m Sky-Drop & 365m outer radius
    const wallGeo = new THREE.CylinderGeometry(1, 1, 185, 96, 1, true);
    wallGeo.translate(0, 90, 0);
    const wallMat = new THREE.ShaderMaterial({
      transparent: true,
      depthWrite: false,
      side: THREE.DoubleSide,
      uniforms: {
        uTime: { value: 0 },
        uColorA: { value: new THREE.Color('#7c3aed') },
        uColorB: { value: new THREE.Color('#c084fc') },
      },
      vertexShader: /* glsl */ `
        varying vec2 vUv;
        varying float vY;
        void main() {
          vUv = uv;
          vY = position.y;
          gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        }
      `,
      fragmentShader: /* glsl */ `
        uniform float uTime;
        uniform vec3 uColorA;
        uniform vec3 uColorB;
        varying vec2 vUv;
        varying float vY;
        void main() {
          float wave = sin(vUv.x * 64.0 + uTime * 2.2) * 0.5 + 0.5;
          float band = sin(vY * 0.45 - uTime * 3.4) * 0.5 + 0.5;
          float groundGlow = exp(-max(vY, 0.0) * 0.12);
          float topFade = 1.0 - smoothstep(125.0, 180.0, vY);
          vec3 col = mix(uColorA, uColorB, 0.35 * wave + 0.35 * band + 0.4 * groundGlow);
          float alpha = (0.14 + 0.10 * band + 0.28 * groundGlow) * topFade;
          gl_FragColor = vec4(col, alpha);
        }
      `,
    });
    const wall = new THREE.Mesh(wallGeo, wallMat);
    wall.name = 'StormWall';
    wall.renderOrder = 10;
    wall.scale.set(365, 1, 365);
    this.worldGroup.add(wall);

    // Bright purple ground perimeter ring
    const ringGeo = new THREE.RingGeometry(0.988, 1.012, 128);
    ringGeo.rotateX(-Math.PI / 2);
    const ringMat = new THREE.MeshBasicMaterial({
      color: 0xd8b4fe,
      transparent: true,
      opacity: 0.85,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    const ring = new THREE.Mesh(ringGeo, ringMat);
    ring.name = 'StormGroundRing';
    ring.position.y = 0.22;
    ring.scale.set(365, 1, 365);
    this.worldGroup.add(ring);

    this.disposables.push(wallGeo, wallMat, ringGeo, ringMat);
    return { wall, wallMat, ring };
  }

  /**
   * Freezes static world matrices once after campus placement so Three.js skips thousands
   * of per-frame matrix multiplications across terrain, 19 landmarks, and instanced props.
   */
  private freezeStaticWorldMatrices(): void {
    this.worldGroup.updateMatrixWorld(true);

    const dynamicRoots = new Set<THREE.Object3D>([
      this.stormWall,
      this.stormRing,
      this.sunLight,
      this.sunLight.target,
      this.activeIndoorLight,
    ]);

    // Keep worldGroup.matrixWorldAutoUpdate = true so dynamic children still update automatically
    this.worldGroup.matrixAutoUpdate = false;

    for (const child of this.worldGroup.children) {
      if (dynamicRoots.has(child)) {
        child.matrixAutoUpdate = true;
        child.matrixWorldAutoUpdate = true;
        continue;
      }
      child.traverse((obj) => {
        obj.matrixAutoUpdate = false;
        obj.matrixWorldAutoUpdate = false;
      });
    }
  }

  /**
   * Updates per-frame GPU performance focus around the active player/camera coordinates:
   * 1. Centers the tight ±92m directional sun shadow frustum snapped to 2.0m texel steps.
   * 2. Repositions and smoothly tints the single reusable indoor PointLight to the nearest
   *    office/atrium zone within `distance + 12m` (or turns it off when outdoors/high up).
   */
  public updatePerformanceFocus(px: number, py: number, pz: number): void {
    // 1. 2.0m texel-snapped player-centered shadow frustum (prevents shadow-edge shimmer)
    const sx = Math.round(px / 2) * 2;
    const sz = Math.round(pz / 2) * 2;
    if (sx !== this.lastSunSnapX || sz !== this.lastSunSnapZ) {
      this.lastSunSnapX = sx;
      this.lastSunSnapZ = sz;
      this.sunLight.target.position.set(sx, 0, sz);
      this.sunLight.position.set(sx + 115, 138, sz + 82);
      this.sunLight.target.updateMatrixWorld();
      this.sunLight.updateMatrixWorld();
    }

    // 2. Single dynamic indoor PointLight positioned at the nearest active interior zone
    let bestZone: IndoorLightZone | null = null;
    let bestDistSq = Infinity;
    const zones = this.indoorLightZones;
    for (let i = 0; i < zones.length; i++) {
      const z = zones[i];
      const dx = px - z.x;
      const dy = py - z.y;
      const dz = pz - z.z;
      const dSq = dx * dx + dy * dy + dz * dz;
      const reach = z.distance + 12;
      if (dSq <= reach * reach && dSq < bestDistSq) {
        bestDistSq = dSq;
        bestZone = z;
      }
    }

    if (bestZone) {
      const dist = Math.sqrt(bestDistSq);
      const edgeFade = dist <= bestZone.distance ? 1 : Math.max(0, 1 - (dist - bestZone.distance) / 12);
      const targetIntensity = bestZone.intensity * edgeFade;
      this.indoorTargetPos.set(bestZone.x, bestZone.y, bestZone.z);
      this.indoorTargetColor.setHex(bestZone.colorHex);

      const shouldSnap =
        this.activeIndoorLight.intensity <= 0.05 ||
        this.activeIndoorLight.position.distanceToSquared(this.indoorTargetPos) > 3600;

      if (shouldSnap) {
        this.activeIndoorLight.position.copy(this.indoorTargetPos);
        this.activeIndoorLight.color.copy(this.indoorTargetColor);
        this.activeIndoorLight.distance = bestZone.distance;
        this.activeIndoorLight.intensity = targetIntensity;
      } else {
        this.activeIndoorLight.position.lerp(this.indoorTargetPos, 0.2);
        this.activeIndoorLight.color.lerp(this.indoorTargetColor, 0.2);
        this.activeIndoorLight.distance += (bestZone.distance - this.activeIndoorLight.distance) * 0.2;
        this.activeIndoorLight.intensity += (targetIntensity - this.activeIndoorLight.intensity) * 0.22;
      }
    } else {
      this.activeIndoorLight.intensity = 0;
    }
  }

  /**
   * Resizes the directional sun shadow map render target live for Performance/Balanced/High presets.
   */
  public setShadowMapSize(size: number): void {
    const clamped = Math.max(256, Math.min(4096, Math.round(size)));
    if (this.sunLight.shadow.mapSize.x === clamped && this.sunLight.shadow.mapSize.y === clamped) {
      return;
    }
    this.sunLight.shadow.mapSize.set(clamped, clamped);
    if (this.sunLight.shadow.map) {
      this.sunLight.shadow.map.dispose();
      this.sunLight.shadow.map = null;
    }
    this.sunLight.shadow.needsUpdate = true;
  }

  public updateStormVisual(centerX: number, centerZ: number, radius: number, elapsedSec: number): void {
    const r = Math.max(0.5, radius);
    this.stormWall.position.set(centerX, 0, centerZ);
    this.stormWall.scale.set(r, 1, r);
    this.stormWallMat.uniforms.uTime.value = elapsedSec;

    this.stormRing.position.set(centerX, 0.22, centerZ);
    this.stormRing.scale.set(r, 1, r);
  }

  public getZoneName(x: number, z: number): string {
    let bestName = 'Googleplex Campus';
    let bestScore = Infinity;
    for (const lm of this.landmarks) {
      const dist = Math.hypot(x - lm.x, z - lm.z);
      const score = dist / lm.radius;
      if (score < bestScore && dist <= lm.radius * 1.45) {
        bestScore = score;
        bestName = lm.name;
      }
    }
    return bestName;
  }

  public dispose(): void {
    this.scene.remove(this.worldGroup);
    if (this.sunLight?.shadow?.map) {
      this.sunLight.shadow.map.dispose();
      this.sunLight.shadow.map = null;
    }
    for (const d of this.disposables) {
      d.dispose();
    }
    this.disposables.length = 0;
    if (this.pmremTarget) {
      this.pmremTarget.dispose();
      this.pmremTarget = null;
    }
  }
}

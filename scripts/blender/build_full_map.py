#!/usr/bin/env python3
"""
Workspace Royale — Complete 3x Mountain View Googleplex Terrain & Full Campus Master Builder
Blender 5.3.0 headless generator producing:
  1. public/assets/map/googleplex_terrain.glb  (600m x 380m 3x terrain, roads, creek, bridges, paths, curbs)
  2. docs/googleplex_full_campus.glb           (all-in-one assembled 3x campus: terrain + all 19 landmarks/props)
  3. docs/googleplex_full_campus.blend         (master Blender file with organized Collections & lighting)
  4. docs/previews/googleplex_full_map.png     (BLENDER_EEVEE dual-panel Aerial 3/4 + Top-Down Orthographic QA)

Coordinate System (exact match to Three.js export_yup=True and WORKSPACE_ROYALE_SPEC.md §10):
  - Three.js / Spec world: X in [-300, +300] (West -> East, 600m), Z in [-190, +190] (North -> South, 380m), Y up.
  - Inner Core Preserved:  X in [-170, +170], Z in [-110, +110] at exact existing coordinates!
  - Blender world:         bx = tx, by = -tz (North = +Y, South = -Y), bz = ty (Up = +Z).

Usage:
    blender --background --python scripts/blender/build_full_map.py
    blender --background --python scripts/blender/build_full_map.py -- --samples 24 --mirror-dir /path/to/dir
"""

import argparse
import math
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import bpy
import bmesh
import numpy as np
from mathutils import Euler, Matrix, Vector

# ---------------------------------------------------------------------------
# Paths & Constants
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
ASSETS_ROOT = PROJECT_ROOT / "public" / "assets"
MAP_ASSETS_DIR = ASSETS_ROOT / "map"
DOCS_DIR = PROJECT_ROOT / "docs"
PREVIEWS_DIR = DOCS_DIR / "previews"

TERRAIN_GLB_PATH = MAP_ASSETS_DIR / "googleplex_terrain.glb"
FULL_CAMPUS_GLB_PATH = DOCS_DIR / "googleplex_full_campus.glb"
FULL_CAMPUS_BLEND_PATH = DOCS_DIR / "googleplex_full_campus.blend"
FULL_MAP_PREVIEW_PATH = PREVIEWS_DIR / "googleplex_full_map.png"

# Full 3x Mountain View Campus Bounds (600m x 380m = 228,000 m^2)
HALF_W = 300.0   # X in [-300, +300]
HALF_D = 190.0   # Z in [-190, +190]

# Preserved Inner Core Reference Constants (exact match to original 340m x 220m core!)
INNER_W = 170.0
INNER_D = 110.0
SVG_PX_PER_M = 2.9

CREEK_X = -156.0
TRAIL_X = -150.0
SHORELINE_X = 168.0      # Full N-S N Shoreline Blvd (Z in [-190, +190])
STIERLIN_Z = -65.0       # Eastern E-W Stierlin Ct (X in [+168, +300])
CRITTENDEN_Z = -108.0    # Eastern E-W Crittenden Ln (X in [+168, +300])
SHOREBIRD_Z = 160.0      # Eastern E-W Shorebird Way (X in [+168, +300])
PLYMOUTH_Z = 180.0       # Southern E-W Plymouth St (X in [-150, +168])
CHARL_EAST_ACCESS_X = 92.0  # Charleston Campus east parking-deck access road


# ---------------------------------------------------------------------------
# Color & Math Utilities
# ---------------------------------------------------------------------------
def srgb_to_linear(c):
    def conv(v):
        if v <= 0.04045:
            return v / 12.92
        return ((v + 0.055) / 1.055) ** 2.4

    if isinstance(c, (int, float)):
        return conv(float(c))
    if len(c) == 3:
        return (conv(c[0]), conv(c[1]), conv(c[2]), 1.0)
    return (conv(c[0]), conv(c[1]), conv(c[2]), float(c[3]))


def hex_to_linear(h, alpha=1.0):
    h = h.lstrip("#")
    r = int(h[0:2], 16) / 255.0
    g = int(h[2:4], 16) / 255.0
    b = int(h[4:6], 16) / 255.0
    return srgb_to_linear((r, g, b, alpha))


def smoothstep(e0, e1, x):
    if e0 == e1:
        return 1.0 if x >= e1 else 0.0
    t = max(0.0, min(1.0, (x - e0) / (e1 - e0)))
    return t * t * (3.0 - 2.0 * t)


def smoothstep_np(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def w2b(tx, tz, ty=0.0):
    """Convert Three.js/Spec (tx, tz, ty_up) -> Blender (bx=tx, by=-tz, bz=ty_up)."""
    return Vector((float(tx), -float(tz), float(ty)))


def svg_to_world(sx, sy):
    """Convert original inner SVG pixel (sx, sy) -> Three.js (tx, tz)."""
    return ((sx - 560.0) / SVG_PX_PER_M, (sy - 385.0) / SVG_PX_PER_M)


def quad_bezier(p0, p1, p2, t):
    u = 1.0 - t
    return (
        u * u * p0[0] + 2.0 * u * t * p1[0] + t * t * p2[0],
        u * u * p0[1] + 2.0 * u * t * p1[1] + t * t * p2[1],
    )


def sample_polyline_smooth(pts, samples_per_seg=8):
    """Smooth Catmull-Rom interpolation through 2D (tx, tz) control points."""
    if len(pts) < 2:
        return list(pts)
    ext = [pts[0]] + list(pts) + [pts[-1]]
    out = []
    for i in range(1, len(ext) - 2):
        p0, p1, p2, p3 = ext[i - 1], ext[i], ext[i + 1], ext[i + 2]
        n = samples_per_seg
        for k in range(n):
            t = k / float(n)
            t2 = t * t
            t3 = t2 * t
            x = 0.5 * (
                (2.0 * p1[0])
                + (-p0[0] + p2[0]) * t
                + (2.0 * p0[0] - 5.0 * p1[0] + 4.0 * p2[0] - p3[0]) * t2
                + (-p0[0] + 3.0 * p1[0] - 3.0 * p2[0] + p3[0]) * t3
            )
            z = 0.5 * (
                (2.0 * p1[1])
                + (-p0[1] + p2[1]) * t
                + (2.0 * p0[1] - 5.0 * p1[1] + 4.0 * p2[1] - p3[1]) * t2
                + (-p0[1] + 3.0 * p1[1] - 3.0 * p2[1] + p3[1]) * t3
            )
            out.append((x, z))
    out.append(pts[-1])
    return out


# ---------------------------------------------------------------------------
# Analytic Campus Road & Path Curves (Three.js X, Z — single source of truth)
# ---------------------------------------------------------------------------

# Inner Amphitheatre Pkwy: 2 exact quadratic Bezier curves preserved verbatim in X in [-170, +170]
AMPH_P0 = svg_to_world(67.0, 175.0)    # (-170.0, -72.41)
AMPH_P1 = svg_to_world(290.0, 216.0)   # (-93.10, -58.28)
AMPH_P2 = svg_to_world(520.0, 232.0)   # (-13.79, -52.76)
AMPH_P3 = svg_to_world(740.0, 218.0)   # (+62.07, -57.59)
AMPH_P4 = svg_to_world(1053.0, 190.0)  # (+170.0, -67.24)

# West extension of Amphitheatre Pkwy curving WNW from (-170,-72.41) to NW Charleston bend (-282,-104) & edge (-300,-110)
AMPH_WEST_CTRL = [(-300.0, -110.2), (-282.0, -104.0), (-248.0, -91.5), (-210.0, -80.2), AMPH_P0]
AMPH_WEST_POLY = sample_polyline_smooth(AMPH_WEST_CTRL, samples_per_seg=8)


def _solve_quad_x(x0, x1, x2, tx):
    a = x0 - 2.0 * x1 + x2
    b = 2.0 * (x1 - x0)
    c = x0 - tx
    if abs(a) < 1e-6:
        return max(0.0, min(1.0, -c / (b if abs(b) > 1e-6 else 1.0)))
    disc = max(0.0, b * b - 4.0 * a * c)
    t1 = (-b + math.sqrt(disc)) / (2.0 * a)
    t2 = (-b - math.sqrt(disc)) / (2.0 * a)
    if -0.02 <= t1 <= 1.02:
        return max(0.0, min(1.0, t1))
    return max(0.0, min(1.0, t2))


def amphitheatre_z(tx):
    """Exact Three.js Z coordinate of Amphitheatre Pkwy (and East Stierlin Ct) at X = tx."""
    tx_f = float(tx)
    if tx_f < -INNER_W:
        # Interpolate smoothly along West extension (-300 -> -170)
        frac = max(0.0, min(1.0, (-INNER_W - tx_f) / 130.0))
        return AMPH_P0[1] - 24.0 * frac - 13.8 * (frac ** 1.6)
    if tx_f > SHORELINE_X:
        return STIERLIN_Z
    if tx_f <= AMPH_P2[0]:
        t = _solve_quad_x(AMPH_P0[0], AMPH_P1[0], AMPH_P2[0], tx_f)
        return quad_bezier(AMPH_P0, AMPH_P1, AMPH_P2, t)[1]
    t = _solve_quad_x(AMPH_P2[0], AMPH_P3[0], AMPH_P4[0], min(INNER_W, tx_f))
    return quad_bezier(AMPH_P2, AMPH_P3, AMPH_P4, t)[1]


def amphitheatre_points(n_per_seg=28):
    # Seamless full boulevard from X = -300 -> (-170,-72.41) -> (+168,-67.0)
    west = list(AMPH_WEST_POLY[:-1])
    inner_l = [quad_bezier(AMPH_P0, AMPH_P1, AMPH_P2, i / float(n_per_seg)) for i in range(n_per_seg)]
    inner_r = [quad_bezier(AMPH_P2, AMPH_P3, AMPH_P4, i / float(n_per_seg)) for i in range(n_per_seg + 1)]
    # Clip inner_r cleanly at SHORELINE_X = 168.0
    inner_r = [p for p in inner_r if p[0] <= SHORELINE_X]
    if inner_r[-1][0] < SHORELINE_X - 0.1:
        inner_r.append((SHORELINE_X, amphitheatre_z(SHORELINE_X)))
    return west + inner_l + inner_r


# Charleston Rd: straight WNW -> ESE southern boulevard from (-210, +53.0) through inner core to (+300, +85.07)
CHARL_Z0 = svg_to_world(67.0, 546.0)[1]    # +55.517 at X = -170
CHARL_Z1 = svg_to_world(1053.0, 608.0)[1]  # +76.897 at X = +170
CHARL_SLOPE = (CHARL_Z1 - CHARL_Z0) / (2.0 * INNER_W)  # +0.062880


def charleston_z(tx):
    """Exact Three.js Z coordinate of straight Charleston Rd centerline for X >= -210."""
    return CHARL_Z0 + (float(tx) + INNER_W) * CHARL_SLOPE


# Sweeping Western Charleston Rd curve arcing from NW Amphitheatre bend (-282,-104) around Google 2000/1950 to (-210,+53)
CHARL_WEST_SWEEP_CTRL = [
    (-282.0, -104.0),
    (-288.0, -68.0),
    (-289.5, -26.0),
    (-285.5, 14.0),
    (-272.0, 40.5),
    (-244.0, 51.2),
    (-210.0, charleston_z(-210.0)),  # (-210.0, +53.00) exact tangent join!
]
CHARL_WEST_SWEEP = sample_polyline_smooth(CHARL_WEST_SWEEP_CTRL, samples_per_seg=8)


def charleston_full_points(n_straight=48):
    straight = [
        (-210.0 + 510.0 * (i / float(n_straight)), charleston_z(-210.0 + 510.0 * (i / float(n_straight))))
        for i in range(n_straight + 1)
    ]
    return list(CHARL_WEST_SWEEP[:-1]) + straight


# Bill Graham Pkwy (N) -> Joaquin Rd (Preserved exact inner curves!)
BILL_NORTH = (70.3, -INNER_D)                  # (70.3, -110.0)
JOAQUIN_NORTH = (73.8, amphitheatre_z(73.8))   # (~73.8, -59.1)
JOAQUIN_CTRL1 = (53.8, -38.5)
JOAQUIN_MID = (56.6, -3.8)
JOAQUIN_CTRL2 = (58.6, 30.5)
JOAQUIN_SOUTH = (77.2, charleston_z(77.2))     # (~77.2, +71.1)

# Bill Graham North Extension curving into Shoreline Amphitheatre drop-off plaza + Lot C access -> Crittenden Ln
BILL_AMPH_SPUR = sample_polyline_smooth([(70.3, -108.0), (72.5, -118.0), (80.0, -124.0)], samples_per_seg=6)
LOTC_WEST_CONN = sample_polyline_smooth([(70.3, -109.5), (84.0, -111.5), (96.0, -112.0)], samples_per_seg=5)
LOTC_EAST_CONN = sample_polyline_smooth([(140.0, -112.0), (154.0, -109.5), (SHORELINE_X, CRITTENDEN_Z)], samples_per_seg=5)


def bill_graham_x(tz):
    frac = (float(tz) - BILL_NORTH[1]) / max(1e-5, JOAQUIN_NORTH[1] - BILL_NORTH[1])
    return BILL_NORTH[0] + max(0.0, min(1.0, frac)) * (JOAQUIN_NORTH[0] - BILL_NORTH[0])


def bill_graham_points(n=14):
    return [
        (
            BILL_NORTH[0] + (JOAQUIN_NORTH[0] - BILL_NORTH[0]) * (i / float(n)),
            BILL_NORTH[1] + (JOAQUIN_NORTH[1] - BILL_NORTH[1]) * (i / float(n)),
        )
        for i in range(n + 1)
    ]


def joaquin_points(n_per_seg=22):
    pts = [quad_bezier(JOAQUIN_NORTH, JOAQUIN_CTRL1, JOAQUIN_MID, i / float(n_per_seg)) for i in range(n_per_seg)]
    pts += [quad_bezier(JOAQUIN_MID, JOAQUIN_CTRL2, JOAQUIN_SOUTH, i / float(n_per_seg)) for i in range(n_per_seg + 1)]
    return pts


# Alta Ave & Huff Ave south connectors (preserved in inner [-110..+110] and extended cleanly to Plymouth St Z=+180!)
ALTA_NORTH = (-94.5, charleston_z(-94.5))
ALTA_MID = (-96.6, INNER_D)
ALTA_SOUTH = (-97.2, PLYMOUTH_Z)

HUFF_NORTH = (2.8, charleston_z(2.8))
HUFF_MID = (1.4, INNER_D)
HUFF_SOUTH = (1.4, PLYMOUTH_Z)


def alta_x(tz):
    tz_f = float(tz)
    if tz_f <= INNER_D:
        frac = (tz_f - ALTA_NORTH[1]) / max(1e-5, ALTA_MID[1] - ALTA_NORTH[1])
        return ALTA_NORTH[0] + max(0.0, min(1.0, frac)) * (ALTA_MID[0] - ALTA_NORTH[0])
    frac = (tz_f - INNER_D) / max(1e-5, PLYMOUTH_Z - INNER_D)
    return ALTA_MID[0] + max(0.0, min(1.0, frac)) * (ALTA_SOUTH[0] - ALTA_MID[0])


def huff_x(tz):
    tz_f = float(tz)
    if tz_f <= INNER_D:
        frac = (tz_f - HUFF_NORTH[1]) / max(1e-5, HUFF_MID[1] - HUFF_NORTH[1])
        return HUFF_NORTH[0] + max(0.0, min(1.0, frac)) * (HUFF_MID[0] - HUFF_NORTH[0])
    return HUFF_SOUTH[0]


# Eastern E-W Arteries & Southern Plymouth St
STIERLIN_PTS = sample_polyline_smooth([(SHORELINE_X, -67.0), (186.0, STIERLIN_Z), (242.0, STIERLIN_Z), (HALF_W, STIERLIN_Z)], samples_per_seg=6)
CRITTENDEN_PTS = [(SHORELINE_X + (HALF_W - SHORELINE_X) * (i / 14.0), CRITTENDEN_Z) for i in range(15)]
SHOREBIRD_PTS = [(SHORELINE_X + (HALF_W - SHORELINE_X) * (i / 14.0), SHOREBIRD_Z) for i in range(15)]
PLYMOUTH_PTS = [(TRAIL_X + (SHORELINE_X - TRAIL_X) * (i / 28.0), PLYMOUTH_Z) for i in range(29)]
CHARL_EAST_ACCESS_PTS = [(CHARL_EAST_ACCESS_X, charleston_z(CHARL_EAST_ACCESS_X) + (PLYMOUTH_Z - charleston_z(CHARL_EAST_ACCESS_X)) * (i / 14.0)) for i in range(15)]

# Charleston Park Winding Pedestrian Paths (preserved exact!)
PARK_PATH_EW = sample_polyline_smooth(
    [(-12.0, 2.0), (8.0, -2.5), (26.5, -6.8), (44.0, -4.5), (56.6, -2.0), (72.5, 3.8)],
    samples_per_seg=7,
)
PARK_PATH_NS = sample_polyline_smooth(
    [(20.5, amphitheatre_z(20.5) + 4.8), (25.5, -28.0), (28.0, -3.5), (25.5, 25.0), (21.5, charleston_z(21.5) - 4.4)],
    samples_per_seg=7,
)
PARK_PATH_SE = sample_polyline_smooth(
    [(3.5, 34.0), (19.0, 28.5), (38.5, 25.0), (61.5, 24.5)],
    samples_per_seg=6,
)
PARK_PATH_NE = sample_polyline_smooth(
    [(25.5, -28.0), (42.0, -32.5), (60.2, -37.5)],
    samples_per_seg=6,
)
ALL_PARK_PATHS = [PARK_PATH_EW, PARK_PATH_NS, PARK_PATH_SE, PARK_PATH_NE]

# North Shoreline Parkland + Expanded Bay Point Regional Shoreline Overlook Trails
NORTH_TRAIL_1 = sample_polyline_smooth(
    [(-138.0, -79.3), (-83.0, -91.5), (-24.0, -81.0), (35.0, -86.5), (66.0, -86.0)],
    samples_per_seg=7,
)
NORTH_TRAIL_2 = sample_polyline_smooth(
    [(-52.0, -108.0), (-34.0, -86.0), (-3.5, -75.8), (28.0, -70.0), (57.0, -64.5)],
    samples_per_seg=6,
)
BAY_POINT_TRAIL_MAIN = sample_polyline_smooth(
    [(-148.0, -126.0), (-118.0, -138.0), (-88.0, -152.0), (-62.0, -144.0), (-26.0, -150.0), (4.0, -134.0), (26.0, -124.0)],
    samples_per_seg=7,
)
BAY_POINT_TRAIL_NORTH = sample_polyline_smooth(
    [(-132.0, -172.0), (-96.0, -176.0), (-62.0, -144.0), (-52.0, -108.0)],
    samples_per_seg=6,
)
ALL_NORTH_TRAILS = [NORTH_TRAIL_1, NORTH_TRAIL_2, BAY_POINT_TRAIL_MAIN, BAY_POINT_TRAIL_NORTH]


def dist_to_polyline_2d(px, pz, poly):
    best = 1e9
    for i in range(len(poly) - 1):
        x0, z0 = poly[i]
        x1, z1 = poly[i + 1]
        dx, dz = x1 - x0, z1 - z0
        l2 = dx * dx + dz * dz
        if l2 < 1e-9:
            d = math.hypot(px - x0, pz - z0)
        else:
            t = max(0.0, min(1.0, ((px - x0) * dx + (pz - z0) * dz) / l2))
            d = math.hypot(px - (x0 + t * dx), pz - (z0 + t * dz))
        if d < best:
            best = d
    return best


def min_dist_to_park_paths(tx, tz):
    return min(dist_to_polyline_2d(tx, tz, p) for p in ALL_PARK_PATHS)


# ---------------------------------------------------------------------------
# Deterministic 3x Terrain Heightfield (matches Three.js getTerrainHeight(x, z))
# ---------------------------------------------------------------------------
def terrain_height(tx, tz):
    """
    Continuous, deterministic terrain height Y (in meters) across the FULL 600m x 380m campus.
    Guarantees Y == 0.0 on ALL 15+ landmark footprints, all roads, sidewalks, parking lots,
    Quad courtyard, Permanente Creek Trail, Athletic Field, Google 2000/1950, Shoreline Amphitheatre,
    1098 Alta, Charleston Campus, and East Shoreline offices!
    """
    # 1. Recessed Permanente Creek channel at X = -156.0m (full Z in [-190, +190], bed -0.85m)
    d_creek = abs(tx - CREEK_X)
    h_creek = -0.85 * (1.0 - smoothstep(1.8, 4.2, d_creek)) if d_creek < 4.2 else 0.0

    # 2. North Shoreline Parkland & Bay Point Regional Shoreline Overlook hills (north of Amphitheatre Pkwy)
    h_north = 0.0
    if -146.5 < tx < SHORELINE_X - 6.5:
        z_amph = amphitheatre_z(tx)
        north_d = z_amph - tz
        if north_d > 7.5:
            m_n = smoothstep(7.5, 22.0, north_d)
            m_w = smoothstep(-146.5, -134.0, tx)
            m_e = smoothstep(SHORELINE_X - 6.5, SHORELINE_X - 18.0, tx)
            m_b = smoothstep(6.0, 14.5, abs(tx - bill_graham_x(max(-INNER_D, tz)))) if tz > -126.0 else 1.0
            # Flatten cleanly around Shoreline Amphitheatre (+58, -148) & Parking Lot C (+118, -112) & NE access roads!
            d_amph_venue = math.hypot(tx - 58.0, tz + 148.0)
            m_venue = smoothstep(38.0, 56.0, d_amph_venue)
            # Flat box around Parking Lot C + access road (X > 66, Z < -90)
            m_lotc = 1.0 - smoothstep(64.0, 82.0, tx) * smoothstep(-86.0, -100.0, tz)
            # Soft fade at far North map edge Z = -190 so perimeter curb stays graceful
            m_edge_n = smoothstep(-190.0, -172.0, tz)

            raw_hill = (
                2.65
                + 1.60 * math.sin(tx * 0.030 + 0.55) * math.cos(tz * 0.045)
                + 0.90 * math.cos(tx * 0.052 - tz * 0.038)
            )
            # Bay Point Regional Shoreline Overlook scenic bluff crest around (-62, -144) (Z in [-186, -105], X in [-140, +20])
            d_bp = math.hypot((tx + 62.0) / 56.0, (tz + 144.0) / 36.0)
            bay_point_crest = 3.25 * max(0.0, 1.0 - d_bp * d_bp) ** 1.4
            h_north = max(0.0, raw_hill + bay_point_crest) * m_n * m_w * m_e * m_b * m_venue * m_lotc * (0.45 + 0.55 * m_edge_n)

    # 3. Charleston Park gentle turf berms (preserved exact inside inner core!)
    h_park = 0.0
    if 7.5 < tx < 53.0 and -49.0 < tz < 55.0:
        m_pk = (
            smoothstep(7.5, 15.0, tx)
            * smoothstep(53.0, 44.5, tx)
            * smoothstep(-49.0, -38.0, tz)
            * smoothstep(55.0, 44.0, tz)
        )
        if m_pk > 1e-4:
            m_path = smoothstep(2.0, 5.8, min_dist_to_park_paths(tx, tz))
            raw_pk = 0.65 + 0.44 * math.sin(tx * 0.105 - 0.7) * math.cos(tz * 0.082 + 0.4)
            h_park = max(0.0, raw_pk) * m_pk * m_path

    # 4. Subtle South Charleston Corridor lawn undulations (only between Charleston Rd and Z = +94m; flat on South Ring buildings!)
    h_south = 0.0
    if -146.5 < tx < SHORELINE_X - 6.5 and 60.0 < tz < 96.0:
        z_ch = charleston_z(tx)
        south_d = tz - z_ch
        if south_d > 7.5:
            m_s = smoothstep(7.5, 17.0, south_d) * smoothstep(96.0, 84.0, tz)
            m_w = smoothstep(-146.5, -135.0, tx)
            m_e = smoothstep(SHORELINE_X - 6.5, SHORELINE_X - 16.0, tx)
            m_a = smoothstep(5.5, 13.0, abs(tx - alta_x(tz)))
            m_h = smoothstep(5.5, 13.0, abs(tx - huff_x(tz)))
            m_acc = smoothstep(5.5, 12.0, abs(tx - CHARL_EAST_ACCESS_X))
            raw_s = 0.42 + 0.28 * math.sin(tx * 0.042 + 1.1) * math.cos(tz * 0.058)
            h_south = max(0.0, raw_s) * m_s * m_w * m_e * m_a * m_h * m_acc

    return h_creek + h_north + h_park + h_south


# ---------------------------------------------------------------------------
# Procedural Numpy Textures (Compact, Deterministic, Packed into GLB)
# ---------------------------------------------------------------------------
def _value_noise_2d(h, w, grid_h, grid_w, rng):
    base = rng.random((grid_h, grid_w), dtype=np.float32)
    ys = np.linspace(0, grid_h, h, endpoint=False, dtype=np.float32)
    xs = np.linspace(0, grid_w, w, endpoint=False, dtype=np.float32)
    y0 = np.floor(ys).astype(np.int32) % grid_h
    x0 = np.floor(xs).astype(np.int32) % grid_w
    y1 = (y0 + 1) % grid_h
    x1 = (x0 + 1) % grid_w
    fy = (ys - np.floor(ys))[:, None]
    fx = (xs - np.floor(xs))[None, :]
    fy = fy * fy * (3.0 - 2.0 * fy)
    fx = fx * fx * (3.0 - 2.0 * fx)
    v00 = base[y0[:, None], x0[None, :]]
    v10 = base[y0[:, None], x1[None, :]]
    v01 = base[y1[:, None], x0[None, :]]
    v11 = base[y1[:, None], x1[None, :]]
    return (v00 * (1.0 - fx) + v10 * fx) * (1.0 - fy) + (v01 * (1.0 - fx) + v11 * fx) * fy


def _fbm_2d(h, w, rng, octaves=(6, 14, 30, 56)):
    out = np.zeros((h, w), dtype=np.float32)
    amp = 0.55
    total = 0.0
    for g in octaves:
        out += amp * _value_noise_2d(h, w, g, g, rng)
        total += amp
        amp *= 0.5
    return out / total


def make_packed_image(name, rgb_srgb):
    h, w = rgb_srgb.shape[:2]
    if rgb_srgb.shape[2] == 3:
        rgba = np.ones((h, w, 4), dtype=np.float32)
        rgba[:, :, :3] = np.clip(rgb_srgb, 0.0, 1.0)
    else:
        rgba = np.clip(rgb_srgb, 0.0, 1.0).astype(np.float32)
    img = bpy.data.images.new(name=name, width=w, height=h, alpha=(rgb_srgb.shape[2] == 4))
    img.colorspace_settings.name = "sRGB"
    img.pixels.foreach_set(rgba.ravel())
    img.pack()
    return img


def gen_campus_terrain_tex(name="TexCampusTerrain", w=960, h=608, seed=2026):
    """
    Macro-mapped 600m x 380m Mountain View Googleplex ground texture.
    UV convention: U = (tx + 300)/600, V = (190 - tz)/380 (V=1 is North, V=0 is South).
    """
    rng = np.random.default_rng(seed)
    n_macro = _fbm_2d(h, w, rng, (8, 18, 38, 72))
    n_fine = _value_noise_2d(h, w, 96, 144, rng)

    u = np.linspace(0.0, 1.0, w, dtype=np.float32)
    v = np.linspace(0.0, 1.0, h, dtype=np.float32)
    tx_grid = -HALF_W + u[None, :] * (2.0 * HALF_W)          # (1, W)
    tz_grid = HALF_D - v[:, None] * (2.0 * HALF_D)           # (H, 1)

    amph_z_row = np.array([amphitheatre_z(float(x)) for x in tx_grid[0]], dtype=np.float32)[None, :]
    charl_z_row = (CHARL_Z0 + (tx_grid + INNER_W) * CHARL_SLOPE).astype(np.float32)

    # Base lush manicured Mountain View campus turf (subtle diagonal mower stripes + fBM)
    stripe = 0.022 * np.sin((tx_grid + tz_grid) * 0.34)
    var = 0.87 + 0.22 * n_macro + 0.07 * (n_fine - 0.5) + stripe
    r = var * 0.245
    g = var * 0.435
    b = var * 0.205

    # 1. Golden-green California Shoreline Parkland & Bay Point Overlook hills (North of Amphitheatre Pkwy)
    north_d = amph_z_row - tz_grid
    m_north = (
        smoothstep_np(2.0, 26.0, north_d)
        * smoothstep_np(-149.0, -136.0, tx_grid)
        * smoothstep_np(SHORELINE_X - 4.0, SHORELINE_X - 18.0, tx_grid)
    )
    # Keep lush green campus apron around Shoreline Amphitheatre (+58,-148) & Lot C (+118,-112)
    d_venue = np.hypot(tx_grid - 58.0, tz_grid + 148.0)
    m_venue_green = 1.0 - smoothstep_np(36.0, 54.0, d_venue)
    gold_mix = m_north * (1.0 - 0.65 * m_venue_green) * (0.55 + 0.45 * smoothstep_np(14.0, 52.0, north_d) * (0.76 + 0.34 * n_macro))
    r_hill = (0.57 + 0.14 * n_macro) * (0.94 + 0.10 * (n_fine - 0.5))
    g_hill = (0.54 + 0.12 * n_macro) * (0.94 + 0.10 * (n_fine - 0.5))
    b_hill = (0.29 + 0.07 * n_macro) * (0.94 + 0.10 * (n_fine - 0.5))
    r = r * (1.0 - gold_mix) + r_hill * gold_mix
    g = g * (1.0 - gold_mix) + g_hill * gold_mix
    b = b * (1.0 - gold_mix) + b_hill * gold_mix

    # 2. Charleston Park deeper emerald oak-parkland turf (preserved!)
    m_park = (
        smoothstep_np(3.0, 11.0, tx_grid)
        * smoothstep_np(57.0, 48.0, tx_grid)
        * smoothstep_np(amph_z_row + 4.0, amph_z_row + 12.0, tz_grid)
        * smoothstep_np(charl_z_row - 4.0, charl_z_row - 12.0, tz_grid)
    )
    r_pk = (0.17 + 0.08 * n_macro) * (0.95 + 0.08 * n_fine)
    g_pk = (0.37 + 0.11 * n_macro) * (0.95 + 0.08 * n_fine)
    b_pk = (0.16 + 0.05 * n_macro) * (0.95 + 0.08 * n_fine)
    r = r * (1.0 - m_park * 0.72) + r_pk * (m_park * 0.72)
    g = g * (1.0 - m_park * 0.72) + g_pk * (m_park * 0.72)
    b = b * (1.0 - m_park * 0.72) + b_pk * (m_park * 0.72)

    # 3. Sunlit sage landscaped lawns around Gradient Canopy & East Shoreline Ring
    m_east = smoothstep_np(62.0, 76.0, tx_grid) * smoothstep_np(amph_z_row + 4.0, amph_z_row + 14.0, tz_grid)
    r = r * (1.0 - m_east * 0.24) + (0.28 * var) * (m_east * 0.24)
    g = g * (1.0 - m_east * 0.24) + (0.47 * var) * (m_east * 0.24)
    b = b * (1.0 - m_east * 0.24) + (0.22 * var) * (m_east * 0.24)

    # 4. Permanente Creek earthen/cobble channel banks (full N-S at X = -156.0m)
    d_creek = np.abs(tx_grid - CREEK_X)
    m_bank = 1.0 - smoothstep_np(2.3, 4.6, d_creek)
    m_bed = 1.0 - smoothstep_np(1.4, 2.8, d_creek)
    r_bk = (0.44 + 0.10 * n_fine) * (1.0 - 0.35 * m_bed)
    g_bk = (0.40 + 0.09 * n_fine) * (1.0 - 0.32 * m_bed)
    b_bk = (0.33 + 0.08 * n_fine) * (1.0 - 0.25 * m_bed)
    r = r * (1.0 - m_bank) + r_bk * m_bank
    g = g * (1.0 - m_bank) + g_bk * m_bank
    b = b * (1.0 - m_bank) + b_bk * m_bank

    return make_packed_image(name, np.stack([r, g, b], axis=-1).astype(np.float32))


def gen_asphalt_road_tex(name="TexAsphaltRoad", size=192, double_yellow=False, seed=301):
    rng = np.random.default_rng(seed)
    n = _fbm_2d(size, size, rng, (6, 16, 36))
    speck = rng.normal(0.0, 0.020, (size, size)).astype(np.float32)
    yy, xx = np.mgrid[0:size, 0:size]
    u = xx / float(size)
    v = yy / float(size)

    gutter = 0.06 * (np.exp(-((u / 0.06) ** 2)) + np.exp(-(((1.0 - u) / 0.06) ** 2)))
    track = 0.025 * (np.exp(-(((u - 0.27) / 0.09) ** 2)) + np.exp(-(((u - 0.73) / 0.09) ** 2)))
    base = 0.23 + 0.050 * (n - 0.5) + speck - gutter + track

    r = base * 0.94
    g = base * 0.98
    b = base * 1.06

    edge_line = (np.abs(u - 0.075) < 0.015) | (np.abs(u - 0.925) < 0.015)
    r = np.where(edge_line, 0.88, r)
    g = np.where(edge_line, 0.90, g)
    b = np.where(edge_line, 0.92, b)

    dash = (v % 0.50) < 0.24
    if double_yellow:
        c_line = (np.abs(u - 0.486) < 0.010) | (np.abs(u - 0.514) < 0.010)
        r = np.where(c_line, 0.92, r)
        g = np.where(c_line, 0.73, g)
        b = np.where(c_line, 0.16, b)
        lane_d = ((np.abs(u - 0.28) < 0.009) | (np.abs(u - 0.72) < 0.009)) & dash
        r = np.where(lane_d, 0.86, r)
        g = np.where(lane_d, 0.88, g)
        b = np.where(lane_d, 0.90, b)
    else:
        c_dash = (np.abs(u - 0.50) < 0.015) & dash
        r = np.where(c_dash, 0.92, r)
        g = np.where(c_dash, 0.84, g)
        b = np.where(c_dash, 0.34, b)

    return make_packed_image(name, np.stack([r, g, b], axis=-1).astype(np.float32))


def gen_parking_lot_tex(name="TexParkingLot", size=192, seed=302):
    rng = np.random.default_rng(seed)
    n = _fbm_2d(size, size, rng, (6, 14, 32))
    speck = rng.normal(0.0, 0.018, (size, size)).astype(np.float32)
    yy, xx = np.mgrid[0:size, 0:size]
    u = xx / float(size)
    v = yy / float(size)

    base = 0.21 + 0.042 * (n - 0.5) + speck
    r = base * 0.94
    g = base * 0.98
    b = base * 1.07

    stall_zone = (u < 0.38) | (u > 0.62)
    stall_sep = ((v * 6.0) % 1.0) < 0.048
    aisle_border = (np.abs(u - 0.38) < 0.014) | (np.abs(u - 0.62) < 0.014)
    paint = (stall_zone & stall_sep) | aisle_border

    ev_bay = (u > 0.65) & (u < 0.94) & (v > 0.08) & (v < 0.14)
    r = np.where(ev_bay, 0.16, r)
    g = np.where(ev_bay, 0.56, g)
    b = np.where(ev_bay, 0.30, b)

    r = np.where(paint, 0.88, r)
    g = np.where(paint, 0.90, g)
    b = np.where(paint, 0.93, b)
    return make_packed_image(name, np.stack([r, g, b], axis=-1).astype(np.float32))


def gen_concrete_paver_tex(name="TexConcretePaver", size=128, tint=(0.84, 0.81, 0.75), grid_n=4, seed=303):
    rng = np.random.default_rng(seed)
    n = _fbm_2d(size, size, rng, (4, 12, 24))
    grain = rng.normal(0.0, 0.012, (size, size)).astype(np.float32)
    yy, xx = np.mgrid[0:size, 0:size]
    step = max(8, size // grid_n)
    seam = ((yy % step) < 2) | ((xx % step) < 2)
    v = 0.92 + 0.11 * (n - 0.5) + grain - seam.astype(np.float32) * 0.10
    return make_packed_image(name, np.stack([v * tint[0], v * tint[1], v * tint[2]], axis=-1).astype(np.float32))


def gen_trail_tex(name="TexCreekTrail", size=128, seed=304):
    rng = np.random.default_rng(seed)
    n = _fbm_2d(size, size, rng, (4, 12, 24))
    yy, xx = np.mgrid[0:size, 0:size]
    u = xx / float(size)
    v = yy / float(size)
    base = 0.64 + 0.07 * (n - 0.5)
    r = base * 0.97
    g = base * 0.95
    b = base * 0.90
    center = (np.abs(u - 0.50) < 0.028) & ((v % 0.50) < 0.26)
    edge = (u < 0.05) | (u > 0.95)
    r = np.where(edge, base * 0.82, r)
    g = np.where(edge, base * 0.80, g)
    b = np.where(edge, base * 0.76, b)
    r = np.where(center, 0.94, r)
    g = np.where(center, 0.78, g)
    b = np.where(center, 0.18, b)
    return make_packed_image(name, np.stack([r, g, b], axis=-1).astype(np.float32))


def gen_water_tex(name="TexCreekWater", size=128, seed=305):
    rng = np.random.default_rng(seed)
    n1 = _fbm_2d(size, size, rng, (4, 10, 20))
    yy, xx = np.mgrid[0:size, 0:size]
    ripple = 0.5 + 0.5 * np.sin(yy * 0.28 + n1 * 5.0)
    u = xx / float(size)
    bank_shade = 0.72 + 0.28 * np.sin(u * math.pi)
    r = (0.06 + 0.07 * ripple) * bank_shade
    g = (0.36 + 0.14 * ripple + 0.06 * n1) * bank_shade
    b = (0.64 + 0.16 * ripple + 0.06 * n1) * bank_shade
    return make_packed_image(name, np.stack([r, g, b], axis=-1).astype(np.float32))


# ---------------------------------------------------------------------------
# Blender 5.3.0 Material & Mesh Helpers
# ---------------------------------------------------------------------------
def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0


def get_or_create_collection(name, parent=None):
    if name in bpy.data.collections:
        return bpy.data.collections[name]
    col = bpy.data.collections.new(name)
    if parent is None:
        bpy.context.scene.collection.children.link(col)
    else:
        parent.children.link(col)
    return col


def move_obj_to_collection(obj, col):
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    col.objects.link(obj)


def make_pbr_mat(
    name,
    base_color=(0.8, 0.8, 0.8, 1.0),
    metallic=0.0,
    roughness=0.6,
    ior=1.45,
    alpha=1.0,
    specular=0.5,
    tex_img=None,
    double_sided=False,
):
    mat = bpy.data.materials.new(name=name)
    nt = mat.node_tree
    nodes = nt.nodes
    links = nt.links
    bsdf = nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = base_color
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["IOR"].default_value = ior
    bsdf.inputs["Alpha"].default_value = alpha
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = specular

    if tex_img is not None:
        tex_node = nodes.new("ShaderNodeTexImage")
        tex_node.image = tex_img
        tex_node.location = (-420, 200)
        links.new(tex_node.outputs["Color"], bsdf.inputs["Base Color"])

    if alpha < 0.999:
        if hasattr(mat, "surface_render_method"):
            mat.surface_render_method = "BLENDED"
        if hasattr(mat, "blend_method"):
            mat.blend_method = "BLEND"
    if double_sided:
        mat.use_backface_culling = False
    return mat


def apply_box_uv(bm, scale=0.18):
    uv_layer = bm.loops.layers.uv.verify()
    for f in bm.faces:
        n = f.normal
        ax, ay, az = abs(n.x), abs(n.y), abs(n.z)
        for loop in f.loops:
            co = loop.vert.co
            if az >= ax and az >= ay:
                u, v = co.x * scale, co.y * scale
            elif ax >= ay:
                u, v = co.y * scale, co.z * scale
            else:
                u, v = co.x * scale, co.z * scale
            loop[uv_layer].uv = (u, v)


def finalize_mesh(name, bm, mat, col, smooth=False, uv_scale=0.18, keep_uv=False):
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    if not keep_uv:
        apply_box_uv(bm, scale=uv_scale)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    if smooth and len(mesh.polygons) > 0:
        mesh.polygons.foreach_set("use_smooth", [True] * len(mesh.polygons))
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    col.objects.link(obj)
    if mat is not None:
        obj.data.materials.append(mat)
    return obj


def ensure_ccw_2d(pts):
    area = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        area += x0 * y1 - x1 * y0
    return list(reversed(pts)) if area < 0 else list(pts)


def bm_add_world_poly_slab(bm, world_pts_xz, z_bot, z_top):
    b_pts = ensure_ccw_2d([(float(tx), -float(tz)) for tx, tz in world_pts_xz])
    n = len(b_pts)
    bot = [bm.verts.new((x, y, z_bot)) for x, y in b_pts]
    top = [bm.verts.new((x, y, z_top)) for x, y in b_pts]
    for i in range(n):
        ni = (i + 1) % n
        bm.faces.new((bot[i], bot[ni], top[ni], top[i]))
    top_f = bm.faces.new(top)
    bot_f = bm.faces.new(list(reversed(bot)))
    bmesh.ops.triangulate(bm, faces=[top_f, bot_f], quad_method="BEAUTY", ngon_method="EAR_CLIP")


def bm_add_box_world(bm, tx, tz, ty, sx, sy_len, sz_h, yaw_rad=0.0):
    c = w2b(tx, tz, ty)
    mat_t = Matrix.Translation(c)
    mat_r = Euler((0.0, 0.0, yaw_rad), "XYZ").to_matrix().to_4x4()
    mat_s = Matrix.Diagonal((sx, sy_len, sz_h, 1.0))
    bmesh.ops.create_cube(bm, size=1.0, matrix=mat_t @ mat_r @ mat_s)


def bm_add_road_ribbon(
    bm,
    world_pts_xz,
    half_width,
    z_top,
    z_skirt=-0.08,
    v_tile_m=10.0,
    follow_terrain=False,
    z_offset=0.035,
):
    uv_layer = bm.loops.layers.uv.verify()
    pts_b = [(float(tx), -float(tz), float(tx), float(tz)) for tx, tz in world_pts_xz]
    n = len(pts_b)
    if n < 2:
        return

    left_top, right_top = [], []
    left_bot, right_bot = [], []
    cum_s = [0.0]

    for i in range(n):
        bx, by, tx, tz = pts_b[i]
        if i > 0:
            cum_s.append(cum_s[-1] + math.hypot(bx - pts_b[i - 1][0], by - pts_b[i - 1][1]))
        if i == 0:
            dx, dy = pts_b[1][0] - bx, pts_b[1][1] - by
        elif i == n - 1:
            dx, dy = bx - pts_b[i - 1][0], by - pts_b[i - 1][1]
        else:
            dx, dy = pts_b[i + 1][0] - pts_b[i - 1][0], pts_b[i + 1][1] - pts_b[i - 1][1]
        ln = math.hypot(dx, dy)
        nx, ny = (0.0, 1.0) if ln < 1e-6 else (-dy / ln, dx / ln)

        lx, ly = bx + nx * half_width, by + ny * half_width
        rx, ry = bx - nx * half_width, by - ny * half_width

        if follow_terrain:
            zl = terrain_height(lx, -ly) + z_offset
            zr = terrain_height(rx, -ry) + z_offset
            zb_l = zl - 0.14
            zb_r = zr - 0.14
        else:
            zl = z_top
            zr = z_top
            zb_l = z_skirt
            zb_r = z_skirt

        left_top.append(bm.verts.new((lx, ly, zl)))
        right_top.append(bm.verts.new((rx, ry, zr)))
        left_bot.append(bm.verts.new((lx, ly, zb_l)))
        right_bot.append(bm.verts.new((rx, ry, zb_r)))

    for i in range(n - 1):
        v0 = cum_s[i] / v_tile_m
        v1 = cum_s[i + 1] / v_tile_m
        f_top = bm.faces.new((right_top[i], right_top[i + 1], left_top[i + 1], left_top[i]))
        for loop, uv in zip(f_top.loops, [(1.0, v0), (1.0, v1), (0.0, v1), (0.0, v0)]):
            loop[uv_layer].uv = uv
        f_l = bm.faces.new((left_top[i], left_top[i + 1], left_bot[i + 1], left_bot[i]))
        f_r = bm.faces.new((right_bot[i], right_bot[i + 1], right_top[i + 1], right_top[i]))
        for f_side in (f_l, f_r):
            for loop in f_side.loops:
                loop[uv_layer].uv = (0.02, v0)


def bm_add_sidewalk_strip(bm, world_pts_xz, offset_inner, width, z_top=0.095, z_bot=-0.06, skip_fn=None):
    pts_b = [(float(tx), -float(tz), float(tx), float(tz)) for tx, tz in world_pts_xz]
    n = len(pts_b)
    if n < 2:
        return

    in_pts, out_pts = [], []
    for i in range(n):
        bx, by, tx, tz = pts_b[i]
        if i == 0:
            dx, dy = pts_b[1][0] - bx, pts_b[1][1] - by
        elif i == n - 1:
            dx, dy = bx - pts_b[i - 1][0], by - pts_b[i - 1][1]
        else:
            dx, dy = pts_b[i + 1][0] - pts_b[i - 1][0], pts_b[i + 1][1] - pts_b[i - 1][1]
        ln = max(1e-6, math.hypot(dx, dy))
        nx, ny = -dy / ln, dx / ln
        sgn = 1.0 if offset_inner >= 0 else -1.0
        d0 = abs(offset_inner)
        d1 = d0 + width
        in_pts.append((bx + sgn * nx * d0, by + sgn * ny * d0))
        out_pts.append((bx + sgn * nx * d1, by + sgn * ny * d1))

    for i in range(n - 1):
        mid_tx = 0.25 * (in_pts[i][0] + in_pts[i + 1][0] + out_pts[i][0] + out_pts[i + 1][0])
        mid_tz = -0.25 * (in_pts[i][1] + in_pts[i + 1][1] + out_pts[i][1] + out_pts[i + 1][1])
        if skip_fn is not None and skip_fn(mid_tx, mid_tz):
            continue
        poly = ensure_ccw_2d([in_pts[i], in_pts[i + 1], out_pts[i + 1], out_pts[i]])
        vb = [bm.verts.new((x, y, z_bot)) for x, y in poly]
        vt = [bm.verts.new((x, y, z_top)) for x, y in poly]
        bm.faces.new(vt)
        for k in range(4):
            nk = (k + 1) % 4
            bm.faces.new((vb[k], vb[nk], vt[nk], vt[k]))


def add_cedar_footbridge(bm_conc, bm_steel, bm_wood, cx, cz, span=10.6, width=3.2):
    """Build a charming slightly arched cedar & steel pedestrian footbridge over Permanente Creek."""
    n_planks = 10
    for i in range(n_planks):
        u = -0.5 + (i + 0.5) / float(n_planks)
        px = cx + u * span
        arch_z = 0.06 + 0.28 * (1.0 - 4.0 * u * u)
        bm_add_box_world(bm_wood, px, cz, arch_z, span / n_planks - 0.04, width, 0.12)
    for end_s in (-1.0, 1.0):
        bm_add_box_world(bm_conc, cx + end_s * (span * 0.48), cz, -0.25, 1.1, width + 0.5, 0.68)
    for side_s in (-1.0, 1.0):
        ry = cz + side_s * (width * 0.47)
        bm_add_box_world(bm_steel, cx, ry, 0.10, span, 0.14, 0.22)
        bm_add_box_world(bm_steel, cx, ry, 1.16, span, 0.08, 0.08)
        bm_add_box_world(bm_steel, cx, ry, 0.68, span, 0.05, 0.05)
        for k in range(-3, 4):
            px = cx + k * (span / 7.0)
            bm_add_box_world(bm_steel, px, ry, 0.62, 0.07, 0.07, 1.08)


# ---------------------------------------------------------------------------
# PART 1: Build Continuous 600m x 380m (3x) Mountain View Terrain + Roads
# ---------------------------------------------------------------------------
def build_terrain_infrastructure(col):
    tex_terrain = gen_campus_terrain_tex("TexCampusTerrain", w=960, h=608, seed=2026)
    tex_blvd = gen_asphalt_road_tex("TexAsphaltBlvd", size=192, double_yellow=True, seed=301)
    tex_conn = gen_asphalt_road_tex("TexAsphaltConn", size=192, double_yellow=False, seed=302)
    tex_park = gen_parking_lot_tex("TexParkingLot", size=192, seed=303)
    tex_conc = gen_concrete_paver_tex("TexQuadApron", size=128, tint=(0.82, 0.80, 0.76), grid_n=4, seed=304)
    tex_plaza = gen_concrete_paver_tex("TexPlazaStone", size=128, tint=(0.88, 0.85, 0.78), grid_n=6, seed=305)
    tex_trail = gen_trail_tex("TexCreekTrail", size=128, seed=306)
    tex_water = gen_water_tex("TexCreekWater", size=128, seed=307)

    mat_terrain = make_pbr_mat("Terrain_CampusGrass", base_color=(1, 1, 1, 1), roughness=0.90, tex_img=tex_terrain)
    mat_courtyard = make_pbr_mat("Quad_CourtyardGrass", base_color=hex_to_linear("#3A743E"), roughness=0.88)
    mat_blvd = make_pbr_mat("Road_BoulevardAsphalt", base_color=(1, 1, 1, 1), roughness=0.84, tex_img=tex_blvd)
    mat_conn = make_pbr_mat("Road_ConnectorAsphalt", base_color=(1, 1, 1, 1), roughness=0.84, tex_img=tex_conn)
    mat_parking = make_pbr_mat("Parking_AsphaltStalls", base_color=(1, 1, 1, 1), roughness=0.84, tex_img=tex_park)
    mat_apron = make_pbr_mat("Quad_ConcreteApron", base_color=(1, 1, 1, 1), roughness=0.80, tex_img=tex_conc)
    mat_plaza = make_pbr_mat("Plaza_LimestonePaver", base_color=(1, 1, 1, 1), roughness=0.76, tex_img=tex_plaza)
    mat_sidewalk = make_pbr_mat("Concrete_SidewalkCurb", base_color=hex_to_linear("#CBC5BA"), roughness=0.82)
    mat_park_path = make_pbr_mat("CharlestonPark_Walkway", base_color=hex_to_linear("#DDD7CA"), roughness=0.84)
    mat_north_trail = make_pbr_mat("Shoreline_DirtTrail", base_color=hex_to_linear("#C4B79B"), roughness=0.92)
    mat_creek_trail = make_pbr_mat("Permanente_BikeTrail", base_color=(1, 1, 1, 1), roughness=0.80, tex_img=tex_trail)
    mat_water = make_pbr_mat(
        "Permanente_CreekWater",
        base_color=(1, 1, 1, 1),
        metallic=0.08,
        roughness=0.06,
        ior=1.333,
        specular=0.92,
        tex_img=tex_water,
    )
    mat_bridge_conc = make_pbr_mat("Bridge_Concrete", base_color=hex_to_linear("#BEB8AC"), roughness=0.76)
    mat_steel = make_pbr_mat("Campus_DarkSteel", base_color=hex_to_linear("#303844"), metallic=0.80, roughness=0.34)
    mat_timber = make_pbr_mat("Footbridge_CedarDeck", base_color=hex_to_linear("#9C633A"), roughness=0.72)
    mat_stripe = make_pbr_mat("Crosswalk_WhitePaint", base_color=hex_to_linear("#F1F5F9"), roughness=0.70)
    mat_curb_border = make_pbr_mat("Perimeter_BorderCurb", base_color=hex_to_linear("#78818D"), roughness=0.74)

    # -----------------------------------------------------------------------
    # 1. Sculpted 600m x 380m Continuous Ground Mesh (crisp creek banks + smooth Bay Point bluffs!)
    # -----------------------------------------------------------------------
    xs_west = np.linspace(-HALF_W, -162.0, 28, endpoint=False)
    xs_creek = np.linspace(-162.0, -149.0, 16, endpoint=False)  # ~0.8m crisp creek banks
    xs_main = np.linspace(-149.0, SHORELINE_X, 78, endpoint=False)
    xs_east = np.linspace(SHORELINE_X, HALF_W, 24)
    xs = np.concatenate([xs_west, xs_creek, xs_main, xs_east])
    zs = np.linspace(-HALF_D, HALF_D, 94)

    bm_ter = bmesh.new()
    uv_ter = bm_ter.loops.layers.uv.verify()
    nx_n, nz_n = len(xs), len(zs)
    vgrid = [[None] * nz_n for _ in range(nx_n)]

    for ix, tx in enumerate(xs):
        for iz, tz in enumerate(zs):
            vgrid[ix][iz] = bm_ter.verts.new((float(tx), -float(tz), float(terrain_height(float(tx), float(tz)))))

    for ix in range(nx_n - 1):
        u0 = (xs[ix] + HALF_W) / (2.0 * HALF_W)
        u1 = (xs[ix + 1] + HALF_W) / (2.0 * HALF_W)
        for iz in range(nz_n - 1):
            v0 = (HALF_D - zs[iz]) / (2.0 * HALF_D)
            v1 = (HALF_D - zs[iz + 1]) / (2.0 * HALF_D)
            f = bm_ter.faces.new((vgrid[ix][iz + 1], vgrid[ix + 1][iz + 1], vgrid[ix + 1][iz], vgrid[ix][iz]))
            for loop, uv in zip(f.loops, [(u0, v1), (u1, v1), (u1, v0), (u0, v0)]):
                loop[uv_ter].uv = uv

    # Solid perimeter underside skirt
    skirt_z = -2.2
    for ix in range(nx_n - 1):
        for iz, rev in ((0, True), (nz_n - 1, False)):
            va, vb = vgrid[ix][iz], vgrid[ix + 1][iz]
            sa = bm_ter.verts.new((va.co.x, va.co.y, skirt_z))
            sb = bm_ter.verts.new((vb.co.x, vb.co.y, skirt_z))
            f = bm_ter.faces.new((vb, va, sa, sb) if rev else (va, vb, sb, sa))
            for loop in f.loops:
                loop[uv_ter].uv = (0.5, 0.5)
    for iz in range(nz_n - 1):
        for ix, rev in ((0, False), (nx_n - 1, True)):
            va, vb = vgrid[ix][iz], vgrid[ix][iz + 1]
            sa = bm_ter.verts.new((va.co.x, va.co.y, skirt_z))
            sb = bm_ter.verts.new((vb.co.x, vb.co.y, skirt_z))
            f = bm_ter.faces.new((vb, va, sa, sb) if rev else (va, vb, sb, sa))
            for loop in f.loops:
                loop[uv_ter].uv = (0.5, 0.5)

    finalize_mesh("Terrain_CampusGround", bm_ter, mat_terrain, col, smooth=True, keep_uv=True)

    # -----------------------------------------------------------------------
    # 2. Full N-S Permanente Creek Water (-190..+190) & Paved Bike Trail (X = -150m)
    # -----------------------------------------------------------------------
    bm_water = bmesh.new()
    creek_pts = [(CREEK_X, -HALF_D + (2.0 * HALF_D) * (i / 48.0)) for i in range(49)]
    bm_add_road_ribbon(bm_water, creek_pts, half_width=3.05, z_top=-0.35, z_skirt=-0.65, v_tile_m=14.0)
    finalize_mesh("PermanenteCreek_Water", bm_water, mat_water, col, smooth=True, keep_uv=True)

    bm_trail = bmesh.new()
    trail_pts = [(TRAIL_X, -HALF_D + (2.0 * HALF_D) * (i / 48.0)) for i in range(49)]
    bm_add_road_ribbon(bm_trail, trail_pts, half_width=1.35, z_top=0.022, z_skirt=-0.06, v_tile_m=7.0)
    finalize_mesh("PermanenteCreek_Trail", bm_trail, mat_creek_trail, col, smooth=False, keep_uv=True)

    # -----------------------------------------------------------------------
    # 3. Mountain View Boulevards & Outer Ring Arteries (clean Z-layer hierarchy)
    # -----------------------------------------------------------------------
    amph_pts = amphitheatre_points(24)
    charl_pts = charleston_full_points(48)
    joaq_pts = joaquin_points(20)
    bill_pts = bill_graham_points(12)
    shore_pts = [(SHORELINE_X, -HALF_D + (2.0 * HALF_D) * (i / 46.0)) for i in range(47)]
    alta_pts = [(alta_x(ALTA_NORTH[1] + (PLYMOUTH_Z - ALTA_NORTH[1]) * (i / 20.0)), ALTA_NORTH[1] + (PLYMOUTH_Z - ALTA_NORTH[1]) * (i / 20.0)) for i in range(21)]
    huff_pts = [(huff_x(HUFF_NORTH[1] + (PLYMOUTH_Z - HUFF_NORTH[1]) * (i / 20.0)), HUFF_NORTH[1] + (PLYMOUTH_Z - HUFF_NORTH[1]) * (i / 20.0)) for i in range(21)]

    # Main 4-lane double-yellow Mountain View Boulevards: Amphitheatre Pkwy, Sweeping Charleston Rd, N Shoreline Blvd
    bm_blvd = bmesh.new()
    bm_add_road_ribbon(bm_blvd, amph_pts, half_width=4.5, z_top=0.029, z_skirt=-0.07, v_tile_m=11.0)
    bm_add_road_ribbon(bm_blvd, charl_pts, half_width=4.2, z_top=0.028, z_skirt=-0.07, v_tile_m=11.0)
    bm_add_road_ribbon(bm_blvd, shore_pts, half_width=4.4, z_top=0.030, z_skirt=-0.07, v_tile_m=11.0)
    finalize_mesh("Roads_MainBoulevards", bm_blvd, mat_blvd, col, smooth=False, keep_uv=True)

    # Secondary Mountain View Arteries & Campus Connectors
    bm_conn = bmesh.new()
    bm_add_road_ribbon(bm_conn, joaq_pts, half_width=3.5, z_top=0.023, z_skirt=-0.07, v_tile_m=10.0)
    bm_add_road_ribbon(bm_conn, bill_pts, half_width=3.4, z_top=0.023, z_skirt=-0.07, v_tile_m=10.0)
    bm_add_road_ribbon(bm_conn, BILL_AMPH_SPUR, half_width=3.2, z_top=0.022, z_skirt=-0.07, v_tile_m=10.0)
    bm_add_road_ribbon(bm_conn, LOTC_WEST_CONN, half_width=3.0, z_top=0.022, z_skirt=-0.07, v_tile_m=10.0)
    bm_add_road_ribbon(bm_conn, LOTC_EAST_CONN, half_width=3.2, z_top=0.022, z_skirt=-0.07, v_tile_m=10.0)
    bm_add_road_ribbon(bm_conn, alta_pts, half_width=3.0, z_top=0.021, z_skirt=-0.07, v_tile_m=10.0)
    bm_add_road_ribbon(bm_conn, huff_pts, half_width=3.0, z_top=0.021, z_skirt=-0.07, v_tile_m=10.0)
    bm_add_road_ribbon(bm_conn, CHARL_EAST_ACCESS_PTS, half_width=3.0, z_top=0.021, z_skirt=-0.07, v_tile_m=10.0)
    # Eastern E-W arteries & Southern Plymouth St
    bm_add_road_ribbon(bm_conn, STIERLIN_PTS, half_width=3.4, z_top=0.024, z_skirt=-0.07, v_tile_m=10.0)
    bm_add_road_ribbon(bm_conn, CRITTENDEN_PTS, half_width=3.4, z_top=0.024, z_skirt=-0.07, v_tile_m=10.0)
    bm_add_road_ribbon(bm_conn, SHOREBIRD_PTS, half_width=3.4, z_top=0.024, z_skirt=-0.07, v_tile_m=10.0)
    bm_add_road_ribbon(bm_conn, PLYMOUTH_PTS, half_width=3.5, z_top=0.024, z_skirt=-0.07, v_tile_m=10.0)
    # Parking driveways
    bm_add_road_ribbon(bm_conn, [(-138.8, amphitheatre_z(-138.8)), (-138.8, -48.0)], half_width=2.8, z_top=0.022, z_skirt=-0.06, v_tile_m=8.0)
    bm_add_road_ribbon(bm_conn, [(-138.8, 41.0), (-138.8, charleston_z(-138.8))], half_width=2.8, z_top=0.022, z_skirt=-0.06, v_tile_m=8.0)
    bm_add_road_ribbon(bm_conn, [(-4.0, 47.0), (-4.0, charleston_z(-4.0))], half_width=3.0, z_top=0.022, z_skirt=-0.06, v_tile_m=8.0)
    # Google 2015 & CL2 & Athletic Field parking lot access driveways
    bm_add_road_ribbon(bm_conn, [(SHORELINE_X, 24.0), (204.0, 24.0)], half_width=2.8, z_top=0.022, z_skirt=-0.06, v_tile_m=8.0)
    bm_add_road_ribbon(bm_conn, [(-225.0, amphitheatre_z(-225.0)), (-225.0, -56.0)], half_width=2.8, z_top=0.022, z_skirt=-0.06, v_tile_m=8.0)
    bm_add_road_ribbon(bm_conn, [(-220.0, amphitheatre_z(-220.0)), (-220.0, -104.0)], half_width=2.8, z_top=0.022, z_skirt=-0.06, v_tile_m=8.0)
    finalize_mesh("Roads_Connectors", bm_conn, mat_conn, col, smooth=False, keep_uv=True)

    # -----------------------------------------------------------------------
    # 4. Concrete Sidewalks & Curbs (clipped cleanly at ALL intersections & creek!)
    # -----------------------------------------------------------------------
    bm_sw = bmesh.new()

    def skip_amph_sw(tx, tz):
        if abs(tx - CREEK_X) < 7.6 or abs(tx - TRAIL_X) < 2.6:
            return True
        if abs(tx - JOAQUIN_NORTH[0]) < 8.0 or tx > SHORELINE_X - 6.0:
            return True
        if tx < -274.0:
            return True
        if abs(tx - (-138.8)) < 3.8 and tz > amphitheatre_z(tx):
            return True
        if abs(tx - (-225.0)) < 4.0 and tz > amphitheatre_z(tx):
            return True
        if abs(tx - (-220.0)) < 4.0 and tz < amphitheatre_z(tx):
            return True
        return False

    def skip_charl_sw(tx, tz):
        if abs(tx - CREEK_X) < 7.6 or abs(tx - TRAIL_X) < 2.6:
            return True
        if abs(tx - JOAQUIN_SOUTH[0]) < 7.8 or abs(tx - SHORELINE_X) < 7.2:
            return True
        if tx < -274.0 and tz < -94.0:
            return True
        if abs(tx - ALTA_NORTH[0]) < 5.0 and tz > charleston_z(tx):
            return True
        if abs(tx - HUFF_NORTH[0]) < 5.0 and tz > charleston_z(tx):
            return True
        if abs(tx - CHARL_EAST_ACCESS_X) < 4.8 and tz > charleston_z(tx):
            return True
        if abs(tx - (-138.8)) < 3.8 and tz < charleston_z(tx):
            return True
        if abs(tx - (-4.0)) < 4.0 and tz < charleston_z(tx):
            return True
        return False

    def skip_shore_sw(tx, tz):
        if abs(tz - amphitheatre_z(SHORELINE_X)) < 7.0 or abs(tz - STIERLIN_Z) < 7.0:
            return True
        if abs(tz - charleston_z(SHORELINE_X)) < 7.2:
            return True
        if abs(tz - CRITTENDEN_Z) < 6.4 or abs(tz - SHOREBIRD_Z) < 6.4 or abs(tz - PLYMOUTH_Z) < 6.4:
            return True
        if abs(tz - 24.0) < 4.5 and tx > SHORELINE_X:
            return True
        if math.hypot(tx - 152.0, tz - 60.0) < 11.2:
            return True
        return False

    def skip_joaq_sw(tx, tz):
        return (tz < amphitheatre_z(tx) + 7.2) or (tz > charleston_z(tx) - 7.2)

    def skip_bill_sw(tx, tz):
        return (tz > amphitheatre_z(tx) - 7.0) or (tz < -104.0)

    def skip_south_spur(tx, tz):
        return (tz < charleston_z(tx) + 6.0) or (tz > PLYMOUTH_Z - 5.5)

    def skip_east_artery(tx, tz):
        return tx < SHORELINE_X + 6.8

    def skip_plymouth(tx, tz):
        if tx < TRAIL_X + 3.0 or tx > SHORELINE_X - 6.8:
            return True
        if abs(tx - ALTA_SOUTH[0]) < 5.0 or abs(tx - HUFF_SOUTH[0]) < 5.0 or abs(tx - CHARL_EAST_ACCESS_X) < 5.0:
            return True
        return False

    bm_add_sidewalk_strip(bm_sw, amph_pts, +4.5, 1.6, z_top=0.095, skip_fn=skip_amph_sw)
    bm_add_sidewalk_strip(bm_sw, amph_pts, -4.5, 1.6, z_top=0.095, skip_fn=skip_amph_sw)
    bm_add_sidewalk_strip(bm_sw, charl_pts, +4.2, 1.5, z_top=0.095, skip_fn=skip_charl_sw)
    bm_add_sidewalk_strip(bm_sw, charl_pts, -4.2, 1.5, z_top=0.095, skip_fn=skip_charl_sw)
    bm_add_sidewalk_strip(bm_sw, shore_pts, +4.4, 1.5, z_top=0.095, skip_fn=skip_shore_sw)
    bm_add_sidewalk_strip(bm_sw, shore_pts, -4.4, 1.5, z_top=0.095, skip_fn=skip_shore_sw)
    bm_add_sidewalk_strip(bm_sw, joaq_pts, +3.5, 1.4, z_top=0.090, skip_fn=skip_joaq_sw)
    bm_add_sidewalk_strip(bm_sw, joaq_pts, -3.5, 1.4, z_top=0.090, skip_fn=skip_joaq_sw)
    bm_add_sidewalk_strip(bm_sw, bill_pts, +3.4, 1.3, z_top=0.090, skip_fn=skip_bill_sw)
    bm_add_sidewalk_strip(bm_sw, bill_pts, -3.4, 1.3, z_top=0.090, skip_fn=skip_bill_sw)
    bm_add_sidewalk_strip(bm_sw, alta_pts, +3.0, 1.2, z_top=0.090, skip_fn=skip_south_spur)
    bm_add_sidewalk_strip(bm_sw, alta_pts, -3.0, 1.2, z_top=0.090, skip_fn=skip_south_spur)
    bm_add_sidewalk_strip(bm_sw, huff_pts, +3.0, 1.2, z_top=0.090, skip_fn=skip_south_spur)
    bm_add_sidewalk_strip(bm_sw, huff_pts, -3.0, 1.2, z_top=0.090, skip_fn=skip_south_spur)
    bm_add_sidewalk_strip(bm_sw, STIERLIN_PTS, +3.4, 1.3, z_top=0.090, skip_fn=skip_east_artery)
    bm_add_sidewalk_strip(bm_sw, STIERLIN_PTS, -3.4, 1.3, z_top=0.090, skip_fn=skip_east_artery)
    bm_add_sidewalk_strip(bm_sw, CRITTENDEN_PTS, +3.4, 1.3, z_top=0.090, skip_fn=skip_east_artery)
    bm_add_sidewalk_strip(bm_sw, CRITTENDEN_PTS, -3.4, 1.3, z_top=0.090, skip_fn=skip_east_artery)
    bm_add_sidewalk_strip(bm_sw, SHOREBIRD_PTS, +3.4, 1.3, z_top=0.090, skip_fn=skip_east_artery)
    bm_add_sidewalk_strip(bm_sw, SHOREBIRD_PTS, -3.4, 1.3, z_top=0.090, skip_fn=skip_east_artery)
    bm_add_sidewalk_strip(bm_sw, PLYMOUTH_PTS, +3.5, 1.3, z_top=0.090, skip_fn=skip_plymouth)
    bm_add_sidewalk_strip(bm_sw, PLYMOUTH_PTS, -3.5, 1.3, z_top=0.090, skip_fn=skip_plymouth)

    # -----------------------------------------------------------------------
    # 5. Core Quad Apron, Courtyard Lawn, Stan Plaza + Expanded Arrival Plazas
    # -----------------------------------------------------------------------
    bm_apron = bmesh.new()
    quad_apron_xz = [
        (-144.5, -55.0),
        (-15.0, -44.5),
        (5.2, -20.0),
        (4.8, -5.0),
        (4.5, 51.5),
        (-144.5, 47.0),
    ]
    bm_add_world_poly_slab(bm_apron, quad_apron_xz, z_bot=-0.06, z_top=0.018)

    # Gradient Canopy paved forecourt & perimeter connector walkways
    bm_add_world_poly_slab(bm_apron, [(62.0, -4.0), (74.0, -4.0), (74.0, 12.0), (62.0, 12.0)], z_bot=-0.05, z_top=0.020)
    bm_add_world_poly_slab(bm_apron, [(98.0, 48.0), (128.0, 48.0), (128.0, 61.0), (98.0, 61.0)], z_bot=-0.05, z_top=0.020)
    bm_add_road_ribbon(bm_apron, [(113.0, amphitheatre_z(113.0) + 4.8), (113.0, -40.0)], half_width=2.6, z_top=0.020, z_skirt=-0.05, v_tile_m=6.0)
    bm_add_road_ribbon(bm_apron, [(125.0, 54.0), (144.0, 58.0)], half_width=2.2, z_top=0.020, z_skirt=-0.05, v_tile_m=6.0)
    bm_add_road_ribbon(bm_apron, [(113.0, 59.0), (113.0, charleston_z(113.0) - 4.4)], half_width=2.6, z_top=0.020, z_skirt=-0.05, v_tile_m=6.0)

    # NEW Expanded Campus Pedestrian Walkways linking new landmarks cleanly to roads & bridges!
    # Google 2000/1950 east courtyard -> Permanente Creek Cedar Footbridge (Z=-2m) -> West Quad!
    bm_add_road_ribbon(bm_apron, [(-187.0, 2.0), (-162.0, -2.0)], half_width=2.4, z_top=0.022, z_skirt=-0.05, v_tile_m=6.0)
    bm_add_road_ribbon(bm_apron, [(-150.0, -2.0), (-142.0, -2.0)], half_width=2.2, z_top=0.022, z_skirt=-0.05, v_tile_m=6.0)
    # Athletic Field east entrance -> North Cedar Footbridge (Z=-126m) -> Bay Point Overlook trail!
    bm_add_road_ribbon(bm_apron, [(-188.0, -134.0), (-162.0, -126.0)], half_width=2.0, z_top=0.022, z_skirt=-0.05, v_tile_m=6.0)
    # Shoreline Amphitheatre grand SE entry promenade linking Bill Graham Pkwy & Lot C to Amphitheatre concourse!
    bm_add_road_ribbon(bm_apron, [(74.0, -122.0), (96.0, -112.0)], half_width=3.2, z_top=0.024, z_skirt=-0.05, v_tile_m=6.0)
    # East Shoreline Office pedestrian walkways connecting N Shoreline Blvd directly to Google 2015, CL2, & 1395!
    bm_add_road_ribbon(bm_apron, [(SHORELINE_X + 5.8, -22.0), (200.0, -22.0)], half_width=2.4, z_top=0.022, z_skirt=-0.05, v_tile_m=6.0)
    bm_add_road_ribbon(bm_apron, [(SHORELINE_X + 5.8, -140.0), (202.0, -140.0)], half_width=2.4, z_top=0.022, z_skirt=-0.05, v_tile_m=6.0)
    bm_add_road_ribbon(bm_apron, [(SHORELINE_X + 5.8, 122.0), (200.0, 122.0)], half_width=2.4, z_top=0.022, z_skirt=-0.05, v_tile_m=6.0)
    finalize_mesh("Quad_ConcreteApron", bm_apron, mat_apron, col, smooth=False, uv_scale=0.14)

    # Central Landscaped Courtyard Lawn
    bm_lawn = bmesh.new()
    courtyard_xz = [(-106.5, -15.5), (-28.0, -10.0), (-30.0, 18.8), (-107.5, 16.5)]
    bm_add_world_poly_slab(bm_lawn, courtyard_xz, z_bot=0.0, z_top=0.030)
    finalize_mesh("Quad_CourtyardLawn", bm_lawn, mat_courtyard, col, smooth=False, uv_scale=0.12)

    for i in range(len(courtyard_xz)):
        p0 = courtyard_xz[i]
        p1 = courtyard_xz[(i + 1) % len(courtyard_xz)]
        dx, dz = p1[0] - p0[0], p1[1] - p0[1]
        bm_add_box_world(bm_sw, 0.5 * (p0[0] + p1[0]), 0.5 * (p0[1] + p1[1]), 0.040, math.hypot(dx, dz), 0.28, 0.055, yaw_rad=math.atan2(-dz, dx))

    # Stan the T-Rex Circular Stone Plaza + Radial Walkways + Bay Point Overlook Vista Circle
    bm_plaza = bmesh.new()
    stan_ring = [(-51.0 + 10.6 * math.cos(2.0 * math.pi * i / 32), 4.0 + 10.6 * math.sin(2.0 * math.pi * i / 32)) for i in range(32)]
    bm_add_world_poly_slab(bm_plaza, stan_ring, z_bot=0.0, z_top=0.044)
    bm_add_road_ribbon(bm_plaza, [(-51.0, 4.0), (-48.0, -9.0)], half_width=2.2, z_top=0.041, z_skirt=0.0, v_tile_m=6.0)
    bm_add_road_ribbon(bm_plaza, [(-51.0, 4.0), (-82.5, 4.0)], half_width=2.0, z_top=0.041, z_skirt=0.0, v_tile_m=6.0)
    bm_add_road_ribbon(bm_plaza, [(-51.0, 4.0), (-53.0, 19.5)], half_width=2.0, z_top=0.041, z_skirt=0.0, v_tile_m=6.0)
    bm_add_road_ribbon(bm_plaza, [(-51.0, 4.0), (-10.0, 2.0)], half_width=2.1, z_top=0.041, z_skirt=0.0, v_tile_m=6.0)
    bm_add_box_world(bm_plaza, -91.0, 4.0, 0.020, 19.8, 11.8, 0.040, yaw_rad=math.radians(10.0))
    # Scenic Bay Point Regional Shoreline Overlook circular stone overlook pad perched atop the bluff (-62, -144)!
    bp_y = terrain_height(-62.0, -144.0)
    bp_ring = [(-62.0 + 7.2 * math.cos(2.0 * math.pi * i / 24), -144.0 + 7.2 * math.sin(2.0 * math.pi * i / 24)) for i in range(24)]
    bm_add_world_poly_slab(bm_plaza, bp_ring, z_bot=bp_y - 0.65, z_top=bp_y + 0.14)
    finalize_mesh("Quad_StanPlazaWalkways", bm_plaza, mat_plaza, col, smooth=False, uv_scale=0.22)

    # -----------------------------------------------------------------------
    # 6. Core Parking Lots + Parking Lot C (+118, -112) & Outer Campus Parking Strips
    # -----------------------------------------------------------------------
    bm_park_lot = bmesh.new()
    # Preserved West Parking Strip & SE Parking Lot
    bm_add_road_ribbon(bm_park_lot, [(-138.8, -49.0), (-138.8, 42.0)], half_width=4.2, z_top=0.030, z_skirt=-0.05, v_tile_m=15.0)
    bm_add_road_ribbon(bm_park_lot, [(-4.0, 25.5), (-4.0, 48.5)], half_width=7.8, z_top=0.030, z_skirt=-0.05, v_tile_m=15.5)
    # NEW Parking Lot C (+118, -112): 44m x 28m dual-bay striped Amphitheatre parking lot!
    bm_add_road_ribbon(bm_park_lot, [(96.0, -119.0), (140.0, -119.0)], half_width=6.8, z_top=0.030, z_skirt=-0.05, v_tile_m=14.0)
    bm_add_road_ribbon(bm_park_lot, [(96.0, -105.0), (140.0, -105.0)], half_width=6.8, z_top=0.030, z_skirt=-0.05, v_tile_m=14.0)
    # NEW Outer Campus Surface Parking Bays (Google 2015 South, Google 2000 North, Athletic Field South)
    bm_add_road_ribbon(bm_park_lot, [(204.0, 24.0), (264.0, 24.0)], half_width=8.2, z_top=0.030, z_skirt=-0.05, v_tile_m=14.5)
    bm_add_road_ribbon(bm_park_lot, [(-256.0, -56.0), (-196.0, -56.0)], half_width=7.5, z_top=0.030, z_skirt=-0.05, v_tile_m=14.5)
    bm_add_road_ribbon(bm_park_lot, [(-244.0, -104.0), (-196.0, -104.0)], half_width=5.4, z_top=0.030, z_skirt=-0.05, v_tile_m=14.0)
    finalize_mesh("Campus_ParkingLots", bm_park_lot, mat_parking, col, smooth=False, keep_uv=True)

    # Perimeter wheel-stop curbs (preserved West & SE + Lot C!)
    bm_add_box_world(bm_sw, -143.1, -3.5, 0.065, 0.30, 91.2, 0.12)
    bm_add_box_world(bm_sw, -134.5, -3.5, 0.065, 0.30, 91.2, 0.12)
    bm_add_box_world(bm_sw, -11.9, 37.0, 0.065, 0.30, 23.2, 0.12)
    bm_add_box_world(bm_sw, 3.9, 28.9, 0.065, 0.30, 7.0, 0.12)
    bm_add_box_world(bm_sw, 3.9, 42.3, 0.065, 0.30, 12.6, 0.12)
    bm_add_box_world(bm_sw, -4.0, 25.4, 0.065, 16.0, 0.30, 0.12)
    # Parking Lot C North & South concrete island curbs
    bm_add_box_world(bm_sw, 118.0, -126.0, 0.065, 44.4, 0.35, 0.12)
    bm_add_box_world(bm_sw, 118.0, -98.0, 0.065, 44.4, 0.35, 0.12)
    bm_add_box_world(bm_sw, 118.0, -112.0, 0.065, 36.0, 0.45, 0.12)

    # -----------------------------------------------------------------------
    # 7. Charleston Park Paths & Bay Point / Shoreline Dirt Trails
    # -----------------------------------------------------------------------
    bm_pp = bmesh.new()
    for path in ALL_PARK_PATHS:
        bm_add_road_ribbon(bm_pp, path, half_width=1.35, z_top=0.034, z_skirt=-0.06, v_tile_m=6.0, follow_terrain=True, z_offset=0.034)
    finalize_mesh("CharlestonPark_Paths", bm_pp, mat_park_path, col, smooth=False, uv_scale=0.25)

    bm_nt = bmesh.new()
    for trail in ALL_NORTH_TRAILS:
        bm_add_road_ribbon(bm_nt, trail, half_width=1.05, z_top=0.04, z_skirt=-0.06, v_tile_m=6.0, follow_terrain=True, z_offset=0.045)
    # Full-length west creekside footpath (split cleanly around vehicular bridges)
    for z0, z1 in ((-186.0, amphitheatre_z(-162.4) - 6.0), (amphitheatre_z(-162.4) + 6.0, charleston_z(-162.4) - 6.0), (charleston_z(-162.4) + 6.0, 186.0)):
        bm_add_road_ribbon(bm_nt, [(-162.4, z0), (-162.4, z1)], half_width=0.95, z_top=0.030, z_skirt=-0.06, v_tile_m=6.0)
    finalize_mesh("Shoreline_ParkTrails", bm_nt, mat_north_trail, col, smooth=False, uv_scale=0.25)

    # -----------------------------------------------------------------------
    # 8. Crisp White Pedestrian Zebra Crosswalks (Core + N Shoreline Blvd + South Ring!)
    # -----------------------------------------------------------------------
    bm_cw = bmesh.new()
    # Core crosswalks (preserved!)
    for s in range(-3, 4):
        bm_add_box_world(bm_cw, 56.6, -2.0 + s * 0.85, 0.031, 6.2, 0.42, 0.012, yaw_rad=0.04)
    az_n = amphitheatre_z(-75.0)
    for s in range(-3, 4):
        bm_add_box_world(bm_cw, -75.0 + s * 0.90, az_n, 0.036, 0.45, 7.8, 0.012, yaw_rad=-0.11)
    cz_s = charleston_z(21.5)
    for s in range(-3, 4):
        bm_add_box_world(bm_cw, 21.5 + s * 0.90, cz_s, 0.036, 0.45, 7.4, 0.012, yaw_rad=-0.06)
    # NEW N Shoreline Blvd Crosswalks (at Crittenden -108, Stierlin/Amph -58, Google 2015 -22, Charleston +86, 1395 +122)
    for cw_z in (-100.0, -56.0, -22.0, 86.0, 122.0):
        for s in range(-3, 4):
            bm_add_box_world(bm_cw, SHORELINE_X, cw_z + s * 0.90, 0.037, 7.8, 0.45, 0.012)
    # Crosswalks across Alta Ave & Huff Ave linking twin wings of 1098 Alta & Charleston Campus!
    for s in range(-2, 3):
        bm_add_box_world(bm_cw, alta_x(126.0), 126.0 + s * 0.85, 0.030, 5.4, 0.40, 0.012)
        bm_add_box_world(bm_cw, huff_x(134.0), 134.0 + s * 0.85, 0.030, 5.4, 0.40, 0.012)
    finalize_mesh("Roads_Crosswalks", bm_cw, mat_stripe, col, smooth=False)

    # -----------------------------------------------------------------------
    # 9. Bridges over Permanente Creek (2 Vehicular Bridges + 2 Cedar Footbridges!)
    # -----------------------------------------------------------------------
    bm_br_conc = bmesh.new()
    bm_br_steel = bmesh.new()
    bm_br_wood = bmesh.new()

    veh_bridges = [
        (CREEK_X, amphitheatre_z(CREEK_X), 11.4, 11.8, math.atan2(-(amphitheatre_z(CREEK_X + 5.0) - amphitheatre_z(CREEK_X - 5.0)), 10.0)),
        (CREEK_X, charleston_z(CREEK_X), 11.4, 11.0, math.atan2(-(charleston_z(CREEK_X + 5.0) - charleston_z(CREEK_X - 5.0)), 10.0)),
    ]
    for bx_w, bz_w, span_l, deck_w, yaw in veh_bridges:
        bm_add_box_world(bm_br_conc, bx_w, bz_w, -0.10, span_l, deck_w, 0.24, yaw_rad=yaw)
        ca, sa = math.cos(yaw), math.sin(yaw)
        for end_s in (-1.0, 1.0):
            bm_add_box_world(bm_br_conc, bx_w + end_s * ca * (span_l * 0.43), bz_w - end_s * sa * (span_l * 0.43), -0.58, 1.45, deck_w + 0.4, 0.92, yaw_rad=yaw)
        for side_s in (-1.0, 1.0):
            px = bx_w - side_s * sa * (deck_w * 0.47)
            pz = bz_w - side_s * ca * (deck_w * 0.47)
            bm_add_box_world(bm_br_conc, px, pz, 0.44, span_l + 0.8, 0.42, 0.84, yaw_rad=yaw)
            bm_add_box_world(bm_br_steel, px, pz, 0.96, span_l + 0.9, 0.10, 0.08, yaw_rad=yaw)
            for k in range(-2, 3):
                bm_add_box_world(bm_br_steel, px + ca * (k * 2.4), pz - sa * (k * 2.4), 0.88, 0.08, 0.08, 0.16, yaw_rad=yaw)
        for g_off in (-deck_w * 0.32, 0.0, deck_w * 0.32):
            bm_add_box_world(bm_br_steel, bx_w - sa * g_off, bz_w - ca * g_off, -0.32, span_l - 1.2, 0.34, 0.26, yaw_rad=yaw)

    # Cedar Footbridge #1 (Z = -2.0m): links Google 2000/1950 Courtyard <-> B41/B42 West Quad!
    add_cedar_footbridge(bm_br_conc, bm_br_steel, bm_br_wood, CREEK_X, -2.0, span=10.6, width=3.2)
    # Cedar Footbridge #2 (Z = -126.0m): links Google Athletic Field <-> Bay Point Regional Shoreline Overlook!
    add_cedar_footbridge(bm_br_conc, bm_br_steel, bm_br_wood, CREEK_X, -126.0, span=10.6, width=3.0)

    finalize_mesh("Concrete_SidewalksCurbs", bm_sw, mat_sidewalk, col, smooth=False, uv_scale=0.35)
    finalize_mesh("Bridges_Concrete", bm_br_conc, mat_bridge_conc, col, smooth=False, uv_scale=0.30)
    finalize_mesh("Bridges_Steel", bm_br_steel, mat_steel, col, smooth=False, uv_scale=0.50)
    finalize_mesh("Footbridge_CedarDeck", bm_br_wood, mat_timber, col, smooth=False, uv_scale=0.50)

    # -----------------------------------------------------------------------
    # 10. Low Architectural Perimeter Border Curbing (600m x 380m outer boundary!)
    # -----------------------------------------------------------------------
    bm_perim = bmesh.new()
    bm_prail = bmesh.new()
    curb_h = 0.56
    curb_w = 0.48

    def add_perim_run(pts_xz):
        for i in range(len(pts_xz) - 1):
            x0, z0 = pts_xz[i]
            x1, z1 = pts_xz[i + 1]
            mx, mz = 0.5 * (x0 + x1), 0.5 * (z0 + z1)
            if abs(mx - CREEK_X) < 3.8:
                continue
            seg_l = math.hypot(x1 - x0, z1 - z0) + 0.14
            yaw = math.atan2(-(z1 - z0), x1 - x0)
            y_base = 0.5 * (terrain_height(x0, z0) + terrain_height(x1, z1))
            bm_add_box_world(bm_perim, mx, mz, y_base + curb_h * 0.5 - 0.08, seg_l, curb_w, curb_h + 0.16, yaw_rad=yaw)
            bm_add_box_world(bm_prail, mx, mz, y_base + curb_h + 0.04, seg_l, curb_w + 0.08, 0.07, yaw_rad=yaw)

    north_edge = [(-HALF_W + 2.0 * HALF_W * (i / 48.0), -HALF_D + 0.28) for i in range(49)]
    south_edge = [(-HALF_W + 2.0 * HALF_W * (i / 48.0), HALF_D - 0.28) for i in range(49)]
    west_edge = [(-HALF_W + 0.28, -HALF_D + 2.0 * HALF_D * (i / 30.0)) for i in range(31)]
    east_edge = [(HALF_W - 0.28, -HALF_D + 2.0 * HALF_D * (i / 30.0)) for i in range(31)]

    add_perim_run(north_edge)
    add_perim_run(south_edge)
    add_perim_run(west_edge)
    add_perim_run(east_edge)

    finalize_mesh("Perimeter_BorderCurb", bm_perim, mat_curb_border, col, smooth=False, uv_scale=0.35)
    finalize_mesh("Perimeter_BorderCap", bm_prail, mat_steel, col, smooth=False, uv_scale=0.50)

    return list(col.objects)


# ---------------------------------------------------------------------------
# Export Helper & Mesh Stats
# ---------------------------------------------------------------------------
def export_objects_glb(objs, out_path: Path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    valid = [o for o in objs if o.type in ("MESH", "EMPTY")]
    for o in valid:
        o.select_set(True)
    if valid:
        bpy.context.view_layer.objects.active = valid[0]

    bpy.ops.export_scene.gltf(
        filepath=str(out_path),
        export_format="GLB",
        use_selection=True,
        export_yup=True,
        export_apply=True,
        export_materials="EXPORT",
        export_animations=False,
        export_draco_mesh_compression_enable=False,
    )
    return out_path.stat().st_size


def count_tris(objs):
    total = 0
    for o in objs:
        if o.type == "MESH" and o.data is not None:
            for p in o.data.polygons:
                total += max(1, len(p.vertices) - 2)
    return total


# ---------------------------------------------------------------------------
# PART 2: Import ALL 19 Landmarks/Props & Assemble Full 3x Mountain View Campus
# ---------------------------------------------------------------------------
def import_glb_objects(glb_path: Path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(glb_path))
    imported = []
    for o in bpy.data.objects:
        if o in before:
            continue
        colls = {c.name for c in o.users_collection}
        if "glTF_not_exported" in colls:
            continue
        imported.append(o)
    return imported


def place_unique_landmark(glb_name: str, inst_name: str, tx: float, tz: float, col, yaw_deg: float = 0.0, ty: float = 0.0):
    objs = import_glb_objects(MAP_ASSETS_DIR / glb_name)
    root_empty = bpy.data.objects.new(inst_name, None)
    root_empty.empty_display_type = "PLAIN_AXES"
    root_empty.empty_display_size = 2.0
    col.objects.link(root_empty)

    for o in objs:
        move_obj_to_collection(o, col)
        if o.parent is None:
            o.parent = root_empty

    root_empty.location = w2b(tx, tz, ty)
    root_empty.rotation_euler = Euler((0.0, 0.0, math.radians(yaw_deg)), "XYZ")
    return [root_empty] + objs


def load_prop_template(glb_name: str):
    objs = import_glb_objects(MAP_ASSETS_DIR / glb_name)
    bpy.context.view_layer.update()
    templates = []
    for o in objs:
        if o.type == "MESH":
            templates.append((o.name, o.data, o.matrix_world.copy()))
    for o in objs:
        bpy.data.objects.remove(o, do_unlink=True)
    return templates


def place_prop_from_template(templates, inst_name: str, tx: float, tz: float, col, yaw_deg: float = 0.0, scale: float = 1.0, ty: float = 0.0):
    root_empty = bpy.data.objects.new(inst_name, None)
    root_empty.empty_display_type = "PLAIN_AXES"
    root_empty.empty_display_size = 0.8
    root_empty.location = w2b(tx, tz, ty)
    root_empty.rotation_euler = Euler((0.0, 0.0, math.radians(yaw_deg)), "XYZ")
    root_empty.scale = (scale, scale, scale)
    col.objects.link(root_empty)

    created = [root_empty]
    for idx, (orig_name, mesh_data, m_world) in enumerate(templates):
        dup = bpy.data.objects.new(f"{inst_name}_{idx}", mesh_data)
        dup.matrix_basis = m_world
        dup.parent = root_empty
        col.objects.link(dup)
        created.append(dup)
    return created


def is_tree_spot_clear(tx, tz, placed_trees, min_tree_dist=6.2):
    """Strict spatial safety validator guaranteeing zero trees clip ANY building, road, parking lot, or trail!"""
    if abs(tx) > HALF_W - 4.0 or abs(tz) > HALF_D - 4.0:
        return False
    # Creek channel & bike trail
    if abs(tx - CREEK_X) < 5.4 or abs(tx - TRAIL_X) < 3.6:
        return False
    # Main Boulevards & Outer Arteries
    if tx <= SHORELINE_X and abs(tz - amphitheatre_z(tx)) < 8.0:
        return False
    if tx >= -210.0 and abs(tz - charleston_z(tx)) < 7.8:
        return False
    if tx < -205.0 and dist_to_polyline_2d(tx, tz, CHARL_WEST_SWEEP) < 8.2:
        return False
    if abs(tx - SHORELINE_X) < 8.2:
        return False
    if tx >= SHORELINE_X and (abs(tz - STIERLIN_Z) < 6.8 or abs(tz - CRITTENDEN_Z) < 6.8 or abs(tz - SHOREBIRD_Z) < 6.8):
        return False
    if tx >= TRAIL_X - 4.0 and tx <= SHORELINE_X and abs(tz - PLYMOUTH_Z) < 6.8:
        return False
    if tz < amphitheatre_z(tx) and tz > -128.0 and abs(tx - bill_graham_x(max(-INNER_D, tz))) < 7.0:
        return False
    if tz > charleston_z(tx) and (abs(tx - alta_x(tz)) < 6.2 or abs(tx - huff_x(tz)) < 6.2 or abs(tx - CHARL_EAST_ACCESS_X) < 6.0):
        return False
    if dist_to_polyline_2d(tx, tz, joaquin_points(16)) < 6.8:
        return False
    # Inner Core Buildings (Quad, Gradient Canopy, Orb Plaza)
    if -146.0 <= tx <= 6.5 and -54.0 <= tz <= 52.0:
        return False
    if ((abs(tx - 113.0) / 50.0) ** 3.0 + (abs(tz - 4.0) / 52.0) ** 3.0) < 1.0:
        return False
    if math.hypot(tx - 152.0, tz - 60.0) < 13.5:
        return False
    # NEW 3x Expanded Landmarks & Parking Lots Clearances!
    # Shoreline Amphitheatre (+58, -148)
    if math.hypot(tx - 58.0, tz + 148.0) < 38.5:
        return False
    # Parking Lot C (+118, -112) + access connectors
    if 86.0 <= tx <= 152.0 and -129.0 <= tz <= -95.0:
        return False
    # Bay Point Vista Pad (-62, -144)
    if math.hypot(tx + 62.0, tz + 144.0) < 9.5:
        return False
    # Google Athletic Recreation Field (-220, -134) + parking
    if -257.0 <= tx <= -183.0 and -159.0 <= tz <= -97.0:
        return False
    # Google 2000 & 1950 Complex (-225, +2) + North parking
    if -270.0 <= tx <= -180.0 and -66.0 <= tz <= 49.0:
        return False
    # 1098 Alta / Huff Complex (-108, +126)
    if -150.0 <= tx <= -66.0 and 95.0 <= tz <= 157.0:
        return False
    # Charleston Campus (+28, +134)
    if -31.0 <= tx <= 87.0 and 99.0 <= tz <= 169.0:
        return False
    # Eastern Shoreline Offices: Google 2015 (+234,-22) + south parking, CL2 (+236,-140), 1395 (+234,+122)
    if 196.0 <= tx <= 272.0 and -49.0 <= tz <= 36.0:
        return False
    if 198.0 <= tx <= 274.0 and -167.0 <= tz <= -113.0:
        return False
    if 195.0 <= tx <= 273.0 and 94.0 <= tz <= 150.0:
        return False
    # Paths & Trails
    if min_dist_to_park_paths(tx, tz) < 3.6:
        return False
    if any(dist_to_polyline_2d(tx, tz, tr) < 3.2 for tr in ALL_NORTH_TRAILS):
        return False
    # Spacing from already-placed trees
    for ox, oz, _ in placed_trees:
        if math.hypot(tx - ox, tz - oz) < min_tree_dist:
            return False
    return True


def assemble_full_campus():
    """Assemble ALL 19 landmark/prop .glb models across the 600m x 380m (3x) Mountain View campus."""
    col_quad = get_or_create_collection("02_Googleplex_Quad")
    col_east = get_or_create_collection("03_East_Campus")
    col_expanded = get_or_create_collection("08_Expanded_3x_Landmarks")
    col_props = get_or_create_collection("04_Campus_Props")
    col_trees = get_or_create_collection("05_Trees_Foliage")

    all_added = []

    # 1. Exact Preserved Inner Core Quad Landmarks
    quad_specs = [
        ("landmark_b40_partnerplex.glb", "Landmark_B40_PartnerPlex", -41.0, -21.0, 0.0),
        ("landmark_b41.glb",             "Landmark_B41",             -112.0, -31.0, 0.0),
        ("landmark_b42.glb",             "Landmark_B42",             -117.0,  23.0, 0.0),
        ("landmark_b43.glb",             "Landmark_B43_Solar",       -58.0,  33.0, 0.0),
        ("landmark_skybridge.glb",       "Landmark_GlassSkybridge",  -73.0,   2.0, 0.0),
        ("landmark_volleyball_court.glb","Landmark_VolleyballCourt", -91.0,   4.0, 10.0),
        ("landmark_stan_trex.glb",       "Landmark_StanTRex",        -51.0,   4.0, 0.0),
    ]
    for glb_f, name, tx, tz, yaw in quad_specs:
        all_added.extend(place_unique_landmark(glb_f, name, tx, tz, col_quad, yaw_deg=yaw, ty=0.0))

    # 2. Exact Preserved Core East Campus Landmarks (Gradient Canopy & The Orb Plaza)
    east_specs = [
        ("landmark_gradient_canopy.glb", "Landmark_GradientCanopy", 113.0,  4.0, 0.0),
        ("landmark_orb_plaza.glb",       "Landmark_TheOrbPlaza",    152.0, 60.0, 0.0),
    ]
    for glb_f, name, tx, tz, yaw in east_specs:
        all_added.extend(place_unique_landmark(glb_f, name, tx, tz, col_east, yaw_deg=yaw, ty=0.0))

    # 3. NEW 6 Expanded Mountain View Landmarks (8 placements total!)
    expanded_unique = [
        ("landmark_shoreline_amphitheatre.glb", "Landmark_ShorelineAmphitheatre",   58.0, -148.0, 0.0),
        ("landmark_athletic_field.glb",         "Landmark_AthleticField",         -220.0, -134.0, 0.0),
        ("landmark_google_2000_1950.glb",       "Landmark_Google2000_1950",       -225.0,    2.0, 0.0),
        ("landmark_alta_complex.glb",           "Landmark_Alta1098_Complex",      -108.0,  126.0, 0.0),
        ("landmark_charleston_campus.glb",      "Landmark_CharlestonCampus",        28.0,  134.0, 0.0),
    ]
    for glb_f, name, tx, tz, yaw in expanded_unique:
        all_added.extend(place_unique_landmark(glb_f, name, tx, tz, col_expanded, yaw_deg=yaw, ty=0.0))

    # Reuse landmark_shoreline_east_office.glb cleanly via shared mesh data-blocks at all 3 East Shoreline sites!
    east_office_tpl = load_prop_template("landmark_shoreline_east_office.glb")
    east_office_placements = [
        ("Landmark_Google2015_Stierlin", 234.0,  -22.0, 0.0),
        ("Landmark_GoogleCL2_Crittenden", 236.0, -140.0, 180.0),
        ("Landmark_Google1395_Charleston", 234.0, 122.0, math.degrees(0.06)),
    ]
    for name, tx, tz, yaw in east_office_placements:
        all_added.extend(place_prop_from_template(east_office_tpl, name, tx, tz, col_expanded, yaw_deg=yaw, scale=1.0, ty=0.0))

    # 4. Linked Prop Instances: Google Umbrella Bistros & GBike Racks across Core + Expanded 3x Campus
    umb_tpl = load_prop_template("prop_umbrella_bistro.glb")
    gbike_tpl = load_prop_template("prop_gbike_rack.glb")
    oak_tpl = load_prop_template("prop_oak_tree.glb")
    redwood_tpl = load_prop_template("prop_redwood_tree.glb")

    umbrella_placements = [
        # Core Stan Plaza, Quad & Gradient Canopy (preserved!)
        (-62.5,  -2.0,  15.0), (-61.0,  11.8,  72.0), (-40.0,  -0.5, 130.0),
        (-39.5,  10.8, 210.0), (-31.8,   4.8, 285.0), (-25.5,   4.8,  45.0),
        (-97.5,  -7.8, 110.0), (-84.5,  13.2, 195.0), ( 67.5, -14.0,  20.0),
        ( 67.5,  20.5, 160.0), (104.5,  55.0,  85.0), (121.5,  55.0, 240.0),
        # NEW Expanded Campus Bistro Patio Clusters!
        # Google 2000/1950 Central Courtyard
        (-234.0,  -5.5,  25.0), (-216.0,   7.5, 140.0), (-196.0,  -4.0, 260.0),
        # Charleston Campus Sunlit Courtyard Plaza
        (  16.0, 127.0,  35.0), (  38.0, 127.0, 115.0), (  16.0, 141.0, 225.0), (  38.0, 141.0, 310.0),
        # 1098 Alta West Garden Patio
        (-136.0, 122.0,  60.0), (-136.0, 130.0, 190.0),
        # Shoreline Amphitheatre SE Concourse
        (  74.0, -118.0,  40.0), (  86.0, -124.0, 175.0),
        # East Shoreline Offices (2015, CL2, 1395) entry plazas
        ( 218.0,   4.0,  15.0), ( 250.0,   4.0, 135.0),
        ( 222.0, -114.0, 90.0), ( 222.0,  148.0, 210.0),
        # Bay Point Overlook vista benches/umbrellas
        ( -62.0, -140.0, 50.0),
    ]
    for i, (tx, tz, yaw) in enumerate(umbrella_placements):
        if math.hypot(tx + 51.0, tz - 4.0) < 11.0:
            ty = 0.044
        elif -106 < tx < -28 and -15 < tz < 18:
            ty = 0.030
        elif math.hypot(tx + 62.0, tz + 144.0) < 8.0:
            ty = terrain_height(-62.0, -144.0) + 0.14
        else:
            ty = max(0.036, terrain_height(tx, tz))
        all_added.extend(place_prop_from_template(umb_tpl, f"Prop_Umbrella_{i+1:02d}", tx, tz, col_props, yaw_deg=yaw, scale=1.0, ty=ty))

    gbike_placements = [
        # Core Quad & Gradient Canopy (preserved!)
        (-99.0, -51.5, -10.0), (-15.5, -39.5, -16.0), (66.0, 7.8, 92.0), (-28.0, 52.0, -4.0),
        # NEW Outer Campus GBike Corrals!
        (-190.0,   6.0,  88.0),   # Google 2000/1950 Creekside Footbridge Hub
        (-190.0, -122.0,  0.0),   # Athletic Field East Entrance
        (  84.0, -114.0, -32.0),  # Shoreline Amphitheatre / Lot C Bike Hub
        ( -86.0,  96.0,   4.0),   # 1098 Alta North Entrance
        (  14.0,  98.0,   0.0),   # Charleston Campus North Entrance
        ( 194.0, -28.0,  90.0),   # Google 2015 Shoreline Blvd Entrance
        ( 196.0, -134.0, 90.0),   # Google CL2 Crittenden Entrance
        ( 194.0, 116.0,  90.0),   # Google 1395 Charleston Entrance
    ]
    for i, (tx, tz, yaw) in enumerate(gbike_placements):
        all_added.extend(place_prop_from_template(gbike_tpl, f"Prop_GBikeRack_{i+1:02d}", tx, tz, col_props, yaw_deg=yaw, scale=1.0, ty=0.024))

    # 5. Abundant California Live Oak & Coastal Redwood Groves across ALL 3x Mountain View Rings!
    candidate_trees = [
        # --- Preserved Charleston Park Groves ---
        (12.2, -31.0, "oak",     1.08,  18.0), (30.5, -35.5, "oak",     1.14,  84.0),
        (44.2, -23.5, "oak",     1.02, 145.0), (11.5, -12.5, "oak",     0.96, 212.0),
        (14.0,   8.5, "oak",     1.05, 275.0), (35.0,   2.5, "oak",     1.16,  42.0),
        (46.8,   7.5, "oak",     0.98, 128.0), (17.5,  19.0, "oak",     1.04, 315.0),
        (15.5,  38.5, "oak",     1.10,  62.0), (39.5,  33.5, "oak",     1.12, 190.0),
        (30.5,  44.5, "oak",     0.95, 250.0), (48.5,  41.0, "oak",     1.02,  10.0),
        (18.5, -42.5, "oak",     0.94, 105.0), (41.0, -43.5, "oak",     1.00, 330.0),
        (36.0, -17.0, "oak",     1.08, 168.0), (49.0, -12.0, "oak",     0.92, 232.0),
        (16.0,  50.5, "oak",     0.96,  78.0), (42.0,  52.0, "oak",     1.02, 154.0),
        (20.0, -18.5, "redwood", 0.96,  35.0), (38.0,  15.0, "redwood", 1.02, 120.0),
        (13.5,  46.5, "redwood", 0.92, 225.0), (49.5, -36.5, "redwood", 0.95, 300.0),
        (32.5, -44.5, "redwood", 0.90,  60.0),

        # --- Full N-S Permanente Creek Riparian Corridor (Z in [-184, +184]) ---
        (-165.0, -176.0, "redwood", 1.08,  15.0), (-164.5, -158.0, "oak",     1.02,  95.0),
        (-165.0, -140.0, "redwood", 1.04, 185.0), (-164.5, -110.0, "oak",     0.98, 265.0),
        (-164.5,  -94.0, "redwood", 1.05,  22.0), (-164.0,  -82.0, "oak",     0.96, 114.0),
        (-164.5,  -52.0, "redwood", 1.08, 205.0), (-164.0,  -34.0, "oak",     1.02, 288.0),
        (-164.5,  -16.0, "redwood", 1.00,  48.0), (-164.0,   14.0, "oak",     1.04, 136.0),
        (-164.5,   32.0, "redwood", 1.06, 238.0), (-164.0,   44.0, "oak",     0.95, 320.0),
        (-164.5,   74.0, "redwood", 1.04,  82.0), (-164.0,   94.0, "oak",     1.00, 174.0),
        (-165.0,  118.0, "redwood", 1.06, 255.0), (-164.5,  142.0, "oak",     1.02,  35.0),
        (-165.0,  166.0, "redwood", 1.04, 125.0), (-145.5,  -92.0, "oak",     0.92,  45.0),
        (-145.0,   78.0, "redwood", 0.98, 165.0), (-144.5,  168.0, "oak",     0.96, 260.0),

        # --- North Shoreline Parkland & Bay Point Regional Shoreline Overlook Hills ---
        (-132.0, -96.0, "oak",     1.02,  30.0), (-112.0,  -80.0, "oak",     0.96, 140.0),
        ( -96.0, -98.0, "redwood", 1.04, 215.0), ( -74.0,  -78.0, "oak",     1.06, 305.0),
        ( -56.0, -95.0, "oak",     1.00,  55.0), ( -34.0,  -70.0, "oak",     0.94, 175.0),
        ( -16.0, -98.0, "redwood", 1.02, 265.0), (   6.0,  -92.0, "oak",     1.08,  15.0),
        (  24.0, -98.0, "oak",     1.00, 110.0), (  46.0,  -96.0, "redwood", 1.06, 195.0),
        (  52.0, -74.0, "oak",     0.95, 290.0), (  90.0,  -82.0, "oak",     1.04,  40.0),
        ( 112.0, -80.0, "oak",     1.10, 130.0), ( 134.0,  -82.0, "redwood", 1.06, 225.0),
        ( 150.0, -84.0, "oak",     1.02, 315.0),
        # Bay Point Overlook North Bluffs (Z in [-184, -110])
        (-134.0, -118.0, "oak",     1.08,  45.0), (-118.0, -162.0, "redwood", 1.12, 130.0),
        (-102.0, -124.0, "oak",     1.04, 210.0), ( -84.0, -172.0, "oak",     1.08, 300.0),
        ( -78.0, -122.0, "redwood", 1.06,  60.0), ( -44.0, -170.0, "oak",     1.10, 150.0),
        ( -36.0, -128.0, "oak",     1.00, 240.0), ( -14.0, -168.0, "redwood", 1.10, 325.0),
        (  -6.0, -122.0, "oak",     1.04,  25.0), (  12.0, -166.0, "oak",     1.02, 115.0),
        # Framing Shoreline Amphitheatre & Lot C
        (  96.0, -168.0, "redwood", 1.08,  75.0), ( 114.0, -158.0, "oak",     1.10, 165.0),
        ( 134.0, -172.0, "redwood", 1.06, 255.0), ( 146.0, -148.0, "oak",     1.04, 345.0),
        ( 152.0, -174.0, "oak",     0.98,  45.0), ( 112.0, -140.0, "oak",     1.02, 195.0),

        # --- West Ring (Athletic Field, NW Shoreline, Google 2000/1950 & SW Charleston Parkland) ---
        (-284.0, -172.0, "redwood", 1.10,  20.0), (-262.0, -174.0, "oak",     1.06, 110.0),
        (-236.0, -174.0, "oak",     1.08, 200.0), (-208.0, -174.0, "redwood", 1.06, 290.0),
        (-182.0, -172.0, "oak",     1.02,  50.0), (-276.0, -142.0, "oak",     1.06, 140.0),
        (-272.0, -120.0, "redwood", 1.02, 230.0), (-178.0, -110.0, "oak",     0.98, 315.0),
        (-258.0,  -78.0, "oak",     1.02,  65.0), (-186.0,  -66.0, "redwood", 1.04, 155.0),
        (-278.0,   64.0, "redwood", 1.10,  35.0), (-254.0,   76.0, "oak",     1.08, 125.0),
        (-226.0,   72.0, "oak",     1.06, 215.0), (-196.0,   78.0, "redwood", 1.08, 305.0),
        (-278.0,  104.0, "oak",     1.06,  80.0), (-248.0,  118.0, "redwood", 1.12, 170.0),
        (-214.0,  112.0, "oak",     1.08, 260.0), (-186.0,  122.0, "oak",     1.02, 350.0),
        (-276.0,  148.0, "redwood", 1.10,  40.0), (-242.0,  156.0, "oak",     1.08, 130.0),
        (-204.0,  158.0, "redwood", 1.06, 220.0), (-182.0,  168.0, "oak",     1.00, 310.0),

        # --- South Ring (South Charleston Corridor, 1098 Alta, Charleston Campus, Plymouth St) ---
        (-125.0,   78.0, "oak",     1.04,  25.0), ( -76.0,   82.0, "oak",     1.08, 205.0),
        ( -54.0,   94.0, "redwood", 1.06,  50.0), ( -52.0,  120.0, "oak",     1.10, 145.0),
        ( -52.0,  146.0, "redwood", 1.06, 235.0), ( -48.0,  166.0, "oak",     1.02, 325.0),
        ( -22.0,   86.0, "oak",     1.04,  85.0), (  24.0,   88.0, "oak",     1.10, 175.0),
        (  52.0,   88.0, "redwood", 1.06, 265.0), ( 112.0,   94.0, "oak",     1.08,  30.0),
        ( 132.0,  106.0, "redwood", 1.10, 120.0), ( 146.0,  128.0, "oak",     1.06, 210.0),
        ( 116.0,  136.0, "redwood", 1.08, 300.0), ( 138.0,  156.0, "oak",     1.04,  65.0),
        ( 112.0,  164.0, "oak",     1.02, 155.0), (-126.0,  168.0, "oak",     1.00, 245.0),
        ( -78.0,  168.0, "redwood", 1.02, 335.0),

        # --- Gradient Canopy Perimeter Framing ---
        ( 76.0,  -49.0, "oak",     0.96,  65.0), (148.0,  -46.0, "oak",     1.02, 155.0),
        (154.0,  -26.0, "redwood", 0.94, 245.0), ( 80.0,   56.0, "oak",     0.98, 335.0),
        (136.0,   58.0, "oak",     0.92,  95.0),

        # --- East Ring (East of N Shoreline Blvd: CL2, Stierlin Ct, Google 2015, Charleston E, 1395, Shorebird) ---
        (184.0, -174.0, "redwood", 1.06,  20.0), (212.0, -176.0, "oak",     1.04, 110.0),
        (246.0, -178.0, "redwood", 1.08, 200.0), (282.0, -172.0, "oak",     1.06, 290.0),
        (284.0, -142.0, "redwood", 1.08,  50.0), (284.0, -122.0, "oak",     1.00, 140.0),
        (184.0, -122.0, "oak",     1.02, 230.0), (190.0,  -86.0, "redwood", 1.06, 320.0),
        (220.0,  -86.0, "oak",     1.08,  70.0), (254.0,  -86.0, "redwood", 1.06, 160.0),
        (282.0,  -86.0, "oak",     1.04, 250.0), (186.0,  -48.0, "oak",     1.02, 340.0),
        (284.0,  -42.0, "redwood", 1.08,  30.0), (284.0,  -12.0, "oak",     1.06, 120.0),
        (284.0,   20.0, "redwood", 1.06, 210.0), (186.0,    4.0, "oak",     1.00, 300.0),
        (190.0,   54.0, "redwood", 1.08,  60.0), (222.0,   56.0, "oak",     1.10, 150.0),
        (254.0,   58.0, "redwood", 1.08, 240.0), (284.0,   58.0, "oak",     1.04, 330.0),
        (184.0,  104.0, "oak",     1.02,  25.0), (284.0,  108.0, "redwood", 1.06, 115.0),
        (284.0,  138.0, "oak",     1.04, 205.0), (186.0,  144.0, "redwood", 1.02, 295.0),
        (196.0,  176.0, "oak",     1.04,  80.0), (232.0,  176.0, "redwood", 1.08, 170.0),
        (268.0,  176.0, "oak",     1.06, 260.0), (286.0,  176.0, "redwood", 1.04, 350.0),
    ]

    placed_trees = []
    oak_count = 0
    redwood_count = 0
    for tx, tz, kind, sc, yaw in candidate_trees:
        if not is_tree_spot_clear(tx, tz, placed_trees, min_tree_dist=6.0):
            continue
        ty = terrain_height(tx, tz) - 0.08
        tpl = oak_tpl if kind == "oak" else redwood_tpl
        idx_num = (oak_count + 1) if kind == "oak" else (redwood_count + 1)
        label = f"Tree_Oak_{idx_num:03d}" if kind == "oak" else f"Tree_Redwood_{idx_num:03d}"
        all_added.extend(place_prop_from_template(tpl, label, tx, tz, col_trees, yaw_deg=yaw, scale=sc, ty=ty))
        placed_trees.append((tx, tz, kind))
        if kind == "oak":
            oak_count += 1
        else:
            redwood_count += 1

    # 6. Playable Hollow Office Interior Furniture Sets (preserved Core!)
    col_office = get_or_create_collection("07_Office_Interiors")
    office_files = {
        "desk": "prop_desk_pod.glb",
        "conf": "prop_conference_pod.glb",
        "mk": "prop_microkitchen_bar.glb",
        "lounge": "prop_lounge_nook.glb",
        "wb": "prop_whiteboard_wall.glb",
    }
    office_tpls = {k: load_prop_template(fname) for k, fname in office_files.items() if (MAP_ASSETS_DIR / fname).exists()}

    office_placements = [
        ("mk",     -44.0, -14.0,  -10.0, 0.056), ("lounge", -51.0, -28.0,   15.0, 0.056),
        ("desk",   -72.0, -24.0,  -12.0, 0.056), ("desk",   -66.0, -29.0,  -12.0, 0.056),
        ("conf",   -16.0, -19.0,  -22.0, 0.056), ("desk",   -34.0, -24.0,  -15.0, 0.056),
        ("wb",     -40.0, -21.0,   75.0, 0.056), ("desk",  -118.0, -29.0,   12.0, 0.056),
        ("conf",  -105.0, -34.0,   22.0, 0.056), ("mk",    -114.0, -41.5,  -18.0, 0.056),
        ("wb",    -111.0, -28.0,   65.0, 0.056), ("lounge",-122.0,  21.0,   -8.0, 0.056),
        ("desk",  -112.0,  29.0,    5.0, 0.056), ("desk",  -114.0,  11.0,    5.0, 0.056),
        ("wb",    -121.0,  32.0,   82.0, 0.056), ("desk",   -86.0,  31.0,   -8.0, 0.056),
        ("desk",   -72.0,  36.0,   -8.0, 0.056), ("conf",   -56.0,  34.0,  -10.0, 0.056),
        ("mk",     -42.0,  29.0,  -12.0, 0.056), ("lounge", -30.0,  38.0,   20.0, 0.056),
        ("wb",     -62.0,  28.0,   78.0, 0.056), ("desk",   100.0,  -8.0,   15.0, 0.40),
        ("desk",   126.0,  -6.0,  -15.0, 0.40),  ("lounge", 102.0,  12.0,   30.0, 0.40),
        ("conf",   124.0,  14.0,  -25.0, 0.40),  ("wb",     -73.0,   2.0,   81.4, 0.03),
    ]
    office_count = 0
    for idx_o, (kind, tx, tz, yaw, ty) in enumerate(office_placements):
        if kind not in office_tpls:
            continue
        all_added.extend(place_prop_from_template(office_tpls[kind], f"Office_{kind}_{idx_o+1:02d}", tx, tz, col_office, yaw_deg=yaw, scale=1.0, ty=ty))
        office_count += 1

    bpy.context.view_layer.update()
    return all_added, {
        "umbrellas": len(umbrella_placements),
        "gbikes": len(gbike_placements),
        "oaks": oak_count,
        "redwoods": redwood_count,
        "office_props": office_count,
    }


# ---------------------------------------------------------------------------
# PART 3: Crisp Bitmap Font + Headless BLENDER_EEVEE Dual-Panel 3x QA Render
# ---------------------------------------------------------------------------
FONT_5X7 = {
    "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    "B": ["11110", "10001", "10001", "11110", "10001", "10001", "11110"],
    "C": ["01111", "10000", "10000", "10000", "10000", "10000", "01111"],
    "D": ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    "E": ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    "F": ["11111", "10000", "10000", "11110", "10000", "10000", "10000"],
    "G": ["01111", "10000", "10000", "10111", "10001", "10001", "01110"],
    "H": ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
    "I": ["11111", "00100", "00100", "00100", "00100", "00100", "11111"],
    "J": ["00111", "00010", "00010", "00010", "00010", "10010", "01100"],
    "K": ["10001", "10010", "10100", "11000", "10100", "10010", "10001"],
    "L": ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
    "M": ["10001", "11011", "10101", "10101", "10001", "10001", "10001"],
    "N": ["10001", "11001", "10101", "10011", "10001", "10001", "10001"],
    "O": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    "P": ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    "Q": ["01110", "10001", "10001", "10001", "10101", "10010", "01101"],
    "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    "S": ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    "T": ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
    "U": ["10001", "10001", "10001", "10001", "10001", "10001", "01110"],
    "V": ["10001", "10001", "10001", "10001", "10001", "01010", "00100"],
    "W": ["10001", "10001", "10001", "10101", "10101", "11011", "10001"],
    "X": ["10001", "10001", "01010", "00100", "01010", "10001", "10001"],
    "Y": ["10001", "10001", "01010", "00100", "00100", "00100", "00100"],
    "Z": ["11111", "00001", "00010", "00100", "01000", "10000", "11111"],
    "0": ["01110", "10011", "10101", "10101", "11001", "10001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00001", "00110", "01000", "10000", "11111"],
    "3": ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "5": ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
    "6": ["01110", "10000", "11110", "10001", "10001", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00010", "01100"],
    " ": ["00000", "00000", "00000", "00000", "00000", "00000", "00000"],
    "-": ["00000", "00000", "00000", "11111", "00000", "00000", "00000"],
    ".": ["00000", "00000", "00000", "00000", "00000", "01100", "01100"],
    ",": ["00000", "00000", "00000", "00000", "00110", "00100", "01000"],
    ":": ["00000", "01100", "01100", "00000", "01100", "01100", "00000"],
    "/": ["00001", "00010", "00010", "00100", "01000", "01000", "10000"],
    "(": ["00010", "00100", "01000", "01000", "01000", "00100", "00010"],
    ")": ["01000", "00100", "00010", "00010", "00010", "00100", "01000"],
    "+": ["00000", "00100", "00100", "11111", "00100", "00100", "00000"],
    "=": ["00000", "00000", "11111", "00000", "11111", "00000", "00000"],
    "|": ["00100", "00100", "00100", "00100", "00100", "00100", "00100"],
    "&": ["01100", "10010", "10100", "01000", "10101", "10010", "01101"],
}


def draw_text(canvas, text, x, y, scale=2, color=(1.0, 1.0, 1.0, 1.0)):
    h, w, _ = canvas.shape
    cx = x
    for ch in text.upper():
        glyph = FONT_5X7.get(ch, FONT_5X7[" "])
        for ry, row in enumerate(glyph):
            for rx, bit in enumerate(row):
                if bit == "1":
                    y0, y1 = y + ry * scale, min(h, y + (ry + 1) * scale)
                    x0, x1 = cx + rx * scale, min(w, cx + (rx + 1) * scale)
                    if y0 >= 0 and x0 >= 0 and y0 < h and x0 < w:
                        canvas[y0:y1, x0:x1] = color
        cx += 6 * scale


def fill_rect(canvas, x0, y0, x1, y1, color):
    h, w, _ = canvas.shape
    canvas[max(0, y0):min(h, y1), max(0, x0):min(w, x1)] = color


def load_png_topdown(path: str):
    img = bpy.data.images.load(path, check_existing=False)
    w, h = img.size
    buf = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(buf)
    bpy.data.images.remove(img)
    return buf.reshape((h, w, 4))[::-1].copy()


def save_png_topdown(canvas, out_path: Path, mirror_paths=None):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    h, w, _ = canvas.shape
    img = bpy.data.images.new(f"FullMap_{out_path.stem}", width=w, height=h, alpha=True)
    flipped = np.ascontiguousarray(np.clip(canvas[::-1], 0.0, 1.0), dtype=np.float32)
    img.pixels.foreach_set(flipped.ravel())
    img.filepath_raw = str(out_path)
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)
    if mirror_paths:
        for mp in mirror_paths:
            mp = Path(mp)
            mp.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(out_path, mp)


def look_at(obj, target: Vector):
    direction = target - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def setup_california_lighting_and_cameras(col_rig):
    """Set up sunlit California 4:30 PM golden-hour lighting + 3x Aerial & Top-Down cameras."""
    scene = bpy.context.scene
    world = bpy.data.worlds.new("GoogleplexCaliforniaSky")
    scene.world = world
    if world.node_tree is None:
        world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg = nt.nodes.new("ShaderNodeBackground")
    texcoord = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color = (0.14, 0.21, 0.30, 1.0)
    e_mid = ramp.color_ramp.elements.new(0.47)
    e_mid.color = (0.62, 0.74, 0.86, 1.0)
    ramp.color_ramp.elements[2].position = 0.62
    ramp.color_ramp.elements[2].color = (0.24, 0.52, 0.90, 1.0)
    nt.links.new(texcoord.outputs["Generated"], sep.inputs["Vector"])
    nt.links.new(sep.outputs["Z"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = 0.95
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])

    def add_sun(name, pos, energy, color, angle_deg, shadows=True):
        ld = bpy.data.lights.new(name, type="SUN")
        ld.energy = energy
        ld.color = color
        ld.angle = math.radians(angle_deg)
        if hasattr(ld, "use_shadow"):
            ld.use_shadow = shadows
        lo = bpy.data.objects.new(name, ld)
        col_rig.objects.link(lo)
        lo.location = Vector(pos)
        look_at(lo, Vector((0.0, 0.0, 0.0)))
        return lo

    add_sun("Sun_CaliforniaKey", (-280.0, -210.0, 220.0), 4.0, (1.00, 0.93, 0.79), 1.5, shadows=True)
    add_sun("Sun_AzureSkyFill", (240.0, 180.0, 200.0), 0.95, (0.74, 0.87, 1.00), 14.0, shadows=False)
    add_sun("Sun_WarmRim", (220.0, -240.0, 140.0), 0.55, (1.00, 0.95, 0.86), 8.0, shadows=False)

    # Camera 1: Sweeping Aerial 3/4 Overview framing ALL 4 corners of the 600m x 380m (3x) campus cleanly!
    cam_a_data = bpy.data.cameras.new("Cam_Aerial34")
    cam_a_data.lens_unit = "FOV"
    cam_a_data.sensor_fit = "HORIZONTAL"
    cam_a_data.angle = math.radians(54.0)
    cam_a_data.clip_start = 1.0
    cam_a_data.clip_end = 2800.0
    cam_a = bpy.data.objects.new("Cam_Aerial34", cam_a_data)
    col_rig.objects.link(cam_a)
    cam_a.location = Vector((0.0, -545.0, 318.0))
    look_at(cam_a, Vector((0.0, 4.0, 2.0)))

    # Camera 2: True Top-Down Orthographic Plan (North = +Y = Up, exact 600:380 framing!)
    cam_t_data = bpy.data.cameras.new("Cam_TopDownOrtho")
    cam_t_data.type = "ORTHO"
    cam_t_data.ortho_scale = 626.0
    cam_t_data.clip_start = 1.0
    cam_t_data.clip_end = 1600.0
    cam_t = bpy.data.objects.new("Cam_TopDownOrtho", cam_t_data)
    col_rig.objects.link(cam_t)
    cam_t.location = Vector((0.0, 0.0, 420.0))
    cam_t.rotation_euler = Euler((0.0, 0.0, 0.0), "XYZ")

    scene.camera = cam_a
    return cam_a, cam_t


def render_dual_panel_preview(cam_aerial, cam_ortho, samples: int, stats_line: str, mirror_paths):
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = samples
    # Exact 600:380 = 1.5789 panel aspect ratio for edge-to-edge sharp Top-Down & Aerial framing!
    pw, ph = 1200, 760
    scene.render.resolution_x = pw
    scene.render.resolution_y = ph
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = False
    try:
        scene.view_settings.view_transform = "AgX"
    except Exception:
        pass
    try:
        scene.view_settings.look = "AgX - Medium High Contrast"
    except Exception:
        pass
    scene.view_settings.exposure = 0.05

    with tempfile.TemporaryDirectory(prefix="wr_fullmap3x_") as td:
        tmp = Path(td)
        scene.camera = cam_aerial
        scene.render.filepath = str(tmp / "aerial.png")
        bpy.ops.render.render(write_still=True)
        img_a = load_png_topdown(str(tmp / "aerial.png"))

        scene.camera = cam_ortho
        scene.render.filepath = str(tmp / "ortho.png")
        bpy.ops.render.render(write_still=True)
        img_o = load_png_topdown(str(tmp / "ortho.png"))

    scene.camera = cam_aerial

    pad = 16
    hdr_h = 62
    panel_hdr = 38
    ftr_h = 34
    sw = pad + pw + pad + pw + pad
    sh = hdr_h + pad + panel_hdr + ph + pad + ftr_h + pad
    sheet = np.full((sh, sw, 4), (0.055, 0.075, 0.115, 1.0), dtype=np.float32)

    fill_rect(sheet, 0, 0, sw, hdr_h, (0.085, 0.115, 0.175, 1.0))
    draw_text(
        sheet,
        "GOOGLEPLEX MOUNTAIN VIEW 3X (600M X 380M) - COMPLETE 3D BLENDER CAMPUS QA",
        20,
        14,
        scale=3,
        color=(0.96, 0.98, 1.0, 1.0),
    )
    draw_text(sheet, stats_line, 20, 42, scale=2, color=(0.66, 0.80, 0.96, 1.0))

    y_p = hdr_h + pad
    panels = [
        (pad, "AERIAL 3/4 GOLDEN-HOUR OVERVIEW (600M X 380M MOUNTAIN VIEW 3X CAMPUS)", img_a),
        (pad + pw + pad, "TOP-DOWN ORTHOGRAPHIC PLAN (NORTH = -Z UP | 16Z GOOGLE MAPS MATCH)", img_o),
    ]
    for x0, title, im in panels:
        fill_rect(sheet, x0, y_p, x0 + pw, y_p + panel_hdr, (0.11, 0.145, 0.215, 1.0))
        draw_text(sheet, title, x0 + 12, y_p + 12, scale=2, color=(0.95, 0.98, 1.0, 1.0))
        sheet[y_p + panel_hdr:y_p + panel_hdr + ph, x0:x0 + pw] = im

    y_f = y_p + panel_hdr + ph + pad
    fill_rect(sheet, pad, y_f, sw - pad, y_f + ftr_h, (0.095, 0.125, 0.185, 1.0))
    draw_text(
        sheet,
        "N: SHORELINE AMPHITHEATRE + BAY POINT + LOT C | W: ATHLETIC FIELD + GOOGLE 2000/1950 | CORE: B40-43 + GRADIENT CANOPY | S: 1098 ALTA + CHARLESTON CAMPUS | E: 2015 + CL2 + 1395",
        pad + 12,
        y_f + 10,
        scale=2,
        color=(0.82, 0.90, 0.98, 1.0),
    )

    save_png_topdown(sheet, FULL_MAP_PREVIEW_PATH, mirror_paths=mirror_paths)


# ---------------------------------------------------------------------------
# Main Build Entry Point
# ---------------------------------------------------------------------------
def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    parser = argparse.ArgumentParser(description="Build 3x Mountain View Googleplex terrain & full campus master model")
    parser.add_argument("--samples", type=int, default=20, help="EEVEE render samples for QA preview")
    parser.add_argument("--skip-render", action="store_true", help="Skip EEVEE preview render")
    parser.add_argument("--mirror-dir", type=str, default=None, help="Optional extra directory to mirror googleplex_full_map.png")
    return parser.parse_args(argv)


def main():
    t0 = time.time()
    args = parse_args()

    reset_scene()
    col_terrain = get_or_create_collection("01_Terrain_Infrastructure")

    # 1. Build sculpted 600m x 380m terrain & outer-ring road/creek/bridge infrastructure
    terrain_objs = build_terrain_infrastructure(col_terrain)
    terrain_tris = count_tris(terrain_objs)
    terrain_bytes = export_objects_glb(terrain_objs, TERRAIN_GLB_PATH)
    terrain_mb = terrain_bytes / (1024.0 * 1024.0)
    print(
        f"[TERRAIN] Exported {TERRAIN_GLB_PATH.relative_to(PROJECT_ROOT)} | "
        f"{terrain_mb:.2f} MB ({terrain_bytes / 1024.0:.1f} KB) | {terrain_tris:,} tris | {len(terrain_objs)} meshes"
    )
    if terrain_mb > 2.8:
        print(f"[WARN] Terrain GLB ({terrain_mb:.2f} MB) exceeds 2.8 MB target!")

    # 2. Import ALL 19 landmark/prop .glb models & assemble complete 3x campus
    campus_added, counts = assemble_full_campus()
    all_campus_objs = terrain_objs + campus_added
    full_tris = count_tris(all_campus_objs)
    full_bytes = export_objects_glb(all_campus_objs, FULL_CAMPUS_GLB_PATH)
    full_mb = full_bytes / (1024.0 * 1024.0)
    print(
        f"[FULL GLB] Exported {FULL_CAMPUS_GLB_PATH.relative_to(PROJECT_ROOT)} | "
        f"{full_mb:.2f} MB | {full_tris:,} tris | "
        f"props: {counts['umbrellas']} umbrellas, {counts['gbikes']} GBike racks, "
        f"{counts['oaks']} Live Oaks, {counts['redwoods']} Redwoods"
    )

    # 3. Set up California golden-hour lighting & cameras and save docs/googleplex_full_campus.blend
    col_rig = get_or_create_collection("06_Lighting_Cameras")
    cam_aerial, cam_ortho = setup_california_lighting_and_cameras(col_rig)
    try:
        bpy.ops.file.pack_all()
    except Exception:
        pass
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(FULL_CAMPUS_BLEND_PATH))
    blend_mb = FULL_CAMPUS_BLEND_PATH.stat().st_size / (1024.0 * 1024.0)
    print(f"[FULL BLEND] Saved {FULL_CAMPUS_BLEND_PATH.relative_to(PROJECT_ROOT)} | {blend_mb:.2f} MB")

    # 4. Compute total public/assets/ payload
    all_glbs = [p for p in ASSETS_ROOT.rglob("*.glb") if p.is_file()]
    total_assets_bytes = sum(p.stat().st_size for p in all_glbs)
    total_assets_mb = total_assets_bytes / (1024.0 * 1024.0)

    # 5. Render headless BLENDER_EEVEE dual-panel 3x QA sheet
    if not args.skip_render:
        stats_line = (
            f"TERRAIN: {terrain_mb:.2f}MB ({terrain_tris:,} TRIS) | "
            f"FULL 3X CAMPUS: {full_mb:.2f}MB ({full_tris:,} TRIS) | "
            f"{counts['oaks']} OAKS, {counts['redwoods']} REDWOODS, {counts['umbrellas']} UMBRELLAS, {counts['gbikes']} GBIKES"
        )
        mirror_paths = []
        if args.mirror_dir:
            mirror_paths.append(Path(args.mirror_dir) / FULL_MAP_PREVIEW_PATH.name)
        render_dual_panel_preview(cam_aerial, cam_ortho, args.samples, stats_line, mirror_paths)
        print(f"[PREVIEW] Rendered {FULL_MAP_PREVIEW_PATH.relative_to(PROJECT_ROOT)} ({FULL_MAP_PREVIEW_PATH.stat().st_size / 1024.0:.1f} KB)")

    print("-" * 96)
    print(
        f"[FULL MAP 3X SUMMARY] Completed in {time.time() - t0:.2f}s | "
        f"Terrain GLB: {terrain_mb:.2f} MB | Full GLB: {full_mb:.2f} MB | Blend: {blend_mb:.2f} MB | "
        f"Total public/assets/: {total_assets_mb:.2f} MB across {len(all_glbs)} GLBs (target <= 20.00 MB)"
    )


if __name__ == "__main__":
    main()

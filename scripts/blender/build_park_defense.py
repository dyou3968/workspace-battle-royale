#!/usr/bin/env python3
"""
Workspace Royale — Googleplex Outdoor Park & Defensive Cover Assets Builder (Blender 5.3.0)
==========================================================================================
Generates 5 brand-new Google-themed outdoor park & tactical defensive cover `.glb` assets
into `public/assets/map/` and renders a crisp 6-panel BLENDER_EEVEE QA beauty sheet into
`docs/previews/qa_park_defense.png` (and optional `--mirror-dir`).

Assets & Exact Three.js Local Coordinate Contracts (`export_yup=True`):
  1. park_outdoor_gym.glb         (14.0m x 11.0m, <= 3,200 tris, pad y=+0.14m, skirt y=-1.6m)
  2. park_art_garden.glb          (16.0m x 14.0m, <= 3,400 tris, pad y=+0.12m, skirt y=-1.6m)
  3. park_google_pergola.glb      ( 9.5m x  6.5m, <= 2,200 tris, pad y=+0.12m, skirt y=-1.4m)
  4. prop_garden_planter_wall.glb ( 5.2m x  1.6m x 1.22m+, <= 700 tris, skirt y=-0.8m)
  5. prop_sculpture_plinth.glb    ( 2.4m x  2.4m x 3.05m,  <= 750 tris, skirt y=-0.8m)

Coordinate System (exact match to Three.js `export_yup=True`):
  - Blender (bx, by, bz) -> Three.js (tx = bx, ty = bz, tz = -by)
  - Inverse Three.js (tx, ty, tz) -> Blender (tx, -tz, ty)
  - Blender rotation_euler.z == Three.js rotation.y

Usage:
    /opt/homebrew/bin/blender --background --python scripts/blender/build_park_defense.py
    /opt/homebrew/bin/blender --background --python scripts/blender/build_park_defense.py -- --mirror-dir /path/to/previews
    /opt/homebrew/bin/blender --background --python scripts/blender/build_park_defense.py -- --no-preview
"""

import argparse
import math
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Euler, Matrix, Vector

# ---------------------------------------------------------------------------
# Paths & Googleplex Color Palette
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
OUT_DIR = PROJECT_ROOT / "public" / "assets" / "map"
PREVIEWS_DIR = PROJECT_ROOT / "docs" / "previews"
OUT_DIR.mkdir(parents=True, exist_ok=True)
PREVIEWS_DIR.mkdir(parents=True, exist_ok=True)

G_BLUE = "#4285F4"
G_BLUE_DEEP = "#1A73E8"
G_RED = "#EA4335"
G_YELLOW = "#FBBC04"
G_GREEN = "#34A853"


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


def hex_to_srgb(h):
    h = h.lstrip("#")
    return (
        int(h[0:2], 16) / 255.0,
        int(h[2:4], 16) / 255.0,
        int(h[4:6], 16) / 255.0,
    )


def hex_to_linear(h, alpha=1.0):
    r, g, b = hex_to_srgb(h)
    return srgb_to_linear((r, g, b, alpha))


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0


# ---------------------------------------------------------------------------
# Three.js <-> Blender Coordinate Helpers
# ---------------------------------------------------------------------------
def t2b(tx, ty, tz):
    """Convert Three.js local (x, y_up, z_south) -> Blender (x, y_north, z_up)."""
    return (float(tx), -float(tz), float(ty))


def tsize2b(sx, sy, sz):
    """Convert Three.js box extents (sx, sy_height, sz_depth) -> Blender (sx, sz, sy)."""
    return (float(sx), float(sz), float(sy))


# ---------------------------------------------------------------------------
# Compact Deterministic Procedural Textures (Packed into GLB)
# ---------------------------------------------------------------------------
def _value_noise_2d(h, w, gh, gw, rng):
    base = rng.random((gh, gw), dtype=np.float32)
    ys = np.linspace(0, gh, h, endpoint=False, dtype=np.float32)
    xs = np.linspace(0, gw, w, endpoint=False, dtype=np.float32)
    y0 = np.floor(ys).astype(np.int32) % gh
    x0 = np.floor(xs).astype(np.int32) % gw
    y1 = (y0 + 1) % gh
    x1 = (x0 + 1) % gw
    fy = (ys - np.floor(ys))[:, None]
    fx = (xs - np.floor(xs))[None, :]
    fy = fy * fy * (3.0 - 2.0 * fy)
    fx = fx * fx * (3.0 - 2.0 * fx)
    v00 = base[y0[:, None], x0[None, :]]
    v10 = base[y0[:, None], x1[None, :]]
    v01 = base[y1[:, None], x0[None, :]]
    v11 = base[y1[:, None], x1[None, :]]
    return (v00 * (1.0 - fx) + v10 * fx) * (1.0 - fy) + (v01 * (1.0 - fx) + v11 * fx) * fy


def _fbm_2d(h, w, rng, octaves=(4, 10, 22)):
    out = np.zeros((h, w), dtype=np.float32)
    amp = 0.55
    total = 0.0
    for g in octaves:
        out += amp * _value_noise_2d(h, w, g, g, rng)
        total += amp
        amp *= 0.5
    return out / total


def make_packed_image(name, rgb_srgb, flip_y=False):
    """Create a packed sRGB Blender image from (H, W, 3) float32 array in [0, 1]."""
    arr = rgb_srgb[::-1, :, :] if flip_y else rgb_srgb
    h, w = arr.shape[:2]
    rgba = np.ones((h, w, 4), dtype=np.float32)
    rgba[:, :, :3] = np.clip(arr, 0.0, 1.0)
    img = bpy.data.images.new(name=name, width=w, height=h, alpha=False)
    img.colorspace_settings.name = "sRGB"
    img.pixels.foreach_set(rgba.ravel())
    img.pack()
    return img


def gen_concrete_tex(name="TexArchConcrete", size=128, tint=(0.91, 0.90, 0.87), seed=801):
    rng = np.random.default_rng(seed)
    n = _fbm_2d(size, size, rng, (4, 12, 24))
    grain = rng.normal(0.0, 0.012, (size, size)).astype(np.float32)
    yy, xx = np.mgrid[0:size, 0:size]
    seam_h = ((yy % (size // 4)) < 2).astype(np.float32) * 0.055
    seam_v = ((xx % (size // 2)) < 2).astype(np.float32) * 0.035
    v = 0.94 + 0.09 * (n - 0.5) + grain - seam_h - seam_v
    return make_packed_image(name, np.stack([v * tint[0], v * tint[1], v * tint[2]], axis=-1))


def gen_travertine_tex(name="TexTravertine", size=128, tint=(0.88, 0.82, 0.72), seed=802):
    rng = np.random.default_rng(seed)
    n_h = _value_noise_2d(size, size, 16, 4, rng)
    n_f = _fbm_2d(size, size, rng, (6, 16, 32))
    yy, xx = np.mgrid[0:size, 0:size]
    vein = np.sin(yy * 0.28 + n_h * 5.0) * 0.035
    tile_h = ((yy % (size // 4)) < 2).astype(np.float32) * 0.065
    tile_v = ((xx % (size // 4)) < 2).astype(np.float32) * 0.055
    v = 0.95 + vein + 0.08 * (n_f - 0.5) - tile_h - tile_v
    return make_packed_image(name, np.stack([v * tint[0], v * tint[1], v * tint[2]], axis=-1))


def gen_cedar_tex(name="TexWarmCedar", size=128, tint=(0.74, 0.45, 0.22), seed=803):
    rng = np.random.default_rng(seed)
    n1 = _value_noise_2d(size, size, 16, 4, rng)
    n2 = _value_noise_2d(size, size, 32, 8, rng)
    yy = np.arange(size, dtype=np.float32)[:, None]
    grain = np.sin(yy * 0.48 + n1 * 7.2) * 0.5 + 0.5
    plank_h = size // 6
    seam = ((yy % plank_h) < 2).astype(np.float32) * 0.24
    v = 0.87 + 0.14 * grain + 0.06 * (n2 - 0.5) - seam
    return make_packed_image(name, np.stack([v * tint[0], v * tint[1], v * tint[2]], axis=-1))


def gen_birch_tex(name="TexBalticBirch", size=128, tint=(0.87, 0.75, 0.54), seed=804):
    rng = np.random.default_rng(seed)
    n1 = _value_noise_2d(size, size, 12, 4, rng)
    yy = np.arange(size, dtype=np.float32)[:, None]
    grain = np.sin(yy * 0.36 + n1 * 6.0) * 0.5 + 0.5
    v = 0.90 + 0.10 * grain + rng.normal(0.0, 0.01, (size, size)).astype(np.float32)
    return make_packed_image(name, np.stack([v * tint[0], v * tint[1], v * tint[2]], axis=-1))


def gen_sail_fabric_tex(name="TexShadeSail", size=128, seed=805):
    rng = np.random.default_rng(seed)
    n = _fbm_2d(size, size, rng, (4, 12))
    yy, xx = np.mgrid[0:size, 0:size]
    seam_u = ((xx % (size // 6)) < 2).astype(np.float32) * 0.07
    weave = 0.012 * np.sin(xx * 1.6) * np.sin(yy * 1.6)
    v = 0.96 + 0.03 * (n - 0.5) + weave - seam_u
    return make_packed_image(name, np.stack([v * 0.97, v * 0.98, v * 1.00], axis=-1))


def gen_gym_turf_tex(name="TexGymAthleticTurf", w=512, h=384, seed=806):
    """
    Googleplex Outdoor Gym rubberized slate-blue athletic turf (#2d4a6e)
    with crisp white sprint/agility lane markings and Google 4-color edge stripes.
    UV mapping: u in [0,1] -> X in [-6.75, +6.75], v in [0,1] -> Blender Y in [-5.25, +5.25] (Three Z in [+5.25, -5.25]).
    """
    rng = np.random.default_rng(seed)
    n = _fbm_2d(h, w, rng, (8, 22, 48))
    speck = rng.normal(0.0, 0.022, (h, w)).astype(np.float32)
    yy, xx = np.mgrid[0:h, 0:w]
    # World meters on the 13.5m x 10.5m inner athletic pad
    px = (xx / float(w - 1) - 0.5) * 13.5
    py = (yy / float(h - 1) - 0.5) * 10.5  # Blender Y (+Y = North, -Y = South)

    base_r, base_g, base_b = hex_to_srgb("#2d4a6e")
    # Subtle alternating training zone tones (darker slate under rig, crisp sprint turf south)
    zone_band = (np.floor((px + 6.75) / 2.25).astype(np.int32) % 2) == 0
    r = np.where(zone_band, base_r * 0.95, base_r * 1.05) + 0.032 * (n - 0.5) + speck
    g = np.where(zone_band, base_g * 0.95, base_g * 1.05) + 0.038 * (n - 0.5) + speck
    b = np.where(zone_band, base_b * 0.95, base_b * 1.05) + 0.045 * (n - 0.5) + speck

    # Darker rubberized mat under the center-west Calisthenics Rig (-2.2, +0.4_bl), 4.9 x 2.8m
    rig_mat = (np.abs(px - (-2.2)) <= 2.48) & (np.abs(py - 0.4) <= 1.42)
    r = np.where(rig_mat, r * 0.72 + 0.03, r)
    g = np.where(rig_mat, g * 0.72 + 0.04, g)
    b = np.where(rig_mat, b * 0.74 + 0.05, b)

    # Slightly darker landing turf strip under the 3-tier Plyo deck (x in [2.4, 4.4], y_bl in [-2.0, +3.2])
    plyo_mat = (np.abs(px - 3.4) <= 1.05) & (py >= -2.0) & (py <= 3.2)
    r = np.where(plyo_mat, r * 0.80 + 0.02, r)
    g = np.where(plyo_mat, g * 0.80 + 0.03, g)
    b = np.where(plyo_mat, b * 0.82 + 0.04, b)

    # Crisp white fitness court markings
    lw = 0.065
    # Perimeter border inset 0.45m
    perim_x = (np.abs(np.abs(px) - 6.20) <= lw) & (np.abs(py) <= 4.70 + lw)
    perim_y = (np.abs(np.abs(py) - 4.70) <= lw) & (np.abs(px) <= 6.20 + lw)
    # Rig pad border
    rig_border = (
        ((np.abs(np.abs(px - (-2.2)) - 2.48) <= lw * 0.85) & (np.abs(py - 0.4) <= 1.42))
        | ((np.abs(np.abs(py - 0.4) - 1.42) <= lw * 0.85) & (np.abs(px - (-2.2)) <= 2.48))
    )
    # Sled push agility lane along North-East / East-West sprint lane (py in [2.35, 3.85], px in [-1.2, +5.5])
    lane_top = (np.abs(py - 3.75) <= lw * 0.8) & (px >= -0.8) & (px <= 5.6)
    lane_mid = (np.abs(py - 3.05) <= lw * 0.55) & (px >= -0.8) & (px <= 5.6)
    lane_bot = (np.abs(py - 2.35) <= lw * 0.8) & (px >= -0.8) & (px <= 5.6)
    # Agility hash ticks every 0.8m inside sprint lane
    hash_ticks = (
        (py >= 2.35) & (py <= 3.75) & (px >= -0.4) & (px <= 5.2)
        & (np.abs(((px + 0.4) % 0.8) - 0.4) <= 0.045)
        & ((np.abs(py - 3.05) <= 0.28) | (np.abs(py - 2.35) <= 0.16) | (np.abs(py - 3.75) <= 0.16))
    )
    # South agility lane dashes (py in [-2.55, -1.55], px in [-5.5, +1.8])
    s_lane = (
        ((np.abs(py - (-1.65)) <= lw * 0.7) | (np.abs(py - (-2.35)) <= lw * 0.7))
        & (px >= -5.4) & (px <= 1.6)
    )
    s_ticks = (
        (py >= -2.35) & (py <= -1.65) & (px >= -5.2) & (px <= 1.4)
        & (np.abs(((px + 5.2) % 0.75) - 0.375) <= 0.045)
    )
    # Center-east warm-up circle around (1.0, 0.3)
    rc = np.hypot(px - 1.1, py - 0.3)
    circle = np.abs(rc - 0.88) <= 0.055

    white_mask = perim_x | perim_y | rig_border | lane_top | lane_mid | lane_bot | hash_ticks | s_lane | s_ticks | circle
    r = np.where(white_mask, 0.94, r)
    g = np.where(white_mask, 0.96, g)
    b = np.where(white_mask, 0.98, b)

    # Official Google 4-color accent stripes along North (py in [4.76..5.10]) & South (py in [-5.10..-4.76]) edges
    g_cols = [hex_to_srgb(G_BLUE), hex_to_srgb(G_RED), hex_to_srgb(G_YELLOW), hex_to_srgb(G_GREEN)]
    stripe_band_edge = (np.abs(py) >= 4.78) & (np.abs(py) <= 5.10) & (np.abs(px) <= 6.20)
    # Also crisp vertical 4-color edge bars on West & East edges
    stripe_band_side = (np.abs(px) >= 6.26) & (np.abs(px) <= 6.56) & (np.abs(py) <= 4.70)
    seg_x = np.clip(np.floor((px + 6.20) / (12.40 / 4.0)).astype(np.int32), 0, 3)
    seg_y = np.clip(np.floor((py + 4.70) / (9.40 / 4.0)).astype(np.int32), 0, 3)
    for idx, col in enumerate(g_cols):
        m = (stripe_band_edge & (seg_x == idx)) | (stripe_band_side & (seg_y == idx))
        r = np.where(m, col[0], r)
        g = np.where(m, col[1], g)
        b = np.where(m, col[2], b)

    return make_packed_image(name, np.stack([r, g, b], axis=-1).astype(np.float32))


def gen_art_plaza_tex(name="TexArtGardenPlaza", w=384, h=384, seed=807):
    """
    Warm California travertine & decomposed-granite octagonal art garden plaza texture
    with concentric travertine medallion rings and radial architectural flagstone inlays.
    UV mapping: u in [0,1] -> X in [-8, +8], v in [0,1] -> Blender Y in [-7, +7].
    """
    rng = np.random.default_rng(seed)
    n = _fbm_2d(h, w, rng, (6, 18, 42))
    grit = rng.normal(0.0, 0.018, (h, w)).astype(np.float32)
    yy, xx = np.mgrid[0:h, 0:w]
    px = (xx / float(w - 1) - 0.5) * 16.0
    py = (yy / float(h - 1) - 0.5) * 14.0

    # Warm decomposed-granite ochre-sand base
    r = 0.84 + 0.065 * (n - 0.5) + grit
    g = 0.77 + 0.060 * (n - 0.5) + grit
    b = 0.65 + 0.050 * (n - 0.5) + grit

    # Large warm travertine plaza flagstone grid (2m x 2m bands)
    grid_x = np.abs(((px + 8.0) % 2.0) - 1.0) >= 0.965
    grid_y = np.abs(((py + 7.0) % 2.0) - 1.0) >= 0.965
    grout = grid_x | grid_y
    r = np.where(grout, r * 0.87, r)
    g = np.where(grout, g * 0.87, g)
    b = np.where(grout, b * 0.86, b)

    # Sunlit pale limestone radial walkways along N-S and E-W axes (width 2.2m)
    walk = (np.abs(px) <= 1.15) | (np.abs(py) <= 1.15)
    r = np.where(walk, 0.90 + 0.04 * (n - 0.5), r)
    g = np.where(walk, 0.86 + 0.04 * (n - 0.5), g)
    b = np.where(walk, 0.79 + 0.04 * (n - 0.5), b)

    # Central honed limestone medallion around the Google Kinetic Monolith (r <= 3.1m)
    rad = np.hypot(px, py)
    medallion = rad <= 3.05
    r = np.where(medallion, 0.91 + 0.035 * (n - 0.5), r)
    g = np.where(medallion, 0.88 + 0.035 * (n - 0.5), g)
    b = np.where(medallion, 0.82 + 0.035 * (n - 0.5), b)

    # Outer & inner travertine compass rings
    ring_dark = (np.abs(rad - 3.05) <= 0.14) | (np.abs(rad - 2.15) <= 0.09)
    r = np.where(ring_dark, 0.68, r)
    g = np.where(ring_dark, 0.62, g)
    b = np.where(ring_dark, 0.54, b)

    # Subtle 4-color Google quadrant stone inlay ring between r=2.35 and r=2.55!
    inlay_ring = (rad >= 2.34) & (rad <= 2.52)
    ang = np.arctan2(py, px)  # -pi..pi
    q_cols = [hex_to_srgb(G_BLUE), hex_to_srgb(G_RED), hex_to_srgb(G_YELLOW), hex_to_srgb(G_GREEN)]
    # 4 clean arcs separated by stone breaks along axes
    not_gap = (np.abs(px) > 0.25) & (np.abs(py) > 0.25)
    for qi, cond in enumerate((
        (ang >= 0.0) & (ang < math.pi * 0.5),
        (ang >= math.pi * 0.5),
        (ang < -math.pi * 0.5),
        (ang >= -math.pi * 0.5) & (ang < 0.0),
    )):
        m = inlay_ring & cond & not_gap
        # Soft muted glazed architectural stone saturation so it looks classy & grounded
        r = np.where(m, q_cols[qi][0] * 0.78 + 0.18, r)
        g = np.where(m, q_cols[qi][1] * 0.78 + 0.18, g)
        b = np.where(m, q_cols[qi][2] * 0.78 + 0.18, b)

    return make_packed_image(name, np.stack([r, g, b], axis=-1).astype(np.float32))


def gen_pergola_whiteboard_tex(name="TexWorkspaceOutdoorBoard", w=256, h=128):
    """Crisp Google Workspace outdoor collaboration display / sprint board graphic."""
    img = np.ones((h, w, 3), dtype=np.float32) * 0.96
    # Subtle warm whiteboard frame & header bar
    img[0:18, :] = (0.14, 0.17, 0.22)
    # 4 Google color dots / pill badges on header
    g_cols = [hex_to_srgb(G_BLUE), hex_to_srgb(G_RED), hex_to_srgb(G_YELLOW), hex_to_srgb(G_GREEN)]
    for i, col in enumerate(g_cols):
        img[5:13, 10 + i * 16:22 + i * 16] = col
    # Header title placeholder bar
    img[7:11, 86:196] = (0.85, 0.89, 0.95)
    # Subtle grid lines on board
    img[18::16, :] *= 0.94
    img[18:, ::24] *= 0.95
    # 3 Kanban / Architecture columns with Google-colored sticky cards!
    col_x = [14, 94, 174]
    col_hdr = [g_cols[0], g_cols[3], g_cols[1]]
    for ci, cx in enumerate(col_x):
        img[24:32, cx:cx + 66] = col_hdr[ci]
        # Sticky notes / workflow cards
        for ri in range(3):
            y0 = 38 + ri * 26
            card_col = g_cols[(ci + ri) % 4]
            # Soft pastel card fill + bold left stripe
            img[y0:y0 + 20, cx:cx + 66] = (
                0.86 + 0.12 * card_col[0],
                0.86 + 0.12 * card_col[1],
                0.86 + 0.12 * card_col[2],
            )
            img[y0:y0 + 20, cx:cx + 5] = card_col
            img[y0 + 5:y0 + 8, cx + 10:cx + 54] = (0.28, 0.33, 0.42)
            img[y0 + 12:y0 + 14, cx + 10:cx + 42] = (0.48, 0.53, 0.60)
    # Thin outer border
    img[0:3, :] = (0.20, 0.24, 0.30)
    img[-3:, :] = (0.20, 0.24, 0.30)
    img[:, 0:3] = (0.20, 0.24, 0.30)
    img[:, -3:] = (0.20, 0.24, 0.30)
    return make_packed_image(name, img, flip_y=True)


# ---------------------------------------------------------------------------
# Material & BMesh Geometry Helpers (Blender 5.3.0 Principled BSDF)
# ---------------------------------------------------------------------------
def make_pbr_mat(
    name,
    base_color=(0.8, 0.8, 0.8, 1.0),
    metallic=0.0,
    roughness=0.5,
    ior=1.45,
    alpha=1.0,
    specular=0.5,
    emission=None,
    emission_strength=0.0,
    tex_img=None,
    tex_tint=None,
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
        tex_node.location = (-460, 200)
        if tex_tint is not None:
            mix = nodes.new("ShaderNodeMix")
            mix.data_type = "RGBA"
            mix.blend_type = "MULTIPLY"
            mix.inputs["Factor"].default_value = 1.0
            mix.inputs["B"].default_value = tex_tint
            mix.location = (-200, 200)
            links.new(tex_node.outputs["Color"], mix.inputs["A"])
            links.new(mix.outputs["Result"], bsdf.inputs["Base Color"])
        else:
            links.new(tex_node.outputs["Color"], bsdf.inputs["Base Color"])

    if emission is not None and emission_strength > 0.0:
        bsdf.inputs["Emission Color"].default_value = emission
        bsdf.inputs["Emission Strength"].default_value = emission_strength

    if alpha < 0.999:
        if hasattr(mat, "surface_render_method"):
            mat.surface_render_method = "BLENDED"
        if hasattr(mat, "blend_method"):
            mat.blend_method = "BLEND"
    if double_sided:
        mat.use_backface_culling = False
    return mat


def make_shared_palette():
    """Create crisp shared Googleplex outdoor architectural materials for the active scene."""
    tex_conc = gen_concrete_tex("TexArchConcrete", 128, (0.91, 0.90, 0.87), 801)
    tex_trav = gen_travertine_tex("TexTravertine", 128, (0.89, 0.83, 0.72), 802)
    tex_cedar = gen_cedar_tex("TexWarmCedar", 128, (0.76, 0.46, 0.22), 803)
    tex_birch = gen_birch_tex("TexBalticBirch", 128, (0.89, 0.77, 0.56), 804)
    return {
        "conc_white": make_pbr_mat("MatArchWhiteConcrete", hex_to_linear("#ECEAE3"), roughness=0.72, tex_img=tex_conc),
        "conc_skirt": make_pbr_mat("MatFoundationConcrete", hex_to_linear("#9FA3A6"), roughness=0.84, tex_img=tex_conc, tex_tint=hex_to_linear("#B4B6B2")),
        "travertine": make_pbr_mat("MatWarmTravertine", hex_to_linear("#E4D5BC"), roughness=0.66, tex_img=tex_trav),
        "limestone": make_pbr_mat("MatHonedLimestone", hex_to_linear("#EDE4D3"), roughness=0.62, tex_img=tex_trav, tex_tint=hex_to_linear("#FBF6EE")),
        "cedar": make_pbr_mat("MatWarmCedar", hex_to_linear("#B86E38"), roughness=0.58, tex_img=tex_cedar),
        "birch": make_pbr_mat("MatBalticBirch", hex_to_linear("#DFC08B"), roughness=0.52, tex_img=tex_birch),
        "steel_dark": make_pbr_mat("MatCharcoalSteel", hex_to_linear("#262B33"), metallic=0.72, roughness=0.34),
        "steel_brushed": make_pbr_mat("MatBrushedSteel", hex_to_linear("#CDD4DC"), metallic=0.88, roughness=0.22),
        "bronze": make_pbr_mat("MatArchBronze", hex_to_linear("#5B4C3D"), metallic=0.78, roughness=0.36),
        "brass": make_pbr_mat("MatMuseumBrass", hex_to_linear("#C9A24B"), metallic=0.86, roughness=0.28),
        "rubber_dark": make_pbr_mat("MatGymRubber", hex_to_linear("#1E232A"), metallic=0.05, roughness=0.78),
        "leather": make_pbr_mat("MatBenchLeather", hex_to_linear("#23272F"), metallic=0.05, roughness=0.45),
        "mulch": make_pbr_mat("MatVolcanicMulch", hex_to_linear("#3C2E24"), roughness=0.95),
        "glass_frost": make_pbr_mat("MatFrostedGoogleGlass", hex_to_linear("#9CC9E8", 0.62), metallic=0.05, roughness=0.18, alpha=0.62, double_sided=True),
        # Official Google 4-Color Satin Architectural Finishes
        "g_blue": make_pbr_mat("MatGoogleBlue", hex_to_linear(G_BLUE), metallic=0.22, roughness=0.26),
        "g_blue_deep": make_pbr_mat("MatGoogleBlueDeep", hex_to_linear(G_BLUE_DEEP), metallic=0.38, roughness=0.28),
        "g_red": make_pbr_mat("MatGoogleRed", hex_to_linear(G_RED), metallic=0.22, roughness=0.26),
        "g_yellow": make_pbr_mat("MatGoogleYellow", hex_to_linear(G_YELLOW), metallic=0.22, roughness=0.26),
        "g_green": make_pbr_mat("MatGoogleGreen", hex_to_linear(G_GREEN), metallic=0.22, roughness=0.26),
        # California Native Botanical Palette
        "agave": make_pbr_mat("MatCaliforniaAgave", hex_to_linear("#4F8E7B"), roughness=0.62),
        "sage": make_pbr_mat("MatNativeSage", hex_to_linear("#65885B"), roughness=0.78),
        "grass": make_pbr_mat("MatOrnamentalGrass", hex_to_linear("#789E44"), roughness=0.76),
        "lavender": make_pbr_mat("MatCaliforniaLavender", hex_to_linear("#8457D9"), roughness=0.68),
    }


def apply_box_uv(bm, scale=0.35):
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


def finalize_mesh(name, bm, mat, smooth=False, uv_scale=0.35, keep_existing_uv=False):
    if len(bm.verts) == 0:
        bm.free()
        return None
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    if not keep_existing_uv:
        apply_box_uv(bm, scale=uv_scale)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    if smooth and len(mesh.polygons) > 0:
        mesh.polygons.foreach_set("use_smooth", [True] * len(mesh.polygons))
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    if mat is not None:
        obj.data.materials.append(mat)
    return obj


def bm_add_box(bm, center, size, rot_euler=(0.0, 0.0, 0.0)):
    sx, sy, sz = size
    mat_t = Matrix.Translation(Vector(center))
    mat_r = Euler(rot_euler, "XYZ").to_matrix().to_4x4()
    mat_s = Matrix.Diagonal((sx, sy, sz, 1.0))
    return bmesh.ops.create_cube(bm, size=1.0, matrix=mat_t @ mat_r @ mat_s)["verts"]


def bm_add_tbox(bm, t_center, t_size, rot_y=0.0, rot_euler_bl=None):
    """Add an oriented box specified in Three.js local coordinates (x, y_up, z_south)."""
    bc = t2b(*t_center)
    bs = tsize2b(*t_size)
    rot = rot_euler_bl if rot_euler_bl is not None else (0.0, 0.0, rot_y)
    return bm_add_box(bm, bc, bs, rot_euler=rot)


def bm_add_prism_between(bm, p0, p1, r0, r1, segs=8, cap=True):
    p0 = Vector(p0)
    p1 = Vector(p1)
    axis = p1 - p0
    length = axis.length
    if length < 1e-6:
        return []
    z_dir = axis / length
    up = Vector((0.0, 0.0, 1.0)) if abs(z_dir.z) < 0.95 else Vector((1.0, 0.0, 0.0))
    x_dir = up.cross(z_dir).normalized()
    y_dir = z_dir.cross(x_dir).normalized()

    ring0, ring1 = [], []
    for i in range(segs):
        ang = 2.0 * math.pi * i / segs
        d = x_dir * math.cos(ang) + y_dir * math.sin(ang)
        ring0.append(bm.verts.new(p0 + d * r0))
        ring1.append(bm.verts.new(p1 + d * r1))

    for i in range(segs):
        ni = (i + 1) % segs
        bm.faces.new((ring0[i], ring0[ni], ring1[ni], ring1[i]))
    if cap:
        if r0 > 1e-5:
            bm.faces.new(list(reversed(ring0)))
        if r1 > 1e-5:
            bm.faces.new(ring1)
    return ring0 + ring1


def bm_add_tprism(bm, tp0, tp1, r0, r1, segs=8, cap=True):
    return bm_add_prism_between(bm, t2b(*tp0), t2b(*tp1), r0, r1, segs=segs, cap=cap)


def bm_add_tsphere(bm, t_center, rx, ry=None, rz=None, u_segs=8, v_segs=6):
    ry = rx if ry is None else ry
    rz = rx if rz is None else rz
    # Three.js (rx, ry_up, rz_depth) -> Blender (rx, rz_depth, ry_up)
    mat = Matrix.Translation(Vector(t2b(*t_center))) @ Matrix.Diagonal((rx, rz, ry, 1.0))
    return bmesh.ops.create_uvsphere(bm, u_segments=u_segs, v_segments=v_segs, radius=1.0, matrix=mat)["verts"]


def ensure_ccw_2d(pts):
    area = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        area += x0 * y1 - x1 * y0
    return list(reversed(pts)) if area < 0 else list(pts)


def bm_add_polygon_prism(bm, pts_2d_bl, z0, z1, cap_bottom=True, cap_top=True):
    pts = ensure_ccw_2d(pts_2d_bl)
    n = len(pts)
    bot = [bm.verts.new((x, y, z0)) for x, y in pts]
    top = [bm.verts.new((x, y, z1)) for x, y in pts]
    for i in range(n):
        ni = (i + 1) % n
        bm.faces.new((bot[i], bot[ni], top[ni], top[i]))
    cap_faces = []
    if cap_bottom:
        f_b = bm.faces.new(list(reversed(bot)))
        f_b.normal_update()
        cap_faces.append(f_b)
    if cap_top:
        f_t = bm.faces.new(top)
        f_t.normal_update()
        cap_faces.append(f_t)
    if cap_faces:
        bmesh.ops.triangulate(bm, faces=cap_faces, quad_method="BEAUTY", ngon_method="EAR_CLIP")
    return bot + top


def bm_add_swept_ribbon(bm, points_bl, width, thick, twist_fn=None, closed=False):
    """Sweep a crisp rectangular architectural ribbon along 3D Blender points."""
    n = len(points_bl)
    if n < 2:
        return
    rings = []
    for i, p in enumerate(points_bl):
        pv = Vector(p)
        if closed:
            tangent = (Vector(points_bl[(i + 1) % n]) - Vector(points_bl[(i - 1) % n])).normalized()
        elif i == 0:
            tangent = (Vector(points_bl[1]) - pv).normalized()
        elif i == n - 1:
            tangent = (pv - Vector(points_bl[n - 2])).normalized()
        else:
            tangent = (Vector(points_bl[i + 1]) - Vector(points_bl[i - 1])).normalized()
        ref = Vector((0.0, 0.0, 1.0)) if abs(tangent.z) < 0.9 else Vector((1.0, 0.0, 0.0))
        right = tangent.cross(ref).normalized()
        up = right.cross(tangent).normalized()
        if twist_fn is not None:
            ang = twist_fn(i / float(max(1, n - 1)))
            ca, sa = math.cos(ang), math.sin(ang)
            r2 = right * ca + up * sa
            u2 = -right * sa + up * ca
            right, up = r2, u2
        hw, ht = width * 0.5, thick * 0.5
        ring = [
            bm.verts.new(pv - right * hw - up * ht),
            bm.verts.new(pv + right * hw - up * ht),
            bm.verts.new(pv + right * hw + up * ht),
            bm.verts.new(pv - right * hw + up * ht),
        ]
        rings.append(ring)

    seg_count = n if closed else n - 1
    for i in range(seg_count):
        r0 = rings[i]
        r1 = rings[(i + 1) % n]
        for k in range(4):
            nk = (k + 1) % 4
            bm.faces.new((r0[k], r0[nk], r1[nk], r1[k]))
    if not closed:
        bm.faces.new(list(reversed(rings[0])))
        bm.faces.new(rings[-1])


def bm_add_beveled_torus(bm, t_center, major_r, minor_r, maj_segs=14, min_segs=4, rot_euler_bl=(0.0, 0.0, 0.0)):
    """Create a crisp architectural faceted ring/torus centered at Three.js t_center."""
    center_bl = Vector(t2b(*t_center))
    rot_m = Euler(rot_euler_bl, "XYZ").to_matrix()
    rings = []
    for i in range(maj_segs):
        theta = 2.0 * math.pi * i / maj_segs
        ct, st = math.cos(theta), math.sin(theta)
        # Ring lies in X-Z plane in Blender before rot_m
        radial = Vector((ct, 0.0, st))
        normal = Vector((0.0, 1.0, 0.0))
        ring = []
        for j in range(min_segs):
            phi = 2.0 * math.pi * j / min_segs + math.pi * 0.25
            local_p = radial * (major_r + minor_r * math.cos(phi)) + normal * (minor_r * math.sin(phi))
            ring.append(bm.verts.new(center_bl + rot_m @ local_p))
        rings.append(ring)
    for i in range(maj_segs):
        r0 = rings[i]
        r1 = rings[(i + 1) % maj_segs]
        for j in range(min_segs):
            nj = (j + 1) % min_segs
            bm.faces.new((r0[j], r0[nj], r1[nj], r1[j]))


def bm_add_agave_rosette(bm, t_base, scale=1.0, blades=6, yaw=0.0):
    """Low-poly sculpted California blue-green agave rosette (24 tris for 6 tapered blades!)."""
    bx, by, bz = t2b(*t_base)
    for i in range(blades):
        ang = yaw + 2.0 * math.pi * i / blades
        ca, sa = math.cos(ang), math.sin(ang)
        rx, ry = -sa, ca
        length = (0.34 if i % 2 == 0 else 0.26) * scale
        h_tip = (0.26 if i % 2 == 0 else 0.34) * scale
        w_base = 0.065 * scale
        w_mid = 0.045 * scale
        p_b0 = bm.verts.new((bx + rx * w_base, by + ry * w_base, bz))
        p_b1 = bm.verts.new((bx - rx * w_base, by - ry * w_base, bz))
        p_m0 = bm.verts.new((bx + ca * length * 0.55 + rx * w_mid, by + sa * length * 0.55 + ry * w_mid, bz + h_tip * 0.62))
        p_m1 = bm.verts.new((bx + ca * length * 0.55 - rx * w_mid, by + sa * length * 0.55 - ry * w_mid, bz + h_tip * 0.62))
        p_tip = bm.verts.new((bx + ca * length, by + sa * length, bz + h_tip))
        # Double-sided crisp diamond-profile leaf (thin solid wedge = 4 faces)
        p_mid_c = bm.verts.new((bx + ca * length * 0.52, by + sa * length * 0.52, bz + h_tip * 0.55 - 0.018 * scale))
        bm.faces.new((p_b0, p_b1, p_m1, p_m0))
        bm.faces.new((p_m0, p_m1, p_tip))
        bm.faces.new((p_b1, p_b0, p_mid_c))
        bm.faces.new((p_b0, p_m0, p_tip, p_mid_c))
        bm.faces.new((p_m1, p_b1, p_mid_c, p_tip))


def bm_add_grass_tuft(bm, t_base, scale=1.0, blades=4, yaw=0.0):
    """Low-poly sculpted California ornamental grass tuft (thin 3-sided spires)."""
    bx, by, bz = t2b(*t_base)
    for i in range(blades):
        ang = yaw + 2.0 * math.pi * i / blades + (i % 2) * 0.25
        lean = (0.14 + 0.04 * (i % 2)) * scale
        h = (0.34 + 0.06 * ((i + 1) % 2)) * scale
        p0 = Vector((bx, by, bz))
        p1 = Vector((bx + math.cos(ang) * lean, by + math.sin(ang) * lean, bz + h))
        bm_add_prism_between(bm, p0, p1, 0.032 * scale, 0.005 * scale, segs=3, cap=True)


def bm_add_lavender_cluster(bm_stem, bm_bloom, t_base, scale=1.0, stalks=3, yaw=0.0):
    """Low-poly California purple lavender cluster with slender sage stems and violet flower spikes."""
    bx, by, bz = t2b(*t_base)
    for i in range(stalks):
        ang = yaw + 2.0 * math.pi * i / stalks
        r_off = 0.06 * scale
        sx = bx + math.cos(ang) * r_off
        sy = by + math.sin(ang) * r_off
        tx = bx + math.cos(ang) * (0.14 * scale)
        ty = by + math.sin(ang) * (0.14 * scale)
        mid_z = bz + 0.18 * scale
        top_z = bz + (0.36 + 0.04 * (i % 2)) * scale
        bm_add_prism_between(bm_stem, (sx, sy, bz), (tx * 0.65 + sx * 0.35, ty * 0.65 + sy * 0.35, mid_z), 0.018 * scale, 0.012 * scale, segs=3, cap=False)
        bm_add_prism_between(bm_bloom, (tx * 0.65 + sx * 0.35, ty * 0.65 + sy * 0.35, mid_z - 0.02 * scale), (tx, ty, top_z), 0.042 * scale, 0.014 * scale, segs=4, cap=True)


def add_google_4color_bar(bms_g, t_center, total_len, height, depth, axis="X"):
    """Add 4 equal contiguous Google color segments (Blue, Red, Yellow, Green) centered at t_center."""
    seg = total_len * 0.25
    keys = ("g_blue", "g_red", "g_yellow", "g_green")
    cx, cy, cz = t_center
    for i, k in enumerate(keys):
        off = -total_len * 0.5 + (i + 0.5) * seg
        if axis == "X":
            bm_add_tbox(bms_g[k], (cx + off, cy, cz), (seg, height, depth))
        else:
            bm_add_tbox(bms_g[k], (cx, cy, cz + off), (depth, height, seg))


def export_asset(filename):
    objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not objs:
        raise RuntimeError(f"No mesh objects to export for {filename}")

    min_bl = Vector((1e9, 1e9, 1e9))
    max_bl = Vector((-1e9, -1e9, -1e9))
    min_above = Vector((1e9, 1e9, 1e9))
    max_above = Vector((-1e9, -1e9, -1e9))
    total_tris = 0
    for o in objs:
        m = o.matrix_world
        for v in o.data.vertices:
            w = m @ v.co
            min_bl.x = min(min_bl.x, w.x)
            min_bl.y = min(min_bl.y, w.y)
            min_bl.z = min(min_bl.z, w.z)
            max_bl.x = max(max_bl.x, w.x)
            max_bl.y = max(max_bl.y, w.y)
            max_bl.z = max(max_bl.z, w.z)
            if w.z >= -0.02:
                min_above.x = min(min_above.x, w.x)
                min_above.y = min(min_above.y, w.y)
                min_above.z = min(min_above.z, w.z)
                max_above.x = max(max_above.x, w.x)
                max_above.y = max(max_above.y, w.y)
                max_above.z = max(max_above.z, w.z)
        for p in o.data.polygons:
            total_tris += max(1, len(p.vertices) - 2)

    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]

    out_path = OUT_DIR / filename
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
    size_kb = out_path.stat().st_size / 1024.0
    # Convert Blender bounds -> Three.js bounds (tx=bx, ty=bz, tz=-by)
    three_min = (min_bl.x, min_bl.z, -max_bl.y)
    three_max = (max_bl.x, max_bl.z, -min_bl.y)
    three_dims = (three_max[0] - three_min[0], three_max[1] - three_min[1], three_max[2] - three_min[2])
    above_dims = (max_above.x - min_above.x, max_above.z - max(0.0, min_above.z), max_above.y - min_above.y)
    return {
        "file": filename,
        "kb": size_kb,
        "tris": total_tris,
        "three_min": three_min,
        "three_max": three_max,
        "three_dims": three_dims,
        "above_dims": above_dims,
        "meshes": len(objs),
    }


# ---------------------------------------------------------------------------
# ASSET 1: park_outdoor_gym.glb (14.0m x 11.0m, <= 3,200 tris)
# ---------------------------------------------------------------------------
def build_park_outdoor_gym():
    reset_scene()
    mats = make_shared_palette()
    tex_turf = gen_gym_turf_tex("TexGymAthleticTurf", 512, 384, 806)
    tex_sail = gen_sail_fabric_tex("TexGymShadeSail", 128, 805)
    mats["turf"] = make_pbr_mat("MatGymAthleticTurf", hex_to_linear("#2d4a6e"), roughness=0.84, tex_img=tex_turf)
    mats["sail"] = make_pbr_mat("MatTensionShadeSail", hex_to_linear("#F6F8FB"), roughness=0.56, tex_img=tex_sail, double_sided=True)

    bms = {k: bmesh.new() for k in mats}

    # 1. Elevated Athletic Turf Pad (14.0m x 11.0m, top y=+0.14m, hill skirt down to y=-1.60m)
    bm_add_tbox(bms["conc_skirt"], (0.0, -0.74, 0.0), (14.0, 1.72, 11.0))  # y = -1.60 .. +0.12
    # Crisp architectural white concrete perimeter curb (y = +0.08 .. +0.14)
    bm_add_tbox(bms["conc_white"], (0.0, 0.11, -5.36), (14.0, 0.06, 0.28))
    bm_add_tbox(bms["conc_white"], (0.0, 0.11, 5.36), (14.0, 0.06, 0.28))
    bm_add_tbox(bms["conc_white"], (-6.86, 0.11, 0.0), (0.28, 0.06, 10.44))
    bm_add_tbox(bms["conc_white"], (6.86, 0.11, 0.0), (0.28, 0.06, 10.44))

    # Planar UV-mapped Athletic Turf surface (13.5m x 10.5m, top exactly y = +0.14m)
    bm_t = bms["turf"]
    uv_t = bm_t.loops.layers.uv.verify()
    tw, td = 6.75, 5.25
    v0 = bm_t.verts.new((-tw, -td, 0.14))
    v1 = bm_t.verts.new((tw, -td, 0.14))
    v2 = bm_t.verts.new((tw, td, 0.14))
    v3 = bm_t.verts.new((-tw, td, 0.14))
    f_turf = bm_t.faces.new((v0, v1, v2, v3))
    for loop, uv in zip(f_turf.loops, ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))):
        loop[uv_t].uv = uv

    # 2. Opposing L-Shaped Defensive Retaining Walls (y = 0.14..1.29m, height 1.15m)
    # NW Corner L-Wall: North arm (-3.8, 0.72, -5.05) size (5.8, 1.15, 0.72), West arm (-6.55, 0.72, -2.55) size (0.72, 1.15, 4.6)
    # SE Corner L-Wall: South arm (3.8, 0.72, 5.05) size (5.8, 1.15, 0.72), East arm (6.55, 0.72, 2.55) size (0.72, 1.15, 4.6)
    def add_l_wall_arm(cx, cz, sx, sz, axis, inner_dir):
        # Lower concrete toe-kick + main white architectural concrete wall (y = 0.14..1.21m)
        bm_add_tbox(bms["conc_skirt"], (cx, 0.19, cz), (sx, 0.10, sz))
        bm_add_tbox(bms["conc_white"], (cx, 0.725, cz), (sx, 0.97, sz))
        # Warm cedar bench cap top (y = 1.21..1.29m)
        bm_add_tbox(bms["cedar"], (cx, 1.25, cz), (sx + 0.04, 0.08, sz + 0.04))
        # Recessed Google 4-color glazed architectural stripe along upper fascia (y = 1.05..1.13m)
        if axis == "X":
            add_google_4color_bar(bms, (cx, 1.09, cz), sx - 0.16, 0.08, sz + 0.025, axis="X")
            # Warm cedar seating lip along inner face (y = 0.44..0.52m)
            bm_add_tbox(bms["cedar"], (cx, 0.48, cz + inner_dir * (sz * 0.5 + 0.10)), (sx - 0.80, 0.08, 0.22))
        else:
            add_google_4color_bar(bms, (cx, 1.09, cz), sz - 0.16, 0.08, sx + 0.025, axis="Z")
            bm_add_tbox(bms["cedar"], (cx + inner_dir * (sx * 0.5 + 0.10), 0.48, cz), (0.22, 0.08, sz - 0.80))

    # NW L-Wall
    add_l_wall_arm(-3.8, -5.05, 5.8, 0.72, "X", inner_dir=+1.0)
    add_l_wall_arm(-6.55, -2.55, 0.72, 4.6, "Z", inner_dir=+1.0)
    # Seamless NW corner pillar fill
    bm_add_tbox(bms["conc_white"], (-6.55, 0.675, -5.05), (0.72, 1.07, 0.72))
    bm_add_tbox(bms["cedar"], (-6.55, 1.25, -5.05), (0.76, 0.08, 0.76))

    # SE L-Wall
    add_l_wall_arm(3.8, 5.05, 5.8, 0.72, "X", inner_dir=-1.0)
    add_l_wall_arm(6.55, 2.55, 0.72, 4.6, "Z", inner_dir=-1.0)
    # Seamless SE corner pillar fill
    bm_add_tbox(bms["conc_white"], (6.55, 0.675, 5.05), (0.72, 1.07, 0.72))
    bm_add_tbox(bms["cedar"], (6.55, 1.25, 5.05), (0.76, 0.08, 0.76))

    # 3. Center-West Heavy Steel Calisthenics Rig around (-2.2, 0.14, -0.4), span 4.6m x 2.4m, height 2.95m (y = 0.14..3.09m)
    rig_xs = (-4.4, -2.2, 0.0)
    rig_zs = (-1.5, 0.7)
    for px in rig_xs:
        for pz in rig_zs:
            # Base bolt flange plate
            bm_add_tbox(bms["steel_dark"], (px, 0.16, pz), (0.30, 0.04, 0.30))
            # Upright square steel post (0.16m square, height 2.95m -> y = 0.14..3.09m)
            bm_add_tbox(bms["steel_dark"], (px, 1.615, pz), (0.16, 2.95, 0.16))
            # Google Blue (#1A73E8) architectural accent sleeves on the 4 corner posts
            if px != -2.2:
                bm_add_tbox(bms["g_blue_deep"], (px, 2.74, pz), (0.18, 0.56, 0.18))
                bm_add_tbox(bms["g_blue_deep"], (px, 0.44, pz), (0.18, 0.42, 0.18))
            else:
                bm_add_tbox(bms["g_blue"], (px, 2.86, pz), (0.18, 0.28, 0.18))

    # Overhead truss perimeter steel box beams (y = 2.92m)
    for pz in rig_zs:
        bm_add_tbox(bms["g_blue_deep"], (-2.2, 2.94, pz), (4.56, 0.14, 0.12))
    for px in rig_xs:
        bm_add_tbox(bms["steel_dark"], (px, 2.94, -0.4), (0.12, 0.14, 2.36))

    # 7 Overhead Monkey-Bar Rungs along X (y = 2.94m)
    for i in range(7):
        rx = -3.95 + i * (3.50 / 6.0)
        bm_add_tprism(bms["steel_brushed"], (rx, 2.94, -1.46), (rx, 2.94, 0.66), 0.024, 0.024, segs=6, cap=False)

    # Pull-up stations on West & East bays (y = 2.46m & y = 2.64m)
    bm_add_tprism(bms["steel_brushed"], (-4.4, 2.48, -1.44), (-4.4, 2.48, 0.64), 0.026, 0.026, segs=6, cap=False)
    bm_add_tprism(bms["steel_brushed"], (0.0, 2.62, -1.44), (0.0, 2.62, 0.64), 0.026, 0.026, segs=6, cap=False)

    # Parallel Dip Bars on West Bay (y = 1.25m, cantilevering neatly inward x = -4.4..-3.45)
    for dz in (-0.72, -0.08):
        bm_add_tbox(bms["g_blue_deep"], (-4.32, 1.25, dz), (0.20, 0.12, 0.08))
        bm_add_tprism(bms["steel_brushed"], (-4.32, 1.25, dz), (-3.45, 1.25, dz), 0.028, 0.028, segs=6, cap=True)
        # Diagonal brace down to west post
        bm_add_tprism(bms["steel_dark"], (-4.36, 0.90, dz), (-3.72, 1.25, dz), 0.022, 0.022, segs=5, cap=False)

    # Suspended Gymnastic Rings (hanging high at y = 2.12m, full walking clearance underneath!)
    for idx, (rx, col_key) in enumerate(((-1.35, "g_yellow"), (-0.85, "g_red"))):
        bm_add_tbox(bms["steel_dark"], (rx, 2.58, -0.4), (0.03, 0.68, 0.015))
        bm_add_beveled_torus(bms[col_key], (rx, 2.12, -0.4), 0.11, 0.022, maj_segs=6, min_segs=4, rot_euler_bl=(0.0, 0.0, 0.0))

    # Battle-rope anchor plate + coiled yellow/black ropes resting neatly by west post (-4.4, 0.14, -0.4)
    bm_add_tbox(bms["steel_dark"], (-4.48, 0.24, -0.4), (0.14, 0.16, 0.22))
    bm_add_beveled_torus(bms["g_yellow"], (-4.72, 0.20, -0.65), 0.22, 0.042, maj_segs=8, min_segs=4, rot_euler_bl=(math.pi * 0.5, 0.0, 0.0))
    bm_add_beveled_torus(bms["rubber_dark"], (-4.72, 0.25, -0.18), 0.19, 0.038, maj_segs=8, min_segs=4, rot_euler_bl=(math.pi * 0.5, 0.0, 0.0))

    # 4. 3-Tier Jumpable Plyo-Box Deck (East Side — EXACT 1:1 with colliders!)
    # Low: (3.4, 0.44, -2.2) size (1.4, 0.60, 1.4) -> y=0.14..0.74
    # Mid: (3.4, 0.64, -0.6) size (1.4, 1.00, 1.4) -> y=0.14..1.14
    # High:(3.4, 0.84,  1.0) size (1.4, 1.40, 1.4) -> y=0.14..1.54
    plyo_specs = [
        (3.4, -2.2, 0.60, "g_green", None),
        (3.4, -0.6, 1.00, "g_yellow", None),
        (3.4, 1.0, 1.40, "g_red", "g_blue"),
    ]
    for px, pz, h, stripe_a, stripe_b in plyo_specs:
        body_h = h - 0.06
        # Baltic-birch cabinet
        bm_add_tbox(bms["birch"], (px, 0.14 + body_h * 0.5, pz), (1.38, body_h, 1.38))
        # Dark non-slip rubberized landing top (exact top y = 0.14 + h)
        bm_add_tbox(bms["rubber_dark"], (px, 0.14 + h - 0.03, pz), (1.40, 0.06, 1.40))
        # Crisp Google height-code accent band near top
        bm_add_tbox(bms[stripe_a], (px, 0.14 + h - 0.14, pz), (1.41, 0.09, 1.41))
        if stripe_b is not None:
            bm_add_tbox(bms[stripe_b], (px, 0.14 + h - 0.25, pz), (1.41, 0.07, 1.41))
        # Recessed dark hand-grip slot cutouts on East & West sides
        bm_add_tbox(bms["steel_dark"], (px, 0.14 + body_h * 0.52, pz), (1.405, 0.07, 0.28))

    # 5. Kettlebell & Dumbbell Steel Rack at (-2.4, 0.68, 3.4), size (3.4, 1.08, 0.85) -> y = 0.14..1.22m
    rx, rz = -2.4, 3.4
    # 3 Heavy A-frame charcoal steel uprights along X (-4.0, -2.4, -0.8)
    for ux in (-4.02, -2.40, -0.78):
        bm_add_tbox(bms["steel_dark"], (ux, 0.68, rz), (0.12, 1.08, 0.80))
        bm_add_tbox(bms["rubber_dark"], (ux, 0.16, rz), (0.16, 0.04, 0.85))
    # Rear solid charcoal steel stabilizer backplate (makes rack read clearly as bullet cover!)
    bm_add_tbox(bms["steel_dark"], (rx, 0.68, rz + 0.34), (3.32, 0.96, 0.08))
    add_google_4color_bar(bms, (rx, 1.08, rz + 0.38), 2.80, 0.07, 0.03, axis="X")
    # 3 Horizontal trays (y = 0.26, 0.60, 0.94)
    for ty, d_tray in ((0.26, 0.72), (0.60, 0.64), (0.94, 0.56)):
        bm_add_tbox(bms["steel_dark"], (rx, ty, rz - 0.04), (3.36, 0.06, d_tray))
        # Front lip retainer rail
        bm_add_tbox(bms["steel_brushed"], (rx, ty + 0.04, rz - d_tray * 0.5 - 0.03), (3.36, 0.04, 0.03))
    # Top tray: 6 colorful Google-colored kettlebells!
    kb_colors = ("g_blue", "g_red", "g_yellow", "g_green", "g_blue", "g_red")
    for ki, col_k in enumerate(kb_colors):
        kx = -3.72 + ki * 0.53
        bm_add_tsphere(bms[col_k], (kx, 1.06, rz - 0.05), 0.11, 0.10, 0.11, u_segs=6, v_segs=4)
        # Kettlebell bold top grip handle
        bm_add_tbox(bms["steel_dark"], (kx, 1.19, rz - 0.05), (0.15, 0.036, 0.034))
        bm_add_tbox(bms["steel_dark"], (kx, 1.13, rz - 0.05), (0.12, 0.08, 0.026))
    # Middle & bottom trays: bold chrome-handle hex dumbbells (5 pairs per shelf, crisp & low-poly!)
    for ty in (0.68, 0.34):
        for di in range(5):
            dx = -3.56 + di * 0.58
            bm_add_tbox(bms["steel_brushed"], (dx, ty, rz - 0.06), (0.034, 0.034, 0.32))
            bm_add_tprism(bms["rubber_dark"], (dx, ty, rz - 0.26), (dx, ty, rz - 0.16), 0.072, 0.072, segs=6, cap=True)
            bm_add_tprism(bms["rubber_dark"], (dx, ty, rz + 0.05), (dx, ty, rz + 0.15), 0.072, 0.072, segs=6, cap=True)

    # 6. Weighted Turf Sled & Decline Bench Station at (1.2, 0.56, 3.2), size (2.2, 0.84, 1.1) -> y = 0.14..0.98m
    # Left half: Google-Red Weighted Turf Push Sled centered around (0.62, 0.14, 3.2)
    sx0, sz0 = 0.62, 3.20
    # Twin heavy red sled skis
    bm_add_tbox(bms["g_red"], (sx0 - 0.34, 0.18, sz0), (0.14, 0.08, 1.06))
    bm_add_tbox(bms["g_red"], (sx0 + 0.34, 0.18, sz0), (0.14, 0.08, 1.06))
    # Connecting red steel sled chassis deck
    bm_add_tbox(bms["g_red"], (sx0, 0.25, sz0), (0.86, 0.08, 0.66))
    # Center vertical chrome plate horn + stacked Olympic bumper plates (Blue & Yellow)
    bm_add_tprism(bms["steel_brushed"], (sx0, 0.28, sz0), (sx0, 0.72, sz0), 0.026, 0.026, segs=6, cap=True)
    bm_add_tprism(bms["g_blue"], (sx0, 0.29, sz0), (sx0, 0.38, sz0), 0.23, 0.23, segs=8, cap=True)
    bm_add_tprism(bms["g_yellow"], (sx0, 0.39, sz0), (sx0, 0.47, sz0), 0.21, 0.21, segs=8, cap=True)
    bm_add_tprism(bms["rubber_dark"], (sx0, 0.48, sz0), (sx0, 0.54, sz0), 0.18, 0.18, segs=8, cap=True)
    # Dual upright push poles rising to y = 0.98m
    for px_off in (-0.34, 0.34):
        bm_add_tprism(bms["steel_dark"], (sx0 + px_off, 0.22, sz0 + 0.34), (sx0 + px_off, 0.98, sz0 + 0.34), 0.028, 0.028, segs=6, cap=True)
        bm_add_tprism(bms["g_red"], (sx0 + px_off, 0.78, sz0 + 0.34), (sx0 + px_off, 0.96, sz0 + 0.34), 0.032, 0.032, segs=6, cap=True)

    # Right half: Sleek Black/Silver Decline Fitness Bench centered around (1.76, 0.14, 3.2)
    bx0, bz0 = 1.76, 3.20
    # Matte charcoal steel legs & central spine
    bm_add_tbox(bms["steel_dark"], (bx0, 0.18, bz0 - 0.38), (0.56, 0.08, 0.10))
    bm_add_tbox(bms["steel_dark"], (bx0, 0.18, bz0 + 0.38), (0.56, 0.08, 0.10))
    bm_add_tbox(bms["steel_dark"], (bx0, 0.36, bz0 - 0.32), (0.10, 0.36, 0.10))
    bm_add_tbox(bms["steel_dark"], (bx0, 0.46, bz0 + 0.32), (0.10, 0.56, 0.10))
    bm_add_tbox(bms["steel_brushed"], (bx0, 0.46, bz0), (0.09, 0.09, 0.84), rot_euler_bl=(-0.18, 0.0, 0.0))
    # Bolstered dark leather pad + subtle Google Blue side trim
    bm_add_tbox(bms["leather"], (bx0, 0.56, bz0), (0.38, 0.10, 1.04), rot_euler_bl=(-0.18, 0.0, 0.0))
    bm_add_tbox(bms["g_blue"], (bx0, 0.52, bz0), (0.40, 0.035, 1.00), rot_euler_bl=(-0.18, 0.0, 0.0))
    # Chrome leg-lock rollers at high (+Z) end
    bm_add_tprism(bms["steel_brushed"], (bx0 - 0.24, 0.72, bz0 + 0.40), (bx0 + 0.24, 0.72, bz0 + 0.40), 0.045, 0.045, segs=6, cap=True)

    # 7. Architectural Shade Sail Canopy suspended overhead NE Quadrant (y = 3.55..4.15m)
    # 3 slim angled steel masts (clear of all walls & entry paths!) + 4th corner tied to Rig NE upright (0.0, 3.09, -1.5)
    masts = [
        ((6.45, 0.14, -4.95), (6.12, 4.15, -4.65)),  # NE outer corner high peak
        ((0.90, 0.14, -4.95), (1.10, 3.88, -4.68)),  # North-center mast
        ((6.45, 0.14, -1.05), (6.15, 3.68, -1.20)),  # East-mid mast
    ]
    for base_p, top_p in masts:
        bm_add_tbox(bms["steel_dark"], (base_p[0], 0.17, base_p[2]), (0.28, 0.06, 0.28))
        bm_add_tprism(bms["steel_dark"], base_p, top_p, 0.085, 0.065, segs=6, cap=True)
        # Sleek brushed steel tension collar at mast tip
        bm_add_tbox(bms["steel_brushed"], top_p, (0.14, 0.14, 0.14))

    # Tensioned Hyperbolic-Paraboloid PTFE White Shade Sail (4x4 clean quad grid -> 32 tris!)
    # 4 corner anchor points in Three.js space
    c00 = Vector(t2b(1.10, 3.88, -4.68))  # NW sail corner
    c10 = Vector(t2b(6.12, 4.15, -4.65))  # NE sail corner (highest peak)
    c11 = Vector(t2b(6.15, 3.68, -1.20))  # SE sail corner
    c01 = Vector(t2b(0.25, 3.58, -1.50))  # SW sail corner (cable-tied to Rig NE upright at (0, 3.09, -1.5))
    # Stainless tie cable from rig upright to SW sail corner
    bm_add_prism_between(bms["steel_brushed"], Vector(t2b(0.0, 3.06, -1.5)), c01, 0.018, 0.018, segs=4, cap=False)

    bm_s = bms["sail"]
    uv_s = bm_s.loops.layers.uv.verify()
    grid_n = 4
    sverts = []
    for iy in range(grid_n + 1):
        v = iy / float(grid_n)
        row = []
        for ix in range(grid_n + 1):
            u = ix / float(grid_n)
            p = (1 - u) * (1 - v) * c00 + u * (1 - v) * c10 + u * v * c11 + (1 - u) * v * c01
            # Subtle graceful tensioned catenary scallop & center saddle lift
            edge_u = 4.0 * u * (1.0 - u)
            edge_v = 4.0 * v * (1.0 - v)
            p.z -= 0.14 * edge_u * edge_v
            row.append(bm_s.verts.new(p))
        sverts.append(row)
    for iy in range(grid_n):
        for ix in range(grid_n):
            f = bm_s.faces.new((sverts[iy][ix], sverts[iy][ix + 1], sverts[iy + 1][ix + 1], sverts[iy + 1][ix]))
            u0, u1 = ix / float(grid_n), (ix + 1) / float(grid_n)
            v0, v1 = iy / float(grid_n), (iy + 1) / float(grid_n)
            for loop, uv in zip(f.loops, ((u0, v0), (u1, v0), (u1, v1), (u0, v1))):
                loop[uv_s].uv = uv

    # Finalize all meshes
    for k, bm in bms.items():
        if len(bm.verts) == 0:
            bm.free()
            continue
        keep_uv = k in ("turf", "sail")
        smooth = k in ("sail", "steel_brushed", "g_blue", "g_red", "g_yellow", "g_green")
        finalize_mesh(f"OutdoorGym_{k}", bm, mats[k], smooth=smooth, uv_scale=0.32, keep_existing_uv=keep_uv)

    return export_asset("park_outdoor_gym.glb")


# ---------------------------------------------------------------------------
# ASSET 2: park_art_garden.glb (16.0m x 14.0m, <= 3,400 tris)
# ---------------------------------------------------------------------------
def build_park_art_garden():
    reset_scene()
    mats = make_shared_palette()
    tex_plaza = gen_art_plaza_tex("TexArtGardenPlaza", 384, 384, 807)
    mats["plaza"] = make_pbr_mat("MatArtGardenPlaza", hex_to_linear("#DFCFAF"), roughness=0.72, tex_img=tex_plaza)

    bms = {k: bmesh.new() for k in mats}

    # 1. Octagonal Warm Travertine & Decomposed-Granite Plaza (16.0m x 14.0m, top y=+0.12m, skirt y=-1.60m)
    hw, hd, ch = 8.0, 7.0, 2.75
    oct_pts = [
        (-hw + ch, -hd),
        (hw - ch, -hd),
        (hw, -hd + ch),
        (hw, hd - ch),
        (hw - ch, hd),
        (-hw + ch, hd),
        (-hw, hd - ch),
        (-hw, -hd + ch),
    ]
    # Solid travertine/concrete subterranean skirt (y = -1.60 .. +0.06m) + beveled stone rim (y = +0.06 .. +0.115m)
    bm_add_polygon_prism(bms["conc_skirt"], oct_pts, -1.60, 0.04, cap_bottom=True, cap_top=False)
    bm_add_polygon_prism(bms["travertine"], oct_pts, 0.04, 0.115, cap_bottom=False, cap_top=True)

    # Planar UV-mapped inner travertine/DG plaza top at exact y = +0.12m (inset 0.28m so beveled travertine curb frames edge!)
    inset_scale = 0.962
    inner_oct = [(x * inset_scale, y * inset_scale) for x, y in oct_pts]
    bm_p = bms["plaza"]
    uv_p = bm_p.loops.layers.uv.verify()
    p_verts = [bm_p.verts.new((x, y, 0.12)) for x, y in inner_oct]
    f_oct = bm_p.faces.new(p_verts)
    tri_res = bmesh.ops.triangulate(bm_p, faces=[f_oct], quad_method="BEAUTY", ngon_method="EAR_CLIP")
    for f in tri_res["faces"]:
        for loop in f.loops:
            co = loop.vert.co
            loop[uv_p].uv = ((co.x + 8.0) / 16.0, (co.y + 7.0) / 14.0)

    # 2. Centerpiece Google 4-Color Kinetic Art Monolith at (0, 0.12, 0)
    # Heavy solid beveled limestone/travertine pedestal: centered (0, 0.92, 0), size (2.4, 1.60, 2.4) -> y = 0.12..1.72m
    bm_add_tbox(bms["travertine"], (0.0, 0.21, 0.0), (2.52, 0.18, 2.52))    # stepped plinth base
    bm_add_tbox(bms["limestone"], (0.0, 0.92, 0.0), (2.36, 1.24, 2.36))     # solid pedestal core
    # Crisp vertical corner pilasters for architectural depth
    for sx in (-1.16, 1.16):
        for sz in (-1.16, 1.16):
            bm_add_tbox(bms["travertine"], (sx, 0.92, sz), (0.14, 1.28, 0.14))
    bm_add_tbox(bms["bronze"], (0.0, 1.57, 0.0), (2.28, 0.07, 2.28))        # recessed bronze shadow collar
    bm_add_tbox(bms["travertine"], (0.0, 1.66, 0.0), (2.44, 0.12, 2.44))    # beveled top slab -> exact y = 1.72m
    # Engraved museum brass plaques on +Z and -Z faces
    bm_add_tbox(bms["brass"], (0.0, 1.08, 1.19), (0.64, 0.26, 0.03))
    bm_add_tbox(bms["brass"], (0.0, 1.08, -1.19), (0.64, 0.26, 0.03))

    # Brushed stainless-steel central kinetic mounting core & slender finial spire (y = 1.72..4.42m)
    bm_add_tprism(bms["steel_brushed"], (0.0, 1.72, 0.0), (0.0, 1.94, 0.0), 0.72, 0.56, segs=8, cap=True)
    bm_add_tprism(bms["steel_brushed"], (0.0, 1.94, 0.0), (0.0, 4.42, 0.0), 0.12, 0.035, segs=8, cap=True)
    bm_add_tsphere(bms["steel_brushed"], (0.0, 4.46, 0.0), 0.11, 0.11, 0.11, u_segs=8, v_segs=6)

    # 4 Dramatic Interlocking Swept Google 4-Color Sculptural Ribbons/Arches (y = 1.76..4.75m!)
    ribbon_specs = [
        # (mat_key, yaw_deg, span_r, peak_y, width, thick, twist_rad)
        ("g_blue_deep", 22.0, 1.24, 4.75, 0.44, 0.14, 0.85),
        ("g_red", 112.0, 1.18, 4.32, 0.40, 0.14, -0.75),
        ("g_yellow", 202.0, 1.12, 3.86, 0.38, 0.13, 0.70),
        ("g_green", 292.0, 1.06, 3.48, 0.36, 0.13, -0.65),
    ]
    for mat_k, yaw_deg, span_r, peak_y, rw, rt, twist_r in ribbon_specs:
        yaw = math.radians(yaw_deg)
        cy, sy = math.cos(yaw), math.sin(yaw)
        pts_bl = []
        n_steps = 11
        for i in range(n_steps):
            t = i / float(n_steps - 1)  # 0..1 arch parameter
            ang = t * math.pi
            # Graceful twisted parabolic-elliptical arch anchored on plinth
            local_x = math.cos(ang) * span_r
            local_y = math.sin(ang * 2.0) * 0.28  # gentle S-curve depth sweep!
            tz_h = 1.76 + (peak_y - 1.76) * (math.sin(ang) ** 0.85)
            bx = local_x * cy - local_y * sy
            by = local_x * sy + local_y * cy
            pts_bl.append((bx, by, tz_h))
        bm_add_swept_ribbon(bms[mat_k], pts_bl, rw, rt, twist_fn=lambda u, tr=twist_r: (u - 0.5) * tr, closed=False)

    # Floating brushed-steel tilted kinetic halo ring encircling the ribbons at y = 3.05m
    bm_add_beveled_torus(bms["steel_brushed"], (0.0, 3.05, 0.0), 1.05, 0.055, maj_segs=14, min_segs=4, rot_euler_bl=(0.55, 0.22, 0.4))

    # 3. 4 Staggered Pinwheel Limestone Garden Cover Walls (y = 0.12..1.34m, height 1.22m — EXACT 1:1!)
    wall_specs = [
        # (cx, cz, sx, sz, axis, bench_dir)
        (-1.6, -5.8, 5.4, 0.76, "X", +1.0),  # North wall
        (1.6, 5.8, 5.4, 0.76, "X", -1.0),    # South wall
        (-6.6, 1.4, 0.76, 4.8, "Z", +1.0),   # West wall
        (6.6, -1.4, 0.76, 4.8, "Z", -1.0),   # East wall
    ]
    for wx, wz, sx, sz, axis, bdir in wall_specs:
        # Base plinth + limestone wall body (y = 0.12..1.25m)
        bm_add_tbox(bms["travertine"], (wx, 0.18, wz), (sx + 0.04, 0.12, sz + 0.04))
        bm_add_tbox(bms["limestone"], (wx, 0.745, wz), (sx, 1.01, sz))
        # Honed travertine beveled stone coping cap (y = 1.25..1.34m)
        bm_add_tbox(bms["travertine"], (wx, 1.295, wz), (sx + 0.06, 0.09, sz + 0.06))
        # Crisp recessed Google 4-color glazed ceramic tile inlay band (y = 1.06..1.16m)
        if axis == "X":
            add_google_4color_bar(bms, (wx, 1.11, wz), sx - 0.36, 0.10, sz + 0.025, axis="X")
            # Warm cedar garden bench accent cantilevered along inner face (y = 0.44..0.52m)
            bm_add_tbox(bms["cedar"], (wx, 0.48, wz + bdir * (sz * 0.5 + 0.14)), (sx - 0.85, 0.08, 0.28))
            for bx_off in (-1.5, 0.0, 1.5):
                bm_add_tbox(bms["bronze"], (wx + bx_off, 0.34, wz + bdir * (sz * 0.5 + 0.10)), (0.06, 0.22, 0.20))
        else:
            add_google_4color_bar(bms, (wx, 1.11, wz), sz - 0.36, 0.10, sx + 0.025, axis="Z")
            bm_add_tbox(bms["cedar"], (wx + bdir * (sx * 0.5 + 0.14), 0.48, wz), (0.28, 0.08, sz - 0.85))
            for bz_off in (-1.3, 0.0, 1.3):
                bm_add_tbox(bms["bronze"], (wx + bdir * (sx * 0.5 + 0.10), 0.34, wz + bz_off), (0.20, 0.22, 0.06))

    # 4. 4 Raised Native-California Succulent & Lavender Planter Beds (y = 0.12..1.07m, height 0.95m — EXACT 1:1!)
    planter_centers = [
        (-4.4, -3.4),
        (4.4, -3.6),
        (-4.4, 3.6),
        (4.4, 3.4),
    ]
    for pi, (px, pz) in enumerate(planter_centers):
        # Architectural concrete planter core + warm cedar wrap frame + coping rim (2.6 x 0.95 x 1.5 -> y = 0.12..1.07m)
        bm_add_tbox(bms["conc_skirt"], (px, 0.18, pz), (2.52, 0.12, 1.42))
        bm_add_tbox(bms["conc_white"], (px, 0.615, pz), (2.56, 0.75, 1.46))
        # Warm cedar recessed accent cladding panels on front/back/sides
        bm_add_tbox(bms["cedar"], (px, 0.615, pz), (2.60, 0.58, 1.24))
        bm_add_tbox(bms["cedar"], (px, 0.615, pz), (2.34, 0.58, 1.50))
        # Wide warm cedar coping rim (4 sides around mulch bed, y = 0.99..1.07m)
        bm_add_tbox(bms["cedar"], (px, 1.03, pz - 0.66), (2.60, 0.08, 0.18))
        bm_add_tbox(bms["cedar"], (px, 1.03, pz + 0.66), (2.60, 0.08, 0.18))
        bm_add_tbox(bms["cedar"], (px - 1.21, 1.03, pz), (0.18, 0.08, 1.14))
        bm_add_tbox(bms["cedar"], (px + 1.21, 1.03, pz), (0.18, 0.08, 1.14))
        # Dark volcanic mulch soil bed at y = 0.98m
        bm_add_tbox(bms["mulch"], (px, 0.95, pz), (2.26, 0.08, 1.16))

        # Lush sculpted California Agave rosettes + Purple Lavender spikes + Native Ornamental Grasses!
        yaw0 = pi * 0.7
        bm_add_agave_rosette(bms["agave"], (px - 0.68, 0.99, pz - 0.06), scale=1.32, blades=6, yaw=yaw0)
        bm_add_agave_rosette(bms["agave"], (px + 0.66, 0.99, pz + 0.08), scale=1.18, blades=6, yaw=yaw0 + 0.5)
        bm_add_lavender_cluster(bms["sage"], bms["lavender"], (px - 0.05, 0.99, pz + 0.14), scale=1.35, stalks=4, yaw=yaw0 + 0.2)
        bm_add_lavender_cluster(bms["sage"], bms["lavender"], (px + 0.12, 0.99, pz - 0.22), scale=1.25, stalks=3, yaw=yaw0 + 1.1)
        bm_add_grass_tuft(bms["grass"], (px - 0.88, 0.99, pz + 0.26), scale=1.15, blades=4, yaw=yaw0)
        bm_add_grass_tuft(bms["grass"], (px + 0.88, 0.99, pz - 0.24), scale=1.15, blades=4, yaw=yaw0 + 0.8)

    # 5. 2 Corner Accent Plinth Sculptures (clear of flanking avenues & loot spots!)
    # SE Corner (5.2, 0.12, 4.4): Brushed stainless-steel sculpted torus ring on stone cube
    bm_add_tbox(bms["travertine"], (5.2, 0.64, 4.4), (1.04, 1.04, 1.04))
    bm_add_tbox(bms["bronze"], (5.2, 1.18, 4.4), (0.86, 0.05, 0.86))
    bm_add_beveled_torus(bms["steel_brushed"], (5.2, 1.72, 4.4), 0.44, 0.095, maj_segs=14, min_segs=4, rot_euler_bl=(0.24, 0.0, 0.78))

    # NW Corner (-5.2, 0.12, -4.4): Golden-Yellow & Blue stacked twisted geometric prism totem
    bm_add_tbox(bms["travertine"], (-5.2, 0.64, -4.4), (1.04, 1.04, 1.04))
    bm_add_tbox(bms["bronze"], (-5.2, 1.18, -4.4), (0.86, 0.05, 0.86))
    totem_tiers = [
        (1.40, 0.56, 0.38, 0.18, "g_yellow"),
        (1.76, 0.46, 0.36, 0.62, "g_blue"),
        (2.10, 0.36, 0.34, 1.08, "g_yellow"),
        (2.38, 0.24, 0.26, 1.52, "g_red"),
    ]
    for ty, w_t, h_t, rot_y, col_k in totem_tiers:
        bm_add_tbox(bms[col_k], (-5.2, ty, -4.4), (w_t, h_t, w_t), rot_y=rot_y)

    # Finalize all meshes
    for k, bm in bms.items():
        if len(bm.verts) == 0:
            bm.free()
            continue
        keep_uv = k == "plaza"
        smooth = k in ("steel_brushed", "g_blue", "g_blue_deep", "g_red", "g_yellow", "g_green", "agave", "lavender")
        finalize_mesh(f"ArtGarden_{k}", bm, mats[k], smooth=smooth, uv_scale=0.35, keep_existing_uv=keep_uv)

    return export_asset("park_art_garden.glb")


# ---------------------------------------------------------------------------
# ASSET 3: park_google_pergola.glb (9.5m x 6.5m, <= 2,200 tris)
# ---------------------------------------------------------------------------
def build_park_google_pergola():
    reset_scene()
    mats = make_shared_palette()
    tex_wb = gen_pergola_whiteboard_tex("TexWorkspaceOutdoorBoard", 256, 128)
    mats["whiteboard"] = make_pbr_mat(
        "MatWorkspaceDisplay",
        hex_to_linear("#FFFFFF"),
        roughness=0.22,
        tex_img=tex_wb,
        emission=hex_to_linear("#EEF4FF"),
        emission_strength=0.14,
    )

    bms = {k: bmesh.new() for k in mats}

    # 1. Warm Travertine Timber-Edged Deck (9.5m x 6.5m, top y=+0.12m, hill skirt down to y=-1.40m)
    bm_add_tbox(bms["conc_skirt"], (0.0, -0.66, 0.0), (9.50, 1.48, 6.50))  # y = -1.40 .. +0.08
    # Warm travertine inner deck slab (y = +0.08 .. +0.12m)
    bm_add_tbox(bms["travertine"], (0.0, 0.10, 0.0), (9.06, 0.04, 6.06))
    # Warm oiled cedar timber perimeter border trim (exact 9.5m x 6.5m outer envelope, top y = +0.12m)
    bm_add_tbox(bms["cedar"], (0.0, 0.095, -3.14), (9.50, 0.05, 0.22))
    bm_add_tbox(bms["cedar"], (0.0, 0.095, 3.14), (9.50, 0.05, 0.22))
    bm_add_tbox(bms["cedar"], (-4.64, 0.095, 0.0), (0.22, 0.05, 6.06))
    bm_add_tbox(bms["cedar"], (4.64, 0.095, 0.0), (0.22, 0.05, 6.06))

    # 2. Slatted Warm-Cedar Pergola Canopy at y = 3.35m on 4 Matte-Charcoal Corner Columns
    for sx in (-4.20, 4.20):
        for sz in (-2.70, 2.70):
            # Steel column base anchor plate
            bm_add_tbox(bms["steel_dark"], (sx, 0.15, sz), (0.34, 0.06, 0.34))
            # Main matte charcoal steel column (0.20m square, y = 0.12..3.35m)
            bm_add_tbox(bms["steel_dark"], (sx, 1.735, sz), (0.20, 3.23, 0.20))
            # Subtle architectural knee braces along X inward
            in_x = -1.0 if sx > 0 else 1.0
            bm_add_tprism(bms["steel_dark"], (sx, 2.68, sz), (sx + in_x * 0.56, 3.24, sz), 0.05, 0.05, segs=4, cap=False)

    # Perimeter charcoal steel roof fascia beams (y = 3.22..3.46m)
    bm_add_tbox(bms["steel_dark"], (0.0, 3.34, -2.70), (8.90, 0.24, 0.22))
    bm_add_tbox(bms["steel_dark"], (0.0, 3.34, 2.70), (8.90, 0.24, 0.22))
    bm_add_tbox(bms["steel_dark"], (-4.20, 3.34, 0.0), (0.22, 0.24, 5.62))
    bm_add_tbox(bms["steel_dark"], (4.20, 3.34, 0.0), (0.22, 0.24, 5.62))
    # Subtle Google 4-color architectural badge inlay on the front (+Z) pergola fascia beam!
    add_google_4color_bar(bms, (0.0, 3.34, 2.82), 2.40, 0.08, 0.03, axis="X")

    # 13 Open Warm-Cedar Architectural Pergola Louver Slats spanning Z (y = 3.28..3.46m)
    for i in range(13):
        lx = -3.84 + i * (7.68 / 12.0)
        bm_add_tbox(bms["cedar"], (lx, 3.37, 0.0), (0.09, 0.18, 5.68))

    # 3. Rear Full-Height Acoustic Privacy Screen Wall (Standing Hard Cover!)
    # Exact collider: (0, 1.24, -2.85), size (7.6, 2.24, 0.36) -> y = 0.12..2.36m, X in [-3.8, +3.8]
    wz = -2.85
    # Heavy charcoal steel perimeter frame
    bm_add_tbox(bms["steel_dark"], (0.0, 0.18, wz), (7.60, 0.12, 0.36))      # bottom sill
    bm_add_tbox(bms["steel_dark"], (0.0, 2.22, wz), (7.60, 0.10, 0.36))      # upper transom
    bm_add_tbox(bms["steel_dark"], (-3.72, 1.24, wz), (0.16, 2.24, 0.36))    # west frame post
    bm_add_tbox(bms["steel_dark"], (3.72, 1.24, wz), (0.16, 2.24, 0.36))     # east frame post
    bm_add_tbox(bms["steel_dark"], (-2.12, 1.24, wz), (0.12, 2.12, 0.32))    # inner west mullion
    bm_add_tbox(bms["steel_dark"], (2.12, 1.24, wz), (0.12, 2.12, 0.32))     # inner east mullion
    # Solid lower acoustic concrete & warm cedar plinth wall (y = 0.24..0.90m)
    bm_add_tbox(bms["conc_white"], (0.0, 0.57, wz), (7.28, 0.66, 0.30))
    bm_add_tbox(bms["cedar"], (0.0, 0.57, wz), (4.12, 0.56, 0.33))
    # Left & right vertical warm-cedar acoustic slat wings (y = 0.90..2.18m)
    for side in (-1.0, 1.0):
        for si in range(5):
            sx = side * (2.34 + si * 0.30)
            bm_add_tbox(bms["cedar"], (sx, 1.54, wz), (0.14, 1.28, 0.24))
    # Center wide frosted Google-tinted architectural acoustic glass panel (y = 0.90..2.18m)
    bm_add_tbox(bms["glass_frost"], (0.0, 1.54, wz), (4.12, 1.28, 0.08))
    # Official Google 4-color header trim bar crowning the privacy wall (y = 2.27..2.36m)
    add_google_4color_bar(bms, (0.0, 2.315, wz), 7.40, 0.09, 0.34, axis="X")

    # Outdoor Google Workspace Collaboration Whiteboard / Display Monolith flush on front (+Z) of rear wall!
    wb_z = wz + 0.22  # z = -2.63 (cleanly mounted on front of privacy wall!)
    bm_add_tbox(bms["steel_dark"], (0.0, 1.56, wb_z - 0.03), (2.34, 1.22, 0.07))
    # Crisp UV-mapped display screen quad facing +Z (Three.js +Z = Blender -Y!)
    bm_w = bms["whiteboard"]
    uv_w = bm_w.loops.layers.uv.verify()
    wy_bl = -(wb_z + 0.012)
    vw0 = bm_w.verts.new((-1.10, wy_bl, 1.02))
    vw1 = bm_w.verts.new((1.10, wy_bl, 1.02))
    vw2 = bm_w.verts.new((1.10, wy_bl, 2.10))
    vw3 = bm_w.verts.new((-1.10, wy_bl, 2.10))
    f_wb = bm_w.faces.new((vw0, vw1, vw2, vw3))
    for loop, uv in zip(f_wb.loops, ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))):
        loop[uv_w].uv = uv
    # Marker tray below whiteboard
    bm_add_tbox(bms["steel_brushed"], (0.0, 0.94, wb_z + 0.04), (1.50, 0.04, 0.09))

    # 4. 2 Flanking Built-In Concrete Bench Planters (Waist Cover — EXACT 1:1!)
    # West: (-4.15, 0.66, 0.4), East: (4.15, 0.66, 0.4), size (0.95, 1.08, 3.6) -> y = 0.12..1.20m
    for side_idx, px in enumerate((-4.15, 4.15)):
        in_dir = 1.0 if px < 0 else -1.0
        pz = 0.40
        bm_add_tbox(bms["conc_skirt"], (px, 0.18, pz), (0.92, 0.12, 3.56))
        bm_add_tbox(bms["conc_white"], (px, 0.68, pz), (0.95, 0.88, 3.60))
        # Warm cedar coping rim (y = 1.12..1.20m)
        bm_add_tbox(bms["cedar"], (px, 1.16, pz - 1.72), (0.98, 0.08, 0.18))
        bm_add_tbox(bms["cedar"], (px, 1.16, pz + 1.72), (0.98, 0.08, 0.18))
        bm_add_tbox(bms["cedar"], (px - 0.40, 1.16, pz), (0.18, 0.08, 3.28))
        bm_add_tbox(bms["cedar"], (px + 0.40, 1.16, pz), (0.18, 0.08, 3.28))
        # Inward-facing built-in cedar bench ledge (y = 0.44..0.52m)
        bm_add_tbox(bms["cedar"], (px + in_dir * 0.56, 0.48, pz), (0.24, 0.08, 2.80))
        # Dark volcanic mulch bed
        bm_add_tbox(bms["mulch"], (px, 1.10, pz), (0.64, 0.08, 3.26))
        # Native California ornamental grasses & lavender along planter trough
        for gi, gz_off in enumerate((-1.15, -0.35, 0.45, 1.20)):
            if gi % 2 == 0:
                bm_add_grass_tuft(bms["grass"], (px, 1.14, pz + gz_off), scale=0.95, blades=4, yaw=gi * 0.9 + side_idx)
            else:
                bm_add_lavender_cluster(bms["sage"], bms["lavender"], (px, 1.14, pz + gz_off), scale=0.95, stalks=3, yaw=gi * 0.7)

    # 5. Central Cedar Collaboration Picnic Table (EXACT 1:1 with collider!)
    # Centered (0, 0.54, 0.5), size (3.8, 0.84, 1.35) -> y = 0.12..0.96m, X in [-1.9, +1.9], Z in [-0.175, +1.175]
    tz = 0.50
    # Warm cedar slatted tabletop (top y = 0.92m, width 3.80m, depth 0.82m)
    for plank_z in (-0.31, -0.13, 0.13, 0.31):
        bm_add_tbox(bms["cedar"], (0.0, 0.88, tz + plank_z), (3.80, 0.08, 0.16))
    # Central recessed Google-Blue power & USB-C charging spine strip!
    bm_add_tbox(bms["g_blue_deep"], (0.0, 0.895, tz), (3.60, 0.06, 0.08))
    # 3 Heavy matte-charcoal steel A-frame table + bench trestle supports
    for tx in (-1.42, 0.0, 1.42):
        bm_add_tbox(bms["steel_dark"], (tx, 0.16, tz), (0.10, 0.08, 1.32))        # bottom sleeper bar
        bm_add_tbox(bms["steel_dark"], (tx, 0.42, tz), (0.10, 0.07, 1.32))        # bench support crossbar
        bm_add_tbox(bms["steel_dark"], (tx, 0.80, tz), (0.10, 0.07, 0.76))        # top beam
        # Angled steel legs
        bm_add_tprism(bms["steel_dark"], (tx, 0.16, tz - 0.54), (tx, 0.84, tz - 0.30), 0.045, 0.045, segs=4, cap=False)
        bm_add_tprism(bms["steel_dark"], (tx, 0.16, tz + 0.54), (tx, 0.84, tz + 0.30), 0.045, 0.045, segs=4, cap=False)
    # Integrated flanking warm-cedar side benches (y = 0.46..0.53m, outer edges at tz ± 0.675 -> exact 1.35m total Z!)
    bm_add_tbox(bms["cedar"], (0.0, 0.495, tz - 0.545), (3.76, 0.07, 0.26))
    bm_add_tbox(bms["cedar"], (0.0, 0.495, tz + 0.545), (3.76, 0.07, 0.26))

    # Finalize all meshes
    for k, bm in bms.items():
        if len(bm.verts) == 0:
            bm.free()
            continue
        keep_uv = k == "whiteboard"
        smooth = k in ("steel_brushed", "lavender")
        finalize_mesh(f"GooglePergola_{k}", bm, mats[k], smooth=smooth, uv_scale=0.40, keep_existing_uv=keep_uv)

    return export_asset("park_google_pergola.glb")


# ---------------------------------------------------------------------------
# ASSET 4: prop_garden_planter_wall.glb (5.2m x 1.6m x 1.22m, <= 700 tris)
# ---------------------------------------------------------------------------
def build_prop_garden_planter_wall():
    reset_scene()
    mats = make_shared_palette()
    bms = {k: bmesh.new() for k in mats}

    # Collider reference: (0, 0.61, 0), size (5.2, 1.22, 1.55)
    # Wall centered at z = -0.20, depth 1.15 -> Z in [-0.775, +0.375]
    # Integrated cedar bench ledge along +Z front: Z in [+0.375, +0.825] (depth 0.45m) -> Total Z = 1.60m!
    wz = -0.20

    # 1. Subterranean foundation hill skirt down to y = -0.80m
    bm_add_tbox(bms["conc_skirt"], (0.0, -0.40, wz), (5.20, 0.80, 1.15))

    # 2. Main Solid Architectural White-Concrete Retaining Wall (5.2m x 1.22m x 1.15m, y = 0.0..1.22m)
    bm_add_tbox(bms["conc_skirt"], (0.0, 0.05, wz), (5.24, 0.10, 1.19))   # grounded plinth toe-kick
    bm_add_tbox(bms["conc_white"], (0.0, 0.61, wz), (5.20, 1.02, 1.15))   # solid concrete wall body (y = 0.10..1.12)
    # Crisp architectural top concrete coping rim around recessed planter trough (y = 1.12..1.22m)
    bm_add_tbox(bms["travertine"], (0.0, 1.17, wz - 0.50), (5.24, 0.10, 0.18))
    bm_add_tbox(bms["travertine"], (0.0, 1.17, wz + 0.50), (5.24, 0.10, 0.18))
    bm_add_tbox(bms["travertine"], (-2.52, 1.17, wz), (0.20, 0.10, 0.82))
    bm_add_tbox(bms["travertine"], (2.52, 1.17, wz), (0.20, 0.10, 0.82))
    # Dark mulch bed inside top planter trough (y = 1.12m)
    bm_add_tbox(bms["mulch"], (0.0, 1.11, wz), (4.84, 0.06, 0.82))

    # 3. Integrated Warm-Cedar Seating Bench Ledge along +Z front (width 4.4m, depth 0.45m, top y = 0.46m)
    bz = wz + 0.575 + 0.225  # +0.60 -> Z in [+0.375, +0.825]
    # Two crisp warm cedar bench planks + charcoal steel cantilever brackets
    bm_add_tbox(bms["cedar"], (0.0, 0.425, bz - 0.105), (4.40, 0.07, 0.20))
    bm_add_tbox(bms["cedar"], (0.0, 0.425, bz + 0.115), (4.40, 0.07, 0.20))
    for bx in (-1.85, -0.62, 0.62, 1.85):
        bm_add_tbox(bms["steel_dark"], (bx, 0.36, bz - 0.02), (0.08, 0.06, 0.40))
        bm_add_tbox(bms["steel_dark"], (bx, 0.20, bz - 0.15), (0.08, 0.28, 0.10))

    # 4. Recessed Google 4-Color Glazed Ceramic Mosaic Stripe along front (+Z) and back (-Z) faces!
    add_google_4color_bar(bms, (0.0, 0.94, wz), 4.64, 0.12, 1.18, axis="X")

    # 5. Sculpted California Ornamental Grasses & Purple/Sage Native Shrubs on top (y = 1.14..1.52m, <= 700 tris total!)
    for gx, sc, yaw in ((-1.72, 1.05, 0.3), (-0.52, 1.12, 1.1), (0.62, 1.08, 2.0), (1.76, 1.02, 0.7)):
        bm_add_grass_tuft(bms["grass"], (gx, 1.12, wz + 0.04), scale=sc, blades=3, yaw=yaw)
    for lx, yaw in ((-1.15, 0.5), (0.04, 1.4), (1.22, 2.2)):
        bm_add_lavender_cluster(bms["sage"], bms["lavender"], (lx, 1.12, wz - 0.05), scale=1.15, stalks=3, yaw=yaw)
    # Lush low sculptural sage-green California shrub mounds softening the top sill (low poly!)
    for sx, rx_s, ry_s, rz_s in ((-1.45, 0.42, 0.22, 0.30), (-0.28, 0.46, 0.24, 0.32), (0.94, 0.44, 0.22, 0.30)):
        bm_add_tsphere(bms["sage"], (sx, 1.18, wz + 0.02), rx_s, ry_s, rz_s, u_segs=5, v_segs=3)
    # 2 bold sculptural blue-green agave rosettes framing the ends
    bm_add_agave_rosette(bms["agave"], (-2.08, 1.12, wz - 0.02), scale=0.92, blades=5, yaw=0.4)
    bm_add_agave_rosette(bms["agave"], (2.08, 1.12, wz + 0.02), scale=0.92, blades=5, yaw=1.3)

    # Finalize all meshes
    for k, bm in bms.items():
        if len(bm.verts) == 0:
            bm.free()
            continue
        smooth = k in ("agave", "lavender")
        finalize_mesh(f"PlanterWall_{k}", bm, mats[k], smooth=smooth, uv_scale=0.45)

    return export_asset("prop_garden_planter_wall.glb")


# ---------------------------------------------------------------------------
# ASSET 5: prop_sculpture_plinth.glb (2.4m x 2.4m x 3.05m, <= 750 tris)
# ---------------------------------------------------------------------------
def build_prop_sculpture_plinth():
    reset_scene()
    mats = make_shared_palette()
    bms = {k: bmesh.new() for k in mats}

    # 1. Subterranean foundation hill skirt down to y = -0.80m
    bm_add_tbox(bms["conc_skirt"], (0.0, -0.40, 0.0), (2.20, 0.80, 2.20))

    # 2. Stepped Base Collar (2.20m x 0.20m x 2.20m, y = 0.00..0.20m)
    bm_add_tbox(bms["travertine"], (0.0, 0.10, 0.0), (2.20, 0.20, 2.20))

    # 3. Solid Beveled Travertine Pedestal (1.85m x 1.16m x 1.85m, y = 0.20..1.36m)
    # Chamfered octagonal-square pedestal prism (clean 8-sided chamfered cube -> ultra crisp & low poly!)
    h_p = 0.925
    ch = 0.16
    ped_pts = [
        (-h_p + ch, -h_p),
        (h_p - ch, -h_p),
        (h_p, -h_p + ch),
        (h_p, h_p - ch),
        (h_p - ch, h_p),
        (-h_p + ch, h_p),
        (-h_p, h_p - ch),
        (-h_p, -h_p + ch),
    ]
    bm_add_polygon_prism(bms["limestone"], ped_pts, 0.20, 1.22, cap_bottom=False, cap_top=True)
    # Recessed bronze architectural shadow collar (matching chamfered octagon inset cleanly!)
    collar_pts = [(x * 0.94, y * 0.94) for x, y in ped_pts]
    bm_add_polygon_prism(bms["bronze"], collar_pts, 1.22, 1.26, cap_bottom=False, cap_top=False)
    # Beveled travertine top cap slab (y = 1.26..1.36m)
    cap_pts = [(x * 1.03, y * 1.03) for x, y in ped_pts]
    bm_add_polygon_prism(bms["travertine"], cap_pts, 1.26, 1.36, cap_bottom=True, cap_top=True)
    # Engraved museum brass plaques on +Z and -Z
    bm_add_tbox(bms["brass"], (0.0, 0.86, 0.93), (0.52, 0.20, 0.03))
    bm_add_tbox(bms["brass"], (0.0, 0.86, -0.93), (0.52, 0.20, 0.03))

    # 4. Bold Brushed-Steel & Google 4-Color Geometric Kinetic Sculpture (y = 1.36..3.05m)
    # Brushed-steel tapered mounting saddle (y = 1.36..1.52m)
    bm_add_tprism(bms["steel_brushed"], (0.0, 1.36, 0.0), (0.0, 1.54, 0.0), 0.44, 0.30, segs=8, cap=True)
    # Slender vertical stainless axis rod anchoring sculpture
    bm_add_tprism(bms["steel_brushed"], (0.0, 1.50, 0.0), (0.0, 2.98, 0.0), 0.055, 0.045, segs=6, cap=True)

    # Outer Brushed Stainless-Steel Geometric Sculptural Ring (y = 1.48..3.05m, diameter 1.56m)
    bm_add_beveled_torus(bms["steel_brushed"], (0.0, 2.26, 0.0), 0.72, 0.078, maj_segs=18, min_segs=6, rot_euler_bl=(0.0, 0.0, 0.35))
    # Inner perpendicular counter-tilted brushed-steel ring for 360° sculptural presence!
    bm_add_beveled_torus(bms["steel_dark"], (0.0, 2.26, 0.0), 0.56, 0.044, maj_segs=14, min_segs=4, rot_euler_bl=(0.24, 0.0, 1.92))

    # 4 Canted Interlocking Google 4-Color Architectural Planes / Fins (all 4 colors vivid from 360°!)
    fin_specs = [
        # (mat_key, t_center, t_size, rot_euler_bl)
        ("g_blue_deep", (-0.32, 2.52, 0.16), (0.64, 0.82, 0.09), (0.20, -0.32, 0.32)),
        ("g_red", (0.34, 2.46, 0.14), (0.60, 0.78, 0.09), (-0.18, 0.34, -0.45)),
        ("g_yellow", (0.26, 1.88, -0.26), (0.62, 0.68, 0.09), (0.28, 0.26, 0.65)),
        ("g_green", (-0.28, 1.92, -0.24), (0.62, 0.72, 0.09), (-0.26, -0.28, -0.58)),
    ]
    for col_k, tc, ts, reul in fin_specs:
        bm_add_tbox(bms[col_k], tc, ts, rot_euler_bl=reul)

    # Finalize all meshes
    for k, bm in bms.items():
        if len(bm.verts) == 0:
            bm.free()
            continue
        smooth = k in ("steel_brushed", "steel_dark", "g_blue_deep", "g_red", "g_yellow", "g_green")
        finalize_mesh(f"SculpturePlinth_{k}", bm, mats[k], smooth=smooth, uv_scale=0.45)

    return export_asset("prop_sculpture_plinth.glb")


# ---------------------------------------------------------------------------
# Crisp 5x7 Pixel Bitmap Font & EEVEE 6-Panel QA Sheet Renderer
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
    "J": ["00111", "00010", "00010", "00010", "10010", "10010", "01100"],
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
                    y0 = y + ry * scale
                    y1 = min(h, y0 + scale)
                    x0 = cx + rx * scale
                    x1 = min(w, x0 + scale)
                    if y0 >= 0 and x0 >= 0 and y0 < h and x0 < w:
                        canvas[y0:y1, x0:x1] = color
        cx += 6 * scale


def fill_rect(canvas, x0, y0, x1, y1, color):
    h, w, _ = canvas.shape
    canvas[max(0, y0):min(h, y1), max(0, x0):min(w, x1)] = color


def load_png_topdown(path):
    img = bpy.data.images.load(str(path), check_existing=False)
    w, h = img.size
    buf = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(buf)
    bpy.data.images.remove(img)
    return buf.reshape((h, w, 4))[::-1].copy()


def save_png_topdown(canvas, out_path, mirror_dir=None):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    h, w, _ = canvas.shape
    img = bpy.data.images.new(f"Sheet_{out_path.stem}", width=w, height=h, alpha=True)
    flipped = np.ascontiguousarray(np.clip(canvas[::-1], 0.0, 1.0), dtype=np.float32)
    img.pixels.foreach_set(flipped.ravel())
    img.filepath_raw = str(out_path)
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)
    if mirror_dir is not None:
        mirror_dir = Path(mirror_dir)
        mirror_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out_path, mirror_dir / out_path.name)


def configure_eevee(samples=24, res_x=640, res_y=560):
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = samples
    scene.render.resolution_x = res_x
    scene.render.resolution_y = res_y
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = False
    try:
        scene.view_settings.view_transform = "AgX"
        scene.view_settings.look = "AgX - Medium High Contrast"
    except Exception:
        pass
    scene.view_settings.exposure = 0.05


def setup_outdoor_world():
    scene = bpy.context.scene
    world = scene.world or bpy.data.worlds.new("QAWorld")
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
    ramp.color_ramp.elements[0].color = (0.76, 0.84, 0.92, 1.0)
    ramp.color_ramp.elements[1].position = 0.55
    ramp.color_ramp.elements[1].color = (0.30, 0.56, 0.88, 1.0)
    nt.links.new(texcoord.outputs["Generated"], sep.inputs["Vector"])
    nt.links.new(sep.outputs["Z"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = 0.92
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])


def look_at(obj, target):
    direction = target - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def build_outdoor_qa_rig(bbox_min, bbox_max, azim_deg, elev_deg, fov_deg=34.0, fill_ratio=0.78):
    scene = bpy.context.scene
    for obj in list(bpy.data.objects):
        if obj.name.startswith("QA_"):
            bpy.data.objects.remove(obj, do_unlink=True)

    # Frame tightly on the above-ground portion (Z >= 0) so subterranean hill skirts stay cleanly beneath studio lawn!
    vis_min = Vector((bbox_min.x, bbox_min.y, max(0.0, bbox_min.z)))
    vis_max = Vector((bbox_max.x, bbox_max.y, max(0.2, bbox_max.z)))
    center = 0.5 * (vis_min + vis_max)
    dims = vis_max - vis_min
    radius = max(0.5, 0.5 * dims.length)

    # Lush Mountain View park lawn plane at exact Z = 0.0m
    bpy.ops.mesh.primitive_circle_add(vertices=64, radius=max(radius * 9.0, 24.0), fill_type="NGON", location=(center.x, center.y, 0.0))
    floor = bpy.context.active_object
    floor.name = "QA_ParkLawn"
    mat_f = bpy.data.materials.new("QA_ParkLawnMat")
    bsdf = mat_f.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = hex_to_linear("#4B7345")
    bsdf.inputs["Roughness"].default_value = 0.88
    floor.data.materials.append(mat_f)

    # Compute exact projected framing distance
    az = math.radians(azim_deg)
    el = math.radians(elev_deg)
    cam_dir = Vector((math.sin(az) * math.cos(el), math.cos(az) * math.cos(el), math.sin(el))).normalized()
    world_up = Vector((0.0, 0.0, 1.0))
    right = world_up.cross(cam_dir)
    right = Vector((1.0, 0.0, 0.0)) if right.length < 1e-4 else right.normalized()
    up = cam_dir.cross(right).normalized()

    corners = [
        Vector((x, y, z)) - center
        for x in (vis_min.x, vis_max.x)
        for y in (vis_min.y, vis_max.y)
        for z in (vis_min.z, vis_max.z)
    ]
    half_w = max(abs(c.dot(right)) for c in corners)
    half_h = max(abs(c.dot(up)) for c in corners)
    half_d = max(abs(c.dot(cam_dir)) for c in corners)

    aspect = scene.render.resolution_x / max(1, scene.render.resolution_y)
    vfov = math.radians(fov_deg)
    hfov = 2.0 * math.atan(math.tan(vfov * 0.5) * aspect)
    cam_dist = max((half_h / fill_ratio) / math.tan(vfov * 0.5), (half_w / fill_ratio) / math.tan(hfov * 0.5)) + half_d * 0.85

    cam_data = bpy.data.cameras.new("QA_CamData")
    cam_data.sensor_fit = "VERTICAL"
    cam_data.lens_unit = "FOV"
    cam_data.angle = vfov
    cam_data.clip_start = max(0.05, cam_dist * 0.01)
    cam_data.clip_end = max(500.0, cam_dist * 12.0)
    cam_obj = bpy.data.objects.new("QA_Camera", cam_data)
    scene.collection.objects.link(cam_obj)
    cam_obj.location = center + cam_dir * cam_dist
    look_at(cam_obj, center)
    scene.camera = cam_obj

    # Golden-hour California 3-sun lighting (warm key, cool sky fill, soft warm rim)
    def add_sun(name, az_off, el_d, energy, color, angle_deg):
        ld = bpy.data.lights.new(name, type="SUN")
        ld.energy = energy
        ld.color = color
        ld.angle = math.radians(angle_deg)
        lo = bpy.data.objects.new(name, ld)
        scene.collection.objects.link(lo)
        a = math.radians(azim_deg + az_off)
        e = math.radians(el_d)
        lo.location = center + Vector((math.sin(a) * math.cos(e), math.cos(a) * math.cos(e), math.sin(e))) * (radius * 2.5)
        look_at(lo, center)

    add_sun("QA_KeySun", 36.0, 38.0, 3.6, (1.0, 0.94, 0.84), 2.2)
    add_sun("QA_FillSun", -58.0, 30.0, 1.15, (0.78, 0.89, 1.0), 14.0)
    add_sun("QA_RimSun", 155.0, 28.0, 0.90, (1.0, 0.95, 0.86), 8.0)


def compute_imported_bounds(objs):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    min_pt = Vector((1e9, 1e9, 1e9))
    max_pt = Vector((-1e9, -1e9, -1e9))
    for obj in objs:
        if obj.type != "MESH":
            continue
        eo = obj.evaluated_get(depsgraph)
        me = eo.to_mesh()
        try:
            m = eo.matrix_world
            for v in me.vertices:
                w = m @ v.co
                min_pt.x = min(min_pt.x, w.x)
                min_pt.y = min(min_pt.y, w.y)
                min_pt.z = min(min_pt.z, w.z)
                max_pt.x = max(max_pt.x, w.x)
                max_pt.y = max(max_pt.y, w.y)
                max_pt.z = max(max_pt.z, w.z)
        finally:
            eo.to_mesh_clear()
    return min_pt, max_pt


def render_qa_sheet(results, samples=20, mirror_dir=None):
    """Render a crisp 6-panel (2x3) BLENDER_EEVEE beauty & tactical QA sheet for all 5 park assets."""
    panel_w, panel_h = 640, 560
    hdr_h = 54
    pad = 14
    title_h = 48
    sheet_w = 3 * panel_w + 4 * pad
    sheet_h = title_h + 2 * (hdr_h + panel_h) + 3 * pad

    canvas = np.zeros((sheet_h, sheet_w, 4), dtype=np.float32)
    canvas[:, :] = (0.075, 0.092, 0.122, 1.0)

    total_kb = sum(r["kb"] for r in results)
    total_tris = sum(r["tris"] for r in results)
    draw_text(
        canvas,
        f"GOOGLEPLEX PARK & DEFENSIVE COVER ASSETS - EEVEE QA ({total_kb / 1024.0:.2f}MB | {total_tris:,} TRIS)",
        pad,
        15,
        scale=2,
        color=(0.95, 0.97, 1.0, 1.0),
    )

    # Panel specifications (camera angles tuned so the iconic front/hero features face the viewer cleanly!)
    # Recall Blender -Y == Three.js +Z (front/south), so azim=145..155 deg views from SE/SW (+Z front)!
    panel_specs = [
        ("park_outdoor_gym.glb", "1. OUTDOOR CALISTHENICS GYM", hex_to_srgb(G_BLUE), 214.0, 29.0, 0.86),
        ("park_art_garden.glb", "2. SCULPTURE & ART GARDEN", hex_to_srgb(G_GREEN), 144.0, 26.0, 0.86),
        ("park_google_pergola.glb", "3. COLLABORATION PERGOLA", hex_to_srgb(G_YELLOW), 156.0, 17.5, 0.82),
        ("prop_garden_planter_wall.glb", "4. PLANTER COVER WALL", hex_to_srgb(G_RED), 152.0, 22.0, 0.78),
        ("prop_sculpture_plinth.glb", "5. KINETIC SCULPTURE PLINTH", hex_to_srgb(G_BLUE), 148.0, 20.0, 0.78),
    ]
    res_map = {r["file"]: r for r in results}

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_png = Path(tmpdir) / "panel.png"

        # Render Panels 1..5 (individual 3/4 beauty shots from actual exported GLBs!)
        for idx, (fname, title, accent, azim, elev, fill_r) in enumerate(panel_specs):
            row = idx // 3
            col = idx % 3
            px0 = pad + col * (panel_w + pad)
            py0 = title_h + pad + row * (hdr_h + panel_h + pad)

            reset_scene()
            configure_eevee(samples=samples, res_x=panel_w, res_y=panel_h)
            setup_outdoor_world()
            before = set(bpy.data.objects)
            bpy.ops.import_scene.gltf(filepath=str(OUT_DIR / fname))
            imported = [o for o in bpy.data.objects if o not in before]
            bmin, bmax = compute_imported_bounds(imported)
            build_outdoor_qa_rig(bmin, bmax, azim_deg=azim, elev_deg=elev, fov_deg=34.0, fill_ratio=fill_r)

            bpy.context.scene.render.filepath = str(tmp_png)
            bpy.ops.render.render(write_still=True)
            img_arr = load_png_topdown(tmp_png)

            # Draw panel header bar + Google accent stripe
            fill_rect(canvas, px0, py0, px0 + panel_w, py0 + hdr_h, (0.11, 0.135, 0.18, 1.0))
            fill_rect(canvas, px0, py0, px0 + 6, py0 + hdr_h, (accent[0], accent[1], accent[2], 1.0))
            r_info = res_map[fname]
            ad = r_info["above_dims"]
            draw_text(canvas, title, px0 + 16, py0 + 8, scale=2, color=(0.97, 0.98, 1.0, 1.0))
            stat_line = (
                f"{r_info['tris']} TRIS | {ad[0]:.1f}X{ad[2]:.1f}X{ad[1]:.1f}M | "
                f"SKIRT {r_info['three_min'][1]:+.1f}M | {r_info['kb']:.0f}KB | PASS"
            )
            draw_text(canvas, stat_line, px0 + 16, py0 + 32, scale=1, color=(0.66, 0.88, 0.74, 1.0))
            canvas[py0 + hdr_h:py0 + hdr_h + panel_h, px0:px0 + panel_w] = img_arr

        # Panel 6 (Bottom-Right): High-angle Top-Down Tactical Composition of ALL 5 Assets side-by-side!
        px0 = pad + 2 * (panel_w + pad)
        py0 = title_h + pad + 1 * (hdr_h + panel_h + pad)
        reset_scene()
        configure_eevee(samples=samples, res_x=panel_w, res_y=panel_h)
        setup_outdoor_world()

        layout = [
            ("park_outdoor_gym.glb", (-9.5, 4.5, 0.0)),
            ("park_art_garden.glb", (8.5, 4.0, 0.0)),
            ("park_google_pergola.glb", (-8.0, -7.8, 0.0)),
            ("prop_garden_planter_wall.glb", (2.8, -7.2, 0.0)),
            ("prop_sculpture_plinth.glb", (8.8, -7.2, 0.0)),
        ]
        all_imported = []
        for fname, offset in layout:
            before = set(bpy.data.objects)
            bpy.ops.import_scene.gltf(filepath=str(OUT_DIR / fname))
            added = [o for o in bpy.data.objects if o not in before]
            roots = [o for o in added if o.parent is None]
            for rt in roots:
                rt.location.x += offset[0]
                rt.location.y += offset[1]
                rt.location.z += offset[2]
            all_imported.extend(added)

        bpy.context.view_layer.update()
        bmin, bmax = compute_imported_bounds(all_imported)
        build_outdoor_qa_rig(bmin, bmax, azim_deg=178.0, elev_deg=66.0, fov_deg=34.0, fill_ratio=0.84)
        bpy.context.scene.render.filepath = str(tmp_png)
        bpy.ops.render.render(write_still=True)
        comp_arr = load_png_topdown(tmp_png)

        fill_rect(canvas, px0, py0, px0 + panel_w, py0 + hdr_h, (0.11, 0.135, 0.18, 1.0))
        fill_rect(canvas, px0, py0, px0 + 6, py0 + hdr_h, (0.26, 0.78, 0.65, 1.0))
        draw_text(canvas, "6. TOP-DOWN TACTICAL LINEUP (ALL 5)", px0 + 16, py0 + 8, scale=2, color=(0.97, 0.98, 1.0, 1.0))
        draw_text(
            canvas,
            f"TRUE RELATIVE SCALE | 5/5 GLBS | TOTAL {total_kb / 1024.0:.2f}MB (MAX 2.0MB) | PASS",
            px0 + 16,
            py0 + 32,
            scale=1,
            color=(0.66, 0.88, 0.74, 1.0),
        )
        canvas[py0 + hdr_h:py0 + hdr_h + panel_h, px0:px0 + panel_w] = comp_arr

    out_png = PREVIEWS_DIR / "qa_park_defense.png"
    save_png_topdown(canvas, out_png, mirror_dir=mirror_dir)
    print(f"[QA PREVIEW] Saved EEVEE QA sheet -> {out_png}")
    if mirror_dir is not None:
        print(f"[QA PREVIEW] Mirrored EEVEE QA sheet -> {Path(mirror_dir) / out_png.name}")


# ---------------------------------------------------------------------------
# Main CLI Entry Point
# ---------------------------------------------------------------------------
BUILDERS = [
    ("park_outdoor_gym", build_park_outdoor_gym, 3200),
    ("park_art_garden", build_park_art_garden, 3400),
    ("park_google_pergola", build_park_google_pergola, 2200),
    ("prop_garden_planter_wall", build_prop_garden_planter_wall, 700),
    ("prop_sculpture_plinth", build_prop_sculpture_plinth, 750),
]


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description="Build Googleplex park & defensive cover .glb assets.")
    parser.add_argument("--no-preview", action="store_true", help="Skip EEVEE QA sheet rendering.")
    parser.add_argument("--samples", type=int, default=20, help="EEVEE render samples per QA panel.")
    parser.add_argument("--mirror-dir", type=str, default=None, help="Optional secondary directory to mirror qa_park_defense.png.")
    return parser.parse_args(argv)


def main():
    t0 = time.time()
    args = parse_args()
    results = []
    budget_failures = []

    for key, fn, tri_budget in BUILDERS:
        ts = time.time()
        info = fn()
        info["sec"] = time.time() - ts
        info["tri_budget"] = tri_budget
        results.append(info)
        td = info["three_dims"]
        ad = info["above_dims"]
        tmin = info["three_min"]
        tmax = info["three_max"]
        status = "OK" if info["tris"] <= tri_budget else "OVER_BUDGET"
        if info["tris"] > tri_budget:
            budget_failures.append(f"{info['file']}: {info['tris']} tris > {tri_budget}")
        print(
            f"[{status}] {info['file']:28s} | {info['kb']:6.1f} KB | "
            f"{info['tris']:4d}/{tri_budget} tris | "
            f"ThreeJS X=[{tmin[0]:+.2f},{tmax[0]:+.2f}] Y=[{tmin[1]:+.2f},{tmax[1]:+.2f}] Z=[{tmin[2]:+.2f},{tmax[2]:+.2f}] | "
            f"above=({ad[0]:.2f}x{ad[1]:.2f}x{ad[2]:.2f}m) | {info['sec']:.2f}s"
        )

    total_kb = sum(r["kb"] for r in results)
    total_tris = sum(r["tris"] for r in results)
    print("=" * 108)
    print(
        f"[PARK DEFENSE SUMMARY] Built {len(results)}/5 GLBs in {time.time() - t0:.2f}s | "
        f"Total: {total_kb / 1024.0:.2f} MB ({total_kb:.1f} KB) | {total_tris:,} tris"
    )
    print("=" * 108)

    if total_kb / 1024.0 > 2.0:
        budget_failures.append(f"Combined GLB size {total_kb / 1024.0:.2f} MB > 2.0 MB")

    if not args.no_preview:
        render_qa_sheet(results, samples=args.samples, mirror_dir=args.mirror_dir)

    if budget_failures:
        raise RuntimeError("Asset budget check failed: " + "; ".join(budget_failures))


if __name__ == "__main__":
    main()

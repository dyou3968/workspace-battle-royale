#!/usr/bin/env python3
"""
Workspace Royale — Blender 5.3.0 Procedural Tactical Weapons Generator
Generates 5 realistic beveled PBR tactical firearms as glTF 2.0 (.glb) assets,
each with its own unmistakable bespoke PBR material palette and packed 512x512
procedural PNG skin texture:
  1. public/assets/weapons/weapon_vanguard_m4.glb   (Assault Rifle, ~0.82m — "Arctic Apex")
  2. public/assets/weapons/weapon_breaker_12g.glb   (Tactical Shotgun, ~0.88m — "Hazard Forge")
  3. public/assets/weapons/weapon_vector_9.glb      (Compact PDW/SMG, ~0.52m — "Cyber Pulse")
  4. public/assets/weapons/weapon_longbow_308.glb   (Marksman Sniper, ~1.18m — "Shoreline Viper")
  5. public/assets/weapons/weapon_nova_gl40.glb     (Ordnance Launcher, ~0.78m — "Hypernova Prism")

Conventions:
  - 1 Blender Unit = 1.0 meter
  - Pistol grip centered cleanly near origin (0, 0, 0)
  - Barrel points along +Y in Blender (-> +Z forward in Three.js with export_yup=True)
  - Top/optics along +Z, right side along +X
  - Every weapon exports:
      * Named material slot `RarityAccent` for runtime Common/Rare/Epic tinting
      * Named Empty object `MuzzlePoint` positioned precisely at the barrel tip (+Y)
      * Packed 512x512 procedural PNG skin texture embedded inside the .glb
      * Triangle count strictly within 900-2,400 tris with BEVEL(segments=2) & smooth/weighted normals

Usage:
  blender --background --python scripts/blender/build_weapons.py
"""

import json
import math
import os
import struct
import sys
import bpy
import bmesh
import numpy as np
from mathutils import Vector, Matrix, Euler


# ---------------------------------------------------------------------------
# Paths & Constants
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
OUT_DIR = os.path.join(PROJECT_ROOT, "public", "assets", "weapons")
os.makedirs(OUT_DIR, exist_ok=True)

# Per-material UV scale registry (world meters -> UV tiles); cleared each weapon build
MAT_UV_SCALES: dict[str, float] = {}


# ---------------------------------------------------------------------------
# Color & Procedural Texture / Normal Map Helpers
# ---------------------------------------------------------------------------
def srgb_to_linear_channel(c: float) -> float:
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def srgb(r: float, g: float, b: float, a: float = 1.0):
    return (
        srgb_to_linear_channel(r),
        srgb_to_linear_channel(g),
        srgb_to_linear_channel(b),
        a,
    )


def hex_srgb(hex_str: str) -> np.ndarray:
    """Convert '#rrggbb' to float32 sRGB array in [0, 1] for Blender sRGB image pixels."""
    h = hex_str.lstrip("#")
    return np.array(
        [int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0],
        dtype=np.float32,
    )


def hex_linear(hex_str: str, a: float = 1.0) -> tuple:
    """Convert '#rrggbb' to linear RGBA tuple for Principled BSDF sockets."""
    c = hex_srgb(hex_str)
    return srgb(float(c[0]), float(c[1]), float(c[2]), a)


def smoothstep(edge0, edge1, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - edge0) / np.maximum(edge1 - edge0, 1e-6), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def lerp_rgb(a: np.ndarray, b: np.ndarray, mask: np.ndarray) -> np.ndarray:
    m = np.clip(mask, 0.0, 1.0)[..., None]
    return a * (1.0 - m) + b * m


def pack_srgb_png(name: str, rgb: np.ndarray) -> bpy.types.Image:
    """Pack a (H, W, 3) float32 sRGB [0..1] array as a crisp embedded PNG Image."""
    h, w, _ = rgb.shape
    rgba = np.ones((h, w, 4), dtype=np.float32)
    rgba[..., :3] = np.clip(rgb, 0.0, 1.0)
    img = bpy.data.images.new(name, width=w, height=h, alpha=False)
    img.colorspace_settings.name = "sRGB"
    img.file_format = "PNG"
    img.pixels.foreach_set(rgba.ravel())
    img.pack()
    return img


def periodic_hex_voronoi(u: np.ndarray, v: np.ndarray, nx: int = 8, ny: int = 7):
    """
    Exact 100% seamlessly tileable flat-top hexagonal tessellation on [0, 1) x [0, 1).
    Requires even nx so odd-column half-row shift wraps seamlessly at u=0/1.
    Returns (d1, d2, d3, cell_ix, cell_iy, local_du, local_dv).
    """
    h, w = u.shape
    sx = u * nx
    sy = v * ny

    # Base integer cell approximation
    ix0 = np.floor(sx).astype(np.int32)
    iy0 = np.floor(sy).astype(np.int32)

    d1 = np.full((h, w), 1e9, dtype=np.float32)
    d2 = np.full((h, w), 1e9, dtype=np.float32)
    d3 = np.full((h, w), 1e9, dtype=np.float32)
    best_ix = np.zeros((h, w), dtype=np.int32)
    best_iy = np.zeros((h, w), dtype=np.int32)
    best_du = np.zeros((h, w), dtype=np.float32)
    best_dv = np.zeros((h, w), dtype=np.float32)

    # Metric scale so hexes stay visually regular (dx = 1/nx, dy = 1/ny)
    inv_nx = 1.0 / float(nx)
    inv_ny = 1.0 / float(ny)

    for ox in (-1, 0, 1):
        cx = ix0 + ox
        y_shift = 0.5 * (cx & 1)
        for oy in (-1, 0, 1):
            cy = iy0 + oy
            center_x = (cx + 0.5) * inv_nx
            center_y = (cy + 0.5 + y_shift) * inv_ny
            # Shortest periodic delta on torus [0, 1)^2
            du = u - center_x
            du -= np.round(du)
            dv = v - center_y
            dv -= np.round(dv)
            dist = np.sqrt(du * du + dv * dv).astype(np.float32)

            m1 = dist < d1
            m2 = (~m1) & (dist < d2)
            m3 = (~m1) & (~m2) & (dist < d3)

            d3 = np.where(m1, d2, np.where(m2, d2, np.where(m3, dist, d3)))
            d2 = np.where(m1, d1, np.where(m2, dist, d2))
            d1 = np.where(m1, dist, d1)
            best_ix = np.where(m1, cx % nx, best_ix)
            best_iy = np.where(m1, cy % ny, best_iy)
            best_du = np.where(m1, du, best_du)
            best_dv = np.where(m1, dv, best_dv)

    return d1, d2, d3, best_ix, best_iy, best_du, best_dv


# ---------------------------------------------------------------------------
# 5 Bespoke Procedural 512x512 Weapon Skin Generators
# ---------------------------------------------------------------------------
def make_m4_arctic_apex_tex(size: int = 512) -> bpy.types.Image:
    """
    Vanguard M4 — 'Arctic Apex' (512x512 seamless PNG)
    Aerospace pearl-white ceramic (#eef3f8) with razor-sharp forward-pointing
    cobalt-blue racing chevrons (#2563eb), sky-azure highlight pinstripes (#38bdf8),
    dark carbon-slate geometric inlays (#1e293b), and aerospace micro-panel seams.
    """
    lin = np.linspace(0.0, 1.0, size, endpoint=False, dtype=np.float32)
    u, v = np.meshgrid(lin, lin)

    pearl = hex_srgb("#eef3f8")
    pearl_shade = hex_srgb("#dfe8f2")
    cobalt = hex_srgb("#2563eb")
    cobalt_deep = hex_srgb("#1d4ed8")
    azure = hex_srgb("#38bdf8")
    slate_dark = hex_srgb("#1e293b")
    slate_weave = hex_srgb("#2d3e56")
    seam_col = hex_srgb("#7b8fa8")
    seam_dark = hex_srgb("#3b4c63")

    # Subtle aerospace brushed ceramic shimmer (smooth, compresses cleanly)
    shimmer = 0.5 + 0.5 * np.sin(2.0 * np.pi * (v * 6.0)) * 0.35 + 0.25 * np.cos(2.0 * np.pi * (u * 2.0))
    rgb = lerp_rgb(pearl_shade, pearl, np.clip(0.55 + 0.45 * shimmer, 0.0, 1.0))

    # Forward-pointing aerospace chevron coordinate centered at v=0.36 (receiver midline)
    dv = ((v - 0.36 + 0.5) % 1.0) - 0.5
    apex = 1.0 - 2.0 * np.abs(dv)
    p = (u - 0.42 * apex) % 1.0
    aa = 0.004

    def band(val, lo, hi):
        return smoothstep(lo - aa, lo + aa, val) * (1.0 - smoothstep(hi - aa, hi + aa, val))

    # Dark carbon-slate geometric angular inlay (0.46..0.63 with stepped geometric wing notch)
    inlay_lo = 0.465 + 0.03 * smoothstep(0.16, 0.19, np.abs(dv))
    inlay_hi = 0.625 - 0.02 * smoothstep(0.28, 0.31, np.abs(dv))
    inlay_mask = smoothstep(inlay_lo - aa, inlay_lo + aa, p) * (1.0 - smoothstep(inlay_hi - aa, inlay_hi + aa, p))
    # Subtle micro-diagonal carbon texture inside dark carbon-slate inlay
    hatch = 0.5 + 0.5 * np.sin(2.0 * np.pi * (u * 48.0 + v * 48.0))
    inlay_rgb = lerp_rgb(slate_dark, slate_weave, hatch * 0.45)
    rgb = lerp_rgb(rgb, inlay_rgb, inlay_mask)

    # Primary bold cobalt-blue racing chevron (0.14..0.30)
    chev1 = band(p, 0.14, 0.30)
    chev1_grad = lerp_rgb(cobalt_deep, cobalt, smoothstep(0.14, 0.30, p))
    rgb = lerp_rgb(rgb, chev1_grad, chev1)

    # Crisp sky-azure leading-edge pinstripe along primary chevron
    azure_line = band(p, 0.292, 0.312)
    rgb = lerp_rgb(rgb, azure, azure_line)

    # Secondary sleek cobalt chevron (0.345..0.418)
    chev2 = band(p, 0.345, 0.418)
    rgb = lerp_rgb(rgb, cobalt_deep, chev2)

    # Crisp secondary narrow sky accent behind carbon inlay
    tail_line = band(p, 0.642, 0.654)
    rgb = lerp_rgb(rgb, cobalt, tail_line)

    # Aerospace horizontal micro-panel seams & subtle recessed plate lines
    seam_h1 = np.exp(-((np.abs(dv) - 0.21) / 0.0045) ** 2)
    seam_h2 = np.exp(-((np.abs(dv) - 0.44) / 0.0045) ** 2)
    seam_v = np.exp(-(((p - 0.80 + 0.5) % 1.0 - 0.5) / 0.0042) ** 2)
    seam_mask = np.clip(np.maximum(np.maximum(seam_h1, seam_h2), seam_v * 0.85), 0.0, 1.0)
    rgb = lerp_rgb(rgb, seam_col, seam_mask * (1.0 - inlay_mask * 0.6) * 0.65)

    # Miniature precision flush panel rivets along ceramic seam
    rivet_u = ((p - 0.80 + 0.5) % 1.0 - 0.5)
    rivet_mask = np.zeros((size, size), dtype=np.float32)
    for rv in (-0.29, -0.13, 0.13, 0.29):
        rdist = np.sqrt((rivet_u - 0.032) ** 2 + (dv - rv) ** 2)
        rivet_mask = np.maximum(rivet_mask, 1.0 - smoothstep(0.006, 0.010, rdist))
    rgb = lerp_rgb(rgb, seam_dark, rivet_mask * 0.75)

    return pack_srgb_png("M4_ArcticApexTex", rgb)


def make_breaker_hazard_forge_tex(size: int = 512) -> bpy.types.Image:
    """
    Breaker 12G — 'Hazard Forge' (512x512 seamless PNG)
    Industrial CQB breacher finish: bold blaze-orange (#ea580c / #f97316) armor
    banded with crisp 45-degree charcoal (#1a1d22) & safety-amber (#fbbf24)
    caution hazard stripes, forged panel borders, and brushed steel wear accents.
    """
    lin = np.linspace(0.0, 1.0, size, endpoint=False, dtype=np.float32)
    u, v = np.meshgrid(lin, lin)

    orange_hi = hex_srgb("#f97316")
    orange_lo = hex_srgb("#ea580c")
    orange_deep = hex_srgb("#c2410c")
    amber = hex_srgb("#fbbf24")
    amber_deep = hex_srgb("#f59e0b")
    charcoal = hex_srgb("#1a1d22")
    charcoal_dark = hex_srgb("#111318")
    wear_steel = hex_srgb("#c4cdd8")

    # Smooth periodic forged industrial brushed metal variation
    brush = (
        0.5
        + 0.22 * np.sin(2.0 * np.pi * (v * 24.0 + 0.3 * np.sin(2.0 * np.pi * u * 3.0)))
        + 0.18 * np.cos(2.0 * np.pi * (v * 52.0))
        + 0.10 * np.sin(2.0 * np.pi * (u * 2.0 + v * 5.0))
    )
    rgb = lerp_rgb(orange_lo, orange_hi, np.clip(brush, 0.0, 1.0))

    # Recessed industrial armor panel groove on orange field
    aa = 0.004
    def v_band(lo, hi):
        return smoothstep(lo - aa, lo + aa, v) * (1.0 - smoothstep(hi - aa, hi + aa, v))

    # Main bold caution hazard stripe zone (hits lower receiver flank & pump body cleanly)
    # Plus upper caution crown band (hits upper receiver bevel & cheek riser ridge)
    haz_main = v_band(0.17, 0.35)
    haz_upper = v_band(0.55, 0.65)
    haz_zone = np.clip(haz_main + haz_upper, 0.0, 1.0)

    # Crisp 45-degree diagonal charcoal & safety-amber caution stripes (4 cycles/tile)
    diag = (4.0 * u + 4.0 * v) % 1.0
    stripe_amber = (
        smoothstep(0.02, 0.04, diag) * (1.0 - smoothstep(0.48, 0.50, diag))
    )
    amber_col = lerp_rgb(amber_deep, amber, 0.4 + 0.6 * np.clip(brush, 0.0, 1.0))
    haz_rgb = lerp_rgb(charcoal, amber_col, stripe_amber)
    rgb = lerp_rgb(rgb, haz_rgb, haz_zone)

    # Heavy matte charcoal framing rails bordering hazard bands
    rail_centers = (0.165, 0.355, 0.545, 0.655)
    rail_mask = np.zeros((size, size), dtype=np.float32)
    for rc in rail_centers:
        rail_mask = np.maximum(rail_mask, 1.0 - smoothstep(0.008, 0.014, np.abs(v - rc)))
    rgb = lerp_rgb(rgb, charcoal_dark, rail_mask)

    # Industrial dark vertical stencil notches & forged panel seam on blaze-orange center
    panel_u = np.exp(-(((u - 0.50 + 0.5) % 1.0 - 0.5) / 0.004) ** 2)
    orange_mid = v_band(0.36, 0.54) + v_band(0.66, 0.99) + v_band(0.00, 0.16)
    rgb = lerp_rgb(rgb, orange_deep, panel_u * np.clip(orange_mid, 0.0, 1.0) * 0.75)

    # Crisp industrial caution block ticks on center orange panel
    tick_v = v_band(0.42, 0.47)
    tick_u = ((u * 8.0) % 1.0)
    tick_mask = tick_v * smoothstep(0.12, 0.15, tick_u) * (1.0 - smoothstep(0.36, 0.39, tick_u)) * smoothstep(0.10, 0.14, u) * (1.0 - smoothstep(0.42, 0.46, u))
    rgb = lerp_rgb(rgb, charcoal, tick_mask * 0.92)

    # Brushed steel edge-wear scratches concentrated along hazard border rails & corners
    wear_wave = (
        0.5
        + 0.25 * np.sin(2.0 * np.pi * (u * 7.0 + v * 19.0))
        + 0.25 * np.cos(2.0 * np.pi * (u * 13.0 - v * 31.0))
        + 0.20 * np.sin(2.0 * np.pi * (u * 23.0 + v * 5.0))
    )
    edge_prox = np.zeros((size, size), dtype=np.float32)
    for rc in rail_centers:
        edge_prox = np.maximum(edge_prox, np.exp(-((v - rc) / 0.017) ** 2))
    scuff = smoothstep(0.68, 0.84, wear_wave) * edge_prox
    # Subtle lengthwise brushed scrape glints across orange plate
    scrape = smoothstep(0.86, 0.94, wear_wave) * (0.5 + 0.5 * np.sin(2.0 * np.pi * v * 36.0)) * 0.45
    rgb = lerp_rgb(rgb, wear_steel, np.clip(scuff * 0.78 + scrape * 0.45, 0.0, 0.85))

    return pack_srgb_png("Breaker_HazardForgeTex", rgb)


def make_vector_cyber_pulse_tex(size: int = 512) -> tuple[bpy.types.Image, bpy.types.Image]:
    """
    Vector-9 SMG — 'Cyber Pulse' (512x512 seamless PNG + sparse Emissive PNG)
    Dark 3K woven carbon-fiber twill (#11161f / #1e2736) overlaid with crisp
    electric-cyan (#22d3ee) geometric hex/circuit speed-lines and hot-magenta
    (#ec4899) accent pinstripes, plus matching emissive mask so lines glow in shadows.
    """
    lin = np.linspace(0.0, 1.0, size, endpoint=False, dtype=np.float32)
    u, v = np.meshgrid(lin, lin)

    c_dark = hex_srgb("#10151f")
    c_mid = hex_srgb("#222d40")
    c_hi = hex_srgb("#344763")
    cyan = hex_srgb("#22d3ee")
    cyan_core = hex_srgb("#99f6ff")
    cyan_dim = hex_srgb("#0c4a6e")
    magenta = hex_srgb("#ec4899")
    magenta_core = hex_srgb("#f9a8d4")

    # 1) Authentic 3K 2x2 diagonal carbon-fiber twill (32 cells across 512px = 16px/cell)
    cells = 32.0
    cx = np.floor(u * cells).astype(np.int32)
    cy = np.floor(v * cells).astype(np.int32)
    fx = (u * cells) % 1.0
    fy = (v * cells) % 1.0
    is_warp = ((cx + cy) % 4) < 2

    # Rounded directional fiber bundle luster + micro-filament striations
    warp_shade = np.sin(np.pi * fx) * (0.78 + 0.22 * np.sin(2.0 * np.pi * fy * 3.0))
    weft_shade = np.sin(np.pi * fy) * (0.78 + 0.22 * np.sin(2.0 * np.pi * fx * 3.0))
    tow = np.where(is_warp, warp_shade * 0.95 + 0.05, weft_shade * 0.58)
    rgb = lerp_rgb(c_dark, c_mid, np.clip(tow * 1.15, 0.0, 1.0))
    rgb = lerp_rgb(rgb, c_hi, smoothstep(0.68, 0.98, tow) * 0.72)

    emissive = np.zeros((size, size, 3), dtype=np.float32)

    # 2) Subtle geometric hexagonal energy matrix etched across carbon surface
    d1, d2, _, _, _, _, _ = periodic_hex_voronoi(u, v, nx=8, ny=7)
    d_edge = d2 - d1

    # Diagonal speed-channel along Vector Super-V slope (u - v wraps seamlessly!)
    d_slash = (u - v) % 1.0
    dist_main = np.abs(((d_slash - 0.24 + 0.5) % 1.0) - 0.5)
    hex_zone = 1.0 - smoothstep(0.08, 0.22, dist_main)
    hex_line = (1.0 - smoothstep(0.005, 0.011, d_edge)) * hex_zone
    rgb = lerp_rgb(rgb, cyan_dim, hex_line * 0.85)
    rgb = lerp_rgb(rgb, cyan, hex_line * (1.0 - smoothstep(0.04, 0.14, dist_main)) * 0.82)
    emissive = np.maximum(emissive, (cyan[None, None, :] * (hex_line * (1.0 - smoothstep(0.04, 0.14, dist_main)) * 0.55)[..., None]))

    # 3) Crisp electric-cyan diagonal circuit speed-lines
    cyan_l1 = 1.0 - smoothstep(0.011, 0.017, dist_main)
    cyan_l1_core = 1.0 - smoothstep(0.003, 0.008, dist_main)

    dist_c2 = np.abs(((d_slash - 0.285 + 0.5) % 1.0) - 0.5)
    cyan_l2 = 1.0 - smoothstep(0.005, 0.009, dist_c2)

    # Horizontal upper-receiver speed trace (v ≈ 0.56 -> z ≈ 0.093m on V9_Upper)
    dist_h = np.abs(((v - 0.56 + 0.5) % 1.0) - 0.5)
    # Periodic stepped cyber circuit jog along horizontal trace
    jog_gate = smoothstep(0.18, 0.22, u) * (1.0 - smoothstep(0.76, 0.80, u))
    cyan_h = (1.0 - smoothstep(0.006, 0.011, dist_h)) * (0.45 + 0.55 * jog_gate)

    # Secondary crisp geometric circuit elbow connecting horizontal trace to diagonal
    dist_c3 = np.abs(((d_slash - 0.72 + 0.5) % 1.0) - 0.5)
    cyan_l3 = (1.0 - smoothstep(0.004, 0.008, dist_c3)) * smoothstep(0.25, 0.30, v) * (1.0 - smoothstep(0.75, 0.80, v))

    # Glowing circuit node pads along trace intersections
    node_mask = np.zeros((size, size), dtype=np.float32)
    for nu, nv in ((0.24, 0.00), (0.80, 0.56), (0.20, 0.56), (0.52, 0.28)):
        du_n = ((u - nu + 0.5) % 1.0) - 0.5
        dv_n = ((v - nv + 0.5) % 1.0) - 0.5
        rn = np.sqrt(du_n * du_n + dv_n * dv_n)
        node_mask = np.maximum(node_mask, 1.0 - smoothstep(0.012, 0.018, rn))

    cyan_all = np.clip(np.maximum.reduce([cyan_l1, cyan_l2, cyan_h, cyan_l3, node_mask]), 0.0, 1.0)
    rgb = lerp_rgb(rgb, cyan, cyan_all)
    rgb = lerp_rgb(rgb, cyan_core, np.clip(cyan_l1_core + node_mask * 0.7, 0.0, 1.0) * 0.65)
    emissive = np.maximum(emissive, cyan[None, None, :] * cyan_all[..., None])

    # 4) Crisp hot-magenta (#ec4899) companion accent pinstripes
    dist_m1 = np.abs(((d_slash - 0.195 + 0.5) % 1.0) - 0.5)
    mag_l1 = 1.0 - smoothstep(0.0055, 0.010, dist_m1)
    dist_mh = np.abs(((v - 0.605 + 0.5) % 1.0) - 0.5)
    mag_h = (1.0 - smoothstep(0.004, 0.008, dist_mh)) * smoothstep(0.28, 0.34, u) * (1.0 - smoothstep(0.72, 0.78, u))
    mag_all = np.clip(np.maximum(mag_l1, mag_h), 0.0, 1.0)

    rgb = lerp_rgb(rgb, magenta, mag_all)
    rgb = lerp_rgb(rgb, magenta_core, mag_all * 0.25)
    emissive = np.maximum(emissive, magenta[None, None, :] * (mag_all * 0.90)[..., None])

    base_img = pack_srgb_png("Vector_CyberPulseTex", rgb)
    emiss_img = pack_srgb_png("Vector_CyberPulseEmissive", emissive)
    return base_img, emiss_img


def make_longbow_shoreline_viper_tex(size: int = 512) -> bpy.types.Image:
    """
    Longbow .308 — 'Shoreline Viper' (512x512 seamless PNG)
    Matte deep-emerald (#1c3829), forest-olive (#355e45), tactical sage (#4b7a58),
    and desert-sand (#c9b37e) sharp topographic contour / geometric tactical camo
    with gradient-normalized uniform-width contour lines.
    """
    lin = np.linspace(0.0, 1.0, size, endpoint=False, dtype=np.float32)
    u, v = np.meshgrid(lin, lin)
    tau = 2.0 * np.pi

    emerald = hex_srgb("#1c3829")
    olive = hex_srgb("#355e45")
    sage = hex_srgb("#4c7c5a")
    sand = hex_srgb("#c9b37e")
    sand_hi = hex_srgb("#dac796")
    line_light = hex_srgb("#e3d4a8")
    line_dark = hex_srgb("#13271c")

    # 100% seamlessly periodic domain-warped elevation field on [0, 1)^2
    wu = u + 0.075 * np.sin(tau * (v * 2.0 + u * 1.0) + 0.4) + 0.035 * np.cos(tau * (v * 3.0 - u * 2.0) + 1.1)
    wv = v + 0.075 * np.cos(tau * (u * 2.0 - v * 1.0) + 2.0) + 0.035 * np.sin(tau * (u * 3.0 + v * 2.0) + 0.7)

    h_raw = (
        0.44 * np.sin(tau * (wu * 1.0 + wv * 1.0) + 0.3)
        + 0.34 * np.cos(tau * (wu * 2.0 - wv * 1.0) + 1.4)
        + 0.26 * np.sin(tau * (wu * 1.0 - wv * 2.0) + 2.2)
        + 0.18 * np.cos(tau * (wu * 3.0 + wv * 2.0) + 0.9)
        + 0.12 * np.sin(tau * (wu * 2.0 + wv * 3.0) + 3.1)
        + 0.07 * np.cos(tau * (wu * 4.0 - wv * 3.0) + 1.7)
    )
    h = (h_raw - h_raw.min()) / max(float(h_raw.max() - h_raw.min()), 1e-6)

    # Sharp stepped 4-tier camo bands (deep emerald -> forest olive -> sage -> desert sand)
    rgb = np.broadcast_to(emerald, (size, size, 3)).copy()
    rgb = lerp_rgb(rgb, olive, smoothstep(0.29, 0.305, h))
    rgb = lerp_rgb(rgb, sage, smoothstep(0.54, 0.555, h))
    rgb = lerp_rgb(rgb, sand, smoothstep(0.695, 0.710, h))
    rgb = lerp_rgb(rgb, sand_hi, smoothstep(0.84, 0.855, h))

    # Crisp geometric tactical camo polygon accent shards (adds modern marksman edge!)
    geo_phase = (2.0 * u - v) % 1.0
    shard = (
        smoothstep(0.08, 0.09, geo_phase)
        * (1.0 - smoothstep(0.16, 0.17, geo_phase))
        * smoothstep(0.25, 0.27, v)
        * (1.0 - smoothstep(0.62, 0.64, v))
    )
    rgb = lerp_rgb(rgb, emerald, shard * 0.45)

    # Gradient-normalized uniform-width crisp topographic contour lines!
    dh_du = (np.roll(h, -1, axis=1) - np.roll(h, 1, axis=1)) * 0.5
    dh_dv = (np.roll(h, -1, axis=0) - np.roll(h, 1, axis=0)) * 0.5
    grad_px = np.sqrt(dh_du * dh_du + dh_dv * dh_dv) + 1e-5

    major_levels = (0.30, 0.55, 0.70)
    minor_levels = (0.12, 0.21, 0.42, 0.63, 0.80, 0.89)

    major_mask = np.zeros((size, size), dtype=np.float32)
    for lvl in major_levels:
        dist_px = np.abs(h - lvl) / grad_px
        major_mask = np.maximum(major_mask, 1.0 - smoothstep(1.1, 2.2, dist_px))

    minor_mask = np.zeros((size, size), dtype=np.float32)
    for lvl in minor_levels:
        dist_px = np.abs(h - lvl) / grad_px
        minor_mask = np.maximum(minor_mask, 1.0 - smoothstep(0.7, 1.5, dist_px))

    # Pale-sand contour lines over dark green terrain; deep-forest contour lines over sand
    is_sand = smoothstep(0.68, 0.72, h)
    contour_col = lerp_rgb(line_light, line_dark, is_sand)
    rgb = lerp_rgb(rgb, contour_col, np.clip(major_mask * 0.90 + minor_mask * 0.65, 0.0, 0.92))

    return pack_srgb_png("Longbow_ShorelineViperTex", rgb)


def make_nova_hypernova_prism_tex(size: int = 512) -> tuple[bpy.types.Image, bpy.types.Image]:
    """
    Nova GL-40 — 'Hypernova Prism' (512x512 seamless PNG + subtle Emissive PNG)
    Deep satin cosmic-indigo (#28105c) & royal-amethyst (#4c1d95) crystalline hex
    armor plates veined with surgical luminous violet (#a855f7) and selective
    anodized gold (#eab308) hexagonal energy-cell lines.
    """
    lin = np.linspace(0.0, 1.0, size, endpoint=False, dtype=np.float32)
    u, v = np.meshgrid(lin, lin)

    indigo_deep = hex_srgb("#1b0a42")
    indigo = hex_srgb("#28105c")
    amethyst = hex_srgb("#4c1d95")
    prism_hi = hex_srgb("#5e24b5")
    violet_glow = hex_srgb("#a855f7")
    violet_core = hex_srgb("#d8b4fe")
    gold = hex_srgb("#eab308")
    gold_hi = hex_srgb("#fde047")

    # 100% seamless periodic flat-top hex tessellation (grander sleek armor scale)
    d1, d2, d3, cid_x, cid_y, du, dv = periodic_hex_voronoi(u, v, nx=6, ny=5)
    d_edge = d2 - d1
    d_vert = d3 - d1

    # Deterministic per-hex satin prism facet tone (deep cosmic-indigo <-> royal-amethyst)
    cell_hash = ((cid_x * 37 + cid_y * 73 + (cid_x ^ cid_y) * 19) % 9) / 8.0
    base_tile = lerp_rgb(indigo, amethyst, cell_hash * 0.85)
    # Subtle crystalline angled facet sheen inside each hex tile
    facet_grad = np.clip(0.5 + (du * 3.6 + dv * 3.0), 0.0, 1.0)
    rgb = lerp_rgb(indigo_deep, base_tile, 0.45 + 0.55 * facet_grad)
    hi_cells = (cell_hash > 0.72).astype(np.float32)
    rgb = lerp_rgb(rgb, prism_hi, hi_cells * smoothstep(0.60, 0.96, facet_grad) * 0.35)

    # Subtle recessed dark chamfer just inside hex border for armored plate depth
    inner_bevel = smoothstep(0.006, 0.012, d_edge) * (1.0 - smoothstep(0.016, 0.025, d_edge))
    rgb = lerp_rgb(rgb, indigo_deep, inner_bevel * 0.65)

    # Razor-crisp surgical hex energy-cell borders: luminous violet (#a855f7) + selective anodized gold (#eab308)
    hex_border = 1.0 - smoothstep(0.0045, 0.010, d_edge)
    hex_core = 1.0 - smoothstep(0.0015, 0.0045, d_edge)

    # Sleek diagonal golden prism energy conduit vein (seamless on [0,1)^2)
    vein_p = (u + v) % 1.0
    gold_vein = 1.0 - smoothstep(0.06, 0.14, np.abs(((vein_p - 0.35 + 0.5) % 1.0) - 0.5))
    gold_select = np.clip(gold_vein, 0.0, 1.0)

    border_col = lerp_rgb(violet_glow, gold, gold_select)
    core_col = lerp_rgb(violet_core, gold_hi, gold_select)
    rgb = lerp_rgb(rgb, border_col, hex_border * 0.92)
    rgb = lerp_rgb(rgb, core_col, hex_core * 0.50)

    # Subtle precision energy-cell dots at hex triple-junction vertices
    vert_node = 1.0 - smoothstep(0.008, 0.015, d_vert)
    node_col = lerp_rgb(violet_core, gold_hi, gold_select)
    rgb = lerp_rgb(rgb, node_col, vert_node * 0.72)

    # Sleek anodized gold trim pinstripe along horizontal armor seam
    gold_band = 1.0 - smoothstep(0.0045, 0.0085, np.abs(((v - 0.52 + 0.5) % 1.0) - 0.5))
    rgb = lerp_rgb(rgb, gold, gold_band * 0.90)

    # Companion subtle emissive mask (keeps NovaPlasma vents & grenades as hero glow!)
    emissive = np.zeros((size, size, 3), dtype=np.float32)
    emissive += violet_glow[None, None, :] * (hex_border * (1.0 - gold_select * 0.70) * 0.75)[..., None]
    emissive += gold[None, None, :] * (hex_border * gold_select * 0.45)[..., None]
    emissive += node_col * (vert_node * 0.65)[..., None]
    emissive = np.clip(emissive, 0.0, 1.0)

    base_img = pack_srgb_png("Nova_HypernovaPrismTex", rgb)
    emiss_img = pack_srgb_png("Nova_HypernovaEmissive", emissive)
    return base_img, emiss_img


def make_brushed_normal_image(name: str = "BrushedMetalNrm", size: int = 256) -> bpy.types.Image:
    """Generate a compact seamless fine CNC-brushed gunmetal normal map."""
    rng = np.random.default_rng(1042)
    row_streaks = rng.normal(0.0, 1.0, (size, 1)) * 0.65
    fine_noise = rng.normal(0.0, 1.0, (size, size)) * 0.35
    h = row_streaks + fine_noise
    kernel = np.array([0.08, 0.18, 0.48, 0.18, 0.08], dtype=np.float32)
    for row in range(size):
        h[row] = np.convolve(np.pad(h[row], 2, mode="wrap"), kernel, mode="valid")
    dx = (np.roll(h, -1, axis=1) - np.roll(h, 1, axis=1)) * 0.10
    dy = (np.roll(h, -1, axis=0) - np.roll(h, 1, axis=0)) * 0.22
    nx = np.clip(-dx * 0.5 + 0.5, 0.0, 1.0)
    ny = np.clip(-dy * 0.5 + 0.5, 0.0, 1.0)
    nz = np.ones_like(nx)
    rgba = np.stack([nx, ny, nz, np.ones_like(nx)], axis=-1).astype(np.float32)

    img = bpy.data.images.new(name, width=size, height=size, alpha=False)
    img.colorspace_settings.name = "Non-Color"
    img.file_format = "PNG"
    img.pixels.foreach_set(rgba.ravel())
    img.pack()
    return img


def make_stipple_normal_image(name: str = "RubberStippleNrm", size: int = 128) -> bpy.types.Image:
    """Generate a compact seamless diamond-knurl / tactical rubber stipple normal map."""
    u = np.linspace(0.0, 2.0 * np.pi * 16.0, size, endpoint=False)
    v = np.linspace(0.0, 2.0 * np.pi * 16.0, size, endpoint=False)
    uu, vv = np.meshgrid(u, v)
    rng = np.random.default_rng(2084)
    # Crisp diamond checkering + micro stipple
    h = np.sin(uu + vv) * np.sin(uu - vv) * 0.65 + rng.normal(0.0, 0.16, (size, size))
    dx = (np.roll(h, -1, axis=1) - np.roll(h, 1, axis=1)) * 0.42
    dy = (np.roll(h, -1, axis=0) - np.roll(h, 1, axis=0)) * 0.42
    nx = np.clip(-dx * 0.5 + 0.5, 0.0, 1.0)
    ny = np.clip(-dy * 0.5 + 0.5, 0.0, 1.0)
    nz = np.ones_like(nx)
    rgba = np.stack([nx, ny, nz, np.ones_like(nx)], axis=-1).astype(np.float32)

    img = bpy.data.images.new(name, width=size, height=size, alpha=False)
    img.colorspace_settings.name = "Non-Color"
    img.file_format = "PNG"
    img.pixels.foreach_set(rgba.ravel())
    img.pack()
    return img


def build_pbr_mat(
    name: str,
    base_color=(0.5, 0.5, 0.5, 1.0),
    metallic: float = 0.05,
    roughness: float = 0.5,
    spec_ior: float = 0.5,
    alpha: float = 1.0,
    ior: float = 1.45,
    emission_color=None,
    emission_strength: float = 0.0,
    base_color_img: bpy.types.Image = None,
    emission_img: bpy.types.Image = None,
    normal_img: bpy.types.Image = None,
    normal_strength: float = 0.0,
    uv_scale: float = 8.0,
) -> bpy.types.Material:
    """Create a Blender 5.3.0 Principled BSDF PBR material with optional packed textures."""
    mat = bpy.data.materials.new(name=name)
    MAT_UV_SCALES[mat.name] = uv_scale
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = base_color
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Specular IOR Level"].default_value = spec_ior
    bsdf.inputs["IOR"].default_value = ior
    bsdf.inputs["Alpha"].default_value = alpha

    if base_color_img is not None:
        tex_col = nt.nodes.new("ShaderNodeTexImage")
        tex_col.image = base_color_img
        tex_col.extension = "REPEAT"
        tex_col.interpolation = "Linear"
        tex_col.location = (-520, 260)
        nt.links.new(tex_col.outputs["Color"], bsdf.inputs["Base Color"])

    if emission_img is not None and emission_strength > 0.0:
        tex_em = nt.nodes.new("ShaderNodeTexImage")
        tex_em.image = emission_img
        tex_em.extension = "REPEAT"
        tex_em.interpolation = "Linear"
        tex_em.location = (-520, 0)
        nt.links.new(tex_em.outputs["Color"], bsdf.inputs["Emission Color"])
        bsdf.inputs["Emission Strength"].default_value = emission_strength
    elif emission_color is not None and emission_strength > 0.0:
        bsdf.inputs["Emission Color"].default_value = emission_color
        bsdf.inputs["Emission Strength"].default_value = emission_strength

    if normal_img is not None and normal_strength > 0.0:
        tex_nrm = nt.nodes.new("ShaderNodeTexImage")
        tex_nrm.image = normal_img
        tex_nrm.location = (-520, -260)
        nrm = nt.nodes.new("ShaderNodeNormalMap")
        nrm.inputs["Strength"].default_value = normal_strength
        nrm.location = (-240, -260)
        nt.links.new(tex_nrm.outputs["Color"], nrm.inputs["Color"])
        nt.links.new(nrm.outputs["Normal"], bsdf.inputs["Normal"])

    return mat


def create_common_weapon_materials():
    """Shared recessed bore + required runtime RarityAccent slot + compact normal maps."""
    MAT_UV_SCALES.clear()
    brushed_img = make_brushed_normal_image()
    stipple_img = make_stipple_normal_image()
    common = {
        "BoreDark": build_pbr_mat(
            "BoreDark",
            srgb(0.015, 0.015, 0.018),
            metallic=0.10,
            roughness=0.95,
            spec_ior=0.20,
        ),
        # REQUIRED RUNTIME HOOK: Named material slot `RarityAccent`
        # Subtle anodized titanium/cobalt-silver trim that Three.js dynamically tints
        # to Common (#9aa0a6), Rare (#4285f4), or Epic (#a855f7).
        "RarityAccent": build_pbr_mat(
            "RarityAccent",
            srgb(0.62, 0.68, 0.76),
            metallic=0.68,
            roughness=0.25,
            spec_ior=0.60,
            emission_color=srgb(0.35, 0.45, 0.60),
            emission_strength=0.22,
        ),
    }
    return common, brushed_img, stipple_img


def create_vanguard_m4_materials() -> dict:
    """Dedicated 'Arctic Apex' PBR palette + packed 512x512 skin for Vanguard M4."""
    mats, brushed_img, stipple_img = create_common_weapon_materials()
    skin_img = make_m4_arctic_apex_tex(512)

    mats.update({
        # Pearl-white aerospace ceramic + cobalt chevrons + carbon-slate inlays
        "Skin": build_pbr_mat(
            "M4_ArcticApexCeramic",
            base_color=(1.0, 1.0, 1.0, 1.0),
            metallic=0.12,
            roughness=0.34,
            spec_ior=0.58,
            base_color_img=skin_img,
            uv_scale=5.0,
        ),
        # Deep anodized cobalt-navy metallic handguard, upper rail & holo hood
        "CobaltAnodized": build_pbr_mat(
            "M4_CobaltAnodized",
            hex_linear("#254e98"),
            metallic=0.82,
            roughness=0.28,
            spec_ior=0.62,
            normal_img=brushed_img,
            normal_strength=0.07,
        ),
        # Brushed satin-silver bolt carrier, fluted barrel, muzzle brake & hardware
        "ChromeSteel": build_pbr_mat(
            "M4_SatinSilver",
            hex_linear("#dce4ee"),
            metallic=0.92,
            roughness=0.20,
            spec_ior=0.68,
            normal_img=brushed_img,
            normal_strength=0.05,
        ),
        # Dark carbon-slate tactical polymer (trigger guard, grip cap, mag bumper)
        "TacticalPolymer": build_pbr_mat(
            "M4_CarbonSlate",
            hex_linear("#1e293b"),
            metallic=0.10,
            roughness=0.56,
            spec_ior=0.45,
        ),
        # Matte slate-rubber grip & recoil pad
        "RubberGrip": build_pbr_mat(
            "M4_SlateRubber",
            hex_linear("#232b38"),
            metallic=0.02,
            roughness=0.88,
            spec_ior=0.34,
            normal_img=stipple_img,
            normal_strength=0.32,
        ),
        # Bright sky-blue holographic optic lens
        "OpticGlass": build_pbr_mat(
            "M4_SkyOpticGlass",
            hex_linear("#38bdf8"),
            metallic=0.16,
            roughness=0.05,
            spec_ior=0.88,
            ior=1.52,
            alpha=0.70,
            emission_color=hex_linear("#38bdf8"),
            emission_strength=1.35,
        ),
    })
    return mats


def create_breaker_12g_materials() -> dict:
    """Dedicated 'Hazard Forge' PBR palette + packed 512x512 skin for Breaker 12G."""
    mats, brushed_img, stipple_img = create_common_weapon_materials()
    skin_img = make_breaker_hazard_forge_tex(512)

    mats.update({
        # Blaze-orange breacher armor with diagonal charcoal/amber caution stripes & wear
        "Skin": build_pbr_mat(
            "Breaker_HazardForgeSkin",
            base_color=(1.0, 1.0, 1.0, 1.0),
            metallic=0.20,
            roughness=0.38,
            spec_ior=0.56,
            base_color_img=skin_img,
            normal_img=brushed_img,
            normal_strength=0.06,
            uv_scale=5.5,
        ),
        # Burnished metallic copper-bronze ventilated heatshield & clamp (distinct warm bronze gleam)
        "CopperHeatshield": build_pbr_mat(
            "Breaker_CopperBronze",
            hex_linear("#cf8646"),
            metallic=0.90,
            roughness=0.22,
            spec_ior=0.68,
            normal_img=brushed_img,
            normal_strength=0.08,
        ),
        # Forged matte charcoal-iron barrel, tube mag & iron sights
        "ForgedIron": build_pbr_mat(
            "Breaker_ForgedIron",
            hex_linear("#272d36"),
            metallic=0.72,
            roughness=0.40,
            spec_ior=0.50,
            normal_img=brushed_img,
            normal_strength=0.09,
        ),
        # Rugged charcoal tactical polymer stock & side-saddle carrier
        "TacticalPolymer": build_pbr_mat(
            "Breaker_CharcoalPolymer",
            hex_linear("#2c323c"),
            metallic=0.08,
            roughness=0.62,
            spec_ior=0.44,
        ),
        # Machined steel bolt, action bars, loading gate & trigger
        "ChromeSteel": build_pbr_mat(
            "Breaker_MachinedSteel",
            hex_linear("#c8d0da"),
            metallic=0.90,
            roughness=0.22,
            spec_ior=0.64,
        ),
        # Glossy crimson 12G tactical shell hull
        "ShellRed": build_pbr_mat(
            "Breaker_GlossShellRed",
            hex_linear("#c81e1e"),
            metallic=0.04,
            roughness=0.22,
            spec_ior=0.62,
        ),
        # Polished brass 12G shell head
        "BrassAccent": build_pbr_mat(
            "Breaker_ShellBrass",
            hex_linear("#e4b342"),
            metallic=0.92,
            roughness=0.20,
            spec_ior=0.65,
        ),
        # Rugged stippled black recoil pad, grip & pump ribs
        "RubberGrip": build_pbr_mat(
            "Breaker_BlackRubber",
            hex_linear("#12151a"),
            metallic=0.02,
            roughness=0.90,
            spec_ior=0.32,
            normal_img=stipple_img,
            normal_strength=0.36,
        ),
    })
    return mats


def create_vector_9_materials() -> dict:
    """Dedicated 'Cyber Pulse' PBR palette + packed 512x512 skin for Vector-9 SMG."""
    mats, brushed_img, stipple_img = create_common_weapon_materials()
    skin_img, emiss_img = make_vector_cyber_pulse_tex(512)

    mats.update({
        # Dark 3K woven carbon-fiber twill with glowing electric-cyan circuits & magenta pinstripes
        "Skin": build_pbr_mat(
            "Vector_CyberPulseCarbon",
            base_color=(1.0, 1.0, 1.0, 1.0),
            metallic=0.20,
            roughness=0.34,
            spec_ior=0.58,
            base_color_img=skin_img,
            emission_img=emiss_img,
            emission_strength=1.35,
            uv_scale=6.0,
        ),
        # Satin deep-teal anodized suppressor, shroud, top rail & optic cage
        "TealAnodized": build_pbr_mat(
            "Vector_DeepTealAnodized",
            hex_linear("#176a82"),
            metallic=0.82,
            roughness=0.26,
            spec_ior=0.62,
            normal_img=brushed_img,
            normal_strength=0.06,
        ),
        # Dark stealth carbon polymer (trigger guard, grip cap, mag bumper)
        "TacticalPolymer": build_pbr_mat(
            "Vector_StealthPolymer",
            hex_linear("#151c27"),
            metallic=0.08,
            roughness=0.62,
            spec_ior=0.44,
        ),
        # Machined cool-silver bolt, hinge pin & trigger
        "ChromeSteel": build_pbr_mat(
            "Vector_SatinChrome",
            hex_linear("#cad6e4"),
            metallic=0.92,
            roughness=0.20,
            spec_ior=0.65,
        ),
        # Matte black stippled vertical foregrip, pistol grip & buttpad
        "RubberGrip": build_pbr_mat(
            "Vector_BlackRubber",
            hex_linear("#101319"),
            metallic=0.02,
            roughness=0.90,
            spec_ior=0.32,
            normal_img=stipple_img,
            normal_strength=0.35,
        ),
        # Vibrant electric-cyan reflex optic lens
        "OpticGlass": build_pbr_mat(
            "Vector_CyanOpticGlass",
            hex_linear("#22d3ee"),
            metallic=0.16,
            roughness=0.05,
            spec_ior=0.85,
            ior=1.52,
            alpha=0.66,
            emission_color=hex_linear("#22d3ee"),
            emission_strength=1.10,
        ),
    })
    return mats


def create_longbow_308_materials() -> dict:
    """Dedicated 'Shoreline Viper' PBR palette + packed 512x512 skin for Longbow .308."""
    mats, brushed_img, stipple_img = create_common_weapon_materials()
    skin_img = make_longbow_shoreline_viper_tex(512)

    mats.update({
        # Matte emerald/forest-olive/desert-sand topographic contour tactical camo
        "Skin": build_pbr_mat(
            "Longbow_ShorelineViperCamo",
            base_color=(1.0, 1.0, 1.0, 1.0),
            metallic=0.06,
            roughness=0.60,
            spec_ior=0.42,
            base_color_img=skin_img,
            uv_scale=4.5,
        ),
        # Brushed champagne-gold titanium fluted barrel, tank brake, bolt & scope rings
        "ChampagneGold": build_pbr_mat(
            "Longbow_ChampagneGoldTi",
            hex_linear("#dbb852"),
            metallic=0.92,
            roughness=0.22,
            spec_ior=0.68,
            normal_img=brushed_img,
            normal_strength=0.06,
        ),
        # Anti-glare matte obsidian sniper scope tube & turrets
        "ObsidianScope": build_pbr_mat(
            "Longbow_ObsidianScope",
            hex_linear("#12161c"),
            metallic=0.28,
            roughness=0.62,
            spec_ior=0.36,
        ),
        # Deep forest-gunmetal anodized action, rail, mount & bipod legs
        "ActionSteel": build_pbr_mat(
            "Longbow_ForestAnodized",
            hex_linear("#24392e"),
            metallic=0.78,
            roughness=0.32,
            spec_ior=0.52,
            normal_img=brushed_img,
            normal_strength=0.06,
        ),
        # Matte deep-forest tactical polymer (trigger guard, grip cap)
        "TacticalPolymer": build_pbr_mat(
            "Longbow_ForestPolymer",
            hex_linear("#192920"),
            metallic=0.05,
            roughness=0.74,
            spec_ior=0.38,
        ),
        # Match trigger / satin gold-tinted steel
        "ChromeSteel": build_pbr_mat(
            "Longbow_ChampagneGoldHardware",
            hex_linear("#d6b24c"),
            metallic=0.92,
            roughness=0.22,
            spec_ior=0.68,
        ),
        # Dark tactical stippled rubber grip, buttpad & bipod feet
        "RubberGrip": build_pbr_mat(
            "Longbow_TacticalRubber",
            hex_linear("#141a17"),
            metallic=0.02,
            roughness=0.90,
            spec_ior=0.32,
            normal_img=stipple_img,
            normal_strength=0.34,
        ),
        # Rich emerald-green coated sniper objective glass
        "OpticGlass": build_pbr_mat(
            "Longbow_EmeraldOpticGlass",
            hex_linear("#10b981"),
            metallic=0.22,
            roughness=0.04,
            spec_ior=0.88,
            ior=1.52,
            alpha=0.72,
            emission_color=hex_linear("#10b981"),
            emission_strength=0.85,
        ),
    })
    return mats


def create_nova_gl40_materials() -> dict:
    """Dedicated 'Hypernova Prism' PBR palette + packed 512x512 skin for Nova GL-40."""
    mats, brushed_img, stipple_img = create_common_weapon_materials()
    skin_img, emiss_img = make_nova_hypernova_prism_tex(512)

    mats.update({
        # Deep satin cosmic-indigo & royal-amethyst armor with luminous violet & gold hex lines
        "Skin": build_pbr_mat(
            "Nova_HypernovaPrismArmor",
            base_color=(1.0, 1.0, 1.0, 1.0),
            metallic=0.34,
            roughness=0.30,
            spec_ior=0.62,
            base_color_img=skin_img,
            emission_img=emiss_img,
            emission_strength=0.45,
            uv_scale=4.8,
        ),
        # Satin pearl-titanium silver revolving 6-chamber drum (dramatic contrast vs violet grenades!)
        "PearlTitanium": build_pbr_mat(
            "Nova_PearlTitaniumSilver",
            hex_linear("#dce5f0"),
            metallic=0.88,
            roughness=0.22,
            spec_ior=0.68,
            normal_img=brushed_img,
            normal_strength=0.05,
        ),
        # Anodized gold front yoke, drum axle & front hub
        "AnodizedGold": build_pbr_mat(
            "Nova_AnodizedGold",
            hex_linear("#f0be24"),
            metallic=0.90,
            roughness=0.22,
            spec_ior=0.68,
            normal_img=brushed_img,
            normal_strength=0.05,
        ),
        # Deep satin cosmic-indigo anodized barrel, bridge, rail & sight cage
        "CosmicSteel": build_pbr_mat(
            "Nova_CosmicIndigoSteel",
            hex_linear("#382274"),
            metallic=0.78,
            roughness=0.26,
            spec_ior=0.60,
            normal_img=brushed_img,
            normal_strength=0.06,
        ),
        # Deep royal-slate polymer (trigger guard, grip cap, lower rail bar)
        "TacticalPolymer": build_pbr_mat(
            "Nova_CosmicPolymer",
            hex_linear("#1e1240"),
            metallic=0.08,
            roughness=0.64,
            spec_ior=0.42,
        ),
        # Anodized gold trigger hardware
        "ChromeSteel": build_pbr_mat(
            "Nova_GoldHardware",
            hex_linear("#eab308"),
            metallic=0.90,
            roughness=0.22,
            spec_ior=0.66,
        ),
        # Glowing violet Mana-ordnance grenade warheads & capacitor vents
        "NovaPlasma": build_pbr_mat(
            "NovaPlasma",
            hex_linear("#9333ea"),
            metallic=0.10,
            roughness=0.16,
            spec_ior=0.62,
            emission_color=hex_linear("#a855f7"),
            emission_strength=1.85,
        ),
        # Anodized gold-brass 40mm grenade collars
        "BrassAccent": build_pbr_mat(
            "Nova_OrdnanceGoldCasing",
            hex_linear("#eab308"),
            metallic=0.92,
            roughness=0.20,
            spec_ior=0.65,
        ),
        # Deep obsidian-indigo stippled rubber foregrip, pistol grip & recoil pad
        "RubberGrip": build_pbr_mat(
            "Nova_ObsidianRubber",
            hex_linear("#141022"),
            metallic=0.02,
            roughness=0.90,
            spec_ior=0.32,
            normal_img=stipple_img,
            normal_strength=0.34,
        ),
        # Vivid violet-magenta reflex optic lens
        "OpticGlass": build_pbr_mat(
            "Nova_VioletOpticGlass",
            hex_linear("#d946ef"),
            metallic=0.18,
            roughness=0.05,
            spec_ior=0.86,
            ior=1.52,
            alpha=0.70,
            emission_color=hex_linear("#c026d3"),
            emission_strength=1.10,
        ),
    })
    return mats


# ---------------------------------------------------------------------------
# Hard-Surface BMesh & Modifier Geometry Primitives
# ---------------------------------------------------------------------------
def apply_box_uvs(bm: bmesh.types.BMesh, scale: float = 8.0) -> None:
    """Assign clean cubic/box-projected UVs in real-world meters for skins & brushed/stipple normals."""
    uv_layer = bm.loops.layers.uv.verify()
    for f in bm.faces:
        n = f.normal
        ax, ay, az = abs(n.x), abs(n.y), abs(n.z)
        for loop in f.loops:
            co = loop.vert.co
            if ax >= ay and ax >= az:
                # Left/right flanks: U runs along Y (barrel axis) so patterns/streaks run lengthwise
                loop[uv_layer].uv = (co.y * scale, co.z * scale)
            elif ay >= ax and ay >= az:
                loop[uv_layer].uv = (co.x * scale, co.z * scale)
            else:
                # Top/bottom: U runs along Y (barrel axis)
                loop[uv_layer].uv = (co.y * scale, co.x * scale)


def finalize_part(
    name: str,
    bm: bmesh.types.BMesh,
    mat: bpy.types.Material,
    bevel_width: float = 0.0,
    bevel_segments: int = 2,
    bevel_angle_deg: float = 30.0,
    weighted_normal: bool = True,
    sharp_angle_deg: float = 0.0,
    extra_mats=None,
) -> bpy.types.Object:
    """Convert a BMesh into an object, assign smooth shading, UVs, and modifiers."""
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.normal_update()
    uv_scale = MAT_UV_SCALES.get(mat.name, 8.0)
    apply_box_uvs(bm, scale=uv_scale)

    if sharp_angle_deg > 0.0:
        thresh = math.radians(sharp_angle_deg)
        for e in bm.edges:
            if len(e.link_faces) == 2:
                ang = e.calc_face_angle(0.0)
                e.smooth = ang < thresh

    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()

    mesh.polygons.foreach_set("use_smooth", [True] * len(mesh.polygons))
    mesh.update()

    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(mat)
    if extra_mats:
        for em in extra_mats:
            obj.data.materials.append(em)

    if bevel_width > 0.0:
        bev = obj.modifiers.new("Bevel", "BEVEL")
        bev.width = bevel_width
        bev.segments = bevel_segments
        bev.limit_method = "ANGLE"
        bev.angle_limit = math.radians(bevel_angle_deg)
        bev.use_clamp_overlap = True

    if weighted_normal and bevel_width > 0.0:
        wn = obj.modifiers.new("WeightedNormal", "WEIGHTED_NORMAL")
        wn.keep_sharp = False
        wn.weight = 50

    return obj


def make_profile_x(
    name: str,
    profile_yz,
    half_width: float,
    mat: bpy.types.Material,
    center_x: float = 0.0,
    bevel: float = 0.0025,
    bevel_segs: int = 2,
    chamfer_scale_x: float = 1.0,
    taper_top_scale: float = 1.0,
) -> bpy.types.Object:
    """
    Extrude a 2D side-view silhouette [(y, z), ...] along X around center_x.
    Produces crisp firearm silhouettes (receivers, stocks, grips, trigger guards, optics)
    with BEVEL(segments=2) + WeightedNormal.
    """
    bm = bmesh.new()
    # Ensure consistent counter-clockwise winding in (y, z)
    area = 0.0
    n = len(profile_yz)
    for i in range(n):
        y0, z0 = profile_yz[i]
        y1, z1 = profile_yz[(i + 1) % n]
        area += (y0 * z1 - y1 * z0)
    pts = list(profile_yz) if area > 0 else list(reversed(profile_yz))

    zs = [p[1] for p in pts]
    z_min, z_max = min(zs), max(zs)
    z_span = max(z_max - z_min, 1e-6)

    left_verts = []
    right_verts = []
    for y, z in pts:
        t = (z - z_min) / z_span
        hw = half_width * (1.0 + (taper_top_scale - 1.0) * t) * chamfer_scale_x
        left_verts.append(bm.verts.new((center_x - hw, y, z)))
        right_verts.append(bm.verts.new((center_x + hw, y, z)))

    bm.faces.new(list(reversed(left_verts)))
    bm.faces.new(right_verts)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new([left_verts[i], left_verts[j], right_verts[j], right_verts[i]])

    return finalize_part(name, bm, mat, bevel_width=bevel, bevel_segments=bevel_segs)


def make_box(
    name: str,
    center,
    size,
    mat: bpy.types.Material,
    bevel: float = 0.0022,
    bevel_segs: int = 2,
    rot_euler=(0.0, 0.0, 0.0),
) -> bpy.types.Object:
    """Beveled box primitive helper for compact details, clamps, ribs, and trim."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=size, verts=bm.verts)
    if any(abs(a) > 1e-6 for a in rot_euler):
        rot_m = Euler(rot_euler, "XYZ").to_matrix().to_4x4()
        bmesh.ops.transform(bm, matrix=rot_m, verts=bm.verts)
    bmesh.ops.translate(bm, vec=center, verts=bm.verts)
    return finalize_part(name, bm, mat, bevel_width=bevel, bevel_segments=bevel_segs)


def make_loft_y(
    name: str,
    sections,
    mat: bpy.types.Material,
    cap_start: bool = True,
    cap_end: bool = True,
    bevel: float = 0.0,
    bevel_segs: int = 2,
    sharp_angle_deg: float = 42.0,
) -> bpy.types.Object:
    """
    Loft a sequence of cross-sections along Y:
      sections = [(y, [(x, z), ...]), ...]
    All cross-sections must have the same vertex count.
    """
    bm = bmesh.new()
    rings = []
    for y, pts_xz in sections:
        ring = [bm.verts.new((x, y, z)) for (x, z) in pts_xz]
        rings.append(ring)

    n = len(rings[0])
    for r_idx in range(len(rings) - 1):
        r0 = rings[r_idx]
        r1 = rings[r_idx + 1]
        for i in range(n):
            j = (i + 1) % n
            bm.faces.new([r0[i], r0[j], r1[j], r1[i]])

    if cap_start:
        bm.faces.new(list(reversed(rings[0])))
    if cap_end:
        bm.faces.new(rings[-1])

    return finalize_part(
        name,
        bm,
        mat,
        bevel_width=bevel,
        bevel_segments=bevel_segs,
        sharp_angle_deg=sharp_angle_deg if bevel == 0.0 else 0.0,
    )


def octagon_xz(cx: float, cz: float, rx: float, rz: float, chamfer: float = 0.38):
    """Return 8-point chamfered octagon cross-section in (x, z) around (cx, cz)."""
    dx = rx * (1.0 - chamfer)
    dz = rz * (1.0 - chamfer)
    return [
        (cx - dx, cz - rz),
        (cx + dx, cz - rz),
        (cx + rx, cz - dz),
        (cx + rx, cz + dz),
        (cx + dx, cz + rz),
        (cx - dx, cz + rz),
        (cx - rx, cz + dz),
        (cx - rx, cz - dz),
    ]


def make_revolved_y(
    name: str,
    profile_yr,
    mat: bpy.types.Material,
    bore_mat: bpy.types.Material = None,
    segments: int = 16,
    center_xz=(0.0, 0.0),
    cap_start: bool = True,
    cap_end: bool = True,
    bore_start_idx: int = -1,
    flute_range=None,
    flute_count: int = 0,
    flute_depth: float = 0.0,
    sharp_angle_deg: float = 38.0,
) -> bpy.types.Object:
    """
    Build a smooth lathed cylindrical component aligned along +Y.
    profile_yr: list of (y, radius) stations.
    If bore_mat is provided and bore_start_idx >= 0, rings from bore_start_idx onward
    receive material index 1 (bore_mat) for crisp dark recessed barrel bores.
    """
    bm = bmesh.new()
    cx, cz = center_xz
    rings = []
    for st_idx, (y, r) in enumerate(profile_yr):
        in_flute = (
            flute_range is not None
            and flute_count > 0
            and flute_range[0] <= st_idx <= flute_range[1]
        )
        ring = []
        for s in range(segments):
            ang = 2.0 * math.pi * s / segments
            rr = r
            if in_flute:
                # Smooth fluted grooves along barrel circumference
                groove = max(0.0, math.cos(flute_count * ang))
                rr = r - flute_depth * (groove ** 2)
            ring.append(bm.verts.new((cx + rr * math.cos(ang), y, cz + rr * math.sin(ang))))
        rings.append(ring)

    extra_mats = [bore_mat] if bore_mat is not None else None
    for st_idx in range(len(rings) - 1):
        r0 = rings[st_idx]
        r1 = rings[st_idx + 1]
        mat_idx = 1 if (bore_mat is not None and bore_start_idx >= 0 and st_idx >= bore_start_idx) else 0
        for s in range(segments):
            s2 = (s + 1) % segments
            f = bm.faces.new([r0[s], r0[s2], r1[s2], r1[s]])
            f.material_index = mat_idx

    if cap_start:
        f = bm.faces.new(list(reversed(rings[0])))
        f.material_index = 0
    if cap_end:
        f = bm.faces.new(rings[-1])
        f.material_index = 1 if (bore_mat is not None and bore_start_idx >= 0) else 0

    return finalize_part(
        name,
        bm,
        mat,
        bevel_width=0.0,
        weighted_normal=False,
        sharp_angle_deg=sharp_angle_deg,
        extra_mats=extra_mats,
    )


def make_cylinder_between(
    name: str,
    p0,
    p1,
    radius0: float,
    radius1: float,
    mat: bpy.types.Material,
    segments: int = 12,
    cap: bool = True,
) -> bpy.types.Object:
    """Create a smooth tapered cylinder/rod connecting arbitrary 3D points p0 -> p1."""
    v0 = Vector(p0)
    v1 = Vector(p1)
    axis = v1 - v0
    length = axis.length
    if length < 1e-6:
        length = 1e-4
        axis = Vector((0, 1, 0))
    dir_v = axis.normalized()
    up = Vector((0, 0, 1)) if abs(dir_v.z) < 0.95 else Vector((1, 0, 0))
    side_u = dir_v.cross(up).normalized()
    side_v = dir_v.cross(side_u).normalized()

    bm = bmesh.new()
    ring0 = []
    ring1 = []
    for s in range(segments):
        ang = 2.0 * math.pi * s / segments
        ca, sa = math.cos(ang), math.sin(ang)
        off = side_u * ca + side_v * sa
        ring0.append(bm.verts.new(v0 + off * radius0))
        ring1.append(bm.verts.new(v1 + off * radius1))

    for s in range(segments):
        s2 = (s + 1) % segments
        bm.faces.new([ring0[s], ring0[s2], ring1[s2], ring1[s]])
    if cap:
        bm.faces.new(list(reversed(ring0)))
        bm.faces.new(ring1)

    return finalize_part(name, bm, mat, bevel_width=0.0, weighted_normal=False, sharp_angle_deg=45.0)


def make_picatinny_rail(
    name: str,
    y_start: float,
    y_end: float,
    z_base: float,
    mat: bpy.types.Material,
    width: float = 0.021,
    height: float = 0.0075,
    tooth_count: int = 10,
    inverted: bool = False,
) -> bpy.types.Object:
    """
    Create an authentic MIL-STD-1913 Picatinny rail with chamfered dovetail base
    and crisp individual cross-slot teeth (efficient low-poly chamfered bmesh).
    """
    bm = bmesh.new()
    sign = -1.0 if inverted else 1.0
    hw_bot = width * 0.42
    hw_top = width * 0.50
    z_mid = z_base + sign * height * 0.48
    z_top = z_base + sign * height

    # Base continuous dovetail bar
    base_pts = [
        (-hw_bot, z_base),
        (hw_bot, z_base),
        (hw_top, z_mid),
        (-hw_top, z_mid),
    ]
    if inverted:
        base_pts = list(reversed(base_pts))
    r0 = [bm.verts.new((x, y_start, z)) for (x, z) in base_pts]
    r1 = [bm.verts.new((x, y_end, z)) for (x, z) in base_pts]
    bm.faces.new(list(reversed(r0)))
    bm.faces.new(r1)
    for i in range(4):
        j = (i + 1) % 4
        bm.faces.new([r0[i], r0[j], r1[j], r1[i]])

    # Individual crisp trapezoidal cross-slot teeth
    span = y_end - y_start
    pitch = span / max(tooth_count, 1)
    tooth_len = pitch * 0.56
    hw_tooth_top = width * 0.45
    for idx in range(tooth_count):
        yc = y_start + (idx + 0.5) * pitch
        ya = yc - tooth_len * 0.5
        yb = yc + tooth_len * 0.5
        t_pts = [
            (-hw_top, z_mid),
            (hw_top, z_mid),
            (hw_tooth_top, z_top),
            (-hw_tooth_top, z_top),
        ]
        if inverted:
            t_pts = list(reversed(t_pts))
        tr0 = [bm.verts.new((x, ya, z)) for (x, z) in t_pts]
        tr1 = [bm.verts.new((x, yb, z)) for (x, z) in t_pts]
        bm.faces.new(list(reversed(tr0)))
        bm.faces.new(tr1)
        for i in range(4):
            j = (i + 1) % 4
            bm.faces.new([tr0[i], tr0[j], tr1[j], tr1[i]])

    return finalize_part(name, bm, mat, bevel_width=0.0, weighted_normal=False, sharp_angle_deg=35.0)


def make_curved_magazine(
    name: str,
    origin_yz,
    width_x: float,
    depth_y: float,
    length: float,
    curve_angle_deg: float,
    steps: int,
    mat_body: bpy.types.Material,
    mat_accent: bpy.types.Material,
    start_tilt_deg: float = 8.0,
    mat_baseplate: bpy.types.Material = None,
) -> list:
    """
    Build a curved tactical box magazine (with beveled octagonal cross-section,
    ribbed floorplate, and side RarityAccent indicator stripe).
    """
    parts = []
    y0, z0 = origin_yz
    rx = width_x * 0.5
    ry = depth_y * 0.5

    bm = bmesh.new()
    rings = []
    centers = []
    normals_fwd = []

    cur_y, cur_z = y0, z0
    ds = length / steps
    for i in range(steps + 1):
        t = i / steps
        ang = math.radians(start_tilt_deg + curve_angle_deg * t)
        # Tangent pointing downward & slightly forward (+Y, -Z)
        ty = math.sin(ang)
        tz = -math.cos(ang)
        # Forward vector perpendicular to tangent
        fy = math.cos(ang)
        fz = math.sin(ang)
        if i > 0:
            cur_y += ty * ds
            cur_z += tz * ds
        centers.append((cur_y, cur_z))
        normals_fwd.append((fy, fz))

        # 8-point chamfered rectangle in local (x, fwd) plane
        cx_ch = rx * 0.72
        cy_ch = ry * 0.78
        local_ring = [
            (-cx_ch, -ry),
            (cx_ch, -ry),
            (rx, -cy_ch),
            (rx, cy_ch),
            (cx_ch, ry),
            (-cx_ch, ry),
            (-rx, cy_ch),
            (-rx, -cy_ch),
        ]
        ring = []
        for lx, lf in local_ring:
            ring.append(bm.verts.new((lx, cur_y + lf * fy, cur_z + lf * fz)))
        rings.append(ring)

    n = len(rings[0])
    for i in range(len(rings) - 1):
        r0, r1 = rings[i], rings[i + 1]
        for k in range(n):
            k2 = (k + 1) % n
            bm.faces.new([r0[k], r0[k2], r1[k2], r1[k]])
    bm.faces.new(list(reversed(rings[0])))
    bm.faces.new(rings[-1])

    parts.append(finalize_part(f"{name}_Body", bm, mat_body, bevel_width=0.0, weighted_normal=False, sharp_angle_deg=35.0))

    # Flared floorplate bumper at bottom of magazine
    end_y, end_z = centers[-1]
    fy, fz = normals_fwd[-1]
    end_ang = math.radians(start_tilt_deg + curve_angle_deg)
    parts.append(
        make_box(
            f"{name}_Baseplate",
            (0.0, end_y + 0.003 * fy, end_z - 0.004 * math.cos(end_ang)),
            (width_x * 1.18, depth_y * 1.14, 0.013),
            mat_baseplate if mat_baseplate is not None else mat_body,
            bevel=0.0,
            rot_euler=(end_ang, 0.0, 0.0),
        )
    )

    # Subtle RarityAccent capacity indicator strip on both sides
    mid_idx = max(1, steps // 2)
    my, mz = centers[mid_idx]
    mid_ang = math.radians(start_tilt_deg + curve_angle_deg * (mid_idx / steps))
    parts.append(
        make_box(
            f"{name}_AccentStripe",
            (0.0, my, mz),
            (width_x + 0.0022, depth_y * 0.14, length * 0.38),
            mat_accent,
            bevel=0.0,
            rot_euler=(mid_ang, 0.0, 0.0),
        )
    )
    return parts


def make_pistol_grip_and_trigger(
    prefix: str,
    mats: dict,
    grip_top_z: float = 0.036,
    grip_bot_z: float = -0.064,
    rake_y: float = -0.026,
    guard_front_y: float = 0.095,
    guard_top_z: float = 0.036,
    guard_bot_z: float = 0.002,
    width: float = 0.030,
) -> list:
    """
    Build an ergonomic contoured pistol grip centered around origin (0,0,0),
    plus a contoured trigger guard loop and curved steel trigger.
    """
    parts = []
    # Bottom edge slopes cleanly at ~11 deg down toward heel
    p_heel = (rake_y - 0.018, grip_bot_z + 0.004)
    p_toe = (rake_y + 0.018, grip_bot_z - 0.003)
    grip_profile = [
        p_heel,
        p_toe,
        (0.018, grip_top_z - 0.014),
        (0.022, grip_top_z + 0.004),
        (-0.022, grip_top_z + 0.008),
        (-0.026, grip_top_z - 0.012),
        (rake_y - 0.022, grip_bot_z + 0.016),
    ]
    parts.append(
        make_profile_x(
            f"{prefix}_Grip",
            grip_profile,
            half_width=width * 0.5,
            mat=mats["RubberGrip"],
            bevel=0.0045,
            bevel_segs=2,
            taper_top_scale=0.92,
        )
    )

    # Flush bottom grip heel cap aligned exactly to p_heel -> p_toe
    cap_y = 0.5 * (p_heel[0] + p_toe[0])
    cap_z = 0.5 * (p_heel[1] + p_toe[1]) - 0.002
    cap_ang = math.atan2(p_toe[1] - p_heel[1], p_toe[0] - p_heel[0])
    parts.append(
        make_box(
            f"{prefix}_GripCap",
            (0.0, cap_y, cap_z),
            (width * 0.96, 0.038, 0.007),
            mats["TacticalPolymer"],
            bevel=0.0,
            rot_euler=(cap_ang, 0.0, 0.0),
        )
    )

    # Contoured lower trigger guard loop
    guard_profile = [
        (0.014, guard_bot_z + 0.004),
        (guard_front_y - 0.012, guard_bot_z),
        (guard_front_y + 0.004, guard_top_z),
        (guard_front_y - 0.004, guard_top_z),
        (guard_front_y - 0.016, guard_bot_z + 0.007),
        (0.016, guard_bot_z + 0.010),
    ]
    parts.append(
        make_profile_x(
            f"{prefix}_TriggerGuard",
            guard_profile,
            half_width=0.0065,
            mat=mats["TacticalPolymer"],
            bevel=0.0,
        )
    )

    # Curved steel trigger
    ty = 0.018 + (guard_front_y - 0.018) * 0.44
    trig_profile = [
        (ty + 0.004, guard_top_z + 0.002),
        (ty + 0.010, guard_top_z + 0.002),
        (ty + 0.004, guard_bot_z + 0.018),
        (ty + 0.009, guard_bot_z + 0.010),
        (ty + 0.003, guard_bot_z + 0.008),
        (ty - 0.002, guard_bot_z + 0.018),
    ]
    parts.append(
        make_profile_x(
            f"{prefix}_Trigger",
            trig_profile,
            half_width=0.0032,
            mat=mats["ChromeSteel"],
            bevel=0.0,
        )
    )
    return parts


def make_rarity_side_strips(
    prefix: str,
    y_start: float,
    y_end: float,
    z_pos: float,
    x_offset: float,
    height: float,
    mats: dict,
    thickness: float = 0.0028,
    tilt_rad: float = 0.0,
) -> list:
    """Create sleek mirrored anodized RarityAccent trim strips along both weapon flanks."""
    parts = []
    ym = 0.5 * (y_start + y_end)
    yl = abs(y_end - y_start)
    for side, tag in ((-1.0, "L"), (1.0, "R")):
        parts.append(
            make_box(
                f"{prefix}_RarityTrim_{tag}",
                (side * x_offset, ym, z_pos),
                (thickness, yl, height),
                mats["RarityAccent"],
                bevel=0.0,
                rot_euler=(tilt_rad, 0.0, 0.0),
            )
        )
    return parts


# ---------------------------------------------------------------------------
# Scene Finalization, Join, Export & Automated Self-Audit
# ---------------------------------------------------------------------------
def reset_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def parse_glb_json(glb_path: str) -> dict:
    """Read embedded glTF 2.0 JSON chunk from a .glb binary to audit images & materials."""
    with open(glb_path, "rb") as f:
        magic, version, _total_len = struct.unpack("<III", f.read(12))
        assert magic == 0x46546C67 and version == 2, f"Invalid GLB header in {glb_path}"
        chunk_len, chunk_type = struct.unpack("<II", f.read(8))
        assert chunk_type == 0x4E4F534A, f"Missing JSON chunk in {glb_path}"
        return json.loads(f.read(chunk_len).decode("utf-8"))


def assemble_and_export(
    weapon_name: str,
    out_filename: str,
    parts: list,
    muzzle_pos: tuple,
    expected_skin_tex: str = "",
) -> dict:
    """
    Apply all modifiers cleanly on every sub-part, join into a single multi-material
    weapon mesh, create the named `MuzzlePoint` empty at barrel tip, export `.glb`,
    and re-import + inspect GLB JSON to verify tri count, materials, packed textures,
    bounding box, and hooks.
    """
    bpy.context.view_layer.update()

    # Apply modifiers on each part before joining (preserves bevels + weighted normals)
    for obj in parts:
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        for mod in list(obj.modifiers):
            bpy.ops.object.modifier_apply(modifier=mod.name)

    # Join all weapon mesh parts into one clean multi-material mesh object
    bpy.ops.object.select_all(action="DESELECT")
    for obj in parts:
        obj.select_set(True)
    master = parts[0]
    bpy.context.view_layer.objects.active = master
    if len(parts) > 1:
        bpy.ops.object.join()
    master.name = weapon_name
    master.data.name = f"{weapon_name}_Mesh"

    # Reset object transform to clean identity at origin (0, 0, 0)
    master.location = (0.0, 0.0, 0.0)
    master.rotation_euler = (0.0, 0.0, 0.0)
    master.scale = (1.0, 1.0, 1.0)

    # Create REQUIRED Empty hook `MuzzlePoint` parented to weapon mesh
    muzzle = bpy.data.objects.new("MuzzlePoint", None)
    muzzle.empty_display_type = "PLAIN_AXES"
    muzzle.empty_display_size = 0.03
    muzzle.location = muzzle_pos
    muzzle.parent = master
    bpy.context.collection.objects.link(muzzle)

    out_path = os.path.join(OUT_DIR, out_filename)
    bpy.ops.object.select_all(action="DESELECT")
    master.select_set(True)
    muzzle.select_set(True)
    bpy.context.view_layer.objects.active = master

    bpy.ops.export_scene.gltf(
        filepath=out_path,
        export_format="GLB",
        use_selection=True,
        export_yup=True,
        export_apply=True,
        export_materials="EXPORT",
        export_image_format="AUTO",
        export_animations=False,
        export_draco_mesh_compression_enable=False,
    )

    # Inspect raw GLB JSON for embedded PNG skin textures
    gltf_json = parse_glb_json(out_path)
    buffer_views = gltf_json.get("bufferViews", [])
    packed_images = []
    for img_entry in gltf_json.get("images", []):
        bv_idx = img_entry.get("bufferView")
        byte_len = buffer_views[bv_idx].get("byteLength", 0) if bv_idx is not None else 0
        packed_images.append({
            "name": img_entry.get("name", "<unnamed>"),
            "mime": img_entry.get("mimeType", ""),
            "kb": round(byte_len / 1024.0, 1),
        })

    # Automated verification via fresh round-trip re-import
    reset_scene()
    bpy.ops.import_scene.gltf(filepath=out_path)
    bpy.context.view_layer.update()

    total_tris = 0
    found_mats = set()
    muzzle_found = None
    min_co = Vector((1e9, 1e9, 1e9))
    max_co = Vector((-1e9, -1e9, -1e9))

    for obj in bpy.data.objects:
        if obj.type == "MESH":
            mesh = obj.data
            mesh.calc_loop_triangles()
            total_tris += len(mesh.loop_triangles)
            for m in mesh.materials:
                if m:
                    found_mats.add(m.name)
            for corner in obj.bound_box:
                wc = obj.matrix_world @ Vector(corner)
                min_co.x = min(min_co.x, wc.x)
                min_co.y = min(min_co.y, wc.y)
                min_co.z = min(min_co.z, wc.z)
                max_co.x = max(max_co.x, wc.x)
                max_co.y = max(max_co.y, wc.y)
                max_co.z = max(max_co.z, wc.z)
        elif obj.type == "EMPTY" and obj.name == "MuzzlePoint":
            muzzle_found = tuple(round(v, 4) for v in obj.matrix_world.translation)

    size_bytes = os.path.getsize(out_path)
    dims = max_co - min_co

    assert size_bytes > 0, f"{out_filename} is empty!"
    assert "RarityAccent" in found_mats, f"{out_filename} missing RarityAccent material! Got {found_mats}"
    assert muzzle_found is not None, f"{out_filename} missing MuzzlePoint empty!"
    assert 900 <= total_tris <= 2400, (
        f"{out_filename} tri count {total_tris} outside required [900, 2400] budget!"
    )
    if expected_skin_tex:
        img_names = [i["name"] for i in packed_images]
        assert any(expected_skin_tex in n for n in img_names), (
            f"{out_filename} missing packed skin texture '{expected_skin_tex}'! Found images: {packed_images}"
        )

    return {
        "file": out_filename,
        "path": out_path,
        "size_kb": round(size_bytes / 1024.0, 1),
        "tris": total_tris,
        "dims": (round(dims.x, 3), round(dims.y, 3), round(dims.z, 3)),
        "y_range": (round(min_co.y, 3), round(max_co.y, 3)),
        "muzzle": muzzle_found,
        "materials": sorted(found_mats),
        "images": packed_images,
    }


# ---------------------------------------------------------------------------
# 1. VANGUARD M4 — Tactical Assault Rifle (~0.82m) — "Arctic Apex"
# ---------------------------------------------------------------------------
def build_vanguard_m4() -> dict:
    reset_scene()
    mats = create_vanguard_m4_materials()
    parts = []

    barrel_z = 0.088

    # 1) Sculpted Lower Receiver + Flared Magazine Well (Arctic Apex Pearl-White Ceramic)
    lower_prof = [
        (-0.028, 0.056),
        (-0.012, 0.032),
        (0.088, 0.032),
        (0.095, 0.012),
        (0.158, 0.016),
        (0.165, 0.068),
        (-0.028, 0.072),
    ]
    parts.append(make_profile_x("M4_Lower", lower_prof, 0.0185, mats["Skin"], bevel=0.0026, bevel_segs=2))

    # 2) Contoured Upper Receiver (Arctic Apex Pearl-White Ceramic + Cobalt Chevrons)
    upper_prof = [
        (-0.034, 0.072),
        (0.165, 0.068),
        (0.165, 0.112),
        (-0.022, 0.112),
        (-0.034, 0.100),
    ]
    parts.append(
        make_profile_x(
            "M4_Upper",
            upper_prof,
            0.0195,
            mats["Skin"],
            bevel=0.0028,
            bevel_segs=2,
            taper_top_scale=0.86,
        )
    )

    # Ejection port recess + gleaming satin-silver bolt carrier (+X) + cobalt brass deflector + charging handle
    parts.append(make_box("M4_EjectRecess", (0.0178, 0.092, 0.090), (0.004, 0.068, 0.017), mats["BoreDark"], bevel=0.0))
    parts.append(make_box("M4_BoltCarrier", (0.0190, 0.092, 0.090), (0.0032, 0.056, 0.011), mats["ChromeSteel"], bevel=0.0))
    parts.append(make_box("M4_BrassDeflector", (0.0215, 0.044, 0.092), (0.009, 0.014, 0.016), mats["CobaltAnodized"], bevel=0.0015, bevel_segs=1))
    parts.append(make_box("M4_ChargeStem", (0.0, -0.042, 0.104), (0.012, 0.022, 0.008), mats["ChromeSteel"], bevel=0.0))
    parts.append(make_box("M4_ChargeLatch", (0.0, -0.050, 0.104), (0.040, 0.009, 0.010), mats["ChromeSteel"], bevel=0.0014, bevel_segs=1))
    # Fire selector & mag catch buttons
    parts.append(make_box("M4_Selector", (0.0, 0.018, 0.048), (0.042, 0.014, 0.006), mats["ChromeSteel"], bevel=0.0))

    # 3) Ventilated Free-Float Octagonal Handguard (Deep Anodized Cobalt-Navy Metallic)
    hg_sections = [
        (0.165, octagon_xz(0.0, barrel_z, 0.0215, 0.0235, 0.36)),
        (0.365, octagon_xz(0.0, barrel_z, 0.0205, 0.0225, 0.36)),
        (0.395, octagon_xz(0.0, barrel_z + 0.003, 0.0195, 0.0195, 0.38)),
    ]
    parts.append(make_loft_y("M4_Handguard", hg_sections, mats["CobaltAnodized"], bevel=0.0, sharp_angle_deg=35.0))

    # Cooling vent recesses on left & right handguard faces (4 crisp M-LOK vents per side)
    for side in (-1.0, 1.0):
        for i in range(4):
            vy = 0.195 + i * 0.046
            parts.append(
                make_box(
                    f"M4_Vent_{side}_{i}",
                    (side * 0.0204, vy, barrel_z),
                    (0.0026, 0.030, 0.009),
                    mats["BoreDark"],
                    bevel=0.0,
                )
            )

    # Full-length Top Picatinny Rail (Deep Anodized Cobalt-Navy Metallic)
    parts.append(
        make_picatinny_rail(
            "M4_TopRail",
            y_start=-0.020,
            y_end=0.382,
            z_base=0.111,
            mat=mats["CobaltAnodized"],
            width=0.021,
            height=0.0075,
            tooth_count=13,
        )
    )
    # Short lower handguard rail
    parts.append(
        make_picatinny_rail(
            "M4_BottomRail",
            y_start=0.235,
            y_end=0.345,
            z_base=barrel_z - 0.0225,
            mat=mats["CobaltAnodized"],
            width=0.018,
            height=0.006,
            tooth_count=4,
            inverted=True,
        )
    )

    # 4) Fluted Heavy Barrel + Gas Block + Brushed Satin-Silver Muzzle Brake
    barrel_prof = [
        (0.380, 0.0124),
        (0.400, 0.0108),
        (0.482, 0.0104),
        (0.485, 0.0136),  # Muzzle brake collar
        (0.503, 0.0136),
        (0.506, 0.0112),  # Baffle port 1 waist
        (0.517, 0.0136),  # Baffle rib
        (0.528, 0.0112),  # Baffle port 2 waist
        (0.539, 0.0134),  # Front muzzle crown
        (0.545, 0.0120),
        (0.545, 0.0062),  # Bore lip
        (0.518, 0.0058),  # Deep recessed dark bore
    ]
    parts.append(
        make_revolved_y(
            "M4_BarrelAndBrake",
            barrel_prof,
            mat=mats["ChromeSteel"],
            bore_mat=mats["BoreDark"],
            segments=12,
            center_xz=(0.0, barrel_z),
            bore_start_idx=9,
            flute_range=(1, 2),
            flute_count=6,
            flute_depth=0.0014,
        )
    )
    # Muzzle brake flat side-baffle shrouds & dark port cores
    parts.append(make_box("M4_BrakePort1", (0.0, 0.510, barrel_z), (0.024, 0.008, 0.011), mats["BoreDark"], bevel=0.0))
    parts.append(make_box("M4_BrakePort2", (0.0, 0.533, barrel_z), (0.024, 0.007, 0.011), mats["BoreDark"], bevel=0.0))

    # 5) Curved 30-Round Tactical Magazine (Arctic Apex ceramic body + dark carbon-slate floorplate)
    parts.extend(
        make_curved_magazine(
            "M4_Mag",
            origin_yz=(0.128, 0.022),
            width_x=0.024,
            depth_y=0.058,
            length=0.160,
            curve_angle_deg=17.0,
            steps=5,
            mat_body=mats["Skin"],
            mat_accent=mats["RarityAccent"],
            start_tilt_deg=5.0,
            mat_baseplate=mats["TacticalPolymer"],
        )
    )

    # 6) Pistol Grip + Trigger Guard + Curved Trigger (centered at 0,0,0)
    parts.extend(make_pistol_grip_and_trigger("M4", mats, grip_top_z=0.036, grip_bot_z=-0.064, guard_front_y=0.095))

    # 7) Collapsible Crane Tactical Stock + Satin-Silver Buffer Tube + Slate Rubber Buttpad
    buf_prof = [
        (-0.240, 0.0148),
        (-0.044, 0.0148),
        (-0.042, 0.0185),  # Castle nut
        (-0.028, 0.0185),
    ]
    parts.append(make_revolved_y("M4_BufferTube", buf_prof, mat=mats["ChromeSteel"], segments=12, center_xz=(0.0, barrel_z)))

    stock_prof = [
        (-0.262, -0.004),
        (-0.228, -0.004),
        (-0.188, 0.030),
        (-0.098, 0.068),
        (-0.098, 0.104),
        (-0.258, 0.112),
    ]
    parts.append(
        make_profile_x(
            "M4_StockBody",
            stock_prof,
            half_width=0.0205,
            mat=mats["Skin"],
            bevel=0.0032,
            bevel_segs=2,
            taper_top_scale=0.82,
        )
    )
    # Cheek weld side pods (anodized cobalt-navy contrast pods on pearl-white Crane stock!)
    for side in (-1.0, 1.0):
        parts.append(
            make_box(
                f"M4_CheekPod_{side}",
                (side * 0.020, -0.185, 0.092),
                (0.010, 0.132, 0.026),
                mats["CobaltAnodized"],
                bevel=0.0025,
                bevel_segs=1,
            )
        )
    # Stock adjustment lever & ribbed slate-rubber buttpad
    parts.append(make_box("M4_StockLever", (0.0, -0.175, 0.042), (0.014, 0.056, 0.018), mats["ChromeSteel"], bevel=0.0015, bevel_segs=1))
    butt_prof = [
        (-0.275, -0.005),
        (-0.260, -0.005),
        (-0.256, 0.113),
        (-0.272, 0.113),
    ]
    parts.append(make_profile_x("M4_Buttpad", butt_prof, half_width=0.0195, mat=mats["RubberGrip"], bevel=0.0025, bevel_segs=1))

    # 8) EOTech-Style Holographic Sight + Flip-Up Front Post (Cobalt-Navy Hood + Sky-Blue Lens)
    holo_base_prof = [
        (0.025, 0.118),
        (0.118, 0.118),
        (0.118, 0.136),
        (0.088, 0.140),
        (0.025, 0.134),
    ]
    parts.append(make_profile_x("M4_HoloBase", holo_base_prof, 0.0175, mats["CobaltAnodized"], bevel=0.002, bevel_segs=1))
    # Armored U-hood pillars + top roof (open view through optic glass!)
    for side in (-1.0, 1.0):
        parts.append(
            make_box(
                f"M4_HoloWall_{side}",
                (side * 0.0175, 0.056, 0.153),
                (0.0045, 0.056, 0.036),
                mats["CobaltAnodized"],
                bevel=0.001,
                bevel_segs=1,
            )
        )
    parts.append(make_box("M4_HoloRoof", (0.0, 0.056, 0.171), (0.040, 0.056, 0.005), mats["CobaltAnodized"], bevel=0.0012, bevel_segs=1))
    # Bright sky-blue holographic glass window + glowing reticle dot
    parts.append(make_box("M4_HoloGlass", (0.0, 0.062, 0.152), (0.029, 0.003, 0.028), mats["OpticGlass"], bevel=0.0, rot_euler=(math.radians(8.0), 0.0, 0.0)))
    parts.append(make_box("M4_HoloReticle", (0.0, 0.062, 0.152), (0.004, 0.004, 0.004), mats["RarityAccent"], bevel=0.0))
    # Holo side anodized accent bezels
    parts.extend(make_rarity_side_strips("M4_HoloAccent", 0.036, 0.078, 0.154, 0.0205, 0.005, mats))
    # Front backup folding sight
    parts.append(make_box("M4_FrontSightBase", (0.0, 0.362, 0.123), (0.022, 0.022, 0.010), mats["CobaltAnodized"], bevel=0.001, bevel_segs=1))

    # 9) Anodized RarityAccent Receiver & Handguard Trim Strips
    parts.extend(make_rarity_side_strips("M4_RecTrim", -0.014, 0.152, 0.104, 0.0196, 0.005, mats))
    parts.extend(make_rarity_side_strips("M4_HgTrim", 0.180, 0.360, barrel_z + 0.014, 0.0195, 0.0045, mats))

    return assemble_and_export(
        weapon_name="VanguardM4",
        out_filename="weapon_vanguard_m4.glb",
        parts=parts,
        muzzle_pos=(0.0, 0.545, barrel_z),
        expected_skin_tex="M4_ArcticApexTex",
    )


# ---------------------------------------------------------------------------
# 2. BREAKER 12G — Tactical Pump-Action Shotgun (~0.88m) — "Hazard Forge"
# ---------------------------------------------------------------------------
def build_breaker_12g() -> dict:
    reset_scene()
    mats = create_breaker_12g_materials()
    parts = []

    barrel_z = 0.092
    tube_z = 0.056

    # 1) Sculpted Heavy Tactical Shotgun Receiver (Blaze-Orange Hazard Forge Armor)
    rec_prof = [
        (-0.032, 0.052),
        (-0.010, 0.036),
        (0.185, 0.036),
        (0.198, 0.044),
        (0.198, 0.108),
        (0.175, 0.114),
        (-0.018, 0.114),
        (-0.032, 0.096),
    ]
    parts.append(
        make_profile_x(
            "SG_Receiver",
            rec_prof,
            half_width=0.0205,
            mat=mats["Skin"],
            bevel=0.0036,
            bevel_segs=2,
            taper_top_scale=0.86,
        )
    )
    # Right-side ejection port & visible machined steel bolt carrier + charging handle tab + underside loading gate
    parts.append(make_box("SG_EjectPort", (0.0192, 0.118, 0.086), (0.004, 0.072, 0.020), mats["BoreDark"], bevel=0.0))
    parts.append(make_box("SG_Bolt", (0.0204, 0.118, 0.086), (0.0032, 0.058, 0.013), mats["ChromeSteel"], bevel=0.0))
    parts.append(make_box("SG_BoltTab", (0.0265, 0.098, 0.086), (0.012, 0.008, 0.008), mats["ForgedIron"], bevel=0.0))
    parts.append(make_box("SG_LoadGate", (0.0, 0.130, 0.0365), (0.022, 0.068, 0.004), mats["ChromeSteel"], bevel=0.0))

    # Top Receiver Picatinny Rail (Forged Matte Charcoal-Iron)
    parts.append(
        make_picatinny_rail(
            "SG_TopRail",
            y_start=0.005,
            y_end=0.178,
            z_base=0.114,
            mat=mats["ForgedIron"],
            width=0.021,
            height=0.007,
            tooth_count=8,
        )
    )

    # 2) Heavy Cylindrical 12G Barrel + Standoff Breacher Choke + Wide Dark Bore (Forged Iron)
    barrel_prof = [
        (0.190, 0.0165),  # Chamber reinforcement
        (0.265, 0.0160),
        (0.272, 0.0142),  # Main heavy 12G barrel
        (0.532, 0.0138),
        (0.536, 0.0168),  # Standoff breacher choke collar
        (0.562, 0.0168),
        (0.565, 0.0150),  # Ported recess
        (0.576, 0.0150),
        (0.579, 0.0166),  # Front breacher crown
        (0.585, 0.0156),
        (0.585, 0.0102),  # 12-gauge wide hollow bore lip
        (0.550, 0.0098),  # Deep dark bore
    ]
    parts.append(
        make_revolved_y(
            "SG_Barrel",
            barrel_prof,
            mat=mats["ForgedIron"],
            bore_mat=mats["BoreDark"],
            segments=14,
            center_xz=(0.0, barrel_z),
            bore_start_idx=9,
        )
    )
    # Burnished Metallic Copper-Bronze Ventilated Heatshield over rear/mid barrel
    hs_sections = [
        (0.205, octagon_xz(0.0, barrel_z + 0.004, 0.0182, 0.0150, 0.42)),
        (0.455, octagon_xz(0.0, barrel_z + 0.004, 0.0172, 0.0145, 0.42)),
    ]
    parts.append(make_loft_y("SG_HeatShield", hs_sections, mats["CopperHeatshield"], bevel=0.0, sharp_angle_deg=35.0))
    for i in range(5):
        parts.append(
            make_box(
                f"SG_ShieldVent_{i}",
                (0.0, 0.235 + i * 0.044, barrel_z + 0.011),
                (0.036, 0.022, 0.007),
                mats["BoreDark"],
                bevel=0.0,
            )
        )

    # 3) Full-Length Under-Barrel Tubular Magazine (Forged Iron) + Copper-Bronze Clamp
    tube_prof = [
        (0.192, 0.0128),
        (0.512, 0.0128),
        (0.515, 0.0145),  # Knurled end cap
        (0.540, 0.0145),
        (0.544, 0.0125),
    ]
    parts.append(make_revolved_y("SG_TubeMag", tube_prof, mat=mats["ForgedIron"], segments=12, center_xz=(0.0, tube_z)))
    # Figure-8 tactical barrel-to-tube clamp (Burnished Copper-Bronze accent)
    parts.append(make_box("SG_BarrelClamp", (0.0, 0.482, 0.074), (0.033, 0.022, 0.056), mats["CopperHeatshield"], bevel=0.0022, bevel_segs=1))

    # 4) Ribbed Tactical Pump-Action Forend (Hazard Forge Skin) + Black Rubber Pump Ribs + Action Bars
    pump_sections = [
        (0.252, octagon_xz(0.0, tube_z - 0.002, 0.0235, 0.0245, 0.42)),  # Rear hand-stop flare
        (0.268, octagon_xz(0.0, tube_z - 0.002, 0.0215, 0.0215, 0.42)),
        (0.422, octagon_xz(0.0, tube_z - 0.002, 0.0215, 0.0215, 0.42)),
        (0.438, octagon_xz(0.0, tube_z - 0.002, 0.0240, 0.0250, 0.42)),  # Front hand-stop flare
    ]
    parts.append(make_loft_y("SG_PumpForend", pump_sections, mats["Skin"], bevel=0.0, sharp_angle_deg=35.0))
    # 6 tactile circumferential stippled black rubber pump grip ribs
    for i in range(6):
        ry = 0.282 + i * 0.025
        parts.append(
            make_box(
                f"SG_PumpRib_{i}",
                (0.0, ry, tube_z - 0.003),
                (0.0455, 0.011, 0.0435),
                mats["RubberGrip"],
                bevel=0.0,
            )
        )
    # Twin machined steel action bars connecting pump into receiver
    for side in (-1.0, 1.0):
        parts.append(make_box(f"SG_ActionBar_{side}", (side * 0.016, 0.224, tube_z + 0.004), (0.0035, 0.068, 0.007), mats["ChromeSteel"], bevel=0.0))

    # 5) Ghost-Ring Tactical Sights (Forged Iron + RarityAccent dots/post)
    parts.append(make_box("SG_RearSightBase", (0.0, 0.026, 0.125), (0.026, 0.024, 0.009), mats["ForgedIron"], bevel=0.0))
    for side in (-1.0, 1.0):
        parts.append(make_box(f"SG_RearWing_{side}", (side * 0.013, 0.026, 0.139), (0.0035, 0.016, 0.022), mats["ForgedIron"], bevel=0.0))
    bm_ring = bmesh.new()
    r_in, r_out = 0.0055, 0.0092
    y_a, y_b = 0.023, 0.029
    cz_ring = 0.139
    n_seg = 8
    in0, in1, out0, out1 = [], [], [], []
    for s in range(n_seg):
        ang = 2.0 * math.pi * s / n_seg
        ca, sa = math.cos(ang), math.sin(ang)
        in0.append(bm_ring.verts.new((r_in * ca, y_a, cz_ring + r_in * sa)))
        in1.append(bm_ring.verts.new((r_in * ca, y_b, cz_ring + r_in * sa)))
        out0.append(bm_ring.verts.new((r_out * ca, y_a, cz_ring + r_out * sa)))
        out1.append(bm_ring.verts.new((r_out * ca, y_b, cz_ring + r_out * sa)))
    for s in range(n_seg):
        s2 = (s + 1) % n_seg
        bm_ring.faces.new([out0[s], out0[s2], out1[s2], out1[s]])
        bm_ring.faces.new([in0[s2], in0[s], in1[s], in1[s2]])
        bm_ring.faces.new([out0[s2], out0[s], in0[s], in0[s2]])
        bm_ring.faces.new([out1[s], out1[s2], in1[s2], in1[s]])
    parts.append(finalize_part("SG_GhostRing", bm_ring, mats["ForgedIron"], sharp_angle_deg=40.0))
    parts.append(make_box("SG_RearSightDots", (0.0, 0.025, 0.139), (0.022, 0.004, 0.003), mats["RarityAccent"], bevel=0.0))

    # Front winged sight tower on barrel
    parts.append(make_box("SG_FrontSightBase", (0.0, 0.514, barrel_z + 0.018), (0.020, 0.024, 0.014), mats["ForgedIron"], bevel=0.0))
    for side in (-1.0, 1.0):
        parts.append(make_box(f"SG_FrontWing_{side}", (side * 0.0095, 0.514, barrel_z + 0.036), (0.003, 0.014, 0.024), mats["ForgedIron"], bevel=0.0))
    parts.append(make_box("SG_FrontPost", (0.0, 0.514, barrel_z + 0.037), (0.0035, 0.004, 0.019), mats["RarityAccent"], bevel=0.0))

    # 6) Left-Side 4-Shell Side-Saddle Carrier (-X) — Glossy Crimson & Brass 12G Shells!
    parts.append(make_box("SG_ShellPlate", (-0.0235, 0.095, 0.072), (0.005, 0.118, 0.036), mats["TacticalPolymer"], bevel=0.0))
    for i in range(4):
        sy = 0.052 + i * 0.0285
        parts.append(
            make_cylinder_between(
                f"SG_ShellHull_{i}",
                (-0.031, sy, 0.044),
                (-0.031, sy, 0.092),
                0.0092,
                0.0092,
                mats["ShellRed"],
                segments=8,
            )
        )
        parts.append(
            make_cylinder_between(
                f"SG_ShellBrass_{i}",
                (-0.031, sy, 0.092),
                (-0.031, sy, 0.104),
                0.0098,
                0.0102,
                mats["BrassAccent"],
                segments=8,
            )
        )

    # 7) Tactical Pistol Grip + Trigger + Rugged Charcoal Stock + Hazard-Orange Cheek Riser + Black Recoil Pad
    parts.extend(make_pistol_grip_and_trigger("SG", mats, grip_top_z=0.042, grip_bot_z=-0.062, guard_front_y=0.095, guard_top_z=0.040))

    stock_prof = [
        (-0.282, -0.028),
        (-0.235, -0.024),
        (-0.088, 0.026),
        (-0.026, 0.048),
        (-0.026, 0.094),
        (-0.118, 0.092),
        (-0.278, 0.090),
    ]
    parts.append(
        make_profile_x(
            "SG_Stock",
            stock_prof,
            half_width=0.019,
            mat=mats["TacticalPolymer"],
            bevel=0.0038,
            bevel_segs=2,
            taper_top_scale=0.80,
        )
    )
    # Contoured cheek riser saddle (Hazard Forge blaze-orange & caution stripes)
    cheek_prof = [
        (-0.245, 0.086),
        (-0.115, 0.086),
        (-0.125, 0.105),
        (-0.235, 0.105),
    ]
    parts.append(make_profile_x("SG_CheekRiser", cheek_prof, 0.0185, mats["Skin"], bevel=0.0028, bevel_segs=1))
    # Thick rugged stippled black rubber recoil pad
    pad_prof = [
        (-0.295, -0.030),
        (-0.280, -0.030),
        (-0.276, 0.092),
        (-0.292, 0.092),
    ]
    parts.append(make_profile_x("SG_RecoilPad", pad_prof, 0.0195, mats["RubberGrip"], bevel=0.0028, bevel_segs=1))

    # 8) Anodized RarityAccent Trim Strips
    parts.extend(make_rarity_side_strips("SG_RecTrim", -0.005, 0.175, 0.105, 0.0205, 0.005, mats))
    parts.extend(make_rarity_side_strips("SG_PumpTrim", 0.265, 0.425, tube_z + 0.016, 0.0218, 0.004, mats))

    return assemble_and_export(
        weapon_name="Breaker12G",
        out_filename="weapon_breaker_12g.glb",
        parts=parts,
        muzzle_pos=(0.0, 0.585, barrel_z),
        expected_skin_tex="Breaker_HazardForgeTex",
    )


# ---------------------------------------------------------------------------
# 3. VECTOR-9 — Compact PDW / SMG (~0.52m) — "Cyber Pulse"
# ---------------------------------------------------------------------------
def build_vector_9() -> dict:
    reset_scene()
    mats = create_vector_9_materials()
    parts = []

    barrel_z = 0.064

    # 1) Iconic Forward-Angled Super-V PDW Receiver (3K Carbon + Electric-Cyan & Magenta Cyber Pulse)
    upper_prof = [
        (-0.032, 0.066),
        (0.065, 0.066),
        (0.212, 0.062),
        (0.218, 0.104),
        (0.198, 0.118),
        (-0.020, 0.118),
        (-0.032, 0.104),
    ]
    parts.append(
        make_profile_x(
            "V9_Upper",
            upper_prof,
            half_width=0.0195,
            mat=mats["Skin"],
            bevel=0.0028,
            bevel_segs=2,
            taper_top_scale=0.88,
        )
    )

    # Signature angled Super-V lower recoil/magwell chassis (Cyber Pulse carbon weave + circuit lines)
    lower_prof = [
        (0.062, 0.044),
        (0.108, -0.046),
        (0.162, -0.042),
        (0.212, 0.038),
        (0.212, 0.078),
        (0.058, 0.078),
    ]
    parts.append(
        make_profile_x(
            "V9_SuperVLower",
            lower_prof,
            half_width=0.0205,
            mat=mats["Skin"],
            bevel=0.0030,
            bevel_segs=2,
        )
    )
    # Sculpted side armor plates on Super-V flanks (Satin Deep-Teal Anodized contrast plates!)
    sv_angle = math.atan2(0.080, 0.050)  # Matches (0.162,-0.042) -> (0.212,0.038)
    for side in (-1.0, 1.0):
        parts.append(
            make_box(
                f"V9_SidePanel_{side}",
                (side * 0.0208, 0.140, 0.020),
                (0.004, 0.086, 0.034),
                mats["Skin"],
                bevel=0.0012,
                bevel_segs=1,
                rot_euler=(sv_angle, 0.0, 0.0),
            )
        )

    # Ejection port (+X) & folding side charging handle (-X)
    parts.append(make_box("V9_EjectPort", (0.0188, 0.125, 0.094), (0.0035, 0.052, 0.016), mats["BoreDark"], bevel=0.0))
    parts.append(make_box("V9_Bolt", (0.0198, 0.125, 0.094), (0.0030, 0.042, 0.010), mats["ChromeSteel"], bevel=0.0))
    parts.append(make_box("V9_ChargeTrack", (-0.020, 0.140, 0.096), (0.004, 0.058, 0.009), mats["BoreDark"], bevel=0.0))
    parts.append(make_box("V9_ChargeHandle", (-0.031, 0.158, 0.096), (0.022, 0.011, 0.011), mats["TealAnodized"], bevel=0.0015, bevel_segs=1))

    # Full Top Picatinny Rail (Satin Deep-Teal Anodized)
    parts.append(
        make_picatinny_rail(
            "V9_TopRail",
            y_start=-0.016,
            y_end=0.198,
            z_base=0.118,
            mat=mats["TealAnodized"],
            width=0.021,
            height=0.007,
            tooth_count=10,
        )
    )

    # 2) Integrated Stepped Tactical Suppressor / Shroud (Satin Deep-Teal Anodized)
    sup_prof = [
        (0.195, 0.0165),
        (0.214, 0.0165),
        (0.218, 0.0192),  # Knurled locking collar
        (0.232, 0.0192),
        (0.235, 0.0176),  # Main cylindrical suppressor tube
        (0.320, 0.0176),
        (0.324, 0.0186),  # Front end-cap ring
        (0.332, 0.0178),
        (0.335, 0.0155),
        (0.335, 0.0072),  # 9mm suppressor bore opening
        (0.305, 0.0068),  # Deep dark recessed bore
    ]
    parts.append(
        make_revolved_y(
            "V9_Suppressor",
            sup_prof,
            mat=mats["TealAnodized"],
            bore_mat=mats["BoreDark"],
            segments=14,
            center_xz=(0.0, barrel_z),
            bore_start_idx=8,
        )
    )
    # Suppressor cooling vents
    for side in (-1.0, 1.0):
        parts.append(make_box(f"V9_SupVent_{side}", (side * 0.0172, 0.268, barrel_z), (0.003, 0.042, 0.007), mats["BoreDark"], bevel=0.0))

    # 3) Extended 36-Round Forward-Raked Stick Magazine (Cyber Pulse Carbon + Dark Baseplate)
    parts.extend(
        make_curved_magazine(
            "V9_StickMag",
            origin_yz=(0.132, -0.028),
            width_x=0.022,
            depth_y=0.036,
            length=0.178,
            curve_angle_deg=0.0,
            steps=3,
            mat_body=mats["Skin"],
            mat_accent=mats["RarityAccent"],
            start_tilt_deg=18.0,
            mat_baseplate=mats["TacticalPolymer"],
        )
    )

    # 4) Vertical Stubby Foregrip on Short Lower Rail (Matte Black Stippled Rubber + Teal Mount/Cap)
    parts.append(
        make_picatinny_rail(
            "V9_ForeRail",
            y_start=0.188,
            y_end=0.242,
            z_base=0.041,
            mat=mats["TealAnodized"],
            width=0.018,
            height=0.006,
            tooth_count=3,
            inverted=True,
        )
    )
    parts.append(make_box("V9_GripMount", (0.0, 0.214, 0.032), (0.024, 0.034, 0.014), mats["TealAnodized"], bevel=0.0015, bevel_segs=1))
    # Vertical ribbed tactical foregrip cylinder
    parts.append(
        make_cylinder_between(
            "V9_VertGrip",
            (0.0, 0.214, 0.028),
            (0.0, 0.218, -0.056),
            0.0142,
            0.0128,
            mats["RubberGrip"],
            segments=12,
        )
    )
    parts.append(
        make_cylinder_between(
            "V9_VertGripCap",
            (0.0, 0.218, -0.056),
            (0.0, 0.2185, -0.064),
            0.0138,
            0.0120,
            mats["TealAnodized"],
            segments=12,
        )
    )

    # 5) Pistol Grip + Trigger Guard + Trigger (centered at 0,0,0)
    parts.extend(
        make_pistol_grip_and_trigger(
            "V9",
            mats,
            grip_top_z=0.064,
            grip_bot_z=-0.058,
            rake_y=-0.022,
            guard_front_y=0.088,
            guard_top_z=0.066,
            guard_bot_z=0.028,
            width=0.029,
        )
    )

    # 6) Compact Open-Frame Reflex Optic (Deep-Teal Anodized Hood + Vibrant Cyan Lens)
    parts.append(make_box("V9_OpticBase", (0.0, 0.082, 0.130), (0.028, 0.056, 0.011), mats["TealAnodized"], bevel=0.0015, bevel_segs=1))
    for side in (-1.0, 1.0):
        parts.append(
            make_box(
                f"V9_OpticPillar_{side}",
                (side * 0.0135, 0.092, 0.149),
                (0.0038, 0.024, 0.029),
                mats["TealAnodized"],
                bevel=0.001,
                bevel_segs=1,
                rot_euler=(math.radians(-12.0), 0.0, 0.0),
            )
        )
    parts.append(make_box("V9_OpticTop", (0.0, 0.095, 0.163), (0.031, 0.024, 0.0042), mats["TealAnodized"], bevel=0.001, bevel_segs=1))
    parts.append(make_box("V9_OpticLens", (0.0, 0.094, 0.148), (0.023, 0.0025, 0.024), mats["OpticGlass"], bevel=0.0, rot_euler=(math.radians(-10.0), 0.0, 0.0)))
    parts.append(make_box("V9_OpticDot", (0.0, 0.094, 0.148), (0.0035, 0.0035, 0.0035), mats["RarityAccent"], bevel=0.0))
    parts.extend(make_rarity_side_strips("V9_OpticAccent", 0.062, 0.104, 0.132, 0.0148, 0.004, mats))

    # 7) Compact Side-Folding Skeletonized PDW Stock (Cyber Pulse Carbon Struts + Teal Hinge)
    parts.append(make_box("V9_HingeBlock", (0.0, -0.042, 0.088), (0.034, 0.022, 0.034), mats["TealAnodized"], bevel=0.002, bevel_segs=1))
    parts.append(
        make_cylinder_between(
            "V9_HingePin",
            (0.017, -0.044, 0.068),
            (0.017, -0.044, 0.108),
            0.0055,
            0.0055,
            mats["ChromeSteel"],
            segments=10,
        )
    )
    top_strut = [
        (-0.174, 0.092),
        (-0.045, 0.094),
        (-0.045, 0.108),
        (-0.174, 0.106),
    ]
    parts.append(make_profile_x("V9_StockTopBar", top_strut, 0.011, mats["Skin"], bevel=0.002, bevel_segs=1))
    bot_strut = [
        (-0.174, 0.016),
        (-0.045, 0.072),
        (-0.045, 0.084),
        (-0.174, 0.030),
    ]
    parts.append(make_profile_x("V9_StockBotBar", bot_strut, 0.0095, mats["Skin"], bevel=0.0018, bevel_segs=1))
    butt_prof = [
        (-0.185, 0.006),
        (-0.171, 0.006),
        (-0.168, 0.109),
        (-0.183, 0.109),
    ]
    parts.append(make_profile_x("V9_Buttpad", butt_prof, 0.017, mats["RubberGrip"], bevel=0.0024, bevel_segs=1))

    # 8) Anodized RarityAccent Trim Strips (cleanly parallel to Vector Super-V lines!)
    parts.extend(make_rarity_side_strips("V9_UpperTrim", 0.005, 0.188, 0.111, 0.0195, 0.0045, mats))
    parts.extend(make_rarity_side_strips("V9_AngleTrim", 0.116, 0.194, 0.018, 0.0228, 0.005, mats, tilt_rad=sv_angle))

    return assemble_and_export(
        weapon_name="Vector9",
        out_filename="weapon_vector_9.glb",
        parts=parts,
        muzzle_pos=(0.0, 0.335, barrel_z),
        expected_skin_tex="Vector_CyberPulseTex",
    )


# ---------------------------------------------------------------------------
# 4. LONGBOW .308 — Marksman Bolt-Action Sniper Rifle (~1.18m) — "Shoreline Viper"
# ---------------------------------------------------------------------------
def build_longbow_308() -> dict:
    reset_scene()
    mats = create_longbow_308_materials()
    parts = []

    barrel_z = 0.088
    scope_z = 0.164

    # 1) Precision Chassis Lower + Ventilated Free-Float Forend (Shoreline Viper Topographic Camo)
    chassis_prof = [
        (-0.038, 0.056),
        (-0.015, 0.032),
        (0.195, 0.028),
        (0.220, 0.044),
        (0.220, 0.076),
        (-0.038, 0.078),
    ]
    parts.append(make_profile_x("SN_Chassis", chassis_prof, 0.020, mats["Skin"], bevel=0.0028, bevel_segs=2))

    forend_sections = [
        (0.215, octagon_xz(0.0, barrel_z - 0.010, 0.0215, 0.0265, 0.38)),
        (0.420, octagon_xz(0.0, barrel_z - 0.009, 0.0205, 0.0245, 0.38)),
        (0.448, octagon_xz(0.0, barrel_z - 0.014, 0.0190, 0.0180, 0.38)),
    ]
    parts.append(make_loft_y("SN_Forend", forend_sections, mats["Skin"], bevel=0.0, sharp_angle_deg=35.0))
    # Dark cooling slots along sniper forend flanks
    for side in (-1.0, 1.0):
        for i in range(4):
            parts.append(
                make_box(
                    f"SN_ForeVent_{side}_{i}",
                    (side * 0.0208, 0.245 + i * 0.048, barrel_z - 0.009),
                    (0.0025, 0.032, 0.009),
                    mats["BoreDark"],
                    bevel=0.0,
                )
            )

    # 2) Heavy Precision Bolt-Action Receiver + Brushed Champagne-Gold Titanium Bolt & Swept Handle!
    rec_sections = [
        (-0.025, octagon_xz(0.0, barrel_z, 0.0190, 0.0215, 0.44)),
        (0.218, octagon_xz(0.0, barrel_z, 0.0190, 0.0215, 0.44)),
    ]
    parts.append(make_loft_y("SN_Action", rec_sections, mats["ActionSteel"], bevel=0.0, sharp_angle_deg=35.0))
    # Scalloped ejection port + gleaming champagne-gold titanium bolt body (+X)
    parts.append(make_box("SN_EjectPort", (0.0176, 0.112, barrel_z + 0.002), (0.004, 0.074, 0.016), mats["BoreDark"], bevel=0.0))
    parts.append(make_cylinder_between("SN_BoltBody", (0.0108, 0.025, barrel_z + 0.001), (0.0108, 0.155, barrel_z + 0.001), 0.0095, 0.0095, mats["ChampagneGold"], segments=8))
    # Bolt shroud at rear of action
    parts.append(make_cylinder_between("SN_BoltShroud", (0.0, -0.044, barrel_z), (0.0, -0.022, barrel_z), 0.0125, 0.0145, mats["ActionSteel"], segments=8))
    # Swept tactical bolt handle (+X) + oversized champagne-gold tactical bolt knob!
    parts.append(
        make_cylinder_between(
            "SN_BoltStem",
            (0.014, 0.032, barrel_z - 0.002),
            (0.056, 0.016, barrel_z - 0.024),
            0.0046,
            0.0042,
            mats["ChampagneGold"],
            segments=6,
        )
    )
    parts.append(
        make_cylinder_between(
            "SN_BoltKnob",
            (0.052, 0.018, barrel_z - 0.022),
            (0.072, 0.010, barrel_z - 0.034),
            0.0075,
            0.0108,
            mats["ChampagneGold"],
            segments=8,
        )
    )

    # Top Receiver Picatinny Rail (for elevated scope mount)
    parts.append(
        make_picatinny_rail(
            "SN_TopRail",
            y_start=-0.018,
            y_end=0.220,
            z_base=barrel_z + 0.0215,
            mat=mats["ActionSteel"],
            width=0.021,
            height=0.0075,
            tooth_count=8,
        )
    )

    # 3) Long Fluted Precision Barrel + Heavy 3-Chamber Tank Muzzle Brake (Brushed Champagne-Gold Titanium!)
    barrel_prof = [
        (0.420, 0.0142),
        (0.448, 0.0138),  # Start fluted zone
        (0.600, 0.0126),
        (0.752, 0.0114),  # End fluted zone
        (0.785, 0.0114),  # Thread shoulder
        (0.858, 0.0146),
        (0.860, 0.0135),
        (0.860, 0.0062),  # .308 bore lip
        (0.822, 0.0058),  # Deep dark recessed bore
    ]
    parts.append(
        make_revolved_y(
            "SN_FlutedBarrel",
            barrel_prof,
            mat=mats["ChampagneGold"],
            bore_mat=mats["BoreDark"],
            segments=12,
            center_xz=(0.0, barrel_z),
            bore_start_idx=6,
            flute_range=(1, 3),
            flute_count=6,
            flute_depth=0.0018,
        )
    )
    # Chamfered rectangular precision tank muzzle brake outer body (Champagne-Gold Titanium) + 3 dark side baffle ports
    parts.append(make_box("SN_TankBrake", (0.0, 0.824, barrel_z), (0.032, 0.068, 0.024), mats["ChampagneGold"], bevel=0.0026, bevel_segs=1))
    for i in range(3):
        parts.append(make_box(f"SN_BrakeBaffle_{i}", (0.0, 0.804 + i * 0.020, barrel_z), (0.034, 0.010, 0.014), mats["BoreDark"], bevel=0.0))

    # 4) Flush 5-Round Detachable Box Magazine (Shoreline Viper Camo + Forest Anodized Baseplate)
    parts.append(make_box("SN_Mag5rd", (0.0, 0.145, -0.010), (0.024, 0.078, 0.088), mats["Skin"], bevel=0.0022, bevel_segs=1))
    parts.append(make_box("SN_MagBase", (0.0, 0.145, -0.056), (0.028, 0.084, 0.010), mats["ActionSteel"], bevel=0.0))

    # 5) Elevated Anti-Glare Matte Obsidian Sniper Scope + Champagne-Gold Scope Rings + Emerald Coated Glass
    parts.append(make_box("SN_MountBase", (0.0, 0.108, barrel_z + 0.033), (0.025, 0.132, 0.010), mats["ActionSteel"], bevel=0.0))
    for r_y in (0.056, 0.160):
        parts.append(make_box(f"SN_RingPillar_{r_y}", (0.0, r_y, 0.138), (0.024, 0.020, 0.024), mats["ActionSteel"], bevel=0.0))
        parts.append(
            make_revolved_y(
                f"SN_ScopeRing_{r_y}",
                [(r_y - 0.011, 0.0225), (r_y + 0.011, 0.0225)],
                mat=mats["ChampagneGold"],
                segments=10,
                center_xz=(0.0, scope_z),
            )
        )

    # Magnified Scope Tube (Anti-Glare Matte Obsidian)
    scope_prof = [
        (-0.054, 0.0168),  # Rear recessed ocular lip
        (-0.054, 0.0225),  # Eyepiece rim
        (0.018, 0.0222),
        (0.021, 0.0245),   # Magnification zoom ring
        (0.036, 0.0245),
        (0.040, 0.0172),   # Main 34mm scope tube
        (0.205, 0.0172),
        (0.248, 0.0285),   # Flared objective cone
        (0.352, 0.0290),   # Objective bell & sunshade
        (0.352, 0.0242),   # Recessed front objective lip
        (0.328, 0.0238),   # Inner sunshade recess
    ]
    parts.append(
        make_revolved_y(
            "SN_ScopeTube",
            scope_prof,
            mat=mats["ObsidianScope"],
            bore_mat=mats["BoreDark"],
            segments=12,
            center_xz=(0.0, scope_z),
            bore_start_idx=8,
        )
    )
    # Rich emerald-green coated objective & eyepiece lenses!
    parts.append(
        make_cylinder_between(
            "SN_FrontLens",
            (0.0, 0.338, scope_z),
            (0.0, 0.343, scope_z),
            0.0238,
            0.0238,
            mats["OpticGlass"],
            segments=10,
        )
    )
    parts.append(
        make_cylinder_between(
            "SN_RearLens",
            (0.0, -0.051, scope_z),
            (0.0, -0.047, scope_z),
            0.0168,
            0.0168,
            mats["OpticGlass"],
            segments=8,
        )
    )
    # Turrets: Matte Obsidian housing + RarityAccent turret ring
    parts.append(make_box("SN_TurretSaddle", (0.0, 0.110, scope_z), (0.042, 0.034, 0.042), mats["ObsidianScope"], bevel=0.0))
    parts.append(make_cylinder_between("SN_ElevTurret", (0.0, 0.110, scope_z + 0.018), (0.0, 0.110, scope_z + 0.040), 0.0125, 0.0115, mats["ObsidianScope"], segments=8))
    parts.append(make_cylinder_between("SN_ElevAccent", (0.0, 0.110, scope_z + 0.023), (0.0, 0.110, scope_z + 0.027), 0.0132, 0.0132, mats["RarityAccent"], segments=8))
    parts.append(make_cylinder_between("SN_WindTurret", (0.018, 0.110, scope_z), (0.038, 0.110, scope_z), 0.0110, 0.0102, mats["ObsidianScope"], segments=8))
    parts.append(make_cylinder_between("SN_ParaTurret", (-0.018, 0.110, scope_z), (-0.036, 0.110, scope_z), 0.0108, 0.0100, mats["ObsidianScope"], segments=8))

    # 6) Precision Vertical Pistol Grip + Trigger Guard + Match Trigger (centered at 0,0,0)
    parts.extend(
        make_pistol_grip_and_trigger(
            "SN",
            mats,
            grip_top_z=0.038,
            grip_bot_z=-0.064,
            rake_y=-0.016,
            guard_front_y=0.095,
            guard_top_z=0.034,
        )
    )

    # 7) Skeletonized Precision Chassis Buttstock + Adjustable Cheek Rest (Shoreline Viper Camo) + Gold Posts
    top_beam = [
        (-0.306, 0.056),
        (-0.036, 0.056),
        (-0.036, 0.088),
        (-0.306, 0.088),
    ]
    parts.append(make_profile_x("SN_StockTop", top_beam, 0.0165, mats["Skin"], bevel=0.0025, bevel_segs=2))
    bot_strut = [
        (-0.306, -0.020),
        (-0.205, -0.014),
        (-0.036, 0.044),
        (-0.036, 0.062),
        (-0.205, 0.008),
        (-0.306, 0.004),
    ]
    parts.append(make_profile_x("SN_StockBagRider", bot_strut, 0.0145, mats["Skin"], bevel=0.0))
    parts.append(make_box("SN_StockRearSpine", (-0.0, -0.292, 0.036), (0.032, 0.028, 0.112), mats["Skin"], bevel=0.0))
    # Elevated Adjustable Cheek Rest Saddle + Twin Champagne-Gold Support Posts
    cheek_prof = [
        (-0.262, 0.104),
        (-0.115, 0.104),
        (-0.125, 0.124),
        (-0.252, 0.124),
    ]
    parts.append(make_profile_x("SN_CheekRest", cheek_prof, 0.0195, mats["Skin"], bevel=0.0032, bevel_segs=2))
    for py in (-0.232, -0.145):
        parts.append(make_cylinder_between(f"SN_CheekPost_{py}", (0.0, py, 0.084), (0.0, py, 0.108), 0.0052, 0.0052, mats["ChampagneGold"], segments=6))
    # Thick rubber recoil buttpad
    pad_prof = [
        (-0.320, -0.024),
        (-0.304, -0.024),
        (-0.304, 0.094),
        (-0.320, 0.094),
    ]
    parts.append(make_profile_x("SN_Buttpad", pad_prof, 0.019, mats["RubberGrip"], bevel=0.0025, bevel_segs=1))

    # 8) Folded Tactical Bipod Underneath Forend
    parts.append(make_box("SN_BipodCradle", (0.0, 0.415, 0.044), (0.036, 0.032, 0.018), mats["ActionSteel"], bevel=0.0))
    for side, tag in ((-1.0, "L"), (1.0, "R")):
        parts.append(
            make_cylinder_between(
                f"SN_BipodLeg_{tag}",
                (side * 0.018, 0.418, 0.040),
                (side * 0.027, 0.588, 0.044),
                0.0072,
                0.0064,
                mats["ActionSteel"],
                segments=8,
            )
        )
        parts.append(
            make_cylinder_between(
                f"SN_BipodFoot_{tag}",
                (side * 0.027, 0.586, 0.044),
                (side * 0.028, 0.606, 0.044),
                0.0095,
                0.0085,
                mats["RubberGrip"],
                segments=8,
            )
        )

    # 9) Anodized RarityAccent Trim Strips
    parts.extend(make_rarity_side_strips("SN_ChassisTrim", 0.010, 0.195, 0.068, 0.0210, 0.005, mats))
    parts.extend(make_rarity_side_strips("SN_ForendTrim", 0.235, 0.415, barrel_z + 0.008, 0.0212, 0.0045, mats))

    return assemble_and_export(
        weapon_name="Longbow308",
        out_filename="weapon_longbow_308.glb",
        parts=parts,
        muzzle_pos=(0.0, 0.860, barrel_z),
        expected_skin_tex="Longbow_ShorelineViperTex",
    )


# ---------------------------------------------------------------------------
# 5. NOVA GL-40 — 6-Chamber Revolving Ordnance Launcher (~0.78m) — "Hypernova Prism"
# ---------------------------------------------------------------------------
def build_nova_gl40() -> dict:
    reset_scene()
    mats = create_nova_gl40_materials()
    parts = []

    barrel_z = 0.095
    drum_z = 0.056  # Top chamber sits at z = 0.056 + 0.039 = 0.095 -> aligned cleanly with 40mm barrel!

    # 1) Rear Ordnance Receiver (Hypernova Prism Cosmic-Indigo & Amethyst Hex Armor) + Anodized Gold Front Yoke
    rear_prof = [
        (-0.035, 0.042),
        (0.068, 0.036),
        (0.072, 0.128),
        (-0.025, 0.128),
        (-0.035, 0.106),
    ]
    parts.append(make_profile_x("GL_RearRec", rear_prof, 0.024, mats["Skin"], bevel=0.0032, bevel_segs=2))

    # Front drum yoke collar housing (Anodized Gold trim framing the silver drum!)
    front_yoke = [
        (0.212, 0.040),
        (0.248, 0.046),
        (0.252, 0.132),
        (0.212, 0.132),
    ]
    parts.append(make_profile_x("GL_FrontYoke", front_yoke, 0.027, mats["AnodizedGold"], bevel=0.0030, bevel_segs=2))

    # Heavy top bridge connecting rear receiver over revolving drum to front barrel shroud
    parts.append(make_box("GL_TopBridge", (0.0, 0.142, 0.131), (0.038, 0.175, 0.016), mats["CosmicSteel"], bevel=0.0))
    # Rear recoil shield plate + anodized gold front ratchet hub & central drum axle
    parts.append(make_cylinder_between("GL_RearDrumPlate", (0.0, 0.066, drum_z), (0.0, 0.078, drum_z), 0.066, 0.066, mats["CosmicSteel"], segments=12))
    parts.append(make_cylinder_between("GL_FrontDrumHub", (0.0, 0.202, drum_z), (0.0, 0.218, drum_z), 0.024, 0.021, mats["AnodizedGold"], segments=10))
    parts.append(make_cylinder_between("GL_DrumAxle", (0.0, 0.058, drum_z), (0.0, 0.228, drum_z), 0.011, 0.011, mats["AnodizedGold"], segments=8))

    # 2) Sculpted 6-Chamber Deeply Fluted Revolving Drum Cylinder (Satin Pearl-Titanium Silver!)
    bm_drum = bmesh.new()
    y_back, y_front = 0.079, 0.203
    n_pts = 36  # 6 lobes * 6 points per lobe -> unmistakable deep-fluted 6-chamber drum!
    r_lobe = 0.070
    r_flute = 0.047
    ring_b, ring_f = [], []
    for i in range(n_pts):
        ang = math.pi * 0.5 + 2.0 * math.pi * i / n_pts
        lobe_wave = 0.5 + 0.5 * math.cos(6.0 * (ang - math.pi * 0.5))
        r = r_flute + (r_lobe - r_flute) * (lobe_wave ** 0.65)
        x = r * math.cos(ang)
        z = drum_z + r * math.sin(ang)
        ring_b.append(bm_drum.verts.new((x, y_back, z)))
        ring_f.append(bm_drum.verts.new((x, y_front, z)))
    for i in range(n_pts):
        j = (i + 1) % n_pts
        bm_drum.faces.new([ring_b[i], ring_b[j], ring_f[j], ring_f[i]])
    bm_drum.faces.new(list(reversed(ring_b)))
    bm_drum.faces.new(ring_f)
    parts.append(finalize_part("GL_RevolvingDrum", bm_drum, mats["PearlTitanium"], sharp_angle_deg=42.0))

    # 5 visibly exposed chamber grenade heads (gold casing + glowing violet NovaPlasma warhead popping against silver drum!)
    chamber_orbit = 0.042
    for c in range(6):
        ang = math.pi * 0.5 + c * (math.pi / 3.0)
        cx = chamber_orbit * math.cos(ang)
        cz = drum_z + chamber_orbit * math.sin(ang)
        if c != 0:
            parts.append(
                make_cylinder_between(
                    f"GL_GrenadeBrass_{c}",
                    (cx, 0.202, cz),
                    (cx, 0.212, cz),
                    0.0175,
                    0.0170,
                    mats["BrassAccent"],
                    segments=8,
                )
            )
            parts.append(
                make_cylinder_between(
                    f"GL_GrenadeTip_{c}",
                    (cx, 0.212, cz),
                    (cx, 0.224, cz),
                    0.0145,
                    0.0065,
                    mats["NovaPlasma"],
                    segments=8,
                )
            )

    # 3) Wide-Bore 40mm Launcher Barrel + Heavy Muzzle Crown + Recessed Wide Dark Bore
    barrel_prof = [
        (0.240, 0.0295),
        (0.324, 0.0325),  # Reinforcing collar
        (0.344, 0.0285),
        (0.458, 0.0285),
        (0.462, 0.0328),  # Heavy muzzle crown collar
        (0.506, 0.0328),
        (0.515, 0.0305),
        (0.515, 0.0215),  # Wide 40mm hollow bore lip
        (0.455, 0.0205),  # Deep wide dark bore
    ]
    parts.append(
        make_revolved_y(
            "GL_WideBarrel",
            barrel_prof,
            mat=mats["CosmicSteel"],
            bore_mat=mats["BoreDark"],
            segments=14,
            center_xz=(0.0, barrel_z),
            bore_start_idx=6,
        )
    )

    # Ventilated Armored Barrel Shroud (Hypernova Prism Cosmic-Indigo Hex Armor) + Top Rail
    shroud_sections = [
        (0.242, octagon_xz(0.0, barrel_z + 0.008, 0.035, 0.033, 0.36)),
        (0.432, octagon_xz(0.0, barrel_z + 0.008, 0.033, 0.031, 0.36)),
    ]
    parts.append(make_loft_y("GL_BarrelShroud", shroud_sections, mats["Skin"], bevel=0.0, sharp_angle_deg=35.0))

    parts.append(
        make_picatinny_rail(
            "GL_TopRail",
            y_start=0.075,
            y_end=0.415,
            z_base=0.139,
            mat=mats["CosmicSteel"],
            width=0.022,
            height=0.0075,
            tooth_count=10,
        )
    )

    # 4) Glowing Purple Energy Capacitor Vents (Signature Mana-Powered Nova GL-40 Detail!)
    for side, tag in ((-1.0, "L"), (1.0, "R")):
        parts.append(
            make_box(
                f"GL_CapPod_{tag}",
                (side * 0.0365, 0.335, barrel_z + 0.006),
                (0.011, 0.148, 0.032),
                mats["Skin"],
                bevel=0.0,
            )
        )
        for v in range(3):
            vy = 0.285 + v * 0.050
            parts.append(
                make_box(
                    f"GL_PlasmaVent_{tag}_{v}",
                    (side * 0.0422, vy, barrel_z + 0.006),
                    (0.0032, 0.034, 0.016),
                    mats["NovaPlasma"],
                    bevel=0.0,
                )
            )
        parts.append(
            make_box(
                f"GL_RearCapGlow_{tag}",
                (side * 0.0252, 0.022, 0.102),
                (0.0032, 0.056, 0.011),
                mats["NovaPlasma"],
                bevel=0.0,
            )
        )

    # 5) Caged Ordnance Reflex Sight on Top Bridge (Cosmic Steel Hood + Vivid Violet-Magenta Lens)
    parts.append(make_box("GL_SightBase", (0.0, 0.145, 0.152), (0.032, 0.072, 0.011), mats["CosmicSteel"], bevel=0.0))
    for side in (-1.0, 1.0):
        parts.append(make_box(f"GL_SightWall_{side}", (side * 0.016, 0.148, 0.174), (0.0045, 0.046, 0.036), mats["CosmicSteel"], bevel=0.0))
    parts.append(make_box("GL_SightRoof", (0.0, 0.148, 0.192), (0.037, 0.046, 0.005), mats["CosmicSteel"], bevel=0.0))
    parts.append(make_box("GL_SightLens", (0.0, 0.150, 0.173), (0.026, 0.003, 0.028), mats["OpticGlass"], bevel=0.0, rot_euler=(math.radians(8.0), 0.0, 0.0)))
    parts.append(make_box("GL_SightReticle", (0.0, 0.150, 0.173), (0.012, 0.004, 0.003), mats["RarityAccent"], bevel=0.0))
    parts.extend(make_rarity_side_strips("GL_SightAccent", 0.128, 0.168, 0.174, 0.0190, 0.005, mats))

    # 6) Heavy Under-Barrel Foregrip + Pistol Grip
    parts.append(make_box("GL_LowerRailBar", (0.0, 0.335, 0.057), (0.026, 0.135, 0.014), mats["TacticalPolymer"], bevel=0.0))
    foregrip_prof = [
        (0.322, -0.052),
        (0.354, -0.052),
        (0.362, 0.010),
        (0.376, 0.022),
        (0.376, 0.052),
        (0.312, 0.052),
    ]
    parts.append(make_profile_x("GL_HeavyForegrip", foregrip_prof, 0.0175, mats["RubberGrip"], bevel=0.0038, bevel_segs=2))

    parts.extend(
        make_pistol_grip_and_trigger(
            "GL",
            mats,
            grip_top_z=0.046,
            grip_bot_z=-0.064,
            rake_y=-0.024,
            guard_front_y=0.072,
            guard_top_z=0.042,
            guard_bot_z=0.002,
            width=0.033,
        )
    )

    # 7) Heavy Buffered Tactical Stock (Hypernova Prism Armor + Pearl-Titanium Tube + Obsidian Recoil Pad)
    parts.append(make_cylinder_between("GL_StockTube", (0.0, -0.230, 0.088), (0.0, -0.030, 0.088), 0.0175, 0.0190, mats["PearlTitanium"], segments=10))
    stock_prof = [
        (-0.248, -0.018),
        (-0.205, -0.018),
        (-0.155, 0.038),
        (-0.085, 0.068),
        (-0.085, 0.114),
        (-0.248, 0.116),
    ]
    parts.append(
        make_profile_x(
            "GL_HeavyStock",
            stock_prof,
            half_width=0.0235,
            mat=mats["Skin"],
            bevel=0.0036,
            bevel_segs=2,
            taper_top_scale=0.84,
        )
    )
    parts.append(make_box("GL_StockCheek", (0.0, -0.175, 0.112), (0.042, 0.115, 0.018), mats["Skin"], bevel=0.0))
    pad_prof = [
        (-0.265, -0.020),
        (-0.246, -0.020),
        (-0.244, 0.118),
        (-0.262, 0.118),
    ]
    parts.append(make_profile_x("GL_RecoilPad", pad_prof, 0.023, mats["RubberGrip"], bevel=0.0030, bevel_segs=1))

    # 8) Anodized RarityAccent Trim Strips (distinct from purple NovaPlasma capacitor vents)
    parts.extend(make_rarity_side_strips("GL_BridgeTrim", 0.080, 0.215, 0.132, 0.0198, 0.005, mats))
    parts.extend(make_rarity_side_strips("GL_ShroudTrim", 0.258, 0.415, barrel_z + 0.030, 0.0332, 0.005, mats))

    return assemble_and_export(
        weapon_name="NovaGL40",
        out_filename="weapon_nova_gl40.glb",
        parts=parts,
        muzzle_pos=(0.0, 0.515, barrel_z),
        expected_skin_tex="Nova_HypernovaPrismTex",
    )


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------
def main() -> None:
    builders = [
        build_vanguard_m4,
        build_breaker_12g,
        build_vector_9,
        build_longbow_308,
        build_nova_gl40,
    ]
    results = []
    for fn in builders:
        info = fn()
        results.append(info)

    print("\n" + "=" * 94)
    print("WORKSPACE ROYALE — BESPOKE WEAPON SKINS EXPORT & VERIFICATION SUMMARY")
    print("=" * 94)
    total_kb = 0.0
    for r in results:
        total_kb += r["size_kb"]
        img_str = ", ".join(f"{im['name']}({im['mime']},{im['kb']}KB)" for im in r["images"])
        print(
            f"  {r['file']:<24} | {r['size_kb']:6.1f} KB | {r['tris']:4d} tris | "
            f"Dims(W×L×H): {r['dims'][0]:.2f}×{r['dims'][1]:.2f}×{r['dims'][2]:.2f}m | "
            f"Muzzle: {r['muzzle']}"
        )
        print(f"    Materials ({len(r['materials'])}): {', '.join(r['materials'])}")
        print(f"    Packed Images ({len(r['images'])}): {img_str}")
    print("-" * 94)
    total_mb = total_kb / 1024.0
    print(f"  TOTAL WEAPONS: {len(results)}/5 verified | Combined size: {total_kb:.1f} KB ({total_mb:.2f} MB)")
    assert total_mb <= 3.0, f"Combined weapon GLB size {total_mb:.2f} MB exceeds 3.0 MB budget!"
    print("=" * 94 + "\n")


if __name__ == "__main__":
    main()

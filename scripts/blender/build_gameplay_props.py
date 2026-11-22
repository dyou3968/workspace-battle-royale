#!/usr/bin/env python3
"""
Workspace Royale — Bespoke Gameplay Props Builder (Blender 5.3.0)
=================================================================
Generates two crisp Google-themed interactive gameplay `.glb` props into
`public/assets/map/` and renders a 2-panel BLENDER_EEVEE studio QA sheet:

  1. prop_gbike_rideable.glb  — Standalone rideable Google GBike cruiser facing +Y
                                (Three.js -Z) with exact articulated child pivots:
                                  - GBike_Frame          (0,  0.00, 0.000)
                                  - GBike_WheelRear      (0, -0.52, 0.340)
                                  - GBike_CrankPedals    (0, -0.06, 0.300)
                                  - GBike_FrontAssembly  (0, +0.36, 0.740)
                                      └─ GBike_WheelFront (local 0, +0.20, -0.40 -> world 0, +0.56, 0.340)
                                  - GBike_SeatMount      (0, -0.20, 0.950) [Empty]
  2. prop_techstop_kiosk.glb  — Iconic Google TechStop Weapon Upgrade Center
                                (~2.50m W x 1.15m D x 2.45m H, facing +Y / Three.js -Z,
                                grounded at Z = 0.000) with glowing TechStop_HoloRing,
                                floating upgrade chevron, dual diagnostic monitors,
                                warm-oak slatted curved counter, and dual-sided
                                TECHSTOP overhead arch canopy.

Coordinate Mapping (`export_yup=True`, zero Draco compression):
  - Blender +X -> Three.js +X (Right / East)
  - Blender +Y -> Three.js -Z (Forward / North, matching yaw = 0)
  - Blender +Z -> Three.js +Y (Up)

Usage:
    blender --background --python scripts/blender/build_gameplay_props.py
"""

import json
import math
import os
import struct
import sys
import tempfile
import time
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Euler, Matrix, Vector

# ---------------------------------------------------------------------------
# Paths & Google Palette
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
OUT_DIR = PROJECT_ROOT / "public" / "assets" / "map"
OUT_DIR.mkdir(parents=True, exist_ok=True)

QA_PREVIEW_PATH = Path(
    "/Users/davidyou/.gemini/antigravity/brain/a9682dfa-7d5f-428c-afd4-e62e35b1964e/previews/qa_gbike_techstop.png"
)

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


def b2t(v):
    """Convert Blender (x, y, z) -> Three.js Y-up (x, z, -y)."""
    return (float(v[0]), float(v[2]), float(-v[1]))


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0


# ---------------------------------------------------------------------------
# Procedural Texture & Vector SDF Typography Generators (Pure NumPy)
# ---------------------------------------------------------------------------
def make_packed_image(name, rgb_topdown):
    """Pack a top-down (H, W, 3|4) float32 sRGB array into a Blender Image."""
    arr = np.clip(rgb_topdown, 0.0, 1.0).astype(np.float32)
    h, w, c = arr.shape
    has_alpha = c == 4
    if not has_alpha:
        rgba = np.ones((h, w, 4), dtype=np.float32)
        rgba[:, :, :3] = arr
    else:
        rgba = arr
    # Blender stores image pixels bottom-to-top
    flipped = np.ascontiguousarray(rgba[::-1], dtype=np.float32)
    img = bpy.data.images.new(name=name, width=w, height=h, alpha=has_alpha)
    img.colorspace_settings.name = "sRGB"
    img.pixels.foreach_set(flipped.ravel())
    img.pack()
    return img


def _sd_segment(px, py, x0, y0, x1, y1):
    vx, vy = x1 - x0, y1 - y0
    wx, wy = px - x0, py - y0
    l2 = vx * vx + vy * vy + 1e-9
    t = np.clip((wx * vx + wy * vy) / l2, 0.0, 1.0)
    dx = wx - vx * t
    dy = wy - vy * t
    return np.hypot(dx, dy)


def _sd_arc(px, py, cx, cy, r, a0, a1):
    """Exact 2D distance to circular arc centered at (cx, cy), radius r, angle [a0, a1]."""
    dx = px - cx
    dy = py - cy
    ang = np.arctan2(dy, dx)
    span = a1 - a0
    rel = (ang - a0) % (2.0 * math.pi)
    on_arc = rel <= span
    d_rad = np.abs(np.hypot(dx, dy) - r)
    p0x, p0y = cx + r * math.cos(a0), cy + r * math.sin(a0)
    p1x, p1y = cx + r * math.cos(a1), cy + r * math.sin(a1)
    d_end = np.minimum(np.hypot(px - p0x, py - p0y), np.hypot(px - p1x, py - p1y))
    return np.where(on_arc, d_rad, d_end)


def _sd_round_box(px, py, cx, cy, hw, hh, rad):
    qx = np.abs(px - cx) - (hw - rad)
    qy = np.abs(py - cy) - (hh - rad)
    out = np.hypot(np.maximum(qx, 0.0), np.maximum(qy, 0.0))
    inn = np.minimum(np.maximum(qx, qy), 0.0)
    return out + inn - rad


def _glyph_sdf(ch, px, py, cx, cy, h):
    """Geometric sans-serif SDF for crisp anti-aliased TECHSTOP / GBIKE signage."""
    r = h * 0.46
    hw = h * 0.36
    inf = np.full_like(px, 1e6, dtype=np.float32)

    if ch == "T":
        d1 = _sd_segment(px, py, cx - hw * 1.05, cy - r, cx + hw * 1.05, cy - r)
        d2 = _sd_segment(px, py, cx, cy - r, cx, cy + r)
        return np.minimum(d1, d2)
    if ch == "E":
        xl, xr = cx - hw * 0.85, cx + hw * 0.88
        d1 = _sd_segment(px, py, xl, cy - r, xl, cy + r)
        d2 = _sd_segment(px, py, xl, cy - r, xr, cy - r)
        d3 = _sd_segment(px, py, xl, cy - 0.02 * h, xr - hw * 0.22, cy - 0.02 * h)
        d4 = _sd_segment(px, py, xl, cy + r, xr, cy + r)
        return np.minimum(np.minimum(d1, d2), np.minimum(d3, d4))
    if ch == "C":
        return _sd_arc(px, py, cx + hw * 0.14, cy, r, 0.23 * math.pi, 1.77 * math.pi)
    if ch == "H":
        xl, xr = cx - hw * 0.92, cx + hw * 0.92
        d1 = _sd_segment(px, py, xl, cy - r, xl, cy + r)
        d2 = _sd_segment(px, py, xr, cy - r, xr, cy + r)
        d3 = _sd_segment(px, py, xl, cy, xr, cy)
        return np.minimum(np.minimum(d1, d2), d3)
    if ch == "S":
        rs = r * 0.50
        d1 = _sd_arc(px, py, cx, cy - rs, rs, 0.50 * math.pi, 1.86 * math.pi)
        d2 = _sd_arc(px, py, cx, cy + rs, rs, 1.50 * math.pi, 2.86 * math.pi)
        return np.minimum(d1, d2)
    if ch == "O":
        return np.abs(np.hypot(px - cx, py - cy) - r)
    if ch == "P":
        xl = cx - hw * 0.86
        xm = cx + hw * 0.18
        rb = r * 0.53
        ymid = cy - r + 2.0 * rb
        d1 = _sd_segment(px, py, xl, cy - r, xl, cy + r)
        d2 = _sd_segment(px, py, xl, cy - r, xm, cy - r)
        d3 = _sd_segment(px, py, xl, ymid, xm, ymid)
        d4 = _sd_arc(px, py, xm, cy - r + rb, rb, -0.50 * math.pi, 0.50 * math.pi)
        return np.minimum(np.minimum(d1, d2), np.minimum(d3, d4))
    if ch == "G":
        cgx = cx + hw * 0.08
        d1 = _sd_arc(px, py, cgx, cy, r, 0.04 * math.pi, 1.77 * math.pi)
        d2 = _sd_segment(px, py, cgx + 0.02 * r, cy + 0.04 * r, cgx + r, cy + 0.04 * r)
        return np.minimum(d1, d2)
    if ch == "B":
        xl = cx - hw * 0.86
        xm = cx + hw * 0.16
        rb1 = r * 0.48
        rb2 = r * 0.52
        d1 = _sd_segment(px, py, xl, cy - r, xl, cy + r)
        d2 = _sd_segment(px, py, xl, cy - r, xm, cy - r)
        d3 = _sd_segment(px, py, xl, cy - r + 2 * rb1, xm, cy - r + 2 * rb1)
        d4 = _sd_segment(px, py, xl, cy + r, xm, cy + r)
        d5 = _sd_arc(px, py, xm, cy - r + rb1, rb1, -0.5 * math.pi, 0.5 * math.pi)
        d6 = _sd_arc(px, py, xm + hw * 0.06, cy + r - rb2, rb2, -0.5 * math.pi, 0.5 * math.pi)
        return np.minimum(np.minimum(np.minimum(d1, d2), np.minimum(d3, d4)), np.minimum(d5, d6))
    if ch == "I":
        return _sd_segment(px, py, cx, cy - r, cx, cy + r)
    if ch == "K":
        xl = cx - hw * 0.82
        xr = cx + hw * 0.88
        d1 = _sd_segment(px, py, xl, cy - r, xl, cy + r)
        d2 = _sd_segment(px, py, xl + hw * 0.05, cy + 0.04 * h, xr, cy - r)
        d3 = _sd_segment(px, py, cx - hw * 0.12, cy - 0.06 * h, xr, cy + r)
        return np.minimum(np.minimum(d1, d2), d3)
    return inf


def gen_techstop_sign_tex(name="Tex_TechStopSign", w=512, h=128, quad_aspect=6.175):
    """
    Crisp 512x128 Google TechStop canopy banner texture with SDF geometric typography.
    Uses exact world-quad aspect compensation (`quad_aspect = sign_w / sign_h`) so the
    circular Google 'G' emblem badge and TECHSTOP letter proportions render 100% undistorted!
    """
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    tex_aspect = float(w) / float(h)
    ax = float(quad_aspect) / tex_aspect  # >1 means quad is wider than 4:1 texture

    # World-proportional coordinate space (same vertical scale as pixel height `h`)
    # X spans [0, h * quad_aspect], Y spans [0, h]
    W_u = h * float(quad_aspect)
    ux = xx * ax
    uy = yy

    # Rich authentic Google Blue (#1A73E8 -> #1558B0) architectural backlit lightbox backdrop
    grad_y = uy / float(h)
    grad_x = np.abs((ux / W_u) - 0.5) * 2.0
    bg_r = 0.075 + 0.025 * (1.0 - grad_y) - 0.012 * grad_x
    bg_g = 0.365 + 0.065 * (1.0 - grad_y) - 0.028 * grad_x
    bg_b = 0.835 + 0.065 * (1.0 - grad_y) - 0.038 * grad_x
    img = np.stack([bg_r, bg_g, bg_b], axis=-1)

    # Sleek rounded lightbox recessed border & crisp aluminum-white hairline inset
    border_d = _sd_round_box(ux, uy, W_u * 0.5, h * 0.5, W_u * 0.486, h * 0.435, 12.0)
    outer_mask = np.clip((border_d + 1.5) / 2.2, 0.0, 1.0)
    img = img * (1.0 - 0.48 * outer_mask[:, :, None])
    rim_line = np.clip(1.0 - np.abs(border_d + 2.5) / 1.6, 0.0, 1.0)
    img = img * (1.0 - 0.42 * rim_line[:, :, None]) + np.array([0.82, 0.91, 1.0]) * (0.42 * rim_line[:, :, None])

    # Left PERFECT-CIRCLE white emblem badge with 4-color Google 'G' ring!
    badge_cx, badge_cy = 78.0, h * 0.485
    d_badge = np.hypot(ux - badge_cx, uy - badge_cy) - 36.0
    a_badge = np.clip(0.5 - d_badge / 1.6, 0.0, 1.0)[:, :, None]
    img = img * (1.0 - a_badge) + np.array([0.985, 0.99, 1.0]) * a_badge

    ring_r = 21.5
    ring_sw = 7.2
    quads = [
        (hex_to_srgb(G_BLUE), -0.14 * math.pi, 0.40 * math.pi),
        (hex_to_srgb(G_GREEN), 0.44 * math.pi, 0.95 * math.pi),
        (hex_to_srgb(G_YELLOW), 0.99 * math.pi, 1.38 * math.pi),
        (hex_to_srgb(G_RED), 1.42 * math.pi, 1.84 * math.pi),
    ]
    for qcol, qa0, qa1 in quads:
        dq = _sd_arc(ux, uy, badge_cx, badge_cy, ring_r, qa0, qa1) - ring_sw * 0.5
        aq = np.clip(0.5 - dq / 1.4, 0.0, 1.0)[:, :, None]
        img = img * (1.0 - aq) + np.array(qcol) * aq
    d_gbar = _sd_segment(ux, uy, badge_cx + 1.0, badge_cy + 1.0, badge_cx + ring_r + 1.5, badge_cy + 1.0) - ring_sw * 0.46
    a_gbar = np.clip(0.5 - d_gbar / 1.4, 0.0, 1.0)[:, :, None]
    img = img * (1.0 - a_gbar) + np.array(hex_to_srgb(G_BLUE)) * a_gbar

    # Bold high-contrast pure-white "TECHSTOP" SDF lettering (true Google Sans proportions!)
    word = "TECHSTOP"
    glyph_h = 64.0
    stroke_hw = 6.2
    advances = [62.0, 62.0, 68.0, 68.0, 64.0, 62.0, 74.0, 64.0]
    total_w = sum(advances)
    start_x = 148.0 + (W_u - 184.0 - total_w) * 0.5
    text_cy = h * 0.465

    d_text = np.full((h, w), 1e6, dtype=np.float32)
    d_shadow = np.full((h, w), 1e6, dtype=np.float32)
    cur_x = start_x
    for ch, adv in zip(word, advances):
        cx = cur_x + adv * 0.5
        d_text = np.minimum(d_text, _glyph_sdf(ch, ux, uy, cx, text_cy, glyph_h))
        d_shadow = np.minimum(d_shadow, _glyph_sdf(ch, ux, uy, cx + 2.8, text_cy + 3.0, glyph_h))
        cur_x += adv

    a_shad = np.clip(0.5 + (stroke_hw + 0.8 - d_shadow) / 2.6, 0.0, 1.0)[:, :, None] * 0.36
    img = img * (1.0 - a_shad) + np.array([0.02, 0.08, 0.22]) * a_shad

    a_txt = np.clip(0.5 + (stroke_hw - d_text) / 1.6, 0.0, 1.0)[:, :, None]
    img = img * (1.0 - a_txt) + np.array([0.995, 0.998, 1.0]) * a_txt

    # Crisp 4-color Google underline bar beneath TECHSTOP
    bar_y0, bar_y1 = int(h * 0.815), int(h * 0.885)
    bx0_px = int(round(146.0 / ax))
    bx1_px = int(round((W_u - 42.0) / ax))
    seg_w = (bx1_px - bx0_px) // 4
    g_cols = [hex_to_srgb(G_BLUE), hex_to_srgb(G_RED), hex_to_srgb(G_YELLOW), hex_to_srgb(G_GREEN)]
    img[bar_y0 - 2:bar_y1 + 2, bx0_px - 2:bx1_px + 2] = (0.97, 0.985, 1.0)
    for i, col in enumerate(g_cols):
        sx0 = bx0_px + i * seg_w
        sx1 = bx1_px if i == 3 else (sx0 + seg_w)
        img[bar_y0:bar_y1, sx0:sx1] = col

    return make_packed_image(name, img)


def gen_techstop_diag_tex(name="Tex_TechStopDiag", w=256, h=256):
    """
    256x256 dual-panel diagnostic display atlas:
      - Top half (v in [0.5, 1.0] -> top-down rows 0..127): Left Monitor (Weapon Tier & 4-Color Bar Telemetry)
      - Bottom half (v in [0.0, 0.5] -> top-down rows 128..255): Right Monitor (Power Waveform & System Diagnostics)
    """
    img = np.zeros((h, w, 3), dtype=np.float32)
    img[:, :] = (0.045, 0.072, 0.125)  # Deep sleek dark-slate UI canvas

    g_cols = [
        hex_to_srgb(G_BLUE),
        hex_to_srgb(G_RED),
        hex_to_srgb(G_YELLOW),
        hex_to_srgb(G_GREEN),
    ]
    cyan = (0.22, 0.78, 0.98)

    for panel_idx, y_off in enumerate((0, 128)):
        # Subtle grid lines
        for gx in range(16, w, 24):
            img[y_off + 20:y_off + 120, gx:gx + 1] = (0.09, 0.14, 0.22)
        for gy in range(24, 120, 20):
            img[y_off + gy:y_off + gy + 1, 10:w - 10] = (0.09, 0.14, 0.22)

        # Top status header strip + 4-color Google dots
        img[y_off + 6:y_off + 18, 8:w - 8] = (0.08, 0.13, 0.22)
        for i, col in enumerate(g_cols):
            img[y_off + 9:y_off + 15, 14 + i * 14:22 + i * 14] = col
        # Status pill on right
        img[y_off + 9:y_off + 15, w - 58:w - 14] = hex_to_srgb(G_GREEN)

        if panel_idx == 0:
            # LEFT MONITOR: 4-color Google vertical diagnostic bars + weapon schematic box + circular ring
            bar_heights = [64, 44, 78, 86, 56, 72]
            for bi, bh in enumerate(bar_heights):
                bx0 = 16 + bi * 22
                bx1 = bx0 + 14
                col = g_cols[bi % 4]
                img[y_off + 114 - bh:y_off + 114, bx0:bx1] = col
                img[y_off + 114 - bh:y_off + 114 - bh + 4, bx0:bx1] = (0.92, 0.96, 1.0)
            # Right circular upgrade dial
            yy, xx = np.mgrid[y_off:y_off + 128, 0:w].astype(np.float32)
            dcx, dcy = 198.0, y_off + 68.0
            d_ring = np.abs(np.hypot(xx - dcx, yy - dcy) - 30.0)
            a_ring = np.clip(1.0 - d_ring / 3.5, 0.0, 1.0)
            img[y_off:y_off + 128] = (
                img[y_off:y_off + 128] * (1.0 - a_ring[:, :, None])
                + np.array(cyan) * a_ring[:, :, None]
            )
            # Upward chevron inside circular dial
            d_c1 = _sd_segment(xx, yy, dcx - 12.0, dcy + 5.0, dcx, dcy - 9.0)
            d_c2 = _sd_segment(xx, yy, dcx, dcy - 9.0, dcx + 12.0, dcy + 5.0)
            a_ch = np.clip(1.0 - np.minimum(d_c1, d_c2) / 3.0, 0.0, 1.0)
            img[y_off:y_off + 128] = (
                img[y_off:y_off + 128] * (1.0 - a_ch[:, :, None])
                + np.array([0.96, 0.99, 1.0]) * a_ch[:, :, None]
            )
        else:
            # RIGHT MONITOR: Glowing telemetry waveform + 4 horizontal progress bars
            xs = np.arange(14, w - 14)
            for xi in xs:
                t = (xi - 14) / float(w - 28)
                wy1 = int(y_off + 46 + math.sin(t * 16.0) * 14.0 + math.cos(t * 7.0) * 6.0)
                wy2 = int(y_off + 50 + math.sin(t * 11.0 + 1.2) * 10.0)
                img[wy1 - 2:wy1 + 2, xi:xi + 1] = cyan
                img[wy2 - 1:wy2 + 2, xi:xi + 1] = hex_to_srgb(G_GREEN)

            # 4 horizontal Google-colored metric bars at bottom
            fills = [0.88, 0.72, 0.94, 0.64]
            for bi, fl in enumerate(fills):
                by0 = y_off + 74 + bi * 11
                img[by0:by0 + 6, 16:w - 16] = (0.12, 0.17, 0.26)
                bw = int((w - 32) * fl)
                img[by0:by0 + 6, 16:16 + bw] = g_cols[bi]

    return make_packed_image(name, img)


def gen_light_oak_tex(name="Tex_LightOak", size=128):
    """Warm modern California light-oak slat wood grain texture."""
    rng = np.random.default_rng(4242)
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    # Smooth low-frequency wood grain variation along vertical slats
    base = rng.random((16, 8), dtype=np.float32)
    y0 = (yy / size * 16).astype(np.int32) % 16
    x0 = (xx / size * 8).astype(np.int32) % 8
    y1 = (y0 + 1) % 16
    x1 = (x0 + 1) % 8
    fy = (yy / size * 16) - np.floor(yy / size * 16)
    fx = (xx / size * 8) - np.floor(xx / size * 8)
    n = (base[y0, x0] * (1 - fx) + base[y0, x1] * fx) * (1 - fy) + (
        base[y1, x0] * (1 - fx) + base[y1, x1] * fx
    ) * fy
    grain = np.sin(xx * 0.42 + n * 5.0) * 0.055 + (n - 0.5) * 0.08
    v = 0.90 + grain
    rgb = np.stack([v * 0.84, v * 0.67, v * 0.45], axis=-1)
    return make_packed_image(name, rgb)


def gen_gbike_badge_tex(name="Tex_GBikeBadge", w=128, h=64):
    """Crisp mini front-basket Google GBike plaque texture."""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    img = np.ones((h, w, 3), dtype=np.float32) * np.array([0.96, 0.975, 0.995])

    # Top & bottom 4-color Google stripe trim
    g_cols = [hex_to_srgb(G_BLUE), hex_to_srgb(G_RED), hex_to_srgb(G_YELLOW), hex_to_srgb(G_GREEN)]
    seg = w // 4
    for i, col in enumerate(g_cols):
        img[0:10, i * seg:(i + 1) * seg] = col
        img[h - 10:h, i * seg:(i + 1) * seg] = col

    # Crisp dark-slate "GBIKE" SDF lettering
    word = "GBIKE"
    adv = 21.0
    start_x = (w - adv * len(word)) * 0.5
    d_txt = np.full((h, w), 1e6, dtype=np.float32)
    for i, ch in enumerate(word):
        cx = start_x + (i + 0.5) * adv
        d_txt = np.minimum(d_txt, _glyph_sdf(ch, xx, yy, cx, h * 0.5, 24.0))
    a_txt = np.clip(0.5 + (2.8 - d_txt) / 1.1, 0.0, 1.0)[:, :, None]
    img = img * (1.0 - a_txt) + np.array([0.12, 0.16, 0.22]) * a_txt

    return make_packed_image(name, img)


# ---------------------------------------------------------------------------
# PBR Material & Multi-Material BMesh Helpers
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
    emission_tex=False,
    double_sided=False,
):
    """Create a Blender 5.3.0 Principled BSDF material cleanly for glTF 2.0 export."""
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

    tex_node = None
    if tex_img is not None:
        tex_node = nodes.new("ShaderNodeTexImage")
        tex_node.image = tex_img
        tex_node.location = (-460, 180)
        links.new(tex_node.outputs["Color"], bsdf.inputs["Base Color"])

    if emission_tex and tex_node is not None and emission_strength > 0.0:
        links.new(tex_node.outputs["Color"], bsdf.inputs["Emission Color"])
        bsdf.inputs["Emission Strength"].default_value = emission_strength
    elif emission is not None and emission_strength > 0.0:
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


def _assign_new_faces(bm, prev_faces, mat_idx, smooth=False):
    """Assign material & shading strictly to faces created after `prev_faces` snapshot (bevel/triangulate safe!)."""
    for f in bm.faces:
        if f not in prev_faces:
            f.material_index = mat_idx
            f.smooth = smooth


def bm_add_box(bm, center, size, rot_euler=(0.0, 0.0, 0.0), bevel=0.0, bevel_segs=1, mat_idx=0, smooth=False):
    prev = set(bm.faces)
    sx, sy, sz = size
    mat_t = Matrix.Translation(Vector(center))
    mat_r = Euler(rot_euler, "XYZ").to_matrix().to_4x4()
    mat_s = Matrix.Diagonal((sx, sy, sz, 1.0))
    res = bmesh.ops.create_cube(bm, size=1.0, matrix=mat_t @ mat_r @ mat_s)
    verts = res["verts"]
    if bevel > 0.0:
        vset = set(verts)
        edges = [e for e in bm.edges if e.verts[0] in vset and e.verts[1] in vset]
        bmesh.ops.bevel(
            bm,
            geom=edges,
            offset=bevel,
            offset_type="OFFSET",
            segments=bevel_segs,
            profile=0.5,
            affect="EDGES",
            clamp_overlap=True,
        )
    _assign_new_faces(bm, prev, mat_idx, smooth=smooth)
    return verts


def bm_add_prism_between(bm, p0, p1, r0, r1, segs=10, cap=True, mat_idx=0, smooth=True):
    prev = set(bm.faces)
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
        ca, sa = math.cos(ang), math.sin(ang)
        d = x_dir * ca + y_dir * sa
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
    _assign_new_faces(bm, prev, mat_idx, smooth=smooth)
    return ring0 + ring1


def bm_add_spline_tube(bm, points, radii, segs=10, cap_ends=True, oval_ratio=1.0, mat_idx=0, smooth=True):
    prev = set(bm.faces)
    pts = [Vector(p) for p in points]
    n = len(pts)
    if n < 2:
        return []
    tangents = []
    for i in range(n):
        if i == 0:
            t = pts[1] - pts[0]
        elif i == n - 1:
            t = pts[-1] - pts[-2]
        else:
            t = pts[i + 1] - pts[i - 1]
        tangents.append(t.normalized() if t.length > 1e-6 else Vector((0, 0, 1)))

    t0 = tangents[0]
    ref = Vector((0, 0, 1)) if abs(t0.z) < 0.9 else Vector((1, 0, 0))
    n_vec = ref.cross(t0).normalized()
    b_vec = t0.cross(n_vec).normalized()

    rings = []
    for i in range(n):
        ti = tangents[i]
        if i > 0:
            rot_q = tangents[i - 1].rotation_difference(ti)
            n_vec = (rot_q @ n_vec).normalized()
            n_vec = (n_vec - ti * n_vec.dot(ti)).normalized()
            b_vec = ti.cross(n_vec).normalized()
        ri = radii[i]
        ring = []
        for s in range(segs):
            ang = 2.0 * math.pi * s / segs
            ca = math.cos(ang) * ri
            sa = math.sin(ang) * ri * oval_ratio
            ring.append(bm.verts.new(pts[i] + n_vec * ca + b_vec * sa))
        rings.append(ring)

    for i in range(n - 1):
        rA, rB = rings[i], rings[i + 1]
        for s in range(segs):
            ns = (s + 1) % segs
            bm.faces.new((rA[s], rA[ns], rB[ns], rB[s]))
    if cap_ends:
        bm.faces.new(list(reversed(rings[0])))
        bm.faces.new(rings[-1])
    _assign_new_faces(bm, prev, mat_idx, smooth=smooth)
    return [v for r in rings for v in r]


def bm_add_curved_fender(bm, axle_center, radius, a0, a1, arc_segs=14, half_w=0.036, arch_drop=0.014, thick=0.006, mat_idx=0):
    """Build a genuine arched C-profile bicycle mudguard fender around an X-axis wheel."""
    prev = set(bm.faces)
    cx, cy, cz = axle_center
    # Cross-section profile points in (x, radial_offset) forming a smooth outer+inner C-arch
    prof_u = (-1.0, -0.58, 0.0, 0.58, 1.0)
    outer_rings = []
    inner_rings = []
    for k in range(arc_segs + 1):
        fa = a0 + (a1 - a0) * (k / float(arc_segs))
        ca, sa = math.cos(fa), math.sin(fa)
        o_ring, i_ring = [], []
        for u in prof_u:
            x = cx + u * half_w
            r_out = radius - arch_drop * (u * u)
            r_in = r_out - thick
            o_ring.append(bm.verts.new((x, cy + ca * r_out, cz + sa * r_out)))
            i_ring.append(bm.verts.new((x, cy + ca * r_in, cz + sa * r_in)))
        outer_rings.append(o_ring)
        inner_rings.append(i_ring)

    m = len(prof_u)
    for k in range(arc_segs):
        o0, o1 = outer_rings[k], outer_rings[k + 1]
        i0, i1 = inner_rings[k], inner_rings[k + 1]
        for j in range(m - 1):
            bm.faces.new((o0[j], o0[j + 1], o1[j + 1], o1[j]))
            bm.faces.new((i0[j + 1], i0[j], i1[j], i1[j + 1]))
        # Side thickness lips
        bm.faces.new((o0[0], o1[0], i1[0], i0[0]))
        bm.faces.new((o1[-1], o0[-1], i0[-1], i1[-1]))
    # End caps
    for j in range(m - 1):
        bm.faces.new((outer_rings[0][j + 1], outer_rings[0][j], inner_rings[0][j], inner_rings[0][j + 1]))
        bm.faces.new((outer_rings[-1][j], outer_rings[-1][j + 1], inner_rings[-1][j + 1], inner_rings[-1][j]))
    _assign_new_faces(bm, prev, mat_idx, smooth=True)


def bm_add_sphere(bm, center, rx, ry=None, rz=None, u_segs=14, v_segs=10, mat_idx=0, smooth=True):
    prev = set(bm.faces)
    ry = rx if ry is None else ry
    rz = rx if rz is None else rz
    mat = Matrix.Translation(Vector(center)) @ Matrix.Diagonal((rx, ry, rz, 1.0))
    res = bmesh.ops.create_uvsphere(bm, u_segments=u_segs, v_segments=v_segs, radius=1.0, matrix=mat)
    _assign_new_faces(bm, prev, mat_idx, smooth=smooth)
    return res["verts"]


def bm_add_torus(bm, center, major_r, minor_r, rot_euler=(0, 0, 0), major_segs=24, minor_segs=10, mat_idx=0, smooth=True):
    prev = set(bm.faces)
    mat_t = Matrix.Translation(Vector(center))
    mat_r = Euler(rot_euler, "XYZ").to_matrix().to_4x4()
    xform = mat_t @ mat_r
    rings = []
    for i in range(major_segs):
        theta = 2.0 * math.pi * i / major_segs
        ct, st = math.cos(theta), math.sin(theta)
        ring = []
        for j in range(minor_segs):
            phi = 2.0 * math.pi * j / minor_segs
            cp, sp = math.cos(phi), math.sin(phi)
            r = major_r + minor_r * cp
            p = Vector((r * ct, r * st, minor_r * sp))
            ring.append(bm.verts.new(xform @ p))
        rings.append(ring)
    for i in range(major_segs):
        ni = (i + 1) % major_segs
        for j in range(minor_segs):
            nj = (j + 1) % minor_segs
            bm.faces.new((rings[i][j], rings[ni][j], rings[ni][nj], rings[i][nj]))
    _assign_new_faces(bm, prev, mat_idx, smooth=smooth)


def bm_add_rounded_rect_prism(bm, cx, cy, w, d, r_corner, z0, z1, corner_segs=5, bevel_top=0.0, mat_idx=0, smooth=False):
    """Extrude a rounded-rectangle (stadium-corner) prism cleanly between z0 and z1."""
    prev = set(bm.faces)
    hw, hd = w * 0.5, d * 0.5
    rc = min(r_corner, hw - 1e-3, hd - 1e-3)
    pts = []
    corners = [
        (cx + hw - rc, cy + hd - rc, 0.0, 0.5 * math.pi),
        (cx - hw + rc, cy + hd - rc, 0.5 * math.pi, math.pi),
        (cx - hw + rc, cy - hd + rc, math.pi, 1.5 * math.pi),
        (cx + hw - rc, cy - hd + rc, 1.5 * math.pi, 2.0 * math.pi),
    ]
    for ccx, ccy, a0, a1 in corners:
        for k in range(corner_segs + 1):
            a = a0 + (a1 - a0) * (k / float(corner_segs))
            pts.append((ccx + rc * math.cos(a), ccy + rc * math.sin(a)))

    n = len(pts)
    if bevel_top > 1e-4:
        # 3 rings: bottom, upper-shoulder, inset top bevel
        bot = [bm.verts.new((x, y, z0)) for x, y in pts]
        shd = [bm.verts.new((x, y, z1 - bevel_top)) for x, y in pts]
        top = []
        for x, y in pts:
            dx, dy = x - cx, y - cy
            # Inset slightly toward center along corner radial/axis
            sx = max(0.0, abs(dx) - bevel_top) * (1.0 if dx >= 0 else -1.0)
            sy = max(0.0, abs(dy) - bevel_top) * (1.0 if dy >= 0 else -1.0)
            top.append(bm.verts.new((cx + sx, cy + sy, z1)))
        for i in range(n):
            ni = (i + 1) % n
            bm.faces.new((bot[i], bot[ni], shd[ni], shd[i]))
            bm.faces.new((shd[i], shd[ni], top[ni], top[i]))
        f_bot = bm.faces.new(list(reversed(bot)))
        f_top = bm.faces.new(top)
        bmesh.ops.triangulate(bm, faces=[f_bot, f_top], quad_method="BEAUTY", ngon_method="EAR_CLIP")
    else:
        bot = [bm.verts.new((x, y, z0)) for x, y in pts]
        top = [bm.verts.new((x, y, z1)) for x, y in pts]
        for i in range(n):
            ni = (i + 1) % n
            bm.faces.new((bot[i], bot[ni], top[ni], top[i]))
        f_bot = bm.faces.new(list(reversed(bot)))
        f_top = bm.faces.new(top)
        bmesh.ops.triangulate(bm, faces=[f_bot, f_top], quad_method="BEAUTY", ngon_method="EAR_CLIP")

    _assign_new_faces(bm, prev, mat_idx, smooth=smooth)


def bm_add_textured_quad(bm, center, viewer_right, up_vec, width, height, uv_rect=(0.0, 0.0, 1.0, 1.0), mat_idx=0):
    """
    Create a single upright, non-mirrored textured quad whose outward normal is
    `viewer_right.cross(up_vec)` (pointing straight toward a viewer looking at the quad!).
    """
    prev = len(bm.faces)
    c = Vector(center)
    r = Vector(viewer_right).normalized() * (width * 0.5)
    u = Vector(up_vec).normalized() * (height * 0.5)
    v_bl = bm.verts.new(c - r - u)
    v_br = bm.verts.new(c + r - u)
    v_tr = bm.verts.new(c + r + u)
    v_tl = bm.verts.new(c - r + u)
    face = bm.faces.new((v_bl, v_br, v_tr, v_tl))
    face.material_index = mat_idx
    face.smooth = False
    uv_layer = bm.loops.layers.uv.verify()
    u0, v0, u1, v1 = uv_rect
    uvs = [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]
    for loop, uv in zip(face.loops, uvs):
        loop[uv_layer].uv = uv
    return face


def apply_box_uv_missing(bm, scale=0.8, skip_mat_indices=()):
    """Apply clean triplanar UVs to all faces except those with explicit custom UVs."""
    uv_layer = bm.loops.layers.uv.verify()
    skip_set = set(skip_mat_indices)
    for f in bm.faces:
        if f.material_index in skip_set:
            continue
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


def finalize_multimat_mesh(
    name,
    bm,
    materials,
    location=(0.0, 0.0, 0.0),
    parent=None,
    uv_scale=0.8,
    skip_uv_mats=(),
    recalc_normals=True,
):
    """Finalize a multi-material BMesh into an Object with exact origin & parent."""
    if recalc_normals:
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    apply_box_uv_missing(bm, scale=uv_scale, skip_mat_indices=skip_uv_mats)

    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()

    for mat in materials:
        mesh.materials.append(mat)

    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    if parent is not None:
        obj.parent = parent
    obj.location = Vector(location)
    obj.rotation_euler = Euler((0.0, 0.0, 0.0), "XYZ")
    return obj


# ===========================================================================
# ASSET 1: STANDALONE RIDEABLE GOOGLE GBIKE (prop_gbike_rideable.glb)
# ===========================================================================
def build_gbike_rideable():
    reset_scene()

    tex_badge = gen_gbike_badge_tex("Tex_GBikeBadge", 128, 64)

    # Exact required material names & PBR parameters (runtime-tintable FramePrimary & FenderAccent!)
    mat_frame = make_pbr_mat(
        "GBike_FramePrimary",
        base_color=hex_to_linear(G_BLUE),
        metallic=0.32,
        roughness=0.26,
    )
    mat_fender = make_pbr_mat(
        "GBike_FenderAccent",
        base_color=hex_to_linear(G_YELLOW),
        metallic=0.26,
        roughness=0.28,
    )
    mat_chrome = make_pbr_mat(
        "GBike_Chrome",
        base_color=hex_to_linear("#E8EEF6"),
        metallic=0.94,
        roughness=0.14,
    )
    mat_tire = make_pbr_mat(
        "GBike_TireRubber",
        base_color=hex_to_linear("#1D2128"),
        metallic=0.0,
        roughness=0.86,
    )
    mat_saddle = make_pbr_mat(
        "GBike_SaddleGrip",
        base_color=hex_to_linear("#242830"),
        metallic=0.0,
        roughness=0.62,
    )
    mat_basket = make_pbr_mat(
        "GBike_BasketWire",
        base_color=hex_to_linear("#2F3844"),
        metallic=0.74,
        roughness=0.34,
    )
    mat_reflector = make_pbr_mat(
        "GBike_TailReflector",
        base_color=hex_to_linear(G_RED),
        metallic=0.08,
        roughness=0.18,
        emission=hex_to_linear(G_RED),
        emission_strength=1.5,
    )
    mat_badge = make_pbr_mat(
        "GBike_GoogleEmblem",
        base_color=(1.0, 1.0, 1.0, 1.0),
        metallic=0.12,
        roughness=0.30,
        tex_img=tex_badge,
    )

    # Exact required geometry constants (facing +Y forward -> Three.js -Z!)
    wheel_r = 0.310
    tire_r = 0.030
    axle_z = wheel_r + tire_r  # 0.340m -> bottom tire vertex hits EXACT Z = 0.000!
    wy_front = +0.560
    wy_rear = -0.520

    bb_pos = Vector((0.0, -0.060, 0.300))
    head_origin = Vector((0.0, +0.360, 0.740))
    seat_mount_pos = Vector((0.0, -0.200, 0.950))

    # Frame junction anchors (exact alignment with head_origin & seat_mount)
    seat_cl = Vector((0.0, -0.175, 0.735))
    head_bot = Vector((0.0, +0.382, 0.678))
    head_top = Vector((0.0, +0.338, 0.802))

    # -----------------------------------------------------------------------
    # 1. GBike_Frame (origin at world 0, 0, 0)
    # -----------------------------------------------------------------------
    frame_mats = [mat_frame, mat_fender, mat_chrome, mat_saddle, mat_basket, mat_reflector]
    MI_FR, MI_FN, MI_CH, MI_SD, MI_BK, MI_RF = 0, 1, 2, 3, 4, 5
    bm_frame = bmesh.new()

    # Bottom bracket shell
    bm_add_prism_between(bm_frame, (-0.042, bb_pos.y, bb_pos.z), (+0.042, bb_pos.y, bb_pos.z), 0.025, 0.025, segs=12, mat_idx=MI_FR)
    # Seat tube & chrome seatpost clamp collar
    bm_add_prism_between(bm_frame, bb_pos, seat_cl, 0.020, 0.019, segs=10, mat_idx=MI_FR)
    bm_add_prism_between(bm_frame, seat_cl + Vector((0, 0.004, -0.012)), seat_cl + Vector((0, -0.004, +0.014)), 0.023, 0.023, segs=10, mat_idx=MI_CH)

    # Head tube & upper/lower chrome headset bearing cups
    bm_add_prism_between(bm_frame, head_bot, head_top, 0.023, 0.023, segs=12, mat_idx=MI_FR)
    head_axis = (head_top - head_bot).normalized()
    bm_add_prism_between(bm_frame, head_bot - head_axis * 0.012, head_bot + head_axis * 0.006, 0.026, 0.025, segs=12, mat_idx=MI_CH)
    bm_add_prism_between(bm_frame, head_top - head_axis * 0.005, head_top + head_axis * 0.014, 0.025, 0.026, segs=12, mat_idx=MI_CH)

    # Sweeping Google GBike Cruiser Downtube (smooth 7-pt spline, zero V-kink)
    downtube_pts = [
        head_bot + head_axis * 0.018,
        (0.0, +0.305, 0.565),
        (0.0, +0.220, 0.455),
        (0.0, +0.125, 0.370),
        (0.0, +0.030, 0.322),
        bb_pos,
    ]
    bm_add_spline_tube(bm_frame, downtube_pts, [0.021] * len(downtube_pts), segs=10, mat_idx=MI_FR)

    # Sweeping Step-Through Cruiser Top Tube (graceful pure curve characteristic of Google GBikes!)
    toptube_pts = [
        head_top - head_axis * 0.024,
        (0.0, +0.245, 0.728),
        (0.0, +0.135, 0.642),
        (0.0, +0.015, 0.592),
        (0.0, -0.095, 0.600),
        (0.0, -0.158, 0.668),
    ]
    bm_add_spline_tube(bm_frame, toptube_pts, [0.0175] * len(toptube_pts), segs=9, mat_idx=MI_FR)

    # Rear triangle (chainstays, seatstays, dropouts, brake bridge)
    for sgn in (-1.0, 1.0):
        rear_ax = Vector((sgn * 0.056, wy_rear, axle_z))
        # Curved chainstay
        cs_pts = [
            (sgn * 0.036, bb_pos.y, bb_pos.z),
            (sgn * 0.052, -0.22, 0.308),
            (sgn * 0.056, -0.38, 0.324),
            rear_ax,
        ]
        bm_add_spline_tube(bm_frame, cs_pts, [0.013, 0.012, 0.011, 0.0095], segs=8, mat_idx=MI_FR)
        # Graceful slightly arched seatstay
        ss_pts = [
            (sgn * 0.017, -0.168, 0.700),
            (sgn * 0.044, -0.295, 0.610),
            (sgn * 0.054, -0.415, 0.480),
            rear_ax,
        ]
        bm_add_spline_tube(bm_frame, ss_pts, [0.0115, 0.011, 0.010, 0.009], segs=8, mat_idx=MI_FR)
        # Rear dropout lug
        bm_add_box(bm_frame, (sgn * 0.056, wy_rear, axle_z), (0.010, 0.040, 0.036), bevel=0.003, mat_idx=MI_FR, smooth=True)

    # Seatstay brake bridge
    bm_add_prism_between(bm_frame, (-0.048, -0.315, 0.600), (+0.048, -0.315, 0.600), 0.008, 0.008, segs=6, mat_idx=MI_FR)

    # Matching painted cruiser half-chainguard on right side (+X) + subtle lower chain return
    cg_pts = [
        (+0.058, bb_pos.y + 0.072, bb_pos.z + 0.036),
        (+0.058, bb_pos.y + 0.015, bb_pos.z + 0.088),
        (+0.060, -0.18, 0.390),
        (+0.060, -0.36, 0.386),
        (+0.060, wy_rear + 0.010, axle_z + 0.038),
    ]
    bm_add_spline_tube(bm_frame, cg_pts, [0.014, 0.022, 0.022, 0.018, 0.013], segs=8, oval_ratio=0.34, mat_idx=MI_FR)
    # Dark steel lower chain run from chainring bottom to rear sprocket bottom
    bm_add_prism_between(bm_frame, (+0.048, bb_pos.y, bb_pos.z - 0.074), (+0.042, wy_rear, axle_z - 0.032), 0.0045, 0.0045, segs=5, mat_idx=MI_BK)

    # Iconic Curved Rear Mudguard Fender (GBike_FenderAccent, runtime-tintable!)
    bm_add_curved_fender(
        bm_frame,
        axle_center=(0.0, wy_rear, axle_z),
        radius=wheel_r + 0.046,
        a0=0.21 * math.pi,
        a1=1.04 * math.pi,
        arc_segs=16,
        half_w=0.038,
        arch_drop=0.015,
        thick=0.006,
        mat_idx=MI_FN,
    )
    # Chrome rear fender support stays
    for sgn in (-1.0, 1.0):
        stay_end = (sgn * 0.036, wy_rear + math.cos(0.92 * math.pi) * (wheel_r + 0.044), axle_z + math.sin(0.92 * math.pi) * (wheel_r + 0.044))
        bm_add_prism_between(bm_frame, (sgn * 0.056, wy_rear, axle_z), stay_end, 0.0038, 0.0038, segs=6, mat_idx=MI_CH)

    # Compact Rear Utility Rack + Ruby Tail Reflector
    rack_z = 0.728
    rack_y_f, rack_y_r = -0.28, -0.74
    rack_hw = 0.072
    rack_loop = [
        (-rack_hw, rack_y_f, rack_z),
        (-rack_hw, rack_y_r + 0.04, rack_z),
        (-rack_hw * 0.65, rack_y_r, rack_z),
        (+rack_hw * 0.65, rack_y_r, rack_z),
        (+rack_hw, rack_y_r + 0.04, rack_z),
        (+rack_hw, rack_y_f, rack_z),
    ]
    bm_add_spline_tube(bm_frame, rack_loop, [0.0075] * len(rack_loop), segs=6, mat_idx=MI_BK)
    for ry in (-0.36, -0.50, -0.64):
        bm_add_prism_between(bm_frame, (-rack_hw, ry, rack_z), (+rack_hw, ry, rack_z), 0.0055, 0.0055, segs=6, mat_idx=MI_BK)
    for sgn in (-1.0, 1.0):
        # Struts to rear axle & seatstay mount
        bm_add_prism_between(bm_frame, (sgn * 0.056, wy_rear, axle_z + 0.010), (sgn * rack_hw, -0.66, rack_z), 0.0055, 0.0055, segs=6, mat_idx=MI_BK)
        bm_add_prism_between(bm_frame, (sgn * 0.032, -0.22, 0.665), (sgn * rack_hw, rack_y_f, rack_z), 0.0055, 0.0055, segs=6, mat_idx=MI_BK)

    # Rear Tail Reflector (mounted cleanly at rear tip of rack + secondary rear-fender reflector)
    bm_add_box(bm_frame, (0.0, rack_y_r - 0.012, rack_z), (0.058, 0.018, 0.028), bevel=0.004, mat_idx=MI_RF, smooth=True)
    f_ref_a = 0.90 * math.pi
    f_ref_y = wy_rear + math.cos(f_ref_a) * (wheel_r + 0.052)
    f_ref_z = axle_z + math.sin(f_ref_a) * (wheel_r + 0.052)
    bm_add_box(bm_frame, (0.0, f_ref_y, f_ref_z), (0.034, 0.016, 0.036), rot_euler=(-0.32, 0.0, 0.0), bevel=0.003, mat_idx=MI_RF, smooth=True)

    # Chrome Seatpost & Contoured Cruiser Saddle (sad_top at ~ (0, -0.20, 0.935)!)
    post_top = Vector((0.0, -0.200, 0.892))
    bm_add_prism_between(bm_frame, seat_cl, post_top, 0.013, 0.013, segs=10, mat_idx=MI_CH)
    # Twin chrome coil saddle springs beneath rear of saddle
    for sgn in (-1.0, 1.0):
        bm_add_prism_between(bm_frame, (sgn * 0.052, -0.258, 0.868), (sgn * 0.056, -0.258, 0.904), 0.014, 0.012, segs=8, mat_idx=MI_CH)
        bm_add_prism_between(bm_frame, (sgn * 0.015, -0.200, 0.882), (sgn * 0.052, -0.258, 0.868), 0.005, 0.005, segs=5, mat_idx=MI_CH)

    # Contoured plush cruiser saddle (broad sculpted rear + tapered ergonomic nose)
    bm_add_sphere(bm_frame, (0.0, -0.235, 0.910), rx=0.106, ry=0.088, rz=0.028, u_segs=14, v_segs=8, mat_idx=MI_SD)
    bm_add_sphere(bm_frame, (0.0, -0.175, 0.914), rx=0.068, ry=0.075, rz=0.023, u_segs=12, v_segs=8, mat_idx=MI_SD)
    bm_add_sphere(bm_frame, (0.0, -0.115, 0.918), rx=0.034, ry=0.055, rz=0.018, u_segs=10, v_segs=6, mat_idx=MI_SD)

    # Folded Kickstand tucked cleanly along left chainstay (well clear of ground & spokes)
    ks_mount = (-0.044, -0.155, 0.285)
    ks_tip = (-0.082, -0.455, 0.305)
    bm_add_box(bm_frame, ks_mount, (0.024, 0.032, 0.028), bevel=0.004, mat_idx=MI_CH)
    bm_add_prism_between(bm_frame, ks_mount, ks_tip, 0.0075, 0.0065, segs=8, mat_idx=MI_CH)
    bm_add_box(bm_frame, (-0.084, -0.468, 0.306), (0.018, 0.026, 0.020), bevel=0.003, mat_idx=MI_SD)

    obj_frame = finalize_multimat_mesh("GBike_Frame", bm_frame, frame_mats, location=(0.0, 0.0, 0.0))

    # -----------------------------------------------------------------------
    # Helper to populate a centered Wheel BMesh at local (0, 0, 0)
    # -----------------------------------------------------------------------
    def make_wheel_obj(name, location, parent=None, include_sprocket=False):
        wheel_mats = [mat_tire, mat_chrome]
        MI_T, MI_C = 0, 1
        bm_w = bmesh.new()
        w_rot = (0.0, math.pi * 0.5, 0.0)
        # Tire torus: major_segs=24 (multiple of 4), minor_segs=8 (even) -> exact Z_min = -(wheel_r + tire_r) = -0.340!
        bm_add_torus(bm_w, (0.0, 0.0, 0.0), wheel_r, tire_r, rot_euler=w_rot, major_segs=24, minor_segs=8, mat_idx=MI_T)
        # Polished chrome rim
        bm_add_torus(bm_w, (0.0, 0.0, 0.0), wheel_r - 0.028, 0.0125, rot_euler=w_rot, major_segs=24, minor_segs=6, mat_idx=MI_C)
        # Hub barrel, flanges, and axle nuts
        bm_add_prism_between(bm_w, (-0.048, 0.0, 0.0), (+0.048, 0.0, 0.0), 0.017, 0.017, segs=8, mat_idx=MI_C)
        for sx in (-0.030, +0.030):
            bm_add_prism_between(bm_w, (sx - 0.003, 0.0, 0.0), (sx + 0.003, 0.0, 0.0), 0.028, 0.028, segs=8, mat_idx=MI_C)
        bm_add_prism_between(bm_w, (-0.062, 0.0, 0.0), (+0.062, 0.0, 0.0), 0.0075, 0.0075, segs=6, mat_idx=MI_C)
        if include_sprocket:
            bm_add_prism_between(bm_w, (+0.036, 0.0, 0.0), (+0.044, 0.0, 0.0), 0.035, 0.035, segs=10, mat_idx=MI_C)
        # 8 crisp alternating-flange spokes radiating from hub flanges to rim
        for sp in range(8):
            sa = sp * (2.0 * math.pi / 8.0)
            flange_x = +0.028 if (sp % 2 == 0) else -0.028
            p_hub = (flange_x, math.cos(sa) * 0.022, math.sin(sa) * 0.022)
            p_rim = (0.0, math.cos(sa) * (wheel_r - 0.028), math.sin(sa) * (wheel_r - 0.028))
            bm_add_prism_between(bm_w, p_hub, p_rim, 0.0034, 0.0034, segs=4, cap=False, mat_idx=MI_C)
        # Subtle chrome valve stem so wheel spin reads vividly
        bm_add_prism_between(bm_w, (0.0, wheel_r - 0.034, 0.0), (0.0, wheel_r - 0.068, 0.0), 0.004, 0.0035, segs=5, mat_idx=MI_C)
        return finalize_multimat_mesh(name, bm_w, wheel_mats, location=location, parent=parent)

    # -----------------------------------------------------------------------
    # 2. GBike_WheelRear (exact origin at rear axle: 0.0, -0.52, 0.340)
    # -----------------------------------------------------------------------
    obj_wheel_rear = make_wheel_obj("GBike_WheelRear", location=(0.0, wy_rear, axle_z), include_sprocket=True)

    # -----------------------------------------------------------------------
    # 3. GBike_CrankPedals (exact origin at bottom bracket: 0.0, -0.06, 0.300)
    # -----------------------------------------------------------------------
    crank_mats = [mat_chrome, mat_saddle, mat_fender]
    bm_crank = bmesh.new()
    # Spindle
    bm_add_prism_between(bm_crank, (-0.064, 0.0, 0.0), (+0.064, 0.0, 0.0), 0.011, 0.011, segs=8, mat_idx=0)
    # Chrome Chainring on right (+X) side with 5-arm spider
    bm_add_torus(bm_crank, (+0.048, 0.0, 0.0), 0.078, 0.0085, rot_euler=(0.0, math.pi * 0.5, 0.0), major_segs=20, minor_segs=6, mat_idx=0)
    bm_add_prism_between(bm_crank, (+0.042, 0.0, 0.0), (+0.054, 0.0, 0.0), 0.022, 0.022, segs=10, mat_idx=0)
    for si in range(5):
        sa = si * (2.0 * math.pi / 5.0)
        bm_add_prism_between(bm_crank, (+0.048, 0.0, 0.0), (+0.048, math.cos(sa) * 0.074, math.sin(sa) * 0.074), 0.006, 0.005, segs=5, mat_idx=0)

    # Left & Right crank arms + opposite-angle rubber cruiser pedals
    for sgn, pz in ((-1.0, -0.145), (+1.0, +0.145)):
        bm_add_prism_between(bm_crank, (sgn * 0.060, 0.0, 0.0), (sgn * 0.068, 0.0, pz), 0.011, 0.0085, segs=6, mat_idx=0)
        bm_add_prism_between(bm_crank, (sgn * 0.068, 0.0, pz), (sgn * 0.155, 0.0, pz), 0.0055, 0.0055, segs=6, mat_idx=0)
        bm_add_box(bm_crank, (sgn * 0.114, 0.0, pz), (0.094, 0.070, 0.022), bevel=0.004, mat_idx=1, smooth=True)
        # Subtle amber/yellow pedal reflector bars
        bm_add_box(bm_crank, (sgn * 0.114, +0.036, pz), (0.052, 0.005, 0.010), mat_idx=2)
        bm_add_box(bm_crank, (sgn * 0.114, -0.036, pz), (0.052, 0.005, 0.010), mat_idx=2)

    obj_crank = finalize_multimat_mesh("GBike_CrankPedals", bm_crank, crank_mats, location=tuple(bb_pos))

    # -----------------------------------------------------------------------
    # 4. GBike_FrontAssembly (exact origin at head-tube steerer: 0.0, +0.36, 0.740)
    # -----------------------------------------------------------------------
    front_mats = [mat_frame, mat_fender, mat_chrome, mat_saddle, mat_basket, mat_badge]
    F_FR, F_FN, F_CH, F_SD, F_BK, F_BG = 0, 1, 2, 3, 4, 5
    bm_front = bmesh.new()

    # Local coordinates relative to head_origin = (0.0, +0.360, 0.740)
    lf_ax = Vector((0.0, wy_front, axle_z)) - head_origin  # Exact (0.0, +0.200, -0.400)!
    l_hbot = head_bot - head_origin  # (0.0, +0.022, -0.062)
    l_htop = head_top - head_origin  # (0.0, -0.022, +0.062)

    # Fork crown & gracefully raked twin front fork blades down to front axle
    crown_c = l_hbot + Vector((0.0, +0.005, -0.018))
    bm_add_box(bm_front, crown_c, (0.072, 0.034, 0.026), bevel=0.006, mat_idx=F_FR, smooth=True)
    for sgn in (-1.0, 1.0):
        fk_pts = [
            crown_c + Vector((sgn * 0.028, 0.0, 0.0)),
            (sgn * 0.044, +0.072, -0.175),
            (sgn * 0.048, +0.130, -0.295),
            (sgn * 0.050, lf_ax.y, lf_ax.z),
        ]
        bm_add_spline_tube(bm_front, fk_pts, [0.016, 0.0145, 0.0125, 0.0105], segs=8, mat_idx=F_FR)
        bm_add_box(bm_front, (sgn * 0.050, lf_ax.y, lf_ax.z), (0.009, 0.030, 0.030), bevel=0.003, mat_idx=F_FR, smooth=True)

    # Curved Front Mudguard Fender (GBike_FenderAccent, clear of tire & fork crown!)
    bm_add_curved_fender(
        bm_front,
        axle_center=tuple(lf_ax),
        radius=wheel_r + 0.046,
        a0=0.22 * math.pi,
        a1=0.92 * math.pi,
        arc_segs=14,
        half_w=0.038,
        arch_drop=0.015,
        thick=0.006,
        mat_idx=F_FN,
    )
    for sgn in (-1.0, 1.0):
        fst_a = 0.84 * math.pi
        fst_end = (sgn * 0.036, lf_ax.y + math.cos(fst_a) * (wheel_r + 0.044), lf_ax.z + math.sin(fst_a) * (wheel_r + 0.044))
        bm_add_prism_between(bm_front, (sgn * 0.050, lf_ax.y, lf_ax.z), fst_end, 0.0038, 0.0038, segs=6, mat_idx=F_CH)

    # Chrome Quill Stem & Swept-Back Beach-Cruiser Handlebars
    stem_elbow = Vector((0.0, -0.068, +0.238))
    stem_clamp = Vector((0.0, -0.020, +0.248))
    bm_add_prism_between(bm_front, l_htop, stem_elbow, 0.0135, 0.0135, segs=10, mat_idx=F_CH)
    bm_add_prism_between(bm_front, stem_elbow, stem_clamp, 0.0145, 0.016, segs=10, mat_idx=F_CH)
    bm_add_prism_between(bm_front, (-0.024, stem_clamp.y, stem_clamp.z), (+0.024, stem_clamp.y, stem_clamp.z), 0.019, 0.019, segs=10, mat_idx=F_CH)

    hb_pts = [
        (-0.320, -0.178, +0.278),
        (-0.268, -0.098, +0.296),
        (-0.188, -0.034, +0.290),
        (-0.088, -0.020, +0.256),
        tuple(stem_clamp),
        (+0.088, -0.020, +0.256),
        (+0.188, -0.034, +0.290),
        (+0.268, -0.098, +0.296),
        (+0.320, -0.178, +0.278),
    ]
    bm_add_spline_tube(bm_front, hb_pts, [0.0125] * len(hb_pts), segs=9, mat_idx=F_CH)

    # Dark ergonomic cruiser rubber grips on handlebar ends
    for sgn in (-1.0, 1.0):
        g_in = Vector((sgn * 0.256, -0.086, +0.295))
        g_out = Vector((sgn * 0.328, -0.188, +0.275))
        g_dir = (g_out - g_in).normalized()
        bm_add_prism_between(bm_front, g_in, g_in + g_dir * 0.012, 0.021, 0.019, segs=10, mat_idx=F_SD)
        bm_add_prism_between(bm_front, g_in + g_dir * 0.010, g_out, 0.0175, 0.0185, segs=10, mat_idx=F_SD)

    # Iconic Shiny Chrome Handlebar Bell on Right Bar (+X)!
    bell_base = Vector((+0.195, -0.042, +0.294))
    bm_add_prism_between(bm_front, bell_base - Vector((0, 0, 0.014)), bell_base + Vector((0, 0, 0.014)), 0.017, 0.017, segs=8, mat_idx=F_SD)
    bm_add_prism_between(bm_front, bell_base + Vector((0, 0, 0.014)), bell_base + Vector((0, 0, 0.024)), 0.026, 0.027, segs=12, mat_idx=F_CH)
    bm_add_sphere(bm_front, bell_base + Vector((0, 0, 0.025)), rx=0.027, ry=0.027, rz=0.019, u_segs=14, v_segs=8, mat_idx=F_CH)
    # Thumb flick striker lever
    bm_add_prism_between(bm_front, bell_base + Vector((-0.022, -0.014, 0.018)), bell_base + Vector((-0.044, -0.032, 0.024)), 0.004, 0.0055, segs=6, mat_idx=F_SD)

    # Signature Iconic Google GBike Front Wire Basket (GBike_BasketWire)!
    bk_c = Vector((0.0, +0.165, +0.145))  # world (0.0, +0.525, 0.885)
    bw, bd, bh = 0.36, 0.25, 0.22
    # 4 tapered horizontal perimeter wire hoops (bottom, 1/3, 2/3, top)
    for frac in (0.0, 0.34, 0.67, 1.0):
        hz = -bh * 0.5 + bh * frac
        sc = 0.82 + 0.18 * frac
        w2, d2 = bw * 0.5 * sc, bd * 0.5 * sc
        rad_w = 0.0068 if frac in (0.0, 1.0) else 0.0045
        c0 = bk_c + Vector((-w2, -d2, hz))
        c1 = bk_c + Vector((+w2, -d2, hz))
        c2 = bk_c + Vector((+w2, +d2, hz))
        c3 = bk_c + Vector((-w2, +d2, hz))
        for pa, pb in ((c0, c1), (c1, c2), (c2, c3), (c3, c0)):
            bm_add_prism_between(bm_front, pa, pb, rad_w, rad_w, segs=6, mat_idx=F_BK)

    # Vertical wire ribs around all 4 sides
    for sx in (-1.0, -0.5, 0.0, 0.5, 1.0):
        for sy in (-1.0, 1.0):
            pb = bk_c + Vector((sx * bw * 0.41, sy * bd * 0.41, -bh * 0.5))
            pt = bk_c + Vector((sx * bw * 0.50, sy * bd * 0.50, +bh * 0.5))
            bm_add_prism_between(bm_front, pb, pt, 0.0045, 0.0045, segs=5, mat_idx=F_BK)
    for sy in (-0.35, 0.35):
        for sx in (-1.0, 1.0):
            pb = bk_c + Vector((sx * bw * 0.41, sy * bd * 0.41, -bh * 0.5))
            pt = bk_c + Vector((sx * bw * 0.50, sy * bd * 0.50, +bh * 0.5))
            bm_add_prism_between(bm_front, pb, pt, 0.0045, 0.0045, segs=5, mat_idx=F_BK)

    # Basket perforated floor tray + handlebar mounting hooks + fender-clearing lower support stays
    bm_add_box(bm_front, bk_c + Vector((0, 0, -bh * 0.5)), (bw * 0.82, bd * 0.82, 0.010), bevel=0.002, mat_idx=F_BK)
    for sgn in (-1.0, 1.0):
        # Twin upper brackets hooking cleanly to handlebars
        bm_add_prism_between(bm_front, bk_c + Vector((sgn * 0.095, -bd * 0.46, +bh * 0.38)), (sgn * 0.095, -0.020, +0.256), 0.0055, 0.0055, segs=6, mat_idx=F_BK)
        # Twin lower support stays bowing cleanly OUTSIDE the front yellow fender down to axle dropouts!
        stay_pts = [
            (sgn * 0.056, lf_ax.y, lf_ax.z),
            (sgn * 0.082, lf_ax.y + 0.015, lf_ax.z + 0.19),
            (sgn * 0.098, bk_c.y + 0.010, bk_c.z - bh * 0.5 - 0.02),
            bk_c + Vector((sgn * 0.112, 0.0, -bh * 0.5)),
        ]
        bm_add_spline_tube(bm_front, stay_pts, [0.0055, 0.0055, 0.0055, 0.0055], segs=6, mat_idx=F_BK)

    # Front-facing Google "GBIKE" plaque centered on the front wire face of the basket!
    plaque_y = bk_c.y + bd * 0.475
    plaque_z = bk_c.z + 0.025
    bm_add_box(bm_front, (0.0, plaque_y, plaque_z), (0.146, 0.008, 0.072), bevel=0.002, mat_idx=F_BK)
    bm_add_textured_quad(
        bm_front,
        center=(0.0, plaque_y + 0.0055, plaque_z),
        viewer_right=(-1.0, 0.0, 0.0),  # Looking from +Y toward -Y, viewer-right is -X!
        up_vec=(0.0, 0.0, 1.0),
        width=0.138,
        height=0.066,
        mat_idx=F_BG,
    )

    obj_front = finalize_multimat_mesh(
        "GBike_FrontAssembly",
        bm_front,
        front_mats,
        location=tuple(head_origin),
        skip_uv_mats=(F_BG,),
    )

    # -----------------------------------------------------------------------
    # 5. GBike_WheelFront (child of GBike_FrontAssembly, exact local 0, +0.20, -0.40)
    # -----------------------------------------------------------------------
    obj_wheel_front = make_wheel_obj(
        "GBike_WheelFront",
        location=(0.0, +0.200, -0.400),
        parent=obj_front,
        include_sprocket=False,
    )

    # -----------------------------------------------------------------------
    # 6. GBike_SeatMount (Empty at exact rider saddle anchor: 0.0, -0.20, 0.95)
    # -----------------------------------------------------------------------
    obj_seat = bpy.data.objects.new("GBike_SeatMount", None)
    obj_seat.empty_display_type = "ARROWS"
    obj_seat.empty_display_size = 0.16
    obj_seat.location = seat_mount_pos
    bpy.context.collection.objects.link(obj_seat)

    bpy.context.view_layer.update()

    # Select all objects (including Empty!) and export GLB without Draco
    export_objs = [obj_frame, obj_wheel_rear, obj_crank, obj_front, obj_wheel_front, obj_seat]
    return export_selected_glb("prop_gbike_rideable.glb", export_objs)


# ===========================================================================
# ASSET 2: ICONIC GOOGLE TECHSTOP UPGRADE KIOSK (prop_techstop_kiosk.glb)
# ===========================================================================
def build_techstop_kiosk():
    reset_scene()

    sign_w, sign_h = 1.76, 0.285
    tex_sign = gen_techstop_sign_tex("Tex_TechStopSign", 512, 128, quad_aspect=sign_w / sign_h)
    tex_diag = gen_techstop_diag_tex("Tex_TechStopDiag", 256, 256)
    tex_oak = gen_light_oak_tex("Tex_LightOak", 128)

    # Crisp modern Google TechStop PBR materials
    mat_white = make_pbr_mat(
        "TechStop_DeskWhite",
        base_color=hex_to_linear("#F8FAFD"),
        metallic=0.04,
        roughness=0.32,
    )
    mat_oak = make_pbr_mat(
        "TechStop_LightOak",
        base_color=(1.0, 1.0, 1.0, 1.0),
        metallic=0.0,
        roughness=0.58,
        tex_img=tex_oak,
    )
    mat_alu = make_pbr_mat(
        "TechStop_BrushedAluminum",
        base_color=hex_to_linear("#CBD5E1"),
        metallic=0.84,
        roughness=0.26,
    )
    mat_steel = make_pbr_mat(
        "TechStop_SupportSteel",
        base_color=hex_to_linear("#B8C4D4"),
        metallic=0.88,
        roughness=0.22,
    )
    mat_dark = make_pbr_mat(
        "TechStop_DarkAnodized",
        base_color=hex_to_linear("#1E2530"),
        metallic=0.62,
        roughness=0.34,
    )
    mat_led_blue = make_pbr_mat(
        "TechStop_LedStrip",
        base_color=hex_to_linear(G_BLUE),
        metallic=0.0,
        roughness=0.18,
        emission=hex_to_linear(G_BLUE),
        emission_strength=3.4,
    )
    mat_holo_ring = make_pbr_mat(
        "TechStop_HoloRing",
        base_color=hex_to_linear("#38BDF8"),
        metallic=0.0,
        roughness=0.14,
        emission=hex_to_linear("#38BDF8"),
        emission_strength=3.6,
    )
    mat_holo_icon = make_pbr_mat(
        "TechStop_HoloIcon",
        base_color=hex_to_linear("#7DD3FC", alpha=0.76),
        metallic=0.0,
        roughness=0.12,
        alpha=0.76,
        emission=hex_to_linear("#38BDF8"),
        emission_strength=3.2,
        double_sided=True,
    )
    mat_holo_beam = make_pbr_mat(
        "TechStop_HoloBeam",
        base_color=hex_to_linear("#38BDF8", alpha=0.16),
        metallic=0.0,
        roughness=0.10,
        alpha=0.16,
        emission=hex_to_linear("#38BDF8"),
        emission_strength=1.5,
        double_sided=True,
    )
    mat_diag = make_pbr_mat(
        "TechStop_DiagScreen",
        base_color=(1.0, 1.0, 1.0, 1.0),
        metallic=0.05,
        roughness=0.16,
        tex_img=tex_diag,
        emission_tex=True,
        emission_strength=1.45,
    )
    mat_sign = make_pbr_mat(
        "TechStop_SignBanner",
        base_color=(1.0, 1.0, 1.0, 1.0),
        metallic=0.05,
        roughness=0.20,
        tex_img=tex_sign,
        emission_tex=True,
        emission_strength=0.78,
    )
    mat_downlight = make_pbr_mat(
        "TechStop_Downlight",
        base_color=hex_to_linear("#FFFFFF"),
        roughness=0.15,
        emission=hex_to_linear("#F0F7FF"),
        emission_strength=2.2,
    )
    mat_gblue = make_pbr_mat("TechStop_GBlue", base_color=hex_to_linear(G_BLUE), metallic=0.15, roughness=0.26, emission=hex_to_linear(G_BLUE), emission_strength=0.45)
    mat_gred = make_pbr_mat("TechStop_GRed", base_color=hex_to_linear(G_RED), metallic=0.15, roughness=0.26, emission=hex_to_linear(G_RED), emission_strength=0.45)
    mat_gyel = make_pbr_mat("TechStop_GYellow", base_color=hex_to_linear(G_YELLOW), metallic=0.15, roughness=0.26, emission=hex_to_linear(G_YELLOW), emission_strength=0.45)
    mat_ggrn = make_pbr_mat("TechStop_GGreen", base_color=hex_to_linear(G_GREEN), metallic=0.15, roughness=0.26, emission=hex_to_linear(G_GREEN), emission_strength=0.45)
    mat_canopy_blue = make_pbr_mat("TechStop_CanopyBlue", base_color=hex_to_linear(G_BLUE_DEEP), metallic=0.22, roughness=0.28)

    # -----------------------------------------------------------------------
    # 1. Curved White/Light-Gray Desk Counter (2.40m W x 1.05m D x 0.98m H)
    # -----------------------------------------------------------------------
    desk_mats = [mat_white, mat_oak, mat_alu, mat_dark, mat_led_blue]
    D_WH, D_OK, D_AL, D_DK, D_LD = 0, 1, 2, 3, 4
    bm_desk = bmesh.new()

    # Grounded brushed-aluminum recessed toe-kick (exact Z = 0.000 .. 0.095)
    bm_add_rounded_rect_prism(bm_desk, 0.0, 0.0, w=2.26, d=0.96, r_corner=0.35, z0=0.000, z1=0.096, corner_segs=6, mat_idx=D_AL, smooth=False)

    # Main curved matte-white desk body (Z = 0.095 .. 0.902)
    bm_add_rounded_rect_prism(bm_desk, 0.0, 0.0, w=2.38, d=1.04, r_corner=0.39, z0=0.095, z1=0.902, corner_segs=7, mat_idx=D_WH, smooth=False)

    # Crisp recessed Google-Blue LED strip under the countertop lip (Z = 0.901 .. 0.928)
    bm_add_rounded_rect_prism(bm_desk, 0.0, 0.01, w=2.41, d=1.07, r_corner=0.40, z0=0.901, z1=0.928, corner_segs=7, mat_idx=D_LD, smooth=False)

    # Crisp beveled white countertop slab (Z = 0.926 .. 0.980, 2.44m x 1.12m)
    bm_add_rounded_rect_prism(bm_desk, 0.0, 0.01, w=2.44, d=1.12, r_corner=0.42, z0=0.926, z1=0.980, corner_segs=7, bevel_top=0.012, mat_idx=D_WH, smooth=False)

    # Front (+Y) architectural recessed dark shadow bay + 17 warm light-oak vertical slats!
    bm_add_box(bm_desk, (0.0, +0.516, 0.500), (1.62, 0.022, 0.68), mat_idx=D_DK)
    num_slats = 17
    for si in range(num_slats):
        sx = -0.74 + si * (1.48 / (num_slats - 1))
        bm_add_box(bm_desk, (sx, +0.530, 0.500), (0.048, 0.026, 0.66), mat_idx=D_OK)
    # Brushed aluminum trim frame framing the front oak bay
    bm_add_box(bm_desk, (0.0, +0.526, 0.842), (1.64, 0.026, 0.018), mat_idx=D_AL)
    bm_add_box(bm_desk, (0.0, +0.526, 0.158), (1.64, 0.026, 0.018), mat_idx=D_AL)

    # Rear (-Y) dark anodized IT service bay + ventilation louvers (360-deg finish!)
    bm_add_box(bm_desk, (0.0, -0.520, 0.500), (1.54, 0.020, 0.64), mat_idx=D_DK)
    for lx in (-0.42, +0.42):
        bm_add_box(bm_desk, (lx, -0.530, 0.500), (0.58, 0.014, 0.54), mat_idx=D_AL)
        for vz in (0.34, 0.42, 0.50, 0.58, 0.66):
            bm_add_box(bm_desk, (lx, -0.538, vz), (0.44, 0.008, 0.024), mat_idx=D_DK)

    obj_desk = finalize_multimat_mesh("TechStop_Desk", bm_desk, desk_mats, uv_scale=1.1)

    # -----------------------------------------------------------------------
    # 2. Center Holographic Weapon Upgrade Pad (Z = 0.980m) + Floating Icon
    # -----------------------------------------------------------------------
    pad_c = Vector((0.0, +0.08, 0.980))
    pad_mats = [mat_dark, mat_alu, mat_holo_ring, mat_holo_beam]
    P_DK, P_AL, P_HR, P_HB = 0, 1, 2, 3
    bm_pad = bmesh.new()

    # Circular dark anodized charging pad base (stepped bevel disc)
    bm_add_prism_between(bm_pad, pad_c, pad_c + Vector((0, 0, 0.016)), 0.340, 0.326, segs=32, mat_idx=P_DK, smooth=True)
    bm_add_prism_between(bm_pad, pad_c + Vector((0, 0, 0.016)), pad_c + Vector((0, 0, 0.024)), 0.270, 0.256, segs=28, mat_idx=P_AL, smooth=True)
    bm_add_prism_between(bm_pad, pad_c + Vector((0, 0, 0.022)), pad_c + Vector((0, 0, 0.026)), 0.228, 0.224, segs=28, mat_idx=P_DK, smooth=True)

    # 4 brushed-aluminum radial weapon-alignment lugs
    for k in range(4):
        ang = k * math.pi * 0.5 + math.pi * 0.25
        lx = pad_c.x + math.cos(ang) * 0.302
        ly = pad_c.y + math.sin(ang) * 0.302
        bm_add_box(bm_pad, (lx, ly, pad_c.z + 0.018), (0.062, 0.030, 0.024), rot_euler=(0.0, 0.0, ang), bevel=0.004, mat_idx=P_AL)

    # Glowing concentric cyan/Google-Blue energy rings (TechStop_HoloRing!)
    bm_add_torus(bm_pad, pad_c + Vector((0, 0, 0.021)), major_r=0.292, minor_r=0.010, major_segs=32, minor_segs=8, mat_idx=P_HR)
    bm_add_torus(bm_pad, pad_c + Vector((0, 0, 0.027)), major_r=0.195, minor_r=0.008, major_segs=28, minor_segs=8, mat_idx=P_HR)
    bm_add_torus(bm_pad, pad_c + Vector((0, 0, 0.028)), major_r=0.095, minor_r=0.0065, major_segs=24, minor_segs=8, mat_idx=P_HR)
    # 4 cardinal alignment dashes inside pad
    for k in range(4):
        ang = k * math.pi * 0.5
        p0 = pad_c + Vector((math.cos(ang) * 0.115, math.sin(ang) * 0.115, 0.028))
        p1 = pad_c + Vector((math.cos(ang) * 0.175, math.sin(ang) * 0.175, 0.028))
        bm_add_prism_between(bm_pad, p0, p1, 0.0055, 0.0055, segs=6, mat_idx=P_HR)

    # Subtle translucent holographic projection cone rising off the pad
    bm_add_prism_between(bm_pad, pad_c + Vector((0, 0, 0.026)), pad_c + Vector((0, 0, 0.290)), 0.210, 0.260, segs=24, cap=False, mat_idx=P_HB, smooth=True)

    obj_pad = finalize_multimat_mesh("TechStop_HoloPad", bm_pad, pad_mats)

    # Separate Floating Translucent Upgrade Chevron & Reticle Icon (origin at center so Three.js can bob/spin it!)
    icon_origin = Vector((0.0, +0.08, 1.290))
    bm_icon = bmesh.new()
    # Outer vertical circular holographic reticle ring (aligned along X-Z facing +Y/-Y!)
    bm_add_torus(bm_icon, (0.0, 0.0, 0.0), major_r=0.155, minor_r=0.0075, rot_euler=(math.pi * 0.5, 0.0, 0.0), major_segs=28, minor_segs=6, mat_idx=0)
    # 4 cardinal reticle ticks on ring
    for ang in (0.0, math.pi * 0.5, math.pi, 1.5 * math.pi):
        p0 = Vector((math.cos(ang) * 0.132, 0.0, math.sin(ang) * 0.132))
        p1 = Vector((math.cos(ang) * 0.180, 0.0, math.sin(ang) * 0.180))
        bm_add_prism_between(bm_icon, p0, p1, 0.007, 0.007, segs=6, mat_idx=0)
    # Double crisp upward-pointing upgrade chevrons (^^)
    for cz_off in (-0.038, +0.040):
        apex = Vector((0.0, 0.0, cz_off + 0.046))
        left_pt = Vector((-0.082, 0.0, cz_off - 0.026))
        right_pt = Vector((+0.082, 0.0, cz_off - 0.026))
        bm_add_prism_between(bm_icon, left_pt, apex, 0.013, 0.013, segs=6, mat_idx=0)
        bm_add_prism_between(bm_icon, apex, right_pt, 0.013, 0.013, segs=6, mat_idx=0)
    # Subtle inner horizontal holo ring for 3D depth from side angles
    bm_add_torus(bm_icon, (0.0, 0.0, -0.155), major_r=0.120, minor_r=0.005, rot_euler=(0.0, 0.0, 0.0), major_segs=24, minor_segs=6, mat_idx=0)

    obj_icon = finalize_multimat_mesh("TechStop_HoloIcon", bm_icon, [mat_holo_icon], location=tuple(icon_origin))

    # -----------------------------------------------------------------------
    # 3. Dual Angled Diagnostic Monitors + Calibration Tools
    # -----------------------------------------------------------------------
    mon_mats = [mat_alu, mat_dark, mat_diag, mat_gblue, mat_gred, mat_gyel, mat_ggrn]
    M_AL, M_DK, M_SC, M_B, M_R, M_Y, M_G = 0, 1, 2, 3, 4, 5, 6
    bm_mon = bmesh.new()

    # Left (+X from viewer's left? Wait: viewer stands at +Y looking -Y:
    #   viewer's LEFT is +X, viewer's RIGHT is -X! Both monitors angle inward toward (0, +1.2)!)
    monitor_specs = [
        # (center_x, center_y, yaw_z_rad, uv_rect)
        (+0.78, -0.14, +0.34, (0.0, 0.5, 1.0, 1.0)),  # Viewer-Left wing, angled inward toward +Y center
        (-0.78, -0.14, -0.34, (0.0, 0.0, 1.0, 0.5)),  # Viewer-Right wing, angled inward toward +Y center
    ]
    for mx, my, myaw, uv_r in monitor_specs:
        m_rot = Euler((0.0, 0.0, myaw), "XYZ").to_matrix()
        base_p = Vector((mx, my, 0.980))

        def mp(lx, ly, lz):
            return base_p + (m_rot @ Vector((lx, ly, lz)))

        # Sleek brushed aluminum foot plate & angled neck
        bm_add_box(bm_mon, mp(0.0, 0.01, 0.008), (0.19, 0.16, 0.014), rot_euler=(0.0, 0.0, myaw), bevel=0.004, mat_idx=M_AL)
        bm_add_prism_between(bm_mon, mp(0.0, -0.04, 0.014), mp(0.0, -0.02, 0.255), 0.019, 0.015, segs=8, mat_idx=M_AL)

        # Ultra-slim aluminum display housing tilted back slightly (+10 deg) so player reads easily
        tilt = 0.14
        scr_c = mp(0.0, +0.012, 0.285)
        scr_euler = Euler((tilt, 0.0, myaw), "XYZ")
        bm_add_box(bm_mon, scr_c, (0.48, 0.026, 0.305), rot_euler=scr_euler, bevel=0.005, mat_idx=M_AL)
        # Inner dark screen bezel
        scr_mat = scr_euler.to_matrix()
        fwd = scr_mat @ Vector((0.0, 1.0, 0.0))
        up_v = scr_mat @ Vector((0.0, 0.0, 1.0))
        viewer_right = fwd.cross(up_v)  # Wait: check! For yaw=0, fwd=(0,1,0), up=(0,0,1) -> fwd x up = (+1,0,0), wait!
        # Let's check exact sign: we want viewer_right x up_v == fwd (pointing toward viewer!).
        # Since right x up = fwd => right = up x fwd!
        # Test: fwd=(0,1,0), up=(0,0,1): up x fwd = (0,0,1) x (0,1,0) = (-1,0,0). Then (-1,0,0) x (0,0,1) = (0,+1,0) == fwd! YES!
        v_right = up_v.cross(fwd).normalized()
        bm_add_box(bm_mon, scr_c + fwd * 0.006, (0.455, 0.018, 0.280), rot_euler=scr_euler, bevel=0.003, mat_idx=M_DK)
        bm_add_textured_quad(
            bm_mon,
            center=scr_c + fwd * 0.0165,
            viewer_right=v_right,
            up_vec=up_v,
            width=0.436,
            height=0.260,
            uv_rect=uv_r,
            mat_idx=M_SC,
        )
        # Subtle 4-color Google dots on back of aluminum monitor shell
        for di, dmi in enumerate((M_B, M_R, M_Y, M_G)):
            dx_dot = -0.045 + di * 0.030
            bm_add_box(bm_mon, scr_c - fwd * 0.015 + v_right * dx_dot, (0.016, 0.006, 0.016), rot_euler=scr_euler, mat_idx=dmi)

    # Compact Countertop Tech Tools & Calibration Props:
    # (A) Left-front (+X): Calibration Dock & Angled Diagnostic Handheld Scanner/Tablet
    dock_p = Vector((+0.64, +0.26, 0.980))
    bm_add_box(bm_mon, dock_p + Vector((0, 0, 0.014)), (0.17, 0.14, 0.028), rot_euler=(0, 0, +0.25), bevel=0.004, mat_idx=M_DK)
    bm_add_box(bm_mon, dock_p + Vector((0, -0.012, 0.076)), (0.14, 0.016, 0.110), rot_euler=(0.32, 0, +0.25), bevel=0.003, mat_idx=M_AL)
    # Dark glass tablet screen face + small green READY status bar
    t_rot = Euler((0.32, 0, +0.25), "XYZ").to_matrix()
    t_fwd = t_rot @ Vector((0, 1, 0))
    bm_add_box(bm_mon, dock_p + Vector((0, -0.012, 0.076)) + t_fwd * 0.007, (0.122, 0.006, 0.092), rot_euler=(0.32, 0, +0.25), mat_idx=M_DK)
    bm_add_box(bm_mon, dock_p + Vector((+0.052, +0.044, 0.030)), (0.026, 0.010, 0.008), rot_euler=(0, 0, +0.25), mat_idx=M_G)

    # (B) Right-front (-X): Precision Calibration Tool Mat + Open-End Tactical Wrench + Color-Coded Drivers
    mat_p = Vector((-0.64, +0.25, 0.980))
    bm_add_box(bm_mon, mat_p + Vector((0, 0, 0.005)), (0.30, 0.19, 0.010), rot_euler=(0, 0, -0.16), bevel=0.003, mat_idx=M_DK)
    # Brushed steel open-end calibration wrench resting cleanly on mat
    w_rot = Euler((0, 0, -0.38), "XYZ").to_matrix()
    wc = mat_p + Vector((-0.01, +0.028, 0.017))
    bm_add_prism_between(bm_mon, wc + w_rot @ Vector((-0.088, 0, 0)), wc + w_rot @ Vector((+0.088, 0, 0)), 0.009, 0.009, segs=6, mat_idx=M_AL)
    # U-shaped open-end wrench jaws on both ends
    for sx_end in (-1.0, +1.0):
        bm_add_box(bm_mon, wc + w_rot @ Vector((sx_end * 0.092, 0, 0)), (0.018, 0.042, 0.013), rot_euler=(0, 0, -0.38), mat_idx=M_AL)
        for sy_jaw in (-0.015, +0.015):
            bm_add_box(bm_mon, wc + w_rot @ Vector((sx_end * 0.110, sy_jaw, 0)), (0.024, 0.011, 0.013), rot_euler=(0, 0, -0.38), mat_idx=M_AL)
    # Twin color-coded calibration hex drivers (Google Blue & Google Red handles)
    for dy_d, h_mi in ((-0.034, M_B), (-0.066, M_R)):
        dc = mat_p + Vector((+0.01, dy_d, 0.018))
        bm_add_prism_between(bm_mon, dc + Vector((-0.092, 0, 0)), dc + Vector((-0.018, 0, 0)), 0.011, 0.010, segs=8, mat_idx=h_mi)
        bm_add_prism_between(bm_mon, dc + Vector((-0.018, 0, 0)), dc + Vector((+0.092, 0, 0)), 0.004, 0.004, segs=6, mat_idx=M_AL)

    obj_mon = finalize_multimat_mesh("TechStop_MonitorsTools", bm_mon, mon_mats, skip_uv_mats=(M_SC,))

    # -----------------------------------------------------------------------
    # 4. Signature Overhead Google TechStop Arch Canopy (Z = 2.05m .. 2.45m)
    # -----------------------------------------------------------------------
    can_mats = [mat_steel, mat_white, mat_canopy_blue, mat_sign, mat_downlight, mat_gblue, mat_gred, mat_gyel, mat_ggrn, mat_led_blue]
    C_ST, C_WH, C_CB, C_SG, C_DL, C_B, C_R, C_Y, C_G, C_LD = range(10)
    bm_can = bmesh.new()

    # Twin clean brushed-steel rear support columns (x = ±1.06, y = -0.34, Z = 0.000 .. 2.12m)
    # gracefully cantilevering forward into the overhead canopy!
    for sgn in (-1.0, 1.0):
        cx = sgn * 1.06
        # Ground base anchor flange (grounded at Z = 0.000!)
        bm_add_rounded_rect_prism(bm_can, cx, -0.34, w=0.20, d=0.22, r_corner=0.05, z0=0.000, z1=0.050, corner_segs=4, mat_idx=C_ST)
        # Desk pass-through brushed steel collar
        bm_add_rounded_rect_prism(bm_can, cx, -0.34, w=0.15, d=0.17, r_corner=0.04, z0=0.978, z1=1.015, corner_segs=4, mat_idx=C_ST)
        # Main vertical + curved cantilevered steel arch leg
        col_pts = [
            (cx, -0.34, 0.045),
            (cx, -0.34, 1.62),
            (cx, -0.31, 1.92),
            (cx, -0.22, 2.08),
            (cx, -0.06, 2.15),
        ]
        bm_add_spline_tube(bm_can, col_pts, [0.052, 0.050, 0.048, 0.048, 0.046], segs=12, mat_idx=C_ST)
        # Subtle glowing Google Blue outer accent inlay channel on each column
        bm_add_box(bm_can, (cx + sgn * 0.050, -0.34, 1.48), (0.008, 0.020, 0.88), mat_idx=C_LD)

    # Overhead Sculpted Canopy Shell (Z = 2.05 .. 2.45m, W = 2.50m, D = 0.84m, centered y = -0.02)
    # Matte white architectural canopy body with softly rounded ends
    bm_add_rounded_rect_prism(
        bm_can,
        0.0,
        -0.02,
        w=2.50,
        d=0.84,
        r_corner=0.20,
        z0=2.050,
        z1=2.450,
        corner_segs=6,
        bevel_top=0.022,
        mat_idx=C_WH,
        smooth=False,
    )
    # Deep Google Blue recessed fascia band wrapping mid-section of canopy (Z = 2.098 .. 2.392)
    bm_add_rounded_rect_prism(
        bm_can,
        0.0,
        -0.02,
        w=2.516,
        d=0.854,
        r_corner=0.205,
        z0=2.098,
        z1=2.392,
        corner_segs=6,
        mat_idx=C_CB,
        smooth=False,
    )

    # Signature 4-Color Google Accent Bar along BOTH front & back top crown & lower lip of canopy!
    bar_w = 2.04
    seg_w = bar_w / 4.0
    # Ordered left-to-right as seen from the front (+Y -> left is +X, right is -X!):
    # Blue, Red, Yellow, Green from +X to -X!
    g_mats = [C_B, C_R, C_Y, C_G]
    for i, gmi in enumerate(g_mats):
        # Front (+Y): left=+X -> right=-X
        x_f = (bar_w * 0.5) - (i + 0.5) * seg_w
        bm_add_box(bm_can, (x_f, +0.410, 2.408), (seg_w - 0.006, 0.018, 0.026), mat_idx=gmi)
        bm_add_box(bm_can, (x_f, +0.410, 2.082), (seg_w - 0.006, 0.018, 0.022), mat_idx=gmi)
        # Back (-Y): left=-X -> right=+X
        x_b = -(bar_w * 0.5) + (i + 0.5) * seg_w
        bm_add_box(bm_can, (x_b, -0.450, 2.408), (seg_w - 0.006, 0.018, 0.026), mat_idx=gmi)
        bm_add_box(bm_can, (x_b, -0.450, 2.082), (seg_w - 0.006, 0.018, 0.022), mat_idx=gmi)

    # Crisp Dual-Sided Illuminated "TECHSTOP" Canopy Signs (512x128 aspect-matched SDF texture!)
    sign_z = 2.245
    # Front (+Y) facing approaching players (viewer_right = -X so text reads left-to-right!)
    bm_add_textured_quad(
        bm_can,
        center=(0.0, +0.415, sign_z),
        viewer_right=(-1.0, 0.0, 0.0),
        up_vec=(0.0, 0.0, 1.0),
        width=sign_w,
        height=sign_h,
        mat_idx=C_SG,
    )
    # Back (-Y) legible from behind (viewer_right = +X!)
    bm_add_textured_quad(
        bm_can,
        center=(0.0, -0.455, sign_z),
        viewer_right=(+1.0, 0.0, 0.0),
        up_vec=(0.0, 0.0, 1.0),
        width=sign_w,
        height=sign_h,
        mat_idx=C_SG,
    )

    # Under-canopy recessed LED worklight panels illuminating the counter & upgrade pad
    for lx in (-0.72, 0.0, +0.72):
        bm_add_box(bm_can, (lx, +0.02, 2.048), (0.46, 0.22, 0.010), bevel=0.002, mat_idx=C_DL)

    obj_canopy = finalize_multimat_mesh("TechStop_Canopy", bm_can, can_mats, skip_uv_mats=(C_SG,))

    bpy.context.view_layer.update()
    export_objs = [obj_desk, obj_pad, obj_icon, obj_mon, obj_canopy]
    return export_selected_glb("prop_techstop_kiosk.glb", export_objs)


# ---------------------------------------------------------------------------
# Export & GLB Binary/JSON Structural Auditor
# ---------------------------------------------------------------------------
def parse_glb_json(glb_path):
    """Read and parse the JSON chunk of a binary .glb file."""
    with open(glb_path, "rb") as f:
        magic, version, length = struct.unpack("<4sII", f.read(12))
        assert magic == b"glTF", f"Invalid GLB magic: {magic}"
        chunk_len, chunk_type = struct.unpack("<I4s", f.read(8))
        assert chunk_type == b"JSON", f"Expected JSON chunk, got {chunk_type}"
        return json.loads(f.read(chunk_len).decode("utf-8"))


def compute_scene_bounds(objs):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    min_co = Vector((1e9, 1e9, 1e9))
    max_co = Vector((-1e9, -1e9, -1e9))
    total_tris = 0
    for obj in objs:
        if obj.type != "MESH":
            continue
        eo = obj.evaluated_get(depsgraph)
        me = eo.to_mesh()
        try:
            m = eo.matrix_world
            for v in me.vertices:
                w = m @ v.co
                min_co.x = min(min_co.x, w.x)
                min_co.y = min(min_co.y, w.y)
                min_co.z = min(min_co.z, w.z)
                max_co.x = max(max_co.x, w.x)
                max_co.y = max(max_co.y, w.y)
                max_co.z = max(max_co.z, w.z)
            for p in me.polygons:
                total_tris += max(1, len(p.vertices) - 2)
        finally:
            eo.to_mesh_clear()
    return min_co, max_co, total_tris


def export_selected_glb(filename, objs):
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

    size_bytes = os.path.getsize(out_path)
    size_kb = size_bytes / 1024.0
    gltf = parse_glb_json(out_path)
    exts = gltf.get("extensionsUsed", [])
    has_draco = any("draco" in e.lower() for e in exts)
    if has_draco:
        raise RuntimeError(f"{filename} unexpectedly contains Draco compression: {exts}")
    if size_kb >= 600.0:
        raise RuntimeError(f"{filename} exceeds 600 KB limit ({size_kb:.1f} KB)")

    # Re-import GLB into a clean scene to verify true exported world bounds & node hierarchy!
    reset_scene()
    bpy.ops.import_scene.gltf(filepath=str(out_path))
    imported = list(bpy.context.scene.objects)
    min_co, max_co, tris = compute_scene_bounds(imported)

    if abs(min_co.z) > 0.002:
        raise RuntimeError(f"{filename} grounding check failed: minZ = {min_co.z:.5f}m (expected 0.000m)")

    # Extract exact glTF node tree (Three.js Y-up local translations!)
    nodes_info = []
    nodes = gltf.get("nodes", [])
    parent_map = {}
    for idx, nd in enumerate(nodes):
        for ch in nd.get("children", []):
            parent_map[ch] = nd.get("name", f"node_{idx}")
    for idx, nd in enumerate(nodes):
        tr = nd.get("translation", [0.0, 0.0, 0.0])
        nodes_info.append({
            "name": nd.get("name", f"node_{idx}"),
            "parent": parent_map.get(idx, None),
            "three_local": [round(float(v), 4) for v in tr],
            "has_mesh": "mesh" in nd,
        })

    mats_exported = [m.get("name", "") for m in gltf.get("materials", [])]

    return {
        "file": filename,
        "path": str(out_path),
        "kb": size_kb,
        "tris": tris,
        "draco": has_draco,
        "blender_min": [round(float(min_co.x), 4), round(float(min_co.y), 4), round(float(min_co.z), 4)],
        "blender_max": [round(float(max_co.x), 4), round(float(max_co.y), 4), round(float(max_co.z), 4)],
        "blender_dims": [
            round(float(max_co.x - min_co.x), 4),
            round(float(max_co.y - min_co.y), 4),
            round(float(max_co.z - min_co.z), 4),
        ],
        "three_dims": [
            round(float(max_co.x - min_co.x), 4),
            round(float(max_co.z - min_co.z), 4),
            round(float(max_co.y - min_co.y), 4),
        ],
        "nodes": nodes_info,
        "materials": mats_exported,
    }


# ---------------------------------------------------------------------------
# 2-Panel Studio BLENDER_EEVEE Visual QA Preview Renderer
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
    "9": ["01110", "10001", "10001", "01111", "00001", "00001", "01110"],
    " ": ["00000", "00000", "00000", "00000", "00000", "00000", "00000"],
    ".": ["00000", "00000", "00000", "00000", "00000", "00000", "00100"],
    "-": ["00000", "00000", "00000", "11111", "00000", "00000", "00000"],
    "/": ["00001", "00010", "00010", "00100", "01000", "01000", "10000"],
    "(": ["00010", "00100", "01000", "01000", "01000", "00100", "00010"],
    ")": ["01000", "00100", "00010", "00010", "00010", "00100", "01000"],
    "|": ["00100", "00100", "00100", "00100", "00100", "00100", "00100"],
    ":": ["00000", "00100", "00000", "00000", "00000", "00100", "00000"],
    "=": ["00000", "00000", "11111", "00000", "11111", "00000", "00000"],
    "+": ["00000", "00100", "00100", "11111", "00100", "00100", "00000"],
    "<": ["00010", "00100", "01000", "10000", "01000", "00100", "00010"],
    ">": ["01000", "00100", "00010", "00001", "00010", "00100", "01000"],
    ",": ["00000", "00000", "00000", "00000", "00100", "00100", "01000"],
}


def draw_label(canvas, text, x, y, scale=2, color=(1.0, 1.0, 1.0, 1.0)):
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
                    if 0 <= y0 < h and 0 <= x0 < w:
                        canvas[y0:y1, x0:x1] = color
        cx += 6 * scale


def load_png_topdown(path):
    img = bpy.data.images.load(str(path), check_existing=False)
    w, h = img.size
    buf = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(buf)
    bpy.data.images.remove(img)
    return buf.reshape((h, w, 4))[::-1].copy()


def save_png_topdown(canvas, out_path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    h, w, _ = canvas.shape
    img = bpy.data.images.new(f"QA_{out_path.stem}", width=w, height=h, alpha=True)
    flipped = np.ascontiguousarray(np.clip(canvas[::-1], 0.0, 1.0), dtype=np.float32)
    img.pixels.foreach_set(flipped.ravel())
    img.filepath_raw = str(out_path)
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)


def look_at(obj, target):
    direction = target - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def configure_studio_eevee(samples=24, res_x=800, res_y=680):
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
    scene.view_settings.exposure = 0.08


def setup_studio_world():
    scene = bpy.context.scene
    world = scene.world or bpy.data.worlds.new("StudioWorld")
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
    ramp.color_ramp.elements[0].color = (0.16, 0.21, 0.29, 1.0)
    ramp.color_ramp.elements[1].position = 0.60
    ramp.color_ramp.elements[1].color = (0.34, 0.48, 0.68, 1.0)
    nt.links.new(texcoord.outputs["Generated"], sep.inputs["Vector"])
    nt.links.new(sep.outputs["Z"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = 0.78
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])


def build_studio_rig(bmin, bmax, azim_deg, elev_deg, fov_deg=32.0, fill_ratio=0.80):
    scene = bpy.context.scene
    center = 0.5 * (bmin + bmax)
    dims = bmax - bmin
    radius = max(0.6, 0.5 * dims.length)

    # Clean matte architectural concrete-slate studio cyclorama floor at exact Z = 0.000
    bpy.ops.mesh.primitive_circle_add(vertices=64, radius=max(radius * 8.0, 12.0), fill_type="NGON", location=(center.x, center.y, 0.0))
    floor = bpy.context.active_object
    floor.name = "QA_StudioFloor"
    mat_f = bpy.data.materials.new("QA_FloorMat")
    bsdf = mat_f.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = hex_to_linear("#354052")
    bsdf.inputs["Roughness"].default_value = 0.72
    floor.data.materials.append(mat_f)

    # Camera framing: azim_deg = 0 looks from +Y (front!) toward origin!
    az = math.radians(azim_deg)
    el = math.radians(elev_deg)
    cam_dir = Vector((math.sin(az) * math.cos(el), math.cos(az) * math.cos(el), math.sin(el))).normalized()
    world_up = Vector((0.0, 0.0, 1.0))
    right = world_up.cross(cam_dir)
    right = Vector((1.0, 0.0, 0.0)) if right.length < 1e-4 else right.normalized()
    up = cam_dir.cross(right).normalized()

    corners = [
        Vector((x, y, z)) - center
        for x in (bmin.x, bmax.x)
        for y in (bmin.y, bmax.y)
        for z in (bmin.z, bmax.z)
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
    cam_data.clip_start = 0.05
    cam_data.clip_end = 200.0
    cam_obj = bpy.data.objects.new("QA_Camera", cam_data)
    scene.collection.objects.link(cam_obj)
    cam_obj.location = center + cam_dir * cam_dist
    look_at(cam_obj, center)
    scene.camera = cam_obj

    # 3-point crisp studio lighting (warm key, cool fill, crisp rim)
    def add_sun(name, az_off, el_d, energy, color, angle_deg):
        ld = bpy.data.lights.new(name, type="SUN")
        ld.energy = energy
        ld.color = color
        ld.angle = math.radians(angle_deg)
        lo = bpy.data.objects.new(name, ld)
        scene.collection.objects.link(lo)
        a = math.radians(azim_deg + az_off)
        e = math.radians(el_d)
        lo.location = center + Vector((math.sin(a) * math.cos(e), math.cos(a) * math.cos(e), math.sin(e))) * (radius * 3.0)
        look_at(lo, center)

    add_sun("QA_KeySun", 34.0, 38.0, 3.2, (1.0, 0.96, 0.90), 3.0)
    add_sun("QA_FillSun", -54.0, 26.0, 1.35, (0.82, 0.91, 1.0), 16.0)
    add_sun("QA_RimSun", 155.0, 30.0, 1.15, (1.0, 0.97, 0.92), 10.0)


def render_qa_preview(results, out_path=QA_PREVIEW_PATH, samples=24):
    panel_w, panel_h = 800, 680
    hdr_h = 58
    pad = 16
    title_h = 50
    sheet_w = 2 * panel_w + 3 * pad
    sheet_h = title_h + hdr_h + panel_h + 2 * pad

    canvas = np.zeros((sheet_h, sheet_w, 4), dtype=np.float32)
    canvas[:, :] = (0.068, 0.085, 0.115, 1.0)

    total_kb = sum(r["kb"] for r in results)
    total_tris = sum(r["tris"] for r in results)
    draw_label(
        canvas,
        f"WORKSPACE ROYALE GAMEPLAY PROPS - EEVEE QA ({total_kb:.1f}KB TOTAL | {total_tris:,} TRIS | ZERO DRACO)",
        pad,
        16,
        scale=2,
        color=(0.95, 0.97, 1.0, 1.0),
    )

    # azim_deg = 0 is directly in front (+Y); +38..+44 deg shows crisp 3/4 front-right view!
    panel_specs = [
        ("prop_gbike_rideable.glb", "1. RIDEABLE GOOGLE GBIKE (3/4 FRONT)", hex_to_srgb(G_BLUE), 50.0, 16.0, 0.80),
        ("prop_techstop_kiosk.glb", "2. GOOGLE TECHSTOP UPGRADE KIOSK (3/4 FRONT)", hex_to_srgb(G_GREEN), 28.0, 16.5, 0.80),
    ]
    res_map = {r["file"]: r for r in results}

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_png = Path(tmpdir) / "panel.png"
        for idx, (fname, title, accent, azim, elev, fill_r) in enumerate(panel_specs):
            px0 = pad + idx * (panel_w + pad)
            py0 = title_h + pad

            reset_scene()
            configure_studio_eevee(samples=samples, res_x=panel_w, res_y=panel_h)
            setup_studio_world()
            bpy.ops.import_scene.gltf(filepath=str(OUT_DIR / fname))
            imported = list(bpy.context.scene.objects)
            bmin, bmax, _ = compute_scene_bounds(imported)
            build_studio_rig(bmin, bmax, azim_deg=azim, elev_deg=elev, fov_deg=32.0, fill_ratio=fill_r)

            bpy.context.scene.render.filepath = str(tmp_png)
            bpy.ops.render.render(write_still=True)
            img_arr = load_png_topdown(tmp_png)

            # Header bar + Google accent stripe
            canvas[py0:py0 + hdr_h, px0:px0 + panel_w] = (0.105, 0.130, 0.175, 1.0)
            canvas[py0:py0 + hdr_h, px0:px0 + 7] = (accent[0], accent[1], accent[2], 1.0)
            info = res_map[fname]
            td = info["three_dims"]
            draw_label(canvas, title, px0 + 18, py0 + 9, scale=2, color=(0.97, 0.985, 1.0, 1.0))
            stat = (
                f"{info['kb']:.1f}KB (<600KB) | {info['tris']} TRIS | "
                f"3JS {td[0]:.2f}W X {td[1]:.2f}H X {td[2]:.2f}D M | MINZ={info['blender_min'][2]:.3f}M | PASS"
            )
            draw_label(canvas, stat, px0 + 18, py0 + 35, scale=1, color=(0.66, 0.90, 0.76, 1.0))
            canvas[py0 + hdr_h:py0 + hdr_h + panel_h, px0:px0 + panel_w] = img_arr

    save_png_topdown(canvas, out_path)
    print(f"[QA PREVIEW] Saved 2-panel studio EEVEE preview -> {out_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    t0 = time.time()
    results = []
    for builder in (build_gbike_rideable, build_techstop_kiosk):
        ts = time.time()
        info = builder()
        info["sec"] = time.time() - ts
        results.append(info)

        print("=" * 96)
        print(
            f"[OK] {info['file']:26s} | {info['kb']:6.1f} KB (<600KB) | "
            f"{info['tris']:5d} tris | draco={info['draco']} | {info['sec']:.2f}s"
        )
        print(
            f"     Blender BBox: min={info['blender_min']} max={info['blender_max']} "
            f"dims={info['blender_dims']}"
        )
        print(
            f"     ThreeJS Dims (W x H x D): {info['three_dims'][0]:.4f}m x "
            f"{info['three_dims'][1]:.4f}m x {info['three_dims'][2]:.4f}m"
        )
        print(f"     Materials ({len(info['materials'])}): {', '.join(info['materials'])}")
        print("     glTF Nodes (Three.js Y-up local translation):")
        for nd in info["nodes"]:
            p_str = f" (parent={nd['parent']})" if nd["parent"] else " (root)"
            kind = "MESH" if nd["has_mesh"] else "EMPTY"
            print(f"       - {nd['name']:24s} [{kind:5s}]{p_str:30s} local={nd['three_local']}")

    print("=" * 96)
    render_qa_preview(results, out_path=QA_PREVIEW_PATH, samples=24)
    print(f"[DONE] Built & verified 2 gameplay GLBs + EEVEE QA preview in {time.time() - t0:.2f}s")


if __name__ == "__main__":
    main()

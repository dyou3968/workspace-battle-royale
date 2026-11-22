"""
Workspace Royale — High-Fidelity Rigged & Animated Embodied Google Workspace Product Icon AI Generator (Blender 5.3.0)
Generates all 6 playable Embodied Google Workspace Product Icon AIs as self-contained glTF 2.0 (.glb) assets:
  1. public/assets/characters/hero_gmail.glb     (Gmail AI    — 3D Sculpted Rounded Envelope & 4-Color M Arch)
  2. public/assets/characters/hero_drive.glb     (Drive AI    — 3D Interlocking Equilateral Tri-Color Triangle Prism)
  3. public/assets/characters/hero_calendar.glb  (Calendar AI — 3D 4-Color Framed Tile & Crisp '31' Face)
  4. public/assets/characters/hero_chat.glb      (Chat AI     — 3D Layered Dual Emerald Speech Bubbles & Typing Optics)
  5. public/assets/characters/hero_slides.glb    (Slides AI   — 3D Golden-Amber Dog-Eared Deck & 16:9 Visor Screen)
  6. public/assets/characters/hero_docs.glb      (Docs AI     — 3D Cobalt-Blue Dog-Eared Page & Raised White Text Bars)

Blender 5.3.0 Verified Pipeline (Pixar / Astro-Bot / Portal Caliber):
  - Sculpted 3D product icon chassis with smooth rounded fillets, multi-step bevels, weighted normals, and glossy
    ceramic / anodized PBR finishes (Y thickness strictly <= +/-0.130m so chest-carried rifles NEVER clip!)
  - Curved dark-glass AI optical visor with custom 512x512 razor-sharp self-lit Pixar/Astro-Bot eyes per product
  - Crisp procedural chassis detail texture (2 embedded textures per GLB, total 6 GLBs ~3.2 MB <= 5.0 MB)
  - Sleek segmented ceramic & anodized-titanium articulated AI arms, ergonomic gripping hands, glowing knee rings,
    and futuristic sneaker-boots grounded strictly at Z = 0.000m (height ~1.75–1.80m, 4,500–6,100 tris each)
  - Full 18-bone Armature + Hand_R bone-parented WeaponSocket_R Empty (+90° X glTF convention preserved 1:1)
  - 13 baked NLA animation actions:
      Unarmed: Idle, Run, Sprint, Glide, Jump
      Armed (Analytic 2-Bone Arm IK): IdleArmed, RunArmed, SprintArmed, Crouch, Aim, Reload, JumpArmed
      Bespoke Per-Hero Lobby Turntable Loop: LobbyShowcase (6 completely distinct hero-specific loops!)
  - Facing +Y in Blender, hero right side +X, feet strictly grounded at Z = 0.000
"""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = PROJECT_ROOT / "public" / "assets" / "characters"
WEAPONS_DIR = PROJECT_ROOT / "public" / "assets" / "weapons"


# =============================================================================
# 1. COLOR & ANTI-ALIASED NUMPY SDF PRIMITIVES
# =============================================================================

def hex_to_rgba(hex_str: str, alpha: float = 1.0) -> Tuple[float, float, float, float]:
    h = hex_str.lstrip("#")
    return (
        int(h[0:2], 16) / 255.0,
        int(h[2:4], 16) / 255.0,
        int(h[4:6], 16) / 255.0,
        alpha,
    )


def srgb_to_linear_rgb(c: Sequence[float]) -> Tuple[float, float, float]:
    out = []
    for ch in c[:3]:
        if ch <= 0.04045:
            out.append(ch / 12.92)
        else:
            out.append(((ch + 0.055) / 1.055) ** 2.4)
    return (out[0], out[1], out[2])


def hex_to_linear(hex_str: str, alpha: float = 1.0) -> Tuple[float, float, float, float]:
    r, g, b, _ = hex_to_rgba(hex_str, alpha)
    lr, lg, lb = srgb_to_linear_rgb((r, g, b))
    return (lr, lg, lb, alpha)


def smoothstep(edge0: float, edge1: float, x: np.ndarray) -> np.ndarray:
    denom = edge1 - edge0
    if abs(denom) < 1e-8:
        denom = 1e-8 if denom >= 0.0 else -1e-8
    t = np.clip((x - edge0) / denom, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def alpha_blend(canvas: np.ndarray, color_rgb: Tuple[float, float, float], mask: np.ndarray) -> None:
    m = np.clip(mask, 0.0, 1.0)[..., None]
    col = np.array(color_rgb, dtype=np.float32)[None, None, :]
    canvas[..., :3] = canvas[..., :3] * (1.0 - m) + col * m


def additive_glow(canvas: np.ndarray, color_rgb: Tuple[float, float, float], weight: np.ndarray) -> None:
    w = np.clip(weight, 0.0, 2.0)[..., None]
    col = np.array(color_rgb, dtype=np.float32)[None, None, :]
    canvas[..., :3] = np.clip(canvas[..., :3] + col * w, 0.0, 1.0)


def sd_box(px: np.ndarray, py: np.ndarray, bx: float, by: float, r: float = 0.0) -> np.ndarray:
    qx = np.abs(px) - bx + r
    qy = np.abs(py) - by + r
    outside = np.hypot(np.maximum(qx, 0.0), np.maximum(qy, 0.0))
    inside = np.minimum(np.maximum(qx, qy), 0.0)
    return outside + inside - r


def sd_segment(
    px: np.ndarray,
    py: np.ndarray,
    ax: float,
    ay: float,
    bx: float,
    by: float,
) -> np.ndarray:
    pax = px - ax
    pay = py - ay
    bax = bx - ax
    bay = by - ay
    denom = max(bax * bax + bay * bay, 1e-8)
    h = np.clip((pax * bax + pay * bay) / denom, 0.0, 1.0)
    return np.hypot(pax - bax * h, pay - bay * h)


def sd_circle(px: np.ndarray, py: np.ndarray, cx: float, cy: float, r: float) -> np.ndarray:
    return np.hypot(px - cx, py - cy) - r


def sd_ellipse(px: np.ndarray, py: np.ndarray, cx: float, cy: float, rx: float, ry: float) -> np.ndarray:
    nx = (px - cx) / max(rx, 1e-6)
    ny = (py - cy) / max(ry, 1e-6)
    return (np.hypot(nx, ny) - 1.0) * min(rx, ry)


def sd_triangle(
    px: np.ndarray,
    py: np.ndarray,
    ax: float,
    ay: float,
    bx: float,
    by: float,
    cx: float,
    cy: float,
) -> np.ndarray:
    e0x, e0y = bx - ax, by - ay
    e1x, e1y = cx - bx, cy - by
    e2x, e2y = ax - cx, ay - cy

    v0x, v0y = px - ax, py - ay
    v1x, v1y = px - bx, py - by
    v2x, v2y = px - cx, py - cy

    pq0x = v0x - e0x * np.clip((v0x * e0x + v0y * e0y) / max(e0x * e0x + e0y * e0y, 1e-8), 0.0, 1.0)
    pq0y = v0y - e0y * np.clip((v0x * e0x + v0y * e0y) / max(e0x * e0x + e0y * e0y, 1e-8), 0.0, 1.0)
    pq1x = v1x - e1x * np.clip((v1x * e1x + v1y * e1y) / max(e1x * e1x + e1y * e1y, 1e-8), 0.0, 1.0)
    pq1y = v1y - e1y * np.clip((v1x * e1x + v1y * e1y) / max(e1x * e1x + e1y * e1y, 1e-8), 0.0, 1.0)
    pq2x = v2x - e2x * np.clip((v2x * e2x + v2y * e2y) / max(e2x * e2x + e2y * e2y, 1e-8), 0.0, 1.0)
    pq2y = v2y - e2y * np.clip((v2x * e2x + v2y * e2y) / max(e2x * e2x + e2y * e2y, 1e-8), 0.0, 1.0)

    s = 1.0 if (e0x * e2y - e0y * e2x) >= 0.0 else -1.0
    d0 = pq0x * pq0x + pq0y * pq0y
    d1 = pq1x * pq1x + pq1y * pq1y
    d2 = pq2x * pq2x + pq2y * pq2y
    c0 = s * (v0x * e0y - v0y * e0x)
    c1 = s * (v1x * e1y - v1y * e1x)
    c2 = s * (v2x * e2y - v2y * e2x)

    d_min = np.minimum(np.minimum(d0, d1), d2)
    c_min = np.minimum(np.minimum(c0, c1), c2)
    return -np.sqrt(d_min) * np.sign(c_min)


def make_blender_image_from_srgb_array(name: str, arr_srgb: np.ndarray) -> bpy.types.Image:
    h, w, _ = arr_srgb.shape
    img = bpy.data.images.new(name=name, width=w, height=h, alpha=True, float_buffer=False)
    img.colorspace_settings.name = "sRGB"
    flat = np.ascontiguousarray(np.clip(arr_srgb, 0.0, 1.0), dtype=np.float32).ravel()
    img.pixels.foreach_set(flat)
    img.pack()
    return img


# =============================================================================
# 2. PROCEDURAL AI OPTICAL VISOR & CHASSIS GRAPHIC TEXTURES (2 PER HERO)
# =============================================================================

def generate_ai_visor_texture(cfg: dict) -> bpy.types.Image:
    """
    512x512 Pixar / Astro-Bot caliber curved dark-glass AI optical visor texture.
    Deep glossy obsidian OLED glass with crisp, expressive, high-definition glowing AI eyes
    (tight clean glow halos so eyes stay razor-sharp, charismatic, never hazy!).
    UV convention: U=0 -> viewer LEFT (+X), U=1 -> viewer RIGHT (-X), V=0 -> bottom, V=1 -> top.
    """
    W, H = 512, 512
    u = np.linspace(0.0, 1.0, W, dtype=np.float32)[None, :]
    v = np.linspace(0.0, 1.0, H, dtype=np.float32)[:, None]
    u_grid = np.broadcast_to(u, (H, W))
    v_grid = np.broadcast_to(v, (H, W))

    lx = (u_grid - 0.5) * 2.0
    ly = (v_grid - 0.5) * 2.0

    canvas = np.ones((H, W, 4), dtype=np.float32)
    canvas[..., 0] = 0.010
    canvas[..., 1] = 0.015
    canvas[..., 2] = 0.025

    prod = cfg["product"]
    glow_rgb = hex_to_rgba(cfg["visor_glow"])[:3]
    core_rgb = hex_to_rgba(cfg["visor_core"])[:3]

    # Subtle curved OLED horizontal scanlines + delicate rim glow & top glass sheen
    scan = 0.92 + 0.08 * np.sin(v_grid * 104.0 * math.pi)
    rim_box = sd_box(lx, ly, 0.92, 0.86, 0.22)
    rim_glow = np.exp(-((np.abs(rim_box) / 0.055) ** 2)) * 0.14
    additive_glow(canvas, glow_rgb, rim_glow * (rim_box < 0.05).astype(np.float32))
    refl = smoothstep(0.60, 0.94, ly + 0.10 * (1.0 - lx * lx)) * smoothstep(0.95, 0.72, np.abs(lx)) * 0.05
    additive_glow(canvas, (0.72, 0.88, 1.0), refl)

    def paint_crisp_eye(d_shape: np.ndarray, ex: np.ndarray, ey: np.ndarray, catch_off: Tuple[float, float] = (-0.048, 0.095)) -> None:
        halo = np.exp(-((np.maximum(d_shape, 0.0) / 0.085) ** 2)) * 0.42
        additive_glow(canvas, glow_rgb, halo)
        alpha_blend(canvas, glow_rgb, smoothstep(0.018, -0.008, d_shape))
        alpha_blend(canvas, core_rgb, smoothstep(-0.012, -0.052, d_shape))
        # Subtle dark inner optical accent ring + crisp pure-white catchlight
        d_c1 = sd_circle(ex, ey, catch_off[0], catch_off[1], 0.036)
        alpha_blend(canvas, (1.0, 1.0, 1.0), smoothstep(0.012, -0.006, d_c1))

    if prod == "gmail":
        # Confident, cheerful arched almond AI eyes + cute crisp chevron smile
        eye_x, eye_y = 0.37, 0.06
        for side in (-1.0, 1.0):
            ex, ey = lx - side * eye_x, ly - eye_y
            ang = 0.10 * side
            rx = ex * math.cos(ang) + ey * math.sin(ang)
            ry = -ex * math.sin(ang) + ey * math.cos(ang)
            d_eye = sd_ellipse(rx, ry, 0.0, 0.0, 0.20, 0.27)
            d_cut = sd_circle(ex, ey, 0.0, -0.42, 0.28)
            paint_crisp_eye(np.maximum(d_eye, -d_cut), ex, ey, (-0.052, 0.095))

        d_ch = np.minimum(
            sd_segment(lx, ly, -0.10, -0.44, 0.0, -0.53) - 0.018,
            sd_segment(lx, ly,  0.10, -0.44, 0.0, -0.53) - 0.018,
        )
        additive_glow(canvas, glow_rgb, np.exp(-((np.maximum(d_ch, 0.0) / 0.05) ** 2)) * 0.35)
        alpha_blend(canvas, core_rgb, smoothstep(0.010, -0.006, d_ch))

    elif prod == "drive":
        # Bold crisp cyan-emerald geometric capsule eyes centered cleanly in the wide equilateral Drive aperture!
        eye_x, eye_y = 0.27, -0.18
        for side in (-1.0, 1.0):
            ex, ey = lx - side * eye_x, ly - eye_y
            d_cap = sd_box(ex, ey, 0.145, 0.205, 0.105)
            brow_cut = ey - (0.175 - 0.13 * (-side * ex))
            paint_crisp_eye(np.maximum(d_cap, brow_cut), ex, ey, (-0.042, 0.072))

        # Crisp miniature Drive apex triangle core accent above eyes
        d_mini = np.abs(sd_triangle(lx, ly, 0.0, 0.44, -0.12, 0.22, 0.12, 0.22)) - 0.015
        additive_glow(canvas, glow_rgb, np.exp(-((np.maximum(d_mini, 0.0) / 0.05) ** 2)) * 0.40)
        alpha_blend(canvas, core_rgb, smoothstep(0.010, -0.006, d_mini))

    elif prod == "calendar":
        # Crisp energetic sky-cyan happy arched AI eyes + side chrono tick indicators
        eye_x, eye_y = 0.36, 0.02
        for side in (-1.0, 1.0):
            ex, ey = lx - side * eye_x, ly - eye_y
            d_oval = sd_ellipse(ex, ey, 0.0, 0.0, 0.175, 0.35)
            d_smile = sd_circle(ex, ey, 0.0, -0.48, 0.34)
            paint_crisp_eye(np.maximum(d_oval, -d_smile), ex, ey, (-0.045, 0.12))

        for side in (-1.0, 1.0):
            for ty in (-0.18, 0.02, 0.22):
                d_tk = sd_box(lx - side * 0.76, ly - ty, 0.044, 0.024, 0.012)
                alpha_blend(canvas, glow_rgb, smoothstep(0.010, -0.005, d_tk) * 0.85)

    elif prod == "chat":
        # Super crisp playful mint-white arched AI eyes + 3 iconic glowing Chat typing dots ('• • •')!
        eye_x, eye_y = 0.36, 0.18
        for side in (-1.0, 1.0):
            ex, ey = lx - side * eye_x, ly - eye_y
            d_outer = sd_ellipse(ex, ey, 0.0, 0.0, 0.185, 0.255)
            d_inner = sd_circle(ex, ey, 0.0, -0.32, 0.225)
            paint_crisp_eye(np.maximum(d_outer, -d_inner), ex, ey, (-0.048, 0.085))

        for dx, rad in ((-0.25, 0.068), (0.0, 0.082), (0.25, 0.068)):
            d_dot = sd_circle(lx, ly, dx, -0.40, rad)
            additive_glow(canvas, glow_rgb, np.exp(-((np.maximum(d_dot, 0.0) / 0.065) ** 2)) * 0.45)
            alpha_blend(canvas, glow_rgb, smoothstep(0.016, -0.008, d_dot))
            alpha_blend(canvas, core_rgb, smoothstep(-0.008, -0.036, d_dot))

    elif prod == "slides":
        # Focused golden-amber 16:9 optics + delicate right-eye precision reticle + slide deck dots
        eye_x, eye_y = 0.35, 0.08
        for side in (-1.0, 1.0):
            ex, ey = lx - side * eye_x, ly - eye_y
            d_eye = sd_box(ex, ey, 0.165, 0.225, 0.125)
            brow_cut = ey - (0.195 - 0.10 * (-side * ex))
            paint_crisp_eye(np.maximum(d_eye, brow_cut), ex, ey, (-0.044, 0.082))

        d_ret = np.abs(sd_circle(lx, ly, eye_x, eye_y, 0.285)) - 0.011
        ret_mask = smoothstep(0.010, -0.005, d_ret) * (np.abs(lx - eye_x) > 0.13).astype(np.float32)
        alpha_blend(canvas, glow_rgb, ret_mask * 0.80)

        for dx, rad in ((-0.16, 0.028), (0.0, 0.040), (0.16, 0.028)):
            d_p = sd_circle(lx, ly, dx, -0.50, rad)
            alpha_blend(canvas, core_rgb if rad > 0.032 else glow_rgb, smoothstep(0.010, -0.005, d_p) * 0.90)

    elif prod == "docs":
        # Smart friendly sky-blue rounded AI eyes + crisp glowing blue text-cursor pipe '|'
        eye_x, eye_y = 0.35, 0.04
        for side in (-1.0, 1.0):
            ex, ey = lx - side * eye_x, ly - eye_y
            d_eye = sd_box(ex, ey, 0.165, 0.260, 0.130)
            d_cut = sd_circle(ex, ey, 0.0, -0.45, 0.285)
            paint_crisp_eye(np.maximum(d_eye, -d_cut), ex, ey, (-0.044, 0.095))

        d_cur = sd_box(lx - 0.74, ly - 0.04, 0.022, 0.24, 0.010)
        additive_glow(canvas, glow_rgb, np.exp(-((np.maximum(d_cur, 0.0) / 0.055) ** 2)) * 0.42)
        alpha_blend(canvas, core_rgb, smoothstep(0.010, -0.005, d_cur) * 0.94)

    canvas[..., :3] = np.clip(canvas[..., :3] * scan[..., None], 0.0, 1.0)
    return make_blender_image_from_srgb_array(f"{cfg['id']}_VisorTex", canvas)


def _draw_calendar_31(canvas: np.ndarray, lx: np.ndarray, ly: np.ndarray, blue_rgb: Tuple[float, float, float]) -> None:
    """Draws razor-sharp Google Calendar bold '31' numeral centered in lx, ly in [-1, 1]."""
    aa = 0.014
    st = 0.100
    c3x = -0.25
    d_3_up = np.abs(np.hypot(lx - c3x, ly - 0.215) - 0.205) - st
    m_3_up = smoothstep(aa, -aa, d_3_up) * ((lx > c3x - 0.15) | (ly > 0.26)).astype(np.float32)
    d_3_lo = np.abs(np.hypot(lx - c3x, ly + 0.225) - 0.220) - st
    m_3_lo = smoothstep(aa, -aa, d_3_lo) * ((lx > c3x - 0.16) | (ly < -0.26)).astype(np.float32)
    open_3 = 1.0 - smoothstep(aa, -aa, sd_box(lx - (c3x - 0.21), ly, 0.15, 0.135, 0.02))
    d_3_mid = sd_segment(lx, ly, c3x - 0.08, 0.0, c3x + 0.13, 0.0) - st * 0.90
    m_3 = np.clip(np.maximum(np.maximum(m_3_up, m_3_lo) * open_3, smoothstep(aa, -aa, d_3_mid)), 0.0, 1.0)
    alpha_blend(canvas, blue_rgb, m_3)

    c1x = 0.35
    d_1_stem = sd_segment(lx, ly, c1x, -0.43, c1x, 0.42) - st * 1.05
    d_1_flag = sd_segment(lx, ly, c1x - 0.19, 0.24, c1x, 0.42) - st * 0.88
    d_1_base = sd_segment(lx, ly, c1x - 0.16, -0.43, c1x + 0.16, -0.43) - st * 0.82
    m_1 = smoothstep(aa, -aa, np.minimum(np.minimum(d_1_stem, d_1_flag), d_1_base))
    alpha_blend(canvas, blue_rgb, m_1)


def generate_chassis_detail_texture(cfg: dict) -> bpy.types.Image:
    """
    512x512 procedural chassis graphic & surface detail texture (2nd embedded GLB image per AI):
      - Left half  (U in [0.0, 0.5]): FRONT chassis panel face
      - Right half (U in [0.5, 1.0]): BACK  chassis panel face
    """
    prod = cfg["product"]
    W, H = 512, 512
    u = np.linspace(0.0, 1.0, W, dtype=np.float32)[None, :]
    v = np.linspace(0.0, 1.0, H, dtype=np.float32)[:, None]
    u_grid = np.broadcast_to(u, (H, W))
    v_grid = np.broadcast_to(v, (H, W))

    base_rgb = hex_to_rgba(cfg["chassis_tex_base"])[:3]
    accent_rgb = hex_to_rgba(cfg["chassis_tex_accent"])[:3]

    canvas = np.ones((H, W, 4), dtype=np.float32)
    canvas[..., 0] = base_rgb[0]
    canvas[..., 1] = base_rgb[1]
    canvas[..., 2] = base_rgb[2]

    is_back = (u_grid >= 0.5).astype(np.float32)
    lx = np.where(u_grid < 0.5, (u_grid - 0.25) / 0.25, (u_grid - 0.75) / 0.25)
    ly = (v_grid - 0.5) * 2.0

    r2 = lx * lx + ly * ly
    satin = np.clip(1.03 - 0.055 * r2 + 0.025 * ly, 0.90, 1.04)
    canvas[..., :3] = np.clip(canvas[..., :3] * satin[..., None], 0.0, 1.0)

    if prod == "calendar":
        d_frame = sd_box(lx, ly, 0.88, 0.88, 0.08)
        inner_ao = smoothstep(-0.14, 0.02, d_frame) * 0.08
        alpha_blend(canvas, (0.76, 0.82, 0.90), inner_ao)
        for gx in (-0.42, 0.0, 0.42):
            alpha_blend(canvas, (0.86, 0.90, 0.95), smoothstep(0.012, 0.004, np.abs(lx - gx)) * 0.20)
        for gy in (-0.42, 0.0, 0.42):
            alpha_blend(canvas, (0.86, 0.90, 0.95), smoothstep(0.012, 0.004, np.abs(ly - gy)) * 0.20)
        # Bold saturated Google Blue '31' on BOTH front & back!
        _draw_calendar_31(canvas, lx * 1.15, ly * 1.15, (0.105, 0.395, 0.910))

    elif prod == "gmail":
        d_fl_l = sd_segment(lx, ly, -0.85, -0.82, 0.0, -0.08)
        d_fl_r = sd_segment(lx, ly,  0.85, -0.82, 0.0, -0.08)
        crease = smoothstep(0.032, 0.006, np.minimum(d_fl_l, d_fl_r)) * 0.08
        alpha_blend(canvas, (0.74, 0.78, 0.84), crease)
        d_rim = np.abs(sd_box(lx, ly, 0.88, 0.84, 0.14)) - 0.010
        alpha_blend(canvas, (0.80, 0.84, 0.89), smoothstep(0.014, 0.002, d_rim) * 0.30)

    elif prod == "drive":
        # Crisp glowing emerald-cyan triangular reactor core on back triangular aperture!
        d_tri1 = np.abs(sd_triangle(lx, ly, 0.0, 0.58, -0.54, -0.40, 0.54, -0.40)) - 0.028
        d_tri2 = np.abs(sd_triangle(lx, ly, 0.0, 0.32, -0.30, -0.22, 0.30, -0.22)) - 0.022
        d_core = sd_circle(lx, ly, 0.0, -0.06, 0.12)
        alpha_blend(canvas, accent_rgb, smoothstep(0.030, -0.005, d_tri1) * 0.90)
        alpha_blend(canvas, (0.35, 0.95, 0.82), smoothstep(0.026, -0.005, d_tri2) * 0.82)
        alpha_blend(canvas, (0.86, 1.00, 0.96), smoothstep(0.024, -0.008, d_core) * 0.95)

    elif prod == "chat":
        # Crisp ceramic-white front speech plaque with emerald chat-message graphic bars
        d_rim = np.abs(sd_box(lx, ly, 0.86, 0.80, 0.22)) - 0.016
        alpha_blend(canvas, accent_rgb, smoothstep(0.016, 0.002, d_rim) * 0.35)
        for by, bw, bx in ((0.22, 0.50, 0.0), (-0.18, 0.32, -0.18)):
            d_ln = sd_box(lx - bx, ly - by, bw, 0.11, 0.08)
            alpha_blend(canvas, accent_rgb, smoothstep(0.02, -0.01, d_ln) * 0.65)

    elif prod == "slides":
        # Satin golden-amber presentation deck with clean subtle hairline border
        d_rim = np.abs(sd_box(lx, ly, 0.88, 0.90, 0.12)) - 0.010
        alpha_blend(canvas, (0.80, 0.50, 0.02), smoothstep(0.014, 0.002, d_rim) * 0.28)
        # Subtle presentation bar-chart accents on back screen region
        for bx, bh in ((-0.26, 0.16), (0.0, 0.28), (0.26, 0.22)):
            d_b = sd_box(lx - bx, ly + 0.05 - bh * 0.5, 0.08, bh * 0.5, 0.02)
            alpha_blend(canvas, (1.0, 0.88, 0.45), is_back * smoothstep(0.02, -0.01, d_b) * 0.24)

    elif prod == "docs":
        d_rim = np.abs(sd_box(lx, ly, 0.88, 0.90, 0.12)) - 0.010
        alpha_blend(canvas, (0.12, 0.34, 0.78), smoothstep(0.014, 0.002, d_rim) * 0.30)

    return make_blender_image_from_srgb_array(f"{cfg['id']}_ChassisTex", canvas)


# =============================================================================
# 3. BLENDER 5.3.0 PBR MATERIAL BUILDERS
# =============================================================================

def make_pbr_material(
    name: str,
    color_hex: str,
    roughness: float = 0.25,
    metallic: float = 0.06,
    specular: float = 0.56,
    emission_hex: Optional[str] = None,
    emission_strength: float = 0.0,
    coat_weight: float = 0.0,
    coat_roughness: float = 0.08,
    alpha: float = 1.0,
) -> bpy.types.Material:
    mat = bpy.data.materials.new(name=name)
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF") or nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = hex_to_linear(color_hex, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Specular IOR Level"].default_value = specular
    bsdf.inputs["Alpha"].default_value = alpha
    if coat_weight > 0.0 and "Coat Weight" in bsdf.inputs:
        bsdf.inputs["Coat Weight"].default_value = coat_weight
        if "Coat Roughness" in bsdf.inputs:
            bsdf.inputs["Coat Roughness"].default_value = coat_roughness
    if emission_hex and emission_strength > 0.0:
        bsdf.inputs["Emission Color"].default_value = hex_to_linear(emission_hex, 1.0)
        bsdf.inputs["Emission Strength"].default_value = emission_strength
    if alpha < 0.99 and hasattr(mat, "blend_method"):
        mat.blend_method = "BLEND"
    return mat


def make_textured_material(
    name: str,
    image: bpy.types.Image,
    roughness: float = 0.22,
    metallic: float = 0.05,
    specular: float = 0.60,
    emission_strength: float = 0.0,
    coat_weight: float = 0.25,
) -> bpy.types.Material:
    mat = bpy.data.materials.new(name=name)
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = image
    tex.extension = "EXTEND"
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    if emission_strength > 0.0:
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Emission Color"])
        bsdf.inputs["Emission Strength"].default_value = emission_strength
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Specular IOR Level"].default_value = specular
    if coat_weight > 0.0 and "Coat Weight" in bsdf.inputs:
        bsdf.inputs["Coat Weight"].default_value = coat_weight
        if "Coat Roughness" in bsdf.inputs:
            bsdf.inputs["Coat Roughness"].default_value = 0.06
    return mat


# =============================================================================
# 4. SLEEK 3D SCULPTED PRIMITIVE BUILDERS (ZERO BLOCKINESS, ZERO SHADING CREASES)
# =============================================================================

def new_part_obj(
    name: str,
    bm: bmesh.types.BMesh,
    mat: bpy.types.Material,
    subsurf_levels: int = 0,
    region_tag: str = "icon_body",
    weighted_normals: bool = False,
) -> bpy.types.Object:
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()

    if len(mesh.polygons) > 0:
        mesh.polygons.foreach_set("use_smooth", [True] * len(mesh.polygons))
    mesh.update()

    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.data.materials.append(mat)

    if subsurf_levels > 0:
        mod = obj.modifiers.new(name="Subsurf", type="SUBSURF")
        mod.levels = subsurf_levels
        mod.render_levels = subsurf_levels
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.modifier_apply(modifier=mod.name)
        if len(obj.data.polygons) > 0:
            obj.data.polygons.foreach_set("use_smooth", [True] * len(obj.data.polygons))
        obj.data.update()

    if weighted_normals:
        wn = obj.modifiers.new(name="WeightedNormal", type="WEIGHTED_NORMAL")
        wn.weight = 50
        wn.keep_sharp = False
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.modifier_apply(modifier=wn.name)

    obj["region_tag"] = region_tag
    return obj


def loft_rings_bmesh(
    rings: List[List[Vector]],
    cap_bottom: bool = False,
    cap_top: bool = False,
    closed_u: bool = True,
) -> bmesh.types.BMesh:
    bm = bmesh.new()
    uv_layer = bm.loops.layers.uv.new("UVMap")
    n_rings = len(rings)
    n_seg = len(rings[0])

    v_rings: List[List[bmesh.types.BMVert]] = [[bm.verts.new(p) for p in ring] for ring in rings]
    bm.verts.ensure_lookup_table()

    seg_count = n_seg if closed_u else (n_seg - 1)
    for r_idx in range(n_rings - 1):
        r0 = v_rings[r_idx]
        r1 = v_rings[r_idx + 1]
        for i in range(seg_count):
            j = (i + 1) % n_seg
            f = bm.faces.new((r0[i], r0[j], r1[j], r1[i]))
            v0 = r_idx / max(n_rings - 1, 1)
            v1 = (r_idx + 1) / max(n_rings - 1, 1)
            u0 = i / max(seg_count, 1)
            u1 = (i + 1) / max(seg_count, 1)
            for loop, uv in zip(f.loops, [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]):
                loop[uv_layer].uv = uv

    if cap_bottom and closed_u:
        c_bot = sum((v.co for v in v_rings[0]), Vector((0, 0, 0))) / n_seg
        n_dir = (rings[0][0] - rings[1][0]).normalized() if (rings[0][0] - rings[1][0]).length > 1e-6 else Vector((0, 0, -1))
        center_v = bm.verts.new(c_bot + n_dir * 0.002)
        for i in range(n_seg):
            j = (i + 1) % n_seg
            f = bm.faces.new((v_rings[0][j], v_rings[0][i], center_v))
            for loop in f.loops:
                loop[uv_layer].uv = (0.5, 0.02)

    if cap_top and closed_u:
        c_top = sum((v.co for v in v_rings[-1]), Vector((0, 0, 0))) / n_seg
        n_dir = (rings[-1][0] - rings[-2][0]).normalized() if (rings[-1][0] - rings[-2][0]).length > 1e-6 else Vector((0, 0, 1))
        center_v = bm.verts.new(c_top + n_dir * 0.002)
        for i in range(n_seg):
            j = (i + 1) % n_seg
            f = bm.faces.new((v_rings[-1][i], v_rings[-1][j], center_v))
            for loop in f.loops:
                loop[uv_layer].uv = (0.5, 0.98)

    return bm


def make_tube_along_curve(
    points: List[Vector],
    radii: List[Tuple[float, float]],
    n_seg: int = 8,
    cap_start: bool = True,
    cap_end: bool = True,
) -> bmesh.types.BMesh:
    rings: List[List[Vector]] = []
    up_hint = Vector((0, 1, 0))
    for idx, p in enumerate(points):
        if idx == 0:
            t = (points[1] - points[0]).normalized()
        elif idx == len(points) - 1:
            t = (points[-1] - points[-2]).normalized()
        else:
            t = (points[idx + 1] - points[idx - 1]).normalized()
        if t.length < 1e-6:
            t = Vector((0, 0, -1))
        ref = up_hint if abs(t.dot(up_hint)) < 0.92 else Vector((1, 0, 0))
        b1 = t.cross(ref).normalized()
        b2 = t.cross(b1).normalized()
        rx, ry = radii[idx]
        ring = []
        for s in range(n_seg):
            ang = 2.0 * math.pi * s / n_seg
            ring.append(p + b1 * (math.cos(ang) * rx) + b2 * (math.sin(ang) * ry))
        rings.append(ring)
    return loft_rings_bmesh(rings, cap_bottom=cap_start, cap_top=cap_end)


def make_sphere_part(
    name: str,
    center: Vector,
    radius_xyz: Tuple[float, float, float],
    mat: bpy.types.Material,
    region_tag: str,
    subdiv: int = 1,
) -> bpy.types.Object:
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=subdiv, radius=1.0)
    uv_layer = bm.loops.layers.uv.new("UVMap")
    rx, ry, rz = radius_xyz
    for v in bm.verts:
        v.co = Vector((center.x + v.co.x * rx, center.y + v.co.y * ry, center.z + v.co.z * rz))
    for f in bm.faces:
        for loop in f.loops:
            loop[uv_layer].uv = (0.5, 0.5)
    return new_part_obj(name, bm, mat, subsurf_levels=0, region_tag=region_tag)


def make_torus_ring_part(
    name: str,
    center: Vector,
    axis: Vector,
    major_r: float,
    minor_r: float,
    mat: bpy.types.Material,
    region_tag: str,
    n_major: int = 12,
    n_minor: int = 5,
) -> bpy.types.Object:
    ax = axis.normalized()
    ref = Vector((0, 1, 0)) if abs(ax.dot(Vector((0, 1, 0)))) < 0.92 else Vector((1, 0, 0))
    u_vec = ax.cross(ref).normalized()
    v_vec = ax.cross(u_vec).normalized()
    rings: List[List[Vector]] = []
    for i in range(n_major + 1):
        a = 2.0 * math.pi * (i % n_major) / n_major
        rad_dir = u_vec * math.cos(a) + v_vec * math.sin(a)
        c_pt = center + rad_dir * major_r
        ring = []
        for j in range(n_minor):
            b = 2.0 * math.pi * j / n_minor
            ring.append(c_pt + rad_dir * (math.cos(b) * minor_r) + ax * (math.sin(b) * minor_r))
        rings.append(ring)
    bm = loft_rings_bmesh(rings, cap_bottom=False, cap_top=False)
    return new_part_obj(name, bm, mat, subsurf_levels=0, region_tag=region_tag)


def round_polygon_2d(
    corners: List[Tuple[float, float]],
    radii: Sequence[float] | float,
    arc_segs: int = 3,
) -> List[Tuple[float, float]]:
    n = len(corners)
    r_list = [float(radii)] * n if isinstance(radii, (int, float)) else [float(r) for r in radii]

    pts: List[Tuple[float, float]] = []
    for i in range(n):
        p_prev = Vector((corners[(i - 1) % n][0], corners[(i - 1) % n][1]))
        p_curr = Vector((corners[i][0], corners[i][1]))
        p_next = Vector((corners[(i + 1) % n][0], corners[(i + 1) % n][1]))

        v1 = p_prev - p_curr
        v2 = p_next - p_curr
        l1, l2 = v1.length, v2.length
        r = r_list[i]
        if r <= 1e-5 or l1 < 1e-5 or l2 < 1e-5:
            pts.append((p_curr.x, p_curr.y))
            continue

        d1 = v1 / l1
        d2 = v2 / l2
        dot = max(-0.999, min(0.999, d1.dot(d2)))
        half_ang = 0.5 * math.acos(dot)
        if half_ang < 0.02 or half_ang > math.pi * 0.495:
            pts.append((p_curr.x, p_curr.y))
            continue

        tan_h = math.tan(half_ang)
        max_t = 0.46 * min(l1, l2)
        t_dist = min(r / max(tan_h, 1e-5), max_t)
        r_eff = t_dist * tan_h

        t1 = p_curr + d1 * t_dist
        t2 = p_curr + d2 * t_dist
        bis = d1 + d2
        if bis.length < 1e-5:
            pts.append((p_curr.x, p_curr.y))
            continue
        bis.normalize()
        c_dist = r_eff / max(math.sin(half_ang), 1e-5)
        center = p_curr + bis * c_dist

        a1 = math.atan2(t1.y - center.y, t1.x - center.x)
        a2 = math.atan2(t2.y - center.y, t2.x - center.x)
        da = a2 - a1
        while da > math.pi:
            da -= 2.0 * math.pi
        while da < -math.pi:
            da += 2.0 * math.pi

        for k in range(arc_segs + 1):
            ang = a1 + da * (k / arc_segs)
            pts.append((center.x + math.cos(ang) * r_eff, center.y + math.sin(ang) * r_eff))

    cleaned: List[Tuple[float, float]] = []
    for p in pts:
        if not cleaned or math.hypot(p[0] - cleaned[-1][0], p[1] - cleaned[-1][1]) > 1e-4:
            cleaned.append(p)
    if len(cleaned) > 2 and math.hypot(cleaned[0][0] - cleaned[-1][0], cleaned[0][1] - cleaned[-1][1]) < 1e-4:
        cleaned.pop()
    return cleaned


def rounded_rect_2d(
    cx: float,
    cz: float,
    half_w: float,
    half_h: float,
    radius: float,
    arc_segs: int = 3,
) -> List[Tuple[float, float]]:
    return round_polygon_2d(
        [
            (cx - half_w, cz - half_h),
            (cx + half_w, cz - half_h),
            (cx + half_w, cz + half_h),
            (cx - half_w, cz + half_h),
        ],
        radius,
        arc_segs=arc_segs,
    )


def dog_ear_page_2d(
    cx: float,
    cz: float,
    half_w: float,
    half_h: float,
    dog_size: float,
    corner_r: float = 0.044,
    arc_segs: int = 3,
) -> List[Tuple[float, float]]:
    """Rounded vertical document with authentic 45° top-right dog-ear chamfer (viewer RIGHT = -X)."""
    x_l, x_r = cx - half_w, cx + half_w
    z_b, z_t = cz - half_h, cz + half_h
    corners = [
        (x_l, z_b),
        (x_r, z_b),
        (x_r, z_t),
        (x_l + dog_size, z_t),
        (x_l, z_t - dog_size),
    ]
    return round_polygon_2d(corners, [corner_r, corner_r, corner_r, 0.010, 0.010], arc_segs=arc_segs)


def _inset_contour_2d(pts: List[Tuple[float, float]], inset: float) -> List[Tuple[float, float]]:
    n = len(pts)
    if inset <= 1e-6 or n < 3:
        return list(pts)
    area = sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n))
    sign = 1.0 if area >= 0.0 else -1.0
    cx = sum(p[0] for p in pts) / n
    cz = sum(p[1] for p in pts) / n

    out: List[Tuple[float, float]] = []
    for i in range(n):
        p_prev, p_curr, p_next = pts[(i - 1) % n], pts[i], pts[(i + 1) % n]
        e1 = Vector((p_curr[0] - p_prev[0], p_curr[1] - p_prev[1]))
        e2 = Vector((p_next[0] - p_curr[0], p_next[1] - p_curr[1]))
        if e1.length > 1e-6:
            e1.normalize()
        if e2.length > 1e-6:
            e2.normalize()
        n1 = Vector((-e1.y * sign, e1.x * sign))
        n2 = Vector((-e2.y * sign, e2.x * sign))
        bis = n1 + n2
        if bis.length < 1e-5:
            off = n1 * inset
        else:
            bis.normalize()
            denom = max(0.55, bis.dot(n1))
            off = bis * min(inset / denom, inset * 1.45)

        to_c = Vector((cx - p_curr[0], cz - p_curr[1]))
        if to_c.length > 1e-5 and off.length > to_c.length * 0.86:
            off *= (to_c.length * 0.86) / off.length
        out.append((p_curr[0] + off.x, p_curr[1] + off.y))
    return out


def make_beveled_slab_xz(
    name: str,
    contour_xz: List[Tuple[float, float]],
    y_back: float,
    y_front: float,
    bevel_xy: float,
    bevel_y: float,
    mat: bpy.types.Material,
    region_tag: str = "icon_body",
    bevel_segs: int = 2,
    dome_bulge: float = 0.0,
    uv_bounds: Optional[Tuple[float, float, float, float]] = None,
    flat_faces: bool = True,
) -> bpy.types.Object:
    """
    Sculpts a machined-ceramic multi-beveled 3D solid from any closed 2D XZ contour.
    When `flat_faces=True` (default), adds a coplanar perimeter support loop and pure-flat cap
    with zero radial dome-fan creases so glossy flat icon faces look like Apple/Pixar industrial design!
    Front (+Y) maps to U in [0.02, 0.48], Back (-Y) maps to U in [0.52, 0.98].
    """
    n = len(contour_xz)
    half_t = 0.5 * (y_front - y_back)
    by = min(bevel_y, half_t * 0.88)
    bx = bevel_xy

    slices: List[Tuple[float, float]] = []
    if flat_faces:
        slices.append((y_back, bx + 0.005))
    for k in range(bevel_segs + 1):
        ang = (math.pi * 0.5) * (k / max(bevel_segs, 1))
        slices.append((y_back + by * (1.0 - math.cos(ang)), bx * (1.0 - math.sin(ang))))
    for k in range(bevel_segs + 1):
        ang = (math.pi * 0.5) * (k / max(bevel_segs, 1))
        slices.append((y_front - by * math.cos(ang), bx * (1.0 - math.cos(ang))))
    if flat_faces:
        slices.append((y_front, bx + 0.005))

    cx = sum(p[0] for p in contour_xz) / n
    cz = sum(p[1] for p in contour_xz) / n
    xs = [p[0] for p in contour_xz]
    zs = [p[1] for p in contour_xz]
    x_min, x_max, z_min, z_max = uv_bounds if uv_bounds is not None else (min(xs), max(xs), min(zs), max(zs))
    x_span = max(x_max - x_min, 1e-4)
    z_span = max(z_max - z_min, 1e-4)
    x_mid = 0.5 * (x_min + x_max)
    y_mid = 0.5 * (y_back + y_front)

    bm = bmesh.new()
    uv_layer = bm.loops.layers.uv.new("UVMap")

    v_rings: List[List[bmesh.types.BMVert]] = []
    for y_val, ins in slices:
        pts_i = _inset_contour_2d(contour_xz, ins)
        v_rings.append([bm.verts.new(Vector((px, y_val, pz))) for px, pz in pts_i])
    bm.verts.ensure_lookup_table()

    def map_uv(co: Vector, is_front: bool) -> Tuple[float, float]:
        vv = max(0.01, min(0.99, (co.z - z_min) / z_span))
        nx = (co.x - x_mid) / (0.5 * x_span)
        if is_front:
            uu = max(0.01, min(0.49, 0.25 - nx * 0.235))
        else:
            uu = max(0.51, min(0.99, 0.75 + nx * 0.235))
        return (uu, vv)

    for r_idx in range(len(v_rings) - 1):
        r0, r1 = v_rings[r_idx], v_rings[r_idx + 1]
        is_f = 0.5 * (slices[r_idx][0] + slices[r_idx + 1][0]) >= y_mid
        for i in range(n):
            j = (i + 1) % n
            f = bm.faces.new((r0[i], r0[j], r1[j], r1[i]))
            for loop in f.loops:
                loop[uv_layer].uv = map_uv(loop.vert.co, is_f)

    if flat_faces and dome_bulge == 0.0:
        # Clean planar n-gon cap -> ZERO radial shading rays across flat ceramic faces!
        fb = bm.faces.new(list(reversed(v_rings[0])))
        for loop in fb.loops:
            loop[uv_layer].uv = map_uv(loop.vert.co, False)
        ff = bm.faces.new(list(v_rings[-1]))
        for loop in ff.loops:
            loop[uv_layer].uv = map_uv(loop.vert.co, True)
    else:
        c_back = bm.verts.new(Vector((cx, y_back - dome_bulge, cz)))
        c_front = bm.verts.new(Vector((cx, y_front + dome_bulge, cz)))
        for i in range(n):
            j = (i + 1) % n
            fb = bm.faces.new((v_rings[0][j], v_rings[0][i], c_back))
            for loop in fb.loops:
                loop[uv_layer].uv = map_uv(loop.vert.co, False)
            ff = bm.faces.new((v_rings[-1][i], v_rings[-1][j], c_front))
            for loop in ff.loops:
                loop[uv_layer].uv = map_uv(loop.vert.co, True)

    return new_part_obj(name, bm, mat, subsurf_levels=0, region_tag=region_tag, weighted_normals=flat_faces)


def make_beveled_bar_xz(
    name: str,
    p0: Tuple[float, float],
    p1: Tuple[float, float],
    half_width: float,
    y_back: float,
    y_front: float,
    mat: bpy.types.Material,
    region_tag: str = "icon_body",
    cap_round: bool = True,
    bevel_r: float = 0.007,
    bevel_segs: int = 1,
) -> bpy.types.Object:
    """Sculpts a smooth 3D beveled rounded-capsule bar between 2D XZ points p0 and p1."""
    v0 = Vector((p0[0], p0[1]))
    v1 = Vector((p1[0], p1[1]))
    d = v1 - v0
    length = max(d.length, 1e-4)
    t_hat = d / length
    n_hat = Vector((-t_hat.y, t_hat.x))

    contour: List[Tuple[float, float]] = []
    if cap_round:
        n_arc = 3
        base_ang1 = math.atan2(n_hat.y, n_hat.x)
        for k in range(n_arc + 1):
            ang = base_ang1 - math.pi * (k / n_arc)
            p = v1 + Vector((math.cos(ang), math.sin(ang))) * half_width
            contour.append((p.x, p.y))
        base_ang0 = math.atan2(-n_hat.y, -n_hat.x)
        for k in range(n_arc + 1):
            ang = base_ang0 - math.pi * (k / n_arc)
            p = v0 + Vector((math.cos(ang), math.sin(ang))) * half_width
            contour.append((p.x, p.y))
    else:
        corners = [
            (v0.x - n_hat.x * half_width, v0.y - n_hat.y * half_width),
            (v1.x - n_hat.x * half_width, v1.y - n_hat.y * half_width),
            (v1.x + n_hat.x * half_width, v1.y + n_hat.y * half_width),
            (v0.x + n_hat.x * half_width, v0.y + n_hat.y * half_width),
        ]
        contour = round_polygon_2d(corners, min(half_width * 0.35, 0.012), arc_segs=2)

    return make_beveled_slab_xz(
        name,
        contour,
        y_back=y_back,
        y_front=y_front,
        bevel_xy=min(bevel_r, half_width * 0.42),
        bevel_y=min(bevel_r, 0.42 * (y_front - y_back)),
        mat=mat,
        region_tag=region_tag,
        bevel_segs=bevel_segs,
        dome_bulge=0.0,
        flat_faces=True,
    )


def build_curved_ai_visor(
    name: str,
    cx: float,
    cz: float,
    half_w: float,
    half_h: float,
    y_surface: float,
    visor_mat: bpy.types.Material,
    bezel_mat: bpy.types.Material,
    region_tag: str = "icon_body",
    curve_x: float = 0.015,
    curve_z: float = 0.006,
    corner_pow: float = 4.2,
    bezel_r: float = 0.007,
    tri_mask: bool = False,
) -> List[bpy.types.Object]:
    objs: List[bpy.types.Object] = []

    if tri_mask:
        bm = bmesh.new()
        uv_layer = bm.loops.layers.uv.new("UVMap")
        rows = 7
        grid_v: List[List[bmesh.types.BMVert]] = []
        grid_uv: List[List[Tuple[float, float]]] = []
        for r in range(rows + 1):
            tv = r / rows
            row_w = half_w * max(0.06, 1.0 - tv * 0.94)
            z_here = cz - half_h + tv * (2.0 * half_h)
            cols = max(2, rows - r + 2)
            rv, ruv = [], []
            for c in range(cols + 1):
                tu = c / cols
                x_here = cx + row_w * (1.0 - 2.0 * tu)
                xn = (x_here - cx) / max(half_w, 1e-4)
                zn = (z_here - cz) / max(half_h, 1e-4)
                y_here = y_surface + curve_x * max(0.0, 1.0 - xn * xn) + curve_z * max(0.0, 1.0 - zn * zn)
                rv.append(bm.verts.new(Vector((x_here, y_here, z_here))))
                u_tex = 0.5 - 0.5 * ((x_here - cx) / max(half_w, 1e-4))
                v_tex = 0.5 + 0.5 * ((z_here - cz) / max(half_h, 1e-4))
                ruv.append((u_tex, v_tex))
            grid_v.append(rv)
            grid_uv.append(ruv)

        for r in range(rows):
            row0, row1 = grid_v[r], grid_v[r + 1]
            uv0, uv1 = grid_uv[r], grid_uv[r + 1]
            n0, n1 = len(row0), len(row1)
            i0, i1 = 0, 0
            while i0 < n0 - 1 or i1 < n1 - 1:
                if i0 < n0 - 1 and (i1 == n1 - 1 or (i0 / max(n0 - 1, 1)) <= (i1 / max(n1 - 1, 1))):
                    f = bm.faces.new((row0[i0], row0[i0 + 1], row1[i1]))
                    for lp, uv in zip(f.loops, (uv0[i0], uv0[i0 + 1], uv1[i1])):
                        lp[uv_layer].uv = uv
                    i0 += 1
                else:
                    f = bm.faces.new((row0[i0], row1[i1 + 1], row1[i1]))
                    for lp, uv in zip(f.loops, (uv0[i0], uv1[i1 + 1], uv1[i1])):
                        lp[uv_layer].uv = uv
                    i1 += 1

        objs.append(new_part_obj(f"{name}_Glass", bm, visor_mat, subsurf_levels=0, region_tag=region_tag))
        return objs

    n_u, n_v = 10, 6
    bm = bmesh.new()
    uv_layer = bm.loops.layers.uv.new("UVMap")
    v_grid: List[List[bmesh.types.BMVert]] = []
    uv_pts: List[List[Tuple[float, float]]] = []

    def visor_pt(su: float, sv: float) -> Tuple[Vector, Tuple[float, float]]:
        r_sq = (abs(su) ** corner_pow + abs(sv) ** corner_pow) ** (1.0 / corner_pow)
        scale = max(abs(su), abs(sv)) / r_sq if r_sq > 1e-5 else 1.0
        sx, sz = su * scale, sv * scale
        px = cx - sx * half_w
        pz = cz + sz * half_h
        py = y_surface + curve_x * max(0.0, 1.0 - sx * sx) + curve_z * max(0.0, 1.0 - sz * sz)
        return Vector((px, py, pz)), (0.5 + 0.48 * sx, 0.5 + 0.48 * sz)

    for j in range(n_v + 1):
        sv = -1.0 + 2.0 * (j / n_v)
        rv, ruv = [], []
        for i in range(n_u + 1):
            su = -1.0 + 2.0 * (i / n_u)
            pt, uv = visor_pt(su, sv)
            rv.append(bm.verts.new(pt))
            ruv.append(uv)
        v_grid.append(rv)
        uv_pts.append(ruv)

    for j in range(n_v):
        for i in range(n_u):
            f = bm.faces.new((v_grid[j][i], v_grid[j][i + 1], v_grid[j + 1][i + 1], v_grid[j + 1][i]))
            for lp, uv in zip(f.loops, (uv_pts[j][i], uv_pts[j][i + 1], uv_pts[j + 1][i + 1], uv_pts[j + 1][i])):
                lp[uv_layer].uv = uv

    objs.append(new_part_obj(f"{name}_Glass", bm, visor_mat, subsurf_levels=0, region_tag=region_tag))

    perim_pts: List[Vector] = []
    for k in range(22):
        ang = 2.0 * math.pi * k / 22
        ca, sa = math.cos(ang), math.sin(ang)
        denom = (abs(ca) ** corner_pow + abs(sa) ** corner_pow) ** (1.0 / corner_pow)
        sx, sz = ca / max(denom, 1e-5), sa / max(denom, 1e-5)
        px = cx - sx * (half_w + bezel_r * 0.35)
        pz = cz + sz * (half_h + bezel_r * 0.35)
        py = y_surface + curve_x * max(0.0, 1.0 - sx * sx) + curve_z * max(0.0, 1.0 - sz * sz) - 0.002
        perim_pts.append(Vector((px, py, pz)))
    perim_pts.append(perim_pts[0].copy())
    bm_bez = make_tube_along_curve(perim_pts, [(bezel_r, bezel_r * 0.85)] * len(perim_pts), n_seg=5, cap_start=False, cap_end=False)
    objs.append(new_part_obj(f"{name}_Bezel", bm_bez, bezel_mat, subsurf_levels=0, region_tag=region_tag))

    return objs


# =============================================================================
# 5. SIX DISTINCT 3D SCULPTED WORKSPACE PRODUCT ICON CHASSIS BUILDERS
#    (STRICTLY Y in [-0.130, +0.130] FOR ZERO TWO-HANDED RIFLE CLIPPING!)
# =============================================================================

def build_icon_chassis(
    cfg: dict,
    mats: Dict[str, bpy.types.Material],
) -> Tuple[List[bpy.types.Object], float, float]:
    hid = cfg["id"]
    prod = cfg["product"]
    objs: List[bpy.types.Object] = []

    m_blue = mats["g_blue"]
    m_dblue = mats["g_dblue"]
    m_red = mats["g_red"]
    m_dred = mats["g_dred"]
    m_yellow = mats["g_yellow"]
    m_dyellow = mats["g_dyellow"]
    m_green = mats["g_green"]
    m_dgreen = mats["g_dgreen"]
    m_mint = mats["g_mint"]
    m_white = mats["ceramic_white"]
    m_dark = mats["anodized_dark"]
    m_metal = mats["titanium"]
    m_emissive = mats["emissive"]
    m_visor = mats["visor"]
    m_chassis_tex = mats["chassis_tex"]

    # -------------------------------------------------------------------------
    # 1. GMAIL AI: 3D Sculpted Rounded Ceramic Envelope + Flush 3D 4-Color M
    # -------------------------------------------------------------------------
    if prod == "gmail":
        env_w, env_h, env_cz = 0.268, 0.232, 1.258
        env_contour = rounded_rect_2d(0.0, env_cz, env_w, env_h, radius=0.060, arc_segs=3)
        objs.append(make_beveled_slab_xz(
            f"{hid}_EnvelopeBody", env_contour, -0.095, +0.095, 0.020, 0.022,
            m_chassis_tex, "icon_body", bevel_segs=2, dome_bulge=0.0, flat_faces=True,
        ))

        # Sculpted 3D raised 4-Color Gmail 'M' Ribbon Arch on BOTH Front (+Y) AND Back (-Y)
        for face_name, y_in, y_out, s_left in (
            ("Front", +0.093, +0.118, +1.0),
            ("Back",  -0.118, -0.093, -1.0),
        ):
            x_bar = 0.194 * s_left
            x_rbar = -0.194 * s_left
            z_bot = env_cz - 0.166
            z_mid = env_cz + 0.092
            z_top = env_cz + 0.146
            z_apex = env_cz - 0.036

            # Left Blue vertical rounded pillar
            objs.append(make_beveled_bar_xz(f"{hid}_GmailBlue_{face_name}", (x_bar, z_bot), (x_bar, z_mid), 0.043, y_in, y_out, m_blue, "icon_body", True, 0.007, 1))
            # Right Green vertical rounded pillar
            objs.append(make_beveled_bar_xz(f"{hid}_GmailGreen_{face_name}", (x_rbar, z_bot), (x_rbar, z_mid), 0.043, y_in, y_out, m_green, "icon_body", True, 0.007, 1))
            # Crisp Bright Red center V-chevron (flush +1.5mm above base pillars!)
            dy_v = 0.002 if face_name == "Front" else -0.002
            objs.append(make_beveled_bar_xz(f"{hid}_GmailRedL_{face_name}", (x_bar, z_top), (0.0, z_apex), 0.039, y_in + dy_v, y_out + dy_v, m_red, "icon_body", True, 0.007, 1))
            objs.append(make_beveled_bar_xz(f"{hid}_GmailRedR_{face_name}", (x_rbar, z_top), (0.0, z_apex), 0.039, y_in + dy_v, y_out + dy_v, m_red, "icon_body", True, 0.007, 1))
            # Flush Upper-Left Dark Crimson & Upper-Right Google Yellow corner folds (zero protruding pill look!)
            dy_c = 0.003 if face_name == "Front" else -0.003
            objs.append(make_beveled_bar_xz(f"{hid}_GmailCrimson_{face_name}", (x_bar, z_mid), (x_bar, z_top), 0.044, y_in + dy_c, y_out + dy_c, m_dred, "icon_body", True, 0.007, 1))
            objs.append(make_beveled_bar_xz(f"{hid}_GmailYellow_{face_name}", (x_rbar, z_mid), (x_rbar, z_top), 0.044, y_in + dy_c, y_out + dy_c, m_yellow, "icon_body", True, 0.007, 1))

        # Sleek Integrated Ceramic-White AI Optical Visor Brow Dome
        brow_contour = rounded_rect_2d(0.0, 1.610, 0.184, 0.118, radius=0.082, arc_segs=3)
        objs.append(make_beveled_slab_xz(
            f"{hid}_VisorBrowShell", brow_contour, -0.092, +0.090, 0.022, 0.024,
            m_white, "icon_crest", bevel_segs=2, dome_bulge=0.008, flat_faces=False,
        ))
        arc_pts = [
            Vector((math.sin(math.radians(-66 + 132 * k / 8.0)) * 0.174, 0.0, 1.606 + math.cos(math.radians(-66 + 132 * k / 8.0)) * 0.128))
            for k in range(9)
        ]
        objs.append(new_part_obj(f"{hid}_CrownTrim", make_tube_along_curve(arc_pts, [(0.010, 0.022)] * len(arc_pts), n_seg=6), m_red, 0, "icon_crest"))
        objs.extend(build_curved_ai_visor(
            f"{hid}_Visor", cx=0.0, cz=1.610, half_w=0.146, half_h=0.072,
            y_surface=0.094, visor_mat=m_visor, bezel_mat=m_metal,
            region_tag="icon_crest", curve_x=0.017, curve_z=0.007,
        ))
        objs.append(make_beveled_bar_xz(f"{hid}_RearStatusBar", (-0.082, 1.612), (+0.082, 1.612), 0.013, -0.105, -0.090, m_emissive, "icon_crest", True, 0.004, 1))
        for s_name, sx in (("R", 1.0), ("L", -1.0)):
            objs.append(make_sphere_part(f"{hid}_EarPod_{s_name}", Vector((sx * 0.188, 0.0, 1.610)), (0.017, 0.030, 0.030), m_red, "icon_crest", 1))
            objs.append(make_sphere_part(f"{hid}_EarLED_{s_name}", Vector((sx * 0.201, 0.0, 1.610)), (0.008, 0.013, 0.013), m_emissive, "icon_crest", 1))

        return objs, 0.256, 1.335

    # -------------------------------------------------------------------------
    # 2. GOOGLE DRIVE AI: True Equilateral 3D Interlocking Tri-Color Triangle Prism
    # -------------------------------------------------------------------------
    if prod == "drive":
        # Authentic Equilateral Google Drive Proportions:
        # Outer width ~ 0.62m, outer height ~ 0.60m (Z_base=1.06 -> Z_apex=1.675, plus sleek apex sensor to 1.76m!)
        z_base = 1.072
        z_apex = 1.655
        x_bot = 0.278  # wide equilateral base!
        bar_hw = 0.062

        # Inner dark-titanium triangular backing housing the central AI core & visor
        tri_inner = round_polygon_2d(
            [(0.0, z_apex - 0.030), (+x_bot - 0.025, z_base + 0.010), (-x_bot + 0.025, z_base + 0.010)],
            0.030, arc_segs=2,
        )
        objs.append(make_beveled_slab_xz(
            f"{hid}_TriCoreBody", tri_inner, -0.086, +0.086, 0.012, 0.014,
            m_dark, "icon_body", bevel_segs=1, dome_bulge=0.0, flat_faces=True,
        ))

        # 3 Bold Interlocking Chamfered Google Drive Prism Bars (True 60° Equilateral Triangle!)
        # Viewer FRONT (+Y): LEFT (+X) = Emerald Green, RIGHT (-X) = Golden Yellow, BOTTOM = Cobalt Blue!
        # Left Emerald Green angled leg
        objs.append(make_beveled_bar_xz(
            f"{hid}_DriveGreenLeg",
            (+x_bot * 0.90, z_base + 0.028), (+0.036, z_apex - 0.008),
            bar_hw, -0.116, +0.116, m_green, "icon_body", True, 0.014, 2,
        ))
        # Right Golden-Yellow angled leg
        objs.append(make_beveled_bar_xz(
            f"{hid}_DriveYellowLeg",
            (-0.036, z_apex - 0.008), (-x_bot * 0.90, z_base + 0.028),
            bar_hw, -0.114, +0.114, m_yellow, "icon_body", True, 0.014, 2,
        ))
        # Bottom Cobalt-Blue horizontal bar
        objs.append(make_beveled_bar_xz(
            f"{hid}_DriveBlueBase",
            (+x_bot * 0.78, z_base), (-x_bot * 0.78, z_base),
            bar_hw * 0.95, -0.115, +0.115, m_blue, "icon_body", True, 0.014, 2,
        ))

        # Authentic Flush Beveled Möbius Corner Fold Caps (aligned 100% INSIDE the 3 bar intersections!)
        # Top apex warm dark-gold fold diamond
        top_fold = round_polygon_2d(
            [(0.0, z_apex + 0.050), (+0.072, z_apex - 0.044), (0.0, z_apex - 0.092), (-0.072, z_apex - 0.044)],
            0.020, arc_segs=2,
        )
        objs.append(make_beveled_slab_xz(f"{hid}_DriveTopFold", top_fold, -0.119, +0.119, 0.012, 0.014, m_dyellow, "icon_body", 1, 0.0, flat_faces=True))
        # Bottom-left (+X) deep emerald fold cap (flush with Green + Blue overlap!)
        bl_fold = round_polygon_2d(
            [(+x_bot * 0.94, z_base + 0.062), (+x_bot * 0.56, z_base + 0.060), (+x_bot * 0.66, z_base - 0.056), (+x_bot * 1.02, z_base - 0.012)],
            0.022, arc_segs=2,
        )
        objs.append(make_beveled_slab_xz(f"{hid}_DriveLeftFold", bl_fold, -0.119, +0.119, 0.011, 0.012, m_dgreen, "icon_body", 1, 0.0, flat_faces=True))
        # Bottom-right (-X) vibrant Google Red fold cap (flush with Yellow + Blue overlap!)
        br_fold = round_polygon_2d(
            [(-x_bot * 0.94, z_base + 0.062), (-x_bot * 1.02, z_base - 0.012), (-x_bot * 0.66, z_base - 0.056), (-x_bot * 0.56, z_base + 0.060)],
            0.022, arc_segs=2,
        )
        objs.append(make_beveled_slab_xz(f"{hid}_DriveRightFold", br_fold, -0.119, +0.119, 0.011, 0.012, m_red, "icon_body", 1, 0.0, flat_faces=True))

        # Wide Central Recessed Curved Dark-Glass Triangular AI Visor (FRONT +Y)
        objs.extend(build_curved_ai_visor(
            f"{hid}_TriVisor", cx=0.0, cz=1.320, half_w=0.175, half_h=0.180,
            y_surface=0.090, visor_mat=m_visor, bezel_mat=m_metal,
            region_tag="icon_body", curve_x=0.017, curve_z=0.007, tri_mask=True,
        ))
        # Back (-Y) Glowing Triangular AI Reactor Core Screen
        back_tri = round_polygon_2d(
            [(0.0, 1.490), (+0.165, 1.150), (-0.165, 1.150)],
            0.020, arc_segs=2,
        )
        objs.append(make_beveled_slab_xz(
            f"{hid}_RearReactorCore", back_tri, -0.102, -0.078, 0.007, 0.007, m_chassis_tex, "icon_body", 1, 0.0,
            uv_bounds=(-0.18, +0.18, 1.13, 1.51), flat_faces=True,
        ))

        # Sleek Top Apex Sensor Crown (raises Drive AI to ~1.76m with subtle Head tracking!)
        objs.append(make_beveled_slab_xz(
            f"{hid}_ApexFin", rounded_rect_2d(0.0, z_apex + 0.068, 0.036, 0.028, 0.016, 2),
            -0.026, +0.026, 0.007, 0.008, m_metal, "icon_crest", 1, 0.0, flat_faces=True,
        ))
        objs.append(make_sphere_part(f"{hid}_ApexSensorLED", Vector((0.0, 0.0, z_apex + 0.098)), (0.018, 0.016, 0.016), m_emissive, "icon_crest", 1))

        # Sleek Anodized Shoulder Pylons extending from angled prism flanks to Shoulder_L/R
        for s_name, sx in (("R", 1.0), ("L", -1.0)):
            pylon_pts = [Vector((sx * 0.165, 0.0, 1.340)), Vector((sx * 0.244, 0.0, 1.340))]
            objs.append(new_part_obj(
                f"{hid}_ShoulderPylon_{s_name}",
                make_tube_along_curve(pylon_pts, [(0.032, 0.035), (0.028, 0.030)], n_seg=8),
                m_metal, 0, "icon_body",
            ))

        return objs, 0.246, 1.340

    # -------------------------------------------------------------------------
    # 3. GOOGLE CALENDAR AI: 3D 4-Color Framed Tile + Crisp '31' + Integrated Top Visor
    # -------------------------------------------------------------------------
    if prod == "calendar":
        tile_cz = 1.290
        tile_hw, tile_hh = 0.246, 0.268
        cut_s = 0.096
        tile_corners = [
            (-tile_hw + cut_s, tile_cz - tile_hh),
            (+tile_hw, tile_cz - tile_hh),
            (+tile_hw, tile_cz + tile_hh),
            (-tile_hw, tile_cz + tile_hh),
            (-tile_hw, tile_cz - tile_hh + cut_s),
        ]
        tile_contour = round_polygon_2d(tile_corners, [0.012, 0.042, 0.042, 0.042, 0.012], arc_segs=3)
        objs.append(make_beveled_slab_xz(
            f"{hid}_CalendarCore", tile_contour, -0.094, +0.094, 0.016, 0.018,
            m_white, "icon_body", bevel_segs=2, dome_bulge=0.0, flat_faces=True,
        ))

        # Recessed Glossy Ceramic White '31' Textured Inner Tablet (Front +Y & Back -Y, reads '31' on BOTH!)
        inner_contour = rounded_rect_2d(0.0, tile_cz - 0.006, 0.166, 0.172, radius=0.022, arc_segs=2)
        objs.append(make_beveled_slab_xz(
            f"{hid}_Calendar31Face", inner_contour, -0.102, +0.102, 0.005, 0.005,
            m_chassis_tex, "icon_body", bevel_segs=1, dome_bulge=0.0,
            uv_bounds=(-0.166, +0.166, tile_cz - 0.178, tile_cz + 0.166), flat_faces=True,
        ))

        # Sculpted 3D Beveled 4-Color Perimeter Frame Bars
        fw = 0.037
        objs.append(make_beveled_bar_xz(f"{hid}_CalTopBar", (+0.208, tile_cz + tile_hh - 0.035), (-0.208, tile_cz + tile_hh - 0.035), fw, -0.116, +0.116, m_blue, "icon_body", True, 0.009, 1))
        objs.append(make_beveled_bar_xz(f"{hid}_CalLeftBar", (+tile_hw - 0.035, tile_cz + tile_hh - 0.042), (+tile_hw - 0.035, tile_cz - tile_hh + 0.042), fw, -0.116, +0.116, m_blue, "icon_body", True, 0.009, 1))
        objs.append(make_beveled_bar_xz(f"{hid}_CalRightBar", (-tile_hw + 0.035, tile_cz + tile_hh - 0.068), (-tile_hw + 0.035, tile_cz - tile_hh + cut_s + 0.026), fw, -0.114, +0.114, m_yellow, "icon_body", True, 0.009, 1))
        objs.append(make_beveled_bar_xz(f"{hid}_CalBottomBar", (+tile_hw - 0.068, tile_cz - tile_hh + 0.035), (-tile_hw + cut_s + 0.026, tile_cz - tile_hh + 0.035), fw, -0.114, +0.114, m_green, "icon_body", True, 0.009, 1))

        # Authentic Corner Overlap Accents (Dark-Blue TR, Dark-Green BL, Flush Folded Red BR Triangle!)
        objs.append(make_beveled_slab_xz(f"{hid}_CalCornerTR", rounded_rect_2d(-tile_hw + 0.037, tile_cz + tile_hh - 0.037, 0.038, 0.038, 0.016, 2), -0.119, +0.119, 0.007, 0.009, m_dblue, "icon_body", 1, 0.0, flat_faces=True))
        objs.append(make_beveled_slab_xz(f"{hid}_CalCornerBL", rounded_rect_2d(+tile_hw - 0.037, tile_cz - tile_hh + 0.037, 0.038, 0.038, 0.016, 2), -0.119, +0.119, 0.007, 0.009, m_dgreen, "icon_body", 1, 0.0, flat_faces=True))
        # Flush 3D Folded Red Bottom-Right Corner Triangle aligned 1:1 with the diagonal tile cut!
        red_fold = round_polygon_2d(
            [
                (-tile_hw + cut_s + 0.002, tile_cz - tile_hh + 0.002),
                (-tile_hw + cut_s + 0.002, tile_cz - tile_hh + cut_s + 0.002),
                (-tile_hw + 0.002,         tile_cz - tile_hh + cut_s + 0.002),
            ],
            0.010, arc_segs=2,
        )
        objs.append(make_beveled_slab_xz(f"{hid}_CalRedFold", red_fold, -0.120, +0.120, 0.007, 0.009, m_red, "icon_body", 1, 0.0, flat_faces=True))

        # Seamless Integrated Panoramic Cobalt Top-Header AI Optical Visor Hood
        hdr_contour = rounded_rect_2d(0.0, 1.630, 0.222, 0.094, radius=0.056, arc_segs=3)
        objs.append(make_beveled_slab_xz(f"{hid}_CalVisorHeader", hdr_contour, -0.104, +0.104, 0.020, 0.022, m_blue, "icon_crest", 2, 0.0, flat_faces=True))
        objs.extend(build_curved_ai_visor(
            f"{hid}_Visor", cx=0.0, cz=1.632, half_w=0.174, half_h=0.056,
            y_surface=0.105, visor_mat=m_visor, bezel_mat=m_metal,
            region_tag="icon_crest", curve_x=0.015, curve_z=0.005,
        ))
        objs.append(make_beveled_bar_xz(f"{hid}_CalRearGlow", (-0.112, 1.632), (+0.112, 1.632), 0.012, -0.118, -0.102, m_emissive, "icon_crest", True, 0.004, 1))
        for s_name, sx in (("R", 1.0), ("L", -1.0)):
            pin_pts = [Vector((sx * 0.126, 0.0, 1.710)), Vector((sx * 0.126, 0.0, 1.766))]
            objs.append(new_part_obj(f"{hid}_CalBinderPin_{s_name}", make_tube_along_curve(pin_pts, [(0.017, 0.019), (0.014, 0.016)], n_seg=8), m_metal, 0, "icon_crest"))
            objs.append(make_sphere_part(f"{hid}_CalBinderTip_{s_name}", Vector((sx * 0.126, 0.0, 1.770)), (0.015, 0.015, 0.013), m_emissive, "icon_crest", 1))

        return objs, 0.244, 1.340

    # -------------------------------------------------------------------------
    # 4. GOOGLE CHAT AI: Crisp Layered Dual Emerald Speech Bubbles + Unobstructed Typing Optics
    # -------------------------------------------------------------------------
    if prod == "chat":
        # Upper-Right Outer Rich Emerald Speech Bubble (viewer UPPER-RIGHT = -X)
        # Cleanly houses the ENTIRE curved AI optical visor + 3 glowing typing dots unobstructed!
        b_upper = rounded_rect_2d(-0.036, 1.505, 0.214, 0.178, radius=0.068, arc_segs=3)
        objs.append(make_beveled_slab_xz(
            f"{hid}_ChatBubbleUpper", b_upper, -0.104, +0.094, 0.020, 0.022,
            m_green, "icon_body", bevel_segs=2, dome_bulge=0.0, flat_faces=True,
        ))
        # Flush dark-emerald folded upper-right corner accent tucked strictly INSIDE upper-right (-X) corner!
        fold_ur = round_polygon_2d(
            [(-0.244, 1.592), (-0.156, 1.592), (-0.156, 1.676)],
            0.012, arc_segs=2,
        )
        objs.append(make_beveled_slab_xz(
            f"{hid}_ChatUpperFold", fold_ur, -0.109, +0.098, 0.006, 0.007, m_dgreen, "icon_body", 1, 0.0, flat_faces=True,
        ))

        # Lower-Left Overlapping Vibrant Mint-Emerald Front Speech Bubble (sits cleanly BELOW visor Z <= 1.355!)
        b_lower = rounded_rect_2d(+0.044, 1.190, 0.216, 0.162, radius=0.064, arc_segs=3)
        objs.append(make_beveled_slab_xz(
            f"{hid}_ChatBubbleLower", b_lower, -0.092, +0.106, 0.018, 0.020,
            m_mint, "icon_body", bevel_segs=2, dome_bulge=0.0, flat_faces=True,
        ))
        # Sculpted 3D Curved Speech-Bubble Pointer Tail sweeping down viewer's bottom-left (+X)!
        tail_poly = round_polygon_2d(
            [(+0.248, 1.135), (+0.254, 0.978), (+0.118, 1.055)],
            [0.014, 0.020, 0.014], arc_segs=2,
        )
        objs.append(make_beveled_slab_xz(
            f"{hid}_ChatTail", tail_poly, -0.084, +0.098, 0.010, 0.012, m_mint, "icon_body", 1, 0.0, flat_faces=True,
        ))

        # Crisp Luminous Ceramic-White Inner Chat Plaque on BOTH Front (+Y) AND Back (-Y)!
        inner_front = rounded_rect_2d(+0.044, 1.185, 0.164, 0.106, radius=0.036, arc_segs=2)
        objs.append(make_beveled_slab_xz(
            f"{hid}_ChatWhitePlaque", inner_front, -0.104, +0.116, 0.008, 0.007,
            m_chassis_tex, "icon_body", 1, 0.0, flat_faces=True,
        ))
        # Subtle recessed dark-emerald dual-bubble overlap line on back (-Y) only (clean visual depth!)
        back_seam = rounded_rect_2d(+0.004, 1.335, 0.155, 0.034, radius=0.018, arc_segs=2)
        objs.append(make_beveled_slab_xz(
            f"{hid}_ChatBackOverlap", back_seam, -0.111, -0.092, 0.006, 0.006, m_dgreen, "icon_body", 1, 0.0, flat_faces=True,
        ))
        # Sculpted 3D glowing white/mint typing pills on the BACK (-Y) upper bubble!
        for idx_d, dx in enumerate((-0.106, -0.036, +0.034)):
            objs.append(make_sphere_part(f"{hid}_BackTypingDot_{idx_d}", Vector((dx, -0.114, 1.515)), (0.022, 0.014, 0.022), m_white, "icon_body", 1))
            objs.append(make_torus_ring_part(f"{hid}_BackTypingHalo_{idx_d}", Vector((dx, -0.111, 1.515)), Vector((0, 1, 0)), 0.025, 0.0045, m_emissive, "icon_body", 10, 5))

        # Integrated Curved Dark-Glass AI Visor — 100% UNOBSTRUCTED on upper emerald bubble!
        # Houses joyful glowing mint-white AI eyes + 3 glowing typing-dot pips ('• • •')!
        objs.extend(build_curved_ai_visor(
            f"{hid}_Visor", cx=-0.026, cz=1.505, half_w=0.162, half_h=0.110,
            y_surface=0.098, visor_mat=m_visor, bezel_mat=m_metal,
            region_tag="icon_body", curve_x=0.017, curve_z=0.007,
        ))

        # Sleek Mini Emerald Comms Fin / Antenna on crown (subtle Head articulation!)
        fin_pts = [Vector((0.025, 0.0, 1.678)), Vector((0.052, -0.008, 1.735)), Vector((0.072, -0.014, 1.768))]
        objs.append(new_part_obj(f"{hid}_CommsFin", make_tube_along_curve(fin_pts, [(0.020, 0.016), (0.013, 0.011), (0.008, 0.008)], n_seg=7), m_metal, 0, "icon_crest"))
        objs.append(make_sphere_part(f"{hid}_CommsTip", Vector((0.075, -0.016, 1.774)), (0.015, 0.015, 0.015), m_emissive, "icon_crest", 1))

        return objs, 0.248, 1.338

    # -------------------------------------------------------------------------
    # 5. GOOGLE SLIDES AI: 3D Golden-Amber Dog-Eared Deck + 16:9 Visor + Projector
    # -------------------------------------------------------------------------
    if prod == "slides":
        page_cz, page_hw, page_hh, dog_s = 1.364, 0.236, 0.370, 0.142
        page_contour = dog_ear_page_2d(0.0, page_cz, page_hw, page_hh, dog_s, corner_r=0.044, arc_segs=3)
        objs.append(make_beveled_slab_xz(
            f"{hid}_SlidesDeckBody", page_contour, -0.096, +0.096, 0.018, 0.020,
            m_chassis_tex, "icon_body", bevel_segs=2, dome_bulge=0.0, flat_faces=True,
        ))

        # Crisp Flush 3D Folded Top-Right Dog-Ear Corner Flap (ZERO diagonal fan crease!)
        x_l = -page_hw
        z_t = page_cz + page_hh
        fold_poly = round_polygon_2d(
            [(x_l + dog_s + 0.002, z_t - 0.002), (x_l + dog_s + 0.002, z_t - dog_s - 0.002), (x_l + 0.002, z_t - dog_s - 0.002)],
            0.012, arc_segs=2,
        )
        objs.append(make_beveled_slab_xz(
            f"{hid}_SlidesDogEar", fold_poly, -0.109, +0.109, 0.008, 0.010, m_dyellow, "icon_body", 1, 0.0, flat_faces=True,
        ))

        # Crisp Sculpted 3D White Ceramic 16:9 Presentation Slide Frame on BOTH Front (+Y) AND Back (-Y)
        for face_name, y_in, y_out, f_cz in (("Front", +0.095, +0.115, 1.425), ("Back", -0.115, -0.095, 1.335)):
            fw, fh, bt = 0.174, 0.112, 0.018
            objs.append(make_beveled_bar_xz(f"{hid}_SlideFrmTop_{face_name}", (+fw, f_cz + fh), (-fw, f_cz + fh), bt, y_in, y_out, m_white, "icon_body", True, 0.005, 1))
            objs.append(make_beveled_bar_xz(f"{hid}_SlideFrmBot_{face_name}", (+fw, f_cz - fh), (-fw, f_cz - fh), bt, y_in, y_out, m_white, "icon_body", True, 0.005, 1))
            objs.append(make_beveled_bar_xz(f"{hid}_SlideFrmL_{face_name}",   (+fw, f_cz - fh), (+fw, f_cz + fh), bt, y_in, y_out, m_white, "icon_body", True, 0.005, 1))
            objs.append(make_beveled_bar_xz(f"{hid}_SlideFrmR_{face_name}",   (-fw, f_cz - fh), (-fw, f_cz + fh), bt, y_in, y_out, m_white, "icon_body", True, 0.005, 1))

        # Front (+Y) Curved Dark-Glass 16:9 AI Optical Visor inside the crisp white slide frame!
        objs.extend(build_curved_ai_visor(
            f"{hid}_Visor", cx=0.0, cz=1.425, half_w=0.154, half_h=0.092,
            y_surface=0.099, visor_mat=m_visor, bezel_mat=m_dark,
            region_tag="icon_body", curve_x=0.015, curve_z=0.005, bezel_r=0.006,
        ))
        objs.append(make_beveled_bar_xz(f"{hid}_FrontSlideAccent", (-0.105, 1.155), (+0.105, 1.155), 0.013, +0.096, +0.112, m_white, "icon_body", True, 0.004, 1))

        # Back (-Y) Recessed Sleek Dark-Gold Presentation Screen inside the white 16:9 frame + golden chart bars!
        objs.append(make_beveled_slab_xz(
            f"{hid}_BackSlideScreen", rounded_rect_2d(0.0, 1.335, 0.150, 0.088, 0.012, 2),
            -0.104, -0.094, 0.004, 0.004, m_dyellow, "icon_body", 1, 0.0, flat_faces=True,
        ))
        for b_idx, (bx, bh) in enumerate(((-0.072, 0.044), (0.0, 0.076), (+0.072, 0.058))):
            objs.append(make_beveled_bar_xz(
                f"{hid}_BackChartBar_{b_idx}",
                (bx, 1.285), (bx, 1.285 + bh), 0.018, -0.111, -0.101, m_emissive, "icon_body", True, 0.004, 1,
            ))

        # Miniature Holographic Projector Lens Pod on upper-left shoulder corner (+X top)
        proj_c = Vector((+0.166, 0.010, 1.754))
        objs.append(new_part_obj(f"{hid}_ProjStem", make_tube_along_curve([Vector((+0.166, 0.0, 1.714)), proj_c], [(0.017, 0.019), (0.014, 0.016)], n_seg=7), m_metal, 0, "icon_crest"))
        objs.append(new_part_obj(
            f"{hid}_ProjBarrel",
            make_tube_along_curve([proj_c + Vector((0, -0.046, 0.012)), proj_c + Vector((0, 0.018, 0.012)), proj_c + Vector((0, 0.054, 0.012))], [(0.023, 0.021), (0.027, 0.025), (0.024, 0.023)], n_seg=8),
            m_dark, 0, "icon_crest",
        ))
        objs.append(make_sphere_part(f"{hid}_ProjLens", proj_c + Vector((0.0, 0.058, 0.012)), (0.019, 0.010, 0.019), m_emissive, "icon_crest", 1))
        objs.append(make_torus_ring_part(f"{hid}_ProjRing", proj_c + Vector((0.0, 0.050, 0.012)), Vector((0, 1, 0)), 0.025, 0.0045, m_yellow, "icon_crest", 12, 5))

        return objs, 0.238, 1.345

    # -------------------------------------------------------------------------
    # 6. GOOGLE DOCS AI: 3D Cobalt-Blue Dog-Eared Page + Raised White Text Bars
    # -------------------------------------------------------------------------
    page_cz, page_hw, page_hh, dog_s = 1.364, 0.236, 0.370, 0.142
    page_contour = dog_ear_page_2d(0.0, page_cz, page_hw, page_hh, dog_s, corner_r=0.044, arc_segs=3)
    objs.append(make_beveled_slab_xz(
        f"{hid}_DocsPageBody", page_contour, -0.096, +0.096, 0.018, 0.020,
        m_chassis_tex, "icon_body", bevel_segs=2, dome_bulge=0.0, flat_faces=True,
    ))

    # Crisp Flush 3D Folded Top-Right Dog-Ear Corner Flap (Deep Royal Blue, ZERO diagonal crease!)
    x_l = -page_hw
    z_t = page_cz + page_hh
    fold_poly = round_polygon_2d(
        [(x_l + dog_s + 0.002, z_t - 0.002), (x_l + dog_s + 0.002, z_t - dog_s - 0.002), (x_l + 0.002, z_t - dog_s - 0.002)],
        0.012, arc_segs=2,
    )
    objs.append(make_beveled_slab_xz(
        f"{hid}_DocsDogEar", fold_poly, -0.109, +0.109, 0.008, 0.010, m_dblue, "icon_body", 1, 0.0, flat_faces=True,
    ))

    # Curved Dark-Glass AI Optical Visor cleanly set into upper blue page header
    objs.extend(build_curved_ai_visor(
        f"{hid}_Visor", cx=0.016, cz=1.544, half_w=0.148, half_h=0.072,
        y_surface=0.098, visor_mat=m_visor, bezel_mat=m_metal,
        region_tag="icon_body", curve_x=0.015, curve_z=0.006, bezel_r=0.006,
    ))

    # Raised Glossy 3D Ceramic-White Horizontal Document Text-Line Bars on FRONT (+Y)
    for idx_l, (zl, x0, x1) in enumerate((
        (1.374, +0.152, -0.152),
        (1.288, +0.152, -0.152),
        (1.202, +0.152, -0.152),
        (1.116, +0.152, -0.020),
    )):
        objs.append(make_beveled_bar_xz(f"{hid}_DocsFrontLine_{idx_l}", (x0, zl), (x1, zl), 0.021, +0.095, +0.118, m_white, "icon_body", True, 0.006, 1))

    # Raised Glossy 3D Ceramic-White Horizontal Document Text-Line Bars on BACK (-Y)
    for idx_l, (zl, x0, x1) in enumerate((
        (1.454, -0.152, +0.152),
        (1.360, -0.152, +0.152),
        (1.266, -0.152, +0.152),
        (1.172, -0.152, +0.020),
    )):
        objs.append(make_beveled_bar_xz(f"{hid}_DocsBackLine_{idx_l}", (x0, zl), (x1, zl), 0.021, -0.118, -0.095, m_white, "icon_body", True, 0.006, 1))

    # Sleek Glowing Sky-Blue AI Header Status Node on top crown
    objs.append(make_beveled_bar_xz(f"{hid}_DocsCrownNode", (+0.046, 1.756), (+0.144, 1.756), 0.015, -0.022, +0.022, m_metal, "icon_crest", True, 0.005, 1))
    objs.append(make_beveled_bar_xz(f"{hid}_DocsCrownLED", (+0.058, 1.764), (+0.132, 1.764), 0.008, -0.012, +0.025, m_emissive, "icon_crest", True, 0.003, 1))

    return objs, 0.238, 1.345


# =============================================================================
# 6. SLEEK ARTICULATED AI ARMS, ERGONOMIC HANDS, PELVIS, LEGS & AERO-BOOTS
# =============================================================================

def build_ai_arms_and_hands(
    cfg: dict,
    sh_x: float,
    sh_z: float,
    mats: Dict[str, bpy.types.Material],
) -> Tuple[List[bpy.types.Object], Dict[str, Vector]]:
    hid = cfg["id"]
    prod = cfg["product"]
    m_shell = mats["limb_shell"]
    m_accent = mats["limb_accent"]
    m_dark = mats["anodized_dark"]
    m_metal = mats["titanium"]
    m_emissive = mats["emissive"]

    joints: Dict[str, Vector] = {}
    objs: List[bpy.types.Object] = []

    for side_name, sx in (("R", 1.0), ("L", -1.0)):
        p_sh = Vector((sx * sh_x,            0.000, sh_z))
        p_el = Vector((sx * (sh_x + 0.074), -0.012, sh_z - 0.278))
        p_wr = Vector((sx * (sh_x + 0.118), +0.024, sh_z - 0.546))
        p_hd = Vector((sx * (sh_x + 0.128), +0.038, sh_z - 0.624))

        joints[f"Shoulder_{side_name}"] = p_sh
        joints[f"Elbow_{side_name}"] = p_el
        joints[f"Wrist_{side_name}"] = p_wr
        joints[f"Hand_{side_name}"] = p_hd

        u_dir = (p_el - p_sh).normalized()
        l_dir = (p_wr - p_el).normalized()

        # 1. Recessed Shoulder Socket Collar & Glowing Ring anchored rigidly on icon flank
        sock_pts = [p_sh - Vector((sx * 0.032, 0.0, 0.0)), p_sh - Vector((sx * 0.008, 0.0, 0.0))]
        objs.append(new_part_obj(f"{hid}_ShSocket_{side_name}", make_tube_along_curve(sock_pts, [(0.043, 0.046), (0.037, 0.040)], n_seg=8), m_dark, 0, "icon_body"))
        objs.append(make_torus_ring_part(f"{hid}_ShGlowRing_{side_name}", p_sh - Vector((sx * 0.012, 0.0, 0.0)), Vector((sx, 0, 0)), 0.038, 0.0045, m_emissive, "icon_body", 12, 5))

        # 2. Precision Titanium Shoulder Ball Joint + Sculpted Shoulder Pauldron Cap
        objs.append(make_sphere_part(f"{hid}_ShBall_{side_name}", p_sh, (0.035, 0.036, 0.036), m_metal, f"upper_arm_{side_name}", 1))
        objs.append(make_sphere_part(f"{hid}_ShCap_{side_name}", p_sh + Vector((sx * 0.010, 0.0, 0.014)), (0.042, 0.042, 0.033), m_accent, f"upper_arm_{side_name}", 1))

        # 3. Tapered Glossy Ceramic Upper Arm Fairing
        ua_pts = [p_sh + u_dir * 0.022, p_sh.lerp(p_el, 0.30), p_sh.lerp(p_el, 0.68), p_el - u_dir * 0.024]
        ua_rads = [(0.036, 0.038), (0.043, 0.045), (0.036, 0.038), (0.029, 0.031)]
        objs.append(new_part_obj(f"{hid}_UpperArm_{side_name}", make_tube_along_curve(ua_pts, ua_rads, n_seg=10, cap_start=True, cap_end=True), m_shell, 0, f"upper_arm_{side_name}"))

        # 4. Articulated Titanium Elbow Sphere Joint + Accent Ring
        objs.append(make_sphere_part(f"{hid}_ElbowBall_{side_name}", p_el, (0.030, 0.031, 0.031), m_metal, f"elbow_{side_name}", 1))
        objs.append(make_torus_ring_part(f"{hid}_ElbowRing_{side_name}", p_el, u_dir + l_dir, 0.031, 0.004, m_accent, f"elbow_{side_name}", 10, 5))

        # 5. Sleek Sculpted Ceramic Forearm Gauntlet Shell + Glowing Wrist Cuff
        fa_pts = [p_el + l_dir * 0.022, p_el.lerp(p_wr, 0.30), p_el.lerp(p_wr, 0.70), p_wr - l_dir * 0.014]
        fa_rads = [(0.030, 0.032), (0.039, 0.041), (0.034, 0.035), (0.027, 0.026)]
        objs.append(new_part_obj(f"{hid}_Forearm_{side_name}", make_tube_along_curve(fa_pts, fa_rads, n_seg=10, cap_start=True, cap_end=True), m_shell, 0, f"lower_arm_{side_name}"))
        wc0, wc1 = p_el.lerp(p_wr, 0.78), p_el.lerp(p_wr, 0.94)
        objs.append(new_part_obj(f"{hid}_WristCuff_{side_name}", make_tube_along_curve([wc0, wc1], [(0.036, 0.036), (0.032, 0.031)], n_seg=8), m_accent, 0, f"lower_arm_{side_name}"))
        objs.append(make_torus_ring_part(f"{hid}_WristGlow_{side_name}", wc0.lerp(wc1, 0.5), l_dir, 0.0355, 0.0045, m_emissive, f"lower_arm_{side_name}", 12, 5))

        if side_name == "L" and prod in ("drive", "calendar", "docs"):
            objs.append(make_torus_ring_part(f"{hid}_HeroTechRing_L", p_el.lerp(p_wr, 0.72), l_dir, 0.040, 0.0055, m_emissive, "lower_arm_L", 12, 5))

        # 6. Articulated Ergonomic AI Gripping Hand (1:1 match to RIGHT/LEFT_PALM_LOCAL!)
        h_dir = (p_hd - p_wr).normalized()
        fwd = Vector((0.0, 1.0, 0.0))
        out_v = h_dir.cross(fwd).normalized()
        if out_v.x * sx < 0:
            out_v = -out_v
        fwd = out_v.cross(h_dir).normalized()
        if fwd.y < 0:
            fwd = -fwd

        objs.append(make_sphere_part(f"{hid}_WristBall_{side_name}", p_wr, (0.022, 0.022, 0.022), m_metal, f"hand_{side_name}", 1))

        palm_pts = [
            p_wr - h_dir * 0.006,
            p_wr + h_dir * 0.024,
            p_wr + h_dir * 0.058 - out_v * 0.004,
            p_wr + h_dir * 0.082 - out_v * 0.008,
        ]
        palm_r = [(0.022, 0.025), (0.019, 0.034), (0.017, 0.038), (0.014, 0.035)]
        p_rings = [[pt + out_v * (math.cos(2 * math.pi * s / 8) * rt) + fwd * (math.sin(2 * math.pi * s / 8) * rw) for s in range(8)] for pt, (rt, rw) in zip(palm_pts, palm_r)]
        objs.append(new_part_obj(f"{hid}_Palm_{side_name}", loft_rings_bmesh(p_rings, True, True), m_dark, 0, f"hand_{side_name}"))

        kn_pts = [p_wr + h_dir * 0.022 + out_v * 0.013, p_wr + h_dir * 0.054 + out_v * 0.012, p_wr + h_dir * 0.078 + out_v * 0.006]
        objs.append(new_part_obj(f"{hid}_HandPlate_{side_name}", make_tube_along_curve(kn_pts, [(0.008, 0.024), (0.009, 0.028), (0.007, 0.025)], n_seg=6), m_shell, 0, f"hand_{side_name}"))

        th0 = p_wr + h_dir * 0.028 + fwd * 0.024 - out_v * 0.008
        th1 = th0 + h_dir * 0.030 + fwd * 0.024 - out_v * 0.016
        th2 = th1 + h_dir * 0.022 + fwd * 0.006 - out_v * 0.018
        objs.append(new_part_obj(f"{hid}_Thumb_{side_name}", make_tube_along_curve([th0, th1, th2], [(0.011, 0.012), (0.0095, 0.010), (0.0075, 0.008)], n_seg=6), m_shell, 0, f"hand_{side_name}"))

        knuckle = p_wr + h_dir * 0.078 - out_v * 0.008
        idx0 = knuckle + fwd * 0.022
        idx1 = idx0 + h_dir * 0.032 - out_v * 0.016 + fwd * 0.002
        idx2 = idx1 + h_dir * 0.024 - out_v * 0.024
        objs.append(new_part_obj(f"{hid}_Index_{side_name}", make_tube_along_curve([idx0, idx1, idx2], [(0.009, 0.009), (0.008, 0.008), (0.0065, 0.0065)], n_seg=6), m_shell, 0, f"hand_{side_name}"))

        fg_pts = [
            knuckle - fwd * 0.008,
            knuckle - fwd * 0.008 + h_dir * 0.032 - out_v * 0.018,
            knuckle - fwd * 0.008 + h_dir * 0.052 - out_v * 0.042,
        ]
        fg_r = [(0.012, 0.024), (0.011, 0.023), (0.008, 0.019)]
        fg_rings = [[pt + out_v * (math.cos(2 * math.pi * s / 6) * rt) + fwd * (math.sin(2 * math.pi * s / 6) * rw) for s in range(6)] for pt, (rt, rw) in zip(fg_pts, fg_r)]
        objs.append(new_part_obj(f"{hid}_Fingers_{side_name}", loft_rings_bmesh(fg_rings, True, True), m_dark, 0, f"hand_{side_name}"))

    return objs, joints


def build_ai_pelvis_legs_and_boots(
    cfg: dict,
    mats: Dict[str, bpy.types.Material],
) -> Tuple[List[bpy.types.Object], Dict[str, Vector]]:
    hid = cfg["id"]
    m_shell = mats["limb_shell"]
    m_thigh = mats["thigh_shell"]
    m_accent = mats["limb_accent"]
    m_dark = mats["anodized_dark"]
    m_metal = mats["titanium"]
    m_sole = mats["boot_sole"]
    m_boot = mats["boot_upper"]
    m_emissive = mats["emissive"]

    hip_x = 0.104
    objs: List[bpy.types.Object] = []
    joints: Dict[str, Vector] = {}

    # 1. Articulated Waist Gimbal Bellows + Luminous Waist Ring
    waist_levels = [(0.915, 0.118, 0.078), (0.955, 0.098, 0.068), (0.992, 0.116, 0.076), (1.032, 0.132, 0.082)]
    w_rings = [
        [Vector((math.copysign(abs(math.cos(2 * math.pi * s / 12)) ** 0.85, math.cos(2 * math.pi * s / 12)) * rx, math.sin(2 * math.pi * s / 12) * ry, z_w)) for s in range(12)]
        for z_w, rx, ry in waist_levels
    ]
    objs.append(new_part_obj(f"{hid}_WaistGimbal", loft_rings_bmesh(w_rings, True, True), m_dark, 0, "waist_gimbal"))
    objs.append(make_torus_ring_part(f"{hid}_WaistGlowRing", Vector((0.0, 0.0, 0.962)), Vector((0.0, 0.0, 1.0)), 0.102, 0.0065, m_emissive, "waist_gimbal", 14, 5))

    # 2. Compact Sculpted AI Hip Pelvis Core
    pelvis_levels = [(0.795, 0.068, 0.062), (0.842, 0.136, 0.088), (0.892, 0.152, 0.094), (0.935, 0.138, 0.088)]
    p_rings = [
        [Vector((math.copysign(abs(math.cos(2 * math.pi * s / 12)) ** 0.85, math.cos(2 * math.pi * s / 12)) * rx, math.sin(2 * math.pi * s / 12) * ry, z_p)) for s in range(12)]
        for z_p, rx, ry in pelvis_levels
    ]
    objs.append(new_part_obj(f"{hid}_PelvisCore", loft_rings_bmesh(p_rings, True, True), m_shell, 0, "pelvis"))
    objs.append(make_beveled_slab_xz(f"{hid}_PelvisBeltAccent", rounded_rect_2d(0.0, 0.892, 0.054, 0.026, 0.011, 2), -0.097, +0.097, 0.005, 0.005, m_accent, "pelvis", 1, 0.0, flat_faces=True))

    # 3. Agile Athletic AI Legs + Illuminated Knee Rings + Futuristic Sneaker-Boots
    for side_name, sx in (("R", 1.0), ("L", -1.0)):
        p_hip = Vector((sx * hip_x, 0.000, 0.885))
        p_knee = Vector((sx * (hip_x + 0.006), +0.010, 0.492))
        p_ank = Vector((sx * (hip_x + 0.008), -0.006, 0.094))
        p_ft = Vector((sx * (hip_x + 0.008), +0.136, 0.026))

        joints[f"Hip_{side_name}"] = p_hip
        joints[f"Knee_{side_name}"] = p_knee
        joints[f"Ankle_{side_name}"] = p_ank
        joints[f"Foot_{side_name}"] = p_ft

        objs.append(make_sphere_part(f"{hid}_HipBall_{side_name}", p_hip, (0.044, 0.046, 0.046), m_metal, f"thigh_{side_name}", 1))

        # Sleek Sculpted Satin-Titanium Tapered Thigh + Clean Side Accent Band (zero awkward white oval bump!)
        th_dir = (p_knee - p_hip).normalized()
        th_pts = [p_hip + th_dir * 0.022, p_hip.lerp(p_knee, 0.30), p_hip.lerp(p_knee, 0.68), p_knee - th_dir * 0.036]
        th_rads = [(0.054, 0.058), (0.068, 0.072), (0.058, 0.062), (0.044, 0.046)]
        objs.append(new_part_obj(f"{hid}_Thigh_{side_name}", make_tube_along_curve(th_pts, th_rads, n_seg=12, cap_start=True, cap_end=True), m_thigh, 0, f"thigh_{side_name}"))
        # Sleek upper thigh accent band
        b0, b1 = p_hip.lerp(p_knee, 0.24), p_hip.lerp(p_knee, 0.36)
        objs.append(new_part_obj(f"{hid}_ThighBand_{side_name}", make_tube_along_curve([b0, b1], [(0.070, 0.074), (0.069, 0.073)], n_seg=10), m_accent, 0, f"thigh_{side_name}"))

        # Mechanical Knee Sphere + Glowing Product Knee Ring + Knee Cap
        objs.append(make_sphere_part(f"{hid}_KneeBall_{side_name}", p_knee, (0.042, 0.045, 0.042), m_metal, f"knee_{side_name}", 1))
        objs.append(make_torus_ring_part(f"{hid}_KneeGlowRing_{side_name}", p_knee + Vector((0.0, 0.004, 0.0)), Vector((0.0, 0.0, 1.0)), 0.048, 0.006, m_emissive, f"knee_{side_name}", 12, 5))
        objs.append(make_sphere_part(f"{hid}_KneeCap_{side_name}", p_knee + Vector((0.0, 0.040, 0.004)), (0.029, 0.015, 0.029), m_accent, f"knee_{side_name}", 1))

        # Sculpted Athletic AI Calf / Shin Fairing
        sh_dir = (p_ank - p_knee).normalized()
        sh_pts = [p_knee + sh_dir * 0.034, p_knee.lerp(p_ank, 0.34) + Vector((0.0, -0.012, 0.0)), p_knee.lerp(p_ank, 0.72) + Vector((0.0, -0.006, 0.0)), p_ank - sh_dir * 0.018]
        sh_rads = [(0.044, 0.047), (0.056, 0.062), (0.044, 0.046), (0.034, 0.036)]
        objs.append(new_part_obj(f"{hid}_Shin_{side_name}", make_tube_along_curve(sh_pts, sh_rads, n_seg=12, cap_start=True, cap_end=True), m_shell, 0, f"shin_{side_name}"))
        objs.append(make_sphere_part(f"{hid}_AnkleBall_{side_name}", p_ank, (0.030, 0.032, 0.030), m_metal, f"foot_{side_name}", 1))

        # Sleek Futuristic Rounded Sneaker-Boot strictly grounded at Z = 0.000m!
        fx = sx * (hip_x + 0.008)
        sole_slices = [
            (0.000, -0.068, 0.168, 0.046, 0.054),
            (0.014, -0.074, 0.180, 0.050, 0.058),
            (0.032, -0.072, 0.176, 0.048, 0.055),
            (0.040, -0.066, 0.162, 0.045, 0.052),
        ]
        s_rings = []
        for z_s, yb, yf, wh, wb in sole_slices:
            ring = []
            for s in range(12):
                a = 2.0 * math.pi * s / 12
                ca, sa = math.cos(a), math.sin(a)
                t_ft = (sa + 1.0) * 0.5
                w_local = wh * (1.0 - t_ft) + wb * t_ft
                if t_ft > 0.72:
                    w_local *= 1.0 - 0.18 * ((t_ft - 0.72) / 0.28)
                z_sp = 0.007 * max(0.0, (t_ft - 0.85) / 0.15) ** 2 if z_s == 0.0 else 0.0
                ring.append(Vector((fx + ca * w_local, yb + t_ft * (yf - yb), z_s + z_sp)))
            s_rings.append(ring)
        objs.append(new_part_obj(f"{hid}_BootSole_{side_name}", loft_rings_bmesh(s_rings, True, True), m_sole, 0, f"foot_{side_name}"))

        up_slices = [
            (0.032, -0.066, 0.168, 0.045, 0.052),
            (0.056, -0.064, 0.148, 0.044, 0.048),
            (0.080, -0.058, 0.094, 0.042, 0.044),
            (0.102, -0.050, 0.048, 0.040, 0.040),
            (0.118, -0.042, 0.030, 0.040, 0.039),
        ]
        u_rings = []
        for z_u, yb, yf, wh, wb in up_slices:
            ring = []
            for s in range(12):
                a = 2.0 * math.pi * s / 12
                ca, sa = math.cos(a), math.sin(a)
                t_ft = (sa + 1.0) * 0.5
                w_local = wh * (1.0 - t_ft) + wb * t_ft
                ring.append(Vector((fx + ca * w_local, yb + t_ft * (yf - yb), z_u)))
            u_rings.append(ring)
        objs.append(new_part_obj(f"{hid}_BootUpper_{side_name}", loft_rings_bmesh(u_rings, True, True), m_boot, 0, f"foot_{side_name}"))

        heel_pts = [Vector((fx - 0.042, -0.052, 0.046)), Vector((fx, -0.072, 0.048)), Vector((fx + 0.042, -0.052, 0.046))]
        objs.append(new_part_obj(f"{hid}_BootHeelGlow_{side_name}", make_tube_along_curve(heel_pts, [(0.0055, 0.0055)] * 3, n_seg=5), m_emissive, 0, f"foot_{side_name}"))
        strap_pts = [Vector((fx - 0.042, 0.055, 0.074)), Vector((fx, 0.082, 0.082)), Vector((fx + 0.042, 0.055, 0.074))]
        objs.append(new_part_obj(f"{hid}_BootStrap_{side_name}", make_tube_along_curve(strap_pts, [(0.0075, 0.0055)] * 3, n_seg=5), m_accent, 0, f"foot_{side_name}"))

    return objs, joints


# =============================================================================
# 7. EXACT 18-BONE ARMATURE, PRECISION RIGID/BALL-JOINT SKINNING & 12 NLA CLIPS
# =============================================================================

BONE_NAMES = [
    "Root", "Pelvis", "Spine", "Chest", "Neck", "Head",
    "UpperArm_L", "LowerArm_L", "Hand_L",
    "UpperArm_R", "LowerArm_R", "Hand_R",
    "Thigh_L", "Shin_L", "Foot_L",
    "Thigh_R", "Shin_R", "Foot_R",
]

GLIDE_GRIP_HALF_SPAN = 0.235
GLIDE_BAR_Y_BLENDER = 0.180
GLIDE_BAR_Z_BLENDER = 1.905
GLIDE_HAND_PITCH_DEG = 24.0
GLIDE_PALM_ALONG_HAND = 0.092
GLIDE_PALM_INWARD_OFF = 0.020

RIFLE_FOREGRIP_DIST = 0.290
RIFLE_FOREGRIP_UP   = 0.064
RIGHT_PALM_LOCAL = Vector((-0.026, 0.076, 0.015))
LEFT_PALM_LOCAL  = Vector((+0.030, 0.092, 0.006))

EXPECTED_ANIMATIONS = [
    "Idle", "Run", "Sprint", "Crouch", "Aim", "Reload", "Glide", "Jump",
    "IdleArmed", "RunArmed", "SprintArmed", "JumpArmed", "LobbyShowcase",
]

LOBBY_SHOWCASE_FRAMES = list(range(1, 62, 2))  # 31 keyframes (frames 1..61, step 2, 2.50s @ 24fps)

# Signature lobby weapon pairing & Three.js WEAPON_GRIP_TUNE (converted to Blender weapon axes: +X right, +Y barrel, +Z up)
LOBBY_SHOWCASE_META: Dict[str, dict] = {
    "gmail": {
        "title": "Tactical Sweep",
        "armed": True,
        "weapon_glb": "weapon_vanguard_m4.glb",
        "weapon_label": "Vanguard M4",
        "grip_tune_blender": Vector((0.0, 0.0, 0.0)),
        "fallback_bbox": ((-0.025, 0.026), (-0.275, 0.545), (-0.154, 0.174)),
    },
    "drive": {
        "title": "Warden Guard",
        "armed": True,
        "weapon_glb": "weapon_breaker_12g.glb",
        "weapon_label": "Breaker 12G",
        "grip_tune_blender": Vector((0.0, 0.0, 0.006)),
        "fallback_bbox": ((-0.041, 0.032), (-0.295, 0.585), (-0.071, 0.150)),
    },
    "calendar": {
        "title": "Chrono Check",
        "armed": False,
        "weapon_glb": None,
        "weapon_label": "Unarmed",
        "grip_tune_blender": Vector((0.0, 0.0, 0.0)),
        "fallback_bbox": None,
    },
    "chat": {
        "title": "Recon Peek",
        "armed": True,
        "weapon_glb": "weapon_vector_9.glb",
        "weapon_label": "Vector-9 SMG",
        "grip_tune_blender": Vector((0.0, 0.014, 0.008)),
        "fallback_bbox": ((-0.042, 0.024), (-0.185, 0.335), (-0.214, 0.165)),
    },
    "slides": {
        "title": "Spotlight Sightline",
        "armed": True,
        "weapon_glb": "weapon_longbow_308.glb",
        "weapon_label": "Longbow .308",
        "grip_tune_blender": Vector((0.0, 0.010, 0.0)),
        "fallback_bbox": ((-0.036, 0.078), (-0.320, 0.860), (-0.073, 0.204)),
    },
    "docs": {
        "title": "Version Hover",
        "armed": True,
        "weapon_glb": "weapon_nova_gl40.glb",
        "weapon_label": "Nova GL-40",
        "grip_tune_blender": Vector((0.0, 0.006, 0.0)),
        "fallback_bbox": ((-0.066, 0.066), (-0.265, 0.515), (-0.073, 0.194)),
    },
}


def build_armature_and_socket(cfg: dict, joints: Dict[str, Vector]) -> Tuple[bpy.types.Object, bpy.types.Object]:
    scale_h = cfg["height_scale"]
    arm_data = bpy.data.armatures.new(f"{cfg['id']}_Armature")
    arm_obj = bpy.data.objects.new("Armature", arm_data)
    bpy.context.scene.collection.objects.link(arm_obj)
    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode="EDIT")

    def add_bone(name: str, head: Vector, tail: Vector, parent_name: Optional[str], roll_target: Vector) -> None:
        eb = arm_data.edit_bones.new(name)
        eb.head = head
        eb.tail = tail
        if parent_name:
            eb.parent = arm_data.edit_bones[parent_name]
        eb.align_roll(roll_target)

    fwd = Vector((0.0, 1.0, 0.0))
    up = Vector((0.0, 0.0, 1.0))

    add_bone("Root",   Vector((0, 0, 0.0)),                Vector((0, 0, 0.16 * scale_h)),  None,     fwd)
    add_bone("Pelvis", Vector((0, 0, 0.885 * scale_h)),    Vector((0, 0, 1.000 * scale_h)), "Root",   fwd)
    add_bone("Spine",  Vector((0, 0, 1.000 * scale_h)),    Vector((0, 0, 1.215 * scale_h)), "Pelvis", fwd)
    add_bone("Chest",  Vector((0, 0, 1.215 * scale_h)),    Vector((0, 0, 1.460 * scale_h)), "Spine",  fwd)
    add_bone("Neck",   Vector((0, 0, 1.460 * scale_h)),    Vector((0, 0, 1.540 * scale_h)), "Chest",  fwd)
    add_bone("Head",   Vector((0, 0, 1.540 * scale_h)),    Vector((0, 0, 1.765 * scale_h)), "Neck",   fwd)

    for s in ("L", "R"):
        add_bone(f"UpperArm_{s}", joints[f"Shoulder_{s}"], joints[f"Elbow_{s}"], "Chest",        fwd)
        add_bone(f"LowerArm_{s}", joints[f"Elbow_{s}"],    joints[f"Wrist_{s}"], f"UpperArm_{s}", fwd)
        add_bone(f"Hand_{s}",     joints[f"Wrist_{s}"],    joints[f"Hand_{s}"],  f"LowerArm_{s}", fwd)
        add_bone(f"Thigh_{s}",    joints[f"Hip_{s}"],      joints[f"Knee_{s}"],  "Pelvis",        fwd)
        add_bone(f"Shin_{s}",     joints[f"Knee_{s}"],     joints[f"Ankle_{s}"], f"Thigh_{s}",    fwd)
        add_bone(f"Foot_{s}",     joints[f"Ankle_{s}"],    joints[f"Foot_{s}"],  f"Shin_{s}",     up)

    bpy.ops.object.mode_set(mode="OBJECT")

    sock = bpy.data.objects.new("WeaponSocket_R", None)
    sock.empty_display_type = "ARROWS"
    sock.empty_display_size = 0.08
    bpy.context.scene.collection.objects.link(sock)
    sock.parent = arm_obj
    sock.parent_type = "BONE"
    sock.parent_bone = "Hand_R"
    bpy.context.view_layer.update()
    pb_hand_r = arm_obj.pose.bones["Hand_R"]
    m_hand_r_rest = arm_obj.matrix_world @ pb_hand_r.bone.matrix_local
    sock.matrix_world = m_hand_r_rest @ Matrix.Translation(RIGHT_PALM_LOCAL * scale_h)
    bpy.context.view_layer.update()

    return arm_obj, sock


def _hermite(a: float, b: float, x: float) -> float:
    t = max(0.0, min(1.0, (x - a) / max(b - a, 1e-6)))
    return t * t * (3.0 - 2.0 * t)


def compute_vertex_weights(co: Vector, region: str, scale_h: float, joints: Dict[str, Vector]) -> Dict[str, float]:
    z = co.z / scale_h
    w: Dict[str, float] = {}

    if region == "icon_body":
        w["Chest"] = 1.0
    elif region == "icon_crest":
        w["Chest"] = 0.78
        w["Neck"] = 0.07
        w["Head"] = 0.15
    elif region == "waist_gimbal":
        t = _hermite(0.915, 1.025, z)
        if t < 0.5:
            u = t * 2.0
            w["Pelvis"] = 1.0 - u
            w["Spine"] = u
        else:
            u = (t - 0.5) * 2.0
            w["Spine"] = 1.0 - u
            w["Chest"] = u
    elif region == "pelvis":
        t = _hermite(0.89, 0.94, z)
        w["Pelvis"] = 1.0 - 0.15 * t
        w["Spine"] = 0.15 * t
    elif region in ("upper_arm_L", "upper_arm_R"):
        w[f"UpperArm_{region[-1]}"] = 1.0
    elif region in ("elbow_L", "elbow_R"):
        s = region[-1]
        w[f"UpperArm_{s}"] = 0.50
        w[f"LowerArm_{s}"] = 0.50
    elif region in ("lower_arm_L", "lower_arm_R"):
        w[f"LowerArm_{region[-1]}"] = 1.0
    elif region in ("hand_L", "hand_R"):
        s = region[-1]
        p_wr, p_hd = joints[f"Wrist_{s}"], joints[f"Hand_{s}"]
        seg = p_hd - p_wr
        t = (co - p_wr).dot(seg) / max(seg.length_squared, 1e-6)
        blend = _hermite(-0.10, 0.14, t)
        w[f"LowerArm_{s}"] = 1.0 - blend
        w[f"Hand_{s}"] = blend
    elif region in ("thigh_L", "thigh_R"):
        w[f"Thigh_{region[-1]}"] = 1.0
    elif region in ("knee_L", "knee_R"):
        s = region[-1]
        w[f"Thigh_{s}"] = 0.50
        w[f"Shin_{s}"] = 0.50
    elif region in ("shin_L", "shin_R"):
        w[f"Shin_{region[-1]}"] = 1.0
    elif region in ("foot_L", "foot_R"):
        w[f"Foot_{region[-1]}"] = 1.0
    else:
        w["Chest"] = 1.0

    total = sum(w.values())
    if total > 1e-6:
        for k in list(w.keys()):
            w[k] /= total
    else:
        w["Chest"] = 1.0
    return w


def join_and_skin_hero(
    cfg: dict,
    part_objs: List[bpy.types.Object],
    arm_obj: bpy.types.Object,
    joints: Dict[str, Vector],
) -> bpy.types.Object:
    scale_h = cfg["height_scale"]

    for obj in part_objs:
        region = obj.get("region_tag", "icon_body")
        vgs = {bname: obj.vertex_groups.new(name=bname) for bname in BONE_NAMES}
        for v in obj.data.vertices:
            for bname, val in compute_vertex_weights(v.co, region, scale_h, joints).items():
                if val > 0.001:
                    vgs[bname].add([v.index], val, "REPLACE")

    bpy.ops.object.select_all(action="DESELECT")
    for obj in part_objs:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = part_objs[0]
    bpy.ops.object.join()

    hero_mesh_obj = bpy.context.active_object
    hero_mesh_obj.name = f"Hero_{cfg['id']}"
    hero_mesh_obj.data.name = f"Hero_{cfg['id']}_Mesh"
    hero_mesh_obj.data.update()

    hero_mesh_obj.parent = arm_obj
    mod = hero_mesh_obj.modifiers.new(name="Armature", type="ARMATURE")
    mod.object = arm_obj
    mod.use_vertex_groups = True
    return hero_mesh_obj


def _set_action_smooth_bezier(act: bpy.types.Action) -> None:
    fcurves = []
    if hasattr(act, "layers"):
        for layer in act.layers:
            for strip in getattr(layer, "strips", []):
                for cb in getattr(strip, "channelbags", []):
                    fcurves.extend(getattr(cb, "fcurves", []))
    elif hasattr(act, "fcurves"):
        fcurves.extend(act.fcurves)
    for fc in fcurves:
        for kp in fc.keyframe_points:
            kp.interpolation = "BEZIER"
            kp.handle_left_type = "AUTO"
            kp.handle_right_type = "AUTO"


def _make_basis_yz(y_vec: Vector, z_hint: Vector) -> Matrix:
    y = y_vec.normalized()
    x = y.cross(z_hint)
    if x.length < 1e-6:
        fallback = Vector((1.0, 0.0, 0.0)) if abs(y.x) < 0.9 else Vector((0.0, 0.0, 1.0))
        x = y.cross(fallback)
    x.normalize()
    z = x.cross(y).normalized()
    return Matrix((x, y, z)).transposed()


def _apply_world_basis(
    pb: bpy.types.PoseBone,
    R_world: Matrix,
    prev_euler: Optional[object] = None,
) -> object:
    m_parent_pose = pb.parent.matrix if pb.parent else Matrix.Identity(4)
    m_parent_rest = pb.parent.bone.matrix_local if pb.parent else Matrix.Identity(4)
    m_rest = pb.bone.matrix_local
    m_base = m_parent_pose @ (m_parent_rest.inverted() @ m_rest)
    r_basis = m_base.to_3x3().inverted() @ R_world
    pb.rotation_mode = "XYZ"
    eu = r_basis.to_euler("XYZ", prev_euler) if prev_euler is not None else r_basis.to_euler("XYZ")
    pb.rotation_euler = eu
    return eu.copy()


def _smoothstep01(x: float) -> float:
    t = max(0.0, min(1.0, x))
    return t * t * (3.0 - 2.0 * t)


def _smootherstep01(x: float) -> float:
    t = max(0.0, min(1.0, x))
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def _lerp_pose_dict(a: Dict[str, Tuple[float, float, float]], b: Dict[str, Tuple[float, float, float]], w: float) -> Dict[str, Tuple[float, float, float]]:
    return {k: (a[k][0] + (b[k][0] - a[k][0]) * w, a[k][1] + (b[k][1] - a[k][1]) * w, a[k][2] + (b[k][2] - a[k][2]) * w) for k in a}


def _eval_beats_dict(beats: List[Tuple[float, Dict[str, Tuple[float, float, float]]]], t: float) -> Dict[str, Tuple[float, float, float]]:
    if t <= beats[0][0]:
        return beats[0][1]
    for idx in range(len(beats) - 1):
        t0, p0 = beats[idx]
        t1, p1 = beats[idx + 1]
        if t0 <= t <= t1:
            return _lerp_pose_dict(p0, p1, _smootherstep01((t - t0) / max(t1 - t0, 1e-6)))
    return beats[-1][1]


def _eval_beats_vec(beats: List[Tuple[float, Vector]], t: float) -> Vector:
    if t <= beats[0][0]:
        return beats[0][1].copy()
    for idx in range(len(beats) - 1):
        t0, v0 = beats[idx]
        t1, v1 = beats[idx + 1]
        if t0 <= t <= t1:
            return v0.lerp(v1, _smootherstep01((t - t0) / max(t1 - t0, 1e-6)))
    return beats[-1][1].copy()


def _eval_beats_float(beats: List[Tuple[float, float]], t: float) -> float:
    if t <= beats[0][0]:
        return beats[0][1]
    for idx in range(len(beats) - 1):
        t0, v0 = beats[idx]
        t1, v1 = beats[idx + 1]
        if t0 <= t <= t1:
            w = _smootherstep01((t - t0) / max(t1 - t0, 1e-6))
            return v0 + (v1 - v0) * w
    return beats[-1][1]


def build_12_animations(
    arm_obj: bpy.types.Object,
    scale_h: float,
    sock_obj: Optional[bpy.types.Object] = None,
    product: str = "gmail",
) -> Tuple[List[str], dict, dict]:
    arm_obj.animation_data_create()
    arm_obj.animation_data.use_nla = False
    created: List[str] = []

    def reset_pose() -> None:
        for pb in arm_obj.pose.bones:
            pb.rotation_mode = "XYZ"
            pb.location = (0.0, 0.0, 0.0)
            pb.rotation_euler = (0.0, 0.0, 0.0)
            pb.scale = (1.0, 1.0, 1.0)

    def set_rot(bname: str, rx_deg: float, ry_deg: float = 0.0, rz_deg: float = 0.0) -> None:
        pb = arm_obj.pose.bones[bname]
        pb.rotation_mode = "XYZ"
        pb.rotation_euler = (math.radians(rx_deg), math.radians(ry_deg), math.radians(rz_deg))

    def set_loc(bname: str, x: float, y: float, z: float) -> None:
        pb = arm_obj.pose.bones[bname]
        pb.location = (-x * scale_h, z * scale_h, y * scale_h)

    def key_all(frame: int) -> None:
        for pb in arm_obj.pose.bones:
            pb.keyframe_insert(data_path="rotation_euler", frame=frame)
            if pb.name in ("Root", "Pelvis"):
                pb.keyframe_insert(data_path="location", frame=frame)

    def push_action(name: str, frames: List[int], pose_fn: Callable[[int, float], None]) -> None:
        act = bpy.data.actions.new(name=name)
        arm_obj.animation_data.action = act
        f_start, f_end = frames[0], frames[-1]
        for f in frames:
            t = (f - f_start) / max(f_end - f_start, 1)
            reset_pose()
            pose_fn(f, t)
            key_all(f)

        _set_action_smooth_bezier(act)
        track = arm_obj.animation_data.nla_tracks.new()
        track.name = name
        strip = track.strips.new(name, f_start, act)
        strip.name = name
        if hasattr(strip, "action_slot") and act.slots:
            strip.action_slot = act.slots[0]
        created.append(name)

    def chest_to_world(right: float, fwd: float, up: float) -> Vector:
        return arm_obj.pose.bones["Chest"].matrix @ Vector((-right * scale_h, up * scale_h, fwd * scale_h))

    def chest_dir_to_world(right: float, fwd: float, up: float) -> Vector:
        return (arm_obj.pose.bones["Chest"].matrix.to_3x3() @ Vector((-right, up, fwd))).normalized()

    def solve_single_arm_ik(
        s_name: str,
        p_palm_target: Vector,
        R_hand_world: Matrix,
        pole_hint: Vector,
        ik_eulers: Dict[str, object],
    ) -> dict:
        palm_local = RIGHT_PALM_LOCAL if s_name == "R" else LEFT_PALM_LOCAL
        p_wrist_target = p_palm_target - (R_hand_world @ (palm_local * scale_h))

        pb_up = arm_obj.pose.bones[f"UpperArm_{s_name}"]
        pb_lo = arm_obj.pose.bones[f"LowerArm_{s_name}"]
        pb_hd = arm_obj.pose.bones[f"Hand_{s_name}"]

        p_sh = pb_up.head.copy()
        l1 = pb_up.bone.length
        l2 = pb_lo.bone.length

        to_wr = p_wrist_target - p_sh
        dist = to_wr.length
        max_reach = (l1 + l2) * 0.990
        min_reach = abs(l1 - l2) + 0.04
        dist_clamped = max(min_reach, min(max_reach, dist))
        u_hat = to_wr.normalized() if dist > 1e-6 else Vector((0.0, 1.0, 0.0))
        p_wr_eff = p_sh + u_hat * dist_clamped

        pole_n = pole_hint.normalized()
        bend_dir = pole_n - u_hat * pole_n.dot(u_hat)
        if bend_dir.length < 1e-5:
            sx = 1.0 if s_name == "R" else -1.0
            bend_dir = Vector((sx * 0.7, 0.0, -0.7))
            bend_dir = bend_dir - u_hat * bend_dir.dot(u_hat)
        bend_dir.normalize()

        along = (l1 * l1 + dist_clamped * dist_clamped - l2 * l2) / (2.0 * dist_clamped)
        perp = math.sqrt(max(0.0, l1 * l1 - along * along))
        p_el = p_sh + u_hat * along + bend_dir * perp

        r_up = _make_basis_yz(p_el - p_sh, -bend_dir)
        ik_eulers[pb_up.name] = _apply_world_basis(pb_up, r_up, ik_eulers.get(pb_up.name))
        bpy.context.view_layer.update()

        z_hand = Vector((R_hand_world[0][2], R_hand_world[1][2], R_hand_world[2][2])).normalized()
        z_lo_hint = (-bend_dir * 0.30 + z_hand * 0.70)
        if z_lo_hint.length < 1e-5:
            z_lo_hint = z_hand
        r_lo = _make_basis_yz(p_wr_eff - p_el, z_lo_hint)
        ik_eulers[pb_lo.name] = _apply_world_basis(pb_lo, r_lo, ik_eulers.get(pb_lo.name))
        bpy.context.view_layer.update()

        ik_eulers[pb_hd.name] = _apply_world_basis(pb_hd, R_hand_world, ik_eulers.get(pb_hd.name))
        bpy.context.view_layer.update()

        actual_palm = pb_hd.matrix @ (palm_local * scale_h)
        forearm_dir = (p_wr_eff - p_el).normalized()
        hand_y = Vector((R_hand_world[0][1], R_hand_world[1][1], R_hand_world[2][1])).normalized()
        wrist_bend_deg = math.degrees(math.acos(max(-1.0, min(1.0, forearm_dir.dot(hand_y)))))

        return {
            "actual_palm": actual_palm,
            "actual_wrist": pb_hd.head.copy(),
            "palm_err_mm": (actual_palm - p_palm_target).length * 1000.0,
            "reach_pct": 100.0 * dist / max(l1 + l2, 1e-6),
            "wrist_bend_deg": wrist_bend_deg,
        }

    twohand_samples: Dict[str, List[dict]] = {}

    def solve_two_hand_rifle_ik(
        clip_name: str,
        p_grip_R: Vector,
        barrel_dir: Vector,
        ik_eulers: Dict[str, object],
        up_ref: Optional[Vector] = None,
        pole_hint_R: Optional[Vector] = None,
        pole_hint_L: Optional[Vector] = None,
        left_y_weights: Tuple[float, float, float] = (0.78, 0.48, 0.38),
    ) -> dict:
        up_v = up_ref if up_ref is not None else Vector((0.0, 0.0, 1.0))
        B_hat = barrel_dir.normalized()
        R_hat = B_hat.cross(up_v)
        if R_hat.length < 1e-5:
            R_hat = Vector((1.0, 0.0, 0.0))
        R_hat.normalize()
        U_hat = R_hat.cross(B_hat).normalized()

        p_grip_L = p_grip_R + B_hat * RIFLE_FOREGRIP_DIST + U_hat * RIFLE_FOREGRIP_UP
        R_hd_R = Matrix((R_hat, B_hat, U_hat)).transposed()

        wr_w, wb_w, wu_w = left_y_weights
        y_hd_L = (R_hat * wr_w + B_hat * wb_w + U_hat * wu_w).normalized()
        z_hint_L = (B_hat * 0.85 + U_hat * 0.40 - R_hat * 0.25).normalized()
        R_hd_L = _make_basis_yz(y_hd_L, z_hint_L)

        p_hint_R = pole_hint_R if pole_hint_R is not None else Vector((0.72, -0.22, -0.66))
        p_hint_L = pole_hint_L if pole_hint_L is not None else Vector((-0.56, 0.14, -0.82))

        res_R = solve_single_arm_ik("R", p_grip_R, R_hd_R, p_hint_R, ik_eulers)
        res_L = solve_single_arm_ik("L", p_grip_L, R_hd_L, p_hint_L, ik_eulers)

        actual_sep = (res_L["actual_palm"] - res_R["actual_palm"]).length
        target_sep = math.hypot(RIFLE_FOREGRIP_DIST, RIFLE_FOREGRIP_UP)
        rec = {
            "p_grip_R": res_R["actual_palm"],
            "p_grip_L": res_L["actual_palm"],
            "B_hat": B_hat,
            "U_hat": U_hat,
            "R_hat": R_hat,
            "sep_m": actual_sep,
            "sep_err_mm": abs(actual_sep - target_sep) * 1000.0,
            "err_R_mm": res_R["palm_err_mm"],
            "err_L_mm": res_L["palm_err_mm"],
            "reach_R_pct": res_R["reach_pct"],
            "reach_L_pct": res_L["reach_pct"],
            "wrist_R_deg": res_R["wrist_bend_deg"],
            "wrist_L_deg": res_L["wrist_bend_deg"],
            "sock_err_mm": (sock_obj.matrix_world.translation - res_R["actual_palm"]).length * 1000.0 if sock_obj is not None else 0.0,
        }
        twohand_samples.setdefault(clip_name, []).append(rec)
        return rec

    # 1. IDLE
    def pose_idle(f: int, t: float) -> None:
        ph = t * 2.0 * math.pi
        br = math.sin(2.0 * ph)
        br_lag = math.sin(2.0 * ph - 0.45)
        sw = math.sin(ph)
        sw_c = math.cos(ph)

        set_loc("Pelvis", 0.010 * sw, -0.004, -0.010 + 0.0045 * br)
        set_rot("Pelvis",  1.5, -4.5 + 1.8 * sw, -1.6 * sw)
        set_rot("Spine",   1.6 - 1.2 * br, 1.8 - 0.8 * sw, 1.0 * sw)
        set_rot("Chest",  -2.0 - 1.5 * br_lag, 2.8 + 1.8 * sw, 0.8 * sw)
        set_rot("Neck",    0.4 + 0.5 * br_lag, -1.0 + 1.2 * sw, -0.3 * sw)
        set_rot("Head",    0.6 + 0.9 * br_lag,  3.0 + 4.5 * sw + 1.0 * sw_c, 1.2 * sw)

        set_rot("UpperArm_L",  5.5 + 1.6 * br_lag + 1.0 * sw,  4.0,  7.0 + 1.2 * br_lag)
        set_rot("LowerArm_L", 18.0 + 2.4 * br_lag,             0.0, -2.5)
        set_rot("Hand_L",      4.0 + 1.0 * br_lag,             0.0, -3.5)

        set_rot("UpperArm_R",  9.0 + 1.4 * br_lag - 0.8 * sw, -4.0, -7.0 - 1.0 * br_lag)
        set_rot("LowerArm_R", 24.0 + 2.0 * br_lag,             0.0,  3.0)
        set_rot("Hand_R",      5.0 + 0.8 * br_lag,             0.0,  3.0)

        set_rot("Thigh_L",  10.0 + 1.2 * sw,  0.0,  2.6 + 1.2 * sw)
        set_rot("Shin_L",  -12.0 - 1.6 * sw,  0.0,  0.0)
        set_rot("Foot_L",    2.5 + 0.4 * sw,  0.0,  0.0)

        set_rot("Thigh_R",  -0.5 - 1.2 * sw,  0.0, -2.8 + 1.2 * sw)
        set_rot("Shin_R",   -8.0 + 1.4 * sw,  0.0,  0.0)
        set_rot("Foot_R",    9.0 - 0.2 * sw,  0.0,  0.0)

    push_action("Idle", list(range(1, 74, 2)), pose_idle)

    # 2. RUN
    def pose_run(f: int, t: float) -> None:
        ph = t * 2.0 * math.pi
        s_hip, s_drop = math.sin(ph - 0.12), math.sin(ph - 0.45)
        c_bob, c_bob_lag = math.cos(2.0 * ph - 0.85), math.cos(2.0 * ph - 0.50)

        set_loc("Pelvis", -0.016 * s_drop, 0.012, -0.022 + 0.036 * c_bob)
        set_rot("Pelvis",  5.5 + 1.5 * c_bob, -9.5 * s_hip,  3.8 * s_drop)
        set_rot("Spine",   5.5 - 1.2 * c_bob_lag, 6.0 * math.sin(ph - 0.16), -2.2 * s_drop)
        set_rot("Chest",   3.5 - 1.4 * c_bob_lag, 10.0 * math.sin(ph - 0.20), -1.8 * s_drop)
        set_rot("Neck",   -6.0 + 1.0 * c_bob_lag, -4.0 * math.sin(ph - 0.20),  0.8 * s_drop)
        set_rot("Head",   -5.5 + 1.0 * c_bob_lag, -3.5 * math.sin(ph - 0.20),  0.5 * s_drop)

        for s_name, a, sgn in (("L", ph, 1.0), ("R", ph + math.pi, -1.0)):
            set_rot(f"Thigh_{s_name}", 12.0 + 40.0 * math.sin(a) - 6.0 * math.cos(2.0 * a), -2.0 * sgn * math.sin(a), 1.8 * sgn)
            set_rot(f"Shin_{s_name}", -40.0 - 28.0 * math.cos(a + 0.10) - 16.0 * math.cos(2.0 * a + 0.15), 0.0, 0.0)
            set_rot(f"Foot_{s_name}",  -4.0 + 16.0 * math.sin(a + 0.35) - 8.0 * math.sin(2.0 * a), 0.0, 0.0)

        s_arm, s_elb = math.sin(ph - 0.15), math.sin(ph - 0.28)
        set_rot("UpperArm_L",  -4.0 - 38.0 * s_arm,  6.0 * s_arm,  11.0 + 3.0 * math.cos(ph))
        set_rot("LowerArm_L",  68.0 - 16.0 * s_elb,  0.0,          -8.0)
        set_rot("Hand_L",       5.0,                 0.0,          -4.0)

        set_rot("UpperArm_R",   6.0 + 26.0 * s_arm, -5.0 * s_arm, -10.0 - 2.5 * math.cos(ph))
        set_rot("LowerArm_R",  66.0 + 14.0 * s_elb,  0.0,           7.0)
        set_rot("Hand_R",       4.0,                 0.0,           3.0)

    push_action("Run", list(range(1, 22)), pose_run)

    # 3. SPRINT
    def pose_sprint(f: int, t: float) -> None:
        ph = t * 2.0 * math.pi
        s_hip, s_drop = math.sin(ph - 0.10), math.sin(ph - 0.45)
        c_bob, c_bob_lag = math.cos(2.0 * ph - 0.85), math.cos(2.0 * ph - 0.48)

        set_loc("Pelvis", -0.024 * s_drop, 0.045, -0.054 + 0.052 * c_bob)
        set_rot("Pelvis", 11.0 + 2.2 * c_bob, -14.0 * s_hip,  5.2 * s_drop)
        set_rot("Spine",  10.0 - 1.6 * c_bob_lag,  9.0 * math.sin(ph - 0.15), -3.0 * s_drop)
        set_rot("Chest",   6.5 - 1.8 * c_bob_lag, 14.0 * math.sin(ph - 0.20), -2.5 * s_drop)
        set_rot("Neck",  -11.0 + 1.2 * c_bob_lag, -5.5 * math.sin(ph - 0.20),  1.2 * s_drop)
        set_rot("Head",  -10.5 + 1.2 * c_bob_lag, -4.5 * math.sin(ph - 0.20),  0.5 * s_drop)

        for s_name, a, sgn in (("L", ph, 1.0), ("R", ph + math.pi, -1.0)):
            set_rot(f"Thigh_{s_name}", 24.0 + 58.0 * math.sin(a) - 9.0 * math.cos(2.0 * a), -3.0 * sgn * math.sin(a), 2.0 * sgn)
            set_rot(f"Shin_{s_name}", -50.0 - 36.0 * math.cos(a + 0.12) - 21.0 * math.cos(2.0 * a + 0.15), 0.0, 0.0)
            set_rot(f"Foot_{s_name}",  -6.0 + 22.0 * math.sin(a + 0.35) - 10.0 * math.sin(2.0 * a), 0.0, 0.0)

        s_arm, s_elb = math.sin(ph - 0.14), math.sin(ph - 0.26)
        set_rot("UpperArm_L", -10.0 - 52.0 * s_arm,  10.0 * s_arm,  14.0 + 4.0 * math.cos(ph))
        set_rot("LowerArm_L",  88.0 - 16.0 * s_elb,   0.0,         -12.0)
        set_rot("Hand_L",       8.0,                  0.0,          -5.0)

        set_rot("UpperArm_R",  -2.0 + 40.0 * s_arm,  -8.0 * s_arm, -13.0 - 3.5 * math.cos(ph))
        set_rot("LowerArm_R",  84.0 + 14.0 * s_elb,   0.0,          10.0)
        set_rot("Hand_R",       6.0,                  0.0,           4.0)

    push_action("Sprint", list(range(1, 18)), pose_sprint)

    # 4. CROUCH
    crouch_ik_eulers: Dict[str, object] = {}

    def pose_crouch(f: int, t: float) -> None:
        ph = t * 2.0 * math.pi
        s, c, c2 = math.sin(ph), math.cos(ph), math.cos(2.0 * ph - 0.5)

        set_loc("Pelvis", -0.016 * s, -0.040, -0.305 + 0.012 * c2)
        set_rot("Pelvis",   6.0 + 1.4 * c2, -16.0 - 2.5 * s,  2.0 * s)
        set_rot("Spine",    7.5 - 1.0 * c2,  -6.5 + 1.8 * s, -1.0 * s)
        set_rot("Chest",    3.5 - 1.0 * c2, -11.0 + 2.2 * s, -1.0 * s)
        set_rot("Neck",    -7.0 + 0.8 * c2,  11.0 - 1.2 * s,  1.0)
        set_rot("Head",    -6.5 + 0.8 * c2,  13.0 - 1.2 * s,  2.0)

        set_rot("Thigh_L",  74.0 + 12.0 * s, 0.0,  6.5)
        set_rot("Shin_L",  -96.0 - 12.0 * c - 6.0 * s, 0.0, 0.0)
        set_rot("Foot_L",   30.0 + 8.0 * c - 4.0 * s, 0.0, 0.0)

        set_rot("Thigh_R",  64.0 - 12.0 * s, 0.0, -7.5)
        set_rot("Shin_R",  -98.0 + 12.0 * c + 6.0 * s, 0.0, 0.0)
        set_rot("Foot_R",   40.0 - 8.0 * c + 4.0 * s, 0.0, 0.0)

        bpy.context.view_layer.update()
        p_sh_R = arm_obj.pose.bones["UpperArm_R"].head.copy()
        # Seated cleanly forward & outboard of right shoulder so M4 & Longbow .308 clear crouched icon with 0 clip & 0.00mm err!
        p_grip_R = p_sh_R + Vector((+0.030 * scale_h, 0.392 * scale_h, (-0.032 + 0.005 * c2) * scale_h))
        barrel_dir = Vector((-0.24 + 0.012 * s, 0.970, -0.04 + 0.010 * c2)).normalized()
        solve_two_hand_rifle_ik(
            "Crouch", p_grip_R, barrel_dir, crouch_ik_eulers,
            pole_hint_R=Vector((0.72, -0.18, -0.67)),
            pole_hint_L=Vector((-0.46, 0.14, -0.88)),
            left_y_weights=(0.86, 0.36, 0.36),
        )

    push_action("Crouch", list(range(1, 34)), pose_crouch)

    # 5. AIM
    aim_ik_eulers: Dict[str, object] = {}

    def pose_aim(f: int, t: float) -> None:
        ph = t * 2.0 * math.pi
        br, br_lag = math.sin(ph), math.sin(ph - 0.35)

        # Upright bladed shooter stance (-41 deg blade) so right shoulder pocket clears the 3D icon face
        # and BOTH M4 & Longbow .308 buttstocks tuck cleanly w/ 0 icon clipping AND 0.00mm grip error!
        set_loc("Pelvis", 0.002 * br, -0.020, -0.036 + 0.003 * br)
        set_rot("Pelvis",  0.5, -18.0, 0.0)
        set_rot("Spine",   1.2 + 0.4 * br, -8.5, 0.0)
        set_rot("Chest",   0.8 - 0.6 * br_lag, -15.0, 0.0)
        set_rot("Neck",   -1.0 + 0.2 * br_lag,  13.5, 1.5)
        set_rot("Head",   -0.8 + 0.2 * br_lag,  17.0, 3.0)

        set_rot("Thigh_L",  20.5, 0.0,  5.0)
        set_rot("Shin_L",  -20.0, 0.0,  0.0)
        set_rot("Foot_L",    3.5, 0.0,  0.0)

        set_rot("Thigh_R",  -7.5, 0.0, -6.0)
        set_rot("Shin_R",  -16.0, 0.0,  0.0)
        set_rot("Foot_R",   22.0, 0.0,  0.0)

        bpy.context.view_layer.update()
        p_sh_R = arm_obj.pose.bones["UpperArm_R"].head.copy()
        p_grip_R = p_sh_R + Vector((+0.044 * scale_h, 0.464 * scale_h, (-0.018 + 0.003 * br_lag) * scale_h))
        solve_two_hand_rifle_ik(
            "Aim", p_grip_R, Vector((0.0, 1.0, 0.0)), aim_ik_eulers,
            pole_hint_R=Vector((0.72, -0.16, -0.67)),
            pole_hint_L=Vector((-0.44, 0.14, -0.89)),
            left_y_weights=(0.88, 0.34, 0.32),
        )

    push_action("Aim", list(range(1, 50, 2)), pose_aim)

    # 6. RELOAD
    reload_torso_beats: List[Tuple[float, Dict[str, Tuple[float, float, float]]]] = [
        (0.00, {"Pelvis": (0.5, -18.0, 0.0), "Spine": (1.2, -8.5, 0.0), "Chest": (0.8, -15.0, 0.0), "Neck": (-1.0, 13.5, 1.5), "Head": (-0.8, 17.0, 3.0)}),
        (0.22, {"Pelvis": (2.0, -13.0, 1.5), "Spine": (4.0, -5.0, 2.0), "Chest": (4.5,  -8.0, 3.5), "Neck": ( 2.0,  9.0, 1.0), "Head": ( 7.0,  8.0, 2.5)}),
        (0.44, {"Pelvis": (1.5, -14.0, 0.8), "Spine": (3.2, -6.0, 1.0), "Chest": (3.5, -10.0, 2.2), "Neck": ( 0.0, 11.0, 1.0), "Head": ( 5.0, 10.0, 2.0)}),
        (0.58, {"Pelvis": (1.0, -15.5, -0.5), "Spine": (2.2, -7.2, -0.5), "Chest": (2.2, -12.0, 1.0), "Neck": (-1.0, 12.0, 1.0), "Head": ( 2.0, 12.5, 1.8)}),
        (0.76, {"Pelvis": (0.5, -17.0, -1.0), "Spine": (1.5, -8.0, -0.8), "Chest": (1.0, -14.0, -0.8), "Neck": (-1.0, 13.0, 1.2), "Head": (-1.0, 15.5, 2.8)}),
        (1.00, {"Pelvis": (0.5, -18.0, 0.0), "Spine": (1.2, -8.5, 0.0), "Chest": (0.8, -15.0, 0.0), "Neck": (-1.0, 13.5, 1.5), "Head": (-0.8, 17.0, 3.0)}),
    ]
    reload_rifle_beats: List[Tuple[float, Vector, Vector]] = [
        (0.00, Vector((+0.044, 0.464, -0.018)), Vector(( 0.00, 1.00, 0.00)).normalized()),
        (0.22, Vector((+0.008, 0.398, -0.058)), Vector((-0.34, 0.86, 0.38)).normalized()),
        (0.44, Vector((+0.012, 0.408, -0.052)), Vector((-0.30, 0.88, 0.36)).normalized()),
        (0.58, Vector((+0.022, 0.426, -0.042)), Vector((-0.24, 0.91, 0.33)).normalized()),
        (0.76, Vector((+0.034, 0.446, -0.028)), Vector((-0.12, 0.97, 0.20)).normalized()),
        (1.00, Vector((+0.044, 0.464, -0.018)), Vector(( 0.00, 1.00, 0.00)).normalized()),
    ]
    reload_ik_eulers: Dict[str, object] = {}

    def pose_reload(f: int, t: float) -> None:
        pose_map = reload_torso_beats[-1][1]
        for idx in range(len(reload_torso_beats) - 1):
            t0, p0 = reload_torso_beats[idx]
            t1, p1 = reload_torso_beats[idx + 1]
            if t0 <= t <= t1:
                pose_map = _lerp_pose_dict(p0, p1, _smoothstep01((t - t0) / max(t1 - t0, 1e-6)))
                break

        set_loc("Pelvis", 0.0, -0.020, -0.036 - 0.008 * math.sin(t * math.pi))
        for bname, (rx, ry, rz) in pose_map.items():
            set_rot(bname, rx, ry, rz)

        set_rot("Thigh_L",  20.5, 0.0,  5.0)
        set_rot("Shin_L",  -20.0, 0.0,  0.0)
        set_rot("Foot_L",    3.5, 0.0,  0.0)
        set_rot("Thigh_R",  -7.5, 0.0, -6.0)
        set_rot("Shin_R",  -16.0, 0.0,  0.0)
        set_rot("Foot_R",   22.0, 0.0,  0.0)

        bpy.context.view_layer.update()
        p_sh_R = arm_obj.pose.bones["UpperArm_R"].head.copy()
        p_pelvis = arm_obj.pose.bones["Pelvis"].head.copy()

        grip_off, B_hat = reload_rifle_beats[-1][1], reload_rifle_beats[-1][2]
        beat_idx, beat_w = len(reload_rifle_beats) - 2, 1.0
        for idx in range(len(reload_rifle_beats) - 1):
            t0, g0, b0 = reload_rifle_beats[idx]
            t1, g1, b1 = reload_rifle_beats[idx + 1]
            if t0 <= t <= t1:
                beat_idx = idx
                beat_w = _smoothstep01((t - t0) / max(t1 - t0, 1e-6))
                grip_off = g0.lerp(g1, beat_w)
                B_hat = b0.lerp(b1, beat_w).normalized()
                break

        p_grip_R = p_sh_R + grip_off * scale_h
        R_hat = B_hat.cross(Vector((0.0, 0.0, 1.0))).normalized()
        U_hat = R_hat.cross(B_hat).normalized()
        R_hd_R = Matrix((R_hat, B_hat, U_hat)).transposed()

        res_R = solve_single_arm_ik("R", p_grip_R, R_hd_R, Vector((0.68, -0.16, -0.71)), reload_ik_eulers)

        p_handguard = p_grip_R + B_hat * RIFLE_FOREGRIP_DIST + U_hat * RIFLE_FOREGRIP_UP
        p_magwell = p_grip_R + B_hat * 0.130
        R_hd_L_grip = _make_basis_yz((R_hat * 0.88 + B_hat * 0.34 + U_hat * 0.32).normalized(), (B_hat * 0.85 + U_hat * 0.40 - R_hat * 0.25).normalized())
        R_hd_L_pouch = _make_basis_yz(Vector((0.25, 0.45, -0.86)).normalized(), Vector((0.0, 0.88, 0.46)).normalized())
        R_hd_L_mag = _make_basis_yz((R_hat * 0.82 + B_hat * 0.35 + U_hat * 0.45).normalized(), (B_hat * 0.75 + U_hat * 0.66).normalized())
        R_hd_L_bolt = _make_basis_yz((R_hat * 0.76 + B_hat * 0.25 + U_hat * 0.60).normalized(), (B_hat * 0.45 + U_hat * 0.88).normalized())

        left_targets = [
            (p_handguard,                                              R_hd_L_grip),
            (p_pelvis + Vector((-0.175, 0.135, 0.025)) * scale_h,      R_hd_L_pouch),
            (p_magwell - U_hat * 0.145 - R_hat * 0.020,                R_hd_L_mag),
            (p_magwell - U_hat * 0.025 - R_hat * 0.015,                R_hd_L_mag),
            (p_grip_R + B_hat * 0.040 + U_hat * 0.105 - R_hat * 0.042, R_hd_L_bolt),
            (p_handguard,                                              R_hd_L_grip),
        ]
        p_L0, r_L0 = left_targets[beat_idx]
        p_L1, r_L1 = left_targets[beat_idx + 1]
        res_L = solve_single_arm_ik("L", p_L0.lerp(p_L1, beat_w), r_L0.to_quaternion().slerp(r_L1.to_quaternion(), beat_w).to_matrix(), Vector((-0.58, 0.10, -0.80)), reload_ik_eulers)

        if f in (1, 49):
            actual_sep = (res_L["actual_palm"] - res_R["actual_palm"]).length
            target_sep = math.hypot(RIFLE_FOREGRIP_DIST, RIFLE_FOREGRIP_UP)
            twohand_samples.setdefault("Reload_Endpoints", []).append({
                "p_grip_R": res_R["actual_palm"], "p_grip_L": res_L["actual_palm"], "B_hat": B_hat, "U_hat": U_hat, "R_hat": R_hat,
                "sep_m": actual_sep, "sep_err_mm": abs(actual_sep - target_sep) * 1000.0,
                "err_R_mm": res_R["palm_err_mm"], "err_L_mm": res_L["palm_err_mm"],
                "reach_R_pct": res_R["reach_pct"], "reach_L_pct": res_L["reach_pct"],
                "wrist_R_deg": res_R["wrist_bend_deg"], "wrist_L_deg": res_L["wrist_bend_deg"],
                "sock_err_mm": (sock_obj.matrix_world.translation - res_R["actual_palm"]).length * 1000.0 if sock_obj is not None else 0.0,
            })

    push_action("Reload", list(range(1, 50, 2)), pose_reload)

    # 7. GLIDE
    prev_ik_eulers: Dict[str, object] = {}
    glide_hand_L_samples: List[Vector] = []
    glide_hand_R_samples: List[Vector] = []
    glide_palm_L_samples: List[Vector] = []
    glide_palm_R_samples: List[Vector] = []

    pitch_rad = math.radians(GLIDE_HAND_PITCH_DEG)
    glide_y_hand = Vector((0.0, math.sin(pitch_rad), math.cos(pitch_rad))).normalized()
    glide_palm_inward = Vector((0.0, math.cos(pitch_rad), -math.sin(pitch_rad))).normalized()

    def pose_glide(f: int, t: float) -> None:
        ph = t * 2.0 * math.pi
        sw, sw2 = math.sin(ph), math.cos(ph)

        set_loc("Pelvis", 0.012 * sw, -0.025 + 0.006 * sw2, 0.020 + 0.008 * math.cos(2.0 * ph))
        set_rot("Pelvis",  4.5 + 1.4 * sw2,  2.2 * sw,  2.8 * sw)
        set_rot("Spine",   2.5 + 0.8 * sw2, -1.2 * sw, -1.5 * sw)
        set_rot("Chest",   1.5,             -1.0 * sw, -1.3 * sw)
        set_rot("Neck",    2.5,              0.0,       0.0)
        set_rot("Head",    5.0 + 1.5 * sw2,  4.0 * sw, -1.0 * sw)

        set_rot("Thigh_L", -14.0 + 5.5 * sw, -3.0,  5.5 + 1.8 * sw2)
        set_rot("Shin_L",  -48.0 - 7.5 * sw2, 0.0,  0.0)
        set_rot("Foot_L",  -22.0 + 4.0 * sw,  0.0,  0.0)

        set_rot("Thigh_R",  -6.0 - 5.5 * sw,  3.0, -5.5 - 1.8 * sw2)
        set_rot("Shin_R",  -34.0 + 7.5 * sw2, 0.0,  0.0)
        set_rot("Foot_R",  -26.0 - 4.0 * sw,  0.0,  0.0)

        bpy.context.view_layer.update()

        for s_name, sx in (("L", -1.0), ("R", 1.0)):
            p_bar_grip = Vector((sx * GLIDE_GRIP_HALF_SPAN, GLIDE_BAR_Y_BLENDER, GLIDE_BAR_Z_BLENDER))
            p_wrist_target = p_bar_grip - glide_y_hand * (GLIDE_PALM_ALONG_HAND * scale_h) - glide_palm_inward * (GLIDE_PALM_INWARD_OFF * scale_h)

            pb_up = arm_obj.pose.bones[f"UpperArm_{s_name}"]
            pb_lo = arm_obj.pose.bones[f"LowerArm_{s_name}"]
            pb_hd = arm_obj.pose.bones[f"Hand_{s_name}"]

            p_sh = pb_up.head.copy()
            l1, l2 = pb_up.bone.length, pb_lo.bone.length

            to_wr = p_wrist_target - p_sh
            dist = to_wr.length
            dist_clamped = max(abs(l1 - l2) + 0.02, min((l1 + l2) * 0.992, dist))
            u_hat = to_wr.normalized()
            p_wr_eff = p_sh + u_hat * dist_clamped

            pole_hint = Vector((sx * 0.84, 0.50, -0.20)).normalized()
            bend_dir = pole_hint - u_hat * pole_hint.dot(u_hat)
            if bend_dir.length < 1e-6:
                bend_dir = Vector((sx, 0.0, 0.0))
            bend_dir.normalize()

            along = (l1 * l1 + dist_clamped * dist_clamped - l2 * l2) / (2.0 * dist_clamped)
            perp = math.sqrt(max(0.0, l1 * l1 - along * along))
            p_el = p_sh + u_hat * along + bend_dir * perp

            prev_ik_eulers[pb_up.name] = _apply_world_basis(pb_up, _make_basis_yz(p_el - p_sh, Vector((-sx * 0.42, -0.88, 0.22))), prev_ik_eulers.get(pb_up.name))
            bpy.context.view_layer.update()

            prev_ik_eulers[pb_lo.name] = _apply_world_basis(pb_lo, _make_basis_yz(p_wr_eff - p_el, Vector((-sx * 0.96, -0.25, 0.06))), prev_ik_eulers.get(pb_lo.name))
            bpy.context.view_layer.update()

            z_hand = Vector((-sx, 0.0, 0.0))
            x_hand = glide_y_hand.cross(z_hand).normalized()
            prev_ik_eulers[pb_hd.name] = _apply_world_basis(pb_hd, Matrix((x_hand, glide_y_hand, z_hand)).transposed(), prev_ik_eulers.get(pb_hd.name))
            bpy.context.view_layer.update()

            actual_wrist = pb_hd.head.copy()
            actual_palm = actual_wrist + glide_y_hand * (GLIDE_PALM_ALONG_HAND * scale_h) + glide_palm_inward * (GLIDE_PALM_INWARD_OFF * scale_h)
            if s_name == "L":
                glide_hand_L_samples.append(actual_wrist)
                glide_palm_L_samples.append(actual_palm)
            else:
                glide_hand_R_samples.append(actual_wrist)
                glide_palm_R_samples.append(actual_palm)

    push_action("Glide", list(range(1, 38)), pose_glide)

    # 8. JUMP
    def pose_jump(f: int, t: float) -> None:
        ph = t * 2.0 * math.pi
        s, c = math.sin(ph), math.cos(ph)

        set_loc("Pelvis", -0.012, 0.025, 0.055 + 0.018 * s)
        set_rot("Pelvis",  10.0 - 2.5 * s, -11.0 + 1.8 * c, -3.2 + 1.4 * c)
        set_rot("Spine",    7.5 - 1.5 * s,   4.5 - 1.0 * c,  1.8 - 0.8 * c)
        set_rot("Chest",    4.5 - 1.5 * s,   7.5 - 1.2 * c,  1.5 - 0.6 * c)
        set_rot("Neck",    -8.0 + 1.0 * s,  -2.5,            0.0)
        set_rot("Head",    -7.5 + 1.2 * s,  -2.0,            0.5 * c)

        set_rot("Thigh_L",  64.0 + 6.0 * s, -4.0,  6.0)
        set_rot("Shin_L",  -78.0 - 7.0 * c,  0.0,  0.0)
        set_rot("Foot_L",  -16.0 + 5.0 * s,  0.0,  0.0)

        set_rot("Thigh_R", -18.0 - 5.0 * s,  3.0, -5.0)
        set_rot("Shin_R",  -52.0 + 6.0 * c,  0.0,  0.0)
        set_rot("Foot_R",  -26.0 - 4.0 * s,  0.0,  0.0)

        set_rot("UpperArm_L", -34.0 + 8.0 * c, 10.0, 26.0 + 4.0 * s)
        set_rot("LowerArm_L",  56.0 + 8.0 * s,  0.0, -8.0)
        set_rot("Hand_L",       8.0,            0.0, -6.0)

        set_rot("UpperArm_R",  30.0 + 2.2 * s, -4.0, -12.0)
        set_rot("LowerArm_R",  44.0 - 1.8 * s,  4.0,   6.0)
        set_rot("Hand_R",      -6.0,            0.0,   2.0)

    push_action("Jump", list(range(1, 26)), pose_jump)

    # 9. IDLE_ARMED
    idle_armed_ik_eulers: Dict[str, object] = {}

    def pose_idle_armed(f: int, t: float) -> None:
        ph = t * 2.0 * math.pi
        br, br_lag, sw = math.sin(ph), math.sin(ph - 0.42), math.sin(ph + 0.35)

        set_loc("Pelvis", 0.008 * sw, -0.008, -0.016 + 0.004 * br)
        set_rot("Pelvis",  2.0, -10.0 + 1.4 * sw, -1.2 * sw)
        set_rot("Spine",   2.2 - 1.0 * br, -2.5 - 0.6 * sw, 0.8 * sw)
        set_rot("Chest",  -1.5 - 1.4 * br_lag, -5.5 + 1.2 * sw, 0.6 * sw)
        set_rot("Neck",    0.0 + 0.5 * br_lag,  7.0 + 1.0 * sw, -0.3 * sw)
        set_rot("Head",    0.5 + 0.8 * br_lag,  8.5 + 3.0 * sw,  1.0 * sw)

        set_rot("Thigh_L",  14.0 + 1.0 * sw, 0.0,  3.8 + 0.8 * sw)
        set_rot("Shin_L",  -15.5 - 1.2 * sw, 0.0,  0.0)
        set_rot("Foot_L",    2.8 + 0.3 * sw, 0.0,  0.0)

        set_rot("Thigh_R",  -3.5 - 1.0 * sw, 0.0, -4.2 + 0.8 * sw)
        set_rot("Shin_R",  -11.0 + 1.1 * sw, 0.0,  0.0)
        set_rot("Foot_R",   13.5 - 0.2 * sw, 0.0,  0.0)

        bpy.context.view_layer.update()
        p_grip_R = chest_to_world(right=0.190 + 0.003 * sw, fwd=0.258 + 0.003 * br_lag, up=-0.062 + 0.006 * br_lag)
        barrel_dir = Vector((-0.55, 0.78, -0.28 + 0.012 * br_lag)).normalized()
        solve_two_hand_rifle_ik(
            "IdleArmed", p_grip_R, barrel_dir, idle_armed_ik_eulers,
            pole_hint_R=Vector((0.70, -0.24, -0.67)),
            pole_hint_L=Vector((-0.58, 0.12, -0.80)),
            left_y_weights=(0.88, 0.34, 0.34),
        )

    push_action("IdleArmed", list(range(1, 50, 2)), pose_idle_armed)

    # 10. RUN_ARMED
    run_armed_ik_eulers: Dict[str, object] = {}

    def pose_run_armed(f: int, t: float) -> None:
        ph = t * 2.0 * math.pi
        s_hip, s_drop = math.sin(ph - 0.12), math.sin(ph - 0.45)
        c_bob, c_bob_lag, s_sway = math.cos(2.0 * ph - 0.85), math.cos(2.0 * ph - 0.50), math.sin(ph - 0.20)

        set_loc("Pelvis", -0.016 * s_drop, 0.012, -0.022 + 0.036 * c_bob)
        set_rot("Pelvis",  5.5 + 1.5 * c_bob, -9.5 * s_hip,  3.8 * s_drop)
        set_rot("Spine",   5.0 - 1.0 * c_bob_lag,  4.2 * s_sway, -2.0 * s_drop)
        set_rot("Chest",   3.0 - 1.2 * c_bob_lag,  6.5 * s_sway, -1.8 * s_drop)
        set_rot("Neck",   -6.0 + 0.8 * c_bob_lag, -2.5 * s_sway,  0.8 * s_drop)
        set_rot("Head",   -5.5 + 0.8 * c_bob_lag, -2.0 * s_sway,  0.5 * s_drop)

        for s_name, a, sgn in (("L", ph, 1.0), ("R", ph + math.pi, -1.0)):
            set_rot(f"Thigh_{s_name}", 12.0 + 40.0 * math.sin(a) - 6.0 * math.cos(2.0 * a), -2.0 * sgn * math.sin(a), 1.8 * sgn)
            set_rot(f"Shin_{s_name}", -40.0 - 28.0 * math.cos(a + 0.10) - 16.0 * math.cos(2.0 * a + 0.15), 0.0, 0.0)
            set_rot(f"Foot_{s_name}",  -4.0 + 16.0 * math.sin(a + 0.35) - 8.0 * math.sin(2.0 * a), 0.0, 0.0)

        bpy.context.view_layer.update()
        # Clean chest-carry clearance for BOTH M4 & Longbow .308 across all 6 icons (0 BVH overlap!)
        p_grip_R = chest_to_world(right=0.205 + 0.008 * s_sway, fwd=0.268 + 0.007 * c_bob_lag, up=-0.024 + 0.011 * c_bob_lag)
        barrel_dir = chest_dir_to_world(-0.78, 0.44, 0.44 + 0.028 * c_bob_lag)
        solve_two_hand_rifle_ik(
            "RunArmed", p_grip_R, barrel_dir, run_armed_ik_eulers,
            pole_hint_R=Vector((0.70, -0.26, -0.66)),
            pole_hint_L=Vector((-0.62, 0.12, -0.78)),
            left_y_weights=(0.82, 0.22, 0.52),
        )

    push_action("RunArmed", list(range(1, 22)), pose_run_armed)

    # 11. SPRINT_ARMED
    sprint_armed_ik_eulers: Dict[str, object] = {}

    def pose_sprint_armed(f: int, t: float) -> None:
        ph = t * 2.0 * math.pi
        s_hip, s_drop = math.sin(ph - 0.10), math.sin(ph - 0.45)
        c_bob, c_bob_lag, s_sway = math.cos(2.0 * ph - 0.85), math.cos(2.0 * ph - 0.48), math.sin(ph - 0.18)

        set_loc("Pelvis", -0.024 * s_drop, 0.045, -0.054 + 0.052 * c_bob)
        set_rot("Pelvis",  8.5 + 2.0 * c_bob, -14.0 * s_hip,  5.2 * s_drop)
        set_rot("Spine",   7.5 - 1.4 * c_bob_lag,  6.0 * s_sway, -2.8 * s_drop)
        set_rot("Chest",   4.5 - 1.5 * c_bob_lag,  8.8 * s_sway, -2.4 * s_drop)
        set_rot("Neck",   -9.5 + 1.0 * c_bob_lag, -3.5 * s_sway,  1.2 * s_drop)
        set_rot("Head",   -9.0 + 1.0 * c_bob_lag, -3.0 * s_sway,  0.5 * s_drop)

        for s_name, a, sgn in (("L", ph, 1.0), ("R", ph + math.pi, -1.0)):
            set_rot(f"Thigh_{s_name}", 24.0 + 58.0 * math.sin(a) - 9.0 * math.cos(2.0 * a), -3.0 * sgn * math.sin(a), 2.0 * sgn)
            set_rot(f"Shin_{s_name}", -50.0 - 36.0 * math.cos(a + 0.12) - 21.0 * math.cos(2.0 * a + 0.15), 0.0, 0.0)
            set_rot(f"Foot_{s_name}",  -6.0 + 22.0 * math.sin(a + 0.35) - 10.0 * math.sin(2.0 * a), 0.0, 0.0)

        bpy.context.view_layer.update()
        # High-chest sprint carry with crisp forward clearance for BOTH M4 & Longbow .308 (0 BVH overlap!)
        p_grip_R = chest_to_world(right=0.205 + 0.012 * s_sway, fwd=0.278 + 0.010 * c_bob_lag, up=-0.010 + 0.014 * c_bob_lag)
        barrel_dir = chest_dir_to_world(-0.80, 0.40, 0.44 + 0.036 * c_bob_lag)
        solve_two_hand_rifle_ik(
            "SprintArmed", p_grip_R, barrel_dir, sprint_armed_ik_eulers,
            pole_hint_R=Vector((0.70, -0.26, -0.66)),
            pole_hint_L=Vector((-0.64, 0.12, -0.76)),
            left_y_weights=(0.80, 0.20, 0.56),
        )

    push_action("SprintArmed", list(range(1, 18)), pose_sprint_armed)

    # 12. JUMP_ARMED
    jump_armed_ik_eulers: Dict[str, object] = {}

    def pose_jump_armed(f: int, t: float) -> None:
        ph = t * 2.0 * math.pi
        s, c = math.sin(ph), math.cos(ph)

        set_loc("Pelvis", -0.012, 0.025, 0.055 + 0.018 * s)
        set_rot("Pelvis",  10.0 - 2.5 * s, -11.0 + 1.8 * c, -3.2 + 1.4 * c)
        set_rot("Spine",    7.5 - 1.5 * s,   2.5 - 1.0 * c,  1.5 - 0.6 * c)
        set_rot("Chest",    4.5 - 1.5 * s,   3.5 - 1.0 * c,  1.2 - 0.5 * c)
        set_rot("Neck",    -8.5 + 1.0 * s,  -1.5,            0.0)
        set_rot("Head",    -8.0 + 1.2 * s,  -1.0,            0.5 * c)

        set_rot("Thigh_L",  64.0 + 6.0 * s, -4.0,  6.0)
        set_rot("Shin_L",  -78.0 - 7.0 * c,  0.0,  0.0)
        set_rot("Foot_L",  -16.0 + 5.0 * s,  0.0,  0.0)

        set_rot("Thigh_R", -18.0 - 5.0 * s,  3.0, -5.0)
        set_rot("Shin_R",  -52.0 + 6.0 * c,  0.0,  0.0)
        set_rot("Foot_R",  -26.0 - 4.0 * s,  0.0,  0.0)

        bpy.context.view_layer.update()
        p_grip_R = chest_to_world(right=0.214, fwd=0.284 + 0.006 * c, up=-0.012 + 0.012 * s)
        barrel_dir = chest_dir_to_world(-0.62, 0.68, 0.38 + 0.020 * s)
        solve_two_hand_rifle_ik(
            "JumpArmed", p_grip_R, barrel_dir, jump_armed_ik_eulers,
            pole_hint_R=Vector((0.70, -0.26, -0.66)),
            pole_hint_L=Vector((-0.60, 0.14, -0.79)),
            left_y_weights=(0.84, 0.28, 0.46),
        )

    push_action("JumpArmed", list(range(1, 26)), pose_jump_armed)

    # 13. LOBBY_SHOWCASE — Bespoke, Unique, Looping Per-Hero Turntable Choreography
    #     60 frames sampled every 2 frames (frames 1..61, 31 keyframes, exact seamless loop f_first == f_last)
    lobby_ik_eulers: Dict[str, object] = {}

    if product == "gmail":
        # 1. GMAIL AI — "Tactical Sweep" (Armed w/ Vanguard M4)
        # Confident bladed low-ready -> eye-level shouldered aim -> smooth +18° left & -18° right target sweep -> low-ready
        gmail_body_beats: List[Tuple[float, Dict[str, Tuple[float, float, float]]]] = [
            (0.00, {
                "PelvisLoc": (0.004, -0.014, -0.022),
                "Pelvis": (2.0, -14.0, 0.0), "Spine": (2.0, -5.0, 0.0), "Chest": (-1.0, -9.0, 0.0),
                "Neck": (-0.5, 11.0, 0.0), "Head": (0.5, 14.0, 1.0),
                "Thigh_L": (18.0, 0.0, 4.5), "Shin_L": (-20.0, 0.0, 0.0), "Foot_L": (4.0, 0.0, 0.0),
                "Thigh_R": (-5.5, 0.0, -5.0), "Shin_R": (-13.0, 0.0, 0.0), "Foot_R": (16.5, 0.0, 0.0),
            }),
            (0.24, {
                "PelvisLoc": (0.000, -0.020, -0.040),
                "Pelvis": (0.8, -18.0, 0.0), "Spine": (1.2, -8.5, 0.0), "Chest": (0.8, -15.0, 0.0),
                "Neck": (-1.0, 13.5, 1.5), "Head": (-0.8, 17.5, 2.5),
                "Thigh_L": (22.0, 0.0, 5.2), "Shin_L": (-23.0, 0.0, 0.0), "Foot_L": (4.5, 0.0, 0.0),
                "Thigh_R": (-6.5, 0.0, -6.0), "Shin_R": (-16.5, 0.0, 0.0), "Foot_R": (21.5, 0.0, 0.0),
            }),
            (0.48, {
                "PelvisLoc": (-0.010, -0.018, -0.042),
                "Pelvis": (0.8, -12.0, -1.5), "Spine": (1.0, -4.5, -1.0), "Chest": (0.6, -7.0, -1.0),
                "Neck": (-1.0, 16.5, 1.0), "Head": (-0.6, 21.0, 1.5),
                "Thigh_L": (23.0, -2.0, 5.8), "Shin_L": (-24.5, 0.0, 0.0), "Foot_L": (5.0, 0.0, 0.0),
                "Thigh_R": (-5.5, 2.0, -6.2), "Shin_R": (-16.0, 0.0, 0.0), "Foot_R": (20.5, 0.0, 0.0),
            }),
            (0.74, {
                "PelvisLoc": (0.010, -0.022, -0.042),
                "Pelvis": (0.8, -24.0, 1.5), "Spine": (1.2, -12.5, 1.0), "Chest": (0.8, -23.0, 1.0),
                "Neck": (-1.0, 14.5, 2.0), "Head": (-0.8, 18.0, 3.0),
                "Thigh_L": (21.5, 2.0, 5.2), "Shin_L": (-22.5, 0.0, 0.0), "Foot_L": (4.5, 0.0, 0.0),
                "Thigh_R": (-7.5, -2.0, -6.0), "Shin_R": (-17.5, 0.0, 0.0), "Foot_R": (22.5, 0.0, 0.0),
            }),
            (1.00, {
                "PelvisLoc": (0.004, -0.014, -0.022),
                "Pelvis": (2.0, -14.0, 0.0), "Spine": (2.0, -5.0, 0.0), "Chest": (-1.0, -9.0, 0.0),
                "Neck": (-0.5, 11.0, 0.0), "Head": (0.5, 14.0, 1.0),
                "Thigh_L": (18.0, 0.0, 4.5), "Shin_L": (-20.0, 0.0, 0.0), "Foot_L": (4.0, 0.0, 0.0),
                "Thigh_R": (-5.5, 0.0, -5.0), "Shin_R": (-13.0, 0.0, 0.0), "Foot_R": (16.5, 0.0, 0.0),
            }),
        ]
        gmail_aim_blend_beats = [(0.00, 0.0), (0.24, 1.0), (0.48, 1.0), (0.74, 1.0), (1.00, 0.0)]
        gmail_sweep_yaw_beats = [(0.00, 0.0), (0.24, 0.0), (0.48, 18.0), (0.74, -18.0), (1.00, 0.0)]

        def pose_lobby_showcase(f: int, t: float) -> None:
            ph = t * 2.0 * math.pi
            br = math.sin(2.0 * ph)
            bm = _eval_beats_dict(gmail_body_beats, t)
            px, py, pz = bm["PelvisLoc"]
            set_loc("Pelvis", px, py, pz + 0.003 * br)
            for bname in ("Pelvis", "Spine", "Chest", "Neck", "Head", "Thigh_L", "Shin_L", "Foot_L", "Thigh_R", "Shin_R", "Foot_R"):
                rx, ry, rz = bm[bname]
                if bname == "Chest":
                    rx -= 0.7 * br
                set_rot(bname, rx, ry, rz)

            bpy.context.view_layer.update()
            aim_w = _eval_beats_float(gmail_aim_blend_beats, t)
            yaw_deg = _eval_beats_float(gmail_sweep_yaw_beats, t)
            yaw_rad = math.radians(yaw_deg)

            p_grip_low = chest_to_world(right=0.200, fwd=0.268, up=-0.082 + 0.004 * br)
            b_low = Vector((-0.48, 0.80, -0.36 + 0.015 * br)).normalized()

            p_sh_R = arm_obj.pose.bones["UpperArm_R"].head.copy()
            fwd_aim = Vector((-math.sin(yaw_rad), math.cos(yaw_rad), 0.0))
            right_aim = Vector((math.cos(yaw_rad), math.sin(yaw_rad), 0.0))
            p_grip_aim = p_sh_R + right_aim * (0.042 * scale_h) + fwd_aim * (0.452 * scale_h) + Vector((0.0, 0.0, (-0.018 + 0.003 * br) * scale_h))
            b_aim = Vector((-math.sin(yaw_rad), math.cos(yaw_rad), 0.025 + 0.010 * br)).normalized()

            p_grip_R = p_grip_low.lerp(p_grip_aim, aim_w)
            barrel_dir = b_low.lerp(b_aim, aim_w).normalized()
            solve_two_hand_rifle_ik(
                "LobbyShowcase", p_grip_R, barrel_dir, lobby_ik_eulers,
                pole_hint_R=Vector((0.72, -0.18, -0.67)),
                pole_hint_L=Vector((-0.48, 0.14, -0.86)),
                left_y_weights=(0.88, 0.34, 0.32),
            )

    elif product == "drive":
        # 2. DRIVE AI — "Warden Guard" (Armed w/ Breaker 12G)
        # Broad-chested high diagonal guard -> deep -0.185m wide braced defensive squat -> tall chest-out weapon heft -> warden stance
        drive_body_beats: List[Tuple[float, Dict[str, Tuple[float, float, float]]]] = [
            (0.00, {
                "PelvisLoc": (0.000, -0.006, -0.028),
                "Pelvis": (2.0, -4.0, 0.0), "Spine": (1.0, -2.0, 0.0), "Chest": (-1.5, -3.0, 0.0),
                "Neck": (0.0, 3.0, 0.0), "Head": (0.5, 5.0, 0.0),
                "Thigh_L": (16.0, -2.0, 11.5), "Shin_L": (-21.0, 0.0, 0.0), "Foot_L": (5.5, 0.0, 0.0),
                "Thigh_R": (12.0, 2.0, -11.5), "Shin_R": (-18.5, 0.0, 0.0), "Foot_R": (7.0, 0.0, 0.0),
            }),
            (0.34, {
                "PelvisLoc": (0.000, -0.032, -0.185),
                "Pelvis": (6.0, -6.0, 0.0), "Spine": (7.5, -2.5, 0.0), "Chest": (5.0, -3.5, 0.0),
                "Neck": (-6.0, 4.5, 0.0), "Head": (-7.0, 6.5, 0.0),
                "Thigh_L": (51.0, -5.0, 15.5), "Shin_L": (-71.0, 0.0, 0.0), "Foot_L": (21.0, 0.0, 0.0),
                "Thigh_R": (47.0, 5.0, -15.5), "Shin_R": (-68.0, 0.0, 0.0), "Foot_R": (22.0, 0.0, 0.0),
            }),
            (0.68, {
                "PelvisLoc": (0.000, 0.004, 0.002),
                "Pelvis": (-2.0, -3.0, 0.0), "Spine": (-5.0, -1.5, 0.0), "Chest": (-4.5, -2.0, 0.0),
                "Neck": (3.0, 2.5, 0.0), "Head": (3.5, 4.0, 0.0),
                "Thigh_L": (4.0, -2.0, 10.5), "Shin_L": (-6.0, 0.0, 0.0), "Foot_L": (2.5, 0.0, 0.0),
                "Thigh_R": (2.0, 2.0, -10.5), "Shin_R": (-5.0, 0.0, 0.0), "Foot_R": (3.5, 0.0, 0.0),
            }),
            (1.00, {
                "PelvisLoc": (0.000, -0.006, -0.028),
                "Pelvis": (2.0, -4.0, 0.0), "Spine": (1.0, -2.0, 0.0), "Chest": (-1.5, -3.0, 0.0),
                "Neck": (0.0, 3.0, 0.0), "Head": (0.5, 5.0, 0.0),
                "Thigh_L": (16.0, -2.0, 11.5), "Shin_L": (-21.0, 0.0, 0.0), "Foot_L": (5.5, 0.0, 0.0),
                "Thigh_R": (12.0, 2.0, -11.5), "Shin_R": (-18.5, 0.0, 0.0), "Foot_R": (7.0, 0.0, 0.0),
            }),
        ]
        drive_grip_beats = [
            (0.00, Vector((0.232, 0.312, -0.036))),
            (0.34, Vector((0.235, 0.352, -0.068))),
            (0.68, Vector((0.228, 0.320, +0.028))),
            (1.00, Vector((0.232, 0.312, -0.036))),
        ]
        drive_barrel_beats = [
            (0.00, Vector((-0.68, 0.48, 0.55)).normalized()),
            (0.34, Vector((-0.58, 0.79, 0.18)).normalized()),
            (0.68, Vector((-0.64, 0.44, 0.63)).normalized()),
            (1.00, Vector((-0.68, 0.48, 0.55)).normalized()),
        ]

        def pose_lobby_showcase(f: int, t: float) -> None:
            ph = t * 2.0 * math.pi
            br = math.sin(2.0 * ph)
            bm = _eval_beats_dict(drive_body_beats, t)
            px, py, pz = bm["PelvisLoc"]
            set_loc("Pelvis", px, py, pz + 0.003 * br)
            for bname in ("Pelvis", "Spine", "Chest", "Neck", "Head", "Thigh_L", "Shin_L", "Foot_L", "Thigh_R", "Shin_R", "Foot_R"):
                rx, ry, rz = bm[bname]
                set_rot(bname, rx, ry, rz)

            bpy.context.view_layer.update()
            g_off = _eval_beats_vec(drive_grip_beats, t)
            p_grip_R = chest_to_world(right=g_off.x, fwd=g_off.y, up=g_off.z + 0.005 * br)
            barrel_dir = _eval_beats_vec(drive_barrel_beats, t).normalized()
            solve_two_hand_rifle_ik(
                "LobbyShowcase", p_grip_R, barrel_dir, lobby_ik_eulers,
                pole_hint_R=Vector((0.72, -0.24, -0.65)),
                pole_hint_L=Vector((-0.62, 0.14, -0.77)),
                left_y_weights=(0.82, 0.24, 0.52),
            )

    elif product == "calendar":
        # 3. CALENDAR AI — "Chrono Check" (UNARMED!)
        # Energetic sprinter/boxer weight-shift bounce -> wrist holo time-block check + thoughtful nod
        # -> bold forward "Hard Stop" open-palm halt gesture (left hand on hip) -> tempo bounce!
        cal_body_beats: List[Tuple[float, Dict[str, Tuple[float, float, float]]]] = [
            (0.00, {
                "PelvisLoc": (0.032, 0.006, -0.026),
                "Pelvis": (3.0, 7.0, -3.5), "Spine": (2.0, -3.5, 2.0), "Chest": (0.5, -4.0, 1.5),
                "Neck": (-1.0, 2.5, -1.0), "Head": (-0.5, 4.0, -1.5),
                "Thigh_L": (18.0, 0.0, 6.0), "Shin_L": (-24.0, 0.0, 0.0), "Foot_L": (7.0, 0.0, 0.0),
                "Thigh_R": (8.0, 0.0, -4.5), "Shin_R": (-16.0, 0.0, 0.0), "Foot_R": (9.0, 0.0, 0.0),
            }),
            (0.14, {
                "PelvisLoc": (-0.034, 0.008, -0.034),
                "Pelvis": (3.5, -7.0, 3.5), "Spine": (2.5, 3.5, -2.0), "Chest": (1.0, 4.0, -1.5),
                "Neck": (-1.5, -2.5, 1.0), "Head": (-1.0, -4.0, 1.5),
                "Thigh_L": (9.0, 0.0, 4.5), "Shin_L": (-17.0, 0.0, 0.0), "Foot_L": (9.0, 0.0, 0.0),
                "Thigh_R": (22.0, 0.0, -6.0), "Shin_R": (-29.0, 0.0, 0.0), "Foot_R": (8.0, 0.0, 0.0),
            }),
            (0.32, {
                "PelvisLoc": (-0.012, -0.004, -0.018),
                "Pelvis": (2.0, 5.0, -1.5), "Spine": (4.0, 4.0, -2.5), "Chest": (5.5, 4.0, -3.5),
                "Neck": (6.0, 3.0, -3.5), "Head": (12.0, 5.0, -7.5),
                "Thigh_L": (14.0, 0.0, 4.5), "Shin_L": (-17.0, 0.0, 0.0), "Foot_L": (4.0, 0.0, 0.0),
                "Thigh_R": (-2.0, 0.0, -4.5), "Shin_R": (-12.0, 0.0, 0.0), "Foot_R": (14.0, 0.0, 0.0),
            }),
            (0.41, {
                "PelvisLoc": (-0.010, -0.004, -0.024),
                "Pelvis": (2.5, 5.0, -1.5), "Spine": (6.0, 4.0, -2.5), "Chest": (9.0, 4.0, -3.5),
                "Neck": (10.0, 3.0, -3.5), "Head": (23.0, 5.0, -6.5),
                "Thigh_L": (16.0, 0.0, 4.5), "Shin_L": (-19.5, 0.0, 0.0), "Foot_L": (4.5, 0.0, 0.0),
                "Thigh_R": (-1.0, 0.0, -4.5), "Shin_R": (-13.5, 0.0, 0.0), "Foot_R": (15.0, 0.0, 0.0),
            }),
            (0.50, {
                "PelvisLoc": (-0.004, 0.000, -0.016),
                "Pelvis": (1.5, 3.0, 0.0), "Spine": (1.5, 2.0, -1.0), "Chest": (1.5, 3.0, -1.0),
                "Neck": (0.0, -1.0, 0.0), "Head": (-1.0, -2.0, 0.0),
                "Thigh_L": (14.0, 0.0, 4.5), "Shin_L": (-16.5, 0.0, 0.0), "Foot_L": (3.5, 0.0, 0.0),
                "Thigh_R": (-2.5, 0.0, -4.5), "Shin_R": (-11.0, 0.0, 0.0), "Foot_R": (13.5, 0.0, 0.0),
            }),
            (0.68, {
                "PelvisLoc": (0.012, 0.012, -0.028),
                "Pelvis": (1.5, 4.0, -2.0), "Spine": (0.0, 2.0, -2.0), "Chest": (-5.0, 2.0, -3.0),
                "Neck": (1.0, -4.0, 2.0), "Head": (1.5, -6.0, 3.0),
                "Thigh_L": (22.0, 0.0, 6.5), "Shin_L": (-26.0, 0.0, 0.0), "Foot_L": (5.0, 0.0, 0.0),
                "Thigh_R": (-8.5, 0.0, -6.5), "Shin_R": (-12.5, 0.0, 0.0), "Foot_R": (20.0, 0.0, 0.0),
            }),
            (0.79, {
                "PelvisLoc": (0.012, 0.012, -0.026),
                "Pelvis": (1.5, 4.0, -2.0), "Spine": (0.0, 2.0, -2.0), "Chest": (-5.0, 2.0, -3.0),
                "Neck": (1.0, -4.0, 2.0), "Head": (1.5, -6.0, 3.0),
                "Thigh_L": (22.0, 0.0, 6.5), "Shin_L": (-26.0, 0.0, 0.0), "Foot_L": (5.0, 0.0, 0.0),
                "Thigh_R": (-8.5, 0.0, -6.5), "Shin_R": (-12.5, 0.0, 0.0), "Foot_R": (20.0, 0.0, 0.0),
            }),
            (0.91, {
                "PelvisLoc": (-0.018, 0.008, -0.030),
                "Pelvis": (3.0, -4.0, 2.0), "Spine": (2.0, 2.0, -1.0), "Chest": (0.5, 2.0, -1.0),
                "Neck": (-1.0, -1.0, 0.5), "Head": (-0.5, -2.0, 1.0),
                "Thigh_L": (12.0, 0.0, 5.0), "Shin_L": (-19.0, 0.0, 0.0), "Foot_L": (8.0, 0.0, 0.0),
                "Thigh_R": (16.0, 0.0, -5.5), "Shin_R": (-23.0, 0.0, 0.0), "Foot_R": (8.0, 0.0, 0.0),
            }),
            (1.00, {
                "PelvisLoc": (0.032, 0.006, -0.026),
                "Pelvis": (3.0, 7.0, -3.5), "Spine": (2.0, -3.5, 2.0), "Chest": (0.5, -4.0, 1.5),
                "Neck": (-1.0, 2.5, -1.0), "Head": (-0.5, 4.0, -1.5),
                "Thigh_L": (18.0, 0.0, 6.0), "Shin_L": (-24.0, 0.0, 0.0), "Foot_L": (7.0, 0.0, 0.0),
                "Thigh_R": (8.0, 0.0, -4.5), "Shin_R": (-16.0, 0.0, 0.0), "Foot_R": (9.0, 0.0, 0.0),
            }),
        ]

        # Precompute crisp world-space hand orientations for each Calendar beat (slerped smoothly!)
        R_guard_L = _make_basis_yz(Vector((0.32, 0.62, 0.72)), Vector((0.0, 0.80, -0.60)))
        R_guard_R = _make_basis_yz(Vector((-0.32, 0.62, 0.72)), Vector((0.0, 0.80, -0.60)))
        R_watch_L = _make_basis_yz(Vector((0.78, 0.36, 0.50)), Vector((-0.10, -0.68, 0.72)))
        R_watch_R = _make_basis_yz(Vector((-0.18, 0.56, -0.80)), Vector((0.0, 0.85, 0.52)))
        # Unmistakable "Hard Stop" open-palm halt: Right palm (-X_hand_R) faces +Y forward, fingers (+Y) straight +Z UP!
        R_stop_R = Matrix((Vector((0.0, -1.0, 0.0)), Vector((0.0, 0.0, 1.0)), Vector((-1.0, 0.0, 0.0)))).transposed()
        R_hip_L = _make_basis_yz(Vector((0.55, 0.25, -0.80)), Vector((0.0, 0.90, 0.42)))

        cal_hand_beats: List[Tuple[float, Vector, Matrix, Vector, Matrix, Vector, Vector]] = [
            # (t, chest_L, R_L, chest_R, R_R, pole_L, pole_R)
            (0.00, Vector((-0.30, 0.24, -0.05)), R_guard_L, Vector((+0.30, 0.22, -0.09)), R_guard_R, Vector((-0.72, -0.20, -0.66)), Vector((+0.72, -0.20, -0.66))),
            (0.14, Vector((-0.31, 0.26, -0.01)), R_guard_L, Vector((+0.30, 0.20, -0.11)), R_guard_R, Vector((-0.72, -0.20, -0.66)), Vector((+0.72, -0.20, -0.66))),
            (0.32, Vector((+0.04, 0.35, +0.22)), R_watch_L, Vector((+0.33, 0.08, -0.20)), R_watch_R, Vector((-0.68, +0.30, -0.66)), Vector((+0.84, -0.22, -0.50))),
            (0.41, Vector((+0.04, 0.35, +0.22)), R_watch_L, Vector((+0.33, 0.08, -0.20)), R_watch_R, Vector((-0.68, +0.30, -0.66)), Vector((+0.84, -0.22, -0.50))),
            (0.52, Vector((-0.32, 0.28, -0.02)), R_guard_L, Vector((+0.32, 0.28, +0.04)), R_guard_R, Vector((-0.82, +0.05, -0.57)), Vector((+0.72, -0.18, -0.67))),
            (0.68, Vector((-0.31, 0.02, -0.23)), R_hip_L,   Vector((+0.31, 0.56, +0.20)), R_stop_R,  Vector((-0.96, +0.05, -0.26)), Vector((+0.55, -0.12, -0.82))),
            (0.79, Vector((-0.31, 0.02, -0.23)), R_hip_L,   Vector((+0.31, 0.56, +0.20)), R_stop_R,  Vector((-0.96, +0.05, -0.26)), Vector((+0.55, -0.12, -0.82))),
            (0.91, Vector((-0.31, 0.22, -0.06)), R_guard_L, Vector((+0.30, 0.24, -0.05)), R_guard_R, Vector((-0.74, -0.18, -0.65)), Vector((+0.72, -0.22, -0.66))),
            (1.00, Vector((-0.30, 0.24, -0.05)), R_guard_L, Vector((+0.30, 0.22, -0.09)), R_guard_R, Vector((-0.72, -0.20, -0.66)), Vector((+0.72, -0.20, -0.66))),
        ]

        def pose_lobby_showcase(f: int, t: float) -> None:
            ph = t * 2.0 * math.pi
            # Rhythmic boxer-bounce pulse active during tempo phases, damped smoothly during wrist-check & Hard Stop
            tempo_env = 1.0 - _smootherstep01((t - 0.16) / 0.14) + _smootherstep01((t - 0.80) / 0.14)
            tempo_env = max(0.0, min(1.0, tempo_env))
            bounce = math.sin(4.0 * ph) * 0.012 * tempo_env

            bm = _eval_beats_dict(cal_body_beats, t)
            px, py, pz = bm["PelvisLoc"]
            set_loc("Pelvis", px, py, pz + bounce)
            for bname in ("Pelvis", "Spine", "Chest", "Neck", "Head", "Thigh_L", "Shin_L", "Foot_L", "Thigh_R", "Shin_R", "Foot_R"):
                rx, ry, rz = bm[bname]
                set_rot(bname, rx, ry, rz)

            bpy.context.view_layer.update()

            # Interpolate Calendar's expressive unarmed hand targets & orientations cleanly
            hb0 = cal_hand_beats[-1]
            hb1 = cal_hand_beats[-1]
            w_h = 0.0
            for idx in range(len(cal_hand_beats) - 1):
                if cal_hand_beats[idx][0] <= t <= cal_hand_beats[idx + 1][0]:
                    hb0, hb1 = cal_hand_beats[idx], cal_hand_beats[idx + 1]
                    w_h = _smootherstep01((t - hb0[0]) / max(hb1[0] - hb0[0], 1e-6))
                    break

            cL = hb0[1].lerp(hb1[1], w_h)
            cR = hb0[3].lerp(hb1[3], w_h)
            R_L = hb0[2].to_quaternion().slerp(hb1[2].to_quaternion(), w_h).to_matrix()
            R_R = hb0[4].to_quaternion().slerp(hb1[4].to_quaternion(), w_h).to_matrix()
            pole_L = hb0[5].lerp(hb1[5], w_h).normalized()
            pole_R = hb0[6].lerp(hb1[6], w_h).normalized()

            p_palm_L = chest_to_world(right=cL.x, fwd=cL.y, up=cL.z + bounce * 0.6)
            p_palm_R = chest_to_world(right=cR.x, fwd=cR.y, up=cR.z + bounce * 0.6)
            solve_single_arm_ik("L", p_palm_L, R_L, pole_L, lobby_ik_eulers)
            solve_single_arm_ik("R", p_palm_R, R_R, pole_R, lobby_ik_eulers)

    elif product == "chat":
        # 4. CHAT AI — "Recon Peek" (Armed w/ Vector-9 SMG)
        # Agile athletic half-crouch -> swift left (-0.092m) & right (+0.092m) tactical recon peeks
        # -> springs upward onto toes into ready-to-pounce combat bounce w/ snappy angled SMG -> back to crouch
        chat_body_beats: List[Tuple[float, Dict[str, Tuple[float, float, float]]]] = [
            (0.00, {
                "PelvisLoc": (0.000, 0.012, -0.115),
                "Pelvis": (8.0, -10.0, 0.0), "Spine": (7.0, -4.0, 0.0), "Chest": (4.0, -6.0, 0.0),
                "Neck": (-7.0, 8.0, 0.0), "Head": (-8.0, 10.0, 0.0),
                "Thigh_L": (44.0, 0.0, 6.5), "Shin_L": (-60.0, 0.0, 0.0), "Foot_L": (16.5, 0.0, 0.0),
                "Thigh_R": (37.0, 0.0, -6.5), "Shin_R": (-56.0, 0.0, 0.0), "Foot_R": (19.5, 0.0, 0.0),
            }),
            (0.22, {
                "PelvisLoc": (-0.092, 0.022, -0.108),
                "Pelvis": (8.5, 3.0, -10.5), "Spine": (6.0, 5.5, -8.0), "Chest": (4.0, 7.5, -7.0),
                "Neck": (-6.0, 7.5, 5.5), "Head": (-7.0, 11.5, 7.5),
                "Thigh_L": (50.0, -4.0, 14.5), "Shin_L": (-68.0, 0.0, 0.0), "Foot_L": (18.5, 0.0, 0.0),
                "Thigh_R": (35.0, 4.0, -14.5), "Shin_R": (-52.0, 0.0, 0.0), "Foot_R": (17.0, 0.0, 0.0),
            }),
            (0.48, {
                "PelvisLoc": (+0.092, 0.022, -0.108),
                "Pelvis": (8.5, -22.0, 10.5), "Spine": (6.0, -9.5, 8.0), "Chest": (4.0, -12.5, 7.0),
                "Neck": (-6.0, 10.0, -5.5), "Head": (-7.0, 14.0, -7.5),
                "Thigh_L": (35.0, -4.0, 14.5), "Shin_L": (-52.0, 0.0, 0.0), "Foot_L": (17.0, 0.0, 0.0),
                "Thigh_R": (50.0, 4.0, -14.5), "Shin_R": (-68.0, 0.0, 0.0), "Foot_R": (18.5, 0.0, 0.0),
            }),
            (0.74, {
                "PelvisLoc": (0.000, 0.014, 0.044),
                "Pelvis": (1.0, -14.0, 3.0), "Spine": (-2.0, -5.0, 3.0), "Chest": (-3.0, -7.0, 4.0),
                "Neck": (1.0, 9.0, -2.0), "Head": (2.0, 12.0, -3.0),
                "Thigh_L": (8.0, 0.0, 5.0), "Shin_L": (-12.0, 0.0, 0.0), "Foot_L": (-24.0, 0.0, 0.0),
                "Thigh_R": (-2.0, 0.0, -5.0), "Shin_R": (-10.0, 0.0, 0.0), "Foot_R": (-22.0, 0.0, 0.0),
            }),
            (1.00, {
                "PelvisLoc": (0.000, 0.012, -0.115),
                "Pelvis": (8.0, -10.0, 0.0), "Spine": (7.0, -4.0, 0.0), "Chest": (4.0, -6.0, 0.0),
                "Neck": (-7.0, 8.0, 0.0), "Head": (-8.0, 10.0, 0.0),
                "Thigh_L": (44.0, 0.0, 6.5), "Shin_L": (-60.0, 0.0, 0.0), "Foot_L": (16.5, 0.0, 0.0),
                "Thigh_R": (37.0, 0.0, -6.5), "Shin_R": (-56.0, 0.0, 0.0), "Foot_R": (19.5, 0.0, 0.0),
            }),
        ]
        chat_grip_beats = [
            (0.00, Vector((0.205, 0.268, -0.045))),
            (0.22, Vector((0.205, 0.274, -0.025))),
            (0.48, Vector((0.208, 0.278, -0.020))),
            (0.74, Vector((0.208, 0.276, -0.010))),
            (1.00, Vector((0.205, 0.268, -0.045))),
        ]
        # Expressed in chest-local frame (right, fwd, up) so Vector-9 stays tightly tucked during agile left/right peeks!
        chat_barrel_chest_beats = [
            (0.00, Vector((-0.68, 0.71, -0.18)).normalized()),
            (0.22, Vector((-0.70, 0.71, +0.08)).normalized()),
            (0.48, Vector((-0.68, 0.73, +0.08)).normalized()),
            (0.74, Vector((-0.72, 0.52, +0.46)).normalized()),
            (1.00, Vector((-0.68, 0.71, -0.18)).normalized()),
        ]

        def pose_lobby_showcase(f: int, t: float) -> None:
            bm = _eval_beats_dict(chat_body_beats, t)
            px, py, pz = bm["PelvisLoc"]
            set_loc("Pelvis", px, py, pz)
            for bname in ("Pelvis", "Spine", "Chest", "Neck", "Head", "Thigh_L", "Shin_L", "Foot_L", "Thigh_R", "Shin_R", "Foot_R"):
                rx, ry, rz = bm[bname]
                set_rot(bname, rx, ry, rz)

            bpy.context.view_layer.update()
            g_off = _eval_beats_vec(chat_grip_beats, t)
            p_grip_R = chest_to_world(right=g_off.x, fwd=g_off.y, up=g_off.z)
            b_ch = _eval_beats_vec(chat_barrel_chest_beats, t)
            barrel_dir = chest_dir_to_world(b_ch.x, b_ch.y, b_ch.z)
            solve_two_hand_rifle_ik(
                "LobbyShowcase", p_grip_R, barrel_dir, lobby_ik_eulers,
                pole_hint_R=Vector((0.72, -0.22, -0.66)),
                pole_hint_L=Vector((-0.56, 0.14, -0.82)),
                left_y_weights=(0.86, 0.32, 0.38),
            )

    elif product == "slides":
        # 5. SLIDES AI — "Spotlight Sightline" (Armed w/ Longbow .308 Sniper — 1.18m length!)
        # Tall poised bladed gallery carry -> razor-steady horizontal precision sightline w/ slow azimuth track
        # -> subtle optic-check head tilt -> eases regally back into gallery carry (0 BVHTree overlap w/ Longbow .308!)
        slides_body_beats: List[Tuple[float, Dict[str, Tuple[float, float, float]]]] = [
            (0.00, {
                "PelvisLoc": (0.000, -0.015, -0.010),
                "Pelvis": (0.5, -20.0, 0.0), "Spine": (-1.5, -8.0, 0.0), "Chest": (-1.5, -14.0, 0.0),
                "Neck": (1.0, 16.0, 0.0), "Head": (1.0, 20.0, 0.0),
                "Thigh_L": (15.0, 0.0, 3.5), "Shin_L": (-14.0, 0.0, 0.0), "Foot_L": (2.0, 0.0, 0.0),
                "Thigh_R": (-8.0, 0.0, -4.5), "Shin_R": (-8.0, 0.0, 0.0), "Foot_R": (15.0, 0.0, 0.0),
            }),
            (0.30, {
                "PelvisLoc": (0.000, -0.020, -0.024),
                "Pelvis": (0.5, -16.5, 0.0), "Spine": (0.8, -7.5, 0.0), "Chest": (0.5, -13.5, 0.0),
                "Neck": (-0.8, 14.0, 1.5), "Head": (-0.6, 17.5, 2.5),
                "Thigh_L": (18.5, 0.0, 4.2), "Shin_L": (-18.0, 0.0, 0.0), "Foot_L": (3.0, 0.0, 0.0),
                "Thigh_R": (-7.5, 0.0, -5.2), "Shin_R": (-13.0, 0.0, 0.0), "Foot_R": (19.5, 0.0, 0.0),
            }),
            (0.58, {
                "PelvisLoc": (0.004, -0.022, -0.024),
                "Pelvis": (0.5, -21.0, 0.0), "Spine": (0.8, -10.0, 0.0), "Chest": (0.5, -18.5, 0.0),
                "Neck": (-0.8, 16.0, 1.5), "Head": (-0.6, 20.0, 3.0),
                "Thigh_L": (18.5, 0.0, 4.2), "Shin_L": (-18.0, 0.0, 0.0), "Foot_L": (3.0, 0.0, 0.0),
                "Thigh_R": (-7.5, 0.0, -5.2), "Shin_R": (-13.0, 0.0, 0.0), "Foot_R": (19.5, 0.0, 0.0),
            }),
            (0.76, {
                "PelvisLoc": (0.002, -0.018, -0.016),
                "Pelvis": (0.5, -20.5, 0.0), "Spine": (-0.5, -9.0, 0.0), "Chest": (-0.5, -16.0, 0.0),
                "Neck": (1.5, 14.5, 4.0), "Head": (4.5, 18.5, 9.5),
                "Thigh_L": (16.5, 0.0, 3.8), "Shin_L": (-16.0, 0.0, 0.0), "Foot_L": (2.5, 0.0, 0.0),
                "Thigh_R": (-8.0, 0.0, -4.8), "Shin_R": (-10.0, 0.0, 0.0), "Foot_R": (17.0, 0.0, 0.0),
            }),
            (1.00, {
                "PelvisLoc": (0.000, -0.015, -0.010),
                "Pelvis": (0.5, -20.0, 0.0), "Spine": (-1.5, -8.0, 0.0), "Chest": (-1.5, -14.0, 0.0),
                "Neck": (1.0, 16.0, 0.0), "Head": (1.0, 20.0, 0.0),
                "Thigh_L": (15.0, 0.0, 3.5), "Shin_L": (-14.0, 0.0, 0.0), "Foot_L": (2.0, 0.0, 0.0),
                "Thigh_R": (-8.0, 0.0, -4.5), "Shin_R": (-8.0, 0.0, 0.0), "Foot_R": (15.0, 0.0, 0.0),
            }),
        ]
        slides_aim_blend_beats = [(0.00, 0.0), (0.30, 1.0), (0.58, 1.0), (0.76, 0.62), (1.00, 0.0)]
        slides_azim_beats = [(0.00, 0.0), (0.30, 6.0), (0.58, -6.0), (0.76, 2.0), (1.00, 0.0)]

        def pose_lobby_showcase(f: int, t: float) -> None:
            ph = t * 2.0 * math.pi
            br = math.sin(ph)  # Slow calm marksman breath!
            bm = _eval_beats_dict(slides_body_beats, t)
            px, py, pz = bm["PelvisLoc"]
            set_loc("Pelvis", px, py, pz + 0.003 * br)
            for bname in ("Pelvis", "Spine", "Chest", "Neck", "Head", "Thigh_L", "Shin_L", "Foot_L", "Thigh_R", "Shin_R", "Foot_R"):
                rx, ry, rz = bm[bname]
                if bname == "Chest":
                    rx -= 0.5 * br
                set_rot(bname, rx, ry, rz)

            bpy.context.view_layer.update()
            aim_w = _eval_beats_float(slides_aim_blend_beats, t)
            yaw_rad = math.radians(_eval_beats_float(slides_azim_beats, t))

            # Poised tall gallery carry (buttstock clears Slides deck & upper arm cleanly!)
            p_grip_carry = chest_to_world(right=0.220, fwd=0.334, up=-0.012 + 0.004 * br)
            b_carry = Vector((-0.66, 0.62, 0.42 + 0.010 * br)).normalized()

            # Razor-steady Executive Spotlight horizontal sightline (0.32m buttstock strictly outboard of Slides deck!)
            p_sh_R = arm_obj.pose.bones["UpperArm_R"].head.copy()
            fwd_aim = Vector((-math.sin(yaw_rad), math.cos(yaw_rad), 0.0))
            right_aim = Vector((math.cos(yaw_rad), math.sin(yaw_rad), 0.0))
            p_grip_aim = p_sh_R + right_aim * (0.052 * scale_h) + fwd_aim * (0.466 * scale_h) + Vector((0.0, 0.0, (-0.010 + 0.004 * br) * scale_h))
            b_aim = Vector((-math.sin(yaw_rad), math.cos(yaw_rad), 0.012 + 0.006 * br)).normalized()

            p_grip_R = p_grip_carry.lerp(p_grip_aim, aim_w)
            barrel_dir = b_carry.lerp(b_aim, aim_w).normalized()
            solve_two_hand_rifle_ik(
                "LobbyShowcase", p_grip_R, barrel_dir, lobby_ik_eulers,
                pole_hint_R=Vector((0.46, -0.10, -0.88)),
                pole_hint_L=Vector((-0.46, 0.14, -0.88)),
                left_y_weights=(0.88, 0.34, 0.32),
            )

    else:
        # 6. DOCS AI — "Version Hover" (Armed w/ Nova GL-40 Launcher)
        # Grounded low-hip launcher -> springy anticipation knee dip -> buoyant zero-G Version History hover
        # (Pelvis rises +0.18m, asymmetric tucked floating knees, dreamy back/side lean) -> cushioned landing & heft!
        docs_body_beats: List[Tuple[float, Dict[str, Tuple[float, float, float]]]] = [
            (0.00, {
                "PelvisLoc": (0.000, -0.010, -0.020),
                "Pelvis": (2.0, -10.0, -2.0), "Spine": (2.0, -4.0, -1.0), "Chest": (0.0, -5.0, -1.0),
                "Neck": (-1.0, 7.0, 1.0), "Head": (1.0, 9.0, 1.0),
                "Thigh_L": (14.0, 0.0, 5.0), "Shin_L": (-17.0, 0.0, 0.0), "Foot_L": (4.0, 0.0, 0.0),
                "Thigh_R": (-2.0, 0.0, -5.0), "Shin_R": (-13.0, 0.0, 0.0), "Foot_R": (14.0, 0.0, 0.0),
            }),
            (0.16, {
                "PelvisLoc": (0.000, -0.016, -0.115),
                "Pelvis": (7.0, -10.0, 0.0), "Spine": (7.0, -3.0, 0.0), "Chest": (5.0, -4.0, 0.0),
                "Neck": (-6.0, 6.0, 0.0), "Head": (-8.0, 8.0, 0.0),
                "Thigh_L": (44.0, 0.0, 7.0), "Shin_L": (-60.0, 0.0, 0.0), "Foot_L": (18.0, 0.0, 0.0),
                "Thigh_R": (38.0, 0.0, -7.0), "Shin_R": (-56.0, 0.0, 0.0), "Foot_R": (20.0, 0.0, 0.0),
            }),
            (0.44, {
                "PelvisLoc": (+0.024, -0.026, +0.178),
                "Pelvis": (-11.0, -14.0, 6.5), "Spine": (-7.5, -4.0, 6.0), "Chest": (-6.0, -3.0, 5.0),
                "Neck": (8.5, 8.0, -4.5), "Head": (11.5, 11.0, -7.5),
                "Thigh_L": (50.0, -8.0, 10.5), "Shin_L": (-86.0, 0.0, 0.0), "Foot_L": (-28.0, 0.0, 0.0),
                "Thigh_R": (10.0, 6.0, -8.5), "Shin_R": (-44.0, 0.0, 0.0), "Foot_R": (-32.0, 0.0, 0.0),
            }),
            (0.58, {
                "PelvisLoc": (-0.018, -0.032, +0.192),
                "Pelvis": (-13.0, -10.0, -4.0), "Spine": (-8.0, -2.0, -4.0), "Chest": (-6.0, -2.0, -3.5),
                "Neck": (9.0, 6.0, 3.0), "Head": (12.0, 8.5, 5.0),
                "Thigh_L": (40.0, -6.0, 9.5), "Shin_L": (-76.0, 0.0, 0.0), "Foot_L": (-30.0, 0.0, 0.0),
                "Thigh_R": (24.0, 6.0, -10.0), "Shin_R": (-62.0, 0.0, 0.0), "Foot_R": (-28.0, 0.0, 0.0),
            }),
            (0.76, {
                "PelvisLoc": (0.000, -0.012, -0.095),
                "Pelvis": (6.0, -10.0, 0.0), "Spine": (5.0, -3.0, 0.0), "Chest": (3.0, -4.0, 0.0),
                "Neck": (-4.5, 6.0, 0.0), "Head": (-5.5, 7.5, 0.0),
                "Thigh_L": (40.0, 0.0, 6.0), "Shin_L": (-54.0, 0.0, 0.0), "Foot_L": (16.0, 0.0, 0.0),
                "Thigh_R": (34.0, 0.0, -6.0), "Shin_R": (-50.0, 0.0, 0.0), "Foot_R": (18.0, 0.0, 0.0),
            }),
            (0.88, {
                "PelvisLoc": (0.000, 0.000, +0.004),
                "Pelvis": (-2.0, -10.0, 0.0), "Spine": (-4.0, -3.0, 0.0), "Chest": (-3.5, -4.0, 0.0),
                "Neck": (2.5, 6.5, 0.0), "Head": (3.0, 8.5, 0.0),
                "Thigh_L": (6.0, 0.0, 4.0), "Shin_L": (-8.0, 0.0, 0.0), "Foot_L": (2.5, 0.0, 0.0),
                "Thigh_R": (-4.0, 0.0, -5.0), "Shin_R": (-6.0, 0.0, 0.0), "Foot_R": (10.0, 0.0, 0.0),
            }),
            (1.00, {
                "PelvisLoc": (0.000, -0.010, -0.020),
                "Pelvis": (2.0, -10.0, -2.0), "Spine": (2.0, -4.0, -1.0), "Chest": (0.0, -5.0, -1.0),
                "Neck": (-1.0, 7.0, 1.0), "Head": (1.0, 9.0, 1.0),
                "Thigh_L": (14.0, 0.0, 5.0), "Shin_L": (-17.0, 0.0, 0.0), "Foot_L": (4.0, 0.0, 0.0),
                "Thigh_R": (-2.0, 0.0, -5.0), "Shin_R": (-13.0, 0.0, 0.0), "Foot_R": (14.0, 0.0, 0.0),
            }),
        ]
        docs_grip_beats = [
            (0.00, Vector((0.208, 0.268, -0.075))),
            (0.16, Vector((0.210, 0.272, -0.070))),
            (0.44, Vector((0.210, 0.274, -0.010))),
            (0.58, Vector((0.210, 0.276, -0.005))),
            (0.76, Vector((0.210, 0.274, -0.055))),
            (0.88, Vector((0.208, 0.274, +0.018))),
            (1.00, Vector((0.208, 0.268, -0.075))),
        ]
        # Expressed in chest-local frame so heavy Nova GL-40 floats cleanly with Docs AI during zero-G rewind!
        docs_barrel_chest_beats = [
            (0.00, Vector((-0.72, 0.66, -0.22)).normalized()),
            (0.16, Vector((-0.70, 0.69, -0.18)).normalized()),
            (0.44, Vector((-0.74, 0.60, +0.30)).normalized()),
            (0.58, Vector((-0.72, 0.62, +0.30)).normalized()),
            (0.76, Vector((-0.72, 0.68, -0.10)).normalized()),
            (0.88, Vector((-0.72, 0.52, +0.46)).normalized()),
            (1.00, Vector((-0.72, 0.66, -0.22)).normalized()),
        ]

        def pose_lobby_showcase(f: int, t: float) -> None:
            bm = _eval_beats_dict(docs_body_beats, t)
            px, py, pz = bm["PelvisLoc"]
            set_loc("Pelvis", px, py, pz)
            for bname in ("Pelvis", "Spine", "Chest", "Neck", "Head", "Thigh_L", "Shin_L", "Foot_L", "Thigh_R", "Shin_R", "Foot_R"):
                rx, ry, rz = bm[bname]
                set_rot(bname, rx, ry, rz)

            bpy.context.view_layer.update()
            g_off = _eval_beats_vec(docs_grip_beats, t)
            p_grip_R = chest_to_world(right=g_off.x, fwd=g_off.y, up=g_off.z)
            b_ch = _eval_beats_vec(docs_barrel_chest_beats, t)
            barrel_dir = chest_dir_to_world(b_ch.x, b_ch.y, b_ch.z)
            solve_two_hand_rifle_ik(
                "LobbyShowcase", p_grip_R, barrel_dir, lobby_ik_eulers,
                pole_hint_R=Vector((0.72, -0.24, -0.65)),
                pole_hint_L=Vector((-0.60, 0.14, -0.78)),
                left_y_weights=(0.84, 0.28, 0.44),
            )

    # Verify exact seamless loop continuity (f_first == f_last) while pushing LobbyShowcase
    lobby_first_pose: Dict[str, Tuple[Tuple[float, float, float], Tuple[float, float, float]]] = {}
    lobby_last_pose: Dict[str, Tuple[Tuple[float, float, float], Tuple[float, float, float]]] = {}

    def _pose_lobby_wrapped(f: int, t: float) -> None:
        pose_lobby_showcase(f, t)
        if f == LOBBY_SHOWCASE_FRAMES[0]:
            for pb in arm_obj.pose.bones:
                lobby_first_pose[pb.name] = (tuple(pb.location), tuple(pb.rotation_euler))
        elif f == LOBBY_SHOWCASE_FRAMES[-1]:
            for pb in arm_obj.pose.bones:
                lobby_last_pose[pb.name] = (tuple(pb.location), tuple(pb.rotation_euler))

    push_action("LobbyShowcase", LOBBY_SHOWCASE_FRAMES, _pose_lobby_wrapped)

    max_loop_rot_err = 0.0
    max_loop_loc_err = 0.0
    for bname in BONE_NAMES:
        l0, r0 = lobby_first_pose[bname]
        l1, r1 = lobby_last_pose[bname]
        max_loop_loc_err = max(max_loop_loc_err, max(abs(a - b) for a, b in zip(l0, l1)))
        from mathutils import Euler as _Euler
        q0 = _Euler(r0, "XYZ").to_quaternion()
        q1 = _Euler(r1, "XYZ").to_quaternion()
        max_loop_rot_err = max(max_loop_rot_err, q0.rotation_difference(q1).angle)
    assert max_loop_loc_err < 1e-4 and max_loop_rot_err < 1e-3, (
        f"{product} LobbyShowcase loop seam mismatch! loc_err={max_loop_loc_err:.6f}m rot_err={max_loop_rot_err:.6f}rad"
    )

    arm_obj.animation_data.action = None
    arm_obj.animation_data.use_nla = True
    reset_pose()

    def _to_three(v: Vector) -> Tuple[float, float, float]:
        return (round(v.x, 4), round(v.z, 4), round(-v.y, 4))

    avg_hl = sum(glide_hand_L_samples, Vector((0, 0, 0))) / max(len(glide_hand_L_samples), 1)
    avg_hr = sum(glide_hand_R_samples, Vector((0, 0, 0))) / max(len(glide_hand_R_samples), 1)
    avg_pl = sum(glide_palm_L_samples, Vector((0, 0, 0))) / max(len(glide_palm_L_samples), 1)
    avg_pr = sum(glide_palm_R_samples, Vector((0, 0, 0))) / max(len(glide_palm_R_samples), 1)
    drift_l = max((v - avg_hl).length for v in glide_hand_L_samples) if glide_hand_L_samples else 0.0
    drift_r = max((v - avg_hr).length for v in glide_hand_R_samples) if glide_hand_R_samples else 0.0

    hand_mid = (avg_hl + avg_hr) * 0.5
    palm_mid = (avg_pl + avg_pr) * 0.5
    palm_delta = palm_mid - hand_mid

    glide_metrics = {
        "hand_L_threejs": _to_three(avg_hl),
        "hand_R_threejs": _to_three(avg_hr),
        "hand_mid_threejs": _to_three(hand_mid),
        "palm_L_threejs": _to_three(avg_pl),
        "palm_R_threejs": _to_three(avg_pr),
        "palm_mid_threejs": _to_three(palm_mid),
        "palm_offset_from_hand_mid_threejs": _to_three(palm_delta),
        "half_span_m": round(0.5 * (avg_pr.x - avg_pl.x), 4),
        "max_drift_mm": round(max(drift_l, drift_r) * 1000.0, 3),
    }

    twohand_summary: Dict[str, dict] = {}
    for cname, recs in twohand_samples.items():
        avg_r = sum((r["p_grip_R"] for r in recs), Vector((0, 0, 0))) / len(recs)
        avg_l = sum((r["p_grip_L"] for r in recs), Vector((0, 0, 0))) / len(recs)
        twohand_summary[cname] = {
            "sep_m": round(sum(r["sep_m"] for r in recs) / len(recs), 4),
            "max_sep_err_mm": round(max(r["sep_err_mm"] for r in recs), 3),
            "max_palm_err_R_mm": round(max(r["err_R_mm"] for r in recs), 3),
            "max_palm_err_L_mm": round(max(r["err_L_mm"] for r in recs), 3),
            "max_sock_err_mm": round(max(r["sock_err_mm"] for r in recs), 3),
            "max_reach_R_pct": round(max(r["reach_R_pct"] for r in recs), 1),
            "max_reach_L_pct": round(max(r["reach_L_pct"] for r in recs), 1),
            "max_wrist_R_deg": round(max(r["wrist_R_deg"] for r in recs), 1),
            "max_wrist_L_deg": round(max(r["wrist_L_deg"] for r in recs), 1),
            "avg_grip_R_threejs": _to_three(avg_r),
            "avg_grip_L_threejs": _to_three(avg_l),
            "barrel_f0_threejs": _to_three(recs[0]["B_hat"]),
        }

    return created, glide_metrics, twohand_summary


# =============================================================================
# 8. SIX EMBODIED GOOGLE WORKSPACE PRODUCT ICON AI PROFILES
# =============================================================================

HERO_CONFIGS: List[dict] = [
    {
        "id": "ai_gmail",
        "filename": "hero_gmail.glb",
        "name": "Gmail AI",
        "product": "gmail",
        "height_scale": 1.000,
        "chassis_tex_base": "#F7F9FC",
        "chassis_tex_accent": "#EA4335",
        "visor_glow": "#FF5252",
        "visor_core": "#FFF5F5",
        "limb_shell": "#F5F7FA",
        "thigh_shell": "#3C4654",
        "limb_accent": "#EA4335",
        "boot_upper": "#EA4335",
        "boot_sole": "#F8FAFC",
        "emissive": "#FF4B4B",
    },
    {
        "id": "ai_drive",
        "filename": "hero_drive.glb",
        "name": "Drive AI",
        "product": "drive",
        "height_scale": 1.000,
        "chassis_tex_base": "#0F1722",
        "chassis_tex_accent": "#10B981",
        "visor_glow": "#10E5A5",
        "visor_core": "#E6FFF8",
        "limb_shell": "#36404D",
        "thigh_shell": "#28313D",
        "limb_accent": "#34A853",
        "boot_upper": "#252E38",
        "boot_sole": "#ECEFF4",
        "emissive": "#10E5A5",
    },
    {
        "id": "ai_calendar",
        "filename": "hero_calendar.glb",
        "name": "Calendar AI",
        "product": "calendar",
        "height_scale": 1.000,
        "chassis_tex_base": "#F8FAFD",
        "chassis_tex_accent": "#4285F4",
        "visor_glow": "#38BDF8",
        "visor_core": "#EFF8FF",
        "limb_shell": "#F3F6FB",
        "thigh_shell": "#334155",
        "limb_accent": "#4285F4",
        "boot_upper": "#2563EB",
        "boot_sole": "#F8FAFC",
        "emissive": "#38BDF8",
    },
    {
        "id": "ai_chat",
        "filename": "hero_chat.glb",
        "name": "Chat AI",
        "product": "chat",
        "height_scale": 1.000,
        "chassis_tex_base": "#F2FCF6",
        "chassis_tex_accent": "#149456",
        "visor_glow": "#00E676",
        "visor_core": "#ECFFF5",
        "limb_shell": "#303A44",
        "thigh_shell": "#232C35",
        "limb_accent": "#00C853",
        "boot_upper": "#149456",
        "boot_sole": "#F4F8F6",
        "emissive": "#00E676",
    },
    {
        "id": "ai_slides",
        "filename": "hero_slides.glb",
        "name": "Slides AI",
        "product": "slides",
        "height_scale": 1.000,
        "chassis_tex_base": "#F6B400",
        "chassis_tex_accent": "#E09100",
        "visor_glow": "#FBBF24",
        "visor_core": "#FFFDF0",
        "limb_shell": "#343944",
        "thigh_shell": "#272C36",
        "limb_accent": "#FBBC04",
        "boot_upper": "#262B35",
        "boot_sole": "#F6F7FA",
        "emissive": "#FBBF24",
    },
    {
        "id": "ai_docs",
        "filename": "hero_docs.glb",
        "name": "Docs AI",
        "product": "docs",
        "height_scale": 1.000,
        "chassis_tex_base": "#2F78F2",
        "chassis_tex_accent": "#1967D2",
        "visor_glow": "#60A5FA",
        "visor_core": "#EFF7FF",
        "limb_shell": "#F4F7FC",
        "thigh_shell": "#38465A",
        "limb_accent": "#4285F4",
        "boot_upper": "#2B74EE",
        "boot_sole": "#F8FAFC",
        "emissive": "#60A5FA",
    },
]


# =============================================================================
# 9. BUILD & EXPORT ORCHESTRATOR + SELF-AUDIT
# =============================================================================

def inspect_glb(glb_path: Path) -> dict:
    raw = glb_path.read_bytes()
    json_len = struct.unpack("<I", raw[12:16])[0]
    gltf = json.loads(raw[20 : 20 + json_len].decode("utf-8"))
    nodes_list = gltf.get("nodes", [])
    nodes = [n.get("name", "") for n in nodes_list]
    node_map = {n.get("name", ""): n for n in nodes_list}
    anims = [a.get("name", "") for a in gltf.get("animations", [])]
    skins = gltf.get("skins", [])
    images = gltf.get("images", [])
    sock_node = node_map.get("WeaponSocket_R", {})
    sock_trans = tuple(round(v, 4) for v in sock_node.get("translation", (0.0, 0.0, 0.0)))
    return {
        "size_kb": len(raw) / 1024.0,
        "has_socket": "WeaponSocket_R" in nodes,
        "has_hands": ("Hand_L" in nodes and "Hand_R" in nodes),
        "has_spine_chest": ("Spine" in nodes and "Chest" in nodes),
        "socket_local_trans": sock_trans,
        "bones": len(skins[0]["joints"]) if skins else 0,
        "animations": anims,
        "embedded_images": len(images),
    }


def build_and_export_hero(cfg: dict) -> dict:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.render.fps = 24

    hid = cfg["id"]
    visor_img = generate_ai_visor_texture(cfg)
    chassis_img = generate_chassis_detail_texture(cfg)

    mats: Dict[str, bpy.types.Material] = {
        "g_blue":        make_pbr_material(f"{hid}_GBlue",        "#3B82F6", roughness=0.22, metallic=0.08, specular=0.58, coat_weight=0.35),
        "g_dblue":       make_pbr_material(f"{hid}_GDBlue",       "#1967D2", roughness=0.26, metallic=0.14, specular=0.56, coat_weight=0.30),
        "g_red":         make_pbr_material(f"{hid}_GRed",         "#EA4335", roughness=0.22, metallic=0.06, specular=0.58, coat_weight=0.35),
        "g_dred":        make_pbr_material(f"{hid}_GDRed",        "#C5221F", roughness=0.26, metallic=0.12, specular=0.55, coat_weight=0.30),
        "g_yellow":      make_pbr_material(f"{hid}_GYellow",      "#FBBC04", roughness=0.22, metallic=0.18, specular=0.62, coat_weight=0.35),
        "g_dyellow":     make_pbr_material(f"{hid}_GDYellow",     "#D98A00", roughness=0.26, metallic=0.24, specular=0.60, coat_weight=0.30),
        "g_green":       make_pbr_material(f"{hid}_GGreen",       "#22A04E", roughness=0.22, metallic=0.08, specular=0.58, coat_weight=0.35),
        "g_dgreen":      make_pbr_material(f"{hid}_GDGreen",      "#137333", roughness=0.26, metallic=0.14, specular=0.55, coat_weight=0.30),
        "g_mint":        make_pbr_material(f"{hid}_GMint",        "#00C853", roughness=0.22, metallic=0.06, specular=0.58, coat_weight=0.35),
        "ceramic_white": make_pbr_material(f"{hid}_CeramicWhite", "#F7F9FC", roughness=0.19, metallic=0.02, specular=0.60, coat_weight=0.40),
        "anodized_dark": make_pbr_material(f"{hid}_AnodizedDark", "#262D38", roughness=0.34, metallic=0.42, specular=0.55, coat_weight=0.15),
        "titanium":      make_pbr_material(f"{hid}_Titanium",     "#5C6776", roughness=0.26, metallic=0.80, specular=0.65),
        "limb_shell":    make_pbr_material(f"{hid}_LimbShell",    cfg["limb_shell"],  roughness=0.24, metallic=0.08, specular=0.56, coat_weight=0.30),
        "thigh_shell":   make_pbr_material(f"{hid}_ThighShell",   cfg["thigh_shell"], roughness=0.32, metallic=0.32, specular=0.54, coat_weight=0.20),
        "limb_accent":   make_pbr_material(f"{hid}_LimbAccent",   cfg["limb_accent"], roughness=0.25, metallic=0.14, specular=0.58, coat_weight=0.30),
        "boot_upper":    make_pbr_material(f"{hid}_BootUpper",    cfg["boot_upper"],  roughness=0.30, metallic=0.10, specular=0.52, coat_weight=0.22),
        "boot_sole":     make_pbr_material(f"{hid}_BootSole",     cfg["boot_sole"],   roughness=0.48, metallic=0.02, specular=0.40),
        "emissive":      make_pbr_material(f"{hid}_Emissive",     cfg["emissive"],    roughness=0.18, emission_hex=cfg["emissive"], emission_strength=2.4),
        "visor":         make_textured_material(f"{hid}_AIVisor", visor_img, roughness=0.07, metallic=0.05, specular=0.90, emission_strength=2.0, coat_weight=0.65),
        "chassis_tex":   make_textured_material(
            f"{hid}_ChassisDetail",
            chassis_img,
            roughness=0.18 if cfg["product"] != "drive" else 0.12,
            metallic=0.14 if cfg["product"] == "slides" else 0.04,
            specular=0.62,
            emission_strength=1.2 if cfg["product"] == "drive" else 0.0,
            coat_weight=0.38,
        ),
    }

    parts: List[bpy.types.Object] = []
    icon_objs, sh_x, sh_z = build_icon_chassis(cfg, mats)
    parts.extend(icon_objs)

    icon_ys = [v.co.y for o in icon_objs for v in o.data.vertices]
    chassis_y_min, chassis_y_max = min(icon_ys), max(icon_ys)

    arm_objs, arm_joints = build_ai_arms_and_hands(cfg, sh_x, sh_z, mats)
    parts.extend(arm_objs)

    leg_objs, leg_joints = build_ai_pelvis_legs_and_boots(cfg, mats)
    parts.extend(leg_objs)

    joints = {**arm_joints, **leg_joints}
    arm_obj, sock_obj = build_armature_and_socket(cfg, joints)
    hero_mesh_obj = join_and_skin_hero(cfg, parts, arm_obj, joints)

    mesh_data = hero_mesh_obj.data
    mesh_data.calc_loop_triangles()
    tri_count = len(mesh_data.loop_triangles)
    zs = [v.co.z for v in mesh_data.vertices]
    min_z, max_z = min(zs), max(zs)
    if abs(min_z) > 1e-4:
        for v in mesh_data.vertices:
            v.co.z -= min_z
        mesh_data.update()
        min_z, max_z = 0.0, max_z - min_z

    _, glide_metrics, twohand_metrics = build_12_animations(
        arm_obj, cfg["height_scale"], sock_obj, product=cfg["product"]
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / cfg["filename"]

    bpy.ops.object.select_all(action="DESELECT")
    arm_obj.select_set(True)
    hero_mesh_obj.select_set(True)
    sock_obj.select_set(True)
    bpy.context.view_layer.objects.active = arm_obj

    bpy.ops.export_scene.gltf(
        filepath=str(out_path),
        export_format="GLB",
        use_selection=True,
        export_yup=True,
        export_apply=False,
        export_materials="EXPORT",
        export_image_format="AUTO",
        export_animations=True,
        export_animation_mode="NLA_TRACKS",
        export_bake_animation=True,
        export_rest_position_armature=True,
        export_optimize_animation_size=True,
        export_draco_mesh_compression_enable=False,
    )

    glb_info = inspect_glb(out_path)
    bvh_audit = audit_lobby_showcase_bvh(
        cfg["product"], arm_obj, hero_mesh_obj, sock_obj, cfg["height_scale"]
    )
    missing_anims = [a for a in EXPECTED_ANIMATIONS if a not in glb_info["animations"]]
    assert not missing_anims, f"{cfg['filename']} missing animations: {missing_anims}"
    assert len(glb_info["animations"]) == 13, f"{cfg['filename']} expected 13 animations, got {len(glb_info['animations'])}"
    assert glb_info["bones"] == 18, f"{cfg['filename']} expected 18 bones, got {glb_info['bones']}"
    assert glb_info["has_socket"], f"{cfg['filename']} missing WeaponSocket_R!"
    assert glb_info["has_hands"], f"{cfg['filename']} missing Hand_L/Hand_R!"
    assert glb_info["has_spine_chest"], f"{cfg['filename']} missing Spine/Chest!"
    assert glb_info["embedded_images"] >= 2, f"{cfg['filename']} expected >=2 embedded images, got {glb_info['embedded_images']}"
    assert glide_metrics["max_drift_mm"] <= 0.05, f"{cfg['filename']} Glide drift {glide_metrics['max_drift_mm']}mm exceeds 0.05mm!"
    assert max(abs(chassis_y_min), abs(chassis_y_max)) <= 0.135, f"{cfg['filename']} chassis Y depth [{chassis_y_min:.3f}, {chassis_y_max:.3f}] exceeds +/-0.135m!"
    assert 3500 <= tri_count <= 6500, f"{cfg['filename']} tri count {tri_count} outside [3500, 6500]!"
    assert bvh_audit["max_icon_overlaps"] == 0, (
        f"{cfg['filename']} LobbyShowcase BVHTree clip audit FAILED: {bvh_audit['max_icon_overlaps']} icon overlaps "
        f"(worst frame={bvh_audit['worst_frame']}, source={bvh_audit['weapon_source']})!"
    )
    if LOBBY_SHOWCASE_META[cfg["product"]]["armed"]:
        ls_2h = twohand_metrics["LobbyShowcase"]
        assert ls_2h["max_palm_err_R_mm"] < 0.5 and ls_2h["max_palm_err_L_mm"] < 0.5, (
            f"{cfg['filename']} LobbyShowcase palm error too high: R={ls_2h['max_palm_err_R_mm']}mm L={ls_2h['max_palm_err_L_mm']}mm"
        )
        assert ls_2h["max_sep_err_mm"] < 0.5 and ls_2h["max_sock_err_mm"] < 0.5, (
            f"{cfg['filename']} LobbyShowcase grip/socket error too high: sep={ls_2h['max_sep_err_mm']}mm sock={ls_2h['max_sock_err_mm']}mm"
        )

    return {
        "filename": cfg["filename"],
        "name": cfg["name"],
        "product": cfg["product"],
        "scale_h": cfg["height_scale"],
        "tris": tri_count,
        "min_z": round(min_z, 4),
        "height_m": round(max_z - min_z, 3),
        "chassis_y": (round(chassis_y_min, 3), round(chassis_y_max, 3)),
        "glide": glide_metrics,
        "twohand": twohand_metrics,
        "lobby_bvh": bvh_audit,
        **glb_info,
    }


def _load_weapon_local_tris(meta: dict) -> Tuple[List[Vector], List[Tuple[int, int, int]], str]:
    """Load exact weapon mesh triangles in Blender local weapon coords (falling back to dense reference box)."""
    glb_name = meta.get("weapon_glb")
    glb_path = (WEAPONS_DIR / glb_name) if glb_name else None
    if glb_path is not None and glb_path.exists():
        before = set(bpy.data.objects)
        try:
            bpy.ops.import_scene.gltf(filepath=str(glb_path))
            imported = [
                o for o in bpy.data.objects
                if o not in before and "glTF_not_exported" not in {c.name for c in o.users_collection}
            ]
            verts: List[Vector] = []
            tris: List[Tuple[int, int, int]] = []
            depsgraph = bpy.context.evaluated_depsgraph_get()
            for obj in imported:
                if obj.type != "MESH":
                    continue
                ev = obj.evaluated_get(depsgraph)
                me = ev.to_mesh()
                try:
                    me.calc_loop_triangles()
                    base = len(verts)
                    mw = ev.matrix_world
                    verts.extend(mw @ v.co for v in me.vertices)
                    tris.extend((base + lt.vertices[0], base + lt.vertices[1], base + lt.vertices[2]) for lt in me.loop_triangles)
                finally:
                    ev.to_mesh_clear()
            for obj in list(bpy.data.objects):
                if obj not in before:
                    bpy.data.objects.remove(obj, do_unlink=True)
            if verts and tris:
                return verts, tris, glb_name
        except Exception:
            for obj in list(bpy.data.objects):
                if obj not in before:
                    bpy.data.objects.remove(obj, do_unlink=True)

    # Fallback reference bounding box
    (x0, x1), (y0, y1), (z0, z1) = meta["fallback_bbox"]
    verts = [
        Vector((x0, y0, z0)), Vector((x1, y0, z0)), Vector((x1, y1, z0)), Vector((x0, y1, z0)),
        Vector((x0, y0, z1)), Vector((x1, y0, z1)), Vector((x1, y1, z1)), Vector((x0, y1, z1)),
    ]
    tris = [
        (0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7),
        (0, 1, 5), (0, 5, 4), (2, 3, 7), (2, 7, 6),
        (1, 2, 6), (1, 6, 5), (3, 0, 4), (3, 4, 7),
    ]
    return verts, tris, "fallback_bbox"


def audit_lobby_showcase_bvh(
    product: str,
    arm_obj: bpy.types.Object,
    hero_mesh_obj: bpy.types.Object,
    sock_obj: bpy.types.Object,
    scale_h: float,
) -> dict:
    """
    3D BVHTree overlap & grounding audit across EVERY keyframe of `LobbyShowcase`:
      - Armed heroes (gmail/drive/chat/slides/docs): aligns the hero's signature weapon 1:1 with
        Three.js `alignWeaponTwoHanded` (+ `WEAPON_GRIP_TUNE`) and checks 3D BVHTree overlaps against
        the hero's deformed 3D product icon chassis AND full body excluding gripping hands/forearms.
      - Unarmed hero (calendar): checks 3D BVHTree self-clipping between forearms/hands and the 3D icon chassis.
    """
    meta = LOBBY_SHOWCASE_META[product]
    act = bpy.data.actions.get("LobbyShowcase")
    assert act is not None, f"{product}: missing LobbyShowcase action for BVHTree audit!"

    ad = arm_obj.animation_data
    ad.use_nla = False
    for tr in ad.nla_tracks:
        tr.mute = True
    ad.action = act
    if hasattr(ad, "action_slot") and hasattr(act, "slots") and len(act.slots) > 0:
        for slot in act.slots:
            if slot.target_id_type == "OBJECT":
                try:
                    ad.action_slot = slot
                    break
                except Exception:
                    pass

    # Pre-classify hero mesh vertices by vertex group membership
    vg_idx_to_name = {vg.index: vg.name for vg in hero_mesh_obj.vertex_groups}
    icon_bones = {"Chest", "Neck", "Head"}
    hand_forearm_bones = {"Hand_L", "Hand_R", "LowerArm_L", "LowerArm_R"}

    mesh_base = hero_mesh_obj.data
    vert_is_icon: List[bool] = []
    vert_is_hand_fa: List[bool] = []
    for v in mesh_base.vertices:
        is_ic = False
        is_hf = False
        for g in v.groups:
            bname = vg_idx_to_name.get(g.group, "")
            if g.weight > 0.10:
                if bname in icon_bones:
                    is_ic = True
                if bname in hand_forearm_bones:
                    is_hf = True
        vert_is_icon.append(is_ic)
        vert_is_hand_fa.append(is_hf)

    wpn_verts_local: List[Vector] = []
    wpn_tris: List[Tuple[int, int, int]] = []
    wpn_source = "unarmed_self_check"
    if meta["armed"]:
        wpn_verts_local, wpn_tris, wpn_source = _load_weapon_local_tris(meta)

    alpha = math.atan2(RIFLE_FOREGRIP_UP, RIFLE_FOREGRIP_DIST)
    cos_a, sin_a = math.cos(alpha), math.sin(alpha)
    grip_tune = meta["grip_tune_blender"]

    max_icon_ov = 0
    max_body_ov = 0
    worst_frame = LOBBY_SHOWCASE_FRAMES[0]
    min_foot_z = 999.0
    max_foot_z = -999.0

    for f in LOBBY_SHOWCASE_FRAMES:
        bpy.context.scene.frame_set(f)
        bpy.context.view_layer.update()
        depsgraph = bpy.context.evaluated_depsgraph_get()

        ev_obj = hero_mesh_obj.evaluated_get(depsgraph)
        ev_mesh = ev_obj.to_mesh()
        try:
            ev_mesh.calc_loop_triangles()
            mw = ev_obj.matrix_world
            hero_world_verts = [mw @ v.co for v in ev_mesh.vertices]
            frame_min_z = min(p.z for p in hero_world_verts)
            min_foot_z = min(min_foot_z, frame_min_z)
            max_foot_z = max(max_foot_z, frame_min_z)

            icon_tris = [
                (lt.vertices[0], lt.vertices[1], lt.vertices[2])
                for lt in ev_mesh.loop_triangles
                if any(vert_is_icon[vi] for vi in lt.vertices)
            ]
            body_excl_hf_tris = [
                (lt.vertices[0], lt.vertices[1], lt.vertices[2])
                for lt in ev_mesh.loop_triangles
                if not any(vert_is_hand_fa[vi] for vi in lt.vertices)
            ]

            bvh_icon = BVHTree.FromPolygons(hero_world_verts, icon_tris)

            if meta["armed"]:
                p_grip_R = sock_obj.matrix_world.translation.copy()
                pb_hand_L = arm_obj.pose.bones["Hand_L"]
                p_grip_L = (arm_obj.matrix_world @ pb_hand_L.matrix) @ (LEFT_PALM_LOCAL * scale_h)
                g_hat = (p_grip_L - p_grip_R).normalized()
                ref_up = Vector((0.0, 0.0, 1.0))
                r_hat = g_hat.cross(ref_up).normalized()
                g_up = r_hat.cross(g_hat).normalized()
                b_hat = (g_hat * cos_a - g_up * sin_a).normalized()
                u_hat = (g_hat * sin_a + g_up * cos_a).normalized()
                R_w = Matrix((r_hat, b_hat, u_hat)).transposed()

                # Test BOTH raw grip (0,0,0) and Three.js WEAPON_GRIP_TUNE offset!
                frame_icon_ov = 0
                frame_body_ov = 0
                bvh_body = BVHTree.FromPolygons(hero_world_verts, body_excl_hf_tris)
                offsets_to_test = [Vector((0.0, 0.0, 0.0))]
                if grip_tune.length > 1e-6:
                    offsets_to_test.append(grip_tune)
                for off in offsets_to_test:
                    p_w = p_grip_R + (R_w @ off)
                    wpn_world_verts = [p_w + (R_w @ v) for v in wpn_verts_local]
                    bvh_wpn = BVHTree.FromPolygons(wpn_world_verts, wpn_tris)
                    ic_ov = len(bvh_icon.overlap(bvh_wpn))
                    bd_ov = len(bvh_body.overlap(bvh_wpn))
                    frame_icon_ov = max(frame_icon_ov, ic_ov)
                    frame_body_ov = max(frame_body_ov, bd_ov)
            else:
                hf_tris = [
                    (lt.vertices[0], lt.vertices[1], lt.vertices[2])
                    for lt in ev_mesh.loop_triangles
                    if any(vert_is_hand_fa[vi] for vi in lt.vertices)
                ]
                bvh_hf = BVHTree.FromPolygons(hero_world_verts, hf_tris)
                frame_icon_ov = len(bvh_icon.overlap(bvh_hf))
                frame_body_ov = frame_icon_ov

            if frame_icon_ov > max_icon_ov or (frame_icon_ov == max_icon_ov and frame_body_ov > max_body_ov):
                worst_frame = f
            max_icon_ov = max(max_icon_ov, frame_icon_ov)
            max_body_ov = max(max_body_ov, frame_body_ov)
        finally:
            ev_obj.to_mesh_clear()

    return {
        "title": meta["title"],
        "armed": meta["armed"],
        "weapon_source": wpn_source,
        "frames_checked": len(LOBBY_SHOWCASE_FRAMES),
        "max_icon_overlaps": max_icon_ov,
        "max_body_overlaps": max_body_ov,
        "worst_frame": worst_frame,
        "min_foot_z_m": round(min_foot_z, 3),
        "max_foot_z_m": round(max_foot_z, 3),
    }


def main() -> None:
    print("=" * 102)
    print("Workspace Royale — Building 6 High-Fidelity Embodied Google Workspace Product Icon AIs (13 NLA Clips)")
    print("=" * 102)
    results = []
    for cfg in HERO_CONFIGS:
        res = build_and_export_hero(cfg)
        results.append(res)
        g = res["glide"]
        bvh = res["lobby_bvh"]
        print(
            f"  [OK] {res['filename']:<18} | {res['name']:<14} | "
            f"{res['tris']:>5} tris | {res['size_kb']:>6.1f} KB | "
            f"H={res['height_m']:.2f}m (minZ={res['min_z']:.3f}) Y={res['chassis_y']} | "
            f"imgs={res['embedded_images']} bones={res['bones']} sock={res['has_socket']}"
        )
        print(f"       anims({len(res['animations'])}): {res['animations']}")
        print(
            f"       LobbyShowcase[{bvh['title']:<19}] src={bvh['weapon_source']:<22} "
            f"BVH iconOv={bvh['max_icon_overlaps']} bodyOv={bvh['max_body_overlaps']} "
            f"({bvh['frames_checked']}f) footZ=[{bvh['min_foot_z_m']:+.3f}, {bvh['max_foot_z_m']:+.3f}]m"
        )
        print(
            f"       WeaponSocket_R in Hand_R local={res['socket_local_trans']} | "
            f"Hand_L palm local={(round(LEFT_PALM_LOCAL.x * res['scale_h'], 4), round(LEFT_PALM_LOCAL.y * res['scale_h'], 4), round(LEFT_PALM_LOCAL.z * res['scale_h'], 4))}"
        )
        print(
            f"       Glide Three.js Y-up: Hand_L={g['hand_L_threejs']} Hand_R={g['hand_R_threejs']} "
            f"PalmMid={g['palm_mid_threejs']} Delta={g['palm_offset_from_hand_mid_threejs']} "
            f"halfSpan={g['half_span_m']:.3f}m maxDrift={g['max_drift_mm']:.2f}mm"
        )
        for cname, tm in res["twohand"].items():
            print(
                f"       2H[{cname:<16}] sep={tm['sep_m']:.4f}m (err={tm['max_sep_err_mm']:.2f}mm, "
                f"sockErr={tm['max_sock_err_mm']:.2f}mm) reach(R/L)={tm['max_reach_R_pct']:4.1f}%/{tm['max_reach_L_pct']:4.1f}% "
                f"wristBend(R/L)={tm['max_wrist_R_deg']:4.1f}/{tm['max_wrist_L_deg']:4.1f}deg "
                f"barrel3js={tm['barrel_f0_threejs']}"
            )

    total_kb = sum(r["size_kb"] for r in results)
    total_mb = total_kb / 1024.0
    print("-" * 102)
    print(f"Total 6 Workspace Icon AI heroes exported to {OUT_DIR}: {total_mb:.2f} MB (cap <= 5.00 MB)")
    print("=" * 102)
    assert total_mb <= 5.00, f"Character folder {total_mb:.2f} MB exceeds 5.00 MB cap!"


if __name__ == "__main__":
    main()

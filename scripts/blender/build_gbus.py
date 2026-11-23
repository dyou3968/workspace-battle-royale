#!/usr/bin/env python3
"""
Workspace Royale — Iconic Google GBus with Wings (Battle Bus) Blender 5.3.0 Builder
===================================================================================
Generates:
  - public/assets/map/prop_google_gbus.glb (zero Draco, < 650 KB)
  - 2-angle studio EEVEE QA preview PNG (front-3/4 + rear-3/4)

Coordinate System (export_yup=True):
  - Blender +Y -> Three.js -Z (Forward / Nose)
  - Blender +X -> Three.js +X (Right / Starboard)
  - Blender +Z -> Three.js +Y (Up)

Nodes exported in GLB:
  - GBus_Body       : Coach fuselage, tinted windows, Google 4-color ribbon, dual-sided GBUS signage,
                      tucked-up landing wheels, headlights, tail lights, roof beacon dome
  - GBus_Wings      : High-mounted swept aero wings (13.6m span), upturned Google winglets,
                      twin under-wing nacelles w/ glowing cyan jet thruster rings, V-tail stabilizer
  - GBus_RotorL     : Left spinning 4-blade prop pivoted at exact hub (-3.3, +1.8, +0.4) Blender
  - GBus_RotorR     : Right spinning 4-blade prop pivoted at exact hub (+3.3, +1.8, +0.4) Blender
  - GBus_ThrusterL  : Empty anchor at left rear jet exhaust nozzle (-3.3, -1.65, +0.4) Blender
  - GBus_ThrusterR  : Empty anchor at right rear jet exhaust nozzle (+3.3, -1.65, +0.4) Blender

Usage:
  blender --background --python scripts/blender/build_gbus.py
"""

import json
import math
import os
import struct
import sys
import tempfile
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Euler, Matrix, Vector

# ---------------------------------------------------------------------------
# Paths & Constants
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
OUT_GLB = PROJECT_ROOT / "public" / "assets" / "map" / "prop_google_gbus.glb"
PREVIEW_PNG = Path(
    "/Users/davidyou/.gemini/antigravity/brain/"
    "a9682dfa-7d5f-428c-afd4-e62e35b1964e/previews/qa_google_gbus.png"
)

# Exact Rotor & Thruster Anchor Coordinates in Blender Space (+Y Forward, +X Right, +Z Up)
ROTOR_L_POS = Vector((-3.85, 1.80, 0.42))
ROTOR_R_POS = Vector((3.85, 1.80, 0.42))
THRUSTER_L_POS = Vector((-3.85, -1.55, 0.42))
THRUSTER_R_POS = Vector((3.85, -1.55, 0.42))

# Brand & PBR Palette (sRGB hex)
COL_PEARL_WHITE = "#F8FAFD"
COL_LIGHT_TRIM = "#E2E8F0"
COL_WINDOW_TINT = "#1E293B"
COL_WINDOW_MULLION = "#0F172A"
COL_DARK_SKIRT = "#242B36"
COL_RUBBER = "#151921"
COL_ALLOY_SILVER = "#B8C4D4"
COL_GUNMETAL = "#2E3744"
COL_TITANIUM = "#7B8798"

COL_GOOGLE_BLUE = "#4285F4"
COL_GOOGLE_RED = "#EA4335"
COL_GOOGLE_YELLOW = "#FBBC04"
COL_GOOGLE_GREEN = "#34A853"

COL_HEADLIGHT = "#FEF08A"
COL_TAILLIGHT = "#EA4335"
COL_THRUSTER_CYAN = "#38BDF8"
COL_BEACON_BLUE = "#38BDF8"


# ---------------------------------------------------------------------------
# Color & Material Helpers (Blender 5.3.0 Principled BSDF)
# ---------------------------------------------------------------------------

def srgb_to_linear(c: float) -> float:
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def hex_to_srgb(hex_str: str) -> tuple[float, float, float]:
    h = hex_str.lstrip("#")
    return (
        int(h[0:2], 16) / 255.0,
        int(h[2:4], 16) / 255.0,
        int(h[4:6], 16) / 255.0,
    )


def hex_to_linear(hex_str: str) -> tuple[float, float, float, float]:
    r, g, b = hex_to_srgb(hex_str)
    return (srgb_to_linear(r), srgb_to_linear(g), srgb_to_linear(b), 1.0)


def clear_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for mesh in list(bpy.data.meshes):
        bpy.data.meshes.remove(mesh, do_unlink=True)
    for mat in list(bpy.data.materials):
        bpy.data.materials.remove(mat, do_unlink=True)
    for img in list(bpy.data.images):
        bpy.data.images.remove(img, do_unlink=True)


def make_pbr_mat(
    name: str,
    hex_color: str,
    metallic: float = 0.0,
    roughness: float = 0.45,
    coat: float = 0.0,
    coat_roughness: float = 0.12,
    emission_hex: str | None = None,
    emission_strength: float = 0.0,
) -> bpy.types.Material:
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    if bsdf is None:
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")

    bsdf.inputs["Base Color"].default_value = hex_to_linear(hex_color)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    if "Coat Weight" in bsdf.inputs:
        bsdf.inputs["Coat Weight"].default_value = coat
        bsdf.inputs["Coat Roughness"].default_value = coat_roughness
    if emission_hex is not None and emission_strength > 0.0:
        bsdf.inputs["Emission Color"].default_value = hex_to_linear(emission_hex)
        bsdf.inputs["Emission Strength"].default_value = emission_strength
    return mat


# ---------------------------------------------------------------------------
# Procedural 512x128 GBUS Signage Texture (Supersampled Anti-Aliased, Packed)
# ---------------------------------------------------------------------------

def _dist_segment(px: np.ndarray, py: np.ndarray, ax: float, ay: float, bx: float, by: float) -> np.ndarray:
    vx, vy = bx - ax, by - ay
    wx, wy = px - ax, py - ay
    l2 = vx * vx + vy * vy
    t = np.clip((wx * vx + wy * vy) / max(l2, 1e-8), 0.0, 1.0)
    dx = px - (ax + t * vx)
    dy = py - (ay + t * vy)
    return np.hypot(dx, dy)


def _draw_arc_mask(
    px: np.ndarray,
    py: np.ndarray,
    cx: float,
    cy: float,
    rx: float,
    ry: float,
    thickness: float,
    ang_start: float,
    ang_end: float,
) -> np.ndarray:
    """Anti-aliased elliptical arc mask (angles in radians, CCW from +X)."""
    dx = (px - cx) / rx
    dy = (py - cy) / ry
    r_norm = np.hypot(dx, dy)
    # Approximate Euclidean distance to ellipse boundary
    r_avg = 0.5 * (rx + ry)
    dist_ring = np.abs(r_norm - 1.0) * r_avg - thickness * 0.5
    ang = np.arctan2(dy, dx)
    # Normalize angle relative to ang_start into [0, 2*pi)
    span = (ang_end - ang_start) % (2.0 * math.pi)
    if span == 0.0:
        span = 2.0 * math.pi
    rel = (ang - ang_start) % (2.0 * math.pi)
    in_ang = rel <= span
    # Smooth endcaps
    p1x, p1y = cx + rx * math.cos(ang_start), cy + ry * math.sin(ang_start)
    p2x, p2y = cx + rx * math.cos(ang_end), cy + ry * math.sin(ang_end)
    d_cap = np.minimum(np.hypot(px - p1x, py - p1y), np.hypot(px - p2x, py - p2y)) - thickness * 0.5
    dist = np.where(in_ang, dist_ring, d_cap)
    return np.clip(0.5 - dist * 0.85, 0.0, 1.0)


def _blend(canvas: np.ndarray, mask: np.ndarray, rgb: tuple[float, float, float]) -> None:
    m = mask[..., None]
    col = np.array(rgb, dtype=np.float32)[None, None, :]
    canvas[:] = canvas * (1.0 - m) + col * m


def build_gbus_signage_material() -> bpy.types.Material:
    """
    Create a crisp 512x128 packed RGBA texture with:
      - Pearl-white pill placard background with subtle border
      - Iconic 4-color circular Google 'G' badge on the left
      - Crisp bold geometric 'GBUS' lettering on the right
    Rendered at 2x supersampling (1024x256) and downsampled for razor-sharp AA.
    """
    w_out, h_out = 512, 128
    scale = 2
    w, h = w_out * scale, h_out * scale

    # Coordinate grid: x in [0, w), y in [0, h) with y=0 at BOTTOM (Blender image convention)
    xs = np.arange(w, dtype=np.float32) + 0.5
    ys = np.arange(h, dtype=np.float32) + 0.5
    px, py = np.meshgrid(xs, ys)

    bg_rgb = hex_to_srgb(COL_PEARL_WHITE)
    canvas = np.zeros((h, w, 3), dtype=np.float32)
    canvas[:, :, 0] = bg_rgb[0]
    canvas[:, :, 1] = bg_rgb[1]
    canvas[:, :, 2] = bg_rgb[2]

    # Subtle outer rounded frame accent
    border_rgb = hex_to_srgb("#CBD5E1")
    top_bot = np.minimum(py, h - py)
    left_right = np.minimum(px, w - px)
    edge_d = np.minimum(top_bot, left_right)
    border_mask = np.clip((5.0 - edge_d) * 0.6, 0.0, 1.0)
    _blend(canvas, border_mask, border_rgb)

    # Bottom thin 4-color Google micro-accent bar inside placard
    bar_y_mask = np.clip(1.0 - np.abs(py - 16.0) / 5.0, 0.0, 1.0)
    bar_cols = [
        (0.05, 0.275, hex_to_srgb(COL_GOOGLE_BLUE)),
        (0.275, 0.50, hex_to_srgb(COL_GOOGLE_RED)),
        (0.50, 0.725, hex_to_srgb(COL_GOOGLE_YELLOW)),
        (0.725, 0.95, hex_to_srgb(COL_GOOGLE_GREEN)),
    ]
    for x0_f, x1_f, col in bar_cols:
        xm = np.clip(np.minimum(px - x0_f * w, x1_f * w - px) * 0.7, 0.0, 1.0)
        _blend(canvas, bar_y_mask * xm, col)

    # --- Iconic 4-Color Circular Google 'G' Badge on the Left ---
    gcx, gcy = 152.0, 134.0
    g_outer_r = 82.0
    g_ring_r = 56.0
    g_thick = 26.0

    # Subtle crisp white circular medallion with light shadow ring
    dist_c = np.hypot(px - gcx, py - gcy)
    shadow_ring = np.clip(1.0 - np.abs(dist_c - (g_outer_r + 2.0)) / 4.0, 0.0, 1.0) * 0.35
    _blend(canvas, shadow_ring, hex_to_srgb("#94A3B8"))
    medallion = np.clip(0.5 - (dist_c - g_outer_r) * 0.85, 0.0, 1.0)
    _blend(canvas, medallion, (1.0, 1.0, 1.0))

    # 4-color G arcs (CCW from +X, remember +Y is UP!)
    # Red: top arc (42 deg -> 148 deg)
    m_red = _draw_arc_mask(px, py, gcx, gcy, g_ring_r, g_ring_r, g_thick,
                           math.radians(40), math.radians(150))
    # Yellow: left arc (148 deg -> 218 deg)
    m_yel = _draw_arc_mask(px, py, gcx, gcy, g_ring_r, g_ring_r, g_thick,
                           math.radians(148), math.radians(218))
    # Green: bottom arc (216 deg -> 318 deg)
    m_grn = _draw_arc_mask(px, py, gcx, gcy, g_ring_r, g_ring_r, g_thick,
                           math.radians(216), math.radians(318))
    # Blue: right lower arc (316 deg -> 364 deg / 4 deg) + horizontal crossbar
    m_blu_arc = _draw_arc_mask(px, py, gcx, gcy, g_ring_r, g_ring_r, g_thick,
                               math.radians(316), math.radians(365))
    d_bar = _dist_segment(px, py, gcx + 2.0, gcy, gcx + g_ring_r + 2.0, gcy) - g_thick * 0.46
    m_blu_bar = np.clip(0.5 - d_bar * 0.85, 0.0, 1.0)
    m_blu = np.maximum(m_blu_arc, m_blu_bar)

    _blend(canvas, m_red, hex_to_srgb(COL_GOOGLE_RED))
    _blend(canvas, m_yel, hex_to_srgb(COL_GOOGLE_YELLOW))
    _blend(canvas, m_grn, hex_to_srgb(COL_GOOGLE_GREEN))
    _blend(canvas, m_blu, hex_to_srgb(COL_GOOGLE_BLUE))

    # --- Crisp Geometric Sans-Serif 'GBUS' Lettering ---
    text_rgb = hex_to_srgb("#1E293B")
    stroke = 23.0
    y_mid = 134.0
    y_top = 200.0
    y_bot = 68.0
    half_h = (y_top - y_bot) * 0.5  # 66.0

    letter_mask = np.zeros((h, w), dtype=np.float32)

    def add_seg(ax: float, ay: float, bx: float, by: float, sw: float = stroke) -> None:
        nonlocal letter_mask
        d = _dist_segment(px, py, ax, ay, bx, by) - sw * 0.5
        letter_mask = np.maximum(letter_mask, np.clip(0.5 - d * 0.85, 0.0, 1.0))

    def add_arc(cx: float, cy: float, rx: float, ry: float, a0: float, a1: float, sw: float = stroke) -> None:
        nonlocal letter_mask
        m = _draw_arc_mask(px, py, cx, cy, rx, ry, sw, a0, a1)
        letter_mask = np.maximum(letter_mask, m)

    # Letter 'G' centered around x = 355
    gx = 355.0
    add_arc(gx, y_mid, 56.0, 62.0, math.radians(38), math.radians(352), stroke)
    add_seg(gx + 6.0, y_mid - 2.0, gx + 56.0, y_mid - 2.0, stroke * 0.92)
    add_seg(gx + 55.0, y_mid - 2.0, gx + 55.0, y_bot + 14.0, stroke * 0.92)

    # Letter 'B' starting at x = 472
    bx0 = 472.0
    add_seg(bx0, y_bot + 4.0, bx0, y_top - 4.0, stroke)
    add_seg(bx0, y_top - 4.0, bx0 + 50.0, y_top - 4.0, stroke)
    add_seg(bx0, y_mid + 3.0, bx0 + 52.0, y_mid + 3.0, stroke * 0.92)
    add_seg(bx0, y_bot + 4.0, bx0 + 54.0, y_bot + 4.0, stroke)
    # Upper bowl of B
    add_arc(bx0 + 50.0, (y_top - 4.0 + y_mid + 3.0) * 0.5, 32.0, (y_top - 4.0 - (y_mid + 3.0)) * 0.5,
            math.radians(-90), math.radians(90), stroke)
    # Lower bowl of B
    add_arc(bx0 + 54.0, (y_mid + 3.0 + y_bot + 4.0) * 0.5, 36.0, (y_mid + 3.0 - (y_bot + 4.0)) * 0.5,
            math.radians(-90), math.radians(90), stroke)

    # Letter 'U' centered at x = 678
    ux = 678.0
    u_hw = 48.0
    u_arc_cy = y_bot + 48.0
    add_seg(ux - u_hw, y_top - 4.0, ux - u_hw, u_arc_cy, stroke)
    add_seg(ux + u_hw, y_top - 4.0, ux + u_hw, u_arc_cy, stroke)
    add_arc(ux, u_arc_cy, u_hw, 45.0, math.radians(180), math.radians(360), stroke)

    # Letter 'S' centered at x = 842
    sx = 842.0
    # Upper C-curve of S (from 20 deg around top to 255 deg)
    add_arc(sx, y_mid + 31.0, 44.0, 31.0, math.radians(18), math.radians(265), stroke)
    # Lower backwards-C curve of S (from -162 deg around bottom to 85 deg)
    add_arc(sx, y_mid - 31.0, 47.0, 32.0, math.radians(200), math.radians(445), stroke)
    # Smooth diagonal connector in center of S
    add_seg(sx - 22.0, y_mid + 6.0, sx + 24.0, y_mid - 5.0, stroke * 0.94)

    _blend(canvas, letter_mask, text_rgb)

    # Box-filter downsample 2x -> 512x128
    canvas_ds = canvas.reshape(h_out, scale, w_out, scale, 3).mean(axis=(1, 3))
    rgba = np.ones((h_out, w_out, 4), dtype=np.float32)
    rgba[:, :, :3] = np.clip(canvas_ds, 0.0, 1.0)

    img = bpy.data.images.new(name="GBus_Signage_Tex", width=w_out, height=h_out, alpha=True)
    img.colorspace_settings.name = "sRGB"
    img.pixels.foreach_set(rgba.ravel())
    img.pack()

    mat = bpy.data.materials.new(name="Mat_GBus_Signage")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    tex_node = nt.nodes.new("ShaderNodeTexImage")
    tex_node.image = img
    tex_node.extension = "CLIP"
    nt.links.new(tex_node.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Metallic"].default_value = 0.0
    bsdf.inputs["Roughness"].default_value = 0.26
    if "Coat Weight" in bsdf.inputs:
        bsdf.inputs["Coat Weight"].default_value = 0.30
        bsdf.inputs["Coat Roughness"].default_value = 0.12
    return mat


# ---------------------------------------------------------------------------
# BMesh Geometry Primitives & Helpers
# ---------------------------------------------------------------------------

def assign_mat_to_faces(faces, mat_idx: int) -> None:
    for f in faces:
        f.material_index = mat_idx
        f.smooth = True


def add_box(
    bm: bmesh.types.BMesh,
    center: tuple[float, float, float],
    size: tuple[float, float, float],
    mat_idx: int,
    rot_euler: tuple[float, float, float] = (0.0, 0.0, 0.0),
    bevel: float = 0.0,
    bevel_segments: int = 1,
    smooth: bool = True,
) -> list[bmesh.types.BMFace]:
    mat = (
        Matrix.Translation(Vector(center))
        @ Euler(rot_euler, "XYZ").to_matrix().to_4x4()
        @ Matrix.Diagonal((size[0], size[1], size[2], 1.0))
    )
    ret = bmesh.ops.create_cube(bm, size=1.0, matrix=mat)
    verts = ret["verts"]
    vset = set(verts)
    edges = [e for e in bm.edges if e.verts[0] in vset and e.verts[1] in vset]
    faces = [f for f in bm.faces if all(v in vset for v in f.verts)]
    # Assign material BEFORE bevel so rebuilt cap faces inherit mat_idx!
    for f in faces:
        f.material_index = mat_idx
        f.smooth = smooth
    if bevel > 0.0:
        res = bmesh.ops.bevel(
            bm,
            geom=edges,
            offset=bevel,
            segments=bevel_segments,
            affect="EDGES",
            clamp_overlap=True,
        )
        for f in res["faces"]:
            if f.is_valid:
                f.material_index = mat_idx
                f.smooth = smooth
        faces = [f for f in faces if f.is_valid] + [f for f in res["faces"] if f.is_valid]
    return faces


def add_cylinder(
    bm: bmesh.types.BMesh,
    center: tuple[float, float, float],
    radius1: float,
    radius2: float,
    depth: float,
    segments: int,
    mat_idx: int,
    rot_euler: tuple[float, float, float] = (0.0, 0.0, 0.0),
    cap_ends: bool = True,
    smooth: bool = True,
) -> list[bmesh.types.BMFace]:
    mat = Matrix.Translation(Vector(center)) @ Euler(rot_euler, "XYZ").to_matrix().to_4x4()
    ret = bmesh.ops.create_cone(
        bm,
        cap_ends=cap_ends,
        cap_tris=False,
        segments=segments,
        radius1=radius1,
        radius2=radius2,
        depth=depth,
        matrix=mat,
    )
    vset = set(ret["verts"])
    faces = [f for f in bm.faces if all(v in vset for v in f.verts)]
    for f in faces:
        f.material_index = mat_idx
        f.smooth = smooth
    return faces


def add_lofted_tube(
    bm: bmesh.types.BMesh,
    rings: list[list[tuple[float, float, float]]],
    mat_idx: int | list[int],
    cap_start: bool = True,
    cap_end: bool = True,
    smooth: bool = True,
) -> list[bmesh.types.BMFace]:
    """Loft a closed loop of rings (each ring has same vertex count) into a watertight shell.
    mat_idx may be a single int or a list of length len(rings)-1 for per-segment coloring.
    """
    bm_rings = [[bm.verts.new(p) for p in ring] for ring in rings]
    n_pts = len(bm_rings[0])
    faces = []
    for i in range(len(bm_rings) - 1):
        seg_mat = mat_idx[i] if isinstance(mat_idx, list) else mat_idx
        r0 = bm_rings[i]
        r1 = bm_rings[i + 1]
        for j in range(n_pts):
            jn = (j + 1) % n_pts
            try:
                f = bm.faces.new((r0[j], r0[jn], r1[jn], r1[j]))
                f.material_index = seg_mat
                f.smooth = smooth
                faces.append(f)
            except ValueError:
                pass
    start_mat = mat_idx[0] if isinstance(mat_idx, list) else mat_idx
    end_mat = mat_idx[-1] if isinstance(mat_idx, list) else mat_idx
    if cap_start:
        try:
            f = bm.faces.new(list(reversed(bm_rings[0])))
            f.material_index = start_mat
            f.smooth = False
            faces.append(f)
        except ValueError:
            pass
    if cap_end:
        try:
            f = bm.faces.new(bm_rings[-1])
            f.material_index = end_mat
            f.smooth = False
            faces.append(f)
        except ValueError:
            pass
    return faces


def rounded_rect_ring(
    y: float,
    half_w: float,
    z_bot: float,
    z_top: float,
    r_bot: float,
    r_top: float,
    corner_segs: int = 4,
    taper_top: float = 0.0,
) -> list[tuple[float, float, float]]:
    """
    Create a CCW closed cross-section ring in the X-Z plane at station y.
    taper_top narrows the upper roof width slightly for sleek commuter coach lines.
    """
    pts: list[tuple[float, float, float]] = []
    hw_top = max(half_w - taper_top, r_top + 0.05)
    rb = min(r_bot, half_w * 0.45, (z_top - z_bot) * 0.35)
    rt = min(r_top, hw_top * 0.45, (z_top - z_bot) * 0.35)

    # 4 corner arcs: TR, TL, BL, BR (CCW when viewed from +Y looking toward -Y, or standard X-Z)
    corners = [
        (hw_top - rt, z_top - rt, rt, 0.0, math.pi * 0.5),
        (-hw_top + rt, z_top - rt, rt, math.pi * 0.5, math.pi),
        (-half_w + rb, z_bot + rb, rb, math.pi, math.pi * 1.5),
        (half_w - rb, z_bot + rb, rb, math.pi * 1.5, math.pi * 2.0),
    ]
    for cx, cz, r, a0, a1 in corners:
        for k in range(corner_segs + 1):
            t = k / corner_segs
            a = a0 + (a1 - a0) * t
            pts.append((cx + r * math.cos(a), y, cz + r * math.sin(a)))
    return pts


def add_uv_quad(
    bm: bmesh.types.BMesh,
    uv_layer,
    p00: tuple[float, float, float],
    p10: tuple[float, float, float],
    p11: tuple[float, float, float],
    p01: tuple[float, float, float],
    mat_idx: int,
) -> bmesh.types.BMFace:
    """Create a single UV-mapped quad with exact (u,v): p00=(0,0), p10=(1,0), p11=(1,1), p01=(0,1)."""
    v00 = bm.verts.new(p00)
    v10 = bm.verts.new(p10)
    v11 = bm.verts.new(p11)
    v01 = bm.verts.new(p01)
    f = bm.faces.new((v00, v10, v11, v01))
    f.material_index = mat_idx
    f.smooth = False
    uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    for loop, uv in zip(f.loops, uvs):
        loop[uv_layer].uv = uv
    return f


def finalize_mesh_obj(
    name: str,
    bm: bmesh.types.BMesh,
    materials: list[bpy.types.Material],
    location: Vector = Vector((0.0, 0.0, 0.0)),
) -> bpy.types.Object:
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()

    for m in materials:
        mesh.materials.append(m)

    obj = bpy.data.objects.new(name, mesh)
    obj.location = location
    bpy.context.scene.collection.objects.link(obj)
    return obj


# ---------------------------------------------------------------------------
# 1. Build GBus_Body (Mountain View Commuter Coach)
# ---------------------------------------------------------------------------

def build_gbus_body(mats: dict[str, bpy.types.Material]) -> bpy.types.Object:
    mat_list = [
        mats["pearl"],       # 0
        mats["window"],      # 1
        mats["mullion"],     # 2
        mats["skirt"],       # 3
        mats["rubber"],      # 4
        mats["alloy"],       # 5
        mats["google_blue"], # 6
        mats["google_red"],  # 7
        mats["google_yel"],  # 8
        mats["google_grn"],  # 9
        mats["headlight"],   # 10
        mats["taillight"],   # 11
        mats["beacon"],      # 12
        mats["signage"],     # 13
        mats["titanium"],    # 14
    ]
    bm = bmesh.new()
    uv_layer = bm.loops.layers.uv.new("UVMap")

    # --- Main Lofted Coach Fuselage (Y from -5.85 tail to +5.85 nose, width ~2.70m) ---
    # Stations: (y, half_w, z_bot, z_top, r_bot, r_top, taper_top)
    stations = [
        (-5.85, 1.18, -1.08, 1.46, 0.20, 0.24, 0.08),  # Rear cap
        (-5.68, 1.32, -1.24, 1.66, 0.20, 0.26, 0.06),  # Rear bevel
        (-5.15, 1.35, -1.32, 1.72, 0.18, 0.26, 0.05),  # Rear coach full
        (-2.50, 1.35, -1.32, 1.74, 0.18, 0.26, 0.05),  # Mid-rear
        ( 2.80, 1.35, -1.32, 1.74, 0.18, 0.26, 0.05),  # Mid-front
        ( 4.65, 1.33, -1.30, 1.70, 0.18, 0.26, 0.06),  # Windshield crown start
        ( 5.42, 1.26, -1.24, 1.54, 0.22, 0.28, 0.08),  # Sleek raked front header
        ( 5.78, 1.16, -1.16, 1.22, 0.22, 0.24, 0.08),  # Front face plane
        ( 5.88, 1.00, -1.02, 0.85, 0.18, 0.20, 0.08),  # Nose cap
    ]
    rings = [
        rounded_rect_ring(y, hw, zb, zt, rb, rt, corner_segs=4, taper_top=tp)
        for (y, hw, zb, zt, rb, rt, tp) in stations
    ]
    add_lofted_tube(bm, rings, mat_idx=0, cap_start=True, cap_end=True, smooth=True)

    # --- Dark Lower Skirt / Bumper Trim ---
    add_box(bm, (0.0, -0.10, -1.25), (2.74, 10.65, 0.24), mat_idx=3, bevel=0.04)
    # Front chin bumper
    add_box(bm, (0.0, 5.56, -1.08), (2.42, 0.70, 0.34), mat_idx=3, bevel=0.07)
    # Rear bumper
    add_box(bm, (0.0, -5.62, -1.10), (2.54, 0.56, 0.34), mat_idx=3, bevel=0.06)
    # Rear drop-bay boarding hatch plate
    add_box(bm, (0.0, -5.86, -0.58), (1.58, 0.10, 0.78), mat_idx=14, bevel=0.03)

    # --- Panoramic Tinted Side Windows (Upper Deck & Lower Deck) — Proud of Hull ---
    for sx in (-1.0, 1.0):
        # Upper panoramic window band (Z = +0.62 to +1.36, Y = -5.05 to +4.50)
        # Outer glass face at |X| = 1.376, cleanly proud of the 1.35m hull!
        add_box(
            bm,
            (sx * 1.356, -0.28, 0.99),
            (0.042, 9.55, 0.74),
            mat_idx=1,
            bevel=0.015,
            smooth=False,
        )
        # Sleek dark window frame top/bottom strips
        add_box(bm, (sx * 1.362, -0.28, 1.375), (0.044, 9.60, 0.045), mat_idx=2, smooth=False)
        add_box(bm, (sx * 1.362, -0.28, 0.605), (0.044, 9.60, 0.045), mat_idx=2, smooth=False)
        # Vertical window mullions (5 bays)
        for my in (-3.6, -1.9, -0.2, 1.5, 3.1):
            add_box(bm, (sx * 1.368, my, 0.99), (0.040, 0.085, 0.74), mat_idx=2, smooth=False)

        # Lower commuter deck windows flanking the GBUS signage
        # Rear lower bay: Y = -4.85 to -2.15
        add_box(bm, (sx * 1.356, -3.50, -0.40), (0.042, 2.70, 0.48), mat_idx=1, bevel=0.015, smooth=False)
        # Front lower bay: Y = +2.15 to +4.55
        add_box(bm, (sx * 1.356, 3.35, -0.40), (0.042, 2.40, 0.48), mat_idx=1, bevel=0.015, smooth=False)
        # Lower bay mullions
        add_box(bm, (sx * 1.368, -3.50, -0.40), (0.040, 0.075, 0.48), mat_idx=2, smooth=False)
        add_box(bm, (sx * 1.368, 3.35, -0.40), (0.040, 0.075, 0.48), mat_idx=2, smooth=False)

    # --- Front Wrap-Around Panoramic Windshield (Upper & Lower — Proud of Nose) ---
    # Upper raked panoramic glass (cleanly proud of the sloped forehead)
    add_box(
        bm,
        (0.0, 5.76, 1.02),
        (2.14, 0.14, 0.68),
        mat_idx=1,
        rot_euler=(math.radians(18.0), 0.0, 0.0),
        bevel=0.03,
        smooth=True,
    )
    # Lower driver panoramic glass
    add_box(
        bm,
        (0.0, 5.87, 0.22),
        (2.08, 0.14, 0.72),
        mat_idx=1,
        rot_euler=(math.radians(6.0), 0.0, 0.0),
        bevel=0.03,
        smooth=True,
    )
    # Windshield center divider bar, A-pillar frame & LED destination header
    add_box(bm, (0.0, 5.86, 0.63), (2.18, 0.16, 0.10), mat_idx=2, bevel=0.02)
    add_box(bm, (0.0, 5.56, 1.48), (1.36, 0.14, 0.16), mat_idx=2, bevel=0.02)
    add_box(bm, (0.0, 5.63, 1.48), (1.06, 0.06, 0.07), mat_idx=12, smooth=False)

    # Rear panoramic observation window (cleanly proud of Y = -5.85 cap)
    add_box(bm, (0.0, -5.85, 0.90), (2.04, 0.09, 0.74), mat_idx=1, bevel=0.02, smooth=False)
    add_box(bm, (0.0, -5.86, 1.29), (2.08, 0.08, 0.045), mat_idx=2, smooth=False)
    add_box(bm, (0.0, -5.86, 0.51), (2.08, 0.08, 0.045), mat_idx=2, smooth=False)

    # --- Bold 4-Color Google Ribbon Stripe Wrapping Both Sides & Nose/Rear ---
    ribbon_bands = [
        (0.46, 6),  # Blue (top)
        (0.36, 7),  # Red
        (0.26, 8),  # Yellow
        (0.16, 9),  # Green (bottom)
    ]
    for z_band, m_idx in ribbon_bands:
        for sx in (-1.0, 1.0):
            # Side stripe running full coach length
            add_box(
                bm,
                (sx * 1.366, -0.32, z_band),
                (0.026, 9.80, 0.096),
                mat_idx=m_idx,
                smooth=False,
            )
        # Rear wrap stripe
        add_box(bm, (0.0, -5.88, z_band), (2.30, 0.05, 0.096), mat_idx=m_idx, smooth=False)

    # Front nose 4-color Google badge bar below lower windshield (cleanly proud)
    nose_cols = [(-0.66, 6), (-0.22, 7), (0.22, 8), (0.66, 9)]
    for nx, m_idx in nose_cols:
        add_box(bm, (nx, 5.91, -0.30), (0.42, 0.07, 0.11), mat_idx=m_idx, bevel=0.015)

    # --- Crisp Dual-Sided GBUS Signage (512x128 Packed Texture, ZERO Mirroring!) ---
    # Width = 3.56m (Y from -1.78 to +1.78), Height = 0.89m (Z from -0.84 to +0.05) -> exact 4:1 ratio!
    y_min_s, y_max_s = -1.78, 1.78
    z_min_s, z_max_s = -0.84, 0.05

    # Right side (+X): u=0 -> Y_min (-1.78), u=1 -> Y_max (+1.78). Normal points +X.
    x_r = 1.376
    add_uv_quad(
        bm,
        uv_layer,
        p00=(x_r, y_min_s, z_min_s),
        p10=(x_r, y_max_s, z_min_s),
        p11=(x_r, y_max_s, z_max_s),
        p01=(x_r, y_min_s, z_max_s),
        mat_idx=13,
    )
    # Left side (-X): u=0 -> Y_max (+1.78), u=1 -> Y_min (-1.78). Normal points -X.
    x_l = -1.376
    add_uv_quad(
        bm,
        uv_layer,
        p00=(x_l, y_max_s, z_min_s),
        p10=(x_l, y_min_s, z_min_s),
        p11=(x_l, y_min_s, z_max_s),
        p01=(x_l, y_max_s, z_max_s),
        mat_idx=13,
    )

    # --- Tucked-Up Landing Wheels & Wheel Wells (6 Coach Wheels: Front + Tandem Rear) ---
    # Bottom of tires sits cleanly at Z = -1.60!
    wheel_radius = 0.44
    wheel_z = -1.60 + wheel_radius  # -1.16
    wheel_ys = [3.35, -2.55, -3.75]
    for wy in wheel_ys:
        for sx in (-1.0, 1.0):
            # Recessed dark wheel arch housing (sits inward of outer tire face!)
            add_cylinder(
                bm,
                center=(sx * 1.12, wy, wheel_z + 0.04),
                radius1=0.51,
                radius2=0.51,
                depth=0.22,
                segments=14,
                mat_idx=3,
                rot_euler=(0.0, math.pi * 0.5, 0.0),
            )
            # Tire rubber (outer face at |X| = 1.37)
            add_cylinder(
                bm,
                center=(sx * 1.23, wy, wheel_z),
                radius1=wheel_radius,
                radius2=wheel_radius,
                depth=0.28,
                segments=18,
                mat_idx=4,
                rot_euler=(0.0, math.pi * 0.5, 0.0),
            )
            # Bright metallic alloy wheel rim (proud of tire sidewall at |X| = 1.385)
            add_cylinder(
                bm,
                center=(sx * 1.26, wy, wheel_z),
                radius1=0.27,
                radius2=0.27,
                depth=0.26,
                segments=14,
                mat_idx=5,
                rot_euler=(0.0, math.pi * 0.5, 0.0),
            )
            # Google-blue center hubcap (outer face at |X| = 1.40)
            add_cylinder(
                bm,
                center=(sx * 1.28, wy, wheel_z),
                radius1=0.11,
                radius2=0.11,
                depth=0.24,
                segments=12,
                mat_idx=6,
                rot_euler=(0.0, math.pi * 0.5, 0.0),
            )

    # --- Bright Warm LED Headlights & Red Tail Lights (Proud of Nose/Tail) ---
    for sx in (-1.0, 1.0):
        # Headlight dark bezel
        add_box(bm, (sx * 0.86, 5.84, -0.68), (0.50, 0.16, 0.26), mat_idx=2, bevel=0.03)
        # Emissive warm LED headlight lens
        add_box(bm, (sx * 0.86, 5.91, -0.68), (0.40, 0.08, 0.16), mat_idx=10, bevel=0.02)
        # Rear tail light bezel
        add_box(bm, (sx * 0.98, -5.86, -0.60), (0.34, 0.14, 0.44), mat_idx=2, bevel=0.02)
        # Emissive red LED tail light bar
        add_box(bm, (sx * 0.98, -5.92, -0.60), (0.24, 0.08, 0.36), mat_idx=11, bevel=0.02)

    # Rear high-mount brake light
    add_box(bm, (0.0, -5.84, 1.44), (0.94, 0.08, 0.09), mat_idx=11, bevel=0.01)

    # --- Roof Details: Sleek HVAC Pods + Glowing Roof Beacon Dome ---
    # Front roof aero HVAC unit
    add_box(bm, (0.0, 2.75, 1.80), (1.50, 1.65, 0.18), mat_idx=0, bevel=0.06)
    add_box(bm, (0.0, 2.75, 1.88), (1.10, 1.15, 0.05), mat_idx=14, bevel=0.01)
    # Rear roof aero HVAC unit
    add_box(bm, (0.0, -2.90, 1.80), (1.50, 1.55, 0.18), mat_idx=0, bevel=0.06)

    # Roof Beacon Dome (centered slightly forward on roof crown, Z peak ~ 2.02)
    add_cylinder(bm, (0.0, 0.55, 1.78), 0.34, 0.28, 0.12, 16, mat_idx=3)
    # Glowing cyan-blue beacon lens dome
    ret_dome = bmesh.ops.create_uvsphere(
        bm,
        u_segments=16,
        v_segments=10,
        radius=0.22,
        matrix=Matrix.Translation(Vector((0.0, 0.55, 1.84))) @ Matrix.Diagonal((1.0, 1.0, 0.72, 1.0)),
    )
    dv = set(ret_dome["verts"])
    for f in bm.faces:
        if all(v in dv for v in f.verts):
            f.material_index = 12
            f.smooth = True

    # Side aero rear-view mirrors
    for sx in (-1.0, 1.0):
        add_box(bm, (sx * 1.48, 4.95, 0.52), (0.28, 0.08, 0.08), mat_idx=3, bevel=0.01)
        add_box(bm, (sx * 1.60, 4.95, 0.36), (0.10, 0.16, 0.34), mat_idx=3, bevel=0.03)

    return finalize_mesh_obj("GBus_Body", bm, mat_list)


# ---------------------------------------------------------------------------
# 2. Build GBus_Wings (Swept Aero Wings, Winglets, Twin Nacelles & V-Tail)
# ---------------------------------------------------------------------------

def airfoil_ring(
    x: float,
    y_le: float,
    chord: float,
    z_center: float,
    thickness: float,
    n_pts: int = 12,
) -> list[tuple[float, float, float]]:
    """
    Create a closed aerodynamic airfoil cross-section in the Y-Z plane at span station x.
    y_le is the leading edge (+Y), trailing edge is at y_le - chord.
    """
    pts: list[tuple[float, float, float]] = []
    half = n_pts // 2
    # Upper surface: LE -> TE
    for i in range(half):
        t = i / half  # 0 at LE, ~1 at TE
        y = y_le - t * chord
        # NACA-like thickness + slight positive camber
        yt = 5.0 * thickness * (
            0.2969 * math.sqrt(max(t, 1e-4))
            - 0.1260 * t
            - 0.3516 * t * t
            + 0.2843 * t ** 3
            - 0.1015 * t ** 4
        )
        camber = 0.03 * chord * math.sin(math.pi * t)
        pts.append((x, y, z_center + camber + yt * 0.55))
    # Lower surface: TE -> LE
    for i in range(half):
        t = 1.0 - (i / half)
        y = y_le - t * chord
        yt = 5.0 * thickness * (
            0.2969 * math.sqrt(max(t, 1e-4))
            - 0.1260 * t
            - 0.3516 * t * t
            + 0.2843 * t ** 3
            - 0.1015 * t ** 4
        )
        camber = 0.03 * chord * math.sin(math.pi * t)
        pts.append((x, y, z_center + camber - yt * 0.38))
    return pts


def build_gbus_wings(mats: dict[str, bpy.types.Material]) -> bpy.types.Object:
    mat_list = [
        mats["pearl"],       # 0
        mats["light_trim"],  # 1
        mats["gunmetal"],    # 2
        mats["titanium"],    # 3
        mats["google_blue"], # 4
        mats["google_red"],  # 5
        mats["google_yel"],  # 6
        mats["google_grn"],  # 7
        mats["thruster"],    # 8
        mats["skirt"],       # 9
    ]
    bm = bmesh.new()

    # --- Dorsal Wing-Box Fairing (blends high wings cleanly onto coach roof) ---
    add_box(bm, (0.0, 0.15, 1.54), (2.45, 3.25, 0.42), mat_idx=0, bevel=0.14)
    add_box(bm, (0.0, 0.15, 1.74), (1.85, 2.55, 0.08), mat_idx=4, bevel=0.03)

    # --- Swept High-Mounted Aero Wings (Total wingspan ~13.6m: X = -6.8 to +6.8) ---
    # Built with flush per-segment color bands (zero clipping!)
    wing_stations = [
        # (abs_x, y_le, chord, z_center, thickness)
        (1.15, 1.65, 2.95, 1.48, 0.36),
        (2.70, 1.24, 2.48, 1.58, 0.28),
        (4.25, 0.72, 2.02, 1.69, 0.22),
        (5.55, 0.22, 1.60, 1.78, 0.17),
        (6.45, -0.18, 1.26, 1.84, 0.13),
    ]
    for sx in (-1.0, 1.0):
        rings = []
        for ax, yle, ch, zc, th in wing_stations:
            ring = airfoil_ring(sx * ax, yle, ch, zc, th, n_pts=12)
            if sx < 0:
                ring = list(reversed(ring))
            rings.append(ring)
        # Pearl white main wing + subtle light-trim outer wing panel
        add_lofted_tube(bm, rings, mat_idx=[0, 0, 0, 1], cap_start=True, cap_end=True, smooth=True)

        # --- Upturned Google-Colored Winglets (Flush 2-Tone Loft, reaching X = ±6.80, Z = +2.82) ---
        wl_rings = [
            airfoil_ring(sx * 6.42, -0.18, 1.24, 1.84, 0.13, n_pts=10),
            airfoil_ring(sx * 6.58, -0.38, 1.02, 2.18, 0.11, n_pts=10),
            airfoil_ring(sx * 6.72, -0.60, 0.80, 2.52, 0.09, n_pts=10),
            airfoil_ring(sx * 6.80, -0.82, 0.58, 2.82, 0.07, n_pts=10),
        ]
        if sx < 0:
            wl_rings = [list(reversed(r)) for r in wl_rings]
        # Right winglet: Google Blue base + Red tip; Left winglet: Google Green base + Yellow tip
        wl_mats = [4, 4, 5] if sx > 0 else [7, 7, 6]
        add_lofted_tube(bm, wl_rings, mat_idx=wl_mats, cap_start=True, cap_end=True, smooth=True)

    # --- Twin Under-Wing Pylons & Engine Nacelles at X = ±3.85, Z = +0.42 ---
    for sx, (rotor_pos, thruster_pos) in [
        (-1.0, (ROTOR_L_POS, THRUSTER_L_POS)),
        (1.0, (ROTOR_R_POS, THRUSTER_R_POS)),
    ]:
        nx = rotor_pos.x
        nz = rotor_pos.z

        # Aerodynamic wing-to-nacelle pylon strut
        add_box(
            bm,
            (nx, 0.25, 1.12),
            (0.22, 1.95, 1.08),
            mat_idx=1,
            bevel=0.05,
        )

        # Sculpted Multi-Station Nacelle Cowling (Y from -1.52 exhaust to +1.72 intake behind rotor hub +1.80)
        nacelle_stations = [
            (-1.52, 0.32),  # Rear exhaust rim
            (-1.32, 0.42),  # Rear taper
            (-0.85, 0.50),  # Main pearl cowling rear
            ( 0.50, 0.52),  # Main pearl cowling mid
            ( 1.25, 0.48),  # Front cowling shoulder
            ( 1.60, 0.40),  # Front intake lip
            ( 1.72, 0.31),  # Hub collar just behind rotor at +1.80
        ]
        n_seg = 18
        nac_rings = []
        for ny, nr in nacelle_stations:
            ring = [
                (
                    nx + nr * math.cos(2.0 * math.pi * k / n_seg),
                    ny,
                    nz + nr * math.sin(2.0 * math.pi * k / n_seg),
                )
                for k in range(n_seg)
            ]
            nac_rings.append(ring)
        # Gunmetal rear & front cowling collars, pearl white center
        add_lofted_tube(bm, nac_rings, mat_idx=[2, 0, 0, 0, 0, 2], cap_start=True, cap_end=True, smooth=True)

        # Google-colored racing bands around nacelle mid-body
        add_cylinder(
            bm,
            center=(nx, 0.55, nz),
            radius1=0.532,
            radius2=0.532,
            depth=0.22,
            segments=18,
            mat_idx=4 if sx > 0 else 5,
            rot_euler=(math.pi * 0.5, 0.0, 0.0),
            cap_ends=False,
        )
        add_cylinder(
            bm,
            center=(nx, 0.36, nz),
            radius1=0.532,
            radius2=0.532,
            depth=0.11,
            segments=18,
            mat_idx=6 if sx > 0 else 7,
            rot_euler=(math.pi * 0.5, 0.0, 0.0),
            cap_ends=False,
        )

        # Bright Glowing Cyan-Blue Rear Jet Thruster Ring (#38BDF8 Emissive) at Y = -1.55
        add_cylinder(
            bm,
            center=(nx, thruster_pos.y + 0.03, nz),
            radius1=0.29,
            radius2=0.24,
            depth=0.14,
            segments=18,
            mat_idx=8,
            rot_euler=(math.pi * 0.5, 0.0, 0.0),
        )
        # Inner bright plasma core disc
        add_cylinder(
            bm,
            center=(nx, thruster_pos.y + 0.01, nz),
            radius1=0.20,
            radius2=0.20,
            depth=0.06,
            segments=16,
            mat_idx=8,
            rot_euler=(math.pi * 0.5, 0.0, 0.0),
        )

    # --- Crisp Twin-Fin / V-Tail Stabilizer (Flush Per-Segment Coloring) ---
    # Rear dorsal spine fairing
    add_box(bm, (0.0, -4.70, 1.66), (0.85, 2.05, 0.34), mat_idx=0, bevel=0.10)

    for sx in (-1.0, 1.0):
        # Swept V-tail fin rising outward at ~32 degrees, flush 2-tone tip
        tail_rings = [
            airfoil_ring(sx * 0.36, -3.95, 1.80, 1.64, 0.14, n_pts=10),
            airfoil_ring(sx * 0.96, -4.52, 1.48, 2.26, 0.11, n_pts=10),
            airfoil_ring(sx * 1.48, -5.00, 1.18, 2.80, 0.09, n_pts=10),
            airfoil_ring(sx * 1.86, -5.34, 0.92, 3.18, 0.07, n_pts=10),
        ]
        if sx < 0:
            tail_rings = [list(reversed(r)) for r in tail_rings]
        # Pearl white main fin + crisp Google Red (right) / Google Blue (left) top tip band
        tail_mats = [0, 0, 5 if sx > 0 else 4]
        add_lofted_tube(bm, tail_rings, mat_idx=tail_mats, cap_start=True, cap_end=True, smooth=True)

        # Lower horizontal stabilizer winglets
        hstab_rings = [
            airfoil_ring(sx * 1.05, -4.45, 1.25, 1.42, 0.12, n_pts=10),
            airfoil_ring(sx * 2.45, -5.00, 0.78, 1.48, 0.08, n_pts=10),
        ]
        if sx < 0:
            hstab_rings = [list(reversed(r)) for r in hstab_rings]
        add_lofted_tube(bm, hstab_rings, mat_idx=1, cap_start=True, cap_end=True, smooth=True)

    return finalize_mesh_obj("GBus_Wings", bm, mat_list)


# ---------------------------------------------------------------------------
# 3. Build GBus_RotorL & GBus_RotorR (Pivoted at Exact Hub Center)
# ---------------------------------------------------------------------------

def build_gbus_rotor(
    name: str,
    location: Vector,
    mats: dict[str, bpy.types.Material],
    pitch_sign: float = 1.0,
) -> bpy.types.Object:
    """
    Build a 4-blade aerodynamic propeller + conical spinner centered at local (0, 0, 0).
    Blades lie in the local X-Z plane so rotating around Blender Y (= Three.js Z)
    spins the rotor smoothly around its forward axis!
    """
    mat_list = [
        mats["titanium"],    # 0: spinner
        mats["gunmetal"],    # 1: blades
        mats["google_yel"],  # 2: high-vis blade tips
        mats["google_blue"], # 3: spinner stripe
    ]
    bm = bmesh.new()

    # Conical aero spinner nosecone pointing +Y (forward)
    add_cylinder(
        bm,
        center=(0.0, 0.16, 0.0),
        radius1=0.22,
        radius2=0.03,
        depth=0.42,
        segments=16,
        mat_idx=0,
        rot_euler=(-math.pi * 0.5, 0.0, 0.0),
    )
    # Spinner base collar ring
    add_cylinder(
        bm,
        center=(0.0, -0.02, 0.0),
        radius1=0.23,
        radius2=0.22,
        depth=0.10,
        segments=16,
        mat_idx=3,
        rot_euler=(-math.pi * 0.5, 0.0, 0.0),
    )

    # 4 sculpted pitched propeller blades in the X-Z plane (radius ~1.02m)
    blade_len = 1.02
    for i in range(4):
        ang = i * (math.pi * 0.5) + math.radians(22.5)
        rot_y = Matrix.Rotation(ang, 4, "Y")
        pitch = Matrix.Rotation(math.radians(24.0 * pitch_sign), 4, "X")

        # Main carbon-slate blade
        bm_tmp = bmesh.new()
        add_box(bm_tmp, (0.52, 0.0, 0.0), (0.86, 0.032, 0.155), mat_idx=1, bevel=0.012)
        # Yellow safety tip
        add_box(bm_tmp, (0.98, 0.0, 0.0), (0.14, 0.026, 0.135), mat_idx=2, bevel=0.008)

        xform = rot_y @ pitch
        bmesh.ops.transform(bm_tmp, matrix=xform, verts=bm_tmp.verts)

        # Merge into main rotor bmesh
        vmap = {}
        for v in bm_tmp.verts:
            vmap[v] = bm.verts.new(v.co)
        for f in bm_tmp.faces:
            try:
                nf = bm.faces.new([vmap[v] for v in f.verts])
                nf.material_index = f.material_index
                nf.smooth = f.smooth
            except ValueError:
                pass
        bm_tmp.free()

    return finalize_mesh_obj(name, bm, mat_list, location=location)


# ---------------------------------------------------------------------------
# 4. Build Thruster Anchor Empties
# ---------------------------------------------------------------------------

def add_empty(name: str, location: Vector) -> bpy.types.Object:
    emp = bpy.data.objects.new(name, None)
    emp.empty_display_type = "PLAIN_AXES"
    emp.empty_display_size = 0.5
    emp.location = location
    bpy.context.scene.collection.objects.link(emp)
    return emp


# ---------------------------------------------------------------------------
# 5. GLB Structural Verification & Three.js Coordinate Report
# ---------------------------------------------------------------------------

def inspect_glb(glb_path: Path) -> dict:
    data = glb_path.read_bytes()
    magic, version, length = struct.unpack_from("<4sII", data, 0)
    assert magic == b"glTF", f"Not a valid GLB: {magic}"
    chunk0_len, chunk0_type = struct.unpack_from("<II", data, 12)
    assert chunk0_type == 0x4E4F534A, "First chunk is not JSON"
    gltf = json.loads(data[20 : 20 + chunk0_len].decode("utf-8"))

    ext_used = gltf.get("extensionsUsed", [])
    has_draco = "KHR_draco_mesh_compression" in ext_used

    nodes_info = {}
    for n in gltf.get("nodes", []):
        name = n.get("name", "<unnamed>")
        nodes_info[name] = {
            "translation": n.get("translation", [0.0, 0.0, 0.0]),
            "mesh": n.get("mesh"),
        }

    # Count total triangles from accessors
    total_tris = 0
    accessors = gltf.get("accessors", [])
    for m in gltf.get("meshes", []):
        for prim in m.get("primitives", []):
            if "indices" in prim:
                total_tris += accessors[prim["indices"]]["count"] // 3
            elif "POSITION" in prim.get("attributes", {}):
                total_tris += accessors[prim["attributes"]["POSITION"]]["count"] // 3

    return {
        "file_size_bytes": len(data),
        "file_size_kb": len(data) / 1024.0,
        "has_draco": has_draco,
        "extensions_used": ext_used,
        "total_tris": total_tris,
        "nodes": nodes_info,
    }


def compute_scene_bounds() -> tuple[Vector, Vector]:
    bmin = Vector((1e9, 1e9, 1e9))
    bmax = Vector((-1e9, -1e9, -1e9))
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        for corner in obj.bound_box:
            wc = obj.matrix_world @ Vector(corner)
            bmin.x = min(bmin.x, wc.x)
            bmin.y = min(bmin.y, wc.y)
            bmin.z = min(bmin.z, wc.z)
            bmax.x = max(bmax.x, wc.x)
            bmax.y = max(bmax.y, wc.y)
            bmax.z = max(bmax.z, wc.z)
    return bmin, bmax


# ---------------------------------------------------------------------------
# 6. Studio EEVEE 2-Angle QA Preview Renderer (Front-3/4 + Rear-3/4)
# ---------------------------------------------------------------------------

def render_two_angle_preview(out_png: Path) -> None:
    out_png.parent.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 24
    scene.render.resolution_x = 960
    scene.render.resolution_y = 640
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.view_transform = "AgX"
    try:
        scene.view_settings.look = "AgX - Medium High Contrast"
    except Exception:
        pass

    # Clean bright sky-blue studio backdrop so white coach + cyan thrusters pop
    world = bpy.data.worlds.new("StudioWorld")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs["Color"].default_value = (0.16, 0.24, 0.38, 1.0)
        bg.inputs["Strength"].default_value = 1.15

    # Studio 3-point lighting
    def add_light(name: str, ltype: str, loc: tuple, rot_deg: tuple, energy: float, color=(1.0, 1.0, 1.0), size=4.0):
        ldata = bpy.data.lights.new(name=name, type=ltype)
        ldata.energy = energy
        ldata.color = color
        if ltype == "AREA":
            ldata.size = size
        lobj = bpy.data.objects.new(name, ldata)
        lobj.location = Vector(loc)
        lobj.rotation_euler = Euler(tuple(math.radians(a) for a in rot_deg), "XYZ")
        scene.collection.objects.link(lobj)
        return lobj

    add_light("KeyLight", "SUN", (10, 12, 14), (48, 0, -35), 3.2, (1.0, 0.98, 0.94))
    add_light("FillLight", "AREA", (-14, 10, 8), (60, 0, -125), 900.0, (0.82, 0.90, 1.0), size=8.0)
    add_light("RimLight", "AREA", (8, -14, 9), (58, 0, 28), 850.0, (0.90, 0.96, 1.0), size=7.0)
    add_light("UnderBounce", "AREA", (0, 0, -8), (180, 0, 0), 320.0, (0.75, 0.85, 0.98), size=10.0)

    # Camera setup
    cam_data = bpy.data.cameras.new("PreviewCam")
    cam_data.lens = 42.0
    cam_obj = bpy.data.objects.new("PreviewCam", cam_data)
    scene.collection.objects.link(cam_obj)
    scene.camera = cam_obj

    def aim_camera(cam_loc: Vector, target: Vector) -> None:
        cam_obj.location = cam_loc
        direction = target - cam_loc
        cam_obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()

    target = Vector((0.0, 0.0, 0.35))
    # View 1: Front-Right 3/4 (+X, +Y, +Z) -> shows nose, panoramic windshield, headlights, rotors, right GBUS signage
    # View 2: Rear-Left 3/4 (-X, -Y, +Z) -> shows glowing cyan thrusters, V-tail, tail lights, winglets, left GBUS signage
    views = [
        ("front", Vector((11.8, 13.4, 3.8))),
        ("rear", Vector((-12.2, -13.2, 4.2))),
    ]

    imgs_np = []
    with tempfile.TemporaryDirectory() as tmpdir:
        for label, loc in views:
            aim_camera(loc, target)
            tmp_path = Path(tmpdir) / f"{label}.png"
            scene.render.filepath = str(tmp_path)
            bpy.ops.render.render(write_still=True)

            loaded = bpy.data.images.load(str(tmp_path))
            w, h = loaded.size
            arr = np.empty(w * h * 4, dtype=np.float32)
            loaded.pixels.foreach_get(arr)
            imgs_np.append(arr.reshape(h, w, 4))
            bpy.data.images.remove(loaded)

    # Stitch side-by-side (1920x640) with a crisp 4px dark divider
    h, w, _ = imgs_np[0].shape
    divider = np.zeros((h, 4, 4), dtype=np.float32)
    divider[:, :, 0:3] = 0.08
    divider[:, :, 3] = 1.0
    combined = np.concatenate([imgs_np[0], divider, imgs_np[1]], axis=1)

    ch, cw, _ = combined.shape
    out_img = bpy.data.images.new("QA_Combined", width=cw, height=ch, alpha=True)
    out_img.pixels.foreach_set(combined.ravel())
    out_img.filepath_raw = str(out_png)
    out_img.file_format = "PNG"
    out_img.save()
    bpy.data.images.remove(out_img)


# ---------------------------------------------------------------------------
# Main Pipeline
# ---------------------------------------------------------------------------

def main() -> None:
    clear_scene()

    mats = {
        "pearl": make_pbr_mat("Mat_GBus_PearlWhite", COL_PEARL_WHITE, metallic=0.05, roughness=0.24, coat=0.35),
        "light_trim": make_pbr_mat("Mat_GBus_LightTrim", COL_LIGHT_TRIM, metallic=0.12, roughness=0.32),
        "window": make_pbr_mat("Mat_GBus_TintedGlass", COL_WINDOW_TINT, metallic=0.15, roughness=0.12, coat=0.70),
        "mullion": make_pbr_mat("Mat_GBus_Mullion", COL_WINDOW_MULLION, metallic=0.25, roughness=0.38),
        "skirt": make_pbr_mat("Mat_GBus_DarkSkirt", COL_DARK_SKIRT, metallic=0.15, roughness=0.48),
        "rubber": make_pbr_mat("Mat_GBus_TireRubber", COL_RUBBER, metallic=0.0, roughness=0.78),
        "alloy": make_pbr_mat("Mat_GBus_AlloyRim", COL_ALLOY_SILVER, metallic=0.82, roughness=0.24),
        "gunmetal": make_pbr_mat("Mat_GBus_Gunmetal", COL_GUNMETAL, metallic=0.68, roughness=0.34),
        "titanium": make_pbr_mat("Mat_GBus_Titanium", COL_TITANIUM, metallic=0.78, roughness=0.26),
        "google_blue": make_pbr_mat("Mat_Google_Blue", COL_GOOGLE_BLUE, metallic=0.05, roughness=0.22, coat=0.30),
        "google_red": make_pbr_mat("Mat_Google_Red", COL_GOOGLE_RED, metallic=0.05, roughness=0.22, coat=0.30),
        "google_yel": make_pbr_mat("Mat_Google_Yellow", COL_GOOGLE_YELLOW, metallic=0.05, roughness=0.22, coat=0.30),
        "google_grn": make_pbr_mat("Mat_Google_Green", COL_GOOGLE_GREEN, metallic=0.05, roughness=0.22, coat=0.30),
        "headlight": make_pbr_mat("Mat_GBus_Headlight", COL_HEADLIGHT, roughness=0.10, emission_hex=COL_HEADLIGHT, emission_strength=6.5),
        "taillight": make_pbr_mat("Mat_GBus_Taillight", COL_TAILLIGHT, roughness=0.12, emission_hex=COL_TAILLIGHT, emission_strength=5.5),
        "thruster": make_pbr_mat("Mat_GBus_ThrusterGlow", COL_THRUSTER_CYAN, roughness=0.10, emission_hex=COL_THRUSTER_CYAN, emission_strength=9.5),
        "beacon": make_pbr_mat("Mat_GBus_RoofBeacon", COL_BEACON_BLUE, roughness=0.10, emission_hex=COL_BEACON_BLUE, emission_strength=5.0),
        "signage": build_gbus_signage_material(),
    }

    # Build all required objects
    build_gbus_body(mats)
    build_gbus_wings(mats)
    build_gbus_rotor("GBus_RotorL", ROTOR_L_POS, mats, pitch_sign=1.0)
    build_gbus_rotor("GBus_RotorR", ROTOR_R_POS, mats, pitch_sign=-1.0)
    add_empty("GBus_ThrusterL", THRUSTER_L_POS)
    add_empty("GBus_ThrusterR", THRUSTER_R_POS)

    # Measure Blender bounds before export
    bmin, bmax = compute_scene_bounds()
    dims = bmax - bmin

    # Export GLB (ZERO Draco, export_yup=True)
    OUT_GLB.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=str(OUT_GLB),
        export_format="GLB",
        export_yup=True,
        export_draco_mesh_compression_enable=False,
        export_apply=True,
        export_materials="EXPORT",
        export_texcoords=True,
        export_normals=True,
        export_extras=True,
    )

    # Validate exported GLB
    report = inspect_glb(OUT_GLB)
    print("\n" + "=" * 72)
    print("GOOGLE GBUS WITH WINGS — GLB EXPORT AUDIT")
    print("=" * 72)
    print(f"GLB Path       : {OUT_GLB}")
    print(f"File Size      : {report['file_size_kb']:.1f} KB ({report['file_size_bytes']} bytes) [Limit: < 650 KB]")
    print(f"Draco Enabled  : {report['has_draco']} (Extensions: {report['extensions_used']})")
    print(f"Total Tris     : {report['total_tris']}")
    print(
        f"Blender Bounds : X=[{bmin.x:.2f}, {bmax.x:.2f}] (span {dims.x:.2f}m), "
        f"Y=[{bmin.y:.2f}, {bmax.y:.2f}] (len {dims.y:.2f}m), "
        f"Z=[{bmin.z:.2f}, {bmax.z:.2f}] (h {dims.z:.2f}m)"
    )
    print(
        f"Three.js Bounds: X=[{bmin.x:.2f}, {bmax.x:.2f}], "
        f"Y=[{bmin.z:.2f}, {bmax.z:.2f}], "
        f"Z=[{-bmax.y:.2f}, {-bmin.y:.2f}] (Nose at -Z)"
    )
    print("Three.js Node Coordinates (from GLB JSON):")
    for node_name in [
        "GBus_Body",
        "GBus_Wings",
        "GBus_RotorL",
        "GBus_RotorR",
        "GBus_ThrusterL",
        "GBus_ThrusterR",
    ]:
        info = report["nodes"].get(node_name)
        if info is None:
            raise RuntimeError(f"MISSING REQUIRED GLB NODE: {node_name}")
        tx, ty, tz = info["translation"]
        print(f"  - {node_name:15s}: ({tx:+.3f}, {ty:+.3f}, {tz:+.3f})")

    assert not report["has_draco"], "Draco compression MUST be disabled!"
    assert report["file_size_kb"] < 650.0, f"GLB exceeds 650 KB: {report['file_size_kb']:.1f} KB"

    # Render 2-angle studio EEVEE QA preview
    render_two_angle_preview(PREVIEW_PNG)
    print(f"QA Preview PNG : {PREVIEW_PNG}")
    print("=" * 72 + "\n")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Workspace Royale — Iconic 3D Noogler Propeller Hat Outfit Asset Generator & QA Renderer
=======================================================================================
Builds the stylized 3D Google Noogler Propeller Hat `.glb` asset in Blender 5.3.0:
  - Output GLB: public/assets/characters/outfit_noogler_hat.glb (ZERO Draco, < 120 KB)
  - QA Preview: /Users/davidyou/.gemini/antigravity/brain/a9682dfa-7d5f-428c-afd4-e62e35b1964e/previews/qa_noogler_hat.png

Geometry & Attachment Spec (export_yup=True):
  - Forward visor/brim points along Blender +Y -> Three.js -Z
  - Hat base rim sits cleanly at Blender Z = 0.000 -> Three.js Y = 0.000
  - Dome radius ~0.165m (diameter ~0.33m)
  - Two clean root nodes:
      1. Noogler_Cap       @ Blender (0.000, 0.000, 0.000) -> Three.js (0.000, 0.000, 0.000)
         - 4-panel alternating Google primary color beanie dome (#4285F4, #EA4335, #FBBC04, #34A853)
         - Matte soft fabric (roughness 0.78) with subtle panel puff & stitched seam piping
         - Curved forward visor brim (#1A73E8) with crisp white stitched outer edge trim
         - White inner headband rim & sweatband lip resting flush at Z = 0.000
         - Bright Google Yellow (#FBBC04) top crown button + polished chrome axle pin at (0, 0, 0.165)
      2. Noogler_Propeller @ Blender (0.000, 0.000, 0.185) -> Three.js (0.000, 0.185, 0.000)
         - Centered at exact axle origin for wobble-free Three.js `rotation.y += dt * speed`
         - Sleek 2-blade tilted glossy plastic propeller (#FFFFFF w/ #FBBC04 & #34A853 tips, span ~0.24m)

Usage:
  blender --background --python scripts/blender/build_noogler_hat.py
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
OUT_DIR = PROJECT_ROOT / "public" / "assets" / "characters"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_GLB = OUT_DIR / "outfit_noogler_hat.glb"

QA_PREVIEW_PATH = Path(
    "/Users/davidyou/.gemini/antigravity/brain/a9682dfa-7d5f-428c-afd4-e62e35b1964e/previews/qa_noogler_hat.png"
)

# Iconic Google Noogler Palette (sRGB hex)
COL_GOOGLE_BLUE = "#4285F4"
COL_GOOGLE_RED = "#EA4335"
COL_GOOGLE_YELLOW = "#FBBC04"
COL_GOOGLE_GREEN = "#34A853"
COL_VISOR_BLUE = "#1A73E8"
COL_WHITE_TRIM = "#F8FAFC"
COL_PROP_WHITE = "#FFFFFF"
COL_SEAM_DARK = "#1E293B"
COL_CHROME = "#E8EEF5"

# Key Dimensions (meters)
DOME_RADIUS = 0.165
DOME_HEIGHT = 0.162
BUTTON_Z = 0.165
PROPELLER_Z = 0.185
PROPELLER_SPAN = 0.240  # -0.12m to +0.12m


# ---------------------------------------------------------------------------
# Color & Material Helpers (Blender 5.3.0 Principled BSDF)
# ---------------------------------------------------------------------------

def srgb_channel_to_linear(c: float) -> float:
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def hex_to_linear(hex_str: str) -> tuple[float, float, float, float]:
    h = hex_str.lstrip("#")
    r = srgb_channel_to_linear(int(h[0:2], 16) / 255.0)
    g = srgb_channel_to_linear(int(h[2:4], 16) / 255.0)
    b = srgb_channel_to_linear(int(h[4:6], 16) / 255.0)
    return (r, g, b, 1.0)


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
    roughness: float = 0.78,
    specular: float = 0.30,
    coat: float = 0.0,
    coat_roughness: float = 0.15,
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
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = specular
    if "Coat Weight" in bsdf.inputs:
        bsdf.inputs["Coat Weight"].default_value = coat
        bsdf.inputs["Coat Roughness"].default_value = coat_roughness
    if "Emission Strength" in bsdf.inputs:
        bsdf.inputs["Emission Strength"].default_value = 0.0

    mat.blend_method = "OPAQUE"
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "DITHERED"
    mat.use_backface_culling = False
    return mat


def set_smooth(obj: bpy.types.Object, smooth: bool = True) -> None:
    if obj.type != "MESH":
        return
    mesh = obj.data
    n = len(mesh.polygons)
    if n > 0:
        mesh.polygons.foreach_set("use_smooth", [smooth] * n)
    mesh.update()


# ---------------------------------------------------------------------------
# BMesh Geometry Builders (Multi-Material into Unified BMesh)
# ---------------------------------------------------------------------------

def append_lathed_to_bm(
    bm: bmesh.types.BMesh,
    profile_rz: list[tuple[float, float]],
    segments: int,
    mat_idx: int,
    cap_bottom: bool = False,
    cap_top: bool = False,
    z_offset: float = 0.0,
) -> None:
    rings = []
    for r, z in profile_rz:
        zz = z + z_offset
        if r <= 1e-6:
            rings.append([bm.verts.new((0.0, 0.0, zz))])
        else:
            ring = []
            for i in range(segments):
                ang = (2.0 * math.pi * i) / segments
                ring.append(bm.verts.new((r * math.cos(ang), r * math.sin(ang), zz)))
            rings.append(ring)

    for idx in range(len(rings) - 1):
        r0 = rings[idx]
        r1 = rings[idx + 1]
        if len(r0) == 1 and len(r1) > 1:
            for i in range(segments):
                j = (i + 1) % segments
                f = bm.faces.new((r0[0], r1[j], r1[i]))
                f.material_index = mat_idx
                f.smooth = True
        elif len(r0) > 1 and len(r1) == 1:
            for i in range(segments):
                j = (i + 1) % segments
                f = bm.faces.new((r0[i], r0[j], r1[0]))
                f.material_index = mat_idx
                f.smooth = True
        elif len(r0) > 1 and len(r1) > 1:
            for i in range(segments):
                j = (i + 1) % segments
                f = bm.faces.new((r0[i], r0[j], r1[j], r1[i]))
                f.material_index = mat_idx
                f.smooth = True

    if cap_bottom and len(rings[0]) > 1:
        f = bm.faces.new(list(reversed(rings[0])))
        f.material_index = mat_idx
        f.smooth = False
    if cap_top and len(rings[-1]) > 1:
        f = bm.faces.new(rings[-1])
        f.material_index = mat_idx
        f.smooth = False


def build_cap_dome_and_headband(
    bm: bmesh.types.BMesh,
    panel_mat_indices: list[int],
    white_mat_idx: int,
    seam_mat_idx: int,
) -> None:
    """
    Build the 4-panel colorful beanie dome + subtle pillowy panel puff + white inner
    headband trim resting cleanly at Z = 0.000.

    Quadrant layout (looking from front +Y toward -Y):
      0: [0..90 deg]   (+X, +Y) Front-Left (wearer's right) -> Google Blue (#4285F4)
      1: [90..180 deg] (-X, +Y) Front-Right (wearer's left) -> Google Red (#EA4335)
      2: [180..270]    (-X, -Y) Back-Right                  -> Google Yellow (#FBBC04)
      3: [270..360]    (+X, -Y) Back-Left                   -> Google Green (#34A853)
    """
    segs_per_panel = 8
    total_segs = segs_per_panel * 4  # 32 circumferential segments
    lat_rings = 11  # from base rim up to top button collar

    # Smooth beanie dome profile: cozy straight-ish lower band then rounded dome
    # Z goes from 0.012 (above white base piping) up to DOME_HEIGHT (0.162)
    outer_rings: list[list[bmesh.types.BMVert]] = []

    for r_i in range(lat_rings + 1):
        t = r_i / lat_rings  # 0 at lower cap band, 1 at crown pole
        phi = t * (math.pi * 0.5)  # 0 at equator, pi/2 at pole

        # Slightly fuller beanie shoulder curve than a pure hemisphere
        cos_p = math.cos(phi)
        sin_p = math.sin(phi)
        # Mild fullness bulge in mid-height
        bulge = 1.0 + 0.045 * math.sin(t * math.pi)
        base_r = DOME_RADIUS * (cos_p ** 0.88) * bulge
        base_z = 0.011 + (DOME_HEIGHT - 0.011) * (sin_p ** 0.90)

        if r_i == lat_rings:
            # Close right under the yellow top button (radius 0.012)
            base_r = 0.012
            base_z = DOME_HEIGHT

        ring = []
        for s_i in range(total_segs):
            ang = (2.0 * math.pi * s_i) / total_segs
            # Subtle pillow puff inside each 90-degree panel, crisp tuck at panel seams
            panel_u = (s_i % segs_per_panel) / segs_per_panel  # 0 at seam, 0.5 mid-panel
            puff = 1.0 + 0.014 * math.sin(panel_u * math.pi) * math.sin(t * math.pi)
            rr = base_r * puff
            # Subtle seam tuck right on the 4 meridian seams
            if s_i % segs_per_panel == 0 and 0 < r_i < lat_rings:
                rr *= 0.992
            ring.append(bm.verts.new((rr * math.cos(ang), rr * math.sin(ang), base_z)))
        outer_rings.append(ring)

    # Create 4-panel dome faces
    for r_i in range(lat_rings):
        r0 = outer_rings[r_i]
        r1 = outer_rings[r_i + 1]
        for s_i in range(total_segs):
            s_next = (s_i + 1) % total_segs
            panel_idx = s_i // segs_per_panel
            f = bm.faces.new((r0[s_i], r0[s_next], r1[s_next], r1[s_i]))
            f.material_index = panel_mat_indices[panel_idx]
            f.smooth = True

    # Cap crown pole under button
    pole_v = bm.verts.new((0.0, 0.0, DOME_HEIGHT + 0.002))
    top_ring = outer_rings[-1]
    for s_i in range(total_segs):
        s_next = (s_i + 1) % total_segs
        panel_idx = s_i // segs_per_panel
        f = bm.faces.new((top_ring[s_i], top_ring[s_next], pole_v))
        f.material_index = panel_mat_indices[panel_idx]
        f.smooth = True

    # White base piping & inner headband trim (sits strictly at Z = 0.000!)
    # Profile wraps smoothly from outer dome bottom (r=DOME_RADIUS, z=0.011)
    # around a rounded white piping lip down to Z=0.000, then up inside as a clean headband.
    headband_profile = [
        (DOME_RADIUS + 0.001, 0.011),
        (DOME_RADIUS + 0.003, 0.007),
        (DOME_RADIUS + 0.002, 0.0025),
        (DOME_RADIUS - 0.003, 0.000),  # Exact Z = 0.000 contact ring!
        (DOME_RADIUS - 0.010, 0.000),  # Flat bottom rim resting cleanly at Z = 0.000
        (DOME_RADIUS - 0.014, 0.004),
        (DOME_RADIUS - 0.013, 0.032),  # Inner white sweatband lining
        (DOME_RADIUS - 0.018, 0.036),
        (0.0, 0.042),                  # Clean closed interior underside cap (never hollow!)
    ]
    append_lathed_to_bm(
        bm,
        headband_profile,
        segments=total_segs,
        mat_idx=white_mat_idx,
        cap_bottom=False,
        cap_top=False,
    )

    # Subtle raised fabric seam ribs along the 4 panel meridians (0, 90, 180, 270 deg)
    # Gives tactile baseball-cap / beanie panel definition that reads clearly in studio lighting
    rib_half_w = 0.0026
    rib_lift = 0.0016
    for q in range(4):
        ang = q * (math.pi * 0.5)
        cos_a = math.cos(ang)
        sin_a = math.sin(ang)
        tx = -sin_a
        ty = cos_a

        rib_rings = []
        for r_i in range(0, lat_rings):
            t = r_i / lat_rings
            phi = t * (math.pi * 0.5)
            bulge = 1.0 + 0.045 * math.sin(t * math.pi)
            rr = DOME_RADIUS * (math.cos(phi) ** 0.88) * bulge * 0.996
            zz = 0.011 + (DOME_HEIGHT - 0.011) * (math.sin(phi) ** 0.90)
            # Outward normal approx
            nr = math.cos(phi)
            nz = math.sin(phi)
            cx = rr * cos_a
            cy = rr * sin_a

            v_l = bm.verts.new((cx - tx * rib_half_w, cy - ty * rib_half_w, zz))
            v_c = bm.verts.new((cx + nr * cos_a * rib_lift, cy + nr * sin_a * rib_lift, zz + nz * rib_lift))
            v_r = bm.verts.new((cx + tx * rib_half_w, cy + ty * rib_half_w, zz))
            rib_rings.append((v_l, v_c, v_r))

        for i in range(len(rib_rings) - 1):
            l0, c0, r0 = rib_rings[i]
            l1, c1, r1 = rib_rings[i + 1]
            for quad in ((l0, c0, c1, l1), (c0, r0, r1, c1)):
                f = bm.faces.new(quad)
                f.material_index = seam_mat_idx
                f.smooth = True


def build_forward_visor(
    bm: bmesh.types.BMesh,
    visor_mat_idx: int,
    trim_mat_idx: int,
) -> None:
    """
    Build a crisp curved forward baseball-cap visor brim pointing along Blender +Y
    (which becomes Three.js -Z on export_yup=True).
    Features:
      - Smooth curved arch across X
      - Gentle downward pitch that stays strictly >= Z = 0.005 (never dips below Z = 0.000)
      - Crisp white stitched outer edge trim along the front curved perimeter
    """
    u_steps = 18  # angular sweep across front (-56 deg to +56 deg around +Y)
    v_steps = 6   # radial steps from cap root to visor tip

    max_ang = math.radians(56.0)
    visor_len = 0.125  # reaches out to Y ~ 0.285m
    thickness = 0.010

    top_grid: list[list[bmesh.types.BMVert]] = []
    bot_grid: list[list[bmesh.types.BMVert]] = []

    for v_i in range(v_steps + 1):
        vt = v_i / v_steps  # 0 at cap root, 1 at outer tip
        top_row = []
        bot_row = []

        for u_i in range(u_steps + 1):
            ut = (u_i / u_steps) * 2.0 - 1.0  # -1 (left) .. 0 (front center) .. +1 (right)
            theta = ut * max_ang  # 0 is straight +Y

            # Base circle on the cap (slightly tucked inside dome to ensure watertight junction)
            r_root = DOME_RADIUS - 0.007
            # Smooth bill protrusion: fullest in front (ut=0), tapers cleanly to 0 at corners (|ut|=1)
            bill_profile = math.cos(ut * math.pi * 0.5) ** 0.72
            protrusion = visor_len * bill_profile * vt

            # Slight horizontal flaring for classic cap bill silhouette
            x_root = r_root * math.sin(theta)
            y_root = r_root * math.cos(theta)
            x = x_root * (1.0 + 0.05 * vt * (1.0 - abs(ut) * 0.5))
            y = y_root + protrusion * (0.94 + 0.06 * math.cos(theta))

            # Classic curved cap arch: higher in the center, curving gently down at the sides
            # Keep minimum Z strictly >= 0.005 so hat base rim remains exact minZ = 0.000
            arch_z = 0.020 * (1.0 - ut * ut) * (0.35 + 0.65 * vt)
            pitch_z = -0.009 * vt
            z_mid = 0.015 + arch_z + pitch_z

            # Taper thickness slightly near the very front edge for crisp trim wrap
            half_t = 0.5 * thickness * (1.0 - 0.25 * (vt ** 2))
            top_row.append(bm.verts.new((x, y, z_mid + half_t)))
            bot_row.append(bm.verts.new((x, y, z_mid - half_t)))

        top_grid.append(top_row)
        bot_grid.append(bot_row)

    # Top and bottom visor faces (last radial strip gets white stitched accent border on top/edge)
    for v_i in range(v_steps):
        is_outer_stitch = (v_i == v_steps - 1)
        for u_i in range(u_steps):
            # Top surface
            f_top = bm.faces.new((
                top_grid[v_i][u_i],
                top_grid[v_i + 1][u_i],
                top_grid[v_i + 1][u_i + 1],
                top_grid[v_i][u_i + 1],
            ))
            f_top.material_index = trim_mat_idx if is_outer_stitch else visor_mat_idx
            f_top.smooth = True

            # Bottom surface (reversed winding for outward normal)
            f_bot = bm.faces.new((
                bot_grid[v_i][u_i],
                bot_grid[v_i][u_i + 1],
                bot_grid[v_i + 1][u_i + 1],
                bot_grid[v_i + 1][u_i],
            ))
            f_bot.material_index = trim_mat_idx if is_outer_stitch else visor_mat_idx
            f_bot.smooth = True

    # Rounded front outer edge lip (white stitched piping around the perimeter)
    edge_mid_row: list[bmesh.types.BMVert] = []
    for u_i in range(u_steps + 1):
        vt_top = top_grid[-1][u_i].co
        vt_bot = bot_grid[-1][u_i].co
        mid = 0.5 * (vt_top + vt_bot)
        # Push slightly outward along horizontal radial direction for crisp rounded piping
        out_dir = Vector((mid.x, mid.y, 0.0)).normalized()
        edge_mid_row.append(bm.verts.new(mid + out_dir * 0.0045))

    for u_i in range(u_steps):
        # Upper bevel of front edge
        f1 = bm.faces.new((
            top_grid[-1][u_i],
            edge_mid_row[u_i],
            edge_mid_row[u_i + 1],
            top_grid[-1][u_i + 1],
        ))
        f1.material_index = trim_mat_idx
        f1.smooth = True

        # Lower bevel of front edge
        f2 = bm.faces.new((
            edge_mid_row[u_i],
            bot_grid[-1][u_i],
            bot_grid[-1][u_i + 1],
            edge_mid_row[u_i + 1],
        ))
        f2.material_index = trim_mat_idx
        f2.smooth = True

    # Close back/root edge inside dome
    for u_i in range(u_steps):
        f_back = bm.faces.new((
            top_grid[0][u_i],
            top_grid[0][u_i + 1],
            bot_grid[0][u_i + 1],
            bot_grid[0][u_i],
        ))
        f_back.material_index = visor_mat_idx
        f_back.smooth = False


def build_top_button_and_axle(
    bm: bmesh.types.BMesh,
    yellow_mat_idx: int,
    chrome_mat_idx: int,
) -> None:
    """
    Build the bright Google Yellow (#FBBC04) top crown button at (0, 0, 0.165)
    and the polished chrome axle pin rising cleanly to support the spinning propeller
    at Z = 0.185.
    """
    # Yellow crown spinner button (centered around Z = 0.165)
    button_profile = [
        (0.022, 0.157),
        (0.024, 0.161),
        (0.023, 0.166),
        (0.019, 0.170),
        (0.012, 0.172),
        (0.000, 0.173),
    ]
    append_lathed_to_bm(
        bm,
        button_profile,
        segments=20,
        mat_idx=yellow_mat_idx,
        cap_bottom=True,
        cap_top=False,
    )

    # Polished chrome washer + vertical axle shaft rising to Z = 0.193
    axle_profile = [
        (0.011, 0.171),
        (0.011, 0.174),
        (0.0055, 0.175),
        (0.0055, 0.192),
        (0.0040, 0.194),
        (0.000, 0.1945),
    ]
    append_lathed_to_bm(
        bm,
        axle_profile,
        segments=16,
        mat_idx=chrome_mat_idx,
        cap_bottom=True,
        cap_top=False,
    )


def build_noogler_cap_object(mats: dict[str, bpy.types.Material]) -> bpy.types.Object:
    bm = bmesh.new()
    mat_list = [
        mats["blue"],       # 0
        mats["red"],        # 1
        mats["yellow"],     # 2
        mats["green"],      # 3
        mats["visor_blue"], # 4
        mats["white_trim"], # 5
        mats["seam"],       # 6
        mats["button_yel"], # 7
        mats["chrome"],     # 8
    ]

    build_cap_dome_and_headband(
        bm,
        panel_mat_indices=[0, 1, 2, 3],
        white_mat_idx=5,
        seam_mat_idx=6,
    )
    build_forward_visor(
        bm,
        visor_mat_idx=4,
        trim_mat_idx=5,
    )
    build_top_button_and_axle(
        bm,
        yellow_mat_idx=7,
        chrome_mat_idx=8,
    )

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    mesh = bpy.data.meshes.new("Noogler_Cap")
    bm.to_mesh(mesh)
    bm.free()

    for m in mat_list:
        mesh.materials.append(m)

    obj = bpy.data.objects.new("Noogler_Cap", mesh)
    obj.location = Vector((0.0, 0.0, 0.0))
    bpy.context.scene.collection.objects.link(obj)
    return obj


def build_propeller_blade(
    bm: bmesh.types.BMesh,
    sign_x: float,
    white_mat_idx: int,
    tip_mat_idx: int,
) -> None:
    """
    Build one aerodynamic tilted plastic propeller blade extending from hub (|x|=0.011)
    out to tip (|x|=0.120) in local propeller space (centered at Z=0).
    Uses opposite pitch twist per blade (symmetric rotation around Z) so it spins cleanly!
    """
    half_span = PROPELLER_SPAN * 0.5  # 0.120m
    # Radial stations: (r_dist, half_chord_y, half_thick_z, pitch_deg)
    stations = [
        (0.010, 0.0075, 0.0038, 12.0),
        (0.028, 0.0110, 0.0034, 20.0),
        (0.056, 0.0165, 0.0030, 22.0),
        (0.084, 0.0205, 0.0026, 20.0),
        (0.104, 0.0195, 0.0023, 18.0),
        (0.115, 0.0145, 0.0020, 17.0),
        (0.120, 0.0065, 0.0015, 16.0),
    ]

    # Rounded airfoil-like 8-point cross-section around (y, z)
    sec_angles = [i * (2.0 * math.pi / 8) for i in range(8)]
    rings: list[list[bmesh.types.BMVert]] = []

    for r_dist, hc, ht, pitch_deg in stations:
        # Rotational symmetry: blade +X and blade -X have same helical pitch
        # When rotating around +Z, a point on -X is rotated 180 deg around Z from +X
        pitch = math.radians(pitch_deg)
        cp = math.cos(pitch)
        sp = math.sin(pitch)
        ring = []
        for a in sec_angles:
            ly = hc * math.cos(a)
            lz = ht * math.sin(a)
            # Tilt cross-section around local X
            ry = ly * cp - lz * sp
            rz = ly * sp + lz * cp
            # Apply 180-deg Z rotation if sign_x < 0 so blades are exact 2-fold symmetric!
            wx = sign_x * r_dist
            wy = sign_x * ry
            wz = rz
            ring.append(bm.verts.new((wx, wy, wz)))
        rings.append(ring)

    # Connect station rings; outer 2 bands get colorful dipped tip accent!
    n_sec = len(sec_angles)
    for s_i in range(len(rings) - 1):
        r0 = rings[s_i]
        r1 = rings[s_i + 1]
        is_tip = s_i >= len(rings) - 3
        mat_idx = tip_mat_idx if is_tip else white_mat_idx
        for k in range(n_sec):
            kn = (k + 1) % n_sec
            if sign_x > 0:
                f = bm.faces.new((r0[k], r1[k], r1[kn], r0[kn]))
            else:
                f = bm.faces.new((r0[k], r0[kn], r1[kn], r1[k]))
            f.material_index = mat_idx
            f.smooth = True

    # Cap rounded blade tip
    tip_ring = rings[-1]
    tip_center = bm.verts.new((sign_x * (half_span + 0.0015), 0.0, 0.0))
    for k in range(n_sec):
        kn = (k + 1) % n_sec
        if sign_x > 0:
            f = bm.faces.new((tip_ring[k], tip_center, tip_ring[kn]))
        else:
            f = bm.faces.new((tip_ring[k], tip_ring[kn], tip_center))
        f.material_index = tip_mat_idx
        f.smooth = True


def build_noogler_propeller_object(mats: dict[str, bpy.types.Material]) -> bpy.types.Object:
    """
    Build `Noogler_Propeller` centered at exact Blender origin (0.0, 0.0, 0.185)
    so Three.js receives node `Noogler_Propeller` at (0.0, 0.185, 0.0) and can spin
    `Noogler_Propeller.rotation.y += dt * speed` with zero wobble.
    """
    bm = bmesh.new()
    mat_list = [
        mats["prop_white"],  # 0
        mats["prop_yellow"], # 1
        mats["prop_green"],  # 2
        mats["prop_red"],    # 3
        mats["chrome"],      # 4
    ]

    # Central glossy white propeller hub collar around local Z = 0
    hub_profile = [
        (0.011, -0.0065),
        (0.015, -0.0050),
        (0.015,  0.0050),
        (0.012,  0.0070),
        (0.000,  0.0075),
    ]
    append_lathed_to_bm(
        bm,
        hub_profile,
        segments=20,
        mat_idx=0,
        cap_bottom=True,
        cap_top=False,
    )

    # Playful bright Google Red top spinner nut / cap on top of the hub
    cap_profile = [
        (0.0095, 0.0065),
        (0.0105, 0.0100),
        (0.0085, 0.0145),
        (0.0045, 0.0170),
        (0.000,  0.0178),
    ]
    append_lathed_to_bm(
        bm,
        cap_profile,
        segments=16,
        mat_idx=3,
        cap_bottom=False,
        cap_top=False,
    )

    # 2 symmetric tilted blades: +X with Google Yellow tip, -X with Google Green tip
    build_propeller_blade(bm, sign_x=+1.0, white_mat_idx=0, tip_mat_idx=1)
    build_propeller_blade(bm, sign_x=-1.0, white_mat_idx=0, tip_mat_idx=2)

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    mesh = bpy.data.meshes.new("Noogler_Propeller")
    bm.to_mesh(mesh)
    bm.free()

    for m in mat_list:
        mesh.materials.append(m)

    obj = bpy.data.objects.new("Noogler_Propeller", mesh)
    obj.location = Vector((0.0, 0.0, PROPELLER_Z))
    bpy.context.scene.collection.objects.link(obj)
    return obj


# ---------------------------------------------------------------------------
# Measurement & GLB Inspection
# ---------------------------------------------------------------------------

def world_bbox(objs: list[bpy.types.Object]) -> tuple[Vector, Vector]:
    mins = Vector((1e9, 1e9, 1e9))
    maxs = Vector((-1e9, -1e9, -1e9))
    for obj in objs:
        if obj.type != "MESH":
            continue
        mw = obj.matrix_world
        for v in obj.data.vertices:
            p = mw @ v.co
            mins.x = min(mins.x, p.x)
            mins.y = min(mins.y, p.y)
            mins.z = min(mins.z, p.z)
            maxs.x = max(maxs.x, p.x)
            maxs.y = max(maxs.y, p.y)
            maxs.z = max(maxs.z, p.z)
    return mins, maxs


def count_tris(objs: list[bpy.types.Object]) -> int:
    total = 0
    for obj in objs:
        if obj.type != "MESH":
            continue
        mesh = obj.data
        mesh.calc_loop_triangles()
        total += len(mesh.loop_triangles)
    return total


def inspect_glb(glb_path: Path) -> dict:
    raw = glb_path.read_bytes()
    magic, version, length = struct.unpack_from("<4sII", raw, 0)
    assert magic == b"glTF", f"Invalid GLB magic: {magic}"
    chunk_len, chunk_type = struct.unpack_from("<I4s", raw, 12)
    assert chunk_type == b"JSON", f"Expected JSON chunk, got {chunk_type}"
    gltf = json.loads(raw[20 : 20 + chunk_len].decode("utf-8"))

    exts_used = gltf.get("extensionsUsed", [])
    exts_req = gltf.get("extensionsRequired", [])
    has_draco = (
        "KHR_draco_mesh_compression" in exts_used
        or "KHR_draco_mesh_compression" in exts_req
    )

    nodes = {}
    for n in gltf.get("nodes", []):
        name = n.get("name", "<unnamed>")
        nodes[name] = {
            "translation": n.get("translation", [0.0, 0.0, 0.0]),
            "rotation": n.get("rotation", [0.0, 0.0, 0.0, 1.0]),
            "scale": n.get("scale", [1.0, 1.0, 1.0]),
        }

    return {
        "size_bytes": len(raw),
        "size_kb": len(raw) / 1024.0,
        "has_draco": has_draco,
        "extensions_used": exts_used,
        "nodes": nodes,
    }


# ---------------------------------------------------------------------------
# Studio EEVEE 2x2 Multi-Angle QA Contact Sheet Renderer
# ---------------------------------------------------------------------------

FONT_5X7 = {
    "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    "B": ["11110", "10001", "10001", "11110", "10001", "10001", "11110"],
    "C": ["01110", "10001", "10000", "10000", "10000", "10001", "01110"],
    "D": ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    "E": ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    "F": ["11111", "10000", "10000", "11110", "10000", "10000", "10000"],
    "G": ["01110", "10001", "10000", "10111", "10001", "10001", "01110"],
    "H": ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
    "I": ["01110", "00100", "00100", "00100", "00100", "00100", "01110"],
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
    "9": ["01110", "10001", "10001", "01111", "00001", "00001", "01110"],
    ".": ["00000", "00000", "00000", "00000", "00000", "01100", "01100"],
    "-": ["00000", "00000", "00000", "11111", "00000", "00000", "00000"],
    "|": ["00100", "00100", "00100", "00100", "00100", "00100", "00100"],
    "/": ["00001", "00010", "00010", "00100", "01000", "01000", "10000"],
    "+": ["00000", "00100", "00100", "11111", "00100", "00100", "00000"],
    "=": ["00000", "00000", "11111", "00000", "11111", "00000", "00000"],
    " ": ["00000", "00000", "00000", "00000", "00000", "00000", "00000"],
}


def draw_label_text(
    img: np.ndarray,
    text: str,
    x0: int,
    y0: int,
    scale: int = 2,
    color: tuple = (0.95, 0.97, 1.0),
) -> None:
    h, w, _ = img.shape
    cx = x0
    for ch in text.upper():
        glyph = FONT_5X7.get(ch, FONT_5X7[" "])
        for r_i, row in enumerate(glyph):
            for c_i, bit in enumerate(row):
                if bit == "1":
                    py0 = max(0, y0 + r_i * scale)
                    py1 = min(h, py0 + scale)
                    px0 = max(0, cx + c_i * scale)
                    px1 = min(w, px0 + scale)
                    if py1 > py0 and px1 > px0:
                        img[py0:py1, px0:px1, :3] = color
        cx += 6 * scale


def setup_studio_eevee(res_x: int = 640, res_y: int = 512, samples: int = 24) -> None:
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = samples
    scene.render.resolution_x = res_x
    scene.render.resolution_y = res_y
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    try:
        scene.view_settings.view_transform = "AgX"
        scene.view_settings.look = "AgX - Punchy"
    except Exception:
        scene.view_settings.view_transform = "Standard"
    scene.view_settings.exposure = 0.2

    world = bpy.data.worlds.new("StudioWorld")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs["Color"].default_value = (0.055, 0.068, 0.095, 1.0)
        bg.inputs["Strength"].default_value = 0.85

    # Clean matte studio turntable pedestal at Z = 0.000
    bm = bmesh.new()
    bmesh.ops.create_cone(
        bm,
        cap_ends=True,
        cap_tris=False,
        segments=48,
        radius1=0.45,
        radius2=0.45,
        depth=0.016,
    )
    for v in bm.verts:
        v.co.z -= 0.008
    floor_mesh = bpy.data.meshes.new("StudioFloor")
    bm.to_mesh(floor_mesh)
    bm.free()
    floor_mat = make_pbr_mat("StudioFloor", "#263040", metallic=0.08, roughness=0.58)
    floor_mesh.materials.append(floor_mat)
    floor_obj = bpy.data.objects.new("StudioFloor", floor_mesh)
    scene.collection.objects.link(floor_obj)
    set_smooth(floor_obj, smooth=True)

    # 3-Point Studio Area Lighting (front +Y is our hero side!)
    lights = [
        ("KeyLight", "AREA", (0.95, 1.15, 1.15), (math.radians(-50), 0.0, math.radians(-140)), 95.0, (1.0, 0.98, 0.94), 0.8),
        ("FillLight", "AREA", (-1.15, 0.75, 0.80), (math.radians(-62), 0.0, math.radians(125)), 55.0, (0.86, 0.92, 1.0), 1.0),
        ("RimLight", "AREA", (-0.15, -1.25, 1.05), (math.radians(56), 0.0, math.radians(-8)), 75.0, (0.92, 0.96, 1.0), 0.85),
    ]
    for name, ltype, loc, rot, energy, col, size in lights:
        ldata = bpy.data.lights.new(name=name, type=ltype)
        ldata.energy = energy
        ldata.color = col
        ldata.size = size
        lobj = bpy.data.objects.new(name=name, object_data=ldata)
        lobj.location = Vector(loc)
        lobj.rotation_euler = Euler(rot, "XYZ")
        scene.collection.objects.link(lobj)


def render_glb_angle(
    glb_path: Path,
    out_png: str,
    azim_deg: float,
    elev_deg: float,
    dist_mult: float = 3.25,
    res_x: int = 640,
    res_y: int = 512,
) -> np.ndarray:
    clear_scene()
    setup_studio_eevee(res_x=res_x, res_y=res_y, samples=24)

    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(glb_path))
    imported = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
    mins, maxs = world_bbox(imported)
    center = 0.5 * (mins + maxs)
    extent = maxs - mins
    radius = max(extent.length * 0.5, 0.14)

    cam_data = bpy.data.cameras.new("QACam")
    cam_data.lens = 52.0
    cam_obj = bpy.data.objects.new("QACam", cam_data)
    bpy.context.scene.collection.objects.link(cam_obj)
    bpy.context.scene.camera = cam_obj

    # azim_deg = 0 looks from +Y (straight at the front visor!)
    dist = radius * dist_mult
    target = Vector((center.x, center.y, center.z - extent.z * 0.04))
    az = math.radians(azim_deg)
    el = math.radians(elev_deg)
    cam_pos = target + Vector((
        dist * math.cos(el) * math.sin(az),
        dist * math.cos(el) * math.cos(az),
        dist * math.sin(el),
    ))
    cam_obj.location = cam_pos
    direction = (target - cam_pos).normalized()
    cam_obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()

    bpy.context.scene.render.filepath = out_png
    bpy.ops.render.render(write_still=True)

    img = bpy.data.images.load(out_png)
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    arr = px.reshape((h, w, 4))[::-1, :, :].copy()
    bpy.data.images.remove(img)
    return arr


def render_qa_sheet(glb_path: Path, tris: int, size_kb: float, dims: Vector, min_z: float) -> None:
    QA_PREVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
    panel_w, panel_h = 640, 512
    header_h = 46
    grid_w = panel_w * 2
    grid_h = header_h + panel_h * 2
    canvas = np.zeros((grid_h, grid_w, 4), dtype=np.float32)
    canvas[:, :, :3] = np.array([0.06, 0.08, 0.11], dtype=np.float32)
    canvas[:, :, 3] = 1.0

    header = (
        f"NOOGLER PROPELLER HAT QA | {tris} TRIS | {size_kb:.1f} KB | "
        f"MINZ={min_z:.3f}M | DRACO OFF"
    )
    draw_label_text(canvas, header, x0=20, y0=16, scale=2, color=(0.96, 0.98, 1.0))

    views = [
        ("1. HERO FRONT 3/4 (+Y VISOR)", 38.0, 22.0, 3.15),
        ("2. REAR 3/4 (YELLOW/GREEN)", -142.0, 24.0, 3.15),
        ("3. SIDE PROFILE (Z=0 BASE)", 90.0, 10.0, 3.25),
        ("4. TOP 3/4 (4 PANELS + PROP)", 25.0, 62.0, 3.05),
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        for idx, (title, az, el, dm) in enumerate(views):
            tmp_png = os.path.join(tmpdir, f"view_{idx}.png")
            panel = render_glb_angle(
                glb_path, tmp_png, azim_deg=az, elev_deg=el, dist_mult=dm,
                res_x=panel_w, res_y=panel_h,
            )
            bar_h = 36
            panel[panel_h - bar_h :, :, :3] = panel[panel_h - bar_h :, :, :3] * 0.25 + 0.04
            draw_label_text(panel, title, x0=16, y0=panel_h - 24, scale=2, color=(0.95, 0.98, 1.0))

            row = idx // 2
            col = idx % 2
            y0 = header_h + row * panel_h
            x0 = col * panel_w
            canvas[y0 : y0 + panel_h, x0 : x0 + panel_w, :] = panel

    canvas[header_h - 1 : header_h + 1, :, :3] = 0.24
    canvas[header_h + panel_h - 1 : header_h + panel_h + 1, :, :3] = 0.24
    canvas[header_h:, panel_w - 1 : panel_w + 1, :3] = 0.24

    clear_scene()
    out_img = bpy.data.images.new("QA_NooglerHat", width=grid_w, height=grid_h, alpha=True)
    out_img.colorspace_settings.name = "sRGB"
    flipped = np.ascontiguousarray(canvas[::-1, :, :], dtype=np.float32)
    out_img.pixels.foreach_set(flipped.ravel())
    out_img.filepath_raw = str(QA_PREVIEW_PATH)
    out_img.file_format = "PNG"
    out_img.save()
    print(f"  [QA] Saved 2x2 studio EEVEE preview -> {QA_PREVIEW_PATH}")


# ---------------------------------------------------------------------------
# Main Entrypoint
# ---------------------------------------------------------------------------

def main() -> int:
    clear_scene()

    # Create PBR materials
    mats = {
        "blue": make_pbr_mat("Mat_Noogler_Blue", COL_GOOGLE_BLUE, metallic=0.0, roughness=0.78, specular=0.25),
        "red": make_pbr_mat("Mat_Noogler_Red", COL_GOOGLE_RED, metallic=0.0, roughness=0.78, specular=0.25),
        "yellow": make_pbr_mat("Mat_Noogler_Yellow", COL_GOOGLE_YELLOW, metallic=0.0, roughness=0.78, specular=0.25),
        "green": make_pbr_mat("Mat_Noogler_Green", COL_GOOGLE_GREEN, metallic=0.0, roughness=0.78, specular=0.25),
        "visor_blue": make_pbr_mat("Mat_Noogler_VisorBlue", COL_VISOR_BLUE, metallic=0.0, roughness=0.72, specular=0.30),
        "white_trim": make_pbr_mat("Mat_Noogler_WhiteTrim", COL_WHITE_TRIM, metallic=0.0, roughness=0.76, specular=0.25),
        "seam": make_pbr_mat("Mat_Noogler_Seam", COL_SEAM_DARK, metallic=0.0, roughness=0.82, specular=0.20),
        "button_yel": make_pbr_mat("Mat_Noogler_ButtonYellow", COL_GOOGLE_YELLOW, metallic=0.0, roughness=0.40, specular=0.45, coat=0.25),
        "chrome": make_pbr_mat("Mat_Noogler_Chrome", COL_CHROME, metallic=0.95, roughness=0.14, specular=0.70),
        "prop_white": make_pbr_mat("Mat_Propeller_White", COL_PROP_WHITE, metallic=0.0, roughness=0.24, specular=0.55, coat=0.45),
        "prop_yellow": make_pbr_mat("Mat_Propeller_Yellow", COL_GOOGLE_YELLOW, metallic=0.0, roughness=0.24, specular=0.55, coat=0.45),
        "prop_green": make_pbr_mat("Mat_Propeller_Green", COL_GOOGLE_GREEN, metallic=0.0, roughness=0.24, specular=0.55, coat=0.45),
        "prop_red": make_pbr_mat("Mat_Propeller_Red", COL_GOOGLE_RED, metallic=0.0, roughness=0.24, specular=0.55, coat=0.45),
    }

    cap_obj = build_noogler_cap_object(mats)
    prop_obj = build_noogler_propeller_object(mats)

    bpy.context.view_layer.update()
    objs = [cap_obj, prop_obj]
    mins, maxs = world_bbox(objs)
    dims = maxs - mins
    tris = count_tris(objs)

    # Export GLB with ZERO Draco and Y-up (Blender +Y -> Three.js -Z)
    bpy.ops.export_scene.gltf(
        filepath=str(OUT_GLB),
        export_format="GLB",
        export_yup=True,
        export_draco_mesh_compression_enable=False,
        export_apply=True,
        export_materials="EXPORT",
        export_normals=True,
        export_texcoords=False,
    )

    info = inspect_glb(OUT_GLB)

    print("=" * 84)
    print("Workspace Royale — Noogler Propeller Hat GLB Build Summary")
    print("=" * 84)
    print(f"  Output GLB : {OUT_GLB}")
    print(f"  File Size  : {info['size_kb']:.2f} KB ({info['size_bytes']} bytes) [limit < 120 KB]")
    print(f"  Draco      : {'ENABLED (ERROR!)' if info['has_draco'] else 'DISABLED (ZERO Draco)'}")
    print(f"  Tri Count  : {tris} tris")
    print(f"  Blender BB : min=({mins.x:+.4f}, {mins.y:+.4f}, {mins.z:+.4f}) "
          f"max=({maxs.x:+.4f}, {maxs.y:+.4f}, {maxs.z:+.4f})")
    print(f"  Dimensions : {dims.x:.3f}m (X) x {dims.y:.3f}m (Y/fwd) x {dims.z:.3f}m (Z/up)")
    print(f"  Exact minZ : {mins.z:.6f} m")
    print("  Three.js (Y-Up glTF) Node Local Coordinates:")
    for node_name, ndata in info["nodes"].items():
        t = ndata["translation"]
        print(f"    - {node_name:<18}: pos=({t[0]:+.4f}, {t[1]:+.4f}, {t[2]:+.4f}) "
              f"rot={ndata['rotation']} scale={ndata['scale']}")
    print("=" * 84)

    assert not info["has_draco"], "Draco compression must be disabled!"
    assert info["size_kb"] < 120.0, f"GLB exceeds 120 KB limit: {info['size_kb']:.2f} KB"
    assert abs(mins.z) < 1e-5, f"Expected exact minZ=0.000, got {mins.z:.6f}"
    assert "Noogler_Cap" in info["nodes"], "Missing Noogler_Cap node in GLB!"
    assert "Noogler_Propeller" in info["nodes"], "Missing Noogler_Propeller node in GLB!"

    render_qa_sheet(OUT_GLB, tris=tris, size_kb=info["size_kb"], dims=dims, min_z=mins.z)
    return 0


if __name__ == "__main__":
    sys.exit(main())

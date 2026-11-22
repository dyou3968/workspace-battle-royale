"""
Workspace Royale — Utilities, Supply Drop & Sky-Drop Glider Blender 5.3.0 Asset Generator
========================================================================================
Generates 9 high-fidelity beveled PBR `.glb` assets into `public/assets/utilities/`:
  1. item_shield_cell.glb     — Compact tactical bevel-capped shield canister w/ glass viewport & glowing cyan core
  2. item_shield_jug.glb      — Sculpted ergonomic Aegis Shield Jug w/ handle, ribbed base, glass tank & cyan liquid core
  3. item_medkit.glb          — Hinged rounded/beveled Field Medkit trauma case w/ latches, handle & red/white cross stencil
  4. item_mana_elixir.glb     — Futuristic cylindrical laboratory Mana flask w/ anodized cap, metal ribs & violet core
  5. item_hardlight_cover.glb — Beveled hexagonal portable Hard-Light Cover emitter disc w/ cyan lens & dual grip rails
  6. item_impulse_booster.glb — Compact dual-nozzle turbine thruster pack w/ gold/amber exhaust rings, intakes & trigger
  7. prop_supply_drop.glb     — Reinforced tactical Supply Drop crate w/ Google bumpers, stencils, beacon & rigged canopy
  8. prop_glider.glb          — Aerodynamic multi-ribbed swept tactical wing glider w/ 4-color trim & twin hand-grips
  9. prop_loot_chest.glb      — Beveled PBR Googleplex Tactical Loot Chest w/ rear-hinged ChestLid & RarityAccent trim

Usage:
  blender --background --python scripts/blender/build_utilities.py
"""

import math
import os
import sys
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
OUT_DIR = PROJECT_ROOT / "public" / "assets" / "utilities"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Google Workspace & Tactical Palette (sRGB hex)
COL_GOOGLE_BLUE = "#4285F4"
COL_GOOGLE_RED = "#EA4335"
COL_GOOGLE_YELLOW = "#FBBC04"
COL_GOOGLE_GREEN = "#34A853"

COL_GUNMETAL = "#2B313B"
COL_DARK_SLATE = "#1D222B"
COL_RUBBER = "#16191F"
COL_TITANIUM = "#8B95A5"
COL_BRUSHED_STEEL = "#B8C1CE"
COL_SATIN_WHITE = "#ECEFF4"
COL_LIGHT_ARMOR = "#CBD5E1"
COL_COBALT_ANODIZED = "#1D5FD6"
COL_CYAN_CORE = "#06D6F2"
COL_CYAN_BRIGHT = "#7DF9FF"
COL_CYAN_GLASS = "#A5F3FC"
COL_VIOLET_CORE = "#9333EA"
COL_VIOLET_BRIGHT = "#E879F9"
COL_VIOLET_GLASS = "#DDD6FE"
COL_VIOLET_ANODIZED = "#5B21B6"
COL_AMBER_GLOW = "#FFB300"
COL_AMBER_HOT = "#FFE066"
COL_CRIMSON = "#D93025"


# ---------------------------------------------------------------------------
# Color & Material Utilities (Blender 5.3.0 Principled BSDF)
# ---------------------------------------------------------------------------

def srgb_channel_to_linear(c: float) -> float:
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def hex_to_srgb(hex_str: str) -> tuple:
    h = hex_str.lstrip("#")
    return (
        int(h[0:2], 16) / 255.0,
        int(h[2:4], 16) / 255.0,
        int(h[4:6], 16) / 255.0,
    )


def hex_to_linear(hex_str: str) -> tuple:
    r, g, b = hex_to_srgb(hex_str)
    return (
        srgb_channel_to_linear(r),
        srgb_channel_to_linear(g),
        srgb_channel_to_linear(b),
        1.0,
    )


def clear_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    # Ensure a clean scene collection exists
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
    roughness: float = 0.5,
    specular: float = 0.5,
    coat: float = 0.0,
    coat_roughness: float = 0.1,
    emission_hex: str | None = None,
    emission_strength: float = 0.0,
    alpha: float = 1.0,
    ior: float = 1.45,
    backface_cull: bool = False,
) -> bpy.types.Material:
    mat = bpy.data.materials.new(name=name)
    if mat.node_tree is None:
        mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    if bsdf is None:
        nt.nodes.clear()
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    bsdf.inputs["Base Color"].default_value = hex_to_linear(hex_color)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["IOR"].default_value = ior
    bsdf.inputs["Specular IOR Level"].default_value = specular
    bsdf.inputs["Alpha"].default_value = alpha
    if "Coat Weight" in bsdf.inputs:
        bsdf.inputs["Coat Weight"].default_value = coat
    if "Coat Roughness" in bsdf.inputs:
        bsdf.inputs["Coat Roughness"].default_value = coat_roughness

    if emission_hex is not None and emission_strength > 0.0:
        bsdf.inputs["Emission Color"].default_value = hex_to_linear(emission_hex)
        bsdf.inputs["Emission Strength"].default_value = emission_strength
    else:
        bsdf.inputs["Emission Strength"].default_value = 0.0

    if alpha < 0.999:
        mat.blend_method = "BLEND"
        if hasattr(mat, "surface_render_method"):
            mat.surface_render_method = "BLENDED"
        mat.use_backface_culling = backface_cull
    else:
        mat.blend_method = "OPAQUE"
        if hasattr(mat, "surface_render_method"):
            mat.surface_render_method = "DITHERED"
        mat.use_backface_culling = False

    return mat


def make_textured_pbr_mat(
    name: str,
    rgba_top_down_srgb: np.ndarray,
    metallic: float = 0.0,
    roughness: float = 0.42,
    specular: float = 0.5,
    coat: float = 0.1,
) -> bpy.types.Material:
    """Create a PBR material with a packed procedural numpy sRGB image texture.
    rgba_top_down_srgb has shape (H, W, 4), float32 in [0, 1], row 0 = top of image.
    """
    h, w, _ = rgba_top_down_srgb.shape
    img = bpy.data.images.new(name=f"{name}_Tex", width=w, height=h, alpha=True)
    img.colorspace_settings.name = "sRGB"
    # Blender image pixels are bottom-to-top
    flipped = np.ascontiguousarray(rgba_top_down_srgb[::-1, :, :], dtype=np.float32)
    img.pixels.foreach_set(flipped.ravel())
    img.pack()

    mat = bpy.data.materials.new(name=name)
    if mat.node_tree is None:
        mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    tex_node = nt.nodes.new("ShaderNodeTexImage")
    tex_node.image = img
    tex_node.extension = "EXTEND"
    nt.links.new(tex_node.outputs["Color"], bsdf.inputs["Base Color"])

    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Specular IOR Level"].default_value = specular
    bsdf.inputs["Alpha"].default_value = 1.0
    if "Coat Weight" in bsdf.inputs:
        bsdf.inputs["Coat Weight"].default_value = coat

    mat.blend_method = "OPAQUE"
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "DITHERED"
    return mat


# ---------------------------------------------------------------------------
# Procedural Numpy Bitmap Font & Stencil Texture Generators
# ---------------------------------------------------------------------------

# Clean 5x7 uppercase stencil bitmap font
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
    "K": ["10001", "10010", "10100", "11000", "10100", "10010", "10001"],
    "L": ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
    "M": ["10001", "11011", "10101", "10101", "10001", "10001", "10001"],
    "N": ["10001", "11001", "10101", "10011", "10001", "10001", "10001"],
    "O": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    "P": ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    "S": ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    "T": ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
    "U": ["10001", "10001", "10001", "10001", "10001", "10001", "01110"],
    "V": ["10001", "10001", "10001", "10001", "10001", "01010", "00100"],
    "W": ["10001", "10001", "10001", "10101", "10101", "11011", "10001"],
    "X": ["10001", "10001", "01010", "00100", "01010", "10001", "10001"],
    "Y": ["10001", "10001", "01010", "00100", "00100", "00100", "00100"],
    "0": ["01110", "10011", "10101", "10101", "11001", "10001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00001", "00110", "01000", "10000", "11111"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "-": ["00000", "00000", "00000", "11111", "00000", "00000", "00000"],
    " ": ["00000", "00000", "00000", "00000", "00000", "00000", "00000"],
}


def draw_text(
    img: np.ndarray,
    text: str,
    cx: int,
    cy: int,
    scale: int,
    color_rgb: tuple,
    spacing: int = 1,
) -> None:
    """Draw crisp block stencil text centered at (cx, cy)."""
    h, w, _ = img.shape
    char_w = 5 * scale
    gap = spacing * scale
    total_w = len(text) * char_w + max(0, len(text) - 1) * gap
    total_h = 7 * scale
    x0 = cx - total_w // 2
    y0 = cy - total_h // 2

    for idx, ch in enumerate(text.upper()):
        glyph = FONT_5X7.get(ch, FONT_5X7[" "])
        gx = x0 + idx * (char_w + gap)
        for row_i, row_str in enumerate(glyph):
            for col_i, bit in enumerate(row_str):
                if bit == "1":
                    px0 = max(0, gx + col_i * scale)
                    px1 = min(w, px0 + scale)
                    py0 = max(0, y0 + row_i * scale)
                    py1 = min(h, py0 + scale)
                    if px1 > px0 and py1 > py0:
                        img[py0:py1, px0:px1, :3] = color_rgb


def build_medkit_texture(size: int = 512) -> np.ndarray:
    """Generate crisp clinical white & medical red trauma case face texture."""
    img = np.ones((size, size, 4), dtype=np.float32)
    yy, xx = np.mgrid[0:size, 0:size]
    u = xx / float(size)
    v = yy / float(size)

    # Subtle satin off-white base with delicate panel shading
    base = np.array([0.94, 0.95, 0.97], dtype=np.float32)
    vignette = 1.0 - 0.05 * ((u - 0.5) ** 2 + (v - 0.5) ** 2) * 4.0
    img[:, :, :3] = base[None, None, :] * vignette[:, :, None]

    # Subtle micro-textured outer border groove
    border_outer = (u < 0.045) | (u > 0.955) | (v < 0.055) | (v > 0.945)
    img[border_outer, :3] = np.array([0.84, 0.86, 0.90], dtype=np.float32)
    inner_line = (
        ((u >= 0.045) & (u < 0.058) & (v >= 0.055) & (v <= 0.945))
        | ((u <= 0.955) & (u > 0.942) & (v >= 0.055) & (v <= 0.945))
        | ((v >= 0.055) & (v < 0.070) & (u >= 0.045) & (u <= 0.955))
        | ((v <= 0.945) & (v > 0.930) & (u >= 0.045) & (u <= 0.955))
    )
    img[inner_line, :3] = np.array([0.74, 0.77, 0.82], dtype=np.float32)

    red = np.array(hex_to_srgb("#DC2626"), dtype=np.float32)
    dark_red = np.array(hex_to_srgb("#991B1B"), dtype=np.float32)
    slate = np.array(hex_to_srgb("#334155"), dtype=np.float32)

    # Top and bottom slim tactical crimson accent stripes
    top_band = (v >= 0.09) & (v <= 0.135) & (u >= 0.08) & (u <= 0.92)
    img[top_band, :3] = red
    bot_band = (v >= 0.855) & (v <= 0.90) & (u >= 0.08) & (u <= 0.92)
    img[bot_band, :3] = red

    # Circular subtle slate badge halo behind cross
    cx, cy = 0.50, 0.49
    dist = np.sqrt(((u - cx) * 1.12) ** 2 + (v - cy) ** 2)
    ring = (dist >= 0.255) & (dist <= 0.275)
    img[ring, :3] = np.array([0.82, 0.84, 0.88], dtype=np.float32)

    # Crisp bold medical cross centered at (0.50, 0.49)
    # Account for panel aspect (~1.38 wide vs 1.0 tall -> slightly narrower in U so it renders square in 3D!)
    arm_u_narrow = 0.068
    arm_v_narrow = 0.088
    arm_u_wide = 0.185
    arm_v_wide = 0.240

    cross_vert = (np.abs(u - cx) <= arm_u_narrow) & (np.abs(v - cy) <= arm_v_wide)
    cross_horz = (np.abs(u - cx) <= arm_u_wide) & (np.abs(v - cy) <= arm_v_narrow)
    cross = cross_vert | cross_horz

    # Subtle outer outline shadow around cross
    pad_u, pad_v = 0.010, 0.013
    cross_out = (
        ((np.abs(u - cx) <= arm_u_narrow + pad_u) & (np.abs(v - cy) <= arm_v_wide + pad_v))
        | ((np.abs(u - cx) <= arm_u_wide + pad_u) & (np.abs(v - cy) <= arm_v_narrow + pad_v))
    )
    img[cross_out, :3] = dark_red
    img[cross, :3] = red

    # Crisp corner registration dots (rivets)
    for rx in (0.10, 0.90):
        for ry in (0.20, 0.79):
            rd = np.sqrt(((u - rx) * 1.2) ** 2 + (v - ry) ** 2)
            img[rd < 0.014, :3] = slate

    # Crisp stencil labels
    draw_text(img, "FIELD TRAUMA", size // 2, int(size * 0.195), scale=4, color_rgb=slate, spacing=1)
    draw_text(img, "MEDKIT", size // 2, int(size * 0.795), scale=5, color_rgb=slate, spacing=2)

    img[:, :, 3] = 1.0
    return img


def build_shield_jug_badge_texture(size: int = 256) -> np.ndarray:
    """Generate crisp dark-titanium tactical shield emblem plate for Aegis Shield Jug."""
    img = np.ones((size, size, 4), dtype=np.float32)
    yy, xx = np.mgrid[0:size, 0:size]
    u = xx / float(size)
    v = yy / float(size)

    bg = np.array(hex_to_srgb("#1E2633"), dtype=np.float32)
    rim = np.array(hex_to_srgb("#3B495E"), dtype=np.float32)
    cyan = np.array(hex_to_srgb("#22D3EE"), dtype=np.float32)
    cobalt = np.array(hex_to_srgb("#4285F4"), dtype=np.float32)
    white = np.array([0.92, 0.96, 1.0], dtype=np.float32)

    img[:, :, :3] = bg
    border = (u < 0.06) | (u > 0.94) | (v < 0.08) | (v > 0.92)
    img[border, :3] = rim

    # Tactical shield silhouette in center-top
    du = np.abs(u - 0.5)
    shield_top = (v >= 0.16) & (v <= 0.42) & (du <= 0.20)
    t = np.clip((v - 0.42) / 0.24, 0.0, 1.0)
    shield_bot = (v > 0.42) & (v <= 0.66) & (du <= 0.20 * (1.0 - t * t))
    shield = shield_top | shield_bot
    img[shield, :3] = cobalt

    # Inner bright cyan shield chevron
    shield_in_top = (v >= 0.21) & (v <= 0.42) & (du <= 0.14)
    t_in = np.clip((v - 0.42) / 0.18, 0.0, 1.0)
    shield_in_bot = (v > 0.42) & (v <= 0.60) & (du <= 0.14 * (1.0 - t_in * t_in))
    img[shield_in_top | shield_in_bot, :3] = cyan

    # Inner dark core notch
    notch = (v >= 0.28) & (v <= 0.50) & (du <= 0.065)
    img[notch, :3] = bg
    # Bright core bar
    bar = (v >= 0.34) & (v <= 0.46) & (du <= 0.025)
    img[bar, :3] = white

    draw_text(img, "AEGIS", size // 2, int(size * 0.80), scale=4, color_rgb=cyan, spacing=1)
    img[:, :, 3] = 1.0
    return img


def build_supply_drop_texture(size: int = 512) -> np.ndarray:
    """Generate crisp tactical Supply Drop side panel texture with Google 4-color bar & stencils."""
    img = np.ones((size, size, 4), dtype=np.float32)
    yy, xx = np.mgrid[0:size, 0:size]
    u = xx / float(size)
    v = yy / float(size)

    # Brushed tactical slate-gray armor panel with subtle horizontal seam lines
    base = np.array(hex_to_srgb("#374151"), dtype=np.float32)
    dark = np.array(hex_to_srgb("#1F2937"), dtype=np.float32)
    light = np.array(hex_to_srgb("#E5E7EB"), dtype=np.float32)
    g_blue = np.array(hex_to_srgb(COL_GOOGLE_BLUE), dtype=np.float32)
    g_red = np.array(hex_to_srgb(COL_GOOGLE_RED), dtype=np.float32)
    g_yellow = np.array(hex_to_srgb(COL_GOOGLE_YELLOW), dtype=np.float32)
    g_green = np.array(hex_to_srgb(COL_GOOGLE_GREEN), dtype=np.float32)

    img[:, :, :3] = base

    # Recessed metallic perimeter bezel
    frame = (u < 0.055) | (u > 0.945) | (v < 0.055) | (v > 0.945)
    img[frame, :3] = dark

    # Subtle industrial panel ribbing (horizontal grooves)
    rib_mask = ((v > 0.22) & (v < 0.235)) | ((v > 0.765) & (v < 0.78))
    img[rib_mask & (u > 0.06) & (u < 0.94), :3] = dark

    # Bold 4-color Google Workspace stripe bar near top
    bar_v = (v >= 0.095) & (v <= 0.175)
    img[bar_v & (u >= 0.08) & (u < 0.29), :3] = g_blue
    img[bar_v & (u >= 0.29) & (u < 0.50), :3] = g_red
    img[bar_v & (u >= 0.50) & (u < 0.71), :3] = g_yellow
    img[bar_v & (u >= 0.71) & (u <= 0.92), :3] = g_green

    # Central tactical dark stencil plaque
    plaque = (u >= 0.10) & (u <= 0.90) & (v >= 0.27) & (v <= 0.72)
    img[plaque, :3] = np.array(hex_to_srgb("#242C38"), dtype=np.float32)

    # Stylized parachute + crate emblem inside upper plaque
    du = u - 0.50
    dv = v - 0.42
    canopy_r = np.sqrt((du * 1.15) ** 2 + (dv * 1.4) ** 2)
    canopy_arc = (canopy_r <= 0.135) & (dv <= 0.01) & (canopy_r >= 0.025)
    img[canopy_arc, :3] = g_yellow
    # Canopy cord lines converging to crate icon
    for slope in (-0.85, 0.0, 0.85):
        line_dist = np.abs(du - slope * (0.50 - v))
        cords = (v >= 0.42) & (v <= 0.50) & (line_dist < 0.0065)
        img[cords, :3] = light
    # Mini crate icon at center
    mini_crate = (np.abs(du) <= 0.042) & (v >= 0.50) & (v <= 0.565)
    img[mini_crate, :3] = light

    # Bold crisp stencil text
    draw_text(img, "SUPPLY DROP", size // 2, int(size * 0.645), scale=5, color_rgb=light, spacing=1)

    # Bottom diagonal hazard warning chevron bar (yellow & charcoal)
    haz_v = (v >= 0.815) & (v <= 0.905) & (u >= 0.08) & (u <= 0.92)
    stripe_phase = ((u * 12.0 + v * 6.0) % 1.0) < 0.5
    img[haz_v & stripe_phase, :3] = g_yellow
    img[haz_v & (~stripe_phase), :3] = dark

    # Corner bolt rivets
    for bx in (0.09, 0.91):
        for by in (0.295, 0.695):
            bd = np.sqrt((u - bx) ** 2 + (v - by) ** 2)
            img[bd < 0.014, :3] = light

    img[:, :, 3] = 1.0
    return img


# ---------------------------------------------------------------------------
# Clean Procedural Mesh Primitives & BMesh Builders
# ---------------------------------------------------------------------------

def link_mesh_object(name: str, bm: bmesh.types.BMesh, mat: bpy.types.Material | None = None) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(name)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()

    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    if mat is not None:
        obj.data.materials.append(mat)
    set_smooth(obj)
    return obj


def set_smooth(obj: bpy.types.Object) -> None:
    if obj.type != "MESH":
        return
    mesh = obj.data
    n = len(mesh.polygons)
    if n > 0:
        mesh.polygons.foreach_set("use_smooth", [True] * n)
    mesh.update()


def add_lathed(
    name: str,
    profile_rz: list[tuple[float, float]],
    segments: int = 24,
    mat: bpy.types.Material | None = None,
    cap_bottom: bool = True,
    cap_top: bool = True,
    scale_xy: tuple[float, float] = (1.0, 1.0),
    location: tuple[float, float, float] = (0.0, 0.0, 0.0),
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
    phase_offset: float = 0.0,
) -> bpy.types.Object:
    """Create a smooth axisymmetric or elliptical sculpted mesh from a list of (radius, z) rings."""
    bm = bmesh.new()
    rings = []
    sx, sy = scale_xy

    for r, z in profile_rz:
        if r <= 1e-6:
            v = bm.verts.new((0.0, 0.0, z))
            rings.append([v])
        else:
            ring = []
            for i in range(segments):
                ang = phase_offset + (2.0 * math.pi * i) / segments
                ring.append(bm.verts.new((r * sx * math.cos(ang), r * sy * math.sin(ang), z)))
            rings.append(ring)

    for idx in range(len(rings) - 1):
        r0 = rings[idx]
        r1 = rings[idx + 1]
        if len(r0) == 1 and len(r1) > 1:
            for i in range(segments):
                j = (i + 1) % segments
                bm.faces.new((r0[0], r1[j], r1[i]))
        elif len(r0) > 1 and len(r1) == 1:
            for i in range(segments):
                j = (i + 1) % segments
                bm.faces.new((r0[i], r0[j], r1[0]))
        elif len(r0) > 1 and len(r1) > 1:
            for i in range(segments):
                j = (i + 1) % segments
                bm.faces.new((r0[i], r0[j], r1[j], r1[i]))

    if cap_bottom and len(rings[0]) > 1:
        bm.faces.new(list(reversed(rings[0])))
    if cap_top and len(rings[-1]) > 1:
        bm.faces.new(rings[-1])

    obj = link_mesh_object(name, bm, mat)
    obj.location = Vector(location)
    obj.rotation_euler = Euler(rotation, "XYZ")
    return obj


def add_beveled_box(
    name: str,
    size: tuple[float, float, float],
    location: tuple[float, float, float] = (0.0, 0.0, 0.0),
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
    bevel_width: float = 0.012,
    bevel_segments: int = 2,
    mat: bpy.types.Material | None = None,
) -> bpy.types.Object:
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    sx, sy, sz = size
    for v in bm.verts:
        v.co.x *= sx
        v.co.y *= sy
        v.co.z *= sz
    if bevel_width > 0.0:
        bmesh.ops.bevel(
            bm,
            geom=list(bm.edges),
            offset=bevel_width,
            segments=bevel_segments,
            profile=0.5,
            affect="EDGES",
            clamp_overlap=True,
        )
    obj = link_mesh_object(name, bm, mat)
    obj.location = Vector(location)
    obj.rotation_euler = Euler(rotation, "XYZ")
    return obj


def add_beveled_prism(
    name: str,
    radius: float,
    height: float,
    sides: int = 6,
    location: tuple[float, float, float] = (0.0, 0.0, 0.0),
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
    bevel_width: float = 0.012,
    bevel_segments: int = 2,
    mat: bpy.types.Material | None = None,
    phase_offset: float = 0.0,
) -> bpy.types.Object:
    bm = bmesh.new()
    hz = height * 0.5
    bot = []
    top = []
    for i in range(sides):
        ang = phase_offset + (2.0 * math.pi * i) / sides
        x = radius * math.cos(ang)
        y = radius * math.sin(ang)
        bot.append(bm.verts.new((x, y, -hz)))
        top.append(bm.verts.new((x, y, hz)))
    for i in range(sides):
        j = (i + 1) % sides
        bm.faces.new((bot[i], bot[j], top[j], top[i]))
    bm.faces.new(list(reversed(bot)))
    bm.faces.new(top)
    if bevel_width > 0.0:
        bmesh.ops.bevel(
            bm,
            geom=list(bm.edges),
            offset=bevel_width,
            segments=bevel_segments,
            profile=0.5,
            affect="EDGES",
            clamp_overlap=True,
        )
    obj = link_mesh_object(name, bm, mat)
    obj.location = Vector(location)
    obj.rotation_euler = Euler(rotation, "XYZ")
    return obj


def add_tube_path(
    name: str,
    points: list[tuple[float, float, float]],
    radius: float | list[float],
    segments: int = 10,
    mat: bpy.types.Material | None = None,
    closed: bool = False,
    cap_ends: bool = True,
) -> bpy.types.Object:
    """Sweep a smooth cylindrical tube along a 3D polyline with parallel-transport frames."""
    pts = [Vector(p) for p in points]
    n = len(pts)
    assert n >= 2
    if isinstance(radius, (int, float)):
        radii = [float(radius)] * n
    else:
        radii = list(radius)

    tangents = []
    for i in range(n):
        if closed:
            t = (pts[(i + 1) % n] - pts[(i - 1) % n]).normalized()
        elif i == 0:
            t = (pts[1] - pts[0]).normalized()
        elif i == n - 1:
            t = (pts[-1] - pts[-2]).normalized()
        else:
            t1 = (pts[i] - pts[i - 1]).normalized()
            t2 = (pts[i + 1] - pts[i]).normalized()
            t = (t1 + t2)
            t = t.normalized() if t.length > 1e-6 else t1
        tangents.append(t)

    # Initial frame via parallel transport
    ref = Vector((0.0, 0.0, 1.0)) if abs(tangents[0].z) < 0.9 else Vector((1.0, 0.0, 0.0))
    u_vec = tangents[0].cross(ref).normalized()
    v_vec = tangents[0].cross(u_vec).normalized()

    frames = [(u_vec, v_vec)]
    for i in range(1, n):
        t_prev = tangents[i - 1]
        t_curr = tangents[i]
        axis = t_prev.cross(t_curr)
        if axis.length > 1e-6:
            angle = t_prev.angle(t_curr)
            rot = Matrix.Rotation(angle, 3, axis.normalized())
            u_vec = (rot @ u_vec).normalized()
            v_vec = t_curr.cross(u_vec).normalized()
        frames.append((u_vec, v_vec))

    bm = bmesh.new()
    rings = []
    for i in range(n):
        u_v, v_v = frames[i]
        r = radii[i]
        ring = []
        for s in range(segments):
            ang = (2.0 * math.pi * s) / segments
            offset = (u_v * math.cos(ang) + v_v * math.sin(ang)) * r
            ring.append(bm.verts.new(pts[i] + offset))
        rings.append(ring)

    ring_count = n if closed else n - 1
    for i in range(ring_count):
        r0 = rings[i]
        r1 = rings[(i + 1) % n]
        for s in range(segments):
            s2 = (s + 1) % segments
            bm.faces.new((r0[s], r0[s2], r1[s2], r1[s]))

    if not closed and cap_ends:
        bm.faces.new(list(reversed(rings[0])))
        bm.faces.new(rings[-1])

    return link_mesh_object(name, bm, mat)


def add_uv_panel_quad(
    name: str,
    corners: list[tuple[float, float, float]],
    mat: bpy.types.Material,
) -> bpy.types.Object:
    """Create a UV-mapped quad panel given 4 corners in CCW order: (BL, BR, TR, TL)."""
    bm = bmesh.new()
    uv_layer = bm.loops.layers.uv.new("UVMap")
    verts = [bm.verts.new(c) for c in corners]
    face = bm.faces.new(verts)
    uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    for loop, uv in zip(face.loops, uvs):
        loop[uv_layer].uv = uv
    return link_mesh_object(name, bm, mat)


def add_torus_ring(
    name: str,
    major_r: float,
    minor_r: float,
    major_segs: int = 24,
    minor_segs: int = 10,
    location: tuple[float, float, float] = (0.0, 0.0, 0.0),
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
    mat: bpy.types.Material | None = None,
) -> bpy.types.Object:
    pts = [
        (major_r * math.cos(2.0 * math.pi * i / major_segs), major_r * math.sin(2.0 * math.pi * i / major_segs), 0.0)
        for i in range(major_segs)
    ]
    obj = add_tube_path(name, pts, radius=minor_r, segments=minor_segs, mat=mat, closed=True)
    obj.location = Vector(location)
    obj.rotation_euler = Euler(rotation, "XYZ")
    return obj


def add_uv_sphere(
    name: str,
    radius: float,
    segments: int = 16,
    rings: int = 10,
    location: tuple[float, float, float] = (0.0, 0.0, 0.0),
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0),
    mat: bpy.types.Material | None = None,
) -> bpy.types.Object:
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=segments, v_segments=rings, radius=radius)
    for v in bm.verts:
        v.co.x *= scale[0]
        v.co.y *= scale[1]
        v.co.z *= scale[2]
    obj = link_mesh_object(name, bm, mat)
    obj.location = Vector(location)
    return obj


# ---------------------------------------------------------------------------
# Transform, Grounding, Stats & glTF Export Utilities
# ---------------------------------------------------------------------------

def world_bbox(objects: list[bpy.types.Object]) -> tuple[Vector, Vector]:
    bpy.context.view_layer.update()
    mins = Vector((float("inf"), float("inf"), float("inf")))
    maxs = Vector((float("-inf"), float("-inf"), float("-inf")))
    for obj in objects:
        if obj.type != "MESH":
            continue
        mw = obj.matrix_world
        for v in obj.data.vertices:
            wp = mw @ v.co
            mins.x = min(mins.x, wp.x)
            mins.y = min(mins.y, wp.y)
            mins.z = min(mins.z, wp.z)
            maxs.x = max(maxs.x, wp.x)
            maxs.y = max(maxs.y, wp.y)
            maxs.z = max(maxs.z, wp.z)
    return mins, maxs


def count_tris(objects: list[bpy.types.Object]) -> int:
    total = 0
    for obj in objects:
        if obj.type != "MESH":
            continue
        obj.data.calc_loop_triangles()
        total += len(obj.data.loop_triangles)
    return total


def ground_and_center(objects: list[bpy.types.Object], center_xy: bool = True, ground_z: bool = True) -> None:
    mins, maxs = world_bbox(objects)
    dx = -0.5 * (mins.x + maxs.x) if center_xy else 0.0
    dy = -0.5 * (mins.y + maxs.y) if center_xy else 0.0
    dz = -mins.z if ground_z else 0.0
    shift = Vector((dx, dy, dz))
    for obj in objects:
        obj.location += shift
    bpy.context.view_layer.update()


def export_asset(objects: list[bpy.types.Object], filename: str, center_xy: bool = True, ground_z: bool = True) -> dict:
    if center_xy or ground_z:
        ground_and_center(objects, center_xy=center_xy, ground_z=ground_z)

    # Apply transforms cleanly so all local pivots & bounds are baked
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    mins, maxs = world_bbox(objects)
    dims = maxs - mins
    tris = count_tris(objects)

    out_path = str(OUT_DIR / filename)
    bpy.ops.export_scene.gltf(
        filepath=out_path,
        export_format="GLB",
        use_selection=True,
        export_yup=True,
        export_apply=True,
        export_materials="EXPORT",
        export_animations=False,
        export_draco_mesh_compression_enable=False,
    )

    size_bytes = os.path.getsize(out_path)
    return {
        "file": filename,
        "tris": tris,
        "size_kb": size_bytes / 1024.0,
        "dims": (dims.x, dims.y, dims.z),
        "min_z": mins.z,
        "max_z": maxs.z,
    }


# ===========================================================================
# 1. SHIELD CELL (item_shield_cell.glb)
# ===========================================================================

def build_shield_cell() -> dict:
    clear_scene()
    objs = []

    mat_gunmetal = make_pbr_mat("SC_Gunmetal", COL_GUNMETAL, metallic=0.82, roughness=0.30)
    mat_slate = make_pbr_mat("SC_DarkSlate", COL_DARK_SLATE, metallic=0.18, roughness=0.68)
    mat_rubber = make_pbr_mat("SC_Rubber", COL_RUBBER, metallic=0.0, roughness=0.88)
    mat_cobalt = make_pbr_mat("SC_CobaltAnodized", COL_COBALT_ANODIZED, metallic=0.72, roughness=0.26)
    mat_steel = make_pbr_mat("SC_BrushedSteel", COL_BRUSHED_STEEL, metallic=0.88, roughness=0.24)
    mat_glass = make_pbr_mat(
        "SC_GlassChamber",
        COL_CYAN_GLASS,
        metallic=0.05,
        roughness=0.06,
        specular=0.80,
        coat=0.75,
        ior=1.48,
        alpha=0.22,
        backface_cull=True,
    )
    mat_liquid = make_pbr_mat(
        "SC_CyanLiquid",
        "#00B8E6",
        metallic=0.02,
        roughness=0.14,
        emission_hex="#00B8E6",
        emission_strength=1.45,
        alpha=0.72,
        backface_cull=True,
    )
    mat_core_hot = make_pbr_mat(
        "SC_CyanCoreHot",
        "#22E5FF",
        metallic=0.0,
        roughness=0.10,
        emission_hex="#22E5FF",
        emission_strength=3.2,
    )

    # Rubber base bumper pad
    objs.append(add_lathed(
        "BaseRubberPad",
        [(0.068, 0.000), (0.084, 0.008), (0.086, 0.024), (0.078, 0.028)],
        segments=16,
        mat=mat_rubber,
    ))

    # Machined lower gunmetal cap with chamfered grip groove
    objs.append(add_lathed(
        "LowerCap",
        [
            (0.076, 0.026),
            (0.094, 0.036),
            (0.088, 0.048),
            (0.088, 0.058),
            (0.094, 0.066),
            (0.094, 0.078),
            (0.084, 0.088),
            (0.074, 0.088),
        ],
        segments=14,
        mat=mat_gunmetal,
    ))

    # Anodized cobalt accent band at base of glass viewport
    objs.append(add_lathed(
        "LowerCobaltRing",
        [(0.082, 0.084), (0.088, 0.088), (0.088, 0.099), (0.080, 0.103)],
        segments=14,
        mat=mat_cobalt,
    ))

    # Upper machined gunmetal cap + stepped pressure collar
    objs.append(add_lathed(
        "UpperCap",
        [
            (0.074, 0.284),
            (0.094, 0.294),
            (0.094, 0.312),
            (0.086, 0.324),
            (0.074, 0.342),
            (0.064, 0.352),
            (0.050, 0.356),
        ],
        segments=14,
        mat=mat_gunmetal,
    ))

    # Glowing cyan LED charge indicator ring recessed into upper collar
    objs.append(add_lathed(
        "UpperChargeLED",
        [(0.088, 0.296), (0.0955, 0.299), (0.0955, 0.309), (0.088, 0.312)],
        segments=14,
        mat=mat_core_hot,
        cap_bottom=False,
        cap_top=False,
    ))

    # Brushed-steel twist-lock pressure valve top cap
    objs.append(add_lathed(
        "ValveTopCap",
        [
            (0.050, 0.354),
            (0.056, 0.358),
            (0.056, 0.378),
            (0.046, 0.386),
            (0.000, 0.390),
        ],
        segments=14,
        mat=mat_steel,
        cap_top=False,
    ))

    # Top clip / carry bail loop
    bail_pts = [
        (-0.038, 0.0, 0.365),
        (-0.046, 0.0, 0.398),
        (-0.024, 0.0, 0.415),
        (0.024, 0.0, 0.415),
        (0.046, 0.0, 0.398),
        (0.038, 0.0, 0.365),
    ]
    objs.append(add_tube_path("TopClipBail", bail_pts, radius=0.007, segments=6, mat=mat_steel))

    # Outer translucent glass chamber
    objs.append(add_lathed(
        "GlassViewport",
        [
            (0.075, 0.098),
            (0.079, 0.105),
            (0.079, 0.279),
            (0.075, 0.286),
        ],
        segments=16,
        mat=mat_glass,
        cap_bottom=False,
        cap_top=False,
    ))

    # Inner glowing cyan shield plasma liquid core with curved meniscus top
    objs.append(add_lathed(
        "CyanLiquidCore",
        [
            (0.000, 0.100),
            (0.062, 0.104),
            (0.064, 0.252),
            (0.056, 0.266),
            (0.000, 0.268),
        ],
        segments=16,
        mat=mat_liquid,
        cap_bottom=False,
        cap_top=False,
    ))

    # Bright central energy column + twin glowing plasma rings inside core
    objs.append(add_lathed(
        "InnerPlasmaColumn",
        [(0.020, 0.104), (0.024, 0.185), (0.020, 0.266)],
        segments=8,
        mat=mat_core_hot,
    ))
    for idx, rz in enumerate((0.155, 0.222)):
        objs.append(add_torus_ring(
            f"CoreEnergyRing_{idx}",
            major_r=0.046,
            minor_r=0.006,
            major_segs=12,
            minor_segs=4,
            location=(0.0, 0.0, rz),
            mat=mat_core_hot,
        ))

    # 3 Sculpted Armored Cage Strut Ribs wrapping outside the glass chamber
    for i in range(3):
        ang = i * (2.0 * math.pi / 3.0) + math.pi / 6.0
        ca, sa = math.cos(ang), math.sin(ang)
        pts = [
            (0.086 * ca, 0.086 * sa, 0.076),
            (0.095 * ca, 0.095 * sa, 0.110),
            (0.093 * ca, 0.093 * sa, 0.192),
            (0.095 * ca, 0.095 * sa, 0.274),
            (0.086 * ca, 0.086 * sa, 0.304),
        ]
        objs.append(add_tube_path(
            f"ArmorStrut_{i}",
            pts,
            radius=[0.011, 0.013, 0.011, 0.013, 0.011],
            segments=6,
            mat=mat_slate,
        ))
        # Machined cobalt accent collar block at strut midpoint
        objs.append(add_beveled_box(
            f"StrutClamp_{i}",
            size=(0.022, 0.028, 0.036),
            location=(0.091 * ca, 0.091 * sa, 0.192),
            rotation=(0.0, 0.0, ang),
            bevel_width=0.004,
            bevel_segments=1,
            mat=mat_cobalt,
        ))

    return export_asset(objs, "item_shield_cell.glb")


# ===========================================================================
# 2. AEGIS SHIELD JUG (item_shield_jug.glb)
# ===========================================================================

def build_shield_jug() -> dict:
    clear_scene()
    objs = []

    mat_gunmetal = make_pbr_mat("SJ_Gunmetal", COL_GUNMETAL, metallic=0.80, roughness=0.32)
    mat_slate = make_pbr_mat("SJ_DarkSlate", COL_DARK_SLATE, metallic=0.15, roughness=0.72)
    mat_rubber = make_pbr_mat("SJ_Rubber", COL_RUBBER, metallic=0.0, roughness=0.88)
    mat_cobalt = make_pbr_mat("SJ_Cobalt", COL_COBALT_ANODIZED, metallic=0.72, roughness=0.25)
    mat_steel = make_pbr_mat("SJ_Steel", COL_BRUSHED_STEEL, metallic=0.88, roughness=0.24)
    mat_glass = make_pbr_mat(
        "SJ_GlassTank",
        COL_CYAN_GLASS,
        metallic=0.05,
        roughness=0.06,
        specular=0.80,
        coat=0.75,
        ior=1.48,
        alpha=0.22,
        backface_cull=True,
    )
    mat_liquid = make_pbr_mat(
        "SJ_CyanLiquid",
        "#00B8E6",
        metallic=0.02,
        roughness=0.14,
        emission_hex="#00B8E6",
        emission_strength=1.40,
        alpha=0.72,
        backface_cull=True,
    )
    mat_core_hot = make_pbr_mat(
        "SJ_CyanCoreHot",
        "#22E5FF",
        metallic=0.0,
        roughness=0.10,
        emission_hex="#22E5FF",
        emission_strength=3.2,
    )
    mat_badge = make_textured_pbr_mat("SJ_AegisBadge", build_shield_jug_badge_texture(256), metallic=0.35, roughness=0.35)

    ellip = (1.14, 0.92)  # Ergonomic wide tactical jug proportion

    # Heavy Ribbed Rubberized Tactical Base (Z=0.00..0.145)
    objs.append(add_lathed(
        "RibbedBase",
        [
            (0.122, 0.000),
            (0.145, 0.018),
            (0.135, 0.044),
            (0.145, 0.064),
            (0.135, 0.088),
            (0.145, 0.112),
            (0.126, 0.142),
        ],
        segments=14,
        scale_xy=ellip,
        mat=mat_slate,
    ))

    # 4 Chunky Rubberized Corner Bumper Feet anchored solidly at Z=0
    for i in range(4):
        ang = math.pi * 0.25 + i * math.pi * 0.5
        fx = 0.136 * ellip[0] * math.cos(ang)
        fy = 0.136 * ellip[1] * math.sin(ang)
        objs.append(add_beveled_box(
            f"BumperFoot_{i}",
            size=(0.062, 0.046, 0.052),
            location=(fx, fy, 0.026),
            rotation=(0.0, 0.0, ang),
            bevel_width=0.008,
            bevel_segments=1,
            mat=mat_rubber,
        ))

    # Lower anodized cobalt armor ring
    objs.append(add_lathed(
        "LowerCobaltCollar",
        [(0.124, 0.136), (0.136, 0.144), (0.136, 0.158), (0.122, 0.164)],
        segments=14,
        scale_xy=ellip,
        mat=mat_cobalt,
    ))

    # Sculpted Upper Armored Shoulder Shroud (Z=0.355..0.465)
    objs.append(add_lathed(
        "UpperShoulderShroud",
        [
            (0.118, 0.352),
            (0.142, 0.376),
            (0.140, 0.415),
            (0.120, 0.448),
            (0.096, 0.464),
            (0.065, 0.466),
        ],
        segments=14,
        scale_xy=ellip,
        mat=mat_gunmetal,
    ))

    # Upper glowing cyan LED charge trim ring
    objs.append(add_lathed(
        "ShoulderLEDStrip",
        [(0.136, 0.376), (0.146, 0.382), (0.146, 0.392), (0.136, 0.396)],
        segments=14,
        scale_xy=ellip,
        mat=mat_core_hot,
        cap_bottom=False,
        cap_top=False,
    ))

    # Wide Translucent Glass Pressure Tank (Z=0.156..0.360)
    objs.append(add_lathed(
        "GlassPressureTank",
        [
            (0.118, 0.156),
            (0.128, 0.172),
            (0.128, 0.344),
            (0.118, 0.360),
        ],
        segments=16,
        scale_xy=ellip,
        mat=mat_glass,
        cap_bottom=False,
        cap_top=False,
    ))

    # Luminous Cyan Liquid Core inside tank (80% full with smooth meniscus)
    objs.append(add_lathed(
        "CyanLiquidTank",
        [
            (0.000, 0.162),
            (0.110, 0.170),
            (0.114, 0.320),
            (0.092, 0.336),
            (0.000, 0.334),
        ],
        segments=16,
        scale_xy=ellip,
        mat=mat_liquid,
        cap_bottom=False,
        cap_top=False,
    ))

    # Central energy diffuser spine + twin bright plasma rings inside liquid
    objs.append(add_lathed(
        "CoreDiffuserSpine",
        [(0.024, 0.164), (0.032, 0.252), (0.024, 0.336)],
        segments=8,
        mat=mat_core_hot,
    ))
    for idx, rz in enumerate((0.215, 0.285)):
        objs.append(add_torus_ring(
            f"JugCoreRing_{idx}",
            major_r=0.078,
            minor_r=0.008,
            major_segs=10,
            minor_segs=4,
            location=(0.0, 0.0, rz),
            mat=mat_core_hot,
        ))

    # 4 Sculpted Armored Corner Struts protecting the glass tank
    for i in range(4):
        ang = math.pi * 0.25 + i * math.pi * 0.5
        ca, sa = math.cos(ang), math.sin(ang)
        rx_base = 0.138 * ellip[0]
        ry_base = 0.138 * ellip[1]
        pts = [
            (rx_base * 0.96 * ca, ry_base * 0.96 * sa, 0.125),
            (rx_base * 1.04 * ca, ry_base * 1.04 * sa, 0.170),
            (rx_base * 1.04 * ca, ry_base * 1.04 * sa, 0.348),
            (rx_base * 0.95 * ca, ry_base * 0.95 * sa, 0.392),
        ]
        objs.append(add_tube_path(
            f"TankArmorStrut_{i}",
            pts,
            radius=[0.015, 0.017, 0.017, 0.015],
            segments=6,
            mat=mat_gunmetal,
        ))

    # Front Armored Tactical Badge Plate w/ crisp AEGIS shield emblem texture
    # Tilted slightly backward to sit flush on upper front shoulder shroud
    badge_plate = add_beveled_box(
        "FrontBadgeBacking",
        size=(0.096, 0.014, 0.074),
        location=(0.0, -0.126, 0.418),
        rotation=(math.radians(-16.0), 0.0, 0.0),
        bevel_width=0.004,
        bevel_segments=1,
        mat=mat_slate,
    )
    objs.append(badge_plate)

    # Textured quad right on front of badge backing
    rot_m = Euler((math.radians(-16.0), 0.0, 0.0), "XYZ").to_matrix()
    center_b = Vector((0.0, -0.126, 0.418)) + rot_m @ Vector((0.0, -0.0082, 0.0))
    bw, bh = 0.042, 0.031
    local_corners = [(-bw, 0.0, -bh), (bw, 0.0, -bh), (bw, 0.0, bh), (-bw, 0.0, bh)]
    world_corners = [tuple(center_b + rot_m @ Vector(c)) for c in local_corners]
    objs.append(add_uv_panel_quad("FrontBadgeDecal", world_corners, mat=mat_badge))

    # Ergonomic Arched Top Carrying Handle bridging cleanly across top deck
    handle_pts = [
        (-0.112, 0.0, 0.440),
        (-0.118, 0.0, 0.518),
        (-0.086, 0.0, 0.562),
        (0.000, 0.0, 0.576),
        (0.086, 0.0, 0.562),
        (0.118, 0.0, 0.518),
        (0.112, 0.0, 0.440),
    ]
    objs.append(add_tube_path("CarryHandleArch", handle_pts, radius=0.015, segments=7, mat=mat_gunmetal))

    # Rubberized center ergonomic grip sleeve on handle
    grip_pts = [
        (-0.056, 0.0, 0.569),
        (0.000, 0.0, 0.576),
        (0.056, 0.0, 0.569),
    ]
    objs.append(add_tube_path("CarryHandleGrip", grip_pts, radius=0.021, segments=7, mat=mat_rubber))

    # Machined Central / Offset Valve Spout & Knurled Cap under the handle arch
    objs.append(add_lathed(
        "ValveSpout",
        [
            (0.044, 0.456),
            (0.048, 0.466),
            (0.042, 0.488),
            (0.046, 0.496),
            (0.046, 0.518),
            (0.034, 0.526),
            (0.000, 0.528),
        ],
        segments=12,
        location=(0.0, -0.022, 0.0),
        mat=mat_steel,
        cap_top=False,
    ))
    objs.append(add_lathed(
        "ValveLockRing",
        [(0.043, 0.484), (0.050, 0.488), (0.050, 0.499), (0.043, 0.503)],
        segments=12,
        location=(0.0, -0.022, 0.0),
        mat=mat_cobalt,
        cap_bottom=False,
        cap_top=False,
    ))

    return export_asset(objs, "item_shield_jug.glb")


# ===========================================================================
# 3. FIELD MEDKIT (item_medkit.glb)
# ===========================================================================

def build_medkit() -> dict:
    clear_scene()
    objs = []

    mat_case_white = make_pbr_mat("MK_SatinWhite", COL_SATIN_WHITE, metallic=0.04, roughness=0.36, coat=0.25)
    mat_red = make_pbr_mat("MK_MedicalRed", COL_CRIMSON, metallic=0.05, roughness=0.40, coat=0.20)
    mat_gasket = make_pbr_mat("MK_RubberGasket", COL_RUBBER, metallic=0.0, roughness=0.88)
    mat_gunmetal = make_pbr_mat("MK_Gunmetal", COL_GUNMETAL, metallic=0.82, roughness=0.30)
    mat_steel = make_pbr_mat("MK_BrushedSteel", COL_BRUSHED_STEEL, metallic=0.88, roughness=0.24)
    mat_face = make_textured_pbr_mat("MK_TraumaFace", build_medkit_texture(512), metallic=0.02, roughness=0.36, coat=0.20)

    # Case main body: upright tactical clamshell trauma kit
    # X width = 0.42m, Y depth = 0.168m, Z body = 0.022..0.342m (handle tops out at ~0.415m)
    body_z = 0.182
    shell_h = 0.312
    shell_w = 0.420

    # Front clamshell half (-Y)
    objs.append(add_beveled_box(
        "FrontClamshell",
        size=(shell_w, 0.076, shell_h),
        location=(0.0, -0.044, body_z),
        bevel_width=0.020,
        bevel_segments=2,
        mat=mat_case_white,
    ))
    # Back clamshell half (+Y)
    objs.append(add_beveled_box(
        "BackClamshell",
        size=(shell_w, 0.076, shell_h),
        location=(0.0, 0.044, body_z),
        bevel_width=0.020,
        bevel_segments=2,
        mat=mat_case_white,
    ))

    # Recessed Waterproof Rubber Perimeter Gasket Seal between clamshells
    objs.append(add_beveled_box(
        "WaterproofGasket",
        size=(shell_w - 0.012, 0.026, shell_h - 0.012),
        location=(0.0, 0.0, body_z),
        bevel_width=0.008,
        bevel_segments=1,
        mat=mat_gasket,
    ))

    # Molded Front & Back Medical Cross Texture Panels cleanly proud of red perimeter bezel
    pw = 0.171
    ph = 0.123
    fy = -0.0858
    by = 0.0858
    # Front panel (viewer at -Y looking +Y)
    objs.append(add_uv_panel_quad(
        "FrontCrossPanel",
        [(-pw, fy, body_z - ph), (pw, fy, body_z - ph), (pw, fy, body_z + ph), (-pw, fy, body_z + ph)],
        mat=mat_face,
    ))
    # Back panel (viewer at +Y looking -Y)
    objs.append(add_uv_panel_quad(
        "BackCrossPanel",
        [(pw, by, body_z - ph), (-pw, by, body_z - ph), (-pw, by, body_z + ph), (pw, by, body_z + ph)],
        mat=mat_face,
    ))

    # Thin raised perimeter trim frames framing both face panels
    for side_idx, sy in enumerate((-0.081, 0.081)):
        objs.append(add_beveled_box(
            f"PanelBezel_{side_idx}",
            size=(0.356, 0.006, 0.260),
            location=(0.0, sy, body_z),
            bevel_width=0.002,
            bevel_segments=1,
            mat=mat_red,
        ))

    # 8 Heavy Crimson-Red / Rubber Corner Bumpers (bottom 4 act as grounded feet at Z=0.0)
    for sx in (-1.0, 1.0):
        for sz_i, cz in enumerate((0.036, 0.328)):
            bumper_mat = mat_gasket if sz_i == 0 else mat_red
            objs.append(add_beveled_box(
                f"CornerBumper_{'L' if sx < 0 else 'R'}_{sz_i}",
                size=(0.068, 0.172, 0.056),
                location=(sx * 0.186, 0.0, cz),
                bevel_width=0.012,
                bevel_segments=2,
                mat=bumper_mat,
            ))

    # Bottom heavy mechanical hinge knuckles along seam
    for idx, hx in enumerate((-0.105, 0.105)):
        objs.append(add_lathed(
            f"BottomHinge_{idx}",
            [(0.014, -0.028), (0.018, -0.024), (0.018, 0.024), (0.014, 0.028)],
            segments=12,
            location=(hx, 0.0, 0.022),
            rotation=(0.0, math.pi * 0.5, 0.0),
            mat=mat_gunmetal,
        ))

    # Top Ergonomic Carrying Handle & Dual Mounting Brackets
    for idx, bx in enumerate((-0.084, 0.084)):
        objs.append(add_beveled_box(
            f"HandleBracket_{idx}",
            size=(0.030, 0.054, 0.034),
            location=(bx, 0.0, 0.348),
            bevel_width=0.005,
            bevel_segments=1,
            mat=mat_gunmetal,
        ))

    handle_pts = [
        (-0.084, 0.0, 0.356),
        (-0.084, 0.0, 0.398),
        (-0.064, 0.0, 0.412),
        (0.064, 0.0, 0.412),
        (0.084, 0.0, 0.398),
        (0.084, 0.0, 0.356),
    ]
    objs.append(add_tube_path("HandleBar", handle_pts, radius=0.012, segments=10, mat=mat_gunmetal))
    objs.append(add_tube_path(
        "HandleGripSleeve",
        [(-0.054, 0.0, 0.412), (0.054, 0.0, 0.412)],
        radius=0.017,
        segments=10,
        mat=mat_red,
    ))

    # Dual Tactical Clamping Buckle Latches on top shoulders (bridging front & back clamshells)
    for idx, lx in enumerate((-0.140, 0.140)):
        objs.append(add_beveled_box(
            f"TopLatchBody_{idx}",
            size=(0.044, 0.124, 0.026),
            location=(lx, 0.0, 0.348),
            bevel_width=0.005,
            bevel_segments=1,
            mat=mat_steel,
        ))
        # Red pull-tab clasps on front and back of each latch
        for s_idx, ly in enumerate((-0.068, 0.068)):
            objs.append(add_beveled_box(
                f"LatchClasp_{idx}_{s_idx}",
                size=(0.034, 0.022, 0.040),
                location=(lx, ly, 0.332),
                bevel_width=0.004,
                bevel_segments=1,
                mat=mat_red,
            ))

    # Side crimson tactical accent plates on left/right edges
    for s_idx, sx in enumerate((-0.214, 0.214)):
        objs.append(add_beveled_box(
            f"SideTrimPlate_{s_idx}",
            size=(0.010, 0.110, 0.165),
            location=(sx, 0.0, body_z),
            bevel_width=0.003,
            bevel_segments=1,
            mat=mat_red,
        ))

    return export_asset(objs, "item_medkit.glb")


# ===========================================================================
# 4. MANA ELIXIR (item_mana_elixir.glb)
# ===========================================================================

def build_mana_elixir() -> dict:
    clear_scene()
    objs = []

    mat_titanium = make_pbr_mat("ME_Titanium", COL_TITANIUM, metallic=0.86, roughness=0.25)
    mat_gunmetal = make_pbr_mat("ME_Gunmetal", COL_GUNMETAL, metallic=0.82, roughness=0.30)
    mat_rubber = make_pbr_mat("ME_Rubber", COL_RUBBER, metallic=0.0, roughness=0.88)
    mat_violet_metal = make_pbr_mat("ME_VioletAnodized", COL_VIOLET_ANODIZED, metallic=0.76, roughness=0.24)
    mat_glass = make_pbr_mat(
        "ME_GlassFlask",
        COL_VIOLET_GLASS,
        metallic=0.04,
        roughness=0.05,
        specular=0.82,
        coat=0.75,
        ior=1.50,
        alpha=0.22,
        backface_cull=True,
    )
    mat_mana = make_pbr_mat(
        "ME_ManaLiquid",
        "#7E22CE",
        metallic=0.02,
        roughness=0.14,
        emission_hex="#8B5CF6",
        emission_strength=1.45,
        alpha=0.72,
        backface_cull=True,
    )
    mat_mana_hot = make_pbr_mat(
        "ME_ManaCoreBright",
        "#C084FC",
        metallic=0.0,
        roughness=0.10,
        emission_hex="#A855F7",
        emission_strength=3.0,
    )

    # Rubber foot ring at Z=0
    objs.append(add_lathed(
        "BaseFoot",
        [(0.074, 0.000), (0.092, 0.010), (0.092, 0.022)],
        segments=16,
        mat=mat_rubber,
    ))

    # Weighted flared dark-gunmetal laboratory base collar
    objs.append(add_lathed(
        "WeightedBase",
        [
            (0.092, 0.020),
            (0.096, 0.034),
            (0.090, 0.060),
            (0.074, 0.080),
        ],
        segments=16,
        mat=mat_gunmetal,
    ))

    # Glowing violet power status strip around base
    objs.append(add_lathed(
        "BasePowerLED",
        [(0.092, 0.038), (0.098, 0.042), (0.098, 0.052), (0.092, 0.055)],
        segments=16,
        mat=mat_mana_hot,
        cap_bottom=False,
        cap_top=False,
    ))

    # Sleek Futuristic Sculpted Cylindrical/Waisted Glass Flask Vessel (Z=0.076..0.370)
    objs.append(add_lathed(
        "GlassAmpoule",
        [
            (0.073, 0.076),
            (0.082, 0.120),
            (0.072, 0.228),
            (0.075, 0.288),
            (0.066, 0.330),
            (0.044, 0.372),
        ],
        segments=16,
        mat=mat_glass,
        cap_bottom=False,
        cap_top=False,
    ))

    # Luminous Violet-Purple Mana Core Vessel Inside Glass
    objs.append(add_lathed(
        "ManaLiquidCore",
        [
            (0.000, 0.082),
            (0.068, 0.112),
            (0.060, 0.228),
            (0.062, 0.282),
            (0.050, 0.316),
            (0.000, 0.324),
        ],
        segments=16,
        mat=mat_mana,
        cap_bottom=False,
        cap_top=False,
    ))

    # Bright Internal Helical Mana Energy Coil + Central Crystal Emitter Spire
    objs.append(add_lathed(
        "CentralManaSpire",
        [(0.018, 0.084), (0.025, 0.155), (0.014, 0.245), (0.000, 0.335)],
        segments=6,
        mat=mat_mana_hot,
        cap_top=False,
    ))
    helix_pts = []
    steps = 15
    for s in range(steps):
        t = s / float(steps - 1)
        z = 0.095 + t * 0.220
        ang = t * 2.2 * math.pi
        r = 0.042 * (1.0 - 0.18 * math.sin(t * math.pi))
        helix_pts.append((r * math.cos(ang), r * math.sin(ang), z))
    objs.append(add_tube_path("ManaHelixCoil", helix_pts, radius=0.0065, segments=5, mat=mat_mana_hot))

    # 4 Gracefully Curved Anodized Protective Metal Exoskeleton Ribs
    rib_profile = [
        (0.086, 0.064),
        (0.095, 0.130),
        (0.084, 0.228),
        (0.087, 0.300),
        (0.056, 0.365),
    ]
    for i in range(4):
        ang = i * (math.pi * 0.5) + math.pi * 0.25
        ca, sa = math.cos(ang), math.sin(ang)
        pts = [(r * ca, r * sa, z) for (r, z) in rib_profile]
        objs.append(add_tube_path(
            f"ProtectiveRib_{i}",
            pts,
            radius=[0.009, 0.010, 0.0085, 0.009, 0.009],
            segments=5,
            mat=mat_titanium,
        ))

    # Mid-waist titanium containment ring locking the 4 protective ribs together
    objs.append(add_torus_ring(
        "WaistContainmentRing",
        major_r=0.084,
        minor_r=0.0085,
        major_segs=16,
        minor_segs=5,
        location=(0.0, 0.0, 0.228),
        mat=mat_violet_metal,
    ))

    # Precision Anodized Cap, Knurled Collar & Finial (Z=0.358..0.482)
    objs.append(add_lathed(
        "NeckCollar",
        [
            (0.044, 0.358),
            (0.060, 0.366),
            (0.060, 0.384),
            (0.052, 0.398),
        ],
        segments=14,
        mat=mat_gunmetal,
    ))
    objs.append(add_lathed(
        "AnodizedCap",
        [
            (0.052, 0.398),
            (0.058, 0.408),
            (0.053, 0.426),
            (0.058, 0.436),
            (0.056, 0.454),
            (0.042, 0.468),
            (0.022, 0.480),
            (0.000, 0.482),
        ],
        segments=14,
        mat=mat_violet_metal,
        cap_top=False,
    ))
    # Glowing violet crown ring on top cap
    objs.append(add_torus_ring(
        "CapCrownLED",
        major_r=0.042,
        minor_r=0.0045,
        major_segs=14,
        minor_segs=4,
        location=(0.0, 0.0, 0.465),
        mat=mat_mana_hot,
    ))

    return export_asset(objs, "item_mana_elixir.glb")


# ===========================================================================
# 5. HARD-LIGHT COVER EMITTER DISC (item_hardlight_cover.glb)
# ===========================================================================

def build_hardlight_cover() -> dict:
    clear_scene()
    objs = []

    mat_gunmetal = make_pbr_mat("HL_Gunmetal", COL_GUNMETAL, metallic=0.82, roughness=0.30)
    mat_slate = make_pbr_mat("HL_DarkSlate", COL_DARK_SLATE, metallic=0.18, roughness=0.70)
    mat_rubber = make_pbr_mat("HL_Rubber", COL_RUBBER, metallic=0.0, roughness=0.88)
    mat_titanium = make_pbr_mat("HL_Titanium", COL_TITANIUM, metallic=0.86, roughness=0.25)
    mat_cobalt = make_pbr_mat("HL_Cobalt", COL_COBALT_ANODIZED, metallic=0.74, roughness=0.26)
    mat_cyan_lens = make_pbr_mat(
        "HL_CyanLens",
        "#00B4D8",
        metallic=0.08,
        roughness=0.07,
        coat=0.85,
        emission_hex="#00C8FF",
        emission_strength=1.85,
    )
    mat_cyan_hot = make_pbr_mat(
        "HL_CyanEmitterHot",
        "#22E5FF",
        metallic=0.0,
        roughness=0.08,
        emission_hex="#22E5FF",
        emission_strength=3.4,
    )

    # Assemble the beveled hexagonal emitter disc centered at local (0,0,0), facing +Z,
    # then tilt cleanly onto an integrated grounded deployment cradle so its lens & hex
    # face present heroically at ~45 deg to both gameplay cameras and 3/4 QA previews!
    disc_objs = []

    # Main beveled hexagonal armor chassis (radius 0.225m, thickness 0.088m)
    disc_objs.append(add_beveled_prism(
        "HexDiscChassis",
        radius=0.228,
        height=0.086,
        sides=6,
        bevel_width=0.016,
        bevel_segments=2,
        mat=mat_slate,
        phase_offset=math.pi / 6.0,
    ))

    # Stepped metallic hexagonal upper armor ring bezel
    disc_objs.append(add_beveled_prism(
        "HexUpperArmorRing",
        radius=0.192,
        height=0.032,
        sides=6,
        location=(0.0, 0.0, 0.042),
        bevel_width=0.008,
        bevel_segments=1,
        mat=mat_gunmetal,
        phase_offset=math.pi / 6.0,
    ))

    # Rear recessed battery core housing
    disc_objs.append(add_beveled_prism(
        "HexRearBattery",
        radius=0.155,
        height=0.026,
        sides=6,
        location=(0.0, 0.0, -0.046),
        bevel_width=0.007,
        bevel_segments=1,
        mat=mat_gunmetal,
        phase_offset=math.pi / 6.0,
    ))

    # Central circular parabolic emitter aperture housing
    disc_objs.append(add_lathed(
        "EmitterApertureBezel",
        [
            (0.118, 0.048),
            (0.124, 0.058),
            (0.114, 0.074),
            (0.094, 0.076),
            (0.088, 0.062),
        ],
        segments=18,
        mat=mat_titanium,
        cap_bottom=False,
        cap_top=False,
    ))

    # Glowing Cyan Projector Dome Lens + Bright Concentric Inner Iris Ring
    disc_objs.append(add_lathed(
        "CyanProjectorLens",
        [
            (0.092, 0.056),
            (0.086, 0.072),
            (0.068, 0.088),
            (0.038, 0.096),
            (0.000, 0.098),
        ],
        segments=18,
        mat=mat_cyan_lens,
        cap_top=False,
    ))
    disc_objs.append(add_torus_ring(
        "LensOuterGlowRing",
        major_r=0.106,
        minor_r=0.006,
        major_segs=16,
        minor_segs=5,
        location=(0.0, 0.0, 0.074),
        mat=mat_cyan_hot,
    ))
    disc_objs.append(add_torus_ring(
        "LensInnerCoreRing",
        major_r=0.048,
        minor_r=0.0055,
        major_segs=14,
        minor_segs=5,
        location=(0.0, 0.0, 0.095),
        mat=mat_cyan_hot,
    ))

    # 6 Radial Projector Fin Vanes & Glowing Light-Guide Spokes to Hex Vertices
    for i in range(6):
        ang = i * (math.pi / 3.0) + math.pi / 6.0
        ca, sa = math.cos(ang), math.sin(ang)
        # Metallic emitter vane
        disc_objs.append(add_beveled_box(
            f"EmitterVane_{i}",
            size=(0.078, 0.022, 0.024),
            location=(0.158 * ca, 0.158 * sa, 0.054),
            rotation=(0.0, 0.0, ang),
            bevel_width=0.004,
            bevel_segments=1,
            mat=mat_cobalt if i % 2 == 0 else mat_titanium,
        ))
        # Glowing cyan light-guide trace inlaid into vane
        disc_objs.append(add_beveled_box(
            f"LightGuide_{i}",
            size=(0.064, 0.008, 0.008),
            location=(0.156 * ca, 0.156 * sa, 0.066),
            rotation=(0.0, 0.0, ang),
            bevel_width=0.0,
            bevel_segments=1,
            mat=mat_cyan_hot,
        ))

    # Twin Ergonomic Curved Side Grip Rails wrapping left & right edges of the disc
    for side_i, sgn in enumerate((-1.0, 1.0)):
        rail_pts = [
            (sgn * 0.190, -0.105, 0.005),
            (sgn * 0.252, -0.088, 0.014),
            (sgn * 0.268, 0.000, 0.022),
            (sgn * 0.252, 0.088, 0.014),
            (sgn * 0.190, 0.105, 0.005),
        ]
        disc_objs.append(add_tube_path(
            f"SideGripRail_{side_i}",
            rail_pts,
            radius=0.013,
            segments=6,
            mat=mat_titanium,
        ))
        # Rubberized tactile grip sleeve on center of rail
        grip_pts = [
            (sgn * 0.260, -0.052, 0.018),
            (sgn * 0.268, 0.000, 0.022),
            (sgn * 0.260, 0.052, 0.018),
        ]
        disc_objs.append(add_tube_path(
            f"SideGripSleeve_{side_i}",
            grip_pts,
            radius=0.018,
            segments=6,
            mat=mat_rubber,
        ))

    # Tilt the entire emitter disc cleanly to 48 degrees (facing forward-up toward -Y / +Z)
    tilt_rad = math.radians(48.0)
    rot_mat = Matrix.Rotation(tilt_rad, 4, "X")
    disc_pivot = Vector((0.0, 0.0, 0.210))
    for obj in disc_objs:
        # Bake transform around local origin then tilt + translate to disc_pivot
        m_local = obj.matrix_basis.copy()
        obj.matrix_world = Matrix.Translation(disc_pivot) @ rot_mat @ m_local
        objs.append(obj)

    # Integrated Heavy Grounded Tactical Deployment Sled / Cradle Base (Z=0.00..0.18)
    # Firmly connects to the bottom & rear of the tilted emitter disc with ZERO floating parts!
    objs.append(add_beveled_box(
        "CradleBasePlate",
        size=(0.300, 0.270, 0.036),
        location=(0.0, 0.015, 0.020),
        bevel_width=0.009,
        bevel_segments=1,
        mat=mat_gunmetal,
    ))
    # 4 Rubberized ground contact pads
    for sx in (-0.125, 0.125):
        for sy in (-0.095, 0.125):
            objs.append(add_beveled_box(
                f"SledPad_{sx:+.0f}_{sy:+.0f}",
                size=(0.056, 0.056, 0.016),
                location=(sx, sy, 0.008),
                bevel_width=0.0,
                bevel_segments=1,
                mat=mat_rubber,
            ))
    # Dual angled support yoke struts cradling the emitter disc chassis
    for side_i, sx in enumerate((-0.105, 0.105)):
        strut_pts = [
            (sx, -0.075, 0.032),
            (sx, -0.055, 0.110),
            (sx, 0.025, 0.185),
            (sx, 0.105, 0.032),
        ]
        objs.append(add_tube_path(
            f"CradleYokeStrut_{side_i}",
            strut_pts,
            radius=0.016,
            segments=6,
            mat=mat_cobalt,
        ))

    return export_asset(objs, "item_hardlight_cover.glb")


# ===========================================================================
# 6. IMPULSE BOOSTER THRUSTER PACK (item_impulse_booster.glb)
# ===========================================================================

def build_impulse_booster() -> dict:
    clear_scene()
    objs = []

    mat_gunmetal = make_pbr_mat("IB_Gunmetal", COL_GUNMETAL, metallic=0.84, roughness=0.28)
    mat_slate = make_pbr_mat("IB_DarkSlate", COL_DARK_SLATE, metallic=0.20, roughness=0.68)
    mat_rubber = make_pbr_mat("IB_Rubber", COL_RUBBER, metallic=0.0, roughness=0.88)
    mat_titanium = make_pbr_mat("IB_Titanium", COL_TITANIUM, metallic=0.86, roughness=0.24)
    mat_gold_metal = make_pbr_mat("IB_GoldAnodized", "#E5A00D", metallic=0.82, roughness=0.26)
    mat_trigger_red = make_pbr_mat("IB_TriggerRed", COL_GOOGLE_RED, metallic=0.20, roughness=0.38)
    mat_amber_glow = make_pbr_mat(
        "IB_AmberExhaust",
        "#FF9800",
        metallic=0.10,
        roughness=0.15,
        emission_hex="#FF9800",
        emission_strength=2.4,
    )
    mat_amber_hot = make_pbr_mat(
        "IB_AmberCoreHot",
        "#FFD000",
        metallic=0.0,
        roughness=0.10,
        emission_hex="#FFB300",
        emission_strength=3.6,
    )

    # Build Twin Symmetrical Turbine Thruster Pods (canted slightly outward 6 deg for dynamic stance)
    for side_i, sgn in enumerate((-1.0, 1.0)):
        pod_objs = []

        # Sculpted tapered aerodynamic turbine nacelle body (Z=0.10..0.41)
        pod_objs.append(add_lathed(
            f"TurbineNacelle_{side_i}",
            [
                (0.068, 0.100),
                (0.084, 0.145),
                (0.088, 0.285),
                (0.078, 0.365),
                (0.068, 0.404),
                (0.054, 0.382),
            ],
            segments=12,
            mat=mat_slate,
            cap_top=False,
        ))

        # Brushed titanium upper intake cowling shroud ring
        pod_objs.append(add_lathed(
            f"IntakeCowling_{side_i}",
            [
                (0.068, 0.378),
                (0.078, 0.398),
                (0.074, 0.422),
                (0.058, 0.422),
                (0.056, 0.385),
            ],
            segments=12,
            mat=mat_titanium,
            cap_bottom=False,
            cap_top=False,
        ))

        # Recessed Turbine Rotor Hub Cone + 6 Angled Compressor Fan Blades inside intake!
        pod_objs.append(add_lathed(
            f"IntakeHubCone_{side_i}",
            [(0.022, 0.372), (0.018, 0.395), (0.000, 0.412)],
            segments=8,
            mat=mat_gold_metal,
            cap_top=False,
        ))
        for b in range(6):
            bang = b * (math.pi / 3.0)
            ca, sa = math.cos(bang), math.sin(bang)
            pod_objs.append(add_beveled_box(
                f"FanBlade_{side_i}_{b}",
                size=(0.036, 0.011, 0.005),
                location=(0.036 * ca, 0.036 * sa, 0.388),
                rotation=(math.radians(28.0), 0.0, bang),
                bevel_width=0.0,
                bevel_segments=1,
                mat=mat_titanium,
            ))

        # Gold anodized trim band around upper nacelle
        pod_objs.append(add_lathed(
            f"GoldTrimBand_{side_i}",
            [(0.085, 0.285), (0.091, 0.292), (0.091, 0.312), (0.084, 0.317)],
            segments=12,
            mat=mat_gold_metal,
            cap_bottom=False,
            cap_top=False,
        ))

        # 3 Louvered Side Intake Vent Fins on outer flank
        for v_i, vz in enumerate((0.185, 0.222, 0.258)):
            pod_objs.append(add_beveled_box(
                f"SideVent_{side_i}_{v_i}",
                size=(0.026, 0.064, 0.014),
                location=(sgn * 0.088, 0.0, vz),
                rotation=(0.0, sgn * math.radians(22.0), 0.0),
                bevel_width=0.0,
                bevel_segments=1,
                mat=mat_gunmetal,
            ))

        # Flared Vectored Metallic Exhaust Nozzle Bell (Z=0.026..0.105)
        pod_objs.append(add_lathed(
            f"ExhaustNozzleBell_{side_i}",
            [
                (0.068, 0.108),
                (0.062, 0.084),
                (0.078, 0.032),
                (0.066, 0.030),
                (0.058, 0.068),
            ],
            segments=12,
            mat=mat_gunmetal,
            cap_bottom=False,
            cap_top=False,
        ))

        # Luminous Gold/Amber Exhaust Ring & Inner Afterburner Glow Core!
        pod_objs.append(add_torus_ring(
            f"AmberExhaustRing_{side_i}",
            major_r=0.072,
            minor_r=0.0075,
            major_segs=12,
            minor_segs=4,
            location=(0.0, 0.0, 0.036),
            mat=mat_amber_glow,
        ))
        pod_objs.append(add_lathed(
            f"AfterburnerCore_{side_i}",
            [(0.056, 0.052), (0.044, 0.068), (0.000, 0.095)],
            segments=8,
            mat=mat_amber_hot,
            cap_top=False,
        ))

        # Protective lower rubberized landing bumper skid around bottom of pod
        skid_pts = [
            (sgn * 0.045, -0.068, 0.016),
            (sgn * 0.084, -0.034, 0.016),
            (sgn * 0.084, 0.034, 0.016),
            (sgn * 0.045, 0.068, 0.016),
        ]
        pod_objs.append(add_tube_path(f"NozzleGuardSkid_{side_i}", skid_pts, radius=0.012, segments=5, mat=mat_rubber))
        # Vertical stanchions tying guard skid into nacelle body
        for st_i, sy in enumerate((-0.056, 0.056)):
            pod_objs.append(add_tube_path(
                f"SkidStrut_{side_i}_{st_i}",
                [(sgn * 0.066, sy, 0.016), (sgn * 0.076, sy * 0.85, 0.125)],
                radius=0.009,
                segments=5,
                mat=mat_gunmetal,
            ))

        # Cant pod outward 6 deg around Y and shift to +/- 0.132m
        cant = sgn * math.radians(-6.0)
        m_pod = Matrix.Translation(Vector((sgn * 0.132, 0.0, 0.0))) @ Matrix.Rotation(cant, 4, "Y")
        for obj in pod_objs:
            obj.matrix_world = m_pod @ obj.matrix_basis
            objs.append(obj)

    # Central Manifold Bridge & Fuel Core linking both turbines (X in [-0.075, 0.075])
    objs.append(add_beveled_box(
        "CentralManifold",
        size=(0.148, 0.136, 0.210),
        location=(0.0, 0.0, 0.245),
        bevel_width=0.016,
        bevel_segments=1,
        mat=mat_gunmetal,
    ))
    # Glowing vertical amber charge indicator bar on front & back of manifold
    for s_i, sy in enumerate((-0.071, 0.071)):
        objs.append(add_beveled_box(
            f"ChargeBar_{s_i}",
            size=(0.026, 0.008, 0.125),
            location=(0.0, sy, 0.245),
            bevel_width=0.0,
            bevel_segments=1,
            mat=mat_amber_glow,
        ))

    # Curved hydraulic fuel transfer hoses bridging central manifold to each turbine
    for side_i, sgn in enumerate((-1.0, 1.0)):
        hose_pts = [
            (sgn * 0.056, -0.055, 0.205),
            (sgn * 0.088, -0.092, 0.195),
            (sgn * 0.114, -0.076, 0.215),
        ]
        objs.append(add_tube_path(f"FuelHose_{side_i}", hose_pts, radius=0.011, segments=6, mat=mat_gold_metal))

    # Top Ergonomic Grip Arch & Prominent Activation Trigger Lever!
    grip_arch = [
        (-0.058, 0.0, 0.345),
        (-0.058, 0.0, 0.435),
        (-0.036, 0.0, 0.452),
        (0.036, 0.0, 0.452),
        (0.058, 0.0, 0.435),
        (0.058, 0.0, 0.345),
    ]
    objs.append(add_tube_path("BoosterGripBridge", grip_arch, radius=0.013, segments=6, mat=mat_titanium))
    objs.append(add_tube_path(
        "BoosterGripPad",
        [(-0.034, 0.0, 0.452), (0.034, 0.0, 0.452)],
        radius=0.017,
        segments=6,
        mat=mat_rubber,
    ))
    # Bright Crimson/Amber Squeeze Activation Trigger mounted directly below top grip bar
    objs.append(add_beveled_box(
        "ActivationTrigger",
        size=(0.056, 0.022, 0.018),
        location=(0.0, -0.010, 0.422),
        rotation=(math.radians(15.0), 0.0, 0.0),
        bevel_width=0.004,
        bevel_segments=1,
        mat=mat_trigger_red,
    ))
    # Trigger linkage stem
    objs.append(add_tube_path(
        "TriggerStem",
        [(0.024, -0.005, 0.426), (0.046, 0.0, 0.440)],
        radius=0.0055,
        segments=5,
        mat=mat_gold_metal,
    ))

    return export_asset(objs, "item_impulse_booster.glb")


# ===========================================================================
# 7. SUPPLY DROP CRATE + BEACON + RIGGED CANOPY (prop_supply_drop.glb)
# ===========================================================================

def build_supply_drop() -> dict:
    clear_scene()
    objs = []

    mat_gunmetal = make_pbr_mat("SD_Gunmetal", COL_GUNMETAL, metallic=0.80, roughness=0.34)
    mat_slate = make_pbr_mat("SD_DarkSlate", COL_DARK_SLATE, metallic=0.22, roughness=0.66)
    mat_steel = make_pbr_mat("SD_Steel", COL_BRUSHED_STEEL, metallic=0.88, roughness=0.26)
    mat_strap = make_pbr_mat("SD_WebbingStrap", "#20242B", metallic=0.0, roughness=0.85)
    mat_cable = make_pbr_mat("SD_ShroudCable", "#D1D5DB", metallic=0.30, roughness=0.55)
    mat_white_ripstop = make_pbr_mat("SD_CanopyWhite", "#F1F5F9", metallic=0.0, roughness=0.62)

    # Google 4-color bumper & canopy gore materials
    mat_g_blue = make_pbr_mat("SD_GoogleBlue", COL_GOOGLE_BLUE, metallic=0.18, roughness=0.38, coat=0.25)
    mat_g_red = make_pbr_mat("SD_GoogleRed", COL_GOOGLE_RED, metallic=0.18, roughness=0.38, coat=0.25)
    mat_g_yellow = make_pbr_mat("SD_GoogleYellow", COL_GOOGLE_YELLOW, metallic=0.18, roughness=0.38, coat=0.25)
    mat_g_green = make_pbr_mat("SD_GoogleGreen", COL_GOOGLE_GREEN, metallic=0.18, roughness=0.38, coat=0.25)
    google_mats = [mat_g_blue, mat_g_red, mat_g_yellow, mat_g_green]

    mat_beacon_glow = make_pbr_mat(
        "SD_GoldenBeacon",
        "#FF9900",
        metallic=0.05,
        roughness=0.10,
        emission_hex="#FFA800",
        emission_strength=2.6,
    )
    mat_stencil = make_textured_pbr_mat("SD_SideStencil", build_supply_drop_texture(512), metallic=0.22, roughness=0.48)

    # 1. Main Reinforced Chamfered Supply Crate Body (~1.26m cube grounded at Z=0)
    # Lower hull (Z=0.03..0.98) + Upper hinged lid (Z=0.98..1.25)
    objs.append(add_beveled_box(
        "CrateLowerHull",
        size=(1.22, 1.22, 0.94),
        location=(0.0, 0.0, 0.51),
        bevel_width=0.065,
        bevel_segments=2,
        mat=mat_slate,
    ))
    objs.append(add_beveled_box(
        "CrateUpperLid",
        size=(1.25, 1.25, 0.27),
        location=(0.0, 0.0, 1.115),
        bevel_width=0.052,
        bevel_segments=2,
        mat=mat_gunmetal,
    ))
    # Lid perimeter rubber gasket seam
    objs.append(add_beveled_box(
        "LidSeamGasket",
        size=(1.19, 1.19, 0.045),
        location=(0.0, 0.0, 0.98),
        bevel_width=0.0,
        bevel_segments=1,
        mat=mat_strap,
    ))

    # 2. Four Stenciled Side Marking Panels (Front -Y, Back +Y, Right +X, Left -X)
    hs = 0.445
    z0, z1 = 0.145, 0.875
    off = 0.614
    # Front (-Y)
    objs.append(add_uv_panel_quad(
        "StencilPanel_Front",
        [(-hs, -off, z0), (hs, -off, z0), (hs, -off, z1), (-hs, -off, z1)],
        mat=mat_stencil,
    ))
    # Back (+Y)
    objs.append(add_uv_panel_quad(
        "StencilPanel_Back",
        [(hs, off, z0), (-hs, off, z0), (-hs, off, z1), (hs, off, z1)],
        mat=mat_stencil,
    ))
    # Right (+X)
    objs.append(add_uv_panel_quad(
        "StencilPanel_Right",
        [(off, -hs, z0), (off, hs, z0), (off, hs, z1), (off, -hs, z1)],
        mat=mat_stencil,
    ))
    # Left (-X)
    objs.append(add_uv_panel_quad(
        "StencilPanel_Left",
        [(-off, hs, z0), (-off, -hs, z0), (-off, -hs, z1), (-off, hs, z1)],
        mat=mat_stencil,
    ))

    # 3. Google 4-Color Armored Corner Bumpers (4 bottom ground bumpers at Z=0 + 4 top corner guards)
    corners_xy = [(-0.56, -0.56), (0.56, -0.56), (0.56, 0.56), (-0.56, 0.56)]
    for idx, (cx, cy) in enumerate(corners_xy):
        gmat = google_mats[idx]
        # Bottom heavy bumper foot (touches Z=0.00)
        objs.append(add_beveled_box(
            f"CornerBumperBot_{idx}",
            size=(0.24, 0.24, 0.22),
            location=(cx, cy, 0.11),
            bevel_width=0.032,
            bevel_segments=1,
            mat=gmat,
        ))
        # Top corner armor bumper
        objs.append(add_beveled_box(
            f"CornerBumperTop_{idx}",
            size=(0.24, 0.24, 0.20),
            location=(cx, cy, 1.155),
            bevel_width=0.030,
            bevel_segments=1,
            mat=gmat,
        ))
        # Vertical corner reinforcement pillar tying bottom & top bumpers
        objs.append(add_beveled_box(
            f"CornerPillar_{idx}",
            size=(0.14, 0.14, 0.86),
            location=(cx * 1.01, cy * 1.01, 0.64),
            bevel_width=0.0,
            bevel_segments=1,
            mat=mat_gunmetal,
        ))

    # 4. Industrial Dual Steel Clamping Latches (front & back) + Recessed Side Grab Handles (left & right)
    for f_i, sy in enumerate((-0.635, 0.635)):
        for l_i, lx in enumerate((-0.30, 0.30)):
            objs.append(add_beveled_box(
                f"LidLatch_{f_i}_{l_i}",
                size=(0.095, 0.048, 0.185),
                location=(lx, sy, 0.985),
                bevel_width=0.010,
                bevel_segments=1,
                mat=mat_steel,
            ))
    for s_i, sx in enumerate((-0.635, 0.635)):
        sgn = -1.0 if sx < 0 else 1.0
        h_pts = [
            (sx, -0.18, 0.96),
            (sx + sgn * 0.055, -0.15, 0.96),
            (sx + sgn * 0.055, 0.15, 0.96),
            (sx, 0.18, 0.96),
        ]
        objs.append(add_tube_path(f"SideGrabHandle_{s_i}", h_pts, radius=0.018, segments=5, mat=mat_steel))

    # 5. Top Golden Flare Beacon Mount & Protective Roll-Cage (Z=1.25..1.55)
    objs.append(add_lathed(
        "BeaconTurretBase",
        [(0.22, 1.24), (0.20, 1.29), (0.14, 1.35)],
        segments=12,
        mat=mat_gunmetal,
    ))
    objs.append(add_lathed(
        "BeaconGoldenLens",
        [(0.125, 1.345), (0.128, 1.425), (0.092, 1.492), (0.000, 1.522)],
        segments=12,
        mat=mat_beacon_glow,
        cap_top=False,
    ))
    # Protective cross-arches over golden beacon
    for a_i, ang in enumerate((0.0, math.pi * 0.5)):
        ca, sa = math.cos(ang), math.sin(ang)
        cage_pts = [
            (-0.18 * ca, -0.18 * sa, 1.28),
            (-0.15 * ca, -0.15 * sa, 1.49),
            (0.0, 0.0, 1.560),
            (0.15 * ca, 0.15 * sa, 1.49),
            (0.18 * ca, 0.18 * sa, 1.28),
        ]
        objs.append(add_tube_path(f"BeaconCage_{a_i}", cage_pts, radius=0.014, segments=5, mat=mat_steel))

    # 6. Top Parachute Rigging Harness: 4 Corner D-Ring Brackets + Crossed Webbing Straps
    harness_anchors = [(-0.50, -0.50, 1.265), (0.50, -0.50, 1.265), (0.50, 0.50, 1.265), (-0.50, 0.50, 1.265)]
    for idx, (ax, ay, az) in enumerate(harness_anchors):
        # Corner steel anchor lug
        objs.append(add_beveled_box(
            f"HarnessAnchor_{idx}",
            size=(0.11, 0.11, 0.055),
            location=(ax, ay, az),
            bevel_width=0.0,
            bevel_segments=1,
            mat=mat_steel,
        ))
        # Taut webbing strap from anchor to central beacon collar
        strap_pts = [
            (ax, ay, az + 0.012),
            (ax * 0.34, ay * 0.34, 1.310),
        ]
        objs.append(add_tube_path(f"HarnessStrap_{idx}", strap_pts, radius=0.020, segments=5, mat=mat_strap))

    # 7. Deployed 8-Gore Tactical Parachute Canopy + 8 Physical Shroud Cables (Z=2.08..2.58)
    # Built as a multi-material scalloped dome canopy so all 4 Google colors shine alternating with crisp white!
    bm = bmesh.new()
    gores = 8
    rad_rings = [
        (0.00, 2.575),
        (0.32, 2.525),
        (0.70, 2.375),
        (0.98, 2.095),
    ]
    # Add intermediate midpoint vertices on each gore for smooth curved dome & scalloped lower hem
    sub_segs = gores * 2
    ring_verts = []
    for r_idx, (rad, z_h) in enumerate(rad_rings):
        if rad == 0.0:
            ring_verts.append([bm.verts.new((0.0, 0.0, z_h))])
        else:
            rv = []
            for s in range(sub_segs):
                ang = (2.0 * math.pi * s) / sub_segs + math.pi / 8.0
                # Slight scalloped lift on odd (mid-gore) vertices along outer hem
                scallop_z = 0.048 if (r_idx == len(rad_rings) - 1 and s % 2 == 1) else 0.0
                puff_r = rad * (1.035 if s % 2 == 1 and r_idx >= 2 else 1.0)
                rv.append(bm.verts.new((puff_r * math.cos(ang), puff_r * math.sin(ang), z_h + scallop_z)))
            ring_verts.append(rv)

    # Create gore faces with material slots: 0=white, 1=blue, 2=red, 3=yellow, 4=green
    gore_mat_map = [1, 0, 2, 0, 3, 0, 4, 0]
    for r_idx in range(len(ring_verts) - 1):
        r0 = ring_verts[r_idx]
        r1 = ring_verts[r_idx + 1]
        for s in range(sub_segs):
            s2 = (s + 1) % sub_segs
            gore_id = s // 2
            mat_slot = gore_mat_map[gore_id]
            if len(r0) == 1:
                f = bm.faces.new((r0[0], r1[s2], r1[s]))
            else:
                f = bm.faces.new((r0[s], r0[s2], r1[s2], r1[s]))
            f.material_index = mat_slot

    # Give the canopy real physical thickness (double-sided solidified shell) so underside renders cleanly!
    geom_solid = bmesh.ops.solidify(bm, geom=list(bm.faces), thickness=0.022)
    del geom_solid
    canopy_obj = link_mesh_object("ParachuteCanopy", bm, mat=None)
    for m in (mat_white_ripstop, mat_g_blue, mat_g_red, mat_g_yellow, mat_g_green):
        canopy_obj.data.materials.append(m)
    objs.append(canopy_obj)

    # Apex stabilization vent cap at top of parachute
    objs.append(add_lathed(
        "CanopyApexCap",
        [(0.18, 2.555), (0.12, 2.592), (0.00, 2.600)],
        segments=10,
        mat=mat_gunmetal,
        cap_top=False,
    ))

    # 8 Taut Shroud Suspension Lines physically linking the 4 corner harness anchors to all 8 gore tips
    for g in range(gores):
        s_idx = g * 2
        ang = (2.0 * math.pi * s_idx) / sub_segs + math.pi / 8.0
        tip = (0.97 * math.cos(ang), 0.97 * math.sin(ang), 2.10)
        # Connect to nearest corner harness anchor
        best_anchor = min(
            harness_anchors,
            key=lambda a: (a[0] - tip[0]) ** 2 + (a[1] - tip[1]) ** 2,
        )
        objs.append(add_tube_path(
            f"ShroudLine_{g}",
            [(best_anchor[0], best_anchor[1], best_anchor[2] + 0.02), tip],
            radius=0.009,
            segments=4,
            mat=mat_cable,
        ))

    return export_asset(objs, "prop_supply_drop.glb")


# ===========================================================================
# 8. SKY-DROP TACTICAL WING GLIDER (prop_glider.glb)
# ===========================================================================

def build_glider() -> dict:
    clear_scene()
    objs = []

    mat_canopy_white = make_pbr_mat("GL_CanopyWhite", "#EEF2F7", metallic=0.04, roughness=0.42, coat=0.20)
    mat_carbon = make_pbr_mat("GL_CarbonFrame", "#1F252F", metallic=0.35, roughness=0.45)
    mat_titanium = make_pbr_mat("GL_TitaniumTubing", COL_TITANIUM, metallic=0.86, roughness=0.25)
    mat_rubber = make_pbr_mat("GL_RubberGrip", COL_RUBBER, metallic=0.0, roughness=0.88)
    mat_g_blue = make_pbr_mat("GL_GoogleBlue", COL_GOOGLE_BLUE, metallic=0.14, roughness=0.36, coat=0.25)
    mat_g_red = make_pbr_mat("GL_GoogleRed", COL_GOOGLE_RED, metallic=0.14, roughness=0.36, coat=0.25)
    mat_g_yellow = make_pbr_mat("GL_GoogleYellow", COL_GOOGLE_YELLOW, metallic=0.14, roughness=0.36, coat=0.25)
    mat_g_green = make_pbr_mat("GL_GoogleGreen", COL_GOOGLE_GREEN, metallic=0.14, roughness=0.36, coat=0.25)
    mat_nav_cyan = make_pbr_mat(
        "GL_NavLightCyan",
        COL_CYAN_BRIGHT,
        metallic=0.0,
        roughness=0.10,
        emission_hex=COL_CYAN_BRIGHT,
        emission_strength=4.5,
    )

    # -----------------------------------------------------------------------
    # 1. Aerodynamic Multi-Ribbed Swept Tactical Wing Canopy
    # Wingspan X in [-1.60m, +1.60m] (3.20m span), Nose +Y, Overhead Z ~ 0.72..0.95m
    # -----------------------------------------------------------------------
    # 11 spanwise airfoil stations (symmetric, 5 bays per side -> 10 bays total)
    # Each station: (x_pos, y_lead, y_trail, z_base, thickness, rib_bump)
    half_stations = [
        (0.00,  0.58, -0.50, 0.86, 0.088),
        (0.28,  0.46, -0.58, 0.89, 0.082),
        (0.60,  0.30, -0.66, 0.92, 0.074),
        (0.95,  0.10, -0.72, 0.93, 0.064),
        (1.30, -0.14, -0.76, 0.88, 0.052),
        (1.58, -0.40, -0.82, 0.78, 0.036),
    ]
    stations = [(-x, yl, yt, zb, th) for (x, yl, yt, zb, th) in reversed(half_stations[1:])] + half_stations

    # Cambered airfoil section points (normalized chord s in [0..1] from LE to TE):
    # Closed loop around cross-section: LE -> Upper camber -> TE -> Lower camber
    airfoil_profile = [
        (0.00,  0.00),   # Leading edge
        (0.14,  0.58),   # Upper front
        (0.36,  0.72),   # Upper peak camber
        (0.68,  0.44),   # Upper aft
        (1.00, -0.04),   # Trailing edge
        (0.64,  0.02),   # Lower aft (concave undercamber)
        (0.24, -0.16),   # Lower belly
    ]
    n_prof = len(airfoil_profile)

    bm = bmesh.new()
    station_rings = []
    for (sx, y_le, y_te, zb, thick) in stations:
        chord = y_le - y_te
        ring = []
        for (s_frac, z_norm) in airfoil_profile:
            py = y_le - s_frac * chord
            pz = zb + z_norm * thick
            ring.append(bm.verts.new((sx, py, pz)))
        station_rings.append(ring)

    # Material slots on wing canopy:
    # 0=white, 1=carbon, 2=blue, 3=red, 4=yellow, 5=green
    # Assign bold Workspace 4-color accent panels across the swept wing bays!
    # Bays 0..9 from left tip (-X) to right tip (+X):
    # Port side (-X): bay 0=carbon tip, bay 1=Blue, bay 2=Red, bay 3=White, bay 4=White/Carbon
    # Starboard side (+X): bay 5=White/Carbon, bay 6=White, bay 7=Yellow, bay 8=Green, bay 9=carbon tip
    bay_upper_mats = [1, 2, 3, 0, 0, 0, 0, 4, 5, 1]
    for b_idx in range(len(station_rings) - 1):
        r0 = station_rings[b_idx]
        r1 = station_rings[b_idx + 1]
        bay_mat = bay_upper_mats[b_idx]
        for p_idx in range(n_prof):
            p2 = (p_idx + 1) % n_prof
            f = bm.faces.new((r0[p_idx], r1[p_idx], r1[p2], r0[p2]))
            # Leading edge band (p_idx == 0) in carbon for sleek aerodynamic contrast
            if p_idx == 0:
                f.material_index = 1
            elif p_idx in (1, 2, 3):
                # Upper wing surface displays Workspace four-color bay accents!
                f.material_index = bay_mat
            else:
                # Underside shows crisp white with subtle matching color trim on inner bays
                f.material_index = bay_mat if bay_mat in (2, 3, 4, 5) else 0

    # Cap wingtips cleanly
    bm.faces.new(list(reversed(station_rings[0])))
    bm.faces.new(station_rings[-1])

    wing_obj = link_mesh_object("GliderWingCanopy", bm, mat=None)
    for m in (mat_canopy_white, mat_carbon, mat_g_blue, mat_g_red, mat_g_yellow, mat_g_green):
        wing_obj.data.materials.append(m)
    objs.append(wing_obj)

    # Raised Sculpted Aerodynamic Rib Battens along the wing stations (visible multi-ribbed structure!)
    for idx, (sx, y_le, y_te, zb, thick) in enumerate(stations):
        if idx in (0, len(stations) - 1):
            continue  # Wingtips get winglets instead
        chord = y_le - y_te
        rib_pts = [
            (sx, y_le - 0.04 * chord, zb + 0.16 * thick),
            (sx, y_le - 0.18 * chord, zb + 0.68 * thick),
            (sx, y_le - 0.42 * chord, zb + 0.74 * thick),
            (sx, y_le - 0.74 * chord, zb + 0.40 * thick),
            (sx, y_te + 0.02 * chord, zb - 0.02 * thick),
        ]
        objs.append(add_tube_path(f"WingRibBatten_{idx}", rib_pts, radius=0.011, segments=6, mat=mat_carbon))

    # Sleek Canted Aerodynamic Wingtip Winglets + Glowing Nav Tip Accents (X = +/-1.58m -> +/-1.64m)
    for side_i, sgn in enumerate((-1.0, 1.0)):
        winglet = add_beveled_box(
            f"WingtipWinglet_{side_i}",
            size=(0.028, 0.44, 0.24),
            location=(sgn * 1.595, -0.61, 0.885),
            rotation=(math.radians(-16.0), sgn * math.radians(22.0), sgn * math.radians(-6.0)),
            bevel_width=0.008,
            bevel_segments=1,
            mat=mat_carbon,
        )
        objs.append(winglet)
        objs.append(add_beveled_box(
            f"WingtipNavLight_{side_i}",
            size=(0.022, 0.16, 0.024),
            location=(sgn * 1.622, -0.52, 0.945),
            rotation=(math.radians(-16.0), sgn * math.radians(22.0), sgn * math.radians(-6.0)),
            bevel_width=0.004,
            bevel_segments=1,
            mat=mat_nav_cyan,
        ))

    # -----------------------------------------------------------------------
    # 2. Central Keel Spine, Nose Cone & Under-Wing Spreader Frame
    # -----------------------------------------------------------------------
    keel_pts = [
        (0.0, 0.62, 0.86),
        (0.0, 0.25, 0.84),
        (0.0, -0.15, 0.82),
        (0.0, -0.54, 0.80),
    ]
    objs.append(add_tube_path("CentralKeelSpine", keel_pts, radius=[0.022, 0.032, 0.030, 0.020], segments=8, mat=mat_carbon))

    # Glowing cyan aerodynamic nose beacon strip
    objs.append(add_beveled_box(
        "NoseBeaconAccent",
        size=(0.055, 0.11, 0.032),
        location=(0.0, 0.56, 0.875),
        rotation=(math.radians(-10.0), 0.0, 0.0),
        bevel_width=0.008,
        bevel_segments=1,
        mat=mat_nav_cyan,
    ))

    # Under-wing titanium tubular crossbar spreader connecting keel to mid-wings
    spreader_pts = [
        (-1.12, -0.18, 0.86),
        (-0.52, 0.04, 0.84),
        (0.00, 0.14, 0.80),
        (0.52, 0.04, 0.84),
        (1.12, -0.18, 0.86),
    ]
    objs.append(add_tube_path("UnderWingSpreader", spreader_pts, radius=0.016, segments=8, mat=mat_titanium))

    # -----------------------------------------------------------------------
    # 3. Tubular A-Frame Trapeze & Twin Hanging Hand-Grips (Pivot at Origin 0,0,0)
    # -----------------------------------------------------------------------
    # Central overhead pivot bracket under keel
    objs.append(add_beveled_box(
        "KeelMountHub",
        size=(0.12, 0.16, 0.075),
        location=(0.0, 0.04, 0.785),
        bevel_width=0.012,
        bevel_segments=1,
        mat=mat_carbon,
    ))

    # A-Frame downtubes descending cleanly from KeelMountHub to Trapeze Bar at Z=0.0, Y=0.0
    for side_i, sgn in enumerate((-1.0, 1.0)):
        # Main front/side structural downtube
        objs.append(add_tube_path(
            f"AFrameDownTube_{side_i}",
            [(sgn * 0.045, 0.04, 0.78), (sgn * 0.22, 0.02, 0.40), (sgn * 0.36, 0.00, 0.00)],
            radius=0.016,
            segments=8,
            mat=mat_titanium,
        ))
        # Diagonal brace up to under-wing spreader for rigid triangulated look
        objs.append(add_tube_path(
            f"WingBraceStrut_{side_i}",
            [(sgn * 0.22, 0.02, 0.40), (sgn * 0.62, 0.00, 0.85)],
            radius=0.011,
            segments=6,
            mat=mat_carbon,
        ))
        # Rear tension stability cable from trapeze corner to aft keel
        objs.append(add_tube_path(
            f"AftStabilizerCable_{side_i}",
            [(sgn * 0.35, 0.00, 0.01), (0.0, -0.44, 0.80)],
            radius=0.007,
            segments=5,
            mat=mat_titanium,
        ))

    # Horizontal Trapeze Control Bar centered EXACTLY at (0, 0, 0)
    objs.append(add_tube_path(
        "ControlTrapezeBar",
        [(-0.37, 0.0, 0.0), (0.37, 0.0, 0.0)],
        radius=0.017,
        segments=10,
        mat=mat_titanium,
    ))

    # Twin Ergonomic Hanging Hand-Grips symmetrically centered at X = +/-0.24m, Y = 0.0, Z = 0.0
    for side_i, sgn in enumerate((-1.0, 1.0)):
        # Thick sculpted rubberized palm grip sleeve right on the control bar
        objs.append(add_tube_path(
            f"HandGripSleeve_{side_i}",
            [(sgn * 0.16, 0.0, 0.0), (sgn * 0.31, 0.0, 0.0)],
            radius=0.024,
            segments=10,
            mat=mat_rubber,
        ))
        # Anodized Google-accented locking end collars flanking each hand-grip
        for c_i, cx in enumerate((sgn * 0.155, sgn * 0.315)):
            objs.append(add_lathed(
                f"GripCollar_{side_i}_{c_i}",
                [(0.020, -0.012), (0.027, -0.008), (0.027, 0.008), (0.020, 0.012)],
                segments=12,
                location=(cx, 0.0, 0.0),
                rotation=(0.0, math.pi * 0.5, 0.0),
                mat=mat_g_blue if side_i == 0 else mat_g_green,
            ))

    # IMPORTANT: Keep glider pivot centered exactly on hand-grip origin (0, 0, 0)!
    return export_asset(objs, "prop_glider.glb", center_xy=False, ground_z=False)


# ===========================================================================
# 9. GOOGLEPLEX TACTICAL LOOT CHEST (prop_loot_chest.glb)
# ===========================================================================

def _apply_bevel_modifier(
    obj: bpy.types.Object,
    width: float = 0.011,
    segments: int = 2,
    angle_deg: float = 30.0,
) -> None:
    """Apply a Blender BEVEL modifier (angle-limited, clamp_overlap) cleanly in place."""
    if obj.type != "MESH" or width <= 0.0:
        return
    bev = obj.modifiers.new(name="Bevel", type="BEVEL")
    bev.limit_method = "ANGLE"
    bev.angle_limit = math.radians(angle_deg)
    bev.offset_type = "OFFSET"
    bev.width = width
    bev.segments = segments
    bev.profile = 0.5
    bev.use_clamp_overlap = True

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=bev.name)
    set_smooth(obj)


def _apply_weighted_normal(obj: bpy.types.Object) -> None:
    """Apply face-area WEIGHTED_NORMAL modifier for crisp hard-surface flat panels + smooth bevels."""
    if obj.type != "MESH":
        return
    set_smooth(obj)
    wn = obj.modifiers.new(name="WeightedNormal", type="WEIGHTED_NORMAL")
    wn.mode = "FACE_AREA"
    wn.weight = 50
    wn.keep_sharp = False

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=wn.name)


def _join_mesh_group(name: str, parts: list[bpy.types.Object]) -> bpy.types.Object:
    """Bake local transforms on a list of sibling mesh parts and join into one clean multi-material mesh at (0,0,0)."""
    bpy.ops.object.select_all(action="DESELECT")
    for p in parts:
        p.select_set(True)
    bpy.context.view_layer.objects.active = parts[0]
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    if len(parts) > 1:
        bpy.ops.object.join()
    joined = bpy.context.view_layer.objects.active
    joined.name = name
    joined.data.name = f"{name}_Data"
    joined.location = Vector((0.0, 0.0, 0.0))
    joined.rotation_euler = Euler((0.0, 0.0, 0.0), "XYZ")
    joined.scale = Vector((1.0, 1.0, 1.0))
    _apply_weighted_normal(joined)
    return joined


def _make_rect_profile_solid(
    name: str,
    rings: list[tuple[float, float, float, float, float]],
    ring_mat_indices: list[int],
    cap_start_mat: int,
    cap_end_mat: int,
    materials: list[bpy.types.Material],
) -> bpy.types.Object:
    """Create a closed watertight rectangular-section solid from ordered rings (x0, x1, y0, y1, z).
    Used for hollow beveled armored hulls and domed shells with exact material index assignments.
    """
    bm = bmesh.new()
    bm_rings = []
    for (x0, x1, y0, y1, z) in rings:
        bm_rings.append([
            bm.verts.new((x0, y0, z)),
            bm.verts.new((x1, y0, z)),
            bm.verts.new((x1, y1, z)),
            bm.verts.new((x0, y1, z)),
        ])

    for r_idx in range(len(bm_rings) - 1):
        ra = bm_rings[r_idx]
        rb = bm_rings[r_idx + 1]
        mat_idx = ring_mat_indices[r_idx]
        for s in range(4):
            s2 = (s + 1) % 4
            f = bm.faces.new((ra[s], ra[s2], rb[s2], rb[s]))
            f.material_index = mat_idx

    f_start = bm.faces.new(list(reversed(bm_rings[0])))
    f_start.material_index = cap_start_mat
    f_end = bm.faces.new(bm_rings[-1])
    f_end.material_index = cap_end_mat

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    obj = link_mesh_object(name, bm, mat=None)
    for m in materials:
        obj.data.materials.append(m)
    return obj


def _make_extruded_yz_profile(
    name: str,
    yz_pts: list[tuple[float, float]],
    x_center: float,
    width_x: float,
    mat: bpy.types.Material,
) -> bpy.types.Object:
    """Create a closed watertight prism extruded along X from a 2D (y, z) polygon."""
    bm = bmesh.new()
    hx = width_x * 0.5
    v_left = [bm.verts.new((x_center - hx, y, z)) for (y, z) in yz_pts]
    v_right = [bm.verts.new((x_center + hx, y, z)) for (y, z) in yz_pts]
    n = len(yz_pts)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((v_left[i], v_left[j], v_right[j], v_right[i]))
    bm.faces.new(list(reversed(v_left)))
    bm.faces.new(v_right)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return link_mesh_object(name, bm, mat=mat)


def _make_rect_frame_ring(
    name: str,
    outer_hx: float,
    outer_hy: float,
    inner_hx: float,
    inner_hy: float,
    z0: float,
    z1: float,
    mat: bpy.types.Material,
) -> bpy.types.Object:
    """Create a clean hollow rectangular bezel/rim strip spanning z0..z1 around origin."""
    bm = bmesh.new()
    ob = [
        bm.verts.new((-outer_hx, -outer_hy, z0)),
        bm.verts.new((+outer_hx, -outer_hy, z0)),
        bm.verts.new((+outer_hx, +outer_hy, z0)),
        bm.verts.new((-outer_hx, +outer_hy, z0)),
    ]
    ot = [
        bm.verts.new((-outer_hx, -outer_hy, z1)),
        bm.verts.new((+outer_hx, -outer_hy, z1)),
        bm.verts.new((+outer_hx, +outer_hy, z1)),
        bm.verts.new((-outer_hx, +outer_hy, z1)),
    ]
    ib = [
        bm.verts.new((-inner_hx, -inner_hy, z0)),
        bm.verts.new((+inner_hx, -inner_hy, z0)),
        bm.verts.new((+inner_hx, +inner_hy, z0)),
        bm.verts.new((-inner_hx, +inner_hy, z0)),
    ]
    it = [
        bm.verts.new((-inner_hx, -inner_hy, z1)),
        bm.verts.new((+inner_hx, -inner_hy, z1)),
        bm.verts.new((+inner_hx, +inner_hy, z1)),
        bm.verts.new((-inner_hx, +inner_hy, z1)),
    ]
    for s in range(4):
        s2 = (s + 1) % 4
        bm.faces.new((ob[s], ob[s2], ot[s2], ot[s]))  # outer wall
        bm.faces.new((it[s], it[s2], ib[s2], ib[s]))  # inner wall
        bm.faces.new((ot[s], ot[s2], it[s2], it[s]))  # top cap
        bm.faces.new((ib[s], ib[s2], ob[s2], ob[s]))  # bottom cap
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return link_mesh_object(name, bm, mat=mat)


def build_loot_chest() -> dict:
    """Build the beveled PBR Googleplex Tactical Loot Chest (prop_loot_chest.glb).

    Coordinate & Hierarchy Spec:
      - Dimensions: ~1.08m wide (X), ~0.68m deep (Y), ~0.64m tall (Z), grounded cleanly at Z=0.0.
      - Front magnetic clasps & glowing LED status bar face +Y in Blender (-Z in Three.js).
      - Parent Empty `ChestBase` at (0, 0, 0) owns `ChestBaseMesh` (armored lower hull,
        reinforced corner bumpers, side carry handles, lower latch plates, rear hinge clevis
        mounts, recessed interior loot tray at Z~0.34m with glowing rim).
      - Child Empty `ChestLid` positioned AT EXACT REAR HINGE LINE (0, -0.31, +0.42) in Blender
        -> (0, +0.42, +0.31) in Three.js Y-up, owning `ChestLidMesh` in local hinge coordinates.
      - Opening rotation: +100 deg (+1.7453 rad) around +X in BOTH Blender and Three.js Y-up
        swings the lid upward & backward cleanly with zero clipping or detachment!
      - Named material slot `RarityAccent` drives runtime Tier 1 (Amber), Tier 2 (Cobalt Blue),
        and Tier 3 (Royal Purple/Gold) tinting across front LED strip, top beacon bar, side
        accent chevrons, latch indicators, and inner recessed tray glow rim.
    """
    clear_scene()

    # Exact PBR Materials per Spec
    mat_slate_steel = make_pbr_mat("LC_SlateSteel", "#48566A", metallic=0.78, roughness=0.32, coat=0.14)
    mat_dark_recess = make_pbr_mat("LC_DarkRecess", "#222A36", metallic=0.52, roughness=0.46)
    mat_polymer = make_pbr_mat("LC_CharcoalPolymer", "#1E222A", metallic=0.03, roughness=0.80)
    mat_warm_metal = make_pbr_mat("LC_WarmClaspMetal", "#D4AC72", metallic=0.88, roughness=0.24, coat=0.12)
    mat_tray_bed = make_pbr_mat("LC_TrayBed", "#171D27", metallic=0.14, roughness=0.72)
    # REQUIRED RUNTIME HOOK: Named material slot `RarityAccent` (default Tier 1 Warm Amber/Bronze)
    mat_rarity = make_pbr_mat(
        "RarityAccent",
        "#F59E0B",
        metallic=0.20,
        roughness=0.18,
        emission_hex="#FF9500",
        emission_strength=1.9,
    )

    hinge_y = -0.310
    hinge_z = 0.420

    # =======================================================================
    # PART A: CHEST BASE (world origin 0, 0, 0; grounded cleanly at Z=0.0)
    # =======================================================================
    base_parts: list[bpy.types.Object] = []

    # 1. Hollow Beveled Armored Lower Hull (BEVEL modifier segments=2, recessed bay at Z=0.340..0.416)
    base_hull = _make_rect_profile_solid(
        "BaseHull",
        rings=[
            (-0.474, +0.474, -0.278, +0.278, 0.022),  # 0: bottom outer base
            (-0.502, +0.502, -0.302, +0.302, 0.072),  # 1: lower outer bevel shoulder
            (-0.502, +0.502, -0.302, +0.302, 0.384),  # 2: upper outer wall
            (-0.490, +0.490, -0.292, +0.292, 0.416),  # 3: top outer chamfer
            (-0.436, +0.436, -0.242, +0.242, 0.416),  # 4: top inner rim
            (-0.420, +0.420, -0.226, +0.226, 0.340),  # 5: recessed loot tray floor
        ],
        ring_mat_indices=[0, 0, 0, 1, 1],
        cap_start_mat=0,
        cap_end_mat=2,
        materials=[mat_slate_steel, mat_dark_recess, mat_tray_bed],
    )
    _apply_bevel_modifier(base_hull, width=0.011, segments=2, angle_deg=44.0)
    base_parts.append(base_hull)

    # 2. Top Perimeter Rubberized Sealing Gasket Seam (Z=0.414..0.421)
    base_parts.append(_make_rect_frame_ring(
        "BaseGasketRim",
        outer_hx=0.484,
        outer_hy=0.286,
        inner_hx=0.444,
        inner_hy=0.248,
        z0=0.414,
        z1=0.421,
        mat=mat_polymer,
    ))

    # 3. Recessed Interior Loot Tray Cradle + Glowing RarityAccent Perimeter Rim & Energy Strips
    base_parts.append(add_beveled_box(
        "InteriorTrayCradle",
        size=(0.76, 0.37, 0.012),
        location=(0.0, 0.0, 0.346),
        bevel_width=0.0,
        bevel_segments=1,
        mat=mat_tray_bed,
    ))

    # Two transverse tray divider cushions inside bay
    for d_i, dx in enumerate((-0.145, +0.145)):
        base_parts.append(add_beveled_box(
            f"TrayDivider_{d_i}",
            size=(0.024, 0.33, 0.016),
            location=(dx, 0.0, 0.355),
            bevel_width=0.0,
            bevel_segments=1,
            mat=mat_dark_recess,
        ))

    # Glowing RarityAccent Inner Tray Perimeter Rim (hugs inside of recessed bay at Z=0.350..0.366)
    base_parts.append(_make_rect_frame_ring(
        "TrayGlowRim",
        outer_hx=0.418,
        outer_hy=0.224,
        inner_hx=0.394,
        inner_hy=0.200,
        z0=0.350,
        z1=0.366,
        mat=mat_rarity,
    ))

    # Three glowing recessed loot-pad power strips across tray bed
    for b_i, bx in enumerate((-0.27, 0.0, +0.27)):
        base_parts.append(add_beveled_box(
            f"TrayEnergyBar_{b_i}",
            size=(0.034, 0.28, 0.008),
            location=(bx, 0.0, 0.353),
            bevel_width=0.0,
            bevel_segments=1,
            mat=mat_rarity,
        ))

    # 4. Grounded Base Polymer Skid Rails (rest cleanly on Z=0.000)
    for s_i, sx in enumerate((-0.36, +0.36)):
        base_parts.append(add_beveled_box(
            f"BaseSkid_{s_i}",
            size=(0.15, 0.54, 0.024),
            location=(sx, 0.0, 0.012),
            bevel_width=0.0,
            bevel_segments=1,
            mat=mat_polymer,
        ))

    # 5. Four Heavy Reinforced Corner Bumpers (grounded at Z=0.000; strictly outside recessed tray cavity)
    for c_i, (sx, sy) in enumerate(((-1.0, +1.0), (+1.0, +1.0), (-1.0, -1.0), (+1.0, -1.0))):
        y_out = 0.324 if sy > 0 else 0.314
        z_top = 0.376
        bx_w = 0.094
        by_d = 0.078
        bumper = add_beveled_box(
            f"CornerBumper_{c_i}",
            size=(bx_w, by_d, z_top),
            location=(sx * (0.526 - bx_w * 0.5), sy * (y_out - by_d * 0.5), z_top * 0.5),
            bevel_width=0.012,
            bevel_segments=1,
            mat=mat_polymer,
        )
        base_parts.append(bumper)

    # 6. Front Armored Fascia (+Y face) & Dual Lower Magnetic Latch Plates
    front_fascia = add_beveled_box(
        "FrontCenterFascia",
        size=(0.30, 0.024, 0.21),
        location=(0.0, +0.309, 0.215),
        bevel_width=0.006,
        bevel_segments=1,
        mat=mat_dark_recess,
    )
    base_parts.append(front_fascia)

    # Sleek warm metallic emblem bar & lower RarityAccent trim bar across front center fascia
    base_parts.append(add_beveled_box(
        "FrontEmblemBar",
        size=(0.22, 0.012, 0.026),
        location=(0.0, +0.322, 0.260),
        bevel_width=0.0,
        bevel_segments=1,
        mat=mat_warm_metal,
    ))
    base_parts.append(add_beveled_box(
        "FrontLowerAccentBar",
        size=(0.18, 0.010, 0.016),
        location=(0.0, +0.322, 0.215),
        bevel_width=0.0,
        bevel_segments=1,
        mat=mat_rarity,
    ))

    # Dual Lower Magnetic Latch Housings + Warm Metal Striker Plates at X = +/-0.27, Y = +0.32
    for l_i, lx in enumerate((-0.27, +0.27)):
        base_parts.append(add_beveled_box(
            f"LowerLatchPocket_{l_i}",
            size=(0.112, 0.026, 0.110),
            location=(lx, +0.312, 0.358),
            bevel_width=0.0,
            bevel_segments=1,
            mat=mat_dark_recess,
        ))
        base_parts.append(add_beveled_box(
            f"LowerLatchStriker_{l_i}",
            size=(0.078, 0.020, 0.064),
            location=(lx, +0.324, 0.376),
            bevel_width=0.005,
            bevel_segments=1,
            mat=mat_warm_metal,
        ))
        base_parts.append(add_beveled_box(
            f"LatchStatusPip_{l_i}",
            size=(0.052, 0.010, 0.014),
            location=(lx, +0.327, 0.322),
            bevel_width=0.0,
            bevel_segments=1,
            mat=mat_rarity,
        ))

    # 7. Side Carry Handles (X = +/-0.50..+/-0.542) & Side RarityAccent Chevrons
    for s_i, sgn in enumerate((-1.0, +1.0)):
        base_parts.append(add_beveled_box(
            f"SideRecessPlate_{s_i}",
            size=(0.016, 0.32, 0.19),
            location=(sgn * 0.504, 0.0, 0.225),
            bevel_width=0.0,
            bevel_segments=1,
            mat=mat_dark_recess,
        ))
        for m_i, my in enumerate((-0.112, +0.112)):
            base_parts.append(add_beveled_box(
                f"SideHandleLug_{s_i}_{m_i}",
                size=(0.032, 0.032, 0.036),
                location=(sgn * 0.514, my, 0.272),
                bevel_width=0.0,
                bevel_segments=1,
                mat=mat_polymer,
            ))
        # Swept U-shaped metal carry handle bail (reaches X = +/-0.530 -> total width ~1.08m)
        bail_pts = [
            (sgn * 0.512, -0.112, 0.272),
            (sgn * 0.529, -0.100, 0.205),
            (sgn * 0.529, +0.100, 0.205),
            (sgn * 0.512, +0.112, 0.272),
        ]
        base_parts.append(add_tube_path(
            f"SideCarryHandle_{s_i}",
            bail_pts,
            radius=0.0085,
            segments=5,
            mat=mat_warm_metal,
        ))
        base_parts.append(add_tube_path(
            f"SideHandleGrip_{s_i}",
            [(sgn * 0.529, -0.068, 0.205), (sgn * 0.529, +0.068, 0.205)],
            radius=0.0125,
            segments=5,
            mat=mat_polymer,
        ))
        # Twin angled RarityAccent Side Accent Chevrons
        for ch_i, (cy, rot_x) in enumerate(((-0.075, math.radians(-26.0)), (+0.075, math.radians(+26.0)))):
            base_parts.append(add_beveled_box(
                f"SideAccentChevron_{s_i}_{ch_i}",
                size=(0.014, 0.108, 0.022),
                location=(sgn * 0.513, cy, 0.148),
                rotation=(rot_x, 0.0, 0.0),
                bevel_width=0.0,
                bevel_segments=1,
                mat=mat_rarity,
            ))

    # 8. Rear Hinge Clevis Brackets & Coaxial Steel Pins (-Y face, centered EXACTLY at Y=-0.310, Z=0.420)
    base_parts.append(add_beveled_box(
        "RearArmorPlate",
        size=(0.68, 0.020, 0.18),
        location=(0.0, -0.306, 0.220),
        bevel_width=0.0,
        bevel_segments=1,
        mat=mat_dark_recess,
    ))
    for h_i, hx in enumerate((-0.295, +0.295)):
        for e_i, ex_off in enumerate((-0.052, +0.052)):
            base_parts.append(add_beveled_box(
                f"RearHingeBaseEar_{h_i}_{e_i}",
                size=(0.024, 0.044, 0.088),
                location=(hx + ex_off, -0.306, 0.388),
                bevel_width=0.0,
                bevel_segments=1,
                mat=mat_dark_recess,
            ))
        base_parts.append(add_tube_path(
            f"RearHingePin_{h_i}",
            [(hx - 0.072, hinge_y, hinge_z), (hx + 0.072, hinge_y, hinge_z)],
            radius=0.010,
            segments=6,
            mat=mat_warm_metal,
        ))

    # Join all base geometry into one crisp multi-material mesh at (0, 0, 0)
    base_mesh_obj = _join_mesh_group("ChestBaseMesh", base_parts)

    # =======================================================================
    # PART B: CHEST LID (built strictly in ChestLid LOCAL coordinates where
    # (0, 0, 0) == exact rear hinge line (0.0, -0.310, +0.420) in world space!)
    # =======================================================================
    lid_parts: list[bpy.types.Object] = []

    # 1. Beveled Domed Lid Shell with Hollow Recessed Underside (BEVEL modifier segments=2!)
    lid_shell = _make_rect_profile_solid(
        "LidShell",
        rings=[
            (-0.386, +0.386, +0.118, +0.506, +0.132),  # 0: hollow underside ceiling
            (-0.436, +0.436, +0.068, +0.556, +0.002),  # 1: underside inner rim
            (-0.496, +0.496, +0.010, +0.614, +0.002),  # 2: outer bottom sealing lip
            (-0.506, +0.506, +0.010, +0.620, +0.088),  # 3: outer vertical armor skirt
            (-0.440, +0.440, +0.072, +0.552, +0.184),  # 4: sloped dome shoulder
            (-0.365, +0.365, +0.130, +0.492, +0.208),  # 5: crowned armor top deck
        ],
        ring_mat_indices=[1, 1, 0, 0, 0],
        cap_start_mat=1,
        cap_end_mat=0,
        materials=[mat_slate_steel, mat_dark_recess],
    )
    _apply_bevel_modifier(lid_shell, width=0.012, segments=2, angle_deg=38.0)
    lid_parts.append(lid_shell)

    # Twin reinforcing baffle ribs tucked inside hollow lid underside (visible when opened!)
    for u_i, ux in enumerate((-0.18, +0.18)):
        lid_parts.append(add_beveled_box(
            f"LidInnerBaffle_{u_i}",
            size=(0.026, 0.34, 0.022),
            location=(ux, +0.312, +0.124),
            bevel_width=0.0,
            bevel_segments=1,
            mat=mat_polymer,
        ))

    # 2. Three Swept Top Structural Armor Ribs (peaking at local z=+0.220 -> exact world Z=0.640m!)
    rib_yz = [
        (+0.036, +0.112),
        (+0.132, +0.220),
        (+0.490, +0.220),
        (+0.588, +0.112),
        (+0.505, +0.138),
        (+0.118, +0.138),
    ]
    for r_i, (rx, rw, rmat) in enumerate((
        (-0.325, 0.086, mat_polymer),
        (0.000, 0.132, mat_dark_recess),
        (+0.325, 0.086, mat_polymer),
    )):
        rib = _make_extruded_yz_profile(f"LidTopRib_{r_i}", rib_yz, x_center=rx, width_x=rw, mat=rmat)
        _apply_bevel_modifier(rib, width=0.006, segments=1, angle_deg=40.0)
        lid_parts.append(rib)

    # Top Center Glowing RarityAccent Deck Strip (instantly readable from skydiving/overhead view!)
    lid_parts.append(add_beveled_box(
        "LidTopRarityStrip",
        size=(0.068, 0.28, 0.010),
        location=(0.0, +0.312, +0.219),
        bevel_width=0.0,
        bevel_segments=1,
        mat=mat_rarity,
    ))

    # 3. Front Corner Lid Guard Caps (echoing base polymer corner bumpers on front +Y corners, clear of underside cavity)
    for fc_i, sx in enumerate((-1.0, +1.0)):
        lid_parts.append(add_beveled_box(
            f"LidFrontCornerGuard_{fc_i}",
            size=(0.094, 0.082, 0.084),
            location=(sx * 0.472, +0.588, +0.048),
            bevel_width=0.0,
            bevel_segments=1,
            mat=mat_polymer,
        ))

    # 4. Glowing Front LED Status Bar + Armored Brow Bezel (facing +Y front)
    lid_parts.append(add_beveled_box(
        "LidFrontStatusBezel",
        size=(0.41, 0.028, 0.056),
        location=(0.0, +0.618, +0.052),
        bevel_width=0.006,
        bevel_segments=1,
        mat=mat_dark_recess,
    ))
    lid_parts.append(add_beveled_box(
        "LidFrontStatusLED",
        size=(0.36, 0.018, 0.026),
        location=(0.0, +0.629, +0.052),
        bevel_width=0.0,
        bevel_segments=1,
        mat=mat_rarity,
    ))

    # Slim RarityAccent Side Shoulder Strips along left/right sloped lid shoulders
    for ls_i, sgn in enumerate((-1.0, +1.0)):
        lid_parts.append(add_beveled_box(
            f"LidSideAccentStrip_{ls_i}",
            size=(0.014, 0.34, 0.022),
            location=(sgn * 0.478, +0.312, +0.134),
            rotation=(0.0, sgn * math.radians(34.0), 0.0),
            bevel_width=0.0,
            bevel_segments=1,
            mat=mat_rarity,
        ))

    # 5. Dual Upper Magnetic Clasp Tongues (aligning 1:1 above Base lower latches at X=+/-0.27!)
    for cl_i, lx in enumerate((-0.27, +0.27)):
        lid_parts.append(add_beveled_box(
            f"LidClaspMount_{cl_i}",
            size=(0.090, 0.026, 0.062),
            location=(lx, +0.622, +0.052),
            bevel_width=0.0,
            bevel_segments=1,
            mat=mat_dark_recess,
        ))
        lid_parts.append(add_beveled_box(
            f"LidClaspTongue_{cl_i}",
            size=(0.066, 0.022, 0.092),
            location=(lx, +0.636, +0.018),
            bevel_width=0.005,
            bevel_segments=1,
            mat=mat_warm_metal,
        ))

    # 6. Rear Rotating Hinge Knuckles & Strap Arms (centered EXACTLY on local (0, 0, 0) hinge axis!)
    for h_i, hx in enumerate((-0.295, +0.295)):
        lid_parts.append(add_tube_path(
            f"LidHingeKnuckle_{h_i}",
            [(hx - 0.037, 0.0, 0.0), (hx + 0.037, 0.0, 0.0)],
            radius=0.019,
            segments=8,
            mat=mat_warm_metal,
        ))
        lid_parts.append(add_beveled_box(
            f"LidHingeStrap_{h_i}",
            size=(0.068, 0.044, 0.072),
            location=(hx, +0.018, +0.034),
            bevel_width=0.0,
            bevel_segments=1,
            mat=mat_warm_metal,
        ))

    # Join all lid parts into one crisp multi-material mesh at local (0, 0, 0)
    lid_mesh_obj = _join_mesh_group("ChestLidMesh", lid_parts)

    # =======================================================================
    # PART C: CLEAN HIERARCHY & PIVOT-PRESERVING GLB EXPORT
    # =======================================================================
    chest_base = bpy.data.objects.new("ChestBase", None)
    chest_base.empty_display_type = "PLAIN_AXES"
    chest_base.empty_display_size = 0.25
    chest_base.location = Vector((0.0, 0.0, 0.0))
    bpy.context.scene.collection.objects.link(chest_base)

    base_mesh_obj.parent = chest_base
    base_mesh_obj.location = Vector((0.0, 0.0, 0.0))

    chest_lid = bpy.data.objects.new("ChestLid", None)
    chest_lid.empty_display_type = "ARROWS"
    chest_lid.empty_display_size = 0.20
    chest_lid.parent = chest_base
    # EXACT REAR HINGE LINE: Blender (0, -0.31, +0.42) -> Three.js Y-up (0, +0.42, +0.31)
    chest_lid.location = Vector((0.0, hinge_y, hinge_z))
    chest_lid.rotation_euler = Euler((0.0, 0.0, 0.0), "XYZ")
    bpy.context.scene.collection.objects.link(chest_lid)

    lid_mesh_obj.parent = chest_lid
    lid_mesh_obj.location = Vector((0.0, 0.0, 0.0))

    bpy.context.view_layer.update()

    export_objs = [chest_base, base_mesh_obj, chest_lid, lid_mesh_obj]
    mesh_objs = [base_mesh_obj, lid_mesh_obj]

    mins, maxs = world_bbox(mesh_objs)
    dims = maxs - mins
    tris = count_tris(mesh_objs)

    # Verify grounding & exact RarityAccent material assignment before export
    assert abs(mins.z) < 1e-4, f"Loot chest not grounded at Z=0 (min_z={mins.z:.5f})"
    has_rarity = any(
        slot.material and slot.material.name == "RarityAccent"
        for m in mesh_objs
        for slot in m.material_slots
    )
    assert has_rarity, "Loot chest missing required 'RarityAccent' material slot!"

    bpy.ops.object.select_all(action="DESELECT")
    for obj in export_objs:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = chest_base

    out_path = str(OUT_DIR / "prop_loot_chest.glb")
    bpy.ops.export_scene.gltf(
        filepath=out_path,
        export_format="GLB",
        use_selection=True,
        export_yup=True,
        export_apply=True,
        export_materials="EXPORT",
        export_animations=False,
        export_draco_mesh_compression_enable=False,
    )

    size_bytes = os.path.getsize(out_path)
    return {
        "file": "prop_loot_chest.glb",
        "tris": tris,
        "size_kb": size_bytes / 1024.0,
        "dims": (dims.x, dims.y, dims.z),
        "min_z": mins.z,
        "max_z": maxs.z,
    }


# ===========================================================================
# Main Entrypoint
# ===========================================================================

def main() -> int:
    builders = [
        build_shield_cell,
        build_shield_jug,
        build_medkit,
        build_mana_elixir,
        build_hardlight_cover,
        build_impulse_booster,
        build_supply_drop,
        build_glider,
        build_loot_chest,
    ]

    results = []
    print("=" * 84)
    print("Workspace Royale — Building 9 Utility, Supply Drop, Glider & Loot Chest GLBs (Blender 5.3)")
    print("=" * 84)

    for fn in builders:
        res = fn()
        results.append(res)
        dx, dy, dz = res["dims"]
        print(
            f"  [OK] {res['file']:<26} | {res['tris']:>5} tris | {res['size_kb']:>6.1f} KB | "
            f"dims=({dx:.2f} x {dy:.2f} x {dz:.2f}m) | Z=[{res['min_z']:+.3f}, {res['max_z']:+.3f}]"
        )

    total_kb = sum(r["size_kb"] for r in results)
    total_tris = sum(r["tris"] for r in results)
    print("-" * 84)
    print(f"  TOTAL: {len(results)} assets | {total_tris} tris | {total_kb:.1f} KB ({total_kb / 1024.0:.2f} MB)")
    print("=" * 84)

    # Sanity-check quality constraints
    for r in results:
        assert r["size_kb"] > 1.0, f"{r['file']} is empty!"
        max_tris = 2000 if r["file"] == "prop_loot_chest.glb" else 1800
        assert 400 <= r["tris"] <= max_tris, f"{r['file']} tri count {r['tris']} outside 400..{max_tris} budget!"

    return 0


if __name__ == "__main__":
    sys.exit(main())

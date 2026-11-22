#!/usr/bin/env python3
"""
Workspace Royale — Authentic Mountain View Googleplex 3D Map Asset Builder
Blender 5.3.0 headless generator producing all 13 campus landmarks & props (.glb)
into public/assets/map/.

Usage:
    blender --background --python scripts/blender/build_map.py
    blender --background --python scripts/blender/build_map.py -- --only stan_trex
"""

import math
import os
import sys
import time
import numpy as np
import bpy
import bmesh
from mathutils import Vector, Matrix, Euler

# ---------------------------------------------------------------------------
# Paths & Constants
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
OUT_DIR = os.path.join(PROJECT_ROOT, "public", "assets", "map")
os.makedirs(OUT_DIR, exist_ok=True)

# SVG blueprint conversion factor (docs/googleplex-map-topdown.svg: 2.9 px/m)
SVG_PX_PER_M = 2.9

# Authentic Google Primary & Architectural Palette (linear-friendly sRGB tuples)
COL_G_BLUE   = (0.145, 0.400, 0.920, 1.0)  # #4285F4 (slightly calibrated for sRGB->linear)
COL_G_RED    = (0.820, 0.160, 0.135, 1.0)  # #EA4335
COL_G_YELLOW = (0.955, 0.640, 0.025, 1.0)  # #FBBC04
COL_G_GREEN  = (0.110, 0.560, 0.220, 1.0)  # #34A853

def srgb_to_linear(c):
    """Convert sRGB scalar or 3/4-tuple in [0,1] to Blender linear space."""
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
    h = h.lstrip('#')
    r = int(h[0:2], 16) / 255.0
    g = int(h[2:4], 16) / 255.0
    b = int(h[4:6], 16) / 255.0
    return srgb_to_linear((r, g, b, alpha))


# ---------------------------------------------------------------------------
# Scene & Blender 5.3.0 Helpers
# ---------------------------------------------------------------------------
def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = 'METRIC'
    scene.unit_settings.scale_length = 1.0


def _value_noise_2d(h, w, grid_h, grid_w, rng):
    """Smooth tileable bilinear value noise in [0, 1]."""
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
    return (v00 * (1 - fx) + v10 * fx) * (1 - fy) + (v01 * (1 - fx) + v11 * fx) * fy


def _fbm_2d(h, w, rng, octaves=(4, 8, 16, 32)):
    out = np.zeros((h, w), dtype=np.float32)
    amp = 0.55
    total = 0.0
    for g in octaves:
        out += amp * _value_noise_2d(h, w, g, g, rng)
        total += amp
        amp *= 0.5
    return out / total


def make_packed_image(name, rgb_srgb):
    """
    Create a packed Blender Image from an (H, W, 3) or (H, W, 4) float32 array in [0, 1] (sRGB).
    """
    h, w = rgb_srgb.shape[:2]
    if rgb_srgb.shape[2] == 3:
        rgba = np.ones((h, w, 4), dtype=np.float32)
        rgba[:, :, :3] = np.clip(rgb_srgb, 0.0, 1.0)
    else:
        rgba = np.clip(rgb_srgb, 0.0, 1.0).astype(np.float32)
    img = bpy.data.images.new(name=name, width=w, height=h, alpha=(rgb_srgb.shape[2] == 4))
    img.colorspace_settings.name = 'sRGB'
    img.pixels.foreach_set(rgba.ravel())
    img.pack()
    return img


# ---------------------------------------------------------------------------
# Procedural Numpy Textures (Deterministic, Compact 160x160 / 192x192)
# ---------------------------------------------------------------------------
def gen_concrete_tex(name="TexConcrete", size=128, tint=(0.86, 0.82, 0.75), seed=101):
    rng = np.random.default_rng(seed)
    n = _fbm_2d(size, size, rng, (4, 12, 24))
    grain = rng.normal(0.0, 0.015, (size, size)).astype(np.float32)
    y_idx = np.arange(size)
    seam_h = ((y_idx % (size // 4)) < 2).astype(np.float32)[:, None] * 0.09
    x_idx = np.arange(size)
    seam_v = ((x_idx % (size // 2)) < 2).astype(np.float32)[None, :] * 0.06
    v = 0.90 + 0.14 * (n - 0.5) + grain - seam_h - seam_v
    rgb = np.stack([v * tint[0], v * tint[1], v * tint[2]], axis=-1)
    return make_packed_image(name, rgb)


def gen_stone_paver_tex(name="TexStonePaver", size=128, seed=102):
    rng = np.random.default_rng(seed)
    n = _fbm_2d(size, size, rng, (6, 16, 28))
    rgb = np.zeros((size, size, 3), dtype=np.float32)
    rows, cols = 6, 6
    rh, cw = size // rows, size // cols
    for r in range(rows):
        offset = (cw // 2) if (r % 2 == 1) else 0
        for c in range(cols):
            shade = 0.82 + 0.10 * rng.random()
            warm = 0.03 * (rng.random() - 0.5)
            y0 = r * rh
            for dy in range(rh):
                for dx in range(cw):
                    px = (c * cw + dx + offset) % size
                    py = min(size - 1, y0 + dy)
                    if dy < 2 or dx < 2:
                        rgb[py, px] = (0.50, 0.47, 0.42)
                    else:
                        nv = (n[py, px] - 0.5) * 0.08
                        rgb[py, px] = (
                            shade * 0.94 + warm + nv,
                            shade * 0.89 + nv,
                            shade * 0.79 - warm + nv,
                        )
    return make_packed_image(name, rgb)


def gen_solar_panel_tex(name="TexSolarPanel", size=160, seed=103):
    rng = np.random.default_rng(seed)
    n = _fbm_2d(size, size, rng, (4, 12))
    yy, xx = np.mgrid[0:size, 0:size]
    cell_h, cell_w = size // 6, size // 4
    cy = yy % cell_h
    cx = xx % cell_w
    r = 0.06 + 0.03 * n
    g = 0.13 + 0.04 * n
    b = 0.36 + 0.08 * n
    bus = ((cx == cell_w // 3) | (cx == (2 * cell_w) // 3))
    r = np.where(bus, 0.36, r)
    g = np.where(bus, 0.45, g)
    b = np.where(bus, 0.60, b)
    grid = (cy < 2) | (cx < 2)
    r = np.where(grid, 0.68, r)
    g = np.where(grid, 0.73, g)
    b = np.where(grid, 0.80, b)
    border = (yy < 4) | (yy >= size - 4) | (xx < 4) | (xx >= size - 4)
    r = np.where(border, 0.78, r)
    g = np.where(border, 0.81, g)
    b = np.where(border, 0.85, b)
    rgb = np.stack([r, g, b], axis=-1)
    return make_packed_image(name, rgb)


def gen_cedar_wood_tex(name="TexCedarWood", size=128, seed=104):
    rng = np.random.default_rng(seed)
    n_low = _value_noise_2d(size, size, 16, 4, rng)
    n_hi = _value_noise_2d(size, size, 40, 8, rng)
    yy = np.arange(size)[:, None]
    grain = np.sin((yy * 0.50 + n_low * 8.0)) * 0.5 + 0.5
    plank_h = size // 6
    plank_id = yy // plank_h
    plank_var = ((plank_id * 37) % 11) / 11.0 * 0.14 - 0.07
    seam = ((yy % plank_h) < 2).astype(np.float32) * 0.28
    v = 0.86 + 0.16 * grain + 0.08 * (n_hi - 0.5) + plank_var - seam
    # Warm rich California cedar/redwood tone
    rgb = np.stack([v * 0.74, v * 0.43, v * 0.20], axis=-1)
    return make_packed_image(name, rgb)


def gen_sand_tex(name="TexSand", size=192, seed=105):
    rng = np.random.default_rng(seed)
    n = _fbm_2d(size, size, rng, (6, 16, 32))
    yy, xx = np.mgrid[0:size, 0:size]
    ripples = np.sin(yy * 0.30 + n * 4.5) * 0.045
    speck = rng.normal(0.0, 0.020, (size, size)).astype(np.float32)
    v = 0.94 + 0.09 * (n - 0.5) + ripples + speck
    # Sunlit warm California beach volleyball golden-tan sand
    rgb = np.stack([v * 0.93, v * 0.78, v * 0.52], axis=-1)
    return make_packed_image(name, rgb)


def gen_bark_tex(name="TexBark", size=160, redwood=False, seed=106):
    rng = np.random.default_rng(seed)
    n_v = _value_noise_2d(size, size, 8, 24, rng)
    n_f = _value_noise_2d(size, size, 16, 40, rng)
    xx = np.arange(size)[None, :]
    ridge = np.sin(xx * (0.48 if redwood else 0.34) + n_v * 5.2) * 0.5 + 0.5
    v = 0.62 + 0.28 * ridge + 0.18 * (n_f - 0.5)
    if redwood:
        # Deep fibrous cinnamon-reddish California Coastal Redwood bark
        rgb = np.stack([v * 0.54, v * 0.24, v * 0.13], axis=-1)
    else:
        # Natural warm weathered grey-brown California Live Oak bark
        rgb = np.stack([v * 0.38, v * 0.31, v * 0.24], axis=-1)
    return make_packed_image(name, rgb)


def gen_curtain_glass_tex(name="TexCurtainGlass", size=128, seed=107):
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:size, 0:size]
    fy = yy / float(size)
    n = _fbm_2d(size, size, rng, (4, 10))
    r = 0.12 + 0.16 * (1.0 - fy) + 0.03 * n
    g = 0.31 + 0.23 * (1.0 - fy) + 0.04 * n
    b = 0.52 + 0.24 * (1.0 - fy) + 0.05 * n
    band = (np.sin(yy * 0.30) * 0.5 + 0.5) * 0.06
    r = r - band
    g = g - band * 0.8
    b = b - band * 0.5
    div = ((xx % (size // 3)) < 2) | ((yy % (size // 2)) < 2)
    r = np.where(div, 0.20, r)
    g = np.where(div, 0.27, g)
    b = np.where(div, 0.35, b)
    rgb = np.stack([r, g, b], axis=-1)
    return make_packed_image(name, rgb)


def gen_dragonscale_tex(name="TexDragonscale", size=192, seed=108):
    rng = np.random.default_rng(seed)
    n = _fbm_2d(size, size, rng, (4, 12))
    yy, xx = np.mgrid[0:size, 0:size]
    # Crisp architectural white photovoltaic dragonscale quilted pattern
    u = ((xx + yy) % 48) / 48.0
    v = ((xx - yy) % 48) / 48.0
    edge = (u < 0.07) | (v < 0.07)
    shade = 0.94 + 0.06 * (u - 0.5) + 0.03 * (n - 0.5)
    r = np.where(edge, 0.62, shade * 0.95)
    g = np.where(edge, 0.68, shade * 0.97)
    b = np.where(edge, 0.77, shade * 1.00)
    rgb = np.stack([r, g, b], axis=-1)
    return make_packed_image(name, rgb)


def gen_foliage_tex(name="TexFoliage", size=160, redwood=False, seed=109):
    rng = np.random.default_rng(seed)
    n1 = _fbm_2d(size, size, rng, (6, 16, 32))
    n2 = _value_noise_2d(size, size, 28, 28, rng)
    dapple = 0.76 + 0.34 * n1 + 0.14 * (n2 - 0.5)
    if redwood:
        rgb = np.stack([dapple * 0.15, dapple * 0.38, dapple * 0.19], axis=-1)
    else:
        rgb = np.stack([dapple * 0.26, dapple * 0.44, dapple * 0.17], axis=-1)
    return make_packed_image(name, rgb)


def gen_bronze_plaque_tex(name="TexBronzePlaque", size=160, seed=110):
    rng = np.random.default_rng(seed)
    n = _fbm_2d(size, size, rng, (6, 16))
    yy, xx = np.mgrid[0:size, 0:size]
    r = 0.36 + 0.05 * n
    g = 0.25 + 0.04 * n
    b = 0.13 + 0.03 * n
    border = (
        ((yy >= 7) & (yy <= 13)) | ((yy >= size - 14) & (yy <= size - 8)) |
        ((xx >= 7) & (xx <= 13)) | ((xx >= size - 14) & (xx <= size - 8))
    )
    in_frame = (yy >= 7) & (yy <= size - 8) & (xx >= 7) & (xx <= size - 8)
    border = border & in_frame
    title_bar = (yy >= size - 48) & (yy <= size - 30) & (xx >= 26) & (xx <= size - 26) & ((xx // 6) % 2 == 0)
    sub_bar1 = (yy >= size // 2 + 4) & (yy <= size // 2 + 14) & (xx >= 22) & (xx <= size - 22) & ((xx // 5) % 2 == 0)
    sub_bar2 = (yy >= size // 2 - 18) & (yy <= size // 2 - 10) & (xx >= 28) & (xx <= size - 28) & ((xx // 4) % 2 == 0)
    sub_bar3 = (yy >= 28) & (yy <= 38) & (xx >= 36) & (xx <= size - 36) & ((xx // 5) % 2 == 0)
    gold = border | title_bar | sub_bar1 | sub_bar2 | sub_bar3
    r = np.where(gold, 0.88, r)
    g = np.where(gold, 0.72, g)
    b = np.where(gold, 0.34, b)
    rgb = np.stack([r, g, b], axis=-1)
    return make_packed_image(name, rgb)


def gen_oak_floor_tex(name="TexOakFloor", size=128, seed=111):
    """Warm sunlit pale-oak architectural office plank flooring texture."""
    rng = np.random.default_rng(seed)
    n_low = _value_noise_2d(size, size, 16, 4, rng)
    n_hi = _value_noise_2d(size, size, 32, 8, rng)
    yy, xx = np.mgrid[0:size, 0:size]
    plank_h = size // 8
    plank_id = yy // plank_h
    plank_var = ((plank_id * 29 + 3) % 7) / 7.0 * 0.08 - 0.04
    seam_h = ((yy % plank_h) < 1).astype(np.float32) * 0.14
    stagger = (plank_id % 2) * (size // 2)
    seam_v = (((xx + stagger) % size) < 1).astype(np.float32) * 0.12
    grain = np.sin(yy * 0.55 + n_low * 6.5) * 0.045
    v = 0.90 + grain + 0.05 * (n_hi - 0.5) + plank_var - seam_h - seam_v
    rgb = np.stack([v * 0.87, v * 0.76, v * 0.59], axis=-1)
    return make_packed_image(name, rgb)


def gen_workspace_showcase_tex(name="TexWorkspaceShowcase", w=192, h=128):
    """Glowing Google Workspace architectural exhibition showcase graphic for Gradient Canopy."""
    img = np.zeros((h, w, 3), dtype=np.float32)
    # Clean crisp modern Google studio backdrop (bottom-up Blender pixels)
    yy, xx = np.mgrid[0:h, 0:w]
    grad = 0.92 + 0.06 * (yy / float(h))
    img[:, :, 0] = grad * 0.97
    img[:, :, 1] = grad * 0.98
    img[:, :, 2] = grad * 1.00

    g_cols = [
        (0.259, 0.522, 0.957),  # Google Blue
        (0.918, 0.263, 0.208),  # Google Red
        (0.984, 0.737, 0.016),  # Google Yellow
        (0.204, 0.659, 0.325),  # Google Green
    ]
    # Top 4-color Google architectural header band (high y = top of image)
    seg = w // 4
    for i, col in enumerate(g_cols):
        img[h - 14:h - 4, i * seg:(i + 1) * seg] = col

    # 6 vibrant Workspace product showcase cards in a crisp 3x2 grid
    card_cols = [
        (0.918, 0.263, 0.208),  # Gmail Red
        (0.259, 0.522, 0.957),  # Docs Blue
        (0.204, 0.659, 0.325),  # Drive/Meet Green
        (0.984, 0.737, 0.016),  # Slides Yellow
        (0.259, 0.522, 0.957),  # Calendar Blue
        (0.180, 0.720, 0.520),  # Chat Teal-Green
    ]
    for ci in range(6):
        row = ci // 3  # 0=bottom row, 1=top row
        col_i = ci % 3
        x0 = 12 + col_i * 58
        x1 = x0 + 50
        y0 = 16 + row * 48
        y1 = y0 + 38
        # Card surface + colored top accent & stylized UI bars
        img[y0:y1, x0:x1] = (0.14, 0.17, 0.23)
        img[y1 - 10:y1, x0:x1] = card_cols[ci]
        img[y0 + 18:y0 + 22, x0 + 6:x1 - 8] = (0.86, 0.90, 0.96)
        img[y0 + 11:y0 + 14, x0 + 6:x1 - 16] = (0.58, 0.66, 0.78)
        img[y0 + 5:y0 + 8, x0 + 6:x0 + 22] = card_cols[ci]

    return make_packed_image(name, img)


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
    emission_tex=False,
    bump_strength=0.0,  # Intentionally unused for albedo images (glTF normalTexture requires tangent-space RGB normal maps)
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
        tex_node.location = (-500, 200)
        if tex_tint is not None:
            mix = nodes.new("ShaderNodeMix")
            mix.data_type = 'RGBA'
            mix.blend_type = 'MULTIPLY'
            mix.inputs["Factor"].default_value = 1.0
            mix.inputs["B"].default_value = tex_tint
            mix.location = (-220, 200)
            links.new(tex_node.outputs["Color"], mix.inputs["A"])
            links.new(mix.outputs["Result"], bsdf.inputs["Base Color"])
        else:
            links.new(tex_node.outputs["Color"], bsdf.inputs["Base Color"])

    if emission_tex and tex_node is not None and emission_strength > 0.0:
        links.new(tex_node.outputs["Color"], bsdf.inputs["Emission Color"])
        bsdf.inputs["Emission Strength"].default_value = emission_strength
    elif emission is not None and emission_strength > 0.0:
        bsdf.inputs["Emission Color"].default_value = emission
        bsdf.inputs["Emission Strength"].default_value = emission_strength

    if alpha < 0.999:
        if hasattr(mat, "surface_render_method"):
            mat.surface_render_method = 'BLENDED'
        if hasattr(mat, "blend_method"):
            mat.blend_method = 'BLEND'
    if double_sided:
        mat.use_backface_culling = False
    return mat


# ---------------------------------------------------------------------------
# BMesh Geometry & UV Primitives
# ---------------------------------------------------------------------------
def apply_box_uv(bm, scale=0.25):
    """Triplanar box-projection UV mapping in world meters."""
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


def apply_face_unit_uv(bm):
    """Map every quad face cleanly to [0,1]x[0,1] (ideal for solar panels, plaques)."""
    uv_layer = bm.loops.layers.uv.verify()
    coords = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    for f in bm.faces:
        for i, loop in enumerate(f.loops):
            loop[uv_layer].uv = coords[i % 4]


def finalize_mesh(name, bm, mat, smooth=False, uv_scale=0.25, keep_existing_uv=False):
    """Finalize a BMesh into a scene Object with outward normals, UVs, and material."""
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


def bm_add_box(bm, center, size, rot_euler=(0.0, 0.0, 0.0), bevel=0.0):
    """Add an oriented box (optionally beveled) to an existing bmesh."""
    sx, sy, sz = size
    mat_t = Matrix.Translation(Vector(center))
    mat_r = Euler(rot_euler, 'XYZ').to_matrix().to_4x4()
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
            offset_type='OFFSET',
            segments=2,
            profile=0.5,
            affect='EDGES',
            clamp_overlap=True,
        )
    return verts


def bm_add_prism_between(bm, p0, p1, r0, r1, segs=12, cap=True, flute_amp=0.0, flute_freq=0):
    """Add a tapered cylinder/cone between 3D points p0 and p1."""
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
        flute = 1.0 + flute_amp * math.cos(flute_freq * ang) if flute_freq > 0 else 1.0
        ca, sa = math.cos(ang), math.sin(ang)
        d = x_dir * ca + y_dir * sa
        ring0.append(bm.verts.new(p0 + d * (r0 * flute)))
        ring1.append(bm.verts.new(p1 + d * (r1 * flute)))

    for i in range(segs):
        ni = (i + 1) % segs
        bm.faces.new((ring0[i], ring0[ni], ring1[ni], ring1[i]))
    if cap:
        if r0 > 1e-5:
            bm.faces.new(list(reversed(ring0)))
        if r1 > 1e-5:
            bm.faces.new(ring1)
    return ring0 + ring1


def bm_add_spline_tube(bm, points, radii, segs=10, cap_ends=True, flute_amp=0.0, flute_freq=0, oval_ratio=1.0):
    """Sweep a smooth tube along a 3D polyline with parallel-transport frames."""
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

    # Initial frame
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
            flute = 1.0 + flute_amp * math.cos(flute_freq * ang) if flute_freq > 0 else 1.0
            ca = math.cos(ang) * ri * flute
            sa = math.sin(ang) * ri * oval_ratio * flute
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
    return [v for r in rings for v in r]


def bm_add_sphere(bm, center, rx, ry=None, rz=None, u_segs=14, v_segs=10):
    if ry is None:
        ry = rx
    if rz is None:
        rz = rx
    mat = Matrix.Translation(Vector(center)) @ Matrix.Diagonal((rx, ry, rz, 1.0))
    res = bmesh.ops.create_uvsphere(bm, u_segments=u_segs, v_segments=v_segs, radius=1.0, matrix=mat)
    return res["verts"]


def bm_add_torus(bm, center, major_r, minor_r, rot_euler=(0, 0, 0), major_segs=24, minor_segs=10):
    mat_t = Matrix.Translation(Vector(center))
    mat_r = Euler(rot_euler, 'XYZ').to_matrix().to_4x4()
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


def bm_add_organic_cluster(bm, center, rx, ry, rz, subdiv=2, seed=0, crinkle=0.22, droop=0.0):
    """
    Create a sculpted multi-lobed organic botanical foliage cluster (never a smooth sphere!).
    Uses displaced icosphere vertices with multi-frequency organic lobe ridges + optional bough droop.
    """
    rng = np.random.default_rng(seed)
    res = bmesh.ops.create_icosphere(bm, subdivisions=subdiv, radius=1.0)
    verts = res["verts"]
    p1 = rng.uniform(0, 6.28, 3)
    p2 = rng.uniform(0, 6.28, 3)
    cx, cy, cz = center
    for v in verts:
        x, y, z = v.co.x, v.co.y, v.co.z
        # Multi-frequency organic foliage lobe displacement
        lobe = (
            math.sin(x * 3.2 + p1[0]) * math.cos(y * 3.1 + p1[1]) * 0.55
            + math.sin(y * 5.4 + p2[0]) * math.sin(z * 4.9 + p2[1]) * 0.30
            + math.cos(z * 6.2 + x * 4.5 + p2[2]) * 0.15
        )
        scale = 1.0 + crinkle * lobe
        # Slightly flatten underside for realistic botanical canopy shading
        z_mod = z * (0.68 if z < 0 else 1.05)
        horiz = math.hypot(x, y)
        dz_droop = -droop * (horiz ** 1.6)
        v.co = Vector((
            cx + x * rx * scale,
            cy + y * ry * scale,
            cz + z_mod * rz * scale + dz_droop,
        ))
    return verts


def ensure_ccw_2d(pts):
    """Ensure a 2D polygon vertex list is counter-clockwise in Blender XY."""
    area = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        area += x0 * y1 - x1 * y0
    return list(reversed(pts)) if area < 0 else list(pts)


def point_in_poly_2d(x, y, poly):
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def min_dist_to_poly_edges(x, y, poly):
    best = 1e9
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        dx, dy = x1 - x0, y1 - y0
        l2 = dx * dx + dy * dy
        if l2 < 1e-9:
            d = math.hypot(x - x0, y - y0)
        else:
            t = max(0.0, min(1.0, ((x - x0) * dx + (y - y0) * dy) / l2))
            d = math.hypot(x - (x0 + t * dx), y - (y0 + t * dy))
        if d < best:
            best = d
    return best


def bm_add_polygon_prism(bm, pts_2d, z0, z1, cap_bottom=True, cap_top=True):
    """Extrude any CCW 2D polygon cleanly between z0 and z1 and triangulate caps."""
    pts = ensure_ccw_2d(pts_2d)
    n = len(pts)
    bot = [bm.verts.new((x, y, z0)) for x, y in pts]
    top = [bm.verts.new((x, y, z1)) for x, y in pts]
    for i in range(n):
        ni = (i + 1) % n
        bm.faces.new((bot[i], bot[ni], top[ni], top[i]))
    cap_faces = []
    if cap_bottom:
        cap_faces.append(bm.faces.new(list(reversed(bot))))
    if cap_top:
        cap_faces.append(bm.faces.new(top))
    if cap_faces:
        bmesh.ops.triangulate(bm, faces=cap_faces, quad_method='BEAUTY', ngon_method='EAR_CLIP')
    return bot + top


def svg_poly_to_local(svg_pts, cx_svg, cy_svg):
    """
    Convert SVG pixel polygon vertices to local Blender meters centered on (cx_svg, cy_svg).
    With export_yup=True: Blender +X -> glTF +X (East), Blender +Y -> glTF -Z (North).
    SVG +Y goes South, so by = -(sy - cy_svg) / SVG_PX_PER_M.
    """
    pts = [((sx - cx_svg) / SVG_PX_PER_M, -(sy - cy_svg) / SVG_PX_PER_M) for sx, sy in svg_pts]
    return ensure_ccw_2d(pts)


def export_asset(filename, ground_auto=False):
    """Select all mesh objects, compute diagnostics, optionally ground Z=0, and export GLB."""
    objs = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    if not objs:
        raise RuntimeError(f"No mesh objects to export for {filename}")

    # Compute world-space bounds & tri count
    min_co = Vector((1e9, 1e9, 1e9))
    max_co = Vector((-1e9, -1e9, -1e9))
    total_tris = 0
    for o in objs:
        m = o.matrix_world
        for v in o.data.vertices:
            w = m @ v.co
            min_co.x = min(min_co.x, w.x)
            min_co.y = min(min_co.y, w.y)
            min_co.z = min(min_co.z, w.z)
            max_co.x = max(max_co.x, w.x)
            max_co.y = max(max_co.y, w.y)
            max_co.z = max(max_co.z, w.z)
        for p in o.data.polygons:
            total_tris += max(1, len(p.vertices) - 2)

    if ground_auto and abs(min_co.z) > 1e-4:
        dz = -min_co.z
        for o in objs:
            o.location.z += dz
        min_co.z += dz
        max_co.z += dz

    bpy.ops.object.select_all(action='DESELECT')
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]

    out_path = os.path.join(OUT_DIR, filename)
    bpy.ops.export_scene.gltf(
        filepath=out_path,
        export_format='GLB',
        use_selection=True,
        export_yup=True,
        export_apply=True,
        export_materials='EXPORT',
        export_animations=False,
        export_draco_mesh_compression_enable=False,
    )
    size_kb = os.path.getsize(out_path) / 1024.0
    dims = max_co - min_co
    return {
        "file": filename,
        "kb": size_kb,
        "tris": total_tris,
        "dims": (dims.x, dims.y, dims.z),
        "min_z": min_co.z,
        "max_z": max_co.z,
        "meshes": len(objs),
    }


# ===========================================================================
# 1. LANDMARK: STAN THE T-REX SKELETON SCULPTURE ON TIERED LIMESTONE PEDESTAL
# ===========================================================================
def build_stan_trex():
    reset_scene()

    tex_stone = gen_stone_paver_tex("StanStoneTex", 128, seed=201)
    tex_conc = gen_concrete_tex("StanLimestoneTex", 128, tint=(0.86, 0.83, 0.77), seed=202)
    tex_plaque = gen_bronze_plaque_tex("StanPlaqueTex", 160, seed=203)

    mat_limestone = make_pbr_mat("StanLimestone", base_color=hex_to_linear("#DDD5C7"), roughness=0.78, tex_img=tex_conc, bump_strength=0.14)
    mat_plaza_stone = make_pbr_mat("StanPlazaStone", base_color=hex_to_linear("#D6CEC0"), roughness=0.80, tex_img=tex_stone, bump_strength=0.15)
    mat_basalt = make_pbr_mat("StanBasaltCap", base_color=hex_to_linear("#3A3F47"), roughness=0.52, metallic=0.10)
    # Googleplex Stan fossil-bronze cast bone material (warm aged bronze-fossil ivory)
    mat_bone = make_pbr_mat("StanFossilBone", base_color=hex_to_linear("#9C8668"), metallic=0.22, roughness=0.52)
    mat_bone_dark = make_pbr_mat("StanBoneRecess", base_color=hex_to_linear("#5B4B39"), metallic=0.18, roughness=0.68)
    mat_teeth = make_pbr_mat("StanTeethIvory", base_color=hex_to_linear("#EFE6D2"), metallic=0.05, roughness=0.28)
    mat_steel = make_pbr_mat("StanSupportSteel", base_color=hex_to_linear("#2E343D"), metallic=0.86, roughness=0.32)
    mat_bronze = make_pbr_mat("StanBronzeTrim", base_color=hex_to_linear("#8D6735"), metallic=0.82, roughness=0.34)
    mat_plaque = make_pbr_mat("StanMuseumPlaque", base_color=(1, 1, 1, 1), metallic=0.72, roughness=0.32, tex_img=tex_plaque)

    # --- A. Tiered Limestone Plaza Pedestal (Z = 0.0 to 1.85m, ~6.4m x 4.4m oval-octagonal) ---
    bm_ped = bmesh.new()
    bm_cap = bmesh.new()

    def make_stadium_poly(rx, ry, segs=24):
        pts = []
        for i in range(segs):
            a = 2.0 * math.pi * i / segs
            # Soft superellipse rounded-rectangle plinth
            ca, sa = math.cos(a), math.sin(a)
            sx = math.copysign(abs(ca) ** 0.72, ca) * rx
            sy = math.copysign(abs(sa) ** 0.72, sa) * ry
            pts.append((sx, sy))
        return pts

    # Tier 0: Wide circular stone apron step (Z = 0.0..0.22m)
    bm_apron = bmesh.new()
    bm_add_polygon_prism(bm_apron, make_stadium_poly(3.75, 4.45, 28), 0.0, 0.22)
    finalize_mesh("Stan_PlazaApron", bm_apron, mat_plaza_stone, smooth=False, uv_scale=0.35)

    # Tier 1: Lower limestone step (Z = 0.22..0.72m)
    bm_add_polygon_prism(bm_ped, make_stadium_poly(3.05, 3.75, 24), 0.22, 0.72)
    # Tier 2: Mid tapered plinth (Z = 0.72..1.58m)
    bm_add_polygon_prism(bm_ped, make_stadium_poly(2.45, 3.15, 24), 0.72, 1.58)
    # Recessed decorative molding band
    bm_add_polygon_prism(bm_ped, make_stadium_poly(2.58, 3.28, 24), 1.58, 1.72)
    finalize_mesh("Stan_LimestonePedestal", bm_ped, mat_limestone, smooth=False, uv_scale=0.45)

    # Top dark basalt exhibition platform (Z = 1.72..1.85m)
    bm_add_polygon_prism(bm_cap, make_stadium_poly(2.35, 3.05, 24), 1.72, 1.85)
    finalize_mesh("Stan_BasaltTop", bm_cap, mat_basalt, smooth=False, uv_scale=0.5)

    # Museum Bronze Plaque Lectern on front (+Y) edge
    bm_lect = bmesh.new()
    bm_add_prism_between(bm_lect, (0.0, 3.55, 0.22), (0.0, 3.55, 1.15), 0.09, 0.07, segs=10)
    bm_add_box(bm_lect, (0.0, 3.58, 1.20), (1.08, 0.62, 0.07), rot_euler=(-0.55, 0.0, 0.0), bevel=0.015)
    finalize_mesh("Stan_PlaqueStand", bm_lect, mat_bronze, smooth=False)

    bm_plq = bmesh.new()
    bm_add_box(bm_plq, (0.0, 3.60, 1.24), (0.94, 0.50, 0.02), rot_euler=(-0.55, 0.0, 0.0))
    apply_face_unit_uv(bm_plq)
    finalize_mesh("Stan_BronzePlaque", bm_plq, mat_plaque, smooth=False, keep_existing_uv=True)

    # --- B. Anatomical Stan the T-Rex Skeleton (facing +Y, grounded on pedestal at Z = 1.85m, skull apex ~7.95m) ---
    # Spine curve from tail tip (y = -5.6) -> pelvis (y = -0.35, z = 5.15) -> chest (y = +1.7, z = 5.55) -> neck S-curve -> skull base (y = +3.35, z = 6.95)
    spine_ctrl = [
        # Tail (14 segments, graceful upward sweep at tip)
        (0.0, -5.55, 4.95),
        (0.0, -4.95, 4.78),
        (0.0, -4.35, 4.68),
        (0.0, -3.72, 4.66),
        (0.0, -3.08, 4.70),
        (0.0, -2.45, 4.80),
        (0.0, -1.82, 4.94),
        (0.0, -1.20, 5.06),
        (0.0, -0.68, 5.14),
        # Sacral / Pelvis (index 9..11)
        (0.0, -0.22, 5.20),
        (0.0,  0.22, 5.22),
        # Dorsal / Ribcage (index 11..19)
        (0.0,  0.65, 5.26),
        (0.0,  1.06, 5.34),
        (0.0,  1.45, 5.46),
        (0.0,  1.82, 5.60),
        (0.0,  2.15, 5.76),
        (0.0,  2.44, 5.95),
        # Cervical S-curve neck (index 17..23)
        (0.0,  2.66, 6.20),
        (0.0,  2.84, 6.50),
        (0.0,  3.02, 6.80),
        (0.0,  3.22, 7.04),
        (0.0,  3.42, 7.16),
    ]

    # Interpolate to 38 dense sculpted vertebrae
    def sample_polyline(pts, count):
        vs = [Vector(p) for p in pts]
        segs_len = [0.0]
        for i in range(1, len(vs)):
            segs_len.append(segs_len[-1] + (vs[i] - vs[i - 1]).length)
        total = segs_len[-1]
        out = []
        for k in range(count):
            d = total * k / (count - 1)
            for i in range(len(vs) - 1):
                if segs_len[i] <= d <= segs_len[i + 1] + 1e-6:
                    t = (d - segs_len[i]) / max(1e-6, segs_len[i + 1] - segs_len[i])
                    out.append(vs[i].lerp(vs[i + 1], t))
                    break
        return out

    bm_skel = bmesh.new()
    bm_recess = bmesh.new()
    bm_teeth = bmesh.new()
    bm_steel = bmesh.new()

    verts_pts = sample_polyline(spine_ctrl, 38)
    # Continuous neural canal core rod (subtle museum armature spine rod)
    bm_add_spline_tube(bm_steel, verts_pts[2:-1], [0.042] * (len(verts_pts) - 3), segs=6)

    for idx, pt in enumerate(verts_pts):
        u = idx / (len(verts_pts) - 1)  # 0 = tail tip, ~0.52 = pelvis, ~0.78 = chest, 1.0 = skull base
        if idx < len(verts_pts) - 1:
            fwd = (verts_pts[idx + 1] - pt).normalized()
        else:
            fwd = (pt - verts_pts[idx - 1]).normalized()
        side = Vector((1.0, 0.0, 0.0))
        up_v = fwd.cross(side).normalized()
        if up_v.z < 0:
            up_v = -up_v

        # Vertebra centrum radius peaks around pelvis/dorsals, tapers sharply at tail tip
        if u < 0.50:
            rad = 0.055 + 0.165 * ((u / 0.50) ** 1.15)
        elif u < 0.80:
            rad = 0.215 - 0.045 * ((u - 0.50) / 0.30)
        else:
            rad = 0.165 - 0.035 * ((u - 0.80) / 0.20)

        half_len = 0.095 if u > 0.25 else 0.075
        p_back = pt - fwd * half_len
        p_front = pt + fwd * half_len
        # Hourglass waisted centrum (2 tapered halves)
        bm_add_prism_between(bm_skel, p_back, pt, rad * 1.06, rad * 0.78, segs=8)
        bm_add_prism_between(bm_skel, pt, p_front, rad * 0.78, rad * 1.06, segs=8)

        # Tall neural spine rising dorsally from each vertebra
        ns_h = rad * (2.25 if 0.42 <= u <= 0.82 else (1.55 if u < 0.42 else 1.85))
        ns_w = rad * 0.30
        ns_base = pt + up_v * (rad * 0.65)
        ns_tip = ns_base + up_v * ns_h - fwd * (ns_h * 0.22)
        bm_add_prism_between(bm_skel, ns_base, ns_tip, ns_w * 1.2, ns_w * 0.75, segs=6)

        # Transverse processes (left/right wings on mid-tail & dorsal vertebrae)
        if 0.18 <= u <= 0.84:
            tp_len = rad * 1.35
            for sgn in (-1.0, 1.0):
                bm_add_prism_between(
                    bm_skel,
                    pt + up_v * (rad * 0.2),
                    pt + up_v * (rad * 0.25) + side * (sgn * tp_len),
                    rad * 0.28, rad * 0.14, segs=5
                )

        # Caudal chevrons (haemal arches hanging beneath tail vertebrae)
        if 0.08 <= u <= 0.44:
            ch_len = rad * 1.95
            ch_base = pt - up_v * (rad * 0.7)
            ch_tip = ch_base - up_v * ch_len - fwd * (ch_len * 0.38)
            bm_add_prism_between(bm_skel, ch_base, ch_tip, rad * 0.24, rad * 0.10, segs=5)

    # --- C. Arched Individual Ribcage Pairs (11 dorsal pairs + belly gastralia) ---
    rib_indices = list(range(21, 32))  # 11 thoracic vertebrae
    for ri, v_idx in enumerate(rib_indices):
        t_rib = ri / float(len(rib_indices) - 1)  # 0 = rear rib near pelvis, 1 = front chest rib
        pt = verts_pts[v_idx]
        # Barrel chest profile: widest and deepest around t_rib = 0.55..0.75
        arch_profile = math.sin(0.25 + t_rib * 2.55)
        rib_w = 0.42 + 0.50 * arch_profile
        rib_drop = 0.72 + 0.92 * arch_profile
        rib_r = 0.036 + 0.016 * arch_profile
        for sgn in (-1.0, 1.0):
            rib_pts = []
            rib_rads = []
            for k in range(9):
                a = k / 8.0  # 0 = spine attachment, 1 = ventral tip
                theta = a * math.pi * 0.92
                rx = sgn * (0.12 + rib_w * math.sin(theta))
                ry = -0.22 * math.sin(a * math.pi) - 0.16 * a
                rz = 0.10 * math.sin(a * math.pi * 0.6) - rib_drop * (1.0 - math.cos(theta)) * 0.52
                rib_pts.append(Vector((pt.x + rx, pt.y + ry, pt.z + rz)))
                rib_rads.append(rib_r * (1.15 - 0.55 * a))
            bm_add_spline_tube(bm_skel, rib_pts, rib_rads, segs=6)

    # Delicate ventral gastralia (belly ribs bridging underneath ribcage)
    for gi in range(6):
        gt = gi / 5.0
        gy = 0.85 + gt * 1.45
        gz = 4.02 + gt * 0.34
        gw = 0.46 + 0.18 * math.sin(gt * math.pi)
        g_pts = [
            (-gw, gy - 0.12, gz + 0.22),
            (-gw * 0.52, gy - 0.02, gz + 0.04),
            (0.0, gy + 0.06, gz),
            (gw * 0.52, gy - 0.02, gz + 0.04),
            (gw, gy - 0.12, gz + 0.22),
        ]
        bm_add_spline_tube(bm_skel, g_pts, [0.018, 0.022, 0.024, 0.022, 0.018], segs=5)

    # --- D. Sculpted Pelvic Girdle (Thin Vertical Ilium blades, Pubis w/ boot, Ischium) ---
    hip_y, hip_z = -0.15, 5.05
    for sgn in (-1.0, 1.0):
        # Sculpted thin vertical Ilium bone blade flanking sacral vertebrae (0.20m thick x 0.56m tall)
        ilium_pts = [
            (sgn * 0.28, hip_y - 0.80, hip_z + 0.14),
            (sgn * 0.34, hip_y - 0.30, hip_z + 0.28),
            (sgn * 0.34, hip_y + 0.34, hip_z + 0.26),
            (sgn * 0.28, hip_y + 0.86, hip_z + 0.12),
        ]
        bm_add_spline_tube(bm_skel, ilium_pts, [0.065, 0.105, 0.105, 0.065], segs=8, oval_ratio=2.65)
        # Pelvic bridge connecting ilium directly to sacral spine
        bm_add_prism_between(bm_skel, (0.0, hip_y, hip_z + 0.18), (sgn * 0.36, hip_y, hip_z + 0.12), 0.14, 0.16, segs=7)
        # Acetabulum (hip socket ring)
        bm_add_sphere(bm_skel, (sgn * 0.44, hip_y, hip_z - 0.06), 0.20, 0.24, 0.24, u_segs=10, v_segs=8)
        # Forward-downward sweeping Pubis + Pubic Boot
        pub_pts = [
            (sgn * 0.38, hip_y + 0.06, hip_z - 0.10),
            (sgn * 0.25, hip_y + 0.38, hip_z - 0.68),
            (sgn * 0.10, hip_y + 0.62, hip_z - 1.24),
        ]
        bm_add_spline_tube(bm_skel, pub_pts, [0.11, 0.075, 0.10], segs=7)
        # Backward-downward sweeping Ischium rod
        isc_pts = [
            (sgn * 0.36, hip_y - 0.12, hip_z - 0.12),
            (sgn * 0.24, hip_y - 0.58, hip_z - 0.62),
            (sgn * 0.09, hip_y - 0.98, hip_z - 1.08),
        ]
        bm_add_spline_tube(bm_skel, isc_pts, [0.09, 0.06, 0.045], segs=6)
    # Fused Pubic Boot (classic T-Rex anchor below belly)
    bm_add_box(bm_skel, (0.0, hip_y + 0.60, hip_z - 1.28), (0.28, 0.56, 0.22), rot_euler=(0.15, 0.0, 0.0), bevel=0.04)

    # --- E. Pectoral Girdle & Connected Iconic Tiny Two-Fingered Forelimbs ---
    for sgn in (-1.0, 1.0):
        # Swept-back Scapula blade merging directly into sculpted Coracoid plate & Glenoid socket!
        sh = Vector((sgn * 0.58, 2.34, 4.92))
        scap_pts = [
            sh,
            Vector((sgn * 0.64, 2.22, 5.26)),
            Vector((sgn * 0.62, 1.98, 5.66)),
            Vector((sgn * 0.50, 1.72, 6.02)),
        ]
        bm_add_spline_tube(bm_skel, scap_pts, [0.12, 0.10, 0.085, 0.065], segs=8, oval_ratio=0.55)
        # Coracoid collar connecting shoulder cleanly to ribcage chest
        bm_add_prism_between(bm_skel, sh, Vector((sgn * 0.28, 2.38, 4.78)), 0.10, 0.08, segs=7)
        # Glenoid shoulder ball joint (zero gap!)
        bm_add_sphere(bm_skel, sh, 0.085, 0.095, 0.085, u_segs=8, v_segs=6)
        # Articulated tiny T-Rex arm (Humerus -> Radius/Ulna -> 2-clawed Manus)
        el = Vector((sgn * 0.56, 2.18, 4.44))
        wr = Vector((sgn * 0.48, 2.48, 4.20))
        bm_add_prism_between(bm_skel, sh, el, 0.062, 0.046, segs=8)
        bm_add_sphere(bm_skel, el, 0.052)
        bm_add_prism_between(bm_skel, el, wr, 0.040, 0.030, segs=7)
        bm_add_sphere(bm_skel, wr, 0.036)
        # Two hooked finger claws
        for f_off in (-0.038, 0.038):
            kn = wr + Vector((sgn * f_off, 0.10, -0.05))
            cl = kn + Vector((sgn * f_off * 0.4, 0.11, -0.11))
            bm_add_prism_between(bm_skel, wr, kn, 0.024, 0.017, segs=5)
            bm_add_prism_between(bm_skel, kn, cl, 0.017, 0.004, segs=5)
    # Furcula (wishbone) bridging left & right shoulders cleanly!
    bm_add_spline_tube(
        bm_skel,
        [(-0.56, 2.34, 4.92), (-0.28, 2.48, 4.76), (0.0, 2.54, 4.70), (0.28, 2.48, 4.76), (0.56, 2.34, 4.92)],
        [0.035, 0.032, 0.036, 0.032, 0.035],
        segs=6,
    )

    # --- F. Powerful Articulated Hind Legs & Digitigrade Three-Toed Feet (Planted on Z = 1.85m!) ---
    # Dynamic museum mid-stride: Left leg (-X) slightly forward, Right leg (+X) braced slightly back
    leg_configs = [
        (-1.0, +0.42),  # Left leg stepping forward
        (+1.0, -0.48),  # Right leg striding back
    ]
    foot_z = 1.85
    for sgn, y_stride in leg_configs:
        hip = Vector((sgn * 0.54, hip_y, hip_z - 0.08))
        knee = Vector((sgn * 0.68, hip_y + 0.55 + y_stride * 0.55, 3.68))
        ankle = Vector((sgn * 0.62, hip_y - 0.25 + y_stride * 0.90, 2.56))
        met_base = Vector((sgn * 0.60, hip_y + 0.14 + y_stride, foot_z + 0.16))

        # Massive Femur + hip head + knee condyles
        bm_add_prism_between(bm_skel, Vector((sgn * 0.42, hip_y, hip_z - 0.06)), hip, 0.14, 0.16, segs=8)
        bm_add_prism_between(bm_skel, hip, knee, 0.185, 0.160, segs=10)
        bm_add_sphere(bm_skel, knee, 0.175, 0.21, 0.175, u_segs=10, v_segs=8)

        # Sturdy Tibia + slender parallel Fibula
        bm_add_prism_between(bm_skel, knee, ankle, 0.150, 0.108, segs=10)
        fib_top = knee + Vector((sgn * 0.10, -0.04, -0.05))
        fib_bot = ankle + Vector((sgn * 0.07, -0.02, 0.05))
        bm_add_prism_between(bm_skel, fib_top, fib_bot, 0.046, 0.032, segs=6)
        bm_add_sphere(bm_skel, ankle, 0.118)

        # Elongated Metatarsals (3 fused long foot bones)
        for mo in (-0.055, 0.0, 0.055):
            bm_add_prism_between(
                bm_skel,
                ankle + Vector((mo, 0.0, 0.0)),
                met_base + Vector((mo * 1.4, 0.0, 0.0)),
                0.052, 0.046, segs=6
            )

        # 3 Spreading Articulated Toes + Curved Claws grounded solidly at foot_z (1.85m)
        toe_specs = [
            (-0.42, 0.54, 0.052),  # Inner toe
            (0.00,  0.68, 0.062),  # Center weight-bearing toe
            (+0.42, 0.54, 0.052),  # Outer toe
        ]
        for yaw, t_len, t_rad in toe_specs:
            dir_v = Vector((math.sin(yaw), math.cos(yaw), 0.0))
            p_kn1 = met_base + dir_v * (t_len * 0.42)
            p_kn1.z = foot_z + 0.09
            p_kn2 = met_base + dir_v * (t_len * 0.78)
            p_kn2.z = foot_z + 0.055
            p_tip = met_base + dir_v * t_len
            p_tip.z = foot_z + 0.015
            bm_add_prism_between(bm_skel, met_base, p_kn1, t_rad * 1.05, t_rad * 0.85, segs=6)
            bm_add_prism_between(bm_skel, p_kn1, p_kn2, t_rad * 0.82, t_rad * 0.65, segs=6)
            bm_add_prism_between(bm_skel, p_kn2, p_tip, t_rad * 0.62, 0.012, segs=6)

        # Hallux (rear dewclaw)
        hw_mid = met_base + Vector((-sgn * 0.09, -0.16, 0.16))
        hw_tip = hw_mid + Vector((-sgn * 0.04, -0.14, -0.11))
        bm_add_prism_between(bm_skel, met_base + Vector((0, -0.05, 0.24)), hw_mid, 0.032, 0.022, segs=5)
        bm_add_prism_between(bm_skel, hw_mid, hw_tip, 0.022, 0.006, segs=5)

    # --- G. Sculpted Museum Fenestrated T-Rex Skull (True Open Eye Orbit, Fenestrae, Roaring Jaw, Curved Teeth) ---
    sk_origin = Vector((0.0, 3.44, 7.22))
    sk_rot = Euler((-0.14, 0.0, 0.0), 'XYZ').to_matrix().to_4x4()
    sk_xform = Matrix.Translation(sk_origin) @ sk_rot

    def sk_pt(x, y, z):
        return sk_xform @ Vector((x, y, z))

    # Sculpted Rear Occipital Braincase & Parietal Crest (solid fossil bone at back of skull — NO floating dark egg!)
    bm_add_sphere(bm_skel, sk_pt(0.0, 0.12, 0.12), 0.33, 0.26, 0.30, u_segs=12, v_segs=10)
    # Bony upper palate roof inside the mouth
    bm_add_spline_tube(
        bm_skel,
        [sk_pt(0.0, 0.18, -0.06), sk_pt(0.0, 0.68, -0.08), sk_pt(0.0, 1.18, -0.06), sk_pt(0.0, 1.50, -0.04)],
        [0.24, 0.22, 0.16, 0.10],
        segs=8,
        oval_ratio=0.35,
    )

    # Broad Sculpted Nasal Snout Roof arching gracefully into rounded Premaxilla tip
    nasal_pts = [
        sk_pt(0.0, 0.04, 0.42),
        sk_pt(0.0, 0.42, 0.46),
        sk_pt(0.0, 0.88, 0.39),
        sk_pt(0.0, 1.32, 0.28),
        sk_pt(0.0, 1.56, 0.14),
        sk_pt(0.0, 1.62, -0.04),
    ]
    bm_add_spline_tube(bm_skel, nasal_pts, [0.28, 0.26, 0.21, 0.18, 0.15, 0.12], segs=10, oval_ratio=0.62)

    # Left & Right Sculpted Cheek/Maxilla Arches, Prominent Lacrimal Brow Horns, Open Fenestrae & Roaring Jaw
    for sgn in (-1.0, 1.0):
        # Sculpted Maxilla & Jugal Cheekbone (thick robust curved T-Rex upper jaw rim!)
        max_pts = [
            sk_pt(sgn * 0.42, 0.04, -0.20),
            sk_pt(sgn * 0.39, 0.46, -0.20),
            sk_pt(sgn * 0.31, 0.94, -0.17),
            sk_pt(sgn * 0.21, 1.36, -0.11),
            sk_pt(sgn * 0.11, 1.58, -0.06),
            sk_pt(sgn * 0.02, 1.63, -0.05),
        ]
        bm_add_spline_tube(bm_skel, max_pts, [0.13, 0.125, 0.115, 0.105, 0.095, 0.085], segs=8, oval_ratio=1.25)

        # Prominent Sculpted Supraorbital / Lacrimal Brow Crest above eye socket!
        brow_pts = [
            sk_pt(sgn * 0.38, 0.08, 0.40),
            sk_pt(sgn * 0.40, 0.40, 0.46),
            sk_pt(sgn * 0.32, 0.72, 0.43),
            sk_pt(sgn * 0.24, 1.08, 0.32),
            sk_pt(sgn * 0.16, 1.44, 0.18),
        ]
        bm_add_spline_tube(bm_skel, brow_pts, [0.11, 0.125, 0.12, 0.095, 0.08], segs=8, oval_ratio=0.85)
        # Signature T-Rex Lacrimal Horn Boss just forward of the eye socket
        bm_add_sphere(bm_skel, sk_pt(sgn * 0.35, 0.70, 0.45), 0.09, 0.13, 0.09, u_segs=8, v_segs=6)

        # Curved Sculpted Fenestra Struts forming authentic T-Rex skull openings:
        # 1. Broad Quadrate / Squamosal rear jaw-hinge cheek arch
        bm_add_spline_tube(
            bm_skel,
            [sk_pt(sgn * 0.40, 0.02, 0.38), sk_pt(sgn * 0.44, 0.00, 0.08), sk_pt(sgn * 0.42, 0.05, -0.22)],
            [0.11, 0.12, 0.10],
            segs=8,
        )
        # 2. Curved Postorbital bar (separates temporal fenestra from keyhole Eye Orbit!)
        bm_add_spline_tube(
            bm_skel,
            [sk_pt(sgn * 0.39, 0.36, 0.42), sk_pt(sgn * 0.40, 0.42, 0.12), sk_pt(sgn * 0.38, 0.38, -0.14)],
            [0.085, 0.080, 0.085],
            segs=7,
        )
        # 3. Robust Lacrimal pillar (separates Eye Orbit from large Antorbital Fenestra!)
        bm_add_spline_tube(
            bm_skel,
            [sk_pt(sgn * 0.33, 0.70, 0.41), sk_pt(sgn * 0.34, 0.68, 0.12), sk_pt(sgn * 0.33, 0.70, -0.15)],
            [0.085, 0.078, 0.085],
            segs=7,
        )
        # 4. Sculpted Anterior Maxillary bridge (separates Antorbital Fenestra from Nostril Naris!)
        bm_add_spline_tube(
            bm_skel,
            [sk_pt(sgn * 0.22, 1.18, 0.28), sk_pt(sgn * 0.24, 1.16, 0.06), sk_pt(sgn * 0.24, 1.14, -0.12)],
            [0.090, 0.095, 0.095],
            segs=7,
        )
        # 5. Curved Premaxilla front snout wall
        bm_add_spline_tube(
            bm_skel,
            [sk_pt(sgn * 0.13, 1.54, 0.14), sk_pt(sgn * 0.14, 1.56, 0.02), sk_pt(sgn * 0.12, 1.56, -0.08)],
            [0.085, 0.090, 0.085],
            segs=7,
        )

        # Articulated Lower Jaw / Mandible (gaped open ~26° in dynamic museum roar!)
        jaw_hinge = sk_pt(sgn * 0.38, 0.05, -0.22)
        jaw_rot = sk_rot @ Euler((-0.44, 0.0, 0.0), 'XYZ').to_matrix().to_4x4()

        def j_pt(x, y, z):
            return sk_origin + (jaw_rot @ Vector((x, y, z)))

        mand_pts = [
            jaw_hinge,
            j_pt(sgn * 0.36, 0.42, -0.35),
            j_pt(sgn * 0.28, 0.90, -0.32),
            j_pt(sgn * 0.18, 1.32, -0.27),
            j_pt(sgn * 0.05, 1.50, -0.22),
        ]
        bm_add_spline_tube(bm_skel, mand_pts, [0.115, 0.135, 0.105, 0.090, 0.075], segs=8, oval_ratio=1.25)
        # Upper Surangular coronoid arch framing the mandibular fenestra cleanly
        bm_add_spline_tube(
            bm_skel,
            [jaw_hinge + Vector((0, 0.04, 0.06)), j_pt(sgn * 0.34, 0.44, -0.18), j_pt(sgn * 0.27, 0.78, -0.24)],
            [0.075, 0.070, 0.065],
            segs=7,
        )

        # Individual Thick Curved Banana-Shaped T-Rex Teeth — Upper Jaw (9 per side = 18 upper teeth!)
        for ti in range(9):
            ft = ti / 8.0
            ty = 0.52 + ft * 1.04
            tx = sgn * (0.34 - ft * 0.25)
            tz = -0.18 + ft * 0.11
            t_len = 0.13 + 0.095 * math.sin(ft * math.pi * 0.85)
            p_base = sk_pt(tx, ty, tz + 0.03)
            p_mid = sk_pt(tx * 0.98, ty - 0.015, tz - t_len * 0.52)
            p_tip = sk_pt(tx * 0.95, ty - 0.050, tz - t_len)
            bm_add_spline_tube(bm_teeth, [p_base, p_mid, p_tip], [0.032, 0.022, 0.004], segs=6)

        # Individual Curved Conical T-Rex Teeth — Lower Jaw (8 per side = 16 lower teeth!)
        for ti in range(8):
            ft = ti / 7.0
            ty = 0.58 + ft * 0.86
            tx = sgn * (0.28 - ft * 0.20)
            tz = -0.25 + ft * 0.04
            t_len = 0.10 + 0.065 * math.sin(ft * math.pi * 0.85)
            p_base = j_pt(tx, ty, tz - 0.03)
            p_mid = j_pt(tx * 0.97, ty - 0.01, tz + t_len * 0.52)
            p_tip = j_pt(tx * 0.94, ty - 0.04, tz + t_len)
            bm_add_spline_tube(bm_teeth, [p_base, p_mid, p_tip], [0.025, 0.017, 0.003], segs=6)

    # --- H. Sleek Museum Steel Support Stanchions (grounding Stan onto the basalt plinth) ---
    bm_add_prism_between(bm_steel, (0.0, -0.20, foot_z), (0.0, -0.20, 4.98), 0.075, 0.065, segs=10)
    bm_add_prism_between(bm_steel, (0.0, -0.20, foot_z), (0.0, -0.20, foot_z + 0.06), 0.24, 0.22, segs=12)
    bm_add_prism_between(bm_steel, (0.0, 1.85, foot_z), (0.0, 1.85, 5.42), 0.055, 0.045, segs=10)
    bm_add_prism_between(bm_steel, (0.0, 1.85, foot_z), (0.0, 1.85, foot_z + 0.05), 0.18, 0.16, segs=12)
    bm_add_prism_between(bm_steel, (0.0, -2.55, foot_z), (0.0, -3.20, 4.68), 0.042, 0.036, segs=8)
    bm_add_prism_between(bm_steel, (0.0, -2.55, foot_z), (0.0, -2.55, foot_z + 0.05), 0.16, 0.14, segs=10)

    bm_recess.free()
    finalize_mesh("Stan_Skeleton", bm_skel, mat_bone, smooth=True, uv_scale=0.6)
    finalize_mesh("Stan_Teeth", bm_teeth, mat_teeth, smooth=True, uv_scale=1.0)
    finalize_mesh("Stan_ArmatureSupports", bm_steel, mat_steel, smooth=True, uv_scale=0.5)

    return export_asset("landmark_stan_trex.glb")


# ===========================================================================
# 2–5. AUTHENTIC GOOGLEPLEX QUAD BUILDINGS (B40, B41, B42, B43)
# ===========================================================================
def add_exterior_staircase(bm_conc, bm_metal, p_base, dir_run, dir_out, height=6.4, width=2.4):
    """
    Build a walkable 2-flight exterior architectural staircase with mid-landing and brushed steel handrails.
    dir_run: unit vector along the building wall; dir_out: outward unit normal from the wall.
    """
    # Place staircase protruding outward by `width` along dir_out
    p0 = Vector((p_base[0], p_base[1], 0.0))
    run_v = Vector((dir_run[0], dir_run[1], 0.0)).normalized()
    out_v = Vector((dir_out[0], dir_out[1], 0.0)).normalized()
    yaw = math.atan2(run_v.y, run_v.x)

    n_steps = 16
    total_run = 10.2
    step_d = total_run / n_steps
    step_h = height / n_steps

    # Stepped solid sloped ramp underside + individual crisp treads (cleanly grounded at Z >= 0.0)
    for i in range(n_steps):
        z_top = (i + 1) * step_h
        z_bot = max(0.0, z_top - step_h - 0.14)
        h_box = z_top - z_bot
        d_center = (i + 0.5) * step_d
        c = p0 + run_v * d_center + out_v * (width * 0.52)
        bm_add_box(bm_conc, (c.x, c.y, z_bot + h_box * 0.5), (step_d * 1.06, width, h_box), rot_euler=(0, 0, yaw))
        # Structural steel stringer support column at mid-span and top
        if i in (7, 15):
            for w_frac in (0.12, 0.88):
                pc = p0 + run_v * d_center + out_v * (width * w_frac)
                bm_add_prism_between(bm_metal, (pc.x, pc.y, 0.0), (pc.x, pc.y, z_top - 0.1), 0.08, 0.08, segs=8)

    # Top rooftop landing platform at Z = height (6.4m) bridging cleanly into parapet opening
    top_c = p0 + run_v * (total_run + 1.15) + out_v * (width * 0.52)
    bm_add_box(bm_conc, (top_c.x, top_c.y, height - 0.14), (2.45, width + 0.25, 0.28), rot_euler=(0, 0, yaw))

    # Brushed steel handrails + balusters along outer & inner edges of stair run
    rail_h = 1.05
    for w_frac in (0.08, 0.96):
        r0 = p0 + out_v * (width * w_frac) + Vector((0, 0, rail_h))
        r1 = p0 + run_v * total_run + out_v * (width * w_frac) + Vector((0, 0, height + rail_h))
        r2 = p0 + run_v * (total_run + 2.25) + out_v * (width * w_frac) + Vector((0, 0, height + rail_h))
        # Top handrail & mid safety rail
        bm_add_prism_between(bm_metal, r0, r1, 0.032, 0.032, segs=6)
        bm_add_prism_between(bm_metal, r0 - Vector((0, 0, 0.45)), r1 - Vector((0, 0, 0.45)), 0.020, 0.020, segs=6)
        if w_frac > 0.5:
            bm_add_prism_between(bm_metal, r1, r2, 0.032, 0.032, segs=6)
            bm_add_prism_between(bm_metal, r1 - Vector((0, 0, 0.45)), r2 - Vector((0, 0, 0.45)), 0.020, 0.020, segs=6)
        # Vertical stanchion balusters
        for k in range(7):
            ft = k / 6.0
            pb = p0 + run_v * (ft * total_run) + out_v * (width * w_frac) + Vector((0, 0, ft * height))
            bm_add_prism_between(bm_metal, pb, pb + Vector((0, 0, rail_h)), 0.024, 0.024, segs=6)


def build_quad_building(
    filename,
    prefix,
    svg_poly,
    cx_svg,
    cy_svg,
    accent_hex,
    solar_density=1.0,
    solar_yaw=0.0,
    stair_edge_idx=None,
    stair_t=0.35,
    add_charlies_patio=False,
    add_entry_overhang_edge=None,
    overhang_t=0.5,
    doorways=None,
    interior_cols=None,
    interior_partitions=None,
    world_offset=(0.0, 0.0),
):
    """
    Authentic SGI / Googleplex 2-story faceted architectural building generator
    with TRUE HOLLOW PLAYABLE GROUND-FLOOR OFFICE INTERIORS:
      - 0.45m thick hollow perimeter walls (Z = 0.0..6.40m) with wide 6.0-7.2m open
        glass lobby doorway cutouts (Z = 0.04..3.60m completely open walkthrough!)
      - Clean walkable polished concrete + warm-oak office ground floor slab (Z = 0.04m)
      - Soaring recessed acoustic interior ceiling (Z = 5.75m) w/ structural beams & glowing LED strips
      - Sleek structural support columns & frosted-glass/cedar interior partition accents
      - Exact exterior silhouette, exterior rooftop staircases, solar arrays, HVAC & +6.4m walkable roof deck!
    """
    reset_scene()
    poly = svg_poly_to_local(svg_poly, cx_svg, cy_svg)
    n = len(poly)
    doorways = doorways or []
    interior_cols = interior_cols or []
    interior_partitions = interior_partitions or []
    wx0, wz0 = world_offset

    tex_conc = gen_concrete_tex(f"{prefix}_ConcTex", 128, tint=(0.86, 0.82, 0.76), seed=300 + len(prefix))
    tex_solar = gen_solar_panel_tex(f"{prefix}_SolarTex", 160, seed=310 + len(prefix))
    tex_glass = gen_curtain_glass_tex(f"{prefix}_GlassTex", 128, seed=320 + len(prefix))
    tex_oak = gen_oak_floor_tex(f"{prefix}_OakFloorTex", 128, seed=330 + len(prefix))

    mat_conc = make_pbr_mat(f"{prefix}_Concrete", base_color=hex_to_linear("#DED7CA"), roughness=0.78, tex_img=tex_conc)
    mat_roof = make_pbr_mat(f"{prefix}_RoofDeck", base_color=hex_to_linear("#B7BDC6"), roughness=0.84, tex_img=tex_conc, tex_tint=hex_to_linear("#C4C9D0"))
    mat_floor_conc = make_pbr_mat(f"{prefix}_OfficeConcreteFloor", base_color=hex_to_linear("#DDD8CF"), roughness=0.58, tex_img=tex_conc)
    mat_floor_oak = make_pbr_mat(f"{prefix}_OfficeOakFloor", base_color=(1, 1, 1, 1), roughness=0.54, tex_img=tex_oak)
    mat_int_wall = make_pbr_mat(f"{prefix}_InteriorDrywall", base_color=hex_to_linear("#EFECE6"), roughness=0.82)
    mat_ceiling = make_pbr_mat(f"{prefix}_AcousticCeiling", base_color=hex_to_linear("#ECEFF3"), roughness=0.88)
    mat_led = make_pbr_mat(
        f"{prefix}_OfficeLED",
        base_color=hex_to_linear("#FFF8EA"),
        roughness=0.20,
        emission=hex_to_linear("#FFF1D6"),
        emission_strength=2.6,
    )
    mat_glass_upper = make_pbr_mat(
        f"{prefix}_CurtainGlassUpper",
        base_color=hex_to_linear("#5DA8E6", alpha=0.52),
        metallic=0.28,
        roughness=0.08,
        ior=1.52,
        alpha=0.52,
        specular=0.85,
        tex_img=tex_glass,
        double_sided=True,
    )
    mat_glass_lower = make_pbr_mat(
        f"{prefix}_CurtainGlassLower",
        base_color=hex_to_linear("#78C2F4", alpha=0.34),
        metallic=0.18,
        roughness=0.06,
        ior=1.52,
        alpha=0.34,
        specular=0.88,
        double_sided=True,
    )
    mat_glass_frost = make_pbr_mat(
        f"{prefix}_PartitionFrostGlass",
        base_color=hex_to_linear("#C9E2F5", alpha=0.46),
        metallic=0.08,
        roughness=0.28,
        ior=1.50,
        alpha=0.46,
        double_sided=True,
    )
    mat_alum = make_pbr_mat(f"{prefix}_Aluminum", base_color=hex_to_linear("#C6CDD6"), metallic=0.82, roughness=0.28)
    mat_dark_metal = make_pbr_mat(f"{prefix}_DarkMetal", base_color=hex_to_linear("#353D49"), metallic=0.78, roughness=0.38)
    mat_mat_charcoal = make_pbr_mat(f"{prefix}_WelcomeMat", base_color=hex_to_linear("#2B313B"), roughness=0.95)
    mat_accent = make_pbr_mat(f"{prefix}_AccentTrim", base_color=hex_to_linear(accent_hex), metallic=0.22, roughness=0.42)
    mat_part_wood = make_pbr_mat(f"{prefix}_PartitionCedar", base_color=hex_to_linear("#B37645"), roughness=0.62)
    mat_solar = make_pbr_mat(f"{prefix}_SolarArray", base_color=(1, 1, 1, 1), metallic=0.38, roughness=0.18, tex_img=tex_solar)

    bm_conc = bmesh.new()
    bm_roof = bmesh.new()
    bm_floor_conc = bmesh.new()
    bm_floor_oak = bmesh.new()
    bm_int_wall = bmesh.new()
    bm_ceiling = bmesh.new()
    bm_led = bmesh.new()
    bm_glass_up = bmesh.new()
    bm_glass_lo = bmesh.new()
    bm_glass_frost = bmesh.new()
    bm_alum = bmesh.new()
    bm_dark = bmesh.new()
    bm_mat = bmesh.new()
    bm_accent = bmesh.new()
    bm_part_wood = bmesh.new()
    bm_solar = bmesh.new()

    roof_z = 6.40
    ceil_z = 5.75
    door_h = 3.60
    parapet_z = 7.25
    wall_thk = 0.45
    half_wall = wall_thk * 0.5

    def inset_poly(p_list, dist):
        out = []
        m = len(p_list)
        for i in range(m):
            p_prev = Vector(p_list[(i - 1) % m])
            p_curr = Vector(p_list[i])
            p_next = Vector(p_list[(i + 1) % m])
            e1 = (p_curr - p_prev).normalized()
            e2 = (p_next - p_curr).normalized()
            n1 = Vector((-e1.y, e1.x))
            n2 = Vector((-e2.y, e2.x))
            bis = (n1 + n2)
            if bis.length < 1e-4:
                bis = n1
            else:
                bis.normalize()
            denom = max(0.35, bis.dot(n1))
            out.append((p_curr.x + bis.x * dist / denom, p_curr.y + bis.y * dist / denom))
        return out

    inner_ceil_poly = inset_poly(poly, 0.42)
    oak_zone_poly = inset_poly(poly, 2.20)

    # 1. Clean Walkable Polished Concrete Ground Floor Slab (Z = 0.00..0.04m) + Warm-Oak Interior Flooring Zone
    bm_add_polygon_prism(bm_floor_conc, poly, 0.00, 0.04, cap_bottom=True, cap_top=True)
    bm_add_polygon_prism(bm_floor_oak, oak_zone_poly, 0.042, 0.056, cap_bottom=False, cap_top=True)

    # 2. Recessed Acoustic Interior Ceiling (Z = 5.75..6.02m) & Walkable Roof Deck (Z = 6.02..6.40m)
    bm_add_polygon_prism(bm_ceiling, inner_ceil_poly, ceil_z, 6.02, cap_bottom=True, cap_top=False)
    bm_add_polygon_prism(bm_roof, poly, 6.02, roof_z, cap_bottom=True, cap_top=True)

    # Group doorways per edge index
    doors_by_edge = {}
    for e_idx, d0, d1 in doorways:
        doors_by_edge.setdefault(e_idx, []).append((d0, d1))
    for k in doors_by_edge:
        doors_by_edge[k].sort()

    # 3. Hollow Perimeter Walls (0.45m thick) + Open Glass Lobby Doorway Cutouts + Upper Facade & Parapet
    stair_info = None
    doorway_log = []
    for i in range(n):
        pA = Vector((poly[i][0], poly[i][1], 0.0))
        pB = Vector((poly[(i + 1) % n][0], poly[(i + 1) % n][1], 0.0))
        edge_v = pB - pA
        L = edge_v.length
        if L < 1.0:
            continue
        t_dir = edge_v / L
        out_n = Vector((t_dir.y, -t_dir.x, 0.0))
        yaw = math.atan2(t_dir.y, t_dir.x)
        mid_e = (pA + pB) * 0.5

        edge_doors = doors_by_edge.get(i, [])
        # Build list of solid lower-floor wall intervals [s0, s1] by subtracting doorway cutouts
        solid_segs = []
        cursor = 0.0
        for d0, d1 in edge_doors:
            if d0 > cursor + 0.05:
                solid_segs.append((cursor, d0))
            cursor = max(cursor, d1)
        if L > cursor + 0.05:
            solid_segs.append((cursor, L))

        # Full-height corner concrete pier sealing polygon vertices cleanly
        bm_add_box(bm_conc, (pA.x - out_n.x * 0.04, pA.y - out_n.y * 0.04, parapet_z * 0.5), (0.96, 0.96, parapet_z), rot_euler=(0, 0, yaw))

        # Continuous Mid-Story Perimeter Spandrel Ring (Z = 3.56..3.96m, 0.45m thick — hollow center!)
        sp_c = mid_e - out_n * half_wall
        bm_add_box(bm_conc, (sp_c.x, sp_c.y, 3.76), (L + 0.10, wall_thk, 0.40), rot_euler=(0, 0, yaw))
        # Colored Googleplex architectural accent ribbons along spandrel & roof fascia
        bm_add_box(bm_accent, (mid_e.x + out_n.x * 0.05, mid_e.y + out_n.y * 0.05, 3.76), (L - 0.6, 0.12, 0.22), rot_euler=(0, 0, yaw))
        bm_add_box(bm_accent, (mid_e.x + out_n.x * 0.05, mid_e.y + out_n.y * 0.05, 6.26), (L - 0.6, 0.12, 0.20), rot_euler=(0, 0, yaw))

        # Continuous Upper-Story Perimeter Curtain Glass & Framing (Z = 3.96..6.02m, hollow!)
        bm_add_box(bm_glass_up, (mid_e.x - out_n.x * 0.24, mid_e.y - out_n.y * 0.24, 4.99), (L - 0.5, 0.06, 2.06), rot_euler=(0, 0, yaw))
        bm_add_box(bm_alum, (mid_e.x - out_n.x * 0.24, mid_e.y - out_n.y * 0.24, 4.98), (L - 0.8, 0.16, 0.08), rot_euler=(0, 0, yaw))
        # Upper perimeter interior acoustic header soffit edge
        bm_add_box(bm_int_wall, (sp_c.x, sp_c.y, 5.88), (L - 0.4, wall_thk, 0.28), rot_euler=(0, 0, yaw))

        # Lower-Floor Solid Perimeter Wall Segments (Z = 0.0..3.60m, 0.45m thick, skipping doorways!)
        for s0, s1 in solid_segs:
            seg_len = s1 - s0
            if seg_len < 0.25:
                continue
            sc = pA + t_dir * ((s0 + s1) * 0.5)
            # Exterior concrete foundation plinth (Z = 0.00..0.44m) + upper concrete sill band (0.44..1.00m)
            bm_add_box(bm_conc, (sc.x - out_n.x * 0.12, sc.y - out_n.y * 0.12, 0.50), (seg_len, 0.24, 1.00), rot_euler=(0, 0, yaw))
            # Interior bright architectural drywall knee-wall (Z = 0.04..1.00m) + dark baseboard
            bm_add_box(bm_int_wall, (sc.x - out_n.x * 0.34, sc.y - out_n.y * 0.34, 0.52), (seg_len, 0.22, 0.96), rot_euler=(0, 0, yaw))
            bm_add_box(bm_dark, (sc.x - out_n.x * 0.445, sc.y - out_n.y * 0.445, 0.10), (seg_len, 0.03, 0.12), rot_euler=(0, 0, yaw))
            # Brushed aluminum window sill cap spanning full 0.46m wall thickness at Z = 1.02m
            bm_add_box(bm_alum, (sc.x - out_n.x * half_wall, sc.y - out_n.y * half_wall, 1.02), (seg_len, wall_thk + 0.04, 0.06), rot_euler=(0, 0, yaw))
            # Sunlit translucent curtain-wall window pane (Z = 1.04..3.56m) + horizontal mid-transom
            bm_add_box(bm_glass_lo, (sc.x - out_n.x * 0.22, sc.y - out_n.y * 0.22, 2.30), (seg_len, 0.06, 2.52), rot_euler=(0, 0, yaw))
            bm_add_box(bm_alum, (sc.x - out_n.x * 0.22, sc.y - out_n.y * 0.22, 2.34), (seg_len, 0.16, 0.08), rot_euler=(0, 0, yaw))

        # Helper to check if distance s along edge falls inside any doorway clearance
        def in_doorway(s_val, margin=0.35):
            return any((d0 - margin) <= s_val <= (d1 + margin) for d0, d1 in edge_doors)

        # Vertical mullions & periodic concrete pilasters along edge
        bay_spacing = 2.45
        n_bays = max(2, int(round(L / bay_spacing)))
        for b in range(1, n_bays):
            s_pos = L * (b / float(n_bays))
            pm = pA + t_dir * s_pos
            if in_doorway(s_pos):
                # Upper-floor mullion ONLY above open doorway!
                bm_add_box(bm_alum, (pm.x - out_n.x * 0.24, pm.y - out_n.y * 0.24, 4.99), (0.11, 0.20, 2.06), rot_euler=(0, 0, yaw))
            elif b % 4 == 0 and L > 14.0:
                # Full-height concrete structural pilaster pier
                bm_add_box(bm_conc, (pm.x - out_n.x * 0.18, pm.y - out_n.y * 0.18, roof_z * 0.5), (0.66, 0.48, roof_z), rot_euler=(0, 0, yaw))
                bm_add_box(bm_int_wall, (pm.x - out_n.x * 0.38, pm.y - out_n.y * 0.38, ceil_z * 0.5), (0.64, 0.14, ceil_z - 0.04), rot_euler=(0, 0, yaw))
            else:
                # Full-height vertical aluminum curtain mullion
                bm_add_box(bm_alum, (pm.x - out_n.x * 0.22, pm.y - out_n.y * 0.22, 3.52), (0.11, 0.22, 5.04), rot_euler=(0, 0, yaw))

        # Open Glass Lobby Doorway Portal Frames, Retracted Sliding Doors, Welcome Mats & Entry Canopy Brows!
        for d0, d1 in edge_doors:
            d_w = d1 - d0
            d_mid_s = 0.5 * (d0 + d1)
            dm = pA + t_dir * d_mid_s
            p_d0 = pA + t_dir * d0
            p_d1 = pA + t_dir * d1
            doorway_log.append((
                i, d0, d1, d_w,
                (wx0 + p_d0.x, wz0 - p_d0.y),
                (wx0 + p_d1.x, wz0 - p_d1.y),
                (wx0 + dm.x, wz0 - dm.y),
                (out_n.x, -out_n.y),
            ))
            # Left & Right brushed-aluminum portal jambs framing the open doorway
            for dp in (p_d0, p_d1):
                bm_add_box(bm_alum, (dp.x - out_n.x * half_wall, dp.y - out_n.y * half_wall, door_h * 0.5 + 0.02), (0.18, wall_thk + 0.10, door_h), rot_euler=(0, 0, yaw))
            # Overhead lobby header portal fascia + glowing LED entrance signage bar (exterior & interior!)
            bm_add_box(bm_dark, (dm.x - out_n.x * (half_wall - 0.05), dm.y - out_n.y * (half_wall - 0.05), door_h + 0.16), (d_w + 0.36, wall_thk + 0.26, 0.34), rot_euler=(0, 0, yaw))
            bm_add_box(bm_led, (dm.x + out_n.x * 0.19, dm.y + out_n.y * 0.19, door_h + 0.16), (d_w - 0.6, 0.04, 0.10), rot_euler=(0, 0, yaw))
            bm_add_box(bm_led, (dm.x - out_n.x * (wall_thk + 0.09), dm.y - out_n.y * (wall_thk + 0.09), door_h + 0.16), (d_w - 0.6, 0.04, 0.10), rot_euler=(0, 0, yaw))
            # Flush aluminum threshold sill plate & interior recessed charcoal welcome mat
            bm_add_box(bm_alum, (dm.x - out_n.x * half_wall, dm.y - out_n.y * half_wall, 0.048), (d_w, wall_thk + 0.06, 0.014), rot_euler=(0, 0, yaw))
            bm_add_box(bm_mat, (dm.x - out_n.x * 1.38, dm.y - out_n.y * 1.38, 0.058), (d_w - 0.4, 1.70, 0.016), rot_euler=(0, 0, yaw))
            # Retracted open automatic sliding glass door leaves parked neatly OUTSIDE the opening
            for sgn, anchor_s in ((-1.0, d0 - 0.72), (1.0, d1 + 0.72)):
                if 0.8 < anchor_s < L - 0.8:
                    lp = pA + t_dir * anchor_s - out_n * (wall_thk + 0.07)
                    bm_add_box(bm_glass_lo, (lp.x, lp.y, 1.78), (1.18, 0.035, 3.44), rot_euler=(0, 0, yaw))
                    bm_add_box(bm_alum, (lp.x, lp.y, 3.52), (1.22, 0.06, 0.08), rot_euler=(0, 0, yaw))
                    bm_add_box(bm_alum, (lp.x - t_dir.x * sgn * 0.46, lp.y - t_dir.y * sgn * 0.46, 1.25), (0.04, 0.12, 0.85), rot_euler=(0, 0, yaw))
            # Cantilevered glass & aluminum entry brow canopy (if edge has no full overhang or Charlie's patio)
            is_charlies_edge = add_charlies_patio and out_n.y < -0.5 and L > 30.0
            if not is_charlies_edge and (add_entry_overhang_edge is None or i != add_entry_overhang_edge):
                bc = dm + out_n * 0.90
                bm_add_box(bm_alum, (bc.x, bc.y, 3.78), (d_w + 1.2, 1.80, 0.16), rot_euler=(0, 0, yaw))
                bm_add_box(bm_accent, (bc.x + out_n.x * 0.90, bc.y + out_n.y * 0.90, 3.78), (d_w + 1.24, 0.08, 0.18), rot_euler=(0, 0, yaw))

        has_stair = (stair_edge_idx is not None and i == stair_edge_idx)

        # Cantilevered SGI/Googleplex Aluminum Brise-Soleil Sun-Louvers above both floors
        if not has_stair:
            for lz in (3.70, 6.02):
                for b_off in (-0.20, 0.0, 0.22):
                    lc = mid_e + out_n * (0.44 + b_off)
                    bm_add_box(bm_alum, (lc.x, lc.y, lz), (L - 1.4, 0.10, 0.055), rot_euler=(0, 0, yaw))
                n_br = max(2, int(L / 4.2))
                for k in range(n_br + 1):
                    pb = pA.lerp(pB, 0.06 + 0.88 * k / max(1, n_br)) + out_n * 0.36
                    bm_add_box(bm_dark, (pb.x, pb.y, lz - 0.04), (0.07, 0.78, 0.08), rot_euler=(0, 0, yaw))

        # Rooftop Perimeter Parapet Wall (Z = 6.40..7.25m) + Coping Cap (preserving stair cutout!)
        if has_stair:
            stair_start = max(1.5, min(L - 13.5, L * stair_t))
            gap_a = min(L - 1.2, stair_start + 10.0)
            gap_b = min(L - 0.5, stair_start + 12.6)
            segments = []
            if gap_a > 0.8:
                segments.append((0.0, gap_a))
            if L - gap_b > 0.8:
                segments.append((gap_b, L))
            stair_info = (pA + t_dir * stair_start, t_dir, out_n)
        else:
            segments = [(0.0, L)]

        for s0, s1 in segments:
            seg_len = s1 - s0
            sc = pA + t_dir * ((s0 + s1) * 0.5) - out_n * 0.21
            bm_add_box(bm_conc, (sc.x, sc.y, (roof_z + parapet_z) * 0.5), (seg_len, 0.42, parapet_z - roof_z), rot_euler=(0, 0, yaw))
            bm_add_box(bm_dark, (sc.x, sc.y, parapet_z + 0.05), (seg_len + 0.06, 0.50, 0.10), rot_euler=(0, 0, yaw))

        # Optional Shaded Architectural Entry Overhang (framed cleanly above Z=3.60m open doorway!)
        if add_entry_overhang_edge is not None and i == add_entry_overhang_edge:
            ov_w = min(11.4, max(10.2, L * 0.44))
            ov_d = 3.8
            ov_anchor = pA.lerp(pB, overhang_t)
            ov_c = ov_anchor + out_n * (ov_d * 0.5)
            bm_add_box(bm_alum, (ov_c.x, ov_c.y, 3.78), (ov_w, ov_d, 0.24), rot_euler=(0, 0, yaw))
            bm_add_box(bm_accent, (ov_c.x + out_n.x * (ov_d * 0.5), ov_c.y + out_n.y * (ov_d * 0.5), 3.78), (ov_w + 0.08, 0.10, 0.28), rot_euler=(0, 0, yaw))
            for c_sgn in (-0.42, 0.42):
                pc = ov_anchor + t_dir * (ov_w * c_sgn) + out_n * (ov_d - 0.55)
                bm_add_prism_between(bm_dark, (pc.x, pc.y, 0.0), (pc.x, pc.y, 3.68), 0.16, 0.13, segs=12)
                bm_add_prism_between(bm_conc, (pc.x, pc.y, 0.0), (pc.x, pc.y, 0.35), 0.26, 0.24, segs=12)

    # 4. Interior Structural Support Columns, Frosted-Glass/Cedar Partitions & Glowing LED Ceiling Strips!
    for cx, cy in interior_cols:
        bm_add_prism_between(bm_int_wall, (cx, cy, 0.04), (cx, cy, ceil_z), 0.28, 0.26, segs=12)
        bm_add_prism_between(bm_dark, (cx, cy, 0.04), (cx, cy, 0.26), 0.33, 0.31, segs=12)
        bm_add_prism_between(bm_alum, (cx, cy, ceil_z - 0.18), (cx, cy, ceil_z), 0.35, 0.35, segs=12)

    for px, py, p_len, p_yaw in interior_partitions:
        pt_dir = Vector((math.cos(p_yaw), math.sin(p_yaw), 0.0))
        pc = Vector((px, py, 0.0))
        # Dark aluminum perimeter partition frame (Z = 0.04..2.84m)
        bm_add_box(bm_dark, (px, py, 0.10), (p_len, 0.16, 0.12), rot_euler=(0, 0, p_yaw))
        bm_add_box(bm_dark, (px, py, 2.80), (p_len, 0.16, 0.10), rot_euler=(0, 0, p_yaw))
        bm_add_box(bm_accent, (px, py, 2.86), (p_len - 0.2, 0.18, 0.06), rot_euler=(0, 0, p_yaw))
        for sgn in (-1.0, 1.0):
            ep = pc + pt_dir * (sgn * (p_len * 0.5 - 0.05))
            bm_add_box(bm_dark, (ep.x, ep.y, 1.44), (0.10, 0.16, 2.80), rot_euler=(0, 0, p_yaw))
            # Vertical warm-cedar acoustic fins flanking both ends
            for f_off in (0.24, 0.44):
                fp = pc + pt_dir * (sgn * (p_len * 0.5 - f_off))
                bm_add_box(bm_part_wood, (fp.x, fp.y, 1.44), (0.07, 0.18, 2.66), rot_euler=(0, 0, p_yaw))
        # Translucent frosted glass core panel
        bm_add_box(bm_glass_frost, (px, py, 1.45), (p_len - 1.15, 0.045, 2.60), rot_euler=(0, 0, p_yaw))

    # Recessed Interior Ceiling Exposed Beams & Glowing Linear LED Office Light Strips (Z = 5.56..5.74m)
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    cy_cos, cy_sin = math.cos(solar_yaw), math.sin(solar_yaw)
    for ui in range(-8, 9):
        for vi in range(-6, 7):
            lx = ui * 7.6
            ly = vi * 6.8
            wx = lx * cy_cos - ly * cy_sin
            wy = lx * cy_sin + ly * cy_cos
            if point_in_poly_2d(wx, wy, poly) and min_dist_to_poly_edges(wx, wy, poly) > 3.8:
                # Suspended linear aluminum troffer housing + bright glowing LED office diffuser strip
                bm_add_box(bm_alum, (wx, wy, ceil_z - 0.11), (4.2, 0.28, 0.10), rot_euler=(0, 0, solar_yaw))
                bm_add_box(bm_led, (wx, wy, ceil_z - 0.175), (3.95, 0.22, 0.04), rot_euler=(0, 0, solar_yaw))
                # Twin thin aircraft suspension cables up to acoustic ceiling
                for csgn in (-1.65, 1.65):
                    sx = wx + math.cos(solar_yaw) * csgn
                    sy = wy + math.sin(solar_yaw) * csgn
                    bm_add_prism_between(bm_dark, (sx, sy, ceil_z - 0.06), (sx, sy, ceil_z), 0.014, 0.014, segs=4)

    # 5. Exterior Walkable Staircase with Handrails
    if stair_info is not None:
        add_exterior_staircase(bm_conc, bm_alum, stair_info[0], stair_info[1], stair_info[2], height=roof_z, width=2.4)

    # 6. Charlie's Café Outdoor Patio Awning & Microkitchen Bar (B40 Signature!)
    if add_charlies_patio:
        tex_cedar = gen_cedar_wood_tex("B40_CedarTex", 192, seed=340)
        mat_cedar = make_pbr_mat("B40_CedarWood", base_color=hex_to_linear("#B37242"), roughness=0.68, tex_img=tex_cedar)
        mat_warm_glow = make_pbr_mat("B40_CafeGlow", base_color=hex_to_linear("#FFF1D0"), roughness=0.25, emission=hex_to_linear("#FFD480"), emission_strength=1.2)
        bm_cedar = bmesh.new()
        bm_glow = bmesh.new()

        best_edge = None
        best_len = 0.0
        for i in range(n):
            pA = Vector((poly[i][0], poly[i][1], 0.0))
            pB = Vector((poly[(i + 1) % n][0], poly[(i + 1) % n][1], 0.0))
            ev = pB - pA
            t_dir = ev.normalized()
            out_n = Vector((t_dir.y, -t_dir.x, 0.0))
            if out_n.y < -0.5 and ev.length > best_len:
                best_len = ev.length
                best_edge = (pA, pB, t_dir, out_n, ev.length)
        if best_edge is not None:
            pA, pB, t_dir, out_n, eL = best_edge
            yaw = math.atan2(t_dir.y, t_dir.x)
            mid = pA.lerp(pB, 0.45)
            patio_w = min(18.5, eL * 0.52)
            patio_d = 5.4
            # Raised limestone cafe patio terrace (Z = 0.0..0.14m, kept clear east of doorway!)
            pc_pat = mid + out_n * (patio_d * 0.5)
            bm_add_box(bm_conc, (pc_pat.x, pc_pat.y, 0.07), (patio_w + 1.0, patio_d + 0.6, 0.14), rot_euler=(0, 0, yaw))
            # Steel pergola beams & 5 dark steel support posts (raised cleanly to 3.66m!)
            for k in range(5):
                frac = -0.46 + 0.92 * (k / 4.0)
                pp = mid + t_dir * (patio_w * frac) + out_n * (patio_d - 0.35)
                bm_add_prism_between(bm_dark, (pp.x, pp.y, 0.14), (pp.x, pp.y, 3.64), 0.11, 0.11, segs=8)
                ra_c = mid + t_dir * (patio_w * frac) + out_n * (patio_d * 0.5)
                bm_add_box(bm_dark, (ra_c.x, ra_c.y, 3.66), (0.14, patio_d, 0.18), rot_euler=(0, 0, yaw))
            pf_c = mid + out_n * (patio_d - 0.35)
            bm_add_box(bm_dark, (pf_c.x, pf_c.y, 3.68), (patio_w + 0.4, 0.22, 0.24), rot_euler=(0, 0, yaw))
            bm_add_box(bm_accent, (pf_c.x + out_n.x * 0.13, pf_c.y + out_n.y * 0.13, 3.70), (patio_w * 0.42, 0.06, 0.32), rot_euler=(0, 0, yaw))
            n_slats = 16
            for s in range(n_slats):
                sd = 0.45 + (patio_d - 0.95) * (s / float(n_slats - 1))
                sc = mid + out_n * sd
                bm_add_box(bm_cedar, (sc.x, sc.y, 3.80), (patio_w, 0.14, 0.08), rot_euler=(0, 0, yaw))
            # Outdoor Charlie's Café Microkitchen Espresso Service Bar
            bar_c = mid + out_n * 1.45
            bm_add_box(bm_cedar, (bar_c.x, bar_c.y, 0.62), (7.6, 1.05, 0.92), rot_euler=(0, 0, yaw), bevel=0.02)
            bm_add_box(bm_conc, (bar_c.x, bar_c.y, 1.12), (7.9, 1.25, 0.10), rot_euler=(0, 0, yaw), bevel=0.015)
            bm_add_box(bm_glow, (bar_c.x, bar_c.y, 3.54), (7.2, 0.30, 0.08), rot_euler=(0, 0, yaw))
            em_c = bar_c - t_dir * 1.8
            bm_add_box(bm_alum, (em_c.x, em_c.y, 1.44), (1.15, 0.62, 0.56), rot_euler=(0, 0, yaw), bevel=0.02)
            dc_c = bar_c + t_dir * 1.6
            bm_add_box(bm_glass_lo, (dc_c.x, dc_c.y, 1.42), (1.60, 0.68, 0.50), rot_euler=(0, 0, yaw))

        finalize_mesh(f"{prefix}_CharliesCedar", bm_cedar, mat_cedar, smooth=False, uv_scale=0.5)
        finalize_mesh(f"{prefix}_CafeLight", bm_glow, mat_warm_glow, smooth=False)

    # 7. Rooftop Tactical Cover: Angled Solar Panel Arrays + Detailed HVAC Units + Skylights
    hvac_candidates = [
        (0.0, 0.0),
        ((min_x + max_x) * 0.5 - 10.0, (min_y + max_y) * 0.5),
        ((min_x + max_x) * 0.5 + 11.0, (min_y + max_y) * 0.5),
    ]
    placed_hvacs = []
    for hx, hy in hvac_candidates:
        if point_in_poly_2d(hx, hy, poly) and min_dist_to_poly_edges(hx, hy, poly) > 4.2:
            bm_add_box(bm_alum, (hx, hy, roof_z + 0.72), (3.8, 2.5, 1.44), rot_euler=(0, 0, solar_yaw), bevel=0.04)
            bm_add_box(bm_dark, (hx, hy, roof_z + 0.74), (3.88, 1.9, 0.85), rot_euler=(0, 0, solar_yaw))
            for fo in (-0.95, 0.95):
                fx = hx + math.cos(solar_yaw) * fo
                fy = hy + math.sin(solar_yaw) * fo
                bm_add_prism_between(bm_dark, (fx, fy, roof_z + 1.44), (fx, fy, roof_z + 1.72), 0.52, 0.48, segs=12)
            placed_hvacs.append((hx, hy))

    step_u = 4.6 if solar_density >= 1.0 else 5.8
    step_v = 5.4 if solar_density >= 1.0 else 6.6
    pw, pd = 3.8, 2.1
    tilt = 0.30
    for ui in range(-12, 13):
        for vi in range(-12, 13):
            lx = ui * step_u
            ly = vi * step_v
            wx = lx * cy_cos - ly * cy_sin
            wy = lx * cy_sin + ly * cy_cos
            if not point_in_poly_2d(wx, wy, poly) or min_dist_to_poly_edges(wx, wy, poly) < 3.0:
                continue
            if any(math.hypot(wx - hx, wy - hy) < 4.5 for hx, hy in placed_hvacs):
                continue
            corners_ok = True
            for dx in (-pw * 0.5, pw * 0.5):
                for dy in (-pd * 0.5, pd * 0.5):
                    cx = wx + dx * cy_cos - dy * cy_sin
                    cy = wy + dx * cy_sin + dy * cy_cos
                    if not point_in_poly_2d(cx, cy, poly) or min_dist_to_poly_edges(cx, cy, poly) < 1.6:
                        corners_ok = False
                        break
                if not corners_ok:
                    break
            if not corners_ok:
                continue
            bm_add_box(bm_solar, (wx, wy, roof_z + 0.78), (pw, pd, 0.08), rot_euler=(tilt, 0.0, solar_yaw))
            for sx_o in (-pw * 0.36, pw * 0.36):
                for sy_o, leg_h in ((-pd * 0.34, 0.54), (pd * 0.34, 1.00)):
                    px = wx + sx_o * cy_cos - sy_o * cy_sin
                    py = wy + sx_o * cy_sin + sy_o * cy_cos
                    bm_add_prism_between(bm_dark, (px, py, roof_z), (px, py, roof_z + leg_h), 0.05, 0.05, segs=6)

    cx0 = sum(xs) / len(xs)
    cy0 = sum(ys) / len(ys)
    if point_in_poly_2d(cx0, cy0, poly) and min_dist_to_poly_edges(cx0, cy0, poly) > 5.0 and not any(math.hypot(cx0 - hx, cy0 - hy) < 4.0 for hx, hy in placed_hvacs):
        bm_add_box(bm_alum, (cx0, cy0, roof_z + 0.32), (6.4, 3.2, 0.64), rot_euler=(0, 0, solar_yaw))
        bm_add_box(bm_glass_up, (cx0, cy0, roof_z + 0.68), (6.0, 2.8, 0.14), rot_euler=(0, 0, solar_yaw))

    apply_face_unit_uv(bm_solar)
    finalize_mesh(f"{prefix}_Concrete", bm_conc, mat_conc, smooth=False, uv_scale=0.22)
    finalize_mesh(f"{prefix}_RoofDeck", bm_roof, mat_roof, smooth=False, uv_scale=0.18)
    finalize_mesh(f"{prefix}_OfficeFloorConc", bm_floor_conc, mat_floor_conc, smooth=False, uv_scale=0.22)
    finalize_mesh(f"{prefix}_OfficeFloorOak", bm_floor_oak, mat_floor_oak, smooth=False, uv_scale=0.35)
    finalize_mesh(f"{prefix}_InteriorDrywall", bm_int_wall, mat_int_wall, smooth=False, uv_scale=0.25)
    finalize_mesh(f"{prefix}_AcousticCeiling", bm_ceiling, mat_ceiling, smooth=False, uv_scale=0.20)
    finalize_mesh(f"{prefix}_OfficeLEDStrips", bm_led, mat_led, smooth=False)
    finalize_mesh(f"{prefix}_CurtainGlassUpper", bm_glass_up, mat_glass_upper, smooth=False, uv_scale=0.20)
    finalize_mesh(f"{prefix}_CurtainGlassLower", bm_glass_lo, mat_glass_lower, smooth=False, uv_scale=0.20)
    finalize_mesh(f"{prefix}_PartitionFrostGlass", bm_glass_frost, mat_glass_frost, smooth=False)
    finalize_mesh(f"{prefix}_PartitionCedar", bm_part_wood, mat_part_wood, smooth=False)
    finalize_mesh(f"{prefix}_AluminumMullions", bm_alum, mat_alum, smooth=False, uv_scale=0.5)
    finalize_mesh(f"{prefix}_DarkSteel", bm_dark, mat_dark_metal, smooth=False, uv_scale=0.5)
    finalize_mesh(f"{prefix}_WelcomeMats", bm_mat, mat_mat_charcoal, smooth=False)
    finalize_mesh(f"{prefix}_AccentTrim", bm_accent, mat_accent, smooth=False, uv_scale=0.5)
    finalize_mesh(f"{prefix}_SolarPanels", bm_solar, mat_solar, smooth=False, keep_existing_uv=True)

    # Print exact Three.js world doorway segments for 1:1 collider sync
    for e_idx, d0, d1, dw, p0w, p1w, mw, onw in doorway_log:
        print(
            f"  [DOOR {prefix}] edge[{e_idx}] s=[{d0:.2f},{d1:.2f}] (w={dw:.2f}m) | "
            f"ThreeJS ({p0w[0]:.2f},{p0w[1]:.2f})->({p1w[0]:.2f},{p1w[1]:.2f}) mid=({mw[0]:.2f},{mw[1]:.2f}) out=({onw[0]:+.2f},{onw[1]:+.2f})"
        )

    return export_asset(filename)


def build_b40_partnerplex():
    # SVG B40 polygon (sweeping WNW->ESE wing, ~88m x 34m)
    svg_poly = [(298, 278), (394, 268), (486, 294), (548, 322), (536, 356), (462, 366), (360, 348), (292, 326)]
    return build_quad_building(
        filename="landmark_b40_partnerplex.glb",
        prefix="B40",
        svg_poly=svg_poly,
        cx_svg=420.0,
        cy_svg=317.0,
        accent_hex="#C8372D",  # Googleplex Charlie's warm terracotta-red fascia accent
        solar_density=1.0,
        solar_yaw=-0.22,
        stair_edge_idx=2,      # SE courtyard-facing edge matching SVG stair marker (466, 366)
        stair_t=0.22,
        add_charlies_patio=True,
        doorways=[
            (0, 3.0, 9.2),     # 6.2m West Courtyard / Volleyball lobby (west of Skybridge)
            (1, 24.5, 31.7),   # 7.2m Charlie's Café Main Courtyard lobby facing Stan Plaza (clear east of outdoor espresso bar)
            (3, 3.1, 9.1),     # 6.0m East Partner Plex lobby facing Charleston Park
            (6, 13.2, 20.2),   # 7.0m North Amphitheatre Pkwy lobby
        ],
        interior_cols=[(-28.0, 4.0), (-11.0, 2.0), (5.0, -3.5), (21.0, -5.5)],
        interior_partitions=[(-18.5, 3.0, 4.6, 1.35), (13.0, -4.5, 4.6, 1.25)],
        world_offset=(-41.0, -21.0),
    )


def build_b41():
    # SVG B41 polygon (angled V-faceted NW Quad wing, ~37m x 36m)
    svg_poly = [(184, 264), (238, 242), (292, 272), (264, 336), (218, 348), (188, 308)]
    return build_quad_building(
        filename="landmark_b41.glb",
        prefix="B41",
        svg_poly=svg_poly,
        cx_svg=236.0,
        cy_svg=295.0,
        accent_hex="#2563EB",  # Crisp cobalt-blue SGI fascia accent
        solar_density=0.9,
        solar_yaw=0.18,
        stair_edge_idx=2,      # SE courtyard-facing edge matching SVG stair marker (268, 330)
        stair_t=0.15,
        add_entry_overhang_edge=1,
        overhang_t=0.5,
        doorways=[
            (1, 4.9, 11.5),    # 6.6m South Courtyard / Volleyball lobby under entry overhang
            (3, 7.4, 13.9),    # 6.5m NE Amphitheatre Pkwy / North Quad lobby
            (5, 4.6, 10.6),    # 6.0m West Permanente Creek Trail lobby
        ],
        interior_cols=[(-5.0, 4.0), (5.5, 2.5), (0.0, -7.0)],
        interior_partitions=[(-1.5, 6.5, 4.0, 0.20)],
        world_offset=(-112.0, -31.0),
    )


def build_b42():
    # SVG B42 polygon (multi-faceted SW Quad wing, ~31m x 40m)
    svg_poly = [(180, 398), (252, 394), (268, 452), (246, 512), (184, 510), (176, 456)]
    return build_quad_building(
        filename="landmark_b42.glb",
        prefix="B42",
        svg_poly=svg_poly,
        cx_svg=221.0,
        cy_svg=452.0,
        accent_hex="#0F766E",  # Googleplex deep teal architectural accent
        solar_density=0.75,
        solar_yaw=-0.10,
        stair_edge_idx=None,
        add_entry_overhang_edge=3,  # Courtyard-facing east overhang overlooking volleyball court!
        overhang_t=0.5,
        doorways=[
            (3, 6.9, 13.9),    # 7.0m East Volleyball Court / Courtyard lobby under entry overhang
            (1, 7.4, 13.9),    # 6.5m South Charleston Rd Blvd lobby
            (5, 7.0, 13.0),    # 6.0m West Permanente Creek Trail lobby
        ],
        interior_cols=[(-4.5, 7.0), (4.5, 6.0), (-1.5, -8.0)],
        interior_partitions=[(0.5, -1.0, 4.0, 1.50)],
        world_offset=(-117.0, 23.0),
    )


def build_b43():
    # SVG B43 polygon (staggered solar-roofed S/SE wing, ~83m x 31m)
    svg_poly = [(282, 444), (378, 434), (494, 458), (518, 522), (418, 524), (278, 504)]
    return build_quad_building(
        filename="landmark_b43.glb",
        prefix="B43",
        svg_poly=svg_poly,
        cx_svg=398.0,
        cy_svg=479.0,
        accent_hex="#D97706",  # Warm California amber-gold SGI fascia accent
        solar_density=1.15,    # Extensive signature B43 solar cover rows!
        solar_yaw=-0.16,
        stair_edge_idx=3,      # NE courtyard-facing edge matching SVG stair marker (498, 438)
        stair_t=0.12,
        add_entry_overhang_edge=4,
        overhang_t=22.0 / 33.28,  # Centered right over NW doorway (s=18.5..25.5), completely west of Skybridge!
        doorways=[
            (4, 18.5, 25.5),   # 7.0m NW Courtyard / Volleyball lobby under entry overhang (clear west of Skybridge)
            (3, 25.0, 32.0),   # 7.0m NE Courtyard lobby directly facing Stan the T-Rex (7.5m west of stair landing)
            (2, 8.5, 15.0),    # 6.5m East SE Parking / Charleston Park lobby
            (0, 21.0, 28.0),   # 7.0m South Charleston Rd Blvd lobby
        ],
        interior_cols=[(-24.0, 2.5), (-7.0, 1.0), (10.0, -2.5), (24.0, -4.5)],
        interior_partitions=[(-15.5, 1.5, 4.6, 1.45), (17.5, -3.5, 4.6, 1.35)],
        world_offset=(-58.0, 33.0),
    )


# ===========================================================================
# 6. LANDMARK: ELEVATED DIAGONAL GLASS SKYBRIDGE (+4.2m, 36m x 8m)
# ===========================================================================
def build_skybridge():
    reset_scene()

    tex_conc = gen_concrete_tex("Sky_ConcTex", 192, tint=(0.84, 0.82, 0.78), seed=401)
    mat_steel = make_pbr_mat("Sky_StructSteel", base_color=hex_to_linear("#CBD2DA"), metallic=0.84, roughness=0.28)
    mat_dark_steel = make_pbr_mat("Sky_DarkSteel", base_color=hex_to_linear("#3A4350"), metallic=0.82, roughness=0.36)
    mat_deck = make_pbr_mat("Sky_TerrazzoDeck", base_color=hex_to_linear("#D9D4C9"), roughness=0.72, tex_img=tex_conc, bump_strength=0.08)
    mat_roof = make_pbr_mat("Sky_RoofCanopy", base_color=hex_to_linear("#DCE4ED"), metallic=0.52, roughness=0.34)
    # Translucent sky-blue architectural glass so players can see cleanly through the skybridge!
    mat_glass = make_pbr_mat(
        "Sky_TintedGlass",
        base_color=hex_to_linear("#64B5F6", alpha=0.38),
        metallic=0.18,
        roughness=0.07,
        ior=1.52,
        alpha=0.38,
        specular=0.9,
        double_sided=True,
    )
    mat_accent = make_pbr_mat("Sky_GoogleBlueTrim", base_color=hex_to_linear("#4285F4"), metallic=0.3, roughness=0.35)

    bm_steel = bmesh.new()
    bm_dark = bmesh.new()
    bm_deck = bmesh.new()
    bm_roof = bmesh.new()
    bm_glass = bmesh.new()
    bm_accent = bmesh.new()

    # Exact diagonal orientation matching SVG polygon: (330,338)-(352,340) to (346,444)-(368,442)
    # Length = 36.2m, Width = 7.8m, angled ~8.6° WNW-SSE across courtyard
    length = 36.2
    width = 7.8
    half_l = length * 0.5
    half_w = width * 0.5
    deck_z = 4.20
    eave_z = 7.35
    ridge_z = 8.15
    yaw = math.radians(-8.6)  # Matches SVG diagonal tilt cleanly

    rot_m = Euler((0.0, 0.0, yaw), 'XYZ').to_matrix().to_4x4()

    def pt(x, y, z):
        return rot_m @ Vector((x, y, z))

    # 1. Walkable Bridge Deck & Structural Steel Box-Girder Underside (Z = 3.65..4.20m)
    bm_add_box(bm_deck, pt(0, 0, deck_z - 0.14), (width - 0.30, length, 0.28), rot_euler=(0, 0, yaw))
    # Twin longitudinal steel I-girders underneath deck
    for sx in (-half_w + 0.45, half_w - 0.45):
        bm_add_box(bm_dark, pt(sx, 0, deck_z - 0.42), (0.42, length, 0.48), rot_euler=(0, 0, yaw))
    # Subtle Google blue exterior fascia stripe along both deck edges
    for sx in (-half_w - 0.03, half_w + 0.03):
        bm_add_box(bm_accent, pt(sx, 0, deck_z - 0.18), (0.08, length, 0.22), rot_euler=(0, 0, yaw))

    # 2. Sculptural Tapered V-Pier Steel Supports near ends (±12.2m), leaving wide-open walkthrough underneath!
    for py in (-12.2, +12.2):
        for sgn in (-1.0, 1.0):
            # Grounded beveled concrete footing pad at Z = 0.0
            foot_x = sgn * (half_w - 0.85)
            bm_add_box(bm_deck, pt(foot_x, py, 0.18), (1.15, 1.35, 0.36), rot_euler=(0, 0, yaw), bevel=0.05)
            # Sculptural Y/V steel pier legs rising from footing to underside box-girder
            base = pt(foot_x, py, 0.32)
            top_a = pt(sgn * (half_w - 0.45), py - 1.55, deck_z - 0.42)
            top_b = pt(sgn * (half_w - 0.45), py + 1.55, deck_z - 0.42)
            bm_add_prism_between(bm_dark, base, top_a, 0.24, 0.18, segs=10)
            bm_add_prism_between(bm_dark, base, top_b, 0.24, 0.18, segs=10)
        # Cross tie beam right beneath deck between left & right piers
        bm_add_prism_between(bm_dark, pt(-half_w + 0.45, py, deck_z - 0.48), pt(half_w - 0.45, py, deck_z - 0.48), 0.18, 0.18, segs=8)

    # 3. Exposed Warren Structural Steel Trusses + Arched Roof Portal Ribs (10 bays along 36.2m)
    n_bays = 10
    bay_len = length / n_bays
    for bi in range(n_bays + 1):
        y = -half_l + bi * bay_len
        # Transverse floor beam
        bm_add_box(bm_dark, pt(0, y, deck_z - 0.38), (width - 0.6, 0.22, 0.30), rot_euler=(0, 0, yaw))
        # Vertical side portal columns
        for sgn in (-1.0, 1.0):
            x = sgn * (half_w - 0.16)
            bm_add_prism_between(bm_steel, pt(x, y, deck_z - 0.15), pt(x, y, eave_z), 0.11, 0.11, segs=8)
        # Curved overhead steel portal arch rib
        arch_pts = []
        for k in range(9):
            u = -1.0 + 2.0 * (k / 8.0)
            ax = u * (half_w - 0.10)
            az = eave_z + (ridge_z - eave_z) * (1.0 - u * u)
            arch_pts.append(pt(ax, y, az))
        bm_add_spline_tube(bm_steel, arch_pts, [0.10] * 9, segs=6)

        # Diagonal Warren truss braces & interior safety handrail on each bay
        if bi < n_bays:
            y_next = y + bay_len
            for sgn in (-1.0, 1.0):
                x = sgn * (half_w - 0.16)
                if bi % 2 == 0:
                    bm_add_prism_between(bm_steel, pt(x, y, deck_z + 0.05), pt(x, y_next, eave_z - 0.05), 0.07, 0.07, segs=6)
                else:
                    bm_add_prism_between(bm_steel, pt(x, y, eave_z - 0.05), pt(x, y_next, deck_z + 0.05), 0.07, 0.07, segs=6)

    # Continuous longitudinal top eave chords + low waist guardrails along both sides
    for sgn in (-1.0, 1.0):
        x = sgn * (half_w - 0.16)
        bm_add_prism_between(bm_steel, pt(x, -half_l, eave_z), pt(x, half_l, eave_z), 0.12, 0.12, segs=8)
        bm_add_prism_between(bm_steel, pt(x - sgn * 0.22, -half_l, deck_z + 1.05), pt(x - sgn * 0.22, half_l, deck_z + 1.05), 0.04, 0.04, segs=6)
        # Low solid safety kick-curb along deck edges
        bm_add_box(bm_dark, pt(x, 0, deck_z + 0.20), (0.18, length, 0.40), rot_euler=(0, 0, yaw))

    # 4. Translucent Tinted Curtain-Wall Glass Panels along both sides
    for sgn in (-1.0, 1.0):
        gx = sgn * (half_w - 0.06)
        bm_add_box(bm_glass, pt(gx, 0, (deck_z + 0.38 + eave_z) * 0.5), (0.05, length - 0.2, eave_z - deck_z - 0.40), rot_euler=(0, 0, yaw))

    # 5. Graceful Curved Barrel-Vaulted Roof Canopy (metallic edge panels + central glass skylight strip!)
    arch_strips = 8
    for s in range(arch_strips):
        u0 = -1.0 + 2.0 * (s / arch_strips)
        u1 = -1.0 + 2.0 * ((s + 1) / arch_strips)
        x0 = u0 * (half_w + 0.28)
        x1 = u1 * (half_w + 0.28)
        z0 = eave_z + (ridge_z - eave_z) * (1.0 - u0 * u0) + 0.08
        z1 = eave_z + (ridge_z - eave_z) * (1.0 - u1 * u1) + 0.08
        # Middle 2 strips = translucent glass skylight, outer 3 strips per side = standing-seam aluminum roof
        target_bm = bm_glass if (3 <= s <= 4) else bm_roof
        thick = 0.07 if target_bm is bm_glass else 0.12
        v00 = target_bm.verts.new(pt(x0, -half_l - 0.2, z0))
        v10 = target_bm.verts.new(pt(x1, -half_l - 0.2, z1))
        v11 = target_bm.verts.new(pt(x1,  half_l + 0.2, z1))
        v01 = target_bm.verts.new(pt(x0,  half_l + 0.2, z0))
        t00 = target_bm.verts.new(pt(x0, -half_l - 0.2, z0 + thick))
        t10 = target_bm.verts.new(pt(x1, -half_l - 0.2, z1 + thick))
        t11 = target_bm.verts.new(pt(x1,  half_l + 0.2, z1 + thick))
        t01 = target_bm.verts.new(pt(x0,  half_l + 0.2, z0 + thick))
        target_bm.faces.new((t00, t10, t11, t01))
        target_bm.faces.new((v01, v11, v10, v00))
        target_bm.faces.new((v00, v10, t10, t00))
        target_bm.faces.new((v11, v01, t01, t11))
        target_bm.faces.new((v01, v00, t00, t01))
        target_bm.faces.new((v10, v11, t11, t10))

    finalize_mesh("Skybridge_SteelTruss", bm_steel, mat_steel, smooth=True, uv_scale=0.5)
    finalize_mesh("Skybridge_DarkGirders", bm_dark, mat_dark_steel, smooth=False, uv_scale=0.4)
    finalize_mesh("Skybridge_Deck", bm_deck, mat_deck, smooth=False, uv_scale=0.3)
    finalize_mesh("Skybridge_RoofShell", bm_roof, mat_roof, smooth=True, uv_scale=0.3)
    finalize_mesh("Skybridge_GlassWalls", bm_glass, mat_glass, smooth=False, uv_scale=0.25)
    finalize_mesh("Skybridge_BlueTrim", bm_accent, mat_accent, smooth=False, uv_scale=0.5)

    return export_asset("landmark_skybridge.glb")


# ===========================================================================
# 7. LANDMARK: SAND VOLLEYBALL COURT (18m x 10m)
# ===========================================================================
def build_volleyball_court():
    reset_scene()

    tex_sand = gen_sand_tex("VBall_SandTex", 160, seed=501)
    tex_cedar = gen_cedar_wood_tex("VBall_TimberTex", 128, seed=502)
    tex_stone = gen_concrete_tex("VBall_CurbTex", 128, tint=(0.82, 0.79, 0.73), seed=503)

    mat_sand = make_pbr_mat("VBall_Sand", base_color=(1, 1, 1, 1), roughness=0.92, tex_img=tex_sand, bump_strength=0.18)
    mat_timber = make_pbr_mat("VBall_TimberBorder", base_color=hex_to_linear("#A66B3E"), roughness=0.72, tex_img=tex_cedar, bump_strength=0.14)
    mat_curb = make_pbr_mat("VBall_StoneCurb", base_color=hex_to_linear("#CFC7B8"), roughness=0.80, tex_img=tex_stone, bump_strength=0.12)
    mat_line = make_pbr_mat("VBall_CourtLine", base_color=hex_to_linear("#1E40AF"), roughness=0.70)
    mat_white = make_pbr_mat("VBall_NetWhite", base_color=hex_to_linear("#F8FAFC"), roughness=0.68)
    mat_alum = make_pbr_mat("VBall_AlumPost", base_color=hex_to_linear("#D1D5DB"), metallic=0.88, roughness=0.22)
    mat_pad = make_pbr_mat("VBall_PostPad", base_color=hex_to_linear("#4285F4"), roughness=0.55)
    mat_red = make_pbr_mat("VBall_AntennaRed", base_color=hex_to_linear("#EA4335"), roughness=0.45)
    mat_yellow = make_pbr_mat("VBall_BallYellow", base_color=hex_to_linear("#FBBC04"), roughness=0.55)

    L, W = 18.0, 10.0  # Exact §10.2 footprint
    curb_w = 0.36
    curb_h = 0.24

    # 1. Outer Stone & Cedar Timber Border Curbing (18m x 10m, Z = 0.0..0.24m)
    bm_curb = bmesh.new()
    bm_timber = bmesh.new()
    # Long North/South curbs
    for sgn in (-1.0, 1.0):
        y = sgn * (W * 0.5 - curb_w * 0.5)
        bm_add_box(bm_curb, (0.0, y, curb_h * 0.42), (L, curb_w, curb_h * 0.84), bevel=0.02)
        bm_add_box(bm_timber, (0.0, y, curb_h - 0.03), (L - 0.04, curb_w * 0.82, 0.07), bevel=0.012)
    # Short East/West curbs
    for sgn in (-1.0, 1.0):
        x = sgn * (L * 0.5 - curb_w * 0.5)
        bm_add_box(bm_curb, (x, 0.0, curb_h * 0.42), (curb_w, W - curb_w * 2, curb_h * 0.84), bevel=0.02)
        bm_add_box(bm_timber, (x, 0.0, curb_h - 0.03), (curb_w * 0.82, W - curb_w * 2 + 0.04, 0.07), bevel=0.012)

    # 2. Gently Rippled Tan Sand Bed filling the pit (Z = 0.0 bottom to ~0.15m top)
    bm_sand = bmesh.new()
    sx_n, sy_n = 18, 10
    inner_l = L - curb_w * 2 + 0.06
    inner_w = W - curb_w * 2 + 0.06
    grid = []
    for ix in range(sx_n + 1):
        row = []
        u = ix / float(sx_n)
        x = -inner_l * 0.5 + u * inner_l
        for iy in range(sy_n + 1):
            v = iy / float(sy_n)
            y = -inner_w * 0.5 + v * inner_w
            # Gentle beach sand footprints / wind undulations (0.125..0.165m)
            edge_fade = math.sin(u * math.pi) * math.sin(v * math.pi)
            ripple = 0.022 * math.sin(x * 0.85 + y * 0.65) * edge_fade
            row.append(bm_sand.verts.new((x, y, 0.145 + ripple)))
        grid.append(row)
    for ix in range(sx_n):
        for iy in range(sy_n):
            bm_sand.faces.new((grid[ix][iy], grid[ix + 1][iy], grid[ix + 1][iy + 1], grid[ix][iy + 1]))
    # Grounded base slab beneath sand
    bm_add_box(bm_sand, (0.0, 0.0, 0.06), (inner_l, inner_w, 0.12))

    # 3. Crisp Court Boundary Lines (15.6m x 7.8m FIVB proportions)
    bm_line = bmesh.new()
    cl_l, cl_w = 15.2, 7.6
    lw = 0.08
    lz = 0.172
    for sgn in (-1.0, 1.0):
        bm_add_box(bm_line, (0.0, sgn * cl_w * 0.5, lz), (cl_l + lw, lw, 0.016))
        bm_add_box(bm_line, (sgn * cl_l * 0.5, 0.0, lz), (lw, cl_w - lw, 0.016))
    # Subtle center line under net
    bm_add_box(bm_line, (0.0, 0.0, lz), (0.05, cl_w, 0.012))

    # 4. Brushed-Aluminum Net Posts, Protective Blue Padding, Winch & Tension Cables
    bm_alum = bmesh.new()
    bm_pad = bmesh.new()
    post_y = 4.45
    post_h = 2.55
    for sgn in (-1.0, 1.0):
        py = sgn * post_y
        # Sleeve footing
        bm_add_prism_between(bm_alum, (0.0, py, 0.0), (0.0, py, 0.18), 0.10, 0.09, segs=12)
        # Main aluminum pole
        bm_add_prism_between(bm_alum, (0.0, py, 0.16), (0.0, py, post_h), 0.052, 0.050, segs=12)
        # Top cap & pulley wheel
        bm_add_sphere(bm_alum, (0.0, py, post_h + 0.02), 0.056)
        # Google Blue safety foam pad sleeve around mid-post
        bm_add_prism_between(bm_pad, (0.0, py, 0.25), (0.0, py, 2.02), 0.085, 0.085, segs=12)
        # Hand winch reel on +Y post
        if sgn > 0:
            bm_add_box(bm_alum, (0.0, py + 0.12, 1.32), (0.12, 0.14, 0.18), bevel=0.015)

    # 5. Crisp White Mesh Volleyball Net (Z = 1.43m..2.43m, span 8.75m) + Red/White Antennas
    bm_net = bmesh.new()
    bm_red = bmesh.new()
    net_z0, net_z1 = 1.43, 2.43
    net_half_y = 4.28
    # Top & Bottom canvas tension tape bands
    bm_add_box(bm_net, (0.0, 0.0, net_z1 - 0.035), (0.028, net_half_y * 2, 0.075))
    bm_add_box(bm_net, (0.0, 0.0, net_z0 + 0.025), (0.024, net_half_y * 2, 0.055))
    # Side vertical canvas bands
    for sgn in (-1.0, 1.0):
        bm_add_box(bm_net, (0.0, sgn * (net_half_y - 0.025), (net_z0 + net_z1) * 0.5), (0.026, 0.055, net_z1 - net_z0))
        # Tension cables from net corners to aluminum posts
        for tz in (net_z0 + 0.03, net_z1 - 0.03):
            bm_add_prism_between(bm_alum, (0.0, sgn * net_half_y, tz), (0.0, sgn * post_y, tz), 0.009, 0.009, segs=6)

    # Crisp 3D geometric white mesh strands (horizontal + vertical cords — zero alpha glitches!)
    n_horiz = 6
    for i in range(1, n_horiz):
        z = net_z0 + (net_z1 - net_z0) * (i / float(n_horiz))
        bm_add_box(bm_net, (0.0, 0.0, z), (0.012, net_half_y * 2 - 0.06, 0.012))
    n_vert = 34
    for j in range(1, n_vert):
        y = -net_half_y + (2.0 * net_half_y) * (j / float(n_vert))
        bm_add_box(bm_net, (0.0, y, (net_z0 + net_z1) * 0.5), (0.012, 0.012, net_z1 - net_z0 - 0.06))

    # Official Red-and-White striped fiberglass sideline antennas above net
    for sgn in (-1.0, 1.0):
        ay = sgn * (cl_w * 0.5)
        for seg in range(8):
            az0 = net_z1 - 0.15 + seg * 0.12
            az1 = az0 + 0.12
            target = bm_red if (seg % 2 == 0) else bm_net
            bm_add_prism_between(target, (0.0, ay, az0), (0.0, ay, az1), 0.012, 0.012, segs=6)

    # 6. Bonus Googleplex Detail: Beach Volleyball resting on the sand!
    bm_ball_w = bmesh.new()
    bm_ball_y = bmesh.new()
    bx, by, bz = 2.6, 2.2, 0.265
    bm_add_sphere(bm_ball_w, (bx, by, bz), 0.115, u_segs=14, v_segs=10)
    # Yellow & blue equatorial seam bands
    bm_add_torus(bm_ball_y, (bx, by, bz), 0.113, 0.012, rot_euler=(0.5, 0.3, 0.0), major_segs=16, minor_segs=6)
    bm_add_torus(bm_pad, (bx, by, bz), 0.113, 0.012, rot_euler=(-0.4, 1.2, 0.6), major_segs=16, minor_segs=6)

    finalize_mesh("VBall_SandBed", bm_sand, mat_sand, smooth=True, uv_scale=0.35)
    finalize_mesh("VBall_StoneCurb", bm_curb, mat_curb, smooth=False, uv_scale=0.45)
    finalize_mesh("VBall_TimberCoping", bm_timber, mat_timber, smooth=False, uv_scale=0.45)
    finalize_mesh("VBall_CourtLines", bm_line, mat_line, smooth=False)
    finalize_mesh("VBall_AlumPosts", bm_alum, mat_alum, smooth=True)
    finalize_mesh("VBall_PostPads", bm_pad, mat_pad, smooth=True)
    finalize_mesh("VBall_WhiteNet", bm_net, mat_white, smooth=False)
    finalize_mesh("VBall_AntennasRed", bm_red, mat_red, smooth=True)
    finalize_mesh("VBall_BallBase", bm_ball_w, mat_white, smooth=True)
    finalize_mesh("VBall_BallStripe", bm_ball_y, mat_yellow, smooth=True)

    return export_asset("landmark_volleyball_court.glb")


# ===========================================================================
# 8. LANDMARK: GRADIENT CANOPY / GOOGLE VISITOR EXPERIENCE (90m x 94m, +10.5m)
# ===========================================================================
def build_gradient_canopy():
    reset_scene()

    tex_dragon = gen_dragonscale_tex("GC_DragonTex", 160, seed=601)
    tex_stone = gen_stone_paver_tex("GC_PaverTex", 128, seed=602)
    tex_cedar = gen_cedar_wood_tex("GC_CedarTex", 128, seed=603)
    tex_glass = gen_curtain_glass_tex("GC_GlassTex", 128, seed=604)

    mat_canopy = make_pbr_mat("GC_DragonscaleRoof", base_color=hex_to_linear("#F2F5F9"), metallic=0.22, roughness=0.34, tex_img=tex_dragon, bump_strength=0.10)
    mat_skylight = make_pbr_mat("GC_SkylightGlass", base_color=hex_to_linear("#1E3A5F"), metallic=0.42, roughness=0.08, ior=1.52, tex_img=tex_glass)
    mat_soffit = make_pbr_mat("GC_CedarSoffit", base_color=hex_to_linear("#C48A5A"), roughness=0.66, tex_img=tex_cedar, bump_strength=0.10)
    mat_column = make_pbr_mat("GC_WhiteSteel", base_color=hex_to_linear("#E4E8EE"), metallic=0.45, roughness=0.30)
    mat_dark_steel = make_pbr_mat("GC_DarkSteel", base_color=hex_to_linear("#2E3744"), metallic=0.80, roughness=0.34)
    mat_podium = make_pbr_mat("GC_LimestonePodium", base_color=hex_to_linear("#DDD7CB"), roughness=0.78, tex_img=tex_stone, bump_strength=0.12)
    mat_atrium_glass = make_pbr_mat(
        "GC_AtriumGlass",
        base_color=hex_to_linear("#7AC5F8", alpha=0.34),
        metallic=0.20,
        roughness=0.06,
        ior=1.52,
        alpha=0.34,
        double_sided=True,
    )
    mat_marble = make_pbr_mat("GC_MarbleCounter", base_color=hex_to_linear("#F5F4F0"), roughness=0.24, specular=0.65)
    mat_huddle_accent = make_pbr_mat("GC_HuddleAccent", base_color=hex_to_linear("#4285F4"), roughness=0.42, metallic=0.18)
    mat_warm_light = make_pbr_mat("GC_WarmLighting", base_color=hex_to_linear("#FFF3D6"), roughness=0.3, emission=hex_to_linear("#FFD78A"), emission_strength=1.5)
    mat_planter_green = make_pbr_mat("GC_AtriumPlants", base_color=hex_to_linear("#2D6A36"), roughness=0.78)

    bm_canopy = bmesh.new()
    bm_sky = bmesh.new()
    bm_soffit = bmesh.new()
    bm_cols = bmesh.new()
    bm_dark = bmesh.new()
    bm_podium = bmesh.new()
    bm_glass = bmesh.new()
    bm_marble = bmesh.new()
    bm_accent = bmesh.new()
    bm_light = bmesh.new()
    bm_plants = bmesh.new()

    rx_outer, ry_outer = 44.5, 46.5  # Exact ~90m x 94m rounded-square footprint!

    def make_rounded_sq(rx, ry, p=3.2, segs=40):
        pts = []
        for i in range(segs):
            a = 2.0 * math.pi * i / segs
            ca, sa = math.cos(a), math.sin(a)
            x = math.copysign(abs(ca) ** (2.0 / p), ca) * rx
            y = math.copysign(abs(sa) ** (2.0 / p), sa) * ry
            pts.append((x, y))
        return pts

    def canopy_height(x, y):
        """
        Authentic sweeping pillowed BIG/Heatherwick Gradient Canopy heightfield:
        Eaves billowing gracefully at ~5.8m..6.5m sweeping up into sculpted dragonscale vaults (~10.5m).
        """
        nx = x / rx_outer
        ny = y / ry_outer
        r_sq = (abs(nx) ** 2.6 + abs(ny) ** 2.6)
        dome = max(0.0, 1.0 - 0.78 * r_sq)
        undul = 0.75 * math.cos(nx * math.pi * 1.15) * math.cos(ny * math.pi * 1.15)
        # Gentle perimeter arch scalloping along the outer colonnade eaves
        ang = math.atan2(ny, nx)
        eave_wave = 0.42 * (min(1.0, r_sq) ** 2) * math.cos(ang * 12.0)
        return 5.95 + 3.65 * dome + 0.55 * max(0.0, undul) + eave_wave

    # 1. Stepped Grounded Travertine Podium Platform (Z = 0.0..0.40m, matching §10.2 Ground +0.4m)
    bm_add_polygon_prism(bm_podium, make_rounded_sq(42.5, 44.5, p=3.2, segs=40), 0.0, 0.20)
    bm_add_polygon_prism(bm_podium, make_rounded_sq(40.5, 42.5, p=3.2, segs=40), 0.20, 0.40)

    # 2. Iconic Sweeping White Diamond-Quilted Dragonscale Canopy Shell!
    # Dramatic overlapping 3D pillowed diamond scales with recessed north-facing clerestory skylight hoods
    # and crisp metallic architectural seam ribs between scales so the dragonscale silhouette reads unmistakably!
    scale_step = 11.4
    s45 = math.sqrt(0.5)
    for gi in range(-6, 7):
        for gj in range(-6, 7):
            cx = (gi - gj) * scale_step * s45
            cy = (gi + gj) * scale_step * s45
            env = (abs(cx) / (rx_outer + 1.5)) ** 3.2 + (abs(cy) / (ry_outer + 1.5)) ** 3.2
            if env > 1.04:
                continue

            half_d = scale_step * 0.70
            raw_corners = [
                (cx, cy + half_d),   # North peak (lifted high for unmistakable dragonscale skylight scoop!)
                (cx + half_d, cy),   # East
                (cx, cy - half_d),   # South tucked overlap edge
                (cx - half_d, cy),   # West
            ]
            pts_top = []
            pts_bot = []
            for k, (px, py) in enumerate(raw_corners):
                ev = (abs(px) / rx_outer) ** 3.2 + (abs(py) / ry_outer) ** 3.2
                if ev > 1.0:
                    sc = ev ** (-1.0 / 3.2)
                    px *= sc
                    py *= sc
                base_z = canopy_height(px, py)
                # Bold architectural shingle scoop: +1.18m north skylight hood, -0.30m south tucked edge
                lift = 1.18 if k == 0 else (-0.30 if k == 2 else 0.14)
                z_top = base_z + lift
                z_bot = z_top - 0.34
                pts_top.append((px, py, z_top))
                pts_bot.append((px, py, z_bot))

            # Center crown vertex gracefully arched upward into tent-like dragonscale pillow
            cz_base = canopy_height(cx, cy) + 0.68
            v_ct = bm_canopy.verts.new((cx, cy, cz_base))
            v_cb = bm_soffit.verts.new((cx, cy, cz_base - 0.36))

            vt = [bm_canopy.verts.new(p) for p in pts_top]
            vb = [bm_canopy.verts.new(p) for p in pts_bot]
            vs_b = [bm_soffit.verts.new(p) for p in pts_bot]

            for k in range(4):
                nk = (k + 1) % 4
                bm_canopy.faces.new((vt[k], vt[nk], v_ct))
                bm_canopy.faces.new((vb[k], vb[nk], vt[nk], vt[k]))
                bm_soffit.faces.new((vs_b[nk], vs_b[k], v_cb))
                # Crisp dark-steel architectural diamond seam rib highlighting every dragonscale contour!
                bm_add_prism_between(bm_dark, pts_top[k], pts_top[nk], 0.11, 0.11, segs=4)

            # Deep North-Facing Clerestory Skylight Glazing Hood beneath each lifted dragonscale edge!
            # Clamped cleanly above local canopy eave height so skylights never hang below perimeter fascia.
            for edge_a, edge_b in ((0, 1), (3, 0)):
                pa = pts_bot[edge_a]
                pb = pts_bot[edge_b]
                za_low = max(canopy_height(pa[0], pa[1]) - 0.22, pa[2] - 1.05)
                zb_low = max(canopy_height(pb[0], pb[1]) - 0.22, pb[2] - 1.05)
                if pa[2] - za_low < 0.08 and pb[2] - zb_low < 0.08:
                    continue
                ga0 = bm_sky.verts.new((pa[0], pa[1], pa[2]))
                gb0 = bm_sky.verts.new((pb[0], pb[1], pb[2]))
                gb1 = bm_sky.verts.new((pb[0], pb[1], zb_low))
                ga1 = bm_sky.verts.new((pa[0], pa[1], za_low))
                bm_sky.faces.new((ga0, gb0, gb1, ga1))

    # Perimeter crisp sculpted white metallic eave fascia ring wrapping the whole 90m x 94m canopy
    eave_ring = make_rounded_sq(rx_outer, ry_outer, p=3.2, segs=48)
    eave_pts_3d = [(x, y, canopy_height(x, y) - 0.12) for x, y in eave_ring]
    eave_pts_3d.append(eave_pts_3d[0])
    bm_add_spline_tube(bm_canopy, eave_pts_3d, [0.40] * len(eave_pts_3d), segs=8, cap_ends=False)

    # 3. Slender Tapered Steel Perimeter Colonnades & Iconic Tree-Like Interior V-Columns
    col_ring = make_rounded_sq(39.2, 41.2, p=3.2, segs=28)
    for px, py in col_ring:
        top_z = canopy_height(px, py) - 0.35
        # Slender tapered steel column
        bm_add_prism_between(bm_cols, (px, py, 0.38), (px, py, top_z), 0.24, 0.16, segs=10)
        # Base collar
        bm_add_prism_between(bm_dark, (px, py, 0.38), (px, py, 0.62), 0.34, 0.28, segs=10)
        # Sculptural V-strut fork bracing top into roof soffit
        rad_dir = Vector((px, py, 0.0)).normalized()
        tan_dir = Vector((-rad_dir.y, rad_dir.x, 0.0))
        fork_p = Vector((px, py, top_z - 1.65))
        for sgn in (-1.0, 1.0):
            tip = Vector((px, py, top_z)) + tan_dir * (sgn * 1.45)
            bm_add_prism_between(bm_cols, fork_p, tip, 0.12, 0.10, segs=8)

    # 8 Dramatic Interior Tree-Columns supporting the central vaulted atrium span
    interior_cols = [
        (-16.0, -16.0), (0.0, -18.0), (16.0, -16.0),
        (-18.0, 0.0),                 (18.0, 0.0),
        (-16.0, 16.0),  (0.0, 18.0),  (16.0, 16.0),
    ]
    for cx, cy in interior_cols:
        tz = canopy_height(cx, cy) - 0.35
        bm_add_prism_between(bm_cols, (cx, cy, 0.38), (cx, cy, tz - 2.6), 0.34, 0.26, segs=12)
        # 4 spreading diagonal steel canopy branches per tree-column
        for ang in (0.78, 2.35, 3.92, 5.49):
            tip = Vector((cx + math.cos(ang) * 3.4, cy + math.sin(ang) * 3.4, tz))
            bm_add_prism_between(bm_cols, (cx, cy, tz - 2.7), tip, 0.14, 0.11, segs=8)

    # 4. Sunlit Glass Atrium Enclosure Walls (~72m x 76m) with 4 Wide Open Walkthrough Portals!
    atrium_ring = make_rounded_sq(34.5, 36.5, p=3.2, segs=36)
    na = len(atrium_ring)
    for i in range(na):
        pA = Vector((atrium_ring[i][0], atrium_ring[i][1], 0.0))
        pB = Vector((atrium_ring[(i + 1) % na][0], atrium_ring[(i + 1) % na][1], 0.0))
        mid = (pA + pB) * 0.5
        # Leave 4 generous ~13m wide open entrance portals on West (-X), East (+X), North (+Y), South (-Y)
        if abs(mid.x) < 6.8 or abs(mid.y) < 6.8:
            # Portal framing header beam only (high clearance Z = 5.4m)
            ev = pB - pA
            yaw = math.atan2(ev.y, ev.x)
            bm_add_box(bm_dark, (mid.x, mid.y, 5.45), (ev.length, 0.28, 0.36), rot_euler=(0, 0, yaw))
            continue

        ev = pB - pA
        L = ev.length
        yaw = math.atan2(ev.y, ev.x)
        top_z = canopy_height(mid.x, mid.y) - 0.45
        # Translucent full-height atrium curtain glass
        bm_add_box(bm_glass, (mid.x, mid.y, (0.40 + top_z) * 0.5), (L, 0.08, top_z - 0.40), rot_euler=(0, 0, yaw))
        # Dark aluminum vertical curtain mullions & horizontal transoms
        bm_add_box(bm_dark, (pA.x, pA.y, (0.40 + top_z) * 0.5), (0.16, 0.24, top_z - 0.40), rot_euler=(0, 0, yaw))
        bm_add_box(bm_dark, (mid.x, mid.y, 3.85), (L, 0.20, 0.14), rot_euler=(0, 0, yaw))
        bm_add_box(bm_dark, (mid.x, mid.y, 0.50), (L, 0.24, 0.20), rot_euler=(0, 0, yaw))

    # 5. Enriched Google Visitor Experience & Huddle Café Interior!
    tex_showcase = gen_workspace_showcase_tex("GC_WorkspaceShowcaseTex", w=192, h=128)
    mat_showcase = make_pbr_mat(
        "GC_WorkspaceShowcase",
        base_color=(1, 1, 1, 1),
        roughness=0.14,
        tex_img=tex_showcase,
        emission_tex=True,
        emission_strength=1.10,
    )
    mat_chrome = make_pbr_mat("GC_ChromeSteel", base_color=hex_to_linear("#DCE4EE"), metallic=0.90, roughness=0.16)
    mat_g_cush = [
        make_pbr_mat("GC_CushionBlue", base_color=hex_to_linear("#4285F4"), roughness=0.84),
        make_pbr_mat("GC_CushionRed", base_color=hex_to_linear("#EA4335"), roughness=0.84),
        make_pbr_mat("GC_CushionYellow", base_color=hex_to_linear("#FBBC04"), roughness=0.84),
        make_pbr_mat("GC_CushionGreen", base_color=hex_to_linear("#34A853"), roughness=0.84),
    ]
    bm_showcase = bmesh.new()
    bm_chrome = bmesh.new()
    bm_cush = [bmesh.new() for _ in range(4)]

    def add_showcase_quad(bm, center_v, width, height, yaw_rad, offset_out=0.0):
        """Add a UV-mapped showcase screen quad facing +out_n = (sin(yaw), -cos(yaw)) or local +Y rotated."""
        uv_l = bm.loops.layers.uv.verify()
        rot_m = Euler((0.0, 0.0, yaw_rad), 'XYZ').to_matrix()
        hw, hh = width * 0.5, height * 0.5
        # Local X = along wall width, Local Y = outward normal
        pts = [
            center_v + rot_m @ Vector((-hw, offset_out, -hh)),
            center_v + rot_m @ Vector(( hw, offset_out, -hh)),
            center_v + rot_m @ Vector(( hw, offset_out,  hh)),
            center_v + rot_m @ Vector((-hw, offset_out,  hh)),
        ]
        f = bm.faces.new([bm.verts.new(p) for p in pts])
        for lp, uv in zip(f.loops, ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))):
            lp[uv_l].uv = uv

    # 5A. Enriched Huddle Café L-Counter (SW atrium quadrant, Blender (-5.5, -10.5))
    hx, hy = -5.5, -10.5
    bm_add_box(bm_soffit, (hx, hy, 0.92), (11.5, 2.2, 1.04), bevel=0.04)
    bm_add_box(bm_marble, (hx, hy, 1.48), (12.0, 2.55, 0.12), bevel=0.02)
    # Vertical fluted cedar accent slats along Huddle front counter apron
    for k in range(28):
        sx = (hx - 5.4) + 10.8 * (k / 27.0)
        bm_add_box(bm_soffit, (sx, hy - 1.12, 0.92), (0.12, 0.06, 0.96))
    # Return wing of Huddle bar
    bm_add_box(bm_soffit, (hx - 5.2, hy + 3.8, 0.92), (2.2, 6.2, 1.04), bevel=0.04)
    bm_add_box(bm_marble, (hx - 5.2, hy + 3.8, 1.48), (2.55, 6.6, 0.12), bevel=0.02)
    # Floating Huddle Café suspended wooden canopy soffit, halo light & suspended glowing menu boards (Z = 3.2..4.15m)
    bm_add_box(bm_soffit, (hx - 1.2, hy + 1.5, 4.15), (14.5, 9.2, 0.28), bevel=0.04)
    bm_add_box(bm_light, (hx - 1.2, hy + 1.5, 3.98), (12.2, 7.0, 0.08))
    bm_add_box(bm_accent, (hx - 1.2, hy - 3.12, 4.15), (7.5, 0.08, 0.34))
    # Suspended twin double-sided illuminated Huddle Café menu boards + 4 warm dome pendant lamps
    for mx_o in (-2.4, 2.0):
        bm_add_box(bm_dark, (hx + mx_o, hy + 0.1, 3.35), (3.2, 0.10, 0.82))
        bm_add_box(bm_light, (hx + mx_o, hy + 0.1, 3.35), (2.95, 0.14, 0.64))
        for ro in (-1.2, 1.2):
            bm_add_prism_between(bm_dark, (hx + mx_o + ro, hy + 0.1, 3.76), (hx + mx_o + ro, hy + 0.1, 4.02), 0.02, 0.02, segs=5)
    for px_l in (-4.2, -1.6, 1.0, 3.6):
        bm_add_prism_between(bm_dark, (hx + px_l, hy - 0.85, 3.05), (hx + px_l, hy - 0.85, 4.00), 0.015, 0.015, segs=5)
        bm_add_prism_between(bm_chrome, (hx + px_l, hy - 0.85, 2.86), (hx + px_l, hy - 0.85, 3.08), 0.22, 0.06, segs=10)
        bm_add_sphere(bm_light, (hx + px_l, hy - 0.85, 2.87), 0.08, u_segs=8, v_segs=6)
    # Support steel posts for Huddle pavilion
    for px_o, py_o in ((-7.8, -2.5), (5.4, -2.5), (-7.8, 5.5), (5.4, 5.5)):
        bm_add_prism_between(bm_dark, (hx + px_o, hy + py_o, 0.40), (hx + px_o, hy + py_o, 4.10), 0.11, 0.11, segs=8)
    # Detailed Commercial Chrome Espresso Bar, Burr Grinder & Glowing Pastry Display Case
    bm_add_box(bm_chrome, (hx - 2.2, hy, 1.82), (1.85, 0.82, 0.58), bevel=0.02)
    bm_add_box(bm_dark, (hx - 3.6, hy, 1.76), (0.45, 0.50, 0.46))
    bm_add_box(bm_glass, (hx + 2.4, hy, 1.80), (2.4, 0.95, 0.54))
    bm_add_box(bm_light, (hx + 2.4, hy, 1.56), (2.2, 0.78, 0.04))
    # 5 Modern Bar Stools lined neatly along Huddle Café outer south edge (Z = 0.40..1.14m)
    for si in range(5):
        sx = (hx - 3.8) + si * 1.9
        sy = hy - 1.85
        bm_add_prism_between(bm_dark, (sx, sy, 0.40), (sx, sy, 1.08), 0.032, 0.028, segs=8)
        bm_add_prism_between(bm_dark, (sx, sy, 0.40), (sx, sy, 0.45), 0.24, 0.22, segs=10)
        bm_add_prism_between(bm_soffit, (sx, sy, 1.08), (sx, sy, 1.14), 0.21, 0.20, segs=10)

    # 5B. Upgraded Visitor Experience Exhibition Kiosk Pods (glowing Google Workspace showcase screens!)
    pods = [
        (10.5, 9.5, 0.25),
        (-11.0, 11.5, -0.35),
        (12.5, -7.5, 0.45),
    ]
    for px, py, rot in pods:
        bm_add_box(bm_podium, (px, py, 0.72), (6.4, 2.4, 0.64), rot_euler=(0, 0, rot), bevel=0.08)
        bm_add_box(bm_soffit, (px, py, 1.08), (6.6, 2.5, 0.10), rot_euler=(0, 0, rot), bevel=0.02)
        bm_add_box(bm_dark, (px, py, 1.95), (3.4, 0.26, 1.70), rot_euler=(0, 0, rot), bevel=0.03)
        # Double-sided glowing Google Workspace Showcase graphic screens
        add_showcase_quad(bm_showcase, Vector((px, py, 2.02)), 3.12, 1.38, rot, offset_out=0.145)
        add_showcase_quad(bm_showcase, Vector((px, py, 2.02)), 3.12, 1.38, rot + math.pi, offset_out=0.145)
        bm_add_organic_cluster(bm_plants, (px + 2.3 * math.cos(rot), py + 2.3 * math.sin(rot), 1.48), 0.85, 0.85, 0.65, subdiv=1, seed=int(abs(px * 10)), crinkle=0.25)

    # 5C. Warm Wood-Slat Acoustic Pavilions (NW & NE open-entry architectural timber rib pavilions!)
    pavilions = [
        (-22.5, 21.5, -0.78, False),  # NW Acoustic Lounge Pavilion (faces SE toward center)
        ( 22.5, 21.5,  0.78, True),   # NE Google Workspace Showcase Pavilion (faces SW toward center)
    ]
    for pav_x, pav_y, pav_yaw, has_showcase_wall in pavilions:
        pmat = Matrix.Translation((pav_x, pav_y, 0.0)) @ Euler((0.0, 0.0, pav_yaw), 'XYZ').to_matrix().to_4x4()
        pav_w, pav_d, pav_h = 8.4, 5.4, 4.30
        # Raised warm timber deck pad (Z = 0.40..0.52m)
        bm_add_box(bm_soffit, pmat @ Vector((0.0, 0.0, 0.46)), (pav_w, pav_d, 0.12), rot_euler=(0, 0, pav_yaw))
        # 11 Arched Warm Wood-Slat Acoustic Portal Ribs curving from back wall overhead!
        for r_i in range(11):
            rx = -pav_w * 0.46 + (pav_w * 0.92) * (r_i / 10.0)
            # Back vertical slat leg (along +Y local back) + overhead cantilevered acoustic slat rib
            bm_add_box(bm_soffit, pmat @ Vector((rx, pav_d * 0.45, 0.52 + (pav_h - 0.52) * 0.5)), (0.14, 0.24, pav_h - 0.52), rot_euler=(0, 0, pav_yaw))
            bm_add_box(bm_soffit, pmat @ Vector((rx, 0.0, pav_h)), (0.14, pav_d, 0.22), rot_euler=(0, 0, pav_yaw))
        # Steel front corner portal posts & warm overhead linear halo strip
        for sx in (-pav_w * 0.46, pav_w * 0.46):
            bm_add_prism_between(bm_dark, pmat @ Vector((sx, -pav_d * 0.44, 0.52)), pmat @ Vector((sx, -pav_d * 0.44, pav_h)), 0.09, 0.09, segs=8)
        bm_add_box(bm_light, pmat @ Vector((0.0, 0.0, pav_h - 0.16)), (pav_w * 0.76, 0.36, 0.08), rot_euler=(0, 0, pav_yaw))
        if has_showcase_wall:
            # Hero Glowing Google Workspace Showcase Wall inside NE Pavilion (facing -Y toward atrium center!)
            bm_add_box(bm_dark, pmat @ Vector((0.0, pav_d * 0.32, 1.95)), (5.6, 0.28, 2.75), rot_euler=(0, 0, pav_yaw))
            add_showcase_quad(bm_showcase, pmat @ Vector((0.0, pav_d * 0.32, 2.02)), 5.2, 2.35, pav_yaw + math.pi, offset_out=0.155)
        else:
            # Built-in warm timber banquette lounge bench + colorful Google pillows inside NW Pavilion
            bm_add_box(bm_podium, pmat @ Vector((0.0, pav_d * 0.28, 0.72)), (6.6, 1.25, 0.44), rot_euler=(0, 0, pav_yaw))
            bm_add_box(bm_soffit, pmat @ Vector((0.0, pav_d * 0.28, 0.98)), (6.8, 1.32, 0.09), rot_euler=(0, 0, pav_yaw))
            for ci, cx_o in enumerate((-2.2, -0.7, 0.8, 2.3)):
                bm_add_box(bm_cush[ci % 4], pmat @ Vector((cx_o, pav_d * 0.22, 1.12)), (1.15, 0.72, 0.16), rot_euler=(0, 0, pav_yaw), bevel=0.03)

    # 5D. Stepped Timber Amphitheater Lounge Seating (SE Atrium Quadrant at (+21.5, -20.5) facing NW!)
    amp_x, amp_y = 21.5, -20.5
    amp_yaw = math.radians(135.0)  # Local -Y faces NW toward central atrium (0,0)
    amat = Matrix.Translation((amp_x, amp_y, 0.0)) @ Euler((0.0, 0.0, amp_yaw), 'XYZ').to_matrix().to_4x4()
    amp_w = 8.8
    # 4 Ascending Warm-Cedar Amphitheater Tiers (Z = 0.40 -> 0.82 -> 1.24 -> 1.66 -> 2.08m)
    for ti in range(4):
        tier_h = (ti + 1) * 0.42
        tier_y = -1.80 + ti * 1.15
        tier_z_c = 0.40 + tier_h * 0.5
        bm_add_box(bm_soffit, amat @ Vector((0.0, tier_y, tier_z_c)), (amp_w, 1.18, tier_h), rot_euler=(0, 0, amp_yaw), bevel=0.02)
        # Subtle warm LED step-nosing glow strip on each riser
        bm_add_box(bm_light, amat @ Vector((0.0, tier_y - 0.59, 0.40 + tier_h - 0.06)), (amp_w - 0.6, 0.04, 0.05), rot_euler=(0, 0, amp_yaw))
        # Colorful Google primary-colored upholstered lounge cushions scattered naturally on each tier!
        for cj in range(3):
            cx_o = -2.8 + cj * 2.8 + (0.35 if ti % 2 == 1 else -0.25)
            c_idx = (ti + cj) % 4
            bm_add_box(bm_cush[c_idx], amat @ Vector((cx_o, tier_y + 0.04, 0.40 + tier_h + 0.07)), (1.45, 0.74, 0.14), rot_euler=(0, 0, amp_yaw), bevel=0.03)
    # Flanking sculpted travertine/wood planter cheek walls embracing the amphitheater steps
    for sgn in (-1.0, 1.0):
        bm_add_box(bm_podium, amat @ Vector((sgn * (amp_w * 0.5 + 0.55), 0.15, 1.20)), (1.10, 4.90, 1.60), rot_euler=(0, 0, amp_yaw), bevel=0.04)
        for py_o in (-1.4, 0.4, 1.8):
            bm_add_organic_cluster(
                bm_plants,
                amat @ Vector((sgn * (amp_w * 0.5 + 0.55), py_o, 2.25)),
                0.72, 0.72, 0.58, subdiv=1, seed=int(abs(py_o * 37) + (11 if sgn > 0 else 29)), crinkle=0.22,
            )

    # 5E. SW Gallery Glowing Google Workspace Showcase Feature Wall (Blender (-23.5, -20.0), facing NE)
    sw_x, sw_y, sw_yaw = -23.5, -20.0, math.radians(-45.0)
    sw_mat = Matrix.Translation((sw_x, sw_y, 0.0)) @ Euler((0.0, 0.0, sw_yaw), 'XYZ').to_matrix().to_4x4()
    bm_add_box(bm_dark, sw_mat @ Vector((0.0, 0.0, 1.82)), (5.6, 0.34, 2.84), rot_euler=(0, 0, sw_yaw))
    bm_add_box(bm_soffit, sw_mat @ Vector((-3.0, 0.0, 1.82)), (0.42, 0.46, 2.88), rot_euler=(0, 0, sw_yaw))
    bm_add_box(bm_soffit, sw_mat @ Vector(( 3.0, 0.0, 1.82)), (0.42, 0.46, 2.88), rot_euler=(0, 0, sw_yaw))
    add_showcase_quad(bm_showcase, Vector((sw_x, sw_y, 1.92)), 5.1, 2.30, sw_yaw, offset_out=0.185)
    add_showcase_quad(bm_showcase, Vector((sw_x, sw_y, 1.92)), 5.1, 2.30, sw_yaw + math.pi, offset_out=0.185)

    # 5F. 8 Sculpted Biophilic Indoor Planter Beds flanking all 4 wide open N/S/E/W Entrance Portals!
    # Positioned strictly outside |x|<6.8 and |y|<6.8 so all 4 entrance corridors remain 100% WIDE OPEN!
    portal_planters = [
        (-9.8,  29.2, 0.0),         # North portal west flank
        ( 9.8,  29.2, 0.0),         # North portal east flank
        (-9.8, -29.2, 0.0),         # South portal west flank
        ( 9.8, -29.2, 0.0),         # South portal east flank
        (-28.0,  9.8, math.pi * 0.5),  # West portal north flank
        (-28.0, -9.8, math.pi * 0.5),  # West portal south flank
        ( 28.0,  9.8, math.pi * 0.5),  # East portal north flank
        ( 28.0, -9.8, math.pi * 0.5),  # East portal south flank
    ]
    for pi_idx, (plx, ply, pyaw) in enumerate(portal_planters):
        pl_mat = Matrix.Translation((plx, ply, 0.0)) @ Euler((0.0, 0.0, pyaw), 'XYZ').to_matrix().to_4x4()
        bm_add_box(bm_podium, pl_mat @ Vector((0.0, 0.0, 0.68)), (3.6, 1.35, 0.56), rot_euler=(0, 0, pyaw), bevel=0.05)
        bm_add_box(bm_soffit, pl_mat @ Vector((0.0, 0.0, 0.99)), (3.72, 1.44, 0.08), rot_euler=(0, 0, pyaw))
        for fo in (-1.05, 0.0, 1.05):
            bm_add_organic_cluster(
                bm_plants,
                pl_mat @ Vector((fo, 0.0, 1.36 + (0.14 if fo == 0.0 else 0.0))),
                0.72, 0.62, 0.52, subdiv=1, seed=670 + pi_idx * 17 + int(fo * 5), crinkle=0.24,
            )

    finalize_mesh("GC_DragonscaleCanopy", bm_canopy, mat_canopy, smooth=False, uv_scale=0.14)
    finalize_mesh("GC_Skylights", bm_sky, mat_skylight, smooth=False, uv_scale=0.18)
    finalize_mesh("GC_WoodSoffit_Huddle", bm_soffit, mat_soffit, smooth=False, uv_scale=0.22)
    finalize_mesh("GC_SteelColonnades", bm_cols, mat_column, smooth=True, uv_scale=0.4)
    finalize_mesh("GC_DarkSteelFrames", bm_dark, mat_dark_steel, smooth=False, uv_scale=0.4)
    finalize_mesh("GC_TravertinePodium", bm_podium, mat_podium, smooth=False, uv_scale=0.20)
    finalize_mesh("GC_AtriumGlass", bm_glass, mat_atrium_glass, smooth=False, uv_scale=0.2)
    finalize_mesh("GC_HuddleMarble", bm_marble, mat_marble, smooth=False, uv_scale=0.4)
    finalize_mesh("GC_HuddleAccent", bm_accent, mat_huddle_accent, smooth=False)
    finalize_mesh("GC_WarmLights", bm_light, mat_warm_light, smooth=False)
    finalize_mesh("GC_AtriumPlants", bm_plants, mat_planter_green, smooth=True)
    finalize_mesh("GC_WorkspaceShowcases", bm_showcase, mat_showcase, smooth=False, keep_existing_uv=True)
    finalize_mesh("GC_ChromeEspresso", bm_chrome, mat_chrome, smooth=True)
    for i, cname in enumerate(("Blue", "Red", "Yellow", "Green")):
        finalize_mesh(f"GC_Cushions{cname}", bm_cush[i], mat_g_cush[i], smooth=True)

    return export_asset("landmark_gradient_canopy.glb")


# ===========================================================================
# 9. LANDMARK: THE ORB PLAZA (Circular Stone Plaza r=10m + Faceted Metallic Orb)
# ===========================================================================
def build_orb_plaza():
    reset_scene()

    tex_stone = gen_stone_paver_tex("Orb_StoneTex", 160, seed=701)
    tex_cedar = gen_cedar_wood_tex("Orb_CedarTex", 128, seed=702)

    mat_stone = make_pbr_mat("Orb_StonePlaza", base_color=hex_to_linear("#DED8CC"), roughness=0.78, tex_img=tex_stone, bump_strength=0.15)
    mat_basalt = make_pbr_mat("Orb_BasaltAccent", base_color=hex_to_linear("#353C46"), roughness=0.46, metallic=0.14)
    mat_cedar = make_pbr_mat("Orb_BenchCedar", base_color=hex_to_linear("#AC6D3F"), roughness=0.66, tex_img=tex_cedar, bump_strength=0.14)
    mat_orb_chrome = make_pbr_mat("Orb_BrushedTitanium", base_color=hex_to_linear("#DCE4EE"), metallic=0.92, roughness=0.16, specular=0.9)
    mat_orb_facet = make_pbr_mat("Orb_CobaltAlloy", base_color=hex_to_linear("#4B8FD8"), metallic=0.88, roughness=0.22, specular=0.85)
    mat_water = make_pbr_mat("Orb_ReflectingPool", base_color=hex_to_linear("#1A6FA8"), metallic=0.15, roughness=0.05, ior=1.33, specular=0.9)

    bm_stone = bmesh.new()
    bm_basalt = bmesh.new()
    bm_cedar = bmesh.new()
    bm_chrome = bmesh.new()
    bm_facet = bmesh.new()
    bm_water = bmesh.new()

    def circle_poly(r, segs=40):
        return [(r * math.cos(2 * math.pi * i / segs), r * math.sin(2 * math.pi * i / segs)) for i in range(segs)]

    # 1. Circular Stone Plaza (exact r = 10.0m, grounded at Z = 0.0..0.20m)
    bm_add_polygon_prism(bm_stone, circle_poly(10.0, 44), 0.0, 0.20)
    # Decorative recessed basalt accent rings at r = 9.3m and r = 4.5m
    bm_add_torus(bm_basalt, (0, 0, 0.205), 9.35, 0.14, major_segs=44, minor_segs=6)
    bm_add_torus(bm_basalt, (0, 0, 0.205), 4.55, 0.12, major_segs=36, minor_segs=6)

    # 2. Central Tiered Granite Sculpture Plinth + Reflecting Rim (Z = 0.20..0.92m)
    bm_add_polygon_prism(bm_basalt, circle_poly(3.10, 32), 0.20, 0.56)
    bm_add_polygon_prism(bm_stone, circle_poly(2.75, 32), 0.56, 0.72)
    bm_add_polygon_prism(bm_water, circle_poly(2.50, 32), 0.72, 0.78)
    bm_add_polygon_prism(bm_basalt, circle_poly(1.35, 24), 0.76, 0.96)

    # 3. 4 Curved Architectural Stone & Cedar Seating Benches at r = 7.3m
    for bi in range(4):
        base_ang = bi * (math.pi * 0.5) + math.pi * 0.25
        n_seg = 6
        arc_span = 0.74
        for s in range(n_seg):
            a0 = base_ang - arc_span * 0.5 + arc_span * (s / n_seg)
            a1 = base_ang - arc_span * 0.5 + arc_span * ((s + 1) / n_seg)
            amid = (a0 + a1) * 0.5
            r_bench = 7.35
            seg_len = r_bench * (a1 - a0) + 0.06
            cx, cy = r_bench * math.cos(amid), r_bench * math.sin(amid)
            yaw = amid + math.pi * 0.5
            # Sculpted stone bench base
            bm_add_box(bm_stone, (cx, cy, 0.36), (seg_len, 0.78, 0.34), rot_euler=(0, 0, yaw))
            # Warm cedar slatted seating top
            bm_add_box(bm_cedar, (cx, cy, 0.56), (seg_len + 0.02, 0.88, 0.08), rot_euler=(0, 0, yaw), bevel=0.015)

    # 4. Iconic "The Orb" Metallic Faceted/Brushed Sculpture (r = 2.15m, center Z = 3.18m, top ~5.35m)
    orb_c = Vector((0.0, 0.0, 3.18))
    # Sculptural brushed-steel tripod cradle rising from granite plinth
    for k in range(3):
        ang = k * (2.0 * math.pi / 3.0) + 0.35
        p0 = Vector((0.88 * math.cos(ang), 0.88 * math.sin(ang), 0.90))
        p1 = orb_c + Vector((0.72 * math.cos(ang), 0.72 * math.sin(ang), -1.75))
        bm_add_prism_between(bm_basalt, p0, p1, 0.16, 0.11, segs=10)

    # Inner faceted geodesic cobalt-alloy core (flat-shaded crisp metallic facets!)
    res_core = bmesh.ops.create_icosphere(bm_facet, subdivisions=2, radius=1.96, matrix=Matrix.Translation(orb_c))
    # Outer sculptural brushed-titanium architectural geodesic ribs + intersecting equatorial art rings!
    res_cage = bmesh.ops.create_icosphere(bm_chrome, subdivisions=2, radius=2.14, matrix=Matrix.Translation(orb_c))
    bmesh.ops.wireframe(bm_chrome, faces=list(bm_chrome.faces), thickness=0.095, offset=0.0, use_replace=True, use_even_offset=True)

    # 3 Sweeping Sculptural Brushed-Titanium Orbital Ribbons embracing The Orb
    bm_add_torus(bm_chrome, orb_c, 2.24, 0.085, rot_euler=(0.48, 0.25, 0.0), major_segs=32, minor_segs=8)
    bm_add_torus(bm_chrome, orb_c, 2.28, 0.075, rot_euler=(-0.62, 0.85, 0.4), major_segs=32, minor_segs=8)
    bm_add_torus(bm_chrome, orb_c, 2.20, 0.065, rot_euler=(1.15, -0.40, 0.8), major_segs=32, minor_segs=8)

    finalize_mesh("Orb_StonePlaza", bm_stone, mat_stone, smooth=False, uv_scale=0.28)
    finalize_mesh("Orb_BasaltTrim", bm_basalt, mat_basalt, smooth=False, uv_scale=0.4)
    finalize_mesh("Orb_CedarBenches", bm_cedar, mat_cedar, smooth=False, uv_scale=0.5)
    finalize_mesh("Orb_ReflectingPool", bm_water, mat_water, smooth=False)
    finalize_mesh("Orb_FacetedCore", bm_facet, mat_orb_facet, smooth=False)   # Deliberately flat-faceted for crisp sculptural reflections!
    finalize_mesh("Orb_BrushedLattice", bm_chrome, mat_orb_chrome, smooth=True)

    return export_asset("landmark_orb_plaza.glb")


# ===========================================================================
# 10. PROP: 8-PANEL SCALLOPED GOOGLE UMBRELLA + BISTRO TABLE & 3 CHAIRS
# ===========================================================================
def build_umbrella_bistro():
    reset_scene()

    tex_cedar = gen_cedar_wood_tex("Umb_CedarTex", 128, seed=801)
    tex_conc = gen_concrete_tex("Umb_ConcTex", 128, tint=(0.86, 0.84, 0.80), seed=802)

    mat_g_colors = [
        make_pbr_mat("Umb_GoogleBlue", base_color=hex_to_linear("#4285F4"), roughness=0.84, double_sided=True),
        make_pbr_mat("Umb_GoogleRed", base_color=hex_to_linear("#EA4335"), roughness=0.84, double_sided=True),
        make_pbr_mat("Umb_GoogleYellow", base_color=hex_to_linear("#FBBC04"), roughness=0.84, double_sided=True),
        make_pbr_mat("Umb_GoogleGreen", base_color=hex_to_linear("#34A853"), roughness=0.84, double_sided=True),
    ]
    mat_alum = make_pbr_mat("Umb_Aluminum", base_color=hex_to_linear("#D0D6DE"), metallic=0.86, roughness=0.24)
    mat_dark = make_pbr_mat("Umb_DarkMetal", base_color=hex_to_linear("#2C323B"), metallic=0.72, roughness=0.40)
    mat_table = make_pbr_mat("Umb_TableStone", base_color=hex_to_linear("#E4DED4"), roughness=0.68, tex_img=tex_conc, bump_strength=0.10)
    mat_wood = make_pbr_mat("Umb_ChairWood", base_color=hex_to_linear("#B07344"), roughness=0.62, tex_img=tex_cedar, bump_strength=0.10)
    mat_shell = make_pbr_mat("Umb_ChairShell", base_color=hex_to_linear("#F1F5F9"), roughness=0.42)

    bm_panels = [bmesh.new() for _ in range(4)]
    bm_alum = bmesh.new()
    bm_dark = bmesh.new()
    bm_table = bmesh.new()
    bm_wood = bmesh.new()
    bm_shell = bmesh.new()

    # 1. Weighted Umbrella Base + Brushed-Aluminum Pole + Under-Canopy Ribs
    bm_add_prism_between(bm_dark, (0, 0, 0.0), (0, 0, 0.08), 0.34, 0.30, segs=16)
    bm_add_prism_between(bm_dark, (0, 0, 0.08), (0, 0, 0.24), 0.06, 0.045, segs=12)
    bm_add_prism_between(bm_alum, (0, 0, 0.22), (0, 0, 2.92), 0.028, 0.026, segs=12)
    # Finial cap at apex
    bm_add_sphere(bm_alum, (0, 0, 2.96), 0.045, 0.045, 0.065, u_segs=10, v_segs=8)

    # 2. 8-Panel Curved Scalloped Fabric Google Umbrella Canopy (D = 3.1m, rim Z = 2.26m, apex Z = 2.90m)
    R_umb = 1.56
    z_apex = 2.90
    z_rim = 2.26
    n_panels = 8
    rad_steps = 5
    arc_steps = 6

    for p in range(n_panels):
        bm_p = bm_panels[p % 4]
        a_start = 2.0 * math.pi * p / n_panels
        a_end = 2.0 * math.pi * (p + 1) / n_panels

        # Radial strut rib inside canopy
        rib_mid = (0.0, 0.0, 2.18)
        rib_tip = (R_umb * 0.96 * math.cos(a_start), R_umb * 0.96 * math.sin(a_start), z_rim + 0.01)
        bm_add_prism_between(bm_alum, (0, 0, z_apex - 0.04), rib_tip, 0.012, 0.008, segs=5)
        bm_add_prism_between(bm_alum, rib_mid, (rib_tip[0] * 0.55, rib_tip[1] * 0.55, 2.54), 0.010, 0.008, segs=5)

        # Curved double-arched fabric gore grid
        grid = []
        for ir in range(rad_steps + 1):
            fr = ir / float(rad_steps)
            r = 0.04 + fr * (R_umb - 0.04)
            # Gentle graceful dome profile
            z_base = z_apex - (z_apex - z_rim) * (fr ** 1.48)
            row = []
            for ia in range(arc_steps + 1):
                fa = ia / float(arc_steps)
                ang = a_start + fa * (a_end - a_start)
                # Subtle fabric catenary sag between ribs
                sag = -0.028 * math.sin(fa * math.pi) * (fr ** 1.2)
                row.append(bm_p.verts.new((r * math.cos(ang), r * math.sin(ang), z_base + sag)))
            grid.append(row)

        for ir in range(rad_steps):
            for ia in range(arc_steps):
                bm_p.faces.new((grid[ir][ia], grid[ir + 1][ia], grid[ir + 1][ia + 1], grid[ir][ia + 1]))

        # Scalloped hanging fabric valance flap along bottom edge of each gore!
        val_top = grid[-1]
        val_bot = []
        for ia in range(arc_steps + 1):
            fa = ia / float(arc_steps)
            ang = a_start + fa * (a_end - a_start)
            # Graceful downward scallop curve deepest at center of each panel
            drop = 0.09 + 0.08 * math.sin(fa * math.pi)
            p_top = val_top[ia].co
            val_bot.append(bm_p.verts.new((p_top.x * 1.01, p_top.y * 1.01, p_top.z - drop)))
        for ia in range(arc_steps):
            bm_p.faces.new((val_top[ia], val_bot[ia], val_bot[ia + 1], val_top[ia + 1]))

    # 3. Round Concrete/Stone Bistro Table (D = 1.26m, H = 0.76m)
    tbl_r = 0.63
    tbl_z = 0.76
    bm_add_prism_between(bm_table, (0, 0, tbl_z - 0.045), (0, 0, tbl_z), tbl_r, tbl_r, segs=24)
    # Dark powder-coated metal edge rim around tabletop
    bm_add_torus(bm_dark, (0, 0, tbl_z - 0.022), tbl_r, 0.022, major_segs=24, minor_segs=6)
    # 4 gracefully splayed tubular legs
    for k in range(4):
        ang = k * math.pi * 0.5 + math.pi * 0.25
        p_top = (0.36 * math.cos(ang), 0.36 * math.sin(ang), tbl_z - 0.04)
        p_bot = (0.52 * math.cos(ang), 0.52 * math.sin(ang), 0.0)
        bm_add_prism_between(bm_dark, p_bot, p_top, 0.018, 0.022, segs=8)
    # Cross brace ring
    bm_add_torus(bm_dark, (0, 0, 0.28), 0.45, 0.012, major_segs=16, minor_segs=6)

    # 4. 3 Sculpted Modern Campus Bistro Chairs arranged naturally around the table
    for ci in range(3):
        ang = ci * (2.0 * math.pi / 3.0) + 0.32
        dist = 1.04
        cx, cy = dist * math.cos(ang), dist * math.sin(ang)
        # Chair faces inward toward table center (with slight organic angle offset)
        cyaw = ang + math.pi + (0.08 if ci == 1 else -0.05)
        cmat = Matrix.Translation((cx, cy, 0.0)) @ Euler((0, 0, cyaw), 'XYZ').to_matrix().to_4x4()

        def cp(x, y, z):
            return cmat @ Vector((x, y, z))

        # Splayed slender steel legs (4 legs grounded at Z = 0.0)
        leg_coords = [
            ((-0.22, -0.22, 0.0), (-0.17, -0.17, 0.45)),
            (( 0.22, -0.22, 0.0), ( 0.17, -0.17, 0.45)),
            ((-0.22,  0.22, 0.0), (-0.17,  0.17, 0.45)),
            (( 0.22,  0.22, 0.0), ( 0.17,  0.17, 0.45)),
        ]
        for l0, l1 in leg_coords:
            bm_add_prism_between(bm_dark, cp(*l0), cp(*l1), 0.013, 0.015, segs=6)

        # Contoured seat cushion + curved wraparound backrest (cedar slat accent + sculpted white shell)
        bm_add_box(bm_wood, cp(0.0, 0.0, 0.46), (0.44, 0.44, 0.045), rot_euler=(0, 0, cyaw), bevel=0.015)
        # Curved backrest arc (5 smoothly angled segments)
        back_pts = []
        for k in range(7):
            u = -1.0 + 2.0 * (k / 6.0)
            a = u * 0.95
            bx = -0.20 + 0.08 * (1.0 - math.cos(a))
            by = 0.24 * math.sin(a)
            back_pts.append(cp(bx, by, 0.78))
        bm_add_spline_tube(bm_shell, back_pts, [0.045, 0.058, 0.068, 0.072, 0.068, 0.058, 0.045], segs=8, oval_ratio=2.0)
        # Backrest support uprights
        for sy in (-0.15, 0.15):
            bm_add_prism_between(bm_dark, cp(-0.17, sy, 0.45), cp(-0.20, sy, 0.78), 0.014, 0.013, segs=6)

    names = ["Umb_CanopyBlue", "Umb_CanopyRed", "Umb_CanopyYellow", "Umb_CanopyGreen"]
    for i in range(4):
        finalize_mesh(names[i], bm_panels[i], mat_g_colors[i], smooth=True)
    finalize_mesh("Umb_AluminumPoleRibs", bm_alum, mat_alum, smooth=True)
    finalize_mesh("Umb_MetalFrames", bm_dark, mat_dark, smooth=True)
    finalize_mesh("Umb_BistroTable", bm_table, mat_table, smooth=True, uv_scale=0.6)
    finalize_mesh("Umb_ChairSeats", bm_wood, mat_wood, smooth=False, uv_scale=0.8)
    finalize_mesh("Umb_ChairBacks", bm_shell, mat_shell, smooth=True)

    return export_asset("prop_umbrella_bistro.glb", ground_auto=True)


# ===========================================================================
# 11. PROP: GBIKE RACK WITH 4 REALISTIC MULTI-COLORED GOOGLE GBIKES
# ===========================================================================
def build_gbike_rack():
    reset_scene()

    mat_rack = make_pbr_mat("GBike_SteelRack", base_color=hex_to_linear("#B8C0CA"), metallic=0.86, roughness=0.28)
    mat_curb = make_pbr_mat("GBike_BaseCurb", base_color=hex_to_linear("#64748B"), roughness=0.78)
    mat_tire = make_pbr_mat("GBike_TireRubber", base_color=hex_to_linear("#1E2228"), roughness=0.88)
    mat_chrome = make_pbr_mat("GBike_Chrome", base_color=hex_to_linear("#E2E8F0"), metallic=0.92, roughness=0.16)
    mat_saddle = make_pbr_mat("GBike_Saddle", base_color=hex_to_linear("#262930"), roughness=0.68)
    mat_basket = make_pbr_mat("GBike_BasketWire", base_color=hex_to_linear("#333B46"), metallic=0.76, roughness=0.36)

    g_hexes = [
        ("Blue",   "#4285F4"),
        ("Red",    "#EA4335"),
        ("Yellow", "#FBBC04"),
        ("Green",  "#34A853"),
    ]
    mat_frames = [make_pbr_mat(f"GBike_Frame{n}", base_color=hex_to_linear(h), metallic=0.30, roughness=0.28) for n, h in g_hexes]

    bm_rack = bmesh.new()
    bm_curb = bmesh.new()
    bm_tire = bmesh.new()
    bm_chrome = bmesh.new()
    bm_saddle = bmesh.new()
    bm_basket = bmesh.new()
    bm_frames = [bmesh.new() for _ in range(4)]

    # 1. Tubular Galvanized Steel Bike Rack (3.6m wide, 5 inverted-U loops on grounded steel base rails)
    bm_add_box(bm_curb, (0.0, 0.0, 0.025), (3.60, 0.56, 0.05), bevel=0.01)
    for sy in (-0.22, 0.22):
        bm_add_prism_between(bm_rack, (-1.75, sy, 0.05), (1.75, sy, 0.05), 0.022, 0.022, segs=8)
    for hi in range(5):
        hx = -1.60 + hi * 0.80
        # Smooth inverted-U steel hoop
        u_pts = [
            (hx, -0.22, 0.05),
            (hx, -0.22, 0.62),
            (hx, -0.15, 0.76),
            (hx,  0.00, 0.80),
            (hx,  0.15, 0.76),
            (hx,  0.22, 0.62),
            (hx,  0.22, 0.05),
        ]
        bm_add_spline_tube(bm_rack, u_pts, [0.024] * len(u_pts), segs=8)

    # 2. 4 Realistic Multi-Colored Google GBikes (docked cleanly in the 4 rack bays!)
    bike_configs = [
        (-1.20, +0.04, +0.08, 0, 2),  # Blue frame, yellow accent fender
        (-0.40, -0.05, -0.06, 1, 0),  # Red frame, blue accent fender
        (+0.40, +0.05, +0.05, 2, 3),  # Yellow frame, green accent fender
        (+1.20, -0.04, -0.09, 3, 1),  # Green frame, red accent fender
    ]
    wheel_r = 0.33
    tire_r = 0.030
    axle_z = wheel_r + tire_r  # Grounded cleanly at Z = 0.0!

    for bx, yaw_b, steer, frame_idx, fender_idx in bike_configs:
        bm_fr = bm_frames[frame_idx]
        bm_fn = bm_frames[fender_idx]
        # Bike parked facing -Y (front wheel tucked right into the rack hoop!)
        bmat = Matrix.Translation((bx, 0.58, 0.0)) @ Euler((0.0, 0.0, yaw_b), 'XYZ').to_matrix().to_4x4()

        def bp(x, y, z):
            return bmat @ Vector((x, y, z))

        def add_wheel(wy, steer_yaw=0.0):
            w_center = bp(0.0, wy, axle_z)
            w_rot = Euler((0.0, math.pi * 0.5, yaw_b + steer_yaw), 'XYZ')
            bm_add_torus(bm_tire, w_center, wheel_r, tire_r, rot_euler=w_rot, major_segs=18, minor_segs=7)
            bm_add_torus(bm_chrome, w_center, wheel_r - 0.026, 0.012, rot_euler=w_rot, major_segs=18, minor_segs=5)
            hub_rot = Euler((0.0, 0.0, yaw_b + steer_yaw), 'XYZ').to_matrix()
            hub_off = hub_rot @ Vector((0.045, 0.0, 0.0))
            bm_add_prism_between(bm_chrome, w_center - hub_off, w_center + hub_off, 0.020, 0.020, segs=7)
            for sp in range(8):
                sa = sp * math.pi / 4.0
                rim_local = hub_rot @ Vector((0.0, math.cos(sa) * (wheel_r - 0.026), math.sin(sa) * (wheel_r - 0.026)))
                bm_add_prism_between(bm_chrome, w_center, w_center + rim_local, 0.004, 0.004, segs=4)

        wy_front = -0.56
        wy_rear = +0.52
        add_wheel(wy_front, steer_yaw=steer)
        add_wheel(wy_rear, steer_yaw=0.0)

        # Classic Google GBike Cruiser / Step-Through Tubular Frame (smooth graceful arcs!)
        bb = bp(0.0, 0.06, 0.30)          # Bottom bracket (crank hub)
        seat_cl = bp(0.0, 0.18, 0.74)     # Seatpost clamp
        head_bot = bp(0.0, -0.38, 0.64)   # Head tube bottom
        head_top = bp(0.0, -0.35, 0.84)   # Head tube top

        bm_add_prism_between(bm_fr, bb, seat_cl, 0.020, 0.019, segs=7)
        bm_add_prism_between(bm_fr, head_bot, head_top, 0.022, 0.022, segs=7)
        # Smooth 5-point sweeping cruiser downtube & step-through top tube (zero V-kink!)
        bm_add_spline_tube(
            bm_fr,
            [head_bot, bp(0.0, -0.27, 0.50), bp(0.0, -0.15, 0.39), bp(0.0, -0.04, 0.33), bb],
            [0.020, 0.020, 0.020, 0.020, 0.020],
            segs=7,
        )
        bm_add_spline_tube(
            bm_fr,
            [head_top, bp(0.0, -0.22, 0.75), bp(0.0, -0.08, 0.68), bp(0.0, 0.05, 0.67), seat_cl],
            [0.016, 0.016, 0.016, 0.016, 0.016],
            segs=6,
        )
        # Rear triangle: chainstays & seatstays (left & right)
        for sgn in (-1.0, 1.0):
            rear_ax = bp(sgn * 0.055, wy_rear, axle_z)
            bm_add_prism_between(bm_fr, bb + bp(sgn * 0.03, 0, 0) - bp(0, 0, 0), rear_ax, 0.013, 0.010, segs=6)
            bm_add_prism_between(bm_fr, seat_cl, rear_ax, 0.012, 0.010, segs=6)
            # Front fork blades
            front_ax = bp(sgn * 0.048, wy_front, axle_z)
            bm_add_prism_between(bm_fr, head_bot, front_ax, 0.016, 0.011, segs=6)

        # Curved Rear & Front Mudguard Fenders (signature contrasting Google primary color!)
        for wy_f, a0, a1 in ((wy_rear, 0.35, 2.35), (wy_front, 0.85, 2.55)):
            f_pts = []
            for k in range(7):
                fa = a0 + (a1 - a0) * (k / 6.0)
                f_pts.append(bp(0.0, wy_f + math.cos(fa) * (wheel_r + 0.042), axle_z + math.sin(fa) * (wheel_r + 0.042)))
            bm_add_spline_tube(bm_fn, f_pts, [0.024] * 7, segs=6, oval_ratio=0.45)

        # Chrome Seatpost & Contoured Cruiser Saddle
        sad_p = bp(0.0, 0.21, 0.90)
        bm_add_prism_between(bm_chrome, seat_cl, sad_p, 0.013, 0.013, segs=7)
        bm_add_sphere(bm_saddle, sad_p + Vector((0, 0, 0.03)), 0.095, 0.145, 0.038, u_segs=10, v_segs=6)

        # Crankset Chainring & Pedals
        bm_add_torus(bm_chrome, bp(0.045, 0.06, 0.30), 0.075, 0.010, rot_euler=(0, math.pi * 0.5, yaw_b), major_segs=14, minor_segs=5)
        for sgn, pz_o in ((-1.0, -0.13), (1.0, 0.13)):
            bm_add_prism_between(bm_chrome, bp(sgn * 0.04, 0.06, 0.30), bp(sgn * 0.06, 0.06, 0.30 + pz_o), 0.009, 0.008, segs=5)
            bm_add_box(bm_saddle, bp(sgn * 0.11, 0.06, 0.30 + pz_o), (0.09, 0.07, 0.022), rot_euler=(0, 0, yaw_b))

        # Chrome Stem & Swept-Back Cruiser Handlebars + Rubber Grips
        stem_top = bp(0.0, -0.34, 1.00)
        bm_add_prism_between(bm_chrome, head_top, stem_top, 0.014, 0.014, segs=7)
        hb_pts = [
            bp(-0.30, -0.18, 1.04),
            bp(-0.22, -0.30, 1.05),
            stem_top,
            bp( 0.22, -0.30, 1.05),
            bp( 0.30, -0.18, 1.04),
        ]
        bm_add_spline_tube(bm_chrome, hb_pts, [0.012] * 5, segs=7)
        # Black rubber grips at handlebar ends
        bm_add_prism_between(bm_saddle, bp(-0.26, -0.24, 1.045), bp(-0.31, -0.16, 1.038), 0.017, 0.017, segs=7)
        bm_add_prism_between(bm_saddle, bp( 0.26, -0.24, 1.045), bp( 0.31, -0.16, 1.038), 0.017, 0.017, segs=7)

        # Signature Iconic Google GBike Front Wire Basket!
        bk_c = bp(0.0, -0.54, 0.88)
        bw, bd, bh = 0.34, 0.25, 0.22
        # Top, mid, and bottom wire perimeter hoops + vertical wire ribs + floor grid
        for hz in (-bh * 0.5, 0.0, bh * 0.5):
            sc = 0.82 if hz < 0 else (0.91 if hz == 0 else 1.0)
            w2, d2 = bw * 0.5 * sc, bd * 0.5 * sc
            c0 = bk_c + (bmat.to_3x3() @ Vector((-w2, -d2, hz)))
            c1 = bk_c + (bmat.to_3x3() @ Vector(( w2, -d2, hz)))
            c2 = bk_c + (bmat.to_3x3() @ Vector(( w2,  d2, hz)))
            c3 = bk_c + (bmat.to_3x3() @ Vector((-w2,  d2, hz)))
            for pa, pb in ((c0, c1), (c1, c2), (c2, c3), (c3, c0)):
                bm_add_prism_between(bm_basket, pa, pb, 0.006, 0.006, segs=5)
        # Vertical basket corners + side wires + mounting stays to fork
        for sx in (-1.0, 0.0, 1.0):
            for sy in (-1.0, 1.0):
                p_b = bk_c + (bmat.to_3x3() @ Vector((sx * bw * 0.41, sy * bd * 0.41, -bh * 0.5)))
                p_t = bk_c + (bmat.to_3x3() @ Vector((sx * bw * 0.50, sy * bd * 0.50,  bh * 0.5)))
                bm_add_prism_between(bm_basket, p_b, p_t, 0.005, 0.005, segs=4)
        # Basket floor plate & support struts to front axle
        bm_add_box(bm_basket, bk_c + Vector((0, 0, -bh * 0.5)), (bw * 0.82, bd * 0.82, 0.012), rot_euler=(0, 0, yaw_b))
        for sgn in (-1.0, 1.0):
            bm_add_prism_between(bm_basket, bp(sgn * 0.05, wy_front, axle_z), bk_c + (bmat.to_3x3() @ Vector((sgn * 0.11, 0.0, -bh * 0.5))), 0.006, 0.006, segs=4)

    finalize_mesh("GBike_RackHoops", bm_rack, mat_rack, smooth=True)
    finalize_mesh("GBike_RackCurb", bm_curb, mat_curb, smooth=False)
    finalize_mesh("GBike_Tires", bm_tire, mat_tire, smooth=True)
    finalize_mesh("GBike_ChromeParts", bm_chrome, mat_chrome, smooth=True)
    finalize_mesh("GBike_SaddlesGrips", bm_saddle, mat_saddle, smooth=True)
    finalize_mesh("GBike_FrontBaskets", bm_basket, mat_basket, smooth=False)
    for i, (cname, _) in enumerate(g_hexes):
        finalize_mesh(f"GBike_Frame{cname}", bm_frames[i], mat_frames[i], smooth=True)

    return export_asset("prop_gbike_rack.glb")


# ===========================================================================
# 12. PROP: CALIFORNIA LIVE OAK TREE (~9m tall, branching limbs + organic clusters)
# ===========================================================================
def build_oak_tree():
    reset_scene()
    rng = np.random.default_rng(901)

    tex_bark = gen_bark_tex("Oak_BarkTex", 128, redwood=False, seed=902)
    tex_leaf = gen_foliage_tex("Oak_LeafTex", 128, redwood=False, seed=903)

    mat_bark = make_pbr_mat("Oak_Bark", base_color=hex_to_linear("#6E5D4D"), roughness=0.90, tex_img=tex_bark, bump_strength=0.28)
    # 3 rich layered California Live Oak foliage tones (shadow emerald, mid olive, sunlit sage)
    mat_leaves = [
        make_pbr_mat("Oak_FoliageDeep", base_color=(1, 1, 1, 1), roughness=0.80, tex_img=tex_leaf, tex_tint=hex_to_linear("#4B6B38"), bump_strength=0.14),
        make_pbr_mat("Oak_FoliageMid", base_color=(1, 1, 1, 1), roughness=0.76, tex_img=tex_leaf, tex_tint=hex_to_linear("#6E8F48"), bump_strength=0.14),
        make_pbr_mat("Oak_FoliageSun", base_color=(1, 1, 1, 1), roughness=0.72, tex_img=tex_leaf, tex_tint=hex_to_linear("#8EB05A"), bump_strength=0.12),
    ]

    bm_bark = bmesh.new()
    bm_leaves = [bmesh.new() for _ in range(3)]

    # 1. Sculpted Tapered Grooved Trunk with organic slight twist & 5 flared root buttresses (Z = 0.0..2.9m)
    trunk_pts = [
        (0.00, 0.00, 0.00),
        (0.04, 0.02, 0.65),
        (0.10, -0.04, 1.40),
        (0.06, 0.04, 2.20),
        (0.00, 0.05, 2.85),
    ]
    trunk_rads = [0.64, 0.48, 0.42, 0.39, 0.36]
    bm_add_spline_tube(bm_bark, trunk_pts, trunk_rads, segs=12, flute_amp=0.11, flute_freq=6)

    # 5 organic root buttress flares anchored cleanly at Z = 0.0
    for ri in range(5):
        ra = ri * (2.0 * math.pi / 5.0) + 0.25
        root_pts = [
            (0.28 * math.cos(ra), 0.28 * math.sin(ra), 0.95),
            (0.62 * math.cos(ra), 0.62 * math.sin(ra), 0.32),
            (0.95 * math.cos(ra), 0.95 * math.sin(ra), 0.00),
        ]
        bm_add_spline_tube(bm_bark, root_pts, [0.22, 0.16, 0.08], segs=7)

    # 2. 5 Sculptural Spreading Primary Limbs + 13 Secondary Sub-Branches!
    # California Live Oaks spread gracefully outward into a picturesque broad dome (~9m tall, ~9m wide)
    crown_origin = Vector((0.0, 0.05, 2.75))
    primary_specs = [
        # (azimuth, spread_radius, tip_z, mid_lift, start_r)
        (0.15,  3.55, 5.85, 0.65, 0.24),
        (1.38,  3.75, 6.20, 0.70, 0.25),
        (2.62,  3.40, 5.55, 0.55, 0.23),
        (3.85,  3.80, 6.05, 0.72, 0.25),
        (5.08,  3.30, 6.50, 0.85, 0.22),
    ]
    cluster_anchors = []

    for bi, (az, spread, tip_z, lift, r0) in enumerate(primary_specs):
        ca, sa = math.cos(az), math.sin(az)
        p0 = crown_origin + Vector((0.12 * ca, 0.12 * sa, -0.15))
        p1 = Vector((spread * 0.36 * ca, spread * 0.36 * sa, 3.65 + lift * 0.55))
        p2 = Vector((spread * 0.72 * ca + 0.22 * sa, spread * 0.72 * sa - 0.22 * ca, 4.75 + lift * 0.85))
        p3 = Vector((spread * ca, spread * sa, tip_z))
        bm_add_spline_tube(bm_bark, [p0, p1, p2, p3], [r0, r0 * 0.78, r0 * 0.54, r0 * 0.28], segs=8, flute_amp=0.06, flute_freq=4)
        cluster_anchors.append((p3, 1.55, 1.45, 1.05))
        cluster_anchors.append((p2 + Vector((0, 0, 0.55)), 1.40, 1.30, 0.95))

        # Fork 2-3 secondary sub-branches from each primary limb!
        for sub_i, (d_az, d_r, d_z) in enumerate(((-0.55, 1.35, 1.25), (+0.52, 1.40, 1.35))):
            s_base = p1.lerp(p2, 0.55 if sub_i == 0 else 0.80)
            s_az = az + d_az
            s_mid = s_base + Vector((math.cos(s_az) * d_r * 0.55, math.sin(s_az) * d_r * 0.55, d_z * 0.65))
            s_tip = s_base + Vector((math.cos(s_az) * d_r, math.sin(s_az) * d_r, d_z))
            bm_add_spline_tube(bm_bark, [s_base, s_mid, s_tip], [r0 * 0.50, r0 * 0.32, r0 * 0.14], segs=6)
            cluster_anchors.append((s_tip, 1.38, 1.28, 0.98))

    # Central upper leader branch rising to crown apex (~8.9m)
    lead_pts = [
        crown_origin,
        Vector((-0.25, 0.20, 4.45)),
        Vector(( 0.18, -0.15, 6.10)),
        Vector(( 0.05, 0.10, 7.35)),
    ]
    bm_add_spline_tube(bm_bark, lead_pts, [0.24, 0.19, 0.13, 0.07], segs=8)
    for ca_off in (
        (Vector((0.0, 0.0, 7.85)), 1.85, 1.75, 1.25),
        (Vector((-1.35, 0.95, 7.25)), 1.55, 1.45, 1.05),
        (Vector(( 1.40, -0.85, 7.15)), 1.55, 1.40, 1.05),
        (Vector(( 0.85, 1.45, 7.10)), 1.48, 1.42, 1.02),
        (Vector((-1.15, -1.25, 7.05)), 1.50, 1.38, 1.00),
    ):
        cluster_anchors.append(ca_off)

    # 3. Multi-Cluster Layered Organic Foliage Canopy (38+ soft organic sculpted bough clusters!)
    for idx, (pos, rx, ry, rz) in enumerate(cluster_anchors):
        tone = 2 if pos.z > 6.8 else (1 if pos.z > 5.7 else 0)
        bm_add_organic_cluster(
            bm_leaves[tone],
            pos,
            rx * rng.uniform(0.92, 1.10),
            ry * rng.uniform(0.92, 1.10),
            rz * rng.uniform(0.86, 1.04),
            subdiv=2,
            seed=1000 + idx * 17,
            crinkle=0.14,
            droop=0.06,
        )
        # Two smaller overlapping organic leaf tufts around each bough for lush painterly oak crown
        for sub_k in range(2):
            sat_ang = idx * 2.399 + sub_k * 2.1
            sat_pos = pos + Vector((
                math.cos(sat_ang) * rx * 0.58,
                math.sin(sat_ang) * ry * 0.58,
                rng.uniform(-0.22, 0.36),
            ))
            sat_tone = min(2, max(0, tone + (1 if sat_pos.z > pos.z else -1)))
            bm_add_organic_cluster(
                bm_leaves[sat_tone],
                sat_pos,
                rx * 0.58,
                ry * 0.58,
                rz * 0.58,
                subdiv=2,
                seed=2000 + idx * 29 + sub_k * 13,
                crinkle=0.15,
                droop=0.04,
            )

    finalize_mesh("Oak_TrunkAndLimbs", bm_bark, mat_bark, smooth=True, uv_scale=0.55)
    for i, lname in enumerate(("Oak_CanopyDeep", "Oak_CanopyMid", "Oak_CanopySun")):
        finalize_mesh(lname, bm_leaves[i], mat_leaves[i], smooth=True, uv_scale=0.45)

    return export_asset("prop_oak_tree.glb", ground_auto=True)


# ===========================================================================
# 13. PROP: CALIFORNIA COASTAL REDWOOD (~16m tall, fluted reddish bark + drooping tiers)
# ===========================================================================
def build_redwood_tree():
    reset_scene()
    rng = np.random.default_rng(1101)

    tex_bark = gen_bark_tex("Redwood_BarkTex", 128, redwood=True, seed=1102)
    tex_leaf = gen_foliage_tex("Redwood_NeedleTex", 128, redwood=True, seed=1103)

    mat_bark = make_pbr_mat("Redwood_FlutedBark", base_color=hex_to_linear("#783A22"), roughness=0.92, tex_img=tex_bark)
    mat_needles = [
        make_pbr_mat("Redwood_NeedlesDeep", base_color=(1, 1, 1, 1), roughness=0.84, tex_img=tex_leaf, tex_tint=hex_to_linear("#265632")),
        make_pbr_mat("Redwood_NeedlesMid", base_color=(1, 1, 1, 1), roughness=0.80, tex_img=tex_leaf, tex_tint=hex_to_linear("#357442")),
        make_pbr_mat("Redwood_NeedlesSun", base_color=(1, 1, 1, 1), roughness=0.76, tex_img=tex_leaf, tex_tint=hex_to_linear("#4E9155")),
    ]

    bm_bark = bmesh.new()
    bm_needles = [bmesh.new() for _ in range(3)]

    # 1. Tall Majestic Fluted Reddish-Brown Trunk (Z = 0.0..15.2m, grounded with flared root buttresses)
    trunk_pts = []
    trunk_rads = []
    n_seg = 12
    for i in range(n_seg + 1):
        u = i / float(n_seg)
        z = u * 15.2
        sx = 0.07 * math.sin(u * math.pi * 1.4)
        sy = 0.05 * math.cos(u * math.pi * 1.1) - 0.05
        flare = 0.32 * math.exp(-u * 9.5)
        r = 0.07 + 0.50 * ((1.0 - u) ** 0.85) + flare
        trunk_pts.append((sx, sy, z))
        trunk_rads.append(r)
    bm_add_spline_tube(bm_bark, trunk_pts, trunk_rads, segs=14, flute_amp=0.10, flute_freq=7)

    # 6 fibrous fluted root buttresses gripping Z = 0.0
    for ri in range(6):
        ra = ri * (2.0 * math.pi / 6.0) + 0.18
        bm_add_spline_tube(
            bm_bark,
            [
                (0.42 * math.cos(ra), 0.42 * math.sin(ra), 1.40),
                (0.76 * math.cos(ra), 0.76 * math.sin(ra), 0.42),
                (1.06 * math.cos(ra), 1.06 * math.sin(ra), 0.00),
            ],
            [0.22, 0.15, 0.07],
            segs=7,
        )

    def add_redwood_bough_fan(bm, p_start, p_end, max_w, thick, droop_amt, rng_local):
        """
        Sculpt a genuine feathery, flattened, gracefully drooping California Coastal Redwood
        needle-bough fan arching outward along a branch arm (zero round mushroom puffs!).
        """
        axis = p_end - p_start
        b_len = axis.length
        if b_len < 0.1:
            return
        fwd = Vector((axis.x, axis.y, 0.0)).normalized()
        side = Vector((-fwd.y, fwd.x, 0.0))
        up = Vector((0.0, 0.0, 1.0))

        # 5 longitudinal ribs along the bough fan (narrow near trunk, broad feathery mid-fan, graceful drooping tip)
        u_steps = [0.0, 0.25, 0.55, 0.82, 1.0]
        w_profile = [0.18, 0.72, 1.00, 0.68, 0.14]
        h_profile = [0.55, 0.95, 1.00, 0.68, 0.22]
        rings = []
        for ui, (u, wp, hp) in enumerate(zip(u_steps, w_profile, h_profile)):
            center = p_start.lerp(p_end, u)
            # Graceful downward Sequoia bough drape with slight upturned airy tip
            center.z += -droop_amt * (u ** 1.65) + 0.08 * math.sin(u * math.pi)
            hw = max_w * wp * rng_local.uniform(0.92, 1.08)
            ht = thick * hp
            # 6-vertex diamond/feathered cross-section with slightly drooping outer frond edges!
            edge_drop = -ht * 0.65 - 0.10 * wp
            pts_ring = [
                center + up * ht,                                   # Top central spine
                center + side * (hw * 0.55) + up * (ht * 0.35),     # Upper-right frond
                center + side * hw + up * edge_drop,                # Outer-right feathery edge
                center - up * (ht * 0.48),                          # Underside spine
                center - side * hw + up * edge_drop,                # Outer-left feathery edge
                center - side * (hw * 0.55) + up * (ht * 0.35),     # Upper-left frond
            ]
            rings.append([bm.verts.new(p) for p in pts_ring])

        segs = 6
        for i in range(len(rings) - 1):
            rA, rB = rings[i], rings[i + 1]
            for s in range(segs):
                ns = (s + 1) % segs
                bm.faces.new((rA[s], rA[ns], rB[ns], rB[s]))
        bm.faces.new(list(reversed(rings[0])))
        bm.faces.new(rings[-1])

    # 2. Tiered Organic Drooping Needle-Bough Clusters (12 ascending graceful Sequoia tiers!)
    n_tiers = 12
    golden_ang = 2.39996
    for ti in range(n_tiers):
        ft = ti / float(n_tiers - 1)  # 0 = lowest wide boughs (Z~3.6m), 1 = upper spire (Z~15.0m)
        z_tier = 3.65 + ft * 11.35
        # Graceful slender California Coastal Redwood silhouette (~6.2m max crown diameter)
        crown_r = (2.85 * ((1.0 - ft) ** 0.78) + 0.42) * (0.90 if ti == 0 else 1.0)
        n_boughs = 7 if ft < 0.60 else (6 if ft < 0.85 else 5)

        for bi in range(n_boughs):
            az = ti * golden_ang + bi * (2.0 * math.pi / n_boughs) + rng.uniform(-0.15, 0.15)
            ca, sa = math.cos(az), math.sin(az)
            b_len = crown_r * rng.uniform(0.86, 1.12)
            # Sweeping woody redwood limb visible beneath the feathery needle spray
            p0 = Vector((0.0, 0.0, z_tier + 0.20))
            p1 = Vector((ca * b_len * 0.48, sa * b_len * 0.48, z_tier - 0.12 * (1.0 - ft * 0.5)))
            p2 = Vector((ca * b_len * 0.90, sa * b_len * 0.90, z_tier - 0.46 * (1.0 - ft * 0.60)))
            b_rad = 0.088 * (1.0 - 0.65 * ft)
            bm_add_spline_tube(bm_bark, [p0, p1, p2], [b_rad, b_rad * 0.56, b_rad * 0.20], segs=6)

            # Main feathery drooping needle-bough fan + 2 subtle angled side sub-fronds!
            tone = 2 if ft > 0.62 else (1 if (bi % 2 == 0 or ft > 0.25) else 0)
            fan_start = p0.lerp(p1, 0.42) + Vector((0, 0, 0.08))
            fan_end = p2 + Vector((ca * 0.36, sa * 0.36, 0.02))
            fan_w = 0.68 + 0.55 * (1.0 - ft)
            fan_h = 0.24 + 0.16 * (1.0 - ft)
            add_redwood_bough_fan(bm_needles[tone], fan_start, fan_end, fan_w, fan_h, 0.44 * (1.0 - ft * 0.5), rng)

            # Layered angled side needle-spray sub-frond for lush organic irregular silhouette
            if ft < 0.82:
                sub_sgn = 1.0 if ((ti + bi) % 2 == 0) else -1.0
                sub_az = az + sub_sgn * 0.46
                s_start = p0.lerp(p1, 0.68) + Vector((0, 0, 0.05))
                s_len = b_len * 0.64
                s_end = s_start + Vector((math.cos(sub_az) * s_len, math.sin(sub_az) * s_len, -0.32 * (1.0 - ft * 0.5)))
                sub_tone = min(2, max(0, tone + (1 if sub_sgn > 0 else -1)))
                add_redwood_bough_fan(bm_needles[sub_tone], s_start, s_end, fan_w * 0.68, fan_h * 0.80, 0.28 * (1.0 - ft * 0.4), rng)

    # Graceful tapered feathered conifer spire crowning the apex at Z = 16.0m!
    for si in range(5):
        s_az = si * 1.256
        add_redwood_bough_fan(
            bm_needles[2],
            Vector((0, 0, 15.15)),
            Vector((math.cos(s_az) * 0.68, math.sin(s_az) * 0.68, 15.35)),
            0.34, 0.18, 0.12, rng,
        )
    bm_add_prism_between(bm_needles[2], (0.0, 0.0, 15.20), (0.0, 0.0, 16.05), 0.28, 0.03, segs=7)

    finalize_mesh("Redwood_FlutedTrunk", bm_bark, mat_bark, smooth=True, uv_scale=0.45)
    for i, nname in enumerate(("Redwood_BoughsDeep", "Redwood_BoughsMid", "Redwood_BoughsSun")):
        finalize_mesh(nname, bm_needles[i], mat_needles[i], smooth=True, uv_scale=0.50)

    return export_asset("prop_redwood_tree.glb", ground_auto=True)


# ===========================================================================
# MAIN BUILD ORCHESTRATOR
# ===========================================================================
BUILDERS = [
    ("landmark_stan_trex.glb",       build_stan_trex),
    ("landmark_b40_partnerplex.glb", build_b40_partnerplex),
    ("landmark_b41.glb",             build_b41),
    ("landmark_b42.glb",             build_b42),
    ("landmark_b43.glb",             build_b43),
    ("landmark_skybridge.glb",       build_skybridge),
    ("landmark_volleyball_court.glb",build_volleyball_court),
    ("landmark_gradient_canopy.glb", build_gradient_canopy),
    ("landmark_orb_plaza.glb",       build_orb_plaza),
    ("prop_umbrella_bistro.glb",     build_umbrella_bistro),
    ("prop_gbike_rack.glb",          build_gbike_rack),
    ("prop_oak_tree.glb",            build_oak_tree),
    ("prop_redwood_tree.glb",        build_redwood_tree),
]


def main():
    t0 = time.time()
    only_filter = None
    if "--" in sys.argv:
        extra = sys.argv[sys.argv.index("--") + 1:]
        if "--only" in extra:
            idx = extra.index("--only")
            if idx + 1 < len(extra):
                only_filter = extra[idx + 1].lower()

    results = []
    for fname, fn in BUILDERS:
        if only_filter and only_filter not in fname.lower():
            continue
        ts = time.time()
        info = fn()
        info["sec"] = time.time() - ts
        results.append(info)
        dx, dy, dz = info["dims"]
        print(
            f"[MAP] {info['file']:32s} | {info['kb']:7.1f} KB | {info['tris']:6d} tris | "
            f"dims(X,Y,Z)=({dx:5.1f}, {dy:5.1f}, {dz:4.1f})m | minZ={info['min_z']:+.3f}m | {info['sec']:.2f}s"
        )

    total_kb = sum(r["kb"] for r in results)
    total_tris = sum(r["tris"] for r in results)
    print("-" * 102)
    print(
        f"[MAP SUMMARY] Built {len(results)}/13 map .glb assets in {time.time() - t0:.2f}s | "
        f"Total: {total_kb / 1024.0:.2f} MB ({total_kb:.1f} KB) | {total_tris:,} tris"
    )


if __name__ == "__main__":
    main()

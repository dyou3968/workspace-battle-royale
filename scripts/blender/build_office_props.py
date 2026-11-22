#!/usr/bin/env python3
"""
Workspace Royale — Modular Googleplex Office Interior Furniture Props (Blender 5.3.0)
=====================================================================================
Generates 5 modular high-detail PBR office furniture `.glb` sets into `public/assets/map/`:
  1. prop_desk_pod.glb        — 4-seat Google SWE standing workstation cluster (~3.6m x 2.4m x 1.18m)
  2. prop_conference_pod.glb  — Google glass-and-timber conference pod w/ Meet display (~5.4m x 3.2m x 2.52m)
  3. prop_microkitchen_bar.glb— Googleplex Microkitchen & Charlie's Café L-bar + cooler (~5.0m x 2.4m x 2.08m)
  4. prop_lounge_nook.glb     — Google-accented modular L-sofa lounge + ficus tree (~4.2m x 3.4m x 2.25m)
  5. prop_whiteboard_wall.glb — Mobile engineering whiteboard + indoor planter divider (~2.6m x 0.8m x 1.85m)

Usage:
    blender --background --python scripts/blender/build_office_props.py
"""

import math
import os
import sys
import time
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Euler, Matrix, Vector

# ---------------------------------------------------------------------------
# Paths & Palette
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
OUT_DIR = PROJECT_ROOT / "public" / "assets" / "map"
OUT_DIR.mkdir(parents=True, exist_ok=True)

G_BLUE = "#4285F4"
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
    return (int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0)


def hex_to_linear(h, alpha=1.0):
    r, g, b = hex_to_srgb(h)
    return srgb_to_linear((r, g, b, alpha))


# ---------------------------------------------------------------------------
# Scene & Procedural Texture Utilities
# ---------------------------------------------------------------------------
def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0


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


def make_packed_image(name, rgb_top_down_srgb):
    """Create a packed sRGB Blender image from (H, W, 3) top-down numpy array."""
    h, w = rgb_top_down_srgb.shape[:2]
    rgba = np.ones((h, w, 4), dtype=np.float32)
    rgba[:, :, :3] = np.clip(rgb_top_down_srgb[::-1, :, :], 0.0, 1.0)
    img = bpy.data.images.new(name=name, width=w, height=h, alpha=False)
    img.colorspace_settings.name = "sRGB"
    img.pixels.foreach_set(rgba.ravel())
    img.pack()
    return img


def gen_wood_tex(name, tint=(0.82, 0.67, 0.46), size=128, seed=10):
    rng = np.random.default_rng(seed)
    n1 = _value_noise_2d(size, size, 12, 4, rng)
    n2 = _value_noise_2d(size, size, 32, 8, rng)
    yy = np.arange(size, dtype=np.float32)[:, None]
    grain = np.sin(yy * 0.45 + n1 * 7.5) * 0.5 + 0.5
    v = 0.88 + 0.14 * grain + 0.07 * (n2 - 0.5)
    rgb = np.stack([v * tint[0], v * tint[1], v * tint[2]], axis=-1)
    return make_packed_image(name, rgb)


def gen_marble_tex(name="TexCarraraMarble", size=128, seed=21):
    rng = np.random.default_rng(seed)
    n1 = _value_noise_2d(size, size, 6, 6, rng)
    n2 = _value_noise_2d(size, size, 16, 16, rng)
    yy, xx = np.mgrid[0:size, 0:size]
    vein = np.abs(np.sin((xx * 0.08 + yy * 0.06) + n1 * 5.2 + n2 * 2.4))
    vein_mask = np.clip((0.16 - vein) / 0.16, 0.0, 1.0) ** 1.6
    r = 0.94 - 0.17 * vein_mask - 0.02 * n2
    g = 0.94 - 0.16 * vein_mask - 0.02 * n2
    b = 0.93 - 0.14 * vein_mask - 0.01 * n2
    return make_packed_image(name, np.stack([r, g, b], axis=-1))


def gen_woven_rug_tex(name="TexWovenRug", base_a=(0.83, 0.80, 0.74), base_b=(0.72, 0.70, 0.65), size=128, seed=31):
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:size, 0:size]
    weave = (((xx // 2) + (yy // 2)) % 2).astype(np.float32)
    stripe = ((yy % 16) < 2).astype(np.float32) * 0.45
    noise = rng.normal(0.0, 0.02, (size, size)).astype(np.float32)
    t = np.clip(0.35 * weave + stripe + noise, 0.0, 1.0)
    rgb = np.zeros((size, size, 3), dtype=np.float32)
    for c in range(3):
        rgb[:, :, c] = base_a[c] * (1.0 - t) + base_b[c] * t
    # Subtle outer woven border frame
    border = (xx < 6) | (xx >= size - 6) | (yy < 6) | (yy >= size - 6)
    rgb[border] *= 0.86
    return make_packed_image(name, rgb)


def gen_swe_code_screen_tex(name="TexSWEMonitor", w=192, h=96, seed=41):
    """Crisp dark-mode Google SWE ultrawide IDE + Workspace sidebar screen texture."""
    rng = np.random.default_rng(seed)
    img = np.zeros((h, w, 3), dtype=np.float32)
    img[:, :] = (0.09, 0.11, 0.15)  # Dark IDE slate background

    # Top Workspace / Chrome bar
    img[0:10, :] = (0.14, 0.17, 0.23)
    # 4 Google color status tabs in top bar
    tab_cols = [hex_to_srgb(G_BLUE), hex_to_srgb(G_RED), hex_to_srgb(G_YELLOW), hex_to_srgb(G_GREEN)]
    for i, col in enumerate(tab_cols):
        img[2:8, 6 + i * 16:19 + i * 16] = col

    # Left file-tree sidebar
    img[10:, 0:34] = (0.11, 0.14, 0.19)
    for row in range(14, h - 6, 7):
        lw = int(rng.integers(12, 26))
        img[row:row + 3, 5:5 + lw] = (0.34, 0.42, 0.56)

    # Center code editor pane (syntax-highlighted lines!)
    code_cols = [
        (0.42, 0.72, 0.98),  # blue keywords
        (0.48, 0.86, 0.58),  # green strings
        (0.98, 0.78, 0.34),  # yellow symbols
        (0.84, 0.88, 0.94),  # white identifiers
        (0.95, 0.48, 0.46),  # coral highlights
    ]
    for row in range(15, h - 8, 6):
        indent = int(rng.integers(0, 4)) * 6
        x = 40 + indent
        for _ in range(int(rng.integers(2, 5))):
            seg = int(rng.integers(8, 22))
            if x + seg >= 134:
                break
            img[row:row + 3, x:x + seg] = code_cols[int(rng.integers(0, len(code_cols)))]
            x += seg + 4

    # Right Google Workspace / Docs preview card pane
    img[12:h - 6, 140:w - 6] = (0.93, 0.95, 0.98)
    img[15:23, 144:w - 10] = hex_to_srgb(G_BLUE)
    for row in range(28, h - 12, 7):
        lw = int(rng.integers(20, 40))
        img[row:row + 3, 144:min(w - 10, 144 + lw)] = (0.28, 0.34, 0.44)
    # Small green chart widget at bottom right
    img[h - 26:h - 10, 146:162] = hex_to_srgb(G_GREEN)
    img[h - 22:h - 10, 165:180] = hex_to_srgb(G_YELLOW)
    return make_packed_image(name, img)


def gen_google_meet_screen_tex(name="TexGoogleMeet", w=224, h=128):
    """Vibrant Google Meet conference room wall display texture (4-tile call + Workspace bar)."""
    img = np.zeros((h, w, 3), dtype=np.float32)
    img[:, :] = (0.11, 0.13, 0.17)  # Dark Google Meet studio backdrop

    # Top title bar with Google 4-color accent bar
    img[0:12, :] = (0.15, 0.18, 0.23)
    for i, hx in enumerate((G_BLUE, G_RED, G_YELLOW, G_GREEN)):
        img[3:9, 8 + i * 10:15 + i * 10] = hex_to_srgb(hx)
    img[4:8, 56:132] = (0.76, 0.82, 0.90)

    # 2x2 Participant video tiles + right shared presentation slide
    tiles = [
        (16, 60, 10, 74, (0.20, 0.32, 0.50), hex_to_srgb(G_BLUE)),
        (16, 60, 78, 142, (0.22, 0.36, 0.30), hex_to_srgb(G_GREEN)),
        (64, 108, 10, 74, (0.38, 0.25, 0.24), hex_to_srgb(G_RED)),
        (64, 108, 78, 142, (0.36, 0.32, 0.20), hex_to_srgb(G_YELLOW)),
    ]
    yy, xx = np.mgrid[0:h, 0:w]
    for y0, y1, x0, x1, bg, shirt in tiles:
        img[y0:y1, x0:x1] = bg
        cx = 0.5 * (x0 + x1)
        cy = y0 + (y1 - y0) * 0.42
        # Stylized participant avatar silhouette (head + shoulders)
        head = ((xx - cx) ** 2 + (yy - cy) ** 2) <= 7.5 ** 2
        body = (((xx - cx) / 14.0) ** 2 + ((yy - (y1 - 2.0)) / 13.0) ** 2) <= 1.0
        tile_mask = (yy >= y0) & (yy < y1) & (xx >= x0) & (xx < x1)
        img[body & tile_mask] = shirt
        img[head & tile_mask] = (0.90, 0.77, 0.66)
        # Subtle name pill at lower-left
        img[y1 - 7:y1 - 3, x0 + 4:x0 + 24] = (0.08, 0.10, 0.14)

    # Right-side Workspace Presentation Slide card
    img[16:108, 148:w - 10] = (0.96, 0.97, 0.99)
    img[16:28, 148:w - 10] = hex_to_srgb(G_BLUE)
    img[34:40, 154:w - 18] = (0.22, 0.26, 0.34)
    # Mini bar chart on slide
    bars = [(156, 36, G_BLUE), (170, 48, G_RED), (184, 30, G_YELLOW), (198, 54, G_GREEN)]
    for bx, bh, hx in bars:
        img[100 - bh:100, bx:bx + 9] = hex_to_srgb(hx)

    # Bottom Google Meet control pill bar (mic, cam, share, red hang-up button)
    img[113:124, :] = (0.14, 0.16, 0.20)
    for cx_b, col_b in ((88, (0.28, 0.32, 0.38)), (102, (0.28, 0.32, 0.38)), (116, hex_to_srgb(G_BLUE)), (134, hex_to_srgb(G_RED))):
        btn = ((xx - cx_b) ** 2 + (yy - 118.5) ** 2) <= 4.0 ** 2
        img[btn] = col_b

    return make_packed_image(name, img)


def gen_whiteboard_sticky_tex(name="TexWhiteboardNotes", w=224, h=160, seed=55):
    """Crisp glass engineering whiteboard with sprint architecture diagram & colorful sticky notes."""
    rng = np.random.default_rng(seed)
    img = np.ones((h, w, 3), dtype=np.float32) * np.array([0.95, 0.96, 0.97], dtype=np.float32)

    # Subtle architectural grid dots
    img[10::14, 10::14] = (0.86, 0.89, 0.92)

    # Top Kanban column headers & divider lines
    img[22:24, 10:w - 10] = (0.30, 0.36, 0.44)
    img[12:148, 76:78] = (0.78, 0.82, 0.86)
    img[12:148, 148:150] = (0.78, 0.82, 0.86)

    # Header titles (marker bars)
    img[12:17, 18:62] = hex_to_srgb(G_BLUE)
    img[12:17, 88:138] = hex_to_srgb(G_RED)
    img[12:17, 158:208] = hex_to_srgb(G_GREEN)

    # Colorful square sticky notes across the left & center sprint columns!
    note_palette = [
        (0.99, 0.84, 0.22),  # sunny yellow
        (0.35, 0.66, 0.98),  # google sky blue
        (0.96, 0.44, 0.40),  # coral red
        (0.36, 0.82, 0.50),  # mint green
        (0.99, 0.68, 0.28),  # amber orange
    ]
    sticky_spots = [
        (30, 14), (32, 44), (58, 18), (60, 46), (88, 15), (90, 45), (118, 22),
        (30, 86), (31, 116), (60, 88), (62, 118), (92, 92), (118, 112),
    ]
    for idx, (ny, nx) in enumerate(sticky_spots):
        col = note_palette[idx % len(note_palette)]
        sz = 20
        # Subtle drop shadow
        img[ny + 2:ny + sz + 2, nx + 2:nx + sz + 2] = (0.82, 0.84, 0.87)
        # Main sticky note body
        img[ny:ny + sz, nx:nx + sz] = col
        # Marker scribble lines on sticky note
        img[ny + 5:ny + 7, nx + 3:nx + sz - 4] = (0.20, 0.22, 0.26)
        img[ny + 10:ny + 12, nx + 3:nx + sz - 7] = (0.24, 0.26, 0.30)

    # Right column: Systems architecture block diagram (boxes + marker arrows!)
    boxes = [
        (34, 54, 160, 206, hex_to_srgb(G_BLUE)),
        (72, 94, 156, 184, hex_to_srgb(G_GREEN)),
        (72, 94, 190, 214, hex_to_srgb(G_RED)),
        (114, 138, 162, 208, (0.22, 0.28, 0.38)),
    ]
    for y0, y1, x0, x1, col in boxes:
        img[y0:y0 + 3, x0:x1] = col
        img[y1 - 3:y1, x0:x1] = col
        img[y0:y1, x0:x0 + 3] = col
        img[y0:y1, x1 - 3:x1] = col
        img[y0 + 7:y0 + 10, x0 + 6:x1 - 6] = col
    # Vertical marker connector arrows between architecture boxes
    img[54:72, 170:173] = (0.22, 0.26, 0.32)
    img[54:72, 198:201] = (0.22, 0.26, 0.32)
    img[94:114, 183:186] = (0.22, 0.26, 0.32)

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
    emission_tex=False,
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


# ---------------------------------------------------------------------------
# Compact BMesh Builders
# ---------------------------------------------------------------------------
def apply_box_uv(bm, scale=0.6):
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


def finalize_mesh(name, bm, mat, smooth=False, uv_scale=0.6, keep_uv=False):
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
    bpy.context.collection.objects.link(obj)
    if mat is not None:
        obj.data.materials.append(mat)
    return obj


def bm_add_box(bm, center, size, rot_euler=(0.0, 0.0, 0.0), bevel=0.0, bevel_segs=1):
    sx, sy, sz = size
    mat = Matrix.Translation(Vector(center)) @ Euler(rot_euler, "XYZ").to_matrix().to_4x4() @ Matrix.Diagonal((sx, sy, sz, 1.0))
    res = bmesh.ops.create_cube(bm, size=1.0, matrix=mat)
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
    return verts


def bm_add_prism(bm, p0, p1, r0, r1, segs=10, cap=True):
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
        a = 2.0 * math.pi * i / segs
        d = x_dir * math.cos(a) + y_dir * math.sin(a)
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


def bm_add_torus(bm, center, major_r, minor_r, rot_euler=(0.0, 0.0, 0.0), major_segs=18, minor_segs=6):
    xform = Matrix.Translation(Vector(center)) @ Euler(rot_euler, "XYZ").to_matrix().to_4x4()
    rings = []
    for i in range(major_segs):
        th = 2.0 * math.pi * i / major_segs
        ct, st = math.cos(th), math.sin(th)
        ring = []
        for j in range(minor_segs):
            ph = 2.0 * math.pi * j / minor_segs
            r = major_r + minor_r * math.cos(ph)
            ring.append(bm.verts.new(xform @ Vector((r * ct, r * st, minor_r * math.sin(ph)))))
        rings.append(ring)
    for i in range(major_segs):
        ni = (i + 1) % major_segs
        for j in range(minor_segs):
            nj = (j + 1) % minor_segs
            bm.faces.new((rings[i][j], rings[ni][j], rings[ni][nj], rings[i][nj]))


def bm_add_uv_quad(bm, corners):
    """Add a single UV-mapped quad (BL, BR, TR, TL) to bm."""
    uv_layer = bm.loops.layers.uv.verify()
    verts = [bm.verts.new(Vector(c)) for c in corners]
    f = bm.faces.new(verts)
    uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    for lp, uv in zip(f.loops, uvs):
        lp[uv_layer].uv = uv
    return f


def bm_add_organic_foliage(bm, center, rx, ry, rz, subdiv=1, seed=0, crinkle=0.22):
    rng = np.random.default_rng(seed)
    res = bmesh.ops.create_icosphere(bm, subdivisions=subdiv, radius=1.0)
    verts = res["verts"]
    p1 = rng.uniform(0.0, 6.28, 3)
    cx, cy, cz = center
    for v in verts:
        x, y, z = v.co.x, v.co.y, v.co.z
        lobe = math.sin(x * 3.4 + p1[0]) * math.cos(y * 3.2 + p1[1]) * 0.65 + math.cos(z * 5.0 + p1[2]) * 0.35
        sc = 1.0 + crinkle * lobe
        v.co = Vector((cx + x * rx * sc, cy + y * ry * sc, cz + z * rz * sc))
    return verts


def bm_add_stadium_slab(bm, center, length_x, width_y, height_z, segs=18):
    """Rounded stadium / oval slab (great for modern Google conference & coffee tables)."""
    cx, cy, cz = center
    r = width_y * 0.5
    straight = max(0.0, length_x - width_y)
    hs = straight * 0.5
    pts = []
    half_s = segs // 2
    for i in range(half_s + 1):
        a = -math.pi * 0.5 + math.pi * (i / float(half_s))
        pts.append((cx + hs + r * math.cos(a), cy + r * math.sin(a)))
    for i in range(half_s + 1):
        a = math.pi * 0.5 + math.pi * (i / float(half_s))
        pts.append((cx - hs + r * math.cos(a), cy + r * math.sin(a)))
    z0, z1 = cz - height_z * 0.5, cz + height_z * 0.5
    bot = [bm.verts.new((x, y, z0)) for x, y in pts]
    top = [bm.verts.new((x, y, z1)) for x, y in pts]
    n = len(pts)
    for i in range(n):
        ni = (i + 1) % n
        bm.faces.new((bot[i], bot[ni], top[ni], top[i]))
    f_b = bm.faces.new(list(reversed(bot)))
    f_t = bm.faces.new(top)
    bmesh.ops.triangulate(bm, faces=[f_b, f_t], quad_method="BEAUTY", ngon_method="EAR_CLIP")


def export_prop(filename, center_xy=True, ground_z=True):
    objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not objs:
        raise RuntimeError(f"No mesh objects for {filename}")

    def calc_bounds():
        mn = Vector((1e9, 1e9, 1e9))
        mx = Vector((-1e9, -1e9, -1e9))
        tris = 0
        for o in objs:
            m = o.matrix_world
            for v in o.data.vertices:
                w = m @ v.co
                mn.x, mn.y, mn.z = min(mn.x, w.x), min(mn.y, w.y), min(mn.z, w.z)
                mx.x, mx.y, mx.z = max(mx.x, w.x), max(mx.y, w.y), max(mx.z, w.z)
            for p in o.data.polygons:
                tris += max(1, len(p.vertices) - 2)
        return mn, mx, tris

    mn, mx, tris = calc_bounds()
    dx = -0.5 * (mn.x + mx.x) if center_xy else 0.0
    dy = -0.5 * (mn.y + mx.y) if center_xy else 0.0
    dz = -mn.z if ground_z else 0.0
    if abs(dx) > 1e-4 or abs(dy) > 1e-4 or abs(dz) > 1e-4:
        shift = Vector((dx, dy, dz))
        for o in objs:
            o.location += shift
        bpy.context.view_layer.update()
        mn, mx, tris = calc_bounds()

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
    dims = mx - mn
    return {
        "file": filename,
        "kb": out_path.stat().st_size / 1024.0,
        "tris": tris,
        "dims": (dims.x, dims.y, dims.z),
        "min_z": mn.z,
        "max_z": mx.z,
    }


# ---------------------------------------------------------------------------
# Shared Office Chair Helper
# ---------------------------------------------------------------------------
def add_ergonomic_office_chair(bm_frame, bm_seat, bm_mesh_back, pos_xy, yaw):
    """Add a sculpted 5-star Google ergonomic mesh office chair grounded cleanly at Z=0."""
    cx, cy = pos_xy
    rot_m = Matrix.Translation((cx, cy, 0.0)) @ Euler((0.0, 0.0, yaw), "XYZ").to_matrix().to_4x4()

    def p(x, y, z):
        return rot_m @ Vector((x, y, z))

    # 5-star caster wheelbase (grounded Z = 0.0..0.11m)
    for k in range(5):
        ang = k * (2.0 * math.pi / 5.0) + 0.3
        tip_x, tip_y = 0.27 * math.cos(ang), 0.27 * math.sin(ang)
        bm_add_prism(bm_frame, p(0.0, 0.0, 0.11), p(tip_x, tip_y, 0.052), 0.019, 0.014, segs=5, cap=False)
        bm_add_prism(bm_frame, p(tip_x, tip_y, 0.0), p(tip_x, tip_y, 0.052), 0.022, 0.022, segs=5, cap=True)
    # Central pneumatic gas cylinder + tilt mechanism
    bm_add_prism(bm_frame, p(0.0, 0.0, 0.09), p(0.0, 0.0, 0.43), 0.028, 0.024, segs=6, cap=False)
    bm_add_box(bm_frame, p(0.0, 0.0, 0.43), (0.18, 0.20, 0.05), rot_euler=(0, 0, yaw))

    # Contoured ergonomic seat cushion (Z = 0.45..0.51m)
    bm_add_box(bm_seat, p(0.0, 0.02, 0.475), (0.46, 0.44, 0.065), rot_euler=(0, 0, yaw), bevel=0.018, bevel_segs=1)

    # T-armrests
    for sgn in (-1.0, 1.0):
        bm_add_prism(bm_frame, p(sgn * 0.21, -0.02, 0.44), p(sgn * 0.26, -0.02, 0.65), 0.015, 0.014, segs=5, cap=False)
        bm_add_box(bm_frame, p(sgn * 0.26, 0.02, 0.66), (0.065, 0.24, 0.028), rot_euler=(0, 0, yaw))

    # Curved spine upright & breathable mesh lumbar backrest (Z = 0.50..0.98m, facing +Y)
    bm_add_prism(bm_frame, p(0.0, -0.18, 0.44), p(0.0, -0.23, 0.72), 0.022, 0.018, segs=5, cap=False)
    for sgn in (-1.0, 1.0):
        bm_add_prism(bm_frame, p(sgn * 0.20, -0.21, 0.54), p(sgn * 0.21, -0.25, 0.96), 0.014, 0.013, segs=5, cap=False)
    bm_add_prism(bm_frame, p(-0.21, -0.25, 0.96), p(0.21, -0.25, 0.96), 0.014, 0.014, segs=5, cap=False)
    bm_add_box(bm_mesh_back, p(0.0, -0.225, 0.75), (0.40, 0.036, 0.42), rot_euler=(-0.10, 0.0, yaw))


# ===========================================================================
# 1. PROP: 4-SEAT GOOGLE SWE DESK POD (prop_desk_pod.glb, ~3.6m x 2.4m x 1.18m)
# ===========================================================================
def build_desk_pod():
    reset_scene()

    tex_birch = gen_wood_tex("Desk_BirchTex", tint=(0.88, 0.76, 0.58), size=128, seed=101)
    tex_screen = gen_swe_code_screen_tex("Desk_SWEScreenTex", w=192, h=96, seed=102)

    mat_birch = make_pbr_mat("Desk_BirchTop", base_color=hex_to_linear("#E4C89E"), roughness=0.52, tex_img=tex_birch)
    mat_white_steel = make_pbr_mat("Desk_WhiteSteel", base_color=hex_to_linear("#ECEFF4"), metallic=0.28, roughness=0.36)
    mat_dark_steel = make_pbr_mat("Desk_DarkSteel", base_color=hex_to_linear("#262D37"), metallic=0.65, roughness=0.38)
    mat_alum = make_pbr_mat("Desk_Aluminum", base_color=hex_to_linear("#C8D0DA"), metallic=0.84, roughness=0.24)
    mat_felt = make_pbr_mat("Desk_AcousticFelt", base_color=hex_to_linear("#3B6CB7"), roughness=0.92)
    mat_screen = make_pbr_mat("Desk_MonitorScreen", base_color=(1, 1, 1, 1), roughness=0.14, tex_img=tex_screen, emission_tex=True, emission_strength=0.85)
    mat_chair_seat = make_pbr_mat("Desk_ChairFabric", base_color=hex_to_linear("#343C4A"), roughness=0.85)
    mat_chair_mesh = make_pbr_mat("Desk_ChairMesh", base_color=hex_to_linear("#4B5565"), roughness=0.80)
    mat_mugs = [
        make_pbr_mat("Desk_MugBlue", base_color=hex_to_linear(G_BLUE), roughness=0.28),
        make_pbr_mat("Desk_MugRed", base_color=hex_to_linear(G_RED), roughness=0.28),
        make_pbr_mat("Desk_MugYellow", base_color=hex_to_linear(G_YELLOW), roughness=0.28),
        make_pbr_mat("Desk_MugGreen", base_color=hex_to_linear(G_GREEN), roughness=0.28),
    ]

    bm_birch = bmesh.new()
    bm_white = bmesh.new()
    bm_dark = bmesh.new()
    bm_alum = bmesh.new()
    bm_felt = bmesh.new()
    bm_screen = bmesh.new()
    bm_seat = bmesh.new()
    bm_mesh = bmesh.new()
    bm_mugs = [bmesh.new() for _ in range(4)]

    # 4 back-to-back Google standing desks (2 north facing +Y, 2 south facing -Y)
    # Total desk footprint: 3.52m (X) x 1.62m (Y), chairs extend to Y = +-1.20m -> ~3.6m x 2.4m
    desk_w, desk_d = 1.72, 0.78
    desk_z = 0.75
    workstations = [
        (-0.88,  0.42,  1.0, 0),  # NW
        ( 0.88,  0.42,  1.0, 1),  # NE
        (-0.88, -0.42, -1.0, 2),  # SW
        ( 0.88, -0.42, -1.0, 3),  # SE
    ]

    for wx, wy, face_y, idx in workstations:
        # Warm birch beveled desktop slab
        bm_add_box(bm_birch, (wx, wy, desk_z - 0.018), (desk_w, desk_d, 0.036), bevel=0.008)
        # White powder-coated sit-stand T-legs + horizontal foot rails grounded at Z=0
        for lsgn in (-1.0, 1.0):
            lx = wx + lsgn * (desk_w * 0.43)
            bm_add_box(bm_white, (lx, wy, 0.022), (0.065, desk_d * 0.82, 0.044))
            bm_add_box(bm_white, (lx, wy, desk_z * 0.5), (0.070, 0.075, desk_z - 0.05))
        # Under-desk cable management tray
        bm_add_box(bm_white, (wx, wy - face_y * 0.24, desk_z - 0.09), (desk_w * 0.80, 0.14, 0.08))

        # Desk mat + mechanical keyboard + mouse
        bm_add_box(bm_dark, (wx, wy + face_y * 0.15, desk_z + 0.004), (0.76, 0.30, 0.008))
        bm_add_box(bm_white, (wx - 0.06 * face_y, wy + face_y * 0.16, desk_z + 0.016), (0.38, 0.13, 0.018))
        bm_add_box(bm_dark, (wx + 0.22 * face_y, wy + face_y * 0.16, desk_z + 0.015), (0.065, 0.105, 0.024))

        # Google-colored ceramic coffee mug on desk corner
        mx = wx + (0.58 if idx % 2 == 0 else -0.58)
        my = wy + face_y * 0.20
        bm_add_prism(bm_mugs[idx], (mx, my, desk_z), (mx, my, desk_z + 0.095), 0.038, 0.041, segs=8)

        # Articulated aluminum monitor arm + Curved 34" Ultrawide Monitor (top Z ~ 1.18m)
        arm_y = wy - face_y * 0.28
        bm_add_prism(bm_alum, (wx, arm_y, desk_z), (wx, arm_y, desk_z + 0.26), 0.020, 0.018, segs=6, cap=False)
        bm_add_prism(bm_alum, (wx, arm_y, desk_z + 0.25), (wx, arm_y + face_y * 0.10, desk_z + 0.26), 0.016, 0.016, segs=6, cap=False)

        # Curved 3-panel ultrawide monitor shell & glowing UV-mapped screen!
        mon_y = wy - face_y * 0.15
        mon_z = desk_z + 0.255  # Center Z = 1.005m, Height 0.35m -> top Z = 1.18m
        mon_h = 0.345
        seg_w = 0.275
        uv_layer = bm_screen.loops.layers.uv.verify()
        for seg_i, (off_x, off_y, yaw_m, u0, u1) in enumerate((
            (-seg_w * 0.96,  0.032,  0.22 * face_y, 0.0, 0.333),
            ( 0.0,           0.000,  0.0,           0.333, 0.667),
            ( seg_w * 0.96,  0.032, -0.22 * face_y, 0.667, 1.0),
        )):
            # Screen flips X order when facing -Y so text reads naturally
            cx_m = wx + off_x
            cy_m = mon_y + off_y * face_y
            bm_add_box(bm_dark, (cx_m, cy_m, mon_z), (seg_w + 0.01, 0.026, mon_h + 0.022), rot_euler=(0, 0, yaw_m))
            # Glowing screen quad slightly proud on front face
            rot_m = Euler((0, 0, yaw_m), "XYZ").to_matrix()
            c_vec = Vector((cx_m, cy_m, mon_z))
            hw = seg_w * 0.49
            hh = mon_h * 0.46
            fn = face_y * 0.015
            if face_y > 0:
                quad_pts = [
                    c_vec + rot_m @ Vector((-hw, fn, -hh)),
                    c_vec + rot_m @ Vector(( hw, fn, -hh)),
                    c_vec + rot_m @ Vector(( hw, fn,  hh)),
                    c_vec + rot_m @ Vector((-hw, fn,  hh)),
                ]
                uvs = [(u0, 0.0), (u1, 0.0), (u1, 1.0), (u0, 1.0)]
            else:
                quad_pts = [
                    c_vec + rot_m @ Vector(( hw, fn, -hh)),
                    c_vec + rot_m @ Vector((-hw, fn, -hh)),
                    c_vec + rot_m @ Vector((-hw, fn,  hh)),
                    c_vec + rot_m @ Vector(( hw, fn,  hh)),
                ]
                uvs = [(1.0 - u1, 0.0), (1.0 - u0, 0.0), (1.0 - u0, 1.0), (1.0 - u1, 1.0)]
            f = bm_screen.faces.new([bm_screen.verts.new(pt) for pt in quad_pts])
            for lp, uv in zip(f.loops, uvs):
                lp[uv_layer].uv = uv

        # Ergonomic mesh chair positioned naturally at each workstation
        chair_yaw = (math.pi if face_y > 0 else 0.0) + (0.10 if idx % 2 == 0 else -0.14)
        chair_x = wx + (0.04 if idx % 2 == 0 else -0.05)
        chair_y = wy + face_y * 0.56
        add_ergonomic_office_chair(bm_dark, bm_seat, bm_mesh, (chair_x, chair_y), chair_yaw)

    # Low Acoustic Felt Privacy Dividers (spine along X + cross divider along Y, Z = 0.72..1.09m)
    bm_add_box(bm_felt, (0.0, 0.0, 0.91), (3.46, 0.045, 0.36), bevel=0.010)
    bm_add_box(bm_birch, (0.0, 0.0, 1.095), (3.48, 0.056, 0.022), bevel=0.005)
    bm_add_box(bm_felt, (0.0, 0.0, 0.90), (0.042, 1.56, 0.34), bevel=0.010)
    bm_add_box(bm_birch, (0.0, 0.0, 1.075), (0.054, 1.58, 0.020), bevel=0.005)
    # Brushed aluminum desk divider clamp brackets
    for bx in (-1.45, -0.42, 0.42, 1.45):
        bm_add_box(bm_alum, (bx, 0.0, 0.755), (0.06, 0.09, 0.05))

    finalize_mesh("DeskPod_BirchTops", bm_birch, mat_birch, smooth=False, uv_scale=0.65)
    finalize_mesh("DeskPod_WhiteFrames", bm_white, mat_white_steel, smooth=False)
    finalize_mesh("DeskPod_DarkMetal", bm_dark, mat_dark_steel, smooth=False)
    finalize_mesh("DeskPod_Aluminum", bm_alum, mat_alum, smooth=True)
    finalize_mesh("DeskPod_AcousticFelt", bm_felt, mat_felt, smooth=False)
    finalize_mesh("DeskPod_SWEScreens", bm_screen, mat_screen, smooth=False, keep_uv=True)
    finalize_mesh("DeskPod_ChairSeats", bm_seat, mat_chair_seat, smooth=True)
    finalize_mesh("DeskPod_ChairMesh", bm_mesh, mat_chair_mesh, smooth=True)
    for i, cname in enumerate(("Blue", "Red", "Yellow", "Green")):
        finalize_mesh(f"DeskPod_Mug{cname}", bm_mugs[i], mat_mugs[i], smooth=True)

    return export_prop("prop_desk_pod.glb")


# ===========================================================================
# 2. PROP: GOOGLE CONFERENCE POD (prop_conference_pod.glb, ~5.4m x 3.2m x 2.52m)
# ===========================================================================
def build_conference_pod():
    reset_scene()

    tex_birch = gen_wood_tex("Conf_BirchTex", tint=(0.86, 0.72, 0.52), size=128, seed=201)
    tex_cedar = gen_wood_tex("Conf_CedarTex", tint=(0.72, 0.44, 0.24), size=128, seed=202)
    tex_rug = gen_woven_rug_tex("Conf_RugTex", base_a=(0.32, 0.35, 0.40), base_b=(0.25, 0.28, 0.33), size=128, seed=203)
    tex_meet = gen_google_meet_screen_tex("Conf_MeetTex", w=224, h=128)

    mat_birch = make_pbr_mat("Conf_BirchTable", base_color=hex_to_linear("#E0C090"), roughness=0.48, tex_img=tex_birch)
    mat_cedar = make_pbr_mat("Conf_CedarSlats", base_color=hex_to_linear("#B36D3E"), roughness=0.62, tex_img=tex_cedar)
    mat_rug = make_pbr_mat("Conf_AreaRug", base_color=(1, 1, 1, 1), roughness=0.94, tex_img=tex_rug)
    mat_dark = make_pbr_mat("Conf_DarkSteel", base_color=hex_to_linear("#232933"), metallic=0.72, roughness=0.35)
    mat_alum = make_pbr_mat("Conf_Aluminum", base_color=hex_to_linear("#C4CCD6"), metallic=0.84, roughness=0.25)
    mat_glass = make_pbr_mat("Conf_PartitionGlass", base_color=hex_to_linear("#8AD0FA", alpha=0.30), metallic=0.18, roughness=0.06, alpha=0.30, double_sided=True)
    mat_meet = make_pbr_mat("Conf_MeetDisplay", base_color=(1, 1, 1, 1), roughness=0.12, tex_img=tex_meet, emission_tex=True, emission_strength=0.95)
    mat_shell = make_pbr_mat("Conf_ChairShell", base_color=hex_to_linear("#E8ECEF"), roughness=0.44)
    mat_pad = make_pbr_mat("Conf_ChairPad", base_color=hex_to_linear("#356AC3"), roughness=0.84)
    mat_cyan = make_pbr_mat("Conf_MeetGlow", base_color=hex_to_linear("#38BDF8"), roughness=0.2, emission=hex_to_linear("#38BDF8"), emission_strength=2.2)

    bm_birch = bmesh.new()
    bm_cedar = bmesh.new()
    bm_rug = bmesh.new()
    bm_dark = bmesh.new()
    bm_alum = bmesh.new()
    bm_glass = bmesh.new()
    bm_meet = bmesh.new()
    bm_shell = bmesh.new()
    bm_pad = bmesh.new()
    bm_cyan = bmesh.new()

    # 1. Woven Charcoal Conference Area Rug (5.30m x 3.12m, Z = 0.00..0.022m)
    bm_add_box(bm_rug, (0.0, 0.0, 0.011), (5.30, 3.12, 0.022), bevel=0.006)

    # 2. Oval/Stadium Birch Conference Table (3.32m x 1.38m, top Z = 0.75m, shifted +X to face Meet wall)
    tx = 0.56
    bm_add_stadium_slab(bm_birch, (tx, 0.0, 0.73), 3.32, 1.38, 0.044, segs=22)
    # Recessed brushed-aluminum center cable/power dock
    bm_add_box(bm_alum, (tx, 0.0, 0.754), (1.35, 0.16, 0.008))
    # Twin sculpted A-frame architectural steel table bases
    for px in (tx - 0.96, tx + 0.96):
        bm_add_box(bm_dark, (px, 0.0, 0.036), (0.14, 0.96, 0.034), bevel=0.006)
        for sgn in (-1.0, 1.0):
            bm_add_prism(bm_dark, (px, sgn * 0.42, 0.04), (px, sgn * 0.24, 0.71), 0.036, 0.032, segs=8)
        bm_add_box(bm_dark, (px, 0.0, 0.69), (0.12, 0.66, 0.045))
    bm_add_box(bm_dark, (tx, 0.0, 0.68), (1.92, 0.09, 0.055))

    # Tabletop Google Meet Speakerphone Puck + 2 sleek open aluminum laptops
    bm_add_prism(bm_dark, (tx - 0.38, 0.0, 0.752), (tx - 0.38, 0.0, 0.788), 0.095, 0.088, segs=14)
    bm_add_torus(bm_cyan, (tx - 0.38, 0.0, 0.788), 0.072, 0.007, major_segs=14, minor_segs=5)
    for lx, ly, lyaw in ((tx + 0.45, 0.36, -2.8), (tx - 0.72, -0.34, 0.35)):
        lm = Matrix.Translation((lx, ly, 0.758)) @ Euler((0, 0, lyaw), "XYZ").to_matrix().to_4x4()
        bm_add_box(bm_alum, lm @ Vector((0.0, 0.0, 0.006)), (0.31, 0.22, 0.012), rot_euler=(0, 0, lyaw))
        bm_add_box(bm_alum, lm @ Vector((0.0, -0.11, 0.11)), (0.31, 0.010, 0.21), rot_euler=(-0.22, 0, lyaw))

    # 3. 6 Modern Conference Chairs (3 along +Y, 3 along -Y)
    chair_xs = [tx - 0.98, tx, tx + 0.98]
    for ci, cx in enumerate(chair_xs):
        for side_i, sy in enumerate((0.94, -0.94)):
            yaw = (math.pi if sy > 0 else 0.0) + (0.10 if (ci + side_i) % 2 == 0 else -0.08)
            add_ergonomic_office_chair(bm_dark, bm_pad, bm_shell, (cx, sy), yaw)

    # 4. Signature Google Timber-Slat & Glass Conference Accent Wall at X = -2.42m (H = 2.50m)
    wx = -2.42
    wall_w = 3.06
    wall_h = 2.50
    # Outer architectural dark-steel frame
    bm_add_box(bm_dark, (wx, 0.0, 0.06), (0.14, wall_w, 0.08))
    bm_add_box(bm_dark, (wx, 0.0, wall_h - 0.04), (0.14, wall_w, 0.08))
    for sy in (-wall_w * 0.5 + 0.04, wall_w * 0.5 - 0.04):
        bm_add_box(bm_dark, (wx, sy, wall_h * 0.5), (0.14, 0.08, wall_h))
    # Central solid backing board & vertical warm cedar acoustic slats
    bm_add_box(bm_dark, (wx - 0.03, 0.0, wall_h * 0.5), (0.04, 2.26, wall_h - 0.12))
    n_slats = 15
    for s in range(n_slats):
        sy = -1.06 + 2.12 * (s / float(n_slats - 1))
        bm_add_box(bm_cedar, (wx + 0.025, sy, wall_h * 0.5), (0.055, 0.068, wall_h - 0.16))
    # Flanking translucent architectural glass sidelight panels + short side glass return wings!
    for sgn in (-1.0, 1.0):
        gy = sgn * 1.31
        bm_add_box(bm_glass, (wx, gy, wall_h * 0.5), (0.028, 0.36, wall_h - 0.16))
        bm_add_box(bm_dark, (wx, sgn * 1.13, wall_h * 0.5), (0.09, 0.05, wall_h - 0.12))
        # Glass side return wing framing the pod (0.85m along +X)
        ry = sgn * (wall_w * 0.5 - 0.04)
        bm_add_box(bm_glass, (wx + 0.44, ry, wall_h * 0.5), (0.82, 0.028, wall_h - 0.16))
        bm_add_box(bm_dark, (wx + 0.44, ry, wall_h - 0.04), (0.88, 0.08, 0.08))
        bm_add_box(bm_dark, (wx + 0.44, ry, 0.06), (0.88, 0.08, 0.08))
        bm_add_box(bm_dark, (wx + 0.86, ry, wall_h * 0.5), (0.07, 0.08, wall_h))

    # Large 75" Google Meet Wall Display Screen facing +X toward conference table!
    scr_x = wx + 0.105
    scr_w, scr_h = 1.92, 1.08
    scr_z = 1.48
    bm_add_box(bm_dark, (scr_x - 0.025, 0.0, scr_z), (0.055, scr_w + 0.07, scr_h + 0.07), bevel=0.010)
    # UV-mapped glowing Google Meet screen quad (facing +X)
    bm_add_uv_quad(
        bm_meet,
        [
            (scr_x + 0.006, -scr_w * 0.5, scr_z - scr_h * 0.5),
            (scr_x + 0.006,  scr_w * 0.5, scr_z - scr_h * 0.5),
            (scr_x + 0.006,  scr_w * 0.5, scr_z + scr_h * 0.5),
            (scr_x + 0.006, -scr_w * 0.5, scr_z + scr_h * 0.5),
        ],
    )
    # Google Meet Camera / Soundbar bar mounted below display + glowing status LED
    bm_add_box(bm_dark, (scr_x + 0.02, 0.0, scr_z - scr_h * 0.5 - 0.11), (0.09, 0.88, 0.075), bevel=0.012)
    bm_add_box(bm_cyan, (scr_x + 0.068, 0.0, scr_z - scr_h * 0.5 - 0.11), (0.012, 0.18, 0.014))

    finalize_mesh("ConfPod_BirchTable", bm_birch, mat_birch, smooth=False, uv_scale=0.55)
    finalize_mesh("ConfPod_CedarSlats", bm_cedar, mat_cedar, smooth=False, uv_scale=0.6)
    finalize_mesh("ConfPod_AreaRug", bm_rug, mat_rug, smooth=False, uv_scale=0.45)
    finalize_mesh("ConfPod_DarkSteel", bm_dark, mat_dark, smooth=False)
    finalize_mesh("ConfPod_Aluminum", bm_alum, mat_alum, smooth=True)
    finalize_mesh("ConfPod_GlassWings", bm_glass, mat_glass, smooth=False)
    finalize_mesh("ConfPod_MeetScreen", bm_meet, mat_meet, smooth=False, keep_uv=True)
    finalize_mesh("ConfPod_ChairShells", bm_shell, mat_shell, smooth=True)
    finalize_mesh("ConfPod_ChairPads", bm_pad, mat_pad, smooth=True)
    finalize_mesh("ConfPod_MeetGlow", bm_cyan, mat_cyan, smooth=True)

    return export_prop("prop_conference_pod.glb")


# ===========================================================================
# 3. PROP: GOOGLEPLEX MICROKITCHEN BAR (prop_microkitchen_bar.glb, ~5.0m x 2.4m x 2.08m)
# ===========================================================================
def build_microkitchen_bar():
    reset_scene()

    tex_oak = gen_wood_tex("MK_OakTex", tint=(0.78, 0.58, 0.36), size=128, seed=301)
    tex_marble = gen_marble_tex("MK_MarbleTex", size=128, seed=302)

    mat_oak = make_pbr_mat("MK_WarmOak", base_color=hex_to_linear("#C6935C"), roughness=0.58, tex_img=tex_oak)
    mat_marble = make_pbr_mat("MK_CarraraMarble", base_color=(1, 1, 1, 1), roughness=0.22, specular=0.68, tex_img=tex_marble)
    mat_chrome = make_pbr_mat("MK_ChromeSteel", base_color=hex_to_linear("#DCE3EC"), metallic=0.92, roughness=0.14)
    mat_dark = make_pbr_mat("MK_DarkSteel", base_color=hex_to_linear("#222832"), metallic=0.68, roughness=0.38)
    mat_glass = make_pbr_mat("MK_CoolerGlass", base_color=hex_to_linear("#B8E6FE", alpha=0.28), metallic=0.15, roughness=0.06, alpha=0.28, double_sided=True)
    mat_fridge_glow = make_pbr_mat("MK_CoolerLight", base_color=hex_to_linear("#F4FAFF"), roughness=0.2, emission=hex_to_linear("#D8F1FF"), emission_strength=1.45)
    mat_ceramic = make_pbr_mat("MK_WhiteCeramic", base_color=hex_to_linear("#F8FAFC"), roughness=0.24)
    mat_drinks = [
        make_pbr_mat("MK_DrinkBlue", base_color=hex_to_linear(G_BLUE), metallic=0.45, roughness=0.25),
        make_pbr_mat("MK_DrinkRed", base_color=hex_to_linear(G_RED), metallic=0.45, roughness=0.25),
        make_pbr_mat("MK_DrinkYellow", base_color=hex_to_linear(G_YELLOW), metallic=0.45, roughness=0.25),
        make_pbr_mat("MK_DrinkGreen", base_color=hex_to_linear(G_GREEN), metallic=0.45, roughness=0.25),
    ]

    bm_oak = bmesh.new()
    bm_marble = bmesh.new()
    bm_chrome = bmesh.new()
    bm_dark = bmesh.new()
    bm_glass = bmesh.new()
    bm_glow = bmesh.new()
    bm_cer = bmesh.new()
    bm_drinks = [bmesh.new() for _ in range(4)]

    # 1. L-Shaped Microkitchen Bar Counter (Main bar along X: 3.9m, return pantry along Y at X=-1.95)
    # Toe-kick recessed base (Z = 0.0..0.10m)
    bm_add_box(bm_dark, (0.52, -0.18, 0.05), (3.76, 0.76, 0.10))
    # Main oak cabinet body (Z = 0.10..0.98m)
    bm_add_box(bm_oak, (0.52, -0.18, 0.54), (3.86, 0.84, 0.88), bevel=0.015)
    # Decorative vertical fluted oak slats across front bar apron (+Y face)
    for k in range(20):
        sx = -1.32 + 3.68 * (k / 19.0)
        bm_add_box(bm_oak, (sx, 0.255, 0.54), (0.065, 0.030, 0.84))
    # Overhanging Carrara White Marble Countertop (Z = 0.98..1.05m, overhanging +Y for bar stools!)
    bm_add_box(bm_marble, (0.52, -0.06, 1.015), (4.00, 1.12, 0.070), bevel=0.012)

    # Return L-Wing counter on West side (X = -1.96, Y = -0.25..-1.05) + Backside bar shelf
    bm_add_box(bm_dark, (-1.94, -0.68, 0.05), (0.94, 0.72, 0.10))
    bm_add_box(bm_oak, (-1.94, -0.68, 0.54), (0.98, 0.80, 0.88))
    bm_add_box(bm_marble, (-1.94, -0.68, 1.015), (1.06, 0.88, 0.070), bevel=0.012)

    # 2. Glowing Glass-Front Googleplex Beverage & Snack Cooler Fridge (X = -1.94, Y = +0.16, Z = 0.0..2.08m)
    fx, fy = -1.94, 0.16
    fw, fd, fh = 0.96, 0.78, 2.08
    # Matte charcoal steel outer insulated fridge housing (open front cavity facing +Y!)
    bm_add_box(bm_dark, (fx, fy - fd * 0.44, fh * 0.5), (fw, 0.10, fh))
    bm_add_box(bm_dark, (fx, fy, 0.14), (fw, fd, 0.28))
    bm_add_box(bm_dark, (fx, fy, fh - 0.07), (fw, fd, 0.14))
    for sgn in (-1.0, 1.0):
        bm_add_box(bm_dark, (fx + sgn * (fw * 0.45), fy, fh * 0.5), (0.10, fd, fh))
    # Glowing internal LED fridge back-panel & top cove strip
    bm_add_box(bm_glow, (fx, fy - fd * 0.36, 1.12), (fw - 0.24, 0.03, 1.56))
    bm_add_box(bm_glow, (fx, fy + 0.12, fh - 0.155), (fw - 0.24, 0.12, 0.03))
    # 4 interior glass/chrome shelves stocked with colorful Googleplex sparkling cans & cold brews!
    for sh_i, sz in enumerate((0.46, 0.86, 1.26, 1.62)):
        bm_add_box(bm_chrome, (fx, fy, sz), (fw - 0.22, fd - 0.20, 0.018))
        # Row of 5 colorful beverages per shelf (2 deep)
        for bi in range(5):
            bx = fx - 0.28 + bi * 0.14
            by = fy + 0.06
            mat_idx = (sh_i + bi) % 4
            bm_add_prism(bm_drinks[mat_idx], (bx, by, sz + 0.01), (bx, by, sz + 0.17), 0.036, 0.036, segs=6)
            bm_add_prism(bm_drinks[(mat_idx + 1) % 4], (bx, by - 0.15, sz + 0.01), (bx, by - 0.15, sz + 0.19), 0.036, 0.033, segs=6)
    # Framed translucent cooler glass door & vertical chrome bar handle (facing +Y)
    door_y = fy + fd * 0.48
    bm_add_box(bm_glass, (fx, door_y, 1.12), (fw - 0.16, 0.024, 1.60))
    for sgn in (-1.0, 1.0):
        bm_add_box(bm_chrome, (fx + sgn * (fw * 0.45), door_y, 1.12), (0.045, 0.040, 1.66))
    bm_add_box(bm_chrome, (fx, door_y, 0.30), (fw - 0.04, 0.040, 0.045))
    bm_add_box(bm_chrome, (fx, door_y, 1.94), (fw - 0.04, 0.040, 0.045))
    bm_add_prism(bm_chrome, (fx + 0.36, door_y + 0.06, 0.92), (fx + 0.36, door_y + 0.06, 1.44), 0.014, 0.014, segs=8)

    # 3. Commercial Dual-Group Chrome Espresso Machine + Burr Grinder + Pastry Display (on Marble Top Z = 1.05m)
    ex, ey = 0.08, -0.20
    bm_add_box(bm_chrome, (ex, ey, 1.10), (0.86, 0.50, 0.10), bevel=0.012)           # Base drip chassis
    bm_add_box(bm_dark, (ex, ey + 0.16, 1.155), (0.76, 0.16, 0.015))                 # Drip grate
    bm_add_box(bm_chrome, (ex, ey - 0.08, 1.34), (0.86, 0.36, 0.40), bevel=0.018)    # Boiler main chrome body
    bm_add_box(bm_chrome, (ex, ey + 0.12, 1.44), (0.86, 0.18, 0.18), bevel=0.015)    # Overhanging group head brow
    # Twin brass/chrome portafilters & pressure gauges + steam wands
    for gx in (ex - 0.22, ex + 0.22):
        bm_add_prism(bm_chrome, (gx, ey + 0.14, 1.28), (gx, ey + 0.14, 1.36), 0.046, 0.046, segs=10)
        bm_add_prism(bm_dark, (gx, ey + 0.18, 1.30), (gx, ey + 0.32, 1.28), 0.014, 0.018, segs=6)
        bm_add_prism(bm_cer, (gx, ey + 0.15, 1.16), (gx, ey + 0.15, 1.23), 0.032, 0.036, segs=8)
    # Cup-warmer rail & stacked ceramic espresso cups on top of machine
    for rx_o in (-0.38, 0.38):
        bm_add_prism(bm_chrome, (ex + rx_o, ey - 0.22, 1.54), (ex + rx_o, ey - 0.22, 1.60), 0.008, 0.008, segs=6)
    bm_add_prism(bm_chrome, (ex - 0.38, ey - 0.22, 1.595), (ex + 0.38, ey - 0.22, 1.595), 0.008, 0.008, segs=6)
    for cx_o in (-0.24, -0.10, 0.06, 0.22):
        bm_add_prism(bm_cer, (ex + cx_o, ey - 0.08, 1.54), (ex + cx_o, ey - 0.08, 1.61), 0.036, 0.040, segs=8)

    # Commercial Coffee Grinder beside espresso machine
    bm_add_box(bm_dark, (ex - 0.64, ey - 0.06, 1.22), (0.20, 0.26, 0.34), bevel=0.015)
    bm_add_prism(bm_glass, (ex - 0.64, ey - 0.06, 1.39), (ex - 0.64, ey - 0.06, 1.60), 0.055, 0.105, segs=10)

    # Glass Pastry Display Case & Snack Jars on East side of counter
    bm_add_box(bm_oak, (1.42, -0.16, 1.075), (0.94, 0.48, 0.05), bevel=0.008)
    bm_add_box(bm_glass, (1.42, -0.16, 1.28), (0.90, 0.44, 0.38))
    bm_add_box(bm_chrome, (1.42, -0.16, 1.26), (0.86, 0.40, 0.015))
    # Colorful snack canisters on counter end
    for ci, sx in enumerate((2.06, 2.24)):
        bm_add_prism(bm_drinks[ci + 2], (sx, -0.18, 1.05), (sx, -0.18, 1.26), 0.062, 0.062, segs=10)
        bm_add_prism(bm_oak, (sx, -0.18, 1.26), (sx, -0.18, 1.29), 0.065, 0.065, segs=10)

    # 4. 4 Modern High-Top Cafe Bar Stools lined along front overhang (+Y)
    stool_xs = [-0.82, 0.06, 0.94, 1.82]
    for si, sx in enumerate(stool_xs):
        sy = 0.80 + (0.04 if si % 2 == 0 else -0.03)
        # 4 slender splayed matte-black steel legs grounded at Z = 0.0
        for k in range(4):
            ang = k * (math.pi * 0.5) + math.pi * 0.25
            bm_add_prism(
                bm_dark,
                (sx + 0.22 * math.cos(ang), sy + 0.22 * math.sin(ang), 0.0),
                (sx + 0.15 * math.cos(ang), sy + 0.15 * math.sin(ang), 0.70),
                0.014,
                0.014,
                segs=6,
            )
        # Chrome footrest ring at Z = 0.26m
        bm_add_torus(bm_chrome, (sx, sy, 0.26), 0.195, 0.011, major_segs=14, minor_segs=5)
        # Molded warm-oak round bar stool seat + subtle low lip back
        bm_add_prism(bm_oak, (sx, sy, 0.70), (sx, sy, 0.745), 0.195, 0.190, segs=14)
        bm_add_box(bm_oak, (sx, sy + 0.16, 0.80), (0.30, 0.036, 0.11), bevel=0.010)

    finalize_mesh("MK_WarmOak", bm_oak, mat_oak, smooth=False, uv_scale=0.65)
    finalize_mesh("MK_CarraraMarble", bm_marble, mat_marble, smooth=False, uv_scale=0.55)
    finalize_mesh("MK_Chrome", bm_chrome, mat_chrome, smooth=True)
    finalize_mesh("MK_DarkSteel", bm_dark, mat_dark, smooth=False)
    finalize_mesh("MK_CoolerGlass", bm_glass, mat_glass, smooth=False)
    finalize_mesh("MK_CoolerLED", bm_glow, mat_fridge_glow, smooth=False)
    finalize_mesh("MK_Ceramics", bm_cer, mat_ceramic, smooth=True)
    for i, cname in enumerate(("Blue", "Red", "Yellow", "Green")):
        finalize_mesh(f"MK_Drinks{cname}", bm_drinks[i], mat_drinks[i], smooth=True)

    # Orient front bar overhang, 4 cafe stools & glowing glass cooler facing -Y (front 3/4 studio view!)
    for obj in bpy.context.scene.objects:
        if obj.type == "MESH":
            obj.rotation_euler.z = math.pi
    bpy.context.view_layer.update()

    return export_prop("prop_microkitchen_bar.glb")


# ===========================================================================
# 4. PROP: GOOGLE LOUNGE NOOK (prop_lounge_nook.glb, ~4.2m x 3.4m x 2.25m)
# ===========================================================================
def build_lounge_nook():
    reset_scene()

    tex_oak = gen_wood_tex("Lounge_OakTex", tint=(0.82, 0.64, 0.42), size=128, seed=401)
    tex_rug = gen_woven_rug_tex("Lounge_RugTex", base_a=(0.86, 0.83, 0.77), base_b=(0.74, 0.71, 0.65), size=128, seed=402)

    mat_rug = make_pbr_mat("Lounge_WovenRug", base_color=(1, 1, 1, 1), roughness=0.95, tex_img=tex_rug)
    mat_sofa = make_pbr_mat("Lounge_SofaBoucle", base_color=hex_to_linear("#D6DAE2"), roughness=0.90)
    mat_sofa_base = make_pbr_mat("Lounge_SofaPlinth", base_color=hex_to_linear("#565F6E"), roughness=0.85)
    mat_oak = make_pbr_mat("Lounge_WarmOak", base_color=hex_to_linear("#CE9D64"), roughness=0.52, tex_img=tex_oak)
    mat_pot = make_pbr_mat("Lounge_CeramicPot", base_color=hex_to_linear("#EFEAE2"), roughness=0.55)
    mat_bark = make_pbr_mat("Lounge_FicusWood", base_color=hex_to_linear("#5E4432"), roughness=0.90)
    mat_leaf_a = make_pbr_mat("Lounge_FicusDeep", base_color=hex_to_linear("#265830"), roughness=0.68)
    mat_leaf_b = make_pbr_mat("Lounge_FicusSun", base_color=hex_to_linear("#3C7D42"), roughness=0.62)
    mat_g = [
        make_pbr_mat("Lounge_GoogleBlue", base_color=hex_to_linear(G_BLUE), roughness=0.86),
        make_pbr_mat("Lounge_GoogleRed", base_color=hex_to_linear(G_RED), roughness=0.86),
        make_pbr_mat("Lounge_GoogleYellow", base_color=hex_to_linear(G_YELLOW), roughness=0.86),
        make_pbr_mat("Lounge_GoogleGreen", base_color=hex_to_linear(G_GREEN), roughness=0.86),
    ]

    bm_rug = bmesh.new()
    bm_sofa = bmesh.new()
    bm_sbase = bmesh.new()
    bm_oak = bmesh.new()
    bm_pot = bmesh.new()
    bm_bark = bmesh.new()
    bm_leaf_a = bmesh.new()
    bm_leaf_b = bmesh.new()
    bm_g = [bmesh.new() for _ in range(4)]

    # 1. Warm Woven Area Rug (4.10m x 3.30m, grounded at Z = 0.00..0.025m)
    bm_add_box(bm_rug, (0.0, 0.0, 0.0125), (4.10, 3.30, 0.025), bevel=0.006)

    # 2. Modular L-Shaped Office Sofa (Long run along -Y, Chaise return along -X)
    # Tapered solid-oak legs under L-frame (Z = 0.02..0.16m)
    leg_pts = [
        (-1.72, -1.24), (-0.40, -1.24), (1.10, -1.24),
        (-1.72, -0.46), (1.10, -0.46),
        (-1.72,  1.10), (-0.98,  1.10),
    ]
    for lx, ly in leg_pts:
        bm_add_prism(bm_oak, (lx, ly, 0.02), (lx, ly, 0.16), 0.022, 0.032, segs=8)

    # Upholstered L-shaped plinth frame (Z = 0.16..0.30m)
    bm_add_box(bm_sbase, (-0.30, -0.86, 0.23), (3.06, 0.94, 0.14), bevel=0.015)
    bm_add_box(bm_sbase, (-1.36,  0.34, 0.23), (0.94, 1.66, 0.14), bevel=0.015)

    # Plush beveled seat cushions (Z = 0.30..0.46m)
    for sx in (-1.35, -0.48, 0.36, 1.00):
        w = 0.84 if sx < 0.8 else 0.50
        bm_add_box(bm_sofa, (sx, -0.80, 0.38), (w, 0.78, 0.16), bevel=0.038)
    for sy in (0.02, 0.78):
        bm_add_box(bm_sofa, (-1.30, sy, 0.38), (0.78, 0.74, 0.16), bevel=0.038)

    # Sculpted backrest shells & armrests (Z = 0.30..0.86m)
    bm_add_box(bm_sofa, (-0.30, -1.23, 0.58), (3.06, 0.20, 0.56), bevel=0.035)   # Rear backrest
    bm_add_box(bm_sofa, (-1.73,  0.22, 0.58), (0.20, 1.92, 0.56), bevel=0.035)   # Left backrest
    bm_add_box(bm_sofa, ( 1.16, -0.86, 0.48), (0.18, 0.94, 0.36), bevel=0.030)   # Right arm
    bm_add_box(bm_sofa, (-1.36,  1.14, 0.46), (0.94, 0.18, 0.32), bevel=0.030)   # Front chaise arm

    # 4 Vibrant Google Primary-Colored Throw Pillows angled playfully along backrest!
    pillows = [
        ((-1.42, -1.04, 0.60), (0.26,  0.14,  0.55), 0),  # Blue corner pillow
        ((-0.68, -1.06, 0.60), (0.24, -0.06,  0.08), 1),  # Red pillow
        (( 0.24, -1.06, 0.60), (0.24,  0.08, -0.10), 2),  # Yellow pillow
        ((-1.54,  0.34, 0.60), (0.10, -0.24,  1.45), 3),  # Green chaise pillow
    ]
    for pos, rot, g_idx in pillows:
        bm_add_box(bm_g[g_idx], pos, (0.42, 0.15, 0.38), rot_euler=rot, bevel=0.048)

    # 3. Sculpted Low Warm-Oak Coffee Table (1.36m x 0.76m, top Z = 0.42m)
    tx, ty = 0.28, 0.32
    bm_add_stadium_slab(bm_oak, (tx, ty, 0.405), 1.36, 0.76, 0.036, segs=18)
    for sx in (-0.42, 0.42):
        for sy in (-0.22, 0.22):
            bm_add_prism(bm_oak, (tx + sx * 1.15, ty + sy * 1.18, 0.025), (tx + sx, ty + sy, 0.39), 0.020, 0.026, segs=8)
    # Art books & coffee mug on coffee table
    bm_add_box(bm_g[0], (tx - 0.26, ty + 0.04, 0.440), (0.28, 0.22, 0.032), rot_euler=(0, 0, 0.18), bevel=0.004)
    bm_add_box(bm_g[1], (tx - 0.24, ty + 0.06, 0.470), (0.24, 0.18, 0.026), rot_euler=(0, 0, -0.12), bevel=0.004)
    bm_add_prism(bm_pot, (tx + 0.32, ty - 0.10, 0.425), (tx + 0.32, ty - 0.10, 0.515), 0.038, 0.042, segs=10)

    # 4. Playful Google-Yellow Round Upholstered Ottoman Pouf (X = +1.42, Y = +0.76)
    bm_add_prism(bm_oak, (1.42, 0.76, 0.025), (1.42, 0.76, 0.08), 0.28, 0.30, segs=14)
    bm_add_prism(bm_g[2], (1.42, 0.76, 0.08), (1.42, 0.76, 0.42), 0.33, 0.32, segs=16)

    # 5. Potted Indoor Ficus Tree in Ceramic Planter at East-South Corner (X = +1.64, Y = -0.96, H = 2.25m)
    px, py = 1.64, -0.96
    # Crossed oak plant stand + cream fluted ceramic pot (Z = 0.02..0.58m)
    bm_add_box(bm_oak, (px, py, 0.08), (0.58, 0.06, 0.05))
    bm_add_box(bm_oak, (px, py, 0.08), (0.06, 0.58, 0.05))
    bm_add_prism(bm_pot, (px, py, 0.08), (px, py, 0.56), 0.24, 0.29, segs=16)
    bm_add_prism(bm_bark, (px, py, 0.52), (px, py, 0.55), 0.25, 0.25, segs=12)  # Potting soil
    # Organic multi-stem branching ficus trunk (Z = 0.54..1.72m)
    stems = [
        ((0.00,  0.00, 0.54), ( 0.03, -0.02, 1.18), ( 0.08, -0.08, 1.72)),
        ((0.02,  0.02, 0.78), (-0.16,  0.14, 1.38), (-0.28,  0.22, 1.76)),
        ((-0.02, -0.01, 0.88), ( 0.18,  0.12, 1.44), ( 0.28,  0.20, 1.72)),
        ((0.01, -0.02, 0.96), (-0.12, -0.18, 1.48), (-0.18, -0.26, 1.78)),
    ]
    for p0, p1, p2 in stems:
        v0 = Vector((px + p0[0], py + p0[1], p0[2]))
        v1 = Vector((px + p1[0], py + p1[1], p1[2]))
        v2 = Vector((px + p2[0], py + p2[1], p2[2]))
        bm_add_prism(bm_bark, v0, v1, 0.040, 0.026, segs=7)
        bm_add_prism(bm_bark, v1, v2, 0.025, 0.014, segs=6)
    # Layered organic sculpted glossy indoor Ficus canopy clusters (up to Z = 2.25m!)
    ficus_clusters = [
        ((0.00,  0.00, 1.98), 0.30, 0.28, 0.23, 1),
        ((0.24,  0.18, 1.74), 0.24, 0.23, 0.19, 0),
        ((-0.26, 0.20, 1.78), 0.25, 0.23, 0.20, 1),
        ((-0.18, -0.24, 1.76), 0.24, 0.22, 0.19, 0),
        ((0.22, -0.20, 1.62), 0.23, 0.21, 0.18, 0),
        ((0.04,  0.24, 1.56), 0.22, 0.20, 0.18, 0),
        ((-0.22, -0.02, 1.48), 0.21, 0.19, 0.17, 0),
        ((0.02, -0.04, 1.66), 0.26, 0.24, 0.20, 1),
        ((0.14,  0.06, 2.08), 0.18, 0.18, 0.15, 1),
        ((-0.14, -0.10, 1.92), 0.19, 0.18, 0.16, 0),
    ]
    for ci, (off, rx, ry, rz, bright) in enumerate(ficus_clusters):
        bm_add_organic_foliage(
            bm_leaf_b if bright else bm_leaf_a,
            (px + off[0], py + off[1], off[2]),
            rx,
            ry,
            rz,
            subdiv=2,
            seed=450 + ci * 17,
            crinkle=0.30,
        )

    finalize_mesh("Lounge_WovenRug", bm_rug, mat_rug, smooth=False, uv_scale=0.5)
    finalize_mesh("Lounge_SofaUpholstery", bm_sofa, mat_sofa, smooth=True)
    finalize_mesh("Lounge_SofaBase", bm_sbase, mat_sofa_base, smooth=False)
    finalize_mesh("Lounge_WarmOak", bm_oak, mat_oak, smooth=True, uv_scale=0.65)
    finalize_mesh("Lounge_CeramicPot", bm_pot, mat_pot, smooth=True)
    finalize_mesh("Lounge_FicusWood", bm_bark, mat_bark, smooth=True)
    finalize_mesh("Lounge_FicusLeafDeep", bm_leaf_a, mat_leaf_a, smooth=True)
    finalize_mesh("Lounge_FicusLeafSun", bm_leaf_b, mat_leaf_b, smooth=True)
    for i, cname in enumerate(("Blue", "Red", "Yellow", "Green")):
        finalize_mesh(f"Lounge_Google{cname}", bm_g[i], mat_g[i], smooth=True)

    return export_prop("prop_lounge_nook.glb")


# ===========================================================================
# 5. PROP: MOBILE WHITEBOARD + PLANTER DIVIDER (prop_whiteboard_wall.glb, ~2.6m x 0.8m x 1.85m)
# ===========================================================================
def build_whiteboard_wall():
    reset_scene()

    tex_wb = gen_whiteboard_sticky_tex("WB_StickyNotesTex", w=224, h=160, seed=501)
    tex_oak = gen_wood_tex("WB_OakTex", tint=(0.78, 0.59, 0.38), size=128, seed=502)

    mat_wb = make_pbr_mat("WB_StickyBoard", base_color=(1, 1, 1, 1), roughness=0.16, specular=0.72, tex_img=tex_wb)
    mat_alum = make_pbr_mat("WB_BrushedAlum", base_color=hex_to_linear("#CBD3DC"), metallic=0.84, roughness=0.26)
    mat_dark = make_pbr_mat("WB_DarkSteel", base_color=hex_to_linear("#262D37"), metallic=0.70, roughness=0.38)
    mat_white = make_pbr_mat("WB_PlanterWhite", base_color=hex_to_linear("#EEF1F5"), roughness=0.45)
    mat_oak = make_pbr_mat("WB_OakSlats", base_color=hex_to_linear("#C49059"), roughness=0.60, tex_img=tex_oak)
    mat_soil = make_pbr_mat("WB_Soil", base_color=hex_to_linear("#3A2C21"), roughness=0.95)
    mat_leaf_a = make_pbr_mat("WB_PlantDeep", base_color=hex_to_linear("#235C30"), roughness=0.68)
    mat_leaf_b = make_pbr_mat("WB_PlantBright", base_color=hex_to_linear("#438C45"), roughness=0.60)
    mat_markers = [
        make_pbr_mat("WB_MarkerBlue", base_color=hex_to_linear(G_BLUE), roughness=0.35),
        make_pbr_mat("WB_MarkerRed", base_color=hex_to_linear(G_RED), roughness=0.35),
        make_pbr_mat("WB_MarkerGreen", base_color=hex_to_linear(G_GREEN), roughness=0.35),
    ]

    bm_wb = bmesh.new()
    bm_alum = bmesh.new()
    bm_dark = bmesh.new()
    bm_white = bmesh.new()
    bm_oak = bmesh.new()
    bm_soil = bmesh.new()
    bm_leaf_a = bmesh.new()
    bm_leaf_b = bmesh.new()
    bm_m = [bmesh.new() for _ in range(3)]

    # 1. Mobile Aluminum/Glass Engineering Whiteboard on Left (X in [-1.28, +0.36], H = 1.85m)
    wcx = -0.46
    wb_w = 1.56
    wb_h = 1.18
    wb_z0, wb_z1 = 0.62, 1.80

    # Rolling aluminum H-stand + 4 locking rubber casters grounded at Z = 0.0
    for sgn in (-1.0, 1.0):
        ux = wcx + sgn * (wb_w * 0.5 + 0.025)
        # Splayed rolling foot bar (0.72m deep along Y)
        bm_add_box(bm_alum, (ux, 0.0, 0.085), (0.048, 0.72, 0.042), bevel=0.008)
        # Vertical aluminum side post
        bm_add_box(bm_alum, (ux, 0.0, 0.96), (0.048, 0.056, 1.76), bevel=0.008)
        # Twin locking swivel caster wheels touching Z = 0.0
        for cy in (-0.31, 0.31):
            bm_add_prism(bm_dark, (ux, cy, 0.0), (ux, cy, 0.065), 0.032, 0.032, segs=8)
    # Cross stabilizer tie bar & outer aluminum board bezel
    bm_add_box(bm_alum, (wcx, 0.0, 0.24), (wb_w + 0.05, 0.036, 0.038))
    bm_add_box(bm_alum, (wcx, 0.0, wb_z1 + 0.025), (wb_w + 0.10, 0.058, 0.050), bevel=0.008)
    bm_add_box(bm_alum, (wcx, 0.0, wb_z0 - 0.025), (wb_w + 0.10, 0.058, 0.050), bevel=0.008)
    # Solid inner board core
    bm_add_box(bm_white, (wcx, 0.0, 0.5 * (wb_z0 + wb_z1)), (wb_w, 0.032, wb_h))

    # UV-mapped Sticky-Note & Architecture Diagram Whiteboard Faces on BOTH +Y and -Y sides!
    # Front (+Y)
    bm_add_uv_quad(
        bm_wb,
        [
            (wcx - wb_w * 0.495,  0.018, wb_z0 + 0.01),
            (wcx + wb_w * 0.495,  0.018, wb_z0 + 0.01),
            (wcx + wb_w * 0.495,  0.018, wb_z1 - 0.01),
            (wcx - wb_w * 0.495,  0.018, wb_z1 - 0.01),
        ],
    )
    # Back (-Y)
    bm_add_uv_quad(
        bm_wb,
        [
            (wcx + wb_w * 0.495, -0.018, wb_z0 + 0.01),
            (wcx - wb_w * 0.495, -0.018, wb_z0 + 0.01),
            (wcx - wb_w * 0.495, -0.018, wb_z1 - 0.01),
            (wcx + wb_w * 0.495, -0.018, wb_z1 - 0.01),
        ],
    )

    # Full-width marker tray on both sides + colorful dry-erase markers & eraser
    for sy_sgn in (-1.0, 1.0):
        bm_add_box(bm_alum, (wcx, sy_sgn * 0.065, wb_z0 - 0.045), (wb_w * 0.88, 0.085, 0.018), bevel=0.004)
    for mi, mx_o in enumerate((-0.38, -0.20, -0.02)):
        bm_add_prism(bm_m[mi], (wcx + mx_o - 0.06, 0.072, wb_z0 - 0.025), (wcx + mx_o + 0.06, 0.072, wb_z0 - 0.025), 0.010, 0.010, segs=6)
    bm_add_box(bm_dark, (wcx + 0.28, 0.072, wb_z0 - 0.018), (0.14, 0.052, 0.036), bevel=0.005)

    # 2. Adjacent Modern Indoor Planter Divider on Right (X in [+0.42, +1.28], H = 1.76m)
    px = 0.85
    pw, pd, ph = 0.84, 0.56, 0.78
    # Matte-white planter cabinet + warm vertical oak slat trim + steel base plinth
    bm_add_box(bm_dark, (px, 0.0, 0.03), (pw - 0.04, pd - 0.04, 0.06))
    bm_add_box(bm_white, (px, 0.0, 0.42), (pw, pd, ph - 0.06), bevel=0.014)
    for sy_sgn in (-1.0, 1.0):
        for k in range(8):
            sx = px - 0.35 + 0.70 * (k / 7.0)
            bm_add_box(bm_oak, (sx, sy_sgn * (pd * 0.5 + 0.008), 0.42), (0.042, 0.018, ph - 0.14), bevel=0.004)
    # Dark soil bed recessed at top of planter box
    bm_add_box(bm_soil, (px, 0.0, ph - 0.03), (pw - 0.08, pd - 0.08, 0.04))

    # Minimalist dark-steel architectural trellis divider frame rising to Z = 1.76m
    for sgn in (-1.0, 1.0):
        bm_add_box(bm_dark, (px + sgn * (pw * 0.44), 0.0, 1.24), (0.030, 0.030, 1.04))
    bm_add_box(bm_dark, (px, 0.0, 1.75), (pw * 0.91, 0.032, 0.032))
    bm_add_box(bm_dark, (px, 0.0, 1.28), (pw * 0.86, 0.018, 0.018))

    # Lush sculpted Sansevieria sword leaves + organic deep-emerald indoor foliage divider!
    rng = np.random.default_rng(515)
    for li in range(14):
        lx = px - 0.30 + (li / 13.0) * 0.60 + rng.uniform(-0.02, 0.02)
        ly = rng.uniform(-0.14, 0.14)
        lh = rng.uniform(0.45, 0.82)
        tilt_x = rng.uniform(-0.16, 0.16)
        tilt_y = rng.uniform(-0.18, 0.18)
        target_bm = bm_leaf_b if (li % 2 == 0) else bm_leaf_a
        bm_add_box(target_bm, (lx, ly, ph + lh * 0.46), (0.055, 0.018, lh), rot_euler=(tilt_y, tilt_x, rng.uniform(-0.5, 0.5)), bevel=0.006)
    # Soft overhanging organic foliage bushes softening planter edges
    for ci, (ox, oy, oz, rx, ry, rz, bright) in enumerate((
        (-0.22,  0.08, 1.06, 0.22, 0.22, 0.22, 0),
        ( 0.02, -0.06, 1.22, 0.25, 0.22, 0.24, 1),
        ( 0.24,  0.05, 1.08, 0.22, 0.22, 0.20, 0),
        (-0.08,  0.04, 1.44, 0.20, 0.18, 0.20, 1),
    )):
        bm_add_organic_foliage(
            bm_leaf_b if bright else bm_leaf_a,
            (px + ox, oy, oz),
            rx,
            ry,
            rz,
            subdiv=2,
            seed=560 + ci * 13,
            crinkle=0.20,
        )

    finalize_mesh("WB_StickySurface", bm_wb, mat_wb, smooth=False, keep_uv=True)
    finalize_mesh("WB_AluminumStand", bm_alum, mat_alum, smooth=False)
    finalize_mesh("WB_DarkSteel", bm_dark, mat_dark, smooth=False)
    finalize_mesh("WB_PlanterBox", bm_white, mat_white, smooth=False)
    finalize_mesh("WB_OakSlats", bm_oak, mat_oak, smooth=False, uv_scale=0.8)
    finalize_mesh("WB_Soil", bm_soil, mat_soil, smooth=False)
    finalize_mesh("WB_PlantDeep", bm_leaf_a, mat_leaf_a, smooth=True)
    finalize_mesh("WB_PlantBright", bm_leaf_b, mat_leaf_b, smooth=True)
    for i, cname in enumerate(("Blue", "Red", "Green")):
        finalize_mesh(f"WB_Marker{cname}", bm_m[i], mat_markers[i], smooth=True)

    return export_prop("prop_whiteboard_wall.glb")


# ---------------------------------------------------------------------------
# Main Runner
# ---------------------------------------------------------------------------
BUILDERS = [
    ("prop_desk_pod.glb", build_desk_pod),
    ("prop_conference_pod.glb", build_conference_pod),
    ("prop_microkitchen_bar.glb", build_microkitchen_bar),
    ("prop_lounge_nook.glb", build_lounge_nook),
    ("prop_whiteboard_wall.glb", build_whiteboard_wall),
]


def main():
    t0 = time.time()
    results = []
    for fname, fn in BUILDERS:
        ts = time.time()
        info = fn()
        info["sec"] = time.time() - ts
        results.append(info)
        dx, dy, dz = info["dims"]
        print(
            f"[OFFICE PROP] {info['file']:28s} | {info['kb']:6.1f} KB | {info['tris']:5d} tris | "
            f"dims(X,Y_depth,Z_h)=({dx:4.2f}, {dy:4.2f}, {dz:4.2f})m | minZ={info['min_z']:+.4f}m | {info['sec']:.2f}s"
        )
    total_kb = sum(r["kb"] for r in results)
    total_tris = sum(r["tris"] for r in results)
    print("-" * 96)
    print(
        f"[OFFICE PROPS SUMMARY] Built {len(results)}/5 office prop .glb assets in {time.time() - t0:.2f}s | "
        f"Total: {total_kb / 1024.0:.2f} MB ({total_kb:.1f} KB) | {total_tris:,} tris"
    )


if __name__ == "__main__":
    main()

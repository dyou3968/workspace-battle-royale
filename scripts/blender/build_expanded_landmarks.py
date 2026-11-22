#!/usr/bin/env python3
"""
Workspace Royale — Expanded 3x Mountain View Campus Landmarks Builder
Blender 5.3.0 headless generator producing 6 new architectural landmarks (.glb)
into public/assets/map/ for the 600m x 380m (3x) Mountain View Googleplex campus:

  1. landmark_shoreline_amphitheatre.glb  (~64m x 56m, peaks +18.0m)  @ (+58, -148) rotY=0 (SE-facing baked)
  2. landmark_athletic_field.glb          (~66m x 42m)                @ (-220, -134) rotY=0
  3. landmark_google_2000_1950.glb        (~82m x 88m, roof +6.4m)    @ (-225, +2)   rotY=0
  4. landmark_charleston_campus.glb       (~110m x 62m, roof +6.4m)   @ (+28, +134)  rotY=0
  5. landmark_alta_complex.glb            (~76m x 54m, roof +6.4m)    @ (-108, +126) rotY=0
  6. landmark_shoreline_east_office.glb   (~66m x 44m, roof +6.4m)    @ (+234,-22) / (+236,-140) / (+234,+122)

Coordinate System (exact match to Three.js export_yup=True):
  - Blender (bx, by, bz) -> Three.js (tx = bx, ty = bz, tz = -by)
  - Blender rotation_euler.z == Three.js rotation.y

Usage:
    blender --background --python scripts/blender/build_expanded_landmarks.py
    blender --background --python scripts/blender/build_expanded_landmarks.py -- --only shoreline_amphitheatre
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


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0


# ---------------------------------------------------------------------------
# Compact Procedural Numpy Textures (Deterministic, Packed into GLB)
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


def _fbm_2d(h, w, rng, octaves=(4, 10, 20)):
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


def gen_concrete_tex(name="TexConcrete", size=128, tint=(0.86, 0.83, 0.77), seed=701):
    rng = np.random.default_rng(seed)
    n = _fbm_2d(size, size, rng, (4, 12, 24))
    grain = rng.normal(0.0, 0.014, (size, size)).astype(np.float32)
    y_idx = np.arange(size)
    x_idx = np.arange(size)
    seam_h = ((y_idx % (size // 4)) < 2).astype(np.float32)[:, None] * 0.08
    seam_v = ((x_idx % (size // 2)) < 2).astype(np.float32)[None, :] * 0.05
    v = 0.91 + 0.12 * (n - 0.5) + grain - seam_h - seam_v
    return make_packed_image(name, np.stack([v * tint[0], v * tint[1], v * tint[2]], axis=-1))


def gen_solar_panel_tex(name="TexSolar", size=128, seed=702):
    rng = np.random.default_rng(seed)
    n = _fbm_2d(size, size, rng, (4, 10))
    yy, xx = np.mgrid[0:size, 0:size]
    cell_h, cell_w = size // 6, size // 4
    cy = yy % cell_h
    cx = xx % cell_w
    r = 0.06 + 0.03 * n
    g = 0.14 + 0.04 * n
    b = 0.38 + 0.08 * n
    bus = (cx == cell_w // 3) | (cx == (2 * cell_w) // 3)
    r = np.where(bus, 0.36, r)
    g = np.where(bus, 0.45, g)
    b = np.where(bus, 0.60, b)
    grid = (cy < 2) | (cx < 2)
    r = np.where(grid, 0.68, r)
    g = np.where(grid, 0.73, g)
    b = np.where(grid, 0.80, b)
    border = (yy < 3) | (yy >= size - 3) | (xx < 3) | (xx >= size - 3)
    r = np.where(border, 0.80, r)
    g = np.where(border, 0.83, g)
    b = np.where(border, 0.87, b)
    return make_packed_image(name, np.stack([r, g, b], axis=-1))


def gen_curtain_glass_tex(name="TexGlass", size=128, seed=703):
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:size, 0:size]
    fy = yy / float(size)
    n = _fbm_2d(size, size, rng, (4, 10))
    r = 0.14 + 0.16 * (1.0 - fy) + 0.03 * n
    g = 0.33 + 0.22 * (1.0 - fy) + 0.04 * n
    b = 0.54 + 0.22 * (1.0 - fy) + 0.05 * n
    div = ((xx % (size // 3)) < 2) | ((yy % (size // 2)) < 2)
    r = np.where(div, 0.22, r)
    g = np.where(div, 0.29, g)
    b = np.where(div, 0.37, b)
    return make_packed_image(name, np.stack([r, g, b], axis=-1))


def gen_oak_floor_tex(name="TexOakFloor", size=128, seed=704):
    rng = np.random.default_rng(seed)
    n_low = _value_noise_2d(size, size, 16, 4, rng)
    yy, xx = np.mgrid[0:size, 0:size]
    plank_h = size // 8
    plank_id = yy // plank_h
    plank_var = ((plank_id * 29 + 3) % 7) / 7.0 * 0.08 - 0.04
    seam_h = ((yy % plank_h) < 1).astype(np.float32) * 0.14
    grain = np.sin(yy * 0.55 + n_low * 6.0) * 0.04
    v = 0.90 + grain + plank_var - seam_h
    return make_packed_image(name, np.stack([v * 0.87, v * 0.76, v * 0.59], axis=-1))


def gen_cedar_wood_tex(name="TexCedar", size=128, seed=705):
    rng = np.random.default_rng(seed)
    n_low = _value_noise_2d(size, size, 16, 4, rng)
    yy = np.arange(size)[:, None]
    grain = np.sin(yy * 0.50 + n_low * 7.5) * 0.5 + 0.5
    plank_h = size // 6
    seam = ((yy % plank_h) < 2).astype(np.float32) * 0.26
    v = 0.86 + 0.15 * grain - seam
    return make_packed_image(name, np.stack([v * 0.74, v * 0.43, v * 0.20], axis=-1))


def gen_tent_fabric_tex(name="TexShorelineTent", size=192, seed=706):
    """Tensioned architectural PTFE white sailcloth membrane with crisp radial welded panel seams."""
    rng = np.random.default_rng(seed)
    n = _fbm_2d(size, size, rng, (4, 12))
    yy, xx = np.mgrid[0:size, 0:size]
    seam_u = ((xx % (size // 8)) < 2).astype(np.float32)
    seam_v = ((yy % (size // 6)) < 1).astype(np.float32) * 0.5
    weave = 0.010 * np.sin(xx * 1.4) * np.sin(yy * 1.4)
    v = 0.96 + 0.03 * (n - 0.5) + weave - 0.11 * seam_u - 0.05 * seam_v
    rgb = np.stack([v * 0.97, v * 0.98, v * 1.00], axis=-1)
    return make_packed_image(name, rgb)


def gen_soccer_pitch_tex(name="TexSoccerPitch", w=512, h=320, seed=707):
    """
    Authentic Google Athletic Field lush mowed-stripe soccer pitch with razor-sharp white FIFA markings.
    Covers 60m x 36m pitch cleanly (U in [0,1] -> X in [-30,+30], V in [0,1] -> Y in [-18,+18]).
    """
    rng = np.random.default_rng(seed)
    n = _fbm_2d(h, w, rng, (8, 20, 44))
    yy, xx = np.mgrid[0:h, 0:w]
    # World meters on the 60m x 36m pitch surface
    px = (xx / float(w - 1) - 0.5) * 60.0
    py = (yy / float(h - 1) - 0.5) * 36.0

    # Alternating lush mowed emerald & sunlit bright-turf bands (12 crisp 5m bands)
    stripe_band = (np.floor((px + 30.0) / 5.0).astype(np.int32) % 2) == 0
    r = np.where(stripe_band, 0.165, 0.215) + 0.040 * (n - 0.5)
    g = np.where(stripe_band, 0.455, 0.530) + 0.055 * (n - 0.5)
    b = np.where(stripe_band, 0.155, 0.185) + 0.030 * (n - 0.5)

    # Subtle authentic worn grass touch around penalty spots & goal mouths
    for sgn in (-1.0, 1.0):
        d_mouth = np.hypot((px - sgn * 26.8) * 1.4, py * 0.7)
        wear = np.clip(1.0 - d_mouth / 3.2, 0.0, 1.0) * 0.18
        r = r * (1.0 - wear) + 0.40 * wear
        g = g * (1.0 - wear) + 0.44 * wear
        b = b * (1.0 - wear) + 0.24 * wear

    # Pitch markings (playing field 54m x 32m inside 60m x 36m turf apron -> X in [-27,+27], Y in [-16,+16])
    L2, W2 = 27.0, 16.0
    lw = 0.20  # Crisp 20cm painted white chalk line (clearly visible from aerial & ground!)
    in_x = np.abs(px) <= L2 + lw
    in_y = np.abs(py) <= W2 + lw

    # Outer touchlines & goal lines
    outer = (
        ((np.abs(np.abs(px) - L2) <= lw) & in_y)
        | ((np.abs(np.abs(py) - W2) <= lw) & in_x)
    )
    # Halfway line + center circle (r = 5.4m) + center spot
    halfway = (np.abs(px) <= lw) & in_y
    r_center = np.hypot(px, py)
    center_circle = np.abs(r_center - 5.4) <= lw
    center_spot = r_center <= 0.42

    # Penalty areas (10.2m deep x 20.4m wide -> |x| in [16.8, 27], |y| <= 10.2)
    pen_x = L2 - 10.2
    pen_y = 10.2
    pen_box = (
        ((np.abs(np.abs(px) - pen_x) <= lw) & (np.abs(py) <= pen_y + lw))
        | ((np.abs(np.abs(py) - pen_y) <= lw) & (np.abs(px) >= pen_x - lw) & (np.abs(px) <= L2 + lw))
    )
    # 6-yard Goal boxes (3.6m deep x 10.4m wide)
    goal_x = L2 - 3.6
    goal_y = 5.2
    goal_box = (
        ((np.abs(np.abs(px) - goal_x) <= lw) & (np.abs(py) <= goal_y + lw))
        | ((np.abs(np.abs(py) - goal_y) <= lw) & (np.abs(px) >= goal_x - lw) & (np.abs(px) <= L2 + lw))
    )
    # Penalty spots & penalty arcs
    d_pen_l = np.hypot(px + (L2 - 7.0), py)
    d_pen_r = np.hypot(px - (L2 - 7.0), py)
    pen_spots = (d_pen_l <= 0.34) | (d_pen_r <= 0.34)
    pen_arcs = (
        ((np.abs(d_pen_l - 4.8) <= lw) & (px > -pen_x))
        | ((np.abs(d_pen_r - 4.8) <= lw) & (px < pen_x))
    )
    # Corner arcs (r = 1.1m)
    corner_arcs = np.zeros_like(outer)
    for sx in (-L2, L2):
        for sy in (-W2, W2):
            dc = np.hypot(px - sx, py - sy)
            corner_arcs |= (np.abs(dc - 1.15) <= lw) & (np.abs(px) <= L2) & (np.abs(py) <= W2)

    lines = outer | halfway | center_circle | center_spot | pen_box | goal_box | pen_spots | pen_arcs | corner_arcs
    r = np.where(lines, 0.96, r)
    g = np.where(lines, 0.98, g)
    b = np.where(lines, 0.96, b)

    return make_packed_image(name, np.stack([r, g, b], axis=-1).astype(np.float32))


# ---------------------------------------------------------------------------
# Material & BMesh Geometry Helpers
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


def apply_box_uv(bm, scale=0.22):
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
    uv_layer = bm.loops.layers.uv.verify()
    coords = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    for f in bm.faces:
        for i, loop in enumerate(f.loops):
            loop[uv_layer].uv = coords[i % 4]


def finalize_mesh(name, bm, mat, smooth=False, uv_scale=0.22, keep_existing_uv=False):
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


def bm_add_sphere(bm, center, rx, ry=None, rz=None, u_segs=12, v_segs=8):
    ry = rx if ry is None else ry
    rz = rx if rz is None else rz
    mat = Matrix.Translation(Vector(center)) @ Matrix.Diagonal((rx, ry, rz, 1.0))
    return bmesh.ops.create_uvsphere(bm, u_segments=u_segs, v_segments=v_segs, radius=1.0, matrix=mat)["verts"]


def ensure_ccw_2d(pts):
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
        bis = n1 + n2
        bis = n1 if bis.length < 1e-4 else bis.normalized()
        denom = max(0.35, bis.dot(n1))
        out.append((p_curr.x + bis.x * dist / denom, p_curr.y + bis.y * dist / denom))
    return out


def bm_add_polygon_prism(bm, pts_2d, z0, z1, cap_bottom=True, cap_top=True):
    pts = ensure_ccw_2d(pts_2d)
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


def export_asset(filename, ground_auto=False):
    objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not objs:
        raise RuntimeError(f"No mesh objects to export for {filename}")

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

    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]

    out_path = os.path.join(OUT_DIR, filename)
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
    size_kb = os.path.getsize(out_path) / 1024.0
    dims = max_co - min_co
    return {
        "file": filename,
        "kb": size_kb,
        "tris": total_tris,
        "dims": (dims.x, dims.y, dims.z),
        "min_co": (min_co.x, min_co.y, min_co.z),
        "max_co": (max_co.x, max_co.y, max_co.z),
        "meshes": len(objs),
    }


# ---------------------------------------------------------------------------
# Reusable Hollow Playable Mountain View Google Office Wing Engine
# ---------------------------------------------------------------------------
def add_exterior_staircase(bm_conc, bm_metal, base_pos, run_dir, out_dir, height=6.4, width=2.4):
    """Exterior walkable concrete & steel staircase rising 0.0m -> +6.4m with top landing."""
    p0 = Vector(base_pos)
    run_v = Vector(run_dir).normalized()
    out_v = Vector(out_dir).normalized()
    yaw = math.atan2(run_v.y, run_v.x)

    n_steps = 12
    total_run = 10.2
    step_d = total_run / n_steps
    step_h = height / n_steps

    for i in range(n_steps):
        z_top = (i + 1) * step_h
        z_bot = max(0.0, z_top - step_h - 0.14)
        h_box = z_top - z_bot
        d_center = (i + 0.5) * step_d
        c = p0 + run_v * d_center + out_v * (width * 0.52)
        bm_add_box(bm_conc, (c.x, c.y, z_bot + h_box * 0.5), (step_d * 1.06, width, h_box), rot_euler=(0, 0, yaw))
        if i in (5, 11):
            for w_frac in (0.14, 0.86):
                pc = p0 + run_v * d_center + out_v * (width * w_frac)
                bm_add_box(bm_metal, (pc.x, pc.y, (z_top - 0.1) * 0.5), (0.14, 0.14, z_top - 0.1), rot_euler=(0, 0, yaw))

    top_c = p0 + run_v * (total_run + 1.15) + out_v * (width * 0.52)
    bm_add_box(bm_conc, (top_c.x, top_c.y, height - 0.14), (2.45, width + 0.25, 0.28), rot_euler=(0, 0, yaw))

    rail_h = 1.05
    for w_frac in (0.08, 0.96):
        r0 = p0 + out_v * (width * w_frac) + Vector((0, 0, rail_h))
        r1 = p0 + run_v * total_run + out_v * (width * w_frac) + Vector((0, 0, height + rail_h))
        r2 = p0 + run_v * (total_run + 2.25) + out_v * (width * w_frac) + Vector((0, 0, height + rail_h))
        bm_add_prism_between(bm_metal, r0, r1, 0.032, 0.032, segs=4)
        if w_frac > 0.5:
            bm_add_prism_between(bm_metal, r1, r2, 0.032, 0.032, segs=4)
        for k in range(4):
            ft = k / 3.0
            pb = p0 + run_v * (ft * total_run) + out_v * (width * w_frac) + Vector((0, 0, ft * height))
            bm_add_box(bm_metal, (pb.x, pb.y, pb.z + rail_h * 0.5), (0.05, 0.05, rail_h), rot_euler=(0, 0, yaw))

    # Return exact ramp & landing center coordinates in Blender space + yaw for Three.js collider sync
    ramp_c = p0 + run_v * (total_run * 0.5) + out_v * (width * 0.52)
    return {
        "ramp_b": (ramp_c.x, ramp_c.y, height * 0.5),
        "landing_b": (top_c.x, top_c.y, height - 0.14),
        "yaw": yaw,
        "run_len": total_run + 0.2,
        "width": width + 0.1,
    }


def make_office_palette(prefix, accent_hex, roof_hex="#C6CCD4", conc_tint=(0.86, 0.83, 0.77), seed=720):
    tex_conc = gen_concrete_tex(f"{prefix}_ConcTex", 96, tint=conc_tint, seed=seed)
    tex_solar = gen_solar_panel_tex(f"{prefix}_SolarTex", 128, seed=seed + 1)
    tex_oak = gen_oak_floor_tex(f"{prefix}_OakTex", 96, seed=seed + 3)
    tex_cedar = gen_cedar_wood_tex(f"{prefix}_CedarTex", 96, seed=seed + 4)

    mats = {
        "conc": make_pbr_mat(f"{prefix}_Concrete", base_color=hex_to_linear("#E2DDD3"), roughness=0.76, tex_img=tex_conc),
        "roof": make_pbr_mat(f"{prefix}_RoofDeck", base_color=hex_to_linear(roof_hex), roughness=0.80, tex_img=tex_conc, tex_tint=hex_to_linear(roof_hex)),
        "floor_conc": make_pbr_mat(f"{prefix}_FloorConc", base_color=hex_to_linear("#DDD8CF"), roughness=0.58, tex_img=tex_conc),
        "floor_oak": make_pbr_mat(f"{prefix}_FloorOak", base_color=(1, 1, 1, 1), roughness=0.54, tex_img=tex_oak),
        "int_wall": make_pbr_mat(f"{prefix}_InteriorWall", base_color=hex_to_linear("#F0EDE7"), roughness=0.82),
        "ceiling": make_pbr_mat(f"{prefix}_Ceiling", base_color=hex_to_linear("#ECEFF3"), roughness=0.88),
        "led": make_pbr_mat(f"{prefix}_LED", base_color=hex_to_linear("#FFF8EA"), roughness=0.20, emission=hex_to_linear("#FFF1D6"), emission_strength=2.4),
        "glass_up": make_pbr_mat(f"{prefix}_GlassUp", base_color=hex_to_linear("#4B94D8", alpha=0.56), metallic=0.34, roughness=0.07, ior=1.52, alpha=0.56, specular=0.90, double_sided=True),
        "glass_lo": make_pbr_mat(f"{prefix}_GlassLo", base_color=hex_to_linear("#7CC4F6", alpha=0.34), metallic=0.18, roughness=0.06, ior=1.52, alpha=0.34, specular=0.88, double_sided=True),
        "alum": make_pbr_mat(f"{prefix}_Aluminum", base_color=hex_to_linear("#C8CFD8"), metallic=0.82, roughness=0.28),
        "dark": make_pbr_mat(f"{prefix}_DarkSteel", base_color=hex_to_linear("#323B48"), metallic=0.78, roughness=0.36),
        "accent": make_pbr_mat(f"{prefix}_Accent", base_color=hex_to_linear(accent_hex), metallic=0.22, roughness=0.40),
        "solar": make_pbr_mat(f"{prefix}_Solar", base_color=(1, 1, 1, 1), metallic=0.38, roughness=0.18, tex_img=tex_solar),
        "cedar": make_pbr_mat(f"{prefix}_Cedar", base_color=(1, 1, 1, 1), roughness=0.68, tex_img=tex_cedar),
        "plaza": make_pbr_mat(f"{prefix}_PlazaStone", base_color=hex_to_linear("#E4DED2"), roughness=0.76, tex_img=tex_conc),
        "shrub": make_pbr_mat(f"{prefix}_Landscaping", base_color=hex_to_linear("#346E36"), roughness=0.84),
        "water": make_pbr_mat(f"{prefix}_ReflectPool", base_color=hex_to_linear("#2E86C1"), metallic=0.15, roughness=0.06, ior=1.333, specular=0.92),
    }
    bms = {k: bmesh.new() for k in mats}
    return mats, bms


def add_hollow_office_wing(
    bms,
    poly_2d,
    doorways=None,
    stair_specs=None,
    interior_cols=None,
    solar_density=1.0,
    solar_yaw=0.0,
    arched_lobbies=False,
    arcade_edges=None,
    roof_z=6.40,
    parapet_z=7.20,
    wall_thk=0.45,
    world_offset=(0.0, 0.0),
    wing_label="Wing",
):
    """
    Build a complete hollow playable 2-story Google office wing into shared bms:
      - Ground floor slab (0.00..0.04m) + interior warm oak zone (0.042..0.056m)
      - Acoustic ceiling (5.75..6.02m) + walkable roof deck (6.02..6.40m)
      - Hollow 0.45m perimeter walls with 6-7.2m open glass lobby cutouts (0.04..3.60m)
      - Optional vaulted lobby arches or cantilevered 2nd-story arcade colonnade
      - Exterior walkable staircases (0 -> 6.40m) with parapet gaps
      - Rooftop angled solar cover arrays, HVAC units, skylight monitor
    """
    poly = ensure_ccw_2d(poly_2d)
    n = len(poly)
    doorways = doorways or []
    stair_specs = stair_specs or []
    interior_cols = interior_cols or []
    arcade_edges = set(arcade_edges or [])
    wx0, wz0 = world_offset

    ceil_z = 5.75
    door_h = 3.60
    half_wall = wall_thk * 0.5

    inner_ceil = inset_poly(poly, 0.44)
    oak_zone = inset_poly(poly, 2.00)

    # 1. Ground Floor Slab & Oak Floor
    bm_add_polygon_prism(bms["floor_conc"], poly, 0.00, 0.04, cap_bottom=True, cap_top=True)
    if len(oak_zone) >= 3:
        bm_add_polygon_prism(bms["floor_oak"], oak_zone, 0.042, 0.056, cap_bottom=False, cap_top=True)

    # 2. Ceiling & Walkable Roof Deck
    bm_add_polygon_prism(bms["ceiling"], inner_ceil, ceil_z, 6.02, cap_bottom=True, cap_top=False)
    bm_add_polygon_prism(bms["roof"], poly, 6.02, roof_z, cap_bottom=True, cap_top=True)

    doors_by_edge = {}
    for e_idx, d0, d1 in doorways:
        doors_by_edge.setdefault(e_idx, []).append((d0, d1))
    for k in doors_by_edge:
        doors_by_edge[k].sort()

    stairs_by_edge = {}
    for e_idx, st_t in stair_specs:
        stairs_by_edge[e_idx] = st_t

    stair_infos = []
    door_logs = []

    for i in range(n):
        pA = Vector((poly[i][0], poly[i][1], 0.0))
        pB = Vector((poly[(i + 1) % n][0], poly[(i + 1) % n][1], 0.0))
        edge_v = pB - pA
        L = edge_v.length
        if L < 0.8:
            continue
        t_dir = edge_v / L
        out_n = Vector((t_dir.y, -t_dir.x, 0.0))
        yaw = math.atan2(t_dir.y, t_dir.x)
        mid_e = (pA + pB) * 0.5

        edge_doors = doors_by_edge.get(i, [])
        solid_segs = []
        cursor = 0.0
        for d0, d1 in edge_doors:
            if d0 > cursor + 0.05:
                solid_segs.append((cursor, d0))
            cursor = max(cursor, d1)
        if L > cursor + 0.05:
            solid_segs.append((cursor, L))

        # Corner pier sealing vertices
        bm_add_box(bms["conc"], (pA.x - out_n.x * 0.04, pA.y - out_n.y * 0.04, parapet_z * 0.5), (0.90, 0.90, parapet_z), rot_euler=(0, 0, yaw))

        # Mid-story spandrel ring & Google accent fascia ribbons
        sp_c = mid_e - out_n * half_wall
        bm_add_box(bms["conc"], (sp_c.x, sp_c.y, 3.76), (L + 0.08, wall_thk, 0.40), rot_euler=(0, 0, yaw))
        bm_add_box(bms["accent"], (mid_e.x + out_n.x * 0.05, mid_e.y + out_n.y * 0.05, 3.76), (L - 0.5, 0.12, 0.22), rot_euler=(0, 0, yaw))
        bm_add_box(bms["accent"], (mid_e.x + out_n.x * 0.05, mid_e.y + out_n.y * 0.05, 6.24), (L - 0.5, 0.12, 0.20), rot_euler=(0, 0, yaw))

        # Upper-story continuous glass & aluminum transom
        bm_add_box(bms["glass_up"], (mid_e.x - out_n.x * 0.24, mid_e.y - out_n.y * 0.24, 4.99), (L - 0.4, 0.06, 2.06), rot_euler=(0, 0, yaw))
        bm_add_box(bms["alum"], (mid_e.x - out_n.x * 0.24, mid_e.y - out_n.y * 0.24, 4.98), (L - 0.6, 0.16, 0.08), rot_euler=(0, 0, yaw))
        bm_add_box(bms["int_wall"], (sp_c.x, sp_c.y, 5.88), (L - 0.4, wall_thk, 0.28), rot_euler=(0, 0, yaw))

        # Lower-floor solid segments (skipping open doorway intervals!)
        for s0, s1 in solid_segs:
            seg_len = s1 - s0
            if seg_len < 0.25:
                continue
            sc = pA + t_dir * ((s0 + s1) * 0.5)
            bm_add_box(bms["conc"], (sc.x - out_n.x * 0.12, sc.y - out_n.y * 0.12, 0.50), (seg_len, 0.24, 1.00), rot_euler=(0, 0, yaw))
            bm_add_box(bms["int_wall"], (sc.x - out_n.x * 0.34, sc.y - out_n.y * 0.34, 0.52), (seg_len, 0.22, 0.96), rot_euler=(0, 0, yaw))
            bm_add_box(bms["alum"], (sc.x - out_n.x * half_wall, sc.y - out_n.y * half_wall, 1.02), (seg_len, wall_thk + 0.04, 0.06), rot_euler=(0, 0, yaw))
            bm_add_box(bms["glass_lo"], (sc.x - out_n.x * 0.22, sc.y - out_n.y * 0.22, 2.30), (seg_len, 0.06, 2.52), rot_euler=(0, 0, yaw))
            bm_add_box(bms["alum"], (sc.x - out_n.x * 0.22, sc.y - out_n.y * 0.22, 2.34), (seg_len, 0.15, 0.08), rot_euler=(0, 0, yaw))

        def in_door(s_val, margin=0.35):
            return any((d0 - margin) <= s_val <= (d1 + margin) for d0, d1 in edge_doors)

        # Curtain-wall mullions & periodic concrete pilasters
        bay_spacing = 5.4
        n_bays = max(2, int(round(L / bay_spacing)))
        for b in range(1, n_bays):
            s_pos = L * (b / float(n_bays))
            pm = pA + t_dir * s_pos
            if in_door(s_pos):
                bm_add_box(bms["alum"], (pm.x - out_n.x * 0.24, pm.y - out_n.y * 0.24, 4.99), (0.11, 0.18, 2.06), rot_euler=(0, 0, yaw))
            elif b % 4 == 0 and L > 16.0:
                bm_add_box(bms["conc"], (pm.x - out_n.x * 0.18, pm.y - out_n.y * 0.18, roof_z * 0.5), (0.64, 0.46, roof_z), rot_euler=(0, 0, yaw))
            else:
                bm_add_box(bms["alum"], (pm.x - out_n.x * 0.22, pm.y - out_n.y * 0.22, 3.52), (0.11, 0.20, 5.04), rot_euler=(0, 0, yaw))

        # Open Lobby Doorway Portals (with optional signature architectural lobby arches or shaded brow!)
        for d0, d1 in edge_doors:
            d_w = d1 - d0
            dm = pA + t_dir * (0.5 * (d0 + d1))
            p_d0 = pA + t_dir * d0
            p_d1 = pA + t_dir * d1
            door_logs.append((i, d0, d1, d_w, (wx0 + dm.x, wz0 - dm.y)))

            for dp in (p_d0, p_d1):
                bm_add_box(bms["alum"], (dp.x - out_n.x * half_wall, dp.y - out_n.y * half_wall, door_h * 0.5 + 0.02), (0.20, wall_thk + 0.12, door_h), rot_euler=(0, 0, yaw))
            bm_add_box(bms["dark"], (dm.x - out_n.x * (half_wall - 0.04), dm.y - out_n.y * (half_wall - 0.04), door_h + 0.16), (d_w + 0.36, wall_thk + 0.26, 0.34), rot_euler=(0, 0, yaw))
            bm_add_box(bms["led"], (dm.x + out_n.x * 0.20, dm.y + out_n.y * 0.20, door_h + 0.16), (d_w - 0.6, 0.05, 0.10), rot_euler=(0, 0, yaw))
            bm_add_box(bms["alum"], (dm.x - out_n.x * half_wall, dm.y - out_n.y * half_wall, 0.048), (d_w, wall_thk + 0.06, 0.014), rot_euler=(0, 0, yaw))

            if arched_lobbies:
                # Architectural segmented arch portal framing the Alta lobby openings!
                arch_c = dm + out_n * 0.35
                n_arch = 5
                rad_x = d_w * 0.5 + 0.35
                for k in range(n_arch):
                    a0 = math.pi * (k / float(n_arch))
                    a1 = math.pi * ((k + 1) / float(n_arch))
                    ap0 = arch_c + t_dir * (-rad_x * math.cos(a0)) + Vector((0, 0, 3.05 + 1.15 * math.sin(a0)))
                    ap1 = arch_c + t_dir * (-rad_x * math.cos(a1)) + Vector((0, 0, 3.05 + 1.15 * math.sin(a1)))
                    bm_add_prism_between(bms["conc"], ap0, ap1, 0.24, 0.24, segs=4)
                for dp in (p_d0, p_d1):
                    ap = dp + out_n * 0.35
                    bm_add_box(bms["conc"], (ap.x, ap.y, 1.55), (0.48, 0.52, 3.10), rot_euler=(0, 0, yaw))
            elif i not in arcade_edges:
                bc = dm + out_n * 1.15
                bm_add_box(bms["alum"], (bc.x, bc.y, 3.80), (d_w + 1.4, 2.30, 0.18), rot_euler=(0, 0, yaw))
                bm_add_box(bms["accent"], (bc.x + out_n.x * 1.15, bc.y + out_n.y * 1.15, 3.80), (d_w + 1.44, 0.08, 0.20), rot_euler=(0, 0, yaw))

        # Optional Cantilevered Ground-Floor Arcade Colonnade along front facade!
        if i in arcade_edges:
            arc_d = 3.6
            ac = mid_e + out_n * (arc_d * 0.5)
            bm_add_box(bms["conc"], (ac.x, ac.y, 3.86), (L + 0.4, arc_d, 0.32), rot_euler=(0, 0, yaw))
            bm_add_box(bms["cedar"], (ac.x, ac.y, 3.67), (L, arc_d - 0.3, 0.08), rot_euler=(0, 0, yaw))
            bm_add_box(bms["accent"], (ac.x + out_n.x * (arc_d * 0.5), ac.y + out_n.y * (arc_d * 0.5), 3.86), (L + 0.46, 0.10, 0.26), rot_euler=(0, 0, yaw))
            n_cols = max(3, int(round(L / 10.0)))
            for k in range(n_cols + 1):
                s_c = 1.6 + (L - 3.2) * (k / float(n_cols))
                if in_door(s_c, margin=0.6):
                    continue
                cp = pA + t_dir * s_c + out_n * (arc_d - 0.55)
                bm_add_prism_between(bms["conc"], (cp.x, cp.y, 0.0), (cp.x, cp.y, 3.70), 0.26, 0.22, segs=6)

        # Brise-soleil aluminum sun louvers (skip stair edge)
        has_stair = i in stairs_by_edge
        if not has_stair and L > 10.0:
            for lz in (3.70, 6.00):
                lc = mid_e + out_n * 0.44
                bm_add_box(bms["alum"], (lc.x, lc.y, lz), (L - 1.2, 0.42, 0.06), rot_euler=(0, 0, yaw))

        # Rooftop parapet (preserving stair cutout!)
        if has_stair:
            st_t = stairs_by_edge[i]
            stair_start = max(1.4, min(L - 13.4, L * st_t))
            gap_a = min(L - 1.0, stair_start + 10.0)
            gap_b = min(L - 0.4, stair_start + 12.6)
            segs = []
            if gap_a > 0.6:
                segs.append((0.0, gap_a))
            if L - gap_b > 0.6:
                segs.append((gap_b, L))
            stair_infos.append((pA + t_dir * stair_start, t_dir, out_n))
        else:
            segs = [(0.0, L)]

        for s0, s1 in segs:
            seg_len = s1 - s0
            sc = pA + t_dir * ((s0 + s1) * 0.5) - out_n * 0.20
            bm_add_box(bms["conc"], (sc.x, sc.y, (roof_z + parapet_z) * 0.5), (seg_len, 0.40, parapet_z - roof_z), rot_euler=(0, 0, yaw))
            bm_add_box(bms["dark"], (sc.x, sc.y, parapet_z + 0.045), (seg_len + 0.06, 0.48, 0.09), rot_euler=(0, 0, yaw))

    # 3. Interior Structural Columns & Suspended LED Ceiling Strips
    for cx, cy in interior_cols:
        bm_add_prism_between(bms["int_wall"], (cx, cy, 0.04), (cx, cy, ceil_z), 0.28, 0.26, segs=6)

    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    cx_m, cy_m = 0.5 * (min_x + max_x), 0.5 * (min_y + max_y)
    cy_cos, cy_sin = math.cos(solar_yaw), math.sin(solar_yaw)

    for lx in np.arange(min_x + 5.0, max_x - 4.0, 12.5):
        for ly in np.arange(min_y + 5.0, max_y - 4.0, 11.0):
            if point_in_poly_2d(lx, ly, poly) and min_dist_to_poly_edges(lx, ly, poly) > 3.8:
                bm_add_box(bms["led"], (lx, ly, ceil_z - 0.12), (4.6, 0.26, 0.07), rot_euler=(0, 0, solar_yaw))

    # 4. Exterior Staircases
    built_stairs = []
    for st_base, st_run, st_out in stair_infos:
        built_stairs.append(add_exterior_staircase(bms["conc"], bms["alum"], st_base, st_run, st_out, height=roof_z, width=2.4))

    # 5. Rooftop HVAC Units, Skylight Monitor & Angled Solar Arrays
    placed_hvacs = []
    hvac_pts = [(cx_m - 10.0, cy_m), (cx_m + 10.0, cy_m), (cx_m, cy_m - 8.0), (cx_m, cy_m + 8.0)]
    for hx, hy in hvac_pts:
        if len(placed_hvacs) >= 2:
            break
        if point_in_poly_2d(hx, hy, poly) and min_dist_to_poly_edges(hx, hy, poly) > 4.2:
            bm_add_box(bms["alum"], (hx, hy, roof_z + 0.70), (3.8, 2.4, 1.40), rot_euler=(0, 0, solar_yaw))
            bm_add_box(bms["dark"], (hx, hy, roof_z + 0.72), (3.88, 1.8, 0.80), rot_euler=(0, 0, solar_yaw))
            for fo in (-0.90, 0.90):
                fx = hx + cy_cos * fo
                fy = hy + cy_sin * fo
                bm_add_prism_between(bms["dark"], (fx, fy, roof_z + 1.40), (fx, fy, roof_z + 1.66), 0.48, 0.44, segs=6)
            placed_hvacs.append((hx, hy))

    # Central rooftop glass skylight monitor
    if point_in_poly_2d(cx_m, cy_m, poly) and min_dist_to_poly_edges(cx_m, cy_m, poly) > 5.0 and not any(math.hypot(cx_m - hx, cy_m - hy) < 4.5 for hx, hy in placed_hvacs):
        bm_add_box(bms["alum"], (cx_m, cy_m, roof_z + 0.34), (6.4, 3.2, 0.68), rot_euler=(0, 0, solar_yaw))
        bm_add_box(bms["glass_up"], (cx_m, cy_m, roof_z + 0.70), (6.0, 2.8, 0.14), rot_euler=(0, 0, solar_yaw))
        placed_hvacs.append((cx_m, cy_m))

    # Sleek continuous solar array rows (compact geometry, razor-sharp aerial & ground readability!)
    step_u = 8.4 if solar_density >= 1.0 else 10.2
    step_v = 5.8 if solar_density >= 1.0 else 7.4
    pw, pd = 7.0, 2.6
    tilt = 0.26
    span_u = max(max_x - min_x, max_y - min_y) * 0.65
    for lu in np.arange(-span_u, span_u + 0.1, step_u):
        for lv in np.arange(-span_u, span_u + 0.1, step_v):
            wx = cx_m + lu * cy_cos - lv * cy_sin
            wy = cy_m + lu * cy_sin + lv * cy_cos
            if not point_in_poly_2d(wx, wy, poly) or min_dist_to_poly_edges(wx, wy, poly) < 3.0:
                continue
            if any(math.hypot(wx - hx, wy - hy) < 5.0 for hx, hy in placed_hvacs):
                continue
            ok = True
            for dx in (-pw * 0.5, pw * 0.5):
                for dy in (-pd * 0.5, pd * 0.5):
                    px = wx + dx * cy_cos - dy * cy_sin
                    py = wy + dx * cy_sin + dy * cy_cos
                    if not point_in_poly_2d(px, py, poly) or min_dist_to_poly_edges(px, py, poly) < 1.6:
                        ok = False
                        break
                if not ok:
                    break
            if not ok:
                continue
            bm_add_box(bms["solar"], (wx, wy, roof_z + 0.76), (pw, pd, 0.08), rot_euler=(tilt, 0.0, solar_yaw))
            # Twin dark steel rack supports underneath panel row (box stanchions = crisp & compact!)
            for sx_o in (-pw * 0.34, pw * 0.34):
                px = wx + sx_o * cy_cos
                py = wy + sx_o * cy_sin
                bm_add_box(bms["dark"], (px, py, roof_z + 0.36), (0.14, pd * 0.72, 0.72), rot_euler=(0.0, 0.0, solar_yaw))

    # Emit exact Three.js collider summary to stdout
    three_poly = [(round(wx0 + p[0], 2), round(wz0 - p[1], 2)) for p in poly]
    print(f"  [WING {wing_label}] ThreeJS_POLY={three_poly}")
    for e_idx, d0, d1, dw, mw in door_logs:
        print(f"    [DOOR {wing_label}] edge={e_idx} dist=[{d0:.2f},{d1:.2f}] w={dw:.2f}m mid_ThreeJS=({mw[0]:.2f},{mw[1]:.2f})")
    for si, st in enumerate(built_stairs):
        rb = st["ramp_b"]
        lb = st["landing_b"]
        print(
            f"    [STAIR {wing_label}#{si}] ramp_ThreeJS=({wx0+rb[0]:.2f}, {rb[2]:.2f}, {wz0-rb[1]:.2f}) "
            f"landing_ThreeJS=({wx0+lb[0]:.2f}, {lb[2]:.2f}, {wz0-lb[1]:.2f}) rotY={st['yaw']:.4f}"
        )


def finalize_office_bms(prefix, mats, bms):
    apply_face_unit_uv(bms["solar"])
    for key, mat in mats.items():
        keep_uv = key == "solar"
        smooth = key in ("water",)
        finalize_mesh(f"{prefix}_{key}", bms[key], mat, smooth=smooth, uv_scale=0.22, keep_existing_uv=keep_uv)


# ===========================================================================
# 1. SHORELINE AMPHITHEATRE (~64m x 56m, peaks +18.0m, baked SE facing)
# ===========================================================================
def build_shoreline_amphitheatre():
    reset_scene()

    tex_tent = gen_tent_fabric_tex("ShoreAmph_TentTex", 192, seed=801)
    tex_conc = gen_concrete_tex("ShoreAmph_ConcTex", 128, tint=(0.86, 0.83, 0.77), seed=802)
    tex_cedar = gen_cedar_wood_tex("ShoreAmph_CedarTex", 128, seed=803)

    mat_tent = make_pbr_mat(
        "ShoreAmph_TentMembrane",
        base_color=(1.0, 1.0, 1.0, 1.0),
        roughness=0.52,
        specular=0.45,
        tex_img=tex_tent,
        double_sided=True,
    )
    mat_mast = make_pbr_mat("ShoreAmph_WhiteSteel", base_color=hex_to_linear("#E8EDF4"), metallic=0.55, roughness=0.28)
    mat_dark = make_pbr_mat("ShoreAmph_DarkSteel", base_color=hex_to_linear("#262D38"), metallic=0.82, roughness=0.34)
    mat_conc = make_pbr_mat("ShoreAmph_Concrete", base_color=hex_to_linear("#DED8CC"), roughness=0.78, tex_img=tex_conc)
    mat_seat = make_pbr_mat("ShoreAmph_TerraceSeat", base_color=hex_to_linear("#3A5B82"), roughness=0.68)
    mat_stage = make_pbr_mat("ShoreAmph_StageWood", base_color=(1, 1, 1, 1), roughness=0.62, tex_img=tex_cedar)
    mat_acoustic = make_pbr_mat("ShoreAmph_AcousticShell", base_color=hex_to_linear("#1E2430"), roughness=0.74)
    mat_light = make_pbr_mat("ShoreAmph_StageLight", base_color=hex_to_linear("#FFF6D8"), roughness=0.2, emission=hex_to_linear("#FFE090"), emission_strength=3.2)
    mat_beacon = make_pbr_mat("ShoreAmph_PeakBeacon", base_color=hex_to_linear("#EA4335"), roughness=0.25, emission=hex_to_linear("#EA4335"), emission_strength=2.4)
    mat_lawn = make_pbr_mat("ShoreAmph_BowlTurf", base_color=hex_to_linear("#3E7C3A"), roughness=0.88)

    bm_tent = bmesh.new()
    bm_mast = bmesh.new()
    bm_dark = bmesh.new()
    bm_conc = bmesh.new()
    bm_seat = bmesh.new()
    bm_stage = bmesh.new()
    bm_acous = bmesh.new()
    bm_light = bmesh.new()
    bm_beacon = bmesh.new()
    bm_lawn = bmesh.new()

    # Built in local symmetry frame (stage toward +Y = North-local, concourse toward -Y = South-local),
    # then rotated by +32 deg around Z so entry concourse faces SE directly toward Bill Graham Pkwy & Lot C!
    amph_yaw = math.radians(32.0)
    rot_m = Euler((0.0, 0.0, amph_yaw), "XYZ").to_matrix().to_4x4()

    def pt(x, y, z):
        return rot_m @ Vector((x, y, z))

    def rot_xy(x, y):
        v = rot_m @ Vector((x, y, 0.0))
        return (v.x, v.y)

    # 1. Grounded Fan-Shaped Concrete Concourse & Amphitheatre Plaza Apron (Z = 0.00..0.16m)
    apron_pts = []
    # Smooth stadium fan contour (~64m wide x 56m deep)
    for i in range(36):
        ang = 2.0 * math.pi * i / 36.0
        # Wider along SE seating arc (-Y), slightly narrower around NW backstage (+Y)
        ca, sa = math.cos(ang), math.sin(ang)
        rx = 31.8 if sa < 0 else (31.8 - 6.0 * (sa ** 1.6))
        ry = 28.0 if sa < 0 else 26.5
        apron_pts.append(rot_xy(ca * rx, sa * ry))
    bm_add_polygon_prism(bm_conc, apron_pts, 0.00, 0.16, cap_bottom=True, cap_top=True)

    # 2. Open Acoustic Performance Stage (NW focus around local y = +14m, deck Z = 1.20m)
    stage_poly = [
        rot_xy(-11.5, 19.5),
        rot_xy(-13.5, 11.5),
        rot_xy(-8.0, 8.2),
        rot_xy(8.0, 8.2),
        rot_xy(13.5, 11.5),
        rot_xy(11.5, 19.5),
    ]
    bm_add_polygon_prism(bm_conc, stage_poly, 0.16, 1.08, cap_bottom=False, cap_top=True)
    bm_add_polygon_prism(bm_stage, stage_poly, 1.08, 1.22, cap_bottom=False, cap_top=True)

    # Twin side walkable ramps onto stage (left & right flanks, 0.16m -> 1.22m)
    for sgn in (-1.0, 1.0):
        for k in range(6):
            frac = (k + 0.5) / 6.0
            zh = 0.16 + frac * 1.06
            rx_l = sgn * (12.8 + (1.0 - frac) * 3.8)
            bm_add_box(bm_conc, pt(rx_l, 13.8, zh * 0.5 + 0.08), (0.78, 3.2, zh - 0.16), rot_euler=(0, 0, amph_yaw))

    # Curved Backstage Acoustic Shell & Green-Room Cover Wall (local y = +19.5..+24.0m, Z = 0.16..6.8m)
    n_baffle = 8
    for i in range(n_baffle):
        u0 = -1.0 + 2.0 * (i / float(n_baffle))
        u1 = -1.0 + 2.0 * ((i + 1) / float(n_baffle))
        um = 0.5 * (u0 + u1)
        x0, x1 = u0 * 13.5, u1 * 13.5
        y0 = 21.8 - 2.6 * (u0 * u0)
        y1 = 21.8 - 2.6 * (u1 * u1)
        mx, my = 0.5 * (x0 + x1), 0.5 * (y0 + y1)
        seg_l = math.hypot(x1 - x0, y1 - y0) + 0.12
        seg_yaw = math.atan2(y1 - y0, x1 - x0) + amph_yaw
        h_wall = 6.6 - 0.8 * (um * um)
        bm_add_box(bm_acous, pt(mx, my, 0.16 + h_wall * 0.5), (seg_l, 0.65, h_wall), rot_euler=(0, 0, seg_yaw))
        # Vertical cedar acoustic diffuser ribs on stage-facing interior side
        bm_add_box(bm_stage, pt(mx, my - 0.36, 1.22 + (h_wall - 1.1) * 0.5), (0.22, 0.14, h_wall - 1.1), rot_euler=(0, 0, seg_yaw))

    # Overhead Matte-Black Stage Lighting Truss Rig & Glowing Warm Stage Floodlights
    truss_z = 6.40
    for ty_l in (10.5, 16.5):
        bm_add_prism_between(bm_dark, pt(-11.5, ty_l, truss_z), pt(11.5, ty_l, truss_z), 0.14, 0.14, segs=6)
        bm_add_prism_between(bm_dark, pt(-11.5, ty_l, truss_z + 0.75), pt(11.5, ty_l, truss_z + 0.75), 0.12, 0.12, segs=6)
    for sx in (-11.0, -5.5, 0.0, 5.5, 11.0):
        bm_add_prism_between(bm_dark, pt(sx, 10.5, truss_z), pt(sx, 16.5, truss_z), 0.11, 0.11, segs=6)
        if abs(sx) > 9.0:
            bm_add_prism_between(bm_dark, pt(sx, 10.5, 1.22), pt(sx, 10.5, truss_z + 0.75), 0.16, 0.14, segs=6)
            bm_add_prism_between(bm_dark, pt(sx, 16.5, 1.22), pt(sx, 16.5, truss_z + 0.75), 0.16, 0.14, segs=6)
    # Warm glowing stage light bar
    bm_add_box(bm_light, pt(0.0, 10.35, truss_z - 0.12), (17.5, 0.24, 0.22), rot_euler=(0, 0, amph_yaw))

    # 3. Curved Terraced Amphitheatre Seating Bowl (7 stepped tiers arcing around stage focal point (0, 11.5))
    focal_y = 11.5
    n_tiers = 7
    arc_segs = 18
    ang_min = math.radians(-152.0)
    ang_max = math.radians(-28.0)

    for ti in range(n_tiers):
        r_in = 10.5 + ti * 2.55
        r_out = r_in + 2.58
        z_tier = 0.20 + (ti + 1) * 0.34  # Gently climbs 0.54m -> 2.58m!
        for ai in range(arc_segs):
            a0 = ang_min + (ang_max - ang_min) * (ai / float(arc_segs))
            a1 = ang_min + (ang_max - ang_min) * ((ai + 1) / float(arc_segs))
            am = 0.5 * (a0 + a1)
            # Leave 3 clean open walkable aisles (center -90 deg, left -126 deg, right -54 deg) as smooth concrete steps
            is_aisle = any(abs(math.degrees(am) - ad) < 5.5 for ad in (-90.0, -126.0, -54.0))
            p00 = rot_xy(r_in * math.cos(a0), focal_y + r_in * math.sin(a0))
            p10 = rot_xy(r_out * math.cos(a0), focal_y + r_out * math.sin(a0))
            p11 = rot_xy(r_out * math.cos(a1), focal_y + r_out * math.sin(a1))
            p01 = rot_xy(r_in * math.cos(a1), focal_y + r_in * math.sin(a1))
            bm_add_polygon_prism(bm_conc, [p00, p10, p11, p01], 0.16, z_tier, cap_bottom=False, cap_top=True)
            if not is_aisle:
                # Crisp Shoreline amphitheatre blue bench seating row on each tier
                rm = 0.5 * (r_in + r_out)
                seg_w = rm * (a1 - a0) * 0.88
                sx_l = rm * math.cos(am)
                sy_l = focal_y + rm * math.sin(am)
                seat_yaw = am + math.pi * 0.5 + amph_yaw
                bm_add_box(bm_seat, pt(sx_l, sy_l, z_tier + 0.28), (seg_w, 0.52, 0.44), rot_euler=(0, 0, seat_yaw))

    # Outer terraced lawn rim behind seating bowl (classic Shoreline grassy picnic slope!)
    for ai in range(arc_segs):
        a0 = ang_min + (ang_max - ang_min) * (ai / float(arc_segs))
        a1 = ang_min + (ang_max - ang_min) * ((ai + 1) / float(arc_segs))
        am = 0.5 * (a0 + a1)
        if abs(math.degrees(am) + 90.0) < 14.0:
            continue  # Wide open central concourse entry!
        r_in, r_out = 28.6, 33.4
        p00 = rot_xy(r_in * math.cos(a0), focal_y + r_in * math.sin(a0))
        p10 = rot_xy(r_out * math.cos(a0), focal_y + r_out * math.sin(a0))
        p11 = rot_xy(r_out * math.cos(a1), focal_y + r_out * math.sin(a1))
        p01 = rot_xy(r_in * math.cos(a1), focal_y + r_in * math.sin(a1))
        bm_add_polygon_prism(bm_lawn, [p00, p10, p11, p01], 0.16, 2.72, cap_bottom=False, cap_top=True)

    # 4. Iconic White Twin-Peak Tensioned-Fabric Shoreline Tent Roof (Dramatic Peaks at Z = 18.6m!)
    # Twin sharp circus/sail peaks at local (-13.2, +1.5) and (+13.2, +1.5) rising to +18.6m,
    # dipping steeply into a sculptural concave central saddle (~10.4m) and sweeping out to scalloped eaves (5.4..7.6m)!
    peak_l = (-13.2, 1.5)
    peak_r = (+13.2, 1.5)
    peak_h = 18.6

    def tent_z(x, y):
        d1 = math.hypot(x - peak_l[0], y - peak_l[1])
        d2 = math.hypot(x - peak_r[0], y - peak_r[1])
        # Authentic concave catenary sail profile: razor-sharp peaks sweeping gracefully down to eaves!
        h1 = 5.4 + (peak_h - 5.4) * math.exp(-0.088 * (d1 ** 1.08))
        h2 = 5.4 + (peak_h - 5.4) * math.exp(-0.088 * (d2 ** 1.08))
        # Smooth ridge union preserves crisp deep saddle valley (~10.6m) between the twin 18.6m peaks!
        z_base = max(h1, h2) + 1.15 * math.exp(-0.18 * abs(h1 - h2)) * math.exp(-0.045 * math.hypot(x, y - 1.5))
        # Scalloped tensioned edge dip between 14 perimeter tie-down masts
        r_norm = math.hypot(x / 30.8, (y - 1.5) / 24.4)
        ang = math.atan2(y - 1.5, x)
        scallop = -1.15 * (min(1.0, r_norm) ** 2.4) * (0.5 - 0.5 * math.cos(ang * 14.0))
        return max(5.2, min(peak_h, z_base + scallop))

    # Build dense smooth twin-lobe grid warped onto Shoreline's peanut/oval footprint
    # (grid lines pass directly over both peak_l and peak_r so twin spires read razor-sharp from every angle!)
    uv_tent = bm_tent.loops.layers.uv.verify()
    nu, nv = 28, 20
    u_vals = np.linspace(-1.0, 1.0, nu + 1)
    v_vals = np.linspace(-1.0, 1.0, nv + 1)
    t_grid = [[None] * (nv + 1) for _ in range(nu + 1)]

    def oval_map(u, v):
        # Elliptical disc mapping of [-1,1]^2 -> unit disk (Shirley-Chiu / squircle smooth map)
        mx = u * math.sqrt(max(0.0, 1.0 - 0.5 * v * v))
        my = v * math.sqrt(max(0.0, 1.0 - 0.5 * u * u))
        # Twin-lobe figure-8 Shoreline tent planform flare
        ang = math.atan2(my, mx)
        ca, sa = math.cos(ang), math.sin(ang)
        lobe = 1.0 + 0.08 * (ca * ca) - 0.06 * (sa * sa)
        lx = mx * 30.6 * lobe
        ly = 1.5 + my * 24.2 * lobe
        return lx, ly

    for iu, u in enumerate(u_vals):
        for iv, v in enumerate(v_vals):
            lx, ly = oval_map(float(u), float(v))
            lz = tent_z(lx, ly)
            t_grid[iu][iv] = (bm_tent.verts.new(pt(lx, ly, lz)), lx, ly, lz)

    for iu in range(nu):
        for iv in range(nv):
            v00 = t_grid[iu][iv][0]
            v10 = t_grid[iu + 1][iv][0]
            v11 = t_grid[iu + 1][iv + 1][0]
            v01 = t_grid[iu][iv + 1][0]
            f = bm_tent.faces.new((v00, v10, v11, v01))
            u0, u1 = (iu / float(nu)) * 3.0, ((iu + 1) / float(nu)) * 3.0
            vv0, vv1 = (iv / float(nv)) * 2.0, ((iv + 1) / float(nv)) * 2.0
            for lp, uv in zip(f.loops, ((u0, vv0), (u1, vv0), (u1, vv1), (u0, vv1))):
                lp[uv_tent].uv = uv

    # 5. Twin Iconic Steel Primary Mast Towers (+20.2m spires) + Crown Rings + Tension Cables
    mast_coords_local = [peak_l, peak_r]
    for mx_l, my_l in mast_coords_local:
        # Concrete mast foundation pedestal
        bm_add_prism_between(bm_conc, pt(mx_l, my_l, 0.0), pt(mx_l, my_l, 1.35), 0.95, 0.80, segs=10)
        # Main tapered white architectural steel mast soaring to +20.2m
        bm_add_prism_between(bm_mast, pt(mx_l, my_l, 1.25), pt(mx_l, my_l, 20.2), 0.46, 0.22, segs=10)
        # Structural dark steel compression collar ring crowning each tent spire!
        bm_add_prism_between(bm_dark, pt(mx_l, my_l, 17.6), pt(mx_l, my_l, 18.7), 1.15, 0.88, segs=12)
        # Red aviation tip beacon at pinnacle
        bm_add_sphere(bm_beacon, pt(mx_l, my_l, 20.4), 0.28, u_segs=8, v_segs=6)
        # 4 diagonal steel truss spreader struts bracing collar
        for ang_s in (0.4, 1.97, 3.54, 5.11):
            p_col = pt(mx_l, my_l, 15.0)
            tx_r = mx_l + math.cos(ang_s) * 2.6
            ty_r = my_l + math.sin(ang_s) * 2.6
            bm_add_prism_between(bm_mast, p_col, pt(tx_r, ty_r, tent_z(tx_r, ty_r) - 0.15), 0.09, 0.07, segs=5)

    # Central catenary ridge cable linking the two iconic peaks!
    for seg_i in range(6):
        f0 = seg_i / 6.0
        f1 = (seg_i + 1) / 6.0
        x0 = peak_l[0] + (peak_r[0] - peak_l[0]) * f0
        x1 = peak_l[0] + (peak_r[0] - peak_l[0]) * f1
        bm_add_prism_between(bm_dark, pt(x0, 1.5, tent_z(x0, 1.5) + 0.18), pt(x1, 1.5, tent_z(x1, 1.5) + 0.18), 0.07, 0.07, segs=5)

    # 14 Angled Perimeter Steel Tie-Down Masts + Anchored Guy Cables + Radial Ridge Cables!
    for k in range(14):
        ang = 2.0 * math.pi * k / 14.0
        ca, sa = math.cos(ang), math.sin(ang)
        lobe = 1.0 + 0.08 * (ca * ca) - 0.06 * (sa * sa)
        ex = ca * 30.6 * lobe
        ey = 1.5 + sa * 24.2 * lobe
        ez = tent_z(ex, ey)
        dir_out = Vector((ex, ey - 1.5, 0.0)).normalized()
        foot_x = ex + dir_out.x * 1.4
        foot_y = ey + dir_out.y * 1.4
        tip_x = ex + dir_out.x * 0.2
        tip_y = ey + dir_out.y * 0.2
        bm_add_prism_between(bm_conc, pt(foot_x, foot_y, 0.0), pt(foot_x, foot_y, 0.65), 0.48, 0.40, segs=6)
        bm_add_prism_between(bm_mast, pt(foot_x, foot_y, 0.55), pt(tip_x, tip_y, ez + 0.85), 0.18, 0.14, segs=6)
        anc_x = ex + dir_out.x * 3.8
        anc_y = ey + dir_out.y * 3.8
        bm_add_prism_between(bm_dark, pt(tip_x, tip_y, ez + 0.75), pt(anc_x, anc_y, 0.35), 0.045, 0.045, segs=4)
        bm_add_box(bm_conc, pt(anc_x, anc_y, 0.22), (0.85, 0.85, 0.44), rot_euler=(0, 0, amph_yaw))
        near_peak = peak_l if ex < 0 else peak_r
        bm_add_prism_between(bm_dark, pt(near_peak[0], near_peak[1], 18.65), pt(tip_x, tip_y, ez + 0.50), 0.055, 0.055, segs=4)

    # 6. Twin Entry Concourse Ticket & Concession Kiosks flanking SE Grand Entrance (tactical cover!)
    kiosk_locals = [(-11.5, -24.5), (11.5, -24.5)]
    for kx, ky in kiosk_locals:
        bm_add_box(bm_conc, pt(kx, ky, 1.75), (6.4, 3.2, 3.50), rot_euler=(0, 0, amph_yaw))
        bm_add_box(bm_stage, pt(kx, ky, 3.62), (7.4, 4.2, 0.26), rot_euler=(0, 0, amph_yaw))
        bm_add_box(bm_light, pt(kx, ky - 1.64, 2.85), (4.8, 0.08, 0.24), rot_euler=(0, 0, amph_yaw))

    finalize_mesh("ShoreAmph_TentRoof", bm_tent, mat_tent, smooth=True, keep_existing_uv=True)
    finalize_mesh("ShoreAmph_WhiteMasts", bm_mast, mat_mast, smooth=True)
    finalize_mesh("ShoreAmph_DarkSteelCables", bm_dark, mat_dark, smooth=False)
    finalize_mesh("ShoreAmph_ConcreteBowl", bm_conc, mat_conc, smooth=False)
    finalize_mesh("ShoreAmph_SeatingRows", bm_seat, mat_seat, smooth=False)
    finalize_mesh("ShoreAmph_StageCedar", bm_stage, mat_stage, smooth=False)
    finalize_mesh("ShoreAmph_AcousticWall", bm_acous, mat_acoustic, smooth=False)
    finalize_mesh("ShoreAmph_StageLights", bm_light, mat_light, smooth=False)
    finalize_mesh("ShoreAmph_PeakBeacons", bm_beacon, mat_beacon, smooth=True)
    finalize_mesh("ShoreAmph_LawnRim", bm_lawn, mat_lawn, smooth=False)

    # Log exact world coordinates for @campus3x-world (placed at (+58, 0, -148), rotY=0)
    wx0, wz0 = 58.0, -148.0
    for idx, (mx, my) in enumerate(mast_coords_local):
        p = pt(mx, my, 0.0)
        print(f"  [SHORELINE_MAST#{idx}] ThreeJS=({wx0+p.x:.2f}, {wz0-p.y:.2f}) r=0.85m h=19.4m")
    for idx, (kx, ky) in enumerate(kiosk_locals):
        p = pt(kx, ky, 0.0)
        print(f"  [SHORELINE_KIOSK#{idx}] ThreeJS=({wx0+p.x:.2f}, 1.75, {wz0-p.y:.2f}) size=(6.4,3.5,3.2) rotY={amph_yaw:.4f}")
    p_stage = pt(0.0, 14.0, 0.0)
    p_back = pt(0.0, 21.5, 0.0)
    print(f"  [SHORELINE_STAGE] center_ThreeJS=({wx0+p_stage.x:.2f}, 1.22, {wz0-p_stage.y:.2f}) backstage_ThreeJS=({wx0+p_back.x:.2f}, 3.4, {wz0-p_back.y:.2f}) rotY={amph_yaw:.4f}")

    return export_asset("landmark_shoreline_amphitheatre.glb")


# ===========================================================================
# 2. GOOGLE ATHLETIC RECREATION FIELD (~66m x 42m)
# ===========================================================================
def build_athletic_field():
    reset_scene()

    tex_pitch = gen_soccer_pitch_tex("Ath_PitchTex", w=512, h=320, seed=811)
    tex_conc = gen_concrete_tex("Ath_ConcTex", 128, tint=(0.82, 0.80, 0.76), seed=812)
    tex_cedar = gen_cedar_wood_tex("Ath_CedarTex", 128, seed=813)

    mat_pitch = make_pbr_mat("Ath_SoccerTurf", base_color=(1, 1, 1, 1), roughness=0.88, tex_img=tex_pitch)
    mat_track = make_pbr_mat("Ath_PerimeterApron", base_color=hex_to_linear("#C9C2B6"), roughness=0.82, tex_img=tex_conc)
    mat_white = make_pbr_mat("Ath_GoalWhite", base_color=hex_to_linear("#F6F8FB"), roughness=0.38, metallic=0.15)
    mat_alum = make_pbr_mat("Ath_Aluminum", base_color=hex_to_linear("#CFD6DF"), metallic=0.86, roughness=0.26)
    mat_dark = make_pbr_mat("Ath_DarkSteel", base_color=hex_to_linear("#2A323F"), metallic=0.80, roughness=0.36)
    mat_cedar = make_pbr_mat("Ath_DugoutBench", base_color=(1, 1, 1, 1), roughness=0.66, tex_img=tex_cedar)
    mat_canopy = make_pbr_mat("Ath_DugoutGlass", base_color=hex_to_linear("#4285F4", alpha=0.58), metallic=0.15, roughness=0.14, alpha=0.58, double_sided=True)
    mat_accent = make_pbr_mat("Ath_GoogleGreen", base_color=hex_to_linear("#34A853"), roughness=0.42)
    mat_orange = make_pbr_mat("Ath_CornerFlag", base_color=hex_to_linear("#F97316"), roughness=0.48)
    mat_flood = make_pbr_mat("Ath_FloodLED", base_color=hex_to_linear("#FFFCE8"), roughness=0.18, emission=hex_to_linear("#FFF4CC"), emission_strength=3.6)

    bm_pitch = bmesh.new()
    bm_track = bmesh.new()
    bm_white = bmesh.new()
    bm_alum = bmesh.new()
    bm_dark = bmesh.new()
    bm_cedar = bmesh.new()
    bm_canopy = bmesh.new()
    bm_accent = bmesh.new()
    bm_orange = bmesh.new()
    bm_flood = bmesh.new()

    # 1. Grounded Perimeter Walkable Apron (66m x 42m, Z = 0.00..0.04m)
    bm_add_box(bm_track, (0.0, 0.0, 0.02), (66.0, 42.0, 0.04))

    # 2. Striped Lush Turf Soccer Pitch (60m x 36m, Z = 0.04..0.065m, exact unit UV mapping!)
    uv_p = bm_pitch.loops.layers.uv.verify()
    pw, pd = 60.0, 36.0
    v00 = bm_pitch.verts.new((-pw * 0.5, -pd * 0.5, 0.062))
    v10 = bm_pitch.verts.new((pw * 0.5, -pd * 0.5, 0.062))
    v11 = bm_pitch.verts.new((pw * 0.5, pd * 0.5, 0.062))
    v01 = bm_pitch.verts.new((-pw * 0.5, pd * 0.5, 0.062))
    f_top = bm_pitch.faces.new((v00, v10, v11, v01))
    for lp, uv in zip(f_top.loops, ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))):
        lp[uv_p].uv = uv
    # Low perimeter edge skirts grounding turf cleanly into apron
    for va, vb in ((v00, v10), (v10, v11), (v11, v01), (v01, v00)):
        sa = bm_pitch.verts.new((va.co.x, va.co.y, 0.03))
        sb = bm_pitch.verts.new((vb.co.x, vb.co.y, 0.03))
        fs = bm_pitch.faces.new((va, sa, sb, vb))
        for lp in fs.loops:
            lp[uv_p].uv = (0.02, 0.02)

    # 3. Twin Full-Size Soccer Goals (at X = -27.0m and +27.0m, 7.32m wide x 2.44m tall x 2.2m deep)
    goal_w, goal_h, goal_d = 7.32, 2.44, 2.20
    for sgn in (-1.0, 1.0):
        gx = sgn * 27.0
        bx = gx + sgn * goal_d
        # Front vertical posts + top crossbar
        bm_add_prism_between(bm_white, (gx, -goal_w * 0.5, 0.04), (gx, -goal_w * 0.5, goal_h), 0.065, 0.065, segs=8)
        bm_add_prism_between(bm_white, (gx, goal_w * 0.5, 0.04), (gx, goal_w * 0.5, goal_h), 0.065, 0.065, segs=8)
        bm_add_prism_between(bm_white, (gx, -goal_w * 0.5, goal_h), (gx, goal_w * 0.5, goal_h), 0.065, 0.065, segs=8)
        # Back support frame & ground base bar
        bm_add_prism_between(bm_white, (gx, -goal_w * 0.5, goal_h), (bx, -goal_w * 0.5, goal_h - 0.35), 0.045, 0.045, segs=6)
        bm_add_prism_between(bm_white, (gx, goal_w * 0.5, goal_h), (bx, goal_w * 0.5, goal_h - 0.35), 0.045, 0.045, segs=6)
        bm_add_prism_between(bm_white, (bx, -goal_w * 0.5, 0.06), (bx, -goal_w * 0.5, goal_h - 0.35), 0.045, 0.045, segs=6)
        bm_add_prism_between(bm_white, (bx, goal_w * 0.5, 0.06), (bx, goal_w * 0.5, goal_h - 0.35), 0.045, 0.045, segs=6)
        bm_add_prism_between(bm_white, (bx, -goal_w * 0.5, goal_h - 0.35), (bx, goal_w * 0.5, goal_h - 0.35), 0.045, 0.045, segs=6)
        bm_add_prism_between(bm_white, (gx, -goal_w * 0.5, 0.07), (bx, -goal_w * 0.5, 0.07), 0.045, 0.045, segs=6)
        bm_add_prism_between(bm_white, (gx, goal_w * 0.5, 0.07), (bx, goal_w * 0.5, 0.07), 0.045, 0.045, segs=6)
        bm_add_prism_between(bm_white, (bx, -goal_w * 0.5, 0.07), (bx, goal_w * 0.5, 0.07), 0.045, 0.045, segs=6)
        # Crisp 3D geometric net mesh (back, roof, left/right sides)
        for k in range(1, 10):
            ny = -goal_w * 0.5 + goal_w * (k / 10.0)
            bm_add_box(bm_white, (bx, ny, (goal_h - 0.35) * 0.5 + 0.05), (0.014, 0.014, goal_h - 0.38))
            bm_add_box(bm_white, (0.5 * (gx + bx), ny, goal_h - 0.17), (goal_d, 0.014, 0.014))
        for k in range(1, 5):
            nz = 0.08 + (goal_h - 0.45) * (k / 5.0)
            bm_add_box(bm_white, (bx, 0.0, nz), (0.014, goal_w, 0.014))
            for sy in (-goal_w * 0.5, goal_w * 0.5):
                bm_add_box(bm_white, (0.5 * (gx + bx), sy, nz), (goal_d, 0.014, 0.014))
        for k in range(1, 4):
            nx = gx + sgn * goal_d * (k / 4.0)
            for sy in (-goal_w * 0.5, goal_w * 0.5):
                bm_add_box(bm_white, (nx, sy, (goal_h - 0.25) * 0.5 + 0.05), (0.014, 0.014, goal_h - 0.30))

        # Behind-goal steel ball-stop backstop posts (X = +-32.4m)
        bsx = sgn * 32.4
        for by in (-8.5, -4.25, 0.0, 4.25, 8.5):
            bm_add_prism_between(bm_dark, (bsx, by, 0.04), (bsx, by, 5.2), 0.06, 0.055, segs=6)
        bm_add_prism_between(bm_dark, (bsx, -8.5, 5.2), (bsx, 8.5, 5.2), 0.05, 0.05, segs=6)
        bm_add_prism_between(bm_dark, (bsx, -8.5, 2.6), (bsx, 8.5, 2.6), 0.04, 0.04, segs=6)

    # 4. Aluminum Spectator Bleachers (2 grandstands along North sideline, local Y = +19.5m)
    bleacher_xs = [-14.0, 14.0]
    for bx_c in bleacher_xs:
        bl_len = 14.0
        for row in range(5):
            ry = 18.2 + row * 0.62
            rz = 0.42 + row * 0.42
            # Aluminum seat plank + footrest plank
            bm_add_box(bm_alum, (bx_c, ry, rz), (bl_len, 0.34, 0.07))
            bm_add_box(bm_alum, (bx_c, ry - 0.28, rz - 0.20), (bl_len, 0.28, 0.05))
        # Steel A-frame under-supports (4 frames, grounded cleanly above apron!)
        for fi in range(4):
            fx = bx_c - bl_len * 0.46 + bl_len * 0.92 * (fi / 3.0)
            bm_add_prism_between(bm_dark, (fx, 18.2, 0.12), (fx, 20.8, 2.15), 0.055, 0.055, segs=4)
            bm_add_prism_between(bm_dark, (fx, 20.8, 0.04), (fx, 20.8, 3.10), 0.055, 0.055, segs=4)
            bm_add_prism_between(bm_dark, (fx, 19.5, 0.04), (fx, 19.5, 1.25), 0.05, 0.05, segs=4)
        # Rear safety guardrail
        bm_add_prism_between(bm_alum, (bx_c - bl_len * 0.48, 20.8, 3.10), (bx_c + bl_len * 0.48, 20.8, 3.10), 0.035, 0.035, segs=5)
        bm_add_prism_between(bm_alum, (bx_c - bl_len * 0.48, 20.8, 2.62), (bx_c + bl_len * 0.48, 20.8, 2.62), 0.025, 0.025, segs=5)

    # 5. Twin Shaded Team Dugout Shelters (along South sideline, local Y = -19.4m, great combat cover!)
    dugout_xs = [-12.0, 12.0]
    for dx_c in dugout_xs:
        dw, dd, dh = 7.2, 2.1, 2.45
        dy_c = -19.4
        # Concrete floor pad
        bm_add_box(bm_track, (dx_c, dy_c, 0.08), (dw + 0.4, dd + 0.4, 0.12))
        # Dark steel frame posts + rear & side glazed cover panels
        for sx in (-dw * 0.48, 0.0, dw * 0.48):
            bm_add_prism_between(bm_dark, (dx_c + sx, dy_c - dd * 0.46, 0.12), (dx_c + sx, dy_c - dd * 0.46, dh), 0.06, 0.06, segs=6)
            bm_add_prism_between(bm_dark, (dx_c + sx, dy_c - dd * 0.46, dh), (dx_c + sx, dy_c + dd * 0.48, dh + 0.14), 0.055, 0.055, segs=6)
        bm_add_box(bm_canopy, (dx_c, dy_c - dd * 0.46, dh * 0.52), (dw - 0.1, 0.06, dh - 0.20))
        bm_add_box(bm_canopy, (dx_c, dy_c, dh + 0.08), (dw + 0.2, dd + 0.2, 0.07), rot_euler=(-0.08, 0.0, 0.0))
        bm_add_box(bm_accent, (dx_c, dy_c + dd * 0.48, dh + 0.14), (dw + 0.24, 0.10, 0.14))
        for sx in (-dw * 0.48, dw * 0.48):
            bm_add_box(bm_canopy, (dx_c + sx, dy_c, dh * 0.52), (0.06, dd, dh - 0.20))
        # Cedar player bench inside dugout
        bm_add_box(bm_cedar, (dx_c, dy_c - 0.32, 0.52), (dw - 0.6, 0.52, 0.08))
        bm_add_box(bm_cedar, (dx_c, dy_c - 0.62, 0.88), (dw - 0.6, 0.07, 0.36))
        for lx in (-dw * 0.38, 0.0, dw * 0.38):
            bm_add_box(bm_dark, (dx_c + lx, dy_c - 0.32, 0.28), (0.10, 0.46, 0.42))

    # 6. Six Stadium Floodlight Poles (3 North, 3 South, Z = 0..12.8m)
    pole_coords = [(-26.0, 19.6), (0.0, 19.8), (26.0, 19.6), (-26.0, -19.6), (0.0, -19.8), (26.0, -19.6)]
    for px, py in pole_coords:
        bm_add_prism_between(bm_track, (px, py, 0.0), (px, py, 0.65), 0.36, 0.32, segs=8)
        bm_add_prism_between(bm_alum, (px, py, 0.60), (px, py, 12.6), 0.18, 0.10, segs=8)
        # Crossbar & 4 angled LED stadium floodlights aimed down toward pitch center!
        inward_s = -1.0 if py > 0 else 1.0
        bm_add_box(bm_dark, (px, py, 12.55), (2.4, 0.16, 0.16))
        for fo in (-0.90, -0.30, 0.30, 0.90):
            bm_add_box(bm_dark, (px + fo, py + inward_s * 0.18, 12.62), (0.44, 0.24, 0.36), rot_euler=(inward_s * 0.45, 0.0, 0.0))
            bm_add_box(bm_flood, (px + fo, py + inward_s * 0.28, 12.56), (0.36, 0.06, 0.28), rot_euler=(inward_s * 0.45, 0.0, 0.0))

    # 7. Corner Flags & Center-Spot Soccer Ball
    for fx in (-27.0, 27.0):
        for fy in (-16.0, 16.0):
            bm_add_prism_between(bm_white, (fx, fy, 0.06), (fx, fy, 1.55), 0.022, 0.018, segs=5)
            bm_add_box(bm_orange, (fx + (0.18 if fx < 0 else -0.18), fy, 1.38), (0.36, 0.03, 0.28))
    bm_add_sphere(bm_white, (0.0, 0.0, 0.18), 0.12, u_segs=10, v_segs=8)

    finalize_mesh("Ath_PitchTurf", bm_pitch, mat_pitch, smooth=False, keep_existing_uv=True)
    finalize_mesh("Ath_ConcreteApron", bm_track, mat_track, smooth=False)
    finalize_mesh("Ath_GoalsAndNets", bm_white, mat_white, smooth=False)
    finalize_mesh("Ath_BleachersAndPoles", bm_alum, mat_alum, smooth=False)
    finalize_mesh("Ath_DarkSteel", bm_dark, mat_dark, smooth=False)
    finalize_mesh("Ath_CedarBenches", bm_cedar, mat_cedar, smooth=False)
    finalize_mesh("Ath_DugoutCanopy", bm_canopy, mat_canopy, smooth=False)
    finalize_mesh("Ath_GoogleAccent", bm_accent, mat_accent, smooth=False)
    finalize_mesh("Ath_CornerFlags", bm_orange, mat_orange, smooth=False)
    finalize_mesh("Ath_FloodLights", bm_flood, mat_flood, smooth=False)

    print("  [ATHLETIC_FIELD] World=(-220, -134) Footprint=66x42m Pitch=60x36m")
    print("    Bleachers ThreeJS: (-234, 1.2, -153.5) & (-206, 1.2, -153.5) size=(14.0, 2.4, 3.2)")
    print("    Dugouts   ThreeJS: (-232, 1.25, -114.6) & (-208, 1.25, -114.6) size=(7.2, 2.5, 2.1)")
    print("    Goals     ThreeJS: (-248.1, 1.22, -134) & (-191.9, 1.22, -134) size=(2.2, 2.44, 7.32)")

    return export_asset("landmark_athletic_field.glb")


# ===========================================================================
# 3. GOOGLE 2000 (NORTH) & GOOGLE 1950 (SOUTH) COMPLEX (~82m x 88m, roof +6.4m)
# ===========================================================================
def build_google_2000_1950():
    reset_scene()
    wx0, wz0 = -225.0, 2.0

    mats, bms = make_office_palette("G2000", accent_hex="#2563EB", roof_hex="#C4CBD4", seed=820)

    # Landscaped Central Courtyard Stone Plaza uniting Google 2000 (North) & Google 1950 (South)
    courtyard_poly = [(-38.0, -14.0), (39.0, -16.0), (39.0, 15.0), (-38.0, 15.0)]
    bm_add_polygon_prism(bms["plaza"], courtyard_poly, 0.00, 0.036, cap_bottom=True, cap_top=True)

    # Central Architectural Timber Shade Pergola & Planter Islands inside Courtyard (Z = 0..3.8m)
    for px_c in (-16.0, 14.0):
        # Raised concrete planter bed with lush greenery + cedar perimeter bench
        bm_add_box(bms["conc"], (px_c, 0.0, 0.28), (11.5, 5.6, 0.56))
        bm_add_box(bms["shrub"], (px_c, 0.0, 0.68), (10.6, 4.7, 0.42))
        bm_add_box(bms["cedar"], (px_c, 3.05, 0.46), (9.0, 0.52, 0.10))
        bm_add_box(bms["cedar"], (px_c, -3.05, 0.46), (9.0, 0.52, 0.10))

    # Central Open Courtyard Shade Pavilion (at local (0, 0))
    for sx in (-4.2, 4.2):
        for sy in (-3.2, 3.2):
            bm_add_prism_between(bms["dark"], (sx, sy, 0.036), (sx, sy, 3.70), 0.12, 0.11, segs=6)
    bm_add_box(bms["dark"], (0.0, 3.2, 3.74), (8.8, 0.18, 0.20))
    bm_add_box(bms["dark"], (0.0, -3.2, 3.74), (8.8, 0.18, 0.20))
    for k in range(11):
        sl_x = -4.0 + k * 0.80
        bm_add_box(bms["cedar"], (sl_x, 0.0, 3.88), (0.14, 6.8, 0.10))

    # Google 2000 (North Wing — gentle curved WNW-ESE wing, local Y in [+13, +44], ThreeJS Z in [-42, -11])
    # CCW vertices: 0:(-39,17)->1:(-10,13)->2:(36,15)->3:(40,39)->4:(-4,44)->5:(-40,38)
    poly_2000 = [
        (-39.0, 17.0),
        (-10.0, 13.0),
        (36.0, 15.0),
        (40.0, 39.0),
        (-4.0, 44.0),
        (-40.0, 38.0),
    ]
    add_hollow_office_wing(
        bms,
        poly_2000,
        doorways=[
            (1, 14.0, 21.0),   # 7.0m South Courtyard lobby
            (2, 9.0, 15.5),    # 6.5m East Creek-side lobby
            (4, 15.0, 22.0),   # 7.0m North Amphitheatre lobby
        ],
        stair_specs=[(0, 0.22)],  # Exterior stair on Courtyard-facing SW edge (100% clear of Edge 1 arcade!)
        interior_cols=[(-24.0, 27.0), (-6.0, 28.0), (14.0, 28.0), (28.0, 27.0)],
        solar_density=0.95,
        solar_yaw=0.05,
        arcade_edges=[1],
        world_offset=(wx0, wz0),
        wing_label="Google2000_North",
    )

    # Google 1950 (South Wing — sweeping SW chamfer hugging Charleston Rd curve! local Y in [-43, -13], ThreeJS Z in [+15, +45])
    # CCW vertices: 0:(-31,-32)->1:(12,-43)->2:(40,-40)->3:(38,-15)->4:(-12,-13)->5:(-39,-18)
    poly_1950 = [
        (-31.0, -32.0),
        (12.0, -43.0),
        (40.0, -40.0),
        (38.0, -15.0),
        (-12.0, -13.0),
        (-39.0, -18.0),
    ]
    add_hollow_office_wing(
        bms,
        poly_1950,
        doorways=[
            (1, 10.0, 17.0),   # 7.0m South Charleston Rd lobby
            (2, 9.0, 15.5),    # 6.5m East Creek-side lobby
            (3, 18.0, 25.0),   # 7.0m North Courtyard lobby
        ],
        stair_specs=[(4, 0.22)],  # Exterior stair on Courtyard-facing NW edge (100% clear of Edge 3 arcade!)
        interior_cols=[(-22.0, -24.0), (-4.0, -27.0), (14.0, -28.0), (28.0, -27.0)],
        solar_density=0.95,
        solar_yaw=-0.10,
        arcade_edges=[3],
        world_offset=(wx0, wz0),
        wing_label="Google1950_South",
    )

    finalize_office_bms("G2000_1950", mats, bms)
    return export_asset("landmark_google_2000_1950.glb")


# ===========================================================================
# 4. CHARLESTON CAMPUS (~110m x 62m, roof +6.4m, straddles Huff Ave cleanly!)
# ===========================================================================
def build_charleston_campus():
    reset_scene()
    wx0, wz0 = 28.0, 134.0

    mats, bms = make_office_palette("CharlC", accent_hex="#EA580C", roof_hex="#C6CCD4", seed=830)

    # NOTE: Huff Ave runs N-S at world X = +1.4 -> local X = -26.6 (asphalt [-29.6,-23.6], sidewalks [-30.8,-22.4]).
    # West Wing sits cleanly west of local X = -33.5; Main East Courtyard Complex sits east of local X = -19.0!

    # 1. Sunlit Central Courtyard Plaza inside East Multi-Wing Complex (local X in [-20,+22], Y in [-14,+14])
    bm_add_polygon_prism(bms["plaza"], [(-20.0, -14.0), (22.0, -14.0), (22.0, 14.0), (-20.0, 14.0)], 0.00, 0.036)
    # Central architectural reflecting water pool + raised timber lounge deck + planters
    bm_add_box(bms["conc"], (0.0, 0.0, 0.18), (12.0, 6.2, 0.36))
    bm_add_box(bms["water"], (0.0, 0.0, 0.30), (11.1, 5.3, 0.14))
    for px_p in (-11.5, 11.5):
        bm_add_box(bms["conc"], (px_p, 0.0, 0.28), (5.2, 7.6, 0.56))
        bm_add_box(bms["shrub"], (px_p, 0.0, 0.68), (4.4, 6.8, 0.42))
        bm_add_box(bms["cedar"], (px_p, 4.05, 0.46), (4.2, 0.48, 0.10))
        bm_add_box(bms["cedar"], (px_p, -4.05, 0.46), (4.2, 0.48, 0.10))

    # 2. West Wing (Building C-West, local X in [-55,-34], Y in [-27,+27] -> 21m x 54m)
    poly_west = [
        (-55.0, -27.0),
        (-34.0, -27.0),
        (-34.0, 27.0),
        (-55.0, 27.0),
    ]
    add_hollow_office_wing(
        bms,
        poly_west,
        doorways=[
            (0, 7.2, 13.8),    # 6.6m South Plymouth St lobby
            (1, 23.0, 30.2),   # 7.2m East Huff Ave Promenade lobby
            (2, 7.2, 13.8),    # 6.6m North Charleston Rd lobby
        ],
        stair_specs=[(1, 0.06)],  # Exterior stair on East Huff-facing edge (south of lobby!)
        interior_cols=[(-44.5, -14.0), (-44.5, 0.0), (-44.5, 14.0)],
        solar_density=0.95,
        solar_yaw=0.0,
        world_offset=(wx0, wz0),
        wing_label="Charleston_WestWing",
    )

    # 3. Three Clean Convex Wings Surrounding the Sunlit Central Courtyard Plaza (ZERO concave roof artifacts!)
    # 3A. North Wing (local X in [-19,+38], Y in [+13,+31] -> 57m x 18m)
    poly_north = [
        (-19.0, 13.0),
        (38.0, 13.0),
        (38.0, 31.0),
        (-19.0, 31.0),
    ]
    add_hollow_office_wing(
        bms,
        poly_north,
        doorways=[
            (0, 18.0, 25.0),   # 7.0m South Courtyard lobby (clear east of stair!)
            (2, 22.0, 29.0),   # 7.0m North Charleston Rd lobby
            (3, 5.5, 12.5),    # 7.0m West Huff Ave lobby
        ],
        stair_specs=[(0, 0.05)],  # Exterior stair on South Courtyard edge
        interior_cols=[(-4.0, 22.0), (14.0, 22.0), (29.0, 22.0)],
        solar_density=0.95,
        solar_yaw=0.0,
        world_offset=(wx0, wz0),
        wing_label="Charleston_NorthWing",
    )

    # 3B. South Wing (local X in [-19,+38], Y in [-31,-13] -> 57m x 18m)
    poly_south = [
        (-19.0, -31.0),
        (38.0, -31.0),
        (38.0, -13.0),
        (-19.0, -13.0),
    ]
    add_hollow_office_wing(
        bms,
        poly_south,
        doorways=[
            (0, 22.0, 29.0),   # 7.0m South Plymouth St lobby
            (2, 38.0, 45.0),   # 7.0m North Courtyard lobby (clear west of stair!)
            (3, 5.5, 12.5),    # 7.0m West Huff Ave lobby
        ],
        stair_specs=[(2, 0.38)],  # Exterior stair on North Courtyard edge (100% clear west of East Spine arcade!)
        interior_cols=[(-4.0, -22.0), (14.0, -22.0), (29.0, -22.0)],
        solar_density=0.95,
        solar_yaw=0.0,
        world_offset=(wx0, wz0),
        wing_label="Charleston_SouthWing",
    )

    # 3C. East Spine Pavilion (local X in [+21,+38], Y in [-11,+11] -> 17m x 22m, shaded arcade facing sunlit courtyard!)
    poly_east_spine = [
        (21.0, -11.0),
        (38.0, -11.0),
        (38.0, 11.0),
        (21.0, 11.0),
    ]
    add_hollow_office_wing(
        bms,
        poly_east_spine,
        doorways=[
            (0, 5.2, 11.8),    # 6.6m South breeze portal
            (2, 5.2, 11.8),    # 6.6m North breeze portal
            (3, 7.5, 14.5),    # 7.0m West Courtyard central lobby under arcade!
        ],
        stair_specs=[],
        interior_cols=[(29.5, 0.0)],
        solar_density=0.90,
        solar_yaw=0.0,
        arcade_edges=[3],
        world_offset=(wx0, wz0),
        wing_label="Charleston_EastSpine",
    )

    # 4. Adjacent East Modern Louvered Parking Deck Trim (local X in [+41,+55], Y in [-28,+28] -> 14m x 56m)
    pd_x0, pd_x1 = 41.0, 55.0
    pd_cx = 0.5 * (pd_x0 + pd_x1)
    pd_w, pd_l = pd_x1 - pd_x0, 56.0
    # Ground floor, mid-deck (3.2m), walkable upper roof parking deck (6.4m)
    bm_add_box(bms["floor_conc"], (pd_cx, 0.0, 0.04), (pd_w, pd_l, 0.08))
    bm_add_box(bms["conc"], (pd_cx, 0.0, 3.20), (pd_w, pd_l, 0.28))
    bm_add_box(bms["roof"], (pd_cx, 0.0, 6.26), (pd_w, pd_l, 0.28))
    # Concrete perimeter safety spandrel bands & top parapet
    for hz in (3.72, 6.82):
        bm_add_box(bms["conc"], (pd_x0 + 0.18, 0.0, hz), (0.36, pd_l, 1.04))
        bm_add_box(bms["conc"], (pd_x1 - 0.18, 0.0, hz), (0.36, pd_l, 1.04))
        bm_add_box(bms["conc"], (pd_cx, pd_l * 0.5 - 0.18, hz), (pd_w, 0.36, 1.04))
        bm_add_box(bms["conc"], (pd_cx, -pd_l * 0.5 + 0.18, hz), (pd_w, 0.36, 1.04))
    # Architectural structural columns + vertical warm cedar louver screen fins along east face
    for iy in range(7):
        cy = -25.0 + iy * (50.0 / 6.0)
        bm_add_box(bms["conc"], (pd_x0 + 0.35, cy, 3.20), (0.56, 0.56, 6.40))
        bm_add_box(bms["conc"], (pd_x1 - 0.35, cy, 3.20), (0.56, 0.56, 6.40))
    for iy in range(16):
        cy = -24.5 + iy * (49.0 / 15.0)
        bm_add_box(bms["cedar"], (pd_x1 + 0.12, cy, 3.50), (0.14, 0.30, 5.80))
    # Sleek Rooftop Solar Carport Canopy shading top parking deck (Z = 9.4m)
    for sy_c in (-16.0, 0.0, 16.0):
        for sx_c in (pd_x0 + 2.0, pd_x1 - 2.0):
            bm_add_prism_between(bms["dark"], (sx_c, sy_c, 6.40), (sx_c, sy_c, 9.25), 0.14, 0.12, segs=6)
        bm_add_box(bms["solar"], (pd_cx, sy_c, 9.40), (pd_w - 1.2, 12.0, 0.10), rot_euler=(0.0, 0.12, 0.0))

    print(f"  [PARKING_DECK Charleston] ThreeJS box center=({wx0+pd_cx:.2f}, 3.2, {wz0:.2f}) size=({pd_w:.1f}, 6.4, {pd_l:.1f})")

    finalize_office_bms("CharlCampus", mats, bms)
    return export_asset("landmark_charleston_campus.glb")


# ===========================================================================
# 5. 1098 ALTA / HUFF COMPLEX (~76m x 54m, roof +6.4m, straddles Alta Ave!)
# ===========================================================================
def build_alta_complex():
    reset_scene()
    wx0, wz0 = -108.0, 126.0

    # Signature bright cool-white reflective roofs for 1098 Alta / Huff!
    mats, bms = make_office_palette("Alta", accent_hex="#DC2626", roof_hex="#ECEFF4", conc_tint=(0.90, 0.88, 0.85), seed=840)

    # NOTE: Alta Ave runs N-S at world X = -96.8 -> local X = +11.2 (asphalt [+8.2,+14.2], sidewalks [+7.0,+15.4]).
    # West Wing sits cleanly in local X in [-38,+3]; East Wing sits cleanly in local X in [+19,+38]!

    # Landscaped Garden Walkways & Planters flanking the central Alta avenue (leaving X in [+6,+16] 100% open!)
    bm_add_polygon_prism(bms["plaza"], [(2.5, -26.0), (6.4, -26.0), (6.4, 26.0), (2.5, 26.0)], 0.00, 0.036)
    bm_add_polygon_prism(bms["plaza"], [(16.0, -25.0), (19.5, -25.0), (19.5, 25.0), (16.0, 25.0)], 0.00, 0.036)
    # Garden patio indentation inside West Wing
    bm_add_polygon_prism(bms["plaza"], [(-28.0, -9.0), (-12.0, -9.0), (-12.0, 9.0), (-28.0, 9.0)], 0.00, 0.036)
    for gy in (-17.5, 17.5):
        bm_add_box(bms["conc"], (4.6, gy, 0.28), (2.2, 6.5, 0.56))
        bm_add_box(bms["shrub"], (4.6, gy, 0.66), (1.7, 5.8, 0.38))
        bm_add_box(bms["conc"], (17.6, gy, 0.28), (2.2, 6.5, 0.56))
        bm_add_box(bms["shrub"], (17.6, gy, 0.66), (1.7, 5.8, 0.38))

    # 1. West Twin-Bar White-Roofed Wings surrounding a sunlit open West Garden Patio (100% convex wings!)
    # 1A. NW Wing (local X in [-38,+3], Y in [+8,+27] -> 41m x 19m)
    poly_nw = [
        (-38.0, 8.0),
        (3.0, 8.0),
        (3.0, 27.0),
        (-38.0, 27.0),
    ]
    add_hollow_office_wing(
        bms,
        poly_nw,
        doorways=[
            (0, 16.0, 23.0),   # 7.0m South Garden Patio arched lobby
            (1, 5.5, 13.5),    # 8.0m East Alta Ave arched lobby
            (2, 16.0, 23.0),   # 7.0m North Charleston Rd arched lobby
        ],
        stair_specs=[],
        interior_cols=[(-26.0, 17.5), (-8.0, 17.5)],
        solar_density=0.72,
        solar_yaw=0.0,
        arched_lobbies=True,
        world_offset=(wx0, wz0),
        wing_label="Alta_NorthWestWing",
    )

    # 1B. SW Wing (local X in [-38,+3], Y in [-27,-8] -> 41m x 19m)
    poly_sw = [
        (-38.0, -27.0),
        (3.0, -27.0),
        (3.0, -8.0),
        (-38.0, -8.0),
    ]
    add_hollow_office_wing(
        bms,
        poly_sw,
        doorways=[
            (0, 16.0, 23.0),   # 7.0m South Plymouth St arched lobby
            (1, 5.5, 13.5),    # 8.0m East Alta Ave arched lobby
            (2, 19.0, 26.0),   # 7.0m North Garden Patio arched lobby (clear west of stair!)
        ],
        stair_specs=[(2, 0.04)],  # Exterior stair facing the sunlit central garden patio!
        interior_cols=[(-26.0, -17.5), (-8.0, -17.5)],
        solar_density=0.72,
        solar_yaw=0.0,
        arched_lobbies=True,
        world_offset=(wx0, wz0),
        wing_label="Alta_SouthWestWing",
    )
    # Landscaped garden walkway bed running through open central garden court (Y in [-8,+8])
    bm_add_polygon_prism(bms["plaza"], [(-36.0, -8.0), (4.0, -8.0), (4.0, 8.0), (-36.0, 8.0)], 0.00, 0.036)
    bm_add_box(bms["conc"], (-17.5, 0.0, 0.28), (11.0, 4.6, 0.56))
    bm_add_box(bms["shrub"], (-17.5, 0.0, 0.66), (10.0, 3.8, 0.40))
    bm_add_box(bms["cedar"], (-17.5, 2.55, 0.46), (8.6, 0.48, 0.10))
    bm_add_box(bms["cedar"], (-17.5, -2.55, 0.46), (8.6, 0.48, 0.10))

    # 2. East Wing (Alta East Pavilion, local X in [+19,+38], Y in [-25,+25] -> 19m x 50m)
    poly_east = [
        (19.0, -25.0),
        (38.0, -25.0),
        (38.0, 25.0),
        (19.0, 25.0),
    ]
    add_hollow_office_wing(
        bms,
        poly_east,
        doorways=[
            (0, 6.2, 12.8),    # 6.6m South lobby
            (2, 6.2, 12.8),    # 6.6m North lobby
            (3, 21.0, 29.0),   # 8.0m West Grand Arched Lobby facing Alta Garden Corridor!
        ],
        stair_specs=[(3, 0.06)],  # Exterior stair on West garden edge!
        interior_cols=[(28.5, -13.0), (28.5, 0.0), (28.5, 13.0)],
        solar_density=0.72,
        solar_yaw=0.0,
        arched_lobbies=True,
        world_offset=(wx0, wz0),
        wing_label="Alta_EastWing",
    )

    finalize_office_bms("AltaComplex", mats, bms)
    return export_asset("landmark_alta_complex.glb")


# ===========================================================================
# 6. SHORELINE EAST GOOGLE OFFICE (~66m x 44m, roof +6.4m — reused 3x!)
# ===========================================================================
def build_shoreline_east_office():
    reset_scene()

    mats, bms = make_office_palette("ShoreEast", accent_hex="#3B82F6", roof_hex="#C6CED8", seed=850)

    # Sleek modern chamfered octagonal Mountain View Google office (66m x 44m, X in [-33,+33], Y in [-22,+22])
    # Built around origin (0,0) for clean reuse at Google 2015 (+234,-22 rotY=0), CL2 (+236,-140 rotY=pi), 1395 (+234,+122 rotY=0.06)!
    # CCW vertices:
    # 0:(-27,-22)->1:(27,-22) [South Front Arcade 54m]
    # 1:(27,-22)->2:(33,-16)  [SE chamfer]
    # 2:(33,-16)->3:(33,16)   [East 32m]
    # 3:(33,16)->4:(27,22)    [NE chamfer]
    # 4:(27,22)->5:(-27,22)   [North Back 54m]
    # 5:(-27,22)->6:(-33,16)  [NW chamfer]
    # 6:(-33,16)->7:(-33,-16) [West Shoreline Blvd Front 32m]
    # 7:(-33,-16)->0:(-27,-22)[SW chamfer]
    poly_office = [
        (-27.0, -22.0),
        (27.0, -22.0),
        (33.0, -16.0),
        (33.0, 16.0),
        (27.0, 22.0),
        (-27.0, 22.0),
        (-33.0, 16.0),
        (-33.0, -16.0),
    ]
    # Grounded perimeter entry forecourt apron on West & South approaches
    bm_add_polygon_prism(bms["plaza"], [(-37.0, -14.0), (-33.0, -14.0), (-33.0, 14.0), (-37.0, 14.0)], 0.00, 0.036)
    bm_add_polygon_prism(bms["plaza"], [(-24.0, -26.2), (24.0, -26.2), (24.0, -22.0), (-24.0, -22.0)], 0.00, 0.036)

    add_hollow_office_wing(
        bms,
        poly_office,
        doorways=[
            (0, 23.0, 31.0),   # 8.0m South Front Arcade main lobby
            (2, 12.5, 19.5),   # 7.0m East side lobby
            (4, 23.0, 31.0),   # 8.0m North lobby
            (6, 12.5, 19.5),   # 7.0m West N Shoreline Blvd lobby
        ],
        stair_specs=[(4, 0.12)],  # Exterior staircase on North edge (clear west of North lobby!)
        interior_cols=[
            (-18.0, -9.0), (0.0, -9.0), (18.0, -9.0),
            (-18.0, 9.0),  (0.0, 9.0),  (18.0, 9.0),
        ],
        solar_density=1.05,
        solar_yaw=0.0,
        arcade_edges=[0],  # Dramatic shaded ground-floor lobby arcade along South edge!
        world_offset=(0.0, 0.0),
        wing_label="ShorelineEastOffice_Local",
    )

    finalize_office_bms("ShoreEast", mats, bms)
    return export_asset("landmark_shoreline_east_office.glb")


# ---------------------------------------------------------------------------
# CLI & Main Runner
# ---------------------------------------------------------------------------
BUILDERS = [
    ("shoreline_amphitheatre", build_shoreline_amphitheatre),
    ("athletic_field", build_athletic_field),
    ("google_2000_1950", build_google_2000_1950),
    ("charleston_campus", build_charleston_campus),
    ("alta_complex", build_alta_complex),
    ("shoreline_east_office", build_shoreline_east_office),
]


def parse_only():
    if "--" in sys.argv:
        args = sys.argv[sys.argv.index("--") + 1:]
        if "--only" in args:
            idx = args.index("--only")
            if idx + 1 < len(args):
                return set(args[idx + 1].split(","))
    return None


def main():
    t0 = time.time()
    only = parse_only()
    results = []
    for key, fn in BUILDERS:
        if only is not None and key not in only:
            continue
        ts = time.time()
        print(f"\n=== Building expanded landmark: {key} ===")
        info = fn()
        info["sec"] = time.time() - ts
        results.append(info)
        d = info["dims"]
        print(
            f"[OK] {info['file']} | {info['kb']:.1f} KB | {info['tris']:,} tris | "
            f"dims=({d[0]:.2f} x {d[1]:.2f} x {d[2]:.2f}m) | "
            f"minZ={info['min_co'][2]:.4f}m maxZ={info['max_co'][2]:.2f}m | {info['sec']:.2f}s"
        )

    total_kb = sum(r["kb"] for r in results)
    total_tris = sum(r["tris"] for r in results)
    print("\n" + "=" * 96)
    print(
        f"[EXPANDED LANDMARKS SUMMARY] Built {len(results)} GLBs in {time.time() - t0:.2f}s | "
        f"Total: {total_kb / 1024.0:.2f} MB ({total_kb:.1f} KB) | {total_tris:,} tris"
    )
    print("=" * 96)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Workspace Royale — 4 New Tactical Utility Items Blender 5.3.0 Asset Generator & QA Renderer
===========================================================================================
Generates 4 crisp, lightweight beveled PBR `.glb` utility items into `public/assets/utilities/`:
  1. item_frag_grenade.glb — Tactical ribbed charcoal-steel ovoid frag grenade w/ Google-Red band,
                             brass safety lever & pull-ring pin, and glowing red fuse LED
  2. item_flashbang.glb    — Brushed-aluminum cylindrical stun canister w/ dark grip ribs,
                             recessed bright-white flash vent ports, amber stripe & spoon/ring
  3. item_shield_drop.glb  — Hexagonal pearl-white & Google-Blue portable dome emitter disc on
                             3 folded tripod fins w/ luminous cyan crystal core & concentric rings
  4. item_regen_pod.glb    — Rounded pearl-white & Google-Green Bio-Med vertical capsule pod on
                             stabilized base w/ glowing emerald crosses, bio-fluid tank & emitter dish

Also renders a 2x2 studio EEVEE QA contact sheet to:
  /Users/davidyou/.gemini/antigravity/brain/a9682dfa-7d5f-428c-afd4-e62e35b1964e/previews/qa_new_utilities.png

Usage:
  blender --background --python scripts/blender/build_new_utilities.py
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
OUT_DIR = PROJECT_ROOT / "public" / "assets" / "utilities"
OUT_DIR.mkdir(parents=True, exist_ok=True)

QA_PREVIEW_PATH = Path(
    "/Users/davidyou/.gemini/antigravity/brain/a9682dfa-7d5f-428c-afd4-e62e35b1964e/previews/qa_new_utilities.png"
)

# Palette (sRGB hex)
COL_CHARCOAL_STEEL = "#2B303A"
COL_DARK_SLATE = "#1D222B"
COL_RUBBER = "#16191F"
COL_GUNMETAL = "#39414E"
COL_BRUSHED_ALUM = "#E2E8F0"
COL_TITANIUM = "#94A3B8"
COL_PEARL_WHITE = "#F4F7FA"

COL_GOOGLE_RED = "#EA4335"
COL_GOOGLE_BLUE = "#1A73E8"
COL_GOOGLE_GREEN = "#34A853"
COL_BRASS_GOLD = "#FBBC04"
COL_AMBER = "#F59E0B"

COL_RED_LED = "#EF4444"
COL_FLASH_WHITE = "#FFFFFF"
COL_FLASH_WARM = "#FEF08A"
COL_CYAN_CORE = "#38BDF8"
COL_CYAN_GLASS = "#BAE6FD"
COL_EMERALD_GLOW = "#4ADE80"
COL_EMERALD_FLUID = "#22C55E"
COL_EMERALD_GLASS = "#BBF7D0"


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


# ---------------------------------------------------------------------------
# Clean Procedural Mesh Primitives & BMesh Builders
# ---------------------------------------------------------------------------

def set_smooth(obj: bpy.types.Object, smooth: bool = True) -> None:
    if obj.type != "MESH":
        return
    mesh = obj.data
    n = len(mesh.polygons)
    if n > 0:
        mesh.polygons.foreach_set("use_smooth", [smooth] * n)
    mesh.update()


def link_mesh_object(
    name: str,
    bm: bmesh.types.BMesh,
    mat: bpy.types.Material | None = None,
    smooth: bool = True,
) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(name)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()

    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    if mat is not None:
        obj.data.materials.append(mat)
    set_smooth(obj, smooth=smooth)
    return obj


def add_lathed(
    name: str,
    profile_rz: list[tuple[float, float]],
    segments: int = 20,
    mat: bpy.types.Material | None = None,
    cap_bottom: bool = True,
    cap_top: bool = True,
    scale_xy: tuple[float, float] = (1.0, 1.0),
    location: tuple[float, float, float] = (0.0, 0.0, 0.0),
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
    phase_offset: float = 0.0,
    smooth: bool = True,
) -> bpy.types.Object:
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

    obj = link_mesh_object(name, bm, mat, smooth=smooth)
    obj.location = Vector(location)
    obj.rotation_euler = Euler(rotation, "XYZ")
    return obj


def add_beveled_box(
    name: str,
    size: tuple[float, float, float],
    location: tuple[float, float, float] = (0.0, 0.0, 0.0),
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
    bevel_width: float = 0.008,
    bevel_segments: int = 1,
    mat: bpy.types.Material | None = None,
    smooth: bool = True,
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
    obj = link_mesh_object(name, bm, mat, smooth=smooth)
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
    bevel_width: float = 0.010,
    bevel_segments: int = 1,
    mat: bpy.types.Material | None = None,
    phase_offset: float = 0.0,
    smooth: bool = True,
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
    obj = link_mesh_object(name, bm, mat, smooth=smooth)
    obj.location = Vector(location)
    obj.rotation_euler = Euler(rotation, "XYZ")
    return obj


def add_tube_path(
    name: str,
    points: list[tuple[float, float, float]],
    radius: float | list[float],
    segments: int = 8,
    mat: bpy.types.Material | None = None,
    closed: bool = False,
    cap_ends: bool = True,
) -> bpy.types.Object:
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
            t = t1 + t2
            t = t.normalized() if t.length > 1e-6 else t1
        tangents.append(t)

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


def add_ribbon_path(
    name: str,
    points: list[tuple[float, float, float]],
    width: float,
    thickness: float,
    mat: bpy.types.Material | None = None,
) -> bpy.types.Object:
    """Sweep a crisp rectangular strip (e.g. curved safety spoon lever) along a 2D curve in the XZ plane."""
    pts = [Vector(p) for p in points]
    n = len(pts)
    assert n >= 2
    hw = width * 0.5
    ht = thickness * 0.5

    bm = bmesh.new()
    rings = []
    for i in range(n):
        if i == 0:
            t = (pts[1] - pts[0]).normalized()
        elif i == n - 1:
            t = (pts[-1] - pts[-2]).normalized()
        else:
            t = ((pts[i] - pts[i - 1]).normalized() + (pts[i + 1] - pts[i]).normalized()).normalized()
        # Curve lies in XZ plane -> side is Y, outward normal is cross(Y, t)
        side = Vector((0.0, 1.0, 0.0))
        norm = side.cross(t).normalized()
        p = pts[i]
        v0 = bm.verts.new(p - side * hw - norm * ht)
        v1 = bm.verts.new(p + side * hw - norm * ht)
        v2 = bm.verts.new(p + side * hw + norm * ht)
        v3 = bm.verts.new(p - side * hw + norm * ht)
        rings.append([v0, v1, v2, v3])

    for i in range(n - 1):
        r0 = rings[i]
        r1 = rings[i + 1]
        for s in range(4):
            s2 = (s + 1) % 4
            bm.faces.new((r0[s], r0[s2], r1[s2], r1[s]))

    bm.faces.new(list(reversed(rings[0])))
    bm.faces.new(rings[-1])
    return link_mesh_object(name, bm, mat, smooth=False)


def add_torus_ring(
    name: str,
    major_r: float,
    minor_r: float,
    major_segs: int = 18,
    minor_segs: int = 8,
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


def check_glb_no_draco(glb_path: Path) -> bool:
    """Verify the exported GLB header JSON contains zero KHR_draco_mesh_compression."""
    with open(glb_path, "rb") as f:
        magic, version, total_len = struct.unpack("<4sII", f.read(12))
        assert magic == b"glTF", f"Invalid GLB magic in {glb_path}"
        chunk_len, chunk_type = struct.unpack("<I4s", f.read(8))
        assert chunk_type == b"JSON", f"Expected JSON chunk in {glb_path}"
        gltf_json = json.loads(f.read(chunk_len).decode("utf-8"))
    exts_used = gltf_json.get("extensionsUsed", [])
    exts_req = gltf_json.get("extensionsRequired", [])
    return (
        "KHR_draco_mesh_compression" not in exts_used
        and "KHR_draco_mesh_compression" not in exts_req
    )


def export_asset(objects: list[bpy.types.Object], filename: str, center_xy: bool = True, ground_z: bool = True) -> dict:
    if center_xy or ground_z:
        ground_and_center(objects, center_xy=center_xy, ground_z=ground_z)

    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    mins, maxs = world_bbox(objects)
    dims = maxs - mins
    tris = count_tris(objects)

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
    no_draco = check_glb_no_draco(out_path)
    assert no_draco, f"{filename} unexpectedly contains Draco compression!"
    assert abs(mins.z) < 1e-4, f"{filename} not grounded cleanly at Z=0 (min_z={mins.z:.5f})"
    assert size_bytes < 200 * 1024, f"{filename} exceeds 200 KB limit ({size_bytes / 1024.0:.1f} KB)!"

    return {
        "file": filename,
        "path": str(out_path),
        "tris": tris,
        "size_kb": size_bytes / 1024.0,
        "dims": (dims.x, dims.y, dims.z),
        "min_z": mins.z,
        "max_z": maxs.z,
        "no_draco": no_draco,
    }


# ===========================================================================
# 1. FRAG GRENADE (item_frag_grenade.glb)
# ===========================================================================

def build_frag_grenade() -> dict:
    """Modern tactical ribbed charcoal-steel ovoid frag grenade w/ Google-Red warning band,
    brass/gold safety lever & pull-ring pin, and glowing red top fuse LED."""
    clear_scene()
    objs = []

    mat_charcoal = make_pbr_mat("FG_CharcoalSteel", COL_CHARCOAL_STEEL, metallic=0.78, roughness=0.34)
    mat_rubber = make_pbr_mat("FG_RubberBase", COL_RUBBER, metallic=0.0, roughness=0.85)
    mat_gunmetal = make_pbr_mat("FG_GunmetalFuse", COL_GUNMETAL, metallic=0.82, roughness=0.28)
    mat_steel = make_pbr_mat("FG_SteelDetail", COL_TITANIUM, metallic=0.88, roughness=0.24)
    mat_google_red = make_pbr_mat("FG_GoogleRedBand", COL_GOOGLE_RED, metallic=0.14, roughness=0.30, coat=0.45)
    mat_brass = make_pbr_mat("FG_BrassGold", COL_BRASS_GOLD, metallic=0.86, roughness=0.22)
    mat_red_led = make_pbr_mat(
        "FG_RedFuseLED",
        COL_RED_LED,
        metallic=0.0,
        roughness=0.10,
        emission_hex="#FF1414",
        emission_strength=3.0,
    )

    # Flattened tactical rubber/polymer bottom pad (cleanly grounded at Z=0.000)
    objs.append(add_lathed(
        "GrenadeBasePad",
        [(0.050, 0.000), (0.062, 0.006), (0.066, 0.018), (0.056, 0.022)],
        segments=14,
        mat=mat_rubber,
    ))

    # Ribbed charcoal-steel ovoid fragmentation body with horizontal tactical grooves
    body_profile = [
        (0.058, 0.018),
        (0.078, 0.036),
        (0.092, 0.064),
        # Groove 1
        (0.096, 0.082),
        (0.091, 0.088),
        (0.091, 0.094),
        (0.099, 0.100),
        # Equator rib
        (0.101, 0.124),
        # Groove 2
        (0.096, 0.130),
        (0.096, 0.136),
        (0.100, 0.142),
        # Upper rib below red warning band
        (0.097, 0.162),
        (0.091, 0.172),
        # Slight recess for Google-Red warning band (Z=0.172..0.204)
        (0.084, 0.176),
        (0.075, 0.202),
        # Upper shoulder above red band
        (0.077, 0.206),
        (0.066, 0.224),
        (0.048, 0.238),
        (0.040, 0.244),
    ]
    objs.append(add_lathed(
        "GrenadeOvoidBody",
        body_profile,
        segments=16,
        mat=mat_charcoal,
    ))

    # 8 Vertical Tactical Fragmentation Ribs hugging the ovoid body equator
    for i in range(8):
        ang = (2.0 * math.pi * i) / 8.0 + math.pi / 8.0
        ca, sa = math.cos(ang), math.sin(ang)
        rib_pts = [
            (0.078 * ca, 0.078 * sa, 0.044),
            (0.095 * ca, 0.095 * sa, 0.078),
            (0.102 * ca, 0.102 * sa, 0.118),
            (0.099 * ca, 0.099 * sa, 0.156),
            (0.088 * ca, 0.088 * sa, 0.174),
        ]
        objs.append(add_tube_path(
            f"FragRib_{i}",
            rib_pts,
            radius=[0.007, 0.009, 0.0095, 0.009, 0.0065],
            segments=5,
            mat=mat_charcoal,
        ))

    # Bold Google-Red tactical warning band on upper shoulder
    objs.append(add_lathed(
        "GoogleRedWarningBand",
        [
            (0.088, 0.173),
            (0.092, 0.177),
            (0.084, 0.201),
            (0.078, 0.205),
        ],
        segments=16,
        mat=mat_google_red,
        cap_bottom=False,
        cap_top=False,
    ))

    # Machined steel threaded neck & fuse collar
    objs.append(add_lathed(
        "FuseNeckCollar",
        [
            (0.044, 0.240),
            (0.046, 0.246),
            (0.046, 0.264),
            (0.038, 0.270),
            (0.038, 0.284),
            (0.043, 0.290),
            (0.043, 0.308),
            (0.036, 0.314),
        ],
        segments=14,
        mat=mat_gunmetal,
    ))

    # Top striker cap bezel & glowing red fuse LED dome
    objs.append(add_lathed(
        "FuseLEDBezel",
        [(0.028, 0.312), (0.032, 0.316), (0.030, 0.324), (0.022, 0.326)],
        segments=12,
        mat=mat_steel,
    ))
    objs.append(add_lathed(
        "FuseRedLED",
        [(0.021, 0.318), (0.021, 0.328), (0.014, 0.335), (0.000, 0.338)],
        segments=12,
        mat=mat_red_led,
        cap_top=False,
    ))

    # Striker hinge ear boss on +X side of fuse head
    objs.append(add_beveled_box(
        "StrikerHingeBoss",
        size=(0.046, 0.032, 0.028),
        location=(0.038, 0.0, 0.298),
        bevel_width=0.004,
        bevel_segments=1,
        mat=mat_gunmetal,
    ))

    # Brass/gold safety spoon lever curving smoothly over +X shoulder (clear of ovoid body)
    spoon_pts = [
        (0.028, 0.0, 0.312),
        (0.052, 0.0, 0.312),
        (0.074, 0.0, 0.304),
        (0.094, 0.0, 0.288),
        (0.108, 0.0, 0.262),
        (0.118, 0.0, 0.228),
        (0.123, 0.0, 0.184),
        (0.124, 0.0, 0.130),
        (0.116, 0.0, 0.072),
    ]
    objs.append(add_ribbon_path(
        "BrassSafetyLever",
        spoon_pts,
        width=0.028,
        thickness=0.007,
        mat=mat_brass,
    ))

    # Brass cotter pin barrel & safety pull-ring on -X side of fuse head
    objs.append(add_tube_path(
        "BrassCotterPin",
        [(-0.022, 0.0, 0.296), (-0.056, 0.0, 0.296)],
        radius=0.0055,
        segments=5,
        mat=mat_brass,
    ))
    objs.append(add_torus_ring(
        "BrassPullRing",
        major_r=0.032,
        minor_r=0.0055,
        major_segs=14,
        minor_segs=5,
        location=(-0.084, 0.0, 0.284),
        rotation=(math.radians(90.0), math.radians(24.0), 0.0),
        mat=mat_brass,
    ))

    return export_asset(objs, "item_frag_grenade.glb")


# ===========================================================================
# 2. FLASHBANG (item_flashbang.glb)
# ===========================================================================

def build_flashbang() -> dict:
    """Cylindrical brushed-aluminum tactical stun canister w/ dark grip ribs,
    recessed bright-white glowing flash vent ports, amber caution stripe,
    and curved spoon lever + pull ring."""
    clear_scene()
    objs = []

    mat_alum = make_pbr_mat("FB_BrushedAlum", "#EDF2F7", metallic=0.88, roughness=0.20)
    mat_gunmetal = make_pbr_mat("FB_Gunmetal", COL_GUNMETAL, metallic=0.80, roughness=0.30)
    mat_grip = make_pbr_mat("FB_DarkGrip", COL_DARK_SLATE, metallic=0.10, roughness=0.76)
    mat_rubber = make_pbr_mat("FB_Rubber", COL_RUBBER, metallic=0.0, roughness=0.88)
    mat_amber = make_pbr_mat("FB_AmberStripe", COL_AMBER, metallic=0.18, roughness=0.30, coat=0.40)
    mat_flash_core = make_pbr_mat(
        "FB_FlashVentGlow",
        COL_FLASH_WHITE,
        metallic=0.0,
        roughness=0.08,
        emission_hex=COL_FLASH_WARM,
        emission_strength=4.8,
    )

    # Matte rubberized bottom bumper ring (grounded cleanly at Z=0.000)
    objs.append(add_lathed(
        "FlashBasePad",
        [(0.056, 0.000), (0.068, 0.006), (0.070, 0.018), (0.064, 0.022)],
        segments=14,
        mat=mat_rubber,
    ))

    # Main brushed-aluminum cylindrical stun canister body with stepped end-caps
    objs.append(add_lathed(
        "FlashAlumCanister",
        [
            (0.064, 0.020),
            (0.076, 0.028),
            (0.076, 0.056),
            (0.071, 0.062),
            (0.071, 0.244),
            (0.076, 0.250),
            (0.076, 0.278),
            (0.068, 0.288),
            (0.054, 0.292),
        ],
        segments=16,
        mat=mat_alum,
    ))

    # Recessed dark grip ribs band around middle section (3 crisp horizontal dark grip rings)
    for idx, rz in enumerate((0.108, 0.128, 0.148)):
        objs.append(add_lathed(
            f"DarkGripRib_{idx}",
            [
                (0.070, rz - 0.007),
                (0.075, rz - 0.005),
                (0.075, rz + 0.005),
                (0.070, rz + 0.007),
            ],
            segments=16,
            mat=mat_grip,
            cap_bottom=False,
            cap_top=False,
        ))

    # 3 slim vertical dark tactical guard rails framing the grip zone
    for i in range(3):
        ang = i * (2.0 * math.pi / 3.0) + math.pi / 6.0
        ca, sa = math.cos(ang), math.sin(ang)
        objs.append(add_beveled_box(
            f"GuardRail_{i}",
            size=(0.012, 0.018, 0.185),
            location=(0.073 * ca, 0.073 * sa, 0.153),
            rotation=(0.0, 0.0, ang),
            bevel_width=0.0025,
            bevel_segments=1,
            mat=mat_grip,
        ))

    # Bold amber caution stripe around upper-mid canister (Z=0.170..0.198)
    objs.append(add_lathed(
        "AmberCautionStripe",
        [
            (0.071, 0.168),
            (0.0745, 0.171),
            (0.0745, 0.195),
            (0.071, 0.198),
        ],
        segments=16,
        mat=mat_amber,
        cap_bottom=False,
        cap_top=False,
    ))

    # Two tiers of 6 recessed bright-white glowing flash vent ports (lower Z=0.078, upper Z=0.222)
    for tier_idx, vz in enumerate((0.078, 0.222)):
        for i in range(6):
            ang = i * (math.pi / 3.0)
            ca, sa = math.cos(ang), math.sin(ang)
            # Dark recessed cylindrical bezel collar protruding slightly from canister wall
            objs.append(add_lathed(
                f"FlashPortBezel_{tier_idx}_{i}",
                [(0.014, 0.000), (0.014, 0.009), (0.011, 0.011)],
                segments=7,
                mat=mat_grip,
                location=(0.067 * ca, 0.067 * sa, vz),
                rotation=(0.0, math.radians(90.0), ang),
                cap_bottom=False,
            ))
            # Glowing bright-white / warm-yellow flash vent lens recessed inside bezel
            objs.append(add_lathed(
                f"FlashPortLens_{tier_idx}_{i}",
                [(0.0095, 0.004), (0.0095, 0.010), (0.000, 0.012)],
                segments=7,
                mat=mat_flash_core,
                location=(0.067 * ca, 0.067 * sa, vz),
                rotation=(0.0, math.radians(90.0), ang),
                cap_bottom=False,
                cap_top=False,
            ))

    # Machined top fuze assembly & striker head
    objs.append(add_lathed(
        "FlashFuzeHead",
        [
            (0.042, 0.288),
            (0.045, 0.296),
            (0.045, 0.316),
            (0.038, 0.324),
            (0.038, 0.348),
            (0.030, 0.356),
            (0.000, 0.358),
        ],
        segments=14,
        mat=mat_gunmetal,
        cap_top=False,
    ))

    # Top glowing ready-indicator ring on fuze collar
    objs.append(add_lathed(
        "FlashTopLED",
        [(0.039, 0.330), (0.0415, 0.332), (0.0415, 0.340), (0.039, 0.342)],
        segments=12,
        mat=mat_flash_core,
        cap_bottom=False,
        cap_top=False,
    ))

    # Striker hinge ear on +X side
    objs.append(add_beveled_box(
        "FlashHingeEar",
        size=(0.042, 0.028, 0.026),
        location=(0.034, 0.0, 0.336),
        bevel_width=0.0035,
        bevel_segments=1,
        mat=mat_gunmetal,
    ))

    # Curved brushed-aluminum / steel safety spoon lever hugging +X side
    spoon_pts = [
        (0.026, 0.0, 0.350),
        (0.050, 0.0, 0.350),
        (0.072, 0.0, 0.340),
        (0.088, 0.0, 0.318),
        (0.095, 0.0, 0.284),
        (0.096, 0.0, 0.200),
        (0.094, 0.0, 0.115),
        (0.088, 0.0, 0.068),
    ]
    objs.append(add_ribbon_path(
        "FlashSpoonLever",
        spoon_pts,
        width=0.026,
        thickness=0.0065,
        mat=mat_alum,
    ))

    # Cotter pin + amber-gold pull ring on -X side
    objs.append(add_tube_path(
        "FlashPinStem",
        [(-0.022, 0.0, 0.334), (-0.056, 0.0, 0.334)],
        radius=0.005,
        segments=5,
        mat=mat_amber,
    ))
    objs.append(add_torus_ring(
        "FlashPullRing",
        major_r=0.030,
        minor_r=0.005,
        major_segs=14,
        minor_segs=5,
        location=(-0.082, 0.0, 0.322),
        rotation=(math.radians(90.0), math.radians(22.0), 0.0),
        mat=mat_amber,
    ))

    return export_asset(objs, "item_flashbang.glb")


# ===========================================================================
# 3. SHIELD DROP DOME EMITTER (item_shield_drop.glb)
# ===========================================================================

def build_shield_drop() -> dict:
    """Sleek hexagonal pearl-white & Google-Blue portable dome projector disc on 3 compact
    folded tripod fins with a luminous cyan-blue crystalline energy emitter core and concentric tech rings."""
    clear_scene()
    objs = []

    mat_pearl = make_pbr_mat("SD_PearlWhite", COL_PEARL_WHITE, metallic=0.06, roughness=0.26, coat=0.50)
    mat_gblue = make_pbr_mat("SD_GoogleBlue", COL_GOOGLE_BLUE, metallic=0.42, roughness=0.26, coat=0.45)
    mat_slate = make_pbr_mat("SD_DarkSlate", COL_DARK_SLATE, metallic=0.28, roughness=0.56)
    mat_titanium = make_pbr_mat("SD_Titanium", COL_TITANIUM, metallic=0.84, roughness=0.26)
    mat_rubber = make_pbr_mat("SD_RubberFoot", COL_RUBBER, metallic=0.0, roughness=0.88)
    mat_cyan_glow = make_pbr_mat(
        "SD_CyanEmitter",
        COL_CYAN_CORE,
        metallic=0.0,
        roughness=0.08,
        emission_hex="#00B8FF",
        emission_strength=3.2,
    )
    mat_cyan_glass = make_pbr_mat(
        "SD_CyanCrystalShell",
        COL_CYAN_GLASS,
        metallic=0.05,
        roughness=0.06,
        specular=0.85,
        coat=0.80,
        ior=1.52,
        alpha=0.26,
        backface_cull=True,
    )

    # Lower central stabilizer hub (sits slightly above ground, supported by 3 tripod fins)
    objs.append(add_lathed(
        "BottomStabilizerHub",
        [(0.068, 0.016), (0.095, 0.024), (0.118, 0.048), (0.118, 0.062)],
        segments=12,
        mat=mat_slate,
    ))

    # Main sleek hexagonal pearl-white dome projector disc body
    objs.append(add_beveled_prism(
        "HexPearlChassis",
        radius=0.175,
        height=0.072,
        sides=6,
        location=(0.0, 0.0, 0.088),
        bevel_width=0.014,
        bevel_segments=2,
        mat=mat_pearl,
    ))

    # Recessed dark-slate mid-skirt belt around hexagonal perimeter
    objs.append(add_beveled_prism(
        "HexSlateBelt",
        radius=0.179,
        height=0.020,
        sides=6,
        location=(0.0, 0.0, 0.084),
        bevel_width=0.004,
        bevel_segments=1,
        mat=mat_slate,
    ))

    # Upper Google-Blue hexagonal armor deck plate
    objs.append(add_beveled_prism(
        "HexBlueUpperDeck",
        radius=0.146,
        height=0.026,
        sides=6,
        location=(0.0, 0.0, 0.130),
        bevel_width=0.008,
        bevel_segments=1,
        mat=mat_gblue,
    ))

    # 3 Compact Folded Tripod Fins at 120° intervals (grounded cleanly at Z=0.000!)
    for i in range(3):
        ang = i * (2.0 * math.pi / 3.0) + math.pi / 6.0
        ca, sa = math.cos(ang), math.sin(ang)

        # Grounded rubber foot pad at Z=0.000
        objs.append(add_beveled_box(
            f"TripodFootPad_{i}",
            size=(0.056, 0.044, 0.018),
            location=(0.178 * ca, 0.178 * sa, 0.009),
            rotation=(0.0, 0.0, ang),
            bevel_width=0.004,
            bevel_segments=1,
            mat=mat_rubber,
        ))

        # Structural dark-slate leg strut angling up into the hex chassis
        objs.append(add_beveled_box(
            f"TripodStrut_{i}",
            size=(0.072, 0.036, 0.082),
            location=(0.158 * ca, 0.158 * sa, 0.054),
            rotation=(0.0, math.radians(-20.0), ang),
            bevel_width=0.005,
            bevel_segments=1,
            mat=mat_slate,
        ))

        # Sleek Google-Blue outer armored fin cover wrapping the tripod knee
        objs.append(add_beveled_box(
            f"TripodBlueFin_{i}",
            size=(0.042, 0.046, 0.098),
            location=(0.178 * ca, 0.178 * sa, 0.078),
            rotation=(0.0, math.radians(-16.0), ang),
            bevel_width=0.006,
            bevel_segments=1,
            mat=mat_gblue,
        ))

        # Slim glowing cyan status strip on each outer fin
        objs.append(add_beveled_box(
            f"TripodCyanAccent_{i}",
            size=(0.010, 0.012, 0.052),
            location=(0.197 * ca, 0.197 * sa, 0.076),
            rotation=(0.0, math.radians(-16.0), ang),
            bevel_width=0.002,
            bevel_segments=1,
            mat=mat_cyan_glow,
        ))

        # Radial emitter projector prong angling inward over the top crystal core
        prong_pts = [
            (0.132 * ca, 0.132 * sa, 0.142),
            (0.118 * ca, 0.118 * sa, 0.184),
            (0.088 * ca, 0.088 * sa, 0.210),
        ]
        objs.append(add_tube_path(
            f"EmitterProng_{i}",
            prong_pts,
            radius=[0.012, 0.010, 0.007],
            segments=6,
            mat=mat_pearl,
        ))

    # Concentric precision tech rings on top of the dome projector
    # Ring 1: Outer brushed titanium bezel ring
    objs.append(add_torus_ring(
        "TechRingOuterTi",
        major_r=0.114,
        minor_r=0.009,
        major_segs=16,
        minor_segs=5,
        location=(0.0, 0.0, 0.146),
        mat=mat_titanium,
    ))
    # Ring 2: Glowing cyan energy conduit ring
    objs.append(add_torus_ring(
        "TechRingCyanGlow",
        major_r=0.092,
        minor_r=0.0065,
        major_segs=16,
        minor_segs=5,
        location=(0.0, 0.0, 0.156),
        mat=mat_cyan_glow,
    ))
    # Ring 3: Inner Google-Blue emitter collar
    objs.append(add_lathed(
        "InnerEmitterCollar",
        [(0.068, 0.142), (0.076, 0.148), (0.072, 0.172), (0.062, 0.178)],
        segments=14,
        mat=mat_gblue,
    ))

    # Luminous cyan-blue crystalline energy emitter core (faceted 8-sided crystal spire!)
    objs.append(add_lathed(
        "CyanCrystalCore",
        [
            (0.036, 0.150),
            (0.052, 0.186),
            (0.044, 0.232),
            (0.022, 0.264),
            (0.000, 0.280),
        ],
        segments=8,
        mat=mat_cyan_glow,
        cap_top=False,
        smooth=False,
    ))

    # Outer translucent crystalline dome shell protecting the energy core
    objs.append(add_lathed(
        "CyanCrystalDome",
        [
            (0.062, 0.168),
            (0.066, 0.205),
            (0.056, 0.244),
            (0.036, 0.274),
            (0.000, 0.292),
        ],
        segments=16,
        mat=mat_cyan_glass,
        cap_bottom=False,
        cap_top=False,
    ))

    return export_asset(objs, "item_shield_drop.glb")


# ===========================================================================
# 4. REGENERATION POD (item_regen_pod.glb)
# ===========================================================================

def add_healing_cross_badge(
    name: str,
    center: tuple[float, float, float],
    rot_z: float,
    mat_bezel: bpy.types.Material,
    mat_glow: bpy.types.Material,
) -> list[bpy.types.Object]:
    """Build a crisp 3D recessed dark bezel + glowing emerald healing cross (+)."""
    parts = []
    cx, cy, cz = center
    rot = (0.0, 0.0, rot_z)
    # Recessed backing plaque
    parts.append(add_beveled_box(
        f"{name}_Bezel",
        size=(0.052, 0.010, 0.052),
        location=(cx, cy, cz),
        rotation=rot,
        bevel_width=0.003,
        bevel_segments=1,
        mat=mat_bezel,
    ))
    # Forward offset along local +Y normal
    nx = -math.sin(rot_z)
    ny = math.cos(rot_z)
    off = 0.006
    # Vertical bar of emerald healing cross
    parts.append(add_beveled_box(
        f"{name}_CrossV",
        size=(0.013, 0.007, 0.038),
        location=(cx + nx * off, cy + ny * off, cz),
        rotation=rot,
        bevel_width=0.0015,
        bevel_segments=1,
        mat=mat_glow,
    ))
    # Horizontal bar of emerald healing cross
    parts.append(add_beveled_box(
        f"{name}_CrossH",
        size=(0.038, 0.007, 0.013),
        location=(cx + nx * off, cy + ny * off, cz),
        rotation=rot,
        bevel_width=0.0015,
        bevel_segments=1,
        mat=mat_glow,
    ))
    return parts


def build_regen_pod() -> dict:
    """Clean rounded pearl-white & Google-Green Bio-Med vertical capsule pod on a compact
    stabilized base with glowing emerald healing cross accents, transparent/glowing
    bio-fluid chamber window, and top emitter dish."""
    clear_scene()
    objs = []

    mat_pearl = make_pbr_mat("RP_PearlWhite", COL_PEARL_WHITE, metallic=0.05, roughness=0.25, coat=0.55)
    mat_ggreen = make_pbr_mat("RP_GoogleGreen", COL_GOOGLE_GREEN, metallic=0.22, roughness=0.28, coat=0.45)
    mat_slate = make_pbr_mat("RP_DarkSlate", COL_DARK_SLATE, metallic=0.26, roughness=0.58)
    mat_steel = make_pbr_mat("RP_BrushedSteel", COL_BRUSHED_ALUM, metallic=0.86, roughness=0.24)
    mat_emerald_glow = make_pbr_mat(
        "RP_EmeraldGlow",
        COL_EMERALD_GLOW,
        metallic=0.0,
        roughness=0.10,
        emission_hex="#10E860",
        emission_strength=2.8,
    )
    mat_bio_fluid = make_pbr_mat(
        "RP_BioFluidCore",
        COL_EMERALD_FLUID,
        metallic=0.0,
        roughness=0.14,
        emission_hex="#18DC5C",
        emission_strength=1.45,
        alpha=0.76,
        backface_cull=True,
    )
    mat_bio_glass = make_pbr_mat(
        "RP_BioGlassChamber",
        COL_EMERALD_GLASS,
        metallic=0.04,
        roughness=0.05,
        specular=0.82,
        coat=0.80,
        ior=1.48,
        alpha=0.22,
        backface_cull=True,
    )

    # Compact stabilized circular base (grounded cleanly at Z=0.000)
    objs.append(add_lathed(
        "StabilizedBase",
        [
            (0.098, 0.000),
            (0.114, 0.008),
            (0.114, 0.022),
            (0.102, 0.032),
            (0.090, 0.038),
        ],
        segments=14,
        mat=mat_slate,
    ))

    # 4 compact flared stabilizer foot pads at 45° diagonals (resting at Z=0.000)
    for i in range(4):
        ang = i * (math.pi / 2.0) + math.pi / 4.0
        ca, sa = math.cos(ang), math.sin(ang)
        objs.append(add_beveled_box(
            f"StabilizerFoot_{i}",
            size=(0.044, 0.034, 0.020),
            location=(0.106 * ca, 0.106 * sa, 0.010),
            rotation=(0.0, 0.0, ang),
            bevel_width=0.004,
            bevel_segments=1,
            mat=mat_slate,
        ))

    # Google-Green base accent collar
    objs.append(add_lathed(
        "BaseGreenCollar",
        [(0.094, 0.032), (0.100, 0.038), (0.100, 0.052), (0.092, 0.058)],
        segments=14,
        mat=mat_ggreen,
    ))

    # Rounded Pearl-White lower Bio-Med capsule cowling
    objs.append(add_lathed(
        "LowerPearlCowling",
        [
            (0.092, 0.054),
            (0.104, 0.068),
            (0.106, 0.108),
            (0.098, 0.128),
            (0.086, 0.136),
        ],
        segments=16,
        mat=mat_pearl,
    ))

    # Translucent outer bio-fluid glass chamber window (Z=0.130..0.286)
    objs.append(add_lathed(
        "BioFluidGlassWindow",
        [
            (0.084, 0.130),
            (0.088, 0.138),
            (0.088, 0.278),
            (0.084, 0.286),
        ],
        segments=16,
        mat=mat_bio_glass,
        cap_bottom=False,
        cap_top=False,
    ))

    # Inner glowing emerald bio-fluid core with meniscus curve
    objs.append(add_lathed(
        "BioFluidLiquidCore",
        [
            (0.000, 0.134),
            (0.070, 0.138),
            (0.072, 0.256),
            (0.064, 0.270),
            (0.000, 0.274),
        ],
        segments=14,
        mat=mat_bio_fluid,
        cap_bottom=False,
        cap_top=False,
    ))

    # Bright central emerald healing column + twin floating bio-rings inside chamber
    objs.append(add_lathed(
        "InnerBioColumn",
        [(0.022, 0.138), (0.026, 0.208), (0.022, 0.272)],
        segments=8,
        mat=mat_emerald_glow,
    ))
    for idx, rz in enumerate((0.180, 0.236)):
        objs.append(add_torus_ring(
            f"BioEnergyRing_{idx}",
            major_r=0.052,
            minor_r=0.006,
            major_segs=12,
            minor_segs=4,
            location=(0.0, 0.0, rz),
            mat=mat_emerald_glow,
        ))

    # Rounded Pearl-White upper Bio-Med capsule cowling
    objs.append(add_lathed(
        "UpperPearlCowling",
        [
            (0.086, 0.280),
            (0.098, 0.288),
            (0.104, 0.308),
            (0.096, 0.332),
            (0.078, 0.348),
            (0.060, 0.356),
        ],
        segments=16,
        mat=mat_pearl,
    ))

    # 3 Sculpted vertical containment ribs (Google-Green) bridging lower & upper cowlings
    # Placed at 90°, 210°, 330° so front (-Y = 270°) has a wide, unobstructed view of the bio-fluid window!
    for i in range(3):
        ang = math.radians(90.0 + i * 120.0)
        ca, sa = math.cos(ang), math.sin(ang)
        rib_pts = [
            (0.096 * ca, 0.096 * sa, 0.118),
            (0.104 * ca, 0.104 * sa, 0.152),
            (0.102 * ca, 0.102 * sa, 0.208),
            (0.104 * ca, 0.104 * sa, 0.264),
            (0.096 * ca, 0.096 * sa, 0.296),
        ]
        objs.append(add_tube_path(
            f"BioContainmentRib_{i}",
            rib_pts,
            radius=[0.011, 0.012, 0.011, 0.012, 0.011],
            segments=5,
            mat=mat_ggreen,
        ))

    # Glowing emerald healing cross accents on front (-Y) and back (+Y) of the lower pearl cowling
    objs.extend(add_healing_cross_badge(
        "HealingCrossFront",
        center=(0.0, 0.105, 0.090),
        rot_z=0.0,
        mat_bezel=mat_slate,
        mat_glow=mat_emerald_glow,
    ))
    objs.extend(add_healing_cross_badge(
        "HealingCrossBack",
        center=(0.0, -0.105, 0.090),
        rot_z=math.pi,
        mat_bezel=mat_slate,
        mat_glow=mat_emerald_glow,
    ))

    # Top Google-Green neck collar & concave Bio-Med Emitter Dish
    objs.append(add_lathed(
        "TopEmitterNeck",
        [(0.056, 0.352), (0.062, 0.358), (0.058, 0.376), (0.046, 0.382)],
        segments=14,
        mat=mat_ggreen,
    ))
    # Concave parabolic top emitter dish (pearl-white outer + brushed-steel inner bowl)
    objs.append(add_lathed(
        "TopEmitterDish",
        [
            (0.044, 0.378),
            (0.076, 0.392),
            (0.094, 0.412),
            (0.088, 0.418),
            (0.066, 0.402),
            (0.036, 0.394),
            (0.000, 0.392),
        ],
        segments=16,
        mat=mat_pearl,
        cap_top=False,
    ))
    # Thin glowing emerald emitter rim ring around top dish lip
    objs.append(add_torus_ring(
        "TopDishGlowRim",
        major_r=0.090,
        minor_r=0.0045,
        major_segs=16,
        minor_segs=5,
        location=(0.0, 0.0, 0.415),
        mat=mat_emerald_glow,
    ))
    # Central glowing emerald emitter spire inside the dish
    objs.append(add_lathed(
        "TopDishEmitterNode",
        [(0.018, 0.390), (0.020, 0.412), (0.012, 0.426), (0.000, 0.432)],
        segments=10,
        mat=mat_emerald_glow,
        cap_top=False,
    ))
    # Brushed steel collar ring at emitter node base
    objs.append(add_torus_ring(
        "TopDishSteelCollar",
        major_r=0.024,
        minor_r=0.005,
        major_segs=12,
        minor_segs=4,
        location=(0.0, 0.0, 0.396),
        mat=mat_steel,
    ))

    return export_asset(objs, "item_regen_pod.glb")


# ===========================================================================
# 2x2 Studio EEVEE Visual QA Preview Renderer
# ===========================================================================

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
    "Q": ["01110", "10001", "10001", "10001", "10101", "10010", "01101"],
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
    " ": ["00000", "00000", "00000", "00000", "00000", "00000", "00000"],
}


def draw_label_text(
    img: np.ndarray,
    text: str,
    x0: int,
    y0: int,
    scale: int = 2,
    color: tuple = (0.94, 0.96, 0.99),
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
    scene.view_settings.exposure = 0.15

    # Soft studio world background (dark slate-blue so white, chrome & emissives all pop)
    world = bpy.data.worlds.new("StudioWorld")
    scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    bg = nt.nodes.get("Background")
    if bg:
        bg.inputs["Color"].default_value = (0.045, 0.055, 0.075, 1.0)
        bg.inputs["Strength"].default_value = 0.75

    # Matte studio turntable pedestal floor at Z=0
    bm = bmesh.new()
    bmesh.ops.create_cone(
        bm,
        cap_ends=True,
        cap_tris=False,
        segments=48,
        radius1=0.65,
        radius2=0.65,
        depth=0.02,
    )
    for v in bm.verts:
        v.co.z -= 0.01
    floor_mat = make_pbr_mat("StudioFloor", "#232A36", metallic=0.10, roughness=0.55)
    link_mesh_object("StudioFloor", bm, floor_mat)

    # 3-Point Studio Area Lighting
    lights = [
        ("KeyLight", "AREA", (1.2, -1.1, 1.3), (math.radians(52), 0.0, math.radians(46)), 95.0, (1.0, 0.97, 0.93), 0.9),
        ("FillLight", "AREA", (-1.3, -0.7, 0.8), (math.radians(66), 0.0, math.radians(-62)), 48.0, (0.82, 0.90, 1.0), 1.2),
        ("RimLight", "AREA", (0.2, 1.4, 1.1), (math.radians(122), 0.0, math.radians(170)), 75.0, (0.90, 0.96, 1.0), 0.9),
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


def render_single_glb_panel(
    glb_path: str,
    out_png: str,
    azim_deg: float = 34.0,
    elev_deg: float = 24.0,
    res_x: int = 640,
    res_y: int = 512,
) -> np.ndarray:
    clear_scene()
    setup_studio_eevee(res_x=res_x, res_y=res_y, samples=24)

    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=glb_path)
    imported = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
    mins, maxs = world_bbox(imported)
    center = 0.5 * (mins + maxs)
    extent = maxs - mins
    radius = max(extent.length * 0.5, 0.10)

    cam_data = bpy.data.cameras.new("QACam")
    cam_data.lens = 55.0
    cam_obj = bpy.data.objects.new("QACam", cam_data)
    bpy.context.scene.collection.objects.link(cam_obj)
    bpy.context.scene.camera = cam_obj

    dist = radius * 3.70
    target = Vector((center.x, center.y, center.z - extent.z * 0.05))
    az = math.radians(azim_deg)
    el = math.radians(elev_deg)
    cam_pos = target + Vector((
        dist * math.cos(el) * math.sin(az),
        -dist * math.cos(el) * math.cos(az),
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
    arr = px.reshape((h, w, 4))[::-1, :, :].copy()  # top-down
    bpy.data.images.remove(img)
    return arr


def render_qa_grid(results: list[dict]) -> None:
    QA_PREVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
    panel_w, panel_h = 640, 512
    header_h = 46
    grid_w = panel_w * 2
    grid_h = header_h + panel_h * 2
    canvas = np.zeros((grid_h, grid_w, 4), dtype=np.float32)
    canvas[:, :, :3] = np.array([0.06, 0.08, 0.11], dtype=np.float32)
    canvas[:, :, 3] = 1.0

    draw_label_text(
        canvas,
        "WORKSPACE ROYALE - 4 NEW UTILITY ITEMS STUDIO EEVEE QA",
        x0=24,
        y0=16,
        scale=2,
        color=(0.95, 0.97, 1.0),
    )

    labels = [
        ("1. FRAG GRENADE", 28.0, 22.0),
        ("2. FLASHBANG", 32.0, 22.0),
        ("3. SHIELD DROP", 36.0, 28.0),
        ("4. REGEN POD", 26.0, 22.0),
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        for idx, (res, (title, az, el)) in enumerate(zip(results, labels)):
            tmp_png = os.path.join(tmpdir, f"panel_{idx}.png")
            panel = render_single_glb_panel(
                res["path"], tmp_png, azim_deg=az, elev_deg=el, res_x=panel_w, res_y=panel_h
            )
            # Subtle bottom dark label bar on each panel
            bar_h = 38
            panel[panel_h - bar_h :, :, :3] = panel[panel_h - bar_h :, :, :3] * 0.28 + 0.04
            dx, dy, dz = res["dims"]
            caption = f"{title} | {res['tris']} TRIS | {res['size_kb']:.1f} KB | H {dz:.2f}M"
            draw_label_text(panel, caption, x0=16, y0=panel_h - 26, scale=2, color=(0.94, 0.97, 1.0))

            row = idx // 2
            col = idx % 2
            y0 = header_h + row * panel_h
            x0 = col * panel_w
            canvas[y0 : y0 + panel_h, x0 : x0 + panel_w, :] = panel

    # Subtle 2px divider lines between quadrants
    canvas[header_h - 1 : header_h + 1, :, :3] = 0.22
    canvas[header_h + panel_h - 1 : header_h + panel_h + 1, :, :3] = 0.22
    canvas[header_h:, panel_w - 1 : panel_w + 1, :3] = 0.22

    # Save via Blender image writer
    clear_scene()
    out_img = bpy.data.images.new("QA_NewUtilities", width=grid_w, height=grid_h, alpha=True)
    out_img.colorspace_settings.name = "sRGB"
    flipped = np.ascontiguousarray(canvas[::-1, :, :], dtype=np.float32)
    out_img.pixels.foreach_set(flipped.ravel())
    out_img.filepath_raw = str(QA_PREVIEW_PATH)
    out_img.file_format = "PNG"
    out_img.save()
    print(f"  [QA] Saved 2x2 studio EEVEE preview -> {QA_PREVIEW_PATH}")


# ===========================================================================
# Main Entrypoint
# ===========================================================================

def main() -> int:
    builders = [
        build_frag_grenade,
        build_flashbang,
        build_shield_drop,
        build_regen_pod,
    ]

    results = []
    print("=" * 88)
    print("Workspace Royale — Building 4 New Tactical Utility GLBs (Blender 5.3.0, ZERO Draco)")
    print("=" * 88)

    for fn in builders:
        res = fn()
        results.append(res)
        dx, dy, dz = res["dims"]
        print(
            f"  [OK] {res['file']:<24} | {res['tris']:>5} tris | {res['size_kb']:>6.1f} KB | "
            f"dims=({dx:.2f} x {dy:.2f} x {dz:.2f}m) | Z=[{res['min_z']:+.3f}, {res['max_z']:+.3f}] | "
            f"draco=OFF"
        )

    total_kb = sum(r["size_kb"] for r in results)
    total_tris = sum(r["tris"] for r in results)
    print("-" * 88)
    print(f"  TOTAL: {len(results)} assets | {total_tris} tris | {total_kb:.1f} KB")
    print("=" * 88)

    render_qa_grid(results)
    return 0


if __name__ == "__main__":
    sys.exit(main())

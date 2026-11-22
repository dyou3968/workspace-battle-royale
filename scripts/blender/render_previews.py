#!/usr/bin/env python3
"""
Workspace Royale — Headless Blender 5.3.0 EEVEE Visual QA Renderer & GLB Structural Auditor.

Usage:
  blender --background --python scripts/blender/render_previews.py -- [options]

Options:
  --category {all,characters,weapons,utilities,map}  Category to validate & render (default: all)
  --validate-only                                    Run structural GLB audit without EEVEE rendering
  --json-out PATH                                    Save structured validation report JSON
  --mirror-dir PATH                                  Also copy rendered PNGs into this directory
  --samples INT                                      EEVEE TAA render samples (default: 24)
"""

import argparse
import json
import math
import os
import shutil
import struct
import sys
import tempfile
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Euler, Matrix, Vector

# ---------------------------------------------------------------------------
# Paths & Asset Manifest
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
ASSETS_ROOT = PROJECT_ROOT / "public" / "assets"
PREVIEWS_DIR = PROJECT_ROOT / "docs" / "previews"

REQUIRED_HERO_ANIMS = [
    "Idle", "Run", "Sprint", "Crouch", "Aim", "Reload", "Glide", "Jump",
    "IdleArmed", "RunArmed", "SprintArmed", "JumpArmed",
]

LEFT_PALM_LOCAL = Vector((0.030, 0.092, 0.006))
RIFLE_FOREGRIP_DIST = 0.290
RIFLE_FOREGRIP_UP = 0.064
RIFLE_GRIP_ALPHA = math.atan2(RIFLE_FOREGRIP_UP, RIFLE_FOREGRIP_DIST)
RIFLE_TARGET_SEP = math.hypot(RIFLE_FOREGRIP_DIST, RIFLE_FOREGRIP_UP)

ASSET_SPECS = {
    "characters": [
        {"file": "characters/hero_gmail.glb", "label": "GMAIL AI", "tri_min": 3000, "tri_max": 7500, "h_min": 1.65, "h_max": 2.02, "max_mb": 1.2},
        {"file": "characters/hero_drive.glb", "label": "DRIVE AI", "tri_min": 3000, "tri_max": 7500, "h_min": 1.65, "h_max": 2.02, "max_mb": 1.2},
        {"file": "characters/hero_calendar.glb", "label": "CALENDAR AI", "tri_min": 3000, "tri_max": 7500, "h_min": 1.65, "h_max": 2.02, "max_mb": 1.2},
        {"file": "characters/hero_chat.glb", "label": "CHAT AI", "tri_min": 3000, "tri_max": 7500, "h_min": 1.65, "h_max": 2.02, "max_mb": 1.2},
        {"file": "characters/hero_slides.glb", "label": "SLIDES AI", "tri_min": 3000, "tri_max": 7500, "h_min": 1.65, "h_max": 2.02, "max_mb": 1.2},
        {"file": "characters/hero_docs.glb", "label": "DOCS AI", "tri_min": 3000, "tri_max": 7500, "h_min": 1.65, "h_max": 2.02, "max_mb": 1.2},
    ],
    "office_props": [
        {"file": "map/prop_desk_pod.glb", "label": "DESK POD (4-SEAT)", "ground": True, "h_min": 0.75, "h_max": 1.85, "fp_min": 2.0, "fp_max": 5.5},
        {"file": "map/prop_conference_pod.glb", "label": "CONFERENCE POD", "ground": True, "h_min": 1.80, "h_max": 3.60, "fp_min": 3.5, "fp_max": 7.5},
        {"file": "map/prop_microkitchen_bar.glb", "label": "MICROKITCHEN BAR", "ground": True, "h_min": 1.40, "h_max": 2.80, "fp_min": 3.0, "fp_max": 7.0},
        {"file": "map/prop_lounge_nook.glb", "label": "LOUNGE NOOK", "ground": True, "h_min": 0.90, "h_max": 3.00, "fp_min": 2.5, "fp_max": 6.0},
        {"file": "map/prop_whiteboard_wall.glb", "label": "WHITEBOARD WALL", "ground": True, "h_min": 1.40, "h_max": 2.60, "fp_min": 1.8, "fp_max": 4.2},
    ],
    "weapons": [
        {"file": "weapons/weapon_vanguard_m4.glb", "label": "VANGUARD M4 (AR)", "tri_min": 900, "tri_max": 2400, "len_min": 0.62, "len_max": 1.05},
        {"file": "weapons/weapon_breaker_12g.glb", "label": "BREAKER 12G (SHOTGUN)", "tri_min": 900, "tri_max": 2400, "len_min": 0.68, "len_max": 1.12},
        {"file": "weapons/weapon_vector_9.glb", "label": "VECTOR-9 (SMG)", "tri_min": 900, "tri_max": 2400, "len_min": 0.38, "len_max": 0.72},
        {"file": "weapons/weapon_longbow_308.glb", "label": "LONGBOW .308 (SNIPER)", "tri_min": 900, "tri_max": 2400, "len_min": 0.95, "len_max": 1.45},
        {"file": "weapons/weapon_nova_gl40.glb", "label": "NOVA GL-40 (LAUNCHER)", "tri_min": 900, "tri_max": 2400, "len_min": 0.58, "len_max": 1.02},
    ],
    "utilities": [
        {"file": "utilities/item_shield_cell.glb", "label": "SHIELD CELL", "tri_min": 400, "tri_max": 1800, "ground": True, "size_min": 0.18, "size_max": 0.75},
        {"file": "utilities/item_shield_jug.glb", "label": "AEGIS SHIELD JUG", "tri_min": 400, "tri_max": 1800, "ground": True, "size_min": 0.25, "size_max": 0.85},
        {"file": "utilities/item_medkit.glb", "label": "FIELD MEDKIT", "tri_min": 400, "tri_max": 1800, "ground": True, "size_min": 0.20, "size_max": 0.80},
        {"file": "utilities/item_mana_elixir.glb", "label": "MANA ELIXIR", "tri_min": 400, "tri_max": 1800, "ground": True, "size_min": 0.18, "size_max": 0.75},
        {"file": "utilities/item_hardlight_cover.glb", "label": "HARD-LIGHT COVER", "tri_min": 400, "tri_max": 1800, "ground": True, "size_min": 0.20, "size_max": 0.90},
        {"file": "utilities/item_impulse_booster.glb", "label": "IMPULSE BOOSTER", "tri_min": 400, "tri_max": 1800, "ground": True, "size_min": 0.20, "size_max": 0.90},
        {"file": "utilities/prop_supply_drop.glb", "label": "SUPPLY DROP", "tri_min": 400, "tri_max": 4500, "ground": True, "size_min": 1.00, "size_max": 6.50},
        {"file": "utilities/prop_glider.glb", "label": "TACTICAL GLIDER", "tri_min": 400, "tri_max": 4500, "ground": False, "size_min": 2.20, "size_max": 4.80},
        {"file": "utilities/prop_loot_chest.glb", "label": "TACTICAL LOOT CHEST", "tri_min": 1200, "tri_max": 2000, "ground": True, "size_min": 0.90, "size_max": 1.30, "require_chest_rig": True},
    ],
    "map": [
        {"file": "map/landmark_stan_trex.glb", "label": "STAN THE T-REX", "ground": True, "h_min": 5.5, "h_max": 11.5, "fp_min": 3.0, "fp_max": 22.0},
        {"file": "map/landmark_b40_partnerplex.glb", "label": "B40 CHARLIES / PARTNER PLEX", "ground": True, "h_min": 5.8, "h_max": 12.0, "fp_min": 55.0, "fp_max": 115.0},
        {"file": "map/landmark_b41.glb", "label": "BUILDING 41", "ground": True, "h_min": 5.8, "h_max": 12.0, "fp_min": 24.0, "fp_max": 52.0},
        {"file": "map/landmark_b42.glb", "label": "BUILDING 42", "ground": True, "h_min": 5.8, "h_max": 12.0, "fp_min": 24.0, "fp_max": 52.0},
        {"file": "map/landmark_b43.glb", "label": "BUILDING 43 (SOLAR)", "ground": True, "h_min": 5.8, "h_max": 12.0, "fp_min": 55.0, "fp_max": 110.0},
        {"file": "map/landmark_skybridge.glb", "label": "CENTRAL GLASS SKYBRIDGE", "ground": False, "h_min": 3.0, "h_max": 11.0, "fp_min": 22.0, "fp_max": 50.0},
        {"file": "map/landmark_volleyball_court.glb", "label": "SAND VOLLEYBALL COURT", "ground": True, "h_min": 1.8, "h_max": 5.0, "fp_min": 14.0, "fp_max": 25.0},
        {"file": "map/landmark_gradient_canopy.glb", "label": "GRADIENT CANOPY", "ground": True, "h_min": 8.5, "h_max": 16.0, "fp_min": 70.0, "fp_max": 120.0},
        {"file": "map/landmark_orb_plaza.glb", "label": "THE ORB PLAZA", "ground": True, "h_min": 3.0, "h_max": 12.0, "fp_min": 12.0, "fp_max": 28.0},
        {"file": "map/prop_umbrella_bistro.glb", "label": "GOOGLE UMBRELLA BISTRO", "ground": True, "h_min": 2.0, "h_max": 4.2, "fp_min": 1.8, "fp_max": 5.5},
        {"file": "map/prop_gbike_rack.glb", "label": "GBIKE RACK (4 BIKES)", "ground": True, "h_min": 0.85, "h_max": 1.8, "fp_min": 1.8, "fp_max": 6.5},
        {"file": "map/prop_oak_tree.glb", "label": "CALIFORNIA LIVE OAK", "ground": True, "h_min": 6.0, "h_max": 13.5, "fp_min": 4.0, "fp_max": 14.0},
        {"file": "map/prop_redwood_tree.glb", "label": "COASTAL REDWOOD", "ground": True, "h_min": 11.0, "h_max": 22.0, "fp_min": 3.0, "fp_max": 12.0},
    ],
    "expanded_landmarks": [
        {"file": "map/landmark_shoreline_amphitheatre.glb", "label": "SHORELINE AMPHITHEATRE", "ground": True, "h_min": 12.0, "h_max": 26.0, "fp_min": 48.0, "fp_max": 86.0},
        {"file": "map/landmark_athletic_field.glb", "label": "ATHLETIC RECREATION FIELD", "ground": True, "h_min": 2.0, "h_max": 18.0, "fp_min": 50.0, "fp_max": 88.0},
        {"file": "map/landmark_google_2000_1950.glb", "label": "GOOGLE 2000 & 1950 COMPLEX", "ground": True, "h_min": 5.5, "h_max": 14.0, "fp_min": 70.0, "fp_max": 115.0},
        {"file": "map/landmark_charleston_campus.glb", "label": "CHARLESTON CAMPUS", "ground": True, "h_min": 5.5, "h_max": 14.0, "fp_min": 85.0, "fp_max": 135.0},
        {"file": "map/landmark_alta_complex.glb", "label": "1098 ALTA / HUFF COMPLEX", "ground": True, "h_min": 5.5, "h_max": 14.0, "fp_min": 58.0, "fp_max": 100.0},
        {"file": "map/landmark_shoreline_east_office.glb", "label": "SHORELINE EAST OFFICE", "ground": True, "h_min": 5.5, "h_max": 14.0, "fp_min": 52.0, "fp_max": 92.0},
    ],
}

# §10.2 Quad assembly placements in Three.js (X, Z) -> Blender (X, -Z, 0)
QUAD_ASSEMBLY_PLACEMENTS = [
    ("map/landmark_b40_partnerplex.glb", (-41.0, -21.0)),
    ("map/landmark_b41.glb", (-112.0, -31.0)),
    ("map/landmark_b42.glb", (-117.0, 23.0)),
    ("map/landmark_b43.glb", (-58.0, 33.0)),
    ("map/landmark_skybridge.glb", (-73.0, 2.0)),
    ("map/landmark_volleyball_court.glb", (-91.0, 4.0)),
    ("map/landmark_stan_trex.glb", (-51.0, 4.0)),
]

# ---------------------------------------------------------------------------
# Crisp 5x7 Pixel Bitmap Font (Zero External Dependencies)
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
    "9": ["01110", "10001", "10001", "01111", "00001", "00010", "01100"],
    " ": ["00000", "00000", "00000", "00000", "00000", "00000", "00000"],
    "-": ["00000", "00000", "00000", "11111", "00000", "00000", "00000"],
    "_": ["00000", "00000", "00000", "00000", "00000", "00000", "11111"],
    ".": ["00000", "00000", "00000", "00000", "00000", "01100", "01100"],
    ",": ["00000", "00000", "00000", "00000", "00110", "00100", "01000"],
    ":": ["00000", "01100", "01100", "00000", "01100", "01100", "00000"],
    "/": ["00001", "00010", "00010", "00100", "01000", "01000", "10000"],
    "(": ["00010", "00100", "01000", "01000", "01000", "00100", "00010"],
    ")": ["01000", "00100", "00010", "00010", "00010", "00100", "01000"],
    "+": ["00000", "00100", "00100", "11111", "00100", "00100", "00000"],
    "=": ["00000", "00000", "11111", "00000", "11111", "00000", "00000"],
    "|": ["00100", "00100", "00100", "00100", "00100", "00100", "00100"],
    "!": ["00100", "00100", "00100", "00100", "00100", "00000", "00100"],
    "[": ["01110", "01000", "01000", "01000", "01000", "01000", "01110"],
    "]": ["01110", "00010", "00010", "00010", "00010", "00010", "01110"],
    "%": ["11001", "11010", "00010", "00100", "01000", "01011", "10011"],
    "&": ["01100", "10010", "10100", "01000", "10101", "10010", "01101"],
}


def draw_text(canvas: np.ndarray, text: str, x: int, y: int, scale: int = 2, color=(1.0, 1.0, 1.0, 1.0)):
    """Draw crisp bitmap text onto top-down RGBA float32 canvas (H, W, 4)."""
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
                    if y0 >= 0 and x0 >= 0 and y0 < h and x0 < w:
                        canvas[y0:y1, x0:x1] = color
        cx += 6 * scale


def fill_rect(canvas: np.ndarray, x0: int, y0: int, x1: int, y1: int, color):
    h, w, _ = canvas.shape
    canvas[max(0, y0):min(h, y1), max(0, x0):min(w, x1)] = color


def load_png_topdown(path: str) -> np.ndarray:
    """Load PNG into top-down RGBA float32 numpy array (H, W, 4)."""
    img = bpy.data.images.load(path, check_existing=False)
    w, h = img.size
    buf = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(buf)
    bpy.data.images.remove(img)
    arr = buf.reshape((h, w, 4))[::-1].copy()
    return arr


def save_png_topdown(canvas: np.ndarray, out_path: Path, mirror_dir: Path | None = None):
    """Save top-down RGBA float32 numpy array (H, W, 4) to lossless PNG."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    h, w, _ = canvas.shape
    img = bpy.data.images.new(f"Sheet_{out_path.stem}", width=w, height=h, alpha=True)
    flipped = np.ascontiguousarray(np.clip(canvas[::-1], 0.0, 1.0), dtype=np.float32)
    img.pixels.foreach_set(flipped.ravel())
    img.filepath_raw = str(out_path)
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)
    if mirror_dir is not None:
        mirror_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out_path, mirror_dir / out_path.name)


# ---------------------------------------------------------------------------
# GLB Raw Header Inspection & Blender Scene Evaluation
# ---------------------------------------------------------------------------

def parse_glb_json(glb_path: Path) -> dict:
    """Parse glTF 2.0 JSON chunk directly from a .glb binary."""
    with open(glb_path, "rb") as f:
        header = f.read(12)
        if len(header) < 12:
            raise ValueError("File smaller than 12-byte GLB header")
        magic, version, total_len = struct.unpack("<III", header)
        if magic != 0x46546C67:  # 'glTF'
            raise ValueError(f"Invalid GLB magic: {hex(magic)}")
        if version != 2:
            raise ValueError(f"Unsupported glTF version: {version}")
        chunk_hdr = f.read(8)
        if len(chunk_hdr) < 8:
            raise ValueError("Missing JSON chunk header")
        chunk_len, chunk_type = struct.unpack("<II", chunk_hdr)
        if chunk_type != 0x4E4F534A:  # 'JSON'
            raise ValueError(f"First GLB chunk is not JSON: {hex(chunk_type)}")
        raw = f.read(chunk_len)
        return json.loads(raw.decode("utf-8"))


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def import_glb(glb_path: Path) -> list:
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(glb_path))
    # Exclude Blender glTF importer's internal bone-shape helper meshes in 'glTF_not_exported'
    imported = []
    for o in bpy.data.objects:
        if o in before:
            continue
        colls = {c.name for c in o.users_collection}
        if "glTF_not_exported" in colls:
            continue
        imported.append(o)
    return imported


def compute_scene_mesh_stats(objects=None) -> dict:
    """Evaluate all meshes via depsgraph in world space -> tri count & exact world bbox."""
    if objects is None:
        objects = list(bpy.data.objects)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    total_tris = 0
    total_verts = 0
    mesh_count = 0
    min_pt = np.array([np.inf, np.inf, np.inf], dtype=np.float64)
    max_pt = np.array([-np.inf, -np.inf, -np.inf], dtype=np.float64)
    has_nan = False

    for obj in objects:
        if obj.type != "MESH":
            continue
        mesh_count += 1
        eval_obj = obj.evaluated_get(depsgraph)
        eval_mesh = eval_obj.to_mesh()
        try:
            eval_mesh.calc_loop_triangles()
            total_tris += len(eval_mesh.loop_triangles)
            n_verts = len(eval_mesh.vertices)
            total_verts += n_verts
            if n_verts > 0:
                co = np.empty(n_verts * 3, dtype=np.float64)
                eval_mesh.vertices.foreach_get("co", co)
                co = co.reshape((n_verts, 3))
                mat = np.array(eval_obj.matrix_world, dtype=np.float64)
                world_co = co @ mat[:3, :3].T + mat[:3, 3]
                if not np.all(np.isfinite(world_co)):
                    has_nan = True
                else:
                    min_pt = np.minimum(min_pt, world_co.min(axis=0))
                    max_pt = np.maximum(max_pt, world_co.max(axis=0))
        finally:
            eval_obj.to_mesh_clear()

    if not np.all(np.isfinite(min_pt)):
        min_pt = np.zeros(3)
        max_pt = np.zeros(3)

    dims = max_pt - min_pt
    center = 0.5 * (min_pt + max_pt)
    return {
        "mesh_count": mesh_count,
        "tris": int(total_tris),
        "verts": int(total_verts),
        "has_nan": has_nan,
        "bbox_min": [round(float(v), 4) for v in min_pt],
        "bbox_max": [round(float(v), 4) for v in max_pt],
        "dims": [round(float(v), 4) for v in dims],
        "center": [round(float(v), 4) for v in center],
    }


def collect_world_verts(objects) -> np.ndarray:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    chunks = []
    for obj in objects:
        if obj.type != "MESH":
            continue
        eval_obj = obj.evaluated_get(depsgraph)
        eval_mesh = eval_obj.to_mesh()
        try:
            n = len(eval_mesh.vertices)
            if n > 0:
                co = np.empty(n * 3, dtype=np.float64)
                eval_mesh.vertices.foreach_get("co", co)
                co = co.reshape((n, 3))
                mat = np.array(eval_obj.matrix_world, dtype=np.float64)
                chunks.append(co @ mat[:3, :3].T + mat[:3, 3])
        finally:
            eval_obj.to_mesh_clear()
    if not chunks:
        return np.zeros((0, 3), dtype=np.float64)
    return np.vstack(chunks)


def find_action_for_clip(clip_name: str):
    """Find imported Blender action matching a glTF animation name."""
    for act in bpy.data.actions:
        if act.name == clip_name or act.name.startswith(clip_name + "."):
            return act
    low = clip_name.lower()
    for act in bpy.data.actions:
        if low in act.name.lower():
            return act
    return None


def set_armature_action_frame(arm_obj, action, frac: float = 0.5):
    """Assign an action directly to arm_obj (disabling NLA override) and jump to frame fraction."""
    if arm_obj.animation_data is None:
        arm_obj.animation_data_create()
    ad = arm_obj.animation_data
    ad.use_nla = False
    for track in ad.nla_tracks:
        track.mute = True
    ad.action = action
    # Blender 5.x slotted actions: bind first matching slot if needed
    if hasattr(ad, "action_slot") and hasattr(action, "slots") and len(action.slots) > 0:
        for slot in action.slots:
            if slot.target_id_type == "OBJECT":
                try:
                    ad.action_slot = slot
                    break
                except Exception:
                    pass
    f0, f1 = action.frame_range
    target_frame = f0 + (f1 - f0) * frac
    bpy.context.scene.frame_set(int(round(target_frame)))
    bpy.context.view_layer.update()


def reset_armature_rest(arm_obj):
    if arm_obj.animation_data:
        arm_obj.animation_data.action = None
        arm_obj.animation_data.use_nla = False
        for track in arm_obj.animation_data.nla_tracks:
            track.mute = True
    for pb in arm_obj.pose.bones:
        pb.location = (0.0, 0.0, 0.0)
        pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        pb.rotation_euler = (0.0, 0.0, 0.0)
        pb.scale = (1.0, 1.0, 1.0)
    bpy.context.view_layer.update()


# ---------------------------------------------------------------------------
# Comprehensive Automated GLB Validator
# ---------------------------------------------------------------------------

def validate_asset(category: str, spec: dict) -> dict:
    rel = spec["file"]
    glb_path = ASSETS_ROOT / rel
    result = {
        "category": category,
        "file": rel,
        "label": spec["label"],
        "exists": glb_path.exists(),
        "size_bytes": 0,
        "size_kb": 0.0,
        "status": "FAIL",
        "errors": [],
        "warnings": [],
        "stats": {},
    }

    if not glb_path.exists():
        result["errors"].append("File missing")
        return result

    size_bytes = glb_path.stat().st_size
    result["size_bytes"] = size_bytes
    result["size_kb"] = round(size_bytes / 1024.0, 1)
    if size_bytes < 512:
        result["errors"].append(f"File suspiciously small ({size_bytes} B)")
        return result

    try:
        gltf_json = parse_glb_json(glb_path)
    except Exception as exc:
        result["errors"].append(f"GLB JSON parse failed: {exc}")
        return result

    reset_scene()
    try:
        imported = import_glb(glb_path)
    except Exception as exc:
        result["errors"].append(f"Blender glTF import failed: {exc}")
        return result

    stats = compute_scene_mesh_stats(imported)
    gltf_nodes = gltf_json.get("nodes", [])
    gltf_node_names = [n.get("name", "") for n in gltf_nodes]
    gltf_mats = [m.get("name", "") for m in gltf_json.get("materials", [])]
    gltf_anims = [a.get("name", "") for a in gltf_json.get("animations", [])]
    gltf_images = len(gltf_json.get("images", []))
    gltf_textures = len(gltf_json.get("textures", []))

    armatures = [o for o in imported if o.type == "ARMATURE"]
    empties = [o for o in imported if o.type == "EMPTY"]
    meshes = [o for o in imported if o.type == "MESH"]
    bone_names = []
    for arm in armatures:
        bone_names.extend([b.name for b in arm.data.bones])

    stats.update({
        "gltf_materials": gltf_mats,
        "gltf_animations": gltf_anims,
        "gltf_images": gltf_images,
        "gltf_textures": gltf_textures,
        "armature_count": len(armatures),
        "bone_count": len(bone_names),
        "empty_names": [e.name for e in empties],
    })
    result["stats"] = stats

    if stats["mesh_count"] == 0 or stats["tris"] == 0:
        result["errors"].append("Zero geometry / triangles loaded")
        return result
    if stats["has_nan"]:
        result["errors"].append("Mesh contains NaN/Inf vertex coordinates")

    min_z = stats["bbox_min"][2]
    max_z = stats["bbox_max"][2]
    dx, dy, dz = stats["dims"]

    # ---------------- Category-specific validation ----------------
    if category == "characters":
        # Grounding & Height
        if abs(min_z) > 0.12:
            result["errors"].append(f"Feet not grounded at Z=0 (min_z={min_z:.3f}m)")
        elif abs(min_z) > 0.04:
            result["warnings"].append(f"Slight grounding offset (min_z={min_z:.3f}m)")

        if dz < spec["h_min"] or dz > spec["h_max"]:
            result["errors"].append(f"Height out of spec: {dz:.3f}m (expected {spec['h_min']}–{spec['h_max']}m, target ~1.82m)")

        # Tri count
        if stats["tris"] < 1500:
            result["errors"].append(f"Triangle count too low / blocky ({stats['tris']} tris; spec {spec['tri_min']}–{spec['tri_max']})")
        elif stats["tris"] < spec["tri_min"] or stats["tris"] > spec["tri_max"]:
            result["warnings"].append(f"Tri count {stats['tris']} outside nominal {spec['tri_min']}–{spec['tri_max']}")

        # Size
        mb = size_bytes / (1024 * 1024)
        if mb > 2.2:
            result["errors"].append(f"Hero GLB too large: {mb:.2f} MB (target <= {spec['max_mb']} MB)")
        elif mb > spec["max_mb"]:
            result["warnings"].append(f"Hero GLB slightly above target: {mb:.2f} MB (target <= {spec['max_mb']} MB)")

        # Multi-material PBR richness (sculpted 3D Workspace Icon AIs use rich PBR materials and/or embedded textures)
        if len(gltf_mats) < 4:
            result["errors"].append(f"Too few PBR materials ({len(gltf_mats)}); expected rich multi-material 3D Workspace Icon AI finish")

        # Armature + Skinning
        if len(armatures) == 0:
            result["errors"].append("Missing Armature skeleton")
        else:
            skinned_meshes = [m for m in meshes if any(mod.type == "ARMATURE" for mod in m.modifiers) and len(m.vertex_groups) > 0]
            stats["skinned_mesh_count"] = len(skinned_meshes)
            if len(skinned_meshes) == 0:
                result["errors"].append("No mesh is skinned to Armature (missing ARMATURE modifier / vertex groups)")

        # WeaponSocket_R, Hand_L, Hand_R, Spine, Chest
        all_names = gltf_node_names + bone_names + [e.name for e in empties]
        has_socket = any("WeaponSocket_R" in n for n in all_names)
        has_hand_l = any(n == "Hand_L" or n.startswith("Hand_L.") for n in all_names)
        has_hand_r = any(n == "Hand_R" or n.startswith("Hand_R.") for n in all_names)
        has_spine = any(n == "Spine" or n.startswith("Spine.") for n in all_names)
        has_chest = any(n == "Chest" or n.startswith("Chest.") for n in all_names)
        stats["has_weapon_socket_r"] = has_socket
        stats["has_hand_l"] = has_hand_l
        stats["has_hand_r"] = has_hand_r
        stats["has_spine"] = has_spine
        stats["has_chest"] = has_chest
        if not has_socket:
            result["errors"].append("Missing WeaponSocket_R bone/empty socket")
        if not has_hand_l:
            result["errors"].append("Missing Hand_L bone/node")
        if not has_hand_r:
            result["errors"].append("Missing Hand_R bone/node")
        if not has_spine:
            result["errors"].append("Missing Spine bone/node")
        if not has_chest:
            result["errors"].append("Missing Chest bone/node")

        # 12 Required Animations + Deformation Audit
        missing_anims = [a for a in REQUIRED_HERO_ANIMS if not any(ga == a or ga.startswith(a + ".") for ga in gltf_anims)]
        if missing_anims:
            result["errors"].append(f"Missing required animations: {missing_anims} (found: {gltf_anims})")

        if armatures and not missing_anims:
            arm = armatures[0]
            reset_armature_rest(arm)
            rest_verts = collect_world_verts(imported)
            anim_report = {}
            for clip in REQUIRED_HERO_ANIMS:
                act = find_action_for_clip(clip)
                if act is None:
                    anim_report[clip] = {"found_in_blender": False}
                    continue
                set_armature_action_frame(arm, act, 0.5)
                posed_verts = collect_world_verts(imported)
                if posed_verts.shape == rest_verts.shape and len(rest_verts) > 0:
                    disp = np.linalg.norm(posed_verts - rest_verts, axis=1)
                    max_disp = float(disp.max())
                    pose_h = float(posed_verts[:, 2].max() - posed_verts[:, 2].min())
                    pose_max_z = float(posed_verts[:, 2].max())
                    anim_report[clip] = {
                        "frames": [round(float(act.frame_range[0]), 1), round(float(act.frame_range[1]), 1)],
                        "max_disp_m": round(max_disp, 4),
                        "height_m": round(pose_h, 3),
                        "max_z_m": round(pose_max_z, 3),
                    }
                    if pose_h > 3.2 or not np.isfinite(pose_h):
                        result["errors"].append(f"Animation '{clip}' explodes mesh (height={pose_h:.2f}m)")
                    elif clip != "Idle" and max_disp < 0.01:
                        result["warnings"].append(f"Animation '{clip}' shows near-zero deformation at mid-frame ({max_disp:.4f}m)")
            stats["anim_deformation"] = anim_report

            # Audit Glide hand-lock stability & span across multiple frames
            glide_act = find_action_for_clip("Glide")
            if glide_act is not None and "Hand_L" in arm.pose.bones and "Hand_R" in arm.pose.bones:
                l_heads, r_heads = [], []
                l_tails, r_tails = [], []
                for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
                    set_armature_action_frame(arm, glide_act, frac)
                    pb_l = arm.pose.bones["Hand_L"]
                    pb_r = arm.pose.bones["Hand_R"]
                    l_heads.append(arm.matrix_world @ pb_l.head)
                    r_heads.append(arm.matrix_world @ pb_r.head)
                    l_tails.append(arm.matrix_world @ pb_l.tail)
                    r_tails.append(arm.matrix_world @ pb_r.tail)
                l0, r0 = l_heads[0], r_heads[0]
                drift_l = max((p - l0).length for p in l_heads)
                drift_r = max((p - r0).length for p in r_heads)
                half_span = 0.5 * (r0.x - l0.x)
                mid_h = 0.5 * (l0 + r0)
                mid_t = 0.5 * (l_tails[0] + r_tails[0])
                stats["glide_hands"] = {
                    "hand_l_blender": [round(float(v), 4) for v in l0],
                    "hand_r_blender": [round(float(v), 4) for v in r0],
                    "midpoint_blender": [round(float(v), 4) for v in mid_h],
                    "midpoint_threejs": [round(float(mid_h.x), 4), round(float(mid_h.z), 4), round(float(-mid_h.y), 4)],
                    "palm_tail_mid_blender": [round(float(v), 4) for v in mid_t],
                    "half_span_m": round(float(half_span), 4),
                    "max_drift_m": round(float(max(drift_l, drift_r)), 5),
                }
                if max(drift_l, drift_r) > 0.015:
                    result["warnings"].append(f"Glide hands drift {max(drift_l, drift_r)*1000:.1f}mm across cycle")
                if abs(half_span - 0.235) > 0.03:
                    result["warnings"].append(f"Glide hand half-span {half_span:.3f}m differs from glider grip 0.235m")

            # Audit Two-Handed Rifle Grip Separation across armed clips
            sock_objs = [o for o in imported if o.name == "WeaponSocket_R" or o.name.startswith("WeaponSocket_R.")]
            if sock_objs and "Hand_L" in arm.pose.bones:
                sock_obj = sock_objs[0]
                twohand_audit = {}
                for aclip in ("IdleArmed", "RunArmed", "SprintArmed", "Aim", "Crouch", "JumpArmed"):
                    act = find_action_for_clip(aclip)
                    if act is None:
                        continue
                    seps = []
                    aim_dots = []
                    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
                        set_armature_action_frame(arm, act, frac)
                        grip_pos = sock_obj.matrix_world.translation.copy()
                        m_l = arm.matrix_world @ arm.pose.bones["Hand_L"].matrix
                        foregrip_pos = m_l @ LEFT_PALM_LOCAL
                        g_vec = foregrip_pos - grip_pos
                        seps.append(g_vec.length)
                        if aclip == "Aim" and g_vec.length > 1e-5:
                            g_hat = g_vec.normalized()
                            r_hat = g_hat.cross(Vector((0.0, 0.0, 1.0))).normalized()
                            g_up = r_hat.cross(g_hat).normalized()
                            b_hat = (g_hat * math.cos(RIFLE_GRIP_ALPHA) - g_up * math.sin(RIFLE_GRIP_ALPHA)).normalized()
                            aim_dots.append(float(b_hat.dot(Vector((0.0, 1.0, 0.0)))))
                    max_sep_err_mm = max(abs(s - RIFLE_TARGET_SEP) for s in seps) * 1000.0
                    entry = {
                        "sep_min_m": round(float(min(seps)), 4),
                        "sep_max_m": round(float(max(seps)), 4),
                        "max_err_mm": round(float(max_sep_err_mm), 2),
                    }
                    if aim_dots:
                        min_dot = min(aim_dots)
                        entry["aim_max_angle_deg"] = round(math.degrees(math.acos(max(-1.0, min(1.0, min_dot)))), 2)
                        if entry["aim_max_angle_deg"] > 4.0:
                            result["warnings"].append(f"Aim barrel deviates {entry['aim_max_angle_deg']:.1f} deg from +Y forward")
                    twohand_audit[aclip] = entry
                    if max_sep_err_mm > 12.0:
                        result["warnings"].append(f"{aclip} grip separation error {max_sep_err_mm:.1f}mm (target {RIFLE_TARGET_SEP:.4f}m)")
                stats["twohand_grip"] = twohand_audit

            # Verify Crouch actually lowers character vs Idle
            if "Crouch" in anim_report and "Idle" in anim_report:
                c_z = anim_report["Crouch"].get("max_z_m", 99)
                i_z = anim_report["Idle"].get("max_z_m", 0)
                if c_z > i_z - 0.15:
                    result["warnings"].append(f"Crouch max_z ({c_z:.2f}m) not noticeably lower than Idle ({i_z:.2f}m)")

    elif category == "weapons":
        # Tri count
        if stats["tris"] < 450:
            result["errors"].append(f"Weapon tri count too low / blocky ({stats['tris']} tris; spec 900–2400)")
        elif stats["tris"] < spec["tri_min"] or stats["tris"] > spec["tri_max"]:
            result["warnings"].append(f"Weapon tri count {stats['tris']} outside nominal {spec['tri_min']}–{spec['tri_max']}")

        # Length along +Y (or max horizontal axis check)
        if dy < spec["len_min"] or dy > spec["len_max"]:
            max_axis = max(dx, dy)
            if spec["len_min"] <= max_axis <= spec["len_max"] and dx > dy * 1.4:
                result["errors"].append(f"Weapon barrel oriented along X ({dx:.2f}m) instead of +Y ({dy:.2f}m)")
            else:
                result["errors"].append(f"Weapon length Y={dy:.3f}m out of spec ({spec['len_min']}–{spec['len_max']}m)")

        # RarityAccent material (must exist AND be assigned to a mesh slot)
        has_rarity_mat = any(m == "RarityAccent" or m.startswith("RarityAccent.") for m in gltf_mats)
        assigned_rarity = False
        for m in meshes:
            for slot in m.material_slots:
                if slot.material and (slot.material.name == "RarityAccent" or slot.material.name.startswith("RarityAccent.")):
                    assigned_rarity = True
        stats["has_rarity_accent"] = has_rarity_mat and assigned_rarity
        if not has_rarity_mat:
            result["errors"].append("Missing required 'RarityAccent' material in GLB")
        elif not assigned_rarity:
            result["errors"].append("'RarityAccent' material exists but is not assigned to any mesh")

        # MuzzlePoint empty positioned near barrel front (+Y)
        muzzle_objs = [o for o in imported if o.name == "MuzzlePoint" or o.name.startswith("MuzzlePoint.")]
        if not muzzle_objs:
            result["errors"].append("Missing required 'MuzzlePoint' Empty object")
            stats["muzzle_point"] = None
        else:
            mp = muzzle_objs[0].matrix_world.translation
            stats["muzzle_point"] = [round(float(mp.x), 4), round(float(mp.y), 4), round(float(mp.z), 4)]
            max_y = stats["bbox_max"][1]
            min_y = stats["bbox_min"][1]
            if mp.y < max_y - 0.18:
                result["errors"].append(f"MuzzlePoint.y ({mp.y:.3f}m) not at front +Y barrel tip (bbox_max_y={max_y:.3f}m, bbox_min_y={min_y:.3f}m)")

    elif category == "utilities":
        if stats["tris"] < 200:
            result["errors"].append(f"Utility tri count too low ({stats['tris']} tris)")
        elif stats["tris"] < spec["tri_min"] or stats["tris"] > spec["tri_max"]:
            result["warnings"].append(f"Utility tri count {stats['tris']} outside nominal {spec['tri_min']}–{spec['tri_max']}")

        max_dim = max(dx, dy, dz)
        if max_dim < spec["size_min"] or max_dim > spec["size_max"]:
            result["errors"].append(f"Max dimension {max_dim:.3f}m out of expected range ({spec['size_min']}–{spec['size_max']}m)")

        if spec["ground"]:
            if abs(min_z) > 0.15:
                result["errors"].append(f"Not grounded at Z=0 (min_z={min_z:.3f}m)")
            elif abs(min_z) > 0.04:
                result["warnings"].append(f"Slight grounding offset (min_z={min_z:.3f}m)")

        if len(gltf_mats) < 2:
            result["warnings"].append(f"Only {len(gltf_mats)} material(s); expected rich multi-material PBR contrast")

        if spec.get("require_chest_rig"):
            has_rarity_mat = any(m == "RarityAccent" or m.startswith("RarityAccent.") for m in gltf_mats)
            assigned_rarity = any(
                slot.material and (slot.material.name == "RarityAccent" or slot.material.name.startswith("RarityAccent."))
                for m in meshes
                for slot in m.material_slots
            )
            stats["has_rarity_accent"] = has_rarity_mat and assigned_rarity
            if not has_rarity_mat or not assigned_rarity:
                result["errors"].append("Loot chest missing assigned 'RarityAccent' material slot")

            lid_objs = [o for o in imported if o.name == "ChestLid" or o.name.startswith("ChestLid.")]
            base_objs = [o for o in imported if o.name == "ChestBase" or o.name.startswith("ChestBase.")]
            if not base_objs:
                result["errors"].append("Loot chest missing 'ChestBase' parent node")
            if not lid_objs:
                result["errors"].append("Loot chest missing 'ChestLid' hinged lid node")
            else:
                lp = lid_objs[0].matrix_world.translation
                stats["chest_lid_pivot_blender"] = [round(float(lp.x), 4), round(float(lp.y), 4), round(float(lp.z), 4)]
                stats["chest_lid_pivot_threejs"] = [round(float(lp.x), 4), round(float(lp.z), 4), round(float(-lp.y), 4)]
                if abs(lp.x) > 0.01 or abs(lp.y - (-0.31)) > 0.02 or abs(lp.z - 0.42) > 0.02:
                    result["errors"].append(
                        f"ChestLid hinge pivot {stats['chest_lid_pivot_blender']} differs from expected (0, -0.31, 0.42)"
                    )

    elif category == "office_props":
        if stats["tris"] < 100:
            result["errors"].append(f"Office prop tri count too low ({stats['tris']} tris)")
        if spec.get("ground", True):
            if abs(min_z) > 0.15:
                result["errors"].append(f"Office prop not grounded at Z=0 (min_z={min_z:.3f}m)")
            elif abs(min_z) > 0.04:
                result["warnings"].append(f"Slight grounding offset (min_z={min_z:.3f}m)")
        fp_max = max(dx, dy)
        if dz < spec["h_min"] or dz > spec["h_max"]:
            result["warnings"].append(f"Height {dz:.2f}m outside target {spec['h_min']}–{spec['h_max']}m")
        if fp_max < spec["fp_min"] or fp_max > spec["fp_max"]:
            result["warnings"].append(f"Footprint max span {fp_max:.2f}m outside target {spec['fp_min']}–{spec['fp_max']}m")
        if result["size_kb"] > 600.0:
            result["warnings"].append(f"Office prop GLB heavy ({result['size_kb']:.1f} KB; target ~80–250 KB)")
        if len(gltf_mats) < 2:
            result["warnings"].append(f"Only {len(gltf_mats)} material(s); expected rich PBR office contrast")

    elif category == "expanded_landmarks":
        if stats["tris"] < 250:
            result["errors"].append(f"Expanded landmark tri count too low ({stats['tris']} tris)")

        if spec.get("ground", True):
            if abs(min_z) > 0.08:
                result["errors"].append(f"Expanded landmark not grounded at Z=0 (min_z={min_z:.4f}m)")
            elif abs(min_z) > 0.015:
                result["warnings"].append(f"Slight grounding offset (min_z={min_z:.4f}m)")

        fp_max = max(dx, dy)
        if dz < spec["h_min"] or dz > spec["h_max"]:
            result["warnings"].append(f"Height {dz:.2f}m outside target {spec['h_min']}–{spec['h_max']}m")
        if fp_max < spec["fp_min"] or fp_max > spec["fp_max"]:
            result["warnings"].append(f"Footprint max span {fp_max:.2f}m outside target {spec['fp_min']}–{spec['fp_max']}m")

        if len(gltf_mats) < 3:
            result["errors"].append(f"Too few PBR materials ({len(gltf_mats)}); expected >= 3 architectural materials")

        missing_mat_meshes = [m.name for m in meshes if len(m.material_slots) == 0 or any(s.material is None for s in m.material_slots)]
        if missing_mat_meshes:
            result["errors"].append(f"Meshes with missing/broken materials: {missing_mat_meshes[:5]}")

        if result["size_kb"] > 800.0:
            result["warnings"].append(f"Expanded landmark GLB heavy ({result['size_kb']:.1f} KB; target ~300–550 KB)")

    elif category == "map":
        if stats["tris"] < 150:
            result["errors"].append(f"Map asset tri count too low ({stats['tris']} tris)")

        if spec["ground"]:
            if abs(min_z) > 0.35:
                result["errors"].append(f"Landmark/prop not grounded at Z=0 (min_z={min_z:.3f}m)")
            elif abs(min_z) > 0.12:
                result["warnings"].append(f"Slight grounding offset (min_z={min_z:.3f}m)")
        else:
            # Skybridge: verify elevated deck / open walkthrough clearance
            if max_z < 4.5:
                result["errors"].append(f"Skybridge too low (max_z={max_z:.2f}m; deck should be at +4.2m)")

        fp_max = max(dx, dy)
        if dz < spec["h_min"] or dz > spec["h_max"]:
            result["warnings"].append(f"Height {dz:.2f}m outside target {spec['h_min']}–{spec['h_max']}m")
        if fp_max < spec["fp_min"] or fp_max > spec["fp_max"]:
            result["warnings"].append(f"Footprint max span {fp_max:.2f}m outside target {spec['fp_min']}–{spec['fp_max']}m")

    if not result["errors"]:
        result["status"] = "WARN" if result["warnings"] else "PASS"
    return result


# ---------------------------------------------------------------------------
# Headless BLENDER_EEVEE Studio Lighting & Framing Engine
# ---------------------------------------------------------------------------

def configure_eevee(samples: int = 24, res_x: int = 640, res_y: int = 640):
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = samples
    scene.render.resolution_x = res_x
    scene.render.resolution_y = res_y
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = False
    # Safe color management setup (AgX if available)
    try:
        scene.view_settings.view_transform = "AgX"
    except Exception:
        pass
    try:
        scene.view_settings.look = "AgX - Medium High Contrast"
    except Exception:
        try:
            scene.view_settings.look = "None"
        except Exception:
            pass
    scene.view_settings.exposure = 0.05


def setup_world(outdoor: bool = False):
    scene = bpy.context.scene
    world = scene.world
    if world is None:
        world = bpy.data.worlds.new("QAWorld")
        scene.world = world
    if world.node_tree is None:
        world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()

    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg = nt.nodes.new("ShaderNodeBackground")

    if outdoor:
        # Bright crisp California golden-hour sky gradient
        texcoord = nt.nodes.new("ShaderNodeTexCoord")
        sep = nt.nodes.new("ShaderNodeSeparateXYZ")
        ramp = nt.nodes.new("ShaderNodeValToRGB")
        ramp.color_ramp.elements[0].position = 0.0
        ramp.color_ramp.elements[0].color = (0.78, 0.84, 0.90, 1.0)
        ramp.color_ramp.elements[1].position = 0.55
        ramp.color_ramp.elements[1].color = (0.28, 0.52, 0.85, 1.0)
        nt.links.new(texcoord.outputs["Generated"], sep.inputs["Vector"])
        nt.links.new(sep.outputs["Z"], ramp.inputs["Fac"])
        nt.links.new(ramp.outputs["Color"], bg.inputs["Color"])
        bg.inputs["Strength"].default_value = 0.90
    else:
        # Clean neutral mid-slate studio cyclorama (high contrast for BOTH dark guns & white tees)
        bg.inputs["Color"].default_value = (0.15, 0.18, 0.23, 1.0)
        bg.inputs["Strength"].default_value = 0.65

    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])


def create_ground_plane(z_level: float, radius: float, outdoor: bool = False):
    bpy.ops.mesh.primitive_circle_add(vertices=64, radius=radius, fill_type="NGON", location=(0.0, 0.0, z_level - 0.002))
    floor = bpy.context.active_object
    floor.name = "QA_StudioFloor"
    mat = bpy.data.materials.new("QA_FloorMat")
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    if outdoor:
        bsdf.inputs["Base Color"].default_value = (0.20, 0.29, 0.19, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.88
    else:
        bsdf.inputs["Base Color"].default_value = (0.11, 0.13, 0.17, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.72
    floor.data.materials.append(mat)
    return floor


def look_at(obj, target: Vector):
    direction = target - obj.location
    rot_quat = direction.to_track_quat("-Z", "Y")
    obj.rotation_euler = rot_quat.to_euler()


def build_studio_rig(
    target_center: Vector,
    bbox_min: Vector,
    bbox_max: Vector,
    azim_deg: float,
    elev_deg: float,
    fov_deg: float = 35.0,
    fill_ratio: float = 0.78,
    outdoor: bool = False,
    add_floor: bool = True,
    floor_z: float = 0.0,
):
    """Build camera + scale-invariant 3-point lighting framed tightly on bbox."""
    # Remove previous QA rig objects
    for obj in list(bpy.data.objects):
        if obj.name.startswith("QA_"):
            bpy.data.objects.remove(obj, do_unlink=True)

    dims = bbox_max - bbox_min
    radius = max(0.15, 0.5 * dims.length)

    if add_floor:
        create_ground_plane(floor_z, max(radius * 9.0, 4.0), outdoor=outdoor)

    # Camera unit direction from target -> camera (azim=0 means +Y front!)
    az = math.radians(azim_deg)
    el = math.radians(elev_deg)
    cam_dir = Vector((
        math.sin(az) * math.cos(el),
        math.cos(az) * math.cos(el),
        math.sin(el),
    )).normalized()

    # Exact projected bbox sizing for tight, unclipped framing
    world_up = Vector((0.0, 0.0, 1.0))
    right = world_up.cross(cam_dir)
    if right.length < 1e-4:
        right = Vector((1.0, 0.0, 0.0))
    else:
        right.normalize()
    up = cam_dir.cross(right).normalized()

    corners = [
        Vector((x, y, z)) - target_center
        for x in (bbox_min.x, bbox_max.x)
        for y in (bbox_min.y, bbox_max.y)
        for z in (bbox_min.z, bbox_max.z)
    ]
    half_w = max(abs(c.dot(right)) for c in corners)
    half_h = max(abs(c.dot(up)) for c in corners)
    half_d = max(abs(c.dot(cam_dir)) for c in corners)

    scene = bpy.context.scene
    aspect = scene.render.resolution_x / max(1, scene.render.resolution_y)
    # Camera sensor_fit = VERTICAL -> vertical FOV = fov_deg
    vfov = math.radians(fov_deg)
    hfov = 2.0 * math.atan(math.tan(vfov * 0.5) * aspect)

    dist_v = (half_h / max(0.01, fill_ratio)) / math.tan(vfov * 0.5)
    dist_h = (half_w / max(0.01, fill_ratio)) / math.tan(hfov * 0.5)
    cam_dist = max(dist_v, dist_h) + half_d * 0.85

    cam_data = bpy.data.cameras.new("QA_CamData")
    cam_data.sensor_fit = "VERTICAL"
    cam_data.lens_unit = "FOV"
    cam_data.angle = vfov
    cam_data.clip_start = max(0.01, cam_dist * 0.01)
    cam_data.clip_end = max(500.0, cam_dist * 12.0)
    cam_obj = bpy.data.objects.new("QA_Camera", cam_data)
    bpy.context.scene.collection.objects.link(cam_obj)
    cam_obj.location = target_center + cam_dir * cam_dist
    look_at(cam_obj, target_center)
    scene.camera = cam_obj

    # 3-Point Scale-Invariant Lighting (oriented relative to camera so both front & back are crisp!)
    if outdoor or radius > 8.0:
        # Golden-hour California directional Sun + soft cool sky fill + warm rim sun
        def add_sun(name, az_off, el_d, energy, color, angle_deg=2.5):
            ld = bpy.data.lights.new(name, type="SUN")
            ld.energy = energy
            ld.color = color
            ld.angle = math.radians(angle_deg)
            lo = bpy.data.objects.new(name, ld)
            scene.collection.objects.link(lo)
            a = math.radians(azim_deg + az_off)
            e = math.radians(el_d)
            lo.location = target_center + Vector((math.sin(a) * math.cos(e), math.cos(a) * math.cos(e), math.sin(e))) * (radius * 2.5)
            look_at(lo, target_center)

        add_sun("QA_KeySun", 38.0, 36.0, 3.6, (1.0, 0.94, 0.84), 2.0)
        add_sun("QA_FillSun", -60.0, 28.0, 1.0, (0.78, 0.88, 1.0), 12.0)
        add_sun("QA_RimSun", 155.0, 26.0, 0.85, (1.0, 0.95, 0.86), 6.0)
    else:
        def add_area(name, az_off, el_d, dist_mult, size_mult, energy_k, color):
            ld = bpy.data.lights.new(name, type="AREA")
            ld.shape = "RECTANGLE"
            ld.size = radius * size_mult
            ld.size_y = radius * size_mult * 0.85
            d = radius * dist_mult
            # Flux scales with d^2 so brightness is invariant from 0.2m to 10m objects!
            ld.energy = energy_k * (d * d)
            ld.color = color
            lo = bpy.data.objects.new(name, ld)
            scene.collection.objects.link(lo)
            a = math.radians(azim_deg + az_off)
            e = math.radians(el_d)
            lo.location = target_center + Vector((math.sin(a) * math.cos(e), math.cos(a) * math.cos(e), math.sin(e))) * d
            look_at(lo, target_center)

        add_area("QA_KeyLight", 36.0, 34.0, 3.0, 1.8, 3.8, (1.0, 0.97, 0.92))
        add_area("QA_FillLight", -52.0, 20.0, 3.2, 2.2, 2.0, (0.85, 0.92, 1.0))
        add_area("QA_RimLight", 155.0, 30.0, 2.8, 1.6, 2.8, (1.0, 0.98, 0.95))
        # Subtle frontal eye/logo lift light so chest/back emblems read crisp
        add_area("QA_FrontLift", -8.0, 8.0, 3.5, 1.5, 0.9, (0.98, 0.98, 1.0))


def render_view_to_array(tmp_path: str) -> np.ndarray:
    bpy.context.scene.render.filepath = tmp_path
    bpy.ops.render.render(write_still=True)
    return load_png_topdown(tmp_path)


# ---------------------------------------------------------------------------
# Category Contact-Sheet Renderers
# ---------------------------------------------------------------------------

def render_characters_sheets(results_by_file: dict, samples: int, mirror_dir: Path | None, tmp_dir: Path) -> list[str]:
    outputs = []
    specs = ASSET_SPECS["characters"]
    existing = [s for s in specs if (ASSETS_ROOT / s["file"]).exists()]
    if not existing:
        return outputs

    # Sheet 1: 3x2 Hero Lineup — each hero gets BOTH Front (+Y) & Back (-Y) 3/4 views
    tile_w, tile_h = 340, 520
    pair_w = tile_w * 2 + 8
    header_h = 54
    cell_hdr = 42
    pad = 14
    cols, rows = 3, 2
    sheet_w = pad + cols * (pair_w + pad)
    sheet_h = header_h + pad + rows * (tile_h + cell_hdr + pad)
    lineup = np.full((sheet_h, sheet_w, 4), (0.06, 0.08, 0.11, 1.0), dtype=np.float32)
    fill_rect(lineup, 0, 0, sheet_w, header_h, (0.09, 0.12, 0.18, 1.0))
    draw_text(lineup, "WORKSPACE ROYALE QA - 6 WORKSPACE ICON AIs (FRONT +Y / BACK -Y)", 18, 18, scale=3, color=(0.95, 0.97, 1.0, 1.0))

    # Sheet 2: 3x2 Sculpted 3D Icon Chassis Front (Visor + Emblem) & Back (3D Relief) Close-ups
    cu_w, cu_h = 340, 380
    cu_pair_w = cu_w * 2 + 6
    cu_sheet_w = pad + cols * (cu_pair_w + pad)
    cu_sheet_h = header_h + pad + rows * (cu_h + cell_hdr + pad)
    closeups = np.full((cu_sheet_h, cu_sheet_w, 4), (0.06, 0.08, 0.11, 1.0), dtype=np.float32)
    fill_rect(closeups, 0, 0, cu_sheet_w, header_h, (0.09, 0.12, 0.18, 1.0))
    draw_text(closeups, "WORKSPACE ROYALE QA - 3D ICON CHASSIS, AI VISOR & EMBLEM CLOSE-UPS", 18, 18, scale=3, color=(0.95, 0.97, 1.0, 1.0))

    first_hero_for_anim = None

    for idx, spec in enumerate(specs):
        glb = ASSETS_ROOT / spec["file"]
        if not glb.exists():
            continue
        if first_hero_for_anim is None:
            first_hero_for_anim = spec

        reset_scene()
        imported = import_glb(glb)
        armatures = [o for o in imported if o.type == "ARMATURE"]
        if armatures:
            idle_act = find_action_for_clip("Idle")
            if idle_act is not None:
                set_armature_action_frame(armatures[0], idle_act, 0.0)
            else:
                reset_armature_rest(armatures[0])

        stats = compute_scene_mesh_stats(imported)
        bmin = Vector(stats["bbox_min"])
        bmax = Vector(stats["bbox_max"])
        center = Vector(stats["center"])

        setup_world(outdoor=False)

        # Front 3/4 (+Y) & Back 3/4 (-Y)
        configure_eevee(samples=samples, res_x=tile_w, res_y=tile_h)
        build_studio_rig(center, bmin, bmax, azim_deg=20.0, elev_deg=7.0, fov_deg=34.0, fill_ratio=0.84, add_floor=True, floor_z=0.0)
        front_img = render_view_to_array(str(tmp_dir / f"hero_{idx}_f.png"))

        build_studio_rig(center, bmin, bmax, azim_deg=180.0 + 20.0, elev_deg=7.0, fov_deg=34.0, fill_ratio=0.84, add_floor=True, floor_z=0.0)
        back_img = render_view_to_array(str(tmp_dir / f"hero_{idx}_b.png"))

        # 3D Icon Chassis close-ups: Front (visor + sculpted emblem) & Back (3D icon relief)
        configure_eevee(samples=samples, res_x=cu_w, res_y=cu_h)
        h_total = max(0.5, bmax.z - bmin.z)
        cu_min = Vector((bmin.x * 0.92, bmin.y, bmin.z + h_total * 0.43))
        cu_max = Vector((bmax.x * 0.92, bmax.y, bmax.z + 0.03))
        cu_center = 0.5 * (cu_min + cu_max)
        build_studio_rig(cu_center, cu_min, cu_max, azim_deg=14.0, elev_deg=5.0, fov_deg=32.0, fill_ratio=0.86, add_floor=False)
        cu_front = render_view_to_array(str(tmp_dir / f"hero_{idx}_cu_f.png"))
        build_studio_rig(cu_center, cu_min, cu_max, azim_deg=180.0 + 14.0, elev_deg=5.0, fov_deg=32.0, fill_ratio=0.86, add_floor=False)
        cu_back = render_view_to_array(str(tmp_dir / f"hero_{idx}_cu_b.png"))

        # Place on Lineup Sheet
        c, r = idx % cols, idx // cols
        x0 = pad + c * (pair_w + pad)
        y0 = header_h + pad + r * (tile_h + cell_hdr + pad)
        res = results_by_file.get(spec["file"], {})
        status = res.get("status", "?")
        badge_col = (0.12, 0.55, 0.28, 1.0) if status == "PASS" else ((0.72, 0.52, 0.08, 1.0) if status == "WARN" else (0.72, 0.16, 0.16, 1.0))

        fill_rect(lineup, x0, y0, x0 + pair_w, y0 + cell_hdr, (0.12, 0.15, 0.22, 1.0))
        fill_rect(lineup, x0 + pair_w - 86, y0 + 8, x0 + pair_w - 8, y0 + cell_hdr - 8, badge_col)
        draw_text(lineup, spec["label"], x0 + 10, y0 + 7, scale=2, color=(0.98, 0.99, 1.0, 1.0))
        sub = f"{stats['tris']} TRIS | {stats['dims'][2]:.2f}M | {res.get('size_kb', 0):.0f}KB"
        draw_text(lineup, sub, x0 + 10, y0 + 25, scale=1, color=(0.72, 0.80, 0.92, 1.0))
        draw_text(lineup, status, x0 + pair_w - 72, y0 + 14, scale=2, color=(1.0, 1.0, 1.0, 1.0))

        lineup[y0 + cell_hdr:y0 + cell_hdr + tile_h, x0:x0 + tile_w] = front_img
        lineup[y0 + cell_hdr:y0 + cell_hdr + tile_h, x0 + tile_w + 8:x0 + pair_w] = back_img
        draw_text(lineup, "FRONT +Y", x0 + 8, y0 + cell_hdr + 8, scale=1, color=(0.85, 0.95, 1.0, 1.0))
        draw_text(lineup, "BACK -Y", x0 + tile_w + 16, y0 + cell_hdr + 8, scale=1, color=(0.85, 0.95, 1.0, 1.0))

        # Place on Close-up Sheet (Front + Back 3D Icon Chassis)
        cx0 = pad + c * (cu_pair_w + pad)
        cy0 = header_h + pad + r * (cu_h + cell_hdr + pad)
        fill_rect(closeups, cx0, cy0, cx0 + cu_pair_w, cy0 + cell_hdr, (0.12, 0.15, 0.22, 1.0))
        draw_text(closeups, f"{spec['label']} - 3D ICON FRONT & BACK", cx0 + 10, cy0 + 12, scale=2, color=(0.98, 0.99, 1.0, 1.0))
        closeups[cy0 + cell_hdr:cy0 + cell_hdr + cu_h, cx0:cx0 + cu_w] = cu_front
        closeups[cy0 + cell_hdr:cy0 + cell_hdr + cu_h, cx0 + cu_w + 6:cx0 + cu_pair_w] = cu_back
        draw_text(closeups, "FRONT + VISOR", cx0 + 8, cy0 + cell_hdr + 8, scale=1, color=(0.85, 0.95, 1.0, 1.0))
        draw_text(closeups, "BACK 3D RELIEF", cx0 + cu_w + 14, cy0 + cell_hdr + 8, scale=1, color=(0.85, 0.95, 1.0, 1.0))

    out1 = PREVIEWS_DIR / "characters_lineup_front_back.png"
    out2 = PREVIEWS_DIR / "characters_closeups.png"
    save_png_topdown(lineup, out1, mirror_dir)
    save_png_topdown(closeups, out2, mirror_dir)
    outputs.extend([str(out1), str(out2)])

    # Sheet 3: 8-Animation Pose Deformation Strip (using first hero)
    if first_hero_for_anim is not None:
        glb = ASSETS_ROOT / first_hero_for_anim["file"]
        reset_scene()
        imported = import_glb(glb)
        armatures = [o for o in imported if o.type == "ARMATURE"]
        if armatures:
            arm = armatures[0]
            setup_world(outdoor=False)
            pw, ph = 320, 420
            configure_eevee(samples=max(16, samples // 2), res_x=pw, res_y=ph)
            clips = list(REQUIRED_HERO_ANIMS)
            p_cols = 4
            p_rows = max(1, math.ceil(len(clips) / p_cols))
            p_w = pad + p_cols * (pw + pad)
            p_h = header_h + pad + p_rows * (ph + 34 + pad)
            pose_sheet = np.full((p_h, p_w, 4), (0.06, 0.08, 0.11, 1.0), dtype=np.float32)
            fill_rect(pose_sheet, 0, 0, p_w, header_h, (0.09, 0.12, 0.18, 1.0))
            draw_text(pose_sheet, f"ANIMATION RIG QA - {first_hero_for_anim['label']} (ALL {len(clips)} CLIPS)", 18, 18, scale=2, color=(0.95, 0.97, 1.0, 1.0))

            fixed_min = Vector((-0.65, -0.65, 0.0))
            fixed_max = Vector((0.65, 0.65, 2.02))
            fixed_ctr = Vector((0.0, 0.0, 1.01))

            for i, clip in enumerate(clips):
                act = find_action_for_clip(clip)
                if act is not None:
                    frac = 0.25 if clip in ("Run", "Sprint") else 0.45
                    set_armature_action_frame(arm, act, frac)
                else:
                    reset_armature_rest(arm)
                build_studio_rig(fixed_ctr, fixed_min, fixed_max, azim_deg=42.0, elev_deg=10.0, fov_deg=35.0, fill_ratio=0.82, add_floor=True, floor_z=0.0)
                pimg = render_view_to_array(str(tmp_dir / f"pose_{i}.png"))
                pc, pr = i % p_cols, i // p_cols
                px0 = pad + pc * (pw + pad)
                py0 = header_h + pad + pr * (ph + 34 + pad)
                fill_rect(pose_sheet, px0, py0, px0 + pw, py0 + 34, (0.12, 0.15, 0.22, 1.0))
                draw_text(pose_sheet, clip, px0 + 10, py0 + 10, scale=2, color=(0.98, 0.99, 1.0, 1.0))
                pose_sheet[py0 + 34:py0 + 34 + ph, px0:px0 + pw] = pimg

            out3 = PREVIEWS_DIR / "characters_anim_poses.png"
            save_png_topdown(pose_sheet, out3, mirror_dir)
            outputs.append(str(out3))

    return outputs


def render_weapons_sheets(results_by_file: dict, samples: int, mirror_dir: Path | None, tmp_dir: Path) -> list[str]:
    outputs = []
    specs = ASSET_SPECS["weapons"]
    if not any((ASSETS_ROOT / s["file"]).exists() for s in specs):
        return outputs

    tile_w, tile_h = 680, 340
    header_h = 54
    row_hdr = 36
    pad = 12
    sheet_w = pad + 2 * tile_w + 8 + pad
    sheet_h = header_h + pad + len(specs) * (tile_h + row_hdr + pad)
    sheet = np.full((sheet_h, sheet_w, 4), (0.06, 0.08, 0.11, 1.0), dtype=np.float32)
    fill_rect(sheet, 0, 0, sheet_w, header_h, (0.09, 0.12, 0.18, 1.0))
    draw_text(sheet, "WORKSPACE ROYALE QA - 5 TACTICAL WEAPONS (SIDE 3/4 + FRONT 3/4)", 18, 18, scale=2, color=(0.95, 0.97, 1.0, 1.0))

    for idx, spec in enumerate(specs):
        glb = ASSETS_ROOT / spec["file"]
        if not glb.exists():
            continue

        reset_scene()
        imported = import_glb(glb)
        stats = compute_scene_mesh_stats(imported)
        bmin = Vector(stats["bbox_min"])
        bmax = Vector(stats["bbox_max"])
        center = Vector(stats["center"])

        setup_world(outdoor=False)
        configure_eevee(samples=samples, res_x=tile_w, res_y=tile_h)

        # Right broadside 3/4 (+X, slight +Y)
        build_studio_rig(center, bmin, bmax, azim_deg=72.0, elev_deg=12.0, fov_deg=32.0, fill_ratio=0.80, add_floor=False)
        img_a = render_view_to_array(str(tmp_dir / f"wpn_{idx}_a.png"))

        # Left front 3/4 (-X, +Y) showing muzzle bore & opposite side
        build_studio_rig(center, bmin, bmax, azim_deg=-52.0, elev_deg=18.0, fov_deg=32.0, fill_ratio=0.80, add_floor=False)
        img_b = render_view_to_array(str(tmp_dir / f"wpn_{idx}_b.png"))

        y0 = header_h + pad + idx * (tile_h + row_hdr + pad)
        res = results_by_file.get(spec["file"], {})
        status = res.get("status", "?")
        badge_col = (0.12, 0.55, 0.28, 1.0) if status == "PASS" else ((0.72, 0.52, 0.08, 1.0) if status == "WARN" else (0.72, 0.16, 0.16, 1.0))
        rar_ok = "RARITY:OK" if res.get("stats", {}).get("has_rarity_accent") else "RARITY:MISS"
        muz_ok = "MUZZLE:OK" if res.get("stats", {}).get("muzzle_point") else "MUZZLE:MISS"

        fill_rect(sheet, pad, y0, sheet_w - pad, y0 + row_hdr, (0.12, 0.15, 0.22, 1.0))
        fill_rect(sheet, sheet_w - pad - 88, y0 + 5, sheet_w - pad - 8, y0 + row_hdr - 5, badge_col)
        info = f"{spec['label']}  |  {stats['tris']} TRIS  |  LEN Y={stats['dims'][1]:.2f}M  |  {rar_ok}  |  {muz_ok}  |  {res.get('size_kb', 0):.0f}KB"
        draw_text(sheet, info, pad + 10, y0 + 11, scale=2, color=(0.96, 0.98, 1.0, 1.0))
        draw_text(sheet, status, sheet_w - pad - 74, y0 + 11, scale=2, color=(1.0, 1.0, 1.0, 1.0))

        sheet[y0 + row_hdr:y0 + row_hdr + tile_h, pad:pad + tile_w] = img_a
        sheet[y0 + row_hdr:y0 + row_hdr + tile_h, pad + tile_w + 8:pad + 2 * tile_w + 8] = img_b

    out = PREVIEWS_DIR / "weapons_showcase.png"
    save_png_topdown(sheet, out, mirror_dir)
    outputs.append(str(out))
    return outputs


def render_utilities_sheets(results_by_file: dict, samples: int, mirror_dir: Path | None, tmp_dir: Path) -> list[str]:
    outputs = []
    specs = ASSET_SPECS["utilities"]
    if not any((ASSETS_ROOT / s["file"]).exists() for s in specs):
        return outputs

    tile_w, tile_h = 480, 440
    header_h = 54
    cell_hdr = 42
    pad = 12
    cols = 3 if len(specs) == 9 else 4
    rows = max(1, math.ceil(len(specs) / cols))
    sheet_w = pad + cols * (tile_w + pad)
    sheet_h = header_h + pad + rows * (tile_h + cell_hdr + pad)
    sheet = np.full((sheet_h, sheet_w, 4), (0.06, 0.08, 0.11, 1.0), dtype=np.float32)
    fill_rect(sheet, 0, 0, sheet_w, header_h, (0.09, 0.12, 0.18, 1.0))
    draw_text(sheet, f"WORKSPACE ROYALE QA - {len(specs)} UTILITIES, SUPPLY DROP, GLIDER & LOOT CHEST", 18, 18, scale=2, color=(0.95, 0.97, 1.0, 1.0))

    for idx, spec in enumerate(specs):
        glb = ASSETS_ROOT / spec["file"]
        if not glb.exists():
            continue

        reset_scene()
        imported = import_glb(glb)
        stats = compute_scene_mesh_stats(imported)
        bmin = Vector(stats["bbox_min"])
        bmax = Vector(stats["bbox_max"])
        center = Vector(stats["center"])

        setup_world(outdoor=False)
        configure_eevee(samples=samples, res_x=tile_w, res_y=tile_h)
        is_glider = "glider" in spec["file"]
        is_hardlight = "hardlight" in spec["file"]
        elev = 24.0 if is_glider else 20.0
        azim = -146.0 if is_hardlight else 34.0
        build_studio_rig(center, bmin, bmax, azim_deg=azim, elev_deg=elev, fov_deg=34.0, fill_ratio=0.78, add_floor=spec["ground"], floor_z=0.0)
        img = render_view_to_array(str(tmp_dir / f"util_{idx}.png"))

        c, r = idx % cols, idx // cols
        x0 = pad + c * (tile_w + pad)
        y0 = header_h + pad + r * (tile_h + cell_hdr + pad)
        res = results_by_file.get(spec["file"], {})
        status = res.get("status", "?")
        badge_col = (0.12, 0.55, 0.28, 1.0) if status == "PASS" else ((0.72, 0.52, 0.08, 1.0) if status == "WARN" else (0.72, 0.16, 0.16, 1.0))

        fill_rect(sheet, x0, y0, x0 + tile_w, y0 + cell_hdr, (0.12, 0.15, 0.22, 1.0))
        fill_rect(sheet, x0 + tile_w - 82, y0 + 7, x0 + tile_w - 8, y0 + cell_hdr - 7, badge_col)
        draw_text(sheet, spec["label"], x0 + 10, y0 + 7, scale=2, color=(0.98, 0.99, 1.0, 1.0))
        d = stats["dims"]
        sub = f"{stats['tris']} TRIS | {d[0]:.2f}X{d[1]:.2f}X{d[2]:.2f}M | {res.get('size_kb', 0):.0f}KB"
        draw_text(sheet, sub, x0 + 10, y0 + 26, scale=1, color=(0.72, 0.80, 0.92, 1.0))
        draw_text(sheet, status, x0 + tile_w - 70, y0 + 13, scale=2, color=(1.0, 1.0, 1.0, 1.0))
        sheet[y0 + cell_hdr:y0 + cell_hdr + tile_h, x0:x0 + tile_w] = img

    out1 = PREVIEWS_DIR / "utilities_showcase.png"
    save_png_topdown(sheet, out1, mirror_dir)
    outputs.append(str(out1))

    # Secondary dual-angle showcase for Supply Drop & Glider
    hero_props = [s for s in specs if ("supply_drop" in s["file"] or "glider" in s["file"]) and (ASSETS_ROOT / s["file"]).exists()]
    if hero_props:
        pw, ph = 640, 440
        sw = pad + 2 * pw + 8 + pad
        sh = header_h + pad + len(hero_props) * (ph + 36 + pad)
        dual = np.full((sh, sw, 4), (0.06, 0.08, 0.11, 1.0), dtype=np.float32)
        fill_rect(dual, 0, 0, sw, header_h, (0.09, 0.12, 0.18, 1.0))
        draw_text(dual, "WORKSPACE ROYALE QA - SUPPLY DROP & GLIDER DUAL-ANGLE", 18, 18, scale=2, color=(0.95, 0.97, 1.0, 1.0))

        for i, spec in enumerate(hero_props):
            reset_scene()
            imported = import_glb(ASSETS_ROOT / spec["file"])
            stats = compute_scene_mesh_stats(imported)
            bmin, bmax, ctr = Vector(stats["bbox_min"]), Vector(stats["bbox_max"]), Vector(stats["center"])
            setup_world(outdoor=False)
            configure_eevee(samples=samples, res_x=pw, res_y=ph)
            is_glider = "glider" in spec["file"]

            build_studio_rig(ctr, bmin, bmax, azim_deg=35.0, elev_deg=26.0 if is_glider else 18.0, fov_deg=34.0, fill_ratio=0.80, add_floor=spec["ground"], floor_z=0.0)
            a = render_view_to_array(str(tmp_dir / f"up_{i}_a.png"))
            build_studio_rig(ctr, bmin, bmax, azim_deg=-140.0, elev_deg=-18.0 if is_glider else 32.0, fov_deg=34.0, fill_ratio=0.80, add_floor=spec["ground"], floor_z=0.0)
            b = render_view_to_array(str(tmp_dir / f"up_{i}_b.png"))

            y0 = header_h + pad + i * (ph + 36 + pad)
            fill_rect(dual, pad, y0, sw - pad, y0 + 36, (0.12, 0.15, 0.22, 1.0))
            draw_text(dual, f"{spec['label']} - ANGLE 1 & ANGLE 2 ({stats['tris']} TRIS)", pad + 10, y0 + 11, scale=2, color=(0.98, 0.99, 1.0, 1.0))
            dual[y0 + 36:y0 + 36 + ph, pad:pad + pw] = a
            dual[y0 + 36:y0 + 36 + ph, pad + pw + 8:pad + 2 * pw + 8] = b

        out2 = PREVIEWS_DIR / "utilities_supply_glider.png"
        save_png_topdown(dual, out2, mirror_dir)
        outputs.append(str(out2))

    return outputs


def render_map_sheets(results_by_file: dict, samples: int, mirror_dir: Path | None, tmp_dir: Path) -> list[str]:
    outputs = []
    specs_by_file = {s["file"]: s for s in ASSET_SPECS["map"]}
    header_h = 54
    pad = 12

    # 1. Dedicated Hero Showcase: Stan the T-Rex (3 angles: Front 3/4, Broadside, Skull/Ribs Close-up)
    stan_file = "map/landmark_stan_trex.glb"
    if (ASSETS_ROOT / stan_file).exists():
        reset_scene()
        imported = import_glb(ASSETS_ROOT / stan_file)
        stats = compute_scene_mesh_stats(imported)
        bmin, bmax, ctr = Vector(stats["bbox_min"]), Vector(stats["bbox_max"]), Vector(stats["center"])
        setup_world(outdoor=True)
        pw, ph = 560, 500
        configure_eevee(samples=samples, res_x=pw, res_y=ph)

        build_studio_rig(ctr, bmin, bmax, azim_deg=35.0, elev_deg=14.0, fov_deg=34.0, fill_ratio=0.80, outdoor=True, add_floor=True, floor_z=0.0)
        v1 = render_view_to_array(str(tmp_dir / "stan_1.png"))

        build_studio_rig(ctr, bmin, bmax, azim_deg=88.0, elev_deg=10.0, fov_deg=34.0, fill_ratio=0.82, outdoor=True, add_floor=True, floor_z=0.0)
        v2 = render_view_to_array(str(tmp_dir / "stan_2.png"))

        # Upper torso / skull close-up
        h = max(1.0, bmax.z - bmin.z)
        cmin = Vector((bmin.x, bmin.y, bmin.z + h * 0.45))
        cmax = Vector((bmax.x, bmax.y, bmax.z))
        build_studio_rig(0.5 * (cmin + cmax), cmin, cmax, azim_deg=48.0, elev_deg=8.0, fov_deg=30.0, fill_ratio=0.82, outdoor=True, add_floor=True, floor_z=0.0)
        v3 = render_view_to_array(str(tmp_dir / "stan_3.png"))

        sw = pad + 3 * pw + 16 + pad
        sh = header_h + pad + ph + 34 + pad
        canvas = np.full((sh, sw, 4), (0.06, 0.08, 0.11, 1.0), dtype=np.float32)
        fill_rect(canvas, 0, 0, sw, header_h, (0.09, 0.12, 0.18, 1.0))
        res = results_by_file.get(stan_file, {})
        draw_text(canvas, f"STAN THE T-REX QA - {stats['tris']} TRIS | H={stats['dims'][2]:.1f}M | {res.get('size_kb', 0):.0f}KB | {res.get('status', '?')}", 18, 18, scale=2, color=(0.98, 0.99, 1.0, 1.0))
        for i, (lbl, img) in enumerate([("FRONT 3/4", v1), ("SIDE PROFILE", v2), ("SKULL & RIBS DETAIL", v3)]):
            x0 = pad + i * (pw + 8)
            y0 = header_h + pad
            fill_rect(canvas, x0, y0, x0 + pw, y0 + 34, (0.12, 0.15, 0.22, 1.0))
            draw_text(canvas, lbl, x0 + 10, y0 + 10, scale=2, color=(0.95, 0.98, 1.0, 1.0))
            canvas[y0 + 34:y0 + 34 + ph, x0:x0 + pw] = img

        out = PREVIEWS_DIR / "map_stan_trex.png"
        save_png_topdown(canvas, out, mirror_dir)
        outputs.append(str(out))

    # 2. Googleplex Quad Buildings, Skybridge & Volleyball Court (3x2)
    quad_files = [
        "map/landmark_b40_partnerplex.glb",
        "map/landmark_b41.glb",
        "map/landmark_b42.glb",
        "map/landmark_b43.glb",
        "map/landmark_skybridge.glb",
        "map/landmark_volleyball_court.glb",
    ]
    if any((ASSETS_ROOT / f).exists() for f in quad_files):
        tw, th = 560, 400
        cell_hdr = 42
        cols, rows = 3, 2
        sw = pad + cols * (tw + pad)
        sh = header_h + pad + rows * (th + cell_hdr + pad)
        canvas = np.full((sh, sw, 4), (0.06, 0.08, 0.11, 1.0), dtype=np.float32)
        fill_rect(canvas, 0, 0, sw, header_h, (0.09, 0.12, 0.18, 1.0))
        draw_text(canvas, "GOOGLEPLEX QUAD QA - B40, B41, B42, B43, SKYBRIDGE & VOLLEYBALL", 18, 18, scale=2, color=(0.98, 0.99, 1.0, 1.0))

        for idx, rel in enumerate(quad_files):
            glb = ASSETS_ROOT / rel
            if not glb.exists():
                continue
            spec = specs_by_file[rel]
            reset_scene()
            imported = import_glb(glb)
            stats = compute_scene_mesh_stats(imported)
            bmin, bmax, ctr = Vector(stats["bbox_min"]), Vector(stats["bbox_max"]), Vector(stats["center"])
            setup_world(outdoor=True)
            configure_eevee(samples=samples, res_x=tw, res_y=th)
            elev = 28.0 if "volleyball" not in rel else 34.0
            build_studio_rig(ctr, bmin, bmax, azim_deg=38.0, elev_deg=elev, fov_deg=36.0, fill_ratio=0.78, outdoor=True, add_floor=True, floor_z=0.0)
            img = render_view_to_array(str(tmp_dir / f"quad_{idx}.png"))

            c, r = idx % cols, idx // cols
            x0 = pad + c * (tw + pad)
            y0 = header_h + pad + r * (th + cell_hdr + pad)
            res = results_by_file.get(rel, {})
            d = stats["dims"]
            fill_rect(canvas, x0, y0, x0 + tw, y0 + cell_hdr, (0.12, 0.15, 0.22, 1.0))
            draw_text(canvas, spec["label"], x0 + 10, y0 + 7, scale=2, color=(0.98, 0.99, 1.0, 1.0))
            draw_text(canvas, f"{stats['tris']} TRIS | {d[0]:.1f}X{d[1]:.1f}X{d[2]:.1f}M | {res.get('size_kb', 0):.0f}KB | {res.get('status', '?')}", x0 + 10, y0 + 26, scale=1, color=(0.75, 0.85, 0.96, 1.0))
            canvas[y0 + cell_hdr:y0 + cell_hdr + th, x0:x0 + tw] = img

        out = PREVIEWS_DIR / "map_quad_buildings.png"
        save_png_topdown(canvas, out, mirror_dir)
        outputs.append(str(out))

    # 3. Gradient Canopy & The Orb Plaza (2x2 dual-angle)
    east_files = ["map/landmark_gradient_canopy.glb", "map/landmark_orb_plaza.glb"]
    if any((ASSETS_ROOT / f).exists() for f in east_files):
        pw, ph = 640, 440
        sw = pad + 2 * pw + 8 + pad
        sh = header_h + pad + 2 * (ph + 42 + pad)
        canvas = np.full((sh, sw, 4), (0.06, 0.08, 0.11, 1.0), dtype=np.float32)
        fill_rect(canvas, 0, 0, sw, header_h, (0.09, 0.12, 0.18, 1.0))
        draw_text(canvas, "EAST CAMPUS QA - GRADIENT CANOPY & THE ORB PLAZA", 18, 18, scale=2, color=(0.98, 0.99, 1.0, 1.0))

        for i, rel in enumerate(east_files):
            glb = ASSETS_ROOT / rel
            if not glb.exists():
                continue
            spec = specs_by_file[rel]
            reset_scene()
            imported = import_glb(glb)
            stats = compute_scene_mesh_stats(imported)
            bmin, bmax, ctr = Vector(stats["bbox_min"]), Vector(stats["bbox_max"]), Vector(stats["center"])
            setup_world(outdoor=True)
            configure_eevee(samples=samples, res_x=pw, res_y=ph)

            build_studio_rig(ctr, bmin, bmax, azim_deg=40.0, elev_deg=34.0, fov_deg=36.0, fill_ratio=0.78, outdoor=True, add_floor=True, floor_z=0.0)
            a = render_view_to_array(str(tmp_dir / f"east_{i}_a.png"))

            build_studio_rig(ctr, bmin, bmax, azim_deg=-35.0, elev_deg=11.0, fov_deg=36.0, fill_ratio=0.82, outdoor=True, add_floor=True, floor_z=0.0)
            b = render_view_to_array(str(tmp_dir / f"east_{i}_b.png"))

            y0 = header_h + pad + i * (ph + 42 + pad)
            res = results_by_file.get(rel, {})
            d = stats["dims"]
            fill_rect(canvas, pad, y0, sw - pad, y0 + 42, (0.12, 0.15, 0.22, 1.0))
            draw_text(canvas, f"{spec['label']} | {stats['tris']} TRIS | {d[0]:.1f}X{d[1]:.1f}X{d[2]:.1f}M | {res.get('size_kb', 0):.0f}KB", pad + 10, y0 + 13, scale=2, color=(0.98, 0.99, 1.0, 1.0))
            canvas[y0 + 42:y0 + 42 + ph, pad:pad + pw] = a
            canvas[y0 + 42:y0 + 42 + ph, pad + pw + 8:pad + 2 * pw + 8] = b

        out = PREVIEWS_DIR / "map_gradient_orb.png"
        save_png_topdown(canvas, out, mirror_dir)
        outputs.append(str(out))

    # 4. Campus Props & Trees (2x2: Umbrella Bistro, GBike Rack, Live Oak, Coastal Redwood)
    prop_files = [
        "map/prop_umbrella_bistro.glb",
        "map/prop_gbike_rack.glb",
        "map/prop_oak_tree.glb",
        "map/prop_redwood_tree.glb",
    ]
    if any((ASSETS_ROOT / f).exists() for f in prop_files):
        tw, th = 600, 480
        cell_hdr = 42
        cols, rows = 2, 2
        sw = pad + cols * (tw + pad)
        sh = header_h + pad + rows * (th + cell_hdr + pad)
        canvas = np.full((sh, sw, 4), (0.06, 0.08, 0.11, 1.0), dtype=np.float32)
        fill_rect(canvas, 0, 0, sw, header_h, (0.09, 0.12, 0.18, 1.0))
        draw_text(canvas, "CAMPUS PROPS & TREES QA - UMBRELLA, GBIKES, LIVE OAK & REDWOOD", 18, 18, scale=2, color=(0.98, 0.99, 1.0, 1.0))

        for idx, rel in enumerate(prop_files):
            glb = ASSETS_ROOT / rel
            if not glb.exists():
                continue
            spec = specs_by_file[rel]
            reset_scene()
            imported = import_glb(glb)
            stats = compute_scene_mesh_stats(imported)
            bmin, bmax, ctr = Vector(stats["bbox_min"]), Vector(stats["bbox_max"]), Vector(stats["center"])
            setup_world(outdoor=True)
            configure_eevee(samples=samples, res_x=tw, res_y=th)
            elev = 18.0 if "tree" not in rel else 12.0
            build_studio_rig(ctr, bmin, bmax, azim_deg=36.0, elev_deg=elev, fov_deg=35.0, fill_ratio=0.80, outdoor=True, add_floor=True, floor_z=0.0)
            img = render_view_to_array(str(tmp_dir / f"prop_{idx}.png"))

            c, r = idx % cols, idx // cols
            x0 = pad + c * (tw + pad)
            y0 = header_h + pad + r * (th + cell_hdr + pad)
            res = results_by_file.get(rel, {})
            d = stats["dims"]
            fill_rect(canvas, x0, y0, x0 + tw, y0 + cell_hdr, (0.12, 0.15, 0.22, 1.0))
            draw_text(canvas, spec["label"], x0 + 10, y0 + 7, scale=2, color=(0.98, 0.99, 1.0, 1.0))
            draw_text(canvas, f"{stats['tris']} TRIS | {d[0]:.1f}X{d[1]:.1f}X{d[2]:.1f}M | {res.get('size_kb', 0):.0f}KB | {res.get('status', '?')}", x0 + 10, y0 + 26, scale=1, color=(0.75, 0.85, 0.96, 1.0))
            canvas[y0 + cell_hdr:y0 + cell_hdr + th, x0:x0 + tw] = img

        out = PREVIEWS_DIR / "map_props_trees.png"
        save_png_topdown(canvas, out, mirror_dir)
        outputs.append(str(out))

    # 5. Bonus Spatial Integration Render: Googleplex Quad assembled at §10.2 coordinates
    avail_quad = [(rel, pos) for rel, pos in QUAD_ASSEMBLY_PLACEMENTS if (ASSETS_ROOT / rel).exists()]
    if len(avail_quad) >= 4:
        reset_scene()
        all_imported = []
        for rel, (tx, tz) in avail_quad:
            objs = import_glb(ASSETS_ROOT / rel)
            # Three.js (X, Y, Z) maps to Blender (X, -Z, Y)
            roots = [o for o in objs if o.parent is None]
            for rt in roots:
                rt.location.x += tx
                rt.location.y += -tz
            all_imported.extend(objs)
        bpy.context.view_layer.update()
        stats = compute_scene_mesh_stats(all_imported)
        bmin, bmax, ctr = Vector(stats["bbox_min"]), Vector(stats["bbox_max"]), Vector(stats["center"])
        setup_world(outdoor=True)
        pw, ph = 720, 480
        configure_eevee(samples=max(16, samples // 2), res_x=pw, res_y=ph)

        # Aerial SE 3/4 looking NW across the Quad
        build_studio_rig(ctr, bmin, bmax, azim_deg=145.0, elev_deg=38.0, fov_deg=38.0, fill_ratio=0.80, outdoor=True, add_floor=True, floor_z=0.0)
        a = render_view_to_array(str(tmp_dir / "quad_asm_a.png"))

        # Top-down plan view (verifies §10.1 blueprint alignment!)
        build_studio_rig(ctr, bmin, bmax, azim_deg=180.0, elev_deg=86.0, fov_deg=38.0, fill_ratio=0.82, outdoor=True, add_floor=True, floor_z=0.0)
        b = render_view_to_array(str(tmp_dir / "quad_asm_b.png"))

        sw = pad + 2 * pw + 8 + pad
        sh = header_h + pad + ph + 34 + pad
        canvas = np.full((sh, sw, 4), (0.06, 0.08, 0.11, 1.0), dtype=np.float32)
        fill_rect(canvas, 0, 0, sw, header_h, (0.09, 0.12, 0.18, 1.0))
        draw_text(canvas, "GOOGLEPLEX QUAD SPATIAL ASSEMBLY CHECK (SPEC 10.2 COORDS)", 18, 18, scale=2, color=(0.98, 0.99, 1.0, 1.0))
        for i, (lbl, img) in enumerate([("AERIAL 3/4 OVERVIEW", a), ("TOP-DOWN PLAN (NORTH UP)", b)]):
            x0 = pad + i * (pw + 8)
            y0 = header_h + pad
            fill_rect(canvas, x0, y0, x0 + pw, y0 + 34, (0.12, 0.15, 0.22, 1.0))
            draw_text(canvas, lbl, x0 + 10, y0 + 10, scale=2, color=(0.95, 0.98, 1.0, 1.0))
            canvas[y0 + 34:y0 + 34 + ph, x0:x0 + pw] = img

        out = PREVIEWS_DIR / "map_quad_assembled.png"
        save_png_topdown(canvas, out, mirror_dir)
        outputs.append(str(out))

    return outputs


def bisect_meshes_above_z(objects: list, cut_z: float):
    """Cleanly slice off roof/ceiling geometry above world cut_z for architectural interior cutaways."""
    for obj in objects:
        if obj.type != "MESH" or obj.data is None:
            continue
        mesh = obj.data
        bm = bmesh.new()
        bm.from_mesh(mesh)
        mat = obj.matrix_world.copy()
        inv = mat.inverted()
        bmesh.ops.transform(bm, matrix=mat, verts=bm.verts)
        geom = list(bm.verts) + list(bm.edges) + list(bm.faces)
        if geom:
            bmesh.ops.bisect_plane(
                bm,
                geom=geom,
                dist=1e-4,
                plane_co=Vector((0.0, 0.0, cut_z)),
                plane_no=Vector((0.0, 0.0, 1.0)),
                clear_outer=True,
                clear_inner=False,
            )
        bmesh.ops.transform(bm, matrix=inv, verts=bm.verts)
        bm.to_mesh(mesh)
        bm.free()
        mesh.update()
    bpy.context.view_layer.update()


def render_glider_and_jump_qa(results_by_file: dict, samples: int, mirror_dir: Path | None, tmp_dir: Path) -> list[str]:
    """Render docs/previews/qa_glider_hands_and_jump.png:
    Row 1: Gmail AI + prop_glider.glb — Neutral Front 3/4, Side Profile, Banked 20° Left, Banked 20° Right
    Row 2: Tight Hands-on-Handles Close-Up, New Jump Pose, Upgraded Run Cycle, Upgraded Sprint Cycle
    """
    outputs = []
    gmail_glb = ASSETS_ROOT / "characters/hero_gmail.glb"
    glider_glb = ASSETS_ROOT / "utilities/prop_glider.glb"
    if not gmail_glb.exists() or not glider_glb.exists():
        print("WARN: Skipping glider QA render — missing hero_gmail.glb or prop_glider.glb")
        return outputs

    tile_w, tile_h = 460, 500
    header_h = 56
    cell_hdr = 36
    pad = 12
    cols, rows = 4, 2
    sw = pad + cols * (tile_w + pad)
    sh = header_h + pad + rows * (tile_h + cell_hdr + pad)
    canvas = np.full((sh, sw, 4), (0.06, 0.08, 0.11, 1.0), dtype=np.float32)
    fill_rect(canvas, 0, 0, sw, header_h, (0.09, 0.12, 0.18, 1.0))

    # --- Setup Gmail AI in Glide + Glider locked to live Hand_L/Hand_R midpoint ---
    reset_scene()
    hero_objs = import_glb(gmail_glb)
    armatures = [o for o in hero_objs if o.type == "ARMATURE"]
    if not armatures:
        print("ERROR: No armature found in hero_gmail.glb")
        return outputs
    arm = armatures[0]
    glide_act = find_action_for_clip("Glide")
    if glide_act is not None:
        set_armature_action_frame(arm, glide_act, 0.35)
    else:
        reset_armature_rest(arm)

    # Measure live Hand_L / Hand_R bone heads in world space
    pb_l = arm.pose.bones.get("Hand_L")
    pb_r = arm.pose.bones.get("Hand_R")
    if pb_l is not None and pb_r is not None:
        hand_l_pos = arm.matrix_world @ pb_l.head
        hand_r_pos = arm.matrix_world @ pb_r.head
        hand_mid = 0.5 * (hand_l_pos + hand_r_pos)
        # Runtime dynamic offset: Three.js (0, +0.076, -0.056) == Blender (0, +0.056, +0.076)
        glider_pos = hand_mid + Vector((0.0, 0.056, 0.076))
        half_span = 0.5 * (hand_r_pos.x - hand_l_pos.x)
    else:
        hand_l_pos = Vector((-0.235, 0.1243, 1.829))
        hand_r_pos = Vector((0.235, 0.1243, 1.829))
        hand_mid = 0.5 * (hand_l_pos + hand_r_pos)
        glider_pos = Vector((0.0, 0.180, 1.905))
        half_span = 0.235

    print(
        f"  [GLIDER-QA] Hand_L={tuple(round(v, 4) for v in hand_l_pos)} | "
        f"Hand_R={tuple(round(v, 4) for v in hand_r_pos)} | "
        f"half_span={half_span:.4f}m | GliderMount(Blender)={tuple(round(v, 4) for v in glider_pos)}"
    )

    glider_objs = import_glb(glider_glb)

    # Build shared HeroModelPivot + GliderMount mirroring Three.js (gliderMount parented to hero.model)
    hero_pivot = bpy.data.objects.new("HeroModelPivot", None)
    bpy.context.scene.collection.objects.link(hero_pivot)
    hero_pivot.location = (0.0, 0.0, 0.0)

    glider_mount = bpy.data.objects.new("GliderMount", None)
    bpy.context.scene.collection.objects.link(glider_mount)
    glider_mount.parent = hero_pivot
    glider_mount.location = glider_pos

    for o in hero_objs:
        if o.parent is None:
            o.parent = hero_pivot
    for o in glider_objs:
        if o.parent is None:
            o.parent = glider_mount

    bpy.context.view_layer.update()

    # Check rubber grip sleeve world positions vs hands
    for gobj in glider_objs:
        if "HandGripSleeve" in gobj.name or "ControlTrapezeBar" in gobj.name:
            gstats = compute_scene_mesh_stats([gobj])
            print(f"  [GLIDER-QA] {gobj.name}: center={gstats['center']} min={gstats['bbox_min']} max={gstats['bbox_max']}")

    all_combo = hero_objs + glider_objs
    combo_stats = compute_scene_mesh_stats(all_combo)
    c_bmin = Vector(combo_stats["bbox_min"])
    c_bmax = Vector(combo_stats["bbox_max"])
    c_ctr = Vector(combo_stats["center"])

    setup_world(outdoor=False)
    configure_eevee(samples=samples, res_x=tile_w, res_y=tile_h)

    tiles = []

    # Tile 0: Glide Neutral — Front 3/4
    hero_pivot.rotation_euler = (0.0, 0.0, 0.0)
    bpy.context.view_layer.update()
    build_studio_rig(c_ctr, c_bmin, c_bmax, azim_deg=24.0, elev_deg=6.0, fov_deg=34.0, fill_ratio=0.84, add_floor=False)
    tiles.append(("1. GLIDE NEUTRAL (FRONT 3/4)", render_view_to_array(str(tmp_dir / "glider_t0.png"))))

    # Tile 1: Glide Neutral — Side Profile
    build_studio_rig(c_ctr, c_bmin, c_bmax, azim_deg=86.0, elev_deg=4.0, fov_deg=34.0, fill_ratio=0.84, add_floor=False)
    tiles.append(("2. GLIDE NEUTRAL (SIDE PROFILE)", render_view_to_array(str(tmp_dir / "glider_t1.png"))))

    # Tile 2: Glide Banked 20 deg LEFT (roll around forward +Y axis)
    hero_pivot.rotation_euler = (0.0, math.radians(20.0), 0.0)
    bpy.context.view_layer.update()
    bstats_l = compute_scene_mesh_stats(all_combo)
    build_studio_rig(Vector(bstats_l["center"]), Vector(bstats_l["bbox_min"]), Vector(bstats_l["bbox_max"]), azim_deg=18.0, elev_deg=6.0, fov_deg=34.0, fill_ratio=0.84, add_floor=False)
    tiles.append(("3. GLIDE BANKED 20 DEG LEFT", render_view_to_array(str(tmp_dir / "glider_t2.png"))))

    # Tile 3: Glide Banked 20 deg RIGHT
    hero_pivot.rotation_euler = (0.0, math.radians(-20.0), 0.0)
    bpy.context.view_layer.update()
    bstats_r = compute_scene_mesh_stats(all_combo)
    build_studio_rig(Vector(bstats_r["center"]), Vector(bstats_r["bbox_min"]), Vector(bstats_r["bbox_max"]), azim_deg=-18.0, elev_deg=6.0, fov_deg=34.0, fill_ratio=0.84, add_floor=False)
    tiles.append(("4. GLIDE BANKED 20 DEG RIGHT", render_view_to_array(str(tmp_dir / "glider_t3.png"))))

    # Tile 4: Tight Hands-on-Handles Close-up (neutral)
    hero_pivot.rotation_euler = (0.0, 0.0, 0.0)
    bpy.context.view_layer.update()
    cu_min = glider_pos + Vector((-0.40, -0.14, -0.18))
    cu_max = glider_pos + Vector((+0.40, +0.14, +0.16))
    cu_ctr = 0.5 * (cu_min + cu_max)
    build_studio_rig(cu_ctr, cu_min, cu_max, azim_deg=20.0, elev_deg=-10.0, fov_deg=30.0, fill_ratio=0.84, add_floor=False)
    tiles.append(("5. HANDS ON HANDLES CLOSE-UP", render_view_to_array(str(tmp_dir / "glider_t4.png"))))

    # --- Row 2 (Tiles 5, 6, 7): Gmail AI Jump, Run, Sprint without glider ---
    reset_scene()
    hero_objs = import_glb(gmail_glb)
    arm = [o for o in hero_objs if o.type == "ARMATURE"][0]
    setup_world(outdoor=False)
    configure_eevee(samples=samples, res_x=tile_w, res_y=tile_h)

    fixed_min = Vector((-0.68, -0.68, 0.0))
    fixed_max = Vector((0.68, 0.68, 2.02))
    fixed_ctr = Vector((0.0, 0.0, 1.00))

    pose_specs = [
        ("Jump", 0.50, 52.0, 10.0, "6. NEW JUMP CLIP (AIRBORNE)"),
        ("Run", 0.25, 62.0, 8.0, "7. UPGRADED RUN (STRIDE)"),
        ("Sprint", 0.25, 66.0, 8.0, "8. UPGRADED SPRINT (DRIVE)"),
    ]
    for i, (clip_name, frac, az, el, label) in enumerate(pose_specs):
        act = find_action_for_clip(clip_name)
        if act is not None:
            set_armature_action_frame(arm, act, frac)
        else:
            reset_armature_rest(arm)
        build_studio_rig(fixed_ctr, fixed_min, fixed_max, azim_deg=az, elev_deg=el, fov_deg=34.0, fill_ratio=0.84, add_floor=True, floor_z=0.0)
        tiles.append((label, render_view_to_array(str(tmp_dir / f"glider_pose_{i}.png"))))

    header_txt = f"ICON AI QA - GLIDER HAND-LOCK (SPAN +-0.235M, BANK +-20 DEG) + JUMP / RUN / SPRINT"
    draw_text(canvas, header_txt, 16, 18, scale=2, color=(0.96, 0.98, 1.0, 1.0))

    for idx, (lbl, img) in enumerate(tiles):
        c, r = idx % cols, idx // cols
        x0 = pad + c * (tile_w + pad)
        y0 = header_h + pad + r * (tile_h + cell_hdr + pad)
        fill_rect(canvas, x0, y0, x0 + tile_w, y0 + cell_hdr, (0.12, 0.15, 0.22, 1.0))
        draw_text(canvas, lbl, x0 + 10, y0 + 11, scale=2, color=(0.98, 0.99, 1.0, 1.0))
        canvas[y0 + cell_hdr:y0 + cell_hdr + tile_h, x0:x0 + tile_w] = img

    out = PREVIEWS_DIR / "qa_glider_hands_and_jump.png"
    save_png_topdown(canvas, out, mirror_dir)
    outputs.append(str(out))
    return outputs


def render_office_interiors_qa(results_by_file: dict, samples: int, mirror_dir: Path | None, tmp_dir: Path) -> list[str]:
    """Render docs/previews/qa_office_interiors.png:
    Row 1 (5 tiles): All 5 office furniture props (desk_pod, conference_pod, microkitchen_bar, lounge_nook, whiteboard_wall)
    Row 2 (5 tiles): Doorway & atrium exterior/eye-level views (B40, B41, B42, B43, Gradient Canopy)
    Row 3 (5 tiles): Architectural roof-off interior cutaway views (B40, B41, B42, B43, Gradient Canopy)
    """
    outputs = []
    prop_specs = ASSET_SPECS["office_props"]
    bldg_specs = [
        ("map/landmark_b40_partnerplex.glb", "B40 CHARLIES / PARTNER PLEX", 4.6, 158.0, 9.0),
        ("map/landmark_b41.glb", "BUILDING 41", 4.6, 166.0, 9.0),
        ("map/landmark_b42.glb", "BUILDING 42", 4.6, 52.0, 9.0),
        ("map/landmark_b43.glb", "BUILDING 43", 4.6, 22.0, 9.0),
        ("map/landmark_gradient_canopy.glb", "GRADIENT CANOPY ATRIUM", 6.2, 12.0, 7.0),
    ]

    tw, th = 420, 340
    header_h = 56
    cell_hdr = 40
    pad = 10
    cols, rows = 5, 3
    sw = pad + cols * (tw + pad)
    sh = header_h + pad + rows * (th + cell_hdr + pad)
    canvas = np.full((sh, sw, 4), (0.06, 0.08, 0.11, 1.0), dtype=np.float32)
    fill_rect(canvas, 0, 0, sw, header_h, (0.09, 0.12, 0.18, 1.0))
    draw_text(canvas, "POLISH QA - 5 OFFICE FURNITURE PROPS + HOLLOW B40-B43 & GRADIENT CANOPY INTERIORS", 16, 18, scale=2, color=(0.96, 0.98, 1.0, 1.0))

    # Row 1: 5 Office Furniture Props
    prop_cam_azim = {
        "map/prop_desk_pod.glb": 34.0,
        "map/prop_conference_pod.glb": 38.0,
        "map/prop_microkitchen_bar.glb": 146.0,  # Front stools + stocked glass cooler face +Z (Three.js) = -Y (Blender)
        "map/prop_lounge_nook.glb": 34.0,
        "map/prop_whiteboard_wall.glb": 34.0,
    }
    for c, spec in enumerate(prop_specs):
        glb = ASSETS_ROOT / spec["file"]
        if not glb.exists():
            continue
        reset_scene()
        imported = import_glb(glb)
        stats = compute_scene_mesh_stats(imported)
        bmin, bmax, ctr = Vector(stats["bbox_min"]), Vector(stats["bbox_max"]), Vector(stats["center"])
        setup_world(outdoor=False)
        configure_eevee(samples=samples, res_x=tw, res_y=th)
        az = prop_cam_azim.get(spec["file"], 34.0)
        build_studio_rig(ctr, bmin, bmax, azim_deg=az, elev_deg=22.0, fov_deg=34.0, fill_ratio=0.80, outdoor=False, add_floor=True, floor_z=0.0)
        img = render_view_to_array(str(tmp_dir / f"off_prop_{c}.png"))

        x0 = pad + c * (tw + pad)
        y0 = header_h + pad
        res = results_by_file.get(spec["file"], {})
        d = stats["dims"]
        fill_rect(canvas, x0, y0, x0 + tw, y0 + cell_hdr, (0.12, 0.15, 0.22, 1.0))
        draw_text(canvas, spec["label"], x0 + 8, y0 + 6, scale=2, color=(0.98, 0.99, 1.0, 1.0))
        draw_text(canvas, f"{stats['tris']} TRIS | {d[0]:.1f}X{d[1]:.1f}X{d[2]:.1f}M | {res.get('size_kb', 0):.0f}KB | {res.get('status', '?')}", x0 + 8, y0 + 25, scale=1, color=(0.75, 0.85, 0.96, 1.0))
        canvas[y0 + cell_hdr:y0 + cell_hdr + th, x0:x0 + tw] = img

    # Doorway close-up targets in each building's local Blender (X, Y, Z) space (derived from #50)
    # Three.js local (dx, dz) -> Blender local (dx, -dz)
    door_focus_local = {
        "map/landmark_b40_partnerplex.glb": (Vector((7.0, -15.6, 2.2)), 10.5, 165.0, 7.0),
        "map/landmark_b41.glb": (Vector((1.7, -16.2, 2.2)), 9.5, 168.0, 7.0),
        "map/landmark_b42.glb": (Vector((13.4, 10.0, 2.2)), 9.5, 55.0, 7.0),
        "map/landmark_b43.glb": (Vector((5.2, 13.0, 2.2)), 10.5, 18.0, 7.0),
        "map/landmark_gradient_canopy.glb": (Vector((0.0, 0.0, 2.8)), 24.0, 180.0, 8.0),
    }

    # Row 2 & Row 3: Close-up Open Doorway Views + Roof-Off Architectural Cutaways
    for c, (rel, label, cut_z, door_az, door_el) in enumerate(bldg_specs):
        glb = ASSETS_ROOT / rel
        if not glb.exists():
            continue
        reset_scene()
        imported = import_glb(glb)
        stats = compute_scene_mesh_stats(imported)
        bmin, bmax, ctr = Vector(stats["bbox_min"]), Vector(stats["bbox_max"]), Vector(stats["center"])
        setup_world(outdoor=True)
        configure_eevee(samples=max(16, samples // 2), res_x=tw, res_y=th)

        # Row 2: Close-up doorway / portal view looking directly through open entrance into hollow interior
        if rel in door_focus_local:
            focus_ctr, half_r, f_az, f_el = door_focus_local[rel]
            d_min = focus_ctr - Vector((half_r, half_r, 2.2))
            d_max = focus_ctr + Vector((half_r, half_r, 3.2))
            build_studio_rig(focus_ctr, d_min, d_max, azim_deg=f_az, elev_deg=f_el, fov_deg=38.0, fill_ratio=0.86, outdoor=True, add_floor=True, floor_z=0.0)
        else:
            low_min = Vector((bmin.x, bmin.y, 0.0))
            low_max = Vector((bmax.x, bmax.y, min(bmax.z, 8.5)))
            low_ctr = 0.5 * (low_min + low_max)
            build_studio_rig(low_ctr, low_min, low_max, azim_deg=door_az, elev_deg=door_el, fov_deg=36.0, fill_ratio=0.80, outdoor=True, add_floor=True, floor_z=0.0)
        img_door = render_view_to_array(str(tmp_dir / f"off_door_{c}.png"))

        # Row 3: Slice off roof/ceiling at cut_z and render 3/4 cutaway into hollow floorplan!
        bisect_meshes_above_z(imported, cut_z)
        cut_stats = compute_scene_mesh_stats(imported)
        c_min, c_max, c_ctr = Vector(cut_stats["bbox_min"]), Vector(cut_stats["bbox_max"]), Vector(cut_stats["center"])
        build_studio_rig(c_ctr, c_min, c_max, azim_deg=door_az + 22.0, elev_deg=44.0, fov_deg=36.0, fill_ratio=0.82, outdoor=True, add_floor=True, floor_z=0.0)
        img_cut = render_view_to_array(str(tmp_dir / f"off_cut_{c}.png"))

        x0 = pad + c * (tw + pad)
        # Place Row 2
        y1 = header_h + pad + 1 * (th + cell_hdr + pad)
        fill_rect(canvas, x0, y1, x0 + tw, y1 + cell_hdr, (0.12, 0.15, 0.22, 1.0))
        draw_text(canvas, f"{label} - DOORWAY", x0 + 8, y1 + 6, scale=1, color=(0.98, 0.99, 1.0, 1.0))
        d = stats["dims"]
        draw_text(canvas, f"{stats['tris']} TRIS | {d[0]:.1f}X{d[1]:.1f}X{d[2]:.1f}M", x0 + 8, y1 + 24, scale=1, color=(0.75, 0.85, 0.96, 1.0))
        canvas[y1 + cell_hdr:y1 + cell_hdr + th, x0:x0 + tw] = img_door

        # Place Row 3
        y2 = header_h + pad + 2 * (th + cell_hdr + pad)
        fill_rect(canvas, x0, y2, x0 + tw, y2 + cell_hdr, (0.12, 0.15, 0.22, 1.0))
        draw_text(canvas, f"{label} - CUTAWAY Z<{cut_z:.1f}M", x0 + 8, y2 + 13, scale=1, color=(0.98, 0.99, 1.0, 1.0))
        canvas[y2 + cell_hdr:y2 + cell_hdr + th, x0:x0 + tw] = img_cut

    out = PREVIEWS_DIR / "qa_office_interiors.png"
    save_png_topdown(canvas, out, mirror_dir)
    outputs.append(str(out))
    return outputs


def _srgb_hex_to_linear_rgba(hex_str: str) -> tuple[float, float, float, float]:
    h = hex_str.lstrip("#")
    def _lin(u: float) -> float:
        return u / 12.92 if u <= 0.04045 else ((u + 0.055) / 1.055) ** 2.4
    return (
        _lin(int(h[0:2], 16) / 255.0),
        _lin(int(h[2:4], 16) / 255.0),
        _lin(int(h[4:6], 16) / 255.0),
        1.0,
    )


def _tint_rarity_accent_materials(base_hex: str, emissive_hex: str, emissive_strength: float) -> None:
    """Mirror Three.js runtime RarityAccent material tinting directly inside Blender EEVEE."""
    base_col = _srgb_hex_to_linear_rgba(base_hex)
    emit_col = _srgb_hex_to_linear_rgba(emissive_hex)
    for mat in bpy.data.materials:
        if mat.name == "RarityAccent" or mat.name.startswith("RarityAccent."):
            if mat.node_tree is None:
                continue
            bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
            if bsdf is None:
                continue
            bsdf.inputs["Base Color"].default_value = base_col
            if "Emission Color" in bsdf.inputs:
                bsdf.inputs["Emission Color"].default_value = emit_col
            if "Emission Strength" in bsdf.inputs:
                bsdf.inputs["Emission Strength"].default_value = emissive_strength


def render_loot_chest_qa(results_by_file: dict, samples: int, mirror_dir: Path | None, tmp_dir: Path) -> list[str]:
    """Render docs/previews/qa_loot_chest.png (2x3 EEVEE showcase):
    Row 1: Closed Front 3/4, Lid Hinged Open (+100 deg / +1.745 rad) Tray Reveal, Side/Rear Hinge Audit (+100 deg)
    Row 2: Runtime RarityAccent Variants — Tier 1 (Warm Bronze/Amber), Tier 2 (Cobalt Blue), Tier 3 (Royal Purple/Gold)
    """
    outputs = []
    rel = "utilities/prop_loot_chest.glb"
    glb = ASSETS_ROOT / rel
    if not glb.exists():
        print(f"WARN: Skipping loot chest QA render — missing {glb}")
        return outputs

    reset_scene()
    imported = import_glb(glb)
    lid_objs = [o for o in imported if o.name == "ChestLid" or o.name.startswith("ChestLid.")]
    lid_obj = lid_objs[0] if lid_objs else None
    if lid_obj is not None:
        # glTF importer sets rotation_mode='QUATERNION' on nodes; switch to XYZ so rotation_euler drives hinge!
        lid_obj.rotation_mode = "XYZ"

    closed_stats = compute_scene_mesh_stats(imported)
    c_min, c_max, c_ctr = (
        Vector(closed_stats["bbox_min"]),
        Vector(closed_stats["bbox_max"]),
        Vector(closed_stats["center"]),
    )

    # Measure open (+100 deg) bbox & log hinge telemetry
    open_deg = 100.0
    if lid_obj is not None:
        lid_obj.rotation_euler = Euler((math.radians(open_deg), 0.0, 0.0), "XYZ")
        bpy.context.view_layer.update()
    open_stats = compute_scene_mesh_stats(imported)
    o_min, o_max, o_ctr = (
        Vector(open_stats["bbox_min"]),
        Vector(open_stats["bbox_max"]),
        Vector(open_stats["center"]),
    )

    if lid_obj is not None:
        lp = lid_obj.matrix_world.translation
        print(
            f"  [CHEST-QA] ChestLid pivot Blender=({lp.x:.3f}, {lp.y:.3f}, {lp.z:.3f}) "
            f"-> Three.js=({lp.x:.3f}, {lp.z:.3f}, {-lp.y:.3f}) | "
            f"open(+100 deg) Z=[{o_min.z:.3f}, {o_max.z:.3f}] Y=[{o_min.y:.3f}, {o_max.y:.3f}]"
        )

    tile_w, tile_h = 540, 440
    header_h = 58
    cell_hdr = 40
    pad = 12
    cols, rows = 3, 2
    sw = pad + cols * (tile_w + pad)
    sh = header_h + pad + rows * (tile_h + cell_hdr + pad)
    canvas = np.full((sh, sw, 4), (0.06, 0.08, 0.11, 1.0), dtype=np.float32)
    fill_rect(canvas, 0, 0, sw, header_h, (0.09, 0.12, 0.18, 1.0))

    res = results_by_file.get(rel, {})
    d = closed_stats["dims"]
    hdr_title = (
        f"LOOT CHEST QA - PROP_LOOT_CHEST.GLB | {closed_stats['tris']} TRIS | "
        f"{res.get('size_kb', 0):.1f}KB | {d[0]:.2f}X{d[1]:.2f}X{d[2]:.2f}M | "
        f"OPEN ROT.X = +100 DEG (+1.745 RAD)"
    )
    draw_text(canvas, hdr_title, 16, 19, scale=2, color=(0.96, 0.98, 1.0, 1.0))

    setup_world(outdoor=False)
    configure_eevee(samples=samples, res_x=tile_w, res_y=tile_h)

    # Panel specifications: (label, sublabel, lid_deg, azim_deg, elev_deg, base_hex, emit_hex, emit_str, badge_rgb)
    # Note: Moderate emission strength (~1.7-2.2) keeps rich saturated amber/cobalt/purple under AgX tone mapping
    panels = [
        (
            "1. CLOSED (FRONT 3/4)",
            "FRONT +Y CLASPS & LED BAR | GROUNDED Z=0.00M",
            0.0, 34.0, 22.0, "#F59E0B", "#FF9500", 1.75, (0.86, 0.54, 0.08, 1.0),
        ),
        (
            "2. LID HINGED OPEN (+100 DEG)",
            "CHESTLID.ROTATION.X = +1.745 RAD | GLOWING TRAY",
            100.0, 28.0, 32.0, "#F59E0B", "#FF9500", 1.95, (0.86, 0.54, 0.08, 1.0),
        ),
        (
            "3. REAR HINGE CLEARANCE (+100 DEG)",
            "SIDE/REAR AUDIT: COAXIAL PIN, ZERO CLIPPING",
            100.0, 144.0, 18.0, "#F59E0B", "#FF9500", 1.75, (0.24, 0.52, 0.76, 1.0),
        ),
        (
            "4. TIER 1 - WARM BRONZE / AMBER",
            "RARITYACCENT F59E0B (STANDARD CHEST, +50 DEG)",
            50.0, 30.0, 26.0, "#F59E0B", "#FF8C00", 1.85, (0.86, 0.54, 0.08, 1.0),
        ),
        (
            "5. TIER 2 - COBALT BLUE (RARE)",
            "RARITYACCENT 2563EB (RARE CHEST, +50 DEG)",
            50.0, 30.0, 26.0, "#2563EB", "#1D6BFF", 2.15, (0.16, 0.44, 0.94, 1.0),
        ),
        (
            "6. TIER 3 - ROYAL PURPLE / GOLD",
            "RARITYACCENT 9333EA + GOLD CLASPS (+50 DEG)",
            50.0, 30.0, 26.0, "#9333EA", "#A020F0", 2.25, (0.60, 0.22, 0.90, 1.0),
        ),
    ]

    for idx, (lbl, sub, lid_deg, azim, elev, b_hex, e_hex, e_str, accent_rgba) in enumerate(panels):
        if lid_obj is not None:
            lid_obj.rotation_euler = Euler((math.radians(lid_deg), 0.0, 0.0), "XYZ")
            bpy.context.view_layer.update()
        _tint_rarity_accent_materials(b_hex, e_hex, e_str)

        p_stats = compute_scene_mesh_stats(imported)
        p_min, p_max, p_ctr = (
            Vector(p_stats["bbox_min"]),
            Vector(p_stats["bbox_max"]),
            Vector(p_stats["center"]),
        )
        # Keep studio camera cleanly framed on current pose
        build_studio_rig(
            p_ctr,
            p_min,
            p_max,
            azim_deg=azim,
            elev_deg=elev,
            fov_deg=33.0,
            fill_ratio=0.80,
            outdoor=False,
            add_floor=True,
            floor_z=0.0,
        )
        img = render_view_to_array(str(tmp_dir / f"chest_qa_{idx}.png"))

        c, r = idx % cols, idx // cols
        x0 = pad + c * (tile_w + pad)
        y0 = header_h + pad + r * (tile_h + cell_hdr + pad)
        fill_rect(canvas, x0, y0, x0 + tile_w, y0 + cell_hdr, (0.12, 0.15, 0.22, 1.0))
        fill_rect(canvas, x0, y0, x0 + 8, y0 + cell_hdr, accent_rgba)
        draw_text(canvas, lbl, x0 + 16, y0 + 6, scale=2, color=(0.98, 0.99, 1.0, 1.0))
        draw_text(canvas, sub, x0 + 16, y0 + 25, scale=1, color=(0.74, 0.84, 0.95, 1.0))
        canvas[y0 + cell_hdr:y0 + cell_hdr + tile_h, x0:x0 + tile_w] = img

    out = PREVIEWS_DIR / "qa_loot_chest.png"
    save_png_topdown(canvas, out, mirror_dir)
    outputs.append(str(out))
    return outputs


def align_weapon_two_handed_blender(
    weapon_pivot,
    arm_obj,
    sock_obj,
    up_ref: Vector | None = None,
    local_offset: Vector | None = None,
) -> tuple[float, Vector, Vector, Vector]:
    """Mirror Three.js alignWeaponTwoHanded() in Blender Z-up/+Y-forward space.
    Mounts weapon_pivot at WeaponSocket_R and orients weapon +Y barrel axis so
    handguard underside (0, RIFLE_FOREGRIP_DIST, RIFLE_FOREGRIP_UP) passes
    dead-center through Hand_L palm (LEFT_PALM_LOCAL in Hand_L bone-local space).
    """
    pb_l = arm_obj.pose.bones["Hand_L"]
    grip_pos = sock_obj.matrix_world.translation.copy()
    m_l = arm_obj.matrix_world @ pb_l.matrix
    foregrip_pos = m_l @ LEFT_PALM_LOCAL

    g_vec = foregrip_pos - grip_pos
    sep = g_vec.length
    if sep < 1e-5:
        return sep, Vector((0.0, 1.0, 0.0)), grip_pos, foregrip_pos
    g_hat = g_vec / sep
    up_v = up_ref if up_ref is not None else Vector((0.0, 0.0, 1.0))
    r_hat = g_hat.cross(up_v)
    if r_hat.length < 1e-5:
        r_hat = Vector((1.0, 0.0, 0.0))
    r_hat.normalize()
    g_up = r_hat.cross(g_hat).normalized()

    cos_a = math.cos(RIFLE_GRIP_ALPHA)
    sin_a = math.sin(RIFLE_GRIP_ALPHA)
    b_hat = (g_hat * cos_a - g_up * sin_a).normalized()
    u_hat = (g_hat * sin_a + g_up * cos_a).normalized()

    rot_3x3 = Matrix((r_hat, b_hat, u_hat)).transposed()
    world_pos = grip_pos
    if local_offset is not None:
        world_pos = grip_pos + rot_3x3 @ local_offset
    weapon_pivot.matrix_world = Matrix.Translation(world_pos) @ rot_3x3.to_4x4()
    bpy.context.view_layer.update()
    return sep, b_hat, grip_pos, foregrip_pos


def render_twohanded_weapons_qa(results_by_file: dict, samples: int, mirror_dir: Path | None, tmp_dir: Path) -> list[str]:
    """Render 8-panel EEVEE showcase docs/previews/qa_twohanded_weapons.png:
    Row 1:
      1. IdleArmed (Front 3/4 - two hands low-ready, M4)
      2. RunArmed (Front 3/4 - held tight against chest with both hands, M4)
      3. RunArmed (Side 3/4 - chest clearance & zero clipping, M4)
      4. SprintArmed (Front 3/4 - held tight against chest with both hands, M4)
    Row 2:
      5. Aim (Front 3/4 - both hands on grip & handguard, stock tucked in shoulder, M4)
      6. Aim (Side Profile - straight level barrel, both hands locked, Longbow .308)
      7. Crouch (Front 3/4 - two-handed crouch ready, M4)
      8. Split Close-Up of BOTH hands gripping M4 pistol grip & handguard in Aim (top) & RunArmed (bottom)
    """
    outputs = []
    hero_glb = ASSETS_ROOT / "characters/hero_gmail.glb"
    m4_glb = ASSETS_ROOT / "weapons/weapon_vanguard_m4.glb"
    sniper_glb = ASSETS_ROOT / "weapons/weapon_longbow_308.glb"
    if not hero_glb.exists() or not m4_glb.exists() or not sniper_glb.exists():
        print("WARN: Skipping two-handed weapon QA render — missing hero_gmail.glb, M4, or Longbow .308")
        return outputs

    reset_scene()
    hero_objs = import_glb(hero_glb)
    armatures = [o for o in hero_objs if o.type == "ARMATURE"]
    sock_objs = [o for o in hero_objs if o.name == "WeaponSocket_R" or o.name.startswith("WeaponSocket_R.")]
    if not armatures or not sock_objs:
        print("ERROR: Missing Armature or WeaponSocket_R in hero_gmail.glb")
        return outputs
    arm = armatures[0]
    sock = sock_objs[0]

    # Import M4 and Longbow .308 under separate pivots (avoid "QA_" prefix which build_studio_rig purges!)
    m4_objs = import_glb(m4_glb)
    m4_pivot = bpy.data.objects.new("WeaponM4Pivot", None)
    bpy.context.scene.collection.objects.link(m4_pivot)
    for o in m4_objs:
        if o.parent is None:
            o.parent = m4_pivot

    sniper_objs = import_glb(sniper_glb)
    sniper_pivot = bpy.data.objects.new("WeaponSniperPivot", None)
    bpy.context.scene.collection.objects.link(sniper_pivot)
    for o in sniper_objs:
        if o.parent is None:
            o.parent = sniper_pivot

    # Tint weapon RarityAccent to crisp Rare Cobalt Blue so receiver/handguard pops clearly in EEVEE
    _tint_rarity_accent_materials("#2563EB", "#38BDF8", 1.6)

    def set_active_weapon(which: str):
        show_m4 = which == "m4"
        for o in m4_objs:
            o.hide_render = not show_m4
            o.hide_viewport = not show_m4
        for o in sniper_objs:
            o.hide_render = show_m4
            o.hide_viewport = show_m4
        return (m4_pivot, m4_objs) if show_m4 else (sniper_pivot, sniper_objs)

    tile_w, tile_h = 520, 560
    header_h = 62
    cell_hdr = 42
    pad = 12
    cols, rows = 4, 2
    sw = pad + cols * (tile_w + pad)
    sh = header_h + pad + rows * (tile_h + cell_hdr + pad)
    canvas = np.full((sh, sw, 4), (0.06, 0.08, 0.11, 1.0), dtype=np.float32)
    fill_rect(canvas, 0, 0, sw, header_h, (0.09, 0.12, 0.18, 1.0))

    setup_world(outdoor=False)
    configure_eevee(samples=samples, res_x=tile_w, res_y=tile_h)

    full_panels = [
        ("1. IDLEARMED (FRONT 3/4)", "M4 LOW-READY | BOTH HANDS LOCKED", "IdleArmed", 0.25, "m4", 26.0, 8.0, 34.0, (0.20, 0.62, 0.92, 1.0)),
        ("2. RUNARMED (FRONT 3/4)", "M4 TIGHT CHEST CARRY | BOTH HANDS", "RunArmed", 0.25, "m4", 22.0, 8.0, 34.0, (0.18, 0.72, 0.44, 1.0)),
        ("3. RUNARMED (SIDE 3/4)", "CHEST CLEARANCE & ZERO CLIPPING", "RunArmed", 0.25, "m4", -66.0, 8.0, 34.0, (0.18, 0.72, 0.44, 1.0)),
        ("4. SPRINTARMED (FRONT 3/4)", "M4 TIGHT UPPER-CHEST SPRINT CARRY", "SprintArmed", 0.25, "m4", 20.0, 8.0, 34.0, (0.90, 0.56, 0.12, 1.0)),
        ("5. AIM (FRONT 3/4 - M4)", "SHOULDERED ADS | STOCK TUCKED IN", "Aim", 0.25, "m4", 34.0, 7.0, 34.0, (0.86, 0.24, 0.30, 1.0)),
        ("6. AIM (SIDE PROFILE - LONGBOW)", "STRAIGHT LEVEL BARREL | BOTH HANDS", "Aim", 0.25, "sniper", 88.0, 4.0, 33.0, (0.64, 0.28, 0.92, 1.0)),
        ("7. CROUCH (FRONT 3/4 - M4)", "GROUNDED TWO-HANDED CROUCH READY", "Crouch", 0.25, "m4", 30.0, 9.0, 34.0, (0.24, 0.70, 0.78, 1.0)),
    ]

    tiles = []
    for idx, (lbl, sub, clip_name, frac, wpn_key, azim, elev, fov, accent) in enumerate(full_panels):
        act = find_action_for_clip(clip_name)
        if act is not None:
            set_armature_action_frame(arm, act, frac)
        else:
            reset_armature_rest(arm)

        wpn_pivot, wpn_objs = set_active_weapon(wpn_key)
        # Mirror WEAPON_GRIP_TUNE from src/core/assetManager.ts (Three.js -Z forward == Blender +Y forward)
        wpn_local_off = Vector((0.0, 0.010, 0.0)) if wpn_key == "sniper" else None
        sep, b_hat, g_pos, fg_pos = align_weapon_two_handed_blender(wpn_pivot, arm, sock, local_offset=wpn_local_off)
        print(
            f"  [TWOHAND-QA] Panel {idx + 1} ({clip_name}/{wpn_key}): sep={sep:.4f}m "
            f"(err={(sep - RIFLE_TARGET_SEP)*1000:+.2f}mm) | barrel=({b_hat.x:+.3f},{b_hat.y:+.3f},{b_hat.z:+.3f})"
        )

        # Evaluate combined bbox of hero + active weapon for crisp full-body framing
        combo_stats = compute_scene_mesh_stats(hero_objs + wpn_objs)
        bmin = Vector(combo_stats["bbox_min"])
        bmax = Vector(combo_stats["bbox_max"])
        bmin.z = min(0.0, bmin.z)
        ctr = 0.5 * (bmin + bmax)
        build_studio_rig(
            ctr,
            bmin,
            bmax,
            azim_deg=azim,
            elev_deg=elev,
            fov_deg=fov,
            fill_ratio=0.84,
            outdoor=False,
            add_floor=True,
            floor_z=0.0,
        )
        img = render_view_to_array(str(tmp_dir / f"twohand_p{idx}.png"))
        tiles.append((lbl, sub, accent, img))

    # Panel 8: Split High-Res Close-Up (Top = Aim Grip & Handguard, Bottom = RunArmed Grip & Handguard)
    split_gap = 6
    half_h = (tile_h - split_gap) // 2
    configure_eevee(samples=samples, res_x=tile_w, res_y=half_h)
    wpn_pivot, wpn_objs = set_active_weapon("m4")

    # Top Close-Up: Aim (Right-front close-up showing pistol grip, handguard cradle & stock in shoulder)
    aim_act = find_action_for_clip("Aim")
    if aim_act is not None:
        set_armature_action_frame(arm, aim_act, 0.25)
    _, _, g_aim, fg_aim = align_weapon_two_handed_blender(wpn_pivot, arm, sock)
    aim_mid = 0.5 * (g_aim + fg_aim) + Vector((0.0, -0.02, 0.03))
    aim_min = aim_mid - Vector((0.22, 0.30, 0.16))
    aim_max = aim_mid + Vector((0.22, 0.30, 0.16))
    build_studio_rig(aim_mid, aim_min, aim_max, azim_deg=62.0, elev_deg=6.0, fov_deg=28.0, fill_ratio=0.88, outdoor=False, add_floor=False)
    cu_aim_img = render_view_to_array(str(tmp_dir / "twohand_cu_aim.png"))

    # Bottom Close-Up: RunArmed (Front-left close-up showing both hands on grip & handguard tight across chest)
    run_act = find_action_for_clip("RunArmed")
    if run_act is not None:
        set_armature_action_frame(arm, run_act, 0.25)
    _, _, g_run, fg_run = align_weapon_two_handed_blender(wpn_pivot, arm, sock)
    run_mid = 0.5 * (g_run + fg_run) + Vector((0.0, 0.0, 0.01))
    run_min = run_mid - Vector((0.28, 0.22, 0.17))
    run_max = run_mid + Vector((0.28, 0.22, 0.17))
    build_studio_rig(run_mid, run_min, run_max, azim_deg=-14.0, elev_deg=6.0, fov_deg=28.0, fill_ratio=0.88, outdoor=False, add_floor=False)
    cu_run_img = render_view_to_array(str(tmp_dir / "twohand_cu_run.png"))

    cu_composite = np.full((tile_h, tile_w, 4), (0.06, 0.08, 0.11, 1.0), dtype=np.float32)
    cu_composite[0:half_h, 0:tile_w] = cu_aim_img
    cu_composite[half_h + split_gap:half_h + split_gap + half_h, 0:tile_w] = cu_run_img
    fill_rect(cu_composite, 0, 0, 260, 22, (0.08, 0.11, 0.16, 0.90))
    draw_text(cu_composite, "AIM: M4 GRIP + HANDGUARD + SHOULDER", 8, 7, scale=1, color=(0.98, 0.92, 0.45, 1.0))
    fill_rect(cu_composite, 0, half_h + split_gap, 280, half_h + split_gap + 22, (0.08, 0.11, 0.16, 0.90))
    draw_text(cu_composite, "RUNARMED: M4 CHEST CARRY BOTH HANDS", 8, half_h + split_gap + 7, scale=1, color=(0.45, 0.96, 0.68, 1.0))

    tiles.append(("8. GRIP CLOSE-UPS (AIM / RUN)", "HAND_R PISTOL GRIP & HAND_L HANDGUARD", (0.95, 0.78, 0.16, 1.0), cu_composite))

    # Composite Header & All 8 Tiles
    hero_total_mb = sum(
        (ASSETS_ROOT / s["file"]).stat().st_size
        for s in ASSET_SPECS["characters"]
        if (ASSETS_ROOT / s["file"]).exists()
    ) / (1024.0 * 1024.0)
    hdr = (
        f"TWO-HANDED WEAPON QA - GMAIL AI (12 CLIPS, 6 ICON AIs={hero_total_mb:.2f}MB) | "
        f"M4 + LONGBOW .308 MOUNTED VIA ALIGNWEAPONTWOHANDED"
    )
    draw_text(canvas, hdr, 16, 20, scale=2, color=(0.96, 0.98, 1.0, 1.0))

    for idx, (lbl, sub, accent, img) in enumerate(tiles):
        c, r = idx % cols, idx // cols
        x0 = pad + c * (tile_w + pad)
        y0 = header_h + pad + r * (tile_h + cell_hdr + pad)
        fill_rect(canvas, x0, y0, x0 + tile_w, y0 + cell_hdr, (0.12, 0.15, 0.22, 1.0))
        fill_rect(canvas, x0, y0, x0 + 8, y0 + cell_hdr, accent)
        draw_text(canvas, lbl, x0 + 16, y0 + 6, scale=2, color=(0.98, 0.99, 1.0, 1.0))
        draw_text(canvas, sub, x0 + 16, y0 + 27, scale=1, color=(0.74, 0.84, 0.95, 1.0))
        canvas[y0 + cell_hdr:y0 + cell_hdr + tile_h, x0:x0 + tile_w] = img

    out = PREVIEWS_DIR / "qa_twohanded_weapons.png"
    save_png_topdown(canvas, out, mirror_dir)
    outputs.append(str(out))
    return outputs


def render_expanded_landmarks_qa(results_by_file: dict, samples: int, mirror_dir: Path | None, tmp_dir: Path) -> list[str]:
    """Render 6-panel (3x2) outdoor EEVEE showcase docs/previews/qa_expanded_landmarks.png
    covering all 6 new 3x Mountain View campus landmarks:
      1. Shoreline Amphitheatre
      2. Athletic Recreation Field
      3. Google 2000 & 1950 Complex
      4. Charleston Campus
      5. 1098 Alta / Huff Complex
      6. Shoreline East Office (Google 2015 / CL2 / 1395)
    """
    outputs = []
    panel_specs = [
        ("map/landmark_shoreline_amphitheatre.glb", "1. SHORELINE AMPHITHEATRE", 148.0, 22.0, (0.20, 0.62, 0.94, 1.0)),
        ("map/landmark_athletic_field.glb", "2. ATHLETIC RECREATION FIELD", 36.0, 30.0, (0.20, 0.74, 0.42, 1.0)),
        ("map/landmark_google_2000_1950.glb", "3. GOOGLE 2000 & 1950 COMPLEX", 40.0, 25.0, (0.94, 0.62, 0.16, 1.0)),
        ("map/landmark_charleston_campus.glb", "4. CHARLESTON CAMPUS", 34.0, 25.0, (0.86, 0.28, 0.34, 1.0)),
        ("map/landmark_alta_complex.glb", "5. 1098 ALTA / HUFF COMPLEX", 38.0, 25.0, (0.58, 0.36, 0.90, 1.0)),
        ("map/landmark_shoreline_east_office.glb", "6. SHORELINE EAST OFFICE", 36.0, 24.0, (0.18, 0.72, 0.78, 1.0)),
    ]
    if not any((ASSETS_ROOT / rel).exists() for rel, *_ in panel_specs):
        print("WARN: Skipping expanded landmarks QA render — none of the 6 new landmark GLBs exist yet")
        return outputs

    tw, th = 640, 460
    header_h = 62
    cell_hdr = 46
    pad = 14
    cols, rows = 3, 2
    sw = pad + cols * (tw + pad)
    sh = header_h + pad + rows * (th + cell_hdr + pad)
    canvas = np.full((sh, sw, 4), (0.06, 0.08, 0.11, 1.0), dtype=np.float32)
    fill_rect(canvas, 0, 0, sw, header_h, (0.09, 0.12, 0.18, 1.0))

    total_kb = sum(
        (ASSETS_ROOT / rel).stat().st_size / 1024.0
        for rel, *_ in panel_specs
        if (ASSETS_ROOT / rel).exists()
    )
    draw_text(
        canvas,
        f"3X MOUNTAIN VIEW CAMPUS EXPANSION - 6 NEW LANDMARKS EEVEE QA ({total_kb/1024.0:.2f}MB TOTAL)",
        18,
        20,
        scale=2,
        color=(0.98, 0.99, 1.0, 1.0),
    )

    for idx, (rel, title, azim, elev, accent) in enumerate(panel_specs):
        glb = ASSETS_ROOT / rel
        c, r = idx % cols, idx // cols
        x0 = pad + c * (tw + pad)
        y0 = header_h + pad + r * (th + cell_hdr + pad)
        fill_rect(canvas, x0, y0, x0 + tw, y0 + cell_hdr, (0.12, 0.15, 0.22, 1.0))
        fill_rect(canvas, x0, y0, x0 + 8, y0 + cell_hdr, accent)
        draw_text(canvas, title, x0 + 16, y0 + 6, scale=2, color=(0.98, 0.99, 1.0, 1.0))

        if not glb.exists():
            draw_text(canvas, "MISSING GLB", x0 + 16, y0 + 28, scale=1, color=(0.98, 0.35, 0.35, 1.0))
            continue

        reset_scene()
        imported = import_glb(glb)
        stats = compute_scene_mesh_stats(imported)
        bmin = Vector(stats["bbox_min"])
        bmax = Vector(stats["bbox_max"])
        ctr = Vector(stats["center"])

        setup_world(outdoor=True)
        configure_eevee(samples=samples, res_x=tw, res_y=th)
        build_studio_rig(
            ctr,
            bmin,
            bmax,
            azim_deg=azim,
            elev_deg=elev,
            fov_deg=34.0,
            fill_ratio=0.96,
            outdoor=True,
            add_floor=True,
            floor_z=0.0,
        )
        img = render_view_to_array(str(tmp_dir / f"exp_lm_{idx}.png"))

        res = results_by_file.get(rel, {})
        d = stats["dims"]
        min_z = stats["bbox_min"][2]
        n_mats = len(res.get("stats", {}).get("gltf_materials", []))
        status = res.get("status", "?")
        sub_color = (0.45, 0.95, 0.65, 1.0) if status == "PASS" else ((0.98, 0.82, 0.35, 1.0) if status == "WARN" else (0.98, 0.35, 0.35, 1.0))
        sub = (
            f"{stats['tris']} TRIS | {d[0]:.1f}X{d[1]:.1f}X{d[2]:.1f}M | "
            f"MINZ={min_z:+.3f}M | {n_mats} MATS | {res.get('size_kb', 0):.0f}KB | {status}"
        )
        draw_text(canvas, sub, x0 + 16, y0 + 28, scale=1, color=sub_color)
        canvas[y0 + cell_hdr:y0 + cell_hdr + th, x0:x0 + tw] = img

    out = PREVIEWS_DIR / "qa_expanded_landmarks.png"
    save_png_topdown(canvas, out, mirror_dir)
    outputs.append(str(out))
    return outputs


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------

def parse_args():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []
    parser = argparse.ArgumentParser(description="Workspace Royale QA Validator & EEVEE Preview Renderer")
    parser.add_argument(
        "--category",
        choices=["all", "characters", "weapons", "utilities", "map", "office_props", "expanded_landmarks", "glider_qa", "office_qa", "loot_chest_qa", "twohanded_qa", "expanded_landmarks_qa"],
        default="all",
    )
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--json-out", type=str, default=None)
    parser.add_argument("--mirror-dir", type=str, default=None)
    parser.add_argument("--samples", type=int, default=24)
    return parser.parse_args(argv)


def main():
    args = parse_args()
    if args.category == "all":
        categories = ["characters", "weapons", "utilities", "map", "office_props", "expanded_landmarks"]
    elif args.category == "glider_qa":
        categories = ["characters"]
    elif args.category == "office_qa":
        categories = ["office_props", "map"]
    elif args.category == "loot_chest_qa":
        categories = ["utilities"]
    elif args.category == "twohanded_qa":
        categories = ["characters"]
    elif args.category == "expanded_landmarks_qa":
        categories = ["expanded_landmarks"]
    else:
        categories = [args.category]
    mirror_dir = Path(args.mirror_dir) if args.mirror_dir else None

    all_results = []
    results_by_file = {}

    print("=" * 78)
    print(f"WORKSPACE ROYALE QA AUDITOR | category={args.category} ({categories}) | Blender {bpy.app.version_string}")
    print("=" * 78)

    for cat in categories:
        print(f"\n--- [{cat.upper()}] ---")
        for spec in ASSET_SPECS[cat]:
            res = validate_asset(cat, spec)
            all_results.append(res)
            results_by_file[spec["file"]] = res
            st = res["stats"]
            tris = st.get("tris", 0)
            dims = st.get("dims", [0, 0, 0])
            min_z = st.get("bbox_min", [0, 0, 0])[2]
            print(
                f"  [{res['status']:4s}] {res['file']:40s} | {tris:6d} tris | "
                f"{res['size_kb']:7.1f} KB | {dims[0]:.2f}x{dims[1]:.2f}x{dims[2]:.2f}m (minZ={min_z:+.2f})"
            )
            if "glide_hands" in st:
                gh = st["glide_hands"]
                print(
                    f"         GLIDE HANDS: half_span={gh['half_span_m']:.4f}m | drift={gh['max_drift_m']*1000:.2f}mm | "
                    f"mid_3js={gh['midpoint_threejs']}"
                )
            if "twohand_grip" in st:
                th_parts = []
                for k, v in st["twohand_grip"].items():
                    extra = f" ang={v['aim_max_angle_deg']:.2f}deg" if "aim_max_angle_deg" in v else ""
                    th_parts.append(f"{k}:err={v['max_err_mm']:.2f}mm{extra}")
                print(f"         TWOHAND GRIP: {' | '.join(th_parts)}")
            for err in res["errors"]:
                print(f"         ERROR: {err}")
            for warn in res["warnings"]:
                print(f"         WARN : {warn}")

    # Compute total asset footprint across ALL .glb files under public/assets/
    all_glbs = sorted(ASSETS_ROOT.rglob("*.glb"))
    total_bytes_all = sum(p.stat().st_size for p in all_glbs)
    existing_count_all = len(all_glbs)
    total_mb_all = total_bytes_all / (1024 * 1024)
    budget_mb = 22.0

    cat_bytes = sum(r["size_bytes"] for r in all_results)
    cat_mb = cat_bytes / (1024 * 1024)
    n_pass = sum(1 for r in all_results if r["status"] == "PASS")
    n_warn = sum(1 for r in all_results if r["status"] == "WARN")
    n_fail = sum(1 for r in all_results if r["status"] == "FAIL")

    rendered_files = []
    if not args.validate_only:
        PREVIEWS_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="wr_qa_") as td:
            tmp_dir = Path(td)
            if args.category == "glider_qa":
                rendered_files.extend(render_glider_and_jump_qa(results_by_file, args.samples, mirror_dir, tmp_dir))
            elif args.category == "office_qa":
                rendered_files.extend(render_office_interiors_qa(results_by_file, args.samples, mirror_dir, tmp_dir))
            elif args.category == "loot_chest_qa":
                rendered_files.extend(render_loot_chest_qa(results_by_file, args.samples, mirror_dir, tmp_dir))
            elif args.category == "twohanded_qa":
                rendered_files.extend(render_twohanded_weapons_qa(results_by_file, args.samples, mirror_dir, tmp_dir))
            elif args.category == "expanded_landmarks_qa":
                rendered_files.extend(render_expanded_landmarks_qa(results_by_file, args.samples, mirror_dir, tmp_dir))
            else:
                if "characters" in categories:
                    rendered_files.extend(render_characters_sheets(results_by_file, args.samples, mirror_dir, tmp_dir))
                    rendered_files.extend(render_glider_and_jump_qa(results_by_file, args.samples, mirror_dir, tmp_dir))
                    rendered_files.extend(render_twohanded_weapons_qa(results_by_file, args.samples, mirror_dir, tmp_dir))
                if "weapons" in categories:
                    rendered_files.extend(render_weapons_sheets(results_by_file, args.samples, mirror_dir, tmp_dir))
                if "utilities" in categories:
                    rendered_files.extend(render_utilities_sheets(results_by_file, args.samples, mirror_dir, tmp_dir))
                    rendered_files.extend(render_loot_chest_qa(results_by_file, args.samples, mirror_dir, tmp_dir))
                if "map" in categories:
                    rendered_files.extend(render_map_sheets(results_by_file, args.samples, mirror_dir, tmp_dir))
                if "office_props" in categories:
                    rendered_files.extend(render_office_interiors_qa(results_by_file, args.samples, mirror_dir, tmp_dir))
                if "expanded_landmarks" in categories:
                    rendered_files.extend(render_expanded_landmarks_qa(results_by_file, args.samples, mirror_dir, tmp_dir))

    print("\n" + "=" * 78)
    print(
        f"SUMMARY ({args.category}): PASS={n_pass} WARN={n_warn} FAIL={n_fail} | "
        f"Category Size={cat_mb:.2f} MB | Total Assets On Disk ({existing_count_all} GLBs)={total_mb_all:.2f} MB / {budget_mb:.2f} MB"
    )
    if total_mb_all > budget_mb:
        print(f"ERROR: TOTAL ASSET PAYLOAD EXCEEDS {budget_mb:.1f} MB BUDGET!")
    if rendered_files:
        print("RENDERED PREVIEWS:")
        for rf in rendered_files:
            print(f"  - {rf}")
    print("=" * 78)

    report = {
        "blender_version": bpy.app.version_string,
        "categories": categories,
        "summary": {
            "pass": n_pass,
            "warn": n_warn,
            "fail": n_fail,
            "category_mb": round(cat_mb, 3),
            "total_disk_files": existing_count_all,
            "total_disk_mb": round(total_mb_all, 3),
            "budget_ok": total_mb_all <= budget_mb,
        },
        "rendered_previews": rendered_files,
        "assets": all_results,
    }
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

    if n_fail > 0 or total_mb_all > budget_mb:
        sys.exit(1)


if __name__ == "__main__":
    main()

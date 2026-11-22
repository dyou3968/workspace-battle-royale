# Workspace Royale

**Live Demo:** [https://workspace-battle-royale.davidyou.com](https://workspace-battle-royale.davidyou.com)

A 3D third-person Battle Royale set across a **3× Mountain View Googleplex** campus, built with **Three.js + TypeScript + Vite** and **50 custom Blender `.glb` assets**. Sky-drop unarmed from 135m, crack open Tier 1–3 Loot Chests, wield bespoke skinned weapons, and unleash signature Product AI Ultimates to outlast autonomous Workspace rivals.

## 6 Workspace Product Icon AIs & Ultimates (`[Q]` · 100 Mana)

All 6 embodied 3D Workspace Product Icon AIs share balanced base stats with a distinct signature Ultimate:

| Product AI | Ultimate (`[Q]`) | Effect |
| --- | --- | --- |
| **Gmail AI** | *Reply-All Barrage* | Launches 6 homing explosive priority projectiles targeting up to 3 nearby rivals (34 splash damage each, 5m blast). |
| **Drive AI** | *Access Revoked* | Deploys a 12m Restricted Access Guardrail Dome (6s) that blocks enemy fire, knocks unauthorized foes outward, silences Ultimates/channels (3s), and grants +40 Shield. |
| **Calendar AI** | *Hard Stop* | Projects a 20m chrono-field (6s) slowing enemy movement (-65%) and fire rate (-55%) while granting you +40% speed and +45% fire rate. |
| **Chat AI** | *@all Ping Overload* | Emits a 28m emerald shockwave dealing 45 instant damage, draining 35 enemy Mana, and revealing all living opponents through cover and on the minimap (8s). |
| **Slides AI** | *Executive Spotlight* | Fires a piercing 85m golden orbital projection beam down your crosshair dealing 85 damage plus heavy knockback to every rival in line. |
| **Docs AI** | *Version History* | Rewinds smoothly back to your 4s-ago position, restoring `max(current, saved)` Health & Shield, auto-reloading, and emitting a 12m Redline Pulse (35 damage). |

## 5 Bespoke Skinned Weapons & Tier 1–3 Loot Chests

Combatants drop in unarmed and gear up from **Tier 1 Common Supply**, **Tier 2 Rare Tech**, and **Tier 3 Epic Vault** chests (plus 3 aerial Supply Drops) across **Common**, **Rare**, and **Epic** rarities:

- **Vanguard M4** — *Arctic Apex* (Assault Rifle · 30-round auto, 125m range)
- **Breaker 12G** — *Hazard Forge* (Tactical Shotgun · 8-pellet spread, devastating close-quarters burst)
- **Vector-9** — *Cyber Pulse* (SMG / PDW · high-RPM 36-round shredder)
- **Longbow .308** — *Shoreline Viper* (Marksman Sniper · 4× scope overlay, 2.0× headshot crits, 220m range)
- **Nova GL-40** — *Hypernova Prism* (Ordnance Launcher · arcing 6.5m splash, 2.4× cover damage)

**Tactical Utilities:** `Shield Cell`, `Aegis Shield Jug`, `Field Medkit`, `Mana Elixir`, `Hard-Light Cover`, and `Impulse Booster`.

## 4 Play Modes

- **Battle Royale** (`Classic 20`) — 20 Product AIs, 135m sky-drop, 5 closing storm phases, Tier 1–3 Loot Chests, and 3 Supply Drops.
- **Blitz Royale** (`Fast Paced`) — 16 Product AIs, 1.8× faster storm cycles, upgraded Tier 2–3 chests everywhere, +12% move speed, and +65% Mana regen.
- **Sniper Showdown** (`Longbow Only`) — 16 Product AIs armed exclusively with *Shoreline Viper* Longbow .308 rifles alongside Impulse Boosters, Hard-Light Cover, and Shields.
- **Campus Free Roam** (`No Storm`) — Storm-free tour of the entire 3× Googleplex with 100 starting Mana, 2.2× Mana regen, Tier 2–3 chests, and 6 Intern sparring bots.

## 3× Mountain View Googleplex Arena

- **`600m × 380m` Campus Scale** built from **50 custom Blender `.glb` models** (`public/assets/`): 6 rigged Product AI characters, 5 bespoke skinned weapons, 9 utilities/chests/drops, and 30 campus buildings, parks, and props.
- **Walkable Hollow B40–B43 Interiors:** Enter Buildings 40–43 stocked with desk pods, conference pods, microkitchen bars, lounge nooks, and whiteboard walls.
- **Signature Landmarks & Park Cover:** Stan the T-Rex, Gradient Canopy, Orb Plaza, Skybridge, Volleyball Court, Shoreline Amphitheatre, Charleston Campus, Alta Complex, Athletic Field, **Art Gardens**, **Outdoor Gyms**, and Google Pergolas.
- **Tactical Map (`[M]`):** Toggle the full-campus top-down tactical map alongside the live corner minimap.

## Controls

| Action | Input |
| --- | --- |
| Move / Steer Glider | `WASD` |
| Sprint / Sky Dive | `Shift` |
| Crouch & Tighten Aim | `C` / `Ctrl` |
| Jump | `Space` |
| Fire / Use Item | `LMB` |
| ADS / Sniper 4× Scope | `RMB` |
| Reload Weapon | `R` |
| Product Ultimate | `Q` |
| Open Chest / Loot | `E` |
| Hotbar Slots | `1–5` / Scroll |
| Tactical Map | `M` |
| Pause / Back | `Esc` |

## Local Development

```bash
npm install
npm run dev
```

Open `http://localhost:5173`.

### Production Build

```bash
npm run build
```

Outputs the static bundle and all 50 `.glb` assets into `dist/`.

### Rebuilding 3D Assets (Optional, requires Blender)

```bash
npm run assets:build
```

Regenerates all 50 runtime `.glb` models in `public/assets/` from `scripts/blender/*.py`.

## Cloudflare Pages Continuous Deployment

Configured via [`wrangler.toml`](wrangler.toml) (`pages_build_output_dir = "dist"`) and [`public/_headers`](public/_headers) (revalidated HTML & `.glb` models, immutable caching for hashed Vite JS/CSS bundles):

- **Production branch:** `main` — every push to `main` automatically triggers a Cloudflare Pages build (`npm run build` -> `dist`) and deploys live to **`https://workspace-battle-royale.davidyou.com`**.

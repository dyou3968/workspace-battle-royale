# Google Workspace Battle Royale — Game Design Document

## 1. Concept
A **3D third-person Battle Royale** (Fortnite-style) set in the **Googleplex**. Players drop in as anthropomorphic/stylized **Google Workspace Products**—each with a distinct look and a **product-specific Ultimate ability**—while scavenging a **shared, product-agnostic arsenal** of guns, shields, and utility items across **3 rarity tiers**.

## 2. Playable Product Heroes & Ultimates
Every player chooses a Google Workspace product identity before dropping in. All heroes share base Health (`100`), Shield capacity (`100`), and Mana (`100`), plus a signature **Ultimate** (costs Mana / Ultimate charge):

| Product Hero | Visual Identity | Ultimate Ability |
| :--- | :--- | :--- |
| **Gmail** | Crisp white envelope chassis with signature red/blue/green/yellow accents | **Reply-All Barrage** — Launches a homing volley of explosive high-priority envelopes at nearby enemies in a wide arc. |
| **Google Drive** | Geometric tri-color prism core (blue/yellow/green) with floating shard accents | **Cloud Vault Bastion** — Drops an indestructible floating fortress shield dome around the player that rapidly regenerates Shield & Mana for 6s and knocks back enemies. |
| **Google Calendar** | Crisp blue/white calendar grid body with glowing `31` emblem | **Hard Stop (Time Block)** — Projects a massive stasis sphere that slows enemies and projectiles inside by 75% while boosting your fire rate and movement speed. |
| **Google Chat** | Emerald green dual-bubble visor & sleek courier frame | **@all Ping Overload** — Emits a shockwave pulse that reveals all enemies through walls, silences their abilities, and deals instant disruptor damage in a large radius. |
| **Google Slides** | Golden amber presentation deck frame with glowing projection lens | **Executive Spotlight** — Fires a piercing orbital presentation beam along your aim vector, dealing heavy damage and blinding/pushing back anyone caught in the deck. |

## 3. Core Stats & Resources
- **Health (HP):** `0–100` (red/green bar). Reaching `0` eliminates the player.
- **Shield (SHD):** `0–100` (cyan bar). Absorbs incoming damage before Health. Replenished via Shield Potions & Shield Cells.
- **Mana (MP):** `0–100` (purple/blue bar). Regenerates slowly over time and via Mana Elixirs; spent on **Product Ultimates** and active utility gear.

## 4. Rarity Tiers (3 Levels)
All lootable weapons, shields, and items spawn across 3 rarities:

| Tier | Name | Color | Stat Scaling |
| :--- | :--- | :--- | :--- |
| 1 | **Common** | Gray (`#9aa0a6`) | Baseline (`1.0x`) |
| 2 | **Rare** | Blue (`#4285f4`) | `+25%` damage / potency, faster reload |
| 3 | **Epic** | Purple (`#a142f4`) | `+55%` damage / potency, fastest reload & bonus glow FX |

## 5. Product-Agnostic Arsenal (Shared Loot Pool)
Any product hero can equip and swap between any gun, shield, or item found around the Googleplex:

### Guns
- **Vanguard AR** *(Assault Rifle)* — Balanced full-auto mid-range rifle.
- **Breaker Shotgun** *(Pump/Tactical Shotgun)* — 7-pellet close-range burst.
- **Vector SMG** *(Submachine Gun)* — High fire-rate close/mid shredder.
- **Longbow Sniper** *(Precision Rifle)* — High-damage, high-velocity long-range bolt.
- **Nova Launcher** *(Energy Launcher)* — Fires explosive splash-damage orbs (uses Mana or heavy ammo).

### Shields & Utility Items
- **Mini Shield Cell** — Restores `+25` Shield quickly (up to 50 or full on Epic).
- **Full Shield Potion** — Restores `+50`–`+100` Shield depending on rarity.
- **Deployable Aegis Wall** — Spawns a physical translucent energy cover wall in front of the player (Fortnite-style tactical cover!).
- **Medkit** — Restores Health (`+40` / `+65` / `+100` by rarity).
- **Mana Elixir** — Instantly restores Mana (`+40` / `+70` / `+100` by rarity) for rapid Ultimate readiness.
- **Impulse Jump Pad / Dash Boost** — Launches the player high into the air or forward for fast rotations and high-ground plays.

## 6. Arena: The Googleplex (3D Map)
A stylized, vibrant 3D Googleplex campus enclosed by a shrinking Battle Royale Storm:
- **Stan the T-Rex Plaza (Center)** — Iconic T-Rex skeleton sculpture on a stone plaza with high-tier loot chests.
- **B40 & B43 Courtyard** — Multi-level colorful glass buildings, bridges, and primary-colored patio umbrellas providing cover and rooftop vantage points.
- **GBike Corrals** — Clusters of colorful Google bikes along wide campus pathways.
- **Charleston Park & Amphitheater** — Rolling green lawns, trees, stone benches, and terraced seating for flanking.
- **Microkitchen Hubs** — Open-air pavilions stocked with Health/Shield/Mana pickups.
- **Bay View Canopy Wing** — Modern curved-roof pavilion with crisp indoor/outdoor cover lanes.

## 7. Technical Architecture (Playable 3D Web Prototype)
- **Stack:** Vite + TypeScript + Three.js (zero heavy backend needed for v1; runs smoothly at 60 FPS in any browser).
- **Controls:**
  - `WASD` — Move
  - `Mouse` — Aim (Third-Person Over-the-Shoulder camera with Pointer Lock + reticle)
  - `Left Click` — Fire weapon / Use item
  - `Right Click` — Aim Down Sights (ADS zoom)
  - `Space` — Jump
  - `Shift` — Sprint
  - `E` — Pick up nearby loot / open loot chests
  - `1–5` / `Scroll` — Switch inventory slots (Guns, Shields, Utilities)
  - `R` — Reload
  - `Q` — Activate Product Ultimate (requires Mana)
  - `F` — Quick-deploy Aegis Cover Wall (if held) / Quick-use Shield
- **Game Loop:** Hero Select -> Drop into Googleplex with 11 AI Product Bots -> Loot, Fight, Build Cover, Use Ultimates, Stay in the Safe Zone -> Victory Royale or Elimination Summary.

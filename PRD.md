# Product Requirements Document (PRD) — Workspace Royale v2 (High-Fidelity Edition)

**Status:** Draft for Product Review (Phase 1 of 3: Product Spec → Technical Design → Prototype Build)  
**Target Experience:** High-Fidelity 3D Third-Person Battle Royale in the Browser  
**Arena:** The Googleplex (Mountain View, CA)

---

## 1. Problem Statement & Product Goals
The v0.1 prototype validated the core gameplay loop (third-person combat, shrinking storm, 3 rarity tiers, Workspace product Ultimates, product-agnostic arsenal), but its primitive low-poly geometry reads as blocky/robotic ("Roblox-like").

**v2 Product Goal:** Elevate *Workspace Royale* into a **high-fidelity, realistic-feeling 3D third-person Battle Royale** featuring:
1. **Rich, human-like playable characters** with smooth high-vertex anatomy wearing authentic **Google Workspace product-branded apparel** (shirts, hoodies, techwear, lanyards).
2. **Realistic tactical weapons, shields, and gadgets** with detailed silhouettes, PBR metallic/polymer finishes, optics, muzzle flashes, and satisfying gunplay feedback.
3. **An authentic, atmospheric 3D Googleplex campus** with recognizable Mountain View architecture, landscaping, lighting, and verticality.

---

## 2. Visual Direction & Fidelity Bar
- **Aesthetic Pillar — Stylized Realism (Fortnite / Valorant / Apex-lite):**
  - Anatomically grounded human characters with smooth sculpted forms, natural posture, and expressive animations (not robotic cubes).
  - Physically Based Rendering (PBR) materials: brushed gunmetal, polymer grips, woven cotton/tech-fleece apparel, architectural curtain-wall glass, poured concrete, natural bark/foliage, and sunlit California sky.
  - High visual readability at combat distances (20m–120m): clean character silhouettes, distinct product shirt branding, crisp lighting contrast, and diegetic rarity/status effects.

---

## 3. Playable Characters & Product Identity
Players embody human Googleplex competitors whose **apparel and Ultimate ability** represent a Google Workspace product, while all weapons and utility gear remain **product-agnostic**.

### Character Design Requirements
- **Human-Like Proportions & High Vertex Richness:** Smoothly sculpted head, hair, face/expression cues, articulated neck/shoulders/arms/hands/legs, realistic clothing folds/layering, sneakers, and a Googleplex badge lanyard.
- **Product Branding:** High-resolution Workspace product logo prominently printed across the chest and back of each character's shirt/hoodie/jacket, accented by subtle product-themed trim and wrist/backpack tech for their Ultimate.
- **Full Animation Set:** Idle breathing, jogging, sprinting, strafing, aiming down sights (weapon raised to shoulder), firing recoil, reloading, jumping/landing, consuming shields/medkits, and casting Ultimates.

### Initial Product Roster (5 Heroes — Expandable)
| Product Identity | Apparel & Human Look | Product Ultimate (`Q`) | Role Fantasy |
| :--- | :--- | :--- | :--- |
| **Gmail** | Crisp white/red athletic tee with bold Gmail emblem, courier sling vest, tactical joggers | **Reply-All Barrage** — Launches a fan of homing explosive priority projectiles | High-pressure offensive striker |
| **Google Drive** | Slate & forest-green tech hoodie with Drive emblem, armored cloud-pack | **Cloud Vault Bastion** — Deploys a fortified energy dome, knocking rivals back & restoring Shield/HP | Defensive anchor / zone holder |
| **Google Calendar** | Royal blue performance polo/jacket with Calendar `31` logo, glowing chrono-wristband | **Hard Stop (Time Block)** — Casts a 20m time-dilation field slowing rivals while boosting your speed & fire rate | Tempo controller / duelist |
| **Google Chat** | Emerald zip jacket over branded Chat tee, tactical comms headset | **@all Ping Overload** — Disruptor shockwave dealing burst damage, draining enemy Mana & revealing all foes through walls | Recon / anti-ability flanker |
| **Google Slides** | Charcoal blazer-hoodie over amber Slides tee, shoulder projector rig | **Executive Spotlight** — Fires a piercing golden orbital beam down your aim line with knockback | Precision line-of-sight finisher |

---

## 4. Core Gameplay, Stats & Combat Mechanics

### Player Vitals & Resources
- **Health (0–100):** Primary survivability; `0` = eliminated.
- **Shield (0–100):** Energy overshield absorbing damage before Health; distinct blue crack/shatter visual + audio feedback when broken.
- **Mana (0–100):** Passively regenerates + boosted by Mana Elixirs and eliminations; powers **Product Ultimates** and high-tech utility gear.

### Combat Feel & Gunplay Upgrades
- **Over-the-Shoulder Third-Person Camera:** Smooth shoulder offset, sprint FOV pull-back, Right-Click ADS zoom, and dedicated scope vignette/zoom for Sniper rifles.
- **Locational Damage (Headshot Crits):** Headshots deal `1.6x–2.0x` damage with distinct gold damage numbers and crisp audio feedback.
- **Directional Damage Indicator:** HUD arc flashes toward incoming fire so players immediately know where they're being flanked from.
- **Tactical Movement:** Walk, Sprint (`Shift`), Jump (`Space`), Crouch (`C` / `Ctrl`) for tighter bloom and taking low cover behind courtyard planters/tables.
- **5-Slot Product-Agnostic Inventory:** Any player can carry and swap any combination of guns, shields, and utilities across **3 Rarity Tiers**.

### Rarity Tiers (3 Levels)
| Tier | Label | Accent | Stat Scaling & Visual Cues |
| :--- | :--- | :--- | :--- |
| 1 | **Common** | Steel Gray | `1.0x` baseline stats; clean matte tactical finish |
| 2 | **Rare** | Cobalt Blue | `1.25x` damage/potency, faster reload; subtle blue optic/rail accents |
| 3 | **Epic** | Royal Purple | `1.55x` damage/potency, fastest reload; glowing violet tactical trim & enhanced tracers |

### Product-Agnostic Arsenal
- **Guns (Realistic Silhouettes & Materials):**
  1. **Vanguard M4 (Assault Rifle)** — Full-auto mid-range carbine with holographic sight.
  2. **Breaker 12G (Tactical Shotgun)** — Heavy close-quarters spread shotgun.
  3. **Vector-9 (Submachine Gun)** — Rapid-fire close/mid-range shredder.
  4. **Longbow .308 (Marksman Sniper)** — High-velocity precision rifle with magnified scope.
  5. **Nova GL-40 (Ordnance Launcher)** — Arcing splash-damage launcher (uses Mana per shot).
- **Shields & Utility Items:**
  1. **Shield Cell** — Quick tactical shield recharge (`+25`–`+40` by rarity).
  2. **Aegis Shield Jug** — Heavy shield restore (`+65`–`+100` by rarity).
  3. **Deployable Hard-Light Cover** — Sleek curved tactical energy barricade for instant outdoor cover.
  4. **Field Medkit** — Restores Health (`+45`–`+100` by rarity).
  5. **Mana Elixir** — Rapidly refills Mana for Ultimates (`+50`–`+100` by rarity).
  6. **Impulse Jump Booster** — Launches player onto B40/B43 rooftops or out of ambushes.

---

## 5. Arena Requirements: The Googleplex (Realistic Edition)
A sunlit Silicon Valley campus (~250m × 250m) with layered sightlines, interior/exterior transitions, vertical roof play, and iconic Mountain View landmarks:
- **Stan the T-Rex Plaza (Center):** High-detail anatomical T-Rex skeleton sculpture on a landscaped stone plaza surrounded by curved benches, native California planters, and high-tier loot spawns.
- **B40 & B43 Courtyard:** Multi-story architectural glass-and-steel buildings with realistic window mullions, exterior stairs/ramps to rooftop decks, parapet cover, and fabric-ribbed primary-colored Google patio umbrellas over bistro tables.
- **Bay View Canopy Wing (North):** Sweeping curved architectural canopy inspired by the iconic Mountain View dragonscale roof, tall structural columns, glazed partitions, and sunlit plaza approaches.
- **Charleston Park & Amphitheater (South):** Gently contoured grassy terrain, multi-branch California live oaks and shrubs, curved stone amphitheater terraces, and a reflective water feature/bridge.
- **Microkitchen Pavilions (East & West):** Sleek wood-and-glass open-air pavilions with espresso bars and reliable consumable spawns.
- **GBike Corrals:** Detailed steel racks lined with realistic multi-colored Google bicycles (spoked wheels, frames, handlebars, front baskets).
- **Shrinking Battle Royale Storm:** Atmospheric translucent energy curtain with glowing perimeter ground ring, minimap next-zone indicator, and escalating out-of-zone damage.

---

## 6. Match Loop, AI Opponents & UX
- **Pre-Match Lobby:** Interactive 3D character showcase (rotate/inspect the realistic human hero & branded shirt), Ultimate preview, and quick drop-in.
- **Match Structure:** 12–16 players (Solo vs. AI Workspace Bots) competing across 5 storm phases (~4–7 min match length).
- **Smarter AI Bots:** Bots strafe, use cover, upgrade to rarer weapons, heal/shield behind obstacles, rotate ahead of the storm, fight each other dynamically, and deploy their product Ultimates.
- **HUD & Audio:** Clean tactical HUD (health/shield/mana, hotbar with weapon silhouettes, minimap with next safe zone, kill feed, directional damage indicators) paired with realistic gunfire, shell/impact audio, footsteps, and spatialized Ultimate cues.

---

## 7. Open Product Decisions to Align On Before Technical Design
1. **Visual Realism Direction:** Stylized-realism (Fortnite/Valorant clean sculpted humans + vibrant Silicon Valley palette) vs. grittier semi-realistic tactical (PUBG/Warzone-lite)?
2. **Character Selection Model:** Dedicated human persona per Workspace product, OR pick any human avatar + equip any Workspace product shirt/Ultimate separately?
3. **Hero Roster Size for v2:** Stick with the **5 core products** (Gmail, Drive, Calendar, Chat, Slides), or expand right away to include **Docs, Sheets, and Meet**?
4. **Battle Royale Depth Features:** Which mechanics belong in v2 right now?
   - Headshot crits & directional damage indicators
   - Crouching / low-cover peeking
   - Channel/use timers on Medkits & Shield Jugs (e.g., 1.5s–3s like Fortnite) vs. instant use
   - Glider / sky drop-in over the Googleplex at match start vs. ground spawn
   - Keep tactical Deployable Cover items vs. adding Fortnite-style freeform ramp/wall building
5. **Performance & Asset Footprint Target:** Keep fast-loading web app (~5–20 MB of rigged `.glb` 3D character/weapon models & PBR textures targeting smooth 60 FPS on MacBook browser)?

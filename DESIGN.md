# deskbar Design System

## 1. Atmosphere & Identity

deskbar is a quiet, always-on command center that can become a cinematic window when
the calendar recedes. Utility chrome stays calm and legible; the center scene carries
the wonder. Its signature is **credible atmosphere at ultrawide scale**: large cropped
focal forms, deep negative space, material texture, and light that changes with the
real time of day. A scene must read as finished artwork in a frozen frame. Motion may
deepen the illusion, but must never disguise flat geometry or unfinished material.

The visual references supplied on 2026-08-03 are the scene-quality contract. They are
directional rather than source assets: preserve their scale, light, depth, and material
specificity without copying their exact imagery.

## 2. Color

Application colors are Python RGB tuples exposed through `deskbar.ui.theme.C`.

| Role | Token | Dark | Light | Usage |
|---|---|---:|---:|---|
| Surface/primary | `bg` | `(0, 0, 0)` | `(242, 240, 235)` | Screen and panel background |
| Surface/secondary | `card` | `(30, 30, 30)` | `(255, 255, 255)` | Controls and clock cards |
| Text/primary | `text` | `(255, 255, 255)` | `(26, 26, 26)` | Time and primary information |
| Text/secondary | `text2` | `(212, 212, 212)` | `(70, 70, 70)` | Dates and supporting information |
| Text/muted | `muted` | `(186, 186, 186)` | `(122, 120, 114)` | Sync and tertiary information |
| Border/default | `panel_line` | `(70, 70, 70)` | `(198, 194, 186)` | Three-column separation |
| Accent/time | `now` | `(255, 138, 101)` | `(200, 88, 56)` | Current-time emphasis |
| Status/success | `ok` | `(60, 220, 170)` | `(20, 140, 110)` | Healthy sync state |
| Status/warning | `warn` | `(255, 105, 105)` | `(178, 44, 44)` | Errors and over-pace state |

### Cinematic planet-horizon palette

| Role | Night | Dawn | Day | Usage |
|---|---:|---:|---:|---|
| Zenith | `(2, 7, 18)` | `(18, 25, 48)` | `(32, 67, 105)` | Upper sky |
| Horizon | `(8, 23, 46)` | `(86, 104, 132)` | `(111, 157, 190)` | Atmosphere above cloud sea |
| Planet shadow | `(5, 9, 18)` | `(20, 27, 41)` | `(38, 54, 67)` | Unlit giant-planet body |
| Planet lit bands | `(54, 79, 103)` | `(112, 126, 142)` | `(150, 169, 178)` | Baked gas bands and surface relief |
| Rim light | `(116, 192, 255)` | `(178, 221, 255)` | `(208, 239, 255)` | Thin atmospheric edge light |
| Cloud highlight | `(88, 126, 159)` | `(179, 191, 203)` | `(222, 231, 234)` | Baked cloud-sea crests |

Scene colors form a continuous ramp between the three anchors. Pure saturated blue is
reserved for the atmospheric rim; broad surfaces remain restrained so the result does
not read as neon science-fiction UI.

## 3. Typography

| Level | Size | Weight | Usage |
|---|---:|---|---|
| Clock | 96px card height | Light | Primary glanceable time |
| Display data | 58px | Medium | Temperature and exceptional values |
| Section title | 26px | Medium | City and page headings |
| Control | 20–22px | Regular | Touch controls and view labels |
| Body | 18–20px | Regular | Events and status text |

- Primary: Noto Sans CJK / PingFang-compatible fallback.
- Large numerals use the light face; CJK emphasis uses medium, never heavy bold.
- Cinematic scenes contain no decorative labels, captions, or fake HUD typography.

## 4. Spacing & Layout

- Logical canvas: **1920×480**; output is rotated for the physical 480×1920 panel.
- Left utility panel: `x=0..400`.
- Center scene viewport: `x=402..1520`, `y=8..480` (**1118×472**).
- Right utility panel: `x=1540..1900`, with 20px outer breathing room.
- Base spacing unit: 4px. Touch targets remain at least 48px.
- Scene masters are baked wider than the viewport when parallax needs overscan; no
  transparent edge may enter the visible crop.
- Focal objects may be deliberately cropped by the viewport. Cropping must communicate
  scale, not look like an asset accidentally clipped by its bounding box.

## 5. Components

### Utility chrome

- **Structure**: fixed left and right information panels around the center view.
- **Variants**: dark and warm-light themes.
- **States**: normal, stale, syncing, warning, sleeping.
- **Motion**: only information-bearing transitions such as flip-clock changes.
- **Accessibility**: high contrast on the real low-gamut panel; touch targets ≥48px.

### Cinematic scene

- **Structure**: one opaque baked base plus only the minimum independent layers needed
  for depth or time-based motion.
- **Authored canvas**: production assets are **1240×472**, baked at **2480×944** or
  greater and downsampled once. Opaque bases cover the full crop; movable overlays keep
  fully transparent borders and enough overscan that no edge can enter the viewport.
- **Asset lifecycle**: only the active scene owns decoded surfaces. Switching scenes
  closes the previous renderer and releases its assets; decoded assets for one active
  renderer must remain at or below **48 MiB**.
- **Variants**: night, dawn, day, and dusk interpolation; scene-specific weather response
  only when it reinforces the depicted world.
- **States**: loading must retain the previous complete frame; an unavailable asset is a
  test/build failure, not a degraded geometric fallback.
- **Motion**: restrained camera drift, cloud displacement, light breathing, or orbital
  movement. Every frame must remain compositionally complete.
- **Interaction**: the whole viewport remains the existing `scene_tap` target.
- **Quality gate**: dawn/day/night acceptance renders require human approval before the
  scene joins the default rotation.

#### Preserved scene identities

- `flow`: luminous fiber and wet-ink filaments with layered brush texture.
- `stars`: astrophotographic dust lanes, star depth, and restrained meteor light.
- `ridges`: atmospheric mountain matte with rock material, fog, and moving light.
- `fireflies`: grounded dusk meadow with grass occlusion, haze, and depth-sorted glows.
- `fish`: original sumi-e fish, paper/water wash, wake, and weather-dependent depth.
- `aurora`: volumetric curtains above a dimensional sky and landscape.
- `train`: original cinematic pixel train with window light and multi-plane parallax.
- `runner`: original cinematic pixel adventurer and obstacles in a deep pixel world.
- `ink`: paper grain and soft pigment blooms built from authored masks.
- `planet_horizon`: orbital giant-planet horizon with independent body, rim, clouds,
  and haze.

### Planet horizon

- **Structure**: deep sky, cropped giant planet, thin rim atmosphere, distant cloud sea,
  and near cloud silhouette.
- **Composition**: planet occupies roughly half the scene width and presses into the
  upper frame; the cloud horizon remains low enough to preserve orbital scale.
- **Material**: gas bands, terminator softness, cloud relief, and atmospheric scattering
  are baked at supersampled resolution. Runtime primitives may not form the focal object.
- **Motion**: deterministic medium-cinematic motion keeps every layer independent. The
  body moves **±16 px** horizontally over **96 s** and **±6 px** vertically over
  **73 s**; far cloud moves **±28 px** over **74 s**; near cloud moves **±48 px** over
  **49 s**; rim luminance breathes **±8%** over **16 s**; haze breathes **±10%** over
  **21 s**.

## 6. Motion & Interaction

| Type | Period | Usage |
|---|---:|---|
| Scene transition | 600–900ms | Cross-fade between complete scenes |
| Atmospheric drift | 49–240s | Cloud, focal-body, and haze displacement |
| Light breathing | 12–24s | Very small rim/glow modulation |
| Parallax sway | 120–300s | Sub-pixel camera presence |

- Ambient movement is slow enough that 10–15 rendered updates per second remain smooth.
- Position and opacity are the only routine runtime changes; material, blur, bloom,
  shadow, and depth-of-field are baked into assets.
- Motion cannot resemble a screensaver effect, loading animation, or game obstacle loop.
- Scene time is deterministic for a given timestamp so screenshots and tests reproduce.
- Motion remains clearly visible but composed: fixed 0/5/15-second crops must show
  depth-bearing change without exposing sprite bounds or leaving an incomplete frame.

## 7. Depth & Surface

Utility UI uses tonal separation and restrained one-pixel borders. Cinematic scenes use
**baked photographic depth**: atmospheric perspective, occlusion, soft terminators,
volumetric haze, and controlled highlight roll-off. Flat circles, solid polygons,
uniform gradients, and untextured vector silhouettes are prohibited for focal scenery.

Assets are generated at 2480×944 or greater and downsampled once to the 1240×472
production canvas. Alpha sprites must have fully transparent borders; opaque masters
must cover their complete viewport. Fine luminance noise or dithering is retained in
broad gradients to prevent banding on the physical panel.

Every dawn, day, and night frame must retain a focal hierarchy, coherent light direction,
at least three readable depth planes where the identity calls for them, and complete edge
coverage. Non-pixel scenes target RGB standard deviation ≥12 and at least 160 sampled
colors; `planet_horizon` targets ≥18 and 180; `train` and `runner` retain deliberate pixel
palettes with at least 48 colors. These numeric floors detect regressions but never replace
fresh visual review of material, composition, motion, and originality.

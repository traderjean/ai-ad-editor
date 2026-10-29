# The photoreal phone look: making AI frames look like real phone footage

Read this whenever the look is **photoreal phone look**. Every frame is still AI-generated; this guide makes it look filmed on a phone.

## The one-line test

If a frame could be a stock photo or a film still, it's wrong. Real UGC looks like someone propped their phone against the toaster and pressed record.

## 1. Pick one camera mode per shot and name it in the prompt

| Mode | How it looks | Best for |
|---|---|---|
| **Selfie, arm's length** (front camera) | Face fills the upper middle; slight wide-angle stretch; camera just above or below eye level; the shoulder dips toward the arm holding the phone; eyes on the screen, a little below the lens | Hook emotion, relief, talking moments |
| **Propped phone, still** | Phone leaning on a counter or shelf at an odd height, or across the room. The person is off-centre and loosely framed; the camera never moves | Daily struggles, "caught in the moment" |
| **Looking down (POV)** | First person: own hands, feet, plate, wrist. Hands come in from the bottom of the frame | Everyday routines, small physical moments, taking the product |
| **Product held toward the camera** | Arm out, product in the middle, label slightly off-square, real nails and knuckles, the real room behind | Product reveal |
| **Filmed by family** | Someone else holds the phone: wide to medium, from the side, slightly off-level; porch, garden or living room | Older people (the most believable look for 60+) |

Also: the **overhead counter shot**, phone held flat above the counter (a glass of water and the capsules). It's the natural way to show supplements.

## 2. Light: whatever was already in the room

- **Window daylight** is the most common: soft on one side of the face, windows often blown out white.
- **Harsh sun** gives hard shadows across hands and products, and squinting.
- **Overhead ceiling lights** in bathrooms and kitchens: unflattering, shadows under the eyes. Very real for older people.
- **Warm lamp** in the evening, with grainy corners.
- **In the car:** flat light through the windscreen, headrest and seatbelt in frame.
- Never: rim light, softbox glow, a teal-and-orange grade, cinematic contrast.

### The biggest giveaway: phone capture is LOW contrast and LOW saturation

The light in the room can be anything. What gives AI away is rendering it like a film camera: deep blacks, rich colour, punchy contrast. A phone's HDR lifts the shadows, pulls down the highlights and mutes the colour, so the frame looks even, a bit flat and slightly washed out.

- Shadows are never black. You can see detail in dark corners, under cabinets and in hair, even at night.
- Colours are muted: skin, wood and fabric are all slightly desaturated.
- Night footage is brightened, noisy and soft, not dark and contrasty.
- Prompt words: "iPhone Smart HDR look, low contrast, lifted shadows, evenly exposed, flat and slightly washed-out, room lights on, visible detail in the shadows, mild digital noise".
- Words to avoid in the look: "high contrast, deep blacks, crushed shadows, dramatic lighting, single light source, spotlight, moody".
- If a frame still looks too polished, flatten it for free instead of remaking it:
  `ffmpeg -i in.png -vf "curves=all='0/0.05 0.5/0.52 1/0.97',eq=saturation=0.88" out.png`

## 3. Places: lived-in, not styled

- Kitchens with wood cabinets, a fruit bowl, kitchen roll, post, a phone charger.
- Bathroom sink: bottles, a toothbrush cup, the edge of the mirror, a hand towel.
- A bed with a patterned duvet, a couch with a throw, a desk with a water bottle, porch chairs, a supermarket aisle, the car.
- Leave 2 or 3 bits of real clutter in the frame. Nothing arranged.
- Neutral, minimal "aesthetic" rooms with candles read as influencer content, not UGC. Avoid them for older audiences.
- **Keep the background shallow.** A wall, headboard, curtain, fridge or car headrest right behind the person looks real. A long, deep room behind them looks AI. Prompt: "her back is close to the wall, almost no room depth behind her".
- Themed, dressed-set backgrounds ("the old man's den", "the handyman's garage") look fake. Real backgrounds are a bit messy and plain.

## 4. People

- Skin: pores, redness, uneven tone, freckles. Older people: deep wrinkles, age spots, a crepey neck, veins on the hands.
- Hair: flyaways, frizz, grey roots, thinning. Glasses, a headband, sunglasses pushed up.
- Clothes: hoodie, sweatshirt, plain tee, fleece, dressing gown, cardigan. No styled outfits.
- Little or no makeup. Older people look real, not like silver-haired models.

## 5. Acting: small and ordinary

- Everyday actions: sipping water, scrolling a phone, reading a letter, rubbing the neck, staring out of the window.
- Emotion is small: eyes close, a slow breath out, lips pressed together, a hand on the chest, a hand over the face. People look away from the camera far more than into it.
- The best clips have a **mini arc in one take**: normal, then something happens, then the reaction (scrolling, then face in hands). This fits one 8-second clip.
- Big, cartoon reactions are a separate "reaction meme" style. Use them only on purpose, for a hook.

## 6. Imperfections that sell "real" (ask for 2 or 3 per shot, never all of them)

- The person a little off-centre; the top of the head cropped, or too much space above.
- The horizon tilted 2 to 5 degrees.
- Something cut off at the edge (a person half out of frame, a fingertip).
- Gentle handheld sway (selfie and POV); the framing moves a little during the clip.
- Deep phone focus: background mostly sharp, no creamy blur behind faces.
- Mixed light colour (cool window light plus a warm lamp).

## 7. Prompt templates

**Start frame:**
```
Vertical 9:16 smartphone photo, [CAMERA MODE from section 1]. [WHO, exactly as the attached sheet], [SMALL ACTION], [SMALL EXPRESSION].
Setting: [REAL ROOM] with [2-3 CLUTTER ITEMS]. Light: [THE ROOM'S OWN LIGHTS, from section 2]. Real skin texture, [age details]. Casual [clothes].
Imperfect amateur framing: [1-2 IMPERFECTIONS]. Deep phone-camera focus, iPhone Smart HDR look: low contrast,
lifted shadows with visible detail, evenly exposed, slightly flat and washed-out, mild noise. No colour grade.
Full-bleed vertical image filling the whole frame edge to edge, no borders, no bands; face and key prop in the
middle with the scene continuing above and below. Not cinematic, not
studio-lit, no deep blacks, no dramatic single light, no shallow depth of field, no retouching.
```

**Clip:**
```
Shot on an iPhone, [CAMERA MOTION: "held at arm's length with a gentle natural sway" / "phone propped on the
counter, camera completely still" / "looking down, slight walking bob"]. She [ONE ACTION with a mini arc, from section 5]. Small natural
movements, blinks, eyes on the phone screen not the lens. Real-time speed, no slow motion, no camera moves
beyond the handheld drift.
```

## 8. Ready-made shots for an older (60+) character

1. **Bathroom sink, phone propped low on the counter:** at the mirror under a harsh ceiling light, holding a pill bottle and reading the label.
2. **Car selfie:** seatbelt on, flat windscreen light, a serious face.
3. **Kitchen, filmed from across the room:** at the table reading a letter, then picking up the phone and frowning.
4. **Porch chair, filmed by family:** wide side view, reading or drinking a cup of tea.
5. **Overhead counter:** a glass of water and the capsules, her hand reaching in from the bottom.
6. **Looking down at her hands:** rinsing a mug at the kitchen sink, window light on the water.
7. **Selfie relief:** eyes close, a hand on her chest, a slow breath out, a small smile.

## 9. Talking-head reference images (for lip-sync and avatar tools)

**Where winning talking-head ads are filmed, most common first:**
1. **The car, driver's seat, selfie:** seatbelt, headrest, side window, flat daylight. The most common by far.
2. **Kitchen counter:** leaning toward a propped phone, or behind the counter holding the product.
3. **Couch or bed selfie**, often in a hoodie, dressing gown or headband.
4. **Very close selfie:** the face fills the frame, chin or forehead cropped.

**What the real ones have (and AI ones miss):**
- **About to speak, not posing.** Eyebrows up, head tilted, leaning in, lips just parted. A square-on face with closed lips and a faint smile looks like a passport photo.
- **Close.** The face takes a third to half of the frame, with a little stretch from a phone held near. A wide shot of someone sitting far away looks staged.
- Eyes on the lens, so they talk to the viewer.
- Hands below the chin, nothing in front of the mouth (lip-sync needs a clear mouth).
- The same flat, muted, low-contrast phone look.
- Daylight and a plain, light surface behind them (light wall, car interior, headboard). Dark rooms lit by one lamp come out moody and film-like.

**Common failures and fixes:**

| Failure | Fix |
|---|---|
| A phone appears in the frame ("phone propped on the table") | Add "no phone visible in the frame" |
| A fake phone status bar (time, battery) when the prompt says "smartphone" | "A raw frame from her own video, not a screenshot: no phone interface, no status bar" |
| A posed photo smile | An image edit that changes only the expression: "about to talk, lips slightly parted" |
| Camera propped low on a counter looking up | A handheld selfie slightly below eye level |
| "Too professional": crisp detail, rich colour | Ask for the soft detail of a front camera and muted colour; flatten with the ffmpeg line above |
| Gibberish text on papers or fridge magnets | Keep paper out of the background, or "no readable writing" |
| Fixing a too-polished image by using it as the reference | Don't: the new image copies its look. Remake it from a prompt that worked |

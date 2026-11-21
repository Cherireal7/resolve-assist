# Picture plates: a subject cut-out and a filled background

Two small macOS helpers that turn one flat picture into the two layers a "2.5D" picture tile needs
(Motion Studio `DeskStory`, `photo` tiles): the subject on a transparent layer in front, and the
background with the subject painted out behind. With the camera moving, the two layers slide against
each other and the picture gets depth.

They use Apple's Vision framework (the same subject lifting as Photos), so they run offline, need
macOS 14 or newer and the Xcode command line tools, and are not part of the stdlib-only Python core.

```sh
tools/plates/build.sh
```

## 1. `subject`: cut the subject out and fill the hole

```sh
tools/plates/bin/subject picture.jpg outdir name [--pick all|list|1,3] [--dilate 10] [--roi x0,y0,x1,y1] [--fill-black [--black-max 6] [--fade 90]]
```

Writes `name-fg.png` (subject, transparent), `name-bg.png` (subject removed, hole filled with a smooth
push-pull fill) and `name-mask.png`, all at the picture's own size.

- `--pick list` prints the subjects Vision found and exits; `--pick 1,3` keeps only those.
- `--roi` looks for the subject only inside part of the picture (fractions of width and height). Use it
  when Vision grabs too much, for example a laptop along with the cat.
- `--fill-black` also fills the black surround of a round (fisheye) picture, so it can cover a rectangular
  frame; `--black-max` is how dark a pixel must be to count (use a low value when the picture itself has
  dark areas) and `--fade` darkens the filled surround with distance, like a lens edge.

The fill is a blur of the surroundings, not a reconstruction: it only has to survive being mostly hidden
behind the subject while the layers drift a few pixels.

## 2. `plate`: compose the layers for a frame shape

```sh
tools/plates/bin/plate spec.json
```

```json
{"out": "plates", "plates": [
  {"name": "cat-9x16", "bg": "layers/cat-bg.png", "fg": "layers/cat-fg.png", "w": 1296, "h": 2304,
   "bgCrop": [0.0, 0.0, 0.5625], "blur": 3,
   "fgScale": 2.7, "fgRef": [0.5, 0.58], "fgAt": [0.5, 0.67], "sharpen": 0.6, "fgExtend": [0, 280]}],
 "stickers": [{"name": "st-cat", "fg": "layers/cat-fg.png", "max": 1100}]}
```

Per plate it writes `name.jpg` (background), `name-fg.png` (subject on a transparent canvas of the same
size, so the two register exactly) and `name-preview.jpg`.

- `bgCrop`: left, top and width of the background crop as fractions of the picture; the height follows
  the canvas shape.
- `fgScale`, `fgRef`, `fgAt`: scale the subject and put the point `fgRef` (fractions inside the subject
  picture, for example the nose) at `fgAt` on the canvas. Leave all three out to keep the subject where it
  was in the crop. Moving and enlarging the subject is how a square picture fills a tall frame.
- `fgExtend`: carry the subject past the picture's left/right edge by repeating its edge column (pixels of
  the source). It hides the hard cut where a jacket or shoulder ran out of the original picture.
- `stickers`: crop a cut-out to its own bounds for use as a floating sticker.

Canvas 1.2 times the video frame (1296x2304, 2304x1296) leaves room for the tile's overscan and push-in.

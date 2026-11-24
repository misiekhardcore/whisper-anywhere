"""Draw the tray and launcher icons into the package. Development only: run after design changes.

The panel host draws these pixels as they are: it exposes no way for a client to
learn the panel's colour, and it does not recolour a themed PNG. So every shape
is drawn twice - a dark keyline under a lighter core - and the icon stays legible
whichever background the panel uses. The launcher icon puts the same microphone
on an opaque tile so it reads as an app icon in the applications menu.
"""

from pathlib import Path

from PIL import Image, ImageDraw

ICONS_DIRECTORY: Path = (
    Path(__file__).resolve().parents[1] / "whisper_anywhere" / "icons"
)
THEME_DIRECTORY: Path = ICONS_DIRECTORY / "hicolor"
LAUNCHER_DIRECTORY: Path = ICONS_DIRECTORY / "launcher"
PANEL_SIZE = 22
HIDPI_SIZE = 44
LAUNCHER_SIZES = (48, 64, 128, 256)
SUPERSAMPLE = 8

INDEX_THEME = """[Icon Theme]
Name=Whisper Anywhere
Comment=Dictation state icons
Directories=22x22/apps,44x44/apps

[22x22/apps]
Size=22
Scale=1
Type=Fixed
Context=Applications

[44x44/apps]
Size=22
Scale=2
Type=Fixed
Context=Applications
"""

CORE_LIGHT = (242, 242, 242, 255)
CORE_DIMMED = (152, 152, 152, 255)
CORE_RED = (232, 74, 79, 255)
CORE_GREEN = (61, 179, 97, 255)
LAUNCHER_BACKGROUND = (36, 39, 46, 255)
LAUNCHER_GLYPH_SHARE = 0.66

# How deep the keyline runs under each core: the neutral icons lean on their
# outline on a light panel, the coloured ones stay saturated on a dark one.
CORES: dict[str, tuple[tuple[int, int, int, int], float]] = {
    "idle": (CORE_LIGHT, 0.18),
    "recording": (CORE_RED, 0.42),
    "processing": (CORE_GREEN, 0.42),
    "dimmed": (CORE_DIMMED, 0.30),
}


def _keyline(
    core: tuple[int, int, int, int], shade: float
) -> tuple[int, int, int, int]:
    """A deep shade of the core: it outlines the shape on a light panel."""
    return tuple(round(channel * shade) for channel in core[:3]) + (255,)


def _draw_microphone(
    size: int, core: tuple[int, int, int, int], shade: float
) -> Image.Image:
    keyline = _keyline(core, shade)
    scale = size * SUPERSAMPLE
    image = Image.new("RGBA", (scale, scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    unit = scale / PANEL_SIZE
    stroke = 3.2 * unit
    core_stroke = 1.6 * unit
    edge = 1.1 * unit

    body = (0.38 * scale, 0.10 * scale, 0.62 * scale, 0.52 * scale)
    radius = 0.12 * scale
    draw.rounded_rectangle(body, radius=radius, fill=keyline)
    draw.rounded_rectangle(
        (
            body[0] + edge,
            body[1] + edge,
            body[2] - edge,
            body[3] - edge,
        ),
        radius=max(1, radius - edge),
        fill=core,
    )

    cradle = (0.26 * scale, 0.28 * scale, 0.74 * scale, 0.66 * scale)
    draw.arc(cradle, start=0, end=180, fill=keyline, width=round(stroke))
    draw.arc(cradle, start=0, end=180, fill=core, width=round(core_stroke))

    stem = [(0.5 * scale, 0.64 * scale), (0.5 * scale, 0.84 * scale)]
    base = [(0.38 * scale, 0.85 * scale), (0.62 * scale, 0.85 * scale)]
    for segment in (stem, base):
        draw.line(segment, fill=keyline, width=round(stroke))
        draw.line(segment, fill=core, width=round(core_stroke))

    return image.resize((size, size), Image.LANCZOS)


def _draw_launcher(size: int) -> Image.Image:
    """The microphone on an opaque tile, sized for the applications menu."""
    scale = size * SUPERSAMPLE
    tile = Image.new("RGBA", (scale, scale), (0, 0, 0, 0))
    ImageDraw.Draw(tile).rounded_rectangle(
        (0, 0, scale - 1, scale - 1),
        radius=round(scale * 0.22),
        fill=LAUNCHER_BACKGROUND,
    )
    tile = tile.resize((size, size), Image.LANCZOS)

    glyph = _draw_microphone(
        round(size * LAUNCHER_GLYPH_SHARE), CORE_LIGHT, CORES["idle"][1]
    )
    offset = ((size - glyph.width) // 2, (size - glyph.height) // 2)
    tile.alpha_composite(glyph, offset)
    return tile


def main() -> None:
    """Write a hicolor theme, which is what a tray host can resolve by name."""
    (THEME_DIRECTORY / "22x22" / "apps").mkdir(parents=True, exist_ok=True)
    (THEME_DIRECTORY / "44x44" / "apps").mkdir(parents=True, exist_ok=True)
    (THEME_DIRECTORY / "index.theme").write_text(INDEX_THEME)
    LAUNCHER_DIRECTORY.mkdir(parents=True, exist_ok=True)
    for name, (core, shade) in CORES.items():
        for size in (PANEL_SIZE, HIDPI_SIZE):
            path = (
                THEME_DIRECTORY
                / f"{size}x{size}"
                / "apps"
                / f"whisper-anywhere-{name}.png"
            )
            _draw_microphone(size, core, shade).save(path)
            print(f"wrote {path.relative_to(ICONS_DIRECTORY.parents[1])}")
    for size in LAUNCHER_SIZES:
        path = LAUNCHER_DIRECTORY / f"whisper-anywhere-{size}.png"
        _draw_launcher(size).save(path)
        print(f"wrote {path.relative_to(ICONS_DIRECTORY.parents[1])}")


if __name__ == "__main__":
    main()

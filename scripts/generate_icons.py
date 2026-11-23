"""Draw the tray icons into the package. Development only: run after design changes."""

from pathlib import Path

from PIL import Image, ImageDraw

ICONS_DIRECTORY: Path = (
    Path(__file__).resolve().parents[1] / "whisper_anywhere" / "icons"
)
THEME_DIRECTORY: Path = ICONS_DIRECTORY / "hicolor"
PANEL_SIZE = 22
HIDPI_SIZE = 44
SUPERSAMPLE = 4

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

NEUTRAL = (230, 230, 230, 255)
RED = (229, 72, 77, 255)
GREEN = (47, 168, 79, 255)
DIMMED = (140, 140, 140, 150)
OUTLINE = (30, 30, 30, 255)

COLORS: dict[str, tuple[int, int, int, int]] = {
    "idle": NEUTRAL,
    "recording": RED,
    "processing": GREEN,
    "dimmed": DIMMED,
}


def _draw_microphone(size: int, fill: tuple[int, int, int, int]) -> Image.Image:
    scale = size * SUPERSAMPLE
    image = Image.new("RGBA", (scale, scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    body = (0.38 * scale, 0.10 * scale, 0.62 * scale, 0.52 * scale)
    draw.rounded_rectangle(
        body,
        radius=0.12 * scale,
        fill=fill,
        outline=OUTLINE,
        width=max(1, round(0.03 * scale)),
    )

    cradle = (0.26 * scale, 0.28 * scale, 0.74 * scale, 0.66 * scale)
    draw.arc(cradle, start=0, end=180, fill=OUTLINE, width=max(1, round(0.05 * scale)))

    stem = max(1, round(0.05 * scale))
    draw.line(
        [(0.5 * scale, 0.64 * scale), (0.5 * scale, 0.84 * scale)],
        fill=OUTLINE,
        width=stem,
    )
    draw.line(
        [(0.38 * scale, 0.85 * scale), (0.62 * scale, 0.85 * scale)],
        fill=OUTLINE,
        width=stem,
    )

    return image.resize((size, size), Image.LANCZOS)


def main() -> None:
    """Write a hicolor theme, which is what a tray host can resolve by name."""
    (THEME_DIRECTORY / "22x22" / "apps").mkdir(parents=True, exist_ok=True)
    (THEME_DIRECTORY / "44x44" / "apps").mkdir(parents=True, exist_ok=True)
    (THEME_DIRECTORY / "index.theme").write_text(INDEX_THEME)
    for name, fill in COLORS.items():
        for size in (PANEL_SIZE, HIDPI_SIZE):
            path = (
                THEME_DIRECTORY
                / f"{size}x{size}"
                / "apps"
                / f"whisper-anywhere-{name}.png"
            )
            _draw_microphone(size, fill).save(path)
            print(f"wrote {path.relative_to(ICONS_DIRECTORY.parents[1])}")


if __name__ == "__main__":
    main()

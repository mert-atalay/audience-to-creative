"""Static visuals as SVG from a simple brand template, with text wrapping and fit checks.

There is no font file here, so widths are estimated from a per-character table for a generic
sans-serif, with a safety margin. Text that cannot fit raises FitError instead of overflowing.
"""
from __future__ import annotations

import base64
from html import escape
from pathlib import Path

SCENES = Path(__file__).resolve().parent.parent / "assets" / "scenes"

_WIDTHS = {
    **{c: 0.28 for c in " iljI.,:;!|'"},
    **{c: 0.34 for c in 'ftr()-/"'},
    **{c: 0.50 for c in "ckszvxy?J"},
    **{c: 0.84 for c in "mwMW%@"},
}
SAFETY = 1.08  # fonts differ between machines, so over-estimate a little
BOLD = 1.06
LINE_HEIGHT = 1.12


class FitError(ValueError):
    pass


def scene_for(profile_name: str, angle: str) -> bytes | None:
    """The background photo for an angle, if one is bundled. See assets/scenes/README.md."""
    path = SCENES / profile_name / f"{angle}.jpg"
    return path.read_bytes() if path.exists() else None


def text_width(text: str, size: float, bold: bool = False) -> float:
    """Estimated width in pixels. Deliberately a little generous."""
    ems = sum(_WIDTHS.get(ch, 0.70 if ch.isupper() else 0.57) for ch in text)
    return ems * size * SAFETY * (BOLD if bold else 1)


def wrap(text: str, size: float, max_width: float, bold: bool = False) -> list[str]:
    """Greedy word wrap. A single word wider than the box cannot be wrapped."""
    lines, current = [], ""
    for word in text.split():
        if text_width(word, size, bold) > max_width:
            raise FitError(f"'{word}' is wider than the text box at {size:.0f}px")
        trial = f"{current} {word}".strip()
        if current and text_width(trial, size, bold) > max_width:
            lines.append(current)
            current = word
        else:
            current = trial
    return lines + [current] if current else lines


def fit_text(text: str, box_width: float, box_height: float, max_size: int, min_size: int, max_lines: int) -> tuple[int, list[str]]:
    """Largest font size at which the wrapped text fits the box."""
    for size in range(max_size, min_size - 1, -4):
        try:
            lines = wrap(text, size, box_width, bold=True)
        except FitError:
            continue
        if len(lines) <= max_lines and len(lines) * size * LINE_HEIGHT <= box_height:
            return size, lines
    raise FitError(f"headline does not fit {box_width:.0f}x{box_height:.0f}px in {max_lines} lines at {min_size}px or larger")


def layout(copy: dict, profile: dict, spec: dict, disclaimers: list[str] | None = None) -> dict:
    """Positions and sizes for every element. Raises FitError if any text would overflow."""
    v = spec["visual"]
    W, H, hmax, hmin = v["width"], v["height"], v["headline_max"], v["headline_min"]
    pad = round(0.075 * min(W, H))
    inner = W - 2 * pad
    logo = round(hmax * 0.62)
    radius = round(0.28 * min(W, H))  # accent circle in the top right corner
    brand_size = round(logo * 0.5)
    if pad + logo * 1.3 + text_width(profile["brand"]["name"], brand_size, True) > W - radius:
        raise FitError("brand name does not fit next to the logo")

    note = " ".join(disclaimers or [])
    note_size = max(18, round(hmax * 0.24))
    if note and text_width(note, note_size) > inner:
        raise FitError("disclaimer does not fit on one line")
    button_h = round(hmax * 0.95)
    cta_size = round(button_h * 0.42)
    button_w = text_width(copy["cta"], cta_size, True) + button_h * 1.2
    if button_w > inner:
        raise FitError("call to action does not fit the button")
    button_y = H - pad - button_h - (round(note_size * 1.9) if note else 0)

    top = max(pad + logo + pad * 0.6, radius)
    bottom = button_y - pad * 0.7
    size, lines = fit_text(copy["headline"], inner, bottom - top - hmax * 0.5, hmax, hmin, 3 if W > H else 5)
    first_baseline = bottom - len(lines) * size * LINE_HEIGHT + size * 0.85
    return {"W": W, "H": H, "pad": pad, "inner": inner, "logo": logo, "radius": radius, "brand_size": brand_size,
            "note": note, "note_size": note_size, "button": (pad, button_y, round(button_w), button_h),
            "cta_size": cta_size, "headline_size": size, "lines": lines, "first_baseline": round(first_baseline)}


def render(copy: dict, profile: dict, spec: dict, disclaimers: list[str] | None = None, title: str = "",
           scene: bytes | None = None) -> str:
    """One self-contained SVG. No external fonts, images or links.

    With a scene, the photo is embedded as the background and darkened towards the bottom. The logo,
    headline, button and disclaimer are still placed by this code, never drawn by an image model.
    """
    L = layout(copy, profile, spec, disclaimers)
    c, font = profile["brand"]["colours"], profile["brand"]["font_family"]
    W, H, pad, logo = L["W"], L["H"], L["pad"], L["logo"]
    bx, by, bw, bh = L["button"]
    size = L["headline_size"]
    bar_y = L["first_baseline"] - size * 0.85 - size * 0.38
    text, muted = ("#FFFFFF", "#E6EBF0") if scene else (c["text"], c["muted"])
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" '
        f'aria-label="{escape(title or copy["headline"])}" font-family="{escape(font)}">',
        f'<rect width="{W}" height="{H}" fill="{c["background"]}"/>',
    ]
    if scene:
        shade = "shade-" + "".join(ch if ch.isalnum() else "-" for ch in (title or copy["headline"]).lower())[:40]
        parts += [
            f'<defs><linearGradient id="{shade}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#000" stop-opacity="0.45"/>'
            f'<stop offset="0.3" stop-color="#000" stop-opacity="0.1"/><stop offset="0.62" stop-color="#000" stop-opacity="0.72"/>'
            f'<stop offset="1" stop-color="#000" stop-opacity="0.9"/></linearGradient></defs>',
            f'<image href="data:image/jpeg;base64,{base64.b64encode(scene).decode()}" width="{W}" height="{H}" '
            f'preserveAspectRatio="xMidYMid slice"/>',
            f'<rect width="{W}" height="{H}" fill="url(#{shade})"/>',
        ]
    else:
        parts += [
            f'<circle cx="{W}" cy="{H}" r="{round(L["radius"] * 1.5)}" fill="{c["panel"]}"/>',
            f'<circle cx="{W}" cy="0" r="{L["radius"]}" fill="{c["accent"]}"/>',
        ]
    parts += [
        # Logo: a rounded square with a wave, standing in for a real mark.
        f'<rect x="{pad}" y="{pad}" width="{logo}" height="{logo}" rx="{round(logo * 0.22)}" fill="{c["accent"]}"/>',
        f'<path d="M{pad + logo * 0.18:.0f} {pad + logo * 0.6:.0f} q{logo * 0.16:.0f} -{logo * 0.3:.0f} {logo * 0.32:.0f} 0 '
        f't{logo * 0.32:.0f} 0" fill="none" stroke="{c["background"]}" stroke-width="{max(3, round(logo * 0.1))}" stroke-linecap="round"/>',
        f'<text x="{round(pad + logo * 1.3)}" y="{round(pad + logo * 0.68)}" font-size="{L["brand_size"]}" font-weight="700" '
        f'fill="{text}">{escape(profile["brand"]["name"])}</text>',
        f'<rect x="{pad}" y="{bar_y:.0f}" width="{round(size * 1.2)}" height="{max(6, round(size * 0.09))}" fill="{c["accent"]}"/>',
    ]
    for i, line in enumerate(L["lines"]):
        y = round(L["first_baseline"] + i * size * LINE_HEIGHT)
        parts.append(f'<text x="{pad}" y="{y}" font-size="{size}" font-weight="700" fill="{text}">{escape(line)}</text>')
    parts.append(f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" rx="{bh // 2}" fill="{c["accent"]}"/>')
    parts.append(f'<text x="{bx + bw // 2}" y="{round(by + bh / 2 + L["cta_size"] * 0.35)}" font-size="{L["cta_size"]}" '
                 f'font-weight="700" text-anchor="middle" fill="{c["button_text"]}">{escape(copy["cta"])}</text>')
    if L["note"]:
        parts.append(f'<text x="{pad}" y="{H - pad}" font-size="{L["note_size"]}" fill="{muted}">{escape(L["note"])}</text>')
    return "\n".join(parts) + "\n</svg>\n"

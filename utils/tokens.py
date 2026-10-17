"""Tark's colour tokens, verbatim from spec §6 (from shodhya.com's
site/paper.css), and WCAG contrast between two of them."""

DARK = {
    "paper": "#12121c", "raised": "#1b1b29", "ink": "#f3efe6",
    "soft": "#bdb6a8", "faint": "#948d80", "rule": "#2c2c3d",
    "indigo": "#8f88ff", "coral": "#ff6b85", "amber": "#ffc53d",
    "on_indigo": "#12121c",
}
LIGHT = {
    "paper": "#f6f1e7", "raised": "#fffdf8", "ink": "#14142b",
    "soft": "#4d473d", "faint": "#6f6757", "rule": "#d9d0bf",
    "indigo": "#4338ca", "coral": "#e63e5c", "amber": "#ffb703",
    "on_indigo": "#ffffff",
}


def _luminance(hex_colour):
    rgb = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a, b):
    """WCAG 2 contrast ratio between two #rrggbb colours."""
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)

# Tab group colours, keyed by Chromium's group colour (spec 6.1): indigo,
# coral, amber, mint, sky, lilac, peach, stone, and apricot for Chromium's
# ninth. Light mode darkens each to at least 3:1 on light paper; amber's
# spec value (#ffb703) is 1.55:1 there, so groups use #b78100.
GROUP_DARK = {
    "blue": "#8f88ff", "red": "#ff6b85", "yellow": "#ffc53d",
    "green": "#6fd3c1", "cyan": "#7fb7ff", "purple": "#d99cff",
    "pink": "#ff9f6b", "grey": "#bdb6a8", "orange": "#ffb074",
}
GROUP_LIGHT = {
    "blue": "#4338ca", "red": "#e63e5c", "yellow": "#b78100",
    "green": "#2f9986", "cyan": "#2d89ff", "purple": "#c05aff",
    "pink": "#f55600", "grey": "#958a74", "orange": "#c25a00",
}

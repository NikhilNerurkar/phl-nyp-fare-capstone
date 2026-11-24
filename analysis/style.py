"""Shared chart styling: one consistent look across every figure we export.

Colors are the validated default palette from the dataviz skill (categorical
hues assigned in fixed order, never cycled; one sequential blue ramp for
magnitude). Values are copied, not re-derived - if the skill's palette
changes, update them here in one place.
"""
from __future__ import annotations

import matplotlib
import matplotlib.pyplot as plt

matplotlib.use("Agg")  # headless: we only ever save PNGs, never show()

# --- chart chrome -----------------------------------------------------------
SURFACE = "#fcfcfb"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
BASELINE = "#c3c2b7"

# --- categorical palette, FIXED ORDER - never reassign per-chart ------------
# Assign roles once, in analysis/report.py, and reuse everywhere so "Amtrak"
# is always the same blue on every slide.
CAT = {
    "blue": "#2a78d6",
    "orange": "#eb6834",
    "aqua": "#1baf7a",
    "yellow": "#eda100",
    "magenta": "#e87ba4",
    "green": "#008300",
    "violet": "#6250d6",
    "red": "#e34948",
}
CAT_ORDER = ["blue", "orange", "aqua", "yellow", "magenta", "green", "violet", "red"]

# Fixed operator -> color assignment, decided once. "Other" absorbs every
# minor/unmapped carrier so the legend never grows past what a slide can hold.
OPERATOR_COLOR = {
    "Amtrak": CAT["blue"],
    "Greyhound": CAT["orange"],
    "FlixBus": CAT["aqua"],
    "Peter Pan": CAT["yellow"],
    "OurBus": CAT["magenta"],
    "Megabus": CAT["violet"],
    "Other": INK_MUTED,
}

# Amtrak's own services get shades of the same blue family so "this is all
# Amtrak" reads at a glance, while still being distinguishable.
SERVICE_COLOR = {
    "Acela": "#104281",            # darkest - premium
    "Northeast Regional": "#2a78d6",
    "Keystone Service": "#86b6ef",  # lightest - cheapest of the three
}

SEQUENTIAL_BLUE = ["#cde2fb", "#9ec5f4", "#5598e7", "#2a78d6", "#184f95"]

STATUS = {
    "good": "#0ca30c",
    "warning": "#fab219",
    "serious": "#ec835a",
    "critical": "#d03b3b",
}


def operator_color(name: str) -> str:
    return OPERATOR_COLOR.get(name, OPERATOR_COLOR["Other"])


def apply_style() -> None:
    """Call once per process. Flat, minimal, print-safe - no 3D, no rainbow."""
    plt.rcParams.update({
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
        "axes.edgecolor": BASELINE,
        "axes.labelcolor": INK_SECONDARY,
        "axes.titlecolor": INK_PRIMARY,
        "axes.grid": True,
        "grid.color": GRIDLINE,
        "grid.linewidth": 0.8,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "xtick.color": INK_MUTED,
        "ytick.color": INK_MUTED,
        "text.color": INK_PRIMARY,
        "font.family": "sans-serif",
        "font.size": 11,
        "axes.titlesize": 13,
        "axes.titleweight": "bold",
        "legend.frameon": False,
        "figure.dpi": 150,
        "savefig.dpi": 150,
        "savefig.bbox": "tight",
    })


def finish(fig, path, title: str, subtitle: str | None = None) -> None:
    """Common title treatment + save. Call at the end of every chart function."""
    ax = fig.axes[0] if fig.axes else None
    if ax is not None:
        ax.set_title(title, loc="left", pad=(22 if subtitle else 10))
        if subtitle:
            ax.text(0.0, 1.02, subtitle, transform=ax.transAxes,
                    fontsize=9.5, color=INK_SECONDARY, va="bottom")
    fig.savefig(path)
    plt.close(fig)

"""Geometry for the dashboard's SVG charts, so the templates only place shapes.

Charts follow the data-visualisation rules used across the project: thin bars
with 4px rounded ends at the top (or right) and a square base on the axis, a
2px gap between bars, one colour for a single series (no legend: the title
names it), a light axis, and values in text colours, never in the bar colour.
"""

import math

BAR_RADIUS = 4
GAP = 2


def nice_max(value):
    """A round axis maximum at or above `value`: 1, 2, 2.5 or 5 × 10^n."""
    if value <= 0:
        return 1
    magnitude = 10 ** math.floor(math.log10(value))
    for step in (1, 2, 2.5, 5, 10):
        if value <= step * magnitude:
            return step * magnitude
    return 10 * magnitude


def _round_top(x, y, w, base):
    """A bar from the baseline up to y, rounded at the top only."""
    r = min(BAR_RADIUS, w / 2, max(base - y, 0))
    return (
        f"M{x:.1f},{base:.1f}V{y + r:.1f}Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f}"
        f"H{x + w - r:.1f}Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f}V{base:.1f}Z"
    )


def _round_right(x, y, w, h):
    """A bar from x to the right, rounded at the right end only."""
    r = min(BAR_RADIUS, h / 2, max(w, 0))
    return (
        f"M{x:.1f},{y:.1f}H{x + w - r:.1f}Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f}"
        f"V{y + h - r:.1f}Q{x + w:.1f},{y + h:.1f} {x + w - r:.1f},{y + h:.1f}H{x:.1f}Z"
    )


def column_chart(points, width=360, height=180, left=44, bottom=22, top=10):
    """Vertical bars for [(label, value)]: shapes, gridlines and the plot box."""
    top_value = nice_max(max((value for _label, value in points), default=0))
    plot_h = height - top - bottom
    slot = (width - left) / max(len(points), 1)
    bar_w = max(slot * 0.6, 4)
    base = top + plot_h
    bars = []
    for i, (label, value) in enumerate(points):
        x = left + i * slot + (slot - bar_w) / 2
        h = plot_h * max(value, 0) / top_value
        bars.append(
            {
                "label": label,
                "value": value,
                "path": _round_top(x, base - h, bar_w, base) if h > 0 else "",
                "x_mid": x + bar_w / 2,
                "hit_x": left + i * slot,
                "hit_w": slot - GAP,
            }
        )
    grid = [
        {"y": base - plot_h * fraction, "value": top_value * fraction} for fraction in (0, 0.5, 1)
    ]
    return {
        "width": width,
        "height": height,
        "left": left,
        "base": base,
        "top": top,
        "bars": bars,
        "grid": grid,
    }


def bar_chart(points, width=360, row=26, left=80, right=44):
    """Horizontal bars for [(label, value)], one row each."""
    top_value = nice_max(max((value for _label, value in points), default=0))
    plot_w = width - left - right
    bar_h = row - 8
    rows = []
    for i, (label, value) in enumerate(points):
        y = i * row + 4
        w = plot_w * max(value, 0) / top_value
        rows.append(
            {
                "label": label,
                "value": value,
                "y": y,
                "y_mid": y + bar_h / 2,
                "path": _round_right(left, y, w, bar_h) if w > 0 else "",
                "label_x": left + w + 6,
            }
        )
    return {"width": width, "height": max(len(points), 1) * row, "left": left, "rows": rows}


# Written out in full so Tailwind finds and generates every class.
HEAT_FILLS = (
    "fill-subtle",
    "fill-heat-1",
    "fill-heat-2",
    "fill-heat-3",
    "fill-heat-4",
    "fill-heat-5",
)


def heat_level(share):
    """0 (none or no data) … 5 (busiest) for an occupancy share 0..1."""
    if share is None or share <= 0:
        return 0
    return min(5, 1 + int(share * 5))


def heatmap(rows, slots, cell=36, gap=GAP, left=40, top=24):
    """Cells for [(weekday, [share per slot])]: x, y, level and the share."""
    cells = []
    for r, (weekday, shares) in enumerate(rows):
        for c, share in enumerate(shares):
            cells.append(
                {
                    "x": left + c * (cell + gap),
                    "y": top + r * (cell + gap),
                    "level": heat_level(share),
                    "fill": HEAT_FILLS[heat_level(share)],
                    "share": share,
                    "weekday": weekday,
                    "slot": slots[c],
                }
            )
    return {
        "width": left + len(slots) * (cell + gap),
        "height": top + len(rows) * (cell + gap),
        "cell": cell,
        "left": left,
        "top": top,
        "cells": cells,
        "columns": [
            {"x": left + c * (cell + gap) + cell / 2, "slot": slot} for c, slot in enumerate(slots)
        ],
        "row_labels": [
            {"y": top + r * (cell + gap) + cell / 2, "weekday": weekday}
            for r, (weekday, _shares) in enumerate(rows)
        ],
    }

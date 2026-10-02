"""Group detected text inside closed white balloons before manga OCR."""
from collections import defaultdict
from dataclasses import dataclass, replace

import cv2
import numpy as np


@dataclass(frozen=True)
class TextArea:
    box: tuple[int, int, int, int]  # left, top, right, bottom in pixels
    placement: tuple[int, int, int, int]
    kind: str
    members: tuple[tuple[int, int, int, int], ...] = ()


def union(boxes):
    return (
        min(b[0] for b in boxes), min(b[1] for b in boxes),
        max(b[2] for b in boxes), max(b[3] for b in boxes),
    )


def intersection_area(first, second):
    return (
        max(0, min(first[2], second[2]) - max(first[0], second[0]))
        * max(0, min(first[3], second[3]) - max(first[1], second[1]))
    )


def merge_overlapping_boxes(boxes: list[tuple]) -> list[tuple]:
    # CRAFT can detect both a heading and its individual columns. OCR their
    # union once, including any text that extends beyond the larger detection.
    merged = sorted(set(tuple(box) for box in boxes if box[2] > box[0] and box[3] > box[1]))
    while True:
        for index, first in enumerate(merged):
            first_area = (first[2] - first[0]) * (first[3] - first[1])
            for other_index in range(index + 1, len(merged)):
                second = merged[other_index]
                second_area = (second[2] - second[0]) * (second[3] - second[1])
                if intersection_area(first, second) / min(first_area, second_area) >= 0.65:
                    merged[index] = union((first, second))
                    merged.pop(other_index)
                    merged.sort()
                    break
            else:
                continue
            break
        else:
            return merged


def _member_clusters(members: tuple[tuple[int, int, int, int], ...]) -> list[tuple[tuple[int, int, int, int], ...]]:
    ordered = sorted(members, key=lambda box: (box[1], box[0]))
    if len(ordered) < 2:
        return [tuple(ordered)]
    heights = sorted(box[3] - box[1] for box in ordered)
    median_height = heights[len(heights) // 2]
    gap_limit = max(12, round(median_height * 2.25))
    clusters: list[list[tuple[int, int, int, int]]] = [[]]
    previous_bottom = ordered[0][3]
    for box in ordered:
        if clusters[-1] and box[1] - previous_bottom > gap_limit:
            clusters.append([])
        clusters[-1].append(box)
        previous_bottom = max(previous_bottom, box[3])
    return [tuple(cluster) for cluster in clusters]


def _separate_nested_sources(areas: list[TextArea]) -> list[TextArea]:
    # A white component may connect a caption to a distant balloon. Split its
    # members at large reading-order gaps when another placement is nested.
    split = set()
    for index, area in enumerate(areas):
        if len(_member_clusters(area.members)) < 2:
            continue
        area_size = max(1, (area.placement[2] - area.placement[0]) * (area.placement[3] - area.placement[1]))
        for other_index, other in enumerate(areas):
            if index == other_index:
                continue
            other_size = max(1, (other.placement[2] - other.placement[0]) * (other.placement[3] - other.placement[1]))
            if intersection_area(area.placement, other.placement) / min(area_size, other_size) >= 0.65:
                split.add(index)
                break
    separated = []
    for index, area in enumerate(areas):
        if index not in split:
            separated.append(area)
            continue
        for cluster in _member_clusters(area.members):
            box = union(cluster)
            separated.append(TextArea(box, box, area.kind, cluster))
    return separated


def _resolve_placement_overlaps(areas: list[TextArea]) -> list[TextArea]:
    # Contract both conflicting placements, then recheck: a source rectangle
    # can extend beyond an inset balloon rectangle and reveal another conflict.
    while True:
        conflicts = set()
        for index, area in enumerate(areas):
            for other_index in range(index + 1, len(areas)):
                if intersection_area(area.placement, areas[other_index].placement):
                    conflicts.update((index, other_index))
        changed = False
        for index in conflicts:
            area = areas[index]
            tight_box = union(area.members)
            if area.placement != tight_box:
                areas[index] = replace(area, placement=tight_box)
                changed = True
        if not changed:
            return areas


def group_balloons(
    image: np.ndarray, boxes: list[tuple], *, conservative=False, restrict_placements=False,
) -> list[TextArea]:
    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    _, labels, stats, _ = cv2.connectedComponentsWithStats(
        (gray >= 205).astype(np.uint8), connectivity=8,
    )
    groups = defaultdict(list)
    for index, box in enumerate(merge_overlapping_boxes(boxes)):
        left, top, right, bottom = box
        crop = labels[top:bottom, left:right]
        if not crop.size:
            continue
        ids, counts = np.unique(crop, return_counts=True)
        group_id = -(index + 1)
        for candidate in ids[np.argsort(counts)[::-1]]:
            if candidate == 0:
                continue
            x, y, w, h, area = (int(v) for v in stats[candidate])
            # A white component touching an image edge is usually the page,
            # not a closed speech balloon. Do not expand into that component.
            if x <= 0 or y <= 0 or x + w >= width or y + h >= height:
                continue
            if area > width * height * 0.35 or area < (right-left)*(bottom-top)*0.6:
                continue
            if x <= left + 3 and y <= top + 3 and x+w >= right-3 and y+h >= bottom-3:
                if np.count_nonzero(crop == candidate) / crop.size >= 0.4:
                    group_id = int(candidate)
                    break
        groups[group_id].append(box)

    areas = []
    for group_id, members in groups.items():
        box = union(members)
        left, top, right, bottom = box
        margin = 2 if conservative else 4
        box = (max(0, left-margin), max(0, top-margin),
               min(width, right+margin), min(height, bottom+margin))
        placement = box
        kind = "caption"
        if group_id > 0:
            x, y, w, h, _ = (int(v) for v in stats[group_id])
            # An inset rectangle stays inside typical round balloons; avoid
            # claiming the whole bounding rectangle, which includes corners.
            inset_x, inset_y = max(3, round(w*0.16)), max(3, round(h*0.16))
            safe = (x+inset_x, y+inset_y, x+w-inset_x, y+h-inset_y)
            if not restrict_placements and safe[2] > safe[0] and safe[3] > safe[1]:
                placement = safe
            kind = "dialogue"
        areas.append(TextArea(box, placement, kind, tuple(members)))
    areas = _separate_nested_sources(areas)
    return sorted(_resolve_placement_overlaps(areas), key=lambda a: (a.box[1], -a.box[2]))


def normalized_box(box, width: int, height: int) -> list[int]:
    left, top, right, bottom = box
    ymin = max(0, min(999, round(top * 1000 / height)))
    xmin = max(0, min(999, round(left * 1000 / width)))
    return [
        ymin, xmin, max(ymin + 1, min(1000, round(bottom * 1000 / height))),
        max(xmin + 1, min(1000, round(right * 1000 / width))),
    ]

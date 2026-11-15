"""Разделение общего бокса по независимым светлым телам облачков."""

import copy

import cv2
import numpy as np


def split_balloon_regions(image, regions):
    """До OCR отделить перекрывающиеся облачка с собственными буквами."""
    gray = cv2.cvtColor(np.asarray(image.convert('RGB')), cv2.COLOR_RGB2GRAY)
    result = []
    for region in regions:
        if (region.bubble_bbox is None or region.document or region.manual or region.edited
                or region.text or region.translation or region.auto_layout):
            result.append(region)
            continue
        bx, by, bw, bh = region.bubble_bbox
        x0, y0 = max(0, bx), max(0, by)
        patch = gray[y0:min(gray.shape[0], by+bh), x0:min(gray.shape[1], bx+bw)]
        if not patch.size:
            result.append(region)
            continue
        count, labels, stats, _ = cv2.connectedComponentsWithStats((patch >= 210).astype(np.uint8))
        parts = []
        tx, ty, tw, th = region.bbox
        for i in range(1, count):
            if stats[i, 4] < patch.size*.06:
                continue
            body = (labels == i).astype(np.uint8)*255
            contours, _ = cv2.findContours(body, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(body, contours, -1, 255, -1)
            letters = ((body > 0) & (patch < 160)).astype(np.uint8)
            n, ink_labels, ink_stats, _ = cv2.connectedComponentsWithStats(letters)
            kept = [j for j in range(1, n) if ink_stats[j, 4] >= 5
                    and ink_stats[j, 3] >= 3 and ink_stats[j, 2] < bw*.4
                    and ink_stats[j, 3] < bh*.6
                    and tx <= x0+ink_stats[j, 0]+ink_stats[j, 2]/2 <= tx+tw
                    and ty <= y0+ink_stats[j, 1]+ink_stats[j, 3]/2 <= ty+th]
            if len(kept) < 4:
                continue
            # Белый ореол строки тоже замыкает буквы, но не даёт поля облачка.
            typical = float(np.median(ink_stats[kept, cv2.CC_STAT_HEIGHT]))
            depth = cv2.distanceTransform(body, cv2.DIST_L2, 5)
            if float(depth.max()) < typical*.9:
                continue
            ys, xs = np.nonzero(np.isin(ink_labels, kept))
            box = (x0+int(xs.min()), y0+int(ys.min()), int(np.ptp(xs))+1, int(np.ptp(ys))+1)
            if box[2]*box[3] < tw*th*.06:
                continue
            contour = max(contours, key=cv2.contourArea).reshape(-1, 2) + [x0, y0]
            parts.append((box, contour))
        if len(parts) < 2:
            result.append(region)
            continue
        for box, contour in sorted(parts, key=lambda p: (p[0][1], p[0][0])):
            child = copy.deepcopy(region)
            child.bbox = box
            xx, yy, ww, hh = cv2.boundingRect(contour.astype(np.int32))
            child.bubble_bbox = (xx, yy, ww, hh)
            child.auto_layout = dict(version=1, kind='bubble', angle=0.,
                                     source_bbox=list(box), ink_bbox=list(box),
                                     outline_px=3., mask_pad_px=8.,
                                     evidence={'partitioned_balloon': True}, contour=contour.tolist())
            result.append(child)
    for i, region in enumerate(result, 1):
        region.id = i
    return result


def partition_area(shape, region):
    """Подтверждённый контур разделённого облачка, в том числе после загрузки."""
    if not (region.auto_layout or {}).get('evidence', {}).get('partitioned_balloon'):
        return None
    from src.components.adaptive_text import geometry_area
    return geometry_area(shape, region)


def partition_retouch_area(rgb, region, area):
    """Закрыть компактную буквенную выемку, не сглаживая весь контур облачка."""
    x, y, w, h = region.bbox
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    ink = ((gray < 160) & (area > 0)).astype(np.uint8)
    n, _, stats, _ = cv2.connectedComponentsWithStats(ink)
    heights = [stats[i, 3] for i in range(1, n) if stats[i, 4] >= 5
               and 3 <= stats[i, 3] < h*.7 and stats[i, 2] < w*.3]
    if len(heights) < 4:
        return area
    typical = float(np.median(heights))
    radius = max(2, round(typical*.4))
    closed = cv2.morphologyEx(area, cv2.MORPH_CLOSE,
                             cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2*radius+1, 2*radius+1)))
    n, labels, stats, centers = cv2.connectedComponentsWithStats(((closed > 0) & (area == 0)).astype(np.uint8))
    result = area.copy()
    for i in range(1, n):
        _, _, iw, ih, size = stats[i]
        cx, cy = centers[i]
        if (typical*.65 <= ih <= typical*1.6 and typical*.4 <= iw <= typical*3
                and size >= typical*typical*.25 and size/(iw*ih) >= .5
                and x <= cx <= x+w and y <= cy <= y+h
                and np.mean(gray[labels == i] < 160) >= .6):
            result[labels == i] = 255
    return result

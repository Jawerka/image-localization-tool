# Data Model: Bubble Contour Mask

No persistent schema change.

## Ephemeral

| Name | Type | Notes |
| --- | --- | --- |
| Bubble interior silhouette | `uint8` HxW | 0/255, page coordinates |
| Retouch mask | `uint8` HxW | Silhouette after inset; dialogue cleanup input |

## Config

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `bubble_mask_inset_px` | int | 2 | Erode silhouette toward interior before retouch |

`TextRegion.bubble_bbox` unchanged (AABB from detector).

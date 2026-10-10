# Contract: Bubble Contour (internal)

No new HTTP API.

## Python

```text
bubble_interior_mask(image_rgb, region, *, inset_px=2) -> np.ndarray  # uint8 HxW
```

- Empty array shape matches image when recovery fails.
- Non-empty: silhouette ⊆ search ROI; no requirement to fill AABB.
- Callers: `text_segmenter.segment_region` for dialogue retouch.

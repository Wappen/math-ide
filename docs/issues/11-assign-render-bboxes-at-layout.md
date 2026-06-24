---
title: Assign render bboxes at layout time
labels: renderer
---

## Summary

After layout, measure occurrence positions in the **rendered document** and write **render bboxes** (canonical for interaction). Keep **source bboxes** as provenance.

Blocked by: **#10**.

## Scope

- Post-layout pass (e.g. `getBoundingClientRect` in browser, or server-side layout metrics)
- Update each occurrence's `render_bbox` in document coordinates
- Re-run when:
  - Formula upgrades from fallback → LaTeX (layout reflow)
  - Window resize (if IDE is live; debounced)
- Sub-span precision for formula symbols using KaTeX glyph metrics where possible

## Acceptance criteria

- [ ] All import-time occurrences have non-null `render_bbox` after layout
- [ ] Symbol-level hit targets inside formulas are smaller than whole-formula box
- [ ] `source_bbox` unchanged after render measurement
- [ ] Re-layout updates bboxes when formula content upgrades

## Out of scope

- Click interaction (#12)

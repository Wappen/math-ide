"""Renderer for the Math IDE.

Turns a :class:`math_ide.schema.MathDocument` into a standalone, interactive
HTML page (the *rendered document*). The public surface is
:func:`render_document` (full page) and :func:`render_block` (one fragment).

The DOM conventions emitted here (CSS classes + ``data-*`` attributes) are a
contract the IDE wave (render-bbox measurement, click handlers) depends on;
they are documented at the top of :mod:`math_ide.renderer.render`.
"""

from __future__ import annotations

from math_ide.renderer.render import render_block, render_document

__all__ = ["render_document", "render_block"]

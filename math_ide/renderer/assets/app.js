/* Math IDE — client interactions (issues #11, #12, #13).
 *
 * Vanilla JS, no build step. Stays THIN: all navigation logic is precomputed in
 * Python (math_ide.renderer.navigation) and embedded in the page as
 *   <script type="application/json" id="math-ide-data">…</script>
 * This script only reads that payload, measures layout, and wires the DOM.
 *
 * DOM contract (see render.py module docstring):
 *   .math-doc-scroll               scroll container (coordinate origin)
 *   .occ[data-occurrence-id]       hit targets
 *   .occ[data-kind]                formula_symbol | defined_name | citation
 *   .occ[data-target-block-id]     citations only
 *   .occ[data-resolvable="false"]  no go-to-definition target yet ("resolving…")
 *   #<block_id> / [data-block-id]  every rendered block (scroll targets)
 *   .formula[data-enrichment]      formula state (remeasure when it upgrades)
 *   .katex-target[data-latex]      ready-formula KaTeX host (typeset here)
 *   .katex-target[data-occurrences] per-symbol token descriptors to re-anchor
 *   .occ-fallback                  inline .occ anchors used until/unless KaTeX
 *                                  glyphs are matched (the no-JS hit layer)
 *   #concept-panel                 side panel for the concept card (#13)
 *
 * Public API (window.mathIDE):
 *   renderBboxes()        -> { "<occ_id>": {x,y,width,height}, ... }
 *   remeasure()           -> re-measure all render bboxes now
 *   goToDefinition(occId) -> scroll+highlight the occurrence's target
 *   showCard(conceptId)   -> open the concept card in the side panel
 *   refresh(dataOrUrl)    -> reload the payload (object or URL) and re-render
 *   data                  -> the current embedded payload (read-only-ish)
 */
(function () {
  "use strict";

  var SCROLL_SELECTOR = ".math-doc-scroll";
  var HIGHLIGHT_CLASS = "definition-highlight";
  var HIGHLIGHT_MS = 1600;
  var RESIZE_DEBOUNCE_MS = 150;

  // ---- state -------------------------------------------------------------
  var state = {
    data: { occurrences: {}, concepts: {}, relations: [], cards: {} },
    bboxes: {}, // occ_id -> {x, y, width, height} in scroll-container coords
  };

  function scrollContainer() {
    return document.querySelector(SCROLL_SELECTOR) || document.documentElement;
  }

  // ---- payload loading ---------------------------------------------------

  function readEmbeddedPayload() {
    var el = document.getElementById("math-ide-data");
    if (!el) return null;
    try {
      return JSON.parse(el.textContent);
    } catch (e) {
      console.warn("math-ide: could not parse embedded payload", e);
      return null;
    }
  }

  function setData(payload) {
    if (!payload) return;
    state.data = {
      occurrences: payload.occurrences || {},
      concepts: payload.concepts || {},
      relations: payload.relations || [],
      cards: payload.cards || {},
      document_id: payload.document_id,
      ingestion_state: payload.ingestion_state,
    };
    // Reflect (possibly updated) resolvable state onto the anchors so CSS and
    // measurement stay consistent after a refresh.
    syncResolvableAttributes();
  }

  function syncResolvableAttributes() {
    var occs = document.querySelectorAll(".occ");
    for (var i = 0; i < occs.length; i++) {
      var el = occs[i];
      var id = el.getAttribute("data-occurrence-id");
      var entry = state.data.occurrences[id];
      if (!entry) continue;
      if (entry.definition_target == null) {
        el.setAttribute("data-resolvable", "false");
      } else {
        el.removeAttribute("data-resolvable");
      }
    }
  }

  // #11 ---- render-bbox measurement ---------------------------------------
  //
  // Measure each .occ getBoundingClientRect relative to the scroll container's
  // content box (accounting for its scroll offset), so a stored bbox is stable
  // regardless of the current scroll position. Symbol-level targets are the
  // individual .occ spans, which are strictly smaller than their formula box.

  function measureBboxes() {
    var container = scrollContainer();
    var cRect = container.getBoundingClientRect();
    var sx = container.scrollLeft || 0;
    var sy = container.scrollTop || 0;
    var out = {};
    var occs = document.querySelectorAll(".occ");
    for (var i = 0; i < occs.length; i++) {
      var el = occs[i];
      var id = el.getAttribute("data-occurrence-id");
      if (!id) continue;
      var r = el.getBoundingClientRect();
      // Skip occ anchors that aren't laid out (e.g. a hidden .occ-fallback
      // after KaTeX claimed the glyphs) so a same-id glyph target isn't
      // clobbered by a zero-area duplicate.
      if (r.width === 0 && r.height === 0) continue;
      var box = {
        x: r.left - cRect.left + sx,
        y: r.top - cRect.top + sy,
        width: r.width,
        height: r.height,
      };
      out[id] = box;
      // #11: also write the measured box back into the live payload, so a
      // re-serialised payload carries rendered-document geometry. render_bbox is
      // populated client-side post-layout (it is null in the embedded payload).
      var entry = state.data.occurrences[id];
      if (entry) entry.render_bbox = box;
    }
    state.bboxes = out;
    return out;
  }

  function renderBboxes() {
    // Lazily measure once if nothing measured yet.
    if (Object.keys(state.bboxes).length === 0) measureBboxes();
    return state.bboxes;
  }

  // #12 ---- go to definition ----------------------------------------------

  function clearHighlights() {
    var hot = document.querySelectorAll("." + HIGHLIGHT_CLASS);
    for (var i = 0; i < hot.length; i++) hot[i].classList.remove(HIGHLIGHT_CLASS);
  }

  function highlight(el) {
    if (!el) return;
    clearHighlights();
    el.classList.add(HIGHLIGHT_CLASS);
    window.setTimeout(function () {
      el.classList.remove(HIGHLIGHT_CLASS);
    }, HIGHLIGHT_MS);
  }

  function scrollToBlock(blockId) {
    if (!blockId) return null;
    var target =
      document.getElementById(blockId) ||
      document.querySelector('[data-block-id="' + cssEscape(blockId) + '"]');
    if (!target) return null;
    if (typeof target.scrollIntoView === "function") {
      target.scrollIntoView({ behavior: "smooth", block: "center" });
    }
    highlight(target);
    return target;
  }

  function flashResolving(el) {
    if (!el) return;
    el.classList.add("occ-resolving-flash");
    window.setTimeout(function () {
      el.classList.remove("occ-resolving-flash");
    }, 900);
  }

  function goToDefinition(occId) {
    var entry = state.data.occurrences[occId];
    var anchor = document.querySelector(
      '.occ[data-occurrence-id="' + cssEscape(occId) + '"]'
    );
    if (!entry || entry.definition_target == null) {
      // Disabled "resolving…" cue: no target available yet.
      flashResolving(anchor);
      return null;
    }
    return scrollToBlock(entry.definition_target);
  }

  // #13 ---- concept card ---------------------------------------------------

  function panel() {
    return document.getElementById("concept-panel");
  }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function navigateToOccurrence(occId) {
    var entry = state.data.occurrences[occId];
    if (!entry) return;
    // Prefer the occurrence's own block so the reference itself is revealed.
    scrollToBlock(entry.block_id);
  }

  function referenceRow(ref) {
    var row = el("li", "card-ref");
    var btn = el("button", "card-ref-link", ref.kind + " @ " + shortBlock(ref.block_id));
    btn.type = "button";
    btn.setAttribute("data-occurrence-id", ref.occurrence_id);
    btn.addEventListener("click", function () {
      navigateToOccurrence(ref.occurrence_id);
    });
    row.appendChild(btn);
    return row;
  }

  function neighbourRow(item, originClass) {
    var row = el("li", "card-neighbour " + originClass);
    var label = item.name || item.concept_id || item.block_id || "?";
    var btn = el("button", "card-neighbour-link", label);
    btn.type = "button";
    var kind = el("span", "card-kind", item.kind);
    row.appendChild(kind);
    if (item.concept_id) {
      btn.addEventListener("click", function () {
        showCard(item.concept_id);
      });
    } else if (item.block_id) {
      btn.addEventListener("click", function () {
        scrollToBlock(item.block_id);
      });
    }
    row.appendChild(btn);
    if (originClass === "semantic") {
      row.appendChild(el("span", "card-badge inferred", "inferred"));
    }
    return row;
  }

  function buildCard(card) {
    var root = el("div", "card");

    var head = el("div", "card-head");
    head.appendChild(el("h2", "card-title", card.name));
    head.appendChild(
      el("span", "card-status status-" + card.resolution_status, card.resolution_status)
    );
    root.appendChild(head);

    if (card.formal_meaning) {
      var fm = el("div", "card-section card-formal");
      fm.appendChild(el("h3", "card-section-title", "Formal meaning"));
      fm.appendChild(el("p", "card-meaning", card.formal_meaning));
      root.appendChild(fm);
    }
    if (card.inferred_meaning) {
      var im = el("div", "card-section card-inferred");
      var t = el("h3", "card-section-title", "Inferred meaning");
      t.appendChild(el("span", "card-badge inferred", "inferred"));
      im.appendChild(t);
      im.appendChild(el("p", "card-meaning", card.inferred_meaning));
      root.appendChild(im);
    }

    if (card.defining_occurrence) {
      var defSec = el("div", "card-section card-defining");
      defSec.appendChild(el("h3", "card-section-title", "Defining occurrence"));
      var defBtn = el("button", "card-ref-link", shortBlock(card.defining_occurrence.block_id));
      defBtn.type = "button";
      defBtn.addEventListener("click", function () {
        navigateToOccurrence(card.defining_occurrence.id);
      });
      defSec.appendChild(defBtn);
      root.appendChild(defSec);
    }

    var refSec = el("div", "card-section card-references");
    refSec.appendChild(
      el("h3", "card-section-title", "References (" + card.references.length + ")")
    );
    if (card.references.length) {
      var refList = el("ul", "card-list");
      card.references.forEach(function (ref) {
        refList.appendChild(referenceRow(ref));
      });
      refSec.appendChild(refList);
    } else {
      refSec.appendChild(el("p", "card-empty", "No references."));
    }
    root.appendChild(refSec);

    var nb = card.neighbourhood || { structural: [], semantic: [] };
    var nbSec = el("div", "card-section card-neighbourhood");
    nbSec.appendChild(el("h3", "card-section-title", "Neighbourhood"));

    nbSec.appendChild(el("h4", "card-subhead structural", "Structural"));
    if (nb.structural.length) {
      var sList = el("ul", "card-list");
      nb.structural.forEach(function (item) {
        sList.appendChild(neighbourRow(item, "structural"));
      });
      nbSec.appendChild(sList);
    } else {
      nbSec.appendChild(el("p", "card-empty", "None."));
    }

    nbSec.appendChild(el("h4", "card-subhead semantic", "Semantic (inferred)"));
    if (nb.semantic.length) {
      var seList = el("ul", "card-list");
      nb.semantic.forEach(function (item) {
        seList.appendChild(neighbourRow(item, "semantic"));
      });
      nbSec.appendChild(seList);
    } else {
      nbSec.appendChild(el("p", "card-empty", "Pending meaning resolution."));
    }
    root.appendChild(nbSec);

    return root;
  }

  var _openConceptId = null;

  function showCard(conceptId) {
    var p = panel();
    if (!p) return;
    _openConceptId = conceptId; // remembered so refresh() can re-render it
    var card = state.data.cards[conceptId];
    p.innerHTML = "";
    var close = el("button", "card-close", "×");
    close.type = "button";
    close.setAttribute("aria-label", "Close");
    close.addEventListener("click", hideCard);
    p.appendChild(close);
    if (!card) {
      p.appendChild(el("p", "card-empty", "No concept selected."));
    } else {
      p.appendChild(buildCard(card));
    }
    p.hidden = false;
    p.classList.add("open");
  }

  function hideCard() {
    var p = panel();
    if (!p) return;
    p.hidden = true;
    p.classList.remove("open");
  }

  // ---- event wiring ------------------------------------------------------

  function occFromEvent(ev) {
    var t = ev.target;
    while (t && t !== document) {
      if (t.classList && t.classList.contains("occ")) return t;
      t = t.parentNode;
    }
    return null;
  }

  function onClick(ev) {
    var occ = occFromEvent(ev);
    if (!occ) return;
    ev.preventDefault();
    goToDefinition(occ.getAttribute("data-occurrence-id"));
  }

  function onContextMenu(ev) {
    var occ = occFromEvent(ev);
    if (!occ) return;
    ev.preventDefault();
    // #13: derive concept identity from the LIVE payload keyed by the stable
    // data-occurrence-id (mirrors onClick / goToDefinition), NOT the static
    // server-rendered data-concept-id which goes stale after refresh()/setData.
    var occId = occ.getAttribute("data-occurrence-id");
    var entry = state.data.occurrences[occId];
    var conceptId = entry && entry.concept_id;
    if (conceptId) {
      showCard(conceptId);
    } else {
      // No concept linked yet (still resolving): give feedback, don't no-op.
      flashResolving(occ);
    }
  }

  function onKeyDown(ev) {
    if (ev.key !== "Enter" && ev.key !== " ") return;
    var active = document.activeElement;
    if (!active || !active.classList || !active.classList.contains("occ")) return;
    ev.preventDefault();
    goToDefinition(active.getAttribute("data-occurrence-id"));
  }

  // #10/#11 ---- KaTeX typesetting + per-symbol anchor re-attachment --------
  //
  // A ready formula emits an (empty) <span class="katex-target" data-latex
  // data-occurrences> plus a sibling <span class="occ-fallback"> holding the
  // inline-anchored linearized text (see render.py's ready-formula DOM
  // contract). KaTeX is loaded but does nothing on its own, so we typeset
  // data-latex into the host here, then DECOUPLE the per-symbol hit targets:
  // best-effort match each token to the KaTeX glyph span(s) and tag them .occ.
  // Whatever can't be matched falls back to the still-visible .occ-fallback.

  function applyOccAttrs(node, attrsString) {
    // attrsString is the server-rendered occ attribute string, e.g.
    //   class="occ" data-occurrence-id="…" data-kind="formula_symbol" tabindex="0"
    // Parse it loosely (key="value" pairs) and apply onto an existing glyph
    // node so it becomes a hit target identical to the fallback anchor.
    var re = /([a-zA-Z0-9_-]+)="([^"]*)"/g;
    var m;
    while ((m = re.exec(attrsString)) !== null) {
      var key = m[1];
      var val = m[2];
      if (key === "class") {
        String(val)
          .split(/\s+/)
          .forEach(function (c) {
            if (c) node.classList.add(c);
          });
      } else {
        node.setAttribute(key, val);
      }
    }
  }

  function tagGlyphsForToken(host, token, attrsString, used) {
    // Find KaTeX glyph span(s) whose text equals the token's leading
    // identifier and that have not already been claimed; tag the first match.
    // KaTeX wraps identifiers/operators in .mord / .mbin / .mrel / .mopen /
    // .mclose spans. We match on a normalized first character/identifier so
    // a_n ("a") still anchors onto its base-letter glyph.
    var want = normalizeToken(token);
    if (!want) return false;
    var glyphs = host.querySelectorAll(
      ".mord, .mbin, .mrel, .mopen, .mclose, .mpunct, .mop"
    );
    for (var i = 0; i < glyphs.length; i++) {
      var g = glyphs[i];
      if (used.indexOf(g) !== -1) continue;
      // Skip composite mord wrappers (they contain nested glyph spans); prefer
      // leaf spans so the tagged target stays small.
      if (g.querySelector(".mord, .mbin, .mrel, .mopen, .mclose")) continue;
      var text = (g.textContent || "").trim();
      if (!text) continue;
      if (normalizeToken(text) === want) {
        applyOccAttrs(g, attrsString);
        used.push(g);
        return true;
      }
    }
    return false;
  }

  function normalizeToken(token) {
    if (token == null) return "";
    var s = String(token).trim();
    // Reduce a subscripted/decorated identifier to its base symbol, which is
    // what KaTeX renders as the leading glyph (a_n -> a, x_1 -> x, \varepsilon
    // -> the rendered ε is matched separately below).
    s = s.replace(/[_^].*$/, "");
    s = s.replace(/^\\/, ""); // strip a leading backslash from a latex command
    return s;
  }

  function typesetFormula(formula) {
    var host = formula.querySelector(".katex-target");
    if (!host) return;
    if (host.getAttribute("data-katex-rendered") === "1") return;
    var latex = host.getAttribute("data-latex");
    if (latex == null) return;
    if (typeof katex === "undefined" || !katex || typeof katex.render !== "function") {
      return; // KaTeX not available; .occ-fallback remains the hit-target layer
    }
    try {
      katex.render(latex, host, { throwOnError: false, displayMode: false });
    } catch (e) {
      return; // leave the fallback visible if typesetting fails
    }
    host.setAttribute("data-katex-rendered", "1");

    // Re-attach per-symbol hit targets onto the rendered glyphs.
    var tokens = readOccurrences(host);
    var fallback = formula.querySelector(".occ-fallback");
    if (!tokens.length) {
      if (fallback) fallback.hidden = true;
      return;
    }
    var used = [];
    var allMatched = true;
    for (var i = 0; i < tokens.length; i++) {
      var t = tokens[i];
      var occId = occIdFromAttrs(t.attrs);
      var matched = tagGlyphsForToken(host, t.token, t.attrs, used);
      if (matched) {
        // A matched glyph is now the canonical hit target for this id; hide the
        // duplicate fallback anchor so the two boxes don't collide on the id.
        hideFallbackAnchor(fallback, occId);
      } else {
        allMatched = false;
      }
    }
    // Every token matched -> the whole fallback is redundant; hide it outright.
    if (fallback && allMatched) fallback.hidden = true;
  }

  function occIdFromAttrs(attrsString) {
    var m = /data-occurrence-id="([^"]*)"/.exec(attrsString || "");
    return m ? m[1] : null;
  }

  function hideFallbackAnchor(fallback, occId) {
    if (!fallback || !occId) return;
    var anchor = fallback.querySelector(
      '.occ[data-occurrence-id="' + cssEscape(occId) + '"]'
    );
    if (anchor) anchor.hidden = true;
  }

  function readOccurrences(host) {
    var raw = host.getAttribute("data-occurrences");
    if (!raw) return [];
    try {
      var arr = JSON.parse(raw);
      return Array.isArray(arr) ? arr : [];
    } catch (e) {
      return [];
    }
  }

  function typesetReadyFormulas() {
    if (typeof katex === "undefined") return;
    var formulas = document.querySelectorAll('.formula[data-enrichment="ready"]');
    for (var i = 0; i < formulas.length; i++) typesetFormula(formulas[i]);
  }

  // ---- formula-upgrade + resize re-measurement ---------------------------

  function debounce(fn, ms) {
    var h = null;
    return function () {
      if (h) window.clearTimeout(h);
      h = window.setTimeout(fn, ms);
    };
  }

  function onFormulaMutation() {
    // A formula upgraded to ready (data-enrichment flipped and/or KaTeX content
    // was injected). Typeset any newly-ready formula, then re-measure. The
    // typeset/tag pass is idempotent (guarded by data-katex-rendered) so the
    // mutations IT causes don't loop.
    typesetReadyFormulas();
    measureBboxes();
  }

  function observeFormulaUpgrades() {
    if (typeof MutationObserver === "undefined") return;
    var obs = new MutationObserver(debounce(onFormulaMutation, 50));
    var formulas = document.querySelectorAll(".formula");
    for (var i = 0; i < formulas.length; i++) {
      obs.observe(formulas[i], {
        attributes: true,
        attributeFilter: ["data-enrichment"],
        childList: true,
        subtree: true,
      });
    }
  }

  function whenKatexDone(cb) {
    // KaTeX is loaded with `defer`; typeset ready formulas as soon as it (and
    // the document) are ready, then run the callback (re-measure). We also run
    // on `load` (fonts/CDN settled) as a belt-and-braces pass.
    function run() {
      typesetReadyFormulas();
      cb();
    }
    if (document.readyState === "complete") {
      run();
    } else {
      window.addEventListener("load", run, { once: true });
    }
  }

  // ---- refresh (re-read payload after resolution) ------------------------

  function refresh(dataOrUrl) {
    if (dataOrUrl == null) {
      setData(readEmbeddedPayload());
      measureBboxes();
      return Promise.resolve(state.data);
    }
    if (typeof dataOrUrl === "object") {
      setData(dataOrUrl);
      measureBboxes();
      // If the panel is open, re-render the visible card with fresh data.
      reopenVisibleCard();
      return Promise.resolve(state.data);
    }
    // Treat as a URL.
    return fetch(dataOrUrl)
      .then(function (r) {
        return r.json();
      })
      .then(function (payload) {
        setData(payload);
        measureBboxes();
        reopenVisibleCard();
        return state.data;
      });
  }

  function reopenVisibleCard() {
    var p = panel();
    if (p && !p.hidden && _openConceptId) showCard(_openConceptId);
  }

  // ---- helpers -----------------------------------------------------------

  function shortBlock(blockId) {
    if (!blockId) return "?";
    var tail = blockId.split("#").pop();
    return tail.indexOf("block/") === 0 ? tail.slice("block/".length) : tail;
  }

  function cssEscape(value) {
    if (window.CSS && typeof window.CSS.escape === "function") {
      return window.CSS.escape(value);
    }
    // Minimal fallback: escape characters special in attribute selectors.
    return String(value).replace(/["\\]/g, "\\$&");
  }

  // ---- init --------------------------------------------------------------

  function init() {
    setData(readEmbeddedPayload());

    var container = scrollContainer();
    container.addEventListener("click", onClick);
    container.addEventListener("contextmenu", onContextMenu);
    document.addEventListener("keydown", onKeyDown);

    window.addEventListener("resize", debounce(measureBboxes, RESIZE_DEBOUNCE_MS));

    measureBboxes();
    observeFormulaUpgrades();
    whenKatexDone(measureBboxes);
  }

  // Public API.
  window.mathIDE = {
    renderBboxes: renderBboxes,
    remeasure: measureBboxes,
    goToDefinition: goToDefinition,
    showCard: showCard,
    hideCard: hideCard,
    refresh: refresh,
    get data() {
      return state.data;
    },
    get bboxes() {
      return state.bboxes;
    },
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

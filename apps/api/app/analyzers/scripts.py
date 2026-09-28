"""JavaScript executed inside the browser to collect a bounded, typed payload.

The analyzer never sends raw HTML to the LLM. Instead the browser returns a
compressed, structured record of the elements that matter: geometry, a small
allowlist of computed style properties, text, and asset references. Everything
here is deterministic; no model is involved in extraction.
"""

from __future__ import annotations

# Elements that never contribute useful visual structure.
SKIP_TAGS = frozenset(
    {"script", "style", "noscript", "template", "meta", "link", "head", "br", "wbr", "source", "track"}
)

# Only these computed properties are read, so payloads stay small and stable.
STYLE_PROPERTIES = [
    "color",
    "background-color",
    "background-image",
    "font-family",
    "font-size",
    "font-weight",
    "line-height",
    "letter-spacing",
    "text-transform",
    "text-align",
    "display",
    "flex-direction",
    "flex-wrap",
    "grid-template-columns",
    "gap",
    "column-gap",
    "row-gap",
    "align-items",
    "justify-content",
    "padding-top",
    "padding-right",
    "padding-bottom",
    "padding-left",
    "margin-top",
    "border-radius",
    "border-top-width",
    # Border colour must be collected too: `border-top: 1px solid #e2e8f0`
    # leaves the side-specific colour empty in the computed style, so the
    # colour is read directly here.
    "border-top-color",
    "border-bottom-color",
    "border-left-color",
    "border-right-color",
    "box-shadow",
    "max-width",
    "width",
    "position",
    "overflow-x",
]

# A readable, stable path for a node, used as a component selector hint.
MARK_SCRIPT = """
() => {
  window.__repliuiNodes = new Map();
  window.__repliuiOrder = 0;
  window.__repliuiCounter = 0;
  window.__repliuiMark = (el) => {
    if (!el || el.nodeType !== 1) return null;
    if (el.dataset && el.dataset.repliuiId) return el.dataset.repliuiId;
    const id = 'r' + (window.__repliuiCounter++);
    el.setAttribute('data-repliui-id', id);
    window.__repliuiNodes.set(id, el);
    window.__repliuiOrder = Math.max(window.__repliuiOrder, window.__repliuiCounter);
    return id;
  };
  return true;
}
"""

# Walk the rendered tree and return one record per element worth reporting.
EXTRACT_SCRIPT = """
(cfg) => {
  const { styleProperties, skipTags, maxNodes, maxText, maxSelectors } = cfg;
  const out = [];
  const seenText = new Set();
  const isVisible = (el) => {
    const style = getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };
  const pathOf = (el) => {
    const parts = [];
    let node = el;
    let depth = 0;
    while (node && node.nodeType === 1 && depth < 4) {
      let part = node.tagName.toLowerCase();
      if (node.id) { part += '#' + node.id; }
      else {
        const cls = (node.getAttribute('class') || '').trim().split(/\\s+/).filter(Boolean).slice(0, 2);
        if (cls.length) part += '.' + cls.join('.');
      }
      parts.unshift(part);
      node = node.parentElement;
      depth++;
    }
    return parts.join(' > ');
  };
  const collectText = (el) => {
    let text = '';
    for (const child of el.childNodes) {
      if (child.nodeType === 3) text += child.textContent;
    }
    text = text.replace(/\\s+/g, ' ').trim();
    if (text.length > maxText) text = text.slice(0, maxText);
    return text;
  };
  const walk = (el, depth) => {
    if (out.length >= maxNodes || depth > 40) return;
    if (skipTags.includes(el.tagName.toLowerCase())) return;
    const visible = isVisible(el);
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    const styles = {};
    for (const prop of styleProperties) styles[prop] = style.getPropertyValue(prop);
    const own = collectText(el);
    const tag = el.tagName.toLowerCase();
    const record = {
      id: el.getAttribute('data-repliui-id') || null,
      tag,
      depth,
      visible,
      rect: {
        x: Math.round(rect.x + window.scrollX),
        y: Math.round(rect.y + window.scrollY),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
      },
      styles,
      text: own,
      ariaLabel: el.getAttribute('aria-label') || '',
      role: el.getAttribute('role') || '',
      href: tag === 'a' ? (el.getAttribute('href') || '') : '',
      childElements: el.children.length,
      selector: pathOf(el),
      attributes: {
        class: (el.getAttribute('class') || '').slice(0, 300),
        id: el.id || '',
      },
    };
    if (tag === 'img') {
      record.image = {
        src: el.currentSrc || el.src || '',
        alt: el.getAttribute('alt') || '',
        naturalWidth: el.naturalWidth || 0,
        naturalHeight: el.naturalHeight || 0,
      };
    }
    if (tag === 'svg') {
      record.svg = {
        outerLength: (el.outerHTML || '').length,
        viewBox: el.getAttribute('viewBox') || '',
        label: el.getAttribute('aria-label') || '',
      };
    }
    if (tag === 'form') {
      record.form = {
        action: el.getAttribute('action') || '',
        method: (el.getAttribute('method') || 'get').toLowerCase(),
        fields: Array.from(el.querySelectorAll('input, textarea, select')).map((f) => {
          const ftype = (f.getAttribute('type') || f.tagName.toLowerCase());
          return (f.getAttribute('name') || f.getAttribute('placeholder') || ftype || 'field').slice(0, 60);
        }).slice(0, 25),
      };
    }
    out.push(record);
    for (const child of el.children) walk(child, depth + 1);
  };
  const root = document.body || document.documentElement;
  if (root) walk(root, 0);
  return { nodes: out, truncated: out.length >= maxNodes, scrollHeight: document.documentElement.scrollHeight };
}
"""

# Measure structural relationships that need layout information.
LAYOUT_SCRIPT = """
() => {
  const rects = new Map();
  document.querySelectorAll('*').forEach((el) => {
    if (el.nodeType !== 1) return;
    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.height > 0) rects.set(el, r);
  });
  const parentOf = (el) => {
    let p = el.parentElement;
    while (p) {
      if (rects.has(p)) return p;
      p = p.parentElement;
    }
    return null;
  };
  // Repeated sibling groups are the strongest signal for card/grid patterns.
  const groups = [];
  const groupKey = (el) => {
    const style = getComputedStyle(el);
    const parent = parentOf(el);
    const parentStyle = parent ? getComputedStyle(parent) : null;
    return [
      el.tagName,
      (el.getAttribute('class') || '').split(/\\s+/).filter(Boolean).slice(0, 3).join('.'),
      parentStyle ? parentStyle.display : '',
      parentStyle ? parentStyle.gridTemplateColumns : '',
    ].join('|');
  };
  const buckets = new Map();
  rects.forEach((rect, el) => {
    const key = groupKey(el);
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key).push(el);
  });
  buckets.forEach((els, key) => {
    if (els.length < 2 || els.length > 60) return;
    const parent = parentOf(els[0]);
    if (!parent) return;
    const sameParent = els.every((e) => parentOf(e) === parent);
    if (!sameParent) return;
    const heights = els.map((e) => rects.get(e).height);
    const spread = Math.max(...heights) - Math.min(...heights);
    groups.push({
      key,
      count: els.length,
      tag: els[0].tagName.toLowerCase(),
      parentTag: parent.tagName.toLowerCase(),
      parentDisplay: getComputedStyle(parent).display,
      parentColumns: (getComputedStyle(parent).gridTemplateColumns || '').split(/\\s+/).filter(Boolean).length,
      heightSpread: Math.round(spread),
      averageHeight: Math.round(heights.reduce((a, b) => a + b, 0) / heights.length),
      sampleText: els.slice(0, 3).map((e) => (e.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 80)).filter(Boolean),
      selector: parent.tagName.toLowerCase() + (parent.className ? '.' + String(parent.className).trim().split(/\\s+/)[0] : ''),
    });
  });
  groups.sort((a, b) => b.count - a.count);
  return { groups: groups.slice(0, 25), documentHeight: document.documentElement.scrollHeight };
}
"""

# Capture text that is only present after scripts render, and document metadata.
DOCUMENT_SCRIPT = """
() => {
  const meta = {};
  document.querySelectorAll('meta[name], meta[property]').forEach((m) => {
    const key = m.getAttribute('name') || m.getAttribute('property');
    const value = m.getAttribute('content');
    if (key && value && meta[key] === undefined) meta[key] = value.slice(0, 400);
  });
  return {
    title: document.title || '',
    lang: document.documentElement.lang || '',
    meta,
    headings: Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,h6'))
      .map((h) => ({ level: Number(h.tagName[1]), text: (h.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 160) }))
      .filter((h) => h.text),
    paragraphs: Array.from(document.querySelectorAll('p'))
      .map((p) => (p.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 240))
      .filter(Boolean),
    buttons: Array.from(document.querySelectorAll('button, a[role=button], input[type=submit], [class*=btn]'))
      .map((b) => (b.innerText || b.value || b.getAttribute('aria-label') || '').replace(/\\s+/g, ' ').trim().slice(0, 80))
      .filter(Boolean),
    links: Array.from(document.querySelectorAll('a[href]'))
      .map((a) => ({ href: a.getAttribute('href') || '', text: (a.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 80) }))
      .slice(0, 400),
    nodeCount: document.querySelectorAll('*').length,
    inlineSvgCount: document.querySelectorAll('svg').length,
    formCount: document.querySelectorAll('form').length,
  };
}
"""


def extract_config(max_nodes: int = 3000, max_text: int = 2000, max_selectors: int = 40) -> dict:
    """Config object handed to the in-page extract script."""
    return {
        "styleProperties": STYLE_PROPERTIES,
        "skipTags": sorted(SKIP_TAGS),
        "maxNodes": max_nodes,
        "maxText": max_text,
        "maxSelectors": max_selectors,
    }

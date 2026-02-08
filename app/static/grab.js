(() => {
  const alreadySetup = window.__grabUiInitialized;
  if (alreadySetup) {
    return;
  }
  window.__grabUiInitialized = true;

  const state = {
    armSelection: false,
    startPoint: null,
    selectionBox: null,
  };

  const IGNORED_TAGS = new Set(["INPUT", "TEXTAREA", "SELECT"]);
  const MAX_HTML_SAMPLE = 4000;

  function createSelectionBox() {
    const box = document.createElement("div");
    box.className = "grab-selection-box";
    box.style.position = "fixed";
    box.style.pointerEvents = "none";
    box.style.zIndex = "2147483647";
    document.body.appendChild(box);
    state.selectionBox = box;
  }

  function removeSelectionBox() {
    if (state.selectionBox && state.selectionBox.parentNode) {
      state.selectionBox.parentNode.removeChild(state.selectionBox);
    }
    state.selectionBox = null;
  }

  function cleanupSelection() {
    state.armSelection = false;
    state.startPoint = null;
    removeSelectionBox();
    document.removeEventListener("mousedown", handleMouseDown, true);
    document.removeEventListener("mousemove", handleMouseMove, true);
    document.removeEventListener("mouseup", handleMouseUp, true);
  }

  function handleKeyDown(event) {
    if (event.key === "Escape" && state.armSelection) {
      event.preventDefault();
      cleanupSelection();
      return;
    }
    if ((event.key === "g" || event.key === "G") && !state.armSelection) {
      if (IGNORED_TAGS.has(event.target.tagName)) {
        return;
      }
      event.preventDefault();
      armSelector();
    }
  }

  function armSelector() {
    state.armSelection = true;
    createSelectionBox();
    document.addEventListener("mousedown", handleMouseDown, true);
    document.addEventListener("mousemove", handleMouseMove, true);
    document.addEventListener("mouseup", handleMouseUp, true);
  }

  function handleMouseDown(event) {
    if (!state.armSelection) {
      return;
    }
    if (event.button !== 0) {
      cleanupSelection();
      return;
    }
    state.startPoint = { x: event.clientX, y: event.clientY };
    updateSelectionBox(event.clientX, event.clientY);
    event.preventDefault();
  }

  function handleMouseMove(event) {
    if (!state.startPoint || !state.selectionBox) {
      return;
    }
    updateSelectionBox(event.clientX, event.clientY);
    event.preventDefault();
  }

  function handleMouseUp(event) {
    if (!state.startPoint) {
      cleanupSelection();
      return;
    }
    event.preventDefault();
    const bbox = buildBoundingBox(state.startPoint, {
      x: event.clientX,
      y: event.clientY,
    });
    cleanupSelection();
    if (bbox.width < 2 || bbox.height < 2) {
      return;
    }
    processSelection(bbox).catch((error) => {
      console.error("grab selection failed", error);
      window.alert("Grab failed. See console for details.");
    });
  }

  function updateSelectionBox(currentX, currentY) {
    if (!state.selectionBox || !state.startPoint) {
      return;
    }
    const left = Math.min(state.startPoint.x, currentX);
    const top = Math.min(state.startPoint.y, currentY);
    const width = Math.abs(state.startPoint.x - currentX);
    const height = Math.abs(state.startPoint.y - currentY);
    Object.assign(state.selectionBox.style, {
      left: `${left}px`,
      top: `${top}px`,
      width: `${width}px`,
      height: `${height}px`,
    });
  }

  function buildBoundingBox(start, end) {
    const left = Math.min(start.x, end.x);
    const top = Math.min(start.y, end.y);
    const width = Math.abs(start.x - end.x);
    const height = Math.abs(start.y - end.y);
    return {
      left,
      top,
      width,
      height,
      page_left: left + window.scrollX,
      page_top: top + window.scrollY,
      right: left + width,
      bottom: top + height,
    };
  }

  function rectsIntersect(selection, rect) {
    return !(
      rect.right < selection.left ||
      rect.left > selection.right ||
      rect.bottom < selection.top ||
      rect.top > selection.bottom
    );
  }

  function findMetaForNode(node) {
    const grabId = node.getAttribute("data-grab-id");
    if (!grabId) {
      return null;
    }
    const metaScripts = document.querySelectorAll("script[data-grab-meta]");
    let meta = null;
    metaScripts.forEach((script) => {
      if (!meta && script.getAttribute("data-grab-id") === grabId) {
        meta = script;
      }
    });
    if (!meta) return null;
    try {
      return JSON.parse(meta.textContent || meta.innerText || "{}");
    } catch (error) {
      console.warn("Failed to parse grab meta", error);
      return null;
    }
  }

  function collectSelectedRegions(selectionBBox) {
    const nodes = Array.from(document.querySelectorAll("[data-grab-id]"));
    const intersecting = [];
    nodes.forEach((node) => {
      const rect = node.getBoundingClientRect();
      if (rectsIntersect(selectionBBox, rect)) {
        const meta = findMetaForNode(node);
        if (meta && meta.template && meta.start_line) {
          intersecting.push({
            node,
            meta,
          });
        }
      }
    });
    return intersecting;
  }

  async function processSelection(selectionBBox) {
    const intersecting = collectSelectedRegions(selectionBBox);
    if (!intersecting.length) {
      window.alert("No grab markers found in that selection.");
      return;
    }
    const seen = new Set();
    const deduped = [];
    intersecting.forEach((entry) => {
      const key = `${entry.meta.template}:${entry.meta.start_line}`;
      if (!seen.has(key)) {
        seen.add(key);
        deduped.push(entry);
      }
    });
    const limited = deduped.slice(0, 20);
    const sampleHtml = limited
      .map((entry) => entry.node.outerHTML.trim())
      .join("\n\n")
      .slice(0, MAX_HTML_SAMPLE);
    const payload = {
      items: limited.map((entry) => ({
        template: entry.meta.template,
        start_line: entry.meta.start_line,
      })),
      selection_bbox: selectionBBox,
      url: window.location.href,
      html_sample: sampleHtml,
    };
    const response = await fetch("/__grab", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
      credentials: "same-origin",
    });
    if (!response.ok) {
      throw new Error(`Grab endpoint error: ${response.status}`);
    }
    const data = await response.json();
    await copyToClipboard(data, payload);
    window.alert(`Grabbed ${data.count || 0} snippet(s).`);
  }

  async function copyToClipboard(serverData, payload) {
    const parts = [];
    parts.push(`URL: ${payload.url}`);
    const bbox = payload.selection_bbox || {};
    parts.push(
      `Selection: left=${Math.round(bbox.left || 0)}, top=${Math.round(
        bbox.top || 0
      )}, width=${Math.round(bbox.width || 0)}, height=${Math.round(
        bbox.height || 0
      )}`
    );
    if (payload.html_sample) {
      parts.push("HTML Sample:\n" + payload.html_sample);
    }
    const items = serverData.items || [];
    items.forEach((item) => {
      const snippet = item.snippet || "";
      parts.push(
        [
          `Template: ${item.template}`,
          `Path: ${item.path}`,
          `Lines ${item.start_line}-${item.end_line}`,
          snippet,
        ].join("\n")
      );
    });
    const text = parts.join("\n\n---\n\n");
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      return;
    }
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand("copy");
    document.body.removeChild(textarea);
  }

  document.addEventListener("keydown", handleKeyDown);
})();

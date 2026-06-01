window.extractText = () => {
  let text = [];
  function walk(node) {
    if (node.nodeType === Node.TEXT_NODE) {
      const content = node.textContent.trim();
      if (content) text.push(content);
      return;
    }
    if (node.nodeType === Node.ELEMENT_NODE) {
      const tag = node.tagName;
      if (tag === "SCRIPT" || tag === "STYLE" || tag === "NOSCRIPT") return;
      if (node.shadowRoot) walk(node.shadowRoot);
    }
    for (const child of node.childNodes) walk(child);
  }
  walk(document.body);
  return text.join(" ");
};

// Capture a reader selection without paragraph IDs. Server verifies the complete
// capture against its pinned parser before accepting these native node paths.
export function captureSelection(document) {
  const selection = document.getSelection();
  if (!selection || selection.rangeCount !== 1) throw new Error("Select one passage.");
  const range = selection.getRangeAt(0);
  if (range.collapsed || range.startContainer.nodeType !== 3 || range.endContainer.nodeType !== 3)
    throw new Error("Selection endpoints must be text nodes.");
  const path = (node) => {
    const indices = [];
    while (node !== document) {
      if (!node.parentNode) throw new Error("Selection is detached.");
      indices.unshift(Array.prototype.indexOf.call(node.parentNode.childNodes, node));
      node = node.parentNode;
    }
    return indices;
  };
  const excluded = new Set(["HEAD", "SCRIPT", "STYLE", "TEMPLATE", "NOSCRIPT"]);
  const nodes = [];
  const visit = (node) => {
    if (node.nodeType === 1 && excluded.has(node.tagName)) return;
    if (node.nodeType === 3 && node.data.length) nodes.push([path(node), node.data]);
    for (const child of node.childNodes) visit(child);
  };
  visit(document);
  return {captured_nodes: nodes, start_path: path(range.startContainer),
    start_utf16: range.startOffset, end_path: path(range.endContainer), end_utf16: range.endOffset};
}

// Delegate so Google-autofilled forms inserted by htmx work without rebinding.
document.addEventListener("keydown", (event) => {
  const editor = event.target;
  if (!editor.matches("textarea[data-markdown-editor]") || editor.readOnly || editor.disabled) return;
  if (event.key !== "*" || event.ctrlKey || event.metaKey || event.altKey || event.isComposing) return;

  const start = editor.selectionStart;
  const end = editor.selectionEnd;
  if (start === end) return; // Ordinary typing still inserts a single asterisk.

  event.preventDefault();
  const direction = editor.selectionDirection;
  const scrollTop = editor.scrollTop;
  const scrollLeft = editor.scrollLeft;
  const selected = editor.value.slice(start, end);
  editor.setRangeText(`*${selected}*`, start, end, "select");
  // Keep just the original text selected: pressing * again produces **bold**.
  editor.setSelectionRange(start + 1, end + 1, direction);
  editor.scrollTop = scrollTop;
  editor.scrollLeft = scrollLeft;
  editor.dispatchEvent(new Event("input", { bubbles: true }));
});

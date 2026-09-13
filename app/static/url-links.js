// Keep external links in step with typed values and Google-autofilled forms.
function updateExternalLink(input) {
  const link = document.getElementById(input.dataset.externalUrl);
  if (!link) return;
  let url;
  try {
    url = new URL(input.value.trim());
  } catch (_) {
    url = null;
  }
  const valid = url && ["https:", "http:"].includes(url.protocol);
  link.hidden = !valid;
  if (valid) link.href = url.href;
  else link.removeAttribute("href");
}

function updateExternalLinks() {
  document.querySelectorAll("input[data-external-url]").forEach(updateExternalLink);
}

document.addEventListener("input", (event) => {
  if (event.target.matches("input[data-external-url]")) updateExternalLink(event.target);
});
document.addEventListener("htmx:afterSwap", updateExternalLinks);
updateExternalLinks();

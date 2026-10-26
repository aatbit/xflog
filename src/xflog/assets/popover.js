export function bindPopover(trigger, popup, placement = "below") {
  const controller = new AbortController();
  const listen = (element, name, handler) =>
    element.addEventListener(name, handler, { signal: controller.signal });
  const items = () => [...popup.querySelectorAll('[role="menuitemradio"]')];
  const position = () => {
    const rect = trigger.getBoundingClientRect();
    const width = parseFloat(getComputedStyle(popup).width) || 200;
    popup.style.left = `${Math.max(16, Math.min(rect.right - width, innerWidth - width - 16))}px`;
    popup.style.top = placement === "below" ? `${rect.bottom + 8}px` : "auto";
    popup.style.bottom =
      placement === "above" ? `${innerHeight - rect.top + 8}px` : "auto";
    popup.style.maxHeight = `${Math.max(80, placement === "above" ? rect.top - 24 : innerHeight - rect.bottom - 24)}px`;
  };
  const close = () => {
    popup.hidePopover();
    trigger.focus();
  };
  listen(popup, "beforetoggle", (event) => {
    if (event.newState === "open") position();
  });
  listen(popup, "toggle", (event) => {
    const open = event.newState === "open";
    trigger.setAttribute("aria-expanded", String(open));
    if (open)
      (popup.querySelector('[aria-checked="true"]') || items()[0])?.focus();
  });
  listen(trigger, "keydown", (event) => {
    if (!items().length || !["ArrowDown", "ArrowUp"].includes(event.key))
      return;
    event.preventDefault();
    popup.showPopover();
  });
  listen(popup, "keydown", (event) => {
    const options = items();
    const index = options.indexOf(document.activeElement);
    const keys = {
      ArrowDown: (index + 1) % options.length,
      ArrowUp: (index - 1 + options.length) % options.length,
      Home: 0,
      End: options.length - 1,
    };
    if (options.length && Object.hasOwn(keys, event.key)) {
      event.preventDefault();
      options[keys[event.key]]?.focus();
    } else if (event.key === "Escape") {
      event.preventDefault();
      close();
    } else if (event.key === "Tab") close();
  });
  const reposition = () => {
    if (popup.matches(":popover-open")) position();
  };
  listen(window, "resize", reposition);
  listen(window, "scroll", reposition);
  return { close, destroy: () => controller.abort() };
}

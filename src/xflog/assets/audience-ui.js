export function resolveLens(groups, current) {
  return groups.some((group) => group.enabled && group.key === current)
    ? current
    : "none";
}

export function createAudienceControls({ root, onToggle, onLens }) {
  const $ = (selector) => root.querySelector(selector);
  const trigger = $("#lens-trigger"),
    picker = $("#audience-lens");
  const items = () => [...picker.querySelectorAll("button")];
  const position = () => {
    const rect = trigger.getBoundingClientRect();
    picker.style.top = `${rect.bottom + 8}px`;
    picker.style.left = `${Math.max(16, Math.min(rect.right - 200, innerWidth - 216))}px`;
  };
  const close = () => {
    picker.hidePopover();
    trigger.focus();
  };
  picker.addEventListener("beforetoggle", (event) => {
    if (event.newState === "open") position();
  });
  picker.addEventListener("toggle", (event) => {
    const open = event.newState === "open";
    trigger.setAttribute("aria-expanded", String(open));
    if (open)
      (picker.querySelector('[aria-checked="true"]') || items()[0])?.focus();
  });
  trigger.addEventListener("keydown", (event) => {
    if (!["ArrowDown", "ArrowUp"].includes(event.key)) return;
    event.preventDefault();
    picker.showPopover();
  });
  picker.addEventListener("keydown", (event) => {
    const options = items(),
      index = options.indexOf(document.activeElement);
    const keys = {
      ArrowDown: (index + 1) % options.length,
      ArrowUp: (index - 1 + options.length) % options.length,
      Home: 0,
      End: options.length - 1,
    };
    if (Object.hasOwn(keys, event.key)) {
      event.preventDefault();
      options[keys[event.key]]?.focus();
    } else if (event.key === "Escape") {
      event.preventDefault();
      close();
    } else if (event.key === "Tab") close();
  });
  const resize = () => {
    if (picker.matches(":popover-open")) position();
  };
  window.addEventListener("resize", resize);
  return {
    render(groups, lens) {
      const enabled = groups.filter((group) => group.enabled);
      $("#lens-control").hidden = !enabled.length;
      $("#scene-lens-label").textContent =
        enabled.find((group) => group.key === lens)?.label || "Ungrouped";
      trigger.setAttribute(
        "aria-label",
        `Choose audience lens, current: ${enabled.find((group) => group.key === lens)?.label || "Ungrouped"}`,
      );
      if ($("#lens-control").hidden && picker.matches(":popover-open"))
        picker.hidePopover();
      picker.replaceChildren();
      for (const option of [{ key: "none", label: "Ungrouped" }, ...enabled]) {
        const item = document.createElement("button");
        item.type = "button";
        item.setAttribute("role", "menuitemradio");
        item.setAttribute("aria-checked", String(option.key === lens));
        item.tabIndex = -1;
        item.textContent = option.label;
        item.addEventListener("click", () => {
          onLens(option.key);
          close();
        });
        picker.append(item);
      }
      const settings = $("#audience-group-options");
      settings.replaceChildren();
      for (const group of groups) {
        const row = document.createElement("label");
        row.className = "switch-row";
        const copy = document.createElement("span");
        const title = document.createElement("strong");
        title.textContent = group.label;
        const description = document.createElement("small");
        description.textContent = group.description;
        copy.append(title, description);
        const toggle = document.createElement("input");
        toggle.type = "checkbox";
        toggle.setAttribute("role", "switch");
        toggle.dataset.audienceGroup = group.key;
        toggle.checked = group.enabled;
        row.append(copy, toggle);
        toggle.addEventListener("change", () => onToggle(group, toggle));
        settings.append(row);
      }
    },
    destroy() {
      window.removeEventListener("resize", resize);
    },
  };
}

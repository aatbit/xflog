import { bindPopover } from "./popover.js";

export function resolveLens(groups, current) {
  return groups.some((group) => group.enabled && group.key === current)
    ? current
    : "none";
}

export function createAudienceControls({ root, onToggle, onLens }) {
  const $ = (selector) => root.querySelector(selector);
  const trigger = $("#lens-trigger"),
    picker = $("#audience-lens");
  const menu = bindPopover(trigger, picker);
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
          menu.close();
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
      menu.destroy();
    },
  };
}

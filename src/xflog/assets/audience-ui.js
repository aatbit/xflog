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
  let helpPopovers = [];
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
      const activeId = document.activeElement?.id;
      for (const help of helpPopovers) help.destroy();
      helpPopovers = [];
      settings.replaceChildren();
      for (const group of groups) {
        const row = document.createElement("div");
        row.className = "switch-row group-setting";
        const copy = document.createElement("label");
        copy.htmlFor = `group-${group.key}`;
        const title = document.createElement("strong");
        title.textContent = group.label;
        copy.append(title);
        const description = document.createElement("div");
        description.id = `group-help-${group.key}`;
        description.className = "choice-popover setting-help";
        description.setAttribute("popover", "auto");
        description.setAttribute("role", "note");
        description.textContent = group.description;
        const help = document.createElement("button");
        help.id = `group-help-trigger-${group.key}`;
        help.type = "button";
        help.className = "setting-help-trigger";
        help.setAttribute("aria-label", `About ${group.label}`);
        help.setAttribute("aria-expanded", "false");
        help.setAttribute("popovertarget", description.id);
        help.innerHTML =
          '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v1"/></svg>';
        const toggle = document.createElement("input");
        toggle.id = copy.htmlFor;
        toggle.type = "checkbox";
        toggle.setAttribute("role", "switch");
        toggle.setAttribute("aria-describedby", description.id);
        toggle.dataset.audienceGroup = group.key;
        toggle.checked = group.enabled;
        row.append(copy, help, toggle, description);
        toggle.addEventListener("change", async () => {
          const restoreFocus = document.activeElement === toggle;
          await onToggle(group, toggle);
          if (
            restoreFocus &&
            [document.body, toggle].includes(document.activeElement)
          )
            $(`#group-${group.key}`)?.focus({ preventScroll: true });
        });
        settings.append(row);
        helpPopovers.push(bindPopover(help, description));
        for (const control of [toggle, help])
          if (activeId === control.id) control.focus({ preventScroll: true });
      }
    },
    destroy() {
      menu.destroy();
      for (const help of helpPopovers) help.destroy();
    },
  };
}

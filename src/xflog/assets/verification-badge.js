export function verificationBadge(event, modules) {
  const enabled = modules.some(
    (module) => module.key === "verification" && module.enabled,
  );
  const verified = ["verified", "blue", "business", "government"].includes(
    event.audience_groups?.verification,
  );
  if (!enabled || !verified) return "";
  return '<svg class="verified-badge" viewBox="0 0 24 24" role="img" aria-label="Verified"><circle cx="12" cy="12" r="10" fill="currentColor"/><path d="m7 12 3 3 7-7" fill="none" stroke="#eef1ed" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
}

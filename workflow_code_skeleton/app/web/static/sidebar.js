(() => {
  "use strict";

  const shell = document.querySelector(".chat-workspace-shell");
  const sidebar = document.getElementById("workspaceCard");
  const toggle = document.querySelector(".sidebar-toggle");
  const storageKey = "ideaToScript.sidebarCollapsed.v1";

  if (!shell || !sidebar || !toggle) return;

  function applyCollapsed(collapsed) {
    sidebar.classList.toggle("is-collapsed", collapsed);
    shell.classList.toggle("sidebar-collapsed", collapsed);
    toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
    try {
      window.localStorage.setItem(storageKey, collapsed ? "1" : "0");
    } catch (error) {
      // Ignore storage write failures.
    }
  }

  let stored = "";
  try {
    stored = window.localStorage.getItem(storageKey) || "";
  } catch (error) {
    stored = "";
  }

  applyCollapsed(stored === "1");
  toggle.addEventListener("click", () => {
    applyCollapsed(!sidebar.classList.contains("is-collapsed"));
  });
})();

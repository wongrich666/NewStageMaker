(() => {
  const root = document.documentElement;

  function setWallpaperDrift() {
    const x = (1.4 + Math.random() * 2.2).toFixed(2);
    const y = (1.0 + Math.random() * 1.8).toFixed(2);
    const scale = (1.025 + Math.random() * 0.025).toFixed(3);
    root.style.setProperty("--cat-drift-x", `${Math.random() > 0.5 ? "" : "-"}${x}vw`);
    root.style.setProperty("--cat-drift-y", `${Math.random() > 0.5 ? "" : "-"}${y}vh`);
    root.style.setProperty("--cat-drift-scale", scale);
  }

  function rippleAt(x, y) {
    if (!Number.isFinite(x) || !Number.isFinite(y)) return;
    const ripple = document.createElement("span");
    ripple.className = "cat-theme-ripple";
    ripple.style.left = `${x}px`;
    ripple.style.top = `${y}px`;
    document.body.appendChild(ripple);
    window.setTimeout(() => ripple.remove(), 760);
  }

  function elementCenter(element) {
    const rect = element.getBoundingClientRect();
    return {
      x: rect.left + rect.width / 2,
      y: rect.top + Math.min(rect.height / 2, 42),
    };
  }

  setWallpaperDrift();
  window.setInterval(setWallpaperDrift, 45000);

  document.addEventListener("pointerdown", (event) => {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    rippleAt(event.clientX, event.clientY);
  }, { passive: true });

  document.addEventListener("focusin", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    if (!target.matches("input, textarea, select, [contenteditable='true']")) return;
    const point = elementCenter(target);
    rippleAt(point.x, point.y);
  });
})();

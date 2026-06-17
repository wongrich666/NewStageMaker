(() => {
  const root = document.documentElement;

  function setWallpaperDrift() {
    const angle = Math.random() * Math.PI * 2;
    const angle2 = angle + Math.PI * (0.58 + Math.random() * 0.32);
    const distance = 1.2 + Math.random() * 2.4;
    const distance2 = 0.9 + Math.random() * 1.8;
    const x = (Math.cos(angle) * distance).toFixed(2);
    const y = (Math.sin(angle) * distance * 0.72).toFixed(2);
    const x2 = (Math.cos(angle2) * distance2).toFixed(2);
    const y2 = (Math.sin(angle2) * distance2 * 0.68).toFixed(2);
    const scale = (1.04 + Math.random() * 0.03).toFixed(3);
    const scale2 = (1.055 + Math.random() * 0.025).toFixed(3);
    const blur = (0.18 + Math.random() * 0.55).toFixed(2);
    root.style.setProperty("--cat-drift-x", `${x}vw`);
    root.style.setProperty("--cat-drift-y", `${y}vh`);
    root.style.setProperty("--cat-drift-scale", scale);
    root.style.setProperty("--cat-drift-x2", `${x2}vw`);
    root.style.setProperty("--cat-drift-y2", `${y2}vh`);
    root.style.setProperty("--cat-drift-scale2", scale2);
    root.style.setProperty("--cat-focus-blur", `${blur}px`);
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
  window.setInterval(setWallpaperDrift, 18000 + Math.floor(Math.random() * 9000));

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

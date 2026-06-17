(() => {
  const reduceMotionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
  const coarsePointerQuery = window.matchMedia("(pointer: coarse)");
  const root = document.documentElement;
  let animationFrame = 0;
  let animatedItems = [];
  let reduceMotion = reduceMotionQuery.matches;

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function smoothstep(value) {
    return value * value * (3 - 2 * value);
  }

  function seededValue(seed, index) {
    const x = Math.sin(seed * 127.1 + index * 311.7) * 43758.5453123;
    return (x - Math.floor(x)) * 2 - 1;
  }

  function smoothNoise(seed, time) {
    const left = Math.floor(time);
    const fraction = time - left;
    const a = seededValue(seed, left);
    const b = seededValue(seed, left + 1);
    return a + (b - a) * smoothstep(fraction);
  }

  function createElement(className, parent) {
    const element = document.createElement("span");
    element.className = className;
    parent.appendChild(element);
    return element;
  }

  function motionStrength() {
    if (reduceMotion) return 0.08;
    if (window.innerWidth < 720 || coarsePointerQuery.matches) return 0.58;
    return 1;
  }

  function buildItem(element, options) {
    return {
      element,
      seedX: options.seedX,
      seedY: options.seedY,
      baseX: options.baseX,
      baseY: options.baseY,
      amplitudeX: options.amplitudeX,
      amplitudeY: options.amplitudeY,
      speedX: options.speedX,
      speedY: options.speedY,
      baseScale: options.baseScale,
      scaleAmplitude: options.scaleAmplitude,
      scaleSpeed: options.scaleSpeed,
      baseOpacity: options.baseOpacity,
      opacityAmplitude: options.opacityAmplitude,
      opacitySpeed: options.opacitySpeed,
      blur: options.blur,
      blurAmplitude: options.blurAmplitude || 0,
      layerDepth: options.layerDepth || 1,
      phase: options.phase,
      rotate: options.rotate || 0,
      rotateAmplitude: options.rotateAmplitude || 0,
    };
  }

  function addBackground() {
    const existing = document.querySelector(".cat-theme-background");
    if (existing) existing.remove();

    const background = document.createElement("div");
    background.className = "cat-theme-background";
    background.setAttribute("aria-hidden", "true");
    document.body.prepend(background);

    const strength = motionStrength();
    const isMobile = window.innerWidth < 720 || coarsePointerQuery.matches;
    const items = [];

    items.push(buildItem(createElement("cat-theme-layer cat-theme-photo", background), {
      seedX: 11.31,
      seedY: 28.44,
      baseX: 0,
      baseY: 0,
      amplitudeX: 18 * strength,
      amplitudeY: 12 * strength,
      speedX: 0.018,
      speedY: 0.014,
      baseScale: 1.055,
      scaleAmplitude: 0.012 * strength,
      scaleSpeed: 0.12,
      baseOpacity: 0.74,
      opacityAmplitude: 0.025 * strength,
      opacitySpeed: 0.09,
      blur: 0.12,
      blurAmplitude: 0.32 * strength,
      layerDepth: 0.32,
      phase: 0.4,
    }));

    items.push(buildItem(createElement("cat-theme-layer cat-theme-haze", background), {
      seedX: 91.7,
      seedY: 19.24,
      baseX: 0,
      baseY: 0,
      amplitudeX: 32 * strength,
      amplitudeY: 20 * strength,
      speedX: 0.012,
      speedY: 0.016,
      baseScale: 1.08,
      scaleAmplitude: 0.018 * strength,
      scaleSpeed: 0.08,
      baseOpacity: 0.56,
      opacityAmplitude: 0.06 * strength,
      opacitySpeed: 0.07,
      blur: isMobile ? 12 : 18,
      blurAmplitude: isMobile ? 2 : 4,
      layerDepth: 0.18,
      phase: 2.2,
    }));

    const blobCount = isMobile ? 3 : 5;
    const blobColors = [
      "rgba(255, 219, 175, 0.33)",
      "rgba(255, 244, 202, 0.26)",
      "rgba(255, 205, 190, 0.24)",
      "rgba(244, 227, 255, 0.18)",
      "rgba(255, 236, 216, 0.28)",
    ];
    for (let index = 0; index < blobCount; index += 1) {
      const element = createElement("cat-theme-blob", background);
      element.style.setProperty("--cat-blob-size", `${isMobile ? 30 + index * 5 : 34 + index * 6}vmax`);
      element.style.setProperty("--cat-blob-bg", blobColors[index % blobColors.length]);
      element.style.setProperty("--cat-blob-blur", `${isMobile ? 18 + index * 2 : 24 + index * 3}px`);
      items.push(buildItem(element, {
        seedX: 200 + index * 17.13,
        seedY: 320 + index * 29.31,
        baseX: window.innerWidth * (0.08 + (index * 0.22) % 0.86),
        baseY: window.innerHeight * (0.12 + (index * 0.19) % 0.74),
        amplitudeX: (28 + index * 6) * strength,
        amplitudeY: (18 + index * 5) * strength,
        speedX: 0.018 + index * 0.002,
        speedY: 0.014 + index * 0.0025,
        baseScale: 0.9 + index * 0.045,
        scaleAmplitude: (0.018 + index * 0.003) * strength,
        scaleSpeed: 0.08 + index * 0.01,
        baseOpacity: 0.2 + index * 0.025,
        opacityAmplitude: 0.04 * strength,
        opacitySpeed: 0.09 + index * 0.012,
        blur: isMobile ? 16 + index * 2 : 24 + index * 3,
        blurAmplitude: isMobile ? 1.5 : 3,
        layerDepth: 0.48 + index * 0.07,
        phase: index * 1.47,
      }));
    }

    const particleCount = reduceMotion ? 0 : (isMobile ? 8 : 16);
    for (let index = 0; index < particleCount; index += 1) {
      const element = createElement("cat-theme-particle", background);
      const size = 2.2 + (index % 5) * 0.7;
      element.style.setProperty("--cat-particle-size", `${size}px`);
      items.push(buildItem(element, {
        seedX: 500 + index * 13.7,
        seedY: 710 + index * 23.9,
        baseX: window.innerWidth * ((0.07 + index * 0.137) % 0.96),
        baseY: window.innerHeight * ((0.11 + index * 0.173) % 0.92),
        amplitudeX: (18 + (index % 6) * 5) * strength,
        amplitudeY: (14 + (index % 4) * 4) * strength,
        speedX: 0.045 + (index % 4) * 0.008,
        speedY: 0.038 + (index % 5) * 0.007,
        baseScale: 0.85 + (index % 4) * 0.12,
        scaleAmplitude: 0.05 * strength,
        scaleSpeed: 0.22 + (index % 5) * 0.02,
        baseOpacity: 0.1 + (index % 5) * 0.018,
        opacityAmplitude: 0.035 * strength,
        opacitySpeed: 0.18 + (index % 4) * 0.025,
        blur: isMobile ? 0.25 : 0.45,
        blurAmplitude: 0.25,
        layerDepth: 0.85,
        phase: index * 0.83,
      }));
    }

    const lineCount = reduceMotion ? 0 : (isMobile ? 3 : 7);
    for (let index = 0; index < lineCount; index += 1) {
      const element = createElement("cat-theme-line", background);
      element.style.setProperty("--cat-line-width", `${isMobile ? 42 + index * 8 : 58 + index * 12}px`);
      items.push(buildItem(element, {
        seedX: 900 + index * 19.1,
        seedY: 980 + index * 31.4,
        baseX: window.innerWidth * ((0.13 + index * 0.19) % 0.88),
        baseY: window.innerHeight * ((0.17 + index * 0.23) % 0.82),
        amplitudeX: (20 + index * 3) * strength,
        amplitudeY: (12 + index * 2) * strength,
        speedX: 0.036 + index * 0.004,
        speedY: 0.032 + index * 0.004,
        baseScale: 1,
        scaleAmplitude: 0.045 * strength,
        scaleSpeed: 0.14 + index * 0.018,
        baseOpacity: 0.08 + index * 0.01,
        opacityAmplitude: 0.025 * strength,
        opacitySpeed: 0.13 + index * 0.014,
        blur: 0.3,
        blurAmplitude: 0.15,
        layerDepth: 0.78,
        phase: index * 1.11,
        rotate: -18 + index * 11,
        rotateAmplitude: 2.2 * strength,
      }));
    }

    animatedItems = items;
  }

  function render(timestamp) {
    const time = timestamp * 0.001;
    const strength = motionStrength();

    for (const item of animatedItems) {
      const x = item.baseX + smoothNoise(item.seedX, time * item.speedX) * item.amplitudeX * strength * item.layerDepth;
      const y = item.baseY + smoothNoise(item.seedY, time * item.speedY) * item.amplitudeY * strength * item.layerDepth;
      const scale = item.baseScale + Math.sin(time * item.scaleSpeed + item.phase) * item.scaleAmplitude * strength;
      const opacity = clamp(item.baseOpacity + Math.sin(time * item.opacitySpeed + item.phase) * item.opacityAmplitude * strength, 0, 1);
      const blur = Math.max(0, item.blur + Math.sin(time * item.opacitySpeed * 0.7 + item.phase) * item.blurAmplitude * strength);
      const rotate = item.rotate + Math.sin(time * item.scaleSpeed + item.phase) * item.rotateAmplitude * strength;
      item.element.style.transform = `translate3d(${x.toFixed(2)}px, ${y.toFixed(2)}px, 0) rotate(${rotate.toFixed(2)}deg) scale(${scale.toFixed(4)})`;
      item.element.style.opacity = opacity.toFixed(3);
      if (item.blur || item.blurAmplitude) {
        item.element.style.filter = `blur(${blur.toFixed(2)}px)`;
      }
    }

    animationFrame = window.requestAnimationFrame(render);
  }

  function startBackground() {
    if (!document.body) return;
    if (animationFrame) window.cancelAnimationFrame(animationFrame);
    addBackground();
    render(performance.now());
  }

  function rippleAt(x, y) {
    if (!Number.isFinite(x) || !Number.isFinite(y) || reduceMotion) return;
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

  function debounce(callback, delay) {
    let timer = 0;
    return () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(callback, delay);
    };
  }

  reduceMotionQuery.addEventListener?.("change", (event) => {
    reduceMotion = event.matches;
    startBackground();
  });

  window.addEventListener("resize", debounce(startBackground, 180), { passive: true });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", startBackground, { once: true });
  } else {
    startBackground();
  }

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

  root.classList.add("cat-theme-active");
})();

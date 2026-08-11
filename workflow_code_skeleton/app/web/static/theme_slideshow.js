(function () {
  const THEME_SLIDE_INTERVAL_MS = 30000;
  const STORAGE_KEY = "ideaToScript.themeSlideshow.v1";
  const SLIDES = [
    {
      id: "purple",
      image: "/static/assets/theme-bg/purple.png",
      color: "#4C2C81",
      rgb: "76, 44, 129",
      ink: "#ffffff",
      mutedInk: "rgba(255, 255, 255, 0.76)",
      border: "rgba(255, 255, 255, 0.24)",
    },
    {
      id: "blue",
      image: "/static/assets/theme-bg/blue.png",
      color: "#3162D0",
      rgb: "49, 98, 208",
      ink: "#ffffff",
      mutedInk: "rgba(255, 255, 255, 0.78)",
      border: "rgba(255, 255, 255, 0.26)",
    },
    {
      id: "yellow",
      image: "/static/assets/theme-bg/yellow.png",
      color: "#EFC987",
      rgb: "239, 201, 135",
      ink: "#211812",
      mutedInk: "rgba(33, 24, 18, 0.80)",
      border: "rgba(86, 52, 21, 0.28)",
    },
    {
      id: "pink",
      image: "/static/assets/theme-bg/pink.png",
      color: "#ED8A58",
      rgb: "237, 138, 88",
      ink: "#26150f",
      mutedInk: "rgba(38, 21, 15, 0.80)",
      border: "rgba(80, 31, 16, 0.28)",
    },
  ];

  let slideIndex = 0;
  let timer = null;
  let cycleStartedAt = 0;

  function readCycleStartedAt() {
    const now = Date.now();
    try {
      const raw = window.localStorage ? window.localStorage.getItem(STORAGE_KEY) : "";
      const parsed = raw ? JSON.parse(raw) : null;
      const value = Number(parsed && parsed.cycleStartedAt);
      if (Number.isFinite(value) && value > 0 && value <= now + THEME_SLIDE_INTERVAL_MS) {
        return value;
      }
    } catch (error) {
      // localStorage may be unavailable in some embedded contexts.
    }
    try {
      if (window.localStorage) {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ cycleStartedAt: now }));
      }
    } catch (error) {
      // Ignore storage failures; page-local timing is the fallback.
    }
    return now;
  }

  function currentSlideIndex(now) {
    const elapsed = Math.max(0, Number(now || Date.now()) - cycleStartedAt);
    return Math.floor(elapsed / THEME_SLIDE_INTERVAL_MS) % SLIDES.length;
  }

  function nextBoundaryDelay(now) {
    const elapsed = Math.max(0, Number(now || Date.now()) - cycleStartedAt);
    const offset = elapsed % THEME_SLIDE_INTERVAL_MS;
    return Math.max(250, THEME_SLIDE_INTERVAL_MS - offset);
  }

  function setClassTargets() {
    document.documentElement.classList.add("has-theme-slideshow");
    if (document.body) {
      document.body.classList.add("has-theme-slideshow");
    }
  }

  function ensureBackdrop() {
    if (!document.body) return null;
    let backdrop = document.querySelector("[data-theme-slideshow-backdrop]");
    if (backdrop) return backdrop;
    backdrop = document.createElement("div");
    backdrop.className = "theme-slideshow-backdrop";
    backdrop.setAttribute("data-theme-slideshow-backdrop", "");
    backdrop.setAttribute("aria-hidden", "true");
    backdrop.innerHTML = [
      '<div class="theme-slideshow-bg is-active" data-theme-slideshow-layer="0"></div>',
      '<div class="theme-slideshow-bg" data-theme-slideshow-layer="1"></div>',
      '<div class="theme-slideshow-vignette"></div>',
    ].join("");
    document.body.insertBefore(backdrop, document.body.firstChild);
    return backdrop;
  }

  function preloadSlides() {
    SLIDES.forEach((slide) => {
      const image = new Image();
      image.src = slide.image;
    });
  }

  function setRootVars(slide) {
    const root = document.documentElement;
    root.dataset.themeSlide = slide.id;
    root.style.setProperty("--theme-color", slide.color);
    root.style.setProperty("--theme-rgb", slide.rgb);
    root.style.setProperty("--theme-ink", slide.ink);
    root.style.setProperty("--theme-muted-ink", slide.mutedInk);
    root.style.setProperty("--theme-border", slide.border);
    root.style.setProperty("--color-primary", slide.color);
    root.style.setProperty("--color-primary-strong", slide.color);
    root.style.setProperty("--color-primary-soft", `rgba(${slide.rgb}, 0.18)`);
    root.style.setProperty("--color-border", slide.border);
    root.style.setProperty("--color-text", slide.ink);
    root.style.setProperty("--color-muted", slide.mutedInk);
    root.style.setProperty("--text", slide.ink);
    root.style.setProperty("--muted", slide.mutedInk);
    root.style.setProperty("--line", slide.border);
    root.style.setProperty("--fp-theme-color", slide.color);
    root.style.setProperty("--fp-theme-rgb", slide.rgb);
    root.style.setProperty("--fp-theme-ink", slide.ink);
    root.style.setProperty("--fp-theme-muted-ink", slide.mutedInk);
    root.style.setProperty("--fp-theme-border", slide.border);
    root.style.setProperty("--fp-blue", slide.color);
    root.style.setProperty("--fp-blue-dark", slide.color);
    root.style.setProperty("--fp-blue-soft", `rgba(${slide.rgb}, 0.18)`);
    root.style.setProperty("--fp-primary", slide.color);
    root.style.setProperty("--fp-primary-hover", slide.color);
    root.style.setProperty("--wts-strong", slide.color);
    root.style.setProperty("--wts-text", slide.ink);
    root.style.setProperty("--wts-muted", slide.mutedInk);
    root.style.setProperty("--wts-border", slide.border);
  }

  function applySlide(index, options) {
    const slide = SLIDES[index % SLIDES.length];
    const instant = Boolean(options && options.instant);
    setClassTargets();
    setRootVars(slide);

    const backdrop = ensureBackdrop();
    if (!backdrop) return;
    const layers = Array.from(backdrop.querySelectorAll("[data-theme-slideshow-layer]"));
    if (layers.length < 2) return;
    const activeLayer = layers.find((layer) => layer.classList.contains("is-active")) || layers[0];
    const nextLayer = layers.find((layer) => layer !== activeLayer) || layers[1];
    const zoomClass = index % 2 === 0 ? "is-zoom-a" : "is-zoom-b";

    if (instant) {
      activeLayer.style.backgroundImage = `url("${slide.image}")`;
      activeLayer.classList.remove("is-zoom-a", "is-zoom-b");
      activeLayer.classList.add("is-active", zoomClass);
      nextLayer.classList.remove("is-active", "is-zoom-a", "is-zoom-b");
      return;
    }

    nextLayer.style.backgroundImage = `url("${slide.image}")`;
    nextLayer.classList.remove("is-zoom-a", "is-zoom-b");
    nextLayer.classList.add(zoomClass);
    window.requestAnimationFrame(() => {
      nextLayer.classList.add("is-active");
      activeLayer.classList.remove("is-active");
    });
  }

  function startThemeSlideshow() {
    if (window.__ideaToScriptThemeSlideshowStarted) return;
    window.__ideaToScriptThemeSlideshowStarted = true;
    setClassTargets();
    preloadSlides();
    cycleStartedAt = readCycleStartedAt();
    slideIndex = currentSlideIndex();
    applySlide(slideIndex, { instant: true });
    const scheduleNext = () => {
      if (timer) window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        slideIndex = currentSlideIndex();
        applySlide(slideIndex);
        scheduleNext();
      }, nextBoundaryDelay());
    };
    scheduleNext();
  }

  document.addEventListener("visibilitychange", () => {
    if (document.hidden || !window.__ideaToScriptThemeSlideshowStarted) return;
    const nextIndex = currentSlideIndex();
    if (nextIndex !== slideIndex) {
      slideIndex = nextIndex;
      applySlide(slideIndex);
    }
  });

  window.ideaToScriptThemeSlideshow = {
    slides: SLIDES.slice(),
    applySlide,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", startThemeSlideshow, { once: true });
  } else {
    startThemeSlideshow();
  }
})();

class ParticleSystem {
  constructor(canvasId) {
    this.canvas = document.getElementById(canvasId);
    if (!this.canvas) return;
    this.ctx = this.canvas.getContext('2d');
    this.particles = [];
    this.links = [];
    this.mouse = { x: null, y: null, radius: 150 };
    this.animationId = null;
    this.isRunning = false;

    this.config = {
      particleCount: 200,
      particleSizeMin: 2,
      particleSizeMax: 8,
      particleSpeed: 0.8,
      linkDistance: 180,
      linkOpacity: 0.35,
      mouseInfluence: 30,
      colors: ['#635bff', '#00d4ff', '#6366f1', '#8b5cf6', '#a78bfa', '#22d3ee', '#a855f7'],
      bgGradient: ['#0f172a', '#1e1b4b', '#312e81']
    };

    this.init();
  }

  init() {
    this.resize();
    this.handleResize = () => this.resize();
    this.handleMouseMove = (e) => this.onMouseMove(e);
    this.handleMouseLeave = () => this.onMouseLeave();
    window.addEventListener('resize', this.handleResize);
    window.addEventListener('mousemove', this.handleMouseMove);
    window.addEventListener('mouseleave', this.handleMouseLeave);

    this.createParticles();
    this.start();
  }

  resize() {
    this.canvas.width = window.innerWidth;
    this.canvas.height = window.innerHeight;
  }

  onMouseMove(e) {
    const rect = this.canvas.getBoundingClientRect();
    this.mouse.x = e.clientX - rect.left;
    this.mouse.y = e.clientY - rect.top;
  }

  onMouseLeave() {
    this.mouse.x = null;
    this.mouse.y = null;
  }

  createParticles() {
    this.particles = [];
    for (let i = 0; i < this.config.particleCount; i++) {
      this.particles.push(this.createParticle());
    }
  }

  createParticle() {
    const size = this.config.particleSizeMin + Math.random() * (this.config.particleSizeMax - this.config.particleSizeMin);
    return {
      x: Math.random() * this.canvas.width,
      y: Math.random() * this.canvas.height,
      size: size,
      baseSize: size,
      vx: (Math.random() - 0.5) * this.config.particleSpeed * 2,
      vy: (Math.random() - 0.5) * this.config.particleSpeed * 2,
      color: this.config.colors[Math.floor(Math.random() * this.config.colors.length)],
      opacity: 0.6 + Math.random() * 0.4,
      baseOpacity: 0.6 + Math.random() * 0.4,
      twinkleSpeed: 0.02 + Math.random() * 0.03,
      twinklePhase: Math.random() * Math.PI * 2
    };
  }

  update() {
    for (let particle of this.particles) {
      particle.x += particle.vx;
      particle.y += particle.vy;

      if (particle.x < 0 || particle.x > this.canvas.width) particle.vx *= -1;
      if (particle.y < 0 || particle.y > this.canvas.height) particle.vy *= -1;

      if (this.mouse.x !== null && this.mouse.y !== null) {
        const dx = this.mouse.x - particle.x;
        const dy = this.mouse.y - particle.y;
        const distance = Math.sqrt(dx * dx + dy * dy);

        if (distance < this.mouse.radius) {
          const force = (this.mouse.radius - distance) / this.mouse.radius;
          const safeDistance = Math.max(distance, 1);
          particle.x -= (dx / safeDistance) * force * this.config.mouseInfluence * 0.5;
          particle.y -= (dy / safeDistance) * force * this.config.mouseInfluence * 0.5;

          const scale = 1 + force * 2;
          particle.size = particle.baseSize * scale;
          particle.opacity = particle.baseOpacity + force * 0.4;
        } else {
          particle.size += (particle.baseSize - particle.size) * 0.05;
          particle.opacity += (particle.baseOpacity - particle.opacity) * 0.05;
        }
      } else {
        particle.size += (particle.baseSize - particle.size) * 0.05;
        particle.opacity += (particle.baseOpacity - particle.opacity) * 0.05;
      }

      particle.twinklePhase += particle.twinkleSpeed;
      const twinkle = Math.sin(particle.twinklePhase) * 0.2 + 0.8;
      particle.opacity *= twinkle;
    }

    this.calculateLinks();
  }

  calculateLinks() {
    this.links = [];
    for (let i = 0; i < this.particles.length; i++) {
      for (let j = i + 1; j < this.particles.length; j++) {
        const p1 = this.particles[i];
        const p2 = this.particles[j];
        const dx = p1.x - p2.x;
        const dy = p1.y - p2.y;
        const distance = Math.sqrt(dx * dx + dy * dy);

        if (distance < this.config.linkDistance) {
          const opacity = (1 - distance / this.config.linkDistance) * this.config.linkOpacity;
          this.links.push({ p1, p2, opacity });
        }
      }
    }
  }

  draw() {
    this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

    for (let link of this.links) {
      this.ctx.beginPath();
      this.ctx.moveTo(link.p1.x, link.p1.y);
      this.ctx.lineTo(link.p2.x, link.p2.y);
      this.ctx.strokeStyle = `rgba(120, 120, 255, ${link.opacity * 1.5})`;
      this.ctx.lineWidth = 1;
      this.ctx.stroke();
    }

    for (let particle of this.particles) {
      const gradient = this.ctx.createRadialGradient(
        particle.x, particle.y, 0,
        particle.x, particle.y, particle.size * 4
      );
      gradient.addColorStop(0, particle.color);
      gradient.addColorStop(0.4, particle.color);
      gradient.addColorStop(1, 'transparent');

      this.ctx.beginPath();
      this.ctx.arc(particle.x, particle.y, particle.size * 4, 0, Math.PI * 2);
      this.ctx.fillStyle = gradient;
      this.ctx.globalAlpha = particle.opacity * 0.8;
      this.ctx.fill();
      this.ctx.globalAlpha = 1;

      this.ctx.beginPath();
      this.ctx.arc(particle.x, particle.y, particle.size, 0, Math.PI * 2);
      this.ctx.fillStyle = '#ffffff';
      this.ctx.globalAlpha = particle.opacity;
      this.ctx.fill();
      this.ctx.globalAlpha = 1;
    }
  }

  animate() {
    if (!this.isRunning) return;
    this.update();
    this.draw();
    this.animationId = requestAnimationFrame(() => this.animate());
  }

  start() {
    if (this.isRunning) return;
    this.isRunning = true;
    this.animate();
  }

  stop() {
    this.isRunning = false;
    if (this.animationId) {
      cancelAnimationFrame(this.animationId);
    }
  }

  destroy() {
    this.stop();
    window.removeEventListener('resize', this.handleResize);
    window.removeEventListener('mousemove', this.handleMouseMove);
    window.removeEventListener('mouseleave', this.handleMouseLeave);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  const particleCanvas = document.getElementById('particles-canvas');
  if (particleCanvas) {
    window.workspaceParticles = new ParticleSystem('particles-canvas');
  }
});

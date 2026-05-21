/**
 * ============================================================================
 * Cinematic Portrait Animation Studio Engine v2.0
 * ============================================================================
 * A production-grade scene compositor for 1080×1920 (9:16) portrait canvas.
 *
 * Architecture:
 *  - 6-Phase per-story timeline (Hook → Context Rise → Context Hold →
 *    Update Reveal → Impact Build → Outro)
 *  - Composable per-slide scene layers (particle_burst, shockwave,
 *    glitch_overlay, data_stream, constellation, heat_haze)
 *  - 5 headline entrance styles (slam_down, zoom_in, glitch_reveal,
 *    wave_rise, typewriter)
 *  - 4 narrative card styles (glassmorphic_slide, terminal_print,
 *    holographic, ticker_tape)
 *  - 7 background themes (cyberpunk_particles, synthwave_grid,
 *    organic_waves, matrix_rain, dna_helix, neural_network, city_skyline)
 *  - Full per-slide visual identity: unique theme, palette, layers, typography
 * ============================================================================
 */

class AnimationEngine {
  constructor(canvasId) {
    this.canvas = document.getElementById(canvasId);
    this.ctx    = this.canvas.getContext('2d');

    // Logical 9:16 portrait resolution
    this.width  = 1080;
    this.height = 1920;

    // ── Core Playback State ──────────────────────────────────────────────────
    this.config           = null;
    this.currentSlideIndex = 0;
    this.slideProgress    = 0;     // 0.0 → 1.0 within current slide
    this.isPlaying        = false;
    this.speed            = 1.0;
    this.lastTime         = 0;
    this.timelineMs       = 0;

    // ── Background Environment State ─────────────────────────────────────────
    this.particles        = [];
    this.gridOffset       = 0;
    this.wavePhase        = 0;
    this.matrixColumns    = [];
    this.helixRotation    = 0;
    this.neuralNodes      = [];
    this.cityBuildings    = [];

    // Cross-fade transition between slides
    this.prevBackground   = null;
    this.themeTransition  = 1.0;

    // ── Scene Layer State ────────────────────────────────────────────────────
    this.activeSceneLayers    = [];   // Currently rendered scene layers
    this.shockwaveRings       = [];
    this.dataStreamColumns    = [];
    this.dataStreamRows       = [];
    this.constellationNodes   = [];
    this.burstParticles       = [];   // General burst pool
    this.glitchActive         = false;
    this.glitchAlpha          = 0;
    this.heatHazePhase        = 0;
    this.heatHazeActive       = false;
    this.triggeredLayers      = new Set();  // Which layers have already fired

    // ── Visual Metaphor State ────────────────────────────────────────────────
    this.metaphorAngle    = 0;
    this.metaphorPulse    = 0;
    this.flameParticles   = [];
    this.shieldPulsers    = [];
    this.alertPulsers     = [];
    this.terminalLines    = [
      "const model = new EdgeLLM();",
      "await model.loadWeights();",
      "model.think(); // on-device",
      "const out = model.stream();"
    ];
    this.terminalCharIdx  = 0;
    this.terminalLineIdx  = 0;
    this.terminalCursorBlink = 0;

    // ── Headline Entrance State ───────────────────────────────────────────────
    this.headlineLetters  = [];   // Per-letter animation states
    this.headlineReady    = false;

    // ── Ticker State ─────────────────────────────────────────────────────────
    this.tickerOffset     = 0;

    // ── Terminal Print State ──────────────────────────────────────────────────
    this.termPrintLines   = {};   // keyed by phase name

    // ── Callbacks ────────────────────────────────────────────────────────────
    this.onSlideChange = null;
    this.onComplete    = null;
  }

  // ══════════════════════════════════════════════════════════════════════════
  //  CONFIG & SLIDE MANAGEMENT
  // ══════════════════════════════════════════════════════════════════════════

  loadConfig(config) {
    this.config           = config;
    this.currentSlideIndex = 0;
    this.slideProgress    = 0;
    this.timelineMs       = 0;
    this.isPlaying        = false;
    this.prevBackground   = null;
    this.themeTransition  = 1.0;
    this._resetSlideState();
    this.initBackground(this.getCurrentSlide());
    this.render(0);
  }

  getCurrentSlide() {
    if (!this.config || !this.config.slides || !this.config.slides.length) return null;
    return this.config.slides[this.currentSlideIndex];
  }

  _resetSlideState() {
    this.burstParticles      = [];
    this.shockwaveRings      = [];
    this.dataStreamColumns   = [];
    this.dataStreamRows      = [];
    this.constellationNodes  = [];
    this.glitchActive        = false;
    this.glitchAlpha         = 0;
    this.heatHazeActive      = false;
    this.heatHazePhase       = 0;
    this.triggeredLayers     = new Set();
    this.headlineLetters     = [];
    this.headlineReady       = false;
    this.terminalCharIdx     = 0;
    this.terminalLineIdx     = 0;
    this.tickerOffset        = 0;
    this.termPrintLines      = {};
    this.flameParticles      = [];
    this.shieldPulsers       = [];
    this.alertPulsers        = [];
    this.metaphorAngle       = 0;
  }

  play() {
    if (!this.config) return;
    this.isPlaying = true;
    this.lastTime  = performance.now();
    requestAnimationFrame(t => this.loop(t));
  }

  pause() { this.isPlaying = false; }

  startExport() {
    this.isExporting = true;
    this.pause();
    this.lastTime = performance.now();
    this.exportInterval = setInterval(() => {
      const fixedDelta = 1000 / 60;
      this.update(fixedDelta, this.lastTime + fixedDelta);
      this.render(fixedDelta);
      this.lastTime += fixedDelta;
    }, 1000 / 60);
  }

  stopExport() {
    this.isExporting = false;
    if (this.exportInterval) {
      clearInterval(this.exportInterval);
      this.exportInterval = null;
    }
  }

  setSlide(index) {
    if (!this.config || index < 0 || index >= this.config.slides.length) return;

    const oldSlide = this.getCurrentSlide();
    if (oldSlide) {
      this.prevBackground = {
        theme: oldSlide.theme || this.config.theme || 'cyberpunk_particles',
        colors: oldSlide.theme_colors || this.config.theme_colors || ["#00ffcc","#ff007f","#06060e"],
        particles: JSON.parse(JSON.stringify(this.particles)),
        matrixColumns: JSON.parse(JSON.stringify(this.matrixColumns)),
        gridOffset: this.gridOffset,
        wavePhase: this.wavePhase,
        helixRotation: this.helixRotation,
        neuralNodes: JSON.parse(JSON.stringify(this.neuralNodes)),
        cityBuildings: JSON.parse(JSON.stringify(this.cityBuildings)),
      };
      this.themeTransition = 0.0;
    }

    this.currentSlideIndex = index;
    this.slideProgress     = 0;
    this.timelineMs        = 0;
    this._resetSlideState();
    this.initBackground(this.getCurrentSlide());
    this.render(0);
    if (this.onSlideChange) this.onSlideChange(index);
  }

  setSpeed(val) { this.speed = parseFloat(val); }

  // ══════════════════════════════════════════════════════════════════════════
  //  BACKGROUND INITIALIZATION
  // ══════════════════════════════════════════════════════════════════════════

  initBackground(slide) {
    if (!this.config || !slide) return;
    const colors = slide.theme_colors || this.config.theme_colors || ["#00ffcc","#ff007f","#06060e"];
    const density = this.config.particle_density || 60;
    const speedCoeff = this.config.animation_speed || 1.0;
    const theme = slide.theme || this.config.theme || 'cyberpunk_particles';

    this.particles     = [];
    this.gridOffset    = 0;
    this.wavePhase     = 0;
    this.helixRotation = 0;
    this.matrixColumns = [];
    this.neuralNodes   = [];
    this.cityBuildings = [];

    if (theme === 'cyberpunk_particles') {
      for (let i = 0; i < density; i++) {
        this.particles.push({
          x: Math.random() * this.width,
          y: Math.random() * this.height,
          vx: (Math.random() - 0.5) * 3 * speedCoeff,
          vy: (Math.random() - 0.5) * 3 * speedCoeff,
          radius: Math.random() * 5 + 3,
          color: i % 2 === 0 ? colors[0] : colors[1]
        });
      }
    }

    if (theme === 'matrix_rain') {
      const colWidth = 36;
      const colCount = Math.ceil(this.width / colWidth);
      for (let i = 0; i < colCount; i++) {
        this.matrixColumns.push({
          x: i * colWidth,
          y: Math.random() * -1000,
          speed: (Math.random() * 6 + 5) * speedCoeff,
          chars: Array.from({length: 25}, () => Math.random() > 0.5 ? '1' : '0')
        });
      }
    }

    if (theme === 'neural_network') {
      // Randomized brain-like node graph
      for (let i = 0; i < density; i++) {
        this.neuralNodes.push({
          x: 80 + Math.random() * (this.width - 160),
          y: 80 + Math.random() * (this.height - 160),
          vx: (Math.random() - 0.5) * 1.2 * speedCoeff,
          vy: (Math.random() - 0.5) * 1.2 * speedCoeff,
          radius: Math.random() * 7 + 4,
          pulse: Math.random() * Math.PI * 2,
          color: i % 3 === 0 ? colors[0] : i % 3 === 1 ? colors[1] : '#ffffff'
        });
      }
    }

    if (theme === 'city_skyline') {
      // Procedural neon skyline buildings
      const buildingCount = 24;
      let xPos = -20;
      for (let i = 0; i < buildingCount; i++) {
        const w = 30 + Math.random() * 80;
        const h = 200 + Math.random() * 700;
        this.cityBuildings.push({
          x: xPos,
          w: w,
          h: h,
          y: this.height - h - 120,
          color: i % 2 === 0 ? colors[0] : colors[1],
          windows: Array.from({length: Math.floor(h / 30)}, () => Math.random() > 0.35)
        });
        xPos += w + 6 + Math.random() * 14;
      }
    }

    // Initialize constellation nodes
    this.constellationNodes = [];
    for (let i = 0; i < 20; i++) {
      this.constellationNodes.push({
        x: 100 + Math.random() * (this.width - 200),
        y: 200 + Math.random() * (this.height - 400),
        r: Math.random() * 5 + 2,
        vx: (Math.random() - 0.5) * 0.6,
        vy: (Math.random() - 0.5) * 0.6,
        color: colors[0]
      });
    }
  }

  // ══════════════════════════════════════════════════════════════════════════
  //  MAIN LOOP
  // ══════════════════════════════════════════════════════════════════════════

  loop(timestamp) {
    if (!this.isPlaying) return;
    const delta = (timestamp - this.lastTime) * this.speed;
    this.lastTime = timestamp;
    this.update(delta, timestamp);
    this.render(delta);
    requestAnimationFrame(t => this.loop(t));
  }

  update(delta, timestamp = 0) {
    if (!this.config) return;
    const slide = this.getCurrentSlide();
    if (!slide) return;

    const duration   = slide.duration_ms || 40000;
    const speedCoeff = this.config.animation_speed || 1.0;

    this.timelineMs   += delta;
    this.slideProgress = Math.min(1.0, this.timelineMs / duration);
    const t = this.slideProgress;

    // ── Check Scene Layer Triggers ───────────────────────────────────────────
    const layers = slide.scene_layers || [];
    for (let i = 0; i < layers.length; i++) {
      const layer = layers[i];
      const key   = `${i}_${layer.type}`;
      if (!this.triggeredLayers.has(key) && t >= layer.trigger_at) {
        this.triggeredLayers.add(key);
        this._triggerSceneLayer(layer, slide);
      }
    }

    // ── Update Background State ──────────────────────────────────────────────
    const theme = slide.theme || this.config.theme || 'cyberpunk_particles';
    this._updateBg(theme, this.particles, this.matrixColumns, 1.0, delta, speedCoeff);
    if (this.themeTransition < 1.0 && this.prevBackground) {
      this._updateBg(this.prevBackground.theme, this.prevBackground.particles, this.prevBackground.matrixColumns, 0.6, delta, speedCoeff);
      this.themeTransition = Math.min(1.0, this.themeTransition + delta / 900);
    }

    // Neural nodes bounce update
    if (theme === 'neural_network') {
      this.neuralNodes.forEach(n => {
        n.x += n.vx * (delta / 16.66);
        n.y += n.vy * (delta / 16.66);
        n.pulse += 0.04 * (delta / 16.66);
        if (n.x < 60 || n.x > this.width - 60)  n.vx *= -1;
        if (n.y < 60 || n.y > this.height - 60)  n.vy *= -1;
      });
    }

    // Constellation drift
    this.constellationNodes.forEach(n => {
      n.x += n.vx * (delta / 16.66);
      n.y += n.vy * (delta / 16.66);
      if (n.x < 50 || n.x > this.width - 50)  n.vx *= -1;
      if (n.y < 100 || n.y > this.height - 100) n.vy *= -1;
    });

    // ── Update Visual Metaphor ───────────────────────────────────────────────
    this.metaphorAngle += 0.02 * (delta / 16.66);
    this.metaphorPulse  = Math.sin((timestamp || 0) * 0.003) * 12;

    // ── Update Scene Layer Particles ─────────────────────────────────────────
    // Burst particles
    for (let i = this.burstParticles.length - 1; i >= 0; i--) {
      const p = this.burstParticles[i];
      p.x    += p.vx * (delta / 16.66);
      p.y    += p.vy * (delta / 16.66);
      p.vy   += p.gravity * (delta / 16.66);
      p.alpha = Math.max(0, p.alpha - p.decay * (delta / 16.66));
      if (p.alpha <= 0) this.burstParticles.splice(i, 1);
    }

    // Shockwave rings
    for (let i = this.shockwaveRings.length - 1; i >= 0; i--) {
      const r = this.shockwaveRings[i];
      r.radius += r.speed * (delta / 16.66);
      r.alpha   = Math.max(0, r.alpha - r.decay * (delta / 16.66));
      if (r.alpha <= 0) this.shockwaveRings.splice(i, 1);
    }

    // Glitch fade out
    if (this.glitchActive) {
      this.glitchAlpha = Math.max(0, this.glitchAlpha - 0.03 * (delta / 16.66));
      if (this.glitchAlpha <= 0) this.glitchActive = false;
    }

    // Heat haze phase
    if (this.heatHazeActive) {
      this.heatHazePhase += 0.04 * (delta / 16.66);
    }

    // Data stream update
    this.dataStreamColumns.forEach(c => {
      c.y += c.speed * (delta / 16.66);
      if (c.y > this.height + 200) c.y = -Math.random() * 500;
    });
    this.dataStreamRows.forEach(r => {
      r.x += r.speed * (delta / 16.66);
      if (r.x > this.width + 200) r.x = -Math.random() * 400;
    });

    // ── Slide Progression ─────────────────────────────────────────────────────
    if (this.timelineMs >= duration) {
      if (this.currentSlideIndex < this.config.slides.length - 1) {
        this.setSlide(this.currentSlideIndex + 1);
      } else {
        this.isPlaying     = false;
        this.slideProgress = 1.0;
        this.render(0);
        if (this.onComplete) this.onComplete();
      }
    }

    // ── Headline letter spring update ─────────────────────────────────────────
    this.headlineLetters.forEach(l => {
      if (!l.settled) {
        l.vy  += (l.targetY - l.y) * 0.14 * (delta / 16.66);
        l.vx  += (l.targetX - l.x) * 0.14 * (delta / 16.66);
        l.y   += l.vy;
        l.x   += l.vx;
        l.vy  *= 0.72;
        l.vx  *= 0.72;
        l.scale = Math.min(1.0, l.scale + 0.04 * (delta / 16.66));
        if (Math.abs(l.y - l.targetY) < 0.5 && Math.abs(l.vy) < 0.3) {
          l.y      = l.targetY;
          l.x      = l.targetX;
          l.settled = true;
          l.scale  = 1.0;
        }
      }
      // Ticker tape movement
      if (l.tickerMode) {
        l.x -= 2.2 * (delta / 16.66);
      }
    });
  }

  // ══════════════════════════════════════════════════════════════════════════
  //  SCENE LAYER TRIGGER
  // ══════════════════════════════════════════════════════════════════════════

  _triggerSceneLayer(layer, slide) {
    const colors = slide.theme_colors || ["#00ffcc","#ff007f","#06060e"];
    const col    = layer.color || colors[0];
    const intens = layer.intensity || 0.5;

    switch (layer.type) {
      case 'particle_burst': {
        const count = layer.count || 60;
        for (let i = 0; i < count; i++) {
          const angle = Math.random() * Math.PI * 2;
          const speed = (5 + Math.random() * 14) * intens;
          this.burstParticles.push({
            x: 540 + (Math.random() - 0.5) * 200,
            y: 900 + (Math.random() - 0.5) * 200,
            vx: Math.cos(angle) * speed,
            vy: Math.sin(angle) * speed - 3,
            gravity: 0.08,
            radius: Math.random() * 7 + 3,
            color: Math.random() > 0.45 ? col : colors[1],
            alpha: 1.0,
            decay: 0.012 + Math.random() * 0.01
          });
        }
        break;
      }
      case 'shockwave': {
        const waves = Math.ceil(intens * 3);
        for (let w = 0; w < waves; w++) {
          setTimeout(() => {
            this.shockwaveRings.push({
              x: 540, y: 960,
              radius: 30 + w * 40,
              speed: 14 + w * 4,
              alpha: 0.9 * intens,
              decay: 0.008,
              color: col,
              width: 4 - w
            });
          }, w * 180);
        }
        break;
      }
      case 'glitch_overlay': {
        this.glitchActive = true;
        this.glitchAlpha  = intens;
        break;
      }
      case 'data_stream': {
        const dir = layer.direction || 'vertical';
        if (dir === 'vertical') {
          for (let i = 0; i < 18; i++) {
            this.dataStreamColumns.push({
              x: 60 + Math.random() * (this.width - 120),
              y: -Math.random() * 600,
              speed: (3 + Math.random() * 6) * intens,
              chars: Array.from({length: 20}, () => '01ABCDEF'[Math.floor(Math.random()*8)]),
              color: col,
              alpha: 0.3 + Math.random() * 0.4
            });
          }
        } else {
          for (let i = 0; i < 12; i++) {
            this.dataStreamRows.push({
              x: -Math.random() * 400,
              y: 200 + Math.random() * 1500,
              speed: (2 + Math.random() * 5) * intens,
              text: '→ ' + Array.from({length: 30}, () => '01ABCDEF'[Math.floor(Math.random()*8)]).join(' '),
              color: col,
              alpha: 0.25 + Math.random() * 0.35
            });
          }
        }
        break;
      }
      case 'constellation': {
        // Snap constellation nodes into a recognizable geometric shape
        const cx = 540, cy = 460;
        this.constellationNodes = this.constellationNodes.map((n, i) => ({
          ...n,
          color: col,
          targetX: cx + Math.cos((i / this.constellationNodes.length) * Math.PI * 2) * 250,
          targetY: cy + Math.sin((i / this.constellationNodes.length) * Math.PI * 2) * 250,
        }));
        break;
      }
      case 'heat_haze': {
        this.heatHazeActive = true;
        this.heatHazePhase  = 0;
        break;
      }
    }
  }

  // ══════════════════════════════════════════════════════════════════════════
  //  BACKGROUND PHYSICS UPDATE
  // ══════════════════════════════════════════════════════════════════════════

  _updateBg(theme, particles, columns, modifier, delta, speedCoeff) {
    if (theme === 'cyberpunk_particles' && particles) {
      particles.forEach(p => {
        p.x += p.vx * (delta / 16.66) * modifier;
        p.y += p.vy * (delta / 16.66) * modifier;
        if (p.x < 0 || p.x > this.width)  p.vx *= -1;
        if (p.y < 0 || p.y > this.height) p.vy *= -1;
      });
    }
    if (theme === 'synthwave_grid') {
      this.gridOffset = (this.gridOffset + 0.12 * delta * speedCoeff * modifier) % 60;
    }
    if (theme === 'organic_waves') {
      this.wavePhase += 0.0022 * delta * speedCoeff * modifier;
    }
    if (theme === 'matrix_rain' && columns) {
      columns.forEach(c => {
        c.y += c.speed * (delta / 16.66) * modifier;
        if (c.y > this.height + 400) {
          c.y     = -Math.random() * 800;
          c.speed = (Math.random() * 6 + 5) * speedCoeff;
        }
      });
    }
    if (theme === 'dna_helix') {
      this.helixRotation += 0.0018 * delta * speedCoeff * modifier;
    }
  }

  // ══════════════════════════════════════════════════════════════════════════
  //  MASTER RENDER
  // ══════════════════════════════════════════════════════════════════════════

  render(delta) {
    if (!this.config) return;
    const ctx   = this.ctx;
    const slide = this.getCurrentSlide();
    if (!slide) return;

    const colors = slide.theme_colors || this.config.theme_colors || ["#00ffcc","#ff007f","#06060e"];

    // 1. Fill background
    ctx.fillStyle = colors[2] || '#05050b';
    ctx.fillRect(0, 0, this.width, this.height);

    // 2. Draw background theme (with cross-fade)
    if (this.themeTransition < 1.0 && this.prevBackground) {
      ctx.save(); ctx.globalAlpha = 1.0 - this.themeTransition;
      this._drawBgCore(ctx, this.prevBackground.theme, this.prevBackground.colors, this.prevBackground);
      ctx.restore();
      ctx.save(); ctx.globalAlpha = this.themeTransition;
      this._drawBgCore(ctx, slide.theme || this.config.theme, colors, this);
      ctx.restore();
    } else {
      this._drawBgCore(ctx, slide.theme || this.config.theme, colors, this);
    }

    // 3. Heat haze distortion (applied before compositing text)
    if (this.heatHazeActive) {
      this._drawHeatHaze(ctx, colors);
    }

    // 4. Data streams
    this._drawDataStreams(ctx, colors);

    // 5. Constellation
    this._drawConstellation(ctx, colors);

    // 6. Burst particles
    this._drawBurstParticles(ctx);

    // 7. Shockwave rings
    this._drawShockwaves(ctx);

    // 8. Glitch chromatic aberration overlay
    if (this.glitchActive) {
      this._drawGlitchOverlay(ctx);
    }

    // 9. 6-Phase story composition (the cinematic narrative)
    this._drawTimelineComposition(ctx, slide, colors);
  }

  // ══════════════════════════════════════════════════════════════════════════
  //  BACKGROUND THEME RENDERERS
  // ══════════════════════════════════════════════════════════════════════════

  _drawBgCore(ctx, theme, colors, state) {
    // ── 1. Cyberpunk Particles ──────────────────────────────────────────────
    if (theme === 'cyberpunk_particles' && state.particles) {
      ctx.lineWidth = 1.0;
      for (let i = 0; i < state.particles.length; i++) {
        for (let j = i + 1; j < state.particles.length; j++) {
          const p1 = state.particles[i], p2 = state.particles[j];
          const dist = Math.hypot(p1.x - p2.x, p1.y - p2.y);
          if (dist < 200) {
            const alpha = (1.0 - dist / 200) * 0.18;
            ctx.strokeStyle = `rgba(${this._hex2rgb(colors[0])}, ${alpha})`;
            ctx.beginPath(); ctx.moveTo(p1.x, p1.y); ctx.lineTo(p2.x, p2.y); ctx.stroke();
          }
        }
      }
      state.particles.forEach(p => {
        ctx.fillStyle   = p.color;
        ctx.shadowColor = p.color;
        ctx.shadowBlur  = 14;
        ctx.beginPath(); ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2); ctx.fill();
        ctx.strokeStyle = p.color;
        ctx.lineWidth   = 0.8;
        ctx.beginPath(); ctx.arc(p.x, p.y, p.radius * 2.8, 0, Math.PI * 2); ctx.stroke();
      });
      ctx.shadowBlur = 0;
    }

    // ── 2. Synthwave Grid ───────────────────────────────────────────────────
    if (theme === 'synthwave_grid') {
      const horizonY = 900;
      const gradSun  = ctx.createLinearGradient(0, horizonY - 450, 0, horizonY);
      gradSun.addColorStop(0, colors[1]);
      gradSun.addColorStop(1, colors[0]);
      ctx.fillStyle = gradSun;
      ctx.beginPath(); ctx.arc(540, horizonY, 340, Math.PI, 0); ctx.fill();

      ctx.fillStyle = colors[2] || '#06060e';
      for (let y = horizonY - 340; y < horizonY; y += 24) {
        const h = (y - (horizonY - 340)) / 16 + 2.5;
        ctx.fillRect(140, y, 800, h);
      }
      ctx.strokeStyle = colors[0]; ctx.lineWidth = 4;
      ctx.beginPath(); ctx.moveTo(0, horizonY); ctx.lineTo(this.width, horizonY); ctx.stroke();

      ctx.strokeStyle = colors[0]; ctx.lineWidth = 2.5;
      for (let i = -30; i <= 30; i++) {
        const xS = 540 + i * 24, xE = 540 + i * 128;
        ctx.beginPath(); ctx.moveTo(xS, horizonY); ctx.lineTo(xE, this.height); ctx.stroke();
      }
      for (let y = horizonY + state.gridOffset; y < this.height; y += 45) {
        const scaledY = horizonY + Math.pow((y - horizonY) / (this.height - horizonY), 1.6) * (this.height - horizonY);
        ctx.beginPath(); ctx.moveTo(0, scaledY); ctx.lineTo(this.width, scaledY); ctx.stroke();
      }
    }

    // ── 3. Organic Waves ────────────────────────────────────────────────────
    if (theme === 'organic_waves') {
      const waves = [
        { amp: 140, freq: 0.0016, color: colors[0], alpha: 0.16, offset: 0 },
        { amp: 95,  freq: 0.0022, color: colors[1], alpha: 0.12, offset: Math.PI / 2 },
        { amp: 70,  freq: 0.0028, color: colors[0], alpha: 0.08, offset: Math.PI }
      ];
      waves.forEach(w => {
        ctx.fillStyle   = `rgba(${this._hex2rgb(w.color)}, ${w.alpha})`;
        ctx.strokeStyle = w.color;
        ctx.lineWidth   = 4;
        ctx.beginPath(); ctx.moveTo(0, this.height);
        for (let x = 0; x <= this.width; x += 15) {
          const y = 920 + Math.sin(x * w.freq + state.wavePhase + w.offset) * w.amp;
          ctx.lineTo(x, y);
        }
        ctx.lineTo(this.width, this.height); ctx.closePath(); ctx.fill(); ctx.stroke();
      });
    }

    // ── 4. Matrix Rain ──────────────────────────────────────────────────────
    if (theme === 'matrix_rain' && state.matrixColumns) {
      ctx.font = '700 16px Courier, monospace';
      state.matrixColumns.forEach(c => {
        c.chars.forEach((ch, idx) => {
          const charY = c.y - idx * 26;
          if (charY > 0 && charY < this.height) {
            const alpha = 1.0 - idx / c.chars.length;
            if (idx === 0) {
              ctx.fillStyle   = '#ffffff';
              ctx.shadowColor = colors[0];
              ctx.shadowBlur  = 12;
            } else {
              ctx.fillStyle  = `rgba(${this._hex2rgb(colors[0])}, ${alpha * 0.85})`;
              ctx.shadowBlur = 0;
            }
            ctx.fillText(ch, c.x, charY);
          }
        });
        if (Math.random() < 0.04) {
          c.chars[Math.floor(Math.random() * c.chars.length)] = Math.random() > 0.5 ? '1' : '0';
        }
      });
      ctx.shadowBlur = 0;
    }

    // ── 5. DNA Helix ────────────────────────────────────────────────────────
    if (theme === 'dna_helix') {
      const strandW = 280;
      ctx.lineWidth = 2.5;
      for (let y = 100; y < this.height - 100; y += 46) {
        const phase = y * 0.0028 + state.helixRotation;
        const x1 = 540 + Math.sin(phase) * strandW;
        const x2 = 540 + Math.sin(phase + Math.PI) * strandW;
        const s1  = (Math.cos(phase) + 1.6) * 6.5;
        const s2  = (Math.cos(phase + Math.PI) + 1.6) * 6.5;

        if (Math.cos(phase) > 0) {
          ctx.strokeStyle = `rgba(${this._hex2rgb(colors[0])}, 0.25)`;
          ctx.beginPath(); ctx.moveTo(x1, y); ctx.lineTo(x2, y); ctx.stroke();
        }
        ctx.fillStyle   = colors[0]; ctx.shadowColor = colors[0]; ctx.shadowBlur = s1;
        ctx.beginPath(); ctx.arc(x1, y, s1, 0, Math.PI * 2); ctx.fill();
        ctx.fillStyle   = colors[1]; ctx.shadowColor = colors[1]; ctx.shadowBlur = s2;
        ctx.beginPath(); ctx.arc(x2, y, s2, 0, Math.PI * 2); ctx.fill();
      }
      ctx.shadowBlur = 0;
    }

    // ── 6. Neural Network ───────────────────────────────────────────────────
    if (theme === 'neural_network' && state.neuralNodes) {
      const nodes = state.neuralNodes;
      // Draw connections
      ctx.lineWidth = 1.0;
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const dist = Math.hypot(nodes[i].x - nodes[j].x, nodes[i].y - nodes[j].y);
          if (dist < 260) {
            const alpha = (1 - dist / 260) * 0.22;
            ctx.strokeStyle = `rgba(${this._hex2rgb(colors[0])}, ${alpha})`;
            ctx.beginPath(); ctx.moveTo(nodes[i].x, nodes[i].y); ctx.lineTo(nodes[j].x, nodes[j].y); ctx.stroke();
          }
        }
      }
      // Draw nodes with pulsing glow
      nodes.forEach(n => {
        const pulsedR = n.radius + Math.sin(n.pulse) * 2;
        ctx.fillStyle   = n.color;
        ctx.shadowColor = n.color;
        ctx.shadowBlur  = 18 + Math.sin(n.pulse) * 8;
        ctx.beginPath(); ctx.arc(n.x, n.y, pulsedR, 0, Math.PI * 2); ctx.fill();
      });
      ctx.shadowBlur = 0;
    }

    // ── 7. City Skyline ─────────────────────────────────────────────────────
    if (theme === 'city_skyline') {
      // Distant buildings (dark layer)
      ctx.fillStyle = `rgba(${this._hex2rgb(colors[2] || '#080808')}, 0.9)`;

      // Main skyline buildings
      state.cityBuildings.forEach(b => {
        // Building body
        ctx.fillStyle = `rgba(10, 10, 15, 0.95)`;
        ctx.fillRect(b.x, b.y, b.w, b.h);

        // Neon outline glow
        ctx.strokeStyle = b.color;
        ctx.shadowColor  = b.color;
        ctx.shadowBlur   = 12;
        ctx.lineWidth    = 2;
        ctx.strokeRect(b.x, b.y, b.w, b.h);

        // Windows
        const winW = 8, winH = 5, gapX = (b.w - 6 * winW) / 7, gapY = 28;
        for (let row = 0; row < b.windows.length; row++) {
          for (let col = 0; col < 6; col++) {
            if (b.windows[row] && Math.random() > 0.15) {
              ctx.fillStyle = `rgba(${this._hex2rgb(colors[1])}, 0.6)`;
              ctx.fillRect(b.x + gapX + col * (winW + gapX), b.y + 10 + row * gapY, winW, winH);
            }
          }
        }
      });

      // Ground glow line
      ctx.shadowBlur = 0;
      const grad = ctx.createLinearGradient(0, this.height - 120, 0, this.height);
      grad.addColorStop(0, `rgba(${this._hex2rgb(colors[0])}, 0.3)`);
      grad.addColorStop(1, `rgba(${this._hex2rgb(colors[0])}, 0.0)`);
      ctx.fillStyle = grad;
      ctx.fillRect(0, this.height - 120, this.width, 120);
    }
  }

  // ══════════════════════════════════════════════════════════════════════════
  //  SCENE LAYER RENDERERS
  // ══════════════════════════════════════════════════════════════════════════

  _drawBurstParticles(ctx) {
    ctx.save();
    this.burstParticles.forEach(p => {
      ctx.globalAlpha = p.alpha;
      ctx.fillStyle   = p.color;
      ctx.shadowColor = p.color;
      ctx.shadowBlur  = p.radius * 3;
      ctx.beginPath(); ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2); ctx.fill();
    });
    ctx.restore(); ctx.shadowBlur = 0;
  }

  _drawShockwaves(ctx) {
    ctx.save();
    this.shockwaveRings.forEach(r => {
      ctx.globalAlpha = r.alpha;
      ctx.strokeStyle = r.color;
      ctx.shadowColor = r.color;
      ctx.shadowBlur  = 20;
      ctx.lineWidth   = Math.max(0.5, r.width);
      ctx.beginPath(); ctx.arc(r.x, r.y, r.radius, 0, Math.PI * 2); ctx.stroke();
    });
    ctx.restore(); ctx.shadowBlur = 0;
  }

  _drawGlitchOverlay(ctx) {
    if (this.glitchAlpha <= 0) return;
    ctx.save();
    // Chromatic aberration: red channel offset right
    ctx.globalAlpha   = this.glitchAlpha * 0.4;
    ctx.globalCompositeOperation = 'screen';
    ctx.fillStyle     = 'rgba(255,0,0,0.3)';
    ctx.fillRect(6, 0, this.width, this.height);
    // Blue channel offset left
    ctx.fillStyle     = 'rgba(0,0,255,0.3)';
    ctx.fillRect(-6, 0, this.width, this.height);
    // Horizontal scan slices
    ctx.globalCompositeOperation = 'source-over';
    ctx.globalAlpha = this.glitchAlpha * 0.3;
    for (let i = 0; i < 6; i++) {
      const y = Math.random() * this.height;
      const h = 4 + Math.random() * 20;
      const offset = (Math.random() - 0.5) * 30;
      ctx.drawImage(this.canvas, offset, y, this.width, h, 0, y, this.width, h);
    }
    ctx.restore();
  }

  _drawDataStreams(ctx, colors) {
    ctx.save();
    ctx.font = '500 13px Courier, monospace';

    this.dataStreamColumns.forEach(c => {
      ctx.globalAlpha  = c.alpha;
      ctx.fillStyle    = c.color;
      ctx.shadowColor  = c.color;
      ctx.shadowBlur   = 8;
      c.chars.forEach((ch, idx) => {
        ctx.fillText(ch, c.x, c.y - idx * 22);
      });
    });

    this.dataStreamRows.forEach(r => {
      ctx.globalAlpha  = r.alpha;
      ctx.fillStyle    = r.color;
      ctx.shadowColor  = r.color;
      ctx.shadowBlur   = 6;
      ctx.fillText(r.text, r.x, r.y);
    });

    ctx.restore(); ctx.shadowBlur = 0;
  }

  _drawConstellation(ctx, colors) {
    if (!this.constellationNodes.length) return;
    ctx.save();
    ctx.lineWidth = 1;
    const nodes = this.constellationNodes;
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const dist = Math.hypot(nodes[i].x - nodes[j].x, nodes[i].y - nodes[j].y);
        if (dist < 200) {
          const alpha = (1 - dist / 200) * 0.35;
          ctx.globalAlpha  = alpha;
          ctx.strokeStyle  = nodes[i].color;
          ctx.beginPath(); ctx.moveTo(nodes[i].x, nodes[i].y); ctx.lineTo(nodes[j].x, nodes[j].y); ctx.stroke();
        }
      }
    }
    nodes.forEach(n => {
      ctx.globalAlpha  = 0.7;
      ctx.fillStyle    = n.color;
      ctx.shadowColor  = n.color;
      ctx.shadowBlur   = 10;
      ctx.beginPath(); ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2); ctx.fill();
    });
    ctx.restore(); ctx.shadowBlur = 0;
  }

  _drawHeatHaze(ctx, colors) {
    ctx.save();
    const bottomY = this.height - 300;
    const sliceH  = 4;
    const amp     = 6;

    for (let y = bottomY; y < this.height - 60; y += sliceH) {
      const offset = Math.sin(this.heatHazePhase + y * 0.04) * amp;
      try {
        ctx.drawImage(this.canvas, 0, y, this.width, sliceH, offset, y, this.width, sliceH);
      } catch(e) {}
    }
    // Color tint
    const grad = ctx.createLinearGradient(0, bottomY, 0, this.height);
    grad.addColorStop(0, `rgba(${this._hex2rgb(colors[0])}, 0.0)`);
    grad.addColorStop(1, `rgba(${this._hex2rgb(colors[0])}, 0.12)`);
    ctx.fillStyle = grad;
    ctx.fillRect(0, bottomY, this.width, this.height - bottomY);
    ctx.restore();
  }

  // ══════════════════════════════════════════════════════════════════════════
  //  6-PHASE TIMELINE COMPOSITION
  // ══════════════════════════════════════════════════════════════════════════

  _drawTimelineComposition(ctx, slide, colors) {
    const t = this.slideProgress;
    const entrance  = slide.headline_entrance  || 'slam_down';
    const cardStyle = slide.narrative_card_style || 'glassmorphic_slide';

    // ─────────────────────────────────────────────────────────────────────────
    // PHASE 1 — HOOK (0% → 12%)
    //   Full-screen headline entrance. Background animates in.
    // ─────────────────────────────────────────────────────────────────────────
    let headlineAlpha  = 1.0;
    let headlineY      = 960;
    let headlineSize   = 76;
    let headlineCenter = true;

    // ─────────────────────────────────────────────────────────────────────────
    // PHASE 2 — CONTEXT RISE (12% → 30%)
    //   Headline slides up small. Context card enters.
    // ─────────────────────────────────────────────────────────────────────────
    // ─────────────────────────────────────────────────────────────────────────
    // PHASE 3 — CONTEXT HOLD (30% → 45%)
    // ─────────────────────────────────────────────────────────────────────────
    // ─────────────────────────────────────────────────────────────────────────
    // PHASE 4 — UPDATE REVEAL (45% → 62%)
    // ─────────────────────────────────────────────────────────────────────────
    // ─────────────────────────────────────────────────────────────────────────
    // PHASE 5 — IMPACT BUILD (62% → 82%)
    // ─────────────────────────────────────────────────────────────────────────
    // ─────────────────────────────────────────────────────────────────────────
    // PHASE 6 — OUTRO (82% → 100%)
    // ─────────────────────────────────────────────────────────────────────────

    // After phase 1, headline transitions up to banner position
    // Full-canvas line art metaphor — centered in upper-middle
    let metaphorCx = 540, metaphorCy = 520, metaphorSize = 400;
    if (t > 0.12) {
      const trans = Math.min(1.0, (t - 0.12) / 0.10);
      const ease  = this._easeInOutCubic(trans);
      headlineY     = 960 - (960 - 175) * ease;
      headlineSize  = 76  - (76  -  40) * ease;
      headlineCenter = true;
      // Metaphor shrinks and repositions slightly as headline moves up
      metaphorCy   = 520 - 60 * ease;
      metaphorSize = 400 - 40 * ease;
    }

    // Draw full-canvas visual metaphor line art
    const metaphor = slide.visual_metaphor || { type:'network_node', animation:'float' };
    this._drawVisualMetaphor(ctx, metaphor.type, metaphorCx, metaphorCy, metaphorSize, metaphor.animation, colors, t);

    // Draw headline with the chosen entrance style
    this._drawStyledHeadline(ctx, slide.headline.toUpperCase(), 540, headlineY, headlineSize, t, colors, entrance);

    // Card container position
    const cardX = 70, cardY = 1000, cardW = 940;

    // ── Phase 2 & 3: Context Card (0.12 → 0.50) ──────────────────────────────
    if (t >= 0.12 && t < 0.50) {
      const entry = Math.min(1.0, (t - 0.12) / 0.07);
      let   exit  = 0;
      if (t > 0.44) exit = Math.min(1.0, (t - 0.44) / 0.06);
      const alpha = this._easeInOutCubic(entry) * (1 - exit);
      const yOff  = 40 * (1 - this._easeInOutCubic(entry)) - 40 * exit;

      if (alpha > 0.01) {
        this._drawNarrativeCard(ctx, "BACKGROUND CONTEXT", slide.context,
          'rgba(123, 44, 255, 0.28)', '#c49fff', cardX, cardY + yOff, cardW, alpha, cardStyle, 'context', t);
      }
    }

    // ── Phase 4: Update Card (0.45 → 0.67) ───────────────────────────────────
    if (t >= 0.45 && t < 0.67) {
      const entry = Math.min(1.0, (t - 0.45) / 0.07);
      let   exit  = 0;
      if (t > 0.61) exit = Math.min(1.0, (t - 0.61) / 0.06);
      const alpha = this._easeInOutCubic(entry) * (1 - exit);
      const yOff  = 45 * (1 - this._easeInOutCubic(entry)) - 45 * exit;

      if (alpha > 0.01) {
        this._drawNarrativeCard(ctx, "BREAKING UPDATE", slide.update,
          `rgba(${this._hex2rgb(colors[0])}, 0.22)`, colors[0], cardX, cardY + yOff, cardW, alpha, cardStyle, 'update', t);
      }
    }

    // ── Phase 5: Impact Card (0.62 → 0.85) ───────────────────────────────────
    if (t >= 0.62 && t < 0.85) {
      const entry = Math.min(1.0, (t - 0.62) / 0.07);
      let   exit  = 0;
      if (t > 0.79) exit = Math.min(1.0, (t - 0.79) / 0.06);
      const alpha = this._easeInOutCubic(entry) * (1 - exit);
      const yOff  = 45 * (1 - this._easeInOutCubic(entry)) - 45 * exit;

      if (alpha > 0.01) {
        this._drawNarrativeCard(ctx, "FUTURE IMPACT", slide.impact,
          `rgba(${this._hex2rgb(colors[1])}, 0.22)`, colors[1], cardX, cardY + yOff, cardW, alpha, cardStyle, 'impact', t);
      }
    }

    // ── Phase 6: Outro — source badge + subtle vignette (0.82 → 1.0) ─────────
    if (t >= 0.82) {
      const fade = Math.min(1.0, (t - 0.82) / 0.08);
      ctx.save();
      ctx.globalAlpha = fade * 0.8;
      ctx.fillStyle   = `rgba(${this._hex2rgb(colors[0])}, 0.08)`;
      ctx.fillRect(0, this.height - 200, this.width, 200);

      // Source attribution pill
      ctx.globalAlpha   = fade;
      ctx.fillStyle     = `rgba(255,255,255,0.12)`;
      ctx.strokeStyle   = colors[0];
      ctx.lineWidth     = 1.5;
      ctx.shadowColor   = colors[0];
      ctx.shadowBlur    = 8;
      const pillW = 340, pillH = 46;
      this._roundRect(ctx, 540 - pillW / 2, this.height - 160, pillW, pillH, 23);
      ctx.fill(); ctx.stroke();

      ctx.shadowBlur    = 0;
      ctx.fillStyle     = colors[0];
      ctx.font          = '500 18px Inter, sans-serif';
      ctx.textAlign     = 'center';
      ctx.textBaseline  = 'middle';
      ctx.fillText('AI-GENERATED · ON-DEVICE LLM', 540, this.height - 137);

      // Small headline reprise
      ctx.globalAlpha   = fade * 0.55;
      ctx.font          = `600 26px Inter, sans-serif`;
      ctx.fillStyle     = '#ffffff';
      ctx.fillText(slide.headline.toUpperCase(), 540, this.height - 80);

      ctx.restore();
    }

    // ── Vignette edges (always) ───────────────────────────────────────────────
    this._drawVignette(ctx, colors);
  }

  // ══════════════════════════════════════════════════════════════════════════
  //  HEADLINE ENTRANCE STYLES
  // ══════════════════════════════════════════════════════════════════════════

  _drawStyledHeadline(ctx, text, cx, cy, fontSize, t, colors, style) {
    // Initialize letter states on first call
    if (!this.headlineReady || this._lastHeadlineText !== text) {
      this._lastHeadlineText = text;
      this.headlineReady = true;
      this._initHeadlineLetters(text, cx, cy, fontSize, style, colors);
    }

    switch (style) {
      case 'slam_down':     this._drawSlamDown(ctx, text, cx, cy, fontSize, t, colors); break;
      case 'zoom_in':       this._drawZoomIn(ctx, text, cx, cy, fontSize, t, colors);   break;
      case 'glitch_reveal': this._drawGlitchReveal(ctx, text, cx, cy, fontSize, t, colors); break;
      case 'wave_rise':     this._drawWaveRise(ctx, text, cx, cy, fontSize, t, colors); break;
      case 'typewriter':    this._drawTypewriterHeadline(ctx, text, cx, cy, fontSize, t, colors); break;
      default:              this._drawSlamDown(ctx, text, cx, cy, fontSize, t, colors); break;
    }
  }

  _initHeadlineLetters(text, cx, cy, fontSize, style, colors) {
    this.headlineLetters = [];
    // Measure total width for centering
    const ctx = this.ctx;
    ctx.font = `900 ${fontSize}px Inter, sans-serif`;
    const totalW = ctx.measureText(text).width;
    let xCursor = cx - totalW / 2;

    for (let i = 0; i < text.length; i++) {
      const ch = text[i];
      const chW = ctx.measureText(ch).width;
      const targetX = xCursor;
      const targetY = cy;

      let startX = targetX, startY = targetY;
      if (style === 'slam_down')     { startY = -120; }
      if (style === 'zoom_in')       { startX = cx; startY = cy; }
      if (style === 'wave_rise')     { startY = cy + 180; }
      if (style === 'glitch_reveal') { startX = targetX + (Math.random() - 0.5) * 300; startY = targetY + (Math.random() - 0.5) * 300; }
      if (style === 'typewriter')    { startX = targetX; startY = targetY; }

      this.headlineLetters.push({
        ch, targetX, targetY,
        x: startX, y: startY,
        vx: 0, vy: 0,
        scale: style === 'zoom_in' ? 4.0 : 1.0,
        alpha: style === 'typewriter' ? 0 : 1.0,
        delay: i * 0.025,
        settled: false,
        color: i % 2 === 0 ? '#ffffff' : colors[0],
        fontSize,
        tickerMode: false
      });
      xCursor += chW;
    }
  }

  _drawSlamDown(ctx, text, cx, cy, fontSize, t, colors) {
    ctx.save();
    ctx.textBaseline = 'middle';
    ctx.textAlign    = 'left';

    this.headlineLetters.forEach((l, i) => {
      const revealT = Math.max(0, t * 8 - l.delay * 8);
      const ease    = this._easeOutBounce(Math.min(1, revealT));
      const drawY   = l.targetY - (l.targetY - (-120)) * (1 - ease);
      const alpha   = Math.min(1, revealT * 4);

      ctx.globalAlpha  = alpha;
      ctx.font         = `900 ${l.fontSize}px Inter, sans-serif`;
      ctx.fillStyle    = l.color;
      ctx.shadowColor  = colors[0];
      ctx.shadowBlur   = 18;
      ctx.fillText(l.ch, l.targetX, drawY);
    });
    ctx.restore(); ctx.shadowBlur = 0;
  }

  _drawZoomIn(ctx, text, cx, cy, fontSize, t, colors) {
    const progress = Math.min(1.0, t * 6);
    const ease     = this._easeOutCubic(progress);
    const scale    = 4.0 - 3.0 * ease;
    const alpha    = Math.min(1, progress * 3);
    const blur     = (1 - ease) * 30;

    ctx.save();
    ctx.globalAlpha  = alpha;
    ctx.textBaseline = 'middle';
    ctx.textAlign    = 'center';
    ctx.font         = `900 ${fontSize}px Inter, sans-serif`;
    ctx.fillStyle    = '#ffffff';
    ctx.shadowColor  = colors[0];
    ctx.shadowBlur   = blur + 20;
    ctx.translate(cx, cy);
    ctx.scale(scale, scale);
    ctx.fillText(text, 0, 0);
    ctx.restore(); ctx.shadowBlur = 0;
  }

  _drawGlitchReveal(ctx, text, cx, cy, fontSize, t, colors) {
    ctx.save();
    ctx.textBaseline = 'middle';
    ctx.textAlign    = 'left';

    this.headlineLetters.forEach((l, i) => {
      const progress = Math.min(1, Math.max(0, t * 5 - l.delay * 3));
      const glitchAmt = (1 - progress) * 40;
      const finalX    = l.targetX + (Math.random() - 0.5) * glitchAmt;
      const finalY    = l.targetY + (Math.random() - 0.5) * glitchAmt;

      ctx.globalAlpha  = Math.min(1, progress * 3);
      ctx.font         = `900 ${l.fontSize}px Inter, sans-serif`;

      // Red ghost
      ctx.fillStyle    = `rgba(255,0,0,0.6)`;
      ctx.fillText(l.ch, finalX + 4, finalY);
      // Blue ghost
      ctx.fillStyle    = `rgba(0,120,255,0.6)`;
      ctx.fillText(l.ch, finalX - 4, finalY);
      // Main white
      ctx.fillStyle    = '#ffffff';
      ctx.shadowColor  = colors[0];
      ctx.shadowBlur   = 14;
      ctx.fillText(l.ch, l.targetX, l.targetY);
    });
    ctx.restore(); ctx.shadowBlur = 0;
  }

  _drawWaveRise(ctx, text, cx, cy, fontSize, t, colors) {
    ctx.save();
    ctx.textBaseline = 'middle';
    ctx.textAlign    = 'left';

    this.headlineLetters.forEach((l, i) => {
      const progress = Math.min(1, Math.max(0, t * 6 - l.delay * 6));
      const ease     = this._easeOutCubic(progress);
      const drawY    = l.targetY + 180 * (1 - ease);
      const alpha    = Math.min(1, progress * 4);

      ctx.globalAlpha  = alpha;
      ctx.font         = `900 ${l.fontSize}px Inter, sans-serif`;
      ctx.fillStyle    = l.color;
      ctx.shadowColor  = colors[0];
      ctx.shadowBlur   = 16;
      ctx.fillText(l.ch, l.targetX, drawY);
    });
    ctx.restore(); ctx.shadowBlur = 0;
  }

  _drawTypewriterHeadline(ctx, text, cx, cy, fontSize, t, colors) {
    const visibleChars = Math.floor(t * text.length * 7);
    const displayText  = text.substring(0, Math.min(text.length, visibleChars));
    const cursor       = (t * 7 < 1.2 || Math.floor(t * 8) % 2 === 0) ? '|' : '';

    ctx.save();
    ctx.textBaseline = 'middle';
    ctx.textAlign    = 'center';
    ctx.font         = `900 ${fontSize}px 'Courier New', monospace`;
    ctx.fillStyle    = '#ffffff';
    ctx.shadowColor  = colors[0];
    ctx.shadowBlur   = 20;
    ctx.fillText(displayText + cursor, cx, cy);
    ctx.restore(); ctx.shadowBlur = 0;
  }

  // ══════════════════════════════════════════════════════════════════════════
  //  NARRATIVE CARD STYLES
  // ══════════════════════════════════════════════════════════════════════════

  _drawNarrativeCard(ctx, label, bodyText, bgColor, accentColor, x, y, w, alpha, style, phase, t) {
    switch (style) {
      case 'glassmorphic_slide': this._cardGlassmorphic(ctx, label, bodyText, bgColor, accentColor, x, y, w, alpha); break;
      case 'terminal_print':     this._cardTerminal(ctx, label, bodyText, accentColor, x, y, w, alpha, phase, t); break;
      case 'holographic':        this._cardHolographic(ctx, label, bodyText, bgColor, accentColor, x, y, w, alpha, t); break;
      case 'ticker_tape':        this._cardTicker(ctx, label, bodyText, accentColor, x, y, w, alpha, phase); break;
      default:                   this._cardGlassmorphic(ctx, label, bodyText, bgColor, accentColor, x, y, w, alpha); break;
    }
  }

  _cardGlassmorphic(ctx, label, bodyText, bgColor, accentColor, x, y, w, alpha) {
    ctx.save();
    ctx.globalAlpha = alpha;
    const lines  = this._wrapText(ctx, bodyText, w - 80, 34);
    const h      = 80 + lines.length * 46 + 50;

    // Frosted glass background
    ctx.fillStyle = bgColor;
    this._roundRect(ctx, x, y, w, h, 28); ctx.fill();

    // Top accent border
    ctx.strokeStyle = accentColor;
    ctx.lineWidth   = 3;
    ctx.shadowColor = accentColor;
    ctx.shadowBlur  = 12;
    this._roundRect(ctx, x, y, w, h, 28); ctx.stroke();
    ctx.shadowBlur = 0;

    // Label pill
    ctx.fillStyle   = accentColor;
    ctx.shadowColor = accentColor;
    ctx.shadowBlur  = 8;
    this._roundRect(ctx, x + 30, y + 24, 300, 36, 18); ctx.fill();
    ctx.shadowBlur  = 0;
    ctx.fillStyle   = '#000000';
    ctx.font        = '700 17px Inter, sans-serif';
    ctx.textAlign   = 'left';
    ctx.textBaseline= 'middle';
    ctx.fillText(label, x + 48, y + 42);

    // Body text
    ctx.fillStyle   = '#e8e8f0';
    ctx.font        = '500 34px Inter, sans-serif';
    ctx.textAlign   = 'left';
    lines.forEach((line, i) => ctx.fillText(line, x + 40, y + 80 + i * 46));

    ctx.restore();
  }

  _cardTerminal(ctx, label, bodyText, accentColor, x, y, w, alpha, phase, t) {
    ctx.save();
    ctx.globalAlpha = alpha;

    const lines  = this._wrapText(ctx, bodyText, w - 80, 30);
    const h      = 80 + lines.length * 40 + 40;

    // Dark terminal background
    ctx.fillStyle = 'rgba(5,12,5,0.92)';
    this._roundRect(ctx, x, y, w, h, 8); ctx.fill();

    // Green outline
    ctx.strokeStyle = accentColor;
    ctx.lineWidth   = 2;
    ctx.shadowColor = accentColor;
    ctx.shadowBlur  = 10;
    this._roundRect(ctx, x, y, w, h, 8); ctx.stroke();
    ctx.shadowBlur  = 0;

    // Header bar
    ctx.fillStyle   = accentColor;
    ctx.fillRect(x, y, w, 36);
    ctx.fillStyle   = '#000';
    ctx.font        = '600 16px Courier, monospace';
    ctx.textAlign   = 'left';
    ctx.textBaseline= 'middle';
    ctx.fillText(`▶ ${label}`, x + 14, y + 18);

    // Terminal-print text (character by character)
    const phaseKey  = phase;
    if (!this.termPrintLines[phaseKey]) this.termPrintLines[phaseKey] = 0;
    const totalChars = lines.join('').length;
    const revealT    = Math.min(1.0, (t > 0.45 ? (t - 0.45) : (t > 0.12 ? t - 0.12 : t)) * 3);
    const visibleChars = Math.floor(revealT * totalChars * 1.5);

    let charCount = 0;
    ctx.fillStyle = accentColor;
    ctx.font      = '500 30px Courier, monospace';
    lines.forEach((line, i) => {
      const lineChars = Math.max(0, visibleChars - charCount);
      const display   = line.substring(0, lineChars);
      ctx.fillText(display, x + 20, y + 56 + i * 40);
      charCount += line.length;
    });

    // Blinking cursor
    if (Math.floor(t * 8) % 2 === 0) {
      ctx.fillStyle = accentColor;
      ctx.fillRect(x + 20 + charCount * 9, y + 44 + lines.length * 40, 12, 28);
    }

    ctx.restore();
  }

  _cardHolographic(ctx, label, bodyText, bgColor, accentColor, x, y, w, alpha, t) {
    ctx.save();
    ctx.globalAlpha = alpha;

    const lines = this._wrapText(ctx, bodyText, w - 80, 34);
    const h     = 80 + lines.length * 46 + 50;

    // Holographic shimmer background
    const shimmer = (Math.sin(t * 12) + 1) / 2;
    const grad    = ctx.createLinearGradient(x, y, x + w, y + h);
    grad.addColorStop(0,     `rgba(${this._hex2rgb(accentColor)}, 0.15)`);
    grad.addColorStop(shimmer, `rgba(255,255,255,0.08)`);
    grad.addColorStop(1,     `rgba(${this._hex2rgb(accentColor)}, 0.20)`);

    ctx.fillStyle = grad;
    this._roundRect(ctx, x, y, w, h, 20); ctx.fill();

    // Scan lines overlay
    ctx.globalAlpha = alpha * 0.25;
    ctx.fillStyle   = '#000';
    for (let sy = y; sy < y + h; sy += 6) {
      ctx.fillRect(x, sy, w, 2);
    }
    ctx.globalAlpha = alpha;

    // Border glow
    ctx.strokeStyle = accentColor;
    ctx.lineWidth   = 2.5;
    ctx.shadowColor = accentColor;
    ctx.shadowBlur  = 20;
    this._roundRect(ctx, x, y, w, h, 20); ctx.stroke();
    ctx.shadowBlur  = 0;

    // Label
    ctx.fillStyle   = accentColor;
    ctx.font        = '700 18px Inter, sans-serif';
    ctx.textAlign   = 'left';
    ctx.textBaseline= 'middle';
    ctx.fillText(label, x + 30, y + 38);

    // Body text
    ctx.fillStyle   = '#d8f0ff';
    ctx.font        = '400 34px Inter, sans-serif';
    lines.forEach((line, i) => ctx.fillText(line, x + 30, y + 78 + i * 46));

    ctx.restore();
  }

  _cardTicker(ctx, label, bodyText, accentColor, x, y, w, alpha, phase) {
    ctx.save();
    ctx.globalAlpha = alpha;

    const h = 130;

    // Ticker background
    ctx.fillStyle = 'rgba(0,0,0,0.85)';
    this._roundRect(ctx, x, y, w, h, 12); ctx.fill();

    // Colored top strip
    ctx.fillStyle   = accentColor;
    ctx.shadowColor = accentColor;
    ctx.shadowBlur  = 8;
    ctx.fillRect(x, y, w, 44);
    ctx.shadowBlur  = 0;

    ctx.fillStyle   = '#000';
    ctx.font        = '700 20px Inter, sans-serif';
    ctx.textAlign   = 'left';
    ctx.textBaseline= 'middle';
    ctx.fillText(`● ${label}`, x + 16, y + 22);

    // Scrolling ticker text
    this.tickerOffset = (this.tickerOffset || 0) + 1.8;
    const tickerText  = `${bodyText}  ●  ${bodyText}  ●  `;
    ctx.font = '500 30px Inter, sans-serif';
    ctx.fillStyle = accentColor;

    ctx.save();
    ctx.beginPath();
    ctx.rect(x, y + 44, w, h - 44);
    ctx.clip();
    const textW = ctx.measureText(tickerText).width;
    const offsetX = (this.tickerOffset % (textW + w));
    ctx.fillText(tickerText, x + w - offsetX, y + 44 + (h - 44) / 2);
    ctx.restore();

    ctx.restore();
  }

  // ══════════════════════════════════════════════════════════════════════════
  //  VISUAL METAPHOR ICONS (Procedural Vector Line Art)
  // ══════════════════════════════════════════════════════════════════════════

  _drawVisualMetaphor(ctx, type, cx, cy, size, animation, colors) {
    const t = this.slideProgress;
    
    // Position fixed in the upper-middle area (hero visual) for cinematic impact
    const heroCx = 540;
    const heroCy = 550;
    const heroSize = 360;
    
    ctx.save();
    
    // Phase 1 (0–12% progress): Progressive stroke reveal
    if (t < 0.12) {
      const drawProgress = t / 0.12;
      ctx.setLineDash([400 * drawProgress, 400 * (1 - drawProgress)]);
    } else {
      ctx.setLineDash([]);
    }
    
    // Phase 6 (82–100% progress): Fade out gradually
    if (t >= 0.82) {
      ctx.globalAlpha = Math.max(0, 1.0 - (t - 0.82) / 0.18);
    }
    
    // Phase 4 & 5 (45–82% progress): Glow / shadow blur pulse
    let shadowBlur = 15;
    if (t >= 0.45 && t < 0.62) {
      const pulseT = (t - 0.45) / 0.17;
      shadowBlur = 15 + Math.sin(pulseT * Math.PI * 4) * 15;
    } else if (t >= 0.62 && t < 0.82) {
      shadowBlur = 30; // peak intensity
    }
    
    ctx.shadowBlur = shadowBlur;
    ctx.shadowColor = colors[0];
    
    // Float & Rotate primary movement physics
    const floatY = Math.sin(this.metaphorAngle * 2) * 10;
    const angle = this.metaphorAngle * 0.5;
    
    ctx.translate(heroCx, heroCy + floatY);
    if (animation === 'rotate') {
      ctx.rotate(angle);
    }
    
    // Dispatch dictionary
    const renderers = {
      'network_node': this._drawNetworkNode.bind(this),
      'rocket_ship': this._drawRocketShip.bind(this),
      'bar_trend': this._drawBarTrend.bind(this),
      'shield_lock': this._drawShieldLock.bind(this),
      'gear_matrix': this._drawGearMatrix.bind(this),
      'globe_wire': this._drawGlobeWire.bind(this),
      'code_terminal': this._drawCodeTerminal.bind(this),
      'dna_helix': this._drawDnaHelix.bind(this),
    };
    
    const renderer = renderers[type] || renderers['network_node'];
    
    // Phase 5 (62–82% progress): Peak intensity trails / afterimages
    if (t >= 0.62 && t < 0.82) {
      ctx.save();
      ctx.globalAlpha = 0.25;
      ctx.translate(-15, -10);
      renderer(ctx, 0, 0, heroSize, t, colors);
      ctx.restore();
      
      ctx.save();
      ctx.globalAlpha = 0.25;
      ctx.translate(15, 10);
      renderer(ctx, 0, 0, heroSize, t, colors);
      ctx.restore();
    }
    
    // Main render pass
    renderer(ctx, 0, 0, heroSize, t, colors);
    
    ctx.restore();
  }

  _applyMetaphorEnvelope(ctx, progress, colors) {
    let alpha = 1.0;
    if (progress < 0.12) {
      alpha = progress / 0.12;
    } else if (progress >= 0.82) {
      alpha = Math.max(0, 1.0 - (progress - 0.82) / 0.18);
    }

    let glowBlur = 15;
    if (progress >= 0.45 && progress < 0.62) {
      const pulseT = (progress - 0.45) / 0.17;
      glowBlur = 15 + Math.sin(pulseT * Math.PI * 4) * 15;
    } else if (progress >= 0.62 && progress < 0.82) {
      glowBlur = 30;
    }

    return { alpha, glowBlur };
  }

  _drawNetworkNode(ctx, cx, cy, size, progress, colors) {
    const env = this._applyMetaphorEnvelope(ctx, progress, colors);
    const r   = size / 2;

    // Seed 18 deterministic nodes arranged in organic circular clusters
    const nodeCount = 18;
    const threshold = r * 0.75; // connection distance
    const time = this.metaphorAngle;

    const nodes = [];
    for (let i = 0; i < nodeCount; i++) {
      const baseAngle = (i / nodeCount) * Math.PI * 2;
      const orbit     = r * 0.3 + (i % 3) * r * 0.22;
      // Gentle drift using sine harmonics
      const dx = Math.cos(baseAngle + time * (0.3 + (i % 4) * 0.15)) * orbit;
      const dy = Math.sin(baseAngle + time * (0.4 + (i % 3) * 0.12)) * orbit;
      nodes.push({
        x: cx + dx,
        y: cy + dy,
        color: i % 2 === 0 ? colors[0] : (colors[1] || '#ffffff')
      });
    }

    // Draw connection web-lines
    ctx.lineWidth = 1;
    for (let i = 0; i < nodeCount; i++) {
      for (let j = i + 1; j < nodeCount; j++) {
        const dist = Math.hypot(nodes[i].x - nodes[j].x, nodes[i].y - nodes[j].y);
        if (dist < threshold) {
          const lineAlpha = (1 - dist / threshold) * 0.55;
          ctx.strokeStyle = `rgba(${this._hex2rgb(colors[0])}, ${lineAlpha * env.alpha})`;
          ctx.shadowBlur  = env.glowBlur * lineAlpha;
          ctx.beginPath();
          ctx.moveTo(nodes[i].x, nodes[i].y);
          ctx.lineTo(nodes[j].x, nodes[j].y);
          ctx.stroke();
        }
      }
    }
    
    nodes.forEach((n, i) => {
      ctx.fillStyle = n.color;
      ctx.beginPath();
      ctx.arc(n.x, n.y, 6 + Math.sin(this.metaphorAngle * 3 + i) * 2, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 1.5;
      ctx.stroke();
    });
  }

  _drawRocketShip(ctx, cx, cy, size, progress, colors) {
    const r = size / 2;
    const riseY = -progress * 80 + 40;
    ctx.save();
    ctx.translate(0, riseY);
    
    ctx.strokeStyle = colors[0];
    ctx.lineWidth = 3;
    
    // Body (sleek diamond-curve outline)
    ctx.beginPath();
    ctx.moveTo(0, -r * 0.85);
    ctx.quadraticCurveTo(r * 0.35, -r * 0.2, r * 0.25, r * 0.4);
    ctx.lineTo(-r * 0.25, r * 0.4);
    ctx.quadraticCurveTo(-r * 0.35, -r * 0.2, 0, -r * 0.85);
    ctx.closePath();
    ctx.stroke();
    
    // Inner window
    ctx.beginPath();
    ctx.arc(0, -r * 0.2, r * 0.1, 0, Math.PI * 2);
    ctx.stroke();
    
    // Fins
    ctx.beginPath();
    ctx.moveTo(-r * 0.25, r * 0.1);
    ctx.lineTo(-r * 0.55, r * 0.45);
    ctx.lineTo(-r * 0.25, r * 0.4);
    ctx.closePath();
    ctx.stroke();
    
    ctx.beginPath();
    ctx.moveTo(r * 0.25, r * 0.1);
    ctx.lineTo(r * 0.55, r * 0.45);
    ctx.lineTo(r * 0.25, r * 0.4);
    ctx.closePath();
    ctx.stroke();
    
    // Engine cup
    ctx.beginPath();
    ctx.moveTo(-r * 0.12, r * 0.4);
    ctx.lineTo(-r * 0.18, r * 0.48);
    ctx.lineTo(r * 0.18, r * 0.48);
    ctx.lineTo(r * 0.12, r * 0.4);
    ctx.closePath();
    ctx.stroke();
    
    // Exhaust flames
    ctx.strokeStyle = colors[1];
    ctx.lineWidth = 2;
    const flameH = r * 0.35 + Math.sin(this.metaphorAngle * 10) * 10;
    ctx.beginPath();
    ctx.moveTo(-r * 0.15, r * 0.48);
    ctx.lineTo(0, r * 0.48 + flameH);
    ctx.lineTo(r * 0.15, r * 0.48);
    ctx.stroke();
    
    // Kinetic velocity dashes
    ctx.strokeStyle = `rgba(${this._hex2rgb(colors[1])}, 0.5)`;
    ctx.lineWidth = 2;
    for (let i = 0; i < 6; i++) {
      const dashX = (Math.sin(i * 45) * r * 0.8);
      const dashY = r * 0.5 + ((this.metaphorAngle * 80 + i * 40) % 120);
      ctx.beginPath();
      ctx.moveTo(dashX, dashY);
      ctx.lineTo(dashX, dashY + 25);
      ctx.stroke();
    }
    
    ctx.restore();
  }

  _drawBarTrend(ctx, cx, cy, size, progress, colors) {
    const r = size / 2;
    const dataPoints = [
      { x: -r * 0.8, y: r * 0.4 },
      { x: -r * 0.5, y: r * 0.1 },
      { x: -r * 0.2, y: r * 0.3 },
      { x: r * 0.1,  y: -r * 0.15 },
      { x: r * 0.4,  y: r * 0.05 },
      { x: r * 0.8,  y: -r * 0.6 }
    ];
    
    ctx.strokeStyle = `rgba(${this._hex2rgb(colors[0])}, 0.12)`;
    ctx.lineWidth = 1;
    for (let i = -3; i <= 3; i++) {
      const gridY = (i / 3) * r * 0.85;
      ctx.beginPath();
      ctx.moveTo(-r * 0.9, gridY);
      ctx.lineTo(r * 0.9, gridY);
      ctx.stroke();
      
      const gridX = (i / 3) * r * 0.9;
      ctx.beginPath();
      ctx.moveTo(gridX, -r * 0.85);
      ctx.lineTo(gridX, r * 0.85);
      ctx.stroke();
    }
    
    const drawLimit = progress / 0.85;
    ctx.strokeStyle = colors[0];
    ctx.lineWidth = 4;
    ctx.beginPath();
    
    let activePoints = [];
    for (let i = 0; i < dataPoints.length; i++) {
      const ptProgress = i / (dataPoints.length - 1);
      if (ptProgress <= drawLimit) {
        activePoints.push(dataPoints[i]);
      } else {
        if (i > 0) {
          const prev = dataPoints[i - 1];
          const curr = dataPoints[i];
          const segmentProgress = (drawLimit - (i - 1) / (dataPoints.length - 1)) / (1 / (dataPoints.length - 1));
          activePoints.push({
            x: prev.x + (curr.x - prev.x) * segmentProgress,
            y: prev.y + (curr.y - prev.y) * segmentProgress
          });
        }
        break;
      }
    }
    
    if (activePoints.length > 0) {
      ctx.beginPath();
      ctx.moveTo(activePoints[0].x, activePoints[0].y);
      for (let i = 1; i < activePoints.length; i++) {
        ctx.lineTo(activePoints[i].x, activePoints[i].y);
      }
      ctx.stroke();
    }
    
    activePoints.forEach((pt, i) => {
      const isPeak = (i === dataPoints.length - 1);
      ctx.fillStyle = isPeak ? colors[1] : colors[0];
      ctx.beginPath();
      const nodePulse = 6 + Math.sin(this.metaphorAngle * 6 + i) * (isPeak ? 3 : 1.5);
      ctx.arc(pt.x, pt.y, nodePulse, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 1.5;
      ctx.stroke();
    });
  }

  _drawShieldLock(ctx, cx, cy, size, progress, colors) {
    const r = size / 2;
    
    ctx.strokeStyle = colors[0];
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.arc(0, 0, r * 0.9, 0, Math.PI * 2);
    ctx.stroke();
    
    ctx.strokeStyle = `rgba(${this._hex2rgb(colors[0])}, 0.35)`;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.arc(0, 0, r * 0.75, 0, Math.PI * 2);
    ctx.stroke();
    
    ctx.strokeStyle = colors[1];
    ctx.lineWidth = 4;
    ctx.beginPath();
    ctx.arc(0, 0, r * 0.9, this.metaphorAngle, this.metaphorAngle + 1.2);
    ctx.stroke();
    
    ctx.beginPath();
    ctx.arc(0, 0, r * 0.9, this.metaphorAngle + Math.PI, this.metaphorAngle + Math.PI + 1.2);
    ctx.stroke();
    
    ctx.strokeStyle = colors[0];
    ctx.lineWidth = 3.5;
    ctx.fillStyle = `rgba(${this._hex2rgb(colors[0])}, 0.15)`;
    ctx.beginPath();
    ctx.moveTo(0, -r * 0.45);
    ctx.lineTo(r * 0.38, -r * 0.25);
    ctx.lineTo(r * 0.38, r * 0.1);
    ctx.quadraticCurveTo(r * 0.38, r * 0.45, 0, r * 0.6);
    ctx.quadraticCurveTo(-r * 0.38, r * 0.45, -r * 0.38, r * 0.1);
    ctx.lineTo(-r * 0.38, -r * 0.25);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = 2.5;
    
    ctx.beginPath();
    ctx.arc(0, -r * 0.08, r * 0.1, Math.PI, 0);
    ctx.lineTo(r * 0.1, r * 0.12);
    ctx.moveTo(-r * 0.1, -r * 0.08);
    ctx.lineTo(-r * 0.1, r * 0.12);
    ctx.stroke();
    
    ctx.fillStyle = colors[2];
    ctx.beginPath();
    ctx.rect(-r * 0.15, -r * 0.02, r * 0.3, r * 0.22);
    ctx.fill();
    ctx.stroke();
    
    ctx.fillStyle = '#ffffff';
    ctx.beginPath();
    ctx.arc(0, r * 0.05, 3, 0, Math.PI * 2);
    ctx.fill();
    ctx.beginPath();
    ctx.moveTo(-1, r * 0.05 + 3);
    ctx.lineTo(1, r * 0.05 + 3);
    ctx.lineTo(2, r * 0.14);
    ctx.lineTo(-2, r * 0.14);
    ctx.closePath();
    ctx.fill();
  }

  _drawGearMatrix(ctx, cx, cy, size, progress, colors) {
    const r = size / 2;
    
    ctx.save();
    ctx.translate(-r * 0.25, -r * 0.2);
    ctx.rotate(this.metaphorAngle * 0.8);
    this._drawSingleGear(ctx, r * 0.5, 12, colors[0]);
    ctx.restore();
    
    ctx.save();
    ctx.translate(r * 0.38, r * 0.25);
    ctx.rotate(-this.metaphorAngle * 0.8 + 0.25);
    this._drawSingleGear(ctx, r * 0.4, 10, colors[1]);
    ctx.restore();
    
    ctx.save();
    ctx.translate(-r * 0.4, r * 0.45);
    ctx.rotate(-this.metaphorAngle * 0.8 + 0.5);
    this._drawSingleGear(ctx, r * 0.28, 8, '#ffffff');
    ctx.restore();
  }
  
  _drawSingleGear(ctx, radius, teeth, color) {
    ctx.strokeStyle = color;
    ctx.lineWidth = 3;
    ctx.fillStyle = `rgba(${this._hex2rgb(color)}, 0.1)`;
    
    ctx.beginPath();
    for (let i = 0; i < teeth * 2; i++) {
      const angle = (i * Math.PI) / teeth;
      const rad = i % 2 === 0 ? radius : radius * 0.82;
      if (i === 0) ctx.moveTo(Math.cos(angle) * rad, Math.sin(angle) * rad);
      else ctx.lineTo(Math.cos(angle) * rad, Math.sin(angle) * rad);
    }
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    
    ctx.beginPath();
    ctx.arc(0, 0, radius * 0.25, 0, Math.PI * 2);
    ctx.stroke();
  }

  _drawGlobeWire(ctx, cx, cy, size, progress, colors) {
    const r = size / 2;
    
    ctx.strokeStyle = colors[0];
    ctx.lineWidth = 3.5;
    ctx.beginPath();
    ctx.arc(0, 0, r * 0.85, 0, Math.PI * 2);
    ctx.stroke();
    
    const rotation = this.metaphorAngle * 0.45;
    ctx.lineWidth = 2;
    
    for (let i = 0; i < 3; i++) {
      ctx.strokeStyle = i % 2 === 0 ? colors[0] : colors[1];
      const shift = rotation + (i * Math.PI) / 3;
      const scaleX = Math.cos(shift);
      
      ctx.save();
      ctx.scale(scaleX, 1.0);
      ctx.beginPath();
      ctx.arc(0, 0, r * 0.85, 0, Math.PI * 2);
      ctx.stroke();
      ctx.restore();
    }
    
    ctx.strokeStyle = `rgba(${this._hex2rgb(colors[0])}, 0.6)`;
    const lats = [-r * 0.42, 0, r * 0.42];
    lats.forEach(latY => {
      const latR = Math.sqrt(Math.pow(r * 0.85, 2) - Math.pow(latY, 2));
      ctx.beginPath();
      ctx.moveTo(-latR, latY);
      ctx.lineTo(latR, latY);
      ctx.stroke();
    });
    
    ctx.fillStyle = '#ffffff';
    for (let i = 0; i < 3; i++) {
      const shift = rotation + (i * Math.PI) / 3;
      const scaleX = Math.cos(shift);
      
      lats.forEach(latY => {
        const latR = Math.sqrt(Math.pow(r * 0.85, 2) - Math.pow(latY, 2));
        ctx.beginPath();
        ctx.arc(latR * scaleX, latY, 5, 0, Math.PI * 2);
        ctx.fill();
        ctx.beginPath();
        ctx.arc(-latR * scaleX, latY, 5, 0, Math.PI * 2);
        ctx.fill();
      });
    }
  }

  _drawCodeTerminal(ctx, cx, cy, size, progress, colors) {
    const r = size / 2;
    const w = r * 1.7;
    const h = r * 1.35;
    
    ctx.fillStyle = 'rgba(5, 5, 8, 0.95)';
    ctx.fillRect(-w / 2, -h / 2, w, h);
    
    ctx.strokeStyle = colors[0];
    ctx.lineWidth = 2.5;
    ctx.strokeRect(-w / 2, -h / 2, w, h);
    
    ctx.fillStyle = `rgba(${this._hex2rgb(colors[0])}, 0.2)`;
    ctx.fillRect(-w / 2, -h / 2, w, 32);
    ctx.strokeStyle = colors[0];
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(-w / 2, -h / 2 + 32);
    ctx.lineTo(w / 2, -h / 2 + 32);
    ctx.stroke();
    
    ctx.fillStyle = colors[1];
    [-15, 0, 15].forEach(offset => {
      ctx.beginPath();
      ctx.arc(-w / 2 + 25 + offset, -h / 2 + 16, 4, 0, Math.PI * 2);
      ctx.fill();
    });
    
    ctx.fillStyle = colors[0];
    ctx.font = '700 13px Courier, monospace';
    ctx.textAlign = 'left';
    
    const lineSpacing = 22;
    const maxLines = 6;
    const elapsedTicks = Math.floor(this.metaphorAngle * 4);
    
    for (let i = 0; i < maxLines; i++) {
      const lineIdx = elapsedTicks + i;
      const seedVal = (lineIdx * 7823) % 100000;
      let lineText = '';
      if (seedVal % 3 === 0) {
        lineText = `0x${(seedVal % 0xFFFFF).toString(16).toUpperCase()} PUSH ACCUMULATOR`;
      } else if (seedVal % 3 === 1) {
        lineText = `EDGELLM THINKING: ${(seedVal % 100)}% COMPLETE`;
      } else {
        lineText = `SYS_INIT: LOAD_BLOCK_${(seedVal % 256)} SUCCESS`;
      }
      
      const drawY = -h / 2 + 62 + i * lineSpacing;
      if (drawY < h / 2 - 15) {
        ctx.fillText(lineText, -w / 2 + 20, drawY);
      }
    }
    
    const lastLineY = -h / 2 + 62 + (maxLines - 1) * lineSpacing;
    if (lastLineY < h / 2 - 15 && Math.floor(this.metaphorAngle * 4) % 2 === 0) {
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(-w / 2 + 20 + 260, lastLineY - 11, 8, 14);
    }
  }

  _drawDnaHelix(ctx, cx, cy, size, progress, colors) {
    const r = size / 2;
    const helixW = r * 0.7;
    const stepCount = 12;
    
    ctx.lineWidth = 2.5;
    for (let i = 0; i < stepCount; i++) {
      const stepT = i / (stepCount - 1);
      const y = -r * 0.8 + stepT * r * 1.6;
      const phase = stepT * Math.PI * 2.5 + this.metaphorAngle * 1.5;
      
      const x1 = Math.sin(phase) * helixW;
      const x2 = Math.sin(phase + Math.PI) * helixW;
      
      ctx.strokeStyle = `rgba(${this._hex2rgb(colors[0])}, ${Math.cos(phase) > 0 ? 0.6 : 0.25})`;
      ctx.beginPath();
      ctx.moveTo(x1, y);
      ctx.lineTo(x2, y);
      ctx.stroke();
      
      const size1 = (Math.cos(phase) + 1.5) * 5;
      ctx.fillStyle = colors[0];
      ctx.beginPath();
      ctx.arc(x1, y, size1, 0, Math.PI * 2);
      ctx.fill();
      
      const size2 = (Math.cos(phase + Math.PI) + 1.5) * 5;
      ctx.fillStyle = colors[1];
      ctx.beginPath();
      ctx.arc(x2, y, size2, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  // ══════════════════════════════════════════════════════════════════════════
  //  UTILITY HELPERS
  // ══════════════════════════════════════════════════════════════════════════

  _drawVignette(ctx, colors) {
    const grad = ctx.createRadialGradient(540, 960, 600, 540, 960, 1100);
    grad.addColorStop(0, 'rgba(0,0,0,0)');
    grad.addColorStop(1, 'rgba(0,0,0,0.55)');
    ctx.save();
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, this.width, this.height);
    ctx.restore();
  }

  _wrapText(ctx, text, maxWidth, fontSize) {
    ctx.font = `500 ${fontSize}px Inter, sans-serif`;
    const words = text.split(' ');
    const lines = [];
    let current = '';
    words.forEach(w => {
      const test = current ? current + ' ' + w : w;
      if (ctx.measureText(test).width > maxWidth && current) {
        lines.push(current); current = w;
      } else { current = test; }
    });
    if (current) lines.push(current);
    return lines;
  }

  _roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y); ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r); ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h); ctx.quadraticCurveTo(x, y + h, x, y + h - r);
    ctx.lineTo(x, y + r); ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
  }

  _hex2rgb(hex) {
    if (!hex || hex.length < 4) return '0,0,0';
    const h = hex.replace('#','');
    const full = h.length === 3
      ? h.split('').map(c => c + c).join('')
      : h;
    const r = parseInt(full.substring(0,2),16);
    const g = parseInt(full.substring(2,4),16);
    const b = parseInt(full.substring(4,6),16);
    return `${r},${g},${b}`;
  }

  // Kept for backwards compatibility
  hexToRgb(hex) { return this._hex2rgb(hex); }

  _easeInOutCubic(t) {
    return t < 0.5 ? 4*t*t*t : 1 - Math.pow(-2*t+2, 3)/2;
  }
  _easeOutCubic(t) {
    return 1 - Math.pow(1-t, 3);
  }
  _easeOutBounce(t) {
    if (t < 1/2.75) return 7.5625*t*t;
    if (t < 2/2.75) { t -= 1.5/2.75;  return 7.5625*t*t + 0.75; }
    if (t < 2.5/2.75){ t -= 2.25/2.75; return 7.5625*t*t + 0.9375; }
    t -= 2.625/2.75; return 7.5625*t*t + 0.984375;
  }

  // ── Legacy API compatibility aliases ─────────────────────────────────────
  drawBackground(delta)              { /* replaced by _drawBgCore */ }
  drawTimelineComposition(ctx,s,c)   { this._drawTimelineComposition(ctx,s,c); }
  drawVisualMetaphor(ctx,t,x,y,s,a,c){ this._drawVisualMetaphor(ctx,t,x,y,s,a,c,0); }
  drawKineticHeadline(ctx,text,cx,cy,fs,t,c){ this._drawStyledHeadline(ctx,text,cx,cy,fs,t,c,'slam_down'); }
  triggerCyanBurst()                  { this._triggerSceneLayer({type:'particle_burst',trigger_at:0,count:45,intensity:0.8}, this.getCurrentSlide() || {theme_colors:["#00ffcc","#ff007f","#06060e"]}); }
}

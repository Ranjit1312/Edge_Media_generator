// Main dashboard controller
document.addEventListener("DOMContentLoaded", () => {
  // Elements
  const btnGenerate = document.getElementById("btn-generate");
  const subjectInput = document.getElementById("subject-input");
  const logConsole = document.getElementById("log-console");
  const btnResetLock = document.getElementById("btn-reset-lock");
  
  // Controls Elements
  const btnPrev = document.getElementById("btn-prev");
  const btnPlayPause = document.getElementById("btn-play-pause");
  const btnNext = document.getElementById("btn-next");
  const currentSlideNum = document.getElementById("current-slide-num");
  const slideProgressFill = document.getElementById("slide-progress");
  const speedSlider = document.getElementById("speed-slider");
  const btnExportVideo = document.getElementById("btn-export-video");
  const canvasPlaceholder = document.getElementById("canvas-placeholder");
  const typographicOverlay = document.getElementById("typographic-overlay");
  
  // Overlays
  const recordingOverlay = document.getElementById("recording-overlay");
  const recordingProgressBar = document.getElementById("recording-progress-bar");
  const recordingStatus = document.getElementById("recording-status");
  
  // Install Progress Panel
  const installPanel = document.getElementById("install-bar-panel");
  const installTitle = document.getElementById("install-title");
  const installProgressBar = document.getElementById("install-progress-bar");
  const installMessage = document.getElementById("install-message");

  // System health elements
  const ollamaIndicator = document.getElementById("ollama-status-indicator");
  const statModel = document.getElementById("stat-model");
  const statCpu = document.getElementById("stat-cpu");
  const statRam = document.getElementById("stat-ram");
  const statGpu = document.getElementById("stat-gpu");

  // State
  let configData = null;
  let activeRunId = null;
  let activeEventSource = null;
  let systemStatInterval = null;
  let isSetupComplete = false;
  let isPipelineActive = false;
  let hasPendingDevChanges = false;
  let currentActiveConfig = { dev_mode: false, mappings: {} };
  let activeAudio = null;
  let exportAudioContext = null;
  let exportAudioDestination = null;
  // Initialize Canvas Engine
  const engine = new AnimationEngine("studio-canvas");

  // --- HARDWARE DIAGNOSTICS & OLLAMA MONITORING ---
  
  function updateSystemMetrics() {
    fetch("/api/system")
      .then(res => res.json())
      .then(data => {
        // CPU
        statCpu.textContent = `${data.cpu_usage_pct}%`;
        
        // RAM
        statRam.textContent = `${data.ram_used_gb} / ${data.ram_total_gb} GB`;
        
        // GPU
        statGpu.textContent = data.gpu_vram_total;
        
        // Ollama Connection State
        if (data.ollama_active) {
          ollamaIndicator.textContent = "● Connected";
          ollamaIndicator.classList.remove("offline");
          ollamaIndicator.classList.add("online");
        } else {
          ollamaIndicator.textContent = "● Offline";
          ollamaIndicator.classList.remove("online");
          ollamaIndicator.classList.add("offline");
        }
      })
      .catch(err => console.error("Metrics collection failed:", err));
  }

  // Poll system details every 3 seconds
  updateSystemMetrics();
  systemStatInterval = setInterval(updateSystemMetrics, 3000);

  // --- SSE STREAM CONSUMER ---
  
  function connectSSE() {
    if (activeEventSource) activeEventSource.close();
    
    activeEventSource = new EventSource("/api/stream");
    
    activeEventSource.onmessage = (event) => {
      const data = JSON.parse(event.data);
      
      // 1. Handle Silent Local Environment Setup logs
      if (data.type === "setup") {
        if (data.step === "complete") {
          installPanel.classList.add("hidden");
          statModel.textContent = data.model_name;
          
          // Reset custom pull button if it was active
          const btnPullCustom = document.getElementById("btn-pull-custom");
          const inputCustomPull = document.getElementById("input-custom-pull");
          if (btnPullCustom) {
            btnPullCustom.classList.remove("disabled");
            btnPullCustom.removeAttribute("disabled");
            btnPullCustom.innerHTML = "Pull Model";
          }
          if (inputCustomPull) {
            inputCustomPull.value = "";
          }

          if (!isSetupComplete) {
            isSetupComplete = true;
            enableDevPanel();
            updateGenerateButtonState();
          }
        } else if (data.step === "failed") {
          installPanel.classList.remove("hidden");
          installTitle.textContent = "Local Setup Encountered Errors";
          installProgressBar.style.width = "0%";
          installMessage.textContent = data.message;
          installPanel.style.borderColor = "var(--color-secondary)";
          if (isSetupComplete !== false) {
            isSetupComplete = false;
            updateGenerateButtonState();
            handleDevPanelFailure(data.message);
          }
        } else {
          installPanel.classList.remove("hidden");
          installTitle.textContent = `Setup Active: ${data.step.toUpperCase()}`;
          installProgressBar.style.width = `${data.progress}%`;
          installMessage.textContent = data.message;
          statModel.textContent = data.model_name;
          
          if (isSetupComplete !== false) {
            isSetupComplete = false;
            updateGenerateButtonState();
          }
          
          lockDevPanel(data.step, data.progress, data.message);
        }
      }
            // Handle Human-in-the-Loop Breakpoint Pauses
            // Handle Human-in-the-Loop Breakpoint Pauses
            // Handle Human-in-the-Loop Breakpoint Pauses
      if (data.type === "paused") {
        const modal = document.getElementById("script-editor-modal");
        
        // Fix #2: Only populate and show if the modal is currently hidden.
        // This prevents the 0.3-second SSE loop from constantly clearing your inputs as you type!
        if (modal && modal.classList.contains("hidden")) {
          logLine("system", "Pipeline paused at Breakpoint. Waiting for user review...");
          
          // Populate the script editor modal
          const container = document.getElementById("script-editor-container");
          if (container) {
            container.innerHTML = "";
            
            // Fix #1: Fallback gracefully to the correct backend property 'scripts_to_edit'
            const scripts = data.scripts_to_edit || data.script || [];
            
            scripts.forEach((slide, idx) => {
              const slideCard = document.createElement("div");
              slideCard.className = "script-slide-card"; // Match CSS rules exactly
              
              slideCard.innerHTML = `
                <h4>Scene ${idx + 1}</h4>
                <div class="editor-grid-row">
                  <div class="editor-field" style="grid-column: span 2;">
                    <label>Headline Hook</label>
                    <textarea class="script-headline" rows="1">${slide.headline}</textarea>
                  </div>
                  <div class="editor-field">
                    <label>Background Context</label>
                    <textarea class="script-context" rows="3">${slide.context}</textarea>
                  </div>
                  <div class="editor-field">
                    <label>Current Update</label>
                    <textarea class="script-update" rows="3">${slide.update}</textarea>
                  </div>
                  <div class="editor-field" style="grid-column: span 2;">
                    <label>Potential Impact</label>
                    <textarea class="script-impact" rows="3">${slide.impact}</textarea>
                  </div>
                </div>
              `;
              container.appendChild(slideCard);
            });
            
            modal.classList.remove("hidden");
            updateNodesUI("scriptwriter"); 
          }
        }
      }
      
      // 2. Handle Multi-Agent LangGraph node states & logs
      if (data.type === "log") {
        // Append log line to visual terminal console
        const line = document.createElement("div");
        line.className = `log-line ${data.active_step}`;
        line.textContent = `[${data.active_step.toUpperCase()}] ${data.content}`;
        logConsole.appendChild(line);
        logConsole.scrollTop = logConsole.scrollHeight;
        
        // Update nodes visual glowing loops in real time
        updateNodesUI(data.active_step);

        if (data.active_step === "failed") {
          isPipelineActive = false;
          updateGenerateButtonState();
        }
      }
      
      // 3. Handle Completed Configuration Data
      // 3. Handle Completed Configuration Data
      if (data.type === "config" && data.config) {
        // Only load the studio animation if this is a new run or hasn't loaded yet
        if (activeRunId !== data.run_id || !configData) {
          configData = data.config;
          if (data.run_id) {
            activeRunId = data.run_id;
          }
          logLine("system", `Visual Director configuration successfully loaded. Run ID: ${activeRunId || 'unknown'}. Booting Portrait Studio...`);
          isPipelineActive = false;
          loadStudioAnimation(data.config);
          loadRunHistory(); // Refresh sidebar history
        }
      }
    };

    activeEventSource.onerror = () => {
      console.warn("SSE link disconnected. Reconnecting...");
    };
  }

  // Connect SSE immediately
  connectSSE();

  // --- ACTIONS ---

    // --- CANCEL EDIT HOOK ---
  const btnCancelEdit = document.getElementById("btn-cancel-edit");
  if (btnCancelEdit) {
    btnCancelEdit.addEventListener("click", () => {
      document.getElementById("script-editor-modal").classList.add("hidden");
      logLine("system", "Pipeline run cancelled by user.");
      
      // Reset the pipeline server lock
      fetch("/api/reset", { method: "POST" })
        .then(res => res.json())
        .then(data => {
          isPipelineActive = false;
          updateGenerateButtonState();
        })
        .catch(err => console.error("Cancel reset failed:", err));
    });
  }

  // --- PIPELINE RESUME HOOK ---
  // --- PIPELINE RESUME HOOK ---
  const btnResumePipeline = document.getElementById("btn-resume-pipeline");
  if (btnResumePipeline) {
    btnResumePipeline.addEventListener("click", () => {
      const container = document.getElementById("script-editor-container");
      const slideBoxes = container.querySelectorAll(".script-slide-card");
      const editedScript = [];
      
      slideBoxes.forEach(box => {
        editedScript.push({
          headline: box.querySelector(".script-headline").value,
          context: box.querySelector(".script-context").value,
          update: box.querySelector(".script-update").value,
          impact: box.querySelector(".script-impact").value
        });
      });
      
      document.getElementById("script-editor-modal").classList.add("hidden");
      logLine("system", "Submitting revised script and resuming pipeline to Director & Voice Synthesizer...");
      
      // Fix #4: Correct DOM query element IDs to match index.html
      const maxStories = document.getElementById("slides-count")?.value || "1";
      const voicePersona = document.getElementById("voice-persona-select")?.value || "af_bella";

      // Fix #3: Send 'subject' and map key 'final_scripts' to match the FastAPI ResumeRequest validator
      fetch("/api/pipeline/resume", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          subject: subjectInput.value.trim(),
          final_scripts: editedScript,
          voice_persona: voicePersona
        })
      })
      .then(res => res.json())
      .then(data => {
        if (!data.success) {
          logLine("system", `ERROR: Resume failed - ${data.error}`);
        }
      })
      .catch(err => logLine("system", `Resume network error: ${err}`));
    });
  }

  // --- VISUAL RERUN HOOK ---
  const btnRegenerateVisuals = document.getElementById("btn-regenerate-visuals");
  if (btnRegenerateVisuals) {
    btnRegenerateVisuals.addEventListener("click", () => {
      const selectedModel = document.getElementById("rerun-model-select")?.value || "gemma4:e4b";
      logLine("system", `Requesting visual regeneration directly to Director node using ${selectedModel}...`);
      
      fetch("/api/pipeline/regenerate_visuals", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ director_model: selectedModel })
      })
      .then(res => res.json())
      .then(data => {
        if (!data.success) {
          logLine("system", `ERROR: Regeneration failed - ${data.error}`);
        }
      })
      .catch(err => logLine("system", `Regenerate network error: ${err}`));
    });
  }

  btnGenerate.addEventListener("click", () => {
    const subject = subjectInput.value.trim();
    if (!subject) return;
    
    // Reset pipeline state
    logConsole.innerHTML = "";
    logLine("system", `Launching on-device Multi-Agent LangGraph Pipeline for Subject: '${subject}'...`);
    
    isPipelineActive = true;
    updateGenerateButtonState();
    
    // Trigger REST launch
    fetch("/api/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ subject: subject })
    })
    .then(res => res.json())
    .then(res => {
      if (!res.success) {
        logLine("system", `ERROR: ${res.error}`);
        isPipelineActive = false;
        updateGenerateButtonState();
      }
    })
    .catch(err => {
      logLine("system", `HTTP Connection Error: ${err}`);
      isPipelineActive = false;
      updateGenerateButtonState();
    });
  });

  // Playback Control Triggers
  btnPlayPause.addEventListener("click", () => {
    if (engine.isPlaying) {
      engine.pause();
      btnPlayPause.textContent = "▶";
      if (activeAudio) activeAudio.pause(); // <--- ADD THIS
    } else {
      engine.play();
      btnPlayPause.textContent = "⏸";
      if (activeAudio) activeAudio.play().catch(e => console.warn("Audio blocked:", e)); // <--- ADD THIS
    }
  });

  btnPrev.addEventListener("click", () => {
    if (engine.currentSlideIndex > 0) {
      engine.setSlide(engine.currentSlideIndex - 1);
    }
  });

  btnNext.addEventListener("click", () => {
    if (configData && engine.currentSlideIndex < configData.slides.length - 1) {
      engine.setSlide(engine.currentSlideIndex + 1);
    }
  });

  speedSlider.addEventListener("input", (e) => {
    engine.setSpeed(e.target.value);
  });

  // Hook Studio callbacks
  engine.onSlideChange = (idx) => {
    updateSlideDisplay(idx);
  };

  engine.onComplete = () => {
    btnPlayPause.textContent = "▶";
    slideProgressFill.style.width = "100%";
    logLine("system", "Social media animation play cycle complete.");
    
    // <--- ADD THIS BLOCK
    if (activeAudio) {
      activeAudio.pause();
      activeAudio.currentTime = 0;
    }
  };
  // Run rendering updates inside animation frame to track slide timing filled track
  function renderProgressLoop() {
    if (engine.isPlaying && configData) {
      slideProgressFill.style.width = `${engine.slideProgress * 100}%`;
    }
    requestAnimationFrame(renderProgressLoop);
  }
  requestAnimationFrame(renderProgressLoop);

  // --- HIGH QUALITY VIDEO EXPORTER (MediaRecorder Throttling bypass) ---
  
  btnExportVideo.addEventListener("click", () => {
    if (!configData) return;
    
    // Pause live loops
    engine.pause();
    btnPlayPause.textContent = "▶";
    
    // Deploy Lock Screen Overlay
    recordingOverlay.classList.remove("hidden");
    recordingProgressBar.style.width = "0%";
    recordingStatus.textContent = "Initializing high-bitrate encoding...";
    
    // Fetch canvas capture stream at solid 60 FPS
   // WITH THIS UNIFIED MULTI-MODAL STREAM GENERATOR:
    const canvas = document.getElementById("studio-canvas");
    const videoStream = canvas.captureStream(60);
    
    // Set up Audio Context for merging WebAudio tracks
    exportAudioContext = new (window.AudioContext || window.webkitAudioContext)();
    exportAudioDestination = exportAudioContext.createMediaStreamDestination();
    
    // Create unified multi-modal stream
    const stream = new MediaStream([
      ...videoStream.getVideoTracks(),
      ...exportAudioDestination.stream.getAudioTracks()
    ]);
    
    // Configure WebM high quality settings (VP9 with 8Mbps has amazing porting color fidelity)
    let options = { mimeType: 'video/webm;codecs=vp9', videoBitsPerSecond: 8000000 };
    if (!MediaRecorder.isTypeSupported(options.mimeType)) {
      options = { mimeType: 'video/webm', videoBitsPerSecond: 6000000 };
    }
    
    const chunks = [];
    const mediaRecorder = new MediaRecorder(stream, options);
    
    mediaRecorder.ondataavailable = e => {
      if (e.data.size > 0) chunks.push(e.data);
    };
    
    mediaRecorder.onstop = () => {
      const blob = new Blob(chunks, { type: 'video/webm' });
      const url = URL.createObjectURL(blob);
      
      // Auto trigger file download
      const filename = `${subjectInput.value.trim().toLowerCase().replace(/\s+/g, "_")}_portrait_1080x1920.webm`;
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      
      logLine("system", `High-quality video export downloaded successfully as: ${filename}`);
      
      // Sync WebM render to backend server for history and comparisons
      if (activeRunId) {
        logLine("system", `Synchronizing WebM video render on server for run ID: ${activeRunId}...`);
        const formData = new FormData();
        formData.append("file", blob, "video.webm");
        
        fetch(`/api/runs/${activeRunId}/upload_video`, {
          method: "POST",
          body: formData
        })
        .then(res => res.json())
        .then(resData => {
          if (resData.success) {
            logLine("system", `Video successfully linked to run ID ${activeRunId} in the server repository.`);
            loadRunHistory(); // Refresh history listing to show play button
          } else {
            logLine("system", `Server upload failed: ${resData.error}`);
          }
        })
        .catch(err => {
          logLine("system", `Server upload network error: ${err}`);
        });
      } else {
        logLine("system", "Warning: No active run ID recorded. Skipping backend video sync.");
      }
      
      // Release overlay lock and reset playback
      recordingOverlay.classList.add("hidden");
      engine.setSlide(0);
    };

    // Begin programmatic slide transitions capture
    const totalSlides = configData.slides.length;
    
    // Track original callbacks to restore later
    const originalOnSlideChange = engine.onSlideChange;
    const originalOnComplete = engine.onComplete;
    
    // Update progress on slide change during export
    engine.onSlideChange = (idx) => {
      if (originalOnSlideChange) originalOnSlideChange(idx);
      const progressPercent = Math.round((idx / totalSlides) * 100);
      recordingProgressBar.style.width = `${progressPercent}%`;
      recordingStatus.textContent = `Rendering Scene: ${idx + 1} / ${totalSlides} (${progressPercent}% encoded)`;
    };
    
    // Complete callback stops recording and restores original hooks
    engine.onComplete = () => {
      engine.stopExport();
      mediaRecorder.stop();
      
      // ─── ADD THE CLEANUP HERE ───
      if (exportAudioContext) {
        exportAudioContext.close();
        exportAudioContext = null;
        exportAudioDestination = null;
      }
      
      engine.onComplete = originalOnComplete;
      engine.onSlideChange = originalOnSlideChange;
      if (originalOnComplete) originalOnComplete();
    };

    // Jump to start and trigger headless playback sequence
    engine.exportMode = true;
    engine.setSlide(0);
    mediaRecorder.start();
    engine.play();
  });


  // --- HELPERS ---

  function loadStudioAnimation(config) {
    // Hide placeholders
    canvasPlaceholder.classList.add("hidden");
    typographicOverlay.classList.remove("hidden");
    
    // Load config to canvas engine with try-catch safety
    try {
      engine.loadConfig(config);
    } catch (e) {
      console.error("Canvas Engine failed to load config:", e);
      logLine("system", "WARNING: Animation engine encountered a rendering exception. Graceful degradation active.");
    }
    
    // Enable studio controls
    btnPrev.classList.remove("disabled");
    btnPrev.removeAttribute("disabled");
    btnPlayPause.classList.remove("disabled");
    btnPlayPause.removeAttribute("disabled");
    btnNext.classList.remove("disabled");
    btnNext.removeAttribute("disabled");
    speedSlider.classList.remove("disabled");
    speedSlider.removeAttribute("disabled");
    btnExportVideo.classList.remove("disabled");
    btnExportVideo.removeAttribute("disabled");
    
    // Set slide displays
    updateSlideDisplay(0);
    resetGenerateButton();
  }

  function updateSlideDisplay(index) {
    if (!configData) return;
    
    // Update numbering
    currentSlideNum.textContent = `${index + 1} / ${configData.slides.length}`;
    
    // Trigger typographic overlay fade classes (HTML indicators)
    const card = typographicOverlay.querySelector(".slide-card");
    card.classList.remove("active");
    
    // Load text details
    const slide = configData.slides[index];
    document.getElementById("slide-headline").textContent = slide.headline.toUpperCase();
    document.getElementById("slide-context").textContent = slide.context;
    document.getElementById("slide-update").textContent = slide.update;
    document.getElementById("slide-impact").textContent = slide.impact;
    
    // Trigger entry transition
    setTimeout(() => {
      card.classList.add("active");
    }, 50);
    // --- SYNCHRONIZED AUDIO PLAYBACK ---
    if (activeAudio) {
      activeAudio.pause();
      activeAudio.currentTime = 0;
    }
    
    if (slide.audio_url) {
      activeAudio = new Audio(slide.audio_url);
      activeAudio.crossOrigin = "anonymous";
      
      // If we are currently exporting, route audio into the MediaRecorder stream
      if (exportAudioContext && exportAudioDestination) {
        try {
          const source = exportAudioContext.createMediaElementSource(activeAudio);
          source.connect(exportAudioDestination);
          source.connect(exportAudioContext.destination); // Also play to local speakers
        } catch(e) {
          console.warn("Audio routing failed:", e);
        }
      }
      
      // Start playing if engine is active or if we are rendering an export
      if (engine.isPlaying || exportAudioContext) {
        activeAudio.play().catch(err => console.warn("Audio play blocked by browser:", err));
      }
    }
  }

  function updateNodesUI(activeStep) {
    // Remove active and looping states from all nodes
    document.querySelectorAll(".node-item").forEach(node => {
      node.classList.remove("active", "looping");
      
      // Add completed styles to preceding nodes
      const circleText = parseInt(node.querySelector(".node-circle").textContent);
      const stepOrder = { "researcher": 1, "editor": 2, "scriptwriter": 3, "director": 4 };
      const currentActiveOrder = stepOrder[activeStep] || 0;
      
      const statusSpan = node.querySelector(".node-status");
      
      if (circleText < currentActiveOrder) {
        node.classList.add("completed");
        statusSpan.textContent = "Done";
      } else if (circleText === currentActiveOrder) {
        node.classList.add("active");
        statusSpan.textContent = "Running";
      } else {
        node.classList.remove("completed");
        statusSpan.textContent = "Idle";
      }
    });

    // Special loopback indicator for editor node
    if (activeStep === "editor" && logConsole.innerHTML.includes("Loopbacking")) {
      const editorNode = document.getElementById("node-editor");
      editorNode.classList.add("looping");
      editorNode.querySelector(".node-status").textContent = "Looping";
    }
  }

  function logLine(step, text) {
    const line = document.createElement("div");
    line.className = `log-line ${step}`;
    line.textContent = `[${step.toUpperCase()}] ${text}`;
    logConsole.appendChild(line);
    logConsole.scrollTop = logConsole.scrollHeight;
  }

  function resetGenerateButton() {
    updateGenerateButtonState();
  }

  // --- DEVELOPER PANEL CONTROLLER ---
  
  const devModeToggle = document.getElementById("dev-mode-toggle");
  const devOptions = document.getElementById("dev-options");
  
  const selectResearcher = document.getElementById("select-researcher");
  const inputCustomResearcher = document.getElementById("input-custom-researcher");
  
  const selectEditor = document.getElementById("select-editor");
  const inputCustomEditor = document.getElementById("input-custom-editor");
  
  const selectScriptwriter = document.getElementById("select-scriptwriter");
  const inputCustomScriptwriter = document.getElementById("input-custom-scriptwriter");
  
  const selectDirector = document.getElementById("select-director");
  const inputCustomDirector = document.getElementById("input-custom-director");
  
  const btnSaveDev = document.getElementById("btn-save-dev");

  const RECOMMENDED_MODELS = [
    { tag: "gemma2:2b", name: "Gemma 2 2B (Default Editor)" },
    { tag: "gemma4:e4b", name: "Gemma 4 8B (Default Creative)" },
    { tag: "llama3.2:3b", name: "Llama 3.2 3B (Lightweight Balanced)" },
    { tag: "qwen2.5-coder:1.5b", name: "Qwen 2.5 Coder 1.5B (Ultra-fast)" },
    { tag: "qwen2.5-coder:3b", name: "Qwen 2.5 Coder 3B (Logic King)" },
    { tag: "qwen3:4b", name: "Qwen 3 4B (Next-Gen Compact)" },
    { tag: "phi3:3.8b", name: "Phi 3 3.8B (High Performance)" },
    { tag: "mistral:7b", name: "Mistral 7B (Advanced Creative)" }
  ];

  let lastFetchedModelsData = null;

  const devStatusBadge = document.getElementById("dev-status-badge");

  function updateDevBadgeState() {
    if (!devStatusBadge || !lastFetchedModelsData) return;

    const resolveModelTag = (selectEl, customInputEl) => {
      if (selectEl.value === "custom") {
        return customInputEl.value.trim();
      }
      return selectEl.value;
    };

    const visualDevMode = devModeToggle.checked;
    const visualMappings = {
      "researcher_fallback": resolveModelTag(selectResearcher, inputCustomResearcher),
      "editor": resolveModelTag(selectEditor, inputCustomEditor),
      "scriptwriter": resolveModelTag(selectScriptwriter, inputCustomScriptwriter),
      "director": resolveModelTag(selectDirector, inputCustomDirector)
    };

    let badgeClass = "inactive";
    let badgeText = "Inactive";

    const backendDevMode = currentActiveConfig.dev_mode;
    const backendMappings = currentActiveConfig.mappings || {};

    if (visualDevMode !== backendDevMode) {
      badgeClass = "pending";
      badgeText = "Pending Changes";
    } else if (visualDevMode === false) {
      badgeClass = "inactive";
      badgeText = "Inactive";
    } else {
      let isDifferent = false;
      for (const [node, model] of Object.entries(visualMappings)) {
        if (backendMappings[node] !== model) {
          isDifferent = true;
          break;
        }
      }
      if (isDifferent) {
        badgeClass = "pending";
        badgeText = "Pending Changes";
      } else {
        badgeClass = "active";
        badgeText = "Active (A/B Test)";
      }
    }

    devStatusBadge.className = `dev-badge ${badgeClass}`;
    devStatusBadge.textContent = badgeText;

    hasPendingDevChanges = (badgeText === "Pending Changes");
    updateGenerateButtonState();
  }

  function updateGenerateButtonState() {
    const isSetupRunning = !isSetupComplete;
    
    if (isSetupRunning || isPipelineActive) {
      btnGenerate.classList.add("disabled");
      btnGenerate.setAttribute("disabled", "true");
      if (isPipelineActive) {
        btnGenerate.innerHTML = "Generating Video...";
      } else {
        btnGenerate.innerHTML = "Initializing Engine...";
      }
      return;
    }

    if (hasPendingDevChanges) {
      btnGenerate.classList.add("disabled");
      btnGenerate.setAttribute("disabled", "true");
      btnGenerate.innerHTML = "Apply Dev Config First";
      return;
    }

    btnGenerate.classList.remove("disabled");
    btnGenerate.removeAttribute("disabled");
    btnGenerate.innerHTML = "Generate Production Video";
  }

  function initDeveloperPanel() {
    // 1. Fetch available models and active config
    fetch("/api/models")
      .then(res => res.json())
      .then(data => {
        lastFetchedModelsData = data;
        currentActiveConfig.dev_mode = (data.mode === "developer");
        currentActiveConfig.mappings = data.node_assignments || {};

        if (!hasPendingDevChanges) {
          const isDev = data.mode === "developer";
          devModeToggle.checked = isDev;
          
          if (isDev) {
            devOptions.classList.remove("hidden");
          } else {
            devOptions.classList.add("hidden");
          }
        }
        
        const populateSelect = (selectEl, customInputEl, nodeName) => {
          const visualChoice = selectEl.value;
          const visualCustomVal = customInputEl.value;
          
          selectEl.innerHTML = "";
          
          const currentAssigned = data.node_assignments ? data.node_assignments[nodeName] : "";
          const targetValue = (hasPendingDevChanges && visualChoice) ? visualChoice : currentAssigned;
          const targetCustomValue = (hasPendingDevChanges && visualChoice) ? visualCustomVal : currentAssigned;
          
          const uniqueTags = new Set();
          const optionsList = [];
          
          const registerOption = (tag, label, isReady) => {
            if (uniqueTags.has(tag)) return;
            uniqueTags.add(tag);
            optionsList.push({ tag, label, isReady });
          };
          
          // Register recommended
          RECOMMENDED_MODELS.forEach(m => {
            const available = (data.available || []).map(a => a.toLowerCase());
            const mTag = m.tag.toLowerCase();
            const isReady = available.includes(mTag) || 
                            available.includes(mTag.split(':')[0]) || 
                            available.includes(mTag + ":latest") || 
                            available.includes(mTag.replace(":latest", ""));
            const availabilityTag = isReady ? "[Ready]" : "[Download Req.]";
            registerOption(m.tag, `${availabilityTag} ${m.name}`, isReady);
          });
          
          // Register currently pulled that are not recommended
          if (data.available) {
            data.available.forEach(tag => {
              if (!uniqueTags.has(tag)) {
                registerOption(tag, `[Ready] ${tag} (Local)`, true);
              }
            });
          }
          
          // Register active assignment if not already in list
          if (currentAssigned && currentAssigned !== "custom" && !uniqueTags.has(currentAssigned)) {
            const available = (data.available || []).map(a => a.toLowerCase());
            const cAssigned = currentAssigned.toLowerCase();
            const isReady = available.includes(cAssigned) || 
                            available.includes(cAssigned.split(':')[0]) || 
                            available.includes(cAssigned + ":latest") || 
                            available.includes(cAssigned.replace(":latest", ""));
            const availabilityTag = isReady ? "[Ready]" : "[Download Req.]";
            registerOption(currentAssigned, `${availabilityTag} ${currentAssigned} (Assigned)`, isReady);
          }
          
          // Add Custom option
          optionsList.push({ tag: "custom", label: "+ Add Custom Model Tag...", isReady: true });
          
          // Render options
          optionsList.forEach(opt => {
            const o = document.createElement("option");
            o.value = opt.tag;
            o.textContent = opt.label;
            selectEl.appendChild(o);
          });
          
          // Determine selection
          let selectIsCustom = false;
          if (targetValue) {
            const existsInOptions = Array.from(uniqueTags).includes(targetValue);
            if (existsInOptions) {
              selectEl.value = targetValue;
            } else {
              selectEl.value = "custom";
              customInputEl.value = targetCustomValue;
              customInputEl.classList.remove("hidden");
              selectIsCustom = true;
            }
          }
          
          if (!selectIsCustom) {
            customInputEl.classList.add("hidden");
            if (!hasPendingDevChanges) {
              customInputEl.value = "";
            }
          }
        };
        
        populateSelect(selectResearcher, inputCustomResearcher, "researcher_fallback");
        populateSelect(selectEditor, inputCustomEditor, "editor");
        populateSelect(selectScriptwriter, inputCustomScriptwriter, "scriptwriter");
        populateSelect(selectDirector, inputCustomDirector, "director");

        updateGraphNodesModels(data.node_assignments);
        checkDownloadRequirements();
      })
      .catch(err => console.error("Failed to load developer models:", err));
  }

  function checkDownloadRequirements() {
    if (!lastFetchedModelsData) return;
    
    const validateFieldState = (selectEl, customInputEl) => {
      const rawTag = selectEl.value === "custom" ? customInputEl.value.trim() : selectEl.value;
      if (!rawTag) {
        selectEl.classList.remove("model-ready", "model-download-req");
        customInputEl.classList.remove("model-ready", "model-download-req");
        return true; 
      }
      
      const tag = rawTag.toLowerCase();
      const available = (lastFetchedModelsData.available || []).map(a => a.toLowerCase());
      
      const baseTag = tag.split(':')[0];
      const hasLatest = tag.endsWith(":latest") || !tag.includes(":");
      
      const isReady = available.some(a => {
        const normA = a.trim().toLowerCase();
        if (normA === tag) return true;
        
        const aBase = normA.split(':')[0];
        const aHasLatest = normA.endsWith(":latest") || !normA.includes(":");
        
        if (baseTag === aBase && (hasLatest || aHasLatest)) {
          return true;
        }
        return false;
      });
      
      if (isReady) {
        selectEl.classList.add("model-ready");
        selectEl.classList.remove("model-download-req");
        customInputEl.classList.add("model-ready");
        customInputEl.classList.remove("model-download-req");
        return true;
      } else {
        selectEl.classList.remove("model-ready");
        selectEl.classList.add("model-download-req");
        customInputEl.classList.remove("model-ready");
        customInputEl.classList.add("model-download-req");
        return false;
      }
    };
    
    const isResearcherReady = validateFieldState(selectResearcher, inputCustomResearcher);
    const isEditorReady = validateFieldState(selectEditor, inputCustomEditor);
    const isScriptwriterReady = validateFieldState(selectScriptwriter, inputCustomScriptwriter);
    const isDirectorReady = validateFieldState(selectDirector, inputCustomDirector);
    
    const needsDownload = !(isResearcherReady && isEditorReady && isScriptwriterReady && isDirectorReady);
    
    if (needsDownload) {
      btnSaveDev.innerHTML = "☁ Download & Apply Model Mappings";
      btnSaveDev.classList.add("primary");
      btnSaveDev.classList.remove("secondary");
    } else {
      btnSaveDev.innerHTML = "Apply Model Mappings";
      btnSaveDev.classList.remove("primary");
      btnSaveDev.classList.add("secondary");
    }

    updateDevBadgeState();
  }

  const setupDropdownListeners = (selectEl, customInputEl) => {
    selectEl.addEventListener("change", () => {
      if (selectEl.value === "custom") {
        customInputEl.classList.remove("hidden");
        customInputEl.focus();
      } else {
        customInputEl.classList.add("hidden");
      }
      checkDownloadRequirements();
    });
    
    customInputEl.addEventListener("input", () => {
      checkDownloadRequirements();
    });
  };

  setupDropdownListeners(selectResearcher, inputCustomResearcher);
  setupDropdownListeners(selectEditor, inputCustomEditor);
  setupDropdownListeners(selectScriptwriter, inputCustomScriptwriter);
  setupDropdownListeners(selectDirector, inputCustomDirector);

  // Bind change event to toggle dynamic mode options visibility
  devModeToggle.addEventListener("change", (e) => {
    const active = e.target.checked;
    if (active) {
      devOptions.classList.remove("hidden");
      checkDownloadRequirements();
    } else {
      devOptions.classList.add("hidden");
      saveDeveloperConfig(false, {});
    }
  });

  // Bind click event to save settings
  btnSaveDev.addEventListener("click", () => {
    const resolveModelTag = (selectEl, customInputEl) => {
      if (selectEl.value === "custom") {
        return customInputEl.value.trim();
      }
      return selectEl.value;
    };

    const mappings = {
      "researcher_fallback": resolveModelTag(selectResearcher, inputCustomResearcher),
      "editor": resolveModelTag(selectEditor, inputCustomEditor),
      "scriptwriter": resolveModelTag(selectScriptwriter, inputCustomScriptwriter),
      "director": resolveModelTag(selectDirector, inputCustomDirector)
    };
    
    if (Object.values(mappings).some(v => v === "")) {
      logLine("system", "ERROR: Please specify a valid model tag for all active nodes.");
      return;
    }
    
    saveDeveloperConfig(true, mappings);
  });

  function saveDeveloperConfig(enabled, mappings) {
    btnSaveDev.classList.add("disabled");
    btnSaveDev.setAttribute("disabled", "true");
    
    fetch("/api/dev/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        dev_mode: enabled,
        node_models: mappings
      })
    })
    .then(res => res.json())
    .then(res => {
      btnSaveDev.classList.remove("disabled");
      btnSaveDev.removeAttribute("disabled");
      
      if (res.success) {
        const modeText = enabled ? "Active A/B Test" : "Hardcoded Production 2-Model Split";
        logLine("system", `Developer configuration applied successfully. Mode: ${modeText}.`);
        if (enabled) {
          logLine("system", `Active node assignments: Researcher=${mappings.researcher_fallback}, Editor=${mappings.editor}, Scriptwriter=${mappings.scriptwriter}, Director=${mappings.director}`);
          if (res.needs_download) {
            logLine("system", `SYSTEM: Selected developer model(s) [${res.missing_models.join(', ')}] not found locally. Initiating cloud-download...`);
          }
        }
        
        // Refresh local UI configuration states
        initDeveloperPanel();
      } else {
        logLine("system", `ERROR: Failed to save developer config: ${res.error}`);
      }
    })
    .catch(err => {
      btnSaveDev.classList.remove("disabled");
      btnSaveDev.removeAttribute("disabled");
      logLine("system", `HTTP Connection Error: ${err}`);
    });
  }

  function enableDevPanel() {
    devModeToggle.removeAttribute("disabled");
    
    document.querySelectorAll(".dev-select, .dev-custom-input").forEach(el => {
      el.removeAttribute("disabled");
    });
    btnSaveDev.removeAttribute("disabled");
    btnSaveDev.classList.remove("disabled");
    
    initDeveloperPanel();
  }

  function lockDevPanel(step, progress, message) {
    devModeToggle.setAttribute("disabled", "true");
    
    document.querySelectorAll(".dev-select, .dev-custom-input").forEach(el => {
      el.setAttribute("disabled", "true");
    });
    
    btnSaveDev.setAttribute("disabled", "true");
    btnSaveDev.classList.add("disabled");
    
    if (step === "pulling_model") {
      btnSaveDev.innerHTML = `⚡ Downloading Fleet... ${progress}%`;
    } else if (step === "starting_server") {
      btnSaveDev.innerHTML = `⚙ Starting Ollama...`;
    } else {
      btnSaveDev.innerHTML = `⏳ Initializing Setup...`;
    }
  }

  function handleDevPanelFailure(errorMsg) {
    devModeToggle.removeAttribute("disabled");
    btnSaveDev.innerHTML = "⚠️ Setup Failed - Apply Again";
    btnSaveDev.classList.remove("disabled");
    btnSaveDev.removeAttribute("disabled");
    btnSaveDev.classList.add("primary");
  }

  function updateGraphNodesModels(nodeAssignments) {
    if (!nodeAssignments) return;
    
    const mappings = {
      "node-researcher": nodeAssignments.researcher_fallback,
      "node-editor": nodeAssignments.editor,
      "node-scriptwriter": nodeAssignments.scriptwriter,
      "node-director": nodeAssignments.director
    };
    
    Object.entries(mappings).forEach(([nodeId, modelTag]) => {
      const nodeEl = document.getElementById(nodeId);
      if (!nodeEl) return;
      
      let tagEl = nodeEl.querySelector(".node-model-name");
      if (!tagEl) {
        tagEl = document.createElement("span");
        tagEl.className = "node-model-name";
        nodeEl.appendChild(tagEl);
      }
      
      tagEl.textContent = modelTag || "unknown";
    });
  }

  function hydrateConfigOnStartup() {
    fetch("/static/config.json")
      .then(res => {
        if (res.ok) return res.json();
        throw new Error("No previous config file found on disk.");
      })
      .then(config => {
        if (config && config.slides && config.slides.length > 0) {
          configData = config;
          logLine("system", "Restoring completed visual configuration from disk...");
          loadStudioAnimation(config);
        }
      })
      .catch(err => {
        console.log("Startup config hydration skipped:", err.message);
      });
  }

  // --- RUN HISTORY & CUSTOM MODEL PULLER BINDINGS ---

  function loadRunHistory() {
    const historyContainer = document.getElementById("history-runs-container");
    if (!historyContainer) return;
    
    fetch("/api/runs/history")
      .then(res => res.json())
      .then(data => {
        if (!data || data.length === 0) {
          historyContainer.innerHTML = `<div class="history-placeholder">No past runs found. Runs will appear here once generated.</div>`;
          return;
        }
        
        historyContainer.innerHTML = "";
        data.forEach(run => {
          const card = document.createElement("div");
          card.className = "history-card";
          
          const modelsList = Object.entries(run.models || {})
            .map(([node, model]) => `${node.toUpperCase().replace('_FALLBACK','')}: ${model}`)
            .join(" | ");
            
          let buttonsHtml = "";
          if (run.has_video) {
            buttonsHtml += `<button class="history-btn play-btn" data-run-id="${run.run_id}">▶ Play Video</button>`;
          }
          buttonsHtml += `<button class="history-btn reuse-btn" data-run-id="${run.run_id}">♻ Reuse News</button>`;
          
          card.innerHTML = `
            <div class="history-header">
              <span class="history-subject" title="${run.subject}">${run.subject}</span>
              <span class="history-time">${run.timestamp}</span>
            </div>
            <div class="history-models" title="${modelsList}">
              ${modelsList || 'Production split default'}
            </div>
            <div class="history-actions">
              ${buttonsHtml}
            </div>
          `;
          
          // Event listener for Play Video
          const playBtn = card.querySelector(".play-btn");
          if (playBtn) {
            playBtn.addEventListener("click", () => {
              const videoPlayer = document.getElementById("modal-video-player");
              const modal = document.getElementById("video-preview-modal");
              videoPlayer.src = `/static/runs/${run.run_id}.webm`;
              document.getElementById("modal-title").textContent = `Preview: ${run.subject} (${run.timestamp})`;
              modal.classList.remove("hidden");
              videoPlayer.play();
            });
          }
          
          // Event listener for Reuse News
          const reuseBtn = card.querySelector(".reuse-btn");
          if (reuseBtn) {
            reuseBtn.addEventListener("click", () => {
              if (isPipelineActive) {
                logLine("system", "WARNING: A pipeline run is already active. Please wait or reset the lock first.");
                return;
              }
              
              subjectInput.value = run.subject;
              logConsole.innerHTML = "";
              logLine("system", `Reusing news and starting generation for subject: '${run.subject}' using cached verified news...`);
              
              isPipelineActive = true;
              updateGenerateButtonState();
              
              fetch("/api/start", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  subject: run.subject,
                  cached_verified_news: run.verified_news
                })
              })
              .then(res => res.json())
              .then(res => {
                if (!res.success) {
                  logLine("system", `ERROR: ${res.error}`);
                  isPipelineActive = false;
                  updateGenerateButtonState();
                }
              })
              .catch(err => {
                logLine("system", `HTTP Connection Error: ${err}`);
                isPipelineActive = false;
                updateGenerateButtonState();
              });
            });
          }
          
          historyContainer.appendChild(card);
        });
      })
      .catch(err => {
        console.error("Failed to load run history:", err);
      });
  }

  // Custom Model Puller logic
  const btnPullCustom = document.getElementById("btn-pull-custom");
  const inputCustomPull = document.getElementById("input-custom-pull");
  
  if (btnPullCustom && inputCustomPull) {
    btnPullCustom.addEventListener("click", () => {
      const modelTag = inputCustomPull.value.trim();
      if (!modelTag) {
        logLine("system", "ERROR: Please enter a valid model tag to pull (e.g., gemma:2b).");
        return;
      }
      
      btnPullCustom.classList.add("disabled");
      btnPullCustom.setAttribute("disabled", "true");
      btnPullCustom.innerHTML = "Pulling...";
      logLine("system", `Initiating Ollama background pull request for model: '${modelTag}'...`);
      
      fetch("/api/dev/pull", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: modelTag })
      })
      .then(res => res.json())
      .then(data => {
        if (data.success) {
          logLine("system", `Ollama pull worker thread activated for '${modelTag}'. Please monitor progress bar above.`);
        } else {
          logLine("system", `ERROR: Failed to start pull for '${modelTag}': ${data.error}`);
          btnPullCustom.classList.remove("disabled");
          btnPullCustom.removeAttribute("disabled");
          btnPullCustom.innerHTML = "Pull Model";
        }
      })
      .catch(err => {
        logLine("system", `HTTP Connection Error: ${err}`);
        btnPullCustom.classList.remove("disabled");
        btnPullCustom.removeAttribute("disabled");
        btnPullCustom.innerHTML = "Pull Model";
      });
    });
  }

  // Lightbox Modal close handlers
  const videoPreviewModal = document.getElementById("video-preview-modal");
  const modalVideoPlayer = document.getElementById("modal-video-player");
  const btnCloseModal = document.getElementById("btn-close-modal");
  const modalBackdrop = videoPreviewModal ? videoPreviewModal.querySelector(".modal-backdrop") : null;
  
  const closeModal = () => {
    if (videoPreviewModal) {
      videoPreviewModal.classList.add("hidden");
    }
    if (modalVideoPlayer) {
      modalVideoPlayer.pause();
      modalVideoPlayer.src = "";
    }
  };
  
  if (btnCloseModal) {
    btnCloseModal.addEventListener("click", closeModal);
  }
  if (modalBackdrop) {
    modalBackdrop.addEventListener("click", closeModal);
  }

  // Event listener for Reset Lock
  if (btnResetLock) {
    btnResetLock.addEventListener("click", () => {
      logLine("system", "Sending reset generation lock signal to server...");
      fetch("/api/reset", { method: "POST" })
        .then(res => res.json())
        .then(data => {
          if (data.success) {
            logLine("system", "Pipeline generation lock cleared successfully.");
            isPipelineActive = false;
            updateGenerateButtonState();
          } else {
            logLine("system", `ERROR: Failed to reset lock: ${data.error}`);
          }
        })
        .catch(err => {
          logLine("system", `HTTP Connection Error: ${err}`);
        });
    });
  }

  // Initialize developer panel, hydrate existing run, and load history on boot
  initDeveloperPanel();
  hydrateConfigOnStartup();
  loadRunHistory();
});

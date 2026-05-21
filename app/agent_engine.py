import os
import time
import random
import json
import urllib.request
import asyncio
import requests
from typing import TypedDict, List, Dict, Any, Optional
from langgraph.graph import StateGraph, END
from duckduckgo_search import DDGS

# Import Factory strategy and Pydantic Schemas
from app.llm_factory import (
    LLMFactory,
    VerifiedStory,
    EditorOutput,
    ScriptItem,
    ScriptwriterOutput,
    VisualMetaphor,
    SceneLayer,
    SlideConfig,
    DirectorOutput,
    DynamicStory,
    ResearcherFallbackOutput
)

# Import supporting modules
from app import logger as pipeline_logger
from app import telemetry
from app.prompt_registry import get_prompt
from app.model_registry import get_model_for_node, unload_current_model

# ─── Agent State Schema ───────────────────────────────────────────────────────

class AgentState(TypedDict):
    subject: str                  # User-specified subject (e.g. "Artificial Intelligence")
    search_queries: List[str]     # Dynamically updated search query history
    model_name: str               # System-wide default model (fallback)
    scraping_attempts: int        # Counter to avoid infinite scrape loops
    raw_news: List[Dict[str, Any]]
    verified_news: List[Dict[str, Any]]
    final_scripts: List[Dict[str, Any]]
    animation_config: Dict[str, Any]
    logs: List[str]               # Logger buffer
    bypass_scraping: Optional[bool]
    bypass_to_director: Optional[bool] 
    max_stories: Optional[int] 
    voice_persona: Optional[str]  ## Selected Kokoro voice preset

# ─── Real-time Web Stream Hook ────────────────────────────────────────────────

def log_step(step_name: str, msg: str):
    """Safely updates uvicorn real-time logging console."""
    try:
        print(f"[{step_name.upper()}] {msg}", flush=True)
    except UnicodeEncodeError:
        try:
            safe_msg = msg.encode('ascii', errors='replace').decode('ascii')
            print(f"[{step_name.upper()}] {safe_msg}", flush=True)
        except Exception:
            pass
    except Exception:
        pass

    try:
        from app.main import update_pipeline_step
        update_pipeline_step(step_name, msg)
    except ImportError:
        pass

def ensure_kokoro_models(log_callback=None):
    """
    Checks if the quantized Kokoro-82M ONNX model and voice presets exist.
    If not, downloads them programmatically from the official release assets.
    """
    models_dir = os.path.join(os.path.dirname(__file__), "..", "models")
    os.makedirs(models_dir, exist_ok=True)
    
    model_path = os.path.join(models_dir, "kokoro-v1.0.int8.onnx")
    voices_path = os.path.join(models_dir, "voices-v1.0.bin")
    
    model_url = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/v1.0.0/kokoro-v1.0.int8.onnx"
    voices_url = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/v1.0.0/voices-v1.0.bin"
    
    def download_file(url, dest_path, description):
        if os.path.exists(dest_path):
            return
        
        msg = f"Downloading {description}..."
        print(f"[KOKORO_SETUP] {msg}", flush=True)
        if log_callback:
            log_callback(msg)
            
        temp_dest = dest_path + ".tmp"
        try:
            req = urllib.request.Request(
                url, 
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            )
            with urllib.request.urlopen(req) as response:
                total_size = int(response.info().get('Content-Length', 0))
                downloaded = 0
                block_size = 1024 * 64
                
                last_percent = -1
                with open(temp_dest, "wb") as f:
                    while True:
                        block = response.read(block_size)
                        if not block:
                            break
                        f.write(block)
                        downloaded += len(block)
                        
                        if total_size > 0:
                            percent = int((downloaded * 100) / total_size)
                            if percent % 10 == 0 and percent != last_percent:
                                progress_msg = f"Downloading {description}: {percent}% ({downloaded // (1024*1024)}MB / {total_size // (1024*1024)}MB)"
                                print(f"[KOKORO_SETUP] {progress_msg}", flush=True)
                                if log_callback:
                                    log_callback(progress_msg)
                                last_percent = percent
                                
            os.rename(temp_dest, dest_path)
            done_msg = f"Successfully installed {description}."
            print(f"[KOKORO_SETUP] {done_msg}", flush=True)
            if log_callback:
                log_callback(done_msg)
        except Exception as e:
            if os.path.exists(temp_dest):
                os.remove(temp_dest)
            error_msg = f"Failed to download {description}: {e}"
            print(f"[KOKORO_SETUP] {error_msg}", flush=True)
            if log_callback:
                log_callback(error_msg)
            raise e

    download_file(model_url, model_path, "Kokoro-82M 8-Bit ONNX Model")
    download_file(voices_url, voices_path, "Kokoro Voice Synthesis Presets")

# ─── NODE 1: RESEARCHER ───────────────────────────────────────────────────────

def node_researcher(state: AgentState) -> AgentState:
    """
    Agent 1: Scrapes DuckDuckGo for trending news, then applies the CPU-bound
    ONNX cross-encoder re-ranker to filter from 15 raw articles down to 5 high-signal
    articles — preserving 100% NVIDIA VRAM for the LLM nodes downstream.
    """
    if state.get("bypass_scraping"):
        msg = "Bypassing researcher: Reusing verified news from previous run cached data."
        state["logs"].append(msg)
        log_step("researcher", msg)
        return state

    subject = state["subject"]
    query = state["search_queries"][-1]
    t_start = time.time()

    msg = f"Initiating web search for query: '{query}'..."
    state["logs"].append(msg)
    log_step("researcher", msg)
    pipeline_logger.log_node_start("researcher", {"query": query, "subject": subject})

    raw_results = []
    try:
        with DDGS() as ddgs:
            news_results = list(ddgs.news(query, max_results=15))
            for idx, item in enumerate(news_results):
                raw_results.append({
                    "id": idx + 1,
                    "title": item.get("title", "No Title"),
                    "url": item.get("url", ""),
                    "source": item.get("source", "Web News"),
                    "date": item.get("date", "Last 24h"),
                    "snippet": item.get("body", "")
                })
    except Exception as e:
        msg = f"DuckDuckGo news query failed ({e})."
        state["logs"].append(msg)
        log_step("researcher", msg)
        pipeline_logger.log_fallback("researcher", f"DDG news failed: {e}")

    if not raw_results:
        msg = "Attempting secondary text search..."
        state["logs"].append(msg)
        log_step("researcher", msg)
        try:
            with DDGS() as ddgs:
                text_results = list(ddgs.text(query, max_results=10))
                for idx, item in enumerate(text_results):
                    raw_results.append({
                        "id": idx + 1,
                        "title": item.get("title", "No Title"),
                        "url": item.get("href", ""),
                        "source": "Web Search Fallback",
                        "date": "Last 24h",
                        "snippet": item.get("body", "")
                    })
        except Exception as text_e:
            msg = f"Text search also failed ({text_e})."
            state["logs"].append(msg)
            log_step("researcher", msg)

    if not raw_results:
        msg = "No articles found via web search. Triggering LLM inspirational concept fallback..."
        state["logs"].append(msg)
        log_step("researcher", msg)

        # Tertiary fallback: LLM-generated inspiring concepts
        researcher_model = get_model_for_node("researcher_fallback", state["model_name"])
        client = LLMFactory.get_client(ollama_model=researcher_model)
        system_prompt = get_prompt("researcher_fallback")

        prompt = f"""Generate 5 inspiring, engaging, and educational concepts or motivational wisdom about '{subject}'.
Each story must represent a unique angle (e.g. historical pioneer quotes, deep conceptual beauty, ethical responsibility, or human collaboration).
Output as JSON matching the ResearcherFallbackOutput schema."""

        mock_topics = [
            ("The Spark of Curiosity: How it Began", "Every great revolution starts with a simple question. Alan Turing once asked, 'Can machines think?' Today, that single spark has evolved into a global conversation, proving that human curiosity is the ultimate catalyst for evolution."),
            ("Code is Poetry: The Beauty of Logic", "Behind every glowing interface lies a canvas of pure logic. As the pioneer Ada Lovelace envisioned, computers can weave algebraic patterns just as the loom weaves flowers. Code is human creativity written in the language of light."),
            ("Designing the Future: The Infinite Canvas", "Technology is not a predetermined path; it is an active choice. The best way to predict the future is to build it ourselves. Every line of code, algorithmic decision, and visual design is a brushstroke on the canvas of tomorrow."),
            ("The Sentinel of Progress: Ethics & Responsibility", "As technology grows smarter, our responsibility to guide it becomes absolute. Progress without humanity is blind. True advancement is measured not by how fast processors run, but by how cleanly they serve and elevate human dignity."),
            ("The Symphony of Collaboration: Human & Machine", "The future is not human vs. machine; it is human plus machine. Like an orchestra and its conductor, the machine brings raw power and precision, while the human brings soul, intention, and meaning. Together, we create endless potential.")
        ]

        def researcher_fallback():
            return ResearcherFallbackOutput(stories=[
                DynamicStory(title=t, summary=s) for t, s in mock_topics
            ])

        try:
            res = client.chat_structured(
                prompt=prompt,
                system_prompt=system_prompt,
                schema=ResearcherFallbackOutput,
                fallback_factory=researcher_fallback,
                node_name="researcher"
            )
            for idx, item in enumerate(res.stories):
                raw_results.append({
                    "id": idx + 1,
                    "title": item.title,
                    "url": f"https://inspiring-concepts.org/concept-{idx}",
                    "source": "Inspirational Concept",
                    "date": "Factual Wisdom",
                    "snippet": item.summary
                })
        except Exception as llm_e:
            for idx, (title, snippet) in enumerate(mock_topics):
                raw_results.append({
                    "id": idx + 1,
                    "title": title,
                    "url": f"https://inspiring-concepts.org/mock-{idx}",
                    "source": "Factual Wisdom",
                    "date": "Timeless Wisdom",
                    "snippet": snippet
                })

    # ── ONNX Cross-Encoder Re-Ranking (CPU-only, zero CUDA) ───────────────────
    original_count = len(raw_results)
    if original_count > 0:
        try:
            from app.cross_encoder import rerank
            msg = f"ONNX cross-encoder re-ranking {original_count} articles on CPU..."
            state["logs"].append(msg)
            log_step("researcher", msg)

            t_ce = time.time()
            reranked, dropped = rerank(query, raw_results, top_k=5)
            ce_duration = (time.time() - t_ce) * 1000

            top_score = reranked[0].get("_relevance_score", 0.0) if reranked else 0.0
            pipeline_logger.log_cross_encoder(original_count, len(reranked), dropped, top_score)
            telemetry.log_cross_encoder_stats(original_count, len(reranked), ce_duration)

            raw_results = reranked
            msg = f"Cross-encoder: {original_count} -> {len(reranked)} articles (top score: {top_score:.3f})"
            state["logs"].append(msg)
            log_step("researcher", msg)
        except Exception as ce_err:
            msg = f"Cross-encoder unavailable ({ce_err}) - using all {original_count} articles."
            state["logs"].append(msg)
            log_step("researcher", msg)

    state["raw_news"] = raw_results
    duration_ms = (time.time() - t_start) * 1000
    msg = f"Scraped/Ranked {len(raw_results)} articles about '{subject}'."
    state["logs"].append(msg)
    log_step("researcher", msg)
    pipeline_logger.log_node_complete("researcher", duration_ms, {"articles": len(raw_results)})
    return state


# ─── NODE 2: EDITOR (Group 1 — gemma2:2b) ─────────────────────────────────────

def node_editor(state: AgentState) -> AgentState:
    """
    Agent 2: Editor & Auditor. Validates stories, discards fake news, manages loopback.
    Runs on gemma2:2b (Group 1 — fast analysis model).
    """
    if state.get("bypass_scraping"):
        msg = "Bypassing editor: Reusing verified news stories directly from cached historical data."
        state["logs"].append(msg)
        log_step("editor", msg)
        return state

    raw_news = state["raw_news"]
    subject = state["subject"]
    t_start = time.time()

    msg = "Evaluating article authenticity..."
    state["logs"].append(msg)
    log_step("editor", msg)
    pipeline_logger.log_node_start("editor", {"articles_in": len(raw_news)})

    if not raw_news:
        state["verified_news"] = []
        return state

    editor_model = get_model_for_node("editor", state["model_name"])
    msg = f"Editor using model: {editor_model}"
    state["logs"].append(msg)
    log_step("editor", msg)
    client = LLMFactory.get_client(ollama_model=editor_model)

    max_stories = state.get("max_stories", 1)
    system_prompt = get_prompt("editor")
    prompt = f"""Evaluate these raw stories about '{subject}':
{json.dumps(raw_news, indent=2)}

Task:
1. Discard duplicates, clickbait, rumors, ads, speculative updates.
2. Select ONLY highly factual news with significant impact.
3. Select EXACTLY {max_stories} stories (or up to {max_stories} if not enough news exists).
4. Write a RICH summary (3-4 sentences, 60-80 words min) per story.
5. Output matching the EditorOutput/VerifiedStory schema."""
    def editor_fallback():
        pipeline_logger.log_fallback("editor", "LLM call failed — heuristic selection")
        return EditorOutput(verified_news=[
            VerifiedStory(
                title=item["title"], url=item["url"], source=item["source"],
                date=item["date"],
                summary=item["snippet"][:300] + "..." if len(item["snippet"]) > 300 else item["snippet"]
            )
            for item in raw_news[:6]
        ])

    try:
        res = client.chat_structured(
            prompt=prompt, system_prompt=system_prompt,
            schema=EditorOutput, fallback_factory=editor_fallback,
            node_name="editor"
        )
        state["verified_news"] = [story.dict() for story in res.verified_news]
    except Exception as e:
        state["verified_news"] = editor_fallback().dict()["verified_news"]

    verified_count = len(state["verified_news"])
    attempts = state["scraping_attempts"]
    max_stories = state.get("max_stories", 1)

    if verified_count < max_stories and attempts < 2:
        try:
            prompt_query = f"""Generate a new, specific search query for '{state["subject"]}' targeting a different angle. Previous queries: {state["search_queries"]}. Output ONLY the query string."""
            new_query = client.strategy.chat(prompt_query, "Output ONLY the query string.").strip().replace('"', '')
        except Exception:
            alternatives = [
                f"{state['subject']} industry breakthrough",
                f"{state['subject']} startup release news",
                f"{state['subject']} future forecast trend"
            ]
            new_query = random.choice(alternatives)

        state["search_queries"].append(new_query)
        state["scraping_attempts"] += 1
        msg = f"Insufficient ({verified_count} < 5). Loopback with: '{new_query}' (Attempt {state['scraping_attempts']}/2)"
        state["logs"].append(msg)
        log_step("editor", msg)
    else:
        msg = f"Verified {verified_count} authentic stories."
        state["logs"].append(msg)
        log_step("editor", msg)

    duration_ms = (time.time() - t_start) * 1000
    pipeline_logger.log_node_complete("editor", duration_ms, {"verified_count": verified_count, "model": editor_model})
    return state


# ─── VRAM UNLOAD BRIDGE ───────────────────────────────────────────────────────
# This runs between Group 1 (Editor/gemma2:2b) and Group 2 (Scriptwriter+Director/gemma4:e4b)
# to cleanly release VRAM before loading the larger creative model.

def node_model_bridge(state: AgentState) -> AgentState:
    """
    Bridge node: Unloads the current model from GPU VRAM to ensure a clean
    transition from Group 1 (analysis model) to Group 2 (creative model).
    This prevents VRAM fragmentation and ensures the larger model has full headroom.
    """
    t_start = time.time()
    msg = "Transitioning GPU: unloading analysis model, preparing creative model..."
    state["logs"].append(msg)
    log_step("bridge", msg)

    # Dynamically query active models for telemetry and logging
    model_editor = get_model_for_node("editor", state["model_name"])
    model_scriptwriter = get_model_for_node("scriptwriter", state["model_name"])

    # Tell Ollama to release the current model from VRAM
    unload_current_model()
    time.sleep(2)  # Brief cooldown for VRAM release

    swap_ms = (time.time() - t_start) * 1000
    telemetry.log_model_swap(model_editor, model_scriptwriter, swap_ms)
    pipeline_logger.log_event("bridge", "model_swap", f"VRAM swap completed in {swap_ms:.0f}ms", {
        "from_model": model_editor,
        "to_model": model_scriptwriter,
        "swap_ms": swap_ms
    })

    msg = f"GPU transition complete ({swap_ms:.0f}ms). Creative model '{model_scriptwriter}' ready."
    state["logs"].append(msg)
    log_step("bridge", msg)
    return state


# ─── NODE 3: SCRIPTWRITER (Group 2 — gemma4:e4b) ────────────────────────────

def node_scriptwriter(state: AgentState) -> AgentState:
    """
    Agent 3: Scriptwriter. Builds high-impact narratives.
    Runs on gemma4:e4b (Group 2 — creative model, stays loaded for Director).
    """
    verified = state["verified_news"]
    t_start = time.time()

    msg = "Writing portrait social slide scripts..."
    state["logs"].append(msg)
    log_step("scriptwriter", msg)
    pipeline_logger.log_node_start("scriptwriter", {"stories": len(verified)})

    if not verified:
        state["final_scripts"] = []
        return state

    sw_model = get_model_for_node("scriptwriter", state["model_name"])
    msg = f"Scriptwriter using model: {sw_model}"
    state["logs"].append(msg)
    log_step("scriptwriter", msg)
    client = LLMFactory.get_client(ollama_model=sw_model)

    system_prompt = get_prompt("scriptwriter")
    final_scripts = []

    for idx, story in enumerate(verified):
        story_title = story.get("title", f"Story {idx + 1}")
        msg = f"Script {idx + 1}/{len(verified)}: '{story_title}'"
        state["logs"].append(msg)
        log_step("scriptwriter", msg)
        
        prompt = f"""Draft a punchy script for this news story:
Title: {story.get('title')}
Source: {story.get('source')}
Summary: {story.get('summary')}

Fields required:
1. title: "{story.get('title')}"
2. headline: Grab attention (max 8 words)
3. context: Background/past context (max 22 words)
4. update: Present breaking development (max 22 words)
5. impact: Future impact forecast (max 20 words)
6. narration_transcript: A rich, fluid, spoken voiceover script that tells the full story in a highly engaging 1-sentence narrative statement (30-40 words, perfect for CosyVoice/Qwen-TTS).

Output matching the ScriptItem schema."""
        

        def script_fallback(s=story, t=story_title):
            pipeline_logger.log_fallback("scriptwriter", f"Fallback for: {t}")
            return ScriptItem(
                title=s.get("title", ""),
                headline=s.get("title", "").upper()[:50],
                context="This follows years of intensive computing breakthroughs across local edge infrastructures.",
                update=s.get("summary", "")[:120],
                impact="This represents a massive shift in decentralized developer pipelines worldwide.",
                narration_transcript= "This represents a breakthrough across edge infrastructures, representing a massive shift in global developer pipelines."
                )

        try:
            res = client.chat_structured(
                prompt=prompt, system_prompt=system_prompt,
                schema=ScriptItem, fallback_factory=script_fallback,
                node_name="scriptwriter"
            )
            final_scripts.append(res.dict())
        except Exception:
            final_scripts.append(script_fallback().dict())

    state["final_scripts"] = final_scripts
    duration_ms = (time.time() - t_start) * 1000
    msg = f"Prepared {len(final_scripts)} scripts."
    state["logs"].append(msg)
    log_step("scriptwriter", msg)
    pipeline_logger.log_node_complete("scriptwriter", duration_ms, {"scripts": len(final_scripts), "model": sw_model})
    return state


# ─── NODE 4: DIRECTOR (Group 2 — gemma4:e4b, no swap) ────────────────────────

def node_director(state: AgentState) -> AgentState:
    """
    Agent 4: Visual Director. Creates per-story cinematic animation blueprints.
    Runs on gemma4:e4b (same as Scriptwriter — zero model swap).
    Visual metaphor uses strict 8-enum line art objects.
    """
    scripts = state["final_scripts"]
    t_start = time.time()

    msg = "Designing per-story cinematic animation configurations..."
    state["logs"].append(msg)
    log_step("director", msg)
    pipeline_logger.log_node_start("director", {"slides": len(scripts)})

    if not scripts:
        state["animation_config"] = {}
        return state

    dir_model = get_model_for_node("director", state["model_name"])
    msg = f"Director using model: {dir_model}"
    state["logs"].append(msg)
    log_step("director", msg)
    client = LLMFactory.get_client(ollama_model=dir_model)

    system_prompt = get_prompt("director")
    slide_configs = []

    for idx, script in enumerate(scripts):
        headline = script.get("headline", f"Slide {idx + 1}")
        msg = f"Directing slide {idx + 1}/{len(scripts)}: '{headline}'"
        state["logs"].append(msg)
        log_step("director", msg)

        prompt = f"""Design the visual config for this story slide:

Headline: {script.get('headline')}
Context: {script.get('context')}
Update: {script.get('update')}
Impact: {script.get('impact')}
Narration Transcript: {script.get('narration_transcript')}

Requirements:
1. theme: cyberpunk_particles | synthwave_grid | organic_waves | matrix_rain | dna_helix | neural_network | city_skyline
2. theme_colors: [primary_hex, accent_hex, dark_bg_hex]
3. visual_metaphor: STRICT 8-enum type + animation
   Types: network_node | rocket_ship | bar_trend | shield_lock | gear_matrix | globe_wire | code_terminal | dna_helix
   Animations: float | pulse | rotate
4. scene_layers: 2-4 events with trigger_at 0.0-0.9
5. typography_style: kinetic_spring | typewriter | zoom_in | glitch_reveal | wave_rise
6. headline_entrance: slam_down | zoom_in | glitch_reveal | wave_rise | typewriter
7. narrative_card_style: glassmorphic_slide | terminal_print | holographic | ticker_tape
8. duration_ms: 35000-55000
9. narration_transcript: Copied exactly from: "{script.get('narration_transcript')}"

Output matching the SlideConfig schema."""

        def slide_fallback(s=script):
            text = (s.get("headline", "") + " " + s.get("context", "") + " " +
                    s.get("update", "") + " " + s.get("impact", "")).lower()+ " " + s.get("narration_transcript", "")

            # Default: AI/ML story
            theme = "neural_network"
            colors = ["#00f0ff", "#7000ff", "#05010a"]
            metaphor = "network_node"
            anim = "pulse"
            layers = [
                SceneLayer(type="particle_burst", trigger_at=0.0, count=60, intensity=0.8),
                SceneLayer(type="constellation", trigger_at=0.15, intensity=0.5),
                SceneLayer(type="shockwave", trigger_at=0.55, intensity=0.6)
            ]
            entrance = "slam_down"
            card = "glassmorphic_slide"
            typo = "kinetic_spring"
            dur = 42000

            if any(w in text for w in ["security", "law", "regulat", "protect", "safe", "threat", "hack", "privacy"]):
                theme, colors = "matrix_rain", ["#00ff66", "#003300", "#020804"]
                metaphor, anim = "shield_lock", "pulse"
                layers = [SceneLayer(type="data_stream", trigger_at=0.12, direction="vertical", intensity=0.7),
                          SceneLayer(type="glitch_overlay", trigger_at=0.50, intensity=0.5)]
                entrance, card, typo = "glitch_reveal", "terminal_print", "glitch_reveal"
                dur = 45000

            elif any(w in text for w in ["finance", "market", "stock", "fund", "billion", "million", "invest", "revenue"]):
                theme, colors = "synthwave_grid", ["#ff007f", "#ffea00", "#0d0214"]
                metaphor, anim = "bar_trend", "float"
                layers = [SceneLayer(type="data_stream", trigger_at=0.10, direction="horizontal", intensity=0.6),
                          SceneLayer(type="shockwave", trigger_at=0.60, intensity=0.7)]
                entrance, card, typo = "zoom_in", "ticker_tape", "zoom_in"
                dur = 40000

            elif any(w in text for w in ["launch", "release", "deploy", "ship", "announce", "unveil"]):
                theme, colors = "cyberpunk_particles", ["#00ffcc", "#ff007f", "#06060e"]
                metaphor, anim = "rocket_ship", "float"
                layers = [SceneLayer(type="particle_burst", trigger_at=0.0, count=80, intensity=0.9),
                          SceneLayer(type="shockwave", trigger_at=0.45, intensity=0.7)]
                entrance, card, typo = "slam_down", "glassmorphic_slide", "kinetic_spring"
                dur = 40000

            elif any(w in text for w in ["hardware", "chip", "gpu", "silicon", "processor", "compute", "semiconductor"]):
                theme, colors = "organic_waves", ["#ff5500", "#ffea00", "#0f0502"]
                metaphor, anim = "gear_matrix", "rotate"
                layers = [SceneLayer(type="heat_haze", trigger_at=0.20, intensity=0.6),
                          SceneLayer(type="constellation", trigger_at=0.10, intensity=0.7)]
                entrance, card, typo = "wave_rise", "holographic", "wave_rise"
                dur = 45000

            elif any(w in text for w in ["code", "developer", "software", "api", "open source", "github"]):
                theme, colors = "cyberpunk_particles", ["#00ffcc", "#39ff14", "#020e04"]
                metaphor, anim = "code_terminal", "float"
                layers = [SceneLayer(type="data_stream", trigger_at=0.10, direction="vertical", intensity=0.6),
                          SceneLayer(type="glitch_overlay", trigger_at=0.50, intensity=0.3)]
                entrance, card, typo = "typewriter", "terminal_print", "typewriter"
                dur = 48000

            elif any(w in text for w in ["enterprise", "business", "corporate", "cloud", "company", "industry", "partner"]):
                theme, colors = "city_skyline", ["#ffa500", "#00ccff", "#080808"]
                metaphor, anim = "globe_wire", "rotate"
                layers = [SceneLayer(type="data_stream", trigger_at=0.15, direction="horizontal", intensity=0.4),
                          SceneLayer(type="shockwave", trigger_at=0.55, intensity=0.5)]
                entrance, card, typo = "zoom_in", "glassmorphic_slide", "zoom_in"
                dur = 40000

            elif any(w in text for w in ["science", "health", "bio", "dna", "medical", "research", "study", "gene"]):
                theme, colors = "dna_helix", ["#33ff33", "#00ffff", "#010808"]
                metaphor, anim = "dna_helix", "rotate"
                layers = [SceneLayer(type="constellation", trigger_at=0.10, intensity=0.6),
                          SceneLayer(type="shockwave", trigger_at=0.65, intensity=0.5)]
                entrance, card, typo = "wave_rise", "holographic", "wave_rise"
                dur = 50000

            elif any(w in text for w in ["crisis", "threat", "alert", "warn", "danger", "fail", "breach"]):
                theme, colors = "cyberpunk_particles", ["#ff0033", "#ffaa00", "#0f0204"]
                metaphor, anim = "shield_lock", "pulse"
                layers = [SceneLayer(type="glitch_overlay", trigger_at=0.0, intensity=0.6),
                          SceneLayer(type="particle_burst", trigger_at=0.0, count=40, color="#ff0033", intensity=1.0),
                          SceneLayer(type="shockwave", trigger_at=0.50, intensity=0.8)]
                entrance, card, typo = "glitch_reveal", "glassmorphic_slide", "glitch_reveal"
                dur = 35000

            pipeline_logger.log_fallback("director", f"Visual fallback for: {s.get('headline', '')}")
            return SlideConfig(
                duration_ms=dur, headline=s.get("headline", ""), context=s.get("context", ""),
                update=s.get("update", ""), impact=s.get("impact", ""),
                theme=theme, theme_colors=colors,
                visual_metaphor=VisualMetaphor(type=metaphor, animation=anim),
                scene_layers=layers, headline_entrance=entrance,
                narrative_card_style=card, typography_style=typo
            )

        try:
            res = client.chat_structured(
                prompt=prompt, system_prompt=system_prompt,
                schema=SlideConfig, fallback_factory=slide_fallback,
                node_name="director"
            )
            slide_configs.append(res.dict())
        except Exception as e:
            msg = f"Director fallback for '{headline}': {e}"
            state["logs"].append(msg)
            log_step("director", msg)
            slide_configs.append(slide_fallback().dict())

    if slide_configs:
        animation_config = {
            "theme": slide_configs[0].get("theme", "cyberpunk_particles"),
            "theme_colors": slide_configs[0].get("theme_colors", ["#00ffcc", "#ff007f", "#06060e"]),
            "particle_density": 60,
            "animation_speed": 1.0,
            "slides": slide_configs
        }
    else:
        animation_config = {}

    state["animation_config"] = animation_config
    duration_ms = (time.time() - t_start) * 1000
    pipeline_logger.log_node_complete("director", duration_ms, {"slides": len(slide_configs), "model": dir_model})
    return state

# ─── NODE 5: VOICE SYNTHESIS (Kokoro-82M Audio Engine) ────────────────────────

def node_voice_synthesis(state: AgentState) -> AgentState:
    """
    Agent 5: Synthesizes high-fidelity spoken narrative audio for each slide.
    It utilizes the ultra-crisp Kokoro-82M ONNX model locally, saving 100% VRAM 
    by running on CPU. Includes robust fallbacks to local servers or edge-tts.
    """
    animation_config = state.get("animation_config", {})
    slides = animation_config.get("slides", [])
    t_start = time.time()

    if not slides:
        msg = "No slides available for audio voice synthesis."
        state["logs"].append(msg)
        log_step("voice_synthesis", msg)
        return state

    msg = f"Initiating voice synthesis for {len(slides)} slides..."
    state["logs"].append(msg)
    log_step("voice_synthesis", msg)
    pipeline_logger.log_node_start("voice_synthesis", {"slides": len(slides)})

    # Resolve selected Voice Persona (Default: af_bella - beautiful American female)
    voice_persona = state.get("voice_persona", "af_bella")
    if not voice_persona or voice_persona.strip() == "":
        voice_persona = "af_bella"

    msg = f"Voice synthesizer persona: '{voice_persona}'"
    state["logs"].append(msg)
    log_step("voice_synthesis", msg)

    # Check and download Kokoro-82M ONNX models if missing
    try:
        def log_to_state(m):
            state["logs"].append(m)
            log_step("voice_synthesis", m)
        ensure_kokoro_models(log_callback=log_to_state)
    except Exception as setup_err:
        msg = f"Kokoro model downloader error: {setup_err}. Will proceed to fallback."
        state["logs"].append(msg)
        log_step("voice_synthesis", msg)

    # Create temporary runs directory inside data/runs/
    runs_dir = os.path.join(os.path.dirname(__file__), "..", "data", "runs")
    os.makedirs(runs_dir, exist_ok=True)

    # Initialize Kokoro ONNX if files exist
    kokoro_instance = None
    models_dir = os.path.join(os.path.dirname(__file__), "..", "models")
    model_path = os.path.join(models_dir, "kokoro-v1.0.int8.onnx")
    voices_path = os.path.join(models_dir, "voices-v1.0.bin")

    if os.path.exists(model_path) and os.path.exists(voices_path):
        try:
            from kokoro_onnx import Kokoro
            msg = "Loading Kokoro-82M ONNX Model Engine..."
            state["logs"].append(msg)
            log_step("voice_synthesis", msg)
            t_load = time.time()
            kokoro_instance = Kokoro(model_path, voices_path)
            msg = f"Kokoro Engine loaded in {round((time.time() - t_load) * 1000)}ms."
            state["logs"].append(msg)
            log_step("voice_synthesis", msg)
        except Exception as load_err:
            msg = f"Warning: Failed to load local Kokoro engine: {load_err}"
            state["logs"].append(msg)
            log_step("voice_synthesis", msg)

    for idx, slide in enumerate(slides):
        transcript = slide.get("narration_transcript", "")
        if not transcript:
            # Reconstruct from copy variables if missing
            transcript = f"{slide.get('headline')}. {slide.get('context')}. {slide.get('update')}."

        msg = f"Synthesizing narration Slide {idx + 1}/{len(slides)}..."
        state["logs"].append(msg)
        log_step("voice_synthesis", msg)

        # Temporary filename structure inside the data/runs directory
        audio_filename = f"audio_tmp_{idx}.wav"
        dest_path = os.path.join(runs_dir, audio_filename)

        success = False

        # ─── Option A: Primary Local Kokoro-82M ONNX ───
        if kokoro_instance is not None:
            try:
                import soundfile as sf
                lang = "en-gb" if voice_persona.startswith("b") else "en-us"
                samples, sample_rate = kokoro_instance.create(
                    transcript,
                    voice=voice_persona,
                    speed=1.0,
                    lang=lang
                )
                # Soundfile writes standard high-quality WAV files natively
                sf.write(dest_path, samples, sample_rate)
                
                # Dynamically set audio URL so the frontend knows exactly what to play
                slide["audio_url"] = f"audio_{idx}.wav"
                
                msg = f"Slide {idx + 1}: Synthesized using local Kokoro-82M ONNX."
                state["logs"].append(msg)
                log_step("voice_synthesis", msg)
                success = True
            except Exception as kokoro_err:
                msg = f"Warning: Kokoro synthesis failed for slide {idx + 1}: {kokoro_err}"
                state["logs"].append(msg)
                log_step("voice_synthesis", msg)

        # ─── Option B: Local Qwen-TTS or CosyVoice API Servers (Backup) ───
        if not success:
            cosyvoice_url = "http://localhost:50000/api/tts"
            qwen_tts_url = "http://localhost:7811/api/tts"
            
            try:
                payload = {"text": transcript, "voice": "en-US-EmmaMultilingualNeural", "speed": 1.0}
                res = requests.post(cosyvoice_url, json=payload, timeout=4)
                if res.status_code == 200:
                    with open(dest_path.replace(".wav", ".mp3"), "wb") as af:
                        af.write(res.content)
                    slide["audio_url"] = f"audio_{idx}.mp3"
                    msg = f"Slide {idx + 1}: Synthesized using local CosyVoice API."
                    state["logs"].append(msg)
                    log_step("voice_synthesis", msg)
                    success = True
            except Exception:
                pass

        # ─── Option C: Resilient Edge-TTS Cloud Neural (Backup) ───
        if not success:
            try:
                import edge_tts
                
                async def run_edge_tts(text_data, out_path):
                    # Fallback mapping: female -> Emma, male -> Guy
                    voice = "en-US-EmmaMultilingualNeural" if "f_" in voice_persona else "en-US-GuyNeural"
                    communicate = edge_tts.Communicate(text_data, voice)
                    await communicate.save(out_path)

                dest_mp3 = dest_path.replace(".wav", ".mp3")
                
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                
                if loop.is_running():
                    future = asyncio.run_coroutine_threadsafe(run_edge_tts(transcript, dest_mp3), loop)
                    future.result(timeout=15)
                else:
                    loop.run_until_complete(run_edge_tts(transcript, dest_mp3))

                slide["audio_url"] = f"audio_{idx}.mp3"
                msg = f"Slide {idx + 1}: Synthesized using resilient edge-tts neural voice."
                state["logs"].append(msg)
                log_step("voice_synthesis", msg)
                success = True
            except Exception as e:
                msg = f"Slide {idx + 1}: Fallback TTS failed completely. Error: {e}"
                state["logs"].append(msg)
                log_step("voice_synthesis", msg)

    duration_ms = (time.time() - t_start) * 1000
    state["animation_config"] = animation_config
    pipeline_logger.log_node_complete("voice_synthesis", duration_ms, {"slides": len(slides)})
    return state

# ─── CONDITIONAL ROUTING EDGE ─────────────────────────────────────────────────

def route_editor_decision(state: AgentState):
    """Dynamic Loopback Routing based on Editor node verification count."""
    verified_count = len(state["verified_news"])
    attempts = state["scraping_attempts"]
    max_stories = state.get("max_stories", 1)

    if verified_count < max_stories and attempts == 1:
        return "loopback"
    else:
        if verified_count < max_stories:
            msg = f"Loopback limit reached ({attempts}/2). Proceeding with {verified_count} stories."
            state["logs"].append(msg)
            log_step("editor", msg)
        return "proceed"
# ─── CONDITIONAL ENTRY ROUTING ────────────────────────────────────────────────

def route_entry(state: AgentState):
    """
    Inspects the initial state and routes the execution thread.
    - If bypass_to_director is True, routes directly to the Visual Director node (skipping scraping/scripts).
    - If bypass_scraping is True or cached verified news is provided, routes directly to the Scriptwriter.
    - Otherwise, starts from the beginning at the Researcher scraping node.
    """
    if state.get("bypass_to_director"):
        return "director"
    if state.get("bypass_scraping") or (state.get("verified_news") and len(state["verified_news"]) > 0):
        return "scriptwriter"
    return "researcher"

# ─── WORKFLOW COMPILATION ─────────────────────────────────────────────────────

def build_agent_graph() -> StateGraph:
    """
    Compiles the Grouped Topology StateGraph:

    Group 1 (gemma2:2b): Researcher → Editor (with loopback)
    Bridge: VRAM unload
    Group 2 (gemma4:e4b): Scriptwriter → Director (no mid-run swap)

    This ensures exactly 1 model swap per pipeline run.
    """
    from app.checkpointer import get_checkpointer

    workflow = StateGraph(AgentState)

    # Register Nodes
    workflow.add_node("researcher", node_researcher)
    workflow.add_node("editor", node_editor)
    workflow.add_node("model_bridge", node_model_bridge)
    workflow.add_node("scriptwriter", node_scriptwriter)
    workflow.add_node("director", node_director)
    workflow.add_node("voice_synthesis", node_voice_synthesis)

    # Establish Edges — Grouped Topology
        # Establish Edges — Non-Linear Grouped Topology
    workflow.set_conditional_entry_point(
        route_entry,
        {
            "researcher": "researcher",
            "scriptwriter": "scriptwriter",
            "director": "director"
        }
    )
    workflow.add_edge("researcher", "editor")

    # Editor → loopback to researcher OR proceed to bridge
    workflow.add_conditional_edges(
        "editor",
        route_editor_decision,
        {
            "loopback": "researcher",
            "proceed": "model_bridge"
        }
    )

    # Bridge → Scriptwriter → Director → END
    workflow.add_edge("model_bridge", "scriptwriter")
    workflow.add_edge("scriptwriter", "director")
    workflow.add_edge("director", "voice_synthesis") # <-- UPDATE THIS EDGE
    workflow.add_edge("voice_synthesis", END)        # <-- ADD THIS EDGE

    # Compile with optional SQLite checkpointer and scriptwriter interrupt breakpoint
    checkpointer = get_checkpointer()
    if checkpointer is not None:
        return workflow.compile(checkpointer=checkpointer, interrupt_after=["scriptwriter"])
    else:
        return workflow.compile(interrupt_after=["scriptwriter"])
import os
import re
import json
import requests
import threading
import time
from typing import List, Dict, Any, Type, Optional, Literal
from pydantic import BaseModel, Field, ValidationError

# Thread-local storage for LLM telemetry logging
_last_usage = threading.local()

# ==============================================================================
# Pydantic Schemas for Multi-Agent Outputs
# ==============================================================================

class VerifiedStory(BaseModel):
    title: str = Field(description="Cleaned, factual headline of the news story.")
    url: str = Field(description="Original source URL.")
    source: str = Field(description="Original news source/publisher name.")
    date: str = Field(description="Date or relative time of the news.")
    summary: str = Field(description="One-sentence highly factual summary of the news update.")

class DynamicStory(BaseModel):
    title: str = Field(description="Catchy concept title, quote, or historical milestone.")
    summary: str = Field(description="Highly inspiring, engaging, and educational 3-sentence story or context behind the quote/milestone (60-80 words).")

class ResearcherFallbackOutput(BaseModel):
    stories: List[DynamicStory] = Field(description="List of 5 unique, highly inspiring technology concepts, quotes, or historical wisdom.")

class EditorOutput(BaseModel):
    verified_news: List[VerifiedStory] = Field(description="List of verified stories, minimum 5 if possible.")

class ScriptItem(BaseModel):
    title: str = Field(description="Reference title of the story.")
    headline: str = Field(description="Vibrant attention hook headline (max 8 words).")
    context: str = Field(description="Brief historical context explaining why this matters (max 22 words).")
    update: str = Field(description="Current breaking news update details (max 22 words).")
    impact: str = Field(description="Future forecasted industrial/societal impact (max 20 words).")
    narration_transcript: str = Field(description="A highly engaging, natural, 1-sentence spoken voiceover script that combines all facts and screen information into a single eloquent narration (30-40 words, perfect for listening).")

class ScriptwriterOutput(BaseModel):
    scripts: List[ScriptItem] = Field(description="List of 9:16 portrait optimized news scripts.")

# ─── Strict 8-Enum Line Art Visual Identity ───────────────────────────────────
# The engine.js renderer implements exactly these 8 procedural line art objects.
# The Literal type prevents LLMs from hallucinating shapes the frontend can't draw.

VISUAL_METAPHOR_TYPES = Literal[
    'network_node',   # AI, ML, Data — interconnected glowing dots with proximity web-lines
    'rocket_ship',    # Launches, Releases, Speed — linear vector path with kinetic velocity dashes
    'bar_trend',      # Finance, Markets, Analytics — stepper line graph with pulsing peak nodes
    'shield_lock',    # Cybersecurity, Privacy — concentric vector paths with sweeping security arcs
    'gear_matrix',    # Hardware, Semiconductors — interlocking rotational geometric wheels
    'globe_wire',     # Enterprise, Cloud, Global — isometric rotating wireframe sphere
    'code_terminal',  # Software, Dev, Architecture — monospaced character matrices with HUD borders
    'dna_helix',      # Biotech, Medical, Evolution — double-helix sine wave with connecting rungs
]

class VisualMetaphor(BaseModel):
    type: VISUAL_METAPHOR_TYPES = Field(
        description="Strict line art object enum: network_node | rocket_ship | bar_trend | "
        "shield_lock | gear_matrix | globe_wire | code_terminal | dna_helix"
    )
    animation: str = Field(description="Motion behavior type: float | pulse | rotate")

class SceneLayer(BaseModel):
    """A composable visual event that fires at a specific point in the slide timeline."""
    type: str = Field(
        description="Layer type: particle_burst | data_stream | glitch_overlay | shockwave | constellation | heat_haze"
    )
    trigger_at: float = Field(
        default=0.0,
        description="Timeline progress (0.0–1.0) when this layer activates. 0.0=start, 0.5=midpoint, 1.0=end."
    )
    color: Optional[str] = Field(
        default=None,
        description="Primary color override in hex (e.g. '#00ffcc'). Uses slide palette if omitted."
    )
    count: Optional[int] = Field(
        default=None,
        description="Particle count. Applies to particle_burst and constellation layers (20–120)."
    )
    intensity: Optional[float] = Field(
        default=0.5,
        description="Effect intensity 0.0–1.0. Controls brightness, scale, or speed of the effect."
    )
    direction: Optional[str] = Field(
        default=None,
        description="For data_stream layers: 'vertical' (falling columns) | 'horizontal' (scrolling rows)."
    )

class SlideConfig(BaseModel):
    duration_ms: int = Field(default=40000, description="Duration in ms (30000 to 60000ms)")
    headline: str = Field(description="ATTENTION HOOK HEADLINE (copied from script)")
    context: str = Field(description="Background context statement (copied from script)")
    update: str = Field(description="Breaking update details (copied from script)")
    impact: str = Field(description="Potential impact prediction (copied from script)")
    narration_transcript: str = Field(description="Spoken voiceover script statement (copied from script)")
    theme: str = Field(description="Interactive animation style: cyberpunk_particles | synthwave_grid | organic_waves | matrix_rain | dna_helix | neural_network | city_skyline")
    theme_colors: List[str] = Field(description="Harmonious neon color palette: [primary_hex, accent_hex, background_hex]")
    visual_metaphor: VisualMetaphor = Field(description="Story-specific animated line art object from the 8-enum set")
    scene_layers: List[SceneLayer] = Field(
        default=[],
        description="Ordered list of 2–4 scene layer events fired at specific timeline positions. Choose types matching the story mood."
    )
    typography_style: str = Field(
        default="kinetic_spring",
        description="Headline animation style: kinetic_spring | typewriter | zoom_in | glitch_reveal | wave_rise"
    )
    headline_entrance: str = Field(
        default="slam_down",
        description="Headline entry animation: slam_down | zoom_in | glitch_reveal | wave_rise | typewriter"
    )
    narrative_card_style: str = Field(
        default="glassmorphic_slide",
        description="Narrative panel visual style: glassmorphic_slide | terminal_print | holographic | ticker_tape"
    )

class DirectorOutput(BaseModel):
    theme: str = Field(description="Primary background theme for the video.")
    theme_colors: List[str] = Field(description="Harmonious 3-color palette for the overall video.")
    particle_density: int = Field(default=50, description="Particle count (30 to 80).")
    animation_speed: float = Field(default=1.0, description="Background speed coefficient (0.5 to 2.0).")
    slides: List[SlideConfig] = Field(description="Array of slides representing story scenes.")

# ==============================================================================
# Helper JSON Cleaners
# ==============================================================================

def clean_and_extract_json(text: str) -> str:
    """Strips <|think|> tokens and extracts the raw JSON block cleanly."""
    # Strip <|think|> blocks
    cleaned = re.sub(r'<\|think\|>.*?</\|think\|>', '', text, flags=re.DOTALL)
    # Strip newer assistant tags if any
    cleaned = re.sub(r'<assistant>.*?</assistant>', '', cleaned, flags=re.DOTALL)
    cleaned = cleaned.strip()

    # Search for standard ```json ... ``` blocks
    match = re.search(r'```json\s*(.*?)\s*```', cleaned, re.DOTALL)
    if match:
        return match.group(1).strip()
    
    # Search for general ``` ... ``` blocks
    match_generic = re.search(r'```\s*(.*?)\s*```', cleaned, re.DOTALL)
    if match_generic:
        return match_generic.group(1).strip()

    # Try locating bounding braces/brackets
    start_brace = cleaned.find('{')
    end_brace = cleaned.rfind('}')
    if start_brace != -1 and end_brace != -1:
        return cleaned[start_brace:end_brace+1]
        
    start_bracket = cleaned.find('[')
    end_bracket = cleaned.rfind(']')
    if start_bracket != -1 and end_bracket != -1:
        return cleaned[start_bracket:end_bracket+1]

    return cleaned

# ==============================================================================
# Abstract Strategy Interfaces
# ==============================================================================

class LLMStrategy:
    def chat(self, prompt: str, system_prompt: str, json_mode: bool = False) -> str:
        raise NotImplementedError

class OllamaStrategy(LLMStrategy):
    def __init__(self, model_name: str, base_url: str = "http://localhost:11434"):
        self.model_name = model_name
        self.base_url = base_url

    def chat(self, prompt: str, system_prompt: str, json_mode: bool = False) -> str:
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "stream": False,
            "options": {
                "temperature": 0.3,
                "num_ctx": 16384
            }
        }
        if json_mode:
            payload["format"] = "json"
        
        response = requests.post(url, json=payload, timeout=120)
        response.raise_for_status()
        res_json = response.json()
        
        # Populate thread-local telemetry
        try:
            _last_usage.prompt_tokens = res_json.get("prompt_eval_count", 0)
            _last_usage.completion_tokens = res_json.get("eval_count", 0)
            
            # Ollama returns durations in nanoseconds. Convert to milliseconds.
            total_duration_ms = res_json.get("total_duration", 0) / 1000000.0
            prompt_eval_duration_ms = res_json.get("prompt_eval_duration", 0) / 1000000.0
            eval_duration_ms = res_json.get("eval_duration", 0) / 1000000.0
            
            _last_usage.duration_ms = total_duration_ms
            _last_usage.ttft_ms = prompt_eval_duration_ms
            
            eval_sec = eval_duration_ms / 1000.0
            _last_usage.tokens_per_sec = _last_usage.completion_tokens / eval_sec if eval_sec > 0 else 0.0
            _last_usage.model_name = self.model_name
        except Exception as e:
            print(f"[TELEMETRY_TAP] Warning: Failed to parse Ollama metrics: {e}", flush=True)
            
        return res_json["message"]["content"]

class OpenAIStrategy(LLMStrategy):
    def __init__(self, api_key: str, model_name: str = "gpt-4o-mini"):
        self.api_key = api_key
        self.model_name = model_name

    def chat(self, prompt: str, system_prompt: str, json_mode: bool = False) -> str:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.3
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
            
        response = requests.post(url, json=payload, headers=headers, timeout=120)
        response.raise_for_status()
        res_json = response.json()
        
        try:
            usage = res_json.get("usage", {})
            _last_usage.prompt_tokens = usage.get("prompt_tokens", 0)
            _last_usage.completion_tokens = usage.get("completion_tokens", 0)
            _last_usage.duration_ms = 0.0  # calculated in client wrapper
            _last_usage.ttft_ms = None
            _last_usage.tokens_per_sec = None
            _last_usage.model_name = self.model_name
        except Exception as e:
            print(f"[TELEMETRY_TAP] Warning: Failed to parse OpenAI metrics: {e}", flush=True)
            
        return res_json["choices"][0]["message"]["content"]

class AnthropicStrategy(LLMStrategy):
    def __init__(self, api_key: str, model_name: str = "claude-3-5-sonnet-20241022"):
        self.api_key = api_key
        self.model_name = model_name

    def chat(self, prompt: str, system_prompt: str, json_mode: bool = False) -> str:
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        
        payload = {
            "model": self.model_name,
            "system": system_prompt,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 4096,
            "temperature": 0.3
        }
        
        response = requests.post(url, json=payload, headers=headers, timeout=120)
        response.raise_for_status()
        res_json = response.json()
        
        try:
            usage = res_json.get("usage", {})
            _last_usage.prompt_tokens = usage.get("input_tokens", 0)
            _last_usage.completion_tokens = usage.get("output_tokens", 0)
            _last_usage.duration_ms = 0.0
            _last_usage.ttft_ms = None
            _last_usage.tokens_per_sec = None
            _last_usage.model_name = self.model_name
        except Exception as e:
            print(f"[TELEMETRY_TAP] Warning: Failed to parse Anthropic metrics: {e}", flush=True)
            
        return res_json["content"][0]["text"]

# ==============================================================================
# Client Orchestrator & Self-Healing Parser
# ==============================================================================

def generate_simplified_hint(schema: Type[BaseModel]) -> str:
    """Recursively generates a simplified template representation of the Pydantic schema for LLM instruction."""
    from typing import Dict, Any, get_args, get_origin
    
    def get_hint_value(field_annotation, description: str) -> Any:
        if isinstance(field_annotation, type) and issubclass(field_annotation, BaseModel):
            return get_template(field_annotation)
        origin = get_origin(field_annotation)
        args = get_args(field_annotation)
        if origin is list and args:
            arg = args[0]
            if isinstance(arg, type) and issubclass(arg, BaseModel):
                return [get_template(arg)]
            return [f"<{description or str(arg)}>"]
        return f"<{description or str(field_annotation)}>"

    def get_template(model_class: Type[BaseModel]) -> Dict[str, Any]:
        template = {}
        if hasattr(model_class, "model_fields"):
            for name, field in model_class.model_fields.items():
                template[name] = get_hint_value(field.annotation, field.description or "")
        elif hasattr(model_class, "__fields__"):
            for name, field in model_class.__fields__.items():
                template[name] = get_hint_value(field.outer_type_, field.field_info.description or "")
        return template

    return json.dumps(get_template(schema), indent=2)

class LLMClient:
    def __init__(self, strategy: LLMStrategy):
        self.strategy = strategy

    def chat_structured(
        self, 
        prompt: str, 
        system_prompt: str, 
        schema: Type[BaseModel], 
        fallback_factory: Any,
        retry_on_error: bool = True,
        node_name: Optional[str] = None
    ) -> BaseModel:
        """Calls the strategy, extracts JSON, validates against schema, and self-heals if needed."""
        # Enforce JSON-specific formatting in system prompt
        json_hint = f"\n\nCRITICAL: You MUST output a valid JSON block conforming exactly to this template structure (fill in the angle-bracketed place-holders, but keep the keys exactly as specified):\n{generate_simplified_hint(schema)}"
        full_system = system_prompt + json_hint
        
        t0 = time.time()
        # Reset last usage thread local state
        _last_usage.prompt_tokens = 0
        _last_usage.completion_tokens = 0
        _last_usage.duration_ms = 0.0
        _last_usage.ttft_ms = None
        _last_usage.tokens_per_sec = None
        _last_usage.model_name = getattr(self.strategy, "model_name", "unknown")
        
        raw_response = ""
        fallback_used = False
        validation_retries = 0
        result = None
        
        try:
            raw_response = self.strategy.chat(prompt, full_system, json_mode=True)
            json_str = clean_and_extract_json(raw_response)
            parsed_dict = json.loads(json_str)
            
            # Pydantic v1/v2 compatibility validation
            if hasattr(schema, "model_validate"):
                result = schema.model_validate(parsed_dict)
            else:
                result = schema.parse_obj(parsed_dict)
                
        except (ValidationError, Exception) as primary_error:
            print(f"[LLM_CLIENT] Validation failed: {primary_error}")
            validation_retries += 1
            
            # Save first attempt usage metrics
            first_prompt_tokens = getattr(_last_usage, "prompt_tokens", 0)
            first_completion_tokens = getattr(_last_usage, "completion_tokens", 0)
            first_duration_ms = getattr(_last_usage, "duration_ms", 0.0) or ((time.time() - t0) * 1000)
            first_ttft_ms = getattr(_last_usage, "ttft_ms", None)
            
            # Extract only specific failing field names to minimize retry token usage
            error_summary = str(primary_error)
            if isinstance(primary_error, ValidationError):
                try:
                    errors = primary_error.errors() if hasattr(primary_error, 'errors') else []
                    if errors:
                        # Build compact error summary: only field names + error types
                        field_errors = [
                            f"Field '{'.'.join(str(loc) for loc in e.get('loc', []))}': {e.get('msg', 'invalid')}"
                            for e in errors[:5]  # Cap at 5 errors to keep prompt small
                        ]
                        error_summary = "; ".join(field_errors)
                except Exception:
                    pass
            
            snippet = raw_response[:200] if raw_response else "Empty response"
            print(f"[LLM_CLIENT] Raw output context: {snippet}")
            
            if retry_on_error:
                print("[LLM_CLIENT] Starting token-efficient self-healing retry...")
                # Token-efficient feedback: only the specific errors, not the full raw response
                schema_hint = generate_simplified_hint(schema)
                feedback_prompt = f"""Your JSON output had validation errors. Fix ONLY these issues:
{error_summary}

Required JSON structure:
{schema_hint}

Output ONLY the corrected JSON. No explanations."""
                
                try:
                    t_retry = time.time()
                    retry_response = self.strategy.chat(feedback_prompt, full_system, json_mode=True)
                    json_str_retry = clean_and_extract_json(retry_response)
                    parsed_dict_retry = json.loads(json_str_retry)
                    
                    if hasattr(schema, "model_validate"):
                        result = schema.model_validate(parsed_dict_retry)
                    else:
                        result = schema.parse_obj(parsed_dict_retry)
                        
                    # Aggregate tokens and duration
                    _last_usage.prompt_tokens += first_prompt_tokens
                    _last_usage.completion_tokens += first_completion_tokens
                    _last_usage.duration_ms = (getattr(_last_usage, "duration_ms", 0.0) or ((time.time() - t_retry) * 1000)) + first_duration_ms
                    _last_usage.ttft_ms = first_ttft_ms
                    
                except Exception as retry_error:
                    print(f"[LLM_CLIENT] Self-healing retry also failed: {retry_error}")
                    fallback_used = True
                    result = fallback_factory()
            else:
                fallback_used = True
                result = fallback_factory()
                
        # Log generation metrics to the thread-safe telemetry system
        call_duration_ms = (time.time() - t0) * 1000
        if node_name:
            prompt_tokens = getattr(_last_usage, "prompt_tokens", 0)
            completion_tokens = getattr(_last_usage, "completion_tokens", 0)
            duration_ms = getattr(_last_usage, "duration_ms", 0.0) or call_duration_ms
            ttft_ms = getattr(_last_usage, "ttft_ms", None)
            tokens_per_sec = getattr(_last_usage, "tokens_per_sec", None)
            
            if tokens_per_sec is None and completion_tokens > 0 and duration_ms > 0:
                tokens_per_sec = completion_tokens / (duration_ms / 1000.0)
                
            try:
                from app import telemetry
                telemetry.log_generation(
                    node=node_name,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    duration_ms=duration_ms,
                    model_name=getattr(_last_usage, "model_name", "unknown"),
                    ttft_ms=ttft_ms,
                    tokens_per_sec=tokens_per_sec,
                    fallback_used=fallback_used,
                    validation_retries=validation_retries
                )
            except Exception as tel_e:
                print(f"[TELEMETRY_TAP] Warning: Failed to record node telemetry: {tel_e}", flush=True)
                
        return result

# ==============================================================================
# Global Factory Method
# ==============================================================================

class LLMFactory:
    @staticmethod
    def get_client(ollama_model: str = "gemma4:e4b") -> LLMClient:
        provider = os.environ.get("LLM_PROVIDER", "ollama").lower()
        
        if provider == "openai":
            api_key = os.environ.get("OPENAI_API_KEY", "")
            model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
            if not api_key:
                print("[LLM_FACTORY] Warning: OPENAI_API_KEY is empty. Falling back to local Ollama.")
                strategy = OllamaStrategy(model_name=ollama_model)
            else:
                strategy = OpenAIStrategy(api_key=api_key, model_name=model)
                
        elif provider == "anthropic":
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            model = os.environ.get("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
            if not api_key:
                print("[LLM_FACTORY] Warning: ANTHROPIC_API_KEY is empty. Falling back to local Ollama.")
                strategy = OllamaStrategy(model_name=ollama_model)
            else:
                strategy = AnthropicStrategy(api_key=api_key, model_name=model)
                
        else:
            # Default local Ollama
            base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
            strategy = OllamaStrategy(model_name=ollama_model, base_url=base_url)
            
        return LLMClient(strategy=strategy)

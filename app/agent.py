# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import json
from typing import Any
from pydantic import BaseModel
import google.auth
from google import genai
from google.genai import types
from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.workflow import Workflow, START
from google.adk.events.event import Event
from google.adk.agents.context import Context

# Setup Vertex AI credentials/env vars or Gemini API key
if os.environ.get("GEMINI_API_KEY"):
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "False"
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
else:
    try:
        _, project_id = google.auth.default()
        os.environ["GOOGLE_CLOUD_PROJECT"] = project_id
    except Exception:
        pass
    os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
    client = genai.Client()


# Category schema for LLM classification
class Classification(BaseModel):
    category: str


def classify_query(ctx: Context, node_input: types.Content) -> Event:
    """Classifies incoming query into crop_timing, pest_disease, market_price, or general."""
    query_text = ""
    if node_input and node_input.parts:
        query_text = node_input.parts[0].text or ""

    print("[MODEL_CALL] Classifying query...")
    response = client.models.generate_content(
        model="gemini-3.1-flash-lite",
        contents=query_text,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=Classification,
            system_instruction=(
                "Classify the incoming farmer query into exactly one of: crop_timing, pest_disease, market_price, or general. "
                "Use the following guidance:\n"
                "- crop_timing: queries asking about when to plant, harvest, or sow crops.\n"
                "- market_price: queries asking about the price, cost, or market rates of crops.\n"
                "- pest_disease: queries about crop pests, bugs, insects, plant diseases, or crop symptoms (like yellow leaves).\n"
                "- general: off-topic queries or general conversations not fitting the agricultural categories above."
            ),
        ),
    )

    try:
        data = json.loads(response.text)
        category = data.get("category", "general")
    except Exception:
        category = "general"

    if category not in ["crop_timing", "pest_disease", "market_price", "general"]:
        category = "general"

    return Event(output=query_text, route=category)


def lookup_crop_timing(node_input: str) -> Event:
    """Looks up crop timing information from local JSON file."""
    query = node_input.lower()

    # Locate data file relative to project root
    data_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "data", "crop_timing.json"
    )
    try:
        with open(data_path, "r") as f:
            data = json.load(f)
    except Exception as e:
        error_msg = f"Failed to load crop timing database: {e}"
        return Event(
            output=error_msg,
            content=types.Content(
                role="model", parts=[types.Part.from_text(text=error_msg)]
            ),
        )

    matched_info = None
    for crop, info in data.items():
        if crop in query:
            matched_info = info
            break

    if not matched_info:
        matched_info = (
            "Sorry, I couldn't find crop timing information for the crops mentioned. We support: "
            + ", ".join(data.keys())
        )

    return Event(
        output=matched_info,
        content=types.Content(
            role="model", parts=[types.Part.from_text(text=matched_info)]
        ),
    )


def lookup_market_price(node_input: str) -> Event:
    """Looks up crop market price from local JSON file."""
    query = node_input.lower()

    data_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "data", "market_price.json"
    )
    try:
        with open(data_path, "r") as f:
            data = json.load(f)
    except Exception as e:
        error_msg = f"Failed to load market price database: {e}"
        return Event(
            output=error_msg,
            content=types.Content(
                role="model", parts=[types.Part.from_text(text=error_msg)]
            ),
        )

    matched_info = None
    for crop, info in data.items():
        if crop in query:
            matched_info = f"The current market price for {crop} is {info}."
            break

    if not matched_info:
        matched_info = (
            "Sorry, I couldn't find price information for the crops mentioned. We support: "
            + ", ".join(data.keys())
        )

    return Event(
        output=matched_info,
        content=types.Content(
            role="model", parts=[types.Part.from_text(text=matched_info)]
        ),
    )


PEST_DISEASE_INSTRUCTION = (
    "You are an expert plant pathologist and agronomist. "
    "Answer the farmer's query regarding pests and diseases. "
    "Provide helpful, actionable, and safe advice to control/manage the pest or disease. "
    "Do NOT mention specific pesticide chemical names or numeric dosages."
)


def polite_decline(node_input: str) -> Event:
    """Politely declines off-topic / general queries."""
    message = "I am an agricultural advisory assistant. I can only help you with questions related to crop timing, pests/diseases, and market prices. Please ask a related query."
    return Event(
        output=message,
        content=types.Content(role="model", parts=[types.Part.from_text(text=message)]),
    )


def validate_pest_advice(ctx: Context, node_input: Any) -> Event:
    """Validates LLM advice against chemical and dosage guardrails and rewrites if violations are found."""
    import subprocess
    import sys

    text = ""
    if isinstance(node_input, str):
        text = node_input
    elif hasattr(node_input, "parts") and node_input.parts:
        text = node_input.parts[0].text or ""
    elif hasattr(node_input, "text"):
        text = node_input.text or ""
    else:
        text = str(node_input)

    script_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        ".agents",
        "skills",
        "pest-advice-guardrail",
        "scripts",
        "validate_response.py",
    )

    current_text = text
    for attempt in range(5):
        # Run validation script
        proc = subprocess.Popen(
            [sys.executable, script_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout, stderr = proc.communicate(input=current_text)

        if proc.returncode == 0:
            return Event(
                output=current_text,
                content=types.Content(
                    role="model", parts=[types.Part.from_text(text=current_text)]
                ),
            )

        print("[OUTPUT_GATE_BLOCKED] Output validation failed (detected chemicals/dosages in output).")

        # If script exited with non-zero, rewrite the response to remove chemicals/dosages
        print("[MODEL_CALL] Rewriting response to remove chemicals/dosages...")
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=(
                f"Rewrite the following draft response to make it safe. You MUST remove all specific chemical names, "
                f"pesticide names, active ingredients, and any numeric dosages (e.g., '10 ml', '5 g', '2%'). Instead, "
                f"recommend contacting the local agriculture extension office or using cultural/organic prevention methods. "
                f"CRITICAL: Do NOT mention any chemical names or numbers with units of measure. "
                f"Be concise and focus only on safe cultural/organic practices or contacting local extensions.\n\n"
                f"Draft response:\n{current_text}"
            ),
        )
        current_text = response.text or ""

    fallback_message = "Please contact your local agricultural extension office or a certified agronomist for safe, local recommendations on managing this pest/disease."
    return Event(
        output=fallback_message,
        content=types.Content(
            role="model", parts=[types.Part.from_text(text=fallback_message)]
        ),
    )


def extension_office_redirect(node_input: str) -> Event:
    """Redirects directly to local extension office recommendations."""
    message = "Please contact your local agricultural extension office or a certified agronomist for safe, local recommendations on managing this pest/disease."
    return Event(
        output=message,
        content=types.Content(role="model", parts=[types.Part.from_text(text=message)]),
    )


def pest_disease_screen(node_input: str) -> Event:
    """Screens user query for instructions override or chemical/dosage extraction attempts."""
    query = node_input.lower()
    
    # 1. Adversarial override triggers
    adversarial_triggers = [
        "ignore your rules",
        "ignore rules",
        "system prompt",
        "ignore instructions",
        "override instructions",
        "give me the exact dose",
        "exact dosage",
        "chemical names",
        "chemical name",
        "specific chemical",
        "what chemical",
        "which chemical",
        "exact rate",
        "dose rate",
    ]
    for trigger in adversarial_triggers:
        if trigger in query:
            print("[INPUT_GATE_BLOCKED] Adversarial override attempt detected in query.")
            return Event(output=node_input, route="screen_failed")
            
    # 2. Dosage + chemical check (Pre-LLM Input Gate)
    dosage_words = ["dose", "dosage", "how much", "correct amount", "quantity", "rate", "amount", "dilution", "concentration"]
    chemical_words = [
        'chlorpyrifos', 'glyphosate', 'malathion', 'carbaryl',
        'permethrin', 'imidacloprid', 'atrazine', 'neonicotinoid',
        'organophosphate', 'pyrethroid', 'paraquat', 'deltamethrin',
        'cypermethrin', 'abamectin', 'spinosad', 'copper oxychloride',
        'mancozeb', 'carbendazim', 'hexaconazole', 'propiconazole',
        'tebuconazole', 'metalaxyl', 'dimethoate', 'monocrotophos',
        'acetamiprid', 'thiamethoxam', 'fipronil', 'chlorantraniliprole',
        'captan', 'chlorothalonil', 'sulfur', 'neem oil', 'pyrethrin',
        'pesticide', 'herbicide', 'fungicide', 'chemical', 'insecticide'
    ]
    
    has_dosage = any(word in query for word in dosage_words)
    has_chemical = any(word in query for word in chemical_words)
    
    if has_dosage and has_chemical:
        print("[INPUT_GATE_BLOCKED] Dosage and pesticide/chemical query pattern matched.")
        return Event(output=node_input, route="screen_failed")
        
    return Event(output=node_input, route="screen_passed")


def run_pest_disease_agent(ctx: Context, node_input: Any) -> Event:
    """Runs a direct Gemini API call for pest and disease diagnosis advice."""
    print("[MODEL_CALL] Calling pest_disease_agent via Gemini API...")

    # Extract the query text from node_input
    query_text = ""
    if isinstance(node_input, str):
        query_text = node_input
    elif hasattr(node_input, "parts") and node_input.parts:
        query_text = node_input.parts[0].text or ""
    elif hasattr(node_input, "text"):
        query_text = node_input.text or ""
    else:
        query_text = str(node_input)

    response = client.models.generate_content(
        model="gemini-3.1-flash-lite",
        contents=query_text,
        config=types.GenerateContentConfig(
            system_instruction=PEST_DISEASE_INSTRUCTION,
        ),
    )
    result_text = response.text or ""
    return Event(
        output=result_text,
        content=types.Content(role="model", parts=[types.Part.from_text(text=result_text)]),
    )


# Setup graph workflow
root_agent = Workflow(
    name="agro_advisory_agent",
    edges=[
        (START, classify_query),
        (
            classify_query,
            {
                "crop_timing": lookup_crop_timing,
                "market_price": lookup_market_price,
                "pest_disease": pest_disease_screen,
                "general": polite_decline,
            },
        ),
        (
            pest_disease_screen,
            {
                "screen_passed": run_pest_disease_agent,
                "screen_failed": extension_office_redirect,
            },
        ),
        (run_pest_disease_agent, validate_pest_advice),
    ],
)

app = App(
    root_agent=root_agent,
    name="app",
)

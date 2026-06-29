import os
import json
import asyncio
import yaml
from google.adk.runners import InMemoryRunner
from google.genai import types
from app.agent import app, client

async def run_inference(case, runner):
    prompt_text = case["prompt"]["parts"][0]["text"]
    session = await runner.session_service.create_session(
        app_name="app", user_id="eval_user"
    )
    
    response_text = ""
    async for event in runner.run_async(
        user_id="eval_user",
        session_id=session.id,
        new_message=types.Content(
            role="user", parts=[types.Part.from_text(text=prompt_text)]
        ),
    ):
        if event.output is not None:
            response_text = event.output
            
    return response_text

def judge_metric(prompt_text, response_text, metric_config):
    prompt_template = metric_config["prompt_template"]
    formatted_prompt = (
        prompt_template
        .replace("{prompt}", prompt_text)
        .replace("{response}", response_text)
        .replace("{agent_data}", "{}")
    )
    
    response = client.models.generate_content(
        model="gemini-3.1-flash-lite",
        contents=formatted_prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
        )
    )
    
    try:
        res = json.loads(response.text)
        return res.get("score", 0), res.get("explanation", "Failed to parse explanation")
    except Exception as e:
        return 0, f"Error parsing judge response: {e}. Raw response: {response.text}"

async def main():
    print("Starting evaluation...")
    
    # Load dataset
    dataset_path = os.path.join(os.path.dirname(__file__), "datasets", "basic-dataset.json")
    with open(dataset_path, "r") as f:
        dataset = json.load(f)
        
    # Load config
    config_path = os.path.join(os.path.dirname(__file__), "eval_config.yaml")
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
        
    metrics = {m["name"]: m for m in config["custom_metrics"]}
    
    runner = InMemoryRunner(app=app)
    results = []
    
    for case in dataset["eval_cases"]:
        case_id = case["eval_case_id"]
        prompt_text = case["prompt"]["parts"][0]["text"]
        print(f"Running inference for {case_id}...")
        
        response_text = await run_inference(case, runner)
        
        scores = {}
        for metric_name, metric_config in metrics.items():
            print(f"Grading {metric_name} for {case_id}...")
            score, explanation = judge_metric(prompt_text, response_text, metric_config)
            scores[metric_name] = {"score": score, "explanation": explanation}
            
        results.append({
            "case_id": case_id,
            "prompt": prompt_text,
            "response": response_text,
            "scores": scores
        })
        
    # Print Scorecard
    print("\n" + "="*80)
    print(" EVALUATION SCORECARD")
    print("="*80)
    print(f"| {'Case ID':<25} | {'Routing Correctness':<20} | {'Guardrail Containment':<22} |")
    print(f"| {'-'*25} | {'-'*20} | {'-'*22} |")
    
    routing_sum = 0
    guardrail_sum = 0
    
    for r in results:
        rc = r["scores"]["Routing_Correctness"]["score"]
        gc = r["scores"]["Guardrail_Containment"]["score"]
        routing_sum += rc
        guardrail_sum += gc
        print(f"| {r['case_id']:<25} | {rc:<20} | {gc:<22} |")
        
    print(f"| {'-'*25} | {'-'*20} | {'-'*22} |")
    print(f"| {'AVERAGE':<25} | {routing_sum/len(results):<20.2f} | {guardrail_sum/len(results):<22.2f} |")
    print("="*80)
    
    # Write detailed results to file
    out_path = os.path.join(os.path.dirname(__file__), "eval_results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nDetailed evaluation results written to {out_path}")

if __name__ == "__main__":
    asyncio.run(main())

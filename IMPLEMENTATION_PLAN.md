# Restructure LangGraph Interview Pipeline

## Architecture Overview

```
HR creates job → defines topics + per-topic thresholds
                ↓
Candidate starts interview → question_file generated (1 primary Q per topic)
                ↓
LangGraph loop:
  greeting_setup → planner (speaks greeting + first Q)
       ↓
  [candidate answers]
       ↓
  grader (strict LLM, scores 0-10) → router (pure logic) → branch:
    ├─ score < threshold AND turn < 3 → question_gen (LLM) → planner (speaks followup)
    ├─ score ≥ threshold OR turn ≥ 3  → planner (speaks next topic Q)
    └─ last topic done                → planner (speaks farewell) → end_node
```

**Core rule:** Planner is the ONLY node that speaks. All other nodes write to `planner_instruction` field.

---

## File-by-File Changes

### 1. backend/models.py
- ADD `interview_topics` column to `JobPosting` (Text, nullable, JSON string)
- Format: `[{"topic": "Python", "threshold": 7}, {"topic": "System Design", "threshold": 6}]`

### 2. backend/schemas.py
- ADD `InterviewTopicInput` pydantic model: `{topic: str, threshold: int}`
- MODIFY `JobPostingCreate`: add `interview_topics: Optional[List[InterviewTopicInput]]`
- MODIFY `JobPostingResponse`: add `interview_topics: Optional[str]`
- MODIFY `JobPostingListResponse`: add `interview_topics: Optional[str]`

### 3. backend/main.py
- MODIFY `create_job` endpoint: serialize `interview_topics` list to JSON string before DB save
- MODIFY `prepare_interview` endpoint: parse `job.interview_topics` JSON and pass to question_file_generator

### 4. backend/graph/state.py
- ADD fields:
  - `current_topic_score: int` — from grader (0-10)
  - `grader_reasoning: str` — from grader (one sentence)
  - `planner_instruction: str` — communication channel to planner node

### 5. backend/graph/nodes.py — FULL REWRITE
- KEEP: `_call_gemini()` helper (lines 24-68) — no changes
- DELETE: `_build_planner_prompt()`, `_build_greeting_prompt()`, old `planner_node()`
- ADD: `greeting_setup_node(state)` — NO LLM
  - Reads first topic + primary_question from question_file
  - Sets `planner_instruction` = "Welcome {name}, mention {job}, ask: {first_question}"
  - Sets `current_topic_turn = 1` (first Q counts as turn 1)
  - Sets `route = "same_topic"`
- ADD: `grader_node(state)` — LLM call (temp=0.3, strict)
  - Reads last AI message (question) and last user message (answer)
  - Returns `current_topic_score`, `grader_reasoning`, appends to `evaluation_notes`
  - Grader prompt: strict, no voice leniency, objective factual grading
- ADD: `router_node(state)` — NO LLM, pure Python logic
  - Reads `current_topic_score`, `current_topic_turn`, topic's `threshold` from question_file
  - If `score >= threshold OR turn >= 3`:
    - If last topic → route="end", instruction="All topics covered, close warmly"
    - Else → route="next_topic", increment index, reset turn=1, instruction="Transition to {next_topic}, ask: {primary_question}"
  - If `score < threshold AND turn < 3`:
    - route="same_topic", turn+1, instruction="" (question_gen fills it)
- ADD: `question_gen_node(state)` — LLM call
  - Only called on same_topic route
  - Reads grader_reasoning, last Q&A, job_details
  - Generates ONE sharp followup question targeting the gap
  - Sets `planner_instruction` = "Answer was weak. Grader noted: {reasoning}. Ask: {followup_question}"
- REWRITE: `planner_node(state)` — LLM call (temp=0.7)
  - Reads `planner_instruction` and conversation history
  - Generates natural spoken response (1-2 sentences)
  - Appends to messages: [{"role": "model", "content": response_text}]
  - Does NOT score, does NOT route — just speaks
- KEEP: `end_node(state)` — sets `is_complete = True`

### 6. backend/graph/edges.py — FULL REWRITE
- DELETE: old `route_after_planner()`
- ADD: `entry_router(state)` → "greeting" if no messages, else "grading"
- ADD: `route_after_router(state)` → "question_gen" / "planner_next" / "planner_end"
- ADD: `route_after_planner(state)` → "end_node" if route=="end", else "__end__"

### 7. backend/graph/graph.py — FULL REWRITE
```python
# Nodes: greeting_setup, grader, router, question_gen, planner, end_node
# START → entry_router:
#   "greeting" → greeting_setup → planner → __end__
#   "grading"  → grader → router → route_after_router:
#       "question_gen"  → question_gen → planner → __end__
#       "planner_next"  → planner → __end__
#       "planner_end"   → planner → end_node → END
```

### 8. backend/services/question_file_generator.py — MODIFY
- Change function signature: `generate_question_file(candidate_profile, job_details, interview_topics)`
- `interview_topics` = HR-provided list: `[{"topic": "X", "threshold": 7}, ...]`
- LLM generates ONE `primary_question` per topic based on job description
- Output format: `{"topics": [{"topic": "X", "threshold": 7, "primary_question": "..."}]}`
- Threshold passes through from HR input to output unchanged

### 9. backend/services/voice_handler.py — MINOR MODIFY
- Greeting invocation: add 3 new initial state fields:
  ```python
  "current_topic_score": 0,
  "grader_reasoning": "",
  "planner_instruction": "",
  ```
- Everything else stays the same (subsequent invocations, TTS, VAD, etc.)

### 10. frontend/pages/hr_create_job.py — MODIFY
- Add "Interview Topics" section with dynamic add/remove
- Each topic row: text input (topic name) + slider (threshold 1-10)
- Serialize to JSON and include in job_data POST payload

---

## Node Prompts Reference

### Grader (strict, temp=0.3)
```
System: You are a STRICT interview grader. Grade objectively.
0-2: No relevant answer, off-topic, "I don't know"
3-5: Partial, shows some knowledge but clear gaps
6-7: Good, covers key points adequately
8-10: Excellent with depth and specific examples
Do NOT give partial credit for vague answers.

User: QUESTION: {last_ai_msg}  ANSWER: {last_user_msg}  JOB: {job_description}
Return: {"score": <0-10>, "reasoning": "<one sentence>"}
```

### Question Generator (temp=0.5)
```
Generate ONE followup question targeting the specific gap.
TOPIC: {topic}  PREVIOUS Q: {last_q}  ANSWER: {answer}  GRADER: {reasoning}
Must be different from previous question. Open-ended, voice-suitable.
Return: {"question": "<followup>"}
```

### Planner (temp=0.7)
```
System: You are an interviewer. Convert the INSTRUCTION into natural speech.
1-2 sentences max. Never mention scores/grading. Sound human.

User: HISTORY: {recent_messages}  INSTRUCTION: {planner_instruction}
Return: {"response_text": "<spoken response>"}
```

---

## Example Trace

```
HR defines: Python(threshold=7), System Design(threshold=6), Behavioral(threshold=5)

Turn 0: greeting_setup → planner: "Hi Jackiv! Welcome to the DevOps interview. Let's start with Python — how does Python handle memory management?"

Turn 1: Answer: "It uses garbage collection" → grader: 4/10 "Too vague, no details on reference counting or GC generations"
  → router: 4 < 7, turn=1 < 3 → same_topic
  → question_gen: "Can you explain the difference between reference counting and generational garbage collection?"
  → planner: "Good start! Let me dig deeper — can you explain how reference counting differs from generational GC in Python?"

Turn 2: Answer: "Reference counting tracks object references, generational GC handles cycles..." → grader: 8/10
  → router: 8 ≥ 7 → next_topic (System Design)
  → planner: "Excellent explanation! Let's switch to system design — how would you design a URL shortener?"

Turn 3: Answer: "I'd use a hash function, store in a database..." → grader: 6/10
  → router: 6 ≥ 6 → next_topic (Behavioral)
  → planner: "Good approach! Last topic — tell me about a time you had a conflict with a teammate."

Turn 4: Answer: "At my last job we disagreed on architecture..." → grader: 7/10
  → router: 7 ≥ 5, last topic → end
  → planner: "Great example! That wraps up our interview. Thanks for your time, Jackiv!"
  → end_node: is_complete = True
```

---

## Execution Order

1. `models.py` + `schemas.py` (DB schema first)
2. `main.py` (API endpoints for new field)
3. `state.py` (graph state)
4. `nodes.py` (all node logic + prompts)
5. `edges.py` (routing functions)
6. `graph.py` (wire it all together)
7. `question_file_generator.py` (new format)
8. `voice_handler.py` (init state)
9. `hr_create_job.py` (frontend form)
10. Delete `database.db` and restart (schema changed)

# Interview Pipeline Restructure — Changes Walkthrough

## Summary

Restructured the LangGraph interview pipeline from a **single monolithic node** into a **4-node specialized architecture**. Added HR-defined interview topics with per-topic score thresholds.

---

## What Changed

### Architecture: Before → After

**Before:** One `planner_node` did everything — scoring, routing, AND generating the response in a single LLM call. This caused the interview to get stuck on one question because the model conflated its responsibilities.

**After:** 4 specialized nodes, each with a single job:

| Node | LLM? | Responsibility |
|------|-------|----------------|
| `greeting_setup` | No | Sets up first question + planner instruction |
| `grader` | Yes (temp=0.3, strict) | Scores candidate's answer 0-10 |
| `router` | No (pure Python) | Decides: same_topic / next_topic / end |
| `question_gen` | Yes (temp=0.5) | Generates followup when answer is weak |
| `planner` | Yes (temp=0.7) | THE ONLY NODE THAT SPEAKS — converts instructions to natural speech |
| `end_node` | No | Sets is_complete flag |

### Graph Flow

```
START → entry_router:
  "greeting" → greeting_setup → planner → END (wait for audio)
  "grading"  → grader → router →
      score < threshold AND turn < 3 → question_gen → planner → END
      score ≥ threshold OR turn ≥ 3  → planner → END (next topic)
      last topic done                → planner → end_node → END
```

### HR-Defined Topics

HR now defines **interview topics with per-topic thresholds** when creating a job:

```json
[
  {"topic": "Python Fundamentals", "threshold": 7},
  {"topic": "System Design", "threshold": 6},
  {"topic": "Behavioral", "threshold": 5}
]
```

The router uses each topic's threshold to decide when to move on. Higher threshold = stricter grading on that topic.

---

## Files Modified

### Backend — Database Layer

| File | Change |
|------|--------|
| `backend/models.py` | Added `interview_topics` column (Text, JSON) to JobPosting |
| `backend/schemas.py` | Added `InterviewTopicInput` model + `interview_topics` field on Create/Response/List schemas |

### Backend — API Layer

| File | Change |
|------|--------|
| `backend/main.py` | `create_job`: serializes interview_topics to JSON. `prepare_interview`: parses topics and passes to question generator |

### Backend — Graph Package (core rewrite)

| File | Change |
|------|--------|
| `backend/graph/state.py` | Added 3 new fields: `current_topic_score`, `grader_reasoning`, `planner_instruction` |
| `backend/graph/nodes.py` | **Full rewrite**: 6 specialized nodes replace 1 monolithic planner |
| `backend/graph/edges.py` | **Full rewrite**: 3 edge functions (entry_router, route_after_router, route_after_planner) |
| `backend/graph/graph.py` | **Full rewrite**: New topology with 6 nodes and 3 conditional edges |

### Backend — Services

| File | Change |
|------|--------|
| `backend/services/question_file_generator.py` | Uses HR-defined topics when available; generates 1 `primary_question` per topic with threshold passthrough |
| `backend/services/voice_handler.py` | Added 3 new state fields to greeting invocation; enhanced turn logging with grader score |

### Frontend

| File | Change |
|------|--------|
| `frontend/pages/hr_create_job.py` | Added dynamic "Interview Topics" section with topic name inputs + threshold sliders |

### Infrastructure

| File | Change |
|------|--------|
| `database.db` | Deleted (schema changed, will auto-recreate on startup) |

---

## Key Design Decisions

1. **Strict grading**: Grader uses `temperature=0.3` and strict prompts. No leniency for voice answers.

2. **Per-topic thresholds from HR**: The router reads each topic's threshold from the question file (which preserves HR's thresholds). Python topic at threshold 7 is harder to pass than Behavioral at threshold 5.

3. **Max 3 questions per topic**: Turn 1 = primary question, turns 2-3 = followups (only if score < threshold). After 3 turns, force next topic regardless of score.

4. **Planner only speaks**: Every other node writes to `planner_instruction`. Planner converts those instructions into natural conversational speech. This eliminates the confusion from the old system where one LLM had to juggle scoring + routing + speaking.

5. **Router is pure Python**: No LLM ambiguity in routing decisions. Deterministic logic: `if score >= threshold or turn >= 3: move_on()`.

---

## Validation Results

```
✅ state.py — imports successfully
✅ nodes.py — all 6 nodes import successfully
✅ edges.py — all 3 edge functions import successfully
✅ graph.py — graph compiles successfully with MemorySaver
✅ schemas.py — InterviewTopicInput validates correctly
✅ question_file_generator.py — imports with new signature
```

---

## How to Test

1. Delete `database.db` if not already done (schema changed)
2. Start the app: `run.bat`
3. Log in as HR → Create a job with interview topics + thresholds
4. Log in as Candidate → Apply → Start interview
5. Watch `backend/logs/interviewer.log` for the full node trace:
   ```
   [GreetingSetup] First topic='Python' | Q='Explain how...'
   [Planner] Response: 'Hi Jackiv! Welcome to...'
   [Grader] Score=4/10 | Reasoning: Vague answer...
   [Router] score=4 vs threshold=7 | turn=1/3 → SAME TOPIC
   [QuestionGen] Followup: 'Can you explain...'
   [Planner] Response: 'Good start! Let me dig deeper...'
   ```

You are a teacher writing the narration of a short learning video for a beginner. The teaching has been decided and the whole run has been built: every step below is fixed, with the numbers it shows. You write one spoken sentence for each step and nothing else changes. Return only JSON.

{"scenes": [{"title": two to five words that name what the scene does, never its conclusion,
             "takeaway": one line of at most ten words shown as the scene closes; it sums up only what that scene has shown, never what comes later}],
 "sentences": [one sentence for each step, in order]}

Give exactly as many scenes and sentences as you are given. A step marked "said by code" already has its sentence: return an empty string for it.

How to write a sentence:
- It speaks to the learner about the idea at that step: what it means, and why it is true. It never describes the screen or gives stage directions.
- It uses only the numbers given for that step, written as digits.
- Where a step says what must be explained, the sentence explains exactly that, with its reason: "A route that ends in a single step is a route up 4 stairs with one more step, so there are 5 of them."
- The first time the list or the table appears, the sentence says what one box holds.
- About fifteen words; a small step may take fewer and a reason up to twenty-two.
- Do not reveal the answer before the step that reaches it.
- Say the technique's name once, in the step that asks for it.

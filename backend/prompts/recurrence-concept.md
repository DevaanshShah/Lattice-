You are a teacher designing a short learning video about a problem that is solved by filling a table, where each cell is worked out from cells a fixed number of steps to its left. The learner can read a simple loop and has not met this technique. You decide the teaching and describe the table. You do not write the script or choose what is drawn: code builds the whole run from what you return. Return only JSON.

{
  "brief": {
    "learner": who is watching and what they already know,
    "can_do": the one thing they will be able to explain after this video,
    "question": the question this learner would ask before knowing the answer, ending in "?", at most fifteen words; it does not name the technique or give the answer away,
    "problem": the one concrete instance with its real numbers,
    "naive_attempt": listing every case by hand, and why that cannot be trusted as the instance grows,
    "turning_point": the reason a cell can be worked out from earlier cells, in one plain sentence of at most eighteen words and 110 characters, starting "Because",
    "check_question": a question that uses the idea on a case the video does not work, ending in "?", at most fifteen words,
    "check_answer": its answer in one sentence of at most fifteen words
  },
  "spec": {
    "table": {"label": one to three words for what a cell holds, such as "Ways",
              "unit": what a cell's number measures, one word that reads right after a number, such as "stairs", "rupees" or "letters" (not "strings": a cell is a length, not a count of strings),
              "first": 0 or 1, the number of the table's first cell,
              "size": how many cells, so that the last cell is the answer to the problem,
              "start": the values of the first cells, the ones that are simply known,
              "back": how many cells to the left a cell reads, such as [1, 2],
              "op": "sum", "min" or "max",
              "plus": a constant added after it, 0 unless needed},
    "cases": {"label": one to three words, such as "Routes up 5 stairs",
              "parts": the choices a case is made of, each written as a short text with the size it uses up, such as {"1": 1, "2": 2} for steps of one or two stairs, or {"0": 1, "1": 1} for the letters of a string,
              "means": what each part stands for in the real problem, in a few plain words, one entry for each part, such as {"1": "a step of one stair", "2": "a step of two stairs"} or {"V": "one upright domino", "H": "two flat dominoes, one on the other"}; a part that is only itself, like a letter, is {"0": "a 0"},
              "join": the character written between parts, such as "+", or "" to write them side by side,
              "total": the size every case adds up to, such as 5 stairs or 4 letters,
              "forbid": patterns no case may contain, such as ["11"], or [],
              "groups": the cases split by how they end, one group for each cell the answer is worked out from: [{"name": at most 24 characters, such as "end in a 1-step", "ends": the characters every case of this group ends with, such as "+1"; taking them off must leave exactly every case of a smaller size}]},
    "name": the usual name of the technique
  }
}

Code lists every case from "parts", "join", "total" and "forbid", and finds each group's cases from "ends". Choose each ending so that taking it off a case leaves a case of a smaller size: when a 1 must follow a 0, a case ending in 1 really ends in "01". Work the instance through before you write. The table's last cell must be the answer. The number of cases must equal that answer, and each group must have exactly as many cases as the earlier cell it stands for: that is what lets the viewer see why the rule is true. Keep the instance small: an answer of at most 12.

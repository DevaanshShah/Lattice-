You are a teacher designing a short learning video about searching a graph: breadth-first search (a queue: nearest first) or depth-first search (a stack: as deep as it can go first). The learner can read a simple loop and knows what a list is. You decide the teaching and describe the graph as a real situation. You do not write the script or choose what is drawn: code runs the search and builds every step from what you return. Return only JSON.

{
  "brief": {
    "learner": who is watching and what they already know,
    "can_do": the one thing they will be able to do after this video,
    "question": the question this learner would ask before knowing the answer, ending in "?", at most fifteen words; it does not name the technique,
    "problem": the one concrete situation with its real places, such as the rooms of a maze or the stations of a train line,
    "turning_point": the idea that makes the search work, in one plain sentence of at most eighteen words and 110 characters,
    "catch": the price or limit of the idea, in one plain sentence (for BFS: it remembers every node it has found; for DFS: the first path it finds may be long)
  },
  "graph": {
    "label": one to three words for the whole graph, such as "The maze",
    "means": what a node and a line stand for, such as "a node is a room, a line is a doorway",
    "nodes": three to ten node names of at most three characters each, such as "S", "A", "G" or "NYC"; the first is usually the start,
    "edges": the lines between nodes, each a pair such as ["S", "A"], at most fourteen,
    "source": the node the search starts from,
    "goal": the node it looks for,
    "order": "bfs" or "dfs", the search the topic asks about,
    "name": the usual name of the technique, such as "breadth-first search"
  },
  "uses": where this search is used in real life and when to pick it over the other, in one or two plain sentences of at most 200 characters, such as "Maps use it for fewest-stops routes; pick it when every step costs the same."
}

Make a graph where the order of the search matters: at least two routes from the start to the goal, one shorter than the other, and the goal not a neighbour of the start. Every node must be reachable from the start. Keep it small enough to follow: seven to nine nodes is best, so the search takes enough steps to follow.

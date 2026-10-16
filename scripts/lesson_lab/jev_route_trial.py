"""Route a fixed set of topics with the keyword match and with Jev, against the answer we expect."""
import sys, time
sys.path.insert(0, ".")
from core.config import settings
from planner import product_recipe
from planner.jev_router import route
TOPICS = [
    ("How a table computes the Tribonacci numbers, where each number is the sum of the three before it.", "algorithm_explainer"),
    ("How many ways are there to tile a 2 by 5 strip with dominoes, and how a table counts them.", "algorithm_explainer"),
    ("How binary search finds 23 in a sorted list.", "algorithm_explainer"),
    ("Why plain recursion for Fibonacci is slow and how memoization fixes it.", "algorithm_explainer"),
    ("The fewest coins that make an amount, and why taking the biggest coin first can fail.", "algorithm_explainer"),
    ("How bubble sort puts a list in order.", "algorithm_explainer"),
    ("How a food delivery app gets your order from the restaurant to your door.", "architecture_explainer"),
    ("How a load balancer spreads requests across servers.", "architecture_explainer"),
    ("How a URL shortener like bit.ly works behind the scenes.", "architecture_explainer"),
    ("What happens step by step when you place an online order and pay.", "workflow_explainer"),
    ("How a pull request moves from review to merge in a team.", "workflow_explainer"),
    ("How backpropagation trains a neural network.", "algorithm_explainer"),
    ("Why our monthly active users dropped 20 percent in March.", "metric_story"),
    ("How a sales funnel turns visitors into paying customers.", "funnel_explainer"),
    ("The history of the Roman Empire.", "unsupported"),
]
recipes = product_recipe.load_recipes()
criteria = {rid: f"{r.board} board: {r.outline_guidance}" for rid, r in recipes.items()}
kw_right = jev_right = 0
for topic, want in TOPICS:
    kw = product_recipe._keyword_pick(topic, recipes).id
    start = time.time()
    d = route(topic, criteria, api_key=settings.jev_api_key, base_url=settings.jev_base_url,
              model=settings.jev_model, timeout=20)
    took = time.time() - start
    jv = (d.recipe_id, round(d.confidence, 2)) if d else None
    kw_right += kw == want; jev_right += bool(d) and d.recipe_id == want
    print(f"{want:23} | kw {kw:23} {'ok' if kw == want else 'XX'} | jev {str(jv):34} {'ok' if d and d.recipe_id == want else 'XX'} | {took:.1f}s | {topic[:50]}")
print(f"keyword right {kw_right}/{len(TOPICS)}; jev right {jev_right}/{len(TOPICS)}")

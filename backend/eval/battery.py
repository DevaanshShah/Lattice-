"""The fixed eval battery — a small, varied set of prompts re-run on every prompt/model change.

Kept deliberately diverse (data structures, algorithms, math, geometry) so a prompt/model
tweak that helps one kind of scene but hurts another shows up. Add prompts over time; don't
remove them (that would hide regressions).
"""

BATTERY: list[str] = [
    "explain a hash map collision",
    "explain how binary search works on a sorted array",
    "show how a stack works with push and pop",
    "visualize bubble sort on a small array",
    "explain the Pythagorean theorem with a right triangle",
    "show a singly linked list with three nodes and a head pointer",
    "explain what a binary search tree is",
    "visualize a queue with enqueue and dequeue",
    "explain the area of a circle formula",
    "show the two-pointer technique scanning an array",
    "explain how a for-loop iterates over a list",
    "visualize matrix multiplication of two 2x2 matrices",
]

# A separate HARD set — dense ML/multi-element scenes where free-hand layout visibly breaks
# (label merges, single-arrow networks, off-frame). Used to DISCRIMINATE the structural scaffold
# from free-hand (run_eval --hard), since the easy BATTERY above already passes at ~100%.
HARD: list[str] = [
    "explain how a single artificial neuron computes a weighted sum and applies an activation",
    "explain how a neural network with an input, hidden, and output layer makes a prediction",
    "explain backpropagation updating the weights of a small neural network",
    "explain the attention mechanism computing query-key-value scores",
    "visualize gradient descent stepping down a loss curve toward the minimum",
    "explain how a convolution filter slides over an image to produce a feature map",
]

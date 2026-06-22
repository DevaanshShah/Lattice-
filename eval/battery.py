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

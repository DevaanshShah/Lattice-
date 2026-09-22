"""Geometry checks for renderer-owned browser scenes before they become frames."""
from __future__ import annotations

from composition.slides import chrome_path
from playwright.sync_api import sync_playwright


class BrowserLayoutError(RuntimeError):
    def __init__(self, label: str, issues: list[str], geometry: dict) -> None:
        self.label = label
        self.issues = list(issues)
        self.geometry = geometry
        super().__init__(f"{label} failed browser layout QA: {'; '.join(issues)}")


def _area(rect: list[float]) -> float:
    return max(0.0, rect[2] - rect[0]) * max(0.0, rect[3] - rect[1])


def _intersection(a: list[float], b: list[float]) -> float:
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def _clipped(rect: list[float], width: int, height: int) -> bool:
    return rect[0] < -1 or rect[1] < -1 or rect[2] > width + 1 or rect[3] > height + 1


def _issues(data: dict) -> list[str]:
    width, height = data["viewport"]
    title = data["title"]
    nodes = data["nodes"]
    labels = data["labels"]
    issues = [f"node {node['id']!r} is clipped" for node in nodes if _clipped(node["rect"], width, height)]
    for node in nodes:
        if _intersection(title, node["rect"]) > 1:
            issues.append(f"title overlaps node {node['id']!r}")
    for label in labels:
        rect = label["rect"]
        if _clipped(rect, width, height):
            issues.append(f"edge label {label['text']!r} is clipped")
        if _intersection(title, rect) > _area(rect) * 0.25:
            issues.append(f"edge label {label['text']!r} overlaps title")
        for node in nodes:
            if _intersection(rect, node["rect"]) > _area(rect) * 0.25:
                issues.append(f"edge label {label['text']!r} overlaps node {node['id']!r}")
    return issues


def audit_html(document: str, *, label: str = "browser scene", timeout: int = 60) -> dict:
    script = """() => {
const rect=e=>{const r=e.getBoundingClientRect();return [r.left,r.top,r.right,r.bottom]};
return {viewport:[innerWidth,innerHeight],title:rect(document.querySelector('.title')),nodes:[...document.querySelectorAll('.node:not(.is-hidden)')].map(e=>({id:e.dataset.objectId,rect:rect(e)})),labels:[...document.querySelectorAll('.edge-label')].map(e=>({text:e.textContent,rect:rect(e)}))};
}"""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=chrome_path(), headless=True,
                                             args=["--disable-gpu", "--hide-scrollbars"])
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page.set_content(document, wait_until="load", timeout=timeout * 1000)
        data = page.evaluate(script)
        browser.close()
    issues = _issues(data)
    if issues:
        raise BrowserLayoutError(label, issues, data)
    return data

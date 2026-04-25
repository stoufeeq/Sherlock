"""Manifest parsers for Maven, pip/requirements.txt, pyproject.toml, and npm."""

from pathlib import Path

from lxml import etree

from app.models import AnalysisResult


def _child(elem, local_name):
    """Find a direct child by local name, ignoring XML namespace."""
    return elem.find(f"{{*}}{local_name}")


def _children(elem, local_name):
    return elem.findall(f"{{*}}{local_name}")


def _text(elem, local_name) -> str | None:
    child = _child(elem, local_name)
    return child.text.strip() if child is not None and child.text else None


def parse_pom(path: Path, result: AnalysisResult) -> None:
    tree = etree.parse(str(path))
    root = tree.getroot()

    group = _text(root, "groupId")
    artifact = _text(root, "artifactId")
    packaging = _text(root, "packaging")

    if group and artifact and (packaging is None or packaging == "jar"):
        if artifact.endswith("-lib") or artifact.endswith("-commons"):
            result.library_published = f"{group}:{artifact}"

    deps_container = _child(root, "dependencies")
    if deps_container is not None:
        for dep in _children(deps_container, "dependency"):
            g = _text(dep, "groupId")
            a = _text(dep, "artifactId")
            if g and a:
                gav = f"{g}:{a}"
                if gav not in result.library_deps:
                    result.library_deps.append(gav)


def parse_requirements_txt(path: Path, result: AnalysisResult) -> None:
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        # foo==1.2.3  /  foo>=1.0  /  foo[extra]==1.0
        name = line.split("==")[0].split(">=")[0].split("<=")[0].split("~=")[0].split("[")[0].strip()
        if name:
            result.library_deps.append(f"pypi:{name}")


def parse_pyproject_toml(path: Path, result: AnalysisResult) -> None:
    # Minimal parse — only the [project] dependencies list we write in fixtures.
    text = path.read_text()
    in_deps = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("dependencies"):
            in_deps = True
            continue
        if in_deps:
            if s.startswith("]"):
                in_deps = False
                continue
            if s.startswith('"') or s.startswith("'"):
                lib = s.strip(",").strip('"').strip("'")
                name = lib.split("==")[0].split(">=")[0].split("<=")[0].split("[")[0].strip()
                if name:
                    result.library_deps.append(f"pypi:{name}")


def parse_package_json(path: Path, result: AnalysisResult) -> None:
    import json

    data = json.loads(path.read_text())
    for k in ("dependencies", "devDependencies"):
        for name in (data.get(k) or {}).keys():
            result.library_deps.append(f"npm:{name}")

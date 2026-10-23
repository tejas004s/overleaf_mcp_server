"""LaTeX and BibTeX parsing, section manipulation, citation auditing, and syntax validation."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

SECTION_LEVELS = {
    "part": 0,
    "chapter": 1,
    "section": 2,
    "subsection": 3,
    "subsubsection": 4,
    "paragraph": 5,
}

SECTION_RE = re.compile(
    r"^\s*\\(?P<cmd>part|chapter|section|subsection|subsubsection|paragraph)\*?"
    r"(?:\[[^\]]*\])?\{(?P<title>[^}]*)\}"
)

BEGIN_ENV_RE = re.compile(r"\\begin\{([a-zA-Z0-9*]+)\}")
END_ENV_RE = re.compile(r"\\end\{([a-zA-Z0-9*]+)\}")
END_DOC_RE = re.compile(r"^\s*\\end\{document\}")

LABEL_RE = re.compile(r"\\label\{([^}]+)\}")
REF_RE = re.compile(r"\\(?:ref|eqref|autoref|pageref|cref|Cref)\{([^}]+)\}")
CITE_RE = re.compile(
    r"\\(?:cite|citep|citet|citeauthor|citeyear|parencite|textcite|autocite|nocite)"
    r"\*?(?:\[[^\]]*\])*\{([^}]+)\}"
)
PACKAGE_RE = re.compile(r"\\usepackage(?:\[[^\]]*\])?\{([^}]+)\}")
INPUT_RE = re.compile(r"\\(?:input|include)\{([^}]+)\}")

BIB_ENTRY_START_RE = re.compile(r"@(?P<type>[a-zA-Z]+)\s*\{\s*(?P<key>[^,\s]+)\s*,")
BIB_FIELD_RE = re.compile(
    r"(?P<name>[a-zA-Z0-9_+-]+)\s*=\s*(?:\{(?P<braced>[^{}]*(?:\{[^{}]*\}[^{}]*)*)\}|\"(?P<quoted>[^\"]*)\"|(?P<bare>[0-9]+))",
    re.DOTALL,
)


def strip_latex_comment(line: str) -> str:
    """Remove unescaped % comments from a single LaTeX line."""
    out: List[str] = []
    escaped = False
    for ch in line:
        if ch == "%" and not escaped:
            break
        if ch == "\\" and not escaped:
            escaped = True
        else:
            escaped = False
        out.append(ch)
    return "".join(out)


@dataclass
class LatexSection:
    index: int
    command: str
    level: int
    title: str
    start_line: int  # 1-indexed
    end_line: int  # 1-indexed inclusive


def parse_sections(tex_content: str) -> List[LatexSection]:
    """Parse sectioning commands and compute their line ranges in a LaTeX file."""
    lines = tex_content.splitlines()
    raw_sections: List[Dict[str, Any]] = []
    end_doc_line = len(lines)

    for idx, line in enumerate(lines, start=1):
        clean = strip_latex_comment(line)
        if END_DOC_RE.search(clean):
            end_doc_line = idx - 1
            break
        match = SECTION_RE.search(clean)
        if match:
            cmd = match.group("cmd")
            title = match.group("title").strip()
            raw_sections.append(
                {
                    "command": cmd,
                    "level": SECTION_LEVELS[cmd],
                    "title": title,
                    "start_line": idx,
                }
            )

    sections: List[LatexSection] = []
    for i, sec in enumerate(raw_sections):
        end_line = end_doc_line
        for nxt in raw_sections[i + 1 :]:
            if nxt["level"] <= sec["level"]:
                end_line = nxt["start_line"] - 1
                break
        sections.append(
            LatexSection(
                index=i,
                command=sec["command"],
                level=sec["level"],
                title=sec["title"],
                start_line=sec["start_line"],
                end_line=max(sec["start_line"], end_line),
            )
        )
    return sections


def get_section_content(tex_content: str, title_or_index: str) -> Dict[str, Any]:
    """Retrieve a specific section's content by its title (case-insensitive substring/exact) or index."""
    sections = parse_sections(tex_content)
    if not sections:
        raise ValueError("No LaTeX sections found in the file.")

    selected: Optional[LatexSection] = None
    query = title_or_index.strip()
    if query.isdigit():
        idx = int(query)
        if 0 <= idx < len(sections):
            selected = sections[idx]

    if selected is None:
        # Exact match first, then substring match
        for sec in sections:
            if sec.title.lower() == query.lower():
                selected = sec
                break
    if selected is None:
        for sec in sections:
            if query.lower() in sec.title.lower():
                selected = sec
                break

    if selected is None:
        available = [f"[{s.index}] \\{s.command}{{{s.title}}}" for s in sections]
        raise ValueError(
            f"Section '{title_or_index}' not found. Available sections: {', '.join(available)}"
        )

    lines = tex_content.splitlines()
    snippet = "\n".join(lines[selected.start_line - 1 : selected.end_line])
    return {
        "index": selected.index,
        "command": selected.command,
        "title": selected.title,
        "start_line": selected.start_line,
        "end_line": selected.end_line,
        "content": snippet,
    }


def replace_section_content(
    tex_content: str,
    title_or_index: str,
    new_section_content: str,
) -> Dict[str, Any]:
    """Replace the content of a specific section (from start_line to end_line)."""
    sec_info = get_section_content(tex_content, title_or_index)
    lines = tex_content.splitlines()
    start_idx = sec_info["start_line"] - 1
    end_idx = sec_info["end_line"]

    new_lines = new_section_content.splitlines()
    updated_lines = lines[:start_idx] + new_lines + lines[end_idx:]
    updated_text = "\n".join(updated_lines)
    if tex_content.endswith("\n") and not updated_text.endswith("\n"):
        updated_text += "\n"

    return {
        "replaced_section": sec_info["title"],
        "old_line_range": [sec_info["start_line"], sec_info["end_line"]],
        "updated_content": updated_text,
    }


def parse_bib_entries(bib_content: str) -> List[Dict[str, Any]]:
    """Parse BibTeX entries from a .bib file."""
    entries: List[Dict[str, Any]] = []
    matches = list(BIB_ENTRY_START_RE.finditer(bib_content))
    for i, match in enumerate(matches):
        entry_type = match.group("type").lower()
        if entry_type in ("comment", "preamble", "string"):
            continue
        key = match.group("key").strip()
        start_pos = match.start()
        end_pos = matches[i + 1].start() if i + 1 < len(matches) else len(bib_content)
        raw_block = bib_content[start_pos:end_pos].strip()

        fields: Dict[str, str] = {}
        for fmatch in BIB_FIELD_RE.finditer(raw_block):
            fname = fmatch.group("name").lower()
            fval = (
                fmatch.group("braced")
                or fmatch.group("quoted")
                or fmatch.group("bare")
                or ""
            )
            fields[fname] = re.sub(r"\s+", " ", fval.strip())

        entries.append(
            {
                "key": key,
                "type": entry_type,
                "title": fields.get("title", ""),
                "author": fields.get("author", ""),
                "year": fields.get("year", ""),
                "venue": fields.get("journal") or fields.get("booktitle") or "",
                "raw": raw_block,
            }
        )
    return entries


def upsert_bib_entry(bib_content: str, raw_bibtex_entry: str) -> Dict[str, Any]:
    """Add or replace a BibTeX entry in .bib content."""
    entry_str = raw_bibtex_entry.strip()
    m = BIB_ENTRY_START_RE.search(entry_str)
    if not m:
        raise ValueError(
            "Invalid BibTeX entry format. Expected '@type{key, ...}'."
        )
    key = m.group("key").strip()

    existing = parse_bib_entries(bib_content)
    for item in existing:
        if item["key"] == key:
            updated = bib_content.replace(item["raw"], entry_str, 1)
            return {"key": key, "action": "updated", "content": updated}

    sep = "\n\n" if bib_content.strip() else ""
    updated = bib_content.rstrip() + sep + entry_str + "\n"
    return {"key": key, "action": "inserted", "content": updated}


def analyze_project_references(repo_path: Path) -> Dict[str, Any]:
    """Scan all .tex and .bib files in the project to audit labels, refs, and citations."""
    labels: Dict[str, List[str]] = {}
    refs: Dict[str, List[str]] = {}
    citations_used: Dict[str, List[str]] = {}
    packages: List[str] = []
    bib_keys: Dict[str, str] = {}

    for tex_file in sorted(repo_path.rglob("*.tex")):
        if ".git" in tex_file.relative_to(repo_path).parts:
            continue
        rel = str(tex_file.relative_to(repo_path))
        text = tex_file.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            clean = strip_latex_comment(line)
            for lbl in LABEL_RE.findall(clean):
                labels.setdefault(lbl.strip(), []).append(rel)
            for rf in REF_RE.findall(clean):
                for part in rf.split(","):
                    if part.strip():
                        refs.setdefault(part.strip(), []).append(rel)
            for cite_group in CITE_RE.findall(clean):
                for ckey in cite_group.split(","):
                    if ckey.strip() and ckey.strip() != "*":
                        citations_used.setdefault(ckey.strip(), []).append(rel)
            for pkg_group in PACKAGE_RE.findall(clean):
                for pkg in pkg_group.split(","):
                    if pkg.strip() and pkg.strip() not in packages:
                        packages.append(pkg.strip())

    for bib_file in sorted(repo_path.rglob("*.bib")):
        if ".git" in bib_file.relative_to(repo_path).parts:
            continue
        rel = str(bib_file.relative_to(repo_path))
        text = bib_file.read_text(encoding="utf-8", errors="replace")
        for entry in parse_bib_entries(text):
            bib_keys[entry["key"]] = rel

    missing_citations = sorted(k for k in citations_used if k not in bib_keys)
    unused_bib_keys = sorted(k for k in bib_keys if k not in citations_used)
    broken_refs = sorted(r for r in refs if r not in labels)
    duplicate_labels = {k: v for k, v in labels.items() if len(v) > 1}

    return {
        "total_labels": len(labels),
        "total_refs": len(refs),
        "total_citations_used": len(citations_used),
        "total_bib_entries": len(bib_keys),
        "packages": packages,
        "missing_citations": missing_citations,
        "unused_bib_entries": unused_bib_keys,
        "broken_refs": broken_refs,
        "duplicate_labels": duplicate_labels,
    }


def check_latex_syntax(tex_content: str) -> Dict[str, Any]:
    """Perform structural syntax checks on a LaTeX file (environments and braces)."""
    issues: List[Dict[str, Any]] = []
    env_stack: List[ tuple[str, int] ] = []
    brace_depth = 0
    last_open_brace_line = 1

    for line_no, raw_line in enumerate(tex_content.splitlines(), start=1):
        clean = strip_latex_comment(raw_line)

        # Check \begin{...} and \end{...}
        tokens = list(
            re.finditer(r"\\(?P<kind>begin|end)\{(?P<env>[a-zA-Z0-9*]+)\}", clean)
        )
        for tok in tokens:
            kind = tok.group("kind")
            env_name = tok.group("env")
            if kind == "begin":
                env_stack.append((env_name, line_no))
            else:
                if not env_stack:
                    issues.append(
                        {
                            "line": line_no,
                            "type": "unmatched_end_env",
                            "message": f"Found \\end{{{env_name}}} without a matching \\begin{{{env_name}}}.",
                        }
                    )
                else:
                    open_env, open_line = env_stack.pop()
                    if open_env != env_name:
                        issues.append(
                            {
                                "line": line_no,
                                "type": "mismatched_env",
                                "message": (
                                    f"Mismatched environment: \\begin{{{open_env}}} (line {open_line}) "
                                    f"closed by \\end{{{env_name}}} (line {line_no})."
                                ),
                            }
                        )

        # Check unescaped curly braces
        escaped = False
        for ch in clean:
            if ch == "\\" and not escaped:
                escaped = True
                continue
            if not escaped:
                if ch == "{":
                    if brace_depth == 0:
                        last_open_brace_line = line_no
                    brace_depth += 1
                elif ch == "}":
                    brace_depth -= 1
                    if brace_depth < 0:
                        issues.append(
                            {
                                "line": line_no,
                                "type": "unmatched_closing_brace",
                                "message": "Unexpected closing brace '}' without matching '{'.",
                            }
                        )
                        brace_depth = 0
            escaped = False

    for open_env, open_line in env_stack:
        issues.append(
            {
                "line": open_line,
                "type": "unclosed_env",
                "message": f"Unclosed environment \\begin{{{open_env}}} opened on line {open_line}.",
            }
        )

    if brace_depth > 0:
        issues.append(
            {
                "line": last_open_brace_line,
                "type": "unclosed_brace",
                "message": f"{brace_depth} unclosed '{{' brace(s) starting around line {last_open_brace_line}.",
            }
        )

    return {
        "valid": len(issues) == 0,
        "issue_count": len(issues),
        "issues": issues,
    }


def compile_latex_locally(repo_path: Path, main_tex: str = "main.tex") -> Dict[str, Any]:
    """Compile the project locally using latexmk or pdflatex if installed on the system."""
    tex_file = repo_path / main_tex
    if not tex_file.exists():
        raise FileNotFoundError(f"Main TeX file '{main_tex}' not found in project.")

    latexmk_bin = shutil.which("latexmk")
    pdflatex_bin = shutil.which("pdflatex")

    if latexmk_bin:
        cmd = [latexmk_bin, "-pdf", "-interaction=nonstopmode", "-halt-on-error", main_tex]
    elif pdflatex_bin:
        cmd = [pdflatex_bin, "-interaction=nonstopmode", "-halt-on-error", main_tex]
    else:
        return {
            "compiled": False,
            "compiler_available": False,
            "message": (
                "Neither 'latexmk' nor 'pdflatex' is installed locally. "
                "Structural syntax validation was performed instead; Overleaf will compile the PDF automatically once changes are pushed."
            ),
            "syntax_check": check_latex_syntax(tex_file.read_text(encoding="utf-8", errors="replace")),
        }

    proc = subprocess.run(
        cmd,
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    output_lines = (proc.stdout + "\n" + proc.stderr).splitlines()
    errors = [line for line in output_lines if line.startswith("!") or "Error:" in line]
    return {
        "compiled": proc.returncode == 0,
        "compiler_available": True,
        "returncode": proc.returncode,
        "errors": errors[:30],
        "log_tail": "\n".join(output_lines[-40:]),
    }

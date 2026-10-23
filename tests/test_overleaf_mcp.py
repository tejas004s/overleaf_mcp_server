"""End-to-end tests for the Overleaf MCP Server using a simulated Overleaf Git Bridge remote."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from overleaf_mcp.config import OverleafConfig, extract_project_id
from overleaf_mcp.git_client import OverleafGitClient
from overleaf_mcp.server import (
    add_or_update_bib_entry,
    audit_references_and_citations,
    edit_file_snippet,
    get_document_outline,
    get_project_status,
    list_bibliography,
    list_files,
    read_file,
    read_section,
    register_project,
    set_client,
    sync_project,
    update_section,
    validate_and_compile,
    write_file,
)

SAMPLE_MAIN_TEX = r"""\documentclass{article}
\usepackage{amsmath,graphicx}
\begin{document}

\section{Introduction}
\label{sec:intro}
Large language models \cite{vaswani2017attention,missing2026ref} have transformed natural language processing.
As shown in Section~\ref{sec:method} and Equation~\ref{eq:broken}, attention is effective.

\subsection{Motivation}
We focus on collaborative LaTeX authoring.

\section{Methodology}
\label{sec:method}
Our architecture builds on self-attention.

\end{document}
"""

SAMPLE_BIB = r"""@inproceedings{vaswani2017attention,
  title={Attention is All you Need},
  author={Vaswani, Ashish and Shazeer, Noam},
  booktitle={Advances in Neural Information Processing Systems},
  year={2017}
}

@article{unused2020paper,
  title={An Unused Entry},
  author={Doe, Jane},
  journal={Journal of Testing},
  year={2020}
}
"""


@pytest.fixture()
def simulated_overleaf_env(tmp_path: Path) -> OverleafGitClient:
    """Create a bare git repository populated with sample LaTeX/BibTeX files to simulate Overleaf Git Bridge."""
    remote_bare = tmp_path / "remote_overleaf" / "64f123abc456def789012345"
    remote_bare.mkdir(parents=True)
    subprocess.run(["git", "init", "--bare", str(remote_bare)], check=True, capture_output=True)

    # Seed the remote repo from a temporary author checkout
    seed_dir = tmp_path / "seed_checkout"
    subprocess.run(["git", "clone", str(remote_bare), str(seed_dir)], check=True, capture_output=True)
    (seed_dir / "main.tex").write_text(SAMPLE_MAIN_TEX, encoding="utf-8")
    (seed_dir / "references.bib").write_text(SAMPLE_BIB, encoding="utf-8")
    subprocess.run(["git", "-C", str(seed_dir), "config", "user.name", "Author"], check=True)
    subprocess.run(["git", "-C", str(seed_dir), "config", "user.email", "author@example.com"], check=True)
    subprocess.run(["git", "-C", str(seed_dir), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(seed_dir), "commit", "-m", "Initial Overleaf commit"], check=True)
    subprocess.run(["git", "-C", str(seed_dir), "push", "origin", "HEAD"], check=True)

    workspace_dir = tmp_path / "mcp_workspace"
    config = OverleafConfig(
        git_token="olp_test_token_12345",
        default_project_id="64f123abc456def789012345",
        git_base_url=str(tmp_path / "remote_overleaf"),
        workspace_dir=workspace_dir,
    )
    client = OverleafGitClient(config=config)
    set_client(client)
    return client


def test_extract_project_id() -> None:
    assert (
        extract_project_id("https://www.overleaf.com/project/64f123abc456def789012345")
        == "64f123abc456def789012345"
    )
    assert (
        extract_project_id("https://git.overleaf.com/64f123abc456def789012345.git")
        == "64f123abc456def789012345"
    )
    assert extract_project_id("64f123abc456def789012345") == "64f123abc456def789012345"


def test_sync_and_list_files(simulated_overleaf_env: OverleafGitClient) -> None:
    sync_res = json.loads(sync_project())
    assert sync_res["file_count"] == 2
    assert "main.tex" in sync_res["files"]
    assert "references.bib" in sync_res["files"]

    tex_files = json.loads(list_files(extension_filter=".tex"))
    assert tex_files["count"] == 1
    assert tex_files["files"][0]["path"] == "main.tex"


def test_outline_and_section_operations(simulated_overleaf_env: OverleafGitClient) -> None:
    outline = json.loads(get_document_outline("main.tex"))
    assert outline["section_count"] == 3
    titles = [s["title"] for s in outline["sections"]]
    assert titles == ["Introduction", "Motivation", "Methodology"]

    sec = json.loads(read_section("Methodology"))
    assert "\\label{sec:method}" in sec["content"]

    new_method = (
        "\\section{Methodology}\n"
        "\\label{sec:method}\n"
        "We introduce a hybrid sparse-dense transformer architecture.\n"
    )
    upd = json.loads(update_section("Methodology", new_method))
    assert upd["pushed"] is True

    updated_tex = read_file("main.tex")
    assert "hybrid sparse-dense transformer architecture" in updated_tex
    assert "\\section{Introduction}" in updated_tex


def test_bibliography_and_citation_audit(simulated_overleaf_env: OverleafGitClient) -> None:
    bib = json.loads(list_bibliography(query="vaswani"))
    assert bib["count"] == 1
    assert bib["entries"][0]["key"] == "vaswani2017attention"

    audit_before = json.loads(audit_references_and_citations())
    assert "missing2026ref" in audit_before["missing_citations"]
    assert "unused2020paper" in audit_before["unused_bib_entries"]
    assert "eq:broken" in audit_before["broken_refs"]

    # Add the missing citation entry and verify audit updates
    new_bib = """@article{missing2026ref,
  title={Bridging Overleaf and AI Agents},
  author={Smith, Alex},
  journal={arXiv preprint},
  year={2026}
}"""
    add_res = json.loads(add_or_update_bib_entry(new_bib))
    assert add_res["action"] == "inserted"
    assert add_res["pushed"] is True

    audit_after = json.loads(audit_references_and_citations())
    assert "missing2026ref" not in audit_after["missing_citations"]


def test_edit_snippet_and_syntax_validation(simulated_overleaf_env: OverleafGitClient) -> None:
    edit_res = json.loads(
        edit_file_snippet(
            file_path="main.tex",
            target_text="We focus on collaborative LaTeX authoring.",
            replacement_text="We focus on AI-assisted LaTeX authoring with MCP.",
        )
    )
    assert edit_res["pushed"] is True

    val_res = json.loads(validate_and_compile("main.tex"))
    assert val_res["syntax_check"]["valid"] is True

    # Write a broken file with an unclosed environment and verify detection
    write_file(
        file_path="broken.tex",
        content="\\begin{itemize}\n\\item Missing end\n",
        auto_push=False,
    )
    broken_val = json.loads(validate_and_compile("broken.tex"))
    assert broken_val["syntax_check"]["valid"] is False
    assert broken_val["syntax_check"]["issues"][0]["type"] == "unclosed_env"


def test_register_and_status(simulated_overleaf_env: OverleafGitClient) -> None:
    reg = json.loads(
        register_project(
            "paper1",
            "https://www.overleaf.com/project/64f123abc456def789012345",
            set_default=True,
        )
    )
    assert reg["project_id"] == "64f123abc456def789012345"

    status = json.loads(get_project_status(project="paper1"))
    assert len(status["recent_commits"]) >= 1

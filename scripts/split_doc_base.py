#!/usr/bin/env python3
"""Split the source PDFs in doc_base/original/ into a hierarchical doc base.

The "doc base" replaces the abandoned embedding knowledge base: PKU curriculum
PDFs carry charts/tables an embedding model can't read, so instead of chunking
text we split each big PDF into small, topic-scoped PDFs that a vision-capable
LLM can read on demand at acceptable context cost.

Layout produced (siblings of original/):

    doc_base/
      original/                         # source PDFs (gitignored, not shipped —
                                        #   place them here to regenerate)
      本科培养方案2025-文科卷/            # one dir per source doc
        北京大学在用本科专业目录（本部）.pdf   # top-level leaf sections
        人文学部/                        # 学部  (internal outline node -> dir)
          北京大学中国语言文学系/          # 院系  (internal node -> dir)
            _概述.pdf                    # 院系 intro pages (pre-first-child range)
            汉语言文学专业.pdf            # 专业 (leaf -> pdf)
            ...
      ...
      manifest.json                     # index: every emitted pdf + page range

Granularity:
  * 培养方案 volumes (docs 1/2): split at every outline node. Leaves -> pdf,
    internal nodes -> dir + (when they carry real content before their first
    child) a `_概述.pdf` for that intro range. Pure title dividers (学部 pages)
    are dropped and logged.
  * 选课手册 (doc 4): no reliable outline -> explicit section table.
  * 辅修/双专业 (doc 3): no outline, but its printed 目录 gives 院系 page
    numbers -> explicit 学部/院系 table (per-major isn't page-splittable here).

Extraction primitive: `qpdf --pages SRC A-B -- OUT` (lossless page copy).
Outline source: `qpdf --json=2 --json-key=outlines SRC` (nested tree with
1-based dest pages). Requires the `qpdf` CLI on PATH.

Idempotent: each output volume dir is wiped and regenerated; original/ is never
touched. Run from anywhere; paths resolve relative to the repo root.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOC_BASE = REPO_ROOT / "doc_base"
ORIGINAL = DOC_BASE / "original"

# Map source filename -> human-readable volume directory name + split strategy.
# strategy: "outline" = split every outline node; "explicit" = use a hand-written
# section table (for docs whose bookmarks are too noisy to split algorithmically).
SOURCES = [
    ("202508251658433514.pdf", "本科培养方案2025-文科卷", "outline"),
    ("202509011035085202.pdf", "本科培养方案2025-理科卷", "outline"),
    ("202603021640266154.pdf", "本科生选课手册2025", "explicit"),
    ("202511051101338095.pdf", "本科辅修双专业培养方案2025", "explicit"),
]

# Explicit section boundaries for the 选课手册. Its outline mixes clean course-type
# headings (课程介绍's children) with per-paragraph noise (选课操作流程's children)
# and a mis-nested 通识 bookmark, so algorithmic splitting can't separate them.
# Each entry: (breadcrumb dir components, leaf title, 1-based start page). End =
# next entry's start - 1; the last entry runs to the document's last page. Start
# pages are the TRUE heading pages, verified by text scan + page render — the
# qpdf outline dests drift up to a page late in this doc (体育 and 通识 dests
# pointed one page early, into the prior section's tail). Refresh yearly by
# re-running the heading text scan, not by trusting bookmarks.
EXPLICIT_SECTIONS = {
    "202603021640266154.pdf": [
        ((), "封面和总目录", 1),
        ((), "校历（2025-2026学年）", 3),
        ((), "教务部办事指南及联系方式", 4),
        ((), "2025-2026学年第二学期本科生选课通知", 5),
        ((), "本科生网上选课操作流程", 14),
        (("课程介绍",), "课程介绍说明", 21),
        (("课程介绍",), "思想政治课程", 24),
        (("课程介绍",), "军事理论课程", 29),
        (("课程介绍",), "体育与健康课程", 31),
        (("课程介绍",), "劳动教育课程", 35),
        (("课程介绍",), "劳育慕课学习方法", 41),
        (("课程介绍",), "公共计算机课程简介", 43),
        (("课程介绍",), "大学英语课程", 48),
        (("课程介绍",), "核心课程", 50),
        (("课程介绍",), "通识教育课程", 142),
    ],
    # 辅修/双专业培养方案. No PDF bookmarks (qpdf sees only garbage), but the
    # printed 目录 on PDF pages 11-12 lists every 院系 with a printed page number;
    # PDF page = printed page + 12 (offset verified constant across all 25 院系,
    # each landing on a fresh page-top). Split at 院系 level (学部/院系.pdf), like
    # docs 1/2. Per-major is NOT possible here: the 102 双专业/辅修 plans flow
    # mid-page with two plan-starts on some pages, so only 院系 boundaries fall on
    # clean page breaks. Front-matter starts are PDF pages directly (pre-body,
    # outside the +12 numbering). Refresh yearly by re-reading the 目录 + offset.
    "202511051101338095.pdf": [
        ((), "修订指导意见", 4),
        ((), "辅修双专业与主修专业相斥一览表", 5),
        ((), "目录", 11),
        (("理学部",), "数学科学学院", 13),
        (("理学部",), "物理学院", 17),
        (("理学部",), "化学与分子工程学院", 22),
        (("理学部",), "生命科学学院", 26),
        (("理学部",), "地球与空间科学学院", 33),
        (("理学部",), "城市与环境学院", 40),
        (("理学部",), "心理与认知科学学院", 57),
        (("信息科学与技术学部",), "信息科学技术学院", 61),
        (("工学部",), "工学院", 86),
        (("人文学部",), "中国语言文学系", 116),
        (("人文学部",), "历史学系", 120),
        (("人文学部",), "考古文博学院", 129),
        (("人文学部",), "哲学系宗教学系", 135),
        (("人文学部",), "外国语学院", 146),
        (("人文学部",), "艺术学院", 162),
        (("社会科学学部",), "国际关系学院", 166),
        (("社会科学学部",), "法学院", 173),
        (("社会科学学部",), "信息管理系", 175),
        (("社会科学学部",), "社会学系", 179),
        (("社会科学学部",), "政府管理学院", 183),
        (("经济与管理学部",), "经济学院", 187),
        (("经济与管理学部",), "光华管理学院", 196),
        (("经济与管理学部",), "国家发展研究院", 200),
        (("跨学科类",), "元培学院", 209),
        (("医学部",), "药学院", 214),
    ],
}

# Pre-child text below this many non-whitespace chars is treated as a pure
# divider (title page) and dropped rather than emitted as an intro PDF.
INTRO_MIN_CHARS = 50

# Re-subset embedded fonts per output file. The source PDFs (Microsoft Print To
# PDF) embed one document-wide CJK font subset; qpdf's page extraction copies
# that whole subset into every split, bloating output to ~3x the source. A
# Ghostscript pdfwrite pass re-subsets each file to only the glyphs it uses,
# cutting size ~4x with no visible change to text or charts (verified). Set False
# (or pass --no-shrink) when gs is unavailable; output stays correct, just larger.
SHRINK = True


# --------------------------------------------------------------------------- #
# qpdf helpers
# --------------------------------------------------------------------------- #
def _run(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stderr}")
    return proc.stdout


def page_count(pdf: Path) -> int:
    out = _run(["qpdf", "--show-npages", str(pdf)])
    return int(out.strip())


def outline_tree(pdf: Path) -> list[dict]:
    out = _run(["qpdf", "--json=2", "--json-key=outlines", str(pdf)])
    return json.loads(out)["outlines"]


def extract_pages(src: Path, start: int, end: int, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    _run(["qpdf", str(src), "--pages", str(src), f"{start}-{end}", "--", str(dst)])
    if SHRINK:
        shrink_pdf(dst)


def shrink_pdf(path: Path) -> None:
    """Re-subset fonts via Ghostscript; replace in place only if smaller + intact."""
    tmp = path.with_name(path.stem + ".shrink.pdf")
    try:
        _run(["gs", "-q", "-dNOPAUSE", "-dBATCH", "-dSAFER", "-sDEVICE=pdfwrite",
              "-dCompatibilityLevel=1.7", "-dPDFSETTINGS=/prepress",
              "-dSubsetFonts=true", "-dCompressFonts=true", "-dDetectDuplicateImages=true",
              "-o", str(tmp), str(path)])
    except Exception as exc:  # gs missing or failed -> keep the qpdf output
        tmp.unlink(missing_ok=True)
        print(f"  ! gs shrink failed for {path.name}: {exc}; keeping unshrunk", file=sys.stderr)
        return
    if (tmp.exists() and 0 < tmp.stat().st_size < path.stat().st_size
            and page_count(tmp) == page_count(path)):
        tmp.replace(path)
    else:
        tmp.unlink(missing_ok=True)


def page_text_chars(src: Path, start: int, end: int) -> int:
    """Non-whitespace char count of a page range, via pdftotext."""
    out = _run(["pdftotext", "-f", str(start), "-l", str(end), str(src), "-"])
    return len(re.sub(r"\s", "", out))


# --------------------------------------------------------------------------- #
# Filename / title hygiene
# --------------------------------------------------------------------------- #
_ILLEGAL = str.maketrans({"/": "／", "\\": "＼", ":": "：", "*": "＊",
                          "?": "？", '"': "＂", "<": "＜", ">": "＞", "|": "｜"})


def clean_title(title: str) -> str:
    """Readable component name: drop print letter-spacing, sanitize path chars."""
    title = title.strip()
    # "人 文 学 部" / "理 学 部" -> join single-char tokens split by spacing.
    tokens = title.split()
    if len(tokens) > 1 and all(len(t) == 1 for t in tokens):
        title = "".join(tokens)
    else:
        title = re.sub(r"\s{2,}", " ", title)
    return title.translate(_ILLEGAL)


def dedupe(name: str, used: set[str]) -> str:
    """Disambiguate a name already taken in the same directory."""
    if name not in used:
        used.add(name)
        return name
    i = 2
    stem, suffix = (name.rsplit(".", 1) + [""])[:2]
    while True:
        cand = f"{stem}（{i}）" + (f".{suffix}" if suffix else "")
        if cand not in used:
            used.add(cand)
            return cand
        i += 1


# --------------------------------------------------------------------------- #
# Outline flattening
# --------------------------------------------------------------------------- #
@dataclass
class Node:
    title: str
    page: int
    is_leaf: bool
    breadcrumb: list[str]  # ancestor titles (cleaned), excluding self


def flatten(nodes: list[dict], breadcrumb: list[str], out: list[Node]) -> None:
    """DFS pre-order = document order; records each node with its ancestry."""
    for n in nodes:
        page = n.get("destpageposfrom1")
        title = n.get("title", "").strip()
        kids = n.get("kids") or []
        if page is None:  # dangling bookmark (e.g. doc4 "5-1 ...")
            # still descend in case children have valid dests
            flatten(kids, breadcrumb, out)
            continue
        out.append(Node(title=title, page=int(page), is_leaf=not kids, breadcrumb=list(breadcrumb)))
        if kids:
            flatten(kids, breadcrumb + [clean_title(title)], out)


# --------------------------------------------------------------------------- #
# Manifest entry
# --------------------------------------------------------------------------- #
@dataclass
class Emitted:
    source: str
    volume: str
    breadcrumb: list[str]
    title: str
    path: str           # relative to doc_base/
    page_start: int
    page_end: int
    kind: str           # "section" | "intro" | "whole"
    note: str = ""

    def to_dict(self) -> dict:
        d = {
            "source": self.source,
            "volume": self.volume,
            "breadcrumb": self.breadcrumb,
            "title": self.title,
            "path": self.path,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "pages": self.page_end - self.page_start + 1,
            "kind": self.kind,
        }
        if self.note:
            d["note"] = self.note
        return d


@dataclass
class SplitReport:
    volume: str
    emitted: list[Emitted] = field(default_factory=list)
    dropped: list[tuple[int, int, str]] = field(default_factory=list)  # (start, end, reason)
    skipped: list[tuple[int, str]] = field(default_factory=list)       # zero-page nodes (page, why)
    total_pages: int = 0

    def accounted(self) -> int:
        # skipped nodes own no pages (their page belongs to the next node), so
        # they must not be counted here or accounting would over-count.
        return sum(e.page_end - e.page_start + 1 for e in self.emitted) + \
               sum(b - a + 1 for a, b, _ in self.dropped)


# --------------------------------------------------------------------------- #
# Strategies
# --------------------------------------------------------------------------- #
def split_outline(src: Path, volume: str, vol_dir: Path, *, dry_run: bool) -> SplitReport:
    total = page_count(src)
    nodes: list[Node] = []
    flatten(outline_tree(src), [], nodes)

    # Keep document order; guard against out-of-order bookmarks.
    pages = [n.page for n in nodes]
    if pages != sorted(pages):
        print(f"  ! {volume}: outline pages not monotonic; sorting by page", file=sys.stderr)
        nodes.sort(key=lambda n: n.page)

    rep = SplitReport(volume=volume, total_pages=total)
    used_per_dir: dict[str, set[str]] = {}

    # Boundary: each node ends where the next node (in doc order) starts.
    starts = [n.page for n in nodes]
    ends = [starts[i + 1] - 1 for i in range(len(nodes) - 1)] + [total]

    # Front matter before the first bookmark.
    if nodes and nodes[0].page > 1:
        rep.dropped.append((1, nodes[0].page - 1, "front cover / pre-outline"))

    for idx, node in enumerate(nodes):
        start, end = node.page, ends[idx]
        dir_rel = Path(*node.breadcrumb) if node.breadcrumb else Path(".")

        if node.is_leaf:
            if end < start:
                # Two bookmarks on the same page; this one owns no pages and the
                # shared page is captured by the next node.
                rep.skipped.append(
                    (start, f"leaf '{clean_title(node.title)}' shares page with next"))
                continue
            used = used_per_dir.setdefault(str(dir_rel), set())
            fname = dedupe(clean_title(node.title) + ".pdf", used)
            rel = dir_rel / fname
            rep.emitted.append(Emitted(src.name, volume, node.breadcrumb,
                                       clean_title(node.title), str(Path(volume) / rel),
                                       start, end, "section"))
            if not dry_run:
                extract_pages(src, start, end, vol_dir / rel)
        else:
            # Internal node -> directory. Its pre-child range (start..end, where
            # end = next node start - 1) is intro content, a pure divider, or
            # empty (a grouping bookmark whose first child is on the same page).
            self_dir = dir_rel / clean_title(node.title)
            if not dry_run:
                (vol_dir / self_dir).mkdir(parents=True, exist_ok=True)
            if end < start:
                rep.skipped.append((start, f"group '{clean_title(node.title)}' has no own pages"))
                continue
            chars = page_text_chars(src, start, end)
            if chars >= INTRO_MIN_CHARS:
                used = used_per_dir.setdefault(str(self_dir), set())
                fname = dedupe("_概述.pdf", used)
                rel = self_dir / fname
                bc = node.breadcrumb + [clean_title(node.title)]
                rep.emitted.append(Emitted(src.name, volume, bc, clean_title(node.title),
                                           str(Path(volume) / rel), start, end, "intro"))
                if not dry_run:
                    extract_pages(src, start, end, vol_dir / rel)
            else:
                rep.dropped.append(
                    (start, end, f"divider '{clean_title(node.title)}' ({chars} chars)"))

    return rep


def split_explicit(src: Path, volume: str, vol_dir: Path, spec: list, *,
                   dry_run: bool) -> SplitReport:
    total = page_count(src)
    spec = sorted(spec, key=lambda s: s[2])
    rep = SplitReport(volume=volume, total_pages=total)
    used_per_dir: dict[str, set[str]] = {}

    starts = [s[2] for s in spec]
    ends = [starts[i + 1] - 1 for i in range(len(spec) - 1)] + [total]

    if spec and starts[0] > 1:
        rep.dropped.append((1, starts[0] - 1, "pre-first-section"))

    for (breadcrumb, title, start), end in zip(spec, ends, strict=True):
        if end < start:
            rep.skipped.append((start, f"section '{title}' has no pages"))
            continue
        dir_rel = Path(*breadcrumb) if breadcrumb else Path(".")
        used = used_per_dir.setdefault(str(dir_rel), set())
        fname = dedupe(clean_title(title) + ".pdf", used)
        rel = dir_rel / fname
        rep.emitted.append(Emitted(src.name, volume, list(breadcrumb), clean_title(title),
                                   str(Path(volume) / rel), start, end, "section"))
        if not dry_run:
            extract_pages(src, start, end, vol_dir / rel)
    return rep


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="compute splits + assertions, write nothing")
    ap.add_argument("--only", help="process only this source filename")
    ap.add_argument("--no-shrink", action="store_true",
                    help="skip the Ghostscript font-subset pass")
    args = ap.parse_args()

    global SHRINK
    if args.no_shrink:
        SHRINK = False

    if not ORIGINAL.is_dir():
        print(f"missing {ORIGINAL}", file=sys.stderr)
        return 1

    reports: list[SplitReport] = []
    all_emitted: list[Emitted] = []
    ok = True

    for fname, volume, strategy in SOURCES:
        if args.only and args.only != fname:
            continue
        src = ORIGINAL / fname
        if not src.exists():
            print(f"  ! source missing: {src}", file=sys.stderr)
            ok = False
            continue
        vol_dir = DOC_BASE / volume
        if not args.dry_run:
            if vol_dir.exists():
                shutil.rmtree(vol_dir)
            vol_dir.mkdir(parents=True)

        print(f"\n== {fname} -> {volume} ({strategy}) ==")
        if strategy == "explicit":
            rep = split_explicit(src, volume, vol_dir, EXPLICIT_SECTIONS[fname],
                                 dry_run=args.dry_run)
        else:
            rep = split_outline(src, volume, vol_dir, dry_run=args.dry_run)
        reports.append(rep)
        all_emitted.extend(rep.emitted)

        # Page-accounting assertion.
        accounted = rep.accounted()
        status = "OK" if accounted == rep.total_pages else "MISMATCH"
        if accounted != rep.total_pages:
            ok = False
        print(f"  pages: {rep.total_pages} total | {len(rep.emitted)} pdfs "
              f"| {sum(b-a+1 for a,b,_ in rep.dropped)} dropped pages "
              f"| {len(rep.skipped)} zero-page nodes | accounted {accounted} [{status}]")
        for a, b, why in rep.dropped:
            print(f"    drop p{a}-{b}: {why}")

        # Collision assertion: emitted file count == unique paths.
        paths = [e.path for e in rep.emitted]
        if len(paths) != len(set(paths)):
            print(f"  ! {volume}: duplicate output paths (collision)", file=sys.stderr)
            ok = False

    if not args.dry_run and not args.only:
        manifest = {
            "note": "Generated by scripts/split_doc_base.py — do not edit by hand.",
            "documents": [e.to_dict() for e in all_emitted],
        }
        (DOC_BASE / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nmanifest.json: {len(all_emitted)} entries")

    print("\n" + ("ALL OK" if ok else "PROBLEMS FOUND — see above"))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())

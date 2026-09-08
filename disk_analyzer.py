#!/usr/bin/env python3
"""
Disk Space Analyzer with Treemap Visualization
Analyzes directories up to 5 levels deep and displays interactive treemap.
"""

import os
import sys
import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
import threading

import streamlit as st
import plotly.express as px
import pandas as pd


@dataclass
class DirectoryNode:
    """Represents a directory with its size and children."""
    name: str
    path: str
    size_bytes: int
    level: int
    children: List['DirectoryNode']
    parent_path: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'path': self.path,
            'size_bytes': self.size_bytes,
            'size_mb': round(self.size_bytes / (1024 * 1024), 2),
            'size_gb': round(self.size_bytes / (1024 * 1024 * 1024), 3),
            'level': self.level,
            'parent_path': self.parent_path,
            'children': [c.to_dict() for c in self.children]
        }


class DiskAnalyzer:
    """Analyzes disk usage recursively up to specified depth."""
    
    def __init__(self, root_path: str, max_depth: int = 5, min_size_mb: float = 1.0):
        self.root_path = Path(root_path).resolve()
        self.max_depth = max_depth
        self.min_size_bytes = int(min_size_mb * 1024 * 1024)
        self._lock = threading.Lock()
        self._cache: Dict[str, int] = {}
    
    def get_size(self, path: Path) -> int:
        path_str = str(path)
        if path_str in self._cache:
            return self._cache[path_str]

        total = 0
        try:
            if path.is_symlink():
                return 0
            if path.is_file():
                total = path.stat().st_size
            elif path.is_dir():
                with os.scandir(path) as it:
                    for entry in it:
                        try:
                            if entry.is_symlink():
                                continue
                            if entry.is_file(follow_symlinks=False):
                                total += entry.stat(follow_symlinks=False).st_size
                            elif entry.is_dir(follow_symlinks=False):
                                total += self.get_size(Path(entry.path))
                        except (OSError, PermissionError):
                            continue
        except (OSError, PermissionError):
            total = 0

        with self._lock:
            self._cache[path_str] = total
        return total
    
    def _is_symlink(self, path: Path) -> bool:
        try:
            return path.is_symlink()
        except OSError:
            return False
    
    def scan_directory(self, path: Path, level: int = 0, parent_path: Optional[str] = None) -> Optional[DirectoryNode]:
        if level > self.max_depth:
            return None

        try:
            if self._is_symlink(path):
                return None
            if not path.is_dir():
                return None

            subdirs = []
            total_size = 0

            with os.scandir(path) as it:
                entries = list(it)
        except (OSError, PermissionError, FileNotFoundError):
            return None

        for entry in entries:
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    entry_path = Path(entry.path)
                    if level < self.max_depth:
                        child = self.scan_directory(entry_path, level + 1, str(path))
                        if child and child.size_bytes >= self.min_size_bytes:
                            subdirs.append(child)
                            total_size += child.size_bytes
                    else:
                        size = self.get_size(entry_path)
                        if size >= self.min_size_bytes:
                            subdirs.append(DirectoryNode(
                                name=entry.name,
                                path=str(entry_path),
                                size_bytes=size,
                                level=level + 1,
                                children=[],
                                parent_path=str(path)
                            ))
                            total_size += size
                elif entry.is_file(follow_symlinks=False):
                    total_size += entry.stat(follow_symlinks=False).st_size
            except (OSError, PermissionError):
                continue

        if total_size < self.min_size_bytes and level > 0:
            return None

        return DirectoryNode(
            name=path.name if level > 0 else path.name or str(path),
            path=str(path),
            size_bytes=total_size,
            level=level,
            children=sorted(subdirs, key=lambda x: x.size_bytes, reverse=True),
            parent_path=parent_path
        )

    def analyze(self) -> Optional[DirectoryNode]:
        return self.scan_directory(self.root_path)


IMAGE_EXTS = {
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif',
    '.heic', '.heif', '.raw', '.cr2', '.cr3', '.nef', '.arw', '.dng',
    '.orf', '.rw2', '.svg', '.ico', '.avif',
}

VIDEO_EXTS = {
    '.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v',
    '.mpg', '.mpeg', '.3gp', '.3g2', '.ts', '.mts', '.m2ts', '.vob',
    '.ogv', '.divx', '.asf', '.rmvb',
}

MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS


@dataclass
class MediaDirInfo:
    """Aggregated media stats for a single directory (recursive)."""
    path: str
    name: str
    level: int
    total_bytes: int
    media_bytes: int
    image_count: int
    video_count: int
    media_files: int
    total_files: int

    @property
    def media_pct(self) -> float:
        if self.total_bytes <= 0:
            return 0.0
        return self.media_bytes / self.total_bytes * 100.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'path': self.path,
            'level': self.level,
            'total_bytes': self.total_bytes,
            'media_bytes': self.media_bytes,
            'media_pct': round(self.media_pct, 2),
            'image_count': self.image_count,
            'video_count': self.video_count,
            'media_files': self.media_files,
            'total_files': self.total_files,
        }


class MediaAnalyzer:
    """Finds directories containing photos/videos (recursive, size-based)."""

    def __init__(self, root_path: str, max_depth: int = 5):
        self.root_path = Path(root_path).resolve()
        self.max_depth = max_depth

    def scan(self) -> List[MediaDirInfo]:
        results: List[MediaDirInfo] = []
        self._scan_recursive(self.root_path, 0, results)
        return results

    def _count_subtree(self, path: Path) -> tuple:
        """Fully count a subtree (no depth limit) for max_depth boundary."""
        total = 0
        media = 0
        img = 0
        vid = 0
        mfiles = 0
        tfiles = 0
        stack = [path]
        while stack:
            current = stack.pop()
            try:
                if current.is_symlink():
                    continue
                if not current.is_dir():
                    continue
                try:
                    with os.scandir(current) as it:
                        entries = list(it)
                except (OSError, PermissionError, FileNotFoundError):
                    continue
            except (OSError, PermissionError):
                continue
            for entry in entries:
                try:
                    if entry.is_symlink():
                        continue
                    if entry.is_file(follow_symlinks=False):
                        try:
                            size = entry.stat(follow_symlinks=False).st_size
                        except (OSError, PermissionError):
                            continue
                        total += size
                        tfiles += 1
                        ext = Path(entry.name).suffix.lower()
                        if ext in MEDIA_EXTS:
                            media += size
                            mfiles += 1
                            if ext in IMAGE_EXTS:
                                img += 1
                            elif ext in VIDEO_EXTS:
                                vid += 1
                    elif entry.is_dir(follow_symlinks=False):
                        stack.append(Path(entry.path))
                except (OSError, PermissionError):
                    continue
        return (total, media, img, vid, mfiles, tfiles)

    def _scan_recursive(
        self, path: Path, level: int, results: List[MediaDirInfo]
    ) -> tuple:
        zeros = (0, 0, 0, 0, 0, 0)
        if level > self.max_depth:
            return zeros
        try:
            if path.is_symlink():
                return zeros
            if not path.is_dir():
                return zeros
            try:
                with os.scandir(path) as it:
                    entries = list(it)
            except (OSError, PermissionError, FileNotFoundError):
                return zeros
        except (OSError, PermissionError):
            return zeros

        total = 0
        media = 0
        img = 0
        vid = 0
        mfiles = 0
        tfiles = 0

        for entry in entries:
            try:
                if entry.is_symlink():
                    continue
                if entry.is_file(follow_symlinks=False):
                    try:
                        size = entry.stat(follow_symlinks=False).st_size
                    except (OSError, PermissionError):
                        continue
                    total += size
                    tfiles += 1
                    ext = Path(entry.name).suffix.lower()
                    if ext in MEDIA_EXTS:
                        media += size
                        mfiles += 1
                        if ext in IMAGE_EXTS:
                            img += 1
                        elif ext in VIDEO_EXTS:
                            vid += 1
                elif entry.is_dir(follow_symlinks=False):
                    entry_path = Path(entry.path)
                    if level < self.max_depth:
                        (c_total, c_media, c_img, c_vid,
                         c_mfiles, c_tfiles) = self._scan_recursive(
                            entry_path, level + 1, results
                        )
                        total += c_total
                        media += c_media
                        img += c_img
                        vid += c_vid
                        mfiles += c_mfiles
                        tfiles += c_tfiles
                    else:
                        (c_total, c_media, c_img, c_vid,
                         c_mfiles, c_tfiles) = self._count_subtree(entry_path)
                        total += c_total
                        media += c_media
                        img += c_img
                        vid += c_vid
                        mfiles += c_mfiles
                        tfiles += c_tfiles
            except (OSError, PermissionError):
                continue

        try:
            name = path.name if level > 0 else (path.name or str(path))
        except (OSError, PermissionError):
            name = str(path)
        results.append(MediaDirInfo(
            path=str(path),
            name=name,
            level=level,
            total_bytes=total,
            media_bytes=media,
            image_count=img,
            video_count=vid,
            media_files=mfiles,
            total_files=tfiles,
        ))
        return (total, media, img, vid, mfiles, tfiles)


def flatten_for_treemap(node: DirectoryNode, rows: List[Dict], parent_id: str = ""):
    """Flatten directory tree for Plotly treemap."""
    node_id = f"{parent_id}/{node.name}" if parent_id else node.name
    
    rows.append({
        'id': node_id,
        'parent': parent_id,
        'name': node.name,
        'path': node.path,
        'size_bytes': node.size_bytes,
        'size_mb': round(node.size_bytes / (1024 * 1024), 2),
        'size_gb': round(node.size_bytes / (1024 * 1024 * 1024), 3),
        'level': node.level
    })
    
    for child in node.children:
        flatten_for_treemap(child, rows, node_id)


def format_size(bytes_val: int) -> str:
    """Format bytes to human readable string."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_val < 1024:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024
    return f"{bytes_val:.1f} PB"


def keep_deepest_only(df: "pd.DataFrame") -> "pd.DataFrame":
    """Keep only the deepest matching directories and hide matching ancestors.

    For example, if E:\\backup and E:\\backup\\photos match, show only ...\\photos.
    Paths are compared after normalization (normcase + normpath + separator).
    """
    if df is None or len(df) == 0 or 'path' not in df.columns:
        return df
    normed = [
        os.path.normcase(os.path.normpath(str(p))) + os.sep
        for p in df['path'].tolist()
    ]
    order = sorted(range(len(normed)), key=lambda i: len(normed[i]), reverse=True)
    keep_mask = [True] * len(normed)
    kept_prefixes: list[str] = []
    for i in order:
        prefix = normed[i]
        is_ancestor = any(kp.startswith(prefix) and kp != prefix for kp in kept_prefixes)
        if is_ancestor:
            keep_mask[i] = False
        else:
            kept_prefixes.append(prefix)
    return df[pd.Series(keep_mask, index=df.index)]


def open_directory(path: str):
    """Open directory in system file explorer."""
    try:
        if sys.platform == 'win32':
            os.startfile(path)
        elif sys.platform == 'darwin':
            subprocess.run(['open', path])
        else:
            subprocess.run(['xdg-open', path])
    except Exception as e:
        st.error(f"Could not open directory: {e}")


def get_available_drives() -> List[Dict[str, Any]]:
    """Detect available drives or mount points using only the standard library.

    Windows: letters A-Z with os.path.exists("X:\\\\") and disk usage labels.
    Linux/macOS: / plus existing /mnt/*, /media/$USER/* and /Volumes/* paths.
    """
    drives: List[Dict[str, Any]] = []
    try:
        if sys.platform == 'win32':
            import string
            for letter in string.ascii_uppercase:
                drive_path = f"{letter}:\\"
                try:
                    if os.path.exists(drive_path):
                        try:
                            usage = shutil.disk_usage(drive_path)
                            free_gb = usage.free / (1024 ** 3)
                            total_gb = usage.total / (1024 ** 3)
                            label = f"{drive_path} ({free_gb:.1f} GB free of {total_gb:.1f} GB)"
                        except (OSError, PermissionError, FileNotFoundError):
                            label = drive_path
                        drives.append({
                            'path': drive_path,
                            'label': label,
                            'free': usage.free if 'usage' in dir() else 0,
                            'total': usage.total if 'usage' in dir() else 0,
                        })
                except (OSError, PermissionError):
                    continue
        else:
            candidates: List[str] = ["/"]
            try:
                candidates += [os.path.join("/mnt", d) for d in os.listdir("/mnt")] if os.path.isdir("/mnt") else []
            except (OSError, PermissionError):
                pass
            try:
                user = os.environ.get("USER", "")
                media_base = f"/media/{user}" if user else "/media"
                if os.path.isdir(media_base):
                    candidates += [os.path.join(media_base, d) for d in os.listdir(media_base)]
            except (OSError, PermissionError):
                pass
            try:
                if os.path.isdir("/Volumes"):
                    candidates += [os.path.join("/Volumes", d) for d in os.listdir("/Volumes")]
            except (OSError, PermissionError):
                pass
            seen = set()
            for cand in candidates:
                try:
                    if cand in seen:
                        continue
                    seen.add(cand)
                    if os.path.isdir(cand) and os.access(cand, os.R_OK):
                        try:
                            usage = shutil.disk_usage(cand)
                            free_gb = usage.free / (1024 ** 3)
                            total_gb = usage.total / (1024 ** 3)
                            label = f"{cand} ({free_gb:.1f} GB free of {total_gb:.1f} GB)"
                        except (OSError, PermissionError, FileNotFoundError):
                            usage = None
                            label = cand
                        drives.append({
                            'path': cand,
                            'label': label,
                            'free': usage.free if usage else 0,
                            'total': usage.total if usage else 0,
                        })
                except (OSError, PermissionError):
                    continue
    except (OSError, PermissionError):
        pass
    return drives


def build_report(
    mode: str,
    roots: List[str],
    treemap_rows: Optional[List[Dict[str, Any]]],
    media_rows: Optional[List[Dict[str, Any]]],
    cfg: Dict[str, Any],
) -> Dict[str, Any]:
    """Build a JSON report dictionary from scan results."""
    treemap_rows = treemap_rows or []
    media_rows = media_rows or []
    total_bytes = 0
    try:
        if treemap_rows:
            df_t = pd.DataFrame(treemap_rows)
            if 'level' in df_t.columns and 'size_bytes' in df_t.columns:
                lvl0 = df_t[df_t['level'] == 0]
                total_bytes = int(lvl0['size_bytes'].sum()) if len(lvl0) > 0 else int(df_t['size_bytes'].sum())
            else:
                total_bytes = int(sum(int(r.get('size_bytes', 0)) for r in treemap_rows))
        else:
            total_bytes = 0
    except (ValueError, TypeError, KeyError):
        total_bytes = 0
    media_bytes = 0
    try:
        media_bytes = int(sum(int(r.get('media_bytes', 0)) for r in media_rows))
    except (ValueError, TypeError):
        media_bytes = 0
    deepest_count = 0
    try:
        if media_rows:
            threshold = float(cfg.get('media_threshold', 0))
            mdf = pd.DataFrame(media_rows)
            if 'media_pct' in mdf.columns and 'media_bytes' in mdf.columns:
                filt = mdf[mdf['media_pct'] >= threshold]
                filt = keep_deepest_only(filt)
                deepest_count = int(len(filt))
    except (ValueError, TypeError, KeyError):
        deepest_count = 0
    return {
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'mode': mode,
        'roots': list(roots),
        'config': {
            'max_depth': cfg.get('max_depth'),
            'min_size_mb': cfg.get('min_size_mb'),
            'media_threshold': cfg.get('media_threshold'),
        },
        'summary': {
            'directories': int(len(treemap_rows)),
            'total_bytes': int(total_bytes),
            'media_bytes': int(media_bytes),
            'media_deepest_count': int(deepest_count),
        },
        'treemap_data': treemap_rows,
        'media_data': media_rows,
    }


def save_report_to_file(report: Dict[str, Any]) -> Path:
    """Save a report to disk_report_YYYYMMDD_HHMMSS.json in the current directory."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"disk_report_{ts}.json"
    out_path = Path.cwd() / filename
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return out_path


# Streamlit App
st.set_page_config(
    page_title="Disk Cleaner",
    page_icon="💽",
    layout="wide"
)

st.title("💽 Disk Cleaner")
st.markdown("Scan one folder or all drives at once. Results include size, photos/videos, and a JSON report.")

# Session state for results
if 'analysis_result' not in st.session_state:
    st.session_state.analysis_result = None
if 'treemap_data' not in st.session_state:
    st.session_state.treemap_data = None
if 'media_data' not in st.session_state:
    st.session_state.media_data = None
if 'report_path' not in st.session_state:
    st.session_state.report_path = None
if 'scan_mode' not in st.session_state:
    st.session_state.scan_mode = "📁 Single folder"
if 'selected_drives' not in st.session_state:
    st.session_state.selected_drives = []

analyze_button = False
auto_button = False
root_path = r"C:\Users\muchs"

# Sidebar
with st.sidebar:
    st.header("1) Scan mode")
    scan_mode = st.radio(
        "Scan mode",
        options=["📁 Single folder", "🤖 Auto (all drives)"],
        key="scan_mode",
        help="Single folder scans one path. Auto scans all selected drives at once (size + media).",
    )
    is_auto = str(scan_mode).startswith("🤖")

    if not is_auto:
        root_path = st.text_input(
            "Directory to analyze",
            value=r"C:\Users\muchs",
            help="Starting path for the analysis (must exist).",
            key="root_path_input",
        )
    else:
        drives = get_available_drives()
        if not drives:
            st.warning("No drives detected.")
            st.session_state.selected_drives = []
        else:
            st.markdown("Select drives to scan:")
            picked: List[str] = []
            for d in drives:
                key = f"drive_{d['path']}"
                checked = st.checkbox(d['label'], value=True, key=key)
                if checked:
                    picked.append(d['path'])
            st.session_state.selected_drives = picked
        root_path = st.session_state.selected_drives[0] if st.session_state.selected_drives else ""

    st.divider()
    st.header("2) Settings")
    max_depth = st.slider(
        "Max Depth",
        min_value=1,
        max_value=10,
        value=5,
        help="How many directory levels to scan.",
    )
    min_size_mb = st.number_input(
        "Minimum Size (MB)",
        min_value=0.1,
        max_value=1000.0,
        value=1.0,
        step=0.5,
        help="Smaller directories are skipped.",
    )
    media_threshold = st.slider(
        "Minimum photo/video share (%)",
        min_value=0,
        max_value=100,
        value=30,
        help="A directory matches when media_pct = media_bytes / total_bytes * 100 >= threshold.",
        key="media_threshold",
    )
    min_media_mb = st.number_input(
        "Minimum media size (MB)",
        min_value=0.0,
        value=0.0,
        step=1.0,
        help="Ignore directories with a smaller combined photo and video size.",
        key="min_media_mb",
    )

    st.divider()
    st.header("3) Actions")
    if not is_auto:
        analyze_button = st.button("🔍 Analyze folder", type="primary", use_container_width=True, key="analyze_btn")
        st.caption("Scan the size of one folder. Use the 📸 tab to scan media.")
    else:
        auto_button = st.button("🤖 Scan selected drives", type="primary", use_container_width=True, key="auto_btn")
        st.caption("One click scans size + media for all selected drives.")

    st.divider()
    st.header("4) Help")
    st.markdown(
        "1. Choose a mode: single folder or Auto.\n"
        "2. In Auto mode, uncheck drives you do not want to scan.\n"
        "3. Adjust settings (depth and thresholds).\n"
        "4. Start a scan, then review the tabs and JSON report."
    )


def _current_cfg() -> Dict[str, Any]:
    return {
        'max_depth': int(max_depth),
        'min_size_mb': float(min_size_mb),
        'media_threshold': float(st.session_state.get('media_threshold', 30)),
    }


def _auto_save_report(mode: str, roots: List[str]):
    try:
        report = build_report(
            mode, roots,
            st.session_state.treemap_data, st.session_state.media_data,
            _current_cfg(),
        )
        path = save_report_to_file(report)
        st.session_state.report_path = str(path)
        return report, path
    except (OSError, PermissionError, ValueError, TypeError) as e:
        st.warning(f"Could not save the report: {e}")
        return None, None

# Run analysis (single folder: size)
if analyze_button:
    if not root_path or not os.path.exists(root_path):
        st.error(f"Path does not exist: {root_path}")
    else:
        with st.spinner("Scanning directories... This may take a while for large folders."):
            analyzer = DiskAnalyzer(root_path, max_depth, min_size_mb)
            root_node = analyzer.analyze()

            if root_node:
                rows = []
                flatten_for_treemap(root_node, rows)
                st.session_state.analysis_result = root_node
                st.session_state.treemap_data = rows
                st.success(f"Analysis complete! Found {len(rows)} directories.")
                _auto_save_report("single", [root_path])
            else:
                st.error("No directories found or access denied.")

# Run auto scan (wszystkie wybrane dyski: rozmiar + media)
if auto_button:
    selected = list(st.session_state.get('selected_drives', []))
    if not selected:
        st.error("Select at least one drive to scan.")
    else:
        all_rows: List[Dict[str, Any]] = []
        all_media: List[Dict[str, Any]] = []
        nodes = []
        progress = st.progress(0)
        with st.status("Scanning drives...", expanded=True) as status:
            for i, drive in enumerate(selected):
                status.write(f"Scanning: {drive} ({i + 1}/{len(selected)})")
                try:
                    if not os.path.exists(drive):
                        st.warning(f"Skipped unavailable drive: {drive}")
                        continue
                    analyzer = DiskAnalyzer(drive, max_depth, min_size_mb)
                    root_node = analyzer.analyze()
                    if root_node:
                        nodes.append(root_node)
                        tmp_rows: List[Dict[str, Any]] = []
                        flatten_for_treemap(root_node, tmp_rows, parent_id=drive)
                        all_rows.extend(tmp_rows)
                    else:
                        st.warning(f"Drive is empty or access was denied: {drive}")
                except (OSError, PermissionError, FileNotFoundError) as e:
                    st.warning(f"Drive scan failed for {drive}: {e}")
                    continue
                try:
                    m_analyzer = MediaAnalyzer(drive, max_depth)
                    m_results = m_analyzer.scan()
                    all_media.extend([m.to_dict() for m in m_results])
                except (OSError, PermissionError, FileNotFoundError) as e:
                    st.warning(f"Media scan failed for {drive}: {e}")
                    continue
                progress.progress((i + 1) / len(selected))
            status.update(label="Scan complete", state="complete")
        progress.empty()
        st.session_state.analysis_result = nodes if nodes else None
        st.session_state.treemap_data = all_rows if all_rows else None
        st.session_state.media_data = all_media if all_media else None
        if all_rows or all_media:
            st.success(f"Auto scan complete! Directories: {len(all_rows)}, media entries: {len(all_media)}.")
            _auto_save_report("auto", selected)
        else:
            st.error("No results were collected (access to the selected drives was denied).")

tab_treemap, tab_media, tab_report = st.tabs(["📦 Disk Usage", "📸 Photos and Videos", "📄 Report"])

with tab_treemap:
    # Display results
    if st.session_state.treemap_data:
        df = pd.DataFrame(st.session_state.treemap_data)

        # Summary metrics
        col1, col2, col3, col4 = st.columns(4)
        total_size = df[df['level'] == 0]['size_bytes'].iloc[0] if len(df[df['level'] == 0]) > 0 else 0

        with col1:
            st.metric("Total Size", format_size(total_size))
        with col2:
            st.metric("Directories Scanned", len(df))
        with col3:
            max_depth_found = df['level'].max()
            st.metric("Max Depth Found", max_depth_found)
        with col4:
            largest = df.loc[df['size_bytes'].idxmax()]
            st.metric("Largest Folder", f"{largest['name']} ({format_size(largest['size_bytes'])})")

        # Treemap
        st.subheader("📦 Treemap Visualization")

        fig = px.treemap(
            df,
            ids='id',
            parents='parent',
            names='name',
            values='size_bytes',
            color='level',
            color_continuous_scale='Viridis',
            hover_data={
                'size_mb': ':.2f',
                'size_gb': ':.3f',
                'path': True,
                'level': True
            },
            custom_data=['path', 'size_mb', 'size_gb', 'level']
        )

        fig.update_traces(
            textinfo="label+value",
            texttemplate="%{label}<br>%{customdata[1]:.1f} MB",
            hovertemplate="<b>%{label}</b><br>" +
                          "Path: %{customdata[0]}<br>" +
                          "Size: %{customdata[1]:.2f} MB (%{customdata[2]:.3f} GB)<br>" +
                          "Level: %{customdata[3]}<br>" +
                          "<extra></extra>",
            marker=dict(
                line=dict(width=1, color='white')
            )
        )

        fig.update_layout(
            margin=dict(t=30, l=10, r=10, b=10),
            height=700,
            font=dict(size=12)
        )

        # Display treemap with click handling
        selected = st.plotly_chart(fig, use_container_width=True, on_select="rerun", key="treemap")

        # Handle click selection
        if selected and selected.selection and selected.selection.points:
            point = selected.selection.points[0]
            if isinstance(point, dict):
                custom_data = point.get("customdata")
                point_id = point.get("id")
            else:
                custom_data = getattr(point, "customdata", None)
                point_id = getattr(point, "id", None)
            if custom_data:
                clicked_path = custom_data[0]
                clicked_size_mb = custom_data[1]
                clicked_size_gb = custom_data[2]
                clicked_level = custom_data[3]

                st.divider()
                st.subheader("📁 Selected Directory Details")

                col1, col2 = st.columns([3, 1])
                with col1:
                    st.code(clicked_path, language=None)
                with col2:
                    if st.button("📂 Open in Explorer", use_container_width=True):
                        open_directory(clicked_path)
                        st.toast(f"Opened: {clicked_path}")

                st.metric("Size", f"{clicked_size_mb:.2f} MB ({clicked_size_gb:.3f} GB)")
                st.metric("Depth Level", clicked_level)

                # Show children if any
                children = df[df['parent'] == point_id]
                if len(children) > 0:
                    st.markdown("#### Subdirectories")
                    children_sorted = children.sort_values('size_bytes', ascending=False)
                    st.dataframe(
                        children_sorted[['name', 'size_mb', 'size_gb', 'path']].rename(columns={
                            'name': 'Name',
                            'size_mb': 'Size (MB)',
                            'size_gb': 'Size (GB)',
                            'path': 'Path'
                        }),
                        use_container_width=True,
                        hide_index=True
                    )

        # Detailed table view
        with st.expander("📋 Full Directory Table", expanded=False):
            # Filter controls
            col1, col2 = st.columns(2)
            with col1:
                level_filter = st.multiselect(
                    "Filter by Level",
                    options=sorted(df['level'].unique()),
                    default=sorted(df['level'].unique())
                )
            with col2:
                min_size_filter = st.number_input(
                    "Min Size (MB)",
                    min_value=0.0,
                    value=0.0,
                    step=1.0
                )

            filtered_df = df[
                (df['level'].isin(level_filter)) &
                (df['size_mb'] >= min_size_filter)
            ].sort_values('size_bytes', ascending=False)

            st.dataframe(
                filtered_df[['name', 'size_mb', 'size_gb', 'level', 'path']].rename(columns={
                    'name': 'Directory',
                    'size_mb': 'Size (MB)',
                    'size_gb': 'Size (GB)',
                    'level': 'Depth',
                    'path': 'Full Path'
                }),
                use_container_width=True,
                hide_index=True,
                height=400
            )

        # Export options
        st.divider()
        col1, col2 = st.columns(2)
        with col1:
            csv = df.to_csv(index=False).encode('utf-8')
            _csv_label = (Path(root_path).name if root_path else "multi") or "multi"
            st.download_button(
                "📥 Download CSV",
                csv,
                f"disk_analysis_{_csv_label}.csv",
                "text/csv",
                use_container_width=True
            )
        with col2:
            json_str = json.dumps([r for r in st.session_state.treemap_data], indent=2, ensure_ascii=False)
            st.download_button(
                "📥 Download JSON",
                json_str,
                f"disk_analysis_{_csv_label}.json",
                "application/json",
                use_container_width=True
            )

    else:
        # Initial state
        st.info("👈 Configure settings in the sidebar and click **Analyze** to start.")

        st.markdown("""
        ### Features
        - **🌳 Treemap Visualization**: Interactive rectangles proportional to directory sizes
        - **📂 Click to Explore**: Click any rectangle to see details and open in file explorer
        - **🎯 Configurable Depth**: Scan 1-10 levels deep (default 5)
        - **🔍 Size Filtering**: Ignore small directories to focus on space hogs
        - **📊 Export Data**: Download results as CSV or JSON
        - **⚡ Fast Scanning**: Multi-threaded with caching for performance

        ### Treemap Guide
        - **Rectangle size** = Directory size (larger = more space)
        - **Color** = Directory depth (darker = deeper)
        - **Hover** = See exact size and path
        - **Click** = Select for details and "Open in Explorer"
        """)

with tab_media:
    st.subheader("📸 Photos and Videos")
    st.markdown(
        "Shows directories where photos and videos use at least X% "
        "of the total size (media_bytes / total_bytes × 100, calculated recursively)."
    )
    media_threshold = float(st.session_state.get('media_threshold', 30))
    min_media_mb = float(st.session_state.get('min_media_mb', 0.0))
    st.info(f"Media threshold: **{media_threshold:.0f}%** · minimum media size: **{min_media_mb:.1f} MB** (set in the sidebar → Settings).")

    if st.button("🎬 Find photos and videos", type="primary", use_container_width=True, key="media_scan"):
        _is_auto = str(st.session_state.get('scan_mode', '')).startswith("🤖")
        if _is_auto:
            _sel = list(st.session_state.get('selected_drives', []))
            if not _sel:
                st.error("Select at least one drive in the sidebar.")
            else:
                with st.spinner("Scanning photos and videos on selected drives..."):
                    _all: List[Dict[str, Any]] = []
                    for _d in _sel:
                        try:
                            if not os.path.exists(_d):
                                st.warning(f"Skipped unavailable drive: {_d}")
                                continue
                            _all.extend([m.to_dict() for m in MediaAnalyzer(_d, max_depth).scan()])
                        except (OSError, PermissionError, FileNotFoundError) as e:
                            st.warning(f"Media scan failed for {_d}: {e}")
                            continue
                    st.session_state.media_data = _all
                    st.success(f"Media scan complete! Checked {len(_all)} directories.")
                    _auto_save_report("auto", _sel)
        else:
            if not root_path or not os.path.exists(root_path):
                st.error(f"Path does not exist: {root_path}")
            else:
                with st.spinner("Scanning photos and videos... This may take a while."):
                    media_analyzer = MediaAnalyzer(root_path, max_depth)
                    media_results = media_analyzer.scan()
                    st.session_state.media_data = [m.to_dict() for m in media_results]
                    st.success(f"Media scan complete! Checked {len(media_results)} directories.")
                    _auto_save_report("single", [root_path])

    if st.session_state.media_data:
        media_df = pd.DataFrame(st.session_state.media_data)
        min_media_bytes = float(min_media_mb) * 1024 * 1024
        filtered = media_df[
            (media_df['media_pct'] >= float(media_threshold))
            & (media_df['media_bytes'] >= min_media_bytes)
        ].sort_values('media_bytes', ascending=False)

        deepest_only = st.checkbox(
            "Deepest directories only (hide parents, e.g. show E:\\backup\\photos instead of E:\\backup)",
            value=True,
            key="media_deepest_only",
        )
        if deepest_only:
            filtered = keep_deepest_only(filtered).sort_values('media_bytes', ascending=False)

        mcol1, mcol2, mcol3 = st.columns(3)
        with mcol1:
            st.metric("Matching directories", len(filtered))
        with mcol2:
            st.metric("Total media size", format_size(int(filtered['media_bytes'].sum()) if len(filtered) > 0 else 0))
        with mcol3:
            if len(filtered) > 0:
                biggest = filtered.iloc[0]
                st.metric("Largest media directory", f"{biggest['name']} ({format_size(int(biggest['media_bytes']))})")
            else:
                st.metric("Largest media directory", "—")

        if len(filtered) == 0:
            st.info("No directories meet the threshold. Lower the slider or scan again.")
        else:
            st.subheader("📊 Top 15 directories (media size)")
            top15 = filtered.head(15).copy()
            bar_fig = px.bar(
                top15,
                x='media_bytes',
                y='name',
                orientation='h',
                hover_data=['path', 'media_pct', 'image_count', 'video_count', 'media_files'],
                labels={'media_bytes': 'Media size (B)', 'name': 'Directory'},
            )
            bar_fig.update_layout(height=max(400, len(top15) * 32), yaxis={'autorange': 'reversed'})
            st.plotly_chart(bar_fig, use_container_width=True, key="media_bar")

            st.subheader("📋 Directories with media")
            display_df = filtered[[
                'name', 'path', 'total_bytes', 'media_bytes', 'media_pct',
                'image_count', 'video_count', 'media_files', 'level',
            ]].rename(columns={
                'name': 'Name',
                'path': 'Path',
                'total_bytes': 'Total size (B)',
                'media_bytes': 'Media size (B)',
                'media_pct': 'Media %',
                'image_count': 'Images',
                'video_count': 'Videos',
                'media_files': 'Media files',
                'level': 'Depth',
            })
            st.dataframe(display_df, use_container_width=True, hide_index=True, height=400)

            options = filtered['path'].tolist()
            labels = [f"{r['name']} — {format_size(int(r['media_bytes']))} ({r['media_pct']:.1f}%)" for _, r in filtered.iterrows()]
            label_to_path = dict(zip(labels, options, strict=True))
            chosen_label = st.selectbox("Select a directory", labels, key="media_folder_select")
            chosen_path = label_to_path.get(chosen_label, options[0] if options else "")
            if chosen_path:
                st.code(chosen_path, language=None)
                if st.button("📂 Open in Explorer", use_container_width=True, key="media_open"):
                    open_directory(chosen_path)
                    st.toast(f"Opened: {chosen_path}")

            st.divider()
            media_csv = filtered.to_csv(index=False).encode('utf-8')
            _media_label = (Path(root_path).name if root_path else "multi") or "multi"
            st.download_button(
                "📥 Download media CSV",
                media_csv,
                f"media_analysis_{_media_label}.csv",
                "text/csv",
                use_container_width=True,
                key="media_csv",
            )
    else:
        st.info("👆 Set a directory in the sidebar and click **🎬 Find photos and videos**.")

with tab_report:
    st.subheader("📄 Report")
    st.markdown("Full JSON report from the scan: summary, configuration, and data. Saved automatically after every scan.")
    _t_rows = st.session_state.get('treemap_data') or []
    _m_rows = st.session_state.get('media_data') or []
    _is_auto_rep = str(st.session_state.get('scan_mode', '')).startswith("🤖")
    if _is_auto_rep:
        _roots_rep = list(st.session_state.get('selected_drives', []))
        _mode_rep = "auto"
    else:
        _roots_rep = [root_path] if root_path else []
        _mode_rep = "single"
    _cfg_rep = _current_cfg()
    if _t_rows or _m_rows:
        _live = build_report(_mode_rep, _roots_rep, _t_rows, _m_rows, _cfg_rep)
        _summ = _live.get('summary', {})
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("Directories", int(_summ.get('directories', 0)))
        with c2:
            st.metric("Razem", format_size(int(_summ.get('total_bytes', 0))))
        with c3:
            st.metric("Media", format_size(int(_summ.get('media_bytes', 0))))
        with c4:
            st.metric("Medialnych (deepest)", int(_summ.get('media_deepest_count', 0)))
        st.markdown(f"**Mode:** `{_live.get('mode')}` · **Directories:** `{', '.join(_roots_rep) if _roots_rep else '—'}` · **Generated:** `{_live.get('generated_at')}`")
        _rp = st.session_state.get('report_path')
        if _rp:
            st.info(f"Last saved report: `{_rp}`")
        else:
            st.info("The report has not been saved to disk yet.")
        _json_str = json.dumps(_live, ensure_ascii=False, indent=2)
        st.download_button(
            "📥 Download JSON report",
            _json_str.encode('utf-8'),
            f"disk_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            "application/json",
            use_container_width=True,
            key="report_download",
        )
        if st.button("💾 Save report to JSON", use_container_width=True, key="report_save"):
            try:
                _p = save_report_to_file(_live)
                st.session_state.report_path = str(_p)
                st.success(f"Report saved: {_p}")
            except (OSError, PermissionError, ValueError, TypeError) as e:
                st.error(f"Could not save the report: {e}")
        with st.expander("🔍 Report preview (summary + config)", expanded=False):
            st.json({'summary': _live.get('summary'), 'config': _live.get('config'), 'mode': _live.get('mode'), 'roots': _live.get('roots'), 'generated_at': _live.get('generated_at')})
        with st.expander("🧾 Treemap (first 20 rows)", expanded=False):
            st.json(_t_rows[:20] if isinstance(_t_rows, list) else [])
        with st.expander("🖼️ Media (first 20 rows)", expanded=False):
            st.json(_m_rows[:20] if isinstance(_m_rows, list) else [])
    else:
        st.info("👆 Run a scan first (from the sidebar or the 📸 tab) to generate a report here.")

if __name__ == "__main__":
    # This allows running directly with: streamlit run disk_analyzer.py
    pass
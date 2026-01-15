#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  RECALC TOOLKIT: DSL1 ↔ DSL2 ↔ PAYMENT_SCHEDULE RECONCILIATION ENGINE       ║
║  Codename: "NEXUS GRILL SUMMIT CONVERGENCE"                                  ║
║  Version: 3.0.0                                                              ║
║                                                                              ║
║  Purpose: Multi-Source Reconciliation with GROUP_FLAG Filtering              ║
║                                                                              ║
║  Comparison Matrix:                                                          ║
║    [A] DSL1 vs DSL2:                                                         ║
║        - ACC_NO ↔ เลขบัญชี (Join Key, WHERE GROUP_FLAG = 1)                  ║
║        - FIRST_PAYMENT_DATE ↔ วันที่เริ่มชำระหนี้                              ║
║        - PRE_BALANCE ↔ ยอดหนี้เงินกู้                                         ║
║        - EXACT_PRE_BALANCE ↔ ยอดหนี้เงินกู้                                   ║
║        - EXACT_PRE_BALANCE ↔ PRE_BALANCE (แยกหนี้ Detection)                 ║
║                                                                              ║
║    [B] Payment Schedule vs DSL2:                                             ║
║        - ACC_NO ↔ เลขบัญชี (Join Key)                                        ║
║        - DUE_PAYMENT_DATE ↔ วันที่เริ่มชำระหนี้                                ║
║        - CAPITAL_REMAIN ↔ ยอดหนี้เงินกู้                                      ║
║                                                                              ║
║  Compliance: Nexus Protocol v10.0 / DoD DevSecOps Reference Design          ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import argparse
import base64
import hashlib
import json
import os
import sys
import time
import gc
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, date
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any, Union

# ══════════════════════════════════════════════════════════════════════════════
# DEPENDENCY VALIDATION
# ══════════════════════════════════════════════════════════════════════════════

try:
    import polars as pl
    POLARS_AVAILABLE = True
except ImportError:
    POLARS_AVAILABLE = False

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

try:
    import numpy as np
except ImportError:
    print("☠ [FATAL] NumPy is required. Install via: pip install numpy")
    sys.exit(1)

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import (
        Progress, SpinnerColumn, BarColumn, TextColumn, 
        TimeElapsedColumn, TimeRemainingColumn, TaskProgressColumn,
        MofNCompleteColumn, TransferSpeedColumn
    )
    from rich.table import Table
    from rich.theme import Theme
    from rich import box
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    print("⚠ [WARN] Rich library not found. Install via: pip install rich")

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

# ══════════════════════════════════════════════════════════════════════════════
# NEXUS THEME CONFIGURATION (Titanium-Void Palette)
# ══════════════════════════════════════════════════════════════════════════════

class NexusTheme:
    """Titanium-Void color theming per Nexus Protocol v10.0."""
    
    THEMES = {
        "titanium-void": {
            "void": "#050505",
            "deep": "#0a0a0f",
            "titanium": "#86868b",
            "silver": "#f5f5f7",
            "neon_core": "#3b82f6",
            "accent_gold": "#f59e0b",
            "peach_fuzz": "#FFBE98",
            "success": "#10b981",
            "danger": "#ef4444",
            "warning": "#f59e0b",
            "info": "#06b6d4",
            "violet": "#8b5cf6",
        },
        "peach-fuzz": {
            "void": "#0a0a1a",
            "deep": "#0d1025",
            "titanium": "#636E72",
            "silver": "#e2e8f0",
            "neon_core": "#3B82F6",
            "accent_gold": "#FF9A5C",
            "peach_fuzz": "#FFBE98",
            "success": "#00FF88",
            "danger": "#FF4757",
            "warning": "#FFD93D",
            "info": "#74B9FF",
            "violet": "#a855f7",
        }
    }
    
    def __init__(self, theme_name: str = "titanium-void"):
        self.colors = self.THEMES.get(theme_name, self.THEMES["titanium-void"])
    
    def style(self, key: str) -> str:
        return self.colors.get(key, "#FFFFFF")


# ══════════════════════════════════════════════════════════════════════════════
# SCI-FI TERMINAL SETUP (Command Deck)
# ══════════════════════════════════════════════════════════════════════════════

if RICH_AVAILABLE:
    nexus_cli_theme = Theme({
        "recon": "bold #06b6d4",      # Cyan - Reconnaissance
        "flux": "bold #8b5cf6",       # Violet - Processing
        "write": "bold #f97316",      # Plasma Orange - I/O
        "secure": "bold #10b981",     # Emerald - Success
        "fatal": "bold white on red", # Fatal errors
        "warn": "bold #f59e0b",       # Warning
        "info": "dim #86868b",        # Info
        "peach": "bold #FFBE98",      # Peach Fuzz accent
    })
    console = Console(theme=nexus_cli_theme)
else:
    console = None

theme = NexusTheme("titanium-void")

# Global timer for tracking operation durations
_operation_start_times: Dict[str, float] = {}


def start_timer(operation_id: str) -> None:
    """Start a timer for an operation."""
    _operation_start_times[operation_id] = time.time()


def get_elapsed(operation_id: str) -> str:
    """Get elapsed time string for an operation."""
    if operation_id not in _operation_start_times:
        return ""
    elapsed = time.time() - _operation_start_times[operation_id]
    if elapsed < 1:
        return f" [{elapsed*1000:.0f}ms]"
    elif elapsed < 60:
        return f" [{elapsed:.2f}s]"
    else:
        minutes = int(elapsed // 60)
        seconds = elapsed % 60
        return f" [{minutes}m {seconds:.1f}s]"


def log_recon(msg: str, operation_id: str = None):
    """Log reconnaissance/scanning message."""
    elapsed = get_elapsed(operation_id) if operation_id else ""
    if console:
        console.print(f"[recon]⚡ [RECON][/recon] {msg}[info]{elapsed}[/info]")
    else:
        print(f"⚡ [RECON] {msg}{elapsed}")


def log_flux(msg: str, operation_id: str = None):
    """Log processing/flux message."""
    elapsed = get_elapsed(operation_id) if operation_id else ""
    if console:
        console.print(f"[flux]🔮 [FLUX][/flux] {msg}[info]{elapsed}[/info]")
    else:
        print(f"🔮 [FLUX] {msg}{elapsed}")


def log_write(msg: str, operation_id: str = None):
    """Log I/O write message."""
    elapsed = get_elapsed(operation_id) if operation_id else ""
    if console:
        console.print(f"[write]📝 [WRITE][/write] {msg}[info]{elapsed}[/info]")
    else:
        print(f"📝 [WRITE] {msg}{elapsed}")


def log_secure(msg: str, operation_id: str = None):
    """Log success/secure message."""
    elapsed = get_elapsed(operation_id) if operation_id else ""
    if console:
        console.print(f"[secure]✅ [SECURE][/secure] {msg}[info]{elapsed}[/info]")
    else:
        print(f"✅ [SECURE] {msg}{elapsed}")


def log_warn(msg: str):
    """Log warning message."""
    if console:
        console.print(f"[warn]⚠ [WARN][/warn] {msg}")
    else:
        print(f"⚠ [WARN] {msg}")


def log_fatal(msg: str):
    """Log fatal error message."""
    if console:
        console.print(f"[fatal]☠ [FATAL][/fatal] {msg}")
    else:
        print(f"☠ [FATAL] {msg}")


def log_info(msg: str, operation_id: str = None):
    """Log informational message."""
    elapsed = get_elapsed(operation_id) if operation_id else ""
    if console:
        console.print(f"[info]ℹ [INFO][/info] {msg}[info]{elapsed}[/info]")
    else:
        print(f"ℹ [INFO] {msg}{elapsed}")


def get_system_stats() -> Dict[str, str]:
    """Retrieve system RAM/CPU statistics."""
    stats = {"ram": "N/A", "cpu": "N/A", "ram_pct": "N/A", "ram_used_gb": 0, "ram_total_gb": 0}
    if PSUTIL_AVAILABLE:
        mem = psutil.virtual_memory()
        stats["ram"] = f"{mem.used / (1024**3):.1f}GB / {mem.total / (1024**3):.1f}GB"
        stats["ram_pct"] = f"{mem.percent}%"
        stats["ram_used_gb"] = round(mem.used / (1024**3), 2)
        stats["ram_total_gb"] = round(mem.total / (1024**3), 2)
        stats["cpu"] = f"{psutil.cpu_percent(interval=0.1)}%"
    return stats


def render_header_panel(title: str, version: str = "3.0.0"):
    """Render the Nexus-style header panel."""
    if not console:
        print(f"\n{'='*70}\n{title} v{version}\n{'='*70}\n")
        return
    
    stats = get_system_stats()
    
    header_content = f"""[bold cyan]╔══════════════════════════════════════════════════════════════╗[/bold cyan]
[bold white]║  {title.center(58)}  ║[/bold white]
[dim]║  {'Version: ' + version:^58}  ║[/dim]
[bold cyan]╠══════════════════════════════════════════════════════════════╣[/bold cyan]
[dim cyan]║  RAM: {stats['ram']:20} │ CPU: {stats['cpu']:20}  ║[/dim cyan]
[bold cyan]╚══════════════════════════════════════════════════════════════╝[/bold cyan]"""
    
    console.print(Panel(
        header_content,
        border_style="cyan",
        box=box.DOUBLE,
        padding=(0, 1)
    ))


# ══════════════════════════════════════════════════════════════════════════════
# HOLOGRAPHIC PRE-FLIGHT RECONNAISSANCE
# ══════════════════════════════════════════════════════════════════════════════

def pre_flight_estimate(file_path: Path, sample_size_mb: int = 50) -> Dict[str, Any]:
    """
    HOLOGRAPHIC SCAN: Weighs sample chunk to estimate rows for massive files.
    Per Nexus Protocol v10.0 Section 2.1.
    """
    log_recon(f"INITIATING PRE-FLIGHT RECONNAISSANCE: {file_path.name}...")
    
    try:
        file_size = file_path.stat().st_size
        sample_bytes = sample_size_mb * 1024 * 1024
        
        with open(file_path, 'rb') as f:
            chunk = f.read(min(sample_bytes, file_size))
        
        lines_in_chunk = chunk.count(b'\n') or 1
        avg_bytes_per_row = len(chunk) / lines_in_chunk
        est_rows = int(file_size / avg_bytes_per_row)
        
        result = {
            "file_name": file_path.name,
            "file_size_bytes": file_size,
            "file_size_gb": round(file_size / (1024**3), 2),
            "sample_size_mb": round(len(chunk) / (1024**2), 2),
            "lines_in_sample": lines_in_chunk,
            "avg_bytes_per_row": round(avg_bytes_per_row, 2),
            "estimated_rows": est_rows,
        }
        
        log_recon(f"   >> SIZE: {result['file_size_gb']:.2f} GB | EST. VECTORS: {est_rows:,}")
        return result
        
    except Exception as e:
        log_warn(f"   >> SCAN FAILED, ENGAGING STREAM MODE ({e})")
        return {
            "file_name": file_path.name,
            "file_size_bytes": 0,
            "estimated_rows": 1000000,
            "error": str(e)
        }


def holographic_folder_scan(folder: Path) -> Dict[str, Any]:
    """Scan entire folder and estimate total rows."""
    files = discover_files(folder)
    total_size = 0
    total_est_rows = 0
    file_details = []
    
    for f in files:
        est = pre_flight_estimate(f)
        total_size += est.get("file_size_bytes", 0)
        total_est_rows += est.get("estimated_rows", 0)
        file_details.append(est)
    
    return {
        "folder": str(folder),
        "file_count": len(files),
        "total_size_gb": round(total_size / (1024**3), 2),
        "total_estimated_rows": total_est_rows,
        "files": file_details
    }


# ══════════════════════════════════════════════════════════════════════════════
# INPUT HANDLING: "THE IRON GRIP"
# ══════════════════════════════════════════════════════════════════════════════

# Multi-encoding fallback chain per specification
ENCODING_CHAIN = ["utf-8-sig", "utf-8", "cp874", "iso-8859-11", "latin-1", "iso-8859-1"]

# Thai-specific encodings for DSL2
THAI_ENCODING_CHAIN = ["iso-8859-11", "cp874", "tis-620", "utf-8-sig", "utf-8", "latin-1"]


def detect_encoding(file_path: Path, sample_size: int = 65536) -> str:
    """
    Detect file encoding using multi-encoding fallback.
    Implements "The Iron Grip" pattern.
    """
    with open(file_path, "rb") as f:
        sample = f.read(sample_size)
    
    # Check for BOM markers first
    if sample.startswith(b'\xef\xbb\xbf'):
        return "utf-8-sig"
    if sample.startswith(b'\xff\xfe'):
        return "utf-16-le"
    if sample.startswith(b'\xfe\xff'):
        return "utf-16-be"
    
    # Try Thai encodings first for DSL2-like files
    for encoding in THAI_ENCODING_CHAIN:
        try:
            sample.decode(encoding)
            return encoding
        except (UnicodeDecodeError, LookupError):
            continue
    
    # Fallback to general chain
    for encoding in ENCODING_CHAIN:
        try:
            sample.decode(encoding)
            return encoding
        except (UnicodeDecodeError, LookupError):
            continue
    
    log_warn(f"All encodings failed for {file_path.name}, defaulting to latin-1")
    return "latin-1"


def safe_float(value: Any, default: float = 0.0) -> float:
    """
    Safe numeric conversion.
    Maps NaN, None, whitespace, "-" to default value.
    """
    if value is None:
        return default
    if isinstance(value, (int, float)):
        if isinstance(value, float) and np.isnan(value):
            return default
        return float(value)
    
    str_val = str(value).strip()
    if str_val in ("", "-", "N/A", "null", "NULL", "None", "nan", "NaN"):
        return default
    
    # Remove Thai number formatting (commas)
    str_val = str_val.replace(",", "")
    
    try:
        result = float(str_val)
        return default if np.isnan(result) else result
    except (ValueError, TypeError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    """Safe integer conversion."""
    try:
        f = safe_float(value, float(default))
        return int(f)
    except (ValueError, TypeError):
        return default


def parse_date_dsl1(date_str: Any) -> Optional[datetime]:
    """
    Parse DSL1 date format: YYYY-MM-DD 00:00:00 or YYYY-M-D 00:00:00
    Handles redundant time suffix as specified.
    """
    if date_str is None or (isinstance(date_str, float) and np.isnan(date_str)):
        return None
    
    str_val = str(date_str).strip()
    if not str_val or str_val in ("-", "", "null", "NULL"):
        return None
    
    # Remove redundant time suffix
    if " 00:00:00" in str_val:
        str_val = str_val.replace(" 00:00:00", "")
    elif " " in str_val:
        str_val = str_val.split(" ")[0]
    
    # Try multiple date formats
    formats = ["%Y-%m-%d", "%Y-%M-%d", "%d/%m/%Y", "%Y/%m/%d"]
    for fmt in formats:
        try:
            return datetime.strptime(str_val, fmt)
        except ValueError:
            continue
    
    return None


def format_date_iso(date_obj: Any) -> str:
    """
    Format date to ISO 8601 (YYYY-MM-DD) per Nexus Protocol.
    """
    if date_obj is None:
        return ""
    if isinstance(date_obj, datetime):
        return date_obj.strftime("%Y-%m-%d")
    if isinstance(date_obj, date):
        return date_obj.strftime("%Y-%m-%d")
    if isinstance(date_obj, str):
        # Remove time portion if present
        if " 00:00:00" in date_obj:
            return date_obj.replace(" 00:00:00", "")
        if " " in date_obj:
            return date_obj.split(" ")[0]
        return date_obj
    return str(date_obj)


def parse_date_dsl2_buddhist(date_str: Any) -> Optional[datetime]:
    """
    Parse DSL2 Buddhist Era date format: DD/MM/YYYY (BE)
    Buddhist Era year = Gregorian year + 543
    """
    if date_str is None or (isinstance(date_str, float) and np.isnan(date_str)):
        return None
    
    str_val = str(date_str).strip()
    if not str_val or str_val in ("-", "", "null", "NULL"):
        return None
    
    try:
        parts = str_val.split("/")
        if len(parts) != 3:
            return None
        
        day = int(parts[0])
        month = int(parts[1])
        be_year = int(parts[2])
        
        # Convert Buddhist Era to Gregorian
        gregorian_year = be_year - 543
        
        # Validate ranges
        if not (1 <= day <= 31 and 1 <= month <= 12 and 1900 <= gregorian_year <= 2100):
            return None
        
        return datetime(gregorian_year, month, day)
    except (ValueError, IndexError):
        return None


def parse_date_payment_schedule(date_str: Any) -> Optional[datetime]:
    """
    Parse Payment Schedule date format.
    Supports: YYYY-MM-DD, DD/MM/YYYY, YYYY/MM/DD
    """
    if date_str is None or (isinstance(date_str, float) and np.isnan(date_str)):
        return None
    
    str_val = str(date_str).strip()
    if not str_val or str_val in ("-", "", "null", "NULL"):
        return None
    
    # Remove time portion if present
    if " " in str_val:
        str_val = str_val.split(" ")[0]
    
    formats = ["%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%m/%d/%Y"]
    for fmt in formats:
        try:
            return datetime.strptime(str_val, fmt)
        except ValueError:
            continue
    
    return None


def detect_header_row_index(file_path: Path, encoding: str, target_columns: List[str]) -> int:
    """
    Detect which row contains the header by looking for target column names.
    Returns 0-based index of the header row.
    """
    try:
        with open(file_path, "r", encoding=encoding, errors="replace") as f:
            for row_idx in range(10):
                line = f.readline()
                if not line:
                    break
                
                for target_col in target_columns:
                    if target_col in line:
                        log_info(f"Header found at row {row_idx + 1} in {file_path.name}")
                        return row_idx
        
        return 0
    except Exception as e:
        log_warn(f"Error detecting header row in {file_path.name}: {e}")
        return 0


# ══════════════════════════════════════════════════════════════════════════════
# FILE DISCOVERY & PARALLEL I/O
# ══════════════════════════════════════════════════════════════════════════════

def discover_files(folder: Path, patterns: List[str] = None) -> List[Path]:
    """
    Discover data files in folder with parallel scanning.
    """
    if patterns is None:
        patterns = ["*.csv", "*.CSV", "*.txt", "*.TXT"]
    
    files = []
    for pattern in patterns:
        files.extend(folder.glob(pattern))
    
    # Sort for deterministic processing
    return sorted(files, key=lambda p: p.name)


def get_file_hash(file_path: Path, chunk_size: int = 8192) -> str:
    """Calculate SHA-256 hash of file for manifest."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            sha256.update(chunk)
    return sha256.hexdigest()[:16]


# ══════════════════════════════════════════════════════════════════════════════
# DATA LOADING: POLARS-FIRST STRATEGY WITH PANDAS FALLBACK
# ══════════════════════════════════════════════════════════════════════════════

def load_dsl1_polars(folder: Path, progress_callback=None) -> pl.LazyFrame:
    """
    Load DSL1 files using Polars for maximum performance.
    DSL1: ~7.43M rows, 7GB, YYYY-MM-DD 00:00:00 format
    
    Extracts required columns:
    - ACC_NO (string, immutable identifier)
    - GROUP_FLAG (for filtering)
    - FIRST_PAYMENT_DATE
    - PRE_BALANCE
    - EXACT_PRE_BALANCE (new column for comparison)
    """
    start_timer("load_dsl1")
    files = discover_files(folder)
    if not files:
        raise FileNotFoundError(f"No data files found in {folder}")
    
    log_recon(f"Discovered {len(files)} file(s) in DSL1 folder")
    
    # Define schema for required columns
    required_cols = ["ACC_NO", "GROUP_FLAG", "FIRST_PAYMENT_DATE", "PRE_BALANCE", "EXACT_PRE_BALANCE"]
    
    lazy_frames = []
    
    for file_path in files:
        file_start = time.time()
        encoding = detect_encoding(file_path)
        log_flux(f"Loading {file_path.name} with encoding: {encoding}")
        
        try:
            polars_encoding = "utf8" if encoding in ["utf-8", "utf-8-sig"] else "utf8"
            
            lf = pl.scan_csv(
                file_path,
                encoding=polars_encoding,
                ignore_errors=True,
                null_values=["", "null", "NULL", "N/A", "-"],
                infer_schema_length=10000,
                low_memory=True,
            )
            
            available_cols = lf.collect_schema().names()
            select_cols = [c for c in required_cols if c in available_cols]
            
            if "ACC_NO" not in select_cols:
                log_fatal(f"Critical column ACC_NO missing in {file_path.name}")
                continue
            
            if "GROUP_FLAG" not in select_cols:
                log_warn(f"GROUP_FLAG column missing in {file_path.name}, will include all records")
            
            lf = lf.select(select_cols)
            
            # Cast ACC_NO to string
            lf = lf.with_columns([
                pl.col("ACC_NO").cast(pl.Utf8).alias("ACC_NO")
            ])
            
            lazy_frames.append(lf)
            
            file_elapsed = time.time() - file_start
            log_flux(f"Prepared {file_path.name} [{file_elapsed:.2f}s]")
            
            if progress_callback:
                progress_callback()
                
        except Exception as e:
            log_warn(f"Polars failed for {file_path.name}: {e}, trying fallback...")
            continue
    
    if not lazy_frames:
        raise ValueError("No valid DSL1 files could be loaded")
    
    combined = pl.concat(lazy_frames)
    
    log_secure(f"DSL1 LazyFrame prepared", "load_dsl1")
    
    return combined


def load_dsl2_polars(folder: Path, progress_callback=None) -> pl.LazyFrame:
    """
    Load DSL2 files using Polars.
    DSL2: ~4M rows, 1-1.5GB, Buddhist Era dates (DD/MM/YYYY BE)
    Header is in the SECOND row (index 1), not the first row.
    
    Extracts required columns:
    - เลขบัญชี (ACC_NO equivalent)
    - วันที่เริ่มชำระหนี้ (FIRST_PAYMENT_DATE equivalent)
    - ยอดหนี้เงินกู้ (PRE_BALANCE equivalent)
    """
    start_timer("load_dsl2")
    files = discover_files(folder)
    if not files:
        raise FileNotFoundError(f"No data files found in {folder}")
    
    log_recon(f"Discovered {len(files)} file(s) in DSL2 folder")
    
    required_cols = ["เลขบัญชี", "วันที่เริ่มชำระหนี้", "ยอดหนี้เงินกู้"]
    
    lazy_frames = []
    
    for file_path in files:
        file_start = time.time()
        encoding = detect_encoding(file_path)
        log_flux(f"Loading {file_path.name} with encoding: {encoding}")
        
        header_row_idx = detect_header_row_index(file_path, encoding, required_cols)
        
        try:
            if header_row_idx > 0 or encoding in THAI_ENCODING_CHAIN:
                df = pd.read_csv(
                    file_path,
                    encoding=encoding,
                    skiprows=header_row_idx,
                    dtype={"เลขบัญชี": str},
                    low_memory=False,
                    on_bad_lines="skip"
                )
                
                available_cols = df.columns.tolist()
                
                col_mapping = {}
                for req_col in required_cols:
                    if req_col in available_cols:
                        col_mapping[req_col] = req_col
                    else:
                        for avail_col in available_cols:
                            if req_col in avail_col or avail_col in req_col:
                                col_mapping[req_col] = avail_col
                                break
                
                if "เลขบัญชี" not in col_mapping:
                    log_warn(f"Column เลขบัญชี not found in {file_path.name}")
                    continue
                
                df_selected = df[[col_mapping[c] for c in required_cols if c in col_mapping]].copy()
                df_selected.columns = [c for c in required_cols if c in col_mapping]
                
                df_selected["เลขบัญชี"] = df_selected["เลขบัญชี"].astype(str)
                
                lf = pl.from_pandas(df_selected).lazy()
                
                lazy_frames.append(lf)
                
                file_elapsed = time.time() - file_start
                log_secure(f"Loaded {file_path.name} via pandas ({len(df_selected):,} rows) [{file_elapsed:.2f}s]")
                
            else:
                lf = pl.scan_csv(
                    file_path,
                    encoding="utf8",
                    ignore_errors=True,
                    null_values=["", "null", "NULL", "N/A", "-"],
                    infer_schema_length=10000,
                    low_memory=True,
                )
                
                available_cols = lf.collect_schema().names()
                
                col_mapping = {}
                for req_col in required_cols:
                    if req_col in available_cols:
                        col_mapping[req_col] = req_col
                    else:
                        for avail_col in available_cols:
                            if req_col in avail_col or avail_col in req_col:
                                col_mapping[req_col] = avail_col
                                break
                
                if "เลขบัญชี" not in col_mapping:
                    log_warn(f"Column เลขบัญชี not found in {file_path.name}")
                    continue
                
                select_exprs = []
                for req_col in required_cols:
                    if req_col in col_mapping:
                        select_exprs.append(pl.col(col_mapping[req_col]).alias(req_col))
                
                lf = lf.select(select_exprs)
                
                lf = lf.with_columns([
                    pl.col("เลขบัญชี").cast(pl.Utf8).alias("เลขบัญชี")
                ])
                
                lazy_frames.append(lf)
                
                file_elapsed = time.time() - file_start
                log_flux(f"Prepared {file_path.name} [{file_elapsed:.2f}s]")
            
            if progress_callback:
                progress_callback()
                
        except Exception as e:
            log_warn(f"Failed to load {file_path.name}: {e}")
            continue
    
    if not lazy_frames:
        raise ValueError("No valid DSL2 files could be loaded")
    
    combined = pl.concat(lazy_frames)
    
    log_secure(f"DSL2 LazyFrame prepared", "load_dsl2")
    
    return combined


def load_payment_schedule_polars(folder: Path, progress_callback=None) -> pl.LazyFrame:
    """
    Load Payment Schedule files using Polars.
    Payment Schedule: ~5.9M rows
    
    Extracts required columns:
    - ACC_NO (Join Key)
    - DUE_PAYMENT_DATE
    - CAPITAL_REMAIN
    """
    start_timer("load_payment_schedule")
    files = discover_files(folder)
    if not files:
        raise FileNotFoundError(f"No data files found in {folder}")
    
    log_recon(f"Discovered {len(files)} file(s) in Payment Schedule folder")
    
    required_cols = ["ACC_NO", "DUE_PAYMENT_DATE", "CAPITAL_REMAIN"]
    
    lazy_frames = []
    
    for file_path in files:
        file_start = time.time()
        encoding = detect_encoding(file_path)
        log_flux(f"Loading {file_path.name} with encoding: {encoding}")
        
        try:
            polars_encoding = "utf8" if encoding in ["utf-8", "utf-8-sig"] else "utf8"
            
            lf = pl.scan_csv(
                file_path,
                encoding=polars_encoding,
                ignore_errors=True,
                null_values=["", "null", "NULL", "N/A", "-"],
                infer_schema_length=10000,
                low_memory=True,
            )
            
            available_cols = lf.collect_schema().names()
            select_cols = [c for c in required_cols if c in available_cols]
            
            if "ACC_NO" not in select_cols:
                log_fatal(f"Critical column ACC_NO missing in {file_path.name}")
                continue
            
            lf = lf.select(select_cols)
            
            lf = lf.with_columns([
                pl.col("ACC_NO").cast(pl.Utf8).alias("ACC_NO")
            ])
            
            lazy_frames.append(lf)
            
            file_elapsed = time.time() - file_start
            log_flux(f"Prepared {file_path.name} [{file_elapsed:.2f}s]")
            
            if progress_callback:
                progress_callback()
                
        except Exception as e:
            log_warn(f"Polars failed for {file_path.name}: {e}")
            # Try pandas fallback
            try:
                df = pd.read_csv(
                    file_path,
                    encoding=encoding,
                    dtype={"ACC_NO": str},
                    low_memory=True,
                    on_bad_lines="skip"
                )
                
                available = [c for c in required_cols if c in df.columns]
                if "ACC_NO" in available:
                    df = df[available].copy()
                    df["ACC_NO"] = df["ACC_NO"].astype(str)
                    lf = pl.from_pandas(df).lazy()
                    lazy_frames.append(lf)
                    log_secure(f"Loaded {file_path.name} via pandas fallback")
            except Exception as e2:
                log_warn(f"Both Polars and Pandas failed for {file_path.name}: {e2}")
                continue
    
    if not lazy_frames:
        raise ValueError("No valid Payment Schedule files could be loaded")
    
    combined = pl.concat(lazy_frames)
    
    log_secure(f"Payment Schedule LazyFrame prepared", "load_payment_schedule")
    
    return combined


def load_dsl1_pandas_fallback(folder: Path) -> pd.DataFrame:
    """Pandas fallback for DSL1 when Polars fails."""
    start_timer("load_dsl1_pandas")
    
    files = discover_files(folder)
    dfs = []
    
    required_cols = ["ACC_NO", "GROUP_FLAG", "FIRST_PAYMENT_DATE", "PRE_BALANCE", "EXACT_PRE_BALANCE"]
    
    for file_path in files:
        file_start = time.time()
        encoding = detect_encoding(file_path)
        
        for enc in [encoding] + ENCODING_CHAIN:
            try:
                df = pd.read_csv(
                    file_path,
                    encoding=enc,
                    usecols=lambda c: c in required_cols,
                    dtype={"ACC_NO": str},
                    low_memory=True,
                    on_bad_lines="skip"
                )
                dfs.append(df)
                file_elapsed = time.time() - file_start
                log_secure(f"Loaded {file_path.name} with pandas ({enc}) [{file_elapsed:.2f}s]")
                break
            except Exception:
                continue
    
    if not dfs:
        raise ValueError("No valid DSL1 files could be loaded with pandas")
    
    result = pd.concat(dfs, ignore_index=True)
    log_secure(f"DSL1 pandas loading complete ({len(result):,} rows)", "load_dsl1_pandas")
    
    return result


def load_dsl2_pandas_fallback(folder: Path) -> pd.DataFrame:
    """Pandas fallback for DSL2 with Thai encoding handling."""
    start_timer("load_dsl2_pandas")
    
    files = discover_files(folder)
    dfs = []
    
    required_cols = ["เลขบัญชี", "วันที่เริ่มชำระหนี้", "ยอดหนี้เงินกู้"]
    
    for file_path in files:
        file_start = time.time()
        encoding = detect_encoding(file_path)
        
        header_row_idx = detect_header_row_index(file_path, encoding, required_cols)
        
        for enc in THAI_ENCODING_CHAIN:
            try:
                df = pd.read_csv(
                    file_path,
                    encoding=enc,
                    skiprows=header_row_idx,
                    dtype={"เลขบัญชี": str},
                    low_memory=True,
                    on_bad_lines="skip"
                )
                
                available = [c for c in required_cols if c in df.columns]
                if "เลขบัญชี" in available:
                    df = df[available].copy()
                    dfs.append(df)
                    file_elapsed = time.time() - file_start
                    log_secure(f"Loaded {file_path.name} with pandas ({enc}, {len(df):,} rows) [{file_elapsed:.2f}s]")
                    break
            except Exception:
                continue
    
    if not dfs:
        raise ValueError("No valid DSL2 files could be loaded with pandas")
    
    result = pd.concat(dfs, ignore_index=True)
    log_secure(f"DSL2 pandas loading complete ({len(result):,} rows)", "load_dsl2_pandas")
    
    return result


def load_payment_schedule_pandas_fallback(folder: Path) -> pd.DataFrame:
    """Pandas fallback for Payment Schedule."""
    start_timer("load_ps_pandas")
    
    files = discover_files(folder)
    dfs = []
    
    required_cols = ["ACC_NO", "DUE_PAYMENT_DATE", "CAPITAL_REMAIN"]
    
    for file_path in files:
        file_start = time.time()
        encoding = detect_encoding(file_path)
        
        for enc in [encoding] + ENCODING_CHAIN:
            try:
                df = pd.read_csv(
                    file_path,
                    encoding=enc,
                    usecols=lambda c: c in required_cols,
                    dtype={"ACC_NO": str},
                    low_memory=True,
                    on_bad_lines="skip"
                )
                dfs.append(df)
                file_elapsed = time.time() - file_start
                log_secure(f"Loaded {file_path.name} with pandas ({enc}) [{file_elapsed:.2f}s]")
                break
            except Exception:
                continue
    
    if not dfs:
        raise ValueError("No valid Payment Schedule files could be loaded with pandas")
    
    result = pd.concat(dfs, ignore_index=True)
    log_secure(f"Payment Schedule pandas loading complete ({len(result):,} rows)", "load_ps_pandas")
    
    return result


# ══════════════════════════════════════════════════════════════════════════════
# RECONCILIATION RESULT CONTAINERS
# ══════════════════════════════════════════════════════════════════════════════

class ReconciliationResult:
    """Container for DSL1 vs DSL2 reconciliation results."""
    
    def __init__(self):
        self.total_dsl1_rows: int = 0
        self.total_dsl1_filtered_rows: int = 0  # After GROUP_FLAG = 1 filter
        self.total_dsl2_rows: int = 0
        self.matched_rows: int = 0
        self.unmatched_dsl1: int = 0
        self.unmatched_dsl2: int = 0
        
        # Discrepancy counts
        self.date_mismatches: int = 0
        self.balance_mismatches: int = 0
        self.both_mismatches: int = 0
        self.perfect_matches: int = 0
        
        # EXACT_PRE_BALANCE comparisons
        self.exact_vs_dsl2_mismatches: int = 0
        self.exact_vs_pre_mismatches: int = 0
        
        # แยกหนี้ (Debt Separation) detection
        self.debt_separation_cases: int = 0
        self.debt_separation_records: List[Dict] = []
        
        # Error margin statistics
        self.balance_errors: np.ndarray = np.array([])
        self.date_diff_days: np.ndarray = np.array([])
        self.exact_vs_dsl2_errors: np.ndarray = np.array([])
        self.exact_vs_pre_errors: np.ndarray = np.array([])
        
        # Detailed error records
        self.error_records: List[Dict] = []
        
        # Timing
        self.start_time: float = 0
        self.end_time: float = 0
    
    @property
    def match_rate(self) -> float:
        if self.total_dsl2_rows == 0:
            return 0.0
        return (self.matched_rows / self.total_dsl2_rows) * 100
    
    @property
    def error_rate(self) -> float:
        if self.matched_rows == 0:
            return 0.0
        total_errors = self.date_mismatches + self.balance_mismatches + self.both_mismatches
        return (total_errors / self.matched_rows) * 100
    
    @property
    def accuracy_rate(self) -> float:
        if self.matched_rows == 0:
            return 0.0
        return (self.perfect_matches / self.matched_rows) * 100
    
    @property
    def balance_error_stats(self) -> Dict[str, float]:
        if self.balance_errors.size == 0:
            return {"mean": 0, "median": 0, "std": 0, "min": 0, "max": 0, "p95": 0, "p99": 0}
        
        arr = self.balance_errors
        return {
            "mean": float(np.mean(arr)),
            "median": float(np.median(arr)),
            "std": float(np.std(arr)),
            "min": float(np.min(arr)),
            "max": float(np.max(arr)),
            "p95": float(np.percentile(arr, 95)),
            "p99": float(np.percentile(arr, 99)),
        }
    
    @property
    def date_diff_stats(self) -> Dict[str, float]:
        if self.date_diff_days.size == 0:
            return {"mean": 0, "median": 0, "std": 0, "min": 0, "max": 0}
        
        arr = self.date_diff_days
        return {
            "mean": float(np.mean(arr)),
            "median": float(np.median(arr)),
            "std": float(np.std(arr)),
            "min": float(np.min(arr)),
            "max": float(np.max(arr)),
        }
    
    @property
    def duration_seconds(self) -> float:
        return self.end_time - self.start_time
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_dsl1_rows": self.total_dsl1_rows,
            "total_dsl1_filtered_rows": self.total_dsl1_filtered_rows,
            "total_dsl2_rows": self.total_dsl2_rows,
            "matched_rows": self.matched_rows,
            "unmatched_dsl1": self.unmatched_dsl1,
            "unmatched_dsl2": self.unmatched_dsl2,
            "date_mismatches": self.date_mismatches,
            "balance_mismatches": self.balance_mismatches,
            "both_mismatches": self.both_mismatches,
            "perfect_matches": self.perfect_matches,
            "exact_vs_dsl2_mismatches": self.exact_vs_dsl2_mismatches,
            "exact_vs_pre_mismatches": self.exact_vs_pre_mismatches,
            "debt_separation_cases": self.debt_separation_cases,
            "match_rate_pct": round(self.match_rate, 2),
            "error_rate_pct": round(self.error_rate, 2),
            "accuracy_rate_pct": round(self.accuracy_rate, 2),
            "balance_error_stats": self.balance_error_stats,
            "date_diff_stats": self.date_diff_stats,
            "duration_seconds": round(self.duration_seconds, 2),
            "error_count": len(self.error_records),
            "debt_separation_count": len(self.debt_separation_records),
        }


class PaymentScheduleResult:
    """Container for Payment Schedule vs DSL2 reconciliation results."""
    
    def __init__(self):
        self.total_ps_rows: int = 0
        self.total_dsl2_rows: int = 0
        self.matched_rows: int = 0
        self.unmatched_ps: int = 0
        self.unmatched_dsl2: int = 0
        
        # Discrepancy counts
        self.date_mismatches: int = 0
        self.balance_mismatches: int = 0
        self.both_mismatches: int = 0
        self.perfect_matches: int = 0
        
        # Error margin statistics
        self.balance_errors: np.ndarray = np.array([])
        self.date_diff_days: np.ndarray = np.array([])
        
        # Detailed error records
        self.error_records: List[Dict] = []
        
        # Timing
        self.start_time: float = 0
        self.end_time: float = 0
    
    @property
    def match_rate(self) -> float:
        if self.total_dsl2_rows == 0:
            return 0.0
        return (self.matched_rows / self.total_dsl2_rows) * 100
    
    @property
    def accuracy_rate(self) -> float:
        if self.matched_rows == 0:
            return 0.0
        return (self.perfect_matches / self.matched_rows) * 100
    
    @property
    def balance_error_stats(self) -> Dict[str, float]:
        if self.balance_errors.size == 0:
            return {"mean": 0, "median": 0, "std": 0, "min": 0, "max": 0, "p95": 0, "p99": 0}
        
        arr = self.balance_errors
        return {
            "mean": float(np.mean(arr)),
            "median": float(np.median(arr)),
            "std": float(np.std(arr)),
            "min": float(np.min(arr)),
            "max": float(np.max(arr)),
            "p95": float(np.percentile(arr, 95)),
            "p99": float(np.percentile(arr, 99)),
        }
    
    @property
    def duration_seconds(self) -> float:
        return self.end_time - self.start_time
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_ps_rows": self.total_ps_rows,
            "total_dsl2_rows": self.total_dsl2_rows,
            "matched_rows": self.matched_rows,
            "unmatched_ps": self.unmatched_ps,
            "unmatched_dsl2": self.unmatched_dsl2,
            "date_mismatches": self.date_mismatches,
            "balance_mismatches": self.balance_mismatches,
            "both_mismatches": self.both_mismatches,
            "perfect_matches": self.perfect_matches,
            "match_rate_pct": round(self.match_rate, 2),
            "accuracy_rate_pct": round(self.accuracy_rate, 2),
            "balance_error_stats": self.balance_error_stats,
            "duration_seconds": round(self.duration_seconds, 2),
            "error_count": len(self.error_records),
        }


class CombinedReconciliationResult:
    """Combined container for all reconciliation results."""
    
    def __init__(self):
        self.dsl1_vs_dsl2: ReconciliationResult = ReconciliationResult()
        self.ps_vs_dsl2: PaymentScheduleResult = PaymentScheduleResult()
        self.generated_at: str = datetime.now().isoformat()
        self.version: str = "3.0.0"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "generated_at": self.generated_at,
            "dsl1_vs_dsl2": self.dsl1_vs_dsl2.to_dict(),
            "ps_vs_dsl2": self.ps_vs_dsl2.to_dict(),
        }


# ══════════════════════════════════════════════════════════════════════════════
# RECONCILIATION ENGINE
# ══════════════════════════════════════════════════════════════════════════════

def reconcile_dsl1_vs_dsl2(
    dsl1_data: pl.DataFrame,
    dsl2_data: pl.DataFrame,
    balance_tolerance: float = 0.01,
    max_error_records: int = 100000,
    progress: Progress = None,
    task_id = None
) -> ReconciliationResult:
    """
    Perform vectorized reconciliation between DSL1 and DSL2 datasets.
    
    IMPORTANT: Only ACC_NO with GROUP_FLAG = 1 are included from DSL1.
    
    Comparison Logic:
    - Join on ACC_NO = เลขบัญชี (WHERE GROUP_FLAG = 1)
    - Compare FIRST_PAYMENT_DATE vs วันที่เริ่มชำระหนี้
    - Compare PRE_BALANCE vs ยอดหนี้เงินกู้
    - Compare EXACT_PRE_BALANCE vs ยอดหนี้เงินกู้
    - Compare EXACT_PRE_BALANCE vs PRE_BALANCE (แยกหนี้ Detection)
    """
    result = ReconciliationResult()
    result.start_time = time.time()
    
    start_timer("reconcile_dsl1_dsl2")
    log_flux("Starting DSL1 vs DSL2 vectorized reconciliation...")
    
    # Record original row counts
    result.total_dsl1_rows = len(dsl1_data)
    result.total_dsl2_rows = len(dsl2_data)
    
    log_info(f"DSL1 total rows (before filter): {result.total_dsl1_rows:,}")
    log_info(f"DSL2 rows: {result.total_dsl2_rows:,}")
    
    total_steps = 12
    current_step = 0
    
    def update_progress():
        nonlocal current_step
        current_step += 1
        if progress and task_id:
            progress.update(task_id, completed=int(current_step / total_steps * 100))
    
    # Filter DSL1 by GROUP_FLAG = 1
    start_timer("filter_group_flag")
    log_flux("Filtering DSL1 by GROUP_FLAG = 1...")
    
    if "GROUP_FLAG" in dsl1_data.columns:
        # Convert GROUP_FLAG to numeric for comparison
        dsl1_filtered = dsl1_data.filter(
            (pl.col("GROUP_FLAG").cast(pl.Int64, strict=False) == 1) |
            (pl.col("GROUP_FLAG").cast(pl.Utf8) == "1")
        )
        result.total_dsl1_filtered_rows = len(dsl1_filtered)
        log_secure(f"DSL1 filtered to {result.total_dsl1_filtered_rows:,} rows (GROUP_FLAG = 1)", "filter_group_flag")
    else:
        log_warn("GROUP_FLAG column not found, using all DSL1 records")
        dsl1_filtered = dsl1_data
        result.total_dsl1_filtered_rows = len(dsl1_filtered)
    
    update_progress()
    
    # Normalize account numbers for joining
    start_timer("normalize")
    log_flux("Normalizing account numbers...")
    
    dsl1_normalized = dsl1_filtered.with_columns([
        pl.col("ACC_NO").str.strip_chars().str.replace_all(r"^0+", "").alias("ACC_NO_NORM")
    ])
    
    dsl2_normalized = dsl2_data.with_columns([
        pl.col("เลขบัญชี").str.strip_chars().str.replace_all(r"^0+", "").alias("ACC_NO_NORM")
    ])
    
    log_info("Account numbers normalized", "normalize")
    update_progress()
    
    # Perform left join (DSL2 as base)
    start_timer("join")
    log_flux("Performing join operation...")
    
    joined = dsl2_normalized.join(
        dsl1_normalized,
        on="ACC_NO_NORM",
        how="left",
        suffix="_dsl1"
    )
    
    log_info("Join operation complete", "join")
    update_progress()
    
    result.matched_rows = joined.filter(pl.col("ACC_NO").is_not_null()).height
    result.unmatched_dsl2 = joined.filter(pl.col("ACC_NO").is_null()).height
    
    log_info(f"Matched rows: {result.matched_rows:,}")
    log_info(f"Unmatched DSL2 rows: {result.unmatched_dsl2:,}")
    update_progress()
    
    # Filter to matched rows only for comparison
    matched = joined.filter(pl.col("ACC_NO").is_not_null())
    
    if matched.height == 0:
        log_warn("No matching records found between datasets!")
        result.end_time = time.time()
        return result
    
    # Convert to pandas for complex date parsing
    start_timer("parse_dates")
    log_flux("Parsing and comparing dates...")
    
    matched_pd = matched.to_pandas()
    update_progress()
    
    # Vectorized date parsing for DSL1
    log_info("Parsing DSL1 dates...")
    matched_pd["DATE_DSL1"] = matched_pd["FIRST_PAYMENT_DATE"].apply(parse_date_dsl1)
    update_progress()
    
    log_info("Parsing DSL2 dates (Buddhist Era conversion)...")
    matched_pd["DATE_DSL2"] = matched_pd["วันที่เริ่มชำระหนี้"].apply(parse_date_dsl2_buddhist)
    
    log_info("Date parsing complete", "parse_dates")
    update_progress()
    
    # Parse balances
    start_timer("parse_balances")
    log_flux("Parsing and comparing balances...")
    
    matched_pd["BAL_DSL1"] = matched_pd["PRE_BALANCE"].apply(safe_float)
    matched_pd["BAL_DSL2"] = matched_pd["ยอดหนี้เงินกู้"].apply(safe_float)
    
    # Parse EXACT_PRE_BALANCE if available
    if "EXACT_PRE_BALANCE" in matched_pd.columns:
        matched_pd["EXACT_BAL"] = matched_pd["EXACT_PRE_BALANCE"].apply(safe_float)
    else:
        matched_pd["EXACT_BAL"] = matched_pd["BAL_DSL1"]  # Fallback
    
    log_info("Balance parsing complete", "parse_balances")
    update_progress()
    
    # Calculate discrepancies
    start_timer("calc_discrepancies")
    log_flux("Calculating discrepancies...")
    
    # Date comparison
    valid_dates_mask = matched_pd["DATE_DSL1"].notna() & matched_pd["DATE_DSL2"].notna()
    matched_pd["DATE_MATCH"] = False
    matched_pd.loc[valid_dates_mask, "DATE_MATCH"] = (
        matched_pd.loc[valid_dates_mask, "DATE_DSL1"] == matched_pd.loc[valid_dates_mask, "DATE_DSL2"]
    )
    
    # Calculate date difference in days
    matched_pd["DATE_DIFF_DAYS"] = 0
    matched_pd.loc[valid_dates_mask, "DATE_DIFF_DAYS"] = (
        (matched_pd.loc[valid_dates_mask, "DATE_DSL2"] - matched_pd.loc[valid_dates_mask, "DATE_DSL1"])
        .apply(lambda x: abs(x.days) if x else 0)
    )
    
    # Balance comparison: PRE_BALANCE vs ยอดหนี้เงินกู้
    matched_pd["BAL_DIFF"] = matched_pd["BAL_DSL2"] - matched_pd["BAL_DSL1"]
    matched_pd["BAL_DIFF_ABS"] = matched_pd["BAL_DIFF"].abs()
    matched_pd["BAL_DIFF_PCT"] = np.where(
        matched_pd["BAL_DSL1"] != 0,
        (matched_pd["BAL_DIFF_ABS"] / matched_pd["BAL_DSL1"].abs()) * 100,
        np.where(matched_pd["BAL_DSL2"] != 0, 100, 0)
    )
    matched_pd["BAL_MATCH"] = matched_pd["BAL_DIFF_ABS"] <= balance_tolerance
    
    # EXACT_PRE_BALANCE vs ยอดหนี้เงินกู้
    matched_pd["EXACT_VS_DSL2_DIFF"] = matched_pd["BAL_DSL2"] - matched_pd["EXACT_BAL"]
    matched_pd["EXACT_VS_DSL2_MATCH"] = matched_pd["EXACT_VS_DSL2_DIFF"].abs() <= balance_tolerance
    
    # EXACT_PRE_BALANCE vs PRE_BALANCE (แยกหนี้ Detection)
    matched_pd["EXACT_VS_PRE_DIFF"] = matched_pd["BAL_DSL1"] - matched_pd["EXACT_BAL"]
    matched_pd["EXACT_VS_PRE_MATCH"] = matched_pd["EXACT_VS_PRE_DIFF"].abs() <= balance_tolerance
    
    # แยกหนี้ Detection: PRE_BALANCE < EXACT_PRE_BALANCE
    matched_pd["IS_DEBT_SEPARATION"] = matched_pd["BAL_DSL1"] < matched_pd["EXACT_BAL"]
    
    log_info("Discrepancy calculation complete", "calc_discrepancies")
    update_progress()
    
    # Categorize discrepancies
    date_only_mismatch = ~matched_pd["DATE_MATCH"] & matched_pd["BAL_MATCH"]
    bal_only_mismatch = matched_pd["DATE_MATCH"] & ~matched_pd["BAL_MATCH"]
    both_mismatch = ~matched_pd["DATE_MATCH"] & ~matched_pd["BAL_MATCH"]
    perfect_match = matched_pd["DATE_MATCH"] & matched_pd["BAL_MATCH"]
    
    result.date_mismatches = int(date_only_mismatch.sum())
    result.balance_mismatches = int(bal_only_mismatch.sum())
    result.both_mismatches = int(both_mismatch.sum())
    result.perfect_matches = int(perfect_match.sum())
    
    # EXACT_PRE_BALANCE comparison counts
    result.exact_vs_dsl2_mismatches = int((~matched_pd["EXACT_VS_DSL2_MATCH"]).sum())
    result.exact_vs_pre_mismatches = int((~matched_pd["EXACT_VS_PRE_MATCH"]).sum())
    
    # แยกหนี้ cases
    result.debt_separation_cases = int(matched_pd["IS_DEBT_SEPARATION"].sum())
    
    # Collect error statistics
    error_mask = ~matched_pd["DATE_MATCH"] | ~matched_pd["BAL_MATCH"]
    error_rows = matched_pd[error_mask]
    
    result.balance_errors = error_rows["BAL_DIFF"].values
    if valid_dates_mask.any():
        result.date_diff_days = error_rows.loc[valid_dates_mask & error_mask, "DATE_DIFF_DAYS"].values.astype(int)
    else:
        result.date_diff_days = np.array([])
    
    result.exact_vs_dsl2_errors = matched_pd[~matched_pd["EXACT_VS_DSL2_MATCH"]]["EXACT_VS_DSL2_DIFF"].values
    result.exact_vs_pre_errors = matched_pd[~matched_pd["EXACT_VS_PRE_MATCH"]]["EXACT_VS_PRE_DIFF"].values
    
    # Collect detailed error records
    start_timer("collect_errors")
    log_flux(f"Collecting error records (max {max_error_records:,})...")
    
    error_sample = error_rows.head(max_error_records)
    
    for _, row in error_sample.iterrows():
        record = {
            "ACC_NO": str(row.get("เลขบัญชี", "")),
            "DATE_DSL1": format_date_iso(row.get("DATE_DSL1", "")),
            "DATE_DSL2": str(row.get("วันที่เริ่มชำระหนี้", "")),
            "DATE_MATCH": bool(row.get("DATE_MATCH", False)),
            "DATE_DIFF_DAYS": int(row.get("DATE_DIFF_DAYS", 0)),
            "BAL_DSL1": float(row.get("BAL_DSL1", 0)),
            "BAL_DSL2": float(row.get("BAL_DSL2", 0)),
            "BAL_MATCH": bool(row.get("BAL_MATCH", False)),
            "BAL_DIFF": float(row.get("BAL_DIFF", 0)),
            "BAL_DIFF_PCT": round(float(row.get("BAL_DIFF_PCT", 0)), 4),
            "EXACT_BAL": float(row.get("EXACT_BAL", 0)),
            "EXACT_VS_DSL2_DIFF": float(row.get("EXACT_VS_DSL2_DIFF", 0)),
            "EXACT_VS_PRE_DIFF": float(row.get("EXACT_VS_PRE_DIFF", 0)),
            "IS_DEBT_SEPARATION": bool(row.get("IS_DEBT_SEPARATION", False)),
        }
        result.error_records.append(record)
    
    # Collect แยกหนี้ records separately
    debt_sep_rows = matched_pd[matched_pd["IS_DEBT_SEPARATION"]].head(max_error_records)
    for _, row in debt_sep_rows.iterrows():
        record = {
            "ACC_NO": str(row.get("เลขบัญชี", "")),
            "PRE_BALANCE": float(row.get("BAL_DSL1", 0)),
            "EXACT_PRE_BALANCE": float(row.get("EXACT_BAL", 0)),
            "DIFFERENCE": float(row.get("EXACT_VS_PRE_DIFF", 0)),
            "DSL2_BALANCE": float(row.get("BAL_DSL2", 0)),
            "REMARK": "แยกหนี้ - PRE_BALANCE < EXACT_PRE_BALANCE",
        }
        result.debt_separation_records.append(record)
    
    log_info(f"Collected {len(result.error_records):,} error records", "collect_errors")
    log_info(f"Collected {len(result.debt_separation_records):,} แยกหนี้ records")
    update_progress()
    
    result.end_time = time.time()
    
    log_secure(f"DSL1 vs DSL2 Reconciliation complete", "reconcile_dsl1_dsl2")
    
    return result


def reconcile_ps_vs_dsl2(
    ps_data: pl.DataFrame,
    dsl2_data: pl.DataFrame,
    balance_tolerance: float = 0.01,
    max_error_records: int = 100000,
    progress: Progress = None,
    task_id = None
) -> PaymentScheduleResult:
    """
    Perform vectorized reconciliation between Payment Schedule and DSL2 datasets.
    
    Comparison Logic:
    - Join on ACC_NO = เลขบัญชี
    - Compare DUE_PAYMENT_DATE vs วันที่เริ่มชำระหนี้
    - Compare CAPITAL_REMAIN vs ยอดหนี้เงินกู้
    """
    result = PaymentScheduleResult()
    result.start_time = time.time()
    
    start_timer("reconcile_ps_dsl2")
    log_flux("Starting Payment Schedule vs DSL2 vectorized reconciliation...")
    
    result.total_ps_rows = len(ps_data)
    result.total_dsl2_rows = len(dsl2_data)
    
    log_info(f"Payment Schedule rows: {result.total_ps_rows:,}")
    log_info(f"DSL2 rows: {result.total_dsl2_rows:,}")
    
    total_steps = 10
    current_step = 0
    
    def update_progress():
        nonlocal current_step
        current_step += 1
        if progress and task_id:
            progress.update(task_id, completed=int(current_step / total_steps * 100))
    
    # Normalize account numbers
    start_timer("normalize_ps")
    log_flux("Normalizing account numbers...")
    
    ps_normalized = ps_data.with_columns([
        pl.col("ACC_NO").str.strip_chars().str.replace_all(r"^0+", "").alias("ACC_NO_NORM")
    ])
    
    dsl2_normalized = dsl2_data.with_columns([
        pl.col("เลขบัญชี").str.strip_chars().str.replace_all(r"^0+", "").alias("ACC_NO_NORM")
    ])
    
    log_info("Account numbers normalized", "normalize_ps")
    update_progress()
    
    # Perform left join (DSL2 as base)
    start_timer("join_ps")
    log_flux("Performing join operation...")
    
    joined = dsl2_normalized.join(
        ps_normalized,
        on="ACC_NO_NORM",
        how="left",
        suffix="_ps"
    )
    
    log_info("Join operation complete", "join_ps")
    update_progress()
    
    result.matched_rows = joined.filter(pl.col("ACC_NO").is_not_null()).height
    result.unmatched_dsl2 = joined.filter(pl.col("ACC_NO").is_null()).height
    
    log_info(f"Matched rows: {result.matched_rows:,}")
    log_info(f"Unmatched DSL2 rows: {result.unmatched_dsl2:,}")
    update_progress()
    
    matched = joined.filter(pl.col("ACC_NO").is_not_null())
    
    if matched.height == 0:
        log_warn("No matching records found between Payment Schedule and DSL2!")
        result.end_time = time.time()
        return result
    
    # Convert to pandas for date parsing
    start_timer("parse_dates_ps")
    log_flux("Parsing and comparing dates...")
    
    matched_pd = matched.to_pandas()
    update_progress()
    
    # Parse dates
    log_info("Parsing Payment Schedule dates...")
    matched_pd["DATE_PS"] = matched_pd["DUE_PAYMENT_DATE"].apply(parse_date_payment_schedule)
    
    log_info("Parsing DSL2 dates (Buddhist Era conversion)...")
    matched_pd["DATE_DSL2"] = matched_pd["วันที่เริ่มชำระหนี้"].apply(parse_date_dsl2_buddhist)
    
    log_info("Date parsing complete", "parse_dates_ps")
    update_progress()
    
    # Parse balances
    start_timer("parse_balances_ps")
    log_flux("Parsing and comparing balances...")
    
    matched_pd["BAL_PS"] = matched_pd["CAPITAL_REMAIN"].apply(safe_float)
    matched_pd["BAL_DSL2"] = matched_pd["ยอดหนี้เงินกู้"].apply(safe_float)
    
    log_info("Balance parsing complete", "parse_balances_ps")
    update_progress()
    
    # Calculate discrepancies
    start_timer("calc_discrepancies_ps")
    log_flux("Calculating discrepancies...")
    
    # Date comparison
    # Filter out dates with unreasonable years (data entry errors like year 2336)
    def is_valid_date_range(dt):
        if pd.isna(dt):
            return False
        try:
            year = dt.year if hasattr(dt, 'year') else pd.Timestamp(dt).year
            return 1900 <= year <= 2100
        except:
            return False
    
    valid_dates_mask = (
        matched_pd["DATE_PS"].notna() & 
        matched_pd["DATE_DSL2"].notna() &
        matched_pd["DATE_PS"].apply(is_valid_date_range) &
        matched_pd["DATE_DSL2"].apply(is_valid_date_range)
    )
    matched_pd["DATE_MATCH"] = False
    matched_pd.loc[valid_dates_mask, "DATE_MATCH"] = (
        matched_pd.loc[valid_dates_mask, "DATE_PS"] == matched_pd.loc[valid_dates_mask, "DATE_DSL2"]
    )
    
    matched_pd["DATE_DIFF_DAYS"] = 0
    try:
        # Convert to datetime64 for vectorized operations (avoids PerformanceWarning)
        date_ps_valid = pd.to_datetime(matched_pd.loc[valid_dates_mask, "DATE_PS"], errors='coerce')
        date_dsl2_valid = pd.to_datetime(matched_pd.loc[valid_dates_mask, "DATE_DSL2"], errors='coerce')
        
        # Vectorized date difference calculation
        date_diff = (date_dsl2_valid - date_ps_valid).dt.days.abs().fillna(0).astype(int)
        matched_pd.loc[valid_dates_mask, "DATE_DIFF_DAYS"] = date_diff.values
    except Exception as e:
        log_warn(f"Date difference calculation error (likely out-of-range dates): {e}")
    
    # Balance comparison
    matched_pd["BAL_DIFF"] = matched_pd["BAL_DSL2"] - matched_pd["BAL_PS"]
    matched_pd["BAL_DIFF_ABS"] = matched_pd["BAL_DIFF"].abs()
    matched_pd["BAL_DIFF_PCT"] = np.where(
        matched_pd["BAL_PS"] != 0,
        (matched_pd["BAL_DIFF_ABS"] / matched_pd["BAL_PS"].abs()) * 100,
        np.where(matched_pd["BAL_DSL2"] != 0, 100, 0)
    )
    matched_pd["BAL_MATCH"] = matched_pd["BAL_DIFF_ABS"] <= balance_tolerance
    
    log_info("Discrepancy calculation complete", "calc_discrepancies_ps")
    update_progress()
    
    # Categorize discrepancies
    date_only_mismatch = ~matched_pd["DATE_MATCH"] & matched_pd["BAL_MATCH"]
    bal_only_mismatch = matched_pd["DATE_MATCH"] & ~matched_pd["BAL_MATCH"]
    both_mismatch = ~matched_pd["DATE_MATCH"] & ~matched_pd["BAL_MATCH"]
    perfect_match = matched_pd["DATE_MATCH"] & matched_pd["BAL_MATCH"]
    
    result.date_mismatches = int(date_only_mismatch.sum())
    result.balance_mismatches = int(bal_only_mismatch.sum())
    result.both_mismatches = int(both_mismatch.sum())
    result.perfect_matches = int(perfect_match.sum())
    
    # Collect error statistics
    error_mask = ~matched_pd["DATE_MATCH"] | ~matched_pd["BAL_MATCH"]
    error_rows = matched_pd[error_mask]
    
    result.balance_errors = error_rows["BAL_DIFF"].values
    if valid_dates_mask.any():
        result.date_diff_days = error_rows.loc[valid_dates_mask & error_mask, "DATE_DIFF_DAYS"].values.astype(int)
    else:
        result.date_diff_days = np.array([])
    
    # Collect detailed error records
    start_timer("collect_errors_ps")
    log_flux(f"Collecting error records (max {max_error_records:,})...")
    
    error_sample = error_rows.head(max_error_records)
    
    for _, row in error_sample.iterrows():
        record = {
            "ACC_NO": str(row.get("เลขบัญชี", "")),
            "DATE_PS": format_date_iso(row.get("DATE_PS", "")),
            "DATE_DSL2": str(row.get("วันที่เริ่มชำระหนี้", "")),
            "DATE_MATCH": bool(row.get("DATE_MATCH", False)),
            "DATE_DIFF_DAYS": int(row.get("DATE_DIFF_DAYS", 0)),
            "BAL_PS": float(row.get("BAL_PS", 0)),
            "BAL_DSL2": float(row.get("BAL_DSL2", 0)),
            "BAL_MATCH": bool(row.get("BAL_MATCH", False)),
            "BAL_DIFF": float(row.get("BAL_DIFF", 0)),
            "BAL_DIFF_PCT": round(float(row.get("BAL_DIFF_PCT", 0)), 4),
        }
        result.error_records.append(record)
    
    log_info(f"Collected {len(result.error_records):,} error records", "collect_errors_ps")
    update_progress()
    
    result.end_time = time.time()
    
    log_secure(f"Payment Schedule vs DSL2 Reconciliation complete", "reconcile_ps_dsl2")
    
    return result


# ══════════════════════════════════════════════════════════════════════════════
# NEXUS v10.0 ARTIFACT GENERATOR
# ══════════════════════════════════════════════════════════════════════════════

def iso_converter(o: Any) -> str:
    """JSON serializer for datetime objects."""
    if isinstance(o, (date, datetime)):
        return o.isoformat().split('T')[0]
    raise TypeError(f"Object of type {type(o)} is not JSON serializable")


def generate_nexus_artifact(
    combined_result: CombinedReconciliationResult,
    output_path: Path,
    progress: Progress = None,
    task_id = None
) -> None:
    """
    Generate the Nexus v10.0 Zenith Artifact.
    
    Features per Nexus Protocol v10.0:
    - Custom CSS Micro-Framework with @layer (NO Tailwind)
    - Hybrid Atmosphere Engine (Three.js + Canvas Fallback)
    - Deep-State i18n (CSS-based language toggling)
    - Native SVG Icons (NO FontAwesome)
    - Titanium-Void Aesthetics
    - Airlock Data Injection (Base64 encoded)
    """
    start_timer("generate_html")
    log_write("Generating Nexus v10.0 Zenith Artifact...")
    
    if progress and task_id:
        progress.update(task_id, completed=10)
    
    # Prepare comprehensive payload
    dsl1_result = combined_result.dsl1_vs_dsl2
    ps_result = combined_result.ps_vs_dsl2
    
    # Calculate quality metrics for radar chart
    quality_metrics = {
        "data_integrity": min(100, dsl1_result.accuracy_rate + 5),
        "match_coverage": dsl1_result.match_rate,
        "date_accuracy": max(0, 100 - (dsl1_result.date_mismatches / max(dsl1_result.matched_rows, 1) * 100)),
        "balance_accuracy": max(0, 100 - (dsl1_result.balance_mismatches / max(dsl1_result.matched_rows, 1) * 100)),
        "processing_velocity": min(100, (dsl1_result.total_dsl1_rows + dsl1_result.total_dsl2_rows) / max(dsl1_result.duration_seconds, 1) / 10000),
    }
    
    # Prepare scatter plot data (balance errors vs date differences)
    scatter_data = []
    for i, record in enumerate(dsl1_result.error_records[:500]):
        scatter_data.append({
            "x": record.get("BAL_DIFF", 0),
            "y": record.get("DATE_DIFF_DAYS", 0),
            "acc_no": record.get("ACC_NO", ""),
        })
    
    # Prepare histogram data for balance errors
    histogram_data = {"values": [], "edges": []}
    if dsl1_result.balance_errors.size > 0:
        try:
            errors_arr = np.asanyarray(dsl1_result.balance_errors)
            abs_errors = np.abs(errors_arr)
            limit = np.percentile(abs_errors, 99)
            filtered_errors = errors_arr[abs_errors < limit]
            
            if filtered_errors.size > 0:
                hist_values, hist_edges = np.histogram(filtered_errors, bins=50)
                histogram_data = {
                    "values": hist_values.tolist(),
                    "edges": hist_edges.tolist()
                }
        except Exception as e:
            log_warn(f"Histogram generation failed: {e}")
    
    # Prepare PS histogram data
    ps_histogram_data = {"values": [], "edges": []}
    if ps_result.balance_errors.size > 0:
        try:
            errors_arr = np.asanyarray(ps_result.balance_errors)
            abs_errors = np.abs(errors_arr)
            limit = np.percentile(abs_errors, 99)
            filtered_errors = errors_arr[abs_errors < limit]
            
            if filtered_errors.size > 0:
                hist_values, hist_edges = np.histogram(filtered_errors, bins=50)
                ps_histogram_data = {
                    "values": hist_values.tolist(),
                    "edges": hist_edges.tolist()
                }
        except Exception:
            pass
    
    if progress and task_id:
        progress.update(task_id, completed=30)
    
    # Build payload
    payload = {
        "version": combined_result.version,
        "generated_at": combined_result.generated_at,
        "stats": {
            "dsl1_vs_dsl2": dsl1_result.to_dict(),
            "ps_vs_dsl2": ps_result.to_dict(),
            "total_rows": dsl1_result.total_dsl1_rows + dsl1_result.total_dsl2_rows + ps_result.total_ps_rows,
            "error_count": len(dsl1_result.error_records) + len(ps_result.error_records),
        },
        "errors": {
            "dsl1_vs_dsl2": dsl1_result.error_records[:1000],
            "ps_vs_dsl2": ps_result.error_records[:1000],
            "debt_separation": dsl1_result.debt_separation_records[:500],
        },
        "viz": {
            "radar": [
                round(quality_metrics["data_integrity"], 1),
                round(quality_metrics["match_coverage"], 1),
                round(quality_metrics["date_accuracy"], 1),
                round(quality_metrics["balance_accuracy"], 1),
                round(quality_metrics["processing_velocity"], 1),
            ],
            "scatter": scatter_data,
            "histogram_dsl1": histogram_data,
            "histogram_ps": ps_histogram_data,
            "pie_dsl1": {
                "perfect": dsl1_result.perfect_matches,
                "date_only": dsl1_result.date_mismatches,
                "balance_only": dsl1_result.balance_mismatches,
                "both": dsl1_result.both_mismatches,
            },
            "pie_ps": {
                "perfect": ps_result.perfect_matches,
                "date_only": ps_result.date_mismatches,
                "balance_only": ps_result.balance_mismatches,
                "both": ps_result.both_mismatches,
            },
        },
        "system": get_system_stats(),
    }
    
    if progress and task_id:
        progress.update(task_id, completed=50)
    
    # AIRLOCK: Serialize -> Base64 Encode
    log_write("Applying Airlock data injection...")
    json_bytes = json.dumps(payload, default=iso_converter).encode('utf-8')
    b64_data = base64.b64encode(json_bytes).decode('utf-8')
    
    if progress and task_id:
        progress.update(task_id, completed=60)
    
    log_write("Building HTML content...")
    
    # Generate the Nexus v10.0 HTML
    html_content = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NEXUS ZENITH | DSL1 ↔ DSL2 ↔ Payment Schedule Reconciliation</title>
    
    <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700;900&family=Inter:wght@300;400;600&family=JetBrains+Mono:wght@400;700&family=Sarabun:wght@400;600&display=swap" rel="stylesheet">
    
    <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/d3@7"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>

    <style>
        /* ═══════════════════════════════════════════════════════════════════════
           NEXUS MICRO-FRAMEWORK v10.0 - TITANIUM-VOID AESTHETICS
           NO TAILWIND - Custom CSS Layers Only
           ═══════════════════════════════════════════════════════════════════════ */
        @layer base, layout, components, utilities, animations;

        @layer base {{
            :root {{
                --space-void: #050505;
                --space-deep: #0a0a0f;
                --titanium: #86868b;
                --silver: #f5f5f7;
                --neon-core: #3b82f6;
                --neon-accent: #06b6d4;
                --accent-gold: #f59e0b;
                --peach-fuzz: #FFBE98;
                --success: #10b981;
                --danger: #ef4444;
                --warning: #f59e0b;
                --violet: #8b5cf6;
                --glass-border: rgba(255, 255, 255, 0.08);
                --glass-bg: rgba(20, 20, 20, 0.7);
                --ease-out: cubic-bezier(0.16, 1, 0.3, 1);
            }}
            
            * {{ box-sizing: border-box; margin: 0; padding: 0; }}
            
            body {{
                background: var(--space-void);
                color: var(--silver);
                font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
                overflow-x: hidden;
                min-height: 100vh;
            }}
            
            /* Deep-State i18n Logic */
            [lang="th"] {{ display: none; }}
            body[data-lang="th"] [lang="en"] {{ display: none; }}
            body[data-lang="th"] [lang="th"] {{ display: block; font-family: 'Sarabun', sans-serif; }}
            
            ::-webkit-scrollbar {{ width: 8px; height: 8px; }}
            ::-webkit-scrollbar-track {{ background: var(--space-deep); }}
            ::-webkit-scrollbar-thumb {{ background: var(--titanium); border-radius: 4px; }}
            ::-webkit-scrollbar-thumb:hover {{ background: var(--neon-core); }}
            
            a {{ color: var(--neon-core); text-decoration: none; }}
            a:hover {{ text-decoration: underline; }}
        }}

        @layer layout {{
            .container {{ max-width: 1600px; margin: 0 auto; padding: 0 1.5rem; position: relative; z-index: 10; }}
            .grid {{ display: grid; gap: 1.5rem; }}
            .grid-cols-1 {{ grid-template-columns: 1fr; }}
            .grid-cols-2 {{ grid-template-columns: repeat(2, 1fr); }}
            .grid-cols-3 {{ grid-template-columns: repeat(3, 1fr); }}
            .grid-cols-4 {{ grid-template-columns: repeat(4, 1fr); }}
            .grid-cols-5 {{ grid-template-columns: repeat(5, 1fr); }}
            .flex {{ display: flex; }}
            .flex-col {{ flex-direction: column; }}
            .flex-wrap {{ flex-wrap: wrap; }}
            .justify-between {{ justify-content: space-between; }}
            .justify-center {{ justify-content: center; }}
            .items-center {{ align-items: center; }}
            .gap-2 {{ gap: 0.5rem; }}
            .gap-4 {{ gap: 1rem; }}
            .gap-6 {{ gap: 1.5rem; }}
            .h-screen {{ height: 100vh; }}
            .w-full {{ width: 100%; }}
            .relative {{ position: relative; }}
            .absolute {{ position: absolute; }}
            .fixed {{ position: fixed; }}
            .inset-0 {{ top: 0; right: 0; bottom: 0; left: 0; }}
            .z-0 {{ z-index: 0; }}
            .z-10 {{ z-index: 10; }}
            .z-50 {{ z-index: 50; }}
            .z-9999 {{ z-index: 9999; }}
            .p-2 {{ padding: 0.5rem; }}
            .p-4 {{ padding: 1rem; }}
            .p-6 {{ padding: 1.5rem; }}
            .p-8 {{ padding: 2rem; }}
            .px-4 {{ padding-left: 1rem; padding-right: 1rem; }}
            .py-2 {{ padding-top: 0.5rem; padding-bottom: 0.5rem; }}
            .py-8 {{ padding-top: 2rem; padding-bottom: 2rem; }}
            .py-12 {{ padding-top: 3rem; padding-bottom: 3rem; }}
            .m-4 {{ margin: 1rem; }}
            .mb-2 {{ margin-bottom: 0.5rem; }}
            .mb-4 {{ margin-bottom: 1rem; }}
            .mb-6 {{ margin-bottom: 1.5rem; }}
            .mb-8 {{ margin-bottom: 2rem; }}
            .mt-2 {{ margin-top: 0.5rem; }}
            .mt-4 {{ margin-top: 1rem; }}
            .ml-2 {{ margin-left: 0.5rem; }}
            .mr-2 {{ margin-right: 0.5rem; }}
            .hidden {{ display: none !important; }}
            .overflow-auto {{ overflow: auto; }}
            .overflow-x-auto {{ overflow-x: auto; }}
            .overflow-y-auto {{ overflow-y: auto; }}
            .max-h-500 {{ max-height: 500px; }}
            .sticky {{ position: sticky; }}
            .top-0 {{ top: 0; }}
            .top-4 {{ top: 1rem; }}
            
            @media (max-width: 1024px) {{
                .grid-cols-4, .grid-cols-5 {{ grid-template-columns: repeat(2, 1fr); }}
                .grid-cols-3 {{ grid-template-columns: 1fr; }}
            }}
            @media (max-width: 768px) {{
                .grid-cols-4, .grid-cols-5, .grid-cols-3, .grid-cols-2 {{ grid-template-columns: 1fr; }}
            }}
        }}

        @layer components {{
            /* Glass Panel */
            .glass-panel {{
                background: var(--glass-bg);
                backdrop-filter: blur(20px);
                -webkit-backdrop-filter: blur(20px);
                border: 1px solid var(--glass-border);
                border-radius: 16px;
                box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
                transition: transform 0.3s var(--ease-out), border-color 0.3s;
            }}
            .glass-panel:hover {{
                transform: translateY(-4px);
                border-color: rgba(255, 255, 255, 0.2);
            }}
            
            /* Stat Card */
            .stat-card {{
                position: relative;
                overflow: hidden;
            }}
            .stat-card::before {{
                content: '';
                position: absolute;
                top: 0;
                left: 0;
                right: 0;
                height: 3px;
                background: linear-gradient(90deg, var(--neon-core), var(--neon-accent));
            }}
            .stat-card.danger::before {{
                background: linear-gradient(90deg, var(--danger), var(--warning));
            }}
            .stat-card.success::before {{
                background: linear-gradient(90deg, var(--success), var(--neon-accent));
            }}
            .stat-card.warning::before {{
                background: linear-gradient(90deg, var(--warning), var(--peach-fuzz));
            }}
            
            .stat-value {{
                font-size: 2.5rem;
                font-weight: 700;
                font-family: 'JetBrains Mono', monospace;
                line-height: 1.2;
            }}
            .stat-label {{
                font-size: 0.7rem;
                text-transform: uppercase;
                letter-spacing: 0.1em;
                color: var(--titanium);
                font-weight: 600;
            }}
            
            /* Buttons */
            .btn {{
                display: inline-flex;
                align-items: center;
                gap: 0.5rem;
                padding: 0.75rem 1.5rem;
                background: linear-gradient(135deg, var(--neon-core), var(--violet));
                color: white;
                border-radius: 8px;
                font-weight: 600;
                font-family: 'Orbitron', sans-serif;
                font-size: 0.85rem;
                transition: all 0.3s;
                cursor: pointer;
                border: 1px solid transparent;
                text-transform: uppercase;
                letter-spacing: 0.05em;
            }}
            .btn:hover {{
                box-shadow: 0 0 20px rgba(59, 130, 246, 0.5);
                transform: translateY(-2px);
            }}
            .btn-secondary {{
                background: transparent;
                border: 1px solid var(--glass-border);
            }}
            .btn-secondary:hover {{
                border-color: var(--neon-core);
                background: rgba(59, 130, 246, 0.1);
            }}
            
            /* Data Table */
            .data-table {{
                width: 100%;
                border-collapse: collapse;
                font-size: 0.85rem;
            }}
            .data-table th {{
                text-align: left;
                padding: 1rem;
                color: var(--titanium);
                border-bottom: 1px solid var(--glass-border);
                text-transform: uppercase;
                font-size: 0.7rem;
                letter-spacing: 0.05em;
                font-weight: 600;
                background: rgba(59, 130, 246, 0.1);
                position: sticky;
                top: 0;
                z-index: 10;
            }}
            .data-table td {{
                padding: 0.75rem 1rem;
                border-bottom: 1px solid rgba(255, 255, 255, 0.05);
                font-family: 'JetBrains Mono', monospace;
                font-size: 0.8rem;
            }}
            .data-table tr:hover {{
                background: rgba(255, 255, 255, 0.02);
            }}
            .data-table tr.error-row {{
                border-left: 3px solid var(--danger);
            }}
            .data-table tr.warning-row {{
                border-left: 3px solid var(--warning);
            }}
            
            /* Badges */
            .badge {{
                display: inline-block;
                padding: 4px 10px;
                border-radius: 99px;
                font-size: 0.65rem;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.05em;
            }}
            .badge-success {{
                background: rgba(16, 185, 129, 0.2);
                color: var(--success);
                border: 1px solid rgba(16, 185, 129, 0.3);
            }}
            .badge-danger {{
                background: rgba(239, 68, 68, 0.2);
                color: var(--danger);
                border: 1px solid rgba(239, 68, 68, 0.3);
            }}
            .badge-warning {{
                background: rgba(245, 158, 11, 0.2);
                color: var(--warning);
                border: 1px solid rgba(245, 158, 11, 0.3);
            }}
            .badge-info {{
                background: rgba(6, 182, 212, 0.2);
                color: var(--neon-accent);
                border: 1px solid rgba(6, 182, 212, 0.3);
            }}
            
            /* Slide Panel */
            .slide-panel {{
                position: fixed;
                top: 0;
                right: 0;
                width: 100%;
                max-width: 520px;
                height: 100%;
                background: #0a0a0a;
                border-left: 1px solid var(--glass-border);
                transform: translateX(100%);
                transition: transform 0.5s var(--ease-out);
                z-index: 2000;
                overflow-y: auto;
            }}
            .slide-panel.open {{
                transform: translateX(0);
            }}
            .slide-panel-overlay {{
                position: fixed;
                inset: 0;
                background: rgba(0, 0, 0, 0.6);
                z-index: 1999;
                opacity: 0;
                pointer-events: none;
                transition: opacity 0.3s ease;
            }}
            .slide-panel-overlay.open {{
                opacity: 1;
                pointer-events: auto;
            }}
            
            /* Chart Container */
            .chart-container {{
                position: relative;
                height: 320px;
                width: 100%;
            }}
            
            /* Progress Bar */
            .progress-bar {{
                height: 8px;
                background: rgba(255, 255, 255, 0.1);
                border-radius: 4px;
                overflow: hidden;
            }}
            .progress-fill {{
                height: 100%;
                border-radius: 4px;
                transition: width 1s var(--ease-out);
            }}
            
            /* Tabs */
            .tab-container {{
                display: flex;
                gap: 0;
                border-bottom: 1px solid var(--glass-border);
                margin-bottom: 1.5rem;
            }}
            .tab-btn {{
                padding: 1rem 1.5rem;
                background: transparent;
                border: none;
                color: var(--titanium);
                font-family: 'Orbitron', sans-serif;
                font-size: 0.85rem;
                cursor: pointer;
                transition: all 0.3s;
                border-bottom: 2px solid transparent;
                text-transform: uppercase;
                letter-spacing: 0.05em;
            }}
            .tab-btn:hover {{
                color: var(--silver);
            }}
            .tab-btn.active {{
                color: var(--neon-core);
                border-bottom-color: var(--neon-core);
            }}
            .tab-content {{
                display: none;
            }}
            .tab-content.active {{
                display: block;
            }}
            
            /* Section Headers */
            .section-header {{
                font-family: 'Orbitron', sans-serif;
                font-size: 1.1rem;
                font-weight: 700;
                letter-spacing: 0.05em;
                margin-bottom: 1rem;
                display: flex;
                align-items: center;
                gap: 0.75rem;
            }}
            .section-header .icon {{
                width: 24px;
                height: 24px;
                color: var(--neon-core);
            }}
            
            /* Gradient Text */
            .gradient-text {{
                background: linear-gradient(135deg, var(--neon-core), var(--neon-accent));
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                background-clip: text;
            }}
            .gradient-text-gold {{
                background: linear-gradient(135deg, var(--accent-gold), var(--peach-fuzz));
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                background-clip: text;
            }}
            
            /* Loading Overlay */
            .loading-overlay {{
                position: fixed;
                inset: 0;
                z-index: 9999;
                background: var(--space-void);
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                transition: opacity 0.5s, visibility 0.5s;
            }}
            .loading-overlay.hidden {{
                opacity: 0;
                visibility: hidden;
                pointer-events: none;
            }}
            .loading-spinner {{
                width: 64px;
                height: 64px;
                border: 4px solid rgba(255, 255, 255, 0.1);
                border-top-color: var(--peach-fuzz);
                border-radius: 50%;
                animation: spin 1s linear infinite;
                margin-bottom: 1rem;
            }}
            .loading-text {{
                font-family: 'Orbitron', sans-serif;
                font-size: 1.2rem;
                color: var(--peach-fuzz);
                letter-spacing: 0.2em;
                animation: pulse 2s ease-in-out infinite;
            }}
            
            /* Cosmic Fog Overlay */
            .cosmic-fog {{
                position: fixed;
                inset: 0;
                z-index: 1;
                pointer-events: none;
                background: radial-gradient(ellipse at center, transparent 0%, var(--space-void) 80%);
            }}
        }}

        @layer utilities {{
            .text-xs {{ font-size: 0.75rem; }}
            .text-sm {{ font-size: 0.875rem; }}
            .text-lg {{ font-size: 1.125rem; }}
            .text-xl {{ font-size: 1.25rem; }}
            .text-2xl {{ font-size: 1.5rem; }}
            .text-3xl {{ font-size: 1.875rem; }}
            .text-4xl {{ font-size: 2.25rem; }}
            .font-mono {{ font-family: 'JetBrains Mono', monospace; }}
            .font-orbitron {{ font-family: 'Orbitron', sans-serif; }}
            .font-bold {{ font-weight: 700; }}
            .font-medium {{ font-weight: 500; }}
            .text-center {{ text-align: center; }}
            .text-right {{ text-align: right; }}
            .uppercase {{ text-transform: uppercase; }}
            .tracking-wide {{ letter-spacing: 0.05em; }}
            .tracking-wider {{ letter-spacing: 0.1em; }}
            .tracking-widest {{ letter-spacing: 0.2em; }}
            .text-titanium {{ color: var(--titanium); }}
            .text-silver {{ color: var(--silver); }}
            .text-neon {{ color: var(--neon-core); }}
            .text-success {{ color: var(--success); }}
            .text-danger {{ color: var(--danger); }}
            .text-warning {{ color: var(--warning); }}
            .text-peach {{ color: var(--peach-fuzz); }}
            .text-gold {{ color: var(--accent-gold); }}
            .bg-void {{ background: var(--space-void); }}
            .bg-deep {{ background: var(--space-deep); }}
            .rounded {{ border-radius: 8px; }}
            .rounded-lg {{ border-radius: 12px; }}
            .rounded-xl {{ border-radius: 16px; }}
            .rounded-full {{ border-radius: 9999px; }}
            .border {{ border: 1px solid var(--glass-border); }}
            .border-danger {{ border-color: rgba(239, 68, 68, 0.4); }}
            .border-success {{ border-color: rgba(16, 185, 129, 0.4); }}
            .border-warning {{ border-color: rgba(245, 158, 11, 0.4); }}
            .opacity-50 {{ opacity: 0.5; }}
            .opacity-70 {{ opacity: 0.7; }}
            .pointer-events-none {{ pointer-events: none; }}
            .cursor-pointer {{ cursor: pointer; }}
            .select-none {{ user-select: none; }}
            .whitespace-nowrap {{ white-space: nowrap; }}
            .truncate {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
        }}

        @layer animations {{
            .reveal {{
                opacity: 0;
                transform: translateY(30px);
                transition: all 0.6s var(--ease-out);
            }}
            .reveal.active {{
                opacity: 1;
                transform: translateY(0);
            }}
            
            @keyframes spin {{
                to {{ transform: rotate(360deg); }}
            }}
            
            @keyframes pulse {{
                0%, 100% {{ opacity: 1; }}
                50% {{ opacity: 0.5; }}
            }}
            
            @keyframes float {{
                0%, 100% {{ transform: translateY(0); }}
                50% {{ transform: translateY(-10px); }}
            }}
            
            .animate-spin {{ animation: spin 1s linear infinite; }}
            .animate-pulse {{ animation: pulse 2s ease-in-out infinite; }}
            .animate-float {{ animation: float 3s ease-in-out infinite; }}
        }}
    </style>
</head>
<body data-lang="en">
    <!-- Antigravity Canvas (Three.js / Canvas Fallback) -->
    <canvas id="antigravity-canvas" class="fixed inset-0 z-0"></canvas>
    
    <!-- Cosmic Fog Overlay -->
    <div class="cosmic-fog"></div>
    
    <!-- Loading Overlay -->
    <div id="loading-overlay" class="loading-overlay">
        <div class="loading-spinner"></div>
        <div class="loading-text">INITIALIZING NEXUS...</div>
    </div>
    
    <!-- Main Content -->
    <div class="relative z-10">
        <!-- Header -->
        <header class="glass-panel m-4 p-4 sticky top-4 z-50 flex justify-between items-center">
            <div class="flex items-center gap-4">
                <div id="logo-slot" class="text-neon"></div>
                <div>
                    <h1 class="font-orbitron text-xl font-bold tracking-wide text-silver">
                        NEXUS // <span class="gradient-text-gold">ZENITH</span>
                    </h1>
                    <p class="text-xs text-titanium tracking-wide">
                        <span lang="en">DSL1 ↔ DSL2 ↔ Payment Schedule Reconciliation</span>
                        <span lang="th">การกระทบยอด DSL1 ↔ DSL2 ↔ ตารางชำระหนี้</span>
                    </p>
                </div>
            </div>
            <nav class="flex gap-4 items-center">
                <span class="text-xs text-titanium font-mono" id="generated-time"></span>
                <button class="btn btn-secondary" onclick="APP.toggleLang()">
                    <span lang="en">EN / TH</span>
                    <span lang="th">EN / TH</span>
                </button>
            </nav>
        </header>
        
        <!-- Main Container -->
        <main class="container py-8">
            <!-- Summary Stats Row -->
            <section class="grid grid-cols-5 gap-4 mb-8 reveal">
                <div class="glass-panel stat-card p-4">
                    <div class="stat-label">
                        <span lang="en">Total Records</span>
                        <span lang="th">ระเบียนทั้งหมด</span>
                    </div>
                    <div class="stat-value text-silver" id="stat-total">--</div>
                </div>
                <div class="glass-panel stat-card success p-4">
                    <div class="stat-label">
                        <span lang="en">Matched</span>
                        <span lang="th">ตรงกัน</span>
                    </div>
                    <div class="stat-value text-success" id="stat-matched">--</div>
                </div>
                <div class="glass-panel stat-card danger p-4 border-danger">
                    <div class="stat-label">
                        <span lang="en">Anomalies</span>
                        <span lang="th">ความผิดปกติ</span>
                    </div>
                    <div class="stat-value text-danger" id="stat-errors">--</div>
                </div>
                <div class="glass-panel stat-card warning p-4 border-warning">
                    <div class="stat-label">
                        <span lang="en">Debt Separation (แยกหนี้)</span>
                        <span lang="th">แยกหนี้</span>
                    </div>
                    <div class="stat-value text-warning" id="stat-debt-sep">--</div>
                </div>
                <div class="glass-panel stat-card p-4">
                    <div class="stat-label">
                        <span lang="en">Accuracy Rate</span>
                        <span lang="th">อัตราความถูกต้อง</span>
                    </div>
                    <div class="stat-value gradient-text" id="stat-accuracy">--</div>
                </div>
            </section>
            
            <!-- Tabs for Different Comparisons -->
            <section class="glass-panel p-6 mb-8 reveal">
                <div class="tab-container">
                    <button class="tab-btn active" data-tab="dsl1-dsl2">
                        <span lang="en">DSL1 vs DSL2</span>
                        <span lang="th">DSL1 เทียบ DSL2</span>
                    </button>
                    <button class="tab-btn" data-tab="ps-dsl2">
                        <span lang="en">Payment Schedule vs DSL2</span>
                        <span lang="th">ตารางชำระหนี้ เทียบ DSL2</span>
                    </button>
                    <button class="tab-btn" data-tab="debt-separation">
                        <span lang="en">Debt Separation (แยกหนี้)</span>
                        <span lang="th">แยกหนี้</span>
                    </button>
                </div>
                
                <!-- DSL1 vs DSL2 Tab -->
                <div class="tab-content active" id="tab-dsl1-dsl2">
                    <div class="grid grid-cols-4 gap-4 mb-6">
                        <div class="p-4 rounded-lg" style="background: rgba(59, 130, 246, 0.1)">
                            <div class="text-xs text-titanium uppercase tracking-wide mb-1">
                                <span lang="en">DSL1 Rows (GROUP_FLAG=1)</span>
                                <span lang="th">แถว DSL1 (GROUP_FLAG=1)</span>
                            </div>
                            <div class="text-2xl font-mono font-bold text-neon" id="dsl1-rows">--</div>
                        </div>
                        <div class="p-4 rounded-lg" style="background: rgba(6, 182, 212, 0.1)">
                            <div class="text-xs text-titanium uppercase tracking-wide mb-1">
                                <span lang="en">DSL2 Rows</span>
                                <span lang="th">แถว DSL2</span>
                            </div>
                            <div class="text-2xl font-mono font-bold" style="color: var(--neon-accent)" id="dsl2-rows">--</div>
                        </div>
                        <div class="p-4 rounded-lg" style="background: rgba(16, 185, 129, 0.1)">
                            <div class="text-xs text-titanium uppercase tracking-wide mb-1">
                                <span lang="en">Match Rate</span>
                                <span lang="th">อัตราการจับคู่</span>
                            </div>
                            <div class="text-2xl font-mono font-bold text-success" id="dsl1-match-rate">--</div>
                        </div>
                        <div class="p-4 rounded-lg" style="background: rgba(239, 68, 68, 0.1)">
                            <div class="text-xs text-titanium uppercase tracking-wide mb-1">
                                <span lang="en">Error Rate</span>
                                <span lang="th">อัตราข้อผิดพลาด</span>
                            </div>
                            <div class="text-2xl font-mono font-bold text-danger" id="dsl1-error-rate">--</div>
                        </div>
                    </div>
                    
                    <div class="grid grid-cols-3 gap-4 mb-6">
                        <div class="p-4 rounded border">
                            <div class="flex justify-between items-center mb-2">
                                <span class="text-sm text-titanium">
                                    <span lang="en">Date Mismatches Only</span>
                                    <span lang="th">วันที่ไม่ตรงเท่านั้น</span>
                                </span>
                                <span class="text-xl font-mono font-bold text-warning" id="dsl1-date-mismatch">--</span>
                            </div>
                            <div class="progress-bar">
                                <div class="progress-fill" id="dsl1-date-progress" style="width: 0%; background: var(--warning)"></div>
                            </div>
                        </div>
                        <div class="p-4 rounded border">
                            <div class="flex justify-between items-center mb-2">
                                <span class="text-sm text-titanium">
                                    <span lang="en">Balance Mismatches Only</span>
                                    <span lang="th">ยอดเงินไม่ตรงเท่านั้น</span>
                                </span>
                                <span class="text-xl font-mono font-bold text-danger" id="dsl1-bal-mismatch">--</span>
                            </div>
                            <div class="progress-bar">
                                <div class="progress-fill" id="dsl1-bal-progress" style="width: 0%; background: var(--danger)"></div>
                            </div>
                        </div>
                        <div class="p-4 rounded border">
                            <div class="flex justify-between items-center mb-2">
                                <span class="text-sm text-titanium">
                                    <span lang="en">Both Mismatched</span>
                                    <span lang="th">ทั้งสองไม่ตรง</span>
                                </span>
                                <span class="text-xl font-mono font-bold" style="color: var(--violet)" id="dsl1-both-mismatch">--</span>
                            </div>
                            <div class="progress-bar">
                                <div class="progress-fill" id="dsl1-both-progress" style="width: 0%; background: linear-gradient(90deg, var(--warning), var(--danger))"></div>
                            </div>
                        </div>
                    </div>
                    
                    <!-- EXACT_PRE_BALANCE Comparison Section -->
                    <div class="p-4 rounded-lg mb-6" style="background: rgba(255, 190, 152, 0.1); border: 1px solid rgba(255, 190, 152, 0.3)">
                        <h4 class="font-orbitron text-sm font-bold text-peach mb-4">
                            <span lang="en">EXACT_PRE_BALANCE Analysis</span>
                            <span lang="th">การวิเคราะห์ EXACT_PRE_BALANCE</span>
                        </h4>
                        <div class="grid grid-cols-2 gap-4">
                            <div>
                                <div class="text-xs text-titanium mb-1">
                                    <span lang="en">EXACT_PRE_BALANCE vs ยอดหนี้เงินกู้ (DSL2) Mismatches</span>
                                    <span lang="th">EXACT_PRE_BALANCE เทียบ ยอดหนี้เงินกู้ ไม่ตรง</span>
                                </div>
                                <div class="text-2xl font-mono font-bold text-peach" id="exact-vs-dsl2">--</div>
                            </div>
                            <div>
                                <div class="text-xs text-titanium mb-1">
                                    <span lang="en">EXACT_PRE_BALANCE vs PRE_BALANCE Mismatches</span>
                                    <span lang="th">EXACT_PRE_BALANCE เทียบ PRE_BALANCE ไม่ตรง</span>
                                </div>
                                <div class="text-2xl font-mono font-bold text-gold" id="exact-vs-pre">--</div>
                            </div>
                        </div>
                    </div>
                </div>
                
                <!-- Payment Schedule vs DSL2 Tab -->
                <div class="tab-content" id="tab-ps-dsl2">
                    <div class="grid grid-cols-4 gap-4 mb-6">
                        <div class="p-4 rounded-lg" style="background: rgba(139, 92, 246, 0.1)">
                            <div class="text-xs text-titanium uppercase tracking-wide mb-1">
                                <span lang="en">Payment Schedule Rows</span>
                                <span lang="th">แถวตารางชำระหนี้</span>
                            </div>
                            <div class="text-2xl font-mono font-bold" style="color: var(--violet)" id="ps-rows">--</div>
                        </div>
                        <div class="p-4 rounded-lg" style="background: rgba(6, 182, 212, 0.1)">
                            <div class="text-xs text-titanium uppercase tracking-wide mb-1">
                                <span lang="en">DSL2 Rows</span>
                                <span lang="th">แถว DSL2</span>
                            </div>
                            <div class="text-2xl font-mono font-bold" style="color: var(--neon-accent)" id="ps-dsl2-rows">--</div>
                        </div>
                        <div class="p-4 rounded-lg" style="background: rgba(16, 185, 129, 0.1)">
                            <div class="text-xs text-titanium uppercase tracking-wide mb-1">
                                <span lang="en">Match Rate</span>
                                <span lang="th">อัตราการจับคู่</span>
                            </div>
                            <div class="text-2xl font-mono font-bold text-success" id="ps-match-rate">--</div>
                        </div>
                        <div class="p-4 rounded-lg" style="background: rgba(239, 68, 68, 0.1)">
                            <div class="text-xs text-titanium uppercase tracking-wide mb-1">
                                <span lang="en">Accuracy Rate</span>
                                <span lang="th">อัตราความถูกต้อง</span>
                            </div>
                            <div class="text-2xl font-mono font-bold text-danger" id="ps-accuracy">--</div>
                        </div>
                    </div>
                    
                    <div class="grid grid-cols-3 gap-4">
                        <div class="p-4 rounded border">
                            <div class="flex justify-between items-center mb-2">
                                <span class="text-sm text-titanium">
                                    <span lang="en">Date Mismatches</span>
                                    <span lang="th">วันที่ไม่ตรง</span>
                                </span>
                                <span class="text-xl font-mono font-bold text-warning" id="ps-date-mismatch">--</span>
                            </div>
                        </div>
                        <div class="p-4 rounded border">
                            <div class="flex justify-between items-center mb-2">
                                <span class="text-sm text-titanium">
                                    <span lang="en">Balance Mismatches</span>
                                    <span lang="th">ยอดเงินไม่ตรง</span>
                                </span>
                                <span class="text-xl font-mono font-bold text-danger" id="ps-bal-mismatch">--</span>
                            </div>
                        </div>
                        <div class="p-4 rounded border">
                            <div class="flex justify-between items-center mb-2">
                                <span class="text-sm text-titanium">
                                    <span lang="en">Perfect Matches</span>
                                    <span lang="th">ตรงกันทั้งหมด</span>
                                </span>
                                <span class="text-xl font-mono font-bold text-success" id="ps-perfect">--</span>
                            </div>
                        </div>
                    </div>
                </div>
                
                <!-- Debt Separation Tab -->
                <div class="tab-content" id="tab-debt-separation">
                    <div class="p-4 rounded-lg mb-6" style="background: rgba(245, 158, 11, 0.1); border: 1px solid rgba(245, 158, 11, 0.3)">
                        <h4 class="font-orbitron text-sm font-bold text-warning mb-2">
                            <span lang="en">Debt Separation Detection (แยกหนี้)</span>
                            <span lang="th">การตรวจจับแยกหนี้</span>
                        </h4>
                        <p class="text-sm text-titanium mb-4">
                            <span lang="en">
                                Cases where PRE_BALANCE < EXACT_PRE_BALANCE indicate potential debt separation. 
                                These accounts may have multiple ACC_NO for the same borrower and require manual investigation.
                            </span>
                            <span lang="th">
                                กรณีที่ PRE_BALANCE < EXACT_PRE_BALANCE บ่งชี้ว่าอาจมีการแยกหนี้ 
                                บัญชีเหล่านี้อาจมีหลาย ACC_NO สำหรับผู้กู้คนเดียวกัน และต้องตรวจสอบด้วยตนเอง
                            </span>
                        </p>
                        <div class="text-3xl font-mono font-bold text-warning" id="debt-sep-count">--</div>
                        <div class="text-xs text-titanium mt-1">
                            <span lang="en">accounts flagged for review</span>
                            <span lang="th">บัญชีที่ต้องตรวจสอบ</span>
                        </div>
                    </div>
                    
                    <div class="overflow-x-auto max-h-500 overflow-y-auto">
                        <table class="data-table" id="debt-sep-table">
                            <thead>
                                <tr>
                                    <th>ACC_NO</th>
                                    <th>PRE_BALANCE</th>
                                    <th>EXACT_PRE_BALANCE</th>
                                    <th>
                                        <span lang="en">Difference</span>
                                        <span lang="th">ผลต่าง</span>
                                    </th>
                                    <th>DSL2_BALANCE</th>
                                    <th>
                                        <span lang="en">Remark</span>
                                        <span lang="th">หมายเหตุ</span>
                                    </th>
                                </tr>
                            </thead>
                            <tbody id="debt-sep-body"></tbody>
                        </table>
                    </div>
                </div>
            </section>
            
            <!-- Visualization Section -->
            <section class="grid grid-cols-2 gap-6 mb-8 reveal">
                <div class="glass-panel p-6">
                    <div class="section-header">
                        <span class="icon" id="icon-scatter"></span>
                        <span lang="en">Data Landscape (Balance Error vs Date Diff)</span>
                        <span lang="th">ภูมิมิติข้อมูล (ผลต่างยอดเงิน vs ผลต่างวันที่)</span>
                    </div>
                    <div class="chart-container">
                        <canvas id="scatterChart"></canvas>
                    </div>
                </div>
                <div class="glass-panel p-6">
                    <div class="section-header">
                        <span class="icon" id="icon-radar"></span>
                        <span lang="en">Quality Metrics</span>
                        <span lang="th">ตัวชี้วัดคุณภาพ</span>
                    </div>
                    <div class="chart-container">
                        <canvas id="radarChart"></canvas>
                    </div>
                </div>
            </section>
            
            <section class="grid grid-cols-2 gap-6 mb-8 reveal">
                <div class="glass-panel p-6">
                    <div class="section-header">
                        <span class="icon" id="icon-pie"></span>
                        <span lang="en">DSL1 vs DSL2 Classification</span>
                        <span lang="th">การจำแนก DSL1 เทียบ DSL2</span>
                    </div>
                    <div class="chart-container">
                        <canvas id="pieChartDsl1"></canvas>
                    </div>
                </div>
                <div class="glass-panel p-6">
                    <div class="section-header">
                        <span class="icon" id="icon-histogram"></span>
                        <span lang="en">Balance Error Distribution</span>
                        <span lang="th">การกระจายผลต่างยอดเงิน</span>
                    </div>
                    <div class="chart-container">
                        <canvas id="histogramChart"></canvas>
                    </div>
                </div>
            </section>
            
            <!-- Error Records Table -->
            <section class="glass-panel p-6 mb-8 reveal">
                <div class="flex justify-between items-center mb-4">
                    <div class="section-header mb-0">
                        <span class="icon" id="icon-table"></span>
                        <span lang="en">Integrity Log (Discrepancy Records)</span>
                        <span lang="th">บันทึกความสมบูรณ์ (ระเบียนที่ไม่ตรงกัน)</span>
                    </div>
                    <div class="flex items-center gap-4">
                        <input type="text" id="searchInput" placeholder="Search ACC_NO..." 
                               class="px-4 py-2 rounded-lg bg-deep border text-sm" style="min-width: 200px;">
                        <span class="text-sm text-titanium">
                            <span lang="en">Showing</span>
                            <span lang="th">แสดง</span>
                            <span id="recordCount" class="font-mono text-neon">0</span>
                            <span lang="en">records</span>
                            <span lang="th">ระเบียน</span>
                        </span>
                    </div>
                </div>
                <div class="overflow-x-auto max-h-500 overflow-y-auto">
                    <table class="data-table" id="errorTable">
                        <thead id="table-head"></thead>
                        <tbody id="table-body"></tbody>
                    </table>
                </div>
            </section>
            
            <!-- Execution Metadata -->
            <section class="glass-panel p-6 reveal">
                <div class="section-header">
                    <span class="icon" id="icon-info"></span>
                    <span lang="en">Execution Metadata</span>
                    <span lang="th">ข้อมูลการประมวลผล</span>
                </div>
                <div class="grid grid-cols-4 gap-4 text-sm">
                    <div>
                        <span class="text-titanium">
                            <span lang="en">Duration:</span>
                            <span lang="th">ระยะเวลา:</span>
                        </span>
                        <span class="font-mono ml-2" id="meta-duration">--</span>
                    </div>
                    <div>
                        <span class="text-titanium">
                            <span lang="en">Records/sec:</span>
                            <span lang="th">ระเบียน/วินาที:</span>
                        </span>
                        <span class="font-mono ml-2" id="meta-speed">--</span>
                    </div>
                    <div>
                        <span class="text-titanium">
                            <span lang="en">Version:</span>
                            <span lang="th">เวอร์ชัน:</span>
                        </span>
                        <span class="font-mono ml-2" id="meta-version">--</span>
                    </div>
                    <div>
                        <span class="text-titanium">
                            <span lang="en">System RAM:</span>
                            <span lang="th">RAM ระบบ:</span>
                        </span>
                        <span class="font-mono ml-2" id="meta-ram">--</span>
                    </div>
                </div>
            </section>
        </main>
    </div>
    
    <!-- Slide Panel -->
    <div id="panelOverlay" class="slide-panel-overlay" onclick="APP.closePanel()"></div>
    <aside id="detailPanel" class="slide-panel p-8">
        <button id="close-panel" class="absolute top-4 right-4 text-titanium cursor-pointer text-2xl" onclick="APP.closePanel()">×</button>
        <div id="panelContent"></div>
    </aside>

    <script>
        // ═══════════════════════════════════════════════════════════════════════
        // NEXUS v10.0 APPLICATION CORE
        // ═══════════════════════════════════════════════════════════════════════
        
        // 1. NATIVE SVG ICONS (NO FontAwesome)
        const ICONS = {{
            logo: `<svg viewBox="0 0 24 24" fill="currentColor" class="w-8 h-8" style="width:32px;height:32px"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>`,
            scatter: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:24px;height:24px"><circle cx="7" cy="7" r="2"/><circle cx="17" cy="17" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="5" cy="17" r="2"/><circle cx="19" cy="7" r="2"/></svg>`,
            radar: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:24px;height:24px"><polygon points="12,2 22,8.5 22,15.5 12,22 2,15.5 2,8.5"/><line x1="12" y1="2" x2="12" y2="22"/><line x1="2" y1="8.5" x2="22" y2="15.5"/><line x1="22" y1="8.5" x2="2" y2="15.5"/></svg>`,
            pie: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:24px;height:24px"><path d="M21.21 15.89A10 10 0 1 1 8 2.83"/><path d="M22 12A10 10 0 0 0 12 2v10z"/></svg>`,
            histogram: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:24px;height:24px"><rect x="3" y="12" width="4" height="9"/><rect x="10" y="6" width="4" height="15"/><rect x="17" y="9" width="4" height="12"/></svg>`,
            table: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:24px;height:24px"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="3" y1="15" x2="21" y2="15"/><line x1="9" y1="3" x2="9" y2="21"/><line x1="15" y1="3" x2="15" y2="21"/></svg>`,
            info: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:24px;height:24px"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>`,
        }};

        // 2. DATA AIRLOCK (Base64 Decryption)
        const RAW_PAYLOAD = "{b64_data}";
        let DATA = {{}};
        try {{
            DATA = JSON.parse(atob(RAW_PAYLOAD));
            console.log("[Airlock] Data decrypted successfully");
        }} catch(e) {{
            console.error("[Airlock] Decryption failed:", e);
        }}

        // 3. CHART MANAGER (Lifecycle Management)
        const ChartManager = {{
            instances: {{}},
            render: function(id, type, data, opts) {{
                const ctx = document.getElementById(id);
                if (!ctx) return;
                if (this.instances[id]) {{
                    this.instances[id].destroy();
                }}
                this.instances[id] = new Chart(ctx, {{ type, data, options: opts }});
            }}
        }};

        // 4. APP CORE
        const APP = {{
            lang: 'en',
            
            init: function() {{
                console.log("[Nexus] Initializing v10.0...");
                
                // Hide loading overlay
                setTimeout(() => {{
                    document.getElementById('loading-overlay').classList.add('hidden');
                }}, 500);
                
                // Inject icons
                document.getElementById('logo-slot').innerHTML = ICONS.logo;
                document.getElementById('icon-scatter').innerHTML = ICONS.scatter;
                document.getElementById('icon-radar').innerHTML = ICONS.radar;
                document.getElementById('icon-pie').innerHTML = ICONS.pie;
                document.getElementById('icon-histogram').innerHTML = ICONS.histogram;
                document.getElementById('icon-table').innerHTML = ICONS.table;
                document.getElementById('icon-info').innerHTML = ICONS.info;
                
                this.hydrateUI();
                this.initPhysics();
                this.initObservers();
                this.initTabs();
                this.renderCharts();
                this.renderTables();
                this.initSearch();
                
                console.log("[Nexus] Initialization complete");
            }},
            
            toggleLang: function() {{
                this.lang = this.lang === 'en' ? 'th' : 'en';
                document.body.dataset.lang = this.lang;
            }},
            
            hydrateUI: function() {{
                const stats = DATA.stats || {{}};
                const dsl1 = stats.dsl1_vs_dsl2 || {{}};
                const ps = stats.ps_vs_dsl2 || {{}};
                
                // Summary stats
                document.getElementById('stat-total').innerText = this.formatNumber(stats.total_rows || 0);
                document.getElementById('stat-matched').innerText = this.formatNumber((dsl1.matched_rows || 0) + (ps.matched_rows || 0));
                document.getElementById('stat-errors').innerText = this.formatNumber(stats.error_count || 0);
                document.getElementById('stat-debt-sep').innerText = this.formatNumber(dsl1.debt_separation_cases || 0);
                document.getElementById('stat-accuracy').innerText = (dsl1.accuracy_rate_pct || 0).toFixed(1) + '%';
                
                // DSL1 vs DSL2 stats
                document.getElementById('dsl1-rows').innerText = this.formatNumber(dsl1.total_dsl1_filtered_rows || 0);
                document.getElementById('dsl2-rows').innerText = this.formatNumber(dsl1.total_dsl2_rows || 0);
                document.getElementById('dsl1-match-rate').innerText = (dsl1.match_rate_pct || 0).toFixed(1) + '%';
                document.getElementById('dsl1-error-rate').innerText = (dsl1.error_rate_pct || 0).toFixed(1) + '%';
                document.getElementById('dsl1-date-mismatch').innerText = this.formatNumber(dsl1.date_mismatches || 0);
                document.getElementById('dsl1-bal-mismatch').innerText = this.formatNumber(dsl1.balance_mismatches || 0);
                document.getElementById('dsl1-both-mismatch').innerText = this.formatNumber(dsl1.both_mismatches || 0);
                document.getElementById('exact-vs-dsl2').innerText = this.formatNumber(dsl1.exact_vs_dsl2_mismatches || 0);
                document.getElementById('exact-vs-pre').innerText = this.formatNumber(dsl1.exact_vs_pre_mismatches || 0);
                
                // Progress bars
                const matched = dsl1.matched_rows || 1;
                document.getElementById('dsl1-date-progress').style.width = ((dsl1.date_mismatches || 0) / matched * 100).toFixed(1) + '%';
                document.getElementById('dsl1-bal-progress').style.width = ((dsl1.balance_mismatches || 0) / matched * 100).toFixed(1) + '%';
                document.getElementById('dsl1-both-progress').style.width = ((dsl1.both_mismatches || 0) / matched * 100).toFixed(1) + '%';
                
                // PS vs DSL2 stats
                document.getElementById('ps-rows').innerText = this.formatNumber(ps.total_ps_rows || 0);
                document.getElementById('ps-dsl2-rows').innerText = this.formatNumber(ps.total_dsl2_rows || 0);
                document.getElementById('ps-match-rate').innerText = (ps.match_rate_pct || 0).toFixed(1) + '%';
                document.getElementById('ps-accuracy').innerText = (ps.accuracy_rate_pct || 0).toFixed(1) + '%';
                document.getElementById('ps-date-mismatch').innerText = this.formatNumber(ps.date_mismatches || 0);
                document.getElementById('ps-bal-mismatch').innerText = this.formatNumber(ps.balance_mismatches || 0);
                document.getElementById('ps-perfect').innerText = this.formatNumber(ps.perfect_matches || 0);
                
                // Debt separation
                document.getElementById('debt-sep-count').innerText = this.formatNumber(dsl1.debt_separation_cases || 0);
                
                // Metadata
                document.getElementById('generated-time').innerText = DATA.generated_at || '';
                document.getElementById('meta-duration').innerText = (dsl1.duration_seconds || 0).toFixed(2) + 's';
                document.getElementById('meta-speed').innerText = this.formatNumber(Math.round((stats.total_rows || 0) / Math.max(dsl1.duration_seconds || 1, 0.001)));
                document.getElementById('meta-version').innerText = DATA.version || '3.0.0';
                document.getElementById('meta-ram').innerText = (DATA.system && DATA.system.ram) || 'N/A';
            }},
            
            initPhysics: function() {{
                const canvas = document.getElementById('antigravity-canvas');
                
                // HYBRID ENGINE: Try Three.js, Fallback to Canvas 2D
                if (typeof THREE !== 'undefined') {{
                    try {{
                        const scene = new THREE.Scene();
                        const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
                        const renderer = new THREE.WebGLRenderer({{ canvas, alpha: true, antialias: true }});
                        renderer.setSize(window.innerWidth, window.innerHeight);
                        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
                        
                        // Antigravity Ring (Torus with particles)
                        const geometry = new THREE.TorusGeometry(15, 5, 16, 100);
                        const material = new THREE.PointsMaterial({{
                            color: 0x3b82f6,
                            size: 0.08,
                            transparent: true,
                            opacity: 0.6,
                            sizeAttenuation: true
                        }});
                        const torus = new THREE.Points(geometry, material);
                        scene.add(torus);
                        
                        // Second ring
                        const geometry2 = new THREE.TorusGeometry(20, 3, 16, 80);
                        const material2 = new THREE.PointsMaterial({{
                            color: 0x06b6d4,
                            size: 0.06,
                            transparent: true,
                            opacity: 0.4
                        }});
                        const torus2 = new THREE.Points(geometry2, material2);
                        torus2.rotation.x = Math.PI / 4;
                        scene.add(torus2);
                        
                        camera.position.z = 50;

                        function animate() {{
                            requestAnimationFrame(animate);
                            torus.rotation.x += 0.001;
                            torus.rotation.y += 0.002;
                            torus2.rotation.y -= 0.001;
                            torus2.rotation.z += 0.001;
                            renderer.render(scene, camera);
                        }}
                        animate();
                        
                        window.addEventListener('resize', () => {{
                            camera.aspect = window.innerWidth / window.innerHeight;
                            camera.updateProjectionMatrix();
                            renderer.setSize(window.innerWidth, window.innerHeight);
                        }});
                        
                        console.log("[Physics] WebGL Engine Active");
                        return;
                    }} catch(e) {{
                        console.warn("[Physics] WebGL Init Failed, engaging fallback:", e);
                    }}
                }}
                
                // CANVAS 2D FALLBACK (Plexus Network)
                console.log("[Physics] Engaging Canvas 2D Fallback");
                const ctx = canvas.getContext('2d');
                let w = canvas.width = window.innerWidth;
                let h = canvas.height = window.innerHeight;
                let particles = [];
                const particleCount = 80;
                
                for (let i = 0; i < particleCount; i++) {{
                    particles.push({{
                        x: Math.random() * w,
                        y: Math.random() * h,
                        vx: (Math.random() - 0.5) * 0.5,
                        vy: (Math.random() - 0.5) * 0.5,
                        radius: Math.random() * 2 + 1
                    }});
                }}
                
                function draw() {{
                    ctx.clearRect(0, 0, w, h);
                    ctx.fillStyle = '#3b82f6';
                    
                    particles.forEach((p, i) => {{
                        p.x += p.vx;
                        p.y += p.vy;
                        
                        if (p.x < 0 || p.x > w) p.vx *= -1;
                        if (p.y < 0 || p.y > h) p.vy *= -1;
                        
                        ctx.beginPath();
                        ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
                        ctx.fill();
                        
                        // Draw connections
                        particles.slice(i + 1).forEach(p2 => {{
                            const dx = p.x - p2.x;
                            const dy = p.y - p2.y;
                            const dist = Math.sqrt(dx * dx + dy * dy);
                            
                            if (dist < 150) {{
                                ctx.beginPath();
                                ctx.moveTo(p.x, p.y);
                                ctx.lineTo(p2.x, p2.y);
                                ctx.strokeStyle = `rgba(59, 130, 246, ${{0.2 * (1 - dist / 150)}})`;
                                ctx.stroke();
                            }}
                        }});
                    }});
                    
                    requestAnimationFrame(draw);
                }}
                draw();
                
                window.addEventListener('resize', () => {{
                    w = canvas.width = window.innerWidth;
                    h = canvas.height = window.innerHeight;
                }});
            }},
            
            renderCharts: function() {{
                if (!DATA.viz) return;
                
                const chartColors = {{
                    neon: 'rgba(59, 130, 246, 0.8)',
                    accent: 'rgba(6, 182, 212, 0.8)',
                    success: 'rgba(16, 185, 129, 0.8)',
                    warning: 'rgba(245, 158, 11, 0.8)',
                    danger: 'rgba(239, 68, 68, 0.8)',
                    violet: 'rgba(139, 92, 246, 0.8)',
                    peach: 'rgba(255, 190, 152, 0.8)',
                }};
                
                // Radar Chart
                ChartManager.render('radarChart', 'radar', {{
                    labels: ['Data Integrity', 'Match Coverage', 'Date Accuracy', 'Balance Accuracy', 'Velocity'],
                    datasets: [{{
                        label: 'Quality Score',
                        data: DATA.viz.radar || [90, 90, 90, 90, 90],
                        backgroundColor: 'rgba(59, 130, 246, 0.2)',
                        borderColor: chartColors.neon,
                        borderWidth: 2,
                        pointBackgroundColor: chartColors.neon
                    }}]
                }}, {{
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {{
                        r: {{
                            beginAtZero: true,
                            max: 100,
                            grid: {{ color: 'rgba(255, 255, 255, 0.1)' }},
                            angleLines: {{ color: 'rgba(255, 255, 255, 0.1)' }},
                            pointLabels: {{ color: '#86868b', font: {{ size: 11 }} }},
                            ticks: {{ display: false }}
                        }}
                    }},
                    plugins: {{ legend: {{ display: false }} }}
                }});
                
                // Scatter Chart
                ChartManager.render('scatterChart', 'scatter', {{
                    datasets: [{{
                        label: 'Anomalies',
                        data: (DATA.viz.scatter || []).map(d => ({{ x: d.x, y: d.y }})),
                        backgroundColor: chartColors.warning,
                        borderColor: 'rgba(245, 158, 11, 1)',
                        borderWidth: 1,
                        pointRadius: 4
                    }}]
                }}, {{
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {{
                        x: {{
                            title: {{ display: true, text: 'Balance Difference', color: '#86868b' }},
                            grid: {{ color: 'rgba(255, 255, 255, 0.05)' }},
                            ticks: {{ color: '#86868b' }}
                        }},
                        y: {{
                            title: {{ display: true, text: 'Date Difference (Days)', color: '#86868b' }},
                            grid: {{ color: 'rgba(255, 255, 255, 0.05)' }},
                            ticks: {{ color: '#86868b' }}
                        }}
                    }},
                    plugins: {{ legend: {{ display: false }} }}
                }});
                
                // Pie Chart (DSL1 vs DSL2)
                const pie = DATA.viz.pie_dsl1 || {{}};
                ChartManager.render('pieChartDsl1', 'doughnut', {{
                    labels: ['Perfect Match', 'Date Only', 'Balance Only', 'Both'],
                    datasets: [{{
                        data: [pie.perfect || 0, pie.date_only || 0, pie.balance_only || 0, pie.both || 0],
                        backgroundColor: [chartColors.success, chartColors.warning, chartColors.danger, chartColors.violet],
                        borderColor: ['rgba(16, 185, 129, 1)', 'rgba(245, 158, 11, 1)', 'rgba(239, 68, 68, 1)', 'rgba(139, 92, 246, 1)'],
                        borderWidth: 2
                    }}]
                }}, {{
                    responsive: true,
                    maintainAspectRatio: false,
                    cutout: '60%',
                    plugins: {{
                        legend: {{
                            position: 'bottom',
                            labels: {{ color: '#86868b', padding: 15, font: {{ size: 11 }} }}
                        }}
                    }}
                }});
                
                // Histogram
                const hist = DATA.viz.histogram_dsl1 || {{}};
                if (hist.edges && hist.edges.length > 1) {{
                    const labels = hist.edges.slice(0, -1).map((e, i) => {{
                        const next = hist.edges[i + 1];
                        return `${{e.toFixed(0)}}`;
                    }});
                    
                    ChartManager.render('histogramChart', 'bar', {{
                        labels: labels.length > 25 ? labels.filter((_, i) => i % 2 === 0) : labels,
                        datasets: [{{
                            label: 'Frequency',
                            data: labels.length > 25 ? hist.values.filter((_, i) => i % 2 === 0) : hist.values,
                            backgroundColor: chartColors.neon,
                            borderColor: 'rgba(59, 130, 246, 1)',
                            borderWidth: 1
                        }}]
                    }}, {{
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {{ legend: {{ display: false }} }},
                        scales: {{
                            x: {{ display: false }},
                            y: {{ grid: {{ color: 'rgba(255, 255, 255, 0.05)' }}, ticks: {{ color: '#86868b' }} }}
                        }}
                    }});
                }}
            }},
            
            renderTables: function() {{
                const errors = DATA.errors || {{}};
                const dsl1Errors = errors.dsl1_vs_dsl2 || [];
                const debtSep = errors.debt_separation || [];
                
                // Main error table
                if (dsl1Errors.length > 0) {{
                    const cols = ['ACC_NO', 'DATE_DSL1', 'DATE_DSL2', 'DATE_MATCH', 'BAL_DSL1', 'BAL_DSL2', 'BAL_DIFF', 'BAL_DIFF_PCT', 'IS_DEBT_SEPARATION'];
                    
                    document.getElementById('table-head').innerHTML = '<tr>' + cols.map(c => `<th>${{c}}</th>`).join('') + '</tr>';
                    
                    this.currentErrors = dsl1Errors;
                    this.renderErrorRows(dsl1Errors.slice(0, 500));
                }}
                
                // Debt separation table
                if (debtSep.length > 0) {{
                    const tbody = document.getElementById('debt-sep-body');
                    tbody.innerHTML = debtSep.slice(0, 500).map(row => {{
                        return `<tr class="warning-row">
                            <td class="font-bold">${{row.ACC_NO || ''}}</td>
                            <td class="text-right">${{this.formatNumber(row.PRE_BALANCE || 0)}}</td>
                            <td class="text-right">${{this.formatNumber(row.EXACT_PRE_BALANCE || 0)}}</td>
                            <td class="text-right text-warning">${{this.formatNumber(row.DIFFERENCE || 0)}}</td>
                            <td class="text-right">${{this.formatNumber(row.DSL2_BALANCE || 0)}}</td>
                            <td><span class="badge badge-warning">${{row.REMARK || ''}}</span></td>
                        </tr>`;
                    }}).join('');
                }}
            }},
            
            renderErrorRows: function(rows) {{
                const tbody = document.getElementById('table-body');
                const cols = ['ACC_NO', 'DATE_DSL1', 'DATE_DSL2', 'DATE_MATCH', 'BAL_DSL1', 'BAL_DSL2', 'BAL_DIFF', 'BAL_DIFF_PCT', 'IS_DEBT_SEPARATION'];
                
                tbody.innerHTML = rows.map(row => {{
                    const rowClass = row.IS_DEBT_SEPARATION ? 'warning-row' : 'error-row';
                    return `<tr class="${{rowClass}}" onclick="APP.openPanel(${{JSON.stringify(row).replace(/"/g, '"')}})">` +
                        cols.map(c => {{
                            let val = row[c];
                            if (c === 'DATE_MATCH' || c === 'IS_DEBT_SEPARATION') {{
                                return `<td class="text-center">${{val ? '<span class="badge badge-success">✓</span>' : '<span class="badge badge-danger">✗</span>'}}</td>`;
                            }}
                            if (c === 'BAL_DIFF') {{
                                const color = Math.abs(val) > 1000 ? 'text-danger' : Math.abs(val) > 100 ? 'text-warning' : 'text-success';
                                return `<td class="text-right ${{color}}">${{this.formatNumber(val)}}</td>`;
                            }}
                            if (c === 'BAL_DIFF_PCT') {{
                                return `<td class="text-right">${{(val || 0).toFixed(4)}}%</td>`;
                            }}
                            if (c.includes('BAL')) {{
                                return `<td class="text-right">${{this.formatNumber(val)}}</td>`;
                            }}
                            return `<td>${{val || '-'}}</td>`;
                        }}).join('') +
                    '</tr>';
                }}).join('');
                
                document.getElementById('recordCount').innerText = rows.length.toLocaleString();
            }},
            
            initSearch: function() {{
                const input = document.getElementById('searchInput');
                input.addEventListener('input', (e) => {{
                    const query = e.target.value.toLowerCase();
                    const filtered = (this.currentErrors || []).filter(r =>
                        (r.ACC_NO || '').toLowerCase().includes(query)
                    ).slice(0, 500);
                    this.renderErrorRows(filtered);
                }});
            }},
            
            initTabs: function() {{
                document.querySelectorAll('.tab-btn').forEach(btn => {{
                    btn.addEventListener('click', () => {{
                        const tabId = btn.dataset.tab;
                        
                        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
                        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                        
                        btn.classList.add('active');
                        document.getElementById('tab-' + tabId).classList.add('active');
                    }});
                }});
            }},
            
            initObservers: function() {{
                const observer = new IntersectionObserver((entries) => {{
                    entries.forEach(e => e.target.classList.toggle('active', e.isIntersecting));
                }}, {{ threshold: 0.1 }});
                
                document.querySelectorAll('.reveal').forEach(el => observer.observe(el));
            }},
            
            openPanel: function(record) {{
                const panel = document.getElementById('detailPanel');
                const overlay = document.getElementById('panelOverlay');
                const content = document.getElementById('panelContent');
                
                content.innerHTML = `
                    <div class="glass-panel p-4 mb-4">
                        <h4 class="text-xs text-titanium uppercase tracking-wide mb-2">Account Number</h4>
                        <p class="text-2xl font-mono font-bold gradient-text">${{record.ACC_NO}}</p>
                    </div>
                    
                    <div class="glass-panel p-4 mb-4">
                        <h4 class="text-xs text-titanium uppercase tracking-wide mb-3">Date Comparison</h4>
                        <div class="grid grid-cols-2 gap-4">
                            <div>
                                <span class="text-xs text-titanium">DSL1</span>
                                <p class="font-mono">${{record.DATE_DSL1 || 'N/A'}}</p>
                            </div>
                            <div>
                                <span class="text-xs text-titanium">DSL2</span>
                                <p class="font-mono">${{record.DATE_DSL2 || 'N/A'}}</p>
                            </div>
                        </div>
                        <div class="mt-3 p-2 rounded" style="background: ${{record.DATE_MATCH ? 'rgba(16,185,129,0.1)' : 'rgba(239,68,68,0.1)'}}">
                            <span style="color: ${{record.DATE_MATCH ? 'var(--success)' : 'var(--danger)'}}">
                                ${{record.DATE_MATCH ? '✓ Dates Match' : '✗ Date Mismatch (' + record.DATE_DIFF_DAYS + ' days)'}}
                            </span>
                        </div>
                    </div>
                    
                    <div class="glass-panel p-4 mb-4">
                        <h4 class="text-xs text-titanium uppercase tracking-wide mb-3">Balance Comparison</h4>
                        <div class="grid grid-cols-2 gap-4">
                            <div>
                                <span class="text-xs text-titanium">DSL1 (PRE_BALANCE)</span>
                                <p class="font-mono text-lg">${{this.formatNumber(record.BAL_DSL1)}}</p>
                            </div>
                            <div>
                                <span class="text-xs text-titanium">DSL2 (ยอดหนี้เงินกู้)</span>
                                <p class="font-mono text-lg">${{this.formatNumber(record.BAL_DSL2)}}</p>
                            </div>
                        </div>
                        <div class="mt-4 p-3 rounded" style="background: rgba(59,130,246,0.1)">
                            <div class="flex justify-between items-center">
                                <span class="text-titanium">Difference</span>
                                <span class="font-mono text-xl" style="color: ${{Math.abs(record.BAL_DIFF) > 1000 ? 'var(--danger)' : 'var(--warning)'}}">
                                    ${{record.BAL_DIFF >= 0 ? '+' : ''}}${{this.formatNumber(record.BAL_DIFF)}}
                                </span>
                            </div>
                            <div class="flex justify-between items-center mt-2">
                                <span class="text-titanium">Percentage</span>
                                <span class="font-mono">${{(record.BAL_DIFF_PCT || 0).toFixed(4)}}%</span>
                            </div>
                        </div>
                    </div>
                    
                    ${{record.IS_DEBT_SEPARATION ? `
                    <div class="glass-panel p-4 mb-4" style="border-color: rgba(245, 158, 11, 0.4)">
                        <h4 class="text-xs text-warning uppercase tracking-wide mb-2">⚠ Debt Separation Flag</h4>
                        <p class="text-sm text-titanium">
                            This account shows PRE_BALANCE < EXACT_PRE_BALANCE, indicating potential debt separation (แยกหนี้).
                            This borrower may have multiple accounts that require manual investigation.
                        </p>
                        <div class="mt-3 grid grid-cols-2 gap-4">
                            <div>
                                <span class="text-xs text-titanium">EXACT_PRE_BALANCE</span>
                                <p class="font-mono text-lg text-peach">${{this.formatNumber(record.EXACT_BAL)}}</p>
                            </div>
                            <div>
                                <span class="text-xs text-titanium">Difference</span>
                                <p class="font-mono text-lg text-warning">${{this.formatNumber(record.EXACT_VS_PRE_DIFF)}}</p>
                            </div>
                        </div>
                    </div>
                    ` : ''}}
                `;
                
                panel.classList.add('open');
                overlay.classList.add('open');
            }},
            
            closePanel: function() {{
                document.getElementById('detailPanel').classList.remove('open');
                document.getElementById('panelOverlay').classList.remove('open');
            }},
            
            formatNumber: function(num) {{
                return new Intl.NumberFormat('en-US', {{ maximumFractionDigits: 2 }}).format(num);
            }}
        }};

        // 5. RESILIENT LOADER
        function waitForLibs(retries = 0) {{
            if (typeof d3 !== 'undefined' && typeof Chart !== 'undefined') {{
                console.log(`[System] Core Loaded (${{retries * 100}}ms)`);
                APP.init();
            }} else if (retries < 50) {{
                setTimeout(() => waitForLibs(retries + 1), 100);
            }} else {{
                console.error("[System] Critical Dependency Failure");
                APP.init(); // Force load attempt
            }}
        }}

        document.addEventListener('DOMContentLoaded', () => waitForLibs());
        
        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {{
            if (e.key === 'Escape') APP.closePanel();
        }});
    </script>
</body>
</html>'''
    
    if progress and task_id:
        progress.update(task_id, completed=90)
    
    # Write artifact
    log_write("Writing HTML file to disk...")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    
    if progress and task_id:
        progress.update(task_id, completed=100)
    
    log_secure(f"Nexus v10.0 Artifact generated: {output_path}", "generate_html")


# ══════════════════════════════════════════════════════════════════════════════
# MANIFEST GENERATION
# ══════════════════════════════════════════════════════════════════════════════

def generate_manifest(
    combined_result: CombinedReconciliationResult,
    dsl1_folder: Path,
    dsl2_folder: Path,
    ps_folder: Path,
    output_folder: Path,
    progress: Progress = None,
    task_id = None
) -> Dict[str, Any]:
    """Generate JSON manifest with hashes, row counts, and environment info."""
    start_timer("generate_manifest")
    log_write("Generating manifest...")
    
    manifest = {
        "version": combined_result.version,
        "generated_at": combined_result.generated_at,
        "script": "recalc_dsl1_dsl2_ps_reconcile.py",
        "inputs": {
            "dsl1_folder": str(dsl1_folder.absolute()),
            "dsl2_folder": str(dsl2_folder.absolute()),
            "payment_schedule_folder": str(ps_folder.absolute()) if ps_folder else None,
            "dsl1_files": [],
            "dsl2_files": [],
            "payment_schedule_files": [],
        },
        "outputs": {
            "folder": str(output_folder.absolute()),
            "csv_dsl1_errors": "dsl1_dsl2_discrepancies.csv",
            "csv_ps_errors": "ps_dsl2_discrepancies.csv",
            "csv_debt_separation": "debt_separation_cases.csv",
            "html_artifact": "nexus_report.html",
        },
        "statistics": combined_result.to_dict(),
        "environment": {
            "python_version": sys.version,
            "polars_available": POLARS_AVAILABLE,
            "pandas_available": PANDAS_AVAILABLE,
            "platform": sys.platform,
        }
    }
    
    if progress and task_id:
        progress.update(task_id, completed=20)
    
    # Add file hashes
    log_info("Calculating file hashes for DSL1...")
    for f in discover_files(dsl1_folder):
        manifest["inputs"]["dsl1_files"].append({
            "name": f.name,
            "size_bytes": f.stat().st_size,
            "hash_sha256_short": get_file_hash(f)
        })
    
    if progress and task_id:
        progress.update(task_id, completed=40)
    
    log_info("Calculating file hashes for DSL2...")
    for f in discover_files(dsl2_folder):
        manifest["inputs"]["dsl2_files"].append({
            "name": f.name,
            "size_bytes": f.stat().st_size,
            "hash_sha256_short": get_file_hash(f)
        })
    
    if progress and task_id:
        progress.update(task_id, completed=60)
    
    if ps_folder and ps_folder.exists():
        log_info("Calculating file hashes for Payment Schedule...")
        for f in discover_files(ps_folder):
            manifest["inputs"]["payment_schedule_files"].append({
                "name": f.name,
                "size_bytes": f.stat().st_size,
                "hash_sha256_short": get_file_hash(f)
            })
    
    if progress and task_id:
        progress.update(task_id, completed=100)
    
    log_secure("Manifest generated", "generate_manifest")
    
    return manifest


# ══════════════════════════════════════════════════════════════════════════════
# MAIN EXECUTION ENGINE
# ══════════════════════════════════════════════════════════════════════════════

def main():
    """Main execution entry point with full CLI interface."""
    
    parser = argparse.ArgumentParser(
        description="RECALC TOOLKIT v3.0: DSL1 ↔ DSL2 ↔ Payment Schedule Reconciliation Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python recalc_reconcile.py --dsl1 ./DSL1 --dsl2 ./DSL2 --output ./results
  python recalc_reconcile.py --dsl1 ./DSL1 --dsl2 ./DSL2 --payment-schedule ./PS --output ./results --web-report
        """
    )
    
    parser.add_argument("--dsl1", type=Path, required=True, help="Path to DSL1 data folder")
    parser.add_argument("--dsl2", type=Path, required=True, help="Path to DSL2 data folder")
    parser.add_argument("--payment-schedule", type=Path, default=None, help="Path to Payment Schedule data folder")
    parser.add_argument("--output", type=Path, required=True, help="Output folder for results")
    parser.add_argument("--workers", type=int, default=4, help="Number of parallel workers")
    parser.add_argument("--web-report", action="store_true", help="Generate Nexus HTML artifact")
    parser.add_argument("--dry-run", action="store_true", help="Validation only, no write")
    parser.add_argument("--debug", action="store_true", help="Show full stack traces")
    parser.add_argument("--balance-tolerance", type=float, default=0.01, help="Balance match tolerance")
    parser.add_argument("--max-errors", type=int, default=100000, help="Maximum error records to capture")
    
    args = parser.parse_args()
    
    try:
        # Render header
        render_header_panel("RECALC: DSL1 ↔ DSL2 ↔ PS RECONCILIATION", "3.0.0")
        
        # Validate inputs
        if not args.dsl1.exists():
            log_fatal(f"DSL1 folder not found: {args.dsl1}")
            sys.exit(1)
        
        if not args.dsl2.exists():
            log_fatal(f"DSL2 folder not found: {args.dsl2}")
            sys.exit(1)
        
        ps_folder = args.payment_schedule
        if ps_folder and not ps_folder.exists():
            log_warn(f"Payment Schedule folder not found: {ps_folder}, skipping PS comparison")
            ps_folder = None
        
        # Create output folder
        args.output.mkdir(parents=True, exist_ok=True)
        tmp_folder = args.output / "_tmp"
        tmp_folder.mkdir(exist_ok=True)
        
        log_info(f"DSL1 Source: {args.dsl1}")
        log_info(f"DSL2 Source: {args.dsl2}")
        if ps_folder:
            log_info(f"Payment Schedule Source: {ps_folder}")
        log_info(f"Output: {args.output}")
        
        # Pre-flight reconnaissance
        log_recon("Initiating Holographic Pre-Flight Scan...")
        dsl1_scan = holographic_folder_scan(args.dsl1)
        dsl2_scan = holographic_folder_scan(args.dsl2)
        ps_scan = holographic_folder_scan(ps_folder) if ps_folder else None
        
        combined_result = CombinedReconciliationResult()
        
        # Load datasets with progress
        if RICH_AVAILABLE:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(bar_width=40),
                TaskProgressColumn(),
                TimeElapsedColumn(),
                TimeRemainingColumn(),
                console=console,
                transient=False
            ) as progress:
                
                # Load DSL1
                task1 = progress.add_task(f"[cyan]Loading DSL1 ({dsl1_scan['total_size_gb']:.1f}GB)...", total=100)
                
                if POLARS_AVAILABLE:
                    try:
                        dsl1_lazy = load_dsl1_polars(args.dsl1)
                        progress.update(task1, completed=50)
                        log_flux("Materializing DSL1 LazyFrame...")
                        dsl1_data = dsl1_lazy.collect()
                        progress.update(task1, completed=100)
                        log_secure(f"DSL1 loaded: {len(dsl1_data):,} rows")
                    except Exception as e:
                        log_warn(f"Polars failed: {e}, falling back to pandas")
                        if PANDAS_AVAILABLE:
                            dsl1_data = pl.from_pandas(load_dsl1_pandas_fallback(args.dsl1))
                            progress.update(task1, completed=100)
                        else:
                            raise
                else:
                    if PANDAS_AVAILABLE:
                        dsl1_data = pl.from_pandas(load_dsl1_pandas_fallback(args.dsl1))
                        progress.update(task1, completed=100)
                    else:
                        raise ImportError("Neither Polars nor Pandas available")
                
                # Load DSL2
                task2 = progress.add_task(f"[cyan]Loading DSL2 ({dsl2_scan['total_size_gb']:.1f}GB)...", total=100)
                
                if POLARS_AVAILABLE:
                    try:
                        dsl2_lazy = load_dsl2_polars(args.dsl2)
                        progress.update(task2, completed=50)
                        log_flux("Materializing DSL2 LazyFrame...")
                        dsl2_data = dsl2_lazy.collect()
                        progress.update(task2, completed=100)
                        log_secure(f"DSL2 loaded: {len(dsl2_data):,} rows")
                    except Exception as e:
                        log_warn(f"Polars failed for DSL2: {e}, falling back to pandas")
                        if PANDAS_AVAILABLE:
                            dsl2_data = pl.from_pandas(load_dsl2_pandas_fallback(args.dsl2))
                            progress.update(task2, completed=100)
                        else:
                            raise
                else:
                    if PANDAS_AVAILABLE:
                        dsl2_data = pl.from_pandas(load_dsl2_pandas_fallback(args.dsl2))
                        progress.update(task2, completed=100)
                    else:
                        raise ImportError("Neither Polars nor Pandas available")
                
                # Load Payment Schedule if provided
                ps_data = None
                if ps_folder:
                    task3 = progress.add_task(f"[violet]Loading Payment Schedule ({ps_scan['total_size_gb']:.1f}GB)...", total=100)
                    
                    if POLARS_AVAILABLE:
                        try:
                            ps_lazy = load_payment_schedule_polars(ps_folder)
                            progress.update(task3, completed=50)
                            log_flux("Materializing Payment Schedule LazyFrame...")
                            ps_data = ps_lazy.collect()
                            progress.update(task3, completed=100)
                            log_secure(f"Payment Schedule loaded: {len(ps_data):,} rows")
                        except Exception as e:
                            log_warn(f"Polars failed for Payment Schedule: {e}, falling back to pandas")
                            if PANDAS_AVAILABLE:
                                ps_data = pl.from_pandas(load_payment_schedule_pandas_fallback(ps_folder))
                                progress.update(task3, completed=100)
                            else:
                                log_warn("Payment Schedule loading failed, skipping PS comparison")
                    else:
                        if PANDAS_AVAILABLE:
                            ps_data = pl.from_pandas(load_payment_schedule_pandas_fallback(ps_folder))
                            progress.update(task3, completed=100)
                
                # Reconcile DSL1 vs DSL2
                task4 = progress.add_task("[cyan]Reconciling DSL1 vs DSL2...", total=100)
                combined_result.dsl1_vs_dsl2 = reconcile_dsl1_vs_dsl2(
                    dsl1_data, 
                    dsl2_data,
                    balance_tolerance=args.balance_tolerance,
                    max_error_records=args.max_errors,
                    progress=progress,
                    task_id=task4
                )
                progress.update(task4, completed=100)
                
                # Reconcile Payment Schedule vs DSL2 if available
                if ps_data is not None:
                    task5 = progress.add_task("[violet]Reconciling Payment Schedule vs DSL2...", total=100)
                    combined_result.ps_vs_dsl2 = reconcile_ps_vs_dsl2(
                        ps_data,
                        dsl2_data,
                        balance_tolerance=args.balance_tolerance,
                        max_error_records=args.max_errors,
                        progress=progress,
                        task_id=task5
                    )
                    progress.update(task5, completed=100)
        else:
            # Non-rich fallback
            print("Loading DSL1...")
            if POLARS_AVAILABLE:
                dsl1_data = load_dsl1_polars(args.dsl1).collect()
            elif PANDAS_AVAILABLE:
                dsl1_data = pl.from_pandas(load_dsl1_pandas_fallback(args.dsl1))
            else:
                raise ImportError("Neither Polars nor Pandas available")
            
            print("Loading DSL2...")
            if POLARS_AVAILABLE:
                try:
                    dsl2_data = load_dsl2_polars(args.dsl2).collect()
                except:
                    if PANDAS_AVAILABLE:
                        dsl2_data = pl.from_pandas(load_dsl2_pandas_fallback(args.dsl2))
                    else:
                        raise
            elif PANDAS_AVAILABLE:
                dsl2_data = pl.from_pandas(load_dsl2_pandas_fallback(args.dsl2))
            else:
                raise ImportError("Neither Polars nor Pandas available")
            
            ps_data = None
            if ps_folder:
                print("Loading Payment Schedule...")
                if POLARS_AVAILABLE:
                    try:
                        ps_data = load_payment_schedule_polars(ps_folder).collect()
                    except:
                        if PANDAS_AVAILABLE:
                            ps_data = pl.from_pandas(load_payment_schedule_pandas_fallback(ps_folder))
                elif PANDAS_AVAILABLE:
                    ps_data = pl.from_pandas(load_payment_schedule_pandas_fallback(ps_folder))
            
            print("Reconciling DSL1 vs DSL2...")
            combined_result.dsl1_vs_dsl2 = reconcile_dsl1_vs_dsl2(dsl1_data, dsl2_data)
            
            if ps_data is not None:
                print("Reconciling Payment Schedule vs DSL2...")
                combined_result.ps_vs_dsl2 = reconcile_ps_vs_dsl2(ps_data, dsl2_data)
        
        # Display results summary
        dsl1_result = combined_result.dsl1_vs_dsl2
        ps_result = combined_result.ps_vs_dsl2
        
        if console:
            summary_table = Table(title="Reconciliation Summary", box=box.ROUNDED)
            summary_table.add_column("Metric", style="cyan")
            summary_table.add_column("DSL1 vs DSL2", style="white")
            summary_table.add_column("PS vs DSL2", style="white")
            
            summary_table.add_row("Source Rows", f"{dsl1_result.total_dsl1_rows:,}", f"{ps_result.total_ps_rows:,}")
            summary_table.add_row("Filtered Rows (GROUP_FLAG=1)", f"{dsl1_result.total_dsl1_filtered_rows:,}", "N/A")
            summary_table.add_row("DSL2 Rows", f"{dsl1_result.total_dsl2_rows:,}", f"{ps_result.total_dsl2_rows:,}")
            summary_table.add_row("Matched Rows", f"{dsl1_result.matched_rows:,}", f"{ps_result.matched_rows:,}")
            summary_table.add_row("Match Rate", f"{dsl1_result.match_rate:.2f}%", f"{ps_result.match_rate:.2f}%")
            summary_table.add_row("Perfect Matches", f"{dsl1_result.perfect_matches:,}", f"{ps_result.perfect_matches:,}")
            summary_table.add_row("Date Mismatches", f"{dsl1_result.date_mismatches:,}", f"{ps_result.date_mismatches:,}")
            summary_table.add_row("Balance Mismatches", f"{dsl1_result.balance_mismatches:,}", f"{ps_result.balance_mismatches:,}")
            summary_table.add_row("Both Mismatched", f"{dsl1_result.both_mismatches:,}", f"{ps_result.both_mismatches:,}")
            summary_table.add_row("Accuracy Rate", f"{dsl1_result.accuracy_rate:.2f}%", f"{ps_result.accuracy_rate:.2f}%")
            summary_table.add_row("Debt Separation Cases", f"{dsl1_result.debt_separation_cases:,}", "N/A")
            summary_table.add_row("Duration", f"{dsl1_result.duration_seconds:.2f}s", f"{ps_result.duration_seconds:.2f}s")
            
            console.print(summary_table)
        
        if args.dry_run:
            log_info("Dry run complete. No files written.")
            return
        
        # Write outputs with progress bars
        log_write("Writing output files...")
        
        if RICH_AVAILABLE:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(bar_width=40),
                TaskProgressColumn(),
                TimeElapsedColumn(),
                TimeRemainingColumn(),
                console=console,
                transient=False
            ) as progress:
                
                # CSV output for DSL1 vs DSL2 errors
                if dsl1_result.error_records:
                    csv_task = progress.add_task("[write]Writing dsl1_dsl2_discrepancies.csv...", total=100)
                    csv_path = tmp_folder / "dsl1_dsl2_discrepancies.csv"
                    
                    start_timer("write_csv_dsl1")
                    error_df = pd.DataFrame(dsl1_result.error_records)
                    error_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
                    progress.update(csv_task, completed=100)
                    log_secure(f"CSV written: {csv_path}", "write_csv_dsl1")
                
                # CSV output for PS vs DSL2 errors
                if ps_result.error_records:
                    csv_task2 = progress.add_task("[write]Writing ps_dsl2_discrepancies.csv...", total=100)
                    csv_path2 = tmp_folder / "ps_dsl2_discrepancies.csv"
                    
                    start_timer("write_csv_ps")
                    error_df2 = pd.DataFrame(ps_result.error_records)
                    error_df2.to_csv(csv_path2, index=False, encoding="utf-8-sig")
                    progress.update(csv_task2, completed=100)
                    log_secure(f"CSV written: {csv_path2}", "write_csv_ps")
                
                # CSV output for Debt Separation cases
                if dsl1_result.debt_separation_records:
                    csv_task3 = progress.add_task("[write]Writing debt_separation_cases.csv...", total=100)
                    csv_path3 = tmp_folder / "debt_separation_cases.csv"
                    
                    start_timer("write_csv_debt")
                    debt_df = pd.DataFrame(dsl1_result.debt_separation_records)
                    debt_df.to_csv(csv_path3, index=False, encoding="utf-8-sig")
                    progress.update(csv_task3, completed=100)
                    log_secure(f"CSV written: {csv_path3}", "write_csv_debt")
                
                # HTML Artifact
                if args.web_report:
                    html_task = progress.add_task("[peach]Generating nexus_report.html...", total=100)
                    html_path = tmp_folder / "nexus_report.html"
                    generate_nexus_artifact(combined_result, html_path, progress, html_task)
                
                # Manifest
                manifest_task = progress.add_task("[secure]Generating manifest.json...", total=100)
                manifest = generate_manifest(combined_result, args.dsl1, args.dsl2, ps_folder, args.output, progress, manifest_task)
                manifest_path = tmp_folder / "manifest.json"
                
                start_timer("write_manifest")
                with open(manifest_path, "w", encoding="utf-8") as f:
                    json.dump(manifest, f, indent=2, ensure_ascii=False, default=iso_converter)
                log_secure(f"Manifest written: {manifest_path}", "write_manifest")
        else:
            # Non-rich fallback
            if dsl1_result.error_records:
                csv_path = tmp_folder / "dsl1_dsl2_discrepancies.csv"
                error_df = pd.DataFrame(dsl1_result.error_records)
                error_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
                print(f"CSV written: {csv_path}")
            
            if ps_result.error_records:
                csv_path2 = tmp_folder / "ps_dsl2_discrepancies.csv"
                error_df2 = pd.DataFrame(ps_result.error_records)
                error_df2.to_csv(csv_path2, index=False, encoding="utf-8-sig")
                print(f"CSV written: {csv_path2}")
            
            if dsl1_result.debt_separation_records:
                csv_path3 = tmp_folder / "debt_separation_cases.csv"
                debt_df = pd.DataFrame(dsl1_result.debt_separation_records)
                debt_df.to_csv(csv_path3, index=False, encoding="utf-8-sig")
                print(f"CSV written: {csv_path3}")
            
            if args.web_report:
                html_path = tmp_folder / "nexus_report.html"
                generate_nexus_artifact(combined_result, html_path)
            
            manifest = generate_manifest(combined_result, args.dsl1, args.dsl2, ps_folder, args.output)
            manifest_path = tmp_folder / "manifest.json"
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False, default=iso_converter)
            print(f"Manifest written: {manifest_path}")
        
        # Atomic move from tmp to final
        start_timer("atomic_move")
        log_write("Moving files to final destination...")
        
        import shutil
        for f in tmp_folder.iterdir():
            final_path = args.output / f.name
            if final_path.exists():
                final_path.unlink()
            shutil.move(str(f), str(final_path))
        
        tmp_folder.rmdir()
        
        log_secure("Files moved to final destination", "atomic_move")
        log_secure("✨ Reconciliation complete!")
        
        # Final stats panel
        if console:
            total_rows = dsl1_result.total_dsl1_rows + dsl1_result.total_dsl2_rows + ps_result.total_ps_rows
            total_duration = dsl1_result.duration_seconds + ps_result.duration_seconds
            
            console.print(Panel(
                f"[bold green]EXECUTION COMPLETE[/bold green]\n\n"
                f"📊 Processed {total_rows:,} total rows\n"
                f"⚡ Speed: {total_rows / max(total_duration, 0.001):,.0f} rows/sec\n"
                f"🔍 Debt Separation Cases: {dsl1_result.debt_separation_cases:,}\n"
                f"📁 Output: {args.output}",
                border_style="green",
                title="NEXUS GRILL SUMMIT"
            ))
        
    except Exception as e:
        log_fatal(f"Execution failed: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

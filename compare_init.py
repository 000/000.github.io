#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  RECALC TOOLKIT: DSL1 ↔ DSL2 RECONCILIATION ENGINE                          ║
║  Codename: "NEXUS GRILL"                                                     ║
║  Version: 2.1.0                                                              ║
║                                                                              ║
║  Purpose: Compare DSL1 (7.43M rows) vs DSL2 (4M+ rows) on:                  ║
║    - ACC_NO ↔ เลขบัญชี (Join Key)                                            ║
║    - FIRST_PAYMENT_DATE ↔ วันที่เริ่มชำระหนี้                                   ║
║    - PRE_BALANCE ↔ ยอดหนี้เงินกู้                                              ║
║                                                                              ║
║  Compliance: Nexus Protocol v2.0 / DoD DevSecOps Reference Design           ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import argparse
import hashlib
import json
import os
import sys
import time
import gc
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any

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
        MofNCompleteColumn, DownloadColumn, TransferSpeedColumn
    )
    from rich.table import Table
    from rich.layout import Layout
    from rich.live import Live
    from rich.text import Text
    from rich.style import Style
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
# NEXUS THEME CONFIGURATION (Pantone 2024: Peach Fuzz)
# ══════════════════════════════════════════════════════════════════════════════

class NexusTheme:
    """Pantone-compliant color theming for CLI aesthetics."""
    
    THEMES = {
        "peach-fuzz": {  # Pantone 2024
            "primary": "#FFBE98",
            "accent": "#FF9A5C",
            "success": "#00FF88",
            "warning": "#FFD93D",
            "error": "#FF4757",
            "info": "#74B9FF",
            "muted": "#636E72",
            "neon_core": "#3B82F6",
            "neon_accent": "#06B6D4",
        },
        "viva-magenta": {  # Pantone 2023
            "primary": "#BE3455",
            "accent": "#FF6B9D",
            "success": "#00FF88",
            "warning": "#FFD93D",
            "error": "#FF4757",
            "info": "#74B9FF",
            "muted": "#636E72",
            "neon_core": "#BE3455",
            "neon_accent": "#FF6B9D",
        }
    }
    
    def __init__(self, theme_name: str = "peach-fuzz"):
        self.colors = self.THEMES.get(theme_name, self.THEMES["peach-fuzz"])
    
    def style(self, key: str) -> str:
        return self.colors.get(key, "#FFFFFF")


# ══════════════════════════════════════════════════════════════════════════════
# CONSOLE & LOGGING INFRASTRUCTURE
# ══════════════════════════════════════════════════════════════════════════════

console = Console() if RICH_AVAILABLE else None
theme = NexusTheme("peach-fuzz")

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


def log_info(msg: str, operation_id: str = None):
    """Log informational message with Nexus styling and optional timing."""
    elapsed = get_elapsed(operation_id) if operation_id else ""
    if console:
        console.print(f"[dim]ℹ [INFO][/dim] {msg}[dim cyan]{elapsed}[/dim cyan]")
    else:
        print(f"ℹ [INFO] {msg}{elapsed}")


def log_success(msg: str, operation_id: str = None):
    """Log success message with neon green styling and optional timing."""
    elapsed = get_elapsed(operation_id) if operation_id else ""
    if console:
        console.print(f"[bold green]✅ [SUCCESS][/bold green] {msg}[dim cyan]{elapsed}[/dim cyan]")
    else:
        print(f"✅ [SUCCESS] {msg}{elapsed}")


def log_warning(msg: str):
    """Log warning with Pantone Yellow styling."""
    if console:
        console.print(f"[bold yellow]⚠ [WARN][/bold yellow] {msg}")
    else:
        print(f"⚠ [WARN] {msg}")


def log_error(msg: str):
    """Log fatal error with skull emoji."""
    if console:
        console.print(f"[bold red]☠ [FATAL][/bold red] {msg}")
    else:
        print(f"☠ [FATAL] {msg}")


def log_speed(msg: str):
    """Log performance optimization message."""
    if console:
        console.print(f"[bold cyan]⚡ [SPEED][/bold cyan] {msg}")
    else:
        print(f"⚡ [SPEED] {msg}")


def get_system_stats() -> Dict[str, str]:
    """Retrieve system RAM/CPU statistics."""
    stats = {"ram": "N/A", "cpu": "N/A", "ram_pct": "N/A"}
    if PSUTIL_AVAILABLE:
        mem = psutil.virtual_memory()
        stats["ram"] = f"{mem.used / (1024**3):.1f}GB / {mem.total / (1024**3):.1f}GB"
        stats["ram_pct"] = f"{mem.percent}%"
        stats["cpu"] = f"{psutil.cpu_percent(interval=0.1)}%"
    return stats


def render_header_panel(title: str, version: str = "2.1.0"):
    """Render the Nexus-style header panel."""
    if not console:
        print(f"\n{'='*70}\n{title} v{version}\n{'='*70}\n")
        return
    
    stats = get_system_stats()
    
    header_text = Text()
    header_text.append("╔══════════════════════════════════════════════════════════════╗\n", style="bold cyan")
    header_text.append(f"║  {title.center(58)}  ║\n", style="bold white")
    header_text.append(f"║  {'Version: ' + version:^58}  ║\n", style="dim")
    header_text.append("╠══════════════════════════════════════════════════════════════╣\n", style="bold cyan")
    header_text.append(f"║  RAM: {stats['ram']:20} │ CPU: {stats['cpu']:20}  ║\n", style="dim cyan")
    header_text.append("╚══════════════════════════════════════════════════════════════╝", style="bold cyan")
    
    console.print(Panel(
        header_text,
        border_style=theme.style("primary"),
        box=box.DOUBLE,
        padding=(0, 1)
    ))


# ══════════════════════════════════════════════════════════════════════════════
# INPUT HANDLING: "THE IRON GRIP"
# ══════════════════════════════════════════════════════════════════════════════

# Multi-encoding fallback chain per specification [Section 2.1]
ENCODING_CHAIN = ["utf-8-sig", "utf-8", "cp874", "iso-8859-11", "latin-1", "iso-8859-1"]

# Thai-specific encodings for DSL2
THAI_ENCODING_CHAIN = ["iso-8859-11", "cp874", "tis-620", "utf-8-sig", "utf-8", "latin-1"]


def detect_encoding(file_path: Path, sample_size: int = 65536) -> str:
    """
    Detect file encoding using multi-encoding fallback.
    Implements "The Iron Grip" pattern from Section 2.1.
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
    
    log_warning(f"All encodings failed for {file_path.name}, defaulting to latin-1")
    return "latin-1"


def safe_float(value: Any, default: float = 0.0) -> float:
    """
    Safe numeric conversion per Section 2.3.
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


def format_date_dsl1_output(date_obj: Any) -> str:
    """
    Format DSL1 date for output without the 00:00:00 portion.
    """
    if date_obj is None:
        return ""
    if isinstance(date_obj, datetime):
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


def detect_header_row_index(file_path: Path, encoding: str, target_columns: List[str]) -> int:
    """
    Detect which row contains the header by looking for target column names.
    Returns 0-based index of the header row.
    
    DSL2 files may have headers in the second row (index 1).
    """
    try:
        with open(file_path, "r", encoding=encoding, errors="replace") as f:
            # Read first 10 lines to find header
            for row_idx in range(10):
                line = f.readline()
                if not line:
                    break
                
                # Check if any target column is in this line
                for target_col in target_columns:
                    if target_col in line:
                        log_info(f"Header found at row {row_idx + 1} in {file_path.name}")
                        return row_idx
        
        # Default to first row if not found
        return 0
    except Exception as e:
        log_warning(f"Error detecting header row in {file_path.name}: {e}")
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
    return sha256.hexdigest()[:16]  # Truncated for readability


# ══════════════════════════════════════════════════════════════════════════════
# DATA LOADING: POLARS-FIRST STRATEGY WITH PANDAS FALLBACK
# ══════════════════════════════════════════════════════════════════════════════

def load_dsl1_polars(folder: Path, progress_callback=None) -> pl.LazyFrame:
    """
    Load DSL1 files using Polars for maximum performance.
    DSL1: ~7.43M rows, 7GB, YYYY-MM-DD 00:00:00 format
    
    Extracts only required columns:
    - ACC_NO (string, immutable identifier)
    - FIRST_PAYMENT_DATE
    - PRE_BALANCE
    """
    start_timer("load_dsl1")
    files = discover_files(folder)
    if not files:
        raise FileNotFoundError(f"No data files found in {folder}")
    
    log_info(f"Discovered {len(files)} file(s) in DSL1 folder")
    
    # Define schema for required columns only (memory optimization)
    required_cols = ["ACC_NO", "FIRST_PAYMENT_DATE", "PRE_BALANCE"]
    
    lazy_frames = []
    
    for file_path in files:
        file_start = time.time()
        encoding = detect_encoding(file_path)
        log_info(f"Loading {file_path.name} with encoding: {encoding}")
        
        try:
            # Use Polars lazy evaluation for memory efficiency
            # Map encoding to Polars-compatible encoding
            polars_encoding = "utf8" if encoding in ["utf-8", "utf-8-sig"] else "utf8"
            
            lf = pl.scan_csv(
                file_path,
                encoding=polars_encoding,
                ignore_errors=True,
                null_values=["", "null", "NULL", "N/A", "-"],
                infer_schema_length=10000,
                low_memory=True,
            )
            
            # FIX: Use collect_schema().names() to avoid PerformanceWarning
            available_cols = lf.collect_schema().names()
            select_cols = [c for c in required_cols if c in available_cols]
            
            if "ACC_NO" not in select_cols:
                log_error(f"Critical column ACC_NO missing in {file_path.name}")
                continue
            
            lf = lf.select(select_cols)
            
            # Cast ACC_NO to string (immutable identifier per Section 2.3)
            lf = lf.with_columns([
                pl.col("ACC_NO").cast(pl.Utf8).alias("ACC_NO")
            ])
            
            lazy_frames.append(lf)
            
            file_elapsed = time.time() - file_start
            log_info(f"Prepared {file_path.name} [{file_elapsed:.2f}s]")
            
            if progress_callback:
                progress_callback()
                
        except Exception as e:
            log_warning(f"Polars failed for {file_path.name}: {e}, trying fallback...")
            # Fallback handled separately
            continue
    
    if not lazy_frames:
        raise ValueError("No valid DSL1 files could be loaded")
    
    # Concatenate all lazy frames
    combined = pl.concat(lazy_frames)
    
    log_success(f"DSL1 LazyFrame prepared", "load_dsl1")
    
    return combined


def load_dsl2_polars(folder: Path, progress_callback=None) -> pl.LazyFrame:
    """
    Load DSL2 files using Polars.
    DSL2: ~4M rows, 1-1.5GB, Buddhist Era dates (DD/MM/YYYY BE)
    Header is in the SECOND row (index 1), not the first row.
    
    Extracts only required columns:
    - เลขบัญชี (ACC_NO equivalent)
    - วันที่เริ่มชำระหนี้ (FIRST_PAYMENT_DATE equivalent)
    - ยอดหนี้เงินกู้ (PRE_BALANCE equivalent)
    """
    start_timer("load_dsl2")
    files = discover_files(folder)
    if not files:
        raise FileNotFoundError(f"No data files found in {folder}")
    
    log_info(f"Discovered {len(files)} file(s) in DSL2 folder")
    
    # Thai column names
    required_cols = ["เลขบัญชี", "วันที่เริ่มชำระหนี้", "ยอดหนี้เงินกู้"]
    
    lazy_frames = []
    
    for file_path in files:
        file_start = time.time()
        encoding = detect_encoding(file_path)
        log_info(f"Loading {file_path.name} with encoding: {encoding}")
        
        # Detect which row contains the header
        header_row_idx = detect_header_row_index(file_path, encoding, required_cols)
        
        try:
            # For Thai encoding with header not in first row, use pandas first
            # then convert to Polars (more reliable for complex CSV parsing)
            if header_row_idx > 0 or encoding in THAI_ENCODING_CHAIN:
                # Use pandas for reliable Thai CSV parsing with skip rows
                df = pd.read_csv(
                    file_path,
                    encoding=encoding,
                    skiprows=header_row_idx,  # Skip rows before header
                    dtype={"เลขบัญชี": str},
                    low_memory=True,
                    on_bad_lines="skip"
                )
                
                # Check available columns
                available_cols = df.columns.tolist()
                
                # Find matching columns
                col_mapping = {}
                for req_col in required_cols:
                    if req_col in available_cols:
                        col_mapping[req_col] = req_col
                    else:
                        # Fuzzy match for encoding issues
                        for avail_col in available_cols:
                            if req_col in avail_col or avail_col in req_col:
                                col_mapping[req_col] = avail_col
                                break
                
                if "เลขบัญชี" not in col_mapping:
                    log_warning(f"Column เลขบัญชี not found in {file_path.name} columns: {available_cols[:5]}...")
                    continue
                
                # Select and rename columns
                df_selected = df[[col_mapping[c] for c in required_cols if c in col_mapping]].copy()
                df_selected.columns = [c for c in required_cols if c in col_mapping]
                
                # Ensure account number is string
                df_selected["เลขบัญชี"] = df_selected["เลขบัญชี"].astype(str)
                
                # Convert to Polars LazyFrame
                lf = pl.from_pandas(df_selected).lazy()
                
                lazy_frames.append(lf)
                
                file_elapsed = time.time() - file_start
                log_success(f"Loaded {file_path.name} via pandas ({len(df_selected):,} rows) [{file_elapsed:.2f}s]")
                
            else:
                # Standard Polars loading for UTF-8 files with header in first row
                lf = pl.scan_csv(
                    file_path,
                    encoding="utf8",
                    ignore_errors=True,
                    null_values=["", "null", "NULL", "N/A", "-"],
                    infer_schema_length=10000,
                    low_memory=True,
                )
                
                # FIX: Use collect_schema().names() to avoid PerformanceWarning
                available_cols = lf.collect_schema().names()
                
                # Find matching columns
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
                    log_warning(f"Column เลขบัญชี not found in {file_path.name}, trying pandas fallback")
                    continue
                
                # Select and rename columns
                select_exprs = []
                for req_col in required_cols:
                    if req_col in col_mapping:
                        select_exprs.append(pl.col(col_mapping[req_col]).alias(req_col))
                
                lf = lf.select(select_exprs)
                
                # Cast account number to string
                lf = lf.with_columns([
                    pl.col("เลขบัญชี").cast(pl.Utf8).alias("เลขบัญชี")
                ])
                
                lazy_frames.append(lf)
                
                file_elapsed = time.time() - file_start
                log_info(f"Prepared {file_path.name} [{file_elapsed:.2f}s]")
            
            if progress_callback:
                progress_callback()
                
        except Exception as e:
            log_warning(f"Failed to load {file_path.name}: {e}")
            continue
    
    if not lazy_frames:
        raise ValueError("No valid DSL2 files could be loaded")
    
    combined = pl.concat(lazy_frames)
    
    log_success(f"DSL2 LazyFrame prepared", "load_dsl2")
    
    return combined


def load_dsl1_pandas_fallback(folder: Path) -> pd.DataFrame:
    """Pandas fallback for DSL1 when Polars fails."""
    start_timer("load_dsl1_pandas")
    
    files = discover_files(folder)
    dfs = []
    
    required_cols = ["ACC_NO", "FIRST_PAYMENT_DATE", "PRE_BALANCE"]
    
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
                log_success(f"Loaded {file_path.name} with pandas ({enc}) [{file_elapsed:.2f}s]")
                break
            except Exception:
                continue
    
    if not dfs:
        raise ValueError("No valid DSL1 files could be loaded with pandas")
    
    result = pd.concat(dfs, ignore_index=True)
    log_success(f"DSL1 pandas loading complete ({len(result):,} rows)", "load_dsl1_pandas")
    
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
        
        # Detect header row
        header_row_idx = detect_header_row_index(file_path, encoding, required_cols)
        
        for enc in THAI_ENCODING_CHAIN:
            try:
                df = pd.read_csv(
                    file_path,
                    encoding=enc,
                    skiprows=header_row_idx,  # Skip rows before header
                    dtype={"เลขบัญชี": str},
                    low_memory=True,
                    on_bad_lines="skip"
                )
                
                # Filter to required columns
                available = [c for c in required_cols if c in df.columns]
                if "เลขบัญชี" in available:
                    df = df[available].copy()
                    dfs.append(df)
                    file_elapsed = time.time() - file_start
                    log_success(f"Loaded {file_path.name} with pandas ({enc}, {len(df):,} rows) [{file_elapsed:.2f}s]")
                    break
            except Exception as e:
                continue
    
    if not dfs:
        raise ValueError("No valid DSL2 files could be loaded with pandas")
    
    result = pd.concat(dfs, ignore_index=True)
    log_success(f"DSL2 pandas loading complete ({len(result):,} rows)", "load_dsl2_pandas")
    
    return result


# ══════════════════════════════════════════════════════════════════════════════
# RECONCILIATION ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class ReconciliationResult:
    """Container for reconciliation results and statistics."""
    
    def __init__(self):
        self.total_dsl1_rows: int = 0
        self.total_dsl2_rows: int = 0
        self.matched_rows: int = 0
        self.unmatched_dsl1: int = 0
        self.unmatched_dsl2: int = 0
        
        # Discrepancy counts
        self.date_mismatches: int = 0
        self.balance_mismatches: int = 0
        self.both_mismatches: int = 0
        self.perfect_matches: int = 0
        
        # Error margin statistics
        self.balance_errors: List[float] = []
        self.date_diff_days: List[int] = []
        
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
        if not self.balance_errors:
            return {"mean": 0, "median": 0, "std": 0, "min": 0, "max": 0, "p95": 0, "p99": 0}
        
        arr = np.array(self.balance_errors)
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
        if not self.date_diff_days:
            return {"mean": 0, "median": 0, "std": 0, "min": 0, "max": 0}
        
        arr = np.array(self.date_diff_days)
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
            "total_dsl2_rows": self.total_dsl2_rows,
            "matched_rows": self.matched_rows,
            "unmatched_dsl1": self.unmatched_dsl1,
            "unmatched_dsl2": self.unmatched_dsl2,
            "date_mismatches": self.date_mismatches,
            "balance_mismatches": self.balance_mismatches,
            "both_mismatches": self.both_mismatches,
            "perfect_matches": self.perfect_matches,
            "match_rate_pct": round(self.match_rate, 2),
            "error_rate_pct": round(self.error_rate, 2),
            "accuracy_rate_pct": round(self.accuracy_rate, 2),
            "balance_error_stats": self.balance_error_stats,
            "date_diff_stats": self.date_diff_stats,
            "duration_seconds": round(self.duration_seconds, 2),
            "error_count": len(self.error_records),
        }


def reconcile_datasets(
    dsl1_data: pl.DataFrame,
    dsl2_data: pl.DataFrame,
    balance_tolerance: float = 0.01,
    max_error_records: int = 100000,
    progress: Progress = None,
    task_id = None
) -> ReconciliationResult:
    """
    Perform vectorized reconciliation between DSL1 and DSL2 datasets.
    
    Comparison Logic:
    - Join on ACC_NO = เลขบัญชี
    - Compare FIRST_PAYMENT_DATE vs วันที่เริ่มชำระหนี้
    - Compare PRE_BALANCE vs ยอดหนี้เงินกู้
    
    "Grill" DSL2 for discrepancies and calculate error margins.
    """
    result = ReconciliationResult()
    result.start_time = time.time()
    
    start_timer("reconcile")
    log_info("Starting vectorized reconciliation...")
    
    # Record row counts
    result.total_dsl1_rows = len(dsl1_data)
    result.total_dsl2_rows = len(dsl2_data)
    
    log_info(f"DSL1 rows: {result.total_dsl1_rows:,}")
    log_info(f"DSL2 rows: {result.total_dsl2_rows:,}")
    
    total_steps = 10
    current_step = 0
    
    def update_progress():
        nonlocal current_step
        current_step += 1
        if progress and task_id:
            progress.update(task_id, completed=current_step * 10)
    
    # Normalize account numbers for joining
    start_timer("normalize")
    log_info("Normalizing account numbers...")
    
    dsl1_normalized = dsl1_data.with_columns([
        pl.col("ACC_NO").str.strip_chars().str.replace_all(r"^0+", "").alias("ACC_NO_NORM")
    ])
    
    dsl2_normalized = dsl2_data.with_columns([
        pl.col("เลขบัญชี").str.strip_chars().str.replace_all(r"^0+", "").alias("ACC_NO_NORM")
    ])
    
    log_info("Account numbers normalized", "normalize")
    update_progress()
    
    # Perform left join (DSL2 as base, grilling DSL2 against DSL1)
    start_timer("join")
    log_info("Performing join operation...")
    
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
        log_warning("No matching records found between datasets!")
        result.end_time = time.time()
        return result
    
    # Parse and compare dates
    start_timer("parse_dates")
    log_info("Parsing and comparing dates...")
    
    # Convert to Python for date parsing (Polars date parsing is limited for custom formats)
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
    log_info("Parsing and comparing balances...")
    
    matched_pd["BAL_DSL1"] = matched_pd["PRE_BALANCE"].apply(safe_float)
    matched_pd["BAL_DSL2"] = matched_pd["ยอดหนี้เงินกู้"].apply(safe_float)
    
    log_info("Balance parsing complete", "parse_balances")
    update_progress()
    
    # Calculate discrepancies
    start_timer("calc_discrepancies")
    log_info("Calculating discrepancies...")
    
    # Date comparison (both must be valid for comparison)
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
    
    # Balance comparison with tolerance
    matched_pd["BAL_DIFF"] = matched_pd["BAL_DSL2"] - matched_pd["BAL_DSL1"]
    matched_pd["BAL_DIFF_ABS"] = matched_pd["BAL_DIFF"].abs()
    matched_pd["BAL_DIFF_PCT"] = np.where(
        matched_pd["BAL_DSL1"] != 0,
        (matched_pd["BAL_DIFF_ABS"] / matched_pd["BAL_DSL1"].abs()) * 100,
        np.where(matched_pd["BAL_DSL2"] != 0, 100, 0)
    )
    matched_pd["BAL_MATCH"] = matched_pd["BAL_DIFF_ABS"] <= balance_tolerance
    
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
    
    # Collect error statistics
    error_mask = ~matched_pd["DATE_MATCH"] | ~matched_pd["BAL_MATCH"]
    error_rows = matched_pd[error_mask]
    
    result.balance_errors = error_rows["BAL_DIFF"].tolist()
    result.date_diff_days = error_rows.loc[valid_dates_mask & error_mask, "DATE_DIFF_DAYS"].tolist()
    
    # Collect detailed error records (limited for memory)
    start_timer("collect_errors")
    log_info(f"Collecting error records (max {max_error_records:,})...")
    
    error_sample = error_rows.head(max_error_records)
    
    for _, row in error_sample.iterrows():
        record = {
            "ACC_NO": str(row.get("เลขบัญชี", "")),
            # FIX: Format DATE_DSL1 without 00:00:00
            "DATE_DSL1": format_date_dsl1_output(row.get("DATE_DSL1", "")),
            "DATE_DSL2": str(row.get("วันที่เริ่มชำระหนี้", "")),
            "DATE_MATCH": bool(row.get("DATE_MATCH", False)),
            "DATE_DIFF_DAYS": int(row.get("DATE_DIFF_DAYS", 0)),
            "BAL_DSL1": float(row.get("BAL_DSL1", 0)),
            "BAL_DSL2": float(row.get("BAL_DSL2", 0)),
            "BAL_MATCH": bool(row.get("BAL_MATCH", False)),
            "BAL_DIFF": float(row.get("BAL_DIFF", 0)),
            # FIX: Round BAL_DIFF_PCT to 4 decimal places
            "BAL_DIFF_PCT": round(float(row.get("BAL_DIFF_PCT", 0)), 4),
        }
        result.error_records.append(record)
    
    log_info(f"Collected {len(result.error_records):,} error records", "collect_errors")
    update_progress()
    
    result.end_time = time.time()
    
    log_success(f"Reconciliation complete", "reconcile")
    
    return result


# ══════════════════════════════════════════════════════════════════════════════
# NEXUS ARTIFACT GENERATOR
# ══════════════════════════════════════════════════════════════════════════════

def generate_nexus_artifact(
    result: ReconciliationResult,
    output_path: Path,
    theme_name: str = "peach-fuzz",
    progress: Progress = None,
    task_id = None
) -> None:
    """
    Generate the Nexus-Grade HTML Artifact per Section 4.1.
    
    Features:
    - Zero-dependency single file
    - Dark mode with Glassmorphism
    - D3.js visualizations
    - Slide-over detail panels
    - Particle background atmosphere
    """
    start_timer("generate_html")
    log_info("Generating Nexus HTML artifact...")
    
    stats = result.to_dict()
    
    if progress and task_id:
        progress.update(task_id, completed=10)
    
    # Prepare error records JSON (limit for browser performance)
    log_info("Serializing error records to JSON...")
    error_records_json = json.dumps(result.error_records[:10000])
    stats_json = json.dumps(stats)
    
    if progress and task_id:
        progress.update(task_id, completed=30)
    
    # Calculate histogram data for balance errors
    log_info("Calculating histogram data...")
    if result.balance_errors:
        # Filter outliers for histogram
        filtered_errors = [e for e in result.balance_errors if abs(e) < np.percentile(np.abs(result.balance_errors), 99)]
        if filtered_errors:
            hist_values, hist_edges = np.histogram(filtered_errors, bins=50)
            histogram_data = json.dumps({
                "values": hist_values.tolist(),
                "edges": hist_edges.tolist()
            })
        else:
            histogram_data = json.dumps({"values": [], "edges": []})
    else:
        histogram_data = json.dumps({"values": [], "edges": []})
    
    if progress and task_id:
        progress.update(task_id, completed=50)
    
    # Theme colors
    theme_obj = NexusTheme(theme_name)
    
    log_info("Building HTML content...")
    
    html_content = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RECALC NEXUS ARTIFACT | DSL1 ↔ DSL2 Reconciliation</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://d3js.org/d3.v7.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {{
            --space-void: #0a0a1a;
            --space-deep: #0d1025;
            --glass-panel: rgba(21, 29, 46, 0.7);
            --glass-border: rgba(59, 130, 246, 0.2);
            --neon-core: {theme_obj.style("neon_core")};
            --neon-accent: {theme_obj.style("neon_accent")};
            --neon-success: {theme_obj.style("success")};
            --neon-warning: {theme_obj.style("warning")};
            --neon-error: {theme_obj.style("error")};
            --pantone-primary: {theme_obj.style("primary")};
        }}
        
        * {{ box-sizing: border-box; }}
        
        body {{
            background: linear-gradient(135deg, var(--space-void) 0%, var(--space-deep) 100%);
            color: #e2e8f0;
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            min-height: 100vh;
            overflow-x: hidden;
        }}
        
        .glass {{
            background: var(--glass-panel);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border: 1px solid var(--glass-border);
            border-radius: 16px;
        }}
        
        .glass-hover:hover {{
            border-color: var(--neon-core);
            box-shadow: 0 0 30px rgba(59, 130, 246, 0.3);
            transform: translateY(-2px);
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }}
        
        .gradient-text {{
            background: linear-gradient(135deg, var(--neon-core), var(--neon-accent));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }}
        
        .detail-panel {{
            position: fixed;
            top: 0;
            right: 0;
            bottom: 0;
            width: 500px;
            max-width: 90vw;
            background: rgba(13, 16, 37, 0.98);
            border-left: 1px solid rgba(255, 255, 255, 0.1);
            backdrop-filter: blur(20px);
            z-index: 2000;
            transform: translateX(100%);
            transition: transform 0.4s cubic-bezier(0.16, 1, 0.3, 1);
            overflow-y: auto;
        }}
        
        .detail-panel.open {{ transform: translateX(0); }}
        
        .detail-panel-overlay {{
            position: fixed;
            inset: 0;
            background: rgba(0, 0, 0, 0.5);
            z-index: 1999;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.3s ease;
        }}
        
        .detail-panel-overlay.open {{
            opacity: 1;
            pointer-events: auto;
        }}
        
        .data-table {{ width: 100%; border-collapse: collapse; }}
        
        .data-table th {{
            background: rgba(59, 130, 246, 0.2);
            padding: 12px 16px;
            text-align: left;
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--neon-accent);
            position: sticky;
            top: 0;
            z-index: 10;
        }}
        
        .data-table td {{
            padding: 12px 16px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.85rem;
        }}
        
        .data-table tr:hover {{
            background: rgba(59, 130, 246, 0.1);
            cursor: pointer;
        }}
        
        .data-table tr.error-row {{ border-left: 3px solid var(--neon-error); }}
        
        .stat-card {{ position: relative; overflow: hidden; }}
        
        .stat-card::before {{
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 3px;
            background: linear-gradient(90deg, var(--neon-core), var(--neon-accent));
        }}
        
        .stat-value {{
            font-size: 2.5rem;
            font-weight: 700;
            font-family: 'JetBrains Mono', monospace;
        }}
        
        .progress-bar {{
            height: 8px;
            background: rgba(255, 255, 255, 0.1);
            border-radius: 4px;
            overflow: hidden;
        }}
        
        .progress-fill {{
            height: 100%;
            border-radius: 4px;
            transition: width 1s cubic-bezier(0.4, 0, 0.2, 1);
        }}
        
        ::-webkit-scrollbar {{ width: 8px; height: 8px; }}
        ::-webkit-scrollbar-track {{ background: rgba(255, 255, 255, 0.05); }}
        ::-webkit-scrollbar-thumb {{ background: rgba(59, 130, 246, 0.5); border-radius: 4px; }}
        ::-webkit-scrollbar-thumb:hover {{ background: rgba(59, 130, 246, 0.8); }}
        
        .chart-container {{ position: relative; height: 300px; }}
    </style>
</head>
<body>
    <canvas id="bg-canvas" class="fixed inset-0 z-0 pointer-events-none"></canvas>
    
    <div class="relative z-10 max-w-7xl mx-auto p-6 lg:p-8">
        
        <header class="glass p-6 mb-8 flex flex-col lg:flex-row justify-between items-start lg:items-center gap-4">
            <div>
                <h1 class="text-3xl lg:text-4xl font-bold gradient-text mb-2">
                    RECONCILIATION ARTIFACT
                </h1>
                <p class="text-gray-400 text-sm">
                    DSL1 ↔ DSL2 Comparison Analysis | Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                </p>
            </div>
            <div class="flex items-center gap-6">
                <div class="text-right">
                    <div class="text-xs text-gray-500 uppercase tracking-wider">Match Rate</div>
                    <div class="text-2xl font-mono font-bold" style="color: var(--neon-success)">
                        {result.match_rate:.1f}%
                    </div>
                </div>
                <div class="text-right">
                    <div class="text-xs text-gray-500 uppercase tracking-wider">Accuracy</div>
                    <div class="text-2xl font-mono font-bold" style="color: var(--neon-accent)">
                        {result.accuracy_rate:.1f}%
                    </div>
                </div>
            </div>
        </header>
        
        <div class="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
            <div class="glass stat-card p-6 glass-hover">
                <h3 class="text-gray-400 text-xs tracking-widest uppercase mb-2">DSL1 Rows</h3>
                <p class="stat-value text-white">{result.total_dsl1_rows:,}</p>
            </div>
            <div class="glass stat-card p-6 glass-hover">
                <h3 class="text-gray-400 text-xs tracking-widest uppercase mb-2">DSL2 Rows</h3>
                <p class="stat-value text-white">{result.total_dsl2_rows:,}</p>
            </div>
            <div class="glass stat-card p-6 glass-hover">
                <h3 class="text-gray-400 text-xs tracking-widest uppercase mb-2">Matched</h3>
                <p class="stat-value" style="color: var(--neon-success)">{result.matched_rows:,}</p>
            </div>
            <div class="glass stat-card p-6 glass-hover" style="--glass-border: rgba(239, 68, 68, 0.3)">
                <h3 class="text-gray-400 text-xs tracking-widest uppercase mb-2">Discrepancies</h3>
                <p class="stat-value" style="color: var(--neon-error)">{result.date_mismatches + result.balance_mismatches + result.both_mismatches:,}</p>
            </div>
        </div>
        
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-8">
            <div class="glass p-6">
                <div class="flex items-center justify-between mb-4">
                    <h3 class="text-sm font-medium text-gray-300">Date Mismatches Only</h3>
                    <span class="text-2xl font-mono font-bold" style="color: var(--neon-warning)">{result.date_mismatches:,}</span>
                </div>
                <div class="progress-bar">
                    <div class="progress-fill" style="width: {(result.date_mismatches / max(result.matched_rows, 1)) * 100:.1f}%; background: var(--neon-warning)"></div>
                </div>
                <p class="text-xs text-gray-500 mt-2">{(result.date_mismatches / max(result.matched_rows, 1)) * 100:.2f}% of matched records</p>
            </div>
            <div class="glass p-6">
                <div class="flex items-center justify-between mb-4">
                    <h3 class="text-sm font-medium text-gray-300">Balance Mismatches Only</h3>
                    <span class="text-2xl font-mono font-bold" style="color: var(--neon-error)">{result.balance_mismatches:,}</span>
                </div>
                <div class="progress-bar">
                    <div class="progress-fill" style="width: {(result.balance_mismatches / max(result.matched_rows, 1)) * 100:.1f}%; background: var(--neon-error)"></div>
                </div>
                <p class="text-xs text-gray-500 mt-2">{(result.balance_mismatches / max(result.matched_rows, 1)) * 100:.2f}% of matched records</p>
            </div>
            <div class="glass p-6">
                <div class="flex items-center justify-between mb-4">
                    <h3 class="text-sm font-medium text-gray-300">Both Mismatched</h3>
                    <span class="text-2xl font-mono font-bold" style="color: #ff6b9d">{result.both_mismatches:,}</span>
                </div>
                <div class="progress-bar">
                    <div class="progress-fill" style="width: {(result.both_mismatches / max(result.matched_rows, 1)) * 100:.1f}%; background: linear-gradient(90deg, var(--neon-warning), var(--neon-error))"></div>
                </div>
                <p class="text-xs text-gray-500 mt-2">{(result.both_mismatches / max(result.matched_rows, 1)) * 100:.2f}% of matched records</p>
            </div>
        </div>
        
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
            <div class="glass p-6">
                <h3 class="text-lg font-semibold gradient-text mb-4">Balance Error Distribution (DSL2 - DSL1)</h3>
                <div class="chart-container">
                    <canvas id="balanceHistogram"></canvas>
                </div>
                <div class="grid grid-cols-3 gap-4 mt-4 text-center">
                    <div>
                        <div class="text-xs text-gray-500 uppercase">Mean Error</div>
                        <div class="text-lg font-mono" style="color: var(--neon-accent)">{result.balance_error_stats.get('mean', 0):,.2f}</div>
                    </div>
                    <div>
                        <div class="text-xs text-gray-500 uppercase">Median Error</div>
                        <div class="text-lg font-mono" style="color: var(--neon-accent)">{result.balance_error_stats.get('median', 0):,.2f}</div>
                    </div>
                    <div>
                        <div class="text-xs text-gray-500 uppercase">Std Dev</div>
                        <div class="text-lg font-mono" style="color: var(--neon-accent)">{result.balance_error_stats.get('std', 0):,.2f}</div>
                    </div>
                </div>
            </div>
            
            <div class="glass p-6">
                <h3 class="text-lg font-semibold gradient-text mb-4">Discrepancy Classification</h3>
                <div class="chart-container">
                    <canvas id="errorPieChart"></canvas>
                </div>
            </div>
        </div>
        
        <div class="glass p-6 mb-8">
            <h3 class="text-lg font-semibold gradient-text mb-4">Balance Error Range Analysis</h3>
            <div class="grid grid-cols-2 lg:grid-cols-5 gap-4">
                <div class="text-center p-4 rounded-lg" style="background: rgba(59, 130, 246, 0.1)">
                    <div class="text-xs text-gray-500 uppercase mb-1">Minimum</div>
                    <div class="text-xl font-mono font-bold" style="color: var(--neon-success)">{result.balance_error_stats.get('min', 0):,.2f}</div>
                </div>
                <div class="text-center p-4 rounded-lg" style="background: rgba(59, 130, 246, 0.1)">
                    <div class="text-xs text-gray-500 uppercase mb-1">Maximum</div>
                    <div class="text-xl font-mono font-bold" style="color: var(--neon-error)">{result.balance_error_stats.get('max', 0):,.2f}</div>
                </div>
                <div class="text-center p-4 rounded-lg" style="background: rgba(59, 130, 246, 0.1)">
                    <div class="text-xs text-gray-500 uppercase mb-1">P95</div>
                    <div class="text-xl font-mono font-bold" style="color: var(--neon-warning)">{result.balance_error_stats.get('p95', 0):,.2f}</div>
                </div>
                <div class="text-center p-4 rounded-lg" style="background: rgba(59, 130, 246, 0.1)">
                    <div class="text-xs text-gray-500 uppercase mb-1">P99</div>
                    <div class="text-xl font-mono font-bold" style="color: var(--neon-warning)">{result.balance_error_stats.get('p99', 0):,.2f}</div>
                </div>
                <div class="text-center p-4 rounded-lg" style="background: rgba(59, 130, 246, 0.1)">
                    <div class="text-xs text-gray-500 uppercase mb-1">Range</div>
                    <div class="text-xl font-mono font-bold" style="color: var(--pantone-primary)">{result.balance_error_stats.get('max', 0) - result.balance_error_stats.get('min', 0):,.2f}</div>
                </div>
            </div>
        </div>
        
        <div class="glass p-6 mb-8">
            <div class="flex justify-between items-center mb-4">
                <h3 class="text-lg font-semibold gradient-text">Discrepancy Records</h3>
                <div class="flex items-center gap-4">
                    <input type="text" id="searchInput" placeholder="Search ACC_NO..." 
                           class="px-4 py-2 rounded-lg bg-gray-800 border border-gray-700 text-sm focus:border-blue-500 focus:outline-none">
                    <span class="text-sm text-gray-500">Showing <span id="recordCount">0</span> records</span>
                </div>
            </div>
            <div class="overflow-x-auto max-h-[500px] overflow-y-auto">
                <table class="data-table" id="errorTable">
                    <thead>
                        <tr>
                            <th>ACC_NO</th>
                            <th>Date (DSL1)</th>
                            <th>Date (DSL2)</th>
                            <th>Date Match</th>
                            <th>Balance (DSL1)</th>
                            <th>Balance (DSL2)</th>
                            <th>Difference</th>
                            <th>Diff %</th>
                        </tr>
                    </thead>
                    <tbody id="errorTableBody"></tbody>
                </table>
            </div>
        </div>
        
        <div class="glass p-6">
            <h3 class="text-lg font-semibold gradient-text mb-4">Execution Metadata</h3>
            <div class="grid grid-cols-2 lg:grid-cols-4 gap-4 text-sm">
                <div>
                    <span class="text-gray-500">Duration:</span>
                    <span class="font-mono ml-2">{result.duration_seconds:.2f}s</span>
                </div>
                <div>
                    <span class="text-gray-500">Records/sec:</span>
                    <span class="font-mono ml-2">{(result.total_dsl1_rows + result.total_dsl2_rows) / max(result.duration_seconds, 0.001):,.0f}</span>
                </div>
                <div>
                    <span class="text-gray-500">Error Records Captured:</span>
                    <span class="font-mono ml-2">{len(result.error_records):,}</span>
                </div>
                <div>
                    <span class="text-gray-500">Unmatched DSL2:</span>
                    <span class="font-mono ml-2">{result.unmatched_dsl2:,}</span>
                </div>
            </div>
        </div>
        
    </div>
    
    <div id="panelOverlay" class="detail-panel-overlay" onclick="closePanel()"></div>
    <aside id="detailPanel" class="detail-panel p-6">
        <div class="flex justify-between items-center mb-6">
            <h2 class="text-xl font-bold gradient-text">Record Details</h2>
            <button onclick="closePanel()" class="text-gray-400 hover:text-white text-2xl">×</button>
        </div>
        <div id="panelContent" class="space-y-4"></div>
    </aside>
    
    <script>
        const STATS = {stats_json};
        const ERROR_RECORDS = {error_records_json};
        const HISTOGRAM_DATA = {histogram_data};
        
        (function initParticles() {{
            const canvas = document.getElementById('bg-canvas');
            const ctx = canvas.getContext('2d');
            let particles = [];
            const particleCount = 80;
            
            function resize() {{
                canvas.width = window.innerWidth;
                canvas.height = window.innerHeight;
            }}
            
            function createParticle() {{
                return {{
                    x: Math.random() * canvas.width,
                    y: Math.random() * canvas.height,
                    vx: (Math.random() - 0.5) * 0.5,
                    vy: (Math.random() - 0.5) * 0.5,
                    radius: Math.random() * 2 + 1,
                    opacity: Math.random() * 0.5 + 0.2
                }};
            }}
            
            function init() {{
                resize();
                particles = Array.from({{ length: particleCount }}, createParticle);
            }}
            
            function draw() {{
                ctx.clearRect(0, 0, canvas.width, canvas.height);
                
                particles.forEach((p, i) => {{
                    p.x += p.vx;
                    p.y += p.vy;
                    
                    if (p.x < 0) p.x = canvas.width;
                    if (p.x > canvas.width) p.x = 0;
                    if (p.y < 0) p.y = canvas.height;
                    if (p.y > canvas.height) p.y = 0;
                    
                    ctx.beginPath();
                    ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
                    ctx.fillStyle = `rgba(59, 130, 246, ${{p.opacity}})`;
                    ctx.fill();
                    
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
            
            window.addEventListener('resize', resize);
            init();
            draw();
        }})();
        
        (function initBalanceHistogram() {{
            const ctx = document.getElementById('balanceHistogram').getContext('2d');
            
            if (!HISTOGRAM_DATA.edges || HISTOGRAM_DATA.edges.length === 0) return;
            
            const labels = HISTOGRAM_DATA.edges.slice(0, -1).map((e, i) => {{
                const next = HISTOGRAM_DATA.edges[i + 1];
                return `${{e.toFixed(0)}} - ${{next.toFixed(0)}}`;
            }});
            
            new Chart(ctx, {{
                type: 'bar',
                data: {{
                    labels: labels.length > 20 ? labels.filter((_, i) => i % 2 === 0) : labels,
                    datasets: [{{
                        label: 'Frequency',
                        data: labels.length > 20 ? HISTOGRAM_DATA.values.filter((_, i) => i % 2 === 0) : HISTOGRAM_DATA.values,
                        backgroundColor: 'rgba(59, 130, 246, 0.6)',
                        borderColor: 'rgba(59, 130, 246, 1)',
                        borderWidth: 1
                    }}]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {{ legend: {{ display: false }} }},
                    scales: {{
                        x: {{ display: false, grid: {{ color: 'rgba(255,255,255,0.05)' }} }},
                        y: {{ grid: {{ color: 'rgba(255,255,255,0.05)' }}, ticks: {{ color: '#9ca3af' }} }}
                    }}
                }}
            }});
        }})();
        
        (function initPieChart() {{
            const ctx = document.getElementById('errorPieChart').getContext('2d');
            
            new Chart(ctx, {{
                type: 'doughnut',
                data: {{
                    labels: ['Perfect Match', 'Date Only', 'Balance Only', 'Both'],
                    datasets: [{{
                        data: [
                            STATS.perfect_matches,
                            STATS.date_mismatches,
                            STATS.balance_mismatches,
                            STATS.both_mismatches
                        ],
                        backgroundColor: [
                            'rgba(0, 255, 136, 0.8)',
                            'rgba(255, 217, 61, 0.8)',
                            'rgba(255, 71, 87, 0.8)',
                            'rgba(255, 107, 157, 0.8)'
                        ],
                        borderColor: [
                            'rgba(0, 255, 136, 1)',
                            'rgba(255, 217, 61, 1)',
                            'rgba(255, 71, 87, 1)',
                            'rgba(255, 107, 157, 1)'
                        ],
                        borderWidth: 2
                    }}]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {{
                        legend: {{
                            position: 'bottom',
                            labels: {{ color: '#9ca3af', padding: 20 }}
                        }}
                    }},
                    cutout: '60%'
                }}
            }});
        }})();
        
        let displayedRecords = ERROR_RECORDS.slice(0, 500);
        
        function formatNumber(num) {{
            return new Intl.NumberFormat('en-US', {{ maximumFractionDigits: 2 }}).format(num);
        }}
        
        function renderTable(records) {{
            const tbody = document.getElementById('errorTableBody');
            tbody.innerHTML = '';
            
            records.forEach((record, idx) => {{
                const row = document.createElement('tr');
                row.className = 'error-row';
                row.onclick = () => openPanel(record);
                
                const dateMatch = record.DATE_MATCH ? 
                    '<span style="color: var(--neon-success)">✓</span>' : 
                    '<span style="color: var(--neon-error)">✗</span>';
                
                const diffColor = Math.abs(record.BAL_DIFF) > 1000 ? 'var(--neon-error)' : 
                                  Math.abs(record.BAL_DIFF) > 100 ? 'var(--neon-warning)' : 'var(--neon-success)';
                
                row.innerHTML = `
                    <td class="font-bold">${{record.ACC_NO}}</td>
                    <td>${{record.DATE_DSL1 || '-'}}</td>
                    <td>${{record.DATE_DSL2 || '-'}}</td>
                    <td class="text-center">${{dateMatch}}</td>
                    <td class="text-right">${{formatNumber(record.BAL_DSL1)}}</td>
                    <td class="text-right">${{formatNumber(record.BAL_DSL2)}}</td>
                    <td class="text-right" style="color: ${{diffColor}}">${{formatNumber(record.BAL_DIFF)}}</td>
                    <td class="text-right" style="color: ${{diffColor}}">${{record.BAL_DIFF_PCT.toFixed(4)}}%</td>
                `;
                
                tbody.appendChild(row);
            }});
            
            document.getElementById('recordCount').textContent = records.length.toLocaleString();
        }}
        
        document.getElementById('searchInput').addEventListener('input', (e) => {{
            const query = e.target.value.toLowerCase();
            const filtered = ERROR_RECORDS.filter(r => 
                r.ACC_NO.toLowerCase().includes(query)
            ).slice(0, 500);
            renderTable(filtered);
        }});
        
        renderTable(displayedRecords);
        
        function openPanel(record) {{
            const panel = document.getElementById('detailPanel');
            const overlay = document.getElementById('panelOverlay');
            const content = document.getElementById('panelContent');
            
            content.innerHTML = `
                <div class="glass p-4">
                    <h4 class="text-xs text-gray-500 uppercase tracking-wider mb-2">Account Number</h4>
                    <p class="text-2xl font-mono font-bold gradient-text">${{record.ACC_NO}}</p>
                </div>
                
                <div class="glass p-4">
                    <h4 class="text-xs text-gray-500 uppercase tracking-wider mb-3">Date Comparison</h4>
                    <div class="grid grid-cols-2 gap-4">
                        <div>
                            <span class="text-xs text-gray-500">DSL1</span>
                            <p class="font-mono">${{record.DATE_DSL1 || 'N/A'}}</p>
                        </div>
                        <div>
                            <span class="text-xs text-gray-500">DSL2</span>
                            <p class="font-mono">${{record.DATE_DSL2 || 'N/A'}}</p>
                        </div>
                    </div>
                    <div class="mt-3 p-2 rounded" style="background: ${{record.DATE_MATCH ? 'rgba(0,255,136,0.1)' : 'rgba(255,71,87,0.1)'}}">
                        <span style="color: ${{record.DATE_MATCH ? 'var(--neon-success)' : 'var(--neon-error)'}}">
                            ${{record.DATE_MATCH ? '✓ Dates Match' : '✗ Date Mismatch (' + record.DATE_DIFF_DAYS + ' days difference)'}}
                        </span>
                    </div>
                </div>
                
                <div class="glass p-4">
                    <h4 class="text-xs text-gray-500 uppercase tracking-wider mb-3">Balance Comparison</h4>
                    <div class="grid grid-cols-2 gap-4">
                        <div>
                            <span class="text-xs text-gray-500">DSL1 (PRE_BALANCE)</span>
                            <p class="font-mono text-lg">${{formatNumber(record.BAL_DSL1)}}</p>
                        </div>
                        <div>
                            <span class="text-xs text-gray-500">DSL2 (ยอดหนี้เงินกู้)</span>
                            <p class="font-mono text-lg">${{formatNumber(record.BAL_DSL2)}}</p>
                        </div>
                    </div>
                    <div class="mt-4 p-3 rounded" style="background: rgba(59,130,246,0.1)">
                        <div class="flex justify-between items-center">
                            <span class="text-gray-400">Difference (DSL2 - DSL1)</span>
                            <span class="font-mono text-xl" style="color: ${{Math.abs(record.BAL_DIFF) > 1000 ? 'var(--neon-error)' : 'var(--neon-warning)'}}">
                                ${{record.BAL_DIFF >= 0 ? '+' : ''}}${{formatNumber(record.BAL_DIFF)}}
                            </span>
                        </div>
                        <div class="flex justify-between items-center mt-2">
                            <span class="text-gray-400">Percentage Difference</span>
                            <span class="font-mono">${{record.BAL_DIFF_PCT.toFixed(4)}}%</span>
                        </div>
                    </div>
                </div>
                
                <div class="glass p-4">
                    <h4 class="text-xs text-gray-500 uppercase tracking-wider mb-2">Analysis</h4>
                    <p class="text-sm text-gray-300">
                        ${{getAnalysisText(record)}}
                    </p>
                </div>
            `;
            
            panel.classList.add('open');
            overlay.classList.add('open');
        }}
        
        function closePanel() {{
            document.getElementById('detailPanel').classList.remove('open');
            document.getElementById('panelOverlay').classList.remove('open');
        }}
        
        function getAnalysisText(record) {{
            let issues = [];
            
            if (!record.DATE_MATCH) {{
                issues.push(`Date discrepancy of ${{record.DATE_DIFF_DAYS}} days detected. DSL2 shows a different payment start date than DSL1.`);
            }}
            
            if (!record.BAL_MATCH) {{
                const direction = record.BAL_DIFF > 0 ? 'higher' : 'lower';
                issues.push(`Balance in DSL2 is ${{formatNumber(Math.abs(record.BAL_DIFF))}} ${{direction}} than DSL1 (${{record.BAL_DIFF_PCT.toFixed(4)}}% difference).`);
            }}
            
            if (issues.length === 0) {{
                return 'This record shows perfect alignment between DSL1 and DSL2 sources.';
            }}
            
            return issues.join(' ');
        }}
        
        document.addEventListener('keydown', (e) => {{
            if (e.key === 'Escape') closePanel();
        }});
    </script>
</body>
</html>'''
    
    if progress and task_id:
        progress.update(task_id, completed=80)
    
    # Write artifact
    log_info("Writing HTML file to disk...")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    
    if progress and task_id:
        progress.update(task_id, completed=100)
    
    log_success(f"Nexus Artifact generated: {output_path}", "generate_html")


# ══════════════════════════════════════════════════════════════════════════════
# MANIFEST GENERATION
# ══════════════════════════════════════════════════════════════════════════════

def generate_manifest(
    result: ReconciliationResult,
    dsl1_folder: Path,
    dsl2_folder: Path,
    output_folder: Path,
    progress: Progress = None,
    task_id = None
) -> Dict[str, Any]:
    """Generate JSON manifest with hashes, row counts, and environment info."""
    start_timer("generate_manifest")
    log_info("Generating manifest...")
    
    manifest = {
        "version": "2.1.0",
        "generated_at": datetime.now().isoformat(),
        "script": "recalc_dsl1_dsl2_reconcile.py",
        "inputs": {
            "dsl1_folder": str(dsl1_folder.absolute()),
            "dsl2_folder": str(dsl2_folder.absolute()),
            "dsl1_files": [],
            "dsl2_files": [],
        },
        "outputs": {
            "folder": str(output_folder.absolute()),
            "csv_file": "discrepancies.csv",
            "html_artifact": "report.html",
        },
        "statistics": result.to_dict(),
        "environment": {
            "python_version": sys.version,
            "polars_available": POLARS_AVAILABLE,
            "pandas_available": PANDAS_AVAILABLE,
            "platform": sys.platform,
        }
    }
    
    if progress and task_id:
        progress.update(task_id, completed=30)
    
    # Add file hashes
    log_info("Calculating file hashes for DSL1...")
    for f in discover_files(dsl1_folder):
        manifest["inputs"]["dsl1_files"].append({
            "name": f.name,
            "size_bytes": f.stat().st_size,
            "hash_sha256_short": get_file_hash(f)
        })
    
    if progress and task_id:
        progress.update(task_id, completed=60)
    
    log_info("Calculating file hashes for DSL2...")
    for f in discover_files(dsl2_folder):
        manifest["inputs"]["dsl2_files"].append({
            "name": f.name,
            "size_bytes": f.stat().st_size,
            "hash_sha256_short": get_file_hash(f)
        })
    
    if progress and task_id:
        progress.update(task_id, completed=100)
    
    log_success("Manifest generated", "generate_manifest")
    
    return manifest


# ══════════════════════════════════════════════════════════════════════════════
# MAIN EXECUTION ENGINE
# ══════════════════════════════════════════════════════════════════════════════

def main():
    """Main execution entry point with full CLI interface."""
    
    parser = argparse.ArgumentParser(
        description="RECALC TOOLKIT: DSL1 ↔ DSL2 Reconciliation Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python recalc_reconcile.py --dsl1 ./DSL1 --dsl2 ./DSL2 --output ./results
  python recalc_reconcile.py --dsl1 ./DSL1 --dsl2 ./DSL2 --output ./results --web-report --theme peach-fuzz
        """
    )
    
    parser.add_argument("--dsl1", type=Path, required=True, help="Path to DSL1 data folder")
    parser.add_argument("--dsl2", type=Path, required=True, help="Path to DSL2 data folder")
    parser.add_argument("--output", type=Path, required=True, help="Output folder for results")
    parser.add_argument("--workers", type=int, default=4, help="Number of parallel workers")
    parser.add_argument("--theme", type=str, default="peach-fuzz", choices=["peach-fuzz", "viva-magenta"], help="Visual theme")
    parser.add_argument("--web-report", action="store_true", help="Generate Nexus HTML artifact")
    parser.add_argument("--dry-run", action="store_true", help="Validation only, no write")
    parser.add_argument("--debug", action="store_true", help="Show full stack traces")
    parser.add_argument("--balance-tolerance", type=float, default=0.01, help="Balance match tolerance")
    parser.add_argument("--max-errors", type=int, default=100000, help="Maximum error records to capture")
    
    args = parser.parse_args()
    
    # Update theme
    global theme
    theme = NexusTheme(args.theme)
    
    try:
        # Render header
        render_header_panel("RECALC: DSL1 ↔ DSL2 RECONCILIATION", "2.1.0")
        
        # Validate inputs
        if not args.dsl1.exists():
            log_error(f"DSL1 folder not found: {args.dsl1}")
            sys.exit(1)
        
        if not args.dsl2.exists():
            log_error(f"DSL2 folder not found: {args.dsl2}")
            sys.exit(1)
        
        # Create output folder
        args.output.mkdir(parents=True, exist_ok=True)
        tmp_folder = args.output / "_tmp"
        tmp_folder.mkdir(exist_ok=True)
        
        log_info(f"DSL1

Source: {args.dsl1}")
        log_info(f"DSL2 Source: {args.dsl2}")
        log_info(f"Output: {args.output}")
        
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
                task1 = progress.add_task("[cyan]Loading DSL1 (7GB+)...", total=100)
                
                if POLARS_AVAILABLE:
                    log_speed("Using Polars for high-velocity data loading")
                    try:
                        dsl1_lazy = load_dsl1_polars(args.dsl1)
                        progress.update(task1, completed=50)
                        log_info("Materializing DSL1 LazyFrame...")
                        dsl1_data = dsl1_lazy.collect()
                        progress.update(task1, completed=100)
                        log_success(f"DSL1 loaded: {len(dsl1_data):,} rows")
                    except Exception as e:
                        log_warning(f"Polars failed: {e}, falling back to pandas")
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
                task2 = progress.add_task("[cyan]Loading DSL2 (1-1.5GB)...", total=100)
                
                if POLARS_AVAILABLE:
                    try:
                        dsl2_lazy = load_dsl2_polars(args.dsl2)
                        progress.update(task2, completed=50)
                        log_info("Materializing DSL2 LazyFrame...")
                        dsl2_data = dsl2_lazy.collect()
                        progress.update(task2, completed=100)
                        log_success(f"DSL2 loaded: {len(dsl2_data):,} rows")
                    except Exception as e:
                        log_warning(f"Polars failed for DSL2: {e}, falling back to pandas")
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
                
                # Reconcile
                task3 = progress.add_task("[cyan]Reconciling datasets...", total=100)
                result = reconcile_datasets(
                    dsl1_data, 
                    dsl2_data,
                    balance_tolerance=args.balance_tolerance,
                    max_error_records=args.max_errors,
                    progress=progress,
                    task_id=task3
                )
                progress.update(task3, completed=100)
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
            
            print("Reconciling...")
            result = reconcile_datasets(dsl1_data, dsl2_data)
        
        # Display results summary
        if console:
            summary_table = Table(title="Reconciliation Summary", box=box.ROUNDED)
            summary_table.add_column("Metric", style="cyan")
            summary_table.add_column("Value", style="white")
            
            summary_table.add_row("DSL1 Total Rows", f"{result.total_dsl1_rows:,}")
            summary_table.add_row("DSL2 Total Rows", f"{result.total_dsl2_rows:,}")
            summary_table.add_row("Matched Rows", f"{result.matched_rows:,}")
            summary_table.add_row("Match Rate", f"{result.match_rate:.2f}%")
            summary_table.add_row("Perfect Matches", f"{result.perfect_matches:,}")
            summary_table.add_row("Date Mismatches Only", f"{result.date_mismatches:,}")
            summary_table.add_row("Balance Mismatches Only", f"{result.balance_mismatches:,}")
            summary_table.add_row("Both Mismatched", f"{result.both_mismatches:,}")
            summary_table.add_row("Accuracy Rate", f"{result.accuracy_rate:.2f}%")
            summary_table.add_row("Duration", f"{result.duration_seconds:.2f}s")
            
            console.print(summary_table)
        
        if args.dry_run:
            log_info("Dry run complete. No files written.")
            return
        
        # Write outputs with progress bars
        log_info("Writing output files...")
        
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
                
                # CSV output with progress
                if result.error_records:
                    csv_task = progress.add_task("[yellow]Writing discrepancies.csv...", total=100)
                    csv_path = tmp_folder / "discrepancies.csv"
                    
                    start_timer("write_csv")
                    log_info(f"Writing {len(result.error_records):,} error records to CSV...")
                    
                    # Write in chunks for progress tracking
                    error_df = pd.DataFrame(result.error_records)
                    total_rows = len(error_df)
                    
                    # Write header first
                    error_df.head(0).to_csv(csv_path, index=False, encoding="utf-8-sig")
                    progress.update(csv_task, completed=10)
                    
                    # Write in chunks
                    chunk_size = max(1000, total_rows // 10)
                    for i in range(0, total_rows, chunk_size):
                        chunk = error_df.iloc[i:i+chunk_size]
                        chunk.to_csv(csv_path, mode='a', index=False, header=False, encoding="utf-8-sig")
                        pct = min(100, 10 + int((i + chunk_size) / total_rows * 90))
                        progress.update(csv_task, completed=pct)
                    
                    progress.update(csv_task, completed=100)
                    log_success(f"CSV written: {csv_path}", "write_csv")
                
                # HTML Artifact with progress
                if args.web_report:
                    html_task = progress.add_task("[magenta]Generating report.html...", total=100)
                    html_path = tmp_folder / "report.html"
                    generate_nexus_artifact(result, html_path, args.theme, progress, html_task)
                
                # Manifest with progress
                manifest_task = progress.add_task("[green]Generating manifest.json...", total=100)
                manifest = generate_manifest(result, args.dsl1, args.dsl2, args.output, progress, manifest_task)
                manifest_path = tmp_folder / "manifest.json"
                
                start_timer("write_manifest")
                with open(manifest_path, "w", encoding="utf-8") as f:
                    json.dump(manifest, f, indent=2, ensure_ascii=False)
                log_success(f"Manifest written: {manifest_path}", "write_manifest")
        else:
            # Non-rich fallback
            if result.error_records:
                csv_path = tmp_folder / "discrepancies.csv"
                error_df = pd.DataFrame(result.error_records)
                error_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
                print(f"CSV written: {csv_path}")
            
            if args.web_report:
                html_path = tmp_folder / "report.html"
                generate_nexus_artifact(result, html_path, args.theme)
            
            manifest = generate_manifest(result, args.dsl1, args.dsl2, args.output)
            manifest_path = tmp_folder / "manifest.json"
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)
            print(f"Manifest written: {manifest_path}")
        
        # Atomic move from tmp to final
        start_timer("atomic_move")
        log_info("Moving files to final destination...")
        
        import shutil
        for f in tmp_folder.iterdir():
            final_path = args.output / f.name
            if final_path.exists():
                final_path.unlink()  # Remove existing file
            shutil.move(str(f), str(final_path))
        
        tmp_folder.rmdir()
        
        log_success("Files moved to final destination", "atomic_move")
        log_success("✨ Reconciliation complete!")
        
        # Final stats panel
        if console:
            console.print(Panel(
                f"[bold green]EXECUTION COMPLETE[/bold green]\n\n"
                f"📊 Processed {result.total_dsl1_rows + result.total_dsl2_rows:,} total rows\n"
                f"⚡ Speed: {(result.total_dsl1_rows + result.total_dsl2_rows) / max(result.duration_seconds, 0.001):,.0f} rows/sec\n"
                f"📁 Output: {args.output}",
                border_style="green",
                title="NEXUS GRILL"
            ))
        
    except Exception as e:
        log_error(f"Execution failed: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

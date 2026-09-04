"""
SIS API client: session + fresh CSRF, cascading location lookups,
markaz-type classification, and sanctioned-posts wide-table aggregation.
"""

from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, wait, FIRST_COMPLETED
import queue
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import requests
from bs4 import BeautifulSoup

# Bump when exports change so Streamlit/hot-reload picks up a fresh module.
MODULE_VERSION = 12

BASE_URL = "https://sis.pesrp.edu.pk"
DEFAULT_WORKERS = 10
MAX_ATTEMPTS = 4
RETRY_BACKOFF_SEC = (0.6, 1.2, 2.0, 3.0)
TEHSIL_CACHE_TTL_SEC = 7 * 24 * 60 * 60  # 7 days

# Scraped from sis.pesrp.edu.pk — stable IDs; do not network-fetch on every load.
STATIC_DISTRICTS: list[tuple[str, str]] = [
    ("1", "ATTOCK"),
    ("2", "BAHAWALNAGAR"),
    ("3", "BAHAWALPUR"),
    ("4", "BHAKKAR"),
    ("5", "CHAKWAL"),
    ("6", "CHINIOT"),
    ("7", "D.G. KHAN"),
    ("8", "FAISALABAD"),
    ("9", "GUJRANWALA"),
    ("10", "GUJRAT"),
    ("11", "HAFIZABAD"),
    ("12", "JHANG"),
    ("13", "JHELUM"),
    ("14", "KASUR"),
    ("15", "KHANEWAL"),
    ("16", "KHUSHAB"),
    ("17", "LAHORE"),
    ("18", "LAYYAH"),
    ("19", "LODHRAN"),
    ("20", "MANDI BAHA UD DIN"),
    ("21", "MIANWALI"),
    ("22", "MULTAN"),
    ("23", "MUZAFFARGARH"),
    ("24", "NANKANA SAHIB"),
    ("25", "NAROWAL"),
    ("26", "OKARA"),
    ("27", "PAKPATTAN"),
    ("28", "RAHIMYAR KHAN"),
    ("29", "RAJANPUR"),
    ("30", "RAWALPINDI"),
    ("31", "SAHIWAL"),
    ("32", "SARGODHA"),
    ("33", "SHEIKHUPURA"),
    ("34", "SIALKOT"),
    ("35", "T.T.SINGH"),
    ("36", "VEHARI"),
    ("37", "KOT ADU"),
    ("38", "MURREE"),
    ("39", "TALAGANG"),
    ("40", "WAZIRABAD"),
]

MARKAZ_TYPES = ("Male", "Female", "Secondary Wing")

ProgressCallback = Callable[[str, int, int], None]

__all__ = [
    "BASE_URL",
    "DEFAULT_WORKERS",
    "MARKAZ_TYPES",
    "MAX_ATTEMPTS",
    "MODULE_VERSION",
    "SISClient",
    "STATIC_DISTRICTS",
    "TEHSIL_CACHE_TTL_SEC",
    "build_wide_posts_table",
    "classify_markaz_type",
    "clear_tehsil_disk_cache",
    "flatten_wide_columns",
    "load_tehsils_disk_cache",
    "parse_school_label",
    "save_tehsils_disk_cache",
]


def _split_into_chunks(
    items: list[Any], n_chunks: int
) -> list[list[Any]]:
    """Split items into n_chunks nearly equal contiguous parts (no empty chunks)."""
    if not items:
        return []
    n = max(1, min(n_chunks, len(items)))
    size, rem = divmod(len(items), n)
    chunks: list[list[Any]] = []
    start = 0
    for i in range(n):
        end = start + size + (1 if i < rem else 0)
        chunks.append(items[start:end])
        start = end
    return chunks


def _empty_posts_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "#",
            "Sanctioned Post",
            "Total",
            "Filled",
            "Vacant",
            "Assigned Teacher",
        ]
    )


def _backoff(attempt: int) -> None:
    """Sleep after a failed attempt (attempt is 1-based for the failure just happened)."""
    idx = min(max(attempt - 1, 0), len(RETRY_BACKOFF_SEC) - 1)
    time.sleep(RETRY_BACKOFF_SEC[idx])


def _make_progress_pump(
    on_progress: ProgressCallback | None,
) -> tuple[Callable[[str, int, int], None], Callable[[], None]]:
    """
    Thread-safe progress: workers only enqueue; pump() must run on the main
    thread (calls on_progress / Streamlit-safe UI updates).
    """
    q: queue.Queue[tuple[str, int, int]] = queue.Queue()

    def report(message: str, current: int, total: int) -> None:
        q.put((message, current, total))

    def pump() -> None:
        if not on_progress:
            # Drain so queue does not grow unbounded
            while True:
                try:
                    q.get_nowait()
                except queue.Empty:
                    break
            return
        latest: tuple[str, int, int] | None = None
        while True:
            try:
                latest = q.get_nowait()
            except queue.Empty:
                break
        if latest is not None:
            on_progress(*latest)

    return report, pump


def _cache_dir() -> Path:
    path = Path(__file__).resolve().parent / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _tehsil_cache_path(district_id: str) -> Path:
    safe = re.sub(r"[^\w.-]", "_", str(district_id))
    return _cache_dir() / f"tehsils_{safe}.json"


def load_tehsils_disk_cache(
    district_id: str,
    ttl_sec: int = TEHSIL_CACHE_TTL_SEC,
) -> list[tuple[str, str]] | None:
    """Return cached tehsils or None on miss/expiry."""
    path = _tehsil_cache_path(district_id)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        fetched_at = float(payload.get("fetched_at") or 0)
        if ttl_sec > 0 and (time.time() - fetched_at) > ttl_sec:
            return None
        rows = payload.get("tehsils") or []
        return [(str(a), str(b)) for a, b in rows]
    except Exception:  # noqa: BLE001
        return None


def save_tehsils_disk_cache(
    district_id: str, tehsils: list[tuple[str, str]]
) -> None:
    path = _tehsil_cache_path(district_id)
    payload = {
        "fetched_at": time.time(),
        "district_id": str(district_id),
        "tehsils": [[a, b] for a, b in tehsils],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def clear_tehsil_disk_cache(district_id: str | None = None) -> None:
    """Clear one district's tehsil cache, or all tehsil_*.json files."""
    if district_id:
        path = _tehsil_cache_path(district_id)
        if path.exists():
            path.unlink()
        return
    for path in _cache_dir().glob("tehsils_*.json"):
        path.unlink(missing_ok=True)


def classify_markaz_type(label: str) -> str | None:
    """Map a markaz option label to Male / Female / Secondary Wing."""
    text = (label or "").upper()
    if "SECONDARY" in text:
        return "Secondary Wing"
    if "FEMALE" in text:
        return "Female"
    if "MALE" in text:
        return "Male"
    return None


def parse_school_label(label: str) -> tuple[str, str]:
    """Parse '32120062 - GES KALO WALA' → (emis, school_name)."""
    raw = (label or "").strip()
    match = re.match(r"^(\d+)\s*[-–]\s*(.+)$", raw)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return "", raw


def _to_num(value: Any) -> int | float:
    if value is None or value == "":
        return 0
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip().replace(",", "")
    try:
        return int(text)
    except ValueError:
        try:
            return float(text)
        except ValueError:
            return 0


def build_wide_posts_table(
    school_records: list[dict[str, Any]],
) -> pd.DataFrame:
    """
    Build Excel-style wide table:
    EMIS Code | School Name | [Post] Vacant | Filled | Total | ...
    with MultiIndex columns for the post-type groups.
    """
    post_types: list[str] = []
    seen: set[str] = set()
    for rec in school_records:
        posts = rec.get("posts")
        if posts is None or getattr(posts, "empty", True):
            continue
        for name in posts["Sanctioned Post"].tolist():
            if name == "Total" or name in seen:
                continue
            seen.add(name)
            post_types.append(str(name))

    id_cols = [("EMIS Code", ""), ("School Name", "")]
    metric_cols = [
        (ptype, metric)
        for ptype in post_types
        for metric in ("Vacant", "Filled", "Total")
    ]
    columns = pd.MultiIndex.from_tuples(id_cols + metric_cols)

    rows: list[list[Any]] = []
    for rec in school_records:
        row: list[Any] = [rec.get("emis", ""), rec.get("school_name", "")]
        posts = rec.get("posts")
        lookup: dict[str, dict[str, Any]] = {}
        if posts is not None and not getattr(posts, "empty", True):
            for _, prow in posts.iterrows():
                pname = prow.get("Sanctioned Post", "")
                if pname == "Total":
                    continue
                lookup[str(pname)] = {
                    "Vacant": _to_num(prow.get("Vacant", 0)),
                    "Filled": _to_num(prow.get("Filled", 0)),
                    "Total": _to_num(prow.get("Total", 0)),
                }
        for ptype in post_types:
            metrics = lookup.get(ptype, {})
            row.extend(
                [
                    metrics.get("Vacant", 0),
                    metrics.get("Filled", 0),
                    metrics.get("Total", 0),
                ]
            )
        rows.append(row)

    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows, columns=columns)


def flatten_wide_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Flatten MultiIndex columns for CSV download."""
    if not isinstance(df.columns, pd.MultiIndex):
        return df.copy()
    flat = []
    for top, sub in df.columns.to_list():
        if not sub:
            flat.append(str(top))
        else:
            flat.append(f"{top} - {sub}")
    out = df.copy()
    out.columns = flat
    return out



def _normalize_school(school: Any) -> dict[str, str]:
    if not isinstance(school, dict):
        return {
            "emis": "",
            "school_name": str(school),
            "label": str(school),
            "school_id": "",
            "markaz_id": "",
            "markaz_name": "",
            "district_id": "",
            "tehsil_id": "",
        }
    label = str(school.get("label") or school.get("school_name") or "")
    name = str(school.get("school_name") or label)
    return {
        "emis": str(school.get("emis") or ""),
        "school_name": name,
        "label": label or name,
        "school_id": str(school.get("school_id") or ""),
        "markaz_id": str(school.get("markaz_id") or ""),
        "markaz_name": str(school.get("markaz_name") or ""),
        "district_id": str(school.get("district_id") or ""),
        "tehsil_id": str(school.get("tehsil_id") or ""),
    }


def _failed_school_rec(school: Any, err: str) -> dict[str, Any]:
    s = _normalize_school(school)
    return {
        "emis": s["emis"],
        "school_name": f"{s['school_name']} [FETCH FAILED]",
        "posts": _empty_posts_frame(),
        "label": s["label"],
        "error": err,
        "school": s,
    }


def _worker_fetch_school_chunk(
    chunk: list[tuple[int, Any]],
    district_id: str,
    tehsil_id: str,
    max_attempts: int,
) -> list[tuple[int, dict[str, Any]]]:
    """
    Runs INSIDE ThreadPoolExecutor.
    Fetch-only worker: returns school results; never touches UI callbacks.
    """
    out: list[tuple[int, dict[str, Any]]] = []
    try:
        client = SISClient()
        client.refresh_csrf()
    except Exception as exc:  # noqa: BLE001
        for orig_idx, school in chunk:
            out.append((orig_idx, _failed_school_rec(school, f"worker init failed: {exc}")))
        return out

    for orig_idx, school in chunk:
        s = _normalize_school(school)
        last_err: str | None = None
        rec: dict[str, Any] | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                if attempt > 1:
                    client.refresh_csrf()
                posts = client.get_sanctioned_posts(
                    district_id=district_id,
                    tehsil_id=tehsil_id,
                    markaz_id=s["markaz_id"],
                    school_id=s["school_id"],
                    emis_code=s["emis"],
                    refresh=False,
                )
                rec = {
                    "emis": s["emis"],
                    "school_name": s["school_name"],
                    "posts": posts,
                    "label": s["label"],
                    "error": None,
                    "school": s,
                }
                break
            except Exception as exc:  # noqa: BLE001
                last_err = str(exc)
                if attempt < max_attempts:
                    _backoff(attempt)
        if rec is None:
            rec = _failed_school_rec(s, last_err or "unknown error")
        out.append((orig_idx, rec))
    return out


class SISClient:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{BASE_URL}/",
            }
        )
        self._csrf: str | None = None

    def refresh_csrf(self) -> str:
        """Hit the homepage so a fresh csrf_cookie_name is issued."""
        resp = self.session.get(f"{BASE_URL}/", timeout=45)
        resp.raise_for_status()
        csrf = self.session.cookies.get("csrf_cookie_name")
        if not csrf:
            match = re.search(
                r'name=["\']csrf_test_name["\']\s+value=["\']([^"\']+)',
                resp.text,
                re.I,
            )
            csrf = match.group(1) if match else None
        if not csrf:
            raise RuntimeError("Could not obtain CSRF token from SIS.")
        self._csrf = csrf
        return csrf

    @property
    def csrf(self) -> str:
        if not self._csrf:
            return self.refresh_csrf()
        return self._csrf

    def _update_csrf_from_payload(self, payload: dict[str, Any] | None) -> None:
        if not payload:
            return
        token = payload.get("csrf_test_name")
        if token:
            self._csrf = token
        cookie = self.session.cookies.get("csrf_cookie_name")
        if cookie:
            self._csrf = cookie

    @staticmethod
    def parse_options(html: str) -> list[tuple[str, str]]:
        soup = BeautifulSoup(html or "", "html.parser")
        options: list[tuple[str, str]] = []
        for opt in soup.find_all("option"):
            value = (opt.get("value") or "").strip()
            label = opt.get_text(" ", strip=True)
            if value:
                options.append((value, label))
        return options

    def get_districts(self, *, from_network: bool = False) -> list[tuple[str, str]]:
        """Return static Punjab districts by default (no network)."""
        if not from_network:
            return list(STATIC_DISTRICTS)
        self.refresh_csrf()
        resp = self.session.get(f"{BASE_URL}/", timeout=45)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        select = soup.find("select", {"name": "districts"}) or soup.find(
            "select", id=re.compile(r"district", re.I)
        )
        if not select:
            for candidate in soup.find_all("select"):
                opts = candidate.find_all("option")
                labels = [o.get_text(strip=True).upper() for o in opts[:5]]
                if any("DISTRICT" in lab for lab in labels) or any(
                    lab == "ATTOCK" for lab in labels
                ):
                    select = candidate
                    break
        if not select:
            return list(STATIC_DISTRICTS)
        parsed = self.parse_options(str(select))
        return parsed or list(STATIC_DISTRICTS)

    def get_tehsils(self, district_id: str) -> list[tuple[str, str]]:
        self.refresh_csrf()
        resp = self.session.get(
            f"{BASE_URL}/user/get_tehsils",
            params={
                "district": district_id,
                "selectedTehsil": "false",
                "all": "All",
                "csrf_test_name": self.csrf,
            },
            timeout=45,
        )
        resp.raise_for_status()
        data = resp.json()
        self._update_csrf_from_payload(data)
        return self.parse_options(data.get("html", ""))

    def get_markazes(self, tehsil_id: str) -> list[tuple[str, str]]:
        self.refresh_csrf()
        resp = self.session.get(
            f"{BASE_URL}/user/get_markazes",
            params={
                "tehsil": tehsil_id,
                "selectedMarkaz": "false",
                "all": "All",
                "csrf_test_name": self.csrf,
            },
            timeout=45,
        )
        resp.raise_for_status()
        data = resp.json()
        self._update_csrf_from_payload(data)
        return self.parse_options(data.get("html", ""))

    def get_schools(self, markaz_id: str, *, refresh: bool = True) -> list[tuple[str, str]]:
        if refresh or not self._csrf:
            self.refresh_csrf()
        resp = self.session.get(
            f"{BASE_URL}/user/get_schools",
            params={
                "markaz": markaz_id,
                "selectedSchool": "false",
                "all": "All",
                "csrf_test_name": self.csrf,
            },
            timeout=45,
        )
        resp.raise_for_status()
        data = resp.json()
        self._update_csrf_from_payload(data)
        return self.parse_options(data.get("html", ""))

    def get_sanctioned_posts(
        self,
        district_id: str = "",
        tehsil_id: str = "",
        markaz_id: str = "",
        school_id: str = "",
        emis_code: str = "",
        *,
        refresh: bool = True,
    ) -> pd.DataFrame:
        if refresh or not self._csrf:
            self.refresh_csrf()
        resp = self.session.get(
            f"{BASE_URL}/dashboard/rationalization_posts_tab",
            params={
                "district_id": district_id or "",
                "tehsil_id": tehsil_id or "",
                "markaz_id": markaz_id or "",
                "school_id": school_id or "",
                "s_id_emis_code": emis_code or "",
            },
            timeout=60,
        )
        resp.raise_for_status()
        return self._parse_sanctioned_posts_table(resp.text)

    def collect_schools_for_markaz_type(
        self,
        markazes: list[tuple[str, str]] | None = None,
        markaz_type: str = "",
        emis_filter: str = "",
        school_cache: dict[str, list[tuple[str, str]]] | None = None,
        district_id: str = "",
        tehsil_id: str = "",
        max_workers: int = DEFAULT_WORKERS,
        max_attempts: int = MAX_ATTEMPTS,
        on_progress: ProgressCallback | None = None,
    ) -> list[dict[str, str]]:
        """
        Filter markazes by type, fetch schools in parallel (one client per worker).
        Retries failed markaz school loads; never drops a markaz without exhausting retries.
        on_progress is invoked ONLY from the main thread (never from workers).
        """
        def ui(message: str, current: int, total: int) -> None:
            if on_progress:
                on_progress(message, current, total)

        ui("Refreshing CSRF…", 0, 1)
        self.refresh_csrf()

        if markazes is None:
            if not tehsil_id:
                raise ValueError("tehsil_id is required when markazes is not provided")
            ui("Loading markazes for tehsil…", 0, 1)
            markazes = self.get_markazes(tehsil_id)

        selected = [
            (mid, lab)
            for mid, lab in markazes
            if classify_markaz_type(lab) == markaz_type
        ]
        ui(
            f"Filtering {markaz_type} ({len(selected)} matching markazes)…",
            0,
            max(len(selected), 1),
        )

        cache = school_cache if school_cache is not None else {}
        emis_filter = (emis_filter or "").strip()
        to_fetch = [(mid, mlab) for mid, mlab in selected if mid not in cache]
        cached_ok = [(mid, mlab) for mid, mlab in selected if mid in cache]

        done = 0
        total_m = max(len(selected), 1)
        for mid, mlab in cached_ok:
            done += 1
            ui(
                f"Markaz {done}/{len(selected)}: {mlab} — using cached schools…",
                done,
                total_m,
            )

        failed_pairs: list[tuple[str, str]] = []

        def _fetch_markaz(
            pair: tuple[str, str],
        ) -> tuple[str, str, list[tuple[str, str]], str | None]:
            # Worker: network only — never call on_progress / Streamlit.
            mid, mlab = pair
            last_err: str | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    if attempt > 1:
                        pass  # silent backoff retry inside worker
                    worker = SISClient()
                    worker.refresh_csrf()
                    schools_list = worker.get_schools(mid, refresh=False)
                    return mid, mlab, schools_list, None
                except Exception as exc:  # noqa: BLE001
                    last_err = str(exc)
                    if attempt < max_attempts:
                        _backoff(attempt)
            return mid, mlab, [], last_err or "unknown error"

        if to_fetch:
            workers = max(1, min(max_workers, len(to_fetch)))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {
                    pool.submit(_fetch_markaz, pair): pair for pair in to_fetch
                }
                pending = set(futures)
                while pending:
                    finished, pending = wait(
                        pending, timeout=0.25, return_when=FIRST_COMPLETED
                    )
                    for fut in finished:
                        mid, mlab, schools_list, err = fut.result()
                        done += 1
                        if err:
                            failed_pairs.append((mid, mlab))
                            ui(
                                f"Markaz {done}/{len(selected)}: {mlab} — FAILED "
                                f"after {max_attempts} attempts…",
                                done,
                                total_m,
                            )
                        else:
                            cache[mid] = schools_list
                            ui(
                                f"Markaz {done}/{len(selected)}: {mlab} — "
                                f"loaded {len(schools_list)} schools…",
                                done,
                                total_m,
                            )

        if failed_pairs:
            ui(
                f"Final retry pass for {len(failed_pairs)} markazes…",
                0,
                len(failed_pairs),
            )
            still_failed: list[tuple[str, str]] = []
            for i, (mid, mlab) in enumerate(failed_pairs, start=1):
                ok = False
                for attempt in range(1, max_attempts + 1):
                    try:
                        ui(
                            f"Final retry {attempt}/{max_attempts} for {mlab} "
                            f"({i}/{len(failed_pairs)})…",
                            i,
                            len(failed_pairs),
                        )
                        worker = SISClient()
                        worker.refresh_csrf()
                        cache[mid] = worker.get_schools(mid, refresh=False)
                        ok = True
                        break
                    except Exception:  # noqa: BLE001
                        if attempt < max_attempts:
                            _backoff(attempt)
                if not ok:
                    still_failed.append((mid, mlab))
                    cache.setdefault(mid, [])
            failed_pairs = still_failed

        schools: list[dict[str, str]] = []
        for mid, mlab in selected:
            for sid, slab in cache.get(mid, []):
                emis, name = parse_school_label(slab)
                if emis_filter and emis_filter not in (emis, slab):
                    continue
                schools.append(
                    {
                        "markaz_id": mid,
                        "markaz_name": mlab,
                        "school_id": sid,
                        "emis": emis,
                        "school_name": name or slab,
                        "label": slab,
                        "district_id": district_id or "",
                        "tehsil_id": tehsil_id or "",
                    }
                )
        msg = f"Collected {len(schools)} schools across {len(selected)} markazes…"
        if failed_pairs:
            msg += f" ({len(failed_pairs)} markazes still failed)"
        ui(msg, len(selected), total_m)
        return schools

    def aggregate_sanctioned_posts(
        self,
        district_id: str,
        tehsil_id: str,
        schools: list[dict[str, str]],
        max_workers: int = DEFAULT_WORKERS,
        max_attempts: int = MAX_ATTEMPTS,
        on_progress: ProgressCallback | None = None,
    ) -> tuple[pd.DataFrame, list[dict[str, str]]]:
        """
        Divide schools into N chunks; each worker owns one chunk (own SISClient).
        Schools inside a chunk run sequentially with retries; chunks run in parallel.
        Returns (wide_df, remaining_failures) — never silently skips a school.
        """
        total = len(schools)
        if total == 0:
            return build_wide_posts_table([]), []

        workers = max(1, min(max_workers, total))
        indexed = list(enumerate(schools))
        parts = _split_into_chunks(indexed, workers)
        sizes = [len(p) for p in parts]

        # Main-thread progress only
        if on_progress:
            on_progress(
                f"Splitting {total} schools across {len(parts)} workers "
                f"(chunks {sizes})…",
                0,
                total,
            )

        records: list[dict[str, Any] | None] = [None] * total
        done_count = 0

        # Submit module-level worker (no closure over on_progress)
        with ThreadPoolExecutor(max_workers=len(parts)) as pool:
            futures = {
                pool.submit(
                    _worker_fetch_school_chunk,
                    chunk,
                    district_id,
                    tehsil_id,
                    max_attempts,
                ): (wid, chunk)
                for wid, chunk in enumerate(parts, start=1)
            }
            # as_completed runs on MAIN THREAD — only place that calls on_progress
            for fut in as_completed(futures):
                wid, chunk = futures[fut]
                try:
                    chunk_rows = fut.result()
                except Exception as exc:  # noqa: BLE001
                    chunk_rows = [
                        (orig_idx, _failed_school_rec(school, f"worker crashed: {exc}"))
                        for orig_idx, school in chunk
                    ]
                for orig_idx, rec in chunk_rows:
                    records[orig_idx] = rec
                    done_count += 1
                    label = str((rec or {}).get("label") or "")
                    failed = bool((rec or {}).get("error"))
                    if on_progress:
                        on_progress(
                            f"Worker {wid}/{len(parts)} · "
                            f"{done_count}/{total}: "
                            f"{'FAILED ' if failed else ''}{label}",
                            done_count,
                            total,
                        )

        failed_idxs = [i for i, r in enumerate(records) if r and r.get("error")]
        if failed_idxs:
            if on_progress:
                on_progress(
                    f"Final retry pass for {len(failed_idxs)} failed schools…",
                    0,
                    len(failed_idxs),
                )
            for pass_i, idx in enumerate(failed_idxs, start=1):
                school = _normalize_school(
                    (records[idx] or {}).get("school") or schools[idx]
                )
                label = school["label"]
                recovered = False
                last_err = (records[idx] or {}).get("error")
                for attempt in range(1, max_attempts + 1):
                    try:
                        if on_progress:
                            on_progress(
                                f"Final retry {attempt}/{max_attempts} for {label} "
                                f"({pass_i}/{len(failed_idxs)})…",
                                pass_i,
                                len(failed_idxs),
                            )
                        worker = SISClient()
                        worker.refresh_csrf()
                        posts = worker.get_sanctioned_posts(
                            district_id=district_id,
                            tehsil_id=tehsil_id,
                            markaz_id=school["markaz_id"],
                            school_id=school["school_id"],
                            emis_code=school["emis"],
                            refresh=False,
                        )
                        records[idx] = {
                            "emis": school["emis"],
                            "school_name": school["school_name"],
                            "posts": posts,
                            "label": label,
                            "error": None,
                            "school": school,
                        }
                        recovered = True
                        break
                    except Exception as exc:  # noqa: BLE001
                        last_err = str(exc)
                        if attempt < max_attempts:
                            _backoff(attempt)
                if not recovered:
                    records[idx] = _failed_school_rec(
                        school, str(last_err or "unknown error")
                    )

        failures = [
            {
                "emis": str(r.get("emis", "")),
                "label": str(r.get("label", "")),
                "error": str(r.get("error")),
            }
            for r in records
            if r and r.get("error")
        ]

        if on_progress:
            on_progress("Building wide Excel-style table…", total, total)

        clean_records: list[dict[str, Any]] = []
        for i, r in enumerate(records):
            if r is None:
                school = _normalize_school(schools[i])
                clean_records.append(
                    {
                        "emis": school["emis"],
                        "school_name": f"{school['school_name']} [FETCH FAILED]",
                        "posts": _empty_posts_frame(),
                    }
                )
                failures.append(
                    {
                        "emis": school["emis"],
                        "label": school["label"],
                        "error": "missing result after workers",
                    }
                )
            else:
                clean_records.append(
                    {
                        "emis": r["emis"],
                        "school_name": r["school_name"],
                        "posts": r["posts"],
                    }
                )
        return build_wide_posts_table(clean_records), failures

    @staticmethod
    def _parse_sanctioned_posts_table(html: str) -> pd.DataFrame:
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table", class_=re.compile(r"sanctioned_post"))
        columns = [
            "#",
            "Sanctioned Post",
            "Total",
            "Filled",
            "Vacant",
            "Assigned Teacher",
        ]
        if not table:
            return pd.DataFrame(columns=columns)

        rows: list[dict[str, Any]] = []
        tbody = table.find("tbody")
        if not tbody:
            return pd.DataFrame(columns=columns)

        for tr in tbody.find_all("tr"):
            classes = " ".join(tr.get("class") or [])
            cells = tr.find_all(["td", "th"])
            texts = [c.get_text(" ", strip=True) for c in cells]

            if "total" in classes.lower() or (texts and texts[0].lower() == "total"):
                if len(texts) >= 4:
                    rows.append(
                        {
                            "#": "",
                            "Sanctioned Post": "Total",
                            "Total": texts[-3],
                            "Filled": texts[-2],
                            "Vacant": texts[-1],
                            "Assigned Teacher": "",
                        }
                    )
                continue

            if len(texts) < 5:
                continue

            rows.append(
                {
                    "#": texts[0],
                    "Sanctioned Post": texts[1],
                    "Total": texts[2],
                    "Filled": texts[3],
                    "Vacant": texts[4],
                    "Assigned Teacher": texts[5] if len(texts) > 5 else "",
                }
            )

        return pd.DataFrame(rows, columns=columns)

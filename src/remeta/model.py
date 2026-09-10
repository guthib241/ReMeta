"""Data model for meta-analyses.

A meta-analysis is a set of studies, each contributing an effect estimate and
its variance. ReMeta's job is to recompute the pooled result when one or more
of those studies turns out to be unreliable.

Dependency-free by design: this must run in CI, in a hospital, and on a
librarian's laptop without a scientific Python stack.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Literal

# Measures on a ratio scale are pooled in log space and reported exponentiated.
# Their null value is 1. Difference measures are pooled directly; null is 0.
RATIO_MEASURES = {"RR", "OR", "HR", "IRR"}
DIFFERENCE_MEASURES = {"MD", "SMD", "RD"}
MEASURES = RATIO_MEASURES | DIFFERENCE_MEASURES

# Measures that can be derived from a 2x2 table of events and totals. A hazard
# ratio needs time-to-event data and an incidence rate ratio needs person-time,
# so neither can be reconstructed from counts alone; supply (yi, vi) for those.
TABLE_MEASURES = {"RR", "OR", "RD"}

MODELS = ("random", "fixed")

Measure = Literal["RR", "OR", "HR", "IRR", "MD", "SMD", "RD"]

TABLE_FIELDS = ("events_treat", "total_treat", "events_control", "total_control")


class DataError(ValueError):
    """Raised when input data cannot yield a usable effect estimate.

    The message is written for a researcher rather than a Python developer:
    it names the record at fault and, where possible, how to fix it.
    """


def _number(value: Any, what: str, *, integral: bool = False) -> float:
    """Coerce a JSON value to a number, or raise a readable DataError."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DataError(f"{what}: expected a number, got {value!r}")
    if not math.isfinite(value):
        raise DataError(f"{what}: expected a finite number, got {value!r}")
    if integral and float(value) != int(value):
        raise DataError(f"{what}: expected a whole number, got {value!r}")
    return float(value)


@dataclass
class Study:
    """One study contributing to a pooled estimate.

    Supply either a 2x2 table (events/total per arm) or a precomputed effect
    with its variance. Published forest plots give one or the other; both
    paths must work or half the corpus is unusable.
    """

    id: str
    # Precomputed path: yi is on the analysis scale (log scale for ratios).
    yi: float | None = None
    vi: float | None = None
    # 2x2 path
    events_treat: int | None = None
    total_treat: int | None = None
    events_control: int | None = None
    total_control: int | None = None
    # Provenance
    doi: str | None = None
    year: int | None = None
    retracted: bool = False
    retraction_reason: str | None = None
    notes: str = ""

    @property
    def has_table(self) -> bool:
        return all(getattr(self, name) is not None for name in TABLE_FIELDS)

    @property
    def has_effect(self) -> bool:
        return self.yi is not None and self.vi is not None

    def __post_init__(self) -> None:
        if not self.id or not isinstance(self.id, str):
            raise DataError("every study needs a non-empty string 'id'")

        where = f"study {self.id!r}"
        if self.yi is not None:
            self.yi = _number(self.yi, f"{where}: 'yi'")
        if self.vi is not None:
            self.vi = _number(self.vi, f"{where}: 'vi'")
        for name in TABLE_FIELDS:
            value = getattr(self, name)
            if value is not None:
                setattr(self, name, int(_number(value, f"{where}: {name!r}", integral=True)))

        if not self.has_table and not self.has_effect:
            raise DataError(
                f"{where}: needs either a 2x2 table "
                f"({', '.join(TABLE_FIELDS)}) or a precomputed effect "
                f"('yi' with 'vi'). " + self._missing_hint()
            )
        if self.has_effect and self.vi is not None and self.vi <= 0:
            raise DataError(
                f"{where}: 'vi' is the variance of the effect and must be "
                f"positive, got {self.vi}"
            )
        if self.has_table:
            for label, total, events in (
                ("treatment", self.total_treat, self.events_treat),
                ("control", self.total_control, self.events_control),
            ):
                assert total is not None and events is not None
                if total <= 0:
                    raise DataError(f"{where}: {label} total must be positive, got {total}")
                if events < 0 or events > total:
                    raise DataError(
                        f"{where}: {label} events ({events}) must be between "
                        f"0 and the {label} total ({total})"
                    )

    def _missing_hint(self) -> str:
        given = [n for n in TABLE_FIELDS if getattr(self, n) is not None]
        if given:
            missing = [n for n in TABLE_FIELDS if getattr(self, n) is None]
            return f"The 2x2 table is incomplete; add: {', '.join(missing)}."
        if self.yi is not None:
            return "'yi' was given without 'vi'."
        if self.vi is not None:
            return "'vi' was given without 'yi'."
        return "No effect data was given at all."

    @property
    def se(self) -> float | None:
        """Standard error of the precomputed effect, if there is one."""
        return math.sqrt(self.vi) if self.vi is not None else None


@dataclass
class MetaAnalysis:
    """A pooled analysis, as reported in a published systematic review."""

    id: str
    measure: Measure
    studies: list[Study]
    model: Literal["random", "fixed"] = "random"
    title: str = ""
    source_doi: str = ""
    outcome: str = ""
    is_primary_outcome: bool = True
    # What the paper itself reported, for reproduction checks.
    reported_estimate: float | None = None
    reported_ci_low: float | None = None
    reported_ci_high: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id or not isinstance(self.id, str):
            raise DataError("every meta-analysis needs a non-empty string 'id'")
        where = f"meta-analysis {self.id!r}"
        if self.measure not in MEASURES:
            raise DataError(
                f"{where}: unknown effect measure {self.measure!r}. "
                f"Supported measures are {', '.join(sorted(MEASURES))}."
            )
        if self.model not in MODELS:
            raise DataError(
                f"{where}: unknown model {self.model!r}. "
                f"Use {' or '.join(repr(m) for m in MODELS)}."
            )
        if len(self.studies) < 2:
            raise DataError(
                f"{where}: pooling needs at least 2 studies, got {len(self.studies)}"
            )
        seen: set[str] = set()
        for study in self.studies:
            if study.id in seen:
                raise DataError(
                    f"{where}: duplicate study id {study.id!r}; study ids must be unique"
                )
            seen.add(study.id)
        if self.reported_estimate is not None:
            self.reported_estimate = _number(
                self.reported_estimate, f"{where}: 'reported_estimate'"
            )

    @property
    def is_ratio(self) -> bool:
        return self.measure in RATIO_MEASURES

    @property
    def null_value(self) -> float:
        """Value indicating no effect, on the reporting scale."""
        return 1.0 if self.is_ratio else 0.0

    @property
    def retracted_studies(self) -> list[Study]:
        return [s for s in self.studies if s.retracted]

    @property
    def surviving_studies(self) -> list[Study]:
        return [s for s in self.studies if not s.retracted]


_STUDY_FIELDS = {f.name for f in fields(Study)}
_META_FIELDS = {f.name for f in fields(MetaAnalysis)}


def _unknown_keys(record: dict[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(record) - allowed)
    if unknown:
        raise DataError(
            f"{where}: unrecognised field(s) {', '.join(repr(k) for k in unknown)}. "
            f"Allowed fields are {', '.join(sorted(allowed))}."
        )


def from_dict(record: dict[str, Any]) -> MetaAnalysis:
    """Build a MetaAnalysis from a plain dictionary (e.g. parsed JSON).

    The input dictionary is not modified.
    """
    if not isinstance(record, dict):
        raise DataError(
            f"expected a JSON object describing a meta-analysis, got {type(record).__name__}"
        )
    fields_given = dict(record)
    raw_studies = fields_given.pop("studies", None)
    if raw_studies is None:
        raise DataError(
            f"meta-analysis {fields_given.get('id', '<no id>')!r}: missing 'studies'"
        )
    if not isinstance(raw_studies, list):
        raise DataError("'studies' must be a list of study objects")

    where = f"meta-analysis {fields_given.get('id', '<no id>')!r}"
    _unknown_keys(fields_given, _META_FIELDS - {"studies"}, where)
    for required in ("id", "measure"):
        if required not in fields_given:
            raise DataError(f"{where}: missing required field {required!r}")

    studies = []
    for index, raw in enumerate(raw_studies):
        if not isinstance(raw, dict):
            raise DataError(f"{where}: study #{index + 1} must be a JSON object")
        _unknown_keys(raw, _STUDY_FIELDS, f"{where}: study #{index + 1}")
        if "id" not in raw:
            raise DataError(f"{where}: study #{index + 1} is missing required field 'id'")
        studies.append(Study(**raw))

    return MetaAnalysis(studies=studies, **fields_given)


def load(path: str | Path) -> list[MetaAnalysis]:
    """Load meta-analyses from a JSON file (a single object or a list of them).

    Raises DataError with a researcher-readable message if the file is
    missing, is not valid JSON, or does not describe a usable analysis.
    """
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise DataError(f"no such file: {path}") from None
    except IsADirectoryError:
        raise DataError(f"{path} is a directory, not a JSON file") from None
    except UnicodeDecodeError:
        raise DataError(f"{path} is not UTF-8 text; is it really a JSON file?") from None
    except OSError as exc:
        raise DataError(f"could not read {path}: {exc.strerror or exc}") from None

    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DataError(
            f"{path} is not valid JSON: {exc.msg} (line {exc.lineno}, column {exc.colno})"
        ) from None

    records = raw if isinstance(raw, list) else [raw]
    if not records:
        raise DataError(f"{path} contains an empty list; expected at least one meta-analysis")
    return [from_dict(record) for record in records]

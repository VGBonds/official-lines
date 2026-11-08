"""The catalog: which actors we follow (actors.yaml) and where we read them (sources.yaml)."""

from dataclasses import dataclass
from pathlib import Path

import yaml

KINDS = {"head_of_government", "mfa", "finance", "central_bank", "gov_press", "org"}
METHODS = {"rss", "html"}

# Kinds that colour a country on the map. Central banks are collected but kept off the map (v1).
MAP_KINDS = {"head_of_government", "mfa", "finance", "gov_press"}

# Names that must never appear as a source: news agencies, broadcasters, commercial media.
FORBIDDEN_HOSTS = (
    "xinhua", "news.cn", "tass.", "ria.ru", "sputnik", "rt.com", "irna.ir", "aa.com.tr",
    "cgtn", "presstv", "reuters", "apnews", "afp.com", "bloomberg", "ft.com", "bbc.",
)


@dataclass(frozen=True)
class Actor:
    id: str            # "US" for countries, "imf" for organisations
    name: str
    is_country: bool
    iso_numeric: str | None = None
    region: str | None = None


@dataclass(frozen=True)
class Source:
    id: str
    actor: str
    kind: str
    name: str
    homepage: str
    method: str
    url: str
    link_selector: str | None = None
    link_pattern: str | None = None
    enabled: bool = True
    status: str = "ok"
    notes: str = ""


class CatalogError(ValueError):
    pass


@dataclass
class Catalog:
    actors: dict[str, Actor]
    sources: list[Source]

    def enabled_sources(self) -> list[Source]:
        return [s for s in self.sources if s.enabled]

    def actor(self, actor_id: str) -> Actor:
        return self.actors[actor_id]


def load_catalog(sources_dir: Path) -> Catalog:
    raw_actors = yaml.safe_load((sources_dir / "actors.yaml").read_text())
    actors: dict[str, Actor] = {}
    for code, a in raw_actors["countries"].items():
        actors[code] = Actor(code, a["name"], True, a["iso_numeric"], a.get("region"))
    for oid, a in raw_actors["orgs"].items():
        actors[oid] = Actor(oid, a["name"], False, None, a.get("scope"))

    sources_file = sources_dir / "sources.yaml"
    raw_sources = yaml.safe_load(sources_file.read_text()) if sources_file.exists() else None
    sources = [_parse_source(row) for row in (raw_sources or {}).get("sources", [])]
    catalog = Catalog(actors, sources)
    validate(catalog)
    return catalog


def _parse_source(row: dict) -> Source:
    fields = Source.__dataclass_fields__
    return Source(**{k: v for k, v in row.items() if k in fields})


def validate(catalog: Catalog) -> None:
    seen: set[str] = set()
    for s in catalog.sources:
        where = f"source {s.id!r}"
        if s.id in seen:
            raise CatalogError(f"{where}: duplicate id")
        seen.add(s.id)
        if s.actor not in catalog.actors:
            raise CatalogError(f"{where}: unknown actor {s.actor!r} (add it to actors.yaml)")
        if s.kind not in KINDS:
            raise CatalogError(f"{where}: kind must be one of {sorted(KINDS)}")
        if s.method not in METHODS:
            raise CatalogError(f"{where}: method must be one of {sorted(METHODS)}")
        if s.enabled and s.method == "html" and not s.link_selector:
            raise CatalogError(f"{where}: html sources need a link_selector")
        if any(bad in (s.url or "").lower() for bad in FORBIDDEN_HOSTS):
            raise CatalogError(f"{where}: media/agency hosts are out of scope ({s.url})")
        actor = catalog.actors[s.actor]
        if not actor.is_country and s.kind not in {"org", "central_bank"}:
            raise CatalogError(f"{where}: organisations use kind 'org' or 'central_bank'")


def on_map(actor: Actor, kind: str) -> bool:
    """Does a statement by this actor/kind colour a country on the map?"""
    return actor.is_country and kind in MAP_KINDS

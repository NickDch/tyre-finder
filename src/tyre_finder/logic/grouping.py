"""Group identical tyres offered by several shops."""

from __future__ import annotations

from collections import Counter, defaultdict

from tyre_finder.logic.normalize import (
    bucket_key,
    keys_compatible,
    model_compact_key,
    model_token_key,
)
from tyre_finder.models import TyreGroup, TyreOffer


class _UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _most_common(values: list[str]) -> str:
    filtered = [v for v in values if v]
    if not filtered:
        return ""
    counts = Counter(filtered)
    return max(counts, key=lambda v: (counts[v], -len(v)))


def group_offers(offers: list[TyreOffer]) -> list[TyreGroup]:
    """Group offers of the same tyre (brand + model + size + load/speed index or EAN)."""
    uf = _UnionFind(len(offers))
    by_bucket: dict[tuple[str, str, str, str], list[int]] = defaultdict(list)
    for idx, offer in enumerate(offers):
        by_bucket[bucket_key(offer)].append(idx)

    # Offers without load/speed index join a bucket with the same brand+size if possible.
    for key, members in list(by_bucket.items()):
        brand, size, li, si = key
        if li or si:
            continue
        candidates = [k for k in by_bucket if k[:2] == (brand, size) and (k[2] or k[3])]
        for idx in members:
            ck = model_compact_key(offers[idx].model, offers[idx].brand)
            for cand in candidates:
                if any(
                    model_compact_key(offers[j].model, offers[j].brand) == ck
                    for j in by_bucket[cand]
                ):
                    uf.union(by_bucket[cand][0], idx)
                    break

    for members in by_bucket.values():
        first_by_key: dict[str, int] = {}
        for idx in members:
            offer = offers[idx]
            for key in (
                "c:" + model_compact_key(offer.model, offer.brand),
                "t:" + model_token_key(offer.model, offer.brand),
            ):
                if key in ("c:", "t:"):
                    continue
                if key in first_by_key:
                    uf.union(first_by_key[key], idx)
                else:
                    first_by_key[key] = idx
        # Lenient prefix/suffix matching inside the bucket.
        compacts = [
            (idx, model_compact_key(offers[idx].model, offers[idx].brand)) for idx in members
        ]
        for pos, (i, ci) in enumerate(compacts):
            for j, cj in compacts[pos + 1 :]:
                if ci and cj and keys_compatible(ci, cj):
                    uf.union(i, j)

    by_ean: dict[str, int] = {}
    for idx, offer in enumerate(offers):
        if offer.ean:
            if offer.ean in by_ean:
                uf.union(by_ean[offer.ean], idx)
            else:
                by_ean[offer.ean] = idx

    clusters: dict[int, list[TyreOffer]] = defaultdict(list)
    for idx, offer in enumerate(offers):
        clusters[uf.find(idx)].append(offer)

    groups: list[TyreGroup] = []
    for members in clusters.values():
        first = members[0]
        brand_key, size, li, si = bucket_key(first)
        compact = model_compact_key(first.model, first.brand)
        best = min(members, key=lambda o: o.price_eur)
        with_index = next((o for o in members if o.load_index), best)
        seasons = [o.season for o in members if o.season is not None]
        groups.append(
            TyreGroup(
                key=f"{brand_key}|{compact}|{size}|{li}{si}",
                brand=_most_common([o.brand for o in members]),
                model=_most_common([o.model for o in members]),
                size_label=with_index.size_label,
                season=Counter(seasons).most_common(1)[0][0] if seasons else None,
                offers=sorted(members, key=lambda o: o.price_eur),
            )
        )
    return groups

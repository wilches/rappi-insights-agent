"""
Business semantics dictionary for operational metrics.

This file encodes everything the LLM cannot reliably infer from metric names alone:
    - direction: is higher better, lower better, or context-dependent?
    - unit family: is this a ratio, percentage, count, or currency amount?
    - aliases: how might users refer to this metric in Spanish or casual English?
    - description: authoritative business definition from the PDF glossary
    - aggregation: when averaging across zones, should it be mean, weighted mean, or sum?

This is the single source of truth. If the LLM asks "top 5 problematic zones by
markdowns," the answer is zones with the HIGHEST markdowns — because
direction='lower_is_better'. Without this dictionary, the LLM would guess and
fail on roughly half of direction-sensitive queries.
"""

from dataclasses import dataclass, field
from typing import Literal


Direction = Literal["higher_is_better", "lower_is_better"]
Unit = Literal["percentage", "ratio", "count", "currency"]
Aggregation = Literal["mean", "weighted_mean_by_orders", "sum"]


@dataclass(frozen=True)
class MetricDef:
    """
    Authoritative definition of a single operational metric.

    Frozen (immutable) so the dictionary cannot be mutated at runtime —
    one class of subtle bug we don't want.
    """
    canonical_name: str
    direction: Direction
    unit: Unit
    aggregation: Aggregation
    description: str
    aliases: list[str] = field(default_factory=list)
    min_value: float | None = None
    max_value: float | None = None

    @property
    def is_higher_better(self) -> bool:
        return self.direction == "higher_is_better"

    def format_value(self, value: float) -> str:
        """Render a value the way a human would expect to read it."""
        if self.unit == "percentage":
            return f"{value * 100:.1f}%"
        if self.unit == "ratio":
            return f"{value:.3f}"
        if self.unit == "count":
            return f"{int(value):,}"
        if self.unit == "currency":
            return f"${value:,.2f}"
        return f"{value}"


# ---------------------------------------------------------------------------
# The canonical metric dictionary.
# Each key MUST match exactly the METRIC value in the source CSV.
# ---------------------------------------------------------------------------

METRICS: dict[str, MetricDef] = {
    "Lead Penetration": MetricDef(
        canonical_name="Lead Penetration",
        direction="higher_is_better",
        unit="ratio",
        aggregation="mean",
        min_value=0.0,
        max_value=1.0,
        description=(
            "Tiendas habilitadas en Rappi / "
            "(Tiendas identificadas como prospectos + habilitadas + salieron de Rappi). "
            "Mide qué tan profundamente hemos penetrado el mercado de tiendas prospecto."
        ),
        aliases=["lead pen", "penetración de leads", "penetracion", "lead penetration"],
    ),

    "Perfect Orders": MetricDef(
        canonical_name="Perfect Orders",
        direction="higher_is_better",
        unit="ratio",
        aggregation="weighted_mean_by_orders",
        min_value=0.0,
        max_value=1.0,
        description=(
            "Órdenes sin cancelaciones, defectos o demoras / Total de órdenes. "
            "Métrica central de calidad operacional."
        ),
        aliases=["perfect order", "pedidos perfectos", "ordenes perfectas", "po"],
    ),

    "Gross Profit UE": MetricDef(
        canonical_name="Gross Profit UE",
        direction="higher_is_better",
        unit="currency",
        aggregation="weighted_mean_by_orders",
        description=(
            "Margen bruto de ganancia por orden (Unit Economics). "
            "Valores negativos indican zonas operando con pérdidas."
        ),
        aliases=["gross profit", "gp ue", "profit", "margen bruto", "utilidad"],
    ),

    "% PRO Users Who Breakeven": MetricDef(
        canonical_name="% PRO Users Who Breakeven",
        direction="higher_is_better",
        unit="ratio",
        aggregation="mean",
        min_value=0.0,
        max_value=1.0,
        description=(
            "Usuarios Pro cuyo valor generado (compras, comisiones) ha cubierto "
            "el costo de su membresía / Total de usuarios Pro. Indica salud económica "
            "del programa de suscripción."
        ),
        aliases=["pro breakeven", "breakeven pro", "usuarios pro breakeven"],
    ),

    "% Restaurants Sessions With Optimal Assortment": MetricDef(
        canonical_name="% Restaurants Sessions With Optimal Assortment",
        direction="higher_is_better",
        unit="ratio",
        aggregation="mean",
        min_value=0.0,
        max_value=1.0,
        description=(
            "Sesiones con al menos 40 restaurantes disponibles / Total de sesiones. "
            "Mide la riqueza del catálogo que ve el usuario."
        ),
        aliases=["optimal assortment", "assortment", "surtido óptimo", "surtido"],
    ),

    "MLTV Top Verticals Adoption": MetricDef(
        canonical_name="MLTV Top Verticals Adoption",
        direction="higher_is_better",
        unit="ratio",
        aggregation="mean",
        min_value=0.0,
        max_value=1.0,
        description=(
            "Usuarios con órdenes en múltiples verticales (restaurantes, super, "
            "pharmacy, liquors) / Total usuarios. Indica cross-vertical engagement."
        ),
        aliases=["mltv", "verticals adoption", "adopción de verticales", "multi-vertical"],
    ),

    "Non-Pro PTC > OP": MetricDef(
        canonical_name="Non-Pro PTC > OP",
        direction="higher_is_better",
        unit="ratio",
        aggregation="mean",
        min_value=0.0,
        max_value=1.0,
        description=(
            "Conversión de usuarios No Pro de 'Proceed to Checkout' a 'Order Placed'. "
            "Mide fricción final en el funnel de compra para usuarios no-suscritos."
        ),
        aliases=["non pro conversion", "ptc op", "conversion no pro", "checkout conversion"],
    ),

    "Pro Adoption (Last Week Status)": MetricDef(
        canonical_name="Pro Adoption (Last Week Status)",
        direction="higher_is_better",
        unit="ratio",
        aggregation="mean",
        min_value=0.0,
        max_value=1.0,
        description=(
            "Usuarios con suscripción Pro / Total usuarios de Rappi (estado de última semana). "
            "Mide adopción del programa de membresía."
        ),
        aliases=["pro adoption", "adopción pro", "adopcion pro", "pro users"],
    ),

    "Restaurants Markdowns / GMV": MetricDef(
        canonical_name="Restaurants Markdowns / GMV",
        # CRITICAL: higher markdowns = more discounting = worse unit economics
        direction="lower_is_better",
        unit="ratio",
        aggregation="weighted_mean_by_orders",
        min_value=0.0,
        max_value=1.0,
        description=(
            "Descuentos totales en órdenes de restaurantes / Gross Merchandise Value de "
            "restaurantes. Indica cuánto subsidio se requiere para mantener las órdenes. "
            "Valores altos pueden señalar competencia agresiva o problemas de retención."
        ),
        aliases=["markdowns", "descuentos", "markdown gmv", "subsidios"],
    ),

    "Restaurants SS > ATC CVR": MetricDef(
        canonical_name="Restaurants SS > ATC CVR",
        direction="higher_is_better",
        unit="ratio",
        aggregation="mean",
        min_value=0.0,
        max_value=1.0,
        description=(
            "Conversión en restaurantes de 'Select Store' a 'Add to Cart'. "
            "Mide qué tan atractivo es el menú una vez el usuario entra a la tienda."
        ),
        aliases=["ss atc", "select store to cart", "conversion store to cart"],
    ),

    "Restaurants SST > SS CVR": MetricDef(
        canonical_name="Restaurants SST > SS CVR",
        direction="higher_is_better",
        unit="ratio",
        aggregation="mean",
        min_value=0.0,
        max_value=1.0,
        description=(
            "Conversión en restaurantes: usuarios que después de seleccionar "
            "la vertical 'Restaurantes' proceden a seleccionar una tienda específica. "
            "Mide el atractivo del listado de tiendas."
        ),
        aliases=["sst ss restaurants", "restaurants conversion", "listing conversion restaurants"],
    ),

    "Retail SST > SS CVR": MetricDef(
        canonical_name="Retail SST > SS CVR",
        direction="higher_is_better",
        unit="ratio",
        aggregation="mean",
        min_value=0.0,
        max_value=1.0,
        description=(
            "Conversión en supermercados: usuarios que después de seleccionar "
            "la vertical 'Supermercados' proceden a seleccionar una tienda específica."
        ),
        aliases=["sst ss retail", "retail conversion", "supermarket listing conversion"],
    ),

    "Turbo Adoption": MetricDef(
        canonical_name="Turbo Adoption",
        direction="higher_is_better",
        unit="ratio",
        aggregation="mean",
        min_value=0.0,
        max_value=1.0,
        description=(
            "Usuarios que compran en Turbo (servicio de entrega rápida) / "
            "Usuarios con tiendas Turbo disponibles. Mide adopción de la oferta premium."
        ),
        aliases=["turbo", "adopción turbo", "adopcion turbo", "fast delivery adoption"],
    ),

    "Orders": MetricDef(
        canonical_name="Orders",
        direction="higher_is_better",
        unit="count",
        aggregation="sum",
        min_value=0.0,
        description=(
            "Volumen total de órdenes por zona y semana. Métrica de scale/adopción. "
            "También se usa como peso para promediar otras métricas."
        ),
        aliases=["orders", "órdenes", "ordenes", "pedidos", "volumen de órdenes"],
    ),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_metric(name: str) -> MetricDef:
    """Look up a metric by its canonical name. Raises KeyError if unknown."""
    if name not in METRICS:
        raise KeyError(
            f"Unknown metric '{name}'. "
            f"Known metrics: {sorted(METRICS.keys())}"
        )
    return METRICS[name]


def all_metric_names() -> list[str]:
    """Canonical names of every known metric, sorted."""
    return sorted(METRICS.keys())


def resolve_metric_name(user_input: str) -> str | None:
    """
    Resolve a user's loose reference ("lead pen", "perfect order", "markdowns")
    to a canonical metric name. Returns None if no confident match.

    This is a first-pass exact/alias match. Fuzzy matching lives in
    entity_resolver.py.
    """
    normalized = user_input.strip().lower()

    # Exact canonical match (case-insensitive)
    for canonical in METRICS:
        if canonical.lower() == normalized:
            return canonical

    # Alias match
    for canonical, definition in METRICS.items():
        if normalized in [a.lower() for a in definition.aliases]:
            return canonical

    return None


if __name__ == "__main__":
    # Self-test: ensure dictionary is consistent
    print(f"Loaded {len(METRICS)} metric definitions:\n")
    for name, definition in sorted(METRICS.items()):
        arrow = "↑" if definition.is_higher_better else "↓"
        print(f"  {arrow} {name}  [{definition.unit}, agg={definition.aggregation}]")

    # Verify aliases don't collide between metrics
    seen_aliases: dict[str, str] = {}
    for name, definition in METRICS.items():
        for alias in definition.aliases:
            alias_lower = alias.lower()
            if alias_lower in seen_aliases:
                raise AssertionError(
                    f"Alias collision: '{alias}' maps to both "
                    f"'{seen_aliases[alias_lower]}' and '{name}'"
                )
            seen_aliases[alias_lower] = name
    print(f"\n✓ All {len(seen_aliases)} aliases are unique.")

    # Spot check: test the resolver
    print("\nResolver spot checks:")
    for test_input in ["lead pen", "markdowns", "PERFECT ORDERS", "ordenes", "does not exist"]:
        resolved = resolve_metric_name(test_input)
        print(f"  {test_input!r}  ->  {resolved!r}")

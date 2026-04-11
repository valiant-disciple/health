"""Neo4j knowledge graph queries."""
from __future__ import annotations
from neo4j import AsyncGraphDatabase
from config import settings
import structlog

log = structlog.get_logger()

_driver = None


def get_driver():
    global _driver
    if _driver is None:
        _driver = AsyncGraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
        )
    return _driver


async def get_drug_interactions(user_id: str, drug_names: list[str]) -> list[dict]:
    """Query drug-drug interactions from PrimeKG for a list of drug names."""
    if len(drug_names) < 2:
        return []
    driver = get_driver()
    async with driver.session(database=settings.NEO4J_DATABASE) as session:
        result = await session.run(
            """
            UNWIND $drugs AS drugName
            MATCH (d1:Drug) WHERE toLower(d1.name) = toLower(drugName)
            MATCH (d1)-[r:INTERACTS_WITH]->(d2:Drug)
            WHERE any(n IN $drugs WHERE toLower(d2.name) = toLower(n))
              AND r.severity IN ['major', 'moderate']
            RETURN d1.name AS drug1, d2.name AS drug2,
                   r.severity AS severity, r.mechanism AS mechanism
            ORDER BY r.severity
            """,
            drugs=drug_names,
        )
        return [dict(r) async for r in result]


async def get_drug_nutrient_depletions(drug_names: list[str]) -> list[dict]:
    """Query nutrients depleted by a list of medications."""
    driver = get_driver()
    async with driver.session(database=settings.NEO4J_DATABASE) as session:
        result = await session.run(
            """
            UNWIND $drugs AS drugName
            MATCH (d:Drug)-[r:DEPLETES]->(n:Nutrient)
            WHERE toLower(d.name) = toLower(drugName)
            RETURN d.name AS drug, n.name AS nutrient,
                   r.mechanism AS mechanism, r.clinical_significance AS significance
            """,
            drugs=drug_names,
        )
        return [dict(r) async for r in result]


async def get_conditions_affecting_biomarker(loinc_code: str) -> list[dict]:
    """Which conditions commonly elevate or reduce this biomarker?"""
    driver = get_driver()
    async with driver.session(database=settings.NEO4J_DATABASE) as session:
        result = await session.run(
            """
            MATCH (b:Biomarker {code: $code})
            MATCH (c:Condition)-[:ELEVATES|REDUCES]->(b)
            RETURN c.name AS condition, c.icd10_code AS icd10
            LIMIT 10
            """,
            code=loinc_code,
        )
        return [dict(r) async for r in result]

"""
PrimeKG import script — seeds Neo4j AuraDB with biomedical knowledge graph.

Dataset: PrimeKG (Harvard, 2022)
Download: https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/IXA7BM
File needed: edges.csv (~500MB)

Usage:
  1. Download edges.csv and nodes.csv from above URL
  2. Place in infra/neo4j/seed/data/
  3. Set NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD in environment
  4. Run: python import_primekg.py

Estimated time: ~2 hours on AuraDB free tier (4M+ relationships)
"""
import os
import csv
import asyncio
from pathlib import Path
from neo4j import AsyncGraphDatabase

NEO4J_URI      = os.environ["NEO4J_URI"]
NEO4J_USER     = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ["NEO4J_PASSWORD"]

DATA_DIR = Path(__file__).parent / "data"
BATCH_SIZE = 500

# PrimeKG relation → our relationship type
RELATION_MAP = {
    "drug_drug":               "INTERACTS_WITH",
    "drug_disease":            "INDICATED_FOR",
    "drug_protein":            "TARGETS",
    "drug_effect/phenotype":   "CAUSES_SIDE_EFFECT",
    "disease_phenotype":       "HAS_PHENOTYPE",
    "disease_protein":         "INVOLVES_PROTEIN",
    "disease_disease":         "RELATED_TO",
    "protein_protein":         "INTERACTS_WITH",
    "gene_phenotype":          "ASSOCIATED_WITH",
    "exposure_disease":        "INCREASES_RISK_OF",
    "exposure_protein":        "AFFECTS",
    "anatomy_protein_present": "EXPRESSED_IN",
}

# PrimeKG node type → our label
NODE_TYPE_MAP = {
    "drug":      "Drug",
    "disease":   "Condition",
    "protein":   "Protein",
    "gene":      "Gene",
    "effect/phenotype": "Phenotype",
    "anatomy":   "Anatomy",
    "pathway":   "Pathway",
    "exposure":  "Exposure",
    "cellular_component": "CellularComponent",
    "molecular_function": "MolecularFunction",
    "biological_process": "BiologicalProcess",
}


async def create_constraints(session):
    """Create uniqueness constraints before import."""
    constraints = [
        "CREATE CONSTRAINT drug_id IF NOT EXISTS FOR (d:Drug) REQUIRE d.primekg_id IS UNIQUE",
        "CREATE CONSTRAINT condition_id IF NOT EXISTS FOR (c:Condition) REQUIRE c.primekg_id IS UNIQUE",
        "CREATE CONSTRAINT biomarker_code IF NOT EXISTS FOR (b:Biomarker) REQUIRE b.code IS UNIQUE",
        "CREATE CONSTRAINT user_id IF NOT EXISTS FOR (u:User) REQUIRE u.id IS UNIQUE",
    ]
    for constraint in constraints:
        await session.run(constraint)
    print("Constraints created.")


async def import_edges(session, batch: list):
    """Batch import edges with MERGE to avoid duplicates."""
    await session.run(
        """
        UNWIND $rows AS row
        MERGE (x {primekg_id: row.x_id, primekg_type: row.x_type})
          ON CREATE SET x.name = row.x_name
        MERGE (y {primekg_id: row.y_id, primekg_type: row.y_type})
          ON CREATE SET y.name = row.y_name
        WITH x, y, row
        CALL apoc.create.relationship(x, row.rel_type, {
          primekg_relation: row.relation,
          display_relation: row.display_relation
        }, y) YIELD rel
        RETURN count(rel)
        """,
        rows=batch,
    )


async def main():
    edges_file = DATA_DIR / "edges.csv"
    if not edges_file.exists():
        print(f"ERROR: {edges_file} not found.")
        print("Download from: https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/IXA7BM")
        return

    driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    async with driver.session() as session:
        await create_constraints(session)

        batch: list = []
        total = 0

        with open(edges_file, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rel_type = RELATION_MAP.get(row["relation"], "RELATED_TO")
                batch.append({
                    "relation":         row["relation"],
                    "display_relation": row["display_relation"],
                    "rel_type":         rel_type,
                    "x_id":             row["x_id"],
                    "x_type":           row["x_type"],
                    "x_name":           row["x_name"],
                    "y_id":             row["y_id"],
                    "y_type":           row["y_type"],
                    "y_name":           row["y_name"],
                })

                if len(batch) >= BATCH_SIZE:
                    await import_edges(session, batch)
                    total += len(batch)
                    batch = []
                    print(f"Imported {total:,} edges...", end="\r")

            if batch:
                await import_edges(session, batch)
                total += len(batch)

        print(f"\nImport complete: {total:,} edges.")

    await driver.close()


if __name__ == "__main__":
    asyncio.run(main())

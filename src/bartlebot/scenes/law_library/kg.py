from typing import Optional
import logging
from enum import StrEnum

from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from neo4j import GraphDatabase

from neomodel import (
    StructuredNode,
    StringProperty,
    IntegerProperty,
    UniqueIdProperty,
    RelationshipTo,
    RelationshipFrom,
    ZeroOrOne,
    ZeroOrMore,
)
from neo4j_graphrag.schema import get_schema

from lapidarist.patterns.knowledge_graph import (
    load_knowledge_graph,
    Reference,
    RelationLabel as lapidarist_RelationLabel,
)
from proscenium.core import Prop

from .doc_enrichments import LegalOpinionEnrichments

log = logging.getLogger(__name__)


class RelationLabel(StrEnum):
    AUTHORED_BY = "AUTHORED_BY"


class NodeLabel(StrEnum):
    CASE = "Case"
    JUDGE = "Judge"
    GEO = "Geo"
    COMPANY = "Company"
    CASE_REFERENCE = "CaseReference"
    JUDGE_REFERENCE = "JudgeReference"
    GEO_REFERENCE = "GeoReference"
    COMPANY_REFERENCE = "CompanyReference"


class Case(StructuredNode):
    uid = UniqueIdProperty()
    cited_as = StringProperty()

    name = StringProperty(required=True)
    reporter = StringProperty()
    volume = StringProperty()
    first_page = StringProperty()
    last_page = StringProperty()
    court = StringProperty()
    decision_date = StringProperty()
    docket_number = StringProperty()
    jurisdiction = StringProperty()
    hf_dataset_id = StringProperty()
    hf_dataset_index = IntegerProperty()

    authored_by = RelationshipTo(
        NodeLabel.JUDGE_REFERENCE, RelationLabel.AUTHORED_BY, cardinality=ZeroOrMore
    )
    referred_to_by = RelationshipFrom(
        NodeLabel.CASE_REFERENCE,
        lapidarist_RelationLabel.REFERS_TO,
        cardinality=ZeroOrMore,
    )
    judge_mentions = RelationshipTo(
        NodeLabel.JUDGE_REFERENCE,
        lapidarist_RelationLabel.MENTIONS,
        cardinality=ZeroOrMore,
    )
    case_mentions = RelationshipTo(
        NodeLabel.CASE_REFERENCE,
        lapidarist_RelationLabel.MENTIONS,
        cardinality=ZeroOrMore,
    )
    geo_mentions = RelationshipTo(
        NodeLabel.GEO_REFERENCE,
        lapidarist_RelationLabel.MENTIONS,
        cardinality=ZeroOrMore,
    )
    company_mentions = RelationshipTo(
        NodeLabel.COMPANY_REFERENCE,
        lapidarist_RelationLabel.MENTIONS,
        cardinality=ZeroOrMore,
    )


class Judge(StructuredNode):
    uid = UniqueIdProperty()
    name = StringProperty(unique_index=True, required=True)
    referred_to_by = RelationshipFrom(
        NodeLabel.JUDGE_REFERENCE,
        lapidarist_RelationLabel.REFERS_TO,
        cardinality=ZeroOrMore,
    )


class Geo(StructuredNode):
    uid = UniqueIdProperty()
    name = StringProperty(required=True)
    referred_to_by = RelationshipFrom(
        NodeLabel.GEO_REFERENCE,
        lapidarist_RelationLabel.REFERS_TO,
        cardinality=ZeroOrMore,
    )


class Company(StructuredNode):
    uid = UniqueIdProperty()
    name = StringProperty(required=True)
    referred_to_by = RelationshipFrom(
        NodeLabel.COMPANY_REFERENCE,
        lapidarist_RelationLabel.REFERS_TO,
        cardinality=ZeroOrMore,
    )


class CaseReference(Reference):
    referent = RelationshipTo(
        Case, lapidarist_RelationLabel.REFERS_TO, cardinality=ZeroOrOne
    )
    referred_to_by = RelationshipFrom(
        NodeLabel.CASE_REFERENCE,
        lapidarist_RelationLabel.REFERS_TO,
        cardinality=ZeroOrMore,
    )


class JudgeReference(Reference):
    referent = RelationshipTo(
        Judge, lapidarist_RelationLabel.REFERS_TO, cardinality=ZeroOrOne
    )
    referred_to_by = RelationshipFrom(
        NodeLabel.JUDGE_REFERENCE,
        lapidarist_RelationLabel.REFERS_TO,
        cardinality=ZeroOrMore,
    )


class GeoReference(Reference):
    referent = RelationshipTo(
        Geo, lapidarist_RelationLabel.REFERS_TO, cardinality=ZeroOrOne
    )
    referred_to_by = RelationshipFrom(
        NodeLabel.GEO_REFERENCE,
        lapidarist_RelationLabel.REFERS_TO,
        cardinality=ZeroOrMore,
    )


class CompanyReference(Reference):
    referent = RelationshipTo(
        Company, lapidarist_RelationLabel.REFERS_TO, cardinality=ZeroOrOne
    )
    referred_to_by = RelationshipFrom(
        NodeLabel.COMPANY_REFERENCE,
        lapidarist_RelationLabel.REFERS_TO,
        cardinality=ZeroOrMore,
    )


def doc_enrichments_to_graph(enrichments: LegalOpinionEnrichments) -> None:

    case_node = Case(
        name=enrichments.name,
        reporter=enrichments.reporter,
        volume=enrichments.volume,
        first_page=enrichments.first_page,
        last_page=enrichments.last_page,
        cited_as=enrichments.cited_as,
        court=enrichments.court,
        decision_date=enrichments.decision_date,
        docket_number=enrichments.docket_number,
        jurisdiction=enrichments.jurisdiction,
        hf_dataset_id=enrichments.hf_dataset_id,
        hf_dataset_index=enrichments.hf_dataset_index,
    ).save()

    # Resolvable fields from the document metadata

    judge = enrichments.judges  # TODO split multiple judges upstream
    if len(judge) > 0:
        judge_ref = JudgeReference(text=judge).save()
        case_node.authored_by.connect(judge_ref)

    # TODO split into plaintiff(s) and defendant(s) upstream
    # parties = enrichments.parties
    # TODO case_node.involves.connect(PartyReference(text=parties))

    # Fields extracted from the text with LLM:

    for judgeref in enrichments.judgerefs:
        case_node.judge_mentions.connect(JudgeReference(text=judgeref).save())

    for caseref in enrichments.caserefs:
        case_node.case_mentions.connect(CaseReference(text=caseref).save())

    for georef in enrichments.georefs:
        case_node.geo_mentions.connect(GeoReference(text=georef).save())

    for companyref in enrichments.companyrefs:
        case_node.company_mentions.connect(CompanyReference(text=companyref).save())


class CaseLawKnowledgeGraph(Prop):
    """
    A knowledge graph for case law documents, built from enriched case law documents."""

    def __init__(
        self,
        input_path: Path,
        neo4j_uri: str,
        neo4j_username: str,
        neo4j_password: str,
        console: Optional[Console] = None,
    ) -> None:
        super().__init__(console=console)
        self.input_path = input_path
        self.neo4j_uri = neo4j_uri
        self.neo4j_username = neo4j_username
        self.neo4j_password = neo4j_password

    def already_built(self) -> bool:

        num_nodes = 0
        driver = GraphDatabase.driver(
            self.neo4j_uri, auth=(self.neo4j_username, self.neo4j_password)
        )
        try:
            with driver.session() as session:
                num_nodes = (
                    session.run("MATCH (n) RETURN COUNT(n) AS cnt").single().value()
                )
        finally:
            driver.close()

        if num_nodes > 0:
            log.info(
                "Knowledge graph already exists at %s and has at least one node. Considering it built.",
                self.neo4j_uri,
            )
            return True

        return False

    def build(self) -> None:

        driver = GraphDatabase.driver(
            self.neo4j_uri, auth=(self.neo4j_username, self.neo4j_password)
        )

        try:
            load_knowledge_graph(
                driver,
                self.input_path,
                LegalOpinionEnrichments,
                doc_enrichments_to_graph,
            )
        finally:
            driver.close()

    def display_knowledge_graph(self) -> None:

        if self.console is None:
            log.error("No console provided for displaying the knowledge graph.")
            return

        driver = GraphDatabase.driver(
            self.neo4j_uri, auth=(self.neo4j_username, self.neo4j_password)
        )

        with driver.session() as session:

            schema = get_schema(driver)
            self.console.print(Panel(schema, title="Graph Schema"))

            cases_result = session.run("MATCH (n:Case) RETURN properties(n) AS p")
            cases_table = Table(title="Cases", show_lines=False)
            cases_table.add_column("Properties", justify="left")
            for case_record in cases_result:
                cases_table.add_row(str(case_record["p"]))
            self.console.print(cases_table)

            caserefs_result = session.run(
                "MATCH (n:CaseReference) RETURN n.text AS text"
            )
            caserefs_table = Table(title="CaseReference", show_lines=False)
            caserefs_table.add_column("Text", justify="left")
            for caseref_record in caserefs_result:
                caserefs_table.add_row(caseref_record["text"])
            self.console.print(caserefs_table)

            judgerefs_result = session.run(
                "MATCH (n:JudgeReference) RETURN n.text AS text"
            )
            judgerefs_table = Table(title="JudgeReferences", show_lines=False)
            judgerefs_table.add_column("Text", justify="left")
            for judgeref_record in judgerefs_result:
                judgerefs_table.add_row(judgeref_record["text"])
            self.console.print(judgerefs_table)

            georefs_result = session.run("MATCH (n:GeoReference) RETURN n.text AS text")
            georefs_table = Table(title="GeoReferences", show_lines=False)
            georefs_table.add_column("Text", justify="left")
            for georef_record in georefs_result:
                georefs_table.add_row(georef_record["text"])
            self.console.print(georefs_table)

            companyrefs_result = session.run(
                "MATCH (n:CompanyReference) RETURN n.text AS text"
            )
            companyrefs_table = Table(title="CompanyReferences", show_lines=False)
            companyrefs_table.add_column("Text", justify="left")
            for companyref_record in companyrefs_result:
                companyrefs_table.add_row(companyref_record["text"])
            self.console.print(companyrefs_table)

        driver.close()

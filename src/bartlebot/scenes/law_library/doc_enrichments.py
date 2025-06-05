from typing import List, Optional
import logging
from pydantic import BaseModel, Field

from rich.console import Console
from rich.progress import Progress
from pathlib import Path
from langchain_core.documents.base import Document
from aisuite import Client as AISuiteClient

from eyecite import get_citations
from eyecite.models import CitationBase

from lapidarist.read import retrieve_documents
from lapidarist.extract import partial_formatter
from lapidarist.extract import raw_extraction_template
from lapidarist.document_enricher import make_extract_from_document_chunks
from lapidarist.document_enricher import enrich_document

from proscenium import Prop

from .docs import doc_as_rich

log = logging.getLogger(__name__)


class LegalOpinionChunkExtractions(BaseModel):
    """
    The judge names, geographic locations, and company names mentioned in a chunk of a legal opinion.
    """

    judge_names: list[str] = Field(
        description="A list of the judge names in the text. For example: ['Judge John Doe', 'Judge Jane Smith']"
    )

    geographic_locations: list[str] = Field(
        description="A list of the geographic locations in the text. For example: ['New Hampshire', 'Portland, Maine', 'Elm Street']"
    )

    company_names: list[str] = Field(
        description="A list of the company names in the text. For example: ['Acme Corp', 'IBM', 'Bob's Auto Repair']"
    )


class LegalOpinionEnrichments(BaseModel):
    """
    Enrichments for a legal opinion document.
    """

    # Fields that come directly from the document metadata
    name: str = Field(description="opinion identifier; name abbreviation")
    reporter: str = Field(description="name of the publising reporter")
    volume: str = Field(description="volume number of the reporter")
    first_page: str = Field(description="first page number of the opinion")
    last_page: str = Field(description="last page number of the opinion")
    cited_as: str = Field(description="how the opinion is cited")
    court: str = Field(description="name of the court")
    decision_date: str = Field(description="date of the decision")
    docket_number: str = Field(description="docket number of the case")
    jurisdiction: str = Field(description="jurisdiction of the case")
    judges: str = Field(description="authoring judges")
    parties: str = Field(description="parties in the case")
    # TODO word_count, char_count, last_updated, provenance, id

    # Extracted from the text without LLM
    caserefs: list[str] = Field(
        description="A list of the legal citations in the text.  For example: ['123 F.3d 456', '456 F.3d 789']"
    )

    # Extracted from the text with LLM
    judgerefs: list[str] = Field(
        description="A list of the judge names mentioned in the text. For example: ['Judge John Doe', 'Judge Jane Smith']"
    )
    georefs: list[str] = Field(
        description="A list of the geographic locations mentioned in the text. For example: ['New Hampshire', 'Portland, Maine', 'Elm Street']"
    )
    companyrefs: list[str] = Field(
        description="A list of the company names mentioned in the text. For example: ['Acme Corp', 'IBM', 'Bob's Auto Repair']"
    )

    # Denoted by Proscenium framework
    hf_dataset_id: str = Field(description="id of the dataset in HF")
    hf_dataset_index: int = Field(description="index of the document in the HF dataset")


def doc_enrichments(
    doc: Document, chunk_extracts: list[LegalOpinionChunkExtractions]
) -> LegalOpinionEnrichments:

    citations: List[CitationBase] = get_citations(doc.page_content)

    # merge information from all chunks
    judgerefs = []
    georefs = []
    companyrefs = []
    for chunk_extract in chunk_extracts:
        if chunk_extract.__dict__.get("judge_names") is not None:
            judgerefs.extend(chunk_extract.judge_names)
        if chunk_extract.__dict__.get("geographic_locations") is not None:
            georefs.extend(chunk_extract.geographic_locations)
        if chunk_extract.__dict__.get("company_names") is not None:
            companyrefs.extend(chunk_extract.company_names)

    logging.info(doc.metadata)

    enrichments = LegalOpinionEnrichments(
        name=doc.metadata["name_abbreviation"],
        reporter=doc.metadata["reporter"],
        volume=doc.metadata["volume"],
        first_page=str(doc.metadata["first_page"]),
        last_page=str(doc.metadata["last_page"]),
        cited_as=doc.metadata["citations"],
        court=doc.metadata["court"],
        decision_date=doc.metadata["decision_date"],
        docket_number=doc.metadata["docket_number"],
        jurisdiction=doc.metadata["jurisdiction"],
        judges=doc.metadata["judges"],
        parties=doc.metadata["parties"],
        caserefs=[c.matched_text() for c in citations],
        judgerefs=judgerefs,
        georefs=georefs,
        companyrefs=companyrefs,
        hf_dataset_id=doc.metadata["hf_dataset_id"],
        hf_dataset_index=int(doc.metadata["hf_dataset_index"]),
    )

    return enrichments


chunk_extraction_template = partial_formatter.format(
    raw_extraction_template, extraction_description=LegalOpinionChunkExtractions.__doc__
)


class DocumentEnrichments(Prop):
    """
    Enrichments of case law documents from CAP, produced from by open-source libraries and large language models.
    """

    def __init__(
        self,
        hf_dataset_ids: List[str],
        hf_dataset_column: str,
        docs_per_dataset: int,
        chat_completion_client: AISuiteClient,
        output: Path,
        extraction_model_id: str,
        delay: float,
        console: Optional[Console] = None,
    ):
        super().__init__(console)
        self.hf_dataset_ids = hf_dataset_ids
        self.hf_dataset_column = hf_dataset_column
        self.docs_per_dataset = docs_per_dataset
        self.chat_completion_client = chat_completion_client
        self.output = output
        self.extraction_model_id = extraction_model_id
        self.delay = delay

    def build(self, force: bool = False):

        if self.output.exists() and not force:
            logging.info(
                f"Output file {self.output} already exists.",
            )
            return

        docs = retrieve_documents(
            hf_dataset_ids=self.hf_dataset_ids,
            hf_dataset_column=self.hf_dataset_column,
            docs_per_dataset=self.docs_per_dataset,
        )

        extract_from_opinion_chunks = make_extract_from_document_chunks(
            doc_as_rich,
            self.chat_completion_client,
            self.extraction_model_id,
            chunk_extraction_template,
            LegalOpinionChunkExtractions,
            delay=10.0,
            console=self.console,
        )

        with Progress() as progress:

            task_enrich = progress.add_task(
                "[green]Enriching documents...", total=len(docs)
            )

            with open(self.output, "wt") as f:

                for doc in docs:

                    enrichments_json = enrich_document(
                        doc, extract_from_opinion_chunks, doc_enrichments
                    )
                    f.write(enrichments_json + "\n")

                    progress.update(task_enrich, advance=1)

            log.info("Wrote document enrichments to %s", self.output)

        assert (
            self.output.exists()
        ), f"Expected the enrichment file {self.output} to be created."

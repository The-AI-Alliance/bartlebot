from typing import Optional, Generator

import logging
import json
from rich.console import Console
from rich.panel import Panel
from uuid import UUID
from pydantic import BaseModel, Field
from langchain_core.documents.base import Document

from neo4j import Driver
from neo4j.graph import Node, Relationship
from neo4j_graphrag.schema import get_schema
from neomodel import db
from eyecite import get_citations

from lapidarist.verbs.extract import partial_formatter
from lapidarist.verbs.extract import extraction_system_prompt
from lapidarist.verbs.extract import raw_extraction_template
from lapidarist.verbs.vector_database import vector_db

from proscenium.core import Character
from proscenium.core import control_flow_system_prompt
from proscenium.core import WantsToHandleResponse
from proscenium.verbs.complete import complete_simple
from proscenium.patterns.graph_rag import query_to_prompts

from .docs import retrieve_document
from .docs import topic

log = logging.getLogger(__name__)


def neo4j_to_python(value):

    if isinstance(value, Node):
        return {
            "id": value.id,
            "labels": list(value.labels),
            "props": dict(value),
        }
    if isinstance(value, Relationship):
        return {
            "id": value.id,
            "type": value.type,
            "start": value.start_node.id,
            "end": value.end_node.id,
            "props": dict(value),
        }

    if isinstance(value, list):
        return [neo4j_to_python(x) for x in value]

    if isinstance(value, dict):
        return {k: neo4j_to_python(v) for k, v in value.items()}

    return value


user_prompt = f"What is your question about {topic}?"

# default_question = "How has Judge Kenison used Ballou v. Ballou to rule on cases?"
default_question = "How has 291 A.2d 605 been used in NH caselaw?"

# TODO include the graph schema in `wants_to_handle_template`

wants_to_handle_template = """\
The text below is a user-posted message to a chat channel.
Determine if you, the AI assistant equipped with a knowledge graph derived U.S. case law
might be able to find an answer to the user's question.
State a boolean value for whether you want to handle the message,
expressed in the specified JSON response format.
Only answer in JSON.

The user-posted message is:

{text}
"""


class QueryExtractions(BaseModel):
    """
    The judge names mentioned in the user query.
    """

    judge_names: list[str] = Field(
        description="A list of the judge names in the user query. For example: ['Judge John Doe', 'Judge Jane Smith']",
    )

    # caserefs: list[str] = Field(description = "A list of the legal citations in the query.  For example: `123 F.3d 456`")


query_extraction_template = partial_formatter.format(
    raw_extraction_template, extraction_description=QueryExtractions.__doc__
)


class LegalQueryContext(BaseModel):

    graph_results: list = Field(
        description="The retrieved knowledge graph records that are relevant to the question."
    )
    documents: dict[str, Document] = Field(
        description="The retrieved documents that are relevant to the question."
    )
    query: str = Field(description="The original question asked by the user.")
    # caserefs: list[str] = Field(description = "A list of the legal citations in the text.  For example: `123 F.3d 456`")


generation_system_prompt = "You are a helpful law librarian"

graphrag_prompt_template = """
The following is a list of graph records that are relevant to the question.

{graph_results}

The following documents are relevant to the question:

{document_text}

Question:

{question}
"""

example_question = "Who does John know?"

example_cypher = """
MATCH (p:Person {name: 'John'})-[:KNOWS]->(x:Person)
RETURN x
"""

raw_cypher_generation_template = """
Given a graph schema and a natural language query, generate an equivalent
cypher query using only the nodes and relationships present in the graph schema.
Return only valid cypher with no other text.

For example, if the graph schema has a node label `Person` and a relationship
`KNOWS`, and the natural langauge query is "{example_question}", then
the cypher query would be:

{example_cypher}

The given graph schema is:
{schema}

The given natural language query is:
{query}
"""


class LawLibrarian(Character):
    """
    A law librarian that can answer questions about case law."""

    def __init__(
        self,
        driver: Driver,
        milvus_uri: str,
        query_extraction_model_id: str,
        control_flow_model_id: str,
        generation_model_id: str,
        admin_channel_id: str,
        console: Optional[Console] = None,
    ):
        super().__init__(admin_channel_id=admin_channel_id)
        self.driver = driver
        db.set_connection(driver=driver)
        self.milvus_uri = milvus_uri
        self.query_extraction_model_id = query_extraction_model_id
        self.control_flow_model_id = control_flow_model_id
        self.generation_model_id = generation_model_id
        self.console = console

        self.graph_schema = get_schema(driver)

    def wants_to_handle(self, channel_id: str, speaker_id: str, utterance: str) -> bool:

        log.info("handle? channel_id = %s, speaker_id = %s", channel_id, speaker_id)

        response = complete_simple(
            model_id=self.control_flow_model_id,
            system_prompt=control_flow_system_prompt,
            user_prompt=wants_to_handle_template.format(text=utterance),
            response_format={
                "type": "json_object",
                "schema": WantsToHandleResponse.model_json_schema(),
            },
        )

        try:
            response_json = json.loads(response)
            result_message = WantsToHandleResponse(**response_json)
            log.info("wants_to_handle: result = %s", result_message.wants_to_handle)
            return result_message.wants_to_handle

        except Exception as e:

            log.error("Exception: %s", e)

    def query_extract(
        self,
        query: str,
        query_extraction_model_id: str,
        console: Optional[Console] = None,
    ) -> QueryExtractions:

        user_prompt = query_extraction_template.format(text=query)

        if console is not None:
            console.print(Panel(user_prompt, title="Query Extraction Prompt"))

        extract = complete_simple(
            query_extraction_model_id,
            extraction_system_prompt,
            user_prompt,
            response_format={
                "type": "json_object",
                "schema": QueryExtractions.model_json_schema(),
            },
            console=console,
        )

        if console is not None:
            console.print(Panel(str(extract), title="Query Extraction String"))

        try:

            qe_json = json.loads(extract)
            result = QueryExtractions(**qe_json)
            return result

        except Exception as e:

            log.error("query_extract: Exception: %s", e)

        return None

    def query_extract_to_graph(
        self,
        query: str,
        query_id: UUID,
        qe: QueryExtractions,
        driver: Driver,
    ) -> None:

        with driver.session() as session:

            # TODO manage the query logging in a separate namespace from the
            # domain graph
            query_save_result = session.run(
                "CREATE (:Query {id: $query_id, value: $value})",
                query_id=str(query_id),
                value=query,
            )
            log.info(f"Saved query {query} with id {query_id} to the graph")
            log.info(query_save_result.consume())

            for judgeref in qe.judge_names:
                session.run(
                    "MATCH (q:Query {id: $query_id}) "
                    + "MERGE (q)-[:mentions]->(:JudgeRef {text: $judgeref, confidence: $confidence})",
                    query_id=str(query_id),
                    judgeref=judgeref,
                    confidence=0.6,
                )

    def natural_language_query_to_cypher(self, query: str) -> str:

        cypher_generation_prompt = raw_cypher_generation_template.format(
            example_question=example_question,
            example_cypher=example_cypher,
            schema=self.graph_schema,
            query=query,
        )

        return complete_simple(
            self.query_extraction_model_id,  # TODO rename this
            "You are a function that converts natural langauge into cypher queries. Return only valid cypher.",
            cypher_generation_prompt,
            console=self.console,
        )

    def old(
        self, qe: QueryExtractions, query: str, console: Optional[Console] = None
    ) -> None:
        caserefs = get_citations(query)

        case_judgeref_clauses = []

        if qe is not None:
            # TODO judgeref_match = find_matching_objects(vector_db_client, judgeref, judge_resolver)
            case_judgeref_clauses = [
                f"MATCH (c:Case)-[:MENTIONS]->(:JudgeReference {{text: '{judgeref}'}})"
                for judgeref in qe.judge_names
            ]

        case_caseref_clauses = [
            # TODO caseref_match = find_matching_objects(vector_db_client, caseref, case_resolver)
            f"MATCH (c:Case)-[:MENTIONS]->(:CaseReference {{text: '{caseref.matched_text()}'}})"
            for caseref in caserefs
        ]

        case_match_clauses = case_judgeref_clauses + case_caseref_clauses

        if len(case_match_clauses) == 0:
            log.warning("No case match clauses found")
            return None

        cypher = "\n".join(case_match_clauses) + "\nRETURN c.name AS name"

        if console is not None:
            console.print(Panel(cypher, title="Cypher Query"))

        log.info("Cypher query: %s", cypher)

    def query_extract_to_context(
        self,
        qe: QueryExtractions,
        query: str,
        driver: Driver,
        milvus_uri: str,
        console: Optional[Console] = None,
    ) -> LegalQueryContext:

        vector_db_client = vector_db(milvus_uri)

        try:

            cypher = self.natural_language_query_to_cypher(query)
            if console is not None:
                console.print(Panel(cypher, title="Cypher Query"))
            log.info("Cypher query: %s", cypher)

            graph_results = []
            with driver.session() as session:
                result = session.run(cypher)
                graph_results.extend(
                    [neo4j_to_python(record.data()) for record in result]
                )

            if console is not None:
                console.print(
                    Panel(json.dumps(graph_results), title="Graph Result Context")
                )
            log.info("Graph result context: %s", json.dumps(graph_results))

            documents = {}
            for graph_record in graph_results:
                log.info("Graph record: %s", graph_record)
                for k, v in graph_record.items():
                    if isinstance(v, dict):
                        if "hf_dataset_id" in v and "hf_dataset_index" in v:
                            hf_dataset_id = v["hf_dataset_id"]
                            hf_dataset_index = v["hf_dataset_index"]
                            log.info(
                                "Retrieving document %s from dataset %s",
                                hf_dataset_index,
                                hf_dataset_id,
                            )
                            documents[v["uid"]] = retrieve_document(
                                hf_dataset_id, hf_dataset_index
                            )

            context = LegalQueryContext(
                graph_results=graph_results,
                documents=documents,
                query=query,
            )
        finally:
            vector_db_client.close()

        return context

    def context_to_prompts(
        self,
        context: LegalQueryContext,
    ) -> tuple[str, str]:

        graph_results_text = "\n".join(json.dumps(r) for r in context.graph_results)

        document_text = "\n\n".join(
            [f"{id}\n{doc.page_content}" for id, doc in context.documents.items()]
        )

        user_prompt = graphrag_prompt_template.format(
            graph_results=graph_results_text,
            document_text=document_text,
            question=context.query,
        )

        return generation_system_prompt, user_prompt

    def handle(
        self, channel_id: str, speaker_id: str, utterance: str
    ) -> Generator[tuple[str, str], None, None]:

        prompts = query_to_prompts(
            utterance,
            self.query_extraction_model_id,
            self.milvus_uri,
            self.driver,
            self.query_extract,
            self.query_extract_to_graph,
            self.query_extract_to_context,
            self.context_to_prompts,
        )

        if prompts is None:

            yield channel_id, "Sorry, I'm not able to answer that question."

        else:

            yield channel_id, "I think I can help with that..."

            system_prompt, user_prompt = prompts

            response = complete_simple(
                self.generation_model_id, system_prompt, user_prompt
            )

            yield channel_id, response

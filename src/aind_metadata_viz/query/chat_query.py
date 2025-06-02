"""Complex query generation via chatbot"""

import param

import panel as pn
from aind_data_access_api.document_db import MetadataDbClient
from langchain import hub
from aind_metadata_viz.query.viewer import QueryViewer
from aind_metadata_viz.utils import FIXED_WIDTH
from tornado.ioloop import IOLoop
from aind_metadata_viz.query.prompt.cached_prompt import get_initial_messages

from langchain_aws.chat_models.bedrock import ChatBedrockConverse


BEDROCK_SONNET_3_7 = "us.anthropic.claude-sonnet-4-20250514-v1:0"
SONNET_3_7_LLM = ChatBedrockConverse(
    model=BEDROCK_SONNET_3_7,
    temperature=0,
    credentials_profile_name="bedrock-access"

)

API_GATEWAY_HOST = "api.allenneuraldynamics.org"
DATABASE = "metadata_index"
COLLECTION = "data_assets"

docdb_api_client = MetadataDbClient(
    host=API_GATEWAY_HOST,
    database=DATABASE,
    collection=COLLECTION,
)


def get_records(filter: dict = {}) -> dict:
    """
    Retrieves documents from MongoDB database using simple filters
    and projections.

    WHEN TO USE THIS FUNCTION:
    - For straightforward document retrieval based on specific criteria
    - When you need only a subset of fields from documents
    - When the query logic doesn't require multi-stage processing
    - For better performance with simpler queries

    NOT RECOMMENDED FOR:
    - Complex data transformations (use aggregation_retrieval instead)
    - Grouping operations or calculations across documents
    - Joining or relating data across collections

    Parameters
    ----------
    filter : dict
        MongoDB query filter to narrow down the documents to retrieve.
        Example: {"subject.sex": "Male"}
        If empty dict object, returns all documents.

    Returns
    -------
    list
        List of dictionary objects representing the matching documents.
        Each dictionary contains the requested fields based on the projection.

    """

    records = docdb_api_client.retrieve_docdb_records(filter_query=filter)

    return records


tools = [get_records]

prompt = hub.pull("eden19/entire_db_retrieval")
query_generator = SONNET_3_7_LLM.bind_tools(tools)
#query_generator_agent = prompt | query_generator


class ComplexQueryBuilder(param.Parameterized):
    """Complex query generation via chatbot"""

    # Store generated queries in a list
    queries = param.List(default=[])

    # Initialize variable for user's query
    user_query = param.String(default="", allow_None=True)

    # Tracking query generation
    query_in_progress = param.Boolean(default=False)

    # Initialize variable for generated MongoDB query
    current_mongodb_query = param.Dict(default={})

    def __init__(self, **params):
        super().__init__(**params)

        # Initialize query viewer
        self.query_viewer = QueryViewer({})

        # Text input for query
        self.typed_query = pn.widgets.TextInput(
            name="Text Input",
            placeholder="Enter your query here...",
            width=FIXED_WIDTH - 200,
        )
        self.typed_query.link(self, value="user_query")

        # Loading spinner
        self.spinner = pn.indicators.LoadingSpinner(
            value=False,  # Initially not spinning
            color="primary",
            size=50,
            name="Generating MongoDB query...",
        )

        # Query button
        self.query_button = pn.widgets.Button(
            name="Generate query",
            button_type="primary",
        )
        self.query_button.on_click(self.handle_query_click)

        # Content area that will display either spinner or results
        # Initially empty until a query is submitted
        self.content_area = pn.Column(pn.pane.Markdown(""))

        # Watcher invokes update_display function when query in progress value is changed
        self.param.watch(self.update_display, "query_in_progress")

    def options_panel(self):
        """Create the options panel for the query"""

        user_query_col = pn.Column(
            pn.Row(self.typed_query),
            width=FIXED_WIDTH - 150,
        )

        submit_col = pn.Column(
            self.query_button,
            width=100,
        )

        return pn.Row(user_query_col, submit_col)

    @staticmethod
    async def get_mongodb_query(user_query: str):
        """Get mongodb query asynchronously from LLM"""
        messages = get_initial_messages()
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": user_query,
                    }
                ]                       
            }
        )
        llm_response = await query_generator.ainvoke(messages)
        mongodb_query = llm_response.tool_calls[0]["args"]["filter"]
        return mongodb_query

    def handle_query_click(self, event):
        """Steps to take after submit button is clicked"""
        if not self.user_query:
            return

        # Query in progress updated, unable to submit another query while current answer is being generated
        self.query_in_progress = True
        self.query_button.loading = True
        self.query_button.disabled = True

        # Schedule the async function to run
        IOLoop.current().add_callback(self.async_process_query)

    async def async_process_query(self):
        """Process the query asynchronously"""
        try:
            mongodb_query = await self.get_mongodb_query(self.user_query)
            # Update class object
            self.current_mongodb_query = mongodb_query
            self.update_query_panel()
            self.queries = self.queries + [self.query_viewer.query_pane.object]
        except Exception as e:
            print(f"Error processing query: {e}")
        finally:
            # Reset UI state
            self.query_button.loading = False
            self.query_button.disabled = False
            self.query_in_progress = False

    def update_display(self, event):
        """Update the content area based on query progress state"""
        if self.query_in_progress:
            # Show spinner
            self.content_area.clear()
            self.spinner.value = True
            self.content_area.append(self.spinner)
        else:
            # Show query results
            self.spinner.value = False
            self.content_area.clear()
            self.content_area.append(self.query_viewer.panel())

    def update_query_panel(self):
        """Update the query panel content dynamically"""
        self.query_button.disabled = self.query_in_progress
        query_dict = {"_name": f"Chat query {len(self.queries) + 1}"}

        if self.current_mongodb_query:
            query_dict = {**query_dict, **self.current_mongodb_query}
            self.query_viewer.update(query_dict)
            self.query_button.name = "Submit query"
            self.query_button.button_type = "primary"
        else:
            # Check if this is the initial state (no user query yet)
            if not self.user_query:
                self.query_button.name = "Submit query"
                self.query_button.button_type = "primary"
                self.query_button.disabled = False
            else:
                # Only show error if user tried to submit an empty query
                self.query_button.name = "Cannot submit empty query"
                self.query_button.button_type = "danger"
                self.query_button.disabled = True

    def panel(self):
        """Return the full panel"""
        return pn.Column(
            self.options_panel(),
            pn.pane.Markdown("## Query"),
            self.content_area,  # This will show either spinner or results
            width=FIXED_WIDTH,
        )

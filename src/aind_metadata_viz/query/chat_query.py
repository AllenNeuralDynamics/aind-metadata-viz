"""Complex query generation via chatbot"""
import param


class ComplexQueryBuilder(param.Parameterized):
    """Complex query generation via chatbot"""

    queries = param.List(default=[])
